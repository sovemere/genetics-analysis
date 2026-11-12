"""Card search: the one ranking ``cards search`` and ``runs search`` share (roadmap M13.3).

Ranking is checked on invented documents, so each rule is tested alone. The committed pack
is then searched for every card's own id, title, gene and rsIDs, which is the property the
command exists for: a card can be found without knowing its id.
"""

from __future__ import annotations

import pytest

from genetics.engine import search as engine
from genetics.engine.cards import CardKind, KnowledgePack, default_knowledge_dir
from genetics.engine.search import Document, SearchField, parse_query, search, stem, tokenize
from genetics.privacy import find_genotypes

GENOTYPE_QUERY = "rs4988235" + ": " + "A" + "/" + "G"
"""An identifier with a call attached, assembled at runtime so this file holds none."""


@pytest.fixture(scope="module")
def pack() -> KnowledgePack:
    return KnowledgePack.load(default_knowledge_dir())


def _doc(name: str, /, **fields: str) -> Document:
    return Document(name, tuple((SearchField(key), text) for key, text in fields.items()))


def _ids(documents: list[Document], text: str) -> list[str]:
    return [hit.card_id for hit in search(documents, parse_query(text))]


# ---------------------------------------------------------------------------
# Words and stems
# ---------------------------------------------------------------------------


def test_text_splits_into_lowercase_runs_of_letters_and_digits() -> None:
    assert tokenize("WNT10A hair-curl association") == ["wnt10a", "hair", "curl", "association"]
    assert tokenize("wnt10a_hair_curl") == ["wnt10a", "hair", "curl"]
    assert tokenize("HLA-B*57:01") == ["hla", "b", "57", "01"]
    assert tokenize("10.1371/journal.pgen.1000993") == ["10", "1371", "journal", "pgen", "1000993"]
    assert tokenize("  ...  ") == []


@pytest.mark.parametrize(
    "words",
    [
        ("curl", "curls", "curly", "curlier", "curliest", "curliness", "curled", "curling"),
        ("hair", "hairs", "hairy"),
        ("taste", "tastes", "tasted", "tasting"),
        ("disease", "diseases"),
        ("allergy", "allergies"),
        ("smoke", "smoked", "smoking"),
        ("colour", "color", "colours", "colors", "coloured"),
        ("odour", "odor"),
        ("flush", "flushes", "flushing"),
        ("run", "running"),
        ("eye", "eyes"),
        ("gene", "genes"),
    ],
)
def test_forms_of_one_word_share_a_stem(words: tuple[str, ...]) -> None:
    assert len({stem(word) for word in words}) == 1, {word: stem(word) for word in words}


@pytest.mark.parametrize(
    "word", ["rs7349332", "wnt10a", "aldh2", "pgs000007", "c677t", "ace", "hla", "b12", "β"]
)
def test_identifiers_and_short_words_are_never_stemmed(word: str) -> None:
    assert stem(word) == word


def test_distinct_words_keep_distinct_stems() -> None:
    for left, right in (("hair", "heart"), ("curl", "cure"), ("class", "clay"), ("bed", "be")):
        assert stem(left) != stem(right), (left, right)
    # Short stems are refused rather than collapsed: "seed" is not "see" plus -ed.
    assert stem("seed") == "seed" and stem("ring") == "ring" and stem("status") == "status"


@pytest.mark.parametrize(
    ("word", "other"),
    [("note", "not"), ("none", "non"), ("rate", "rat"), ("site", "sit"), ("case", "cas")],
)
def test_a_four_letter_word_keeps_its_last_letter(word: str, other: str) -> None:
    """Review, 2026-11-12: ``note`` stemmed to ``not`` and matched nearly every card."""
    assert stem(word) == word != stem(other)
    assert stem(word + "s") == word
    documents = [_doc("card", summary=f"This is {other} about that.")]
    assert _ids(documents, word) == []


def test_a_search_for_note_does_not_list_every_card_that_says_not(pack: KnowledgePack) -> None:
    documents = [engine.pack_document(card) for card in pack.cards]
    note = search(documents, parse_query("note"))
    negated = search(documents, parse_query("not"))
    assert len(negated) > len(pack.cards) // 2
    assert 0 < len(note) < len(negated) // 4
    for hit in note:
        document = next(d for d in documents if d.card_id == hit.card_id)
        words = {word for _, text in document.fields for word in tokenize(text)}
        assert words & {"note", "notes", "noted", "noting"} or any(
            word.startswith("note") for word in words
        ), hit.card_id


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def test_a_query_is_split_once_per_word_and_common_words_are_reported() -> None:
    query = parse_query("  Risk of   the HEART disease, heart ")
    assert query.text == "Risk of the HEART disease, heart"
    assert query.terms == ("risk", "heart", "disease")
    assert query.ignored == ("of", "the")
    # The words as typed, repeats and dropped words included, for the side-by-side bonus.
    assert query.words == ("risk", "of", "the", "heart", "disease", "heart")


def test_a_query_of_only_common_words_is_searched_as_given() -> None:
    query = parse_query("what is it")
    assert query.terms == ("what", "is", "it") and query.ignored == ()


@pytest.mark.parametrize("text", ["", "   ", "?!", "--- ***", "_"])
def test_a_query_with_nothing_to_search_for_is_refused(text: str) -> None:
    with pytest.raises(engine.EmptyQueryError):
        parse_query(text)


@pytest.mark.privacy
def test_a_query_that_reads_as_a_genotype_is_refused_without_being_repeated() -> None:
    assert find_genotypes(GENOTYPE_QUERY)
    with pytest.raises(engine.GenotypeQueryError) as caught:
        parse_query(GENOTYPE_QUERY)
    assert find_genotypes(str(caught.value)) == []
    assert GENOTYPE_QUERY not in str(caught.value) and "rs4988235" not in str(caught.value)
    # The variant on its own is what a search is for.
    assert parse_query("rs4988235").terms == ("rs4988235",)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_exact_beats_stem_beats_prefix_within_one_field() -> None:
    documents = [
        _doc("prefix", title="curlicue"),
        _doc("stem", title="curly"),
        _doc("exact", title="curl"),
        _doc("none", title="straight"),
    ]
    hits = search(documents, parse_query("curl"))
    assert [hit.card_id for hit in hits] == ["exact", "stem", "prefix"]
    weight = engine.WEIGHTS[SearchField.TITLE]
    assert [hit.score for hit in hits] == [
        weight * engine.EXACT,
        weight * engine.STEM,
        weight * engine.PREFIX,
    ]


def test_a_title_outweighs_a_passing_mention() -> None:
    documents = [
        _doc("mention", caveats="Unrelated to earwax."),
        _doc("named", title="Earwax type"),
        _doc("cited", citations="A paper about earwax"),
    ]
    assert _ids(documents, "earwax") == ["named", "mention", "cited"]


def test_a_card_scores_each_term_once_at_its_best_field() -> None:
    document = _doc("card", title="hair", summary="hair hair hair", caveats="hair")
    (hit,) = search([document], parse_query("hair"))
    assert hit.score == engine.WEIGHTS[SearchField.TITLE]
    assert [(m.field, m.terms) for m in hit.matched] == [
        (SearchField.TITLE, ("hair",)),
        (SearchField.SUMMARY, ("hair",)),
        (SearchField.CAVEATS, ("hair",)),
    ]


def test_cards_matching_every_term_come_before_cards_matching_some() -> None:
    documents = [
        _doc("one-strong", title="hair", gene="hair", card_id="hair"),
        _doc("both-weak", citations="curly hair in mice"),
    ]
    hits = search(documents, parse_query("curly hair"))
    assert [(hit.card_id, hit.terms_matched) for hit in hits] == [
        ("both-weak", 2),
        ("one-strong", 1),
    ]
    assert hits[1].score > hits[0].score


def test_partial_matches_are_listed_not_dropped() -> None:
    """AGENTS.md 0.1A: rank, do not hide."""
    documents = [
        _doc("a", title="curly hair"),
        _doc("b", title="hair colour"),
        _doc("c", title="x"),
    ]
    assert _ids(documents, "curly hair") == ["a", "b"]


def test_terms_side_by_side_and_in_order_score_a_bonus() -> None:
    documents = [
        _doc("apart", summary="pressure in the blood"),
        _doc("together", summary="high blood pressure"),
        _doc("reversed", summary="pressure blood"),
    ]
    hits = {hit.card_id: hit.score for hit in search(documents, parse_query("blood pressure"))}
    weight = engine.WEIGHTS[SearchField.SUMMARY]
    assert hits["apart"] == hits["reversed"] == 2 * weight
    assert hits["together"] == 2 * weight + engine.PHRASE_BONUS * weight
    assert hits["together"] > hits["apart"]
    assert _ids(documents, "blood pressure") == ["together", "apart", "reversed"]
    # Stems count as side by side too: "curlier hair" holds "curly hair".
    assert search([_doc("s", summary="curlier hair")], parse_query("curly hair"))[0].score == (
        weight * engine.STEM + weight + engine.PHRASE_BONUS * weight
    )
    # A phrase does not run across two passages of one field.
    split = Document("split", ((SearchField.CAVEATS, "blood"), (SearchField.CAVEATS, "pressure")))
    assert search([split], parse_query("blood pressure"))[0].score == 2 * 1.5


def test_the_side_by_side_bonus_is_for_the_query_as_typed() -> None:
    """Review, 2026-11-12: dropped words were left out of the phrase, so text saying exactly
    what was asked earned nothing and text missing a word could."""
    documents = [
        _doc("as-asked", summary="the risk of heart disease in adults"),
        _doc("without", summary="risk heart disease"),
        _doc("apart", summary="heart risk and disease"),
    ]
    query = parse_query("risk of heart disease")
    assert query.terms == ("risk", "heart", "disease") and query.ignored == ("of",)
    hits = {hit.card_id: hit.score for hit in search(documents, query)}
    weight = engine.WEIGHTS[SearchField.SUMMARY]
    assert hits["as-asked"] == 3 * weight + engine.PHRASE_BONUS * weight
    assert hits["without"] == hits["apart"] == 3 * weight
    assert _ids(documents, "risk of heart disease")[0] == "as-asked"
    # One searched term is not a phrase, whatever common words came with it.
    (alone,) = search([_doc("card", summary="the earwax")], parse_query("the earwax"))
    assert alone.score == weight


def test_ties_keep_the_order_the_cards_came_in() -> None:
    documents = [_doc(name, title="earwax") for name in ("c", "a", "b")]
    assert _ids(documents, "earwax") == ["c", "a", "b"]


def test_a_prefix_needs_three_characters_and_is_never_a_bare_number() -> None:
    documents = [_doc("card", title="alcohol 677123 rs7349332")]
    assert _ids(documents, "alc") == ["card"]
    assert _ids(documents, "al") == []
    assert _ids(documents, "677") == []
    assert _ids(documents, "rs7349") == ["card"]
    # The start of a word, never its middle.
    assert _ids(documents, "cohol") == []


def test_matching_ignores_case_and_punctuation() -> None:
    documents = [_doc("card", gene="WNT10A", hla="HLA-B*57:01")]
    assert _ids(documents, "wnt10a") == _ids(documents, "WNT10A") == ["card"]
    (hit,) = search(documents, parse_query("B*57:01"))
    assert hit.terms_matched == 3


def test_the_weights_and_qualities_are_the_documented_ones() -> None:
    """docs/agent_cli.md states this table; an agent explains a hit from it."""
    assert (engine.EXACT, engine.STEM, engine.PREFIX) == (1.0, 0.75, 0.5)
    assert (engine.PHRASE_BONUS, engine.PREFIX_MIN_LENGTH) == (0.5, 3)
    assert {field.value: weight for field, weight in engine.WEIGHTS.items()} == {
        "title": 5.0,
        "gene": 5.0,
        "variant": 5.0,
        "card_id": 4.0,
        "trait": 4.0,
        "condition": 4.0,
        "hla": 4.0,
        "summary": 3.0,
        "impossibility_reason": 3.0,
        "detail": 2.0,
        "evidence": 2.0,
        "caveats": 1.5,
        "citations": 1.0,
        "section": 1.0,
    }
    assert len(engine.STOPWORDS) == 36


def test_every_field_has_a_weight_and_a_hit_reports_its_fields_in_declared_order() -> None:
    assert set(engine.WEIGHTS) == set(SearchField)
    assert all(weight > 0 for weight in engine.WEIGHTS.values())
    document = Document("card", tuple((field, "earwax") for field in reversed(SearchField)))
    (hit,) = search([document], parse_query("earwax"))
    assert [match.field for match in hit.matched] == list(SearchField)
    assert hit.to_dict() == {
        "card_id": "card",
        "score": 5.0,
        "terms_matched": 1,
        "matched": [{"field": field.value, "terms": ["earwax"]} for field in SearchField],
    }


# ---------------------------------------------------------------------------
# The committed pack
# ---------------------------------------------------------------------------


def _first(pack: KnowledgePack, text: str) -> list[str]:
    """The ids ranked first for ``text``: every hit tied with the top one."""
    hits = search([engine.pack_document(card) for card in pack.cards], parse_query(text))
    top = (hits[0].terms_matched, hits[0].score)
    return [hit.card_id for hit in hits if (hit.terms_matched, hit.score) == top]


def test_the_brief_s_example_finds_the_hair_curl_cards(pack: KnowledgePack) -> None:
    view = engine.pack_view(pack.cards, parse_query("curly hair"))
    full = [hit["card_id"] for hit in view["hits"] if hit["terms_matched"] == 2]
    assert full[0] == "wnt10a_hair_curl"
    assert {"wnt10a_hair_curl", "lce3e_region_hair_curl", "tchh_hair_morphology"} <= set(full)
    partial = [hit["card_id"] for hit in view["hits"] if hit["terms_matched"] == 1]
    assert "kitlg_blond_hair_enhancer" in partial
    assert view["searched"] == len(pack.cards) and view["total"] == len(view["hits"])
    assert view["hits"] == sorted(
        view["hits"], key=lambda hit: (-hit["terms_matched"], -hit["score"])
    )


@pytest.mark.parametrize(
    ("text", "card_id"),
    [
        ("earwax", "abcc11_earwax_type"),
        ("body odor", "abcc11_axillary_odor"),
        ("eye color", "herc2_oca2_eye_shade"),
        ("lactose", "mcm6_lactase_persistence"),
        ("rs7349332", "wnt10a_hair_curl"),
        ("WNT10A", "wnt10a_hair_curl"),
        ("biological age", "methylation_epigenetic_age"),
        ("MTHFR depression", "mthfr_c677t_depression"),
        ("warfarin", "vkorc1_guidelines"),
        ("abacavir", "hla_b5701_abacavir"),
        ("HLA-B*57:01", "hla_b5701_abacavir"),
    ],
)
def test_a_phrase_finds_the_card_it_is_about(pack: KnowledgePack, text: str, card_id: str) -> None:
    assert card_id in _first(pack, text), _first(pack, text)


def test_every_card_is_found_by_its_own_id_title_gene_and_rsids(pack: KnowledgePack) -> None:
    documents = [engine.pack_document(card) for card in pack.cards]

    def matched(text: str, card_id: str, field: SearchField) -> bool:
        query = parse_query(text)
        hit = next(hit for hit in search(documents, query) if hit.card_id == card_id)
        return hit.terms_matched == len(query.terms) and any(
            match.field is field and match.terms == query.terms for match in hit.matched
        )

    for card in pack.cards:
        assert card.id in _first(pack, card.id), card.id
        assert matched(card.id, card.id, SearchField.CARD_ID), card.id
        assert matched(card.title, card.id, SearchField.TITLE), card.id
        if card.gene:
            assert matched(card.gene, card.id, SearchField.GENE), card.id
        if card.match is not None:
            for variant in card.match.variants:
                assert matched(variant.rsid, card.id, SearchField.VARIANT), card.id
        if card.pgs is not None:
            assert matched(card.pgs.pgs_id, card.id, SearchField.TRAIT), card.id
        if card.carrier is not None:
            assert matched(card.carrier.condition, card.id, SearchField.CONDITION), card.id


def test_template_placeholders_are_not_searched(pack: KnowledgePack) -> None:
    """``{genotype}`` in an outcome template is a slot, not prose about genotypes."""
    card = pack.by_id("wnt10a_hair_curl")
    assert card is not None
    assert any("{genotype}" in outcome.summary for outcome in card.outcomes.values())
    document = engine.pack_document(card)
    words = {word for _, text in document.fields for word in tokenize(text)}
    assert "genotype" not in words and "effect_value" not in words and "value" not in words
    assert engine.template_text("Your {genotype} has {count} copies.") == "Your   has   copies."


def test_no_kind_of_card_is_left_out_of_the_pack_search(pack: KnowledgePack) -> None:
    """Assay-limit, computed, guideline and HLA cards are found like any other (0.1A, 0.1B)."""
    documents = [engine.pack_document(card) for card in pack.cards]
    assert len(documents) == len(pack.cards)
    for kind in CardKind:
        card = next(card for card in pack.cards if card.kind is kind)
        assert card.id in _first(pack, card.id), kind


@pytest.mark.privacy
def test_no_pack_search_result_holds_a_genotype(pack: KnowledgePack) -> None:
    """The runtime scan must never refuse correct output, or it gets switched off (M0.3)."""
    import json

    from genetics.cli.cards_cmd import search_text

    queries = {"curly hair", "risk of heart disease", "rs", "a c g t"}
    for card in pack.cards:
        queries |= {card.id, card.title, card.section.value}
        if card.gene:
            queries.add(card.gene)
        if card.match is not None:
            for variant in card.match.variants:
                queries.add(variant.rsid)
                queries.add(f"{variant.rsid} {' '.join(variant.key.alleles)}")
    for text in sorted(queries):
        view = engine.pack_view(pack.cards, parse_query(text))
        assert find_genotypes(json.dumps(view, indent=2, ensure_ascii=False)) == [], text
        assert find_genotypes(search_text(view)) == [], text
