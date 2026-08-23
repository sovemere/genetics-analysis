"""Loading the two published phylogenies (roadmap M5.7).

Split by what each test needs. The parsing rules -- an ISOGG name implying its parent, a
Newick backbone, a PhyloTree mutation token -- are exercised on inline strings and run
everywhere. The whole-corpus assertions need the real archives and are skipped where
those have not been fetched, which includes CI: neither source ships in the checkout
(``data/references`` payloads are gitignored) and neither is small enough to vendor.

The skipped tests are the ones that would catch a publisher changing a format under us,
so they are written to be run by a developer who has the corpus rather than left out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genetics.ancestry import phylotree, ytree
from genetics.ancestry.phylotree import (
    ARCHIVE,
    PhyloTreeError,
    _mutations,
    load_mt_tree,
    parse_mt_tree,
)
from genetics.ancestry.ytree import (
    DIRECTORY,
    YTreeError,
    _implied_parent,
    _newick_parents,
    _strip,
    load_y_tree,
    parse_y_tree,
)
from genetics.paths import references_dir

MT_ROOT = phylotree.ROOT
Y_ROOT = ytree.ROOT

MT_ARCHIVE = references_dir() / "phylotree_17" / ARCHIVE
Y_DIRECTORY = references_dir() / DIRECTORY

needs_mt = pytest.mark.skipif(not MT_ARCHIVE.exists(), reason="phylotree_17 not fetched")
needs_y = pytest.mark.skipif(
    not (Y_DIRECTORY / "ISOGG_haplogroup_info.csv").exists(),
    reason="y_tree_isogg_grch37 not fetched",
)


# ---------------------------------------------------------------------------
# Parsing rules -- no corpus required
# ---------------------------------------------------------------------------


def test_isogg_name_implies_its_parent() -> None:
    assert _implied_parent("R1b1a1b") == "R1b1a1"
    assert _implied_parent("R1b1a1") == "R1b1a"
    assert _implied_parent("R1") == "R"
    # A backbone node's parent is not derivable from its name; base_tree.nw supplies it.
    assert _implied_parent("R") is None
    assert _implied_parent("IJK") is None


def test_provisional_and_paragroup_suffixes_are_stripped() -> None:
    """``B~`` and ``D2*`` are annotations on a node, not positions in the tree."""
    assert _strip("B~") == "B"
    assert _strip("D2*") == "D2"
    assert _strip("R1b1a1b") == "R1b1a1b"


def test_newick_backbone_is_read_label_after_children() -> None:
    parents = _newick_parents("((A,B)AB,(C,D)CD)root;")
    assert parents == {"A": "AB", "B": "AB", "C": "CD", "D": "CD", "AB": "root", "CD": "root"}


def test_phylotree_substitution_tokens() -> None:
    [mutation] = _mutations("G263A")
    assert (mutation.position, mutation.ancestral, mutation.derived) == (263, "G", "A")
    assert not mutation.uncertain

    # A lowercase derived base marks a transversion; the caller does not use the
    # distinction, so the base is upper-cased rather than treated as a different allele.
    [transversion] = _mutations("C3516a")
    assert transversion.derived == "A"

    # Parentheses mark a mutation not consistently present on the branch.
    [uncertain] = _mutations("(A95c)")
    assert uncertain.uncertain

    # A reversion is still a state change on this branch and still supports it.
    [reversion] = _mutations("A263G!")
    assert (reversion.ancestral, reversion.derived) == ("A", "G")


def test_phylotree_skips_what_cannot_be_matched_to_an_array() -> None:
    """Indels carry no sequence in a vendor export (AGENTS.md 4.2)."""
    assert _mutations("A249d 315.1C 8281-8289d") == []
    assert len(_mutations("A249d G263A")) == 1


def test_missing_corpus_raises_with_the_command_that_fixes_it(tmp_path: Path) -> None:
    with pytest.raises(PhyloTreeError, match="refs fetch --only phylotree_17"):
        parse_mt_tree(tmp_path / "absent.zip")
    with pytest.raises(YTreeError, match="refs fetch --only y_tree_isogg_grch37"):
        parse_y_tree(tmp_path)


# ---------------------------------------------------------------------------
# Whole-corpus structure -- needs the fetched references
# ---------------------------------------------------------------------------


@needs_mt
def test_mt_tree_matches_what_m5_7_measured() -> None:
    tree = load_mt_tree()
    assert tree.lineage == "MT"
    assert tree.root == MT_ROOT
    assert len(tree.nodes) > 4800
    assert len(tree.positions) > 3500


@needs_mt
def test_mt_tree_reproduces_the_canonical_path_to_h1a() -> None:
    """The best-known lineage in the tree, and the one a broken parse would mangle.

    rCRS to H1a runs through the L3 -> N -> R -> HV backbone. Getting this right requires
    the column-depth reading to be correct at every level; an off-by-one in the indentation
    logic reparents whole clades and shows up here first.
    """
    path = load_mt_tree().path_to_root("H1a")
    assert path[0] == MT_ROOT
    assert path[-1] == "H1a"
    for expected in ("L3", "N", "R", "R0", "HV", "H", "H1"):
        assert expected in path, f"{expected} missing from {path}"
    assert path.index("L3") < path.index("N") < path.index("R") < path.index("H")


@needs_y
def test_y_tree_matches_what_m5_7_measured() -> None:
    tree = load_y_tree()
    assert tree.lineage == "Y"
    assert tree.root == Y_ROOT
    assert len(tree.nodes) > 9000
    assert len(tree.positions) > 70000


@needs_y
def test_y_tree_attaches_the_backbone_clades_to_the_root() -> None:
    """Without ``base_tree.nw`` these six detach and take most of humanity with them."""
    tree = load_y_tree()
    for name in ("R", "O2", "E1b1a1", "I1", "J1", "Q1"):
        assert name in tree.nodes, f"{name} absent"
        assert tree.path_to_root(name)[0] == Y_ROOT, f"{name} is not rooted"


@needs_y
def test_y_tree_reproduces_the_known_r1b_lineage() -> None:
    path = load_y_tree().path_to_root("R1b1a1b")
    assert path[0] == Y_ROOT
    for expected in ("A1", "A1b", "BT", "CT", "F", "K", "P", "R", "R1", "R1b"):
        assert expected in path, f"{expected} missing from {path}"
    assert path.index("BT") < path.index("CT") < path.index("F") < path.index("R")


@needs_y
def test_y_mutations_carry_grch37_positions() -> None:
    """A build mix-up here would silently stop every marker matching the array."""
    tree = load_y_tree()
    positions = tree.positions
    # chrY on GRCh37 is 59.4 Mb; every defining site must fall inside it.
    assert min(positions) > 2_000_000
    assert max(positions) < 59_400_000
