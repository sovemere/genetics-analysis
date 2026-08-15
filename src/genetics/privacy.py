"""Leak detection and redaction.

The threat this guards against is mundane: a genotype reaching a public repo not as a
DNA file, but as an illustration. A row pasted into documentation, a debug ``print`` of a
parsed record, an exception message that helpfully includes the offending line, a test
fixture built by trimming a real export. Each looks harmless in isolation and none of
them is caught by ``.gitignore``, because the file they land in is a legitimate one.

This module gives the pre-commit hook and the privacy suite something concrete to check,
and gives genotype-bearing classes a ``__repr__`` that cannot betray them.

Calibration note: patterns here deliberately favour precision over recall. A scanner that
cries wolf gets bypassed, and a bypassed scanner protects nothing. It matches the *row
formats* that carry genotypes rather than trying to spot any pair of letters.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Final

_ALLELE = r"[ACGTID0]"

# Note on the comments below: they describe the shapes in words rather than showing a
# specimen row. A literal example here would be matched by this module's own patterns --
# which is the point of the exercise, not a limitation of it.

#: A vendor genotype row in the AncestryDNA five-column layout: an rsID, a chromosome
#: code, a position, then two single-character alleles, whitespace-separated.
ANCESTRY_ROW: Final = re.compile(
    rf"^\s*rs\d+[ \t]+(?:\d{{1,2}}|[XYM]|MT|PAR)[ \t]+\d+[ \t]+{_ALLELE}[ \t]+{_ALLELE}\s*$",
    re.MULTILINE,
)

#: A 23andMe-style four-column row: as above, but with the two alleles merged into a
#: single genotype field (or a double-dash for a no-call).
MERGED_GENOTYPE_ROW: Final = re.compile(
    rf"^\s*rs\d+[ \t]+(?:\d{{1,2}}|[XYM]|MT)[ \t]+\d+[ \t]+(?:{_ALLELE}{{1,2}}|--)\s*$",
    re.MULTILINE,
)

#: An rsID with a genotype attached inline by a colon or equals sign, with the two
#: alleles optionally separated by a slash or pipe. The prose form that shows up in
#: notes, commit messages and issue comments.
INLINE_GENOTYPE: Final = re.compile(
    rf"\brs\d+\b\s*[:=]\s*['\"]?{_ALLELE}\s*[/|]?\s*{_ALLELE}\b",
)

PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("ancestry genotype row", ANCESTRY_ROW),
    ("merged genotype row", MERGED_GENOTYPE_ROW),
    ("inline rsID genotype", INLINE_GENOTYPE),
)


def find_genotypes(text: str) -> list[tuple[str, str]]:
    """Return ``(pattern name, matched text)`` for every genotype-looking span.

    Empty list means the text is clean by these rules -- which is a statement about the
    known formats, not a proof of safety.
    """
    hits: list[tuple[str, str]] = []
    for name, pattern in PATTERNS:
        hits.extend((name, match.group(0).strip()) for match in pattern.finditer(text))
    return hits


def looks_like_genotype(text: str) -> bool:
    """True if ``text`` contains anything resembling a genotype record."""
    return any(pattern.search(text) for _, pattern in PATTERNS)


def redact(text: str) -> str:
    """Replace genotype-looking spans with a marker, preserving surrounding context."""
    result = text
    for _, pattern in PATTERNS:
        result = pattern.sub("<redacted genotype>", result)
    return result


class NoGenotypeRepr:
    """Mixin giving a class a ``__repr__`` that reports shape, never content.

    Any class holding genotypes must inherit this. The default dataclass and object
    ``__repr__`` will happily print allele values into a traceback, a log line, or a
    debugger session that someone later pastes into an issue.

    Subclasses may set ``_repr_fields`` to name attributes that are safe to show --
    counts, versions, flags. Anything not listed is omitted entirely rather than
    summarised, because summarising is how allele frequencies leak.
    """

    _repr_fields: tuple[str, ...] = ()

    def __repr__(self) -> str:
        shown: list[str] = []
        for name in self._repr_fields:
            value = getattr(self, name, None)
            rendered = repr(value)
            if looks_like_genotype(rendered):
                rendered = "<redacted>"
            shown.append(f"{name}={rendered}")
        body = ", ".join(shown)
        return f"{type(self).__name__}({body})" if body else f"<{type(self).__name__}>"


def assert_no_genotype(text: str, *, context: str = "") -> None:
    """Raise if ``text`` contains genotype-looking content.

    Use at every boundary where data leaves the process: log records, error messages,
    outbound web queries (AGENTS.md 1.3), and anything written to a tracked file.
    """
    hits = find_genotypes(text)
    if hits:
        where = f" in {context}" if context else ""
        names = ", ".join(sorted({name for name, _ in hits}))
        raise GenotypeLeakError(
            f"Refusing to emit genotype-like content{where}: matched {names}. "
            f"Redact it or route it through genetics.privacy.redact()."
        )


class GenotypeLeakError(RuntimeError):
    """Raised when genotype-like content reaches somewhere it must not.

    Deliberately does not include the offending text -- an exception message is one of
    the places this content most easily escapes to.
    """


def scan_paths(paths: Iterable[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Scan ``(label, content)`` pairs. Returns only the entries with hits."""
    findings: dict[str, list[tuple[str, str]]] = {}
    for label, content in paths:
        hits = find_genotypes(content)
        if hits:
            findings[label] = hits
    return findings


def __getattr__(name: str) -> Any:  # pragma: no cover - guards a plausible mistake
    if name in {"genotype", "genotypes", "alleles"}:
        raise AttributeError(
            f"genetics.privacy has no {name!r}; this module detects leaks, it does not hold data."
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
