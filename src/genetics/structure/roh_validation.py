"""Consistency checks for saved schema-2 ROH measurements, without reference access."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from genetics.structure.roh import Interval, RohError, RohSettings


def _interval(raw: Any) -> Interval:
    if (
        not isinstance(raw, Mapping)
        or set(raw) != {"chrom", "start", "end", "n_snps"}
        or not isinstance(raw["chrom"], str)
        or raw["chrom"] not in {str(i) for i in range(1, 23)}
        or any(type(raw[k]) is not int or raw[k] < 1 for k in ("start", "end", "n_snps"))
        or raw["start"] > raw["end"]
    ):
        raise RohError("invalid saved autosomal ROH interval")
    return Interval(raw["chrom"], raw["start"], raw["end"], raw["n_snps"])


def _disjoint(intervals: list[Interval]) -> None:
    previous: dict[str, int] = {}
    for interval in sorted(intervals, key=lambda i: (int(i.chrom), i.start)):
        if interval.start <= previous.get(interval.chrom, 0):
            raise RohError("saved ROH intervals overlap")
        previous[interval.chrom] = interval.end


def validate_result(data: Mapping[str, Any]) -> None:
    """Check relationships omitted by the bundle's top-level type checks.

    Use the recorded policy and schema-2 arithmetic, never current defaults or
    generated prose. This validates an immutable result without recomputing it.
    """
    if type(data["schema_version"]) is not int or data["schema_version"] != 2:
        raise RohError("unsupported saved ROH schema")
    raw_settings = data["settings"]
    if set(raw_settings) != {f.name for f in fields(RohSettings)}:
        raise RohError("invalid saved ROH settings")
    settings = RohSettings(**raw_settings)
    intervals = [_interval(i) for i in data["assayed_intervals"]]
    segments = [_interval(i) for i in data["segments"]]
    _disjoint(intervals)
    _disjoint(segments)
    if any(
        i.length_bp < settings.min_kb * 1000
        or i.n_snps < max(settings.min_snps, settings.window_snps)
        for i in intervals
    ):
        raise RohError("saved assay interval does not meet its recorded policy")
    for segment in segments:
        if (
            segment.length_bp < settings.min_kb * 1000
            or segment.n_snps < settings.min_snps
            or segment.length_bp > settings.density_kb * 1000 * segment.n_snps
            or not any(
                i.chrom == segment.chrom
                and i.start <= segment.start <= segment.end <= i.end
                and segment.n_snps <= i.n_snps
                for i in intervals
            )
        ):
            raise RohError("saved ROH segment does not meet its recorded assay or policy")
    if (
        data["roh_count"] != len(segments)
        or data["total_roh_bp"] != sum(i.length_bp for i in segments)
        or data["longest_roh_bp"] != max((i.length_bp for i in segments), default=0)
        or data["denominator_bp"] != sum(i.length_bp for i in intervals)
        or data["chromosomes_assayed"] != sorted({i.chrom for i in intervals}, key=int)
        or not data["n_missing_calls"]
        <= data["n_analyzed_markers"]
        <= data["n_filtered_reference_markers"]
        <= data["n_array_positions"]
        or sum(i.n_snps for i in intervals) > data["n_analyzed_markers"]
    ):
        raise RohError("saved ROH totals disagree with intervals or marker counts")
    windows = data["window_support"]
    if len(windows) != len(intervals):
        raise RohError("saved ROH window support does not cover the recorded assay")
    density = observed = 0
    for raw, interval in zip(windows, intervals, strict=True):
        if (
            not isinstance(raw, Mapping)
            or set(raw) != {"interval", "density_windows", "observed_windows"}
            or _interval(raw["interval"]) != interval
            or any(type(raw[k]) is not int for k in ("density_windows", "observed_windows"))
            or not 0
            <= raw["observed_windows"]
            <= raw["density_windows"]
            <= max(0, interval.n_snps - settings.window_snps + 1)
        ):
            raise RohError("invalid saved ROH window support")
        density += raw["density_windows"]
        observed += raw["observed_windows"]
    expected = (
        "insufficient_coverage"
        if not intervals or (not density and not segments)
        else "computed"
        if segments or observed
        else "insufficient_calls"
    )
    if data["status"] != expected:
        raise RohError("saved ROH status disagrees with assay support")
    if any(
        not isinstance(data[k], str) or not data[k].strip()
        for k in ("engine_version", "denominator_definition")
    ):
        raise RohError("saved ROH needs its engine and denominator metadata")
    tools = data["tools"]
    if set(tools) != {"plink2", "plink19"} or any(
        not isinstance(v, str) or not v.strip() for v in tools.values()
    ):
        raise RohError("saved ROH needs both native tool versions")
    if not data["warnings"] or any(
        not isinstance(w, str) or not w.strip() for w in data["warnings"]
    ):
        raise RohError("saved ROH needs its assay caveats")
    for reference in data["references"]:
        if not isinstance(reference, Mapping) or any(
            not isinstance(reference.get(k), str) or not reference[k].strip()
            for k in ("population", "version", "status")
        ):
            raise RohError("invalid saved ROH reference metadata")
        digests = reference.get("input_sha256")
        if (
            not isinstance(digests, Mapping)
            or not digests
            or any(
                not isinstance(role, str)
                or not role.strip()
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for role, digest in digests.items()
            )
        ):
            raise RohError("saved ROH needs its reference input digests")
