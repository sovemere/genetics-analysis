"""Distribution checks for data the installed engine needs at runtime."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_wheel_configuration_includes_the_reviewed_knowledge_corpus() -> None:
    """A source checkout passing card lint is insufficient if the wheel drops the cards.

    This stays a structural test rather than requiring the ``uv`` executable at pytest
    runtime. The release check builds the wheel; Hatch's force-include contract is the
    stable boundary this test protects.
    """
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["force-include"] == {"knowledge": "genetics/knowledge"}

    expected = (
        "traits/pigmentation.yaml",
        "traits/sensory_metabolism.yaml",
        "traits/morphology_circadian.yaml",
    )
    assert all((project_root / "knowledge" / relative).is_file() for relative in expected)
