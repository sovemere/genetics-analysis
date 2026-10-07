"""Source-bound array/ClinVar coverage. Counts describe an assay, not a diagnosis.

Sample positions remain in memory. Only run bundles receive sample-derived counts;
the reference index is opened read-only and never gains a sample-selected table.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Mapping
from contextlib import closing
from typing import Any

import polars as pl

from genetics.engine.cards import Card, CardKind
from genetics.engine.evidence import AssembledCard
from genetics.engine.matcher import MatchResult, MatchStatus
from genetics.health.clinvar import ClinVarError, ClinVarIndex, ClinVarLookup
from genetics.ingest.schema import CallStatus, Chrom, GenotypeTable
from genetics.qc.metrics import heterozygosity, infer_sex
from genetics.qc.sex_regions import PAR_GRCH37

SOURCE = "clinvar_coverage"
NOTICE = (
    "Coverage is not clinical sensitivity or a count of confirmed pathogenic findings. "
    "ClinVar reference annotations are not clinical diagnoses. Rare chip calls may be "
    "artifacts; only clinical sequencing can establish or exclude a variant. "
    "Zero overlap is not a negative clinical screen."
)
POLICY = {
    "coordinate_system": "normalized chromosome and 1-based GRCh37 position",
    "reference_scope": "1-22, X, Y, MT; alternate/unplaced contigs excluded and counted",
    "reference_filters": "all classifications, review levels and FILTER values retained",
    "variant_key": "chromosome, position, REF, individual ALT; ALT '.' excluded",
    "matchable_variants": "biallelic A/C/G/T single-base records; duplicates deduplicated",
    "chip_scope": "all listed positions, including no-calls and vendor-labelled PAR",
    "duplicate_policy": "one position across aliases; disagreements remain unresolved",
    "called_policy": "at least one non-no-call probe; does not imply an allele-resolved call",
    "position_states": "conflict, no-call, indel, unresolved ploidy, SNP (in that order)",
    "allele_resolution": (
        "existing alternate_observed/reference_only states, excluding palindromic "
        "A/T and C/G records and unresolved non-PAR sex-chromosome ploidy; "
        "other strand-compatible matches assume vendor forward-strand reporting"
    ),
    "acmg_scope": "all ClinVar; ACMG roster overlaps are reported separately, not gene coverage",
}
STATES = ("conflicting_probes", "no_call", "indel_excluded", "ploidy_unresolved", "called_snp")
PRIMARY = tuple(c.value for c in Chrom if c is not Chrom.PAR)
REFERENCE_KEYS = {
    "records",
    "primary_records",
    "excluded_contig_records",
    "positions",
    "variants",
    "matchable_snv_variants",
}
CHIP_KEYS = {
    "markers",
    "positions",
    "duplicate_positions",
    "extra_probes",
    "called_positions",
    *STATES,
}
OVERLAP_KEYS = {
    *CHIP_KEYS,
    "records",
    "variants",
    "allele_resolved_positions",
    "allele_resolved_variants",
    "alternate_observed_variants",
    "reference_only_variants",
    "strand_unresolved_records",
    "record_states",
}


def _position(probes: list[dict[str, Any]], chrom: str, pos: int, sex: str) -> str:
    observations = {(p["genotype"], p["call_status"]) for p in probes}
    if len(observations) > 1:
        return "conflicting_probes"
    genotype, status = next(iter(observations))
    if status == CallStatus.NO_CALL:
        return "no_call"
    if any(a in "ID" for a in genotype):
        return "indel_excluded"
    nonpar = chrom in {"X", "Y"} and not any(
        start <= pos <= end for start, end in PAR_GRCH37[chrom]
    )
    if status == CallStatus.HET_HAPLOID or (nonpar and sex == "ambiguous"):
        return "ploidy_unresolved"
    return "called_snp"


def _chip_counts(loci: list[dict[str, Any]], sex: str) -> dict[str, int]:
    states: Counter[str] = Counter()
    markers = called = duplicates = 0
    for locus in loci:
        probes = locus["probes"]
        markers += len(probes)
        called += any(p["call_status"] != CallStatus.NO_CALL for p in probes)
        duplicates += len(probes) > 1
        states[_position(probes, locus["chrom"], locus["pos_grch37"], sex)] += 1
    return {
        "markers": markers,
        "positions": len(loci),
        "duplicate_positions": duplicates,
        "extra_probes": markers - len(loci),
        "called_positions": called,
        **{state: states[state] for state in STATES},
    }


def _overlap_counts(loci: list[dict[str, Any]], sex: str) -> dict[str, Any]:
    counts: dict[str, Any] = _chip_counts(loci, sex)
    variants: set[tuple[Any, ...]] = set()
    resolved: dict[tuple[Any, ...], str] = {}
    positions: set[tuple[str, int]] = set()
    states: Counter[str] = Counter()
    strands = 0
    for locus in loci:
        key = (locus["chrom"], locus["pos_grch37"])
        state = _position(locus["probes"], *key, sex)
        for entry in locus["records"]:
            states[entry["status"]] += 1
            for alt in entry["alts"]:
                if alt != ".":
                    variants.add((*key, entry["ref"], alt))
            compatible = entry["status"] in {"alternate_observed", "reference_only"}
            palindrome = set((entry["ref"], *entry["alts"])) in ({"A", "T"}, {"C", "G"})
            strands += compatible and palindrome
            if compatible and not palindrome and state == "called_snp":
                resolved[(*key, entry["ref"], entry["alts"][0])] = entry["status"]
                positions.add(key)
    from genetics.health.clinvar import STATUSES

    counts.update(
        records=sum(states.values()),
        variants=len(variants),
        allele_resolved_positions=len(positions),
        allele_resolved_variants=len(resolved),
        alternate_observed_variants=sum(s == "alternate_observed" for s in resolved.values()),
        reference_only_variants=sum(s == "reference_only" for s in resolved.values()),
        strand_unresolved_records=strands,
        record_states={s: states[s] for s in sorted(STATUSES)},
    )
    return counts


def _reference_counts(index: ClinVarIndex) -> dict[str, int]:
    """Scan the complete installed reference; no sample-dependent reference artifacts."""
    placeholders = ",".join("?" for _ in PRIMARY)
    primary = f"chrom IN ({placeholders})"
    with closing(sqlite3.connect(f"{index.path.as_uri()}?mode=ro", uri=True)) as db:
        db.execute("PRAGMA temp_store=MEMORY")
        records = db.execute("SELECT COUNT(*) FROM variants").fetchone()[0]
        if records != index.provenance["records"] or records == 0:
            raise ClinVarError("ClinVar coverage reference is empty or disagrees with provenance")
        primary_records = db.execute(
            f"SELECT COUNT(*) FROM variants WHERE {primary}", PRIMARY
        ).fetchone()[0]
        positions = db.execute(
            f"SELECT COUNT(*) FROM (SELECT chrom,pos FROM variants WHERE {primary} "
            "GROUP BY chrom,pos)",
            PRIMARY,
        ).fetchone()[0]
        variant_query = (
            "SELECT DISTINCT v.chrom,v.pos,json_extract(v.record,'$.ref') AS ref,a.value AS alt "
            "FROM variants v,json_each(v.record,'$.alts') a "
            f"WHERE v.{primary} AND a.value != '.'"
        )
        variants = db.execute(f"SELECT COUNT(*) FROM ({variant_query})", PRIMARY).fetchone()[0]
        snvs = db.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT chrom,pos,"
            "json_extract(record,'$.ref'),json_extract(record,'$.alts[0]') "
            f"FROM variants WHERE {primary} AND "
            "json_array_length(record,'$.alts')=1 AND "
            "json_extract(record,'$.ref') IN ('A','C','G','T') AND "
            "json_extract(record,'$.alts[0]') IN ('A','C','G','T'))",
            PRIMARY,
        ).fetchone()[0]
    return {
        "records": records,
        "primary_records": primary_records,
        "excluded_contig_records": records - primary_records,
        "positions": positions,
        "variants": variants,
        "matchable_snv_variants": snvs,
    }


def _ratios(
    reference: Mapping[str, int] | None, chip: Mapping[str, int], overlap: Mapping[str, Any] | None
) -> dict[str, Any]:
    pairs = {
        "reference_position_coverage": (
            None if overlap is None else overlap["positions"],
            None if reference is None else reference["positions"],
        ),
        "chip_position_annotation_share": (
            None if overlap is None else overlap["positions"],
            chip["positions"],
        ),
    }
    return {
        name: {"numerator": n, "denominator": d, "fraction": None if n is None or not d else n / d}
        for name, (n, d) in pairs.items()
    }


def measure_coverage(
    table: GenotypeTable, lookup: ClinVarLookup, index: ClinVarIndex | None
) -> dict[str, Any]:
    """Compute once. Missing source remains unknown; malformed/empty input fails."""
    frame = table.frame
    # The table wrapper checks dtypes, not nullability or allele consistency.
    if (
        not frame.height
        or frame.select(
            pl.any_horizontal(pl.col("rsid", "chrom", "pos_grch37", "call_status").is_null())
        )
        .to_series()
        .any()
    ):
        raise ClinVarError("ClinVar coverage requires a complete normalized input table")
    for row in frame.iter_rows(named=True):
        no_call = row["call_status"] == CallStatus.NO_CALL
        if (
            not row["rsid"]
            or not row["pos_grch37"]
            or (no_call and any(row[k] is not None for k in ("a1", "a2", "genotype")))
            or (
                not no_call
                and (
                    row["a1"] not in {"A", "C", "G", "T", "I", "D"}
                    or row["a2"] not in {"A", "C", "G", "T", "I", "D"}
                    or row["genotype"] != "".join(sorted((row["a1"], row["a2"])))
                )
            )
        ):
            raise ClinVarError("ClinVar coverage input has inconsistent normalized calls")
    grouped = (
        frame.group_by("chrom", "pos_grch37", maintain_order=True)
        .agg(pl.struct("rsid", "a1", "a2", "genotype", "call_status").alias("probes"))
        .to_dicts()
    )
    sex = infer_sex(table, heterozygosity(table)).inferred.value
    chip = _chip_counts(grouped, sex)
    reference = None
    overlap = None
    if index is not None:
        if lookup.status != "complete" or lookup.provenance != index.provenance:
            raise ClinVarError("ClinVar coverage and lookup reference identities disagree")
        try:
            reference = _reference_counts(index)
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise ClinVarError("ClinVar coverage reference is malformed or unreadable") from exc
        overlap = _overlap_counts(list(lookup.loci), sex)  # type: ignore[arg-type]
    status = (
        "not_run"
        if reference is None
        else "empty_reference"
        if not reference["positions"]
        else "zero_overlap"
        if not overlap or not overlap["positions"]
        else "complete"
    )
    result = {
        "schema_version": 1,
        "source": SOURCE,
        "status": status,
        "policy": dict(POLICY),
        "notice": NOTICE,
        "provenance": lookup.provenance,
        "reference_counts": reference,
        "chip_counts": chip,
        "overlap_counts": overlap,
        "qc_inferred_sex": sex,
        "ratios": _ratios(reference, chip, overlap),
    }
    validate_coverage(result)
    return result


def _counts(raw: Any, keys: set[str]) -> None:
    if (
        not isinstance(raw, dict)
        or set(raw) != keys
        or any(type(v) is not int or v < 0 for k, v in raw.items() if k != "record_states")
    ):
        raise ValueError


def _validate_chip(raw: Any, keys: set[str]) -> None:
    _counts(raw, keys)
    if (
        sum(raw[s] for s in STATES) != raw["positions"]
        or raw["markers"] != raw["positions"] + raw["extra_probes"]
        or raw["duplicate_positions"] > min(raw["positions"], raw["extra_probes"])
        or (raw["extra_probes"] > 0) != (raw["duplicate_positions"] > 0)
        or not raw["positions"] - raw["no_call"] - raw["conflicting_probes"]
        <= raw["called_positions"]
        <= raw["positions"] - raw["no_call"]
    ):
        raise ValueError


def validate_coverage(data: Mapping[str, Any]) -> None:
    """Check saved arithmetic/provenance without reading a genome or current cache."""
    from genetics.health.clinvar import PROVENANCE_KEYS, STATUSES

    try:
        if (
            set(data)
            != {
                "schema_version",
                "source",
                "status",
                "policy",
                "notice",
                "provenance",
                "reference_counts",
                "chip_counts",
                "overlap_counts",
                "qc_inferred_sex",
                "ratios",
            }
            or type(data["schema_version"]) is not int
            or data["schema_version"] != 1
            or data["source"] != SOURCE
            or data["qc_inferred_sex"] not in {"male", "female", "ambiguous"}
            or data["policy"] != POLICY
            or not isinstance(data["notice"], str)
            or not data["notice"]
        ):
            raise ValueError
        chip, reference, overlap = (
            data["chip_counts"],
            data["reference_counts"],
            data["overlap_counts"],
        )
        _validate_chip(chip, CHIP_KEYS)
        if chip["positions"] == 0:
            raise ValueError
        if reference is None:
            if data["status"] != "not_run" or overlap is not None or data["provenance"] is not None:
                raise ValueError
        else:
            _counts(reference, REFERENCE_KEYS)
            provenance = data["provenance"]
            if (
                not isinstance(provenance, dict)
                or set(provenance) != PROVENANCE_KEYS
                or provenance["records"] != reference["records"]
                or reference["records"] == 0
                or reference["primary_records"] + reference["excluded_contig_records"]
                != reference["records"]
                or reference["positions"] > reference["primary_records"]
                or (reference["positions"] == 0) != (reference["primary_records"] == 0)
                or reference["matchable_snv_variants"] > reference["primary_records"]
                or reference["matchable_snv_variants"] > reference["variants"]
            ):
                raise ValueError
            # Reuse the historical lookup's source-provenance validator.
            from genetics.health.clinvar import validate_lookup

            validate_lookup(
                {
                    "schema_version": 1,
                    "status": "complete",
                    "reason": "",
                    "notice": data["notice"],
                    "provenance": provenance,
                    "loci": [],
                    "counts": {
                        "sample_markers": 0,
                        "sample_loci": 0,
                        "overlapping_loci": 0,
                        "reference_absent_loci": 0,
                        "overlapping_records": 0,
                        **{s: 0 for s in STATUSES},
                    },
                }
            )
            _validate_chip(overlap, OVERLAP_KEYS)
            _counts(overlap["record_states"], set(STATUSES))
            if (
                any(overlap[k] > chip[k] for k in CHIP_KEYS)
                or overlap["positions"] > reference["positions"]
                or overlap["records"] > reference["primary_records"]
                or overlap["records"] < overlap["positions"]
                or sum(overlap["record_states"].values()) != overlap["records"]
                or overlap["variants"] > reference["variants"]
                or not overlap["allele_resolved_positions"] <= overlap["called_snp"]
                or not overlap["allele_resolved_positions"]
                <= overlap["allele_resolved_variants"]
                <= min(overlap["variants"], reference["matchable_snv_variants"])
                or overlap["allele_resolved_variants"]
                != overlap["alternate_observed_variants"] + overlap["reference_only_variants"]
                or overlap["alternate_observed_variants"]
                > overlap["record_states"]["alternate_observed"]
                or overlap["reference_only_variants"] > overlap["record_states"]["reference_only"]
                or overlap["strand_unresolved_records"]
                > overlap["record_states"]["alternate_observed"]
                + overlap["record_states"]["reference_only"]
            ):
                raise ValueError
            status = (
                "empty_reference"
                if not reference["positions"]
                else "zero_overlap"
                if not overlap["positions"]
                else "complete"
            )
            if data["status"] != status:
                raise ValueError
        expected = _ratios(reference, chip, overlap)
        if data["ratios"] != expected:
            raise ValueError
        for ratio in data["ratios"].values():
            for key in ("numerator", "denominator"):
                if ratio[key] is not None and type(ratio[key]) is not int:
                    raise ValueError
            if ratio["fraction"] is not None and type(ratio["fraction"]) is not float:
                raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ClinVarError("Saved ClinVar coverage is malformed or inconsistent") from exc


def validate_coverage_lookup(raw: Mapping[str, Any]) -> None:
    from genetics.health.clinvar import validate_lookup

    try:
        base = dict(raw)
        coverage = base.pop("coverage")
        version = base.pop("lookup_schema_version")
        if type(version) is not int or version not in {1, 2, 3, 4}:
            raise ValueError
        base["schema_version"] = version
        validate_lookup(base)
        validate_coverage(coverage)
        if coverage["provenance"] != base["provenance"]:
            raise ValueError
        if base["status"] == "complete":
            overlap = coverage["overlap_counts"]
            actual = _overlap_counts(base["loci"], coverage["qc_inferred_sex"])
            if overlap != actual or any(
                coverage["chip_counts"][k] != base["counts"][v]
                for k, v in (("markers", "sample_markers"), ("positions", "sample_loci"))
            ):
                raise ValueError
        elif coverage["status"] != "not_run":
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ClinVarError("Saved ClinVar coverage/lookup relationship is inconsistent") from exc


def coverage_summary(data: Mapping[str, Any]) -> str:
    if data["status"] == "not_run":
        return "ClinVar reference unavailable; coverage is unknown. " + NOTICE
    parts = []
    for name, label in (
        ("reference_position_coverage", "ClinVar reference positions covered"),
        ("chip_position_annotation_share", "Chip positions annotated by ClinVar"),
    ):
        ratio = data["ratios"][name]
        fraction = (
            "undefined (empty denominator)"
            if ratio["fraction"] is None
            else f"{ratio['fraction']:.2%}"
        )
        parts.append(f"{label}: {ratio['numerator']:,}/{ratio['denominator']:,} ({fraction}).")
    overlap = data["overlap_counts"]
    parts.append(
        f"{overlap['called_positions']:,} overlapping positions have a call; "
        f"{overlap['allele_resolved_positions']:,} positions and "
        f"{overlap['allele_resolved_variants']:,} REF/ALT variants are allele-resolved."
    )
    return " ".join(parts) + " " + NOTICE


def coverage_reliability(data: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "tier": "limited" if data is not None and data["status"] != "not_run" else None,
        "inputs": {
            "reference_available": data is not None and data["reference_counts"] is not None,
            "clinical_sensitivity_estimated": False,
            "directly_typed_only": True,
        },
        "reason": "Descriptive counts under declared rules; no calibrated clinical sensitivity. "
        + NOTICE,
    }


def assemble_coverage_card(
    card: Card, data: Mapping[str, Any] | None, *, reason: str | None = None
) -> AssembledCard:
    if card.kind is not CardKind.COMPUTED or card.computation != SOURCE:
        raise ClinVarError("Coverage assembly requires the declared coverage card")
    if data is not None and reason is not None:
        raise ClinVarError("Measured coverage cannot carry a separate not-run reason")
    if data is not None:
        validate_coverage(data)
    status = (
        MatchStatus.NOT_RUN if data is None or data["status"] == "not_run" else MatchStatus.COMPUTED
    )
    summary = (
        coverage_summary(data)
        if data is not None
        else (reason or "ClinVar coverage was not recorded.")
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
        match=MatchResult(card.id, status, summary),
        observation=None,
        confidence=None,
        frequencies=(),
        confidence_frequency=None,
        citations=card.citations,
        authored_caveats=card.caveats,
        computed_caveats=(NOTICE,),
        computation={
            "source": SOURCE,
            "status": status.value,
            "reason": summary if data is None else None,
            "result": None if data is None else json.loads(json.dumps(data)),
            "reliability": coverage_reliability(data),
            "method_evidence": dict(card.method_evidence or {}),
        },
    )
