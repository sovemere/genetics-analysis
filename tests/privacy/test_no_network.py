"""The suite does not reach the network, and this proves the guard fires (roadmap M2.7).

Filed with the privacy suite rather than beside the fetcher tests for two reasons. The
failure being guarded is an egress one -- the worst network call this application could
make is the one carrying genotype data off the machine -- and the pre-commit hook runs
``tests/privacy``, so the check runs before a commit rather than only in CI.

M0's lesson governs the shape of this file: a guard that has not been *demonstrated*
failing on real input is not evidence of anything. So the central test drives the actual
production download path, :class:`~genetics.refs.fetcher.UrllibTransport`, rather than a
bare socket that no shipped code resembles.
"""

from __future__ import annotations

import socket

import pytest

from genetics.refs.fetcher import UrllibTransport
from genetics.testing.network import (
    _REAL_GETADDRINFO,
    NetworkAccessError,
    _blocked_connect,
    block_network,
    guard_is_active,
    is_local_address,
)

pytestmark = pytest.mark.privacy


# ---------------------------------------------------------------------------
# The guard refuses
# ---------------------------------------------------------------------------


def test_the_real_download_path_is_blocked() -> None:
    """The one that matters: the module that actually opens sockets in production.

    ``UrllibTransport`` is reached by ``refs fetch`` and by ``tools install``. If some
    later milestone calls either during a test, this is where it stops.
    """
    with pytest.raises(NetworkAccessError):
        UrllibTransport().open("https://ftp.ncbi.nlm.nih.gov/pub/clinvar/clinvar.vcf.gz")


def test_the_refusal_is_not_disguised_as_a_connection_failure() -> None:
    """It must not arrive as ``URLError``.

    ``urllib`` wraps ``OSError`` from its transport into ``URLError``, which reads exactly
    like an ordinary offline failure -- the thing a fetcher is written to retry or report
    calmly. Deriving from ``RuntimeError`` keeps the refusal legible as a rule violation.
    """
    with pytest.raises(NetworkAccessError) as caught:
        UrllibTransport().open("https://example.invalid/whatever")

    assert not isinstance(caught.value, OSError)
    assert "example.invalid" in str(caught.value)
    assert "@pytest.mark.network" in str(caught.value)


def test_name_resolution_is_blocked() -> None:
    """DNS is traffic, and it is the step that discloses what is being fetched."""
    with pytest.raises(NetworkAccessError):
        socket.getaddrinfo("ftp.ebi.ac.uk", 443)


def test_connecting_to_a_literal_address_is_blocked() -> None:
    """Skipping the resolver must not skip the guard."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkAccessError):
            sock.connect(("198.51.100.7", 443))
        with pytest.raises(NetworkAccessError):
            sock.connect_ex(("198.51.100.7", 443))
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# The guard permits
# ---------------------------------------------------------------------------


def test_loopback_still_works() -> None:
    """M4.3 binds a FastAPI app to localhost and M13.5 drives it.

    Not an incidental allowance: a guard that broke the local server would be deleted
    rather than narrowed the first time someone hit it.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client.settimeout(5)
        client.connect(server.getsockname())
        accepted, _ = server.accept()
        accepted.close()
    finally:
        client.close()
        server.close()


def test_localhost_resolves_by_name() -> None:
    assert socket.getaddrinfo("localhost", 0)


@pytest.mark.parametrize(
    ("host", "local"),
    [
        ("127.0.0.1", True),
        ("127.0.0.53", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),  # v4-mapped: IPv6Address.is_loopback says no
        ("0.0.0.0", True),  # the wildcard bind address, not a remote host
        ("localhost", True),
        ("LOCALHOST", True),
        ("api.localhost", True),
        (b"127.0.0.1", True),
        (None, True),
        ("93.184.216.34", False),
        ("ftp.ensembl.org", False),
        ("localhost.attacker.example", False),  # suffix, not the host
        ("", False),
        (1234, False),  # unrecognised shape: refuse rather than guess
    ],
)
def test_locality_classification(host: object, local: bool) -> None:
    assert is_local_address(host) is local


# ---------------------------------------------------------------------------
# The escape hatch
# ---------------------------------------------------------------------------


def test_guard_is_installed_by_default() -> None:
    """The flag *and* the patch.

    ``guard_is_active()`` alone would be satisfied by a bookkeeping variable set beside a
    ``block_network`` that patched nothing -- a check with one possible answer, which is
    the failure M0.6 and M1 each shipped once. Comparing the bound function catches that.
    """
    assert guard_is_active()
    assert socket.getaddrinfo is not _REAL_GETADDRINFO


@pytest.mark.network
def test_the_marker_lifts_the_guard() -> None:
    """Asserted by inspection rather than by connecting to something.

    Proving the hatch works by making a real connection would put actual traffic in the
    suite whose entire point is that it has none, and would fail on any machine that is
    genuinely offline.
    """
    assert not guard_is_active()
    assert socket.getaddrinfo is _REAL_GETADDRINFO
    assert "connect" not in socket.socket.__dict__


@pytest.mark.network
def test_teardown_removes_the_override_rather_than_rewriting_it() -> None:
    """``connect`` is *inherited* from ``_socket.socket``, not defined on ``socket.socket``.

    Restoring it by writing the original function back onto the subclass would leave a
    permanent override that behaves identically, looks identical from outside, and
    survives every later teardown -- so nothing downstream would ever notice. Only the
    ``__dict__`` membership distinguishes the two, which is what this asserts.

    Marked ``network`` to get an unguarded starting state; it opens no socket.
    """
    assert "connect" not in socket.socket.__dict__

    with block_network():
        assert socket.socket.__dict__["connect"] is _blocked_connect
        assert socket.getaddrinfo is not _REAL_GETADDRINFO

    assert "connect" not in socket.socket.__dict__
    assert "connect_ex" not in socket.socket.__dict__
    assert socket.getaddrinfo is _REAL_GETADDRINFO
