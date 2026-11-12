"""Read-side views of one saved run: a card, a section, the QC record, a search (roadmap
M13.1, M13.3). The card view also says what decided the card's tier (M13.4), built by
:mod:`genetics.run.explain`.

The agent's read commands (``genetics runs card``, ``runs show --section``, ``runs qc``,
``runs search``) build their JSON here rather than in the CLI module, so that the projection
of a saved card exists once and ``runs show --json`` uses the same one. M13.5's parity test
can call these functions directly, and M14.4's dashboard search calls :func:`search_view`.

**Frozen record and current context are kept apart.** Every payload carries the saved
record under its own keys, and anything this engine adds at read time -- section titles,
the pointers M12.1 declared, citation links, the PGx section notice, the reading of a
card's confidence -- sits under
``current_context`` with ``"context": "current"``. That is the split the M10.5 PGx framing
made (``pgx calls``) and the M11.6 and M12.1 reviews kept: a saved run is what the person
read, and an engine that has since changed must not appear to have said something then.

**The run id is the directory name**, which is what every command resolves. The manifest
records its own ``run_id`` too; the two differ only when a bundle directory was renamed.
Since M13.2 ``runs show --json`` prints the directory name as well, and keeps the manifest's
value as ``recorded_run_id``.

The CLI tags each of these payloads with its name and schema version before printing; see
:mod:`genetics.cli.contract`.

Nothing here is scanned for genotypes. A card read states the reader's own call at its
marker, as ``runs show`` does; see :mod:`genetics.cli.runs_cmd`. A search result carries each
matched card's face, which states that call too. The QC view holds no genotype, and its
command scans it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from genetics.engine import sections
from genetics.engine.citations import citation_url
from genetics.engine.search import (
    Document,
    Query,
    SearchField,
    query_payload,
    search,
    section_text,
)
from genetics.engine.sections import Section
from genetics.run.bundle import RunBundle, StoredCard
from genetics.run.explain import explain_confidence

INTERPRETED_STATUSES = frozenset({"matched", "computed"})
"""What counts as a finding in a section's tally: matched and computed, as the dashboard's
nav and the run manifest count them."""

SAVED_RECORDS: dict[Section, tuple[tuple[str, str], ...]] = {
    Section.PHYSICAL_HEALTH: (
        ("ClinVar reference lookup", "genetics runs clinvar {run}"),
        ("ACMG secondary-finding gene overlaps", "genetics runs secondary {run}"),
    ),
    Section.PHARMACOGENOMICS: (("Saved pharmacogenomic calls", "genetics pgx calls {run}"),),
    Section.IMMUNOGENETICS: (("HLA classifier calls", "genetics hla calls {run}"),),
}
"""Saved records a section's reader is pointed to beyond its cards, with the command that
prints each. The dashboard links the same records as pages."""


def _plain(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if value is None else dict(value)


def card_payload(card: StoredCard) -> dict[str, Any]:
    """One saved card, as data. The projection ``runs show --json`` and ``runs card`` share.

    Mappings are copied into plain dicts rather than re-serialised through a schema: what
    was written is what a reader of a months-old bundle must get back.
    """
    return {
        "card_id": card.card_id,
        "section": card.section,
        "kind": card.kind,
        "title": card.title,
        "gene": card.gene,
        "status": card.status,
        "confidence_tier": card.confidence_tier,
        "summary": card.summary,
        "detail": card.detail,
        "impossibility_reason": card.impossibility_reason,
        "variant": _plain(card.variant),
        "match": dict(card.match),
        "confidence": _plain(card.confidence),
        "evidence": _plain(card.evidence),
        "observation": _plain(card.observation),
        "frequencies": [dict(f) for f in card.frequencies],
        "confidence_frequency": _plain(card.confidence_frequency),
        "citations": [dict(c) for c in card.citations],
        "authored_caveats": list(card.authored_caveats),
        "computed_caveats": list(card.computed_caveats),
        "computation": _plain(card.computation),
        "multi_marker": _plain(card.multi_marker),
        "risk_context": card.risk_context,
        "imputation_mode": card.imputation_mode,
        "ancestry_comparison": _plain(card.ancestry_comparison),
        "carrier": _plain(card.carrier),
    }


def _header(bundle: RunBundle) -> dict[str, Any]:
    return {
        "run_id": bundle.path.name,
        "path": str(bundle.path),
        "format_version": bundle.format_version,
        "created_at": bundle.created_at,
    }


def parse_section(name: str) -> Section:
    """A section named on the command line. Raises :class:`sections.UnknownSectionError`."""
    return sections.get(name).section


def related(section: Section, cards: Sequence[StoredCard]) -> list[dict[str, Any]]:
    """The pointers ``section`` declares (M12.1), resolved against this run's cards.

    A pointer names a card held by another section. A run saved before that card existed
    gets ``in_run: false`` and the declared label, rather than an id it cannot open.
    """
    by_id = {card.card_id: card for card in cards}
    pointers: list[dict[str, Any]] = []
    for pointer in sections.SECTIONS[section].related:
        card = by_id.get(pointer.card_id)
        pointers.append(
            {
                "card_id": pointer.card_id,
                "in_run": card is not None,
                "title": pointer.label if card is None else card.title,
                "section": None if card is None else card.section,
            }
        )
    return pointers


def pointed_from(card_id: str) -> list[str]:
    """Sections whose pointers name ``card_id``, in AGENTS.md 3.1 order."""
    return [
        section.value
        for section in sections.SECTION_ORDER
        if any(pointer.card_id == card_id for pointer in sections.SECTIONS[section].related)
    ]


def _section_info(name: str) -> dict[str, Any]:
    try:
        info = sections.SECTIONS[Section(name)]
    except ValueError:
        # Not reachable through the version gate today; titled from its own name, as the
        # dashboard does, rather than raising on a card that was read successfully.
        return {"section": name, "title": name.replace("_", " ").capitalize(), "blurb": None}
    return {"section": info.section.value, "title": info.title, "blurb": info.blurb}


def citation_links(citations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Each saved citation's public page, or ``None`` where this engine will not link it.

    Re-validated by :func:`citation_url`, as the dashboard's links are: the saved citation
    is data another version wrote.
    """
    return [
        {
            "type": citation.get("type"),
            "id": citation.get("id"),
            "url": citation_url(
                str(citation.get("type", "")),
                str(citation.get("id", "")),
                None if citation.get("database") is None else str(citation.get("database")),
            ),
        }
        for citation in citations
    ]


def find_card(bundle: RunBundle, card_id: str) -> StoredCard | None:
    """The saved card with this id, matched by equality; never a path."""
    return next((card for card in bundle.cards if card.card_id == card_id), None)


def card_view(bundle: RunBundle, card: StoredCard) -> dict[str, Any]:
    """One card in full, with the current context a reader of it needs.

    ``related`` is what the card's own section points to; ``pointed_from`` names the
    sections that point to this card. M12.2's four MTHFR cards rely on both: a reader of one
    claim card is meant to find the nutrition card, and the reverse.

    ``confidence`` says what decided the card's tier, in one shape whatever the card's kind
    (M13.4). It is this engine's reading of the saved inputs, which is why it is here and
    not in the saved card; see :mod:`genetics.run.explain`.
    """
    context: dict[str, Any] = {
        "context": "current",
        "section": _section_info(card.section),
        "citation_links": citation_links(card.citations),
        "confidence": explain_confidence(card),
        "related": [],
        "pointed_from": pointed_from(card.card_id),
    }
    if card.section in {section.value for section in Section}:
        context["related"] = related(Section(card.section), bundle.cards)
    return _header(bundle) | {"card": card_payload(card), "current_context": context}


def empty_reason(milestone: str, total: int, interpreted: int) -> str | None:
    """Why a section shows nothing, in the dashboard's words; ``None`` when it shows a finding."""
    if total == 0:
        return f"Not built yet — roadmap {milestone}."
    if interpreted == 0:
        return (
            f"{total} card(s) here, none of which produced an interpretation for this "
            "genome. Each one states its own reason."
        )
    return None


def section_context(section: Section, bundle: RunBundle) -> dict[str, Any]:
    """What the dashboard shows around a section's cards, for one run."""
    from genetics.engine.carrier_scope import section_notice
    from genetics.pgx.presentation import section_framing

    info = sections.SECTIONS[section]
    here = [card for card in bundle.cards if card.section == section.value]
    interpreted = sum(1 for card in here if card.status in INTERPRETED_STATUSES)
    name = bundle.path.name
    context: dict[str, Any] = {
        "section": section.value,
        "title": info.title,
        "blurb": info.blurb,
        "milestone": info.milestone,
        "card_count": len(here),
        "interpreted": interpreted,
        "empty_reason": empty_reason(info.milestone, len(here), interpreted),
        "related": related(section, bundle.cards),
        "saved_records": [
            {"title": title, "command": command.format(run=name)}
            for title, command in SAVED_RECORDS.get(section, ())
        ],
    }
    if section is Section.PHARMACOGENOMICS:
        context["section_framing"] = section_framing()
    if section is Section.REPRODUCTIVE:
        context["carrier_scope"] = section_notice(bundle.cards)
    return context


def in_report_order(chosen: Iterable[Section]) -> list[Section]:
    """``chosen``, deduplicated, in AGENTS.md 3.1 order whatever order it was asked in."""
    wanted = set(chosen)
    return [section for section in sections.SECTION_ORDER if section in wanted]


def section_view(bundle: RunBundle, chosen: Sequence[Section]) -> dict[str, Any]:
    """The cards in ``chosen`` sections, in saved order, and each section's context.

    Each section is reported even when it holds nothing, with the reason.
    """
    ordered = in_report_order(chosen)
    names = {section.value for section in ordered}
    return _header(bundle) | {
        "sections": [section.value for section in ordered],
        "cards": [card_payload(card) for card in bundle.cards if card.section in names],
        "current_context": {
            "context": "current",
            "sections": [section_context(section, bundle) for section in ordered],
        },
    }


def qc_view(bundle: RunBundle) -> dict[str, Any]:
    """The saved QC report, imputation execution record and provenance. No genotype.

    Full imputation provenance (per-region parameters) has its own command, ``runs
    imputation``; only its status is repeated here.
    """
    provenance = bundle.imputation_provenance
    return _header(bundle) | {
        "qc": dict(bundle.qc),
        "imputation": _plain(bundle.imputation),
        "imputation_provenance_status": None if provenance is None else provenance.get("status"),
        "provenance": dict(bundle.provenance),
    }


# ---------------------------------------------------------------------------
# Search (M13.3)
# ---------------------------------------------------------------------------


def _texts(*values: Any) -> list[str]:
    """The non-empty strings among ``values``; anything another version wrote is skipped."""
    return [value for value in values if isinstance(value, str) and value]


def search_document(card: StoredCard) -> Document:
    """A saved card's searchable text, read defensively like everything from a bundle.

    What the run recorded and nothing else: the one face and detail it saved, not the
    other outcomes the pack could have chosen. The section title is the one thing taken
    from this engine, so that ``sleep`` finds a card saved under ``sleep_circadian``.
    """
    fields: list[tuple[SearchField, str]] = [
        (SearchField.CARD_ID, card.card_id),
        (SearchField.TITLE, card.title),
        (SearchField.SECTION, section_text(card.section)),
    ]

    def add(field: SearchField, *values: Any) -> None:
        fields.extend((field, text) for text in _texts(*values))

    def get(record: Any, *path: str) -> Any:
        for key in path:
            if not isinstance(record, Mapping):
                return None
            record = record.get(key)
        return record

    add(SearchField.GENE, card.gene)
    add(SearchField.VARIANT, get(card.variant, "rsid"))
    markers = get(card.multi_marker, "markers")
    if isinstance(markers, Sequence) and not isinstance(markers, str):
        add(SearchField.VARIANT, *(get(marker, "variant", "rsid") for marker in markers))
    authored = get(card.computation, "result", "authored")
    add(SearchField.TRAIT, get(authored, "trait"), get(authored, "pgs_id"))
    add(SearchField.CONDITION, get(card.carrier, "condition"), get(card.carrier, "variant"))
    add(SearchField.SUMMARY, card.summary)
    add(SearchField.DETAIL, card.detail, card.risk_context)
    add(SearchField.IMPOSSIBILITY_REASON, card.impossibility_reason)
    add(
        SearchField.EVIDENCE,
        get(card.evidence, "effect", "units"),
        get(card.evidence, "effect", "context"),
    )
    add(
        SearchField.CAVEATS,
        *card.authored_caveats,
        *card.computed_caveats,
        get(card.carrier, "typed_scope"),
    )
    for citation in card.citations:
        add(
            SearchField.CITATIONS,
            citation.get("title"),
            citation.get("id"),
            citation.get("database"),
            citation.get("note"),
        )
    return Document(card.card_id, tuple(fields))


def card_face(card: StoredCard) -> dict[str, Any]:
    """What a saved card shows before it is opened: eight of :func:`card_payload`'s keys."""
    return {
        "card_id": card.card_id,
        "section": card.section,
        "kind": card.kind,
        "title": card.title,
        "gene": card.gene,
        "status": card.status,
        "confidence_tier": card.confidence_tier,
        "summary": card.summary,
    }


def search_view(bundle: RunBundle, query: Query, limit: int | None = None) -> dict[str, Any]:
    """The saved cards that match ``query``, best first (``genetics runs search``).

    ``results`` is the saved record: each matched card's face, unchanged. The ranking is
    this engine's, made now, so the query, the counts and each hit's score and matched
    fields are under ``current_context``; ``hits[i]`` is about ``results[i]``. No card is
    ranked or left out for its status or tier (AGENTS.md 0.1A).
    """
    by_id = {card.card_id: card for card in bundle.cards}
    hits = search((search_document(card) for card in bundle.cards), query)
    shown = hits if limit is None else hits[:limit]
    return _header(bundle) | {
        "results": [card_face(by_id[hit.card_id]) for hit in shown],
        "current_context": {"context": "current"}
        | query_payload(query, searched=len(bundle.cards), total=len(hits), limit=limit)
        | {"hits": [hit.to_dict() for hit in shown]},
    }
