"""Position/allele ClinVar lookup (M7.1), with no clinical interpretation.

The index contains the entire public VCF, never a sample-selected subset. INFO is
preserved verbatim as a mapping. Multiallelic aggregate annotations are deliberately
not assigned to individual alternate alleles. Personal results live only in runs.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import polars as pl

from genetics.ingest.keys import LocusKey, VariantKey
from genetics.ingest.schema import CallStatus, Chrom, GenotypeTable
from genetics.paths import references_dir
from genetics.privacy import NoGenotypeRepr

SCHEMA_VERSION = 1
NOTICE = (
    "Reference lookup only. ClinVar classifications describe reference variants, not "
    "confirmed personal findings. Frequency-based reliability and clinical-risk "
    "interpretation have not been applied. This pipeline is not a clinical test."
)
STATUSES = frozenset(
    {"alternate_observed", "reference_only", "missing", "incompatible", "ambiguous", "excluded"}
)
PROVENANCE_KEYS = frozenset(
    {"source", "version", "build", "filename", "sha256", "index_schema_version", "records"}
)


class ClinVarError(ValueError):
    """Malformed reference or lookup record. Messages never quote sample calls."""


def _hashes(path: Path) -> tuple[str, str]:
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def _info(text: str, line: int) -> dict[str, str | bool]:
    result: dict[str, str | bool] = {}
    if text == ".":
        return result
    for field in text.split(";"):
        key, separator, value = field.partition("=")
        if not key or key in result or (separator and not value):
            raise ClinVarError(f"ClinVar line {line}: malformed or duplicate INFO field")
        result[key] = value if separator else True
    return result


def _parse_record(fields: list[str], line: int) -> dict[str, Any]:
    if len(fields) != 8:
        raise ClinVarError(f"ClinVar line {line}: expected eight VCF columns")
    chrom, position, identifier, ref, alt, quality, filters, info_text = fields
    canonical = "MT" if chrom == "M" else chrom
    # ClinVar also publishes GRCh37 alternate/unplaced contigs. Preserve these public
    # records, but never map their coordinates onto a sample's primary chromosomes.
    if canonical not in {c.value for c in Chrom} and not re.fullmatch(
        r"N[CTW]_\d+\.\d+", canonical
    ):
        raise ClinVarError(f"ClinVar line {line}: invalid chromosome or position") from None
    try:
        pos = int(position)
    except ValueError:
        raise ClinVarError(f"ClinVar line {line}: invalid chromosome or position") from None
    alts = alt.split(",")
    if (
        canonical == Chrom.PAR.value
        or pos <= 0
        or pos > 2**32 - 1
        or not identifier.isdigit()
        or not re.fullmatch("[ACGTN]+", ref)
        or any(not re.fullmatch(r"[ACGTN]+|\*|\.|<[A-Za-z0-9_:]+>", a) for a in alts)
        or len(set(alts)) != len(alts)
        or ref in alts
    ):
        raise ClinVarError(f"ClinVar line {line}: malformed variant record")
    info = _info(info_text, line)
    # Keep all annotation domains distinct. Somatic annotations and included-haplotype
    # classifications cannot be treated as a germline classification of this allele.
    return {
        "variation_id": identifier,
        "chrom": canonical,
        "pos_grch37": pos,
        "ref": ref,
        "alts": alts,
        "quality": quality,
        "filter": filters,
        "info": info,
    }


@dataclass(frozen=True)
class ClinVarLookup(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("status",)

    status: str
    reason: str
    provenance: Mapping[str, Any] | None
    counts: Mapping[str, int]
    loci: tuple[Mapping[str, Any], ...]

    @classmethod
    def not_run(cls, reason: str = "Pinned ClinVar GRCh37 VCF is not installed.") -> ClinVarLookup:
        return cls("not_run", reason, None, {}, ())

    def to_dict(self) -> dict[str, Any]:
        # A fresh nested copy: callers must not mutate a result by editing its export.
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "reason": self.reason,
            "notice": NOTICE,
            "provenance": self.provenance,
            "counts": dict(self.counts),
            "loci": list(self.loci),
        }
        return json.loads(json.dumps(payload))  # type: ignore[no-any-return]


@dataclass(frozen=True)
class ClinVarIndex:
    path: Path
    provenance: Mapping[str, Any]

    @classmethod
    def build(
        cls,
        vcf: Path,
        *,
        version: str,
        expected_sha256: str | None = None,
        expected_md5: str | None = None,
        output: Path | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> ClinVarIndex:
        """Validate the source and atomically build/reuse a reference-only SQLite index."""
        sha, md5 = _hashes(vcf)
        if (expected_sha256 and sha != expected_sha256) or (expected_md5 and md5 != expected_md5):
            raise ClinVarError("ClinVar VCF does not match its pinned checksum; verify references")
        destination = output or vcf.with_name("clinvar_lookup.sqlite")
        contract = {
            "source": "clinvar_grch37",
            "version": version,
            "build": "GRCh37",
            "filename": vcf.name,
            "sha256": sha,
            "index_schema_version": SCHEMA_VERSION,
        }
        sidecar = destination.with_name(destination.name + ".provenance.json")
        if destination.is_file() and sidecar.is_file():
            try:
                saved = json.loads(sidecar.read_text(encoding="utf-8"))
                if not isinstance(saved, dict):
                    raise ValueError
                provenance = saved["provenance"]
                if all(provenance.get(k) == v for k, v in contract.items()):
                    if _hashes(destination)[0] != saved["index_sha256"]:
                        raise ClinVarError(
                            "ClinVar lookup index checksum mismatch; rebuild the index"
                        )
                    return cls(destination, provenance)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ClinVarError(
                    "ClinVar lookup index has invalid provenance; rebuild it"
                ) from exc
        if progress:
            progress("Building ClinVar reference lookup index")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + f".building-{uuid.uuid4().hex}")
        temporary_sidecar = temporary.with_name(temporary.name + ".json")
        count = 0
        try:
            with closing(sqlite3.connect(temporary)) as db, db:
                db.execute("CREATE TABLE variants (chrom TEXT, pos INTEGER, record TEXT)")
                header = False
                build = False
                source_date: str | None = None
                with gzip.open(vcf, "rt", encoding="utf-8") as handle:
                    for number, raw in enumerate(handle, 1):
                        line = raw.rstrip("\r\n")
                        if line.startswith("##"):
                            if header:
                                raise ClinVarError(
                                    f"ClinVar line {number}: metadata after column header"
                                )
                            build |= line == "##reference=GRCh37"
                            if line.startswith("##fileDate="):
                                source_date = line.split("=", 1)[1]
                            continue
                        if line.startswith("#"):
                            if header or line != "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO":
                                raise ClinVarError(f"ClinVar line {number}: invalid column header")
                            if not build or source_date != version:
                                raise ClinVarError(
                                    "ClinVar build or release date differs from its contract"
                                )
                            header = True
                            continue
                        if not header:
                            raise ClinVarError("ClinVar VCF lacks its validated GRCh37 header")
                        record = _parse_record(line.split("\t"), number)
                        db.execute(
                            "INSERT INTO variants VALUES (?, ?, ?)",
                            (record["chrom"], record["pos_grch37"], json.dumps(record)),
                        )
                        count += 1
                        if count % 100_000 == 0 and progress:
                            progress(f"Indexed {count:,} public ClinVar records")
                if not header or count == 0:
                    raise ClinVarError("ClinVar VCF is empty or lacks a column header")
                db.execute("CREATE INDEX loci ON variants (chrom, pos)")
            provenance = {**contract, "records": count}
            temporary_sidecar.write_text(
                json.dumps({"provenance": provenance, "index_sha256": _hashes(temporary)[0]}),
                encoding="utf-8",
            )
            os.replace(temporary, destination)
            os.replace(temporary_sidecar, sidecar)
        except (OSError, EOFError, UnicodeError, sqlite3.Error) as exc:
            raise ClinVarError("ClinVar reference index could not be built") from exc
        finally:
            temporary.unlink(missing_ok=True)
            temporary_sidecar.unlink(missing_ok=True)
        return cls(destination, provenance)

    def lookup(self, table: GenotypeTable) -> ClinVarLookup:
        """Join by locus, then require observed alleles compatible with REF/ALT.

        Results retain every overlapping record, including exclusions and conflicts.
        Loci absent from ClinVar are counted explicitly, rather than saved as hundreds
        of thousands of empty rows. Duplicate probes cannot pick a preferred genotype.
        """
        # The temporary sample table is memory-only. No sample coordinates enter the index.
        grouped = table.frame.group_by("chrom", "pos_grch37", maintain_order=True).agg(
            pl.struct("rsid", "a1", "a2", "genotype", "call_status").alias("probes")
        )
        loci: list[Mapping[str, Any]] = []
        statuses: Counter[str] = Counter()
        try:
            with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)) as db:
                db.execute("PRAGMA temp_store=MEMORY")
                db.execute("CREATE TEMP TABLE sample_loci (chrom TEXT, pos INTEGER)")
                db.executemany(
                    "INSERT INTO sample_loci VALUES (?, ?)",
                    grouped.select("chrom", "pos_grch37").iter_rows(),
                )
                records_by_locus: dict[LocusKey, list[dict[str, Any]]] = {}
                for chrom, pos, record_text in db.execute(
                    "SELECT v.chrom, v.pos, v.record FROM variants v "
                    "JOIN sample_loci s ON v.chrom=s.chrom AND v.pos=s.pos ORDER BY v.rowid"
                ):
                    key = LocusKey(Chrom(chrom), pos)
                    records_by_locus.setdefault(key, []).append(json.loads(record_text))
                for chrom, pos, probes in grouped.iter_rows():
                    key = LocusKey(Chrom(chrom), pos)
                    records = records_by_locus.get(key)
                    if records is None:
                        continue
                    evaluated = _match_records(key, probes, records)
                    for entry in evaluated:
                        statuses[entry["status"]] += 1
                    loci.append(
                        {"chrom": chrom, "pos_grch37": pos, "probes": probes, "records": evaluated}
                    )
        except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            raise ClinVarError("ClinVar lookup index is malformed or unreadable") from exc
        counts = {
            "sample_markers": table.n_markers,
            "sample_loci": grouped.height,
            "overlapping_loci": len(loci),
            "reference_absent_loci": grouped.height - len(loci),
            "overlapping_records": sum(statuses.values()),
            **{status: statuses[status] for status in sorted(STATUSES)},
        }
        return ClinVarLookup("complete", "", self.provenance, counts, tuple(loci))


def _match_record(
    key: LocusKey, probes: list[dict[str, Any]], record: dict[str, Any]
) -> dict[str, Any]:
    ref, alts = record["ref"], record["alts"]
    variant = VariantKey(key.chrom, key.pos_grch37, (ref, *alts))
    observations = {(p["genotype"], p["call_status"]) for p in probes}
    genotype, call_status = next(iter(observations))
    if len(observations) > 1:
        status, reason = "ambiguous", "Duplicate probes disagree in call or call status."
    elif call_status == CallStatus.NO_CALL:
        status, reason = "missing", "The overlapping locus has no call."
    elif call_status == CallStatus.HET_HAPLOID:
        status, reason = "ambiguous", "The call contradicts inferred single-copy ploidy."
    elif (
        genotype is None
        or any(a not in "ACGT" for a in genotype)
        or any(len(a) != 1 or a not in "ACGT" for a in variant.alleles)
    ):
        status, reason = "excluded", "Indel, symbolic or unresolved alleles are not matched."
    elif not set(genotype).issubset(variant.alleles):
        status, reason = (
            "incompatible",
            "Observed forward-strand alleles are incompatible with REF/ALT.",
        )
    elif len(alts) > 1:
        status, reason = (
            "ambiguous",
            "Multiallelic record: aggregate annotations are not assigned to an alternate.",
        )
    elif alts[0] in genotype:
        status, reason = (
            "alternate_observed",
            "Compatible alternate observed; reliability is not yet calibrated.",
        )
    else:
        status, reason = (
            "reference_only",
            "Compatible reference call; the annotated alternate was not observed.",
        )
    return {**record, "status": status, "reason": reason}


def _match_records(
    key: LocusKey, probes: list[dict[str, Any]], records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    multiplicity = Counter((r["ref"], tuple(sorted(r["alts"]))) for r in records)
    evaluated = [_match_record(key, probes, r) for r in records]
    for entry in evaluated:
        if multiplicity[(entry["ref"], tuple(sorted(entry["alts"])))] > 1 and entry["status"] in {
            "alternate_observed",
            "reference_only",
        }:
            entry["status"] = "ambiguous"
            entry["reason"] = (
                "Multiple source records describe this allele; all classifications are retained."
            )
    return evaluated


def lookup_default(
    table: GenotypeTable, *, progress: Callable[[str], None] | None = None
) -> ClinVarLookup:
    """Offline default stage: unavailable source is explicit; damaged source fails."""
    from genetics.refs.manifest import load

    source = load().get("clinvar_grch37")
    files = [item for item in source.files if item.filename.endswith(".vcf.gz") and item.pinned]
    if len(files) != 1:
        raise ClinVarError("ClinVar manifest must declare one pinned GRCh37 VCF")
    item = files[0]
    path = references_dir() / source.id / item.filename
    if not path.is_file():
        return ClinVarLookup.not_run()
    return ClinVarIndex.build(
        path,
        version=source.version,
        expected_sha256=item.sha256,
        expected_md5=item.md5,
        progress=progress,
    ).lookup(table)


def validate_lookup(raw: Mapping[str, Any]) -> None:
    """Validate a saved lookup without consulting today's reference data."""
    try:
        if set(raw) != {
            "schema_version",
            "status",
            "reason",
            "notice",
            "provenance",
            "counts",
            "loci",
        }:
            raise ValueError
        if type(raw["schema_version"]) is not int or raw["schema_version"] != SCHEMA_VERSION:
            raise ValueError
        if raw["status"] not in {"complete", "not_run"} or not isinstance(raw["reason"], str):
            raise ValueError
        if (
            not isinstance(raw["notice"], str)
            or not raw["notice"]
            or not isinstance(raw["counts"], dict)
            or not isinstance(raw["loci"], list)
        ):
            raise ValueError
        if raw["status"] == "not_run":
            if raw["provenance"] is not None or raw["counts"] or raw["loci"] or not raw["reason"]:
                raise ValueError
            return
        provenance = raw["provenance"]
        if not isinstance(provenance, dict) or set(provenance) != PROVENANCE_KEYS:
            raise ValueError
        if (
            provenance["source"] != "clinvar_grch37"
            or provenance["build"] != "GRCh37"
            or provenance["index_schema_version"] != SCHEMA_VERSION
            or type(provenance["index_schema_version"]) is not int
            or not isinstance(provenance["version"], str)
            or not provenance["version"]
            or not isinstance(provenance["filename"], str)
            or not re.fullmatch("[0-9a-f]{64}", provenance["sha256"])
            or type(provenance["records"]) is not int
            or provenance["records"] <= 0
        ):
            raise ValueError
        actual: Counter[str] = Counter()
        markers = 0
        seen: set[LocusKey] = set()
        for locus in raw["loci"]:
            if set(locus) != {"chrom", "pos_grch37", "probes", "records"}:
                raise ValueError
            key = LocusKey(Chrom(locus["chrom"]), locus["pos_grch37"])
            if type(key.pos_grch37) is not int or key.pos_grch37 <= 0 or key in seen:
                raise ValueError
            seen.add(key)
            probes = locus["probes"]
            if not isinstance(probes, list) or not probes:
                raise ValueError
            for p in probes:
                if set(p) != {"rsid", "a1", "a2", "genotype", "call_status"}:
                    raise ValueError
                if not isinstance(p["rsid"], str) or not p["rsid"]:
                    raise ValueError
                call_status = CallStatus(p["call_status"])
                if call_status is CallStatus.NO_CALL:
                    if any(p[k] is not None for k in ("a1", "a2", "genotype")):
                        raise ValueError
                elif any(p[k] not in {"A", "C", "G", "T", "I", "D"} for k in ("a1", "a2")) or p[
                    "genotype"
                ] != "".join(sorted((p["a1"], p["a2"]))):
                    raise ValueError
            markers += len(probes)
            if not isinstance(locus["records"], list) or not locus["records"]:
                raise ValueError
            parsed_records: list[dict[str, Any]] = []
            for entry in locus["records"]:
                if set(entry) != {
                    "variation_id",
                    "chrom",
                    "pos_grch37",
                    "ref",
                    "alts",
                    "quality",
                    "filter",
                    "info",
                    "status",
                    "reason",
                }:
                    raise ValueError
                if (
                    not isinstance(entry["alts"], list)
                    or any(not isinstance(a, str) for a in entry["alts"])
                    or not isinstance(entry["info"], dict)
                    or any(not isinstance(v, str) and v is not True for v in entry["info"].values())
                    or type(entry["pos_grch37"]) is not int
                    or not isinstance(entry["quality"], str)
                    or not isinstance(entry["filter"], str)
                ):
                    raise ValueError
                fields = [
                    entry["chrom"],
                    str(entry["pos_grch37"]),
                    entry["variation_id"],
                    entry["ref"],
                    ",".join(entry["alts"]),
                    entry["quality"],
                    entry["filter"],
                    ";".join(
                        k + ("=" + v if isinstance(v, str) else "")
                        for k, v in entry["info"].items()
                    )
                    or ".",
                ]
                record = _parse_record(fields, 0)
                if record["info"] != entry["info"]:
                    raise ValueError
                if record["chrom"] != key.chrom.value or record["pos_grch37"] != key.pos_grch37:
                    raise ValueError
                if not isinstance(entry["reason"], str) or not entry["reason"]:
                    raise ValueError
                parsed_records.append(record)
                actual[entry["status"]] += 1
            evaluated = _match_records(key, probes, parsed_records)
            if any(
                a["status"] != b["status"] for a, b in zip(evaluated, locus["records"], strict=True)
            ):
                raise ValueError
        counts = raw["counts"]
        expected_keys = {
            "sample_markers",
            "sample_loci",
            "overlapping_loci",
            "reference_absent_loci",
            "overlapping_records",
            *STATUSES,
        }
        if set(counts) != expected_keys or any(
            type(n) is not int or n < 0 for n in counts.values()
        ):
            raise ValueError
        if (
            counts["overlapping_loci"] != len(seen)
            or counts["sample_loci"] != counts["reference_absent_loci"] + len(seen)
            or counts["sample_markers"] < max(markers, counts["sample_loci"])
            or counts["overlapping_records"] != sum(actual.values())
            or counts["overlapping_records"] > provenance["records"]
            or any(counts[s] != actual[s] for s in STATUSES)
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ClinVarError("Saved ClinVar lookup is malformed or inconsistent") from exc
