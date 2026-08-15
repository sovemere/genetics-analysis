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

#: Directories permitted to contain genotype-shaped rows, matched **one level deep
#: only**. Deliberately just one entry: synthetic fixtures are generated, never derived
#: from a real export (AGENTS.md 1.2).
#:
#: Depth matters. Expressed as an fnmatch glob this read ``tests/fixtures/synthetic/*``,
#: and fnmatch's ``*`` crosses ``/`` -- so an arbitrarily nested
#: ``tests/fixtures/synthetic/backup/<real export>`` was exempt from both the filename
#: rule and the content scan. Every layer failed together, because .gitignore's
#: ``!/tests/fixtures/synthetic/**`` un-ignored the whole subtree and the sealing test
#: used a non-recursive ``iterdir()``. Matching a single path segment closes it.
ALLOWLIST_DIRS: tuple[str, ...] = ("tests/fixtures/synthetic",)

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

BINARY_SUFFIXES = frozenset(
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


def _git_bytes(*args: str, cwd: Path | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        check=False,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace')}")
    return result.stdout


def staged_files(cwd: Path | None = None) -> list[str]:
    """Paths staged for commit (added, copied, modified, renamed).

    Uses ``-z`` and splits on NUL. Without it git quotes and octal-escapes any path
    containing non-ASCII characters, the subsequent ``git show`` fails on the mangled
    name, and the file is skipped without a word -- fail-open behaviour in a guard whose
    entire job is to fail closed.
    """
    raw = _git_bytes("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR", cwd=cwd)
    return [chunk.decode("utf-8", errors="surrogateescape") for chunk in raw.split(b"\0") if chunk]


def staged_content(path: str, cwd: Path | None = None) -> str | None:
    """Contents of ``path`` as staged. None only when the file is deliberately skipped."""
    if Path(path).suffix.lower() in BINARY_SUFFIXES:
        return None
    raw = _git_bytes("show", f":{path}", cwd=cwd)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # Undecodable bytes: treat as binary rather than as clean.
        return None


def is_allowlisted(path: str) -> bool:
    """True if ``path`` may legitimately contain genotype-shaped content.

    Matches files sitting **directly** in an allowlisted directory. Nested paths are not
    exempt: a subdirectory is exactly where a real export would be tucked away.
    """
    normalised = path.replace("\\", "/").lower().lstrip("./")
    for directory in ALLOWLIST_DIRS:
        prefix = directory.lower() + "/"
        if normalised.startswith(prefix):
            remainder = normalised[len(prefix) :]
            if remainder and "/" not in remainder:
                return True
    return False


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

        try:
            content = staged_content(path, cwd)
        except RuntimeError as exc:
            # Could not read what is about to be committed. Refuse rather than assume
            # it is clean -- an unreadable file is the one we know least about.
            findings.append(
                Finding(
                    path=path,
                    kind="unreadable staged file",
                    detail=f"could not read the staged blob to scan it ({exc.__class__.__name__})",
                )
            )
            continue

        if content is None:
            continue

        hits = find_genotypes(content)
        if hits:
            names = sorted({hit.pattern for hit in hits})
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
