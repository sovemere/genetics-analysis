"""Assemble matched cards into renderable evidence records (roadmap M3.4).

Matching, authored evidence, runtime reference evidence, and rendering deliberately meet
in one place.  A UI or CLI receiving four loosely-related objects can pair the wrong
frequency with a card, forget a computed caveat, or quietly omit an unresolved match.
An :class:`AssembledCard` carries the complete, immutable record instead.

The cardinality rule is load-bearing: :func:`assemble_pack` returns exactly one record per
card, in knowledge-pack order.  Low confidence, an absent marker, a no-call, and an
impossibility are display states, never filters (AGENTS.md 0.1A and 3.2).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from genetics.engine.cards import Card, CardKind, KnowledgePack
from genetics.engine.citations import Citation
from genetics.engine.confidence import CallSource, ConfidenceResult, calculate_confidence
from genetics.engine.matcher import MatchResult, MatchStatus, Strand, complement
from genetics.engine.sections import Section
from genetics.privacy import NoGenotypeRepr


class EvidenceAssemblyError(ValueError):
    """Raised when cards, matches, or runtime evidence cannot be paired honestly."""


@dataclass(frozen=True)
class PopulationFrequency:
    """Allele frequency and enough provenance to interpret it later.

    M7.2 supplies these from gnomAD.  M3.4 defines the boundary now so a bare float cannot
    lose which allele, population, or release it described while travelling to a run
    bundle.  ``frequency`` is a proportion, never a percentage.
    """

    allele: str
    frequency: float
    population: str
    source: str

    def __post_init__(self) -> None:
        allele = self.allele.strip().upper()
        population = self.population.strip()
        source = self.source.strip()
        if allele not in {"A", "C", "G", "T"}:
            raise EvidenceAssemblyError(
                "population frequency allele must be one of A/C/G/T; indels are not "
                "matchable by default (AGENTS.md 4.2)"
            )
        value = self.frequency
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise EvidenceAssemblyError("population frequency must be a number from 0 to 1")
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise EvidenceAssemblyError(
                f"population frequency must be finite and between 0 and 1; got {value!r}"
            )
        if not population:
            raise EvidenceAssemblyError(
                "population frequency needs a population label; an unlabeled frequency "
                "cannot support ancestry-aware confidence"
            )
        if not source:
            raise EvidenceAssemblyError(
                "population frequency needs a source release for run-bundle provenance"
            )
        object.__setattr__(self, "allele", allele)
        object.__setattr__(self, "frequency", float(value))
        object.__setattr__(self, "population", population)
        object.__setattr__(self, "source", source)


@dataclass(frozen=True)
class ObservationEvidence:
    """Runtime inputs that are not authored by a knowledge card.

    Frequencies are per allele rather than a caller-selected singleton. For a matched
    genotype, assembly deterministically uses the rarest observed allele, so a common
    reference frequency cannot conceal a rare heterozygous call and an unobserved rare
    alternate cannot weaken a common homozygous call. ``call_source`` is mandatory;
    imputed observations require quality and direct observations forbid it.
    """

    call_source: CallSource
    frequencies: tuple[PopulationFrequency, ...] = ()
    imputation_quality: float | None = None
    ancestry_match: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.call_source, CallSource):
            raise EvidenceAssemblyError(
                "call_source must be CallSource.DIRECT or CallSource.IMPUTED"
            )
        try:
            frequencies = tuple(self.frequencies)
        except TypeError:
            raise EvidenceAssemblyError(
                "frequencies must be an iterable of PopulationFrequency records"
            ) from None
        if not all(isinstance(item, PopulationFrequency) for item in frequencies):
            raise EvidenceAssemblyError("frequencies must contain PopulationFrequency records")
        if len({item.allele for item in frequencies}) != len(frequencies):
            raise EvidenceAssemblyError("frequencies contain the same allele more than once")
        contexts = {(item.population, item.source) for item in frequencies}
        if len(contexts) > 1:
            raise EvidenceAssemblyError(
                "frequencies must use one population and source so their values are comparable"
            )
        if sum(item.frequency for item in frequencies) > 1.0 + 1e-12:
            raise EvidenceAssemblyError(
                "frequencies from one locus/population cannot sum to more than 1"
            )
        object.__setattr__(self, "frequencies", frequencies)

        for name in ("imputation_quality", "ancestry_match"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise EvidenceAssemblyError(f"{name} must be a number from 0 to 1, or None")
            numeric = float(value)
            if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
                raise EvidenceAssemblyError(
                    f"{name} must be finite and between 0 and 1; got {value!r}"
                )
            object.__setattr__(self, name, numeric)
        if self.call_source is CallSource.IMPUTED and self.imputation_quality is None:
            raise EvidenceAssemblyError("an imputed observation requires imputation_quality")
        if self.call_source is CallSource.DIRECT and self.imputation_quality is not None:
            raise EvidenceAssemblyError(
                "a directly genotyped observation cannot carry imputation_quality"
            )


@dataclass(frozen=True)
class AssembledCard(NoGenotypeRepr):
    """One renderable card result, including unresolved and impossible states.

    This object contains a :class:`MatchResult`, whose genotype may be personal data, so
    its repr exposes identifiers and status only.  The full values remain available to
    the local UI, CLI JSON boundary, and future run-bundle serializer.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("card_id", "section", "status")

    card_id: str
    section: Section
    kind: CardKind
    title: str
    status: MatchStatus
    summary: str
    detail: str
    card: Card
    match: MatchResult
    observation: ObservationEvidence | None
    confidence: ConfidenceResult | None
    frequencies: tuple[PopulationFrequency, ...]
    confidence_frequency: PopulationFrequency | None
    citations: tuple[Citation, ...]
    authored_caveats: tuple[str, ...]
    computed_caveats: tuple[str, ...]

    @property
    def has_interpretation(self) -> bool:
        return self.status.has_interpretation


def _template_values(
    card: Card,
    match: MatchResult,
    confidence: ConfidenceResult,
) -> dict[str, object]:
    """Build the closed template context validated by ``cards.py``.

    A self-complementary site can match because both strand readings give the same
    outcome while still having no honest card-oriented genotype.  In that case the value
    displayed is explicitly the observed array reading; the match caveat explains why no
    strand was chosen.
    """

    assert card.match is not None
    assert card.evidence is not None
    variant = card.match.variant
    effect = card.evidence.effect
    return {
        "genotype": match.genotype or match.observed_genotype or "unresolved",
        "rsid": match.observed_rsid or variant.rsid,
        # M3.5 requires knowledge cards to use current dbSNP identifiers.  When the export
        # carries a retired name, the matcher has already established merge equivalence;
        # the card's validated identifier is therefore the current one.
        "rsid_current": variant.rsid,
        "gene": card.gene or "",
        "chrom": variant.key.chrom.value,
        "pos": variant.key.pos_grch37,
        "effect_value": effect.value,
        "effect_units": effect.units or "",
        "sample_size": card.evidence.sample_size,
        "confidence": confidence.tier.value,
    }


def render_template(template: str, values: Mapping[str, object]) -> str:
    """Render a schema-validated plain ``str.format`` template.

    Public so card lint and production assembly exercise the exact same renderer.  Lint
    supplies synthetic values to reach every outcome; assembly supplies a real match.
    """

    try:
        return template.format_map(values)
    except (KeyError, ValueError) as exc:  # defensive: schema validation should prevent it
        raise EvidenceAssemblyError(
            "a validated card template could not be rendered; treat this as an engine bug"
        ) from exc


def _confidence_frequency(
    card: Card,
    match: MatchResult,
    observation: ObservationEvidence,
) -> PopulationFrequency | None:
    """Select the rarest called allele from a complete, comparable frequency set."""

    assert card.match is not None
    declared = set(card.match.variant.key.alleles)
    for item in observation.frequencies:
        if item.allele not in declared:
            raise EvidenceAssemblyError(
                f"frequency allele {item.allele!r} is not declared by card {card.id!r}; "
                "using it would attach another variant's calibration"
            )
    if match.status is not MatchStatus.MATCHED or not observation.frequencies:
        return None

    genotype = match.genotype or match.observed_genotype
    if genotype is None:
        raise EvidenceAssemblyError(
            f"matched card {card.id!r} has no observed genotype for frequency calibration"
        )
    called = set(genotype)
    if match.strand is Strand.AMBIGUOUS:
        # A homozygous A/T or C/G observation has two equally valid strand readings.
        # The matcher may still return MATCHED when both map to the same outcome, but the
        # observation reliability must cover both possible alleles. Otherwise a common
        # observed A/A could conceal a rare complemented T/T call and evade the rarity
        # inversion. Heterozygotes are unchanged because their complement has the same set.
        assert match.observed_genotype is not None
        called.update(complement(match.observed_genotype))
    by_allele = {item.allele: item for item in observation.frequencies}
    missing = sorted(called - set(by_allele))
    if missing:
        raise EvidenceAssemblyError(
            f"card {card.id!r} needs frequency for every observed allele; missing "
            + ", ".join(missing)
        )
    return min((by_allele[allele] for allele in called), key=lambda item: item.frequency)


def assemble_card(
    card: Card,
    match: MatchResult,
    observation: ObservationEvidence | None = None,
) -> AssembledCard:
    """Combine one card and its match without suppressing any display state."""

    if match.card_id != card.id:
        raise EvidenceAssemblyError(
            f"cannot assemble card {card.id!r} with match for {match.card_id!r}"
        )
    if card.kind is CardKind.IMPOSSIBILITY:
        if match.status is not MatchStatus.NOT_DETERMINABLE:
            raise EvidenceAssemblyError(
                f"impossibility card {card.id!r} must have a not_determinable match"
            )
        if observation is not None:
            raise EvidenceAssemblyError(
                f"impossibility card {card.id!r} cannot carry genotype-derived runtime "
                "evidence; it is not determinable by construction"
            )
        impossibility_values = {"gene": card.gene or ""}
        assert card.summary is not None and card.detail is not None
        return AssembledCard(
            card_id=card.id,
            section=card.section,
            kind=card.kind,
            title=card.title,
            status=match.status,
            summary=render_template(card.summary, impossibility_values),
            detail=render_template(card.detail, impossibility_values),
            card=card,
            match=match,
            observation=None,
            confidence=None,
            frequencies=(),
            confidence_frequency=None,
            citations=card.citations,
            authored_caveats=card.caveats,
            computed_caveats=match.caveats,
        )

    assert card.match is not None  # interpretation-card schema invariant
    if observation is None:
        raise EvidenceAssemblyError(
            f"interpretation card {card.id!r} requires ObservationEvidence; silently "
            "assuming a direct call could score an imputed observation as perfect"
        )
    observed = observation
    confidence_frequency = _confidence_frequency(card, match, observed)

    if match.status is MatchStatus.NOT_DETERMINABLE:
        raise EvidenceAssemblyError(
            f"interpretation card {card.id!r} cannot have a not_determinable match; that "
            "status belongs to impossibility cards"
        )

    if match.status is not MatchStatus.MATCHED:
        # There is no personal finding to score or outcome template to render.  The match
        # reason is already written for the card face and remains distinct across absent,
        # no-call, conflict, mismatch, indel, ploidy, and strand states.
        return AssembledCard(
            card_id=card.id,
            section=card.section,
            kind=card.kind,
            title=card.title,
            status=match.status,
            summary=match.reason,
            detail=match.reason,
            card=card,
            match=match,
            observation=observed,
            confidence=None,
            frequencies=observed.frequencies,
            confidence_frequency=None,
            citations=card.citations,
            authored_caveats=card.caveats,
            computed_caveats=match.caveats,
        )

    if card.evidence is None or match.outcome is None:
        raise EvidenceAssemblyError(
            f"matched interpretation card {card.id!r} lacks evidence or an outcome"
        )
    confidence = calculate_confidence(
        card.evidence,
        population_allele_frequency=(
            confidence_frequency.frequency if confidence_frequency is not None else None
        ),
        call_source=observed.call_source,
        imputation_quality=observed.imputation_quality,
        ancestry_match=observed.ancestry_match,
    )
    template_values = _template_values(card, match, confidence)
    return AssembledCard(
        card_id=card.id,
        section=card.section,
        kind=card.kind,
        title=card.title,
        status=match.status,
        summary=render_template(match.outcome.summary, template_values),
        detail=render_template(match.outcome.detail, template_values),
        card=card,
        match=match,
        observation=observed,
        confidence=confidence,
        frequencies=observed.frequencies,
        confidence_frequency=confidence_frequency,
        citations=card.citations,
        authored_caveats=card.caveats,
        computed_caveats=match.caveats,
    )


def assemble_pack(
    pack: KnowledgePack,
    matches: Sequence[MatchResult],
    observations: Mapping[str, ObservationEvidence] | None = None,
) -> tuple[AssembledCard, ...]:
    """Return one assembled record per card, in pack order, or refuse misalignment."""

    if len(matches) != len(pack.cards):
        raise EvidenceAssemblyError(
            f"knowledge pack has {len(pack.cards)} cards but received {len(matches)} matches; "
            "assembling a partial result would silently drop a card"
        )

    supplied = observations or {}
    known_ids = {card.id for card in pack.cards}
    extras = sorted(set(supplied) - known_ids)
    if extras:
        raise EvidenceAssemblyError("runtime evidence names unknown card(s): " + ", ".join(extras))

    assembled: list[AssembledCard] = []
    for card, match in zip(pack.cards, matches, strict=True):
        if match.card_id != card.id:
            raise EvidenceAssemblyError(
                f"match order diverges at card {card.id!r}: got {match.card_id!r}. "
                "Pairing by accident would attach evidence to the wrong person-level claim."
            )
        assembled.append(assemble_card(card, match, supplied.get(card.id)))
    return tuple(assembled)
