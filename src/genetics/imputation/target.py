"""Consumer calls aligned to full-reference alleles, with explicit exclusions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from genetics.external.harmonize import SAMPLE_ID, orient, panel_exclusion, site_alleles
from genetics.ingest.normalize import GRCH37_LENGTHS
from genetics.ingest.schema import CallStatus, Chrom, GenotypeTable
from genetics.privacy import NoGenotypeRepr
from genetics.qc.report import InferredSex
from genetics.qc.sex_regions import PAR_GRCH37


class ImputationError(ValueError):
    """Categorical errors: never include private calls, identifiers or coordinates."""


@dataclass(frozen=True)
class Region:
    name: str
    chrom: str
    start: int
    end: int
    map_key: str
    ploidy: int | None

    @property
    def interval(self) -> str:
        return f"{self.chrom}:{self.start}-{self.end}"


def regions(chrom: str, sex: InferredSex) -> tuple[Region, ...]:
    length = GRCH37_LENGTHS[Chrom(chrom)]
    if chrom != "X":
        return (Region(f"chr{chrom}", chrom, 1, length, chrom, 2),)
    (a, b), (c, d) = PAR_GRCH37["X"]
    ploidy = {InferredSex.MALE: 1, InferredSex.FEMALE: 2}.get(sex)
    return (
        Region("X_left", "X", 1, a - 1, "X", ploidy),
        Region("X_par1", "X", a, b, "X_par1", 2),
        Region("X_nonpar", "X", b + 1, c - 1, "X", ploidy),
        Region("X_par2", "X", c, d, "X_par2", 2),
        Region("X_right", "X", d + 1, length, "X", ploidy),
    )


@dataclass(frozen=True, repr=False)
class TypedSite(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ()
    pos: int
    ref: str
    alt: str
    gt: tuple[int, ...] | None
    outcome: str


@dataclass(frozen=True, repr=False)
class Target(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("n_called",)
    region: Region
    sites: dict[int, TypedSite]
    decisions: dict[int, str]

    @property
    def n_called(self) -> int:
        return sum(s.gt is not None for s in self.sites.values())

    def summary(self) -> dict[str, object]:
        return {
            "region": self.region.name,
            "ploidy": self.region.ploidy,
            "positions": len(self.decisions),
            "written": len(self.sites),
            "called": self.n_called,
            "outcomes": dict(sorted(Counter(self.decisions.values()).items())),
        }

    def write(self, path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(
                "##fileformat=VCFv4.2\n##reference=GRCh37\n"
                f"##contig=<ID={self.region.chrom}>\n"
                '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
                f"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{SAMPLE_ID}\n"
            )
            for s in self.sites.values():
                gt = (
                    ("." if self.region.ploidy == 1 else "./.")
                    if s.gt is None
                    else "/".join(map(str, s.gt))
                )
                handle.write(
                    f"{self.region.chrom}\t{s.pos}\t.\t{s.ref}\t{s.alt}\t.\tPASS\t.\tGT\t{gt}\n"
                )


def prepare_target(
    table: GenotypeTable,
    region: Region,
    panel: Mapping[int, tuple[str, str] | None],
) -> Target:
    """One decision per distinct array position; no rsID or probe ordering fallback."""
    probes: dict[int, list[tuple[str | None, str]]] = {}
    for chrom, pos, gt, status in table.frame.select(
        "chrom", "pos_grch37", "genotype", "call_status"
    ).iter_rows():
        if chrom == region.chrom and region.start <= pos <= region.end:
            probes.setdefault(pos, []).append((gt, status))
    sites: dict[int, TypedSite] = {}
    decisions: dict[int, str] = {}
    for pos, values in sorted(probes.items()):
        outcome = "not_in_panel"
        gt_indices: tuple[int, ...] | None = None
        marker = panel.get(pos)
        if region.ploidy is None:
            outcome = "unresolved_ploidy"
        elif pos in panel and marker is None:
            outcome = "duplicate_panel_position"
        elif marker is not None:
            alleles = site_alleles(*marker)
            exclusion = panel_exclusion(alleles)
            calls = {g for g, _ in values if g is not None and set(g) <= set("ACGT")}
            invalid_ploidy = any(
                s == CallStatus.HET_HAPLOID or (region.ploidy == 2 and s == CallStatus.HEMIZYGOUS)
                for _, s in values
            )
            if exclusion is not None:
                outcome = exclusion.value
            elif invalid_ploidy or (region.ploidy == 1 and any(len(set(g)) != 1 for g in calls)):
                outcome = "ploidy_conflict"
            elif len(calls) > 1:
                outcome = "duplicate_conflict"
            elif not calls:
                outcome = "array_indel" if any(g is not None for g, _ in values) else "no_call"
            else:
                indices, oriented = orient(next(iter(calls)), alleles)
                outcome = oriented.value
                if indices is not None:
                    if len(indices) != 2:
                        raise ImputationError("Normalized target has invalid allele cardinality.")
                    gt_indices = (indices[0],) if region.ploidy == 1 else indices
            if outcome in {"as_written", "complemented", "no_call"}:
                sites[pos] = TypedSite(pos, *marker, gt_indices, outcome)
        decisions[pos] = outcome
    return Target(region, sites, decisions)
