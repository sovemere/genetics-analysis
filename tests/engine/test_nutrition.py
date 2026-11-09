"""M12.1 nutrition cards: evidence bindings, strand, saved interfaces and the section pointer.

Observations are fabricated; every published number and direction is bound here
independently of the authored outcome names, so a reversed claim, a borrowed denominator
or a wrong unit fails before any card is rendered. See docs/nutrition.md.
"""

from __future__ import annotations

import itertools
import json
import math
import sqlite3
from contextlib import closing
from html import unescape
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine import sections
from genetics.engine.cards import (
    Card,
    KnowledgePack,
    Replication,
    default_knowledge_dir,
    parse_file,
)
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import (
    AssembledCard,
    ObservationEvidence,
    PopulationFrequency,
    assemble_pack,
)
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.engine.sections import Section
from genetics.ingest.keys import MergeTable
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run.bundle import RunBundle, read_bundle, write_bundle
from genetics.run.pipeline import observations
from genetics.web import WebConfig, create_app

ROOT = Path(__file__).parents[2]
AUTHORED = ROOT / "knowledge" / "nutrition" / "variants.yaml"
MOVED = ROOT / "knowledge" / "nutrition" / "lactase_alcohol.yaml"

# card -> (rsid, chrom, pos, forward alleles, sample size, effect value, measure, tier,
#          replication, study ancestry). Bound from the papers, not from the YAML.
BINDINGS: dict[str, tuple[Any, ...]] = {
    "cyp1a2_coffee_intake": (
        "rs2472297", "15", 75027880, ("C", "T"), 30062, 0.11, "beta", "gwas",
        Replication.INDEPENDENT, ("EUR",),
    ),
    "cyp1a2_rs762551_caffeine": (
        "rs762551", "15", 75041917, ("A", "C"), 51, 0.48, "mean_difference", "candidate_gene",
        Replication.NONE, ("EUR",),
    ),
    "adh1b_alcohol_intake": (
        "rs1229984", "4", 100239319, ("C", "T"), 218969, -17.22, "mean_difference", "gwas",
        Replication.META_ANALYSIS, ("EUR",),
    ),
    "fut2_secretor_status": (
        "rs601338", "19", 49206674, ("A", "G"), 2268, 9.89, "odds_ratio", "functional",
        Replication.META_ANALYSIS, ("MULTI",),
    ),
    "fut2_vitamin_b12": (
        "rs602662", "19", 49206985, ("A", "G"), 37283, 0.16, "beta", "gwas",
        Replication.INDEPENDENT, ("EUR",),
    ),
    "gc_vitamin_d": (
        "rs2282679", "4", 72608383, ("G", "T"), 5656, -18.0, "mean_difference", "gwas",
        Replication.INDEPENDENT, ("EUR",),
    ),
    "folr3_serum_folate": (
        "rs652197", "11", 71849741, ("C", "T"), 28913, 0.069, "beta", "gwas",
        Replication.INDEPENDENT, ("EUR",),
    ),
}  # fmt: skip
# Outcome per genotype, in sorted-pair order (first homozygote, heterozygote, second).
OUTCOMES = {
    "cyp1a2_coffee_intake": ("no_t", "one_t", "two_t"),
    "cyp1a2_rs762551_caffeine": ("aa", "c_carrier", "c_carrier"),
    "adh1b_alcohol_intake": ("non_carrier", "carrier", "two_copies"),
    "fut2_secretor_status": ("non_secretor", "secretor", "secretor"),
    "fut2_vitamin_b12": ("two_a", "one_a", "no_a"),
    "gc_vitamin_d": ("two_g", "one_g", "no_g"),
    "folr3_serum_folate": ("two_c", "one_c", "no_c"),
}
DOIS = {
    "cyp1a2_coffee_intake": {"10.1038/mp.2014.107", "10.1093/hmg/ddr086"},
    "cyp1a2_rs762551_caffeine": {
        "10.1046/j.1365-2125.1999.00898.x",
        "10.1001/jama.295.10.1135",
        "10.1093/hmg/ddr086",
    },
    "adh1b_alcohol_intake": {"10.1136/bmj.g4164"},
    "fut2_secretor_status": {
        "10.1093/cid/civ873",
        "10.1074/jbc.270.9.4640",
        "10.1128/JVI.79.24.15351-15355.2005",
    },
    "fut2_vitamin_b12": {"10.1371/journal.pgen.1003530", "10.1038/ng.210"},
    "gc_vitamin_d": {"10.1016/S0140-6736(10)60588-0"},
    "folr3_serum_folate": {"10.1371/journal.pgen.1003530"},
}
# Published directions and figures on each face. Each tuple must appear in that outcome's
# summary, which is the text the dashboard grid and `runs show` print first.
PUBLISHED_CLAIMS: dict[str, dict[str, tuple[str, ...]]] = {
    "cyp1a2_coffee_intake": {
        "no_t": ("No copy of the rs2472297 T allele", "each T copy", "0.11 more cups a day"),
        "one_t": ("One copy of the rs2472297 T allele", "0.11 more cups of coffee a day"),
        "two_t": ("Two copies of the rs2472297 T allele", "0.11 more cups of coffee a day"),
    },
    "cyp1a2_rs762551_caffeine": {
        "aa": ("AA at CYP1A2 -163", "185 non-smokers showed no difference"),
        "c_carrier": ("At least one C allele", "only in C carriers (OR 1.64, 95% CI 1.14-2.34)"),
    },
    "adh1b_alcohol_intake": {
        "non_carrier": ("No copy of ADH1B His48", "carriers of His48 drank 17.2% fewer"),
        "carrier": ("One copy of ADH1B His48", "drank 17.2% fewer", "0.78 times the odds"),
        "two_copies": ("Two copies of ADH1B His48", "17.2% fewer", "not analysed separately"),
    },
    "fut2_secretor_status": {
        "non_secretor": ("Two copies of the FUT2 nonsense allele", "Secretors had 9.9 times"),
        "secretor": ("At least one working FUT2 copy", "Secretors had 9.9 times"),
    },
    "fut2_vitamin_b12": {
        "two_a": ("Ser258 allele linked to higher blood vitamin B12", "AA averaged 488 pg/ml"),
        "one_a": ("One copy of the FUT2 Ser258 allele", "raised serum B12 by 0.16"),
        "no_a": ("No copy of the FUT2 Ser258 allele linked to higher", "GG averaged 413 pg/ml"),
    },
    "gc_vitamin_d": {
        "two_g": (
            "allele linked to lower blood vitamin D",
            "GG averaged 64.6 nmol/L",
            "82.6 for TT",
        ),
        "one_g": ("allele linked to lower blood vitamin D", "GT averaged 74.8 nmol/L"),
        "no_g": ("No copy of the GC allele linked to lower", "TT had the highest average, 82.6"),
    },
    "folr3_serum_folate": {
        "two_c": ("FOLR3 C allele linked to slightly higher serum folate", "0.069"),
        "one_c": ("FOLR3 C allele linked to slightly higher serum folate", "0.069"),
        "no_c": ("No copy of the FOLR3 C allele linked to slightly higher", "comparison group"),
    },
}
# Outcome-specific evidence, bound from the source tables.
OVERRIDES: dict[tuple[str, str], tuple[Any, ...]] = {
    # Cornelis 2006: >=4 vs <1 cups/day among C carriers (1,114 cases + 1,082 controls).
    ("cyp1a2_rs762551_caffeine", "c_carrier"): (
        2196, "odds_ratio", 1.64, 1.14, 2.34, ("AMR",), "candidate_gene", Replication.NONE,
    ),
    # Wang 2010 Table 2, Framingham, GT minus TT.
    ("gc_vitamin_d", "one_g"): (
        5656, "mean_difference", -7.8, -9.9, -5.7, ("EUR",), "gwas", Replication.INDEPENDENT,
    ),
}  # fmt: skip
# Wang 2010 Table 2, Framingham Heart Study: mean (SE) 25-hydroxyvitamin D, nmol/L.
FRAMINGHAM = {"TT": (82.6, 0.73), "GT": (74.8, 0.81), "GG": (64.6, 1.79)}


def assert_published_claims(card: Card) -> None:
    assert card.evidence is not None
    assert card.evidence.effect.measure.value == BINDINGS[card.id][6], (
        f"Wrong published units for {card.id}"
    )
    for outcome_name, claims in PUBLISHED_CLAIMS[card.id].items():
        summary = " ".join(card.outcomes[outcome_name].summary.split())
        assert all(claim in summary for claim in claims), (
            f"Wrong published direction or estimate for {card.id}/{outcome_name}"
        )


def nutrition_pack() -> KnowledgePack:
    cards = parse_file(AUTHORED.read_text(encoding="utf-8"), str(AUTHORED))
    assert {c.id for c in cards} == set(BINDINGS)
    for card in cards:
        assert_published_claims(card)
    return KnowledgePack(cards, AUTHORED.parent)


def _card(card_id: str) -> Card:
    return next(c for c in nutrition_pack().cards if c.id == card_id)


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


def _pairs(alleles: tuple[str, str]) -> list[str]:
    return ["".join(p) for p in itertools.combinations_with_replacement(alleles, 2)]


def assert_bindings() -> None:
    """Every card's locus, estimate and population, and each outcome's own evidence."""
    for card in nutrition_pack().cards:
        rsid, chrom, pos, alleles, n, value, _, tier, replication, ancestry = BINDINGS[card.id]
        assert card.match is not None and card.evidence is not None
        variant = card.match.variant
        assert (variant.rsid, variant.key.chrom.value, variant.key.pos_grch37) == (rsid, chrom, pos)
        assert tuple(variant.key.alleles) == alleles
        assert card.match.forward_only
        assert card.section is Section.NUTRITION
        assert card.evidence.tier.value == tier
        assert card.evidence.replication is replication
        assert card.evidence.sample_size == n and card.evidence.effect.value == value
        assert tuple(a.value for a in card.evidence.ancestry) == ancestry
        assert {c.id for c in card.citations if c.type.value == "doi"} == DOIS[card.id]
        assert tuple(card.match.genotypes[p] for p in _pairs(alleles)) == OUTCOMES[card.id]
        for name, outcome in card.outcomes.items():
            expected = OVERRIDES.get((card.id, name))
            if expected is None:
                assert not outcome.overrides_evidence, (card.id, name)
                continue
            evidence = outcome.evidence
            assert outcome.overrides_evidence and evidence is not None
            effect = evidence.effect
            assert (
                evidence.sample_size,
                effect.measure.value,
                effect.value,
                effect.ci_low,
                effect.ci_high,
                tuple(a.value for a in evidence.ancestry),
                evidence.tier.value,
                evidence.replication,
            ) == expected


def test_exact_bindings_of_locus_alleles_estimate_and_population() -> None:
    assert_bindings()


def test_intervals_computed_from_printed_standard_errors_reproduce() -> None:
    """Two intervals are arithmetic on a printed SE; recompute them from the source values."""
    pack = {c.id: c for c in nutrition_pack().cards}
    gc = pack["gc_vitamin_d"]
    assert gc.evidence is not None and gc.outcomes["one_g"].evidence is not None
    for genotype, effect in (
        ("GG", gc.evidence.effect),
        ("GT", gc.outcomes["one_g"].evidence.effect),
    ):
        (mean, se), (base, base_se) = FRAMINGHAM[genotype], FRAMINGHAM["TT"]
        half = 1.96 * math.hypot(se, base_se)
        assert effect.value == round(mean - base, 1)
        assert (effect.ci_low, effect.ci_high) == (
            round(mean - base - half, 1),
            round(mean - base + half, 1),
        )
    coffee = pack["cyp1a2_coffee_intake"].evidence
    assert coffee is not None
    # CCGC 2015 Table 1, stage 2 European: beta 0.11, SE 0.01.
    assert (coffee.effect.ci_low, coffee.effect.ci_high) == (
        round(0.11 - 1.96 * 0.01, 2),
        round(0.11 + 1.96 * 0.01, 2),
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("0.11 more cups a day; CC", "0.11 fewer cups a day; CC"),
        ("only in\n          C carriers", "only in\n          AA carriers"),
        ("drank 17.2% fewer alcohol units a week than non-carriers like", "drank 17.2% more"),
        ("Secretors had 9.9 times the odds of GII.4", "Non-secretors had 9.9 times the odds"),
        ("Ser258 allele linked to higher blood vitamin B12. In", "Ser258 allele linked to lower"),
        ("GC allele linked to lower blood vitamin D. In the Framingham\n          Heart Study GG",
         "GC allele linked to higher blood vitamin D. In the Framingham\n          Heart Study GG"),
        ("C allele linked to slightly higher serum folate: 0.069", "C allele linked to lower"),
        ("measure: odds_ratio\n        value: 9.89", "measure: risk_ratio\n        value: 9.89"),
    ],
    ids=[
        "coffee_direction",
        "rs762551_group",
        "adh1b_direction",
        "secretor_direction",
        "b12_direction",
        "vitamin_d_direction",
        "folate_direction",
        "secretor_units",
    ],
)  # fmt: skip
def test_bindings_reject_reversed_claims_and_wrong_units(
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
    with pytest.raises(AssertionError, match="Wrong published"):
        nutrition_pack()


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("sample_size: 2196", "sample_size: 4028", "sample"),
        ("sample_size: 5656\n          ancestry: [EUR]", "sample_size: 33869\n          ancestry: [EUR]",
         "sample"),
        ("value: -7.8\n            ci_low: -9.9\n            ci_high: -5.7",
         "value: -18.0\n            ci_low: -21.8\n            ci_high: -14.2", "effect"),
        ("ancestry: [AMR]", "ancestry: [EUR]", "ancestry"),
    ],
    ids=["cornelis_all_participants", "wang_all_cohorts", "gc_borrowed_effect", "cornelis_ancestry"],
)  # fmt: skip
def test_outcome_evidence_rejects_borrowed_denominators_and_effects(
    monkeypatch: pytest.MonkeyPatch, old: str, new: str, field: str
) -> None:
    read = Path.read_text

    def mutated(path: Path, *args: Any, **kwargs: Any) -> str:
        text = read(path, *args, **kwargs)
        if path == AUTHORED:
            assert old in text, field
            return text.replace(old, new, 1)
        return text

    monkeypatch.setattr(Path, "read_text", mutated)
    with pytest.raises(AssertionError):
        assert_bindings()


@pytest.mark.parametrize("card_id", BINDINGS)
@pytest.mark.parametrize("case", [0, 1, 2], ids=["first", "mixed", "second"])
def test_every_genotype_is_interpreted_with_its_own_evidence(card_id: str, case: int) -> None:
    card = _card(card_id)
    alleles = BINDINGS[card_id][3]
    pair = _pairs(alleles)[case]
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
    override = OVERRIDES.get((card_id, OUTCOMES[card_id][case]))
    expected_value = BINDINGS[card_id][5] if override is None else override[2]
    assert result.confidence.inputs.effect_value == expected_value
    if card_id == "cyp1a2_rs762551_caffeine":
        # Candidate-gene, unreplicated: never above moderate, whatever the observation.
        assert result.confidence.tier.rank >= ConfidenceTier.MODERATE.rank


@pytest.mark.parametrize("card_id", BINDINGS)
def test_missing_and_indel_inputs_remain_unresolved(card_id: str) -> None:
    card = _card(card_id)
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
def test_complemented_alleles_are_a_mismatch_not_a_reverse_strand_reading(card_id: str) -> None:
    """Every marker is multiallelic in dbSNP or names a strand the papers report differently."""
    card = _card(card_id)
    complements = {"A": "T", "C": "G", "G": "C", "T": "A"}
    pair = complements[BINDINGS[card_id][3][0]] * 2
    pack = KnowledgePack((card,), AUTHORED.parent)
    assert match_pack(pack, table(card, pair))[0].status is MatchStatus.ALLELE_MISMATCH


@pytest.mark.parametrize("card_id", BINDINGS)
def test_rarity_still_overrides_the_association(card_id: str) -> None:
    card = _card(card_id)
    alleles = BINDINGS[card_id][3]
    pack = KnowledgePack((card,), AUTHORED.parent)
    runtime = ObservationEvidence(
        CallSource.DIRECT,
        tuple(
            PopulationFrequency(a, 0.000001, "synthetic", "synthetic-reference") for a in alleles
        ),
        ancestry_match=1.0,
    )
    matched = match_pack(pack, table(card, "".join(alleles)))
    result = assemble_pack(pack, matched, {card_id: runtime})[0]
    assert result.status is MatchStatus.MATCHED and result.confidence is not None
    assert result.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT


def test_moved_cards_are_unchanged_apart_from_their_section() -> None:
    """M12.1 moved lactase and ALDH2 from traits; their claims and evidence did not change."""
    moved = parse_file(MOVED.read_text(encoding="utf-8"), str(MOVED))
    assert [c.id for c in moved] == ["mcm6_lactase_persistence", "aldh2_alcohol_flushing"]
    assert all(c.section is Section.NUTRITION for c in moved)
    lactase, aldh2 = moved
    assert lactase.match is not None and aldh2.match is not None
    assert lactase.match.variant.rsid == "rs4988235" and aldh2.match.variant.rsid == "rs671"
    assert lactase.evidence is not None and lactase.evidence.sample_size == 236
    assert aldh2.evidence is not None and aldh2.evidence.effect.value == 16.1
    pack = KnowledgePack.load(default_knowledge_dir())
    assert [c.id for c in pack.cards].count("mcm6_lactase_persistence") == 1
    assert [c.id for c in pack.cards].count("aldh2_alcohol_flushing") == 1


# ---------------------------------------------------------------------------
# The section pointer
# ---------------------------------------------------------------------------


def test_every_section_pointer_names_a_card_another_section_holds() -> None:
    pack = {c.id: c for c in KnowledgePack.load(default_knowledge_dir()).cards}
    declared = 0
    for section in sections.SECTION_ORDER:
        related = sections.SECTIONS[section].related
        assert len({r.card_id for r in related}) == len(related)
        for pointer in related:
            declared += 1
            assert pointer.label.strip()
            assert pointer.card_id in pack, pointer.card_id
            assert pack[pointer.card_id].section is not section, pointer.card_id
    assert declared >= 2
    nutrition = {r.card_id for r in sections.SECTIONS[Section.NUTRITION].related}
    assert nutrition == {
        "hfe_c282y_iron_overload",
        "hla_celiac_dq2_dq8",
        # M12.2: the health claims made for MTHFR render in physical and mental health.
        "mthfr_c677t_venous_thrombosis",
        "mthfr_c677t_coronary_heart_disease",
        "mthfr_c677t_depression",
    }
    assert pack["hfe_c282y_iron_overload"].section is Section.PHYSICAL_HEALTH
    assert pack["hla_celiac_dq2_dq8"].section is Section.IMMUNOGENETICS


def _saved_run(
    case: int, sample_qc: QCReport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RunBundle, Path, tuple[AssembledCard, ...]]:
    """Save the seven cards plus HFE (unmatched); the celiac HLA card is left out."""
    full = KnowledgePack.load(default_knowledge_dir())
    hfe = next(c for c in full.cards if c.id == "hfe_c282y_iron_overload")
    pack = KnowledgePack((*nutrition_pack().cards, hfe), AUTHORED.parent)
    rows = []
    for card in pack.cards:
        if card.id in BINDINGS:
            pair = _pairs(BINDINGS[card.id][3])[case]
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
    return read_bundle(path), root, assembled


@pytest.mark.parametrize("case", [0, 1, 2], ids=["first", "mixed", "second"])
def test_bundle_cli_and_dashboard_preserve_claims_evidence_and_pointer(
    case: int,
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, root, assembled = _saved_run(case, sample_qc, tmp_path, monkeypatch)
    shown = CliRunner().invoke(app, ["runs", "show", bundle.run_id, "--json"])
    assert shown.exit_code == 0, shown.output
    payload = {c["card_id"]: c for c in json.loads(shown.stdout)["cards"]}
    text = CliRunner().invoke(app, ["runs", "show", bundle.run_id])
    assert text.exit_code == 0, text.output
    assert (
        "Nutrition & metabolism also points to: hfe_c282y_iron_overload (physical_health); "
        "HLA-DQ2.5 and DQ8 and celiac disease (not in this run)"
    ) in text.stdout
    with TestClient(
        create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1:8765"
    ) as client:
        page = client.get(f"/runs/{bundle.run_id}?section=nutrition")
        assert page.status_code == 200
        flat = " ".join(unescape(page.text).split())
        assert "Also relevant here, shown in their own sections:" in flat
        assert f"/runs/{bundle.run_id}/cards/hfe_c282y_iron_overload" in page.text
        assert "HFE C282Y and iron-overload disease</a> (Physical health)" in flat
        assert "HLA-DQ2.5 and DQ8 and celiac disease (not in this run)" in flat
        for original in assembled:
            if original.card_id not in BINDINGS:
                continue
            saved = payload[original.card_id]
            assert saved["section"] == "nutrition"
            assert saved["summary"] == original.summary
            assert original.match.outcome_name is not None
            claims = PUBLISHED_CLAIMS[original.card_id][original.match.outcome_name]
            assert all(claim in " ".join(saved["summary"].split()) for claim in claims)
            assert all(claim in flat for claim in claims)
            assert {c["id"] for c in saved["citations"] if c["type"] == "doi"} == DOIS[
                original.card_id
            ]
            override = OVERRIDES.get((original.card_id, original.match.outcome_name))
            n = BINDINGS[original.card_id][4] if override is None else override[0]
            value = BINDINGS[original.card_id][5] if override is None else override[2]
            assert saved["evidence"]["sample_size"] == n
            assert saved["evidence"]["effect"]["value"] == value
            detail = client.get(f"/runs/{bundle.run_id}/cards/{original.card_id}")
            assert detail.status_code == 200
            assert all(claim in " ".join(unescape(detail.text).split()) for claim in claims)
            for doi in DOIS[original.card_id]:
                assert doi in detail.text
    # The HFE card renders once, in physical health; the pointer is not a second copy.
    assert sum(1 for c in bundle.cards if c.card_id == "hfe_c282y_iron_overload") == 1


def test_the_pointer_is_shown_only_on_its_own_section(
    sample_qc: QCReport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, root, _ = _saved_run(0, sample_qc, tmp_path, monkeypatch)
    with TestClient(
        create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1:8765"
    ) as client:
        by_tier = client.get(f"/runs/{bundle.run_id}?group=tier")
        assert by_tier.status_code == 200
        assert "Also relevant here" not in by_tier.text
        page = client.get(f"/runs/{bundle.run_id}")
        # Once per section that declares pointers (M12.2 added physical and mental health),
        # whether or not the section holds a card in this run.
        declaring = sum(1 for s in sections.SECTION_ORDER if sections.SECTIONS[s].related)
        assert declaring == 3
        assert page.text.count("Also relevant here, shown in their own sections:") == declaring
        # A filter that hides the target card does not hide the pointer: it resolves against
        # the whole run, and the detail page it opens is not filtered.
        filtered = client.get(f"/runs/{bundle.run_id}?section=nutrition")
        assert "hfe_c282y_iron_overload" not in filtered.text.split("Also relevant here")[0]
        assert f"/runs/{bundle.run_id}/cards/hfe_c282y_iron_overload" in filtered.text
        detail = client.get(f"/runs/{bundle.run_id}/cards/hfe_c282y_iron_overload")
        assert detail.status_code == 200


# ---------------------------------------------------------------------------
# Native: strand and allele identity against the fetched public references
# ---------------------------------------------------------------------------

CLINVAR = ROOT / "data/references/clinvar_grch37/clinvar_lookup.sqlite"
GNOMAD = ROOT / "data/references/gnomad_exomes_r2_1_1_grch37/gnomad_frequencies.sqlite"


def _site(index: Path, chrom: str, pos: int) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(f"{index.as_uri()}?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT record FROM variants WHERE chrom=? AND pos=?", (chrom, pos))
        return [json.loads(row[0]) for row in rows.fetchall()]


def _frequency(record: dict[str, Any], population: str) -> float:
    counts = record["populations"][population]
    return float(counts["ac"][0]) / float(counts["an"])


@pytest.mark.skipif(not GNOMAD.is_file(), reason="pinned gnomAD exomes index not fetched")
def test_coding_alleles_match_the_papers_population_frequencies() -> None:
    """The strand reasoning in docs/nutrition.md, re-checked against gnomAD r2.1.1 exomes.

    ADH1B His48 is forward T: rare in Europe (Holmes: about 7% carry it), common in East
    Asia. The FUT2 alleles are near-absent in East Asian exomes and common in Europe.
    """
    (adh1b,) = _site(GNOMAD, "4", 100239319)
    assert (adh1b["ref"], adh1b["alts"], adh1b["filter"]) == ("T", ["C"], "PASS")
    his48_nfe = 1 - _frequency(adh1b, "nfe")
    assert his48_nfe < 0.05 and 1 - _frequency(adh1b, "eas") > 0.5
    assert 0.05 < 1 - (1 - his48_nfe) ** 2 < 0.09  # carriers, against Holmes's 7%
    for pos in (49206674, 49206985):
        (fut2,) = _site(GNOMAD, "19", pos)
        assert (fut2["ref"], fut2["alts"], fut2["filter"]) == ("G", ["A"], "PASS")
        assert _frequency(fut2, "eas") < 0.01 and 0.3 < _frequency(fut2, "nfe") < 0.6


@pytest.mark.skipif(not CLINVAR.is_file(), reason="pinned ClinVar index not fetched")
def test_clinvar_consequences_name_the_card_alleles() -> None:
    expected = {
        ("19", 49206674): ("12945", "G", ["A"], "nonsense"),
        ("19", 49206985): ("996599", "G", ["A"], "missense_variant"),
        ("15", 75041917): ("511079", "C", ["A"], None),
    }
    for (chrom, pos), (variation, ref, alts, consequence) in expected.items():
        (record,) = [r for r in _site(CLINVAR, chrom, pos) if r["variation_id"] == variation]
        assert (record["ref"], record["alts"]) == (ref, alts)
        if consequence is not None:
            assert consequence in str(record["info"]["MC"])
    # ADH1B: ClinVar's record is the reference base itself, c.143A= (p.His48=).
    (adh1b,) = [r for r in _site(CLINVAR, "4", 100239319) if r["variation_id"] == "18182"]
    assert adh1b["ref"] == "T" and "ADH1B" in str(adh1b["info"]["GENEINFO"])
