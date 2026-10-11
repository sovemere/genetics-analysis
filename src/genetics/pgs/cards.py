"""M9.6 polygenic score cards: a score result rendered as a finding, never as a point.

A polygenic card is authored like any other -- what the score measures, its evidence and
citations, and optionally absolute outcome rates by score decile -- and evaluated from one
private M9.2-M9.5 score result. This module turns that result into the card's face.

**No point estimate about the person** (AGENTS.md 4.5). The display derivation does not
copy the person's sum or point percentile at all: it carries the reference distribution
(histogram and quantiles of the comparison group) and the person's *interval* within it,
with the deciles that interval overlaps. A renderer cannot show what it is not handed. The
95% interval is M9.4's Wilson interval and reflects only the size of the reference group;
the face says so, and states coverage and portability beside it rather than folding them
into a wider-looking interval with no stated basis.

**The face is computed, not templated.** The statements 4.5 and 0.1B require on the face --
reference group and whether it is ancestry-matched, coverage, portability (M9.5),
within-family attenuation where known, absolute rates by decile where available, and the
base rate beside them -- are written here, so no card can omit one.

**Re-derivable on reload.** The bundle stores the full private score record in
``pgs.run.json`` and the card's display, reliability and face text; reading a run
recomputes all three from the record and the card's own stored evidence and refuses any
difference (:func:`validate_stored`), as M9.3-M9.5 do for their blocks.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, Final

from genetics.engine.cards import (
    Ancestry,
    Card,
    CardKind,
    Effect,
    EffectMeasure,
    Evidence,
    EvidenceTier,
    Replication,
)
from genetics.engine.confidence import (
    PolygenicConfidence,
    calculate_polygenic_confidence,
)
from genetics.engine.evidence import AssembledCard, EvidenceAssemblyError
from genetics.engine.matcher import MatchResult, MatchStatus
from genetics.pgs.catalog import PgsError

SOURCE: Final = "polygenic_score"
DISPLAY_SCHEMA_VERSION: Final = 2
PHASES: Final = ("after", "before")
"""Post-imputation first: it is the default scoring mode and covers more of the score."""

INTERVAL_BASIS: Final = (
    "The interval reflects only the size of the reference group. It does not include "
    "coverage, imputation quality or ancestry portability, which are stated separately."
)
NOT_A_RISK: Final = (
    "A position in a reference distribution is not a risk: no absolute outcome rates by "
    "score decile are recorded for this score."
)


def record_digest(record: Mapping[str, Any]) -> str:
    """Canonical digest of a private score record, binding a card to the exact result."""
    text = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _quantile(ordered: Sequence[float], q: float) -> float:
    """Type-7 interpolation, as M9.4's group quantiles use."""
    h = (len(ordered) - 1) * q
    low = math.floor(h)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (h - low) * (ordered[high] - ordered[low])


def _decile(percentile: float) -> int:
    return min(10, max(1, math.floor(percentile / 10) + 1))


def _phase(record: Mapping[str, Any]) -> str | None:
    block = record.get("reference_distribution")
    if not isinstance(block, Mapping) or block.get("status") != "computed":
        return None
    return next(
        (
            p
            for p in PHASES
            if isinstance(block.get(p), Mapping) and block[p].get("percentile") is not None
        ),
        None,
    )


def unavailable_reason(record: Mapping[str, Any]) -> str:
    """Why a score result places nothing, in words a card can show."""
    block = record.get("reference_distribution")
    if record.get("status") == "unsupported_model":
        return "The score uses a model this engine cannot evaluate (interaction or special terms)."
    if not isinstance(block, Mapping):
        return "The score result has no reference distribution."
    if block.get("status") != "computed":
        return f"No reference distribution: {block.get('reason') or block.get('status')}."
    reasons = {
        p: block[p].get("reason") or block[p].get("status")
        for p in PHASES
        if isinstance(block.get(p), Mapping)
    }
    return (
        "No phase of the score could be placed in the reference "
        f"(after imputation: {reasons.get('after')}; original array: {reasons.get('before')})."
    )


def derive_position(
    record: Mapping[str, Any], *, display_schema_version: int = DISPLAY_SCHEMA_VERSION
) -> dict[str, Any] | None:
    """The person's place in the reference, as an interval over a distribution; or None.

    Pure function of the private record. No sum and no point percentile leave it.
    """
    phase = _phase(record)
    if phase is None:
        return None
    block = record["reference_distribution"]
    data = block[phase]
    group = block["group"]
    primary = data["primary_group"]
    stats = data["groups"][primary]
    labels = block["sample_labels"]
    if primary == "pooled":
        members = list(data["reference_sums"])
    else:
        key = "super_populations" if primary == "super_population" else "populations"
        members = [
            value
            for value, label in zip(data["reference_sums"], labels[key], strict=True)
            if label == stats["label"]
        ]
    ordered = sorted(members)
    low, high = data["percentile_interval_95"]
    terms = {t["row_number"]: t for t in record["terms"]}
    comparable = [terms[n] for n in data["comparable_rows"]]
    total = math.fsum(abs(t["weight"]) for t in comparable if t["weight"] is not None)
    if display_schema_version >= 2:
        # Match the denominator's accurate summation. Ordinary accumulation can
        # round all-direct or all-unknown weights above one at genome-wide scale.
        quality = math.fsum(
            abs(term["weight"] or 0.0)
            * (1.0 if term[phase]["source"] == "direct" else (term[phase]["dr2"] or 0.0))
            for term in comparable
        )
        unknown = math.fsum(
            abs(term["weight"] or 0.0)
            for term in comparable
            if term[phase]["source"] != "direct" and term[phase]["dr2"] is None
        )
    else:
        # Historical display-1 snapshots must reproduce their stored numbers.
        quality = unknown = 0.0
        for term in comparable:
            weight = abs(term["weight"] or 0.0)
            dose = term[phase]
            if dose["source"] == "direct":
                quality += weight
            elif dose["dr2"] is not None:
                quality += weight * dose["dr2"]
            else:
                unknown += weight
    coverage = record["coverage"][phase]
    display = {
        "schema_version": display_schema_version,
        "pgs_id": record["pgs_id"],
        "score_sha256": record_digest(record),
        "phase": phase,
        "imputation_mode": record["imputation_mode"],
        "licence": record["score_definition"]["metadata"]["license"],
        "reference": {
            "group": primary,
            "label": stats["label"],
            "n": stats["n"],
            "ancestry_matched": group["ancestry_matched"],
            "reason": group["reason"],
            "panel": block["panel"]["source"],
        },
        "position": {
            "percentile_interval_95": [low, high],
            "deciles": [_decile(low), _decile(high)],
            "score_interval": [_quantile(ordered, low / 100), _quantile(ordered, high / 100)],
            "basis": INTERVAL_BASIS,
        },
        "distribution": {
            "histogram": stats["histogram"],
            "quantiles": stats["quantiles"],
            "mean": stats["mean"],
            "sd": stats["sd"],
        },
        "coverage": {
            "rows_scored": coverage["rows"]["scored"],
            "rows_total": coverage["rows"]["total"],
            "score_weight_fraction": coverage["weight"]["fraction"],
            "comparable_rows": len(comparable),
            "comparable_weight_fraction": data["fraction_of_score_weight"],
            "excluded_for_reference": data["excluded_for_reference"],
        },
        "quality": {
            "weighted_quality": quality / total if total else 0.0,
            "unknown_quality_weight_fraction": unknown / total if total else 0.0,
            "imputed_weight_fraction": data["person_dose_basis"][
                "imputed_absolute_weight_fraction"
            ],
        },
        "portability": record["portability"],
    }
    if display_schema_version >= 2:
        display["phase_coverage"] = phase_coverage(record)
    return display


def phase_coverage(record: Mapping[str, Any]) -> dict[str, Any]:
    """Both phases' counts and denominators; no genotype proof or personal score."""
    summaries = {}
    for phase in ("before", "after"):
        coverage = record["coverage"][phase]
        rows, variants, weight = (coverage[k] for k in ("rows", "variants", "weight"))
        summaries[phase] = {
            "status": coverage["status"],
            "reason": coverage["reason"],
            "rows_scored": None if rows is None else rows["scored"],
            "rows_total": None if rows is None else rows["total"],
            "variants_covered": None if variants is None else variants["with_usable_dose"],
            "variants_total": None if variants is None else variants["total"],
            "variant_fraction": None if variants is None else variants["fraction"],
            "weight_fraction": None if weight is None else weight["fraction"],
        }
    return summaries


def phase_coverage_text(result: Mapping[str, Any] | None) -> str:
    """Shared face/detail wording, including unavailable phases without false zeros."""
    if result is None or "phase_coverage" not in result:
        return ""  # Historical display 1 is preserved exactly.
    parts = []
    for phase, label in (("before", "Original array"), ("after", "After imputation")):
        coverage = result["phase_coverage"][phase]
        if coverage["status"] in {"unavailable", "unsupported_model"}:
            parts.append(f"{label}: unavailable ({coverage['reason'] or coverage['status']}).")
            continue
        fraction = coverage["variant_fraction"]
        weight = coverage["weight_fraction"]
        parts.append(
            f"{label}: {coverage['variants_covered']:,}/{coverage['variants_total']:,} "
            f"variants ({'unknown' if fraction is None else _percent(fraction)}); "
            f"{coverage['rows_scored']:,}/{coverage['rows_total']:,} rows scored; "
            f"{'unknown' if weight is None else _percent(weight)} of absolute score weight."
        )
    return " ".join(parts)


def _deciles(card_deciles: Mapping[str, Any] | None, position: Mapping[str, Any] | None) -> Any:
    if card_deciles is None:
        return None
    out = dict(card_deciles)
    if position is not None:
        low, high = position["position"]["deciles"]
        out["overlapped"] = list(range(low, high + 1))
        rates = card_deciles["rates"][low - 1 : high]
        out["overlapped_range"] = [min(rates), max(rates)]
    return out


def _percent(value: float) -> str:
    return f"{100 * value:.0f}%" if value >= 0.01 or value == 0 else f"{100 * value:.2g}%"


def _ordinal(value: float) -> str:
    n = round(value)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def face_text(
    title: str,
    trait: str,
    result: Mapping[str, Any] | None,
    within_family_attenuation: float | None,
    reason: str | None,
) -> str:
    """The card face: every statement AGENTS.md 4.5 requires, and no point estimate."""
    if within_family_attenuation is None:
        within = (
            "No within-family estimate is recorded, so how much of the population "
            "association acts directly is unknown."
        )
    elif within_family_attenuation <= 1:
        within = (
            f"Within-family studies retain about {within_family_attenuation:.0%} of the "
            "population effect; the rest reflects ancestry, assortative mating and family "
            "environment rather than the genome acting directly."
        )
    else:
        # The schema admits up to 1.5: a sibling estimate can exceed the population one.
        within = (
            f"Within-family studies estimate about {within_family_attenuation:.0%} of the "
            "population effect, so the population association does not overstate the direct "
            "effect here."
        )
    if result is None or result.get("position") is None:
        summary = f"{title}: not placed. {reason or 'The score was not computed.'} {within}"
        comparison = phase_coverage_text(result)
        return summary + (f" {comparison}" if comparison else "")
    ref = result["reference"]
    low, high = result["position"]["percentile_interval_95"]
    d_low, d_high = result["position"]["deciles"]
    deciles = f"decile {d_low}" if d_low == d_high else f"deciles {d_low}-{d_high}"
    group = (
        f"the {ref['label']} reference ({ref['n']:,} samples)"
        if ref["ancestry_matched"]
        else f"the pooled reference ({ref['n']:,} samples), NOT ancestry-matched"
    )
    coverage = result["coverage"]["comparable_weight_fraction"]
    portability = result["portability"]
    match = portability["match"]
    port = (
        f"Ancestry portability: {portability['judgment'].replace('_', ' ')}"
        + (
            ""
            if match is None
            else f" ({_percent(match['matched'])} of the study population demonstrably "
            f"matches, at most {_percent(match['upper_bound'])})"
        )
        + "."
    )
    parts = [
        f"Among {group}, this {trait} score sits between the {_ordinal(low)} and "
        f"{_ordinal(high)} percentiles ({deciles}). {INTERVAL_BASIS}",
        f"{'Unknown' if coverage is None else _percent(coverage)} of the score's weight was "
        "comparable.",
        port,
        within,
    ]
    comparison = phase_coverage_text(result)
    if comparison:
        parts.append(comparison)
    rates = result["authored"]["decile_outcomes"]
    if rates is None:
        parts.append(NOT_A_RISK)
    else:
        lo_rate, hi_rate = rates["overlapped_range"]
        span = (
            _percent(lo_rate) if lo_rate == hi_rate else f"{_percent(lo_rate)}-{_percent(hi_rate)}"
        )
        parts.append(
            f"In {rates['population']}, {rates['measure']} was {span} across those deciles, "
            f"against {_percent(rates['base_rate'])} overall; these are that study's rates, "
            "not a prediction for you."
        )
    return " ".join(parts)


def reliability(evidence: Evidence, result: Mapping[str, Any] | None) -> dict[str, Any]:
    if result is None or result.get("position") is None:
        return {
            "tier": None,
            "score": None,
            "inputs": {},
            "ceilings": [],
            "reason": "No reference placement, so no reliability tier.",
        }
    confidence: PolygenicConfidence = calculate_polygenic_confidence(
        evidence,
        weight_coverage=result["coverage"]["comparable_weight_fraction"] or 0.0,
        weighted_quality=result["quality"]["weighted_quality"],
        unknown_quality_weight_fraction=result["quality"]["unknown_quality_weight_fraction"],
        ancestry_match=result["portability"]["ancestry_match"],
    )
    inputs = {
        k: (v.value if hasattr(v, "value") else v) for k, v in asdict(confidence.inputs).items()
    }
    return {
        "tier": confidence.tier.value,
        "score": confidence.score,
        "inputs": inputs,
        "ceilings": list(confidence.ceilings),
        "reason": "Computed from evidence, effect, replication, comparable score weight, "
        "weighted imputation quality and ancestry match"
        + (f"; capped by {', '.join(confidence.ceilings)}" if confidence.ceilings else "")
        + ".",
    }


def _authored(card: Card) -> dict[str, Any]:
    assert card.pgs is not None and card.trait is not None
    deciles = card.decile_outcomes
    return {
        "pgs_id": card.pgs.pgs_id,
        "scoring_source": card.pgs.source,
        "trait": card.trait,
        "decile_outcomes": None
        if deciles is None
        else {
            "measure": deciles.measure,
            "population": deciles.population,
            "sample_size": deciles.sample_size,
            "source": deciles.source,
            "base_rate": deciles.base_rate,
            "rates": list(deciles.rates),
            "context": deciles.context,
        },
    }


def build_result(
    authored: Mapping[str, Any],
    record: Mapping[str, Any] | None,
    *,
    display_schema_version: int = DISPLAY_SCHEMA_VERSION,
) -> Any:
    """The stored display: derived position plus the card's authored blocks."""
    if record is None:
        return None
    if type(display_schema_version) is not int or display_schema_version not in {1, 2}:
        raise PgsError("Unsupported polygenic display schema version.")
    if record.get("pgs_id") != authored["pgs_id"]:
        raise PgsError("The score result belongs to a different PGS than the card.")
    position = derive_position(record, display_schema_version=display_schema_version)
    base = (
        position
        if position is not None
        else {
            "schema_version": display_schema_version,
            "pgs_id": record["pgs_id"],
            "score_sha256": record_digest(record),
            "position": None,
            "portability": record.get("portability"),
        }
    )
    if display_schema_version >= 2 and position is None:
        base["phase_coverage"] = phase_coverage(record)
    return {
        **base,
        "authored": {
            **authored,
            "decile_outcomes": _deciles(authored["decile_outcomes"], position),
        },
    }


def computed_caveats(result: Mapping[str, Any] | None) -> tuple[str, ...]:
    if result is None or result.get("position") is None:
        return ()
    caveats = [INTERVAL_BASIS]
    if not result["reference"]["ancestry_matched"]:
        caveats.append(
            "Compared with the pooled 1000 Genomes panel, not an ancestry-matched group: "
            + str(result["reference"]["reason"])
        )
    caveats.append(str(result["portability"]["reason"]))
    if result["quality"]["unknown_quality_weight_fraction"]:
        caveats.append(
            f"{_percent(result['quality']['unknown_quality_weight_fraction'])} of the "
            "comparable weight has no imputation-quality estimate and counts as zero quality."
        )
    return tuple(caveats)


def assemble_polygenic_card(
    card: Card, record: Mapping[str, Any] | None, *, reason: str | None = None
) -> AssembledCard:
    """One polygenic card from one score record, or not run with its reason."""
    if card.kind is not CardKind.POLYGENIC or card.evidence is None or card.pgs is None:
        raise EvidenceAssemblyError("polygenic assembly requires a polygenic card")
    if record is not None and reason is not None:
        raise EvidenceAssemblyError("a computed score result cannot also carry a not-run reason")
    try:
        result = build_result(_authored(card), record)
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceAssemblyError("The score result cannot be placed on a card.") from exc
    placed = result is not None and result.get("position") is not None
    status = MatchStatus.COMPUTED if placed else MatchStatus.NOT_RUN
    why = None if placed else (reason or (unavailable_reason(record) if record else None))
    why = why or "The polygenic score has not been computed for this run."
    summary = face_text(
        card.title, str(card.trait), result, card.evidence.within_family_attenuation, why
    )
    return AssembledCard(
        card_id=card.id,
        section=card.section,
        kind=card.kind,
        title=card.title,
        status=status,
        summary=summary,
        detail=card.detail or "",
        card=card,
        match=MatchResult(card.id, status, summary if placed else why),
        observation=None,
        confidence=None,
        frequencies=(),
        confidence_frequency=None,
        citations=card.citations,
        authored_caveats=card.caveats,
        computed_caveats=computed_caveats(result),
        computation={
            "source": SOURCE,
            "status": status.value,
            "reason": None if placed else why,
            "result": result,
            "reliability": reliability(card.evidence, result),
            "method_evidence": None,
        },
    )


# ---------------------------------------------------------------------------
# Reload validation
# ---------------------------------------------------------------------------


def evidence_from_payload(payload: Mapping[str, Any]) -> Evidence:
    """Rebuild the card's evidence from its bundle payload (format 2+)."""
    effect = payload["effect"]
    return Evidence(
        tier=EvidenceTier(payload["tier"]),
        effect=Effect(
            measure=EffectMeasure(effect["measure"]),
            value=float(effect["value"]),
            units=effect["units"],
            ci_low=effect["ci_low"],
            ci_high=effect["ci_high"],
            context=effect["context"],
        ),
        sample_size=int(payload["sample_size"]),
        ancestry=tuple(Ancestry(a) for a in payload["ancestry"]),
        replication=Replication(payload["replication"]),
        within_family_attenuation=payload["within_family_attenuation"],
    )


def validate_stored(data: Mapping[str, Any], record: Mapping[str, Any] | None) -> None:
    """Refuse a stored polygenic card that its own score record does not reproduce."""
    from genetics.pgs.coverage import compute_coverage
    from genetics.pgs.portability import compute_portability
    from genetics.pgs.reference import validate_distribution

    computation = data["computation"]
    result = computation["result"]
    evidence = evidence_from_payload(data["evidence"])
    if result is None:
        if record is not None or data["status"] != "not_run":
            raise PgsError("A polygenic card without a result must be not run and unscored.")
    else:
        if record is None or record_digest(record) != result["score_sha256"]:
            raise PgsError("The stored score record does not match the polygenic card.")
        schema = int(record["schema_version"])
        if json.loads(json.dumps(compute_coverage(record, schema_version=schema))) != record.get(
            "coverage"
        ):
            raise PgsError("The stored score record's coverage disagrees with its evidence.")
        validate_distribution(record)
        if json.loads(json.dumps(compute_portability(record))) != record.get("portability"):
            raise PgsError("The stored score record's portability disagrees with its inputs.")
        authored = {k: v for k, v in result["authored"].items() if k != "decile_outcomes"}
        deciles = result["authored"]["decile_outcomes"]
        authored["decile_outcomes"] = (
            None
            if deciles is None
            else {k: v for k, v in deciles.items() if k not in {"overlapped", "overlapped_range"}}
        )
        if (
            json.loads(
                json.dumps(
                    build_result(authored, record, display_schema_version=result["schema_version"])
                )
            )
            != result
        ):
            raise PgsError("The stored polygenic display disagrees with its score record.")
    placed = result is not None and result.get("position") is not None
    expected_status = "computed" if placed else "not_run"
    if data["status"] != expected_status or computation["status"] != expected_status:
        raise PgsError("The polygenic card's status disagrees with its result.")
    if json.loads(json.dumps(reliability(evidence, result))) != computation["reliability"]:
        raise PgsError("The polygenic card's reliability disagrees with its inputs.")
    trait = result["authored"]["trait"] if result is not None else ""
    if data["summary"] != face_text(
        data["title"], trait, result, evidence.within_family_attenuation, computation["reason"]
    ):
        raise PgsError("The polygenic card's face disagrees with its result.")
