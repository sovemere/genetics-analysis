"""Card search: one ranking, over the knowledge pack or over a saved run (roadmap M13.3).

An agent asked about "curly hair" does not know the card is called ``wnt10a_hair_curl``.
``genetics cards search`` and ``genetics runs search`` find it, and both call
:func:`search` here. M14.4's dashboard search must call it too (AGENTS.md 3: one engine,
two front-ends), which is why it takes plain :class:`Document` records rather than a pack
or a bundle. :func:`pack_document` builds one from an authored card;
:func:`genetics.run.reads.search_document` builds one from a saved card.

**The ranking is small enough to state in full**, because an agent has to be able to say
why a card came back:

* Text is case-folded and split into runs of letters and digits. ``wnt10a_hair_curl``
  is three words; ``HLA-B*57:01`` is four.
* A query word matches a word in a field exactly (quality 1), by a shared stem (0.75,
  see :func:`stem`), or as the start of a longer word (0.5; three characters or more, and
  not a bare number).
* Each field has a weight (:data:`WEIGHTS`). A query word scores its best weight times
  quality over all fields, and a card's score is the sum over the query's words. Where
  every word of the query appears side by side and in order within one field, half that
  field's weight is added.
* Cards are ordered by how many of the query's words they match, then by score, then by
  the order they were given in. A card that matches one word of two is still listed, below
  every card that matches both: partial matches are ranked, not hidden (AGENTS.md 0.1A).

Nothing is weighted by confidence tier, status or result. A search finds cards; what a
card says is read from the card.

**A query is a variant, gene or trait, never a call at one.** :func:`parse_query` refuses
text the privacy scanner reads as a genotype, before anything is searched or echoed
(AGENTS.md 1.3).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any, Final

from genetics.engine import sections
from genetics.engine.cards import Card
from genetics.privacy import looks_like_genotype


class SearchField(StrEnum):
    """Where in a card a query word was found. Reported with every hit."""

    CARD_ID = "card_id"
    TITLE = "title"
    GENE = "gene"
    VARIANT = "variant"
    """rsIDs the card reads. Never a call at one."""
    TRAIT = "trait"
    """A polygenic card's trait and PGS Catalog id."""
    CONDITION = "condition"
    """A carrier card's condition and the allele it types, as a reader knows it."""
    HLA = "hla"
    """The HLA alleles an HLA card reads."""
    SUMMARY = "summary"
    """The card face. In the pack, every outcome's face with its placeholders removed; in a
    saved run, the one face that run recorded."""
    DETAIL = "detail"
    IMPOSSIBILITY_REASON = "impossibility_reason"
    EVIDENCE = "evidence"
    """The published effect's units and context sentence."""
    CAVEATS = "caveats"
    CITATIONS = "citations"
    """Citation titles, identifiers and notes."""
    SECTION = "section"


WEIGHTS: Final[dict[SearchField, float]] = {
    SearchField.TITLE: 5.0,
    SearchField.GENE: 5.0,
    SearchField.VARIANT: 5.0,
    SearchField.CARD_ID: 4.0,
    SearchField.TRAIT: 4.0,
    SearchField.CONDITION: 4.0,
    SearchField.HLA: 4.0,
    SearchField.SUMMARY: 3.0,
    SearchField.IMPOSSIBILITY_REASON: 3.0,
    SearchField.DETAIL: 2.0,
    SearchField.EVIDENCE: 2.0,
    SearchField.CAVEATS: 1.5,
    SearchField.CITATIONS: 1.0,
    SearchField.SECTION: 1.0,
}
"""What a card is called outweighs what its prose mentions in passing."""

EXACT: Final[float] = 1.0
STEM: Final[float] = 0.75
PREFIX: Final[float] = 0.5
PHRASE_BONUS: Final[float] = 0.5
PREFIX_MIN_LENGTH: Final[int] = 3

STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a", "about", "am", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
        "for", "from", "has", "have", "how", "i", "if", "in", "is", "it", "me", "my", "of",
        "on", "or", "that", "the", "this", "to", "was", "what", "which", "with",
    }
)  # fmt: skip
"""Dropped from a query unless the query holds nothing else, and reported as ``ignored``.

Without this, "risk of heart disease" would list every card whose prose contains "of".
``a`` and ``i`` are here although HLA-A and vitamin A exist: such a query still matches on
its other words, and ``ignored`` says what was dropped.
"""

_WORD: Final = re.compile(r"[^\W_]+")
_PLACEHOLDER: Final = re.compile(r"\{[^{}]*\}")
_VOWELS: Final = frozenset("aeiou")


class QueryError(ValueError):
    """A query that cannot be searched. The CLI reports each subclass under its own kind."""


class EmptyQueryError(QueryError):
    """The query has no letter or digit in it."""


class GenotypeQueryError(QueryError):
    """The query reads as a genotype. Its message never repeats the query."""


def tokenize(text: str) -> list[str]:
    """``text`` as lowercase words: runs of letters and digits, in order."""
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


@lru_cache(maxsize=65536)
def stem(word: str) -> str:
    """A light English stem, so ``curly`` finds ``curl`` and ``curlier``.

    Deliberately small: plurals, ``-ing``/``-ed``/``-ly``/``-ness``, comparatives in
    ``-ier``/``-iest``, a final ``e`` or ``y`` after a consonant, and British ``-our``
    (``colour`` and ``color`` share a stem). Words under four letters, and anything holding a
    digit or a non-ASCII letter, are left alone: ``rs7349332``, ``WNT10A`` and ``ALDH2``
    match exactly or not at all. A stem is not a word and is never shown; it only has to be
    the same on both sides. A wrong stem costs a match at quality 0.75, never a wrong claim.
    """
    if len(word) < 4 or not word.isascii() or not word.isalpha():
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith(("sses", "shes", "ches", "xes", "zes")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix, replacement, shortest in (
        ("iness", "y", 3),
        ("iest", "y", 3),
        ("ier", "y", 3),
        ("ness", "", 3),
        ("ing", "", 4),
        ("ed", "", 4),
        ("ly", "", 4),
    ):
        kept = len(word) - len(suffix)
        if word.endswith(suffix) and kept >= shortest:
            word = word[:kept] + replacement
            if suffix in {"ing", "ed"} and word[-1] == word[-2] and word[-1] not in "lsz":
                word = word[:-1]
            break
    if len(word) >= 5 and word.endswith("our"):
        word = word[:-3] + "or"
    if len(word) >= 4 and word[-1] in "ey" and word[-2] not in _VOWELS:
        word = word[:-1]
    return word


@dataclass(frozen=True)
class Query:
    """A parsed query: what was asked, what is searched for, and what was dropped."""

    text: str
    terms: tuple[str, ...]
    ignored: tuple[str, ...]


def parse_query(text: str) -> Query:
    """Split ``text`` into search terms.

    Raises :class:`GenotypeQueryError` for text the privacy scanner reads as a genotype, and
    :class:`EmptyQueryError` for text with no letter or digit in it.
    """
    text = " ".join(text.split())
    if looks_like_genotype(text):
        raise GenotypeQueryError(
            "The query reads as a genotype, so it was not searched or repeated. Search for "
            "the variant, gene or trait on its own (an rsID, a gene symbol, a phrase), never "
            "for a call at it (AGENTS.md 1.3)."
        )
    words = list(dict.fromkeys(tokenize(text)))
    if not words:
        raise EmptyQueryError(
            "The query has no letter or digit to search for. Give a trait, gene, rsID or "
            "phrase, such as `curly hair`."
        )
    terms = tuple(word for word in words if word not in STOPWORDS)
    if not terms:
        return Query(text=text, terms=tuple(words), ignored=())
    return Query(
        text=text,
        terms=terms,
        ignored=tuple(word for word in words if word in STOPWORDS),
    )


@dataclass(frozen=True)
class Document:
    """One card's searchable text. A field may appear several times, once per passage."""

    card_id: str
    fields: tuple[tuple[SearchField, str], ...]


@dataclass(frozen=True)
class FieldMatch:
    """Which of the query's terms a field matched, in the query's order."""

    field: SearchField
    terms: tuple[str, ...]


@dataclass(frozen=True)
class Hit:
    card_id: str
    score: float
    terms_matched: int
    matched: tuple[FieldMatch, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "score": round(self.score, 3),
            "terms_matched": self.terms_matched,
            "matched": [
                {"field": match.field.value, "terms": list(match.terms)} for match in self.matched
            ],
        }


def _quality(term: str, term_stem: str, words: frozenset[str], stems: frozenset[str]) -> float:
    if term in words:
        return EXACT
    if term_stem in stems:
        return STEM
    if (
        len(term) >= PREFIX_MIN_LENGTH
        and not term.isdigit()
        and any(word.startswith(term) for word in words)
    ):
        return PREFIX
    return 0.0


def _has_run(stems: Sequence[str], wanted: Sequence[str]) -> bool:
    """Whether ``wanted`` appears in ``stems`` side by side and in order."""
    width = len(wanted)
    first = wanted[0]
    return any(
        stems[i] == first and tuple(stems[i : i + width]) == tuple(wanted)
        for i in range(len(stems) - width + 1)
    )


def _score(document: Document, query: Query) -> Hit | None:
    term_stems = tuple(stem(term) for term in query.terms)
    best: dict[str, float] = {}
    found: dict[SearchField, set[str]] = {}
    phrase = 0.0
    for field, text in document.fields:
        passage = tokenize(text)
        if not passage:
            continue
        passage_stems = [stem(word) for word in passage]
        words, stems = frozenset(passage), frozenset(passage_stems)
        weight = WEIGHTS[field]
        for term, term_stem in zip(query.terms, term_stems, strict=True):
            quality = _quality(term, term_stem, words, stems)
            if quality:
                best[term] = max(best.get(term, 0.0), weight * quality)
                found.setdefault(field, set()).add(term)
        if len(term_stems) > 1 and _has_run(passage_stems, term_stems):
            phrase = max(phrase, PHRASE_BONUS * weight)
    if not best:
        return None
    return Hit(
        card_id=document.card_id,
        score=sum(best.values()) + phrase,
        terms_matched=len(best),
        matched=tuple(
            FieldMatch(field, tuple(term for term in query.terms if term in found[field]))
            for field in SearchField
            if field in found
        ),
    )


def search(documents: Iterable[Document], query: Query) -> list[Hit]:
    """Every document that matches at least one term of ``query``, best first.

    Ordered by terms matched, then score, then the order ``documents`` came in, which is
    the order the pack or the run lists its cards everywhere else. Nothing is cut off here;
    a caller that shows fewer says how many there were.
    """
    hits = [
        (position, hit)
        for position, document in enumerate(documents)
        if (hit := _score(document, query)) is not None
    ]
    hits.sort(key=lambda item: (-item[1].terms_matched, -item[1].score, item[0]))
    return [hit for _, hit in hits]


def section_text(name: str) -> str:
    """A section's name and, where this engine knows it, its title."""
    try:
        return f"{name} {sections.SECTIONS[sections.Section(name)].title}"
    except ValueError:
        return name


def template_text(text: str) -> str:
    """An authored template without its ``{placeholders}``, which are not prose."""
    return _PLACEHOLDER.sub(" ", text)


def _effect_text(evidence: Any) -> Iterator[str]:
    if evidence is None:
        return
    for text in (evidence.effect.units, evidence.effect.context):
        if text:
            yield text


def pack_document(card: Card) -> Document:
    """An authored card's searchable text. No run, so no genotype."""
    fields: list[tuple[SearchField, str]] = [
        (SearchField.CARD_ID, card.id),
        (SearchField.TITLE, card.title),
        (SearchField.SECTION, section_text(card.section.value)),
    ]

    def add(field: SearchField, *texts: str | None) -> None:
        fields.extend((field, text) for text in texts if text)

    add(SearchField.GENE, card.gene)
    if card.match is not None:
        add(SearchField.VARIANT, *(variant.rsid for variant in card.match.variants))
    if card.pgs is not None:
        add(SearchField.TRAIT, card.trait, card.pgs.pgs_id)
    if card.carrier is not None:
        add(SearchField.CONDITION, card.carrier.condition, card.carrier.variant)
        add(SearchField.CAVEATS, card.carrier.typed_scope)
    if card.hla is not None:
        for alternative in card.hla.alternatives:
            add(SearchField.HLA, alternative.name)
            for term in alternative.terms:
                add(SearchField.HLA, *(f"HLA-{term.locus}*{allele}" for allele in term.alleles))
    add(SearchField.SUMMARY, card.summary)
    add(SearchField.DETAIL, card.detail)
    for outcome in card.outcomes.values():
        add(SearchField.SUMMARY, template_text(outcome.summary))
        add(SearchField.DETAIL, template_text(outcome.detail))
        if outcome.risk_context:
            add(SearchField.DETAIL, template_text(outcome.risk_context))
        if outcome.overrides_evidence:
            add(SearchField.EVIDENCE, *_effect_text(outcome.evidence))
    add(SearchField.IMPOSSIBILITY_REASON, card.impossibility_reason)
    add(SearchField.EVIDENCE, *_effect_text(card.evidence))
    if card.decile_outcomes is not None:
        deciles = card.decile_outcomes
        add(SearchField.EVIDENCE, deciles.measure, deciles.population, deciles.context)
    add(SearchField.CAVEATS, *card.caveats)
    for citation in card.citations:
        add(SearchField.CITATIONS, citation.title, citation.id, citation.database, citation.note)
    return Document(card.id, tuple(fields))


def query_payload(query: Query, *, searched: int, total: int, limit: int | None) -> dict[str, Any]:
    """What was asked and how much was found, as both search payloads state it.

    ``total`` counts every match, so a ``limit`` never hides how many there were.
    """
    return {
        "query": query.text,
        "terms": list(query.terms),
        "ignored": list(query.ignored),
        "searched": searched,
        "total": total,
        "limit": limit,
    }


def pack_view(cards: Sequence[Card], query: Query, limit: int | None = None) -> dict[str, Any]:
    """``genetics cards search`` as data: the pack's cards that match, best first."""
    by_id = {card.id: card for card in cards}
    hits = search((pack_document(card) for card in cards), query)
    shown = hits if limit is None else hits[:limit]
    return query_payload(query, searched=len(cards), total=len(hits), limit=limit) | {
        "hits": [
            {
                "card_id": hit.card_id,
                "section": by_id[hit.card_id].section.value,
                "kind": by_id[hit.card_id].kind.value,
                "title": by_id[hit.card_id].title,
                "gene": by_id[hit.card_id].gene,
            }
            | hit.to_dict()
            for hit in shown
        ]
    }
