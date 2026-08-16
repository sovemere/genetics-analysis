"""Resolving cards against the normalized table (roadmap M3.2).

The matcher answers one question per card: *what does this sample show at this variant?*
Everything interpretive happens later; what happens here is deciding whether there is an
answer at all, and when there is not, saying which of the several different reasons
applies.

**Every card gets a result.** ``match_pack`` returns one :class:`MatchResult` per card, in
pack order, including cards whose marker is not on the array. AGENTS.md 0.1A forbids
dropping a card, and a matcher that returned only its successes would make "this variant
is not on your chip" indistinguishable from "this variant is fine" by omission -- the same
confusion :mod:`genetics.ingest.keys` names and the card schema's exhaustiveness rule
guards at the other end.

That is why :class:`MatchStatus` is as long as it is. "No interpretation" has at least
seven distinct causes here and they mean entirely different things to a reader: a marker
the array never carried, a marker that failed to call, a position where the card and the
array disagree about which variant lives there, an indel excluded by policy, a
contradictory call at a single-copy locus, two probes that disagree, and a site whose
strand cannot be established. Collapsing those into one "no result" would be the failure
this module is organised against.

Three decisions are load-bearing.

**Strand ambiguity is only reported when it changes the answer.** The vendor claims
forward-strand calls and AGENTS.md's roadblock list says not to trust that blindly, but the
untrustworthiness is not uniform. At an A/G site a flipped call reads ``C``/``T``, which
matches no allele the card declared, so the error announces itself as a mismatch. At an
A/T or C/G site the complement is the same letter pair, so a flip is invisible -- and a
homozygote would read as the *opposite* homozygote. Even there it only matters sometimes:
a heterozygote is its own complement, and where both readings map to the same outcome the
answer is the same either way. So the check is: complement the genotype, and escalate only
if that would change which outcome applies. Anything blunter would either miss real
inversions or flag thousands of harmless ones, and M0.3's lesson is that a check which
cries wolf gets bypassed.

**Duplicate probes are resolved by agreement, never by choice.** M1 found 656 positions
carrying more than one row in the real export and deliberately left the decision here.
Probes that agree are one answer with a note; probes that disagree are a genuine conflict
and get :attr:`MatchStatus.DUPLICATE_CONFLICT`, because picking the first row -- or the
"better" one -- would invent an answer the data does not contain. A no-call alongside a
call is not a disagreement: an uncalled probe carries no information to conflict with.

**The indel rule is applied by calling M1.6, not by reimplementing it.**
:func:`genetics.ingest.indels.matchable_mask` is the single place the policy lives, exactly
as that module asks.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Final

from genetics.engine.cards import Card, CardKind, KnowledgePack, Outcome
from genetics.ingest.indels import IndelPolicy, matchable_mask
from genetics.ingest.keys import LocusKey, MergeTable, VariantKey, lookup_loci
from genetics.ingest.schema import CallStatus, Chrom, GenotypeTable
from genetics.privacy import NoGenotypeRepr

_COMPLEMENT: Final[Mapping[str, str]] = {"A": "T", "T": "A", "C": "G", "G": "C"}

_AMBIGUOUS_PAIRS: Final[tuple[frozenset[str], ...]] = (
    frozenset({"A", "T"}),
    frozenset({"C", "G"}),
)
"""Allele pairs that are their own complement. A strand flip at one of these is invisible
to any comparison of the letters alone -- which is the entire reason this module cannot
simply trust the vendor's forward-strand claim."""

_MATCHABLE_COLUMN: Final[str] = "_matchable"


class MatchStatus(StrEnum):
    """Why there is, or is not, an interpretation."""

    MATCHED = "matched"

    NOT_DETERMINABLE = "not_determinable"
    """An impossibility card (AGENTS.md 3.2). It carries no match and never could; the
    status exists so nothing downstream reads it as a failed lookup."""

    MARKER_ABSENT = "marker_absent"
    """The position is not on the array at all. Says nothing about the person."""

    NO_CALL = "no_call"
    """The marker is on the array and failed to produce a genotype."""

    ALLELE_MISMATCH = "allele_mismatch"
    """The array reports alleles the card does not declare. Usually the card's coordinates
    are wrong or the position is multi-allelic -- either way, the card is not describing
    the variant that is actually there, and reporting an outcome would be reporting it for
    a different variant."""

    INDEL_EXCLUDED = "indel_excluded"
    """The row is an ``I``/``D`` marker outside the whitelist (AGENTS.md 4.2)."""

    HET_HAPLOID = "het_haploid"
    """A heterozygous call at a locus inferred single-copy. The genotype contradicts the
    ploidy, so it is not trustworthy enough to interpret -- but it is reported rather than
    dropped, exactly as M1.5 keeps it countable."""

    DUPLICATE_CONFLICT = "duplicate_conflict"
    """Two or more probes at this position produced different genotypes."""

    STRAND_AMBIGUOUS = "strand_ambiguous"
    """An A/T or C/G site where the two possible strand readings map to different
    outcomes, and nothing available can decide between them."""

    @property
    def has_interpretation(self) -> bool:
        return self is MatchStatus.MATCHED


class Strand(StrEnum):
    """How the observed alleles related to the card's."""

    AS_WRITTEN = "as_written"
    COMPLEMENTED = "complemented"
    """The observed alleles were the unambiguous complement of the card's, so the genotype
    was flipped to the card's strand. Recorded rather than applied silently: it is an
    inference, correct as far as anything here can tell, and a reader is entitled to know
    it happened."""

    AMBIGUOUS = "ambiguous"
    """A self-complementary site. Which strand the call is on cannot be established from
    the letters, and no reference allele is available yet (M2's dbSNP extracts)."""

    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class MatchResult(NoGenotypeRepr):
    """What one card found. Holds a genotype, so it must never print itself."""

    _repr_fields: ClassVar[tuple[str, ...]] = ("card_id", "status", "strand")

    card_id: str
    status: MatchStatus
    reason: str
    """Human-readable, and written for the person rather than the developer: it lands on
    the card face when there is no interpretation, so "this marker is not on your array"
    beats "MARKER_ABSENT"."""

    genotype: str | None = None
    call_status: CallStatus | None = None
    observed_rsid: str | None = None
    outcome_name: str | None = None
    outcome: Outcome | None = None
    strand: Strand = Strand.NOT_APPLICABLE
    caveats: tuple[str, ...] = ()
    """**Computed** caveats -- single-copy locus, complemented alleles, agreeing duplicate
    probes. Kept separate from the card's authored ``caveats`` because these are facts
    about this sample's data rather than about the literature, and merging them would make
    a rendered card unable to say which is which."""

    candidate_outcomes: tuple[str, ...] = ()
    """The competing outcome names when :attr:`status` is ``STRAND_AMBIGUOUS``. Named
    rather than summarised, so the card can show what the answer would be either way."""


# ---------------------------------------------------------------------------
# Strand helpers
# ---------------------------------------------------------------------------


def complement(genotype: str) -> str:
    """Complement each base and re-sort, giving the same normal form the table uses."""
    return "".join(sorted(_COMPLEMENT[base] for base in genotype))


def is_strand_ambiguous(alleles: Sequence[str]) -> bool:
    """True for A/T and C/G sites, whose allele set is its own complement."""
    return frozenset(alleles) in _AMBIGUOUS_PAIRS


# ---------------------------------------------------------------------------
# Locus index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Row(NoGenotypeRepr):
    """One table row. Holds a genotype, so it inherits the guard like everything else."""

    _repr_fields: ClassVar[tuple[str, ...]] = ("call_status", "matchable")

    rsid: str | None
    genotype: str | None
    a1: str | None
    a2: str | None
    call_status: CallStatus
    matchable: bool

    @property
    def alleles(self) -> frozenset[str]:
        return frozenset(a for a in (self.a1, self.a2) if a is not None)


class LocusIndex(NoGenotypeRepr):
    """The sample's rows at the loci a pack asks about.

    Built once per run and only over the loci the cards need, rather than over the whole
    677k-row table: a pack is tens to hundreds of cards, and indexing the entire export to
    answer a hundred questions costs a great deal of memory for nothing.

    Duplicate positions are kept as a list rather than collapsed, because collapsing is the
    decision :meth:`_resolve` exists to make explicitly.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_loci",)

    def __init__(self, rows: Mapping[LocusKey, tuple[_Row, ...]]) -> None:
        self._rows = dict(rows)

    @property
    def n_loci(self) -> int:
        return len(self._rows)

    def get(self, locus: LocusKey) -> tuple[_Row, ...]:
        return self._rows.get(locus, ())

    @classmethod
    def build(
        cls,
        table: GenotypeTable,
        loci: Iterable[LocusKey],
        *,
        policy: IndelPolicy,
    ) -> LocusIndex:
        wanted = list(dict.fromkeys(loci))
        if not wanted:
            return cls({})

        # The mask is applied to the joined subset rather than to the whole table: it reads
        # only the normalized columns, so it is valid on either, and evaluating it over
        # 677k rows to answer a hundred questions is work for nothing. M1.6 still owns the
        # rule -- this calls its expression rather than restating it.
        subset = lookup_loci(table, wanted).with_columns(
            matchable_mask(policy).alias(_MATCHABLE_COLUMN)
        )

        grouped: dict[LocusKey, list[_Row]] = {}
        for record in subset.iter_rows(named=True):
            locus = LocusKey(Chrom(record["chrom"]), int(record["pos_grch37"]))
            grouped.setdefault(locus, []).append(
                _Row(
                    rsid=record["rsid"],
                    genotype=record["genotype"],
                    a1=record["a1"],
                    a2=record["a2"],
                    call_status=CallStatus(record["call_status"]),
                    matchable=bool(record[_MATCHABLE_COLUMN]),
                )
            )
        return cls({locus: tuple(rows) for locus, rows in grouped.items()})


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Matcher:
    """Resolves cards against one sample."""

    index: LocusIndex
    merges: MergeTable = field(default_factory=MergeTable.empty)

    @classmethod
    def for_pack(
        cls,
        pack: KnowledgePack,
        table: GenotypeTable,
        *,
        policy: IndelPolicy | None = None,
        merges: MergeTable | None = None,
    ) -> Matcher:
        loci = [c.variant_key.locus for c in pack.cards if c.variant_key is not None]
        index = LocusIndex.build(table, loci, policy=policy or IndelPolicy.default())
        return cls(index=index, merges=merges or MergeTable.empty())

    def match(self, card: Card) -> MatchResult:
        if card.kind is CardKind.IMPOSSIBILITY:
            return MatchResult(
                card_id=card.id,
                status=MatchStatus.NOT_DETERMINABLE,
                reason=card.impossibility_reason or "Not determinable from array genotypes.",
            )

        assert card.match is not None  # guaranteed by the schema for interpretation cards
        key = card.match.variant.key
        rows = self.index.get(key.locus)
        if not rows:
            return MatchResult(
                card_id=card.id,
                status=MatchStatus.MARKER_ABSENT,
                reason=(
                    f"This array does not carry a marker at {key.locus}. That is a "
                    "property of the chip, not of you."
                ),
            )

        resolved = _resolve_duplicates(rows)
        if isinstance(resolved, MatchStatus):
            return MatchResult(
                card_id=card.id,
                status=resolved,
                reason=(
                    f"{len(rows)} probes at {key.locus} produced different genotypes. "
                    "Neither is preferred over the other, so no interpretation is offered."
                ),
            )
        row, duplicate_note = resolved

        return self._evaluate(card, key, row, duplicate_note)

    # -- one row, one card -------------------------------------------------

    def _evaluate(
        self,
        card: Card,
        key: VariantKey,
        row: _Row,
        duplicate_note: str | None,
    ) -> MatchResult:
        assert card.match is not None
        caveats: list[str] = [duplicate_note] if duplicate_note else []

        if row.rsid is not None:
            observed = self.merges.resolve(row.rsid)
            expected = self.merges.resolve(card.match.variant.rsid)
            if observed != expected:
                caveats.append(
                    f"The card names {card.match.variant.rsid} and the array names "
                    f"{row.rsid} at this position. Matching is positional, so this is "
                    "reported rather than treated as a failure."
                )

        def unresolved(status: MatchStatus, reason: str) -> MatchResult:
            """A result with the observed data attached but no interpretation.

            The observed genotype and call status travel even when nothing is interpreted,
            because "the array called you AG here but the probes disagree" is a materially
            more useful answer than "no result", and a caller cannot add it back later.
            """
            return MatchResult(
                card_id=card.id,
                status=status,
                reason=reason,
                genotype=row.genotype,
                call_status=row.call_status,
                observed_rsid=row.rsid,
                caveats=tuple(caveats),
            )

        if row.call_status is CallStatus.NO_CALL or row.genotype is None:
            return unresolved(
                MatchStatus.NO_CALL,
                "This marker is on the array but did not produce a genotype.",
            )

        if not row.matchable:
            return unresolved(
                MatchStatus.INDEL_EXCLUDED,
                "This marker is an insertion/deletion recorded without its sequence, so it "
                "cannot be matched to a reference allele (AGENTS.md 4.2).",
            )

        if row.call_status is CallStatus.HET_HAPLOID:
            return unresolved(
                MatchStatus.HET_HAPLOID,
                "Two different alleles were called at a locus that should carry only one "
                "copy. The call contradicts itself, so it is not interpreted.",
            )

        if row.call_status is CallStatus.HEMIZYGOUS:
            caveats.append(
                "This locus carries a single copy in this sample, so the pair shown "
                "represents one allele rather than two."
            )

        genotype, strand, strand_caveat = _orient(row, key)
        if strand_caveat:
            caveats.append(strand_caveat)

        if genotype is None:
            return unresolved(
                MatchStatus.ALLELE_MISMATCH,
                f"The array reports {'/'.join(sorted(row.alleles))} at this position where "
                f"the card describes {'/'.join(key.alleles)}. The card is not describing "
                "the variant that is actually there.",
            )

        outcome_name = card.match.genotypes.get(genotype)
        if outcome_name is None:
            # Unreachable through the schema, which requires an exhaustive genotype map over
            # the declared alleles, and _orient has already established that the observed
            # alleles are among them. Kept because "unreachable" is a claim about today's
            # code, and falling through with a None outcome would render an empty card.
            return unresolved(
                MatchStatus.ALLELE_MISMATCH,
                f"No outcome is defined for this genotype on card {card.id}, which the "
                "schema should have made impossible. Treat this as a bug report.",
            )

        if strand is Strand.AMBIGUOUS:
            other = card.match.genotypes.get(complement(genotype))
            if other is not None and other != outcome_name:
                return MatchResult(
                    card_id=card.id,
                    status=MatchStatus.STRAND_AMBIGUOUS,
                    reason=(
                        "This site's two alleles are complements of each other, so the "
                        "strand of the call cannot be established from the data -- and here "
                        "the two readings give different answers."
                    ),
                    genotype=row.genotype,
                    call_status=row.call_status,
                    observed_rsid=row.rsid,
                    strand=strand,
                    caveats=tuple(caveats),
                    candidate_outcomes=tuple(sorted({outcome_name, other})),
                )
            caveats.append(
                "This site's alleles are complements of each other, so the strand cannot "
                "be established from the data. Both readings give the same answer here."
            )

        return MatchResult(
            card_id=card.id,
            status=MatchStatus.MATCHED,
            reason="Matched.",
            genotype=genotype,
            call_status=row.call_status,
            observed_rsid=row.rsid,
            outcome_name=outcome_name,
            outcome=card.outcomes[outcome_name],
            strand=strand,
            caveats=tuple(caveats),
        )


def _resolve_duplicates(rows: tuple[_Row, ...]) -> tuple[_Row, str | None] | MatchStatus:
    """Pick the row to interpret, or report that the probes disagree.

    M1 left this decision here deliberately: 656 positions in the real export carry more
    than one row. The rule is agreement, never preference. A no-call beside a call is not a
    disagreement -- an uncalled probe has no genotype to conflict with -- but two different
    genotypes are a real conflict, and choosing between them would manufacture an answer
    the data does not contain.
    """
    if len(rows) == 1:
        return rows[0], None

    called = [r for r in rows if r.genotype is not None and r.call_status is not CallStatus.NO_CALL]
    if not called:
        return rows[0], f"{len(rows)} probes cover this position; none produced a call."

    distinct = {r.genotype for r in called}
    if len(distinct) > 1:
        return MatchStatus.DUPLICATE_CONFLICT

    if len(called) == len(rows):
        note = f"{len(rows)} probes cover this position and they agree."
    else:
        note = f"{len(rows)} probes cover this position; {len(called)} called, and they agree."
    return called[0], note


def _orient(row: _Row, key: VariantKey) -> tuple[str | None, Strand, str | None]:
    """Put the observed genotype on the card's strand, or report that it cannot be.

    Returns ``(genotype, strand, caveat)``; a ``None`` genotype means the observed alleles
    are not the card's under either strand.

    **The evidence for a flip is not equally strong in both cases, and the caveat says so.**
    A heterozygote shows both alleles, so ``C``/``T`` observed against a declared ``A``/``G``
    is the complete complement of the declared pair -- a coincidence would require the
    array to carry a different variant whose two alleles happen to complement this one's.
    A homozygote shows only one allele, which is :mod:`genetics.ingest.keys`'s whole reason
    for separating ``LocusKey`` from ``VariantKey``, and a single letter cannot distinguish
    "reverse strand" from "a different variant at this position". Worth knowing how narrow
    that gap is: for a biallelic card the declared pair and its complement together cover
    all four bases, so a *homozygote* always has some reading available and this branch can
    never refuse one. A heterozygote can and does -- ``A``/``C`` observed against ``A``/``G``
    fits neither strand.

    Complementing anyway is the right default: an array carrying some markers on the
    reverse strand is ordinary and expected, whereas a card pointing at the wrong variant
    is a card bug, and M3.5's dbSNP cross-check is the thing built to catch that. What is
    not acceptable is doing it silently, so the weaker inference is labelled as weaker.
    """
    observed = row.alleles
    declared = frozenset(key.alleles)
    genotype = row.genotype
    assert genotype is not None  # callers check

    if is_strand_ambiguous(key.alleles):
        # The complement of {A,T} is {A,T}, so the sets always agree and tell us nothing.
        # Whether that matters is decided by the caller, which can see the outcomes.
        return genotype, Strand.AMBIGUOUS, None

    if observed <= declared:
        return genotype, Strand.AS_WRITTEN, None

    flipped = frozenset(_COMPLEMENT[a] for a in observed if a in _COMPLEMENT)
    if len(flipped) == len(observed) and flipped <= declared:
        if len(observed) > 1:
            caveat = (
                "The array reported this marker on the opposite strand to the card, so the "
                "alleles were complemented. Both alleles were observed and together they "
                "are exactly the complement of the card's pair, so the reading is "
                "unambiguous."
            )
        else:
            caveat = (
                "The array reported this marker on the opposite strand to the card, so the "
                "alleles were complemented. Only one allele is visible at a homozygous "
                "locus, so this reading is inferred from less evidence than a heterozygous "
                "one would give; a reference allele would settle it."
            )
        return complement(genotype), Strand.COMPLEMENTED, caveat

    return None, Strand.AS_WRITTEN, None


def match_pack(
    pack: KnowledgePack,
    table: GenotypeTable,
    *,
    policy: IndelPolicy | None = None,
    merges: MergeTable | None = None,
) -> tuple[MatchResult, ...]:
    """One result per card, in pack order.

    Cards are never filtered here. AGENTS.md 0.1A, and the practical reason: a caller that
    receives fewer results than cards has no way to reconstruct which ones went missing or
    why, so the honest states -- marker absent, no call, probes disagree -- would collapse
    into silence.
    """
    matcher = Matcher.for_pack(pack, table, policy=policy, merges=merges)
    return tuple(matcher.match(card) for card in pack.cards)


def summarise(results: Iterable[MatchResult]) -> dict[MatchStatus, int]:
    """Counts per status, for the QC banner and ``cards lint``. Never a pass rate."""
    counts = dict.fromkeys(MatchStatus, 0)
    for result in results:
        counts[result.status] += 1
    return counts
