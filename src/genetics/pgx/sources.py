"""Versioned, source-bound PGx reference ingestion and offline validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from genetics.pgx.archives import HEADERS, MEMBERS, read_archive
from genetics.pgx.sql import REQUIRED, Row, Tables, read_dump
from genetics.refs import licenses, postprocess
from genetics.refs.manifest import PostProcess, Source
from genetics.refs.postprocess import ProcessError, ProcessResult, ProcessStatus

VERSION = 1


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "filename": path.name,
        "sha256": postprocess._sha256(path),
        "size_bytes": path.stat().st_size,
    }


def validate_identity(source: Any, source_id: str) -> None:
    if (
        not isinstance(source, dict)
        or source.get("id") != source_id
        or not isinstance(source.get("version"), str)
        or not source["version"]
        or not isinstance(source.get("license_id"), str)
        or not isinstance(source.get("files"), list)
        or not source["files"]
    ):
        raise ProcessError("PGx source identity is incomplete.")
    licenses.get(source["license_id"])
    seen = set()
    for file in source["files"]:
        if (
            not isinstance(file, dict)
            or not isinstance(file.get("filename"), str)
            or not file["filename"]
            or any(c in file["filename"] for c in "\\/:\x00")
            or file["filename"] in {".", ".."}
            or file["filename"] in seen
            or not isinstance(file.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", file["sha256"]) is None
            or type(file.get("size_bytes")) is not int
            or file["size_bytes"] <= 0
        ):
            raise ProcessError("PGx source file identity is malformed.")
        seen.add(file["filename"])


def validate_archive_metadata(archive: Any) -> None:
    if (
        not isinstance(archive, dict)
        or archive.get("filename") not in MEMBERS
        or archive.get("license_id") not in {"CC-BY-SA-4.0", "CC-BY-NC-SA-4.0"}
        or not isinstance(archive.get("license_notice"), str)
        or not isinstance(archive.get("created"), str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}", archive["created"]) is None
        or not isinstance(archive.get("release_notice"), str)
        or (archive.get("versions") is not None and not isinstance(archive["versions"], str))
    ):
        raise ProcessError("Malformed ClinPGx archive release/license metadata.")
    expected_url = "by-nc-sa" if archive["license_id"] == "CC-BY-NC-SA-4.0" else "by-sa"
    if f"creativecommons.org/licenses/{expected_url}/4.0/" not in archive["license_notice"]:
        raise ProcessError("ClinPGx archive license notice disagrees with classification.")


def _unique(tables: Tables, table: str, key: str = "id") -> dict[str, Row]:
    result: dict[str, Row] = {}
    for row in tables[table]:
        value = row[key]
        if value is None or value in result or not value:
            raise ProcessError(f"CPIC {table}: absent or duplicate primary key.")
        result[value] = row
    return result


def object_field(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "null")
        if not isinstance(parsed, dict):
            raise ValueError
        digest(parsed)  # Reject NaN/Infinity even in nested objects.
        return parsed
    except (ValueError, TypeError) as exc:
        raise ProcessError("CPIC lookup key must be a finite JSON object.") from exc


def validate_tables(tables: Any) -> None:
    if not isinstance(tables, dict) or set(tables) != set(REQUIRED):
        raise ProcessError("CPIC reference table coverage is incomplete.")
    for table, columns in REQUIRED.items():
        rows = tables[table]
        if not isinstance(rows, list):
            raise ProcessError("CPIC table must contain rows.")
        shape: set[str] | None = None
        for row in rows:
            if (
                not isinstance(row, dict)
                or not set(columns) <= set(row)
                or any(
                    not isinstance(k, str) or (v is not None and not isinstance(v, str))
                    for k, v in row.items()
                )
                or (shape is not None and shape != set(row))
            ):
                raise ProcessError(f"CPIC {table}: malformed source row.")
            shape = set(row)
            for column in (
                "version",
                "id",
                "position",
                "alleledefinitionid",
                "locationid",
                "definitionid",
                "phenotypeid",
                "functionphenotypeid",
            ):
                if column in row and (
                    row[column] is None or re.fullmatch(r"[1-9]\d*", row[column] or "") is None
                ):
                    raise ProcessError(f"CPIC {table}: invalid integer identity/version.")
            for column in ("matchesreferencesequence", "structuralvariation"):
                if column in row and row[column] not in {"t", "f"}:
                    raise ProcessError("CPIC definition boolean is missing or malformed.")
    genes = _unique(tables, "gene", "symbol")
    definitions = _unique(tables, "allele_definition")
    locations = _unique(tables, "sequence_location")
    results = _unique(tables, "gene_result")
    lookups = _unique(tables, "gene_result_lookup")
    for table in (
        "allele",
        "gene_result_diplotype",
        "publication",
        "guideline",
        "recommendation",
        "term",
        "file_artifact",
    ):
        _unique(tables, table)
    _unique(tables, "drug", "drugid")
    _unique(tables, "pair", "pairid")
    for table in ("allele_definition", "sequence_location", "allele", "gene_result", "pair"):
        if any(row["genesymbol"] not in genes for row in tables[table]):
            raise ProcessError(f"CPIC {table}: dangling gene reference.")
    for row in tables["allele"]:
        definition = definitions.get(row["definitionid"] or "")
        if definition is None or definition["genesymbol"] != row["genesymbol"]:
            raise ProcessError("CPIC allele function has an inconsistent definition join.")
    seen_values: set[tuple[str | None, str | None]] = set()
    for row in tables["allele_location_value"]:
        definition = definitions.get(row["alleledefinitionid"] or "")
        location = locations.get(row["locationid"] or "")
        marker_key = (row["alleledefinitionid"], row["locationid"])
        if (
            definition is None
            or location is None
            or definition["genesymbol"] != location["genesymbol"]
            or marker_key in seen_values
            or not row["variantallele"]
        ):
            raise ProcessError("CPIC definition marker has a dangling/conflicting join.")
        seen_values.add(marker_key)
    for row in lookups.values():
        if row["phenotypeid"] not in results:
            raise ProcessError("CPIC function lookup has a dangling phenotype.")
        object_field(row["lookupkey"])
    for row in tables["gene_result_diplotype"]:
        lookup = lookups.get(row["functionphenotypeid"] or "")
        if lookup is None:
            raise ProcessError("CPIC diplotype has a dangling function lookup.")
        result = results[lookup["phenotypeid"] or ""]
        key = object_field(row["diplotypekey"])
        result_gene = result["genesymbol"]
        if not isinstance(result_gene, str) or set(key) != {result_gene}:
            raise ProcessError("CPIC diplotype and phenotype genes disagree.")
        # Source counts may be haploid, diploid or copy-number dependent. Do not
        # reinterpret their sum as biological sample ploidy.
        alleles = key[result_gene]
        if (
            not isinstance(alleles, dict)
            or not alleles
            or any(
                not isinstance(a, str) or not a or type(n) is not int or n < 1
                for a, n in alleles.items()
            )
        ):
            raise ProcessError("CPIC diplotype key has malformed allele counts.")


def _same_tables(left: Tables, right: Tables) -> bool:
    return all(
        Counter(digest(row) for row in left[t]) == Counter(digest(row) for row in right[t])
        for t in REQUIRED
    )


def validate_source(payload: Mapping[str, Any]) -> int:
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != VERSION:
        raise ProcessError("Unsupported PGx source schema.")
    kind = payload.get("kind")
    if kind not in {"pgx_cpic", "pgx_annotations"}:
        raise ProcessError("Unknown PGx reference kind.")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise ProcessError("PGx source identity is incomplete.")
    validate_identity(source, "cpic" if kind == "pgx_cpic" else "pharmgkb")
    files = source["files"]
    seen = {file["filename"] for file in files}
    if kind == "pgx_cpic":
        validate_tables(payload.get("tables"))  # Any is checked at the boundary above.
        if payload.get("encodings_agree") is not True or len(files) != 2:
            raise ProcessError("CPIC reference lacks independent dump agreement.")
        rows = sum(len(table) for table in payload["tables"].values())
    else:
        archives = payload.get("archives")
        if (
            not isinstance(archives, list)
            or {a.get("filename") for a in archives if isinstance(a, dict)} != set(MEMBERS)
            or len(archives) != len(MEMBERS)
        ):
            raise ProcessError("ClinPGx reference archive coverage is incomplete.")
        rows = 0
        for archive in archives:
            validate_archive_metadata(archive)
            tables, columns = archive.get("tables"), archive.get("columns")
            if (
                not isinstance(tables, dict)
                or not isinstance(columns, dict)
                or set(tables) != set(MEMBERS[archive["filename"]])
                or set(columns) != set(tables)
            ):
                raise ProcessError("ClinPGx reference table coverage changed.")
            for name, data in tables.items():
                header = columns[name]
                if (
                    not isinstance(header, list)
                    or any(not isinstance(c, str) or not c for c in header)
                    or len(set(header)) != len(header)
                    or not set(HEADERS[name]) <= set(header)
                ):
                    raise ProcessError("Malformed ClinPGx reference columns.")
                if not isinstance(data, list) or any(
                    not isinstance(r, dict)
                    or set(r) != set(header)
                    or any(not isinstance(v, str) for v in r.values())
                    for r in data
                ):
                    raise ProcessError("Malformed ClinPGx reference rows.")
                rows += len(data)
        if seen != set(MEMBERS):
            raise ProcessError("ClinPGx source file set disagrees with archives.")
    if type(payload.get("rows")) is not int or payload["rows"] != rows:
        raise ProcessError("PGx reference row count is inconsistent.")
    return rows


def load_source(path: Path, *, expected: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ProcessError("PGx reference must be an object.")
        rows = validate_source(payload)
        step = (
            "parse_cpic_database" if payload["kind"] == "pgx_cpic" else "parse_pharmgkb_annotations"
        )
        provenance = postprocess.validate_provenance(
            path,
            expected=expected,
            expected_step=step,
            expected_transform_version=1,
            actual_rows=rows,
        )
        if (
            type(provenance.get("schema_version")) is not int
            or type(provenance.get("rows")) is not int
            or type(provenance.get("transform_version")) is not int
            or any(
                provenance.get(k) != payload["source"][field]
                for k, field in (
                    ("source_id", "id"),
                    ("source_version", "version"),
                    ("license_id", "license_id"),
                )
            )
        ):
            raise ProcessError("PGx source labels disagree with publication provenance.")
        if provenance["input"]["sha256"] != digest(payload["source"]["files"]):
            raise ProcessError("PGx reference source files disagree with provenance.")
        return payload
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ProcessError(f"Cannot validate PGx reference {path.name}: {exc}") from exc


def expected_provenance(
    declared: PostProcess, source: Source, records: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        **postprocess._expected_provenance(
            declared,
            Path(records[0]["filename"]),
            digest(records),
            input_filename="PGx complete source file set",
        ),
        "source_id": source.id,
        "source_version": source.version,
        "license_id": source.license.id,
    }


def run_ingestion(
    declared: PostProcess,
    source: Source,
    source_dir: Path,
    *,
    verify_only: bool,
    input_digests: Mapping[str, str] | None,
) -> ProcessResult:
    from genetics.pgx.locking import publication_lock

    output = postprocess._inside(source_dir, declared.params["output"], label="output")
    if verify_only:
        return _run_ingestion(
            declared, source, source_dir, verify_only=True, input_digests=input_digests
        )
    with publication_lock(output):
        return _run_ingestion(
            declared, source, source_dir, verify_only=False, input_digests=input_digests
        )


def _run_ingestion(
    declared: PostProcess,
    source: Source,
    source_dir: Path,
    *,
    verify_only: bool,
    input_digests: Mapping[str, str] | None,
) -> ProcessResult:
    output_name = str(declared.params["output"])
    output = postprocess._inside(source_dir, output_name, label="output")
    if output.suffix != ".json" or output_name in {f.filename for f in source.files}:
        raise ProcessError("PGx output must be a separate JSON reference artifact.")
    records: list[dict[str, Any]] = []
    inputs: list[Path] = []
    for remote in sorted(source.files, key=lambda f: f.filename):
        path = postprocess._inside(source_dir, remote.filename, label="input")
        record = file_record(path)
        if input_digests is not None and record["sha256"] != input_digests.get(remote.filename):
            raise ProcessError("PGx input differs from the verified download.")
        records.append(record)
        inputs.append(path)
    expected = expected_provenance(declared, source, records)
    if output.is_file():
        try:
            load_source(output, expected=expected)
        except ProcessError:
            if verify_only:
                raise
        else:
            return ProcessResult(
                declared.step,
                ProcessStatus.VERIFIED if verify_only else ProcessStatus.ALREADY_PRESENT,
                output_name,
                postprocess._artifact_rows(output),
            )
    if verify_only:
        return ProcessResult(
            declared.step,
            ProcessStatus.PENDING,
            output_name,
            detail="PGx reference not built; run refs fetch for this source.",
        )
    payload: dict[str, Any] = {
        "schema_version": VERSION,
        "source": {
            "id": source.id,
            "version": source.version,
            "license_id": source.license.id,
            "files": records,
        },
    }
    if declared.step == "parse_cpic_database":
        copy = [p for p in inputs if not p.name.endswith("_inserts.sql.gz")]
        inserts = [p for p in inputs if p.name.endswith("_inserts.sql.gz")]
        if len(copy) != 1 or len(inserts) != 1:
            raise ProcessError("CPIC requires one COPY and one inserts dump.")
        tables = read_dump(copy[0], mode="copy")
        other = read_dump(inserts[0], mode="inserts")
        validate_tables(tables)
        validate_tables(other)
        if not _same_tables(tables, other):
            raise ProcessError("CPIC COPY and inserts dumps disagree.")
        payload.update(
            kind="pgx_cpic",
            tables=tables,
            encodings_agree=True,
            rows=sum(len(t) for t in tables.values()),
        )
    else:
        if {p.name for p in inputs} != set(MEMBERS):
            raise ProcessError("ClinPGx ingestion requires its complete archive set.")
        archives = [read_archive(p) for p in inputs]
        payload.update(
            kind="pgx_annotations",
            archives=archives,
            rows=sum(len(t) for a in archives for t in a["tables"].values()),
        )
    # Bind publication to the bytes actually parsed, including interrupted/replaced downloads.
    if records != [file_record(p) for p in inputs]:
        raise ProcessError("PGx source changed during ingestion.")
    rows = validate_source(payload)
    postprocess._write_json_atomic(output, payload)
    postprocess._write_provenance(output, expected, rows)
    load_source(output, expected=expected)
    return ProcessResult(declared.step, ProcessStatus.CREATED, output_name, rows)
