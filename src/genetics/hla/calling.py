"""Shared array-to-HIBAG engine and cache-independent schema-1 sample evidence."""

from __future__ import annotations

import hashlib
import math
import re
import threading
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genetics.external import hibag
from genetics.hla import models, scripts
from genetics.hla.models import HLAError
from genetics.ingest.schema import GenotypeTable
from genetics.privacy import NoGenotypeRepr

VERSION = 1
PARAMETERS = {
    "type": "response",
    "vote": "prob",
    "cl": False,
    "allele_check": False,
    "input": "model-ordered-first-allele-count",
    "observation_source": "original-array",
    "resolution": "two-field",
}
REASONS = {"not-selected", "r-missing", "hibag-missing", "model-missing", "not-supplied"}


def unavailable(reason: str) -> dict[str, Any]:
    if reason not in REASONS:
        raise HLAError("Invalid HLA unavailability reason.")
    return {
        "schema_version": VERSION,
        "status": "unavailable",
        "reason": reason,
        "reference": None,
        "reference_sha256": None,
        "runtime": None,
        "parameters": PARAMETERS.copy(),
        "sample": None,
        "observations": [],
        "genes": {},
        "execution": None,
    }


def collect(table: GenotypeTable, reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    positions = {s["position"] for m in reference["loci"].values() for s in m["markers"]}
    found: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in table.frame.iter_rows(named=True):
        if row["chrom"] == "6" and row["pos_grch37"] in positions:
            found[row["pos_grch37"]].append(
                {k: row[k] for k in ("rsid", "a1", "a2", "call_status")}
            )
    return [{"position": p, "probes": found[p]} for p in sorted(positions)]


def matrices(reference: Mapping[str, Any], observations: Any) -> dict[str, Any]:
    positions = {s["position"] for m in reference["loci"].values() for s in m["markers"]}
    if not isinstance(observations, list) or len(observations) != len(positions):
        raise HLAError("HLA observations have incomplete marker coverage.")
    found = {}
    for row in observations:
        if (
            not isinstance(row, dict)
            or set(row) != {"position", "probes"}
            or type(row["position"]) is not int
            or row["position"] not in positions
            or row["position"] in found
            or not isinstance(row["probes"], list)
        ):
            raise HLAError("HLA observation identity is invalid.")
        for probe in row["probes"]:
            if (
                not isinstance(probe, dict)
                or set(probe) != {"rsid", "a1", "a2", "call_status"}
                or not isinstance(probe["rsid"], str)
                or not probe["rsid"]
                or probe["call_status"] not in ("called", "no_call", "hemizygous", "het_haploid")
                or any(
                    v is not None and (not isinstance(v, str) or v not in "ACGTID" or len(v) != 1)
                    for v in (probe["a1"], probe["a2"])
                )
                or (probe["call_status"] == "no_call")
                != (probe["a1"] is None and probe["a2"] is None)
                or (
                    probe["call_status"] != "no_call"
                    and (probe["a1"] is None or probe["a2"] is None)
                )
            ):
                raise HLAError("HLA probe observation is malformed.")
        found[row["position"]] = row["probes"]
    if set(found) != positions:
        raise HLAError("HLA observations have incomplete marker identities.")
    index = models.strand_index(reference)
    output = {}
    for locus in models.LOCI:
        rows = []
        for marker in reference["loci"][locus]["markers"]:
            probes = found[marker["position"]]
            first, proof = models.orientation(marker, reference, index)
            bases = None
            dose = None
            if not probes:
                state = "absent"
            elif len(probes) != 1:
                state = "duplicate-position"
            elif probes[0]["call_status"] == "no_call":
                state = "no-call"
            elif probes[0]["call_status"] != "called":
                state = "unsupported-ploidy"
            elif first is None:
                state = "unresolved-strand"
            else:
                model_pair = marker["alleles"]
                if first != model_pair[0]:
                    model_pair = [a.translate(models.COMPLEMENT) for a in model_pair]
                bases = [probes[0]["a1"], probes[0]["a2"]]
                if not set(bases) <= set(model_pair):
                    state = "incompatible-alleles"
                else:
                    state = "observed"
                    dose = bases.count(first)
            rows.append(
                {
                    "index": marker["index"],
                    "position": marker["position"],
                    "state": state,
                    "forward_first_allele": first,
                    "strand_evidence": proof,
                    "dose": dose,
                }
            )
        coverage = dict(sorted(Counter(r["state"] for r in rows).items()))
        output[locus] = {
            "markers": rows,
            "coverage": coverage,
            "observed_markers": coverage.get("observed", 0),
            "model_markers": len(rows),
        }
    return output


def input_text(reference: Mapping[str, Any], matrix: Mapping[str, Any]) -> str:
    lines = ["locus\tindex\trsid\tposition\talleles\tdose"]
    for locus in models.LOCI:
        for marker, row in zip(
            reference["loci"][locus]["markers"], matrix[locus]["markers"], strict=True
        ):
            lines.append(
                "\t".join(
                    map(
                        str,
                        [
                            locus,
                            marker["index"],
                            marker["rsid"],
                            marker["position"],
                            "/".join(marker["alleles"]),
                            "NA" if row["dose"] is None else row["dose"],
                        ],
                    )
                )
            )
    return "\n".join(lines) + "\n"


def _runtime(runtime: hibag.HIBAGRuntime) -> dict[str, str]:
    return {
        "r_version": runtime.r_version,
        "r_platform": runtime.r_platform,
        "hibag_version": runtime.hibag_version,
    }


def impute(
    table: GenotypeTable,
    path: Path,
    reference: dict[str, Any],
    runtime: hibag.HIBAGRuntime,
    *,
    timeout: float = 21600,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    models.validate_reference(reference)
    observations = collect(table, reference)
    matrix = matrices(reference, observations)
    sample = uuid.uuid4().hex
    text = input_text(reference, matrix)
    payload = text.encode("utf-8")
    input_path = models.work() / "sample.hla-input.tsv"
    try:
        input_path.write_bytes(payload)
    except OSError:
        raise HLAError("Private HLA matrix could not be written.") from None
    if models.file_hash(path) != reference["source"]["sha256"]:
        raise HLAError("HLA classifier changed before prediction.")
    model_md5 = models.file_hash(path, "md5")
    directory = models.run_r(
        runtime,
        scripts.PREDICT,
        [str(path), str(input_path), sample],
        timeout=timeout,
        cancel=cancel,
    )
    if models.metadata(directory) != reference["loci"]:
        raise HLAError("HIBAG classifier metadata changed during prediction.")
    identity = models.tsv(directory / "identity.tsv", ("sample", "input_md5", "model_md5"))
    if identity != [
        {"sample": sample, "input_md5": hashlib.md5(payload).hexdigest(), "model_md5": model_md5}
    ]:
        raise HLAError("HIBAG prediction input identity disagrees.")
    if (
        models.file_hash(path) != reference["source"]["sha256"]
        or models.file_hash(input_path) != hashlib.sha256(payload).hexdigest()
    ):
        raise HLAError("HLA input changed during prediction.")
    rows = models.tsv(
        directory / "calls.hla-output.tsv",
        ("locus", "sample", "state", "allele1", "allele2", "posterior"),
    )
    if len(rows) != len(models.LOCI) or {r["locus"] for r in rows} != set(models.LOCI):
        raise HLAError("HIBAG prediction locus set is incomplete.")
    genes = {}
    for r in rows:
        if r["sample"] != sample:
            raise HLAError("HIBAG prediction sample identity disagrees.")
        try:
            pair = (
                None
                if r["allele1"] == r["allele2"] == "NA"
                else sorted([r["allele1"], r["allele2"]])
            )
            posterior = None if r["posterior"] == "NA" else float(r["posterior"])
        except ValueError:
            raise HLAError("HIBAG prediction posterior is malformed.") from None
        genes[r["locus"]] = {
            **matrix[r["locus"]],
            "status": r["state"],
            "alleles": pair,
            "posterior": posterior,
        }
    result = {
        "schema_version": VERSION,
        "status": "completed",
        "reason": None,
        "reference": reference,
        "reference_sha256": models.digest(reference),
        "runtime": _runtime(runtime),
        "parameters": PARAMETERS.copy(),
        "sample": sample,
        "observations": observations,
        "genes": genes,
        "execution": {
            "input_sha256": hashlib.sha256(payload).hexdigest(),
            "input_md5": hashlib.md5(payload).hexdigest(),
            "model_md5": model_md5,
            "timeout_seconds": timeout,
        },
    }
    validate(result)
    return result


def _validate(record: Any) -> None:
    if (
        not isinstance(record, dict)
        or set(record)
        != {
            "schema_version",
            "status",
            "reason",
            "reference",
            "reference_sha256",
            "runtime",
            "parameters",
            "sample",
            "observations",
            "genes",
            "execution",
        }
        or type(record["schema_version"]) is not int
        or record["schema_version"] != VERSION
        or models.digest(record["parameters"]) != models.digest(PARAMETERS)
    ):
        raise HLAError("Invalid HLA sample schema.")
    if record["status"] == "unavailable":
        if record != unavailable(record["reason"]):
            raise HLAError("Unavailable HLA stage cannot contain predictions.")
        return
    if record["status"] != "completed" or record["reason"] is not None:
        raise HLAError("Invalid HLA execution state.")
    models.validate_reference(record["reference"])
    if record["reference_sha256"] != models.digest(record["reference"]):
        raise HLAError("Frozen HLA reference checksum disagrees.")
    runtime = record["runtime"]
    if (
        not isinstance(runtime, dict)
        or set(runtime) != {"r_version", "r_platform", "hibag_version"}
        or any(not isinstance(v, str) for v in runtime.values())
        or not re.fullmatch(r"[0-9]+(?:[.-][0-9]+)+", runtime["r_version"])
        or not re.fullmatch(r"[0-9]+(?:[.-][0-9]+)+", runtime["hibag_version"])
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", runtime["r_platform"])
        or not isinstance(record["sample"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", record["sample"])
    ):
        raise HLAError("Invalid frozen HLA runtime or sample identity.")
    matrix = matrices(record["reference"], record["observations"])
    payload = input_text(record["reference"], matrix).encode("utf-8")
    execution = record["execution"]
    if (
        not isinstance(execution, dict)
        or set(execution) != {"input_sha256", "input_md5", "model_md5", "timeout_seconds"}
        or execution["input_sha256"] != hashlib.sha256(payload).hexdigest()
        or execution["input_md5"] != hashlib.md5(payload).hexdigest()
        or not isinstance(execution["model_md5"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", execution["model_md5"])
        or type(execution["timeout_seconds"]) not in (int, float)
        or not math.isfinite(execution["timeout_seconds"])
        or execution["timeout_seconds"] <= 0
    ):
        raise HLAError("Invalid frozen HLA matrix or execution identity.")
    if not isinstance(record["genes"], dict) or set(record["genes"]) != set(models.LOCI):
        raise HLAError("Frozen HLA predictions are incomplete.")
    for locus, expected in matrix.items():
        gene = record["genes"][locus]
        if (
            not isinstance(gene, dict)
            or set(gene) != {*expected, "status", "alleles", "posterior"}
            or any(models.digest(gene[k]) != models.digest(v) for k, v in expected.items())
        ):
            raise HLAError("Frozen HLA marker evidence disagrees with its observations.")
        if gene["status"] == "no-markers":
            if (
                gene["observed_markers"] != 0
                or gene["alleles"] is not None
                or gene["posterior"] is not None
            ):
                raise HLAError("Uncallable HLA locus contains a prediction.")
        elif gene["status"] == "no-prediction":
            if (
                gene["observed_markers"] == 0
                or gene["alleles"] is not None
                or gene["posterior"] is not None
            ):
                raise HLAError("Unsupported HLA prediction state is inconsistent.")
        elif (
            gene["status"] != "predicted"
            or gene["observed_markers"] == 0
            or not isinstance(gene["alleles"], list)
            or len(gene["alleles"]) != 2
            or any(
                not isinstance(a, str) or a not in record["reference"]["loci"][locus]["alleles"]
                for a in gene["alleles"]
            )
            or gene["alleles"] != sorted(gene["alleles"])
            or type(gene["posterior"]) not in (int, float)
            or not math.isfinite(gene["posterior"])
            or not 0 <= gene["posterior"] <= 1
        ):
            raise HLAError("Frozen HLA prediction alleles or posterior are invalid.")


def report(record: Mapping[str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {
            "status": "not-recorded",
            "reason": "This historical run predates HLA evidence.",
            "genes": {},
        }
    validate(record)
    return dict(record)


@dataclass(repr=False)
class HLAStage(NoGenotypeRepr):
    population: str | None = None
    opt_in: bool = False
    timeout: float = 21600
    cancel: threading.Event | None = None
    runtime: hibag.HIBAGRuntime | None = None
    path: Path | None = None
    reference: dict[str, Any] | None = None
    reason: str = "not-selected"

    def prepare(self, progress: Callable[[str], None] | None = None) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise hibag.HIBAGCancelledError("HLA imputation was cancelled.")
        if (
            type(self.timeout) not in (int, float)
            or not math.isfinite(self.timeout)
            or self.timeout <= 0
        ):
            raise HLAError("HLA timeout must be a positive finite number.")
        if self.population is None:
            return
        if self.population not in models.POPULATIONS or self.opt_in is not True:
            raise HLAError("Explicit supported HLA classifier and model-terms opt-in are required.")
        state = hibag.probe(cancel=self.cancel)
        if state.status == "probe-error":
            raise HLAError("R/HIBAG readiness failed; inspect genetics doctor.")
        if state.status != "ready":
            self.reason = state.status
            return
        path, _ = models.source_identity(self.population)
        if not path.exists():
            self.reason = "model-missing"
            return
        self.runtime = hibag.HIBAGRuntime.from_readiness(state)
        self.path, self.reference = models.prepare(
            self.population,
            self.runtime,
            opt_in=self.opt_in,
            timeout=self.timeout,
            cancel=self.cancel,
            progress=progress,
        )

    def run(self, table: GenotypeTable) -> dict[str, Any]:
        if self.reference is None or self.path is None or self.runtime is None:
            return unavailable(self.reason)
        return impute(
            table, self.path, self.reference, self.runtime, timeout=self.timeout, cancel=self.cancel
        )


def validate(record: Any) -> None:
    try:
        _validate(record)
    except HLAError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError):
        raise HLAError("Malformed HLA evidence contract.") from None
