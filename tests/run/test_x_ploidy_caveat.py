"""An X call is said to be unresolved when the sex is (M15.5; project engine review C2)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from genetics.engine.cards import KnowledgePack
from genetics.engine.evidence import assemble_card
from genetics.engine.matcher import MatchResult, MatchStatus, match_pack
from genetics.ingest.keys import MergeTable
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import InferredSex
from genetics.run.pipeline import (
    UNRESOLVED_X_PLOIDY_CAVEAT,
    flag_unresolved_x_ploidy,
    observations,
)

CARD = "ar_rs6152_androgenetic_alopecia"


def _match(pair: str) -> tuple[KnowledgePack, tuple[MatchResult, ...]]:
    card = next(c for c in KnowledgePack.load().cards if c.id == CARD)
    assert card.match is not None
    variant = card.match.variant
    table = GenotypeTable(
        pl.DataFrame(
            [
                {
                    "rsid": variant.rsid,
                    "chrom": variant.key.chrom.value,
                    "pos_grch37": variant.key.pos_grch37,
                    "a1": pair[0],
                    "a2": pair[1],
                    "genotype": "".join(sorted(pair)),
                    "call_status": "called",
                }
            ],
            schema=NORMALIZED_SCHEMA,
        ),
        vendor="synthetic",
    )
    pack = KnowledgePack((card,), Path("synthetic-memory"))
    matches = match_pack(pack, table, merges=MergeTable.empty())
    assert matches[0].status is MatchStatus.MATCHED
    return pack, matches


@pytest.mark.parametrize("pair", ["AA", "GG"])
def test_a_homozygous_looking_x_call_under_ambiguous_sex_says_it_may_be_one_copy(
    pair: str,
) -> None:
    pack, matches = _match(pair)
    flagged = flag_unresolved_x_ploidy(pack, matches, InferredSex.AMBIGUOUS)
    assert UNRESOLVED_X_PLOIDY_CAVEAT in flagged[0].caveats
    assembled = assemble_card(pack.cards[0], flagged[0], observations(pack, flagged)[CARD])
    assert UNRESOLVED_X_PLOIDY_CAVEAT in assembled.computed_caveats
    assert assembled.confidence is not None, "the card is still shown, with its tier"


def test_a_heterozygous_x_call_shows_two_copies_and_needs_no_caveat() -> None:
    pack, matches = _match("AG")
    assert flag_unresolved_x_ploidy(pack, matches, InferredSex.AMBIGUOUS) == matches


@pytest.mark.parametrize("sex", [InferredSex.FEMALE, InferredSex.MALE])
def test_a_resolved_sex_adds_nothing(sex: InferredSex) -> None:
    pack, matches = _match("GG")
    assert flag_unresolved_x_ploidy(pack, matches, sex) == matches
