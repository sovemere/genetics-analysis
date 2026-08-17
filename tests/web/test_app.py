"""The dashboard skeleton (roadmap M4.3).

Organised by the promise each test defends. M4.3 makes three: it binds to loopback only, it
answers only for this machine, and it makes no external request. The last one has two halves
-- the server process and the page it hands the browser -- and each is checked by its own
mechanism, because the one that catches a stray ``urlopen`` cannot see a ``<script src>``.
"""

from __future__ import annotations

import ast
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from genetics import __version__ as ENGINE_VERSION
from genetics.engine.cards import KnowledgePack
from genetics.qc.report import QCReport
from genetics.run.bundle import BUNDLE_FORMAT_VERSION, write_bundle
from genetics.web import SECURITY_HEADERS, WebConfig, WebConfigError, create_app
from genetics.web.config import DEFAULT_HOST, DEFAULT_PORT

WEB_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "genetics" / "web"

LOCAL_BASE_URL = "http://127.0.0.1:8765"
"""``TestClient`` sends ``Host: testserver`` unless told otherwise, and this app refuses it.

That is the host check doing its job, not a test inconvenience: ``testserver`` is exactly
the shape of a name that is not this machine. Every client here therefore states a base URL,
and one test below drives the default deliberately to prove the refusal is real.
"""


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    config = WebConfig(runs_root=tmp_path / "runs")
    with TestClient(create_app(config), base_url=LOCAL_BASE_URL) as running:
        yield running


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def test_the_default_configuration_is_loopback() -> None:
    config = WebConfig()
    assert config.host == DEFAULT_HOST
    assert config.port == DEFAULT_PORT
    assert config.url == f"http://127.0.0.1:{DEFAULT_PORT}"


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",
        "::",
        "[::]",
        # Every one of these was accepted by the first cut, which compared against a literal
        # set of three spellings. Each binds every interface, so each published an
        # unauthenticated genome dashboard to the local network -- the one failure this
        # module exists to prevent, defeated by writing the same address a different way.
        "::0",
        "0::0",
        "0000::0",
        "0:0:0:0:0:0:0:0",
        "[0.0.0.0]",
        "::ffff:0.0.0.0",
        " 0.0.0.0 ",
    ],
)
def test_the_wildcard_bind_address_is_refused_however_it_is_spelled(host: str) -> None:
    """The one-character change that turns a private tool into a public one.

    ``is_local_address`` treats the wildcard as local -- correctly, since it answers "does
    this leave the machine" about an outbound connection. As a *bind* address it means the
    opposite: every interface, so every machine on the network. The two questions differ
    only here, which is why this is a second check rather than a weakening of the shared
    predicate that M2.7's offline guard also depends on.
    """
    with pytest.raises(WebConfigError, match="wildcard"):
        WebConfig(host=host)


@pytest.mark.parametrize("host", ["192.168.1.10", "0.gg", "example.com", "8.8.8.8", ""])
def test_a_non_loopback_bind_address_is_refused(host: str) -> None:
    """The realistic route to this is not malice, it is a connection refused from a VM."""
    with pytest.raises(WebConfigError, match="refusing to bind"):
        WebConfig(host=host)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "127.0.0.5"])
def test_every_loopback_form_is_accepted(host: str) -> None:
    """Refusing a legitimate loopback form would push someone to the wildcard to get past
    it, which is the failure this whole check exists to prevent."""
    assert WebConfig(host=host).host == host


def test_the_app_answers_for_whatever_address_it_was_told_to_bind(tmp_path: Path) -> None:
    """Found on the self-pass, and it is this module's own docstring coming true about it.

    ``127.0.0.5`` is a legitimate loopback address and the ordinary way to dodge a port
    conflict, so ``WebConfig`` accepts it -- and with a fixed allowlist of the *common*
    loopback names, the server then refused every request to itself, citing DNS rebinding.
    That is exactly the failure this module accuses Starlette's ``TrustedHostMiddleware`` of
    for IPv6, written a second time one file away. The allowlist is derived from the bind
    address now rather than left to a caller who would have to remember.
    """
    config = WebConfig(host="127.0.0.5", port=8765)
    assert "127.0.0.5" in config.allowed_hosts
    with TestClient(create_app(config), base_url="http://127.0.0.5:8765") as client:
        assert client.get("/healthz").status_code == 200


def test_a_bracketed_ipv6_bind_address_produces_one_set_of_brackets(tmp_path: Path) -> None:
    """``[::1]`` is a form ``WebConfig`` accepts, so it is a form ``url`` has to render.

    Wrapping any host containing a colon gave ``http://[[::1]]:8765`` -- a URL that resolves
    to nothing, printed by the command whose whole job is telling the user where to click.
    """
    config = WebConfig(host="[::1]")
    assert config.url == f"http://[::1]:{DEFAULT_PORT}"
    # Stored bare, because the literal string "[::1]" is not an address socket.bind or
    # uvicorn can resolve -- a config that kept what the caller typed would validate here
    # and fail at bind time.
    assert config.host == "::1"
    with TestClient(create_app(config), base_url="http://x") as client:
        assert client.get("/healthz", headers={"host": "[::1]:8765"}).status_code == 200


def test_a_port_outside_the_tcp_range_is_refused() -> None:
    for port in (0, -1, 70000):
        with pytest.raises(WebConfigError, match="usable TCP port"):
            WebConfig(port=port)


def test_an_empty_allowlist_is_a_mistake_rather_than_a_lockdown() -> None:
    with pytest.raises(WebConfigError, match="empty"):
        WebConfig(allowed_hosts=())


def test_the_app_really_listens_on_loopback_and_nowhere_else(tmp_path: Path) -> None:
    """The claim is about a socket, so a socket is what gets asked.

    Every other test here drives the app through ``TestClient``, which never opens one --
    so nothing else in this file could tell a correct bind from a config value that is
    merely carried around and ignored. This starts the real server on an ephemeral port and
    reads the address the kernel actually bound. M2.7's guard permits loopback explicitly
    and names this milestone as the reason.
    """
    # `runs_root` is pinned to tmp_path rather than left to default. Bare `create_app()`
    # walks the *developer's* real GENETICS_DATA_DIR when /healthz is probed below, so the
    # test read whatever genome bundles happened to be saved on the machine running it, and
    # its result depended on them. Caught in review.
    app = create_app(WebConfig(runs_root=tmp_path / "runs"))
    config = uvicorn.Config(app, host=DEFAULT_HOST, port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "the server did not come up"

        bound = [sock.getsockname() for sock in server.servers[0].sockets]
        assert bound, "no listening socket"
        for address in bound:
            host, port = address[0], address[1]
            assert socket.inet_aton(host) == socket.inet_aton("127.0.0.1"), (
                f"listening on {host}, which is reachable from off this machine"
            )
            # Proves the socket is real and serving, not merely open: a bound-but-dead
            # listener would satisfy the assertion above and nothing else.
            with socket.create_connection((host, port), timeout=5) as probe:
                probe.sendall(b"GET /healthz HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
                assert b"200" in probe.recv(64)
    finally:
        server.should_exit = True
        thread.join(timeout=10)


# ---------------------------------------------------------------------------
# Who it answers
# ---------------------------------------------------------------------------


def test_a_request_for_another_hostname_is_refused(client: TestClient) -> None:
    """A loopback bind does not mean only this machine can reach the app.

    A page on the open internet can point a hostname it controls at 127.0.0.1 and have the
    visitor's own browser fetch this app -- the request arrives on loopback and looks
    ordinary. The ``Host`` header is the only place the difference shows, and this app
    serves somebody's genome, so it is worth looking at.
    """
    response = client.get("/healthz", headers={"host": "dns-rebind.example.com"})
    assert response.status_code == 421
    assert response.json()["error"] == "host-not-allowed"


def test_the_default_test_client_host_is_refused(tmp_path: Path) -> None:
    """``TestClient``'s own default is ``testserver``, and refusing it is the point.

    Without this, every other test in the file could pass against an app whose host check
    had been deleted -- they all state a loopback base URL, so none of them would notice.
    """
    with TestClient(create_app(WebConfig(runs_root=tmp_path))) as bare:
        assert bare.get("/healthz").status_code == 421


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "127.0.0.1:8765", "localhost:8765", "[::1]:8765", "LOCALHOST"]
)
def test_every_way_a_local_browser_writes_the_host_header_is_accepted(
    host: str, tmp_path: Path
) -> None:
    """``[::1]:8765`` is the case that breaks the obvious implementation.

    Splitting the header on ``":"`` and taking the first field -- which is what Starlette's
    own ``TrustedHostMiddleware`` does -- turns an IPv6 literal into ``"["``. A user who
    binds to ``::1`` would then be refused by their own server on every request, with a
    message about DNS rebinding.
    """
    with TestClient(create_app(WebConfig(runs_root=tmp_path)), base_url="http://x") as bare:
        assert bare.get("/healthz", headers={"host": host}).status_code == 200


# ---------------------------------------------------------------------------
# No external requests
# ---------------------------------------------------------------------------

NETWORK_CLIENTS = frozenset(
    {
        "urllib",
        "urllib.request",
        "http",
        "http.client",
        "socket",
        "socketserver",
        "ftplib",
        "requests",
        "httpx",
        "httpx2",
        "aiohttp",
        "genetics.refs.fetcher",
    }
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_no_module_under_web_reaches_for_a_network_client() -> None:
    """The server half of "no external requests", made structural rather than intended.

    An intention passes every other test in the suite and surfaces at the M15.1 release
    gate, by which point something is built on top of it. This is M1.3's reasoning about
    vendor adapters -- "the coupling claim is checked structurally" -- applied to a boundary
    where the leaked thing would be a genome rather than a layering violation.
    """
    modules = sorted(WEB_PACKAGE.rglob("*.py"))
    assert modules, "no web modules found; this test would pass vacuously"

    for module in modules:
        offending = _imported_modules(module) & NETWORK_CLIENTS
        assert not offending, f"{module.name} imports {', '.join(sorted(offending))}"


def test_the_app_serves_without_touching_the_network(client: TestClient) -> None:
    """Belt to the structural braces: the routes are driven under M2.7's offline guard.

    That guard is installed for the whole session by ``tests/conftest.py``, so a route that
    called out would raise ``NetworkAccessError`` here rather than returning a page. It
    cannot replace the import check -- it only sees the paths a test happens to exercise --
    but it does cover the case that check cannot: a call reached indirectly, through a
    library this package imports for another reason.
    """
    from genetics.testing.network import guard_is_active

    assert guard_is_active(), "the offline guard is not installed; this would prove nothing"
    for route in ("/", "/healthz"):
        assert client.get(route).status_code == 200


def test_the_interactive_api_docs_are_off_because_they_load_from_a_cdn(
    client: TestClient,
) -> None:
    """FastAPI's default docs pull Swagger UI and ReDoc from a CDN.

    That is an outbound request from the user's browser, to a third party, on a page whose
    subject is that user's genome -- exactly what this milestone promises does not happen,
    arriving through a feature nobody switched on deliberately.
    """
    for route in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(route).status_code == 404, f"{route} is served"


def test_the_page_may_load_nothing_this_server_did_not_serve(client: TestClient) -> None:
    """The browser half. M4.4 adds the static check that no template names an external URL;
    this is the runtime half of the same claim, and the half that still holds when somebody
    adds a ``<script src>`` the static check has not learned about."""
    policy = client.get("/").headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "connect-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy


@pytest.mark.parametrize("route", ["/", "/healthz", "/does-not-exist"])
def test_every_response_carries_the_policy_including_errors(route: str, client: TestClient) -> None:
    """A 404 is still a page a browser renders. An error path that lost the headers is an
    error path that could load anything, and it is the path least likely to be looked at."""
    headers = client.get(route).headers
    for name, value in SECURITY_HEADERS.items():
        assert headers.get(name) == value, f"{route} is missing {name}"


def test_a_route_that_raises_still_carries_the_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one response that escapes the middleware, and the only one this app can cause.

    Starlette's error handling wraps ``@app.middleware("http")`` from the outside, so a route
    that raises never reaches the line attaching these headers -- the 500 went out bare while
    the docstring said "every response, including errors". Driven through a real failure
    (``list_runs`` raising) rather than a route added for the test, because a synthetic route
    would not show that the handler covers the ones that ship.
    """

    def explode(*args: object, **kwargs: object) -> object:
        raise RuntimeError("the disk fell off")

    monkeypatch.setattr("genetics.run.store.list_runs", explode)
    with TestClient(
        create_app(WebConfig(runs_root=tmp_path)),
        base_url=LOCAL_BASE_URL,
        raise_server_exceptions=False,
    ) as client:
        response = client.get("/healthz")

    assert response.status_code == 500
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == value, f"a 500 lost {name}"
    assert "disk fell off" not in response.text, "an exception string must not reach the page"


# ---------------------------------------------------------------------------
# What it reports
# ---------------------------------------------------------------------------


def test_health_counts_runs_with_the_same_function_the_cli_uses(
    tmp_path: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
) -> None:
    """AGENTS.md 3: one engine, two front-ends.

    A second traversal of the runs directory would agree today and diverge later, and it is
    exactly the drift M13.5's parity test exists to catch. So the count comes from
    ``store.list_runs`` -- and the way to prove that is to save a real bundle and see the
    number move.
    """
    runs_root = tmp_path / "runs"
    config = WebConfig(runs_root=runs_root)

    with TestClient(create_app(config), base_url=LOCAL_BASE_URL) as empty:
        assert empty.get("/healthz").json()["run_count"] == 0

    write_bundle(
        qc=sample_qc,
        cards=(),
        pack=sample_pack,
        runs_root=runs_root,
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )

    with TestClient(create_app(config), base_url=LOCAL_BASE_URL) as one:
        payload = one.get("/healthz").json()
    assert payload["run_count"] == 1
    assert payload["runs_root"] == str(runs_root.resolve())
    assert payload["ok"] is True


def test_health_reports_an_unusable_runs_directory_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M0.6's rule, on the surface a person is most likely looking at when they hit it.

    An app that could not be *constructed* with a bad ``GENETICS_DATA_DIR`` could not serve
    the page explaining it either, so the resolution is deferred to request time and the
    failure becomes a report.
    """
    from genetics.paths import repo_root

    monkeypatch.setenv("GENETICS_DATA_DIR", str(repo_root() / "scratch_runs"))
    with TestClient(create_app(), base_url=LOCAL_BASE_URL) as client:
        payload = client.get("/healthz").json()

    assert payload["ok"] is False
    assert payload["detail"] is not None and "inside the repository" in payload["detail"]
    assert payload["run_count"] == 0


def test_health_says_what_it_is(client: TestClient) -> None:
    payload = client.get("/healthz").json()
    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["bundle_format_version"] == BUNDLE_FORMAT_VERSION


def test_the_index_says_it_is_a_placeholder(client: TestClient) -> None:
    """A skeleton nobody can open is a skeleton nobody has run, and every claim above is
    only worth something once a real request has travelled through it."""
    body = client.get("/").text
    assert "M4.5" in body, "the page should say what is missing and where it is coming from"
    assert ENGINE_VERSION in body
