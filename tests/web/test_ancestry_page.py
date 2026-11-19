"""The ancestry page and `genetics runs ancestry` (roadmap M14.2).

The record is the synthetic one in ``tests/conftest.py``: invented population, region,
haplogroup and ancient-group names around invented coordinates. Its fits carry no
positions, which is what a run saved before format 29 looks like; :func:`positioned` adds
them, as a format-29 run records them. No export and no saved real run is read.
"""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine.cards import KnowledgePack
from genetics.qc.report import QCReport
from genetics.run import reads
from genetics.run.bundle import BundleError, _check_ancestry_positions, write_bundle
from genetics.web import WebConfig, create_app

LOCAL_BASE_URL = "http://127.0.0.1:8765"

runner = CliRunner()

SCALE = (0.5, 0.25)
CENTROIDS = {"Zzyzx_Population": (0.4, -5.8), "Qwxz_Population": (3.0, 1.0)}


def positioned(context: AncestryContext) -> AncestryContext:
    """``context`` as a format-29 run records it: a scale and a centroid per fit."""
    population = context.population
    placement = population.placement
    assert placement is not None
    fits = tuple(
        dataclasses.replace(fit, centroid=CENTROIDS[fit.population]) for fit in placement.fits
    )
    placement = dataclasses.replace(placement, fits=fits, scale=SCALE)
    return dataclasses.replace(
        context, population=dataclasses.replace(population, placement=placement)
    )


# ---------------------------------------------------------------------------
# The scatter, as data
# ---------------------------------------------------------------------------


def test_a_positioned_run_is_drawn_in_distance_units(placed_ancestry: AncestryContext) -> None:
    record = positioned(placed_ancestry).to_dict()
    pca = reads.ancestry_report(record)["current_context"]["pca"]
    assert pca["drawn"] is True and pca["why_not"] is None
    coordinates = record["population"]["coordinates"]
    assert pca["sample"] == pytest.approx([coordinates[0] / SCALE[0], coordinates[1] / SCALE[1]])
    assert [ref["population"] for ref in pca["references"]] == [
        fit["population"] for fit in record["population"]["fits"]
    ]
    assert [ref["rank"] for ref in pca["references"]] == [1, 2]
    assert [ref["named"] for ref in pca["references"]] == [True, False]
    assert pca["references"][0]["point"] == list(CENTROIDS["Zzyzx_Population"])
    points = [pca["sample"], *(ref["point"] for ref in pca["references"])]
    (x0, x1), (y0, y1) = pca["bounds"]["x"], pca["bounds"]["y"]
    assert all(x0 < x < x1 and y0 < y < y1 for x, y in points), "padding keeps every mark inside"
    assert pca["regions"] == sorted({"Zzyzx_Region", "Elsewhere"})


def test_a_run_saved_before_format_29_lists_its_fits_without_a_scatter(
    placed_ancestry: AncestryContext,
) -> None:
    pca = reads.ancestry_report(placed_ancestry.to_dict())["current_context"]["pca"]
    assert pca["drawn"] is False and pca["sample"] is None and pca["bounds"] is None
    assert "before reference-population positions were recorded (M14.2)" in pca["why_not"]
    assert len(pca["references"]) == 2, "the distances are the run's own and still shown"


def test_a_run_whose_ancestry_did_not_run_or_was_not_recorded_says_which() -> None:
    not_run = AncestryContext.not_run("no reference panel was fetched").to_dict()
    pca = reads.ancestry_report(not_run)["current_context"]["pca"]
    assert pca["status"] == "not_run" and pca["drawn"] is False
    assert "no reference panel was fetched" in pca["why_not"]
    absent = reads.ancestry_report(None)
    assert absent["ancestry"] is None
    assert absent["current_context"]["pca"]["status"] == "not_recorded"
    assert "bundle format 3" in absent["current_context"]["pca"]["why_not"]


def test_positions_in_a_format_before_29_are_refused(placed_ancestry: AncestryContext) -> None:
    record = positioned(placed_ancestry).to_dict()
    _check_ancestry_positions(record, 29)
    with pytest.raises(BundleError, match="require bundle format 29"):
        _check_ancestry_positions(record, 28)
    _check_ancestry_positions(placed_ancestry.to_dict(), 28)
    record["population"]["scale"] = ["0.5", 0.25]
    with pytest.raises(BundleError, match="malformed reference position"):
        _check_ancestry_positions(record, 29)


# ---------------------------------------------------------------------------
# The command and the page, on a saved run
# ---------------------------------------------------------------------------


@pytest.fixture
def runs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "data" / "runs"
    root.mkdir(parents=True)
    return root


def _save(
    root: Path,
    context: AncestryContext,
    qc: QCReport,
    pack: KnowledgePack,
    cards: tuple[object, ...],
) -> str:
    path = write_bundle(
        qc=qc,
        cards=cards,  # type: ignore[arg-type]
        pack=pack,
        ancestry=context,
        runs_root=root,
        lock_path=root / "absent.lock",
        tools_root=root / "tools",
    )
    return path.name


@pytest.fixture
def client(runs_root: Path) -> Iterator[TestClient]:
    with TestClient(create_app(WebConfig(runs_root=runs_root)), base_url=LOCAL_BASE_URL) as running:
        yield running


def test_the_page_draws_the_run_against_its_own_reference(
    client: TestClient,
    runs_root: Path,
    placed_ancestry: AncestryContext,
    ancestry_names: dict[str, str],
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[object, ...],
) -> None:
    run = _save(runs_root, positioned(placed_ancestry), sample_qc, sample_pack, sample_cards)
    body = client.get(f"/runs/{run}/ancestry").text
    assert '<figure class="pcachart">' in body
    assert body.count('class="pcanear"') == 2 and "This run</title>" in body
    for name in ("population", "second_population", "mt", "y", "ancient"):
        assert ancestry_names[name] in body, name
    assert "affinity, not ancestry proportions" in body
    assert "on this array's defining sites" in body
    assert "Infinity" not in body and "nan" not in body.lower().split("<svg")[1].split("</svg>")[0]
    # The nav links the page from every run page.
    assert f"/runs/{run}/ancestry" in client.get(f"/runs/{run}").text


def test_an_older_run_s_page_says_why_there_is_no_scatter(
    client: TestClient,
    runs_root: Path,
    placed_ancestry: AncestryContext,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[object, ...],
) -> None:
    run = _save(runs_root, placed_ancestry, sample_qc, sample_pack, sample_cards)
    body = client.get(f"/runs/{run}/ancestry").text
    assert '<figure class="pcachart">' not in body
    assert "before reference-population positions were recorded" in body
    assert "Nearest reference populations" in body


def test_the_command_prints_what_the_page_draws(
    runs_root: Path,
    placed_ancestry: AncestryContext,
    ancestry_names: dict[str, str],
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[object, ...],
    agent_schema_check: Callable[[object], str],
) -> None:
    from genetics.run.store import load_run

    run = _save(runs_root, positioned(placed_ancestry), sample_qc, sample_pack, sample_cards)
    result = runner.invoke(app, ["runs", "ancestry", run, "--json"])
    assert result.exit_code == 0
    document: dict[str, Any] = json.loads(result.stdout)
    assert agent_schema_check(document) == "runs.ancestry"
    expected = json.loads(json.dumps(reads.ancestry_view(load_run(run))))
    assert {key: value for key, value in document.items() if key != "schema"} == expected
    assert document["current_context"]["pca"]["drawn"] is True
    text = runner.invoke(app, ["runs", "ancestry", run])
    assert text.exit_code == 0
    assert ancestry_names["mt"] in text.stdout and "scatter drawn" in text.stdout
    assert math.isfinite(document["current_context"]["pca"]["sample"][0])


def test_the_section_points_to_the_command(placed_ancestry: AncestryContext) -> None:
    records = dict(reads.SAVED_RECORDS)
    from genetics.engine.sections import Section

    assert ("Placement, ancient affinity and haplogroups", "genetics runs ancestry {run}") in (
        records[Section.ANCESTRY]
    )
