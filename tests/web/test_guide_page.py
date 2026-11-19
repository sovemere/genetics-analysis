"""The ``/guide`` page and the confidence legend in every page's nav (roadmap M14.3).

The page holds no run, so these use an empty runs directory. That a page of a saved run
carries the legend, that the guide page opens no run while one is saved, and that it shows
nothing ``cards guide`` does not print, is checked on a saved run by ``tests/test_parity.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genetics.privacy import assert_no_genotype
from genetics.run import guide
from genetics.web import WebConfig, create_app

LOCAL_BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url=LOCAL_BASE_URL
    ) as running:
        yield running


def test_the_guide_has_a_row_for_every_badge(client: TestClient) -> None:
    response = client.get("/guide")
    assert response.status_code == 200
    page = response.text
    for entry in guide.legend():
        assert f'id="tier-{entry["key"]}"' in page
    for anchor in ("legend", "reading", "confidence", "rarity", "polygenic", "array", "sources"):
        assert f'id="{anchor}"' in page and f'href="#{anchor}"' in page
    committed = guide.committed_guide()
    for rule in committed["confidence"]["ceilings"]:
        assert rule["rule"] in page
    for card in committed["array"]["not_determinable"]:
        assert card["title"].replace("&", "&amp;") in page
    assert "genetics cards guide --json" in page


def test_the_guide_holds_no_genotype(client: TestClient) -> None:
    assert_no_genotype(client.get("/guide").text, context="guide page")


def test_every_page_s_nav_links_each_badge_into_the_guide(client: TestClient) -> None:
    page = client.get("/").text
    links = re.findall(r'href="/guide#tier-([a-z-]+)"', page)
    assert links == [entry["key"] for entry in guide.legend()]
    assert 'href="/guide"' in page


def test_an_unreadable_runs_directory_still_shows_the_guide(tmp_path: Path) -> None:
    blocker = tmp_path / "runs"
    blocker.write_text("not a directory", encoding="utf-8")
    with TestClient(create_app(WebConfig(runs_root=blocker)), base_url=LOCAL_BASE_URL) as client:
        response = client.get("/guide")
    assert response.status_code == 200
    assert 'id="tier-likely-artifact"' in response.text
