"""Synthetic subprocess acceptance for optional R/HIBAG, with no classifiers or DNA."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from genetics import doctor
from genetics.cli.main import app
from genetics.external import hibag
from genetics.external.process import stop as _stop

PROTOCOL = "genetics-hibag\t1\tready\t4.4.1\tx86_64-w64-mingw32\t1.40.0\n"
STUB = r"""
import json, os, pathlib, sys, time
a = sys.argv[1:]
assert a[:3] == ["--vanilla", "--default-packages=NULL", "-e"]
assert "RHOME" not in os.environ
assert "R_PROFILE_USER" not in os.environ
assert "R_SCRIPT_DEFAULT_PACKAGES" not in os.environ
assert os.environ.get("R_LIBS_USER") == "synthetic-library"
mode = os.environ.get("SYNTHETIC_R_MODE", "ready")
identity = "genetics-hibag\t1\tready\t4.4.1\tx86_64-w64-mingw32\t1.40.0\n"
if mode == "hang":
    pathlib.Path("started").write_text(str(os.getpid()))
    time.sleep(60)
if mode == "nonzero":
    print("PRIVATE-SUBPROCESS-DIAGNOSTIC", file=sys.stderr)
    sys.exit(4)
if mode == "missing":
    identity = identity.replace("ready", "hibag-missing").replace("1.40.0", "-")
if mode == "broken":
    identity = identity.replace("ready", "load-error")
if mode == "malformed": identity = "PRIVATE-MALFORMED-OUTPUT"
if len(a) == 4:
    print(identity, end="")
else:
    print("PRIVATE-SUBPROCESS-DIAGNOSTIC")
    if mode == "no-protocol": sys.exit(0)
    if mode == "changed": identity = identity.replace("1.40.0", "1.42.0")
    pathlib.Path(a[4]).write_text(identity, encoding="utf8")
    pathlib.Path("arguments.json").write_text(json.dumps(a[9:]), encoding="utf8")
"""


@pytest.fixture
def r_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Real child Python process standing in for R, including Windows argv handling."""
    script = tmp_path / "R script with spaces.py"
    script.write_text(STUB, encoding="utf-8")
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "private-data"))
    monkeypatch.setenv("GENETICS_RSCRIPT", str(script))
    monkeypatch.setenv("RHOME", "unwanted-home")
    monkeypatch.setenv("R_PROFILE_USER", "unwanted-profile")
    monkeypatch.setenv("R_SCRIPT_DEFAULT_PACKAGES", "unwanted-package")
    monkeypatch.setenv("R_LIBS_USER", "synthetic-library")
    original = subprocess.Popen

    def launch(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        result: subprocess.Popen[bytes] = original(
            [sys.executable, str(script), *command[1:]], **kwargs
        )
        return result

    monkeypatch.setattr(subprocess, "Popen", launch)
    return script


def test_missing_r_is_optional_and_creates_no_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GENETICS_RSCRIPT", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "unused"))
    result = hibag.probe()
    assert result.status == "r-missing" and "R not installed" in result.detail
    assert doctor._check_r().status == "missing"
    assert not (tmp_path / "unused").exists()


def test_invalid_override_is_error_even_if_path_has_r(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GENETICS_RSCRIPT", str(tmp_path / "absent"))
    monkeypatch.setattr(shutil, "which", lambda _: sys.executable)
    assert hibag.probe().status == "probe-error"
    assert doctor._check_r().status == "error"


def test_ready_identity_and_shared_doctor_json(r_stub: Path) -> None:
    runtime = hibag.HIBAGRuntime.discover()
    assert runtime.path == r_stub
    assert (runtime.r_version, runtime.hibag_version) == ("4.4.1", "1.40.0")
    report = doctor._check_r()
    assert report.status == "ok" and report.runtime_status == "ready"
    assert report.r_platform == "x86_64-w64-mingw32"
    assert report.version == "R 4.4.1 + HIBAG 1.40.0"
    payload = json.loads(CliRunner().invoke(app, ["doctor", "--json"]).stdout)
    tool = next(t for t in payload["tools"] if t["name"] == "R (HIBAG)")
    assert tool["r_version"] == "4.4.1" and tool["hibag_version"] == "1.40.0"


@pytest.mark.parametrize(
    ("mode", "state", "doctor_status"),
    [
        ("missing", "hibag-missing", "missing"),
        ("broken", "probe-error", "error"),
        ("nonzero", "probe-error", "error"),
        ("malformed", "probe-error", "error"),
    ],
)
def test_probe_failure_classification(
    r_stub: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    state: str,
    doctor_status: str,
) -> None:
    monkeypatch.setenv("SYNTHETIC_R_MODE", mode)
    result = hibag.probe()
    assert result.status == state
    report = doctor._check_r()
    assert report.status == doctor_status and report.runtime_status == state
    assert "PRIVATE" not in repr(report)
    if mode in ("missing", "broken"):
        assert report.r_version == "4.4.1"
    if mode == "broken":
        assert report.hibag_version == "1.40.0"
    assert (
        report.runtime_failure
        == {
            "missing": None,
            "broken": "namespace",
            "nonzero": "execution",
            "malformed": "protocol",
        }[mode]
    )
    with pytest.raises(hibag.HIBAGError, match=r"R|HIBAG"):
        hibag.HIBAGRuntime.discover()


def test_probe_timeout_is_error(r_stub: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNTHETIC_R_MODE", "hang")
    result = hibag.probe(timeout=0.5)
    assert result.status == "probe-error" and "timed out" in result.detail
    assert result.failure == "timeout"


@pytest.mark.parametrize(
    "output",
    [
        "",
        "HIBAG ok\n",
        " " + PROTOCOL,
        PROTOCOL + "\n",
        PROTOCOL.rstrip("\n"),
        PROTOCOL + PROTOCOL,
        PROTOCOL.replace("\t1\t", "\t2\t"),
        PROTOCOL.replace("ready", "unknown"),
        PROTOCOL.replace("4.4.1", "PRIVATE-INVALID-VERSION"),
        PROTOCOL.replace("1.40.0", "-"),
        PROTOCOL.replace("x86_64-w64-mingw32", "bad/platform"),
        PROTOCOL.replace("ready", "hibag-missing"),
        "x" * 4097,
    ],
)
def test_protocol_rejects_malformed_or_inconsistent_output(tmp_path: Path, output: str) -> None:
    path = tmp_path / "protocol"
    path.write_text(output, encoding="utf-8")
    with pytest.raises(hibag.HIBAGError, match="malformed") as error:
        hibag._protocol(path, Path(sys.executable))
    assert "PRIVATE" not in str(error.value)


def test_bridge_validates_completion_and_preserves_argv(r_stub: Path, tmp_path: Path) -> None:
    runtime = hibag.HIBAGRuntime.discover()
    source = tmp_path / "source with spaces.R"
    source.write_text("# synthetic script", encoding="utf-8")
    args = ("argument with spaces", 'quote"and\\slash', "x; $(nothing) & value", "")
    result = runtime.run_script(source, args)
    assert result.runtime == runtime and result.protocol_version == 1
    assert json.loads((result.directory / "arguments.json").read_text()) == list(args)
    assert result.directory.is_relative_to(tmp_path / "private-data")
    assert result.stdout.read_text().strip() == "PRIVATE-SUBPROCESS-DIAGNOSTIC"
    assert str(result.directory) not in repr(result) and "PRIVATE" not in repr(result)


@pytest.mark.parametrize("mode", ["nonzero", "malformed", "no-protocol", "changed", "missing"])
def test_bridge_rejects_failed_or_changed_execution(
    r_stub: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    runtime = hibag.HIBAGRuntime.discover()
    monkeypatch.setenv("SYNTHETIC_R_MODE", mode)
    source = tmp_path / "source.R"
    source.write_text("# synthetic", encoding="utf-8")
    with pytest.raises(hibag.HIBAGError) as error:
        runtime.run_script(source)
    assert "PRIVATE" not in str(error.value)
    assert str(source) not in str(error.value)


def test_bridge_timeout_reaps_child(
    r_stub: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = hibag.HIBAGRuntime.discover()
    source = tmp_path / "source.R"
    source.write_text("# synthetic", encoding="utf-8")
    monkeypatch.setenv("SYNTHETIC_R_MODE", "hang")
    original = _stop
    stopped: list[subprocess.Popen[bytes]] = []

    def stop(process: subprocess.Popen[bytes]) -> None:
        original(process)
        stopped.append(process)

    monkeypatch.setattr(hibag, "_stop", stop)
    with pytest.raises(hibag.HIBAGTimeoutError):
        runtime.run_script(source, timeout=0.5)
    assert len(stopped) == 1 and stopped[0].poll() is not None


def test_cancellation_stops_running_child(
    r_stub: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = hibag.HIBAGRuntime.discover()
    source = tmp_path / "source.R"
    source.write_text("# synthetic", encoding="utf-8")
    monkeypatch.setenv("SYNTHETIC_R_MODE", "hang")
    stopped: list[subprocess.Popen[bytes]] = []

    def stop(process: subprocess.Popen[bytes]) -> None:
        _stop(process)
        stopped.append(process)

    monkeypatch.setattr(hibag, "_stop", stop)
    cancel = threading.Event()
    timer = threading.Timer(0.4, cancel.set)
    timer.start()
    try:
        with pytest.raises(hibag.HIBAGCancelledError):
            runtime.run_script(source, timeout=10, cancel=cancel)
    finally:
        timer.join()
    assert len(stopped) == 1 and stopped[0].poll() is not None
    with pytest.raises(hibag.HIBAGCancelledError):
        hibag.probe(cancel=cancel)


def test_keyboard_interrupt_stops_child(
    r_stub: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = subprocess.Popen
    made: list[subprocess.Popen[bytes]] = []

    def launch(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        process: subprocess.Popen[bytes] = original(command, **kwargs)
        made.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setenv("SYNTHETIC_R_MODE", "hang")
    original_clock = time.monotonic
    ticks = 0

    def clock() -> float:
        nonlocal ticks
        ticks += 1
        if ticks > 1:
            raise KeyboardInterrupt
        return original_clock()

    monkeypatch.setattr(time, "monotonic", clock)
    with pytest.raises(KeyboardInterrupt):
        hibag.probe()
    assert made and made[0].poll() is not None


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_invalid_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(hibag.HIBAGError, match="timeout"):
        hibag.probe(timeout=timeout)


def test_probe_handles_unexecutable_file_and_unsafe_cache(
    r_stub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: Any) -> subprocess.Popen[bytes]:
        raise OSError("PRIVATE-START-ERROR")

    monkeypatch.setattr(subprocess, "Popen", fail)
    assert hibag.probe().status == "probe-error"
    monkeypatch.setenv("GENETICS_DATA_DIR", str(Path(__file__).resolve().parents[2]))
    assert hibag.probe().status == "probe-error"


@pytest.mark.privacy
def test_attempt_copies_remain_ignored_under_knowledge() -> None:
    from genetics.paths import repo_root

    root = repo_root()
    for path in ("copy.hibag-work/arguments.json", "knowledge/copy.hibag-work/payload.tsv"):
        result = subprocess.run(
            ["git", "check-ignore", path],
            cwd=root,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0


@pytest.mark.parametrize("args", ["bare string", ("embedded\0value",), (1,)])
def test_invalid_job_arguments_are_public_safe(
    r_stub: Path,
    tmp_path: Path,
    args: Any,
) -> None:
    runtime = hibag.HIBAGRuntime.discover()
    source = tmp_path / "PRIVATE-SCRIPT.R"
    source.write_text("# synthetic", encoding="utf-8")
    with pytest.raises(hibag.HIBAGError, match="arguments") as error:
        runtime.run_script(source, args)
    assert "PRIVATE" not in str(error.value)


def test_missing_script_is_public_safe(r_stub: Path, tmp_path: Path) -> None:
    runtime = hibag.HIBAGRuntime.discover()
    with pytest.raises(hibag.HIBAGError, match="unavailable") as error:
        runtime.run_script(tmp_path / "PRIVATE-MISSING-SCRIPT.R")
    assert "PRIVATE" not in str(error.value)


def test_native_r_protocol_and_optional_script(tmp_path: Path) -> None:
    """Exercise actual R syntax when user-installed R is available; never install it."""
    found = os.environ.get("GENETICS_HIBAG_TEST_RSCRIPT") or shutil.which("Rscript")
    if found is None:
        pytest.skip("User-installed Rscript unavailable for native HIBAG bridge acceptance")
    state = hibag.probe(Path(found))
    assert state.status in ("ready", "hibag-missing"), state.detail
    assert state.r_version is not None and state.r_platform is not None
    if state.status == "hibag-missing":
        return
    source = tmp_path / "native bridge.R"
    source.write_text('stopifnot(identical(bridge_args, c("space value", "")))\n', encoding="utf-8")
    result = hibag.HIBAGRuntime.from_readiness(state).run_script(source, ["space value", ""])
    assert result.runtime.hibag_version == state.hibag_version
