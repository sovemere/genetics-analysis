"""Vendored front-end assets, and the promise that nothing here reaches a CDN (roadmap M4.4).

The milestone is one sentence -- vendor htmx and Alpine, and assert no external URL appears
in any template or static asset -- and writing the assertion honestly takes most of the
thinking, because "no external URL" is not quite the property that matters.

What matters is that **the browser makes no request to a third party** while displaying
somebody's genome. A URL is not a request: Alpine's minified bundle contains
``https://alpinejs.dev/plugins/...`` inside the text of an error it throws when a plugin is
missing, which is a documentation pointer and not a fetch. A test that failed on it would be
a test whose first act is to be wrong about correct code -- and M0.3 recorded what happens
to those. So the scan splits by who wrote the file:

* **What actually reaches a browser** -- the rendered HTML of every route, plus templates
  and first-party files under ``static/`` -- is held to the literal rule. No external host,
  anywhere, for any reason.
* **Everything else under ``web/``**, vendored bundles and this project's Python alike, is
  scanned for the shapes that cause a load: ``src=``, ``href=``, ``url(``, ``@import``,
  ``fetch(``, ``new Worker(`` and friends.

The second rule is narrower on purpose, and the reason is not laziness in either direction.
Alpine's strings are not ours to police, and the controls that do cover them are the sha256
pin in ``vendor.yaml`` -- a byte that changes is a byte somebody re-vendored deliberately --
plus M4.3's Content-Security-Policy, which refuses the request at runtime whatever the file
says. And holding *Python* to the literal rule would mean this very docstring could not
name ``cdn.example.com`` while explaining why naming it is forbidden: a guard whose first
casualty is the comment describing it. The rendered-output scan closes the gap that leaves,
and closes it better than reading the source would, because it sees what was emitted rather
than what was written.

Two mechanisms for one promise, the pattern M4.1 settled on for the bundle destination and
M4.3 repeated for the network.

**M4.6 added the first thing on this page that points outward, and it is worth being exact
about what changed and what did not.** A card's citations are clickable, so the card page
carries ``https://doi.org/...`` in an ``href``. That is not a hole in the property above: an
anchor causes no request until a person clicks it, and clicking is that person deciding to
go and read a paper -- on a published identifier, with no referrer, carrying nothing about
them. The thing M4.4 refuses is a *subresource*: a script, a font, a stylesheet, an image
fetched by the page itself, without the reader knowing, while their genome is on screen.

So the rule is refined rather than relaxed. External hosts are permitted **only** inside an
anchor that is a citation link -- ``class="citelink"``, ``target="_blank"`` and
``rel="noreferrer noopener"`` -- and every other appearance still fails, in every file and
in every rendered response. That is a structural exemption: it does not name hosts (a
``url``-type citation may legitimately point anywhere a card author cited), it names the
one shape that cannot fetch. ``test_the_citation_exemption_is_shaped_not_general`` drives it
with the forms it must still catch, including an ``<a>`` missing its ``rel``, because an
exemption asserted only by the code it was written for is an exemption nobody has tested.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genetics.web import (
    STATIC_DIR,
    VENDOR_DIR,
    VENDOR_MANIFEST,
    WebConfig,
    create_app,
    load_vendor_manifest,
    verify_vendored_assets,
)
from genetics.web.assets import VendorManifestError, digest

WEB_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "genetics" / "web"

#: An absolute or protocol-relative URL. ``//host/path`` is included because it is the
#: form that gets missed: it looks like a comment or a path, and a browser fetches it over
#: whatever scheme the page was served with.
EXTERNAL_URL = re.compile(r"(?:https?:)?//(?P<host>[A-Za-z0-9._~-]+\.[A-Za-z]{2,})")

#: What a *request* looks like, as opposed to a mention. The window is short so that a URL
#: merely appearing later in a long minified line is not attributed to an unrelated
#: attribute forty characters back.
FETCH_SHAPED = re.compile(
    r"""(?:
        src \s* = | srcset \s* = | href \s* = | action \s* = | poster \s* = |
        url \s* \( | @import | fetch \s* \( | importScripts \s* \( |
        new \s+ Worker \s* \( | new \s+ EventSource \s* \( | \.open \s* \(
    )
    [^;{}\n]{0,80}?
    (?:https?:)?//[A-Za-z0-9._~-]+\.[A-Za-z]{2,}
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: Hosts that name this machine. A page referring to one of these is not reaching a third
#: party -- but nothing in this project should be writing absolute self-references either,
#: so this exists to keep the regex honest rather than to permit anything.
LOCAL_HOSTS = frozenset({"127.0.0.1", "0.0.0.0", "localhost"})

#: A citation link, as M4.6 emits it: an anchor that opens a public record in a new tab and
#: sends no referrer. Matched on the whole tag with all three attributes required, in any
#: order, so an anchor that drops ``rel`` -- the attribute that stops the destination
#: learning where the reader came from -- is not exempt.
CITATION_ANCHOR = re.compile(
    r"""<a\s
        (?=[^>]*\bclass="[^"]*\bcitelink\b[^"]*")
        (?=[^>]*\btarget="_blank")
        (?=[^>]*\brel="[^"]*\bnoreferrer\b[^"]*")
        [^>]*>
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _outside_citation_links(html: str) -> str:
    """The document with every well-formed citation anchor removed.

    Only the opening tag is removed, not the link text, so a citation whose *title* happened
    to contain a URL would still be caught -- which is right: a URL in visible text is not
    the exemption, and a card author who pasted one there has written something that should
    be a ``url`` citation instead.
    """
    return CITATION_ANCHOR.sub("", html)


TEXT_SUFFIXES = frozenset({".html", ".htm", ".js", ".css", ".svg", ".json", ".txt", ".jinja"})


def _static_files() -> list[Path]:
    return sorted(p for p in STATIC_DIR.rglob("*") if p.is_file())


def _scannable_text() -> list[Path]:
    """Every text file under ``web/`` worth reading, vendored bundles included.

    ``vendor.yaml`` is the one exclusion, and it is exempt by construction rather than by
    convenience: recording where each asset was downloaded from is its entire job, so it is
    the only file in the project whose contents are supposed to be external URLs.
    """
    return sorted(
        path
        for path in WEB_PACKAGE.rglob("*")
        if path.is_file()
        and (path.suffix in TEXT_SUFFIXES or path.suffix == ".py")
        and path != VENDOR_MANIFEST
        and "__pycache__" not in path.parts
    )


def _authored_for_the_browser() -> list[Path]:
    """Templates and first-party static files -- what a browser is handed, minus vendored.

    Thin today: ``templates/`` arrives with M4.5 and ``static/`` currently holds only
    vendored code and its licences. It is written to grow rather than to be rewritten, so
    the first template is covered the moment it exists rather than the moment somebody
    remembers.
    """
    vendored = {asset.path for asset in load_vendor_manifest()}
    roots = [STATIC_DIR, WEB_PACKAGE / "templates"]
    return sorted(
        path
        for root in roots
        if root.is_dir()
        for path in root.rglob("*")
        if path.is_file() and path.suffix in TEXT_SUFFIXES and path not in vendored
    )


def _external_hosts(text: str) -> set[str]:
    return {
        match.group("host")
        for match in EXTERNAL_URL.finditer(text)
        if match.group("host") not in LOCAL_HOSTS
    }


# ---------------------------------------------------------------------------
# The M4.4 assertion
# ---------------------------------------------------------------------------


def test_no_template_or_first_party_asset_names_an_external_host() -> None:
    """The literal rule, on the files handed to a browser that this project writes.

    A URL in a comment here is not a request today and is the draft of the ``src=`` somebody
    adds next month, so it fails now rather than once it costs something. Thin while
    ``templates/`` does not exist -- which is why the rendered-output test below carries the
    weight today, and why this one is written to pick up M4.5's templates without being
    touched.
    """
    offenders = {
        path.name: sorted(hosts)
        for path in _authored_for_the_browser()
        if (hosts := _external_hosts(path.read_text(encoding="utf-8", errors="replace")))
    }
    assert not offenders, f"external hosts in first-party browser files: {offenders}"


def test_nothing_under_web_can_cause_a_request_to_a_third_party() -> None:
    """The rule that matters, over everything -- vendored bundles and our own Python.

    Scanned for the shapes that *fetch* rather than for any occurrence of a URL, because
    Alpine's error text points at its own documentation and failing on that would be a guard
    that is wrong about correct code on its first day.
    """
    files = _scannable_text()
    assert files, "nothing was scanned; this test would pass vacuously"
    assert any(path.parent == VENDOR_DIR for path in files), "the vendored bundles were skipped"

    offenders = {
        path.relative_to(WEB_PACKAGE).as_posix(): match.group(0)[:90]
        for path in files
        if (match := FETCH_SHAPED.search(path.read_text(encoding="utf-8", errors="replace")))
    }
    assert not offenders, f"would fetch from a third party: {offenders}"


def test_the_scanner_recognises_the_forms_it_claims_to() -> None:
    """A negative assertion passes when it is broken, and this one guards two files that
    happen to be clean. So the patterns are driven with the things they must catch.

    ``//cdn.example.com`` is in the list because the protocol-relative form is the one that
    gets missed -- it reads as a comment or a path, and a browser fetches it anyway.
    """
    must_catch = [
        '<script src="https://cdn.example.com/htmx.js"></script>',
        "<script src='//cdn.example.com/htmx.js'></script>",
        '<link href="https://fonts.googleapis.com/css2?family=X" rel="stylesheet">',
        "@import url(https://fonts.gstatic.com/s/x.css);",
        "background: url('//images.example.net/bg.png')",
        'fetch("https://telemetry.example.org/collect")',
        'new Worker("https://cdn.example.com/w.js")',
    ]
    for snippet in must_catch:
        assert FETCH_SHAPED.search(snippet), f"fetch-shaped reference not caught: {snippet}"
        assert _external_hosts(snippet), f"external host not caught: {snippet}"

    must_not_catch = [
        '<script src="/static/vendor/htmx.min.js"></script>',
        '<a href="/healthz">health</a>',
        "url('data:image/svg+xml;base64,AAAA')",
        # The Alpine case, reduced: a documentation pointer inside thrown error text.
        "throw new Error(`Alpine plugin missing: https://alpinejs.dev/plugins/${name}`)",
    ]
    for snippet in must_not_catch:
        assert not FETCH_SHAPED.search(snippet), f"false positive: {snippet}"


def test_the_real_alpine_bundle_is_the_case_that_shaped_this_test() -> None:
    """Recorded so the reasoning is not rediscovered as a bug.

    Alpine genuinely contains an external URL and genuinely fetches nothing. Both halves are
    asserted, because if a future version stops mentioning the URL this test starts passing
    for the wrong reason and the distinction it exists to document goes quiet.
    """
    alpine = (VENDOR_DIR / "alpine.min.js").read_text(encoding="utf-8", errors="replace")
    assert "alpinejs.dev" in alpine, "the documentation pointer is gone; re-check the split"
    assert not FETCH_SHAPED.search(alpine)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_every_vendored_asset_matches_its_pin() -> None:
    """The offline half of the pinning story.

    Re-downloading to compare would need the network on every commit; the question that
    matters day to day -- has one of these been edited, truncated or swapped -- is
    answerable from the checkout alone.
    """
    assert list(verify_vendored_assets()) == []


def test_a_tampered_asset_is_caught(tmp_path: Path) -> None:
    """Driving the check with input it must reject, since the assertion above is negative.

    A copy is used rather than the real tree: a test that edited the committed bundle and
    relied on restoring it would leave a corrupted asset behind the first time it failed
    partway through.
    """
    import shutil

    import yaml

    shutil.copytree(VENDOR_DIR, tmp_path / "vendor")
    manifest = yaml.safe_load(VENDOR_MANIFEST.read_text(encoding="utf-8"))
    (tmp_path / "vendor" / "htmx.min.js").write_text("/* swapped */", encoding="utf-8")

    edited = tmp_path / "vendor.yaml"
    edited.write_text(yaml.safe_dump(manifest), encoding="utf-8")

    from genetics.web import assets as assets_module

    original = assets_module.VENDOR_DIR
    try:
        assets_module.VENDOR_DIR = tmp_path / "vendor"  # type: ignore[misc]
        problems = list(assets_module.verify_vendored_assets(edited))
    finally:
        assets_module.VENDOR_DIR = original  # type: ignore[misc]

    assert any("does not match its pin" in problem for problem in problems)


def test_every_vendored_asset_ships_its_licence() -> None:
    """MIT and BSD both require the notice to travel with the code.

    Alpine's npm package does not contain one -- ``@alpinejs/csp`` ships dist, src, builds
    and package.json and no LICENSE -- so it was fetched from the matching git tag. That is
    a real obligation, not paperwork: distributing the bundle without it is a licence
    violation, and this repository is public.
    """
    for asset in load_vendor_manifest():
        assert asset.license_path.is_file(), f"{asset.id} ships no licence text"
        text = asset.license_path.read_text(encoding="utf-8")
        assert len(text.strip()) > 100, f"{asset.id} licence text looks truncated"
    assert {asset.license for asset in load_vendor_manifest()} == {"0BSD", "MIT"}


def test_a_manifest_missing_a_field_is_refused(tmp_path: Path) -> None:
    """Every field is mandatory: an asset with no digest is one nothing verifies, and one
    with no licence is one the M15.4 audit cannot clear."""
    import yaml

    manifest = yaml.safe_load(VENDOR_MANIFEST.read_text(encoding="utf-8"))
    del manifest["assets"][0]["sha256"]
    broken = tmp_path / "vendor.yaml"
    broken.write_text(yaml.safe_dump(manifest), encoding="utf-8")

    with pytest.raises(VendorManifestError, match="sha256"):
        load_vendor_manifest(broken)


def test_the_served_tree_contains_no_python() -> None:
    """Everything under ``static/`` is fetchable, so nothing there should be source.

    An ``__init__.py`` in the served directory would publish this project's code, and its
    ``__pycache__`` the compiled form, from the one place whose entire contents are handed
    to a browser. Nothing there is secret, which is exactly why it would not have been
    noticed.
    """
    stray = [p.relative_to(STATIC_DIR).as_posix() for p in _static_files() if p.suffix == ".py"]
    assert not stray, f"Python served from the static tree: {stray}"
    assert not (STATIC_DIR / "__pycache__").exists()


def test_the_vendor_manifest_is_not_itself_served() -> None:
    """It is the one file whose job is to hold external URLs."""
    assert VENDOR_MANIFEST.is_file()
    assert STATIC_DIR not in VENDOR_MANIFEST.parents


# ---------------------------------------------------------------------------
# Actually served
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path):  # type: ignore[no-untyped-def]
    with TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1:8765"
    ) as running:
        yield running


def test_each_vendored_asset_is_served_byte_for_byte(client: TestClient) -> None:
    """Vendoring is worth nothing if the mount does not reach the files.

    Compared by digest rather than by status code, because a 200 carrying the wrong bytes --
    a directory listing, an error page, a truncated read -- is the failure a status check
    cannot see.
    """
    import hashlib

    for asset in load_vendor_manifest():
        response = client.get(f"/static/vendor/{asset.filename}")
        assert response.status_code == 200, asset.filename
        assert hashlib.sha256(response.content).hexdigest() == asset.sha256
        assert digest(asset.path) == asset.sha256


def test_the_page_loads_the_vendored_copies_and_not_a_cdn(client: TestClient) -> None:
    body = client.get("/").text
    assert "/static/vendor/htmx.min.js" in body
    assert "/static/vendor/alpine.min.js" in body
    assert not _external_hosts(body), "the page names an external host"


@pytest.mark.parametrize("route", ["/", "/healthz", "/does-not-exist"])
def test_no_rendered_response_names_an_external_host(route: str, client: TestClient) -> None:
    """The literal rule, on every response that has no business naming anywhere else.

    It reads what the app actually emitted, so it covers HTML assembled in Python, a URL
    pasted into an error body, and anything a template interpolates -- none of which a
    source scan sees reliably. The 404 is included because an error page is still a page,
    and it is the one nobody reviews.

    **The dashboard is on this list and stays on it.** Card faces render here and citations
    do not: a citation is detail-view content, so ``/`` is held to the unrefined rule and a
    change that put a resolver URL on the grid would fail here rather than passing under
    M4.6's exemption by association.
    """
    response = client.get(route)
    assert not _external_hosts(response.text), (
        f"{route} names an external host: {sorted(_external_hosts(response.text))}"
    )


def test_htmx_eval_is_turned_off_through_a_meta_tag(client: TestClient) -> None:
    """Two decisions in one line, and both are forced by the policy.

    ``htmx.config.allowEval = false`` because htmx's two eval-backed features would trip the
    CSP silently; a *meta tag* rather than an inline script because ``script-src 'self'``
    blocks inline scripts -- so configuring htmx the ordinary way would have been the first
    thing on the page to violate the policy the page advertises.
    """
    body = client.get("/").text
    assert 'name="htmx-config"' in body
    assert '"allowEval":false' in body
    assert "<script>" not in body, "an inline script would be blocked by script-src 'self'"


def test_the_static_mount_is_covered_by_the_host_check(client: TestClient) -> None:
    """The mount is the part of an app easiest to forget when reasoning about middleware.

    If it sat outside the ``Host`` check, the DNS-rebinding hole M4.3 closed would be open
    again for every asset -- and an attacker's page can read a script's contents.
    """
    response = client.get("/static/vendor/htmx.min.js", headers={"host": "dns-rebind.example.com"})
    assert response.status_code == 421


def test_static_responses_carry_the_security_headers(client: TestClient) -> None:
    from genetics.web import SECURITY_HEADERS

    headers = client.get("/static/vendor/htmx.min.js").headers
    for name, value in SECURITY_HEADERS.items():
        assert headers.get(name) == value, f"a static response is missing {name}"


def test_a_missing_static_path_is_a_404_not_a_traversal(client: TestClient) -> None:
    assert client.get("/static/vendor/nope.js").status_code == 404
    for attempt in ("/static/../vendor.yaml", "/static/vendor/../../vendor.yaml"):
        assert client.get(attempt).status_code in (404, 400), attempt


# ---------------------------------------------------------------------------
# The citation exemption (roadmap M4.6)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def card_page(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str]:
    """A real card page and its fragment, from a real run of the real pipeline.

    Built rather than stubbed because the thing under test is what the app *emitted*, and a
    hand-written string would be this test asserting against its own fixture. Session-scoped
    since the pipeline runs once and both halves are read-only.
    """
    from dataclasses import replace

    from genetics.run.pipeline import analyse, save
    from genetics.testing.fixtures import FIXTURES, render_fixture

    root = tmp_path_factory.mktemp("citations")
    runs = root / "runs"
    runs.mkdir()
    spike_ins = {"rs900000001": (7, 12345678, "A", "G")}
    base = next(spec for spec in FIXTURES if spec.name == "ancestry_v2_male.txt")
    export = root / "spiked.txt"
    export.write_text(
        render_fixture(replace(base, spike_ins=spike_ins)), encoding="utf-8", newline="\n"
    )
    cards = Path(__file__).parents[1] / "fixtures" / "cards"
    saved = save(analyse(export, knowledge_dir=cards), runs_root=runs)

    url = f"/runs/{saved.name}/cards/synthetic_dominant_trait"
    with TestClient(
        create_app(WebConfig(runs_root=runs)), base_url="http://127.0.0.1:8765"
    ) as running:
        page = running.get(url)
        fragment = running.get(url, headers={"HX-Request": "true"})
    assert page.status_code == 200 and fragment.status_code == 200
    return page.text, fragment.text


def test_the_card_page_names_an_external_host_only_inside_a_citation_link(
    card_page: tuple[str, str],
) -> None:
    """The refined rule, on both representations of the card URL.

    Asserted in both directions on purpose. Finding a citation host proves the page really
    does link out, so this cannot pass by rendering nothing -- which is exactly how the
    negative half would have gone quiet if a template edit dropped the citations block.
    """
    for name, html in zip(("page", "fragment"), card_page, strict=True):
        assert "doi.org" in html, f"the {name} links no citation; the check below is vacuous"
        leftover = _external_hosts(_outside_citation_links(html))
        assert not leftover, f"the card {name} names {sorted(leftover)} outside a citation link"


def test_a_citation_link_cannot_cause_a_load(card_page: tuple[str, str]) -> None:
    """The property the exemption rests on: an anchor fetches nothing until somebody clicks.

    ``FETCH_SHAPED`` matches ``href=`` followed by an external host, so it fires on a
    citation anchor by design -- that pattern exists to catch a ``<link href>``, which is a
    stylesheet and does load. The distinction is the element, so it is drawn here rather
    than by loosening the pattern, which would have stopped catching stylesheets.
    """
    for html in card_page:
        outside = _outside_citation_links(html)
        assert not FETCH_SHAPED.search(outside), "something outside a citation link would fetch"
        for tag in ("<link", "<script", "<img", "<iframe", "<source"):
            for match in re.finditer(re.escape(tag) + r"[^>]*>", outside, re.IGNORECASE):
                assert not _external_hosts(match.group(0)), (
                    f"a loading element points at a third party: {match.group(0)[:120]}"
                )


def test_every_citation_link_sends_no_referrer_and_opens_a_new_tab(
    card_page: tuple[str, str],
) -> None:
    """Every anchor to a third party is a *complete* citation link, not merely most of them.

    ``_outside_citation_links`` strips the well-formed ones, so a half-formed anchor already
    fails the test above -- but it fails saying "names an external host", which sends the
    next reader looking for a CDN reference that is not there. This one names the actual
    defect, and it is the attribute a reviewer is most likely to drop while tidying markup.
    """
    for html in card_page:
        anchors = re.findall(r"<a\s[^>]*>", html, re.IGNORECASE)
        outbound = [tag for tag in anchors if _external_hosts(tag)]
        assert outbound, "no outbound anchor found; this test would pass vacuously"
        for tag in outbound:
            assert CITATION_ANCHOR.fullmatch(tag.strip()), (
                f"outbound anchor is not a citelink: {tag}"
            )
            assert "noopener" in tag, f"a new-tab link without noopener: {tag}"


def test_the_citation_exemption_is_shaped_not_general() -> None:
    """Driven with what it must still catch, because it is an exemption.

    The four rejections are the ways this could quietly become "external URLs are fine on
    the card page": a subresource pointing at a resolver host, an anchor that dropped the
    attribute keeping the reader's origin private, an anchor missing the class that says
    what it is, and one that navigates in place rather than opening a tab. None of them is
    hypothetical -- each is one attribute away from the markup that is there now.
    """
    exempt = (
        '<a href="https://doi.org/10.1038/ng1733" target="_blank" '
        'rel="noreferrer noopener" class="citelink">A paper</a>'
    )
    assert not _external_hosts(_outside_citation_links(exempt))

    must_still_fail = [
        # A subresource. The host being a citation resolver changes nothing: this loads.
        '<script src="https://doi.org/evil.js"></script>',
        '<img src="https://pubmed.ncbi.nlm.nih.gov/pixel.gif">',
        # An anchor with no `rel`: the destination learns which page the reader came from.
        '<a href="https://doi.org/10.1038/ng1733" target="_blank" class="citelink">A paper</a>',
        # An anchor that is not marked as a citation at all.
        '<a href="https://example.com/x" target="_blank" rel="noreferrer noopener">Elsewhere</a>',
        # Navigating in place rather than opening a tab, which takes the genome page with it.
        '<a href="https://doi.org/10.1038/ng1733" rel="noreferrer noopener" class="citelink">A</a>',
    ]
    for snippet in must_still_fail:
        assert _external_hosts(_outside_citation_links(snippet)), f"exempted wrongly: {snippet}"


def test_no_template_authors_a_citation_url() -> None:
    """The addresses are built in Python from a validated identifier, never written in markup.

    ``test_no_template_or_first_party_asset_names_an_external_host`` already fails on a host
    in a template, so this is the same fact stated where somebody adding a "helpful" direct
    link would read it. It is here because the two tests would otherwise look redundant and
    one of them would get deleted.
    """
    from genetics.engine.citations import citation_url

    assert citation_url("doi", "10.1038/ng1733") == "https://doi.org/10.1038/ng1733"
    offenders = [
        path.name
        for path in _authored_for_the_browser()
        if "doi.org" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, f"a template writes a resolver URL itself: {offenders}"


# ---------------------------------------------------------------------------
# The Alpine CSP build's one trap (roadmap M4.4, enforced from M4.6)
# ---------------------------------------------------------------------------

#: An Alpine directive that carries an expression: `x-on:click="..."`, `x-text="..."`,
#: `x-show="..."`. `x-data` is excluded by the pattern because its value is a component
#: *name*, which is the one place a bare identifier is the whole point.
ALPINE_EXPRESSION = re.compile(
    r"""\b(?P<directive>x-(?:on:[\w.:-]+|bind:[\w.:-]+|text|html|show|if|model|init))
        \s*=\s*"(?P<expression>[^"]*)"
    """,
    re.VERBOSE,
)

#: What the CSP build can evaluate and this project chooses to write: a bare name, or a
#: dotted path of bare names. Anything with an operator, a call, a literal or an assignment
#: is refused here rather than being discovered as a control that does nothing.
BARE_REFERENCE = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")


def _templates() -> list[Path]:
    return sorted((WEB_PACKAGE / "templates").rglob("*.html"))


def test_no_template_writes_an_alpine_expression_the_csp_build_cannot_evaluate() -> None:
    """The trap M4.4 chose the CSP build knowing about, made into a check at M4.6.

    ``x-on:click="open = !open"`` is **silently inert** under this build: no console error,
    no CSP violation report, just a control that does nothing. That is the worst failure
    shape there is, and it is one keystroke away from every directive in these templates --
    so the check is on the markup rather than on somebody remembering the vendor manifest.

    Registered component names are checked separately below; this is about the value.
    """
    offenders: dict[str, list[str]] = {}
    for path in _templates():
        for match in ALPINE_EXPRESSION.finditer(path.read_text(encoding="utf-8")):
            expression = match.group("expression").strip()
            if not BARE_REFERENCE.fullmatch(expression):
                offenders.setdefault(path.name, []).append(
                    f'{match.group("directive")}="{expression}"'
                )
    assert not offenders, (
        "these would be silently inert under the Alpine CSP build; move the logic into an "
        f"Alpine.data() component in app.js and reference it by name: {offenders}"
    )


def test_every_alpine_component_a_template_names_is_registered() -> None:
    """An ``x-data="typo"`` is the same silence one level up: Alpine finds no component,
    the element gets an empty scope, and every directive inside it resolves to undefined."""
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    registered = set(re.findall(r"Alpine\.data\(\s*'([^']+)'", app_js))
    assert registered, "no components found in app.js; this check would pass vacuously"

    used: dict[str, str] = {}
    for path in _templates():
        for name in re.findall(r'\bx-data="([^"]*)"', path.read_text(encoding="utf-8")):
            used[name.strip()] = path.name

    missing = {name: where for name, where in used.items() if name not in registered}
    assert not missing, f"x-data names no registered component: {missing}"


def test_every_method_a_template_calls_exists_on_its_component() -> None:
    """The half the two checks above leave open: a *well-formed* bare reference to a method
    nobody wrote. ``x-on:click="dismiss"`` beside a component whose method is ``close`` is a
    button that looks right, parses right, and does nothing.

    Matched loosely -- the name must appear somewhere in app.js -- rather than by parsing
    JavaScript, because the alternative is a JS parser in a Python suite. Loose is enough:
    the failure this catches is a renamed or misspelled method, and neither survives "does
    this identifier occur in the file at all".
    """
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    unknown: dict[str, list[str]] = {}
    for path in _templates():
        for match in ALPINE_EXPRESSION.finditer(path.read_text(encoding="utf-8")):
            root = match.group("expression").strip().split(".")[0]
            if root and not re.search(rf"\b{re.escape(root)}\b", app_js):
                unknown.setdefault(path.name, []).append(match.group(0))
    assert not unknown, f"template references nothing app.js defines: {unknown}"


def test_the_directive_scanner_recognises_what_it_claims_to() -> None:
    """A negative assertion passes when it is broken, and all three above are negative."""
    must_reject = [
        '<button x-on:click="open = !open">',
        '<span x-text="count + 1">',
        '<div x-show="items.length > 0">',
        "<button x-on:click=\"$dispatch('close')\">",
        "<p x-text=\"'literal'\">",
    ]
    for snippet in must_reject:
        match = ALPINE_EXPRESSION.search(snippet)
        assert match, f"the directive itself was not found: {snippet}"
        assert not BARE_REFERENCE.fullmatch(match.group("expression").strip()), snippet

    must_accept = ['<button x-on:click="cycle">', '<span x-text="label">', '<a x-on:click="close">']
    for snippet in must_accept:
        match = ALPINE_EXPRESSION.search(snippet)
        assert match and BARE_REFERENCE.fullmatch(match.group("expression").strip()), snippet


def test_the_dialogs_aria_modal_claim_is_backed_by_something() -> None:
    """``aria-modal="true"`` tells a screen reader that everything outside the dialog is
    unavailable. Nothing was making that true — a keyboard user could tab straight out into
    the grid behind it — so the announcement was markup asserting something the page does
    not do, the same defect class as a card explaining an absence it has not established.

    The two halves cannot be executed here, so they are pinned to each other instead: the
    fragment may claim to be modal only while app.js still has the mechanism that makes it
    one. Removing either fails, which is the point — they are only correct together.
    """
    fragment = (WEB_PACKAGE / "templates" / "_carddialog.html").read_text(encoding="utf-8")
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    if 'aria-modal="true"' not in fragment:
        return  # the claim was dropped; nothing to back.

    # Matched on the *calls*, not on the word. The first cut asserted `"inert" in app_js`
    # and passed with the mechanism replaced by `data-x`, because the word survives in the
    # comment explaining it — a guard whose first casualty is its own documentation, and
    # fail-open besides.
    assert "setAttribute('inert'" in app_js, "the dialog claims to be modal; nothing sets inert"
    assert "removeAttribute('inert'" in app_js, "inert is applied and never lifted"
    assert app_js.count("setBackgroundInert") >= 3, "it must be called on open and on close"
