"""Model-dependent archaic f4 ratios on directly typed sites (M6.3).

These are array statistics, not detected introgressed tracts or measured percentages
of the genome. Prüfer 2017 S8 and Bergström 2020's supplement specify the estimators.
We keep their signed results, quantify block uncertainty, and expose sensitivity to
transitions and Denisovan allele sharing. Ascertainment error is not a sampling SE.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any, ClassVar

from genetics.ancestry.eigenstrat import hasharr, open_packed, read_ind, read_individuals, read_snp
from genetics.engine.evidence import AssembledCard
from genetics.ingest.schema import GenotypeTable
from genetics.paths import references_dir
from genetics.privacy import NoGenotypeRepr

SOURCES = frozenset({"neanderthal_f4", "denisovan_f4"})
AUTOSOMES = frozenset(str(c) for c in range(1, 23))
BASES = frozenset("ACGT")
TRANSITIONS = (frozenset("AG"), frozenset("CT"))
REFERENCE_IDS = {
    "altai": "AltaiNeanderthal_snpAD.DG",
    "vindija": "Vindija.DG",
    "denisova": "Denisova3_snpAD.DG",
    "chimp": "Chimp.REF",
}
FORMULAS = {
    "neanderthal_f4": "f4(X, Mbuti; Altai, Chimp) / f4(Vindija, Mbuti; Altai, Chimp)",
    "denisovan_f4": "f4(Mbuti, Vindija; Han, X) / f4(Mbuti, Vindija; Han, Denisova)",
}
WARNINGS = (
    "Array ascertainment and unobserved sites can bias these ratios. No empirical calibration "
    "for this chip/population exists; the range does not bound that systematic error.",
    "This is an allele-sharing model, not a measurement of genome-wide archaic DNA or "
    "a count of introgressed segments. Sequence-based estimates have higher resolution.",
    "The Mbuti baseline is assumed to have no archaic ancestry. The Denisovan estimator "
    "assumes Han and the target have similar Neanderthal ancestry and ignores Han's "
    "small Denisovan component; violations can bias even negative estimates.",
    "Chimp alleles approximate ancestral states; one archaic genome does not represent "
    "all introgressing lineages. Physical blocks approximate linkage, not genetic distance.",
)


class ArchaicError(RuntimeError):
    """Malformed reference input or parameters, with no personal calls in the error."""


@dataclass(frozen=True)
class ArchaicSettings:
    block_bp: int = 5_000_000
    min_informative: int = 2_000
    min_blocks: int = 20
    min_chromosomes: int = 10
    min_population_calls: float = 0.8
    min_population_size: int = 5

    def __post_init__(self) -> None:
        for name in ("block_bp", "min_informative", "min_blocks", "min_population_size"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ArchaicError(f"{name} must be a positive integer")
        if self.min_blocks < 2:
            raise ArchaicError("at least two jackknife blocks are required")
        if type(self.min_chromosomes) is not int or not 1 <= self.min_chromosomes <= 22:
            raise ArchaicError("min_chromosomes must be between 1 and 22")
        if (
            type(self.min_population_calls) not in (int, float)
            or not math.isfinite(self.min_population_calls)
            or not 0 < self.min_population_calls <= 1
        ):
            raise ArchaicError("min_population_calls must be in (0, 1]")


@dataclass(frozen=True, repr=False)
class ArchaicPanel(NoGenotypeRepr):
    sites: tuple[tuple[str, int, str, str], ...]
    frequencies: Mapping[str, tuple[float | None, ...]]
    provenance: Mapping[str, Any]
    _repr_fields: ClassVar[tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        if set(self.frequencies) != {*REFERENCE_IDS, "mbuti", "han"}:
            raise ArchaicError("archaic panel needs Altai, Vindija, Denisova, chimp, Mbuti and Han")
        if any(len(values) != len(self.sites) for values in self.frequencies.values()):
            raise ArchaicError("reference frequencies do not align with the sites table")
        if any(
            value is not None
            and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1)
            for values in self.frequencies.values()
            for value in values
        ):
            raise ArchaicError("reference allele frequencies must be finite fractions or missing")


@dataclass(frozen=True, repr=False)
class ArchaicResult(NoGenotypeRepr):
    data: Mapping[str, Any]
    _repr_fields: ClassVar[tuple[str, ...]] = ()

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(dict(self.data))


def reference_paths(root: Path | None = None) -> tuple[Path, Path, Path]:
    base = (root if root is not None else references_dir()) / "aadr"
    stem = "v66.p1_HO.aadr.patch.PUB"
    return base / f"{stem}.snp", base / f"{stem}.ind", base / f"{stem}.geno"


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_panel(
    paths: tuple[Path, Path, Path],
    *,
    wanted: Sequence[tuple[str, int]],
    settings: ArchaicSettings,
) -> ArchaicPanel:
    """Use the pinned diploid archaics and HGDP .DG populations, not HO duplicates.

    .ind identifiers and .snp order are checked against the packed header; all three
    files are hashed for the immutable result. No per-user cache or output is written.
    """
    snp, ind, geno = paths
    sites = read_snp(snp, wanted=wanted)
    individuals = read_ind(ind)
    counts = Counter(i.sample_id for i in individuals)
    if any(counts[sample_id] != 1 for sample_id in REFERENCE_IDS.values()):
        raise ArchaicError(
            "AADR must contain each required high-coverage archaic/outgroup exactly once"
        )
    populations = {
        label: [
            i
            for i in individuals
            if i.group == group and i.sample_id.startswith("HGDP") and i.sample_id.endswith(".DG")
        ]
        for label, group in (("mbuti", "Mbuti"), ("han", "Han"))
    }
    if any(len(group) < settings.min_population_size for group in populations.values()):
        raise ArchaicError("AADR lacks enough diploid Mbuti or Han reference individuals")
    selected = {i.index: i for i in individuals if i.sample_id in REFERENCE_IDS.values()}
    for group in populations.values():
        for individual in group:
            if counts[individual.sample_id] != 1:
                raise ArchaicError("duplicate reference individual identifier")
            selected[individual.index] = individual
    packed = open_packed(
        geno,
        n_individuals=len(individuals),
        n_sites=sites.n_read,
        individual_id_hash=hasharr(i.sample_id for i in individuals),
        site_id_hash=sites.id_hash,
    )
    decoded = {
        selected[index].sample_id: tuple(None if x == 3 else x / 2 for x in codes)
        for index, codes in read_individuals(packed, list(selected), sites.indices)
    }
    frequencies = {label: decoded[sample_id] for label, sample_id in REFERENCE_IDS.items()}
    for label, group in populations.items():
        needed = math.ceil(settings.min_population_calls * len(group))
        means: list[float | None] = []
        for row in zip(*(decoded[i.sample_id] for i in group), strict=True):
            called = [x for x in row if x is not None]
            means.append(sum(called) / len(called) if len(called) >= needed else None)
        frequencies[label] = tuple(means)
    return ArchaicPanel(
        tuple((r["chrom"], r["pos"], r["a1"], r["a2"]) for r in sites.frame.iter_rows(named=True)),
        frequencies,
        {
            "source": "aadr",
            "version": "v66.p1 HO patch",
            "build": "GRCh37",
            "archaic_ids": dict(REFERENCE_IDS),
            "population_ids": {
                label: [i.sample_id for i in group] for label, group in populations.items()
            },
            "input_sha256": {path.name: _sha256(path) for path in paths},
            "quality": "AADR published calls; original sequence depth/quality masks "
            "are unavailable here",
        },
    )


def jackknife_ratio(
    blocks: Sequence[tuple[float, float, int]], settings: ArchaicSettings
) -> dict[str, Any]:
    """Weighted delete-m jackknife, Patterson 2005 eqs. 1, 3 and 4.

    Weight = count of sites with nonzero numerator OR denominator (Prüfer S8).
    Intervals centre on the bias-corrected ratio, not a clamped percentage.
    A denominator whose own interval includes zero has no stable ratio interval.
    """
    usable = [b for b in blocks if b[2] > 0]
    n = sum(b[2] for b in usable)
    num = math.fsum(b[0] for b in usable)
    den = math.fsum(b[1] for b in usable)
    out: dict[str, Any] = {
        "n_informative": n,
        "n_blocks": len(usable),
        "numerator_sum": num,
        "denominator_sum": den,
        "ratio": None,
        "standard_error": None,
        "interval": None,
        "reason": None,
    }
    if n < settings.min_informative or len(usable) < settings.min_blocks:
        out["reason"] = "insufficient informative sites or independent blocks"
        return out
    if abs(den) <= 1e-12 or any(abs(den - b[1]) <= 1e-12 for b in usable):
        out["reason"] = "zero or unstable reference denominator"
        return out
    # The denominator is a mean contribution per informative site. Estimate its
    # uncertainty with the same weights so an uncertain divisor cannot look precise.
    den_mean = den / n
    den_variance = math.fsum(
        b[2] / (n - b[2]) * (b[1] / b[2] - den_mean) ** 2 for b in usable
    ) / len(usable)
    if abs(den_mean) <= 1.96 * math.sqrt(den_variance):
        out["reason"] = "reference denominator interval includes zero"
        return out
    theta = num / den
    pseudo = [
        (n / weight, (n / weight) * theta - (n / weight - 1) * ((num - ni) / (den - di)))
        for ni, di, weight in usable
    ]
    corrected = math.fsum(value / h for h, value in pseudo)
    variance = math.fsum((value - corrected) ** 2 / (h - 1) for h, value in pseudo) / len(pseudo)
    se = math.sqrt(variance)
    if not all(math.isfinite(x) for x in (corrected, se)):
        out["reason"] = "nonfinite ratio uncertainty"
        return out
    out.update(
        ratio=corrected, standard_error=se, interval=[corrected - 1.96 * se, corrected + 1.96 * se]
    )
    return out


def compute_archaic(
    table: GenotypeTable, panel: ArchaicPanel, *, settings: ArchaicSettings | None = None
) -> Mapping[str, ArchaicResult]:
    policy = settings or ArchaicSettings()
    rows = [r for r in table.frame.iter_rows(named=True) if r["chrom"] in AUTOSOMES]
    sample_counts = Counter((r["chrom"], r["pos_grch37"]) for r in rows)
    calls = {(r["chrom"], r["pos_grch37"]): r for r in rows}
    reference_counts = Counter((s[0], s[1]) for s in panel.sites)
    # A duplicated coordinate is ambiguous even when its calls happen to agree.
    shared = missing = incompatible = duplicates = 0
    blocks: dict[str, dict[tuple[str, int], list[float]]] = {
        name: defaultdict(lambda: [0.0, 0.0, 0.0])
        for name in (
            "neanderthal_all",
            "neanderthal_transversions",
            "neanderthal_denisovan_ancestral",
            "denisovan_all",
            "denisovan_transversions",
        )
    }
    chromosomes: dict[str, set[str]] = {name: set() for name in blocks}
    for idx, (chrom, pos, first, second) in enumerate(panel.sites):
        row = calls.get((chrom, pos))
        if (
            row is None
            or chrom not in AUTOSOMES
            or first not in BASES
            or second not in BASES
            or first == second
        ):
            continue
        if sample_counts[(chrom, pos)] != 1 or reference_counts[(chrom, pos)] != 1:
            duplicates += 1
            continue
        shared += 1
        if row["call_status"] != "called" or row["a1"] is None or row["a2"] is None:
            missing += 1
            continue
        if row["a1"] not in {first, second} or row["a2"] not in {first, second}:
            incompatible += 1
            continue
        x = (int(row["a1"] == first) + int(row["a2"] == first)) / 2
        f = {key: values[idx] for key, values in panel.frequencies.items()}
        tv = frozenset((first, second)) not in TRANSITIONS
        block = (chrom, (pos - 1) // policy.block_bp)
        for lineage in ("neanderthal", "denisovan"):
            required = (
                ("mbuti", "altai", "vindija", "chimp")
                if lineage == "neanderthal"
                else ("mbuti", "vindija", "han", "denisova")
            )
            if any(f[key] is None for key in required):
                continue
            # Explicit values below follow the missingness check above.
            b, v = float(f["mbuti"]), float(f["vindija"])  # type: ignore[arg-type]
            if lineage == "neanderthal":
                a, c = float(f["altai"]), float(f["chimp"])  # type: ignore[arg-type]
                num, den = (x - b) * (a - c), (v - b) * (a - c)
            else:
                h, d = float(f["han"]), float(f["denisova"])  # type: ignore[arg-type]
                num, den = (b - v) * (h - x), (b - v) * (h - d)
            names = [f"{lineage}_all"]
            if tv:
                names.append(f"{lineage}_transversions")
            if lineage == "neanderthal" and f["denisova"] == f["chimp"] and f["chimp"] in (0, 1):
                names.append("neanderthal_denisovan_ancestral")
            if num == 0 and den == 0:
                continue
            for name in names:
                bucket = blocks[name][block]
                bucket[0] += num
                bucket[1] += den
                bucket[2] += 1
                chromosomes[name].add(chrom)
    results = {}
    for source in sorted(SOURCES):
        lineage = source.removesuffix("_f4")
        variants = []
        for name, bins in blocks.items():
            if not name.startswith(lineage):
                continue
            diagnostic = jackknife_ratio([(n, d, int(w)) for n, d, w in bins.values()], policy)
            diagnostic.update(
                filter=name.removeprefix(lineage + "_"),
                chromosomes=sorted(chromosomes[name], key=int),
            )
            if len(chromosomes[name]) < policy.min_chromosomes:
                diagnostic.update(
                    ratio=None,
                    standard_error=None,
                    interval=None,
                    reason="insufficient autosomal breadth",
                )
            variants.append(diagnostic)
        # Neanderthal's Denisovan-ancestral orientation is the reported default:
        # the unrestricted result remains visible as a confounding diagnostic.
        primary_filter = "denisovan_ancestral" if lineage == "neanderthal" else "all"
        primary = next(v for v in variants if v["filter"] == primary_filter)
        intervals = [v["interval"] for v in variants if v["interval"] is not None]
        interval = (
            [min(i[0] for i in intervals), max(i[1] for i in intervals)]
            if primary["interval"] is not None
            else None
        )
        warnings = list(WARNINGS)
        if any(v["interval"] is None for v in variants):
            warnings.append(
                "One or more sensitivity filters have insufficient coverage "
                "or an unstable denominator."
            )
        if interval is not None and (interval[0] < 0 or interval[1] > 1):
            warnings.append(
                "Signed bounds outside [0, 1] are retained; they indicate sampling "
                "uncertainty or model mismatch, not negative DNA."
            )
        results[source] = ArchaicResult(
            {
                "schema_version": 1,
                "source": source,
                "status": "computed" if interval is not None else "insufficient_coverage",
                "formula": FORMULAS[source],
                "primary_filter": primary_filter,
                "range": interval,
                "range_definition": "Envelope of available filter-specific approximate "
                "95% weighted block-jackknife intervals; not a calibrated "
                "95% genome-wide ancestry interval",
                "diagnostics": variants,
                "settings": asdict(policy),
                "reference": dict(panel.provenance),
                "n_array_autosomal_positions": len(sample_counts),
                "n_shared_reference_sites": shared,
                "n_missing_calls": missing,
                "n_incompatible_calls": incompatible,
                "n_duplicate_sites": duplicates,
                "warnings": warnings,
            }
        )
    return results


def infer_archaic_cards(
    cards: tuple[AssembledCard, ...],
    table: GenotypeTable,
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[AssembledCard, ...]:
    from genetics.structure.archaic_interpretation import assemble_archaic_card

    if not any(card.card.computation in SOURCES for card in cards):
        return cards
    paths = reference_paths()
    results: Mapping[str, ArchaicResult] = {}
    reason = None
    if any(not path.is_file() for path in paths):
        reason = (
            "Archaic estimation not run: AADR v66.p1 HO references are missing. "
            "Run `genetics refs fetch --only aadr`."
        )
    else:
        if progress:
            progress(
                "Estimating archaic allele-sharing ranges against AADR high-coverage references"
            )
        wanted = [
            (r[0], r[1])
            for r in table.frame.select("chrom", "pos_grch37").iter_rows()
            if r[0] in AUTOSOMES
        ]
        policy = ArchaicSettings()
        panel = load_panel(paths, wanted=wanted, settings=policy)
        results = compute_archaic(table, panel, settings=policy)
    return tuple(
        assemble_archaic_card(card.card, results.get(card.card.computation), reason=reason)
        if card.card.computation in SOURCES
        else card
        for card in cards
    )


def validate_result(data: Mapping[str, Any], source: str, status: str) -> None:
    """Reject corrupt saved ranges rather than rendering a plausible numeric result."""
    fields = {
        "schema_version",
        "source",
        "status",
        "formula",
        "primary_filter",
        "range",
        "range_definition",
        "diagnostics",
        "settings",
        "reference",
        "n_array_autosomal_positions",
        "n_shared_reference_sites",
        "n_missing_calls",
        "n_incompatible_calls",
        "n_duplicate_sites",
        "warnings",
    }
    if (
        set(data) != fields
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or data["source"] != source
        or data["status"] != status
    ):
        raise ArchaicError("invalid archaic result schema, source or status")
    if status not in {"computed", "insufficient_coverage"} or data["formula"] != FORMULAS[source]:
        raise ArchaicError("invalid archaic model or status")
    for key in fields:
        if key.startswith("n_") and (type(data[key]) is not int or data[key] < 0):
            raise ArchaicError("archaic counts must be nonnegative integers")
    if not isinstance(data["range_definition"], str) or not data["range_definition"].strip():
        raise ArchaicError("archaic range requires an uncertainty definition")
    if (
        not isinstance(data["warnings"], list)
        or not data["warnings"]
        or not all(isinstance(w, str) and w.strip() for w in data["warnings"])
    ):
        raise ArchaicError("archaic warnings must be text")
    if not isinstance(data["reference"], Mapping) or not isinstance(data["settings"], Mapping):
        raise ArchaicError("archaic provenance and parameters must be objects")
    if set(data["settings"]) != {f.name for f in dataclass_fields(ArchaicSettings)}:
        raise ArchaicError("saved archaic parameters must record the complete policy")
    try:
        policy = ArchaicSettings(**data["settings"])
    except (TypeError, ArchaicError) as exc:
        raise ArchaicError("invalid saved archaic parameters") from exc
    reference = data["reference"]
    if any(
        not isinstance(reference.get(k), str) or not reference[k].strip()
        for k in ("source", "version", "quality")
    ):
        raise ArchaicError("archaic reference needs source, version and quality metadata")
    ids = reference.get("archaic_ids")
    populations = reference.get("population_ids")
    if (
        not isinstance(ids, Mapping)
        or set(ids) != {"altai", "vindija", "denisova", "chimp"}
        or any(not isinstance(v, str) or not v.strip() for v in ids.values())
        or not isinstance(populations, Mapping)
        or set(populations) != {"mbuti", "han"}
        or any(
            not isinstance(v, list)
            or not v
            or any(not isinstance(identifier, str) or not identifier.strip() for identifier in v)
            for v in populations.values()
        )
    ):
        raise ArchaicError("archaic reference needs named genomes and baseline individuals")
    if reference.get("build") != "GRCh37" or not isinstance(reference.get("input_sha256"), Mapping):
        raise ArchaicError("archaic reference needs a build and file digests")
    if len(reference["input_sha256"]) != 3 or any(
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
        for digest in reference["input_sha256"].values()
    ):
        raise ArchaicError("invalid archaic reference digests")
    expected = {"all", "transversions"}
    primary_filter = "all"
    if source == "neanderthal_f4":
        expected.add("denisovan_ancestral")
        primary_filter = "denisovan_ancestral"
    if data["primary_filter"] != primary_filter:
        raise ArchaicError("incorrect archaic primary filter")
    diagnostics = data["diagnostics"]
    if not isinstance(diagnostics, list) or len(diagnostics) != len(expected):
        raise ArchaicError("missing archaic sensitivity diagnostics")
    intervals = []
    primary_available = False
    seen: set[str] = set()
    for item in diagnostics:
        if not isinstance(item, Mapping) or set(item) != {
            "filter",
            "chromosomes",
            "n_informative",
            "n_blocks",
            "numerator_sum",
            "denominator_sum",
            "ratio",
            "standard_error",
            "interval",
            "reason",
        }:
            raise ArchaicError("invalid archaic diagnostic schema")
        name = item["filter"]
        if not isinstance(name, str) or name not in expected or name in seen:
            raise ArchaicError("duplicate or unknown archaic sensitivity filter")
        seen.add(name)
        for key in ("n_informative", "n_blocks"):
            if type(item[key]) is not int or item[key] < 0:
                raise ArchaicError("invalid archaic diagnostic counts")
        chroms = item["chromosomes"]
        if (
            not isinstance(chroms, list)
            or any(not isinstance(c, str) or c not in AUTOSOMES for c in chroms)
            or len(set(chroms)) != len(chroms)
        ):
            raise ArchaicError("invalid archaic autosomal breadth")
        if item["n_blocks"] > item["n_informative"] or len(chroms) > item["n_blocks"]:
            raise ArchaicError("inconsistent archaic informative blocks or breadth")
        for key in ("numerator_sum", "denominator_sum"):
            if type(item[key]) not in (float, int) or not math.isfinite(item[key]):
                raise ArchaicError("nonfinite archaic diagnostic")
        bounds = item["interval"]
        if bounds is None:
            if (
                item["ratio"] is not None
                or item["standard_error"] is not None
                or not isinstance(item["reason"], str)
                or not item["reason"].strip()
            ):
                raise ArchaicError(
                    "unavailable archaic diagnostic needs a reason and no numeric ratio"
                )
            continue
        values = (item["ratio"], item["standard_error"])
        if (
            any(type(x) not in (float, int) or not math.isfinite(x) for x in values)
            or values[1] < 0
        ):
            raise ArchaicError("invalid archaic ratio or uncertainty")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or any(type(x) not in (float, int) or not math.isfinite(x) for x in bounds)
        ):
            raise ArchaicError("invalid archaic interval")
        if (
            not math.isclose(bounds[0], values[0] - 1.96 * values[1], abs_tol=1e-12)
            or not math.isclose(bounds[1], values[0] + 1.96 * values[1], abs_tol=1e-12)
            or item["reason"] is not None
            or item["n_informative"] < policy.min_informative
            or item["n_blocks"] < policy.min_blocks
            or len(chroms) < policy.min_chromosomes
            or abs(item["denominator_sum"]) <= 1e-12
        ):
            raise ArchaicError("inconsistent archaic interval or coverage")
        intervals.append(bounds)
        primary_available |= name == primary_filter
    if (status == "computed") != primary_available:
        raise ArchaicError("archaic status disagrees with primary estimator")
    bounds = data["range"]
    if not primary_available:
        if bounds is not None:
            raise ArchaicError("unavailable archaic result cannot have a numeric range")
    elif (
        not isinstance(bounds, list)
        or len(bounds) != 2
        or any(type(x) not in (float, int) or not math.isfinite(x) for x in bounds)
        or not math.isclose(bounds[0], min(i[0] for i in intervals), abs_tol=1e-12)
        or not math.isclose(bounds[1], max(i[1] for i in intervals), abs_tol=1e-12)
    ):
        raise ArchaicError("archaic range does not enclose its recorded diagnostics")
