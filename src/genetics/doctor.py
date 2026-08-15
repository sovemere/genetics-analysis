"""Environment report (roadmap M0.6).

The first thing to run when picking this project up. It answers "what can this machine
actually do right now?" -- which matters more here than in most projects, because the
pipeline leans on four external programs that are each optional in a different way:

* **PLINK 2** is required from M5 on. Native Windows build, pinned (AGENTS.md 4.9).
* **Java** is required only by Beagle, so a missing JVM blocks imputation (M8) and
  nothing before it.
* **Beagle** is a jar, so "installed" means "a file exists at a known path".
* **R + HIBAG** is genuinely optional: HLA (M11) degrades to a clear "R not installed"
  state rather than failing the run.

Reporting is deliberately non-fatal. ``doctor`` describes; it never installs, never
fetches, and never exits non-zero for a missing optional tool -- an exit code that means
"you have not done M2 yet" would be noise on every fresh checkout. It exits non-zero only
when something is *wrong* rather than merely absent (see :func:`Report.has_problem`).

Nothing here touches genotype data, so there is nothing to redact. It is the one report
in the project that can be pasted into an issue verbatim.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from genetics import __version__
from genetics.paths import (
    UnsafeDataDirError,
    reference_lock,
    reference_manifest,
    references_dir,
    tools_dir,
    user_data_dir,
)

Status = Literal["ok", "missing", "error"]

_VERSION_TIMEOUT_S = 20
"""Generous: a cold JVM start on Windows is slow, and a timeout here reads as a broken
install rather than a slow one."""


@dataclass(frozen=True)
class ToolReport:
    """One external program's availability."""

    name: str
    required_from: str
    """Milestone at which this stops being optional. Informational."""

    status: Status
    path: str | None = None
    version: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Report:
    """Everything ``genetics doctor`` knows."""

    engine_version: str
    python_version: str
    python_executable: str
    platform_name: str
    platform_release: str
    machine: str
    data_dir: str | None
    data_dir_error: str | None
    free_disk_gb: float | None
    references_present: bool
    manifest_present: bool
    lock_present: bool
    reference_files: int
    tools: tuple[ToolReport, ...] = field(default_factory=tuple)

    @property
    def has_problem(self) -> bool:
        """True when something is *misconfigured*, as opposed to merely not installed yet.

        A missing PLINK 2 on a fresh checkout is the expected state, not a fault, so it
        must not fail the command -- otherwise the first thing a newcomer runs greets
        them with a red exit code and teaches them to ignore it. A tool that is present
        but will not report its version is a different matter: something is broken.
        """
        if self.data_dir_error is not None:
            return True
        return any(tool.status == "error" for tool in self.tools)


def _run_version(cmd: Sequence[str]) -> tuple[Status, str | None, str | None]:
    """Invoke a version command. Returns ``(status, version, detail)``.

    Any failure is reported, never raised: ``doctor`` runs precisely when the environment
    is suspect, so it must survive a tool that hangs, crashes, or prints to stderr.
    """
    try:
        result = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "error", None, f"timed out after {_VERSION_TIMEOUT_S}s"
    except OSError as exc:
        return "error", None, f"could not execute ({exc.__class__.__name__})"

    # Java prints its version to stderr; PLINK 2 and R use stdout. Take whichever spoke.
    text = (result.stdout or result.stderr).strip()
    if not text:
        return "error", None, f"no version output (exit {result.returncode})"

    first = text.splitlines()[0].strip()
    if result.returncode != 0:
        return "error", first, f"exit {result.returncode}"
    return "ok", first, None


def _which(name: str, tool_id: str | None = None) -> str | None:
    """Locate an executable, searching the app's own tools dir before PATH.

    M2.5 installs pinned builds under the user-data directory rather than expecting a
    system install, so a PATH-only lookup would miss the copy this project put there.

    **The installer's own record is consulted first.** This function originally guessed at
    the layout -- scanning the tools directory one level deep -- and M2.5 then installed to
    ``<tools_root>/<id>/<version>/``, two levels down. The result was that ``doctor``
    reported PLINK 2 missing immediately after ``genetics tools install`` succeeded: the
    command whose entire job is saying what you have, contradicting the command that had
    just put it there. Two modules written from the same mental model and never actually
    connected. Reading what the installer wrote removes the guess; the directory scan stays
    as a fallback for a tool placed there by hand.
    """
    try:
        local = tools_dir()
    except UnsafeDataDirError:
        return shutil.which(name)

    if tool_id is not None:
        try:
            from genetics.refs.tools import recorded_path

            recorded = recorded_path(local, tool_id)
        except Exception:
            recorded = None
        if recorded is not None:
            return str(recorded)

    if local.is_dir():
        found = shutil.which(name, path=str(local))
        if found:
            return found
        # Fallback for a hand-placed binary: scan the tools tree rather than assuming a
        # fixed depth, since that assumption is precisely what failed before.
        for child in sorted(p for p in local.rglob("*") if p.is_dir()):
            found = shutil.which(name, path=str(child))
            if found:
                return found

    return shutil.which(name)


def _check_plink2() -> ToolReport:
    path = _which("plink2", tool_id="plink2")
    if path is None:
        return ToolReport(
            name="plink2",
            required_from="M5",
            status="missing",
            detail="not on PATH or in the tools dir; `genetics tools install` fetches it",
        )
    status, version, detail = _run_version([path, "--version"])
    return ToolReport("plink2", "M5", status, path, version, detail)


def _check_java() -> ToolReport:
    path = _which("java")
    if path is None:
        return ToolReport(
            name="java",
            required_from="M8",
            status="missing",
            detail="no JVM found; Beagle imputation cannot run without one",
        )
    status, version, detail = _run_version([path, "-version"])
    return ToolReport("java", "M8", status, path, version, detail)


def _check_beagle() -> ToolReport:
    """Beagle is a jar, so presence means a file on disk, not an executable on PATH."""
    try:
        candidates = sorted(tools_dir().glob("**/beagle*.jar"))
    except (UnsafeDataDirError, OSError):
        candidates = []

    env_jar = os.environ.get("GENETICS_BEAGLE_JAR")
    if env_jar:
        candidate = Path(env_jar).expanduser()
        if candidate.is_file():
            candidates.insert(0, candidate)
        else:
            return ToolReport(
                name="beagle",
                required_from="M8",
                status="error",
                detail="GENETICS_BEAGLE_JAR is set but points at no file",
            )

    if not candidates:
        return ToolReport(
            name="beagle",
            required_from="M8",
            status="missing",
            detail="no beagle*.jar in the tools dir; `genetics tools install` fetches it",
        )

    # Newest by mtime, not first by name. Beagle jars are named by release *date* --
    # `beagle.28jun21.220.jar`, `beagle.05May22.33a.jar` -- which does not sort
    # chronologically as text: ascending, `05May22` precedes `28jun21`, so picking
    # `sorted(...)[0]` handed M8 the older of two installed versions.
    # An explicit GENETICS_BEAGLE_JAR still wins; it was prepended above.
    jar = candidates[0] if env_jar else max(candidates, key=lambda p: p.stat().st_mtime)

    # Deliberately not launched: Beagle has no cheap --version and starting a JVM to ask
    # would make `doctor` slow for no gain. The filename carries the version.
    return ToolReport("beagle", "M8", "ok", str(jar), jar.stem, None)


def _check_r() -> ToolReport:
    path = _which("Rscript")
    if path is None:
        return ToolReport(
            name="R (HIBAG)",
            required_from="M11 (optional)",
            status="missing",
            detail="HLA imputation is skipped without R; every other section is unaffected",
        )
    status, version, detail = _run_version([path, "--version"])
    if status != "ok":
        return ToolReport("R (HIBAG)", "M11 (optional)", status, path, version, detail)

    # The probe must *print* on success. `_run_version` treats empty output as an error,
    # and the obvious silent form -- `if (!requireNamespace(...)) quit(status=1)` -- prints
    # nothing when the package is present, so it reported "R is installed but HIBAG is
    # not" on every machine including ones where HIBAG was installed. The success path was
    # unreachable.
    hibag_status, _, _ = _run_version(
        [
            path,
            "-e",
            'if (!requireNamespace("HIBAG", quietly=TRUE)) quit(status=1); cat("HIBAG ok\\n")',
        ]
    )
    if hibag_status != "ok":
        return ToolReport(
            name="R (HIBAG)",
            required_from="M11 (optional)",
            status="missing",
            path=path,
            version=version,
            detail="R is installed but the HIBAG package is not",
        )
    return ToolReport("R (HIBAG)", "M11 (optional)", "ok", path, f"{version} + HIBAG", None)


def _free_disk_gb(path: Path) -> float | None:
    """Free space on the volume holding ``path``, or its nearest existing ancestor.

    Falls back up the tree because the data directory legitimately does not exist yet on
    a fresh checkout, and ``shutil.disk_usage`` raises on a missing path.
    """
    probe: Path | None = path
    while probe is not None:
        if probe.exists():
            try:
                return round(shutil.disk_usage(probe).free / 1024**3, 1)
            except OSError:
                return None
        probe = probe.parent if probe.parent != probe else None
    return None


def collect() -> Report:
    """Gather the full environment report. Never raises."""
    data_dir: str | None
    data_dir_error: str | None = None
    free_gb: float | None = None
    try:
        resolved = user_data_dir()
        data_dir = str(resolved)
        free_gb = _free_disk_gb(resolved)
    except UnsafeDataDirError as exc:
        # Reporting this rather than raising is the point: doctor is what you run to
        # find out why everything else refuses to start.
        data_dir = None
        data_dir_error = str(exc)

    refs = references_dir()
    reference_files = 0
    if refs.is_dir():
        reference_files = sum(1 for p in refs.rglob("*") if p.is_file())

    return Report(
        engine_version=__version__,
        python_version=platform.python_version(),
        python_executable=sys.executable,
        platform_name=platform.system(),
        platform_release=platform.release(),
        machine=platform.machine(),
        data_dir=data_dir,
        data_dir_error=data_dir_error,
        free_disk_gb=free_gb,
        references_present=refs.is_dir(),
        manifest_present=reference_manifest().is_file(),
        lock_present=reference_lock().is_file(),
        reference_files=reference_files,
        tools=(_check_plink2(), _check_java(), _check_beagle(), _check_r()),
    )


def to_dict(report: Report) -> dict[str, object]:
    """JSON-serialisable form. The CLI is the agent interface (AGENTS.md 3)."""
    payload = asdict(report)
    payload["has_problem"] = report.has_problem
    return payload
