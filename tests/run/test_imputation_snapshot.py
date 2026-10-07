"""M8.6 durable provenance, atomic publication and saved full native dosages."""

from __future__ import annotations

import copy
import gzip
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.imputation import ImputationError, ImputationResult
from genetics.imputation.dosages import DosageRecord
from genetics.imputation.snapshot import CATALOG_NAMES, PROVENANCE_NAME, digest
from genetics.ingest.schema import GenotypeTable
from genetics.privacy import assert_no_genotype
from genetics.run import pipeline, store
from genetics.run.bundle import BundleError, BundleIntegrityError, read_bundle, write_bundle
from genetics.testing.fixtures import FIXTURES, render_fixture
from genetics.testing.imputation_snapshots import anchors, synthetic_stage
from genetics.web import WebConfig, create_app

PACK = Path(__file__).parents[1] / "fixtures/cards"


@pytest.fixture
def prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[pipeline.Analysis, ImputationResult]:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    export = tmp_path / "synthetic.txt"
    export.write_text(render_fixture(spec), encoding="utf-8")
    observed = []

    def stage(original: GenotypeTable, **kwargs: Any) -> ImputationResult:
        record = DosageRecord(
            "7",
            12345678,
            "A",
            ("G",),
            (0, 1),
            (0, 1),
            (1.1,),
            (1.1,),
            (0.1,),
            2,
            "imputed_untyped",
            "resolved",
            None,
            "beagle_DS",
            "beagle_diploid_dosage",
        )
        result = synthetic_stage(
            original, tmp_path / "synthetic-stage", records=(*anchors("7"), record)
        )
        observed.append(result)
        return result

    monkeypatch.setattr(pipeline, "impute", stage)
    analysis = pipeline.analyse(export, knowledge_dir=PACK)
    return analysis, observed[0]


def _rewrite(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    raw_path = path / PROVENANCE_NAME
    raw = json.loads(raw_path.read_text())
    change(raw)
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    manifest["files"][PROVENANCE_NAME] = digest(raw_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _rewrite_dosage(path: Path, change: Callable[[list[dict[str, Any]]], None]) -> None:
    provenance = json.loads((path / PROVENANCE_NAME).read_text())
    name = provenance["stage"]["files"][0]["name"]
    data_path = path / name
    records = [
        json.loads(line) for line in gzip.decompress(data_path.read_bytes()).decode().splitlines()
    ]
    change(records)
    data_path.write_bytes(
        gzip.compress(("\n".join(json.dumps(r) for r in records) + "\n").encode(), mtime=0)
    )
    sha = digest(data_path)
    _rewrite(path, lambda raw: raw["stage"]["files"][0].update(sha256=sha))
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = sha
    manifest_path.write_text(json.dumps(manifest))


@pytest.mark.privacy
def test_snapshot_is_independent_and_uses_exact_stage_identities(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis, stage = prepared
    events: list[str] = []
    path = pipeline.save(
        analysis,
        tools_root=tmp_path / "missing-tools",
        lock_path=tmp_path / "missing.lock",
        progress=events.append,
    )
    original_metadata = copy.deepcopy(stage.metadata)
    bundle = read_bundle(path)
    assert bundle.format_version == 16
    assert bundle.imputation_provenance is not None
    assert bundle.imputation_provenance["stage"] == original_metadata
    for file in stage.metadata["files"]:
        assert (path / file["name"]).read_bytes() == (stage.directory / file["name"]).read_bytes()
        assert (path / file["name"]).stat().st_ino != (stage.directory / file["name"]).stat().st_ino
    for name in CATALOG_NAMES:
        assert (path / name).is_file()
    before = [r.to_dict() for r in bundle.iter_dosages()]
    assert len(before) == 3
    stage.directory.rename(tmp_path / "relocated-stage")
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "no-current-caches"))
    reopened = read_bundle(path)
    assert [r.to_dict() for r in reopened.iter_dosages()] == before
    assert_no_genotype(repr(reopened))
    assert_no_genotype(repr(next(reopened.iter_dosages())))
    assert any("Copying" in event for event in events) and any(
        "Validating" in event for event in events
    )
    assert_no_genotype("\n".join(events))


def test_disabled_run_records_no_execution_or_dosages(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    tmp_path: Path,
) -> None:
    path = pipeline.save(
        pipeline.analyse(tmp_path / "synthetic.txt", knowledge_dir=PACK, no_impute=True)
    )
    bundle = read_bundle(path)
    assert bundle.imputation_provenance == {
        "schema_version": 1,
        "status": "disabled",
        "stage": None,
    }
    assert not tuple(path.glob("*.dosages.jsonl.gz"))
    result = CliRunner().invoke(app, ["runs", "imputation", path.name, "--dosages", "--json"])
    assert result.exit_code != 0


def test_no_eligible_jobs_records_verified_sources_and_empty_dosage_iterator(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty(original: GenotypeTable, **kwargs: Any) -> ImputationResult:
        return synthetic_stage(original, tmp_path / "empty-stage")

    monkeypatch.setattr(pipeline, "impute", empty)
    analysis = pipeline.analyse(tmp_path / "synthetic.txt", knowledge_dir=PACK)
    bundle = read_bundle(pipeline.save(analysis))
    assert bundle.imputation_provenance is not None
    assert bundle.imputation_provenance["status"] == "recorded"
    assert bundle.imputation is not None and bundle.imputation["status"] == "no_eligible_jobs"
    assert list(bundle.iter_dosages()) == []


@pytest.mark.parametrize("haploid", [False, True])
def test_full_dosages_preserve_multiallelic_quality_and_native_scale(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    haploid: bool,
) -> None:
    chrom, pos, ploidy = ("X", 3000300, 1) if haploid else ("7", 12345678, 2)

    def native(original: GenotypeTable, **kwargs: Any) -> ImputationResult:
        gt, dose = ((2,), (0.1, 0.9)) if haploid else ((1, 2), (1.0, 1.01))
        record = DosageRecord(
            chrom,
            pos,
            "A",
            ("G", "T"),
            gt,
            gt,
            dose,
            dose,
            (0.1, 0.99),
            ploidy,
            "imputed_untyped",
            "resolved",
            None,
            "beagle_DS",
            "beagle_haploid_dosage" if haploid else "beagle_diploid_dosage",
        )
        return synthetic_stage(
            original,
            tmp_path / "native-contract-stage",
            records=(*anchors(chrom, start=3000010 if haploid else 10, ploidy=ploidy), record),
        )

    monkeypatch.setattr(pipeline, "impute", native)
    analysis = pipeline.analyse(tmp_path / "synthetic.txt", knowledge_dir=PACK)
    records = list(read_bundle(pipeline.save(analysis)).iter_dosages())
    record = records[-1]
    assert record.ploidy == ploidy and record.dr2 == (0.1, 0.99) and record.alt == ("G", "T")
    assert record.dosage == ((0.1, 0.9) if haploid else (1.0, 1.01))
    assert record.storage_dosage == record.dosage and record.storage_genotype == record.genotype


def test_saved_cli_dashboard_and_iterator_share_provenance(
    prepared: tuple[pipeline.Analysis, ImputationResult],
) -> None:
    analysis, stage = prepared
    path = pipeline.save(analysis)
    bundle = read_bundle(path)
    result = CliRunner().invoke(app, ["runs", "imputation", path.name, "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["provenance"] == bundle.imputation_provenance
    dosages = CliRunner().invoke(app, ["runs", "imputation", path.name, "--dosages"])
    assert dosages.exit_code == 0
    assert [json.loads(line) for line in dosages.stdout.splitlines()] == [
        json.loads(json.dumps(r.to_dict())) for r in bundle.iter_dosages()
    ]
    shown = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert json.loads(shown.stdout)["imputation_provenance"] == bundle.imputation_provenance
    with TestClient(create_app(WebConfig()), base_url="http://127.0.0.1") as client:
        body = client.get(f"/runs/{path.name}").text
    assert "Full imputation provenance" in body and "seed-8606" in body
    assert "synthetic-beagle" in body
    assert stage.metadata["contract"]["target_sha256"] not in body


@pytest.mark.parametrize(
    "damage",
    [
        "status",
        "count",
        "version",
        "tool_hash",
        "runtime",
        "seed",
        "ploidy",
        "phase_mode",
        "phase_handoff",
        "map_identity",
        "decision",
        "source_version",
        "path",
        "extra_file",
        "schema",
    ],
)
def test_rehashed_provenance_damage_is_rejected(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    damage: str,
) -> None:
    path = pipeline.save(prepared[0])

    def change(raw: dict[str, Any]) -> None:
        stage = raw["stage"]
        if damage == "status":
            raw["status"] = "disabled"
        elif damage == "count":
            stage["records"] += 1
        elif damage == "version":
            stage["contract"]["beagle"]["version"] = "different-version"
        elif damage == "tool_hash":
            stage["contract"]["tool_file_hashes"][0] = "0" * 64
        elif damage == "runtime":
            stage["jobs"][0]["impute"]["contract"]["java"]["major"] = 8
        elif damage == "seed":
            stage["jobs"][0]["impute"]["contract"]["options"]["seed"] += 1
        elif damage == "ploidy":
            stage["jobs"][0]["region"]["ploidy"] = 1
        elif damage == "phase_mode":
            stage["jobs"][0]["phase"]["contract"]["options"]["impute"] = True
        elif damage == "phase_handoff":
            stage["jobs"][0]["impute"]["contract"]["inputs"]["gt"]["sha256"] = "0" * 64
        elif damage == "map_identity":
            for phase in ("phase", "impute"):
                stage["jobs"][0][phase]["contract"]["inputs"]["map"]["sha256"] = "0" * 64
        elif damage == "decision":
            stage["jobs"][0]["decisions"][0][1] = "no_call"
        elif damage == "source_version":
            stage["panel_source"]["version"] = "different-version"
        elif damage == "path":
            stage["files"][0]["name"] = "../outside.dosages.jsonl.gz"
        elif damage == "extra_file":
            stage["files"].append(stage["files"][0])
        elif damage == "schema":
            raw["schema_version"] = True

    _rewrite(path, change)
    with pytest.raises(BundleError) as caught:
        read_bundle(path)
    assert_no_genotype(str(caught.value))


@pytest.mark.parametrize(
    "damage", ["dose", "dr2", "native", "source", "scope", "missing", "duplicate", "orientation"]
)
def test_rehashed_full_dosage_damage_or_card_disagreement_is_rejected(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    damage: str,
) -> None:
    path = pipeline.save(prepared[0])

    def change(records: list[dict[str, Any]]) -> None:
        record = records[-1]
        if damage == "dose":
            record["dosage"] = record["storage_dosage"] = [1.2]
        elif damage == "dr2":
            record["dr2"] = [0.9]
        elif damage == "native":
            record["storage_genotype"] = [1]
        elif damage == "source":
            record["source"] = "direct"
        elif damage == "scope":
            record["quality_scope"] = "beagle_haploid_dosage"
        elif damage == "missing":
            records.pop(0)
        elif damage == "duplicate":
            records.append(record)
        elif damage == "orientation":
            record["ref"], record["alt"] = "G", ["A"]

    _rewrite_dosage(path, change)
    with pytest.raises(BundleError) as caught:
        read_bundle(path)
    assert_no_genotype(str(caught.value))


@pytest.mark.parametrize("member", [PROVENANCE_NAME, *CATALOG_NAMES, "chr7.dosages.jsonl.gz"])
def test_missing_and_modified_payloads_fail_integrity(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    member: str,
) -> None:
    path = pipeline.save(prepared[0])
    payload = path / member
    payload.write_bytes(payload.read_bytes() + b"damage")
    with pytest.raises(BundleIntegrityError):
        read_bundle(path)
    payload.unlink()
    with pytest.raises(BundleIntegrityError):
        read_bundle(path)


def test_iterator_detects_a_change_after_open(
    prepared: tuple[pipeline.Analysis, ImputationResult],
) -> None:
    path = pipeline.save(prepared[0])
    bundle = read_bundle(path)
    data = path / "chr7.dosages.jsonl.gz"
    data.write_bytes(data.read_bytes() + b"damage")
    with pytest.raises(ImputationError, match="changed"):
        list(bundle.iter_dosages())


def test_invalid_deflate_data_is_a_domain_error_after_rehash(
    prepared: tuple[pipeline.Analysis, ImputationResult],
) -> None:
    path = pipeline.save(prepared[0])
    name = "chr7.dosages.jsonl.gz"
    data_path = path / name
    damaged = bytearray(data_path.read_bytes())
    damaged[10] = (damaged[10] & ~6) | 6  # Reserved DEFLATE block type.
    data_path.write_bytes(damaged)
    sha = digest(data_path)
    _rewrite(path, lambda raw: raw["stage"]["files"][0].update(sha256=sha))
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = sha
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BundleError) as caught:
        read_bundle(path)
    assert_no_genotype(str(caught.value))


@pytest.mark.parametrize("damage", ["metadata", "dosage", "catalog", "result_files", "original"])
def test_writer_refuses_changed_stage_and_leaves_no_published_bundle(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    damage: str,
    tmp_path: Path,
) -> None:
    analysis, stage = prepared
    if damage == "metadata":
        (stage.directory / "imputation.run.json").write_text("{}")
    elif damage == "dosage":
        stage.dosage_files[0].write_bytes(b"damaged")
    elif damage == "catalog":
        Path(stage.metadata["contract"]["panel_catalog"]["path"]).write_text("{}")
    elif damage == "result_files":
        analysis = replace(analysis, imputation_result=replace(stage, dosage_files=()))
    elif damage == "original":
        other = GenotypeTable(stage.original.frame.head(1), vendor="synthetic")
        analysis = replace(analysis, imputation_result=replace(stage, original=other))
    root = tmp_path / "store"
    with pytest.raises(BundleError):
        pipeline.save(analysis, runs_root=root, run_id="synthetic-failure")
    assert list(root.iterdir()) == []


def test_failed_copy_is_atomic_and_preserves_stage(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import shutil

    analysis, stage = prepared
    hashes = [digest(path) for path in stage.dosage_files]
    actual_copy = shutil.copyfile

    def fail_copy(source: Any, destination: Any, **kwargs: Any) -> Any:
        if Path(destination).name in CATALOG_NAMES:
            raise OSError("Synthetic interruption")
        return actual_copy(source, destination, **kwargs)

    monkeypatch.setattr(shutil, "copyfile", fail_copy)
    root = tmp_path / "store"
    with pytest.raises(BundleError):
        pipeline.save(analysis, runs_root=root)
    assert list(root.iterdir()) == [] and [digest(path) for path in stage.dosage_files] == hashes


def test_enabled_analysis_requires_its_completed_stage(
    prepared: tuple[pipeline.Analysis, ImputationResult],
) -> None:
    with pytest.raises(ImputationError, match="completed imputation stage"):
        pipeline.save(replace(prepared[0], imputation_result=None))


@pytest.mark.parametrize("version", [1, 13, 14, 15])
def test_new_full_provenance_cannot_be_relabelled_as_an_older_format(
    prepared: tuple[pipeline.Analysis, ImputationResult],
    version: int,
) -> None:
    path = pipeline.save(prepared[0])
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["format_version"] = version
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BundleError):
        read_bundle(path)


def test_historical_format_15_keeps_card_evidence_without_inventing_full_dosages(
    prepared: tuple[pipeline.Analysis, ImputationResult],
) -> None:
    path = pipeline.save(prepared[0])
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for name in (PROVENANCE_NAME, *CATALOG_NAMES, "chr7.dosages.jsonl.gz"):
        manifest["files"].pop(name)
        (path / name).unlink()
    manifest["format_version"] = 15
    manifest_path.write_text(json.dumps(manifest))
    bundle = read_bundle(path)
    assert bundle.imputation_provenance is None and bundle.cards[0].observation is not None
    with pytest.raises(ImputationError, match="not recorded"):
        list(bundle.iter_dosages())


def test_unrecorded_low_level_writer_is_explicit(
    prepared: tuple[pipeline.Analysis, ImputationResult],
) -> None:
    analysis, _ = prepared
    path = write_bundle(
        qc=analysis.qc,
        cards=analysis.cards,
        pack=analysis.pack,
        ancestry=analysis.ancestry,
        clinvar=analysis.clinvar,
        imputation=analysis.imputation,
    )
    record = read_bundle(path).imputation_provenance
    assert record == {"schema_version": 1, "status": "not_recorded", "stage": None}


def test_wreckage_with_full_dosages_is_recognised_without_a_manifest(
    prepared: tuple[pipeline.Analysis, ImputationResult],
) -> None:
    path = pipeline.save(prepared[0])
    (path / "manifest.json").unlink()
    assert store.delete_run(path.name) == path


@pytest.mark.privacy
@pytest.mark.parametrize("directory", ["", "knowledge/", "src/genetics/", "tests/fixtures/"])
def test_every_new_payload_is_ignored_even_inside_knowledge(directory: str) -> None:
    import subprocess

    root = Path(__file__).parents[2]
    for name in (PROVENANCE_NAME, *CATALOG_NAMES, "X_nonpar.dosages.jsonl.gz"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", directory + name],
            cwd=root,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
