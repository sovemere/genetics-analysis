"""Impossibility cards are surfaced in their sections, not in an appendix (roadmap M14.6).

M3.7 placed each AGENTS.md 3.2 card in the section it qualifies. What M14.6 adds is that the
placement survives the grid's arrangements:

* **Named at the section's head, whatever the filter.** A tier filter, a section filter or
  "only cards with an interpretation" hides an assay-limit card and counts it (M4.7); the
  section still names its limits, so it never reads as complete. The CLI prints the same
  list (``runs show --section``'s ``assay_limits``).
* **Kept apart from the cards that did not match.** Sorted by tier a card with no tier goes
  last, so the SMN1 card sat beneath every marker-absent carrier card. It now renders in its
  own block below the findings, under a heading, and the same block holds the assay limits
  in the untiered panel when the grid is grouped by tier.
* **A limit the run does not hold is still named.** A limit is about the array, so one the
  current pack holds is true of a run saved before it existed.

Cards are built in memory; nothing here reads an export or a saved real run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genetics.engine.cards import KnowledgePack
from genetics.engine.sections import SECTION_ORDER, Section
from genetics.run import reads
from genetics.run.bundle import BUNDLE_FORMAT_VERSION, RunBundle, StoredCard
from genetics.run.store import RunListing
from genetics.web import views
from genetics.web.app import _environment


def _card(
    card_id: str,
    section: str,
    *,
    kind: str = "interpretation",
    status: str = "marker_absent",
    tier: str | None = None,
) -> StoredCard:
    impossible = kind == "impossibility"
    return StoredCard(
        card_id=card_id,
        section=section,
        kind=kind,
        title=f"Title {card_id}",
        status="not_determinable" if impossible else status,
        summary="A summary.",
        detail="Detail.",
        gene=None,
        impossibility_reason="Not measurable by a genotyping array." if impossible else None,
        confidence_tier=tier,
        variant=None,
        match={},
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
        created_at="2026-11-20T00:00:00Z",
        provenance={},
        qc={},
        cards=cards,
    )


def _shell(bundle: RunBundle, **query: list[str]) -> views.Shell:
    listing = RunListing(root=Path("/runs"), runs=(), incomplete=(), verified=False)
    return views.shell_for(listing, bundle, selected_id="r1", query=views.parse_query(query))


def _group(shell: views.Shell, key: str) -> views.CardGroup:
    return next(group for group in shell.grid.groups if group.key == key)


def _grid(shell: views.Shell) -> str:
    return _environment().get_template("_cardgrid.html").render({"shell": shell})


def _pack_limits() -> dict[str, list[str]]:
    limits: dict[str, list[str]] = {section.value: [] for section in SECTION_ORDER}
    for card in KnowledgePack.load(None).cards:
        if card.kind.value == "impossibility":
            limits[card.section.value].append(card.id)
    return limits


# A carrier section as a real run has it: findings that matched, many that did not, and the
# two assay limits, saved last as the pack lists them.
CARRIER = _bundle(
    _card("carrier_matched", "reproductive", status="matched", tier="moderate"),
    *(_card(f"carrier_absent_{n}", "reproductive") for n in range(6)),
    _card("smn1_copy_number", "reproductive", kind="impossibility"),
    _card("alpha_globin_deletions", "reproductive", kind="impossibility"),
    _card("trait", "traits", status="matched", tier="strong"),
)


# ---------------------------------------------------------------------------
# The list: reads.assay_limits
# ---------------------------------------------------------------------------


def test_a_section_lists_the_run_s_limits_then_the_pack_s_it_lacks() -> None:
    limits = reads.assay_limits("reproductive", CARRIER.cards)
    assert [(limit["card_id"], limit["in_run"]) for limit in limits] == [
        ("smn1_copy_number", True),
        ("alpha_globin_deletions", True),
    ]
    assert limits[0]["title"] == "Title smn1_copy_number", "the run's own title, as saved"

    without = tuple(card for card in CARRIER.cards if card.card_id != "alpha_globin_deletions")
    held = reads.assay_limits("reproductive", without)
    assert [(limit["card_id"], limit["in_run"]) for limit in held] == [
        ("smn1_copy_number", True),
        ("alpha_globin_deletions", False),
    ]
    assert held[1]["title"] == "Alpha-thalassaemia carrier status", "the current pack's title"


def test_a_run_with_none_names_every_limit_of_the_current_pack() -> None:
    """The register is live (AGENTS.md 3.2) and a limit is about the array, so a run saved
    before a limit existed is told of it, by the pack's title, and not linked."""
    pack = _pack_limits()
    listed = reads.assay_limits_by_section(())
    assert {name: [limit["card_id"] for limit in limits] for name, limits in listed.items()} == pack
    assert sum(len(ids) for ids in pack.values()) == 12
    assert all(not limit["in_run"] for limits in listed.values() for limit in limits)


def test_a_limit_is_listed_where_the_run_saved_it() -> None:
    """A card the pack has since moved is the run's, in the section it was saved in; it is
    not also named as missing from its new one."""
    moved = _card("smn1_copy_number", "physical_health", kind="impossibility")
    assert "smn1_copy_number" in [
        limit["card_id"] for limit in reads.assay_limits("physical_health", (moved,))
    ]
    assert "smn1_copy_number" not in [
        limit["card_id"] for limit in reads.assay_limits("reproductive", (moved,))
    ]


def test_only_impossibility_cards_are_limits() -> None:
    absent = _card("not_a_limit", "ancestry")
    assert "not_a_limit" not in [
        limit["card_id"] for limit in reads.assay_limits("ancestry", (absent,))
    ]


def test_runs_show_section_prints_the_list() -> None:
    contexts = reads.section_view(CARRIER, SECTION_ORDER)["current_context"]["sections"]
    by_section = {context["section"]: context["assay_limits"] for context in contexts}
    assert by_section == reads.assay_limits_by_section(CARRIER.cards)


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------


def test_limits_render_in_their_own_block_after_the_findings() -> None:
    """Sorted by tier, a card with no tier goes last; the limits are not left among them."""
    group = _group(_shell(CARRIER), "reproductive")
    assert [card.card_id for card in group.limit_cards] == [
        "alpha_globin_deletions",
        "smn1_copy_number",
    ]
    assert "smn1_copy_number" not in [card.card_id for card in group.findings]
    assert len(group.findings) + len(group.limit_cards) == len(group.cards) == group.total

    panel = _panel(_grid(_shell(CARRIER)), "reproductive")
    block = panel.index("What this array cannot determine")
    face = panel.index('<h4 class="cardtitle">Title smn1_copy_number</h4>')
    assert panel.index('<h3 class="cardtitle">Title carrier_absent_5</h3>') < block < face
    assert '<h3 class="cardtitle">Title carrier_matched</h3>' in panel
    for card in CARRIER.cards[:-1]:
        assert panel.count(f'class="cardtitle">{card.title}<') == 1, "each card renders once"


def test_the_head_of_the_section_names_its_limits_before_any_card() -> None:
    panel = _panel(_grid(_shell(CARRIER)), "reproductive")
    head = panel.index("Not determinable from this array:")
    assert head < panel.index("Title carrier_matched")
    assert '/runs/r1/cards/smn1_copy_number"' in panel[head : panel.index("Title carrier_matched")]


@pytest.mark.parametrize(
    "query",
    [
        {"tier": ["strong"]},
        {"section": ["traits"]},
        {"interpreted": ["1"]},
    ],
)
def test_a_filter_hides_the_cards_and_the_section_still_names_them(
    query: dict[str, list[str]],
) -> None:
    shell = _shell(CARRIER, **query)
    group = _group(shell, "reproductive")
    assert not group.limit_cards, "the filter hides the card itself, as M4.7 requires"
    assert shell.grid.hidden >= 2, "and counts it"
    assert [link.card_id for link in group.limits] == ["smn1_copy_number", "alpha_globin_deletions"]
    panel = _panel(_grid(shell), "reproductive")
    assert "Not determinable from this array:" in panel
    assert "Title smn1_copy_number" in panel and "Title alpha_globin_deletions" in panel
    # A filtered link keeps the reader's arrangement, as every other link on the grid does.
    assert f"/runs/r1/cards/smn1_copy_number{shell.grid.query.query_string}" in panel


def test_grouped_by_tier_the_limits_are_apart_from_the_unmatched_cards() -> None:
    shell = _shell(CARRIER, group=["tier"])
    untiered = _group(shell, views.NO_TIER)
    assert {card.card_id for card in untiered.limit_cards} == {
        "smn1_copy_number",
        "alpha_globin_deletions",
    }
    assert all(not group.limits for group in shell.grid.groups), "a tier has no section"
    panel = _panel(_grid(shell), views.NO_TIER)
    assert panel.index("Title carrier_absent_0") < panel.index("What this array cannot determine")
    block = panel[panel.index("What this array cannot determine") :]
    assert "Reproductive" in block, "each face names the section it qualifies"


def test_a_limit_not_in_the_run_is_named_without_a_link() -> None:
    bundle = _bundle(_card("carrier_matched", "reproductive", status="matched", tier="moderate"))
    group = _group(_shell(bundle), "reproductive")
    assert [link.card_id for link in group.limits] == _pack_limits()["reproductive"]
    assert all(link.url is None for link in group.limits)
    panel = _panel(_grid(_shell(bundle)), "reproductive")
    assert "in the current knowledge pack, not in this run" in panel
    assert "/cards/smn1_copy_number" not in panel


def test_a_section_with_no_limit_says_nothing_about_limits() -> None:
    panel = _panel(_grid(_shell(CARRIER)), "traits")
    assert "Not determinable" not in panel
    assert "What this array cannot determine" not in panel


def test_every_section_of_a_committed_pack_run_names_its_limits() -> None:
    """The twelve, each at the head of the section the pack places it in."""
    cards = tuple(
        _card(card_id, section, kind="impossibility")
        for section, ids in _pack_limits().items()
        for card_id in ids
    )
    shell = _shell(_bundle(*cards))
    named = {group.key: [link.card_id for link in group.limits] for group in shell.grid.groups}
    assert named == _pack_limits()
    assert set(named["ancestry"]) == {
        "y_str_haplotype",
        "mtdna_heteroplasmy",
        "relative_matching_ibd",
    }
    assert named[Section.PHARMACOGENOMICS.value] == ["cyp2d6_structural_variation"]


def _panel(page: str, key: str) -> str:
    start = page.index(f'id="section-{key}"')
    end = page.find("<section", start)
    return page[start : end if end != -1 else len(page)]


# ---------------------------------------------------------------------------
# The command's text form
# ---------------------------------------------------------------------------


def test_the_text_form_names_the_limits() -> None:
    from genetics.cli import runs_cmd

    lines = runs_cmd._section_lines(reads.section_context(Section.REPRODUCTIVE, CARRIER))
    assert "  Not determinable from this array: smn1_copy_number; alpha_globin_deletions" in lines
    bare = _bundle(_card("carrier_matched", "reproductive", status="matched", tier="moderate"))
    lines = runs_cmd._section_lines(reads.section_context(Section.REPRODUCTIVE, bare))
    limit = next(line for line in lines if "Not determinable" in line)
    assert "`genetics cards evidence smn1_copy_number`" in limit
