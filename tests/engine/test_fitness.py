"""M9.12 evidence, endpoint and saved-interface checks on fabricated observations."""

from __future__ import annotations

import itertools
import json
from html import unescape
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine.cards import Card, KnowledgePack, Replication, parse_file
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import ObservationEvidence, PopulationFrequency, assemble_pack
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.ingest.keys import MergeTable
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run.bundle import read_bundle, write_bundle
from genetics.run.pipeline import observations
from genetics.web import WebConfig, create_app

AUTHORED = Path(__file__).parents[2] / "knowledge" / "fitness" / "variants.yaml"
# Independently bind coordinates, forward alleles, endpoint, evidence and denominator.
BINDINGS = {
    "actn3_resistance_training": ("rs1815739", "11", 66328095, ("C", "T"), 355, 2.0),
    "ace_serum_association": ("rs4343", "17", 61566031, ("A", "G"), 92, 46.6),
    "col5a1_achilles_tendinopathy": ("rs12722", "9", 137734416, ("C", "T"), 295, 0.42),
    "acsl1_aerobic_trainability": ("rs6552828", "4", 185725416, ("A", "G"), 473, 6.1),
}
OUTCOMES = {
    "actn3_resistance_training": ("retained", "retained", "absent"),
    "ace_serum_association": ("lower", "intermediate", "higher"),
    "col5a1_achilles_tendinopathy": ("lower_case_odds", "comparator", "comparator"),
    "acsl1_aerobic_trainability": ("lower", "intermediate", "higher"),
}
DOIS = {
    "actn3_resistance_training": {"10.1152/japplphysiol.01139.2004", "10.1086/377590"},
    "ace_serum_association": {"10.1161/JAHA.116.004465"},
    "col5a1_achilles_tendinopathy": {"10.1136/bjsm.2008.048793", "10.1371/journal.pone.0170422"},
    "acsl1_aerobic_trainability": {"10.1152/japplphysiol.00973.2010"},
}
STUDY_ANCESTRIES = {
    "actn3_resistance_training": ("MULTI",),
    "ace_serum_association": ("UNKNOWN",),
    "col5a1_achilles_tendinopathy": ("EUR",),
    "acsl1_aerobic_trainability": ("EUR",),
}
# Published directions, independent of the authored outcome names. Keep both
# functional/association claims and group contrasts bound to their actual endpoint.
PUBLISHED_CLAIMS: dict[str, dict[str, tuple[str, ...]]] = {
    "actn3_resistance_training": {
        "retained": ("R577 copy preserves alpha-actinin-3", "about 2% of women's strength-gain"),
        "absent": ("associated with absent alpha-actinin-3", "XX gained more one-repetition"),
    },
    "ace_serum_association": {
        "lower": ("associated with lower serum ACE",),
        "intermediate": ("associated with intermediate serum ACE",),
        "higher": ("associated with higher serum ACE",),
    },
    "col5a1_achilles_tendinopathy": {
        "lower_case_odds": ("associated with lower chronic", "OR 0.42 (95% CI 0.20-0.86)"),
        "comparator": ("CT/TT comparator group", "No separate genotype risk"),
    },
    "acsl1_aerobic_trainability": {
        "lower": ("AA had lower VO2max gains than GG",),
        "intermediate": ("AG had intermediate VO2max gains",),
        "higher": ("GG had higher VO2max gains than AA",),
    },
}


def assert_published_claims(card: Card) -> None:
    assert card.evidence is not None
    measure = (
        "odds_ratio" if card.id == "col5a1_achilles_tendinopathy" else "percent_variance_explained"
    )
    assert card.evidence.effect.measure.value == measure, f"Wrong published units for {card.id}"
    for outcome_name, claims in PUBLISHED_CLAIMS[card.id].items():
        summary = " ".join(card.outcomes[outcome_name].summary.split())
        assert all(claim in summary for claim in claims), (
            f"Wrong published direction or estimate for {card.id}/{outcome_name}"
        )


def variant_pack() -> KnowledgePack:
    cards = parse_file(AUTHORED.read_text(encoding="utf-8"), str(AUTHORED))
    assert {c.id for c in cards} == set(BINDINGS)
    for card in cards:
        assert_published_claims(card)
    return KnowledgePack(cards, AUTHORED.parent)


def table(card: Card, pair: str | None) -> GenotypeTable:
    assert card.match is not None
    variant = card.match.variant
    rows = (
        []
        if pair is None
        else [
            {
                "rsid": variant.rsid,
                "chrom": variant.key.chrom.value,
                "pos_grch37": variant.key.pos_grch37,
                "a1": pair[0],
                "a2": pair[1],
                "genotype": "".join(sorted(pair)),
                "call_status": "called",
            }
        ]
    )
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")


def test_exact_variant_endpoint_bindings_and_estimate_scope() -> None:
    for card in variant_pack().cards:
        rsid, chrom, pos, alleles, n, value = BINDINGS[card.id]
        assert card.match is not None and card.evidence is not None
        variant = card.match.variant
        assert (variant.rsid, variant.key.chrom.value, variant.key.pos_grch37) == (rsid, chrom, pos)
        assert tuple(variant.key.alleles) == alleles
        assert card.match.forward_only
        assert card.section.value == "fitness" and card.evidence.tier.value == "candidate_gene"
        assert card.evidence.sample_size == n and card.evidence.effect.value == value
        assert tuple(a.value for a in card.evidence.ancestry) == STUDY_ANCESTRIES[card.id]
        assert {c.id for c in card.citations if c.type.value == "doi"} == DOIS[card.id]
        pairs = ["".join(p) for p in itertools.combinations_with_replacement(alleles, 2)]
        assert tuple(card.match.genotypes[p] for p in pairs) == OUTCOMES[card.id]
        if card.id in {"col5a1_achilles_tendinopathy", "acsl1_aerobic_trainability"}:
            assert card.evidence.replication is Replication.CONFLICTING
        else:
            assert card.evidence.replication is Replication.SAME_COHORT
        if card.id == "col5a1_achilles_tendinopathy":
            assert card.evidence.effect.ci_low == 0.20 and card.evidence.effect.ci_high == 0.86
            assert card.outcomes["comparator"].overrides_evidence
            assert card.outcomes["comparator"].evidence is None


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("XX gained more one-repetition", "XX gained less one-repetition"),
        ("associated with lower serum ACE", "associated with higher serum ACE"),
        ("associated with lower chronic", "associated with higher chronic"),
        ("AA had lower VO2max gains", "AA had higher VO2max gains"),
        ("measure: percent_variance_explained", "measure: odds_ratio"),
    ],
    ids=[
        "actn3_direction",
        "ace_direction",
        "injury_direction",
        "trainability_direction",
        "effect_units",
    ],
)
def test_variant_binding_rejects_reversed_claims_and_wrong_units(
    monkeypatch: pytest.MonkeyPatch, old: str, new: str
) -> None:
    read = Path.read_text

    def mutated(path: Path, *args: Any, **kwargs: Any) -> str:
        text = read(path, *args, **kwargs)
        if path == AUTHORED:
            assert old in text
            return text.replace(old, new, 1)
        return text

    monkeypatch.setattr(Path, "read_text", mutated)
    # The mutation changes only authored claims; observations remain fabricated.
    with pytest.raises(AssertionError, match="Wrong published"):
        variant_pack()


@pytest.mark.parametrize("card_id", BINDINGS)
@pytest.mark.parametrize("case", [0, 1, 2], ids=["first", "mixed", "second"])
def test_every_supported_state_keeps_weak_evidence_visible(
    card_id: str,
    case: int,
) -> None:
    card = next(c for c in variant_pack().cards if c.id == card_id)
    alleles = BINDINGS[card_id][3]
    pair = "".join(list(itertools.combinations_with_replacement(alleles, 2))[case])
    pack = KnowledgePack((card,), AUTHORED.parent)
    matches = match_pack(pack, table(card, pair), merges=MergeTable.empty())
    assert matches[0].outcome_name == OUTCOMES[card_id][case]
    runtime = ObservationEvidence(
        CallSource.DIRECT,
        tuple(PopulationFrequency(a, 0.5, "synthetic", "synthetic-reference") for a in alleles),
        ancestry_match=1.0,
    )
    result = assemble_pack(pack, matches, {card_id: runtime})[0]
    assert result.status is MatchStatus.MATCHED and result.confidence is not None
    assert result.citations == card.citations
    if card_id in {"col5a1_achilles_tendinopathy", "acsl1_aerobic_trainability"}:
        assert result.confidence.tier is ConfidenceTier.LIMITED
    else:
        assert result.confidence.tier.rank >= ConfidenceTier.MODERATE.rank
    if card_id == "col5a1_achilles_tendinopathy" and case != 0:
        assert result.card.evidence is None
        assert result.confidence.inputs.effect_value is None
    if card_id == "actn3_resistance_training":
        assert "men" in result.summary and "women" in result.summary
    if card_id == "ace_serum_association":
        assert "does not determine ACE I/D" in result.summary
    if card_id == "acsl1_aerobic_trainability":
        assert "failed replication" in result.summary


@pytest.mark.parametrize("card_id", BINDINGS)
def test_missing_and_indel_inputs_remain_unresolved(card_id: str) -> None:
    card = next(c for c in variant_pack().cards if c.id == card_id)
    pack = KnowledgePack((card,), AUTHORED.parent)
    missing_matches = match_pack(pack, table(card, None))
    missing = assemble_pack(pack, missing_matches, observations(pack, missing_matches))[0]
    assert missing.status is MatchStatus.MARKER_ABSENT
    assert not missing.has_interpretation
    indel_matches = match_pack(pack, table(card, "ID"))
    unresolved = assemble_pack(pack, indel_matches, observations(pack, indel_matches))[0]
    assert not unresolved.has_interpretation
    assert unresolved.status is not MatchStatus.MATCHED


@pytest.mark.parametrize("card_id", BINDINGS)
def test_unexpected_forward_alleles_cannot_be_reinterpreted_as_the_reverse_strand(
    card_id: str,
) -> None:
    card = next(c for c in variant_pack().cards if c.id == card_id)
    complements = {"A": "T", "C": "G", "G": "C", "T": "A"}
    pair = complements[BINDINGS[card_id][3][0]] * 2
    pack = KnowledgePack((card,), AUTHORED.parent)
    match = match_pack(pack, table(card, pair))[0]
    assert match.status is MatchStatus.ALLELE_MISMATCH


@pytest.mark.parametrize("card_id", BINDINGS)
def test_rarity_still_overrides_the_weak_association(card_id: str) -> None:
    card = next(c for c in variant_pack().cards if c.id == card_id)
    alleles = BINDINGS[card_id][3]
    pair = "".join(alleles)
    pack = KnowledgePack((card,), AUTHORED.parent)
    runtime = ObservationEvidence(
        CallSource.DIRECT,
        tuple(
            PopulationFrequency(a, 0.000001, "synthetic", "synthetic-reference") for a in alleles
        ),
        ancestry_match=1.0,
    )
    result = assemble_pack(pack, match_pack(pack, table(card, pair)), {card_id: runtime})[0]
    assert result.status is MatchStatus.MATCHED and result.confidence is not None
    assert result.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT


@pytest.mark.parametrize("case", [0, 1, 2], ids=["first", "mixed", "second"])
def test_variant_bundle_cli_dashboard_preserve_endpoint_evidence(
    case: int,
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pack = variant_pack()
    rows = []
    for card in pack.cards:
        alleles = BINDINGS[card.id][3]
        pair = "".join(list(itertools.combinations_with_replacement(alleles, 2))[case])
        rows.extend(table(card, pair).frame.to_dicts())
    calls = GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")
    matches = match_pack(pack, calls)
    assembled = assemble_pack(pack, matches, observations(pack, matches))
    root = tmp_path / "data" / "runs"
    monkeypatch.setenv("GENETICS_DATA_DIR", str(root.parent))
    path = write_bundle(
        qc=sample_qc,
        cards=assembled,
        pack=pack,
        ancestry=AncestryContext.not_run("synthetic acceptance"),
        runs_root=root,
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    bundle = read_bundle(path)
    shown = CliRunner().invoke(app, ["runs", "show", bundle.run_id, "--json"])
    assert shown.exit_code == 0, shown.output
    payload = {c["card_id"]: c for c in json.loads(shown.stdout)["cards"]}
    with TestClient(
        create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1:8765"
    ) as client:
        page = client.get(f"/runs/{bundle.run_id}?section=fitness")
        assert page.status_code == 200
        for original in assembled:
            saved = payload[original.card_id]
            assert saved["summary"] == original.summary
            assert original.match.outcome_name is not None
            claims = PUBLISHED_CLAIMS[original.card_id][original.match.outcome_name]
            assert all(claim in " ".join(saved["summary"].split()) for claim in claims)
            assert all(claim in " ".join(unescape(page.text).split()) for claim in claims)
            assert {c["id"] for c in saved["citations"] if c["type"] == "doi"} == DOIS[
                original.card_id
            ]
            if original.card.evidence is None:
                assert saved["evidence"] is None
            else:
                assert saved["evidence"]["sample_size"] == BINDINGS[original.card_id][4]
                assert saved["evidence"]["effect"]["value"] == BINDINGS[original.card_id][5]
                assert (
                    saved["evidence"]["effect"]["measure"]
                    == original.card.evidence.effect.measure.value
                )
            assert original.title in page.text
            detail = client.get(f"/runs/{bundle.run_id}/cards/{original.card_id}")
            assert detail.status_code == 200
            assert all(claim in " ".join(unescape(detail.text).split()) for claim in claims)
            for doi in DOIS[original.card_id]:
                assert doi in detail.text
        assert "failed replication" in page.text
        if case == 0:
            assert "Absolute risk" in page.text
