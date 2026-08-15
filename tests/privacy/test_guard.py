"""Staged-index scanning (roadmap M0.3 / M0.4).

Exercised against throwaway git repositories so the assertions are about real staged
content rather than a mocked approximation of it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from genetics.guard import check_staged, has_forbidden_name, is_allowlisted

pytestmark = pytest.mark.privacy

requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")

TAB = "\t"


def _row(
    rsid: str = "rs900000001", chrom: str = "1", pos: str = "100001", a1: str = "G", a2: str = "G"
) -> str:
    """Assemble a genotype row at runtime; see test_leak_detection for why."""
    return TAB.join([rsid, chrom, pos, a1, a2])


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    return tmp_path


def _stage(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "-f", rel], cwd=repo, check=True)


# ---------------------------------------------------------------------------
# Name rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "AncestryDNA.txt",
        "AncestryDNA_2024.txt",
        "genome_alice.txt",
        "data/sample.vcf",
        "out.eigenvec",
        "scores.sscore",
        "cohort.bim",
        "results/x.run.json",
    ],
)
def test_forbidden_names_are_caught(path: str) -> None:
    assert has_forbidden_name(path) is not None


@pytest.mark.parametrize(
    "path",
    ["README.md", "src/genetics/paths.py", "knowledge/traits/earwax.yaml", "pyproject.toml"],
)
def test_ordinary_names_pass(path: str) -> None:
    assert has_forbidden_name(path) is None


# ---------------------------------------------------------------------------
# Staged content
# ---------------------------------------------------------------------------


@requires_git
def test_clean_staging_produces_no_findings(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage(repo, "notes.md", "Nothing but prose about rs17822931 and earwax.\n")
    assert check_staged(cwd=repo) == []


@requires_git
def test_genotype_in_a_markdown_file_is_caught(tmp_path: Path) -> None:
    """The real failure mode: a legitimately-tracked file with a row pasted into it."""
    repo = _init_repo(tmp_path)
    _stage(repo, "docs/format.md", f"The layout looks like:\n\n{_row()}\n")

    findings = check_staged(cwd=repo)
    assert len(findings) == 1
    assert findings[0].path == "docs/format.md"
    assert findings[0].kind == "genotype content"


@requires_git
def test_genotype_in_source_code_is_caught(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage(repo, "src/debug.py", f'SAMPLE = """\n{_row(a1="A", a2="C")}\n"""\n')
    assert [f.path for f in check_staged(cwd=repo)] == ["src/debug.py"]


@requires_git
def test_forbidden_filename_is_caught_even_when_force_added(tmp_path: Path) -> None:
    """`git add -f` defeats .gitignore; it must not defeat this."""
    repo = _init_repo(tmp_path)
    (repo / ".gitignore").write_text("AncestryDNA*.txt\n", encoding="utf-8")
    _stage(repo, "AncestryDNA.txt", f"{_row()}\n")

    findings = check_staged(cwd=repo)
    assert any(f.kind == "forbidden filename" for f in findings)


@requires_git
def test_synthetic_fixtures_are_allowed_through(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _stage(repo, "tests/fixtures/synthetic/ancestry_v2_male.txt", f"{_row()}\n{_row()}\n")
    assert check_staged(cwd=repo) == []


@requires_git
def test_a_fixture_outside_the_synthetic_dir_is_not_allowed(tmp_path: Path) -> None:
    """Trimming a real export into tests/fixtures/ is the exact move this blocks."""
    repo = _init_repo(tmp_path)
    _stage(repo, "tests/fixtures/sample.txt", f"{_row()}\n")
    assert [f.path for f in check_staged(cwd=repo)] == ["tests/fixtures/sample.txt"]


@requires_git
def test_unstaged_working_tree_changes_are_ignored(tmp_path: Path) -> None:
    """The hook judges the commit, not the working directory."""
    repo = _init_repo(tmp_path)
    _stage(repo, "clean.md", "fine\n")
    (repo / "dirty.md").write_text(f"{_row()}\n", encoding="utf-8", newline="\n")
    assert check_staged(cwd=repo) == []


@requires_git
def test_findings_render_without_echoing_the_genotype(tmp_path: Path) -> None:
    """The hook prints these to a terminal, and terminals get screenshotted."""
    from genetics.privacy import looks_like_genotype

    repo = _init_repo(tmp_path)
    _stage(repo, "docs/format.md", f"{_row()}\n")

    for finding in check_staged(cwd=repo):
        assert not looks_like_genotype(finding.render())


def test_allowlist_pattern_matches_windows_separators() -> None:
    assert is_allowlisted("tests\\fixtures\\synthetic\\ancestry_v2_male.txt")


@pytest.mark.parametrize(
    "path",
    [
        "tests/fixtures/synthetic/backup/AncestryDNA.txt",
        "tests/fixtures/synthetic/old/sample.txt",
        "tests/fixtures/synthetic/a/b/c.txt",
    ],
)
def test_allowlist_does_not_cross_directory_boundaries(path: str) -> None:
    """The allowlist was an fnmatch glob, and fnmatch's `*` crosses `/`.

    That exempted arbitrarily-nested paths from both the name rule and the content
    scan -- a subdirectory being exactly where someone would tuck a real export.
    """
    assert not is_allowlisted(path), f"{path} must not be allowlisted"


@requires_git
def test_nested_export_under_the_fixture_dir_is_caught(tmp_path: Path) -> None:
    """End-to-end version of the hole: it must now produce a Finding."""
    repo = _init_repo(tmp_path)
    _stage(repo, "tests/fixtures/synthetic/backup/AncestryDNA.txt", f"{_row()}\n" * 50)

    findings = check_staged(cwd=repo)
    assert findings, "a nested export under the fixture dir must be blocked"


@requires_git
def test_non_ascii_path_is_scanned_not_skipped(tmp_path: Path) -> None:
    """Without -z git quotes and octal-escapes the path, `git show` fails on the mangled
    name, and the file was skipped silently -- fail-open in a fail-closed guard."""
    repo = _init_repo(tmp_path)
    _stage(repo, "nötes.md", f"{_row()}\n")

    findings = check_staged(cwd=repo)
    assert findings, "a genotype in a non-ASCII path must still be caught"


@requires_git
def test_escaped_genotype_in_source_is_caught(tmp_path: Path) -> None:
    """The idiomatic way to write a row in Python is with escaped tabs, not real ones."""
    repo = _init_repo(tmp_path)
    literal = "rs900000001" + r"\t" + "1" + r"\t" + "100001" + r"\t" + "G" + r"\t" + "G"
    _stage(repo, "src/debug.py", f'SAMPLE = "{literal}"\n')

    assert [f.path for f in check_staged(cwd=repo)] == ["src/debug.py"]


@pytest.mark.parametrize(
    "path",
    [
        "ancestrydna.txt",
        "ANCESTRYDNA.TXT",
        "my_23ANDME_export.txt",
        "sample.VCF",
        "OUT.EIGENVEC",
    ],
)
def test_name_matching_is_case_insensitive_on_every_platform(path: str) -> None:
    """Regression: plain fnmatch folds case on Windows but not Linux.

    A platform-dependent guard is worse than none -- it passes on one CI runner and
    blocks on another, and the resulting flakiness gets the check disabled.
    """
    assert has_forbidden_name(path) is not None, f"{path} should be forbidden"


def test_allowlisted_paths_are_exempt_from_name_rules() -> None:
    """A generated fixture is legitimate whatever it is called."""
    assert has_forbidden_name("tests/fixtures/synthetic/other_vendor_layout.txt") is None
    assert has_forbidden_name("tests/fixtures/synthetic/anything.vcf") is None
    # ...but only inside that one directory.
    assert has_forbidden_name("tests/fixtures/anything.vcf") is not None
