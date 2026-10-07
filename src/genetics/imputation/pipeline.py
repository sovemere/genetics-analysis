"""Restartable full-reference phasing then imputation; no card/bundle mutation."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, dataclass, replace
from io import TextIOWrapper
from pathlib import Path
from typing import Any, ClassVar

import polars as pl

from genetics.external.beagle import Beagle, BeagleOptions, _digest, _job_lock
from genetics.ingest.schema import Chrom, GenotypeTable
from genetics.paths import cache_dir, is_inside_repo
from genetics.privacy import NoGenotypeRepr
from genetics.qc.report import InferredSex
from genetics.refs.imputation import SUPPORTED, BrefTools, VcfSummary, _canonical_bytes, _write_json

from .dosages import DosageRecord, iter_records, read_output
from .reference import PreparedReference, read_markers
from .target import ImputationError, Target, prepare_target, regions


@dataclass(frozen=True, repr=False)
class ImputationResult(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("resumed",)
    original: GenotypeTable
    directory: Path
    dosage_files: tuple[Path, ...]
    metadata: Mapping[str, Any]
    resumed: bool

    def summary(self) -> dict[str, Any]:
        """Genotype-free execution summary for CLI/dashboard progress surfaces."""
        return {
            "status": "computed" if self.dosage_files else "no_eligible_jobs",
            "jobs": len(self.dosage_files),
            "resumed": self.resumed,
            "records": self.metadata["records"],
            "sources": self.metadata["sources"],
            "ploidy_conflicts": self.metadata["ploidy_conflicts"],
            "regions": self.metadata["regions"],
            "unsupported_positions": self.metadata["unsupported_positions"],
        }

    def iter_dosages(self) -> Iterator[DosageRecord]:
        """Stream private records; no whole-genome DataFrame or genotype repr."""
        for path in self.dosage_files:
            yield from iter_records(path)


def _publish_file(pending: Path, destination: Path) -> None:
    """Deterministic inputs/outputs: never overwrite a changed completed artifact."""
    if destination.is_symlink():
        raise ImputationError("Imputation artifacts cannot be symbolic links.")
    if destination.exists():
        if _digest(pending) != _digest(destination):
            raise ImputationError("Existing imputation artifact is damaged or has changed.")
        pending.unlink()
    else:
        pending.replace(destination)


def _serialize(path: Path, vcf: Path, target: Target) -> dict[str, Any]:
    sources: Counter[str] = Counter()
    count = conflicts = 0
    # Empty gzip filename and fixed timestamp ensure deterministic hashes across recovery.
    with path.open("wb") as file:
        with (
            gzip.GzipFile(filename="", fileobj=file, mode="wb", mtime=0) as compressed,
            TextIOWrapper(compressed, encoding="utf-8", newline="") as stream,
        ):
            for record in read_output(vcf, target):
                stream.write(_canonical_bytes(record.to_dict()).decode() + "\n")
                count += 1
                conflicts += record.status == "ploidy_conflict"
                sources[record.source] += 1
        file.flush()
        os.fsync(file.fileno())
    return {
        "records": count,
        "sources": dict(sorted(sources.items())),
        "ploidy_conflicts": conflicts,
    }


def impute(
    table: GenotypeTable,
    *,
    sex: InferredSex,
    reference: PreparedReference | None = None,
    beagle: Beagle | None = None,
    bref: BrefTools | None = None,
    options: BeagleOptions | None = None,
    out: Path | None = None,
    progress: Callable[[str], None] | None = None,
    allow_in_repo: bool = False,
) -> ImputationResult:
    """Shared M8.3 engine. Beagle phases against the full panel, then imputes it.

    The original table remains unchanged. All 23 supported chromosomes present on the
    target are considered; X regions are separate jobs with the matching PAR maps.
    Reference availability fails explicitly; no direct-overlap scoring fallback exists.
    Each job has a stable checkpoint, and interruption restarts only incomplete jobs.
    M8.4 calls this stage from analyse()/run; M8.5-M8.7 own evidence and full provenance.
    """
    if not isinstance(sex, InferredSex):
        raise ImputationError("Supply the inferred-sex enum from QC.")
    options = options or BeagleOptions()
    if not options.impute or options.chrom is not None or options.target_ploidy != 2:
        raise ImputationError("The pipeline requires imputation and owns chromosome partitioning.")
    emit = progress or (lambda _: None)
    emit("Verifying full imputation panels and genetic maps")
    reference = reference or PreparedReference.default()
    panel_catalog, map_catalog = reference.validate()
    beagle = beagle or Beagle.discover()
    bref = bref or BrefTools.discover()
    tool_files = (beagle.jar, beagle.java.path, bref.converter, bref.decoder, bref.java.path)
    tool_hashes = [_digest(p) for p in tool_files]
    if (
        tool_hashes[0] != beagle.sha256
        or tool_hashes[-1] != bref.identities["java"]["executable_sha256"]
        or any(
            _digest(path) != bref.identities[name]["sha256"]
            for path, name in ((bref.converter, "bref3"), (bref.decoder, "unbref3"))
        )
    ):
        raise ImputationError("Imputation tools changed after discovery.")
    contract: dict[str, Any] = {
        "schema_version": 1,
        "target_sha256": hashlib.sha256(table.frame.write_csv().encode()).hexdigest(),
        "sex": sex.value,
        "options": asdict(options),
        "panel_catalog": {
            "path": str(reference.panel_catalog.resolve()),
            "sha256": _digest(reference.panel_catalog),
        },
        "map_catalog": {
            "path": str(reference.map_catalog.resolve()),
            "sha256": _digest(reference.map_catalog),
        },
        "beagle": {
            "version": beagle.version,
            "sha256": beagle.sha256,
            "java": asdict(beagle.java) | {"path": str(beagle.java.path)},
        },
        "bref": dict(bref.identities),
        "tool_file_hashes": tool_hashes,
        "policy": "full-panel; two-stage; preserve-direct; split-X; native-target-ploidy-v2",
    }
    key = hashlib.sha256(_canonical_bytes(contract)).hexdigest()
    prefix = (out or cache_dir() / "imputation" / key / "job").resolve()
    if is_inside_repo(prefix) and not allow_in_repo:
        raise ImputationError("Imputation output requires an outside-repo path or explicit opt-in.")
    root = prefix.with_name(prefix.name + ".imputation-work")
    if root.is_symlink():
        raise ImputationError("Imputation workspace cannot be a symbolic link.")
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "job.imputation.lock"
    if lock.is_symlink():
        raise ImputationError("Imputation lock cannot be a symbolic link.")
    with _job_lock(lock):
        contract_file = root / "contract.run.json"
        if contract_file.is_symlink():
            raise ImputationError("Imputation contract cannot be a symbolic link.")
        if contract_file.exists():
            try:
                if contract_file.is_symlink() or json.loads(contract_file.read_bytes()) != contract:
                    raise ImputationError(
                        "Imputation workspace belongs to a different or damaged contract."
                    )
            except (OSError, ValueError) as exc:
                if isinstance(exc, ImputationError):
                    raise
                raise ImputationError("Imputation workspace contract is unreadable.") from None
        else:
            pending = root / f"contract-{uuid.uuid4().hex}.run.json"
            _write_json(pending, contract)
            pending.replace(contract_file)
        complete = root / "complete"
        if complete.is_symlink():
            raise ImputationError("Imputation completion cannot be a symbolic link.")
        saved: dict[str, Any] | None = None
        if complete.exists():
            try:
                metadata_path = complete / "imputation.run.json"
                if metadata_path.is_symlink():
                    raise ValueError
                saved = json.loads(metadata_path.read_bytes())
                if saved["contract"] != contract:
                    raise ValueError
                for entry in saved["files"]:
                    name = entry["name"]
                    if Path(name).name != name or not name.endswith(".dosages.jsonl.gz"):
                        raise ValueError
                    path = complete / name
                    if path.is_symlink() or _digest(path) != entry["sha256"]:
                        raise ValueError
            except (OSError, ValueError, TypeError, KeyError):
                raise ImputationError("Completed imputation outputs are damaged.") from None
        attempt = root / f"attempt-{uuid.uuid4().hex}"
        attempt.mkdir()
        files: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        sources: Counter[str] = Counter()
        count = conflicts = 0
        resumed = saved is not None
        panel_entries = {e["chromosome"]: e for e in panel_catalog["entries"]}
        maps = {
            e["chromosome"]: reference.map_catalog.parent / e["path"]
            for e in map_catalog["entries"]
        }
        chromosomes = set(table.frame["chrom"].cast(pl.String).unique().to_list())
        for chrom in SUPPORTED:
            if chrom not in chromosomes:
                continue
            if chrom not in panel_entries:
                raise ImputationError("A target chromosome has no prepared full reference.")
            entry = panel_entries[chrom]
            panel_path = reference.panel_catalog.parent / entry["path"]
            wanted = set(table.filter_chrom(Chrom(chrom))["pos_grch37"].to_list())
            markers = read_markers(
                bref,
                panel_path,
                chrom,
                VcfSummary(**entry["summary"]),
                wanted,
                attempt / f"chr{chrom}.decode.log",
                options.memory_mb,
                emit,
            )
            for region in regions(chrom, sex):
                target = prepare_target(table, region, markers)
                report = target.summary()
                # Beagle requires marker information; no inference across a region with
                # fewer than two observed anchors is represented as a completed job.
                if target.n_called < 2:
                    report["status"] = (
                        "unresolved_ploidy" if region.ploidy is None else "insufficient_typed_calls"
                    )
                    reports.append(report)
                    continue
                if region.map_key not in maps:
                    raise ImputationError("A chromosome region has no matching genetic map.")
                assert region.ploidy is not None
                report["status"] = "computed"
                reports.append(report)
                pending_target = attempt / f"{region.name}.vcf"
                target.write(pending_target)
                target_file = root / f"{region.name}.vcf"
                _publish_file(pending_target, target_file)
                emit("Phasing eligible typed observations")
                phase = beagle.run(
                    gt=target_file,
                    ref=panel_path,
                    genetic_map=maps[region.map_key],
                    out=root / f"{region.name}.phase",
                    options=replace(
                        options, impute=False, chrom=region.interval, target_ploidy=region.ploidy
                    ),
                    progress=emit,
                    allow_in_repo=allow_in_repo,
                )
                phased_sites = dict(target.sites)
                for record in read_output(phase.vcf, target, phase_only=True):
                    phased_sites[record.pos_grch37] = replace(
                        phased_sites[record.pos_grch37],
                        gt=tuple(sorted(record.storage_genotype)),
                    )
                emit("Imputing full reference variants from phased observations")
                result = beagle.run(
                    gt=phase.vcf,
                    ref=panel_path,
                    genetic_map=maps[region.map_key],
                    out=root / f"{region.name}.impute",
                    options=replace(options, chrom=region.interval, target_ploidy=region.ploidy),
                    progress=emit,
                    allow_in_repo=allow_in_repo,
                )
                # The second invocation must also retain calls filled by the first.
                for _ in read_output(result.vcf, replace(target, sites=phased_sites)):
                    pass
                name = f"{region.name}.dosages.jsonl.gz"
                stats = _serialize(attempt / name, result.vcf, target)
                count += stats["records"]
                conflicts += stats["ploidy_conflicts"]
                sources.update(stats["sources"])
                files.append({"name": name, "sha256": _digest(attempt / name), **stats})
                jobs.append(
                    {
                        "region": asdict(region),
                        "decisions": sorted(target.decisions.items()),
                        "phase": dict(phase.provenance),
                        "impute": dict(result.provenance),
                    }
                )
                resumed = resumed and phase.resumed and result.resumed
        unsupported = {
            c: table.filter_chrom(Chrom(c)).select("pos_grch37").n_unique()
            for c in sorted(chromosomes - set(SUPPORTED))
        }
        metadata = {
            "schema_version": 1,
            "contract": contract,
            "panel_source": panel_catalog["source"],
            "map_source": map_catalog["source"],
            "files": files,
            "jobs": jobs,
            "regions": reports,
            "unsupported_positions": unsupported,
            "records": count,
            "sources": dict(sorted(sources.items())),
            "ploidy_conflicts": conflicts,
            "limitations": [
                "Y/MT/vendor-PAR are not imputed; original direct calls remain available.",
                "Excluded calls remain original; predictions at those positions are imputed.",
                "Phase-filled no-calls have no estimated quality; hardcall dosage is explicit.",
                "Haploid X uses native one-copy targets, dosages and Beagle haploid quality.",
                "Beagle rounds ALT dosages independently to hundredths; sums allow that error.",
            ],
        }
        metadata = json.loads(_canonical_bytes(metadata))
        emit("Verifying imputation completion")
        if (
            hashlib.sha256(table.frame.write_csv().encode()).hexdigest()
            != contract["target_sha256"]
        ):
            raise ImputationError("Normalized target changed during imputation.")
        if tool_hashes != [_digest(p) for p in tool_files]:
            raise ImputationError("Imputation tool/runtime changed during execution.")
        # Repeat source-bound catalog/companion checks before publication.
        reference.validate()
        if any(
            _digest(Path(contract[k]["path"])) != contract[k]["sha256"]
            for k in ("panel_catalog", "map_catalog")
        ):
            raise ImputationError("Imputation reference catalog changed during execution.")
        if saved is not None:
            if metadata != saved:
                raise ImputationError(
                    "Completed imputation no longer matches validated observations."
                )
            for f in files:
                (attempt / f["name"]).unlink()
        else:
            # Only final validated dosage files and metadata enter complete/.
            staging = attempt / "publish"
            staging.mkdir()
            for f in files:
                (attempt / f["name"]).replace(staging / f["name"])
            _write_json(staging / "imputation.run.json", metadata)
            staging.replace(complete)
        emit("Imputation stage complete")
        return ImputationResult(
            table, complete, tuple(complete / f["name"] for f in files), metadata, resumed
        )
