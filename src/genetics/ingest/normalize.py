"""Shared row normalization: raw vendor columns in, normalized table out.

Every adapter funnels through :func:`normalize_rows`. That is deliberate -- the encoding
facts in AGENTS.md section 2 (unordered alleles, ``0 0`` no-calls, ``I``/``D`` indels) are
vendor-independent enough that re-implementing them per adapter would mean re-making the
same mistake per adapter. What differs between vendors is the *layout*: which columns
exist, how chromosomes are spelled, whether the genotype is one field or two. Adapters own
that; this module owns the rest.

Validation is done with whole-column Polars expressions rather than a Python loop, so a
677k-row file is checked in one pass. Each check answers two questions -- *how many rows
are bad* and *which is the first* -- because "some rows are malformed" is not actionable
and "line 59 is malformed" is.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from genetics.ingest.errors import EmptyExportError, MalformedRowError
from genetics.ingest.schema import (
    CALL_STATUS_ORDER,
    CHROM_ORDER,
    NO_CALL_TOKEN,
    VALID_ALLELES,
    CallStatus,
    Chrom,
)

RAW_COLUMNS = ("rsid", "chrom", "pos", "a1", "a2")
"""What an adapter hands over: five String columns, unvalidated, vendor-spelled."""

_ALLELE_TOKENS = sorted(VALID_ALLELES | {NO_CALL_TOKEN})

GRCH37_LENGTHS: Mapping[Chrom, int] = {
    Chrom.CHR1: 249_250_621,
    Chrom.CHR2: 243_199_373,
    Chrom.CHR3: 198_022_430,
    Chrom.CHR4: 191_154_276,
    Chrom.CHR5: 180_915_260,
    Chrom.CHR6: 171_115_067,
    Chrom.CHR7: 159_138_663,
    Chrom.CHR8: 146_364_022,
    Chrom.CHR9: 141_213_431,
    Chrom.CHR10: 135_534_747,
    Chrom.CHR11: 135_006_516,
    Chrom.CHR12: 133_851_895,
    Chrom.CHR13: 115_169_878,
    Chrom.CHR14: 107_349_540,
    Chrom.CHR15: 102_531_392,
    Chrom.CHR16: 90_354_753,
    Chrom.CHR17: 81_195_210,
    Chrom.CHR18: 78_077_248,
    Chrom.CHR19: 59_128_983,
    Chrom.CHR20: 63_025_520,
    Chrom.CHR21: 48_129_895,
    Chrom.CHR22: 51_304_566,
    Chrom.X: 155_270_560,
    Chrom.Y: 59_373_566,
    Chrom.PAR: 155_270_560,
    Chrom.MT: 16_569,
}
"""Public GRCh37 (hg19) sequence lengths. Used as a coordinate sanity bound, not as
biology: a position past the end of its chromosome is not a build-37 coordinate, whatever
the header claims. PAR is bounded by X because that is where its coordinates live."""


def _first_bad(frame: pl.DataFrame, predicate: pl.Expr) -> tuple[int, int, str] | None:
    """Return ``(count, row_index, rsid)`` for the first row matching ``predicate``.

    Pulls only the row index and the rsID out of the frame. Neither is genotype data, and
    taking the whole row would put alleles one ``f"{row}"`` away from an error message.
    """
    bad = frame.filter(predicate).select("_row", "rsid")
    if bad.height == 0:
        return None
    return bad.height, int(bad.item(0, "_row")), str(bad.item(0, "rsid"))


def normalize_rows(
    raw: pl.DataFrame,
    *,
    chrom_map: Mapping[str, Chrom],
    source_name: str,
    header_lines: int,
) -> pl.DataFrame:
    """Validate and normalize raw vendor columns into the shape in
    :data:`~genetics.ingest.schema.NORMALIZED_SCHEMA`.

    ``chrom_map`` translates the vendor's chromosome spelling. Passing it in rather than
    inferring it is the point of the seam: the AncestryDNA layout writes ``23``-``26`` for
    the sex chromosomes and mitochondrion, other vendors write letters, and no analysis
    module should ever see either.

    ``header_lines`` lets a row index become a *file line number*, which is what someone
    opening the file in an editor actually needs.
    """
    missing = [c for c in RAW_COLUMNS if c not in raw.columns]
    if missing:
        raise MalformedRowError(
            f"{source_name}: adapter produced no {', '.join(missing)} column. "
            f"Raw frames must have exactly {list(RAW_COLUMNS)}."
        )

    if raw.height == 0:
        raise EmptyExportError(
            f"{source_name}: the header parsed but the file contains no marker rows. "
            "A truncated download is the usual cause."
        )

    def line_of(row_index: int) -> int:
        """1-based line in the original file."""
        return header_lines + row_index + 1

    frame = raw.with_row_index("_row").with_columns(
        pl.col("rsid").str.strip_chars(),
        _chrom_raw=pl.col("chrom").str.strip_chars(),
        _pos_raw=pl.col("pos").str.strip_chars(),
        _a1=pl.col("a1").str.strip_chars().str.to_uppercase(),
        _a2=pl.col("a2").str.strip_chars().str.to_uppercase(),
    )

    # --- empty fields -----------------------------------------------------
    # Checked first, and explicitly, because null is the one value that makes every
    # later check fail *open*: `null.is_in([...])` is null, not False, and `filter`
    # treats a null predicate as no match -- so a row with an empty allele would slip
    # past the allele check unreported and arrive as a plausible-looking record. Polars
    # reads an empty CSV field as null by default, so this is reachable from any file
    # with a trailing tab.
    empty = pl.any_horizontal(
        pl.col("rsid").is_null(),
        pl.col("_chrom_raw").is_null(),
        pl.col("_pos_raw").is_null(),
        pl.col("_a1").is_null(),
        pl.col("_a2").is_null(),
    )
    hit = _first_bad(frame.with_columns(rsid=pl.col("rsid").fill_null("<missing>")), empty)
    if hit is not None:
        count, row, rsid = hit
        raise MalformedRowError(
            f"{source_name}: {count} row(s) have an empty field. First at line "
            f"{line_of(row)} ({rsid}). Every column is required; a blank one usually "
            "means a stray tab or a truncated line."
        )

    # --- chromosome -------------------------------------------------------
    frame = frame.with_columns(
        _chrom=pl.col("_chrom_raw").replace_strict(
            {vendor: chrom.value for vendor, chrom in chrom_map.items()},
            default=None,
            return_dtype=pl.String,
        )
    )
    hit = _first_bad(frame, pl.col("_chrom").is_null())
    if hit is not None:
        count, row, rsid = hit
        seen = sorted(
            {
                str(v)
                for v in frame.filter(pl.col("_chrom").is_null())
                .get_column("_chrom_raw")
                .unique()
                .to_list()
            }
        )
        raise MalformedRowError(
            f"{source_name}: {count} row(s) carry an unmapped chromosome code. "
            f"First at line {line_of(row)} ({rsid}). Unmapped codes: {seen}. "
            f"This adapter maps {sorted(chrom_map)}. Never pass a vendor code through "
            "unmapped -- 23-26 read as autosomes corrupts every autosomal statistic."
        )

    # --- position ---------------------------------------------------------
    # strict=False so a non-numeric field becomes null and is reported with a line
    # number, rather than raising a Polars ComputeError that names no row.
    frame = frame.with_columns(_pos=pl.col("_pos_raw").cast(pl.UInt32, strict=False))

    hit = _first_bad(frame, pl.col("_pos").is_null())
    if hit is not None:
        count, row, rsid = hit
        raise MalformedRowError(
            f"{source_name}: {count} row(s) have a position that is not a non-negative "
            f"integer. First at line {line_of(row)} ({rsid})."
        )

    hit = _first_bad(frame, pl.col("_pos") == 0)
    if hit is not None:
        count, row, rsid = hit
        raise MalformedRowError(
            f"{source_name}: {count} row(s) sit at position 0, which is not a coordinate. "
            f"First at line {line_of(row)} ({rsid}). Some vendors use 0 for probes they "
            "could not map; those markers cannot be keyed to a reference and must be "
            "dropped by the adapter explicitly, not carried as position 0."
        )

    bounds = pl.coalesce(
        [
            pl.when(pl.col("_chrom") == chrom.value).then(pl.lit(length, dtype=pl.UInt32))
            for chrom, length in GRCH37_LENGTHS.items()
        ]
    )
    hit = _first_bad(frame.with_columns(_max=bounds), pl.col("_pos") > pl.col("_max"))
    if hit is not None:
        count, row, rsid = hit
        raise MalformedRowError(
            f"{source_name}: {count} position(s) fall beyond the end of their chromosome "
            f"in GRCh37. First at line {line_of(row)} ({rsid}). The file is not on the "
            "build it claims; parsing it as GRCh37 would place every variant at the wrong "
            "locus (AGENTS.md 6)."
        )

    # --- alleles ----------------------------------------------------------
    valid = pl.col("_a1").is_in(_ALLELE_TOKENS) & pl.col("_a2").is_in(_ALLELE_TOKENS)
    hit = _first_bad(frame, ~valid)
    if hit is not None:
        count, row, rsid = hit
        offenders = sorted(
            {
                str(v)
                for column in ("_a1", "_a2")
                for v in frame.get_column(column).unique().to_list()
                if v is not None and v not in _ALLELE_TOKENS
            }
        )
        # Safe to name: by definition these are not valid alleles, so they are not
        # anyone's genotype. A valid allele would never reach this branch.
        raise MalformedRowError(
            f"{source_name}: {count} row(s) contain an allele token outside "
            f"{_ALLELE_TOKENS}. First at line {line_of(row)} ({rsid}). "
            f"Unexpected tokens: {offenders}."
        )

    no_call = (pl.col("_a1") == NO_CALL_TOKEN) & (pl.col("_a2") == NO_CALL_TOKEN)
    half_call = (pl.col("_a1") == NO_CALL_TOKEN) != (pl.col("_a2") == NO_CALL_TOKEN)

    hit = _first_bad(frame, half_call)
    if hit is not None:
        count, row, rsid = hit
        # The values are withheld on purpose: one of them is a real allele, and an rsID
        # beside an allele is a genotype (AGENTS.md 1.3).
        raise MalformedRowError(
            f"{source_name}: {count} row(s) have exactly one allele called and the other "
            f"not. First at line {line_of(row)} ({rsid}). The format has no half-call: "
            "either both columns are the no-call token or neither is."
        )

    # --- sort the pair ----------------------------------------------------
    # AGENTS.md section 2: the file writes heterozygotes in either order and means the
    # same genotype. Sorting once here is what keeps every consumer from having to
    # remember; a positional comparison downstream is then simply unable to go wrong.
    ordered = pl.col("_a1") <= pl.col("_a2")
    lo = pl.when(ordered).then(pl.col("_a1")).otherwise(pl.col("_a2"))
    hi = pl.when(ordered).then(pl.col("_a2")).otherwise(pl.col("_a1"))

    return frame.select(
        pl.col("rsid"),
        pl.col("_chrom").cast(pl.Enum(CHROM_ORDER)).alias("chrom"),
        pl.col("_pos").alias("pos_grch37"),
        # No-call alleles are null, never "0". A "0" would join against a reference table
        # and compare equal to every other no-call; a null cannot.
        pl.when(no_call).then(None).otherwise(lo).alias("a1"),
        pl.when(no_call).then(None).otherwise(hi).alias("a2"),
        pl.when(no_call).then(None).otherwise(lo + hi).alias("genotype"),
        pl.when(no_call)
        .then(pl.lit(CallStatus.NO_CALL.value))
        .otherwise(pl.lit(CallStatus.CALLED.value))
        .cast(pl.Enum(CALL_STATUS_ORDER))
        .alias("call_status"),
    )
