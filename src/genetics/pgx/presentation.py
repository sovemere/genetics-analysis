"""Saved assay limits beside sample calls, independent of knowledge-card filters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from genetics.pgx.calling import report

if TYPE_CHECKING:
    from genetics.run.bundle import RunBundle, StoredCard

CYP2D6_CARD_ID = "cyp2d6_structural_variation"


def section_framing() -> dict[str, str]:
    """Current report context, never part of a run's frozen findings."""
    return {
        "context": "current",
        "section": "pharmacogenomics",
        "title": "Pharmacogenomics scope",
        "text": (
            "This is not a prescribing tool. Array-derived calls and conditional CPIC "
            "guidance are educational evidence; they do not establish a clinical phenotype "
            "or select a medicine or dose. Prescribing based on these findings requires "
            "clinical confirmation and the person's full clinical context."
        ),
    }


def cyp2d6_limitation(cards: Sequence[StoredCard]) -> dict[str, Any]:
    """Use the run's frozen card only; never manufacture historical evidence."""
    card = next((c for c in cards if c.card_id == CYP2D6_CARD_ID), None)
    if (
        card is None
        or card.kind != "impossibility"
        or card.status != "not_determinable"
        or not all(
            text and text.strip()
            for text in (card.title, card.summary, card.detail, card.impossibility_reason)
        )
    ):
        return {
            "card_id": CYP2D6_CARD_ID,
            "status": "not-recorded",
            "reason": "Complete CYP2D6 assay-limitation evidence was not recorded by this run. "
            "CYP2D6 is outside the eight-gene SNP caller; no CYP2D6 call is available.",
            "card": None,
        }
    return {
        "card_id": CYP2D6_CARD_ID,
        "status": "recorded",
        "reason": None,
        "card": {
            "title": card.title,
            "summary": card.summary,
            "detail": card.detail,
            "impossibility_reason": card.impossibility_reason,
            "authored_caveats": list(card.authored_caveats),
            "computed_caveats": list(card.computed_caveats),
        },
    }


def saved_report(bundle: RunBundle, gene: str | None = None) -> dict[str, Any]:
    """Saved evidence plus explicitly separate current section context."""
    guidelines = [
        c for c in bundle.cards if c.kind == "guideline" and (gene is None or c.gene == gene)
    ]
    return report(bundle.pgx, gene) | {
        "current_context": {"section_framing": section_framing()},
        "cyp2d6_limitation": cyp2d6_limitation(bundle.cards),
        "guideline_cards": [
            {
                "card_id": c.card_id,
                "summary": c.summary,
                "computation": c.computation,
                "citations": list(c.citations),
            }
            for c in guidelines
        ],
        "guideline_status": "recorded" if guidelines else "not-recorded",
        # M11.4 HLA drug cards live in this section but key on HLA genes, not these eight.
        "hla_cards": []
        if gene is not None
        else [
            {"card_id": c.card_id, "title": c.title, "status": c.status, "summary": c.summary}
            for c in bundle.cards
            if c.kind == "hla" and c.section == "pharmacogenomics"
        ],
    }
