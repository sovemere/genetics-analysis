"""Small fabricated, fixed-seed stage checkpoints for saved-run integration tests."""

from __future__ import annotations

import gzip
import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from genetics.external.beagle import BeagleOptions
from genetics.imputation import ImputationResult
from genetics.imputation.dosages import DosageRecord
from genetics.imputation.snapshot import CATALOG_NAMES, PROVENANCE_NAME, digest, is_dosage_name
from genetics.imputation.target import regions
from genetics.ingest.schema import GenotypeTable
from genetics.qc.report import InferredSex


def synthetic_stage(
    original: GenotypeTable,
    directory: Path,
    *,
    records: Sequence[DosageRecord] = (),
    empty_report: Mapping[str, Any] | None = None,
) -> ImputationResult:
    """Invent native identities and consistent checkpoint bytes, never use real tools."""
    directory.mkdir(parents=True, exist_ok=True)
    options = BeagleOptions(memory_mb=512, nthreads=2, seed=8606)
    chrom = records[0].chrom if records else "1"
    region = next(
        (
            r
            for r in regions(chrom, InferredSex.MALE)
            if records and r.start <= records[0].pos_grch37 <= r.end
        ),
        regions(chrom, InferredSex.MALE)[0],
    )
    hashes = [hashlib.sha256(f"synthetic-tool-{i}".encode()).hexdigest() for i in range(5)]
    source = {"id": "synthetic_reference", "version": "seed-8606"}
    ref_info: dict[str, Any] = {
        "path": str(directory / "invented-reference.bref3"),
        "size_bytes": 10,
        "sha256": hashlib.sha256(b"synthetic-panel").hexdigest(),
    }
    map_info: dict[str, Any] = {
        "path": str(directory / "invented-genetic.map"),
        "size_bytes": 10,
        "sha256": hashlib.sha256(b"synthetic-map").hexdigest(),
    }
    catalog_info = {}
    for kind, info, key in (
        ("bref3_panel", ref_info, "panel_catalog"),
        ("genetic_maps", map_info, "map_catalog"),
    ):
        name = Path(info["path"]).name
        catalog = {
            "schema_version": 1,
            "kind": kind,
            "build": "GRCh37",
            "source": source,
            "entries": [{"chromosome": chrom, "path": name}],
            "files": [{"path": name, **{k: info[k] for k in ("size_bytes", "sha256")}}],
        }
        path = directory / f"{key}.run.json"
        path.write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")
        catalog_info[key] = {"path": str(path.resolve()), "sha256": digest(path)}
    base: dict[str, Any] = {
        "schema_version": 1,
        "target_sha256": hashlib.sha256(original.frame.write_csv().encode()).hexdigest(),
        "sex": "male",
        "options": asdict(options),
        **catalog_info,
        "beagle": {
            "version": "synthetic-beagle",
            "sha256": hashes[0],
            "java": {"path": "synthetic-java", "version": "17.0.1", "major": 17},
        },
        "bref": {
            "bref3": {"version": "synthetic-bref3", "sha256": hashes[2]},
            "unbref3": {"version": "synthetic-unbref3", "sha256": hashes[3]},
            "java": {"version": "17.0.1", "executable_sha256": hashes[4]},
        },
        "tool_file_hashes": hashes,
        "policy": "full-panel; two-stage; preserve-direct; split-X; native-target-ploidy-v2",
    }
    files: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    if records:
        decision_rows = sorted(
            (r.pos_grch37, r.array_outcome) for r in records if r.array_outcome is not None
        )
        outcomes = dict(Counter(o for _, o in decision_rows))
        sources = dict(Counter(r.source for r in records))
        report = {
            "region": region.name,
            "ploidy": region.ploidy,
            "positions": len(decision_rows),
            "written": sources.get("direct", 0) + sources.get("imputed_no_call", 0),
            "called": sources.get("direct", 0),
            "outcomes": outcomes,
            "status": "computed",
        }
        reports.append(report)
        path = directory / f"{region.name}.dosages.jsonl.gz"
        body = "".join(
            json.dumps(r.to_dict(), sort_keys=True) + "\n"
            for r in sorted(records, key=lambda r: r.pos_grch37)
        )
        path.write_bytes(gzip.compress(body.encode(), mtime=0))
        files.append(
            {
                "name": path.name,
                "sha256": digest(path),
                "records": len(records),
                "sources": sources,
                "ploidy_conflicts": 0,
            }
        )
        first_output_sha = hashlib.sha256(b"synthetic-phase-output").hexdigest()
        job: dict[str, Any] = {"region": asdict(region), "decisions": decision_rows}
        for phase in ("phase", "impute"):
            opts = asdict(options) | {
                "chrom": region.interval,
                "target_ploidy": region.ploidy,
                "impute": phase == "impute",
            }
            gt = {
                "path": "synthetic-target",
                "size_bytes": 10,
                "sha256": first_output_sha
                if phase == "impute"
                else hashlib.sha256(b"synthetic-target").hexdigest(),
            }
            job[phase] = {
                "contract": {
                    "schema_version": 1,
                    "beagle": {k: base["beagle"][k] for k in ("version", "sha256")},
                    "java": {"version": "17.0.1", "major": 17, "executable_sha256": hashes[1]},
                    "inputs": {"gt": gt, "ref": ref_info, "map": map_info},
                    "options": opts,
                },
                "elapsed_seconds": 1.0,
                "files": {
                    "result.vcf.gz": {"sha256": first_output_sha, "size_bytes": 10},
                    "result.log": {
                        "sha256": hashlib.sha256(b"synthetic-log").hexdigest(),
                        "size_bytes": 10,
                    },
                },
            }
        jobs.append(job)
    elif empty_report is not None:
        reports.append(dict(empty_report))
    stage = {
        "schema_version": 1,
        "contract": base,
        "panel_source": source,
        "map_source": source,
        "files": files,
        "jobs": jobs,
        "regions": reports,
        "unsupported_positions": {},
        "records": len(records),
        "sources": dict(Counter(r.source for r in records)),
        "ploidy_conflicts": 0,
        "limitations": ["Synthetic stage; no biological claim."],
    }
    stage = json.loads(json.dumps(stage))
    (directory / "imputation.run.json").write_text(json.dumps(stage), encoding="utf-8")
    return ImputationResult(
        original, directory, tuple(directory / f["name"] for f in files), stage, False
    )


def anchors(chrom: str = "1", *, start: int = 10, ploidy: int = 2) -> tuple[DosageRecord, ...]:
    rng = random.Random(8606)
    result = []
    for pos in (start, start + 10):
        gt = tuple(int(rng.random() < 0.4) for _ in range(ploidy))
        dose = (float(gt.count(1)),)
        result.append(
            DosageRecord(
                chrom,
                pos,
                "A",
                ("G",),
                gt,
                gt,
                dose,
                dose,
                None,
                ploidy,
                "direct",
                "resolved",
                "as_written",
                "observed_allele_count",
                "not_estimated",
            )
        )
    return tuple(result)


def remove_snapshot_for_historical_fixture(directory: Path, manifest: dict[str, Any]) -> None:
    """Remove M8.6 manifest members when fabricating an older recorded contract.

    Leave bytes untouched so a test temporarily reading old metadata can restore the
    original manifest. Older readers ignore files outside their recorded payload set.
    """
    for name in tuple(manifest["files"]):
        if name in {PROVENANCE_NAME, *CATALOG_NAMES} or is_dosage_name(name):
            manifest["files"].pop(name)
