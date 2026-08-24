"""Reading the AADR's EIGENSTRAT trio, measured against the pinned release (roadmap M5.6).

The Allen Ancient DNA Resource ships in David Reich's lab format rather than anything PLINK
reads: a ``.snp`` sites table, a ``.ind`` sample table, a packed binary ``.geno``, and a
``.anno`` metadata sheet. This module is the reader; :mod:`genetics.ancestry.aadr` is what
does something with it.

**Everything below was measured against ``v66.p1_HO`` on disk, not taken from a format
description.** The distinction matters because two of the four facts would have been wrong.

**1. The genotype file is ``TGENO``, not ``GENO``, and the difference is a transpose.**
The magic string is the first five bytes, and the pinned file's is ``TGENO``: records run
one per *individual* rather than one per SNP. Measured layout, and it divides exactly::

    48-byte header + 27,594 records x 146,033 bytes = 4,029,634,650 bytes
    record length  = ceil(n_snps / 4)               (four 2-bit codes per byte)

That is a lucky shape for this milestone. Affinity needs a few thousand markers for each of
a few thousand ancient individuals, and an individual-major file answers "give me this
person" with one seek instead of a pass over the whole 4 GB.

``GENO``, the SNP-major variant, is **refused rather than guessed at**. Its layout is
documented and would be a dozen lines, but no ``GENO`` file is pinned here, so that dozen
lines would be untested code standing between an archive and an ancestry claim. A reader
that says "this file is not the one this was measured against" is the honest failure.

**2. Codes are 0/1/2 = copies of the first allele in the ``.snp`` row, 3 = no call.** Not
EIGENSTRAT's textual ``9`` for missing; the packed form spends two bits and uses ``3``.

**3. Ancient genotypes are pseudo-haploid, and the file says so if you count.** Loschbour --
a high-coverage individual -- decodes to 273,929 twos, 93,902 zeros and **zero ones** across
584,131 markers. Every ancient call is homozygous by construction: capture data is
represented by one randomly drawn read per site, doubled. That is a property of the
resource, not of this file, and it is the deepest reason
[M5.6](../../phase1_roadmap.md) must say *affinity* rather than *descent* -- a pseudo-haploid
sample carries twice the per-site variance of a diploid one, so it cannot be treated as
another sample of the same kind. Whether a given individual is pseudo-haploid is not
uniform across the resource -- the ``.DG``/``.SG`` shotgun genomes are genuinely diploid --
so :mod:`genetics.ancestry.aadr` counts heterozygous calls per individual rather than
inferring it from the identifier's suffix.

**4. Dates come from the ``.anno`` sheet, and present-day individuals are marked by a zero.**
``Date mean in BP`` is 0 for the 8,474 present-day Human Origins samples and positive for the
19,119 ancient ones. Those do not add to 27,594, and the one missing is worth knowing about:
``Khwit.SG`` is dated **-4 BP** -- a 20th-century Georgian individual sampled after 1950,
which is what "before present" makes negative. So ``> 0`` rather than ``!= 0`` separates
ancient from modern, and only a sign test puts him on the right side. The sheet's column
*names* run to whole paragraphs and contain embedded newlines, so columns are located by a
substring of the name rather than by equality or position.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

import polars as pl

__all__ = [
    "CODE_MISSING",
    "AadrIndividual",
    "EigenstratError",
    "EigenstratSites",
    "PackedGenotypes",
    "annotate",
    "hasharr",
    "open_packed",
    "read_anno",
    "read_ind",
    "read_individuals",
    "read_snp",
]


CODE_MISSING: Final = 3
"""The packed no-call code. Textual EIGENSTRAT writes ``9``; two bits cannot, so it is 3."""

_MAGIC_TRANSPOSED: Final = b"TGENO"
_MAGIC_PLAIN: Final = b"GENO"
_HEADER_BYTES: Final = 48
"""Measured. ``48 + n_individuals * record_length`` is the pinned file's size exactly."""

_CODES_PER_BYTE: Final = 4

_HASH_MULTIPLIER: Final = 23
_FOLD_MULTIPLIER: Final = 17
_MASK32: Final = 0xFFFFFFFF


def hasharr(values: Iterable[str]) -> int:
    """EIGENSOFT's ``hasharr`` over a list of identifiers, as a 32-bit unsigned int.

    **Not reconstructed from a description -- checked against the pinned file's own header.**
    ``v66.p1_HO``'s header reads ``TGENO   27594  584131 8c17d6d1 80974215``, and those two
    trailing values are exactly this function over the ``.ind``'s identifiers and the
    ``.snp``'s rsIDs respectively. Both reproduce bit for bit, which is what makes it safe
    to rely on: an algorithm derived from memory and never checked against real output is
    the fabrication AGENTS.md 6 forbids, and this one had a way to be checked.
    """
    folded = 0
    for value in values:
        digest = 0
        for char in value:
            digest = (digest * _HASH_MULTIPLIER + ord(char)) & _MASK32
        folded = ((folded * _FOLD_MULTIPLIER) ^ digest) & _MASK32
    return folded


class EigenstratError(RuntimeError):
    """An EIGENSTRAT file could not be read, or does not describe what it claims to."""


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


SITE_SCHEMA: Final[dict[str, pl.DataType]] = {
    "index": pl.UInt32(),
    "rsid": pl.String(),
    "chrom": pl.String(),
    "pos": pl.UInt32(),
    "a1": pl.String(),
    "a2": pl.String(),
}
"""``index`` is the row's position in the ``.snp`` file, which is the only thing that
locates it in the packed genotypes. Carried explicitly rather than left implicit in row
order, because ``wanted`` filters while reading and a filtered frame's row numbers are not
the file's."""


@dataclass(frozen=True)
class EigenstratSites:
    """The ``.snp`` file, optionally narrowed to positions somebody asked for.

    Carries no genotypes -- positions and alleles are properties of the array design.
    """

    frame: pl.DataFrame
    source: str
    n_read: int
    """Rows in the file, before ``wanted``. The packed record length is derived from this,
    so a filtered ``frame`` cannot be used to compute it."""

    id_hash: int
    """:func:`hasharr` over **every** rsID in the file, including the ones ``wanted``
    filtered out.

    Over all of them because that is what the packed file's header commits to. Computed
    during the read rather than afterwards, since the discarded rows are gone by then and
    re-reading an 18 MB file to hash it would make the check cost what it is meant to save.
    """

    @property
    def n_sites(self) -> int:
        return self.frame.height

    @property
    def indices(self) -> list[int]:
        return [int(value) for value in self.frame.get_column("index")]


def read_snp(path: Path, *, wanted: Iterable[tuple[str, int]] | None = None) -> EigenstratSites:
    """Read a ``.snp`` sites table.

    Whitespace-delimited, six columns: rsID, chromosome, genetic position in Morgans,
    physical position, and the two alleles. The genetic position is read past rather than
    parsed -- nothing here uses a recombination map, and AADR writes ``0`` for many rows.

    ``wanted`` narrows to the given ``(chrom, pos)`` pairs *while reading*, for the reason
    :func:`~genetics.external.harmonize.read_panel_sites` gives: the file is 584,131 rows
    and a caller typically wants ten thousand of them.
    """
    keep = frozenset(wanted) if wanted is not None else None
    all_ids: list[str] = []
    indices: list[int] = []
    rsids: list[str] = []
    chroms: list[str] = []
    positions: list[int] = []
    first: list[str] = []
    second: list[str] = []
    n_read = 0

    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        # `exc` stringifies with its full filename, and a path outside the checkout begins
        # with the account name on Windows -- the reason every `source` field in this
        # project keeps a file's name and drops its path.
        raise EigenstratError(
            f"could not read {path.name}: {exc.strerror or exc.__class__.__name__}"
        ) from exc

    with handle:
        for index, line in enumerate(handle):
            fields = line.split()
            if not fields:
                continue
            if len(fields) < 6:
                raise EigenstratError(
                    f"{path.name} line {index + 1} has {len(fields)} field(s); a .snp row is "
                    "rsid, chromosome, genetic position, physical position and two alleles."
                )
            n_read += 1
            all_ids.append(fields[0])
            chrom = fields[1]
            try:
                position = int(fields[3])
            except ValueError as exc:
                raise EigenstratError(
                    f"{path.name} line {index + 1} has a non-numeric position {fields[3]!r}."
                ) from exc
            if keep is not None and (chrom, position) not in keep:
                continue
            # `n_read - 1`, not `index`. The packed record holds one 2-bit code per SNP
            # *row*, so a site is located by its position among the data rows; `index` is
            # the file's line number and counts blank lines too. Using it shifts every
            # marker after a blank line onto a different marker's genotype -- silently,
            # because `open_packed`'s size check reads `n_read`, which is blank-insensitive
            # and would still agree. `read_ind` counts data rows on the same file family.
            indices.append(n_read - 1)
            rsids.append(fields[0])
            chroms.append(chrom)
            positions.append(position)
            first.append(fields[4].upper())
            second.append(fields[5].upper())

    frame = pl.DataFrame(
        {
            "index": indices,
            "rsid": rsids,
            "chrom": chroms,
            "pos": positions,
            "a1": first,
            "a2": second,
        },
        schema=SITE_SCHEMA,
    )
    return EigenstratSites(frame=frame, source=path.name, n_read=n_read, id_hash=hasharr(all_ids))


# ---------------------------------------------------------------------------
# Individuals
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AadrIndividual:
    """One row of the ``.ind`` file, enriched from ``.anno`` where that is available.

    ``date_bp`` is years before 1950 and is **0 for a present-day sample**, which is how the
    resource distinguishes the 8,474 modern Human Origins individuals from the 19,119
    ancient ones. ``None`` means the ``.anno`` sheet did not name this individual at all,
    which is a different thing from "modern" and must not be collapsed into it.
    """

    index: int
    """Row in the ``.ind`` file, which is what locates this individual in the packed file."""

    sample_id: str
    sex: str
    group: str
    date_bp: float | None = None
    ho_snps: int | None = None
    """Autosomal HO markers this individual is published as hitting. Used to skip obviously
    unusable individuals before spending a 146 KB read on each, not as the coverage figure
    anything is reported against -- that one is counted over the markers actually shared
    with the reference, which this is not."""

    @property
    def is_ancient(self) -> bool:
        return self.date_bp is not None and self.date_bp > 0


def read_ind(path: Path) -> list[AadrIndividual]:
    """Read a ``.ind`` file: identifier, sex, group label, one line per individual."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        # `exc` stringifies with its full filename, and a path outside the checkout begins
        # with the account name on Windows -- the reason every `source` field in this
        # project keeps a file's name and drops its path.
        raise EigenstratError(
            f"could not read {path.name}: {exc.strerror or exc.__class__.__name__}"
        ) from exc

    out: list[AadrIndividual] = []
    for index, line in enumerate(text.splitlines()):
        fields = line.split()
        if not fields:
            # Skipped and not counted, for the reason `read_snp` gives at length: `index`
            # below is used only in the error message, and what locates an individual in
            # the packed file is its position among the data rows. `len(out)` is that.
            continue
        if len(fields) < 3:
            raise EigenstratError(
                f"{path.name} line {index + 1} has {len(fields)} field(s); a .ind row is an "
                "identifier, a sex and a group label."
            )
        out.append(
            AadrIndividual(
                index=len(out), sample_id=fields[0], sex=fields[1], group=" ".join(fields[2:])
            )
        )
    if not out:
        raise EigenstratError(f"{path.name} names no individuals.")
    return out


_ANNO_COLUMNS: Final[dict[str, str]] = {
    "sample_id": "Genetic ID",
    "date_bp": "Date mean in BP",
    "group": "Group ID",
    "ho_snps": "HO snpset",
}
"""Column name *substrings*, because the real header's names are paragraphs.

The sheet documents each field inline -- the identifier column's name is 400 characters of
suffix glossary and contains embedded newlines inside its quoting. Matching on a substring
is the only stable handle; matching on position would break the first time a column is
inserted, which between v54 and v66 it was.
"""


def read_anno(path: Path) -> pl.DataFrame:
    """Read the ``.anno`` metadata sheet down to the four columns this project uses.

    Returns ``sample_id``, ``date_bp``, ``group`` and ``ho_snps``. Dates and marker counts
    that do not parse become null rather than raising: the sheet carries ``..`` and free
    text in numeric columns for individuals whose date is unresolved, and an unresolved date
    is a fact about that individual rather than a broken file.
    """
    try:
        frame = pl.read_csv(path, separator="\t", has_header=True, infer_schema_length=0)
    # Broad, because Polars raises several unrelated types for a file that is not the sheet
    # it was handed -- ComputeError, NoDataError and OSError among them -- and the caller
    # needs one name for "this is not the AADR annotation file".
    except Exception as exc:
        raise EigenstratError(
            f"could not read {path.name} as a tab-separated sheet: {exc}"
        ) from exc

    resolved: dict[str, str] = {}
    for field, needle in _ANNO_COLUMNS.items():
        matches = [column for column in frame.columns if needle in column]
        if not matches:
            raise EigenstratError(
                f"{path.name} has no column whose name contains {needle!r}, so {field} cannot "
                f"be read. It carries {len(frame.columns)} columns."
            )
        # First match wins and the order is the sheet's: two columns mention the HO snpset,
        # the second being a "Compatibility_HO" subset that counts a different marker list.
        resolved[field] = matches[0]

    return frame.select(
        pl.col(resolved["sample_id"]).alias("sample_id"),
        pl.col(resolved["date_bp"]).cast(pl.Float64, strict=False).alias("date_bp"),
        pl.col(resolved["group"]).alias("group"),
        pl.col(resolved["ho_snps"]).cast(pl.Float64, strict=False).alias("ho_snps"),
    )


def annotate(individuals: Sequence[AadrIndividual], anno: pl.DataFrame) -> list[AadrIndividual]:
    """Attach ``.anno`` dates and marker counts to ``.ind`` rows, by identifier.

    An individual the sheet does not name keeps ``date_bp=None``, which
    :attr:`AadrIndividual.is_ancient` reads as "not known to be ancient" rather than as
    "present-day". The two are different and the resource does distinguish them: a
    present-day sample carries an explicit zero.
    """
    lookup = {
        str(row["sample_id"]): row
        for row in anno.iter_rows(named=True)
        if row["sample_id"] is not None
    }
    out: list[AadrIndividual] = []
    for individual in individuals:
        row = lookup.get(individual.sample_id)
        if row is None:
            out.append(individual)
            continue
        snps = row["ho_snps"]
        out.append(
            AadrIndividual(
                index=individual.index,
                sample_id=individual.sample_id,
                sex=individual.sex,
                # The sheet's Group ID is the curated label and the .ind file's is a copy
                # that has drifted in past releases. The sheet wins where it has an opinion.
                group=str(row["group"]) if row["group"] else individual.group,
                date_bp=row["date_bp"],
                ho_snps=None if snps is None else int(snps),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Packed genotypes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackedGenotypes:
    """A validated handle on a packed ``TGENO`` file. Open it with :func:`open_packed`.

    Holds no genotypes itself -- it holds the geometry needed to read them, and every field
    was checked against the file's own size rather than believed from its header.
    """

    path: Path
    n_individuals: int
    n_sites: int
    record_bytes: int

    def offset(self, individual: int) -> int:
        return _HEADER_BYTES + individual * self.record_bytes


def _check_hashes(
    head: bytes,
    path: Path,
    *,
    individual_id_hash: int | None,
    site_id_hash: int | None,
) -> None:
    """Compare the header's declared hashes against what the companion files actually hold.

    Silent when a caller passes neither. A header field that does not parse as hex is also
    passed over rather than raised on: the check is an extra, and refusing a file because a
    field this project only recently learned to read looks unfamiliar would be a regression
    dressed as rigour.
    """
    fields = head[len(_MAGIC_TRANSPOSED) :].split()
    wanted = (("individuals", 2, individual_id_hash), ("sites", 3, site_id_hash))
    for label, position, computed in wanted:
        if computed is None or len(fields) <= position:
            continue
        # The real header pads with NULs, which `split()` does not treat as whitespace, so
        # the last field arrives with them attached.
        raw = fields[position].rstrip(b"\x00").decode("ascii", errors="replace")
        try:
            declared = int(raw, 16)
        except ValueError:
            continue
        if declared != computed:
            raise EigenstratError(
                f"{path.name}'s header commits to {label} hash {declared:08x} and the "
                f"companion file hashes to {computed:08x}. These files are the right shape "
                "for each other and are not the same dataset -- a size or count check "
                "cannot see this, which is what the hash is for. Check that the .geno, "
                ".snp and .ind all come from one release and one patch level."
            )


def _parse_header(head: bytes, path: Path) -> tuple[int, int]:
    if head.startswith(_MAGIC_PLAIN) and not head.startswith(_MAGIC_TRANSPOSED):
        raise EigenstratError(
            f"{path.name} is a SNP-major GENO file. This reader was measured against the "
            "individual-major TGENO layout that AADR v66.p1 ships, and a GENO path here "
            "would be untested code between an archive and an ancestry claim. Convert with "
            "EIGENSOFT, or pin the TGENO release."
        )
    if not head.startswith(_MAGIC_TRANSPOSED):
        raise EigenstratError(
            f"{path.name} does not begin with GENO or TGENO, so it is not a packed "
            f"EIGENSTRAT genotype file. First bytes: {head[:8]!r}."
        )
    fields = head[len(_MAGIC_TRANSPOSED) :].split()
    if len(fields) < 2:
        raise EigenstratError(
            f"{path.name}'s header does not carry two counts after the magic: {head[:48]!r}."
        )
    try:
        return int(fields[0]), int(fields[1])
    except ValueError as exc:
        raise EigenstratError(
            f"{path.name}'s header counts are not numbers: {fields[:2]!r}."
        ) from exc


def open_packed(
    path: Path,
    *,
    n_individuals: int,
    n_sites: int,
    individual_id_hash: int | None = None,
    site_id_hash: int | None = None,
) -> PackedGenotypes:
    """Validate a packed genotype file against the ``.ind`` and ``.snp`` beside it.

    Four checks. The counts in the header are compared against the companion files, the
    record length is derived from the site count, **the file's size must equal header plus
    records exactly** -- a packed file has no per-record framing, so a mismatched one does
    not fail to parse, it reads shifted and every genotype after the shift is a different
    marker's -- and, when the caller supplies them, **the header's own two hashes must match
    the identifiers actually read**.

    That fourth check is the only one with any power over the case that matters. Geometry
    catches a *truncated* file; it cannot catch a **same-shaped wrong** one, and the pinned
    release contains that exact hazard: ``v66.p1_HO...ind`` and
    ``v66.p1_compatibility_HO...ind`` are byte-identical (one md5 in the publisher's own
    checksum list), so between the two HO datasets the individual count discriminates
    nothing at all and only the site count separates them. Any ``.patch`` revision that
    corrects rsIDs without changing the row count is the same shape. The hashes are already
    sitting in bytes 5-48, already being parsed, and cost one pass over identifiers the
    caller has just read anyway.

    The two hash arguments are optional so that a caller holding only counts can still open
    a file, but every caller in this project passes them -- see
    :attr:`EigenstratSites.id_hash`.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(_HEADER_BYTES)
    except OSError as exc:
        # `exc` stringifies with its full filename, and a path outside the checkout begins
        # with the account name on Windows -- the reason every `source` field in this
        # project keeps a file's name and drops its path.
        raise EigenstratError(
            f"could not read {path.name}: {exc.strerror or exc.__class__.__name__}"
        ) from exc
    if len(head) < _HEADER_BYTES:
        raise EigenstratError(f"{path.name} is {len(head)} bytes; it carries no header.")

    declared_individuals, declared_sites = _parse_header(head, path)
    if (declared_individuals, declared_sites) != (n_individuals, n_sites):
        raise EigenstratError(
            f"{path.name} declares {declared_individuals:,} individuals over "
            f"{declared_sites:,} sites, but the .ind names {n_individuals:,} and the .snp "
            f"{n_sites:,}. These three files are not one dataset."
        )

    _check_hashes(
        head,
        path,
        individual_id_hash=individual_id_hash,
        site_id_hash=site_id_hash,
    )

    record_bytes = -(-n_sites // _CODES_PER_BYTE)
    expected = _HEADER_BYTES + n_individuals * record_bytes
    actual = path.stat().st_size
    # Both directions. Too small is a truncated download; too large is a .snp shorter than
    # the one the .geno was packed from, which is the same "not one dataset" case and is the
    # one that still decodes cleanly for every site it is asked about.
    if actual != expected:
        raise EigenstratError(
            f"{path.name} is {actual:,} bytes where {n_individuals:,} individuals over "
            f"{n_sites:,} sites need exactly {expected:,} ({_HEADER_BYTES} header + "
            f"{record_bytes:,} per individual). A packed file has no record framing, so a "
            "size mismatch means every genotype past the discrepancy would be read as a "
            "different marker's."
        )
    return PackedGenotypes(
        path=path, n_individuals=n_individuals, n_sites=n_sites, record_bytes=record_bytes
    )


@contextmanager
def _reader(packed: PackedGenotypes) -> Iterator[IO[bytes]]:
    with packed.path.open("rb") as handle:
        yield handle


def read_individuals(
    packed: PackedGenotypes, indices: Sequence[int], sites: Sequence[int]
) -> Iterator[tuple[int, list[int]]]:
    """Yield ``(individual index, codes at each of ``sites``)`` for the requested people.

    Codes are 0, 1, 2 -- copies of the first allele in that ``.snp`` row -- or
    :data:`CODE_MISSING`. ``sites`` are ``.snp`` row numbers, which is what
    :attr:`EigenstratSites.indices` returns; they are read in the order given, so a caller
    can rely on the codes lining up with its own site frame row for row.

    One 146 KB read per individual, and only for the individuals asked for. That is what the
    transposed layout buys: selecting three thousand well-covered ancient individuals out of
    27,594 costs three thousand seeks rather than a pass over four gigabytes.
    """
    shifts = [6 - 2 * (site & 3) for site in sites]
    bytes_at = [site >> 2 for site in sites]
    with _reader(packed) as handle:
        for individual in indices:
            if not 0 <= individual < packed.n_individuals:
                raise EigenstratError(
                    f"individual {individual} is outside the {packed.n_individuals:,} in "
                    f"{packed.path.name}."
                )
            handle.seek(packed.offset(individual))
            record = handle.read(packed.record_bytes)
            if len(record) != packed.record_bytes:
                raise EigenstratError(
                    f"{packed.path.name} ended {packed.record_bytes - len(record):,} bytes "
                    f"into individual {individual}'s record."
                )
            yield (
                individual,
                [(record[byte] >> shift) & 3 for byte, shift in zip(bytes_at, shifts, strict=True)],
            )
