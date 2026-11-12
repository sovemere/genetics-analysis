"""Computed confidence for card findings (roadmap M3.3).

Confidence is deliberately a function, not a field on a card.  A card supplies the
literature evidence; runtime reference data supplies population frequency, imputation
quality and ancestry match.  This module combines them and returns every numeric factor
used in the decision so the dashboard and CLI can explain the result.

The weighted score describes the strength of an otherwise reliable finding.  Measurement
reliability is a separate ceiling: a very rare chip call or a very poorly imputed call is
``likely-artifact`` even when the literature behind the variant is excellent.  That
separation is load-bearing.  Averaging rarity into a prestigious ClinVar evidence tier
would let strong literature conceal the weak *observation* and reverse AGENTS.md 4.1.

The 0.001% rare-call boundary and 16% empirical benchmark come from the constraint
recorded in AGENTS.md 4.1 (Weedon et al., BMJ 2021).  The benchmark is deliberately
labelled as such: it was measured for rare heterozygous SNP-chip calls and is not an
individual posterior probability.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from genetics.engine.cards import Effect, EffectMeasure, Evidence, EvidenceTier, Replication

RARE_CALL_FREQUENCY_CEILING: Final[float] = 0.00001
"""0.001% as a proportion. Values strictly below this enter the empirical rare-call band."""

RARE_CALL_EMPIRICAL_PPV: Final[float] = 0.16
"""Observed confirmation rate for rare heterozygous SNP-chip calls (AGENTS.md 4.1)."""

_WEIGHTS: Final[dict[str, float]] = {
    "evidence": 0.30,
    "effect": 0.15,
    "replication": 0.20,
    "frequency": 0.20,
    "imputation": 0.10,
    "ancestry": 0.05,
}

SCORE_WEIGHTS: Final[Mapping[str, float]] = MappingProxyType(_WEIGHTS)
"""The six weights, read-only, for a reader that explains a saved score (M13.4). A polygenic
score puts weight coverage in the ``frequency`` slot and weighted quality in ``imputation``."""


class ConfidenceError(ValueError):
    """Raised when runtime confidence inputs are absent, malformed or impossible."""


class ConfidenceTier(StrEnum):
    """Computed finding reliability, ordered from strongest to weakest."""

    WELL_ESTABLISHED = "well-established"
    STRONG = "strong"
    MODERATE = "moderate"
    LIMITED = "limited"
    LIKELY_ARTIFACT = "likely-artifact"

    @property
    def rank(self) -> int:
        """Zero is strongest; useful for deterministic UI sorting."""

        return _CONFIDENCE_ORDER.index(self)


class CallSource(StrEnum):
    """How the observed genotype entered the engine."""

    DIRECT = "direct"
    IMPUTED = "imputed"


_CONFIDENCE_ORDER: Final[tuple[ConfidenceTier, ...]] = (
    ConfidenceTier.WELL_ESTABLISHED,
    ConfidenceTier.STRONG,
    ConfidenceTier.MODERATE,
    ConfidenceTier.LIMITED,
    ConfidenceTier.LIKELY_ARTIFACT,
)

SCORE_BANDS: Final[tuple[tuple[ConfidenceTier, float], ...]] = (
    (ConfidenceTier.WELL_ESTABLISHED, 0.85),
    (ConfidenceTier.STRONG, 0.70),
    (ConfidenceTier.MODERATE, 0.50),
    (ConfidenceTier.LIMITED, 0.0),
)
"""Each tier a weighted score can earn, with the lowest score that earns it. No score earns
``likely-artifact``: only an observation ceiling gives that tier."""


@dataclass(frozen=True)
class Ceiling:
    """The best tier one input allows, whatever the weighted score says.

    A tier is the weaker of the score's band and every ceiling, so a ceiling at or above
    the band changes nothing and is still listed: it is a rule that applied. ``input`` names
    the input that imposed it and ``rule`` states the condition as a clause, so that a
    reader can say why a tier is what it is without re-deriving the thresholds (M13.4).
    """

    input: str
    tier: ConfidenceTier
    rule: str


@dataclass(frozen=True)
class EmpiricalPpv:
    """A published calibration benchmark attached to a reliability gate.

    ``estimate`` is intentionally not folded into ``score``.  It calibrates the chance
    that the chip observation itself is real, whereas the weighted score combines the
    evidence behind the claim.  Showing both prevents a strong ClinVar assertion from
    looking like a strong observation of that assertion in this sample.
    """

    estimate: float
    population_frequency_ceiling: float
    applies_to: str


@dataclass(frozen=True)
class ConfidenceBreakdown:
    """Raw and normalised inputs used to compute a confidence result.

    Raw categorical values are retained beside numeric component scores so a renderer
    never has to reverse-engineer what, for example, ``evidence_score=0.8`` meant.  A
    missing frequency or ancestry match remains ``None`` and receives the explicitly
    visible neutral score of 0.5; absence is never made to look like measured agreement.
    ``call_source`` makes a direct call explicit. Explicit unestimated imputed quality
    stays None, receives a zero quality component and a limited confidence ceiling.
    """

    evidence_tier: EvidenceTier | None
    evidence_score: float
    effect_measure: EffectMeasure | None
    effect_value: float | None
    effect_score: float
    replication: Replication | None
    replication_score: float
    population_allele_frequency: float | None
    frequency_score: float
    call_source: CallSource
    imputation_quality: float | None
    imputation_score: float
    ancestry_match: float | None
    ancestry_score: float


@dataclass(frozen=True)
class ConfidenceResult:
    """Renderable computed confidence and the inputs that produced it."""

    tier: ConfidenceTier
    score: float
    inputs: ConfidenceBreakdown
    empirical_ppv: EmpiricalPpv | None = None


_EVIDENCE_SCORES: Final[dict[EvidenceTier, float]] = {
    EvidenceTier.CLINICAL_GUIDELINE: 1.00,
    EvidenceTier.EXPERT_CURATED: 0.95,
    EvidenceTier.FUNCTIONAL: 0.90,
    EvidenceTier.COHORT: 0.80,
    EvidenceTier.GWAS: 0.80,
    EvidenceTier.CANDIDATE_GENE: 0.35,
    EvidenceTier.ANECDOTAL: 0.10,
}

_REPLICATION_SCORES: Final[dict[Replication, float]] = {
    Replication.META_ANALYSIS: 1.00,
    Replication.INDEPENDENT: 0.90,
    Replication.SAME_COHORT: 0.35,
    Replication.NONE: 0.20,
    Replication.CONFLICTING: 0.00,
}


def _finite_fraction(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfidenceError(f"{name} must be a number between 0 and 1, or None")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ConfidenceError(f"{name} must be finite and between 0 and 1; got {value!r}")
    return numeric


def _effect_score(effect: Effect) -> float:
    """Map heterogeneous published effects to a bounded, displayable signal score.

    Ratio measures have a natural null of one and are symmetric for risk/protective
    effects on the log scale; a fourfold effect saturates the component.  Penetrance and
    proportion are already fractions.  Variance explained is authored as a percentage,
    with five percent treated as a large single-variant effect.

    Betas and mean differences have arbitrary units, so their raw magnitudes cannot be
    compared.  When an interval exists, the unit-free distance from the null relative to
    the interval's **full width** is used: for a 95% interval that is ``z / 3.92``, so a
    nominally significant effect (``z = 1.96``) scores 0.5 and saturation needs roughly
    double that.  Without an interval, a non-zero estimate receives a neutral 0.5 rather
    than allowing centimetres, kilograms and standard deviations to masquerade as one
    scale.

    Full width rather than half-width, and the distinction is a calibration rather than a
    detail: against the half-width every nominally significant effect would saturate the
    component, which makes the score unable to separate "just reached p < 0.05" from
    "unmistakable".  It also sets the crossover where it belongs -- an authored interval
    beats the interval-free default exactly when the effect is nominally significant, so
    reporting uncertainty is rewarded where it is informative and not before.
    :func:`test_effect_score_calibration_points` pins both ends, because the previous
    version of this docstring described the half-width while the code used the full width
    and nothing else in the module said which was intended.
    """

    value = effect.value
    if not math.isfinite(value):
        raise ConfidenceError(f"effect value must be finite; got {value!r}")

    if effect.measure.is_ratio:
        if value <= 0.0:
            raise ConfidenceError(f"{effect.measure.value} must be positive; got {value!r}")
        return min(abs(math.log(value)) / math.log(4.0), 1.0)

    if effect.measure.is_proportion:
        if not 0.0 <= value <= 1.0:
            raise ConfidenceError(f"{effect.measure.value} must be between 0 and 1; got {value!r}")
        return value

    if effect.measure is EffectMeasure.PERCENT_VARIANCE_EXPLAINED:
        if not 0.0 <= value <= 100.0:
            raise ConfidenceError(
                f"percent_variance_explained must be between 0 and 100; got {value!r}"
            )
        return min(value / 5.0, 1.0)

    # BETA and MEAN_DIFFERENCE are unit-bearing. Their interval gives a unit-free
    # signal-to-uncertainty ratio, but a bare magnitude cannot be compared across units.
    if effect.ci_low is None or effect.ci_high is None:
        return 0.5 if value != 0.0 else 0.0
    if not math.isfinite(effect.ci_low) or not math.isfinite(effect.ci_high):
        raise ConfidenceError("effect confidence interval bounds must be finite")
    half_width = (effect.ci_high - effect.ci_low) / 2.0
    if half_width <= 0.0:
        raise ConfidenceError("effect confidence interval must have positive width")
    return min(abs(value) / (2.0 * half_width), 1.0)


def _frequency_score(frequency: float | None) -> float:
    """Rarity-inverted observation reliability, continuous across useful bands."""

    if frequency is None:
        return 0.5
    if frequency < RARE_CALL_FREQUENCY_CEILING:
        return 0.0
    if frequency < 0.0001:
        return 0.15
    if frequency < 0.001:
        return 0.35
    if frequency < 0.01:
        return 0.60
    if frequency < 0.05:
        return 0.80
    return 1.0


def score_tier(score: float) -> ConfidenceTier:
    """The band a weighted score falls in, before any ceiling."""
    for tier, floor in SCORE_BANDS:
        if score >= floor:
            return tier
    return ConfidenceTier.LIMITED


_score_tier = score_tier


def _weaker_of(left: ConfidenceTier, right: ConfidenceTier) -> ConfidenceTier:
    return left if left.rank >= right.rank else right


def weakest(band: ConfidenceTier, ceilings: tuple[Ceiling, ...]) -> ConfidenceTier:
    """The tier: the weaker of the score's band and every ceiling."""
    tier = band
    for ceiling in ceilings:
        tier = _weaker_of(tier, ceiling.tier)
    return tier


def _evidence_ceilings(
    has_evidence: bool, evidence_tier: EvidenceTier | None, replication: Replication | None
) -> list[Ceiling]:
    """Claim-evidence ceilings, weakest first.

    A striking, common observation does not upgrade weak literature. Weakest first, so
    that applying them in order names this group at most once in a saved polygenic record.
    """
    ceilings: list[Ceiling] = []
    if not has_evidence:
        ceilings.append(
            Ceiling(
                "evidence_tier",
                ConfidenceTier.LIMITED,
                "no phenotype estimate applies to this result",
            )
        )
        return ceilings
    if evidence_tier is EvidenceTier.ANECDOTAL:
        ceilings.append(
            Ceiling("evidence_tier", ConfidenceTier.LIMITED, "the evidence tier is anecdotal")
        )
    if replication is Replication.CONFLICTING:
        ceilings.append(
            Ceiling("replication", ConfidenceTier.LIMITED, "replication is conflicting")
        )
    if evidence_tier is EvidenceTier.CANDIDATE_GENE:
        ceilings.append(
            Ceiling("evidence_tier", ConfidenceTier.MODERATE, "the evidence tier is candidate_gene")
        )
    return ceilings


_QUALITY_CEILINGS: Final[tuple[tuple[float, ConfidenceTier], ...]] = (
    (0.30, ConfidenceTier.LIKELY_ARTIFACT),
    (0.60, ConfidenceTier.LIMITED),
    (0.80, ConfidenceTier.MODERATE),
)
"""Observation-quality ceilings for a call's DR2 and a score's weighted DR2: below the
bound, the tier is at best the one beside it. :func:`calculate_hla_call_reliability` applies
the same three bounds to a posterior and states them itself."""


def _quality_ceiling(quality: float, name: str, what: str) -> list[Ceiling]:
    for bound, tier in _QUALITY_CEILINGS:
        if quality < bound:
            return [Ceiling(name, tier, f"{what} is below {bound:.2f}")]
    return []


def _share_ceiling(share: float | None, name: str, what: str) -> list[Ceiling]:
    """:func:`ancestry_ceiling` as a :class:`Ceiling`, for a match or a demonstrated share."""
    tier = ancestry_ceiling(share)
    if tier is None:
        return []
    if share is None:
        return [Ceiling(name, tier, f"{what} is unknown")]
    return [Ceiling(name, tier, f"{what} is below {0.25 if share < 0.25 else 0.50:.2f}")]


def single_call_ceilings(
    *,
    has_evidence: bool,
    evidence_tier: EvidenceTier | None,
    replication: Replication | None,
    population_allele_frequency: float | None,
    call_source: CallSource,
    imputation_quality: float | None,
    ancestry_match: float | None,
    variant_ancestry: bool,
) -> tuple[Ceiling, ...]:
    """Every ceiling :func:`calculate_confidence` applies to one call, from its inputs.

    The calculator calls this, and so does a reader explaining a saved tier, so the two
    cannot state different rules. Order carries no meaning here: the tier is the weakest.
    """
    ceilings = _evidence_ceilings(has_evidence, evidence_tier, replication)
    # Observation-reliability ceilings cannot be averaged away by strong literature.
    if population_allele_frequency is None:
        # Missing runtime calibration cannot establish that a call is common.
        ceilings.append(
            Ceiling(
                "allele_frequency",
                ConfidenceTier.MODERATE,
                "no population allele frequency was available, so rarity could not be checked",
            )
        )
    elif population_allele_frequency < RARE_CALL_FREQUENCY_CEILING:
        ceilings.append(
            Ceiling(
                "allele_frequency",
                ConfidenceTier.LIKELY_ARTIFACT,
                "the population allele frequency is below 0.001%, the rare-call band",
            )
        )
    if call_source is CallSource.IMPUTED and imputation_quality is None:
        ceilings.append(
            Ceiling(
                "call_quality",
                ConfidenceTier.LIMITED,
                "the call is imputed and its quality was not estimated",
            )
        )
    if imputation_quality is not None:
        ceilings += _quality_ceiling(imputation_quality, "call_quality", "imputation quality")
    # M9.13 variant membership changes the weighted component, not PRS transfer ceilings.
    # Preserve the historical unknown-ancestry strong cap and legacy caller behavior.
    if not (variant_ancestry and ancestry_match is not None):
        ceilings += _share_ceiling(ancestry_match, "ancestry_match", "ancestry match to the study")
    return tuple(ceilings)


def polygenic_ceilings(
    *,
    evidence_tier: EvidenceTier,
    replication: Replication,
    weight_coverage: float,
    weighted_quality: float,
    ancestry_match: float | None,
) -> tuple[Ceiling, ...]:
    """Every ceiling :func:`calculate_polygenic_confidence` applies, in application order.

    The order matters to the saved record only: ``ceilings`` there lists the ones that
    lowered the tier when applied in this order.
    """
    return (
        *_evidence_ceilings(True, evidence_tier, replication),
        *_quality_ceiling(weighted_quality, "weighted_quality", "weighted imputation quality"),
        *_share_ceiling(weight_coverage, "weight_coverage", "comparable score weight"),
        *_share_ceiling(ancestry_match, "ancestry_match", "ancestry match to the study"),
    )


def ancestry_ceiling(ancestry_match: float | None) -> ConfidenceTier | None:
    """The tier ceiling a study-to-sample ancestry match imposes, or ``None`` for none.

    Shared with M9.5's portability record so a PRS result states the same ceiling the
    calculator will apply. ``None`` (not computed) cannot establish portability, so it caps
    at strong rather than passing through as agreement.
    """

    ancestry = _finite_fraction(ancestry_match, "ancestry_match")
    if ancestry is None:
        return ConfidenceTier.STRONG
    if ancestry < 0.25:
        return ConfidenceTier.LIMITED
    if ancestry < 0.50:
        return ConfidenceTier.MODERATE
    return None


def calculate_confidence(
    evidence: Evidence | None,
    *,
    population_allele_frequency: float | None,
    call_source: CallSource,
    imputation_quality: float | None = None,
    imputation_quality_unknown: bool = False,
    ancestry_match: float | None = None,
    variant_ancestry: bool = False,
) -> ConfidenceResult:
    """Compute a finding's confidence without hiding low-confidence findings.

    Args:
        evidence: Authored literature evidence from the card schema.
        population_allele_frequency: Population AF as a fraction, or ``None`` when the
            frequency reference has no value. Rarity always lowers confidence.
        call_source: Whether the call was directly genotyped or imputed. Required so
            missing imputation metadata cannot masquerade as a perfect direct call.
        imputation_quality: Per-variant r2/DR2 as a fraction; forbidden for direct calls.
        imputation_quality_unknown: Explicit unestimated imputed quality. Raw quality
            remains None; its contribution is zero and confidence cannot exceed limited.
        ancestry_match: Numeric study-to-sample match in [0, 1], or ``None`` until
            ancestry is available.
        variant_ancestry: M9.13 categorical membership policy: retain the weighted
            component and unknown cap, without borrowing PRS transfer ceilings.

    The function labels; it never filters. Callers receive a result even at the weakest
    tier, including the empirical rare-call benchmark when applicable.
    """

    if type(variant_ancestry) is not bool:
        raise ConfidenceError("variant_ancestry must be an explicit boolean")
    frequency = _finite_fraction(population_allele_frequency, "population_allele_frequency")
    imputation = _finite_fraction(imputation_quality, "imputation_quality")
    ancestry = _finite_fraction(ancestry_match, "ancestry_match")
    if not isinstance(call_source, CallSource):
        raise ConfidenceError("call_source must be CallSource.DIRECT or CallSource.IMPUTED")
    if type(imputation_quality_unknown) is not bool or (
        imputation_quality_unknown
        and (call_source is not CallSource.IMPUTED or imputation is not None)
    ):
        raise ConfidenceError("unknown imputation quality requires an imputed unestimated call")
    if call_source is CallSource.IMPUTED and imputation is None and not imputation_quality_unknown:
        raise ConfidenceError("an imputed call requires imputation_quality")
    if call_source is CallSource.DIRECT and imputation is not None:
        raise ConfidenceError("a directly genotyped call cannot carry imputation_quality")

    # No applicable phenotype estimate is an absence, never another outcome's effect.
    # Observation rarity/quality still apply; lack of evidence caps the result at limited.
    evidence_score = _EVIDENCE_SCORES[evidence.tier] if evidence is not None else 0.0
    effect_score = _effect_score(evidence.effect) if evidence is not None else 0.0
    replication_score = _REPLICATION_SCORES[evidence.replication] if evidence is not None else 0.0
    frequency_score = _frequency_score(frequency)
    imputation_score = 1.0 if call_source is CallSource.DIRECT else (imputation or 0.0)
    assert imputation_score is not None
    ancestry_score = 0.5 if ancestry is None else ancestry

    score = (
        _WEIGHTS["evidence"] * evidence_score
        + _WEIGHTS["effect"] * effect_score
        + _WEIGHTS["replication"] * replication_score
        + _WEIGHTS["frequency"] * frequency_score
        + _WEIGHTS["imputation"] * imputation_score
        + _WEIGHTS["ancestry"] * ancestry_score
    )
    # Binary-fraction arithmetic is an implementation detail, not useful display data.
    score = round(score, 4)

    inputs = ConfidenceBreakdown(
        evidence_tier=evidence.tier if evidence is not None else None,
        evidence_score=evidence_score,
        effect_measure=evidence.effect.measure if evidence is not None else None,
        effect_value=evidence.effect.value if evidence is not None else None,
        effect_score=round(effect_score, 4),
        replication=evidence.replication if evidence is not None else None,
        replication_score=replication_score,
        population_allele_frequency=frequency,
        frequency_score=frequency_score,
        call_source=call_source,
        imputation_quality=imputation,
        imputation_score=imputation_score,
        ancestry_match=ancestry,
        ancestry_score=ancestry_score,
    )

    empirical_ppv: EmpiricalPpv | None = None
    if frequency is not None and frequency < RARE_CALL_FREQUENCY_CEILING:
        empirical_ppv = EmpiricalPpv(
            estimate=RARE_CALL_EMPIRICAL_PPV,
            population_frequency_ceiling=RARE_CALL_FREQUENCY_CEILING,
            applies_to=(
                "Empirical benchmark for heterozygous SNP-chip calls below 0.001% "
                "population frequency in UK Biobank; not an individual posterior probability. "
                "Not calibrated for this vendor, homozygous/hemizygous calls or imputation. "
                "DOI: 10.1136/bmj.n214."
            ),
        )

    # The raw None values stay visible above. The ceilings keep neutral arithmetic from
    # being mistaken for measured agreement, and strong literature from hiding a weak
    # observation. One function states them, for this calculator and for a reader (M13.4).
    tier = weakest(
        _score_tier(score),
        single_call_ceilings(
            has_evidence=evidence is not None,
            evidence_tier=None if evidence is None else evidence.tier,
            replication=None if evidence is None else evidence.replication,
            population_allele_frequency=frequency,
            call_source=call_source,
            imputation_quality=imputation,
            ancestry_match=ancestry,
            variant_ancestry=variant_ancestry,
        ),
    )
    return ConfidenceResult(tier=tier, score=score, inputs=inputs, empirical_ppv=empirical_ppv)


# ---------------------------------------------------------------------------
# Polygenic scores (M9.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolygenicConfidenceInputs:
    """Every input behind a polygenic card's tier, raw beside its component score.

    ``weight_coverage`` is the share of the score's absolute weight that entered the
    reference comparison (M9.4's ``fraction_of_score_weight``). ``weighted_quality`` is the
    absolute-weight mean of per-row quality over those rows: 1 for a direct call, DR2 for an
    imputed one, 0 where quality is unknown -- the single-variant calculator's own scale.
    """

    evidence_tier: EvidenceTier
    evidence_score: float
    effect_measure: EffectMeasure
    effect_value: float
    effect_score: float
    replication: Replication
    replication_score: float
    weight_coverage: float
    coverage_score: float
    weighted_quality: float
    quality_score: float
    unknown_quality_weight_fraction: float
    ancestry_match: float | None
    ancestry_score: float


POLYGENIC_CEILING_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "evidence_tier": "evidence",
        "replication": "evidence",
        "weighted_quality": "imputation_quality",
        "weight_coverage": "coverage",
        "ancestry_match": "ancestry",
    }
)
"""The name a saved polygenic record gives a ceiling (M9.6), by the input that set it."""


@dataclass(frozen=True)
class PolygenicConfidence:
    tier: ConfidenceTier
    score: float
    inputs: PolygenicConfidenceInputs
    ceilings: tuple[str, ...]
    """Why the tier sits below the weighted score's band, in application order."""


def calculate_polygenic_confidence(
    evidence: Evidence,
    *,
    weight_coverage: float,
    weighted_quality: float,
    unknown_quality_weight_fraction: float,
    ancestry_match: float | None,
) -> PolygenicConfidence:
    """Confidence for a polygenic score, from the calculator's own weights and thresholds.

    Nothing here is a new number. The weights are :data:`_WEIGHTS`, with coverage in the
    slot allele frequency holds for a single call: both measure whether the observation the
    claim rests on is really there. Quality ceilings are the single-variant DR2 ceilings
    applied to the weighted quality; coverage reuses :func:`ancestry_ceiling`'s 0.25/0.5
    bands, because both are the demonstrated share of the score's basis. There is no rarity
    ceiling: a sum over common variants has no rare-call PPV (AGENTS.md 4.1). The function
    labels; it never filters.
    """

    coverage = _finite_fraction(weight_coverage, "weight_coverage")
    quality = _finite_fraction(weighted_quality, "weighted_quality")
    unknown = _finite_fraction(unknown_quality_weight_fraction, "unknown_quality_weight_fraction")
    ancestry = _finite_fraction(ancestry_match, "ancestry_match")
    if coverage is None or quality is None or unknown is None:
        raise ConfidenceError("polygenic confidence needs coverage and quality fractions")
    evidence_score = _EVIDENCE_SCORES[evidence.tier]
    effect_score = round(_effect_score(evidence.effect), 4)
    replication_score = _REPLICATION_SCORES[evidence.replication]
    ancestry_score = 0.5 if ancestry is None else ancestry
    score = round(
        _WEIGHTS["evidence"] * evidence_score
        + _WEIGHTS["effect"] * effect_score
        + _WEIGHTS["replication"] * replication_score
        + _WEIGHTS["frequency"] * coverage
        + _WEIGHTS["imputation"] * quality
        + _WEIGHTS["ancestry"] * ancestry_score,
        4,
    )
    tier = _score_tier(score)
    ceilings: list[str] = []
    # The saved record names a ceiling only where it lowered the tier, in application order.
    for ceiling in polygenic_ceilings(
        evidence_tier=evidence.tier,
        replication=evidence.replication,
        weight_coverage=coverage,
        weighted_quality=quality,
        ancestry_match=ancestry,
    ):
        if ceiling.tier.rank > tier.rank:
            tier = ceiling.tier
            ceilings.append(POLYGENIC_CEILING_NAMES[ceiling.input])
    return PolygenicConfidence(
        tier=tier,
        score=score,
        inputs=PolygenicConfidenceInputs(
            evidence_tier=evidence.tier,
            evidence_score=evidence_score,
            effect_measure=evidence.effect.measure,
            effect_value=evidence.effect.value,
            effect_score=effect_score,
            replication=evidence.replication,
            replication_score=replication_score,
            weight_coverage=coverage,
            coverage_score=coverage,
            weighted_quality=quality,
            quality_score=quality,
            unknown_quality_weight_fraction=unknown,
            ancestry_match=ancestry,
            ancestry_score=ancestry_score,
        ),
        ceilings=tuple(ceilings),
    )


# ---------------------------------------------------------------------------
# HLA classifier calls (M11.3)
# ---------------------------------------------------------------------------

HLA_PUBLISHED_CALL_THRESHOLD: Final[float] = 0.5
"""The HIBAG call threshold Zheng et al. 2014 chose (DOI 10.1038/tpj.2013.18), which they
report corresponds to about 80% prediction accuracy. Recorded beside each call so a reader
can see which side of it the call falls on; it filters nothing and sets no tier."""


@dataclass(frozen=True)
class HLACallReliability:
    """The observation ceiling one HLA classifier call carries into any card built on it."""

    ceiling: ConfidenceTier | None
    """``None`` when no measurement lowers it; never a claim the finding is established."""

    ceilings: tuple[str, ...]
    """Which inputs lowered the ceiling, in application order."""

    posterior: float
    marker_coverage: float
    ancestry_match: float | None
    meets_published_call_threshold: bool


def calculate_hla_call_reliability(
    *, posterior: float, marker_coverage: float, ancestry_match: float | None
) -> HLACallReliability:
    """Fold a call's joint posterior, marker coverage and classifier ancestry into a ceiling.

    Nothing here is a new number. The joint posterior sits in the imputation-quality slot
    with the single-variant DR2 ceilings -- where :func:`calculate_confidence` places it once
    an M11.4 card supplies literature evidence. Marker coverage reuses
    :func:`ancestry_ceiling`'s 0.25/0.5 bands, as polygenic weight coverage does, and the
    classifier's ancestry match uses :func:`ancestry_ceiling` itself, so an unknown match
    caps at strong. There is no score: without a claim there is nothing to weight. The
    function labels; it never filters a call.
    """

    quality = _finite_fraction(posterior, "posterior")
    coverage = _finite_fraction(marker_coverage, "marker_coverage")
    ancestry = _finite_fraction(ancestry_match, "ancestry_match")
    if quality is None or coverage is None:
        raise ConfidenceError("HLA call reliability needs a posterior and marker coverage")
    ceiling: ConfidenceTier | None = None
    ceilings: list[str] = []

    def cap(limit: ConfidenceTier | None, why: str) -> None:
        nonlocal ceiling
        if limit is not None and (ceiling is None or limit.rank > ceiling.rank):
            ceiling = limit
            ceilings.append(why)

    if quality < 0.30:
        cap(ConfidenceTier.LIKELY_ARTIFACT, "posterior")
    elif quality < 0.60:
        cap(ConfidenceTier.LIMITED, "posterior")
    elif quality < 0.80:
        cap(ConfidenceTier.MODERATE, "posterior")
    cap(ancestry_ceiling(coverage), "marker_coverage")
    cap(ancestry_ceiling(ancestry), "ancestry")
    return HLACallReliability(
        ceiling=ceiling,
        ceilings=tuple(ceilings),
        posterior=quality,
        marker_coverage=coverage,
        ancestry_match=ancestry,
        meets_published_call_threshold=quality >= HLA_PUBLISHED_CALL_THRESHOLD,
    )
