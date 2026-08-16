"""The privacy suite is selected by marker, and the marker is complete (roadmap M0.4).

The pre-commit hook runs ``pytest -m privacy``. That is the right selector -- privacy
checks belong wherever the thing they guard lives, and several already sit outside this
directory (the fixture-purity checks in ``tests/test_fixtures.py``, the card-file scan in
``tests/engine/test_cards.py``). Selecting by *directory* would silently skip every one of
them at the moment they matter most.

The selector only works if the marker is applied consistently, and it drifted once
already: ``test_leak_detection.py`` sat in this directory unmarked, so directory selection
ran 122 tests and marker selection ran 96 -- neither was the whole suite, and nothing said
so. This file is what stops that recurring. It is the same shape as the structural test in
M1.3 that parses imports to prove analysis modules never reach a vendor adapter:
a convention nobody checks is a convention that has already drifted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.privacy

PRIVACY_DIR = Path(__file__).resolve().parent
MARKER = "pytestmark = pytest.mark.privacy"


def _privacy_modules() -> list[Path]:
    return sorted(p for p in PRIVACY_DIR.glob("test_*.py"))


def test_there_are_privacy_modules_to_check() -> None:
    """Guards the guard: a glob that matched nothing would make the next test vacuous."""
    assert len(_privacy_modules()) >= 5


def test_every_module_here_carries_the_marker() -> None:
    """Otherwise ``-m privacy`` silently runs a subset of this directory.

    Checked at module level rather than per test because that is the convention every file
    here uses, and a per-test decorator would be the drift this test exists to catch.
    """
    unmarked = [p.name for p in _privacy_modules() if MARKER not in p.read_text(encoding="utf-8")]
    assert not unmarked, (
        f"{unmarked} sit in tests/privacy but are not marked, so `pytest -m privacy` -- "
        "what the pre-commit hook runs -- would skip them."
    )


def test_the_hook_selects_by_marker_not_by_directory() -> None:
    """The hook and this file have to agree, and the hook is a shell script nothing types.

    If someone changes ``.githooks/pre-commit`` back to a directory path, every
    privacy-marked test outside this directory stops running before commits, and the only
    symptom is a test count nobody was watching.
    """
    hook = (PRIVACY_DIR.parents[1] / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "-m privacy" in hook, "the pre-commit hook must select the privacy suite by marker"
    assert "pytest tests/privacy" not in hook, (
        "the hook selects by directory, which skips privacy-marked tests living beside the "
        "code they guard"
    )


def test_ci_selects_privacy_checks_by_marker_not_by_directory() -> None:
    """CI must cover the same distributed privacy suite as the pre-commit hook."""

    workflow = (PRIVACY_DIR.parents[1] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "pytest -m privacy" in workflow
    assert "pytest tests/privacy" not in workflow
