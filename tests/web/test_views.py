"""The dashboard's view model (roadmap M4.5).

Every rule the shell has to obey is a property of this module, so it is asserted here rather
than against rendered HTML: a test that greps markup for a heading fails the next time
somebody rewords the heading, and passes when the rule is broken in a way the wording
survives.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from genetics.engine.sections import SECTION_ORDER, Section
from genetics.qc.report import QCReport
from genetics.run.bundle import BUNDLE_FORMAT_VERSION, RunBundle, StoredCard
from genetics.run.store import IncompleteWrite, RunListing, RunStatus, RunSummary
from genetics.web import views
from genetics.web.views import (
    QCBanner,
    banner_for,
    section_views,
    shell_for,
    unknown_sections,
)

_UNSET = object()


def _card(
    section: str,
    *,
    status: str = "matched",
    card_id: str = "c",
    kind: str = "interpretation",
    title: str | None = None,
    summary: str = "A summary.",
    detail: str = "Detail.",
    tier: Any = _UNSET,
    evidence: dict[str, Any] | None = None,
    **rest: Any,
) -> StoredCard:
    """A stored card with everything optional. ``tier`` defaults to what the status implies
    -- a card that did not match has no confidence, because confidence is computed from a
    finding -- and is overridable, since a bundle from a newer engine may carry a tier this
    version has never seen."""
    fields: dict[str, Any] = {
        "card_id": card_id,
        "section": section,
        "kind": kind,
        "title": title if title is not None else f"A card ({card_id})",
        "status": status,
        "summary": summary,
        "detail": detail,
        "gene": None,
        "impossibility_reason": None,
        "confidence_tier": ("moderate" if status == "matched" else None)
        if tier is _UNSET
        else tier,
        "variant": None,
        "match": {},
        "confidence": None,
        "evidence": evidence,
        "observation": None,
        "frequencies": (),
        "confidence_frequency": None,
        "citations": (),
        "authored_caveats": (),
        "computed_caveats": (),
    }
    fields.update(rest)
    return StoredCard(**fields)


def _bundle(
    cards: tuple[StoredCard, ...],
    qc: dict[str, Any] | None = None,
    *,
    format_version: int = BUNDLE_FORMAT_VERSION,
) -> RunBundle:
    return RunBundle(
        path=Path("/runs/r1"),
        run_id="r1",
        format_version=format_version,
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


def test_every_banner_field_is_populated_by_a_real_qc_report(sample_qc: QCReport) -> None:
    """Driven by an actual ``QCReport``, and that is the whole point of the test.

    The first cut of ``banner_for`` read ``duplicates.duplicate_rows`` — a key no QC payload
    has ever contained, since ``DuplicateSummary`` carries ``duplicate_rsids`` and
    ``duplicate_positions``. The banner therefore rendered "-" on every run ever saved,
    reading as "not measured" when it had been. It survived a review *and* a field-coverage
    test because both the code and the test invented the same shape: a test that writes its
    own payload agrees with the reader about a structure neither one shares with QC.

    So this asserts against ``QCReport.to_dict()`` and demands every field resolve. A field
    reading a key that does not exist now fails here rather than rendering a dash forever.
    """
    from dataclasses import fields

    banner = banner_for(_bundle((), qc=dict(sample_qc.to_dict())))
    for field in fields(QCBanner):
        assert getattr(banner, field.name) is not None, (
            f"QCBanner.{field.name} reads a key a real QC report does not contain"
        )


def test_the_banner_reads_the_qc_payload(sample_qc: QCReport) -> None:
    """Values, against the same real report."""
    banner = banner_for(_bundle((), qc=dict(sample_qc.to_dict())))

    assert banner.vendor == sample_qc.vendor
    assert banner.total_markers == sample_qc.call_rates.total_markers
    assert banner.inferred_sex == sample_qc.sex.inferred.value
    assert banner.duplicate_rsids == sample_qc.duplicates.duplicate_rsids
    assert banner.duplicate_positions == sample_qc.duplicates.duplicate_positions
    assert banner.het_haploid_calls == sample_qc.het_haploid_calls


def test_the_banner_renders_from_a_qc_payload_that_is_missing_everything() -> None:
    """A bundle written by another version, or edited by hand. The dashboard has to render
    the run that is worth looking at, which is exactly the damaged one -- ``summarise_run``'s
    rule, applied one layer up."""
    banner = banner_for(_bundle((), qc={}))

    assert banner.vendor is None
    assert banner.markers_display == "-"
    assert banner.call_rate_percent == "-"
    assert banner.warnings == ()


@pytest.mark.parametrize(
    "value",
    [
        True,
        "0.99",
        None,
        [0.99],
        # `json.loads` accepts bare NaN and Infinity and `_load_json` does not restrict it,
        # so these reach the banner from a real file. Without the finiteness check the page
        # read `nan%`, which is the one shape `_number`'s docstring already claimed to catch.
        float("nan"),
        float("inf"),
    ],
)
def test_a_call_rate_that_is_not_a_finite_number_is_dropped(value: Any) -> None:
    """``True`` is not a call rate. Formatting it would print ``100.00%`` for a bundle whose
    QC payload is damaged in a way nothing else here would notice."""
    banner = banner_for(_bundle((), qc={"call_rates": {"call_rate": value}}))
    assert banner.call_rate is None
    assert banner.call_rate_percent == "-"


@pytest.mark.parametrize("value", ["677436", True, 1.5, None, []])
def test_a_marker_count_that_is_not_a_whole_number_does_not_take_the_page_down(
    value: Any,
) -> None:
    """``markers_display`` formats with ``:,``, which raises ``ValueError`` on a string.

    ``call_rate`` was guarded from the start and the counts were not, so a ``qc.run.json``
    written by another engine — the case this module exists to render — 500'd the whole
    dashboard instead of showing a dash.
    """
    banner = banner_for(_bundle((), qc={"call_rates": {"total_markers": value}}))
    assert banner.total_markers is None
    assert banner.markers_display == "-"


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
    assert shell.card_count == 1
    assert shell.total_interpreted == 1


# ---------------------------------------------------------------------------
# Labels: adding an enum member has to force a decision about how it reads
# ---------------------------------------------------------------------------


def test_every_confidence_tier_has_a_label_and_an_explanation() -> None:
    """A tier with no entry falls back to its own slug, which puts ``Likely-artifact`` on a
    card face. The fallback exists for a *newer engine's* tier, not for ours."""
    from genetics.engine.confidence import ConfidenceTier
    from genetics.web.views import _TIER_BLURBS, _TIER_LABELS

    for tier in ConfidenceTier:
        assert tier.value in _TIER_LABELS, f"{tier.value} has no display label"
        assert tier.value in _TIER_BLURBS, f"{tier.value} has no explanation for its heading"


def test_every_match_status_has_a_label() -> None:
    from genetics.engine.matcher import MatchStatus
    from genetics.web.views import _STATUS_LABELS

    missing = [s.value for s in MatchStatus if s.value not in _STATUS_LABELS]
    assert not missing, f"statuses with no label: {missing}"


def test_every_effect_measure_evidence_tier_and_replication_has_a_label() -> None:
    """``.capitalize()`` turned ``gwas`` into ``Gwas`` and ``meta_analysis`` into ``Meta
    analysis`` -- a mangled acronym and a missing hyphen, on a page whose argument is that it
    states things precisely."""
    from genetics.engine.cards import EffectMeasure, EvidenceTier, Replication
    from genetics.web.views import _EVIDENCE_TIER_LABELS, _MEASURE_LABELS, _REPLICATION_LABELS

    for member, table, what in (
        (EffectMeasure, _MEASURE_LABELS, "effect measure"),
        (EvidenceTier, _EVIDENCE_TIER_LABELS, "evidence tier"),
        (Replication, _REPLICATION_LABELS, "replication"),
    ):
        missing = [item.value for item in member if item.value not in table]
        assert not missing, f"{what} values with no label: {missing}"


def test_the_untiered_group_key_cannot_collide_with_a_real_tier() -> None:
    """``NO_TIER`` is a group key, a query value and a CSS class at once. A collision would
    make ``?tier=<NO_TIER>`` mean two things."""
    from genetics.engine.confidence import ConfidenceTier

    assert views.NO_TIER not in {tier.value for tier in ConfidenceTier}


def test_a_tier_this_version_does_not_know_is_shown_rather_than_crashing() -> None:
    """A bundle from a newer engine. ``ConfidenceTier(value)`` on the display path would
    raise on the page whose job is to show it."""
    card = views.CardView.of(
        _card("traits", tier="astonishing"), format_version=BUNDLE_FORMAT_VERSION
    )
    assert card.tier_label == "Astonishing"
    assert card.tier_is_known is False
    assert card.tier_rank == len(views.TIER_ORDER), "an unknown tier sorts after the known ones"


# ---------------------------------------------------------------------------
# The filter never hides anything silently (M4.7, AGENTS.md 0.1A)
# ---------------------------------------------------------------------------


def test_the_default_arrangement_filters_nothing() -> None:
    """The way to break "confidence labels, it does not filter" is not a bad filter. It is a
    default one, applied before the reader knew there was a decision."""
    query = views.parse_query({})
    assert query.is_filtered is False
    assert query.query_string == "", "the default arrangement leaves the URL clean"
    for tier in views.TIER_ORDER:
        card = views.CardView.of(_card("traits", tier=tier), format_version=BUNDLE_FORMAT_VERSION)
        assert query.matches(card), f"the default arrangement hides {tier}"


def test_the_weakest_tier_is_on_the_default_page() -> None:
    """Stated separately from the loop above because this is the specific card AGENTS.md
    0.1A is about: a likely artifact appears, looking like what it is."""
    cards = tuple(
        views.CardView.of(_card("traits", tier=tier, card_id=tier), format_version=2)
        for tier in views.TIER_ORDER
    )
    grid = views.grid_for(cards, views.parse_query({}))
    assert grid.hidden == 0
    shown = {card.card_id for group in grid.groups for card in group.cards}
    assert "likely-artifact" in shown


def test_every_hidden_card_is_counted_and_reversible() -> None:
    cards = tuple(
        views.CardView.of(_card("traits", tier=tier, card_id=tier), format_version=2)
        for tier in views.TIER_ORDER
    )
    query = views.parse_query({"tier": ["strong"]})
    grid = views.grid_for(cards, query)

    assert grid.total == 5
    assert grid.shown == 1
    assert grid.hidden == 4, "the four hidden cards must be accounted for by a number"
    assert query.unfiltered().is_filtered is False
    assert views.grid_for(cards, query.unfiltered()).shown == 5


def test_a_filter_never_changes_what_the_navigation_reports() -> None:
    """The nav describes the run; the grid describes an arrangement of it. If a filter
    reached the nav, hiding the low tiers would make a section report 0/0 -- which reads as
    *this section found nothing*, the exact confusion the no-silent-empty rule prevents."""
    bundle = _bundle((_card("traits"), _card("traits", card_id="b"), _card("ancestry")))
    plain = shell_for(_listing(), bundle)
    filtered = shell_for(_listing(), bundle, query=views.parse_query({"tier": ["strong"]}))

    assert filtered.grid.hidden == 3, "the filter really is hiding everything"
    assert [(v.section, v.card_count, v.interpreted) for v in filtered.sections] == [
        (v.section, v.card_count, v.interpreted) for v in plain.sections
    ]
    assert filtered.card_count == plain.card_count


def test_a_group_reports_its_whole_size_even_when_the_filter_empties_it() -> None:
    cards = (views.CardView.of(_card("traits", tier="limited"), format_version=2),)
    grid = views.grid_for(cards, views.parse_query({"tier": ["strong"]}))
    traits = next(group for group in grid.groups if group.key == "traits")

    assert traits.total == 1
    assert traits.cards == ()
    assert traits.hidden == 1
    assert "hidden by the current filter" in (traits.empty_reason or "")


def test_the_three_reasons_a_panel_is_empty_stay_distinct() -> None:
    """Not built yet, nothing matched, and your own filter are three different facts. The
    first names a milestone; collapsing them would tell somebody their array lacks a marker
    when the truth is that nobody has written the card."""
    unbuilt = views.CardGroup(
        key="ancestry", title="A", blurb=None, cards=(), total=0, interpreted=0, milestone="M5"
    )
    assert "roadmap M5" in (unbuilt.empty_reason or "")

    card = views.CardView.of(_card("traits", status="marker_absent"), format_version=2)
    nothing_matched = views.CardGroup(
        key="traits", title="T", blurb=None, cards=(card,), total=1, interpreted=0, milestone="M3"
    )
    assert "none of which produced an interpretation" in (nothing_matched.empty_reason or "")

    hidden = views.CardGroup(
        key="traits", title="T", blurb=None, cards=(), total=1, interpreted=1, milestone="M3"
    )
    assert "hidden by the current filter" in (hidden.empty_reason or "")


def test_an_unrecognised_filter_value_is_dropped_and_reported_not_applied() -> None:
    """Direction matters. Treated as a filter, ``?tier=strng`` matches nothing and shows an
    empty page, which reads as *this run found nothing*. Dropped, it shows everything. Under
    0.1A the safe failure for a filter is always to show more -- and then to say so, because
    silently ignoring it is how somebody concludes the control is broken."""
    query = views.parse_query({"tier": ["strng"], "group": ["sideways"], "section": ["nope"]})

    assert query.is_filtered is False
    assert query.group == views.GROUP_BY_SECTION
    assert set(query.ignored) == {"tier=strng", "group=sideways", "section=nope"}


def test_a_valid_value_survives_beside_an_invalid_one() -> None:
    query = views.parse_query({"tier": ["strong", "strng"]})
    assert query.tiers == frozenset({"strong"})
    assert query.ignored == ("tier=strng",)


def test_a_card_can_be_opened_by_url_while_the_filter_hides_it() -> None:
    """The card route resolves against the run, not against the grid. Otherwise a link would
    work or not depending on a control setting elsewhere on the page."""
    bundle = _bundle((_card("traits", card_id="hidden_one", tier="limited"),))
    shell = shell_for(_listing(), bundle, query=views.parse_query({"tier": ["strong"]}))

    assert shell.grid.shown == 0
    assert views.find_card(shell.cards, "hidden_one") is not None


# ---------------------------------------------------------------------------
# Sorting and grouping (M4.7)
# ---------------------------------------------------------------------------


def test_sorting_by_tier_puts_the_strongest_first_and_the_untiered_last() -> None:
    cards = (
        views.CardView.of(_card("traits", card_id="c", tier="limited"), format_version=2),
        views.CardView.of(
            _card("traits", card_id="d", status="marker_absent", tier=None), format_version=2
        ),
        views.CardView.of(_card("traits", card_id="a", tier="well-established"), format_version=2),
        views.CardView.of(_card("traits", card_id="b", tier="moderate"), format_version=2),
    )
    grid = views.grid_for(cards, views.parse_query({}))
    traits = next(group for group in grid.groups if group.key == "traits")

    assert [card.card_id for card in traits.cards] == ["a", "b", "c", "d"]


def test_sorting_is_deterministic_when_everything_visible_ties() -> None:
    """Two cards at the same tier with the same title must not swap places between renders,
    or a reader who reloads sees the grid shuffle for no reason."""
    cards = tuple(
        views.CardView.of(_card("traits", card_id=name, tier="strong"), format_version=2)
        for name in ("zeta", "alpha", "mu")
    )
    query = views.parse_query({})
    first = views.grid_for(cards, query).groups
    second = views.grid_for(tuple(reversed(cards)), query).groups
    order = [c.card_id for g in first for c in g.cards]

    assert order == [c.card_id for g in second for c in g.cards] == ["alpha", "mu", "zeta"]


def test_grouping_by_tier_renders_every_tier_including_the_empty_ones() -> None:
    """Same rule as the thirteen sections, and the same reason: a grid built from the tiers
    that happen to be present cannot say *nothing scored here*."""
    cards = (views.CardView.of(_card("traits", tier="strong"), format_version=2),)
    grid = views.grid_for(cards, views.parse_query({"group": ["tier"]}))
    keys = [group.key for group in grid.groups]

    assert keys == [*views.TIER_ORDER, views.NO_TIER]
    empty = next(group for group in grid.groups if group.key == "limited")
    assert empty.empty_reason == "No card in this run is at this level."
    assert "roadmap" not in (empty.empty_reason or ""), "a tier is never unbuilt"


def test_a_newer_engines_section_still_gets_a_panel() -> None:
    """`unknown_sections` already tells the reader the nav cannot place these. Dropping them
    from the grid as well is the same card disappearing twice."""
    cards = (views.CardView.of(_card("proteomics", card_id="p"), format_version=2),)
    grid = views.grid_for(cards, views.parse_query({}))

    assert grid.shown == 1
    extra = next(group for group in grid.groups if group.key == "proteomics")
    assert extra.title == "Proteomics"
    assert extra.milestone is None


def test_filter_options_count_the_whole_run_and_start_unselected() -> None:
    cards = tuple(
        views.CardView.of(_card("traits", card_id=f"c{i}", tier="strong"), format_version=2)
        for i in range(3)
    )
    grid = views.grid_for(cards, views.parse_query({"tier": ["strong"]}))
    strong = next(option for option in grid.tier_options if option.value == "strong")
    limited = next(option for option in grid.tier_options if option.value == "limited")

    assert strong.count == 3 and strong.selected is True
    assert limited.count == 0, "an option at zero is still offered"
    assert [option.value for option in grid.tier_options] == [*views.TIER_ORDER, views.NO_TIER]
    assert not any(
        option.selected for option in views.grid_for(cards, views.parse_query({})).tier_options
    )


def test_an_arrangement_round_trips_through_its_own_query_string() -> None:
    """The controls rebuild links from this, so a value that does not survive the round trip
    is a control that silently resets itself."""
    query = views.parse_query(
        {"group": ["tier"], "sort": ["title"], "tier": ["strong", "limited"], "interpreted": ["1"]}
    )
    from urllib.parse import parse_qs

    assert views.parse_query(parse_qs(query.query_string.lstrip("?"))) == query


# ---------------------------------------------------------------------------
# What a card says (M4.6)
# ---------------------------------------------------------------------------


def test_a_relative_effect_names_the_base_rate_it_does_not_have() -> None:
    """AGENTS.md 0.1B asks for the absolute risk, not only the relative one, and no card
    records the base rate of an outcome. Naming the gap is the honest option; printing 1.4
    where a probability belongs is not."""
    card = views.CardView.of(
        _card("traits", evidence={"effect": {"measure": "odds_ratio", "value": 1.4}}),
        format_version=2,
    )
    note = card.base_rate_note or ""
    assert "relative" in note and "base rate" in note
    assert "allele frequency" in note, "the reader must not read one as the other"


def test_a_proportion_needs_no_base_rate_because_it_is_one() -> None:
    card = views.CardView.of(
        _card("traits", evidence={"effect": {"measure": "proportion", "value": 0.992}}),
        format_version=2,
    )
    assert card.base_rate_note is None


def test_an_effect_size_carries_its_interval_and_context() -> None:
    """``proportion 0.992`` alone is nearly meaningless, which is why bundle format 2 exists.
    The scoring inputs in ``confidence`` never held the units, the interval or the sentence
    saying what the number is a proportion of."""
    card = views.CardView.of(
        _card(
            "traits",
            evidence={
                "effect": {
                    "measure": "beta",
                    "value": 0.3,
                    "units": "cm",
                    "ci_low": 0.2,
                    "ci_high": 0.4,
                    "context": "per copy of the minor allele",
                }
            },
        ),
        format_version=2,
    )
    assert card.effect is not None
    assert card.effect.display == "Beta 0.3 cm (95% CI 0.2 to 0.4)"
    assert card.effect.context == "per copy of the minor allele"


def test_an_older_bundle_says_the_evidence_was_never_recorded() -> None:
    """Two absences that are not the same fact: a card with no evidence, and a run saved
    before evidence was stored. A reader told the first about the second goes looking for a
    defect in the card."""
    card = views.CardView.of(_card("traits"), format_version=1)
    absence = card.evidence_absence or ""

    assert "bundle format 1" in absence and "Re-run" in absence


def test_an_impossibility_card_is_not_reported_as_missing_its_evidence() -> None:
    """Its claim is about the assay, not about a population -- it carries an
    ``impossibility_reason`` instead, and the schema forbids it evidence and citations."""
    card = views.CardView.of(
        _card("traits", kind="impossibility", status="not_determinable"), format_version=2
    )
    assert card.evidence_absence is None


def test_a_frequency_is_never_presented_as_a_base_rate() -> None:
    frequency = views.FrequencyView.of(
        {"allele": "G", "frequency": 0.18, "population": "EUR", "source": "gnomAD v2.1.1"}
    )
    assert frequency.display == "G: 18.0% in EUR (gnomAD v2.1.1)"
    assert "base rate" not in frequency.display.lower()


def test_a_rare_allele_does_not_round_away_to_zero() -> None:
    """Rarity is what drives the confidence ceiling (AGENTS.md 4.1), so this is the one
    frequency where the exact figure matters most."""
    assert views.FrequencyView.of({"allele": "T", "frequency": 0.00001}).display.startswith(
        "T: 0.0010%"
    )


def test_a_non_matched_card_does_not_print_its_reason_twice() -> None:
    """The engine writes ``match.reason`` into both summary and detail for every status but
    ``matched``, so rendering both prints one sentence twice -- which reads as a bug."""
    card = views.CardView.of(
        _card(
            "traits",
            status="marker_absent",
            summary="Not on this array.",
            detail="Not on this array.",
        ),
        format_version=2,
    )
    assert card.has_distinct_detail is False


# ---------------------------------------------------------------------------
# Citations resolve, or say they do not
# ---------------------------------------------------------------------------


def test_a_citation_resolves_to_the_record_it_names() -> None:
    from genetics.engine.citations import citation_url

    assert citation_url("doi", "10.1038/ng1733") == "https://doi.org/10.1038/ng1733"
    assert citation_url("pmid", "16444273") == "https://pubmed.ncbi.nlm.nih.gov/16444273/"
    assert citation_url("accession", "rs17822931", "dbSNP") == (
        "https://www.ncbi.nlm.nih.gov/snp/rs17822931"
    )


@pytest.mark.parametrize(
    "kind,identifier,database",
    [
        # The dangerous one: a `url` citation's stored id *is* the href, and a bundle is
        # read back without re-parsing, so an unvalidated one becomes a clickable script.
        ("url", "javascript:alert(1)", None),
        ("url", "http://insecure.example.com/x", None),
        ("doi", "not a doi at all", None),
        ("pmid", "0123", None),
        ("accession", "rs17822931", "a database nobody has heard of"),
        ("accession", "rs17822931", None),
        ("wat", "anything", None),
    ],
)
def test_a_citation_this_project_will_not_link_to_resolves_to_nothing(
    kind: str, identifier: str, database: str | None
) -> None:
    from genetics.engine.citations import citation_url

    assert citation_url(kind, identifier, database) is None


def test_an_unresolvable_citation_still_renders() -> None:
    """A reference nobody can click is still a reference somebody can look up. Dropping it
    would be the silent omission 0.1A rules out, applied to the evidence rather than to the
    finding."""
    link = views.CitationLink.of(
        {"type": "accession", "id": "XYZ123", "title": "A record", "database": "SomethingNew"}
    )
    assert link.url is None
    assert link.title == "A record"
    assert link.label == "SomethingNew:XYZ123"


def test_every_accession_in_the_committed_knowledge_pack_resolves() -> None:
    """An accession naming a database nothing can resolve is a citation the reader cannot
    check, which is most of what a structured citation was for."""
    from genetics.engine.cards import KnowledgePack
    from genetics.engine.citations import CitationType, citation_url

    pack = KnowledgePack.load(Path(__file__).resolve().parents[2] / "knowledge")
    unresolvable = [
        f"{card.id}: {citation.database}:{citation.id}"
        for card in pack.cards
        for citation in card.citations
        if citation.type is CitationType.ACCESSION
        and citation_url(citation.type.value, citation.id, citation.database) is None
    ]
    assert not unresolvable, f"accessions with no resolver: {unresolvable}"


def test_the_controls_offer_exactly_what_the_parser_accepts() -> None:
    """The two had already drifted: the tier checkboxes were built from the tiers *present
    in the run*, so a newer engine's tier got a box, and ticking it produced "ignored
    tier=..." and no filtering — a control that renders, looks live, and lies."""
    cards = (
        views.CardView.of(_card("traits", tier="astonishing"), format_version=2),
        views.CardView.of(_card("traits", card_id="b", tier="strong"), format_version=2),
    )
    grid = views.grid_for(cards, views.parse_query({}))
    offered = {option.value for option in grid.tier_options}

    assert offered == set(views.filterable_tiers())
    assert "astonishing" not in offered, "a tier the parser would drop is not offered"
    assert views.parse_query({"tier": sorted(offered)}).ignored == ()
    assert {option.value for option in grid.section_options} == set(views.filterable_sections())
    assert views.parse_query({"section": list(views.filterable_sections())}).ignored == ()


def test_a_card_at_an_unknown_tier_is_still_shown_and_still_counted_when_hidden() -> None:
    """It cannot be filtered *to*, which is the cost of not offering it. It must still be
    visible by default and still be accounted for when a filter excludes it."""
    cards = (views.CardView.of(_card("traits", tier="astonishing"), format_version=2),)

    assert views.grid_for(cards, views.parse_query({})).shown == 1
    hidden = views.grid_for(cards, views.parse_query({"tier": ["strong"]}))
    assert hidden.shown == 0 and hidden.hidden == 1


def test_sorting_by_section_uses_the_order_agents_md_fixes() -> None:
    """The useful sort on a tier-grouped page, and the one M4.7 names alongside tier.
    Alphabetical would put ancestry after substance use, which is not the reading order the
    thirteen sections were given."""
    cards = tuple(
        views.CardView.of(_card(section, card_id=section), format_version=2)
        for section in ("traits", "ancestry", "nutrition")
    )
    grid = views.grid_for(cards, views.parse_query({"group": ["tier"], "sort": ["section"]}))
    moderate = next(group for group in grid.groups if group.key == "moderate")

    assert [card.card_id for card in moderate.cards] == ["ancestry", "traits", "nutrition"]


def test_only_interpreted_never_hides_an_interpreted_card_however_weak() -> None:
    """The one filter that could be mistaken for a confidence threshold. It is not: it hides
    cards with *no* finding, and a likely-artifact card has one."""
    cards = (
        views.CardView.of(
            _card("traits", card_id="weak", tier="likely-artifact"), format_version=2
        ),
        views.CardView.of(
            _card("traits", card_id="absent", status="marker_absent"), format_version=2
        ),
    )
    grid = views.grid_for(cards, views.parse_query({"interpreted": ["1"]}))
    shown = {card.card_id for group in grid.groups for card in group.cards}

    assert shown == {"weak"}
    assert grid.hidden == 1, "the card it did hide is still counted"


def test_an_impossibility_card_claims_no_measurement_it_could_not_have() -> None:
    """The first cut rendered an effect-size heading over "this card records no effect size"
    and a rarity caveat naming a confidence tier the card does not have. Both are *false
    statements rendered as explanations*, which is worse than the blank they replaced: a
    reader cannot tell them from the case where they are true."""
    card = views.CardView.of(
        _card("genome_structure", kind="impossibility", status="not_determinable"),
        format_version=BUNDLE_FORMAT_VERSION,
    )
    assert card.is_impossibility is True
    assert card.has_a_call is False
    assert card.frequency_absence is None
    assert card.evidence_absence is None


def test_a_marker_absent_card_is_not_told_its_confidence_was_capped() -> None:
    """The same false sentence, one card type over: a card that never matched has no
    confidence tier, so nothing about it was capped by a missing frequency."""
    card = views.CardView.of(
        _card("traits", status="marker_absent"), format_version=BUNDLE_FORMAT_VERSION
    )
    assert card.frequency_absence is None


def test_a_matched_card_with_no_frequency_is_told_the_rarity_check_was_skipped() -> None:
    """The case where the sentence is true, asserted so suppressing it everywhere would not
    quietly pass — the rarity ceiling is the most consequential thing AGENTS.md §4.1 does."""
    card = views.CardView.of(_card("traits"), format_version=BUNDLE_FORMAT_VERSION)
    assert "rarity check" in (card.frequency_absence or "")


def test_call_source_alone_is_not_evidence_that_anything_was_called() -> None:
    """``call_source`` is recorded for every observation including the ones that produced
    nothing, and its value there is ``direct`` — so a marker-absent card rendered *How this
    was called* over *Call source: direct*, which says a direct call was made about a
    position the array does not carry."""
    absent = views.CardView.of(
        _card("traits", status="marker_absent", observation={"call_source": "direct"}),
        format_version=BUNDLE_FORMAT_VERSION,
    )
    assert absent.call_source == "direct"
    assert absent.has_a_call is False

    called = views.CardView.of(
        _card("traits", match={"observed_rsid": "rs1"}), format_version=BUNDLE_FORMAT_VERSION
    )
    assert called.has_a_call is True

    # M8's case: an imputation that was attempted and failed still has something to say.
    imputed = views.CardView.of(
        _card(
            "traits",
            status="no_call",
            observation={"call_source": "imputed", "imputation_quality": 0.2},
        ),
        format_version=BUNDLE_FORMAT_VERSION,
    )
    assert imputed.has_a_call is True


# ---------------------------------------------------------------------------
# URLs are built, not concatenated
# ---------------------------------------------------------------------------


def test_a_run_id_cannot_inject_a_query_string_into_the_links_on_its_page() -> None:
    """Found by the self-pass, reproduced before fixing.

    A run id is a *directory name on disk* and ``list_runs`` reports whatever it finds, not
    only the names ``check_run_id`` would have written — so a run called ``evil?a=b`` gave
    every nav link on the page a query string the reader never set, and one with ``#`` in it
    truncated the card URL and made the card unopenable. Not an escape (autoescaping holds),
    but a URL built from unvalidated content, which is the habit ``runselector`` in app.js
    was already written against.
    """
    assert views.run_path("evil?a=b#c") == "/runs/evil%3Fa%3Db%23c"
    assert views.card_path("r", "ev il?x=1") == "/runs/r/cards/ev%20il%3Fx%3D1"
    # One segment: a `/` must not become a path separator resolving somewhere else.
    assert views.run_path("a/b") == "/runs/a%2Fb"
    assert views.run_path(None) == "/" and views.run_path("") == "/"


def test_the_shell_and_its_cards_agree_on_where_the_run_lives() -> None:
    """One expression builds both. Two derivations of one address is the shape of problem
    this app already hit at M4.1 and M4.2."""
    bundle = _bundle((_card("traits", card_id="c1"),))
    shell = shell_for(_listing(), bundle)

    assert shell.run_url == views.run_path(shell.selected_id)
    assert shell.cards[0].url.startswith(shell.run_url + "/cards/")


def test_a_renamed_bundle_directory_addresses_its_cards_by_the_new_name() -> None:
    """``summarise_run`` settled that the directory name wins over the manifest's id. The
    card URLs have to follow it, or a card link 404s for the one run it was given about."""
    bundle = _bundle((_card("traits", card_id="c1"),))
    renamed = replace(bundle, path=Path("/runs/renamed-on-disk"), run_id="what-the-manifest-says")
    shell = shell_for(_listing(), renamed)

    assert shell.run_url == "/runs/renamed-on-disk"
    assert shell.cards[0].url == "/runs/renamed-on-disk/cards/c1"


def test_a_database_is_recognised_however_its_name_is_punctuated() -> None:
    """The first cut lowercased only, and then needed two keys for the PGS Catalog to cover
    two spellings — two names for one registry, and still nothing for ``PGS-Catalog``, which
    would have rendered as text with nothing to say why."""
    from genetics.engine.citations import citation_url

    expected = "https://www.pgscatalog.org/score/PGS000001/"
    for spelling in ("PGS Catalog", "PGS-Catalog", "pgscatalog", "PGS_Catalog", "pgs catalog"):
        assert citation_url("accession", "PGS000001", spelling) == expected, spelling
    assert citation_url("accession", "PGS000001", "PGS Catalogue") is None, "not a fuzzy match"


def test_the_evidence_block_cannot_claim_a_format_that_does_not_exist_yet() -> None:
    """Two constants that are equal today and will diverge at the next bump. The direction
    that would be a bug is evidence claiming a version the format has not reached."""
    from genetics.run.bundle import BUNDLE_FORMAT_VERSION as current
    from genetics.run.bundle import EVIDENCE_FORMAT_VERSION as evidence

    assert 1 <= evidence <= current
