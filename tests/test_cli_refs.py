"""Tests for ``genetics refs`` and ``genetics tools`` (roadmap M2.6).

The CLI is the contract (AGENTS.md 3), so what is asserted here is mostly that every
command produces valid, informative JSON. A command that only renders for humans is one an
agent cannot use, and the parity requirement in M13.5 starts being true or false here.

Nothing in this file downloads anything. ``fetch`` is only ever exercised with
``--dry-run``; the required set is 92 GB.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.cli.refs_cmd import _render_report
from genetics.refs import fetcher, postprocess

runner = CliRunner()


def run_json(*args: str) -> dict[str, Any]:
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code in (0, 1), result.output
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


# ---------------------------------------------------------------------------
# refs
# ---------------------------------------------------------------------------


def test_refs_status_lists_every_source_with_its_state() -> None:
    payload = run_json("refs", "status")
    assert isinstance(payload, dict)
    sources = payload["sources"]
    ids = {row["id"] for row in sources}
    assert "gnomad_exomes_r2_1_1_grch37" in ids
    for row in sources:
        assert row["state"] in {
            "complete",
            "partial",
            "missing",
            "manual-step",
            "blocked-by-licence",
            "empty",
            "processing",
            "processing-required",
        }
        assert row["post_process_outputs_present"] <= row["post_process_outputs_total"]


def test_refs_status_reports_what_a_missing_source_costs() -> None:
    """ "gnomAD is missing" is a fact about a file. "The frequency gate cannot be computed"
    is the fact a person actually needs."""
    payload = run_json("refs", "status")
    gnomad = next(r for r in payload["sources"] if r["id"] == "gnomad_exomes_r2_1_1_grch37")
    assert any("frequency gate" in capability for capability in gnomad["enables"])


def test_refs_status_reports_an_active_part_file_as_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A multi-gigabyte resumable download must not look completely absent."""

    source_dir = tmp_path / "dbsnp_b157_grch37"
    source_dir.mkdir()
    (source_dir / "GCF_000001405.25.gz.part").write_bytes(b"public reference prefix")
    monkeypatch.setattr("genetics.cli.refs_cmd.references_dir", lambda: tmp_path)

    result = runner.invoke(app, ["refs", "status", "--json"])
    payload = json.loads(result.stdout)
    dbsnp = next(row for row in payload["sources"] if row["id"] == "dbsnp_b157_grch37")

    assert result.exit_code == 0
    assert dbsnp["state"] == "partial"


def test_refs_status_requires_provenance_for_every_post_process_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A finished-looking table without its input/transform record is not complete."""

    source_dir = tmp_path / "dbsnp_b157_grch37"
    source_dir.mkdir()
    for name in ("GCF_000001405.25.gz", "refsnp-merged.json.bz2"):
        (source_dir / name).touch()

    outputs = (
        "rsid_merges.parquet",
        "rsid_unresolvable.parquet",
        "dbsnp_variants.parquet",
    )
    for name in outputs:
        (source_dir / name).touch()
    for name in outputs[:2]:
        (source_dir / f"{name}.provenance.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("genetics.cli.refs_cmd.references_dir", lambda: tmp_path)
    result = runner.invoke(app, ["refs", "status", "--json"])
    payload = json.loads(result.stdout)
    dbsnp = next(row for row in payload["sources"] if row["id"] == "dbsnp_b157_grch37")

    assert result.exit_code == 0
    assert dbsnp["state"] == "processing-required"
    assert dbsnp["post_process_outputs_present"] == 2
    assert dbsnp["post_process_outputs_total"] == 3


def test_refs_fetch_dry_run_reports_size_without_downloading() -> None:
    """The required set is 92 GB. Finding that out afterwards is not useful."""
    payload = run_json("refs", "fetch", "--dry-run")
    assert payload["total_bytes"] > 0
    assert payload["postprocess_workspace_bytes"] > 0
    assert payload["estimated_peak_bytes"] > payload["total_bytes"]
    assert payload["sources"]
    # Defaults to required-only, so the 495 GB optional genomes must not be included.
    ids = {row["id"] for row in payload["sources"]}
    assert "gnomad_genomes_r2_1_1_grch37" not in ids


def test_refs_fetch_dry_run_all_includes_optional_sources() -> None:
    payload = run_json("refs", "fetch", "--dry-run", "--all")
    ids = {row["id"] for row in payload["sources"]}
    assert "gnomad_genomes_r2_1_1_grch37" in ids


def test_refs_fetch_dry_run_shows_a_licence_block_before_any_bytes_move() -> None:
    payload = run_json("refs", "fetch", "--dry-run", "--only", "pharmgkb")
    row = payload["sources"][0]
    assert row["blocked"], "PharmGKB is share-alike and should require an opt-in"


def test_an_opt_in_clears_the_block_in_the_dry_run() -> None:
    payload = run_json("refs", "fetch", "--dry-run", "--only", "pharmgkb", "--opt-in", "pharmgkb")
    assert payload["sources"][0]["blocked"] is None


def test_refs_licenses_reports_obligations_and_the_opt_in_list() -> None:
    """The input to the M15.4 audit, answerable before anything is downloaded."""
    payload = run_json("refs", "licenses")
    rows = {row["id"]: row for row in payload["sources"]}
    assert rows["snpedia"]["needs_opt_in"] is True
    assert rows["omim"]["needs_opt_in"] is True
    assert rows["pgs_catalog_metadata"]["needs_opt_in"] is False
    assert any(
        "each record carries its own terms" in ob
        for ob in rows["pgs_catalog_metadata"]["obligations"]
    )
    for row in rows.values():
        assert row["terms_url"].startswith("https://")


def test_refs_verify_reports_missing_files_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verification against an isolated empty reference root reports missing."""
    monkeypatch.setattr("genetics.cli.refs_cmd.references_dir", lambda: tmp_path)
    result = runner.invoke(app, ["refs", "verify", "--only", "phylotree_17", "--json"])
    payload = json.loads(result.stdout)
    assert payload["sources"][0]["files"][0]["status"] == "missing"
    assert result.exit_code == 1


def test_human_report_prints_successful_postprocess_detail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = fetcher.FetchReport(
        sources=(
            fetcher.SourceResult(
                source_id="dbsnp_b157_grch37",
                status=fetcher.SourceStatus.COMPLETE,
                process_results=(
                    postprocess.ProcessResult(
                        step="extract_rsid_merge_table",
                        status=postprocess.ProcessStatus.ALREADY_PRESENT,
                        output="rsid_merges.parquet",
                        rows=21,
                        detail="23,340 unresolvable merge record(s)",
                    ),
                ),
            ),
        )
    )

    _render_report(report, as_json=False)

    assert "23,340 unresolvable merge record(s)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# tools (M2.5)
# ---------------------------------------------------------------------------


def test_tools_status_reports_both_tools_for_this_platform() -> None:
    payload = run_json("tools", "status")
    assert payload["platform"].split("_", 1)[0] in {"windows", "macos", "linux"}
    ids = {row["tool_id"] for row in payload["tools"]}
    assert ids == {"plink2", "beagle"}


def test_tools_status_says_which_milestone_needs_each_tool() -> None:
    """A missing PLINK 2 on a fresh checkout is expected, not a fault -- the same stance
    genetics doctor takes. What matters is knowing when it starts mattering."""
    payload = run_json("tools", "status")
    rows = {row["tool_id"]: row for row in payload["tools"]}
    assert rows["plink2"]["required_from"] == "M5"
    assert rows["beagle"]["required_from"] == "M8"


# ---------------------------------------------------------------------------
# Shape of the interface
# ---------------------------------------------------------------------------


def test_every_refs_and_tools_command_supports_json() -> None:
    """AGENTS.md 3: if a computation is only reachable from a human rendering, an agent
    cannot review it."""
    for args in (
        ["refs", "status"],
        ["refs", "licenses"],
        ["refs", "fetch", "--dry-run"],
        ["refs", "verify", "--only", "cpic"],
        ["tools", "status"],
    ):
        result = runner.invoke(app, [*args, "--json"])
        assert result.exit_code in (0, 1), f"{args}: {result.output}"
        json.loads(result.stdout)


def test_an_unknown_id_reports_the_valid_ones_without_a_traceback() -> None:
    """A typo is the commonest way to reach these commands wrongly, and the error already
    lists every valid id -- a rendered traceback buries exactly that line.

    Same reasoning that made ``genetics paths`` catch UnsafeDataDirError.
    """
    for args, expected in (
        (["refs", "fetch", "--dry-run", "--only", "bogus"], "no source 'bogus'"),
        (["refs", "verify", "--only", "bogus"], "no source 'bogus'"),
        (["tools", "install", "--only", "bogus"], "no tool 'bogus'"),
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 1, args
        assert expected in result.output, args
        assert "Traceback" not in result.output, args


def test_the_command_groups_are_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "refs" in result.stdout
    assert "tools" in result.stdout
