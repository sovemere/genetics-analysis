"""Synthetic f4 maths, harmonization, dependency states and saved UI/CLI agreement."""

from __future__ import annotations

import copy
import json
import math
import random
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.ancestry.eigenstrat import EigenstratError, hasharr
from genetics.cli.main import app
from genetics.engine.card_lint import lint_directory
from genetics.engine.cards import KnowledgePack
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.ingest import ingest
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.paths import repo_root
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    BundleError,
    _card_payload,
    _stored_card,
    read_bundle,
    write_bundle,
)
from genetics.run.pipeline import analyse, observations
from genetics.structure import archaic
from genetics.structure.archaic import (
    ArchaicError,
    ArchaicPanel,
    ArchaicSettings,
    compute_archaic,
    jackknife_ratio,
    load_panel,
)
from genetics.structure.archaic_interpretation import assemble_archaic_card
from genetics.structure.interpretation import infer_roh_cards
from genetics.web import WebConfig, create_app

POLICY = ArchaicSettings(min_informative=10, min_blocks=4, min_chromosomes=2)
EXPORT = Path(__file__).parents[1] / "fixtures/synthetic/ancestry_v2_male.txt"


@pytest.fixture
def pack(tmp_path: Path) -> KnowledgePack:
    root = tmp_path / "knowledge/structure"
    root.mkdir(parents=True)
    shutil.copyfile(repo_root() / "knowledge/structure/archaic.yaml", root / "archaic.yaml")
    return KnowledgePack.load(root.parent)


def synthetic() -> tuple[GenotypeTable, ArchaicPanel]:
    """Invented reference frequencies; fixed-seed diploid calls, no real-file subset."""
    rng = random.Random(632026)
    sites = []
    rows: list[tuple[str, str, int, str, str, str, str]] = []
    frequencies: dict[str, list[float | None]] = {
        k: [] for k in (*archaic.REFERENCE_IDS, "mbuti", "han")
    }
    for chromosome in ("1", "2", "3"):
        for block in range(8):
            for offset in range(30):
                neanderthal = offset % 2 == 0
                first, second = ("C", "A") if offset % 3 else ("G", "A")
                pos = block * 5_000_000 + offset * 1000 + 1
                b = 0.1
                v = 1.0 if neanderthal else 0.0
                d = 0.0 if neanderthal else 1.0
                values = {
                    "mbuti": b,
                    "han": 0.96 * b + 0.04 * v,
                    "vindija": v,
                    "altai": v if neanderthal else 0.5,
                    "denisova": d,
                    "chimp": 0.0,
                }
                for key, value in values.items():
                    frequencies[key].append(value)
                p = 0.9 * b + 0.07 * v + 0.03 * d
                pair = sorted(first if rng.random() < p else second for _ in range(2))
                rows.append(
                    (
                        f"rs{20_000_000 + len(rows)}",
                        chromosome,
                        pos,
                        pair[0],
                        pair[1],
                        "".join(pair),
                        "called",
                    )
                )
                sites.append((chromosome, pos, first, second))
    provenance = {
        "source": "synthetic",
        "version": "fixed-seed-v1",
        "build": "GRCh37",
        "archaic_ids": dict(archaic.REFERENCE_IDS),
        "population_ids": {"mbuti": ["invented_mbuti"], "han": ["invented_han"]},
        "input_sha256": {
            "synthetic.snp": "a" * 64,
            "synthetic.ind": "b" * 64,
            "synthetic.geno": "c" * 64,
        },
        "quality": "synthetic frequencies; no real individuals",
    }
    return (
        GenotypeTable(
            pl.DataFrame(rows, schema=NORMALIZED_SCHEMA, orient="row"), vendor="synthetic"
        ),
        ArchaicPanel(tuple(sites), {k: tuple(v) for k, v in frequencies.items()}, provenance),
    )


def test_weighted_jackknife_matches_independent_equations() -> None:
    blocks = [(2.0, 10.0, 10), (3.0, 15.0, 20), (5.0, 20.0, 30), (4.0, 18.0, 40)]
    result = jackknife_ratio(blocks, POLICY)
    theta = 14 / 63
    deleted = [((14 - n) / (63 - d), 100 / w) for n, d, w in blocks]
    corrected = 4 * theta - sum((1 - 1 / h) * t for t, h in deleted)
    variance = sum((h * theta - (h - 1) * t - corrected) ** 2 / (h - 1) for t, h in deleted) / 4
    assert result["ratio"] == pytest.approx(corrected)
    assert result["standard_error"] == pytest.approx(math.sqrt(variance))
    assert result["interval"] == pytest.approx(
        [corrected - 1.96 * math.sqrt(variance), corrected + 1.96 * math.sqrt(variance)]
    )


def test_equal_weight_jackknife_reduces_to_standard_delete_block_variance() -> None:
    blocks = [(i, 10.0, 10) for i in (1.0, 2.0, 3.0, 4.0)]
    result = jackknife_ratio(blocks, POLICY)
    deleted = [(10 - i) / 30 for i in (1.0, 2.0, 3.0, 4.0)]
    mean = sum(deleted) / 4
    expected = 3 / 4 * sum((x - mean) ** 2 for x in deleted)
    assert result["standard_error"] ** 2 == pytest.approx(expected)


@pytest.mark.parametrize(
    "blocks",
    [
        [(0.0, 0.0, 20)] * 4,
        [(1.0, 10.0, 20), (1.0, 0.0, 20), (1.0, 0.0, 20), (1.0, 0.0, 20)],
        [(1.0, 10.0, 20), (1.0, -10.0, 20), (1.0, 10.0, 20), (1.0, -9.0, 20)],
        [(1.0, 10.0, 1)] * 2,
    ],
)
def test_unstable_denominator_or_sparse_data_is_not_numeric_zero(
    blocks: list[tuple[float, float, int]],
) -> None:
    result = jackknife_ratio(blocks, POLICY)
    assert result["ratio"] is None and result["interval"] is None and result["reason"]


def test_signed_ranges_and_exact_zero_are_preserved() -> None:
    negative = jackknife_ratio([(-1.0, 10.0, 20)] * 4, POLICY)
    assert negative["ratio"] == pytest.approx(-0.1) and negative["interval"][1] < 0
    zero = jackknife_ratio([(0.0, 10.0, 20)] * 4, POLICY)
    assert zero["interval"] == [0.0, 0.0] and zero["reason"] is None


@pytest.mark.privacy
def test_methods_report_sensitivity_provenance_and_limited_card_faces(pack: KnowledgePack) -> None:
    table, panel = synthetic()
    results = compute_archaic(table, panel, settings=POLICY)
    assert set(results) == archaic.SOURCES and observations(pack) == {}
    assert lint_directory(pack.source_dir, resolve_variants=False).ok
    for definition in pack.cards:
        assert definition.computation is not None
        result = results[definition.computation]
        record = result.as_dict()
        assert record["status"] == "computed"
        archaic.validate_result(record, definition.computation, "computed")
        intervals = [d["interval"] for d in record["diagnostics"]]
        assert record["range"] == [min(i[0] for i in intervals), max(i[1] for i in intervals)]
        card = assemble_archaic_card(definition, result)
        assert card.status is MatchStatus.COMPUTED and card.has_interpretation
        assert "model range" in card.summary and "not a measured" in card.summary
        assert "uncalibrated" in card.summary
        assert card.computation is not None
        assert card.computation["reliability"]["tier"] == "limited"
        assert card.observation is None and card.confidence is None
        assert record["reference"]["build"] == "GRCh37"
        assert "data" not in repr(result) and "frequencies" not in repr(panel)
    neand = results["neanderthal_f4"].as_dict()
    filtered = {d["filter"]: d for d in neand["diagnostics"]}
    assert filtered["denisovan_ancestral"]["n_informative"] < filtered["all"]["n_informative"]
    assert filtered["transversions"]["n_informative"] < filtered["all"]["n_informative"]
    # Population expectation from the invented mixture (0.9 Mbuti, 0.07
    # Vindija, 0.03 Denisova): (0.16 - 0.1)/(1 - 0.1) on ancestral-D sites.
    expected = (0.16 - 0.1) / 0.9
    lower, upper = filtered["denisovan_ancestral"]["interval"]
    assert lower < expected < upper


def test_allele_order_swapping_preserves_result() -> None:
    table, panel = synthetic()
    swapped = GenotypeTable(
        table.frame.with_columns(pl.col("a2").alias("a1"), pl.col("a1").alias("a2")),
        vendor="synthetic",
    )
    assert compute_archaic(table, panel, settings=POLICY) == compute_archaic(
        swapped, panel, settings=POLICY
    )
    reverse = replace(
        panel,
        sites=tuple((c, p, b, a) for c, p, a, b in panel.sites),
        frequencies={
            k: tuple(None if x is None else 1 - x for x in values)
            for k, values in panel.frequencies.items()
        },
    )
    original = compute_archaic(table, panel, settings=POLICY)
    flipped = compute_archaic(table, reverse, settings=POLICY)
    for source in archaic.SOURCES:
        assert flipped[source].data["range"] == pytest.approx(original[source].data["range"])


def test_harmonization_counts_missing_incompatible_and_duplicate_without_strand_guessing() -> None:
    table, panel = synthetic()
    rows = table.frame.rows(named=True)
    rows[0].update(a1=None, a2=None, genotype=None, call_status="no_call")
    rows[1].update(a1="T", a2="T", genotype="TT")
    rows.append(dict(rows[2]))
    changed = GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")
    result = compute_archaic(changed, panel, settings=POLICY)["neanderthal_f4"].data
    assert result["n_missing_calls"] == 1
    assert result["n_incompatible_calls"] == 1
    assert result["n_duplicate_sites"] == 1
    assert result["n_shared_reference_sites"] == len(panel.sites) - 1


def test_primary_failure_never_replaced_by_unrestricted_sharing(pack: KnowledgePack) -> None:
    table, panel = synthetic()
    freqs = dict(panel.frequencies)
    freqs["denisova"] = tuple(1.0 for _ in panel.sites)
    result = compute_archaic(table, replace(panel, frequencies=freqs), settings=POLICY)[
        "neanderthal_f4"
    ]
    assert result.data["range"] is None and result.data["status"] == "insufficient_coverage"
    assert result.data["diagnostics"][0]["interval"] is not None
    definition = next(c for c in pack.cards if c.computation == "neanderthal_f4")
    card = assemble_archaic_card(definition, result)
    assert not card.has_interpretation and "unavailable" in card.summary
    assert card.computation is not None and card.computation["reliability"]["tier"] is None
    archaic.validate_result(result.data, "neanderthal_f4", "insufficient_coverage")


def test_pipeline_missing_dependencies_keep_both_cards_visible(pack: KnowledgePack) -> None:
    result = analyse(EXPORT, knowledge_dir=pack.source_dir)
    assert len(result.cards) == 2
    assert all(
        c.status is MatchStatus.NOT_RUN and "fetch --only aadr" in c.summary for c in result.cards
    )


def test_stage_computes_once_and_roh_does_not_consume_archaic_cards(
    pack: KnowledgePack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, panel = synthetic()
    cards = assemble_pack(pack, match_pack(pack, table))
    assert infer_roh_cards(cards, table) is cards
    paths = tuple(tmp_path / f"reference.{ext}" for ext in ("snp", "ind", "geno"))
    for path in paths:
        path.touch()
    monkeypatch.setattr(archaic, "reference_paths", lambda: paths)
    monkeypatch.setattr(archaic, "load_panel", lambda *args, **kwargs: panel)
    calls = []
    original = compute_archaic

    def compute(table: GenotypeTable, panel: ArchaicPanel, **kwargs: Any) -> Any:
        calls.append(1)
        return original(table, panel, settings=POLICY)

    monkeypatch.setattr(archaic, "compute_archaic", compute)
    result = archaic.infer_archaic_cards(cards, table)
    assert calls == [1] and all(c.status is MatchStatus.COMPUTED for c in result)


def test_saved_cards_cli_http_and_older_roh_bundles(
    pack: KnowledgePack, sample_qc: QCReport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, panel = synthetic()
    results = compute_archaic(table, panel, settings=POLICY)
    cards = tuple(assemble_archaic_card(c, results[str(c.computation)]) for c in pack.cards)
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    path = write_bundle(
        qc=sample_qc,
        cards=cards,
        pack=pack,
        ancestry=AncestryContext.not_run("Synthetic test"),
        lock_path=tmp_path / "absent",
        tools_root=tmp_path / "tools",
    )
    bundle = read_bundle(path)
    assert bundle.format_version == BUNDLE_FORMAT_VERSION
    assert [c.computation for c in bundle.cards] == [c.computation for c in cards]
    response = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert response.exit_code == 0
    assert [c["computation"] for c in json.loads(response.stdout)["cards"]] == [
        c.computation for c in cards
    ]
    with TestClient(
        create_app(WebConfig(runs_root=path.parent)), base_url="http://127.0.0.1:8765"
    ) as client:
        grid = client.get(f"/runs/{path.name}")
        assert grid.status_code == 200 and "Limited" in grid.text
        for card in cards:
            detail = client.get(f"/runs/{path.name}/cards/{card.card_id}")
            assert detail.status_code == 200
            for text in (
                "Filter sensitivity",
                "Parameters and reference provenance",
                "fixed-seed-v1",
                "SHA-256",
                "929",
                "uncalibrated",
                "10.1126/science.aay5012",
            ):
                assert text in detail.text
            assert "Observed F_ROH" not in detail.text and "Allele frequency" not in detail.text
    shutil.rmtree(pack.source_dir)
    assert read_bundle(path).cards[0].summary == cards[0].summary


@pytest.mark.parametrize(
    "edit",
    [
        "range",
        "nan",
        "se",
        "source",
        "source_type",
        "primary",
        "filter",
        "filter_type",
        "coverage",
        "tier",
        "missing",
        "digest",
        "unavailable",
        "reference_ids",
        "population_ids",
        "reference_text",
        "warnings_empty",
        "settings_missing",
    ],
)
def test_corrupt_numeric_ranges_are_refused(pack: KnowledgePack, edit: str) -> None:
    table, panel = synthetic()
    card = next(c for c in pack.cards if c.computation == "neanderthal_f4")
    payload = copy.deepcopy(
        _card_payload(
            assemble_archaic_card(
                card, compute_archaic(table, panel, settings=POLICY)["neanderthal_f4"]
            )
        )
    )
    raw = payload["computation"]["result"]
    if edit == "range":
        raw["range"][0] += 0.1
    elif edit == "nan":
        raw["diagnostics"][0]["ratio"] = float("nan")
    elif edit == "se":
        raw["diagnostics"][0]["standard_error"] = -1
    elif edit == "source":
        raw["source"] = "denisovan_f4"
    elif edit == "source_type":
        payload["computation"]["source"] = []
    elif edit == "primary":
        raw["primary_filter"] = "all"
    elif edit == "filter":
        raw["diagnostics"][1]["filter"] = "all"
    elif edit == "filter_type":
        raw["diagnostics"][1]["filter"] = []
    elif edit == "coverage":
        raw["diagnostics"][0]["n_blocks"] = 1
    elif edit == "tier":
        payload["computation"]["reliability"]["tier"] = "strong"
    elif edit == "missing":
        del raw["diagnostics"]
    elif edit == "digest":
        raw["reference"]["input_sha256"] = {}
    elif edit == "unavailable":
        raw["status"] = payload["status"] = payload["computation"]["status"] = (
            "insufficient_coverage"
        )
    elif edit == "reference_ids":
        del raw["reference"]["archaic_ids"]
    elif edit == "population_ids":
        raw["reference"]["population_ids"]["han"] = [False]
    elif edit == "reference_text":
        raw["reference"]["version"] = None
    elif edit == "warnings_empty":
        raw["warnings"] = []
    elif edit == "settings_missing":
        del raw["settings"]["block_bp"]
    with pytest.raises(BundleError):
        _stored_card(payload, "synthetic corrupt archaic card")


def test_serialized_archaic_measurement_is_an_independent_snapshot() -> None:
    table, panel = synthetic()
    results = compute_archaic(table, panel, settings=POLICY)
    result = results["neanderthal_f4"]
    serialized = result.as_dict()
    serialized["reference"]["population_ids"]["han"].clear()
    serialized["diagnostics"].clear()
    assert result.data["diagnostics"]
    assert result.data["reference"]["population_ids"]["han"]
    assert results["denisovan_f4"].data["reference"]["population_ids"]["han"]
    assert panel.provenance["population_ids"]["han"]


def write_panel(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Tiny fixed-seed reference archive in the measured TGENO layout."""
    paths = tuple(tmp_path / f"test.{ext}" for ext in ("snp", "ind", "geno"))
    snp, ind, geno = paths
    ids = [*archaic.REFERENCE_IDS.values(), *(f"HGDP{i:05d}.DG" for i in range(10))]
    ind.write_text(
        "\n".join(
            f"{sid} F {('Mbuti' if i < 9 else 'Han') if i >= 4 else 'archaic'}"
            for i, sid in enumerate(ids)
        )
        + "\n",
        encoding="utf-8",
    )
    snps = [f"rs{30_000_000 + i} 1 0 {1 + i * 100} A C" for i in range(8)]
    snp.write_text("\n".join(snps) + "\n", encoding="utf-8")
    rng = random.Random(6342026)
    codes = [[rng.choices([0, 1, 2], weights=[0.3, 0.4, 0.3])[0] for _ in range(8)] for _ in ids]
    codes[4][0] = 3
    header = f"TGENO {len(ids)} 8 {hasharr(ids):08x} {hasharr(row.split()[0] for row in snps):08x}".encode().ljust(
        48, b"\0"
    )
    records = bytes(
        sum(row[j + k] << (6 - 2 * k) for k in range(4)) for row in codes for j in (0, 4)
    )
    geno.write_bytes(header + records)
    return snp, ind, geno


def test_reference_loader_checks_hashes_population_missingness_and_identity(tmp_path: Path) -> None:
    paths = write_panel(tmp_path)
    panel = load_panel(paths, wanted=[("1", 1), ("1", 101)], settings=POLICY)
    assert len(panel.sites) == 2 and len(panel.provenance["population_ids"]["mbuti"]) == 5
    assert len(panel.provenance["input_sha256"]) == 3
    strict = load_panel(
        paths, wanted=[("1", 1)], settings=replace(POLICY, min_population_calls=1.0)
    )
    assert strict.frequencies["mbuti"] == (None,)
    assert panel.frequencies["mbuti"][0] is not None
    paths[0].write_text(paths[0].read_text().replace("rs30000000", "rs40000000"))
    with pytest.raises(EigenstratError, match="hash"):
        load_panel(paths, wanted=[], settings=POLICY)


def test_reference_loader_refuses_missing_archaic_and_malformed_stage(
    tmp_path: Path, pack: KnowledgePack, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = write_panel(tmp_path)
    paths[1].write_text(paths[1].read_text().replace("Vindija.DG", "Denisova11.SG"))
    with pytest.raises(ArchaicError, match="exactly once"):
        load_panel(paths, wanted=[], settings=POLICY)
    monkeypatch.setattr(archaic, "reference_paths", lambda: paths)
    table = ingest(EXPORT).table
    with pytest.raises(ArchaicError):
        archaic.infer_archaic_cards(assemble_pack(pack, match_pack(pack, table)), table)
    response = CliRunner().invoke(
        app, ["run", "--input", str(EXPORT), "--knowledge", str(pack.source_dir), "--json"]
    )
    assert response.exit_code == 2
    error = json.loads(response.stdout)
    assert error["ok"] is False and error["error"]["kind"] == "structure"


@pytest.mark.parametrize(
    "edit",
    [
        {"block_bp": 0},
        {"min_blocks": 1},
        {"min_population_calls": float("nan")},
        {"min_chromosomes": True},
        {"min_informative": True},
    ],
)
def test_invalid_settings_fail_without_echoing_calls(edit: dict[str, Any]) -> None:
    with pytest.raises(ArchaicError):
        ArchaicSettings(**edit)
