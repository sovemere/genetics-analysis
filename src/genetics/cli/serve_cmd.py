"""``genetics serve`` -- run the dashboard (roadmap M4.9).

The app itself is :func:`genetics.web.app.create_app`; what is decided here is only how it
reaches a socket, and the answer is *not* "hand uvicorn a host string and hope".

**This command binds the socket itself, and the reason is a real hole rather than tidiness.**
:class:`~genetics.web.config.WebConfig` validates the host it was *given*, and
:func:`~genetics.netaddr.is_local_address` accepts ``localhost`` by name because a Host
header and a config file both write it. But ``localhost`` is resolved through the hosts
file, which is a thing a machine can be made to lie about -- ``DEFAULT_HOST``'s own
docstring says exactly that and picks the literal for exactly that reason. Nothing checked
the other side of it: every existing test asks the config object, and a config object cannot
tell you what address the kernel handed out. So a machine whose hosts file pointed
``localhost`` at its LAN address would have published an unauthenticated genome dashboard to
the network, past a validator that had already approved the spelling.

So the check is made against the outcome -- the address ``getaddrinfo`` returns, and then
again against ``getsockname`` after the bind, which is the only authoritative answer. It is
the lesson :func:`~genetics.web.config.is_wildcard_address` records ("check the *outcome*,
not the input forms") applied one layer down, to the layer that actually opens the port.
Binding here also means a port conflict is this command's error to report, with the
sentence that says which port and what to do, rather than a uvicorn traceback.

**The access log is off by default.** A request line names the URL, and a card's URL is
``/runs/<id>/cards/<card_id>`` -- a card id names a variant, and :data:`SECURITY_HEADERS`
already sends ``Referrer-Policy: no-referrer`` on the argument that a variant plus a person
is the genotype (AGENTS.md 1.3). Having established that a card URL must not reach a third
party through a header, printing the same URLs to a console -- which is the text people
paste into bug reports -- would be the same disclosure through the more likely route.
``--access-log`` turns it on for someone debugging their own machine, deliberately and per
invocation.

**There is no ``--runs-root``.** M4.0 and M4.2 settled that: the store is addressed through
``GENETICS_DATA_DIR``, and a flag whose only caller is a test is a second name for one thing.
"""

from __future__ import annotations

import json
import socket
import sys
from dataclasses import dataclass
from typing import Annotated, Any, NoReturn

import typer

from genetics.netaddr import is_local_address
from genetics.privacy import assert_no_genotype
from genetics.web.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    WebConfig,
    WebConfigError,
    check_bind_host,
    host_forms,
    is_wildcard_address,
)


class ServeError(RuntimeError):
    """The dashboard could not be brought up on the requested address."""


@dataclass(frozen=True)
class Listener:
    """A bound, listening socket and the address the kernel actually gave it.

    ``host`` and ``port`` are read back from the socket rather than copied off the config,
    which is what makes them worth having: ``--port 0`` asks the kernel to choose, and the
    config's answer would be ``0``. The URL printed at startup is therefore the URL that
    works, not the one that was requested.
    """

    socket: socket.socket
    host: str
    port: int

    @property
    def url(self) -> str:
        """The address to open in a browser, bracketed if IPv6."""
        bare, *bracketed = host_forms(self.host)
        return f"http://{bracketed[0] if bracketed else bare}:{self.port}"


def _refuse_unless_loopback(host: str, *, stage: str) -> None:
    """Raise unless ``host`` is an address only this machine can reach.

    Called twice -- once on what ``getaddrinfo`` resolved, before any socket exists, and
    once on what ``getsockname`` reports afterwards. The first is what keeps a LAN address
    from ever being bound, even for the moment it would take to notice and close it; the
    second is the authoritative one, because the kernel is the only thing that knows what it
    handed out. Same body both times, so the two cannot drift into disagreeing about what
    loopback means.
    """
    if is_local_address(host) and not is_wildcard_address(host):
        return
    raise ServeError(
        f"refusing to serve: {stage} is {host!r}, which is reachable from off this "
        "machine. This app serves a run bundle -- raw DNA (AGENTS.md 1.1) -- over HTTP "
        "with no authentication, so it is safe only while nothing else can reach it. If a "
        "loopback name resolved to that address, this machine's hosts file is the place to "
        "look; bind to 127.0.0.1 to avoid the question entirely."
    )


def open_listener(host: str, port: int) -> Listener:
    """Bind and listen, refusing any address that is not loopback.

    Takes a host and a port rather than a :class:`~genetics.web.config.WebConfig`, because
    the config is built *from the result* of this call. That ordering is what lets
    ``--port 0`` work without loosening the config's own rule that a port must be one a URL
    can name: zero is a request to the kernel, and by the time there is a config the kernel
    has answered.

    Only the first address ``getaddrinfo`` returns is used. That is a real limitation for a
    name like ``localhost``, which can resolve to both ``::1`` and ``127.0.0.1`` in an order
    that differs per machine -- so a browser sent to the other one finds nothing. It is also
    the reason :data:`~genetics.web.config.DEFAULT_HOST` is a literal rather than a name, and
    binding several sockets to paper over an ambiguity the default already avoids would be
    solving it in the wrong place.
    """
    # The host rule is imported, not restated: `check_bind_host` is the same function
    # `WebConfig` applies, so the CLI cannot come to a different conclusion about what
    # loopback means than the app it is about to start.
    bare = check_bind_host(host)
    if not 0 <= port <= 65535:
        raise ServeError(f"port {port} is not a port number this machine can be asked for")

    try:
        infos = socket.getaddrinfo(bare, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)
    except OSError as exc:
        raise ServeError(f"{host!r} could not be resolved to a bind address: {exc}") from exc
    if not infos:
        raise ServeError(f"{host!r} resolved to no bind address at all")

    family, socktype, proto, _canonname, sockaddr = infos[0]
    _refuse_unless_loopback(str(sockaddr[0]), stage=f"{host!r} resolved to")

    sock = socket.socket(family, socktype, proto)
    try:
        if sys.platform != "win32":
            # POSIX only, and the asymmetry is the point. On POSIX this lets a listener
            # rebind while an old connection is still in TIME_WAIT, which is the ordinary
            # Ctrl-C-then-restart flow. On Windows the same option means something else
            # entirely -- another process may bind a port already in use and take over the
            # traffic -- so setting it there would let anything on the machine quietly
            # inherit requests meant for this app.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(sockaddr)
        sock.listen(socket.SOMAXCONN)
    except OSError as exc:
        sock.close()
        raise ServeError(
            f"could not listen on {bare} port {port}: {exc}. If something else holds that "
            "port, pass --port to choose another."
        ) from exc

    bound = sock.getsockname()
    bound_host, bound_port = str(bound[0]), int(bound[1])
    try:
        _refuse_unless_loopback(bound_host, stage="the bound address")
    except ServeError:
        sock.close()
        raise
    return Listener(socket=sock, host=bound_host, port=bound_port)


def _error_kind(exc: Exception) -> str:
    """A stable machine-readable name for a refusal, mirroring ``run_cmd._error_kind``.

    The distinction worth branching on is *which* refusal: a config the user can fix by
    changing a flag, versus a port something else is holding, which they fix by changing the
    machine. Prose is not something an agent can branch on.
    """
    return "config" if isinstance(exc, WebConfigError) else "serve"


def _fail(exc: Exception, *, as_json: bool) -> NoReturn:
    """Report a refusal without a traceback, in the shape ``genetics run`` uses.

    **The JSON branch is not decoration.** AGENTS.md 3 makes the CLI the agent interface,
    and an interface where the success path is JSON and the failure path is a sentence on
    stderr is one an agent cannot use without special-casing the command -- which is exactly
    what "keep every command JSON-capable" exists to prevent. Found in review: this printed
    prose under ``--json`` while ``genetics run`` next door emitted
    ``{"ok": false, "error": {...}}`` for the same class of refusal.

    Scanned like every other boundary where text leaves this process. The messages here name
    addresses and ports rather than data, but the guard belongs at the boundary rather than
    in an argument about which of two exception types could ever carry a call.
    """
    message = str(exc)
    assert_no_genotype(message, context="genetics serve error output")
    if as_json:
        payload = {"ok": False, "error": {"kind": _error_kind(exc), "message": message}}
        text = json.dumps(payload, indent=2)
        assert_no_genotype(text, context="genetics serve --json error output")
        typer.echo(text)
    else:
        typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


def _store_state() -> dict[str, Any]:
    """What the dashboard will find when it looks for saved runs.

    Reports rather than refuses, including when the store is unusable -- ``doctor``'s rule
    (M0.6), and the same call ``/healthz`` and ``genetics runs list`` make, because a second
    traversal here would be a second answer to one question (AGENTS.md 3).
    """
    from genetics.paths import UnsafeDataDirError
    from genetics.run import store

    try:
        listing = store.list_runs(None)
    except (UnsafeDataDirError, OSError) as exc:
        return {"runs_root": None, "run_count": None, "detail": str(exc)}
    return {"runs_root": str(listing.root), "run_count": len(listing.runs), "detail": None}


def _report(listener: Listener, state: dict[str, Any], *, as_json: bool) -> None:
    """Say where the dashboard is, **before** the server loop starts.

    The requirement is that this reaches a pipe, not just a terminal: standard output is
    block-buffered when it is redirected, and a supervising script -- or an agent -- reading
    this line to learn the port would otherwise wait on a buffer that fills when the process
    ends, which for a server is never. ``click.echo`` flushes on every call and documents
    that it does, so nothing extra is needed here; an explicit ``flush`` was written first
    and removed, because a line that changes no behaviour reads as the thing keeping the
    promise and would be deleted by whoever noticed it was doing nothing.
    ``tests/test_cli_serve.py`` holds the promise instead, by reading the report off a pipe
    while the server is still running.
    """
    from genetics import __version__

    if as_json:
        payload = {
            "ok": True,
            "engine_version": __version__,
            "host": listener.host,
            "port": listener.port,
            "url": listener.url,
            **state,
        }
        text = json.dumps(payload, indent=2)
        assert_no_genotype(text, context="genetics serve --json output")
        typer.echo(text)
        return

    lines = [(f"  {listener.url}", {"fg": typer.colors.GREEN, "bold": True})]
    if state["detail"] is not None:
        lines.append((f"  ! {state['detail']}", {"fg": typer.colors.YELLOW}))
        lines.append(("    The dashboard will open and explain this.", {}))
    else:
        lines.append((f"  {state['run_count']} saved run(s) in {state['runs_root']}", {}))
    lines.append(("  Nothing here leaves this machine. Ctrl+C to stop.", {}))

    for text, style in lines:
        # Scanned like the JSON branch and like everything `genetics run` prints. Neither
        # branch can carry a genotype today -- a run count and a path -- but `detail` is an
        # exception message from the store, which is the field most likely to grow one, and
        # the guard belongs at the boundary rather than in that argument.
        assert_no_genotype(text, context="genetics serve output")
        typer.secho(text, **style)  # type: ignore[arg-type]


def serve(
    host: Annotated[
        str,
        typer.Option("--host", help="Loopback address to bind. Anything else is refused."),
    ] = DEFAULT_HOST,
    port: Annotated[
        int,
        typer.Option("--port", help="TCP port. 0 asks the OS for a free one."),
    ] = DEFAULT_PORT,
    access_log: Annotated[
        bool,
        typer.Option(
            "--access-log/--no-access-log",
            help=(
                "Log every request URL to the console. Off by default: a card URL names a variant."
            ),
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Serve the dashboard on this machine only."""
    # Imported here rather than at module scope: uvicorn pulls in asyncio, h11 and its own
    # logging config, and `genetics --help` should not pay for a server it is not starting.
    import uvicorn

    from genetics.web.app import create_app

    try:
        listener = open_listener(host, port)
    except (WebConfigError, ServeError) as exc:
        _fail(exc, as_json=as_json)

    try:
        # Built from the socket, not from the flags. Under `--port 0` the flags do not name
        # an address at all, and under a name that resolved they name it less precisely than
        # the kernel does -- so the app's `allowed_hosts`, which is derived from this, ends
        # up describing what is actually listening. The loopback baseline in LOOPBACK_HOSTS
        # means a browser asking for `localhost` is still answered. Inside the `finally` that
        # closes the socket, because a config built from a *bound* address should not be able
        # to fail and "should not be able to" is how a port gets left listening after the
        # command has already reported that it refused to serve.
        config = WebConfig(host=listener.host, port=listener.port)
        # The app is constructed before the address is announced. The other order reads
        # fine and is wrong: `create_app` mounts the static directory and will raise on an
        # installation missing its package data, so a failure there printed "here is your
        # dashboard, at this URL" and then a traceback for a server that never existed.
        application = create_app(config)
        _report(listener, _store_state(), as_json=as_json)
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                # `warning` rather than `info`, and the first version of this comment
                # got the reason wrong: it claimed `info` would print a banner naming the
                # requested host and port a second time. It does not -- `Server.startup`
                # skips `_log_started_message` whenever it is handed sockets, at every
                # level, so there is no duplicate to avoid. The actual reason is plainer:
                # `info` adds three lines of framework chatter ("Started server process",
                # "Waiting for application startup", "Application startup complete") after a
                # report that has already said the useful thing. Warnings and errors still
                # reach the console, which is what the level is for.
                log_level="info" if access_log else "warning",
                access_log=access_log,
            )
        )
        # Passing the socket means uvicorn does not bind one of its own: the address has
        # already been checked twice and a port conflict already reported in a sentence.
        # It also removes the gap a caller reading the report above would otherwise race --
        # the socket is listening before the URL is printed, so a connection that arrives
        # before this line sits in the accept backlog rather than being refused.
        #
        # On interrupt, uvicorn handles SIGINT, SIGTERM and (on Windows) SIGBREAK. What was
        # actually measured, rather than assumed: sending CTRL_BREAK to this command on
        # Windows stops it with **no traceback and nothing on stderr**, and an exit status of
        # 0xC000013A -- which is Windows' STATUS_CONTROL_C_EXIT, what the console reports for
        # a control-event stop rather than a value this command chooses. A true CTRL_C_EVENT
        # could not be delivered to a child from a test harness, so the graceful-return path
        # is unverified here; the socket is closed by the `finally` below on every path that
        # returns, and by the OS on the one that does not.
        server.run(sockets=[listener.socket])
    except WebConfigError as exc:
        _fail(exc, as_json=as_json)
    finally:
        listener.socket.close()
