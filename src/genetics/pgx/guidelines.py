"""Conditional CPIC guideline cards, reproduced from frozen M10.2 evidence.

No allele activity expression is evaluated and no clinical dose is calculated.
Every recommendation keeps all required genes and its complete clinical context.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from genetics.engine.cards import Card, CardKind
from genetics.engine.citations import Citation, CitationError, citation_url
from genetics.engine.evidence import AssembledCard
from genetics.engine.matcher import MatchResult, MatchStatus
from genetics.pgx.catalog import TRACTABLE
from genetics.pgx.sources import digest, object_field

SOURCE = "pgx_guideline"
VERSION = 2
NOTICE = (
    "Conditional source annotations, not established sample phenotypes. "
    "Every candidate, required gene and population/clinical condition must hold; "
    "no branch establishes an individual dose."
)


def _equal(left: Any, right: Any) -> bool:
    # Numeric scalars only. Never execute source activity expressions or treat n/a as zero.
    numeric = r"[+-]?[0-9]+(?:\.[0-9]+)?"
    if (
        isinstance(left, str)
        and isinstance(right, str)
        and re.fullmatch(numeric, left)
        and re.fullmatch(numeric, right)
    ):
        return Decimal(left) == Decimal(right)
    return bool(left == right)


def _branches(raw: Mapping[str, Any], gene: str) -> list[dict[str, Any]]:
    tables = raw["reference"]["cpic"]["tables"]
    mappings = {r["id"]: r for r in tables["gene_result_diplotype"]}
    lookups = {r["id"]: r for r in tables["gene_result_lookup"]}
    results = {r["id"]: r for r in tables["gene_result"]}
    definitions = raw["reference"]["definitions"]
    calls = raw["genes"][gene]
    branches = []
    for index, candidate in enumerate(calls["candidates"]):
        labels = [definitions[i]["source_definition"]["name"] for i in candidate["definition_ids"]]
        counts = dict(Counter(labels))
        joined = []
        for identity in candidate["mapping_ids"]:
            mapping = mappings[identity]
            lookup = lookups[mapping["functionphenotypeid"]]
            result = results[lookup["phenotypeid"]]
            if (
                lookup["id"] not in candidate["lookup_ids"]
                or object_field(mapping["diplotypekey"]) != {gene: counts}
                or result["genesymbol"] != gene
            ):
                raise ValueError("Guideline candidate source joins disagree.")
            joined.append({"mapping": mapping, "lookup": lookup, "result": result})
        branches.append(
            {
                "candidate_index": index,
                "candidate": candidate,
                "allele_counts": counts,
                "functions": {i: definitions[i]["functions"] for i in candidate["definition_ids"]},
                "joins": joined,
            }
        )
    return branches


def _publication_citations(publication: Mapping[str, Any]) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    for kind in ("pmid", "doi"):
        if publication.get(kind):
            try:
                citations.append(
                    Citation.parse(
                        {"type": kind, "id": publication[kind], "title": publication.get("title")},
                        "PGx publication",
                    )
                )
            except CitationError:
                # Source ingestion preserves curation gaps; malformed evidence cannot
                # establish an implication or prevent other cited branches from rendering.
                continue
    return tuple(citations)


def _usable_guideline_url(guideline: Mapping[str, Any] | None) -> bool:
    if guideline is None:
        return False
    url = guideline.get("url")
    if not isinstance(url, str) or url != url.strip() or citation_url("url", url) is None:
        return False
    try:
        return bool(urlsplit(url).hostname)
    except ValueError:
        return False


def derive(
    raw: Mapping[str, Any] | None, gene: str, *, schema_version: int = VERSION
) -> dict[str, Any]:
    """Pure projection of a validated sample record; retains every compatible branch."""
    if type(schema_version) is not int or schema_version not in {1, VERSION}:
        raise ValueError("Unsupported guideline display schema.")
    if gene not in TRACTABLE:
        raise ValueError("Guideline selector must be a SNP-tractable PGx gene.")
    if raw is None or raw["status"] != "completed":
        return {
            "schema_version": schema_version,
            "gene": gene,
            "status": "unavailable",
            "reason": "PGx sample evidence not recorded." if raw is None else raw["reason"],
            "branches": [],
            "recommendations": [],
            "gaps": ["No frozen PGx reference/calls."],
        }
    tables = raw["reference"]["cpic"]["tables"]
    pairs = [p for p in tables["pair"] if p["genesymbol"] == gene]
    guideline_ids = {p["guidelineid"] for p in pairs if p["guidelineid"] is not None}
    guidelines = [g for g in tables["guideline"] if g["id"] in guideline_ids]
    publications = [p for p in tables["publication"] if p.get("guidelineid") in guideline_ids]
    drugs = {d["drugid"]: d for d in tables["drug"]}
    all_branches = {g: _branches(raw, g) for g in TRACTABLE}
    genes = {g["symbol"]: g for g in tables["gene"]}
    recommendations = []
    gaps = []
    if not all_branches[gene]:
        gaps.append("No compatible source definition candidates.")
    unmapped = [b["candidate_index"] for b in all_branches[gene] if not b["joins"]]
    if unmapped:
        gaps.append(
            "Some candidates have no source phenotype/activity mapping; see unmapped_candidates."
        )
    for row in tables["recommendation"]:
        key = object_field(row["lookupkey"])
        linked = [
            p
            for p in pairs
            if p["guidelineid"] is not None
            and p["guidelineid"] == row["guidelineid"]
            and p["drugid"] == row["drugid"]
        ]
        if gene not in key or not linked:
            continue
        conditions = []
        excluded = False
        for required_gene, value in key.items():
            support = []
            unassessed = []
            method = genes.get(required_gene, {}).get("lookupmethod")
            for branch in all_branches.get(required_gene, []):
                matches = []
                unresolved_value = False
                for join in branch["joins"]:
                    actual = (
                        join["lookup"]["totalactivityscore"]
                        if method == "ACTIVITY_SCORE"
                        else join["result"]["result"]
                        if method == "PHENOTYPE"
                        else None
                    )
                    if actual is None or (
                        method == "ACTIVITY_SCORE"
                        and actual != "n/a"
                        and not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", actual)
                        and actual != value
                    ):
                        unresolved_value = True
                    if actual is not None and _equal(actual, value):
                        matches.append(join["mapping"]["id"])
                if matches:
                    support.append(
                        {"candidate_index": branch["candidate_index"], "mapping_ids": matches}
                    )
                if (
                    not branch["joins"]
                    or unresolved_value
                    or method not in {"PHENOTYPE", "ACTIVITY_SCORE"}
                ):
                    unassessed.append(branch["candidate_index"])
            if required_gene not in all_branches or not all_branches[required_gene]:
                state = "unassessed"
            elif support:
                state = "candidate-compatible"
            elif unassessed:
                state = "unassessed"
            else:
                excluded = True
                break
            conditions.append(
                {
                    "gene": required_gene,
                    "required_value": value,
                    "lookup_method": method,
                    "state": state,
                    "support": support,
                    "unmapped_candidates": unassessed,
                }
            )
        if excluded:
            continue
        guideline = next((g for g in guidelines if g["id"] == row["guidelineid"]), None)
        pubs = [p for p in publications if p["guidelineid"] == row["guidelineid"]]
        row_gaps = []
        usable_url = (
            bool(guideline and guideline.get("url"))
            if schema_version == 1
            else _usable_guideline_url(guideline)
        )
        cited = (
            any(p.get("pmid") or p.get("doi") for p in pubs)
            if schema_version == 1
            else any(_publication_citations(p) for p in pubs)
        )
        text = row.get("drugrecommendation")
        readable = schema_version == 1 or (isinstance(text, str) and bool(text.strip()))
        if not readable:
            row_gaps.append("Recommendation text not provided; implication is unavailable.")
        if not usable_url:
            row_gaps.append("Guideline row/URL not provided.")
        if not cited:
            row_gaps.append(
                "Usable titled guideline DOI/PMID evidence not provided; "
                "implication is unavailable."
                if schema_version >= 2
                else "Guideline DOI/PMID evidence not provided; implication is unavailable."
            )
        if schema_version >= 2 and any(
            sum(bool(p.get(kind)) for kind in ("pmid", "doi")) > len(_publication_citations(p))
            for p in pubs
        ):
            row_gaps.append(
                "Some source publication identifiers/titles are unusable; "
                "the original rows remain in the evidence."
            )
        if row["drugid"] not in drugs:
            row_gaps.append("Drug row not provided.")
        if any(c["state"] == "unassessed" or c["unmapped_candidates"] for c in conditions):
            row_gaps.append("Required gene conditions remain unassessed for some alternatives.")
        recommendations.append(
            {
                "source_row": row,
                "drug": drugs.get(row["drugid"]),
                "pairs": linked,
                "guideline": guideline,
                "publications": pubs,
                "conditions": conditions,
                "status": "evidence-missing"
                if not usable_url or not cited or not readable
                else "conditional",
                "gaps": row_gaps,
            }
        )
    if not recommendations:
        gaps.append(
            "No compatible guideline recommendation lookup rows; no dosing implication established."
        )
    if raw["genes"][gene].get("phenotype_mapping_status") != "available":
        gaps.append("Source phenotype lookup table not provided for this gene.")
    for identity in sorted(guideline_ids):
        if not any(r["source_row"]["guidelineid"] == identity for r in recommendations):
            gaps.append(f"Guideline {identity}: no compatible recommendation key for this gene.")
    required = {c["gene"] for r in recommendations for c in r["conditions"]} | {gene}
    reliability = {
        g: raw["genes"][g].get("reliability") for g in sorted(required) if g in raw["genes"]
    }
    tier = (
        "likely-artifact"
        if any(r and r["tier"] == "likely-artifact" for r in reliability.values())
        else "limited"
    )
    return {
        "schema_version": schema_version,
        "gene": gene,
        "status": "conditional",
        "reason": NOTICE,
        "source": raw["reference"]["cpic"]["source"],
        "annotation_source": raw["reference"]["annotations"]["source"],
        "reference_sha256": raw["reference_sha256"],
        "branches": all_branches[gene],
        "required_gene_branches": {
            g: all_branches[g] for g in sorted(required - {gene}) if g in all_branches
        },
        "call_evidence": {
            g: raw["genes"][g].get("models", []) for g in sorted(required) if g in raw["genes"]
        },
        "unmapped_candidates": unmapped,
        "recommendations": recommendations,
        "pairs": pairs,
        "guidelines": guidelines,
        "publications": publications,
        "gene_notes": raw["genes"][gene].get("gene_notes", {}),
        "notes": raw["genes"][gene].get("notes", []),
        "reliability": {"tier": tier, "reason": NOTICE, "genes": reliability},
        "gaps": gaps,
        "context_limit": (
            "Source population and complete comments are conditions, "
            "not a measured ancestry match. Clinical context is unassessed."
        ),
    }


def _citations(result: Mapping[str, Any], fallback: Sequence[Citation]) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    for publication in result.get("publications", []):
        if result["schema_version"] >= 2:
            citations.extend(_publication_citations(publication))
            continue
        for kind in ("pmid", "doi"):
            if publication.get(kind) and publication.get("title"):
                citations.append(
                    Citation.parse(
                        {"type": kind, "id": publication[kind], "title": publication["title"]},
                        "PGx publication",
                    )
                )
    return tuple(dict.fromkeys(citations)) or tuple(fallback)


def assemble_guideline_card(
    card: Card, raw: Mapping[str, Any] | None, *, display_schema_version: int = VERSION
) -> AssembledCard:
    if card.kind is not CardKind.GUIDELINE or card.gene is None:
        raise ValueError("Expected a guideline card with a gene selector.")
    result = derive(raw, card.gene, schema_version=display_schema_version)
    available = result["status"] == "conditional"
    status = MatchStatus.COMPUTED if available else MatchStatus.NOT_RUN
    tier = result.get("reliability", {}).get("tier")
    count = (
        len(result["recommendations"])
        if display_schema_version == 1
        else sum(r["status"] == "conditional" for r in result["recommendations"])
    )
    incomplete = len(result["recommendations"]) - count
    levels = sorted({p["cpiclevel"] for p in result.get("pairs", []) if p.get("cpiclevel")})
    classes = sorted(
        {
            r["source_row"]["classification"]
            for r in result["recommendations"]
            if r["source_row"].get("classification")
        }
    )
    summary = (
        f"{card.gene}: {count} conditional CPIC recommendation branches; "
        + (f"Source rows lacking usable evidence: {incomplete}; " if incomplete else "")
        + f"CPIC gene-drug levels: {', '.join(levels) or 'not provided'}; "
        f"recommendation classifications: {', '.join(classes) or 'not provided'}. "
        + (f"Reliability: {tier}. " if tier else "")
        + NOTICE
    )
    if not available:
        summary = f"{card.gene}: guideline interpretation unavailable. {result['reason']}"
    reasons = []
    for reliability in result.get("reliability", {}).get("genes", {}).values():
        if reliability:
            reasons.extend(reliability["reasons"])
    if tier == "likely-artifact":
        reasons.append(
            "The ~16% benchmark concerns rare heterozygous SNP-chip calls; "
            "not a personal posterior or an imputation validation."
        )
    # Keep numerical PPV scope and poor/unknown imputation quality on the face.
    summary += " " + " ".join(dict.fromkeys(reasons))
    detail = " ".join([NOTICE, *result["gaps"], result.get("context_limit", "")])
    return AssembledCard(
        card_id=card.id,
        section=card.section,
        kind=card.kind,
        title=card.title,
        status=status,
        summary=summary.strip(),
        detail=detail,
        card=card,
        match=MatchResult(card_id=card.id, status=status, reason=result["reason"] or NOTICE),
        observation=None,
        confidence=None,
        frequencies=(),
        confidence_frequency=None,
        citations=_citations(result, card.citations),
        authored_caveats=card.caveats,
        computed_caveats=(),
        computation={
            "source": SOURCE,
            "status": status.value,
            "reason": result["reason"] or NOTICE,
            "result": result,
            "reliability": {"tier": tier, "reason": NOTICE},
            "method_evidence": None,
        },
    )


def validate_stored(entry: Mapping[str, Any], raw: Mapping[str, Any] | None) -> None:
    """Bind display and citations to the validated sample snapshot, without current caches."""
    from genetics.run.bundle import _card_payload

    card = Card.parse(
        {
            "id": entry["card_id"],
            "section": entry["section"],
            "kind": "guideline",
            "title": entry["title"],
            "gene": entry["gene"],
            "citations": [{k: v for k, v in c.items() if k != "url"} for c in entry["citations"]],
            "caveats": entry["authored_caveats"],
        },
        "saved guideline",
    )
    version = entry["computation"]["result"]["schema_version"]
    expected = _card_payload(assemble_guideline_card(card, raw, display_schema_version=version))
    # Mode is independently bound to the run; every other field must reproduce exactly.
    expected["imputation_mode"] = entry.get("imputation_mode")
    if digest(entry) != digest(expected):
        raise ValueError("Saved guideline card disagrees with frozen PGx evidence.")
