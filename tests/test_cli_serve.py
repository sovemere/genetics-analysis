"""CLI contract for ``genetics serve`` (roadmap M4.9).

Half this file is about one question: **what address did the process actually bind?**
Every test in ``tests/web/test_app.py`` that touches the loopback promise asks the
:class:`~genetics.web.config.WebConfig` object, and a config object records what it was
told. ``localhost`` is accepted by name -- it has to be, a Host header writes it -- and
resolved through a hosts file, which is a thing a machine can be made to lie about. So the
checks that matter here are made against ``getaddrinfo``'s answer and then against
``getsockname``'s, and both are driven with the resolver forced to lie.
"""

from __future__ import annotations

import inspect
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from genetics.cli import main as cli_main
from genetics.cli import serve_cmd
from genetics.cli.serve_cmd import Listener, ServeError, open_listener
from genetics.privacy import GenotypeLeakError
from genetics.web.config import DEFAULT_HOST, DEFAULT_PORT, WebConfig

runner = CliRunner()

LAN_ADDRESS = "192.168.1.50"
"""Not loopback, and the address a mis-set hosts file most plausibly hands back."""


def _serve(*args: str) -> Result:
    return runner.invoke(cli_main.app, ["serve", *args])


# ---------------------------------------------------------------------------
# What the flags default to
# ---------------------------------------------------------------------------


def test_the_command_defaults_match_the_library_constants() -> None:
    """The literals in ``main.py`` and the constants in ``web.config`` must agree.

    They are written twice on purpose -- importing the constants would pull FastAPI into
    ``genetics --help``, and dropping the defaults would blank them out of the help text
    where a person goes to find the port. Two spellings of one value is the drift the
    ``fixtures`` command's own comment argues against, so the agreement is asserted rather
    than remembered.
    """
    parameters = inspect.signature(cli_main.serve).parameters
    assert parameters["host"].default == DEFAULT_HOST
    assert parameters["port"].default == DEFAULT_PORT
    assert parameters["access_log"].default is False, (
        "a card URL names a variant; the access log is off unless asked for"
    )


def test_the_two_command_entry_points_take_the_same_options() -> None:
    """``main.serve`` forwards to ``serve_cmd.serve``; a new flag on one must reach both."""
    assert set(inspect.signature(cli_main.serve).parameters) == set(
        inspect.signature(serve_cmd.serve).parameters
    )


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host", [LAN_ADDRESS, "example.com", "10.0.0.1", "::ffff:10.0.0.1"])
def test_an_address_off_this_machine_is_refused(host: str) -> None:
    result = _serve("--host", host)
    assert result.exit_code == 2
    assert "refusing to bind" in result.output
    assert "AGENTS.md 1.1" in result.output


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "[::]", "0:0:0:0:0:0:0:0", "::ffff:0.0.0.0"])
def test_the_wildcard_is_refused_however_it_is_spelled(host: str) -> None:
    """The same spellings ``is_wildcard_address`` was written for, asked of the command.

    That function has its own tests; this asserts the command actually reaches it rather
    than validating the host some other way on the path to a socket.
    """
    result = _serve("--host", host)
    assert result.exit_code == 2
    assert "wildcard" in result.output


@pytest.mark.parametrize("port", [-1, 65536, 99999])
def test_a_port_this_machine_cannot_be_asked_for_is_refused(port: int) -> None:
    result = _serve("--port", str(port))
    assert result.exit_code == 2
    assert str(port) in result.output


@pytest.mark.parametrize(
    ("args", "kind"),
    [
        (("--host", LAN_ADDRESS), "config"),
        (("--host", "0.0.0.0"), "config"),
        (("--port", "99999"), "serve"),
    ],
)
def test_a_refusal_under_json_is_json(args: tuple[str, ...], kind: str) -> None:
    """AGENTS.md 3 makes the CLI the agent interface, failures included.

    Found in review: this printed prose under ``--json`` while ``genetics run`` next door
    emitted ``{"ok": false, "error": {...}}`` for the same class of refusal, so an agent
    driving both had to special-case one of them.
    """
    result = _serve(*args, "--json")
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["kind"] == kind
    assert payload["error"]["message"].strip()


def test_a_refusal_is_a_message_rather_than_a_traceback() -> None:
    result = _serve("--host", LAN_ADDRESS)
    assert result.exit_code == 2
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# What it binds
# ---------------------------------------------------------------------------


def test_it_binds_loopback_and_reports_the_port_the_kernel_chose() -> None:
    listener = open_listener(DEFAULT_HOST, 0)
    try:
        assert listener.host == DEFAULT_HOST
        assert listener.port != 0, "port 0 is a request, not an answer; report what was given"
        assert listener.url == f"http://{DEFAULT_HOST}:{listener.port}"
        assert listener.socket.getsockname()[1] == listener.port
    finally:
        listener.socket.close()


def test_an_ipv6_url_is_bracketed() -> None:
    """A browser needs ``http://[::1]:8765``; ``socket.bind`` needs ``::1``."""
    unbound = socket.socket()
    try:
        assert Listener(socket=unbound, host="::1", port=8765).url == "http://[::1]:8765"
    finally:
        unbound.close()


def test_a_port_already_in_use_is_reported_with_the_remedy() -> None:
    """The failure ``DEFAULT_PORT``'s docstring is worried about, made a sentence."""
    held = open_listener(DEFAULT_HOST, 0)
    try:
        with pytest.raises(ServeError) as caught:
            open_listener(DEFAULT_HOST, held.port)
        assert "--port" in str(caught.value)
        assert str(held.port) in str(caught.value)
    finally:
        held.socket.close()


def test_the_config_the_app_gets_answers_for_the_address_that_is_listening() -> None:
    """``allowed_hosts`` is derived from the bind, so the DNS-rebinding check permits it.

    Built from the socket rather than the flags: under ``--port 0`` the flags do not name an
    address at all. A config built from the request would leave the app refusing requests to
    itself, which is the bug ``WebConfig.__post_init__`` already records having fixed once.
    """
    listener = open_listener(DEFAULT_HOST, 0)
    try:
        config = WebConfig(host=listener.host, port=listener.port)
        assert listener.host in config.allowed_hosts
        assert "localhost" in config.allowed_hosts, "a browser typing localhost is still us"
        assert config.url == listener.url
    finally:
        listener.socket.close()


# ---------------------------------------------------------------------------
# The resolver, forced to lie
# ---------------------------------------------------------------------------


def _resolving_to(address: str) -> Any:
    """A ``getaddrinfo`` that sends every name to ``address``."""

    def fake(*_args: object, **_kwargs: object) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 8765))]

    return fake


def test_a_loopback_name_pointed_off_this_machine_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hole this command exists to close.

    ``WebConfig`` accepts ``localhost`` by name, because a Host header writes it that way and
    a config file may too. A hosts file can point that name anywhere. Every check that came
    before this one asked the config, so a machine set up this way would have published an
    unauthenticated genome dashboard to its network with every existing test passing.
    """
    monkeypatch.setattr("genetics.cli.serve_cmd.socket.getaddrinfo", _resolving_to(LAN_ADDRESS))
    with pytest.raises(ServeError) as caught:
        open_listener("localhost", 0)
    assert LAN_ADDRESS in str(caught.value)
    assert "hosts file" in str(caught.value)


def test_nothing_is_bound_while_the_resolved_address_is_being_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refused *before* a socket exists, not closed afterwards.

    A bind that happens and is then undone is still a moment during which the port answered
    on a LAN address. The check is ordered ahead of ``socket()`` so that moment does not
    exist, and this asserts the ordering rather than the outcome -- the outcome is the same
    either way, which is exactly why it needs its own test.
    """
    monkeypatch.setattr("genetics.cli.serve_cmd.socket.getaddrinfo", _resolving_to(LAN_ADDRESS))
    created: list[object] = []

    def watched(*args: Any, **kwargs: Any) -> socket.socket:
        opened = socket.socket(*args, **kwargs)
        created.append(opened)
        return opened

    monkeypatch.setattr("genetics.cli.serve_cmd.socket.socket", watched)
    with pytest.raises(ServeError):
        open_listener("localhost", 0)
    assert not created, "a socket was opened for an address that was about to be refused"


def test_the_bound_address_is_checked_and_not_only_the_resolved_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``getsockname`` is the only authoritative answer, so it is asked too.

    Resolution says what was requested of the kernel; this says what the kernel did. They
    agree today, and a check that can only ever return one answer is the failure this
    project has recorded twice (M0.6). Forced apart here so the second check is exercised.
    """
    closed: list[bool] = []

    class Lying(socket.socket):
        def getsockname(self) -> Any:
            return (LAN_ADDRESS, 1234)

        def close(self) -> None:
            closed.append(True)
            super().close()

    monkeypatch.setattr("genetics.cli.serve_cmd.socket.socket", Lying)
    with pytest.raises(ServeError) as caught:
        open_listener(DEFAULT_HOST, 0)
    assert "the bound address" in str(caught.value)
    assert closed, "the socket was refused but left listening"


# ---------------------------------------------------------------------------
# What it prints
# ---------------------------------------------------------------------------


def test_the_startup_report_is_scanned_for_genotype() -> None:
    """``detail`` is a message from the store, and the guard sits at the boundary."""
    listener = open_listener(DEFAULT_HOST, 0)
    try:
        # Assembled at runtime rather than written out, the way `test_cli_run.py` does it.
        # A tab-separated genotype row spelled literally in the source is a genotype row in
        # a public repo, and `genetics check-staged` refuses the commit -- correctly. It
        # caught this file on the first attempt at committing it.
        dirty = "\t".join(("rs4988235", "2", "136608646", "A", "G"))
        state: dict[str, Any] = {"runs_root": None, "run_count": None, "detail": dirty}
        with pytest.raises(GenotypeLeakError):
            serve_cmd._report(listener, state, as_json=False)
        with pytest.raises(GenotypeLeakError):
            serve_cmd._report(listener, state, as_json=True)
    finally:
        listener.socket.close()


def test_the_address_is_not_announced_before_the_app_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is printed until there is something behind the URL.

    ``create_app`` mounts the static directory and raises on an installation missing its
    package data. Reported in the other order -- the natural one -- the command printed
    "here is your dashboard, at this URL" and then a traceback for a server that never
    existed, which is a worse failure than the one it was reporting.
    """

    def missing_package_data(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Directory 'static' does not exist")

    monkeypatch.setattr("genetics.web.app.create_app", missing_package_data)
    result = _serve("--port", "0")
    assert result.exit_code != 0
    assert "http://" not in result.output, "an address was announced for an app that failed"


# ---------------------------------------------------------------------------
# End to end, as a real process
# ---------------------------------------------------------------------------


def _read_json_object(process: subprocess.Popen[str], *, timeout: float) -> dict[str, Any]:
    """Read one pretty-printed JSON object off a live process's stdout.

    In a thread with a deadline, because the process is a server: if the report were not
    flushed, a plain read would block until the process ended, which is never.
    """
    stream = process.stdout
    assert stream is not None
    chunks: list[str] = []

    def reader() -> None:
        for line in iter(stream.readline, ""):
            chunks.append(line)
            if line.rstrip() == "}":
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout)
    text = "".join(chunks)
    if not text.strip():
        # The child is a server, so "printed nothing" usually means it died instead of
        # starting -- and the reason is on the stderr this would otherwise discard, leaving
        # a CI failure that says only that the pipe was empty.
        died = process.poll()
        detail = "(still running)"
        if died is not None and process.stderr is not None:
            detail = process.stderr.read()
        raise AssertionError(
            f"the server printed nothing before it started serving; exit={died}, stderr:\n{detail}"
        )
    return dict(json.loads(text))


def test_the_running_server_answers_on_the_port_it_reported(tmp_path: Path) -> None:
    """The whole command, as a separate process, driven the way an agent would drive it.

    Nothing else here opens a socket through the CLI: every other test in this file stops at
    ``open_listener`` or at a refusal. This is what proves the reported address is the one
    uvicorn is serving on, and that the report reaches a pipe before the loop starts rather
    than sitting in a buffer that fills when the process exits.
    """
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from genetics.cli.main import app; app()",
            "serve",
            "--port",
            "0",
            "--json",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ | {"GENETICS_DATA_DIR": str(tmp_path / "data")},
    )
    try:
        report = _read_json_object(process, timeout=60)
        assert report["ok"] is True
        assert report["port"] != 0
        assert report["run_count"] == 0

        with socket.create_connection((report["host"], report["port"]), timeout=10) as probe:
            request = f"GET /healthz HTTP/1.0\r\nHost: {report['host']}:{report['port']}\r\n\r\n"
            probe.sendall(request.encode())
            received = b""
            while chunk := probe.recv(4096):
                received += chunk
        assert b"200 OK" in received
        assert b'"ok":true' in received.replace(b'"ok": true', b'"ok":true')
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - only on a wedged child
            process.kill()
            process.wait(timeout=30)
