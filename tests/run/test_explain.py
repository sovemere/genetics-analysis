"""What decided a saved card's tier, in one shape (roadmap M13.4).

Two things are checked. The calculators still give the tiers they gave before their
ceilings were moved into shared functions: an independent copy of the earlier rules is kept
here and compared over a grid of inputs. And :func:`explain_confidence`, reading only what a
bundle saves, replays every one of those results to the saved tier and names what decided
it. The cards are built from evidence objects; no genotype and no export is read.
"""

from __future__ import annotations

import itertools
import random
from collections.abc import Iterator
from dataclasses import asdict
from typing import Any

import pytest

from genetics.engine.cards import (
    Ancestry,
    Effect,
    EffectMeasure,
    Evidence,
    EvidenceTier,
    Replication,
)
from genetics.engine.confidence import (
    POLYGENIC_CEILING_NAMES,
    SCORE_BANDS,
    SCORE_WEIGHTS,
    CallSource,
    ConfidenceTier,
    PolygenicConfidence,
    calculate_confidence,
    calculate_polygenic_confidence,
    score_tier,
)
from genetics.engine.serialization import confidence_payload
from genetics.run.bundle import StoredCard
from genetics.run.explain import (
    POLYGENIC_ROWS,
    SCORE_TOLERANCE,
    SINGLE_CALL_ROWS,
    Basis,
    explain_confidence,
)

RANK = {tier: tier.rank for tier in ConfidenceTier}


def _evidence(
    tier: EvidenceTier = EvidenceTier.GWAS,
    replication: Replication = Replication.INDEPENDENT,
    value: float = 1.4,
) -> Evidence:
    return Evidence(
        tier=tier,
        effect=Effect(EffectMeasure.ODDS_RATIO, value),
        sample_size=10_000,
        ancestry=(Ancestry.EUR,),
        replication=replication,
    )


def _card(**changes: Any) -> StoredCard:
    """A saved card with nothing scored. Each test sets the blocks it is about."""
    base: dict[str, Any] = {
        "card_id": "synthetic_card",
        "section": "traits",
        "kind": "interpretation",
        "title": "Synthetic",
        "status": "matched",
        "summary": "Synthetic summary.",
        "detail": "",
        "gene": None,
        "impossibility_reason": None,
        "confidence_tier": None,
        "variant": None,
        "match": {"reason": None},
        "confidence": None,
        "evidence": None,
        "observation": None,
        "frequencies": (),
        "confidence_frequency": None,
        "citations": (),
        "authored_caveats": (),
        "computed_caveats": (),
    }
    return StoredCard(**(base | changes))


# ---------------------------------------------------------------------------
# The rules as they were before M13.4, kept apart from the engine's
# ---------------------------------------------------------------------------


def _weaker(left: ConfidenceTier, right: ConfidenceTier) -> ConfidenceTier:
    return left if RANK[left] >= RANK[right] else right


def _band(score: float) -> ConfidenceTier:
    if score >= 0.85:
        return ConfidenceTier.WELL_ESTABLISHED
    if score >= 0.70:
        return ConfidenceTier.STRONG
    if score >= 0.50:
        return ConfidenceTier.MODERATE
    return ConfidenceTier.LIMITED


def _share(value: float | None) -> ConfidenceTier | None:
    if value is None:
        return ConfidenceTier.STRONG
    if value < 0.25:
        return ConfidenceTier.LIMITED
    if value < 0.50:
        return ConfidenceTier.MODERATE
    return None


def _earlier_single_call_tier(
    evidence: Evidence | None,
    score: float,
    frequency: float | None,
    quality: float | None,
    unknown_quality: bool,
    ancestry: float | None,
    variant_ancestry: bool,
) -> ConfidenceTier:
    tier = _band(score)
    if unknown_quality:
        tier = _weaker(tier, ConfidenceTier.LIMITED)
    if (
        evidence is None
        or evidence.tier is EvidenceTier.ANECDOTAL
        or evidence.replication is Replication.CONFLICTING
    ):
        tier = _weaker(tier, ConfidenceTier.LIMITED)
    elif evidence.tier is EvidenceTier.CANDIDATE_GENE:
        tier = _weaker(tier, ConfidenceTier.MODERATE)
    if (frequency is not None and frequency < 0.00001) or (quality is not None and quality < 0.30):
        tier = ConfidenceTier.LIKELY_ARTIFACT
    elif quality is not None and quality < 0.60:
        tier = _weaker(tier, ConfidenceTier.LIMITED)
    elif quality is not None and quality < 0.80:
        tier = _weaker(tier, ConfidenceTier.MODERATE)
    if frequency is None:
        tier = _weaker(tier, ConfidenceTier.MODERATE)
    ceiling = None if variant_ancestry and ancestry is not None else _share(ancestry)
    return tier if ceiling is None else _weaker(tier, ceiling)


def _earlier_polygenic(
    evidence: Evidence, score: float, coverage: float, quality: float, ancestry: float | None
) -> tuple[ConfidenceTier, list[str]]:
    tier = _band(score)
    ceilings: list[str] = []

    def cap(ceiling: ConfidenceTier | None, why: str) -> None:
        nonlocal tier
        if ceiling is not None and RANK[ceiling] > RANK[tier]:
            tier = ceiling
            ceilings.append(why)

    if evidence.tier is EvidenceTier.ANECDOTAL or evidence.replication is Replication.CONFLICTING:
        cap(ConfidenceTier.LIMITED, "evidence")
    elif evidence.tier is EvidenceTier.CANDIDATE_GENE:
        cap(ConfidenceTier.MODERATE, "evidence")
    if quality < 0.30:
        cap(ConfidenceTier.LIKELY_ARTIFACT, "imputation_quality")
    elif quality < 0.60:
        cap(ConfidenceTier.LIMITED, "imputation_quality")
    elif quality < 0.80:
        cap(ConfidenceTier.MODERATE, "imputation_quality")
    cap(_share(coverage), "coverage")
    cap(_share(ancestry), "ancestry")
    return tier, ceilings


# ---------------------------------------------------------------------------
# Grids
# ---------------------------------------------------------------------------

EVIDENCE: tuple[Evidence | None, ...] = (
    None,
    *(
        _evidence(tier, replication, value)
        for tier in (
            EvidenceTier.EXPERT_CURATED,
            EvidenceTier.GWAS,
            EvidenceTier.CANDIDATE_GENE,
            EvidenceTier.ANECDOTAL,
        )
        for replication in (Replication.META_ANALYSIS, Replication.NONE, Replication.CONFLICTING)
        for value in (1.05, 6.0)
    ),
)
FREQUENCIES = (None, 0.000005, 0.00001, 0.00005, 0.02, 0.3)
CALLS: tuple[tuple[CallSource, float | None], ...] = (
    (CallSource.DIRECT, None),
    (CallSource.IMPUTED, None),
    (CallSource.IMPUTED, 0.29),
    (CallSource.IMPUTED, 0.30),
    (CallSource.IMPUTED, 0.59),
    (CallSource.IMPUTED, 0.79),
    (CallSource.IMPUTED, 0.80),
    (CallSource.IMPUTED, 1.0),
)
ANCESTRY = (None, 0.0, 0.24, 0.25, 0.49, 0.5, 1.0)


def _single_calls() -> Iterator[tuple[StoredCard, ConfidenceTier]]:
    """Every combination, as the saved card and the tier the earlier rules give it."""
    for evidence, frequency, (source, quality), ancestry, by_membership in itertools.product(
        EVIDENCE, FREQUENCIES, CALLS, ANCESTRY, (False, True)
    ):
        unknown = source is CallSource.IMPUTED and quality is None
        result = calculate_confidence(
            evidence,
            population_allele_frequency=frequency,
            call_source=source,
            imputation_quality=quality,
            imputation_quality_unknown=unknown,
            ancestry_match=ancestry,
            variant_ancestry=by_membership,
        )
        expected = _earlier_single_call_tier(
            evidence, result.score, frequency, quality, unknown, ancestry, by_membership
        )
        yield (
            _card(
                confidence=confidence_payload(result),
                confidence_tier=result.tier.value,
                ancestry_comparison={"text": "synthetic"} if by_membership else None,
            ),
            expected,
        )


def _polygenic_card(result: PolygenicConfidence) -> StoredCard:
    """A polygenic card, in the shape genetics.pgs.cards.reliability saves."""
    inputs = {k: (v.value if hasattr(v, "value") else v) for k, v in asdict(result.inputs).items()}
    reliability = {
        "tier": result.tier.value,
        "score": result.score,
        "inputs": inputs,
        "ceilings": list(result.ceilings),
        "reason": "Computed from synthetic inputs.",
    }
    return _card(
        kind="polygenic",
        status="computed",
        confidence_tier=result.tier.value,
        computation={"source": "polygenic_score", "reliability": reliability},
    )


def _polygenic_scores() -> Iterator[tuple[StoredCard, ConfidenceTier, list[str]]]:
    for evidence, coverage, quality, ancestry in itertools.product(
        [e for e in EVIDENCE if e is not None],
        (0.0, 0.24, 0.25, 0.49, 0.5, 0.97),
        (0.1, 0.3, 0.59, 0.79, 0.8, 0.99),
        ANCESTRY,
    ):
        result = calculate_polygenic_confidence(
            evidence,
            weight_coverage=coverage,
            weighted_quality=quality,
            unknown_quality_weight_fraction=0.01,
            ancestry_match=ancestry,
        )
        tier, ceilings = _earlier_polygenic(evidence, result.score, coverage, quality, ancestry)
        yield _polygenic_card(result), tier, ceilings


def _check_scored(block: dict[str, Any], tier: str, score: float) -> None:
    """What holds for every tier that came from a score and ceilings."""
    assert block["replay"] == {"tier": tier, "score": pytest.approx(score, abs=0.00015)} | {
        "matches": True
    }
    assert (block["tier"], block["score"]) == (tier, score)
    assert block["score_tier"] == score_tier(score).value
    weakest = max((RANK[ConfidenceTier(c["tier"])] for c in block["ceilings"]), default=-1)
    final = RANK[ConfidenceTier(tier)]
    assert final == max(weakest, RANK[ConfidenceTier(block["score_tier"])])
    names = {row["name"] for row in block["inputs"]}
    assert {c["input"] for c in block["ceilings"]} <= names
    deciding = [c for c in block["ceilings"] if c["tier"] == tier]
    assert block["limiting"] == list(dict.fromkeys(c["input"] for c in deciding))
    for ceiling in deciding:
        assert ceiling["rule"] in block["reason"]
    if block["basis"] == "score":
        assert block["score_tier"] == tier
        assert weakest <= final
        assert "no ceiling is below it" in block["reason"]
        assert ("A higher score would not raise the tier" in block["reason"]) == bool(deciding)
    else:
        assert block["basis"] == "ceiling"
        assert RANK[ConfidenceTier(block["score_tier"])] < final == weakest
        assert block["limiting"]
        assert f"The tier is {tier} because" in block["reason"]


def test_the_calculator_gives_the_tiers_it_gave_before_and_each_is_explained() -> None:
    """16,800 single calls: the earlier rules' tier, the saved tier and the replay agree."""
    count = 0
    seen: set[tuple[str, str]] = set()
    for card, expected in _single_calls():
        count += 1
        assert card.confidence is not None
        assert card.confidence["tier"] == expected.value
        block = explain_confidence(card)
        assert block["source"] == "confidence"
        _check_scored(block, expected.value, card.confidence["score"])
        seen.add((block["basis"], block["tier"]))
    assert count == len(EVIDENCE) * len(FREQUENCIES) * len(CALLS) * len(ANCESTRY) * 2 == 16_800
    # Every tier is reached, by its score where a score can earn it and by a ceiling.
    assert {tier for basis, tier in seen if basis == "ceiling"} == {
        "strong",
        "moderate",
        "limited",
        "likely-artifact",
    }
    assert {tier for basis, tier in seen if basis == "score"} == {
        tier.value for tier, _ in SCORE_BANDS
    }


def test_a_polygenic_score_keeps_its_saved_ceilings_and_is_explained() -> None:
    count = 0
    for card, expected, ceilings in _polygenic_scores():
        count += 1
        assert card.computation is not None
        reliability = card.computation["reliability"]
        assert (reliability["tier"], reliability["ceilings"]) == (expected.value, ceilings)
        block = explain_confidence(card)
        assert block["source"] == "computation.reliability"
        _check_scored(block, expected.value, reliability["score"])
        # The saved record names a ceiling only where it lowered the tier; the last one
        # named is the one that set it, and the explanation names that input too.
        assert (block["basis"] == "ceiling") == bool(ceilings)
        if ceilings:
            assert ceilings[-1] in {POLYGENIC_CEILING_NAMES[name] for name in block["limiting"]}
            listed = {POLYGENIC_CEILING_NAMES[c["input"]] for c in block["ceilings"]}
            assert set(ceilings) <= listed
    assert count == 24 * 6 * 6 * len(ANCESTRY)


# ---------------------------------------------------------------------------
# The block
# ---------------------------------------------------------------------------


def _explain_call(evidence: Evidence | None = None, **inputs: Any) -> dict[str, Any]:
    given: dict[str, Any] = {
        "population_allele_frequency": 0.3,
        "call_source": CallSource.DIRECT,
        "ancestry_match": 1.0,
    }
    result = calculate_confidence(evidence or _evidence(), **(given | inputs))
    return explain_confidence(
        _card(confidence=confidence_payload(result), confidence_tier=result.tier.value)
    )


def test_every_block_has_the_same_keys_whatever_the_card() -> None:
    blocks = [
        _explain_call(),
        explain_confidence(_card()),
        explain_confidence(_card(kind="impossibility", status="not_determinable")),
        explain_confidence(
            _card(
                kind="computed",
                computation={"source": "long_roh", "reliability": {"tier": "limited"}},
            )
        ),
    ]
    assert {block["basis"] for block in blocks} == {"score", "none", "method"}
    keys = [list(block) for block in blocks]
    assert all(found == keys[0] for found in keys)
    assert keys[0] == [
        "source",
        "basis",
        "tier",
        "score",
        "score_tier",
        "score_bands",
        "inputs",
        "ceilings",
        "limiting",
        "reason",
        "empirical_ppv",
        "replay",
    ]
    bands = [{"tier": tier.value, "min_score": floor} for tier, floor in SCORE_BANDS]
    assert all(block["score_bands"] == bands for block in blocks)


def test_the_scored_rows_add_up_to_the_score() -> None:
    block = _explain_call(_evidence(EvidenceTier.GWAS, Replication.NONE, 1.3))
    rows = block["inputs"]
    assert [row["name"] for row in rows] == [name for name, *_ in SINGLE_CALL_ROWS]
    assert sum(row["weight"] for row in rows) == pytest.approx(1.0)
    assert [row["weight"] for row in rows] == [
        SCORE_WEIGHTS[weight] for *_, weight in SINGLE_CALL_ROWS
    ]
    assert sum(row["contribution"] for row in rows) == pytest.approx(block["score"], abs=0.00015)
    for row in rows:
        assert row["contribution"] + row["lost"] == pytest.approx(row["weight"], abs=0.0001)
    by_name = {row["name"]: row for row in rows}
    assert by_name["evidence_tier"]["values"] == {"evidence_tier": "gwas"}
    assert by_name["effect_size"]["values"] == {
        "effect_measure": "odds_ratio",
        "effect_value": 1.3,
    }
    assert by_name["call_quality"]["values"] == {
        "call_source": "direct",
        "imputation_quality": None,
    }
    assert by_name["replication"]["lost"] == pytest.approx(0.16)


def test_a_tier_set_by_its_score_names_what_the_score_lost_on() -> None:
    block = _explain_call(_evidence(EvidenceTier.GWAS, Replication.NONE, 1.3))
    assert (block["basis"], block["tier"], block["limiting"]) == ("score", "moderate", [])
    assert block["ceilings"] == []
    assert "falls in the moderate band (0.50 up to 0.70)" in block["reason"]
    assert "lost most on replication (0.16 of a possible 0.2) and effect_size" in block["reason"]
    top = _explain_call(_evidence(EvidenceTier.EXPERT_CURATED, Replication.META_ANALYSIS, 6.0))
    assert (top["basis"], top["tier"]) == ("score", "well-established")
    assert "(0.85 or more)" in top["reason"]


def test_a_rare_call_is_explained_by_its_frequency_and_gives_the_measured_rate() -> None:
    """AGENTS.md 4.1: strong literature, a rare call, and the number that says how rare."""
    block = _explain_call(
        _evidence(EvidenceTier.EXPERT_CURATED, Replication.META_ANALYSIS, 12.0),
        population_allele_frequency=0.000001,
    )
    assert (block["basis"], block["tier"]) == ("ceiling", "likely-artifact")
    assert block["limiting"] == ["allele_frequency"]
    assert block["score_tier"] in {"strong", "moderate"}
    assert "below 0.001%, the rare-call band" in block["reason"]
    assert "about 16% confirmed and 84% unconfirmed by sequencing" in block["reason"]
    assert block["empirical_ppv"]["estimate"] == 0.16


def test_every_ceiling_that_applies_is_listed_and_the_weakest_ones_decide() -> None:
    block = _explain_call(
        _evidence(EvidenceTier.EXPERT_CURATED, Replication.CONFLICTING, 6.0),
        population_allele_frequency=None,
        call_source=CallSource.IMPUTED,
        imputation_quality=0.55,
        ancestry_match=None,
    )
    assert (block["basis"], block["score_tier"], block["tier"]) == (
        "ceiling",
        "moderate",
        "limited",
    )
    assert [(c["input"], c["tier"]) for c in block["ceilings"]] == [
        ("replication", "limited"),
        ("allele_frequency", "moderate"),
        ("call_quality", "limited"),
        ("ancestry_match", "strong"),
    ]
    assert block["limiting"] == ["replication", "call_quality"]
    assert (
        "because replication is conflicting and imputation quality is below 0.60" in block["reason"]
    )


def test_membership_ancestry_takes_no_transfer_ceiling() -> None:
    """M9.13: the same saved inputs give different ceilings by how ancestry was compared."""
    result = calculate_confidence(
        _evidence(EvidenceTier.EXPERT_CURATED, Replication.META_ANALYSIS, 6.0),
        population_allele_frequency=0.3,
        call_source=CallSource.DIRECT,
        ancestry_match=0.0,
        variant_ancestry=True,
    )
    saved = {"confidence": confidence_payload(result), "confidence_tier": result.tier.value}
    compared = explain_confidence(_card(**saved, ancestry_comparison={"text": "synthetic"}))
    assert compared["basis"] == "score" and compared["ceilings"] == []
    # Read as a card saved before format 18, the same numbers would have been capped.
    legacy = explain_confidence(_card(**saved))
    assert legacy["basis"] == "not_reproduced"
    assert legacy["replay"] == {"tier": "limited", "score": result.score, "matches": False}


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.update(tier="strong"),
        lambda c: c.update(score=round(c["score"] - 0.01, 4)),
        lambda c: c["inputs"].update(replication_score=0.5),
        lambda c: c["inputs"].update(evidence_tier="sequenced"),
        lambda c: c["inputs"].update(call_source="phased"),
        lambda c: c["inputs"].update(population_allele_frequency="common"),
        lambda c: c["inputs"].update(imputation_quality=1.5),
        lambda c: c["inputs"].update(effect_score=None),
        lambda c: c.update(score=None),
    ],
)
def test_a_tier_this_engine_cannot_reproduce_is_not_explained(change: Any) -> None:
    """A run saved under other rules must not get this engine's reasons for its tier."""
    result = calculate_confidence(
        _evidence(EvidenceTier.GWAS, Replication.NONE, 1.3),
        population_allele_frequency=0.3,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )
    saved = confidence_payload(result)
    assert explain_confidence(_card(confidence=saved))["basis"] == "score"
    change(saved)
    block = explain_confidence(_card(confidence=saved))
    assert block["basis"] == "not_reproduced"
    assert block["replay"]["matches"] is False
    assert block["limiting"] == []
    assert "The saved tier stands." in block["reason"]
    assert "nothing here says which input decided it" in block["reason"]
    # The saved values are reported, not this engine's.
    assert block["tier"] == saved["tier"] and block["score"] == saved["score"]


def test_a_computed_card_s_tier_is_its_method_s() -> None:
    reason = "Interpretation is limited: no empirical chip/population calibration."
    reliability = {
        "tier": "limited",
        "inputs": {"chip_population_calibrated": False, "chromosomes_assayed": 22},
        "reason": reason,
    }
    block = explain_confidence(
        _card(
            kind="computed",
            status="computed",
            confidence_tier="limited",
            computation={"source": "long_roh", "reliability": reliability},
        )
    )
    assert (block["source"], block["basis"]) == ("computation.reliability", "method")
    assert (block["tier"], block["score"], block["score_tier"]) == ("limited", None, None)
    assert block["reason"] == reason
    assert block["ceilings"] == [] and block["replay"] is None
    assert block["inputs"] == [
        {
            "name": "chip_population_calibrated",
            "values": {"chip_population_calibrated": False},
            "component": None,
            "weight": None,
            "contribution": None,
            "lost": None,
        },
        {
            "name": "chromosomes_assayed",
            "values": {"chromosomes_assayed": 22},
            "component": None,
            "weight": None,
            "contribution": None,
            "lost": None,
        },
    ]


def test_a_guideline_card_names_each_gene_and_its_reasons() -> None:
    notice = "Conditional on the saved source rows."
    rare = "Rare-call band: ~16% of rare heterozygous chip calls confirmed in the benchmark."
    genes = {
        "CYP2C19": {"tier": "likely-artifact", "reasons": [notice, rare]},
        "CYP2D6": None,
        "TPMT": {"tier": "provisional", "reasons": [notice]},
    }
    block = explain_confidence(
        _card(
            kind="guideline",
            status="computed",
            confidence_tier="likely-artifact",
            computation={
                "source": "pgx_guideline",
                "result": {"reliability": {"tier": "likely-artifact", "genes": genes}},
                "reliability": {"tier": "likely-artifact", "reason": notice},
            },
        )
    )
    assert (block["basis"], block["tier"]) == ("method", "likely-artifact")
    assert [(row["name"], row["values"]) for row in block["inputs"]] == [
        ("CYP2C19", {"tier": "likely-artifact"}),
        ("CYP2D6", {"tier": None}),
        ("TPMT", {"tier": "provisional"}),
    ]
    # Each sentence once, the card's own first.
    assert block["reason"] == f"{notice} {rare}"


def test_a_scored_record_this_engine_does_not_know_is_reported_as_saved() -> None:
    """A source that saves a score with other inputs is not forced into the six rows."""
    reliability = {
        "tier": "limited",
        "score": 0.31,
        "inputs": {"comparable_weight_fraction": 0.42, "nested": {"b": 1, "a": [2]}},
        "ceilings": ["coverage"],
        "reason": "Capped by coverage.",
    }
    block = explain_confidence(
        _card(kind="polygenic", computation={"source": "other", "reliability": reliability})
    )
    assert (block["basis"], block["score"], block["reason"]) == (
        "method",
        0.31,
        "Capped by coverage.",
    )
    assert block["inputs"][0]["values"] == {"comparable_weight_fraction": 0.42}
    # A nested value is written out, never dropped.
    assert block["inputs"][1]["values"] == {"nested": '{"a": [2], "b": 1}'}


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"kind": "impossibility", "status": "not_determinable"},
            "Not scored: the card states an assay limit, which is not a finding.",
        ),
        (
            {"status": "marker_absent", "match": {"reason": "The marker is not on this array."}},
            "Not scored: no finding for this run (status marker_absent). "
            "The marker is not on this array.",
        ),
        ({"status": "no_call"}, "Not scored: no finding for this run (status no_call)."),
        (
            {
                "kind": "polygenic",
                "status": "not_run",
                "computation": {
                    "source": "polygenic_score",
                    "reason": "The score was not computed.",
                    "reliability": {"tier": None, "score": None, "inputs": {}, "ceilings": []},
                },
            },
            "Not scored: no finding for this run (status not_run). The score was not computed.",
        ),
    ],
)
def test_a_card_with_no_tier_says_why(changes: dict[str, Any], expected: str) -> None:
    block = explain_confidence(_card(**changes))
    assert block == {
        "source": None,
        "basis": "none",
        "tier": None,
        "score": None,
        "score_tier": None,
        "score_bands": block["score_bands"],
        "inputs": [],
        "ceilings": [],
        "limiting": [],
        "reason": expected,
        "empirical_ppv": None,
        "replay": None,
    }


def test_a_multi_marker_card_names_the_marker_whose_confidence_it_took() -> None:
    weak = calculate_confidence(
        _evidence(),
        population_allele_frequency=0.3,
        call_source=CallSource.IMPUTED,
        imputation_quality=0.5,
        ancestry_match=1.0,
    )
    strong = calculate_confidence(
        _evidence(),
        population_allele_frequency=0.3,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )
    markers = [
        {"variant": {"rsid": "rs1000001"}, "confidence": confidence_payload(strong)},
        {"variant": {"rsid": "rs1000002"}, "confidence": confidence_payload(weak)},
    ]
    block = explain_confidence(
        _card(
            confidence=confidence_payload(weak),
            confidence_tier=weak.tier.value,
            multi_marker={"schema_version": 2, "markers": markers},
        )
    )
    assert block["reason"].startswith(
        "This card reads 2 markers and takes the weakest one's confidence (rs1000002). "
    )
    assert (block["basis"], block["limiting"]) == ("ceiling", ["call_quality"])


def _hla_card(locus_ceiling: str | None, saved_tier: str | None = None) -> StoredCard:
    result = calculate_confidence(
        _evidence(EvidenceTier.EXPERT_CURATED, Replication.META_ANALYSIS, 6.0),
        population_allele_frequency=None,
        call_source=CallSource.IMPUTED,
        imputation_quality=0.95,
        ancestry_match=1.0,
        variant_ancestry=True,
    )
    assert result.tier is ConfidenceTier.MODERATE
    payload = confidence_payload(result) | {"tier": saved_tier or result.tier.value}
    return _card(
        kind="hla",
        confidence=payload,
        confidence_tier=payload["tier"],
        computation={
            "source": "hla_card",
            "result": {
                "loci": {
                    "B": {"confidence": {"ceilings": ["marker_coverage", "ancestry"]}},
                    "DQB1": {"confidence": {"ceilings": []}},
                },
                "reliability": {
                    "posterior": 0.95,
                    "posterior_locus": "B",
                    "locus_ceiling": locus_ceiling,
                    "ceiling_loci": [] if locus_ceiling is None else ["B"],
                },
            },
            "reliability": {"tier": payload["tier"], "reason": "Synthetic notice."},
        },
    )


def test_an_hla_card_s_call_ceiling_sits_beside_the_six_inputs() -> None:
    """M11.4 lowers an HLA card to its weakest call's ceiling after the score is banded."""
    free = explain_confidence(_hla_card(None))
    # Read from the confidence block, though an HLA card has computation.reliability too.
    assert (free["source"], free["basis"], free["tier"]) == ("confidence", "ceiling", "moderate")
    assert free["limiting"] == ["allele_frequency"]
    assert free["inputs"][-1]["name"] == "hla_call"
    assert free["inputs"][-1]["values"] == {
        "posterior_locus": "B",
        "locus_ceiling": None,
        "ceiling_loci": None,
    }
    capped = explain_confidence(_hla_card("limited", "limited"))
    assert (capped["basis"], capped["limiting"]) == ("ceiling", ["hla_call"])
    assert capped["ceilings"][-1] == {
        "input": "hla_call",
        "tier": "limited",
        "rule": "the classifier call at HLA-B has a ceiling, lowered by classifier ancestry "
        "match and marker coverage",
    }
    # Without the call ceiling the six inputs alone would not give the saved tier.
    assert explain_confidence(_hla_card(None, "limited"))["basis"] == "not_reproduced"


def test_the_layouts_name_every_saved_input() -> None:
    """A key added to either saved block has to be given a row, or it goes unexplained."""
    single = confidence_payload(
        calculate_confidence(
            _evidence(), population_allele_frequency=0.3, call_source=CallSource.DIRECT
        )
    )["inputs"]
    polygenic = asdict(
        calculate_polygenic_confidence(
            _evidence(),
            weight_coverage=0.9,
            weighted_quality=0.9,
            unknown_quality_weight_fraction=0.0,
            ancestry_match=1.0,
        ).inputs
    )
    for saved, layout in ((single, SINGLE_CALL_ROWS), (polygenic, POLYGENIC_ROWS)):
        named = [key for _, keys, score, _ in layout for key in (*keys, score)]
        assert sorted(named) == sorted(saved)
        assert {weight for *_, weight in layout} == set(SCORE_WEIGHTS)


def test_the_basis_vocabulary_is_closed() -> None:
    assert [basis.value for basis in Basis] == [
        "score",
        "ceiling",
        "method",
        "not_reproduced",
        "none",
    ]


def test_a_ceiling_at_the_score_s_own_band_is_said_to_hold_the_tier() -> None:
    """Weak evidence scores low and is capped as well: both are true, and both are said."""
    block = _explain_call(_evidence(EvidenceTier.CANDIDATE_GENE, Replication.CONFLICTING, 1.05))
    assert (block["basis"], block["score_tier"], block["tier"]) == ("score", "limited", "limited")
    assert block["limiting"] == ["replication"]
    assert [(c["input"], c["tier"]) for c in block["ceilings"]] == [
        ("replication", "limited"),
        ("evidence_tier", "moderate"),
    ]
    assert block["reason"].endswith(
        "A higher score would not raise the tier, because replication is conflicting."
    )


# ---------------------------------------------------------------------------
# Scores with real decimals (review, 2026-11-13)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "value", "coverage", "quality", "ancestry", "score"),
    [
        (EvidenceTier.CLINICAL_GUIDELINE, 1.504, 0.1238, 0.6095, 0.0133, 0.4705),
        (EvidenceTier.COHORT, 2.341, 0.0847, 0.5413, 0.959, 0.4911),
    ],
)
def test_a_score_is_replayed_from_its_components_not_from_the_rounded_rows(
    tier: EvidenceTier, value: float, coverage: float, quality: float, ancestry: float, score: float
) -> None:
    """Each row's `contribution` is rounded for display, and the rounded rows do not add up.

    The first version summed them. These two honest scores came out 0.0002 away, past the
    tolerance, and were reported as saved under other rules. The grids above cannot show
    it: their inputs are round numbers, so no row is rounded at all.
    """
    result = calculate_polygenic_confidence(
        _evidence(tier, Replication.NONE, value),
        weight_coverage=coverage,
        weighted_quality=quality,
        unknown_quality_weight_fraction=0.0,
        ancestry_match=ancestry,
    )
    assert result.score == score
    block = explain_confidence(_polygenic_card(result))
    assert block["replay"] == {"tier": result.tier.value, "score": score, "matches": True}
    assert block["basis"] in {"score", "ceiling"}
    shown = sum(row["contribution"] for row in block["inputs"])
    assert abs(shown - score) > SCORE_TOLERANCE, "the rounded rows no longer disagree"


def test_every_score_with_arbitrary_decimals_is_reproduced() -> None:
    """A real run's DR2, coverage and ancestry match are not round numbers."""
    rng = random.Random(134)
    tiers, replications = list(EvidenceTier), list(Replication)

    def evidence() -> Evidence:
        return _evidence(
            rng.choice(tiers), rng.choice(replications), round(rng.uniform(0.2, 9.0), 3)
        )

    for _ in range(3000):
        polygenic = calculate_polygenic_confidence(
            evidence(),
            weight_coverage=rng.random(),
            weighted_quality=rng.random(),
            unknown_quality_weight_fraction=rng.random(),
            ancestry_match=rng.choice([None, rng.random()]),
        )
        block = explain_confidence(_polygenic_card(polygenic))
        assert block["replay"]["matches"] is True, block["replay"]
        # Polygenic components are saved as scored, so the replay is exact.
        assert block["replay"]["score"] == polygenic.score

        imputed = rng.random() < 0.7
        by_membership = rng.random() < 0.5
        single = calculate_confidence(
            evidence(),
            population_allele_frequency=rng.choice([None, rng.random(), rng.random() / 1000]),
            call_source=CallSource.IMPUTED if imputed else CallSource.DIRECT,
            imputation_quality=rng.random() if imputed else None,
            ancestry_match=rng.choice([None, rng.random()]),
            variant_ancestry=by_membership,
        )
        block = explain_confidence(
            _card(
                confidence=confidence_payload(single),
                confidence_tier=single.tier.value,
                ancestry_comparison={"text": "synthetic"} if by_membership else None,
            )
        )
        assert block["replay"]["matches"] is True, block["replay"]
        # One step in the fourth place at most: the effect component is saved rounded.
        assert abs(block["replay"]["score"] - single.score) < 0.00010001
