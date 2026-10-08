"""Streaming PGS Catalog format-2 ingestion, without computing personal scores.

All authored columns survive parsing, including special models. A row's features
distinguish a haplotype or unresolved locus from an ordinary additive variant.
No alleles are flipped or inferred here.
"""

from __future__ import annotations

import csv
import gzip
import math
import re
import zlib
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from genetics.pgs.catalog import Catalog, PgsError, ScoreMetadata, check_id, fingerprint

FLAGS = ("is_haplotype", "is_diplotype", "is_interaction", "is_dominant", "is_recessive")
DOSAGE_WEIGHTS = ("dosage_0_weight", "dosage_1_weight", "dosage_2_weight")
BUILDS = {"GRCh37", "GRCh38", "NR"}


def _number(value: str, label: str, line: int) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise PgsError(f"Scoring row {line}: invalid {label}.") from exc
    if not math.isfinite(result):
        raise PgsError(f"Scoring row {line}: nonfinite {label}.")
    return result


def _position(value: str, label: str, line: int) -> int | None:
    if not value:
        return None
    if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        raise PgsError(f"Scoring row {line}: invalid {label}.")
    return int(value)


def _chrom(value: str, line: int) -> str | None:
    if not value:
        return None
    if value not in {*(str(i) for i in range(1, 23)), "X", "Y", "MT", "M", "XY"}:
        raise PgsError(f"Scoring row {line}: unsupported chromosome.")
    return {"M": "MT", "XY": "PAR"}.get(value, value)


def _header(handle: TextIO) -> tuple[dict[str, str], tuple[str, ...]]:
    headers: dict[str, str] = {}
    for line in handle:
        if line.startswith("#"):
            if line.startswith("##") or "=" not in line:
                continue
            key, value = line[1:].rstrip("\r\n").split("=", 1)
            if not key or key in headers:
                raise PgsError("Duplicate or empty scoring-header field.")
            headers[key] = value
            continue
        columns = tuple(line.rstrip("\r\n").split("\t"))
        break
    else:
        raise PgsError("Scoring file has no column header.")
    if headers.get("format_version") != "2.0":
        raise PgsError("Only PGS scoring-file format 2.0 is supported; no format is assumed.")
    if not {"pgs_id", "genome_build", "variants_number"} <= headers.keys():
        raise PgsError("Scoring header lacks score ID, build or variant count.")
    check_id(headers["pgs_id"])
    if headers["genome_build"] not in BUILDS:
        raise PgsError("Unknown original scoring-file genome build.")
    if "HmPOS_build" in headers and headers["HmPOS_build"] not in BUILDS - {"NR"}:
        raise PgsError("Unknown harmonized scoring-file genome build.")
    if (
        not re.fullmatch(r"[0-9]+", headers["variants_number"])
        or int(headers["variants_number"]) < 1
    ):
        raise PgsError("Scoring header has an invalid variant count.")
    if len(columns) != len(set(columns)) or any(not column for column in columns):
        raise PgsError("Scoring columns must be nonempty and unique.")
    if not {"effect_allele", "effect_weight"} <= set(columns):
        raise PgsError("Scoring columns lack effect allele or effect weight.")
    if not ({"chr_name", "chr_position"} <= set(columns) or "rsID" in columns):
        raise PgsError("Scoring columns lack a locus or variant identifier.")
    if ("hm_chr" in columns) != ("hm_pos" in columns):
        raise PgsError("Harmonized chromosome and position must be declared together.")
    if ("HmPOS_build" in headers) != ({"hm_chr", "hm_pos"} <= set(columns)):
        raise PgsError("Harmonized coordinates require their declared build and vice versa.")
    if any(k in columns for k in DOSAGE_WEIGHTS) and not set(DOSAGE_WEIGHTS) <= set(columns):
        raise PgsError("Dosage-specific weight columns must form a complete triple.")
    return headers, columns


@dataclass(frozen=True)
class ScoreVariant:
    row_number: int
    chrom: str | None
    position: int | None
    effect_allele: str
    effect_weight: float | None
    fields: Mapping[str, str]
    features: tuple[str, ...]


def _row(fields: Mapping[str, str], *, line: int, harmonized: bool) -> ScoreVariant:
    flags: dict[str, bool] = {}
    for key in FLAGS:
        value = fields.get(key, "").casefold()
        if value not in {"", "true", "false"}:
            raise PgsError(f"Scoring row {line}: invalid model flag.")
        flags[key] = value == "true"
    if flags["is_dominant"] and flags["is_recessive"]:
        raise PgsError(f"Scoring row {line}: conflicting inheritance models.")
    features = {key for key, enabled in flags.items() if enabled}
    for chr_key, pos_key in (("chr_name", "chr_position"), ("hm_chr", "hm_pos")):
        chrom = _chrom(fields.get(chr_key, ""), line)
        position = _position(fields.get(pos_key, ""), pos_key, line)
        if harmonized and chr_key == "hm_chr" and (chrom is None) != (position is None):
            raise PgsError(f"Scoring row {line}: incomplete coordinate pair.")
    prefix = "hm_" if harmonized else "chr_"
    chrom = _chrom(fields.get(prefix + ("chr" if harmonized else "name"), ""), line)
    position = _position(
        fields.get(prefix + ("pos" if harmonized else "position"), ""), "position", line
    )
    identifier = fields.get("rsID", "")
    if chrom is None or position is None:
        chrom = None
        position = None
        features.add("unresolved_locus")
        if not identifier:
            raise PgsError(f"Scoring row {line}: no locus or variant identifier.")
    allele = fields["effect_allele"]
    if not allele or allele == ".":
        raise PgsError(f"Scoring row {line}: missing effect allele.")
    complex_model = any(flags[k] for k in ("is_haplotype", "is_diplotype", "is_interaction"))
    hla = identifier.startswith("HLA-") or fields.get("imputation_method", "") != ""
    if hla:
        features.add("special_calling_method")
    if not re.fullmatch(r"[ACGT]+", allele):
        if allele in {"I", "D", "-"}:
            features.add("unresolved_indel")
        elif not complex_model and not hla:
            raise PgsError(f"Scoring row {line}: invalid effect allele definition.")
    if len(allele) != 1 or (fields.get("other_allele") and len(fields["other_allele"]) != 1):
        features.add("non_snv_alleles")
    other = fields.get("other_allele", "")
    if (
        other
        and not complex_model
        and not hla
        and (not re.fullmatch(r"[ACGTID-]+(?:[,/][ACGTID-]+)*", other) or other == allele)
    ):
        raise PgsError(f"Scoring row {line}: invalid other allele definition.")
    if fields.get("hm_inferOtherAllele"):
        features.add("inferred_other_allele")
    value = fields["effect_weight"]
    weight = _number(value, "effect weight", line) if value else None
    dosage_values = [fields.get(key, "") for key in DOSAGE_WEIGHTS]
    if any(dosage_values):
        if not all(dosage_values):
            raise PgsError(f"Scoring row {line}: incomplete dosage-specific weights.")
        for key, numeric in zip(DOSAGE_WEIGHTS, dosage_values, strict=True):
            _number(numeric, key, line)
        features.add("dosage_specific_weights")
    if weight is None and not all(dosage_values):
        raise PgsError(f"Scoring row {line}: missing effect weight.")
    for key in ("OR", "HR"):
        if fields.get(key) and _number(fields[key], key, line) <= 0:
            raise PgsError(f"Scoring row {line}: nonpositive ratio.")
    if fields.get("inclusion_criteria"):
        features.add("conditional_inclusion")
    if fields.get("variant_description"):
        features.add("variant_description")
    for key in ("hm_match_chr", "hm_match_pos"):
        if fields.get(key, "").casefold() not in {"", "true", "false"}:
            raise PgsError(f"Scoring row {line}: invalid harmonization flag.")
        if fields.get(key, "").casefold() == "false":
            features.add("harmonization_mismatch")
    return ScoreVariant(line, chrom, position, allele, weight, fields, tuple(sorted(features)))


@dataclass(frozen=True)
class ScoringFile:
    path: Path
    headers: Mapping[str, str]
    columns: tuple[str, ...]
    source: Mapping[str, Any]
    metadata: ScoreMetadata
    metadata_source: Mapping[str, Any]

    @property
    def build(self) -> str:
        return self.headers.get("HmPOS_build", self.headers["genome_build"])

    @classmethod
    def open(
        cls,
        path: Path,
        catalog: Catalog,
        *,
        pgs_id: str | None = None,
        expected_build: str | None = "GRCh37",
    ) -> ScoringFile:
        before = fingerprint(path)
        try:
            with _open_text(path) as handle:
                headers, columns = _header(handle)
        except (OSError, EOFError, UnicodeError, zlib.error) as exc:
            raise PgsError("Cannot decode the PGS scoring file.") from exc
        if pgs_id is not None and check_id(pgs_id) != headers["pgs_id"]:
            raise PgsError("Requested score ID disagrees with the scoring header.")
        named = re.fullmatch(r"(PGS[0-9]{6})(?:_hmPOS_(GRCh37|GRCh38))?\.txt(?:\.gz)?", path.name)
        if named and (
            named[1] != headers["pgs_id"]
            or (named[2] is not None and named[2] != headers.get("HmPOS_build"))
        ):
            raise PgsError("Scoring filename disagrees with declared score or harmonized build.")
        metadata = catalog.get(headers["pgs_id"])
        if len(metadata.records) == 1:
            row = metadata.records[0]
            original = row.get("Original Genome Build", "")
            if original not in {"", "NR"} and original != headers["genome_build"]:
                raise PgsError("Metadata and scoring file disagree on original genome build.")
            count = row.get("Number of Variants", "")
            if count and (not count.isdecimal() or int(count) != int(headers["variants_number"])):
                raise PgsError("Metadata and scoring file disagree on variant count.")
        result = cls(path, headers, columns, before, metadata, catalog.source)
        if expected_build is not None and result.build != expected_build:
            raise PgsError("Scoring coordinates do not match the requested genome build.")
        return result

    def iter_variants(self) -> Iterator[ScoreVariant]:
        if fingerprint(self.path) != dict(self.source):
            raise PgsError("Scoring source changed after opening.")
        count = 0
        try:
            with _open_text(self.path) as handle:
                headers, columns = _header(handle)
                if headers != self.headers or columns != self.columns:
                    raise PgsError("Scoring header changed after opening.")
                for count, values in enumerate(csv.reader(handle, delimiter="\t", strict=True), 1):
                    if len(values) != len(columns):
                        raise PgsError(f"Scoring row {count}: incorrect field count.")
                    yield _row(
                        dict(zip(columns, values, strict=True)),
                        line=count,
                        harmonized="HmPOS_build" in headers,
                    )
        except (OSError, EOFError, UnicodeError, csv.Error, zlib.error) as exc:
            raise PgsError("Cannot decode the PGS scoring rows.") from exc
        if count != int(self.headers["variants_number"]):
            raise PgsError("Scoring row count disagrees with the declared variant count.")
        if fingerprint(self.path) != dict(self.source):
            raise PgsError("Scoring source changed during iteration.")

    def inspect(self) -> dict[str, Any]:
        features: Counter[str] = Counter()
        rows = 0
        for variant in self.iter_variants():
            rows += 1
            features.update(variant.features)
        return {
            "pgs_id": self.headers["pgs_id"],
            "build": self.build,
            "headers": dict(self.headers),
            "columns": list(self.columns),
            "rows": rows,
            "features": dict(sorted(features.items())),
            "scoring_source": dict(self.source),
            "metadata_source": dict(self.metadata_source),
            "metadata": self.metadata.to_json(),
            "license_authority": "pgs_all_metadata_scores.csv: License/Terms of Use",
            "scoring_implemented": True,
            "score_computed": False,
        }


def _open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")
