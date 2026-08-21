"""Where the app writes (roadmap M0.3).

AGENTS.md 1.5 requires analysis output to land outside the repository by default, so that
a careless ``git add -A`` cannot reach a run bundle. Gitignore rules are the second line
of defence, not the first -- both are asserted here.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from genetics.paths import (
    UnsafeDataDirError,
    app_write_paths,
    cache_dir,
    is_inside_repo,
    reference_lock,
    reference_manifest,
    references_dir,
    repo_root,
    runs_dir,
    user_data_dir,
)

pytestmark = pytest.mark.privacy

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def test_genotype_derived_output_defaults_outside_the_repo() -> None:
    """Runs and caches hold genotype data; they must not default into the checkout."""
    for path in (user_data_dir(), runs_dir(), cache_dir()):
        assert not is_inside_repo(path), f"{path} defaults inside the repo"


def test_reference_data_lives_in_the_repo_tree_but_ignored() -> None:
    """References are bulky and licence-encumbered, not personal.

    Keeping them beside the committed manifest is deliberate; the concern is size and
    redistribution, not privacy (AGENTS.md 5.5).
    """
    assert is_inside_repo(references_dir())


def test_data_dir_override_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Large panels often need another drive; the override must not break the guarantee."""
    monkeypatch.setenv("GENETICS_DATA_DIR", str(repo_root().parent / "elsewhere"))
    assert not is_inside_repo(user_data_dir())
    assert not is_inside_repo(runs_dir())


@pytest.mark.parametrize(
    "relative",
    ["mydata", "data/mine", ".", "tests/scratch", "data/references/../../runs"],
)
def test_data_dir_override_inside_the_repo_is_rejected(
    monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    """Pointing the data dir at the project is plausible, and would leak.

    ``.gitignore`` only covers the paths we declare. A run bundle under an arbitrary
    in-repo directory is caught unevenly -- ``x.run.json`` matches a pattern but
    ``run_001/cards.json`` does not -- so the override must fail loudly rather than
    quietly relocating genotypes into the checkout.
    """
    monkeypatch.setenv("GENETICS_DATA_DIR", str(repo_root() / relative))
    with pytest.raises(UnsafeDataDirError):
        user_data_dir()


def test_rejection_propagates_to_every_derived_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(repo_root() / "mydata"))
    for factory in (runs_dir, cache_dir, app_write_paths):
        with pytest.raises(UnsafeDataDirError):
            factory()


@requires_git
def test_gitignore_covers_every_writable_path() -> None:
    """Each declared output path is ignored, or explicitly meant to be tracked."""
    root = repo_root()
    failures: list[str] = []

    for label, path, must_ignore in app_write_paths():
        if not is_inside_repo(path):
            continue  # outside the repo entirely; git cannot see it

        rel = str(path.relative_to(root)).replace("\\", "/")
        probe = f"{rel}/probe.tmp" if must_ignore else rel

        ignored = (
            subprocess.run(
                ["git", "check-ignore", "-q", probe],
                cwd=root,
                check=False,
            ).returncode
            == 0
        )

        if must_ignore and not ignored:
            failures.append(f"{label}: {probe} is NOT ignored but must be")
        if not must_ignore and ignored:
            failures.append(f"{label}: {probe} IS ignored but must stay tracked")

    assert not failures, "\n".join(failures)


@requires_git
def test_every_plink_artifact_name_is_ignored() -> None:
    """The M5.2 conversion's outputs, by name rather than by directory.

    ``test_gitignore_covers_every_writable_path`` asks about the *locations* the app
    writes to, which is the first line of defence and the one that holds when the workspace
    is where it should be. This asks the complementary question: if one of these files is
    copied into the checkout by hand -- to look at a pgen, to diff two harmonized VCFs --
    is it still ignored? The knowledge-pack allowlist has already re-admitted a run bundle
    once (see the ``.gitignore`` note above ``/knowledge/**/*.run.json``), and a string
    search of the file cannot see precedence, negation or ordering. Only git can.

    ``<stem>-temporary.pvar.zst`` is in the list because it is the one PLINK writes that
    the ``*.pvar`` rule does not match, and because it survives a crash.
    """
    root = repo_root()
    artifacts = [
        "sample.harmonized.vcf",
        "sample.pgen",
        "sample.pvar",
        "sample.psam",
        "sample.log",
        "sample-temporary.pgen",
        "sample-temporary.pvar.zst",
        "sample-temporary.psam",
    ]

    tracked = [
        name
        for name in artifacts
        if subprocess.run(["git", "check-ignore", "-q", name], cwd=root, check=False).returncode
        != 0
    ]

    assert not tracked, f"these PLINK outputs would be committable: {tracked}"


@requires_git
def test_manifest_and_lock_stay_trackable() -> None:
    """Reproducible builds depend on these being committed alongside ignored payloads."""
    root = repo_root()
    for path in (reference_manifest(), reference_lock()):
        rel = str(path.relative_to(root)).replace("\\", "/")
        result = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=root,
            check=False,
        )
        assert result.returncode != 0, f"{rel} must remain trackable"


def test_every_writable_path_is_declared() -> None:
    """app_write_paths() is what the gitignore check iterates.

    A new output location that skips this registry is a location nothing verifies.
    """
    declared = {path for _, path, _ in app_write_paths()}
    for path in (user_data_dir(), runs_dir(), cache_dir(), references_dir()):
        assert path in declared, f"{path} is missing from app_write_paths()"
