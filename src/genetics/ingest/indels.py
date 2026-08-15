"""Indel policy (roadmap M1.6, AGENTS.md 4.2).

8,830 markers on the V2 array are coded ``I`` or ``D`` and **the inserted or deleted
sequence is not recorded**. That is the whole problem. ``D`` means "the deletion allele",
not "the reference", and for many loci the insertion is the reference state -- so mapping
``I``/``D`` onto a ClinVar or dbSNP REF/ALT pair from the file alone is guesswork. A wrong
guess does not fail; it silently reports the opposite genotype, which for a pathogenic
indel is the difference between "carrier" and "clear".

So the default is **exclude**, and the escape hatch is narrow: an explicit whitelist where
each entry names a *verified* rsID-to-representation mapping and the source that verified
it. :attr:`IndelRepresentation.source` is not decorative -- an entry without one is
refused at construction, because an unsourced mapping is exactly the guess this module
exists to prevent.

Excluding is not hiding. Indel markers stay in the normalized table, are counted in the QC
report, and remain visible; what they are excluded from is *allele matching*. Per
AGENTS.md 0.1A the rule is to label, not to filter, and a card that would rest on an
unresolvable indel should say that rather than silently vanish.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import polars as pl

from genetics.ingest.schema import INDEL_ALLELES, Chrom, GenotypeTable


@dataclass(frozen=True)
class IndelRepresentation:
    """A verified mapping from a vendor ``I``/``D`` code to actual sequence.

    ``insertion_allele`` and ``deletion_allele`` are written in the reference's own
    representation (typically the anchor base plus the inserted sequence, and the anchor
    base alone), so a card can compare against ClinVar without re-deriving anything.
    """

    rsid: str
    chrom: Chrom
    pos_grch37: int
    insertion_allele: str
    deletion_allele: str
    source: str
    """Where the mapping was verified -- a dbSNP build, a ClinVar accession, a paper.
    Required. See the module docstring."""

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError(
                f"{self.rsid}: an indel whitelist entry needs a source recording where "
                "its representation was verified. An unsourced mapping is the guess this "
                "whitelist exists to avoid (AGENTS.md 4.2)."
            )
        if self.insertion_allele == self.deletion_allele:
            raise ValueError(
                f"{self.rsid}: insertion and deletion alleles are identical, so the "
                "mapping resolves nothing."
            )


@dataclass(frozen=True)
class IndelPolicy:
    """How allele matching should treat ``I``/``D`` markers.

    The default -- an empty whitelist -- excludes every indel. That is the correct
    starting point, not a placeholder: no indel is matchable until someone has verified
    its representation against a reference.
    """

    whitelist: Mapping[str, IndelRepresentation]

    @classmethod
    def default(cls) -> IndelPolicy:
        """Exclude all indels from allele matching (AGENTS.md 4.2)."""
        return cls(whitelist={})

    @classmethod
    def with_whitelist(cls, entries: Iterable[IndelRepresentation]) -> IndelPolicy:
        """Allow the named indels, keyed by rsID."""
        mapping: dict[str, IndelRepresentation] = {}
        for entry in entries:
            if entry.rsid in mapping:
                raise ValueError(f"duplicate indel whitelist entry for {entry.rsid}")
            mapping[entry.rsid] = entry
        return cls(whitelist=mapping)

    def allows(self, rsid: str) -> bool:
        return rsid in self.whitelist


def is_indel_expr() -> pl.Expr:
    """True on rows whose alleles are the vendor's ``I``/``D`` codes.

    ``fill_null(False)`` is load-bearing, not defensive tidying. A no-call row has null
    alleles, ``null.is_in([...])`` evaluates to null rather than False, and a null
    predicate matches nothing -- so ``~is_indel_expr()`` silently dropped **every
    no-call** from the matchable set. The indel policy would have been quietly deciding
    what happens to missing genotypes, which is the card engine's call (M3.4), and a
    marker with no data would have become a marker with no card.

    A no-call is not an indel here for a reason beyond the null: the vendor writes ``0 0``
    for an uncalled marker whatever its type, so the file does not record that an
    uncalled marker was I/D coded. That information is genuinely absent, not discarded.
    """
    indels = list(INDEL_ALLELES)
    return pl.col("a1").is_in(indels).fill_null(False) | pl.col("a2").is_in(indels).fill_null(False)


def matchable_mask(policy: IndelPolicy) -> pl.Expr:
    """Rows eligible for allele matching under ``policy``.

    **M3.2 must apply this before comparing alleles.** It is the single place the indel
    rule is enforced; a matcher that filters indels itself will drift from the policy the
    first time the whitelist grows.

    No-calls are *not* excluded here. Whether a missing genotype means "no card" or "card
    with a no-data state" is the card engine's decision (M3.4), and making it here would
    quietly turn an absent result into an absent card.
    """
    allowed = list(policy.whitelist)
    if not allowed:
        return ~is_indel_expr()
    return ~is_indel_expr() | pl.col("rsid").is_in(allowed)


def excluded_count(table: GenotypeTable, policy: IndelPolicy) -> int:
    """How many markers ``policy`` removes from allele matching.

    Surfaced in the coverage-honesty card (M7.6): a section that silently skipped
    thousands of markers would imply a completeness it does not have.
    """
    return int(table.frame.filter(~matchable_mask(policy)).height)


def matchable(table: GenotypeTable, policy: IndelPolicy | None = None) -> pl.DataFrame:
    """The subset of ``table`` eligible for allele matching."""
    return table.frame.filter(matchable_mask(policy or IndelPolicy.default()))
