"""The accessibility pass (roadmap M14.7): keyboard navigation, contrast, screen-reader labels.

Three kinds of check, each computed rather than eyeballed:

* **Contrast** is worked out from the colour tokens in ``app.css``, for each theme: every
  pair of text and background the stylesheet uses meets WCAG 1.4.3's 4.5:1, and every
  control's edge and the focus ring meet 1.4.11's 3:1.
* **The rendered pages** are parsed and audited by :func:`genetics.testing.accessibility.audit`: one ``h1`` in ``main`` and no skipped
  heading level; ids unique and every ``for``, ``aria-labelledby`` and
  ``aria-describedby`` pointing at one; every control labelled and every link and button
  named; landmarks of one role told apart by name; nothing focusable inside an image or a
  hidden subtree, and no positive ``tabindex``.
* **Keyboard behaviour** that lives in ``app.js`` is held to its markup: a select that acts
  on ``change`` also takes its keys, so an arrow press does not leave the page.

The saved run is the committed pack, less its HLA and guideline cards, matched against an invented table, each card's first
and last declared allele, as in ``tests/web/test_search_page.py``. No export is read.
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
from genetics.engine.cards import CardKind, KnowledgePack, default_knowledge_dir
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import match_pack
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run.bundle import write_bundle
from genetics.run.pipeline import observations
from genetics.testing.accessibility import audit, by_id, contrast, name_of, parse
from genetics.web import WebConfig, create_app
from genetics.web.app import TEMPLATE_DIR
from genetics.web.assets import STATIC_DIR

LOCAL_BASE_URL = "http://127.0.0.1:8765"
RUN_ID = "20261120T120000Z-a11ce5ed"
CSS = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
APP_JS = (STATIC_DIR / "app.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Contrast (WCAG 1.4.3 text, 1.4.11 non-text)
# ---------------------------------------------------------------------------


def _palette(selector: str) -> dict[str, str]:
    start = CSS.index(selector)
    block = CSS[start : CSS.index("}", start)]
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


THEMES = {
    "light": _palette(":root {"),
    "dark (system)": _palette(':root:not([data-theme="light"]) {'),
    "dark (chosen)": _palette(':root[data-theme="dark"] {'),
}

SURFACES = ("bg", "panel", "raised")

TEXT_PAIRS: tuple[tuple[str, str, str], ...] = (
    *(
        (ink, surface, "body text, muted text and links")
        for ink in ("ink", "muted", "accent")
        for surface in SURFACES
    ),
    ("accent-ink", "accent", "a filled button's label"),
    ("warn-ink", "warn-bg", "a notice, warning or caution"),
    ("accent", "warn-bg", "a link inside a notice"),
    ("bad-ink", "bad-bg", "a damaged run's notice"),
    *(
        (f"tier-{tier}-ink", f"tier-{tier}-bg", "a tier badge")
        for tier in ("well-established", "strong", "moderate", "limited", "artifact", "none")
    ),
)
"""Each foreground on each background the stylesheet draws it on, and where."""

EDGE_PAIRS: tuple[tuple[str, str, str], ...] = (
    *(("control-line", surface, "the edge of a box, select or button") for surface in SURFACES),
    *(("focus", surface, "the focus ring") for surface in SURFACES),
)


def test_the_contrast_formula_is_wcag_s() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_text_pair_meets_4_5_to_1(theme: str) -> None:
    palette = THEMES[theme]
    failing = [
        f"{fg} on {bg} ({where}): {contrast(palette[fg], palette[bg]):.2f}"
        for fg, bg, where in TEXT_PAIRS
        if contrast(palette[fg], palette[bg]) < 4.5
    ]
    assert not failing, failing


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_control_edges_and_the_focus_ring_meet_3_to_1(theme: str) -> None:
    palette = THEMES[theme]
    failing = [
        f"{fg} on {bg} ({where}): {contrast(palette[fg], palette[bg]):.2f}"
        for fg, bg, where in EDGE_PAIRS
        if contrast(palette[fg], palette[bg]) < 3
    ]
    assert not failing, failing


def test_the_two_dark_palettes_are_one() -> None:
    """The system-dark and chosen-dark blocks are written twice; a token changed in one and
    not the other is a contrast this test passed in one dark theme only."""
    assert THEMES["dark (system)"] == THEMES["dark (chosen)"]


def _rule(selector: str) -> str:
    """The rule whose selector starts a line: ``.card`` is not ``.searchhit .card``."""
    found = re.search(rf"^{re.escape(selector)} \{{", CSS, flags=re.MULTILINE)
    assert found, selector
    return CSS[found.start() : CSS.index("}", found.start())]


@pytest.mark.parametrize(
    "selector",
    [
        ".runselect select,\n.controls select",
        ".runselect .runopen",
        ".searchrow input",
        ".filterset > summary",
        ':root[data-js="on"] .themetoggle',
        ".modalclose",
    ],
)
def test_controls_are_edged_with_the_control_line(selector: str) -> None:
    """``--line`` is a divider at about 1.3:1. A box drawn with it is a box a low-vision
    reader cannot find (1.4.11)."""
    rule = _rule(selector)
    assert "border: 1px solid var(--control-line)" in rule
    assert "var(--line)" not in rule


def test_the_face_layout_stays_on_card_faces() -> None:
    """The stretched link needs a positioned, padded face; the ClinVar sections and PGx gene
    faces also wear `.card` and must not take that layout (found in the M14.7 review)."""
    card = _rule(".card")
    for declaration in ("position:", "padding:", "display:"):
        assert declaration not in card, declaration
    assert "position: relative;" in _rule(".cardface")
    face = (TEMPLATE_DIR / "_cardface.html").read_text(encoding="utf-8")
    assert ' cardface">' in face
    for name in ("clinvar.html", "_pgxfaces.html"):
        assert "cardface" not in (TEMPLATE_DIR / name).read_text(encoding="utf-8"), name


def test_placeholder_text_is_the_checked_muted_colour() -> None:
    assert "::placeholder { color: var(--muted); opacity: 1; }" in CSS


# ---------------------------------------------------------------------------
# Rendered pages
# ---------------------------------------------------------------------------


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
    root = tmp_path_factory.mktemp("a11y") / "runs"
    # HLA and guideline cards need a saved HLA or PGx record to open, as in
    # tests/test_parity.py; every other card in the pack is here.
    full = KnowledgePack.load(default_knowledge_dir())
    pack = KnowledgePack(
        tuple(c for c in full.cards if c.kind not in {CardKind.HLA, CardKind.GUIDELINE}),
        full.source_dir,
    )
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


def _a_card_url(client: TestClient) -> str:
    found = re.search(r'class="cardlink"\s+href="([^"?]+)', client.get(f"/runs/{RUN_ID}").text)
    assert found
    return found.group(1)


PAGES = (
    "/",
    f"/runs/{RUN_ID}",
    f"/runs/{RUN_ID}?group=tier",
    f"/runs/{RUN_ID}?tier=strong",
    f"/runs/{RUN_ID}/search",
    f"/runs/{RUN_ID}/search?q=hair",
    f"/runs/{RUN_ID}/search?q=%3F%21",
    f"/runs/{RUN_ID}/qc",
    f"/runs/{RUN_ID}/ancestry",
    f"/runs/{RUN_ID}/hla",
    f"/runs/{RUN_ID}/pgx",
    f"/runs/{RUN_ID}/clinvar",
    f"/runs/{RUN_ID}/secondary-findings",
    "/guide",
)


@pytest.mark.parametrize("address", PAGES)
def test_each_page_passes_the_audit(client: TestClient, address: str) -> None:
    response = client.get(address)
    assert response.status_code == 200, address
    assert audit(response.text) == []


def test_every_card_page_and_dialog_passes_the_audit(client: TestClient) -> None:
    """Every card the run holds, as a page and as the dialog htmx swaps in."""
    grid = client.get(f"/runs/{RUN_ID}").text
    urls = sorted(set(re.findall(r'class="cardlink"\s+href="([^"?]+)', grid)))
    assert len(urls) > 100
    for url in urls:
        assert audit(client.get(url).text) == [], url
        fragment = client.get(url, headers={"HX-Request": "true"}).text
        assert 'role="dialog"' in fragment
        assert audit(fragment, page=False) == [], url


def test_the_audit_sees_what_it_claims_to() -> None:
    """Each rule fails on the shape it exists for, so a pass above means something."""
    frame = (
        '<html lang="en"><head><title>t</title></head><body>'
        '<nav aria-label="Sections"></nav><main><h1>x</h1>{}</main></body></html>'
    )
    assert audit(frame.format("")) == []
    cases = {
        "<h3>skipped</h3>": "heading skips from h1 to h3",
        '<p id="a"></p><p id="a"></p>': "duplicate id a",
        '<a href="/" aria-describedby="gone">x</a>': "aria-describedby points at no id: gone",
        '<input name="q">': "unlabelled input q",
        '<svg role="img" aria-label="c"><circle tabindex="0"/></svg>': "focusable circle inside a hidden or image subtree",
        '<a href="/"><span aria-hidden="true">x</span></a>': "a with no name",
        "<nav></nav>": "2 navigation landmarks not told apart by name",
        "</main><header>a</header><header>b</header><main>": "2 banner landmarks not told apart by name",
        '<form role="search" aria-label="s"></form><form role="search" aria-label="s"></form>': "2 search landmarks not told apart by name",
        '<button tabindex="2">b</button>': "positive tabindex on button",
        '<svg role="img"></svg>': "role=img with no name on svg",
        "<table><tr><td>1</td></tr></table>": "table with no caption",
        "<table><caption> </caption><tr><td>1</td></tr></table>": "table with no caption",
    }
    for markup, problem in cases.items():
        assert problem in audit(frame.format(markup)), markup


# ---------------------------------------------------------------------------
# Screen-reader labels on particular controls
# ---------------------------------------------------------------------------


def test_a_card_link_is_named_by_its_title_and_described_by_its_tier(
    client: TestClient,
) -> None:
    """A face that was one link read its whole face as the link's name at every Tab."""
    root = parse(client.get(f"/runs/{RUN_ID}").text)
    ids = by_id(root)
    links = [e for e in root.walk() if e.tag == "a" and e.get("class") == "cardlink"]
    assert len(links) > 100
    for link in links:
        heading = link.parent
        assert heading is not None and heading.get("class") == "cardtitle"
        assert heading.children == [link], "the heading is the link, nothing else"
        face = next(a for a in link.ancestors() if a.tag == "article")
        badges = ids[link.attrs["aria-describedby"]]
        assert face in badges.ancestors()
        assert badges.get("class") == "cardbadges"
        assert len(name_of(link, ids)) < 200


def test_the_search_page_has_one_search_landmark(client: TestClient) -> None:
    for address, expected in (
        (f"/runs/{RUN_ID}", "Search this run's cards"),
        (f"/runs/{RUN_ID}/search", "Search this run's cards"),
    ):
        root = parse(client.get(address).text)
        ids = by_id(root)
        searches = [e for e in root.walk() if e.get("role") == "search"]
        assert len(searches) == 1, address
        assert name_of(searches[0], ids) == expected
    page = client.get(f"/runs/{RUN_ID}/search").text
    nav = page.split('<nav class="sidenav"', 1)[1].split("</nav>")[0]
    assert 'id="nav-search"' in nav, "the box stays; only its landmark moves to the page's"


def test_the_nav_marks_the_page_it_is_on(client: TestClient) -> None:
    for page in ("qc", "ancestry", "hla", "clinvar", "secondary-findings"):
        html = client.get(f"/runs/{RUN_ID}/{page}").text
        current = re.findall(r'<a href="([^"]+)" aria-current="page">', html)
        assert current == [f"/runs/{RUN_ID}/{page}"], page
    assert 'aria-current="page"' not in client.get(f"/runs/{RUN_ID}").text


def test_counts_are_read_as_words_not_as_a_fraction(client: TestClient) -> None:
    root = parse(client.get(f"/runs/{RUN_ID}").text)
    counts = [e for e in root.walk() if e.get("class") in {"section-count", "panelcount"}]
    assert len(counts) >= 26
    for count in counts:
        spoken = count.text()
        assert "/" not in spoken and re.fullmatch(r",? ?\d+ of \d+ card\(s\) interpreted", spoken)


def test_the_theme_toggle_is_named_by_what_it_shows() -> None:
    """``aria-label="Colour theme"`` over a button reading "System" was a name a speech-input
    user could not say, and it hid which theme was on (WCAG 2.5.3)."""
    base = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    button = base[base.index('<button type="button" class="themetoggle"') :]
    button = button[: button.index("</button>")]
    assert "aria-label" not in button.split(">", 1)[0]
    assert '<span class="visually-hidden">Colour theme: </span>' in button
    assert 'class="themelabel" x-text="label">System</span>' in button


def test_the_theme_toggle_says_the_new_theme_when_pressed() -> None:
    """A changed button label is not reliably announced (M14.7's open item), so a polite live
    region beside the button, in the same Alpine component, says it."""
    base = (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")
    component = base[base.index('<span x-data="themetoggle">') :]
    component = component[: component.index("</button>") + 200]
    assert 'x-on:click="cycle"' in component
    assert 'role="status" aria-live="polite" x-text="announcement"></span>' in component
    script = (TEMPLATE_DIR.parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "announcement: ''," in script
    assert "this.announcement = `Colour theme: ${this.label}`;" in script


def test_the_skip_link_lands_on_a_focusable_main(client: TestClient) -> None:
    html = client.get(f"/runs/{RUN_ID}").text
    assert '<a class="skip" href="#content">Skip to content</a>' in html
    assert '<main id="content" class="content" tabindex="-1">' in html


def test_the_guide_s_nav_is_named_for_what_it_holds(client: TestClient) -> None:
    assert '<nav class="sidenav" aria-label="On this page">' in client.get("/guide").text
    assert '<nav class="sidenav" aria-label="Sections">' in client.get(f"/runs/{RUN_ID}").text


def test_the_refusal_shows_its_example_as_code(client: TestClient) -> None:
    html = client.get(f"/runs/{RUN_ID}/search", params={"q": "?!"}).text
    assert "such as <code>curly hair</code>." in html


# ---------------------------------------------------------------------------
# Keyboard navigation
# ---------------------------------------------------------------------------


def test_every_select_that_acts_on_change_takes_its_keys() -> None:
    """An arrow press on a closed select fires ``change``. A select that navigated on it
    sent a keyboard user away at the first arrow (WCAG 3.2.2)."""
    acting = 0
    for template in TEMPLATE_DIR.glob("*.html"):
        source = template.read_text(encoding="utf-8")
        for tag in re.findall(r"<select\b[^>]*>", source):
            if 'x-on:change="' not in tag:
                continue
            acting += 1
            assert 'x-on:keydown="key"' in tag, template.name
            assert 'x-on:pointerdown="pointer"' in tag, template.name
    assert acting == 3


def test_the_keyed_guard_is_in_both_components() -> None:
    assert "function keyedSelect()" in APP_JS
    assert APP_JS.count("...keyedSelect(),") == 2
    for component in ("runselector", "gridcontrols"):
        body = APP_JS[APP_JS.index(f"Alpine.data('{component}'") :]
        body = body[: body.index("}));")]
        assert "if (this.keyed) {" in body, component
        assert "key(event) {" in body and "this.pressed(event)" in body, component


def test_a_run_can_be_opened_without_the_change_event(client: TestClient) -> None:
    html = client.get("/guide").text
    assert (
        'x-on:click="openChosen">Open<span class="visually-hidden"> the chosen run</span>' in html
    )
    assert ".jsonly { display: none; }" in CSS
