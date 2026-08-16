"""CLI contract for ``genetics cards lint`` (roadmap M3.5)."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.refs import postprocess

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures" / "cards"


def test_schema_only_lint_is_json_capable_and_names_the_skip() -> None:
    result = runner.invoke(
        app,
        ["cards", "lint", "--knowledge", str(FIXTURES), "--schema-only", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["variant_resolution"] == "skipped"
    assert payload["rendered_templates"] == 14


def test_full_lint_with_a_missing_index_fails_without_a_traceback(tmp_path: Path) -> None:
    missing = tmp_path / "missing.parquet"
    result = runner.invoke(
        app,
        [
            "cards",
            "lint",
            "--knowledge",
            str(FIXTURES),
            "--variant-index",
            str(missing),
            "--json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["variant_resolution"] == "unavailable"
    assert "Traceback" not in result.output


def test_full_cli_lint_resolves_synthetic_variant_keys(tmp_path: Path) -> None:
    index = tmp_path / "dbsnp_variants.parquet"
    pl.DataFrame(
        {
            "rsid": ["rs900000001", "rs900000002"],
            "chrom": ["7", "Y"],
            "pos_grch37": [12345678, 2655180],
            "ref": ["A", "C"],
            "alts": [["G"], ["T"]],
        }
    ).write_parquet(index)
    postprocess._write_provenance(
        index,
        {
            "schema_version": 1,
            "step": "extract_dbsnp_variant_index",
            "transform_version": postprocess.get("extract_dbsnp_variant_index").transform_version,
            "input": {"filename": "synthetic.vcf.gz", "sha256": "0" * 64},
            "params": {"input": "synthetic.vcf.gz", "output": index.name},
            "output": index.name,
        },
        2,
    )
    result = runner.invoke(
        app,
        [
            "cards",
            "lint",
            "--knowledge",
            str(FIXTURES),
            "--variant-index",
            str(index),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["resolved_variants"] == 2
    assert payload["variant_resolution"] == "checked"


def test_human_output_makes_schema_only_visible() -> None:
    result = runner.invoke(
        app,
        ["cards", "lint", "--knowledge", str(FIXTURES), "--schema-only"],
    )
    assert result.exit_code == 0
    assert "SKIPPED (--schema-only)" in result.stdout


def test_variant_index_and_schema_only_are_mutually_exclusive(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "cards",
            "lint",
            "--knowledge",
            str(FIXTURES),
            "--variant-index",
            str(tmp_path / "anything.parquet"),
            "--schema-only",
        ],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_cards_group_is_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "cards" in result.stdout
