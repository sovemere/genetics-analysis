"""Every section explains why it is empty when it is (roadmap M14.1).

Since M12 the committed pack has cards in all thirteen sections, so "not built yet" is no
longer a reason any section can have. What a section with nothing to show says now depends
on which of three facts it is: the run holds no card here (it was saved with a pack that
held none), the run's cards here produced no interpretation (counted by status, with the
engine's own not-run reasons quoted), or no run is open. The sentence comes from one
function, :func:`genetics.run.reads.empty_reason`, for the nav, the grid and
``runs show --section``.

Cards are built in memory; nothing here reads an export or a saved real run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genetics.engine.cards import KnowledgePack
from genetics.engine.sections import SECTION_ORDER
from genetics.privacy import find_genotypes
from genetics.run import reads
from genetics.run.bundle import BUNDLE_FORMAT_VERSION, RunBundle, StoredCard
from genetics.run.store import RunListing
from genetics.web import views


def _card(section: str, status: str, *, card_id: str = "c", reason: str = "") -> StoredCard:
    return StoredCard(
        card_id=card_id,
        section=section,
        kind="interpretation",
        title=card_id,
        status=status,
        summary="A summary.",
        detail="Detail.",
        gene=None,
        impossibility_reason=None,
        confidence_tier="moderate" if status == "matched" else None,
        variant=None,
        match={"reason": reason} if reason else {},
        confidence=None,
        evidence=None,
        observation=None,
        frequencies=(),
        confidence_frequency=None,
        citations=(),
        authored_caveats=(),
        computed_caveats=(),
    )


def _bundle(*cards: StoredCard) -> RunBundle:
    return RunBundle(
        path=Path("/runs/r1"),
        run_id="r1",
        format_version=BUNDLE_FORMAT_VERSION,
        created_at="2026-11-19T00:00:00Z",
        provenance={},
        qc={},
        cards=cards,
    )


def _pack_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in KnowledgePack.load(None).cards:
        counts[card.section.value] = counts.get(card.section.value, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# The sentence
# ---------------------------------------------------------------------------


def test_every_section_in_the_committed_pack_has_cards() -> None:
    """The premise: no section is unbuilt, so no empty state may say one is."""
    counts = _pack_counts()
    assert set(counts) == {section.value for section in SECTION_ORDER}
    assert all(count > 0 for count in counts.values())
    assert reads.pack_section_counts() == counts


def test_a_section_with_no_card_says_the_run_predates_its_cards() -> None:
    reason = reads.empty_reason((), 3)
    assert reason is not None
    assert "knowledge pack it was saved with had none here" in reason
    assert "The current pack has 3" in reason
    assert "Nothing about this genome is implied" in reason
    assert "roadmap" not in reason and "Not built yet" not in reason


def test_a_section_no_pack_has_written_says_that_instead() -> None:
    reason = reads.empty_reason((), 0)
    assert reason is not None and "No card has been written for this section yet" in reason
    unreadable = reads.empty_reason((), None)
    assert unreadable is not None and "could not be read" in unreadable


def test_a_section_with_no_interpretation_counts_its_statuses() -> None:
    cards = (
        _card("traits", "marker_absent", card_id="a"),
        _card("traits", "marker_absent", card_id="b"),
        _card("traits", "no_call", card_id="c"),
    )
    reason = reads.empty_reason(cards, 29)
    assert reason is not None
    assert reason.startswith("None of the 3 card(s) here produced an interpretation")
    assert "(marker not on this array: 2, no call: 1)" in reason
    assert reason.endswith("Each card states its own reason.")


def test_a_not_run_reason_is_quoted_and_a_failed_match_s_is_not() -> None:
    """A not-run reason is the engine's sentence about a module; a failed match's reason is
    about the reader's call, and stays on the card."""
    cards = (
        _card("immunogenetics", "not_run", card_id="a", reason="HLA did not run"),
        _card("immunogenetics", "not_run", card_id="b", reason="HLA did not run"),
        _card("immunogenetics", "allele_mismatch", card_id="c", reason="ABOUT THE CALL"),
    )
    reason = reads.empty_reason(cards, 4)
    assert reason is not None
    assert reason.count("HLA did not run.") == 1, "a repeated reason is quoted once"
    assert "ABOUT THE CALL" not in reason


def test_quoted_reasons_are_capped_and_the_rest_counted() -> None:
    cards = tuple(
        _card("psychometrics", "not_run", card_id=str(n), reason=f"Reason {n}.") for n in range(5)
    )
    reason = reads.empty_reason(cards, 3) or ""
    assert "Reason 0. Reason 1. Reason 2." in reason
    assert "Reason 3" not in reason
    assert "(2 more reason(s) on the cards.)" in reason


def test_a_not_run_reason_that_reads_as_a_call_is_not_quoted() -> None:
    call = "=".join(("rs1", "CT"))
    cards = (_card("traits", "not_run", reason=f"Odd {call}"),)
    reason = reads.empty_reason(cards, 29) or ""
    assert not find_genotypes(reason)
    assert "Not run:" not in reason


def test_a_section_of_assay_limits_says_so() -> None:
    cards = (_card("ancestry", "not_determinable", card_id=str(n)) for n in range(3))
    reason = reads.empty_reason(tuple(cards), 3) or ""
    assert "Every card here is an assay limit" in reason


@pytest.mark.parametrize("status", ["matched", "computed"])
def test_a_section_with_an_interpretation_has_no_reason(status: str) -> None:
    cards = (_card("traits", "marker_absent", card_id="a"), _card("traits", status))
    assert reads.empty_reason(cards, 29) is None


# ---------------------------------------------------------------------------
# One sentence in every place
# ---------------------------------------------------------------------------


def _shell(bundle: RunBundle | None) -> views.Shell:
    listing = RunListing(root=Path("/runs"), runs=(), incomplete=(), verified=False)
    return views.shell_for(listing, bundle, selected_id=None if bundle is None else "r1")


def test_the_nav_the_grid_and_the_command_say_the_same_thing() -> None:
    bundle = _bundle(
        _card("traits", "marker_absent", card_id="a"),
        _card("immunogenetics", "not_run", card_id="b", reason="HLA did not run."),
        _card("physical_health", "matched", card_id="d"),
    )
    shell = _shell(bundle)
    command = {
        context["section"]: context["empty_reason"]
        for context in reads.section_view(bundle, SECTION_ORDER)["current_context"]["sections"]
    }
    nav = {view.section: view.empty_reason for view in shell.sections}
    grid = {group.key: group.empty_reason for group in shell.grid.groups}
    assert nav == command == grid
    assert command["physical_health"] is None
    assert "HLA did not run." in (command["immunogenetics"] or "")
    assert all(reason is not None for name, reason in command.items() if name != "physical_health")


def test_a_filter_still_says_it_is_the_filter() -> None:
    bundle = _bundle(_card("traits", "matched"))
    listing = RunListing(root=Path("/runs"), runs=(), incomplete=(), verified=False)
    query = views.parse_query({"interpreted": ["1"], "section": ["ancestry"]})
    shell = views.shell_for(listing, bundle, selected_id="r1", query=query)
    traits = next(group for group in shell.grid.groups if group.key == "traits")
    assert "hidden by the current filter" in (traits.empty_reason or "")


def test_with_no_run_open_no_section_claims_anything_about_a_run() -> None:
    shell = _shell(None)
    reasons = {view.empty_reason for view in shell.sections}
    assert reasons == {views.NO_RUN_REASON}
    assert {group.empty_reason for group in shell.grid.groups} == {views.NO_RUN_REASON}
