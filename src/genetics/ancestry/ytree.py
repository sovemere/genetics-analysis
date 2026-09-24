"""Reading the Y phylogeny out of the ISOGG marker table (roadmap M5.7).

The counterpart to :mod:`genetics.ancestry.phylotree`, and structurally its opposite.
PhyloTree ships a tree whose mutations hang off it; ISOGG ships a flat list of mutations
whose *names* imply the tree. ``R1b1a1b`` is a child of ``R1b1a1`` because ISOGG's
nomenclature alternates letter and digit runs, one run per branch, so a node's parent is
its own name with the last run removed. Nothing else states the topology.

**Except at the backbone, where the naming rule does not hold.** The deep nodes carry
compound names -- ``BT``, ``CF``, ``DE``, ``IJK``, ``A0-T`` -- built from the descendants
they unite rather than from their own parent, and stripping a run off ``IJK`` yields
nothing. Those relationships come from ``base_tree.nw``, a Newick string in the same
release, which exists precisely because the naming rule stops there. Six names in 10,205
need it; without it, six subtrees covering most of humanity detach from the root.

**Which allele is derived is read, not inferred.** ``MutationInfo`` carries ``C->A``:
ancestral first, derived second. The separate ``Variant`` column repeats the derived base,
and where the two disagree the row is dropped rather than reconciled -- a marker whose
polarity is uncertain would push the call down a branch on the strength of an ancestral
allele, which is worse than not testing it.

**Resolution is bounded by the array, not by this table** ([AGENTS.md 4.7](AGENTS.md)).
Measured 2026-08-23 against the real export: 74,569 markers over 10,205 haplogroups here,
of which the array's 1,665 chrY markers touch 1,129 (re-measured at M5.8, 2026-09-24; M5.7
wrote 1,141, reaching 629, before its parsing was final).
"""

from __future__ import annotations

import csv
import functools
import re
from pathlib import Path
from typing import Final

from genetics.ancestry.haplogroup import HaplogroupTree, Mutation, build_tree
from genetics.paths import references_dir

__all__ = ["YTreeError", "load_y_tree", "parse_y_tree"]

DIRECTORY: Final[str] = "y_tree_isogg_grch37"
MARKERS: Final[str] = "ISOGG_haplogroup_info.csv"
BACKBONE: Final[str] = "base_tree.nw"
SOURCE: Final[str] = "ISOGG Y-DNA tree via Y-LineageTracker (commit 82b14c7)"

ROOT: Final[str] = "Y-Adam"
"""The name ``base_tree.nw`` gives its root. Kept rather than renamed so the two files
agree; a call that reaches no branch reports this, which reads correctly as "no Y lineage
was resolved" and, for a female sample, as the expected outcome."""

_RUN: Final[re.Pattern[str]] = re.compile(r"[A-Z]+|[0-9]+|[a-z]+")
"""One run of an ISOGG name. ``R1b1a1b`` is ``R | 1 | b | 1 | a | 1 | b``."""

_MUTATION: Final[re.Pattern[str]] = re.compile(r"^([ACGT])->([ACGT])$")

_SUFFIXES: Final[str] = "~*"
"""``~`` marks a provisional placement and ``*`` a paragroup. Both are annotations on the
node, not part of its position in the tree, and are stripped before the parent is derived
-- ``B~`` is the same node as ``B`` for descent purposes."""


class YTreeError(RuntimeError):
    """Raised when the ISOGG table is absent or its structure is not what M5.7 measured."""


def _strip(name: str) -> str:
    return name.rstrip(_SUFFIXES)


def _implied_parent(name: str) -> str | None:
    """``R1b1a1b`` -> ``R1b1a1``. ``R`` -> ``None`` (a backbone node's parent is not
    derivable from its name)."""
    runs = _RUN.findall(name)
    if len(runs) <= 1:
        return None
    return "".join(runs[:-1])


def parse_y_tree(directory: Path) -> HaplogroupTree:
    """Parse the ISOGG marker table and backbone into a tree. Prefer :func:`load_y_tree`."""
    markers = directory / MARKERS
    backbone = directory / BACKBONE
    for path in (markers, backbone):
        if not path.exists():
            raise YTreeError(
                f"{path} is missing. Fetch it with "
                "`genetics refs fetch --only y_tree_isogg_grch37`."
            )

    backbone_parents = _newick_parents(backbone.read_text(encoding="utf-8"))

    mutations: dict[str, list[Mutation]] = {}
    seen: set[str] = set()
    with markers.open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            name = _strip((row.get("Haplogroup") or "").strip())
            build37 = (row.get("Build37") or "").strip()
            info = _MUTATION.match((row.get("MutationInfo") or "").strip())
            variant = (row.get("Variant") or "").strip().upper()
            if not name or not build37.isdigit() or info is None:
                continue
            ancestral, derived = info.group(1), info.group(2)
            if variant and variant != derived:
                continue  # polarity disagrees between columns; see module docstring
            seen.add(name)
            mutations.setdefault(name, []).append(
                Mutation(
                    position=int(build37),
                    ancestral=ancestral,
                    derived=derived,
                    uncertain=bool((row.get("ApproximateInfo") or "").strip()),
                    label=(row.get("Mutation") or "").strip(),
                )
            )

    parents: dict[str, str | None] = {ROOT: None}
    for name in sorted(seen | set(backbone_parents)):
        if name == ROOT:
            continue
        parent = backbone_parents.get(name) or _implied_parent(name) or ROOT
        parents[name] = parent

    # Every implied parent must itself be a node. ISOGG lists markers only for branches
    # that have them, so `R1b1a1b` can appear with no row of its own for `R1b1a1`; the
    # intermediate is created empty rather than re-parenting its child onto the root,
    # which would flatten the tree and shorten every path through it.
    while True:
        missing = {p for p in parents.values() if p is not None and p not in parents}
        if not missing:
            break
        for name in missing:
            parents[name] = backbone_parents.get(name) or _implied_parent(name) or ROOT

    if len(parents) < 5000:
        raise YTreeError(
            f"parsed only {len(parents)} haplogroups from {markers}; M5.7 measured "
            "10,205. The table's structure has changed and the parser has not."
        )
    return build_tree("Y", SOURCE, ROOT, parents, mutations)


def _newick_parents(text: str) -> dict[str, str]:
    """Parent-of map from a Newick topology.

    Recursive descent over 221 bytes. A node is an optional parenthesised child list
    followed by that node's own label, so the children are known before the label that
    owns them is read -- which is why this cannot be done with a single left-to-right
    scan and a stack of names.
    """
    parents: dict[str, str] = {}
    body = text.strip().rstrip(";")
    cursor = 0

    def node() -> str:
        nonlocal cursor
        children: list[str] = []
        if cursor < len(body) and body[cursor] == "(":
            cursor += 1
            while True:
                children.append(node())
                if cursor < len(body) and body[cursor] == ",":
                    cursor += 1
                    continue
                if cursor < len(body) and body[cursor] == ")":
                    cursor += 1
                break
        start = cursor
        while cursor < len(body) and body[cursor] not in "(),":
            cursor += 1
        label = body[start:cursor].strip()
        for child in children:
            parents[child] = label
        return label

    node()
    return {child: parent for child, parent in parents.items() if child and parent}


@functools.lru_cache(maxsize=1)
def load_y_tree(directory: Path | None = None) -> HaplogroupTree:
    """The Y tree, parsed once per process."""
    return parse_y_tree(directory or references_dir() / DIRECTORY)
