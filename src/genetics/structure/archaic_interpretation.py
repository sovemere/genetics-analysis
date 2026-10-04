"""Archaic array ranges, their assumptions and unavailable states as visible cards."""

from __future__ import annotations

from genetics.engine.cards import Card, CardKind
from genetics.engine.evidence import AssembledCard, EvidenceAssemblyError
from genetics.engine.matcher import MatchResult, MatchStatus
from genetics.structure.archaic import SOURCES, ArchaicResult


def assemble_archaic_card(
    card: Card, result: ArchaicResult | None, *, reason: str | None = None
) -> AssembledCard:
    if card.kind is not CardKind.COMPUTED or card.computation not in SOURCES:
        raise EvidenceAssemblyError("archaic assembly requires an archaic computed card")
    if result is not None and reason is not None:
        raise EvidenceAssemblyError("a measured archaic result cannot also be not run")
    data = result.as_dict() if result is not None else None
    if data is not None and data["source"] != card.computation:
        raise EvidenceAssemblyError("archaic result and computation source disagree")
    status = MatchStatus(data["status"]) if data is not None else MatchStatus.NOT_RUN
    unavailable = reason or "Archaic estimation has not run."
    summary = unavailable
    if data is not None:
        interval = data["range"]
        if interval is None:
            summary = (
                "Archaic estimate unavailable: insufficient coverage "
                "or an unstable reference denominator."
            )
        else:
            # Round outwards: the face never narrows a recorded interval or implies
            # a precise point estimate. Signed limits are not clamped to zero.
            import math

            low = math.floor(interval[0] * 1000) / 10
            high = math.ceil(interval[1] * 1000) / 10
            summary = (
                f"Array f4 model range {low:.1f}% to {high:.1f}%. "
                "Limited reliability; this is not a measured genome-wide DNA percentage. "
                "The range combines block uncertainty and filter sensitivity; uncalibrated "
                "array bias remains outside it. "
            ) + (card.summary or "")
            if interval[0] < 0 or interval[1] > 1:
                summary += " Signed bounds indicate uncertainty or model mismatch."
    tier = "limited" if status is MatchStatus.COMPUTED else None
    reliability = {
        "tier": tier,
        "inputs": {
            "chip_population_calibrated": False,
            "directly_typed_only": True,
            "original_sequence_quality_masks_available": False,
            "n_shared_reference_sites": None if data is None else data["n_shared_reference_sites"],
            "sensitivity_filters_available": 0
            if data is None
            else sum(d["interval"] is not None for d in data["diagnostics"]),
        },
        "reason": "Limited by uncalibrated array ascertainment, published-reference calls "
        "and admixture-model assumptions. Block uncertainty cannot bound those errors."
        if tier
        else "No numeric interpretation is available.",
    }
    return AssembledCard(
        card_id=card.id,
        section=card.section,
        kind=card.kind,
        title=card.title,
        status=status,
        summary=summary,
        detail=card.detail or "",
        card=card,
        match=MatchResult(card.id, status, summary),
        observation=None,
        confidence=None,
        frequencies=(),
        confidence_frequency=None,
        citations=card.citations,
        authored_caveats=card.caveats,
        computed_caveats=tuple(data["warnings"]) if data is not None else (unavailable,),
        computation={
            "source": card.computation,
            "status": status.value,
            "reason": unavailable if data is None else None,
            "result": data,
            "reliability": reliability,
            "method_evidence": dict(card.method_evidence or {}),
        },
    )
