"""ROH arithmetic, privacy, and real-binary planted-run acceptance.

All panels and calls are generated from fixed-seed reference frequencies here.
Set GENETICS_ROH_TEST_TOOLS to the installed tools root for native acceptance.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.external.plink2 import Plink2
from genetics.external.plink19 import Plink19
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.paths import repo_root
from genetics.structure.roh import (
    Interval,
    ReferenceInput,
    RohError,
    RohResult,
    RohSettings,
    assayed_intervals,
    compute_roh,
    read_segments,
)


def test_gap_denominator_and_inclusive_lengths() -> None:
    markers = [("1", 1 + i * 100_000) for i in range(60)]
    markers += [("1", 10_000_001 + i * 100_000) for i in range(60)]
    blocks = assayed_intervals(markers, RohSettings())
    assert [b.length_bp for b in blocks] == [5_900_001, 5_900_001]
    result = RohResult((blocks[0],), blocks, 120, 120, 120, 0, RohSettings(), (), "2", "1")
    data = result.as_dict()
    assert data["total_roh_bp"] == 5_900_001
    assert data["longest_roh_bp"] == 5_900_001
    assert data["f_roh"] == 0.5
    assert data["roh_count"] == 1
    assert "Partial" in " ".join(data["warnings"])
    assert "5900001" not in repr(result)


def test_no_coverage_is_not_a_zero_score() -> None:
    result = RohResult((), (), 1, 1, 1, 1, RohSettings(), (), "2", "1").as_dict()
    assert result["f_roh"] is None
    assert result["status"] == "insufficient_coverage"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"maf": float("nan")},
        {"maf": 0.7},
        {"min_kb": 0},
        {"gap_kb": -1},
        {"max_hets": -1},
        {"window_snps": 3},
        {"ld_r2": 2},
        {"min_snps": True},
    ],
)
def test_invalid_policy_fails(kwargs: dict[str, float]) -> None:
    with pytest.raises(RohError):
        RohSettings(**kwargs)  # type: ignore[arg-type]


def test_duplicate_markers_and_non_autosomal_input_refused() -> None:
    with pytest.raises(RohError, match="duplicate"):
        assayed_intervals([("1", 10), ("1", 10)], RohSettings())
    with pytest.raises(ValueError):
        assayed_intervals([("X", 10)], RohSettings())


def test_native_report_rejects_wrong_count_and_overlap(tmp_path: Path) -> None:
    markers = [("1", 1 + i * 100_000) for i in range(60)]
    report = tmp_path / "report.hom"
    header = "FID IID CHR POS1 POS2 NSNP\n"
    row = "SAMPLE SAMPLE 1 1 5900001 60\n"
    report.write_text(header + row, encoding="utf-8")
    assert read_segments(report, markers, RohSettings()) == (Interval("1", 1, 5_900_001, 60),)
    for body in (row + row, row.replace("60\n", "59\n"), "bad row\n"):
        report.write_text(header + body, encoding="utf-8")
        with pytest.raises(RohError):
            read_segments(report, markers, RohSettings())


def _synthetic(tmp_path: Path, mode: str = "planted") -> tuple[GenotypeTable, Path]:
    rng = random.Random(6102026)
    cohort = tmp_path / "synthetic-reference.vcf"
    rows: list[dict[str, object]] = []
    with cohort.open("w", encoding="utf-8") as stream:
        stream.write("##fileformat=VCFv4.2\n##contig=<ID=1>\n")
        stream.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        stream.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t")
        stream.write("\t".join(f"ref{i}" for i in range(80)) + "\n")
        previous_gt: list[str] = []
        for i in range(1000):
            pos = 1 + i * 20_000 + (2_000_000 if mode == "gap" and i >= 500 else 0)
            frequency = 0.001 if i % 20 == 0 else 0.35
            gt = [
                f"{int(rng.random() < frequency)}/{int(rng.random() < frequency)}"
                for _ in range(80)
            ]
            if i % 10 == 3:
                gt = previous_gt  # Perfect local LD with preceding common marker.
            previous_gt = gt
            stream.write(f"1\t{pos}\tm{i}\tA\tG\t.\tPASS\t.\tGT\t" + "\t".join(gt) + "\n")
            alleles = sorted("G" if rng.random() < 0.35 else "A" for _ in range(2))
            if mode != "control" and 200 <= i < 800:
                alleles = ["A", "A"]
            missing = (mode == "missing" and 400 <= i < 600) or mode == "all_missing"
            rows.append(
                {
                    "rsid": f"rs{9000000 + i}",
                    "chrom": "1",
                    "pos_grch37": pos,
                    "a1": None if missing else alleles[0],
                    "a2": None if missing else alleles[1],
                    "genotype": None if missing else "".join(alleles),
                    "call_status": "no-call" if missing else "called",
                }
            )
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic"), cohort


def test_workspace_cannot_be_in_repo(tmp_path: Path) -> None:
    table, source = _synthetic(tmp_path)
    with pytest.raises(RohError, match="outside"):
        compute_roh(
            table,
            [ReferenceInput(source, "synthetic-v1", "synthetic")],
            plink2=Plink2(Path("absent"), "test"),
            plink19=Plink19(Path("absent"), "test"),
            workspace=repo_root() / "runs",
        )


def test_cli_refuses_unsafe_output_before_running_tools(tmp_path: Path) -> None:
    source = tmp_path / "empty.txt"
    source.touch()
    result = CliRunner().invoke(
        app, ["roh", "--input", str(source), "--output", str(repo_root() / "result.roh.json")]
    )
    assert result.exit_code == 1
    assert "outside" in result.output


@pytest.fixture
def native_tools() -> tuple[Plink2, Plink19]:
    root = os.environ.get("GENETICS_ROH_TEST_TOOLS")
    if not root:
        pytest.skip("set GENETICS_ROH_TEST_TOOLS for pinned native ROH acceptance")
    return Plink2.discover(tools_root=Path(root)), Plink19.discover(tools_root=Path(root))


@pytest.mark.parametrize("mode", ["planted", "control", "gap", "missing", "all_missing"])
def test_native_planted_runs(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
    mode: str,
) -> None:
    table, source = _synthetic(tmp_path, mode)
    work = tmp_path / "work"
    result = compute_roh(
        table,
        [ReferenceInput(source, "synthetic-v1", "fixed-frequency synthetic cohort")],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=work,
    )
    data = result.as_dict()
    assert list(work.iterdir()) == []
    assert data["n_filtered_reference_markers"] < 1000  # Rare reference sites excluded.
    assert data["n_analyzed_markers"] > 500
    assert result.provenance[0]["n_retained_markers"] < result.provenance[0]["n_eligible_before_ld"]
    assert data["denominator_bp"] > 15_000_000
    assert json.loads(json.dumps(data))["schema_version"] == 1
    if mode == "control":
        assert data["roh_count"] == 0
    elif mode == "planted":
        assert data["roh_count"] == 1
        assert 10_000_000 < data["longest_roh_bp"] < 13_000_000
    elif mode == "gap":
        assert data["roh_count"] == 2
        assert data["longest_roh_bp"] < 8_000_000
    elif mode == "all_missing":
        assert data["status"] == "insufficient_calls"
        assert data["f_roh"] is None
    else:
        assert data["n_missing_calls"] > 150
        assert data["longest_roh_bp"] < 8_000_000


def test_native_failure_cleans_scratch(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    table, source = _synthetic(tmp_path)
    work = tmp_path / "work"
    keep = tmp_path / "keep.txt"
    keep.write_text("ref1\n", encoding="utf-8")
    reference = ReferenceInput(source, "synthetic-v1", "too-small", keep)
    with pytest.raises((RohError, RuntimeError)):
        compute_roh(
            table, [reference], plink2=native_tools[0], plink19=native_tools[1], workspace=work
        )
    assert list(work.iterdir()) == []


def test_every_native_roh_parameter_is_explicit() -> None:
    args = replace(RohSettings(), max_hets=2).arguments()
    assert args[args.index("--homozyg-het") + 1] == "2"
    assert len([a for a in args if a.startswith("--homozyg-")]) == 9


def test_late_native_failure_removes_sample_copy(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    from genetics.external.plink2 import Plink2RunError

    table, source = _synthetic(tmp_path)
    work = tmp_path / "work"
    with pytest.raises(Plink2RunError):
        compute_roh(
            table,
            [ReferenceInput(source, "synthetic", "synthetic")],
            plink2=native_tools[0],
            plink19=Plink19(tmp_path / "missing.exe", "test"),
            workspace=work,
        )
    assert list(work.iterdir()) == []


def test_selection_is_independent_of_subject_calls(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    table, source = _synthetic(tmp_path)
    reference = ReferenceInput(source, "synthetic-v1", "synthetic")
    first = compute_roh(
        table,
        [reference],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=tmp_path / "work",
    )
    # Replace the entire sample with heterozygotes; reference pruning must not change.
    altered = GenotypeTable(
        table.frame.with_columns(
            pl.lit("A").alias("a1"),
            pl.lit("G").alias("a2"),
            pl.lit("AG").alias("genotype"),
        ),
        vendor="synthetic",
    )
    second = compute_roh(
        altered,
        [reference],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=tmp_path / "work",
    )
    assert first.provenance == second.provenance
    assert first.as_dict()["roh_count"] == 1
    assert second.as_dict()["roh_count"] == 0


def test_cli_writes_engine_result_without_overwriting(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import genetics.ingest

    table, source = _synthetic(tmp_path)
    monkeypatch.setattr(genetics.ingest, "ingest", lambda _: SimpleNamespace(table=table))
    monkeypatch.setattr(Plink2, "discover", lambda: native_tools[0])
    monkeypatch.setattr(Plink19, "discover", lambda: native_tools[1])
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "user-data"))
    output = tmp_path / "result.roh.json"
    args = [
        "roh",
        "--input",
        str(source),
        "--reference",
        str(source),
        "--reference-version",
        "synthetic-v1",
        "--population",
        "synthetic",
        "--output",
        str(output),
    ]
    invocation = CliRunner().invoke(app, args)
    assert invocation.exit_code == 0, invocation.output
    saved = output.read_bytes()
    assert json.loads(saved)["roh_count"] == 1
    again = CliRunner().invoke(app, args)
    assert again.exit_code == 1
    assert "already exists" in again.output
    assert output.read_bytes() == saved
