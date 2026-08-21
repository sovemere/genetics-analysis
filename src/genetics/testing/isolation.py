"""Running a command with the network disabled by the operating system (roadmap M4.10).

:mod:`genetics.testing.network` (M2.7) patches *this* process's ``socket`` module. That is
the right mechanism for the code the suite imports and it has no reach whatsoever into a
subprocess -- PLINK 2 at M5, Java and Beagle at M8, R and HIBAG at M11. A wrapper that
phoned home would run entirely outside the guard's view and the suite would report success.
This module is the other half: it does not patch anything, it takes the network away from a
child process and everything that child starts.

**Availability is probed, never assumed.** The mechanism is a Linux network namespace, and
whether an unprivileged process may create one is a per-machine question -- a distribution
can forbid unprivileged user namespaces outright. So :func:`find_isolation` runs a real
probe and reports what happened rather than testing ``unshare`` for existence and hoping.
A caller that cannot get isolation is told why, in a sentence, because the alternative is a
test that skips for a reason nobody can see.

**Nothing here sends a packet, in either direction.** Proving isolation by connecting
somewhere and failing would send real traffic on any machine where the isolation silently
did nothing -- which is precisely the machine the probe exists to detect. The probe instead
asks the child which network interfaces it can see: inside a fresh namespace that is
loopback and nothing else, and the answer arrives without a single byte leaving.

There is no Windows equivalent, and that is a limitation rather than an oversight. Every
OS-level mechanism Windows offers for this -- a firewall rule, a Hyper-V sandbox -- needs
administrator rights, and a check that only runs for administrators is a check that does not
run. On Windows the in-process guard is what covers this, and it covers less; see the
roadmap entry.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = ["Isolation", "Unavailable", "find_isolation"]

PROBE_TIMEOUT = 60
"""Seconds. Generous: the probe starts a Python interpreter under ``unshare``, and a cold
CI runner is slower than it looks."""

_INTERFACE_PROBE = "import socket; print(sorted(name for _, name in socket.if_nameindex()))"
"""What the child is asked. A fresh network namespace has loopback and nothing else."""


@dataclass(frozen=True)
class Isolation:
    """A command prefix that runs anything with no network, and a name for what it is."""

    prefix: tuple[str, ...]
    description: str

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: int = PROBE_TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``argv`` with the network removed. Never raises on a non-zero exit."""
        return subprocess.run(
            [*self.prefix, *argv],
            capture_output=True,
            text=True,
            env=dict(env) if env is not None else None,
            timeout=timeout,
            check=False,
        )


@dataclass(frozen=True)
class Unavailable:
    """No OS-level isolation on this machine, and the sentence explaining that."""

    reason: str


# ``--map-root-user`` is what makes this work without privileges: it creates a user
# namespace in which this user is root, which is the only way an ordinary account is allowed
# to create the network namespace ``--net`` asks for.
_UNSHARE = ("unshare", "--map-root-user", "--net", "--")


def find_isolation() -> Isolation | Unavailable:
    """The OS-level network isolation available here, or why there is none.

    Probed rather than detected. ``unshare`` being on ``PATH`` says nothing about whether
    this account may use it -- a distribution that disables unprivileged user namespaces
    ships the binary and refuses the call -- and the difference between those two states is
    the difference between a guarantee and a test that quietly proves nothing.
    """
    # `platform.system()` rather than `sys.platform`, for the reason `refs.tools` records:
    # mypy narrows `sys.platform` to whichever machine it is running on, so the branches for
    # the other operating systems come out as unreachable under `warn_unreachable` and stop
    # being type-checked. Comparing a plain string keeps all three live on both CI runners.
    system = platform.system().lower()
    if system == "windows":
        return Unavailable(
            "Windows has no way for a non-administrator to take the network away from a "
            "child process: a firewall rule and a Hyper-V sandbox both need elevation, and "
            "a check that runs only for administrators does not run. The in-process guard "
            "(M2.7) is what covers this platform, and it cannot see a subprocess."
        )
    if system != "linux":
        return Unavailable(
            f"no OS-level network isolation is implemented for {system!r}. Linux network "
            "namespaces are the mechanism here; macOS has no unprivileged equivalent."
        )

    candidate = Isolation(prefix=_UNSHARE, description="Linux network namespace (unshare --net)")
    try:
        probe = candidate.run([sys.executable, "-c", _INTERFACE_PROBE])
    except FileNotFoundError:
        return Unavailable("`unshare` is not installed, so no network namespace can be created.")
    except subprocess.TimeoutExpired:
        return Unavailable(f"`unshare` did not answer within {PROBE_TIMEOUT}s.")

    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip().splitlines()
        return Unavailable(
            "`unshare --map-root-user --net` was refused by this kernel, which usually "
            "means unprivileged user namespaces are disabled: "
            + (detail[-1] if detail else f"exit {probe.returncode}")
        )

    interfaces = probe.stdout.strip()
    if interfaces not in ("['lo']", "[]"):
        # The command succeeded and the child could still see the machine's real interfaces,
        # so whatever ran was not isolated. Reported rather than returned: an isolation that
        # does nothing is worse than none, because it makes every test built on it pass.
        return Unavailable(
            "`unshare --net` reported success but the child still sees "
            f"{interfaces or '<nothing printed>'}, so it was not isolated."
        )
    return candidate
