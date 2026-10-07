"""Pinned Beagle jobs with private output, streaming progress and atomic completion.

Resume verifies an entire completed invocation, never a partial VCF or an internal
Beagle window. M8.3 will schedule chromosome jobs through this same interface.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from genetics.paths import cache_dir, is_inside_repo, tools_dir
from genetics.privacy import NoGenotypeRepr
from genetics.refs import tools

if sys.platform == "win32":
    _CREATION_FLAGS = subprocess.CREATE_NO_WINDOW
else:
    _CREATION_FLAGS = 0


class BeagleError(RuntimeError):
    """Messages are categorical: raw JVM/Beagle output never enters an exception."""


class BeagleNotFoundError(BeagleError):
    pass


class BeagleVersionError(BeagleError):
    pass


class BeagleCheckpointError(BeagleError):
    pass


class BeagleBusyError(BeagleError):
    pass


class BeagleRunError(BeagleError):
    def __init__(self, message: str, *, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()


def _java_env() -> dict[str, str]:
    env = dict(os.environ)
    # These override memory options and can install JVM agents. Use only recorded options.
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        env.pop(key, None)
    return env


@dataclass(frozen=True)
class JavaRuntime:
    path: Path
    version: str
    major: int

    @classmethod
    def discover(cls, path: Path | None = None) -> JavaRuntime:
        if path is None:
            home = os.environ.get("JAVA_HOME")
            found = (
                str(Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java"))
                if home
                else shutil.which("java")
            )
            if found is None:
                raise BeagleNotFoundError("Java is not installed; Beagle requires Java 8 or later.")
            path = Path(found)
        if not path.is_file():
            raise BeagleNotFoundError(
                "Configured Java executable is missing; check JAVA_HOME or PATH."
            )
        try:
            result = subprocess.run(
                [str(path), "-version"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                env=_java_env(),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise BeagleVersionError("Java version probe could not complete.") from None
        match = re.search(
            r'(?:openjdk|java) version "((?:1\.)?\d+[^"\r\n]*)"', result.stdout + result.stderr
        )
        if result.returncode != 0 or match is None:
            raise BeagleVersionError("Java did not report a supported runtime version.")
        version = match[1]
        number = re.match(r"\d+", version)
        assert number is not None
        major = int(version.split(".")[1] if version.startswith("1.") else number[0])
        if major < 8:
            raise BeagleVersionError(
                "Beagle requires Java 8 or later; the configured Java is older."
            )
        return cls(path.resolve(), version, major)


def locate_beagle(
    *, tools_root: Path | None = None, manifest: tools.ToolManifest | None = None
) -> tuple[Path, str, str]:
    """Locate and checksum the exact manifest jar; never choose a release by mtime."""
    root = tools_root if tools_root is not None else tools_dir()
    tool = (manifest or tools.load()).get("beagle")
    build = tool.build_for(tools.ANY_PLATFORM)
    if tool.kind is not tools.Kind.JAR or build is None or build.archive:
        raise BeagleVersionError("Beagle manifest must pin one portable, non-archive jar.")
    override = os.environ.get("GENETICS_BEAGLE_JAR")
    jar = Path(override).expanduser() if override else tools.installed_path(root, tool, build)
    if not override and not jar.is_file():
        jar = tools.recorded_path(root, "beagle") or jar
    if not jar.is_file():
        raise BeagleNotFoundError(
            "Pinned Beagle jar is missing; run genetics tools install --only beagle."
        )
    try:
        digest = _digest(jar)
    except OSError:
        raise BeagleVersionError("Beagle jar is unreadable; reinstall the pinned tool.") from None
    if digest != build.sha256:
        raise BeagleVersionError(
            "Beagle jar differs from its pinned SHA256; reinstall with --force."
        )
    return jar.resolve(), tool.version, digest


@dataclass(frozen=True)
class BeagleOptions:
    memory_mb: int = 8192
    nthreads: int = 1
    seed: int = -99999
    impute: bool = True
    chrom: str | None = None

    def __post_init__(self) -> None:
        if type(self.memory_mb) is not int or self.memory_mb < 512:
            raise BeagleError("memory_mb must be an integer of at least 512 MiB.")
        if type(self.nthreads) is not int or self.nthreads < 1:
            raise BeagleError("nthreads must be a positive integer.")
        if type(self.seed) is not int or not -(2**63) <= self.seed < 2**63:
            raise BeagleError("seed must be a signed 64-bit integer.")
        if type(self.impute) is not bool:
            raise BeagleError("impute must be a boolean.")
        if self.chrom is not None and (
            not isinstance(self.chrom, str)
            or not re.fullmatch(r"[A-Za-z0-9_]+(?::[0-9]*-[0-9]*)?", self.chrom)
        ):
            raise BeagleError("chrom must be a chromosome or chromosome:start-end interval.")


@dataclass(frozen=True)
class BeagleResult(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("resumed",)
    vcf: Path
    log: Path
    checkpoint: Path
    resumed: bool
    provenance: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Private job provenance; fingerprints and paths must never be committed."""
        result: dict[str, Any] = json.loads(
            json.dumps(
                {
                    "vcf": str(self.vcf),
                    "log": str(self.log),
                    "checkpoint": str(self.checkpoint),
                    "resumed": self.resumed,
                    "provenance": dict(self.provenance),
                }
            )
        )
        return result


@contextmanager
def _job_lock(path: Path) -> Iterator[None]:
    """Kernel-owned lock: process death releases it, unlike a PID sentinel file."""
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BeagleBusyError(
                "Another process is using this Beagle job; retry after it exits."
            ) from None
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _input(path: Path | None, role: str) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or not resolved.stat().st_size:
            raise OSError
        return {
            "path": str(resolved),
            "size_bytes": resolved.stat().st_size,
            "sha256": _digest(resolved),
        }
    except OSError:
        raise BeagleError(f"Beagle {role} input is missing, empty or unreadable.") from None


def _target_samples(path: Path) -> tuple[str, ...]:
    """Read sample identity privately; never include identifiers in diagnostics."""
    try:
        with path.open("rb") as probe:
            compressed = probe.read(2) == b"\x1f\x8b"
        opener = gzip.open if compressed else open
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("##"):
                    continue
                fields = line.rstrip("\r\n").split("\t")
                if (
                    fields[:9]
                    != ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
                    or len(fields) < 10
                ):
                    raise ValueError
                samples = tuple(fields[9:])
                if any(not value for value in samples) or len(set(samples)) != len(samples):
                    raise ValueError
                return samples
        raise ValueError
    except (OSError, EOFError, UnicodeError, ValueError):
        raise BeagleRunError("Beagle target has no valid unique sample header.") from None


def _validate_vcf(
    path: Path, *, expected_samples: tuple[str, ...], chrom: str | None = None
) -> None:
    """Stream all BGZF/gzip bytes to verify CRCs and a complete phased GT table."""
    try:
        columns = 0
        records = 0
        last: dict[str, int] = {}
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("##"):
                    if columns:
                        raise ValueError
                    continue
                fields = line.rstrip("\r\n").split("\t")
                if line.startswith("#CHROM"):
                    if (
                        columns
                        or len(fields) < 10
                        or fields[:9]
                        != ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
                        or len(set(fields[9:])) != len(fields[9:])
                        or tuple(fields[9:]) != expected_samples
                    ):
                        raise ValueError
                    columns = len(fields)
                    continue
                if not columns or len(fields) != columns or "GT" not in fields[8].split(":"):
                    raise ValueError
                pos = int(fields[1])
                if pos <= 0 or pos < last.get(fields[0], 0):
                    raise ValueError
                if chrom is not None:
                    region, _, interval = chrom.partition(":")
                    lo, _, hi = interval.partition("-")
                    if fields[0] != region or (lo and pos < int(lo)) or (hi and pos > int(hi)):
                        raise ValueError
                last[fields[0]] = pos
                gt_index = fields[8].split(":").index("GT")
                allele_count = len(fields[4].split(",")) + 1
                for call in fields[9:]:
                    genotype = call.split(":")[gt_index]
                    if not re.fullmatch(r"[0-9]+\|[0-9]+", genotype) or any(
                        int(a) >= allele_count for a in genotype.split("|")
                    ):
                        raise ValueError
                records += 1
        if not records:
            raise ValueError
    except (OSError, EOFError, UnicodeError, ValueError, IndexError):
        raise BeagleRunError(
            "Beagle output is damaged, unphased or inconsistent with target samples/region."
        ) from None


def _progress_line(line: str) -> str | None:
    # Never relay paths, intervals, marker IDs, sample IDs, arguments or error lines.
    match = re.fullmatch(r"Window\s+(\d+)\s+\[.*\]:?", line.strip())
    return f"Beagle window {match[1]}" if match else None


_ProcessText = TypeVar("_ProcessText", str, bytes)


def _stop(process: subprocess.Popen[_ProcessText]) -> None:
    if process.poll() is None:
        if sys.platform == "win32":
            # A Windows launcher can own a child JVM. Kill this process tree only.
            with suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    [
                        str(Path(os.environ["SYSTEMROOT"]) / "System32" / "taskkill.exe"),
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            if process.poll() is not None:
                return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@dataclass(frozen=True)
class Beagle:
    java: JavaRuntime
    jar: Path
    version: str
    sha256: str

    @classmethod
    def discover(
        cls,
        *,
        tools_root: Path | None = None,
        manifest: tools.ToolManifest | None = None,
        java: Path | None = None,
    ) -> Beagle:
        jar, version, digest = locate_beagle(tools_root=tools_root, manifest=manifest)
        return cls(JavaRuntime.discover(java), jar, version, digest)

    def run(
        self,
        *,
        gt: Path,
        ref: Path | None = None,
        genetic_map: Path,
        out: Path | None = None,
        options: BeagleOptions | None = None,
        progress: Callable[[str], None] | None = None,
        timeout: float | None = None,
        progress_interval: float = 15,
        allow_in_repo: bool = False,
    ) -> BeagleResult:
        """Run or reuse one invocation. No algorithm weakening or timeout by default.

        ``out`` is a stable job prefix, not a VCF pathname. Completed outputs live in
        ``<out>.beagle-work/complete`` and are published by one directory rename.
        Failed/interrupted attempts remain private for inspection and are never resumed.
        """
        options = options or BeagleOptions()
        if options.impute and ref is None:
            raise BeagleError(
                "Default imputation requires a reference panel; phase-only must be explicit."
            )
        for value in (timeout, progress_interval):
            if value is not None and (
                type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            ):
                raise BeagleError("Timeout and progress interval must be positive finite seconds.")
        emit = progress or (lambda message: None)
        emit("Verifying Beagle job inputs")
        if _digest(self.jar) != self.sha256:
            raise BeagleVersionError(
                "Beagle jar changed after discovery; reinstall the pinned tool."
            )
        runtime = JavaRuntime.discover(self.java.path)
        if runtime != self.java:
            raise BeagleVersionError("Java changed after discovery; discover the runtime again.")
        target_input = _input(gt, "target")
        map_input = _input(genetic_map, "genetic map")
        if target_input is None or map_input is None:
            raise BeagleError("A target VCF and genetic map are required.")
        expected_samples = _target_samples(Path(target_input["path"]))
        inputs = {
            "gt": target_input,
            "ref": _input(ref, "reference"),
            "map": map_input,
        }
        java_sha256 = _digest(self.java.path)
        contract = {
            "schema_version": 1,
            "beagle": {"version": self.version, "sha256": self.sha256},
            "java": {
                "version": self.java.version,
                "major": self.java.major,
                "executable_sha256": java_sha256,
            },
            "inputs": inputs,
            "options": asdict(options),
        }
        key = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
        prefix = out if out is not None else cache_dir() / "beagle" / key / "job"
        prefix = prefix.absolute()
        if prefix.is_dir() or prefix.is_symlink():
            raise BeagleError("Beagle out must be a regular job prefix, not a directory or link.")
        if is_inside_repo(prefix) and not allow_in_repo:
            raise BeagleError(
                "Beagle output must be outside the repo; in-repo output requires explicit opt-in."
            )
        root = prefix.with_name(prefix.name + ".beagle-work")
        if root.is_symlink():
            raise BeagleError("Beagle workspace cannot be a symbolic link.")
        root.mkdir(parents=True, exist_ok=True)
        lock = root / "job.beagle.lock"
        if lock.is_symlink():
            raise BeagleError("Beagle job lock cannot be a symbolic link.")
        with _job_lock(lock):
            complete = root / "complete"
            if complete.exists() or complete.is_symlink():
                result = self._resume(complete, contract, expected_samples)
                emit("Reusing verified completed Beagle job")
                return result
            attempt = root / f"attempt-{uuid.uuid4().hex}"
            attempt.mkdir()
            actual_out = attempt / "result"
            args = [
                str(self.java.path),
                f"-Xmx{options.memory_mb}m",
                "-jar",
                str(self.jar),
                f"gt={target_input['path']}",
                f"map={map_input['path']}",
                f"out={actual_out}",
                f"impute={str(options.impute).lower()}",
                f"seed={options.seed}",
                f"nthreads={options.nthreads}",
            ]
            if ref is not None:
                reference_input = inputs["ref"]
                assert reference_input is not None
                args.append(f"ref={reference_input['path']}")
            if options.chrom is not None:
                args.append(f"chrom={options.chrom}")
            emit(
                "Starting Beagle imputation" if options.impute else "Starting Beagle phase-only job"
            )
            started = time.monotonic()
            self._execute(args, attempt / "console.log", emit, timeout, progress_interval)
            vcf, log = attempt / "result.vcf.gz", attempt / "result.log"
            _validate_vcf(vcf, expected_samples=expected_samples, chrom=options.chrom)
            if not log.is_file() or not log.stat().st_size:
                raise BeagleRunError("Beagle did not produce its completion log.")
            # Changing inputs during a job cannot produce a reusable completed checkpoint.
            if (
                inputs
                != {
                    "gt": _input(gt, "target"),
                    "ref": _input(ref, "reference"),
                    "map": _input(genetic_map, "genetic map"),
                }
                or _digest(self.jar) != self.sha256
                or _digest(self.java.path) != java_sha256
            ):
                raise BeagleCheckpointError(
                    "Beagle inputs, jar or runtime changed during execution; "
                    "no completion was published."
                )
            saved = {
                "contract": contract,
                "elapsed_seconds": time.monotonic() - started,
                "files": {
                    p.name: {"sha256": _digest(p), "size_bytes": p.stat().st_size}
                    for p in (vcf, log)
                },
            }
            checkpoint = attempt / "beagle.run.json"
            with checkpoint.open("w", encoding="utf-8") as handle:
                json.dump(saved, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            if complete.exists() or complete.is_symlink():
                raise BeagleCheckpointError(
                    "Beagle completion destination was created concurrently."
                )
            os.rename(attempt, complete)
            emit("Beagle job completed and checkpointed")
            return BeagleResult(
                complete / vcf.name, complete / log.name, complete / checkpoint.name, False, saved
            )

    def _resume(
        self, complete: Path, contract: Mapping[str, Any], expected_samples: tuple[str, ...]
    ) -> BeagleResult:
        try:
            if complete.is_symlink() or any(p.is_symlink() for p in complete.iterdir()):
                raise ValueError
            checkpoint = complete / "beagle.run.json"
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            if set(saved) != {"contract", "files", "elapsed_seconds"} or json.dumps(
                saved["contract"], sort_keys=True, allow_nan=False
            ) != json.dumps(contract, sort_keys=True, allow_nan=False):
                raise ValueError
            elapsed = saved["elapsed_seconds"]
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError
            if set(saved["files"]) != {"result.vcf.gz", "result.log"}:
                raise ValueError
            for name, info in saved["files"].items():
                path = complete / name
                if (
                    set(info) != {"sha256", "size_bytes"}
                    or type(info["size_bytes"]) is not int
                    or info["size_bytes"] <= 0
                    or path.stat().st_size != info["size_bytes"]
                    or _digest(path) != info["sha256"]
                ):
                    raise ValueError
            _validate_vcf(
                complete / "result.vcf.gz",
                expected_samples=expected_samples,
                chrom=contract["options"]["chrom"],
            )
            return BeagleResult(
                complete / "result.vcf.gz", complete / "result.log", checkpoint, True, saved
            )
        except (OSError, ValueError, TypeError, KeyError, BeagleRunError):
            raise BeagleCheckpointError(
                "Completed Beagle job is damaged or its identity changed; use a new job prefix."
            ) from None

    def _execute(
        self,
        args: list[str],
        console: Path,
        emit: Callable[[str], None],
        timeout: float | None,
        interval: float,
    ) -> None:
        pending: list[str] = []
        errors: list[Exception] = []
        heap_failure = threading.Event()
        mutex = threading.Lock()
        process: subprocess.Popen[str] | None = None
        thread: threading.Thread | None = None
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=console.parent,
                env=_java_env(),
                creationflags=_CREATION_FLAGS,
            )
            assert process.stdout is not None
            stream = process.stdout

            def read() -> None:
                try:
                    with console.open("w", encoding="utf-8") as handle:
                        for line in stream:
                            handle.write(line)
                            if "OutOfMemoryError" in line:
                                heap_failure.set()
                            message = _progress_line(line)
                            if message is not None:
                                with mutex:
                                    pending.append(message)
                except Exception as exc:
                    errors.append(exc)

            thread = threading.Thread(target=read, daemon=True)
            thread.start()
            started = last = time.monotonic()
            while process.poll() is None:
                now = time.monotonic()
                if errors:
                    raise BeagleRunError("Could not capture private Beagle output.")
                if timeout is not None and now - started >= timeout:
                    raise BeagleRunError("Beagle exceeded the explicitly requested timeout.")
                with mutex:
                    messages = pending[:]
                    pending.clear()
                for message in messages:
                    emit(message)
                if now - last >= interval:
                    emit("Beagle is running")
                    last = now
                time.sleep(min(0.1, interval))
            thread.join()
            if errors:
                raise BeagleRunError("Could not capture private Beagle output.")
            with mutex:
                messages = pending[:]
            for message in messages:
                emit(message)
            if process.returncode != 0:
                message = (
                    "Beagle exhausted its Java heap; increase memory_mb."
                    if heap_failure.is_set()
                    else "Beagle failed; inspect its private job logs."
                )
                raise BeagleRunError(message, returncode=process.returncode)
        except OSError:
            raise BeagleRunError("Could not launch or capture the Beagle subprocess.") from None
        finally:
            if process is not None:
                _stop(process)
                if thread is not None:
                    thread.join()
                if process.stdout is not None:
                    process.stdout.close()
