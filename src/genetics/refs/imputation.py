"""Full public-reference preparation. No consumer export or array positions are accepted."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
import zipfile
from collections.abc import Callable, Iterable, Mapping
from contextlib import nullcontext, suppress
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from genetics.external.beagle import (
    _CREATION_FLAGS,
    BeagleBusyError,
    BeagleError,
    JavaRuntime,
    _java_env,
    _job_lock,
    _stop,
)
from genetics.ingest.normalize import GRCH37_LENGTHS
from genetics.ingest.schema import Chrom
from genetics.paths import tools_dir
from genetics.qc.sex_regions import PAR_GRCH37
from genetics.refs import tools
from genetics.refs.manifest import PostProcess, Source
from genetics.refs.postprocess import (
    ProcessError,
    ProcessProgressCallback,
    ProcessProgressEvent,
    ProcessResult,
    ProcessStatus,
    _cached_sha256,
    _expected_provenance,
    _inside,
    _sha256,
    _write_provenance,
    validate_provenance,
)

AUTOSOMES = tuple(str(n) for n in range(1, 23))
SUPPORTED = (*AUTOSOMES, "X")
MAP_KEYS = (*SUPPORTED, "X_par1", "X_par2")
POLICY = {
    "variant_filter": "none; every record and every sample retained",
    "build": "GRCh37",
    "X_encoding": "phased diploid representation; haploid reference calls explicitly doubled",
    "X_analysis": "M8.3 must partition PAR/non-PAR jobs using GRCh37 bounds and matching maps",
    "Y": (
        "not prepared: phased nonmissing diploid Beagle reference/map unavailable; "
        "direct calls retained elsewhere"
    ),
    "MT": "not present in this source or map collection",
    "round_trip": "ordered CHROM/POS/REF/ALT/END and all GTs, with sample-order digest",
    "annotations": (
        "bref3 stores markers and GTs, not all INFO/FORMAT annotations; original VCF untouched"
    ),
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _write_json(path: Path, value: Any) -> None:
    with path.open("wb") as handle:
        handle.write(_canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())


@dataclass(frozen=True)
class VcfSummary:
    records: int
    samples: int
    sample_order_sha256: str
    semantic_sha256: str
    haploid_calls_doubled: int


def _vcf_stream(
    stream: Iterable[bytes],
    chrom: str,
    *,
    consume: Callable[[bytes], Any] | None = None,
    progress: Callable[[int], None] | None = None,
) -> VcfSummary:
    """Canonicalize GT representation and hash every ordered reference observation.

    A vectorized byte scan keeps 2,504-sample records out of Python allele loops.
    The pinned converter additionally validates every allele index and phasing state.
    """
    count = samples = doubled = last_pos = 0
    digest = hashlib.sha256()
    sample_digest = ""
    for raw in stream:
        line = raw.rstrip(b"\r\n")
        if line.startswith(b"##"):
            if samples:
                raise ProcessError("Reference VCF metadata appears after its column header")
            if line.startswith((b"##reference=", b"##assembly=")) and re.search(
                rb"GRCh38|hg38", line, flags=re.IGNORECASE
            ):
                raise ProcessError("Reference VCF declares a build other than GRCh37")
            contig = re.match(rb"##contig=<ID=" + chrom.encode() + rb",length=([0-9]+)", line)
            if contig and int(contig[1]) != GRCH37_LENGTHS[Chrom(chrom)]:
                raise ProcessError("Reference VCF contig length contradicts GRCh37")
            if consume:
                consume(line + b"\n")
            continue
        if line.startswith(b"#CHROM"):
            if samples:
                raise ProcessError("Reference VCF has repeated column headers")
            header = line.split(b"\t")
            if (
                header[:9]
                != [
                    b"#CHROM",
                    b"POS",
                    b"ID",
                    b"REF",
                    b"ALT",
                    b"QUAL",
                    b"FILTER",
                    b"INFO",
                    b"FORMAT",
                ]
                or len(header) < 10
            ):
                raise ProcessError("Reference VCF column header is invalid")
            ids = header[9:]
            if any(not value for value in ids) or len(set(ids)) != len(ids):
                raise ProcessError("Reference VCF sample identifiers are empty or duplicated")
            samples = len(ids)
            sample_digest = hashlib.sha256(b"\t".join(ids)).hexdigest()
            digest.update(b"header\t" + b"\t".join(ids) + b"\n")
            if consume:
                consume(line + b"\n")
            continue
        if not samples:
            raise ProcessError("Reference VCF data precedes a valid column header")
        fields = line.split(b"\t", 9)
        if len(fields) != 10 or fields[0].decode("ascii") != chrom:
            raise ProcessError("Reference VCF chromosome/column count is inconsistent")
        try:
            pos = int(fields[1])
        except ValueError:
            raise ProcessError("Reference VCF has an invalid position") from None
        if not last_pos <= pos <= GRCH37_LENGTHS[Chrom(chrom)] or pos <= 0:
            raise ProcessError("Reference VCF is unsorted or outside GRCh37 coordinates")
        last_pos = pos
        if fields[8].split(b":")[0] != b"GT":
            raise ProcessError("Reference VCF must supply GT as the first FORMAT field")
        body = fields[9]
        if body.count(b"\t") != samples - 1:
            raise ProcessError("Reference VCF sample cardinality changes between records")
        if b":" in body:
            body = re.sub(rb":[^\t]*", b"", body)
        if b"." in body or b"/" in body:
            raise ProcessError(
                "Reference has missing or unphased calls; none are silently discarded"
            )
        if chrom == "X" and body.count(b"|") != samples:
            before = body.count(b"|")
            # C byte replacements avoid billions of backreference expansions on the
            # full X panel. Two passes handle adjacent tokens sharing a delimiter.
            padded = b"\t" + body + b"\t"
            for allele in (b"0", b"1"):
                old, new = b"\t" + allele + b"\t", b"\t" + allele + b"|" + allele + b"\t"
                padded = padded.replace(old, new).replace(old, new)
            body = padded[1:-1]
            if body.count(b"|") != samples:
                body = re.sub(rb"(^|(?<=\t))([0-9]+)(?=\t|$)", rb"\2|\2", body)
            doubled += body.count(b"|") - before
        if body.count(b"|") != samples:
            raise ProcessError("Reference is not a complete phased diploid representation")
        end = next((v[4:] for v in fields[7].split(b";") if v.startswith(b"END=")), b".")
        core = b"\t".join((fields[0], fields[1], fields[3], fields[4], end, body)) + b"\n"
        digest.update(core)
        count += 1
        if consume:
            consume(b"\t".join([*fields[:8], b"GT", body]) + b"\n")
        if progress and count % 100_000 == 0:
            progress(count)
    if count == 0 or samples == 0:
        raise ProcessError("Reference VCF is empty")
    if progress:
        progress(count)
    return VcfSummary(count, samples, sample_digest, digest.hexdigest(), doubled)


@dataclass(frozen=True)
class BrefTools:
    java: JavaRuntime
    converter: Path
    decoder: Path
    identities: Mapping[str, Any]

    @classmethod
    def discover(cls, root: Path | None = None) -> BrefTools:
        manifest = tools.load()
        installed = root if root is not None else tools_dir()
        paths: dict[str, Path] = {}
        identities = {}
        for name in ("bref3", "unbref3"):
            tool = manifest.get(name)
            build = tool.build_for("any")
            if build is None or build.archive or tool.kind is not tools.Kind.JAR:
                raise ProcessError("Bref3 tools must be pinned portable jars")
            path = tools.installed_path(installed, tool, build)
            if not path.is_file():
                raise ProcessError(f"Install the pinned tool: genetics tools install --only {name}")
            digest = _sha256(path)
            if digest != build.sha256:
                raise ProcessError("Bref3 tool checksum mismatch; reinstall with --force")
            paths[name] = path.resolve()
            identities[name] = {"version": tool.version, "sha256": digest}
        java = JavaRuntime.discover()
        if java.major < 11:
            raise ProcessError("Pinned bref3 tools require Java 11+; configure JAVA_HOME or PATH.")
        identities["java"] = {"version": java.version, "executable_sha256": _sha256(java.path)}
        return cls(java, paths["bref3"], paths["unbref3"], identities)

    def convert(
        self,
        source: Path,
        destination: Path,
        chrom: str,
        memory_mb: int,
        progress: Callable[[int], None] | None = None,
    ) -> VcfSummary:
        """Stream the full source to the converter, never raw binary to the terminal."""
        produced: list[VcfSummary] = []
        errors: list[BaseException] = []
        latest = [0]
        process: subprocess.Popen[bytes] | None = None
        thread: threading.Thread | None = None
        with destination.open("wb") as output, destination.with_suffix(".log").open("wb") as log:
            try:
                process = subprocess.Popen(
                    [str(self.java.path), f"-Xmx{memory_mb}m", "-jar", str(self.converter)],
                    stdin=subprocess.PIPE,
                    stdout=output,
                    stderr=log,
                    env=_java_env(),
                    creationflags=_CREATION_FLAGS,
                )
                assert process.stdin is not None
                sink = process.stdin

                def feed() -> None:
                    try:
                        opener = gzip.open if source.name.endswith(".gz") else open
                        with opener(source, "rb") as handle:
                            produced.append(
                                _vcf_stream(
                                    handle,
                                    chrom,
                                    consume=sink.write,
                                    progress=lambda n: latest.__setitem__(0, n),
                                )
                            )
                        sink.close()
                    except BaseException as exc:
                        errors.append(exc)
                        with suppress(OSError):
                            sink.close()

                thread = threading.Thread(target=feed, daemon=True)
                thread.start()
                reported = -1
                while process.poll() is None:
                    if errors:
                        if isinstance(errors[0], ProcessError):
                            raise ProcessError(str(errors[0])) from None
                        raise ProcessError(
                            "Could not stream the full reference into bref3"
                        ) from None
                    if progress and latest[0] != reported:
                        progress(latest[0])
                        reported = latest[0]
                    time.sleep(0.2)
                thread.join()
                if errors or process.returncode != 0 or not produced:
                    raise ProcessError("Bref3 conversion failed; inspect the local converter log")
                output.flush()
                os.fsync(output.fileno())
                return produced[0]
            finally:
                if process is not None:
                    _stop(process)  # Handles cancellation and callback failures.
                    if thread is not None:
                        thread.join()

    def verify_round_trip(
        self,
        panel: Path,
        chrom: str,
        expected: VcfSummary,
        memory_mb: int,
        progress: Callable[[int], None] | None = None,
    ) -> None:
        process: subprocess.Popen[bytes] | None = None
        with panel.with_suffix(".verify.log").open("wb") as log:
            try:
                process = subprocess.Popen(
                    [
                        str(self.java.path),
                        f"-Xmx{memory_mb}m",
                        "-jar",
                        str(self.decoder),
                        str(panel),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    env=_java_env(),
                    creationflags=_CREATION_FLAGS,
                )
                assert process.stdout is not None
                observed = _vcf_stream(process.stdout, chrom, progress=progress)
                process.stdout.close()
                code = process.wait()
                if (
                    code != 0
                    or observed.records != expected.records
                    or observed.samples != expected.samples
                    or observed.sample_order_sha256 != expected.sample_order_sha256
                    or observed.semantic_sha256 != expected.semantic_sha256
                ):
                    raise ProcessError(
                        "Bref3 round-trip changed markers, sample order, alleles or GTs"
                    )
            finally:
                if process is not None:
                    _stop(process)
                    if process.stdout is not None:
                        process.stdout.close()


def _chromosomes(params: Mapping[str, Any]) -> tuple[str, ...]:
    values = params.get("chromosomes", list(SUPPORTED))
    if (
        not isinstance(values, (list, tuple))
        or not values
        or any(c not in SUPPORTED for c in values)
        or len(set(values)) != len(values)
    ):
        raise ProcessError("Bref3 chromosome scope must be unique autosomes and/or X")
    return tuple(values)


def _memory(params: Mapping[str, Any]) -> int:
    value = params.get("memory_mb", 8192)
    if type(value) is not int or value < 512:
        raise ProcessError("Bref3 heap must be an integer of at least 512 MiB")
    return value


def _panel_inputs(
    source: Source, root: Path, chromosomes: tuple[str, ...], digests: Mapping[str, str] | None
) -> list[dict[str, Any]]:
    selected = []
    for chrom in chromosomes:
        matches = [
            f
            for f in source.files
            if re.search(rf"(?:^|\.)chr{chrom}\.", f.filename)
            and f.filename.endswith((".vcf", ".vcf.gz"))
        ]
        if len(matches) != 1:
            raise ProcessError(
                "A full VCF must be declared for each requested reference chromosome"
            )
        item = matches[0]
        path = _inside(root, item.filename, label="reference")
        if not path.is_file():
            raise ProcessError("A declared reference chromosome is missing")
        sha = (digests or {}).get(item.filename) or _sha256(path)
        if not re.fullmatch(r"[0-9a-f]{64}", sha) or (item.sha256 and sha != item.sha256):
            raise ProcessError("Reference chromosome digest differs from its source pin")
        selected.append({"chromosome": chrom, "filename": item.filename, "sha256": sha})
    return selected


def _contract(
    declared: PostProcess, source: Source, inputs: list[dict[str, Any]]
) -> dict[str, Any]:
    combined = hashlib.sha256(_canonical_bytes(inputs)).hexdigest()
    return {
        **_expected_provenance(
            declared, Path("reference-set"), combined, input_filename="full-reference-set"
        ),
        "source_id": source.id,
        "source_version": source.version,
        "build": "GRCh37",
        "inputs": inputs,
    }


def declared_panel_provenance(source: Source, declared: PostProcess) -> dict[str, Any]:
    """Bind runtime consumers to the committed manifest/lock without reading raw VCFs."""
    from genetics.paths import reference_lock
    from genetics.refs.lock import read

    locked = read(reference_lock()).sources.get(source.id)
    if locked is None or locked.version != source.version:
        raise ProcessError("Imputation reference lock is missing or has a stale source version")
    inputs = []
    for chrom in _chromosomes(declared.params):
        matches = [
            f
            for f in source.files
            if re.search(rf"(?:^|\.)chr{chrom}\.", f.filename)
            and f.filename.endswith((".vcf", ".vcf.gz"))
        ]
        if len(matches) != 1:
            raise ProcessError("Imputation reference chromosome declaration is ambiguous")
        item = matches[0]
        record = locked.files.get(item.filename)
        if (
            record is None
            or record.url != item.url
            or (item.sha256 is not None and item.sha256 != record.sha256)
        ):
            raise ProcessError("Imputation reference chromosome lock differs from its declaration")
        inputs.append({"chromosome": chrom, "filename": item.filename, "sha256": record.sha256})
    return _contract(declared, source, inputs)


def _map_stream(
    stream: Iterable[bytes], chrom: str, consume: Callable[[bytes], Any] | None = None
) -> tuple[int, int, float]:
    label = "X" if chrom.startswith("X") else chrom
    last_pos = records = 0
    last_cm = -math.inf
    for raw in stream:
        fields = raw.split()
        if len(fields) != 4 or fields[0] != label.encode():
            raise ProcessError("Genetic map has invalid chromosome/column labels")
        try:
            cm, pos = float(fields[2]), int(fields[3])
        except ValueError:
            raise ProcessError("Genetic map has invalid numerical fields") from None
        if (
            not math.isfinite(cm)
            or cm < 0
            or cm < last_cm
            or not last_pos < pos <= GRCH37_LENGTHS[Chrom(label)]
        ):
            raise ProcessError("Genetic map is unsorted, decreasing or outside GRCh37")
        last_pos, last_cm = pos, cm
        if consume:
            consume(raw)
        records += 1
    if not records:
        raise ProcessError("Genetic map is empty")
    return records, last_pos, last_cm


@lru_cache(maxsize=128)
def _map_stats(path: Path, chrom: str, size: int, modified: int) -> tuple[int, int, float]:
    """Validate unchanged maps once per process, using the same stat key as SHA checks."""
    with path.open("rb") as stream:
        return _map_stream(stream, chrom)


def validate_catalog(output: Path, *, expected: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Verify all companions, not just a valid-looking JSON catalog."""
    try:
        if output.is_symlink():
            raise ValueError
        raw: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
        if (
            raw["schema_version"] != 1
            or type(raw["schema_version"]) is not int
            or raw["kind"] not in {"bref3_panel", "genetic_maps"}
        ):
            raise ValueError
        for name in ("files", "entries"):
            if not isinstance(raw[name], list) or not raw[name]:
                raise ValueError
        rows = 0
        names: set[str] = set()
        for entry in raw["files"]:
            if (
                set(entry) != {"path", "sha256", "size_bytes"}
                or entry["path"] in names
                or type(entry["size_bytes"]) is not int
                or entry["size_bytes"] <= 0
                or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            ):
                raise ValueError
            names.add(entry["path"])
            path = _inside(output.parent, entry["path"], label="prepared reference")
            if (
                path.is_symlink()
                or path.stat().st_size != entry["size_bytes"]
                or _cached_sha256(path) != entry["sha256"]
            ):
                raise ValueError
        provenance = validate_provenance(output, expected=expected)
        scopes: set[str] = set()
        referenced: set[str] = set()
        for entry in raw["entries"]:
            if (
                type(entry["records"]) is not int
                or entry["records"] <= 0
                or entry["chromosome"] in scopes
                or entry["path"] not in names
            ):
                raise ValueError
            scopes.add(entry["chromosome"])
            referenced.add(entry["path"])
            rows += entry["records"]
            if raw["kind"] == "bref3_panel":
                stats = entry["summary"]
                if (
                    set(stats) != set(VcfSummary.__dataclass_fields__)
                    or type(stats["records"]) is not int
                    or type(stats["samples"]) is not int
                    or stats["samples"] <= 0
                    or stats["records"] != entry["records"]
                    or type(stats["haploid_calls_doubled"]) is not int
                    or not 0
                    <= stats["haploid_calls_doubled"]
                    <= stats["samples"] * stats["records"]
                    or any(
                        not re.fullmatch(r"[0-9a-f]{64}", stats[k])
                        for k in ("sample_order_sha256", "semantic_sha256")
                    )
                ):
                    raise ValueError
                checkpoint_name = str(
                    Path(entry["path"]).with_name("checkpoint.bref3.json")
                ).replace("\\", "/")
                if checkpoint_name not in names or entry["chromosome"] not in SUPPORTED:
                    raise ValueError
                referenced.add(checkpoint_name)
                checkpoint = json.loads(
                    _inside(output.parent, checkpoint_name, label="checkpoint").read_text(
                        encoding="utf-8"
                    )
                )
                identity = checkpoint["identity"]
                if (
                    checkpoint["round_trip_verified"] is not True
                    or checkpoint["summary"] != stats
                    or identity["schema_version"] != 1
                    or identity["policy"] != POLICY
                    or identity["source_version"] != provenance["source_version"]
                    or identity["source_id"] != provenance["source_id"]
                    or identity["source"] not in provenance["inputs"]
                    or identity["source"]["chromosome"] != entry["chromosome"]
                    or identity["memory_mb"] != provenance["params"].get("memory_mb", 8192)
                    or checkpoint["panel_sha256"]
                    != next(f["sha256"] for f in raw["files"] if f["path"] == entry["path"])
                ):
                    raise ValueError
                for tool_id in ("bref3", "unbref3"):
                    pinned = tools.load().get(tool_id)
                    build = pinned.build_for("any")
                    if build is None or identity["tools"][tool_id] != {
                        "version": pinned.version,
                        "sha256": build.sha256,
                    }:
                        raise ValueError
                java = identity["tools"]["java"]
                if not isinstance(java["version"], str) or not re.fullmatch(
                    r"[0-9a-f]{64}", java["executable_sha256"]
                ):
                    raise ValueError
            elif (
                entry["path"] != f"plink.chr{entry['chromosome']}.GRCh37.map"
                or type(entry["last_position"]) is not int
                or entry["last_position"] <= 0
                or type(entry["last_cm"]) not in (int, float)
                or not math.isfinite(entry["last_cm"])
                or entry["last_cm"] < 0
            ):
                raise ValueError
            else:
                path = _inside(output.parent, entry["path"], label="genetic map")
                stat = path.stat()
                if _map_stats(path, entry["chromosome"], stat.st_size, stat.st_mtime_ns) != (
                    entry["records"],
                    entry["last_position"],
                    entry["last_cm"],
                ):
                    raise ValueError
        if referenced != names:
            raise ValueError
        if type(raw["rows"]) is not int or raw["rows"] != rows:
            raise ValueError
        if raw["kind"] == "bref3_panel":
            if (
                raw["policy"] != POLICY
                or raw["build"] != "GRCh37"
                or raw["par_grch37"] != json.loads(_canonical_bytes(PAR_GRCH37))
                or raw["source"]
                != {"id": provenance["source_id"], "version": provenance["source_version"]}
                or raw["chromosomes"] != [e["chromosome"] for e in raw["entries"]]
                or raw["chromosomes"] != [i["chromosome"] for i in provenance["inputs"]]
                or raw["chromosomes"] != list(_chromosomes(provenance["params"]))
                or len({e["summary"]["sample_order_sha256"] for e in raw["entries"]}) != 1
                or len({e["summary"]["samples"] for e in raw["entries"]}) != 1
            ):
                raise ValueError
        else:
            if (
                scopes != set(MAP_KEYS)
                or raw["build"] != "GRCh37"
                or raw["units"] != "cM"
                or raw["source"]
                != {"id": provenance["source_id"], "version": provenance["source_version"]}
            ):
                raise ValueError
        validate_provenance(output, expected=expected, actual_rows=rows)
        return raw
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ProcessError(
            "Prepared-reference catalog or companion provenance is invalid"
        ) from None


def _file_record(path: Path, base: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(base).as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _prepare_panel(
    declared: PostProcess,
    source: Source,
    source_dir: Path,
    *,
    verify_only: bool,
    progress: ProcessProgressCallback | None,
    input_digests: Mapping[str, str] | None,
) -> ProcessResult:
    output_name = str(declared.params["output"])
    output = _inside(source_dir, output_name, label="catalog")
    chromosomes = _chromosomes(declared.params)
    memory = _memory(declared.params)
    inputs = _panel_inputs(source, source_dir, chromosomes, input_digests)
    expected = _contract(declared, source, inputs)
    if output.is_file():
        try:
            catalog = validate_catalog(output, expected=expected)
            return ProcessResult(
                declared.step,
                ProcessStatus.VERIFIED if verify_only else ProcessStatus.ALREADY_PRESENT,
                output_name,
                catalog["rows"],
            )
        except ProcessError:
            # Verification is read-only; rebuilding may recover the catalog from job checkpoints.
            if verify_only:
                raise
    if verify_only:
        return ProcessResult(
            declared.step,
            ProcessStatus.PENDING,
            output_name,
            detail="full bref3 panels not built yet",
        )
    converter = BrefTools.discover()
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    files = []
    for item in inputs:
        chrom = item["chromosome"]
        root = _inside(output.parent, f"chr{chrom}.bref3-work", label="workspace")
        root.mkdir(parents=True, exist_ok=True)
        completed = _inside(root, "complete", label="completion")
        identity = {
            "schema_version": 1,
            "source": item,
            "source_version": source.version,
            "source_id": source.id,
            "tools": converter.identities,
            "memory_mb": memory,
            "policy": POLICY,
        }
        callback = (
            (lambda n, c=chrom: progress(ProcessProgressEvent(f"convert_to_bref3 chr{c}", n)))
            if progress
            else None
        )
        with _job_lock(root / "job.beagle.lock"):
            if completed.is_dir():
                try:
                    saved = json.loads(
                        (completed / "checkpoint.bref3.json").read_text(encoding="utf-8")
                    )
                    panel = completed / "panel.bref3"
                    if (
                        _canonical_bytes(saved["identity"]) != _canonical_bytes(identity)
                        or saved["round_trip_verified"] is not True
                        or _sha256(panel) != saved["panel_sha256"]
                    ):
                        raise ValueError
                    summary = VcfSummary(**saved["summary"])
                except (OSError, ValueError, TypeError, KeyError):
                    raise ProcessError(
                        f"Completed chromosome checkpoint is invalid for chr{chrom}; "
                        "remove only that chromosome workspace to rebuild"
                    ) from None
            else:
                work = root / f"attempt-{uuid.uuid4().hex}"
                work.mkdir()
                panel = work / "panel.bref3"
                if callback:
                    callback(0)
                summary = converter.convert(
                    _inside(source_dir, item["filename"], label="input"),
                    panel,
                    chrom,
                    memory,
                    callback,
                )
                verify_callback = (
                    (lambda n, c=chrom: progress(ProcessProgressEvent(f"round_trip chr{c}", n)))
                    if progress
                    else None
                )
                converter.verify_round_trip(panel, chrom, summary, memory, verify_callback)
                # Detect mutation of source/tools across conversion before publishing.
                if (
                    _sha256(_inside(source_dir, item["filename"], label="input")) != item["sha256"]
                    or _sha256(converter.converter) != converter.identities["bref3"]["sha256"]
                    or _sha256(converter.decoder) != converter.identities["unbref3"]["sha256"]
                ):
                    raise ProcessError("Reference source or tool changed during preparation")
                _write_json(
                    work / "checkpoint.bref3.json",
                    {
                        "identity": identity,
                        "summary": asdict(summary),
                        "panel_sha256": _sha256(panel),
                        "round_trip_verified": True,
                    },
                )
                if completed.exists():
                    raise ProcessError("Reference completion destination was created concurrently")
                os.rename(work, completed)
                panel = completed / "panel.bref3"
            record = _file_record(panel, output.parent)
            files.extend([record, _file_record(completed / "checkpoint.bref3.json", output.parent)])
            entries.append(
                {
                    "chromosome": chrom,
                    "path": record["path"],
                    "records": summary.records,
                    "summary": asdict(summary),
                }
            )
    if len({e["summary"]["sample_order_sha256"] for e in entries}) != 1:
        raise ProcessError("Reference chromosome panels do not share the same sample order")
    catalog = {
        "schema_version": 1,
        "kind": "bref3_panel",
        "build": "GRCh37",
        "chromosomes": list(chromosomes),
        "source": {"id": source.id, "version": source.version},
        "policy": POLICY,
        "par_grch37": PAR_GRCH37,
        "entries": entries,
        "files": files,
        "rows": sum(e["records"] for e in entries),
    }
    temporary = output.with_name(output.name + ".tmp")
    _write_json(temporary, catalog)
    os.replace(temporary, output)
    _write_provenance(output, expected, catalog["rows"])
    validate_catalog(output, expected=expected)
    return ProcessResult(declared.step, ProcessStatus.CREATED, output_name, catalog["rows"])


def _prepare_maps(
    declared: PostProcess,
    source: Source,
    source_dir: Path,
    *,
    verify_only: bool,
    progress: ProcessProgressCallback | None,
    input_digests: Mapping[str, str] | None,
) -> ProcessResult:
    input_name = str(declared.params["input"])
    source_path = _inside(source_dir, input_name, label="map archive")
    output_name = str(declared.params["output"])
    output = _inside(source_dir, output_name, label="map catalog")
    if not source_path.is_file():
        raise ProcessError("GRCh37 map archive is missing")
    sha = (input_digests or {}).get(input_name) or _sha256(source_path)
    pin = next((f.sha256 for f in source.files if f.filename == input_name), None)
    if pin and pin != sha:
        raise ProcessError("Genetic map archive differs from its pinned SHA256")
    expected = {
        **_expected_provenance(declared, source_path, sha),
        "source_id": source.id,
        "source_version": source.version,
        "build": "GRCh37",
    }
    if output.is_file():
        try:
            catalog = validate_catalog(output, expected=expected)
            return ProcessResult(
                declared.step,
                ProcessStatus.VERIFIED if verify_only else ProcessStatus.ALREADY_PRESENT,
                output_name,
                catalog["rows"],
            )
        except ProcessError:
            if verify_only:
                raise
    if verify_only:
        return ProcessResult(
            declared.step,
            ProcessStatus.PENDING,
            output_name,
            detail="GRCh37 genetic maps not prepared yet",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    files = []
    with zipfile.ZipFile(source_path) as archive:
        required = [f"plink.chr{c}.GRCh37.map" for c in MAP_KEYS]
        if any(archive.namelist().count(name) != 1 for name in required):
            raise ProcessError("Genetic map archive is incomplete or has duplicate map members")
        for chrom, name in zip(MAP_KEYS, required, strict=True):
            target = _inside(output.parent, name, label="genetic map")
            temporary = target.with_name(target.name + ".tmp")
            with archive.open(name) as source_handle, temporary.open("wb") as out:
                records, last_pos, last_cm = _map_stream(source_handle, chrom, out.write)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, target)
            record = _file_record(target, output.parent)
            files.append(record)
            entries.append(
                {
                    "chromosome": chrom,
                    "path": record["path"],
                    "records": records,
                    "last_position": last_pos,
                    "last_cm": last_cm,
                }
            )
            if progress:
                progress(ProcessProgressEvent(declared.step, sum(e["records"] for e in entries)))
    if _sha256(source_path) != sha:
        raise ProcessError("Genetic map archive changed during preparation")
    catalog = {
        "schema_version": 1,
        "kind": "genetic_maps",
        "build": "GRCh37",
        "source": {"id": source.id, "version": source.version},
        "units": "cM",
        "entries": entries,
        "files": files,
        "rows": sum(e["records"] for e in entries),
    }
    temporary = output.with_name(output.name + ".tmp")
    _write_json(temporary, catalog)
    os.replace(temporary, output)
    _write_provenance(output, expected, catalog["rows"])
    validate_catalog(output, expected=expected)
    return ProcessResult(declared.step, ProcessStatus.CREATED, output_name, catalog["rows"])


def run_preparation(
    declared: PostProcess,
    source: Source,
    source_dir: Path,
    *,
    verify_only: bool,
    progress: ProcessProgressCallback | None,
    input_digests: Mapping[str, str] | None,
) -> ProcessResult:
    try:
        output = _inside(source_dir, declared.params["output"], label="catalog")
        if not verify_only:
            output.parent.mkdir(parents=True, exist_ok=True)
        guard = (
            nullcontext()
            if verify_only
            else _job_lock(output.with_name(output.name + ".beagle.lock"))
        )
        with guard:
            prepare = _prepare_panel if declared.step == "convert_to_bref3" else _prepare_maps
            return prepare(
                declared,
                source,
                source_dir,
                verify_only=verify_only,
                progress=progress,
                input_digests=input_digests,
            )
    except BeagleBusyError:
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            str(declared.params["output"]),
            detail="A reference-preparation workspace is in use; retry after its writer finishes.",
        )
    except ProcessError as exc:
        return ProcessResult(
            declared.step, ProcessStatus.FAILED, str(declared.params["output"]), detail=str(exc)
        )
    except (
        OSError,
        EOFError,
        UnicodeError,
        ValueError,
        BeagleError,
        zipfile.BadZipFile,
    ):
        # Converter/parser errors can quote genotypes. Only categorical diagnostics escape.
        return ProcessResult(
            declared.step,
            ProcessStatus.FAILED,
            str(declared.params["output"]),
            detail="Full-reference preparation failed; inspect local logs and integrity.",
        )
