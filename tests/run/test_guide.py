"""The reading guide and confidence legend (roadmap M14.3).

The guide is built from the confidence engine's own tables and functions and from the
committed knowledge pack. These tests hold it to them: every ceiling the engine can apply
is listed, every figure the prose quotes is the engine's or is in a cited source, and the
pack-derived lists are the pack's. No run is read.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.engine import confidence, ppv
from genetics.engine.cards import CardKind, EvidenceTier, KnowledgePack, Replication
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.privacy import assert_no_genotype
from genetics.run import guide
from genetics.run.explain import POLYGENIC_ROWS, SINGLE_CALL_ROWS
from genetics.run.reads import STATUS_LABELS
from genetics.web import views

runner = CliRunner()


@pytest.fixture(scope="module")
def pack() -> KnowledgePack:
    return KnowledgePack.load(None)


@pytest.fixture(scope="module")
def document(pack: KnowledgePack) -> dict[str, Any]:
    return guide.reading_guide(pack)


# ---------------------------------------------------------------------------
# The legend
# ---------------------------------------------------------------------------


def test_the_legend_is_every_tier_strongest_first_then_no_tier() -> None:
    entries = guide.legend()
    assert [entry["key"] for entry in entries] == [
        *(tier.value for tier in ConfidenceTier),
        guide.NO_TIER,
    ]
    assert entries[-1]["label"] == "No tier"
    floors = {tier.value: floor for tier, floor in confidence.SCORE_BANDS}
    for entry in entries[:-1]:
        assert entry["min_score"] == floors.get(entry["key"])
    assert entries[-1]["min_score"] is None
    assert "No score earns it" in entries[4]["earned_by"]


def test_the_badges_and_the_legend_use_the_same_words() -> None:
    assert views._TIER_LABELS is guide.TIER_LABELS
    assert views._TIER_BLURBS is guide.TIER_BLURBS
    assert views.NO_TIER == guide.NO_TIER
    for entry in guide.legend()[:-1]:
        assert entry["label"] == guide.TIER_LABELS[entry["key"]]
        assert entry["blurb"] == guide.TIER_BLURBS[entry["key"]]


def test_each_tier_names_the_ceilings_that_cap_there() -> None:
    rules = guide.ceiling_rules()
    for entry in guide.legend()[:-1]:
        capped = [rule["rule"] for rule in rules if rule["tier"] == entry["key"]]
        for rule in capped:
            assert rule in entry["earned_by"], (entry["key"], rule)
    assert not any(rule["tier"] == "well-established" for rule in rules)


# ---------------------------------------------------------------------------
# The ceilings are the engine's, all of them
# ---------------------------------------------------------------------------

_FRACTIONS = (None, 0.0, 0.0000099, 0.00001, 0.2, 0.29, 0.3, 0.45, 0.5, 0.59, 0.6, 0.79, 0.8, 1.0)


def _listed() -> set[tuple[str, str, str]]:
    return {(rule["input"], rule["tier"], rule["rule"]) for rule in guide.ceiling_rules()}


def test_every_ceiling_a_single_call_can_meet_is_listed() -> None:
    listed = _listed()
    seen: set[tuple[str, str, str]] = set()
    evidence = [(False, None, None)] + [
        (True, tier, replication) for tier in EvidenceTier for replication in Replication
    ]
    for (has, tier, replication), frequency, (
        source,
        quality,
    ), ancestry, membership in itertools.product(
        evidence,
        _FRACTIONS,
        [(CallSource.DIRECT, None)] + [(CallSource.IMPUTED, q) for q in _FRACTIONS],
        _FRACTIONS,
        (False, True),
    ):
        for ceiling in confidence.single_call_ceilings(
            has_evidence=has,
            evidence_tier=tier,
            replication=replication,
            population_allele_frequency=frequency,
            call_source=source,
            imputation_quality=quality,
            ancestry_match=ancestry,
            variant_ancestry=membership,
        ):
            seen.add((ceiling.input, ceiling.tier.value, ceiling.rule))
    assert seen <= listed, seen - listed
    single = {
        (rule["input"], rule["tier"], rule["rule"])
        for rule in guide.ceiling_rules()
        if "single call" in rule["applies_to"]
    }
    assert single == seen, "a listed single-call rule the grid never met"


def test_every_ceiling_a_polygenic_score_can_meet_is_listed() -> None:
    listed = _listed()
    seen: set[tuple[str, str, str]] = set()
    present = [f for f in _FRACTIONS if f is not None]
    for tier, replication, coverage, quality, ancestry in itertools.product(
        EvidenceTier, Replication, present, present, _FRACTIONS
    ):
        for ceiling in confidence.polygenic_ceilings(
            evidence_tier=tier,
            replication=replication,
            weight_coverage=coverage,
            weighted_quality=quality,
            ancestry_match=ancestry,
        ):
            seen.add((ceiling.input, ceiling.tier.value, ceiling.rule))
    assert seen <= listed, seen - listed
    polygenic = {
        (rule["input"], rule["tier"], rule["rule"])
        for rule in guide.ceiling_rules()
        if "polygenic score" in rule["applies_to"]
    }
    assert polygenic == seen


def test_the_ceilings_are_listed_weakest_tier_first() -> None:
    ranks = [ConfidenceTier(rule["tier"]).rank for rule in guide.ceiling_rules()]
    assert ranks == sorted(ranks, reverse=True)


def test_a_changed_bound_changes_the_guide(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bounds are read, not restated: change one in the engine and the guide follows."""
    changed = ((0.25, ConfidenceTier.LIKELY_ARTIFACT), *confidence.QUALITY_CEILINGS[1:])
    monkeypatch.setattr(confidence, "QUALITY_CEILINGS", changed)
    monkeypatch.setattr(guide, "QUALITY_CEILINGS", changed)
    rules = {rule["rule"] for rule in guide.ceiling_rules()}
    assert "imputation quality is below 0.25" in rules
    assert "imputation quality is below 0.30" not in rules


# ---------------------------------------------------------------------------
# The score, the bands and the rarity components
# ---------------------------------------------------------------------------


def test_the_inputs_are_the_six_rows_runs_card_prints(document: dict[str, Any]) -> None:
    inputs = document["confidence"]["inputs"]
    assert [row["single_call"] for row in inputs] == [row[0] for row in SINGLE_CALL_ROWS]
    assert [row["polygenic"] for row in inputs] == [row[0] for row in POLYGENIC_ROWS]
    assert sum(row["weight"] for row in inputs) == pytest.approx(1.0)
    assert [row["weight"] for row in inputs] == [
        confidence.SCORE_WEIGHTS[row[3]] for row in SINGLE_CALL_ROWS
    ]
    labels = [row.label for row in views.ConfidenceView.of({}).rows]
    assert [row["single_call_label"] for row in inputs] == labels


def test_the_frequency_components_are_the_ones_the_score_uses(
    document: dict[str, Any],
) -> None:
    rows = document["rarity"]["frequency_components"]
    assert rows[0]["from"] is None and rows[-1]["below"] is None
    for row in rows:
        probes = [p for p in (row["from"], row["below"]) if p is not None]
        inside = probes[0] if row["from"] is not None else probes[0] / 2
        assert confidence._frequency_score(inside) == row["component"]
    assert confidence._frequency_score(None) == document["rarity"]["unknown_frequency_component"]
    assert document["rarity"]["rare_call_band"] == confidence.RARE_CALL_FREQUENCY_CEILING


def test_the_benchmarks_are_the_ones_a_clinvar_record_carries(
    document: dict[str, Any],
) -> None:
    rare, brca = document["rarity"]["benchmarks"]
    assert rare == ppv.clinvar_benchmark({})
    assert brca == ppv.clinvar_benchmark({"GENEINFO": "BRCA2:675", "CLNSIG": "Pathogenic"})
    assert rare["estimate"] == confidence.RARE_CALL_EMPIRICAL_PPV


def test_the_rarity_prose_quotes_the_engine_s_figures(document: dict[str, Any]) -> None:
    text = " ".join(document["rarity"]["paragraphs"])
    assert "only 16% of 4,757" in text and "about 5 to 1 against" in text
    assert "positive predictive value was 4.2%, about 23 to 1 against" in text
    assert "0 below 0.001%" in text and "capped at likely artifact" in text
    assert ppv.CLINICAL_NOTICE in text


# ---------------------------------------------------------------------------
# What the pack holds
# ---------------------------------------------------------------------------


def test_the_impossibility_list_is_the_pack_s(
    pack: KnowledgePack, document: dict[str, Any]
) -> None:
    listed = document["array"]["not_determinable"]
    cards = [card for card in pack.cards if card.kind is CardKind.IMPOSSIBILITY]
    assert [row["card_id"] for row in listed] == [card.id for card in cards]
    assert all(row["reason"] for row in listed)
    assert {row["card_id"] for row in listed} >= {"cyp2d6_structural_variation", "smn1_copy_number"}


def test_the_polygenic_list_and_counts_are_the_pack_s(
    pack: KnowledgePack, document: dict[str, Any]
) -> None:
    polygenic = document["polygenic"]
    cards = [card for card in pack.cards if card.kind is CardKind.POLYGENIC]
    assert [row["card_id"] for row in polygenic["cards"]] == [card.id for card in cards]
    european = sum(row["study_ancestry"] == ["EUR"] for row in polygenic["cards"])
    text = " ".join(polygenic["paragraphs"])
    assert f"{european} of {len(cards)} polygenic cards" in text
    if all(row["within_family_attenuation"] is None for row in polygenic["cards"]):
        assert "No polygenic card in this pack has a published within-family estimate" in text


def test_the_statuses_are_the_badges(document: dict[str, Any]) -> None:
    statuses = document["reading"]["statuses"]
    assert {row["status"]: row["label"] for row in statuses} == dict(STATUS_LABELS)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_every_paper_the_prose_names_is_a_listed_source(document: dict[str, Any]) -> None:
    paragraphs = [
        paragraph
        for key in ("reading", "confidence", "rarity", "polygenic", "array")
        for paragraph in document[key]["paragraphs"]
    ]
    text = " ".join(paragraphs)
    sources = " ".join(source["title"] for source in document["sources"])
    for author in re.findall(r"([A-Z][a-z]+(?:-[A-Z][a-z]+)?) et al\.", text):
        assert author in sources, author
    for source in document["sources"]:
        assert source["url"] == f"https://doi.org/{source['id']}"


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_cards_guide_json_is_the_guide_and_holds_no_genotype(
    document: dict[str, Any], agent_schema_check: Callable[[object], str]
) -> None:
    result = runner.invoke(app, ["cards", "guide", "--json"])
    assert result.exit_code == 0, result.output
    printed = json.loads(result.stdout)
    assert agent_schema_check(printed) == "cards.guide"
    assert {key: value for key, value in printed.items() if key != "schema"} == json.loads(
        json.dumps(document)
    )
    assert_no_genotype(result.stdout, context="test")


def test_the_committed_guide_is_a_fresh_copy(document: dict[str, Any]) -> None:
    first = guide.committed_guide()
    first["legend"].clear()
    assert guide.committed_guide() == json.loads(json.dumps(document))


def test_cards_guide_text_covers_each_part() -> None:
    result = runner.invoke(app, ["cards", "guide"])
    assert result.exit_code == 0, result.output
    for heading in (
        "Confidence tiers, strongest first",
        "How a tier is decided",
        "Rarity lowers confidence",
        "What a polygenic score can say",
        "What this array cannot tell you",
        "Sources",
    ):
        assert heading in result.stdout
    assert "at most likely artifact: the population allele frequency is below 0.001%" in (
        result.stdout
    )


def test_a_pack_that_will_not_load_is_a_knowledge_error(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("cards: [{id: 1}]\n", encoding="utf-8")
    result = runner.invoke(app, ["cards", "guide", "--knowledge", str(tmp_path), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["kind"] == "knowledge"


@pytest.mark.parametrize("arguments", [["cards", "guide"], ["cards", "guide", "--json"]])
def test_cards_guide_prints_to_a_cp1252_pipe(arguments: list[str]) -> None:
    """``CliRunner`` substitutes a UTF-8 stream; a pipe on Windows gets cp1252 (M11.6)."""
    result = subprocess.run(
        [sys.executable, "-m", "genetics.cli.main", *arguments],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
