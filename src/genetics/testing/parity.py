"""CLI and dashboard parity: what a page shows, a command prints (roadmap M13.5).

AGENTS.md 3 requires one engine with two front-ends: "If a computation is only reachable
from the UI, an agent cannot review it." This module is the check. It is a library, not a
test file, so that the suites that build the only saved runs with HLA calls, guideline
cards, polygenic scores and a ClinVar lookup can run it on them through the ``parity_check``
fixture in ``tests/conftest.py``, as they run ``agent_schema_check``.

**Reachable means: in the JSON a command prints.** AGENTS.md 0 says the CLI "emits JSON", so
JSON is what is compared. A command's text output is a reading aid and is not checked here.

Three things are compared, and each is listed from the dashboard's own code, so that
something new fails until it is placed:

* **Routes** (:func:`check_routes`). Every route the app serves is in :data:`PAGES` with the
  commands that hold what it shows, and every one of those commands exists and takes
  ``--json``.
* **Engine calls** (:func:`check_engine_calls`). Every engine function ``genetics.web``
  calls is one the CLI's read side calls too, or is in :data:`DISPLAY_ONLY` with the reason
  it is not an analysis.
* **Values** (:func:`check_run`). For one saved run, each page is rendered and what it hands
  its template is recorded: every context key, every field of
  :class:`~genetics.web.views.Shell` and of every card. Each one is compared with the place
  a command's document holds it, or is declared as display: an address, a label, paging or
  chart geometry. :func:`check_views` holds the tables to the classes, field for field.

**What this cannot see.** A view's *properties* word or arrange values the object already
holds, and are listed in :data:`PROPERTIES` so that a new one is noticed. Nothing checks
what a property computes. A calculation written inside a property or a template, from saved
fields and no engine function, is found only by a person reading the diff. The rule for
those is AGENTS.md 3's: an analysis belongs in the engine.

No message here quotes a compared value. A run is raw DNA (AGENTS.md 1.1), so a failure
names the page, the card and the field and nothing else.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import json
import types
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from genetics.engine.sections import SECTION_ORDER
from genetics.web import polygenic, views

__all__ = [
    "DISPLAY_ONLY",
    "PAGES",
    "PROPERTIES",
    "Display",
    "Page",
    "ParityError",
    "Reached",
    "Report",
    "check_engine_calls",
    "check_routes",
    "check_run",
    "check_views",
]


class ParityError(AssertionError):
    """The dashboard shows something no command is recorded as printing, or a different value."""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    """One dashboard route and the commands whose JSON holds what it shows."""

    route: str
    commands: tuple[str, ...]
    shows: str


PAGES: Final[tuple[Page, ...]] = (
    Page(
        "/healthz",
        ("genetics version --json", "genetics runs list --json"),
        "the engine and bundle-format versions, the runs directory and how many runs it holds",
    ),
    Page(
        "/",
        ("genetics runs list --json",),
        "the newest readable run, opened as its own page is",
    ),
    Page(
        "/runs/{run_id}",
        (
            "genetics runs list --json",
            "genetics runs qc <run> --json",
            "genetics runs imputation <run> --json",
            "genetics runs show <run> --section <section> --json",
            "genetics runs show <run> --json",
            "genetics runs card <run> <card-id> --json",
            "genetics pgx calls <run> --json",
        ),
        "the run selector, the QC banner, the thirteen sections and every card's face",
    ),
    Page(
        "/runs/{run_id}/cards/{card_id}",
        ("genetics runs card <run> <card-id> --json",),
        "one card in full, with what decided its tier",
    ),
    Page(
        "/runs/{run_id}/clinvar",
        ("genetics runs clinvar <run> --json",),
        "the saved ClinVar reference lookup",
    ),
    Page(
        "/runs/{run_id}/secondary-findings",
        ("genetics runs secondary <run> --json",),
        "the lookup's ACMG gene-list overlaps",
    ),
    Page(
        "/runs/{run_id}/hla",
        ("genetics hla calls <run> --json",),
        "saved HLA classifier calls and the HLA-linked cards",
    ),
    Page(
        "/runs/{run_id}/pgx",
        ("genetics pgx calls <run> --json", "genetics pgx calls <run> --gene <gene> --json"),
        "saved pharmacogenomic calls, one gene's candidates, and the section's notices",
    ),
)
"""Every route but the static mount. :func:`check_routes` fails on a route not listed here."""

STATIC_MOUNT: Final[str] = "/static"
"""Stylesheets and scripts. No run is read to serve them."""


def _command_words(command: str) -> list[str]:
    """``genetics runs card <run> <card-id> --json`` as the subcommand path ``runs card``."""
    words = command.split()
    if words[0] != "genetics":
        raise ParityError(f"{command!r} does not start with `genetics`")
    return [word for word in words[1:] if not word.startswith(("<", "-"))]


def _takes_json(command: str) -> bool:
    """Whether the named command exists in the CLI and has a ``--json`` option."""
    import typer.main

    from genetics.cli.main import app

    node: Any = typer.main.get_command(app)
    for word in _command_words(command):
        node = getattr(node, "commands", {}).get(word)
        if node is None:
            return False
    return any("--json" in parameter.opts for parameter in node.params)


def check_routes() -> None:
    """Every dashboard route is listed with commands, and every listed command exists."""
    from genetics.web.app import create_app

    served = {str(getattr(route, "path", "")) for route in create_app().routes}
    listed = {page.route for page in PAGES} | {STATIC_MOUNT}
    if served - listed:
        raise ParityError(
            f"dashboard route(s) {sorted(served - listed)} are not in parity.PAGES: name the "
            "commands whose JSON holds what each shows, or it is reachable only from the UI"
        )
    if listed - served:
        raise ParityError(f"parity.PAGES lists route(s) the app does not serve: {listed - served}")
    for page in PAGES:
        for command in page.commands:
            if "--json" not in command.split() or not _takes_json(command):
                raise ParityError(f"{page.route}: `{command}` is not a command that takes --json")


# ---------------------------------------------------------------------------
# Engine calls
# ---------------------------------------------------------------------------

READ_SIDE: Final[tuple[str, ...]] = (
    "genetics.run.reads",
    "genetics.run.explain",
    "genetics.pgx.presentation",
)
"""Modules that build what the read commands print. A function one of them defines or calls
is reached from the CLI, as one a ``genetics.cli`` module calls is."""

DISPLAY_ONLY: Final[dict[str, str]] = {
    "genetics.pgs.cards.phase_coverage_text": (
        "Words a polygenic card's saved before-and-after coverage, which `runs card --json` "
        "holds under computation.result.phase_coverage."
    ),
    "genetics.run.store.run_signature": (
        "The key the dashboard uses to keep one opened run in memory. It reads file sizes "
        "and times, not the run."
    ),
}
"""Engine functions only the dashboard calls, each with the reason that is not an analysis.

:func:`check_engine_calls` requires this to equal what it finds, so an entry that stops
being true fails as a new call does."""


def _package_files(package: str) -> list[Path]:
    module = importlib.import_module(package)
    assert module.__file__ is not None
    return sorted(Path(module.__file__).parent.glob("*.py"))


def _module_file(name: str) -> Path:
    module = importlib.import_module(name)
    assert module.__file__ is not None
    return Path(module.__file__)


def _function_name(obj: Any) -> str | None:
    if inspect.isfunction(obj) and obj.__module__.startswith("genetics."):
        return f"{obj.__module__}.{obj.__qualname__}"
    return None


def engine_functions(paths: Sequence[Path]) -> set[str]:
    """Every ``genetics`` function the files at ``paths`` import or reach through a module.

    Read from the source, so a call inside a function body counts: the dashboard's routes
    import their engine functions there. Classes and constants are not listed. A class
    holds data here, and the functions that fill one are found where they are called.
    """
    found: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: dict[str, types.ModuleType] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("genetics"):
                assert node.module is not None
                source = importlib.import_module(node.module)
                for alias in node.names:
                    obj = getattr(source, alias.name, None)
                    if obj is None:
                        obj = importlib.import_module(f"{node.module}.{alias.name}")
                    if isinstance(obj, types.ModuleType):
                        modules[alias.asname or alias.name] = obj
                    elif (name := _function_name(obj)) is not None:
                        found.add(name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("genetics.") and alias.asname is not None:
                        modules[alias.asname] = importlib.import_module(alias.name)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in modules
                and (name := _function_name(getattr(modules[node.value.id], node.attr, None)))
            ):
                found.add(name)
    return found


def dashboard_only_functions() -> set[str]:
    """Engine functions ``genetics.web`` calls and the CLI's read side does not."""
    web = {
        name
        for name in engine_functions(_package_files("genetics.web"))
        if not name.startswith("genetics.web.")
    }
    read_files = [*_package_files("genetics.cli"), *(_module_file(name) for name in READ_SIDE)]
    reached = engine_functions(read_files)
    for name in READ_SIDE:
        module = importlib.import_module(name)
        reached |= {
            f"{name}.{attr}"
            for attr, obj in vars(module).items()
            if inspect.isfunction(obj) and obj.__module__ == name
        }
    return web - reached


def check_engine_calls() -> None:
    """The dashboard calls no engine function the CLI's read side does not, bar the listed."""
    only = dashboard_only_functions()
    new = only - set(DISPLAY_ONLY)
    if new:
        raise ParityError(
            f"only the dashboard calls {sorted(new)}. Have a read command print the result, "
            "or add the function to parity.DISPLAY_ONLY with the reason it is not an analysis"
        )
    stale = set(DISPLAY_ONLY) - only
    if stale:
        raise ParityError(f"parity.DISPLAY_ONLY lists {sorted(stale)}, which the CLI now reaches")


# ---------------------------------------------------------------------------
# Comparing a value with a document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Display:
    """A value that is presentation: an address, a label, paging, chart geometry."""

    why: str


@dataclass(frozen=True)
class Reached:
    """A value a command's document holds. ``compare`` raises :class:`ParityError` if not.

    ``compare(value, source, where)``: ``value`` is what the dashboard holds, ``source`` is
    what the table's caller reads documents from, and ``where`` names the value in a message.
    """

    command: str
    compare: Callable[[Any, Any, str], None]


Placed = Display | Reached


def plain(value: Any) -> Any:
    """``value`` in the shape JSON gives it back: dicts, lists, scalars."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(plain(item) for item in value)
    return value


def dig(record: Any, *path: str) -> Any:
    """A nested key, or ``None`` where one is missing, as the views read a saved record."""
    for key in path:
        if not isinstance(record, Mapping):
            return None
        record = record.get(key)
    return record


def leaves(value: Any, path: str = "") -> Iterator[tuple[str, str | float]]:
    """Every string and number ``value`` holds, each with where it sits.

    ``None`` and booleans are skipped: neither says anything a document could be searched
    for. A dataclass field listed in :data:`NESTED_DISPLAY` is skipped as display.
    """
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if value:
            yield path, value
    elif isinstance(value, int | float):
        yield path, float(value)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for item in dataclasses.fields(value):
            if (type(value), item.name) not in NESTED_DISPLAY:
                yield from leaves(getattr(value, item.name), f"{path}.{item.name}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from leaves(item, f"{path}.{key}")
    elif isinstance(value, list | tuple | set | frozenset):
        for index, item in enumerate(value):
            yield from leaves(item, f"{path}[{index}]")
    else:
        raise ParityError(f"{path}: a {type(value).__name__} cannot be compared with JSON")


def same(command: str, source: Callable[[Any], Any]) -> Reached:
    """The value equals what ``source`` reads from the command's document."""

    def compare(value: Any, documents: Any, where: str) -> None:
        if plain(value) != source(documents):
            raise ParityError(f"{where} differs from what `{command}` prints")

    return Reached(command, compare)


def within(command: str, source: Callable[[Any], Any]) -> Reached:
    """Every string and number the value holds is in what ``source`` reads.

    For a view that renames keys or keeps part of a record: the keys differ, so the values
    are what is compared.
    """

    def compare(value: Any, documents: Any, where: str) -> None:
        held = {leaf for _, leaf in leaves(source(documents))}
        for path, leaf in leaves(value, where):
            if leaf not in held:
                raise ParityError(f"{path} is not in what `{command}` prints")

    return Reached(command, compare)


def _apply(table: Mapping[str, Placed], obj: Any, source: Any, where: str, report: Report) -> None:
    """Compare each field of dataclass ``obj`` as ``table`` places it."""
    for item in dataclasses.fields(obj):
        placed = table.get(item.name)
        if placed is None:
            raise ParityError(
                f"{type(obj).__name__}.{item.name} is not placed: say which command's JSON "
                "holds it, or that it is display"
            )
        if isinstance(placed, Reached):
            placed.compare(getattr(obj, item.name), source, f"{where}.{item.name}")
            report.compared += 1


# ---------------------------------------------------------------------------
# What the CLI prints for one run
# ---------------------------------------------------------------------------


@dataclass
class Report:
    """What one :func:`check_run` compared, so a caller can tell it was not vacuous."""

    pages: int = 0
    cards: int = 0
    drawn: int = 0
    """Polygenic views compared: cards whose saved computation the dashboard draws."""
    compared: int = 0
    commands: int = 0
    templates: set[str] = field(default_factory=set)
    documents: dict[tuple[str, ...], Any] = field(default_factory=dict, repr=False)
    """Every document the commands printed, by the words that asked for it. Not in the
    ``repr``: a card document states the reader's call."""


class Documents:
    """The JSON the read commands print for one saved run, each fetched once."""

    def __init__(self, run: Path) -> None:
        if run.parent.name != "runs":
            raise ParityError("a run must sit in a directory named `runs`, as the CLI resolves it")
        self.run = run
        self.name = run.name
        self._environment = {"GENETICS_DATA_DIR": str(run.parent.parent)}
        self.report = Report()

    def cli(self, *args: str) -> Any:
        """One command's JSON document. The command is run through the real CLI."""
        from typer.testing import CliRunner

        from genetics.cli.main import app

        if args not in self.report.documents:
            result = CliRunner().invoke(app, [*args, "--json"], env=self._environment)
            if result.exit_code != 0:
                raise ParityError(f"`genetics {' '.join(args)} --json` exited {result.exit_code}")
            self.report.documents[args] = json.loads(result.stdout)
            self.report.commands += 1
        return self.report.documents[args]

    @property
    def version(self) -> Any:
        return self.cli("version")

    @property
    def listing(self) -> Any:
        return self.cli("runs", "list")

    @property
    def show(self) -> Any:
        return self.cli("runs", "show", self.name)

    @property
    def qc(self) -> Any:
        return self.cli("runs", "qc", self.name)

    @property
    def imputation(self) -> Any:
        return self.cli("runs", "imputation", self.name)

    @property
    def clinvar(self) -> Any:
        return self.cli("runs", "clinvar", self.name)

    @property
    def secondary(self) -> Any:
        return self.cli("runs", "secondary", self.name)

    @property
    def hla(self) -> Any:
        return self.cli("hla", "calls", self.name)

    def pgx(self, gene: str | None = None) -> Any:
        return self.cli("pgx", "calls", self.name, *(() if gene is None else ("--gene", gene)))

    def card(self, card_id: str) -> Any:
        return self.cli("runs", "card", self.name, card_id)

    @property
    def sections(self) -> dict[str, Any]:
        """Each of the thirteen sections' context, from one ``runs show --section`` read."""
        flags = [arg for section in SECTION_ORDER for arg in ("--section", section.value)]
        document = self.cli("runs", "show", self.name, *flags)
        return {entry["section"]: entry for entry in document["current_context"]["sections"]}

    def cards_with(self, key: str, value: str | None) -> list[Any]:
        return [card for card in self.show["cards"] if card[key] == value]


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def _card(*path: str) -> Callable[[Any], Any]:
    return lambda document: dig(document["card"], *path)


def _context(*path: str) -> Callable[[Any], Any]:
    return lambda document: dig(document["current_context"], *path)


_RUNS_CARD: Final = "runs card"

NESTED_DISPLAY: Final[dict[tuple[type, str], str]] = {
    (views.ScoreRow, "label"): "The dashboard's name for one confidence input.",
    (views.ScoreRow, "observed"): (
        "One confidence input's saved value, or two joined by a space. `runs card --json` "
        "holds each under card.confidence.inputs."
    ),
}
"""Fields of a nested view that are display. Every other field of a nested view is compared
value by value with the part of the document its card field is placed in."""

NESTED: Final[dict[type, str]] = {
    views.VariantView: "CardView.variant",
    views.EvidenceView: "CardView.evidence",
    views.EffectView: "CardView.evidence",
    views.ConfidenceView: "CardView.confidence",
    views.ScoreRow: "CardView.confidence",
    views.FrequencyView: "CardView.frequencies",
    views.CitationLink: "CardView.citations",
    views.CarrierView: "CardView.carrier",
}
"""Views held inside a card, and the card field each is compared through."""

CARD: Final[dict[str, Placed]] = {
    "card_id": same(_RUNS_CARD, _card("card_id")),
    "section": same(_RUNS_CARD, _card("section")),
    "section_title": same(_RUNS_CARD, _context("section", "title")),
    "kind": same(_RUNS_CARD, _card("kind")),
    "title": same(_RUNS_CARD, _card("title")),
    "gene": same(_RUNS_CARD, _card("gene")),
    "status": same(_RUNS_CARD, _card("status")),
    "summary": same(_RUNS_CARD, _card("summary")),
    "detail": same(_RUNS_CARD, _card("detail")),
    "impossibility_reason": same(_RUNS_CARD, _card("impossibility_reason")),
    "tier": same(_RUNS_CARD, _card("confidence_tier")),
    "variant": within(_RUNS_CARD, _card("variant")),
    "evidence": within(_RUNS_CARD, _card("evidence")),
    "confidence": within(
        _RUNS_CARD,
        lambda document: [
            document["card"]["confidence"],
            document["current_context"]["confidence"]["reason"],
        ],
    ),
    "frequencies": within(_RUNS_CARD, _card("frequencies")),
    "confidence_frequency": within(_RUNS_CARD, _card("confidence_frequency")),
    "citations": within(
        _RUNS_CARD,
        lambda document: [
            document["card"]["citations"],
            document["current_context"]["citation_links"],
        ],
    ),
    "authored_caveats": same(_RUNS_CARD, _card("authored_caveats")),
    "computed_caveats": same(_RUNS_CARD, _card("computed_caveats")),
    "observed_rsid": same(_RUNS_CARD, _card("match", "observed_rsid")),
    "call_source": same(_RUNS_CARD, _card("observation", "call_source")),
    "imputation_quality": same(_RUNS_CARD, _card("observation", "imputation_quality")),
    "ancestry_match": same(_RUNS_CARD, _card("observation", "ancestry_match")),
    "strand": same(_RUNS_CARD, _card("match", "strand")),
    "bundle_format_version": same(_RUNS_CARD, lambda document: document["format_version"]),
    "url": Display("This card's address in the dashboard, built from the run and card ids."),
    "computation": same(_RUNS_CARD, _card("computation")),
    "multi_marker": same(_RUNS_CARD, _card("multi_marker")),
    "risk_context": same(_RUNS_CARD, _card("risk_context")),
    "imputation_mode": same(_RUNS_CARD, _card("imputation_mode")),
    "imputation": same(_RUNS_CARD, _card("observation", "imputation")),
    "carrier": within(_RUNS_CARD, _card("carrier")),
}
"""Each field of :class:`~genetics.web.views.CardView`, against one ``runs card`` document."""

_DRAWN: Final = (
    "Chart geometry and its labels, drawn from computation.result.distribution and "
    "computation.result.position, which `runs card --json` holds."
)

POLYGENIC: Final[dict[str, Placed]] = {
    "pgs_id": within(_RUNS_CARD, _card("computation")),
    "trait": within(_RUNS_CARD, _card("computation")),
    "placed": same(
        _RUNS_CARD, lambda d: dig(d["card"], "computation", "result", "position") is not None
    ),
    "reason": within(_RUNS_CARD, _card("computation")),
    "bars": Display(_DRAWN),
    "band_x": Display(_DRAWN),
    "band_width": Display(_DRAWN),
    "band_label": Display(_DRAWN),
    "ticks": Display(_DRAWN),
    "reference_label": Display("Words computation.result.reference's label and sample count."),
    "ancestry_matched": Display(
        "Whether computation.result.reference.ancestry_matched is set; false for a score "
        "that was not placed."
    ),
    "reference_reason": within(_RUNS_CARD, _card("computation")),
    "phase_label": Display("Words computation.result.phase."),
    "coverage": within(_RUNS_CARD, _card("computation")),
    "quality": within(_RUNS_CARD, _card("computation")),
    "portability": within(_RUNS_CARD, _card("computation")),
    "deciles": within(_RUNS_CARD, _card("computation")),
    "decile_rows": Display(
        "Each saved decile rate as a percentage, from computation.result.authored.decile_outcomes."
    ),
    "reliability": within(_RUNS_CARD, _card("computation")),
    "licence": within(_RUNS_CARD, _card("computation")),
    "phase_coverage": within(_RUNS_CARD, _card("computation")),
}
"""Each field of the polygenic view a card builds from its saved computation."""


def _check_card(card: views.CardView, documents: Documents) -> None:
    document = documents.card(card.card_id)
    where = f"card {card.card_id}"
    _apply(CARD, card, document, where, documents.report)
    drawn = card.polygenic
    if drawn is not None:
        _apply(POLYGENIC, drawn, document, f"{where}.polygenic", documents.report)
        documents.report.drawn += 1
    documents.report.cards += 1


# ---------------------------------------------------------------------------
# The shell: selector, banner, sections, grid
# ---------------------------------------------------------------------------

_LIST: Final = "runs list"
_QC: Final = "runs qc"
_IMPUTATION: Final = "runs imputation"
_SECTION: Final = "runs show --section"
_SHOW: Final = "runs show"
_PGX: Final = "pgx calls"

RUN_OPTION: Final[dict[str, Placed]] = {
    "run_id": same(_LIST, lambda row: row["run_id"]),
    "created_at": same(_LIST, lambda row: row["created_at"]),
    "status": same(_LIST, lambda row: row["status"]),
    "vendor": same(_LIST, lambda row: row["vendor"]),
    "card_count": same(_LIST, lambda row: row["card_count"]),
    "with_interpretation": same(_LIST, lambda row: row["with_interpretation"]),
    "detail": same(_LIST, lambda row: row["detail"]),
    "selectable": same(_LIST, lambda row: row["status"] == "readable"),
}
"""A row of the run selector, against its row of ``runs list``."""

STAGING: Final[dict[str, Placed]] = {
    "run_id": same(_LIST, lambda row: row["run_id"]),
    "name": same(_LIST, lambda row: Path(row["path"]).name),
    "size_bytes": same(_LIST, lambda row: row["size_bytes"]),
}
"""An interrupted save, against its row of ``runs list``'s ``incomplete``."""


def _qc(*path: str) -> Callable[[Documents], Any]:
    return lambda documents: dig(documents.qc["qc"], *path)


def _execution(*path: str) -> Callable[[Documents], Any]:
    return lambda documents: dig(documents.qc["imputation"], *path)


def _provenance(*path: str) -> Callable[[Documents], Any]:
    return lambda documents: dig(documents.imputation["provenance"], *path)


BANNER: Final[dict[str, Placed]] = {
    "vendor": same(_QC, _qc("vendor")),
    "source_path": same(_QC, _qc("source_path")),
    "total_markers": same(_QC, _qc("call_rates", "total_markers")),
    "call_rate": same(_QC, _qc("call_rates", "call_rate")),
    "inferred_sex": same(_QC, _qc("sex", "inferred")),
    "het_haploid_calls": same(_QC, _qc("het_haploid_calls")),
    "duplicate_rsids": same(_QC, _qc("duplicates", "duplicate_rsids")),
    "duplicate_positions": same(_QC, _qc("duplicates", "duplicate_positions")),
    "build_verdict": same(_QC, _qc("build", "verdict")),
    "warnings": same(_QC, lambda documents: documents.qc["qc"].get("warnings") or []),
    "imputation_mode": same(_QC, _execution("mode")),
    "imputation_card_input": same(_QC, _execution("card_input")),
    "imputation_status": same(_QC, _execution("status")),
    "imputation_jobs": same(_QC, _execution("summary", "jobs")),
    "imputation_records": same(_QC, _execution("summary", "records")),
    "imputation_provenance_status": same(
        _QC, lambda documents: documents.qc["imputation_provenance_status"]
    ),
    "imputation_panel_version": same(_IMPUTATION, _provenance("stage", "panel_source", "version")),
    "imputation_beagle_version": same(
        _IMPUTATION, _provenance("stage", "contract", "beagle", "version")
    ),
}
"""Each field of the QC banner, against ``runs qc`` and ``runs imputation``."""


def _key(name: str) -> Callable[[Any], Any]:
    return lambda record: record[name]


SECTION: Final[dict[str, Placed]] = {
    name: same(_SECTION, _key(name))
    for name in ("section", "title", "blurb", "milestone", "card_count", "interpreted")
}
"""A row of the section nav, against that section's context in ``runs show --section``."""

ARRANGED: Final[dict[type, tuple[str, ...]]] = {
    views.Grid: ("query", "groups", "total", "shown", "tier_options", "section_options"),
    views.CardGroup: (
        "key",
        "title",
        "blurb",
        "cards",
        "total",
        "interpreted",
        "milestone",
        "related",
    ),
    views.FilterOption: ("value", "label", "count", "selected"),
    views.RelatedLink: ("card_id", "title", "section_title", "url"),
    views.GridQuery: ("group", "sort", "tiers", "sections", "interpreted_only", "ignored"),
}
"""The grid's classes, which arrange cards the run already holds. :func:`_check_grid` compares
them; the fields are pinned here so that a new one is brought to it."""

DRAWN: Final[dict[type, str]] = {
    polygenic.Bar: _DRAWN,
    polygenic.Tick: _DRAWN,
    polygenic.DecileRow: "A saved decile rate as a percentage.",
}
"""Classes that hold only chart geometry and its labels."""


def _rows(shown: Sequence[Any], listed: Sequence[Any], where: str) -> None:
    if len(shown) != len(listed):
        raise ParityError(f"{where} has a different number of rows from `runs list`")


def _check_runs(value: Any, documents: Documents, where: str) -> None:
    listed = documents.listing["runs"]
    _rows(value, listed, where)
    for option, row in zip(value, listed, strict=True):
        _apply(RUN_OPTION, option, row, f"{where}[{option.run_id}]", documents.report)


def _check_incomplete(value: Any, documents: Documents, where: str) -> None:
    listed = documents.listing["incomplete"]
    _rows(value, listed, where)
    for notice, row in zip(value, listed, strict=True):
        _apply(STAGING, notice, row, f"{where}[{notice.run_id}]", documents.report)


def _check_banner(value: Any, documents: Documents, where: str) -> None:
    if value is None:
        raise ParityError(f"{where} is missing for a run that opened")
    _apply(BANNER, value, documents, where, documents.report)


def _check_sections(value: Any, documents: Documents, where: str) -> None:
    contexts = documents.sections
    if [view.section for view in value] != list(contexts):
        raise ParityError(f"{where} lists different sections from `{_SECTION}`")
    for view in value:
        context = contexts[view.section]
        _apply(SECTION, view, context, f"{where}[{view.section}]", documents.report)
        if view.empty_reason != context["empty_reason"]:
            raise ParityError(f"{where}[{view.section}].empty_reason differs from `{_SECTION}`")


def _check_cards(value: Any, documents: Documents, where: str) -> None:
    if [card.card_id for card in value] != [card["card_id"] for card in documents.show["cards"]]:
        raise ParityError(f"{where} are not the cards `{_SHOW}` prints, in its order")
    for card in value:
        _check_card(card, documents)


def _check_grid(value: Any, documents: Documents, where: str) -> None:
    """The grid adds nothing: its cards are the run's, and its counts are counts of them."""
    saved = documents.show["cards"]
    known = set(documents.sections)
    by_section = value.query.group == views.GROUP_BY_SECTION
    if value.total != len(saved):
        raise ParityError(f"{where}.total differs from the cards `{_SHOW}` prints")
    seen: list[str] = []
    for group in value.groups:
        here = f"{where}.groups[{group.key}]"
        key = None if group.key == views.NO_TIER else group.key
        members = documents.cards_with("section" if by_section else "confidence_tier", key)
        if group.total != len(members) or not {c.card_id for c in group.cards} <= {
            c["card_id"] for c in members
        }:
            raise ParityError(f"{here} does not hold the cards `{_SHOW}` prints for it")
        interpreted = sum(1 for card in members if card["status"] in {"matched", "computed"})
        if group.interpreted != interpreted:
            raise ParityError(f"{here}.interpreted differs from the statuses `{_SHOW}` prints")
        seen.extend(card.card_id for card in group.cards)
        if by_section and group.key in known:
            context = documents.sections[group.key]
            shown = (group.title, group.blurb, group.milestone)
            if shown != (context["title"], context["blurb"], context["milestone"]):
                raise ParityError(f"{here} is framed differently from `{_SECTION}`")
            pointers = [(link.card_id, link.title, link.url is not None) for link in group.related]
            if pointers != [(p["card_id"], p["title"], p["in_run"]) for p in context["related"]]:
                raise ParityError(f"{here}.related differs from `{_SECTION}`")
        elif group.related:
            raise ParityError(f"{here}.related has pointers no command prints")
        documents.report.compared += 5
    if value.shown != len(seen) or len(seen) != len(set(seen)):
        raise ParityError(f"{where} shows a card twice, or miscounts what it shows")
    for options, key in (
        (value.tier_options, "confidence_tier"),
        (value.section_options, "section"),
    ):
        for option in options:
            wanted = None if option.value == views.NO_TIER else option.value
            if option.count != len(documents.cards_with(key, wanted)):
                raise ParityError(f"{where} filter count for {key} differs from `{_SHOW}`")
            documents.report.compared += 1


def _unknown_sections(documents: Documents) -> list[str]:
    return sorted({card["section"] for card in documents.show["cards"]} - set(documents.sections))


SHELL: Final[dict[str, Placed]] = {
    "runs_root": same(_LIST, lambda documents: documents.listing["root"]),
    "run_url": Display("The selected run's address in the dashboard, built from its id."),
    "runs": Reached(_LIST, _check_runs),
    "incomplete": Reached(_LIST, _check_incomplete),
    "selected_id": same(_QC, lambda documents: documents.qc["run_id"]),
    "banner": Reached(f"{_QC}; {_IMPUTATION}", _check_banner),
    "sections": Reached(_SECTION, _check_sections),
    "unknown_sections": same(_SHOW, _unknown_sections),
    "problem": Display(
        "Why no run is shown. A command that cannot open the run prints an error document "
        "with a kind; the dashboard words the same failure for a page."
    ),
    "card_count": same(_SHOW, lambda documents: len(documents.show["cards"])),
    "cards": Reached(_RUNS_CARD, _check_cards),
    "clinvar": same("runs clinvar", lambda documents: documents.clinvar["clinvar"]),
    "grid": Reached(f"{_SHOW}; {_SECTION}", _check_grid),
    "hla": same(_SHOW, lambda documents: documents.show["hla"]),
    "format_version": same(_QC, lambda documents: documents.qc["format_version"]),
    "pgx": same(_SHOW, lambda documents: documents.show["pgx"]),
    "pgx_framing": same(
        _PGX, lambda documents: documents.pgx()["current_context"]["section_framing"]
    ),
    "pgx_limitation": same(_PGX, lambda documents: documents.pgx()["cyp2d6_limitation"]),
    "carrier_scope": same(
        _SECTION, lambda documents: documents.sections["reproductive"]["carrier_scope"]
    ),
}
"""Each field of :class:`~genetics.web.views.Shell`, for a run that opened."""


# ---------------------------------------------------------------------------
# What each page hands its template
# ---------------------------------------------------------------------------

Compare = Callable[[Any, Documents, Mapping[str, Any], str], None]
"""``(value, documents, the whole context, where)``; raises :class:`ParityError`."""


@dataclass(frozen=True)
class Handed:
    """A template context key a command's document holds."""

    command: str
    compare: Compare


def _is(command: str, source: Callable[[Documents, Mapping[str, Any]], Any]) -> Handed:
    def compare(value: Any, documents: Documents, context: Mapping[str, Any], where: str) -> None:
        if plain(value) != source(documents, context):
            raise ParityError(f"{where} differs from what `{command}` prints")

    return Handed(command, compare)


PAGE_SIZE: Final[int] = 100
"""Loci and candidates per dashboard page. The CLI's document holds all of them."""

_PAGING: Final = Display("Paging. The command's document holds every row, not one page of it.")


def _loci(documents: Documents, context: Mapping[str, Any]) -> list[Any]:
    if context["secondary_only"]:
        record = documents.secondary["secondary"]
    else:
        record = documents.clinvar["clinvar"]
    return [] if record is None else list(record["loci"])


def _page_of(rows: Sequence[Any], number: int) -> list[Any]:
    return list(rows[(number - 1) * PAGE_SIZE : number * PAGE_SIZE])


def _benchmark_links(
    value: Any, documents: Documents, context: Mapping[str, Any], where: str
) -> None:
    """Each link ends in the DOI the saved record gives for that variation's benchmark."""
    dois = {
        entry["variation_id"]: dig(entry, "reliability", "empirical_ppv", "doi")
        for locus in _loci(documents, context)
        for entry in locus["records"]
    }
    for variation, url in value.items():
        doi = dois.get(variation)
        if not isinstance(doi, str) or not isinstance(url, str) or not url.endswith(doi):
            raise ParityError(f"{where} links a benchmark the command's document does not name")


def _policy_link(value: Any, documents: Documents, context: Mapping[str, Any], where: str) -> None:
    """The ACMG policy link ends in the DOI the saved roster's provenance records."""
    doi = dig(documents.clinvar["clinvar"], "secondary_reference", "provenance", "doi")
    if doi is not None and not str(value).endswith(doi):
        raise ParityError(f"{where} is not the policy the saved roster cites")


def _hla_cards(value: Any, documents: Documents, context: Mapping[str, Any], where: str) -> None:
    """The page's cards are the run's own, and the ones ``hla calls`` lists."""
    shell = context["shell"]
    if any(card not in shell.cards for card in value):
        raise ParityError(f"{where} holds a card the run does not")
    listed = [card["card_id"] for card in documents.hla["linked_cards"]]
    if [card.card_id for card in value] != listed:
        raise ParityError(f"{where} are not the linked cards `hla calls` prints")


def _report_keys(command: str, document: Callable[[Documents, Mapping[str, Any]], Any]) -> Handed:
    """A saved-record report, key for key as the command's document holds it."""

    def compare(value: Any, documents: Documents, context: Mapping[str, Any], where: str) -> None:
        printed = document(documents, context)
        if any(key not in printed or plain(item) != printed[key] for key, item in value.items()):
            raise ParityError(f"{where} differs from what `{command}` prints")

    return Handed(command, compare)


def _pgx_document(documents: Documents, context: Mapping[str, Any]) -> Any:
    return documents.pgx(context["pgx_gene"])


def _candidates(documents: Documents, context: Mapping[str, Any]) -> list[Any]:
    gene = context["pgx_gene"]
    if gene is None:
        return []
    return list(dig(documents.pgx(gene), "genes", gene, "candidates") or [])


def _the_card(value: Any, documents: Documents, context: Mapping[str, Any], where: str) -> None:
    """The page's card is one of the run's, each of which is compared with ``runs card``."""
    if value is not None and value not in context["shell"].cards:
        raise ParityError(f"{where} is not one of the run's cards")


Template = dict[str, Handed | Display]

_FRAME: Final[Template] = {
    "shell": Display("Compared field by field; see parity.SHELL."),
    "engine_version": _is("version", lambda documents, _: documents.version["version"]),
    "bundle_format_version": _is(
        "version", lambda documents, _: documents.version["bundle_format_version"]
    ),
    "runselector_html": Display("The run selector's markup, rendered from `shell`."),
    "qcbanner_html": Display("The QC banner's markup, rendered from `shell`."),
}
_CARD_PAGE: Final[Template] = {
    "card": Handed(_RUNS_CARD, _the_card),
    "problem": Display(
        "Why no card is shown. `runs card` prints an error of kind card-not-found for the same id."
    ),
}

CONTEXT: Final[dict[str, Template]] = {
    "dashboard.html": _FRAME,
    "card.html": _FRAME | _CARD_PAGE,
    "_carddialog.html": {"shell": _FRAME["shell"]} | _CARD_PAGE,
    "clinvar.html": _FRAME
    | {
        "clinvar_loci": _is(
            "runs clinvar; runs secondary",
            lambda documents, context: _page_of(_loci(documents, context), context["clinvar_page"]),
        ),
        "clinvar_total": _is(
            "runs clinvar; runs secondary",
            lambda documents, context: len(_loci(documents, context)),
        ),
        "clinvar_page": _PAGING,
        "clinvar_pages": _PAGING,
        "clinvar_start": _PAGING,
        "clinvar_benchmark_urls": Handed("runs clinvar; runs secondary", _benchmark_links),
        "acmg_policy_url": Handed("runs clinvar", _policy_link),
        "secondary_only": Display("Which of the two routes was asked for."),
        "clinvar_view_url": Display("This page's own address."),
    },
    "hla.html": _FRAME
    | {
        "hla_report": _report_keys("hla calls", lambda documents, _: documents.hla),
        "hla_cards": Handed("hla calls; runs card", _hla_cards),
        "hla_cards_recorded": _is(
            "hla calls",
            lambda documents, _: documents.hla["linked_cards_status"] == "recorded",
        ),
    },
    "pgx.html": _FRAME
    | {
        "pgx_report": _report_keys(_PGX, _pgx_document),
        "pgx_gene": Display("The gene asked for in the address; `pgx calls --gene` takes it."),
        "pgx_candidates": _is(
            _PGX,
            lambda documents, context: _page_of(
                _candidates(documents, context), context["pgx_page"]
            ),
        ),
        "pgx_total": _is(_PGX, lambda documents, context: len(_candidates(documents, context))),
        "pgx_page": _PAGING,
        "pgx_pages": _PAGING,
    },
}
"""Every key each page's template is handed. A key that is not here fails :func:`check_run`."""

HEALTH: Final[dict[str, Handed | Display]] = {
    "ok": Display("Whether the runs directory could be listed. `runs list` fails when not."),
    "engine_version": _is("version", lambda documents, _: documents.version["version"]),
    "bundle_format_version": _is(
        "version", lambda documents, _: documents.version["bundle_format_version"]
    ),
    "runs_root": _is(_LIST, lambda documents, _: documents.listing["root"]),
    "run_count": _is(_LIST, lambda documents, _: len(documents.listing["runs"])),
    "detail": Display(
        "A sentence counting the damaged and newer-format rows, which `runs list` lists."
    ),
}
"""Each key of the ``/healthz`` document."""


# ---------------------------------------------------------------------------
# The census: every view class, field and property is accounted for
# ---------------------------------------------------------------------------

TABLES: Final[dict[type, Mapping[str, Placed]]] = {
    views.Shell: SHELL,
    views.QCBanner: BANNER,
    views.SectionView: SECTION,
    views.RunOption: RUN_OPTION,
    views.StagingNotice: STAGING,
    views.CardView: CARD,
    polygenic.PolygenicView: POLYGENIC,
}

PROPERTIES: Final[dict[type, tuple[str, ...]]] = {
    views.QCBanner: ("call_rate_percent", "markers_display"),
    views.SectionView: ("empty_reason", "is_empty"),
    views.RunOption: ("url",),
    views.StagingNotice: ("size_display",),
    views.CitationLink: ("label",),
    views.EffectView: ("display", "is_absolute", "is_relative", "measure_label"),
    views.EvidenceView: (
        "populations_display",
        "replication_label",
        "sample_size_display",
        "tier_label",
    ),
    views.FrequencyView: ("display",),
    views.VariantView: ("locus",),
    views.CarrierView: ("clinvar_url", "state_label"),
    views.ScoreRow: ("score_display",),
    views.ConfidenceView: ("clinical_notice", "has_ppv", "ppv_caution", "ppv_display", "ppv_url"),
    views.CardView: (
        "base_rate_note",
        "effect",
        "evidence_absence",
        "frequency_absence",
        "has_a_call",
        "has_distinct_detail",
        "imputation_mode_label",
        "imputation_quality_note",
        "is_computed",
        "is_hla",
        "is_impossibility",
        "is_interpreted",
        "is_polygenic",
        "marker_confidences",
        "polygenic",
        "roh",
        "scope_allele_classes",
        "scope_mechanisms",
        "status_label",
        "tier_is_known",
        "tier_key",
        "tier_label",
        "tier_rank",
    ),
    views.GridQuery: ("is_filtered", "parameters", "query_string"),
    views.RelatedLink: (),
    views.CardGroup: ("empty_reason", "hidden", "is_empty"),
    views.FilterOption: (),
    views.Grid: ("hidden", "is_filtered"),
    views.Shell: ("has_selection", "placed_cards", "total_interpreted"),
    polygenic.Bar: (),
    polygenic.Tick: ("anchor",),
    polygenic.DecileRow: (),
    polygenic.PolygenicView: (
        "band_label_anchor",
        "band_label_x",
        "coverage_display",
        "phase_coverage_display",
        "portability_display",
        "quality_display",
    ),
}
"""Every property of every view class. A property words, labels, counts or arranges what its
object already holds; it is not compared. Listed so that a new one is read by a person who
asks whether it is an analysis, which belongs in the engine (AGENTS.md 3)."""


def view_classes() -> list[type]:
    """Every dataclass ``genetics.web.views`` and ``genetics.web.polygenic`` define."""
    return [
        obj
        for module in (views, polygenic)
        for obj in vars(module).values()
        if inspect.isclass(obj)
        and dataclasses.is_dataclass(obj)
        and obj.__module__ == module.__name__
    ]


def check_views() -> None:
    """Every view class is placed, field for field, and its properties are the listed ones."""
    for cls in view_classes():
        name = cls.__name__
        fields = {item.name for item in dataclasses.fields(cls)}
        if cls in TABLES:
            placed = set(TABLES[cls])
        elif cls in ARRANGED:
            placed = set(ARRANGED[cls])
        elif cls in NESTED or cls in DRAWN:
            placed = fields
        else:
            raise ParityError(
                f"view class {name} is not in parity's tables: place each field against a "
                "command's JSON, or say why the class is display"
            )
        if placed != fields:
            raise ParityError(
                f"{name}: field(s) {sorted(placed ^ fields)} are in the class or in its "
                "parity table and not in both"
            )
        properties = {key for key, item in vars(cls).items() if isinstance(item, property)}
        if properties != set(PROPERTIES.get(cls, ())):
            raise ParityError(
                f"{name}: propert(ies) {sorted(properties ^ set(PROPERTIES.get(cls, ())))} "
                "differ from parity.PROPERTIES. A property may word or arrange what its "
                "object holds; an analysis belongs in the engine, where a command prints it"
            )
    for cls, item in NESTED_DISPLAY:
        if cls not in NESTED or item not in {f.name for f in dataclasses.fields(cls)}:
            raise ParityError(f"parity.NESTED_DISPLAY names {cls.__name__}.{item}, which is gone")


# ---------------------------------------------------------------------------
# One saved run, page by page
# ---------------------------------------------------------------------------

LOCAL: Final[str] = "http://127.0.0.1:8765"


class _Recorder:
    """Records the context each template is rendered with."""

    def __init__(self, application: Any) -> None:
        from jinja2 import Template as JinjaTemplate

        self.rendered: list[tuple[str, dict[str, Any]]] = []
        recorder = self

        class Recording(JinjaTemplate):
            def render(self, *args: Any, **kwargs: Any) -> str:
                recorder.rendered.append((str(self.name), dict(*args, **kwargs)))
                return super().render(*args, **kwargs)

        # Set before any template is loaded, so every one the app renders is a Recording.
        application.state.environment.template_class = Recording

    def page(self) -> tuple[str, dict[str, Any]]:
        """The last template rendered: the page, after the two scanned partials."""
        if not self.rendered:
            raise ParityError("the route rendered no template")
        return self.rendered[-1]


def check_run(run: Path) -> Report:
    """Compare every dashboard page of the saved run at ``run`` with what the CLI prints.

    ``run`` is the bundle's directory, inside a directory named ``runs``. Raises
    :class:`ParityError` at the first difference. The run is read through the real app and
    the real commands; nothing is written.
    """
    from fastapi.testclient import TestClient

    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    documents = Documents(run)
    report = documents.report
    application = create_app(WebConfig(runs_root=run.parent))
    recorder = _Recorder(application)
    base = f"/runs/{run.name}"

    with TestClient(application, base_url=LOCAL) as client:

        def render(address: str, *, fragment: bool = False) -> tuple[str, dict[str, Any]]:
            recorder.rendered.clear()
            headers = {"HX-Request": "true"} if fragment else {}
            response = client.get(address, headers=headers)
            if response.status_code != 200:
                raise ParityError(f"{address} answered {response.status_code}")
            report.pages += 1
            return recorder.page()

        def check(address: str, *, fragment: bool = False, whole: bool = False) -> dict[str, Any]:
            """One page. ``whole`` also compares the shell, which is the same on every page."""
            template, context = render(address, fragment=fragment)
            table = CONTEXT.get(template)
            if table is None:
                raise ParityError(f"{address} renders {template}, which parity.CONTEXT omits")
            for key, value in context.items():
                handed = table.get(key)
                if handed is None:
                    raise ParityError(
                        f"{address} hands {template} `{key}`, which is not placed: say which "
                        "command's JSON holds it, or that it is display"
                    )
                if isinstance(handed, Handed):
                    handed.compare(value, documents, context, f"{address} `{key}`")
                    report.compared += 1
            shell = context["shell"]
            if shell.selected_id != run.name or shell.problem is not None:
                raise ParityError(f"{address} did not open the run")
            if whole:
                _apply(SHELL, shell, documents, f"{address} shell", report)
            report.templates.add(template)
            return context

        health = client.get("/healthz").json()
        report.pages += 1
        for key, value in health.items():
            placed = HEALTH.get(key)
            if placed is None:
                raise ParityError(f"/healthz `{key}` is not placed")
            if isinstance(placed, Handed):
                placed.compare(value, documents, health, f"/healthz `{key}`")
                report.compared += 1

        # The index opens the newest run that `runs list` reports readable.
        _, front = render("/")
        readable = [
            row["run_id"] for row in documents.listing["runs"] if row["status"] == "readable"
        ]
        if front["shell"].selected_id != (readable[0] if readable else None):
            raise ParityError("/ did not open the newest run `runs list` reports readable")

        context = check(base, whole=True)
        check(f"{base}?group=tier", whole=True)
        cards = context["shell"].cards
        for index, card in enumerate(cards):
            shown = check(card.url)
            if shown["card"] != card:
                raise ParityError(f"{card.url} shows a different card from the dashboard's")
            if index == 0:
                check(card.url, fragment=True)
        missing = check(f"{base}/cards/no-such-card")
        if missing["card"] is not None:
            raise ParityError("a card id the run does not hold opened a card")

        for address in (f"{base}/clinvar", f"{base}/secondary-findings"):
            first = check(address)
            for number in range(2, first["clinvar_pages"] + 1):
                check(f"{address}?page={number}")
        check(f"{base}/hla")
        overview = check(f"{base}/pgx")
        for gene in overview["pgx_report"]["genes"]:
            first = check(f"{base}/pgx?gene={gene}")
            for number in range(2, first["pgx_pages"] + 1):
                check(f"{base}/pgx?gene={gene}&page={number}")

    return report
