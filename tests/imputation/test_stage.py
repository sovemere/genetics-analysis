"""M8.3: invented calls only, offline full-stage and native acceptance."""

from __future__ import annotations

import gzip
import io
import json
import os
import random
import subprocess
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.external.beagle import Beagle, BeagleOptions, BeagleResult, JavaRuntime, _job_lock
from genetics.imputation import ImputationError, PreparedReference, impute
from genetics.imputation import pipeline as mod
from genetics.imputation import reference as reference_mod
from genetics.imputation.dosages import read_output
from genetics.imputation.target import Region, Target, TypedSite, prepare_target, regions
from genetics.ingest.normalize import GRCH37_LENGTHS
from genetics.ingest.schema import NORMALIZED_SCHEMA, Chrom, GenotypeTable
from genetics.paths import repo_root
from genetics.privacy import assert_no_genotype
from genetics.qc.report import InferredSex
from genetics.refs import postprocess
from genetics.refs.imputation import BrefTools, _vcf_stream
from genetics.testing.imputation_inputs import native_reference


def table(rows: list[tuple[str, int, str | None, str]]) -> GenotypeTable:
    return GenotypeTable(
        pl.DataFrame(
            [
                (f"synthetic_probe_{i}", c, p, g[0] if g else None, g[1] if g else None, g, s)
                for i, (c, p, g, s) in enumerate(rows)
            ],
            schema=NORMALIZED_SCHEMA,
            orient="row",
        ),
        vendor="synthetic",
    )


def example_target(ploidy: int = 2) -> Target:
    return Target(
        Region("synthetic", "1", 1, 1000, "1", ploidy),
        {
            100: TypedSite(100, "G", "A", (0,) if ploidy == 1 else (0, 0), "as_written"),
            200: TypedSite(200, "G", "A", None, "no_call"),
        },
        {100: "as_written", 200: "no_call", 400: "duplicate_conflict"},
    )


def output(path: Path, *, change: str | None = None) -> Path:
    header = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE"
    rows = [
        ["1", "100", ".", "G", "A", ".", "PASS", "DR2=1", "GT:DS", "0|0:0"],
        ["1", "200", ".", "G", "A", ".", "PASS", "DR2=1", "GT:DS", "0|1:1"],
        ["1", "300", ".", "G", "A,C", ".", "PASS", "IMP;DR2=0.02,0.8", "GT:DS", "1|2:0.8,0.9"],
        ["1", "400", ".", "G", "A", ".", "PASS", "IMP;DR2=0.1", "GT:DS", "0|0:0.2"],
    ]
    if change == "sample":
        header = header.replace("SAMPLE", "wrong_sample")
    elif change == "lost_typed":
        rows.pop(0)
    elif change == "changed_typed":
        rows[0][9] = "0|1:1"
    elif change == "orientation":
        rows[0][3:5] = ["A", "G"]
    elif change == "typed_source":
        rows[0][7] = "IMP;DR2=1"
    elif change == "duplicate":
        rows.insert(0, rows[0])
    elif change == "unphased":
        rows[0][9] = "0/0:0"
    elif change == "allele_index":
        rows[0][9] = "2|2:0"
    elif change == "typed_dosage":
        rows[0][9] = "0|0:0.5"
    elif change == "missing_ds":
        rows[2][8:10] = ["GT", "1|2"]
    elif change == "missing_quality":
        rows[2][7] = "IMP"
    elif change in {"nan", "negative", "quality_high", "quality_cardinality"}:
        rows[2][7] = (
            "IMP;DR2="
            + {
                "nan": "nan,0.8",
                "negative": "-0.2,0.8",
                "quality_high": "1.2,0.8",
                "quality_cardinality": "0.2",
            }[change]
        )
    elif change in {"infinite_ds", "dosage_high", "dosage_sum", "dosage_cardinality"}:
        rows[2][9] = (
            "1|2:"
            + {
                "infinite_ds": "inf,0.1",
                "dosage_high": "2.1,0.1",
                "dosage_sum": "1.5,1.5",
                "dosage_cardinality": "1",
            }[change]
        )
    elif change == "format":
        rows[0][8] = "GT:DS:DS"
    elif change == "repeat_info":
        rows[0][7] = "DR2=1;DR2=0"
    elif change == "region":
        rows[3][1] = "1001"
    elif change == "chrom":
        rows[0][0] = "2"
    elif change == "unsorted":
        rows.reverse()
    elif change == "untyped_source":
        rows[2][7] = "DR2=0.02,0.8"
    elif change == "repeat_allele":
        rows[2][4] = "A,A"
    elif change == "missing_ref":
        rows[2][3] = "."
    elif change == "empty":
        rows.clear()
    elif change == "phase":
        rows = rows[:2]
    text = "##fileformat=VCFv4.2\n" + header + "\n" + "\n".join("\t".join(r) for r in rows) + "\n"
    path.write_bytes(gzip.compress(text.encode(), mtime=0))
    return path


@pytest.mark.parametrize(
    "change",
    [
        "sample",
        "lost_typed",
        "changed_typed",
        "orientation",
        "typed_source",
        "duplicate",
        "unphased",
        "allele_index",
        "typed_dosage",
        "missing_ds",
        "missing_quality",
        "nan",
        "negative",
        "quality_high",
        "quality_cardinality",
        "infinite_ds",
        "dosage_high",
        "dosage_sum",
        "dosage_cardinality",
        "format",
        "repeat_info",
        "region",
        "chrom",
        "unsorted",
        "untyped_source",
        "repeat_allele",
        "missing_ref",
        "empty",
    ],
)
def test_output_refuses_scientifically_invalid_observations(tmp_path: Path, change: str) -> None:
    with pytest.raises(ImputationError):
        list(read_output(output(tmp_path / "output.vcf.gz", change=change), example_target()))


def test_sources_dosage_orientation_quality_and_exclusions_stay_separate(tmp_path: Path) -> None:
    records = list(read_output(output(tmp_path / "output.vcf.gz"), example_target()))
    assert records[0].source == "direct" and records[0].dosage == (0.0,)
    assert records[1].source == "imputed_no_call" and records[1].dr2 is None
    assert records[1].quality_scope == "not_estimated"
    assert records[2].alt == ("A", "C") and records[2].dosage == (0.8, 0.9)
    assert records[2].dr2 == (0.02, 0.8)  # Low quality stays present.
    assert (
        records[3].source == "imputed_untyped" and records[3].array_outcome == "duplicate_conflict"
    )


def test_invalid_deflate_output_is_a_private_domain_error(tmp_path: Path) -> None:
    damaged = bytearray(gzip.compress(b"synthetic", mtime=0))
    damaged[10] = (damaged[10] & ~6) | 6
    path = tmp_path / "damaged.vcf.gz"
    path.write_bytes(damaged)
    with pytest.raises(ImputationError) as caught:
        list(read_output(path, example_target()))
    assert_no_genotype(str(caught.value))


def test_native_haploid_model_uses_one_copy_and_refuses_diploid_output(tmp_path: Path) -> None:
    path = output(tmp_path / "output.vcf.gz")
    with pytest.raises(ImputationError, match="storage genotypes"):
        list(read_output(path, example_target(1)))
    lines = gzip.decompress(path.read_bytes()).splitlines()
    for index, line in enumerate(lines):
        if line.startswith(b"#"):
            continue
        fields = line.split(b"\t")
        fields[9] = {b"100": b"0:0", b"200": b"1:1", b"300": b"2:0.4,0.45", b"400": b"0:0.1"}[
            fields[1]
        ]
        lines[index] = b"\t".join(fields)
    path.write_bytes(gzip.compress(b"\n".join(lines) + b"\n"))
    records = list(read_output(path, example_target(1)))
    assert records[0].genotype == records[0].storage_genotype == (0,)
    assert records[2].dosage == records[2].storage_dosage == (0.4, 0.45)
    assert records[2].genotype == (2,) and records[2].status == "resolved"
    assert records[2].dr2 == (0.02, 0.8) and records[2].quality_scope == "beagle_haploid_dosage"


def test_phase_only_checks_retention_without_requiring_dosage_quality(tmp_path: Path) -> None:
    path = output(tmp_path / "output.vcf.gz", change="phase")
    text = (
        gzip.decompress(path.read_bytes())
        .decode()
        .replace("GT:DS", "GT")
        .replace(":0\n", "\n")
        .replace(":1\n", "\n")
    )
    path.write_bytes(gzip.compress(text.encode()))
    records = list(read_output(path, example_target(), phase_only=True))
    assert records[1].dosage_method == "phased_hardcall_only" and records[1].dr2 is None
    with pytest.raises(ImputationError):
        list(read_output(output(path), example_target(), phase_only=True))


def test_multiallelic_dosage_sum_preserves_pinned_native_rounding(tmp_path: Path) -> None:
    path = output(tmp_path / "output.vcf.gz")
    lines = gzip.decompress(path.read_bytes()).splitlines()
    for index, line in enumerate(lines):
        fields = line.split(b"\t")
        if not line.startswith(b"#") and fields[1] == b"300":
            fields[4] = b"A,C,T"
            fields[7] = b"IMP;DR2=0.5,0.5,0.5"
            fields[9] = b"1|2:0.67,0.67,0.67"
            lines[index] = b"\t".join(fields)
    path.write_bytes(gzip.compress(b"\n".join(lines) + b"\n"))
    record = list(read_output(path, example_target()))[2]
    assert record.dosage == (0.67, 0.67, 0.67)
    assert sum(record.dosage) == pytest.approx(2.01)
    invalid = gzip.decompress(path.read_bytes()).replace(b"0.67", b"0.68")
    path.write_bytes(gzip.compress(invalid))
    with pytest.raises(ImputationError, match="exceed storage ploidy"):
        list(read_output(path, example_target()))


@pytest.mark.parametrize("sex", list(InferredSex))
def test_x_regions_partition_grch37_with_matching_maps_and_ploidy(sex: InferredSex) -> None:
    result = regions("X", sex)
    assert result[0].start == 1 and result[-1].end == GRCH37_LENGTHS[Chrom.X]
    assert all(a.end + 1 == b.start for a, b in pairwise(result))
    assert [r.map_key for r in result] == ["X", "X_par1", "X", "X_par2", "X"]
    assert [r.ploidy for r in result][1::2] == [2, 2]
    expected = {InferredSex.MALE: 1, InferredSex.FEMALE: 2, InferredSex.AMBIGUOUS: None}[sex]
    assert all(r.ploidy == expected for r in result[::2])


@pytest.mark.parametrize(
    ("calls", "marker", "expected"),
    [
        ([("AG", "called")], ("G", "A"), "as_written"),
        ([("CT", "called")], ("G", "A"), "complemented"),
        ([(None, "no_call")], ("G", "A"), "no_call"),
        ([("ID", "called")], ("G", "A"), "array_indel"),
        ([("AG", "called")], ("A", "T"), "ambiguous_site"),
        ([("AG", "called")], ("AC", "A"), "panel_not_snp"),
        ([("AC", "called")], ("G", "A"), "allele_mismatch"),
        ([("AA", "called"), ("AG", "called")], ("G", "A"), "duplicate_conflict"),
        ([("AG", "het_haploid")], ("G", "A"), "ploidy_conflict"),
        ([("AA", "hemizygous")], ("G", "A"), "ploidy_conflict"),
        ([("AA", "called")], None, "duplicate_panel_position"),
    ],
)
def test_target_decisions_reuse_strand_indel_and_duplicate_rules(
    calls: list[tuple[str | None, str]], marker: tuple[str, str] | None, expected: str
) -> None:
    original = table([("1", 100, g, s) for g, s in calls])
    target = prepare_target(original, regions("1", InferredSex.FEMALE)[0], {100: marker})
    assert target.decisions == {100: expected}
    assert target.summary()["positions"] == 1
    assert bool(target.sites) == (expected in {"as_written", "complemented", "no_call"})


def test_x_target_boundaries_missing_positions_and_original_calls_remain_unchanged() -> None:
    original = table(
        [
            ("X", 2699520, "AG", "called"),
            ("X", 2699521, "AA", "hemizygous"),
            ("X", 3000000, "AG", "called"),
            ("X", 3000010, "AA", "hemizygous"),
        ]
    )
    before = original.frame.clone()
    markers = {2699520: ("A", "G"), 2699521: ("A", "G"), 3000000: ("A", "G")}
    rs = regions("X", InferredSex.MALE)
    par = prepare_target(original, rs[1], markers)
    nonpar = prepare_target(original, rs[2], markers)
    assert par.sites[2699520].gt == (0, 1)
    assert nonpar.sites[2699521].gt == (0,)
    assert nonpar.decisions[3000000] == "ploidy_conflict"
    assert nonpar.decisions[3000010] == "not_in_panel"
    ambiguous = prepare_target(original, regions("X", InferredSex.AMBIGUOUS)[2], markers)
    assert set(ambiguous.decisions.values()) == {"unresolved_ploidy"}
    assert original.frame.equals(before)


@pytest.fixture
def fake_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Only stubs transport; strict target/output validation remains real."""
    files = [tmp_path / n for n in ("beagle.jar", "java.exe", "bref.jar", "unbref.jar")]
    for f in files:
        f.write_bytes(f.name.encode())
    java = JavaRuntime(files[1], "17.0.1", 17)
    identities = {
        n: {"sha256": postprocess._sha256(p), "version": "synthetic"}
        for n, p in zip(("bref3", "unbref3"), files[2:], strict=True)
    }
    identities["java"] = {
        "executable_sha256": postprocess._sha256(java.path),
        "version": java.version,
    }
    bref = BrefTools(java, files[2], files[3], identities)
    reference = PreparedReference(tmp_path / "panel.json", tmp_path / "maps.json")
    reference.panel_catalog.write_text("synthetic panel")
    reference.map_catalog.write_text("synthetic maps")
    panel = tmp_path / "full.bref3"
    genetic_map = tmp_path / "map.tmp"
    panel.write_bytes(b"synthetic full reference")
    genetic_map.write_text("1 . 0 1\n1 . 1 1000\n")
    catalogs = (
        {
            "kind": "bref3_panel",
            "source": {"id": "synthetic", "version": "1"},
            "entries": [
                {
                    "chromosome": "1",
                    "path": panel.name,
                    "summary": {
                        "records": 200,
                        "samples": 20,
                        "sample_order_sha256": "0" * 64,
                        "semantic_sha256": "0" * 64,
                        "haploid_calls_doubled": 0,
                    },
                }
            ],
        },
        {
            "kind": "genetic_maps",
            "source": {"id": "synthetic", "version": "1"},
            "entries": [{"chromosome": "1", "path": genetic_map.name}],
        },
    )
    monkeypatch.setattr(PreparedReference, "validate", lambda self: catalogs)
    monkeypatch.setattr(
        mod, "read_markers", lambda *a: {100: ("A", "G"), 200: ("A", "G"), 300: ("A", "G")}
    )
    calls: list[bool] = []

    class Runner:
        jar = files[0]
        sha256 = postprocess._sha256(files[0])
        version = "synthetic"

        def __init__(self) -> None:
            self.java = java

        def run(
            self, *, gt: Path, out: Path, options: BeagleOptions, **kwargs: Any
        ) -> BeagleResult:
            calls.append(options.impute)
            path = out.with_name(out.name + ".vcf.gz")
            resumed = path.exists()
            if not resumed:
                opener = gzip.open if gt.name.endswith(".gz") else open
                with opener(gt, "rt", encoding="utf-8") as stream:
                    rows = stream.read().replace("/", "|").replace(".|.", "0|1")
                if options.impute:
                    rows += "1\t400\t.\tA\tG\t.\tPASS\tIMP;DR2=0.02\tGT:DS\t0|1:0.8\n"
                path.write_bytes(gzip.compress(rows.encode(), mtime=0))
            return BeagleResult(path, path, path, resumed, {"stage": options.impute})

    runner = cast(Beagle, Runner())
    original = table(
        [
            ("1", 100, "AA", "called"),
            ("1", 200, "AG", "called"),
            ("1", 300, None, "no_call"),
            ("MT", 500, "AA", "called"),
        ]
    )
    return {
        "table": original,
        "sex": InferredSex.FEMALE,
        "reference": reference,
        "beagle": runner,
        "bref": bref,
        "out": tmp_path / "stage",
        "_calls": calls,
        "_catalogs": catalogs,
    }


def run_fake(stage: dict[str, Any], **kwargs: Any) -> mod.ImputationResult:
    arguments = {k: v for k, v in stage.items() if not k.startswith("_")}
    return impute(**(arguments | kwargs))


def test_full_stage_runs_two_jobs_preserves_original_and_reuses_validated_outputs(
    fake_stage: dict[str, Any],
) -> None:
    events: list[str] = []
    result = run_fake(fake_stage, progress=events.append)
    assert fake_stage["_calls"] == [False, True]
    assert result.original is fake_stage["table"]
    records = list(result.iter_dosages())
    assert [r.source for r in records] == ["direct", "direct", "imputed_no_call", "imputed_untyped"]
    assert records[-1].dr2 == (0.02,)
    assert result.summary()["unsupported_positions"] == {"MT": 1}
    assert not result.resumed
    resumed = run_fake(fake_stage)
    assert resumed.resumed and resumed.metadata == result.metadata
    assert resumed.dosage_files[0].read_bytes() == result.dosage_files[0].read_bytes()
    assert all("DR2" not in e for e in events)


@pytest.mark.parametrize(
    "change", ["target", "options", "sex", "reference", "dosages", "contract", "metadata"]
)
def test_resume_refuses_changed_contract_or_corrupt_completion(
    fake_stage: dict[str, Any], change: str
) -> None:
    result = run_fake(fake_stage)
    kwargs: dict[str, Any] = {}
    if change == "target":
        kwargs["table"] = table([("1", 100, "AG", "called"), ("1", 200, "AG", "called")])
    elif change == "options":
        kwargs["options"] = BeagleOptions(seed=1)
    elif change == "sex":
        kwargs["sex"] = InferredSex.MALE
    elif change == "reference":
        fake_stage["reference"].panel_catalog.write_text("different panel")
    elif change == "dosages":
        result.dosage_files[0].write_bytes(b"damaged")
    elif change == "contract":
        (result.directory.parent / "contract.run.json").write_text("not JSON")
    else:
        (result.directory / "imputation.run.json").write_text("not JSON")
    with pytest.raises(ImputationError):
        run_fake(fake_stage, **kwargs)


def test_failed_imputation_reuses_phase_and_never_publishes_partial_completion(
    fake_stage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = fake_stage["beagle"]
    original_run = runner.run

    def fail(**kwargs: Any) -> BeagleResult:
        if kwargs["options"].impute:
            raise InterruptedError("synthetic interruption")
        return cast(BeagleResult, original_run(**kwargs))

    monkeypatch.setattr(runner, "run", fail)
    with pytest.raises(InterruptedError):
        run_fake(fake_stage)
    workspace = fake_stage["out"].with_name("stage.imputation-work")
    assert not (workspace / "complete").exists()
    with _job_lock(workspace / "job.imputation.lock"):
        pass
    monkeypatch.setattr(runner, "run", original_run)
    result = run_fake(fake_stage)
    assert result.summary()["records"] == 4 and not result.resumed


def test_phase_filled_observation_must_be_retained_by_second_invocation(
    fake_stage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = fake_stage["beagle"]
    original_run = runner.run

    def changed(**kwargs: Any) -> BeagleResult:
        result = cast(BeagleResult, original_run(**kwargs))
        if kwargs["options"].impute:
            lines = gzip.decompress(result.vcf.read_bytes()).splitlines()
            for index, line in enumerate(lines):
                fields = line.split(b"\t")
                if not line.startswith(b"#") and fields[1] == b"300":
                    fields[9] = b"1|1"
                    lines[index] = b"\t".join(fields)
            result.vcf.write_bytes(gzip.compress(b"\n".join(lines) + b"\n"))
        return result

    monkeypatch.setattr(runner, "run", changed)
    with pytest.raises(ImputationError, match="original typed call"):
        run_fake(fake_stage)


def test_self_consistent_corrupt_dosages_are_revalidated_against_beagle(
    fake_stage: dict[str, Any],
) -> None:
    result = run_fake(fake_stage)
    path = result.dosage_files[0]
    rows = gzip.decompress(path.read_bytes()).decode().splitlines()
    record = json.loads(rows[-1])
    record["dr2"] = [0.99]
    rows[-1] = json.dumps(record)
    path.write_bytes(gzip.compress(("\n".join(rows) + "\n").encode()))
    metadata_path = result.directory / "imputation.run.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["files"][0]["sha256"] = postprocess._sha256(path)
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ImputationError, match="validated observations"):
        run_fake(fake_stage)


@pytest.mark.parametrize("changed", ["target", "tool"])
def test_input_or_tool_drift_cannot_publish_completed_stage(
    fake_stage: dict[str, Any], changed: str
) -> None:
    def progress(message: str) -> None:
        if message != "Verifying imputation completion":
            return
        if changed == "target":
            fake_stage["table"].frame = table([("1", 100, "AG", "called")]).frame
        else:
            fake_stage["bref"].decoder.write_bytes(b"changed during execution")

    with pytest.raises(ImputationError, match="changed during"):
        run_fake(fake_stage, progress=progress)
    assert not fake_stage["out"].with_name("stage.imputation-work").joinpath("complete").exists()


@pytest.mark.parametrize("change", [None, "summary", "exit", "interruption"])
def test_full_marker_decoding_checks_summary_duplicates_and_cleanup(
    fake_stage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str | None
) -> None:
    reference = (
        b"##fileformat=VCFv4.2\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsynthetic_0\n"
    )
    rng = random.Random(8304)
    for pos, ref, alt in ((100, "A", "G"), (100, "A", "C"), (200, "G", "A")):
        indices = [int(rng.random() < 0.4) for _ in range(2)]
        reference += (
            f"1\t{pos}\t.\t{ref}\t{alt}\t.\tPASS\t.\tGT\t{indices[0]}|{indices[1]}\n".encode()
        )
    expected = _vcf_stream(io.BytesIO(reference), "1")
    if change == "summary":
        expected = replace(expected, semantic_sha256="0" * 64)
    cleaned: list[bool] = []
    process = SimpleNamespace(
        stdout=io.BytesIO(reference), wait=lambda: 1 if change == "exit" else 0
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(reference_mod, "_stop", lambda p: cleaned.append(True))

    def progress(message: str) -> None:
        assert_no_genotype(message)
        if change == "interruption":
            raise KeyboardInterrupt

    def decode() -> dict[int, tuple[str, str] | None]:
        return reference_mod.read_markers(
            fake_stage["bref"],
            tmp_path / "full.bref3",
            "1",
            expected,
            {100, 200, 300},
            tmp_path / "decode.log",
            512,
            progress,
        )

    if change == "interruption":
        with pytest.raises(KeyboardInterrupt):
            decode()
        # Callback fires before Popen, so no child exists to clean up.
        assert cleaned == []
        return
    if change:
        with pytest.raises(ImputationError):
            decode()
    else:
        assert decode() == {100: None, 200: ("G", "A")}
    assert cleaned == [True]


@pytest.mark.parametrize(
    "change",
    [
        "missing_panel",
        "missing_map",
        "phase_only",
        "chrom_override",
        "tool_drift",
        "insufficient_calls",
    ],
)
def test_explicit_reference_settings_and_empty_stage_states(
    fake_stage: dict[str, Any], change: str
) -> None:
    kwargs: dict[str, Any] = {}
    if change == "missing_panel":
        fake_stage["_catalogs"][0]["entries"].clear()
    elif change == "missing_map":
        fake_stage["_catalogs"][1]["entries"].clear()
    elif change == "phase_only":
        kwargs["options"] = BeagleOptions(impute=False)
    elif change == "chrom_override":
        kwargs["options"] = BeagleOptions(chrom="1")
    elif change == "tool_drift":
        fake_stage["beagle"].jar.write_bytes(b"changed")
    else:
        kwargs["table"] = table([("1", 100, "AA", "called")])
        result = run_fake(fake_stage, **kwargs)
        assert result.summary()["status"] == "no_eligible_jobs"
        assert result.summary()["regions"][0]["status"] == "insufficient_typed_calls"
        assert fake_stage["_calls"] == []
        return
    with pytest.raises(ImputationError):
        run_fake(fake_stage, **kwargs)


@pytest.mark.privacy
def test_stage_repr_progress_cli_and_ignored_outputs(
    fake_stage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_fake(fake_stage)
    for value in (result, *result.iter_dosages(), example_target()):
        assert_no_genotype(repr(value))
        assert "pos_grch37" not in repr(value) and "storage_genotype" not in repr(value)
    assert_no_genotype(json.dumps(result.summary()))
    for name in (
        "private.imputation-work/contract.run.json",
        "private.imputation-work/nested/unknown.tsv",
        "knowledge/traits/private.imputation-work/nested/unknown.json",
        "knowledge/traits/private.imputation-work/nested/unknown.csv",
        "private.imputation.lock",
        "private.dosages.jsonl.gz",
    ):
        assert (
            subprocess.run(
                ["git", "check-ignore", "-q", name], cwd=repo_root(), check=False
            ).returncode
            == 0
        )
    with pytest.raises(ImputationError, match="outside-repo"):
        run_fake(fake_stage, out=repo_root() / "synthetic-prefix")
    # Both CLI renderers use the same stage and summary a dashboard consumer can call.
    monkeypatch.setattr(
        "genetics.ingest.ingest",
        lambda p: SimpleNamespace(
            table=result.original,
            qc=SimpleNamespace(sex=SimpleNamespace(inferred=InferredSex.FEMALE)),
        ),
    )
    calls: list[dict[str, Any]] = []

    def shared(original: GenotypeTable, **kwargs: Any) -> mod.ImputationResult:
        assert original is result.original
        calls.append(kwargs)
        kwargs["progress"]("Imputation stage complete")
        return result

    monkeypatch.setattr("genetics.imputation.impute", shared)
    for args in ([], ["--json"]):
        invocation = CliRunner().invoke(
            app, ["impute", "--input", str(fake_stage["beagle"].jar), *args]
        )
        assert invocation.exit_code == 0, invocation.output
        assert_no_genotype(invocation.output)
        if args:
            payload = json.loads(invocation.stdout)
            assert {k: payload[k] for k in result.summary()} == result.summary()
    assert len(calls) == 2 and all(c["options"].impute for c in calls)


@pytest.mark.privacy
def test_cli_failure_does_not_echo_private_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "synthetic-input.tmp"
    input_path.write_text("synthetic")

    def fail(path: Path) -> Any:
        raise OSError("private diagnostic that must not be forwarded")

    monkeypatch.setattr("genetics.ingest.ingest", fail)
    for args in ([], ["--json"]):
        result = CliRunner().invoke(app, ["impute", "--input", str(input_path), *args])
        assert result.exit_code == 2 and "private diagnostic" not in result.output
        assert_no_genotype(result.output)


def test_native_full_stage_autosomes_x_par_ploidy_dosages_quality_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = os.environ.get("GENETICS_BEAGLE_TEST_TOOLS")
    if installed is None:
        pytest.skip("set GENETICS_BEAGLE_TEST_TOOLS for native M8.3 acceptance")
    beagle = Beagle.discover(tools_root=Path(installed))
    bref = BrefTools.discover(Path(installed))
    monkeypatch.setattr(BrefTools, "discover", lambda: bref)
    reference, male, female = native_reference(tmp_path / "refs", bref)
    before = [(p, postprocess._sha256(p)) for p in reference.panel_catalog.parent.rglob("*.bref3")]
    for sex, original in ((InferredSex.MALE, male), (InferredSex.FEMALE, female)):
        kwargs: dict[str, Any] = {
            "sex": sex,
            "reference": reference,
            "beagle": beagle,
            "bref": bref,
            "options": BeagleOptions(memory_mb=512, nthreads=2),
            "out": tmp_path / sex.value,
        }
        result = impute(original, **kwargs)
        records = list(result.iter_dosages())
        assert len(result.dosage_files) == 4 and len(records) == 800
        assert result.summary()["sources"] == {
            "direct": 396,
            "imputed_no_call": 4,
            "imputed_untyped": 400,
        }
        assert all(r.dr2 is not None for r in records if r.source == "imputed_untyped")
        assert all(r.dr2 is None for r in records if r.source == "imputed_no_call")
        assert any(len(r.alt) == 2 for r in records) and any(len(r.ref) == 2 for r in records)
        assert all(0 <= sum(r.dosage) <= r.ploidy + 0.0001 for r in records)
        expected = {
            p: g
            for c, p, g, s in original.frame.select(
                "chrom", "pos_grch37", "genotype", "call_status"
            ).iter_rows()
            if c == "1" and g is not None
        }
        for r in records:
            if r.chrom == "1" and r.source == "direct":
                assert (
                    "".join(sorted((r.ref, *r.alt)[i] for i in r.storage_genotype))
                    == expected[r.pos_grch37]
                )
            if r.chrom == "X":
                nonpar = 2699520 < r.pos_grch37 < 154931044
                assert r.ploidy == (1 if nonpar and sex is InferredSex.MALE else 2)
                if r.ploidy == 1:
                    assert r.dosage == r.storage_dosage
                    assert r.genotype is not None and len(r.genotype) == 1
                    assert len(r.storage_genotype) == 1
                    if r.source == "imputed_untyped":
                        assert r.quality_scope == "beagle_haploid_dosage"
        resumed = impute(original, **kwargs)
        assert resumed.resumed and resumed.metadata == result.metadata
        assert [p.read_bytes() for p in resumed.dosage_files] == [
            p.read_bytes() for p in result.dosage_files
        ]
    assert all(postprocess._sha256(p) == digest for p, digest in before)
