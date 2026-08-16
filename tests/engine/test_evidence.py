"""Evidence assembly (roadmap M3.4), using synthetic cards and calls only."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from genetics.engine.cards import Card, CardKind, KnowledgePack, Outcome
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import (
    EvidenceAssemblyError,
    ObservationEvidence,
    PopulationFrequency,
    assemble_card,
    assemble_pack,
)
from genetics.engine.matcher import MatchResult, MatchStatus, Strand
from genetics.ingest.keys import VariantKey

FIXTURE = Path("tests/fixtures/cards/valid_pack.yaml")


def _pack() -> KnowledgePack:
    return KnowledgePack.load(FIXTURE.parent)


def _matched(card_id: str) -> MatchResult:
    card = _pack().by_id(card_id)
    assert card is not None and card.match is not None
    outcome_name = next(iter(card.match.genotypes.values()))
    return MatchResult(
        card_id=card.id,
        status=MatchStatus.MATCHED,
        reason="Matched.",
        genotype="AG",
        observed_genotype="AG",
        observed_rsid=card.match.variant.rsid,
        outcome_name=outcome_name,
        outcome=card.outcomes[outcome_name],
        strand=Strand.AS_WRITTEN,
        caveats=("Synthetic computed caveat.",),
    )


def _frequencies(*, a: float = 0.80, g: float = 0.20) -> tuple[PopulationFrequency, ...]:
    return (
        PopulationFrequency("A", a, "EUR", "synthetic-reference-v1"),
        PopulationFrequency("G", g, "EUR", "synthetic-reference-v1"),
    )


def test_matched_card_bundles_rendered_text_frequency_citations_and_confidence() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    frequencies = _frequencies()

    result = assemble_card(
        card,
        _matched(card.id),
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=frequencies,
            ancestry_match=1.0,
        ),
    )

    assert result.card is card
    assert result.status is MatchStatus.MATCHED
    assert result.summary == "Your AG at rs900000001 carries the synthetic allele."
    assert "SYNTH1" in result.detail
    assert result.frequencies == frequencies
    assert result.confidence_frequency is frequencies[1]
    assert result.citations == card.citations
    assert result.authored_caveats == card.caveats
    assert result.computed_caveats == ("Synthetic computed caveat.",)
    assert result.confidence is not None
    assert result.confidence.inputs.population_allele_frequency == 0.20


def test_rare_low_confidence_finding_is_returned_not_filtered() -> None:
    pack = _pack()
    card = pack.by_id("synthetic_dominant_trait")
    assert card is not None
    rare = (
        PopulationFrequency("A", 0.999999, "global", "synthetic-reference-v1"),
        PopulationFrequency("G", 0.000001, "global", "synthetic-reference-v1"),
    )

    result = assemble_card(
        card,
        _matched(card.id),
        ObservationEvidence(call_source=CallSource.DIRECT, frequencies=rare),
    )

    assert result.confidence is not None
    assert result.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT
    assert result.confidence.empirical_ppv is not None
    assert result.has_interpretation


def test_confidence_placeholder_is_rendered_by_production_assembly() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    outcomes = dict(card.outcomes)
    selected = Outcome("Computed confidence: {confidence}.", outcomes["present"].detail)
    outcomes["present"] = selected
    card = replace(card, outcomes=outcomes)
    match = replace(_matched(card.id), outcome=selected)

    result = assemble_card(
        card,
        match,
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=_frequencies(),
            ancestry_match=1.0,
        ),
    )

    assert result.summary == "Computed confidence: strong."


def test_frequency_allele_must_belong_to_the_card_variant() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    wrong = PopulationFrequency("T", 0.20, "EUR", "synthetic-reference-v1")

    with pytest.raises(EvidenceAssemblyError, match="another variant"):
        assemble_card(
            card,
            _matched(card.id),
            ObservationEvidence(call_source=CallSource.DIRECT, frequencies=(wrong,)),
        )


def test_frequency_is_derived_from_observed_alleles_not_caller_selection() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    match = replace(_matched(card.id), genotype="AA", observed_genotype="AA")

    # Only the unobserved allele is priced. The rare G must not be applied to an AA call,
    # and the gap must not be silent -- but it also must not cost the reader every other
    # card in the pack, so it degrades with a caveat instead of raising.
    unpriced = assemble_card(
        card,
        match,
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=(PopulationFrequency("G", 0.000001, "EUR", "synthetic-reference-v1"),),
        ),
    )
    assert unpriced.confidence_frequency is None
    assert unpriced.confidence is not None
    assert unpriced.confidence.tier is not ConfidenceTier.LIKELY_ARTIFACT
    assert unpriced.confidence.inputs.population_allele_frequency is None
    assert any("No population frequency" in caveat for caveat in unpriced.computed_caveats)

    result = assemble_card(
        card,
        match,
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=_frequencies(a=0.999999, g=0.000001),
        ),
    )
    assert result.confidence_frequency is not None
    assert result.confidence_frequency.allele == "A"
    assert result.confidence is not None
    assert result.confidence.tier is not ConfidenceTier.LIKELY_ARTIFACT


def test_heterozygous_rare_allele_gate_is_frequency_order_independent() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    frequencies = _frequencies(a=0.999999, g=0.000001)

    for ordered in (frequencies, tuple(reversed(frequencies))):
        result = assemble_card(
            card,
            _matched(card.id),
            ObservationEvidence(call_source=CallSource.DIRECT, frequencies=ordered),
        )
        assert result.confidence_frequency is not None
        assert result.confidence_frequency.allele == "G"
        assert result.confidence is not None
        assert result.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT


def test_ambiguous_homozygote_calibrates_both_possible_strand_alleles() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None and card.match is not None
    variant = replace(
        card.match.variant,
        key=VariantKey(
            card.match.variant.key.chrom,
            card.match.variant.key.pos_grch37,
            ("A", "T"),
        ),
    )
    card = replace(
        card,
        match=replace(
            card.match,
            variants=(variant,),
            genotypes={"AA": "present", "AT": "present", "TT": "present"},
        ),
    )
    outcome = card.outcomes["present"]
    match = MatchResult(
        card.id,
        MatchStatus.MATCHED,
        "Both strand readings map to the same outcome.",
        genotype=None,
        observed_genotype="AA",
        outcome_name="present",
        outcome=outcome,
        strand=Strand.AMBIGUOUS,
    )

    result = assemble_card(
        card,
        match,
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=(
                PopulationFrequency("A", 0.999999, "EUR", "synthetic-reference-v1"),
                PopulationFrequency("T", 0.000001, "EUR", "synthetic-reference-v1"),
            ),
        ),
    )

    assert result.confidence_frequency is not None
    assert result.confidence_frequency.allele == "T"
    assert result.confidence is not None
    assert result.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT


@pytest.mark.parametrize(
    "status",
    [
        MatchStatus.MARKER_ABSENT,
        MatchStatus.NO_CALL,
        MatchStatus.ALLELE_MISMATCH,
        MatchStatus.INDEL_EXCLUDED,
        MatchStatus.HET_HAPLOID,
        MatchStatus.DUPLICATE_CONFLICT,
        MatchStatus.STRAND_AMBIGUOUS,
    ],
)
def test_every_unresolved_match_remains_a_renderable_card(status: MatchStatus) -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    match = MatchResult(card.id, status, f"Synthetic reason for {status.value}.")

    observation = ObservationEvidence(call_source=CallSource.DIRECT)
    result = assemble_card(card, match, observation)

    assert result.status is status
    assert result.summary == match.reason
    assert result.detail == match.reason
    assert result.confidence is None
    assert result.observation is observation
    assert not result.has_interpretation


def test_impossibility_card_renders_without_genotype_or_confidence() -> None:
    card = _pack().by_id("synthetic_impossibility")
    assert card is not None and card.kind is CardKind.IMPOSSIBILITY
    match = MatchResult(
        card.id,
        MatchStatus.NOT_DETERMINABLE,
        card.impossibility_reason or "Not determinable.",
    )

    result = assemble_card(card, match)

    assert result.status is MatchStatus.NOT_DETERMINABLE
    assert result.summary == "Not determinable from array genotypes."
    assert result.confidence is None
    assert result.frequencies == ()
    assert result.confidence_frequency is None
    assert result.observation is None


def test_impossibility_refuses_runtime_genotype_evidence() -> None:
    card = _pack().by_id("synthetic_impossibility")
    assert card is not None
    match = MatchResult(card.id, MatchStatus.NOT_DETERMINABLE, "Not determinable.")

    with pytest.raises(EvidenceAssemblyError, match="cannot carry"):
        assemble_card(
            card,
            match,
            ObservationEvidence(call_source=CallSource.DIRECT, ancestry_match=1.0),
        )


def test_interpretation_refuses_impossibility_status() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    match = MatchResult(card.id, MatchStatus.NOT_DETERMINABLE, "Wrong kind.")

    with pytest.raises(EvidenceAssemblyError, match="belongs to impossibility"):
        assemble_card(card, match, ObservationEvidence(call_source=CallSource.DIRECT))


def test_pack_assembly_preserves_cardinality_and_order() -> None:
    pack = _pack()
    matches = tuple(
        MatchResult(
            card.id,
            (
                MatchStatus.NOT_DETERMINABLE
                if card.kind is CardKind.IMPOSSIBILITY
                else MatchStatus.MARKER_ABSENT
            ),
            card.impossibility_reason or "Marker absent.",
        )
        for card in pack.cards
    )

    observations = {
        card.id: ObservationEvidence(call_source=CallSource.DIRECT)
        for card in pack.cards
        if card.kind is CardKind.INTERPRETATION
    }
    results = assemble_pack(pack, matches, observations)

    assert len(results) == len(pack.cards)
    assert [result.card_id for result in results] == [card.id for card in pack.cards]


def test_one_incomplete_reference_row_does_not_cost_the_whole_pack() -> None:
    """The cardinality guarantee has to survive the reference being imperfect.

    gnomAD does not list every allele of every variant, and a strand-ambiguous site adds a
    complemented allele the reference may never have reported. Raising there loses every
    other card in the pack -- 30 good findings discarded because one row was thin, which
    is the low-confidence filtering AGENTS.md 0.1A forbids, arriving as an exception.
    """
    pack = _pack()
    interpretations = [card for card in pack.cards if card.kind is CardKind.INTERPRETATION]
    assert len(interpretations) >= 2, "the fixture must be able to show the pack surviving"
    thin = interpretations[0].id

    def homozygous(card: Card) -> str:
        assert card.match is not None
        return card.match.variant.key.alleles[0] * 2

    matches = tuple(
        (
            MatchResult(card.id, MatchStatus.NOT_DETERMINABLE, card.impossibility_reason or "")
            if card.kind is CardKind.IMPOSSIBILITY
            else replace(
                _matched(card.id),
                genotype=homozygous(card),
                observed_genotype=homozygous(card),
            )
        )
        for card in pack.cards
    )

    def priced(card: Card) -> tuple[PopulationFrequency, ...]:
        assert card.match is not None
        alleles = card.match.variant.key.alleles
        # The thin card is priced only for the allele it did not observe.
        wanted = alleles[1:] if card.id == thin else alleles
        return tuple(
            PopulationFrequency(allele, 0.30, "EUR", "synthetic-reference-v1") for allele in wanted
        )

    observations = {
        card.id: ObservationEvidence(call_source=CallSource.DIRECT, frequencies=priced(card))
        for card in pack.cards
        if card.kind is CardKind.INTERPRETATION
    }

    results = assemble_pack(pack, matches, observations)

    assert len(results) == len(pack.cards)
    degraded = next(result for result in results if result.card_id == thin)
    assert degraded.confidence_frequency is None
    assert any("No population frequency" in caveat for caveat in degraded.computed_caveats)
    intact = [
        result
        for result in results
        if result.card_id != thin and result.kind is CardKind.INTERPRETATION
    ]
    assert intact and all(result.confidence_frequency is not None for result in intact)


def test_pack_refuses_partial_or_misordered_matches() -> None:
    pack = _pack()
    matches = [MatchResult(card.id, MatchStatus.MARKER_ABSENT, "Absent.") for card in pack.cards]

    with pytest.raises(EvidenceAssemblyError, match="silently drop"):
        assemble_pack(pack, matches[:-1])

    reversed_matches = list(reversed(matches))
    with pytest.raises(EvidenceAssemblyError, match="order diverges"):
        assemble_pack(pack, reversed_matches)


def test_pack_refuses_runtime_evidence_for_unknown_card() -> None:
    pack = _pack()
    matches = [MatchResult(card.id, MatchStatus.MARKER_ABSENT, "Absent.") for card in pack.cards]

    with pytest.raises(EvidenceAssemblyError, match="unknown card"):
        assemble_pack(
            pack,
            matches,
            {"typo_card": ObservationEvidence(call_source=CallSource.DIRECT)},
        )


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_population_frequency_is_bounded_and_finite(value: float) -> None:
    with pytest.raises(EvidenceAssemblyError, match="frequency"):
        PopulationFrequency("A", value, "EUR", "synthetic-reference-v1")


def test_population_frequency_requires_allele_population_and_source() -> None:
    with pytest.raises(EvidenceAssemblyError, match="allele"):
        PopulationFrequency("I", 0.2, "EUR", "source")
    with pytest.raises(EvidenceAssemblyError, match="population"):
        PopulationFrequency("A", 0.2, "", "source")
    with pytest.raises(EvidenceAssemblyError, match="source"):
        PopulationFrequency("A", 0.2, "EUR", "")


def test_observation_provenance_enforces_imputation_metadata() -> None:
    with pytest.raises(EvidenceAssemblyError, match="requires imputation_quality"):
        ObservationEvidence(call_source=CallSource.IMPUTED)
    with pytest.raises(EvidenceAssemblyError, match="cannot carry imputation_quality"):
        ObservationEvidence(call_source=CallSource.DIRECT, imputation_quality=0.9)


def test_interpretation_requires_explicit_observation_provenance() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None

    with pytest.raises(EvidenceAssemblyError, match="requires ObservationEvidence"):
        assemble_card(card, _matched(card.id))


def test_frequency_records_must_be_unique_and_comparable() -> None:
    duplicate = PopulationFrequency("A", 0.8, "EUR", "source-v1")
    with pytest.raises(EvidenceAssemblyError, match="same allele"):
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=(duplicate, duplicate),
        )
    with pytest.raises(EvidenceAssemblyError, match="one population and source"):
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=(
                duplicate,
                PopulationFrequency("G", 0.2, "AFR", "source-v1"),
            ),
        )
    with pytest.raises(EvidenceAssemblyError, match="sum to more than 1"):
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=(
                PopulationFrequency("A", 0.8, "EUR", "source-v1"),
                PopulationFrequency("G", 0.3, "EUR", "source-v1"),
            ),
        )


@pytest.mark.parametrize("name", ["imputation_quality", "ancestry_match"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True])
def test_runtime_quality_inputs_are_validated_even_without_a_match(name: str, value: float) -> None:
    kwargs: dict[str, object] = {"call_source": CallSource.DIRECT, name: value}
    with pytest.raises(EvidenceAssemblyError, match=name):
        ObservationEvidence(**kwargs)  # type: ignore[arg-type]


@pytest.mark.privacy
def test_assembled_card_repr_never_prints_the_genotype_bearing_match() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    result = assemble_card(
        card,
        _matched(card.id),
        ObservationEvidence(call_source=CallSource.DIRECT),
    )

    rendered = repr(result)

    assert "AG" not in rendered
    assert "genotype" not in rendered.lower()
    assert card.id in rendered


def test_card_and_match_ids_must_agree() -> None:
    card = _pack().by_id("synthetic_dominant_trait")
    assert card is not None
    wrong = replace(_matched(card.id), card_id="different_card")

    with pytest.raises(EvidenceAssemblyError, match="different_card"):
        assemble_card(card, wrong)
