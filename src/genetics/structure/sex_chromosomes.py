"""Literal sex-chromosome call patterns, not karyotypes (M6.4).

Only direct calls are used. Counts retain repeated probes, as QC does; the result
records duplicate counts and never treats these rates as independent trials.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

import polars as pl

from genetics.engine.evidence import AssembledCard
from genetics.ingest.indels import is_indel_expr
from genetics.ingest.schema import CallStatus, GenotypeTable
from genetics.privacy import NoGenotypeRepr
from genetics.qc.metrics import (
    FEMALE_MAX_Y_CALL,
    FEMALE_MIN_X_HET,
    MALE_MAX_X_HET,
    MALE_MIN_Y_CALL,
    MIN_SEX_LOCI,
    duplicate_summary,
    heterozygosity,
    infer_sex,
)
from genetics.qc.sex_regions import PAR_GRCH37, PAR_SOURCE, coordinate_par_expr, nonpar_expr

SOURCE = "sex_chromosome_profile"
SETTINGS = {
    "min_usable_x_loci": MIN_SEX_LOCI,
    "low_x_max": MALE_MAX_X_HET,
    "high_x_min": FEMALE_MIN_X_HET,
    "low_y_max": FEMALE_MAX_Y_CALL,
    "high_y_min": MALE_MIN_Y_CALL,
    "duplicate_policy": "retain and flag; rates count probes, not independent loci",
    "coordinate_system": "GRCh37, 1-based inclusive",
    "par_boundaries": {c: [list(pair) for pair in bounds] for c, bounds in PAR_GRCH37.items()},
    "par_source": PAR_SOURCE,
}
LIMIT = (
    "Not a karyotype. This export lacks probe intensity and copy-number measurements; "
    "it cannot establish XX/XY, XXY, XYY, a missing chromosome, or mosaicism. "
    "This pattern does not determine gender or reproductive phenotype."
)


class SexChromosomeError(RuntimeError):
    """Malformed stored measurement; messages never include personal calls or rates."""


@dataclass(frozen=True, repr=False)
class SexChromosomeResult(NoGenotypeRepr):
    data: Mapping[str, Any]
    _repr_fields: ClassVar[tuple[str, ...]] = ()

    def as_dict(self) -> dict[str, Any]:
        return dict(self.data)


def _counts(table: GenotypeTable, chrom: str) -> dict[str, int]:
    frame = table.frame.filter(nonpar_expr(chrom))
    called = frame.filter(pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value)
    snps = called.filter(~is_indel_expr())
    return {
        "total": frame.height,
        "called": called.height,
        "snp_called": snps.height,
        "heterozygous_snps": snps.filter(pl.col("a1") != pl.col("a2")).height,
        "indel_called": called.height - snps.height,
    }


def _signals(
    x: Mapping[str, int], y: Mapping[str, int], settings: Mapping[str, Any] = SETTINGS
) -> dict[str, Any]:
    xr = round(x["heterozygous_snps"] / x["snp_called"], 6) if x["snp_called"] else None
    yr = round(y["called"] / y["total"], 6) if y["total"] else None
    xs = (
        "unavailable"
        if xr is None
        else "low"
        if xr <= settings["low_x_max"]
        else "high"
        if xr >= settings["high_x_min"]
        else "intermediate"
    )
    ys = (
        "absent"
        if yr is None
        else "low"
        if yr <= settings["low_y_max"]
        else "high"
        if yr >= settings["high_y_min"]
        else "intermediate"
    )
    enough = x["snp_called"] >= settings["min_usable_x_loci"]
    inferred = (
        "male"
        if enough and xs == "low" and ys in {"high", "absent"}
        else "female"
        if enough and xs == "high" and ys in {"low", "absent"}
        else "ambiguous"
    )
    return {
        "status": "computed" if enough else "insufficient_calls",
        "x_het_rate": xr,
        "y_call_rate": yr,
        "x_signal": xs,
        "y_signal": ys,
        "qc_inferred_sex": inferred,
    }


def compute_sex_chromosomes(table: GenotypeTable) -> SexChromosomeResult:
    x, y = _counts(table, "X"), _counts(table, "Y")
    sex = infer_sex(table, heterozygosity(table))
    signals = _signals(x, y)
    if signals["qc_inferred_sex"] != sex.inferred.value:
        raise SexChromosomeError("sex-chromosome reporting and QC inference disagree")
    duplicates = duplicate_summary(table)
    warnings = [*sex.notes, LIMIT]
    if y["total"] and y["total"] < MIN_SEX_LOCI:
        warnings.append(
            "Fewer than 100 non-PAR Y probes: a small denominator can exaggerate the Y signal. "
            "There is no validated Y-count floor for this export-only heuristic."
        )
    if y["heterozygous_snps"]:
        warnings.append(
            "Non-PAR Y includes heterozygous SNP calls. Error, cross-hybridisation or mixed "
            "samples can produce these; they do not establish additional Y copies."
        )
    if duplicates.duplicate_positions or duplicates.duplicate_rsids:
        warnings.append("Repeated probes are retained in the rates and can overweight a locus.")
    warnings.append(
        "Thresholds are broad QC heuristics, not validated chromosome diagnoses. "
        "Missingness, ancestry, homozygosity, probe error and mixed samples can change the pattern."
    )
    frame = table.frame
    return SexChromosomeResult(
        {
            "schema_version": 1,
            "source": SOURCE,
            **signals,
            "x": x,
            "y": y,
            "par_excluded": {
                "vendor_labelled": frame.filter(pl.col("chrom").cast(pl.String) == "PAR").height,
                "coordinate_x": frame.filter(coordinate_par_expr("X")).height,
                "coordinate_y": frame.filter(coordinate_par_expr("Y")).height,
            },
            "duplicate_positions": duplicates.duplicate_positions,
            "duplicate_rsids": duplicates.duplicate_rsids,
            "settings": dict(SETTINGS),
            "directly_typed_only": True,
            "intensity_available": False,
            "karyotype_determinable": False,
            "warnings": warnings,
        }
    )


def validate_result(data: Mapping[str, Any], status: str) -> None:
    """Validate saved measurements without recomputing a genome or reading references."""
    required = {
        "schema_version",
        "source",
        "status",
        "x_het_rate",
        "y_call_rate",
        "x_signal",
        "y_signal",
        "qc_inferred_sex",
        "x",
        "y",
        "par_excluded",
        "duplicate_positions",
        "duplicate_rsids",
        "settings",
        "directly_typed_only",
        "intensity_available",
        "karyotype_determinable",
        "warnings",
    }
    if (
        set(data) != required
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or data["source"] != SOURCE
        or data["status"] != status
        or data["directly_typed_only"] is not True
        or data["intensity_available"] is not False
        or data["karyotype_determinable"] is not False
    ):
        raise SexChromosomeError("invalid sex-chromosome result schema or method")
    settings = data["settings"]
    if not isinstance(settings, Mapping) or set(settings) != set(SETTINGS):
        raise SexChromosomeError("invalid sex-chromosome settings")
    for key in ("low_x_max", "high_x_min", "low_y_max", "high_y_min"):
        value = settings[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
            raise SexChromosomeError("invalid sex-chromosome threshold")
    if (
        type(settings["min_usable_x_loci"]) is not int
        or settings["min_usable_x_loci"] < 1
        or settings["low_x_max"] >= settings["high_x_min"]
        or settings["low_y_max"] >= settings["high_y_min"]
        or any(
            settings[k] != SETTINGS[k]
            for k in ("par_boundaries", "par_source", "coordinate_system", "duplicate_policy")
        )
    ):
        raise SexChromosomeError("inconsistent sex-chromosome settings")
    for chrom in ("x", "y"):
        counts = data[chrom]
        if (
            not isinstance(counts, Mapping)
            or set(counts) != {"total", "called", "snp_called", "heterozygous_snps", "indel_called"}
            or any(type(n) is not int or n < 0 for n in counts.values())
            or not 0
            <= counts["heterozygous_snps"]
            <= counts["snp_called"]
            <= counts["called"]
            <= counts["total"]
            or counts["snp_called"] + counts["indel_called"] != counts["called"]
        ):
            raise SexChromosomeError("invalid sex-chromosome counts")
    par = data["par_excluded"]
    if (
        not isinstance(par, Mapping)
        or set(par) != {"vendor_labelled", "coordinate_x", "coordinate_y"}
        or any(type(n) is not int or n < 0 for n in par.values())
        or any(
            type(data[k]) is not int or data[k] < 0
            for k in ("duplicate_positions", "duplicate_rsids")
        )
    ):
        raise SexChromosomeError("invalid PAR or duplicate counts")
    expected = _signals(data["x"], data["y"], settings)
    if any(
        data[key] != value or type(data[key]) is not type(value) for key, value in expected.items()
    ):
        raise SexChromosomeError("sex-chromosome rates or inference disagree with counts")
    warnings = data["warnings"]
    if (
        not isinstance(warnings, list)
        or not warnings
        or any(not isinstance(w, str) or not w.strip() for w in warnings)
    ):
        raise SexChromosomeError("sex-chromosome result needs caveats")
    if LIMIT not in warnings:
        raise SexChromosomeError("sex-chromosome result lacks its assay limitation")


def infer_sex_chromosome_cards(
    cards: tuple[AssembledCard, ...], table: GenotypeTable
) -> tuple[AssembledCard, ...]:
    from genetics.structure.sex_interpretation import assemble_sex_chromosome_card

    if not any(c.card.computation == SOURCE for c in cards):
        return cards
    result = compute_sex_chromosomes(table)
    return tuple(
        assemble_sex_chromosome_card(c.card, result) if c.card.computation == SOURCE else c
        for c in cards
    )
