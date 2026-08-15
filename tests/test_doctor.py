"""Tests for `genetics doctor` (roadmap M0.6).

The thing worth testing here is not "does it find PLINK" -- on a CI runner it will not --
but that the report stays *truthful and non-fatal* when tools are absent, and that it
turns fatal exactly when the environment is misconfigured rather than merely bare.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from genetics import doctor
from genetics.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# The report itself
# ---------------------------------------------------------------------------


def test_collect_never_raises_on_a_bare_environment() -> None:
    report = doctor.collect()
    assert report.python_version
    assert report.platform_name
    assert {t.name for t in report.tools} == {"plink2", "java", "beagle", "R (HIBAG)"}


def test_missing_tools_are_not_a_problem() -> None:
    """A fresh checkout has none of these. That must not read as a fault."""
    report = doctor.Report(
        engine_version="0.1.0",
        python_version="3.13.5",
        python_executable="python",
        platform_name="Windows",
        platform_release="11",
        machine="AMD64",
        data_dir="C:/somewhere",
        data_dir_error=None,
        free_disk_gb=100.0,
        references_present=False,
        manifest_present=False,
        lock_present=False,
        reference_files=0,
        tools=(doctor.ToolReport("plink2", "M5", "missing"),),
    )
    assert report.has_problem is False


def test_a_broken_tool_is_a_problem() -> None:
    """Present but unable to report a version means something is actually wrong."""
    report = doctor.Report(
        engine_version="0.1.0",
        python_version="3.13.5",
        python_executable="python",
        platform_name="Linux",
        platform_release="6",
        machine="x86_64",
        data_dir="/tmp/x",
        data_dir_error=None,
        free_disk_gb=1.0,
        references_present=False,
        manifest_present=False,
        lock_present=False,
        reference_files=0,
        tools=(doctor.ToolReport("plink2", "M5", "error", detail="exit 127"),),
    )
    assert report.has_problem is True


def test_unsafe_data_dir_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """doctor is what you run *because* the data dir is wrong.

    An UnsafeDataDirError escaping here would replace the one message that explains the
    problem with a traceback -- and this command is the newcomer's first contact with it.
    """
    from genetics.paths import repo_root

    monkeypatch.setenv("GENETICS_DATA_DIR", str(repo_root() / "inside"))
    report = doctor.collect()

    assert report.data_dir is None
    assert report.data_dir_error is not None
    assert "GENETICS_DATA_DIR" in report.data_dir_error
    assert report.has_problem is True


def test_free_disk_falls_back_to_an_existing_ancestor(tmp_path: Path) -> None:
    """The data dir legitimately does not exist yet; disk_usage raises on a missing path."""
    assert doctor._free_disk_gb(tmp_path / "a" / "b" / "c") is not None


# ---------------------------------------------------------------------------
# Version probing
# ---------------------------------------------------------------------------


def test_version_probe_reports_stderr_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Java prints its version to stderr. Reading only stdout would call a working JVM broken."""

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="openjdk 21\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    status, version, detail = doctor._run_version(["java", "-version"])

    assert (status, version, detail) == ("ok", "openjdk 21", None)


def test_version_probe_survives_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    status, _, detail = doctor._run_version(["hangs"])

    assert status == "error"
    assert detail is not None and "timed out" in detail


def test_version_probe_survives_an_unexecutable_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("Exec format error")

    monkeypatch.setattr(subprocess, "run", fake_run)
    status, _, detail = doctor._run_version(["broken"])

    assert status == "error"
    assert detail is not None and "OSError" in detail


def test_beagle_env_override_pointing_nowhere_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A set-but-wrong override is worse than an unset one: it looks configured."""
    monkeypatch.setenv("GENETICS_BEAGLE_JAR", str(tmp_path / "absent.jar"))
    assert doctor._check_beagle().status == "error"


def test_beagle_env_override_is_used_when_it_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    jar = tmp_path / "beagle.28jun21.220.jar"
    jar.write_bytes(b"not really a jar")
    monkeypatch.setenv("GENETICS_BEAGLE_JAR", str(jar))

    report = doctor._check_beagle()
    assert report.status == "ok"
    assert report.path == str(jar)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_doctor_json_is_parseable() -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.stdout)

    assert payload["engine_version"]
    assert isinstance(payload["tools"], list)
    assert "has_problem" in payload


def test_doctor_human_output_lists_every_tool() -> None:
    result = runner.invoke(app, ["doctor"])
    for name in ("plink2", "java", "beagle", "R (HIBAG)"):
        assert name in result.stdout


def test_doctor_exit_code_tracks_has_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    from genetics.paths import repo_root

    monkeypatch.setenv("GENETICS_DATA_DIR", str(repo_root() / "inside"))
    assert runner.invoke(app, ["doctor"]).exit_code == 1
