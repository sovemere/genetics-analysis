"""Validation of saved small-SNP diplotypes, using only the recorded definitions.

No current knowledge pack, frequency database, phasing prior, or new confidence formula
may reinterpret a saved run. Genotype-bearing validation failures never echo values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from genetics.engine.cards import CardVariant, Match
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import ObservationEvidence, PopulationFrequency
from genetics.engine.matcher import MatchStatus, Strand, complement
from genetics.ingest.schema import CallStatus


def _map(value: Any, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError("invalid multi-marker record fields")
    return value


def validate_snapshot(card: Mapping[str, Any]) -> None:
    """Convert all malformed nested values to a genotype-free domain failure."""
    try:
        _validate_snapshot(card)
    except (ValueError, TypeError, KeyError, IndexError):
        raise ValueError("invalid or inconsistent saved multi-marker evidence") from None


def _validate_snapshot(card: Mapping[str, Any]) -> None:
    multi = _map(
        card.get("multi_marker"),
        {"schema_version", "phase", "haplotypes", "diplotypes", "markers", "candidate_diplotypes"},
    )
    if type(multi["schema_version"]) is not int or multi["schema_version"] != 1:
        raise ValueError("unsupported multi-marker schema")
    if multi["phase"] != "unphased" or card.get("kind") != "interpretation":
        raise ValueError("invalid multi-marker phase or kind")
    if any(card.get(k) is not None for k in ("variant", "computation", "observation")):
        raise ValueError("multi-marker result cannot carry a scalar variant or computation")
    markers = multi["markers"]
    if not isinstance(markers, list) or not 2 <= len(markers) <= 4:
        raise ValueError("multi-marker result requires two to four observations")
    variants = []
    statuses = []
    genotypes = []
    confidences = []
    marker_keys = {
        "variant",
        "status",
        "match",
        "observation",
        "frequencies",
        "confidence_frequency",
        "confidence",
        "computed_caveats",
    }
    for marker in markers:
        record = _map(marker, marker_keys)
        variant = _map(record["variant"], {"rsid", "chrom", "pos_grch37", "alleles"})
        CardVariant.parse(variant, "saved marker")
        variants.append(dict(variant))
        match = _map(
            record["match"],
            {
                "reason",
                "genotype",
                "observed_genotype",
                "observed_rsid",
                "call_status",
                "strand",
                "outcome_name",
                "candidate_outcomes",
            },
        )
        if not isinstance(match["reason"], str) or not match["reason"].strip():
            raise ValueError("marker match requires a reason")
        if match["outcome_name"] is not None or match["candidate_outcomes"] != []:
            raise ValueError("constituent markers cannot carry diplotype interpretations")
        status = MatchStatus(record["status"])
        if status not in {
            MatchStatus.MATCHED,
            MatchStatus.MARKER_ABSENT,
            MatchStatus.NO_CALL,
            MatchStatus.ALLELE_MISMATCH,
            MatchStatus.INDEL_EXCLUDED,
            MatchStatus.HET_HAPLOID,
            MatchStatus.DUPLICATE_CONFLICT,
            MatchStatus.INSUFFICIENT_CALLS,
        }:
            raise ValueError("invalid constituent marker status")
        statuses.append(status)
        strand = Strand(match["strand"])
        call_status = match["call_status"]
        if call_status is not None:
            CallStatus(call_status)
        genotype = match["genotype"]
        observed = match["observed_genotype"]
        for value in (genotype, observed):
            if value is not None and (
                not isinstance(value, str)
                or len(value) != 2
                or value != "".join(sorted(value))
                or any(a not in "ACGTID" for a in value)
            ):
                raise ValueError("invalid marker allele pair")
        if status is MatchStatus.MATCHED:
            if genotype is None or not set(genotype) <= set(variant["alleles"]):
                raise ValueError("resolved marker has no valid oriented observation")
            if strand not in {Strand.AS_WRITTEN, Strand.COMPLEMENTED} or observed is None:
                raise ValueError("resolved marker has no unambiguous strand")
            oriented = observed if strand is Strand.AS_WRITTEN else complement(observed)
            if oriented != genotype or call_status != CallStatus.CALLED.value:
                raise ValueError("marker orientation or ploidy is inconsistent")
        elif genotype is not None:
            raise ValueError("unresolved marker cannot carry an oriented observation")
        genotypes.append(genotype)
        observation = _map(
            record["observation"], {"call_source", "imputation_quality", "ancestry_match"}
        )
        frequencies = record["frequencies"]
        if not isinstance(frequencies, list):
            raise ValueError("marker frequencies must be a list")
        frequency_items = []
        for raw in frequencies:
            item = _map(raw, {"allele", "frequency", "population", "source"})
            if any(not isinstance(item[k], str) for k in ("allele", "population", "source")):
                raise ValueError("invalid marker frequency metadata")
            frequency_items.append(PopulationFrequency(**item))
        ObservationEvidence(
            call_source=CallSource(observation["call_source"]),
            frequencies=tuple(frequency_items),
            imputation_quality=observation["imputation_quality"],
            ancestry_match=observation["ancestry_match"],
        )
        selected = record["confidence_frequency"]
        if selected is not None and (
            selected not in frequencies or genotype is None or selected["allele"] not in genotype
        ):
            raise ValueError("marker confidence frequency is not an observed allele")
        confidence = record["confidence"]
        if (confidence is not None) != (status is MatchStatus.MATCHED):
            raise ValueError("marker confidence contradicts its match status")
        if confidence is not None:
            if not isinstance(confidence, Mapping):
                raise ValueError("invalid marker confidence")
            tier = confidence.get("tier")
            if not isinstance(tier, str):
                raise ValueError("invalid marker reliability tier")
            ConfidenceTier(tier)
            score = confidence.get("score")
            if isinstance(score, bool) or not isinstance(score, int | float) or not 0 <= score <= 1:
                raise ValueError("invalid marker confidence score")
            inputs = confidence.get("inputs")
            if not isinstance(inputs, Mapping) or inputs.get("population_allele_frequency") != (
                selected["frequency"] if selected is not None else None
            ):
                raise ValueError("marker calibration and selected frequency disagree")
            confidences.append(confidence)
        if not isinstance(record["computed_caveats"], list) or any(
            not isinstance(c, str) for c in record["computed_caveats"]
        ):
            raise ValueError("invalid marker caveats")
    definition = Match.parse(
        {
            "variants": variants,
            "haplotypes": multi["haplotypes"],
            "diplotypes": multi["diplotypes"],
        },
        "saved multi-marker definition",
    )
    candidates = (
        definition.compatible_pairs(genotypes)
        if all(s is MatchStatus.MATCHED for s in statuses)
        else ()
    )
    if multi["candidate_diplotypes"] != list(candidates):
        raise ValueError("saved phase candidates disagree with marker observations")
    aggregate_match = card.get("match")
    if (
        not isinstance(aggregate_match, Mapping)
        or any(
            aggregate_match.get(k) is not None
            for k in ("genotype", "observed_genotype", "observed_rsid", "call_status")
        )
        or aggregate_match.get("strand") != "not_applicable"
    ):
        raise ValueError("multi-marker result cannot carry a scalar observation")
    if card.get("frequencies") or card.get("confidence_frequency") is not None:
        raise ValueError("multi-marker frequencies must be locus-specific")
    if len(candidates) == 1:
        if (
            card.get("status") != "matched"
            or aggregate_match.get("outcome_name") != definition.diplotypes[candidates[0]]
            or aggregate_match.get("candidate_outcomes") != []
        ):
            raise ValueError("saved diplotype interpretation disagrees with observations")
        weakest = max(confidences, key=lambda c: (ConfidenceTier(c["tier"]).rank, -c["score"]))
        if card.get("confidence") != weakest:
            raise ValueError("diplotype calibration must inherit its weakest marker")
    else:
        expected = (
            "phase_ambiguous"
            if len(candidates) > 1
            else next(
                (s.value for s in statuses if s is not MatchStatus.MATCHED), "allele_mismatch"
            )
        )
        if (
            card.get("status") != expected
            or card.get("confidence") is not None
            or aggregate_match.get("outcome_name") is not None
        ):
            raise ValueError("unresolved diplotype cannot carry an interpretation or confidence")
        outcomes = sorted({definition.diplotypes[p] for p in candidates})
        if aggregate_match.get("candidate_outcomes") != outcomes:
            raise ValueError("saved candidate interpretations disagree with phase candidates")
