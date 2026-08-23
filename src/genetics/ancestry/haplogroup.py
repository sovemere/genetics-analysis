"""Calling a haplogroup by walking a phylogeny from its root (roadmap M5.7).

Two lineages, one algorithm. mtDNA arrives from PhyloTree 17
(:mod:`genetics.ancestry.phylotree`) and Y-DNA from the ISOGG marker table
(:mod:`genetics.ancestry.ytree`), in different formats describing the same kind of object:
a rooted tree whose every branch is defined by the mutations that occurred on it. Both
loaders build the :class:`HaplogroupTree` below and both call through :func:`call`, which
is why this module holds no notion of which lineage it is walking.

**The uniparental markers are haploid, and that is what makes this tractable.** Neither
the mitochondrion nor the non-recombining Y recombines, so a sample's history is a single
path from the root to one node -- a perfect phylogeny. There is no phasing step, no
probability model, and no admixture: at every branch the sample either carries the derived
state or it does not. That is a much weaker claim than the PCA in
:mod:`genetics.ancestry.projection` needs to make, and it is why this milestone is small.

**The array is the ceiling, not the tree** ([AGENTS.md 4.7](AGENTS.md)). PhyloTree 17
places 11,529 mutations and the ISOGG table 74,569, but an AncestryDNA export carries 262
MT markers and 1,665 chrY markers, and only about half of each falls on a defining site.
So the honest output is not a haplogroup but a haplogroup *plus what supported it*:
:class:`HaplogroupCall` carries the supporting and contradicting marker counts at every
step of the path, and :attr:`HaplogroupCall.markers_on_array` states how far the array could
ever have resolved regardless of this sample. A card that prints the name without those numbers
is making a claim the data does not carry.

**Descent stops at ambiguity rather than guessing.** :func:`call` moves to a child only
when exactly one child is supported. Two supported siblings mean the markers on this array
cannot separate them -- usually recurrent mutation at a site that defines branches in two
places -- and the call stays at the parent with :attr:`HaplogroupCall.stopped_because`
saying so. Choosing the child with the higher count would produce a deeper, more precise
looking name from the same evidence, which is the failure mode AGENTS.md 0.1 exists to
prevent.

**Contradicting markers are counted but do not veto.** A back mutation, a genotyping
error, and a genuinely misplaced branch all look identical from one sample, and PhyloTree
annotates known recurrent sites precisely because they are common. So a branch is taken on
positive evidence and the contradictions travel with the call for the reader to weigh,
rather than silently pruning a branch the sample probably belongs to.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Final

import polars as pl

from genetics.ingest.schema import GenotypeTable
from genetics.privacy import NoGenotypeRepr

__all__ = [
    "Haplogroup",
    "HaplogroupCall",
    "HaplogroupTree",
    "Mutation",
    "PathStep",
    "build_tree",
    "call",
    "observed_haploid_alleles",
]


@dataclass(frozen=True, slots=True)
class Mutation:
    """One state change on one branch, in the lineage's own coordinate system.

    ``position`` is rCRS for mtDNA and GRCh37 chrY for Y-DNA. The two never mix in one
    tree, so the ambiguity costs nothing and naming the field for either build would be
    wrong half the time.
    """

    position: int
    ancestral: str
    derived: str
    uncertain: bool = False
    """PhyloTree parenthesises a mutation that is not consistently present on its branch,
    and ISOGG marks investigational markers. Such a site still counts toward support --
    dropping it would discard most of what a sparse array offers -- but it is tracked so
    :attr:`PathStep.uncertain_support` can say how much of a thin call rests on them."""

    label: str = ""
    """The marker's published name (``M269``, ``A263G``). Carried for the card; the call
    never keys on it, because ISOGG names one marker several ways and PhyloTree none."""


@dataclass(frozen=True, slots=True)
class Haplogroup:
    """One node: a name, its parent, and the mutations that define the branch reaching it."""

    name: str
    parent: str | None
    mutations: tuple[Mutation, ...]
    depth: int


@dataclass(frozen=True)
class HaplogroupTree:
    """A rooted phylogeny in the shape :func:`call` walks.

    Deliberately not indexed by position. The walk only ever asks about the children of
    the node it is standing on, so it touches a handful of nodes per call however large
    the tree is; a position index would be built over ten thousand nodes to answer
    questions about a dozen.
    """

    lineage: str
    """``"MT"`` or ``"Y"``. Only used in messages and to pick the chromosome to read."""

    source: str
    """Which release this came from, for the card's provenance line."""

    nodes: Mapping[str, Haplogroup]
    root: str
    children: Mapping[str, tuple[str, ...]]

    @property
    def positions(self) -> frozenset[int]:
        """Every position any branch in this tree is defined by."""
        return frozenset(m.position for node in self.nodes.values() for m in node.mutations)

    def path_to_root(self, name: str) -> tuple[str, ...]:
        """``name`` and its ancestors, root first."""
        out: list[str] = []
        cursor: str | None = name
        while cursor is not None:
            out.append(cursor)
            cursor = self.nodes[cursor].parent
        return tuple(reversed(out))

    def walk(self) -> Iterator[Haplogroup]:
        """Every node, parents before children."""
        stack = [self.root]
        while stack:
            node = stack.pop()
            yield self.nodes[node]
            stack.extend(reversed(self.children.get(node, ())))


@dataclass(frozen=True, slots=True)
class PathStep(NoGenotypeRepr):
    """One branch the call descended, and the evidence that justified it."""

    name: str
    supporting: int
    contradicting: int
    uncertain_support: int
    typed: int
    """Defining markers for this branch that the array carries at all. ``supporting +
    contradicting`` can be lower: a no-call is typed by neither."""


@dataclass(frozen=True)
class HaplogroupCall(NoGenotypeRepr):
    """A haplogroup assignment and everything a reader needs to discount it.

    :class:`~genetics.privacy.NoGenotypeRepr` because the path implies genotypes: naming
    the branches a sample descended states its derived alleles at every defining site as
    surely as printing them would.

    ``_repr_fields`` shows the shape of the call and withholds the call itself, matching
    :class:`~genetics.ancestry.projection.Projection`. The haplogroup name and the path
    are the two fields a debug log would most want and are exactly the two that restate
    the genotypes; a caller that wants them reads the attributes.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = (
        "lineage",
        "depth",
        "markers_on_array",
        "markers_typed",
    )

    lineage: str
    source: str
    haplogroup: str
    path: tuple[PathStep, ...]
    markers_on_array: int
    """Array markers for this lineage that fall on any defining site in this tree. The
    resolution ceiling AGENTS.md 4.7 requires the card to state."""

    markers_typed: int
    """Of those, how many this sample actually called."""

    stopped_because: str

    @property
    def supporting(self) -> int:
        """Derived-state markers backing the whole path."""
        return sum(step.supporting for step in self.path)

    @property
    def contradicting(self) -> int:
        return sum(step.contradicting for step in self.path)

    @property
    def depth(self) -> int:
        """How many branches below the root the call sits. Zero means unresolved."""
        return len(self.path)

    @property
    def resolved(self) -> bool:
        return self.depth > 0


_MIN_SUPPORT: Final[int] = 1
"""Derived markers a node needs before it is a candidate at all.

One, and deliberately so rather than an unset threshold. Most branches a consumer array
can reach are defined by exactly one typed marker; requiring two would discard the depth
the array does offer and report a shallow call as though the tree were shallow. The cost
is that a single genotyping error makes a spurious candidate, which is handled by ranking
on corroboration rather than by raising this floor -- see :func:`call` -- and by
:class:`PathStep` publishing the count per step, so a path whose every step reads
``supporting=1`` is visibly a different claim from one whose steps read ``supporting=6``.
"""


def observed_haploid_alleles(table: GenotypeTable, chrom: str) -> dict[int, str]:
    """Position to single observed base, for a haploid chromosome.

    Both vendor columns carry the same base at a haploid locus (``G G``), so one is read
    and the pair is required to agree. A disagreement is a
    :attr:`~genetics.ingest.schema.CallStatus.HET_HAPLOID` contradiction -- a genotyping
    error at a single-copy site -- and is dropped rather than resolved: picking either
    allele would invent the evidence a branch is then taken on. The real export carries
    one such chrY site out of 1,665.

    Indel alleles (``I``/``D``) are dropped too. Neither tree defines a branch by an indel
    this project can key on, because the vendor records no sequence for one
    (AGENTS.md 4.2) and both trees name insertions by the bases inserted.
    """
    frame = table.frame.filter(
        (pl.col("chrom") == chrom)
        & pl.col("a1").is_not_null()
        & (pl.col("a1") == pl.col("a2"))
        & pl.col("a1").is_in(("A", "C", "G", "T"))
    ).select("pos_grch37", "a1")
    return {int(pos): str(allele) for pos, allele in frame.iter_rows()}


def _score(node: Haplogroup, observed: Mapping[int, str]) -> tuple[int, int, int, int]:
    """``(supporting, contradicting, uncertain_support, typed)`` for one branch."""
    supporting = contradicting = uncertain = typed = 0
    for mutation in node.mutations:
        base = observed.get(mutation.position)
        if base is None:
            continue
        typed += 1
        if base == mutation.derived:
            supporting += 1
            if mutation.uncertain:
                uncertain += 1
        elif base == mutation.ancestral:
            contradicting += 1
    return supporting, contradicting, uncertain, typed


def call(tree: HaplogroupTree, table: GenotypeTable) -> HaplogroupCall:
    """Assign the deepest haplogroup ``table`` supports, and say what supported it.

    Returns a call at the root when nothing is supported, rather than raising: "the array
    carries no derived marker for this lineage" is a result a card can render, and for a
    female sample on the Y it is the *expected* result rather than an error.
    """
    observed = observed_haploid_alleles(table, tree.lineage)
    scored = {node.name: _score(node, observed) for node in tree.walk()}

    # Deepest-supported, NOT greedy root-to-tip descent, and the difference is the whole
    # correctness of this function. The first implementation walked down from the root and
    # required a derived marker at every branch it crossed. That is right for a sequenced
    # genome and wrong for an array: PhyloTree defines most branches by mutations no
    # consumer chip carries, so an unbroken chain of supported branches does not exist and
    # the walk halted three steps down, reporting a deep-African mtDNA haplogroup for a
    # European sample and nothing at all for the Y. Measured on the real export before the
    # rewrite: mtDNA stopped at L2'3'4'6, chrY at the root with 1,126 markers called.
    #
    # A branch with no typed marker is not evidence against the lineage passing through
    # it; it is silence. So candidates are nodes whose *own* markers are derived, and the
    # path is then read off the tree rather than walked.
    candidates = [
        name
        for name, (supporting, contradicting, _u, _t) in scored.items()
        if supporting >= _MIN_SUPPORT and supporting > contradicting
    ]

    def consistent(name: str) -> bool:
        """No ancestor of ``name`` is outvoted by its own contradicting markers.

        Silence still passes. What fails is a node the sample is positively ancestral at,
        which places it outside that clade however many derived markers sit below.

        The comparison here is ``>=`` where the candidate test above is ``>``, and the
        asymmetry is intended: a candidate must show positive evidence for itself, while
        an ancestor is only asked whether the sample is *excluded* from its clade. A tie
        is ambiguous, and ambiguity is not exclusion.
        """
        return all(
            scored[step][0] >= scored[step][1]
            for step in tree.path_to_root(name)
            if scored[step][3]
        )

    viable = [name for name in candidates if consistent(name)]

    def corroboration(name: str) -> tuple[int, int]:
        """``(support along the whole path, depth)`` -- the ranking key.

        Depth alone is not safe. A single erroneous derived call at a deep node in an
        unrelated clade is a viable candidate, because on a sparse array almost none of
        its ancestors are typed and silence does not disqualify them; ranked on depth it
        would beat a call twenty branches shallower resting on eighty concordant markers.
        Summing support along the path fixes that without a threshold: a node in the
        correct clade inherits every supported branch above it, while the intruder brings
        only itself. Depth remains the tie-break, so the deepest of equally corroborated
        nodes still wins.
        """
        return (
            sum(scored[step][0] for step in tree.path_to_root(name)),
            tree.nodes[name].depth,
        )

    if not viable:
        best = tree.root
        stopped = (
            "no branch carried a derived marker on this array"
            if any(scored[n][3] for n in scored)
            else "this array types no marker that defines a branch in this tree"
        )
    else:
        best_key = max(corroboration(name) for name in viable)
        tied = sorted(name for name in viable if corroboration(name) == best_key)
        best = tied[0]
        stopped = "no better-supported branch was reachable on this array"
        if len(tied) > 1:
            # Equally corroborated, equally deep and incomparable: recurrent mutation
            # at a site defining branches in two clades. Backing off to the common
            # ancestor is the honest answer; picking one would name a subclade on
            # evidence that fits several equally. AGENTS.md 0.1.
            best = _common_ancestor(tree, tied)
            names = ", ".join(tied)
            stopped = (
                f"the array cannot separate {len(tied)} equally supported branches "
                f"({names}); the call backed off to their common ancestor"
            )

    path = tuple(
        PathStep(
            name=step,
            supporting=scored[step][0],
            contradicting=scored[step][1],
            uncertain_support=scored[step][2],
            typed=scored[step][3],
        )
        for step in tree.path_to_root(best)
        if step != tree.root
    )

    defining = tree.positions
    # Two different denominators, and conflating them was a real defect in the first draft
    # of this function. `on_array` asks what this *array* could ever resolve -- a property
    # of the chip, identical for every sample run through it. `typed_positions` asks what
    # this *sample* returned. A female sample on the Y has the full chrY ceiling and zero
    # typed markers, and a card that showed one number could not say which it meant.
    on_array = defining & frozenset(
        int(pos)
        for (pos,) in table.frame.filter(pl.col("chrom") == tree.lineage)
        .select("pos_grch37")
        .iter_rows()
    )
    typed_positions = defining & frozenset(observed)

    return HaplogroupCall(
        lineage=tree.lineage,
        source=tree.source,
        haplogroup=best,
        path=path,
        markers_on_array=len(on_array),
        markers_typed=len(typed_positions),
        stopped_because=stopped,
    )


def _common_ancestor(tree: HaplogroupTree, names: Sequence[str]) -> str:
    """The deepest node every name in ``names`` descends from."""
    paths = [tree.path_to_root(name) for name in names]
    shared = tree.root
    for step in zip(*paths, strict=False):
        if len(set(step)) != 1:
            break
        shared = step[0]
    return shared


def build_tree(
    lineage: str,
    source: str,
    root: str,
    parents: Mapping[str, str | None],
    mutations: Mapping[str, Sequence[Mutation]],
) -> HaplogroupTree:
    """Assemble a :class:`HaplogroupTree` from a loader's flat output.

    Shared by both loaders so the depth computation, the child index and the structural
    checks exist once. Raises :class:`ValueError` for a parent that is not a node and for
    a cycle -- both are corruption in the source table rather than bad input from a user,
    and a tree with a cycle makes :func:`call` loop forever.
    """
    missing = {p for p in parents.values() if p is not None and p not in parents}
    if missing:
        raise ValueError(
            f"{lineage}: {len(missing)} parent(s) are not nodes, e.g. {sorted(missing)[:3]}"
        )
    if root not in parents:
        raise ValueError(f"{lineage}: root {root!r} is not a node")

    depth: dict[str, int] = {}

    def _depth(name: str) -> int:
        chain: list[str] = []
        cursor: str | None = name
        while cursor is not None and cursor not in depth:
            if cursor in chain:
                raise ValueError(f"{lineage}: cycle through {cursor!r}")
            chain.append(cursor)
            cursor = parents[cursor]
        base = 0 if cursor is None else depth[cursor]
        for offset, node in enumerate(reversed(chain), start=1):
            depth[node] = base + offset
        return depth[name]

    for name in parents:
        _depth(name)

    children: dict[str, list[str]] = {}
    for name, parent in parents.items():
        if parent is not None:
            children.setdefault(parent, []).append(name)

    nodes = {
        name: Haplogroup(
            name=name,
            parent=parent,
            mutations=tuple(mutations.get(name, ())),
            depth=depth[name] - depth[root],
        )
        for name, parent in parents.items()
    }
    return HaplogroupTree(
        lineage=lineage,
        source=source,
        nodes=nodes,
        root=root,
        children={k: tuple(sorted(v)) for k, v in children.items()},
    )
