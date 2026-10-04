"""Keep sex-chromosome measurements and their limitations visible together."""

from __future__ import annotations

from genetics.engine.cards import Card, CardKind
from genetics.engine.evidence import AssembledCard, EvidenceAssemblyError
from genetics.engine.matcher import MatchResult, MatchStatus
from genetics.structure.sex_chromosomes import LIMIT, SOURCE, SexChromosomeResult, validate_result


def assemble_sex_chromosome_card(
    card: Card, result: SexChromosomeResult | None, *, reason: str | None = None
) -> AssembledCard:
    if card.kind is not CardKind.COMPUTED or card.computation != SOURCE:
        raise EvidenceAssemblyError("sex-chromosome assembly requires its computed card")
    if result is not None and reason is not None:
        raise EvidenceAssemblyError("measured sex chromosomes cannot also be not run")
    data = None if result is None else result.as_dict()
    if data is not None:
        validate_result(data, data["status"])
    status = MatchStatus.NOT_RUN if data is None else MatchStatus(data["status"])
    unavailable = reason or "Sex-chromosome reporting has not run."
    summary = unavailable
    if data is not None:
        x, y = data["x"], data["y"]
        xr, yr = data["x_het_rate"], data["y_call_rate"]
        xtext = "unavailable" if xr is None else f"{xr:.1%}"
        ytext = "unavailable (no Y probes)" if yr is None else f"{yr:.1%}"
        summary = (
            f"Non-PAR X heterozygosity {xtext} "
            f"({x['heterozygous_snps']}/{x['snp_called']} SNP calls); "
            f"non-PAR Y call rate {ytext} ({y['called']}/{y['total']} probes). "
        )
        if status is not MatchStatus.COMPUTED:
            summary += "Too few usable X SNPs for QC inference. "
        elif data["qc_inferred_sex"] == "ambiguous":
            summary += "Signals do not agree; X/Y ploidy remains unresolved. "
        elif yr is None:
            summary += "QC ploidy assumption rests on X alone. "
        summary += "Limited reliability. " + LIMIT
    reliability = {
        "tier": "limited" if status is MatchStatus.COMPUTED else None,
        "inputs": {
            "directly_typed_only": True,
            "chip_population_calibrated": False,
            "intensity_available": False,
            "usable_x_snps": None if data is None else data["x"]["snp_called"],
            "y_probes": None if data is None else data["y"]["total"],
        },
        "reason": "Call-only QC heuristics have no calibrated karyotype accuracy. "
        "Sparse panels, ancestry, missingness, errors and mixed samples can alter the pattern.",
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
        computed_caveats=(unavailable,) if data is None else tuple(data["warnings"]),
        computation={
            "source": SOURCE,
            "status": status.value,
            "reason": unavailable if data is None else None,
            "result": data,
            "reliability": reliability,
            "method_evidence": dict(card.method_evidence or {}),
        },
    )
