"""Tests for the normalized table contract (roadmap M1.1)."""

from __future__ import annotations

import polars as pl
import pytest

from genetics.ingest.schema import (
    AUTOSOMES,
    CHROM_ORDER,
    COLUMNS,
    NORMALIZED_SCHEMA,
    CallStatus,
    Chrom,
    GenotypeTable,
    SchemaError,
    empty_frame,
    validate_frame,
)


def _one_row() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "rsid": ["rs900000001"],
            "chrom": ["1"],
            "pos_grch37": [12345],
            "a1": ["A"],
            "a2": ["G"],
            "genotype": ["AG"],
            "call_status": [CallStatus.CALLED.value],
        },
        schema=NORMALIZED_SCHEMA,
    )


# ---------------------------------------------------------------------------
# The chromosome enum -- the point of M1.1
# ---------------------------------------------------------------------------


def test_chromosome_enum_has_no_vendor_codes() -> None:
    """23-26 must not exist as members. This is the whole guarantee.

    An enum that merely *maps* 23 to X still lets 23 through as a value; one that has no
    such member cannot. Downstream `chrom <= 22` filters are then unable to silently
    swallow the sex chromosomes.
    """
    values = {c.value for c in Chrom}
    assert values & {"23", "24", "25", "26"} == set()
    assert {"X", "Y", "PAR", "MT"} <= values


def test_autosomes_are_exactly_one_to_twentytwo() -> None:
    assert [c.value for c in AUTOSOMES] == [str(n) for n in range(1, 23)]
    assert Chrom.X.is_autosome is False
    assert Chrom.PAR.is_autosome is False
    assert Chrom.MT.is_autosome is False


def test_par_is_distinct_from_x() -> None:
    """Folding PAR into X would give every male a nonzero X heterozygosity and blunt the
    one signal that separates the sexes cleanly (M1.5)."""
    assert len({Chrom.PAR, Chrom.X}) == 2
    assert CHROM_ORDER.count(Chrom.PAR.value) == 1
    assert CHROM_ORDER.count(Chrom.X.value) == 1


def test_enum_dtype_rejects_a_vendor_code() -> None:
    """A leaked '23' must fail at construction, not become a plausible-looking result."""
    with pytest.raises(pl.exceptions.PolarsError):
        pl.DataFrame({"chrom": ["23"]}, schema={"chrom": pl.Enum(CHROM_ORDER)})


def test_chrom_order_is_biological() -> None:
    assert CHROM_ORDER[:3] == ("1", "2", "3")
    assert CHROM_ORDER[-4:] == ("X", "Y", "PAR", "MT")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_columns_match_agents_md_section_2() -> None:
    assert COLUMNS == ("rsid", "chrom", "pos_grch37", "a1", "a2", "genotype", "call_status")


def test_validate_accepts_a_conforming_frame() -> None:
    validate_frame(_one_row())
    validate_frame(empty_frame())


def test_validate_rejects_a_missing_column() -> None:
    with pytest.raises(SchemaError, match="columns must be exactly"):
        validate_frame(_one_row().drop("genotype"))


def test_validate_rejects_reordered_columns() -> None:
    reordered = _one_row().select(
        "chrom", "rsid", "pos_grch37", "a1", "a2", "genotype", "call_status"
    )
    with pytest.raises(SchemaError, match="columns must be exactly"):
        validate_frame(reordered)


def test_validate_rejects_a_wrong_dtype() -> None:
    """A String position would silently sort lexicographically -- 100 before 99."""
    wrong = _one_row().with_columns(pl.col("pos_grch37").cast(pl.String))
    with pytest.raises(SchemaError, match="dtypes are wrong"):
        validate_frame(wrong)


def test_genotype_table_validates_on_construction() -> None:
    with pytest.raises(SchemaError):
        GenotypeTable(_one_row().drop("a1"), vendor="x")


# ---------------------------------------------------------------------------
# Privacy: the reason GenotypeTable exists at all
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_genotype_table_repr_shows_no_data() -> None:
    """A bare Polars frame prints rows. That is the whole reason for the wrapper."""
    table = GenotypeTable(_one_row(), vendor="ancestrydna_v2")
    text = repr(table)

    assert "n_markers=1" in text
    assert "rs900000001" not in text
    assert "AG" not in text


@pytest.mark.privacy
def test_bare_frame_repr_would_have_leaked() -> None:
    """Demonstrates the threat rather than asserting it away.

    A guard that has never been shown the thing it guards against is not evidence of
    anything (the M0 review's closing lesson). This asserts the unwrapped frame really
    does print genotype content, so the previous test is known to be testing something.
    """
    from genetics.privacy import looks_like_genotype

    assert "rs900000001" in repr(_one_row())
    assert looks_like_genotype(repr(_one_row()))


def test_filter_chrom_selects_by_enum() -> None:
    table = GenotypeTable(_one_row(), vendor="x")
    assert table.filter_chrom(Chrom.CHR1).height == 1
    assert table.filter_chrom(Chrom.X).height == 0
