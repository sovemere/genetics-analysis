"""The shipped impossibility pack (roadmap M3.7, AGENTS.md 3.2).

These tests defend the *corpus*, not the schema -- :mod:`tests.engine.test_cards` already
covers what a card may and may not say. What can go wrong here is different: AGENTS.md 3.2
asks for a "live register", and a register maintained in one file while the cards it
describes live in another is two ways of naming one set. M0.4 recorded what happens next --
they diverge, and the one the automation reads is the one that matters. So the register is
read out of AGENTS.md and compared against the pack.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from genetics.engine.cards import Card, CardKind, KnowledgePack, default_knowledge_dir
from genetics.engine.evidence import AssembledCard, assemble_card
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.engine.sections import Section
from genetics.ingest import ingest
from genetics.privacy import find_genotypes

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Each AGENTS.md 3.2 bullet, verbatim, and the card(s) that render it. Several cards to one
#: bullet is expected: 3.2's copy-number entry names four specific findings inline, and
#: "SMA carrier status is not available" belongs beside carrier screening while "CYP2D6 is
#: not callable" belongs beside the pharmacogenes, which is M14.6's requirement that these
#: surface in their relevant sections rather than in an appendix.
REGISTER: dict[str, tuple[str, ...]] = {
    'Methylation, epigenetic clocks, "biological age"': ("methylation_epigenetic_age",),
    "Somatic mutations / tumour profiling": ("somatic_and_tumour_variants",),
    "Copy-number and structural variants generally": (
        "structural_and_copy_number_variants",
        "smn1_copy_number",
        "alpha_globin_deletions",
        "rhd_zygosity",
        "cyp2d6_structural_variation",
    ),
    "Y-STRs": ("y_str_haplotype",),
    "mtDNA heteroplasmy": ("mtdna_heteroplasmy",),
    "De novo mutations": ("de_novo_mutations",),
    "Relative matching / IBD segment sharing": ("relative_matching_ibd",),
    "Telomere length": ("telomere_length",),
}


@pytest.fixture(scope="module")
def pack() -> KnowledgePack:
    return KnowledgePack.load(default_knowledge_dir())


def _impossibilities(pack: KnowledgePack) -> dict[str, Card]:
    return {c.id: c for c in pack.cards if c.kind is CardKind.IMPOSSIBILITY}


def _declared_impossibilities() -> list[str]:
    """The bold lead-in of every bullet under AGENTS.md 3.2."""
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    body = text.split("### 3.2 Declared impossibilities", 1)[1].split("\n###", 1)[0]
    return re.findall(r"^- \*\*(.+?)\*\*", body, re.MULTILINE)


# ---------------------------------------------------------------------------
# The register and the pack must name the same set
# ---------------------------------------------------------------------------


def test_agents_md_declares_the_impossibilities_this_mapping_expects() -> None:
    """Half of the check, and the half that catches an *addition*.

    A new bullet in 3.2 with no card is the failure the definition of done rules out --
    "3.2 impossibilities render as explicit not-determinable cards" -- and it would be
    invisible from the pack's side, because nothing in the pack knows the bullet exists.
    Reading the register out of AGENTS.md is what makes it live rather than aspirational.
    """
    assert _declared_impossibilities() == list(REGISTER)


def test_every_declared_impossibility_renders_as_a_card(pack: KnowledgePack) -> None:
    cards = _impossibilities(pack)
    expected = {card_id for ids in REGISTER.values() for card_id in ids}
    assert expected <= set(cards), f"no card for: {sorted(expected - set(cards))}"


def test_no_impossibility_card_is_missing_from_the_register(pack: KnowledgePack) -> None:
    """The other half, and it catches a *card* nobody wrote a bullet for.

    An impossibility this tool renders but 3.2 does not list means the register has stopped
    being the register. The fix is to add the bullet, not to widen this test.
    """
    mapped = {card_id for ids in REGISTER.values() for card_id in ids}
    assert set(_impossibilities(pack)) == mapped


# ---------------------------------------------------------------------------
# Placement and content
# ---------------------------------------------------------------------------


def test_impossibility_cards_sit_in_the_section_that_would_otherwise_look_complete(
    pack: KnowledgePack,
) -> None:
    """M14.6: surfaced in their relevant sections, not collected in an appendix.

    The placements pinned here are the load-bearing ones. CYP2D6 belongs with the
    pharmacogenes because AGENTS.md 3.1 asks for it by name -- a pharmacogenomics section
    that silently skips its most important gene is the specific failure. SMN1 and the
    alpha-globin genes belong with carrier status for the same reason, stated in 3.2 as
    incompleteness that is "invisible unless stated".
    """
    placements = {
        "cyp2d6_structural_variation": Section.PHARMACOGENOMICS,
        "smn1_copy_number": Section.REPRODUCTIVE,
        "alpha_globin_deletions": Section.REPRODUCTIVE,
        "structural_and_copy_number_variants": Section.GENOME_STRUCTURE,
        "y_str_haplotype": Section.ANCESTRY,
        "mtdna_heteroplasmy": Section.ANCESTRY,
        "relative_matching_ibd": Section.ANCESTRY,
    }
    cards = _impossibilities(pack)
    assert {card_id: cards[card_id].section for card_id in placements} == placements


def test_carrier_screening_impossibilities_refuse_to_read_as_a_negative_result(
    pack: KnowledgePack,
) -> None:
    """The point of 3.2's carrier-screening note, and the thing a reader gets wrong.

    A card saying "we cannot test for SMA" sits in a section full of carrier results, and
    the natural reading of a section with no finding for a condition is that the finding was
    negative. Saying so explicitly is the whole reason these cards exist rather than being
    omitted, so it is checked rather than left to editorial memory.
    """
    cards = _impossibilities(pack)
    for card_id in ("smn1_copy_number", "alpha_globin_deletions"):
        caveats = " ".join(cards[card_id].caveats).lower()
        assert "negative result" in caveats or "reassurance" in caveats, card_id


def test_impossibility_cards_state_a_reason_and_cite_nothing(pack: KnowledgePack) -> None:
    """The citation exemption is deliberate, and it is only safe while it stays unused.

    The schema does not *require* a citation here because the claim is about the assay
    rather than the person, and demanding a DOI for "an array does not measure methylation"
    pushes an author toward citing something tangentially related. Shipping zero citations
    across the pack is what keeps that reasoning honest: an author reaching for a reference
    to make a card look better fails here, and ``impossibility_reason`` is where the
    justification is supposed to go.
    """
    for card in _impossibilities(pack).values():
        assert card.citations == (), card.id
        assert card.impossibility_reason and card.impossibility_reason.strip(), card.id
        assert card.match is None and card.evidence is None, card.id


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def assembled(pack: KnowledgePack) -> dict[str, AssembledCard]:
    """Every card taken through ingest, the matcher and assembly, once.

    Through a real export rather than a hand-built table: every other test in this module
    reads the corpus, and this is what proves the corpus reaches a reader.
    """
    fixture = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "ancestry_v2_male.txt"
    results = match_pack(pack, ingest(fixture).table)
    # M3.2's cardinality rule, restated where a violation would silently shrink this dict.
    assert len(results) == len(pack.cards)
    wanted = _impossibilities(pack)
    return {
        card.id: assemble_card(card, result)
        for card, result in zip(pack.cards, results, strict=True)
        if card.id in wanted
    }


def test_impossibilities_assemble_as_not_determinable_against_a_real_export(
    pack: KnowledgePack, assembled: dict[str, AssembledCard]
) -> None:
    """Every impossibility lands on NOT_DETERMINABLE and renders.

    No confidence and no observation, deliberately: there is nothing personal to score, and
    a confidence tier on a card about the assay would be meaningless. The brace check is the
    one that catches an unrendered placeholder reaching a reader.
    """
    for card_id in _impossibilities(pack):
        card = assembled[card_id]
        assert card.status is MatchStatus.NOT_DETERMINABLE, card_id
        assert card.summary.strip() and card.detail.strip(), card_id
        assert card.confidence is None and card.observation is None, card_id
        assert "{" not in card.summary and "{" not in card.detail, card_id


def test_a_gene_named_impossibility_substitutes_its_symbol(
    pack: KnowledgePack, assembled: dict[str, AssembledCard]
) -> None:
    """``gene`` is the only placeholder an impossibility card can fill.

    Everything else in the registry needs a matched variant or an evidence block, which
    these cards do not have by construction. Review found ``gene`` being parsed and then
    silently dropped for this kind, so the substitution is exercised by the shipped corpus
    rather than only by a fixture.
    """
    assert "{gene}" in (_impossibilities(pack)["smn1_copy_number"].summary or "")
    assert "SMN1" in assembled["smn1_copy_number"].summary


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_the_committed_knowledge_corpus_does_not_trip_the_genotype_scanner() -> None:
    """Scans the corpus that actually ships, not the test fixtures.

    ``tests/engine/test_cards.py`` scans ``tests/fixtures/cards``; this scans
    ``knowledge/``, which is what the pre-commit content hook runs over on every card
    commit. The two are not the same set, and the shipping one is the one whose blocked
    commit would send an author looking for ``--no-verify``.
    """
    root = default_knowledge_dir()
    files = sorted(root.rglob("*.yaml"))
    assert files, f"no card files under {root}"
    for path in files:
        assert find_genotypes(path.read_text(encoding="utf-8")) == [], path
