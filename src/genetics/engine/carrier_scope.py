"""What carrier screening from this array leaves out (roadmap M11.6).

The section-level statement the carrier panel exists for: carrier screening from an array is
incomplete as a category, not only for the two conditions with impossibility cards. Each
carrier card says what it does not type; only a section-level record can say what the whole
set does not.

Three inputs, kept apart because they answer different questions:

* the card's **declaration**: a cited gene list, the sourced gene-level assay limits and the
  M11.5 audit's excluded alleles, parsed by :func:`parse_declaration`;
* the **panel**: what the knowledge pack types, the same for every run;
* the **run tally**: how many of those markers gave a result for this person. A marker with
  no saved state was not determined, and is never counted as a no-copy result.

A gene with no card is a gap in this report, and is kept apart from an assay limit: the
first says nobody wrote the card, the second says the data could not support one.

Every saved record is rebuilt from the bundle's own carrier records and its frozen
declaration (:func:`validate_saved`). The current knowledge pack is never consulted, so a
saved run keeps the statement it was written with.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from genetics.engine.cards import Card, CardError, CardKind
from genetics.engine.confidence import CallSource
from genetics.engine.matcher import MatchResult, MatchStatus, is_strand_ambiguous

if TYPE_CHECKING:
    from genetics.engine.cards import KnowledgePack
    from genetics.engine.evidence import AssembledCard
    from genetics.run.bundle import StoredCard

SOURCE: Final[str] = "carrier_screening_scope"
RESULT_SCHEMA_VERSION: Final[int] = 1

AUTOSOMAL_RECESSIVE_TABLES: Final[frozenset[int]] = frozenset({1, 2, 3, 4, 5})
X_LINKED_TABLES: Final[frozenset[int]] = frozenset({6})

MECHANISMS: Final[dict[str, str]] = {
    "copy_number": "Copy number",
    "repeat_expansion": "Repeat expansion",
    "inversion": "Inversion",
}

ALLELE_CLASSES: Final[dict[str, str]] = {
    "indel": "Assay limit: an indel on this array, with no sequence recorded",
    "not_on_array": "Chip limit: the allele is not on this array",
    "failed_criterion": "Typed, but failing a criterion for a card",
    "not_authored": "Gap in this report: passes the measured criteria, and no card was written",
}
"""Three classes of reason, and the wording keeps them apart. The last is about this report
and not about the array, so it must never read as an assay limit."""

# The saved face below is rebuilt and compared on every read, so its wording is part of the
# record's schema. Changing it means bumping RESULT_SCHEMA_VERSION and keeping the old text
# for the runs that hold it; test_the_saved_wording_is_pinned fails until that is decided.
NOTICE: Final[str] = (
    "A result here covers named alleles only. No detection rate, residual carrier risk or "
    "offspring risk is computed. Only clinical sequencing can establish or exclude a variant."
)
NOT_RECORDED: Final[str] = (
    "This run did not record its carrier-screening scope. Each carrier card types named "
    "alleles only, and no result in this section is a negative carrier screen."
)

MEASURED_CLASSES: Final[frozenset[str]] = frozenset({"failed_criterion", "not_authored"})
"""The classes whose claim is about one typed allele, re-checked against the references."""

_ALLELE_RE: Final[re.Pattern[str]] = re.compile(r"^[ACGT]>[ACGT]$")
_RSID_RE: Final[re.Pattern[str]] = re.compile(r"^rs[1-9][0-9]*$")
_GENE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9]*$")
_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "source",
        "status",
        "declaration",
        "panel",
        "genes",
        "counts",
        "excluded_alleles",
        "run",
    }
)


class ScopeError(ValueError):
    """A saved scope record that does not follow from its own bundle."""


def _keys(data: Any, allowed: set[str], required: set[str], where: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise CardError(f"{where}: expected a mapping")
    if set(data) - allowed or required - set(data):
        raise CardError(f"{where}: expected fields {sorted(required)}, got {sorted(data)}")
    return dict(data)


def _text(data: Mapping[str, Any], key: str, where: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise CardError(f"{where}.{key}: expected nonempty text")
    return value.strip()


def _gene(data: Mapping[str, Any], key: str, where: str) -> str:
    gene = _text(data, key, where)
    if not _GENE_RE.fullmatch(gene):
        raise CardError(f"{where}.{key}: {gene!r} is not a gene symbol")
    return gene


def _rsid(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _RSID_RE.fullmatch(value):
        raise CardError(f"{where}: {value!r} is not an rsID")
    return value


def _unique(values: Iterable[str], what: str, where: str) -> None:
    repeated = sorted(name for name, n in Counter(values).items() if n > 1)
    if repeated:
        raise CardError(f"{where}: {what} listed twice: {', '.join(repeated)}")


def _choice(data: Mapping[str, Any], key: str, allowed: Iterable[str], where: str) -> str:
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        raise CardError(f"{where}.{key}: expected one of {sorted(allowed)}")
    return value


def _list(raw: Any, where: str) -> list[Any]:
    if not isinstance(raw, list) or not raw:
        raise CardError(f"{where}: expected a nonempty list")
    return raw


def _parse_reference(raw: Any, where: str) -> dict[str, Any]:
    fields = {"name", "citation", "tables", "genes"}
    data = _keys(raw, fields, fields, where)
    tables = data["tables"]
    if not isinstance(tables, Mapping) or not tables:
        raise CardError(f"{where}.tables: expected a mapping of table number to caption")
    # JSON turns the keys to text, so a saved declaration parses the same as an authored one.
    captions: dict[str, str] = {}
    for number, caption in tables.items():
        if not re.fullmatch(r"[1-9][0-9]*", str(number)):
            raise CardError(f"{where}.tables: {number!r} is not a table number")
        if not isinstance(caption, str) or not caption.strip():
            raise CardError(f"{where}.tables.{number}: expected a caption")
        captions[str(number)] = caption.strip()
    genes = []
    for i, row in enumerate(_list(data["genes"], f"{where}.genes")):
        at = f"{where}.genes[{i}]"
        entry = _keys(
            row, {"gene", "listed_as", "table", "condition"}, {"gene", "table", "condition"}, at
        )
        table = entry["table"]
        if type(table) is not int or str(table) not in captions:
            raise CardError(f"{at}.table: {table!r} has no caption in this reference")
        if table not in AUTOSOMAL_RECESSIVE_TABLES | X_LINKED_TABLES:
            raise CardError(f"{at}.table: {table!r} is not a table this reference defines")
        gene: dict[str, Any] = {
            "gene": _gene(entry, "gene", at),
            "table": table,
            "condition": _text(entry, "condition", at),
        }
        if "listed_as" in entry:
            gene["listed_as"] = _gene(entry, "listed_as", at)
        genes.append(gene)
    _unique((g["gene"] for g in genes), "gene", f"{where}.genes")
    return {
        "name": _text(data, "name", where),
        "citation": _text(data, "citation", where),
        "tables": captions,
        "genes": genes,
    }


def parse_declaration(raw: Any, where: str) -> dict[str, Any]:
    """Validate an authored or saved declaration with one contract; return its plain form."""
    fields = {"reference", "assay_limits", "excluded_alleles", "dbsnp_multiallelic"}
    data = _keys(raw, fields, fields, where)
    reference = _parse_reference(data["reference"], f"{where}.reference")
    known = {gene["gene"] for gene in reference["genes"]}
    limits = []
    for i, row in enumerate(_list(data["assay_limits"], f"{where}.assay_limits")):
        at = f"{where}.assay_limits[{i}]"
        entry = _keys(
            row, {"gene", "mechanism", "statement", "card"}, {"gene", "mechanism", "statement"}, at
        )
        gene = _gene(entry, "gene", at)
        if gene not in known:
            raise CardError(f"{at}.gene: {gene} is not in the reference list")
        limit = {
            "gene": gene,
            "mechanism": _choice(entry, "mechanism", MECHANISMS, at),
            "statement": _text(entry, "statement", at),
        }
        if "card" in entry:
            limit["card"] = _text(entry, "card", at)
        limits.append(limit)
    _unique((limit["gene"] for limit in limits), "gene", f"{where}.assay_limits")
    alleles = []
    keys = {"class", "gene", "variant", "rsid", "reason"}
    for i, row in enumerate(_list(data["excluded_alleles"], f"{where}.excluded_alleles")):
        at = f"{where}.excluded_alleles[{i}]"
        entry = _keys(row, {*keys, "allele"}, keys, at)
        kind = _choice(entry, "class", ALLELE_CLASSES, at)
        allele = {
            "class": kind,
            "gene": _gene(entry, "gene", at),
            "variant": _text(entry, "variant", at),
            "rsid": _rsid(entry["rsid"], f"{at}.rsid"),
            "reason": _text(entry, "reason", at),
        }
        if (kind in MEASURED_CLASSES) != ("allele" in entry):
            raise CardError(f"{at}: exactly the typed classes name the forward-strand allele")
        if "allele" in entry:
            if not isinstance(entry["allele"], str) or not _ALLELE_RE.fullmatch(entry["allele"]):
                raise CardError(f"{at}.allele: expected REF>ALT single bases")
            allele["allele"] = entry["allele"]
        alleles.append(allele)
    _unique((allele["rsid"] for allele in alleles), "rsID", f"{where}.excluded_alleles")
    multiallelic = [
        _rsid(rsid, f"{where}.dbsnp_multiallelic[{i}]")
        for i, rsid in enumerate(_list(data["dbsnp_multiallelic"], f"{where}.dbsnp_multiallelic"))
    ]
    _unique(multiallelic, "rsID", f"{where}.dbsnp_multiallelic")
    return {
        "reference": reference,
        "assay_limits": limits,
        "excluded_alleles": alleles,
        "dbsnp_multiallelic": multiallelic,
    }


def check_pack(cards: Sequence[Card], where: str) -> None:
    """Refuse a declaration that contradicts the panel it is written against.

    An excluded allele that is also typed would be counted on both sides of the statement,
    and M11.5's rule is that nothing excluded may count as typed.
    """
    panel = {c.match.variant.rsid: c for c in cards if c.carrier is not None and c.match}
    genes = {c.gene for c in panel.values()}
    ids = {c.id: c for c in cards}
    scopes = sorted(c.id for c in cards if c.screening_scope is not None)
    if len(scopes) > 1:
        raise CardError(f"{where}: one carrier-screening scope card, got {', '.join(scopes)}")
    for card in cards:
        if card.screening_scope is None:
            continue
        declaration = card.screening_scope
        here = f"{where}: {card.id}"
        typed = sorted(a["rsid"] for a in declaration["excluded_alleles"] if a["rsid"] in panel)
        if typed:
            raise CardError(f"{here}: excluded alleles are in the panel: {', '.join(typed)}")
        stray = sorted(set(declaration["dbsnp_multiallelic"]) - set(panel))
        if stray:
            raise CardError(f"{here}: dbsnp_multiallelic is not in the panel: {', '.join(stray)}")
        for limit in declaration["assay_limits"]:
            if limit["gene"] in genes:
                raise CardError(f"{here}: {limit['gene']} is both typed and an assay limit")
            target = ids.get(limit.get("card", ""))
            if "card" in limit and (target is None or target.kind is not CardKind.IMPOSSIBILITY):
                raise CardError(f"{here}: {limit['card']} is not an impossibility card")


def _marker(
    card_id: str, gene: Any, rsid: str, alleles: Sequence[str], carrier: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "gene": gene,
        "rsid": rsid,
        "condition": carrier["condition"],
        "variant": carrier["variant"],
        "strand_symmetric": is_strand_ambiguous(tuple(alleles)),
    }


def _tally(results: Sequence[tuple[str, str | None, bool]]) -> dict[str, Any]:
    """How many markers gave a result, from ``(status, state, imputed)`` per marker.

    ``state`` is ``None`` for anything but a match. A result filled by imputation is counted
    too, because it is one, and apart, because AGENTS.md 4.1 does not let it read as a chip
    call: imputation fixes neither the rarity problem nor the card's reliability tier.
    """
    states = Counter(state for _, state, _ in results)
    undetermined = Counter(status for status, state, _ in results if state is None)
    return {
        "markers": len(results),
        "with_result": len(results) - states[None],
        "imputed_results": sum(state is not None and imputed for _, state, imputed in results),
        "no_copy": states["non_carrier"],
        "one_copy": states["carrier"],
        "two_copies": states["two_copies"],
        "not_determined": states[None],
        "not_determined_by_status": dict(sorted(undetermined.items())),
    }


def _build(
    declaration: Mapping[str, Any],
    markers: Sequence[Mapping[str, Any]],
    run: Mapping[str, Any] | None,
) -> dict[str, Any]:
    ordered = sorted(markers, key=lambda m: (m["condition"].lower(), m["gene"] or "", m["card_id"]))
    per_gene = Counter(m["gene"] for m in ordered)
    reference = declaration["reference"]["genes"]
    limits = {limit["gene"]: limit for limit in declaration["assay_limits"]}
    listed = {gene["gene"] for gene in reference}
    typed = [
        {**gene, "markers": per_gene[gene["gene"]]} for gene in reference if per_gene[gene["gene"]]
    ]
    limited = [
        {**gene, **limits[gene["gene"]]}
        for gene in reference
        if gene["gene"] in limits and not per_gene[gene["gene"]]
    ]
    untouched = [
        dict(gene)
        for gene in reference
        if not per_gene[gene["gene"]] and gene["gene"] not in limits
    ]
    rsids = {m["rsid"] for m in ordered}
    classes = Counter(allele["class"] for allele in declaration["excluded_alleles"])
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "source": SOURCE,
        "status": "complete",
        "declaration": declaration,
        "panel": {
            "markers": len(ordered),
            "conditions": list(dict.fromkeys(m["condition"] for m in ordered)),
            "genes": sorted({m["gene"] for m in ordered if m["gene"]}),
            "strand_symmetric": sum(m["strand_symmetric"] for m in ordered),
            "dbsnp_multiallelic": len(rsids & set(declaration["dbsnp_multiallelic"])),
            "entries": [dict(m) for m in ordered],
        },
        "genes": {
            "typed": typed,
            "assay_limited": limited,
            "no_card": untouched,
            "typed_outside_reference": sorted(
                {m["gene"] for m in ordered if m["gene"] and m["gene"] not in listed}
            ),
        },
        "counts": {
            "reference_genes": len(reference),
            "autosomal_recessive": sum(g["table"] in AUTOSOMAL_RECESSIVE_TABLES for g in reference),
            "x_linked": sum(g["table"] in X_LINKED_TABLES for g in reference),
            "typed": len(typed),
            "assay_limited": len(limited),
            "no_card": len(untouched),
        },
        # Only the classes present: a class added later must not change an old record.
        "excluded_alleles": dict(sorted(classes.items())),
        "run": None if run is None else dict(run),
    }


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def scope_summary(result: Mapping[str, Any]) -> str:
    """The card face: what is typed, what is not and why, and what this run returned."""
    panel, counts, run = result["panel"], result["counts"], result["run"]
    parts = [
        "This is not a carrier screen.",
        f"This report types {_plural(panel['markers'], 'marker')} for "
        f"{_plural(len(panel['conditions']), 'condition')}.",
        f"{result['declaration']['reference']['name']} names "
        f"{_plural(counts['reference_genes'], 'gene')} "
        f"({counts['autosomal_recessive']} autosomal recessive, {counts['x_linked']} X-linked). "
        f"Of those, {counts['typed']} have a typed marker here, and a typed marker reads one "
        f"named allele rather than the gene; {counts['assay_limited']} depend largely on copy "
        "number, repeat length or inversion, which genotype calls cannot show; and "
        f"{counts['no_card']} have no card, a gap in this report and not a measured limit of "
        "the array.",
    ]
    if run is not None:
        imputed = run["imputed_results"]
        parts.append(
            f"In this run {run['with_result']} of {_plural(run['markers'], 'typed marker')} "
            "gave a result"
            + (f" ({imputed} imputed, not read from the array)" if imputed else "")
            + f" and {run['not_determined']} were not determined."
        )
    parts.append("A no-copy result at every typed marker would still not be a negative screen.")
    return " ".join(parts)


def scope_caveats(result: Mapping[str, Any]) -> tuple[str, ...]:
    """Why a no-copy result is weak, counted from the panel."""
    panel, run = result["panel"], result["run"]
    imputed = 0 if run is None else run["imputed_results"]
    return (
        NOTICE,
        f"{panel['dbsnp_multiallelic']} of the {_plural(panel['markers'], 'typed marker')} list "
        "another base in dbSNP b157, and the array's probe alleles are unpublished, so a "
        "homozygous reference call cannot show that the probe tested the card's allele.",
        f"{panel['strand_symmetric']} of the {_plural(panel['markers'], 'typed marker')} are "
        "A/T or C/G sites, where a homozygous direct call cannot be oriented: no copy and two "
        "copies look the same, so that call is reported as not determined. An imputed call "
        "there is reference-oriented and can give a result.",
        *(
            (
                f"{_plural(imputed, 'result')} here came from imputation, not the array. "
                "Imputation does not make a rare call reliable; each carrier card carries its "
                "own tier.",
            )
            if imputed
            else ()
        ),
    )


def scope_reliability(result: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "tier": None if result is None else "limited",
        "inputs": {
            "reference_recorded": result is not None,
            "clinical_sensitivity_estimated": False,
            "residual_risk_estimated": False,
        },
        "reason": "Counts of typed markers against a cited gene list, under a recorded "
        "declaration; no calibrated detection rate. " + NOTICE,
    }


def pack_scope(pack: KnowledgePack) -> dict[str, Any] | None:
    """The comparison as a property of the knowledge pack: no run and no genotype."""
    from genetics.engine.carrier import carrier_panel

    card = next((c for c in pack.cards if c.computation == SOURCE), None)
    if card is None:
        return None
    assert card.screening_scope is not None  # schema: the computation requires it
    markers = [
        _marker(e.card_id, e.gene, e.rsid, e.alleles, e.declaration.to_dict())
        for e in carrier_panel(pack).entries
    ]
    return _build(card.screening_scope, markers, None)


def assemble_scope_card(
    card: Card, cards: Sequence[AssembledCard] | None, *, reason: str | None = None
) -> AssembledCard:
    """The card, measured from this run's assembled carrier cards or recorded as not run."""
    from genetics.engine.evidence import AssembledCard

    if card.kind is not CardKind.COMPUTED or card.computation != SOURCE:
        raise CardError("Scope assembly requires the declared carrier-screening scope card")
    assert card.screening_scope is not None  # schema: the computation requires it
    result = None
    if cards is not None:
        carriers = [c for c in cards if c.carrier is not None]
        markers = []
        for c in carriers:
            assert c.carrier is not None and c.card.match is not None
            variant = c.card.match.variant
            markers.append(
                _marker(c.card_id, c.card.gene, variant.rsid, variant.key.alleles, c.carrier)
            )
        run = _tally(
            [
                (
                    c.status.value,
                    c.carrier["state"],
                    c.observation is not None and c.observation.call_source is CallSource.IMPUTED,
                )
                for c in carriers
                if c.carrier
            ]
        )
        result = _build(card.screening_scope, markers, run)
    status = MatchStatus.NOT_RUN if result is None else MatchStatus.COMPUTED
    summary = (
        (reason or "Carrier-screening scope was not recorded.")
        if result is None
        else scope_summary(result)
    )
    return AssembledCard(
        card_id=card.id,
        section=card.section,
        kind=card.kind,
        title=card.title,
        status=status,
        summary=summary,
        detail=card.detail or "",
        card=card,
        match=MatchResult(card.id, status, summary),
        observation=None,
        confidence=None,
        frequencies=(),
        confidence_frequency=None,
        citations=card.citations,
        authored_caveats=card.caveats,
        computed_caveats=(NOTICE,) if result is None else scope_caveats(result),
        computation={
            "source": SOURCE,
            "status": status.value,
            "reason": summary if result is None else None,
            "result": result,
            "reliability": scope_reliability(result),
            "method_evidence": dict(card.method_evidence or {}),
        },
    )


def validate_saved(entry: Mapping[str, Any], entries: Sequence[Any]) -> None:
    """Rebuild a saved record from its bundle's own carrier records and refuse any difference.

    Only the bundle is consulted. A run keeps the declaration it was written with.
    """
    computation = entry["computation"]
    result = computation.get("result")
    if result is None:
        return
    if not isinstance(result, Mapping) or set(result) != _RESULT_KEYS:
        raise ScopeError("scope record has the wrong fields")
    try:
        declaration = parse_declaration(result["declaration"], "saved scope")
    except CardError as exc:
        raise ScopeError(str(exc)) from exc
    markers = []
    states = []
    for other in entries:
        carrier = other.get("carrier") if isinstance(other, Mapping) else None
        if carrier is None:
            continue
        variant = other["variant"]
        markers.append(
            _marker(
                other["card_id"], other.get("gene"), variant["rsid"], variant["alleles"], carrier
            )
        )
        observation = other.get("observation")
        states.append(
            (
                other["status"],
                carrier["state"],
                isinstance(observation, Mapping)
                and observation.get("call_source") == CallSource.IMPUTED.value,
            )
        )
    expected = _build(declaration, markers, _tally(states))
    if dict(result) != expected:
        raise ScopeError("scope record does not follow from this bundle's carrier cards")
    if entry.get("summary") != scope_summary(expected):
        raise ScopeError("scope summary does not follow from its record")
    if list(entry.get("computed_caveats") or ()) != list(scope_caveats(expected)):
        raise ScopeError("scope caveats do not follow from its record")


def section_notice(cards: Sequence[StoredCard]) -> dict[str, str] | None:
    """The statement a reader sees above the section, whatever the filters hide.

    From the run's own frozen card. A run without the record says so and still states the
    limit, because a carrier section is no more a screen for having been saved earlier. A
    run with no carrier card has nothing to qualify, and gets no statement.
    """
    title = "Carrier screening scope"
    for card in cards:
        computation = card.computation
        if (
            computation is not None
            and computation.get("source") == SOURCE
            and computation.get("result") is not None
        ):
            return {"status": "recorded", "title": title, "text": card.summary}
    if not any(card.carrier is not None for card in cards):
        return None
    return {"status": "not-recorded", "title": title, "text": NOT_RECORDED}
