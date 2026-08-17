"""What counts as an address that never leaves this machine.

One definition, deliberately, because two things depend on it and they must not be able to
disagree. :mod:`genetics.testing.network` (M2.7) uses it to decide which connections the
offline guard permits; :mod:`genetics.web.config` (M4.3) uses it to decide which addresses
the dashboard may bind to and answer for. If those two ever drew the line differently, the
suite would either block the server it is supposed to be driving or vouch for a bind it
never checked -- and the disagreement would surface as a confusing test failure rather than
as the policy question it actually is.

Anything unrecognised is treated as **remote**. That is the same fail-closed rule the
licence gate (M2.1) and the build check (M1.5) follow: guessing in the permissive direction
here would let through exactly the case each caller exists to catch.
"""

from __future__ import annotations

import ipaddress

__all__ = ["is_local_address"]


def is_local_address(host: object) -> bool:
    """True for destinations and bind addresses that never leave this machine."""
    if host is None:
        # ``getaddrinfo(None, port)`` asks for a local bind address, not a destination.
        return True

    if isinstance(host, bytes | bytearray):
        try:
            host = bytes(host).decode("ascii")
        except UnicodeDecodeError:
            return False

    if not isinstance(host, str):
        return False

    text = host.strip()
    # ``[::1]`` is how a URL and an HTTP Host header write an IPv6 literal. Unbracketed is
    # how a config file and ``socket.bind`` write the same address, so both arrive here.
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]

    try:
        address: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(text)
    except ValueError:
        lowered = text.lower()
        return lowered == "localhost" or lowered.endswith(".localhost")

    # ``::ffff:127.0.0.1`` is loopback in every sense that matters here, but
    # ``IPv6Address.is_loopback`` is true only of ``::1``, so unwrap first.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped

    # ``is_unspecified`` covers 0.0.0.0 and ::, which name the wildcard *bind* address
    # rather than any remote host. That is right for the offline guard, which is asking
    # "does this leave the machine"; it is wrong for a bind, which is asking "can anyone
    # else reach this" -- and 0.0.0.0 means yes. See genetics.web.config, which excludes
    # the wildcard separately rather than by weakening this.
    return address.is_loopback or address.is_unspecified
