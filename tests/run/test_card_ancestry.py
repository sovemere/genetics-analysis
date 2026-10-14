"""M9.13: fabricated placement/calls, selected evidence and frozen interface parity."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.card_match import sample_context, validate_card
from genetics.ancestry.context import AncestryContext, PopulationResult
from genetics.ancestry.populations import Placement, PopulationFit
from genetics.cli.main import app
from genetics.engine.cards import Ancestry, KnowledgePack, Outcome
from genetics.engine.confidence import ConfidenceTier
from genetics.engine.evidence import AssembledCard, ObservationEvidence, assemble_card
from genetics.pgs.runner import PolygenicStage
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    CARDS_NAME,
    MANIFEST_NAME,
    BundleError,
    _card_payload,
    read_bundle,
    write_bundle,
)
from genetics.run.pipeline import analyse
from genetics.web import WebConfig, create_app


def placement(code: str = "EUR", *, declined: bool = False) -> PopulationResult:
    return PopulationResult(
        placement=Placement(
            sample_id="SAMPLE",
            coordinates=(0.1, 0.2),
            fits=(PopulationFit("SYNTHETIC", code, 30, 1.0, 1.0, 0.5),),
            population=None if declined else "SYNTHETIC",
            declined_because="Synthetic panel does not fit." if declined else "",
            decline_threshold=2.0,
            coverage=1.0,
            n_scored_markers=100,
            n_reference_markers=100,
            panel_coverage=None,
            labels_source="synthetic.panel",
            n_panel_samples=30,
        ),
        reference="synthetic-pca",
        reference_markers=100,
        n_components=2,
    )


def assembled(
    base: AssembledCard, sample: dict[str, Any], study: tuple[Ancestry, ...]
) -> AssembledCard:
    assert base.card.evidence is not None and base.observation is not None
    card = replace(base.card, evidence=replace(base.card.evidence, ancestry=study))
    return assemble_card(card, base.match, replace(base.observation, ancestry_context=sample))


@pytest.mark.parametrize("code", ["AFR", "AMR", "EAS", "EUR", "SAS"])
@pytest.mark.parametrize(
    "relation", ["matched", "mismatched", "unknown", "multi", "explicit_multi"]
)
def test_study_membership_is_explicit_not_a_universal_multi_claim(
    sample_cards: tuple[AssembledCard, ...],
    code: str,
    relation: str,
) -> None:
    sample = sample_context(placement(code).to_dict())
    other = "AFR" if code != "AFR" else "EUR"
    study = {
        "matched": (Ancestry(code),),
        "mismatched": (Ancestry(other),),
        "unknown": (Ancestry.UNKNOWN,),
        "multi": (Ancestry.MULTI,),
        "explicit_multi": (Ancestry.MULTI, Ancestry(code)),
    }[relation]
    result = assembled(sample_cards[0], sample, study)
    expected = {
        "matched": ("matched", 1.0),
        "explicit_multi": ("matched", 1.0),
        "mismatched": ("mismatched", 0.0),
        "unknown": ("unknown_study_population", None),
        "multi": ("unspecified_multi", None),
    }[relation]
    assert result.ancestry_comparison is not None and result.confidence is not None
    assert (
        result.ancestry_comparison["state"],
        result.confidence.inputs.ancestry_match,
    ) == expected
    assert result.ancestry_comparison["text"] in result.summary
    assert result.ancestry_comparison["text"] in result.detail
    validate_card(_card_payload(result), sample)


@pytest.mark.parametrize("gate_declines", [False, True])
def test_either_panel_decline_is_positive_unrepresented_state(
    sample_cards: tuple[AssembledCard, ...],
    gate_declines: bool,
) -> None:
    sample = sample_context(
        placement(declined=not gate_declines).to_dict(),
        placement(declined=True).to_dict() if gate_declines else None,
    )
    result = assembled(sample_cards[0], sample, (Ancestry.EUR,))
    assert result.ancestry_comparison and result.ancestry_comparison["state"] == "declined"
    assert result.confidence and result.confidence.inputs.ancestry_match == 0.0
    validate_card(_card_payload(result), sample)


def test_not_run_keeps_unknown_without_using_aadr_country(
    sample_cards: tuple[AssembledCard, ...],
) -> None:
    sample = sample_context(
        PopulationResult(not_run_reason="Synthetic missing reference.").to_dict(),
        {"status": "placed", "region": "United Kingdom", "reason": ""},
    )
    result = assembled(sample_cards[0], sample, (Ancestry.EUR,))
    assert result.confidence and result.confidence.inputs.ancestry_match is None
    assert result.ancestry_comparison and result.ancestry_comparison["state"] == "not_run"


@pytest.mark.parametrize("null", [False, True])
def test_selected_outcome_controls_population_and_null_is_preserved(
    sample_cards: tuple[AssembledCard, ...],
    null: bool,
) -> None:
    base = sample_cards[0]
    assert base.card.evidence is not None and base.observation is not None
    selected = None if null else replace(base.card.evidence, ancestry=(Ancestry.EAS,))
    outcome = Outcome(
        "{ancestry}", "Selected evidence: {ancestry}", evidence=selected, overrides_evidence=True
    )
    sample = sample_context(placement("EAS").to_dict())
    result = assemble_card(
        base.card,
        replace(base.match, outcome=outcome),
        replace(base.observation, ancestry_context=sample),
    )
    assert result.card.evidence == selected
    assert result.ancestry_comparison is not None
    assert result.ancestry_comparison["state"] == ("no_applicable_evidence" if null else "matched")
    assert result.summary.count(result.ancestry_comparison["text"]) == 1
    assert "{ancestry}" not in result.detail
    validate_card(_card_payload(result), sample)


@pytest.mark.parametrize(
    "rare,quality,tier",
    [
        (True, None, ConfidenceTier.LIKELY_ARTIFACT),
        (False, 0.1, ConfidenceTier.LIKELY_ARTIFACT),
        (False, 0.5, ConfidenceTier.LIMITED),
    ],
)
def test_ancestry_match_never_rescues_rarity_or_quality(
    sample_cards: tuple[AssembledCard, ...],
    rare: bool,
    quality: float | None,
    tier: ConfidenceTier,
) -> None:
    from genetics.engine.confidence import CallSource
    from genetics.engine.evidence import PopulationFrequency

    base = sample_cards[0]
    assert base.observation is not None
    sample = sample_context(placement().to_dict())
    observed = ObservationEvidence(
        call_source=CallSource.DIRECT if quality is None else CallSource.IMPUTED,
        frequencies=(
            PopulationFrequency("A", 0.000001 if rare else 0.2, "synthetic", "synthetic"),
        ),
        imputation_quality=quality,
        ancestry_context=sample,
    )
    result = assemble_card(base.card, base.match, observed)
    assert result.confidence and result.confidence.tier is tier
    assert result.has_interpretation
    validate_card(_card_payload(result), sample)


@pytest.mark.parametrize(
    "field",
    ["state", "study", "policy", "sample", "numeric", "confidence", "face", "detail", "removed"],
)
def test_digest_consistent_ancestry_corruption_is_refused(
    sample_cards: tuple[AssembledCard, ...],
    sample_pack: KnowledgePack,
    sample_qc: QCReport,
    tmp_path: Path,
    field: str,
) -> None:
    reference = placement()
    context = replace(
        AncestryContext.not_run("Synthetic other stages."), reference_population=reference
    )
    sample = sample_context(reference.to_dict(), context.population.to_dict())
    result = assembled(sample_cards[0], sample, (Ancestry.EUR,))
    directory = write_bundle(
        qc=sample_qc,
        cards=(result,),
        pack=sample_pack,
        ancestry=context,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "missing.lock",
        tools_root=tmp_path / "tools",
    )
    payload = json.loads((directory / CARDS_NAME).read_text())
    card = payload["cards"][0]
    comparison = card["ancestry_comparison"]
    if field == "state":
        comparison["state"] = "mismatched"
    elif field == "study":
        comparison["study"] = ["AFR"]
    elif field == "policy":
        comparison["confidence_policy"] = "prs"
    elif field == "sample":
        comparison["sample"]["super_population"] = "AFR"
    elif field == "numeric":
        card["observation"]["ancestry_match"] = 0.0
    elif field == "confidence":
        card["confidence"]["score"] = 1.0
    elif field in {"face", "detail"}:
        card["summary" if field == "face" else "detail"] = "Missing comparison."
    else:
        card["ancestry_comparison"] = None
    text = json.dumps(payload)
    (directory / CARDS_NAME).write_text(text, encoding="utf-8")
    manifest = json.loads((directory / MANIFEST_NAME).read_text())
    manifest["files"][CARDS_NAME] = hashlib.sha256(text.encode()).hexdigest()
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="ancestry"):
        read_bundle(directory)


def test_frozen_cli_dashboard_and_historical_format(
    sample_cards: tuple[AssembledCard, ...],
    sample_pack: KnowledgePack,
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = placement("EAS")
    context = replace(
        AncestryContext.not_run("Synthetic other stages."), reference_population=reference
    )
    sample = sample_context(reference.to_dict(), context.population.to_dict())
    result = assembled(sample_cards[0], sample, (Ancestry.EUR,))
    runs = tmp_path / "runs"
    directory = write_bundle(
        qc=sample_qc,
        cards=(result,),
        pack=sample_pack,
        ancestry=context,
        runs_root=runs,
        run_id="synthetic-ancestry",
        lock_path=tmp_path / "missing.lock",
        tools_root=tmp_path / "tools",
    )
    frozen = read_bundle(directory).cards[0]
    assert frozen.ancestry_comparison == result.ancestry_comparison
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    cli = CliRunner().invoke(app, ["runs", "show", "synthetic-ancestry", "--json"])
    assert cli.exit_code == 0, cli.stdout
    saved = json.loads(cli.stdout)["cards"][0]
    assert saved["summary"] == result.summary
    assert saved["ancestry_comparison"] == result.ancestry_comparison
    with TestClient(
        create_app(WebConfig(runs_root=runs)), base_url="http://127.0.0.1:8765"
    ) as client:
        face = html.unescape(client.get("/runs/synthetic-ancestry").text)
        detail = html.unescape(client.get(f"/runs/synthetic-ancestry/cards/{result.card_id}").text)
        assert result.summary in face
        assert result.detail in detail
    old = write_bundle(
        qc=sample_qc,
        cards=sample_cards,
        pack=sample_pack,
        ancestry=AncestryContext.not_run("Historical unknown ancestry."),
        runs_root=runs,
        run_id="historical",
        lock_path=tmp_path / "missing.lock",
        tools_root=tmp_path / "tools",
    )
    raw = json.loads((old / MANIFEST_NAME).read_text())
    raw["format_version"] = 17
    (old / MANIFEST_NAME).write_text(json.dumps(raw), encoding="utf-8")
    historical = read_bundle(old).cards[0]
    assert historical.ancestry_comparison is None
    assert historical.summary == sample_cards[0].summary
    assert historical.confidence == _card_payload(sample_cards[0])["confidence"]


def test_pipeline_places_once_before_imputation_even_without_polygenic_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genetics.pgs import runner
    from genetics.run import pipeline

    events: list[str] = []
    reference = placement()

    def place_once(*args: Any, **kwargs: Any) -> PopulationResult:
        events.append("place")
        return reference

    def matching(*args: Any, **kwargs: Any) -> Any:
        assert events == ["place"]
        events.append("match")
        return original_match(*args, **kwargs)

    from genetics.engine.matcher import match_pack

    original_match = match_pack
    monkeypatch.setattr(runner, "place_among_reference_populations", place_once)
    monkeypatch.setattr(pipeline, "match_pack", matching)
    stage = PolygenicStage()
    result = analyse(
        Path("tests/fixtures/synthetic/ancestry_v2_male.txt"),
        knowledge_dir=Path("tests/fixtures/cards"),
        no_impute=True,
        polygenic=stage,
    )
    assert events == ["place", "match"]
    assert result.ancestry.reference_population is reference
    assert stage._run_placement is reference
    assert all(
        c.ancestry_comparison is not None for c in result.cards if c.kind.value == "interpretation"
    )


def test_stage_placement_is_recomputed_for_a_different_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genetics.ingest import ingest
    from genetics.pgs import runner

    first = ingest(Path("tests/fixtures/synthetic/ancestry_v2_male.txt")).table
    second = ingest(Path("tests/fixtures/synthetic/ancestry_v2_female.txt")).table
    seen: list[Any] = []

    def place_once(table: Any, **kwargs: Any) -> PopulationResult:
        seen.append(table)
        return placement("EUR" if table is first else "EAS")

    monkeypatch.setattr(runner, "place_among_reference_populations", place_once)
    stage = PolygenicStage()
    first_result = stage.place(first)
    assert stage.place(first) is first_result
    second_result = stage.place(second)
    assert stage.place(second) is second_result
    assert seen == [first, second]
    assert first_result.to_dict()["region"] == "EUR"
    assert second_result.to_dict()["region"] == "EAS"


def test_placement_precedes_default_imputation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genetics.pgs import runner
    from genetics.run import pipeline

    events: list[str] = []

    def placed(*args: Any, **kwargs: Any) -> PopulationResult:
        events.append("placed")
        return placement()

    def imputation(*args: Any, **kwargs: Any) -> Any:
        assert events == ["placed"]
        raise RuntimeError("Synthetic stop before imputation.")

    monkeypatch.setattr(runner, "place_among_reference_populations", placed)
    monkeypatch.setattr(pipeline, "impute", imputation)
    with pytest.raises(RuntimeError, match="Synthetic stop"):
        analyse(
            Path("tests/fixtures/synthetic/ancestry_v2_male.txt"),
            knowledge_dir=Path("tests/fixtures/cards"),
        )


@pytest.mark.privacy
def test_observation_repr_does_not_expose_inferred_population(
    sample_cards: tuple[AssembledCard, ...],
) -> None:
    base = sample_cards[0]
    assert base.observation is not None
    observation = replace(base.observation, ancestry_context=sample_context(placement().to_dict()))
    assert "SYNTHETIC" not in repr(observation)
    assert "EUR" not in repr(observation)
