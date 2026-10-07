"""Shared observation/calibration serialization for scalar and multi-marker results."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from genetics.engine.confidence import ConfidenceResult
    from genetics.engine.evidence import AssembledCard, ObservationEvidence, PopulationFrequency


def observation_payload(observed: ObservationEvidence) -> dict[str, Any]:
    result: dict[str, Any] = {
        "call_source": observed.call_source.value,
        "imputation_quality": observed.imputation_quality,
        "ancestry_match": observed.ancestry_match,
    }
    if observed.imputation is not None:
        result["imputation"] = observed.imputation.to_dict()
    return result


def frequency_payload(frequency: PopulationFrequency) -> dict[str, Any]:
    return {
        "allele": frequency.allele,
        "frequency": frequency.frequency,
        "population": frequency.population,
        "source": frequency.source,
    }


def confidence_payload(confidence: ConfidenceResult) -> dict[str, Any]:
    """Tier, score, inputs and scoped benchmark; preserved in immutable run snapshots."""
    inputs = confidence.inputs
    ppv = confidence.empirical_ppv
    return {
        "tier": confidence.tier.value,
        "score": confidence.score,
        "inputs": {
            "evidence_tier": inputs.evidence_tier.value
            if inputs.evidence_tier is not None
            else None,
            "evidence_score": inputs.evidence_score,
            "effect_measure": inputs.effect_measure.value
            if inputs.effect_measure is not None
            else None,
            "effect_value": inputs.effect_value,
            "effect_score": inputs.effect_score,
            "replication": inputs.replication.value if inputs.replication is not None else None,
            "replication_score": inputs.replication_score,
            "population_allele_frequency": inputs.population_allele_frequency,
            "frequency_score": inputs.frequency_score,
            "call_source": inputs.call_source.value,
            "imputation_quality": inputs.imputation_quality,
            "imputation_score": inputs.imputation_score,
            "ancestry_match": inputs.ancestry_match,
            "ancestry_score": inputs.ancestry_score,
        },
        "empirical_ppv": None
        if ppv is None
        else {
            "estimate": ppv.estimate,
            "population_frequency_ceiling": ppv.population_frequency_ceiling,
            "applies_to": ppv.applies_to,
        },
    }


def marker_payload(assembled: AssembledCard) -> dict[str, Any]:
    """One constituent marker's observation; never the placeholder interpretation."""
    assert assembled.card.match is not None and assembled.observation is not None
    variant = assembled.card.match.variant
    match = assembled.match
    observed = assembled.observation
    return {
        "variant": {
            "rsid": variant.rsid,
            "chrom": variant.key.chrom.value,
            "pos_grch37": variant.key.pos_grch37,
            "alleles": list(variant.key.alleles),
        },
        "status": match.status.value,
        "match": {
            "reason": match.reason,
            "genotype": match.genotype,
            "observed_genotype": match.observed_genotype,
            "observed_rsid": match.observed_rsid,
            "call_status": match.call_status.value if match.call_status is not None else None,
            "strand": match.strand.value,
            "outcome_name": None,
            "candidate_outcomes": [],
        },
        "observation": observation_payload(observed),
        "frequencies": [frequency_payload(f) for f in assembled.frequencies],
        "confidence_frequency": None
        if assembled.confidence_frequency is None
        else frequency_payload(assembled.confidence_frequency),
        "confidence": None
        if assembled.confidence is None
        else confidence_payload(assembled.confidence),
        "computed_caveats": list(assembled.computed_caveats),
    }
