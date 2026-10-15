"""Saved assay limits beside sample calls, independent of knowledge-card filters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from genetics.pgx.calling import report

if TYPE_CHECKING:
    from genetics.run.bundle import RunBundle, StoredCard

CYP2D6_CARD_ID = "cyp2d6_structural_variation"


def cyp2d6_limitation(cards: Sequence[StoredCard]) -> dict[str, Any]:
    """Use the run's frozen card only; never manufacture historical evidence."""
    card = next((c for c in cards if c.card_id == CYP2D6_CARD_ID), None)
    if card is None or card.kind != "impossibility" or card.status != "not_determinable":
        return {
            "card_id": CYP2D6_CARD_ID,
            "status": "not-recorded",
            "reason": "The CYP2D6 assay-limitation card was not recorded by this run. "
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
    """Sample-call inspection plus saved assay-limit evidence; no new computation."""
    return report(bundle.pgx, gene) | {"cyp2d6_limitation": cyp2d6_limitation(bundle.cards)}
