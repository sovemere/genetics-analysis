"""Ingest: vendor exports in, one normalized table out (roadmap M1).

The public entry points, in the order you usually want them:

* :func:`read_export` -- sniff the vendor, parse, validate. Returns a ploidy-naive table.
* :func:`ingest` -- the same, then QC and ploidy resolution. What the CLI calls.

Everything downstream of this package reads only the normalized table described in
:mod:`genetics.ingest.schema`. That is the whole point: a new vendor is a new adapter,
never an edit to an analysis module (AGENTS.md section 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from genetics.ingest.errors import (
    ColumnCountError,
    EmptyExportError,
    IngestError,
    MalformedHeaderError,
    MalformedRowError,
    UnknownVendorError,
    UnsupportedBuildError,
)
from genetics.ingest.registry import Adapter, ParseResult, SourceInfo, adapters, detect
from genetics.ingest.schema import CallStatus, Chrom, GenotypeTable
from genetics.privacy import NoGenotypeRepr

if TYPE_CHECKING:
    # Import-time cycle, type-check-time not: `genetics.qc` imports this package, so a
    # runtime import here would be circular. Under `from __future__ import annotations`
    # the annotation is a string, so the type is real for mypy and costs nothing at
    # import. Typing the field as `object` instead -- the first attempt -- pushed an
    # `assert isinstance(...)` onto every caller to get the type back.
    from genetics.qc.report import QCReport

__all__ = [
    "Adapter",
    "CallStatus",
    "Chrom",
    "ColumnCountError",
    "EmptyExportError",
    "GenotypeTable",
    "IngestError",
    "IngestResult",
    "MalformedHeaderError",
    "MalformedRowError",
    "ParseResult",
    "SourceInfo",
    "UnknownVendorError",
    "UnsupportedBuildError",
    "adapters",
    "detect",
    "ingest",
    "read_export",
]


def read_export(path: Path) -> ParseResult:
    """Sniff, parse and validate a raw export.

    The table returned is **ploidy-naive**: every called row is
    :attr:`~genetics.ingest.schema.CallStatus.CALLED`, including hemizygous ones, because
    which loci are single-copy depends on inferred sex and that is QC's job. Use
    :func:`ingest` unless you specifically want the pre-QC state.
    """
    return detect(path).parse(path)


@dataclass(frozen=True)
class IngestResult(NoGenotypeRepr):
    """A parsed, QC'd, ploidy-resolved export.

    Inherits the genotype-safe ``__repr__``: this object holds the whole table, and the
    default dataclass ``repr`` would print it into any traceback that carries it.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("vendor", "n_markers")

    table: GenotypeTable
    source: SourceInfo
    qc: QCReport

    @property
    def vendor(self) -> str:
        return self.source.vendor

    @property
    def n_markers(self) -> int:
        return self.table.n_markers


def ingest(path: Path) -> IngestResult:
    """Full ingest: parse, QC, then resolve ploidy from the inferred sex.

    The ordering is load-bearing and is the reason this is one function rather than three
    calls at every call site. Sex is inferred from X heterozygosity and Y call rate, so it
    needs the parsed table; hemizygous handling needs the sex; and reading zygosity off a
    doubled X call before the sex is known is exactly the error AGENTS.md section 2 warns
    about.
    """
    from genetics.qc import resolve_ploidy, run_qc

    parsed = read_export(path)
    qc = run_qc(parsed.table, source=parsed.source)
    resolved = resolve_ploidy(parsed.table, sex=qc.sex.inferred)

    return IngestResult(table=resolved, source=parsed.source, qc=qc)
