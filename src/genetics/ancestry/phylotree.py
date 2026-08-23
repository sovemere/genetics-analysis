"""Reading the mtDNA phylogeny out of PhyloTree build 17 (roadmap M5.7).

PhyloTree publishes its tree as one 14 MB HTML file exported from a spreadsheet, and the
tree structure is carried by *which column* a name lands in: a haplogroup at column ``d``
is a child of the nearest preceding haplogroup at a column below ``d``, and the mutations
defining its branch sit in the cell immediately to its right. There is no nesting in the
markup to follow -- every row is flat, and the indentation is the data. That is the whole
trick, and it is why this module exists rather than a two-line call to an HTML parser.

**The archive is read in place rather than extracted.** The manifest declares an
``extract_zip`` post-process step for this source which has never been implemented, and
implementing it would put a second 14 MB copy of the file on disk to no benefit --
:mod:`zipfile` reads the member directly. The declaration is left standing because
``pharmgkb`` declares the same step and will genuinely need it.

**Encoding is cp1252 and stated rather than sniffed.** The file is an Excel HTML export
and carries no charset that survives round-tripping; decoding as UTF-8 raises on the
first non-breaking space. Wrong here means silently corrupted haplogroup names, which
would fail no test and produce a tree that mostly works.

**What is dropped, and why it is not a loss.** Of PhyloTree's mutation tokens 195 are
indels (``A249d``, ``315.1C``) and are skipped: the vendor writes ``I``/``D`` for an indel
with no sequence (AGENTS.md 4.2), so there is nothing to match them against. What remains
is 11,529 substitutions over 3,874 rCRS positions, of which the array touches 139.
"""

from __future__ import annotations

import functools
import html
import re
import zipfile
from pathlib import Path
from typing import Final

from genetics.ancestry.haplogroup import HaplogroupTree, Mutation, build_tree
from genetics.paths import references_dir

__all__ = ["PhyloTreeError", "load_mt_tree", "parse_mt_tree"]

ARCHIVE: Final[str] = "mtDNA_tree_Build_17.zip"
MEMBER: Final[str] = "mtDNA tree Build 17.htm"
SOURCE: Final[str] = "PhyloTree mtDNA build 17 (18 Feb 2016)"

ROOT: Final[str] = "rCRS"
"""The name given to PhyloTree's root.

PhyloTree's own top node is ``mt-MRCA``, reached from the rCRS by a list of mutations
every human carries. Calling the root ``rCRS`` keeps the tree's coordinate origin and its
root the same object, which is what makes a sample matching the reference at every site
resolve to the root rather than to a named haplogroup it does not belong to.
"""

_ROW: Final[re.Pattern[str]] = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL: Final[re.Pattern[str]] = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)
_COLSPAN: Final[re.Pattern[str]] = re.compile(r"colspan=(\d+)")
_TAG: Final[re.Pattern[str]] = re.compile(r"<[^>]*>")

_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Za-z0-9'@+]*$")
"""What a haplogroup name looks like: ``L0``, ``H1a1``, ``L0a'b'f'g'k``, ``U5b2a1a'b``."""

_SUBSTITUTION: Final[re.Pattern[str]] = re.compile(
    r"^(?P<open>\()?"
    r"(?P<ancestral>[ACGT])"
    r"(?P<position>\d+)"
    r"(?P<derived>[ACGTacgt])"
    r"(?P<reversion>!*)"
    r"(?P<close>\))?$"
)
"""One substitution token.

A lowercase derived base marks a transversion and an upper one a transition; the
distinction is PhyloTree's editorial annotation and carries no information this caller
uses, so the base is upper-cased and the notation discarded. ``!`` marks a reversion to
the ancestral state, which is *still a state change on this branch* and so still supports
it -- the token already names the base the branch arrives at. Parentheses mark a mutation
that is not consistently present, which becomes :attr:`Mutation.uncertain`.
"""

_MAX_DEPTH_COLUMN: Final[int] = 24
"""Columns past this hold example accessions (``EU092665``), not tree structure.

Measured from the file: the deepest real haplogroup sits at column 21 and the accession
columns begin at 25. Without this bound an accession would be read as a haplogroup name
at an absurd depth, silently re-parenting the subtree beneath it.
"""


class PhyloTreeError(RuntimeError):
    """Raised when the archive is absent or its structure is not what M5.7 measured."""


def _cells(row: str) -> list[str]:
    """Row markup to a flat list of cell texts, with ``colspan`` expanded.

    Expanding the span matters: a cell spanning three columns occupies three positions in
    the tree's coordinate system, and collapsing it would shift every name to its right
    into a shallower depth.
    """
    out: list[str] = []
    for match in _CELL.finditer(row):
        span = _COLSPAN.search(match.group(1))
        text = html.unescape(_TAG.sub(" ", match.group(2))).replace("\xa0", " ")
        out.append(" ".join(text.split()))
        out.extend([""] * ((int(span.group(1)) if span else 1) - 1))
    return out


def _mutations(text: str) -> list[Mutation]:
    """Parse one branch's mutation cell, skipping what cannot be matched to an array."""
    out: list[Mutation] = []
    for token in text.split():
        match = _SUBSTITUTION.match(token)
        if match is None:
            continue  # indel, insertion, or an annotation this caller cannot use
        out.append(
            Mutation(
                position=int(match.group("position")),
                ancestral=match.group("ancestral").upper(),
                derived=match.group("derived").upper(),
                uncertain=bool(match.group("open")),
                label=token,
            )
        )
    return out


def parse_mt_tree(archive: Path) -> HaplogroupTree:
    """Parse the PhyloTree archive into a tree. Prefer :func:`load_mt_tree`."""
    if not archive.exists():
        raise PhyloTreeError(
            f"{archive} is missing. Fetch it with `genetics refs fetch --only phylotree_17`."
        )
    try:
        with zipfile.ZipFile(archive) as zf:
            raw = zf.read(MEMBER).decode("cp1252", errors="replace")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise PhyloTreeError(f"{archive} is not the expected PhyloTree archive: {exc}") from exc

    parents: dict[str, str | None] = {ROOT: None}
    mutations: dict[str, list[Mutation]] = {}
    # Column index -> the haplogroup most recently opened at that depth. A name at column
    # d attaches to the deepest entry strictly left of it, which is what makes the flat
    # row sequence a tree.
    open_at: dict[int, str] = {}

    for row in _ROW.finditer(raw):
        cells = [(i, v) for i, v in enumerate(_cells(row.group(1))) if v]
        if not cells:
            continue
        column, text = cells[0]
        if column > _MAX_DEPTH_COLUMN or not _NAME.match(text):
            continue
        if _SUBSTITUTION.match(text):
            continue  # an unnamed sub-branch carrying only mutations

        parent = next((open_at[c] for c in sorted(open_at, reverse=True) if c < column), ROOT)
        name = text
        if name in parents:
            # PhyloTree lists a handful of names twice where a branch is shown in two
            # places. Keeping the first occurrence keeps the shallower, canonical
            # placement; overwriting would re-parent a whole subtree onto a leaf.
            continue
        parents[name] = parent
        open_at[column] = name
        for deeper in [c for c in open_at if c > column]:
            del open_at[deeper]

        if len(cells) > 1 and cells[1][0] == column + 1:
            mutations[name] = _mutations(cells[1][1])

    if len(parents) < 1000:
        raise PhyloTreeError(
            f"parsed only {len(parents)} haplogroups from {archive}; M5.7 measured 4,882. "
            "The archive's structure has changed and the parser has not."
        )
    return build_tree("MT", SOURCE, ROOT, parents, mutations)


@functools.lru_cache(maxsize=1)
def load_mt_tree(archive: Path | None = None) -> HaplogroupTree:
    """The mtDNA tree, parsed once per process.

    Cached because parsing 14 MB of HTML takes a few seconds and every run needs the same
    immutable result -- build 17 has been frozen since 2016. The cache is keyed on the
    path so a test can pass a fixture without poisoning it for the real archive.
    """
    return parse_mt_tree(archive or references_dir() / "phylotree_17" / ARCHIVE)
