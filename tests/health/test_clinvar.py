"""ClinVar lookup uses invented coordinates, identifiers and sample calls only."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Sequence
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
from genetics.health.clinvar import (
    ClinVarError,
    ClinVarIndex,
    ClinVarLookup,
    lookup_default,
    validate_lookup,
)
from genetics.ingest.schema import NORMALIZED_SCHEMA, CallStatus, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    CLINVAR_NAME,
    MANIFEST_NAME,
    BundleError,
    BundleIntegrityError,
    read_bundle,
    write_bundle,
)
from genetics.run.pipeline import analyse, save
from genetics.web.app import create_app
from genetics.web.config import WebConfig

VERSION = "2026-01-01"
POS = 12345678
RSID = "rs900000001"


def vcf_row(
    *,
    pos: int = POS,
    ref: str = "A",
    alt: str = "G",
    identifier: str = "900000001",
    info: str = "CLNSIG=Pathogenic;CLNREVSTAT=criteria_provided,_single_submitter;CLNDN=Synthetic_condition;CLNDISDB=MedGen:SYNTHETIC;ALLELEID=900000011;RS=900000001",
) -> str:
    return "\t".join(("7", str(pos), identifier, ref, alt, ".", ".", info))


def write_vcf(tmp_path: Path, rows: Sequence[str], *, build: str = "GRCh37") -> Path:
    path = tmp_path / "synthetic.vcf.gz"
    lines = [
        "##fileformat=VCFv4.1",
        f"##fileDate={VERSION}",
        f"##reference={build}",
        "\t".join(("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")),
        *rows,
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def table(
    calls: Sequence[tuple[int, str | None, str | None, str]] = ((POS, "A", "G", "called"),),
) -> GenotypeTable:
    rows = []
    for pos, a1, a2, status in calls:
        alleles = sorted((a1, a2)) if a1 is not None and a2 is not None else (None, None)
        rows.append(
            {
                "rsid": RSID,
                "chrom": "7",
                "pos_grch37": pos,
                "a1": alleles[0],
                "a2": alleles[1],
                "genotype": "".join(alleles) if alleles[0] is not None else None,
                "call_status": status,
            }
        )
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")


def build(tmp_path: Path, rows: Sequence[str] | None = None) -> ClinVarIndex:
    return ClinVarIndex.build(write_vcf(tmp_path, rows or [vcf_row()]), version=VERSION)


def test_position_and_alleles_are_primary_and_source_annotations_survive(tmp_path: Path) -> None:
    index = build(tmp_path)
    sample = table(((POS, "G", "A", "called"), (POS + 1, "A", "G", "called")))
    result = index.lookup(sample).to_dict()
    validate_lookup(result)
    assert result["counts"]["reference_absent_loci"] == 1
    entry = result["loci"][0]["records"][0]
    assert entry["status"] == "alternate_observed"
    assert entry["variation_id"] == "900000001"
    assert entry["info"]["ALLELEID"] == "900000011"
    assert entry["info"]["CLNDISDB"] == "MedGen:SYNTHETIC"
    assert result["provenance"]["version"] == VERSION
    assert (
        result["provenance"]["sha256"]
        == hashlib.sha256((tmp_path / "synthetic.vcf.gz").read_bytes()).hexdigest()
    )
    assert result["notice"].startswith("Reference lookup only.")


@pytest.mark.parametrize(
    "a1,a2,call_status,status",
    [
        ("A", "A", "called", "reference_only"),
        ("G", "G", "called", "alternate_observed"),
        ("G", "G", "hemizygous", "alternate_observed"),
        ("C", "G", "called", "incompatible"),
        (None, None, "no_call", "missing"),
        ("A", "G", "het_haploid", "ambiguous"),
        ("I", "D", "called", "excluded"),
    ],
)
def test_call_states_are_explicit(
    tmp_path: Path, a1: str | None, a2: str | None, call_status: str, status: str
) -> None:
    result = build(tmp_path).lookup(table(((POS, a1, a2, call_status),))).to_dict()
    validate_lookup(result)
    assert result["loci"][0]["records"][0]["status"] == status


def test_duplicate_probes_do_not_pick_a_favoured_call(tmp_path: Path) -> None:
    result = (
        build(tmp_path)
        .lookup(table(((POS, "A", "G", "called"), (POS, "A", "A", "called"))))
        .to_dict()
    )
    assert result["counts"]["ambiguous"] == 1
    assert len(result["loci"][0]["probes"]) == 2
    validate_lookup(result)


def test_matching_duplicate_probes_remain_one_locus(tmp_path: Path) -> None:
    result = (
        build(tmp_path)
        .lookup(table(((POS, "A", "G", "called"), (POS, "G", "A", "called"))))
        .to_dict()
    )
    assert result["counts"]["alternate_observed"] == 1
    assert result["counts"]["sample_markers"] == 2
    validate_lookup(result)


def test_multiallelic_and_conflicting_records_preserve_all_annotations(tmp_path: Path) -> None:
    rows = [
        vcf_row(
            alt="G,C",
            info="CLNSIG=Conflicting_classifications_of_pathogenicity;CLNSIGCONF=Benign(1)|Pathogenic(1);CLNSIGINCL=900000999:Pathogenic;ONC=Oncogenic",
        ),
        vcf_row(identifier="900000002", alt="T", info="CLNSIG=Benign"),
    ]
    result = build(tmp_path, rows).lookup(table()).to_dict()
    entries = result["loci"][0]["records"]
    assert [e["status"] for e in entries] == ["ambiguous", "incompatible"]
    assert entries[0]["info"]["CLNSIGCONF"] == "Benign(1)|Pathogenic(1)"
    assert entries[0]["info"]["ONC"] == "Oncogenic"
    assert entries[0]["alts"] == ["G", "C"]
    validate_lookup(result)


def test_duplicate_reference_alleles_are_ambiguous_and_keep_classification_conflicts(
    tmp_path: Path,
) -> None:
    index = build(tmp_path, [vcf_row(), vcf_row(identifier="900000002", info="CLNSIG=Benign")])
    result = index.lookup(table()).to_dict()
    entries = result["loci"][0]["records"]
    assert [e["status"] for e in entries] == ["ambiguous", "ambiguous"]
    assert [e["info"]["CLNSIG"] for e in entries] == ["Pathogenic", "Benign"]
    validate_lookup(result)


def test_no_alternate_and_alternate_contig_records_are_preserved_without_false_matches(
    tmp_path: Path,
) -> None:
    rows = [vcf_row(alt="."), vcf_row().replace("7\t", "NT_113889.1\t", 1)]
    result = build(tmp_path, rows).lookup(table()).to_dict()
    assert result["provenance"]["records"] == 2
    assert result["counts"]["overlapping_records"] == 1
    assert result["counts"]["excluded"] == 1
    validate_lookup(result)


@pytest.mark.parametrize("ref,alt", [("AT", "A"), ("A", "<DEL>"), ("N", "G")])
def test_reference_indels_and_symbolic_alleles_are_excluded(
    tmp_path: Path, ref: str, alt: str
) -> None:
    result = build(tmp_path, [vcf_row(ref=ref, alt=alt)]).lookup(table()).to_dict()
    assert result["counts"]["excluded"] == 1
    validate_lookup(result)


@pytest.mark.parametrize(
    "row",
    [
        vcf_row(identifier="invalid"),
        vcf_row(alt="G,G"),
        vcf_row(alt="A"),
        vcf_row(pos=0),
        vcf_row(info="CLNSIG=Benign;CLNSIG=Pathogenic"),
        "invalid",
    ],
)
def test_malformed_records_fail_without_quoting_calls(tmp_path: Path, row: str) -> None:
    with pytest.raises(ClinVarError, match="ClinVar"):
        build(tmp_path, [row])
    assert not list(tmp_path.glob("*.building-*"))
    assert not (tmp_path / "clinvar_lookup.sqlite").exists()


def test_wrong_build_or_date_and_truncated_gzip_fail(tmp_path: Path) -> None:
    path = write_vcf(tmp_path, [vcf_row()], build="GRCh38")
    with pytest.raises(ClinVarError, match="build"):
        ClinVarIndex.build(path, version=VERSION)
    path = write_vcf(tmp_path, [vcf_row()])
    with pytest.raises(ClinVarError, match="date"):
        ClinVarIndex.build(path, version="wrong")
    path.write_bytes(path.read_bytes()[:-15])
    with pytest.raises(ClinVarError):
        ClinVarIndex.build(path, version=VERSION)


def test_checksum_cache_reuse_and_corruption(tmp_path: Path) -> None:
    index = build(tmp_path)
    stamp = index.path.stat().st_mtime_ns
    assert build(tmp_path).path.stat().st_mtime_ns == stamp
    with pytest.raises(ClinVarError, match="pinned checksum"):
        ClinVarIndex.build(tmp_path / "synthetic.vcf.gz", version=VERSION, expected_md5="0" * 32)
    with index.path.open("ab") as handle:
        handle.write(b"corruption")
    with pytest.raises(ClinVarError, match=r"provenance|checksum"):
        build(tmp_path)


def test_missing_reference_is_explicit_and_exports_do_not_mutate_results() -> None:
    result = lookup_default(table())
    assert result.status == "not_run"
    validate_lookup(result.to_dict())
    assert "genotype" not in repr(result)


@pytest.mark.parametrize("mutate", ["status", "counts", "build", "probe", "info", "unknown"])
def test_saved_results_reject_inconsistent_or_unknown_fields(tmp_path: Path, mutate: str) -> None:
    payload = build(tmp_path).lookup(table()).to_dict()
    if mutate == "status":
        payload["loci"][0]["records"][0]["status"] = "reference_only"
    elif mutate == "counts":
        payload["counts"]["overlapping_loci"] += 1
    elif mutate == "build":
        payload["provenance"]["build"] = "GRCh38"
    elif mutate == "probe":
        payload["loci"][0]["probes"][0]["call_status"] = CallStatus.NO_CALL.value
    elif mutate == "info":
        payload["loci"][0]["records"][0]["info"]["CLNSIG"] = False
    else:
        payload["unknown"] = True
    with pytest.raises(ClinVarError):
        validate_lookup(payload)


def test_bundle_cli_and_dashboard_share_the_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
) -> None:
    result = build(tmp_path).lookup(table())
    snapshot = result.to_dict()
    edited = result.to_dict()
    edited["loci"][0]["records"][0]["info"]["CLNSIG"] = "changed"
    assert result.to_dict() == snapshot
    data = tmp_path / "data"
    monkeypatch.setenv("GENETICS_DATA_DIR", str(data))
    path = write_bundle(
        qc=sample_qc,
        cards=sample_cards,
        pack=sample_pack,
        ancestry=AncestryContext.not_run("synthetic"),
        clinvar=result,
        runs_root=data / "runs",
        run_id="clinvar-test",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    assert read_bundle(path).clinvar == snapshot
    response = CliRunner().invoke(app, ["runs", "clinvar", path.name, "--json"])
    assert response.exit_code == 0
    assert json.loads(response.stdout)["clinvar"] == snapshot
    with TestClient(
        create_app(WebConfig(runs_root=data / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        page = client.get(f"/runs/{path.name}/clinvar")
        assert page.status_code == 200
        for expected in (
            "900000001",
            "alternate_observed",
            "Pathogenic",
            "Synthetic_condition",
            VERSION,
            snapshot["notice"],
        ):
            assert expected in page.text
        assert "/clinvar" in client.get(f"/runs/{path.name}").text
    (path / CLINVAR_NAME).write_text("{}", encoding="utf-8")
    with pytest.raises(BundleIntegrityError):
        read_bundle(path)
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][CLINVAR_NAME] = hashlib.sha256((path / CLINVAR_NAME).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="ClinVar"):
        read_bundle(path)


def test_old_v6_bundles_remain_readable(
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
) -> None:
    path = write_bundle(
        qc=sample_qc,
        cards=(),
        pack=sample_pack,
        ancestry=AncestryContext.not_run("synthetic"),
        runs_root=tmp_path / "runs",
        run_id="old-test",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    manifest = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["format_version"] = 6
    del manifest["files"][CLINVAR_NAME]
    (path / CLINVAR_NAME).unlink()
    (path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    assert read_bundle(path).clinvar is None


def test_dashboard_pages_keep_every_lookup_accessible(
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
) -> None:
    rows = [vcf_row(pos=POS + n, identifier=str(900000001 + n)) for n in range(101)]
    calls = [(POS + n, "A", "G", "called") for n in range(101)]
    result = build(tmp_path, rows).lookup(table(calls))
    path = write_bundle(
        qc=sample_qc,
        cards=(),
        pack=sample_pack,
        ancestry=AncestryContext.not_run("synthetic"),
        clinvar=result,
        runs_root=tmp_path / "runs",
        run_id="pages",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    with TestClient(
        create_app(WebConfig(runs_root=path.parent)), base_url="http://127.0.0.1:8765"
    ) as client:
        first = client.get("/runs/pages/clinvar")
        second = client.get("/runs/pages/clinvar?page=2")
        assert first.status_code == second.status_code == 200
        assert "Variation 900000100" in first.text
        assert "Variation 900000101" not in first.text
        assert "Variation 900000101" in second.text
        assert "Variation 900000100" not in second.text
        assert "Page 1 of 2" in first.text
        assert "Page 2 of 2" in second.text
        assert "Reference lookup only." in first.text and "Reference lookup only." in second.text


def test_pipeline_saves_the_shared_lookup_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample_pack: KnowledgePack,
) -> None:
    index = build(tmp_path)
    received: list[GenotypeTable] = []

    def stage(table: GenotypeTable, **kwargs: Any) -> ClinVarLookup:
        received.append(table)
        return index.lookup(table)

    monkeypatch.setattr("genetics.run.pipeline.lookup_default", stage)
    export = Path(__file__).parents[1] / "fixtures" / "synthetic" / "ancestry_v2_male.txt"
    analysis = analyse(export, knowledge_dir=sample_pack.source_dir)
    assert len(received) == 1
    assert analysis.clinvar.status == "complete"
    path = save(
        analysis,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    assert read_bundle(path).clinvar == analysis.clinvar.to_dict()
