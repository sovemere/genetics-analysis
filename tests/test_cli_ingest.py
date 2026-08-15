"""Tests for `genetics ingest` and `genetics adapters` (roadmap M1.8).

The privacy tests at the bottom are the point of this file. This command's input is a
whole genome, and its output goes to a terminal, a pipe, a log, and from there into
whatever someone pastes. So the guard on the JSON boundary is not asserted to exist -- it
is *demonstrated firing* on a payload crafted to trip it, because a guard that has never
been shown failing is not evidence of anything (the M0 review's closing lesson).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR

runner = CliRunner()


def fixture(name: str) -> str:
    path = DEFAULT_FIXTURE_DIR / name
    if not path.exists():
        pytest.skip("fixtures not generated; run `genetics fixtures`")
    return str(path)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_ingest_reports_counts_and_inferred_sex() -> None:
    result = runner.invoke(app, ["ingest", "--input", fixture("ancestry_v2_male.txt")])

    assert result.exit_code == 0
    assert "markers" in result.stdout
    assert "inferred sex" in result.stdout
    assert "male" in result.stdout


def test_ingest_json_is_parseable_and_complete() -> None:
    result = runner.invoke(app, ["ingest", "--input", fixture("ancestry_v2_female.txt"), "--json"])
    payload = json.loads(result.stdout)

    assert payload["source"]["vendor"] == "ancestrydna_v2"
    assert payload["source"]["build"] == "37"
    assert payload["qc"]["sex"]["inferred"] == "female"
    assert payload["qc"]["call_rates"]["total_markers"] > 0
    assert payload["adapter"]["vendor_id"] == "ancestrydna_v2"


def test_unverified_adapter_is_flagged_in_both_output_modes() -> None:
    """ "It parsed" is not "it was validated"."""
    human = runner.invoke(app, ["ingest", "--input", fixture("other_vendor_layout.txt")])
    assert "not verified against a real export" in human.stdout

    payload = json.loads(
        runner.invoke(
            app, ["ingest", "--input", fixture("other_vendor_layout.txt"), "--json"]
        ).stdout
    )
    assert payload["adapter"]["verified_against_real_export"] is False


def test_warnings_are_surfaced_not_suppressed() -> None:
    result = runner.invoke(app, ["ingest", "--input", fixture("ancestry_v2_high_nocall.txt")])
    assert "warnings" in result.stdout
    assert "call rate" in result.stdout


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_wrong_build_exits_two_with_an_actionable_message() -> None:
    result = runner.invoke(app, ["ingest", "--input", fixture("ancestry_v2_wrong_build.txt")])

    assert result.exit_code == 2
    assert "GRCh37" in result.output
    assert "Re-export on build 37" in result.output


def test_malformed_header_exits_two() -> None:
    result = runner.invoke(app, ["ingest", "--input", fixture("ancestry_v2_malformed_header.txt")])
    assert result.exit_code == 2
    assert "column header" in result.output


def test_unknown_vendor_exits_two(tmp_path: Path) -> None:
    path = tmp_path / "mystery.csv"
    path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

    result = runner.invoke(app, ["ingest", "--input", str(path)])
    assert result.exit_code == 2
    assert "does not match any known vendor" in result.output


# ---------------------------------------------------------------------------
# --expect-counts: the local half of the M1.2 acceptance criterion
# ---------------------------------------------------------------------------


def test_expect_counts_passes_when_the_counts_match() -> None:
    path = fixture("ancestry_v2_male.txt")
    payload = json.loads(runner.invoke(app, ["ingest", "--input", path, "--json"]).stdout)
    total = payload["qc"]["call_rates"]["total_markers"]

    result = runner.invoke(app, ["ingest", "--input", path, "--expect-counts", f"markers={total}"])
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_expect_counts_fails_loudly_on_a_mismatch() -> None:
    """A silent pass here would mean believing a file parsed correctly when it did not."""
    result = runner.invoke(
        app,
        ["ingest", "--input", fixture("ancestry_v2_male.txt"), "--expect-counts", "markers=1"],
    )

    assert result.exit_code == 1
    assert "FAIL" in result.stdout
    assert "do not proceed" in result.stdout.lower()


def test_expect_counts_json_records_the_comparison() -> None:
    result = runner.invoke(
        app,
        [
            "ingest",
            "--input",
            fixture("ancestry_v2_male.txt"),
            "--json",
            "--expect-counts",
            "markers=1,no_calls=2",
        ],
    )
    payload = json.loads(result.stdout)

    assert payload["expect_counts"]["ok"] is False
    assert payload["expect_counts"]["expected"] == {"markers": 1, "no_calls": 2}
    assert result.exit_code == 1


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ("markers", "not key=value"),
        ("marker=1", "unknown count"),
        ("markers=lots", "not an integer"),
        (" ", "no counts to check"),
    ],
)
def test_expect_counts_rejects_a_malformed_spec(spec: str, fragment: str) -> None:
    result = runner.invoke(
        app, ["ingest", "--input", fixture("ancestry_v2_male.txt"), "--expect-counts", spec]
    )
    assert result.exit_code != 0
    assert fragment in result.output


def test_expect_counts_are_named_not_positional() -> None:
    """Named because these numbers are easy to transpose, and a silently swapped pair
    would "pass" against the wrong quantity."""
    from genetics.cli.ingest_cmd import _EXPECTED_KEYS

    assert set(_EXPECTED_KEYS) == {"markers", "called", "no_calls", "indels"}


# ---------------------------------------------------------------------------
# Privacy: demonstrated, not assumed
# ---------------------------------------------------------------------------


@pytest.mark.privacy
@pytest.mark.parametrize(
    "name",
    [
        "ancestry_v2_male.txt",
        "ancestry_v2_female.txt",
        "ancestry_v2_high_nocall.txt",
        "other_vendor_layout.txt",
    ],
)
def test_no_command_output_contains_a_genotype(name: str) -> None:
    from genetics.privacy import looks_like_genotype

    for args in ([], ["--json"]):
        result = runner.invoke(app, ["ingest", "--input", fixture(name), *args])
        assert not looks_like_genotype(result.output), f"{name} {args}"


@pytest.mark.privacy
def test_the_json_guard_actually_fires() -> None:
    """The guard, shown failing.

    ``_emit_json`` runs every payload through the leak scanner. Asserting that clean
    payloads pass proves nothing -- they would pass with the guard deleted. This feeds it
    a payload crafted to trip it and requires the emit to fail.
    """
    from genetics.cli.ingest_cmd import _emit_json
    from genetics.privacy import GenotypeLeakError

    payload: dict[str, object] = {
        "sample_rows": ["\t".join(["rs900000001", "1", "100001", "A", "G"])]
    }
    with pytest.raises(GenotypeLeakError):
        _emit_json(payload)


@pytest.mark.privacy
def test_the_human_render_path_is_guarded_too() -> None:
    """The guard has to cover the branch someone is *more* likely to edit.

    Only ``_emit_json`` scanned its output at first, which left the human path -- the one
    you are staring at when you think "just show me a few rows so I can check the parse"
    -- writing straight to the terminal with nothing to fail.
    """
    from genetics.cli.ingest_cmd import _echo, _secho
    from genetics.privacy import GenotypeLeakError

    row = "\t".join(["rs900000001", "1", "100001", "A", "G"])
    for emit in (_echo, _secho):
        with pytest.raises(GenotypeLeakError):
            emit(f"  sample: {row}")


@pytest.mark.privacy
def test_the_leak_error_does_not_echo_what_it_caught() -> None:
    from genetics.cli.ingest_cmd import _emit_json
    from genetics.privacy import GenotypeLeakError, looks_like_genotype

    payload: dict[str, object] = {
        "sample_rows": ["\t".join(["rs900000001", "1", "100001", "A", "G"])]
    }
    with pytest.raises(GenotypeLeakError) as excinfo:
        _emit_json(payload)

    assert not looks_like_genotype(str(excinfo.value))
    assert "rs900000001" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# genetics adapters
# ---------------------------------------------------------------------------


def test_adapters_lists_both_vendors() -> None:
    result = runner.invoke(app, ["adapters"])
    assert "ancestrydna_v2" in result.stdout
    assert "23andme_like" in result.stdout


def test_adapters_json_records_verification_state() -> None:
    payload = json.loads(runner.invoke(app, ["adapters", "--json"]).stdout)
    by_id = {row["vendor_id"]: row for row in payload}

    assert by_id["ancestrydna_v2"]["verified_against_real_export"] is True
    assert by_id["23andme_like"]["verified_against_real_export"] is False
