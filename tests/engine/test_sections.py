"""The section registry (roadmap M3.1)."""

from __future__ import annotations

import pytest

from genetics.engine import sections
from genetics.engine.sections import SECTION_ORDER, SECTIONS, Section, UnknownSectionError


def test_all_thirteen_sections_are_present() -> None:
    """AGENTS.md 3.1 fixes the number, and the owner decision is recorded there."""
    assert len(Section) == 13
    assert len(SECTION_ORDER) == 13
    assert set(SECTION_ORDER) == set(Section)


def test_every_section_has_info() -> None:
    """A section without display metadata renders as a blank nav entry."""
    assert set(SECTIONS) == set(Section)
    for info in SECTIONS.values():
        assert info.title.strip()
        assert info.blurb.strip()
        assert info.milestone.strip()


def test_order_is_agents_md_order_not_alphabetical() -> None:
    """The order is load-bearing: ancestry feeds PRS confidence, traits demo the product."""
    assert SECTION_ORDER[0] is Section.ANCESTRY
    assert SECTION_ORDER[5] is Section.TRAITS
    assert list(SECTION_ORDER) != sorted(SECTION_ORDER, key=lambda s: s.value)


def test_unknown_section_is_refused() -> None:
    with pytest.raises(UnknownSectionError) as caught:
        sections.get("traits_and_stuff")
    assert "thirteen" in str(caught.value)


def test_the_error_lists_what_is_valid() -> None:
    """A rejection that does not say what would be accepted invites a second guess."""
    with pytest.raises(UnknownSectionError) as caught:
        sections.get("nutrition_metabolism")
    for section in Section:
        assert section.value in str(caught.value)
