"""Distribution checks for data the installed engine needs at runtime."""

from __future__ import annotations

import tomllib
from pathlib import Path

from genetics.web import STATIC_DIR, VENDOR_MANIFEST, load_vendor_manifest


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

    # Two subdirectories on purpose. A force-include narrowed to `knowledge/traits` would
    # still satisfy a list drawn only from `traits/`, and the impossibility cards are the
    # ones whose absence is hardest to notice: a missing "not determinable" card leaves a
    # section looking complete rather than leaving an obvious hole.
    expected = (
        "traits/pigmentation.yaml",
        "traits/sensory_metabolism.yaml",
        "traits/morphology_circadian.yaml",
        "impossibilities/assay_limits.yaml",
        "impossibilities/structural_variants.yaml",
        "impossibilities/ancestry_limits.yaml",
    )
    assert all((project_root / "knowledge" / relative).is_file() for relative in expected)


def test_the_vendored_front_end_ships_inside_the_package(tmp_path: Path) -> None:
    """The dashboard's JavaScript must survive being installed, and by a different route
    from the cards.

    ``knowledge/`` needs a ``force-include`` because it sits outside ``src/genetics``.
    ``static/`` does not, because it is *inside* the package that
    ``[tool.hatch.build.targets.wheel] packages`` names -- which is a quieter arrangement
    and therefore the one worth pinning: moving these assets anywhere above
    ``src/genetics/`` would drop them from the wheel with nothing failing until somebody
    installed it and got a dashboard with no interactivity and a 404 in the console.

    Checked structurally rather than by building a wheel, matching the test above: the
    release check builds it, and hatchling's packages contract is the stable boundary.
    """
    project_root = Path(__file__).resolve().parents[1]
    with (project_root / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/genetics"]

    package_root = project_root / "src" / "genetics"
    for path in (STATIC_DIR, VENDOR_MANIFEST):
        assert package_root in path.parents, f"{path} would not be packaged"
    for asset in load_vendor_manifest():
        assert asset.path.is_file(), f"{asset.filename} is pinned but absent"
        assert asset.license_path.is_file(), f"{asset.id} ships no licence text"
