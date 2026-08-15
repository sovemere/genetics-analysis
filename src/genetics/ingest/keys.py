"""Variant keying and rsID resolution (roadmap M1.7, AGENTS.md section 2).

**rsIDs are not stable identifiers.** dbSNP merges records when two submitted variants
turn out to be the same, and the loser is retired: it still appears in an export produced
before the merge, but it is absent from any reference built after. A card keyed on the
retired ID silently matches nothing, and "no result" is indistinguishable from "no
variant" unless something knows about the merge. That is what :class:`MergeTable` is for.

So the primary key is positional -- ``(chrom, pos_grch37, alleles)`` -- and the rsID is a
secondary index. Position plus alleles is what reference data actually agrees on.

Two shapes, and the distinction matters:

* :class:`LocusKey` -- ``(chrom, pos)``. What a *sample* offers. An export records the two
  alleles observed, not the full allele set at the locus, so a homozygote reveals only one
  of them and the sample side cannot construct a complete allele key.
* :class:`VariantKey` -- ``(chrom, pos, alleles)``. What a *card or reference row* offers,
  where the allele set is known.

Matching therefore joins on locus and checks allele compatibility separately. That
separation is also where M3.2's strand check belongs: the vendor claims forward-strand
calls, but an A/T or C/G site is its own complement, so a strand flip there is invisible
to any comparison of the letters alone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import polars as pl

from genetics.ingest.schema import Chrom, GenotypeTable


@dataclass(frozen=True, order=True)
class LocusKey:
    """A genomic position. What a sample can offer as a join key."""

    chrom: Chrom
    pos_grch37: int

    def __str__(self) -> str:
        return f"{self.chrom.value}:{self.pos_grch37}"


@dataclass(frozen=True)
class VariantKey:
    """A position plus its allele set. The primary key for reference data and cards.

    Alleles are sorted at construction, for the same reason genotypes are sorted at
    ingest: ``A/G`` and ``G/A`` are one variant, and normalising once here means no
    consumer has to remember that.
    """

    chrom: Chrom
    pos_grch37: int
    alleles: tuple[str, ...]

    def __init__(self, chrom: Chrom, pos_grch37: int, alleles: Iterable[str]) -> None:
        normalized = tuple(sorted({a.strip().upper() for a in alleles}))
        if not normalized:
            raise ValueError(f"{chrom.value}:{pos_grch37}: a variant key needs alleles")
        object.__setattr__(self, "chrom", chrom)
        object.__setattr__(self, "pos_grch37", pos_grch37)
        object.__setattr__(self, "alleles", normalized)

    @property
    def locus(self) -> LocusKey:
        return LocusKey(self.chrom, self.pos_grch37)

    def __str__(self) -> str:
        return f"{self.chrom.value}:{self.pos_grch37}:{'/'.join(self.alleles)}"


class MergeTable:
    """Retired rsID to current rsID, from dbSNP's merge records.

    Chains are followed transitively -- dbSNP merges in sequence, so a retired ID can
    point at another retired ID -- with a visited set guarding against a cycle. A cycle
    should not exist in a well-formed dbSNP release, but "should not exist in the input"
    is a poor reason for an infinite loop in a parser, and this table is loaded from a
    fetched file that no one in this project controls.

    The empty table is the identity, which is the correct behaviour before M2 fetches
    dbSNP: unknown rsIDs resolve to themselves rather than to nothing.
    """

    def __init__(self, merges: Mapping[str, str] | None = None) -> None:
        self._merges = dict(merges or {})

    def __len__(self) -> int:
        return len(self._merges)

    @classmethod
    def empty(cls) -> MergeTable:
        return cls()

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, str]]) -> MergeTable:
        """Build from ``(retired_rsid, current_rsid)`` pairs."""
        return cls({retired: current for retired, current in pairs})

    def resolve(self, rsid: str) -> str:
        """Follow the merge chain to the current rsID.

        Returns ``rsid`` unchanged when it is not merged -- including when the table is
        empty. An unknown identifier is not an error here: an export legitimately contains
        rsIDs that a given dbSNP subset does not mention.
        """
        seen = {rsid}
        current = rsid
        while (nxt := self._merges.get(current)) is not None:
            if nxt in seen:
                # A cycle. Stop where we entered it rather than picking arbitrarily; the
                # caller gets a stable answer and the merge file gets flagged in M2.
                return rsid
            seen.add(nxt)
            current = nxt
        return current

    def resolve_all(self, rsids: Iterable[str]) -> dict[str, str]:
        return {rsid: self.resolve(rsid) for rsid in rsids}


def locus_keys(table: GenotypeTable) -> pl.DataFrame:
    """``(chrom, pos_grch37)`` for every row, in table order."""
    return table.frame.select("chrom", "pos_grch37")


def add_current_rsid(table: GenotypeTable, merges: MergeTable) -> pl.DataFrame:
    """Return the frame with a ``rsid_current`` column resolved through ``merges``.

    Added as a *new* column rather than rewriting ``rsid``: the original identifier is
    what the export actually said, and a card citing a retired ID should still be able to
    show that this is the marker it matched. Overwriting would erase the provenance the
    merge table exists to supply.

    The normalized table's own schema is untouched -- this returns a plain frame, so
    :data:`~genetics.ingest.schema.NORMALIZED_SCHEMA` stays the single contract.
    """
    if len(merges) == 0:
        return table.frame.with_columns(pl.col("rsid").alias("rsid_current"))

    mapping = merges.resolve_all(table.frame.get_column("rsid").unique().to_list())
    changed = {old: new for old, new in mapping.items() if old != new}
    if not changed:
        return table.frame.with_columns(pl.col("rsid").alias("rsid_current"))

    return table.frame.with_columns(pl.col("rsid").replace(changed).alias("rsid_current"))


def lookup_loci(
    table: GenotypeTable,
    keys: Iterable[LocusKey],
) -> pl.DataFrame:
    """Rows of ``table`` at the given loci.

    A join rather than a Python loop: at 677k rows against a knowledge pack of any size,
    per-key filtering is quadratic in the worst case and a join is not.
    """
    # Materialised once. The two column comprehensions below each consume ``keys``, so a
    # generator -- which the ``Iterable`` annotation invites -- was exhausted by the first
    # and left the second empty, surfacing as a ShapeError about mismatched column heights
    # rather than as anything resembling the actual mistake.
    materialised = list(keys)

    wanted = pl.DataFrame(
        {
            "chrom": [k.chrom.value for k in materialised],
            "pos_grch37": [k.pos_grch37 for k in materialised],
        },
        schema={"chrom": pl.String, "pos_grch37": pl.UInt32},
    )
    return table.frame.with_columns(pl.col("chrom").cast(pl.String)).join(
        wanted, on=["chrom", "pos_grch37"], how="inner"
    )


def lookup_rsids(
    table: GenotypeTable,
    rsids: Iterable[str],
    merges: MergeTable | None = None,
) -> pl.DataFrame:
    """Rows matching any of ``rsids``, resolving retired identifiers through ``merges``.

    Resolution runs on *both* sides. Resolving only the query would miss an export that
    predates the merge -- which is the common case, since the export is fixed at the date
    it was generated and the reference keeps moving.
    """
    table_merges = merges or MergeTable.empty()
    frame = add_current_rsid(table, table_merges)
    wanted = {table_merges.resolve(r) for r in rsids}
    return frame.filter(pl.col("rsid_current").is_in(list(wanted)))
