"""The normalized table (roadmap M1.1) -- the single contract between vendors and analysis.

Columns are exactly those in AGENTS.md section 2::

    rsid | chrom | pos_grch37 | a1 | a2 | genotype | call_status

Everything downstream reads only this. A new vendor is a new adapter producing this shape;
it must never require touching an analysis module.

Four decisions here are load-bearing, and each is a place a plausible alternative would
have silently produced wrong health claims:

**chrom is an enum, not a number.** The vendor writes ``23``-``26`` for X, Y, PAR and MT.
Carrying those through as integers means every downstream ``chrom <= 22`` filter silently
includes sex chromosomes, and every "autosomal" statistic is quietly wrong. The Polars
``Enum`` dtype has no such members at all, so a leaked vendor code raises at construction
rather than becoming a plausible-looking result.

**No-calls are null, not "0".** The vendor writes ``0 0``. Kept as the string ``"0"``, a
no-call joins cleanly against reference tables and compares equal to other no-calls,
producing confident nonsense. As null it propagates or errors. Fail loudly (AGENTS.md 6).

**Alleles are sorted.** ``A G`` and ``G A`` both occur in the file and mean the same
genotype. Sorting once, here, is what stops every consumer from having to remember.

**call_status carries ploidy, because the genotype string cannot.** A hemizygous call is
written doubled -- male X ``A A`` is indistinguishable from a true homozygote by the
string alone. The status column is the only place that distinction can live, and it is
filled in only after sex inference (M1.5), because until then it is not known.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Final

import polars as pl

from genetics.privacy import NoGenotypeRepr


class Chrom(StrEnum):
    """Chromosome, normalized. Never the vendor's numeric codes for the sex chromosomes.

    ``PAR`` is kept separate from ``X`` on purpose: the pseudoautosomal regions are
    diploid in both sexes, so folding them into X would corrupt the X heterozygosity rate
    that sex inference depends on (M1.5).
    """

    CHR1 = "1"
    CHR2 = "2"
    CHR3 = "3"
    CHR4 = "4"
    CHR5 = "5"
    CHR6 = "6"
    CHR7 = "7"
    CHR8 = "8"
    CHR9 = "9"
    CHR10 = "10"
    CHR11 = "11"
    CHR12 = "12"
    CHR13 = "13"
    CHR14 = "14"
    CHR15 = "15"
    CHR16 = "16"
    CHR17 = "17"
    CHR18 = "18"
    CHR19 = "19"
    CHR20 = "20"
    CHR21 = "21"
    CHR22 = "22"
    X = "X"
    Y = "Y"
    PAR = "PAR"
    MT = "MT"

    @property
    def is_autosome(self) -> bool:
        return self.value.isdigit()


AUTOSOMES: Final[tuple[Chrom, ...]] = tuple(c for c in Chrom if c.is_autosome)

CHROM_ORDER: Final[tuple[str, ...]] = tuple(c.value for c in Chrom)
"""Category order for the Polars enum. Sorting the table sorts biologically."""


class CallStatus(StrEnum):
    """How to read the allele pair on this row.

    ``HEMIZYGOUS`` and ``HET_HAPLOID`` are only ever set after sex inference. Before that
    a single-copy locus is indistinguishable from a homozygous diploid one, and guessing
    would be exactly the mistake AGENTS.md section 2 warns about.
    """

    CALLED = "called"
    """Diploid locus, both alleles observed."""

    HEMIZYGOUS = "hemizygous"
    """Single-copy locus. The doubled pair represents *one* allele; do not read zygosity
    off it, and do not count it toward a heterozygosity rate."""

    HET_HAPLOID = "het_haploid"
    """A heterozygous pair at a locus inferred single-copy -- a contradiction. Usually a
    genotyping error, occasionally real (mosaicism, aneuploidy, a mis-inferred sex). Kept
    as its own status rather than dropped, so it stays countable in QC."""

    NO_CALL = "no_call"
    """Written ``0 0`` by the vendor. Alleles and genotype are null on these rows."""


CALL_STATUS_ORDER: Final[tuple[str, ...]] = tuple(s.value for s in CallStatus)

VALID_ALLELES: Final[frozenset[str]] = frozenset({"A", "C", "G", "T", "I", "D"})
"""``I``/``D`` are indels with no recorded sequence -- see AGENTS.md 4.2 and
:mod:`genetics.ingest.indels`. ``0`` is deliberately absent: a no-call is a null here,
not an allele."""

INDEL_ALLELES: Final[frozenset[str]] = frozenset({"I", "D"})

NO_CALL_TOKEN: Final[str] = "0"
"""What the AncestryDNA layout writes for an uncalled genotype, in both allele columns."""

NORMALIZED_SCHEMA: Final[dict[str, pl.DataType]] = {
    "rsid": pl.String(),
    "chrom": pl.Enum(CHROM_ORDER),
    "pos_grch37": pl.UInt32(),
    "a1": pl.String(),
    "a2": pl.String(),
    "genotype": pl.String(),
    "call_status": pl.Enum(CALL_STATUS_ORDER),
}
"""The whole contract, in one dict. ``UInt32`` holds every GRCh37 coordinate (max ~2.5e8)
and rejects a negative position outright."""

COLUMNS: Final[tuple[str, ...]] = tuple(NORMALIZED_SCHEMA)


class SchemaError(ValueError):
    """A frame does not match :data:`NORMALIZED_SCHEMA`."""


def validate_frame(frame: pl.DataFrame) -> None:
    """Raise :class:`SchemaError` unless ``frame`` matches the contract exactly.

    Checks names, order and dtypes. Order matters because the enum dtypes are positional
    in nothing but readability -- but a column set that has drifted is a signal that an
    adapter has invented its own shape, which is the failure this module exists to stop.
    """
    actual = dict(frame.schema)

    if tuple(actual) != COLUMNS:
        raise SchemaError(
            f"normalized table columns must be exactly {list(COLUMNS)}, got {list(actual)}"
        )

    wrong = {
        name: (str(actual[name]), str(dtype))
        for name, dtype in NORMALIZED_SCHEMA.items()
        if actual[name] != dtype
    }
    if wrong:
        detail = "; ".join(f"{n}: got {got}, expected {want}" for n, (got, want) in wrong.items())
        raise SchemaError(f"normalized table dtypes are wrong -- {detail}")


class GenotypeTable(NoGenotypeRepr):
    """A normalized table plus the guarantee that printing it cannot leak a genotype.

    The wrapper exists for one reason: ``polars.DataFrame.__repr__`` prints rows. A bare
    frame in a traceback, a debugger, or a log line puts genotypes on screen and from
    there into an issue comment. :class:`~genetics.privacy.NoGenotypeRepr` shows only the
    fields named in ``_repr_fields`` -- here, counts and shape.

    ``.frame`` is available and unwrapped; this is a guard against accident, not an
    attempt to stop a determined caller.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_markers", "vendor")

    def __init__(self, frame: pl.DataFrame, *, vendor: str) -> None:
        validate_frame(frame)
        self.frame = frame
        self.vendor = vendor

    @property
    def n_markers(self) -> int:
        return self.frame.height

    def __len__(self) -> int:
        return self.frame.height

    def filter_chrom(self, *chroms: Chrom) -> pl.DataFrame:
        """Rows on the given chromosomes. Convenience used all over QC."""
        wanted = [c.value for c in chroms]
        return self.frame.filter(pl.col("chrom").is_in(wanted))


def empty_frame() -> pl.DataFrame:
    """An empty frame with the right schema. Useful in tests and as an adapter fallback."""
    return pl.DataFrame(schema=NORMALIZED_SCHEMA)
