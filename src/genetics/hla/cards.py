"""M11.4 HLA-linked cards, read from frozen M11.3 classifier calls.

A card names ordered alternatives -- alleles that must all be carried -- and the engine
writes everything a reader needs to weigh the result: the classifier call for each named
locus, which alternative was carried, the reliability and, for a pharmacogenomics card, the
frozen CPIC rows its lookup selects. No card reruns HIBAG or reselects a classifier.

**Absence is not a negative.** No HLA record, a stage that produced no calls, a named locus
with no prediction, or an allele the classifier's frozen allele list cannot emit makes the
card not determinable, with its reason and no tier. A predicted pair without the allele is a
negative *model call*, carrying that call's posterior and ceiling, and the face says it is
not a clinical exclusion.

**Each confidence input goes in the slot it already has.** The lowest joint posterior among
the card's loci is the imputation quality (loci are not independent, so posteriors are never
multiplied); the M9.13 study-to-sample comparison is the weighted ancestry component, under
M9.13's own policy; there is no HLA allele frequency source, so the calculator caps the tier
at moderate; and the weakest named locus ceiling -- M11.3's fold of posterior, marker
coverage and the classifier's ancestry match -- caps the result. See ``docs/hla_cards.md``.

**One engine for the PGx overlap.** A pharmacogenomics card's carrier state selects the
frozen CPIC lookup ``*57:01 positive``/``negative``. Other HLA genes in a CPIC key resolve
from the same HLA record; non-HLA genes stay explicit unassessed conditions. Recommendation
text always comes from the saved CPIC rows, never from the knowledge pack.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from genetics.ancestry.card_match import compare, sample_context
from genetics.engine.cards import (
    HLA_NONE,
    Card,
    CardKind,
    Evidence,
    HlaAlternative,
    hla_pattern_matches,
)
from genetics.engine.confidence import (
    HLA_PUBLISHED_CALL_THRESHOLD,
    CallSource,
    ConfidenceResult,
    ConfidenceTier,
    calculate_confidence,
)
from genetics.engine.evidence import AssembledCard, render_template
from genetics.engine.matcher import MatchResult, MatchStatus
from genetics.hla import calling, models

SOURCE = "hla_card"
VERSION = 1

NOTICE = (
    "Unphased two-field HIBAG imputation from array markers: a model call, not clinical HLA "
    "typing. A call without an allele is not a clinical exclusion."
)
FREQUENCY_NOTE = (
    "No population HLA allele frequency source is recorded (gnomAD carries no HLA alleles), "
    "so the rarity check cannot be applied and the tier cannot exceed moderate."
)
NOT_EVIDENCE = "This is not evidence for or against any allele."

UNAVAILABLE = {
    "not-selected": "HLA imputation was not requested for this run; it needs the HIBAG "
    "model-terms opt-in (--hla-model-opt-in).",
    "not-supplied": "No HLA stage was supplied when this run was saved.",
    "r-missing": "R was not found, so HLA imputation could not run.",
    "hibag-missing": "The HIBAG R package was not found, so HLA imputation could not run.",
    "model-missing": "The selected HIBAG classifier has not been fetched, so HLA imputation "
    "could not run.",
}

PHASE_TEXT = {
    "heterodimer": "HIBAG calls each locus separately and unphased. This claim concerns "
    "alpha/beta heterodimers, which form whether their chains are encoded in cis or in "
    "trans, so phase does not change it.",
    "genotype": "HIBAG calls each locus separately and unphased. The cited estimate is "
    "defined by unphased allele content at these loci, so phase is neither required nor "
    "established.",
}

CEILING_NAMES = {
    "posterior": "posterior",
    "marker_coverage": "marker coverage",
    "ancestry": "classifier ancestry match",
}
"""Display names for the M11.3 inputs that lowered a call ceiling."""

_CPIC_VALUE = re.compile(r"\*([0-9]{2,3}:[0-9]{2,3}[A-Z]?) (positive|negative)")


def definition(card: Card) -> dict[str, Any]:
    """The authored card in saved form, which :meth:`Card.parse` reads back unchanged."""
    from genetics.run.bundle import _citation_payload, evidence_payload

    if card.kind is not CardKind.HLA or card.hla is None or card.gene is None:
        raise ValueError("Expected an HLA-linked card.")
    outcomes: dict[str, Any] = {}
    for name, outcome in card.outcomes.items():
        outcomes[name] = {
            "summary": outcome.summary,
            "detail": outcome.detail,
            "risk_context": outcome.risk_context,
            **(
                {"evidence": evidence_payload(outcome.evidence)}
                if outcome.overrides_evidence
                else {}
            ),
        }
    return {
        "id": card.id,
        "section": card.section.value,
        "kind": card.kind.value,
        "title": card.title,
        "gene": card.gene,
        "hla": card.hla.to_dict(),
        "outcomes": outcomes,
        "evidence": evidence_payload(card.evidence),
        "citations": [_citation_payload(c) for c in card.citations],
        "caveats": list(card.caveats),
    }


def _identity(hla: Mapping[str, Any]) -> dict[str, Any]:
    """Which frozen HLA record a card was read from; enough to refuse another run's card."""
    reference = hla["reference"]
    choice = hla.get("selection")
    return {
        "schema_version": hla["schema_version"],
        "status": hla["status"],
        "reason": hla["reason"],
        "sample": hla["sample"],
        "reference_sha256": hla["reference_sha256"],
        "classifier": None if reference is None else reference["source"]["population"],
        "classifier_version": None if reference is None else reference["source"]["version"],
        "model_sha256": None if reference is None else reference["source"]["sha256"],
        "selection": None
        if choice is None
        else {
            k: choice[k]
            for k in (
                "status",
                "basis",
                "classifier",
                "automatic_classifier",
                "ancestry_match",
                "reason",
            )
        },
    }


def _assign(alternative: HlaAlternative, pairs: Mapping[str, list[str]]) -> list[str] | None:
    """One allele per term, two terms at a locus taking different alleles; None if unmet."""
    assigned: list[str | None] = [None] * len(alternative.terms)
    for locus in alternative.loci:
        indexes = [i for i, t in enumerate(alternative.terms) if t.locus == locus]
        pair = pairs[locus]
        orders = (
            [(pair[0], pair[1]), (pair[1], pair[0])]
            if len(indexes) == 2
            else [(pair[0],), (pair[1],)]
        )
        for order in orders:
            if all(
                any(hla_pattern_matches(p, allele) for p in alternative.terms[i].alleles)
                for i, allele in zip(indexes, order, strict=True)
            ):
                for i, allele in zip(indexes, order, strict=True):
                    assigned[i] = allele
                break
        else:
            return None
    return [a for a in assigned if a is not None]


def _ceiling_rank(value: str | None) -> int:
    return -1 if value is None else ConfidenceTier(value).rank


def _cpic(
    card: Card, carried: bool | None, hla: Mapping[str, Any], pgx: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """The frozen CPIC rows this card's lookup selects, with every condition explicit."""
    from genetics.pgx.guidelines import NOTICE as CPIC_NOTICE
    from genetics.pgx.guidelines import _publication_citations, _usable_guideline_url
    from genetics.pgx.sources import object_field

    assert card.hla is not None
    binding = card.hla.cpic
    if binding is None:
        return None
    base: dict[str, Any] = {
        "gene": binding.gene,
        "allele": binding.allele,
        "lookup": None,
        "notice": CPIC_NOTICE,
        "source": None,
        "reference_sha256": None,
        "recommendations": [],
        "gaps": [],
    }
    if pgx is None or pgx["status"] != "completed":
        reason = "PGx sample evidence not recorded." if pgx is None else str(pgx["reason"])
        return {
            **base,
            "status": "unavailable",
            "reason": "The frozen CPIC release was not recorded for this run, so no "
            f"recommendation row is shown: {reason}",
        }
    base.update(source=pgx["reference"]["cpic"]["source"], reference_sha256=pgx["reference_sha256"])
    if carried is None:
        return {
            **base,
            "status": "not-determinable",
            "reason": "The HLA call is not determinable, so no CPIC lookup value is selected.",
        }
    lookup = binding.lookup(carried)
    tables = pgx["reference"]["cpic"]["tables"]
    drugs = {d["drugid"]: d for d in tables["drug"]}
    guidelines = {g["id"]: g for g in tables["guideline"]}
    recommendations = []
    for row in tables["recommendation"]:
        key = object_field(row["lookupkey"])
        if key.get(binding.gene) != lookup:
            continue
        linked = [
            p
            for p in tables["pair"]
            if p["guidelineid"] is not None
            and p["guidelineid"] == row["guidelineid"]
            and p["drugid"] == row["drugid"]
            and p["genesymbol"] == binding.gene
        ]
        if not linked:
            continue
        conditions = []
        excluded = False
        for gene, value in key.items():
            if gene == binding.gene:
                conditions.append(
                    {
                        "gene": gene,
                        "required_value": value,
                        "state": "compatible",
                        "actual": lookup,
                        "basis": "this card's HLA call",
                    }
                )
                continue
            locus = gene.removeprefix("HLA-")
            if not gene.startswith("HLA-") or locus not in models.LOCI:
                conditions.append(
                    {
                        "gene": gene,
                        "required_value": value,
                        "state": "unassessed",
                        "actual": None,
                        "basis": f"Not assessed by this HLA card; {gene} conditions are read "
                        "from PGx calls, where a guideline card exists.",
                    }
                )
                continue
            actual = _hla_lookup(locus, value, hla)
            if actual is None:
                conditions.append(
                    {
                        "gene": gene,
                        "required_value": value,
                        "state": "unassessed",
                        "actual": None,
                        "basis": f"HLA-{locus} call does not determine this lookup value.",
                    }
                )
            elif actual != value:
                excluded = True
                break
            else:
                conditions.append(
                    {
                        "gene": gene,
                        "required_value": value,
                        "state": "compatible",
                        "actual": actual,
                        "basis": f"the same run's HLA-{locus} call",
                    }
                )
        if excluded:
            continue
        guideline = guidelines.get(row["guidelineid"])
        publications = [
            p for p in tables["publication"] if p.get("guidelineid") == row["guidelineid"]
        ]
        text = row.get("drugrecommendation")
        readable = isinstance(text, str) and bool(text.strip())
        usable_url = _usable_guideline_url(guideline)
        cited = any(_publication_citations(p) for p in publications)
        gaps = []
        if not readable:
            gaps.append("Recommendation text not provided; implication is unavailable.")
        if not usable_url:
            gaps.append("Guideline row/URL not provided.")
        if not cited:
            gaps.append(
                "Usable titled guideline DOI/PMID evidence not provided; implication is "
                "unavailable."
            )
        if row["drugid"] not in drugs:
            gaps.append("Drug row not provided.")
        if any(c["state"] == "unassessed" for c in conditions):
            gaps.append("Some required gene conditions are unassessed by this card.")
        recommendations.append(
            {
                "source_row": row,
                "drug": drugs.get(row["drugid"]),
                "pairs": linked,
                "guideline": guideline,
                "publications": publications,
                "conditions": conditions,
                "status": "conditional"
                if readable and usable_url and cited
                else "evidence-missing",
                "gaps": gaps,
            }
        )
    gaps = (
        []
        if recommendations
        else [f"No compatible CPIC recommendation row for {binding.gene} {lookup}."]
    )
    return {
        **base,
        "status": "conditional",
        "reason": None,
        "lookup": lookup,
        "recommendations": recommendations,
        "gaps": gaps,
    }


def _hla_lookup(locus: str, value: str, hla: Mapping[str, Any]) -> str | None:
    """This run's CPIC-style value for another HLA gene, or None when the call cannot say.

    ``No Result`` is a lookup for an untested gene, so a predicted locus never equals it,
    as an M10.4 called gene never equals it.
    """
    gene = hla["genes"][locus]
    if gene["status"] != "predicted":
        return None
    parsed = _CPIC_VALUE.fullmatch(value)
    if parsed is None:
        # Not an allele lookup ("No Result"): no called locus is untested, so none equals it.
        return "called"
    allele = parsed.group(1)
    if allele not in hla["reference"]["loci"][locus]["alleles"]:
        return None
    carried = allele in gene["alleles"]
    return f"*{allele} {'positive' if carried else 'negative'}"


def derive(
    card: Card,
    hla: Mapping[str, Any] | None,
    pgx: Mapping[str, Any] | None,
    ancestry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Pure projection of a validated HLA record onto one card; filters nothing."""
    if card.kind is not CardKind.HLA or card.hla is None or card.evidence is None:
        raise ValueError("Expected an HLA-linked card.")
    selector = card.hla
    result: dict[str, Any] = {
        "schema_version": VERSION,
        "definition": definition(card),
        "hla": None,
        "status": "not_run",
        "reason": None,
        "loci": {},
        "alternatives": [],
        "state": None,
        "outcome": None,
        "phase": None
        if selector.phase is None
        else {"policy": selector.phase, "text": PHASE_TEXT[selector.phase]},
        "reliability": None,
        "cpic": None,
    }
    if hla is None:
        result["reason"] = "This run did not record HLA evidence."
        result["cpic"] = _cpic(card, None, {}, pgx)
        return result
    calling.validate(hla)
    result["hla"] = _identity(hla)
    if hla["status"] != "completed":
        code = hla["reason"]
        result["reason"] = (
            "No HIBAG classifier was selected: " + hla["selection"]["reason"]
            if code == "no-classifier"
            else UNAVAILABLE[code]
        )
        result["cpic"] = _cpic(card, None, hla, pgx)
        return result
    population = hla["reference"]["source"]["population"]
    problems: list[tuple[str, str]] = []
    for locus in selector.loci:
        gene = hla["genes"][locus]
        allowed = hla["reference"]["loci"][locus]["alleles"]
        patterns = sorted(
            {
                p
                for alt in selector.alternatives
                for t in alt.terms
                if t.locus == locus
                for p in t.alleles
            }
        )
        confidence = gene.get("confidence")
        if confidence is None:
            # HLA schema 1 recorded no selection: the ancestry match is unknown, never invented.
            confidence = calling.confidence(gene, None)
        emittable = {p: [a for a in allowed if hla_pattern_matches(p, a)] for p in patterns}
        result["loci"][locus] = {
            "status": gene["status"],
            "alleles": gene["alleles"],
            "posterior": gene["posterior"],
            "observed_markers": gene["observed_markers"],
            "model_markers": gene["model_markers"],
            "confidence": confidence,
            "emittable": emittable,
        }
        if gene["status"] == "no-markers":
            problems.append(
                (
                    "insufficient_calls",
                    f"HLA-{locus}: no model marker was observed on this array, so the "
                    "classifier made no call.",
                )
            )
        elif gene["status"] != "predicted":
            problems.append(
                ("insufficient_coverage", f"HLA-{locus}: the classifier returned no prediction.")
            )
        for pattern, alleles in emittable.items():
            if not alleles:
                problems.append(
                    (
                        "insufficient_coverage",
                        f"The {population} classifier cannot emit HLA-{locus}*{pattern}, so its "
                        "call can neither establish nor exclude it.",
                    )
                )
    if problems:
        statuses = {status for status, _ in problems}
        result["status"] = (
            "insufficient_calls" if "insufficient_calls" in statuses else "insufficient_coverage"
        )
        result["reason"] = " ".join(text for _, text in problems)
        result["cpic"] = _cpic(card, None, hla, pgx)
        return result
    pairs = {locus: result["loci"][locus]["alleles"] for locus in selector.loci}
    state = HLA_NONE
    for alternative in selector.alternatives:
        assigned = _assign(alternative, pairs)
        result["alternatives"].append(
            {
                "name": alternative.name,
                "carried": assigned is not None,
                "terms": [
                    {
                        "locus": term.locus,
                        "alleles": list(term.alleles),
                        "matched": [
                            a
                            for a in pairs[term.locus]
                            if any(hla_pattern_matches(p, a) for p in term.alleles)
                        ],
                        "assigned": None if assigned is None else assigned[i],
                    }
                    for i, term in enumerate(alternative.terms)
                ],
            }
        )
        if assigned is not None and state == HLA_NONE:
            state = alternative.name
    outcome_name = selector.states[state]
    outcome = card.outcomes[outcome_name]
    evidence = outcome.evidence if outcome.overrides_evidence else card.evidence
    sample = sample_context(
        None if ancestry is None else ancestry.get("reference_population"),
        None if ancestry is None else ancestry.get("population"),
    )
    comparison = compare(evidence, sample)
    weakest = min(selector.loci, key=lambda locus: result["loci"][locus]["posterior"])
    ceilings = {locus: result["loci"][locus]["confidence"]["ceiling"] for locus in selector.loci}
    rank = max(_ceiling_rank(c) for c in ceilings.values())
    locus_ceiling = (
        None if rank < 0 else next(c for c in ceilings.values() if _ceiling_rank(c) == rank)
    )
    result.update(
        status="matched",
        reason=None,
        state=state,
        outcome=outcome_name,
        reliability={
            "posterior": result["loci"][weakest]["posterior"],
            "posterior_locus": weakest,
            "published_call_threshold": HLA_PUBLISHED_CALL_THRESHOLD,
            "locus_ceiling": locus_ceiling,
            "ceiling_loci": [
                locus for locus, c in ceilings.items() if c is not None and _ceiling_rank(c) == rank
            ],
            "frequency": None,
            "frequency_note": FREQUENCY_NOTE,
            "study_ancestry": comparison,
        },
        cpic=_cpic(card, state != HLA_NONE, hla, pgx),
    )
    return result


def _confidence(card: Card, result: Mapping[str, Any]) -> ConfidenceResult:
    assert result["outcome"] is not None
    outcome = card.outcomes[result["outcome"]]
    evidence: Evidence | None = outcome.evidence if outcome.overrides_evidence else card.evidence
    reliability = result["reliability"]
    computed = calculate_confidence(
        evidence,
        population_allele_frequency=None,
        call_source=CallSource.IMPUTED,
        imputation_quality=reliability["posterior"],
        ancestry_match=reliability["study_ancestry"]["ancestry_match"],
        variant_ancestry=True,
    )
    tier = computed.tier
    if reliability["locus_ceiling"] is not None:
        ceiling = ConfidenceTier(reliability["locus_ceiling"])
        tier = ceiling if ceiling.rank > tier.rank else tier
    return replace(computed, tier=tier)


def _classifier_text(identity: Mapping[str, Any]) -> str:
    choice = identity["selection"]
    if choice is None:
        basis = "explicitly requested; ancestry selection not recorded (HLA schema 1)"
        match = "unknown"
    else:
        basis = (
            "selected from the ancestry placement"
            if choice["basis"] == "ancestry"
            else f"explicitly requested; automatic selection {choice['status']}"
        )
        match = "unknown" if choice["ancestry_match"] is None else f"{choice['ancestry_match']:g}"
    return (
        f"Classifier: {identity['classifier']} HLARES ({basis}; classifier ancestry match {match})."
    )


def _call_text(result: Mapping[str, Any]) -> str:
    calls = "; ".join(
        f"HLA-{locus} {'/'.join(record['alleles'])} (joint posterior {record['posterior']:.2f})"
        for locus, record in result["loci"].items()
    )
    return f"Model call{'s' if len(result['loci']) > 1 else ''}: {calls}."


def _state_text(result: Mapping[str, Any]) -> str:
    """The alternative that set the state. Later ones it subsumes stay in the saved record."""
    carried = [a for a in result["alternatives"] if a["carried"]]
    if not carried:
        names = ", ".join(a["name"] for a in result["alternatives"])
        return f"None of {names} is carried by these model calls."
    first = carried[0]
    alleles = "; ".join(f"HLA-{t['locus']}*{t['assigned']}" for t in first["terms"])
    return f"Carried: {first['name']} ({alleles})."


def _tier_text(result: Mapping[str, Any], tier: ConfidenceTier) -> str:
    reliability = result["reliability"]
    parts = [
        f"Tier {tier.value}: weakest named call HLA-{reliability['posterior_locus']} posterior "
        f"{reliability['posterior']:.2f}"
    ]
    if reliability["locus_ceiling"] is not None:
        lowered = sorted(
            {
                CEILING_NAMES[why]
                for locus in reliability["ceiling_loci"]
                for why in result["loci"][locus]["confidence"]["ceilings"]
            }
        )
        loci = ", ".join(f"HLA-{locus}" for locus in reliability["ceiling_loci"])
        parts.append(
            f"call ceiling {reliability['locus_ceiling']} at {loci} (lowered by "
            f"{', '.join(lowered)})"
        )
    return "; ".join(parts) + "."


def assemble_hla_card(
    card: Card,
    hla: Mapping[str, Any] | None,
    pgx: Mapping[str, Any] | None = None,
    ancestry: Mapping[str, Any] | None = None,
) -> AssembledCard:
    """One HLA card from the run's frozen HLA, PGx and ancestry records."""
    result = derive(card, hla, pgx, ancestry)
    status = MatchStatus(result["status"])
    values = {"gene": card.gene or ""}
    cpic = result["cpic"]
    caveats: list[str] = []
    if result["hla"] is not None and result["hla"]["selection"] is None and result["loci"]:
        caveats.append(
            "This HLA record predates classifier selection (HLA schema 1): its classifier was "
            "named explicitly and its ancestry match is treated as unknown."
        )
    confidence = None
    risk = None
    shown = card
    if status is MatchStatus.MATCHED:
        outcome = card.outcomes[result["outcome"]]
        if outcome.overrides_evidence:
            shown = replace(card, evidence=outcome.evidence)
        confidence = _confidence(card, result)
        risk = outcome.risk_context
        reliability = result["reliability"]
        if reliability["posterior"] < HLA_PUBLISHED_CALL_THRESHOLD:
            caveats.append(
                f"The weakest named call's posterior is below the {HLA_PUBLISHED_CALL_THRESHOLD:g} "
                "call threshold Zheng et al. 2014 chose (about 80% accuracy at that threshold)."
            )
        parts = [
            render_template(outcome.summary, values),
            _call_text(result),
            _state_text(result),
            *(() if result["phase"] is None else (result["phase"]["text"],)),
            _classifier_text(result["hla"]),
            _tier_text(result, confidence.tier),
            FREQUENCY_NOTE,
            reliability["study_ancestry"]["text"],
        ]
        detail_parts = [render_template(outcome.detail, values), NOTICE]
        if result["hla"]["selection"] is not None:
            detail_parts.append(result["hla"]["selection"]["reason"])
    else:
        parts = [f"{card.title}: not determinable. {result['reason']} {NOT_EVIDENCE}"]
        detail_parts = [str(result["reason"]), NOT_EVIDENCE, NOTICE]
    if cpic is not None:
        if cpic["status"] == "conditional":
            drugs = sorted(
                {
                    r["drug"]["name"]
                    for r in cpic["recommendations"]
                    if r["drug"] is not None and r["drug"].get("name")
                }
            )
            parts.append(
                f"Frozen CPIC lookup {cpic['gene']} {cpic['lookup']}: "
                f"{sum(r['status'] == 'conditional' for r in cpic['recommendations'])} "
                f"conditional recommendation row(s)"
                + (f" for {', '.join(drugs)}" if drugs else "")
                + f". {cpic['notice']}"
            )
        else:
            parts.append(str(cpic["reason"]))
        detail_parts.extend(cpic["gaps"])
    tier = None if confidence is None else confidence.tier.value
    return AssembledCard(
        card_id=card.id,
        section=card.section,
        kind=card.kind,
        title=card.title,
        status=status,
        summary=" ".join(p.strip() for p in parts if p.strip()),
        detail=" ".join(p.strip() for p in detail_parts if p.strip()),
        card=shown,
        match=MatchResult(
            card_id=card.id,
            status=status,
            reason=result["reason"] or NOTICE,
            outcome_name=result["outcome"],
        ),
        observation=None,
        confidence=confidence,
        frequencies=(),
        confidence_frequency=None,
        citations=card.citations,
        authored_caveats=card.caveats,
        computed_caveats=tuple(caveats),
        computation={
            "source": SOURCE,
            "status": status.value,
            "reason": result["reason"],
            "result": result,
            "reliability": {"tier": tier, "reason": NOTICE},
            "method_evidence": None,
        },
        risk_context=risk,
    )


def validate_stored(
    entry: Mapping[str, Any],
    hla: Mapping[str, Any] | None,
    pgx: Mapping[str, Any] | None,
    ancestry: Mapping[str, Any] | None,
) -> None:
    """Rebuild a saved card from its frozen definition and this bundle's own records."""
    from genetics.run.bundle import _card_payload

    saved = entry["computation"]["result"]["definition"]
    card = Card.parse(saved, "saved HLA card")
    if models.digest(definition(card)) != models.digest(saved):
        raise ValueError("Saved HLA card definition does not read back unchanged.")
    expected = _card_payload(assemble_hla_card(card, hla, pgx, ancestry))
    # Mode is independently bound to the run; every other field must reproduce exactly.
    expected["imputation_mode"] = entry.get("imputation_mode")
    if models.digest(dict(entry)) != models.digest(expected):
        raise ValueError("Saved HLA card disagrees with frozen HLA evidence.")


def cards_report(cards: Sequence[Any]) -> list[dict[str, Any]]:
    """Saved HLA-linked cards for the HLA views, in pack order, without re-deriving them."""
    return [
        {
            "card_id": c.card_id,
            "section": c.section,
            "title": c.title,
            "status": c.status,
            "tier": c.confidence_tier,
            "summary": c.summary,
        }
        for c in cards
        if c.kind == CardKind.HLA.value
    ]
