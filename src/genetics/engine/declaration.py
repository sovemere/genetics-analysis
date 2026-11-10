"""A knowledge-pack card's evidence, as data, with no run in it (roadmap M13.1).

``genetics cards evidence <card-id>`` prints this. It answers the agent's question "what
does this card rest on?": which variants it reads, the published effect and the
population it came from, the citations with their public pages, and the caveats. It reads
the knowledge pack only, so it holds no genotype, and its command scans the output to keep
that true. That makes it the surface to research a card from: AGENTS.md 1.3 asks for
searches about the variant, never about the reader's call at it.

Outcome text is left out on purpose. It is a template with the reader's genotype still to
be filled in, and ``genetics runs card`` prints it filled in for a saved run. What each
outcome does carry is its own evidence, where schema 3 gives it one (M12.1).
"""

from __future__ import annotations

from typing import Any

from genetics.engine.cards import Card
from genetics.engine.citations import citation_url


def declaration(card: Card) -> dict[str, Any]:
    """The authored claim behind ``card``: variants, evidence, citations, caveats."""
    from genetics.run.bundle import citation_payload, evidence_payload

    match = card.match
    deciles = card.decile_outcomes
    return {
        "card_id": card.id,
        "section": card.section.value,
        "kind": card.kind.value,
        "title": card.title,
        "gene": card.gene,
        "variants": []
        if match is None
        else [
            {
                "rsid": variant.rsid,
                "chrom": variant.key.chrom.value,
                "pos_grch37": variant.key.pos_grch37,
                "alleles": list(variant.key.alleles),
            }
            for variant in match.variants
        ],
        "evidence": evidence_payload(card.evidence),
        "outcome_evidence": {
            name: evidence_payload(outcome.evidence)
            for name, outcome in card.outcomes.items()
            if outcome.overrides_evidence
        },
        "polygenic": None
        if card.pgs is None
        else {
            "pgs_id": card.pgs.pgs_id,
            "scoring_source": card.pgs.source,
            "trait": card.trait,
            "decile_outcomes": None
            if deciles is None
            else {
                "measure": deciles.measure,
                "population": deciles.population,
                "sample_size": deciles.sample_size,
                "source": deciles.source,
                "base_rate": deciles.base_rate,
                "rates": list(deciles.rates),
                "context": deciles.context,
            },
        },
        "hla": None if card.hla is None else card.hla.to_dict(),
        "carrier": None if card.carrier is None else card.carrier.to_dict(),
        "computation": card.computation,
        "method_evidence": None if card.method_evidence is None else dict(card.method_evidence),
        "impossibility_reason": card.impossibility_reason,
        "citations": [
            citation_payload(citation)
            | {"url": citation_url(citation.type.value, citation.id, citation.database)}
            for citation in card.citations
        ],
        "caveats": list(card.caveats),
    }
