"""Selected-evidence study comparison; no AADR country mapping (M9.13)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from genetics.engine.cards import Ancestry, CardVariant, Evidence

CODES = frozenset({"AFR", "AMR", "EAS", "EUR", "SAS"})


def sample_context(
    placement: Mapping[str, Any] | None,
    gate: Mapping[str, Any] | None = None,
    *,
    require_fits: bool = False,
) -> dict[str, Any]:
    """Compact saved context; population codes come from the panel's own labels."""
    if placement is None:
        placement = {"status": "not_run", "reason": "1000 Genomes placement not supplied."}
    status = placement.get("status")
    raw_reason = placement.get("reason")
    if raw_reason is not None and not isinstance(raw_reason, str):
        raise ValueError("Placement reason must be text")
    reason = raw_reason or None
    population = placement.get("population")
    region = placement.get("region")
    if status not in {"placed", "declined", "not_run"}:
        raise ValueError("Unknown 1000 Genomes placement state")
    if status == "placed":
        if (
            not isinstance(population, str)
            or not population.strip()
            or region not in CODES
            or reason
        ):
            raise ValueError("Placed sample requires panel population and super-population")
    elif (
        not isinstance(reason, str)
        or not reason.strip()
        or population is not None
        or region is not None
    ):
        raise ValueError("Unplaced sample requires a reason and no population")
    _check_fits(placement, require_fits=require_fits)
    gate_status = "not_supplied" if gate is None else gate.get("status")
    raw_gate_reason = None if gate is None else gate.get("reason")
    if raw_gate_reason is not None and not isinstance(raw_gate_reason, str):
        raise ValueError("AADR gate reason must be text")
    gate_reason = raw_gate_reason or None
    if gate_status not in {"not_supplied", "placed", "declined", "not_run"}:
        raise ValueError("Unknown AADR decline gate")
    if gate_status == "placed" and gate_reason is not None:
        raise ValueError("A placed AADR gate cannot carry a refusal reason")
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


def _number(value: Any, *, finite: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Placement fit requires a numeric value")
    try:
        numeric = float(value)
    except OverflowError:
        raise ValueError("Invalid placement fit value") from None
    if math.isnan(numeric) or numeric < 0 or (finite and not math.isfinite(numeric)):
        raise ValueError("Invalid placement fit value")
    return numeric


def _check_fits(placement: Mapping[str, Any], *, require_fits: bool) -> None:
    """Bind the reported call to the producer's first admissible retained fit.

    Compact runtime callers may omit fits; new saved run contexts must retain them.
    A zero-radius population has infinite fit in the producer and cannot be selected.
    """
    fits = placement.get("fits")
    threshold = placement.get("decline_threshold")
    if placement["status"] == "not_run":
        if fits is not None or threshold is not None:
            raise ValueError("Not-run placement cannot carry measured fits")
        return
    if fits is None and threshold is None and not require_fits:
        return
    limit = _number(threshold)
    if limit <= 0 or not isinstance(fits, list) or not fits:
        raise ValueError("Measured placement requires retained fits and a positive threshold")
    chosen = None
    populations: set[str] = set()
    previous_distance = -1.0
    for fit in fits:
        if not isinstance(fit, Mapping):
            raise ValueError("Malformed retained population fit")
        population, region = fit.get("population"), fit.get("region")
        if (
            not isinstance(population, str)
            or not population.strip()
            or population in populations
            or not isinstance(region, str)
            or not region.strip()
        ):
            raise ValueError("Invalid retained population label")
        populations.add(population)
        value = _number(fit.get("fit"), finite=False)
        if "distance" in fit or "radius" in fit:
            distance, radius = _number(fit.get("distance")), _number(fit.get("radius"))
            expected = distance / radius if radius else math.inf
            if distance < previous_distance or not math.isclose(value, expected, rel_tol=1e-12):
                raise ValueError("Retained distance, radius and fit disagree")
            previous_distance = distance
        if chosen is None and value <= limit:
            chosen = fit
    if placement["status"] == "declined":
        if chosen is not None:
            raise ValueError("Declined placement has an admissible population")
    elif (
        chosen is None
        or chosen["population"] != placement["population"]
        or chosen["region"] != placement["region"]
    ):
        raise ValueError("Reported population/region disagrees with the first admissible fit")


def _same(actual: Any, expected: Any) -> bool:
    """Numeric spelling may vary in JSON; booleans cannot stand in for numbers."""
    if isinstance(expected, Mapping):
        return (
            isinstance(actual, Mapping)
            and set(actual) == set(expected)
            and all(_same(actual[k], v) for k, v in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_same(a, e) for a, e in zip(actual, expected, strict=True))
        )
    if isinstance(expected, int | float) and not isinstance(expected, bool):
        return (
            isinstance(actual, int | float)
            and not isinstance(actual, bool)
            and actual == expected
            and math.isfinite(float(actual))
        )
    return type(actual) is type(expected) and actual == expected


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
        if isinstance(numeric, bool) or not _same(actual, expected):
            raise ValueError
        if any(expected["text"] not in card[key] for key in ("summary", "detail")):
            raise ValueError
        multi = card.get("multi_marker")
        records = multi["markers"] if isinstance(multi, Mapping) else [card]
        for record in records:
            if multi is not None and not _same(record.get("ancestry_comparison"), expected):
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
            variant = CardVariant.parse(record["variant"], "saved variant")
            declared = set(variant.key.alleles)
            if any(f.allele not in declared for f in frequencies):
                raise ValueError
            genotype, observed_pair = match["genotype"], match["observed_genotype"]
            for pair in (genotype, observed_pair):
                if pair is not None and (
                    not isinstance(pair, str)
                    or len(pair) != 2
                    or pair != "".join(sorted(pair))
                    or not set(pair) <= set("ACGT")
                ):
                    raise ValueError
            if observed_pair is None:
                raise ValueError
            strand = match["strand"]
            if strand == "ambiguous":
                if (
                    genotype is not None
                    or not set(observed_pair) <= declared
                    or not set(complement(observed_pair)) <= declared
                ):
                    raise ValueError
            elif (
                strand not in {"as_written", "complemented"}
                or genotype is None
                or not set(genotype) <= declared
                or genotype
                != (complement(observed_pair) if strand == "complemented" else observed_pair)
            ):
                raise ValueError
            called = set(genotype or observed_pair)
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
            if not _same(record["confidence"], confidence_payload(result)):
                raise ValueError
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ValueError("Invalid or inconsistent saved card ancestry comparison") from None
