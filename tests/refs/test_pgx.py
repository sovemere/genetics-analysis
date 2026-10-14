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
    assert json.loads(result.output) == expected
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
