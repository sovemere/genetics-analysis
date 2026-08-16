"""Repository-level leak checks (roadmap M0.3).

These run against what git actually tracks, not what the working tree happens to hold.
The content scan is the one that earns its keep: it is the check that would have caught
two real genotype rows pasted into AGENTS.md as a format illustration.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from genetics.guard import BINARY_SUFFIXES, has_forbidden_name, is_allowlisted
from genetics.paths import repo_root
from genetics.privacy import find_genotypes

pytestmark = pytest.mark.privacy


def _git_available() -> bool:
    return shutil.which("git") is not None


requires_git = pytest.mark.skipif(not _git_available(), reason="git not on PATH")


def _tracked_files() -> list[str]:
    """Tracked paths, NUL-separated so non-ASCII names are not quoted and escaped."""
    raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root(),
        capture_output=True,
        check=True,
    ).stdout
    return [chunk.decode("utf-8", errors="surrogateescape") for chunk in raw.split(b"\0") if chunk]


def _committed_blob(rel: str) -> bytes | None:
    """Bytes of ``rel`` as git stores it, not as the working tree happens to hold it."""
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=repo_root(),
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


@requires_git
def test_no_tracked_file_has_a_forbidden_name() -> None:
    offenders = [(p, has_forbidden_name(p)) for p in _tracked_files() if has_forbidden_name(p)]
    assert not offenders, f"genotype-derived files are tracked: {offenders}"


@requires_git
def test_no_tracked_file_contains_genotype_content() -> None:
    """The check that catches illustrations, debug output and trimmed fixtures.

    Synthetic fixtures are the sole allowlisted location -- they are generated from a
    seeded RNG and never derived from a real export (AGENTS.md 1.2).
    """
    offenders: list[str] = []

    for rel in _tracked_files():
        if is_allowlisted(rel):
            continue
        if Path(rel).suffix.lower() in BINARY_SUFFIXES:
            continue

        # Read what git stores, not what the filesystem holds. Taking the file list from
        # git and then the bytes from disk judges the wrong thing in both directions: a
        # leak already committed passes once the working copy is cleaned, and an
        # uncommitted local edit fails CI for content that was never pushed.
        raw = _committed_blob(rel)
        if raw is None:
            continue  # staged but never committed; the pre-commit guard covers that
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        hits = find_genotypes(content)
        if hits:
            names = sorted({hit.pattern for hit in hits})
            offenders.append(f"{rel} ({len(hits)} hits: {', '.join(names)})")

    assert not offenders, (
        "Genotype-shaped content in tracked files:\n  "
        + "\n  ".join(offenders)
        + "\nIf illustrative, invent the values or avoid real tabs; if test data, "
        "generate it with `genetics fixtures`."
    )


@requires_git
def test_real_export_is_ignored_if_present() -> None:
    """A raw export sitting in the working tree must be invisible to git."""
    root = repo_root()
    exports = list(root.glob("AncestryDNA*.txt")) + list(root.glob("genome_*.txt"))
    if not exports:
        pytest.skip("no raw export in the working tree")

    for export in exports:
        result = subprocess.run(
            ["git", "check-ignore", "-q", export.name],
            cwd=root,
            check=False,
        )
        assert result.returncode == 0, f"{export.name} is NOT gitignored"


@requires_git
def test_synthetic_fixtures_remain_trackable() -> None:
    """The allowlist must actually work, or the test suite has no inputs."""
    root = repo_root()
    fixture = root / "tests" / "fixtures" / "synthetic" / "ancestry_v2_male.txt"
    if not fixture.exists():
        pytest.skip("fixtures not generated")

    result = subprocess.run(
        ["git", "check-ignore", "-q", str(fixture.relative_to(root)).replace("\\", "/")],
        cwd=root,
        check=False,
    )
    assert result.returncode != 0, "synthetic fixtures must not be gitignored"


def test_synthetic_dir_holds_only_known_fixtures() -> None:
    """Seal the one allowlisted directory.

    Everything under tests/fixtures/synthetic/ is exempt from both the content scan and
    the filename rules, so it is the single place a real export could be smuggled in.
    The exemption is only safe while the directory contains exactly what the generator
    produces and nothing else.
    """
    from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR, FIXTURES

    if not DEFAULT_FIXTURE_DIR.exists():
        pytest.skip("fixtures not generated")

    expected = {spec.name for spec in FIXTURES} | {"MANIFEST.json"}

    # rglob, not iterdir. A non-recursive scan filtered by is_file() cannot see a
    # subdirectory at all, so `synthetic/backup/<real export>` was invisible to the
    # very test that guard.py cited as its reason for exempting the directory.
    actual = {
        str(p.relative_to(DEFAULT_FIXTURE_DIR)).replace("\\", "/")
        for p in DEFAULT_FIXTURE_DIR.rglob("*")
        if p.is_file()
    }

    unexpected = actual - expected
    assert not unexpected, (
        f"unrecognised entries in the allowlisted fixture directory: {sorted(unexpected)}. "
        "Only generator output belongs here, and only at the top level."
    )


def test_no_subdirectories_under_the_allowlisted_fixture_dir() -> None:
    """Nesting is how the allowlist gets abused; there is no legitimate use for it."""
    from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR

    if not DEFAULT_FIXTURE_DIR.exists():
        pytest.skip("fixtures not generated")

    subdirs = [p.name for p in DEFAULT_FIXTURE_DIR.iterdir() if p.is_dir()]
    assert not subdirs, f"subdirectories under the fixture allowlist: {subdirs}"


def test_allowlist_is_narrow() -> None:
    """Only synthetic fixtures may hold genotype-shaped content.

    Widening this is how the content scan quietly stops protecting anything.
    """
    assert is_allowlisted("tests/fixtures/synthetic/ancestry_v2_male.txt")
    for path in (
        "AGENTS.md",
        "README.md",
        "src/genetics/ingest/ancestry.py",
        "tests/test_fixtures.py",
        "tests/fixtures/real_sample.txt",
        "docs/example.md",
    ):
        assert not is_allowlisted(path), f"{path} must not be allowlisted"


def test_gitignore_and_gitattributes_are_tracked() -> None:
    root = repo_root()
    assert (root / ".gitignore").exists()
    assert (root / ".gitattributes").exists(), "line-ending pinning is a correctness requirement"


def test_pre_commit_hook_exists_and_is_wired() -> None:
    hook = repo_root() / ".githooks" / "pre-commit"
    assert hook.exists(), "tracked pre-commit hook is missing"
    body = hook.read_text(encoding="utf-8")
    assert "check-staged" in body
    # Asserts the *command*, not the path. This read `"tests/privacy" in body` until the
    # hook was changed to select by marker -- at which point the only remaining occurrence
    # of that path was inside an explanatory comment, so the check passed while verifying
    # nothing. Deleting the pytest line entirely would not have failed it.
    assert "-m privacy" in body, "the hook must run the privacy suite by marker"
    assert "fixtures --check" in body, "the hook must verify fixtures before the push"
    assert "--no-verify" in body, "the hook must state that bypassing it is not acceptable"


@requires_git
def test_pre_commit_hook_is_executable_in_the_index() -> None:
    """Mode 100644 makes the whole guard a silent no-op on Linux and macOS.

    Git finds the hook, sees it is not executable, and skips it -- while
    ``genetics install-hooks`` reports success and the developer believes they are
    covered. The working tree's permission bits are irrelevant on Windows; the index
    mode is what every clone gets.
    """
    out = subprocess.run(
        ["git", "ls-files", "-s", ".githooks/pre-commit"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    if not out:
        pytest.skip("hook not tracked yet")
    mode = out.split()[0]
    assert mode == "100755", (
        f"hook is committed with mode {mode}; git will not execute it on Linux/macOS. "
        "Fix with: git update-index --chmod=+x .githooks/pre-commit"
    )
