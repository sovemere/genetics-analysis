"""The dashboard shell over HTTP (roadmap M4.5).

``tests/web/test_views.py`` owns the rules; this file owns the wiring — that the routes
resolve a run, that the four "nothing to show" states each produce a page rather than a
stack trace, and that the privacy split the page depends on is real in both directions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genetics.engine.cards import KnowledgePack
from genetics.privacy import GenotypeLeakError
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    CARDS_NAME,
    MANIFEST_NAME,
    RunBundle,
    StoredCard,
    write_bundle,
)
from genetics.run.store import RunListing
from genetics.testing.fixtures import FIXTURES, render_fixture
from genetics.web import STATIC_DIR, WebConfig, create_app, views
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


def test_a_populated_section_renders_its_cards(client: TestClient, interpreted: Path) -> None:
    """M4.5's placeholder said the grid was not built yet and named the CLI instead. M4.6
    replaced it, so this asserts the replacement rather than being deleted with it."""
    body = client.get("/").text
    assert "Synthetic dominant trait" in body
    assert f"/runs/{interpreted.name}/cards/synthetic_dominant_trait" in body


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
        "duplicate_rsids": (656, "656"),
        "duplicate_positions": (655, "655"),
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


def test_the_real_qc_facts_appear_on_the_page(
    client: TestClient, saved: Path, sample_qc: QCReport
) -> None:
    """The template check above proves the field is referenced; this proves it *renders a
    real value*.

    Asserting only the labels was what let a field reading a key no QC payload contains sit
    on the page showing "-" — the label was there, so the test passed, and the dash read as
    "not measured" rather than "never wired up".
    """
    body = client.get("/").text
    assert "Het at haploid loci" in body
    assert "Duplicate rsIDs" in body
    assert "Duplicate positions" in body
    assert f"{sample_qc.call_rates.total_markers:,}" in body
    assert f"<dd>{sample_qc.duplicates.duplicate_rsids}</dd>" in body


def test_a_renamed_bundle_is_addressed_by_its_directory_name(
    client: TestClient, saved: Path
) -> None:
    """The directory name wins, because it is what `delete` and `load` resolve against.

    ``summarise_run`` settled that; the shell took the manifest's ``run_id`` instead, so a
    renamed bundle rendered with no option marked current and told the reader to run
    `genetics runs show <manifest id>` — advice that fails for the one run it is about.
    """
    renamed = saved.parent / "renamed-run"
    saved.rename(renamed)

    body = client.get("/runs/renamed-run").text
    assert "renamed-run" in body
    assert 'value="renamed-run"' in body
    assert "selected" in body, "the open run must be the one the selector marks current"


def test_the_card_total_counts_cards_the_nav_cannot_place(client: TestClient, saved: Path) -> None:
    """Two numbers on one page must not disagree in silence.

    The selector shows the manifest's ``card_count``; the banner summed the thirteen known
    sections. A bundle carrying a newer engine's section made the second smaller than the
    first, with the unknown-section notice explaining only that those cards are absent from
    the *navigation*.
    """
    from genetics.web.views import section_views, shell_for

    unplaceable = _card_in_section("epigenetics")
    shell = shell_for(_empty_listing(), _bundle_with((unplaceable,)))

    assert shell.card_count == 1
    assert shell.placed_cards == 0
    assert sum(v.card_count for v in section_views((unplaceable,))) == 0

    markup = _render_one("_qcbanner.html", shell)
    assert "not placed in any section below" in markup


def _card_in_section(section: str) -> StoredCard:
    return StoredCard(
        card_id="future",
        section=section,
        kind="interpretation",
        title="From a newer engine",
        status="matched",
        summary="s",
        detail="d",
        gene=None,
        impossibility_reason=None,
        confidence_tier="moderate",
        variant=None,
        match={},
        confidence=None,
        evidence=None,
        observation=None,
        frequencies=(),
        confidence_frequency=None,
        citations=(),
        authored_caveats=(),
        computed_caveats=(),
    )


def _bundle_with(cards: tuple[StoredCard, ...]) -> RunBundle:
    return RunBundle(
        path=Path("/runs/r1"),
        run_id="r1",
        format_version=BUNDLE_FORMAT_VERSION,
        created_at="2026-08-21T00:00:00Z",
        provenance={},
        qc={},
        cards=cards,
    )


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
@pytest.mark.parametrize("partial", ["_runselector.html", "_qcbanner.html"])
def test_the_scanned_regions_hold_no_genotype_on_a_run_that_matched(
    client: TestClient, interpreted: Path, partial: str
) -> None:
    """The banner and the selector carry no call, on a run where there is a call to carry.

    The M4.5 form of this test asserted the *whole page* held no genotype, which was true
    then and is deliberately false now: M4.6 puts the reader's call on every card face by
    design (AGENTS.md 0.1A wants the finding and its tier before the click). Deleting the
    test along with the property would have removed the coverage; narrowing it to the two
    regions that are still genotype-free keeps it, and keeps it where the guard actually is.

    Asserted against a run that *did* match, since a run where nothing matched would pass
    with the whole mechanism removed. ``test_the_card_face_does_state_the_genotype`` is the
    other half: without it, this could be satisfied by a page that showed nothing at all.
    """
    from genetics.run import store

    listing = store.list_runs(interpreted.parent)
    bundle = store.load_run(interpreted.name, interpreted.parent)
    shell = shell_for(listing, bundle)
    assert any(card.status == "matched" for card in bundle.cards), "nothing matched to hide"

    markup = _render_one(partial, shell)
    assert SPIKED_GENOTYPE not in markup


@pytest.mark.privacy
def test_the_card_face_does_state_the_genotype(client: TestClient, interpreted: Path) -> None:
    """The other direction, and it is a requirement rather than a tolerated leak.

    AGENTS.md 0.1A puts the finding and its confidence tier on the card face, in the summary
    view, before the reader clicks through — and a matched card's summary is a sentence
    about the reader's own call. Asserting it is present is what stops somebody "fixing" the
    narrowed scan above by widening it back over the whole page, which would fail on correct
    output and then be switched off (M0.3).
    """
    body = client.get("/").text
    assert SPIKED_GENOTYPE in body, "the card face must state the call it is interpreting"


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


# ---------------------------------------------------------------------------
# The card grid (roadmap M4.6)
# ---------------------------------------------------------------------------


def test_the_confidence_tier_is_on_the_card_face_not_only_in_the_modal(
    client: TestClient, interpreted: Path
) -> None:
    """AGENTS.md 0.1A makes this a requirement rather than a nicety: nothing is withheld for
    being weak, so the weakness travels with the finding into the summary view, before the
    reader clicks. A grid without it reads as a list of equally solid results."""
    body = client.get("/").text
    grid = body.split('id="card-modal"')[0]

    assert 'class="tier tier-moderate">Moderate<' in grid
    assert "Synthetic dominant trait" in grid


def test_a_card_face_links_to_the_same_address_it_fetches(
    client: TestClient, interpreted: Path
) -> None:
    """One URL, two representations. An ``href`` that differed from the ``hx-get`` would be
    two names for one card, and the no-JavaScript half would rot with every test passing."""
    body = client.get("/").text
    url = f"/runs/{interpreted.name}/cards/synthetic_dominant_trait"

    assert f'href="{url}"' in body
    assert f'hx-get="{url}"' in body
    assert 'hx-target="#card-modal"' in body


def test_the_card_url_answers_with_a_page_and_with_a_fragment(
    client: TestClient, interpreted: Path
) -> None:
    url = f"/runs/{interpreted.name}/cards/synthetic_dominant_trait"
    page = client.get(url)
    fragment = client.get(url, headers={"HX-Request": "true"})

    assert page.status_code == fragment.status_code == 200
    assert page.text.startswith("<!doctype html>")
    assert "<!doctype html>" not in fragment.text
    assert 'role="dialog"' in fragment.text
    # The same rendered detail underneath both, from one template.
    for body in (page.text, fragment.text):
        assert "Odds ratio 1.4 (95% CI 1.25 to 1.57)" in body


def test_the_card_url_declares_that_it_varies(client: TestClient, interpreted: Path) -> None:
    """A cache that did not know would hand a bare fragment to a browser asking for a page."""
    url = f"/runs/{interpreted.name}/cards/synthetic_dominant_trait"
    assert client.get(url).headers.get("Vary") == "HX-Request"


def test_a_card_id_that_names_nothing_is_a_sentence_in_both_forms(
    client: TestClient, interpreted: Path
) -> None:
    """A stale link is the realistic cause -- a card dropped from the pack, or a URL carried
    across data directories -- and every other nothing-to-show state here explains itself."""
    url = f"/runs/{interpreted.name}/cards/no_such_card"
    for headers in ({}, {"HX-Request": "true"}):
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        assert "no card called" in response.text


def test_the_no_javascript_card_page_can_get_back_to_the_run(
    client: TestClient, interpreted: Path
) -> None:
    """It is the whole page a click reaches with scripting off, so it needs a way out that
    is not the browser's back button."""
    body = client.get(f"/runs/{interpreted.name}/cards/synthetic_dominant_trait").text
    assert f'href="/runs/{interpreted.name}"' in body
    assert "All cards in this run" in body


def test_the_detail_view_states_the_population_the_estimate_came_from(
    client: TestClient, interpreted: Path
) -> None:
    """One of the four things AGENTS.md 0.1B requires beside a sensitive claim, and the one
    bundle format 1 could not have shown: ``confidence.inputs`` never held the ancestry."""
    body = client.get(f"/runs/{interpreted.name}/cards/synthetic_dominant_trait").text

    assert "Study population" in body
    assert "EUR, EAS" in body
    assert "120,000" in body, "the sample size the estimate rests on"


def test_the_detail_view_refuses_to_call_an_allele_frequency_a_base_rate(
    client: TestClient, interpreted: Path
) -> None:
    """How common an allele is and how common an outcome is are different quantities.
    Letting the first stand in for the second is the vagueness 0.1B calls a defect."""
    body = client.get(f"/runs/{interpreted.name}/cards/synthetic_dominant_trait").text

    assert "This is not the base rate of the" in body
    assert "Turning it into an absolute risk needs the base rate" in body


def test_the_detail_view_shows_the_arithmetic_behind_the_tier(
    client: TestClient, interpreted: Path
) -> None:
    """AGENTS.md 6 forbids a card authoring its confidence; a computed number with its
    inputs hidden is the same unaccountable figure by another route. Also M13.4's
    requirement, answerable from the page."""
    body = client.get(f"/runs/{interpreted.name}/cards/synthetic_dominant_trait").text

    for label in ("Evidence tier", "Replication", "Ancestry match to the study"):
        assert label in body
    assert "Weighted score" in body


def test_a_citation_is_clickable_and_says_where_it_goes(
    client: TestClient, interpreted: Path
) -> None:
    body = client.get(f"/runs/{interpreted.name}/cards/synthetic_dominant_trait").text

    assert 'href="https://doi.org/10.1038/s41586-000-00000-0"' in body
    assert "leaves your machine" in body, "an outbound link is labelled, not hidden"


def test_the_page_a_citation_is_followed_from_sends_no_referrer(
    client: TestClient, interpreted: Path
) -> None:
    """Load-bearing as of M4.6, and it was not before.

    Until a citation was clickable the CSP meant this page could cause no cross-origin
    request at all, so the header guarded nothing that could happen. Now: without it the
    publisher receives the URL the reader came from, which is ``/runs/<id>/cards/<card_id>``
    -- a card id that names the variant, handed to a third party because somebody wanted to
    read the paper. Two mechanisms, because one of them is an attribute a tidy-up can drop:
    the response header, and ``rel="noreferrer"`` on every anchor (``test_static.py``).
    """
    response = client.get(f"/runs/{interpreted.name}/cards/synthetic_dominant_trait")
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert 'rel="noreferrer noopener"' in response.text


# ---------------------------------------------------------------------------
# Every field reaches the page
# ---------------------------------------------------------------------------


def _full_card() -> views.CardView:
    """A card with every optional block populated and distinctively valued."""
    return views.CardView.of(
        StoredCard(
            card_id="everything",
            section="traits",
            kind="interpretation",
            title="TITLE-MARKER",
            status="matched",
            summary="SUMMARY-MARKER",
            detail="DETAIL-MARKER",
            gene="GENEMARK",
            impossibility_reason="IMPOSSIBLE-MARKER",
            confidence_tier="limited",
            variant={
                "rsid": "rs900000001",
                "chrom": "7",
                "pos_grch37": 12345678,
                "alleles": ["A", "G"],
            },
            match={"observed_rsid": "rs900000009", "strand": "complemented"},
            confidence={
                "tier": "limited",
                "score": 0.42,
                "inputs": {"evidence_tier": "gwas", "evidence_score": 0.8},
                "empirical_ppv": {
                    "estimate": 0.16,
                    "population_frequency_ceiling": 0.00001,
                    "applies_to": "PPV-MARKER",
                },
            },
            evidence={
                "tier": "gwas",
                "replication": "meta_analysis",
                "sample_size": 424242,
                "ancestry": ["SAS"],
                "within_family_attenuation": 0.55,
                "effect": {
                    "measure": "odds_ratio",
                    "value": 1.23,
                    "units": None,
                    "ci_low": 1.11,
                    "ci_high": 1.36,
                    "context": "CONTEXT-MARKER",
                },
            },
            observation={
                "call_source": "imputed",
                "imputation_quality": 0.77,
                "ancestry_match": 0.66,
            },
            frequencies=({"allele": "G", "frequency": 0.25, "population": "AFR", "source": "SRC"},),
            confidence_frequency={
                "allele": "A",
                "frequency": 0.11,
                "population": "AMR",
                "source": "CFSRC",
            },
            citations=({"type": "doi", "id": "10.1038/ng1733", "title": "CITE-MARKER"},),
            authored_caveats=("AUTHORED-MARKER",),
            computed_caveats=("COMPUTED-MARKER",),
        ),
        format_version=BUNDLE_FORMAT_VERSION,
        run_id="a-run",
    )


def _render_card(card: views.CardView, template: str) -> str:
    shell = replace(shell_for(_empty_listing(), None), selected_id="a-run", run_url="/runs/a-run")
    return _environment().get_template(template).render({"card": card, "shell": shell})


#: Fields whose outlet is *conditional* on their own value, so no fixed marker in the map
#: below can test them: rendering `_full_card()` produces the same string whatever they hold.
#: Each is asserted by its own test, named here so the coverage check stays exhaustive
#: rather than being quietly satisfied by a marker that proves nothing.
CONDITIONAL_FIELDS = {
    "kind": "test_the_kind_of_card_decides_which_citations_sentence_is_shown",
    "bundle_format_version": "test_an_old_bundle_says_so_where_the_effect_size_would_be",
}


def test_every_field_a_card_view_collects_reaches_a_rendered_card() -> None:
    """A field in the view model with no outlet in a template is invisible.

    Written the way the banner's equivalent was, after exactly that failure: ``RunOption``
    carried a ``vendor`` the selector never rendered, and it surfaced only because a privacy
    mutation test poisoned the field and nothing leaked. Checked by *rendering* rather than
    by grepping for names, because several fields reach the page through formatting
    properties. Both templates are rendered and the union taken, because ``url`` is a
    property of the card *face* and the tier and title appear on both.

    **Two fields are excluded by name rather than given a marker**, and that is the fix for
    a real defect in the first version of this test: ``kind`` and ``bundle_format_version``
    are only read to choose *which* sentence renders, so any marker for them was satisfied
    by text that is present regardless — the assertion was vacuous for exactly the two
    fields whose rendering is conditional. They are asserted by the two tests named in
    :data:`CONDITIONAL_FIELDS`, and the coverage check below still counts them, so a third
    such field cannot be dropped in silently.
    """
    from dataclasses import fields

    expected: dict[str, str] = {
        "card_id": "everything",
        "section": "#section-traits",
        "section_title": "Traits, morphology",
        "title": "TITLE-MARKER",
        "gene": "GENEMARK",
        "status": "Interpreted",
        "summary": "SUMMARY-MARKER",
        "detail": "DETAIL-MARKER",
        "impossibility_reason": "IMPOSSIBLE-MARKER",
        "tier": "Limited",
        "variant": "chr7:12,345,678",
        "evidence": "424,242",
        "confidence": "0.42",
        "frequencies": "G: 25.0% in AFR (SRC)",
        "confidence_frequency": "A: 11.0% in AMR (CFSRC)",
        "citations": "CITE-MARKER",
        "authored_caveats": "AUTHORED-MARKER",
        "computed_caveats": "COMPUTED-MARKER",
        "observed_rsid": "rs900000009",
        "call_source": "imputed",
        "imputation_quality": "0.77",
        "ancestry_match": "0.66",
        "strand": "complemented",
        "url": "/runs/a-run/cards/everything",
    }
    declared = {field.name for field in fields(views.CardView)}
    assert set(expected) | set(CONDITIONAL_FIELDS) == declared, (
        "the expected-output map has drifted from CardView; a new field needs an outlet in "
        "a card template and an entry here (or a named test, if its outlet is conditional)"
    )

    card = _full_card()
    markup = _render_card(card, "_carddetail.html") + _render_card(card, "_cardface.html")
    missing = {name: marker for name, marker in expected.items() if marker not in markup}
    assert not missing, f"collected but never rendered: {missing}"

    for field_name, test_name in CONDITIONAL_FIELDS.items():
        assert test_name in globals(), f"{field_name} names a test that does not exist"


def test_the_kind_of_card_decides_which_citations_sentence_is_shown() -> None:
    """``kind``'s only outlet. An impossibility card citing nothing is correct and says so;
    an interpretation card citing nothing is a card that is not ready to ship."""
    interpretation = replace(_full_card(), citations=())
    impossibility = replace(interpretation, kind="impossibility")

    assert "records no citation" in _render_card(interpretation, "_carddetail.html")
    assert "the exemption exists to prevent" in _render_card(impossibility, "_carddetail.html")


def test_an_old_bundle_says_so_where_the_effect_size_would_be() -> None:
    """``bundle_format_version``'s only outlet, and it has to be distinguishable from a card
    that simply records no evidence — otherwise a reader goes looking for a defect in the
    card when the answer is to re-run the analysis."""
    old = replace(_full_card(), evidence=None, bundle_format_version=1)
    current = replace(_full_card(), evidence=None)

    assert "bundle format 1" in _render_card(old, "_carddetail.html")
    assert "Re-run" in _render_card(old, "_carddetail.html"), "and what to do about it"
    assert "records no published evidence" in _render_card(current, "_carddetail.html")
    assert "bundle format" not in _render_card(current, "_carddetail.html")


def test_the_detail_page_carries_the_effect_context_and_the_ppv_note() -> None:
    """Both are sentences that only exist to stop a number being misread, so a template edit
    that dropped either would leave the figure looking more certain than it is."""
    markup = _render_card(_full_card(), "_carddetail.html")

    assert "CONTEXT-MARKER" in markup
    assert "PPV-MARKER" in markup
    assert "Meta-analysis" in markup and "GWAS" in markup


# ---------------------------------------------------------------------------
# Sort, filter, group over HTTP (roadmap M4.7)
# ---------------------------------------------------------------------------


def test_the_unarranged_page_shows_every_card_in_the_run(
    client: TestClient, interpreted: Path
) -> None:
    """The rule is about the *first* paint: a page that arrives pre-filtered has made the
    hiding decision 0.1A forbids, before the reader knew there was one."""
    from genetics.run import store

    bundle = store.load_run(interpreted.name, interpreted.parent)
    body = client.get("/").text

    assert bundle.cards, "nothing to show; this would pass vacuously"
    for card in bundle.cards:
        assert f"/cards/{card.card_id}" in body, f"{card.card_id} is not on the default page"
    assert "hidden by the filter" not in body


def test_a_filter_states_what_it_hid_and_offers_one_click_back(
    client: TestClient, interpreted: Path
) -> None:
    body = client.get("/?tier=well-established").text

    assert "card(s) are hidden" in body
    assert "Show every card" in body
    assert f'href="/runs/{interpreted.name}"' in body, "the way back drops every filter"


def test_grouping_by_tier_still_explains_the_sections_that_are_empty(
    client: TestClient, interpreted: Path
) -> None:
    """Grouping by tier takes the section panels off the page and the sentence each empty one
    was carrying with them. The definition of done (item 3) is about the reader being able to
    tell "not built yet" from "nothing matched", not about the shape of the panel saying so."""
    body = client.get("/?group=tier").text

    assert "Sections with nothing to show" in body
    assert "roadmap M5" in body, "the ancestry section still names the milestone that fills it"
    assert "Likely artifact" in body, "every tier gets a heading, populated or not"


def test_an_unrecognised_arrangement_shows_everything_and_says_it_was_ignored(
    client: TestClient, interpreted: Path
) -> None:
    response = client.get("/?tier=strng&group=sideways")

    assert response.status_code == 200
    assert "Ignored" in response.text and "tier=strng" in response.text
    assert "card(s) are hidden" not in response.text


def test_the_navigation_counts_do_not_move_when_a_filter_is_on(
    client: TestClient, interpreted: Path
) -> None:
    """Asserted over HTTP as well as in the view model, because the nav is rendered from a
    different object than the grid and the coupling that keeps them apart is a template."""
    plain = client.get("/").text
    filtered = client.get("/?tier=well-established").text

    def counts(body: str) -> list[str]:
        nav = body.split('class="sections"')[1].split("</ol>")[0]
        return re.findall(r'title="(\d+ card\(s\), \d+ interpreted)"', nav)

    assert "card(s) are hidden" in filtered, "the filter really is hiding something"
    assert counts(plain) == counts(filtered) != []
    # The *links* do differ, and should: they carry the arrangement so that following one
    # does not silently drop the reader's filter. It is the numbers that must not move.
    assert "tier=well-established" in filtered.split('class="sections"')[1]


def test_the_controls_preselect_nothing_on_a_fresh_page(
    client: TestClient, interpreted: Path
) -> None:
    body = client.get("/").text
    controls = body.split('class="controls"')[1].split("</form>")[0]

    assert 'name="tier"' in controls, "the tier filter is offered"
    assert "checked" not in controls, "no filter is on by default"
    assert "Clear filters" not in controls, "there is nothing to clear"


def test_the_controls_are_a_plain_get_form(client: TestClient, interpreted: Path) -> None:
    """It has to work with scripting off, and the arrangement has to land in the URL so it
    can be linked and returned to."""
    body = client.get("/").text
    controls = body.split('class="controls"')[1].split("</form>")[0]

    form = body.split("<form", 1)[1].split(">", 1)[0]
    assert 'method="get"' in form and 'class="controls"' in form
    assert '<button type="submit">Apply</button>' in controls


# ---------------------------------------------------------------------------
# Theming and layout (roadmap M4.8)
# ---------------------------------------------------------------------------


def test_the_theme_script_runs_before_the_first_paint(client: TestClient) -> None:
    """Deferred, it would run after the page had been painted in the system theme, and every
    load under an explicit choice would flash the other one."""
    body = client.get("/").text
    tag = next(line for line in body.splitlines() if "theme.js" in line)

    assert "defer" not in tag and "async" not in tag
    assert body.index("theme.js") < body.index("app.css"), "the attribute must exist before CSS"


def test_the_theme_toggle_is_hidden_when_scripting_is_off() -> None:
    """A control that needs JavaScript and renders anyway is a control that silently does
    nothing, which reads as a broken page rather than an unavailable feature."""
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert ".themetoggle { display: none; }" in css
    assert ':root[data-js="on"] .themetoggle' in css


def test_the_palette_survives_all_three_theme_states() -> None:
    """Three states, not two. The media query needs the ``:not([data-theme="light"])`` guard
    or an explicit light choice loses to a machine set to dark; the ``[data-theme="dark"]``
    block is the same argument in the other direction. Only one of the two is obvious."""
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")

    assert ':root:not([data-theme="light"])' in css
    assert ':root[data-theme="dark"]' in css
    # Every token defined on bare :root first, so nothing has its only definition inside a
    # media query -- the failure where an untested theme renders half-unstyled.
    root = css.split(":root {")[1].split("}")[0]
    for token in ("--bg", "--ink", "--panel", "--line", "--tier-artifact-bg", "--scrim"):
        assert token in root, f"{token} is not defined in the base palette"


def test_a_confidence_tier_is_never_communicated_by_colour_alone() -> None:
    """The one attribute 0.1A makes non-negotiable must not be invisible to a reader with a
    colour vision deficiency."""
    markup = _render_card(_full_card(), "_carddetail.html")
    assert ">Limited<" in markup, "the tier badge carries its own text, not just a hue"


def test_wide_content_scrolls_inside_itself_rather_than_the_page() -> None:
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    assert ".tablescroll { overflow-x: auto; }" in css
    assert "grid-template-columns: 1fr;" in css, "the layout collapses to one column"
    assert "@media (max-width: 40rem)" in css and "@media (max-width: 60rem)" in css


def test_an_impossibility_card_renders_no_measurement_blocks(
    client: TestClient, interpreted: Path
) -> None:
    """Over HTTP, because the suppression is a template condition and the view-model test
    can only assert the inputs to it."""
    body = client.get(f"/runs/{interpreted.name}/cards/synthetic_impossibility").text

    assert "Why this cannot be determined" in body
    for absent in ("Effect size", "Allele frequency", "How this was called"):
        assert absent not in body, f"an impossibility card claims a {absent!r} block"
    assert "the tangential reference the exemption exists to prevent" in body


def test_a_card_that_did_not_match_says_its_figures_are_not_about_the_reader() -> None:
    """It still shows the published claim — a reader is owed what they are being told
    nothing about — but a number under a heading on a genome dashboard reads as personal
    unless something says otherwise.

    Rendered directly rather than over HTTP because ``interpreted`` spikes both synthetic
    markers, so every interpretation card in it matches. A fixture built to make this card
    absent would be a third pipeline run for one template condition.
    """
    from genetics.web import views

    card = replace(
        _full_card(),
        status="marker_absent",
        observed_rsid=None,
        imputation_quality=None,
        call_source="direct",
    )
    assert isinstance(card, views.CardView)
    markup = _render_card(card, "_carddetail.html")

    assert "Nothing below is a statement about" in markup
    assert "Marker not on this array" in markup
    assert "Odds ratio 1.23" in markup, "the published claim is still shown"
    assert "How this was called" not in markup, "no probe answered at this position"
