"""The haplogroup walk (roadmap M5.7).

Built on hand-written trees rather than on PhyloTree or ISOGG, because what is being held
to account here is the *algorithm* and a real tree cannot isolate its cases: a sparse
branch, a contradicted ancestor and two equally deep siblings all exist somewhere in
PhyloTree, but not where a test can point at them and say what should happen.

The case that matters most is :func:`test_descends_through_branches_with_no_typed_marker`.
The first implementation of :func:`~genetics.ancestry.haplogroup.call` walked root-to-tip
and required a derived marker at every branch it crossed, which is correct for a sequenced
genome and wrong for an array -- and every test written against a dense synthetic tree
passed. It was caught only by running the real export, where it reported a deep-African
mtDNA haplogroup for a European sample. That failure is now a test.
"""

from __future__ import annotations

import polars as pl
import pytest

from genetics.ancestry.haplogroup import (
    HaplogroupTree,
    Mutation,
    build_tree,
    call,
    observed_haploid_alleles,
)
from genetics.ingest.schema import CALL_STATUS_ORDER, CHROM_ORDER, GenotypeTable


def table(chrom: str, calls: dict[int, str | None]) -> GenotypeTable:
    """A genotype table carrying one haploid chromosome. ``None`` is a no-call."""
    rows = [
        {
            "rsid": f"v{pos}",
            "chrom": chrom,
            "pos_grch37": pos,
            "a1": base,
            "a2": base,
            "genotype": None if base is None else base * 2,
            "call_status": "no_call" if base is None else "hemizygous",
        }
        for pos, base in sorted(calls.items())
    ]
    frame = pl.DataFrame(
        rows,
        schema={
            "rsid": pl.String(),
            "chrom": pl.Enum(CHROM_ORDER),
            "pos_grch37": pl.UInt32(),
            "a1": pl.String(),
            "a2": pl.String(),
            "genotype": pl.String(),
            "call_status": pl.Enum(CALL_STATUS_ORDER),
        },
    )
    return GenotypeTable(frame, vendor="test")


def linear_tree() -> HaplogroupTree:
    """``root -> A -> A1 -> A1a``, one defining mutation each, plus a sibling ``B``."""
    parents = {"root": None, "A": "root", "A1": "A", "A1a": "A1", "B": "root"}
    mutations = {
        "A": [Mutation(100, "G", "A")],
        "A1": [Mutation(200, "C", "T")],
        "A1a": [Mutation(300, "T", "C")],
        "B": [Mutation(900, "A", "G")],
    }
    return build_tree("Y", "test", "root", parents, mutations)


def test_resolves_to_the_deepest_supported_node() -> None:
    result = call(linear_tree(), table("Y", {100: "A", 200: "T", 300: "C"}))
    assert result.haplogroup == "A1a"
    assert result.depth == 3
    assert result.supporting == 3
    assert result.contradicting == 0


def test_descends_through_branches_with_no_typed_marker() -> None:
    """A branch the array does not type is silence, not evidence against.

    The regression that motivated the rewrite: only the deepest marker is typed, and the
    two branches above it are untested. A root-to-tip walk stops at the root here; the
    correct answer is A1a, because nothing contradicts the path reaching it.
    """
    result = call(linear_tree(), table("Y", {300: "C"}))
    assert result.haplogroup == "A1a"
    assert result.depth == 3
    # The path still reports honestly that two of its three steps rest on nothing.
    assert [(s.name, s.supporting, s.typed) for s in result.path] == [
        ("A", 0, 0),
        ("A1", 0, 0),
        ("A1a", 1, 1),
    ]


def test_ancestral_state_at_an_ancestor_blocks_the_clade() -> None:
    """Silence passes; a positive ancestral call does not.

    Being ancestral at ``A`` places the sample outside that clade however many derived
    markers sit below it, so ``A1a`` must not be reported.
    """
    result = call(linear_tree(), table("Y", {100: "G", 300: "C"}))
    assert result.haplogroup != "A1a"
    assert not result.resolved


def test_equally_deep_siblings_back_off_to_their_common_ancestor() -> None:
    parents = {"root": None, "A": "root", "A1": "A", "A2": "A"}
    mutations = {
        "A": [Mutation(100, "G", "A")],
        "A1": [Mutation(200, "C", "T")],
        "A2": [Mutation(300, "C", "T")],
    }
    tree = build_tree("Y", "test", "root", parents, mutations)
    result = call(tree, table("Y", {100: "A", 200: "T", 300: "T"}))
    assert result.haplogroup == "A"
    assert "cannot separate" in result.stopped_because
    assert "A1" in result.stopped_because and "A2" in result.stopped_because


def test_no_derived_marker_returns_the_root_rather_than_raising() -> None:
    """The expected outcome for a female sample on the Y, not an error."""
    result = call(linear_tree(), table("Y", {100: "G", 200: "C"}))
    assert result.haplogroup == "root"
    assert result.depth == 0
    assert not result.resolved
    assert result.path == ()


def test_ceiling_and_typed_counts_are_different_denominators() -> None:
    """``markers_on_array`` is a property of the chip; ``markers_typed`` of the sample.

    Collapsing the two was a real defect: a card showing one number could not say whether
    a low count meant a thin array or a failed sample.
    """
    result = call(linear_tree(), table("Y", {100: "A", 200: None, 300: None}))
    assert result.markers_on_array == 3
    assert result.markers_typed == 1


def test_heterozygous_haploid_call_is_dropped_not_resolved() -> None:
    """Picking either allele would invent the evidence a branch is then taken on."""
    rows = [
        {
            "rsid": "v100",
            "chrom": "Y",
            "pos_grch37": 100,
            "a1": "G",
            "a2": "A",
            "genotype": "AG",
            "call_status": "het_haploid",
        }
    ]
    frame = pl.DataFrame(
        rows,
        schema={
            "rsid": pl.String(),
            "chrom": pl.Enum(CHROM_ORDER),
            "pos_grch37": pl.UInt32(),
            "a1": pl.String(),
            "a2": pl.String(),
            "genotype": pl.String(),
            "call_status": pl.Enum(CALL_STATUS_ORDER),
        },
    )
    assert observed_haploid_alleles(GenotypeTable(frame, vendor="test"), "Y") == {}


def test_indel_alleles_are_dropped() -> None:
    """``I``/``D`` carry no sequence (AGENTS.md 4.2) and neither tree keys on them."""
    assert observed_haploid_alleles(table("Y", {100: "I", 200: "D", 300: "C"}), "Y") == {300: "C"}


def test_the_other_lineage_is_not_read() -> None:
    """An MT tree must not consume chrY rows, and vice versa."""
    assert observed_haploid_alleles(table("Y", {100: "A"}), "MT") == {}


def test_uncertain_support_is_counted_separately() -> None:
    parents = {"root": None, "A": "root"}
    mutations = {"A": [Mutation(100, "G", "A", uncertain=True), Mutation(200, "C", "T")]}
    tree = build_tree("Y", "test", "root", parents, mutations)
    result = call(tree, table("Y", {100: "A", 200: "T"}))
    assert result.path[0].supporting == 2
    assert result.path[0].uncertain_support == 1


def test_build_tree_rejects_a_cycle() -> None:
    with pytest.raises(ValueError, match="cycle"):
        build_tree("Y", "test", "root", {"root": None, "A": "B", "B": "A"}, {})


def test_build_tree_rejects_an_unknown_parent() -> None:
    with pytest.raises(ValueError, match="are not nodes"):
        build_tree("Y", "test", "root", {"root": None, "A": "ghost"}, {})


def test_call_never_repr_leaks_a_genotype() -> None:
    """The path implies derived alleles, so the call must not print them (AGENTS.md 1)."""
    result = call(linear_tree(), table("Y", {100: "A", 200: "T", 300: "C"}))
    text = repr(result)
    # The shape is shown ...
    assert "lineage='Y'" in text
    assert "depth=3" in text
    # ... and the call itself is not: the name and the path each restate the genotypes.
    assert "A1a" not in text
    assert "PathStep" not in text
