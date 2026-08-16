"""Tests for variant keying and rsID resolution (roadmap M1.7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from genetics.ingest import read_export
from genetics.ingest.keys import (
    LocusKey,
    MergeTable,
    RsidResolutionStatus,
    UnresolvableRsidError,
    VariantKey,
    add_current_rsid,
    locus_keys,
    lookup_loci,
    lookup_rsids,
)
from genetics.ingest.schema import Chrom
from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR


def fixture(name: str = "ancestry_v2_male.txt") -> Path:
    path = DEFAULT_FIXTURE_DIR / name
    if not path.exists():
        pytest.skip("fixtures not generated; run `genetics fixtures`")
    return path


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def test_variant_key_sorts_and_dedupes_alleles() -> None:
    """A/G and G/A are one variant. Normalising once here means no consumer has to
    remember, which is the same reason genotypes are sorted at ingest."""
    assert VariantKey(Chrom.CHR1, 100, ["G", "A"]).alleles == ("A", "G")
    assert VariantKey(Chrom.CHR1, 100, ["A", "G"]) == VariantKey(Chrom.CHR1, 100, ["G", "A"])
    assert VariantKey(Chrom.CHR1, 100, ["a", "A", "g"]).alleles == ("A", "G")


def test_variant_key_requires_alleles() -> None:
    with pytest.raises(ValueError, match="needs alleles"):
        VariantKey(Chrom.CHR1, 100, [])


def test_variant_key_exposes_its_locus() -> None:
    """The sample side can only offer a locus: an export records the two alleles observed,
    so a homozygote reveals only one of them and no complete allele key exists."""
    key = VariantKey(Chrom.X, 500, ["A", "T"])
    assert key.locus == LocusKey(Chrom.X, 500)
    assert str(key) == "X:500:A/T"


def test_locus_keys_are_hashable_and_ordered() -> None:
    keys = {LocusKey(Chrom.CHR2, 5), LocusKey(Chrom.CHR1, 9), LocusKey(Chrom.CHR1, 9)}
    assert len(keys) == 2
    assert sorted(keys)[0] == LocusKey(Chrom.CHR1, 9)


def test_locus_keys_frame_has_one_row_per_marker() -> None:
    table = read_export(fixture()).table
    assert locus_keys(table).height == table.n_markers


# ---------------------------------------------------------------------------
# The merge table -- why rsID is a secondary key
# ---------------------------------------------------------------------------


def test_empty_merge_table_is_the_identity() -> None:
    """The correct behaviour before M2 fetches dbSNP: unknown rsIDs resolve to themselves,
    not to nothing."""
    table = MergeTable.empty()
    assert table.resolve("rs1815739") == "rs1815739"
    assert len(table) == 0


def test_resolves_a_single_merge() -> None:
    table = MergeTable.from_pairs([("rs111", "rs222")])
    assert table.resolve("rs111") == "rs222"
    assert table.resolve("rs222") == "rs222"


def test_follows_a_merge_chain_transitively() -> None:
    """dbSNP merges in sequence, so a retired ID can point at another retired ID."""
    table = MergeTable.from_pairs([("rs111", "rs222"), ("rs222", "rs333")])
    assert table.resolve("rs111") == "rs333"


def test_a_cycle_does_not_hang() -> None:
    """ "Should not exist in the input" is a poor reason for an infinite loop in a parser,
    and this table is loaded from a fetched file nobody here controls."""
    table = MergeTable.from_pairs([("rs111", "rs222"), ("rs222", "rs111")])
    with pytest.raises(UnresolvableRsidError) as first:
        table.resolve("rs111")
    with pytest.raises(UnresolvableRsidError) as second:
        table.resolve("rs222")
    assert first.value.resolution.status is RsidResolutionStatus.CYCLE
    assert second.value.resolution.status is RsidResolutionStatus.CYCLE


def test_an_ambiguous_chain_is_not_mistaken_for_an_identity() -> None:
    table = MergeTable(
        {"rs111": "rs222"},
        {
            "rs222": (
                RsidResolutionStatus.MULTIPLE_CURRENT_TARGETS,
                ("rs333", "rs444"),
            )
        },
    )
    with pytest.raises(UnresolvableRsidError) as error:
        table.resolve("rs111")
    assert error.value.resolution.targets == ("rs333", "rs444")


def test_unknown_rsid_is_not_an_error() -> None:
    """An export legitimately contains rsIDs a given dbSNP subset does not mention."""
    table = MergeTable.from_pairs([("rs111", "rs222")])
    assert table.resolve("rs999") == "rs999"


def test_resolve_all_maps_every_input() -> None:
    table = MergeTable.from_pairs([("rs111", "rs222")])
    assert table.resolve_all(["rs111", "rs999"]) == {"rs111": "rs222", "rs999": "rs999"}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def test_add_current_rsid_preserves_the_original() -> None:
    """A card citing a retired ID should still be able to show which marker it matched.
    Overwriting would erase the provenance the merge table exists to supply."""
    table = read_export(fixture()).table
    original = table.frame.get_column("rsid").to_list()[:5]

    merges = MergeTable.from_pairs([(original[0], "rs999999999")])
    frame = add_current_rsid(table, merges)

    assert frame.get_column("rsid").to_list()[:5] == original
    assert frame.get_column("rsid_current").to_list()[0] == "rs999999999"
    assert frame.get_column("rsid_current").to_list()[1] == original[1]


def test_an_unresolvable_rsid_in_the_export_is_null_not_an_abort_and_not_an_identity() -> None:
    """The third answer.

    b157 carries ~23k retired IDs with zero or several current targets. Raising over one
    of them would refuse to read a 677k-row export the user did not author; writing the
    original back would assert the retired ID is current, which is the false identity
    ``resolve()`` raises to prevent. Null is neither, and it propagates.
    """
    table = read_export(fixture()).table
    original = table.frame.get_column("rsid").to_list()[:3]
    merges = MergeTable(
        {original[1]: "rs999999999"},
        {original[0]: (RsidResolutionStatus.MULTIPLE_CURRENT_TARGETS, ("rs1", "rs2"))},
    )

    frame = add_current_rsid(table, merges)

    current = frame.get_column("rsid_current").to_list()
    assert current[0] is None
    assert current[1] == "rs999999999"
    assert current[2] == original[2]
    assert frame.get_column("rsid").to_list()[:3] == original


def test_add_current_rsid_does_not_change_the_normalized_schema() -> None:
    """The normalized table stays the single contract; keying returns a plain frame."""
    from genetics.ingest.schema import COLUMNS

    table = read_export(fixture()).table
    frame = add_current_rsid(table, MergeTable.empty())

    assert tuple(frame.columns) == (*COLUMNS, "rsid_current")
    assert tuple(table.frame.columns) == COLUMNS


def test_lookup_loci_returns_the_requested_positions() -> None:
    table = read_export(fixture()).table
    rows = table.frame.head(3).to_dicts()
    keys = [LocusKey(Chrom(str(r["chrom"])), int(r["pos_grch37"])) for r in rows]

    found = lookup_loci(table, keys)
    assert found.height == 3
    assert set(found.get_column("rsid").to_list()) == {str(r["rsid"]) for r in rows}


def test_lookup_loci_accepts_a_one_shot_iterable() -> None:
    """The signature says Iterable, so a generator must work.

    Two column comprehensions each consumed the argument; a generator was exhausted by
    the first, leaving the second empty. It surfaced as a ShapeError about mismatched
    column heights -- nothing resembling the actual mistake.
    """
    table = read_export(fixture()).table
    rows = table.frame.head(3).to_dicts()
    keys = [LocusKey(Chrom(str(r["chrom"])), int(r["pos_grch37"])) for r in rows]

    assert lookup_loci(table, iter(keys)).height == 3
    assert lookup_loci(table, (k for k in keys)).height == 3


def test_lookup_loci_on_an_absent_position_returns_nothing() -> None:
    table = read_export(fixture()).table
    assert lookup_loci(table, [LocusKey(Chrom.CHR1, 999_999_99)]).height == 0


def test_lookup_rsids_resolves_a_retired_query_id() -> None:
    """The common case: the export predates the merge, so resolution must run on both
    sides. Resolving only the query would miss it."""
    table = read_export(fixture()).table
    present = str(table.frame.get_column("rsid").to_list()[0])

    merges = MergeTable.from_pairs([("rs800000001", present)])
    found = lookup_rsids(table, ["rs800000001"], merges)

    assert found.height == 1
    assert found.get_column("rsid").to_list() == [present]


def test_lookup_rsids_without_merges_is_a_plain_lookup() -> None:
    table = read_export(fixture()).table
    present = str(table.frame.get_column("rsid").to_list()[0])

    assert lookup_rsids(table, [present]).height == 1
    assert lookup_rsids(table, ["rs800000001"]).height == 0
