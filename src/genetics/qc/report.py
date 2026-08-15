"""The QC report object (roadmap M1.5).

Plain dataclasses, no computation -- :mod:`genetics.qc.metrics` fills them in. Keeping
the shape separate from the arithmetic is what lets the run bundle (M4.1), the CLI (M1.8)
and the UI banner (M4.5) all agree on one structure.

Every rate is stored alongside the counts it came from. A bare "call rate 0.94" invites
the reader to guess whether that is 94% of a million markers or of seventeen; the counts
make the denominator visible, which matters most exactly when the number looks wrong.

Nothing here holds a genotype -- only counts, rates and enum values -- so the report is
safe to print, log and serialise. That is deliberate: it is the object the CLI emits and
the UI renders, and a QC summary that had to be redacted would be useless for both.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Literal


class InferredSex(StrEnum):
    """Chromosomal sex as inferred from the array. Not a karyotype, and not gender.

    ``AMBIGUOUS`` is a real answer, not a failure to produce one. Sex-chromosome
    aneuploidies, mosaicism, a poor-quality array and a genuinely intermediate profile all
    land here, and the honest response is to say so and let hemizygous handling stay
    unresolved (M6.4). Guessing would silently change how every X and Y call is read.
    """

    MALE = "male"
    FEMALE = "female"
    AMBIGUOUS = "ambiguous"


BuildVerdict = Literal["confirmed_37", "suspected_38", "indeterminate"]


@dataclass(frozen=True)
class ChromCallRate:
    """Call rate for one chromosome. Per-chromosome because a single failed array region
    shows up here and nowhere in the overall figure."""

    chrom: str
    total: int
    called: int
    call_rate: float


@dataclass(frozen=True)
class CallRates:
    total_markers: int
    called: int
    no_call: int
    call_rate: float
    by_chrom: tuple[ChromCallRate, ...] = ()


@dataclass(frozen=True)
class Heterozygosity:
    """Heterozygosity rates, computed on SNP loci only.

    Indels are excluded: ``I``/``D`` markers carry no sequence (AGENTS.md 4.2), their
    cluster separation on the array is poorer, and including them moves the rate for
    reasons that have nothing to do with the sample.
    """

    autosomal_loci: int
    autosomal_het: int
    autosomal_het_rate: float
    x_nonpar_loci: int
    x_nonpar_het: int
    x_nonpar_het_rate: float


@dataclass(frozen=True)
class SexInference:
    """The inferred sex plus every number that produced it.

    The inputs are kept because this drives hemizygous handling for the entire X and Y --
    if it is wrong, a whole class of results is wrong -- and because "ambiguous" is
    unhelpful without the two rates that made it ambiguous.
    """

    inferred: InferredSex
    x_het_rate: float
    x_nonpar_loci: int
    y_call_rate: float
    y_loci: int
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildCheck:
    """Evidence that the file really is on the build its header claims.

    Three independent layers, because the header is a claim and the coordinates are the
    fact:

    * ``declared`` -- what the header said. Already enforced by the adapter (M1.4).
    * ``coordinates_within_grch37`` -- no position past the end of its chromosome. A
      cheap, absolute check: a position beyond the sequence end is not a GRCh37
      coordinate whatever the header says.
    * the anchor counts -- known rsIDs sitting at their known GRCh37 or GRCh38
      coordinate. The strongest signal, and empty until M2 supplies verified positions.
    """

    declared: str
    coordinates_within_grch37: bool
    anchors_available: int
    anchors_found: int
    anchors_matching_37: int
    anchors_matching_38: int
    verdict: BuildVerdict


@dataclass(frozen=True)
class IndelSummary:
    """Indel markers are counted, never quietly dropped.

    The count belongs in QC because it is the size of what allele matching will exclude
    by default (AGENTS.md 4.2, M1.6). A section that silently skipped 8,830 markers would
    imply a completeness it does not have.

    This counts markers *observably* I/D coded, which means called ones. An uncalled
    marker is written ``0 0`` whatever its type, so the file does not record that it was
    an indel -- the information is absent from the export, not discarded here.
    """

    indel_markers: int


@dataclass(frozen=True)
class DuplicateSummary:
    """Repeated identifiers and positions.

    Real exports contain both: an rsID can appear twice after a dbSNP merge, and two
    probes can target one position. Reported rather than deduplicated, because which copy
    to keep is a matching decision (M3.2), not an ingest one.
    """

    duplicate_rsids: int
    duplicate_positions: int


@dataclass(frozen=True)
class QCReport:
    """Everything QC knows about one export."""

    vendor: str
    source_path: str
    call_rates: CallRates
    heterozygosity: Heterozygosity
    sex: SexInference
    build: BuildCheck
    indels: IndelSummary
    duplicates: DuplicateSummary
    het_haploid_calls: int = 0
    """Heterozygous calls at loci inferred single-copy. A contradiction, so a direct
    measure of how much to trust the sex inference and the array both."""

    warnings: tuple[str, ...] = field(default_factory=tuple)
    """Human-readable, ordered most-consequential first. Warnings never suppress a
    result -- per AGENTS.md 0.1A the job is to label, not to filter."""

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable form for the CLI (AGENTS.md section 3)."""
        payload = asdict(self)
        payload["sex"]["inferred"] = self.sex.inferred.value
        return payload
