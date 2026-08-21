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
from typing import Any, ClassVar
from urllib.parse import quote, urlencode

from genetics.engine import sections
from genetics.engine.cards import EffectMeasure, EvidenceTier, Replication
from genetics.engine.citations import citation_url
from genetics.engine.confidence import ConfidenceTier
from genetics.engine.matcher import MatchStatus
from genetics.engine.sections import Section
from genetics.privacy import NoGenotypeRepr
from genetics.run.bundle import EVIDENCE_FORMAT_VERSION as _EVIDENCE_FORMAT_VERSION
from genetics.run.bundle import RunBundle, StoredCard
from genetics.run.store import RunListing, RunStatus, RunSummary

__all__ = [
    "ABSOLUTE_MEASURES",
    "GROUPS",
    "GROUP_BY_SECTION",
    "GROUP_BY_TIER",
    "MATCHED",
    "NO_TIER",
    "RELATIVE_MEASURES",
    "SORTS",
    "SORT_BY_SECTION",
    "SORT_BY_TIER",
    "SORT_BY_TITLE",
    "TIER_ORDER",
    "CardGroup",
    "CardView",
    "CitationLink",
    "ConfidenceView",
    "EffectView",
    "EvidenceView",
    "FilterOption",
    "FrequencyView",
    "Grid",
    "GridQuery",
    "QCBanner",
    "RunOption",
    "ScoreRow",
    "SectionView",
    "Shell",
    "StagingNotice",
    "VariantView",
    "banner_for",
    "card_path",
    "card_views",
    "filterable_sections",
    "filterable_tiers",
    "find_card",
    "grid_for",
    "parse_query",
    "run_path",
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


def run_path(run_id: str | None) -> str:
    """The dashboard URL for a run, with the id encoded as a single path segment.

    **Every link this app builds goes through here**, rather than each template writing
    ``"/runs/" ~ id``. Concatenating was wrong in a way only a hostile id shows: a run id is
    a *directory name on disk*, and ``list_runs`` reports whatever it finds rather than only
    the names ``check_run_id`` would have written -- so ``/runs/evil%3Fgroup=tier`` produced
    nav links reading ``/runs/evil?group=tier#section-ancestry``, a query string injected
    into every link on the page from a value the reader never chose. The same string in a
    card id, with a ``#`` in it, silently truncates the URL and makes the card unopenable.

    Neither is an escape -- Jinja's autoescaping keeps it inside the attribute -- but both
    are a URL built from unvalidated content, which is the habit ``runselector`` in app.js
    was already written against ("the id here came out of a ``<select>`` in a document, not
    out of the store"). One function means it cannot be forgotten in the next template.

    ``safe=""`` because a run id is one segment: a ``/`` in it must not become a path
    separator that resolves somewhere else.
    """
    return "/" if not run_id else f"/runs/{quote(run_id, safe='')}"


def card_path(run_id: str | None, card_id: str) -> str:
    """The URL for one card. See :func:`run_path` for why this is not string concatenation."""
    base = run_path(run_id)
    return f"{base}/cards/{quote(card_id, safe='')}"


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

    @property
    def url(self) -> str:
        """This run's dashboard address, id encoded. See :func:`run_path`."""
        return run_path(self.run_id)

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


# ---------------------------------------------------------------------------
# Cards (roadmap M4.6)
# ---------------------------------------------------------------------------


_TIER_LABELS: Mapping[str, str] = {
    ConfidenceTier.WELL_ESTABLISHED.value: "Well established",
    ConfidenceTier.STRONG.value: "Strong",
    ConfidenceTier.MODERATE.value: "Moderate",
    ConfidenceTier.LIMITED.value: "Limited",
    ConfidenceTier.LIKELY_ARTIFACT.value: "Likely artifact",
}
"""Display text per tier, keyed by the *stored string*.

Keyed by string rather than by :class:`ConfidenceTier` for the reason :data:`MATCHED` gives:
a bundle written by a newer engine may carry a tier this version has never heard of, and
``ConfidenceTier(value)`` on the display path would raise on the page whose job is to show
it. An unrecognised tier is labelled from its own text and sorted after the known ones --
visible, marked, and not pretending to be one of ours.

``tests/web/test_views.py`` asserts this covers every member, so adding a tier forces a
decision about how it reads rather than defaulting to a raw slug on a card face.
"""

_TIER_BLURBS: Mapping[str, str] = {
    ConfidenceTier.WELL_ESTABLISHED.value: (
        "Clinical-guideline or expert-curated evidence, replicated, on a call this array "
        "makes reliably."
    ),
    ConfidenceTier.STRONG.value: "Replicated evidence with a clear effect on a reliable call.",
    ConfidenceTier.MODERATE.value: (
        "Real evidence with a limit somewhere — the effect, the replication, the population "
        "match, or the call itself."
    ),
    ConfidenceTier.LIMITED.value: (
        "Thin evidence, a conflicting literature, or an observation this array is not good "
        "at. Read the breakdown before you read the finding."
    ),
    ConfidenceTier.LIKELY_ARTIFACT.value: (
        "The observation itself is probably wrong, most often a rare heterozygous chip call "
        "or a failed imputation. Shown because hiding it would leave you unable to tell it "
        "from a finding nobody looked for (AGENTS.md §0.1A)."
    ),
}

TIER_ORDER: tuple[str, ...] = tuple(tier.value for tier in ConfidenceTier)
"""Strongest first. :class:`ConfidenceTier` is declared in that order and its ``rank`` agrees."""

_UNKNOWN_TIER_RANK: int = len(TIER_ORDER)
_NO_TIER_RANK: int = len(TIER_ORDER) + 1

NO_TIER: str = "untiered"
"""The group key and URL value for a card with no tier, which is every card that did not match.

A real string rather than ``None`` because it is a group heading, a query parameter and a
CSS class at once, and threading ``None`` through those three ends with the word ``None``
printed on the page. Asserted not to collide with any :class:`ConfidenceTier` member.
"""

_STATUS_LABELS: Mapping[str, str] = {
    MatchStatus.MATCHED.value: "Interpreted",
    MatchStatus.NOT_DETERMINABLE.value: "Not determinable by this assay",
    MatchStatus.MARKER_ABSENT.value: "Marker not on this array",
    MatchStatus.NO_CALL.value: "No call",
    MatchStatus.ALLELE_MISMATCH.value: "Allele mismatch",
    MatchStatus.INDEL_EXCLUDED.value: "Indel excluded",
    MatchStatus.HET_HAPLOID.value: "Heterozygous at a haploid locus",
    MatchStatus.DUPLICATE_CONFLICT.value: "Probes disagree",
    MatchStatus.STRAND_AMBIGUOUS.value: "Strand ambiguous",
}
"""Short display text per match status. Same string-keyed rule as :data:`_TIER_LABELS`.

These are *labels*, not explanations. The explanation is already on the card: for every
status but ``matched`` the engine writes ``match.reason`` into the summary, and those
sentences separate absent from no-call from conflict far better than a badge can.
"""

_EVIDENCE_TIER_LABELS: Mapping[str, str] = {
    EvidenceTier.CLINICAL_GUIDELINE.value: "Clinical guideline",
    EvidenceTier.EXPERT_CURATED.value: "Expert curated",
    EvidenceTier.FUNCTIONAL.value: "Functional",
    EvidenceTier.GWAS.value: "GWAS",
    EvidenceTier.CANDIDATE_GENE.value: "Candidate gene",
    EvidenceTier.ANECDOTAL.value: "Anecdotal",
}
"""Evidence tiers as a reader should see them.

A table rather than ``value.capitalize()``, which is what this was first, and which printed
``Gwas`` -- a real acronym mangled into something that reads as a typo on a page whose whole
argument is that it states things precisely. The same reason applies to ``Meta analysis``
below, which needs a hyphen it will never get from a string method.
"""

_REPLICATION_LABELS: Mapping[str, str] = {
    Replication.META_ANALYSIS.value: "Meta-analysis",
    Replication.INDEPENDENT.value: "Independent replication",
    Replication.SAME_COHORT.value: "Same cohort only",
    Replication.NONE.value: "Not replicated",
    Replication.CONFLICTING.value: "Conflicting literature",
}

_MEASURE_LABELS: Mapping[str, str] = {
    EffectMeasure.ODDS_RATIO.value: "Odds ratio",
    EffectMeasure.HAZARD_RATIO.value: "Hazard ratio",
    EffectMeasure.RISK_RATIO.value: "Risk ratio",
    EffectMeasure.BETA.value: "Beta",
    EffectMeasure.MEAN_DIFFERENCE.value: "Mean difference",
    EffectMeasure.PERCENT_VARIANCE_EXPLAINED.value: "Variance explained",
    EffectMeasure.PENETRANCE.value: "Penetrance",
    EffectMeasure.PROPORTION.value: "Proportion",
}

RELATIVE_MEASURES: frozenset[str] = frozenset(
    {
        EffectMeasure.ODDS_RATIO.value,
        EffectMeasure.HAZARD_RATIO.value,
        EffectMeasure.RISK_RATIO.value,
    }
)
"""Measures that are a multiple of something else, and so mean nothing on their own.

AGENTS.md §0.1B requires the **absolute** risk and not only the relative one, and no ratio
becomes an absolute risk without the base rate of the outcome. Nothing records that base
rate -- it is missing from the card schema, not merely from the bundle, see
``BUNDLE_FORMAT_VERSION`` -- so the detail view says which of the two quantities it is
holding rather than letting ``1.4`` read as a probability.
"""

ABSOLUTE_MEASURES: frozenset[str] = frozenset(
    {EffectMeasure.PENETRANCE.value, EffectMeasure.PROPORTION.value}
)
"""Measures that already are a rate. These need no base rate; they are one."""


def _text(value: Any) -> str | None:
    """A non-blank string, or ``None``.

    Containers are rejected rather than stringified: a mapping where a title was expected
    would otherwise render as a Python repr on the page, which is :func:`_warnings`'
    finding one layer down.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Mapping) or (isinstance(value, Sequence) and not isinstance(value, str)):
        return None
    text = str(value).strip()
    return text or None


def _strings(raw: Any) -> tuple[str, ...]:
    """A list of non-blank strings, or empty. ``str`` excluded for :func:`_warnings`' reason."""
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        return ()
    return tuple(text for item in raw if (text := _text(item)) is not None)


def _decimal(value: float) -> str:
    """A number as a reader should see it: four significant figures, no invented zeros."""
    return f"{value:.4g}"


def _percent(value: float) -> str:
    """A frequency as a percentage, with enough places that a rare allele does not round to
    zero -- the one frequency where the exact figure matters most, since rarity is what
    drives the confidence ceiling (AGENTS.md §4.1)."""
    if value >= 0.01 or value <= 0.0:
        return f"{value:.1%}"
    return f"{value:.4%}"


@dataclass(frozen=True)
class CitationLink:
    """One citation, with a resolvable address when this project can build one.

    ``url`` is ``None`` rather than a guess whenever the identifier does not validate or the
    accession names a database :func:`~genetics.engine.citations.citation_url` has no entry
    for. The citation still renders -- identifier, title and note -- because a reference
    nobody can click is still a reference somebody can look up, and dropping it would be the
    silent omission §0.1A rules out.

    **Following one leaves this machine**, which is the only thing on this page that does.
    It carries a published identifier and nothing else: no referrer (the app sends
    ``Referrer-Policy: no-referrer``), no genotype, no run id. That it is outbound at all is
    stated on the page rather than left for someone to notice in a network log -- the same
    label-do-not-hide rule the confidence tiers follow.
    """

    kind: str
    identifier: str
    title: str
    database: str | None
    note: str | None
    url: str | None

    @property
    def label(self) -> str:
        if self.database:
            return f"{self.database}:{self.identifier}"
        return f"{self.kind}:{self.identifier}"

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> CitationLink:
        kind = _text(raw.get("type")) or "unknown"
        identifier = _text(raw.get("id")) or ""
        database = _text(raw.get("database"))
        return cls(
            kind=kind,
            identifier=identifier,
            title=_text(raw.get("title")) or identifier or "Untitled reference",
            database=database,
            note=_text(raw.get("note")),
            # Re-validated inside `citation_url`, not trusted. A stored citation is whatever
            # some version of this engine wrote, read back without re-parsing -- and for a
            # `url` citation the stored id *is* the href.
            url=citation_url(kind, identifier, database),
        )


@dataclass(frozen=True)
class EffectView:
    """The published effect, as something a reader can check.

    Every field is optional and every one is read with ``.get``: this comes out of a saved
    bundle, and a detail page that raised on a missing key would fail on the run somebody
    most wants to look at.
    """

    measure: str
    value: float | None
    units: str | None
    ci_low: float | None
    ci_high: float | None
    context: str | None

    @property
    def measure_label(self) -> str:
        return _MEASURE_LABELS.get(self.measure, self.measure.replace("_", " ").capitalize())

    @property
    def is_relative(self) -> bool:
        return self.measure in RELATIVE_MEASURES

    @property
    def is_absolute(self) -> bool:
        return self.measure in ABSOLUTE_MEASURES

    @property
    def display(self) -> str:
        """``Odds ratio 1.4 (95% CI 1.25 to 1.57)``, or as much of it as was recorded."""
        if self.value is None:
            return f"{self.measure_label} (no value recorded)"
        text = f"{self.measure_label} {_decimal(self.value)}"
        if self.units:
            text += f" {self.units}"
        if self.ci_low is not None and self.ci_high is not None:
            text += f" (95% CI {_decimal(self.ci_low)} to {_decimal(self.ci_high)})"
        return text

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> EffectView:
        return cls(
            measure=_text(raw.get("measure")) or "unknown",
            value=_number(raw.get("value")),
            units=_text(raw.get("units")),
            ci_low=_number(raw.get("ci_low")),
            ci_high=_number(raw.get("ci_high")),
            context=_text(raw.get("context")),
        )


@dataclass(frozen=True)
class EvidenceView:
    """What was measured, in whom, and how well replicated."""

    tier: str | None
    replication: str | None
    sample_size: int | None
    populations: tuple[str, ...]
    within_family_attenuation: float | None
    effect: EffectView | None

    @property
    def tier_label(self) -> str | None:
        if self.tier is None:
            return None
        return _EVIDENCE_TIER_LABELS.get(self.tier, self.tier.replace("_", " ").capitalize())

    @property
    def replication_label(self) -> str | None:
        if self.replication is None:
            return None
        return _REPLICATION_LABELS.get(
            self.replication, self.replication.replace("_", " ").capitalize()
        )

    @property
    def sample_size_display(self) -> str | None:
        return None if self.sample_size is None else f"{self.sample_size:,}"

    @property
    def populations_display(self) -> str:
        """The population the estimate came from, spelled out.

        ``UNKNOWN`` is expanded rather than printed as a code: the schema records it because
        an unstated study population is a real and common property of the literature
        (AGENTS.md §4.4), and a reader seeing ``UNKNOWN`` beside ``EUR`` would reasonably
        read it as a population rather than as an absence.
        """
        if not self.populations:
            return "not recorded"
        return ", ".join(
            "not stated by the source" if name == "UNKNOWN" else name for name in self.populations
        )

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> EvidenceView:
        effect = raw.get("effect")
        return cls(
            tier=_text(raw.get("tier")),
            replication=_text(raw.get("replication")),
            sample_size=_count(raw.get("sample_size")),
            populations=_strings(raw.get("ancestry")),
            within_family_attenuation=_number(raw.get("within_family_attenuation")),
            effect=EffectView.of(effect) if isinstance(effect, Mapping) else None,
        )


@dataclass(frozen=True)
class FrequencyView:
    """One population allele frequency, labelled as what it is.

    Called an **allele** frequency everywhere it appears and never a base rate: how common
    an allele is and how common an outcome is are different quantities, and letting the
    first stand in for the second is exactly the vagueness §0.1B calls a defect rather than
    a kindness.
    """

    allele: str
    frequency: float | None
    population: str | None
    source: str | None

    @property
    def display(self) -> str:
        rate = "not recorded" if self.frequency is None else _percent(self.frequency)
        where = self.population or "unstated population"
        text = f"{self.allele}: {rate} in {where}"
        return f"{text} ({self.source})" if self.source else text

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> FrequencyView:
        return cls(
            allele=_text(raw.get("allele")) or "?",
            frequency=_number(raw.get("frequency")),
            population=_text(raw.get("population")),
            source=_text(raw.get("source")),
        )


@dataclass(frozen=True)
class VariantView:
    """Where on the genome the card looked.

    Not genotype-derived: a coordinate and the alleles the *card* declares are public facts
    about the variant, which is the distinction AGENTS.md §1.3 draws when it permits an
    agent to search ``rs17822931`` and forbids it to search the reader's call there.
    """

    rsid: str | None
    chrom: str | None
    position: int | None
    alleles: tuple[str, ...]

    @property
    def locus(self) -> str | None:
        if self.chrom is None or self.position is None:
            return None
        return f"chr{self.chrom}:{self.position:,}"

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> VariantView:
        return cls(
            rsid=_text(raw.get("rsid")),
            chrom=_text(raw.get("chrom")),
            position=_count(raw.get("pos_grch37")),
            alleles=_strings(raw.get("alleles")),
        )


@dataclass(frozen=True)
class ScoreRow:
    """One line of the confidence breakdown: what went in, and what it scored.

    The breakdown is shown in full rather than summarised because AGENTS.md §6 forbids a
    card from authoring its confidence, and a computed number with its inputs hidden is the
    same unaccountable figure arriving by a different route. It is also M13.4's requirement
    -- "explain why this card is low confidence" -- answerable from the page.
    """

    label: str
    observed: str
    score: float | None

    @property
    def score_display(self) -> str:
        return "-" if self.score is None else f"{self.score:.2f}"


@dataclass(frozen=True)
class ConfidenceView:
    """The computed tier, its score, and every number behind it."""

    tier: str | None
    score: float | None
    rows: tuple[ScoreRow, ...]
    ppv_estimate: float | None
    ppv_ceiling: float | None
    ppv_applies_to: str | None

    @property
    def has_ppv(self) -> bool:
        return self.ppv_estimate is not None

    @property
    def ppv_display(self) -> str | None:
        if self.ppv_estimate is None:
            return None
        ceiling = "" if self.ppv_ceiling is None else f" below {_percent(self.ppv_ceiling)}"
        return f"about {_percent(self.ppv_estimate)} of calls like this one are real{ceiling}"

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> ConfidenceView:
        inputs = raw.get("inputs")
        inputs = inputs if isinstance(inputs, Mapping) else {}
        ppv = raw.get("empirical_ppv")
        ppv = ppv if isinstance(ppv, Mapping) else {}

        def observed(*keys: str) -> str:
            parts = [text for key in keys if (text := _text(inputs.get(key))) is not None]
            return " ".join(parts) if parts else "not recorded"

        rows = (
            ScoreRow(
                "Evidence tier",
                observed("evidence_tier"),
                _number(inputs.get("evidence_score")),
            ),
            ScoreRow(
                "Effect size",
                observed("effect_measure", "effect_value"),
                _number(inputs.get("effect_score")),
            ),
            ScoreRow(
                "Replication",
                observed("replication"),
                _number(inputs.get("replication_score")),
            ),
            ScoreRow(
                "Population allele frequency",
                observed("population_allele_frequency"),
                _number(inputs.get("frequency_score")),
            ),
            ScoreRow(
                "How the call was made",
                observed("call_source", "imputation_quality"),
                _number(inputs.get("imputation_score")),
            ),
            ScoreRow(
                "Ancestry match to the study",
                observed("ancestry_match"),
                _number(inputs.get("ancestry_score")),
            ),
        )
        return cls(
            tier=_text(raw.get("tier")),
            score=_number(raw.get("score")),
            rows=rows,
            ppv_estimate=_number(ppv.get("estimate")),
            ppv_ceiling=_number(ppv.get("population_frequency_ceiling")),
            ppv_applies_to=_text(ppv.get("applies_to")),
        )


@dataclass(frozen=True)
class CardView(NoGenotypeRepr):
    """One card as the grid and the detail view show it.

    **Holds a genotype**, so it inherits :class:`NoGenotypeRepr`: the summary of a matched
    card states the reader's call by design, which is the whole reason the dashboard's
    ``assert_no_genotype`` scan covers the banner and the selector and stops there.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("card_id", "section", "status")

    card_id: str
    section: str
    section_title: str
    kind: str
    title: str
    gene: str | None
    status: str
    summary: str
    detail: str
    impossibility_reason: str | None
    tier: str | None
    variant: VariantView | None
    evidence: EvidenceView | None
    confidence: ConfidenceView | None
    frequencies: tuple[FrequencyView, ...]
    confidence_frequency: FrequencyView | None
    citations: tuple[CitationLink, ...]
    authored_caveats: tuple[str, ...]
    computed_caveats: tuple[str, ...]
    observed_rsid: str | None
    call_source: str | None
    imputation_quality: float | None
    ancestry_match: float | None
    strand: str | None
    bundle_format_version: int
    url: str
    """This card's own address, id encoded. Built once here rather than in each template --
    see :func:`run_path` for the hostile id that made that a correctness question."""

    @property
    def is_interpreted(self) -> bool:
        return self.status == MATCHED

    @property
    def is_impossibility(self) -> bool:
        """An AGENTS.md 3.2 card: its claim is about the assay, not about this person.

        Read from ``kind`` rather than from ``status == "not_determinable"``, even though
        ``assemble_card`` refuses to let the two disagree. ``kind`` is what the card *is*;
        the status is the outcome of matching it. Deriving one from the other here would be
        a second definition, and this is the property that decides whether a block of the
        detail view renders at all.
        """
        return self.kind == "impossibility"

    @property
    def has_a_call(self) -> bool:
        """Whether anything was actually read at this card's position.

        **Deliberately not ``call_source is not None``.** ``call_source`` is recorded for
        every observation including the ones that produced nothing, and its value there is
        ``direct`` -- so a marker-absent card rendered a heading reading *How this was
        called* over the single line *Call source: direct*, which says a direct call was
        made about a position the array does not carry.

        An observed rsID means a probe answered. An imputation quality means one was
        attempted, which is the M8 case where this block still has something to say about a
        card that did not match. Neither is true of an impossibility card, which has no
        position at all.
        """
        return self.observed_rsid is not None or self.imputation_quality is not None

    @property
    def frequency_absence(self) -> str | None:
        """Why no allele frequency is shown, or ``None`` when one is, or when saying so
        would be false.

        The first cut said "no population frequency was available, so the rarity check could
        not be applied and the confidence tier is capped" whenever the frequencies were
        empty -- and then said it on an impossibility card, which has no variant, and on a
        marker-absent card, which has no confidence tier to cap. Both are *false statements
        rendered as explanations*, which is worse than the blank they replaced: a reader has
        no way to tell them from the case where they are true.

        So the sentence is only produced where it is true: a card that matched, scored, and
        found nothing to price.
        """
        if self.frequencies or self.confidence_frequency is not None:
            return None
        if not self.is_interpreted:
            return None
        return (
            "No population frequency was available for this variant, so the rarity check "
            "(AGENTS.md §4.1) could not be applied and the confidence tier is capped."
        )

    @property
    def status_label(self) -> str:
        return _STATUS_LABELS.get(self.status, self.status.replace("_", " ").capitalize())

    @property
    def tier_key(self) -> str:
        """The value this card groups and filters under. Never ``None`` -- see :data:`NO_TIER`."""
        return self.tier or NO_TIER

    @property
    def tier_label(self) -> str:
        if self.tier is None:
            return "No tier"
        return _TIER_LABELS.get(self.tier, self.tier.replace("-", " ").capitalize())

    @property
    def tier_is_known(self) -> bool:
        return self.tier is not None and self.tier in _TIER_LABELS

    @property
    def tier_rank(self) -> int:
        """Sort key. Strongest first, an unrecognised tier after the known ones, and a card
        with no tier last -- because a card with no tier has no finding to rank, not a weak
        one."""
        if self.tier is None:
            return _NO_TIER_RANK
        if self.tier in TIER_ORDER:
            return TIER_ORDER.index(self.tier)
        return _UNKNOWN_TIER_RANK

    @property
    def has_distinct_detail(self) -> bool:
        """Whether ``detail`` says anything ``summary`` did not.

        For every status but ``matched`` the engine writes ``match.reason`` into both, so
        rendering them one after the other prints the same sentence twice -- which reads as
        a bug in the page rather than as the deliberate equality it is.
        """
        return self.detail.strip() != self.summary.strip()

    @property
    def effect(self) -> EffectView | None:
        return None if self.evidence is None else self.evidence.effect

    @property
    def base_rate_note(self) -> str | None:
        """What is missing before this effect becomes an absolute risk, or ``None``.

        AGENTS.md §0.1B asks for the base rate and the absolute risk beside the effect size.
        A ratio has neither without knowing how common the outcome is to begin with, and no
        card records that -- so the honest thing on screen is to name the gap rather than
        print a relative number where a probability belongs, or leave the reader to assume
        one is the other.
        """
        effect = self.effect
        if effect is None:
            return None
        if effect.is_absolute:
            return None
        if effect.is_relative:
            return (
                "This is a relative measure. Turning it into an absolute risk needs the base "
                "rate of the outcome — how common it is without this variant — which no card "
                "records yet (roadmap M7 and M9). The allele frequency below is how common "
                "the allele is, not how common the outcome is."
            )
        return (
            "This is a per-allele shift on the study's own scale, not a probability and not "
            "a multiple of one."
        )

    @property
    def evidence_absence(self) -> str | None:
        """Why there is no evidence block, when there is not."""
        if self.evidence is not None:
            return None
        if self.kind == "impossibility":
            # By construction, and the schema enforces it: an impossibility card's claim is
            # about the assay rather than about a population, so it carries an
            # `impossibility_reason` instead of evidence and cites nothing (AGENTS.md §7.6).
            return None
        if self.bundle_format_version < _EVIDENCE_FORMAT_VERSION:
            return (
                f"This run was saved in bundle format {self.bundle_format_version}, before "
                "the effect size, sample size and study population were recorded. Re-run "
                "the analysis to capture them."
            )
        return "This card records no published evidence."

    @classmethod
    def of(cls, card: StoredCard, *, format_version: int, run_id: str | None = None) -> CardView:
        try:
            section_title = sections.SECTIONS[Section(card.section)].title
        except ValueError:
            # A section this version does not define, from a newer engine's bundle. Titled
            # from its own name rather than dropped -- `unknown_sections` already tells the
            # reader the nav cannot place these, and vanishing here as well would be the
            # same card disappearing twice.
            section_title = card.section.replace("_", " ").capitalize()
        return cls(
            card_id=card.card_id,
            section=card.section,
            section_title=section_title,
            kind=card.kind,
            title=card.title,
            gene=card.gene,
            status=card.status,
            summary=card.summary,
            detail=card.detail,
            impossibility_reason=card.impossibility_reason,
            tier=card.confidence_tier,
            variant=None if card.variant is None else VariantView.of(card.variant),
            evidence=None if card.evidence is None else EvidenceView.of(card.evidence),
            confidence=None if card.confidence is None else ConfidenceView.of(card.confidence),
            frequencies=tuple(FrequencyView.of(item) for item in card.frequencies),
            confidence_frequency=(
                None
                if card.confidence_frequency is None
                else FrequencyView.of(card.confidence_frequency)
            ),
            citations=tuple(CitationLink.of(item) for item in card.citations),
            authored_caveats=card.authored_caveats,
            computed_caveats=card.computed_caveats,
            observed_rsid=_text(card.match.get("observed_rsid")),
            call_source=_text((card.observation or {}).get("call_source")),
            imputation_quality=_number((card.observation or {}).get("imputation_quality")),
            ancestry_match=_number((card.observation or {}).get("ancestry_match")),
            strand=_text(card.match.get("strand")),
            bundle_format_version=format_version,
            url=card_path(run_id, card.card_id),
        )


def card_views(bundle: RunBundle | None, *, run_id: str | None = None) -> tuple[CardView, ...]:
    """Every card in the bundle, in the order it was saved.

    ``run_id`` is the **directory name**, which is what addresses a run -- the same choice
    ``shell_for`` makes for ``selected_id``, and for the same reason: when a bundle
    directory is renamed, the manifest's ``run_id`` no longer resolves.
    """
    if bundle is None:
        return ()
    return tuple(
        CardView.of(card, format_version=bundle.format_version, run_id=run_id)
        for card in bundle.cards
    )


def find_card(cards: Sequence[CardView], card_id: str) -> CardView | None:
    """The card with this id, or ``None``. Matched by equality, never by path resolution:
    a card id addresses an entry inside an already-opened bundle, so nothing here touches
    the filesystem and ``check_run_id``'s containment rule has no analogue to enforce."""
    for card in cards:
        if card.card_id == card_id:
            return card
    return None


# ---------------------------------------------------------------------------
# Sorting, filtering and grouping (roadmap M4.7)
# ---------------------------------------------------------------------------

GROUP_BY_SECTION: str = "section"
GROUP_BY_TIER: str = "tier"
GROUPS: tuple[str, ...] = (GROUP_BY_SECTION, GROUP_BY_TIER)

SORT_BY_TIER: str = "tier"
SORT_BY_SECTION: str = "section"
SORT_BY_TITLE: str = "title"
SORTS: tuple[str, ...] = (SORT_BY_TIER, SORT_BY_SECTION, SORT_BY_TITLE)
"""M4.7 names tier and section, and title is the third because neither of the other two is
an ordering a person can scan for a name they half-remember.

Sorting by section is a no-op inside a section-grouped page and is the useful one on a
tier-grouped page, which is the arrangement AGENTS.md §0.1A actually recommends -- "sorting
and grouping by confidence is the right way to keep a section readable" -- so the two
controls are worth having independently.
"""


@dataclass(frozen=True)
class GridQuery:
    """How the reader has arranged the cards, parsed from the query string.

    **Server-side, in the URL, and never a default.** Three decisions in one sentence.

    *In the URL*, because an arrangement is state a person wants to keep, link and come back
    to -- the same argument M4.5 made for a run getting its own address rather than being
    swapped in client-side.

    *Server-side*, because M4.7's rule is a rule about what the page must show, and the only
    place a rule like that can be asserted is where it is computed. A filter implemented in
    Alpine would put "no default filter hides low-confidence results" inside a browser, where
    the Python suite cannot see it and where the CSP build makes it awkward besides.

    *Never a default*: :func:`parse_query` with nothing in it produces filters that match
    every card. AGENTS.md §0.1A is unambiguous that confidence labels and does not filter,
    and a page that arrives pre-filtered has made exactly the hiding decision the stance
    forbids -- silently, before the reader knew there was a decision.
    """

    group: str = GROUP_BY_SECTION
    sort: str = SORT_BY_TIER
    tiers: frozenset[str] = frozenset()
    sections: frozenset[str] = frozenset()
    interpreted_only: bool = False
    ignored: tuple[str, ...] = ()
    """Parameter values dropped as unrecognised, reported on the page rather than obeyed.

    The direction is the point. A mistyped ``?tier=strng`` treated as a filter matches
    nothing and shows an empty grid, which reads as *this run found nothing*; dropped, it
    shows everything, which is merely unfiltered. Under §0.1A the safe failure for a filter
    is always to show more, so an unrecognised value is discarded -- and then said out loud,
    because silently ignoring it is how somebody concludes the filter is broken.
    """

    @property
    def is_filtered(self) -> bool:
        return bool(self.tiers or self.sections or self.interpreted_only)

    def matches(self, card: CardView) -> bool:
        if self.tiers and card.tier_key not in self.tiers:
            return False
        if self.sections and card.section not in self.sections:
            return False
        return not (self.interpreted_only and not card.is_interpreted)

    def unfiltered(self) -> GridQuery:
        """The same arrangement with every filter cleared -- what "show all" links to."""
        return GridQuery(group=self.group, sort=self.sort)

    def with_group(self, group: str) -> GridQuery:
        return GridQuery(
            group=group,
            sort=self.sort,
            tiers=self.tiers,
            sections=self.sections,
            interpreted_only=self.interpreted_only,
        )

    @property
    def parameters(self) -> tuple[tuple[str, str], ...]:
        """This query as name/value pairs, for rebuilding a link.

        Only what differs from the default is emitted, so an unarranged page has a clean
        URL and "no parameters" and "the defaults" are the same state rather than two.
        """
        pairs: list[tuple[str, str]] = []
        if self.group != GROUP_BY_SECTION:
            pairs.append(("group", self.group))
        if self.sort != SORT_BY_TIER:
            pairs.append(("sort", self.sort))
        pairs.extend(("tier", value) for value in sorted(self.tiers))
        pairs.extend(("section", value) for value in sorted(self.sections))
        if self.interpreted_only:
            pairs.append(("interpreted", "1"))
        return tuple(pairs)

    @property
    def query_string(self) -> str:
        """``?group=tier&tier=strong``, or an empty string. Percent-encoded here rather
        than in a template, where Jinja's autoescaping handles HTML and not URLs."""
        pairs = self.parameters
        return f"?{urlencode(pairs)}" if pairs else ""


def filterable_tiers() -> tuple[str, ...]:
    """The tier values a filter may name. One definition, used by the parser and the controls.

    Written as a function so the two cannot drift, which they had already: the controls
    offered a checkbox for every tier *present in the run* -- including one this version does
    not define, arriving from a newer engine's bundle -- while the parser accepted only the
    five it knows. Ticking that box produced "ignored tier=..." and no filtering: a control
    that renders, looks live, and lies.

    So an unrecognised tier is not offered. Its cards are still shown, still grouped under
    their own heading, and -- like anything else a tier filter excludes -- counted in
    ``Grid.hidden`` with one click back. What a reader loses is the ability to filter *to*
    them by name, which is the right thing to lose: the alternative was accepting arbitrary
    strings as filters, and then a typed ``?tier=strng`` hides every card and reads as *this
    run found nothing*.
    """
    return (*TIER_ORDER, NO_TIER)


def filterable_sections() -> tuple[str, ...]:
    """The section values a filter may name, in AGENTS.md 3.1 order.

    From :data:`~genetics.engine.sections.SECTION_ORDER` rather than from ``Section``, so
    this is the same list in the same order that the nav and the section panels are built
    from. ``tests/engine/test_sections.py`` already pins the two against each other; taking
    them from one place here means a filter cannot come to offer a section the grid does not
    render, or vice versa.
    """
    return tuple(section.value for section in sections.SECTION_ORDER)


def parse_query(params: Mapping[str, Sequence[str]]) -> GridQuery:
    """Read an arrangement out of query parameters, dropping what it does not recognise.

    Takes a mapping of lists rather than a ``Request`` so it can be tested without HTTP,
    which is this module's whole reason for existing.
    """
    ignored: list[str] = []

    def single(name: str, allowed: tuple[str, ...], default: str) -> str:
        values = [value for value in params.get(name, ()) if value]
        if not values:
            return default
        # The *last* value wins when a parameter repeats, matching how a browser resubmits
        # a form; the earlier ones are not "ignored" in the sense the notice means, so they
        # are not reported.
        chosen = values[-1]
        if chosen in allowed:
            return chosen
        ignored.append(f"{name}={chosen}")
        return default

    def many(name: str, allowed: frozenset[str]) -> frozenset[str]:
        kept: set[str] = set()
        for value in params.get(name, ()):
            if not value:
                continue
            if value in allowed:
                kept.add(value)
            else:
                ignored.append(f"{name}={value}")
        return frozenset(kept)

    truthy = {"1", "true", "yes", "on"}
    interpreted_values = [value for value in params.get("interpreted", ()) if value]
    interpreted = bool(interpreted_values) and interpreted_values[-1].lower() in truthy

    return GridQuery(
        group=single("group", GROUPS, GROUP_BY_SECTION),
        sort=single("sort", SORTS, SORT_BY_TIER),
        tiers=many("tier", frozenset(filterable_tiers())),
        sections=many("section", frozenset(filterable_sections())),
        interpreted_only=interpreted,
        ignored=tuple(ignored),
    )


@dataclass(frozen=True)
class CardGroup(NoGenotypeRepr):
    """One panel of the grid: a section, or a confidence tier."""

    _repr_fields: ClassVar[tuple[str, ...]] = ("key", "total")

    key: str
    title: str
    blurb: str | None
    cards: tuple[CardView, ...]
    total: int
    """Cards in this group **before** filtering. What the reader is told is here."""

    interpreted: int
    milestone: str | None

    @property
    def hidden(self) -> int:
        return self.total - len(self.cards)

    @property
    def is_empty(self) -> bool:
        return self.total == 0

    @property
    def empty_reason(self) -> str | None:
        """Why this panel shows nothing, or ``None``. Three distinct reasons, kept distinct.

        The definition of done (item 3) forbids a silent empty panel, and the reasons a
        panel can be empty are not interchangeable: **nobody has written these cards yet**
        is a fact about this tool and names the milestone that fixes it; **cards are here
        and none produced an interpretation** is a fact about this genome and is not a
        defect; **the filter is hiding them** is a fact about the reader's own last click.
        Collapsing any two would tell somebody their array lacks a marker when the truth is
        one of the other two.
        """
        if self.total == 0:
            if self.milestone is not None:
                return f"Not built yet — roadmap {self.milestone}."
            return "No card in this run is at this level."
        if not self.cards:
            return f"All {self.total} card(s) here are hidden by the current filter."
        if self.interpreted == 0:
            return (
                f"{self.total} card(s) here, none of which produced an interpretation for "
                "this genome. Each one states its own reason."
            )
        return None


@dataclass(frozen=True)
class FilterOption:
    """One checkbox in the filter controls: a value, what it reads as, and how many cards
    it would show.

    ``count`` is over the **whole run**, never over what the current filter left standing.
    A count that shrank as you filtered would make the controls describe their own effect
    instead of the run, and the number a reader needs while deciding what to hide is how
    many are there.

    Every option is offered even at ``count`` zero, for the reason the thirteen sections
    always render: an option list built from the values present cannot distinguish *nothing
    scored here* from *this level does not exist*.
    """

    value: str
    label: str
    count: int
    selected: bool


@dataclass(frozen=True)
class Grid(NoGenotypeRepr):
    """Every card in the run, arranged. Holds genotypes; never prints itself."""

    _repr_fields: ClassVar[tuple[str, ...]] = ("total", "shown")

    query: GridQuery
    groups: tuple[CardGroup, ...]
    total: int
    shown: int
    tier_options: tuple[FilterOption, ...]
    section_options: tuple[FilterOption, ...]

    @property
    def hidden(self) -> int:
        """How many cards the filter is keeping off the page.

        Stated on the page whenever it is non-zero, and this is the mechanism behind M4.7's
        rule that filtering must never be the only way to see a card: a hidden card is
        always accounted for by a number and a one-click way back, so no arrangement of this
        page can make a finding *quietly* absent.
        """
        return self.total - self.shown

    @property
    def is_filtered(self) -> bool:
        return self.query.is_filtered


def _section_rank(card: CardView) -> int:
    """AGENTS.md §3.1 order, with a section this version does not define sorted after all
    thirteen rather than raising -- the same treatment an unrecognised tier gets."""
    known = [section.value for section in sections.SECTION_ORDER]
    return known.index(card.section) if card.section in known else len(known)


def _sorted(cards: Sequence[CardView], sort: str) -> tuple[CardView, ...]:
    """Deterministic in every mode: the last key is always the card id, so two cards that
    tie on everything visible still come back in the same order on every render."""
    keys = {
        SORT_BY_TITLE: lambda card: (card.title.casefold(), card.card_id),
        SORT_BY_SECTION: lambda card: (_section_rank(card), card.title.casefold(), card.card_id),
    }
    key = keys.get(sort, lambda card: (card.tier_rank, card.title.casefold(), card.card_id))
    return tuple(sorted(cards, key=key))


def _section_groups(cards: Sequence[CardView], query: GridQuery) -> tuple[CardGroup, ...]:
    """One panel per section, all thirteen, in AGENTS.md §3.1 order.

    Unknown sections are appended rather than dropped, for the reason
    :func:`unknown_sections` exists: a newer engine's fourteenth section holds real cards,
    and losing them from the grid as well as from the nav is the same card disappearing
    twice.
    """
    by_section: dict[str, list[CardView]] = {}
    for card in cards:
        by_section.setdefault(card.section, []).append(card)

    known = [section.value for section in sections.SECTION_ORDER]
    extra = sorted(set(by_section) - set(known))

    groups: list[CardGroup] = []
    for name in [*known, *extra]:
        here = by_section.get(name, [])
        info = sections.SECTIONS.get(Section(name)) if name in known else None
        groups.append(
            CardGroup(
                key=name,
                title=info.title if info is not None else name.replace("_", " ").capitalize(),
                blurb=info.blurb if info is not None else None,
                cards=_sorted([card for card in here if query.matches(card)], query.sort),
                total=len(here),
                interpreted=sum(1 for card in here if card.is_interpreted),
                milestone=info.milestone if info is not None else None,
            )
        )
    return tuple(groups)


def _tier_groups(cards: Sequence[CardView], query: GridQuery) -> tuple[CardGroup, ...]:
    """One panel per confidence tier, strongest first, then the untiered cards.

    Every tier is rendered even when empty, the same rule and for the same reason as the
    thirteen sections: a grid built by grouping the tiers that happen to be present cannot
    distinguish *nothing scored here* from *this level does not exist*, and the first of
    those is worth knowing.

    ``milestone`` is ``None`` throughout, which is what makes
    :attr:`CardGroup.empty_reason` say "no card is at this level" rather than naming a
    roadmap item -- a tier is never unbuilt, so there is nothing to promise.
    """
    by_tier: dict[str, list[CardView]] = {}
    for card in cards:
        by_tier.setdefault(card.tier_key, []).append(card)

    extra = sorted(set(by_tier) - {*TIER_ORDER, NO_TIER})
    order = [*TIER_ORDER, *extra, NO_TIER]

    groups: list[CardGroup] = []
    for key in order:
        here = by_tier.get(key, [])
        title: str
        blurb: str | None
        if key == NO_TIER:
            title = "No confidence tier"
            blurb = (
                "Confidence is computed from a finding, so a card with no interpretation "
                "has none. Each of these says why."
            )
        else:
            title = _TIER_LABELS.get(key, key.replace("-", " ").capitalize())
            blurb = _TIER_BLURBS.get(key)  # None for a tier this version does not define
        groups.append(
            CardGroup(
                key=key,
                title=title,
                blurb=blurb,
                cards=_sorted([card for card in here if query.matches(card)], query.sort),
                total=len(here),
                interpreted=sum(1 for card in here if card.is_interpreted),
                milestone=None,
            )
        )
    return tuple(groups)


def _counted(cards: Sequence[CardView], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        value = card.tier_key if key == "tier" else card.section
        counts[value] = counts.get(value, 0) + 1
    return counts


def _tier_options(cards: Sequence[CardView], query: GridQuery) -> tuple[FilterOption, ...]:
    counts = _counted(cards, "tier")
    return tuple(
        FilterOption(
            value=value,
            label="No tier" if value == NO_TIER else _TIER_LABELS.get(value, value),
            count=counts.get(value, 0),
            selected=value in query.tiers,
        )
        for value in filterable_tiers()
    )


def _section_options(cards: Sequence[CardView], query: GridQuery) -> tuple[FilterOption, ...]:
    counts = _counted(cards, "section")
    return tuple(
        FilterOption(
            value=value,
            label=sections.SECTIONS[Section(value)].title,
            count=counts.get(value, 0),
            selected=value in query.sections,
        )
        for value in filterable_sections()
    )


def grid_for(cards: Sequence[CardView], query: GridQuery) -> Grid:
    """Arrange the cards. Counts are of the whole run, never of what survived the filter."""
    if query.group == GROUP_BY_TIER:
        groups = _tier_groups(cards, query)
    else:
        groups = _section_groups(cards, query)
    return Grid(
        query=query,
        groups=groups,
        total=len(cards),
        shown=sum(len(group.cards) for group in groups),
        tier_options=_tier_options(cards, query),
        section_options=_section_options(cards, query),
    )


@dataclass(frozen=True)
class Shell(NoGenotypeRepr):
    """Everything the dashboard renders for one request.

    **Inherits** :class:`~genetics.privacy.NoGenotypeRepr` **as of M4.6**, which the M4.5
    version of this docstring predicted would be needed the moment a card list joined it.
    It has: :attr:`grid` holds :class:`CardView` objects and a matched card's summary states
    the reader's call. Without the mixin, one ``repr(shell)`` in a traceback, a log line or a
    debugger session prints somebody's genotype -- and this object is the one every route
    hands to a template, so it is the likeliest thing in the process to be printed.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("runs_root", "selected_id", "card_count")

    runs_root: str
    run_url: str
    """Where the selected run lives, id encoded; ``"/"`` when none is selected.

    A field rather than a property over :attr:`selected_id`, so this and every
    :attr:`CardView.url` are built from one expression in :func:`shell_for` -- two
    derivations of one address is the shape of problem this app has already hit at M4.1 and
    M4.2. See :func:`run_path`.
    """

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

    cards: tuple[CardView, ...]
    """Every card in the run, unarranged and unfiltered.

    Carried beside :attr:`grid` because the card route resolves one card by id, and doing
    that by walking the grid would mean a card the reader's own filter is hiding could not
    be opened by its own URL -- a link that works or does not depending on a control setting
    somewhere else on the page. The grid is an arrangement; this is the run.
    """

    grid: Grid
    """The cards, arranged (M4.6/M4.7). Empty rather than ``None`` when no run is open, so
    the page has one shape: a template that had to ask whether a grid exists before asking
    what is in it would answer "nothing here" two different ways."""


def shell_for(
    listing: RunListing,
    bundle: RunBundle | None,
    *,
    selected_id: str | None = None,
    problem: str | None = None,
    query: GridQuery | None = None,
) -> Shell:
    """Assemble the shell model.

    ``bundle`` is ``None`` whenever there is nothing to show, and ``problem`` says why. The
    two are separate arguments rather than one union because the caller knows which of the
    four cases it is in and the message it produces is different in each -- inferring it
    from a ``None`` here would collapse them back into "no run".
    """
    # The **directory name**, not the manifest's ``run_id`` -- see ``selected_id`` below.
    # Resolved once and used for the shell URL, for every card URL, and for the selector's
    # notion of which run is current, because those three disagreeing is exactly what a
    # renamed bundle directory used to cause.
    selected = selected_id if bundle is None else bundle.path.name
    cards = card_views(bundle, run_id=selected)
    return Shell(
        runs_root=str(listing.root),
        run_url=run_path(selected),
        runs=tuple(RunOption.of(summary) for summary in listing.runs),
        incomplete=tuple(
            StagingNotice(run_id=item.run_id, name=item.path.name, size_bytes=item.size_bytes)
            for item in listing.incomplete
        ),
        # ``summarise_run`` already settled which id wins: "the directory name wins, because
        # it is what `delete` and `load` resolve against". When someone renames a bundle
        # directory the two disagree, and taking the manifest's id meant the selector marked
        # no option as current and the page printed a `genetics runs show <id>` that `runs
        # show` cannot resolve -- advice that fails for the one run it was given about.
        selected_id=selected,
        banner=None if bundle is None else banner_for(bundle),
        # The thirteen sections render even with no run open, so the nav is the same shape
        # on an empty store as on a full one. A nav that appears only once a run is loaded
        # makes an empty dashboard look broken rather than empty.
        sections=section_views(() if bundle is None else bundle.cards),
        unknown_sections=() if bundle is None else unknown_sections(bundle.cards),
        card_count=len(cards),
        cards=cards,
        # Built even with no run open, and from the same function either way. A grid that
        # only existed once a bundle loaded would mean the empty-store page and the
        # populated one render through different branches, which is how the two drift.
        grid=grid_for(cards, query or GridQuery()),
        problem=problem,
    )
