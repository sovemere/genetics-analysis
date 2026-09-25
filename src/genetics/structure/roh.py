"""M6.1: long autosomal ROH, with reference-based MAF and LD filtering.

See docs/roh.md for the assay-specific parameter policy and denominator definition.
No interpretation of parental relationships is made here (M6.2 owns interpretation).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from genetics import __version__
from genetics.ancestry.reference_pca import array_marker_positions
from genetics.external.harmonize import (
    SAMPLE_ID,
    SiteOutcome,
    harmonizable_sites,
    read_panel_sites,
)
from genetics.external.pgen import to_pgen
from genetics.external.plink2 import Plink2
from genetics.external.plink19 import Plink19
from genetics.ingest.schema import GenotypeTable
from genetics.paths import cache_dir, is_inside_repo
from genetics.privacy import NoGenotypeRepr


class RohError(ValueError):
    """Unusable inputs or inconsistent tool output; never includes genotype rows."""


@dataclass(frozen=True)
class RohSettings:
    maf: float = 0.05
    reference_missing: float = 0.02
    ld_window_kb: int = 500
    ld_step: int = 1
    ld_r2: float = 0.2
    min_snps: int = 50
    min_kb: int = 5000
    density_kb: int = 100
    gap_kb: int = 500
    max_hets: int = 1
    window_snps: int = 50
    window_hets: int = 1
    window_missing: int = 2
    window_threshold: float = 0.05

    def __post_init__(self) -> None:
        for name in ("maf", "reference_missing", "ld_r2", "window_threshold"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value <= 1:
                raise RohError(f"{name} must be finite and in (0, 1]")
        if self.maf > 0.5:
            raise RohError("maf cannot exceed 0.5")
        for name in (
            "ld_window_kb",
            "ld_step",
            "min_snps",
            "min_kb",
            "density_kb",
            "gap_kb",
            "window_snps",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise RohError(f"{name} must be a positive integer")
        for name in ("max_hets", "window_hets", "window_missing"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise RohError(f"{name} must be a nonnegative integer")
        if self.window_hets + self.window_missing >= self.window_snps:
            raise RohError("a window must require at least one homozygous observed call")

    def arguments(self) -> list[str]:
        flags = {
            "snp": self.min_snps,
            "kb": self.min_kb,
            "density": self.density_kb,
            "gap": self.gap_kb,
            "het": self.max_hets,
            "window-snp": self.window_snps,
            "window-het": self.window_hets,
            "window-missing": self.window_missing,
            "window-threshold": self.window_threshold,
        }
        return [
            "--homozyg",
            *[item for key, value in flags.items() for item in (f"--homozyg-{key}", str(value))],
        ]


@dataclass(frozen=True)
class ReferenceInput:
    """An unpruned GRCh37 cohort VCF or pgen; not an individual's export.

    A pgen path includes its .pgen suffix. The cohort must be unrelated diploid
    reference samples; keep_file can select an ancestry-matched subset explicitly.
    """

    path: Path
    version: str
    population: str
    keep_file: Path | None = None

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.population.strip():
            raise RohError("reference version and population must be named")
        if not (self.path.name.endswith((".vcf", ".vcf.gz", ".pgen"))):
            raise RohError("reference must be an unpruned GRCh37 VCF or pgen")


@dataclass(frozen=True)
class Interval(NoGenotypeRepr):
    chrom: str
    start: int
    end: int
    n_snps: int

    @property
    def length_bp(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class RohResult(NoGenotypeRepr):
    segments: tuple[Interval, ...]
    assayed_intervals: tuple[Interval, ...]
    n_array_positions: int
    n_filtered_reference_markers: int
    n_analyzed_markers: int
    n_missing_calls: int
    settings: RohSettings
    provenance: tuple[dict[str, Any], ...]
    plink2_version: str
    plink19_version: str

    def as_dict(self) -> dict[str, Any]:
        denominator = sum(i.length_bp for i in self.assayed_intervals)
        total = sum(i.length_bp for i in self.segments)
        chroms = sorted({i.chrom for i in self.assayed_intervals}, key=int)
        warnings = [
            "Long ROH estimate only; short runs are outside this parameter policy.",
            "F_ROH uses observable autosomal spans, not the entire reference genome.",
            "Marker selection depends on the named reference population and pruning policy.",
        ]
        if len(chroms) < 22:
            warnings.append("Partial autosomal coverage; this is not a whole-genome estimate.")
        if self.n_missing_calls:
            warnings.append("Missing calls remain missing; ROH confidence depends on call quality.")
        if not denominator:
            warnings.append("No interval meets the minimum span and marker count requirements.")
        enough_calls = self.n_analyzed_markers - self.n_missing_calls >= (
            self.settings.window_snps - self.settings.window_missing - self.settings.window_hets
        )
        if not enough_calls:
            warnings.append("Too few observed calls for a scanning window; F_ROH is unavailable.")
        status = "computed" if denominator else "insufficient_coverage"
        if denominator and not enough_calls:
            status = "insufficient_calls"
        return {
            "schema_version": 1,
            "engine_version": __version__,
            "status": status,
            "total_roh_bp": total,
            "roh_count": len(self.segments),
            "longest_roh_bp": max((i.length_bp for i in self.segments), default=0),
            "f_roh": total / denominator if denominator and enough_calls else None,
            "denominator_bp": denominator,
            "denominator_definition": "sum of gap-bounded assayed autosomal spans (inclusive bp)",
            "chromosomes_assayed": chroms,
            "n_array_positions": self.n_array_positions,
            "n_filtered_reference_markers": self.n_filtered_reference_markers,
            "n_analyzed_markers": self.n_analyzed_markers,
            "n_missing_calls": self.n_missing_calls,
            "segments": [asdict(i) for i in self.segments],
            "assayed_intervals": [asdict(i) for i in self.assayed_intervals],
            "settings": asdict(self.settings),
            "references": list(self.provenance),
            "tools": {"plink2": self.plink2_version, "plink19": self.plink19_version},
            "warnings": warnings,
        }


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def assayed_intervals(
    markers: Sequence[tuple[str, int]], settings: RohSettings
) -> tuple[Interval, ...]:
    """Bound the denominator by typed markers, never bridging a large assay gap."""
    ordered = sorted(markers, key=lambda m: (int(m[0]), m[1]))
    if len(set(ordered)) != len(ordered):
        raise RohError("duplicate analyzed marker positions")
    blocks: list[list[tuple[str, int]]] = []
    for chrom, pos in ordered:
        if chrom not in {str(i) for i in range(1, 23)} or pos < 1:
            raise RohError("ROH markers must be positive GRCh37 autosomal positions")
        if (
            not blocks
            or blocks[-1][-1][0] != chrom
            or pos - blocks[-1][-1][1] > settings.gap_kb * 1000
        ):
            blocks.append([])
        blocks[-1].append((chrom, pos))
    # A sparse whole block may contain a dense eligible sub-run. Keep its full span
    # in the denominator; apply density to actual ROH calls, not to the denominator.
    return tuple(
        Interval(b[0][0], b[0][1], b[-1][1], len(b))
        for b in blocks
        if len(b) >= max(settings.min_snps, settings.window_snps)
        and b[-1][1] - b[0][1] + 1 >= settings.min_kb * 1000
    )


def read_segments(
    path: Path, markers: Sequence[tuple[str, int]], settings: RohSettings
) -> tuple[Interval, ...]:
    """Validate the native report before using it; no rounded KB column arithmetic."""
    segments: list[Interval] = []
    marker_set = set(markers)
    blocks = assayed_intervals(markers, settings)
    with path.open(encoding="utf-8") as stream:
        header = stream.readline().split()
        required = ("FID", "IID", "CHR", "POS1", "POS2", "NSNP")
        if not all(name in header for name in required) or len(set(header)) != len(header):
            raise RohError("invalid ROH report header")
        indices = [header.index(name) for name in required]
        previous: dict[str, int] = {}
        for line in stream:
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) != len(header):
                raise RohError("malformed ROH report row")
            _, sample_id, chrom, start, end, count = [fields[i] for i in indices]
            if sample_id != SAMPLE_ID:
                raise RohError("ROH report does not describe the harmonized sample")
            try:
                segment = Interval(chrom, int(start), int(end), int(count))
            except ValueError:
                raise RohError("invalid numeric field in ROH report") from None
            actual_count = sum(c == chrom and segment.start <= p <= segment.end for c, p in markers)
            if (
                segment.start > segment.end
                or segment.start <= previous.get(chrom, 0)
                or (chrom, segment.start) not in marker_set
                or (chrom, segment.end) not in marker_set
                or segment.n_snps != actual_count
                or segment.n_snps < settings.min_snps
                or segment.length_bp < settings.min_kb * 1000
                or segment.length_bp > settings.density_kb * 1000 * segment.n_snps
                or not any(
                    b.chrom == chrom and b.start <= segment.start and b.end >= segment.end
                    for b in blocks
                )
            ):
                raise RohError("ROH report contains an inconsistent or overlapping segment")
            previous[chrom] = segment.end
            segments.append(segment)
    return tuple(segments)


def compute_roh(
    table: GenotypeTable,
    references: Sequence[ReferenceInput],
    *,
    plink2: Plink2,
    plink19: Plink19,
    settings: RohSettings | None = None,
    workspace: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> RohResult:
    """Compute a single sample's ROH, retaining no scratch data after return or error.

    Reference filtering is performed before sample conversion. No MAF/LD estimate
    is taken from the sample. Reference inputs must have disjoint chromosomes.
    The caller chooses an unpruned diploid cohort; ancestry PCA artifacts are unsuitable.
    """
    policy = settings or RohSettings()
    if not references:
        raise RohError("at least one reference cohort is required")
    root = workspace if workspace is not None else cache_dir() / "roh"
    if is_inside_repo(root.resolve()):
        raise RohError("ROH workspace must be outside the repository")
    positions = array_marker_positions(table)
    if not positions:
        raise RohError("no autosomal array positions")
    root.mkdir(parents=True, exist_ok=True)
    all_markers: list[tuple[str, int]] = []
    all_segments: list[Interval] = []
    provenance: list[dict[str, Any]] = []
    seen_chroms: set[str] = set()
    filtered_count = missing_count = 0
    with TemporaryDirectory(prefix="roh-", dir=root) as scratch:
        work = Path(scratch)
        ranges = work / "array.bed"
        ranges.write_text("".join(f"{c}\t{p - 1}\t{p}\n" for c, p in positions), encoding="utf-8")
        for index, reference in enumerate(references):
            if progress:
                progress(f"Reference {index + 1}/{len(references)}: verify and filter")
            prefix = work / f"reference-{index}"
            source = reference.path
            inputs = (
                [source, source.with_suffix(".pvar"), source.with_suffix(".psam")]
                if source.suffix == ".pgen"
                else [source]
            )
            if reference.keep_file is not None:
                inputs.append(reference.keep_file)
            fingerprints = {p.name: _digest(p) for p in inputs}
            source_args = (
                ["--pfile", str(source.with_suffix(""))]
                if source.suffix == ".pgen"
                else ["--vcf", str(source)]
            )
            keep_args = ["--keep", str(reference.keep_file)] if reference.keep_file else []
            plink2.run(
                [
                    *source_args,
                    *keep_args,
                    "--autosome",
                    "--snps-only",
                    "just-acgt",
                    "--max-alleles",
                    "2",
                    "--extract",
                    "bed0",
                    str(ranges),
                    "--maf",
                    str(policy.maf),
                    "--geno",
                    str(policy.reference_missing),
                    "--set-all-var-ids",
                    "@:#:$r:$a",
                    "--make-pgen",
                    "--sort-vars",
                ],
                out=prefix,
            )
            psam = prefix.with_suffix(".psam")
            n_samples = sum(
                bool(line.strip()) and not line.startswith("#")
                for line in psam.read_text(encoding="utf-8").splitlines()
            )
            if n_samples < 50:
                raise RohError("ROH reference needs at least 50 diploid cohort members")
            sites = read_panel_sites(prefix.with_suffix(".pvar"))
            if sites.n_duplicate_positions:
                raise RohError("reference contains duplicate positions; resolve before ROH")
            sites, _ = harmonizable_sites(sites)
            if sites.n_sites < policy.window_snps:
                raise RohError("too few harmonizable reference markers for the scanning window")
            chroms = set(sites.frame.get_column("chrom").cast(str).to_list())
            if seen_chroms & chroms:
                raise RohError("reference inputs overlap chromosomes")
            seen_chroms.update(chroms)
            extract = work / "eligible.roh-markers.txt"
            extract.write_text(
                "\n".join(sites.frame.get_column("panel_id")) + "\n", encoding="utf-8"
            )
            pruned = work / f"pruned-{index}"
            if progress:
                progress(f"Reference {index + 1}/{len(references)}: LD pruning in cohort")
            plink2.run(
                [
                    "--pfile",
                    str(prefix),
                    "--extract",
                    str(extract),
                    "--indep-pairwise",
                    f"{policy.ld_window_kb}kb",
                    str(policy.ld_step),
                    str(policy.ld_r2),
                ],
                out=pruned,
            )
            eligible_count = sites.n_sites
            retained = set(pruned.with_suffix(".prune.in").read_text(encoding="utf-8").split())
            sites = type(sites)(
                sites.frame.filter(sites.frame["panel_id"].is_in(retained)),
                sites.source,
                sites.n_read,
                sites.n_duplicate_positions,
            )
            filtered_count += sites.n_sites
            if not sites.n_sites:
                raise RohError("reference pruning retained no markers")
            conversion = to_pgen(table, sites, plink=plink2, workspace=work, stem=f"sample-{index}")
            missing_count += conversion.report.counts.get(SiteOutcome.NO_CALL, 0)
            sample_sites = read_panel_sites(conversion.pvar)
            markers = [
                (str(c), int(p)) for c, p in sample_sites.frame.select("chrom", "pos").iter_rows()
            ]
            all_markers.extend(markers)
            native = work / f"native-{index}"
            plink2.run(["--pfile", str(conversion.pgen.with_suffix("")), "--make-bed"], out=native)
            if progress:
                progress(f"Reference {index + 1}/{len(references)}: calling long ROH")
            result_prefix = work / f"result-{index}"
            plink19.run(
                ["--bfile", str(native), "--autosome", *policy.arguments()], out=result_prefix
            )
            all_segments.extend(read_segments(result_prefix.with_suffix(".hom"), markers, policy))
            provenance.append(
                {
                    "version": reference.version,
                    "population": reference.population,
                    "input_sha256": fingerprints,
                    "n_reference_samples": n_samples,
                    "n_retained_markers": sites.n_sites,
                    "n_eligible_before_ld": eligible_count,
                    "marker_sha256": _digest(pruned.with_suffix(".prune.in")),
                    "build": "GRCh37",
                }
            )
    return RohResult(
        tuple(all_segments),
        assayed_intervals(all_markers, policy),
        len(positions),
        filtered_count,
        len(all_markers),
        missing_count,
        policy,
        tuple(provenance),
        plink2.version,
        plink19.version,
    )
