"""Normalized table onto a reference panel's alleles (roadmap M5.2, first half).

M5.2 is two jobs and this module is the first: decide, for every array position, what the
sample's call *means* in the reference panel's coordinate and allele system, and write the
result as a VCF that :mod:`genetics.external.pgen` hands to PLINK 2. The second job -- the
conversion itself -- is a subprocess call and lives there.

Five decisions here are load-bearing.

**A single sample cannot establish which allele is REF, so the panel must.** This is the
whole reason the intermediate is a VCF rather than PLINK 1 ``.ped``/``.map``. That format
has no REF/ALT concept, so PLINK assigns them from allele frequency -- and with one sample
"frequency" is a coin toss between 0, 0.5 and 1. Every marker would get its reference
allele decided by that sample's own genotype, which is precisely backwards: the projection
in M5.4 subtracts reference means and multiplies by reference loadings, so an allele coded
against the wrong reference is a coordinate with its sign flipped. Reading REF and ALT off
the panel is not a refinement, it is the only correct source.

**The array's allele order carries no information.** ``a1``/``a2`` are sorted by
:mod:`genetics.ingest.schema`, so "the first allele" means "the alphabetically first". Any
code that paired ``a1`` with REF would be reading an artefact of sorting as biology.
Orientation is therefore decided by set membership and emitted as allele *indices*.

**Strand-ambiguous sites are dropped whole, including the heterozygotes.** At an A/T or C/G
site both strand readings are consistent with the letters, and with one sample there is no
allele-frequency comparison available to break the tie. A heterozygote is the tempting
exception -- ``AT`` reads as ``AT`` on either strand, so its *encoding* is the same either
way -- and :mod:`genetics.engine.matcher` does keep those, correctly, because there the
question is which outcome one card reports. Here the question is distributional, and
keeping only the heterozygotes at a site would make missingness depend on genotype: every
homozygote at that site becomes absent, so the site's surviving dosages are all exactly 1.
Mean-imputing the rest, which is what ``--score`` does, then pulls the projection toward a
value the data never supported. Fewer markers beats biased ones.

Two consequences of that exclusion are worth stating, because neither is obvious from the
code and both shape what comes out. **Every surviving site is biallelic**: A/C/G/T is two
complementary pairs, so any allele set of three or more contains both members of one and is
therefore ambiguous. Only A/C, A/G, C/T and G/T get through -- which is also what PLINK's
PCA and ``--score`` want. And **a homozygote can never be an allele mismatch**, since each
of those four sets unioned with its own complement is all four bases; only a heterozygote,
which has to satisfy both of its bases under one reading, can fail to fit.

**The panel decides the variant ID.** The vendor's probe id (``i5000123``) exists nowhere
outside the vendor's array, while PCA loadings and PGS scoring files key on the panel's own
rsIDs. Writing the array's id would produce a pgen that matches nothing downstream.

**Autosomes only.** Not a parameter, because the alternative does not merely need a flag:
PLINK 2 refuses a chrX record outright ("Error: chrX is present in the input file, but no
sex information was provided"), and a doubled hemizygous call written as a diploid
homozygote would be a fabricated second allele. Non-autosomal conversion needs the ploidy
and sex plumbing that M6.4 owns, and the consumers here -- PCA projection (M5.3, M5.4) and
ROH (M6.1) -- are autosomal anyway.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from io import TextIOWrapper
from pathlib import Path
from typing import IO, Final

import polars as pl

from genetics import __version__
from genetics.engine.matcher import complement
from genetics.ingest.schema import AUTOSOMES, CHROM_ORDER, CallStatus, Chrom, GenotypeTable

__all__ = [
    "SAMPLE_ID",
    "HarmonizationReport",
    "PanelError",
    "PanelSites",
    "SiteOutcome",
    "is_ambiguous_site",
    "is_snp_site",
    "orient",
    "read_panel_sites",
    "write_harmonized_vcf",
]

SAMPLE_ID: Final[str] = "SAMPLE"
"""The one name that ever appears in a sample column, a ``.psam`` or a PLINK log.

A constant rather than the export's filename or any identifier derived from it. PLINK
copies this string into every file it writes and every log line that mentions the sample,
and those files outlive the run -- so deriving it from the input would put whatever the
person happened to call their download into artefacts nobody thinks of as personal.
"""

_BASES: Final[frozenset[str]] = frozenset("ACGT")

_PANEL_COLUMNS: Final[tuple[str, ...]] = ("#CHROM", "POS", "ID", "REF", "ALT")
"""The leading columns of both formats this reads. VCF fixes them by specification and
PLINK 2's ``.pvar`` uses the same names and order, which is why one parser serves both."""

_CHROM_ALIASES: Final[Mapping[str, str]] = {
    "23": "X",
    "24": "Y",
    "25": "PAR",
    "26": "MT",
    "M": "MT",
    "CHRM": "MT",
}
"""PLINK's numeric chromosome codes and the two spellings of the mitochondrion. Panels are
inconsistent here in a way that is silent: an unrecognised code does not raise, it simply
matches nothing, so a whole chromosome would go missing with no error anywhere."""

_MISSING_ALT: Final[str] = "."

_SINGLE_COPY_STATUSES: Final[frozenset[str]] = frozenset(
    {CallStatus.HEMIZYGOUS.value, CallStatus.HET_HAPLOID.value}
)
"""Compared as plain strings because the joined frame carries ``call_status`` cast to
``String``. ``StrEnum`` members do compare and hash as their values, so the enum members
would work here -- but only because of a mixin detail, and a set that silently stopped
matching would drop a real contradiction rather than raise."""


class PanelError(ValueError):
    """A reference panel file could not be read as sites."""


# ---------------------------------------------------------------------------
# Panel sites
# ---------------------------------------------------------------------------


PANEL_SCHEMA: Final[dict[str, pl.DataType]] = {
    "chrom": pl.Enum(CHROM_ORDER),
    "pos": pl.UInt32(),
    "panel_id": pl.String(),
    "ref": pl.String(),
    "alt": pl.String(),
}
"""``alt`` holds the raw ALT field, commas and all. Split per-site rather than at read
time: a list column would cost memory on every row to serve the minority that are
multiallelic."""


@dataclass(frozen=True)
class PanelSites:
    """The reference panel, reduced to what harmonization needs.

    Carries no genotypes -- only positions, ids and alleles, all of them properties of the
    panel rather than of any person -- so unlike almost everything else in this pipeline it
    is safe to print and safe to log.
    """

    frame: pl.DataFrame
    source: str
    """The panel file's *name*. Deliberately not its path: this string is copied into the
    VCF header, and an absolute path on Windows begins with the user's account name."""

    n_read: int
    """Sites on the requested chromosomes, before the ``wanted`` filter and before
    deduplication. Not the file's line count: a panel covering chromosomes this run does
    not want should not report them as read."""

    n_duplicate_positions: int
    """Sites dropped because an earlier row already claimed that (chromosome, position).

    Counted rather than tolerated: a panel with many of these is a panel that has not been
    split by multiallelic site, and the harmonization below would then be comparing the
    array against whichever row happened to come first. Counted only among the sites that
    survive ``wanted``, since a duplicate at a position this run never looks at is not a
    fact about this run."""

    @property
    def n_sites(self) -> int:
        return self.frame.height


@contextmanager
def _open_text(path: Path) -> Iterator[IO[str]]:
    """Open a panel file, transparently handling gzip.

    ``gzip`` from the standard library rather than an htslib binding: AGENTS.md 4.9 rules
    out ``pysam``/``cyvcf2`` on Windows and notes that BGZF is gzip-compatible for
    sequential reads, which is the only access pattern here.
    """
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as raw:
            yield TextIOWrapper(raw, encoding="utf-8", errors="replace")
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        yield handle


def _panel_chrom(raw: str) -> str | None:
    """Normalize a panel's chromosome spelling, or ``None`` if it is not one we model."""
    value = raw.strip().upper()
    value = value.removeprefix("CHR") if value != "CHRM" else value
    value = _CHROM_ALIASES.get(value, value)
    return value if value in CHROM_ORDER else None


def _column_indices(header: str) -> tuple[int, ...]:
    """Positions of ``#CHROM POS ID REF ALT`` in a header line.

    Resolved by name rather than assumed, because a ``.pvar`` may carry extra columns and
    PLINK does not promise their order. Raises if any of the five is missing -- a file
    without them is not a sites file, and guessing would silently harmonize against the
    wrong column.
    """
    fields = header.rstrip("\n").split("\t")
    try:
        return tuple(fields.index(name) for name in _PANEL_COLUMNS)
    except ValueError as exc:
        raise PanelError(
            f"panel header names {fields[:8]}, which is missing one of "
            f"{list(_PANEL_COLUMNS)}; this is not a VCF or .pvar sites file"
        ) from exc


def read_panel_sites(
    path: Path,
    *,
    chroms: Sequence[Chrom] = AUTOSOMES,
    wanted: Iterable[tuple[str, int]] | None = None,
) -> PanelSites:
    """Read a VCF or PLINK 2 ``.pvar`` as panel sites.

    ``wanted`` restricts the result to the given ``(chrom, pos)`` pairs *while reading*,
    and is the difference between this being usable and not: 1000 Genomes phase 3 is 85
    million sites and the array carries 677 thousand, so materialising the panel and then
    filtering would cost gigabytes to discard 99.2% of them. Pass the array's positions.

    A headerless ``.pvar`` is accepted -- PLINK's format permits it, and specifies the same
    leading column order -- so the positional fallback is not a guess.
    """
    keep = frozenset(chroms)
    wanted_set = frozenset(wanted) if wanted is not None else None

    chrom_out: list[str] = []
    pos_out: list[int] = []
    id_out: list[str] = []
    ref_out: list[str] = []
    alt_out: list[str] = []
    seen: set[tuple[str, int]] = set()
    n_read = 0
    n_duplicate = 0
    indices = tuple(range(5))

    with _open_text(path) as handle:
        for line in handle:
            if line.startswith("##"):
                continue
            if line.startswith("#"):
                indices = _column_indices(line)
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) <= indices[-1]:
                continue
            chrom = _panel_chrom(fields[indices[0]])
            if chrom is None or chrom not in keep:
                continue
            try:
                pos = int(fields[indices[1]])
            except ValueError:
                continue
            n_read += 1
            key = (chrom, pos)
            if wanted_set is not None and key not in wanted_set:
                continue
            if key in seen:
                n_duplicate += 1
                continue
            seen.add(key)
            chrom_out.append(chrom)
            pos_out.append(pos)
            id_out.append(fields[indices[2]])
            ref_out.append(fields[indices[3]].upper())
            alt_out.append(fields[indices[4]].upper())

    frame = pl.DataFrame(
        {
            "chrom": chrom_out,
            "pos": pos_out,
            "panel_id": id_out,
            "ref": ref_out,
            "alt": alt_out,
        },
        schema=PANEL_SCHEMA,
    )
    return PanelSites(
        frame=frame,
        source=path.name,
        n_read=n_read,
        n_duplicate_positions=n_duplicate,
    )


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------


class SiteOutcome(StrEnum):
    """What happened to one array position. Every position gets exactly one."""

    AS_WRITTEN = "as_written"
    """Written. The array's alleles are the panel's, on the panel's strand."""

    COMPLEMENTED = "complemented"
    """Written, after flipping onto the panel's strand. Counted separately because a large
    count is a fact about the array's strand convention worth seeing, and a small nonzero
    one against a panel that should agree is a sign something is wrong."""

    NO_CALL = "no_call"
    """Written as ``./.``. The record is emitted rather than omitted so that the marker
    stays *countable*: a variant missing from the file and a variant present but uncalled
    are the same to a scorer's arithmetic and very different to a coverage report."""

    NOT_IN_PANEL = "not_in_panel"
    """The array position is not a site in this panel. Says nothing about the person."""

    PANEL_NOT_SNP = "panel_not_snp"
    """The panel's alleles are not two or more single-base A/C/G/T alleles -- an indel, an
    MNP, or a monomorphic record. A consumer array reports one base per allele and carries
    no sequence for its indels (AGENTS.md 4.2), so nothing here can be placed against one."""

    ARRAY_INDEL = "array_indel"
    """Every probe at this position is an ``I``/``D`` row. Excluded by AGENTS.md 4.2: the
    codes carry no sequence, so there is no allele to match and no strand to flip."""

    AMBIGUOUS_SITE = "ambiguous_site"
    """The panel's alleles are self-complementary (A/T, C/G, or a multiallelic set that
    contains a complementary pair). See the module docstring for why this excludes the
    heterozygotes too."""

    ALLELE_MISMATCH = "allele_mismatch"
    """The observed alleles are not the panel's under either strand. The array and the
    panel disagree about which variant lives here, so coding one as the other would be
    reporting a different variant's genotype."""

    DUPLICATE_CONFLICT = "duplicate_conflict"
    """Two or more probes called this position differently. Choosing between them would
    manufacture an answer the data does not contain -- the same rule
    :mod:`genetics.engine.matcher` applies, for the same reason."""

    PLOIDY_CONFLICT = "ploidy_conflict"
    """A probe here is marked hemizygous or heterozygous-haploid. On an autosome that is a
    contradiction, so the call is not trustworthy; kept as its own outcome rather than
    folded into ``no_call`` so it stays visible if it ever happens."""

    @property
    def is_written(self) -> bool:
        """True when the site produces a VCF record."""
        return self in _WRITTEN_OUTCOMES


_WRITTEN_OUTCOMES: Final[frozenset[SiteOutcome]] = frozenset(
    {SiteOutcome.AS_WRITTEN, SiteOutcome.COMPLEMENTED, SiteOutcome.NO_CALL}
)


def is_snp_site(alleles: Sequence[str]) -> bool:
    """True when the panel lists two or more *distinct* single-base A/C/G/T alleles.

    Distinctness is not pedantry, and the dangerous case is ``REF == ALT``. Without this
    check it survives every later test: the allele index silently keeps the last position
    for a repeated letter, ``orient`` reports a clean ``AS_WRITTEN``, and the writer emits
    a ``1/1`` call at a site whose ALT *is* the reference -- indistinguishable downstream
    from a real homozygous-alternate call. A repeated ALT (``A`` / ``G,G``) is milder,
    since the genotype still decodes correctly, but it is the same malformed record and it
    would be copied into the output VCF. AGENTS.md 6 says fail loudly on malformed input;
    here that means declining to read the record at all and counting it ``PANEL_NOT_SNP``.

    A well-formed VCF never repeats an allele, so this costs nothing on a real panel.
    """
    return (
        len(alleles) >= 2
        and len(set(alleles)) == len(alleles)
        and all(a in _BASES for a in alleles)
    )


def is_ambiguous_site(alleles: Sequence[str]) -> bool:
    """True when the panel's allele set is its own complement in part or whole.

    The familiar cases are A/T and C/G. The general test also catches multiallelic sets
    that a pairwise check would miss -- ``A/C/T`` contains both A and T -- which matters
    because those sets are exactly as undecidable and would otherwise slip through.

    Requires :func:`is_snp_site`; :func:`complement` refuses anything else.
    """
    present = set(alleles)
    return bool(present & {complement(a) for a in present})


def orient(genotype: str, alleles: Sequence[str]) -> tuple[tuple[int, ...] | None, SiteOutcome]:
    """Code ``genotype`` as panel allele indices, flipping strand if that is what fits.

    Returns ``(indices, outcome)``; ``indices`` is ``None`` exactly when the outcome is
    :attr:`SiteOutcome.ALLELE_MISMATCH`.

    **Callers must have excluded ambiguous sites first**, and given that, the answer here is
    never a judgement call. Let ``S`` be the panel's alleles. An observed allele fits both
    readings only if it lies in ``S`` and in ``complement(S)``, so both readings can fit
    only when those sets intersect -- which is what :func:`is_ambiguous_site` tests. Rule
    that out and at most one reading is possible, so there is no preference to encode, no
    tie to break, and no case where a homozygote's single visible letter leaves the strand
    undetermined.
    """
    index = {allele: position for position, allele in enumerate(alleles)}
    if all(base in index for base in genotype):
        return tuple(sorted(index[base] for base in genotype)), SiteOutcome.AS_WRITTEN
    flipped = complement(genotype)
    if all(base in index for base in flipped):
        return tuple(sorted(index[base] for base in flipped)), SiteOutcome.COMPLEMENTED
    return None, SiteOutcome.ALLELE_MISMATCH


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HarmonizationReport:
    """Counts, and only counts.

    Safe to log, render and store: every field is a property of the array, the panel, or
    the agreement between them. The one number that touches the person -- how many of their
    markers failed to call -- is a QC figure M1 already reports, and an aggregate over
    hundreds of thousands of positions carries no genotype.

    ``counts`` partitions the autosomal positions on the array exactly once, which is what
    makes it readable as a coverage statement rather than a set of overlapping tallies.
    """

    panel_source: str
    panel_sites: int
    panel_duplicate_positions: int
    n_array_rows: int
    counts: Mapping[SiteOutcome, int]

    @property
    def n_sites(self) -> int:
        return sum(self.counts.values())

    @property
    def n_written(self) -> int:
        return sum(count for outcome, count in self.counts.items() if outcome.is_written)

    @property
    def n_usable(self) -> int:
        """Written *and* called -- the markers a projection can actually score."""
        return self.counts.get(SiteOutcome.AS_WRITTEN, 0) + self.counts.get(
            SiteOutcome.COMPLEMENTED, 0
        )

    def render(self) -> str:
        lines = [
            f"Panel: {self.panel_source} ({self.panel_sites} sites)",
            f"Array autosomal positions: {self.n_sites} (from {self.n_array_rows} rows)",
            f"Written: {self.n_written}; usable calls: {self.n_usable}",
        ]
        lines.extend(
            f"  {outcome.value}: {self.counts[outcome]}"
            for outcome in SiteOutcome
            if self.counts.get(outcome)
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


_VCF_COLUMNS: Final[str] = "\t".join(
    ("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", SAMPLE_ID)
)


def _header(chroms: Sequence[str], panel_source: str) -> str:
    """The VCF header.

    No ``##fileDate``. The line is conventional and it is the only thing here that would
    differ between two runs over identical inputs, which would make a byte-comparison of
    the intermediate useless as a check that harmonization is deterministic.
    """
    lines = [
        "##fileformat=VCFv4.2",
        f"##source=genetics-analysis {__version__} (M5.2 harmonization)",
        "##reference=GRCh37",
        f"##panelSource={panel_source}",
        *(f"##contig=<ID={chrom}>" for chrom in chroms),
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
        _VCF_COLUMNS,
    ]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class _Site:
    """One array position's rows, already joined to its panel record."""

    chrom: str
    pos: int
    panel_id: str
    ref: str
    alt: str
    genotypes: tuple[str | None, ...]
    statuses: tuple[str, ...]


def _decide(site: _Site) -> tuple[str | None, SiteOutcome]:
    """Resolve one position to a GT field, or to the reason there is none.

    The order of the checks is the order in which a reason *supersedes* another. Panel
    problems come first because they hold whatever the array did: an unusable or ambiguous
    site is excluded even when the call is clean, so reporting it as a duplicate conflict
    would name the lesser of the two reasons.
    """
    alleles = [site.ref, *(a for a in site.alt.split(",") if a != _MISSING_ALT)]
    if not is_snp_site(alleles):
        return None, SiteOutcome.PANEL_NOT_SNP
    if is_ambiguous_site(alleles):
        return None, SiteOutcome.AMBIGUOUS_SITE

    if any(status in _SINGLE_COPY_STATUSES for status in site.statuses):
        return None, SiteOutcome.PLOIDY_CONFLICT

    snp_calls = [g for g in site.genotypes if g is not None and all(b in _BASES for b in g)]
    if not snp_calls:
        # Either every probe is an indel row, or none of them called. The distinction is
        # the difference between "this position cannot be read" and "it was read and came
        # back empty", and only the second is about the person.
        if any(g is not None for g in site.genotypes):
            return None, SiteOutcome.ARRAY_INDEL
        return "./.", SiteOutcome.NO_CALL

    # Compared literally, not on a strand-independent form. `strand_canonical` exists for
    # probes at a site where the strand is undecidable -- and those sites have already been
    # excluded above, so here two different strings really are two different calls.
    if len(set(snp_calls)) > 1:
        return None, SiteOutcome.DUPLICATE_CONFLICT

    indices, outcome = orient(snp_calls[0], alleles)
    if indices is None:
        return None, outcome
    return "/".join(str(i) for i in indices), outcome


def _sites(frame: pl.DataFrame) -> Iterator[_Site]:
    """Group a position-sorted frame into one :class:`_Site` per (chrom, pos)."""
    current: list[tuple[str, int, str, str, str, str | None, str]] = []
    for row in frame.iter_rows():
        chrom, pos = row[0], row[1]
        if current and (current[0][0], current[0][1]) != (chrom, pos):
            yield _from_rows(current)
            current = []
        current.append(row)
    if current:
        yield _from_rows(current)


def _from_rows(rows: Sequence[tuple[str, int, str, str, str, str | None, str]]) -> _Site:
    first = rows[0]
    return _Site(
        chrom=first[0],
        pos=first[1],
        panel_id=first[2],
        ref=first[3],
        alt=first[4],
        genotypes=tuple(row[5] for row in rows),
        statuses=tuple(row[6] for row in rows),
    )


def write_harmonized_vcf(
    table: GenotypeTable,
    panel: PanelSites,
    destination: Path,
) -> HarmonizationReport:
    """Write the sample's autosomal calls as a VCF on the panel's alleles.

    The file is genotype data in the fullest sense -- ``.gitignore`` blocks ``*.vcf`` for
    exactly this reason -- so ``destination`` belongs under ``cache_dir()`` or another
    location outside the checkout. :func:`genetics.external.pgen.to_pgen` chooses one.

    The join runs in Polars and the decision loop in Python, which is the split that keeps
    this quick without making it unreadable. Positions absent from the panel are the
    majority of a 677-thousand-marker array against an LD-pruned subset, and they are
    removed in bulk by the join; only the positions the panel actually covers reach the
    per-site logic. The count of the removed ones is exact regardless, because whether a
    position is in the panel is a property of the position, identical for every probe on it.
    """
    array = table.filter_chrom(*AUTOSOMES)
    panel_frame = panel.frame.filter(pl.col("chrom").is_in([c.value for c in AUTOSOMES]))

    joined = array.select(
        pl.col("chrom"),
        pl.col("pos_grch37").alias("pos"),
        pl.col("genotype"),
        pl.col("call_status").cast(pl.String()),
    ).join(panel_frame, on=["chrom", "pos"], how="left")

    absent = joined.filter(pl.col("panel_id").is_null())
    n_absent = absent.select("chrom", "pos").n_unique()

    matched = (
        joined.filter(pl.col("panel_id").is_not_null())
        .select("chrom", "pos", "panel_id", "ref", "alt", "genotype", "call_status")
        .sort("chrom", "pos")
    )

    counts: dict[SiteOutcome, int] = dict.fromkeys(SiteOutcome, 0)
    counts[SiteOutcome.NOT_IN_PANEL] = n_absent

    present = set(matched.get_column("chrom").cast(pl.String()).unique().to_list())
    contigs = [chrom for chrom in CHROM_ORDER if chrom in present]

    destination.parent.mkdir(parents=True, exist_ok=True)
    # newline="" so the records are LF-terminated on every platform. A VCF is read by a
    # native binary, and this repository already learned at M0.1 that letting the platform
    # decide line endings turns a byte-identical artefact into a platform-specific one.
    with destination.open("w", encoding="utf-8", newline="") as handle:
        handle.write(_header(contigs, panel.source))
        for site in _sites(matched):
            gt, outcome = _decide(site)
            counts[outcome] += 1
            if gt is None:
                continue
            handle.write(
                f"{site.chrom}\t{site.pos}\t{site.panel_id}\t{site.ref}\t{site.alt}"
                f"\t.\t.\t.\tGT\t{gt}\n"
            )

    return HarmonizationReport(
        panel_source=panel.source,
        panel_sites=panel.n_sites,
        panel_duplicate_positions=panel.n_duplicate_positions,
        n_array_rows=array.height,
        counts={outcome: count for outcome, count in counts.items() if count},
    )
