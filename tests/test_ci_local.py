"""``genetics ci-local`` follows .github/workflows/ci.yml rather than restating it."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from genetics.testing import ci

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def test_the_real_workflow_is_fully_understood() -> None:
    """Every step of the test job is either setup or a command the local run executes."""
    flow = ci.workflow()
    steps = ci.plan(flow)
    commands = [step.command for step in steps]

    assert [c for c in commands if c[0] == "mypy"] == [
        ("mypy", "--platform", platform) for platform in ci.TYPE_PLATFORMS
    ]
    assert ("pytest", "-q") in commands
    tests = next(step for step in steps if step.command == ("pytest", "-q"))
    assert {"GENETICS_ROH_TEST_TOOLS", "GENETICS_BEAGLE_TEST_TOOLS"} <= set(tests.env)
    installs = [step for step in steps if step.command[:3] == ("genetics", "tools", "install")]
    assert installs and all(step.env == ("GENETICS_DATA_DIR",) for step in installs)

    runners, pythons = ci.matrix(flow)
    assert runners and pythons
    assert all(r.split("-")[0] in ci.RUNNER_PLATFORMS for r in runners)
    assert ci.java_major(flow) >= 11
    assert ci.installs_r(flow)
    assert "genotype-derived" in ci.no_data_script(flow)


def _flow(*steps: dict[str, Any]) -> dict[str, Any]:
    return {"jobs": {"test": {"steps": list(steps)}}}


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"name": "Deploy", "run": "make deploy"}, "make deploy"),
        ({"uses": "some/action@v1"}, "some/action"),
        ({"name": "New", "run": "uv run pytest", "env": {"GENETICS_NEW": "1"}}, "GENETICS_NEW"),
        ({"name": "Gated", "if": "runner.os == 'Linux'", "run": "uv run pytest"}, "runner.os"),
    ],
)
def test_an_unrecognised_step_fails_instead_of_being_skipped(
    step: dict[str, Any], message: str
) -> None:
    with pytest.raises(ci.CIError, match=message):
        ci.plan(_flow(step))


def test_setup_lines_and_comments_are_not_commands() -> None:
    flow = _flow(
        {"uses": "actions/checkout@v4"},
        {"name": "Install", "run": "uv venv --python 3.11\nuv pip install -e '.[dev]'"},
        {"uses": "r-lib/actions/setup-r@v2"},
        {"name": "HIBAG", "run": "Rscript -e \"BiocManager::install('HIBAG')\""},
        {"name": "Lint", "run": "# comment\nuv run ruff check .\n"},
        {"name": "Diagnostics", "if": "failure()", "run": "cat stderr.log"},
    )
    assert ci.plan(flow) == [ci.Step("Lint", ("ruff", "check", "."))]


def test_the_no_data_job_must_be_one_bash_script() -> None:
    flow = {"jobs": {"no-data-in-ci": {"steps": [{"run": "true"}, {"run": "true"}]}}}
    with pytest.raises(ci.CIError):
        ci.no_data_script(flow)


def test_the_developer_environment_does_not_leak_into_the_run() -> None:
    inherited = {
        "PATH": "bin",
        "GENETICS_PGS_TEST_TOOLS": "tools",
        "genetics_data_dir": "data",
        "VIRTUAL_ENV": "venv",
        "PYTHONPATH": "src",
    }
    assert ci.base_env(inherited, None) == {"PATH": "bin"}

    java = Path("jdk")
    env = ci.base_env({"PATH": "bin"}, java)
    assert env["JAVA_HOME"] == str(java)
    assert env["PATH"].split(os.pathsep) == [str(java / "bin"), "bin"]


def test_a_machine_without_r_is_named_as_a_gap(tmp_path: Path) -> None:
    assert ci.hibag_gap({"PATH": str(tmp_path)}) == "no Rscript is on PATH."


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@requires_git
def test_the_checkout_holds_exactly_what_a_push_would(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--quiet")
    (source / ".gitignore").write_text("ignored.txt\n")
    (source / "kept.txt").write_text("committed")
    (source / "deleted.txt").write_text("committed")
    _git(source, "add", "--all")
    _git(source, "commit", "--quiet", "--message", "initial")

    clean = tmp_path / "clean"
    assert ci.materialise(source, clean) is False
    assert (clean / "kept.txt").read_text() == "committed"

    (source / "kept.txt").write_text("edited")
    (source / "deleted.txt").unlink()
    (source / "new.txt").write_text("untracked")
    (source / "ignored.txt").write_text("a fetched reference")
    target = tmp_path / "target"
    assert ci.materialise(source, target) is True

    assert (target / "kept.txt").read_text() == "edited"
    assert not (target / "deleted.txt").exists()
    assert not (target / "ignored.txt").exists()
    assert _git(target, "status", "--porcelain") == ""
    assert _git(target, "show", "HEAD:new.txt") == "untracked"
