"""Durable full-dosage snapshots and exact used provenance (M8.6).

All files here are private. Saved validation reads only the bundle, never the current
reference manifest, tool installation or original stage paths.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from genetics.external.beagle import BeagleOptions
from genetics.qc.report import InferredSex

from .context import OUTCOMES, REGIONS, ImputationContext
from .dosages import DosageRecord, iter_records
from .pipeline import ImputationResult
from .quality import ImputationEvidence
from .target import ImputationError, regions

PROVENANCE_NAME = "imputation.provenance.run.json"
PANEL_NAME = "imputation.panel.catalog.run.json"
MAP_NAME = "imputation.map.catalog.run.json"
CATALOG_NAMES = (PANEL_NAME, MAP_NAME)


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def is_dosage_name(name: str) -> bool:
    return isinstance(name, str) and name in {f"{r}.dosages.jsonl.gz" for r in REGIONS}


def _sha(value: Any) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, dict):
        raise ValueError
    return raw


def _summary(stage: Mapping[str, Any], resumed: bool) -> dict[str, Any]:
    return {
        "status": "computed" if stage["files"] else "no_eligible_jobs",
        "jobs": len(stage["files"]),
        "resumed": resumed,
        **{
            k: stage[k]
            for k in ("records", "sources", "ploidy_conflicts", "regions", "unsupported_positions")
        },
    }


def _input(raw: Mapping[str, Any]) -> None:
    if (
        set(raw) != {"path", "sha256", "size_bytes"}
        or not isinstance(raw["path"], str)
        or not raw["path"]
    ):
        raise ValueError
    _sha(raw["sha256"])
    if _count(raw["size_bytes"]) == 0:
        raise ValueError


def _metadata(stage: Mapping[str, Any], execution: Mapping[str, Any]) -> None:
    if (
        set(stage)
        != {
            "schema_version",
            "contract",
            "panel_source",
            "map_source",
            "files",
            "jobs",
            "regions",
            "unsupported_positions",
            "records",
            "sources",
            "ploidy_conflicts",
            "limitations",
        }
        or type(stage["schema_version"]) is not int
        or stage["schema_version"] != 1
    ):
        raise ValueError
    if (
        execution["mode"] != "enabled"
        or _summary(stage, execution["summary"]["resumed"]) != execution["summary"]
    ):
        raise ValueError
    ImputationContext.enabled(_summary(stage, execution["summary"]["resumed"]))
    contract = stage["contract"]
    if (
        set(contract)
        != {
            "schema_version",
            "target_sha256",
            "sex",
            "options",
            "panel_catalog",
            "map_catalog",
            "beagle",
            "bref",
            "tool_file_hashes",
            "policy",
        }
        or type(contract["schema_version"]) is not int
        or contract["schema_version"] != 1
    ):
        raise ValueError
    _sha(contract["target_sha256"])
    sex = InferredSex(contract["sex"])
    options = BeagleOptions(**contract["options"])
    if not options.impute or options.chrom is not None or options.target_ploidy != 2:
        raise ValueError
    if (
        contract["policy"]
        != "full-panel; two-stage; preserve-direct; split-X; native-target-ploidy-v2"
    ):
        raise ValueError
    hashes = contract["tool_file_hashes"]
    if not isinstance(hashes, list) or len(hashes) != 5:
        raise ValueError
    for sha in hashes:
        _sha(sha)
    beagle, bref = contract["beagle"], contract["bref"]
    java = beagle["java"]
    if (
        not isinstance(beagle["version"], str)
        or not beagle["version"]
        or beagle["sha256"] != hashes[0]
    ):
        raise ValueError
    if (
        type(java["major"]) is not int
        or java["major"] < 8
        or not isinstance(java["version"], str)
        or not java["version"]
    ):
        raise ValueError
    for i, name in enumerate(("bref3", "unbref3"), start=2):
        if (
            bref[name]["sha256"] != hashes[i]
            or not isinstance(bref[name]["version"], str)
            or not bref[name]["version"]
        ):
            raise ValueError
    if (
        bref["java"]["executable_sha256"] != hashes[4]
        or not isinstance(bref["java"]["version"], str)
        or not bref["java"]["version"]
    ):
        raise ValueError
    for name in ("panel_catalog", "map_catalog"):
        info = contract[name]
        if set(info) != {"path", "sha256"} or not isinstance(info["path"], str) or not info["path"]:
            raise ValueError
        _sha(info["sha256"])
    for source in (stage["panel_source"], stage["map_source"]):
        if set(source) != {"id", "version"} or any(
            not isinstance(v, str) or not v for v in source.values()
        ):
            raise ValueError
    if not isinstance(stage["limitations"], list) or any(
        not isinstance(v, str) or not v for v in stage["limitations"]
    ):
        raise ValueError
    jobs, files = stage["jobs"], stage["files"]
    if not isinstance(jobs, list) or not isinstance(files, list) or len(jobs) != len(files):
        raise ValueError
    reports = {r["region"]: r for r in stage["regions"] if r["status"] == "computed"}
    names: set[str] = set()
    totals: Counter[str] = Counter()
    for job, file in zip(jobs, files, strict=True):
        if set(job) != {"region", "decisions", "phase", "impute"}:
            raise ValueError
        region = job["region"]
        expected = next(r for r in regions(region["chrom"], sex) if r.name == region["name"])
        if (
            region != asdict(expected)
            or region["name"] not in reports
            or expected.ploidy is None
            or type(region["ploidy"]) is not int
        ):
            raise ValueError
        if set(file) != {"name", "sha256", "records", "sources", "ploidy_conflicts"}:
            raise ValueError
        name = file["name"]
        if (
            not is_dosage_name(name)
            or name != f"{region['name']}.dosages.jsonl.gz"
            or name in names
        ):
            raise ValueError
        names.add(name)
        _sha(file["sha256"])
        if _count(file["records"]) < 2 or _count(file["ploidy_conflicts"]) != 0:
            raise ValueError
        if sum(_count(v) for v in file["sources"].values()) != file["records"]:
            raise ValueError
        report = reports[region["name"]]
        decisions = job["decisions"]
        if not isinstance(decisions, list) or len(decisions) != report["positions"]:
            raise ValueError
        previous = 0
        outcomes: Counter[str] = Counter()
        for pos, outcome in decisions:
            if (
                type(pos) is not int
                or not max(previous + 1, region["start"]) <= pos <= region["end"]
                or outcome not in OUTCOMES
            ):
                raise ValueError
            previous = pos
            outcomes[outcome] += 1
        if dict(outcomes) != report["outcomes"]:
            raise ValueError
        if (
            file["sources"].get("direct", 0) != report["called"]
            or file["sources"].get("imputed_no_call", 0) != report["written"] - report["called"]
        ):
            raise ValueError
        totals.update(file["sources"])
        for phase_only, key in ((True, "phase"), (False, "impute")):
            checkpoint = job[key]
            if set(checkpoint) != {"contract", "files", "elapsed_seconds"}:
                raise ValueError
            elapsed = checkpoint["elapsed_seconds"]
            if (
                isinstance(elapsed, bool)
                or not isinstance(elapsed, int | float)
                or not math.isfinite(elapsed)
                or elapsed < 0
            ):
                raise ValueError
            used = checkpoint["contract"]
            if (type(used["schema_version"]) is not int or used["schema_version"] != 1) or used[
                "beagle"
            ] != {k: beagle[k] for k in ("version", "sha256")}:
                raise ValueError
            if used["java"] != {
                "version": java["version"],
                "major": java["major"],
                "executable_sha256": hashes[1],
            }:
                raise ValueError
            used_options = BeagleOptions(**used["options"])
            if asdict(used_options) != asdict(
                replace(
                    options,
                    impute=not phase_only,
                    chrom=expected.interval,
                    target_ploidy=expected.ploidy,
                )
            ):
                raise ValueError
            if set(used["inputs"]) != {"gt", "ref", "map"}:
                raise ValueError
            for item in used["inputs"].values():
                _input(item)
            if set(checkpoint["files"]) != {"result.vcf.gz", "result.log"}:
                raise ValueError
            for info in checkpoint["files"].values():
                _sha(info["sha256"])
                if _count(info["size_bytes"]) == 0:
                    raise ValueError
        first, second = (job[k]["contract"]["inputs"] for k in ("phase", "impute"))
        if (
            first["ref"] != second["ref"]
            or first["map"] != second["map"]
            or second["gt"]["sha256"] != job["phase"]["files"]["result.vcf.gz"]["sha256"]
        ):
            raise ValueError
    if (
        names != {f"{name}.dosages.jsonl.gz" for name in reports}
        or dict(totals) != stage["sources"]
    ):
        raise ValueError
    if sum(f["records"] for f in files) != stage["records"] or stage["ploidy_conflicts"] != 0:
        raise ValueError


def _catalogs(directory: Path, stage: Mapping[str, Any]) -> None:
    for key, name, kind, source_key in (
        ("panel_catalog", PANEL_NAME, "bref3_panel", "panel_source"),
        ("map_catalog", MAP_NAME, "genetic_maps", "map_source"),
    ):
        path = directory / name
        if digest(path) != stage["contract"][key]["sha256"]:
            raise ValueError
        raw = _load(path)
        if (
            type(raw["schema_version"]) is not int
            or raw["schema_version"] != 1
            or raw["kind"] != kind
            or raw["build"] != "GRCh37"
            or raw["source"] != stage[source_key]
        ):
            raise ValueError
        entries = {e["chromosome"]: e for e in raw["entries"]}
        files = {f["path"]: f for f in raw["files"]}
        if len(entries) != len(raw["entries"]) or len(files) != len(raw["files"]):
            raise ValueError
        for job in stage["jobs"]:
            region = job["region"]
            item = entries[region["chrom"] if key == "panel_catalog" else region["map_key"]]
            expected = files[item["path"]]
            _sha(expected["sha256"])
            for phase in ("phase", "impute"):
                used = job[phase]["contract"]["inputs"]["ref" if key == "panel_catalog" else "map"]
                if (
                    used["sha256"] != expected["sha256"]
                    or used["size_bytes"] != expected["size_bytes"]
                ):
                    raise ValueError


def _wanted(cards: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int], list[Mapping[str, Any]]]:
    wanted: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for card in cards:
        multi = card.get("multi_marker")
        for entry in multi["markers"] if isinstance(multi, Mapping) else [card]:
            observation = entry.get("observation")
            if isinstance(observation, Mapping) and observation.get("imputation") is not None:
                variant = entry["variant"]
                wanted.setdefault((variant["chrom"], variant["pos_grch37"]), []).append(entry)
    return wanted


def _payloads(
    directory: Path,
    stage: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    progress: Callable[[str], None] | None = None,
) -> None:
    wanted = _wanted(cards)
    found: Counter[tuple[str, int]] = Counter()
    for job, file in zip(stage["jobs"], stage["files"], strict=True):
        emit = progress or (lambda _: None)
        emit("Validating saved imputation dosage evidence")
        heartbeat = time.monotonic()
        path = directory / file["name"]
        if path.is_symlink() or digest(path) != file["sha256"]:
            raise ValueError
        region = job["region"]
        decisions = dict(job["decisions"])
        eligible = {
            p for p, d in decisions.items() if d in {"as_written", "complemented", "no_call"}
        }
        retained: set[int] = set()
        counts: Counter[str] = Counter()
        previous = 0
        at_position: set[tuple[str, tuple[str, ...]]] = set()
        for index, record in enumerate(iter_records(path), start=1):
            if progress and index % 100_000 == 0 and time.monotonic() - heartbeat >= 30:
                emit("Validating saved imputation dosage evidence")
                heartbeat = time.monotonic()
            pos = record.pos_grch37
            if (
                record.chrom != region["chrom"]
                or record.ploidy != region["ploidy"]
                or not max(previous, region["start"]) <= pos <= region["end"]
            ):
                raise ValueError
            if pos != previous:
                at_position.clear()
            previous = pos
            variant_key = (record.ref, record.alt)
            if variant_key in at_position:
                raise ValueError
            at_position.add(variant_key)
            decision = decisions.get(pos)
            source = (
                "direct"
                if decision in {"as_written", "complemented"}
                else ("imputed_no_call" if decision == "no_call" else "imputed_untyped")
            )
            if record.source != source or record.array_outcome != decision:
                raise ValueError
            if pos in eligible:
                if pos in retained:
                    raise ValueError
                retained.add(pos)
            counts[source] += 1
            locus = (record.chrom, pos)
            for card in wanted.get(locus, []):
                detail = card["observation"]["imputation"]
                if record.ref != detail["ref"] or list(record.alt) != detail["alt"]:
                    continue
                if ImputationEvidence.from_record(record).to_dict() != detail:
                    raise ValueError
                assert record.genotype is not None
                bases = (record.ref, *record.alt)
                genotype = "".join(sorted(bases[i] for i in record.genotype))
                if record.ploidy == 1:
                    genotype *= 2
                if card["match"]["observed_genotype"] != genotype:
                    raise ValueError
                # Count once per record, even when multiple cards name the same locus.
            if locus in wanted and any(
                record.ref == c["observation"]["imputation"]["ref"]
                and list(record.alt) == c["observation"]["imputation"]["alt"]
                for c in wanted[locus]
            ):
                found[locus] += 1
        if (
            retained != eligible
            or dict(counts) != file["sources"]
            or sum(counts.values()) != file["records"]
        ):
            raise ValueError
    if any(found[locus] != 1 for locus in wanted):
        raise ValueError


def validate_snapshot(
    directory: Path,
    raw: Mapping[str, Any],
    execution: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    recorded: Mapping[str, Any],
    progress: Callable[[str], None] | None = None,
) -> None:
    """Validate only saved bytes; all exceptions are private categorical failures."""
    try:
        if (
            set(raw) != {"schema_version", "status", "stage"}
            or type(raw["schema_version"]) is not int
            or raw["schema_version"] != 1
        ):
            raise ValueError
        if raw["status"] != "recorded":
            if raw["stage"] is not None or raw["status"] != (
                "disabled" if execution["mode"] == "disabled" else "not_recorded"
            ):
                raise ValueError
            expected_files = set()
        else:
            stage = raw["stage"]
            _metadata(stage, execution)
            expected_files = {*CATALOG_NAMES, *(f["name"] for f in stage["files"])}
            for key, name in (("panel_catalog", PANEL_NAME), ("map_catalog", MAP_NAME)):
                if recorded.get(name) != stage["contract"][key]["sha256"]:
                    raise ValueError
            if any(recorded.get(f["name"]) != f["sha256"] for f in stage["files"]):
                raise ValueError
            _catalogs(directory, stage)
            _payloads(directory, stage, cards, progress)
        present = {n for n in recorded if n in CATALOG_NAMES or is_dosage_name(n)}
        if present != expected_files:
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, StopIteration):
        raise ImputationError(
            "Saved full imputation provenance or dosage evidence is invalid."
        ) from None


def publish(
    directory: Path,
    execution: Mapping[str, Any],
    result: ImputationResult | None,
    cards: Sequence[Mapping[str, Any]],
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Copy independent bytes into the bundle's atomic staging directory."""
    raw: dict[str, Any] = {
        "schema_version": 1,
        "status": "disabled" if execution["mode"] == "disabled" else "not_recorded",
        "stage": None,
    }
    hashes: dict[str, str] = {}
    try:
        if result is not None:
            root = result.directory.absolute()
            if root.is_symlink():
                raise ValueError
            metadata_path = root / "imputation.run.json"
            stage = _load(metadata_path)
            metadata_sha = digest(metadata_path)
            if (
                stage != dict(result.metadata)
                or hashlib.sha256(result.original.frame.write_csv().encode()).hexdigest()
                != stage["contract"]["target_sha256"]
            ):
                raise ValueError
            _metadata(stage, execution)
            expected = tuple(root / f["name"] for f in stage["files"])
            if tuple(p.absolute() for p in result.dosage_files) != expected:
                raise ValueError
            copies = [
                (p, p.name, f["sha256"]) for p, f in zip(expected, stage["files"], strict=True)
            ]
            copies += [
                (Path(stage["contract"][key]["path"]), name, stage["contract"][key]["sha256"])
                for key, name in (("panel_catalog", PANEL_NAME), ("map_catalog", MAP_NAME))
            ]
            for source, name, sha in copies:
                if progress:
                    progress("Copying full imputation evidence into the saved run")
                if source.is_symlink():
                    raise ValueError
                destination = directory / name
                shutil.copyfile(source, destination)
                if digest(destination) != sha:
                    raise ValueError
                with destination.open("r+b") as stream:
                    os.fsync(stream.fileno())
                hashes[name] = sha
            raw = {"schema_version": 1, "status": "recorded", "stage": stage}
            if digest(metadata_path) != metadata_sha:
                raise ValueError
        validate_snapshot(directory, raw, execution, cards, hashes, progress)
        return raw, hashes
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ImputationError(
            "Imputation snapshot could not be published from its verified stage."
        ) from None


def iter_saved(directory: Path, raw: Mapping[str, Any] | None) -> Iterator[DosageRecord]:
    if raw is None or raw.get("status") != "recorded":
        raise ImputationError("Full imputation dosage evidence was not recorded for this run.")
    for file in raw["stage"]["files"]:
        path = directory / file["name"]
        if not is_dosage_name(file["name"]) or path.is_symlink() or digest(path) != file["sha256"]:
            raise ImputationError("Saved dosage payload has changed since the run was opened.")
        yield from iter_records(path)
