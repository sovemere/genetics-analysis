"""Tests for the indel policy (roadmap M1.6, AGENTS.md 4.2)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from genetics.ingest import read_export
from genetics.ingest.indels import (
    IndelPolicy,
    IndelRepresentation,
    excluded_count,
    is_indel_expr,
    matchable,
    matchable_mask,
)
from genetics.ingest.schema import Chrom
from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR


def fixture(name: str = "ancestry_v2_male.txt") -> Path:
    path = DEFAULT_FIXTURE_DIR / name
    if not path.exists():
        pytest.skip("fixtures not generated; run `genetics fixtures`")
    return path


def representation(rsid: str = "rs900000001", source: str = "dbSNP b156") -> IndelRepresentation:
    return IndelRepresentation(
        rsid=rsid,
        chrom=Chrom.CHR1,
        pos_grch37=100_001,
        insertion_allele="CTT",
        deletion_allele="C",
        source=source,
    )


# ---------------------------------------------------------------------------
# The default is exclusion, and that is the correct default
# ---------------------------------------------------------------------------


def test_default_policy_excludes_every_indel() -> None:
    table = read_export(fixture()).table
    kept = matchable(table, IndelPolicy.default())

    assert kept.filter(is_indel_expr()).height == 0
    assert kept.height < table.n_markers


def test_excluded_count_is_the_indel_count_under_the_default() -> None:
    """Surfaced in the coverage-honesty card (M7.6): a section that silently skipped
    thousands of markers would imply a completeness it does not have."""
    table = read_export(fixture()).table
    indels = table.frame.filter(is_indel_expr()).height

    assert indels > 0
    assert excluded_count(table, IndelPolicy.default()) == indels


def test_excluding_from_matching_does_not_remove_from_the_table() -> None:
    """Excluded, not hidden. Per AGENTS.md 0.1A the rule is to label, not to filter."""
    table = read_export(fixture()).table
    assert table.frame.filter(is_indel_expr()).height > 0


def test_no_calls_are_not_excluded_by_the_indel_mask() -> None:
    """Whether a missing genotype means "no card" or "card with a no-data state" is the
    card engine's decision (M3.4). Making it here would turn an absent result into an
    absent card.

    This caught a real fail-open bug. A no-call row has null alleles;
    ``null.is_in([...])`` is null rather than False, and a null predicate matches
    nothing -- so ``~is_indel_expr()`` silently dropped every no-call from the matchable
    set. The indel policy was quietly deciding what happens to missing genotypes.
    """
    table = read_export(fixture("ancestry_v2_high_nocall.txt")).table
    kept = matchable(table, IndelPolicy.default())

    no_calls = table.frame.filter(pl.col("genotype").is_null()).height
    assert no_calls > 0
    assert kept.filter(pl.col("genotype").is_null()).height == no_calls


def test_indel_mask_is_null_safe() -> None:
    """The trap above, isolated: the mask must be False on a null row, never null."""
    frame = read_export(fixture("ancestry_v2_high_nocall.txt")).table.frame
    evaluated = frame.select(is_indel_expr().alias("m")).get_column("m")

    assert evaluated.null_count() == 0


# ---------------------------------------------------------------------------
# The whitelist, and the guard on it
# ---------------------------------------------------------------------------


def test_whitelisted_indel_becomes_matchable() -> None:
    table = read_export(fixture()).table
    an_indel = table.frame.filter(is_indel_expr()).row(0, named=True)
    rsid = str(an_indel["rsid"])

    policy = IndelPolicy.with_whitelist([representation(rsid=rsid)])
    kept = table.frame.filter(matchable_mask(policy))

    assert kept.filter(pl.col("rsid") == rsid).height == 1
    assert excluded_count(table, policy) == excluded_count(table, IndelPolicy.default()) - 1


def test_a_representation_without_a_source_is_refused() -> None:
    """An unsourced mapping is exactly the guess the whitelist exists to avoid.

    ``D`` means "the deletion allele", not "the reference", and for many loci the
    insertion is the reference state -- so an unverified mapping does not fail, it
    silently reports the opposite genotype.
    """
    with pytest.raises(ValueError, match="needs a source"):
        representation(source="")

    with pytest.raises(ValueError, match="needs a source"):
        representation(source="   ")


def test_a_representation_that_resolves_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="resolves nothing"):
        IndelRepresentation(
            rsid="rs900000001",
            chrom=Chrom.CHR1,
            pos_grch37=1,
            insertion_allele="C",
            deletion_allele="C",
            source="dbSNP b156",
        )


def test_duplicate_whitelist_entries_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        IndelPolicy.with_whitelist([representation(), representation()])


def test_policy_allows_reports_membership() -> None:
    policy = IndelPolicy.with_whitelist([representation(rsid="rs900000001")])
    assert policy.allows("rs900000001")
    assert not policy.allows("rs900000002")
    assert not IndelPolicy.default().allows("rs900000001")
