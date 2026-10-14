"""Fabricated public-reference shapes, never sample genotypes or network calls."""

from __future__ import annotations

import gzip
import io
import json
import stat
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.pgx import catalog, sources
from genetics.pgx.archives import HEADERS, MEMBERS, read_archive
from genetics.pgx.locking import publication_lock
from genetics.pgx.sql import REQUIRED, Tables, copy_value, read_dump
from genetics.refs import manifest, postprocess
from genetics.refs.postprocess import ProcessError, ProcessStatus


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
