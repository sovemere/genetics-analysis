"""M12.2 MTHFR C677T: four cards on one marker, each scored on its own claim's evidence.

The calibration case for popular claims with thin support (roadmap M12.2). Every published
number, direction and population is bound here from the papers, independently of the YAML,
so a reversed claim, a borrowed denominator or an estimate moved onto the wrong genotype
fails before anything renders. The landing tests pin where the confidence calculator puts
each card, so a change to the calculator that moved them would have to be noticed. See
docs/mthfr.md.
"""

from __future__ import annotations

import itertools
import json
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
AUTHORED = ROOT / "knowledge" / "nutrition" / "mthfr.yaml"

# rs1801133 on GRCh37. MTHFR is on the reverse strand: coding 677C>T is forward G>A, so
# 677T is forward A (gnomAD r2.1.1 exomes: 31.5% of alleles; Frosst 1995: ~38% of chromosomes).
LOCUS = ("rs1801133", "1", 11856378, ("A", "G"))
# Sorted pairs AA, AG, GG are 677 TT, CT, CC.
GENOTYPE_OUTCOMES = ("tt", "ct", "cc")

# card -> (section, sample size, effect value, ci, measure, tier, replication, ancestry).
# Bound from the papers, not from the YAML.
BINDINGS: dict[str, tuple[Any, ...]] = {
    # Holmes 2011: 67 datasets, 53,643 without cardiovascular disease; TT-CC homocysteine.
    "mthfr_c677t_homocysteine": (
        Section.NUTRITION, 53643, 2.10, (1.71, 2.50), "mean_difference", "functional",
        Replication.META_ANALYSIS, ("MULTI",),
    ),
    # Bezemer 2007, MEGA: 4,375 patients + 4,856 controls; TT vs CC.
    "mthfr_c677t_venous_thrombosis": (
        Section.PHYSICAL_HEALTH, 9231, 0.94, (0.81, 1.08), "odds_ratio", "candidate_gene",
        Replication.CONFLICTING, ("EUR",),
    ),
    # Clarke 2012, 19 unpublished datasets: 48,175 cases + 67,961 controls; TT vs CC.
    "mthfr_c677t_coronary_heart_disease": (
        Section.PHYSICAL_HEALTH, 116136, 1.02, (0.98, 1.07), "odds_ratio", "candidate_gene",
        Replication.CONFLICTING, ("MULTI",),
    ),
    # Gilbody 2007: 1,280 cases + 10,429 controls; TT vs CC; populations not verified.
    "mthfr_c677t_depression": (
        Section.MENTAL_HEALTH, 11709, 1.36, (1.11, 1.67), "odds_ratio", "candidate_gene",
        Replication.CONFLICTING, ("UNKNOWN",),
    ),
}  # fmt: skip
# Outcome-specific evidence. None means `evidence: null`: the group is a comparator, or no
# estimate for it was verified, so no other genotype's estimate may stand in for it.
OVERRIDES: dict[tuple[str, str], tuple[Any, ...] | None] = {
    # Holmes 2011: CT-CC 0.42 (0.30-0.54), same 53,643 participants.
    ("mthfr_c677t_homocysteine", "ct"): (
        53643, "mean_difference", 0.42, 0.30, 0.54, ("MULTI",), "functional",
        Replication.META_ANALYSIS,
    ),
    # Bezemer 2007: CT vs CC 0.99 (0.91-1.08).
    ("mthfr_c677t_venous_thrombosis", "ct"): (
        9231, "odds_ratio", 0.99, 0.91, 1.08, ("EUR",), "candidate_gene", Replication.CONFLICTING,
    ),
    ("mthfr_c677t_venous_thrombosis", "cc"): None,
    # Clarke 2012 gives no CT estimate in its text.
    ("mthfr_c677t_coronary_heart_disease", "ct"): None,
    ("mthfr_c677t_coronary_heart_disease", "cc"): None,
    # Gilbody 2007's primary comparison was homozygotes against the common genotype.
    ("mthfr_c677t_depression", "ct"): None,
    ("mthfr_c677t_depression", "cc"): None,
}  # fmt: skip
DOIS = {
    "mthfr_c677t_homocysteine": {
        "10.1038/ng0595-111",
        "10.1016/S0140-6736(11)60872-6",
        "10.1371/journal.pgen.1003530",
        "10.3945/ajcn.114.099994",
        "10.3945/ajcn.110.004671",
        "10.1038/gim.2012.165",
        "10.1038/s41436-020-0843-0",
        "10.1093/oxfordjournals.aje.a010290",
        "10.1016/S0140-6736(03)12771-7",
        "10.1073/pnas.062066299",
        "10.1086/301825",
        "10.3945/ajcn.112.044545",
    },
    "mthfr_c677t_venous_thrombosis": {
        "10.1001/archinte.167.5.497",
        "10.1001/jama.293.6.715",
        "10.1038/gim.2012.165",
    },
    "mthfr_c677t_coronary_heart_disease": {
        "10.1371/journal.pmed.1001177",
        "10.1001/jama.288.16.2023",
        "10.3945/ajcn.112.044545",
        "10.1038/gim.2012.165",
    },
    "mthfr_c677t_depression": {"10.1093/aje/kwj347", "10.1176/appi.ajp.2018.18070881"},
}
# Published directions and figures each face must carry: the dashboard grid and
# `runs show` print the summary first.
PUBLISHED_CLAIMS: dict[str, dict[str, tuple[str, ...]]] = {
    "mthfr_c677t_homocysteine": {
        "tt": ("Two copies of MTHFR 677T", "2.1 micromol/L (95% CI 1.7-2.5) more", "3.1 in Asia"),
        "ct": ("One copy of MTHFR 677T", "0.42 micromol/L (95% CI 0.30-0.54) more",
               "unlikely to be of clinical significance"),
        "cc": ("No copy of MTHFR 677T", "TT averaged 2.1 micromol/L and CT 0.42"),
    },
    "mthfr_c677t_venous_thrombosis": {
        "tt": ("Two copies of MTHFR 677T", "did not differ from CC's",
               "OR 0.94 (95% CI 0.81-1.08)"),
        "ct": ("One copy of MTHFR 677T", "did not differ from CC's",
               "OR 0.99 (95% CI 0.91-1.08)"),
        "cc": ("No copy of MTHFR 677T", "neither CT nor TT had higher odds"),
    },
    "mthfr_c677t_coronary_heart_disease": {
        "tt": ("Two copies of MTHFR 677T", "coronary heart disease did not differ from CC's",
               "OR 1.02 (95% CI 0.98-1.07)", "Published studies gave 1.15"),
        "ct": ("One copy of MTHFR 677T", "No heterozygote estimate is assigned"),
        "cc": ("No copy of MTHFR 677T", "TT did not have higher odds", "OR 1.02"),
    },
    "mthfr_c677t_depression": {
        "tt": ("Two copies of MTHFR 677T", "OR 1.36, 95% CI 1.11-1.67",
               "found no association"),
        "ct": ("One copy of MTHFR 677T", "No heterozygote estimate is assigned",
               "found no association"),
        "cc": ("No copy of MTHFR 677T", "found no association"),
    },
}  # fmt: skip
# Where the calculator lands each card for a common, directly typed call with an exact
# ancestry match: the narrow biochemical claim is well established, and every popular
# health claim is limited because its replication conflicts.
LANDING = {
    "mthfr_c677t_homocysteine": ConfidenceTier.WELL_ESTABLISHED,
    "mthfr_c677t_venous_thrombosis": ConfidenceTier.LIMITED,
    "mthfr_c677t_coronary_heart_disease": ConfidenceTier.LIMITED,
    "mthfr_c677t_depression": ConfidenceTier.LIMITED,
}


def assert_published_claims(card: Card) -> None:
    assert card.evidence is not None
    assert card.evidence.effect.measure.value == BINDINGS[card.id][4], (
        f"Wrong published units for {card.id}"
    )
    for outcome_name, claims in PUBLISHED_CLAIMS[card.id].items():
        summary = " ".join(card.outcomes[outcome_name].summary.split())
        assert all(claim in summary for claim in claims), (
            f"Wrong published direction or estimate for {card.id}/{outcome_name}"
        )


def mthfr_pack() -> KnowledgePack:
    cards = parse_file(AUTHORED.read_text(encoding="utf-8"), str(AUTHORED))
    assert [c.id for c in cards] == list(BINDINGS)
    for card in cards:
        assert_published_claims(card)
    return KnowledgePack(cards, AUTHORED.parent)


def _card(card_id: str) -> Card:
    return next(c for c in mthfr_pack().cards if c.id == card_id)


def _pairs() -> list[str]:
    return ["".join(p) for p in itertools.combinations_with_replacement(LOCUS[3], 2)]


def table(pair: str | None) -> GenotypeTable:
    rsid, chrom, pos, _ = LOCUS
    rows = (
        []
        if pair is None
        else [
            {
                "rsid": rsid,
                "chrom": chrom,
                "pos_grch37": pos,
                "a1": pair[0],
                "a2": pair[1],
                "genotype": "".join(sorted(pair)),
                "call_status": "called",
            }
        ]
    )
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")


def assert_bindings() -> None:
    """Every card's locus, estimate and population, and each outcome's own evidence."""
    for card in mthfr_pack().cards:
        section, n, value, (low, high), _, tier, replication, ancestry = BINDINGS[card.id]
        assert card.match is not None and card.evidence is not None
        variant = card.match.variant
        rsid, chrom, pos, alleles = LOCUS
        assert (variant.rsid, variant.key.chrom.value, variant.key.pos_grch37) == (rsid, chrom, pos)
        assert tuple(variant.key.alleles) == alleles
        assert card.match.forward_only
        assert card.section is section
        assert card.evidence.tier.value == tier
        assert card.evidence.replication is replication
        effect = card.evidence.effect
        assert card.evidence.sample_size == n
        assert (effect.value, effect.ci_low, effect.ci_high) == (value, low, high)
        assert tuple(a.value for a in card.evidence.ancestry) == ancestry
        assert {c.id for c in card.citations if c.type.value == "doi"} == DOIS[card.id]
        assert tuple(card.match.genotypes[p] for p in _pairs()) == GENOTYPE_OUTCOMES
        for name, outcome in card.outcomes.items():
            key = (card.id, name)
            if key not in OVERRIDES:
                assert not outcome.overrides_evidence, key
                continue
            expected = OVERRIDES[key]
            assert outcome.overrides_evidence, key
            if expected is None:
                assert outcome.evidence is None, key
                continue
            evidence = outcome.evidence
            assert evidence is not None
            out = evidence.effect
            assert (
                evidence.sample_size,
                out.measure.value,
                out.value,
                out.ci_low,
                out.ci_high,
                tuple(a.value for a in evidence.ancestry),
                evidence.tier.value,
                evidence.replication,
            ) == expected, key


def test_exact_bindings_of_locus_estimate_population_and_section() -> None:
    assert_bindings()


def test_physical_health_outcomes_state_that_no_absolute_risk_is_assigned() -> None:
    """Case-control odds ratios give no rate; each face says so rather than implying one."""
    for card in mthfr_pack().cards:
        if card.section is not Section.PHYSICAL_HEALTH:
            continue
        for name, outcome in card.outcomes.items():
            assert outcome.risk_context is not None, (card.id, name)
            assert "No absolute" in outcome.risk_context, (card.id, name)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("averaged 2.1 micromol/L (95% CI 1.7-2.5) more", "averaged 2.1 micromol/L (95% CI 1.7-2.5) less"),
        ("CT averaged 0.42 micromol/L (95% CI\n          0.30-0.54) more",
         "CT averaged 0.42 micromol/L (95% CI\n          0.30-0.54) less"),
        ("odds of a first venous thrombosis did not differ from CC's: OR 0.94",
         "odds of a first venous thrombosis were twice CC's: OR 0.94"),
        ("coronary heart disease did not differ from CC's", "coronary heart disease exceeded CC's"),
        ("people found no association.\n        detail: >-\n          Gilbody",
         "people confirmed it.\n        detail: >-\n          Gilbody"),
        ("measure: odds_ratio\n        value: 0.94", "measure: risk_ratio\n        value: 0.94"),
    ],
    ids=[
        "homocysteine_direction",
        "heterozygote_direction",
        "thrombosis_null",
        "heart_disease_null",
        "depression_replication",
        "thrombosis_units",
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
        mthfr_pack()


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        # Holmes's total with data for homocysteine, not the 53,643 without heart disease.
        ("sample_size: 53643\n      ancestry: [MULTI]", "sample_size: 59995\n      ancestry: [MULTI]",
         "sample"),
        # Clarke's published studies, not the unpublished datasets the estimate comes from.
        ("value: 1.02\n        ci_low: 0.98\n        ci_high: 1.07",
         "value: 1.15\n        ci_low: 1.09\n        ci_high: 1.21", "effect"),
        # TT's homocysteine difference borrowed for one copy.
        ("value: 0.42\n            ci_low: 0.30\n            ci_high: 0.54",
         "value: 2.10\n            ci_low: 1.71\n            ci_high: 2.50", "effect"),
        # Border's European samples are not Gilbody's unverified populations.
        ("ancestry: [UNKNOWN]", "ancestry: [EUR]", "ancestry"),
        # A comparator must not inherit the TT odds ratio.
        ("      cc:\n        evidence: null\n        summary: >-\n          No copy of MTHFR 677T: the comparison group. A 2007",
         "      cc:\n        summary: >-\n          No copy of MTHFR 677T: the comparison group. A 2007",
         "comparator"),
    ],
    ids=[
        "holmes_all_participants",
        "clarke_published_estimate",
        "homocysteine_borrowed_effect",
        "gilbody_ancestry",
        "depression_comparator",
    ],
)  # fmt: skip
def test_bindings_reject_borrowed_denominators_effects_and_populations(
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


def _runtime(frequency: float, ancestry_match: float | None) -> ObservationEvidence:
    a, g = LOCUS[3]
    return ObservationEvidence(
        CallSource.DIRECT,
        (
            PopulationFrequency(a, frequency, "synthetic", "synthetic-reference"),
            PopulationFrequency(g, 1 - frequency, "synthetic", "synthetic-reference"),
        ),
        ancestry_match=ancestry_match,
    )


@pytest.mark.parametrize("card_id", BINDINGS)
@pytest.mark.parametrize("case", [0, 1, 2], ids=["tt", "ct", "cc"])
def test_every_genotype_is_interpreted_with_its_own_evidence(card_id: str, case: int) -> None:
    card = _card(card_id)
    pack = KnowledgePack((card,), AUTHORED.parent)
    matches = match_pack(pack, table(_pairs()[case]), merges=MergeTable.empty())
    outcome = GENOTYPE_OUTCOMES[case]
    assert matches[0].outcome_name == outcome
    result = assemble_pack(pack, matches, {card_id: _runtime(0.34, 1.0)})[0]
    assert result.status is MatchStatus.MATCHED and result.confidence is not None
    assert result.citations == card.citations
    key = (card_id, outcome)
    if key in OVERRIDES and OVERRIDES[key] is None:
        assert result.confidence.inputs.effect_value is None
        assert result.confidence.inputs.evidence_tier is None
    else:
        override = OVERRIDES.get(key)
        expected = BINDINGS[card_id][2] if override is None else override[2]
        assert result.confidence.inputs.effect_value == expected


@pytest.mark.parametrize("card_id", BINDINGS)
@pytest.mark.parametrize("case", [0, 1, 2], ids=["tt", "ct", "cc"])
def test_the_calculator_lands_each_claim_where_its_evidence_puts_it(
    card_id: str, case: int
) -> None:
    """The calibration case: one marker, four claims, four independent landings.

    Nothing about these tiers is authored. The biochemical claim lands well established
    because a functional variant with a meta-analysed effect on a common allele scores high
    on every component. Each popular health claim lands limited, for every genotype,
    because its replication conflicts; a comparator with no estimate is capped there too.
    """
    pack = KnowledgePack((_card(card_id),), AUTHORED.parent)
    matches = match_pack(pack, table(_pairs()[case]), merges=MergeTable.empty())
    result = assemble_pack(pack, matches, {card_id: _runtime(0.34, 1.0)})[0]
    assert result.confidence is not None
    assert result.confidence.tier is LANDING[card_id], result.confidence


def test_no_popular_claim_outranks_the_biochemistry() -> None:
    """Whatever the observation, a conflicting candidate-gene claim never reaches moderate."""
    pack = mthfr_pack()
    for frequency, ancestry in itertools.product((0.05, 0.34, 0.5), (1.0, 0.6, None)):
        matches = match_pack(pack, table("AA"), merges=MergeTable.empty())
        runtime = {c.id: _runtime(frequency, ancestry) for c in pack.cards}
        results = {r.card_id: r for r in assemble_pack(pack, matches, runtime)}
        biochem = results["mthfr_c677t_homocysteine"].confidence
        assert biochem is not None
        for card_id in BINDINGS:
            if card_id == "mthfr_c677t_homocysteine":
                continue
            claim = results[card_id].confidence
            assert claim is not None
            assert claim.tier.rank >= ConfidenceTier.LIMITED.rank, (card_id, claim)
            assert claim.tier.rank > biochem.tier.rank, (card_id, frequency, ancestry)


@pytest.mark.parametrize("card_id", BINDINGS)
def test_missing_and_indel_inputs_remain_unresolved(card_id: str) -> None:
    pack = KnowledgePack((_card(card_id),), AUTHORED.parent)
    missing_matches = match_pack(pack, table(None))
    missing = assemble_pack(pack, missing_matches, observations(pack, missing_matches))[0]
    assert missing.status is MatchStatus.MARKER_ABSENT
    assert not missing.has_interpretation
    indel_matches = match_pack(pack, table("ID"))
    unresolved = assemble_pack(pack, indel_matches, observations(pack, indel_matches))[0]
    assert not unresolved.has_interpretation
    assert unresolved.status is not MatchStatus.MATCHED


@pytest.mark.parametrize("card_id", BINDINGS)
@pytest.mark.parametrize("pair", ["TT", "CC", "CT"])
def test_complemented_alleles_are_a_mismatch_not_a_reverse_strand_reading(
    card_id: str, pair: str
) -> None:
    """dbSNP b157 lists G>A,C,T here, so C and T are real alternates, never 677 alleles."""
    pack = KnowledgePack((_card(card_id),), AUTHORED.parent)
    assert match_pack(pack, table(pair))[0].status is MatchStatus.ALLELE_MISMATCH


@pytest.mark.parametrize("card_id", BINDINGS)
def test_rarity_still_overrides_every_claim(card_id: str) -> None:
    pack = KnowledgePack((_card(card_id),), AUTHORED.parent)
    matched = match_pack(pack, table("AG"))
    result = assemble_pack(pack, matched, {card_id: _runtime(0.000001, 1.0)})[0]
    assert result.status is MatchStatus.MATCHED and result.confidence is not None
    assert result.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT


# ---------------------------------------------------------------------------
# Section pointers and the saved interfaces
# ---------------------------------------------------------------------------


def test_the_four_cards_point_to_each_other_across_sections() -> None:
    pack = {c.id: c for c in KnowledgePack.load(default_knowledge_dir()).cards}
    for card_id, binding in BINDINGS.items():
        assert pack[card_id].section is binding[0]
    nutrition = {r.card_id for r in sections.SECTIONS[Section.NUTRITION].related}
    claims = set(BINDINGS) - {"mthfr_c677t_homocysteine"}
    assert claims <= nutrition
    for section in (Section.PHYSICAL_HEALTH, Section.MENTAL_HEALTH):
        related = {r.card_id for r in sections.SECTIONS[section].related}
        assert "mthfr_c677t_homocysteine" in related, section


def _saved_run(
    case: int, sample_qc: QCReport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RunBundle, Path, tuple[AssembledCard, ...]]:
    pack = mthfr_pack()
    matches = match_pack(pack, table(_pairs()[case]))
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


@pytest.mark.parametrize("case", [0, 1, 2], ids=["tt", "ct", "cc"])
def test_bundle_cli_and_dashboard_preserve_claims_evidence_and_pointers(
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
    assert "Physical health also points to: mthfr_c677t_homocysteine (nutrition)" in text.stdout
    assert "Mental health also points to: mthfr_c677t_homocysteine (nutrition)" in text.stdout
    assert "mthfr_c677t_depression (mental_health)" in text.stdout
    outcome = GENOTYPE_OUTCOMES[case]
    with TestClient(
        create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1:8765"
    ) as client:
        for section, target in (
            ("nutrition", "mthfr_c677t_venous_thrombosis"),
            ("physical_health", "mthfr_c677t_homocysteine"),
            ("mental_health", "mthfr_c677t_homocysteine"),
        ):
            page = client.get(f"/runs/{bundle.run_id}?section={section}")
            assert page.status_code == 200
            assert "Also relevant here, shown in their own sections:" in unescape(page.text)
            assert f"/runs/{bundle.run_id}/cards/{target}" in page.text
        for original in assembled:
            saved = payload[original.card_id]
            assert saved["section"] == BINDINGS[original.card_id][0].value
            assert saved["summary"] == original.summary
            assert original.match.outcome_name == outcome
            claims = PUBLISHED_CLAIMS[original.card_id][outcome]
            assert all(claim in " ".join(saved["summary"].split()) for claim in claims)
            assert {c["id"] for c in saved["citations"] if c["type"] == "doi"} == DOIS[
                original.card_id
            ]
            override = OVERRIDES.get((original.card_id, outcome), ())
            if override is None:
                assert saved["evidence"] is None
            else:
                n, value = (
                    (override[0], override[2])
                    if override
                    else (BINDINGS[original.card_id][1], BINDINGS[original.card_id][2])
                )
                assert saved["evidence"]["sample_size"] == n
                assert saved["evidence"]["effect"]["value"] == value
            detail = client.get(f"/runs/{bundle.run_id}/cards/{original.card_id}")
            assert detail.status_code == 200
            flat = " ".join(unescape(detail.text).split())
            assert all(claim in flat for claim in claims)
            for doi in DOIS[original.card_id]:
                assert doi in detail.text
    # One card per claim: the pointers are links, not copies.
    assert sorted(c.card_id for c in bundle.cards) == sorted(BINDINGS)


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
def test_forward_a_is_677t_by_population_frequency() -> None:
    """Forward A matches 677T's published frequencies, and G cannot.

    Frosst 1995: about 38% of unselected chromosomes. Grarup 2013: 677C (G) EAF 0.668 in
    Iceland, so 677T 0.332. ACMG: more than 25% of Hispanics TT; Botto and Yang: TT 1% or
    less among Black people in Africa and the US.
    """
    (site,) = _site(GNOMAD, "1", 11856378)
    assert (site["ref"], site["alts"], site["filter"]) == ("G", ["A"], "PASS")
    assert 0.30 < _frequency(site, "nfe") < 0.40
    assert _frequency(site, "amr") ** 2 > 0.20
    assert _frequency(site, "afr") ** 2 < 0.02


@pytest.mark.skipif(not CLINVAR.is_file(), reason="pinned ClinVar index not fetched")
def test_clinvar_names_forward_a_as_the_ala222val_missense() -> None:
    (record,) = [r for r in _site(CLINVAR, "1", 11856378) if r["variation_id"] == "3520"]
    assert (record["ref"], record["alts"]) == ("G", ["A"])
    assert "missense_variant" in str(record["info"]["MC"])
    assert "MTHFR" in str(record["info"]["GENEINFO"])
    # Not a pathogenic assertion, so the AGENTS.md 4.1 rare-call gate has nothing to gate.
    assert "athogenic" not in str(record["info"]["CLNSIG"])
