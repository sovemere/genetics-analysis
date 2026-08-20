"""What the dashboard renders, as data (roadmap M4.5).

Templates get plain frozen dataclasses, never a :class:`~genetics.run.bundle.RunBundle` or a
raw manifest mapping. Three reasons, in the order they bite:

* **A bundle read is a read of what another version wrote.** ``read_bundle`` returns strings
  and mappings rather than engine enums precisely so a months-old run fails with a *version*
  error or not at all ([M4.1](../../phase1_roadmap.md)). A template reaching into
  ``bundle.qc["call_rates"]["call_rate"]`` re-introduces exactly the fragility that decision
  removed, except now it surfaces as a Jinja ``UndefinedError`` mid-page instead of at the
  boundary.
* **Every rule about what the shell must show is testable here without HTTP.** "No silent
  empty sections" is a property of :func:`section_views`, not of markup, and asserting it
  against rendered HTML would mean asserting against a string that changes every time
  someone edits a heading.
* **The genotype-free half of the page is a *region*, not the page.** See
  :func:`~genetics.web.app.create_app`: M4.6 puts card faces on this same page and those
  state the reader's genotype by design. Splitting the model here is what lets the scan
  cover the banner and the selector and stop there, instead of being switched off wholesale
  the moment cards land ([M0.3](../../phase1_roadmap.md)).

**Everything out of a bundle is read with ``.get``.** The manifest and QC payload are
described by whatever engine wrote them, and a dashboard that raised on a missing key would
fail to render the run *because* the run is the one worth looking at -- which is
``summarise_run``'s rule, and the same reason ``runs list`` reports damage as a row.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from genetics.engine import sections
from genetics.engine.sections import Section
from genetics.run.bundle import RunBundle, StoredCard
from genetics.run.store import RunListing, RunStatus, RunSummary

__all__ = [
    "MATCHED",
    "QCBanner",
    "RunOption",
    "SectionView",
    "Shell",
    "StagingNotice",
    "banner_for",
    "section_views",
    "shell_for",
    "unknown_sections",
]

MATCHED = "matched"
"""The one match status this module compares against, as the *string* a bundle stores.

Not ``MatchStatus.MATCHED``: a stored card's ``status`` is a string by design, and coercing
it back into the enum here would make a bundle written by a newer engine -- with a status
this version has never heard of -- raise on a page whose job is to display it.
"""


def _get(mapping: Mapping[str, Any] | None, *path: str) -> Any:
    """Walk nested keys, returning ``None`` the moment one is missing or not a mapping."""
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _number(value: Any) -> float | None:
    """A finite number, or ``None``.

    Three rejections, and the third is the one that was missing. Booleans, because ``True``
    is not a call rate. Non-numerics, because a bundle is a file another version wrote. And
    **non-finite floats**: ``json.loads`` accepts bare ``NaN`` and ``Infinity`` by default
    and ``_load_json`` does not restrict it, so a QC payload carrying ``NaN`` rendered as
    ``nan%`` in the banner -- the exact shape this function's docstring already claimed to
    catch.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _count(value: Any) -> int | None:
    """A whole-number count, or ``None``.

    ``call_rate`` went through :func:`_number` from the start and the counts did not, which
    is the asymmetry that mattered: ``markers_display`` formats with ``:,``, and that raises
    ``ValueError`` on a string. A ``qc.run.json`` written by another engine -- the case this
    module exists to render -- took the whole dashboard down with a 500 instead of showing
    a dash.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


@dataclass(frozen=True)
class QCBanner:
    """The QC line above the sections.

    Manifest- and QC-derived only, which is what makes it scannable. Every field is
    optional because every one of them comes out of a file another version may have written
    differently, and a banner that cannot render is a banner on the run somebody most needs
    to look at.

    ``warnings`` are carried verbatim and never truncated: they are ordered
    most-consequential-first by QC and AGENTS.md 0.1A is explicit that the job is to label,
    not to filter. A "show more" that hides the third warning is a filter.
    """

    vendor: str | None
    source_path: str | None
    total_markers: int | None
    call_rate: float | None
    inferred_sex: str | None
    het_haploid_calls: int | None
    duplicate_rsids: int | None
    duplicate_positions: int | None
    build_verdict: str | None
    warnings: tuple[str, ...]

    @property
    def call_rate_percent(self) -> str:
        return "-" if self.call_rate is None else f"{self.call_rate:.2%}"

    @property
    def markers_display(self) -> str:
        return "-" if self.total_markers is None else f"{self.total_markers:,}"


def _warnings(raw: Any) -> tuple[str, ...]:
    """QC's warning list, or empty.

    ``str`` is excluded explicitly because it is a ``Sequence``: the obvious isinstance
    check turns a warnings field of ``"oops"`` into four warnings reading o, o, p, s. Items
    are coerced with ``str`` rather than trusted, since a mapping in that list would render
    as a Python repr on the page.
    """
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        return ()
    return tuple(str(item) for item in raw)


def banner_for(bundle: RunBundle) -> QCBanner:
    """Build the QC banner from a bundle's stored QC report."""
    qc = bundle.qc
    return QCBanner(
        vendor=_get(qc, "vendor"),
        source_path=_get(qc, "source_path"),
        total_markers=_count(_get(qc, "call_rates", "total_markers")),
        call_rate=_number(_get(qc, "call_rates", "call_rate")),
        inferred_sex=_get(qc, "sex", "inferred"),
        het_haploid_calls=_count(_get(qc, "het_haploid_calls")),
        # Two counts, not one. `DuplicateSummary` carries `duplicate_rsids` and
        # `duplicate_positions` and they mean different things -- an rsID repeats after a
        # dbSNP merge, two probes repeat a position -- so collapsing them would be inventing
        # a third quantity. The first cut read a `duplicate_rows` key that no QC payload has
        # ever contained, so the banner said "-" on every run ever saved while looking like
        # a measurement.
        duplicate_rsids=_count(_get(qc, "duplicates", "duplicate_rsids")),
        duplicate_positions=_count(_get(qc, "duplicates", "duplicate_positions")),
        build_verdict=_get(qc, "build", "verdict"),
        warnings=_warnings(qc.get("warnings")),
    )


@dataclass(frozen=True)
class SectionView:
    """One of the thirteen sections, as the nav shows it.

    ``card_count`` and ``interpreted`` come from the *bundle*, not the knowledge pack: what
    the nav must describe is this saved run, and a run written before a section was built
    genuinely has nothing in it no matter what the current pack holds.
    """

    section: str
    title: str
    blurb: str
    milestone: str
    card_count: int
    interpreted: int

    @property
    def is_empty(self) -> bool:
        return self.card_count == 0

    @property
    def empty_reason(self) -> str | None:
        """Why this section shows nothing, or ``None`` when it shows something.

        The definition of done (item 3) forbids a silent empty section, and the two ways a
        section can be empty need different sentences: **no cards exist yet** is a fact
        about this tool's progress and names the milestone that fixes it, while **cards
        exist and none produced an interpretation** is a fact about this genome and is not a
        defect at all. Collapsing them into "nothing here" would tell a reader their array
        lacks a marker when the truth is nobody has written the card.
        """
        if self.card_count == 0:
            return f"Not built yet — roadmap {self.milestone}."
        if self.interpreted == 0:
            return (
                f"{self.card_count} card(s) here, none of which produced an interpretation "
                "for this genome. Each one states its own reason."
            )
        return None


def section_views(cards: Sequence[StoredCard]) -> tuple[SectionView, ...]:
    """All thirteen sections in AGENTS.md 3.1 order, always, counts filled in from ``cards``.

    **Every section is returned even when it holds nothing**, which is the whole point: a
    nav built by grouping the cards present would silently be a nav of however many sections
    happen to be populated, and a reader would have no way to tell a section that is empty
    from one that does not exist. That is the failure the no-silent-empty-sections rule
    names, arriving through the navigation rather than through the content.

    A card whose section this engine does not recognise is counted under no section and is
    **not** dropped silently -- see :func:`unknown_sections`.
    """
    counted: dict[str, list[StoredCard]] = {section.value: [] for section in sections.SECTION_ORDER}
    for card in cards:
        if card.section in counted:
            counted[card.section].append(card)

    views: list[SectionView] = []
    for section in sections.SECTION_ORDER:
        info = sections.SECTIONS[section]
        here = counted[section.value]
        views.append(
            SectionView(
                section=section.value,
                title=info.title,
                blurb=info.blurb,
                milestone=info.milestone,
                card_count=len(here),
                interpreted=sum(1 for card in here if card.status == MATCHED),
            )
        )
    return tuple(views)


def unknown_sections(cards: Sequence[StoredCard]) -> tuple[str, ...]:
    """Section names in the bundle that this engine's :class:`Section` does not define.

    Reported rather than ignored. A bundle written by a newer engine may carry a fourteenth
    section, and its cards would otherwise vanish from a nav built on this version's thirteen
    -- indistinguishable from cards that did not match, which is the exact confusion
    ``UnknownSectionError`` exists to prevent at card-load time.
    """
    known = {section.value for section in Section}
    return tuple(sorted({card.section for card in cards} - known))


@dataclass(frozen=True)
class RunOption:
    """One row in the run selector."""

    run_id: str
    created_at: str | None
    status: str
    vendor: str | None
    card_count: int | None
    with_interpretation: int | None
    detail: str | None
    selectable: bool
    """Whether opening it can work. False for damaged and future-version runs.

    Listed anyway, and this is deliberate: hiding an unopenable run is how somebody
    concludes their run was deleted. It is shown with its status and its reason, which is
    what ``runs list`` does for the same rows.
    """

    @classmethod
    def of(cls, summary: RunSummary) -> RunOption:
        return cls(
            run_id=summary.run_id,
            created_at=summary.created_at,
            status=str(summary.status),
            vendor=summary.vendor,
            card_count=summary.card_count,
            with_interpretation=summary.with_interpretation,
            detail=summary.detail,
            selectable=summary.status is RunStatus.READABLE,
        )


@dataclass(frozen=True)
class StagingNotice:
    """An interrupted save, surfaced rather than skipped.

    ``list_runs`` counts and sizes these instead of stepping over them, because a stale
    multi-gigabyte intermediate reported as nothing at all is the M3.3-M3.6 finding about
    ``refs status``. The dashboard inherits the decision rather than re-making it.
    """

    run_id: str
    """The id the interrupted write was claiming, prefix stripped.

    Shown rather than the directory name, because that id is still free -- nothing was ever
    promoted to it -- so it is the thing that tells a reader the run they were saving is
    simply absent rather than half-present under some other name. ``name`` is carried too,
    since ``genetics runs prune`` is what removes it and the directory is what they will see.
    """

    name: str
    size_bytes: int

    @property
    def size_display(self) -> str:
        n = self.size_bytes
        if n >= 1_000_000_000:
            return f"{n / 1e9:.2f} GB"
        if n >= 1_000_000:
            return f"{n / 1e6:.1f} MB"
        return f"{n:,} B"


@dataclass(frozen=True)
class Shell:
    """Everything the dashboard shell renders for one request.

    ``NoGenotypeRepr`` is not inherited and does not need to be: nothing on this object is
    genotype-derived. That stops being true at M4.6, when the card list joins it -- which is
    the moment to add it, and the reason this sentence is here.
    """

    runs_root: str
    runs: tuple[RunOption, ...]
    incomplete: tuple[StagingNotice, ...]
    selected_id: str | None
    banner: QCBanner | None
    sections: tuple[SectionView, ...]
    unknown_sections: tuple[str, ...]
    problem: str | None
    """Why no run is displayed, when none is. ``None`` when one is showing.

    Populated for an unreadable store, an empty store, a run id that names nothing, and a
    run that will not open. All four are states a person arrives in, and all four get a
    sentence rather than a stack trace or a blank page.
    """

    @property
    def has_selection(self) -> bool:
        return self.banner is not None

    card_count: int
    """Every card in the run, including any under a section this version cannot place.

    Carried rather than summed from :attr:`sections`, which counts only the thirteen known
    ones. With a newer engine's fourteenth section in the bundle, a sum would print a card
    total smaller than the ``card_count`` the run selector shows from the manifest on the
    same page -- two numbers disagreeing with nothing to explain the gap, while the
    unknown-section notice says only that those cards are missing from the *navigation*.
    """

    @property
    def placed_cards(self) -> int:
        """Cards the nav can actually show. Below :attr:`card_count` only for a newer
        engine's sections, which is exactly when the difference is worth seeing."""
        return sum(view.card_count for view in self.sections)

    @property
    def total_interpreted(self) -> int:
        return sum(view.interpreted for view in self.sections)


def shell_for(
    listing: RunListing,
    bundle: RunBundle | None,
    *,
    selected_id: str | None = None,
    problem: str | None = None,
) -> Shell:
    """Assemble the shell model.

    ``bundle`` is ``None`` whenever there is nothing to show, and ``problem`` says why. The
    two are separate arguments rather than one union because the caller knows which of the
    four cases it is in and the message it produces is different in each -- inferring it
    from a ``None`` here would collapse them back into "no run".
    """
    return Shell(
        runs_root=str(listing.root),
        runs=tuple(RunOption.of(summary) for summary in listing.runs),
        incomplete=tuple(
            StagingNotice(run_id=item.run_id, name=item.path.name, size_bytes=item.size_bytes)
            for item in listing.incomplete
        ),
        # The **directory name**, not the manifest's ``run_id``. ``summarise_run`` already
        # settled which wins: "the directory name wins, because it is what `delete` and
        # `load` resolve against". When someone renames a bundle directory the two disagree,
        # and taking the manifest's id meant the selector marked no option as current and
        # the page printed a `genetics runs show <id>` that `runs show` cannot resolve --
        # advice that fails for the one run it was given about.
        selected_id=selected_id if bundle is None else bundle.path.name,
        banner=None if bundle is None else banner_for(bundle),
        # The thirteen sections render even with no run open, so the nav is the same shape
        # on an empty store as on a full one. A nav that appears only once a run is loaded
        # makes an empty dashboard look broken rather than empty.
        sections=section_views(() if bundle is None else bundle.cards),
        unknown_sections=() if bundle is None else unknown_sections(bundle.cards),
        card_count=0 if bundle is None else len(bundle.cards),
        problem=problem,
    )
