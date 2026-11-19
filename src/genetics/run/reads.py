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
from functools import lru_cache
from typing import Any, Final

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
from genetics.outbound import reads_as_call
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
    Section.ANCESTRY: (
        (
            "Placement, ancient affinity and haplogroups",
            "genetics runs ancestry {run}",
        ),
    ),
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


STATUS_LABELS: Mapping[str, str] = {
    "phase_ambiguous": "Phase unresolved",
    "matched": "Interpreted",
    "computed": "Computed measurement",
    "not_run": "Computation not run",
    "insufficient_coverage": "Insufficient assay coverage",
    "insufficient_calls": "Insufficient local calls",
    "not_determinable": "Not determinable by this assay",
    "marker_absent": "Marker not on this array",
    "no_call": "No call",
    "allele_mismatch": "Allele mismatch",
    "indel_excluded": "Indel excluded",
    "het_haploid": "Heterozygous at a haploid locus",
    "duplicate_conflict": "Probes disagree",
    "strand_ambiguous": "Strand ambiguous",
}
"""Short display text per match status, shared by the dashboard's badges and the empty
states. String-keyed, since a saved run is read as strings. These are labels; the card's
own summary says why."""


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " ").capitalize())


_MAX_QUOTED: Final = 3


@lru_cache(maxsize=1)
def pack_section_counts() -> Mapping[str, int] | None:
    """How many cards the committed knowledge pack holds per section, or ``None`` when it
    cannot be read. Cached for the process: the pack is source, not data."""
    from genetics.engine.cards import CardError, KnowledgePack

    try:
        pack = KnowledgePack.load(None)
    except (CardError, OSError):
        return None
    counts = {section.value: 0 for section in sections.SECTION_ORDER}
    for card in pack.cards:
        counts[card.section.value] = counts.get(card.section.value, 0) + 1
    return counts


def empty_reason(cards: Sequence[StoredCard], pack_count: int | None) -> str | None:
    """Why a section shows no finding for this run, or ``None`` when it shows one (M14.1).

    Three cases, worded apart, because each is a different fact:

    * **No card at all.** Since M12 the committed pack has cards in every section, so a
      run with none was saved with a pack that held none here. Said with the current
      pack's count, which is what a new run would show. Nothing about the genome.
    * **Cards, and no interpretation.** Each status is counted, by its label. A ``not_run``
      card's reason is quoted, since the engine wrote it about a module (a reference not
      fetched, a licence not accepted, a tool absent); any other card's reason is about the
      call and stays on the card. A section of assay limits says so.
    * **An interpretation.** ``None``.
    """
    if not cards:
        if pack_count is None:
            return (
                "This run holds no card for this section, and the current knowledge pack "
                "could not be read to say whether it has any."
            )
        if pack_count == 0:
            return (
                "No card has been written for this section yet. That is a fact about this "
                "tool, not about this genome."
            )
        return (
            "This run holds no card for this section: the knowledge pack it was saved with "
            f"had none here. The current pack has {pack_count}, so a new run of the same "
            "export would show them. Nothing about this genome is implied."
        )
    if any(card.status in INTERPRETED_STATUSES for card in cards):
        return None
    counts: dict[str, int] = {}
    for card in cards:
        counts[card.status] = counts.get(card.status, 0) + 1
    tally = ", ".join(
        f"{status_label(status).lower()}: {count}"
        for status, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )
    sentences = [
        f"None of the {len(cards)} card(s) here produced an interpretation for this genome "
        f"({tally})."
    ]
    if set(counts) == {"not_determinable"}:
        sentences.append(
            "Every card here is an assay limit: it says what this array cannot determine, "
            "and holds no result for anyone."
        )
    quoted = list(
        dict.fromkeys(
            str(card.match.get("reason")).strip()
            for card in cards
            if card.status == "not_run" and card.match.get("reason")
        )
    )
    # The engine writes these about a module, never a call. Checked anyway: an empty state
    # sits beside the scanned half of the page.
    quoted = [reason for reason in quoted if not reads_as_call(reason)]
    if quoted:
        shown = " ".join(_sentence(reason) for reason in quoted[:_MAX_QUOTED])
        more = len(quoted) - _MAX_QUOTED
        sentences.append(
            f"Not run: {shown}" + (f" ({more} more reason(s) on the cards.)" if more > 0 else "")
        )
    sentences.append("Each card states its own reason.")
    return " ".join(sentences)


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."


def _pack_count(section: str) -> int | None:
    counts = pack_section_counts()
    return None if counts is None else counts.get(section, 0)


def empty_reasons(cards: Sequence[StoredCard]) -> dict[str, str | None]:
    """:func:`empty_reason` for each of the thirteen sections, from one run's cards."""
    by_section: dict[str, list[StoredCard]] = {s.value: [] for s in sections.SECTION_ORDER}
    for card in cards:
        if card.section in by_section:
            by_section[card.section].append(card)
    return {name: empty_reason(here, _pack_count(name)) for name, here in by_section.items()}


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
        "empty_reason": empty_reason(here, _pack_count(section.value)),
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
# Saved records beside the cards (M13.5)
# ---------------------------------------------------------------------------


def clinvar_view(bundle: RunBundle) -> dict[str, Any]:
    """The saved ClinVar reference lookup, whole (``genetics runs clinvar``)."""
    return _header(bundle) | {"clinvar": _plain(bundle.clinvar)}


def secondary_findings_view(bundle: RunBundle) -> dict[str, Any]:
    """The lookup's ACMG gene-list overlaps (``genetics runs secondary``).

    Filtered by :func:`genetics.health.secondary.secondary_view`, which the dashboard's page
    calls too. ``None`` for a run that recorded no lookup.
    """
    from genetics.health.secondary import secondary_view

    return _header(bundle) | {
        "secondary": None if bundle.clinvar is None else secondary_view(bundle.clinvar)
    }


def imputation_view(bundle: RunBundle) -> dict[str, Any]:
    """The imputation execution record and full provenance (``genetics runs imputation``)."""
    return _header(bundle) | {
        "execution": _plain(bundle.imputation),
        "provenance": _plain(bundle.imputation_provenance),
    }


def pgx_view(bundle: RunBundle, gene: str | None = None) -> dict[str, Any]:
    """Saved pharmacogenomic calls and what the section shows beside them (``pgx calls``).

    Raises :class:`genetics.pgx.calling.CallingError` for a gene outside the eight.
    """
    from genetics.pgx.presentation import saved_report

    return _header(bundle) | saved_report(bundle, gene)


def hla_view(bundle: RunBundle) -> dict[str, Any]:
    """Saved HLA classifier evidence and the run's HLA-linked cards (``hla calls``).

    The record's own keys sit beside the envelope, as ``hla calls --json`` has always
    printed them. ``linked_cards`` are the saved cards the HLA page lists. A run saved
    before those cards existed says ``not-recorded``, which is different from a run that
    recorded none; the dashboard's page draws the same line. Raises
    :class:`genetics.hla.models.HLAError` for a record that does not validate.
    """
    from genetics.hla.calling import report
    from genetics.hla.cards import cards_report
    from genetics.run.bundle import HLA_CARD_FORMAT_VERSION

    recorded = bundle.format_version >= HLA_CARD_FORMAT_VERSION
    return (
        _header(bundle)
        | report(bundle.hla)
        | {
            "linked_cards_status": "recorded" if recorded else "not-recorded",
            "linked_cards": cards_report(bundle.cards) if recorded else [],
        }
    )


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


# ---------------------------------------------------------------------------
# Ancestry (M14.2)
# ---------------------------------------------------------------------------

PCA_PADDING: Final = 0.05
"""Fraction of each axis's span added on both sides of the drawn points."""


def ancestry_report(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """A run's ancestry record and what the ancestry page draws from it (M14.2).

    ``ancestry`` is the saved record, whole: the placement among present-day reference
    populations, the mt and Y haplogroup walks with their marker counts, and the affinity
    to ancient groups. ``current_context.pca`` is the scatter: the sample and every
    reference population on the first two components, in pooled within-population standard
    deviations, as M5.5 measures distance. A run saved before M14.2 recorded no reference
    positions, so it is not drawn and says so; its fits are still listed.
    """
    return {
        "ancestry": None if record is None else dict(record),
        "current_context": {"context": "current", "pca": _pca(record)},
    }


def ancestry_view(bundle: RunBundle) -> dict[str, Any]:
    """``genetics runs ancestry``: the envelope and :func:`ancestry_report`."""
    return _header(bundle) | ancestry_report(bundle.ancestry)


def _pca(record: Mapping[str, Any] | None) -> dict[str, Any]:
    population: Mapping[str, Any] = {}
    if record is not None and isinstance(record.get("population"), Mapping):
        population = record["population"]
    status = population.get("status") if population else "not_recorded"
    view: dict[str, Any] = {
        "status": status,
        "drawn": False,
        "why_not": None,
        "axes": ["PC1", "PC2"],
        "units": "pooled within-population standard deviations",
        "sample": None,
        "references": [],
        "regions": [],
        "bounds": None,
    }
    if record is None:
        view["why_not"] = (
            "This run recorded no ancestry analysis: it was saved by a version before the "
            "ancestry record existed (bundle format 3)."
        )
        return view
    fits = population.get("fits")
    if status == "not_run" or not isinstance(fits, list) or not fits:
        view["why_not"] = (
            f"No placement was made: {population.get('reason') or 'no reason recorded'}"
        )
        return view
    regions = sorted({str(fit.get("region")) for fit in fits})
    view["regions"] = regions
    named = population.get("population")
    references = []
    for rank, fit in enumerate(fits, start=1):
        centroid = fit.get("centroid")
        point = (
            [float(centroid[0]), float(centroid[1])]
            if isinstance(centroid, list) and len(centroid) >= 2
            else None
        )
        references.append(
            {
                "rank": rank,
                "population": fit.get("population"),
                "region": fit.get("region"),
                "n_samples": fit.get("n_samples"),
                "distance": fit.get("distance"),
                "fit": fit.get("fit"),
                "percentile": fit.get("percentile"),
                "named": fit.get("population") == named,
                "point": point,
            }
        )
    view["references"] = references
    scale = population.get("scale")
    coordinates = population.get("coordinates")
    if (
        not isinstance(scale, list)
        or not isinstance(coordinates, list)
        or len(scale) < 2
        or len(coordinates) < 2
        or any(reference["point"] is None for reference in references)
    ):
        view["why_not"] = (
            "This run was saved before reference-population positions were recorded "
            "(M14.2), so the scatter cannot be drawn against the reference it was placed "
            "in. The distances below are the run's own; a new run draws them."
        )
        return view
    sample = [float(coordinates[0]) / float(scale[0]), float(coordinates[1]) / float(scale[1])]
    xs = [sample[0], *(reference["point"][0] for reference in references)]
    ys = [sample[1], *(reference["point"][1] for reference in references)]
    pad_x = (max(xs) - min(xs)) * PCA_PADDING or 1.0
    pad_y = (max(ys) - min(ys)) * PCA_PADDING or 1.0
    view["drawn"] = True
    view["sample"] = sample
    view["bounds"] = {
        "x": [min(xs) - pad_x, max(xs) + pad_x],
        "y": [min(ys) - pad_y, max(ys) + pad_y],
    }
    return view
