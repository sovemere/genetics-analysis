"""Leak detection and redaction.

The threat this guards against is mundane: a genotype reaching a public repo not as a
DNA file, but as an illustration. A row pasted into documentation, a debug ``print`` of a
parsed record, an exception message that helpfully includes the offending line, a test
fixture built by trimming a real export. Each looks harmless in isolation and none of
them is caught by ``.gitignore``, because the file they land in is a legitimate one.

This module gives the pre-commit hook and the privacy suite something concrete to check,
and gives genotype-bearing classes a ``__repr__`` that cannot betray them.

Calibration note: patterns favour precision over recall. A scanner that cries wolf gets
bypassed, and a bypassed scanner protects nothing. They match the *shapes* that carry
genotypes rather than trying to spot any pair of letters.

Separator forms, and why there are three
----------------------------------------
A genotype row reaches a file in more than one shape, and an early version of this module
only recognised the first:

* **Literal** -- real tab or space separators, as in the export itself or a pasted block.
* **Escaped** -- ``\\t`` as a two-character sequence, which is what appears inside a
  Python string literal and in anything that has been through ``repr()``. Tracebacks,
  log lines and debug prints all arrive in this form. Matching only literal tabs meant
  the module was blind to the exact threats its own docstring names.
* **Ruled** -- a vertical bar between cells: the ASCII ``|`` of a markdown table, and the
  box-drawing characters a rendered dataframe uses. Added in M1, when the first
  genotype-bearing ``polars.DataFrame`` appeared: its ``__repr__`` lays a row out with
  ``U+2506`` separators, so it printed rsIDs and genotypes in plain sight while matching
  none of the whitespace-separated patterns. Pasting a query result into a doc, an
  issue, or a notebook cell is a leak route, and a markdown table is the same shape.
* **Keyed** -- ``rsid=..., a1=..., a2=...``, the shape a dataclass ``repr`` produces.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar, Final

_ALLELE = r"[ACGTID0]"

_RULE = "|│┆║┊"
"""Vertical rules that separate cells in a rendered table: the ASCII pipe of markdown,
and the box-drawing characters Polars, Rich and friends emit."""

# A separator may be real whitespace, the escaped form that survives repr(), or a table
# rule. The rule alternative comes first so it consumes the padding spaces around it --
# ordered the other way, `[ \t]+` would match the space and leave the bar unconsumed.
_SEP = rf"(?:[ \t]*[{re.escape(_RULE)}][ \t]*|[ \t]+|(?:\\t)+|(?:\\s)+)"

_CHROM = r"(?:\d{1,2}|[XYM]|MT|PAR)"

_RSID = r"(?:rs|i)\d+"
"""23andMe uses ``i``-prefixed identifiers for tens of thousands of custom probes.
The AncestryDNA V2 layout is all ``rs``, but the plug-and-play requirement (AGENTS.md
section 2) means the other-vendor layout must be covered too."""


# Note: the comments below describe shapes in words rather than showing a specimen row.
# A literal example here would be matched by this module's own patterns -- which is the
# point of the exercise, not a limitation of it.

#: A five-column vendor row: identifier, chromosome code, position, then two
#: single-character alleles. Line-anchored, for rows sitting in a file.
ANCESTRY_ROW: Final = re.compile(
    rf"^\s*{_RSID}[ \t]+{_CHROM}[ \t]+\d+[ \t]+{_ALLELE}[ \t]+{_ALLELE}\s*$",
    re.MULTILINE,
)

#: A four-column row with the two alleles merged into one genotype field (or a
#: double-dash no-call). Line-anchored.
MERGED_GENOTYPE_ROW: Final = re.compile(
    rf"^\s*{_RSID}[ \t]+{_CHROM}[ \t]+\d+[ \t]+(?:{_ALLELE}{{1,2}}|--)\s*$",
    re.MULTILINE,
)

#: The same row shapes with escaped separators, deliberately *not* line-anchored: this
#: form appears mid-line, inside a string literal or a repr.
ESCAPED_ROW: Final = re.compile(
    rf"{_RSID}{_SEP}{_CHROM}{_SEP}\d+{_SEP}{_ALLELE}(?:{_SEP}{_ALLELE})?",
)

#: An identifier with a genotype attached inline by a colon or equals sign. The prose
#: form that turns up in notes, commit messages and issue comments.
INLINE_GENOTYPE: Final = re.compile(
    rf"\b{_RSID}\b\s*[:=]\s*['\"]?{_ALLELE}\s*[/|]?\s*{_ALLELE}\b",
)

#: Keyed fields, as produced by a dataclass ``repr``: an rsid-like key followed within a
#: short window by allele keys.
KEYED_FIELDS: Final = re.compile(
    rf"\brsid\s*[=:]\s*['\"]?{_RSID}['\"]?"
    rf".{{0,300}}?"
    rf"\b(?:a|allele)1\s*[=:]\s*['\"]?{_ALLELE}['\"]?",
    re.DOTALL,
)

PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("ancestry genotype row", ANCESTRY_ROW),
    ("merged genotype row", MERGED_GENOTYPE_ROW),
    ("escaped genotype row", ESCAPED_ROW),
    ("inline identifier genotype", INLINE_GENOTYPE),
    ("keyed genotype fields", KEYED_FIELDS),
)


@dataclass(frozen=True)
class Hit:
    """One genotype-shaped span.

    Carries the *location*, never the text. An earlier version returned the matched
    string, which meant any caller doing the obvious thing -- printing the findings,
    logging them, or letting pytest render them on failure -- wrote the genotype to a
    terminal or a CI log. Callers in this repo only ever wanted the pattern name and a
    count, so the text had no consumer justifying the risk.
    """

    pattern: str
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


def find_genotypes(text: str) -> list[Hit]:
    """Return a :class:`Hit` for every genotype-looking span.

    Empty list means the text is clean by these rules -- a statement about the known
    formats, not a proof of safety.
    """
    hits: list[Hit] = []
    for name, pattern in PATTERNS:
        hits.extend(Hit(name, m.start(), m.end()) for m in pattern.finditer(text))
    return sorted(hits, key=lambda h: (h.start, h.pattern))


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

    Any class holding genotypes must inherit this. The default ``object`` and
    ``@dataclass`` ``__repr__`` will happily print allele values into a traceback, a log
    line, or a debugger session that someone later pastes into an issue.

    Subclasses may set ``_repr_fields`` to name attributes that are safe to show --
    counts, versions, flags. Anything not listed is omitted entirely rather than
    summarised, because summarising is how allele frequencies leak.

    **Works with ``@dataclass`` without ceremony.** The decorator would otherwise
    generate a ``__repr__`` directly on the subclass, shadowing this one through normal
    MRO lookup, so inheriting the mixin would silently buy nothing -- and dataclasses are
    the house style here, so that would have bitten the first genotype-bearing record.

    ``__init_subclass__`` therefore *claims the slot*: it copies this ``__repr__`` into
    the subclass's own ``__dict__``. ``dataclasses`` sets its generated methods through
    ``_set_new_attribute``, which never overwrites a name already present in
    ``cls.__dict__``, so it finds the slot taken and leaves it alone. A subclass that
    deliberately writes its own ``__repr__`` in the class body is refused outright.

    Note this cannot be enforced from ``__init_subclass__`` by *inspection*: the
    decorator runs after the class body, so at that point there is nothing yet to see.
    Claiming the slot works precisely because it happens first.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ()
    """Declared ``ClassVar`` so subclasses can be dataclasses: without it, a subclass
    restating ``_repr_fields`` as a ClassVar is a type error, and restating it *without*
    ClassVar makes it a dataclass field -- one that would then need passing to every
    constructor. It is class-level configuration in either case."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        own = cls.__dict__.get("__repr__")
        if own is not None and own is not NoGenotypeRepr.__repr__:
            raise TypeError(
                f"{cls.__name__} defines its own __repr__, which shadows NoGenotypeRepr "
                "and defeats the point of inheriting it. Remove it, or do not inherit "
                "the mixin."
            )
        cls.__repr__ = NoGenotypeRepr.__repr__  # type: ignore[method-assign]

    def __repr__(self) -> str:
        shown: list[str] = []
        for name in self._repr_fields:
            value = getattr(self, name, None)
            # Check the raw value first. Checking only repr(value) misses tab-delimited
            # rows, because repr escapes the very separators the patterns look for.
            dirty = isinstance(value, str) and looks_like_genotype(value)
            rendered = "<redacted>" if dirty else repr(value)
            if looks_like_genotype(rendered):
                rendered = "<redacted>"
            shown.append(f"{name}={rendered}")
        body = ", ".join(shown)
        return f"{type(self).__name__}({body})" if body else f"<{type(self).__name__}>"


class GenotypeLeakError(RuntimeError):
    """Raised when genotype-like content reaches somewhere it must not.

    Deliberately does not include the offending text -- an exception message is one of
    the places this content most easily escapes to.
    """


def assert_no_genotype(text: str, *, context: str = "") -> None:
    """Raise if ``text`` contains genotype-looking content.

    Use at every boundary where data leaves the process: log records, error messages,
    outbound web queries (AGENTS.md 1.3), and anything written to a tracked file.
    """
    hits = find_genotypes(text)
    if hits:
        where = f" in {context}" if context else ""
        names = ", ".join(sorted({hit.pattern for hit in hits}))
        raise GenotypeLeakError(
            f"Refusing to emit genotype-like content{where}: matched {names}. "
            f"Redact it or route it through genetics.privacy.redact()."
        )


def scan_paths(paths: Iterable[tuple[str, str]]) -> dict[str, list[Hit]]:
    """Scan ``(label, content)`` pairs. Returns only the entries with hits."""
    findings: dict[str, list[Hit]] = {}
    for label, content in paths:
        hits = find_genotypes(content)
        if hits:
            findings[label] = hits
    return findings
