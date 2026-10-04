"""Computed-card states, native-engine wiring, immutable storage and UI/CLI parity."""

from __future__ import annotations

import copy
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine.card_lint import lint_directory
from genetics.engine.cards import Card, CardError, KnowledgePack
from genetics.engine.evidence import AssembledCard
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.external.plink2 import Plink2, Plink2NotFoundError, Plink2VersionError
from genetics.external.plink19 import Plink19
from genetics.ingest import ingest
from genetics.ingest.schema import GenotypeTable
from genetics.paths import repo_root
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    BundleError,
    _stored_card,
    read_bundle,
    write_bundle,
)
from genetics.run.pipeline import analyse, observations, save
from genetics.structure import interpretation
from genetics.structure.interpretation import assemble_roh_card, infer_roh_cards
from genetics.structure.roh import Interval, ReferenceInput, RohResult, RohSettings, WindowSupport
from genetics.web import WebConfig, create_app
from genetics.web.views import CardView

EXPORT = Path(__file__).parents[1] / "fixtures" / "synthetic" / "ancestry_v2_male.txt"
NO_ANCESTRY = AncestryContext.not_run("synthetic test: ancestry not run")


@pytest.fixture
def pack(tmp_path: Path) -> KnowledgePack:
    root = tmp_path / "knowledge" / "structure"
    root.mkdir(parents=True)
    shutil.copyfile(
        repo_root() / "knowledge/structure/autozygosity.yaml", root / "autozygosity.yaml"
    )
    return KnowledgePack.load(root.parent)


@pytest.fixture
def definition(pack: KnowledgePack) -> Card:
    return pack.cards[0]


def measured(*, zero: bool = False, unsupported: bool = False) -> RohResult:
    # Invented assay spans, not a subset of any person's measurements.
    first = Interval("1", 1, 10_000_000, 120)
    second = Interval("2", 1, 10_000_000, 120)
    return RohResult(
        () if zero else (Interval("1", 1, 6_000_000, 70),),
        (first, second),
        250,
        240,
        240,
        120 if unsupported else 0,
        RohSettings(),
        (
            {
                "population": "pooled 1000G phase 3 (not ancestry-matched)",
                "version": "synthetic-v1",
                "status": "analyzed",
                "input_sha256": {"vcf": "a" * 64},
            },
        ),
        "synthetic plink2",
        "synthetic plink19",
        (WindowSupport(first, 60, 60), WindowSupport(second, 60, 0 if unsupported else 60)),
    )


def test_definition_is_linted_without_a_variant_or_authored_confidence(pack: KnowledgePack) -> None:
    assert observations(pack) == {}
    report = lint_directory(pack.source_dir, resolve_variants=False)
    assert report.ok and report.rendered_templates == 2
    match = match_pack(pack, ingest(EXPORT).table)[0]
    assert match.status is MatchStatus.NOT_RUN


@pytest.mark.parametrize(
    "edit",
    [
        {"citations": []},
        {"computation": "invented_method"},
        {"confidence": "strong"},
        {"summary": "{genotype}"},
        {"gene": "GENE"},
        {"section": "ancestry"},
        {"method_evidence": {"sample_sizes": [True]}},
    ],
)
def test_computed_schema_refuses_invalid_claims(pack: KnowledgePack, edit: dict[str, Any]) -> None:
    path = pack.source_dir / "structure/autozygosity.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["cards"][0]
    raw.update(edit)
    with pytest.raises(CardError):
        Card.parse(raw, "synthetic schema test")


@pytest.mark.parametrize("population", [None, False, {}, " "])
def test_computed_populations_must_be_nonempty_text(pack: KnowledgePack, population: Any) -> None:
    path = pack.source_dir / "structure/autozygosity.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["cards"][0]
    raw["method_evidence"]["populations"][0] = population
    with pytest.raises(CardError):
        Card.parse(raw, "synthetic method evidence")


@pytest.mark.parametrize(
    "edit",
    [
        "method_null",
        "method_population",
        "method_size",
        "match_genotype",
        "observation",
        "reason",
        "segment_reversed",
        "segment_chrom",
        "segments_missing",
        "interval_length",
        "window_shape",
        "window_count",
        "settings",
        "unavailable_tier",
        "overlap",
        "window_interval",
        "marker_count",
        "reference_digest",
        "tool_version",
        "warnings",
    ],
)
def test_saved_roh_contract_rejects_inconsistent_records(definition: Card, edit: str) -> None:
    from genetics.run.bundle import _card_payload

    data = copy.deepcopy(_card_payload(assemble_roh_card(definition, measured())))
    computation = data["computation"]
    result = computation["result"]
    if edit == "method_null":
        computation["method_evidence"] = None
    elif edit == "method_population":
        computation["method_evidence"]["populations"][0] = False
    elif edit == "method_size":
        computation["method_evidence"]["sample_sizes"][0] = True
    elif edit == "match_genotype":
        data["match"]["genotype"] = "invented"
    elif edit == "observation":
        data["observation"] = {}
    elif edit == "reason":
        computation["reason"] = "A measurement cannot also be not run"
    elif edit == "segment_reversed":
        result["segments"][0]["start"] = 7_000_000
    elif edit == "segment_chrom":
        result["segments"][0]["chrom"] = "X"
    elif edit == "segments_missing":
        result["segments"] = []
    elif edit == "interval_length":
        result["assayed_intervals"][0]["end"] += 1
    elif edit == "window_shape":
        result["window_support"][0] = {}
    elif edit == "window_count":
        result["window_support"][0]["observed_windows"] = 61
    elif edit == "settings":
        result["settings"]["window_snps"] = 0
    elif edit == "unavailable_tier":
        result.update(
            status="insufficient_calls",
            segments=[],
            total_roh_bp=0,
            roh_count=0,
            longest_roh_bp=0,
            f_roh=None,
        )
        for window in result["window_support"]:
            window["observed_windows"] = 0
        data["status"] = computation["status"] = "insufficient_calls"
        computation["reliability"]["tier"] = "strong"
    elif edit == "overlap":
        result["segments"].append(copy.deepcopy(result["segments"][0]))
    elif edit == "window_interval":
        result["window_support"][0]["interval"]["end"] += 1
    elif edit == "marker_count":
        result["n_missing_calls"] = 241
    elif edit == "reference_digest":
        result["references"][0]["input_sha256"] = {"vcf": "not a digest"}
    elif edit == "tool_version":
        result["tools"]["plink19"] = None
    elif edit == "warnings":
        result["warnings"] = []
    with pytest.raises(BundleError):
        _stored_card(data, "synthetic damaged measurement")


def test_serialized_roh_provenance_is_an_independent_snapshot() -> None:
    result = measured()
    serialized = result.as_dict()
    serialized["references"][0]["input_sha256"].clear()
    assert result.provenance[0]["input_sha256"] == {"vcf": "a" * 64}


def test_measured_card_states_the_assay_fraction_and_limits(definition: Card) -> None:
    card = assemble_roh_card(definition, measured())
    assert card.status is MatchStatus.COMPUTED and card.has_interpretation
    assert "30.00% of 20.00 Mb" in card.summary
    assert "6.00 Mb" in card.summary and "Partial autosomal coverage" in card.summary
    assert card.computation is not None
    assert card.computation["reliability"]["tier"] == "limited"
    assert not card.computation["reliability"]["inputs"]["chip_population_calibrated"]
    assert card.observation is None and card.confidence is None and card.match.genotype is None
    assert "parental relationship" in card.detail


def test_supported_zero_and_underestimation_remain_visible(definition: Card) -> None:
    card = assemble_roh_card(definition, measured(zero=True, unsupported=True))
    assert card.status is MatchStatus.COMPUTED
    assert "0.00%" in card.summary and "No run met this policy" in card.summary
    assert "Unsupported assay spans" in card.summary and "Missing calls" in card.summary
    assert card.computation is not None
    assert card.computation["reliability"]["inputs"]["unsupported_intervals"] == 1


@pytest.mark.parametrize("mode", ["coverage", "calls", "not_run"])
def test_unavailable_is_never_a_numeric_zero(definition: Card, mode: str) -> None:
    result = measured(zero=True)
    if mode == "coverage":
        result = replace(result, assayed_intervals=(), window_support=())
        expected = MatchStatus.INSUFFICIENT_COVERAGE
    elif mode == "calls":
        result = replace(
            result,
            window_support=tuple(
                replace(window, observed_windows=0) for window in result.window_support
            ),
        )
        expected = MatchStatus.INSUFFICIENT_CALLS
    else:
        card = assemble_roh_card(definition, None, reason="Synthetic dependencies absent")
        assert card.status is MatchStatus.NOT_RUN and "absent" in card.summary
        assert card.computation is not None and card.computation["result"] is None
        return
    card = assemble_roh_card(definition, result)
    assert card.status is expected and not card.has_interpretation
    assert "unavailable" in card.summary
    assert card.computation is not None
    assert card.computation["result"]["f_roh"] is None
    assert card.computation["reliability"]["tier"] is None


@pytest.mark.parametrize("mode", ["computed", "zero", "unsupported", "coverage", "calls"])
def test_saved_roh_validation_preserves_all_legitimate_states(definition: Card, mode: str) -> None:
    from genetics.run.bundle import _card_payload

    result = measured(zero=mode in {"zero", "coverage", "calls"}, unsupported=mode == "unsupported")
    if mode == "coverage":
        result = replace(result, assayed_intervals=(), window_support=())
    elif mode == "calls":
        result = replace(
            result,
            window_support=tuple(replace(w, observed_windows=0) for w in result.window_support),
        )
    payload = _card_payload(assemble_roh_card(definition, result))
    assert (
        _stored_card(payload, "synthetic saved measurement").computation == payload["computation"]
    )


def test_stage_runs_native_engine_once_and_preserves_result(
    pack: KnowledgePack,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(interpretation, "references_dir", lambda: tmp_path / "references")
    refs = interpretation.default_references()
    for ref in refs:
        # Session-scoped isolated reference tree; this test never reads real payloads.
        ref.path.parent.mkdir(parents=True, exist_ok=True)
        ref.path.touch()
    monkeypatch.setattr(Plink2, "discover", lambda: Plink2(tmp_path / "tool2", "synthetic2"))
    monkeypatch.setattr(Plink19, "discover", lambda: Plink19(tmp_path / "tool19", "synthetic19"))
    calls: list[GenotypeTable] = []

    def engine(table: GenotypeTable, references: object, **kwargs: Any) -> RohResult:
        calls.append(table)
        assert references == refs and kwargs["plink19"].version == "synthetic19"
        return measured()

    monkeypatch.setattr(interpretation, "compute_roh", engine)
    analysis = analyse(EXPORT, knowledge_dir=pack.source_dir)
    assert len(calls) == 1
    assert analysis.cards[0].computation is not None
    assert analysis.cards[0].computation["result"] == measured().as_dict()
    assert analysis.status_counts[MatchStatus.COMPUTED] == 1
    assert analysis.tier_counts[next(t for t in analysis.tier_counts if t.value == "limited")] == 1


@pytest.mark.parametrize("missing", [True, False])
def test_missing_tool_degrades_but_wrong_version_fails(
    definition: Card,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing: bool,
) -> None:
    refs = (ReferenceInput(tmp_path / "synthetic.vcf", "v1", "synthetic"),)
    refs[0].path.touch()
    monkeypatch.setattr(interpretation, "default_references", lambda: refs)

    def discover() -> Plink2:
        if missing:
            raise Plink2NotFoundError("Synthetic tool missing; install pinned tool")
        raise Plink2VersionError("Synthetic wrong version")

    monkeypatch.setattr(Plink2, "discover", discover)
    cards = (assemble_roh_card(definition, None),)
    if missing:
        result = infer_roh_cards(cards, ingest(EXPORT).table)
        assert result[0].status is MatchStatus.NOT_RUN
        assert "install pinned" in result[0].summary
    else:
        with pytest.raises(Plink2VersionError):
            infer_roh_cards(cards, ingest(EXPORT).table)


def test_bundle_cli_and_http_share_the_same_computation(
    definition: Card,
    pack: KnowledgePack,
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    card = assemble_roh_card(definition, measured(unsupported=True))
    path = write_bundle(
        qc=sample_qc,
        cards=(card,),
        pack=pack,
        ancestry=NO_ANCESTRY,
        lock_path=tmp_path / "absent",
        tools_root=tmp_path / "tools",
    )
    bundle = read_bundle(path)
    assert bundle.format_version == BUNDLE_FORMAT_VERSION
    assert bundle.cards[0].computation == card.computation
    # This ROH record existed in format 4; a newer reader must still accept it.
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert read_bundle(path).cards[0].computation == card.computation
    assert bundle.cards[0].confidence_tier == "limited"
    invocation = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert invocation.exit_code == 0
    assert json.loads(invocation.stdout)["cards"][0]["computation"] == card.computation
    with TestClient(
        create_app(WebConfig(runs_root=path.parent)), base_url="http://127.0.0.1:8765"
    ) as client:
        grid = client.get(f"/runs/{path.name}")
        assert grid.status_code == 200 and "Limited" in grid.text
        response = client.get(f"/runs/{path.name}/cards/{card.card_id}")
        assert response.status_code == 200
        for text in (
            "6000000 bp",
            "20000000 bp",
            "Observed F_ROH",
            "2618",
            "1839",
            "10.1016/j.ajhg.2008.08.007",
        ):
            assert text in response.text
        assert "Allele frequency" not in response.text and "Effect size</h3>" not in response.text
    view = CardView.of(bundle.cards[0], format_version=BUNDLE_FORMAT_VERSION)
    assert view.is_interpreted and view.frequency_absence is None
    # Saved interpretations remain independent of the current knowledge pack.
    shutil.rmtree(pack.source_dir)
    assert read_bundle(path).cards[0].summary == card.summary


def test_not_run_card_survives_pipeline_save(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(interpretation, "references_dir", lambda: tmp_path / "missing")
    analysis = analyse(EXPORT, knowledge_dir=pack.source_dir)
    assert analysis.cards[0].status is MatchStatus.NOT_RUN
    path = save(
        analysis,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "absent",
        tools_root=tmp_path / "tools",
    )
    assert read_bundle(path).cards[0].computation is not None


@pytest.mark.parametrize(
    "edit",
    [
        "missing",
        "status",
        "numeric_unavailable",
        "tier",
        "boolean_fraction",
        "nan_fraction",
        "wrong_fraction",
        "missing_metric",
    ],
)
def test_corrupted_computation_is_refused(definition: Card, tmp_path: Path, edit: str) -> None:
    from genetics.run.bundle import _card_payload

    data = copy.deepcopy(_card_payload(assemble_roh_card(definition, measured())))
    if edit == "missing":
        del data["computation"]
    elif edit == "status":
        data["computation"]["status"] = "not_run"
    elif edit == "numeric_unavailable":
        data["status"] = data["computation"]["status"] = "insufficient_calls"
        data["computation"]["result"]["status"] = "insufficient_calls"
        data["computation"]["reliability"]["tier"] = None
    elif edit == "tier":
        data["computation"]["reliability"]["tier"] = "strong"
    elif edit == "missing_metric":
        del data["computation"]["result"]["longest_roh_bp"]
    else:
        data["computation"]["result"]["f_roh"] = {
            "boolean_fraction": True,
            "nan_fraction": float("nan"),
            "wrong_fraction": 0.5,
        }[edit]
    with pytest.raises(BundleError):
        _stored_card(data, "synthetic corrupted card")


def test_old_card_without_computation_reads_as_not_recorded(
    sample_cards: tuple[AssembledCard, ...],
) -> None:
    from genetics.run.bundle import _card_payload

    data = _card_payload(sample_cards[0])
    del data["computation"]
    assert _stored_card(data, "pre-M6.2 card").computation is None


@pytest.mark.privacy
def test_aggregate_results_cannot_print_themselves(definition: Card) -> None:
    result = measured()
    assembled = assemble_roh_card(definition, result)
    assert "6000000" not in repr(result) and "30.00%" not in repr(assembled)
