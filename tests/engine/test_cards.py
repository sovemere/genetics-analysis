"""The card schema (roadmap M3.1).

Tests are organised by the rule each one defends, because the rules are the deliverable.
A permissive schema would pass a "does a valid card parse?" suite completely.

Cards are built from a minimal valid dict and mutated one field at a time, so a failure
names the rule rather than the fixture.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from genetics.engine.cards import (
    SCHEMA_VERSION,
    TEMPLATE_VARS,
    Ancestry,
    Card,
    CardError,
    CardKind,
    EffectMeasure,
    EvidenceTier,
    KnowledgePack,
    Replication,
    parse_file,
)
from genetics.engine.sections import Section
from genetics.privacy import find_genotypes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cards"


def _interpretation() -> dict[str, Any]:
    return {
        "id": "synth_card",
        "section": "traits",
        "kind": "interpretation",
        "title": "Synthetic card",
        "gene": "SYNTH1",
        "match": {
            "variants": [
                {
                    "rsid": "rs900000001",
                    "chrom": "7",
                    "pos_grch37": 12345678,
                    "alleles": ["A", "G"],
                }
            ],
            "genotypes": {"AA": "yes", "AG": "yes", "GG": "no"},
        },
        "outcomes": {
            "yes": {"summary": "Carries it.", "detail": "Long form."},
            "no": {"summary": "Does not.", "detail": "Long form."},
        },
        "evidence": {
            "tier": "gwas",
            "replication": "independent",
            "sample_size": 120000,
            "ancestry": ["EUR"],
            "effect": {"measure": "odds_ratio", "value": 1.4},
        },
        "citations": [
            {"type": "doi", "id": "10.1038/s41586-000-00000-0", "title": "A synthetic paper"}
        ],
    }


def _impossibility() -> dict[str, Any]:
    return {
        "id": "synth_impossible",
        "section": "genome_structure",
        "kind": "impossibility",
        "title": "Synthetic impossibility",
        "impossibility_reason": "The array measures genotypes, not this.",
        "summary": "Not determinable.",
        "detail": "The long form.",
    }


def _card(**changes: Any) -> Card:
    raw = _interpretation()
    raw.update(changes)
    return Card.parse(raw, "test")


def _mutate(path: list[str], value: Any) -> dict[str, Any]:
    """Return the base card with one nested key replaced. Use ``...`` to delete."""
    raw = copy.deepcopy(_interpretation())
    node: Any = raw
    for key in path[:-1]:
        node = node[key]
    if value is ...:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = value
    return raw


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_minimal_interpretation_card_parses() -> None:
    card = _card()
    assert card.kind is CardKind.INTERPRETATION
    assert card.section is Section.TRAITS
    assert card.evidence is not None
    assert card.evidence.tier is EvidenceTier.GWAS
    assert card.evidence.replication is Replication.INDEPENDENT
    assert card.evidence.ancestry == (Ancestry.EUR,)
    assert card.evidence.effect.measure is EffectMeasure.ODDS_RATIO
    assert str(card.variant_key) == "7:12345678:A/G"


def test_an_impossibility_card_parses_without_citations() -> None:
    """Deliberate: the claim is about the assay, not the person.

    Demanding a DOI for "an array does not measure methylation" pushes an author toward
    citing something tangentially related, which is worse for a reader than citing nothing.
    """
    card = Card.parse(_impossibility(), "test")
    assert card.kind is CardKind.IMPOSSIBILITY
    assert card.citations == ()
    assert card.match is None


def test_genotype_keys_are_sorted_before_comparison() -> None:
    """``GA`` and ``AG`` are one genotype; the normalized table sorts alleles at ingest."""
    card = Card.parse(_mutate(["match", "genotypes"], {"AA": "yes", "GA": "yes", "GG": "no"}), "t")
    assert card.match is not None
    assert set(card.match.genotypes) == {"AA", "AG", "GG"}


def test_the_genotype_vocabulary_is_the_same_on_a_haploid_chromosome() -> None:
    """The normalized table writes a haploid call doubled and puts ploidy in call_status.

    A card therefore does not need to know the sample's sex in order to be exhaustive --
    which is what keeps the exhaustiveness rule decidable at load time, with no reference
    data and no QC result.
    """
    raw = _mutate(
        ["match", "variants"],
        [{"rsid": "rs900000002", "chrom": "Y", "pos_grch37": 2655180, "alleles": ["C", "T"]}],
    )
    raw["match"]["genotypes"] = {"CC": "yes", "CT": "yes", "TT": "no"}
    card = Card.parse(raw, "t")
    assert card.match is not None
    assert card.match.variant.genotypes == ("CC", "CT", "TT")


# ---------------------------------------------------------------------------
# Rule: a card cannot author its own confidence (AGENTS.md 6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["confidence", "tier", "score", "reliability"])
def test_a_card_cannot_state_its_own_confidence(key: str) -> None:
    """The single most important refusal in the schema.

    If a card could assert ``confidence: high``, M3.3's calculator becomes decorative and
    the rarity inversion of AGENTS.md 4.1 -- the thing it calls the most important message
    in the interface -- is overridable by whoever authored the card.
    """
    raw = _interpretation()
    raw[key] = "high"
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "test")
    assert "M3.3" in str(caught.value)


def test_evidence_tier_is_still_authored() -> None:
    """The inverse must keep working: inputs are authored, the output is not.

    A guard that rejected every field with 'tier' in the name would also break the
    evidence block, and the schema would have no way to say how strong a source is.
    """
    assert _card().evidence is not None


def test_the_two_ladders_do_not_share_vocabulary() -> None:
    """``evidence.tier`` and the computed confidence must not be confusable by eye.

    M3.3 emits ``well-established``..``likely-artifact``. If an evidence tier were spelled
    the same way, a reader could not tell an authored input from a computed output, which
    is the confusion the whole rule above is defending against.
    """
    computed = {"well_established", "well-established", "likely_artifact", "likely-artifact"}
    assert not {t.value for t in EvidenceTier} & computed


# ---------------------------------------------------------------------------
# Rule: the genotype map must be exhaustive
# ---------------------------------------------------------------------------


def test_a_missing_genotype_is_refused() -> None:
    """ "No result" is indistinguishable from "no variant" -- ingest/keys.py's warning,
    applied at the card level."""
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["match", "genotypes"], {"AA": "yes", "GG": "no"}), "t")
    assert "AG" in str(caught.value)


def test_a_genotype_outside_the_declared_alleles_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        Card.parse(
            _mutate(["match", "genotypes"], {"AA": "yes", "AG": "yes", "GG": "no", "AC": "no"}),
            "t",
        )
    assert "not constructible" in str(caught.value)


def test_a_genotype_mapped_twice_under_different_orderings_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        Card.parse(
            _mutate(["match", "genotypes"], {"AA": "yes", "AG": "yes", "GA": "no", "GG": "no"}),
            "t",
        )
    assert "twice" in str(caught.value)


def test_a_three_allele_variant_needs_all_six_genotypes() -> None:
    raw = _mutate(
        ["match", "variants"],
        [{"rsid": "rs900000003", "chrom": "1", "pos_grch37": 100, "alleles": ["A", "C", "G"]}],
    )
    raw["match"]["genotypes"] = {"AA": "yes", "AC": "yes", "AG": "yes", "CC": "no", "CG": "no"}
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "GG" in str(caught.value)


# ---------------------------------------------------------------------------
# Rule: outcomes and the genotype map must agree
# ---------------------------------------------------------------------------


def test_a_genotype_pointing_at_an_undefined_outcome_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["match", "genotypes"], {"AA": "yes", "AG": "yes", "GG": "maybe"}), "t")
    assert "maybe" in str(caught.value)


def test_an_unused_outcome_is_refused() -> None:
    """Usually a renamed outcome or a typo -- either way some genotype renders text
    nobody intended, which is worse than an error."""
    raw = _interpretation()
    raw["outcomes"]["leftover"] = {"summary": "x", "detail": "y"}
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "leftover" in str(caught.value)


# ---------------------------------------------------------------------------
# Rule: citations
# ---------------------------------------------------------------------------


def test_an_interpretation_card_without_citations_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["citations"], []), "t")
    assert "citation" in str(caught.value)


def test_a_missing_citations_key_is_refused_too() -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["citations"], ...), "t")


# ---------------------------------------------------------------------------
# Rule: variants carry both an rsID and coordinates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["rsid", "chrom", "pos_grch37", "alleles"])
def test_every_variant_field_is_required(key: str) -> None:
    """rsID *and* coordinates, so M3.5 can cross-check them against dbSNP. Either alone is
    unverifiable, and a disagreement means one of them is wrong."""
    variant = _interpretation()["match"]["variants"][0]
    trimmed = {k: v for k, v in variant.items() if k != key}
    with pytest.raises(CardError):
        Card.parse(_mutate(["match", "variants"], [trimmed]), "t")


@pytest.mark.parametrize("bad", ["RS900000001", "rs0", "900000001", "rsid", "rs"])
def test_a_malformed_rsid_is_refused(bad: str) -> None:
    raw = _interpretation()
    raw["match"]["variants"][0]["rsid"] = bad
    with pytest.raises(CardError):
        Card.parse(raw, "t")


@pytest.mark.parametrize("bad", ["23", "24", "25", "26", "chr7", "0", "MTDNA"])
def test_vendor_chromosome_codes_are_refused(bad: str) -> None:
    """M1.1's rule, enforced on the authoring side as well as the parsing side."""
    raw = _interpretation()
    raw["match"]["variants"][0]["chrom"] = bad
    with pytest.raises(CardError):
        Card.parse(raw, "t")


@pytest.mark.parametrize("bad", [0, -1, "12345678"])
def test_a_non_positive_position_is_refused(bad: Any) -> None:
    raw = _interpretation()
    raw["match"]["variants"][0]["pos_grch37"] = bad
    with pytest.raises(CardError):
        Card.parse(raw, "t")


@pytest.mark.parametrize("alleles", [["I", "D"], ["A", "D"], ["I", "G"]])
def test_indel_alleles_are_refused(alleles: list[str]) -> None:
    """AGENTS.md 4.2: no sequence is recorded and either state may be the reference, so a
    wrong guess reports the opposite genotype rather than failing. M1.6 models the
    whitelist and nothing wires it up, so accepting one here would be an unbacked claim."""
    raw = _interpretation()
    raw["match"]["variants"][0]["alleles"] = alleles
    raw["match"]["genotypes"] = {}
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "4.2" in str(caught.value)


def test_the_no_call_token_is_not_an_allele() -> None:
    raw = _interpretation()
    raw["match"]["variants"][0]["alleles"] = ["A", "0"]
    raw["match"]["genotypes"] = {}
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "no-call" in str(caught.value)


def test_a_monomorphic_variant_is_refused() -> None:
    raw = _interpretation()
    raw["match"]["variants"][0]["alleles"] = ["A", "A"]
    raw["match"]["genotypes"] = {"AA": "yes"}
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "distinct" in str(caught.value)


def test_multi_variant_cards_are_refused_with_a_pointer_to_m10() -> None:
    """Declared shape, refused data -- the M2.1 precedent. A genotype cross-product is not
    haplotype calling, and pretending otherwise would give a different, wrong answer."""
    raw = _interpretation()
    raw["match"]["variants"].append(
        {"rsid": "rs900000009", "chrom": "7", "pos_grch37": 12345999, "alleles": ["C", "T"]}
    )
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "M10" in str(caught.value)


# ---------------------------------------------------------------------------
# Rule: effect sizes carry units where units mean something
# ---------------------------------------------------------------------------


def test_a_beta_without_units_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["evidence", "effect"], {"measure": "beta", "value": 0.3}), "t")
    assert "units" in str(caught.value)


def test_a_beta_with_units_parses() -> None:
    card = Card.parse(
        _mutate(["evidence", "effect"], {"measure": "beta", "value": 0.3, "units": "cm"}), "t"
    )
    assert card.evidence is not None
    assert card.evidence.effect.units == "cm"


def test_units_on_a_dimensionless_measure_are_refused() -> None:
    """Otherwise ``units: OR`` and ``units: ""`` get into the corpus and mean nothing."""
    with pytest.raises(CardError):
        Card.parse(
            _mutate(["evidence", "effect"], {"measure": "odds_ratio", "value": 1.4, "units": "OR"}),
            "t",
        )


@pytest.mark.parametrize("value", [1.5, -0.1, 40])
def test_a_proportion_outside_zero_to_one_is_refused(value: float) -> None:
    """A percentage typed as a proportion is the usual cause, and it silently inflates."""
    with pytest.raises(CardError):
        Card.parse(_mutate(["evidence", "effect"], {"measure": "penetrance", "value": value}), "t")


def test_a_generic_proportion_requires_numerator_denominator_context() -> None:
    with pytest.raises(CardError, match="numerator and denominator"):
        Card.parse(
            _mutate(["evidence", "effect"], {"measure": "proportion", "value": 0.8}),
            "t",
        )

    card = Card.parse(
        _mutate(
            ["evidence", "effect"],
            {
                "measure": "proportion",
                "value": 0.8,
                "context": "synthetic concordance (8 of 10 participants)",
            },
        ),
        "t",
    )
    assert card.evidence is not None
    assert card.evidence.effect.context == "synthetic concordance (8 of 10 participants)"


def test_a_non_positive_odds_ratio_is_refused() -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["evidence", "effect"], {"measure": "odds_ratio", "value": 0}), "t")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_effect_value_is_refused(value: float) -> None:
    with pytest.raises(CardError, match="finite"):
        Card.parse(
            _mutate(["evidence", "effect"], {"measure": "odds_ratio", "value": value}),
            "t",
        )


@pytest.mark.parametrize("value", [-0.1, 100.1])
def test_percent_variance_explained_is_bounded(value: float) -> None:
    with pytest.raises(CardError, match="between 0 and 100"):
        Card.parse(
            _mutate(
                ["evidence", "effect"],
                {"measure": "percent_variance_explained", "value": value},
            ),
            "t",
        )


def test_a_value_outside_its_own_interval_is_refused() -> None:
    """The transcription check: one of the three numbers is wrong and nothing else says so."""
    with pytest.raises(CardError) as caught:
        Card.parse(
            _mutate(
                ["evidence", "effect"],
                {"measure": "odds_ratio", "value": 1.4, "ci_low": 1.5, "ci_high": 1.9},
            ),
            "t",
        )
    assert "outside its own interval" in str(caught.value)


def test_half_an_interval_is_refused() -> None:
    with pytest.raises(CardError):
        Card.parse(
            _mutate(["evidence", "effect"], {"measure": "odds_ratio", "value": 1.4, "ci_low": 1.2}),
            "t",
        )


@pytest.mark.parametrize("bound", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_interval_bounds_are_refused(bound: float) -> None:
    with pytest.raises(CardError, match="finite"):
        Card.parse(
            _mutate(
                ["evidence", "effect"],
                {"measure": "odds_ratio", "value": 1.4, "ci_low": 1.2, "ci_high": bound},
            ),
            "t",
        )


# ---------------------------------------------------------------------------
# Rule: evidence describes a real study
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -5, "many", 1.5, True])
def test_a_non_positive_sample_size_is_refused(bad: Any) -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["evidence", "sample_size"], bad), "t")


def test_an_unknown_ancestry_label_is_refused() -> None:
    """Free text here would make M9.5's portability adjustment incomputable: "European",
    "EUR" and "White British" cannot be compared against an inferred ancestry."""
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["evidence", "ancestry"], ["European"]), "t")
    assert "M5.3" in str(caught.value)


def test_unknown_ancestry_is_recordable() -> None:
    """An unstated study population is a real and common property of the literature.

    Forcing a guess would be worse than recording the gap -- M9.5 has to be able to see it.
    """
    card = Card.parse(_mutate(["evidence", "ancestry"], ["UNKNOWN"]), "t")
    assert card.evidence is not None
    assert card.evidence.ancestry == (Ancestry.UNKNOWN,)


def test_an_empty_ancestry_list_is_refused() -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["evidence", "ancestry"], []), "t")


@pytest.mark.parametrize("bad", [0, 40, -0.5, 2.0])
def test_an_implausible_within_family_attenuation_is_refused(bad: float) -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["evidence", "within_family_attenuation"], bad), "t")


def test_candidate_gene_is_its_own_tier() -> None:
    """Not banned -- AGENTS.md 0.1A labels rather than filters -- but visibly weak."""
    card = Card.parse(_mutate(["evidence", "tier"], "candidate_gene"), "t")
    assert card.evidence is not None
    assert card.evidence.tier is EvidenceTier.CANDIDATE_GENE
    assert card.evidence.tier.rank > EvidenceTier.GWAS.rank


def test_replication_is_orthogonal_to_tier() -> None:
    """A GWAS hit nobody replicated and a candidate-gene claim replicated four times are
    different animals, and one field cannot say both."""
    card = Card.parse(_mutate(["evidence", "replication"], "conflicting"), "t")
    assert card.evidence is not None
    assert card.evidence.tier is EvidenceTier.GWAS
    assert card.evidence.replication is Replication.CONFLICTING


# ---------------------------------------------------------------------------
# Rule: templates name placeholders that exist and can be filled
# ---------------------------------------------------------------------------


def test_an_unknown_placeholder_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["outcomes", "yes", "summary"], "You have {genotpye}."), "t")
    assert "genotpye" in str(caught.value)


def test_a_placeholder_from_an_unbuilt_milestone_is_refused_by_name() -> None:
    """The M2.1 precedent again: declared, validated, not executed.

    ``{frequency}`` is a real placeholder that M7.2 will supply. Accepting it now would
    render blank; refusing it without naming the milestone would look like a typo.
    """
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["outcomes", "yes", "summary"], "Frequency {frequency}."), "t")
    assert "M7.2" in str(caught.value)


def test_confidence_placeholder_is_available_after_m3_3() -> None:
    card = Card.parse(_mutate(["outcomes", "yes", "summary"], "Confidence: {confidence}."), "t")

    assert card.outcomes["yes"].summary == "Confidence: {confidence}."
    assert TEMPLATE_VARS["confidence"].available


def test_impossibility_card_cannot_claim_a_confidence_placeholder() -> None:
    """No genotype is observed and no evidence is scored for an impossibility card."""

    raw = _impossibility()
    raw["summary"] = "Confidence: {confidence}."
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "matches no variant" in str(caught.value)


def test_a_format_spec_is_refused() -> None:
    """Card templates are plain named substitutions. Formatting belongs in code where it
    can be tested, and a spec is also the first step toward attribute access."""
    with pytest.raises(CardError):
        Card.parse(_mutate(["outcomes", "yes", "summary"], "You have {genotype:>10}."), "t")


def test_a_conversion_is_refused() -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["outcomes", "yes", "summary"], "You have {genotype!r}."), "t")


def test_a_positional_placeholder_is_refused() -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["outcomes", "yes", "summary"], "You have {}."), "t")


def test_an_empty_template_is_refused() -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["outcomes", "yes", "detail"], "   "), "t")


def test_every_declared_placeholder_is_either_available_or_names_a_milestone() -> None:
    """The registry's own invariant. An unavailable placeholder with no milestone would
    produce "unknown placeholder" for something the schema itself declares."""
    for var in TEMPLATE_VARS.values():
        assert var.available or var.milestone


# ---------------------------------------------------------------------------
# Rule: the two kinds do not blur
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["match", "outcomes", "evidence"])
def test_an_impossibility_card_cannot_carry_matching_fields(key: str) -> None:
    raw = _impossibility()
    raw[key] = _interpretation()[key]
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "impossibility" in str(caught.value)


@pytest.mark.parametrize("key", ["impossibility_reason", "summary", "detail"])
def test_an_interpretation_card_cannot_carry_impossibility_fields(key: str) -> None:
    raw = _interpretation()
    raw[key] = "text"
    with pytest.raises(CardError):
        Card.parse(raw, "t")


def test_an_impossibility_card_must_say_why() -> None:
    raw = _impossibility()
    del raw["impossibility_reason"]
    with pytest.raises(CardError):
        Card.parse(raw, "t")


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["kind"], "guess"), "t")
    assert "interpretation" in str(caught.value)


# ---------------------------------------------------------------------------
# Rule: typos do not pass silently
# ---------------------------------------------------------------------------


def test_an_unknown_card_key_is_refused() -> None:
    raw = _interpretation()
    raw["titel"] = "typo"
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "titel" in str(caught.value)


def test_an_unknown_evidence_key_is_refused() -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["evidence", "populaton"], "EUR"), "t")


def test_an_unknown_outcome_key_is_refused() -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["outcomes", "yes"], {"summary": "x", "detail": "y", "note": "z"}), "t")


@pytest.mark.parametrize("bad", ["Synth_Card", "synth-card", "synth card", "synth.card", ""])
def test_a_malformed_card_id_is_refused(bad: str) -> None:
    """Ids appear in CLI arguments, URLs and run bundles."""
    with pytest.raises(CardError):
        Card.parse(_mutate(["id"], bad), "t")


def test_a_leading_digit_is_allowed_in_an_id() -> None:
    """Same rule as manifest source ids. Gene-derived names like ``5htt`` are legitimate,
    and a card id is a path and URL segment, not a Python identifier."""
    assert Card.parse(_mutate(["id"], "5htt_synthetic"), "t").id == "5htt_synthetic"


def test_an_unknown_section_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["section"], "traits_and_things"), "t")
    assert "thirteen" in str(caught.value)


def test_the_error_names_the_card_it_came_from() -> None:
    """A pack error that names only the file is useless once a file holds several cards."""
    with pytest.raises(CardError) as caught:
        Card.parse(_mutate(["evidence", "sample_size"], 0), "somefile.yaml")
    assert "synth_card" in str(caught.value)


# ---------------------------------------------------------------------------
# File and pack level
# ---------------------------------------------------------------------------


def _file(cards: list[dict[str, Any]], version: int = SCHEMA_VERSION) -> str:
    return yaml.safe_dump({"schema_version": version, "cards": cards}, sort_keys=False)


def test_a_file_parses() -> None:
    assert len(parse_file(_file([_interpretation(), _impossibility()]), "f.yaml")) == 2


def test_a_future_schema_version_is_refused() -> None:
    """Run bundles record the knowledge-pack version and must be re-readable later (M4.2),
    so a reader that does not recognise the version refuses rather than guessing."""
    with pytest.raises(CardError) as caught:
        parse_file(_file([_interpretation()], version=SCHEMA_VERSION + 1), "f.yaml")
    assert "schema_version" in str(caught.value)


def test_a_missing_schema_version_is_refused() -> None:
    with pytest.raises(CardError):
        parse_file(yaml.safe_dump({"cards": [_interpretation()]}), "f.yaml")


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(CardError):
        parse_file("", "f.yaml")


def test_a_file_with_no_cards_is_refused() -> None:
    with pytest.raises(CardError):
        parse_file(_file([]), "f.yaml")


def test_invalid_yaml_is_refused() -> None:
    with pytest.raises(CardError) as caught:
        parse_file("schema_version: 1\ncards: [unclosed", "f.yaml")
    assert "YAML" in str(caught.value)


def test_the_fixture_pack_loads() -> None:
    pack = KnowledgePack.load(FIXTURES)
    assert len(pack) == 3
    assert pack.by_id("synthetic_dominant_trait") is not None
    assert pack.by_id("nope") is None
    assert len(pack.in_section(Section.TRAITS)) == 1


def test_duplicate_ids_across_files_are_refused(tmp_path: Path) -> None:
    """Ids address cards from the CLI and from run bundles, so they must be unique."""
    (tmp_path / "a.yaml").write_text(_file([_interpretation()]), encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_file([_interpretation()]), encoding="utf-8")
    with pytest.raises(CardError) as caught:
        KnowledgePack.load(tmp_path)
    assert "duplicate" in str(caught.value)
    assert "a.yaml" in str(caught.value) and "b.yaml" in str(caught.value)


def test_empty_sections_are_reported_not_inferred(tmp_path: Path) -> None:
    """The definition of done forbids a silently empty section, and a caller cannot render
    "nothing determinable here, because X" without being told which sections need it."""
    (tmp_path / "a.yaml").write_text(_file([_interpretation()]), encoding="utf-8")
    pack = KnowledgePack.load(tmp_path)
    assert Section.TRAITS not in pack.empty_sections
    assert Section.PSYCHOMETRICS in pack.empty_sections
    assert len(pack.empty_sections) == 12


def test_a_missing_knowledge_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(CardError):
        KnowledgePack.load(tmp_path / "nope")


def test_a_yml_file_is_refused_rather_than_skipped(tmp_path: Path) -> None:
    """The glob takes .yaml only, so a .yml card would load as nothing at all.

    No error, no card, and a missing card looks exactly like a card that did not match --
    the confusion the whole schema is organised against. Refused loudly instead.
    """
    (tmp_path / "a.yaml").write_text(_file([_interpretation()]), encoding="utf-8")
    (tmp_path / "b.yml").write_text(_file([_impossibility()]), encoding="utf-8")
    with pytest.raises(CardError) as caught:
        KnowledgePack.load(tmp_path)
    assert "b.yml" in str(caught.value)


def test_the_committed_m3_6_seed_pack_has_reviewable_traits_coverage() -> None:
    """M3.6 is a deliberately small, hand-reviewable traits seed pack.

    The range prevents both accidental disappearance and an unreviewable bulk import.
    Exact IDs pin the high-confidence demonstrations promised by the roadmap without
    coupling this acceptance test to every editorial addition in the pack.
    """
    from genetics.engine.cards import default_knowledge_dir

    root = default_knowledge_dir()
    pack = KnowledgePack.load(root)
    traits = pack.in_section(Section.TRAITS)
    assert 25 <= len(traits) <= 40

    required = {
        "abcc11_earwax_type",
        "tas2r38_prop_ptc_bitterness",
        "mcm6_lactase_persistence",
        "herc2_oca2_eye_shade",
        "mc1r_r151c_red_hair",
    }
    assert required <= {card.id for card in traits}


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_card_files_do_not_trip_the_genotype_scanner() -> None:
    """Cards are committed, so the pre-commit content scan runs over every one of them.

    This is not hypothetical tidiness: a card names an rsID, a chromosome, a position and
    several genotypes, which is exactly the shape of an export row. Had the natural YAML
    layout tripped the scanner, every card commit would have been blocked and the fix
    people would reach for is ``--no-verify`` -- which the hook explicitly says is not
    acceptable. Checked here so the schema is what adapts, not the guard.
    """
    for path in sorted(FIXTURES.rglob("*.yaml")):
        assert find_genotypes(path.read_text(encoding="utf-8")) == [], path


# ---------------------------------------------------------------------------
# Review-pass fixes
# ---------------------------------------------------------------------------


def test_unquoted_yes_no_outcome_names_are_refused_not_coerced() -> None:
    """Found in review, and the trap is as natural as it gets.

    ``yes``/``no`` are the obvious outcome names for a binary trait, and unquoted they are
    YAML 1.1 *booleans*. ``str()``-coercing both sides "works" -- the card renders with an
    outcome literally named ``False`` and nobody finds out. Quote one side and not the
    other and they stop matching, with an error blaming an outcome the author can see is
    right there in the file.
    """
    text = """
schema_version: 1
cards:
  - id: coerced
    section: traits
    kind: interpretation
    title: Coerced outcome names
    match:
      variants:
        - rsid: rs900000001
          chrom: "7"
          pos_grch37: 12345678
          alleles: [A, G]
      genotypes:
        AA: yes
        AG: yes
        GG: no
    outcomes:
      yes:
        summary: "Carries it."
        detail: "Long form."
      no:
        summary: "Does not."
        detail: "Long form."
    evidence:
      tier: gwas
      replication: independent
      sample_size: 1000
      ancestry: [EUR]
      effect: {measure: odds_ratio, value: 1.4}
    citations:
      - type: doi
        id: 10.1038/x000000
        title: A synthetic paper
"""
    with pytest.raises(CardError) as caught:
        parse_file(text, "f.yaml")
    message = str(caught.value)
    assert "quoted" in message.lower()
    assert "YAML 1.1" in message or "YAML" in message


def test_quoting_them_works() -> None:
    """The fix has to be the thing the error message tells you to do."""
    raw = _interpretation()
    raw["match"]["genotypes"] = {"AA": "yes", "AG": "yes", "GG": "no"}
    raw["outcomes"] = {
        "yes": {"summary": "Carries it.", "detail": "Long form."},
        "no": {"summary": "Does not.", "detail": "Long form."},
    }
    assert Card.parse(raw, "t").outcomes.keys() == {"yes", "no"}


@pytest.mark.parametrize("bad", [True, False, None, 2, 1.5])
def test_no_yaml_scalar_sneaks_through_as_an_outcome_name(bad: object) -> None:
    with pytest.raises(CardError):
        Card.parse(_mutate(["match", "genotypes"], {"AA": bad, "AG": "yes", "GG": "no"}), "t")


@pytest.mark.parametrize("written", ["traits", "Traits", "TRAITS", "  traits  "])
def test_section_names_are_normalised_like_every_other_enum_field(written: str) -> None:
    """``kind: Interpretation`` parsed while ``section: Traits`` did not -- an
    inconsistency an author discovers one field at a time."""
    assert Card.parse(_mutate(["section"], written), "t").section is Section.TRAITS


def test_outcome_names_that_collide_after_trimming_are_refused() -> None:
    """Names are stripped so they line up with the genotype map, so two distinct YAML keys
    can collapse into one. A dict comprehension kept the last quietly, and the other
    outcome -- with its own summary and detail -- would never render."""
    raw = _interpretation()
    raw["outcomes"] = {
        "yes": {"summary": "Carries it.", "detail": "Long form."},
        " yes ": {"summary": "Also carries it.", "detail": "Different long form."},
        "no": {"summary": "Does not.", "detail": "Long form."},
    }
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "twice" in str(caught.value)


# ---------------------------------------------------------------------------
# Agent-review fixes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["1.2 (approx)", [1.2], {"v": 1.2}, True])
def test_a_non_numeric_confidence_interval_raises_a_located_card_error(bad: Any) -> None:
    """It went straight to ``float()`` while every other numeric field had an isinstance
    guard. A string raised an unlocated ValueError naming neither file nor key, and a list
    raised TypeError -- which is not a ValueError, so it escaped every ``except CardError``
    in the call chain. The loader's contract is that a bad card yields a located CardError.
    """
    with pytest.raises(CardError) as caught:
        Card.parse(
            _mutate(
                ["evidence", "effect"],
                {"measure": "odds_ratio", "value": 1.4, "ci_low": bad, "ci_high": 1.9},
            ),
            "somefile.yaml",
        )
    assert "ci_low" in str(caught.value)


def test_an_impossibility_card_cannot_use_match_placeholders() -> None:
    """It matches no variant and carries no evidence, so they render blank.

    The milestone gate already refused placeholders no *milestone* can supply; this is the
    same rule for what no *card* can supply, which review found open.
    """
    raw = _impossibility()
    raw["summary"] = "Your {genotype} at {rsid} means nothing here."
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "genotype" in str(caught.value)


def test_a_card_cannot_use_gene_without_declaring_one() -> None:
    raw = _interpretation()
    del raw["gene"]
    raw["outcomes"]["yes"]["summary"] = "Something about {gene}."
    with pytest.raises(CardError) as caught:
        Card.parse(raw, "t")
    assert "gene" in str(caught.value)


def test_declaring_a_gene_makes_the_placeholder_available() -> None:
    """The inverse, so the check cannot be satisfied by refusing everything."""
    raw = _interpretation()
    raw["outcomes"]["yes"]["summary"] = "Something about {gene}."
    assert Card.parse(raw, "t").gene == "SYNTH1"


def test_an_impossibility_card_keeps_its_gene() -> None:
    """AGENTS.md 3.2's own examples are gene-named -- SMN1 copy number, RHD, CYP2D6
    hybrids -- so naming one is legitimate. It was parsed and then silently dropped, a key
    accepted with no effect, which this module's docstring calls out by name.
    """
    raw = _impossibility()
    raw["gene"] = "SMN1"
    raw["summary"] = "Copy number at {gene} is not determinable."
    card = Card.parse(raw, "t")
    assert card.gene == "SMN1"


def test_an_uppercase_yaml_extension_is_refused_not_skipped(tmp_path: Path) -> None:
    """``rglob`` is case-insensitive on Windows and case-sensitive on Linux, so a file
    committed as ``traits.YAML`` loads on the author's machine and vanishes in CI -- the
    very failure the stray-file guard was written for, reintroduced by its own glob."""
    (tmp_path / "a.yaml").write_text(_file([_interpretation()]), encoding="utf-8")
    (tmp_path / "b.YAML").write_text(_file([_impossibility()]), encoding="utf-8")
    with pytest.raises(CardError) as caught:
        KnowledgePack.load(tmp_path)
    assert "b.YAML" in str(caught.value)


def test_unrelated_files_in_the_knowledge_directory_are_still_ignored(tmp_path: Path) -> None:
    """The guard must not start rejecting the README the directory is documented with."""
    (tmp_path / "a.yaml").write_text(_file([_interpretation()]), encoding="utf-8")
    (tmp_path / "README.md").write_text("# notes", encoding="utf-8")
    assert len(KnowledgePack.load(tmp_path)) == 1
