"""The QC and provenance page and the coverage `genetics runs qc` prints (roadmap M14.5).

The saved run is the committed pack's polygenic cards and one trait card, matched against
an invented table (each card's first and last declared allele). No score file is given, so
every polygenic card is saved not run, with its reason. Runs with a placed score and with a
recorded imputation stage are built by ``tests/refs/test_pgs_cards.py`` and
``tests/run/test_imputation_snapshot.py``, which open this page on them too. No export and
no saved real run is read.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine.cards import CardKind, KnowledgePack, default_knowledge_dir
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import match_pack
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run import reads, store
from genetics.run.bundle import RunBundle, write_bundle
from genetics.run.pipeline import observations
from genetics.testing.parity import refused_query
from genetics.web import WebConfig, create_app

LOCAL_BASE_URL = "http://127.0.0.1:8765"
TRAIT = "wnt10a_hair_curl"

runner = CliRunner()


def _table(pack: KnowledgePack) -> GenotypeTable:
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for card in pack.cards:
        if card.match is None:
            continue
        variant = card.match.variants[0]
        first, last = variant.key.alleles[0], variant.key.alleles[-1]
        rows[(variant.key.chrom.value, variant.key.pos_grch37)] = {
            "rsid": variant.rsid,
            "chrom": variant.key.chrom.value,
            "pos_grch37": variant.key.pos_grch37,
            "a1": first,
            "a2": last,
            "genotype": "".join(sorted(first + last)),
            "call_status": "called",
        }
    return GenotypeTable(
        pl.DataFrame(list(rows.values()), schema=NORMALIZED_SCHEMA), vendor="synthetic"
    )


@pytest.fixture
def runs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "data" / "runs"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def saved(sample_qc: QCReport, runs_root: Path) -> Path:
    full = KnowledgePack.load(default_knowledge_dir())
    pack = KnowledgePack(
        tuple(c for c in full.cards if c.kind is CardKind.POLYGENIC or c.id == TRAIT),
        full.source_dir,
    )
    matches = match_pack(pack, _table(pack))
    return write_bundle(
        qc=sample_qc,
        cards=assemble_pack(pack, matches, observations(pack, matches)),
        pack=pack,
        ancestry=AncestryContext.not_run("synthetic test bundle"),
        runs_root=runs_root,
        lock_path=runs_root / "absent.lock",
        tools_root=runs_root / "tools",
    )


@pytest.fixture
def client(runs_root: Path) -> Iterator[TestClient]:
    application = create_app(WebConfig(runs_root=runs_root))
    with TestClient(application, base_url=LOCAL_BASE_URL) as running:
        yield running


# ---------------------------------------------------------------------------
# The coverage record
# ---------------------------------------------------------------------------


def test_every_polygenic_card_is_listed_in_saved_order_placed_or_not(saved: Path) -> None:
    bundle = store.load_run(saved.name)
    report = reads.coverage_report(bundle)
    polygenic = [card for card in bundle.cards if card.kind == "polygenic"]
    assert len(polygenic) > 10
    assert [row["card_id"] for row in report["polygenic"]] == [c.card_id for c in polygenic]
    assert TRAIT not in {row["card_id"] for row in report["polygenic"]}
    assert report["polygenic_counts"] == {
        "scores": len(polygenic),
        "placed": 0,
        "with_phase_coverage": 0,
    }
    for row, card in zip(report["polygenic"], polygenic, strict=True):
        assert row["placed"] is False and row["pgs_id"] is None and row["phase_coverage"] is None
        assert row["reason"] == (card.computation or {})["reason"] and row["reason"]
        assert row["status"] == card.status and row["confidence_tier"] == card.confidence_tier
    # The low-level writer saves a lookup that did not run, with its reason.
    assert bundle.clinvar is not None
    assert report["clinvar_status"] == "lookup-not-run" and report["clinvar"] is None
    assert report["clinvar_reason"] == bundle.clinvar["reason"] and report["clinvar_reason"]


def _bundle(cards: Any, clinvar: Any) -> RunBundle:
    return cast(RunBundle, SimpleNamespace(cards=cards, clinvar=clinvar))


def test_each_clinvar_state_is_named_apart(saved: Path) -> None:
    bundle = store.load_run(saved.name)
    old = reads.coverage_report(_bundle(bundle.cards, {"status": "complete"}))
    assert old["clinvar_status"] == "not-recorded"
    absent = reads.coverage_report(_bundle((), None))
    assert absent["clinvar_status"] == "no-lookup" and absent["clinvar_reason"] is None
    recorded = {"status": "complete", "coverage": {"status": "complete"}}
    report = reads.coverage_report(_bundle((), recorded))
    assert report["clinvar_status"] == "recorded" and report["clinvar"] == recorded["coverage"]
    assert report["clinvar_reason"] is None


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_runs_qc_prints_the_coverage_in_both_forms(saved: Path) -> None:
    bundle = store.load_run(saved.name)
    result = runner.invoke(app, ["runs", "qc", saved.name, "--json"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["current_context"] == {
        "context": "current",
        "coverage": json.loads(json.dumps(reads.coverage_report(bundle))),
    }
    text = runner.invoke(app, ["runs", "qc", saved.name])
    assert text.exit_code == 0, text.output
    assert "Coverage" in text.stdout and "ClinVar  lookup not run: " in text.stdout
    for row in document["current_context"]["coverage"]["polygenic"]:
        assert f"{row['card_id']}  not recorded | not recorded" in text.stdout


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_every_run_page_links_the_qc_page(saved: Path, client: TestClient) -> None:
    for address in (f"/runs/{saved.name}", f"/runs/{saved.name}/ancestry"):
        assert f'href="/runs/{saved.name}/qc"' in client.get(address).text


def test_the_page_shows_the_export_coverage_imputation_and_provenance(
    saved: Path, client: TestClient, sample_qc: QCReport
) -> None:
    response = client.get(f"/runs/{saved.name}/qc")
    assert response.status_code == 200
    body = response.text
    assert "<title>Quality control and provenance · genetics</title>" in body
    assert f"{sample_qc.call_rates.total_markers:,}" in body
    assert f"{sample_qc.call_rates.call_rate * 100:.2f}%" in body
    for row in sample_qc.call_rates.by_chrom:
        assert f'<th scope="row">{row.chrom}</th>' in body
    for warning in sample_qc.warnings:
        assert warning in body
    bundle = store.load_run(saved.name)
    for card in bundle.cards:
        if card.kind == "polygenic":
            assert f'href="/runs/{saved.name}/cards/{card.card_id}"' in body
            assert f"Not placed: {(card.computation or {})['reason']}" in body
    assert f'href="/runs/{saved.name}/cards/{TRAIT}"' not in body
    reason = (bundle.clinvar or {})["reason"]
    assert "The ClinVar lookup did not run" in body and reason in body
    assert "supplied no completed imputation stage" in body
    assert "No reference recorded: no manifest.lock at save time" in body
    assert "No tool was recorded as installed" in body
    assert bundle.provenance["knowledge"]["digest"] in body


def test_a_run_another_version_wrote_renders_its_gaps_as_dashes(
    saved: Path, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every saved record is read with `dig`: a field it lacks is `-`, never a failure."""
    header = {"run_id": saved.name, "path": str(saved), "format_version": 1, "created_at": "x"}
    coverage: dict[str, Any] = {
        "polygenic": [],
        "polygenic_counts": {"scores": 0, "placed": 0, "with_phase_coverage": 0},
        "clinvar_status": "not-recorded",
        "clinvar_reason": None,
        "clinvar": None,
    }
    sparse = header | {
        "qc": {"call_rates": "odd", "sex": {"notes": "not a list"}},
        "imputation": None,
        "imputation_provenance_status": None,
        "provenance": {},
        "current_context": {"context": "current", "coverage": coverage},
    }
    monkeypatch.setattr(reads, "qc_view", lambda bundle: sparse)
    monkeypatch.setattr(
        reads, "imputation_view", lambda bundle: header | {"execution": None, "provenance": None}
    )
    response = client.get(f"/runs/{saved.name}/qc")
    assert response.status_code == 200
    body = " ".join(response.text.split())
    assert "saved before bundle format 14" in body
    assert "before full imputation provenance existed" in body
    assert "saved before coverage was recorded" in body
    assert "This run holds no polygenic card." in body
    assert "No reference recorded: -" in body


def test_the_whole_page_is_scanned_for_genotypes(
    saved: Path, runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page shows what two scanned commands print, so it holds to the same rule."""
    original = reads.qc_view

    def leaking(bundle: Any) -> dict[str, Any]:
        view = original(bundle)
        view["qc"] = dict(view["qc"]) | {"warnings": [refused_query()]}
        return view

    monkeypatch.setattr(reads, "qc_view", leaking)
    application = create_app(WebConfig(runs_root=runs_root))
    with TestClient(application, base_url=LOCAL_BASE_URL, raise_server_exceptions=False) as client:
        response = client.get(f"/runs/{saved.name}/qc")
    assert response.status_code == 500
    assert refused_query() not in response.text


def test_a_run_that_does_not_open_shows_why(client: TestClient) -> None:
    response = client.get("/runs/20200101T000000Z-0000feed/qc")
    assert response.status_code == 200
    assert (
        "No run named" in response.text
        and "Quality control and provenance"
        not in (response.text.split("<title>")[1].split("</title>")[0])
    )
