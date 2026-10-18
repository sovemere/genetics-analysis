"""Run the checks in ``.github/workflows/ci.yml`` on this machine.

From 2026-10-11 to 2026-10-16 CI failed on every push while every local run passed: one
test found bref3 and Beagle in this machine's user-data tools directory, and a runner has
nothing there. A local run is evidence about CI only if it reproduces what makes a runner
different from a development checkout, so this one does:

- **A fresh checkout.** Steps run in a temporary clone holding exactly what a push would
  publish -- the committed tree plus uncommitted, non-ignored changes, committed inside
  the clone so it is as clean as the runner's. Fetched references, raw exports and other
  ignored files in the working checkout stay invisible, as they are on a runner.
- **An empty data directory.** ``GENETICS_DATA_DIR`` points at a new, empty directory and
  every other inherited ``GENETICS_*`` variable is dropped, so a developer's test-tool
  paths cannot enable tests the workflow skips.
- **The workflow's installs.** Each matrix Python gets a cached uv venv with the clone
  installed as CI installs it. Pinned tools go through ``genetics tools install`` into a
  cached directory and reach the tests only through the variables the workflow sets.
- **The workflow's own commands.** Steps are read from ci.yml, not restated: an
  unrecognised step or variable fails the run instead of being skipped, and the no-data
  job's script is executed as written.

What it cannot reproduce is a runner on another operating system. mypy checks every
platform's types from one machine, but executing on Linux -- including the OS-level
network isolation the privacy suite requires there -- needs Linux. Nor does it install
R: the workflow installs R and HIBAG, while a local run uses the developer's Rscript
from PATH and says so when there is none, since the native HIBAG tests then skip.
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from genetics.external import hibag
from genetics.external.beagle import BeagleError, JavaRuntime
from genetics.paths import ci_dir, repo_root

WORKFLOW = Path(".github") / "workflows" / "ci.yml"
TEST_JOB = "test"
NO_DATA_JOB = "no-data-in-ci"

#: The workflow installs R for the native HIBAG tests; a local run uses the developer's.
R_ACTION = "r-lib/actions/setup-r"
#: Actions the test job uses to build its environment; the local run builds its own.
SETUP_ACTIONS = frozenset(
    {"actions/checkout", "astral-sh/setup-uv", "actions/setup-java", R_ACTION}
)
#: Shell lines that do the same. Everything else must be a ``uv run`` command.
SETUP_COMMANDS = ("uv python install ", "uv venv ", "uv pip install ", "Rscript ")
#: The workflow runs mypy once per runner OS; one machine checks every platform instead.
TYPE_PLATFORMS = ("win32", "linux")
#: Matrix ``os`` prefixes, mapped to the ``sys.platform`` that runs them.
RUNNER_PLATFORMS = {"windows": "win32", "ubuntu": "linux", "macos": "darwin"}

#: Variables the workflow sets per step, and how a local run fills each in from the
#: native tools directory. A name missing here fails the plan rather than going unset.
STEP_ENV: Mapping[str, Callable[[Path], str]] = {
    "GENETICS_DATA_DIR": lambda native: str(native),
    "GENETICS_ROH_TEST_TOOLS": lambda native: str(native / "tools"),
    "GENETICS_BEAGLE_TEST_TOOLS": lambda native: str(native / "tools"),
    "GENETICS_REQUIRE_OS_ISOLATION": lambda native: "1" if sys.platform == "linux" else "",
}

#: Inherited variables that describe the developer's environment rather than a runner's.
DROPPED_ENV = frozenset({"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"})


class CIError(RuntimeError):
    """The local run cannot be set up faithfully."""


@dataclass(frozen=True)
class Step:
    """One ``uv run`` command from the test job, and the variables its step sets."""

    name: str
    command: tuple[str, ...]
    env: tuple[str, ...] = ()


@dataclass(frozen=True)
class Outcome:
    label: str
    status: str  # "passed", "failed" or "not run"
    seconds: float = 0.0


def workflow(root: Path | None = None) -> dict[str, Any]:
    path = (root or repo_root()) / WORKFLOW
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
        raise CIError(f"{WORKFLOW.as_posix()} declares no jobs")
    return data


def _job(flow: Mapping[str, Any], name: str) -> dict[str, Any]:
    job = flow["jobs"].get(name)
    if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
        raise CIError(f"{WORKFLOW.as_posix()} has no {name!r} job with steps")
    return job


def matrix(flow: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The test job's runner OS names and Python versions."""
    axes = _job(flow, TEST_JOB).get("strategy", {}).get("matrix", {})
    return tuple(str(v) for v in axes.get("os", ())), tuple(str(v) for v in axes.get("python", ()))


def java_major(flow: Mapping[str, Any]) -> int:
    for step in _job(flow, TEST_JOB)["steps"]:
        if str(step.get("uses", "")).split("@")[0] == "actions/setup-java":
            return int(step["with"]["java-version"])
    raise CIError("the test job sets up no Java")


def installs_r(flow: Mapping[str, Any]) -> bool:
    return any(
        str(s.get("uses", "")).split("@")[0] == R_ACTION for s in _job(flow, TEST_JOB)["steps"]
    )


def hibag_gap(env: Mapping[str, str]) -> str | None:
    """Why the native HIBAG tests CI runs would skip here, or None when they run."""
    found = shutil.which("Rscript", path=env.get("PATH"))
    if found is None:
        return "no Rscript is on PATH."
    state = hibag.probe(Path(found))
    return None if state.status == "ready" else f"{found}: {state.detail}"


def plan(flow: Mapping[str, Any]) -> list[Step]:
    """Every command the test job runs, in order, with mypy expanded per platform."""
    steps: list[Step] = []
    for raw in _job(flow, TEST_JOB)["steps"]:
        uses = raw.get("uses")
        if uses is not None:
            if str(uses).split("@")[0] not in SETUP_ACTIONS:
                raise CIError(f"unrecognised action in the test job: {uses}")
            continue
        name = str(raw.get("name", "unnamed step"))
        env = tuple(raw.get("env") or {})
        unknown = sorted(set(env) - set(STEP_ENV))
        if unknown:
            raise CIError(f"step {name!r} sets {', '.join(unknown)}, which has no local value")
        for line in str(raw.get("run", "")).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(SETUP_COMMANDS):
                continue
            words = tuple(shlex.split(line))
            if words[:2] != ("uv", "run") or len(words) < 3:
                raise CIError(f"unrecognised command in the test job: {line}")
            command = words[2:]
            if command == ("mypy",):
                steps.extend(Step(name, (*command, "--platform", p), env) for p in TYPE_PLATFORMS)
            else:
                steps.append(Step(name, command, env))
    return steps


def no_data_script(flow: Mapping[str, Any]) -> str:
    """The no-data job's shell script, exactly as the workflow runs it."""
    steps = [s for s in _job(flow, NO_DATA_JOB)["steps"] if "run" in s]
    if len(steps) != 1 or steps[0].get("shell") != "bash":
        raise CIError(f"expected one bash step in the {NO_DATA_JOB!r} job")
    return str(steps[0]["run"])


def base_env(inherited: Mapping[str, str], java_home: Path | None) -> dict[str, str]:
    env = {
        key: value
        for key, value in inherited.items()
        if not key.upper().startswith("GENETICS_") and key.upper() not in DROPPED_ENV
    }
    if java_home is not None:
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = os.pathsep.join([str(java_home / "bin"), env.get("PATH", "")])
    return env


def materialise(source: Path, target: Path) -> bool:
    """Clone ``source`` and overlay its working tree; True when that added changes.

    Files git ignores are left behind, deleted files are deleted, and the result is
    committed in the clone, so tests reading ``HEAD`` see what a push would publish.
    """
    _git(source, "clone", "--quiet", str(source), str(target))
    wanted = [
        rel
        for rel in _git_paths(source, "--cached", "--others", "--exclude-standard")
        if (source / rel).is_file()
    ]
    for rel in set(_git_paths(target)) - set(wanted):
        (target / rel).unlink()
    for rel in wanted:
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target / rel)
    if not _git(target, "status", "--porcelain"):
        return False
    _git(target, "add", "--all")
    _git(
        target,
        "-c",
        "user.name=genetics ci-local",
        "-c",
        "user.email=ci-local@localhost",
        "commit",
        "--quiet",
        "--message",
        "Uncommitted working tree",
    )
    return True


def run(
    *,
    pythons: Sequence[str] | None = None,
    java_home: Path | None = None,
    emit: Callable[[str], None] = print,
) -> list[Outcome]:
    root = repo_root()
    flow = workflow(root)
    steps = plan(flow)
    script = no_data_script(flow)
    runners, matrix_pythons = matrix(flow)
    versions = tuple(pythons) if pythons else matrix_pythons
    found_uv = shutil.which("uv")
    if found_uv is None:
        raise CIError("uv is not on PATH; CI installs with uv, and so does this run")
    uv: str = found_uv
    env = base_env(os.environ, java_home)
    _check_java(env, java_major(flow))
    bash, bash_dir = _bash()
    cache = ci_dir()
    native = cache / "native"
    skipped = [r for r in runners if RUNNER_PLATFORMS.get(r.split("-")[0]) != sys.platform]
    if skipped:
        emit(f"Not reproduced on this machine: the {', '.join(skipped)} jobs.")
    gap = hibag_gap(env) if installs_r(flow) else None
    if gap is not None:
        emit(f"Not reproduced on this machine: the native HIBAG tests, because {gap}")

    outcomes: list[Outcome] = []
    with _scratch() as scratch:
        checkout, data = scratch / "checkout", scratch / "data"
        data.mkdir()
        env["GENETICS_DATA_DIR"] = str(data)
        emit(f"==> cloning {root} into {checkout}")
        if materialise(root, checkout):
            emit("    includes uncommitted, non-ignored changes")

        # GitHub runs a `shell: bash` step as `bash --noprofile --norc -eo pipefail`.
        script_file = scratch / "no-data.sh"
        script_file.write_text(script, encoding="utf-8", newline="\n")
        bash_env = {**env, "PATH": os.pathsep.join([bash_dir, env.get("PATH", "")])}
        no_data = [bash, "--noprofile", "--norc", "-eo", "pipefail", str(script_file)]
        outcomes.append(_execute("no real data present", emit, no_data, checkout, bash_env))

        for version in versions:
            venv = cache / f"py{version}"
            label = f"py{version} / Install project"
            outcomes.append(_timed(label, emit, partial(_venv, uv, venv, version, checkout, env)))
            for step in steps:
                label = f"py{version} / {step.name}: {' '.join(step.command)}"
                if outcomes[-1].status != "passed":
                    outcomes.append(Outcome(label, "not run"))
                    continue
                argv = [str(_venv_python(venv)), "-m", *_module(step.command)]
                step_env = {**env, **{name: STEP_ENV[name](native) for name in step.env}}
                outcomes.append(_execute(label, emit, argv, checkout, step_env))
    return outcomes


def _module(command: tuple[str, ...]) -> tuple[str, ...]:
    if command[0] == "genetics":
        return ("genetics.cli.main", *command[1:])
    return command


def _execute(
    label: str,
    emit: Callable[[str], None],
    argv: list[str],
    cwd: Path,
    env: Mapping[str, str],
) -> Outcome:
    def work() -> bool:
        return subprocess.run(argv, cwd=cwd, env=dict(env), check=False).returncode == 0

    return _timed(label, emit, work)


def _timed(label: str, emit: Callable[[str], None], work: Callable[[], bool]) -> Outcome:
    emit(f"==> {label}")
    started = time.monotonic()
    try:
        ok = work()
    except OSError as exc:
        emit(f"    {exc}")
        ok = False
    return Outcome(label, "passed" if ok else "failed", time.monotonic() - started)


def _venv(uv: str, directory: Path, version: str, checkout: Path, env: Mapping[str, str]) -> bool:
    """The workflow's ``uv venv`` and editable ``.[dev]`` install, into a cached venv."""
    run_env = dict(env)
    create = [uv, "venv", "--quiet", "--allow-existing", "--python", version, str(directory)]
    if subprocess.run(create, env=run_env, check=False).returncode != 0:
        return False
    python = str(_venv_python(directory))
    install = [uv, "pip", "install", "--quiet", "--python", python, "-e", f"{checkout}[dev]"]
    return subprocess.run(install, cwd=checkout, env=run_env, check=False).returncode == 0


def _venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _check_java(env: Mapping[str, str], required: int) -> None:
    home = env.get("JAVA_HOME")
    found = (
        str(Path(home) / "bin" / ("java.exe" if os.name == "nt" else "java"))
        if home
        else shutil.which("java", path=env.get("PATH"))
    )
    if found is None:
        raise CIError(f"CI runs Java {required}; none found. Set JAVA_HOME or pass --java-home.")
    try:
        runtime = JavaRuntime.discover(Path(found))
    except BeagleError as exc:
        raise CIError(f"Java at {found} is unusable: {exc}") from None
    if runtime.major < required:
        raise CIError(
            f"CI runs Java {required}; {found} is Java {runtime.major}. "
            "Set JAVA_HOME or pass --java-home."
        )


def _bash() -> tuple[str, str]:
    """A bash with GNU find on its PATH -- on Windows, Git's own, never WSL's launcher."""
    if os.name != "nt":
        found = shutil.which("bash")
        if found is None:
            raise CIError("bash is not on PATH")
        return found, str(Path(found).parent)
    git_root = Path(_git(Path.cwd(), "--exec-path").strip()).parents[2]
    bin_dir = git_root / "usr" / "bin"
    if not (bin_dir / "bash.exe").is_file():
        raise CIError(f"Git Bash not found under {git_root}")
    return str(bin_dir / "bash.exe"), str(bin_dir)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CIError(f"git {args[0]} failed: {detail}")
    return result.stdout.decode("utf-8", errors="surrogateescape")


def _git_paths(cwd: Path, *args: str) -> list[str]:
    return [p for p in _git(cwd, "ls-files", "-z", *args).split("\0") if p]


@contextmanager
def _scratch() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="genetics-ci-"))
    try:
        yield path
    finally:
        # Git writes its objects read-only, which Windows refuses to delete.
        for parent, _, files in os.walk(path):
            for name in files:
                os.chmod(os.path.join(parent, name), stat.S_IREAD | stat.S_IWRITE)
        shutil.rmtree(path, ignore_errors=True)
