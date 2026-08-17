"""Refuse network access in-process (roadmap M2.7).

The project's central promise is that analysis happens offline: no network call at
analysis time is both a definition-of-done item and an explicit non-goal for v1. Today
that promise is easy to keep -- exactly one module in ``src/`` opens a socket
(:class:`genetics.refs.fetcher.UrllibTransport`) and no test touches the network at all.
It gets harder with every milestone that adds a module, and a stray ``urlopen`` in a card
loader or a per-trait PGS fetch would otherwise go unnoticed until the M15.1 release gate,
by which point something is built on top of it. Enforced continuously instead, it fails in
the commit that introduces it, naming the test that reached out.

**Loopback is allowed on purpose.** M4.3 binds a FastAPI app to localhost and M13.5's
parity tests will drive it. A guard that blocked that would be switched off wholesale by
the first person who hit it -- M0.3's "a scanner that cries wolf gets bypassed", applied
to this one.

**What this cannot see, by construction: a subprocess.** PLINK 2, Beagle, Java and R run
in their own address spaces, where patching this process's :mod:`socket` module has no
reach. Nothing here constrains them. Only the OS-level test in M4.10 does, which is why
that box is still open rather than a formality.

:class:`NetworkAccessError` derives from :class:`RuntimeError` rather than
:class:`OSError` deliberately. ``urllib`` catches ``OSError`` around its transport and
re-raises it as ``URLError``; as an ``OSError`` this would arrive wrapped, worded as a
connection failure, and would be indistinguishable from the offline case that retry logic
is written to swallow. As a ``RuntimeError`` it propagates intact, saying what it means.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from genetics.netaddr import is_local_address

__all__ = [
    "NetworkAccessError",
    "allow_network",
    "block_network",
    "guard_is_active",
    "is_local_address",
]


class NetworkAccessError(RuntimeError):
    """Raised when code under the guard reaches for a non-loopback address."""


_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_GETADDRINFO = socket.getaddrinfo

_UNSET = object()
_PATCHED_METHODS = ("connect", "connect_ex")

_depth = 0
"""Nesting depth, not a boolean. A bool would be cleared by the *inner* exit of a nested
``block_network()`` while the outer block is still installed, so ``guard_is_active()``
would report False with the patches still in place -- and that function exists precisely so
a test can trust the answer."""


def guard_is_active() -> bool:
    """Whether the block is currently installed.

    Exists so a test can assert the escape hatch really lifted the guard without opening a
    socket to prove it -- a test that verified the hatch by making a real connection would
    put actual traffic in a suite whose whole point is that there is none.
    """
    return _depth > 0


# ---------------------------------------------------------------------------
# What counts as leaving the machine
# ---------------------------------------------------------------------------
#
# :func:`is_local_address` moved to :mod:`genetics.netaddr` in M4.3 and is re-exported
# here, because the web server's binding policy has to draw the same line this guard does.
# Two copies would let the suite block the very server it is meant to drive, or vouch for a
# bind it never checked -- and either way the disagreement would surface as a puzzling test
# failure instead of as the policy question it is.


def _destination(address: object) -> object | None:
    """Host part of a ``connect`` argument, or None when there is no network host.

    AF_UNIX addresses are a filesystem path and other families have shapes of their own;
    none of them leave the machine, so anything that is not an ``(host, port, ...)`` tuple
    is allowed rather than guessed at.
    """
    if isinstance(address, tuple) and address:
        first: object = address[0]
        return first
    return None


def _refuse(host: object) -> NetworkAccessError:
    return NetworkAccessError(
        f"blocked an attempt to reach {host!r}. This suite runs offline (roadmap M2.7). "
        "Inject a fake transport the way tests/refs/test_fetcher.py does, or mark the "
        "test @pytest.mark.network if it genuinely has to reach the network."
    )


# ---------------------------------------------------------------------------
# Replacements
# ---------------------------------------------------------------------------

_AddressInfo = list[
    tuple[
        socket.AddressFamily,
        socket.SocketKind,
        int,
        str,
        tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes],
    ]
]


def _blocked_connect(self: socket.socket, address: Any) -> None:
    host = _destination(address)
    if is_local_address(host):
        _REAL_CONNECT(self, address)
        return
    raise _refuse(host)


def _blocked_connect_ex(self: socket.socket, address: Any) -> int:
    host = _destination(address)
    if is_local_address(host):
        return _REAL_CONNECT_EX(self, address)
    raise _refuse(host)


def _blocked_getaddrinfo(
    host: bytes | str | None,
    port: bytes | str | int | None,
    family: int = 0,
    type: int = 0,  # shadows a builtin, because socket.getaddrinfo names it that
    proto: int = 0,
    flags: int = 0,
) -> _AddressInfo:
    """Resolution is blocked too, not only connection.

    A DNS lookup is itself traffic, and it is the step that discloses what is being
    fetched. Catching it here also produces the better message: at this point the hostname
    is still in hand, where by ``connect`` time it is an anonymous IP.
    """
    if is_local_address(host):
        return _REAL_GETADDRINFO(host, port, family, type, proto, flags)
    raise _refuse(host)


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


@contextmanager
def allow_network() -> Iterator[None]:
    """Lift the block for the duration, then put back exactly what was there.

    The inverse of :func:`block_network`, and it exists because the guard is installed for
    the whole *session*: a function-scoped fixture cannot cover a session- or module-scoped
    one, since pytest builds higher-scoped fixtures first. A module-scoped "fetch the
    reference once" fixture is the most natural home a stray network call could find, and
    it would have run before any per-test guard was in place. So the block goes on once at
    session scope and a ``network``-marked test lifts it here.
    """
    global _depth

    saved = {name: socket.socket.__dict__.get(name, _UNSET) for name in _PATCHED_METHODS}
    saved_getaddrinfo = socket.getaddrinfo
    saved_depth = _depth

    socket.getaddrinfo = _REAL_GETADDRINFO
    for name in _PATCHED_METHODS:
        if name in socket.socket.__dict__:
            delattr(socket.socket, name)
    _depth = 0
    try:
        yield
    finally:
        _depth = saved_depth
        socket.getaddrinfo = saved_getaddrinfo
        for name, value in saved.items():
            if value is _UNSET:
                if name in socket.socket.__dict__:
                    delattr(socket.socket, name)
            else:
                setattr(socket.socket, name, value)


@contextmanager
def block_network() -> Iterator[None]:
    """Refuse every non-loopback connection and name lookup for the duration.

    ``connect`` and ``connect_ex`` are inherited from ``_socket.socket`` rather than
    defined on ``socket.socket``, so restoring means *removing* the override, not writing
    the inherited function back onto the subclass -- hence the ``__dict__`` check.
    """
    global _depth

    saved = {name: socket.socket.__dict__.get(name, _UNSET) for name in _PATCHED_METHODS}
    saved_getaddrinfo = socket.getaddrinfo

    socket.socket.connect = _blocked_connect  # type: ignore[assignment]
    socket.socket.connect_ex = _blocked_connect_ex  # type: ignore[assignment]
    socket.getaddrinfo = _blocked_getaddrinfo
    _depth += 1
    try:
        yield
    finally:
        _depth -= 1
        socket.getaddrinfo = saved_getaddrinfo
        for name, value in saved.items():
            if value is _UNSET:
                delattr(socket.socket, name)
            else:
                setattr(socket.socket, name, value)
