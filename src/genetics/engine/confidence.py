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
from dataclasses import dataclass
from enum import StrEnum
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
    ``call_source`` makes a direct call explicit, while an imputed call is invalid unless
    it carries quality.
    """

    evidence_tier: EvidenceTier
    evidence_score: float
    effect_measure: EffectMeasure
    effect_value: float
    effect_score: float
    replication: Replication
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
    its half-width is used.  Without an interval, a non-zero estimate receives a neutral
    0.5 rather than allowing centimetres, kilograms and standard deviations to masquerade
    as one scale.
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


def _score_tier(score: float) -> ConfidenceTier:
    if score >= 0.85:
        return ConfidenceTier.WELL_ESTABLISHED
    if score >= 0.70:
        return ConfidenceTier.STRONG
    if score >= 0.50:
        return ConfidenceTier.MODERATE
    return ConfidenceTier.LIMITED


def _weaker_of(left: ConfidenceTier, right: ConfidenceTier) -> ConfidenceTier:
    return left if left.rank >= right.rank else right


def calculate_confidence(
    evidence: Evidence,
    *,
    population_allele_frequency: float | None,
    call_source: CallSource,
    imputation_quality: float | None = None,
    ancestry_match: float | None = None,
) -> ConfidenceResult:
    """Compute a finding's confidence without hiding low-confidence findings.

    Args:
        evidence: Authored literature evidence from the card schema.
        population_allele_frequency: Population AF as a fraction, or ``None`` when the
            frequency reference has no value. Rarity always lowers confidence.
        call_source: Whether the call was directly genotyped or imputed. Required so
            missing imputation metadata cannot masquerade as a perfect direct call.
        imputation_quality: Per-variant r2/DR2 as a fraction. Required for imputed calls
            and forbidden for direct calls.
        ancestry_match: Numeric study-to-sample match in [0, 1], or ``None`` until
            ancestry is available.

    The function labels; it never filters. Callers receive a result even at the weakest
    tier, including the empirical rare-call benchmark when applicable.
    """

    frequency = _finite_fraction(population_allele_frequency, "population_allele_frequency")
    imputation = _finite_fraction(imputation_quality, "imputation_quality")
    ancestry = _finite_fraction(ancestry_match, "ancestry_match")
    if not isinstance(call_source, CallSource):
        raise ConfidenceError("call_source must be CallSource.DIRECT or CallSource.IMPUTED")
    if call_source is CallSource.IMPUTED and imputation is None:
        raise ConfidenceError("an imputed call requires imputation_quality")
    if call_source is CallSource.DIRECT and imputation is not None:
        raise ConfidenceError("a directly genotyped call cannot carry imputation_quality")

    evidence_score = _EVIDENCE_SCORES[evidence.tier]
    effect_score = _effect_score(evidence.effect)
    replication_score = _REPLICATION_SCORES[evidence.replication]
    frequency_score = _frequency_score(frequency)
    imputation_score = 1.0 if call_source is CallSource.DIRECT else imputation
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
        evidence_tier=evidence.tier,
        evidence_score=evidence_score,
        effect_measure=evidence.effect.measure,
        effect_value=evidence.effect.value,
        effect_score=round(effect_score, 4),
        replication=evidence.replication,
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
                "population frequency; not an individual posterior probability."
            ),
        )

    tier = _score_tier(score)
    # A striking, common observation does not upgrade weak literature. These are claim-
    # evidence ceilings, parallel to the observation-reliability ceilings below.
    if evidence.tier is EvidenceTier.ANECDOTAL or evidence.replication is Replication.CONFLICTING:
        tier = _weaker_of(tier, ConfidenceTier.LIMITED)
    elif evidence.tier is EvidenceTier.CANDIDATE_GENE:
        tier = _weaker_of(tier, ConfidenceTier.MODERATE)

    # Observation-reliability ceilings cannot be averaged away by strong literature.
    if empirical_ppv is not None or (imputation is not None and imputation < 0.30):
        tier = ConfidenceTier.LIKELY_ARTIFACT
    elif imputation is not None and imputation < 0.60:
        tier = _weaker_of(tier, ConfidenceTier.LIMITED)
    elif imputation is not None and imputation < 0.80:
        tier = _weaker_of(tier, ConfidenceTier.MODERATE)

    if ancestry is not None and ancestry < 0.25:
        tier = _weaker_of(tier, ConfidenceTier.LIMITED)
    elif ancestry is not None and ancestry < 0.50:
        tier = _weaker_of(tier, ConfidenceTier.MODERATE)

    # Missing runtime calibration cannot establish that a call is common or portable.
    # Keep the raw None values visible above; these ceilings prevent neutral arithmetic
    # from being mistaken for measured agreement while the M5/M7 references are absent.
    if frequency is None:
        tier = _weaker_of(tier, ConfidenceTier.MODERATE)
    if ancestry is None:
        tier = _weaker_of(tier, ConfidenceTier.STRONG)

    return ConfidenceResult(tier=tier, score=score, inputs=inputs, empirical_ppv=empirical_ppv)
