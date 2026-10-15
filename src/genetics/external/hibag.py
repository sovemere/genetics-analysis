"""Optional, offline R/HIBAG readiness and private subprocess execution (M11.1).

Process success is not an HLA result. Scientific output needs a separate versioned
validator in the calling module. No classifier or personal input is read by a probe.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from genetics.external.process import stop as _stop
from genetics.paths import cache_dir, is_inside_repo
from genetics.privacy import NoGenotypeRepr

ReadinessStatus = Literal["ready", "r-missing", "hibag-missing", "probe-error"]
ProbeFailure = Literal["configuration", "execution", "timeout", "protocol", "namespace"]
if sys.platform == "win32":
    _FLAGS = subprocess.CREATE_NO_WINDOW
else:
    _FLAGS = 0
_VERSION = re.compile(r"[0-9]+(?:[.-][0-9]+)+")
_PLATFORM = re.compile(r"[A-Za-z0-9_.-]{1,160}")

# find.package distinguishes absence from a namespace/dependency/DLL load failure.
# Base R suffices for this protocol; no JSON package is a bootstrap dependency.
_R_IDENTITY = r"""
identity <- function(destination="") {
    present <- length(find.package("HIBAG", quiet=TRUE)) > 0L
    state <- if (present) "ready" else "hibag-missing"
    hv <- "-"
    if (present) {
        hv <- as.character(utils::packageVersion("HIBAG"))
        loaded <- tryCatch({
            utils::capture.output(invisible(loadNamespace("HIBAG")), file=stderr())
            TRUE
        }, error=function(e) {
            message(conditionMessage(e))
            FALSE
        })
        if (loaded) {
            hv <- as.character(getNamespaceVersion("HIBAG"))
        } else {
            state <- "load-error"
        }
    }
    cat("genetics-hibag", "1", state, as.character(getRversion()),
        R.version$platform, hv, sep="\t", file=destination)
    cat("\n", file=destination, append=TRUE)
    state
}
"""
_R_PROBE = "local({\n" + _R_IDENTITY + "\ninvisible(identity())\n})\n"
_R_BRIDGE = (
    # Bootstrap bindings must not shadow base::identity or leak into sourced code.
    "local({\n"
    + _R_IDENTITY
    + r"""
a <- commandArgs(trailingOnly=TRUE)
stopifnot(length(a) >= 5L)
# The initial load is private console output, not a completed job protocol.
if (identity() != "ready") quit(status=2L)
stopifnot(identical(a[[3L]], as.character(getRversion())),
          identical(a[[4L]], R.version$platform),
          identical(a[[5L]], as.character(getNamespaceVersion("HIBAG"))))
scope <- new.env(parent=globalenv())
scope$bridge_args <- a[-seq_len(5L)]
sys.source(a[[2L]], envir=scope)
if (identity(a[[1L]]) != "ready") quit(status=2L)
})
"""
)


class HIBAGError(RuntimeError):
    """Only categorical, public-safe messages; never raw R errors or arguments."""


class HIBAGTimeoutError(HIBAGError):
    pass


class HIBAGCancelledError(HIBAGError):
    pass


class HIBAGProtocolError(HIBAGError):
    pass


@dataclass(frozen=True)
class Readiness:
    status: ReadinessStatus
    detail: str
    path: Path | None = None
    r_version: str | None = None
    r_platform: str | None = None
    hibag_version: str | None = None
    failure: ProbeFailure | None = None


@dataclass(frozen=True)
class BridgeResult(NoGenotypeRepr):
    """Validated execution identity, NOT validated HLA evidence or a saved sample record."""

    _repr_fields: ClassVar[tuple[str, ...]] = ()
    runtime: HIBAGRuntime
    directory: Path
    stdout: Path
    stderr: Path
    protocol_version: int = 1


def _env() -> dict[str, str]:
    env = dict(os.environ)
    # --vanilla disables startup files; also stop inherited launch overrides/tracing.
    for key in (
        "RHOME",
        "R_HOME",
        "R_PROFILE",
        "R_PROFILE_USER",
        "R_ENVIRON",
        "R_ENVIRON_USER",
        "R_DEFAULT_PACKAGES",
        "R_SCRIPT_DEFAULT_PACKAGES",
        "_R_TRACE_LOADNAMESPACE_",
    ):
        env.pop(key, None)
    return env


def _seconds(value: float) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise HIBAGError("R execution timeout must be positive finite seconds.")


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise HIBAGCancelledError("R execution was cancelled.")


def _workspace() -> Path:
    path = cache_dir() / "hibag" / f"{uuid.uuid4().hex}.hibag-work"
    if is_inside_repo(path):
        raise HIBAGError("R diagnostics must be outside the repository.")
    path.mkdir(parents=True)
    return path


def _execute(
    command: list[str], directory: Path, timeout: float, cancel: threading.Event | None
) -> None:
    """Bound execution, redirect streams to disk, and reap on every interruption."""
    _seconds(timeout)
    _check_cancel(cancel)
    process: subprocess.Popen[bytes] | None = None
    started = time.monotonic()
    try:
        with (
            (directory / "stdout.log").open("wb") as out,
            (directory / "stderr.log").open("wb") as err,
        ):
            process = subprocess.Popen(
                command,
                cwd=directory,
                env=_env(),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                creationflags=_FLAGS,
            )
            while True:
                _check_cancel(cancel)
                if time.monotonic() - started >= timeout:
                    raise HIBAGTimeoutError("R execution timed out.")
                try:
                    code = process.wait(timeout=min(0.1, timeout))
                    break
                except subprocess.TimeoutExpired:
                    continue
            # A signal/deadline reached during the terminal wait still applies.
            _check_cancel(cancel)
            if time.monotonic() - started >= timeout:
                raise HIBAGTimeoutError("R execution timed out.")
            if code != 0:
                raise HIBAGError("R execution exited unsuccessfully; inspect private diagnostics.")
    except (OSError, ValueError):
        raise HIBAGError("R execution could not start or write private diagnostics.") from None
    finally:
        if process is not None and process.poll() is None:
            _stop(process)


def _protocol(path: Path, executable: Path) -> Readiness:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 4096:
            raise ValueError
        with path.open(encoding="utf-8") as handle:
            text = handle.read(4097)
        if len(text) > 4096 or not text.endswith("\n") or text.count("\n") != 1:
            raise ValueError
        fields = text[:-1].split("\t")
        if len(fields) != 6 or fields[:2] != ["genetics-hibag", "1"]:
            raise ValueError
        _, _, state, rv, platform, hv = fields
        if not _VERSION.fullmatch(rv) or not _PLATFORM.fullmatch(platform):
            raise ValueError
        if state == "ready" and _VERSION.fullmatch(hv):
            return Readiness(
                "ready",
                "R and HIBAG are ready; no HLA call was made.",
                executable,
                rv,
                platform,
                hv,
            )
        if state == "hibag-missing" and hv == "-":
            return Readiness(
                "hibag-missing",
                "R is installed but the HIBAG package is not installed.",
                executable,
                rv,
                platform,
            )
        if state == "load-error" and _VERSION.fullmatch(hv):
            return Readiness(
                "probe-error",
                "HIBAG is installed but its namespace could not load.",
                executable,
                rv,
                platform,
                hv,
                failure="namespace",
            )
        raise ValueError
    except (OSError, UnicodeError, ValueError):
        raise HIBAGProtocolError("R returned malformed runtime protocol output.") from None


def probe(
    path: Path | None = None,
    *,
    timeout: float = 20,
    cancel: threading.Event | None = None,
) -> Readiness:
    """Shared optional readiness; operational errors are never package absence.

    Cancellation propagates so an interrupted caller does not keep working. Ordinary
    discovery/execution/protocol failures are reportable states for doctor and HLA.
    """
    _seconds(timeout)
    _check_cancel(cancel)
    override = os.environ.get("GENETICS_RSCRIPT")
    try:
        found = str(path) if path is not None else override or shutil.which("Rscript")
        if found is None:
            return Readiness("r-missing", "R not installed; HLA imputation is unavailable.")
        executable = Path(found).expanduser().resolve()
        if not executable.is_file():
            return Readiness(
                "probe-error",
                "Configured Rscript executable is missing.",
                executable,
                failure="configuration",
            )
        directory = _workspace()
        _execute(
            [str(executable), "--vanilla", "--default-packages=NULL", "-e", _R_PROBE],
            directory,
            timeout,
            cancel,
        )
        return _protocol(directory / "stdout.log", executable)
    except HIBAGCancelledError:
        raise
    except HIBAGTimeoutError:
        return Readiness("probe-error", "R/HIBAG readiness probe timed out.", failure="timeout")
    except HIBAGProtocolError:
        return Readiness(
            "probe-error",
            "R/HIBAG readiness probe returned malformed output.",
            failure="protocol",
        )
    except HIBAGError:
        return Readiness(
            "probe-error",
            "R/HIBAG readiness probe failed; inspect private diagnostics.",
            failure="execution",
        )
    except (OSError, ValueError, RuntimeError):
        return Readiness(
            "probe-error",
            "R/HIBAG readiness configuration is unusable.",
            failure="configuration",
        )


@dataclass(frozen=True)
class HIBAGRuntime:
    path: Path
    r_version: str
    r_platform: str
    hibag_version: str

    @classmethod
    def discover(
        cls,
        path: Path | None = None,
        *,
        timeout: float = 20,
        cancel: threading.Event | None = None,
    ) -> HIBAGRuntime:
        return cls.from_readiness(probe(path, timeout=timeout, cancel=cancel))

    @classmethod
    def from_readiness(cls, result: Readiness) -> HIBAGRuntime:
        if result.status != "ready":
            raise HIBAGError(result.detail)
        if (
            result.path is None
            or result.r_version is None
            or result.r_platform is None
            or result.hibag_version is None
            or not _VERSION.fullmatch(result.r_version)
            or not _PLATFORM.fullmatch(result.r_platform)
            or not _VERSION.fullmatch(result.hibag_version)
        ):
            raise HIBAGError("R/HIBAG readiness identity is incomplete or invalid.")
        return cls(result.path, result.r_version, result.r_platform, result.hibag_version)

    def run_script(
        self,
        script: Path,
        args: Sequence[str] = (),
        *,
        timeout: float = 3600,
        cancel: threading.Event | None = None,
    ) -> BridgeResult:
        """Run trusted local R source with `bridge_args` in its source environment.

        Arguments are separate OS argv elements; never interpolate data into R source.
        Scripts use the private working directory for outputs. No result is reused or
        published as a biological call. The caller must validate scientific payloads.
        """
        _seconds(timeout)
        _check_cancel(cancel)
        if isinstance(args, (str, bytes)) or any(
            not isinstance(arg, str) or "\0" in arg for arg in args
        ):
            raise HIBAGError("R script arguments must be strings without NUL characters.")
        try:
            source = script.resolve(strict=True)
            if not source.is_file():
                raise OSError
            directory = _workspace()
        except HIBAGError:
            raise
        except (OSError, ValueError, RuntimeError):
            raise HIBAGError("R script or private working directory is unavailable.") from None
        protocol = directory / "runtime.hibag.tsv"
        _execute(
            [
                str(self.path),
                "--vanilla",
                "--default-packages=NULL",
                "-e",
                _R_BRIDGE,
                str(protocol),
                str(source),
                self.r_version,
                self.r_platform,
                self.hibag_version,
                *args,
            ],
            directory,
            timeout,
            cancel,
        )
        actual = self.from_readiness(_protocol(protocol, self.path))
        if actual != self:
            raise HIBAGError("R/HIBAG identity changed after discovery; no result accepted.")
        return BridgeResult(self, directory, directory / "stdout.log", directory / "stderr.log")
