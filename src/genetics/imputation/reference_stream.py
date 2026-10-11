"""Lossless representation of native-equal reference records, never GT selection."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from typing import Any

from genetics.refs.imputation import VcfSummary

from .target import ImputationError


class ReferenceStream:
    """Consumes already validated, normalized GT lines; buffers one coordinate only."""

    def __init__(self, sink: Callable[[bytes], Any] | None = None) -> None:
        self.sink = sink
        self.position: int | None = None
        self.group: dict[tuple[bytes, bytes, bytes], tuple[bytes, bytes, int]] = {}
        self.source_counts: Counter[tuple[int, str, str]] = Counter()
        self.duplicates: dict[tuple[int, str, str], int] = {}
        self.native_duplicates: dict[tuple[int, str, str], int] = {}
        self.folded: list[dict[str, Any]] = []
        self.digest = hashlib.sha256()
        self.samples = 0
        self.sample_sha = ""
        self.records = 0

    def consume(self, raw: bytes) -> None:
        fields = raw.rstrip(b"\r\n").split(b"\t", 9)
        if raw.startswith(b"#"):
            if raw.startswith(b"#CHROM"):
                ids = raw.rstrip(b"\r\n").split(b"\t")[9:]
                self.samples = len(ids)
                self.sample_sha = hashlib.sha256(b"\t".join(ids)).hexdigest()
                self.digest.update(b"header\t" + b"\t".join(ids) + b"\n")
            if self.sink:
                self.sink(raw)
            return
        pos = int(fields[1])
        if self.position != pos:
            self.finish_position()
            self.position = pos
        end = next((v[4:] for v in fields[7].split(b";") if v.startswith(b"END=")), b".")
        key = fields[3], fields[4], end
        self.source_counts[(pos, fields[3].decode(), fields[4].decode())] += 1
        previous = self.group.get(key)
        if previous is None:
            self.group[key] = raw, fields[9], 1
        else:
            first, gt, count = previous
            if gt != fields[9]:
                raise ImputationError(
                    "Reference repeats a native marker with conflicting phased calls; refused."
                )
            self.group[key] = first, gt, count + 1

    def finish_position(self) -> None:
        if self.position is None:
            return
        native_counts: Counter[tuple[int, str, str]] = Counter()
        for (ref, alt, end), (raw, gt, copies) in self.group.items():
            key = self.position, ref.decode(), alt.decode()
            native_counts[key] += 1
            fields = raw.rstrip(b"\r\n").split(b"\t", 9)
            self.digest.update(b"\t".join((fields[0], fields[1], ref, alt, end, gt)) + b"\n")
            self.records += 1
            if self.sink:
                self.sink(raw)
            if copies > 1:
                self.folded.append(
                    {
                        "position": self.position,
                        "ref": ref.decode(),
                        "alt": alt.decode(),
                        "end": end.decode(),
                        "copies": copies,
                        "gt_sha256": hashlib.sha256(gt).hexdigest(),
                    }
                )
        self.duplicates.update({k: n for k, n in self.source_counts.items() if n > 1})
        self.native_duplicates.update({k: n for k, n in native_counts.items() if n > 1})
        self.group.clear()
        self.source_counts.clear()

    def summary(self) -> VcfSummary:
        self.finish_position()
        return VcfSummary(self.records, self.samples, self.sample_sha, self.digest.hexdigest(), 0)


def duplicate_rows(values: dict[tuple[int, str, str], int]) -> list[list[Any]]:
    return [[*key, count] for key, count in sorted(values.items())]
