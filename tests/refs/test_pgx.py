"""Fabricated public-reference shapes, never sample genotypes or network calls."""

from __future__ import annotations

import gzip
import io
import json
import os
import stat
import zipfile
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.imputation.dosages import DosageRecord
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.pgx import calling, catalog, sources
from genetics.pgx.archives import HEADERS, MEMBERS, read_archive
from genetics.pgx.locking import publication_lock
from genetics.pgx.sql import REQUIRED, Tables, copy_value, read_dump
from genetics.qc.report import InferredSex
from genetics.refs import manifest, postprocess
from genetics.refs.postprocess import ProcessError, ProcessStatus

if TYPE_CHECKING:
    from genetics.engine.cards import KnowledgePack
    from genetics.engine.evidence import AssembledCard
    from genetics.qc.report import QCReport


def sample_table(
    pairs: Iterable[tuple[int, str | None, str | None, str]], *, chrom: str = "10"
) -> GenotypeTable:
    """Fabricated boundary cases, assembled in memory; never subset from a genome."""
    rows = [
        ("synthetic-probe", chrom, pos, a1, a2, None if a1 is None else a1 + (a2 or ""), status)
        for pos, a1, a2, status in pairs
    ]
    return GenotypeTable(
        pl.DataFrame(rows, schema=NORMALIZED_SCHEMA, orient="row"), vendor="synthetic"
    )


def refresh_call_reference(record: dict[str, Any]) -> catalog.Catalog:
    record["cpic"]["rows"] = sum(len(t) for t in record["cpic"]["tables"].values())
    record["locations"], record["definitions"] = catalog.normalize(
        record["cpic"], record["annotations"]["variants"], record["dbsnp"]
    )
    catalog.validate_record(record)
    return catalog.Catalog(record)


def _call_gene(frozen: dict[str, Any], table: GenotypeTable, **kwargs: Any) -> dict[str, Any]:
    result = calling.call(
        refresh_call_reference(frozen), table, sex=kwargs.pop("sex", InferredSex.FEMALE), **kwargs
    ).record["genes"][frozen["cpic"]["tables"]["gene"][0]["symbol"]]
    return dict(result)


def gene_reference(record: dict[str, Any], gene: str, *, chrom: str = "10") -> None:
    tables = record["cpic"]["tables"]
    tables["gene"][0].update(
        symbol=gene, chr="chr" + chrom, chromosequenceid=catalog.accession(chrom, "GRCh37")
    )
    for name in ("allele_definition", "sequence_location", "allele", "gene_result"):
        for row in tables[name]:
            row["genesymbol"] = gene
    tables["sequence_location"][0].update(position="101", chromosomelocation="g.101A>G")
    record["dbsnp"]["variants"][0]["chrom"] = chrom
    tables["gene_result_diplotype"][0]["diplotypekey"] = json.dumps({gene: {"*1": 1, "*2": 1}})


@pytest.mark.parametrize(
    "pair,expected", [("AA", ["*1", "*1"]), ("AG", ["*1", "*2"]), ("GG", ["*2", "*2"])]
)
def test_sample_caller_joint_allele_counts(
    frozen: dict[str, Any], pair: str, expected: list[str]
) -> None:
    result = _call_gene(frozen, sample_table([(101, pair[0], pair[1], "called")]))
    assert result["status"] == "unique-compatible"
    assert [c["alleles"] for c in result["candidates"]] == [expected]
    assert result["phase"] == "unresolved"
    assert result["models"][0]["coverage"]["observed_loci"] == 1


@pytest.mark.parametrize("kind", ["untyped", "no_call", "indel", "duplicate", "wrong-alleles"])
def test_missing_or_unusable_markers_never_default_reference(
    frozen: dict[str, Any], kind: str
) -> None:
    pairs = (
        []
        if kind == "untyped"
        else [(101, None, None, "no_call")]
        if kind == "no_call"
        else [(101, "D", "I", "called")]
        if kind == "indel"
        else [(101, "A", "C", "called")]
        if kind == "wrong-alleles"
        else [(101, "A", "A", "called"), (101, "G", "G", "called")]
    )
    result = _call_gene(frozen, sample_table(pairs))
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 3
    assert all(c["support"] == "conditional" for c in result["candidates"])
    assert result["models"][0]["coverage"]["observed_loci"] == 0


@pytest.mark.parametrize("gene", catalog.TRACTABLE)
def test_all_eight_genes_use_the_source_contract(frozen: dict[str, Any], gene: str) -> None:
    gene_reference(frozen, gene, chrom="X" if gene == "G6PD" else "10")
    result = _call_gene(
        frozen, sample_table([(101, "A", "G", "called")], chrom="X" if gene == "G6PD" else "10")
    )
    assert result["candidates"][0]["phenotypes"] == ["Intermediate Metabolizer"]
    assert result["candidates"][0]["mapping_ids"] == ["8"]


def test_native_haploid_mapping_and_unknown_sex(frozen: dict[str, Any]) -> None:
    gene_reference(frozen, "G6PD", chrom="X")
    tables = frozen["cpic"]["tables"]
    tables["gene_result_diplotype"][0].update(diplotype="*2", diplotypekey='{"G6PD":{"*2":1}}')
    tables["gene_result_lookup"][0].update(
        lookupkey='{"No function":1}', function1="No function", function2="N/A"
    )
    table = sample_table([(101, "G", "G", "hemizygous")], chrom="X")
    result = _call_gene(frozen, table, sex=InferredSex.MALE)
    assert result["phase"] == "single-copy"
    assert result["candidates"][0]["alleles"] == ["*2"]
    assert result["candidates"][0]["ploidy"] == 1
    assert result["candidates"][0]["mapping_ids"] == ["8"]
    ambiguous = _call_gene(
        frozen, sample_table([(101, "G", "G", "called")], chrom="X"), sex=InferredSex.AMBIGUOUS
    )
    assert ambiguous["ploidy_status"] == "unresolved"
    assert {c["ploidy"] for c in ambiguous["candidates"]} == {1, 2}


def test_haploid_heterozygosity_does_not_create_two_haplotypes(frozen: dict[str, Any]) -> None:
    gene_reference(frozen, "G6PD", chrom="X")
    result = _call_gene(
        frozen, sample_table([(101, "A", "G", "het_haploid")], chrom="X"), sex=InferredSex.MALE
    )
    assert all(c["ploidy"] == 1 and c["support"] == "conditional" for c in result["candidates"])
    assert result["models"][0]["observations"][0]["state"] == "ploidy-conflict"


def add_second_locus(record: dict[str, Any]) -> None:
    gene_reference(record, "CYP2C19")
    tables = record["cpic"]["tables"]
    tables["sequence_location"].append(
        {
            **tables["sequence_location"][0],
            "id": "9",
            "position": "102",
            "chromosomelocation": "g.102C>T",
            "dbsnpid": "rs1000002",
        }
    )
    record["dbsnp"]["resolutions"]["rs1000002"] = {
        "status": "current",
        "current_rsid": "rs1000002",
        "targets": [],
    }
    record["dbsnp"]["variants"].append(
        {"rsid": "rs1000002", "chrom": "10", "pos_grch37": 102, "ref": "C", "alts": ["T"]}
    )
    tables["allele_definition"].extend(
        [
            {**tables["allele_definition"][1], "id": "10", "name": "*3"},
            {**tables["allele_definition"][1], "id": "11", "name": "*4"},
        ]
    )
    tables["allele_location_value"] = [
        {"alleledefinitionid": i, "locationid": loc, "variantallele": base, "version": "1"}
        for i, first, second in (
            ("1", "A", "C"),
            ("2", "G", "C"),
            ("10", "A", "T"),
            ("11", "G", "T"),
        )
        for loc, base in (("3", first), ("9", second))
    ]


def test_cis_trans_phase_alternatives_are_enumerated(frozen: dict[str, Any]) -> None:
    add_second_locus(frozen)
    result = _call_gene(
        frozen, sample_table([(101, "A", "G", "called"), (102, "C", "T", "called")])
    )
    assert {tuple(c["alleles"]) for c in result["candidates"]} == {("*1", "*4"), ("*3", "*2")}
    assert result["status"] == "ambiguous"
    assert all(c["support"] == "complete" for c in result["candidates"])


@pytest.mark.parametrize(
    "kind",
    ["unresolved", "structural", "conflict", "sparse", "missing-function", "missing-phenotype"],
)
def test_definition_and_mapping_gaps_remain_explicit(frozen: dict[str, Any], kind: str) -> None:
    tables = frozen["cpic"]["tables"]
    if kind == "unresolved":
        tables["sequence_location"][0]["dbsnpid"] = None
        frozen["dbsnp"]["resolutions"] = {}
        frozen["dbsnp"]["variants"] = []
    elif kind == "structural":
        tables["allele_definition"][1]["structuralvariation"] = "t"
    elif kind == "conflict":
        tables["allele_definition"].append({**tables["allele_definition"][1], "id": "99"})
    elif kind == "sparse":
        tables["allele_location_value"] = tables["allele_location_value"][1:]
        tables["allele_definition"][0]["matchesreferencesequence"] = "f"
    elif kind == "missing-function":
        tables["allele"] = []
    else:
        tables["gene_result_diplotype"] = []
    result = _call_gene(frozen, sample_table([(101, "A", "G", "called")]))
    assert result["candidates"]
    if kind in {"unresolved", "structural", "conflict", "sparse"}:
        assert any(c["support"] == "conditional" for c in result["candidates"])
    elif kind == "missing-function":
        assert result["candidates"][0]["function_issues"] == ["1", "2"]
    else:
        assert result["candidates"][0]["mapping_status"] == "missing-mapping"


def test_activity_score_is_source_lookup_not_generic_sum(frozen: dict[str, Any]) -> None:
    gene_reference(frozen, "DPYD")
    tables = frozen["cpic"]["tables"]
    tables["gene"][0]["lookupmethod"] = "ACTIVITY_SCORE"
    for allele in tables["allele"]:
        allele["activityvalue"] = "source-specific expression, not a number"
    tables["gene_result_lookup"][0]["totalactivityscore"] = "source score: 1.5"
    result = _call_gene(frozen, sample_table([(101, "A", "G", "called")]))
    assert result["lookup_method"] == "ACTIVITY_SCORE"
    assert result["candidates"][0]["activity_scores"] == ["source score: 1.5"]


def test_vkorc1_missing_phenotype_is_not_invented(frozen: dict[str, Any]) -> None:
    gene_reference(frozen, "VKORC1")
    for name in ("gene_result_diplotype", "gene_result_lookup", "gene_result"):
        frozen["cpic"]["tables"][name] = []
    result = _call_gene(frozen, sample_table([(101, "A", "G", "called")]))
    assert result["phenotype_mapping_status"] == "not-provided"
    assert result["candidates"][0]["phenotypes"] == []


def imputed_marker(*, source: str = "imputed_untyped", quality: float = 0.1) -> DosageRecord:
    return DosageRecord(
        "10",
        101,
        "A",
        ("G",),
        (0, 1),
        (0, 1),
        (1.0,) if source == "imputed_no_call" else (0.72,),
        (1.0,) if source == "imputed_no_call" else (0.72,),
        None if source == "imputed_no_call" else (quality,),
        2,
        source,
        "resolved",
        None,
        "phased_hardcall_only" if source == "imputed_no_call" else "beagle_DS",
        "not_estimated" if source == "imputed_no_call" else "beagle_diploid_dosage",
    )


@pytest.mark.parametrize(
    "kind", ["untyped", "no_call", "blocked", "duplicate", "dosage_only", "wrong_ploidy"]
)
def test_imputation_preserves_native_evidence_and_blocks_replacement(
    frozen: dict[str, Any], kind: str
) -> None:
    marker = imputed_marker(source="imputed_no_call" if kind == "no_call" else "imputed_untyped")
    pairs = (
        [(101, None, None, "no_call")]
        if kind == "no_call"
        else [(101, "D", "I", "called")]
        if kind == "blocked"
        else []
    )
    table = sample_table(pairs)
    if kind == "dosage_only":
        marker = replace(marker, genotype=None)
        with pytest.raises(ValueError, match="malformed"):
            _call_gene(frozen, table, dosages=[marker])
        return
    if kind == "wrong_ploidy":
        marker = replace(
            marker,
            genotype=(1,),
            storage_genotype=(1,),
            ploidy=1,
            dosage=(0.72,),
            storage_dosage=(0.72,),
            quality_scope="beagle_haploid_dosage",
        )
    result = _call_gene(
        frozen, table, dosages=[marker, marker] if kind == "duplicate" else [marker]
    )
    observation = result["models"][0]["observations"][0]
    assert result["reliability"]["tier"] == "limited"
    if kind in {"untyped", "no_call"}:
        assert observation["source"] == marker.source
        assert result["candidates"][0]["alleles"] == ["*1", "*2"]
    else:
        assert observation["state"] != "observed"
        assert len(result["candidates"]) == 3


@pytest.mark.parametrize("imputed", [False, True])
def test_rare_call_tier_survives_imputation(frozen: dict[str, Any], imputed: bool) -> None:
    from genetics.health.frequencies import parse_record

    public = parse_record(
        "\t".join(["10", "101", ".", "A", "G", ".", "PASS", "AF=0.000001;AC=1;AN=1000000"])
    )
    result = _call_gene(
        frozen,
        sample_table([] if imputed else [(101, "A", "G", "called")]),
        dosages=[imputed_marker()] if imputed else [],
        frequencies={("10", 101): [public]},
    )
    assert result["reliability"]["tier"] == "likely-artifact"
    assert len(result["candidates"]) == 1
    benchmark = result["models"][0]["observations"][0]["rare_call_benchmark"]
    assert benchmark["estimate"] == 0.16 and "not a personal" in benchmark["scope"]


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "sex",
        "derived",
        "coordinates",
        "duplicate",
        "reference",
        "dosage",
        "alleles",
        "frequency",
    ],
)
def test_sample_snapshot_corruption_fails_closed(frozen: dict[str, Any], mutation: str) -> None:
    raw = deepcopy(
        calling.call(
            refresh_call_reference(frozen),
            sample_table([(101, "A", "G", "called")]),
            sex=InferredSex.FEMALE,
        ).to_dict()
    )
    calling.validate(raw)
    if mutation == "schema":
        raw["schema_version"] = True
    elif mutation == "sex":
        raw["sex"] = "invented"
    elif mutation == "derived":
        raw["genes"]["CYP2C19"]["candidates"][0]["ploidy"] = True
    elif mutation == "coordinates":
        raw["observations"][0]["pos_grch37"] = 102
    elif mutation == "duplicate":
        raw["observations"].append(raw["observations"][0])
    elif mutation == "reference":
        raw["reference"]["definitions"]["1"]["constraints"] = []
        raw["reference_sha256"] = sources.digest(raw["reference"])
    elif mutation == "dosage":
        raw["observations"][0]["dosages"] = [{}]
    elif mutation == "frequency":
        raw["observations"][0]["frequencies"] = [
            {
                "chrom": "10",
                "pos_grch37": 101,
                "ref": "A",
                "alts": ["G"],
                "populations": {"global": {"an": -1}},
            }
        ]
    else:
        raw["observations"][0]["probes"][0]["a1"] = "bad"
    with pytest.raises(calling.CallingError, match="malformed or inconsistent"):
        calling.validate(raw)


def test_missing_stage_and_scope_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calling, "references_dir", lambda: tmp_path)
    stage = calling.CallingStage()
    stage.prepare()
    record = stage.run(sample_table([]), sex=InferredSex.AMBIGUOUS).to_dict()
    calling.validate(record)
    assert record["status"] == "unavailable" and set(record["genes"]) == set(catalog.TRACTABLE)
    assert calling.report(None)["status"] == "not-recorded"
    with pytest.raises(calling.CallingError, match="eight"):
        calling.report(record, "CYP2D6")


def test_sample_calls_never_print_observations(frozen: dict[str, Any]) -> None:
    result = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    )
    assert "observations" not in repr(result) and "rs1000001" not in repr(result)
    calling.validate(json.loads(json.dumps(result.to_dict())))


def test_saved_pgx_cli_dashboard_and_historical_parity(
    frozen: dict[str, Any],
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from genetics.ancestry.context import AncestryContext
    from genetics.run.bundle import PGX_NAME, read_bundle, write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    calls = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=sample_qc.sex.inferred,
    )
    root = tmp_path / "runs"
    path = write_bundle(
        qc=sample_qc,
        cards=sample_cards,
        pack=sample_pack,
        ancestry=AncestryContext.not_run("Synthetic PGx acceptance"),
        pgx=calls.to_dict(),
        runs_root=root,
        run_id="pgx-synthetic",
        lock_path=tmp_path / "missing.lock",
        tools_root=tmp_path / "tools",
    )
    expected = calling.report(calls.record, "CYP2C19")
    assert calling.report(read_bundle(path).pgx, "CYP2C19") == expected
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["pgx", "calls", path.name, "--gene", "CYP2C19", "--json"])
    assert result.exit_code == 0, result.output
    from genetics.pgx.presentation import saved_report

    assert json.loads(result.output) == saved_report(read_bundle(path), "CYP2C19")
    client = TestClient(create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1")
    face = client.get(f"/runs/{path.name}")
    assert face.status_code == 200 and "compatible candidate(s)" in face.text
    assert "limited" in face.text and "1/1 resolved loci observed" in face.text
    detail = client.get(f"/runs/{path.name}/pgx?gene=CYP2C19")
    assert detail.status_code == 200 and "Intermediate Metabolizer" in detail.text
    assert "All 1 candidates remain available" in detail.text
    tier_page = client.get(f"/runs/{path.name}?group=tier")
    assert "Pharmacogenomics sample calls" in tier_page.text
    assert client.get(f"/runs/{path.name}/pgx?gene=CYP2D6").status_code == 400
    manifest_path = path / "manifest.json"
    header = json.loads(manifest_path.read_text())
    header["format_version"] = 18
    header["files"].pop(PGX_NAME)
    (path / PGX_NAME).unlink()
    manifest_path.write_text(json.dumps(header), encoding="utf-8")
    assert read_bundle(path).pgx is None
    historical = client.get(f"/runs/{path.name}/pgx?gene=CYP2C19")
    assert historical.status_code == 200 and "not-recorded" in historical.text


@pytest.mark.parametrize("kind", ["sex", "imputation", "digest"])
def test_pgx_bundle_refuses_inconsistent_inputs(
    frozen: dict[str, Any],
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
    kind: str,
) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.run.bundle import BundleError, write_bundle

    calls = calling.call(
        refresh_call_reference(frozen),
        sample_table([] if kind == "imputation" else [(101, "A", "G", "called")]),
        sex=sample_qc.sex.inferred,
        dosages=[imputed_marker()] if kind == "imputation" else [],
    ).to_dict()
    if kind == "sex":
        calls["sex"] = "female" if sample_qc.sex.inferred != InferredSex.FEMALE else "male"
    elif kind == "digest":
        calls["reference_sha256"] = "a" * 64
    with pytest.raises(BundleError):
        write_bundle(
            qc=sample_qc,
            cards=sample_cards,
            pack=sample_pack,
            ancestry=AncestryContext.not_run("Synthetic acceptance"),
            pgx=calls,
            runs_root=tmp_path / "runs",
            lock_path=tmp_path / "missing.lock",
            tools_root=tmp_path / "tools",
        )


def test_pipeline_executes_the_shared_pgx_stage(frozen: dict[str, Any]) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.run.pipeline import analyse

    export = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "ancestry_v2_male.txt"
    analysis = analyse(
        export,
        no_impute=True,
        pgx=calling.CallingStage(refresh_call_reference(frozen)),
        ancestry=lambda _table, _qc: AncestryContext.not_run("Synthetic acceptance"),
    )
    assert analysis.pgx is not None and analysis.pgx["status"] == "completed"
    assert set(analysis.pgx["genes"]) == set(catalog.TRACTABLE)


@pytest.fixture
def pgx_imputed_inputs(
    frozen: dict[str, Any],
    tmp_path: Path,
) -> tuple[catalog.Catalog, GenotypeTable, Any]:
    from genetics.testing.imputation_snapshots import anchors, synthetic_stage

    table = sample_table([])
    result = synthetic_stage(
        table, tmp_path / "private-stage", records=(*anchors("10"), imputed_marker())
    )
    return refresh_call_reference(frozen), table, result


@pytest.mark.parametrize("mutation", ["genotype", "quality", "missing", "extra"])
def test_review_writer_binds_pgx_to_native_dosages(
    pgx_imputed_inputs: tuple[catalog.Catalog, GenotypeTable, Any],
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    tmp_path: Path,
    mutation: str,
) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.imputation.context import ImputationContext
    from genetics.run.bundle import BundleError, write_bundle

    reference, table, stage = pgx_imputed_inputs
    records = list(stage.iter_dosages())
    if mutation == "genotype":
        records[-1] = replace(
            records[-1],
            genotype=(1, 1),
            storage_genotype=(1, 1),
            dosage=(1.8,),
            storage_dosage=(1.8,),
        )
    elif mutation == "quality":
        records[-1] = replace(records[-1], dr2=(0.9,))
    elif mutation == "missing":
        records.pop()
    else:
        records.append(records[-1])
    calls = calling.call(reference, table, sex=sample_qc.sex.inferred, dosages=records)
    with pytest.raises(BundleError, match="PGx"):
        write_bundle(
            qc=sample_qc,
            cards=(),
            pack=sample_pack,
            ancestry=AncestryContext.not_run("Synthetic review"),
            pgx=calls.to_dict(),
            imputation=ImputationContext.enabled(stage.summary(), quality_aware=True),
            imputation_result=stage,
            runs_root=tmp_path / "runs",
            lock_path=tmp_path / "missing.lock",
            tools_root=tmp_path / "tools",
        )


def test_review_reader_binds_pgx_to_native_dosages_without_caches(
    pgx_imputed_inputs: tuple[catalog.Catalog, GenotypeTable, Any],
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    tmp_path: Path,
) -> None:
    import hashlib
    import shutil

    from genetics.ancestry.context import AncestryContext
    from genetics.imputation.context import ImputationContext
    from genetics.run.bundle import PGX_NAME, BundleError, read_bundle, write_bundle

    reference, table, stage = pgx_imputed_inputs
    calls = calling.call(reference, table, sex=sample_qc.sex.inferred, dosages=stage.iter_dosages())
    path = write_bundle(
        qc=sample_qc,
        cards=(),
        pack=sample_pack,
        ancestry=AncestryContext.not_run("Synthetic review"),
        pgx=calls.to_dict(),
        imputation=ImputationContext.enabled(stage.summary(), quality_aware=True),
        imputation_result=stage,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "missing.lock",
        tools_root=tmp_path / "tools",
    )
    shutil.rmtree(stage.directory)
    assert read_bundle(path).pgx is not None
    raw = json.loads((path / PGX_NAME).read_text())
    raw["observations"][0]["dosages"][0]["dr2"] = [0.9]
    raw["genes"] = calling.derive(
        catalog.Catalog(raw["reference"]), raw["observations"], raw["sex"]
    )
    calling.validate(raw)
    text = json.dumps(raw)
    (path / PGX_NAME).write_text(text, encoding="utf-8")
    header = json.loads((path / "manifest.json").read_text())
    header["files"][PGX_NAME] = hashlib.sha256(text.encode()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(header), encoding="utf-8")
    with pytest.raises(BundleError, match="PGx"):
        read_bundle(path)


@pytest.mark.parametrize(
    "mutation",
    ["homozygote-count", "alternate-count-sum", "empty-population", "bad-vector", "missing-filter"],
)
def test_review_bad_frequency_inputs_fail_categorically(
    frozen: dict[str, Any], mutation: str
) -> None:
    from genetics.health.frequencies import parse_record

    record = parse_record(
        "\t".join(["10", "101", ".", "A", "G", ".", "PASS", "AF=0.2;AC=20;AN=100;nhomalt=0"])
    )
    if mutation == "homozygote-count":
        record["populations"]["global"]["nhomalt"] = [30]
    elif mutation == "alternate-count-sum":
        record["alts"].append("C")
        record["populations"]["global"].update(af=[0.8, 0.8], ac=[80, 80], nhomalt=[0, 0])
        record["af_popmax"] = [None, None]
        record["popmax"] = [None, None]
    elif mutation == "empty-population":
        record["populations"] = {"": record["populations"]["global"]}
    elif mutation == "bad-vector":
        record["populations"]["global"]["af"] = None
    else:
        record.pop("filter")
    with pytest.raises(calling.CallingError, match=r"malformed|invalid|inconsistent"):
        calling.call(
            refresh_call_reference(frozen),
            sample_table([(101, "A", "G", "called")]),
            sex=InferredSex.FEMALE,
            frequencies={("10", 101): [record]},
        )


def test_review_equal_alleles_cannot_claim_heterozygous_haploid(frozen: dict[str, Any]) -> None:
    with pytest.raises(calling.CallingError):
        calling.call(
            refresh_call_reference(frozen),
            sample_table([(101, "A", "A", "het_haploid")]),
            sex=InferredSex.FEMALE,
        )


def test_review_invalid_prepared_reference_reports_pgx_not_imputation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genetics.cli.run_cmd import _error_kind

    (tmp_path / "cpic").mkdir()
    (tmp_path / "cpic" / "pgx_reference.json").write_text("{}")
    monkeypatch.setattr(calling, "references_dir", lambda: tmp_path)
    monkeypatch.setattr("genetics.paths.references_dir", lambda: tmp_path)
    with pytest.raises(calling.CallingError) as error:
        calling.CallingStage().prepare()
    assert _error_kind(error.value) == "pgx"


@pytest.mark.parametrize("case", ["constraint-label", "artifact-style"])
def test_review_candidate_view_names_the_correct_allele_and_styles_reliability(
    frozen: dict[str, Any],
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    case: str,
) -> None:
    from fastapi.testclient import TestClient

    from genetics.ancestry.context import AncestryContext
    from genetics.health.frequencies import parse_record
    from genetics.run.bundle import write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    frequencies = {}
    if case == "constraint-label":
        tables = frozen["cpic"]["tables"]
        tables["allele_definition"][0]["matchesreferencesequence"] = "f"
        tables["sequence_location"].append(
            {
                **tables["sequence_location"][0],
                "id": "9",
                "position": "202",
                "chromosomelocation": "g.202C>T",
                "dbsnpid": None,
            }
        )
        tables["allele_location_value"].append(
            {"alleledefinitionid": "2", "locationid": "9", "variantallele": "T", "version": "1"}
        )
    else:
        public = parse_record(
            "\t".join(["10", "101", ".", "A", "G", ".", "PASS", "AF=0.000001;AC=1;AN=1000000"])
        )
        frequencies[("10", 101)] = [public]
    result = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=sample_qc.sex.inferred,
        frequencies=frequencies,
    )
    root = tmp_path / "runs"
    path = write_bundle(
        qc=sample_qc,
        cards=(),
        pack=sample_pack,
        ancestry=AncestryContext.not_run("Synthetic review"),
        pgx=result.to_dict(),
        runs_root=root,
        run_id="review",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    client = TestClient(create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1")
    if case == "constraint-label":
        page = client.get(f"/runs/{path.name}/pgx?gene=CYP2C19")
        assert page.status_code == 200 and "1 for *2" in page.text
    else:
        page = client.get(f"/runs/{path.name}")
        assert page.status_code == 200 and 'class="card tier-likely-artifact"' in page.text
        assert 'class="tier tier-likely-artifact"' in page.text
        assert "~16%" in page.text


@pytest.mark.parametrize("source", ["direct", "imputed_no_call"])
def test_review_native_evidence_also_binds_original_probe_calls(
    frozen: dict[str, Any],
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    source: str,
) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.imputation.context import ImputationContext
    from genetics.run.bundle import BundleError, write_bundle
    from genetics.testing.imputation_snapshots import anchors, synthetic_stage

    original = sample_table(
        [(101, None, None, "no_call")]
        if source == "imputed_no_call"
        else [(101, "A", "G", "called")]
    )
    native = replace(
        imputed_marker(source="imputed_no_call"),
        source=source,
        array_outcome="no_call" if source == "imputed_no_call" else "as_written",
        dosage_method="phased_hardcall_only"
        if source == "imputed_no_call"
        else "observed_allele_count",
    )
    stage = synthetic_stage(original, tmp_path / "stage", records=(*anchors("10"), native))
    changed = sample_table([(101, "G", "G", "called")])
    calls = calling.call(
        refresh_call_reference(frozen),
        changed,
        sex=sample_qc.sex.inferred,
        dosages=stage.iter_dosages(),
    )
    with pytest.raises(BundleError, match="PGx"):
        write_bundle(
            qc=sample_qc,
            cards=(),
            pack=sample_pack,
            ancestry=AncestryContext.not_run("Synthetic review"),
            pgx=calls.to_dict(),
            imputation=ImputationContext.enabled(stage.summary(), quality_aware=True),
            imputation_result=stage,
            runs_root=tmp_path / "runs",
            lock_path=tmp_path / "missing.lock",
            tools_root=tmp_path / "tools",
        )


@pytest.mark.parametrize(
    "ploidy,outcome",
    [(1, "as_written"), (2, "as_written"), (1, "complemented"), (2, "complemented")],
)
def test_review_native_original_probe_controls_preserve_ploidy_and_orientation(
    frozen: dict[str, Any],
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    ploidy: int,
    outcome: str,
) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.imputation.context import ImputationContext
    from genetics.run.bundle import read_bundle, write_bundle
    from genetics.testing.imputation_snapshots import anchors, synthetic_stage

    chrom, pos = ("X", 10000000) if ploidy == 1 else ("10", 101)
    if ploidy == 1:
        gene_reference(frozen, "G6PD", chrom=chrom)
        frozen["cpic"]["tables"]["sequence_location"][0].update(
            position=str(pos), chromosomelocation=f"g.{pos}A>G"
        )
        frozen["dbsnp"]["variants"][0]["pos_grch37"] = pos
    base = "C" if outcome == "complemented" else "G"
    original = sample_table(
        [(pos, base, base, "hemizygous" if ploidy == 1 else "called")], chrom=chrom
    )
    native = DosageRecord(
        chrom,
        pos,
        "A",
        ("G",),
        (1,) * ploidy,
        (1,) * ploidy,
        (float(ploidy),),
        (float(ploidy),),
        None,
        ploidy,
        "direct",
        "resolved",
        outcome,
        "observed_allele_count",
        "not_estimated",
    )
    stage = synthetic_stage(
        original,
        tmp_path / "stage",
        records=(*anchors(chrom, start=pos - 20, ploidy=ploidy), native),
    )
    calls = calling.call(
        refresh_call_reference(frozen),
        original,
        sex=sample_qc.sex.inferred,
        dosages=stage.iter_dosages(),
    )
    path = write_bundle(
        qc=sample_qc,
        cards=(),
        pack=sample_pack,
        ancestry=AncestryContext.not_run("Synthetic control"),
        pgx=calls.to_dict(),
        imputation=ImputationContext.enabled(stage.summary(), quality_aware=True),
        imputation_result=stage,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    saved = read_bundle(path)
    assert saved.pgx is not None and sources.digest(saved.pgx) == sources.digest(calls.to_dict())


def tables_fixture() -> Tables:
    tables: Tables = {name: [] for name in REQUIRED}

    def add(table: str, **values: str | None) -> None:
        tables[table].append({**dict.fromkeys(REQUIRED[table]), **values})

    add(
        "gene",
        symbol="CYP2C19",
        chr="chr10",
        chromosequenceid="NC_000010.11",
        lookupmethod="PHENOTYPE",
        version="1",
    )
    add(
        "allele_definition",
        id="1",
        version="1",
        genesymbol="CYP2C19",
        name="*1",
        matchesreferencesequence="t",
        structuralvariation="f",
    )
    add(
        "allele_definition",
        id="2",
        version="1",
        genesymbol="CYP2C19",
        name="*2",
        matchesreferencesequence="f",
        structuralvariation="f",
    )
    add(
        "sequence_location",
        id="3",
        version="1",
        genesymbol="CYP2C19",
        chromosomelocation="g.201A>G",
        dbsnpid="rs1000001",
        position="201",
    )
    add(
        "allele_location_value",
        alleledefinitionid="1",
        locationid="3",
        variantallele="A",
        version="1",
    )
    add(
        "allele_location_value",
        alleledefinitionid="2",
        locationid="3",
        variantallele="G",
        version="1",
    )
    for i, name, function in (("1", "*1", "Normal function"), ("2", "*2", "No function")):
        add(
            "allele",
            id=str(int(i) + 3),
            version="1",
            genesymbol="CYP2C19",
            name=name,
            definitionid=i,
            functionalstatus=function,
            clinicalfunctionalstatus=function,
            citations="{10000001}",
            strength="strong",
            functioncomments="Fabricated reference-only description, with 'quotes' and\na second line.",
        )
    add(
        "gene_result",
        id="6",
        genesymbol="CYP2C19",
        result="Intermediate Metabolizer",
        activityscore="n/a",
        version="1",
    )
    add(
        "gene_result_lookup",
        id="7",
        phenotypeid="6",
        lookupkey='{"Normal function":1,"No function":1}',
        function1="Normal function",
        function2="No function",
    )
    add(
        "gene_result_diplotype",
        id="8",
        functionphenotypeid="7",
        diplotype="*1/*2",
        diplotypekey='{"CYP2C19":{"*1":1,"*2":1}}',
    )
    return tables


def write_sql(path: Path, tables: Tables, *, inserts: bool = False) -> Path:
    text = "SET standard_conforming_strings = on;\n"
    for table, required in REQUIRED.items():
        columns = list(tables[table][0]) if tables[table] else list(required)
        text += (
            f"CREATE TABLE cpic.{table} (\n" + ",\n".join(f" {c} text" for c in columns) + "\n);\n"
        )
        if inserts:
            for row in tables[table]:
                values = [
                    "NULL" if row[c] is None else "'" + (row[c] or "").replace("'", "''") + "'"
                    for c in columns
                ]
                text += f"INSERT INTO cpic.{table} ({', '.join(columns)}) VALUES ({', '.join(values)});\n"
        else:
            text += f"COPY cpic.{table} ({', '.join(columns)}) FROM stdin;\n"
            for row in tables[table]:
                values = [
                    r"\N"
                    if row[c] is None
                    else (row[c] or "")
                    .replace("\\", "\\\\")
                    .replace("\n", r"\n")
                    .replace("\t", r"\t")
                    .replace("\r", r"\r")
                    for c in columns
                ]
                text += "\t".join(values) + "\n"
            text += "\\.\n"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def archive_fixture(
    path: Path,
    *,
    extra: zipfile.ZipInfo | str | None = None,
    license_id: str = "by-nc-sa",
    variants: list[dict[str, str]] | None = None,
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("LICENSE.txt", f"https://creativecommons.org/licenses/{license_id}/4.0/")
        archive.writestr("CREATED_2026-01-01.txt", "Created on 01/01/2026.")
        for name in MEMBERS[path.name]:
            columns = list(HEADERS[name])
            rows = []
            if name == "variants.tsv":
                rows = variants or [
                    {
                        "Variant ID": "PA1000001",
                        "Variant Name": "rs1000001",
                        "Gene Symbols": "CYP2C19",
                        "Location": "NC_000010.11:201",
                        "Synonyms": "rs1000001, NC_000010.11:g.201A>G, NC_000010.10:g.101A>G",
                    }
                ]
            stream = io.StringIO(newline="")
            import csv

            writer = csv.DictWriter(stream, columns, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(name, stream.getvalue())
        if extra is not None:
            archive.writestr(extra, "ignored")
    return path


@pytest.fixture
def reference_sources(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    for source_id in ("cpic", "pharmgkb"):
        (tmp_path / source_id).mkdir()
    tables = tables_fixture()
    cpic_source = manifest.load().get("cpic")
    for remote in cpic_source.files:
        write_sql(
            tmp_path / "cpic" / remote.filename, tables, inserts="_inserts" in remote.filename
        )
    for name in MEMBERS:
        archive_fixture(tmp_path / "pharmgkb" / name)
    for source_id in ("cpic", "pharmgkb"):
        result = postprocess.run(manifest.load().get(source_id), root=tmp_path)
        assert result[0].status is ProcessStatus.CREATED, result
    return (
        tmp_path,
        sources.load_source(tmp_path / "cpic" / "pgx_cpic.json"),
        sources.load_source(tmp_path / "pharmgkb" / "pgx_annotations.json"),
    )


def dbsnp_fixture(root: Path) -> dict[str, Any]:
    directory = root / "dbsnp_b157_grch37"
    directory.mkdir(exist_ok=True)
    records = [{"rsid": "rs1000001", "chrom": "10", "pos_grch37": 101, "ref": "A", "alts": ["G"]}]
    files = {
        "dbsnp_variants.parquet": pl.DataFrame(records, schema=postprocess.VARIANT_INDEX_SCHEMA),
        "rsid_merges.parquet": pl.DataFrame(
            schema={"retired_rsid": pl.String, "current_rsid": pl.String}
        ),
        "rsid_unresolvable.parquet": pl.DataFrame(
            schema={"retired_rsid": pl.String, "status": pl.String, "targets": pl.List(pl.String)}
        ),
    }
    for name, frame in files.items():
        file = directory / name
        frame.write_parquet(file)
        step = "extract_dbsnp_variant_index" if "variants" in name else "extract_rsid_merge_table"
        postprocess._write_provenance(
            file,
            {
                "step": step,
                "transform_version": postprocess.get(step).transform_version,
                "input": {"filename": "synthetic-reference", "sha256": "a" * 64},
                "params": {},
                "output": name,
            },
            frame.height,
        )
    return catalog._dbsnp(root, {"rs1000001"}, bind=False)


@pytest.fixture
def frozen(reference_sources: tuple[Path, dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    root, cpic, annotations = reference_sources
    return catalog.assemble(cpic, annotations, dbsnp_fixture(root))


def save_catalog(path: Path, record: dict[str, Any]) -> Path:
    postprocess._write_json_atomic(path, record)
    inputs = {
        "cpic": record["cpic"]["source"],
        "pharmgkb": record["annotations"]["source"],
        "dbsnp": record["dbsnp"]["provenance"],
    }
    postprocess._write_provenance(
        path,
        {
            "step": "prepare_pgx_reference",
            "transform_version": 1,
            "input": {"filename": "synthetic-reference-set", "sha256": sources.digest(inputs)},
            "params": {"build": "GRCh37", "strand": "+"},
            "output": path.name,
        },
        len(record["definitions"]),
    )
    return path


def test_cpic_encodings_independently_preserve_escapes_and_nulls(tmp_path: Path) -> None:
    tables = tables_fixture()
    copied = read_dump(write_sql(tmp_path / "copy.sql.gz", tables), mode="copy")
    inserted = read_dump(
        write_sql(tmp_path / "inserts.sql.gz", tables, inserts=True), mode="inserts"
    )
    assert copied == inserted == tables
    assert copied["allele"][0]["functioncomments"].endswith("\na second line.")  # type: ignore[union-attr]
    assert copied["allele_definition"][0]["pharmvarid"] is None
    assert copy_value(r"line\tvalue\n\101\\") == "line\tvalue\nA\\"


@pytest.mark.parametrize("raw", ["\\", r"\xZ", r"\q"])
def test_cpic_malformed_copy_escapes_fail(raw: str) -> None:
    with pytest.raises(ProcessError):
        copy_value(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        "column-count",
        "missing-column",
        "duplicate-block",
        "truncated",
        "expression",
        "strings-off",
        "truncated-schema",
    ],
)
def test_malformed_sql_is_refused(tmp_path: Path, mutation: str) -> None:
    inserts = mutation == "expression"
    path = write_sql(tmp_path / "data.sql.gz", tables_fixture(), inserts=inserts)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        text = handle.read()
    if mutation == "column-count":
        text = text.replace("CYP2C19\tchr10", "CYP2C19\textra\tchr10", 1)
    elif mutation == "missing-column":
        text = text.replace("chromosequenceid", "wrong_column")
    elif mutation == "duplicate-block":
        text += "COPY cpic.gene (symbol, chr, chromosequenceid, lookupmethod, version) FROM stdin;\n\\.\n"
    elif mutation == "truncated":
        text = text[: text.index("\\.\n")]
    elif mutation == "expression":
        text = text.replace("'CYP2C19'", "dangerous_function()", 1)
    elif mutation == "strings-off":
        text = text.replace("strings = on", "strings = off")
    else:
        text = "CREATE TABLE cpic.gene (\n symbol text\n"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)
    with pytest.raises(ProcessError):
        read_dump(path, mode="inserts" if inserts else "copy")


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "/escape.txt",
        "C:/escape.txt",
        "x\\escape.txt",
        "x/../escape.txt",
        "CON.txt",
        "license.TXT",
        "variants.tsv",
        "trailing.",
        "folder/",
        "unknown.tsv",
    ],
)
def test_archive_paths_and_duplicate_members_never_escape(tmp_path: Path, name: str) -> None:
    with (
        pytest.warns(UserWarning)
        if name == "variants.tsv"
        else __import__("contextlib").nullcontext()
    ):
        path = archive_fixture(tmp_path / "variants.zip", extra=name)
    with pytest.raises(ProcessError):
        read_archive(path)
    assert not (tmp_path.parent / "escape.txt").exists()


def test_archive_symlink_is_refused(tmp_path: Path) -> None:
    member = zipfile.ZipInfo("shortcut.txt")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ProcessError):
        read_archive(archive_fixture(tmp_path / "variants.zip", extra=member))


@pytest.mark.parametrize("license_id", ["by-nc-nd", "by", "unknown"])
def test_unknown_archive_terms_are_never_assumed_permissive(
    tmp_path: Path, license_id: str
) -> None:
    with pytest.raises(ProcessError, match="license"):
        read_archive(archive_fixture(tmp_path / "variants.zip", license_id=license_id))


@pytest.mark.parametrize("mutation", ["shape", "missing-date", "missing-license", "bad-crc"])
def test_malformed_archives_fail(tmp_path: Path, mutation: str) -> None:
    path = archive_fixture(tmp_path / "variants.zip")
    if mutation == "bad-crc":
        raw = path.read_bytes().replace(b"Created on", b"Changed on")
        path.write_bytes(raw)
    else:
        with zipfile.ZipFile(path) as archive:
            data = {n: archive.read(n) for n in archive.namelist()}
        if mutation == "shape":
            data["variants.tsv"] += b"too\tfew\n"
        else:
            del data["LICENSE.txt" if mutation == "missing-license" else "CREATED_2026-01-01.txt"]
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in data.items():
                archive.writestr(name, value)
    with pytest.raises(ProcessError):
        read_archive(path)


def test_full_source_ingestion_reuses_verified_completion(
    reference_sources: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    root, cpic, annotations = reference_sources
    assert cpic["encodings_agree"] is True
    assert len(annotations["archives"]) == 5
    for source_id in ("cpic", "pharmgkb"):
        source = manifest.load().get(source_id)
        assert postprocess.run(source, root=root)[0].status is ProcessStatus.ALREADY_PRESENT
        assert (
            postprocess.run(source, root=root, verify_only=True)[0].status is ProcessStatus.VERIFIED
        )


def test_copy_and_inserts_disagreement_is_detected(
    reference_sources: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    root, _, _ = reference_sources
    source = manifest.load().get("cpic")
    tables = tables_fixture()
    tables["allele"][0]["functionalstatus"] = "Wrong function"
    name = next(f.filename for f in source.files if "_inserts" in f.filename)
    write_sql(root / "cpic" / name, tables, inserts=True)
    result = postprocess.run(source, root=root)[0]
    assert result.status is ProcessStatus.FAILED and "disagree" in result.detail


def test_input_drift_cannot_use_stale_download_identity(
    reference_sources: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    root, _, _ = reference_sources
    source = manifest.load().get("cpic")
    result = postprocess.run(
        source, root=root, input_digests={f.filename: "b" * 64 for f in source.files}
    )[0]
    assert result.status is ProcessStatus.FAILED and "verified download" in result.detail


def test_restart_after_interrupted_publication(
    reference_sources: tuple[Path, dict[str, Any], dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, _ = reference_sources
    output = root / "cpic" / "pgx_cpic.json"
    output.unlink()
    original = postprocess._write_provenance
    with monkeypatch.context() as patch:
        patch.setattr(
            postprocess,
            "_write_provenance",
            lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
        with pytest.raises(KeyboardInterrupt):
            postprocess.run(manifest.load().get("cpic"), root=root)
    assert original is postprocess._write_provenance
    # The old sidecar hashes the same deterministic content, so the completed
    # payload is reusable even when interruption happened before sidecar rewrite.
    postprocess.provenance_path(output).unlink()
    assert (
        postprocess.run(manifest.load().get("cpic"), root=root, verify_only=True)[0].status
        is ProcessStatus.FAILED
    )
    assert (
        postprocess.run(manifest.load().get("cpic"), root=root)[0].status is ProcessStatus.CREATED
    )


def test_kernel_lock_is_exclusive_and_released_after_failure(tmp_path: Path) -> None:
    output = tmp_path / "reference.json"
    with (
        publication_lock(output),
        pytest.raises(ProcessError, match="Another process"),
        publication_lock(output),
    ):
        pass
    with publication_lock(output):
        pass


def test_normalization_preserves_forward_alleles_and_source_identity(
    frozen: dict[str, Any],
) -> None:
    catalog.validate_record(frozen)
    locus = frozen["locations"]["3"]
    assert locus["key"] == {"chrom": "10", "pos_grch37": 101, "alleles": ["A", "G"]}
    assert locus["source_location"]["position"] == "201" and locus["source_build"] == "GRCh38"
    assert locus["mapping_evidence"][0]["variant_id"] == "PA1000001"
    assert frozen["definitions"]["2"]["constraints"][0]["required_allele"] == "G"
    assert frozen["definitions"]["2"]["functions"][0]["clinicalfunctionalstatus"] == "No function"


@pytest.mark.parametrize(
    "mutation,state",
    [
        ("unknown-build", "unknown-source-build"),
        ("indel", "unsupported-allele-representation"),
        ("coordinate", "conflicting-source-coordinate"),
        ("missing-rsid", "missing-rsid"),
        ("ambiguous-rsid", "unresolved-rsid"),
        ("missing-map", "missing-grch37-mapping"),
        ("map-conflict", "conflicting-grch37-mapping"),
        ("missing-dbsnp", "missing-dbsnp-variant"),
        ("ambiguous-dbsnp", "ambiguous-dbsnp-variant"),
        ("allele-conflict", "conflicting-dbsnp-variant"),
    ],
)
def test_ambiguous_and_absent_reference_definitions_remain_visible(
    frozen: dict[str, Any], mutation: str, state: str
) -> None:
    cpic, annotations, dbsnp = frozen["cpic"], frozen["annotations"], frozen["dbsnp"]
    location = cpic["tables"]["sequence_location"][0]
    if mutation == "unknown-build":
        cpic["tables"]["gene"][0]["chromosequenceid"] = "NC_000010.999"
    elif mutation == "indel":
        location["chromosomelocation"] = "g.201_202del"
    elif mutation == "coordinate":
        location["position"] = "202"
    elif mutation == "missing-rsid":
        location["dbsnpid"] = None
    elif mutation == "ambiguous-rsid":
        dbsnp["resolutions"]["rs1000001"] = {
            "status": "multiple-current-targets",
            "current_rsid": None,
            "targets": ["rs1000002", "rs1000003"],
        }
    elif mutation == "missing-map":
        annotations["variants"][0]["Synonyms"] = "rs1000001, NC_000010.11:g.201A>G"
    elif mutation == "map-conflict":
        annotations["variants"][0]["Synonyms"] += ", NC_000010.10:g.102A>G"
    elif mutation == "missing-dbsnp":
        dbsnp["variants"] = []
    elif mutation == "ambiguous-dbsnp":
        dbsnp["variants"] *= 2
    else:
        dbsnp["variants"][0]["ref"] = "T"
    locations, definitions = catalog.normalize(cpic, annotations["variants"], dbsnp)
    assert locations["3"]["state"] == state and locations["3"]["key"] is None
    assert len(definitions) == 2 and definitions["2"]["state"] == "partially-resolved-definition"


def test_retired_rsid_keeps_original_and_current_identity(frozen: dict[str, Any]) -> None:
    frozen["dbsnp"]["resolutions"]["rs1000001"]["current_rsid"] = "rs1000002"
    frozen["dbsnp"]["variants"][0]["rsid"] = "rs1000002"
    locations, _ = catalog.normalize(
        frozen["cpic"], frozen["annotations"]["variants"], frozen["dbsnp"]
    )
    assert locations["3"]["source_location"]["dbsnpid"] == "rs1000001"
    assert locations["3"]["rsid_resolution"]["current_rsid"] == "rs1000002"
    assert locations["3"]["state"] == "resolved-snv"


@pytest.mark.parametrize(
    "mutation,state",
    [
        ("structural", "unsupported-structural-or-copy-number"),
        ("missing", "missing-definition"),
        ("reference", "reference-definition"),
        ("iupac", "partially-resolved-definition"),
    ],
)
def test_structural_and_sparse_definitions_are_not_silently_filled(
    frozen: dict[str, Any], mutation: str, state: str
) -> None:
    tables = frozen["cpic"]["tables"]
    if mutation == "structural":
        tables["allele_definition"][1]["structuralvariation"] = "t"
    elif mutation == "iupac":
        tables["allele_location_value"][1]["variantallele"] = "R"
    else:
        tables["allele_location_value"] = tables["allele_location_value"][:1]
        if mutation == "reference":
            tables["allele_definition"][1]["matchesreferencesequence"] = "t"
    _, definitions = catalog.normalize(
        frozen["cpic"], frozen["annotations"]["variants"], frozen["dbsnp"]
    )
    assert definitions["2"]["state"] == state


@pytest.mark.parametrize(
    "mutation",
    [
        "dangling-function",
        "dangling-marker",
        "duplicate-definition",
        "unknown-gene",
        "bad-bool",
        "wrong-phenotype-gene",
        "boolean-count",
        "nonfinite-lookup",
        "duplicate-marker",
    ],
)
def test_malformed_cpic_joins_are_refused(mutation: str) -> None:
    tables = tables_fixture()
    if mutation == "dangling-function":
        tables["allele"][0]["definitionid"] = "999"
    elif mutation == "dangling-marker":
        tables["allele_location_value"][0]["locationid"] = "999"
    elif mutation == "duplicate-definition":
        tables["allele_definition"].append(dict(tables["allele_definition"][0]))
    elif mutation == "unknown-gene":
        tables["allele_definition"][0]["genesymbol"] = "UNKNOWN"
    elif mutation == "bad-bool":
        tables["allele_definition"][0]["structuralvariation"] = "unknown"
    elif mutation == "wrong-phenotype-gene":
        tables["gene_result_diplotype"][0]["diplotypekey"] = '{"DPYD":{"*1":1,"*2":1}}'
    elif mutation == "boolean-count":
        tables["gene_result_diplotype"][0]["diplotypekey"] = '{"CYP2C19":{"*1":true}}'
    elif mutation == "nonfinite-lookup":
        tables["gene_result_lookup"][0]["lookupkey"] = '{"function":NaN}'
    else:
        tables["allele_location_value"].append(dict(tables["allele_location_value"][0]))
    with pytest.raises(ProcessError):
        sources.validate_tables(tables)


@pytest.mark.parametrize(
    "mutation", ["key", "function", "state", "mapping", "schema", "calling", "counts", "proof"]
)
def test_digest_consistent_catalog_corruption_fails(
    tmp_path: Path, frozen: dict[str, Any], mutation: str
) -> None:
    if mutation == "key":
        frozen["locations"]["3"]["key"]["pos_grch37"] = 102
    elif mutation == "function":
        frozen["definitions"]["2"]["functions"][0]["clinicalfunctionalstatus"] = "Wrong"
    elif mutation == "state":
        frozen["definitions"]["2"]["state"] = "missing-definition"
    elif mutation == "mapping":
        frozen["cpic"]["tables"]["gene_result_lookup"][0]["phenotypeid"] = "999"
    elif mutation == "schema":
        frozen["schema_version"] = True
    elif mutation == "calling":
        frozen["sample_calling_implemented"] = True
    elif mutation == "counts":
        frozen["annotations"]["archives"][0]["table_rows"]["clinical_annotations.tsv"] = -1
    else:
        frozen["dbsnp"]["provenance"]["rsid_merges.parquet"]["input"]["sha256"] = "b" * 64
    with pytest.raises(ProcessError):
        catalog.Catalog.load(save_catalog(tmp_path / "reference.json", frozen))


def test_saved_reference_is_independent_of_stage_caches_and_shared_with_cli(
    tmp_path: Path, frozen: dict[str, Any]
) -> None:
    path = save_catalog(tmp_path / "reference.json", frozen)
    expected = catalog.Catalog.load(path).inspect(gene="CYP2C19", allele="*2", diplotype="*2/*1")
    result = CliRunner().invoke(
        app,
        [
            "pgx",
            "inspect",
            "--reference",
            str(path),
            "--gene",
            "CYP2C19",
            "--allele",
            "*2",
            "--diplotype",
            "*2/*1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    actual = json.loads(result.output)
    assert actual == {"ok": True, **expected}
    assert actual["mapping_status"] == "available"
    assert actual["diplotype_mappings"][0]["phenotype"]["result"] == "Intermediate Metabolizer"
    assert actual["definitions"][0]["functions"][0]["citations"] == "{10000001}"
    assert actual["sample_calling_implemented"] is False


def test_missing_and_conflicting_phenotypes_stay_explicit(frozen: dict[str, Any]) -> None:
    tables = frozen["cpic"]["tables"]
    tables["gene_result"].append({**tables["gene_result"][0], "id": "9", "result": "Indeterminate"})
    tables["gene_result_lookup"].append(
        {**tables["gene_result_lookup"][0], "id": "10", "phenotypeid": "9"}
    )
    tables["gene_result_diplotype"].append(
        {**tables["gene_result_diplotype"][0], "id": "11", "functionphenotypeid": "10"}
    )
    frozen["cpic"]["rows"] += 3
    catalog.validate_record(frozen)
    cat = catalog.Catalog(frozen)
    assert (
        cat.inspect(gene="CYP2C19", diplotype="*1/*2")["mapping_status"] == "conflicting-mappings"
    )
    assert len(cat.inspect(gene="CYP2C19", diplotype="*1/*2")["diplotype_mappings"]) == 2
    assert cat.inspect(gene="CYP2C19", diplotype="*99/*1")["mapping_status"] == "missing-mapping"
    assert cat.inspect(gene="CYP2C19", allele="*99")["definition_status"] == "not-defined"


@pytest.mark.parametrize(
    "args",
    [
        ["--gene", "UNKNOWN"],
        ["--allele", "*1"],
        ["--diplotype", "*1/*2"],
        ["--gene", "CYP2C19", "--diplotype", "*1/"],
    ],
)
def test_cli_errors_are_json_not_tracebacks(
    tmp_path: Path, frozen: dict[str, Any], args: list[str]
) -> None:
    path = save_catalog(tmp_path / "reference.json", frozen)
    result = CliRunner().invoke(app, ["pgx", "inspect", "--reference", str(path), *args, "--json"])
    assert result.exit_code == 1 and json.loads(result.output)["ok"] is False


def test_prepare_reuses_and_repairs_corrupt_catalog(
    reference_sources: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    root, _, _ = reference_sources
    dbsnp_fixture(root)
    path, status = catalog.prepare(root, bind_to_manifest=False)
    assert status == "created"
    assert catalog.prepare(root, bind_to_manifest=False) == (path, "already-present")
    path.write_text("broken", encoding="utf-8")
    assert catalog.prepare(root, bind_to_manifest=False) == (path, "created")
    assert catalog.Catalog.load(path).inspect()["counts"]["definitions"] == 2


def test_declared_licenses_and_executor_gate_are_honest() -> None:
    postprocess.assert_registry_is_honest()
    sources_ = manifest.load()
    for source_id in ("cpic", "pharmgkb"):
        assert sources_.get(source_id).license.needs_opt_in is True
        result = CliRunner().invoke(
            app, ["refs", "fetch", "--dry-run", "--only", source_id, "--json"]
        )
        payload = json.loads(result.output)
        assert payload["sources"][0]["blocked"]
    assert sources_.get("pharmgkb").license.commercial_ok is False


def test_bad_source_and_changed_step_cannot_reuse(
    reference_sources: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    root, _, _ = reference_sources
    source = manifest.load().get("cpic")
    changed = replace(source, version="other-release")
    assert postprocess.run(changed, root=root, verify_only=True)[0].status is ProcessStatus.FAILED
    output = root / "cpic" / "pgx_cpic.json"
    record = json.loads(output.read_text(encoding="utf-8"))
    record["rows"] += 1
    postprocess._write_json_atomic(output, record)
    with pytest.raises(ProcessError):
        sources.load_source(output)


@pytest.mark.parametrize(
    "field,value", [("id", "wrong-source"), ("version", "wrong-release"), ("license_id", "CC0-1.0")]
)
def test_source_labels_are_bound_to_publication_provenance(
    reference_sources: tuple[Path, dict[str, Any], dict[str, Any]], field: str, value: str
) -> None:
    root, _, _ = reference_sources
    output = root / "cpic" / "pgx_cpic.json"
    record = json.loads(output.read_text(encoding="utf-8"))
    record["source"][field] = value
    postprocess._write_json_atomic(output, record)
    sidecar = json.loads(postprocess.provenance_path(output).read_text(encoding="utf-8"))
    sidecar["output_sha256"] = postprocess._sha256(output)
    postprocess.provenance_path(output).write_text(json.dumps(sidecar), encoding="utf-8")
    with pytest.raises(ProcessError):
        sources.load_source(output)


@pytest.mark.parametrize(
    "mutation",
    [
        "license",
        "missing-archive",
        "source-identity",
        "table-count",
        "boolean-key",
        "boolean-sidecar",
    ],
)
def test_frozen_metadata_and_numeric_types_are_verified(
    tmp_path: Path, frozen: dict[str, Any], mutation: str
) -> None:
    if mutation == "license":
        frozen["annotations"]["archives"][0]["license_id"] = "CC-BY-SA-4.0"
    elif mutation == "missing-archive":
        frozen["annotations"]["archives"].pop()
    elif mutation == "source-identity":
        frozen["annotations"]["source"]["id"] = "cpic"
    elif mutation == "table-count":
        frozen["annotations"]["archives"][0]["table_rows"] = {"different-table": 0}
    elif mutation == "boolean-key":
        frozen["locations"]["3"]["key"]["pos_grch37"] = True
    path = save_catalog(tmp_path / "reference.json", frozen)
    if mutation == "boolean-sidecar":
        sidecar = json.loads(postprocess.provenance_path(path).read_text(encoding="utf-8"))
        sidecar["transform_version"] = True
        postprocess.provenance_path(path).write_text(json.dumps(sidecar), encoding="utf-8")
    with pytest.raises(ProcessError):
        catalog.Catalog.load(path)


def test_duplicate_named_and_incompatible_locus_definitions_are_conflicts(
    frozen: dict[str, Any],
) -> None:
    tables = frozen["cpic"]["tables"]
    tables["allele_definition"].append({**tables["allele_definition"][1], "id": "20"})
    _, definitions = catalog.normalize(
        frozen["cpic"], frozen["annotations"]["variants"], frozen["dbsnp"]
    )
    assert definitions["2"]["state"] == definitions["20"]["state"] == "conflicting-definition"
    tables["allele_definition"].pop()
    tables["sequence_location"].append({**tables["sequence_location"][0], "id": "21"})
    tables["allele_location_value"].append(
        {
            **tables["allele_location_value"][0],
            "alleledefinitionid": "2",
            "locationid": "21",
            "variantallele": "A",
        }
    )
    _, definitions = catalog.normalize(
        frozen["cpic"], frozen["annotations"]["variants"], frozen["dbsnp"]
    )
    assert definitions["2"]["state"] == "conflicting-definition"


def test_absent_function_and_phenotype_tables_are_visible(frozen: dict[str, Any]) -> None:
    tables = frozen["cpic"]["tables"]
    tables["allele"] = tables["allele"][:1]
    _, definitions = catalog.normalize(
        frozen["cpic"], frozen["annotations"]["variants"], frozen["dbsnp"]
    )
    assert definitions["2"]["function_state"] == "missing-function"
    tables["gene_result"] = tables["gene_result_lookup"] = tables["gene_result_diplotype"] = []
    report = catalog.Catalog({**frozen, "definitions": definitions}).inspect(
        gene="CYP2C19", diplotype="*1/*2"
    )
    assert report["phenotype_mapping_status"] == "not-provided"
    assert report["mapping_status"] == "missing-mapping"


def test_prepare_missing_prerequisites_reports_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("genetics.paths.references_dir", lambda: tmp_path)
    result = CliRunner().invoke(app, ["pgx", "prepare", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["ok"] is False


def test_null_guideline_links_do_not_attribute_unrelated_publications(
    frozen: dict[str, Any],
) -> None:
    tables = frozen["cpic"]["tables"]
    tables["pair"] = [
        {
            **dict.fromkeys(REQUIRED["pair"]),
            "pairid": "10",
            "genesymbol": "CYP2C19",
            "drugid": "drug",
            "guidelineid": None,
        },
        {
            **dict.fromkeys(REQUIRED["pair"]),
            "pairid": "11",
            "genesymbol": "CYP2C19",
            "drugid": "drug",
            "guidelineid": "20",
        },
    ]
    tables["guideline"] = [
        {
            **dict.fromkeys(REQUIRED["guideline"]),
            "id": identity,
            "version": "1",
            "name": "Synthetic guideline",
        }
        for identity in ("20", "21")
    ]
    tables["publication"] = [
        {
            **dict.fromkeys(REQUIRED["publication"]),
            "id": identity,
            "version": "1",
            "pmid": pmid,
            "guidelineid": guideline,
            "title": "Synthetic publication",
        }
        for identity, pmid, guideline in (
            ("30", "10000001", None),  # Direct allele citation; include it.
            ("31", "10000002", None),  # No actual link; exclude it.
            ("32", "10000003", "20"),  # Actual gene guideline; include it.
            ("33", "10000004", "21"),  # Another guideline; exclude it.
        )
    ]
    frozen["cpic"]["rows"] = sum(map(len, tables.values()))
    catalog.validate_record(frozen)
    report = catalog.Catalog(frozen).inspect(gene="CYP2C19", allele="*2")
    assert {p["pmid"] for p in report["publications"]} == {"10000001", "10000003"}
    assert [g["id"] for g in report["guidelines"]] == ["20"]


@pytest.mark.parametrize("destination", ["payload", "sidecar"])
def test_atomic_publication_never_truncates_a_preexisting_scratch_hardlink(
    tmp_path: Path, destination: str
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    output = source_dir / "reference.json"
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("Synthetic unrelated file must stay intact.", encoding="utf-8")
    target = output if destination == "payload" else postprocess.provenance_path(output)
    os.link(unrelated, postprocess._part_path(target))
    if destination == "payload":
        postprocess._write_json_atomic(output, {"reference": "synthetic"})
        assert json.loads(output.read_text(encoding="utf-8")) == {"reference": "synthetic"}
    else:
        output.write_text("synthetic reference", encoding="utf-8")
        postprocess._write_provenance(output, {"step": "synthetic"}, 1)
        assert json.loads(target.read_text(encoding="utf-8"))[
            "output_sha256"
        ] == postprocess._sha256(output)
    assert unrelated.read_text(encoding="utf-8") == "Synthetic unrelated file must stay intact."
    assert not list(source_dir.glob("*.tmp"))


def test_atomic_publication_preserves_previous_output_when_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "reference.json"
    output.write_text('{"old":true}', encoding="utf-8")

    def interrupt(*args: Any) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupt)
        with pytest.raises(KeyboardInterrupt):
            postprocess._write_json_atomic(output, {"new": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}
    assert not list(tmp_path.glob("*.tmp"))
    postprocess._write_json_atomic(output, {"new": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"new": True}


def test_ingestion_supports_declared_nested_outputs(
    reference_sources: tuple[Path, dict[str, Any], dict[str, Any]],
) -> None:
    root, _, _ = reference_sources
    source = manifest.load().get("cpic")
    nested = replace(
        source,
        post_process=(replace(source.post_process[0], params={"output": "nested/reference.json"}),),
    )
    result = postprocess.run(nested, root=root)[0]
    assert result.status is ProcessStatus.CREATED, result
    assert sources.load_source(root / "cpic" / "nested" / "reference.json")["kind"] == "pgx_cpic"
    assert postprocess.run(nested, root=root, verify_only=True)[0].status is ProcessStatus.VERIFIED


@pytest.mark.parametrize(
    "escaped,expected",
    [
        (r"\303\251", "\u00e9"),
        (r"\xe2\x82\xac", "\u20ac"),
        ("\u00e9 " + r"\303\261", "\u00e9 \u00f1"),
    ],
)
def test_copy_byte_escapes_decode_multibyte_utf8(escaped: str, expected: str) -> None:
    assert copy_value(escaped) == expected


@pytest.mark.parametrize("escaped", [r"\400", r"\xff", r"\303", r"\xc0\xaf"])
def test_invalid_copy_byte_sequences_are_refused(escaped: str) -> None:
    with pytest.raises(ProcessError):
        copy_value(escaped)


def test_cpic_copy_utf8_byte_escapes_agree_with_literal_insert_text(tmp_path: Path) -> None:
    tables = tables_fixture()
    tables["allele"][0]["functioncomments"] = "Synthetic caf\u00e9 description."
    copy_path = write_sql(tmp_path / "copy.sql.gz", tables)
    with gzip.open(copy_path, "rt", encoding="utf-8") as handle:
        text = handle.read().replace("caf\u00e9", r"caf\303\251")
    with gzip.open(copy_path, "wt", encoding="utf-8") as handle:
        handle.write(text)
    inserts = write_sql(tmp_path / "inserts.sql.gz", tables, inserts=True)
    assert read_dump(copy_path, mode="copy") == read_dump(inserts, mode="inserts") == tables


@pytest.mark.parametrize("tail", ['"unfinished', '"closed"junk'])
def test_malformed_tsv_quoting_is_refused(tmp_path: Path, tail: str) -> None:
    path = archive_fixture(tmp_path / "variants.zip")
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["variants.tsv"] = (
        "\t".join(HEADERS["variants.tsv"])
        + "\n"
        + "\t".join(["PA1000001", "rs1000001", "CYP2C19", "NC_000010.11:201", tail])
        + "\n"
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    with pytest.raises(ProcessError):
        read_archive(path)


@pytest.mark.parametrize(
    "text",
    [
        '{"CYP2C19":{"*1":1,"*1":2}}',
        '{"CYP2C19":{"*1":2},"CYP2C19":{"*2":2}}',
        '{"Normal function":1,"Normal function":2}',
    ],
)
def test_duplicate_lookup_json_keys_cannot_silently_change_allele_counts(text: str) -> None:
    with pytest.raises(ProcessError, match="duplicate key"):
        sources.object_field(text)


@pytest.mark.parametrize(
    "table,column",
    [
        ("allele_definition", "name"),
        ("allele", "name"),
        ("gene_result", "result"),
        ("gene_result_diplotype", "diplotype"),
        ("sequence_location", "chromosomelocation"),
    ],
)
@pytest.mark.parametrize("missing", [None, ""])
def test_source_labels_required_for_interpretation_are_nonempty(
    table: str, column: str, missing: str | None
) -> None:
    tables = tables_fixture()
    tables[table][0][column] = missing
    with pytest.raises(ProcessError, match="source label"):
        sources.validate_tables(tables)


@pytest.mark.parametrize(
    "mutation",
    ["file-set", "cpic-encodings", "aggregate-license", "conflicting-notice", "invalid-date"],
)
def test_frozen_reference_requires_complete_and_consistent_source_metadata(
    tmp_path: Path, frozen: dict[str, Any], mutation: str
) -> None:
    if mutation == "file-set":
        frozen["annotations"]["source"]["files"] = frozen["annotations"]["source"]["files"][:1]
    elif mutation == "cpic-encodings":
        frozen["cpic"]["source"]["files"][0]["filename"] = "wrong-release.sql.gz"
    elif mutation == "aggregate-license":
        frozen["annotations"]["source"]["license_id"] = "CC-BY-SA-4.0"
    elif mutation == "conflicting-notice":
        frozen["annotations"]["archives"][0]["license_notice"] += (
            " https://creativecommons.org/licenses/by-sa/4.0/"
        )
    else:
        frozen["annotations"]["archives"][0]["created"] = "2026-02-30"
    with pytest.raises(ProcessError):
        catalog.Catalog.load(save_catalog(tmp_path / "reference.json", frozen))


@pytest.mark.parametrize("has_card", [True, False], ids=["saved-card", "nonstandard-pack"])
@pytest.mark.parametrize("stage", ["completed", "unavailable", "historical"])
def test_cyp2d6_limitation_stays_beside_saved_calls(
    frozen: dict[str, Any],
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    monkeypatch: pytest.MonkeyPatch,
    has_card: bool,
    stage: str,
) -> None:
    """Filters, missing references and older formats cannot silently omit the gap."""
    from html import unescape

    from fastapi.testclient import TestClient

    from genetics.ancestry.context import AncestryContext
    from genetics.engine.cards import KnowledgePack, default_knowledge_dir
    from genetics.engine.evidence import assemble_card
    from genetics.engine.matcher import MatchResult, MatchStatus
    from genetics.pgx.presentation import CYP2D6_CARD_ID, saved_report, section_framing
    from genetics.run.bundle import PGX_NAME, read_bundle, write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    cards: tuple[AssembledCard, ...] = ()
    if has_card:
        authored = KnowledgePack.load(default_knowledge_dir()).by_id(CYP2D6_CARD_ID)
        assert authored is not None
        authored = replace(
            authored,
            title="Saved CYP2D6 assay limitation",
            summary="Not callable: saved CYP2D6 copy-number limit.",
        )
        cards = (
            assemble_card(
                authored,
                MatchResult(
                    card_id=authored.id,
                    status=MatchStatus.NOT_DETERMINABLE,
                    reason="Synthetic assay-limit acceptance.",
                ),
            ),
        )
    if stage == "completed":
        # More than one page: every source allele remains a conditional alternative.
        tables = frozen["cpic"]["tables"]
        for number in range(3, 17):
            tables["allele_definition"].append(
                {**tables["allele_definition"][1], "id": str(number + 100), "name": f"*{number}"}
            )
            tables["allele_location_value"].append(
                {**tables["allele_location_value"][1], "alleledefinitionid": str(number + 100)}
            )
    reference = refresh_call_reference(frozen)
    # Prepared catalogs are read from canonical JSON, as in the production stage.
    reference = catalog.Catalog(json.loads(json.dumps(reference.record, sort_keys=True)))
    calls = (
        calling.call(reference, sample_table([]), sex=sample_qc.sex.inferred)
        if stage == "completed"
        else calling.unavailable("Synthetic absent reference.", sex=sample_qc.sex.inferred.value)
    )
    root = tmp_path / "runs"
    path = write_bundle(
        qc=sample_qc,
        cards=cards,
        pack=sample_pack,
        ancestry=AncestryContext.not_run("Synthetic CYP2D6 placement acceptance"),
        pgx=calls.to_dict(),
        runs_root=root,
        run_id="cyp2d6-placement",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    if stage == "historical":
        header_path = path / "manifest.json"
        header = json.loads(header_path.read_text())
        header["format_version"] = 18
        header["files"].pop(PGX_NAME)
        (path / PGX_NAME).unlink()
        header_path.write_text(json.dumps(header), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
    bundle = read_bundle(path)
    expected = saved_report(bundle)
    framing = section_framing()
    assert framing["context"] == "current"
    assert framing["section"] == "pharmacogenomics"
    assert "not a prescribing tool" in framing["text"]
    assert "clinical phenotype" in framing["text"]
    assert "medicine or dose" in framing["text"]
    assert "Prescribing based on these findings" in framing["text"]
    assert "clinical confirmation" in framing["text"]
    assert "full clinical context" in framing["text"]
    assert expected["current_context"] == {"section_framing": framing}
    limitation = expected["cyp2d6_limitation"]
    assert limitation["status"] == ("recorded" if has_card else "not-recorded")
    if has_card:
        assert limitation["card"]["summary"] == cards[0].summary
        assert limitation["card"]["detail"] == cards[0].detail
        assert "star-5 with star-29" in limitation["card"]["detail"]
        from genetics.pgx.presentation import cyp2d6_limitation

        for changed in (
            replace(bundle.cards[0], kind="interpretation"),
            replace(bundle.cards[0], status="marker_absent"),
        ):
            assert cyp2d6_limitation([changed])["status"] == "not-recorded"
    else:
        assert limitation["card"] is None
        assert "not recorded by this run" in limitation["reason"]
    assert "CYP2D6" not in expected["genes"]
    assert set(expected["genes"]) == (set() if stage == "historical" else set(catalog.TRACTABLE))
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    for gene in (None, "CYP2C19"):
        args = ["pgx", "calls", path.name] + ([] if gene is None else ["--gene", gene])
        result = CliRunner().invoke(app, [*args, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == saved_report(bundle, gene)
        text = CliRunner().invoke(app, args)
        assert text.exit_code == 0
        assert text.output.count(framing["text"]) == 1
        assert text.output.index(framing["text"]) < text.output.index("PGx:")
        assert json.loads(result.output)["current_context"] == {"section_framing": framing}
        assert (cards[0].summary if has_card else limitation["reason"]) in text.output
    client = TestClient(create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1")
    urls = [
        "",
        "?group=tier",
        "?tier=strong",
        "?interpreted=1",
        "?section=traits",
        "?group=tier&tier=strong&section=traits",
        "?group=tier&tier=strong&section=traits&interpreted=1",
        "/pgx",
        *[f"/pgx?gene={gene}&page=999" for gene in catalog.TRACTABLE],
    ]
    for suffix in urls:
        response = client.get(f"/runs/{path.name}{suffix}")
        assert response.status_code == 200
        html = unescape(response.text)
        assert html.count(framing["text"]) == 1
        assert html.index(framing["text"]) < html.index('aria-label="CYP2D6 assay limitation"')
        assert f'aria-label="{framing["title"]}"' in html
        assert 'class="notice notice-ignored"' not in html
        if has_card and any(p in suffix for p in ("tier=", "section=", "interpreted=")):
            assert "1 of 1 card(s) are hidden" in html
            assert 'class="cardlink"' not in html
        block = html.split('<aside class="notice" aria-label="CYP2D6 assay limitation">')[1]
        block = block.split("</aside>")[0]
        assert (cards[0].summary if has_card else limitation["reason"]) in block
        assert "regardless of knowledge-card filters" in block
        if has_card:
            assert f"/runs/{path.name}/cards/{CYP2D6_CARD_ID}" in block
            reason = cards[0].card.impossibility_reason
            assert reason is not None and reason in block
        if "/pgx?" not in suffix and stage != "historical":
            for gene in catalog.TRACTABLE:
                assert f"/pgx?gene={gene}" in html
        if suffix.startswith("/pgx?gene=") and stage == "completed":
            gene = suffix.split("gene=")[1].split("&")[0]
            total = len(expected["genes"][gene]["candidates"])
            assert f"All {total} candidates remain available" in html
    if stage == "completed":
        import re

        total = len(expected["genes"]["CYP2C19"]["candidates"])
        assert total > 100
        rows = []
        for page in (1, 2):
            html = client.get(f"/runs/{path.name}/pgx?gene=CYP2C19&page={page}").text
            table = html.split("<th>Source alleles</th>")[1]
            rows.extend(re.findall(r"<tr>\s*<td>([^<]+)</td>", table))
            assert "CYP2D6 assay limitation" in html
            assert unescape(html).count(framing["text"]) == 1
        assert len(rows) == total
        assert set(rows) == {
            " / ".join(c["alleles"]) for c in expected["genes"]["CYP2C19"]["candidates"]
        }
    if has_card:
        detail = client.get(f"/runs/{path.name}/cards/{CYP2D6_CARD_ID}")
        assert detail.status_code == 200 and "star-5 with star-29" in detail.text
        assert framing["text"] not in unescape(detail.text)
    assert all(framing["text"].encode() not in content for content in before.values())
    assert {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()} == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("impossibility_reason", None),
        ("impossibility_reason", " "),
        ("summary", " "),
        ("detail", " "),
        ("title", " "),
    ],
)
def test_incomplete_saved_cyp2d6_text_is_not_reported_as_recorded(
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str | None,
) -> None:
    """Older/nonstandard snapshots may lack text; do not claim complete evidence."""
    import hashlib

    from fastapi.testclient import TestClient

    from genetics.ancestry.context import AncestryContext
    from genetics.engine.cards import KnowledgePack, default_knowledge_dir
    from genetics.engine.evidence import assemble_card
    from genetics.engine.matcher import MatchResult, MatchStatus
    from genetics.pgx.presentation import CYP2D6_CARD_ID, saved_report
    from genetics.run.bundle import CARDS_NAME, read_bundle, write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    authored = KnowledgePack.load(default_knowledge_dir()).by_id(CYP2D6_CARD_ID)
    assert authored is not None
    card = assemble_card(
        authored,
        MatchResult(
            card_id=authored.id, status=MatchStatus.NOT_DETERMINABLE, reason="Assay limit."
        ),
    )
    root = tmp_path / "runs"
    path = write_bundle(
        qc=sample_qc,
        cards=(card,),
        pack=sample_pack,
        ancestry=AncestryContext.not_run("Synthetic incomplete-text review"),
        pgx=calling.unavailable(
            "Synthetic absent reference.", sex=sample_qc.sex.inferred.value
        ).to_dict(),
        runs_root=root,
        run_id="incomplete-cyp2d6",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    cards_path = path / CARDS_NAME
    raw = json.loads(cards_path.read_text())
    raw["cards"][0][field] = value
    cards_path.write_text(json.dumps(raw), encoding="utf-8")
    header_path = path / "manifest.json"
    header = json.loads(header_path.read_text())
    header["files"][CARDS_NAME] = hashlib.sha256(cards_path.read_bytes()).hexdigest()
    header_path.write_text(json.dumps(header), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
    bundle = read_bundle(path)
    limitation = saved_report(bundle)["cyp2d6_limitation"]
    assert limitation["status"] == "not-recorded"
    assert limitation["card"] is None
    assert "Complete CYP2D6 assay-limitation evidence was not recorded" in limitation["reason"]
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["pgx", "calls", path.name, "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["cyp2d6_limitation"] == limitation
    client = TestClient(create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1")
    for suffix in ("", "?group=tier&tier=strong", "/pgx", "/pgx?gene=CYP2C19"):
        response = client.get(f"/runs/{path.name}{suffix}")
        assert response.status_code == 200 and limitation["reason"] in response.text
        assert "Read the saved CYP2D6 limitation" not in response.text
    assert {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()} == before


# M10.4: synthetic source joins, separately from public-source identity acceptance.
def guideline_source(record: dict[str, Any], gene: str = "CYP2C19") -> None:
    gene_reference(record, gene, chrom="X" if gene == "G6PD" else "10")
    tables = record["cpic"]["tables"]
    tables["pair"] = [
        {
            **dict.fromkeys(REQUIRED["pair"]),
            "pairid": "20",
            "genesymbol": gene,
            "drugid": "Synthetic:drug",
            "guidelineid": "21",
            "cpiclevel": "A",
        }
    ]
    tables["guideline"] = [
        {
            **dict.fromkeys(REQUIRED["guideline"]),
            "id": "21",
            "name": "Synthetic guideline",
            "url": "https://example.test/guideline",
            "genes": "{" + gene + "}",
            "version": "1",
        }
    ]
    tables["drug"] = [{"drugid": "Synthetic:drug", "name": "Synthetic drug", "version": "1"}]
    tables["publication"] = [
        {
            **dict.fromkeys(REQUIRED["publication"]),
            "id": "22",
            "guidelineid": "21",
            "pmid": "10000001",
            "version": "1",
            "title": "Synthetic guideline publication",
        }
    ]
    tables["recommendation"] = [
        {
            **dict.fromkeys(REQUIRED["recommendation"]),
            "id": "23",
            "guidelineid": "21",
            "drugid": "Synthetic:drug",
            "classification": "Moderate",
            "version": "1",
            "lookupkey": json.dumps({gene: "Intermediate Metabolizer"}),
            "phenotypes": json.dumps({gene: "Intermediate Metabolizer"}),
            "drugrecommendation": "Synthetic conditional implication",
            "population": "synthetic context only",
            "comments": "Extra clinical condition",
        }
    ]


def guideline_card(gene: str = "CYP2C19") -> Any:
    from genetics.engine.cards import Card

    return Card.parse(
        {
            "id": gene.lower() + "_guidelines",
            "section": "pharmacogenomics",
            "kind": "guideline",
            "title": "Synthetic guideline card",
            "gene": gene,
            "citations": [
                {"type": "pmid", "id": "10000001", "title": "Synthetic guideline publication"}
            ],
        },
        "synthetic",
    )


def test_guideline_exact_candidate_mapping_and_evidence_fields(frozen: dict[str, Any]) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen)
    calls = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    result = derive(calls, "CYP2C19")
    branch = result["branches"][0]
    assert branch["candidate"]["definition_ids"] == ["1", "2"]
    assert branch["allele_counts"] == {"*1": 1, "*2": 1}
    assert branch["joins"][0]["mapping"]["id"] == "8"
    assert branch["joins"][0]["lookup"]["id"] == "7"
    assert branch["joins"][0]["result"]["id"] == "6"
    row = result["recommendations"][0]
    assert row["pairs"][0]["cpiclevel"] == "A"
    assert row["source_row"]["classification"] == "Moderate"
    assert branch["functions"]["1"][0]["strength"] == "strong"
    assert row["source_row"]["population"] == "synthetic context only"
    assert row["source_row"]["comments"] == "Extra clinical condition"
    assert row["conditions"][0]["support"] == [{"candidate_index": 0, "mapping_ids": ["8"]}]
    assert row["publications"][0]["pmid"] == "10000001"
    assert row["status"] == "conditional"


@pytest.mark.parametrize(
    "missing",
    [
        "mapping",
        "lookup",
        "phenotype",
        "recommendation",
        "publication",
        "guideline",
        "drug",
        "url",
        "null-guideline",
    ],
)
def test_guideline_gaps_never_establish_an_implication(
    frozen: dict[str, Any], missing: str
) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen)
    tables = frozen["cpic"]["tables"]
    if missing in {"mapping", "lookup", "phenotype"}:
        tables["gene_result_diplotype"] = []
        if missing in {"lookup", "phenotype"}:
            tables["gene_result_lookup"] = []
        if missing == "phenotype":
            tables["gene_result"] = []
    elif missing in {"recommendation", "publication", "guideline", "drug"}:
        tables[missing] = []
    elif missing == "url":
        tables["guideline"][0]["url"] = None
    else:
        tables["pair"][0]["guidelineid"] = None
        tables["publication"][0]["guidelineid"] = None
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    result = derive(raw, "CYP2C19")
    if missing in {"mapping", "lookup", "phenotype"}:
        assert result["unmapped_candidates"] == [0]
        assert result["recommendations"][0]["conditions"][0]["state"] == "unassessed"
    elif missing in {"publication", "guideline", "url"}:
        assert result["recommendations"][0]["status"] == "evidence-missing"
    elif missing == "drug":
        assert result["recommendations"][0]["drug"] is None
        assert result["recommendations"][0]["gaps"]
    else:
        assert not result["recommendations"] and result["gaps"]
        assert not result["publications"] if missing == "null-guideline" else True


@pytest.mark.parametrize("gene", ["DPYD", "CYP2C9"])
@pytest.mark.parametrize("activity", ["1", "1.0", "0.5+0.5"])
def test_guideline_activity_uses_exact_source_total(
    frozen: dict[str, Any], gene: str, activity: str
) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen, gene)
    tables = frozen["cpic"]["tables"]
    tables["gene"][0]["lookupmethod"] = "ACTIVITY_SCORE"
    tables["gene_result_lookup"][0]["totalactivityscore"] = activity
    tables["recommendation"][0]["lookupkey"] = json.dumps({gene: "1.0"})
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    result = derive(raw, gene)
    assert result["recommendations"]
    assert result["recommendations"][0]["conditions"][0]["state"] == (
        "unassessed" if activity == "0.5+0.5" else "candidate-compatible"
    )
    assert result["branches"][0]["joins"][0]["lookup"]["totalactivityscore"] == activity


@pytest.mark.parametrize("required", ["CYP2D6", "NUDT15"])
def test_guideline_multigene_condition_is_never_inferred(
    frozen: dict[str, Any], required: str
) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen)
    tables = frozen["cpic"]["tables"]
    tables["recommendation"][0]["lookupkey"] = json.dumps(
        {"CYP2C19": "Intermediate Metabolizer", required: "Normal Metabolizer"}
    )
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    row = derive(raw, "CYP2C19")["recommendations"][0]
    assert row["status"] == "conditional"
    condition = next(c for c in row["conditions"] if c["gene"] == required)
    assert condition["state"] == "unassessed" and not condition["support"]
    assert row["gaps"]


@pytest.mark.parametrize("sex", list(InferredSex))
def test_guideline_g6pd_retains_copy_models(frozen: dict[str, Any], sex: InferredSex) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen, "G6PD")
    tables = frozen["cpic"]["tables"]
    tables["gene_result"][0]["result"] = "Variable"
    tables["recommendation"][0]["lookupkey"] = '{"G6PD":"Variable"}'
    raw = calling.call(refresh_call_reference(frozen), sample_table([], chrom="X"), sex=sex).record
    result = derive(raw, "G6PD")
    assert {b["candidate"]["ploidy"] for b in result["branches"]} == (
        {2} if sex == InferredSex.FEMALE else {1} if sex == InferredSex.MALE else {1, 2}
    )
    assert all(b["candidate"]["support"] == "conditional" for b in result["branches"])
    assert all(r["status"] == "conditional" for r in result["recommendations"])


def test_guideline_phase_and_unmapped_alternatives_retained(frozen: dict[str, Any]) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen)
    add_second_locus(frozen)
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called"), (102, "C", "T", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    result = derive(raw, "CYP2C19")
    assert len(result["branches"]) == len(raw["genes"]["CYP2C19"]["candidates"])
    assert len(result["branches"]) > 1
    assert result["unmapped_candidates"]
    assert result["recommendations"]


@pytest.mark.parametrize("mutation", ["drug", "guideline", "phenotype"])
def test_guideline_exact_recommendation_binding(frozen: dict[str, Any], mutation: str) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen)
    row = frozen["cpic"]["tables"]["recommendation"][0]
    if mutation == "phenotype":
        row["lookupkey"] = '{"CYP2C19":"Poor Metabolizer"}'
    else:
        row[mutation + "id"] = "unrelated"
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    assert not derive(raw, "CYP2C19")["recommendations"]


@pytest.mark.parametrize("imputed", [False, True])
def test_guideline_rarity_and_quality_survive(frozen: dict[str, Any], imputed: bool) -> None:
    from genetics.pgx.guidelines import assemble_guideline_card

    guideline_source(frozen)
    from genetics.health.frequencies import parse_record

    public = parse_record(
        "\t".join(["10", "101", ".", "A", "G", ".", "PASS", "AF=0.000001;AC=1;AN=1000000"])
    )
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([]) if imputed else sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
        dosages=[imputed_marker()] if imputed else [],
        frequencies={("10", 101): [public]},
    ).to_dict()
    card = assemble_guideline_card(guideline_card(), raw)
    assert (
        card.computation is not None
        and card.computation["reliability"]["tier"] == "likely-artifact"
    )
    assert (
        "~16%" in card.summary
        and "not a personal posterior or an imputation validation" in card.summary
    )
    if imputed:
        assert "DR2" in card.summary


@pytest.mark.parametrize("display_schema", [1, 2])
@pytest.mark.parametrize("stage", ["completed", "unavailable"])
def test_guideline_saved_cli_dashboard_and_corruption(
    frozen: dict[str, Any],
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    display_schema: int,
) -> None:
    from html import unescape

    from fastapi.testclient import TestClient

    from genetics.ancestry.context import AncestryContext
    from genetics.pgx.guidelines import assemble_guideline_card
    from genetics.pgx.presentation import section_framing
    from genetics.run.bundle import BundleError, _card_payload, read_bundle, write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    framing = section_framing()
    guideline_source(frozen)
    calls = (
        calling.call(
            refresh_call_reference(frozen),
            sample_table([(101, "A", "G", "called")]),
            sex=sample_qc.sex.inferred,
        )
        if stage == "completed"
        else calling.unavailable("Synthetic absent reference", sex=sample_qc.sex.inferred.value)
    )
    card = assemble_guideline_card(
        guideline_card(), calls.record, display_schema_version=display_schema
    )
    pack = replace(sample_pack, cards=(*sample_pack.cards, card.card))
    path = write_bundle(
        qc=sample_qc,
        cards=(*sample_cards, card),
        pack=pack,
        ancestry=AncestryContext.not_run("Synthetic guideline acceptance"),
        pgx=calls.to_dict(),
        runs_root=tmp_path / "runs",
        run_id="guidelines",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        catalog.Catalog,
        "default",
        classmethod(lambda cls: pytest.fail("Current reference must not be read")),
    )
    loaded = read_bundle(path)
    saved = loaded.cards[-1]
    assert saved.computation is not None
    assert saved.computation["result"]["schema_version"] == display_schema
    assert saved.summary == card.summary and saved.computation == card.computation
    for gene_args in ([], ["--gene", "CYP2C19"]):
        args = ["pgx", "calls", path.name, *gene_args]
        cli = CliRunner().invoke(app, [*args, "--json"])
        assert cli.exit_code == 0, cli.output
        assert json.loads(cli.output)["current_context"] == {"section_framing": framing}
        assert json.loads(cli.output)["guideline_cards"] == [
            {
                "card_id": saved.card_id,
                "summary": saved.summary,
                "computation": saved.computation,
                "citations": list(saved.citations),
            }
        ]
        text = CliRunner().invoke(app, args)
        assert text.exit_code == 0, text.output
        assert text.output.count(framing["text"]) == 1
        assert saved.summary in text.output
    detail = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert detail.exit_code == 0, detail.output
    assert "current_context" not in json.loads(detail.output)
    assert json.loads(detail.output)["cards"][-1]["computation"] == card.computation
    client = TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1"
    )
    for suffix in ("", "/pgx", "/pgx?gene=CYP2C19", "/cards/" + card.card_id):
        page = client.get(f"/runs/{path.name}" + suffix)
        assert page.status_code == 200
        assert card.summary in page.text
        assert unescape(page.text).count(framing["text"]) == (
            0 if suffix.startswith("/cards/") else 1
        )
        if suffix.startswith("/cards/") and stage == "completed":
            assert "Synthetic conditional implication" in page.text
            assert "recommendation classification Moderate" in page.text
            assert "CPIC gene-drug level A" in page.text
            assert "10000001" in page.text
            assert "synthetic context only" in page.text
    before = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
    read_bundle(path)
    assert before == {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
    from genetics.pgx.guidelines import validate_stored

    for field in ("summary", "detail", "computation", "citations"):
        entry = deepcopy(_card_payload(card))
        if field == "computation":
            entry[field]["result"]["gene"] = "CYP2D6"
        elif field == "citations":
            entry[field][0]["id"] = "10000002"
        else:
            entry[field] = "Changed evidence"
        if stage == "unavailable" and field == "citations":
            continue  # No source exists to bind authored citations for unavailable runs.
        with pytest.raises(ValueError):
            validate_stored(entry, calls.record)
    from genetics.run.bundle import CARDS_NAME

    cards_path = path / CARDS_NAME
    payload = json.loads(cards_path.read_text())
    entries = payload if isinstance(payload, list) else payload["cards"]
    entries[-1]["summary"] = "Tampered implication"
    cards_path.write_text(json.dumps(payload), encoding="utf-8")
    header_path = path / "manifest.json"
    header = json.loads(header_path.read_text())
    import hashlib

    header["files"][CARDS_NAME] = hashlib.sha256(cards_path.read_bytes()).hexdigest()
    header_path.write_text(json.dumps(header), encoding="utf-8")
    with pytest.raises(BundleError):
        read_bundle(path)


def test_guideline_pipeline_and_schema(frozen: dict[str, Any], tmp_path: Path) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.engine.cards import CardError
    from genetics.run.pipeline import analyse

    guideline_source(frozen)
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    declaration = {
        "id": "cyp2c19_guidelines",
        "section": "pharmacogenomics",
        "kind": "guideline",
        "title": "Synthetic guideline card",
        "gene": "CYP2C19",
        "citations": [{"type": "pmid", "id": "10000001", "title": "Synthetic"}],
    }
    (knowledge / "cards.yaml").write_text(json.dumps({"schema_version": 5, "cards": [declaration]}))
    result = analyse(
        Path(__file__).parents[1] / "fixtures/synthetic/ancestry_v2_female.txt",
        knowledge_dir=knowledge,
        no_impute=True,
        ancestry=lambda _table, _qc: AncestryContext.not_run("Synthetic"),
        pgx=calling.CallingStage(refresh_call_reference(frozen)),
    )
    assert result.cards[0].computation is not None
    assert result.cards[0].computation["source"] == "pgx_guideline"
    assert result.matches[0] == result.cards[0].match
    assert result.cards[0].imputation_mode == "disabled"
    data: dict[str, Any] = {
        "id": "bad",
        "section": "pharmacogenomics",
        "kind": "guideline",
        "title": "Bad",
        "gene": "CYP2D6",
        "citations": [{"type": "pmid", "id": "10000001", "title": "Synthetic"}],
    }
    from genetics.engine.cards import Card

    with pytest.raises(CardError):
        Card.parse(data, "synthetic")
    data["gene"] = "DPYD"
    data["evidence"] = {}
    with pytest.raises(CardError):
        Card.parse(data, "synthetic")


def test_guideline_conflicting_lookup_rows_keep_every_implication(frozen: dict[str, Any]) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen)
    tables = frozen["cpic"]["tables"]
    tables["gene_result"].append(
        {**tables["gene_result"][0], "id": "30", "result": "Poor Metabolizer"}
    )
    tables["gene_result_lookup"].append(
        {**tables["gene_result_lookup"][0], "id": "31", "phenotypeid": "30"}
    )
    tables["gene_result_diplotype"].append(
        {**tables["gene_result_diplotype"][0], "id": "32", "functionphenotypeid": "31"}
    )
    tables["recommendation"].append(
        {
            **tables["recommendation"][0],
            "id": "33",
            "classification": "Strong",
            "lookupkey": '{"CYP2C19":"Poor Metabolizer"}',
            "drugrecommendation": "Conflicting synthetic alternative",
        }
    )
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    result = derive(raw, "CYP2C19")
    assert result["branches"][0]["candidate"]["mapping_status"] == "conflicting-mappings"
    assert {r["source_row"]["id"] for r in result["recommendations"]} == {"23", "33"}
    assert {j["lookup"]["id"] for j in result["branches"][0]["joins"]} == {"7", "31"}


@pytest.mark.parametrize("match", [False, True])
def test_guideline_multigene_binds_both_called_genes(frozen: dict[str, Any], match: bool) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen, "TPMT")
    tables = frozen["cpic"]["tables"]
    for name in (
        "gene",
        "allele_definition",
        "sequence_location",
        "allele_location_value",
        "allele",
        "gene_result",
        "gene_result_lookup",
        "gene_result_diplotype",
    ):
        for original in list(tables[name]):
            row = deepcopy(original)
            for field in (
                "id",
                "definitionid",
                "alleledefinitionid",
                "locationid",
                "phenotypeid",
                "functionphenotypeid",
            ):
                if row.get(field) is not None:
                    row[field] = str(int(row[field]) + 100)
            if name == "gene":
                row["symbol"] = "NUDT15"
            if "genesymbol" in row:
                row["genesymbol"] = "NUDT15"
            if name == "gene_result_diplotype":
                row["diplotypekey"] = '{"NUDT15":{"*1":1,"*2":1}}'
            tables[name].append(row)
    tables["recommendation"][0]["lookupkey"] = json.dumps(
        {
            "TPMT": "Intermediate Metabolizer",
            "NUDT15": "Intermediate Metabolizer" if match else "Poor Metabolizer",
        }
    )
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    result = derive(raw, "TPMT")
    assert bool(result["recommendations"]) == match
    if match:
        conditions = result["recommendations"][0]["conditions"]
        assert {c["gene"] for c in conditions} == {"TPMT", "NUDT15"}
        assert all(c["state"] == "candidate-compatible" and c["support"] for c in conditions)
        assert result["required_gene_branches"]["NUDT15"][0]["candidate"]["definition_ids"] == [
            "101",
            "102",
        ]


def test_guideline_drug_specific_functions_remain_source_annotations(
    frozen: dict[str, Any],
) -> None:
    from genetics.pgx.guidelines import derive

    guideline_source(frozen)
    tables = frozen["cpic"]["tables"]
    tables["allele"][0].update(
        clinicalfunctionalstatus="Drug-specific synthetic function",
        clinicalfunctionalsubstrate="Synthetic:other-drug",
    )
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    result = derive(raw, "CYP2C19")
    functions = result["branches"][0]["functions"]["1"]
    assert functions[0]["functionalstatus"] == "Normal function"
    assert functions[0]["clinicalfunctionalstatus"] == "Drug-specific synthetic function"
    assert functions[0]["clinicalfunctionalsubstrate"] == "Synthetic:other-drug"
    assert (
        result["recommendations"][0]["conditions"][0]["required_value"]
        == "Intermediate Metabolizer"
    )


def test_guideline_vkorc1_source_gap_and_historical_cards(frozen: dict[str, Any]) -> None:
    from genetics.engine.cards import CardError, parse_file
    from genetics.pgx.guidelines import assemble_guideline_card, derive
    from genetics.run.bundle import BundleError, _card_payload, _check_guidelines

    guideline_source(frozen, "VKORC1")
    tables = frozen["cpic"]["tables"]
    for name in ("gene_result_diplotype", "gene_result_lookup", "gene_result", "recommendation"):
        tables[name] = []
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    result = derive(raw, "VKORC1")
    assert result["pairs"][0]["cpiclevel"] == "A"
    assert not result["recommendations"] and result["unmapped_candidates"]
    assert any("phenotype lookup table not provided" in gap for gap in result["gaps"])
    assembled = assemble_guideline_card(guideline_card("VKORC1"), raw)
    with pytest.raises(BundleError, match="format 20"):
        _check_guidelines([_card_payload(assembled)], raw, 19)
    _check_guidelines([], raw, 19)
    entry = {
        "id": "test",
        "kind": "guideline",
        "title": "test",
        "section": "pharmacogenomics",
        "gene": "DPYD",
        "citations": [{"type": "pmid", "id": "10000001", "title": "Synthetic"}],
    }
    with pytest.raises(CardError, match="schema_version 5"):
        parse_file(json.dumps({"schema_version": 4, "cards": [entry]}), "synthetic")


def test_guideline_authored_selectors_and_public_citations() -> None:
    from genetics.engine.cards import CardKind, KnowledgePack

    cards = [c for c in KnowledgePack.load().cards if c.kind is CardKind.GUIDELINE]
    expected = {
        "CYP2C19": "35034351",
        "CYP2C9": "32189324",
        "VKORC1": "28198005",
        "SLCO1B1": "35152405",
        "TPMT": "30447069",
        "DPYD": "29152729",
        "NUDT15": "30447069",
        "G6PD": "36049896",
    }
    assert {c.gene for c in cards} == set(expected)
    assert all(c.evidence is None and c.match is None for c in cards)
    for card in cards:
        assert card.citations[0].id == expected[card.gene or ""]
        assert card.id == (card.gene or "").lower() + "_guidelines"


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("kind", ["guideline", "GUIDELINE", " guideline "])
def test_guideline_version_gate_cannot_be_bypassed(version: int, kind: str) -> None:
    from genetics.engine.cards import CardError, parse_file

    entry = {
        "id": "test",
        "kind": kind,
        "title": "test",
        "section": "pharmacogenomics",
        "gene": "DPYD",
        "citations": [{"type": "pmid", "id": "10000001", "title": "Synthetic"}],
    }
    with pytest.raises(CardError, match="schema_version 5"):
        parse_file(json.dumps({"schema_version": version, "cards": [entry]}), "synthetic")


@pytest.mark.parametrize(
    "mutation", ["schema_boolean", "index_boolean", "copy_boolean", "ploidy_float"]
)
@pytest.mark.parametrize("version", [1, 2])
def test_m104_review_saved_numeric_types_are_exact(
    frozen: dict[str, Any], mutation: str, version: int
) -> None:
    from genetics.pgx.guidelines import assemble_guideline_card, validate_stored
    from genetics.run.bundle import _card_payload

    guideline_source(frozen)
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    entry = deepcopy(
        _card_payload(
            assemble_guideline_card(guideline_card(), raw, display_schema_version=version)
        )
    )
    result = entry["computation"]["result"]
    if mutation == "schema_boolean":
        result["schema_version"] = True
    elif mutation == "index_boolean":
        result["branches"][0]["candidate_index"] = False
    elif mutation == "copy_boolean":
        result["branches"][0]["allele_counts"]["*1"] = True
    else:
        result["branches"][0]["candidate"]["ploidy"] = 2.0
    with pytest.raises(ValueError):
        validate_stored(entry, raw)


@pytest.mark.parametrize(
    "missing",
    [
        "publication_title",
        "publication_identifier",
        "blank_url",
        "invalid_url",
        "recommendation_text",
    ],
)
def test_m104_review_incomplete_evidence_is_explicit(frozen: dict[str, Any], missing: str) -> None:
    from genetics.pgx.guidelines import assemble_guideline_card

    guideline_source(frozen)
    tables = frozen["cpic"]["tables"]
    if missing == "publication_title":
        tables["publication"][0]["title"] = None
    elif missing == "publication_identifier":
        tables["publication"][0]["pmid"] = "not-a-pmid"
    elif missing == "blank_url":
        tables["guideline"][0]["url"] = " "
    elif missing == "invalid_url":
        tables["guideline"][0]["url"] = "not-a-guideline-url"
    else:
        tables["recommendation"][0]["drugrecommendation"] = None
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    card = assemble_guideline_card(guideline_card(), raw)
    assert card.computation is not None
    row = card.computation["result"]["recommendations"][0]
    assert row["status"] == "evidence-missing"
    assert row["gaps"]
    assert "0 conditional CPIC" in card.summary
    assert "Source rows lacking usable evidence: 1" in card.summary


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("stage", ["completed", "unavailable"])
def test_m104_review_both_display_schemas_roundtrip(
    frozen: dict[str, Any],
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
    tmp_path: Path,
    version: int,
    stage: str,
) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.pgx.guidelines import assemble_guideline_card
    from genetics.run.bundle import read_bundle, write_bundle

    guideline_source(frozen)
    raw = (
        calling.call(
            refresh_call_reference(frozen),
            sample_table([(101, "A", "G", "called")]),
            sex=sample_qc.sex.inferred,
        ).record
        if stage == "completed"
        else calling.unavailable(
            "Synthetic missing reference", sex=sample_qc.sex.inferred.value
        ).record
    )
    card = assemble_guideline_card(guideline_card(), raw, display_schema_version=version)
    path = write_bundle(
        qc=sample_qc,
        cards=(*sample_cards, card),
        pack=replace(sample_pack, cards=(*sample_pack.cards, card.card)),
        ancestry=AncestryContext.not_run("Synthetic compatibility"),
        pgx=raw,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "missing.lock",
        tools_root=tmp_path / "tools",
    )
    before = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
    saved = read_bundle(path).cards[-1]
    assert saved.computation == card.computation and saved.summary == card.summary
    assert saved.computation is not None
    assert type(saved.computation["result"]["schema_version"]) is int
    assert saved.computation["result"]["schema_version"] == version
    assert before == {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}


@pytest.mark.parametrize("invalid", ["pmid", "doi"])
def test_m104_review_one_bad_identifier_keeps_valid_citation(
    frozen: dict[str, Any], invalid: str
) -> None:
    from genetics.pgx.guidelines import assemble_guideline_card

    guideline_source(frozen)
    row = frozen["cpic"]["tables"]["publication"][0]
    row.update(doi="10.1000/synthetic", pmid="10000001")
    row[invalid] = "invalid-identifier"
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=InferredSex.FEMALE,
    ).record
    card = assemble_guideline_card(guideline_card(), raw)
    assert card.computation is not None
    recommendation = card.computation["result"]["recommendations"][0]
    assert recommendation["status"] == "conditional"
    assert recommendation["gaps"]
    assert len(card.citations) == 1 and card.citations[0].type.value != invalid
    assert recommendation["publications"][0][invalid] == "invalid-identifier"


@pytest.mark.parametrize("version", [1, 2])
def test_m104_review_reader_rejects_numeric_substitution(
    frozen: dict[str, Any],
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
    tmp_path: Path,
    version: int,
) -> None:
    import hashlib

    from genetics.ancestry.context import AncestryContext
    from genetics.pgx.guidelines import assemble_guideline_card
    from genetics.run.bundle import CARDS_NAME, BundleError, read_bundle, write_bundle

    guideline_source(frozen)
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=sample_qc.sex.inferred,
    ).record
    card = assemble_guideline_card(guideline_card(), raw, display_schema_version=version)
    path = write_bundle(
        qc=sample_qc,
        cards=(*sample_cards, card),
        pack=replace(sample_pack, cards=(*sample_pack.cards, card.card)),
        ancestry=AncestryContext.not_run("Synthetic numeric substitution"),
        pgx=raw,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "missing.lock",
        tools_root=tmp_path / "tools",
    )
    card_path = path / CARDS_NAME
    payload = json.loads(card_path.read_text(encoding="utf8"))
    payload["cards"][-1]["computation"]["result"]["branches"][0]["candidate_index"] = False
    card_path.write_text(json.dumps(payload), encoding="utf8")
    header = json.loads((path / "manifest.json").read_text(encoding="utf8"))
    header["files"][CARDS_NAME] = hashlib.sha256(card_path.read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(header), encoding="utf8")
    with pytest.raises(BundleError, match="guideline card disagrees"):
        read_bundle(path)


@pytest.mark.parametrize("missing", ["title", "identifier", "url", "text"])
def test_m104_review_incomplete_evidence_saved_interfaces(
    frozen: dict[str, Any],
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    from fastapi.testclient import TestClient

    from genetics.ancestry.context import AncestryContext
    from genetics.pgx.guidelines import assemble_guideline_card
    from genetics.run.bundle import read_bundle, write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    guideline_source(frozen)
    tables = frozen["cpic"]["tables"]
    if missing == "title":
        tables["publication"][0]["title"] = None
    elif missing == "identifier":
        tables["publication"][0]["pmid"] = "invalid-identifier"
    elif missing == "url":
        tables["guideline"][0]["url"] = " "
    else:
        tables["recommendation"][0]["drugrecommendation"] = " "
    raw = calling.call(
        refresh_call_reference(frozen),
        sample_table([(101, "A", "G", "called")]),
        sex=sample_qc.sex.inferred,
    ).record
    card = assemble_guideline_card(guideline_card(), raw)
    path = write_bundle(
        qc=sample_qc,
        cards=(*sample_cards, card),
        pack=replace(sample_pack, cards=(*sample_pack.cards, card.card)),
        ancestry=AncestryContext.not_run("Synthetic incomplete evidence"),
        pgx=raw,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "missing.lock",
        tools_root=tmp_path / "tools",
    )
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        catalog.Catalog,
        "default",
        classmethod(lambda cls: pytest.fail("Current reference is unavailable")),
    )
    before = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
    saved = read_bundle(path).cards[-1]
    assert saved.computation == card.computation
    cli = CliRunner().invoke(app, ["pgx", "calls", path.name, "--json"])
    assert cli.exit_code == 0, cli.output
    cli_card = json.loads(cli.output)["guideline_cards"][0]
    assert cli_card["computation"] == card.computation
    client = TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1"
    )
    for suffix in ("", "/pgx", "/pgx?gene=CYP2C19", "/cards/" + card.card_id):
        page = client.get(f"/runs/{path.name}" + suffix)
        assert page.status_code == 200
        assert (
            "0 conditional CPIC" in page.text
            and "Source rows lacking usable evidence: 1" in page.text
        )
        assert "<strong>CPIC source recommendation, conditional:</strong>" not in page.text
        if suffix.startswith("/cards/"):
            assert "Dosing implication unavailable" in page.text
    assert before == {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
