"""Manifest-pinned HIBAG models, complete metadata and GRCh37 allele proofs."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import stat
import threading
import uuid
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, BinaryIO, cast

import polars as pl

from genetics.external.hibag import HIBAGRuntime
from genetics.hla import scripts
from genetics.paths import cache_dir, references_dir
from genetics.refs import manifest, postprocess

LOCI = ("A", "B", "C", "DRB1", "DQA1", "DQB1", "DPB1")
POPULATIONS = ("european", "asian", "hispanic", "african")
LICENSE = "LicenseRef-HIBAG-HLARES-Unspecified"
ALLELE = re.compile(r"[0-9]{2,3}:[0-9]{2,3}[A-Z]?")
HEX = re.compile(r"[a-f0-9]{64}")
BASES = frozenset("ACGT")
COMPLEMENT = str.maketrans("ACGT", "TGCA")
PANEL = "thousand_genomes_phase3_grch37"
PANEL_FILE = re.compile(
    r"ALL\.chr6\.phase3_shapeit2_mvncall_integrated_v5b\.20130502\.genotypes\.vcf\.gz"
)
STRAND_SOURCES = ("dbsnp", "panel")
DBSNP_PROVENANCE_VERSION = 2
"""The dbSNP index sidecar version frozen into saved evidence; a producer bump must be
added here deliberately rather than silently accepted or refused."""


class HLAError(ValueError):
    """Categorical public-safe failure; never include sample values or R diagnostics."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            raise OSError
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, algorithm).hexdigest()
    except (OSError, ValueError, RuntimeError):
        raise HLAError("HLA input is not a readable regular file.") from None


def tsv(path: Path, columns: tuple[str, ...], *, limit: int = 8_000_000) -> list[dict[str, str]]:
    try:
        if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > limit:
            raise ValueError
        raw = path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(raw), delimiter="\t", strict=True)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError
        rows = list(reader)
        if any(set(r) != set(columns) or any(v is None for v in r.values()) for r in rows):
            raise ValueError
        return rows
    except (OSError, ValueError, RuntimeError, UnicodeError, csv.Error):
        raise HLAError("HIBAG scientific output is missing or malformed.") from None


def metadata(directory: Path) -> dict[str, Any]:
    try:
        rows = tsv(
            directory / "models.tsv",
            ("locus", "assembly", "training_samples", "classifiers", "markers", "hla_alleles"),
        )
        if len(rows) != len(LOCI) or {r["locus"] for r in rows} != set(LOCI):
            raise ValueError
        result: dict[str, Any] = {
            r["locus"]: {
                "assembly": r["assembly"],
                "training_samples": int(r["training_samples"]),
                "classifiers": int(r["classifiers"]),
                "marker_count": int(r["markers"]),
                "allele_count": int(r["hla_alleles"]),
                "markers": [],
                "alleles": [],
            }
            for r in rows
        }
        for r in tsv(directory / "markers.tsv", ("locus", "index", "rsid", "position", "alleles")):
            result[r["locus"]]["markers"].append(
                {
                    "index": int(r["index"]),
                    "rsid": r["rsid"],
                    "position": int(r["position"]),
                    "alleles": r["alleles"].split("/"),
                }
            )
        for r in tsv(directory / "alleles.tsv", ("locus", "allele")):
            result[r["locus"]]["alleles"].append(r["allele"])
        validate_metadata(result)
        return result
    except (KeyError, ValueError, TypeError):
        raise HLAError("HIBAG classifier metadata is malformed or incomplete.") from None


def positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _validate_metadata(loci: Any) -> None:
    if not isinstance(loci, dict) or set(loci) != set(LOCI):
        raise HLAError("HLA classifier locus set is incomplete.")
    for m in loci.values():
        if (
            not isinstance(m, dict)
            or set(m)
            != {
                "assembly",
                "training_samples",
                "classifiers",
                "marker_count",
                "allele_count",
                "markers",
                "alleles",
            }
            or m["assembly"] != "hg19"
            or any(
                not positive(m[k])
                for k in ("training_samples", "classifiers", "marker_count", "allele_count")
            )
            or not isinstance(m["markers"], list)
            or len(m["markers"]) != m["marker_count"]
            or not isinstance(m["alleles"], list)
            or len(m["alleles"]) != m["allele_count"]
            or any(not isinstance(a, str) or not ALLELE.fullmatch(a) for a in m["alleles"])
            or len(set(m["alleles"])) != m["allele_count"]
        ):
            raise HLAError("HLA classifier metadata is invalid.")
        positions = set()
        for index, marker in enumerate(m["markers"], 1):
            if (
                not isinstance(marker, dict)
                or set(marker) != {"index", "rsid", "position", "alleles"}
                or type(marker["index"]) is not int
                or marker["index"] != index
                or not isinstance(marker["rsid"], str)
                or not re.fullmatch(r"rs[1-9][0-9]*", marker["rsid"])
                or not positive(marker["position"])
                or not 20_000_000 <= marker["position"] <= 40_000_000
                or not isinstance(marker["alleles"], list)
                or len(marker["alleles"]) != 2
                or any(not isinstance(a, str) or a not in BASES for a in marker["alleles"])
                or len(set(marker["alleles"])) != 2
                or marker["position"] in positions
            ):
                raise HLAError("HLA classifier marker identity is invalid.")
            positions.add(marker["position"])


def _dbsnp(loci: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = root / "dbsnp_b157_grch37" / "dbsnp_variants.parquet"
    try:
        proof = postprocess.validate_provenance(
            path,
            expected=postprocess.declared_artifact_provenance(
                "dbsnp_b157_grch37", "extract_dbsnp_variant_index", output_name=path.name
            ),
            expected_step="extract_dbsnp_variant_index",
            expected_transform_version=postprocess.get(
                "extract_dbsnp_variant_index"
            ).transform_version,
        )
        positions = sorted({s["position"] for m in loci.values() for s in m["markers"]})
        rows = (
            pl.scan_parquet(path)
            .filter(
                (pl.col("chrom").cast(pl.String) == "6") & pl.col("pos_grch37").is_in(positions)
            )
            .select("rsid", "chrom", "pos_grch37", "ref", "alts")
            .collect()
            .to_dicts()
        )
        if file_hash(path) != proof["output_sha256"]:
            raise ValueError
        return {"provenance": proof, "variants": rows}
    except (OSError, KeyError, ValueError, postprocess.ProcessError, pl.exceptions.PolarsError):
        raise HLAError(
            "Verified dbSNP GRCh37 allele reference is unavailable or damaged."
        ) from None


def _panel(loci: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """1000 Genomes chr6 alleles at model positions, lock-verified in the same pass.

    Decompression stops past the last model position; the remaining compressed bytes are
    still hashed, so a damaged or substituted file is refused rather than half-read.
    """
    from genetics.pgs.catalog import PgsError
    from genetics.pgs.reference import _HashingReader, discover_panel

    positions = {s["position"] for m in loci.values() for s in m["markers"]}
    end = max(positions)
    try:
        panel = discover_panel(root)
        if isinstance(panel, str) or "6" not in panel.vcfs:
            raise ValueError
        path, expected = panel.vcfs["6"]
        if not PANEL_FILE.fullmatch(path.name):
            raise ValueError
        rows = []
        last = 0
        with path.open("rb") as raw:
            reader = _HashingReader(raw)
            with gzip.GzipFile(fileobj=cast(BinaryIO, reader), mode="rb") as handle:
                for line in handle:
                    if line.startswith(b"#"):
                        continue
                    chrom, pos, identifier, ref, alt, _ = line.split(b"\t", 5)
                    position = int(pos)
                    if chrom != b"6" or position < last:
                        raise ValueError
                    last = position
                    if position > end:
                        break
                    if position in positions:
                        rows.append(
                            {
                                "id": identifier.decode("ascii"),
                                "pos_grch37": position,
                                "ref": ref.decode("ascii"),
                                "alts": alt.decode("ascii").split(","),
                            }
                        )
            digest = reader.finish()
        if digest != expected:
            raise ValueError
    except (OSError, EOFError, ValueError, UnicodeError, zlib.error, PgsError):
        raise HLAError(
            "Verified 1000 Genomes chr6 panel alleles are unavailable or damaged; "
            f"run `genetics refs fetch --only {PANEL}`."
        ) from None
    return {
        "provenance": {
            "source": PANEL,
            "version": panel.version,
            "filename": path.name,
            "sha256": expected,
        },
        "variants": rows,
    }


def strand_index(reference: Mapping[str, Any]) -> dict[str, dict[int, list[Any]]]:
    """Strand evidence rows by source and position, built once per matrix."""
    index: dict[str, dict[int, list[Any]]] = {name: {} for name in STRAND_SOURCES}
    for name in STRAND_SOURCES:
        for row in reference[name]["variants"]:
            index[name].setdefault(row["pos_grch37"], []).append(row)
    return index


def orientation(
    marker: Mapping[str, Any],
    reference: Mapping[str, Any],
    index: Mapping[str, Mapping[int, list[Any]]] | None = None,
) -> tuple[str | None, list[str]]:
    """Return the first model allele on + strand and the sources that prove it.

    Each source proves a strand only when its single-base allele sets at the position fit
    exactly one reading. dbSNP lists every allele ever submitted, so many MHC sites are
    tetra-allelic there and fit both; 1000 Genomes lists the alleles seen in 2,504 genomes
    and resolves most of them. Indel, MNP and structural records anchored at the position
    describe a different variant and abstain. Palindromic pairs, sources that disagree, a
    source whose SNV alleles fit neither reading, and sites no source resolves stay missing.
    """
    pair = set(marker["alleles"])
    reverse = {a.translate(COMPLEMENT) for a in pair}
    if pair == reverse:
        return None, []
    first = marker["alleles"][0]
    rows = index if index is not None else strand_index(reference)
    votes: dict[str, str] = {}
    for name in STRAND_SOURCES:
        snv = False
        candidates = set()
        for row in rows[name].get(marker["position"], ()):
            forward = {a for a in (row["ref"], *row["alts"]) if a in BASES}
            if len(forward) < 2:
                continue
            snv = True
            if pair <= forward:
                candidates.add(first)
            if reverse <= forward:
                candidates.add(first.translate(COMPLEMENT))
        if snv and not candidates:
            return None, []
        if len(candidates) == 1:
            votes[name] = candidates.pop()
    if len(set(votes.values())) != 1:
        return None, []
    return next(iter(votes.values())), list(votes)


def source_identity(population: str) -> tuple[Path, dict[str, Any]]:
    if population not in POPULATIONS:
        raise HLAError("Choose a supported explicit HIBAG classifier population.")
    source = manifest.load().get("hibag_hlares_" + population + "_hg19")
    item = source.files[0]
    path = references_dir() / source.id / item.filename
    return path, {
        "id": source.id,
        "population": population,
        "version": source.version,
        "filename": item.filename,
        "sha256": item.sha256,
        "size_bytes": item.size_bytes,
        "url": item.url,
        "license": source.license_id,
        "terms_status": "unspecified-model-terms",
        "opt_in": True,
        "citation": "10.1038/tpj.2013.18",
    }


def work() -> Path:
    try:
        path = cache_dir() / (uuid.uuid4().hex + ".hibag-work")
        path.mkdir(parents=True, mode=0o700)
        return path
    except (OSError, ValueError, RuntimeError):
        raise HLAError("Private HLA workspace is unavailable.") from None


def run_r(
    runtime: HIBAGRuntime,
    source: str,
    args: list[str],
    *,
    timeout: float,
    cancel: threading.Event | None,
) -> Path:
    path = work() / "job.R"
    try:
        path.write_text(source, encoding="utf-8")
    except OSError:
        raise HLAError("Private HLA script is unavailable.") from None
    return runtime.run_script(path, args, timeout=timeout, cancel=cancel).directory


def prepare(
    population: str,
    runtime: HIBAGRuntime,
    *,
    opt_in: bool = False,
    timeout: float = 3600,
    cancel: threading.Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    if opt_in is not True:
        raise HLAError("HLA model terms are unspecified; explicit classifier opt-in is required.")
    path, identity = source_identity(population)
    if file_hash(path) != identity["sha256"] or path.stat().st_size != identity["size_bytes"]:
        raise HLAError("HLA classifier bytes disagree with the manifest pin.")
    if progress:
        progress("Inspecting HIBAG classifier metadata in isolated R")
    directory = run_r(runtime, scripts.INSPECT, [str(path)], timeout=timeout, cancel=cancel)
    loci = metadata(directory)
    if progress:
        progress("Proving HLA marker strand against dbSNP and 1000 Genomes chr6 alleles")
    reference = {
        "source": identity,
        "loci": loci,
        "dbsnp": _dbsnp(loci, references_dir()),
        "panel": _panel(loci, references_dir()),
    }
    if file_hash(path) != identity["sha256"]:
        raise HLAError("HLA classifier changed during inspection.")
    validate_reference(reference)
    return path, reference


def _validate_reference(record: Any) -> None:
    if not isinstance(record, dict) or set(record) != {"source", "loci", "dbsnp", "panel"}:
        raise HLAError("Frozen HLA reference is incomplete.")
    source = record["source"]
    if (
        not isinstance(source, dict)
        or set(source)
        != {
            "id",
            "population",
            "version",
            "filename",
            "sha256",
            "size_bytes",
            "url",
            "license",
            "terms_status",
            "opt_in",
            "citation",
        }
        or source["population"] not in POPULATIONS
        or source["id"] != "hibag_hlares_" + source["population"] + "_hg19"
        or source["version"] != "2012-08-05"
        or source["license"] != LICENSE
        or source["terms_status"] != "unspecified-model-terms"
        or source["opt_in"] is not True
        or not isinstance(source["sha256"], str)
        or not HEX.fullmatch(source["sha256"])
        or not positive(source["size_bytes"])
        or source["citation"] != "10.1038/tpj.2013.18"
        or source["filename"] != source["population"].title() + "-HLA4-hg19.RData"
        or source["url"]
        != "https://hibag.s3.amazonaws.com/download/hlares_param/" + source["filename"]
    ):
        raise HLAError("Frozen HLA model identity is invalid.")
    validate_metadata(record["loci"])
    dbsnp = record["dbsnp"]
    if not isinstance(dbsnp, dict) or set(dbsnp) != {"provenance", "variants"}:
        raise HLAError("HLA strand evidence is incomplete.")
    p = dbsnp["provenance"]
    if (
        not isinstance(p, dict)
        or p.get("step") != "extract_dbsnp_variant_index"
        or p.get("output") != "dbsnp_variants.parquet"
        or type(p.get("schema_version")) is not int
        or p["schema_version"] != DBSNP_PROVENANCE_VERSION
        or not positive(p.get("transform_version"))
        or type(p.get("rows")) is not int
        or p["rows"] < 0
        or not isinstance(p.get("params"), dict)
        or not isinstance(p.get("input"), dict)
        or not isinstance(p["input"].get("sha256"), str)
        or not HEX.fullmatch(p["input"]["sha256"])
        or not isinstance(p.get("output_sha256"), str)
        or not HEX.fullmatch(p["output_sha256"])
    ):
        raise HLAError("HLA strand evidence provenance is invalid.")
    positions = {s["position"] for m in record["loci"].values() for s in m["markers"]}
    if not isinstance(dbsnp["variants"], list):
        raise HLAError("HLA strand evidence is invalid.")
    for r in dbsnp["variants"]:
        if (
            not isinstance(r, dict)
            or set(r) != {"rsid", "chrom", "pos_grch37", "ref", "alts"}
            or r["chrom"] != "6"
            or not positive(r["pos_grch37"])
            or r["pos_grch37"] not in positions
            or not isinstance(r["rsid"], str)
            or not isinstance(r["ref"], str)
            or not r["ref"]
            or not isinstance(r["alts"], list)
            or not r["alts"]
            or any(not isinstance(a, str) or not a for a in r["alts"])
        ):
            raise HLAError("HLA strand evidence variant is invalid.")
    panel = record["panel"]
    if (
        not isinstance(panel, dict)
        or set(panel) != {"provenance", "variants"}
        or not isinstance(panel["provenance"], dict)
        or set(panel["provenance"]) != {"source", "version", "filename", "sha256"}
        or panel["provenance"]["source"] != PANEL
        or panel["provenance"]["version"] != "20130502"
        or not isinstance(panel["provenance"]["filename"], str)
        or not PANEL_FILE.fullmatch(panel["provenance"]["filename"])
        or not isinstance(panel["provenance"]["sha256"], str)
        or not HEX.fullmatch(panel["provenance"]["sha256"])
        or not isinstance(panel["variants"], list)
    ):
        raise HLAError("HLA panel strand evidence provenance is invalid.")
    for r in panel["variants"]:
        if (
            not isinstance(r, dict)
            or set(r) != {"id", "pos_grch37", "ref", "alts"}
            or not positive(r["pos_grch37"])
            or r["pos_grch37"] not in positions
            or not isinstance(r["id"], str)
            or not r["id"]
            or not isinstance(r["ref"], str)
            or not r["ref"]
            or not isinstance(r["alts"], list)
            or not r["alts"]
            or any(not isinstance(a, str) or not a for a in r["alts"])
        ):
            raise HLAError("HLA panel strand evidence variant is invalid.")


def validate_reference(record: Any) -> None:
    try:
        _validate_reference(record)
    except HLAError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError):
        raise HLAError("Malformed HLA evidence contract.") from None


def validate_metadata(loci: Any) -> None:
    try:
        _validate_metadata(loci)
    except HLAError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError):
        raise HLAError("Malformed HLA evidence contract.") from None
