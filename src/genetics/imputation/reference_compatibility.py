"""Source-verified, lossless native reference representation and frozen proof."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import uuid
import zlib
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from genetics.external.beagle import _input
from genetics.refs.imputation import BrefTools, VcfSummary, _vcf_stream
from genetics.refs.postprocess import ProcessError

from .reference import ReferenceMarkers, read_markers
from .reference_stream import duplicate_rows
from .target import ImputationError

METHOD = "lossless-native-reference-duplicates-v1"


def _sha(value: Any) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError


def _duplicates(values: Any) -> dict[tuple[int, str, str], int]:
    result = {}
    if not isinstance(values, list):
        raise ValueError
    for pos, ref, alt, copies in values:
        if (
            type(pos) is not int
            or pos < 1
            or not isinstance(ref, str)
            or not ref
            or not isinstance(alt, str)
            or not alt
            or type(copies) is not int
            or copies < 2
            or (pos, ref, alt) in result
        ):
            raise ValueError
        result[(pos, ref, alt)] = copies
    if duplicate_rows(result) != values:
        raise ValueError
    return result


def validate_proof(value: Mapping[str, Any]) -> dict[tuple[int, str, str], int]:
    """Validate frozen relationships without consulting today's panel or tools."""
    if set(value) != {
        "schema_version",
        "method",
        "source",
        "native",
        "source_duplicates",
        "native_duplicates",
        "folded",
    }:
        raise ValueError
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["method"] != METHOD
    ):
        raise ValueError
    for role in ("source", "native"):
        item = value[role]
        if set(item) != {"sha256", "size_bytes", "summary"}:
            raise ValueError
        _sha(item["sha256"])
        if type(item["size_bytes"]) is not int or item["size_bytes"] < 1:
            raise ValueError
        summary = item["summary"]
        if set(summary) != set(VcfSummary.__dataclass_fields__):
            raise ValueError
        for k in ("records", "samples", "haploid_calls_doubled"):
            if type(summary[k]) is not int or summary[k] < (
                0 if k == "haploid_calls_doubled" else 1
            ):
                raise ValueError
        for k in ("semantic_sha256", "sample_order_sha256"):
            _sha(summary[k])
    source = _duplicates(value["source_duplicates"])
    native = _duplicates(value["native_duplicates"])
    if (
        sum(source.values()) > value["source"]["summary"]["records"]
        or sum(native.values()) > value["native"]["summary"]["records"]
    ):
        raise ValueError
    removed: Counter[tuple[int, str, str]] = Counter()
    allocated: Counter[tuple[int, str, str]] = Counter()
    seen = set()
    if not isinstance(value["folded"], list):
        raise ValueError
    for group in value["folded"]:
        if set(group) != {"position", "ref", "alt", "end", "copies", "gt_sha256"}:
            raise ValueError
        key = group["position"], group["ref"], group["alt"]
        if type(group["position"]) is not int:
            raise ValueError
        identity = (*key, group["end"])
        if identity in seen or key not in source or not isinstance(group["end"], str):
            raise ValueError
        if type(group["copies"]) is not int or not 2 <= group["copies"] <= source[key]:
            raise ValueError
        _sha(group["gt_sha256"])
        seen.add(identity)
        allocated[key] += group["copies"]
        removed[key] += group["copies"] - 1
    if any(allocated[k] > n for k, n in source.items()):
        raise ValueError
    if {k: n - removed[k] for k, n in source.items() if n - removed[k] > 1} != native:
        raise ValueError
    first, second = value["source"]["summary"], value["native"]["summary"]
    if first["records"] - sum(removed.values()) != second["records"]:
        raise ValueError
    if any(first[k] != second[k] for k in ("samples", "sample_order_sha256")):
        raise ValueError
    if not removed and value["source"] != value["native"]:
        raise ValueError
    return native


def _descriptor(path: Path, summary: VcfSummary) -> dict[str, Any]:
    item = _input(path, "reference")
    assert item is not None
    return {k: item[k] for k in ("sha256", "size_bytes")} | {"summary": asdict(summary)}


def compatibility_identity(proof: Mapping[str, Any], tools: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "method": METHOD,
        "source": proof["source"],
        "summary": proof["native"]["summary"],
        "folded": proof["folded"],
        "tools": tools,
    }


def compatibility_key(identity: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def prepare_native_reference(
    tools: BrefTools,
    panel: Path,
    chrom: str,
    expected: VcfSummary,
    markers: ReferenceMarkers,
    root: Path,
    memory_mb: int,
    progress: Callable[[str], None],
) -> tuple[Path, dict[str, Any] | None]:
    if not markers.duplicates:
        return panel, None
    source = _descriptor(panel, expected)
    stream = markers.stream
    proof = {
        "schema_version": 1,
        "method": METHOD,
        "source": source,
        "native": source,
        "source_duplicates": duplicate_rows(markers.duplicates),
        "native_duplicates": duplicate_rows(stream.native_duplicates),
        "folded": stream.folded,
    }
    if not stream.folded:
        validate_proof(proof)
        return panel, proof
    summary = stream.summary()
    proof["native"] = {**source, "summary": asdict(summary)}
    identity = compatibility_identity(proof, tools.identities)
    key = compatibility_key(identity)
    directory = root / "native-reference" / chrom / key
    if not directory.resolve().is_relative_to(root.resolve()):
        raise ImputationError("Native reference cache escapes the imputation workspace.")
    complete = directory / "complete"
    native = complete / "native-reference.vcf.gz"
    if complete.exists():
        if (
            complete.is_symlink()
            or native.is_symlink()
            or (complete / "compatibility.run.json").is_symlink()
        ):
            raise ImputationError("Native reference cache cannot be a symbolic link.")
        try:
            stored = json.loads((complete / "compatibility.run.json").read_bytes())
            with gzip.open(native, "rb") as handle:
                observed = _vcf_stream(handle, chrom)
            proof["native"] = _descriptor(native, summary)
        except (OSError, EOFError, ValueError, UnicodeError, ProcessError, zlib.error):
            raise ImputationError(
                "Native reference compatibility cache is damaged; refused."
            ) from None
        if stored != {"identity": identity, "proof": proof} or observed != summary:
            raise ImputationError("Native reference compatibility cache is damaged; refused.")
    else:
        directory.mkdir(parents=True, exist_ok=True)
        attempt = directory / f"attempt-{uuid.uuid4().hex}"
        attempt.mkdir()
        pending = attempt / native.name
        progress("Preparing lossless native reference representation")
        with (
            pending.open("wb") as file,
            gzip.GzipFile(filename="", fileobj=file, mode="wb", mtime=0, compresslevel=1) as sink,
        ):
            observed_markers = read_markers(
                tools,
                panel,
                chrom,
                expected,
                set(),
                attempt / "decode.log",
                memory_mb,
                progress,
                native_sink=sink.write,
            )
        if (
            observed_markers.stream.summary() != summary
            or observed_markers.stream.folded != stream.folded
            or _descriptor(panel, expected) != source
        ):
            raise ImputationError("Reference changed during lossless representation; refused.")
        with gzip.open(pending, "rb") as handle:
            if _vcf_stream(handle, chrom) != summary:
                raise ImputationError("Native reference changed genetic observations; refused.")
        proof["native"] = _descriptor(pending, summary)
        validate_proof(proof)
        (attempt / "compatibility.run.json").write_text(
            json.dumps({"identity": identity, "proof": proof}, sort_keys=True), encoding="utf-8"
        )
        attempt.replace(complete)
    validate_proof(proof)
    return native, proof
