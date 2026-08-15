"""AncestryDNA V2 adapter (roadmap M1.2).

Targets the format measured in AGENTS.md section 2, not a format assumed from
documentation. Every quirk handled here was observed in a real V2.0 export:

* a ``#``-prefixed comment block of about 17 lines, then an uncommented column row;
* chromosomes as integers, with ``23=X 24=Y 25=PAR 26=MT``;
* no-calls written ``0 0`` -- not ``--``, not ``NN``, not empty;
* indels coded ``I``/``D`` with the sequence *not* recorded (AGENTS.md 4.2);
* heterozygote alleles in either column order;
* hemizygous calls written doubled, so a male X looks homozygous throughout.

The allele-level handling lives in :mod:`genetics.ingest.normalize`; what is specific to
this vendor is the header contract and the chromosome map.

Ploidy is *not* resolved here. A doubled ``A A`` on the X is a hemizygous male call or a
homozygous female one, and the file cannot say which -- that needs the inferred sex from
QC (M1.5). Guessing at ingest time is the mistake AGENTS.md section 2 exists to prevent.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from genetics.ingest.errors import (
    ColumnCountError,
    MalformedHeaderError,
    UnsupportedBuildError,
    describe_columns,
)
from genetics.ingest.normalize import normalize_rows
from genetics.ingest.registry import Adapter, ParseResult, SourceInfo, register
from genetics.ingest.schema import Chrom, GenotypeTable

VENDOR_ID = "ancestrydna_v2"

EXPECTED_COLUMNS = ("rsid", "chromosome", "position", "allele1", "allele2")
"""The uncommented column row, exactly. Checked rather than assumed: a vendor that
reorders or renames a column would otherwise be parsed positionally into wrong alleles."""

CHROM_MAP = {
    **{str(n): Chrom(str(n)) for n in range(1, 23)},
    "23": Chrom.X,
    "24": Chrom.Y,
    "25": Chrom.PAR,
    "26": Chrom.MT,
}
"""AGENTS.md section 2. The single most consequential line in this file: without it,
``23``-``26`` are read as autosomes and every autosomal statistic silently includes the
sex chromosomes."""

SUPPORTED_BUILD = "37"
"""GRCh37. The whole reference corpus is on it (AGENTS.md 5.5); a build-38 file parsed as
37 puts every variant at the wrong locus with no symptom but being wrong."""

_BUILD_RE = re.compile(r"build\s+(\d+)(?:\.\d+)?", re.IGNORECASE)
"""The real export states "build 37.1"; the minor revision is not meaningful to us."""

_ARRAY_RE = re.compile(r"array\s+version[:\s]+(\S+)", re.IGNORECASE)

MIN_HEADER_LINES = 5
"""The real file has ~17. Requiring all 17 would make the check brittle against a vendor
tweak; requiring a handful still rejects a file that has been stripped of its provenance,
which is the case that matters -- an unlabelled file has no build to assert."""


def sniff(lines: Sequence[str]) -> bool:
    """Recognise the AncestryDNA layout from its comment block.

    Keys on the vendor name in the comment block rather than on the column row, because a
    file truncated mid-header must still be *recognised* -- so that it can be rejected
    with a message about its header, rather than as an unknown vendor.
    """
    head = "\n".join(line for line in lines if line.startswith("#")).lower()
    return "ancestrydna" in head


def _split_header(lines: Sequence[str]) -> tuple[list[str], str | None]:
    """Return the comment block and the first uncommented line."""
    comments: list[str] = []
    for line in lines:
        if line.startswith("#"):
            comments.append(line)
        else:
            return comments, line
    return comments, None


def _parse_header(lines: Sequence[str], source_name: str) -> tuple[list[str], str, str | None]:
    """Validate the header block. Returns ``(comments, build, array_version)``."""
    comments, column_line = _split_header(lines)

    # The column row is checked before the comment-block size because it produces the
    # more diagnostic message: a truncated export is missing both, and "the header row is
    # gone" is the finding, while "only 4 comment lines" is a symptom of it.
    if column_line is None:
        raise MalformedHeaderError(
            f"{source_name}: the comment block is not followed by a column header row. "
            f"Expected a tab-separated {list(EXPECTED_COLUMNS)}. The file looks truncated."
        )

    columns = tuple(part.strip().lower() for part in column_line.split("\t"))
    if columns != EXPECTED_COLUMNS:
        raise MalformedHeaderError(
            f"{source_name}: expected the column header {list(EXPECTED_COLUMNS)}, "
            f"{describe_columns(columns)}. Columns are read by name, not position, and a "
            "renamed or reordered file must be rejected rather than parsed positionally."
        )

    if len(comments) < MIN_HEADER_LINES:
        raise MalformedHeaderError(
            f"{source_name}: expected an AncestryDNA comment block of at least "
            f"{MIN_HEADER_LINES} '#' lines, found {len(comments)}. Without it there is no "
            "declared build to check, and an undeclared build cannot be assumed."
        )

    header_text = "\n".join(comments)

    build_match = _BUILD_RE.search(header_text)
    if build_match is None:
        raise MalformedHeaderError(
            f"{source_name}: the header declares no reference build. Every coordinate in "
            "this pipeline is GRCh37; a file that will not say which build it is on "
            "cannot be placed."
        )

    build = build_match.group(1)
    if build != SUPPORTED_BUILD:
        raise UnsupportedBuildError(
            f"{source_name}: header declares reference build {build}, but this pipeline "
            f"is GRCh37 ({SUPPORTED_BUILD}) throughout -- ClinVar positions, the "
            "imputation panel and every PGS scoring file. Parsing it as GRCh37 would "
            "report the wrong genes. Re-export on build 37 or lift the coordinates over "
            "first."
        )

    array_match = _ARRAY_RE.search(header_text)
    array_version = array_match.group(1) if array_match else None

    return comments, build, array_version


def parse(path: Path) -> ParseResult:
    """Parse an AncestryDNA export into the normalized table."""
    from genetics.ingest.registry import read_prefix

    source_name = path.name
    comments, build, array_version = _parse_header(read_prefix(path), source_name)

    # comment block + column row
    header_lines = len(comments) + 1

    raw = _read_data(path, source_name)

    table = normalize_rows(
        raw,
        chrom_map=CHROM_MAP,
        source_name=source_name,
        header_lines=header_lines,
    )

    return ParseResult(
        table=GenotypeTable(table, vendor=VENDOR_ID),
        source=SourceInfo(
            vendor=VENDOR_ID,
            display_name="AncestryDNA V2",
            path=source_name,
            build=build,
            array_version=array_version,
            header_lines=header_lines,
            data_rows=table.height,
            representable_chroms=tuple(sorted({c.value for c in CHROM_MAP.values()})),
        ),
    )


def _read_data(path: Path, source_name: str) -> pl.DataFrame:
    """Read the tab-separated body.

    Everything is read as String and cast later, on purpose. Left to infer, Polars reads
    the chromosome column as an integer -- which is precisely the representation this
    adapter exists to eliminate -- and would treat an all-``0`` allele column as numeric.
    Explicit casting also means a bad position is caught by our own check, with a line
    number, instead of by a type error that names no row.
    """
    try:
        frame = pl.read_csv(
            path,
            separator="\t",
            comment_prefix="#",
            has_header=True,
            infer_schema=False,
            encoding="utf8-lossy",
        )
    except pl.exceptions.PolarsError as exc:
        # The header already validated, so this is a body problem, not a header one.
        raise ColumnCountError(
            f"{source_name}: the tab-separated body would not parse "
            f"({exc.__class__.__name__}). Ragged rows are the usual cause -- every data "
            f"row must have exactly {len(EXPECTED_COLUMNS)} tab-separated fields."
        ) from None

    if tuple(frame.columns) != EXPECTED_COLUMNS:
        # The prefix check above already validated the header row; reaching here means the
        # file changed shape between the two reads, or the column row repeats mid-file.
        raise MalformedHeaderError(
            f"{source_name}: expected body columns {list(EXPECTED_COLUMNS)}, "
            f"{describe_columns(tuple(frame.columns))}."
        )

    return frame.rename(
        {"chromosome": "chrom", "position": "pos", "allele1": "a1", "allele2": "a2"}
    )


ADAPTER = register(
    Adapter(
        vendor_id=VENDOR_ID,
        display_name="AncestryDNA V2",
        sniff=sniff,
        parse=parse,
        # Set only after `genetics ingest --expect-counts` reproduced the measured counts
        # of a real V2.0 export (M1.2). That check runs locally and never in CI, because
        # the file can never be committed -- so this flag is the only record that it ran.
        # 2026-08-15: 677,436 markers / 550 no-calls / 8,830 indels, and the sex-chromosome
        # counts in AGENTS.md section 2 reconcile exactly (X 25,231 called - 4 het = 25,227
        # homozygous; Y 1,661 called - 3 het = 1,658; MT 263).
        verified_against_real_export=True,
    )
)
