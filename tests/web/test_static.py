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
    """The literal rule where it can be applied without arguing about comments.

    This is the check with teeth until ``templates/`` exists: it reads what the app actually
    emitted, so it covers HTML assembled in Python, a URL pasted into an error body, and
    anything a future template interpolates -- none of which a source scan sees reliably.
    The 404 is included because an error page is still a page, and it is the one nobody
    reviews.
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
