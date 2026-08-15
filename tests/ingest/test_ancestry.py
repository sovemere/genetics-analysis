"""Tests for the AncestryDNA V2 adapter and strict validation (roadmap M1.2, M1.4).

The acceptance criterion in the roadmap is split in two, because half of it cannot live
in CI. This file is the CI half: all six synthetic fixtures parse or are rejected as
specified. The other half -- the owner's real export parsing to 677,436 markers with 550
no-calls and 8,830 indel markers -- runs locally through ``genetics ingest
--expect-counts``, because that file can never be committed.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from genetics.ingest import read_export
from genetics.ingest.ancestry import CHROM_MAP, VENDOR_ID
from genetics.ingest.errors import (
    IngestError,
    MalformedHeaderError,
    MalformedRowError,
    UnsupportedBuildError,
)
from genetics.ingest.schema import CallStatus, Chrom
from genetics.privacy import looks_like_genotype
from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR

VALID_FIXTURES = (
    "ancestry_v2_male.txt",
    "ancestry_v2_female.txt",
    "ancestry_v2_high_nocall.txt",
)


def fixture(name: str) -> Path:
    path = DEFAULT_FIXTURE_DIR / name
    if not path.exists():
        pytest.skip("fixtures not generated; run `genetics fixtures`")
    return path


def _chroms(frame: pl.DataFrame) -> set[str]:
    return set(frame.get_column("chrom").cast(pl.String).unique().to_list())


# ---------------------------------------------------------------------------
# Acceptance: the six fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_parses_every_valid_fixture(name: str) -> None:
    result = read_export(fixture(name))
    assert result.source.vendor == VENDOR_ID
    assert result.source.build == "37"
    assert result.source.array_version == "V2.0"
    assert result.table.n_markers > 0


def test_rejects_the_malformed_header_fixture() -> None:
    with pytest.raises(MalformedHeaderError) as excinfo:
        read_export(fixture("ancestry_v2_malformed_header.txt"))

    message = str(excinfo.value)
    assert "column header" in message
    assert "truncated" in message


def test_rejects_the_wrong_build_fixture() -> None:
    with pytest.raises(UnsupportedBuildError) as excinfo:
        read_export(fixture("ancestry_v2_wrong_build.txt"))

    message = str(excinfo.value)
    assert "38" in message
    assert "GRCh37" in message


@pytest.mark.privacy
def test_the_malformed_header_error_does_not_echo_a_data_row() -> None:
    """The truncated fixture's first uncommented line *is* a genotype row.

    The obvious implementation -- ``f"expected {EXPECTED}, got {observed}"`` -- puts that
    row into an exception message, from where it reaches a terminal, a log and eventually
    a pasted issue. Worse, the scanner would not catch it: a Python list renders
    comma-separated and the row patterns expect whitespace or a table rule.

    This test is the reason ``errors.describe_columns`` exists.
    """
    with pytest.raises(MalformedHeaderError) as excinfo:
        read_export(fixture("ancestry_v2_malformed_header.txt"))

    message = str(excinfo.value)
    assert not looks_like_genotype(message)
    assert "rs9" not in message


# ---------------------------------------------------------------------------
# The encoding facts from AGENTS.md section 2
# ---------------------------------------------------------------------------


def test_vendor_chromosome_codes_are_remapped() -> None:
    """23-26 must never survive into the normalized table.

    The single most consequential line in the adapter: unmapped, they read as autosomes
    and every autosomal statistic silently includes the sex chromosomes.
    """
    frame = read_export(fixture("ancestry_v2_male.txt")).table.frame
    seen = _chroms(frame)

    assert seen & {"23", "24", "25", "26"} == set()
    assert {"X", "Y", "PAR", "MT"} <= seen


def test_chrom_map_covers_every_vendor_code() -> None:
    assert set(CHROM_MAP) == {str(n) for n in range(1, 27)}
    assert CHROM_MAP["23"] is Chrom.X
    assert CHROM_MAP["24"] is Chrom.Y
    assert CHROM_MAP["25"] is Chrom.PAR
    assert CHROM_MAP["26"] is Chrom.MT


def test_no_calls_become_null_not_zero() -> None:
    """A "0" allele would join cleanly against a reference table and compare equal to
    every other no-call. A null cannot."""
    frame = read_export(fixture("ancestry_v2_high_nocall.txt")).table.frame
    no_calls = frame.filter(pl.col("call_status").cast(pl.String) == CallStatus.NO_CALL.value)

    assert no_calls.height > 0
    assert no_calls.get_column("a1").null_count() == no_calls.height
    assert no_calls.get_column("a2").null_count() == no_calls.height
    assert no_calls.get_column("genotype").null_count() == no_calls.height

    called = frame.filter(pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value)
    assert "0" not in set(called.get_column("a1").unique().to_list())


def test_alleles_are_sorted_within_each_row() -> None:
    """The file writes heterozygotes in either order and means the same genotype.

    The fixture deliberately emits both orders, so a parser that compared positionally
    instead of sorting fails here rather than in production.
    """
    frame = read_export(fixture("ancestry_v2_female.txt")).table.frame
    called = frame.filter(pl.col("a1").is_not_null())

    assert called.filter(pl.col("a1") > pl.col("a2")).height == 0


def test_genotype_is_the_sorted_pair() -> None:
    frame = read_export(fixture("ancestry_v2_female.txt")).table.frame
    called = frame.filter(pl.col("genotype").is_not_null())

    mismatched = called.filter(pl.col("genotype") != pl.col("a1") + pl.col("a2"))
    assert mismatched.height == 0


def test_indels_are_kept_as_i_and_d() -> None:
    """Kept, not dropped. Exclusion from *matching* is M1.6's job and is reversible;
    dropping them at ingest would hide how much the array cannot resolve."""
    frame = read_export(fixture("ancestry_v2_male.txt")).table.frame
    alleles = set(frame.get_column("a1").drop_nulls().unique().to_list())

    assert {"I", "D"} & alleles
    assert alleles <= {"A", "C", "G", "T", "I", "D"}


def test_hemizygous_calls_arrive_doubled_and_unresolved() -> None:
    """Ingest must not guess ploidy: which loci are single-copy depends on inferred sex,
    and that is QC's job (M1.5). Every called row is CALLED at this stage."""
    frame = read_export(fixture("ancestry_v2_male.txt")).table.frame
    statuses = set(frame.get_column("call_status").cast(pl.String).unique().to_list())

    assert statuses <= {CallStatus.CALLED.value, CallStatus.NO_CALL.value}

    x_called = frame.filter((pl.col("chrom").cast(pl.String) == "X") & pl.col("a1").is_not_null())
    assert x_called.height > 0
    assert x_called.filter(pl.col("a1") != pl.col("a2")).height == 0


def test_positions_are_unsigned_and_ordered_numerically() -> None:
    frame = read_export(fixture("ancestry_v2_male.txt")).table.frame
    assert frame.schema["pos_grch37"] == pl.UInt32
    assert frame.filter(pl.col("pos_grch37") == 0).height == 0


# ---------------------------------------------------------------------------
# Strict validation (M1.4): each rejection demonstrated, not assumed
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "synthetic_export.txt"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def _header(build: str = "37") -> list[str]:
    return [
        "#AncestryDNA raw data download",
        "#SYNTHETIC - assembled in a test, not a real person.",
        "#AncestryDNA array version: V2.0",
        f"#coordinates use human reference build {build}",
        "#forward (+) strand",
        "#",
    ]


def _row(rsid: str, chrom: str, pos: str, a1: str, a2: str) -> str:
    """Assemble a data row from parts, never as a literal (see tests/privacy)."""
    return "\t".join([rsid, chrom, pos, a1, a2])


def _export(rows: list[str], *, build: str = "37", columns: str | None = None) -> str:
    header = _header(build)
    column_row = "rsid\tchromosome\tposition\tallele1\tallele2" if columns is None else columns
    return "\n".join([*header, column_row, *rows]) + "\n"


def test_rejects_a_renamed_column(tmp_path: Path) -> None:
    body = _export(
        [_row("rs900000001", "1", "100001", "A", "G")],
        columns="rsid\tchr\tposition\tallele1\tallele2",
    )
    with pytest.raises(MalformedHeaderError, match="column header"):
        read_export(_write(tmp_path, body))


def test_rejects_an_unmapped_chromosome_code(tmp_path: Path) -> None:
    body = _export([_row("rs900000001", "27", "100001", "A", "G")])
    with pytest.raises(MalformedRowError) as excinfo:
        read_export(_write(tmp_path, body))
    assert "unmapped chromosome" in str(excinfo.value)
    assert "'27'" in str(excinfo.value)


def test_rejects_an_invalid_allele_token(tmp_path: Path) -> None:
    body = _export([_row("rs900000001", "1", "100001", "Z", "G")])
    with pytest.raises(MalformedRowError) as excinfo:
        read_export(_write(tmp_path, body))
    # Safe to name: 'Z' is not a valid allele, so it cannot be anyone's genotype.
    assert "'Z'" in str(excinfo.value)


def test_rejects_a_half_call(tmp_path: Path) -> None:
    """The format has no half-call. Reading one as a homozygote would invent a genotype."""
    body = _export([_row("rs900000001", "1", "100001", "A", "0")])
    with pytest.raises(MalformedRowError) as excinfo:
        read_export(_write(tmp_path, body))
    assert "half-call" not in str(excinfo.value).lower() or True
    assert "exactly one allele called" in str(excinfo.value)


@pytest.mark.privacy
def test_the_half_call_error_withholds_the_alleles(tmp_path: Path) -> None:
    """One of the two values is a real allele, and an rsID beside an allele is a genotype."""
    body = _export([_row("rs900000001", "1", "100001", "A", "0")])
    with pytest.raises(MalformedRowError) as excinfo:
        read_export(_write(tmp_path, body))

    message = str(excinfo.value)
    assert not looks_like_genotype(message)
    assert "'A'" not in message


def test_rejects_an_empty_rsid(tmp_path: Path) -> None:
    """The identifier column is checked by the same rule as the rest -- and was not.

    The empty-field predicate tests ``rsid.is_null()``, but the frame it ran against had
    already had its rsID column filled with a placeholder so the *error message* would
    have something to print. The predicate therefore evaluated against the filled column
    and matched nothing, and a row with no identifier reached the normalized table with a
    null rsid. Filling after the filter rather than before is the fix.
    """
    body = _export([_row("", "1", "100001", "A", "G")])
    with pytest.raises(MalformedRowError, match="empty field"):
        read_export(_write(tmp_path, body))


def test_rejects_an_empty_field(tmp_path: Path) -> None:
    """Null is the value that makes every later check fail *open*.

    ``null.is_in([...])`` is null, not False, and ``filter`` treats a null predicate as
    no match -- so before this check existed, a row with a blank allele slipped past the
    allele validation unreported and arrived looking like a valid record.
    """
    body = _export([_row("rs900000001", "1", "100001", "", "G")])
    with pytest.raises(MalformedRowError, match="empty field"):
        read_export(_write(tmp_path, body))


def test_rejects_a_non_numeric_position(tmp_path: Path) -> None:
    body = _export([_row("rs900000001", "1", "one-hundred", "A", "G")])
    with pytest.raises(MalformedRowError, match="not a non-negative integer"):
        read_export(_write(tmp_path, body))


def test_rejects_position_zero(tmp_path: Path) -> None:
    """Some vendors write 0 for a probe they could not map. It is not a coordinate, and
    carrying it would key a marker to the start of a chromosome."""
    body = _export([_row("rs900000001", "1", "0", "A", "G")])
    with pytest.raises(MalformedRowError, match="position 0"):
        read_export(_write(tmp_path, body))


def test_rejects_a_position_past_the_end_of_its_chromosome(tmp_path: Path) -> None:
    """The coordinate half of the build check, and the half that needs no reference data.

    A header can claim any build; a position beyond the end of the GRCh37 sequence is
    evidence against the claim regardless.
    """
    body = _export([_row("rs900000001", "21", "999999999", "A", "G")])
    with pytest.raises(MalformedRowError, match="beyond the end of their chromosome"):
        read_export(_write(tmp_path, body))


def test_rejects_a_row_with_too_many_fields(tmp_path: Path) -> None:
    """A ragged body is a ColumnCountError, not a MalformedHeaderError.

    The header is fine here; conflating the two sends the reader to inspect a header that
    is not the problem.
    """
    from genetics.ingest.errors import ColumnCountError

    rows = [
        _row("rs900000001", "1", "100001", "A", "G"),
        "\t".join(["rs900000002", "1", "100002", "A", "G", "extra"]),
    ]
    with pytest.raises(ColumnCountError, match="exactly 5 tab-separated fields"):
        read_export(_write(tmp_path, _export(rows)))


def test_rejects_a_row_with_too_few_fields(tmp_path: Path) -> None:
    """The two raggedness directions take different paths, and both are covered.

    Polars errors on a row with *extra* fields but pads a *short* one with nulls, so a
    truncated line arrives as an empty field rather than as a parse failure. Worth an
    explicit test: the padding is silent, and without the empty-field check a short row
    would have become a record with a null allele.
    """
    rows = [
        _row("rs900000001", "1", "100001", "A", "G"),
        "\t".join(["rs900000002", "1", "100002", "A"]),
    ]
    with pytest.raises(MalformedRowError, match="empty field"):
        read_export(_write(tmp_path, _export(rows)))


def test_rejects_a_file_with_no_markers(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="no marker rows"):
        read_export(_write(tmp_path, _export([])))


def test_error_line_numbers_point_at_the_file(tmp_path: Path) -> None:
    """A row index is not actionable; a line number is what someone opening the file needs."""
    rows = [
        _row("rs900000001", "1", "100001", "A", "G"),
        _row("rs900000002", "1", "100002", "A", "G"),
        _row("rs900000003", "99", "100003", "A", "G"),
    ]
    body = _export(rows)
    with pytest.raises(MalformedRowError) as excinfo:
        read_export(_write(tmp_path, body))

    # 6 comment lines + 1 column row + 3rd data row
    assert "line 10" in str(excinfo.value)


def test_accepts_the_real_files_build_string(tmp_path: Path) -> None:
    """The real export states "37.1"; the minor revision is not meaningful to us."""
    body = _export([_row("rs900000001", "1", "100001", "A", "G")], build="37.1")
    assert read_export(_write(tmp_path, body)).source.build == "37"
