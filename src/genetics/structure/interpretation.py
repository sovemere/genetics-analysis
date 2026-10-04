"""Interpret observed long ROH without inferring a particular pedigree (M6.2).

The native engine owns measurement; the knowledge pack owns the scientific explanation.
No population percentile, clinical risk or parental relationship is inferred from an
uncalibrated assay fraction. Reliability is independent of the single-variant calculator.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from genetics.engine.cards import Card, CardKind
from genetics.engine.confidence import ConfidenceTier
from genetics.engine.evidence import AssembledCard, EvidenceAssemblyError
from genetics.engine.matcher import MatchResult, MatchStatus
from genetics.external.plink2 import Plink2, Plink2NotFoundError
from genetics.external.plink19 import Plink19
from genetics.ingest.schema import GenotypeTable
from genetics.paths import references_dir
from genetics.structure.roh import ReferenceInput, RohResult, compute_roh


def default_references() -> tuple[ReferenceInput, ...]:
    root = references_dir() / "thousand_genomes_phase3_grch37"
    return tuple(
        ReferenceInput(
            root / f"ALL.chr{c}.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz",
            "1000 Genomes phase 3 GRCh37 20130502 v5b",
            "pooled 1000G phase 3 (not ancestry-matched)",
        )
        for c in range(1, 23)
    )


def assemble_roh_card(
    card: Card, result: RohResult | None, *, reason: str | None = None
) -> AssembledCard:
    if card.kind is not CardKind.COMPUTED or card.computation != "long_roh":
        raise EvidenceAssemblyError("ROH assembly requires a long_roh computed card")
    if result is not None and reason is not None:
        raise EvidenceAssemblyError("a measured ROH result cannot also be not run")
    data = result.as_dict() if result is not None else None
    status = MatchStatus(data["status"]) if data is not None else MatchStatus.NOT_RUN
    unavailable = reason or "Long-ROH computation has not run."
    summary = unavailable
    if data is not None:
        if status is MatchStatus.COMPUTED:
            fraction = data["f_roh"]
            count = data["roh_count"]
            threshold = data["settings"]["min_kb"] / 1000
            summary = (
                f"{count} run(s) of homozygosity meeting the {threshold:g} Mb minimum, "
                f"totalling {data['total_roh_bp'] / 1e6:.2f} Mb; "
                f"observed F_ROH {fraction:.2%} of {data['denominator_bp'] / 1e6:.2f} Mb "
                "of assayed autosomal spans. "
            )
            summary += card.summary or ""
            if not count:
                summary += " No run met this policy; shorter or unobservable runs remain possible."
        elif status is MatchStatus.INSUFFICIENT_CALLS:
            summary = "F_ROH unavailable: insufficient local calls in eligible assay spans."
        else:
            summary = (
                "F_ROH unavailable: insufficient assay coverage for supported long-ROH windows."
            )
    # Calibration belongs to the method, never to a card-author-selected confidence.
    # No empirical chip/population validation currently exists, so interpretation has
    # a limited ceiling even if the assay has complete observability.
    inputs: dict[str, Any] = {
        "chip_population_calibrated": False,
        # A user-chosen population label is not proof of ancestry matching.
        "ancestry_matched_reference": False
        if data is not None
        and any(
            "not ancestry-matched" in reference["population"] for reference in data["references"]
        )
        else None,
        "chromosomes_assayed": 0 if data is None else len(data["chromosomes_assayed"]),
        "unsupported_intervals": 0
        if data is None
        else sum(not window["observed_windows"] for window in data["window_support"]),
        "n_missing_calls": None if data is None else data["n_missing_calls"],
    }
    tier = ConfidenceTier.LIMITED.value if status is MatchStatus.COMPUTED else None
    if status is MatchStatus.COMPUTED:
        if inputs["chromosomes_assayed"] < 22:
            summary += " Partial autosomal coverage."
        if inputs["unsupported_intervals"]:
            summary += " Unsupported assay spans can cause underestimation."
        if inputs["n_missing_calls"]:
            summary += " Missing calls can cause underestimation."
    reliability = {
        "tier": tier,
        "inputs": inputs,
        "reason": "Interpretation is limited: no empirical chip/population calibration; "
        "coverage and reference filtering affect the observed fraction."
        if tier
        else "No numeric interpretation is available.",
    }
    warnings = tuple(data["warnings"]) if data is not None else (unavailable,)
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
        computed_caveats=warnings,
        computation={
            "source": "long_roh",
            "status": status.value,
            "reason": unavailable if data is None else None,
            "result": data,
            "reliability": reliability,
            "method_evidence": dict(card.method_evidence or {}),
        },
    )


def infer_roh_cards(
    cards: tuple[AssembledCard, ...],
    table: GenotypeTable,
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[AssembledCard, ...]:
    """Run once for all ROH cards; absent dependencies stay visible, malformed ones fail."""
    if not any(card.kind is CardKind.COMPUTED for card in cards):
        return cards
    refs = default_references()
    result = None
    reason = None
    if any(not reference.path.is_file() for reference in refs):
        reason = (
            "Long-ROH computation not run: the full 22-autosome 1000 Genomes panel "
            "is missing. Run `genetics refs fetch --only thousand_genomes_phase3_grch37`."
        )
    else:
        try:
            tool2, tool19 = Plink2.discover(), Plink19.discover()
        except Plink2NotFoundError as exc:
            reason = str(exc)
        else:
            if progress:
                progress("Computing long autosomal runs of homozygosity")
            result = compute_roh(table, refs, plink2=tool2, plink19=tool19, progress=progress)
    return tuple(
        assemble_roh_card(card.card, result, reason=reason)
        if card.kind is CardKind.COMPUTED
        else card
        for card in cards
    )
