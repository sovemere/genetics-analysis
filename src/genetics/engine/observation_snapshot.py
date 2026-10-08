"""Validate saved M8.5 dosage evidence without consulting caches or knowledge packs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from genetics.engine.confidence import RARE_CALL_FREQUENCY_CEILING, CallSource, ConfidenceTier
from genetics.engine.evidence import (
    ObservationEvidence,
    PopulationFrequency,
    select_observed_frequency,
)
from genetics.imputation.quality import ImputationEvidence


def validate_imputation_snapshot(card: Mapping[str, Any], *, require_detail: bool = False) -> None:
    try:
        multi = card.get("multi_marker")
        records = multi["markers"] if isinstance(multi, Mapping) else [card]
        for record in records:
            _validate(record, require_detail=require_detail)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        raise ValueError("invalid or inconsistent saved imputation evidence") from None


def _validate(record: Mapping[str, Any], *, require_detail: bool) -> None:
    observation = record.get("observation")
    if observation is None:
        return
    if not isinstance(observation, Mapping):
        raise ValueError
    raw = observation.get("imputation")
    if raw is None:
        if require_detail and observation.get("call_source") == "imputed":
            raise ValueError
        return
    detail = ImputationEvidence.from_dict(raw)
    if (
        observation.get("call_source") != "imputed"
        or observation.get("imputation_quality") != detail.card_quality
    ):
        raise ValueError
    match = record["match"]
    observed = match["observed_genotype"]
    if (
        not isinstance(observed, str)
        or len(observed) != 2
        or not set(observed) <= {detail.ref, *detail.alt}
        or match["call_status"] != ("hemizygous" if detail.ploidy == 1 else "called")
        or (detail.ploidy == 1 and observed[0] != observed[1])
    ):
        raise ValueError
    if detail.source == "imputed_no_call":
        count = observed.count(detail.alt[0]) / (2 if detail.ploidy == 1 else 1)
        if detail.dosage != (count,):
            raise ValueError
    if record["status"] == "matched":
        variant = record["variant"]
        if set(variant["alleles"]) != {detail.ref, *detail.alt} or match["genotype"] != observed:
            raise ValueError
    confidence = record.get("confidence")
    if (confidence is not None) != (record["status"] == "matched"):
        raise ValueError
    if confidence is not None:
        inputs = confidence["inputs"]
        if any(
            inputs.get(k) != observation[k]
            for k in ("call_source", "imputation_quality", "ancestry_match")
        ) or inputs.get("imputation_score") != (detail.card_quality or 0.0):
            raise ValueError
        frequencies = record["frequencies"]
        if not isinstance(frequencies, list):
            raise ValueError
        frequency_items = tuple(PopulationFrequency(**item) for item in frequencies)
        if any(f.allele not in {detail.ref, *detail.alt} for f in frequency_items):
            raise ValueError
        ObservationEvidence(
            call_source=CallSource.IMPUTED,
            frequencies=frequency_items,
            imputation_quality=detail.card_quality,
            imputation=detail,
        )
        called = set(match["genotype"] or observed)
        expected, _ = select_observed_frequency(called, frequency_items)
        frequency = None if expected is None else expected.frequency
        selected = record["confidence_frequency"]
        if (
            (
                selected is not None
                and (selected not in frequencies or selected["allele"] not in called)
            )
            or (None if selected is None else selected["frequency"]) != frequency
            or inputs.get("population_allele_frequency") != frequency
        ):
            raise ValueError
        quality = detail.card_quality
        ceiling = (
            ConfidenceTier.LIMITED
            if quality is None
            else ConfidenceTier.LIKELY_ARTIFACT
            if quality < 0.30
            else ConfidenceTier.LIMITED
            if quality < 0.60
            else ConfidenceTier.MODERATE
            if quality < 0.80
            else ConfidenceTier.WELL_ESTABLISHED
        )
        if frequency is not None and frequency < RARE_CALL_FREQUENCY_CEILING:
            ceiling = ConfidenceTier.LIKELY_ARTIFACT
        elif frequency is None and ceiling.rank < ConfidenceTier.MODERATE.rank:
            ceiling = ConfidenceTier.MODERATE
        if ConfidenceTier(confidence["tier"]).rank < ceiling.rank:
            raise ValueError
