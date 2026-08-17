"""The FastAPI application (roadmap M4.3).

A skeleton on purpose: M4.4 vendors htmx and Alpine, M4.5 builds the dashboard shell, M4.6
the cards, and M4.9 the ``genetics serve`` command that runs this. What lands here is the
part every one of those depends on and none of them should re-decide -- how the app is
constructed, what it refuses, and what it promises about the network.

**"No external requests" is enforced in two places, because it has two halves.** The server
process must not call out, and neither must the page it hands the browser. The second half
is the one that gets missed: a template referencing a CDN produces an outbound request from
the *user's* machine to a third party, on a page whose contents are that user's genome, and
nothing in this process would ever see it happen.

* Server side, the guarantee is structural. ``tests/web/test_app.py`` parses the imports of
  every module under ``genetics/web/`` and fails if any of them reaches a network client --
  urllib, http.client, socket, requests, httpx, or the project's own fetcher. Intention
  alone would pass every other test in the suite (M1.3's reasoning about vendor adapters,
  applied to a boundary where the consequence is worse).
* Browser side, the guarantee is a ``Content-Security-Policy`` of ``default-src 'self'``.
  M4.4 will add a static check that no external URL appears in a template; this is the
  runtime half of the same claim, and it is the half that still holds when somebody adds a
  ``<script src="https://...">`` that the static check has not learned about yet. Two
  independent mechanisms for one promise, which is the pattern M4.1 settled on for the
  bundle destination.

**Nothing here re-implements an analysis.** AGENTS.md 3 makes that non-negotiable -- one
engine, two front-ends -- so the health endpoint counts runs by calling
:func:`genetics.run.store.list_runs`, the same function ``genetics runs list`` calls. A
second traversal of the runs directory that happened to agree today is a second answer that
disagrees later, and M13.5's parity test exists because that is the requirement most likely
to rot quietly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from genetics import __version__ as ENGINE_VERSION
from genetics.paths import UnsafeDataDirError
from genetics.run import store
from genetics.run.bundle import BUNDLE_FORMAT_VERSION
from genetics.web.assets import STATIC_DIR
from genetics.web.config import WebConfig

SECURITY_HEADERS: dict[str, str] = {
    # The browser half of "no external requests". `default-src 'self'` means the page may
    # load nothing this server did not serve: no CDN script, no remote font, no tracking
    # pixel, no `fetch` to another origin. It is deliberately strict now, while there is
    # nothing to break, rather than relaxed later under pressure from one asset -- which is
    # the direction these policies always travel.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    # No other page may frame this one. `frame-ancestors 'none'` above says the same thing
    # to a modern browser; this is here for the ones that only understand the old header.
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    # A card's URL will name a variant, and a variant plus a person is the genotype
    # (AGENTS.md 1.3). `no-referrer` keeps that out of any request the page can cause --
    # which, under the CSP above, should be none, so this is the belt to that braces.
    "Referrer-Policy": "no-referrer",
    # A run bundle is DNA. Nothing should be caching it anywhere but this process.
    "Cache-Control": "no-store",
}
"""Sent on every response, including errors.

On *every* response is the part that needs saying: a 404 or a 500 is still a page a browser
renders, and an error page that lost the policy is an error page that could load anything.
"""

_ALLOWED_HOSTS_KEY = "genetics_allowed_hosts"


def _host_name(raw: str) -> str:
    """The host part of a ``Host`` header, port removed, IPv6 brackets kept.

    Splitting on ``":"`` is the obvious implementation and it mangles every IPv6 literal:
    ``[::1]:8765`` becomes ``[``. So the bracketed form is handled first, which is exactly
    the case a loopback-only app is most likely to meet.
    """
    value = raw.strip()
    if value.startswith("["):
        end = value.find("]")
        if end != -1:
            return value[: end + 1]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def create_app(config: WebConfig | None = None) -> FastAPI:
    """Build the dashboard application.

    A factory rather than a module-level ``app``. Two reasons: a module-level instance is
    constructed at import time, so a test cannot give it a different runs root without
    reaching into globals; and it would run this app's configuration checks during
    ``genetics --help``, which is how a CLI ends up failing to print its own usage because
    of a setting no command was about to use.
    """
    settings = config or WebConfig()

    app = FastAPI(
        title="genetics",
        version=ENGINE_VERSION,
        description="Local, offline dashboard for one person's genome. Never leaves the machine.",
        # The interactive docs are Swagger UI and ReDoc, and both load their assets from a
        # CDN by default -- an outbound request from the user's browser, on this app, which
        # is precisely what M4.3 promises does not happen. They are off rather than
        # reconfigured: the API here is small and the CLI is the documented agent interface
        # (AGENTS.md 3), so there is nothing to trade for the exception.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = settings

    # Mounted before the middleware is declared for readability only -- Starlette applies
    # middleware around the whole app, mounts included, so the policy headers and the host
    # check cover every asset served here exactly as they cover the routes below. A static
    # mount that escaped the host check would be the DNS-rebinding hole reopened for the
    # one part of the app that is easiest to forget about.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def _local_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Refuse a request whose ``Host`` header is not this machine.

        A loopback bind stops another machine *routing* to this app; it does not stop a page
        on the open internet pointing a hostname it owns at 127.0.0.1 and having the
        visitor's own browser fetch it. That request arrives on loopback and looks entirely
        ordinary -- except for the ``Host`` header, which still carries the attacker's
        domain. This is the only place that difference is visible.
        """
        allowed: tuple[str, ...] = request.app.state.config.allowed_hosts
        host = _host_name(request.headers.get("host", ""))
        if host.lower() not in {name.lower() for name in allowed}:
            return JSONResponse(
                status_code=421,
                content={
                    "error": "host-not-allowed",
                    "detail": (
                        f"This server answers only for {', '.join(allowed)}. A request "
                        f"arrived for {host!r}, which means something other than a browser "
                        "on this machine pointed a name it controls at this address."
                    ),
                },
                headers=SECURITY_HEADERS,
            )
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Keep the policy on the one response that escapes the middleware.

        Starlette's error handling sits *outside* ``@app.middleware("http")``, so a route
        that raises never reaches the line that attaches these headers -- the 500 goes out
        bare. That made "sent on every response, including errors" true of every error the
        framework produces and false of the only one this app's own code can cause. The
        message says nothing about what failed: an exception string here is unbounded text
        from inside a process holding a genome (AGENTS.md 1.3), and the traceback is already
        on the operator's console where it belongs.
        """
        return JSONResponse(
            status_code=500,
            content={"error": "internal-error", "detail": "See the server console."},
            headers=SECURITY_HEADERS,
        )

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """What this process is, and whether it can see the saved runs.

        Reports rather than fails, including when the runs directory is unusable -- the
        state a person is most likely to be in when they load this. That is M0.6's rule for
        ``doctor``, and the same reason M4.2's listing turns damage into a row.

        **Declared ``def``, not ``async def``, and that is load-bearing.** ``list_runs`` is a
        synchronous filesystem walk -- and after M8 it sizes staging directories holding
        gigabytes -- so inside a coroutine it would block the event loop for its whole
        duration, stalling every other request on a single-worker local server. FastAPI runs
        a plain ``def`` endpoint in a threadpool, which is exactly the right behaviour and
        costs one keyword.
        """
        payload: dict[str, Any] = {
            "ok": True,
            "engine_version": ENGINE_VERSION,
            "bundle_format_version": BUNDLE_FORMAT_VERSION,
            "runs_root": None,
            "run_count": 0,
            "detail": None,
        }
        try:
            # The same call `genetics runs list` makes. A second traversal here would be a
            # second answer to one question (AGENTS.md 3: one engine, two front-ends).
            listing = store.list_runs(app.state.config.runs_root)
        except (UnsafeDataDirError, OSError) as exc:
            # OSError as well, because `iterdir` on an unreadable runs root raises it and
            # this endpoint's whole job is to report that the store is unusable. Catching
            # only the configured-wrong case turned the disk-wrong case into a 500 -- from
            # the one route someone loads to find out what is wrong.
            payload["ok"] = False
            payload["detail"] = str(exc)
        else:
            payload["runs_root"] = str(listing.root)
            payload["run_count"] = len(listing.runs)
            notes = []
            if listing.damaged:
                notes.append(
                    f"{len(listing.damaged)} of {len(listing.runs)} saved run(s) could not "
                    "be read. `genetics runs list` explains each one."
                )
            if listing.needs_a_newer_engine:
                # Kept out of the sentence above on purpose: the remedy is the newer tool
                # that wrote them, and calling that "could not be read" sends someone
                # looking for a backup they do not need.
                notes.append(
                    f"{len(listing.needs_a_newer_engine)} run(s) were written by a newer "
                    "version of this tool and need it to open them."
                )
            payload["detail"] = " ".join(notes) or None
        return JSONResponse(payload, headers=SECURITY_HEADERS)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """A placeholder that says so.

        The dashboard arrives at M4.5. This exists because a skeleton nobody can open is a
        skeleton nobody has run, and every claim on this page -- the binding, the headers,
        the host check -- is only worth anything once a real request has travelled through
        it. The markup is inline rather than a template: Jinja2 belongs to the milestone
        that has something to render, and an empty ``templates/`` directory now would be a
        structure decided before the thing that has to fit in it.

        It loads htmx and Alpine (M4.4) even though nothing here uses them yet, and that is
        the point: a vendored asset nobody requests is a vendored asset nobody has proved is
        served, mounted at the path the templates will use, and permitted by the policy. All
        three are true or this page fails to load them.

        ``htmx-config`` is a **meta tag rather than an inline script** because
        ``script-src 'self'`` blocks inline scripts -- setting the config the usual way would
        have been the first thing to quietly violate the policy this app advertises.
        ``allowEval: false`` turns htmx's two eval-backed features into a loud
        ``htmx:evalDisallowedError`` instead of a silent CSP refusal in a console nobody has
        open. See ``static/vendor/VENDOR.yaml``.
        """
        return HTMLResponse(
            "<!doctype html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="htmx-config" content=\'{"allowEval":false}\'>'
            "<title>genetics</title>"
            '<script src="/static/vendor/htmx.min.js" defer></script>'
            '<script src="/static/vendor/alpine.min.js" defer></script>'
            "</head><body>"
            "<h1>genetics</h1>"
            f"<p>Engine {ENGINE_VERSION}. The dashboard is not built yet (roadmap M4.5).</p>"
            '<p><a href="/healthz">/healthz</a> reports what this process can see.</p>'
            "</body></html>\n",
            headers=SECURITY_HEADERS,
        )

    return app
