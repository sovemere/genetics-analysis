"""Declared and executable post-download processing steps.

The manifest is the plan; this module is the executor.  A step is only marked
``implemented`` when :func:`run` has a real implementation, and fetch/verify both report
its output state.  Outputs are written beside the public source payload, through a
strict containment check, and promoted with ``os.replace`` only after validation.

Large tabular transforms use restartable Parquet chunks.  A killed process can leave a
chunk or final ``.part`` file, but never a file bearing the declared output name.  The
next run resumes after the last checkpoint and compacts the chunks atomically.  Seeking
inside gzip/bzip2 still requires decompression from the start, but completed rows are not
parsed or written again.

No step here reads a genotype export.  Outputs are derived solely from public reference
data and therefore stay under ``data/references``.  Future steps marked
``output_is_genotype_derived`` must instead be given a cache root outside the repository.
"""

from __future__ import annotations

import bz2
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TypeAlias

import polars as pl

if TYPE_CHECKING:
    from genetics.external.plink2 import Plink2
    from genetics.refs.manifest import PostProcess, Source


@dataclass(frozen=True)
class Step:
    """One named transformation a source may declare."""

    name: str
    summary: str
    required_params: tuple[str, ...] = ()
    optional_params: tuple[str, ...] = ()
    implemented: bool = False
    milestone: str = ""
    output_is_genotype_derived: bool = False
    transform_version: int = 1
    workspace_multiplier: float = 0.0


_STEPS: tuple[Step, ...] = (
    Step(
        name="verify_publisher_md5",
        summary="Check a payload against the publisher's separately fetched md5.",
        required_params=("md5_url",),
        milestone="M2.2",
    ),
    Step(
        name="extract_zip",
        summary="Unpack a zip archive into the source's directory.",
        optional_params=("members",),
        milestone="M2.2",
    ),
    Step(
        name="extract_tar",
        summary="Unpack a tar/tar.gz archive into the source's directory.",
        optional_params=("members",),
        milestone="M2.2",
    ),
    Step(
        name="subset_vcf_to_array_positions",
        summary="Stream a sites VCF into a lookup table for selected array/card loci.",
        required_params=("output",),
        optional_params=("info_fields",),
        milestone="M7.2",
        output_is_genotype_derived=True,
    ),
    Step(
        name="extract_rsid_merge_table",
        summary="Extract retired-to-current rsID mappings from dbSNP RefSNP JSON.",
        required_params=("input", "output", "unresolvable_output"),
        implemented=True,
        milestone="M2.3",
        workspace_multiplier=4.0,
    ),
    Step(
        name="extract_dbsnp_variant_index",
        summary="Extract current rsID, GRCh37 locus and alleles from the dbSNP VCF.",
        required_params=("input", "output"),
        implemented=True,
        milestone="M3.5",
        transform_version=2,
        workspace_multiplier=4.0,
    ),
    Step(
        name="extract_build_anchors",
        summary="Pair verified GRCh37/GRCh38 coordinates from ClinVar variant_summary.",
        required_params=("input", "output"),
        optional_params=("count",),
        implemented=True,
        milestone="M2.3",
        transform_version=2,
        workspace_multiplier=0.1,
    ),
    Step(
        name="build_pca_marker_subset",
        summary="Build the LD-pruned marker subset used for PCA projection.",
        required_params=("output",),
        optional_params=("maf", "max_missing", "window", "step", "r2"),
        implemented=True,
        milestone="M5.3",
        # Was True until M5.3 implemented it, and the change is a decision rather than a
        # correction of a typo. The flag means "this transform reads a genotype export",
        # which is what forces an output outside the checkout. The roadmap's phrasing --
        # "on array-overlapping markers" -- is what made that look true here: an array's
        # marker list has to come from somebody's export.
        #
        # This implementation does not take one. It prunes the *panel* and nothing else,
        # so the artifact is a function of public 1000 Genomes data alone and carries no
        # information about any user; the array intersection moves to the eigenvector
        # build, where an export is genuinely in hand. That also matches what the manifest
        # entry already said out loud -- "writing a separate PCA subset beside it is not
        # [forbidden]" -- and is the reading the two had to be reconciled to.
        #
        # If this step is ever given an array marker list, the flag goes back to True and
        # the output moves out of the repository with it.
        output_is_genotype_derived=False,
        # Per-chromosome filtered pgens, their pruned copies, and the merged result all
        # live in the work directory at once. Conservative on purpose: under-reporting the
        # disk a multi-hour transform needs is the expensive direction to be wrong in.
        workspace_multiplier=1.0,
    ),
    Step(
        name="convert_to_bref3",
        summary="Convert an imputation reference panel to Beagle's bref3 format.",
        required_params=("output",),
        milestone="M8.2",
    ),
    Step(
        name="parse_pgs_score_licenses",
        summary="Extract each PGS Catalog score's machine-readable terms of use.",
        required_params=("output",),
        milestone="M9.1",
    ),
)

STEPS: Final[dict[str, Step]] = {step.name: step for step in _STEPS}


class UnknownStepError(ValueError):
    """Raised for a post-processing step the registry does not define."""


class ProcessError(RuntimeError):
    """A declared transform could not produce a trustworthy output."""


class ProcessStatus(StrEnum):
    CREATED = "created"
    ALREADY_PRESENT = "already-present"
    VERIFIED = "verified"
    PENDING = "pending"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessResult:
    step: str
    status: ProcessStatus
    output: str | None = None
    rows: int | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status not in {ProcessStatus.FAILED}


@dataclass(frozen=True)
class ProcessProgressEvent:
    step: str
    processed_rows: int


ProcessProgressCallback = Callable[[ProcessProgressEvent], None]


def get(name: str) -> Step:
    """Look up a step, or raise :class:`UnknownStepError`."""
    try:
        return STEPS[name]
    except KeyError:
        known = ", ".join(sorted(STEPS))
        raise UnknownStepError(
            f"unknown post-processing step {name!r}. Define it in "
            f"genetics.refs.postprocess first. Known steps: {known}."
        ) from None


def estimated_workspace_bytes(source: Source) -> int:
    """Conservative scratch/output allowance for executable declared transforms."""
    sizes = {item.filename: item.size_bytes for item in source.files}
    total = 0
    for declared in source.post_process:
        definition = declared.definition
        if not definition.implemented:
            continue
        if "input" in declared.params:
            size = sizes.get(str(declared.params["input"]))
        else:
            # A step that names no input consumes the whole source; `build_pca_marker_subset`
            # reads all 22 autosomal VCFs. Falling through to `None` here reported a 16.75 GB
            # transform as needing no scratch space at all, which is the one answer that
            # cannot be right.
            known = [item.size_bytes for item in source.files if item.size_bytes is not None]
            size = sum(known) if known else None
        if size is not None:
            total += int(size * definition.workspace_multiplier)
    return total


_RSID = re.compile(r"rs[1-9][0-9]*\Z")
_CHROMS = (*tuple(str(n) for n in range(1, 23)), "X", "Y", "MT")
_CHROM_SET = frozenset(_CHROMS)
_PARQUET_CHUNK_ROWS = 250_000
_STATE_VERSION = 2
_PROVENANCE_VERSION = 2

PolarsType: TypeAlias = pl.DataType | type[pl.DataType]

VARIANT_INDEX_SCHEMA: Final[Mapping[str, PolarsType]] = {
    "rsid": pl.String,
    "chrom": pl.String,
    "pos_grch37": pl.UInt32,
    "ref": pl.String,
    "alts": pl.List(pl.String),
}
MERGE_TABLE_SCHEMA: Final[Mapping[str, PolarsType]] = {
    "retired_rsid": pl.String,
    "current_rsid": pl.String,
}
UNRESOLVABLE_MERGE_SCHEMA: Final[Mapping[str, PolarsType]] = {
    "retired_rsid": pl.String,
    "status": pl.String,
    "targets": pl.List(pl.String),
}
_MERGE_SOURCE_SCHEMA: Final[Mapping[str, PolarsType]] = {
    "retired_rsid": pl.String,
    "status": pl.String,
    "current_rsid": pl.String,
    "targets": pl.List(pl.String),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


_DIGEST_CACHE: dict[tuple[str, int, int], str] = {}
"""Per-process memo for artifact digests, keyed by path, size and mtime.

Verification hashes the *whole* artifact, and the artifacts here are the largest files the
project produces -- the dbSNP variant index runs to tens of gigabytes. Every resolver
lookup and every ``MergeTable.default()`` re-validates, so ``genetics cards lint`` was
hashing tens of GB to read thirty-one rows, and a matcher run did it twice more. The check
itself is not weakened: the first read in a process is a real hash, and any rewrite the
transform performs changes size or mtime and so misses the memo. What is dropped is
re-hashing bytes this process already read and nothing has touched since.
"""


def _cached_sha256(path: Path) -> str:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _DIGEST_CACHE.get(key)
    if cached is None:
        cached = _sha256(path)
        _DIGEST_CACHE[key] = cached
    return cached


def provenance_path(output: Path) -> Path:
    """Sidecar binding a derived reference artifact to its exact transform input."""
    return output.with_name(f"{output.name}.provenance.json")


def _expected_provenance(
    declared: PostProcess,
    input_path: Path,
    input_sha256: str,
    *,
    output_param: str = "output",
    input_filename: str | None = None,
) -> dict[str, Any]:
    """Build the contract a sidecar is checked against.

    ``input_filename`` overrides the name recorded for the input. It exists for
    ``build_pca_marker_subset``, whose input is 22 files rather than one: there the digest
    is taken over the ordered ``(name, sha256)`` list and the label names the set. The
    binding is the digest either way; the name is what a person reads.
    """
    definition = declared.definition
    # A JSON round trip rejects non-serializable params and gives a stable primitive tree.
    params = json.loads(json.dumps(dict(declared.params), sort_keys=True))
    return {
        "schema_version": _PROVENANCE_VERSION,
        "step": declared.step,
        "transform_version": definition.transform_version,
        "input": {
            "filename": input_filename if input_filename is not None else input_path.name,
            "sha256": input_sha256,
        },
        "params": params,
        # The basename, matching what :func:`_read_provenance` compares against. The
        # sidecar sits beside its artifact, so the directory is already established by
        # where the file is; recording the manifest-relative path here instead meant any
        # output with a directory component was written successfully and then rejected on
        # every subsequent read -- an artifact permanently reported FAILED for a mismatch
        # between two spellings of its own name.
        "output": Path(str(declared.params[output_param])).name,
    }


def declared_artifact_provenance(
    source_id: str,
    step_name: str,
    *,
    output_param: str = "output",
    output_name: str | None = None,
) -> dict[str, Any]:
    """Return the current manifest+lock contract for a default derived artifact.

    A provenance sidecar is self-consistent evidence, not an external authority: someone
    can copy an artifact and its perfectly valid sidecar from another release.  Default
    runtime consumers use this helper to bind that sidecar to the step parameters in the
    committed manifest and to the exact input SHA recorded by the committed lock.  Tests
    and explicit custom artifact APIs can continue validating generic self-provenance.
    """
    from genetics import paths
    from genetics.refs import lock as lockfile
    from genetics.refs import manifest as manifest_mod

    try:
        source = manifest_mod.load(paths.reference_manifest()).get(source_id)
        candidates = [
            declared
            for declared in source.post_process
            if declared.step == step_name
            and output_param in declared.params
            and (output_name is None or str(declared.params[output_param]) == output_name)
        ]
        if len(candidates) != 1:
            raise ProcessError(
                f"{source_id}: expected exactly one {step_name!r} declaration for "
                f"{output_param}={output_name!r}, found {len(candidates)}"
            )
        declared = candidates[0]
        input_name = str(declared.params["input"])
        remote = next((item for item in source.files if item.filename == input_name), None)
        if remote is None:
            raise ProcessError(
                f"{source_id}: declared input {input_name!r} is not a lock-pinned download"
            )

        locked = lockfile.read(paths.reference_lock())
        locked_source = locked.sources.get(source_id)
        if locked_source is None:
            raise ProcessError(
                f"{source_id}: manifest.lock has no source entry; run refs fetch first"
            )
        if locked_source.version != source.version:
            raise ProcessError(
                f"{source_id}: manifest.lock records version {locked_source.version!r}, "
                f"but manifest.yaml declares {source.version!r}"
            )
        locked_file = locked_source.files.get(input_name)
        if locked_file is None:
            raise ProcessError(
                f"{source_id}: manifest.lock has no digest for {input_name!r}; run refs fetch first"
            )
        if locked_file.url != remote.url:
            raise ProcessError(
                f"{source_id}: manifest.lock URL for {input_name!r} does not match manifest.yaml"
            )
        if remote.sha256 is not None and locked_file.sha256 != remote.sha256:
            raise ProcessError(
                f"{source_id}: locked SHA for {input_name!r} does not match manifest.yaml"
            )
    except ProcessError:
        raise
    except (OSError, ValueError) as exc:
        raise ProcessError(f"cannot establish declared provenance for {source_id}: {exc}") from exc

    source_dir = (paths.references_dir() / source_id).resolve()
    input_path = _inside(source_dir, input_name, label="input")
    return _expected_provenance(
        declared,
        input_path,
        locked_file.sha256,
        output_param=output_param,
    )


def _read_provenance(output: Path) -> dict[str, Any]:
    sidecar = provenance_path(output)
    try:
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProcessError(f"{sidecar.name}: missing or malformed artifact provenance") from exc
    if not isinstance(raw, dict):
        raise ProcessError(f"{sidecar.name}: artifact provenance must be an object")
    input_record = raw.get("input")
    input_filename = input_record.get("filename") if isinstance(input_record, dict) else None
    digest = input_record.get("sha256") if isinstance(input_record, dict) else None
    output_digest = raw.get("output_sha256")
    if (
        raw.get("schema_version") != _PROVENANCE_VERSION
        or not isinstance(raw.get("step"), str)
        or not isinstance(raw.get("transform_version"), int)
        or not isinstance(raw.get("params"), dict)
        or raw.get("output") != output.name
        or not isinstance(input_filename, str)
        or not input_filename
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(output_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", output_digest) is None
        or not isinstance(raw.get("rows"), int)
        or raw["rows"] < 0
    ):
        raise ProcessError(f"{sidecar.name}: incomplete artifact provenance")
    return raw


def _artifact_rows(output: Path) -> int:
    """Return the logical row count for a provenance-bearing artifact."""
    try:
        if output.suffix == ".parquet":
            return int(pl.scan_parquet(output).select(pl.len()).collect().item())
        if output.suffix == ".json":
            payload = json.loads(output.read_text(encoding="utf-8"))
            anchors = payload.get("anchors") if isinstance(payload, dict) else None
            if isinstance(anchors, list):
                return len(anchors)
        if output.suffix == ".pgen":
            # A pgen is opaque binary whose variant count lives in the companion .pvar, so
            # "rows" is read from there. That is not a workaround: it also means a .pvar
            # swapped for one of a different length fails provenance, which hashing the
            # .pgen alone would never notice.
            return _pvar_variants(_companion(output, ".pvar"))
    except (OSError, UnicodeError, json.JSONDecodeError, pl.exceptions.PolarsError) as exc:
        raise ProcessError(f"{output.name}: cannot count artifact rows ({exc})") from exc
    raise ProcessError(f"{output.name}: unsupported provenance-bearing artifact format")


def validate_provenance(
    output: Path,
    *,
    expected: Mapping[str, Any] | None = None,
    expected_step: str | None = None,
    expected_transform_version: int | None = None,
    actual_rows: int | None = None,
) -> dict[str, Any]:
    """Validate a sidecar against its artifact and optional manifest/input contract."""
    raw = _read_provenance(output)
    try:
        output_sha256 = _cached_sha256(output)
    except OSError as exc:
        raise ProcessError(f"{output.name}: cannot hash artifact ({exc})") from exc
    if raw["output_sha256"] != output_sha256:
        raise ProcessError(
            f"{provenance_path(output).name}: output digest does not match {output.name}"
        )
    rows = _artifact_rows(output) if actual_rows is None else actual_rows
    if raw["rows"] != rows:
        raise ProcessError(
            f"{provenance_path(output).name}: records {raw['rows']} row(s), "
            f"but {output.name} contains {rows}"
        )
    if expected_step is not None and raw["step"] != expected_step:
        raise ProcessError(
            f"{provenance_path(output).name}: expected step {expected_step!r}, "
            f"found {raw['step']!r}"
        )
    if (
        expected_transform_version is not None
        and raw["transform_version"] != expected_transform_version
    ):
        raise ProcessError(
            f"{provenance_path(output).name}: expected transform version "
            f"{expected_transform_version}, found {raw['transform_version']}"
        )
    if expected is not None:
        observed = {key: raw.get(key) for key in expected}
        if observed != dict(expected):
            raise ProcessError(
                f"{provenance_path(output).name}: artifact is stale for the current "
                "input, transform version, or parameters"
            )
    return raw


def _write_provenance(output: Path, expected: Mapping[str, Any], rows: int) -> None:
    _write_json_atomic(
        provenance_path(output),
        {
            **expected,
            "schema_version": _PROVENANCE_VERSION,
            "rows": rows,
            "output_sha256": _sha256(output),
        },
    )


def _inside(source_dir: Path, relative: object, *, label: str) -> Path:
    """Resolve a manifest path strictly inside its source directory."""
    text = str(relative)
    source_dir = source_dir.resolve()
    target = (source_dir / text).resolve()
    if source_dir not in target.parents:
        raise ProcessError(
            f"{label} {text!r} resolves to {target}, outside source directory {source_dir}"
        )
    return target


def _part_path(output: Path) -> Path:
    return output.with_name(f".{output.name}.part")


def _chunk_dir(output: Path) -> Path:
    return output.with_name(f".{output.name}.chunks")


def _validate_parquet(path: Path, schema: Mapping[str, PolarsType]) -> int:
    try:
        actual = pl.read_parquet_schema(path)
        expected = dict(schema)
        if actual != expected:
            raise ProcessError(
                f"{path.name}: schema is {dict(actual)}, expected {expected}; refusing "
                "to treat an incompatible artifact as complete"
            )
        return int(pl.scan_parquet(path).select(pl.len()).collect().item())
    except ProcessError:
        raise
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise ProcessError(f"{path.name}: unreadable Parquet output ({exc})") from exc


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    part = _part_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(part, path)


@dataclass(frozen=True)
class _Checkpoint:
    processed: int
    chunks: int
    input_complete: bool
    output_promoted: bool


def _read_state(
    staging: Path,
    input_path: Path,
    provenance: Mapping[str, Any] | None,
    schema: Mapping[str, PolarsType],
) -> _Checkpoint:
    state_path = staging / "state.json"
    if not state_path.is_file():
        if any(staging.iterdir()):
            raise ProcessError(
                f"{staging}: contains chunk work without a checkpoint; refusing to "
                "guess which records are durable"
            )
        return _Checkpoint(0, 0, False, False)
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        stat = input_path.stat()
        if raw.get("schema_version") != _STATE_VERSION:
            raise ProcessError("checkpoint schema version changed")
        if raw.get("input_size") != stat.st_size:
            raise ProcessError("input size changed")
        if raw.get("provenance") != provenance:
            raise ProcessError("input digest, transform version, or parameters changed")
        processed = int(raw["processed_records"])
        chunks = int(raw["chunks"])
        input_complete = raw["input_complete"]
        output_promoted = raw["output_promoted"]
        if processed < 0 or chunks < 0:
            raise ProcessError("negative checkpoint value")
        if not isinstance(input_complete, bool) or not isinstance(output_promoted, bool):
            raise ProcessError("checkpoint completion flags are malformed")
        if output_promoted and not input_complete:
            raise ProcessError("checkpoint promotes output before input completion")
        expected = {f"part-{n:08d}.parquet" for n in range(chunks)}
        actual = {p.name for p in staging.glob("part-*.parquet")}
        missing = expected - actual
        if missing:
            raise ProcessError(f"checkpoint chunk(s) are missing: {sorted(missing)}")
        chunk_rows = sum(_validate_parquet(staging / name, schema) for name in sorted(expected))
        if chunk_rows != processed:
            raise ProcessError(
                f"checkpoint records {processed} row(s), but its chunks contain {chunk_rows}"
            )
        # A kill between chunk promotion and checkpoint promotion leaves exactly this
        # shape. The checkpoint is authoritative, so those implementation-owned orphan
        # chunks are safe to discard and regenerate.
        for orphan in actual - expected:
            (staging / orphan).unlink()
        for orphan_part in staging.glob(".part-*.parquet.part"):
            orphan_part.unlink()
        return _Checkpoint(processed, chunks, input_complete, output_promoted)
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        ProcessError,
    ) as exc:
        raise ProcessError(
            f"{state_path}: cannot safely resume this transform ({exc}); remove the "
            "step's hidden chunk directory to rebuild it"
        ) from exc


def _checkpoint(
    staging: Path,
    input_path: Path,
    processed: int,
    chunks: int,
    provenance: Mapping[str, Any] | None,
    *,
    input_complete: bool = False,
    output_promoted: bool = False,
) -> None:
    stat = input_path.stat()
    _write_json_atomic(
        staging / "state.json",
        {
            "schema_version": _STATE_VERSION,
            "input_size": stat.st_size,
            "processed_records": processed,
            "chunks": chunks,
            "input_complete": input_complete,
            "output_promoted": output_promoted,
            "provenance": provenance,
        },
    )


def _cleanup_chunked_state(output: Path) -> None:
    """Remove only implementation-owned state after provenance is durable."""
    staging = _chunk_dir(output)
    if staging.is_dir():
        shutil.rmtree(staging)
    _part_path(output).unlink(missing_ok=True)


def _recover_promoted_output(
    output: Path,
    *,
    input_path: Path,
    schema: Mapping[str, PolarsType],
    provenance: Mapping[str, Any],
) -> int | None:
    """Finish provenance after a kill between output promotion and sidecar commit."""
    staging = _chunk_dir(output)
    if not output.is_file() or not staging.is_dir():
        return None
    try:
        checkpoint = _read_state(staging, input_path, provenance, schema)
        if not checkpoint.output_promoted:
            return None
        rows = _validate_parquet(output, schema)
        if rows != checkpoint.processed:
            return None
    except ProcessError:
        return None
    _write_provenance(output, provenance, rows)
    _cleanup_chunked_state(output)
    return rows


def _resume(records: Iterable[tuple[Any, ...]], processed: int) -> Iterator[tuple[Any, ...]]:
    iterator = iter(records)
    for seen in range(processed):
        try:
            next(iterator)
        except StopIteration:
            raise ProcessError(
                f"checkpoint claims {processed} records but input ended after {seen}"
            ) from None
    yield from iterator


def _write_chunked_parquet(
    records: Iterable[tuple[Any, ...]],
    *,
    input_path: Path,
    output: Path,
    schema: Mapping[str, PolarsType],
    chunk_rows: int = _PARQUET_CHUNK_ROWS,
    progress: ProcessProgressCallback | None = None,
    step_name: str = "post-process",
    provenance: Mapping[str, Any] | None = None,
    retain_staging: bool = False,
) -> int:
    """Write an iterable to Parquet with atomic chunks and a restart checkpoint."""
    if chunk_rows <= 0:
        raise ValueError("chunk_rows must be positive")
    staging = _chunk_dir(output)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        checkpoint = _read_state(staging, input_path, provenance, schema)
    except ProcessError:
        # Staging is private implementation state beside the declared output. A stale
        # checkpoint must never be resumed against a different public input.
        shutil.rmtree(staging)
        staging.mkdir(parents=True)
        checkpoint = _Checkpoint(0, 0, False, False)
    processed = checkpoint.processed
    chunk_number = checkpoint.chunks
    names = list(schema)
    batch: list[tuple[Any, ...]] = []

    def flush() -> None:
        nonlocal chunk_number
        if not batch:
            return
        final = staging / f"part-{chunk_number:08d}.parquet"
        part = _part_path(final)
        pl.DataFrame(batch, schema=schema, orient="row").write_parquet(part)
        _validate_parquet(part, schema)
        os.replace(part, final)
        chunk_number += 1
        _checkpoint(staging, input_path, processed, chunk_number, provenance)
        if progress is not None:
            progress(ProcessProgressEvent(step_name, processed))
        batch.clear()

    if not checkpoint.input_complete:
        for record in _resume(records, processed):
            if len(record) != len(names):
                raise ProcessError(
                    f"transform emitted {len(record)} values for {len(names)} columns"
                )
            batch.append(record)
            processed += 1
            if len(batch) >= chunk_rows:
                flush()
        flush()
        _checkpoint(
            staging,
            input_path,
            processed,
            chunk_number,
            provenance,
            input_complete=True,
        )

    chunks = sorted(staging.glob("part-*.parquet"))
    part_output = _part_path(output)
    part_output.unlink(missing_ok=True)
    if chunks:
        pl.scan_parquet(chunks).sink_parquet(part_output, maintain_order=True, mkdir=True)
    else:
        pl.DataFrame(schema=schema).write_parquet(part_output)
    rows = _validate_parquet(part_output, schema)
    if rows != processed:
        raise ProcessError(
            f"{output.name}: compacted {rows} rows but checkpoint records {processed}"
        )
    os.replace(part_output, output)
    _checkpoint(
        staging,
        input_path,
        processed,
        chunk_number,
        provenance,
        input_complete=True,
        output_promoted=True,
    )
    if not retain_staging:
        _cleanup_chunked_state(output)
    return rows


def _canonical_chrom(accession: str) -> str | None:
    stem = accession.partition(".")[0]
    if stem == "NC_012920":
        return "MT"
    if not stem.startswith("NC_"):
        return None
    try:
        number = int(stem[3:])
    except ValueError:
        return None
    if 1 <= number <= 22:
        return str(number)
    return {23: "X", 24: "Y"}.get(number)


def _vcf_records(path: Path) -> Iterator[tuple[str, str, int, str, list[str]]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.startswith("#"):
                continue
            fields = line.rstrip("\r\n").split("\t", 5)
            if len(fields) != 6:
                raise ProcessError(f"{path.name}: malformed VCF record at line {line_number}")
            accession, pos_text, rsid, ref, alt_text, _ = fields
            chrom = _canonical_chrom(accession)
            if chrom is None:
                continue
            if not _RSID.fullmatch(rsid):
                raise ProcessError(
                    f"{path.name}: non-current rsID field at line {line_number}; "
                    "the variant index cannot guess an identifier"
                )
            try:
                pos = int(pos_text)
            except ValueError:
                raise ProcessError(
                    f"{path.name}: non-integer VCF position at line {line_number}"
                ) from None
            if not 0 < pos < 2**32:
                raise ProcessError(f"{path.name}: invalid VCF position at line {line_number}")
            # VCF uses a lone ``.`` ALT to mean that no alternate allele is specified.
            # dbSNP includes such non-variant RefSNP placements in its release VCF; they
            # are valid VCF records, but cannot contribute an allele-bearing variant to
            # this index. A dot inside a comma-delimited ALT list is not that sentinel
            # and remains malformed, as does an actually empty field.
            if alt_text == ".":
                continue
            alts = alt_text.split(",")
            if not ref or any(not alt or alt == "." for alt in alts):
                raise ProcessError(f"{path.name}: empty allele at line {line_number}")
            yield rsid, chrom, pos, ref, alts


def _merge_records(path: Path) -> Iterator[tuple[str, str, str | None, list[str]]]:
    previous_retired = 0
    with bz2.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                raw = json.loads(line)
                retired_number = int(raw["refsnp_id"])
                merged_into = raw["merged_snapshot_data"]["merged_into"]
                if not isinstance(merged_into, Sequence) or isinstance(merged_into, str):
                    raise TypeError("merged_into is not an array")
                target_numbers = [int(value) for value in merged_into]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ProcessError(
                    f"{path.name}: malformed RefSNP merge object at line {line_number} ({exc})"
                ) from exc
            if retired_number <= 0 or any(target <= 0 for target in target_numbers):
                raise ProcessError(f"{path.name}: non-positive rsID at line {line_number}")
            # NCBI publishes refsnp-merged in ascending refsnp_id order. Enforcing that
            # streaming invariant detects duplicate IDs (and a publisher ordering
            # change) in constant memory; a full string group-by over tens of millions
            # of records is not a production-safe uniqueness check.
            if retired_number <= previous_retired:
                relation = "duplicate" if retired_number == previous_retired else "out-of-order"
                raise ProcessError(
                    f"{path.name}: {relation} retired rsID rs{retired_number} at line {line_number}"
                )
            previous_retired = retired_number
            retired = f"rs{retired_number}"
            targets = [f"rs{target}" for target in target_numbers]
            if len(targets) == 1:
                if targets[0] == retired:
                    raise ProcessError(
                        f"{path.name}: self-merge at line {line_number} for {retired}"
                    )
                yield retired, "resolved", targets[0], targets
            elif not targets:
                yield retired, "no-current-target", None, targets
            else:
                yield retired, "multiple-current-targets", None, targets


@dataclass(frozen=True)
class _AnchorSide:
    chrom: str
    pos: int
    gene: str


def _clinvar_pairs(path: Path) -> Iterator[tuple[str, _AnchorSide, _AnchorSide]]:
    """Yield dual-build rows from AlleleID-grouped ``variant_summary``.

    ClinVar publishes this table in AlleleID order, with the assembly rows for an allele
    adjacent. Checking that order lets this stay streaming rather than retaining millions
    of clinical rows. If the publisher changes the order, extraction fails visibly.
    """
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {
            "#AlleleID",
            "Type",
            "GeneSymbol",
            "RS# (dbSNP)",
            "Assembly",
            "Chromosome",
            "Start",
            "Stop",
            "ReferenceAlleleVCF",
            "AlternateAlleleVCF",
        }
        missing = sorted(required - set(reader.fieldnames or ()))
        if missing:
            raise ProcessError(f"{path.name}: missing ClinVar column(s): {', '.join(missing)}")
        current_allele: int | None = None
        current_rsid: str | None = None
        builds: dict[str, dict[tuple[str, int], set[str]]] = {}

        def completed() -> tuple[str, _AnchorSide, _AnchorSide] | None:
            def unique_side(assembly: str) -> _AnchorSide | None:
                placements = builds.get(assembly, {})
                if len(placements) != 1:
                    return None
                (chrom, pos), genes = next(iter(placements.items()))
                gene = "|".join(sorted(gene for gene in genes if gene != "-")) or "-"
                return _AnchorSide(chrom=chrom, pos=pos, gene=gene)

            side37 = unique_side("GRCh37")
            side38 = unique_side("GRCh38")
            if (
                current_rsid is None
                or side37 is None
                or side38 is None
                or side37.chrom != side38.chrom
            ):
                return None
            return current_rsid, side37, side38

        for line_number, row in enumerate(reader, start=2):
            try:
                allele_id = int(row["#AlleleID"])
            except ValueError:
                raise ProcessError(f"{path.name}: invalid AlleleID at line {line_number}") from None
            if current_allele is not None and allele_id < current_allele:
                raise ProcessError(
                    f"{path.name}: AlleleID order changed at line {line_number}; "
                    "cannot pair assemblies with the streaming extractor"
                )
            if current_allele is not None and allele_id != current_allele:
                candidate = completed()
                if candidate is not None:
                    yield candidate
                current_rsid = None
                builds = {}
            current_allele = allele_id

            assembly = row["Assembly"]
            if assembly not in {"GRCh37", "GRCh38"}:
                continue
            chrom = row["Chromosome"]
            if chrom not in _CHROM_SET:
                continue
            # Current ClinVar exports retain the legacy allele columns but populate them
            # with ``na``. The assembly-normalized VCF columns carry the actual bases.
            ref = row["ReferenceAlleleVCF"]
            alt = row["AlternateAlleleVCF"]
            if row["Type"] != "single nucleotide variant" or len(ref) != 1 or len(alt) != 1:
                continue
            raw_rsid = row["RS# (dbSNP)"].strip()
            if not raw_rsid.isdigit() or raw_rsid == "0":
                continue
            try:
                start, stop = int(row["Start"]), int(row["Stop"])
            except ValueError:
                raise ProcessError(
                    f"{path.name}: invalid ClinVar coordinate at line {line_number}"
                ) from None
            if start != stop or start <= 0:
                continue
            rsid = f"rs{int(raw_rsid)}"
            if current_rsid is not None and current_rsid != rsid:
                raise ProcessError(f"{path.name}: AlleleID {allele_id} carries multiple rsIDs")
            current_rsid = rsid
            gene = row["GeneSymbol"].strip() or "-"
            placements = builds.setdefault(assembly, {})
            placements.setdefault((chrom, start), set()).add(gene)

        candidate = completed()
        if candidate is not None:
            yield candidate


def _select_anchors(
    candidates: Iterable[tuple[str, _AnchorSide, _AnchorSide]], count: int
) -> list[tuple[str, _AnchorSide, _AnchorSide]]:
    if count <= 0:
        raise ProcessError("extract_build_anchors count must be positive")
    seen: dict[str, tuple[_AnchorSide, _AnchorSide]] = {}
    ambiguous: set[str] = set()
    for candidate in candidates:
        rsid, side37, side38 = candidate
        # An unchanged coordinate has no discriminatory power and, because check_build
        # tests GRCh37 first, would incorrectly count a GRCh38 file as a GRCh37 match.
        if side37.pos == side38.pos:
            continue
        if rsid in ambiguous:
            continue
        previous = seen.get(rsid)
        if previous is not None:
            previous37, previous38 = previous
            same_placements = (previous37.chrom, previous37.pos) == (side37.chrom, side37.pos) and (
                previous38.chrom,
                previous38.pos,
            ) == (side38.chrom, side38.pos)
            if not same_placements:
                # A RefSNP can be represented by multiple ClinVar alleles or alternate
                # loci. It is unsuitable as a build discriminator unless its placement
                # is unique across the whole source, so remove it rather than choosing
                # one locus arbitrarily or aborting extraction of every other anchor.
                ambiguous.add(rsid)
                del seen[rsid]
            continue
        seen[rsid] = (side37, side38)
    by_chrom: dict[str, list[tuple[str, _AnchorSide, _AnchorSide]]] = {
        chrom: [] for chrom in _CHROMS
    }
    for rsid, (side37, side38) in seen.items():
        candidate = (rsid, side37, side38)
        rows = by_chrom[side37.chrom]
        rows.append(candidate)
        # Only low rsIDs can survive the final choice. Bound memory even if ClinVar grows
        # to millions of paired records.
        if len(rows) > count * 2:
            rows.sort(key=lambda item: int(item[0][2:]))
            del rows[count:]
    for rows in by_chrom.values():
        rows.sort(key=lambda item: int(item[0][2:]))
    selected: list[tuple[str, _AnchorSide, _AnchorSide]] = []
    offset = 0
    while len(selected) < count:
        added = False
        for chrom in _CHROMS:
            rows = by_chrom[chrom]
            if offset < len(rows):
                selected.append(rows[offset])
                added = True
                if len(selected) == count:
                    break
        if not added:
            break
        offset += 1
    if len(selected) < count:
        raise ProcessError(
            f"ClinVar supplied only {len(selected)} unambiguous dual-build SNV anchors; "
            f"manifest requested {count}"
        )
    return selected


def _run_parquet(
    declared: PostProcess,
    source_dir: Path,
    *,
    records: Callable[[Path], Iterable[tuple[Any, ...]]],
    schema: Mapping[str, PolarsType],
    verify_only: bool,
    progress: ProcessProgressCallback | None,
    input_sha256: str,
) -> ProcessResult:
    input_path = _inside(source_dir, declared.params["input"], label="input")
    output = _inside(source_dir, declared.params["output"], label="output")
    if not input_path.is_file():
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            str(declared.params["output"]),
            detail=f"input {input_path.name} is missing",
        )
    expected_provenance = _expected_provenance(declared, input_path, input_sha256)
    if output.is_file():
        try:
            rows = _validate_parquet(output, schema)
            validate_provenance(output, expected=expected_provenance, actual_rows=rows)
        except ProcessError as exc:
            if verify_only:
                return ProcessResult(
                    declared.step,
                    ProcessStatus.FAILED,
                    str(declared.params["output"]),
                    detail=str(exc),
                )
        else:
            if not verify_only:
                _cleanup_chunked_state(output)
            status = ProcessStatus.VERIFIED if verify_only else ProcessStatus.ALREADY_PRESENT
            return ProcessResult(declared.step, status, str(declared.params["output"]), rows)
    if verify_only:
        # Not built yet is not the same as broken. `refs status` already reports this
        # state as "processing-required" and stays green; reporting FAILED here made
        # `refs verify` exit non-zero and call every checksum-verified download of a
        # 28 GB source broken, so the two commands disagreed about whether the tree was
        # healthy. A *present* artifact that does not validate still fails, above.
        return ProcessResult(
            declared.step,
            ProcessStatus.PENDING,
            str(declared.params["output"]),
            detail="not built yet; run `genetics refs fetch` for this source",
        )
    try:
        recovered_rows = _recover_promoted_output(
            output,
            input_path=input_path,
            schema=schema,
            provenance=expected_provenance,
        )
        if recovered_rows is not None:
            return ProcessResult(
                declared.step,
                ProcessStatus.CREATED,
                str(declared.params["output"]),
                recovered_rows,
                detail="recovered a promoted output and completed its provenance",
            )
        rows = _write_chunked_parquet(
            records(input_path),
            input_path=input_path,
            output=output,
            schema=schema,
            progress=progress,
            step_name=declared.step,
            provenance=expected_provenance,
            retain_staging=True,
        )
        _write_provenance(output, expected_provenance, rows)
        _cleanup_chunked_state(output)
    except (OSError, pl.exceptions.PolarsError, ProcessError) as exc:
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            str(declared.params["output"]),
            detail=str(exc),
        )
    return ProcessResult(declared.step, ProcessStatus.CREATED, str(declared.params["output"]), rows)


def _run_merges(
    declared: PostProcess,
    source_dir: Path,
    *,
    verify_only: bool,
    progress: ProcessProgressCallback | None,
    input_sha256: str,
) -> ProcessResult:
    """Classify every dbSNP merge without inventing a target for ambiguous records."""
    input_path = _inside(source_dir, declared.params["input"], label="input")
    output = _inside(source_dir, declared.params["output"], label="output")
    unresolved_output = _inside(
        source_dir, declared.params["unresolvable_output"], label="unresolvable output"
    )
    if not input_path.is_file():
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            str(declared.params["output"]),
            detail=f"input {input_path.name} is missing",
        )

    expected = _expected_provenance(declared, input_path, input_sha256)
    unresolved_expected = _expected_provenance(
        declared, input_path, input_sha256, output_param="unresolvable_output"
    )
    if output.is_file() and unresolved_output.is_file():
        try:
            rows = _validate_parquet(output, MERGE_TABLE_SCHEMA)
            unresolved_rows = _validate_parquet(unresolved_output, UNRESOLVABLE_MERGE_SCHEMA)
            validate_provenance(output, expected=expected, actual_rows=rows)
            validate_provenance(
                unresolved_output,
                expected=unresolved_expected,
                actual_rows=unresolved_rows,
            )
        except ProcessError as exc:
            if verify_only:
                return ProcessResult(
                    declared.step,
                    ProcessStatus.FAILED,
                    str(declared.params["output"]),
                    detail=str(exc),
                )
        else:
            if not verify_only:
                classified = output.with_name(f".{output.name}.classified.parquet")
                classified.unlink(missing_ok=True)
                provenance_path(classified).unlink(missing_ok=True)
                _cleanup_chunked_state(classified)
            status = ProcessStatus.VERIFIED if verify_only else ProcessStatus.ALREADY_PRESENT
            return ProcessResult(
                declared.step,
                status,
                str(declared.params["output"]),
                rows,
                detail=f"{unresolved_rows} unresolvable merge record(s)",
            )
    elif verify_only:
        # See the note on the single-output verify branches: absent is pending work, not
        # damage.
        missing = [path.name for path in (output, unresolved_output) if not path.is_file()]
        return ProcessResult(
            declared.step,
            ProcessStatus.PENDING,
            str(declared.params["output"]),
            detail=(
                f"not built yet ({', '.join(missing)}); run `genetics refs fetch` for this source"
            ),
        )

    classified = output.with_name(f".{output.name}.classified.parquet")
    classified_expected = {**expected, "output": classified.name}
    completed = False
    try:
        try:
            classified_rows = _validate_parquet(classified, _MERGE_SOURCE_SCHEMA)
            validate_provenance(
                classified,
                expected=classified_expected,
                actual_rows=classified_rows,
            )
        except ProcessError:
            recovered_rows = _recover_promoted_output(
                classified,
                input_path=input_path,
                schema=_MERGE_SOURCE_SCHEMA,
                provenance=classified_expected,
            )
            if recovered_rows is None:
                classified_rows = _write_chunked_parquet(
                    _merge_records(input_path),
                    input_path=input_path,
                    output=classified,
                    schema=_MERGE_SOURCE_SCHEMA,
                    progress=progress,
                    step_name=declared.step,
                    provenance=classified_expected,
                    retain_staging=True,
                )
                _write_provenance(classified, classified_expected, classified_rows)
                _cleanup_chunked_state(classified)
            else:
                classified_rows = recovered_rows
            validate_provenance(
                classified,
                expected=classified_expected,
                actual_rows=classified_rows,
            )
        source = pl.scan_parquet(classified)
        resolved_part = _part_path(output)
        unresolved_part = _part_path(unresolved_output)
        resolved_part.unlink(missing_ok=True)
        unresolved_part.unlink(missing_ok=True)
        source.filter(pl.col("status") == "resolved").select(
            "retired_rsid", "current_rsid"
        ).sink_parquet(resolved_part, maintain_order=True, mkdir=True)
        source.filter(pl.col("status") != "resolved").select(
            "retired_rsid", "status", "targets"
        ).sink_parquet(unresolved_part, maintain_order=True, mkdir=True)
        rows = _validate_parquet(resolved_part, MERGE_TABLE_SCHEMA)
        unresolved_rows = _validate_parquet(unresolved_part, UNRESOLVABLE_MERGE_SCHEMA)
        if rows + unresolved_rows != classified_rows:
            raise ProcessError(
                f"{classified.name}: classified {classified_rows} record(s), but the "
                f"outputs contain {rows + unresolved_rows}"
            )
        os.replace(resolved_part, output)
        os.replace(unresolved_part, unresolved_output)
        _write_provenance(output, expected, rows)
        _write_provenance(unresolved_output, unresolved_expected, unresolved_rows)
        validate_provenance(output, expected=expected, actual_rows=rows)
        validate_provenance(
            unresolved_output,
            expected=unresolved_expected,
            actual_rows=unresolved_rows,
        )
        completed = True
    except (OSError, pl.exceptions.PolarsError, ProcessError) as exc:
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            str(declared.params["output"]),
            detail=str(exc),
        )
    finally:
        if completed:
            classified.unlink(missing_ok=True)
            provenance_path(classified).unlink(missing_ok=True)
            _cleanup_chunked_state(classified)
    return ProcessResult(
        declared.step,
        ProcessStatus.CREATED,
        str(declared.params["output"]),
        rows,
        detail=f"{unresolved_rows} unresolvable merge record(s)",
    )


def _run_anchors(
    declared: PostProcess,
    source_dir: Path,
    *,
    verify_only: bool,
    input_sha256: str,
) -> ProcessResult:
    from genetics.qc.build_anchors import load_anchors

    input_path = _inside(source_dir, declared.params["input"], label="input")
    output = _inside(source_dir, declared.params["output"], label="output")
    count = int(declared.params.get("count", 200))
    expected_provenance = _expected_provenance(declared, input_path, input_sha256)
    if not input_path.is_file():
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            str(declared.params["output"]),
            detail=f"input {input_path.name} is missing",
        )
    if output.is_file():
        try:
            # One validation, not two. `load_anchors` already runs `validate_provenance`
            # and already enforces `expected_count`, so calling both here hashed and
            # row-counted the artifact twice on every fetch and every verify, and stated
            # the count rule in two places that could disagree.
            anchors = load_anchors(
                output,
                expected_count=count,
                expected_provenance=expected_provenance,
            )
        except (OSError, TypeError, ValueError, ProcessError) as exc:
            if verify_only:
                return ProcessResult(
                    declared.step,
                    ProcessStatus.FAILED,
                    str(declared.params["output"]),
                    detail=f"{output.name}: invalid build-anchor output ({exc})",
                )
        else:
            status = ProcessStatus.VERIFIED if verify_only else ProcessStatus.ALREADY_PRESENT
            return ProcessResult(
                declared.step, status, str(declared.params["output"]), len(anchors)
            )
    if verify_only:
        # Not built yet is not the same as broken. `refs status` already reports this
        # state as "processing-required" and stays green; reporting FAILED here made
        # `refs verify` exit non-zero and call every checksum-verified download of a
        # 28 GB source broken, so the two commands disagreed about whether the tree was
        # healthy. A *present* artifact that does not validate still fails, above.
        return ProcessResult(
            declared.step,
            ProcessStatus.PENDING,
            str(declared.params["output"]),
            detail="not built yet; run `genetics refs fetch` for this source",
        )
    try:
        selected = _select_anchors(_clinvar_pairs(input_path), count)
        source_text = (
            f"ClinVar rolling {input_path.name} public export (input sha256 {input_sha256})"
        )
        payload = {
            "schema_version": 1,
            "source": source_text,
            "anchors": [
                {
                    "rsid": rsid,
                    "chrom": side37.chrom,
                    "pos_grch37": side37.pos,
                    "pos_grch38": side38.pos,
                    "gene": side37.gene,
                    "source": source_text,
                }
                for rsid, side37, side38 in selected
            ],
        }
        _write_json_atomic(output, payload)
        _write_provenance(output, expected_provenance, count)
        if len(load_anchors(output, expected_count=count)) != count:
            raise ProcessError(f"{output.name}: generated anchor count changed during validation")
    except (OSError, ProcessError, ValueError) as exc:
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            str(declared.params["output"]),
            detail=str(exc),
        )
    return ProcessResult(
        declared.step, ProcessStatus.CREATED, str(declared.params["output"]), count
    )


# ---------------------------------------------------------------------------
# build_pca_marker_subset (M5.3)
# ---------------------------------------------------------------------------
#
# The one step here that shells out. Everything above is Python and Polars over text; this
# is four PLINK 2 invocations per chromosome and a merge, because AGENTS.md 4.9 put format
# conversion, LD pruning and merging inside one native binary rather than inside htslib.
#
# What it produces is the marker set a reference PCA is computed on: common, autosomal,
# biallelic ACGT SNPs, outside the known long-range LD regions, thinned so that no two
# markers left standing are in strong linkage. Each of those four words is doing work, and
# the reasons are on the constants below.
#
# It is deliberately *not* restricted to a consumer array's markers, though the roadmap's
# phrasing for M5.3 invites that. Two reasons. The artifact stops being a function of
# public data the moment an export chooses its contents -- see the note on the registry
# entry. And the restriction is better applied where the export already is: the eigenvector
# build can intersect this subset with the array and prune again, whereas a subset built
# against one person's chip would be wrong for the next person's.

_PCA_LONG_RANGE_LD_GRCH37: Final[tuple[tuple[str, int, int, str], ...]] = (
    ("2", 135_000_000, 137_000_000, "LCT"),
    ("6", 25_000_000, 35_000_000, "MHC"),
    ("8", 8_000_000, 12_000_000, "inv8p23"),
    ("17", 40_000_000, 45_000_000, "inv17q21"),
)
"""Regions excluded before pruning, in GRCh37 coordinates.

Long-range LD confounds a PCA rather than merely adding noise to it: a single haplotype
block spanning tens of megabases contributes enough correlated markers to claim a principal
component outright, and the resulting axis separates inversion carriers from non-carriers
while looking exactly like an ancestry axis. Price et al. (2008, Am J Hum Genet) is the
standard reference for excluding them.

**This is the conservative core of that list, not the whole of it.** The four here -- the
lactase region, the MHC, and the 8p23 and 17q21.31 inversions -- are the ones whose extents
are not in doubt. Reproducing the full table from memory is exactly the sort of
plausible-looking fabrication AGENTS.md 6 forbids, and the cost of stopping short is a few
thousand markers out of hundreds of thousands. Extend it from the paper, not from recall.
"""

_PCA_DEFAULTS: Final[Mapping[str, Any]] = {
    # Rare variants are the wrong input to a PCA twice over: their loadings are dominated
    # by drift rather than by shared ancestry, and a consumer array carries few of them
    # well. 5% is the usual floor.
    "maf": 0.05,
    # 1000 Genomes phase 3 is called at essentially 100%, so this is a tripwire for a
    # damaged input rather than a filter that does routine work.
    "max_missing": 0.02,
    # Window, step and r^2 for --indep-pairwise. A physical window rather than a variant
    # count, so the thinning does not get denser wherever the panel does.
    "window": "200kb",
    "step": 1,
    "r2": 0.2,
}
"""Effective settings when the manifest declares none.

Recorded in the provenance sidecar under ``settings`` rather than left implicit. The
alternative -- relying on ``transform_version`` alone -- means a changed default silently
leaves every existing artifact looking current, and this is an artifact somebody waits
hours for and will not rebuild on a hunch.
"""

_CHROM_IN_FILENAME: Final[re.Pattern[str]] = re.compile(r"\.chr([0-9]{1,2}|X|Y|MT|M)\.", re.I)
"""Which chromosome a panel file holds, read from the name the manifest pins.

Reading the name is safe here only because the manifest pins it and the fetcher verifies
the file's digest against that entry, so the name is as trustworthy as the bytes. It is
still cross-checked: each conversion passes ``--chr N`` for the N the name claims, so a
file whose contents disagree yields no variants and fails loudly instead of contributing
the wrong chromosome's markers.
"""


@dataclass(frozen=True)
class _PcaSettings:
    """Resolved filter and pruning settings for one run."""

    maf: float
    max_missing: float
    window: str
    step: int
    r2: float

    @classmethod
    def resolve(cls, params: Mapping[str, Any]) -> _PcaSettings:
        merged = {**_PCA_DEFAULTS, **{k: v for k, v in params.items() if k in _PCA_DEFAULTS}}
        try:
            settings = cls(
                maf=float(merged["maf"]),
                max_missing=float(merged["max_missing"]),
                window=str(merged["window"]),
                step=int(merged["step"]),
                r2=float(merged["r2"]),
            )
        except (TypeError, ValueError) as exc:
            raise ProcessError(f"build_pca_marker_subset: unusable settings ({exc})") from None
        if not 0.0 <= settings.maf < 0.5:
            raise ProcessError(f"maf must be in [0, 0.5), got {settings.maf}")
        if not 0.0 <= settings.max_missing <= 1.0:
            raise ProcessError(f"max_missing must be in [0, 1], got {settings.max_missing}")
        if not 0.0 < settings.r2 <= 1.0:
            raise ProcessError(f"r2 must be in (0, 1], got {settings.r2}")
        if settings.step < 1:
            raise ProcessError(f"step must be at least 1, got {settings.step}")
        return settings

    def as_dict(self) -> dict[str, Any]:
        return {
            "maf": self.maf,
            "max_missing": self.max_missing,
            "window": self.window,
            "step": self.step,
            "r2": self.r2,
            "long_range_ld_excluded": [
                f"{chrom}:{start}-{end}" for chrom, start, end, _ in _PCA_LONG_RANGE_LD_GRCH37
            ],
        }


@dataclass(frozen=True)
class _PanelInput:
    chrom: int
    path: Path
    sha256: str


_PGEN_COMPANIONS: Final[tuple[str, ...]] = (".pvar", ".psam")
"""A pgen is a fileset, not a file. All three are promoted and all three are digested."""


def _companion(output: Path, suffix: str) -> Path:
    return output.with_name(output.stem + suffix)


def _pvar_variants(pvar: Path) -> int:
    """Count data lines in a .pvar. Header lines start with ``#``, comments with ``##``."""
    try:
        with pvar.open("r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip() and not line.startswith("#"))
    except OSError as exc:
        raise ProcessError(f"{pvar.name}: cannot count variants ({exc})") from exc


def _autosomal_panel_inputs(
    source: Source, source_dir: Path, input_digests: Mapping[str, str] | None
) -> tuple[_PanelInput, ...]:
    """The source's per-autosome genotype VCFs, in chromosome order, with their digests."""
    found: list[_PanelInput] = []
    for item in source.files:
        match = _CHROM_IN_FILENAME.search(item.filename)
        if match is None:
            continue
        token = match.group(1).upper()
        if not token.isdigit() or not 1 <= int(token) <= 22:
            continue
        path = _inside(source_dir, item.filename, label="input")
        if not path.is_file():
            raise ProcessError(f"panel input {item.filename} is missing; fetch this source first")
        digest = (input_digests or {}).get(item.filename) or _sha256(path)
        found.append(_PanelInput(chrom=int(token), path=path, sha256=digest))
    if not found:
        raise ProcessError(
            "no per-autosome genotype VCF found in this source. The filenames the manifest "
            "pins are what identifies them, and none matched `.chr<1-22>.`"
        )
    return tuple(sorted(found, key=lambda item: item.chrom))


def _panel_input_digest(inputs: Sequence[_PanelInput]) -> str:
    """One digest over the ordered set, so any chromosome changing invalidates the whole."""
    joined = "\n".join(f"{item.path.name} {item.sha256}" for item in inputs)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _write_long_range_ld_bed(path: Path) -> None:
    """Write the exclusion regions for ``--exclude bed1`` (1-based, fully closed)."""
    lines = [
        f"{chrom}\t{start}\t{end}\t{label}"
        for chrom, start, end, label in _PCA_LONG_RANGE_LD_GRCH37
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _pca_work_dir(output: Path) -> Path:
    """Scratch beside the output, hidden and named after it, as the chunked steps are."""
    return output.with_name(f".{output.name}.work")


def _prune_one_chromosome(
    plink: Plink2,
    item: _PanelInput,
    *,
    work: Path,
    exclusions: Path,
    settings: _PcaSettings,
    stamp: str,
) -> Path:
    """Filter, prune and extract one chromosome. Returns the pruned fileset's prefix.

    **Restartable per chromosome.** On real 1000 Genomes each pass is minutes and there are
    twenty-two of them, so losing the lot to an interrupted run three hours in is not a
    theoretical cost. The stamp binds a finished chromosome to the input digest and the
    settings that produced it, so a rerun with either changed redoes the work rather than
    trusting a file that merely exists -- which is the distinction the M2.3 chunk state
    already had to learn.
    """
    pruned = work / f"pruned{item.chrom}"
    marker = work / f"pruned{item.chrom}.stamp"
    written = all(pruned.with_suffix(s).is_file() for s in (".pgen", *_PGEN_COMPANIONS))
    if written and marker.is_file() and marker.read_text(encoding="utf-8").strip() == stamp:
        return pruned

    converted = work / f"chr{item.chrom}"
    plink.run(
        [
            "--vcf",
            str(item.path),
            "--chr",
            str(item.chrom),
            "--snps-only",
            "just-acgt",
            "--min-alleles",
            "2",
            "--max-alleles",
            "2",
            "--maf",
            str(settings.maf),
            "--geno",
            str(settings.max_missing),
            # 1000 Genomes carries repeated variant IDs. Excluding every copy rather than
            # keeping the first is the same rule the matcher applies to duplicate probes:
            # with nothing to choose between them, choosing is manufacturing an answer.
            "--rm-dup",
            "exclude-all",
            "--exclude",
            "bed1",
            str(exclusions),
            "--make-pgen",
            # --pmerge-list requires position-sorted inputs and says so; this is what
            # guarantees it rather than hoping the panel was written in order.
            "--sort-vars",
        ],
        out=converted,
    )
    plink.run(
        [
            "--pfile",
            str(converted),
            "--indep-pairwise",
            settings.window,
            str(settings.step),
            str(settings.r2),
        ],
        out=converted,
    )
    plink.run(
        [
            "--pfile",
            str(converted),
            "--extract",
            str(converted.with_suffix(".prune.in")),
            "--make-pgen",
        ],
        out=pruned,
    )
    marker.write_text(stamp + "\n", encoding="utf-8", newline="\n")
    for suffix in (".pgen", ".pvar", ".psam", ".prune.in", ".prune.out"):
        converted.with_suffix(suffix).unlink(missing_ok=True)
    return pruned


def _merge_pruned(plink: Plink2, prefixes: Sequence[Path], *, work: Path) -> Path:
    """Combine the per-chromosome pruned filesets into one. Returns the merged prefix."""
    if len(prefixes) == 1:
        return prefixes[0]
    listing = work / "merge-list.txt"
    listing.write_text(
        "\n".join(str(prefix) for prefix in prefixes) + "\n", encoding="utf-8", newline="\n"
    )
    merged = work / "merged"
    plink.run(["--pmerge-list", str(listing), "pfile", "--make-pgen"], out=merged)
    return merged


def _promote_fileset(prefix: Path, output: Path) -> None:
    """Move a finished pgen fileset onto the declared output name.

    ``os.replace`` per file, after every one of them exists. The module's invariant is that
    a killed run never leaves a file bearing the declared output name; building under a
    scratch prefix and moving at the end is what keeps that true for a transform whose tool
    writes wherever it is pointed.
    """
    sources = {suffix: prefix.with_suffix(suffix) for suffix in (".pgen", *_PGEN_COMPANIONS)}
    missing = [s for s, path in sources.items() if not path.is_file()]
    if missing:
        raise ProcessError(f"{output.name}: PLINK did not write {', '.join(sorted(missing))}")
    for suffix, path in sources.items():
        os.replace(path, _companion(output, suffix) if suffix != ".pgen" else output)


def _run_pca_subset(
    declared: PostProcess,
    source: Source,
    source_dir: Path,
    *,
    verify_only: bool,
    progress: ProcessProgressCallback | None,
    input_digests: Mapping[str, str] | None,
) -> ProcessResult:
    from genetics.external.plink2 import Plink2, Plink2Error

    output_name = str(declared.params["output"])
    output = _inside(source_dir, output_name, label="output")
    if output.suffix != ".pgen":
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            output_name,
            detail=f"output must name a .pgen fileset, got {output_name!r}",
        )

    try:
        settings = _PcaSettings.resolve(declared.params)
        inputs = _autosomal_panel_inputs(source, source_dir, input_digests)
    except ProcessError as exc:
        if verify_only and not output.is_file():
            return ProcessResult(declared.step, ProcessStatus.PENDING, output_name, detail=str(exc))
        return ProcessResult(declared.step, ProcessStatus.FAILED, output_name, detail=str(exc))

    combined = _panel_input_digest(inputs)
    expected = {
        **_expected_provenance(
            declared,
            inputs[0].path,
            combined,
            input_filename=f"{len(inputs)} autosomal genotype VCFs",
        ),
        "settings": settings.as_dict(),
    }

    if output.is_file():
        try:
            recorded = validate_provenance(
                output,
                expected=expected,
                expected_step=declared.step,
                expected_transform_version=declared.definition.transform_version,
            )
            _validate_companions(output, recorded)
        except ProcessError as exc:
            if verify_only:
                return ProcessResult(
                    declared.step, ProcessStatus.FAILED, output_name, detail=str(exc)
                )
        else:
            status = ProcessStatus.VERIFIED if verify_only else ProcessStatus.ALREADY_PRESENT
            return ProcessResult(declared.step, status, output_name, int(recorded["rows"]))

    if verify_only:
        # Not built is not broken -- the same distinction `_run_anchors` draws, and for the
        # same reason: `refs verify` must not call a checksum-clean 16.75 GB download
        # unhealthy because an hours-long transform has not been asked for yet.
        return ProcessResult(
            declared.step,
            ProcessStatus.PENDING,
            output_name,
            detail="not built yet; run `genetics refs fetch` for this source",
        )

    work = _pca_work_dir(output)
    try:
        plink = Plink2.discover()
        work.mkdir(parents=True, exist_ok=True)
        exclusions = work / "long-range-ld.bed"
        _write_long_range_ld_bed(exclusions)
        stamp = hashlib.sha256(
            json.dumps({"input": combined, "settings": settings.as_dict()}, sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest()

        prefixes: list[Path] = []
        seen = 0
        for item in inputs:
            prefix = _prune_one_chromosome(
                plink,
                item,
                work=work,
                exclusions=exclusions,
                settings=settings,
                stamp=stamp,
            )
            prefixes.append(prefix)
            seen += _pvar_variants(_companion(prefix.with_suffix(".pgen"), ".pvar"))
            if progress is not None:
                progress(ProcessProgressEvent(declared.step, seen))

        merged = _merge_pruned(plink, prefixes, work=work)
        _promote_fileset(merged, output)
        rows = _pvar_variants(_companion(output, ".pvar"))
        if rows == 0:
            raise ProcessError(f"{output.name}: pruning left no markers")
        _write_provenance(
            output,
            {**expected, "companions": _companion_digests(output)},
            rows,
        )
        validate_provenance(output, expected=expected, actual_rows=rows)
    except (OSError, Plink2Error, ProcessError, ValueError) as exc:
        # Leave nothing bearing the declared name. A half-promoted fileset is worse than no
        # fileset: it satisfies every "is it there?" check `refs status` makes while being
        # unreadable, and the sidecar that would have caught that is the part not written.
        for suffix in (".pgen", *_PGEN_COMPANIONS):
            _companion(output, suffix).unlink(missing_ok=True)
        provenance_path(output).unlink(missing_ok=True)
        return ProcessResult(declared.step, ProcessStatus.FAILED, output_name, detail=str(exc))

    # The work directory is removed only here, on success, because it holds a second copy of
    # every marker in the artifact. A failed run keeps it so that a rerun resumes from the
    # chromosomes that finished -- which the stamps are what make safe.
    shutil.rmtree(work, ignore_errors=True)
    return ProcessResult(declared.step, ProcessStatus.CREATED, output_name, rows)


def _companion_digests(output: Path) -> dict[str, str]:
    return {suffix: _sha256(_companion(output, suffix)) for suffix in _PGEN_COMPANIONS}


def _validate_companions(output: Path, recorded: Mapping[str, Any]) -> None:
    """Check the .pvar and .psam against the digests the sidecar recorded.

    ``validate_provenance`` hashes the artifact it is pointed at, and for a pgen that is one
    third of the thing. A .psam swapped for one listing different samples would leave the
    .pgen byte-identical and every downstream projection silently mislabelled.
    """
    stored = recorded.get("companions")
    if not isinstance(stored, Mapping):
        raise ProcessError(f"{provenance_path(output).name}: records no companion digests")
    for suffix in _PGEN_COMPANIONS:
        path = _companion(output, suffix)
        if not path.is_file():
            raise ProcessError(f"{output.stem}{suffix} is missing")
        if stored.get(suffix) != _sha256(path):
            raise ProcessError(f"{path.name} does not match the digest recorded for it")


def run(
    source: Source,
    *,
    root: Path,
    verify_only: bool = False,
    progress: ProcessProgressCallback | None = None,
    input_digests: Mapping[str, str] | None = None,
) -> tuple[ProcessResult, ...]:
    """Run or verify every declared transform for one source, in manifest order."""
    source_dir = (root / source.id).resolve()
    results: list[ProcessResult] = []
    for declared in source.post_process:
        definition = declared.definition
        if not definition.implemented:
            results.append(
                ProcessResult(
                    declared.step,
                    ProcessStatus.PENDING,
                    detail=(f"owned by {definition.milestone or 'an unassigned milestone'}"),
                )
            )
            continue
        if definition.output_is_genotype_derived:
            results.append(
                ProcessResult(
                    declared.step,
                    ProcessStatus.FAILED,
                    detail="genotype-derived transforms require an outside-repository cache root",
                )
            )
            continue
        try:
            if declared.step == "build_pca_marker_subset":
                # Routed before the input resolution below, which assumes one named input
                # file: this step's input is the whole set of per-autosome VCFs and its
                # provenance digest is taken over all of them together.
                #
                # Inside the try, not before it. The executor catches what it can predict,
                # and this is the net for what it cannot -- an unreadable companion file
                # caught mid-validation, say. Dispatching ahead of the try would have made
                # this the one step whose unexpected failure escaped `run()` as a traceback
                # instead of a FAILED result, and `refs fetch` would have died on it rather
                # than reporting it.
                results.append(
                    _run_pca_subset(
                        declared,
                        source,
                        source_dir,
                        verify_only=verify_only,
                        progress=progress,
                        input_digests=input_digests,
                    )
                )
                if results[-1].status is ProcessStatus.FAILED:
                    break
                continue
            input_name = str(declared.params["input"])
            input_path = _inside(source_dir, input_name, label="input")
            input_sha256 = (input_digests or {}).get(input_name)
            if input_sha256 is None and input_path.is_file():
                input_sha256 = _sha256(input_path)
            if input_sha256 is None:
                input_sha256 = "0" * 64  # executor returns the clearer missing-input error
            if declared.step == "extract_rsid_merge_table":
                result = _run_merges(
                    declared,
                    source_dir,
                    verify_only=verify_only,
                    progress=progress,
                    input_sha256=input_sha256,
                )
            elif declared.step == "extract_dbsnp_variant_index":
                result = _run_parquet(
                    declared,
                    source_dir,
                    records=_vcf_records,
                    schema=VARIANT_INDEX_SCHEMA,
                    verify_only=verify_only,
                    progress=progress,
                    input_sha256=input_sha256,
                )
            elif declared.step == "extract_build_anchors":
                result = _run_anchors(
                    declared,
                    source_dir,
                    verify_only=verify_only,
                    input_sha256=input_sha256,
                )
            else:  # pragma: no cover - guarded by assert_registry_is_honest.
                result = ProcessResult(
                    declared.step,
                    ProcessStatus.FAILED,
                    detail="step is marked implemented but has no executor",
                )
        except (
            EOFError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            csv.Error,
            pl.exceptions.PolarsError,
            ProcessError,
        ) as exc:
            result = ProcessResult(
                declared.step,
                ProcessStatus.FAILED,
                output=(str(declared.params["output"]) if "output" in declared.params else None),
                detail=str(exc),
            )
        results.append(result)
        if result.status is ProcessStatus.FAILED:
            break
    return tuple(results)


def assert_registry_is_honest() -> None:
    """Fail if a step claims implementation without an executor branch."""
    executable = {
        "extract_rsid_merge_table",
        "extract_dbsnp_variant_index",
        "extract_build_anchors",
        "build_pca_marker_subset",
    }
    claimed = {name for name, step in STEPS.items() if step.implemented}
    if claimed != executable:
        raise AssertionError(
            f"post-process registry/executor drift: claimed={sorted(claimed)}, "
            f"executable={sorted(executable)}"
        )
