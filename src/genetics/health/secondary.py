"""ACMG gene-list surfacing, separate from clinical reportability (M7.4)."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from genetics.engine.ppv import CLINICAL_NOTICE
from genetics.health.clinvar import ClinVarError, ClinVarLookup
from genetics.paths import references_dir

SOURCE = "acmg_sf_v3_3"
DOI = "10.1016/j.gim.2025.101454"
POLICY = (
    "Exact ClinVar GENEINFO symbols identify ACMG SF v3.3 gene-list overlaps; "
    "NCBI gene IDs are retained, not independently verified against HGNC. All overlaps "
    "remain visible, including uncertain, conflicting and unresolved observations. "
    "Gene membership and a ClinVar P/LP annotation do not establish ACMG clinical "
    "reportability: disease, inheritance, phase, variant type and gene-specific "
    "restrictions have not been adjudicated. An array cannot exclude variants in these "
    "genes, including structural variants. No overlap is not a negative clinical screen."
)
NOTICE = CLINICAL_NOTICE


def _validate_genes(genes: Any) -> None:
    if not isinstance(genes, list) or not genes:
        raise ValueError
    symbols: set[str] = set()
    ids: set[str] = set()
    for gene in genes:
        if (
            not isinstance(gene, dict)
            or set(gene) != {"symbol", "hgnc_id", "guidance"}
            or not isinstance(gene["symbol"], str)
            or not re.fullmatch(r"[A-Z][A-Z0-9-]*", gene["symbol"])
            or not isinstance(gene["hgnc_id"], str)
            or not re.fullmatch(r"HGNC:[1-9][0-9]*", gene["hgnc_id"])
            or not isinstance(gene["guidance"], str)
            or gene["symbol"] in symbols
            or gene["hgnc_id"] in ids
        ):
            raise ValueError
        symbols.add(gene["symbol"])
        ids.add(gene["hgnc_id"])


def parse_reference(payload: bytes, *, expected_genes: int = 84) -> list[dict[str, str]]:
    """Parse the complete public ClinGen export; never a sample-selected roster."""
    try:
        raw = json.loads(payload)
        if (
            type(raw["total"]) is not int
            or raw["total"] != expected_genes
            or raw["totalNotFiltered"] != expected_genes
            or len(raw["rows"]) != expected_genes
        ):
            raise ValueError
        genes = [
            {"symbol": row["symbol"], "hgnc_id": row["hgnc_id"], "guidance": row["comments"]}
            for row in raw["rows"]
        ]
        _validate_genes(genes)
        return sorted(genes, key=lambda gene: gene["symbol"])
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ClinVarError("ClinGen ACMG reference is incomplete or malformed") from exc


def default_reference() -> Mapping[str, Any] | None:
    """Offline only. Missing source is explicit; corruption fails closed."""
    from genetics.refs.manifest import load

    source = load().get(SOURCE)
    item = source.files[0]
    path = references_dir() / source.id / item.filename
    if not path.is_file():
        return None
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if not item.sha256 or digest != item.sha256:
        raise ClinVarError("ClinGen ACMG reference does not match its pinned checksum")
    genes = parse_reference(payload)
    return {
        "provenance": {
            "source": SOURCE,
            "version": source.version,
            "filename": item.filename,
            "sha256": digest,
            "records": len(genes),
            "accessed": "2026-10-05",
            "license": "CC0-1.0",
            "doi": DOI,
        },
        "genes": genes,
    }


def annotation(entry: Mapping[str, Any], genes: list[dict[str, str]]) -> dict[str, Any] | None:
    info = entry["info"]
    gene_info = info.get("GENEINFO")
    if not isinstance(gene_info, str):
        return None
    roster = {gene["symbol"]: gene for gene in genes}
    matches = []
    for pair in sorted(set(gene_info.split("|"))):
        symbol, separator, ncbi_id = pair.partition(":")
        if symbol in roster and separator and re.fullmatch(r"[1-9][0-9]*", ncbi_id):
            matches.append({**roster[symbol], "ncbi_gene_id": ncbi_id})
    if not matches:
        return None
    significance = info.get("CLNSIG")
    labels = (
        [label for group in significance.split("|") for label in group.split("/")]
        if isinstance(significance, str)
        else []
    )
    classification = (
        "pathogenic_or_likely_pathogenic_annotation"
        if labels
        and all(label in {"Pathogenic", "Likely_pathogenic"} for label in labels)
        and not info.get("CLNSIGCONF")
        else "other_or_unresolved_annotation"
    )
    return {
        "genes": matches,
        "classification": classification,
        "reportability": "not_adjudicated",
        "notice": NOTICE,
    }


def surface(lookup: ClinVarLookup, reference: Mapping[str, Any] | None) -> ClinVarLookup:
    """Annotate every overlap without changing observation or reliability results."""
    if lookup.frequency_reference is None:
        raise ClinVarError("ACMG surfacing requires the recorded frequency-screen stage")
    genes = [] if reference is None else reference["genes"]
    counts: Counter[str] = Counter()
    loci = []
    for locus in lookup.loci:
        entries = []
        for entry in locus["records"]:
            acmg = annotation(entry, genes)
            entries.append({**entry, "acmg": acmg})
            if acmg:
                counts["overlapping_records"] += 1
                counts[entry["status"]] += 1
                if entry["status"] == "alternate_observed":
                    counts[acmg["classification"]] += 1
                    counts[entry["reliability"]["tier"]] += 1
        loci.append({**locus, "records": entries})
    snapshot = {
        "status": "complete"
        if reference is not None and lookup.status == "complete"
        else "not_run",
        "reason": (
            "Pinned ClinGen ACMG SF v3.3 gene-list overlaps surfaced; "
            "clinical reportability is not adjudicated."
            if reference is not None and lookup.status == "complete"
            else "ClinGen ACMG gene list or ClinVar lookup is unavailable; "
            "no secondary-finding screen was completed."
        ),
        "policy": POLICY,
        "notice": NOTICE,
        "provenance": None if reference is None else reference["provenance"],
        "genes": genes,
        "counts": dict(sorted(counts.items())),
    }
    return replace(lookup, loci=tuple(loci), secondary_reference=snapshot)


def secondary_view(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The same saved-data view for CLI and dashboard, with no confidence filter."""
    loci = []
    for locus in raw["loci"]:
        entries = [entry for entry in locus["records"] if entry.get("acmg")]
        if entries:
            loci.append({**locus, "records": entries})
    return {"reference": raw.get("secondary_reference"), "loci": loci}


def validate_secondary(raw: Mapping[str, Any]) -> None:
    """Reconstruct annotations from the saved roster, never today's reference cache."""
    from genetics.health.clinvar import validate_lookup

    try:
        base = json.loads(json.dumps(raw))
        saved = base.pop("secondary_reference")
        if not isinstance(saved["counts"], dict) or any(
            type(value) is not int or value < 0 for value in saved["counts"].values()
        ):
            raise ValueError
        base["schema_version"] = 3
        genes = saved["genes"]
        provenance = saved["provenance"]
        if provenance is None:
            if genes != []:
                raise ValueError
            reference = None
        else:
            _validate_genes(genes)
            if (
                set(provenance)
                != {
                    "source",
                    "version",
                    "filename",
                    "sha256",
                    "records",
                    "accessed",
                    "license",
                    "doi",
                }
                or provenance["source"] != SOURCE
                or provenance["version"] != "3.3"
                or provenance["license"] != "CC0-1.0"
                or provenance["doi"] != DOI
                or type(provenance["records"]) is not int
                or provenance["records"] != len(genes)
                or not isinstance(provenance["filename"], str)
                or not provenance["filename"]
                or not re.fullmatch(r"[0-9a-f]{64}", provenance["sha256"])
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", provenance["accessed"])
            ):
                raise ValueError
            reference = {"genes": genes, "provenance": provenance}
        for locus in base["loci"]:
            for entry in locus["records"]:
                recorded = entry.pop("acmg")
                if recorded != annotation(entry, genes):
                    raise ValueError
        validate_lookup(base)
        lookup = ClinVarLookup(
            base["status"],
            base["reason"],
            base["provenance"],
            base["counts"],
            tuple(base["loci"]),
            base["frequency_reference"],
        )
        if surface(lookup, reference).secondary_reference != saved:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ClinVarError("Saved ACMG surfacing is malformed or inconsistent") from exc
