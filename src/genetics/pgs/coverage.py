"""Private M9.3 per-score variant coverage, before and after imputation.

Coverage is derived from saved term evidence, never from PLINK's matrix counts or the
biological ``native_alleles`` total. Every authored weighted row stays in the source
denominator, including rows no model can use. A phase that was not recorded or was
explicitly disabled is unavailable (null), never 0%. Quality is described alongside the
observations it qualifies; it filters nothing and scales nothing (its use is M9.5's).
"""

from __future__ import annotations

import bisect
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NoReturn

from genetics.engine.matcher import is_strand_ambiguous, strand_canonical
from genetics.imputation.dosages import parse_record
from genetics.imputation.target import ImputationError
from genetics.ingest.schema import CALL_STATUS_ORDER
from genetics.pgs.catalog import PgsError
from genetics.pgs.engine import (
    SCORE_SCHEMA_VERSION,
    UNSUPPORTED_FEATURES,
    allele_pair,
    ineligibility_reason,
)
from genetics.pgs.scoring import ScoreVariant, ScoringFile

COVERAGE_SCHEMA_VERSION = 1
METHOD = "M9.3 term-evidence coverage; denominator is every authored weighted row"
# Model-ineligible rows carry proof only when evidence existed at their locus.
INELIGIBLE = frozenset(
    {
        "unsupported_model",
        "unsupported_chromosome",
        "unresolved_locus",
        "allele_contract_missing",
        "harmonization_mismatch",
    }
)
# States the engine reaches only after finding at least one record at the locus.
EVIDENCED = frozenset(
    {
        "observed",
        "no_call",
        "duplicate_conflict",
        "allele_mismatch",
        "indel_excluded",
        "ploidy_unresolved",
        "ploidy_conflict",
        "strand_ambiguous",
        "ambiguous_panel_records",
    }
)
ABSENT = frozenset({"marker_absent", "no_imputed_observation"})
UNAVAILABLE = {"before": "not_recorded", "after": "disabled"}
KNOWN = INELIGIBLE | EVIDENCED | ABSENT | frozenset(UNAVAILABLE.values())
SCORED = frozenset({"scored", "scored_partial"})
PHASE_RESULTS = SCORED | {"no_usable_observations", "unsupported_model"}
SOURCES = frozenset({"direct", "imputed_untyped", "imputed_no_call"})
DR2_BOUNDARIES = tuple(k / 10 for k in range(1, 10))
CORRUPT = "Saved score evidence is malformed or inconsistent; coverage refused."


def _fail() -> NoReturn:
    raise PgsError(CORRUPT)


def _number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def _fraction(numerator: int | float, denominator: int | float) -> float | None:
    return None if not denominator else numerator / denominator


def _variant(term: Any) -> ScoreVariant:
    """Rebuild the authored source row a term was scored from, rejecting corruption."""
    if not isinstance(term, Mapping):
        _fail()
    row, chrom, position = term.get("row_number"), term.get("chrom"), term.get("position")
    effect, weight = term.get("effect_allele"), term.get("weight")
    fields, features = term.get("fields"), term.get("features")
    if (
        type(row) is not int
        or not (chrom is None or isinstance(chrom, str))
        or not (position is None or (type(position) is int and position > 0))
        or (chrom is None) != (position is None)
        or not isinstance(effect, str)
        or not (weight is None or _number(weight))
        or not isinstance(fields, Mapping)
        or any(not isinstance(k, str) or not isinstance(v, str) for k, v in fields.items())
        or not isinstance(features, list | tuple)
        or any(not isinstance(f, str) for f in features)
    ):
        _fail()
    return ScoreVariant(
        row,
        chrom,
        position,
        effect,
        None if weight is None else float(weight),
        dict(fields),
        tuple(features),
    )


def _proof(dose: Mapping[str, Any], locus: tuple[str, int] | None, phase: str) -> str | None:
    """Validate retained evidence and return its kind; locus must match the term."""
    proof = dose.get("native_record")
    if proof is None:
        return None
    if not isinstance(proof, Mapping) or locus is None:
        _fail()
    kind = proof.get("kind")
    if kind == "original_array":
        probes = proof.get("probes")
        if set(proof) != {"kind", "probes"} or not isinstance(probes, list | tuple) or not probes:
            _fail()
        for probe in probes:
            if (
                not isinstance(probe, Mapping)
                or set(probe)
                != {"rsid", "chrom", "pos_grch37", "a1", "a2", "genotype", "call_status"}
                or (str(probe["chrom"]), probe["pos_grch37"]) != locus
                or probe["call_status"] not in CALL_STATUS_ORDER
                or not (probe["genotype"] is None or isinstance(probe["genotype"], str))
            ):
                _fail()
        return "original_array"
    if phase == "before":
        _fail()
    records = (
        proof.get("records")
        if kind == "ambiguous_panel_records" and set(proof) == {"kind", "records"}
        else [proof]
        if kind is None
        else _fail()
    )
    if not isinstance(records, list | tuple) or (kind is not None and len(records) < 2):
        _fail()
    for raw in records:
        try:
            record = parse_record(raw)
        except ImputationError:
            _fail()
        if (record.chrom, record.pos_grch37) != locus:
            _fail()
    return "panel"


def _presence(
    dose: Mapping[str, Any], locus: tuple[str, int] | None, phase: str, schema: int
) -> tuple[str, str | None]:
    """Whether any record existed at the locus: present, absent or (legacy) unknown."""
    status, kind = dose["status"], _proof(dose, locus, phase)
    if status in EVIDENCED:
        if kind is None and schema >= 2:
            _fail()
        return "present", kind
    if status in ABSENT:
        if kind is not None:
            _fail()
        return "absent", None
    if kind is not None:
        return "present", kind
    # Schema 1 could drop the proof of excluded rows; missing proof is not absence.
    return ("absent" if schema >= 2 else "unknown"), None


def _observation(dose: Mapping[str, Any]) -> dict[str, Any]:
    value: Any = dose.get("value")
    ploidy: Any = dose.get("ploidy")
    dr2: Any = dose.get("dr2")
    source, scope, method = (
        dose.get("source"),
        dose.get("quality_scope"),
        dose.get("dosage_method"),
    )
    if (
        source not in SOURCES
        or type(ploidy) is not int
        or ploidy not in {1, 2}
        or not _number(value)
        or not 0 <= value <= ploidy
        or not (dr2 is None or (_number(dr2) and 0 <= dr2 <= 1))
        or not isinstance(scope, str)
        or not isinstance(method, str)
    ):
        _fail()
    quality = (
        "estimated"
        if dr2 is not None
        else f"not_estimated:{method}"
        if scope == "not_estimated"
        else "allele_quality_unknown"  # e.g. multiallelic REF without ALT covariance
    )
    return {"source": source, "ploidy": ploidy, "dr2": dr2, "method": method, "quality": quality}


def _combine(values: Sequence[str]) -> str:
    return "present" if "present" in values else "unknown" if "unknown" in values else "absent"


def _duplicates(probes: Sequence[Mapping[str, Any]], pairs: set[tuple[str, str]]) -> str:
    called = [str(p["genotype"]) for p in probes if p["call_status"] != "no_call" and p["genotype"]]
    if len(called) < 2:
        return "insufficient_calls"
    if len(set(called)) == 1:
        return "identical"
    if not pairs:
        return "unclassified"  # no authored allele pair says whether a complement applies
    if any(is_strand_ambiguous(pair) for pair in pairs):
        return "conflicting"  # palindromic calls cannot be reconciled by strand
    canonical = {strand_canonical(genotype) for genotype in called}
    return "complement_concordant" if len(canonical) == 1 else "conflicting"


def _source(
    variants: Sequence[ScoreVariant],
    reasons: Sequence[str | None],
    identities: Sequence[tuple[str, int, tuple[str, str]] | None],
    loci: Sequence[tuple[str, int] | None],
) -> dict[str, Any]:
    rows_per_variant = Counter(i for i in identities if i is not None)
    effects: defaultdict[tuple[str, int, tuple[str, str]], set[str]] = defaultdict(set)
    for identity, variant in zip(identities, variants, strict=True):
        if identity is not None:
            effects[identity].add(variant.effect_allele)
    rows_per_position = Counter(locus for locus in loci if locus is not None)
    variants_per_position = Counter((i[0], i[1]) for i in rows_per_variant)
    undefined = [
        {
            "row_number": v.row_number,
            "missing": "locus"
            if locus is None and allele_pair(v) is not None
            else "alleles"
            if locus is not None
            else "locus_and_alleles",
            "ineligibility": reason,
            "definition": dict(v.fields),  # public authored definition, kept raw
        }
        for v, reason, identity, locus in zip(variants, reasons, identities, loci, strict=True)
        if identity is None
    ]
    weights = [abs(v.effect_weight) for v in variants if v.effect_weight is not None]
    return {
        "rows": len(variants),
        "model_eligible_rows": sum(r is None for r in reasons),
        "model_ineligible_rows": dict(sorted(Counter(r for r in reasons if r).items())),
        "unsupported_model": any(UNSUPPORTED_FEATURES.intersection(v.features) for v in variants),
        "scalar_weight_rows": len(weights),
        "absolute_weight_total": math.fsum(weights),
        "variants": len(rows_per_variant),
        "repeated_variants": sum(n > 1 for n in rows_per_variant.values()),
        "rows_in_repeated_variants": sum(n for n in rows_per_variant.values() if n > 1),
        "variants_with_multiple_effect_alleles": sum(len(e) > 1 for e in effects.values()),
        "positions": len(rows_per_position),
        "positions_with_multiple_rows": sum(n > 1 for n in rows_per_position.values()),
        "positions_with_multiple_variants": sum(n > 1 for n in variants_per_position.values()),
        "rows_without_variant_identity": len(undefined),
        "undefined_rows": undefined,
    }


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "score_status": reason,
        "rows": None,
        "row_fraction": None,
        "observed_row_fraction": None,
        "variants": None,
        "positions": None,
        "weight": None,
        "observations": None,
    }


def compute_coverage(
    record: Mapping[str, Any],
    *,
    schema_version: int,
    source_rows: Sequence[ScoreVariant] | None = None,
) -> dict[str, Any]:
    """Derive versioned coverage from a score record's terms and phase states.

    ``source_rows`` (from ``ScoringFile.iter_variants()``) binds the denominator to the
    public source; without it the authored rows are rebuilt from the saved terms.
    Schema-1 artifacts can lack excluded-row proof: their presence stays unknown.
    """
    if type(schema_version) is not int or schema_version not in {1, SCORE_SCHEMA_VERSION}:
        raise PgsError("Unsupported score artifact schema; coverage refused.")
    terms = record.get("terms")
    if not isinstance(terms, list | tuple) or not terms:
        _fail()
    variants = [_variant(t) for t in terms]
    count = len(variants)
    definition = record.get("score_definition")
    if (
        [v.row_number for v in variants] != list(range(1, count + 1))
        or not isinstance(definition, Mapping)
        or definition.get("rows") != count
    ):
        _fail()
    if source_rows is not None and list(source_rows) != variants:
        raise PgsError("Score terms disagree with their scoring source; coverage refused.")
    reasons = [ineligibility_reason(v) for v in variants]
    pairs = [allele_pair(v) for v in variants]
    loci = [
        None if v.chrom is None or v.position is None else (v.chrom, v.position) for v in variants
    ]
    identities = [
        None if locus is None or pair is None else (*locus, (min(pair), max(pair)))
        for locus, pair in zip(loci, pairs, strict=True)
    ]
    for term, pair in zip(terms, pairs, strict=True):
        if term.get("other_allele") != (None if pair is None else pair[1]):
            _fail()
    unsupported = any(UNSUPPORTED_FEATURES.intersection(v.features) for v in variants)

    table = record.get("original_table_sha256")
    mode = record.get("imputation_mode")
    stream = record.get("dosage_stream_sha256")
    if not (table is None or (isinstance(table, str) and len(table) == 64)) or mode not in {
        "enabled",
        "disabled",
    }:
        _fail()
    available = {"before": table is not None, "after": mode == "enabled"}
    if not any(available.values()) or (
        schema_version >= 2 and available["after"] != isinstance(stream, str)
    ):
        _fail()

    results: dict[str, Mapping[str, Any]] = {}
    for phase in ("before", "after"):
        result = record.get(phase)
        if not isinstance(result, Mapping) or not isinstance(result.get("status"), str):
            _fail()
        results[phase] = result
        doses = [t.get(phase) for t in terms]
        if any(not isinstance(d, Mapping) or d.get("status") not in KNOWN for d in doses):
            _fail()
        statuses = {d["status"] for d in doses}
        marker = UNAVAILABLE[phase]
        if available[phase]:
            if marker in statuses or result["status"] not in PHASE_RESULTS:
                _fail()
            if (result["status"] == "unsupported_model") != unsupported:
                _fail()
        elif schema_version >= 2 and (statuses != {marker} or result["status"] != marker):
            _fail()  # schema 1 could overwrite an unavailable phase's states

    sums = [results[p].get("sum") for p in ("before", "after") if available[p]]
    expected = (
        "unsupported_model"
        if unsupported
        else "computed"
        if any(s is not None for s in sums)
        else "no_usable_observations"
    )
    if record.get("status") != expected:
        _fail()

    presence: dict[str, list[tuple[str, str | None]]] = {}
    for phase in ("before", "after"):
        if available[phase]:
            presence[phase] = [
                _presence(t[phase], locus, phase, schema_version)
                for t, locus in zip(terms, loci, strict=True)
            ]

    # Original probes are a chip property: one envelope per locus, shared by its rows.
    probes_at: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    before_position: dict[tuple[str, int], str] = {}
    if available["before"]:
        by_locus: defaultdict[tuple[str, int], list[str]] = defaultdict(list)
        for term, locus, (state, kind) in zip(terms, loci, presence["before"], strict=True):
            if locus is None:
                continue
            by_locus[locus].append(state)
            if kind == "original_array":
                probes = list(term["before"]["native_record"]["probes"])
                if locus in probes_at and json.dumps(probes_at[locus], sort_keys=True) != (
                    json.dumps(probes, sort_keys=True)
                ):
                    _fail()
                probes_at[locus] = probes
        before_position = {locus: _combine(states) for locus, states in by_locus.items()}
        pairs_at: defaultdict[tuple[str, int], set[tuple[str, str]]] = defaultdict(set)
        for locus, pair in zip(loci, pairs, strict=True):
            if locus is not None and pair is not None:
                pairs_at[locus].add(pair)
        duplicates = Counter(
            _duplicates(probes, pairs_at[locus])
            for locus, probes in probes_at.items()
            if len(probes) > 1
        )
        states = Counter(before_position.values())
        original_probes: dict[str, Any] = {
            "status": "available",
            "reason": None,
            "positions_on_array": states["present"],
            "positions_absent": states["absent"],
            "positions_unknown": states["unknown"],
            "probes": sum(len(p) for p in probes_at.values()),
            "positions_called": sum(
                any(p["call_status"] != "no_call" and p["genotype"] for p in probes)
                for probes in probes_at.values()
            ),
            "positions_with_duplicate_probes": sum(duplicates.values()),
            "duplicate_positions": {
                key: duplicates[key]
                for key in (
                    "identical",
                    "complement_concordant",
                    "conflicting",
                    "insufficient_calls",
                    "unclassified",
                )
            },
        }
    else:
        original_probes = {"status": "unavailable", "reason": UNAVAILABLE["before"]}

    source = _source(variants, reasons, identities, loci)
    phases: dict[str, dict[str, Any]] = {}
    for phase in ("before", "after"):
        if not available[phase]:
            phases[phase] = _unavailable(UNAVAILABLE[phase])
            continue
        result = results[phase]
        doses = [t[phase] for t in terms]
        observed = [i for i, d in enumerate(doses) if d["status"] == "observed"]
        details = {i: _observation(doses[i]) for i in observed}
        scored = result.get("terms")
        if type(scored) is not int:
            _fail()
        status = result["status"]
        if (
            (status in SCORED and (scored != len(observed) or not observed))
            or (status == "scored") != (status in SCORED and len(observed) == count)
            or (status == "no_usable_observations" and (observed or scored))
            or (status == "unsupported_model" and scored)
            or (status in SCORED) != (result.get("sum") is not None)
        ):
            _fail()
        covered = Counter(identity for i in observed if (identity := identities[i]) is not None)
        rows_per_variant = Counter(i for i in identities if i is not None)
        usable_positions = {loci[i] for i in observed if loci[i] is not None}
        position_states: defaultdict[tuple[str, int], list[str]] = defaultdict(list)
        for locus, (state, _) in zip(loci, presence[phase], strict=True):
            if locus is not None:
                position_states[locus].append(state)
        if phase == "after" and available["before"]:
            # The post-imputation observation set still includes every original probe.
            for locus, state in before_position.items():
                position_states[locus].append(state)
        evidence = Counter(_combine(states) for states in position_states.values())
        positions = source["positions"]
        weights = [variants[i].effect_weight for i in observed]
        if any(w is None for w in weights):
            _fail()
        absolute = [abs(w) for w in weights if w is not None]
        binned: list[list[float]] = [[] for _ in range(len(DR2_BOUNDARIES) + 1)]
        unknown_weight: list[float] = []
        for i, weight_value in zip(observed, absolute, strict=True):
            dr2 = details[i]["dr2"]
            if dr2 is None:
                unknown_weight.append(weight_value)
            else:
                binned[bisect.bisect_right(DR2_BOUNDARIES, dr2)].append(weight_value)
        estimated = [details[i]["dr2"] for i in observed if details[i]["dr2"] is not None]
        has_score = status in SCORED
        phases[phase] = {
            "status": "unsupported_model"
            if status == "unsupported_model"
            else "no_usable_observations"
            if status == "no_usable_observations"
            else "complete"
            if status == "scored"
            else "partial",
            "reason": None,
            "score_status": status,
            "rows": {
                "total": count,
                "scored": scored,
                "observed": len(observed),
                "not_scored": count - scored,
                "by_state": dict(sorted(Counter(d["status"] for d in doses).items())),
            },
            "row_fraction": _fraction(scored, count) if status != "unsupported_model" else None,
            "observed_row_fraction": _fraction(len(observed), count),
            "variants": {
                "total": source["variants"],
                "with_usable_dose": len(covered),
                "partially_observed": sum(n < rows_per_variant[i] for i, n in covered.items()),
                "fraction": _fraction(len(covered), source["variants"]),
            },
            "positions": {
                "total": positions,
                "with_usable_dose": len(usable_positions),
                "usable_fraction": _fraction(len(usable_positions), positions),
                "evidence_present": evidence["present"],
                "evidence_absent": evidence["absent"],
                "evidence_unknown": evidence["unknown"],
                "evidence_fraction": None
                if evidence["unknown"]
                else _fraction(evidence["present"], positions),
                "evidence_fraction_bounds": None
                if not positions
                else [
                    evidence["present"] / positions,
                    (evidence["present"] + evidence["unknown"]) / positions,
                ],
            },
            "weight": {
                "absolute_total": source["absolute_weight_total"],
                "absolute_scored": math.fsum(absolute) if has_score else 0.0,
                "fraction": _fraction(math.fsum(absolute), source["absolute_weight_total"])
                if has_score
                else None,
            },
            "observations": {
                "sources": dict(sorted(Counter(d["source"] for d in details.values()).items())),
                "ploidy": dict(sorted(Counter(str(d["ploidy"]) for d in details.values()).items())),
                "methods": dict(sorted(Counter(d["method"] for d in details.values()).items())),
                "quality": {
                    "estimated": len(estimated),
                    "unknown": dict(
                        sorted(
                            Counter(
                                d["quality"]
                                for d in details.values()
                                if d["quality"] != "estimated"
                            ).items()
                        )
                    ),
                    "dr2_min": min(estimated) if estimated else None,
                    "dr2_max": max(estimated) if estimated else None,
                    # Descriptive tenths; the last bin includes 1.0. Not a threshold.
                    "dr2_bins": [
                        {
                            "lower": k / 10,
                            "upper": (k + 1) / 10,
                            "rows": len(values),
                            "absolute_weight": math.fsum(values),
                        }
                        for k, values in enumerate(binned)
                    ],
                    "absolute_weight_unknown_quality": math.fsum(unknown_weight),
                },
            },
        }
    return {
        "schema_version": COVERAGE_SCHEMA_VERSION,
        "score_schema_version": schema_version,
        "method": METHOD,
        "evidence_proof": "retained"
        if schema_version >= 2
        else "legacy_excluded_row_proof_may_be_missing",
        "source": source,
        "original_probes": original_probes,
        "before": phases["before"],
        "after": phases["after"],
    }


def read_coverage(path: Path, *, scoring: ScoringFile | None = None) -> dict[str, Any]:
    """Reload a private score result and return its validated coverage.

    Schema 2 coverage must equal a recomputation from its own term evidence. Schema 1
    artifacts predate coverage and are recomputed, with lost proof left unknown.
    A supplied scoring file must be the source the result was computed from.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PgsError("Could not read the private score result.") from exc
    if not isinstance(raw, dict) or raw.get("kind") != "pgs_score":
        _fail()
    schema = raw.get("schema_version")
    if type(schema) is not int or schema not in {1, SCORE_SCHEMA_VERSION}:
        raise PgsError("Unsupported score artifact schema; coverage refused.")
    rows = None
    if scoring is not None:
        definition = raw.get("score_definition")
        recorded = definition.get("scoring_source") if isinstance(definition, Mapping) else None
        if (
            raw.get("pgs_id") != scoring.headers["pgs_id"]
            or not isinstance(recorded, Mapping)
            or (recorded.get("sha256"), recorded.get("size_bytes"))
            != (scoring.source["sha256"], scoring.source["size_bytes"])
        ):
            raise PgsError("The saved score was not computed from the supplied scoring file.")
        rows = list(scoring.iter_variants())
    computed = json.loads(
        json.dumps(compute_coverage(raw, schema_version=schema, source_rows=rows), allow_nan=False)
    )
    if schema >= 2:
        if raw.get("coverage") != computed:
            raise PgsError("Saved coverage disagrees with its term evidence; refused.")
        origin = "persisted_verified"
    else:
        if "coverage" in raw:
            _fail()
        origin = "recomputed_legacy"
    return {
        "pgs_id": raw.get("pgs_id"),
        "score_status": raw.get("status"),
        "artifact_schema_version": schema,
        "coverage_origin": origin,
        "scoring_source_verified": scoring is not None,
        "coverage": computed,
    }


def summary(coverage: Mapping[str, Any]) -> list[str]:
    """Plain-text phase lines for local terminal output; no marker identities."""
    lines = []
    for phase, label in (("before", "Original array"), ("after", "After imputation")):
        data = coverage[phase]
        if data["status"] == "unavailable":
            lines.append(f"{label}: coverage unavailable ({data['reason']}), not 0%.")
            continue
        rows, variants = data["rows"], data["variants"]
        fraction = data["row_fraction"]
        lines.append(
            f"{label}: {data['status']}; {rows['scored']}/{rows['total']} weighted rows scored"
            + ("" if fraction is None else f" ({fraction:.1%})")
            + f", {variants['with_usable_dose']}/{variants['total']} variants and "
            f"{data['positions']['with_usable_dose']}/{data['positions']['total']} positions "
            "with a usable dose."
        )
    return lines
