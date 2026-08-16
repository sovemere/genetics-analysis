"""Session-wide test configuration.

One rule is enforced here: **no test reaches the network** (roadmap M2.7). The mechanism
lives in :mod:`genetics.testing.network`, where ruff and strict mypy cover it and where
M4.10 can reuse it; this file only decides when it is installed.

**Installed at session scope, lifted per test.** The first cut installed it per test, which
review showed was a real hole: pytest builds higher-scoped fixtures *before* function-scoped
ones, so a session- or module-scoped fixture ran with no guard at all -- and a module-scoped
"fetch the reference once" fixture is the most natural home a stray network call could find.
Verified empirically before fixing: ``guard_is_active()`` returned False inside both a
session- and a module-scoped fixture while returning True in the test body.

The escape hatch is ``@pytest.mark.network``, which lifts the block for that test only.
There is nothing marked with it today except the guard's own tests -- the live verification
of the fetcher in M2.2 and the tool installs in M2.5 were run by hand, on purpose, because
a suite that phones a real host is a suite that fails when the host is down. The marker
exists so that if such a test is ever written it has to say so in its own source, rather
than the guard being removed for everyone.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from genetics.testing.network import allow_network, block_network


@pytest.fixture(scope="session", autouse=True)
def _offline_session() -> Iterator[None]:
    """Covers fixture setup at every scope, not only test bodies."""
    with block_network():
        yield


@pytest.fixture(autouse=True)
def _offline(request: pytest.FixtureRequest) -> Iterator[None]:
    if request.node.get_closest_marker("network") is None:
        yield
        return
    with allow_network():
        yield
