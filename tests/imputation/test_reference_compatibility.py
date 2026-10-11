"""Fixed-seed reference duplicates, never a person or a fetched panel subset."""

from __future__ import annotations

import copy
import gzip
import io
import os
import random
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from genetics.external.beagle import BeagleRunError
from genetics.imputation import ImputationError, impute, pipeline, snapshot
from genetics.imputation.reference_compatibility import METHOD, validate_proof
from genetics.imputation.reference_stream import ReferenceStream, duplicate_rows
from genetics.ingest.schema import Chrom, GenotypeTable
from genetics.privacy import assert_no_genotype
from genetics.qc.report import InferredSex
from genetics.refs.imputation import BrefTools, _vcf_stream
from genetics.testing.imputation_inputs import native_reference


def fabricated_lines(*, end_differs: bool = False, conflict: bool = False) -> list[bytes]:
    rng = random.Random(9708)
    header = b"##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tsynthetic_0\tsynthetic_1\n"
    lines = [header]
    for i in range(12):
        gt = "\t".join(f"{int(rng.random() < 0.4)}|{int(rng.random() < 0.4)}" for _ in range(2))
        fields = ["1", str(1000 + i * 100), f"synthetic_{i}", "A", "G", ".", "PASS", ".", "GT", gt]
        lines.append(("\t".join(fields) + "\n").encode())
        if i == 5:
            fields[2] = "synthetic_redundant_annotation"
            if end_differs:
                fields[7] = "END=" + fields[1]
            if conflict:
                fields[9] = fields[9].replace("0", "X").replace("1", "0").replace("X", "1")
            lines.append(("\t".join(fields) + "\n").encode())
    return b"".join(lines).splitlines(keepends=True)


def proof(end_differs: bool = False) -> dict[str, Any]:
    source = fabricated_lines(end_differs=end_differs)
    sink = io.BytesIO()
    stream = ReferenceStream(sink.write)
    original = _vcf_stream(source, "1", consume=stream.consume)
    native = stream.summary()
    assert _vcf_stream(sink.getvalue().splitlines(keepends=True), "1") == native
    first = {"sha256": "a" * 64, "size_bytes": 1000, "summary": asdict(original)}
    second = (
        first if end_differs else {"sha256": "b" * 64, "size_bytes": 900, "summary": asdict(native)}
    )
    return {
        "schema_version": 1,
        "method": METHOD,
        "source": first,
        "native": second,
        "source_duplicates": duplicate_rows(stream.duplicates),
        "native_duplicates": duplicate_rows(stream.native_duplicates),
        "folded": stream.folded,
    }


def test_lossless_normalization_keeps_samples_and_every_distinct_phased_vector() -> None:
    data = proof()
    assert data["source"]["summary"]["records"] == 13
    assert data["native"]["summary"]["records"] == 12
    assert data["native"]["summary"]["samples"] == 2
    assert len(data["folded"]) == 1
    assert validate_proof(data) == {}
    assert_no_genotype(repr(ReferenceStream()))


def test_different_END_markers_are_not_collapsed_even_with_same_alleles() -> None:
    data = proof(end_differs=True)
    assert data["folded"] == []
    assert data["native"] == data["source"]
    assert validate_proof(data) == {(1500, "A", "G"): 2}


def test_multiple_folded_END_groups_preserve_each_distinct_observation() -> None:
    lines = fabricated_lines()
    index = next(i for i, raw in enumerate(lines) if b"synthetic_redundant_annotation" in raw)
    fields = lines[index].rstrip().split(b"\t")
    fields[7] = b"END=1500"
    end_record = b"\t".join(fields) + b"\n"
    lines[index + 1 : index + 1] = [end_record, end_record]
    sink = io.BytesIO()
    stream = ReferenceStream(sink.write)
    source = _vcf_stream(lines, "1", consume=stream.consume)
    native = stream.summary()
    assert _vcf_stream(sink.getvalue().splitlines(keepends=True), "1") == native
    assert source.records == 15 and native.records == 13
    data = proof()
    data["source"]["summary"] = asdict(source)
    data["native"]["summary"] = asdict(native)
    data["source_duplicates"] = duplicate_rows(stream.duplicates)
    data["native_duplicates"] = duplicate_rows(stream.native_duplicates)
    data["folded"] = stream.folded
    assert validate_proof(data) == {(1500, "A", "G"): 2}


def test_conflicting_native_equal_phased_vectors_fail_without_echoing_calls() -> None:
    stream = ReferenceStream()
    with pytest.raises(ValueError, match="conflicting phased") as caught:
        _vcf_stream(fabricated_lines(conflict=True), "1", consume=stream.consume)
    assert_no_genotype(str(caught.value))


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "count",
        "samples",
        "order",
        "native_duplicates",
        "fold_count",
        "source_sha",
        "unknown",
        "impossible_multiplicity",
        "impossible_fold_allocation",
    ],
)
def test_frozen_reference_proof_refuses_inconsistent_relationships(change: str) -> None:
    data = copy.deepcopy(proof())
    if change == "version":
        data["schema_version"] = True
    elif change == "count":
        data["native"]["summary"]["records"] += 1
    elif change == "samples":
        data["native"]["summary"]["samples"] += 1
    elif change == "order":
        data["native"]["summary"]["sample_order_sha256"] = "c" * 64
    elif change == "native_duplicates":
        data["native_duplicates"] = data["source_duplicates"]
    elif change == "fold_count":
        data["folded"][0]["copies"] += 1
    elif change == "source_sha":
        data["source"]["sha256"] = "invalid"
    elif change == "impossible_multiplicity":
        data["source_duplicates"][0][-1] = 20
        data["native_duplicates"] = [[1500, "A", "G", 19]]
    elif change == "impossible_fold_allocation":
        # Two distinct END groups with two copies each need four source
        # records. A three-record identity cannot allocate both groups, even
        # when the total removed/native counts appear consistent.
        data["source_duplicates"][0][-1] = 3
        data["source"]["summary"]["records"] += 1
        second = copy.deepcopy(data["folded"][0])
        second["end"] = "1500"
        data["folded"].append(second)
    else:
        data["unexpected"] = 1
    with pytest.raises(ValueError):
        validate_proof(data)


def test_native_duplicate_failure_lossless_execution_and_frozen_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools_root = os.environ.get("GENETICS_BEAGLE_TEST_TOOLS")
    if not tools_root:
        pytest.skip("Set GENETICS_BEAGLE_TEST_TOOLS for the pinned native regression")
    tools = BrefTools.discover(Path(tools_root))
    prepared, _, target = native_reference(tmp_path / "reference", tools, duplicate_markers=True)
    target = GenotypeTable(target.filter_chrom(Chrom("1")), vendor="synthetic")
    with monkeypatch.context() as stock:
        stock.setattr(
            pipeline, "prepare_native_reference", lambda tools, panel, *args: (panel, None)
        )
        with pytest.raises(BeagleRunError):
            impute(target, sex=InferredSex.FEMALE, reference=prepared, out=tmp_path / "stock")
    result = impute(target, sex=InferredSex.FEMALE, reference=prepared, out=tmp_path / "fixed")
    evidence = result.metadata["jobs"][0]["reference_evidence"]
    assert evidence["source"]["summary"]["records"] == 201
    assert evidence["native"]["summary"]["records"] == 200
    assert evidence["native"]["summary"]["samples"] == 20
    assert validate_proof(evidence) == {}
    frozen = tmp_path / "frozen"
    shutil.copytree(result.directory, frozen)
    shutil.copyfile(prepared.panel_catalog, frozen / snapshot.PANEL_NAME)
    shutil.copyfile(prepared.map_catalog, frozen / snapshot.MAP_NAME)
    snapshot._catalogs(frozen, result.metadata)
    snapshot._payloads(frozen, result.metadata, [])
    altered = copy.deepcopy(result.metadata)
    altered["jobs"][0]["reference_evidence"]["native"]["sha256"] = "d" * 64
    with pytest.raises(ValueError):
        snapshot._catalogs(frozen, altered)
    altered = copy.deepcopy(result.metadata)
    altered["jobs"][0]["reference_evidence"]["folded"][0]["gt_sha256"] = "e" * 64
    with pytest.raises(ValueError):
        snapshot._catalogs(frozen, altered)
    resumed = impute(target, sex=InferredSex.FEMALE, reference=prepared, out=tmp_path / "fixed")
    assert resumed.resumed and resumed.metadata == result.metadata
    native_path = Path(result.metadata["jobs"][0]["phase"]["contract"]["inputs"]["ref"]["path"])
    lines = gzip.decompress(native_path.read_bytes()).splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if not line.startswith(b"#"))
    fields = lines[index].rstrip().split(b"\t")
    fields[9] = b"1|1" if fields[9] != b"1|1" else b"0|0"
    lines[index] = b"\t".join(fields) + b"\n"
    native_path.write_bytes(gzip.compress(b"".join(lines), mtime=0))
    with pytest.raises(ImputationError, match="cache is damaged"):
        impute(target, sex=InferredSex.FEMALE, reference=prepared, out=tmp_path / "fixed")
