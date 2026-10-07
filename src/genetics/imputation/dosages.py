"""Strict VCF observations, allele-oriented dosages and per-ALT Beagle DR2."""

from __future__ import annotations

import gzip
import math
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import ClassVar

from genetics.external.harmonize import SAMPLE_ID
from genetics.privacy import NoGenotypeRepr

from .target import ImputationError, Target


@dataclass(frozen=True, repr=False)
class DosageRecord(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("source", "status", "ploidy")
    chrom: str
    pos_grch37: int
    ref: str
    alt: tuple[str, ...]
    genotype: tuple[int, ...] | None
    storage_genotype: tuple[int, ...]
    dosage: tuple[float, ...]
    storage_dosage: tuple[float, ...]
    dr2: tuple[float, ...] | None
    ploidy: int
    source: str
    status: str
    array_outcome: str | None
    dosage_method: str
    quality_scope: str

    def to_dict(self) -> dict[str, object]:
        """Private: contains genotype-derived observations."""
        return asdict(self)


def _vector(value: str, cardinality: int, upper: float) -> tuple[float, ...]:
    try:
        result = tuple(float(v) for v in value.split(","))
    except ValueError:
        raise ImputationError("Beagle output has a nonnumeric dosage or quality value.") from None
    if len(result) != cardinality or any(
        not math.isfinite(v) or not 0 <= v <= upper for v in result
    ):
        raise ImputationError("Beagle output dosage/quality cardinality or range is invalid.")
    return result


def read_output(path: Path, target: Target, *, phase_only: bool = False) -> Iterator[DosageRecord]:
    """Validate even resumed outputs. A missing typed call is never labelled direct.

    Direct dosages are exact allele counts, not uncertainty estimates. Beagle does not
    estimate DR2 for sporadic missing calls filled in its phasing stage: keep None.
    Haploid regions use native single-copy targets, dosages and quality estimates.
    Wrong-ploidy outputs are refused rather than converted from a diploid model.
    """
    region = target.region
    if region.ploidy is None:
        raise ImputationError("Cannot interpret output with unresolved biological ploidy.")
    seen_typed: set[int] = set()
    previous: tuple[int, str, str] | None = None
    at_position: set[tuple[str, str]] = set()
    header = False
    count = 0
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("##"):
                    if header:
                        raise ImputationError("Beagle metadata follows its sample header.")
                    continue
                if line.startswith("#"):
                    fields = line.rstrip("\r\n").split("\t")
                    if header or fields != [
                        "#CHROM",
                        "POS",
                        "ID",
                        "REF",
                        "ALT",
                        "QUAL",
                        "FILTER",
                        "INFO",
                        "FORMAT",
                        SAMPLE_ID,
                    ]:
                        raise ImputationError(
                            "Beagle output does not identify the exact target sample."
                        )
                    header = True
                    continue
                fields = line.rstrip("\r\n").split("\t")
                if not header or len(fields) != 10:
                    raise ImputationError("Beagle output has invalid columns or no sample header.")
                chrom, raw_pos, _, ref, raw_alt = fields[:5]
                pos = int(raw_pos)
                alt = tuple(raw_alt.split(","))
                if (
                    chrom != region.chrom
                    or not region.start <= pos <= region.end
                    or (previous is not None and pos < previous[0])
                    or not ref
                    or not alt
                    or any(not a or a == "." for a in alt)
                    or len(set((ref, *alt))) != len(alt) + 1
                ):
                    raise ImputationError(
                        "Beagle output markers/alleles disagree with the job region."
                    )
                if previous is None or pos != previous[0]:
                    at_position.clear()
                if (ref, raw_alt) in at_position:
                    raise ImputationError("Beagle output repeats a variant.")
                at_position.add((ref, raw_alt))
                previous = (pos, ref, raw_alt)
                names = fields[8].split(":")
                values = fields[9].split(":")
                if len(names) != len(values) or len(set(names)) != len(names) or "GT" not in names:
                    raise ImputationError("Beagle output FORMAT cardinality is invalid.")
                formats = dict(zip(names, values, strict=True))
                gt = tuple(int(a) for a in formats["GT"].split("|"))
                if len(gt) != region.ploidy or any(not 0 <= a <= len(alt) for a in gt):
                    raise ImputationError(
                        "Beagle output must have complete phased storage genotypes."
                    )
                storage_gt = gt
                info_items = fields[7].split(";")
                info = dict(v.split("=", 1) for v in info_items if "=" in v)
                if len(info) != sum("=" in v for v in info_items):
                    raise ImputationError("Beagle output repeats an INFO value.")
                typed = target.sites.get(pos)
                imp = "IMP" in info_items
                if typed is not None:
                    if pos in seen_typed or (ref, raw_alt) != (typed.ref, typed.alt) or imp:
                        raise ImputationError("Beagle changed a typed marker's identity or source.")
                    seen_typed.add(pos)
                    if typed.gt is not None and tuple(sorted(gt)) != typed.gt:
                        raise ImputationError("Beagle changed an eligible original typed call.")
                elif phase_only or not imp:
                    raise ImputationError(
                        "Beagle output contains an unexpected untyped marker/source."
                    )
                if phase_only and imp:
                    raise ImputationError(
                        "Phase-only output unexpectedly contains imputed markers."
                    )
                source = (
                    "direct"
                    if typed is not None and typed.gt is not None
                    else ("imputed_no_call" if typed is not None else "imputed_untyped")
                )
                counts = tuple(float(gt.count(i)) for i in range(1, len(alt) + 1))
                ds = _vector(formats["DS"], len(alt), region.ploidy) if "DS" in formats else None
                dr2 = _vector(info["DR2"], len(alt), 1) if "DR2" in info else None
                if imp and (ds is None or dr2 is None):
                    raise ImputationError("Imputed untyped variants require per-ALT DS and DR2.")
                # The pinned ImputedRecBuilder independently rounds each ALT DS to
                # hundredths. The sum can exceed ploidy by at most 0.005 per ALT.
                if ds is not None and sum(ds) > region.ploidy + 0.005 * len(ds) + 0.000001:
                    raise ImputationError("Beagle alternate dosages exceed storage ploidy.")
                if (
                    source == "direct"
                    and ds is not None
                    and any(abs(a - b) > 0.0001 for a, b in zip(ds, counts, strict=True))
                ):
                    raise ImputationError("Beagle dosage disagrees with an original typed call.")
                # The second invocation sees a phase-filled no-call as typed. Its DR2
                # cannot describe the uncertainty lost during the first invocation.
                if source == "imputed_no_call":
                    dr2 = None
                storage_ds = counts if source != "imputed_untyped" or ds is None else ds
                method = (
                    "observed_allele_count"
                    if source == "direct"
                    else (
                        "beagle_DS"
                        if source == "imputed_untyped" and ds is not None
                        else "phased_hardcall_only"
                    )
                )
                count += 1
                yield DosageRecord(
                    chrom,
                    pos,
                    ref,
                    alt,
                    storage_gt,
                    storage_gt,
                    storage_ds,
                    storage_ds,
                    dr2,
                    region.ploidy,
                    source,
                    "resolved",
                    target.decisions.get(pos),
                    method,
                    ("beagle_haploid_dosage" if region.ploidy == 1 else "beagle_diploid_dosage")
                    if dr2 is not None
                    else "not_estimated",
                )
        if not count or seen_typed != set(target.sites):
            raise ImputationError("Beagle output is empty or lost eligible typed markers.")
    except (OSError, EOFError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ImputationError):
            raise
        raise ImputationError("Beagle output is malformed or unreadable.") from None
