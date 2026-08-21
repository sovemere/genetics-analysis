"""Where the dashboard listens, and who it will answer (roadmap M4.3).

The roadmap line is "binds localhost only". This module is that line made checkable, and
it is worth being precise about what the guarantee actually is, because the obvious reading
of it is wrong in a way that matters here.

**Binding to loopback is refused-by-default, not documented-by-default.** The failure this
prevents is mundane and common: someone hits a "connection refused" from a VM, a container,
or a phone on the same wifi, and fixes it by setting the host to ``0.0.0.0`` -- which
publishes an unauthenticated genome browser to every machine on the network. So the host is
validated at construction and the wildcard is refused by name, with a message that says
what would be exposed rather than "invalid host".

**A loopback bind is not the same guarantee as "only this machine can reach it".** A page
on the open internet can point a hostname it controls at ``127.0.0.1`` and have the
visitor's own browser read this app -- DNS rebinding, and a local server holding somebody's
DNA is a worthwhile target for it. The bind address cannot stop that, because the request
genuinely arrives on loopback; what distinguishes it is the ``Host`` header, which still
carries the attacker's domain. So :data:`WebConfig.allowed_hosts` exists alongside the bind
address, and :mod:`genetics.web.app` enforces it. Saying "binds localhost only" and
stopping there would have been the kind of overclaim this project keeps having to correct.

**The definition of "local" is imported, not restated.** :func:`genetics.netaddr.is_local_address`
is the same predicate M2.7's offline guard uses to decide which connections a test may make.
Two copies would eventually disagree, and the symptom would be the suite blocking the very
server it is meant to be driving.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path

from genetics.netaddr import is_local_address

DEFAULT_HOST = "127.0.0.1"
"""The literal rather than ``localhost``.

``localhost`` resolves through the host file and can be made to answer for something else;
the numeric loopback address cannot. It is also unambiguous about family, where ``localhost``
may resolve to ``::1`` first on one machine and ``127.0.0.1`` on another -- and a bind that
silently changes family between machines is a support question nobody enjoys.
"""

DEFAULT_PORT = 8765
"""Deliberately not 8000 or 8080. Those are the two ports something else is already using
on a developer's machine, and a genome dashboard failing to start because a stale container
holds 8000 is a bad first impression of an offline-first tool."""

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")
"""Host header values that name this machine.

Both the bracketed and bare IPv6 forms are listed because a browser writes ``[::1]:8765``
in a URL and therefore in the header, while a config file and ``socket.bind`` write ``::1``.

This is the *baseline*, not the whole allowlist: :class:`WebConfig` adds whatever address it
was told to bind to. See :func:`host_forms` for why that is not optional.
"""


def bare_host(host: str) -> str:
    """``host`` with surrounding whitespace and any IPv6 brackets removed.

    :class:`WebConfig` stores this form, because it is the one ``socket.bind`` and uvicorn
    accept: the literal string ``"[::1]"`` is not an address either of them can resolve.
    Brackets belong to URLs, and :attr:`WebConfig.url` puts them back.
    """
    text = host.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text


def host_forms(host: str) -> tuple[str, ...]:
    """Every way a browser might write ``host`` in a ``Host`` header.

    The bare address and, for IPv6, the bracketed form -- because a URL and therefore the
    header write ``[::1]:8765`` while a config file and ``socket.bind`` write ``::1``.
    """
    bare = bare_host(host)
    return (bare, f"[{bare}]") if ":" in bare else (bare,)


def is_wildcard_address(host: str) -> bool:
    """True for an address that binds every interface on this machine.

    **Asked of the parsed address, never of the spelling.** The first cut of this check was
    a literal set -- ``{"0.0.0.0", "::", "[::]"}`` -- and review found six spellings that
    walked straight past it: ``::0``, ``0::0``, ``0000::0``, ``0:0:0:0:0:0:0:0``,
    ``[0.0.0.0]`` and ``::ffff:0.0.0.0``. Every one binds every interface, so every one
    published an unauthenticated genome dashboard to the local network -- the single thing
    this module exists to prevent, defeated by writing the same address differently.

    It is also the mistake this project has now made and corrected four times, and the
    lesson is always the same one: check the *outcome*, not the input forms. ``check_run_id``
    reached it about paths after the Windows drive-letter case, ``payload_name`` about
    manifest entries, and M2.5's archive extractor about zip members. A blacklist of
    spellings is a promise that somebody enumerated a notation exhaustively, and nobody ever
    has.
    """
    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(
            bare_host(host)
        )
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return address.is_unspecified


class WebConfigError(ValueError):
    """Raised for a configuration that would expose the dashboard beyond this machine."""


def check_bind_host(host: str) -> str:
    """Return ``host`` in bare form, or raise if binding it would expose the dashboard.

    Module-level rather than inline in :meth:`WebConfig.__post_init__` because there are two
    callers and the rule must not be able to differ between them. ``genetics serve`` (M4.9)
    needs the answer *before* it has a config -- it binds the socket first, so that the
    config it eventually builds describes the address the kernel actually handed out rather
    than the one that was asked for -- and a second copy of these two checks living in the
    CLI is the shape of problem this project keeps recording.
    """
    bare = bare_host(host)
    if not is_local_address(bare):
        raise WebConfigError(
            f"refusing to bind the dashboard to {host!r}. This app serves a run "
            "bundle, which is raw DNA (AGENTS.md 1.1), over HTTP with no authentication "
            "of any kind -- it is safe only because nothing outside this machine can "
            "reach it. Bind to 127.0.0.1. If you need it from another machine, forward "
            "the port over SSH, which keeps the trust boundary where it is."
        )
    if is_wildcard_address(bare):
        # `is_local_address` treats the wildcard as local, correctly, because it answers
        # "does this leave the machine" for an outbound connection. As a *bind* address
        # it means the opposite: every interface, so every machine on the network. The
        # two questions differ only here, which is why this is a second check rather
        # than a weakening of the shared predicate.
        raise WebConfigError(
            f"refusing to bind the dashboard to the wildcard address {host!r}. "
            "That is every network interface on this machine, which publishes an "
            "unauthenticated view of somebody's genome to the local network. It is the "
            "one-character change that turns a private tool into a public one, so it is "
            "refused however it is spelled."
        )
    return bare


@dataclass(frozen=True)
class WebConfig:
    """How to serve the dashboard. Validated at construction, so no caller can skip it."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    runs_root: Path | None = None
    """``None`` means the user data directory, resolved at request time rather than here.

    Resolution is deferred on purpose: :func:`genetics.run.bundle.resolve_runs_root` raises
    when ``GENETICS_DATA_DIR`` points inside the checkout, and an app that could not be
    *constructed* in that state could not serve the page that explains it either. The health
    endpoint reports the problem instead -- ``doctor``'s rule (M0.6), applied to the surface
    a person is most likely to be looking at when they hit it.
    """

    allowed_hosts: tuple[str, ...] = LOOPBACK_HOSTS
    """Host header values the app will answer. See the module docstring on DNS rebinding."""

    def __post_init__(self) -> None:
        host = check_bind_host(self.host)
        # Zero is excluded here and accepted by `genetics serve --port 0`, and the gap is
        # deliberate. This class describes an address a URL can name -- `url` renders it --
        # and `http://127.0.0.1:0` names nothing. Zero is a request to the kernel, not an
        # address, so it belongs to the code doing the asking; by the time a config is built
        # from a bound socket the kernel has already answered with a real port.
        if not 1 <= self.port <= 65535:
            raise WebConfigError(f"port {self.port} is not a usable TCP port")
        if not self.allowed_hosts:
            raise WebConfigError(
                "allowed_hosts is empty, which would refuse every request including this "
                "machine's own. An empty allowlist is a mistake, not a lockdown."
            )

        # A server must answer for the address it was told to bind to. Without this, the
        # allowlist is a fixed list of the *common* loopback names and anything else is
        # refused -- so `WebConfig(host="127.0.0.5")`, which this class accepts and which is
        # the ordinary way to dodge a port conflict, produced a server that rejected every
        # request to itself with a message about DNS rebinding. That is precisely the bug
        # this module's docstring accuses Starlette's TrustedHostMiddleware of, written a
        # second time one file away. Derived rather than left to the caller, because a
        # caller who has to remember to add their own bind address will not.
        object.__setattr__(
            self,
            "allowed_hosts",
            tuple(dict.fromkeys([*self.allowed_hosts, *host_forms(host)])),
        )
        # Stored bare, because that is the form `socket.bind` and uvicorn accept: the
        # literal string "[::1]" is not an address either can resolve, so a config that kept
        # what the caller typed would validate cleanly and then fail at bind time. Brackets
        # are a URL notation and `url` puts them back.
        object.__setattr__(self, "host", host)

    @property
    def url(self) -> str:
        """The address to open in a browser, bracketed if IPv6."""
        bare, *bracketed = host_forms(self.host)
        return f"http://{bracketed[0] if bracketed else bare}:{self.port}"
