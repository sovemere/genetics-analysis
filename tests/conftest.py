"""Session-wide test configuration.

One rule is enforced here: **no test reaches the network** (roadmap M2.7). The mechanism
lives in :mod:`genetics.testing.network`, where ruff and strict mypy cover it and where
M4.10 can reuse it; this file only decides when it is installed.

The escape hatch is ``@pytest.mark.network``. There is nothing marked with it today --
the live verification of the fetcher in M2.2 and the tool installs in M2.5 were run by
hand, on purpose, because a suite that phones a real host is a suite that fails when the
host is down. The marker exists so that if such a test is ever written it has to say so in
its own source, rather than the guard being removed for everyone.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from genetics.testing.network import block_network


@pytest.fixture(autouse=True)
def _offline(request: pytest.FixtureRequest) -> Iterator[None]:
    if request.node.get_closest_marker("network") is not None:
        yield
        return
    with block_network():
        yield
