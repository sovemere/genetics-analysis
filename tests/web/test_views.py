"""The dashboard's view model (roadmap M4.5).

Every rule the shell has to obey is a property of this module, so it is asserted here rather
than against rendered HTML: a test that greps markup for a heading fails the next time
somebody rewords the heading, and passes when the rule is broken in a way the wording
survives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from genetics.engine.sections import SECTION_ORDER, Section
from genetics.run.bundle import RunBundle, StoredCard
from genetics.run.store import IncompleteWrite, RunListing, RunStatus, RunSummary
from genetics.web.views import (
    banner_for,
    section_views,
    shell_for,
    unknown_sections,
)


def _card(section: str, *, status: str = "matched", card_id: str = "c") -> StoredCard:
    return StoredCard(
        card_id=card_id,
        section=section,
        kind="interpretation",
        title="A card",
        status=status,
        summary="A summary.",
        detail="Detail.",
        gene=None,
        impossibility_reason=None,
        confidence_tier="moderate" if status == "matched" else None,
        variant=None,
        match={},
        confidence=None,
        observation=None,
        frequencies=(),
        confidence_frequency=None,
        citations=(),
        authored_caveats=(),
        computed_caveats=(),
    )


def _bundle(cards: tuple[StoredCard, ...], qc: dict[str, Any] | None = None) -> RunBundle:
    return RunBundle(
        path=Path("/runs/r1"),
        run_id="r1",
        format_version=1,
        created_at="2026-08-21T00:00:00Z",
        provenance={},
        qc=qc if qc is not None else {},
        cards=cards,
    )


def _listing(*runs: RunSummary, incomplete: tuple[IncompleteWrite, ...] = ()) -> RunListing:
    return RunListing(root=Path("/runs"), runs=runs, incomplete=incomplete, verified=False)


def _summary(run_id: str, status: RunStatus = RunStatus.READABLE, **kwargs: Any) -> RunSummary:
    return RunSummary(run_id=run_id, path=Path("/runs") / run_id, status=status, **kwargs)


# ---------------------------------------------------------------------------
# No silent empty sections
# ---------------------------------------------------------------------------


def test_all_thirteen_sections_render_whatever_the_run_contains() -> None:
    """A nav built by grouping the cards present is a nav of however many sections happen
    to be populated, and a reader cannot tell an empty section from one that does not
    exist."""
    views = section_views(())

    assert len(views) == len(SECTION_ORDER) == 13
    assert [v.section for v in views] == [s.value for s in SECTION_ORDER]


def test_the_order_is_the_one_agents_md_fixes_not_alphabetical() -> None:
    views = section_views((_card("traits"),))
    assert [v.section for v in views][:2] == ["ancestry", "physical_health"]


def test_an_empty_section_names_the_milestone_that_will_fill_it() -> None:
    """ "Not built yet" and "nothing matched" are different facts and need different
    sentences: one is about this tool's progress, the other about this genome."""
    views = {v.section: v for v in section_views(())}
    ancestry = views["ancestry"]

    assert ancestry.is_empty
    assert ancestry.empty_reason is not None
    assert "M5" in ancestry.empty_reason
    assert "Not built yet" in ancestry.empty_reason


def test_a_populated_section_with_nothing_matched_says_that_instead() -> None:
    """The reader's array, not the roadmap. Telling them a card does not exist when it does
    and simply did not match would be the wrong diagnosis of their own data."""
    views = {v.section: v for v in section_views((_card("traits", status="marker_absent"),))}
    traits = views["traits"]

    assert not traits.is_empty
    assert traits.card_count == 1
    assert traits.interpreted == 0
    assert traits.empty_reason is not None
    assert "none of which produced an interpretation" in traits.empty_reason


def test_a_section_with_an_interpretation_has_no_empty_reason() -> None:
    views = {v.section: v for v in section_views((_card("traits"),))}
    assert views["traits"].empty_reason is None
    assert views["traits"].interpreted == 1


def test_every_section_is_either_populated_or_explains_itself() -> None:
    """The definition of done, item 3, as one assertion over the whole nav."""
    for cards in ((), (_card("traits"),), (_card("traits", status="no_call"),)):
        for view in section_views(cards):
            assert view.interpreted > 0 or view.empty_reason is not None, view.section


# ---------------------------------------------------------------------------
# A newer engine's sections
# ---------------------------------------------------------------------------


def test_a_section_this_version_does_not_know_is_reported_not_dropped() -> None:
    """Cards under an unknown section vanish from a nav built on this version's thirteen,
    which is indistinguishable from cards that did not match -- the confusion
    ``UnknownSectionError`` exists to prevent at card-load time, arriving through the nav."""
    cards = (_card("traits"), _card("epigenetics", card_id="future"))

    assert unknown_sections(cards) == ("epigenetics",)
    assert sum(v.card_count for v in section_views(cards)) == 1


def test_a_known_section_is_never_reported_as_unknown() -> None:
    cards = tuple(_card(s.value, card_id=s.value) for s in Section)
    assert unknown_sections(cards) == ()


# ---------------------------------------------------------------------------
# The QC banner
# ---------------------------------------------------------------------------


def test_the_banner_reads_the_qc_payload() -> None:
    banner = banner_for(
        _bundle(
            (),
            qc={
                "vendor": "ancestrydna_v2",
                "source_path": "AncestryDNA.txt",
                "call_rates": {"total_markers": 677436, "call_rate": 0.999188},
                "sex": {"inferred": "male"},
                "build": {"verdict": "consistent"},
                "het_haploid_calls": 7,
                "duplicates": {"duplicate_rows": 656},
                "warnings": ["first", "second"],
            },
        )
    )

    assert banner.vendor == "ancestrydna_v2"
    assert banner.markers_display == "677,436"
    assert banner.call_rate_percent == "99.92%"
    assert banner.inferred_sex == "male"
    assert banner.warnings == ("first", "second")


def test_the_banner_renders_from_a_qc_payload_that_is_missing_everything() -> None:
    """A bundle written by another version, or edited by hand. The dashboard has to render
    the run that is worth looking at, which is exactly the damaged one -- ``summarise_run``'s
    rule, applied one layer up."""
    banner = banner_for(_bundle((), qc={}))

    assert banner.vendor is None
    assert banner.markers_display == "-"
    assert banner.call_rate_percent == "-"
    assert banner.warnings == ()


@pytest.mark.parametrize("value", [True, "0.99", None, [0.99]])
def test_a_call_rate_that_is_not_a_number_is_dropped_rather_than_rendered(value: Any) -> None:
    """``True`` is not a call rate. Formatting it would print ``100.00%`` for a bundle whose
    QC payload is damaged in a way nothing else here would notice."""
    banner = banner_for(_bundle((), qc={"call_rates": {"call_rate": value}}))
    assert banner.call_rate is None
    assert banner.call_rate_percent == "-"


def test_warnings_are_never_truncated() -> None:
    """AGENTS.md 0.1A: the job is to label, not to filter. A "show more" that hides the
    third warning is a filter wearing a disclosure triangle."""
    many = [f"warning {n}" for n in range(12)]
    assert banner_for(_bundle((), qc={"warnings": many})).warnings == tuple(many)


def test_a_string_warnings_field_does_not_become_one_warning_per_character() -> None:
    """A ``str`` is a ``Sequence``, so the obvious isinstance check turns "oops" into four
    warnings reading o, o, p, s."""
    assert banner_for(_bundle((), qc={"warnings": "oops"})).warnings == ()


# ---------------------------------------------------------------------------
# The run selector
# ---------------------------------------------------------------------------


def test_an_unopenable_run_is_listed_and_marked_unselectable() -> None:
    """Hiding it is how somebody concludes their analysis was deleted. ``runs list`` shows
    the same rows with the same reasoning."""
    shell = shell_for(
        _listing(
            _summary("good"),
            _summary("broken", RunStatus.DAMAGED, detail="qc.run.json is missing"),
            _summary("newer", RunStatus.FUTURE_VERSION, detail="written by format 2"),
        ),
        None,
        problem="pick one",
    )

    assert [run.run_id for run in shell.runs] == ["good", "broken", "newer"]
    assert [run.selectable for run in shell.runs] == [True, False, False]
    assert shell.runs[1].detail == "qc.run.json is missing"


def test_an_interrupted_save_is_surfaced_with_its_size() -> None:
    """A stale multi-gigabyte intermediate reported as nothing at all is the M3.3-M3.6
    finding about ``refs status``; the store already refuses to make it, and so does this."""
    shell = shell_for(
        _listing(
            incomplete=(
                IncompleteWrite(run_id="x", path=Path("/runs/.incoming-x"), size_bytes=2_500_000),
            )
        ),
        None,
        problem="none",
    )

    (notice,) = shell.incomplete
    assert notice.run_id == "x", "the id the save was claiming, which is still free"
    assert notice.name == ".incoming-x"
    assert notice.size_display == "2.5 MB"


# ---------------------------------------------------------------------------
# The shell as a whole
# ---------------------------------------------------------------------------


def test_the_nav_renders_with_no_run_open() -> None:
    """A nav that appears only once a run loads makes an empty dashboard look broken."""
    shell = shell_for(_listing(), None, problem="No runs have been saved yet.")

    assert len(shell.sections) == 13
    assert shell.banner is None
    assert not shell.has_selection
    assert shell.problem is not None


def test_a_selected_run_reports_its_own_id_rather_than_the_requested_one() -> None:
    """The bundle is the authority on what was opened; the requested id is only a request."""
    shell = shell_for(_listing(_summary("r1")), _bundle((_card("traits"),)), selected_id="ignored")

    assert shell.selected_id == "r1"
    assert shell.has_selection
    assert shell.problem is None
    assert shell.total_cards == 1
    assert shell.total_interpreted == 1
