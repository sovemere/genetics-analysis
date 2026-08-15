"""23andMe-layout adapter -- a stub, on purpose (roadmap M1.3).

Its job is to prove the seam: a second vendor with a *structurally different* layout must
be addable without touching a single analysis module. If adding this file required
editing QC, the keying module, or anything downstream, the abstraction would be wrong.

Structurally different in four ways, all handled here rather than downstream:

* four columns, with the two alleles merged into one ``genotype`` field;
* letter chromosome codes (``X``, ``Y``, ``MT``) instead of ``23``-``26``;
* ``--`` for a no-call instead of ``0 0``;
* single-character genotypes at haploid loci, where AncestryDNA doubles the allele.

**This is not verified against a real 23andMe export.** It parses the synthetic
``other_vendor_layout.txt`` fixture and nothing else has ever been put through it, which
is why its adapter registers ``verified_against_real_export=False`` and why
``genetics ingest`` says so out loud. Two known gaps, both deliberate:

* Real files use ``i``-prefixed identifiers for tens of thousands of custom probes. They
  pass through untouched, but they resolve against no reference and M1.7's merge table
  does not know them.
* 23andMe does not distinguish PAR from X, so PAR markers arrive labelled ``X``. Sex
  inference (M1.5) excludes PAR from the X heterozygosity rate; with this layout it
  cannot, and the rate is very slightly inflated. Noted rather than silently corrected --
  inventing a PAR boundary would be worse than a documented approximation.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from genetics.ingest.errors import MalformedHeaderError, UnsupportedBuildError
from genetics.ingest.normalize import normalize_rows
from genetics.ingest.registry import Adapter, ParseResult, SourceInfo, register
from genetics.ingest.schema import Chrom, GenotypeTable

VENDOR_ID = "23andme_like"

EXPECTED_COLUMNS = ("rsid", "chromosome", "position", "genotype")

CHROM_MAP = {
    **{str(n): Chrom(str(n)) for n in range(1, 23)},
    "X": Chrom.X,
    "Y": Chrom.Y,
    "MT": Chrom.MT,
    "M": Chrom.MT,
}
"""No PAR entry: this layout does not distinguish it. See the module docstring."""

SUPPORTED_BUILD = "37"

_BUILD_RE = re.compile(r"build\s+(\d+)(?:\.\d+)?", re.IGNORECASE)
_HEADER_RE = re.compile(r"^#\s*rsid\s+chromosome\s+position\s+genotype\s*$", re.IGNORECASE)

NO_CALL_FIELD = "--"


def sniff(lines: Sequence[str]) -> bool:
    """Recognise the layout by its commented four-column header row.

    Not by the vendor name: the name appears in the comment prose of a real export but not
    reliably, and the column row is the thing that actually determines how to parse. The
    AncestryDNA sniffer keys on its vendor name and its header row has five columns, so
    the two cannot both claim a file -- which :func:`~genetics.ingest.registry.detect`
    would reject anyway rather than resolve by registration order.
    """
    return any(_HEADER_RE.match(line) for line in lines)


def _parse_header(lines: Sequence[str], source_name: str) -> tuple[int, str]:
    """Validate the comment block. Returns ``(header_line_count, build)``."""
    comments = [line for line in lines if line.startswith("#")]
    if not any(_HEADER_RE.match(line) for line in comments):
        raise MalformedHeaderError(
            f"{source_name}: no commented column header row. Expected a '#'-prefixed "
            f"tab-separated {list(EXPECTED_COLUMNS)}."
        )

    header_text = "\n".join(comments)
    match = _BUILD_RE.search(header_text)
    if match is None:
        raise MalformedHeaderError(
            f"{source_name}: the header declares no reference build, and an undeclared "
            "build cannot be assumed -- every coordinate downstream is GRCh37."
        )
    if match.group(1) != SUPPORTED_BUILD:
        raise UnsupportedBuildError(
            f"{source_name}: header declares reference build {match.group(1)}; this "
            f"pipeline is GRCh37 ({SUPPORTED_BUILD}) throughout."
        )

    return len(comments), match.group(1)


def parse(path: Path) -> ParseResult:
    """Parse a 23andMe-layout export into the normalized table."""
    from genetics.ingest.registry import read_prefix

    source_name = path.name
    header_lines, build = _parse_header(read_prefix(path), source_name)

    try:
        frame = pl.read_csv(
            path,
            separator="\t",
            comment_prefix="#",
            has_header=False,
            new_columns=list(EXPECTED_COLUMNS),
            infer_schema=False,
            encoding="utf8-lossy",
        )
    except pl.exceptions.PolarsError as exc:
        raise MalformedHeaderError(
            f"{source_name}: the tab-separated body would not parse "
            f"({exc.__class__.__name__}). Every data row must have exactly "
            f"{len(EXPECTED_COLUMNS)} fields."
        ) from None

    raw = _split_genotype(frame, source_name)

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
            display_name="23andMe-like layout (unverified stub)",
            path=source_name,
            build=build,
            array_version=None,
            header_lines=header_lines,
            data_rows=table.height,
        ),
    )


def _split_genotype(frame: pl.DataFrame, source_name: str) -> pl.DataFrame:
    """Turn the merged ``genotype`` field into the two allele columns normalize expects.

    Three cases, and getting the third wrong is the interesting risk:

    * ``--`` is this vendor's no-call. Rewritten to the shared ``0 0`` token pair so the
      no-call rule lives in exactly one place.
    * two characters: an ordinary diploid call, split.
    * **one character**: a haploid call -- male X/Y, and MT in everyone. This layout
      writes it once where AncestryDNA writes it twice. Doubling it here makes the two
      vendors agree on the normalized table, and the ambiguity that creates is the same
      one AncestryDNA already has, resolved the same way by sex inference in M1.5.
    """
    genotype = pl.col("genotype").str.strip_chars().str.to_uppercase()
    length = genotype.str.len_chars()

    bad = frame.with_row_index("_row").filter(
        (genotype != NO_CALL_FIELD) & ~length.is_between(1, 2)
    )
    if bad.height:
        raise MalformedHeaderError(
            f"{source_name}: {bad.height} row(s) have a genotype field that is neither "
            f"'{NO_CALL_FIELD}' nor one or two allele characters. First at line "
            f"{int(bad.item(0, '_row'))} of the body."
        )

    return frame.select(
        pl.col("rsid"),
        pl.col("chromosome").alias("chrom"),
        pl.col("position").alias("pos"),
        pl.when(genotype == NO_CALL_FIELD)
        .then(pl.lit("0"))
        .otherwise(genotype.str.slice(0, 1))
        .alias("a1"),
        pl.when(genotype == NO_CALL_FIELD)
        .then(pl.lit("0"))
        # slice(1, 1) is empty for a one-character genotype, so fall back to the first
        # character: a haploid call becomes the doubled pair the schema expects.
        .otherwise(
            pl.when(length == 1).then(genotype).otherwise(genotype.str.slice(1, 1)),
        )
        .alias("a2"),
    )


ADAPTER = register(
    Adapter(
        vendor_id=VENDOR_ID,
        display_name="23andMe-like layout (unverified stub)",
        sniff=sniff,
        parse=parse,
        verified_against_real_export=False,
    )
)
