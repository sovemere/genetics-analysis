"""Staged-change inspection for the pre-commit hook.

``.gitignore`` stops files whose *name* gives them away. This catches the other case: a
legitimately-tracked file -- a doc, a test, a module -- that has acquired genotype content
inside it. That is the failure mode that actually happens, because nothing about the
filename looks wrong.

Runs against the staged index rather than the working tree, so it sees exactly what the
commit would contain.
"""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from pathlib import Path

from genetics.privacy import find_genotypes

#: Paths permitted to contain genotype-shaped rows. Deliberately just one entry:
#: synthetic fixtures are generated, never derived from a real export (AGENTS.md 1.2).
CONTENT_ALLOWLIST: tuple[str, ...] = ("tests/fixtures/synthetic/*",)

#: Filenames that should never be tracked regardless of content. A subset of
#: ``.gitignore`` re-checked here, because a hand-written ``git add -f`` bypasses it.
FORBIDDEN_NAMES: tuple[str, ...] = (
    "AncestryDNA*.txt",
    "genome_*.txt",
    "*23andMe*.txt",
    "*MyHeritage*.csv",
    "*.vcf",
    "*.vcf.gz",
    "*.bcf",
    "*.bed",
    "*.bim",
    "*.fam",
    "*.pgen",
    "*.pvar",
    "*.psam",
    "*.eigenvec",
    "*.eigenval",
    "*.sscore",
    "*.profile",
    "*.grm",
    "*.king",
    "*.kin0",
    "*.genome",
    "*.Q",
    "*.P",
    "*.run.json",
    "*.analysis.json",
    "*.dose",
    "*.dosage",
    "*.bgen",
    "*.haps",
    "*.bam",
    "*.cram",
    "*.fastq",
    "*.fastq.gz",
)

_BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".exe", ".dll", ".so", ".jar"}
)


@dataclass(frozen=True)
class Finding:
    """One reason to block a commit."""

    path: str
    kind: str
    detail: str

    def render(self) -> str:
        return f"  {self.path}\n      {self.kind}: {self.detail}"


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def staged_files(cwd: Path | None = None) -> list[str]:
    """Paths staged for commit (added, copied, modified, renamed)."""
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", cwd=cwd)
    return [line.strip() for line in out.splitlines() if line.strip()]


def staged_content(path: str, cwd: Path | None = None) -> str | None:
    """Contents of ``path`` as staged. None if it is binary or unreadable as text."""
    if Path(path).suffix.lower() in _BINARY_SUFFIXES:
        return None
    try:
        return _git("show", f":{path}", cwd=cwd)
    except (RuntimeError, UnicodeDecodeError):
        return None


def is_allowlisted(path: str) -> bool:
    """True if ``path`` may legitimately contain genotype-shaped content."""
    normalised = path.replace("\\", "/").lower()
    return any(fnmatch.fnmatchcase(normalised, pattern.lower()) for pattern in CONTENT_ALLOWLIST)


def has_forbidden_name(path: str) -> str | None:
    """Return the pattern matched, if the filename is one that must never be tracked.

    Matching is explicitly case-insensitive on every platform. Plain ``fnmatch.fnmatch``
    normcases via the OS, so it folds case on Windows but not on Linux -- a check that
    behaves differently per platform is worse than no check, because it passes CI on one
    runner and blocks on another.

    Allowlisted paths are exempt: a generated fixture is legitimate whatever it is called.
    That exemption is safe only because the allowlist is a single generated directory,
    which ``test_synthetic_dir_holds_only_known_fixtures`` keeps sealed.
    """
    if is_allowlisted(path):
        return None

    name = Path(path).name.lower()
    normalised = path.replace("\\", "/").lower()
    for pattern in FORBIDDEN_NAMES:
        lowered = pattern.lower()
        if fnmatch.fnmatchcase(name, lowered) or fnmatch.fnmatchcase(normalised, lowered):
            return pattern
    return None


def check_staged(cwd: Path | None = None) -> list[Finding]:
    """Inspect the staged index. Empty list means the commit is clear to proceed."""
    findings: list[Finding] = []

    for path in staged_files(cwd):
        pattern = has_forbidden_name(path)
        if pattern is not None:
            findings.append(
                Finding(
                    path=path,
                    kind="forbidden filename",
                    detail=f"matches {pattern!r}; genotype-derived files are never tracked",
                )
            )
            continue

        if is_allowlisted(path):
            continue

        content = staged_content(path, cwd)
        if content is None:
            continue

        hits = find_genotypes(content)
        if hits:
            names = sorted({name for name, _ in hits})
            findings.append(
                Finding(
                    path=path,
                    kind="genotype content",
                    detail=(
                        f"{len(hits)} match(es) for {', '.join(names)}. "
                        "If this is illustrative, invent the values; if it is test data, "
                        "generate it with `genetics fixtures`."
                    ),
                )
            )

    return findings
