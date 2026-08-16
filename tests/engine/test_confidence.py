"""Confidence calculation (roadmap M3.3).

The boundary cases are the product contract: strong literature must not rescue a rare
chip observation, and common large-effect trait evidence must be allowed to reach the top
tier.  Tests use evidence objects only and contain no genotype rows or personal data.
"""

from __future__ import annotations

import math

import pytest

from genetics.engine.cards import (
    Ancestry,
    Effect,
    EffectMeasure,
    Evidence,
    EvidenceTier,
    Replication,
)
from genetics.engine.confidence import (
    RARE_CALL_EMPIRICAL_PPV,
    RARE_CALL_FREQUENCY_CEILING,
    CallSource,
    ConfidenceError,
    ConfidenceTier,
    calculate_confidence,
)


def _evidence(
    *,
    tier: EvidenceTier = EvidenceTier.FUNCTIONAL,
    measure: EffectMeasure = EffectMeasure.ODDS_RATIO,
    value: float = 7.0,
    replication: Replication = Replication.INDEPENDENT,
    units: str | None = None,
    ci_low: float | None = None,
    ci_high: float | None = None,
) -> Evidence:
    return Evidence(
        tier=tier,
        effect=Effect(measure, value, units, ci_low, ci_high),
        sample_size=10_000,
        ancestry=(Ancestry.EUR,),
        replication=replication,
    )


def test_rare_pathogenic_chip_hit_is_likely_artifact_with_empirical_ppv() -> None:
    """Excellent ClinVar evidence cannot rescue the reliability of a very rare call."""

    result = calculate_confidence(
        _evidence(tier=EvidenceTier.EXPERT_CURATED, value=12.0),
        population_allele_frequency=0.000001,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )

    assert result.tier is ConfidenceTier.LIKELY_ARTIFACT
    assert result.empirical_ppv is not None
    assert result.empirical_ppv.estimate == RARE_CALL_EMPIRICAL_PPV == 0.16
    assert result.empirical_ppv.population_frequency_ceiling == RARE_CALL_FREQUENCY_CEILING
    assert "not an individual posterior" in result.empirical_ppv.applies_to
    assert result.inputs.frequency_score == 0.0


def test_common_large_effect_trait_is_well_established() -> None:
    """A HERC2-like common, replicated, large-effect result reaches the top tier."""

    result = calculate_confidence(
        _evidence(),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )

    assert result.tier is ConfidenceTier.WELL_ESTABLISHED
    assert result.empirical_ppv is None
    assert result.inputs.effect_score == 1.0
    assert result.inputs.frequency_score == 1.0
    assert result.score >= 0.85


def test_rarity_monotonically_lowers_the_score() -> None:
    frequencies = [0.20, 0.02, 0.005, 0.0005, 0.00005, 0.000001]
    results = [
        calculate_confidence(
            _evidence(),
            population_allele_frequency=frequency,
            call_source=CallSource.DIRECT,
            ancestry_match=1.0,
        )
        for frequency in frequencies
    ]

    assert [result.score for result in results] == sorted(
        (result.score for result in results), reverse=True
    )
    assert results[-1].tier is ConfidenceTier.LIKELY_ARTIFACT


def test_the_rare_band_is_strictly_below_point_zero_zero_one_percent() -> None:
    at_boundary = calculate_confidence(
        _evidence(),
        population_allele_frequency=RARE_CALL_FREQUENCY_CEILING,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )
    below_boundary = calculate_confidence(
        _evidence(),
        population_allele_frequency=math.nextafter(RARE_CALL_FREQUENCY_CEILING, 0.0),
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )

    assert at_boundary.empirical_ppv is None
    assert at_boundary.tier is not ConfidenceTier.LIKELY_ARTIFACT
    assert below_boundary.empirical_ppv is not None
    assert below_boundary.tier is ConfidenceTier.LIKELY_ARTIFACT


def test_imputation_quality_degrades_and_caps_confidence() -> None:
    qualities = [None, 0.85, 0.70, 0.50, 0.20]
    results = [
        calculate_confidence(
            _evidence(),
            population_allele_frequency=0.20,
            call_source=(CallSource.DIRECT if quality is None else CallSource.IMPUTED),
            imputation_quality=quality,
            ancestry_match=1.0,
        )
        for quality in qualities
    ]

    assert [result.score for result in results] == sorted(
        (result.score for result in results), reverse=True
    )
    assert [result.tier for result in results] == [
        ConfidenceTier.WELL_ESTABLISHED,
        ConfidenceTier.WELL_ESTABLISHED,
        ConfidenceTier.MODERATE,
        ConfidenceTier.LIMITED,
        ConfidenceTier.LIKELY_ARTIFACT,
    ]


def test_high_quality_imputation_does_not_rescue_a_rare_call() -> None:
    result = calculate_confidence(
        _evidence(tier=EvidenceTier.CLINICAL_GUIDELINE),
        population_allele_frequency=0.000001,
        call_source=CallSource.IMPUTED,
        imputation_quality=0.99,
        ancestry_match=1.0,
    )

    assert result.tier is ConfidenceTier.LIKELY_ARTIFACT
    assert result.empirical_ppv is not None


def test_imputed_call_requires_quality_and_direct_call_forbids_it() -> None:
    with pytest.raises(ConfidenceError, match="requires imputation_quality"):
        calculate_confidence(
            _evidence(),
            population_allele_frequency=0.20,
            call_source=CallSource.IMPUTED,
        )

    with pytest.raises(ConfidenceError, match="cannot carry imputation_quality"):
        calculate_confidence(
            _evidence(),
            population_allele_frequency=0.20,
            call_source=CallSource.DIRECT,
            imputation_quality=0.95,
        )


def test_ancestry_mismatch_degrades_and_caps_confidence() -> None:
    matched = calculate_confidence(
        _evidence(),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )
    partial = calculate_confidence(
        _evidence(),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=0.40,
    )
    mismatched = calculate_confidence(
        _evidence(),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=0.10,
    )

    assert matched.score > partial.score > mismatched.score
    assert partial.tier is ConfidenceTier.MODERATE
    assert mismatched.tier is ConfidenceTier.LIMITED


def test_unknown_runtime_inputs_remain_visible_as_unknown() -> None:
    result = calculate_confidence(
        _evidence(),
        population_allele_frequency=None,
        call_source=CallSource.DIRECT,
        ancestry_match=None,
    )

    assert result.inputs.population_allele_frequency is None
    assert result.inputs.frequency_score == 0.5
    assert result.inputs.imputation_quality is None
    assert result.inputs.imputation_score == 1.0
    assert result.inputs.ancestry_match is None
    assert result.inputs.ancestry_score == 0.5
    assert result.tier is ConfidenceTier.MODERATE


def test_weak_literature_is_limited_not_mislabeled_as_an_artifact() -> None:
    result = calculate_confidence(
        _evidence(tier=EvidenceTier.ANECDOTAL, replication=Replication.NONE),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )

    assert result.tier is ConfidenceTier.LIMITED
    assert result.empirical_ppv is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("population_allele_frequency", -0.1),
        ("population_allele_frequency", 1.1),
        ("population_allele_frequency", math.nan),
        ("population_allele_frequency", math.inf),
        ("imputation_quality", -0.1),
        ("imputation_quality", 1.1),
        ("ancestry_match", -0.1),
        ("ancestry_match", 1.1),
    ],
)
def test_runtime_fractions_must_be_finite_and_bounded(name: str, value: float) -> None:
    kwargs: dict[str, object] = {
        "population_allele_frequency": 0.2,
        "call_source": CallSource.DIRECT,
        "imputation_quality": None,
        "ancestry_match": 1.0,
    }
    kwargs[name] = value

    with pytest.raises(ConfidenceError, match=name):
        calculate_confidence(_evidence(), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["population_allele_frequency", "imputation_quality"])
def test_booleans_are_not_accepted_as_runtime_fractions(name: str) -> None:
    kwargs: dict[str, object] = {
        "population_allele_frequency": 0.2,
        "call_source": CallSource.DIRECT,
        "imputation_quality": None,
        "ancestry_match": 1.0,
    }
    kwargs[name] = True

    with pytest.raises(ConfidenceError, match=name):
        calculate_confidence(_evidence(), **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (Effect(EffectMeasure.ODDS_RATIO, 1.0), 0.0),
        (Effect(EffectMeasure.ODDS_RATIO, 4.0), 1.0),
        (Effect(EffectMeasure.ODDS_RATIO, 0.25), 1.0),
        (Effect(EffectMeasure.PENETRANCE, 0.8), 0.8),
        (Effect(EffectMeasure.PERCENT_VARIANCE_EXPLAINED, 2.5), 0.5),
        (Effect(EffectMeasure.BETA, 0.3, "cm"), 0.5),
        (Effect(EffectMeasure.BETA, 0.0, "cm"), 0.0),
    ],
)
def test_effect_measures_are_normalised_transparently(effect: Effect, expected: float) -> None:
    evidence = _evidence()
    evidence = Evidence(
        tier=evidence.tier,
        effect=effect,
        sample_size=evidence.sample_size,
        ancestry=evidence.ancestry,
        replication=evidence.replication,
    )

    result = calculate_confidence(
        evidence,
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )

    assert result.inputs.effect_score == expected


def test_unit_bearing_effect_uses_unit_free_interval_precision() -> None:
    result = calculate_confidence(
        _evidence(
            measure=EffectMeasure.MEAN_DIFFERENCE,
            value=2.0,
            units="cm",
            ci_low=1.0,
            ci_high=3.0,
        ),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )

    assert result.inputs.effect_score == 1.0


def test_effect_score_calibration_points() -> None:
    """Pin the interval rule to numbers, because prose alone already drifted from it once.

    The docstring described the half-width while the code divided by the full width, and
    nothing in the module said which was intended. These three points fix the calibration:
    the null scores zero, a nominally significant effect (z = 1.96, so |value| equal to
    the half-width) scores 0.5 -- exactly the interval-free default, so an authored
    interval starts paying off precisely where the effect becomes significant -- and
    saturation arrives at twice that.
    """
    scores = []
    for value, ci_low, ci_high in [
        (0.0, -1.0, 1.0),  # null: the interval spans zero symmetrically
        (1.0, 0.0, 2.0),  # z = 1.96: |value| equals the half-width
        (2.0, 0.0, 2.0),  # z = 3.92: |value| equals the full width
    ]:
        result = calculate_confidence(
            _evidence(
                measure=EffectMeasure.BETA,
                value=value,
                units="cm",
                ci_low=ci_low,
                ci_high=ci_high,
            ),
            population_allele_frequency=0.20,
            call_source=CallSource.DIRECT,
            ancestry_match=1.0,
        )
        scores.append(result.inputs.effect_score)

    assert scores == [0.0, 0.5, 1.0]

    interval_free = calculate_confidence(
        _evidence(measure=EffectMeasure.BETA, value=1.0, units="cm"),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )
    assert interval_free.inputs.effect_score == scores[1], (
        "the crossover must sit at nominal significance: an interval-bearing effect that "
        "just reaches z = 1.96 should score what an effect with no interval at all scores"
    )


def test_conflicting_replication_is_weaker_than_independent_replication() -> None:
    independent = calculate_confidence(
        _evidence(replication=Replication.INDEPENDENT),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )
    conflicting = calculate_confidence(
        _evidence(replication=Replication.CONFLICTING),
        population_allele_frequency=0.20,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )

    assert independent.inputs.replication_score > conflicting.inputs.replication_score
    assert independent.score > conflicting.score


def test_all_numeric_inputs_that_produced_the_result_are_exposed() -> None:
    result = calculate_confidence(
        _evidence(value=2.0),
        population_allele_frequency=0.08,
        call_source=CallSource.IMPUTED,
        imputation_quality=0.91,
        ancestry_match=0.75,
    )

    assert result.inputs.evidence_score == 0.90
    assert result.inputs.effect_value == 2.0
    assert result.inputs.effect_score == 0.5
    assert result.inputs.replication_score == 0.90
    assert result.inputs.population_allele_frequency == 0.08
    assert result.inputs.frequency_score == 1.0
    assert result.inputs.call_source is CallSource.IMPUTED
    assert result.inputs.imputation_quality == 0.91
    assert result.inputs.imputation_score == 0.91
    assert result.inputs.ancestry_match == 0.75
    assert result.inputs.ancestry_score == 0.75
    assert 0.0 <= result.score <= 1.0


def test_confidence_ladder_vocabulary_is_disjoint_from_authored_evidence() -> None:
    assert {tier.value for tier in ConfidenceTier}.isdisjoint({tier.value for tier in EvidenceTier})
    assert [tier.rank for tier in ConfidenceTier] == list(range(len(ConfidenceTier)))
