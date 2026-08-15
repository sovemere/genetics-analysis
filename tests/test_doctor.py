"""Tests for `genetics doctor` (roadmap M0.6).

The thing worth testing here is not "does it find PLINK" -- on a CI runner it will not --
but that the report stays *truthful and non-fatal* when tools are absent, and that it
turns fatal exactly when the environment is misconfigured rather than merely bare.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
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


def test_hibag_present_is_reportable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The success path must be reachable at all -- it was not.

    ``_run_version`` treats empty output as an error, and the obvious silent probe
    (``if (!requireNamespace(...)) quit(status=1)``) prints nothing when the package *is*
    installed. So every machine reported "R is installed but HIBAG is not", including
    machines with HIBAG. The probe now prints on success.
    """

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "R version 4.4.1\n", "")
        return subprocess.CompletedProcess(cmd, 0, "HIBAG ok\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(doctor, "_which", lambda name: "Rscript")

    report = doctor._check_r()
    assert report.status == "ok"
    assert report.version is not None and "HIBAG" in report.version


def test_hibag_absent_is_still_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "R version 4.4.1\n", "")
        return subprocess.CompletedProcess(cmd, 1, "", "Error: package not found\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(doctor, "_which", lambda name: "Rscript")

    report = doctor._check_r()
    assert report.status == "missing"
    assert report.detail is not None and "HIBAG package is not" in report.detail


def test_newest_beagle_jar_wins_not_the_alphabetically_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Beagle jars are named by release date, which does not sort as text.

    Ascending, `05May22` precedes `28jun21`, so taking `sorted(...)[0]` handed M8 the
    older of two installed versions.
    """
    older = tmp_path / "beagle.28jun21.220.jar"
    older.write_bytes(b"x")
    time.sleep(0.02)
    newer = tmp_path / "beagle.05May22.33a.jar"
    newer.write_bytes(b"x")

    monkeypatch.setattr(doctor, "tools_dir", lambda: tmp_path)
    assert doctor._check_beagle().path == str(newer)


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


# ---------------------------------------------------------------------------
# The seam between doctor (M0.6) and the tools installer (M2.5)
# ---------------------------------------------------------------------------


def test_doctor_finds_a_tool_where_the_installer_actually_put_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """doctor used to guess the layout, and M2.5 then chose a different one.

    ``_which`` scanned the tools directory one level deep; the installer writes to
    ``<tools_root>/<id>/<version>/``, two levels down. So ``genetics doctor`` reported
    PLINK 2 missing immediately after ``genetics tools install`` reported success -- the
    command whose whole job is saying what you have, contradicting the one that had just
    put it there. Reading the installer's own record removes the guess.
    """
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    tools_root = tmp_path / "tools"
    nested = tools_root / "plink2" / "v2.0.0-a.7.3"
    nested.mkdir(parents=True)
    binary = nested / ("plink2.exe" if os.name == "nt" else "plink2")
    binary.write_text("#!/bin/sh\necho stub\n")

    (tools_root / "installed.json").write_text(
        json.dumps({"schema_version": 1, "tools": {"plink2": {"path": str(binary)}}}),
        encoding="utf-8",
    )

    assert doctor._which("plink2", tool_id="plink2") == str(binary)


def test_doctor_ignores_a_recorded_path_that_no_longer_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale record must not be reported as an installed tool."""
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    tools_root = tmp_path / "tools"
    tools_root.mkdir(parents=True)
    (tools_root / "installed.json").write_text(
        json.dumps(
            {"schema_version": 1, "tools": {"plink2": {"path": str(tmp_path / "gone.exe")}}}
        ),
        encoding="utf-8",
    )

    # Falls through to the directory scan and PATH, which will not find it either here.
    assert doctor._which("definitely-not-a-real-binary", tool_id="plink2") is None
