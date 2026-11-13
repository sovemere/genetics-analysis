"""CLI and dashboard parity (roadmap M13.5): every analysis a page shows, a command prints.

The check is :mod:`genetics.testing.parity`. This file runs it three ways. The route table
and the engine-call list are held to the dashboard's own code. The view tables are held to
the view classes, field for field. And every page of a saved run is compared with what the
commands print for it.

A check that passes proves little by itself, so each rule is also broken on purpose: a
route, a call, a field, a property or a value is changed on one side only, and the check
has to fail and name the place.

The saved run is the committed pack matched against an invented table (each card's first
and last declared allele), with a damaged run and an interrupted save beside it so that the
run selector has rows of every kind. No export is read. The saved runs with HLA calls,
guideline cards, placed polygenic scores and a ClinVar lookup are built by ``tests/hla``,
``tests/refs`` and ``tests/health``, which run the same check through ``parity_check``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from genetics.ancestry.context import AncestryContext
from genetics.engine.cards import CardKind, KnowledgePack, default_knowledge_dir
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import match_pack
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run import reads
from genetics.run.bundle import INCOMING_PREFIX, MANIFEST_NAME, write_bundle
from genetics.run.pipeline import observations
from genetics.testing import parity
from genetics.testing.parity import ParityError, Report
from genetics.web import app as web_app
from genetics.web import polygenic, views

Check = Callable[[Path], Report]

CARD = "wnt10a_hair_curl"
"""A matched single-marker card, for the changes made to one card."""


def _table(pack: KnowledgePack) -> GenotypeTable:
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for card in pack.cards:
        if card.match is None:
            continue
        variant = card.match.variants[0]
        first, last = variant.key.alleles[0], variant.key.alleles[-1]
        rows[(variant.key.chrom.value, variant.key.pos_grch37)] = {
            "rsid": variant.rsid,
            "chrom": variant.key.chrom.value,
            "pos_grch37": variant.key.pos_grch37,
            "a1": first,
            "a2": last,
            "genotype": "".join(sorted(first + last)),
            "call_status": "called",
        }
    return GenotypeTable(
        pl.DataFrame(list(rows.values()), schema=NORMALIZED_SCHEMA), vendor="synthetic"
    )


@pytest.fixture(scope="module")
def saved(sample_qc: QCReport, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Every card that needs no stage record, beside a damaged run and an interrupted save."""
    root = tmp_path_factory.mktemp("parity")
    runs = root / "data" / "runs"
    full = KnowledgePack.load(default_knowledge_dir())
    pack = KnowledgePack(
        tuple(c for c in full.cards if c.kind not in {CardKind.HLA, CardKind.GUIDELINE}),
        full.source_dir,
    )
    matches = match_pack(pack, _table(pack))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GENETICS_DATA_DIR", str(root / "data"))
        path = write_bundle(
            qc=sample_qc,
            cards=assemble_pack(pack, matches, observations(pack, matches)),
            pack=pack,
            ancestry=AncestryContext.not_run("synthetic test bundle"),
            runs_root=runs,
            lock_path=root / "absent.lock",
            tools_root=root / "tools",
        )
        damaged = runs / "20200101T000000Z-0000dead"
        damaged.mkdir()
        (damaged / MANIFEST_NAME).write_text("{ not json", encoding="utf-8")
        interrupted = runs / f"{INCOMING_PREFIX}20200102T000000Z-0000beef"
        interrupted.mkdir()
        (interrupted / "cards.run.json").write_text("{}", encoding="utf-8")
        yield path


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def test_every_route_names_the_commands_that_print_what_it_shows() -> None:
    parity.check_routes()
    assert len({page.route for page in parity.PAGES}) == len(parity.PAGES) == 8


def test_a_route_with_no_commands_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure this item exists for: a page added to the app and to no table."""
    monkeypatch.setattr(parity, "PAGES", parity.PAGES[:-1])
    with pytest.raises(ParityError, match=r"/runs/\{run_id\}/pgx.*not in parity\.PAGES"):
        parity.check_routes()


def test_a_listed_route_or_command_that_is_gone_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = parity.PAGES
    gone = parity.Page("/runs/{run_id}/ancestry", ("genetics runs show <run> --json",), "x")
    monkeypatch.setattr(parity, "PAGES", (*pages, gone))
    with pytest.raises(ParityError, match="does not serve"):
        parity.check_routes()
    for command in (
        "genetics runs ancestry <run> --json",  # no such command
        "genetics runs prune",  # exists, but the page's data must be in JSON
        "genetics fixtures --json",  # exists, with no --json option
    ):
        renamed = dataclasses.replace(pages[0], commands=(command,))
        monkeypatch.setattr(parity, "PAGES", (renamed, *pages[1:]))
        with pytest.raises(ParityError, match="is not a command that takes --json"):
            parity.check_routes()
    # An option the table writes and the command has since lost or renamed.
    renamed = dataclasses.replace(
        pages[0], commands=("genetics runs show <run> --part <x> --json",)
    )
    monkeypatch.setattr(parity, "PAGES", (renamed, *pages[1:]))
    with pytest.raises(ParityError, match="--part, which the command does not take"):
        parity.check_routes()


def test_the_route_table_is_the_one_the_documentation_gives() -> None:
    """docs/agent_cli.md is where an agent reads which command stands for which page."""
    text = (Path(__file__).parents[1] / "docs" / "agent_cli.md").read_text(encoding="utf-8")
    for page in parity.PAGES:
        assert f"`{page.route}`" in text, page.route
        for command in page.commands:
            assert f"`{command}`" in text, (page.route, command)


# ---------------------------------------------------------------------------
# Engine calls
# ---------------------------------------------------------------------------


def test_the_dashboard_calls_no_engine_function_the_cli_does_not() -> None:
    parity.check_engine_calls()
    # The harvest finds what it should, so an empty one cannot pass for agreement.
    web = parity.engine_functions(parity._package_files("genetics.web"))
    assert {
        "genetics.run.explain.explain_confidence",
        "genetics.health.secondary.secondary_view",  # imported inside a route
        "genetics.run.reads.empty_reason",  # reached through an imported module
        "genetics.hla.calling.report",
    } <= web


def test_a_function_only_the_dashboard_calls_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parity, "DISPLAY_ONLY", {})
    with pytest.raises(ParityError, match=r"only the dashboard calls.*phase_coverage_text"):
        parity.check_engine_calls()


def test_an_exemption_that_is_no_longer_needed_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    listed = parity.DISPLAY_ONLY | {"genetics.run.store.list_runs": "Both call it."}
    monkeypatch.setattr(parity, "DISPLAY_ONLY", listed)
    with pytest.raises(ParityError, match=r"list_runs.*the CLI now reaches"):
        parity.check_engine_calls()


def test_calls_are_read_from_function_bodies_and_through_modules(tmp_path: Path) -> None:
    source = tmp_path / "page.py"
    source.write_text(
        "from genetics.run import store\n"
        "from genetics.engine.sections import Section\n"
        "def route():\n"
        "    from genetics.engine.citations import citation_url as link\n"
        "    return store.list_runs(), link, Section\n",
        encoding="utf-8",
    )
    assert parity.engine_functions([source]) == {
        "genetics.run.store.list_runs",
        "genetics.engine.citations.citation_url",
    }


@pytest.mark.parametrize(
    ("line", "match"),
    [
        ("from ..run import store", "page.py:1: a relative import cannot be followed"),
        ("import genetics.run.store", r"page.py:1: `import genetics\.run\.store` cannot be"),
    ],
)
def test_an_import_the_reader_cannot_follow_fails(tmp_path: Path, line: str, match: str) -> None:
    """A call made through either form would not be listed, so the form itself fails."""
    source = tmp_path / "page.py"
    source.write_text(f"{line}\nimport json\nfrom pathlib import Path\n", encoding="utf-8")
    with pytest.raises(ParityError, match=match):
        parity.engine_functions([source])


# ---------------------------------------------------------------------------
# View classes
# ---------------------------------------------------------------------------


def test_every_view_field_is_placed_and_every_property_is_listed() -> None:
    parity.check_views()
    classes = parity.view_classes()
    assert {views.Shell, views.CardView, polygenic.PolygenicView} <= set(classes)
    assert len(classes) == 23
    # Each class is accounted for one way only.
    kinds = (parity.TABLES, parity.ARRANGED, parity.NESTED, parity.DRAWN)
    assert all(sum(cls in kind for kind in kinds) == 1 for cls in classes)
    assert set(parity.PROPERTIES) == set(classes)


def test_a_field_with_no_place_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A field added to a view and to no table: shown by the dashboard, unknown to the check."""
    shorter = {name: placed for name, placed in parity.CARD.items() if name != "risk_context"}
    monkeypatch.setitem(parity.TABLES, views.CardView, shorter)
    with pytest.raises(ParityError, match=r"CardView.*risk_context"):
        parity.check_views()


def test_a_new_property_or_view_class_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(views.CardView, "relative_risk", property(lambda self: 2.0), raising=False)
    with pytest.raises(ParityError, match=r"CardView: propert.*relative_risk.*engine"):
        parity.check_views()
    monkeypatch.undo()

    @dataclasses.dataclass(frozen=True)
    class AncestryView:
        population: str

    AncestryView.__module__ = views.__name__
    monkeypatch.setattr(views, "AncestryView", AncestryView, raising=False)
    with pytest.raises(ParityError, match="view class AncestryView is not in parity's tables"):
        parity.check_views()


def test_a_nested_exemption_for_a_field_that_is_gone_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(parity.APART, (views.ScoreRow, "weight"), "Removed.")
    with pytest.raises(ParityError, match=r"ScoreRow: field\(s\) \['weight'\] are in the class or"):
        parity.check_views()


# ---------------------------------------------------------------------------
# One saved run, every page
# ---------------------------------------------------------------------------


def test_a_saved_run_shows_nothing_the_commands_do_not_print(
    saved: Path, parity_check: Check
) -> None:
    report = parity_check(saved)
    cards = [words[-1] for words in report.documents if words[:2] == ("runs", "card")]
    assert len(cards) == len(set(cards)) == 103
    assert report.cards == 2 * len(cards), "each card is compared grouped by section and by tier"
    assert report.templates == set(parity.CONTEXT)
    genes = list(report.documents[("pgx", "calls", saved.name)]["genes"])
    assert len(genes) == 8, "a run with no PGx stage still records each gene as unavailable"
    # healthz, the index, two groupings, each card's page, one fragment, a missing card,
    # the ClinVar, secondary, HLA and PGx pages, then each gene's page.
    assert report.pages == 2 + 2 + len(cards) + 2 + 4 + len(genes)
    # One `runs card` each, one `pgx calls --gene` each, and the ten other documents.
    assert report.commands == len(report.documents) == len(cards) + len(genes) + 10
    assert report.compared > 5000


def test_the_run_has_the_rows_the_selector_must_show(saved: Path, parity_check: Check) -> None:
    listing = parity_check(saved).documents[("runs", "list")]
    assert [row["status"] for row in listing["runs"]] == ["readable", "damaged"]
    assert len(listing["incomplete"]) == 1


def _fails(saved: Path, match: str) -> str:
    with pytest.raises(ParityError, match=match) as caught:
        parity.check_run(saved)
    return str(caught.value)


def test_a_card_value_the_command_does_not_print_fails(
    saved: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build = views.CardView.of.__func__  # type: ignore[attr-defined]

    def changed(cls: type[views.CardView], /, card: Any, **kwargs: Any) -> views.CardView:
        view: views.CardView = build(cls, card, **kwargs)
        return dataclasses.replace(view, gene="ZZZ9") if card.card_id == CARD else view

    monkeypatch.setattr(views.CardView, "of", classmethod(changed))
    message = _fails(saved, rf"card {CARD}\.gene differs from what `runs card` prints")
    assert "ZZZ9" not in message, "a failure names the field, never the value"


def test_a_value_inside_a_nested_view_fails(saved: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build = views.VariantView.of.__func__  # type: ignore[attr-defined]

    def changed(cls: type[views.VariantView], raw: Any) -> views.VariantView:
        view: views.VariantView = build(cls, raw)
        return dataclasses.replace(view, position=(view.position or 0) + 1)

    monkeypatch.setattr(views.VariantView, "of", classmethod(changed))
    _fails(saved, r"\.variant\.position differs from what `runs card` prints")


def test_a_card_field_the_command_drops_fails(saved: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The other direction of the same break: the dashboard is right and the CLI lost a key."""
    build = reads.card_payload

    def shorter(card: Any) -> dict[str, Any]:
        return build(card) | {"risk_context": None, "summary": ""}

    monkeypatch.setattr(reads, "card_payload", shorter)
    _fails(saved, r"\.summary differs from what `runs card` prints")


@pytest.mark.parametrize(
    ("target", "name", "change", "match"),
    [
        (
            views,
            "banner_for",
            lambda banner: dataclasses.replace(banner, call_rate=0.5),
            r"shell\.banner\.call_rate differs from what `runs qc` prints",
        ),
        (
            views,
            "section_views",
            lambda rows: (dataclasses.replace(rows[0], interpreted=99), *rows[1:]),
            r"shell\.sections\[ancestry\]\.interpreted differs from what `runs show --section`",
        ),
        (
            views,
            "related_links",
            lambda links: (),
            r"shell\.grid\.groups\[\w+\]\.related differs from `runs show --section`",
        ),
        (
            views,
            "unknown_sections",
            lambda names: ("fourteenth",),
            r"shell\.unknown_sections differs from what `runs show` prints",
        ),
    ],
)
def test_a_shell_value_the_commands_do_not_print_fails(
    saved: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: Any,
    name: str,
    change: Callable[[Any], Any],
    match: str,
) -> None:
    build = getattr(target, name)
    monkeypatch.setattr(target, name, lambda *args, **kwargs: change(build(*args, **kwargs)))
    _fails(saved, match)


def test_a_selector_row_that_differs_from_the_listing_fails(
    saved: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build = views.RunOption.of.__func__  # type: ignore[attr-defined]

    def changed(cls: type[views.RunOption], summary: Any) -> views.RunOption:
        option: views.RunOption = build(cls, summary)
        return dataclasses.replace(option, selectable=True)

    monkeypatch.setattr(views.RunOption, "of", classmethod(changed))
    _fails(saved, r"shell\.runs\[20200101T000000Z-0000dead\]\.selectable differs")


def test_a_context_value_that_differs_fails(saved: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_app, "ENGINE_VERSION", "0.0.0-other")
    message = _fails(saved, r"`engine_version` differs from what `version` prints")
    assert "0.0.0-other" not in message


def test_healthz_is_compared_too(saved: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_app, "BUNDLE_FORMAT_VERSION", 1)
    _fails(saved, r"/healthz `bundle_format_version` differs from what `version` prints")


@pytest.mark.parametrize(
    ("template", "key"),
    [
        ("hla.html", "hla_report"),
        ("pgx.html", "pgx_candidates"),
        ("clinvar.html", "clinvar_loci"),
        ("card.html", "card"),
        ("dashboard.html", "engine_version"),
    ],
)
def test_a_context_key_with_no_place_fails(
    saved: Path, monkeypatch: pytest.MonkeyPatch, template: str, key: str
) -> None:
    """A route that hands its template something new, which no table places."""
    table = {name: placed for name, placed in parity.CONTEXT[template].items() if name != key}
    monkeypatch.setitem(parity.CONTEXT, template, table)
    _fails(saved, rf"hands {template} `{key}`, which is not placed")


def test_the_index_s_keys_are_placed_too(saved: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``/`` is rendered first, so a key only it were handed could not go unplaced."""
    table = {k: v for k, v in parity.CONTEXT["dashboard.html"].items() if k != "engine_version"}
    monkeypatch.setitem(parity.CONTEXT, "dashboard.html", table)
    _fails(saved, r"^/ hands dashboard\.html `engine_version`, which is not placed")


@pytest.mark.parametrize(
    ("built_before", "match"),
    [
        # `/` builds the first shell, and the run page grouped two ways the next two.
        (0, r"^/ shell\.card_count differs from the run page's"),
        (3, r"/cards/\w+ shell\.card_count differs from the run page's"),
    ],
)
def test_a_page_whose_shell_is_not_the_compared_one_fails(
    saved: Path, monkeypatch: pytest.MonkeyPatch, built_before: int, match: str
) -> None:
    """Only the run page's shell is compared with the commands, so every other page's
    must equal it. A page that built its own differently would otherwise pass."""
    build = views.shell_for
    built: list[views.Shell] = []

    def other(*args: Any, **kwargs: Any) -> views.Shell:
        shell = build(*args, **kwargs)
        built.append(shell)
        if len(built) == built_before + 1:
            return dataclasses.replace(shell, card_count=shell.card_count + 1)
        return shell

    monkeypatch.setattr(views, "shell_for", other)
    _fails(saved, match)


def test_a_partial_handed_a_key_the_page_is_not_fails() -> None:
    """The page's keys are the ones placed, so nothing rendered before it may hold another."""
    from types import SimpleNamespace

    recorder = parity._Recorder(
        SimpleNamespace(state=SimpleNamespace(environment=SimpleNamespace()))
    )
    recorder.rendered = [
        ("_qcbanner.html", {"shell": None, "relative_risk": 2.0}),
        ("dashboard.html", {"shell": None, "qcbanner_html": ""}),
    ]
    with pytest.raises(ParityError, match=r"hands _qcbanner\.html \['relative_risk'\]"):
        recorder.page("/runs/x")
    recorder.rendered[0] = ("_qcbanner.html", {"shell": None})
    assert recorder.page("/runs/x")[0] == "dashboard.html"
    recorder.rendered.clear()
    with pytest.raises(ParityError, match="/runs/x rendered no template"):
        recorder.page("/runs/x")


def test_a_view_field_with_no_place_fails_when_a_run_is_checked(
    saved: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``check_views`` finds this without a run; a run check must not pass over it either."""
    shorter = {name: placed for name, placed in parity.CARD.items() if name != "risk_context"}
    monkeypatch.setattr(parity, "CARD", shorter)
    _fails(saved, r"CardView\.risk_context is not placed")


def test_a_template_the_tables_do_not_know_fails(
    saved: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delitem(parity.CONTEXT, "hla.html")
    _fails(saved, r"/hla renders hla\.html, which parity\.CONTEXT omits")


def test_a_run_outside_a_runs_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ParityError, match="a directory named `runs`"):
        parity.check_run(tmp_path / "elsewhere" / "20260101T000000Z-00000000")


def test_changing_any_one_value_a_card_shows_fails(saved: Path, parity_check: Check) -> None:
    """Every compared field of every card, one change at a time (M13.5 review).

    The tests above change a handful of values chosen by hand. ``parity.unnoticed`` changes
    each string, number, flag and absent value that each of the 103 card views holds, nested
    views and saved records included, and adds an entry to each mapping and list. Every
    change has to fail, bar a confidence row's label, which is the dashboard's own name for
    an input. ``parity_check`` asserts the same on every run another suite hands it.
    """
    report = parity_check(saved)
    tried, passed = parity.unnoticed(report)
    assert len(report.shown) == 103 and tried > 6000
    assert passed == set(parity.UNNOTICED) == {"confidence.rows[].label"}
    # A seventh row of the confidence table is a row no table places, whatever it holds.
    card, document = next(pair for pair in report.shown if pair[0].confidence is not None)
    rows = card.confidence.rows
    longer = dataclasses.replace(card.confidence, rows=(*rows, rows[0]))
    with pytest.raises(ParityError, match=r"a row parity\.CONFIDENCE_ROWS does not place"):
        parity._apply(
            parity.CARD, dataclasses.replace(card, confidence=longer), document, "card", Report()
        )


def test_the_fixture_fails_a_run_whose_comparison_would_miss_a_change(
    saved: Path, parity_check: Check, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``parity_check`` probes every run a suite hands it, so a table that compares a field
    loosely fails in the suite that builds a run where it matters."""
    loose = parity.Reached("runs card", lambda value, document, where: None)
    monkeypatch.setitem(parity.CARD, "evidence", loose)
    with pytest.raises(AssertionError, match=r"evidence\.within_family_attenuation"):
        parity_check(saved)


def test_one_change_reaches_every_kind_of_value() -> None:
    row = views.ScoreRow(label="Evidence tier", observed="gwas", score=0.5)
    held = {"flag": True, "none": None, "rows": (row,)}
    assert [where for where, _ in parity.one_change(held, "x")] == [
        "x.flag",
        "x.none",
        "x.rows[].label",
        "x.rows[].observed",
        "x.rows[].score",
        "x.rows[+]",
        "x.+",
    ]
    changed = dict(parity.one_change(held, "x"))
    assert changed["x.flag"]["flag"] is False and changed["x.none"]["none"] == "~"
    assert changed["x.rows[].score"]["rows"][0].score == 1.5
    assert held == {"flag": True, "none": None, "rows": (row,)}, "the original is left alone"


# ---------------------------------------------------------------------------
# The comparisons themselves
# ---------------------------------------------------------------------------


def test_a_view_s_value_is_the_saved_one_as_a_view_reads_it() -> None:
    assert parity.as_read("EUR", " EUR ") and parity.as_read("5", 5)
    assert parity.as_read(0.5, 0.5) and parity.as_read(5.0, 5) and parity.as_read(5, 5)
    assert parity.as_read(("A", "G"), ["A", " ", None, "G"])
    assert not parity.as_read("EUR", "EAS") and not parity.as_read("EUR", None)
    assert not parity.as_read(0.5, 1.5) and not parity.as_read(0.5, "0.5")
    assert not parity.as_read(1, True) and not parity.as_read(("A",), ["A", "G"])
    assert not parity.as_read({"a": 1}, {"a": 1}), "a view holds no mapping it read by key"


def test_same_read_and_kept_fail_on_a_difference_and_only_then() -> None:
    saved = {"rsid": "rs1", "pos_grch37": 5, "chrom": None, "alleles": ["A", "G"]}
    document = {"card": {"gene": "WNT10A", "variant": saved, "list": [saved], "none": None}}
    variant = views.VariantView(rsid="rs1", chrom=None, position=5, alleles=("A", "G"))
    parity.same("runs card", lambda d: d["card"]["gene"]).compare("WNT10A", document, "gene")
    with pytest.raises(ParityError, match="gene differs from what `runs card` prints"):
        parity.same("runs card", lambda d: d["card"]["gene"]).compare("EDAR", document, "gene")

    one = parity.read("runs card", lambda d: d["card"]["variant"])
    one.compare(variant, document, "v")
    one.compare(None, document, "v")
    with pytest.raises(ParityError, match=r"v\.position differs from what `runs card` prints"):
        one.compare(dataclasses.replace(variant, position=6), document, "v")
    # A figure that is elsewhere in the same record is still the wrong figure. Comparing
    # by whether a value appears anywhere in the record passed this until the review.
    elsewhere = {**saved, "other": 6}
    with pytest.raises(ParityError, match=r"v\.position differs"):
        parity.read("runs card", lambda d: elsewhere).compare(
            dataclasses.replace(variant, position=6), document, "v"
        )
    with pytest.raises(ParityError, match=r"v\.chrom is shown, and `runs card` prints no value"):
        one.compare(dataclasses.replace(variant, chrom="7"), document, "v")
    with pytest.raises(ParityError, match="v is shown, and `runs card` prints no record"):
        parity.read("runs card", lambda d: d["card"]["none"]).compare(variant, document, "v")
    # A placeholder stands for a saved value that is absent, and for nothing else.
    blank = views.FrequencyView(allele="?", frequency=None, population=None, source=None)
    parity.read("x", lambda d: {"allele": " "}).compare(blank, document, "f")
    with pytest.raises(ParityError, match=r"f\.allele differs"):
        parity.read("x", lambda d: {"allele": "A"}).compare(blank, document, "f")

    each = parity.read_each("runs card", lambda d: d["card"]["list"])
    each.compare((variant,), document, "vs")
    with pytest.raises(ParityError, match="vs has more or fewer entries"):
        each.compare((variant, variant), document, "vs")
    with pytest.raises(ParityError, match=r"vs\[0\]\.rsid differs"):
        each.compare((dataclasses.replace(variant, rsid="rs2"),), document, "vs")

    whole = parity.kept("runs card", lambda d: d["card"]["variant"])
    whole.compare(saved, document, "k")
    whole.compare({}, document, "k")
    whole.compare(None, document, "k")
    with pytest.raises(ParityError, match="k differs from what `runs card` prints"):
        whole.compare({**saved, "chrom": "7"}, document, "k")
    # A tuple the dashboard holds equals the list JSON gives back.
    parity.same("x", lambda d: [1, 2]).compare((1, 2), document, "pair")
    assert parity.dig(document, "card", "variant", "rsid") == "rs1"
    assert parity.dig(document, "card", "absent", "rsid") is None
