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
    window_support,
)


def test_gap_denominator_and_inclusive_lengths() -> None:
    markers = [("1", 1 + i * 100_000) for i in range(60)]
    markers += [("1", 10_000_001 + i * 100_000) for i in range(60)]
    blocks = assayed_intervals(markers, RohSettings())
    assert [b.length_bp for b in blocks] == [5_900_001, 5_900_001]
    result = RohResult(
        (blocks[0],),
        blocks,
        120,
        120,
        120,
        0,
        RohSettings(),
        (),
        "2",
        "1",
        window_support(markers, set(), RohSettings()),
    )
    data = result.as_dict()
    assert data["total_roh_bp"] == 5_900_001
    assert data["longest_roh_bp"] == 5_900_001
    assert data["f_roh"] == 0.5
    assert data["roh_count"] == 1
    assert "Partial" in " ".join(data["warnings"])
    assert "5900001" not in repr(result)


def test_no_coverage_is_not_a_zero_score() -> None:
    result = RohResult((), (), 1, 1, 1, 1, RohSettings(), (), "2", "1", ()).as_dict()
    assert result["f_roh"] is None
    assert result["status"] == "insufficient_coverage"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"maf": float("nan")},
        {"maf": 10**400},
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
                    "call_status": "no_call" if missing else "called",
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


def test_invalid_export_is_a_cli_error_without_traceback(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "invalid.txt"
    source.write_text("not a genome export\n", encoding="utf-8")
    monkeypatch.setattr(Plink2, "discover", lambda: native_tools[0])
    monkeypatch.setattr(Plink19, "discover", lambda: native_tools[1])
    invocation = CliRunner().invoke(app, ["roh", "--input", str(source)])
    assert invocation.exit_code == 1
    assert "ROH failed:" in invocation.output
    assert isinstance(invocation.exception, SystemExit)


def test_zero_reference_missingness_is_a_valid_policy() -> None:
    assert RohSettings(reference_missing=0).reference_missing == 0


@pytest.mark.parametrize("name", ["maf", "reference_missing", "ld_r2", "window_threshold"])
def test_boolean_settings_are_not_numbers(name: str) -> None:
    with pytest.raises(RohError):
        RohSettings(**{name: True})


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
    assert json.loads(json.dumps(data))["schema_version"] == 2
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


def test_scattered_calls_cannot_establish_a_zero_roh_fraction(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    table, source = _synthetic(tmp_path)
    observed = pl.col("pos_grch37") % 40_000 == 1
    frame = table.frame.with_columns(
        *[
            pl.when(observed).then(pl.col(name)).otherwise(None).alias(name)
            for name in ("a1", "a2", "genotype")
        ],
        pl.when(observed)
        .then(pl.col("call_status"))
        .otherwise(pl.lit("no_call"))
        .cast(NORMALIZED_SCHEMA["call_status"])
        .alias("call_status"),
    )
    result = compute_roh(
        GenotypeTable(frame, vendor="synthetic"),
        [ReferenceInput(source, "synthetic", "synthetic")],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=tmp_path / "work",
    ).as_dict()
    assert result["n_analyzed_markers"] - result["n_missing_calls"] > 100
    assert result["roh_count"] == 0
    assert result["f_roh"] is None
    assert result["status"] == "insufficient_calls"


def test_no_reference_overlap_is_an_explicit_unavailable_result(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    table, source = _synthetic(tmp_path)
    table = GenotypeTable(
        table.frame.with_columns(
            (pl.col("pos_grch37") + 100_000_000).alias("pos_grch37"),
        ),
        vendor="synthetic",
    )
    result = compute_roh(
        table,
        [ReferenceInput(source, "synthetic", "synthetic")],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=tmp_path / "work",
    ).as_dict()
    assert result["status"] == "insufficient_coverage"
    assert result["n_analyzed_markers"] == 0
    assert result["f_roh"] is None
    assert result["references"][0]["status"] == "no_eligible_markers"


def test_supported_calls_must_be_inside_denominator_intervals() -> None:
    policy = RohSettings()
    eligible = [("1", 1 + 100_000 * i) for i in range(60)]
    # A small, well-called island on another chromosome cannot rescue this missing block.
    markers = eligible + [("2", 1 + i * 1000) for i in range(80)]
    support = window_support(markers, set(eligible), policy)
    result = RohResult(
        (), assayed_intervals(markers, policy), 140, 140, 140, 60, policy, (), "2", "1", support
    ).as_dict()
    assert result["status"] == "insufficient_calls"
    assert result["f_roh"] is None


def test_sparse_grid_does_not_establish_a_zero_fraction() -> None:
    policy = RohSettings()
    markers = [("1", 1 + 200_000 * i) for i in range(60)]
    support = window_support(markers, set(), policy)
    result = RohResult(
        (), assayed_intervals(markers, policy), 60, 60, 60, 0, policy, (), "2", "1", support
    ).as_dict()
    assert result["status"] == "insufficient_coverage"
    assert result["f_roh"] is None


def test_unobservable_blocks_remain_visible_alongside_valid_findings() -> None:
    policy = RohSettings()
    called = [("1", 1 + 100_000 * i) for i in range(60)]
    missing = [("2", 1 + 100_000 * i) for i in range(60)]
    markers = called + missing
    intervals = assayed_intervals(markers, policy)
    result = RohResult(
        (intervals[0],),
        intervals,
        120,
        120,
        120,
        60,
        policy,
        (),
        "2",
        "1",
        window_support(markers, set(missing), policy),
    ).as_dict()
    assert result["f_roh"] == 0.5
    assert result["roh_count"] == 1
    assert "underestimate" in " ".join(result["warnings"])
    assert result["window_support"][1]["observed_windows"] == 0


def test_failed_result_write_never_claims_the_final_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genetics.cli import roh_cmd

    def fail_sync(_: int) -> None:
        raise OSError("simulated storage failure")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(OSError, match="storage failure"):
        roh_cmd._write_result(tmp_path / "result.roh.json", '{"complete": true}')
    assert list(tmp_path.iterdir()) == []


def test_concurrent_result_writer_is_not_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genetics.cli import roh_cmd

    real_link = os.link
    target = tmp_path / "result.roh.json"

    def concurrent_link(source: Path, destination: Path) -> None:
        destination.write_text("winner", encoding="utf-8")
        real_link(source, destination)

    monkeypatch.setattr(os, "link", concurrent_link)
    with pytest.raises(FileExistsError):
        roh_cmd._write_result(target, "loser")
    assert target.read_text(encoding="utf-8") == "winner"
    assert list(tmp_path.iterdir()) == [target]


def test_reference_and_keep_hashes_survive_identical_basenames(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    table, source = _synthetic(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    keep = other / source.name
    keep.write_text("\n".join(f"ref{i}" for i in range(80)), encoding="utf-8")
    result = compute_roh(
        table,
        [ReferenceInput(source, "synthetic", "synthetic", keep)],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=tmp_path / "work",
    ).as_dict()
    hashes = result["references"][0]["input_sha256"]
    assert set(hashes) == {"vcf", "keep"}
    assert hashes["vcf"] != hashes["keep"]


def test_window_support_applies_the_missing_limit_at_the_boundary() -> None:
    policy = replace(RohSettings(), min_kb=100)
    markers = [("1", 1 + 20_000 * i) for i in range(50)]
    assert window_support(markers, set(markers[:2]), policy)[0].observed_windows == 1
    assert window_support(markers, set(markers[:3]), policy)[0].observed_windows == 0


def test_reference_parse_errors_are_not_hidden_as_missing_coverage(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    from genetics.external.plink2 import Plink2RunError

    table, source = _synthetic(tmp_path)
    source.write_text("invalid reference header\n", encoding="utf-8")
    with pytest.raises(Plink2RunError):
        compute_roh(
            table,
            [ReferenceInput(source, "synthetic", "synthetic")],
            plink2=native_tools[0],
            plink19=native_tools[1],
            workspace=tmp_path / "work",
        )
    assert list((tmp_path / "work").iterdir()) == []


def test_small_reference_intersection_is_not_a_native_failure(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    table, source = _synthetic(tmp_path)
    tiny = GenotypeTable(table.frame.head(20), vendor="synthetic")
    result = compute_roh(
        tiny,
        [ReferenceInput(source, "synthetic", "synthetic")],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=tmp_path / "work",
    ).as_dict()
    assert result["status"] == "insufficient_coverage"
    assert result["references"][0]["status"] == "insufficient_marker_support"


def test_small_island_does_not_erase_a_valid_other_chromosome(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    table, source = _synthetic(tmp_path)
    second = tmp_path / "chr2.vcf"
    content = source.read_text(encoding="utf-8").replace("ID=1>", "ID=2>")
    content = (
        "\n".join(
            "2" + line[1:] if line.startswith("1\t") else line for line in content.splitlines()
        )
        + "\n"
    )
    second.write_text(content, encoding="utf-8")
    island = table.frame.head(20).with_columns(
        pl.lit("2").cast(NORMALIZED_SCHEMA["chrom"]).alias("chrom")
    )
    table = GenotypeTable(pl.concat([table.frame, island]), vendor="synthetic")
    result = compute_roh(
        table,
        [ReferenceInput(p, "synthetic", "synthetic") for p in (source, second)],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=tmp_path / "work",
    ).as_dict()
    assert result["status"] == "computed"
    assert result["roh_count"] == 1
    assert result["references"][1]["status"] == "insufficient_marker_support"


def test_unresolvable_array_indels_produce_unavailable_coverage(
    tmp_path: Path,
    native_tools: tuple[Plink2, Plink19],
) -> None:
    table, source = _synthetic(tmp_path)
    table = GenotypeTable(
        table.frame.with_columns(
            pl.lit("D").alias("a1"),
            pl.lit("I").alias("a2"),
            pl.lit("DI").alias("genotype"),
        ),
        vendor="synthetic",
    )
    result = compute_roh(
        table,
        [ReferenceInput(source, "synthetic", "synthetic")],
        plink2=native_tools[0],
        plink19=native_tools[1],
        workspace=tmp_path / "work",
    ).as_dict()
    assert result["status"] == "insufficient_coverage"
    assert result["references"][0]["status"] == "no_harmonized_markers"
    assert result["references"][0]["harmonization_counts"]["array_indel"] > 0


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
