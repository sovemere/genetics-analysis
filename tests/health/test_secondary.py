"""ACMG views use fabricated reference loci/calls, never a personal export."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine.cards import KnowledgePack
from genetics.engine.evidence import AssembledCard
from genetics.health.clinvar import ClinVarError, ClinVarIndex, ClinVarLookup, validate_lookup
from genetics.health.frequencies import FrequencyIndex, calibrate, parse_record
from genetics.health.secondary import (
    DOI,
    SOURCE,
    annotation,
    default_reference,
    parse_reference,
    secondary_view,
    surface,
)
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run.bundle import CLINVAR_NAME, MANIFEST_NAME, BundleError, read_bundle, write_bundle
from genetics.web.app import create_app
from genetics.web.config import WebConfig

POS = 12345678


def reference() -> dict[str, Any]:
    return {
        "provenance": {
            "source": SOURCE,
            "version": "3.3",
            "filename": "synthetic-acmg.json",
            "sha256": "1" * 64,
            "records": 2,
            "accessed": "2026-10-05",
            "license": "CC0-1.0",
            "doi": DOI,
        },
        "genes": [
            {
                "symbol": "BRCA1",
                "hgnc_id": "HGNC:1100",
                "guidance": "Synthetic disease-specific restriction.",
            },
            {
                "symbol": "TTN",
                "hgnc_id": "HGNC:12403",
                "guidance": "Synthetic truncation restriction; not adjudicated.",
            },
        ],
    }


def lookup(
    tmp_path: Path,
    *,
    count: int = 1,
    info: str = "GENEINFO=BRCA1:672;CLNSIG=Pathogenic",
    alt: str = "G",
    called: str = "AG",
    frequency: bool = True,
) -> ClinVarLookup:
    path = tmp_path / "synthetic.vcf.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("##fileformat=VCFv4.1\n##fileDate=2026-01-01\n##reference=GRCh37\n")
        handle.write(
            "\t".join(("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")) + "\n"
        )
        for n in range(count):
            handle.write(
                "\t".join(("7", str(POS + n), str(900000001 + n), "A", alt, ".", ".", info)) + "\n"
            )
    rows = [
        {
            "rsid": f"rs{900000001 + n}",
            "chrom": "7",
            "pos_grch37": POS + n,
            "a1": called[0] if called else None,
            "a2": called[1] if called else None,
            "genotype": called or None,
            "call_status": "called" if called else "no_call",
        }
        for n in range(count)
    ]
    table = GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")
    result = ClinVarIndex.build(path, version="2026-01-01").lookup(table)
    index = FrequencyIndex(
        tmp_path / "absent.sqlite",
        {
            "source": "gnomad_exomes_r2_1_1_grch37",
            "version": "r2.1.1",
            "build": "GRCh37",
            "filename": "synthetic.vcf.bgz",
            "sha256": "2" * 64,
            "index_schema_version": 2,
            "records": count,
        },
    )
    frequencies = {
        ("7", POS + n): [
            parse_record(
                "\t".join(
                    (
                        "7",
                        str(POS + n),
                        ".",
                        "A",
                        "G",
                        ".",
                        "PASS",
                        "AC=1;AN=200000;AF=0.000005;nhomalt=0",
                    )
                )
            )
        ]
        for n in range(count)
    }
    return calibrate(
        result, index=index if frequency else None, records=frequencies if frequency else {}
    )


@pytest.mark.parametrize(
    "pair,match",
    [
        ("BRCA1:672", True),
        ("OTHER:900|BRCA1:672", True),
        ("BRCA1P1:900", False),
        ("brca1:672", False),
        ("BRCA1", False),
        ("BRCA1:wrong", False),
        ("BRCA1:0", False),
        ("TTN:7273", True),
    ],
)
def test_membership_is_exact_symbol_and_numeric_gene_id(pair: str, match: bool) -> None:
    actual = annotation({"info": {"GENEINFO": pair, "CLNSIG": "Pathogenic"}}, reference()["genes"])
    assert bool(actual) == match
    if actual:
        assert actual["reportability"] == "not_adjudicated"


@pytest.mark.parametrize(
    "significance,conflict,plp",
    [
        ("Pathogenic", "", True),
        ("Likely_pathogenic", "", True),
        ("Pathogenic/Likely_pathogenic", "", True),
        ("Pathogenic|Likely_pathogenic", "", True),
        ("Pathogenic|Uncertain_significance", "", False),
        ("Pathogenic", "Pathogenic(1)|Benign(1)", False),
        ("Conflicting_classifications_of_pathogenicity", "", False),
        ("Uncertain_significance", "", False),
        ("Benign", "", False),
        ("", "", False),
    ],
)
def test_classification_is_reference_only_and_never_reportability(
    significance: str, conflict: str, plp: bool
) -> None:
    info = {"GENEINFO": "BRCA1:672", "CLNSIG": significance, "CLNSIGCONF": conflict}
    actual = annotation({"info": info}, reference()["genes"])
    assert actual is not None
    assert (actual["classification"] == "pathogenic_or_likely_pathogenic_annotation") == plp
    assert actual["reportability"] == "not_adjudicated"


@pytest.mark.parametrize(
    "called,alt,frequency",
    [
        ("AG", "G", True),
        ("AG", "G", False),
        ("AA", "G", True),
        ("", "G", True),
        ("AD", "<DEL>", True),
        ("AG", "G,T", True),
    ],
)
def test_every_overlap_survives_with_original_reliability(
    tmp_path: Path, called: str, alt: str, frequency: bool
) -> None:
    original = lookup(tmp_path, called=called, alt=alt, frequency=frequency)
    result = surface(original, reference()).to_dict()
    validate_lookup(result)
    view = secondary_view(result)
    assert len(view["loci"]) == 1
    entry = view["loci"][0]["records"][0]
    old_entry = original.to_dict()["loci"][0]["records"][0]
    assert {k: v for k, v in entry.items() if k != "acmg"} == old_entry
    assert (
        "Only clinical sequencing can establish or exclude the variant." in entry["acmg"]["notice"]
    )
    if called == "AG" and alt == "G":
        assert entry["reliability"]["tier"] == ("likely-artifact" if frequency else "unknown")


@pytest.mark.parametrize(
    "field", ["counts", "guidance", "classification", "notice", "sha256", "extra"]
)
def test_saved_acmg_metadata_is_validated_offline(tmp_path: Path, field: str) -> None:
    saved = surface(lookup(tmp_path), reference()).to_dict()
    if field == "counts":
        saved["secondary_reference"]["counts"]["likely-artifact"] = 99
    elif field == "guidance":
        saved["loci"][0]["records"][0]["acmg"]["genes"][0]["guidance"] = "changed"
    elif field in {"classification", "notice"}:
        saved["loci"][0]["records"][0]["acmg"][field] = "changed"
    elif field == "sha256":
        saved["secondary_reference"]["provenance"][field] = "invalid"
    else:
        saved["secondary_reference"]["extra"] = True
    with pytest.raises(ClinVarError):
        validate_lookup(saved)


def test_missing_sources_are_not_a_negative_screen(tmp_path: Path) -> None:
    assert default_reference() is None
    for original, ref in [
        (lookup(tmp_path), None),
        (calibrate(ClinVarLookup.not_run(), index=None, records={}), reference()),
    ]:
        saved = surface(original, ref).to_dict()
        validate_lookup(saved)
        assert saved["secondary_reference"]["status"] == "not_run"
        assert secondary_view(saved)["loci"] == []
    with pytest.raises(ClinVarError, match="frequency-screen"):
        surface(ClinVarLookup.not_run(), reference())


@pytest.mark.parametrize("damage", ["none", "count", "duplicate", "identifier", "guidance"])
def test_complete_reference_parser_refuses_truncated_or_damaged_roster(damage: str) -> None:
    rows = [
        {"symbol": g["symbol"], "hgnc_id": g["hgnc_id"], "comments": g["guidance"]}
        for g in reference()["genes"]
    ]
    raw: dict[str, Any] = {"total": 2, "totalNotFiltered": 2, "rows": rows}
    if damage == "count":
        raw["totalNotFiltered"] = 3
    elif damage == "duplicate":
        rows[1] = rows[0]
    elif damage == "identifier":
        rows[0]["hgnc_id"] = "wrong"
    elif damage == "guidance":
        rows[0]["comments"] = None
    payload = json.dumps(raw).encode()
    if damage == "none":
        assert parse_reference(payload, expected_genes=2) == reference()["genes"]
    else:
        with pytest.raises(ClinVarError):
            parse_reference(payload, expected_genes=2)
    with pytest.raises(ClinVarError):
        parse_reference(payload)


def test_corrupted_default_cache_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.refs.manifest import load

    item = load().get(SOURCE).files[0]
    source = tmp_path / SOURCE
    source.mkdir()
    (source / item.filename).write_text("corrupt", encoding="utf-8")
    monkeypatch.setattr("genetics.health.secondary.references_dir", lambda: tmp_path)
    with pytest.raises(ClinVarError, match="checksum"):
        default_reference()


def test_default_cache_is_pinned_complete_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.refs.manifest import Manifest, load

    rows = [
        {
            "symbol": f"SYNTHETIC{n}",
            "hgnc_id": f"HGNC:{900000 + n}",
            "comments": "Synthetic guidance",
        }
        for n in range(84)
    ]
    payload = json.dumps({"total": 84, "totalNotFiltered": 84, "rows": rows}).encode()
    source = load().get(SOURCE)
    item = replace(source.files[0], sha256=hashlib.sha256(payload).hexdigest())
    manifest = Manifest(schema_version=1, sources=(replace(source, files=(item,)),))
    root = tmp_path / SOURCE
    root.mkdir()
    target = root / item.filename
    target.write_bytes(payload)
    monkeypatch.setattr("genetics.refs.manifest.load", lambda: manifest)
    monkeypatch.setattr("genetics.health.secondary.references_dir", lambda: tmp_path)
    result = default_reference()
    assert result is not None
    assert result["provenance"]["records"] == 84
    assert result["provenance"]["sha256"] == item.sha256
    assert target.read_bytes() == payload
    assert list(root.iterdir()) == [target]


@pytest.mark.parametrize("available", [False, True])
def test_empty_view_never_claims_a_negative_clinical_screen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample_qc: QCReport,
    sample_cards: tuple[AssembledCard, ...],
    sample_pack: KnowledgePack,
    available: bool,
) -> None:
    result = surface(
        lookup(tmp_path, info="GENEINFO=OTHER:999;CLNSIG=Benign"),
        reference() if available else None,
    )
    data = tmp_path / "data"
    monkeypatch.setenv("GENETICS_DATA_DIR", str(data))
    path = write_bundle(
        qc=sample_qc,
        cards=sample_cards,
        pack=sample_pack,
        ancestry=AncestryContext.not_run("synthetic"),
        clinvar=result,
        runs_root=data / "runs",
        run_id="empty-secondary",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    with TestClient(
        create_app(WebConfig(runs_root=data / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        page = client.get(f"/runs/{path.name}/secondary-findings")
        assert page.status_code == 200
        assert "No overlap is not a negative clinical screen" in page.text
        if available:
            assert "No ACMG gene-list overlap was recorded" in page.text
            assert "This does not exclude a variant or a condition" in page.text
        else:
            assert "no secondary-finding screen was completed" in page.text
            assert "No ACMG gene-list overlap was recorded" not in page.text
        full = client.get(f"/runs/{path.name}/clinvar")
        assert "Variation 900000001" in full.text


@pytest.mark.parametrize("legacy", [False, True])
def test_bundle_cli_dashboard_share_saved_overlaps_and_paginate_all_tiers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample_qc: QCReport,
    sample_cards: tuple[AssembledCard, ...],
    sample_pack: KnowledgePack,
    legacy: bool,
) -> None:
    original = lookup(tmp_path, count=101, info="GENEINFO=TTN:7273;CLNSIG=Uncertain_significance")
    result = original if legacy else surface(original, reference())
    snapshot = result.to_dict()
    data = tmp_path / "data"
    monkeypatch.setenv("GENETICS_DATA_DIR", str(data))
    path = write_bundle(
        qc=sample_qc,
        cards=sample_cards,
        pack=sample_pack,
        ancestry=AncestryContext.not_run("synthetic"),
        clinvar=result,
        runs_root=data / "runs",
        run_id="secondary-test",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    if legacy:
        manifest = json.loads((path / MANIFEST_NAME).read_text())
        manifest["format_version"] = 9
        (path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    assert read_bundle(path).clinvar == snapshot
    json_result = CliRunner().invoke(app, ["runs", "secondary", path.name, "--json"])
    assert json_result.exit_code == 0, json_result.stdout
    assert json.loads(json_result.stdout)["secondary"] == secondary_view(snapshot)
    full_json = CliRunner().invoke(app, ["runs", "clinvar", path.name, "--json"])
    assert json.loads(full_json.stdout)["clinvar"] == snapshot
    human = CliRunner().invoke(app, ["runs", "secondary", path.name])
    assert human.exit_code == 0
    with TestClient(
        create_app(WebConfig(runs_root=data / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        page = client.get(f"/runs/{path.name}/secondary-findings")
        assert page.status_code == 200
        assert "ACMG secondary-finding gene overlaps" in page.text
        if legacy:
            assert "older run did not record ACMG" in page.text
            assert "older run did not record ACMG" in human.stdout
        else:
            assert "<title>ACMG gene overlaps" in page.text
            assert "all ClinVar reference overlaps" in page.text
            assert human.stdout.count("Measurement reliability: likely-artifact") == 101
            assert "Synthetic truncation restriction" in page.text
            assert "not_adjudicated" in page.text
            assert "Only clinical sequencing can establish or exclude the variant." in page.text
            assert "doi.org/10.1016/j.gim.2025.101454" in page.text
            assert page.headers["referrer-policy"] == "no-referrer"
            assert "Showing loci 1\u2013100 of 101" in page.text
            assert "secondary-findings?page=2" in page.text
            last = client.get(f"/runs/{path.name}/secondary-findings?page=2")
            assert "Showing loci 101\u2013101 of 101" in last.text
            assert "Variation 900000101" in last.text
            assert "likely-artifact" in last.text
            manifest = json.loads((path / MANIFEST_NAME).read_text())
            manifest["format_version"] = 9
            (path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
            with pytest.raises(BundleError, match="format 10"):
                read_bundle(path)


@pytest.mark.parametrize("schema", [2, 3, 4])
def test_empty_saved_alt_is_a_bundle_error_and_dashboard_explanation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample_qc: QCReport,
    sample_cards: tuple[AssembledCard, ...],
    sample_pack: KnowledgePack,
    schema: int,
) -> None:
    from genetics.health.frequencies import _legacy_reliability

    original = lookup(tmp_path)
    result = surface(original, reference()) if schema == 4 else original
    data = tmp_path / "data"
    monkeypatch.setenv("GENETICS_DATA_DIR", str(data))
    path = write_bundle(
        qc=sample_qc,
        cards=sample_cards,
        pack=sample_pack,
        ancestry=AncestryContext.not_run("synthetic"),
        clinvar=result,
        runs_root=data / "runs",
        run_id="malformed-secondary",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    saved = result.to_dict()
    if schema == 2:
        saved["schema_version"] = 2
        entry = saved["loci"][0]["records"][0]
        entry["reliability"] = _legacy_reliability(entry, entry["frequency_records"])
    validate_lookup(saved)
    saved["loci"][0]["records"][0]["alts"] = []
    with pytest.raises(ClinVarError, match="malformed"):
        validate_lookup(saved)
    payload_path = path / CLINVAR_NAME
    payload_path.write_text(json.dumps(saved), encoding="utf-8")
    manifest = json.loads((path / MANIFEST_NAME).read_text())
    manifest["files"][CLINVAR_NAME] = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    (path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="malformed"):
        read_bundle(path)
    cli = CliRunner().invoke(app, ["runs", "secondary", path.name, "--json"])
    assert cli.exit_code == 1
    assert "malformed" in cli.stdout
    with TestClient(
        create_app(WebConfig(runs_root=data / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        page = client.get(f"/runs/{path.name}/secondary-findings")
        assert page.status_code == 200
        assert "malformed" in page.text
