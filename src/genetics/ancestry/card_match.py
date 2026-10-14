"""Selected-evidence study comparison; no AADR country mapping (M9.13)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from genetics.engine.cards import Ancestry, Evidence

CODES = frozenset({"AFR", "AMR", "EAS", "EUR", "SAS"})


def sample_context(
    placement: Mapping[str, Any] | None, gate: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Compact saved context; population codes come from the panel's own labels."""
    if placement is None:
        placement = {"status": "not_run", "reason": "1000 Genomes placement not supplied."}
    status = placement.get("status")
    reason = placement.get("reason") or None
    population = placement.get("population")
    region = placement.get("region")
    if status not in {"placed", "declined", "not_run"}:
        raise ValueError("Unknown 1000 Genomes placement state")
    if status == "placed":
        if not isinstance(population, str) or not population or region not in CODES or reason:
            raise ValueError("Placed sample requires panel population and super-population")
    elif (
        not isinstance(reason, str)
        or not reason.strip()
        or population is not None
        or region is not None
    ):
        raise ValueError("Unplaced sample requires a reason and no population")
    gate_status = "not_supplied" if gate is None else gate.get("status")
    gate_reason = None if gate is None else gate.get("reason") or None
    if gate_status not in {"not_supplied", "placed", "declined", "not_run"}:
        raise ValueError("Unknown AADR decline gate")
    if gate_status in {"declined", "not_run"} and (
        not isinstance(gate_reason, str) or not gate_reason.strip()
    ):
        raise ValueError("AADR decline/not-run gate requires a reason")
    return {
        "status": status,
        "reason": reason,
        "population": population,
        "super_population": region,
        "aadr_status": gate_status,
        "aadr_reason": gate_reason,
    }


def compare(evidence: Evidence | None, sample: Mapping[str, Any]) -> dict[str, Any]:
    """Explicit membership at the study vocabulary's resolution; MULTI is not universal."""
    study = [] if evidence is None else [a.value for a in evidence.ancestry]
    region = sample["super_population"]
    numeric: float | None = None
    if evidence is None:
        state = "no_applicable_evidence"
        note = "no applicable phenotype estimate; no study population is assigned"
    elif sample["aadr_status"] == "declined" or sample["status"] == "declined":
        state = "declined"
        numeric = 0.0
        reason = sample["aadr_reason"] if sample["aadr_status"] == "declined" else sample["reason"]
        note = "placement declined; the sample is unrepresented. " + str(reason)
    elif sample["status"] == "not_run":
        state = "not_run"
        note = "1000 Genomes placement not run; ancestry agreement is unknown. " + str(
            sample["reason"]
        )
    elif region in study:
        state = "matched"
        numeric = 1.0
        note = f"matched at super-population level ({region}); this is not individual calibration"
    elif Ancestry.UNKNOWN.value in study:
        state = "unknown_study_population"
        note = "study population UNKNOWN; agreement cannot be established"
    elif Ancestry.MULTI.value in study:
        state = "unspecified_multi"
        note = (
            "study population MULTI without a matching explicit code; "
            "agreement cannot be established"
        )
    else:
        state = "mismatched"
        numeric = 0.0
        note = (
            "mismatched at super-population level; "
            "the published effect is not calibrated for this sample"
        )
    study_text = "/".join(study) or "no applicable estimate"
    sample_text = (
        f"{sample['population']} ({region})" if sample["status"] == "placed" else sample["status"]
    )
    text = f"Ancestry: {note.rstrip('.')}. Study: {study_text}; 1000 Genomes sample: {sample_text}."
    return {
        "schema_version": 1,
        "method": "1000-genomes-super-population-membership-v1",
        "confidence_policy": "variant-weighted-v1",
        "study": study,
        "sample": dict(sample),
        "state": state,
        "ancestry_match": numeric,
        "text": text,
    }


def display(text: str, comparison: Mapping[str, Any] | None) -> str:
    """Put the comparison on every face/detail; templates can choose its location."""
    if comparison is None or comparison["text"] in text:
        return text
    return text + " " + str(comparison["text"])


def validate_card(card: Mapping[str, Any], sample: Mapping[str, Any]) -> None:
    """Validate new snapshots from frozen evidence, without current references or packs."""
    from genetics.engine.confidence import CallSource, calculate_confidence
    from genetics.engine.evidence import (
        ObservationEvidence,
        PopulationFrequency,
        select_observed_frequency,
    )
    from genetics.engine.matcher import complement
    from genetics.engine.serialization import confidence_payload, frequency_payload
    from genetics.imputation.quality import ImputationEvidence

    try:
        if card.get("kind") != "interpretation":
            if card.get("ancestry_comparison") is not None:
                raise ValueError
            return
        raw_evidence = card.get("evidence")
        evidence = None if raw_evidence is None else Evidence.parse(raw_evidence, "saved evidence")
        expected = compare(evidence, sample)
        actual = card.get("ancestry_comparison")
        if not isinstance(actual, Mapping) or type(actual.get("schema_version")) is not int:
            raise ValueError
        numeric = actual.get("ancestry_match")
        if isinstance(numeric, bool) or actual != expected:
            raise ValueError
        if any(expected["text"] not in card[key] for key in ("summary", "detail")):
            raise ValueError
        multi = card.get("multi_marker")
        records = multi["markers"] if isinstance(multi, Mapping) else [card]
        for record in records:
            if multi is not None and record.get("ancestry_comparison") != expected:
                raise ValueError
            observed = record["observation"]
            if (
                isinstance(observed.get("ancestry_match"), bool)
                or observed["ancestry_match"] != numeric
            ):
                raise ValueError
            if record["status"] != "matched":
                if record.get("confidence") is not None:
                    raise ValueError
                continue
            raw_detail = observed.get("imputation")
            detail = None if raw_detail is None else ImputationEvidence.from_dict(raw_detail)
            frequencies = tuple(PopulationFrequency(**f) for f in record["frequencies"])
            observation = ObservationEvidence(
                call_source=CallSource(observed["call_source"]),
                imputation_quality=observed["imputation_quality"],
                ancestry_match=numeric,
                frequencies=frequencies,
                imputation=detail,
            )
            match = record["match"]
            called = set(match["genotype"] or match["observed_genotype"])
            if match["strand"] == "ambiguous":
                called.update(complement(match["observed_genotype"]))
            frequency, _ = select_observed_frequency(called, frequencies)
            if record["confidence_frequency"] != (
                None if frequency is None else frequency_payload(frequency)
            ):
                raise ValueError
            result = calculate_confidence(
                evidence,
                population_allele_frequency=None if frequency is None else frequency.frequency,
                call_source=observation.call_source,
                imputation_quality=observation.imputation_quality,
                imputation_quality_unknown=observation.call_source is CallSource.IMPUTED
                and observation.imputation_quality is None,
                ancestry_match=numeric,
                variant_ancestry=True,
            )
            if record["confidence"] != confidence_payload(result):
                raise ValueError
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ValueError("Invalid or inconsistent saved card ancestry comparison") from None
