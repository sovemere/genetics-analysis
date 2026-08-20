"""The dashboard shell over HTTP (roadmap M4.5).

``tests/web/test_views.py`` owns the rules; this file owns the wiring — that the routes
resolve a run, that the four "nothing to show" states each produce a page rather than a
stack trace, and that the privacy split the page depends on is real in both directions.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genetics.engine.cards import KnowledgePack
from genetics.privacy import GenotypeLeakError
from genetics.qc.report import QCReport
from genetics.run.bundle import CARDS_NAME, MANIFEST_NAME, write_bundle
from genetics.run.store import RunListing
from genetics.testing.fixtures import FIXTURES, render_fixture
from genetics.web import WebConfig, create_app
from genetics.web.app import _environment
from genetics.web.views import QCBanner, RunOption, Shell, shell_for

LOCAL_BASE_URL = "http://127.0.0.1:8765"

SYNTHETIC_CARDS = Path(__file__).parents[1] / "fixtures" / "cards"
SPIKED_GENOTYPE = "AG"
SPIKE_INS = {
    "rs900000001": (7, 12345678, "A", "G"),
    "rs900000002": (24, 2655180, "T", "T"),
}


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def client(runs_root: Path) -> Iterator[TestClient]:
    config = WebConfig(runs_root=runs_root)
    with TestClient(create_app(config), base_url=LOCAL_BASE_URL) as running:
        yield running


@pytest.fixture
def saved(
    runs_root: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[object, ...],
) -> Path:
    """A readable bundle carrying one matched card, so the page has a genotype to not print."""
    return write_bundle(
        qc=sample_qc,
        cards=sample_cards,  # type: ignore[arg-type]
        pack=sample_pack,
        runs_root=runs_root,
        run_id="20260821T090000Z-aaaa1111",
        lock_path=runs_root / "absent.lock",
        tools_root=runs_root / "tools",
    )


@pytest.fixture
def interpreted(runs_root: Path, tmp_path: Path) -> Path:
    """A run produced by the real pipeline against an export that actually matches.

    The committed fixtures carry no spike-ins, so every interpretation card in them returns
    ``marker_absent`` — a dashboard developed against one would never render a populated
    section. See ``tests/run/test_pipeline.py``.
    """
    from genetics.run.pipeline import analyse, save

    base = next(spec for spec in FIXTURES if spec.name == "ancestry_v2_male.txt")
    export = tmp_path / "spiked.txt"
    export.write_text(
        render_fixture(replace(base, spike_ins=SPIKE_INS)), encoding="utf-8", newline="\n"
    )
    return save(analyse(export, knowledge_dir=SYNTHETIC_CARDS), runs_root=runs_root)


# ---------------------------------------------------------------------------
# Resolving a run
# ---------------------------------------------------------------------------


def test_the_index_opens_the_newest_readable_run(client: TestClient, saved: Path) -> None:
    body = client.get("/").text
    assert saved.name in body
    assert "Call rate" in body


def test_a_run_is_reachable_by_its_own_url(client: TestClient, saved: Path) -> None:
    """A URL per run is what makes one linkable, reloadable, and reachable with Back."""
    response = client.get(f"/runs/{saved.name}")
    assert response.status_code == 200
    assert saved.name in response.text


def test_the_newest_readable_run_is_preferred_over_a_newer_damaged_one(
    client: TestClient, saved: Path, runs_root: Path
) -> None:
    """Defaulting to the most recent *run* would open the dashboard on an error page for
    somebody whose last save happened to fail."""
    broken = runs_root / "20260821T100000Z-bbbb2222"
    broken.mkdir()
    (broken / MANIFEST_NAME).write_text("{ not json", encoding="utf-8")

    body = client.get("/").text
    assert saved.name in body
    assert "Call rate" in body, "the readable run should be the one displayed"


# ---------------------------------------------------------------------------
# The four states where there is nothing to show
# ---------------------------------------------------------------------------


def test_an_empty_store_renders_the_shell_and_says_it_is_empty(client: TestClient) -> None:
    """An empty dashboard must look empty rather than broken, so the nav renders anyway."""
    response = client.get("/")
    assert response.status_code == 200
    assert "No runs have been saved yet" in response.text
    assert "Ancestry" in response.text, "the nav renders with no run open"
    assert "genetics run --input" in response.text, "it says how to make one"


def test_an_unknown_run_id_is_a_page_not_a_crash(client: TestClient, saved: Path) -> None:
    response = client.get("/runs/20260101T000000Z-deadbeef")
    assert response.status_code == 200
    assert "is saved here" in response.text


@pytest.mark.parametrize("run_id", ["..", "../elsewhere", "a/b", "D:elsewhere"])
def test_a_run_id_that_is_not_a_plain_name_is_refused_with_a_page(
    client: TestClient, run_id: str
) -> None:
    """``check_run_id`` owns this check; the route's job is to not turn its refusal into a
    500. Asserted through the URL because that is where an id from outside arrives."""
    response = client.get(f"/runs/{run_id}")
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert "Nothing to show" in response.text


def test_a_damaged_bundle_explains_itself_rather_than_500ing(
    client: TestClient, saved: Path
) -> None:
    """The dashboard has to render the run that is worth looking at, which is the broken one."""
    (saved / CARDS_NAME).write_text("{ truncated", encoding="utf-8")

    response = client.get(f"/runs/{saved.name}")
    assert response.status_code == 200
    assert "Nothing to show" in response.text


def test_an_unusable_data_directory_is_reported_on_the_page(tmp_path: Path) -> None:
    """The state a person is most likely to be in when they first load this."""
    from genetics.paths import repo_root

    config = WebConfig(runs_root=repo_root() / "scratch_runs")
    with TestClient(create_app(config), base_url=LOCAL_BASE_URL) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Nothing to show" in response.text
    assert "inside the repository" in response.text


# ---------------------------------------------------------------------------
# Damaged and interrupted runs stay visible
# ---------------------------------------------------------------------------


def test_an_unopenable_run_is_still_listed(
    client: TestClient, saved: Path, runs_root: Path
) -> None:
    """Hiding it is how somebody concludes their analysis was deleted."""
    broken = runs_root / "20260821T100000Z-bbbb2222"
    broken.mkdir()
    (broken / MANIFEST_NAME).write_text("{ not json", encoding="utf-8")

    body = client.get("/").text
    assert broken.name in body
    assert "damaged" in body


def test_a_newer_format_run_is_offered_the_right_remedy(
    client: TestClient, saved: Path, runs_root: Path
) -> None:
    """Intact, and unreadable here. Calling that "damaged" sends someone looking for a
    backup when what they need is the version of the tool that wrote it -- the distinction
    ``RunStatus`` exists to preserve, thrown away by the page that reports it."""
    newer = runs_root / "20260821T120000Z-dddd4444"
    newer.mkdir()
    (newer / MANIFEST_NAME).write_text(
        json.dumps({"format_version": 99, "run_id": newer.name}), encoding="utf-8"
    )

    body = client.get("/").text
    assert newer.name in body
    assert "future-version" in body
    assert "the version of this tool that wrote it" in body
    assert "damaged" not in body, "an intact newer bundle must not be reported as damage"


def test_an_interrupted_save_is_named_on_the_page(
    client: TestClient, saved: Path, runs_root: Path
) -> None:
    staging = runs_root / ".incoming-20260821T110000Z-cccc3333"
    staging.mkdir()
    (staging / "qc.run.json").write_text("{}", encoding="utf-8")

    body = client.get("/").text
    assert "20260821T110000Z-cccc3333" in body
    assert "genetics runs prune" in body


# ---------------------------------------------------------------------------
# No silent empty sections, over HTTP
# ---------------------------------------------------------------------------


def test_all_thirteen_sections_appear_with_a_run_open(client: TestClient, saved: Path) -> None:
    body = client.get("/").text
    for title in ("Ancestry", "Physical health", "Psychometrics"):
        assert title in body
    # Escaped, because autoescape is on and a section title is text rather than markup.
    # Asserting the raw form here would have quietly required turning autoescape off.
    assert "Fitness &amp; physiology" in body


def test_an_unbuilt_section_names_its_milestone_on_the_page(
    client: TestClient, saved: Path
) -> None:
    body = client.get("/").text
    assert "Not built yet" in body
    assert "roadmap M5" in body, "the ancestry section should name the milestone that fills it"


def test_a_populated_section_points_at_the_command_that_reads_the_cards(
    client: TestClient, interpreted: Path
) -> None:
    """The card grid is M4.6. Until then the page says so and names what does work today."""
    body = client.get("/").text
    assert "M4.6" in body
    assert f"genetics runs show {interpreted.name}" in body


def _empty_listing() -> RunListing:
    return RunListing(root=Path("/runs"), runs=(), incomplete=(), verified=False)


def _render_one(partial: str, shell: Shell) -> str:
    """Render one scanned partial in isolation, through the app's own environment.

    Its own environment rather than a fresh one, so this exercises the autoescape and
    ``StrictUndefined`` settings the real page renders under -- a second Environment here
    would be a second configuration to keep in step.
    """
    return _environment().get_template(partial).render({"shell": shell})


def _render_banner(banner: QCBanner) -> str:
    shell = shell_for(_empty_listing(), None, problem="none")
    return _render_one("_qcbanner.html", replace(shell, banner=banner))


def _render_selector(option: RunOption) -> str:
    shell = shell_for(_empty_listing(), None, problem="none")
    return _render_one("_runselector.html", replace(shell, runs=(option,)))


def test_every_fact_the_banner_collects_reaches_the_page() -> None:
    """A field in the view model with no outlet in the template is invisible.

    Written after exactly that: ``RunOption`` carried ``vendor`` that the selector never
    rendered, and it surfaced only because a privacy mutation test poisoned that field and
    nothing leaked -- a passing test proving the guard untested rather than the code safe.
    The same slip had also left ``het_haploid_calls`` and ``duplicate_rows`` collected and
    unshown.

    Checked by **rendering**, not by grepping the template for field names: two fields reach
    the page through formatting properties (``markers_display``, ``call_rate_percent``), so a
    name check reports them missing while they are on screen -- and would be "fixed" by
    weakening it into something that catches nothing. The expected-output map is asserted to
    cover the dataclass, so adding a field forces a decision about how it renders rather than
    letting it default to invisible.
    """
    from dataclasses import fields

    cases: dict[str, tuple[object, str]] = {
        "vendor": ("acmedna_v9", "acmedna_v9"),
        "source_path": ("Export.txt", "Export.txt"),
        "total_markers": (123456, "123,456"),
        "call_rate": (0.5, "50.00%"),
        "inferred_sex": ("female", "female"),
        "het_haploid_calls": (7, "7"),
        "duplicate_rows": (656, "656"),
        "build_verdict": ("consistent", "consistent"),
        "warnings": (("a distinctive warning",), "a distinctive warning"),
    }
    assert set(cases) == {f.name for f in fields(QCBanner)}, (
        "a QCBanner field has no expected rendering; decide how it appears on the page"
    )

    banner = QCBanner(**{name: value for name, (value, _) in cases.items()})  # type: ignore[arg-type]
    markup = _render_banner(banner)
    for name, (_, expected) in cases.items():
        assert expected in markup, f"QCBanner.{name} is collected but never rendered"


def test_every_fact_the_run_selector_collects_reaches_the_page() -> None:
    """The counterpart, over ``RunOption``. See above for why this exists.

    ``selectable`` is excluded from the value check and asserted separately: it is not text
    on the page, it is the ``disabled`` attribute and the notice block.
    """
    from dataclasses import fields

    cases: dict[str, tuple[object, str]] = {
        "run_id": ("20260821T090000Z-aaaa1111", "20260821T090000Z-aaaa1111"),
        "created_at": ("2026-08-21T09:00:00Z", "2026-08-21T09:00:00Z"),
        "status": ("damaged", "damaged"),
        "vendor": ("acmedna_v9", "acmedna_v9"),
        "card_count": (43, "43"),
        "with_interpretation": (26, "26"),
        "detail": ("a distinctive reason", "a distinctive reason"),
    }
    assert set(cases) | {"selectable"} == {f.name for f in fields(RunOption)}, (
        "a RunOption field has no expected rendering; decide how it appears on the page"
    )

    option = RunOption(
        selectable=False,
        **{name: value for name, (value, _) in cases.items()},  # type: ignore[arg-type]
    )
    markup = _render_selector(option)
    for name, (_, expected) in cases.items():
        assert expected in markup, f"RunOption.{name} is collected but never rendered"
    assert "disabled" in markup, "an unselectable run must be marked as such"


def test_the_real_qc_facts_appear_on_the_page(client: TestClient, saved: Path) -> None:
    """The template check above proves the field is referenced; this proves it renders."""
    body = client.get("/").text
    assert "Het at haploid loci" in body
    assert "Duplicate rows" in body


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_the_shell_prints_no_genotype_even_when_the_run_has_matches(
    client: TestClient, interpreted: Path
) -> None:
    """The shell renders counts; card faces are M4.6. Asserted against a run that *did*
    match, since a run where nothing matched would pass with the guard removed."""
    body = client.get("/").text
    assert SPIKED_GENOTYPE not in body
    assert "1/1" in body, "the counts are there; it is the calls that are not"


@pytest.mark.privacy
@pytest.mark.parametrize("partial", ["_runselector.html", "_qcbanner.html"])
def test_each_scanned_partial_is_actually_scanned(
    client: TestClient, saved: Path, monkeypatch: pytest.MonkeyPatch, partial: str
) -> None:
    """Parametrised so dropping either scan fails a test.

    Poisoning goes in through the *stored manifest*, not through a patched function: the
    banner and the selector are built from what a bundle says, and a bundle written by
    another version is exactly the case the scan exists for.
    """
    manifest = json.loads((saved / MANIFEST_NAME).read_text(encoding="utf-8"))
    dirty = "\t".join(("rs4988235", "2", "136608646", "A", "G"))
    if partial == "_runselector.html":
        # `vendor` reaches the selector rows via RunSummary.
        manifest["provenance"]["input"]["vendor"] = dirty
    else:
        manifest["provenance"]["input"]["vendor"] = "clean"
    (saved / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    if partial == "_qcbanner.html":
        # The banner reads the QC payload, so poison that instead -- and refresh the digest,
        # or the read fails on integrity before the render is ever reached.
        from genetics.run import bundle as bundle_mod

        qc = json.loads((saved / "qc.run.json").read_text(encoding="utf-8"))
        qc["warnings"] = [dirty]
        text = json.dumps(qc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        (saved / "qc.run.json").write_text(text, encoding="utf-8", newline="")
        manifest = json.loads((saved / MANIFEST_NAME).read_text(encoding="utf-8"))
        manifest["files"]["qc.run.json"] = bundle_mod._digest(saved / "qc.run.json")
        (saved / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GenotypeLeakError):
        client.get("/")


def test_the_dashboard_serves_without_touching_the_network(client: TestClient, saved: Path) -> None:
    from genetics.testing.network import guard_is_active

    assert guard_is_active(), "the offline guard is not installed; this would prove nothing"
    assert client.get("/").status_code == 200
    assert client.get(f"/runs/{saved.name}").status_code == 200
