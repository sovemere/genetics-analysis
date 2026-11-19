"""The dashboard's search page and the search box in every run page's nav (roadmap M14.4).

The saved run is six committed cards matched against an invented table, as in
``tests/test_cli_search.py``: each card's first and last declared allele. No export is read.
That the page holds exactly what ``genetics runs search --json`` prints, and refuses what it
refuses in the same words, is checked on a larger saved run by ``tests/test_parity.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

from genetics.ancestry.context import AncestryContext
from genetics.engine import search as engine
from genetics.engine.cards import KnowledgePack, default_knowledge_dir
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import match_pack
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run import reads
from genetics.run.bundle import read_bundle, write_bundle
from genetics.run.pipeline import observations
from genetics.testing.parity import REFUSED_RSID, refused_query
from genetics.web import WebConfig, create_app

LOCAL_BASE_URL = "http://127.0.0.1:8765"

CARD_IDS = (
    "mthfr_c677t_homocysteine",
    "mthfr_c677t_venous_thrombosis",
    "mthfr_c677t_coronary_heart_disease",
    "mthfr_c677t_depression",
    "wnt10a_hair_curl",
    "methylation_epigenetic_age",
)
RUN_ID = "20261119T120000Z-5ea7c400"
CARD_LINK = re.compile(r'<a class="cardlink"\s+href="/runs/[^/]+/cards/([^"?]+)')


def _table(pack: KnowledgePack) -> GenotypeTable:
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for card in pack.cards:
        if card.match is None:
            continue
        variant = card.match.variants[0]
        first, last = variant.key.alleles[0], variant.key.alleles[-1]
        rows[(variant.key.chrom.value, variant.key.pos_grch37)] = {
            "rsid": variant.rsid,
            "chrom": variant.key.chrom.value,
            "pos_grch37": variant.key.pos_grch37,
            "a1": first,
            "a2": last,
            "genotype": "".join(sorted(first + last)),
            "call_status": "called",
        }
    return GenotypeTable(
        pl.DataFrame(list(rows.values()), schema=NORMALIZED_SCHEMA), vendor="synthetic"
    )


@pytest.fixture(scope="module")
def runs_root(tmp_path_factory: pytest.TempPathFactory, sample_qc: QCReport) -> Path:
    root = tmp_path_factory.mktemp("search") / "runs"
    full = KnowledgePack.load(default_knowledge_dir())
    pack = KnowledgePack(tuple(card for card in full.cards if card.id in CARD_IDS), full.source_dir)
    matches = match_pack(pack, _table(pack))
    write_bundle(
        qc=sample_qc,
        cards=assemble_pack(pack, matches, observations(pack, matches)),
        pack=pack,
        ancestry=AncestryContext.not_run("synthetic test bundle"),
        runs_root=root,
        run_id=RUN_ID,
        lock_path=root.parent / "absent.lock",
        tools_root=root.parent / "tools",
    )
    return root


@pytest.fixture(scope="module")
def client(runs_root: Path) -> Iterator[TestClient]:
    app = create_app(WebConfig(runs_root=runs_root))
    with TestClient(app, base_url=LOCAL_BASE_URL) as running:
        yield running


def _page(client: TestClient, query: str | None, **extra: str) -> str:
    params = {**({} if query is None else {"q": query}), **extra}
    response = client.get(f"/runs/{RUN_ID}/search", params=params)
    assert response.status_code == 200
    return response.text


def _content(page: str) -> str:
    """The page's main region: the nav has a search form too, and no card faces."""
    return page.split('<main id="content"', 1)[1].split("</main>", 1)[0]


def _shown(page: str) -> list[str]:
    """The card faces listed, in order, from a whole page or its main region."""
    return CARD_LINK.findall(_content(page) if '<main id="content"' in page else page)


def _expected(runs_root: Path, query: str) -> list[str]:
    bundle = read_bundle(runs_root / RUN_ID)
    view = reads.search_view(bundle, engine.parse_query(query))
    return [result["card_id"] for result in view["results"]]


# ---------------------------------------------------------------------------
# What is listed
# ---------------------------------------------------------------------------


def test_the_page_lists_what_runs_search_lists_in_its_order(
    client: TestClient, runs_root: Path
) -> None:
    page = _page(client, "curly hair")
    assert _shown(page) == _expected(runs_root, "curly hair")
    assert _shown(page)[0] == "wnt10a_hair_curl"
    assert f"of {len(CARD_IDS)} card(s)</strong> match" in page


def test_partial_matches_are_listed_below_full_ones_under_their_own_heading(
    client: TestClient, runs_root: Path
) -> None:
    """AGENTS.md 0.1A: a card that matches some of the words is ranked, not hidden."""
    page = _content(_page(client, "MTHFR depression"))
    shown = _shown(page)
    assert shown == _expected(runs_root, "MTHFR depression")
    assert set(shown) == {card_id for card_id in CARD_IDS if card_id.startswith("mthfr")}
    every, some = page.index("Matching every word"), page.index("Matching some of the words")
    assert every < some
    assert page.index("mthfr_c677t_depression") < some
    assert all(page.index(card_id) > some for card_id in shown[1:])
    assert "Matched 1 of 2 word(s) in" in page and "Matched 2 of 2 word(s) in" in page


def test_each_hit_says_which_words_it_matched_and_where(client: TestClient) -> None:
    page = _content(_page(client, "curly hair"))
    first = page.split('class="searchmatched', 1)[1].split("</p>", 1)[0]
    assert "Matched 2 of 2 word(s) in" in first
    assert "title (curly, hair)" in first


def test_a_card_with_no_tier_is_found_with_its_status_on_its_face(client: TestClient) -> None:
    page = _content(_page(client, "biological age"))
    assert _shown(page)[0] == "methylation_epigenetic_age"
    assert "Not determinable by this assay" in page


def test_the_grid_s_filters_ride_along_and_do_not_narrow_the_search(
    client: TestClient, runs_root: Path
) -> None:
    page = _page(client, "MTHFR", tier="strong", group="tier")
    assert _shown(page) == _expected(runs_root, "MTHFR")
    assert len(_shown(page)) == 4
    content = _content(page)
    assert '<input type="hidden" name="tier" value="strong">' in content
    assert f'href="/runs/{RUN_ID}?group=tier&amp;tier=strong">Back to the run' in content
    assert "/cards/mthfr_c677t_homocysteine?group=tier&amp;tier=strong" in content


def test_no_match_is_an_answer(client: TestClient) -> None:
    page = _content(_page(client, "zygomorphic"))
    assert _shown(page) == []
    assert "0 of 6 card(s)</strong> match" in page
    assert "No card in this run mentions any of those words" in page


def test_common_words_are_dropped_and_said_to_be(client: TestClient) -> None:
    page = _content(_page(client, "the curl"))
    assert "Common words left out of the search: the." in page


def test_no_query_shows_the_box_and_nothing_else(client: TestClient) -> None:
    for query in (None, "", "   "):
        page = _content(_page(client, query))
        assert 'id="search-query"' in page and 'value=""' in page
        assert _shown(page) == [] and "card(s)</strong> match" not in page
        assert 'role="alert"' not in page


def test_a_searched_query_is_shown_in_the_box_escaped(client: TestClient) -> None:
    page = _page(client, "<b>hair</b>")
    assert "<b>hair</b>" not in page
    assert 'value="&lt;b&gt;hair&lt;/b&gt;"' in page
    assert "<title>Search · " + RUN_ID + "</title>" in page


# ---------------------------------------------------------------------------
# Refused queries (AGENTS.md 1.3)
# ---------------------------------------------------------------------------


def test_a_query_that_reads_as_a_genotype_is_refused_and_not_shown_again(
    client: TestClient,
) -> None:
    page = _page(client, refused_query())
    assert REFUSED_RSID not in page
    content = _content(page)
    assert "The query reads as a genotype, so it was not searched or repeated." in content
    assert 'role="alert"' in content
    assert 'id="search-query" type="search" name="q" autocomplete="off"\n' in content
    assert 'value=""' in content
    assert _shown(page) == [] and "card(s)</strong> match" not in content


def test_the_refusal_is_the_engine_s_own_sentence(client: TestClient) -> None:
    with pytest.raises(engine.GenotypeQueryError) as refused:
        engine.parse_query(refused_query())
    assert str(refused.value) in _page(client, refused_query())
    with pytest.raises(engine.EmptyQueryError) as empty:
        engine.parse_query("?!")
    assert str(empty.value) in _page(client, "?!")


# ---------------------------------------------------------------------------
# The box, and pages with no run
# ---------------------------------------------------------------------------


def test_every_page_of_an_open_run_has_the_box_in_its_nav(client: TestClient) -> None:
    for address in (
        "/",
        f"/runs/{RUN_ID}",
        f"/runs/{RUN_ID}/cards/wnt10a_hair_curl",
        f"/runs/{RUN_ID}/ancestry",
        f"/runs/{RUN_ID}/search",
    ):
        nav = client.get(address).text.split('<nav class="sidenav"', 1)[1].split("</nav>")[0]
        assert f'action="/runs/{RUN_ID}/search"' in nav, address
        assert 'id="nav-search"' in nav, address


def test_a_page_with_no_run_open_has_no_box(client: TestClient, tmp_path: Path) -> None:
    assert 'id="nav-search"' not in client.get("/guide").text
    empty = create_app(WebConfig(runs_root=tmp_path / "runs"))
    with TestClient(empty, base_url=LOCAL_BASE_URL) as other:
        assert 'id="nav-search"' not in other.get("/").text


def test_an_unknown_run_is_a_page_not_a_crash(client: TestClient) -> None:
    response = client.get("/runs/20200101T000000Z-00000000/search", params={"q": "hair"})
    assert response.status_code == 200
    assert "No run named" in response.text
    assert 'id="search-query"' not in response.text


def test_the_matched_line_shares_the_cell_with_the_face(client: TestClient) -> None:
    """In the grid a face fills its cell (``height: 100%``). Here the matched line sits
    under it, and without its own rule overflowed onto the next panel (M14.4 review)."""
    from genetics.web import STATIC_DIR

    page = _content(_page(client, "MTHFR"))
    assert page.count('<li class="searchhit">') == len(_shown(page)) == 4
    css = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
    assert ".searchhit { display: flex; flex-direction: column; }" in css
    assert ".searchhit .card { height: auto; flex: 1 1 auto; }" in css
