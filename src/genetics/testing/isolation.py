"""Running a command with the network disabled by the operating system (roadmap M4.10).

:mod:`genetics.testing.network` (M2.7) patches *this* process's ``socket`` module. That is
the right mechanism for the code the suite imports and it has no reach whatsoever into a
subprocess -- PLINK 2 at M5, Java and Beagle at M8, R and HIBAG at M11. A wrapper that
phoned home would run entirely outside the guard's view and the suite would report success.
This module is the other half: it does not patch anything, it takes the network away from a
child process and everything that child starts.

**Availability is probed, never assumed, and the first CI run proved why.** The mechanism is
a Linux network namespace, and whether an unprivileged process may create one is a
per-machine question. GitHub's ``ubuntu-latest`` is Ubuntu 24.04, which restricts
unprivileged user namespaces through AppArmor: ``unshare --map-root-user --net`` gets far
enough to create the namespace and is then refused the uid mapping --
``unshare: write failed /proc/self/uid_map: Operation not permitted``. A detector that
checked ``PATH`` for ``unshare`` would have called that machine capable. So
:func:`find_isolation` runs a real probe against each candidate in :data:`_CANDIDATES` and
reports what actually happened; a caller that cannot get isolation is told why, in a
sentence, because the alternative is a test that skips for a reason nobody can see.

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

import json
import os
import platform
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = ["Isolation", "Unavailable", "find_isolation"]

PROBE_TIMEOUT = 60
"""Seconds. Generous: the probe starts a Python interpreter under ``unshare``, and a cold
CI runner is slower than it looks."""

_PROBE_TOKEN_ENV = "GENETICS_ISOLATION_PROBE"
"""Set to a known value for the probe, and required back from the child. See :func:`_probe`."""

_PROBE = (
    "import json, os, socket; "
    "print(json.dumps({"
    '"interfaces": sorted(name for _, name in socket.if_nameindex()), '
    f'"token": os.environ.get("{_PROBE_TOKEN_ENV}")'
    "}))"
)
"""What the child is asked, and it is asked two things rather than one.

The interfaces answer whether the network is gone: a fresh namespace has loopback and
nothing else. The token answers whether the *environment* survived the trip, which stopped
being a silly question the moment a ``sudo`` prefix became one of the candidates -- ``sudo``
resets the environment by default, and a mechanism that isolates the network while quietly
dropping ``GENETICS_DATA_DIR`` would run the pipeline against the wrong store and pass.
Both are asked in one child so neither can be answered by a different process than the other.
"""


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


_CANDIDATES: tuple[tuple[tuple[str, ...], str], ...] = (
    # First choice, and the only one that needs no privileges at all. ``--map-root-user``
    # creates a user namespace in which this account is root, which is how an ordinary user
    # is allowed to create the network namespace ``--net`` asks for.
    (
        ("unshare", "--map-root-user", "--net", "--"),
        "Linux network namespace (unshare --map-root-user --net)",
    ),
    # Second choice, and it exists because the first one does not work on the machine this
    # guarantee most needs to hold: **GitHub's ubuntu-latest refuses it**. Ubuntu 24.04
    # restricts unprivileged user namespaces through AppArmor, so the namespace is created
    # and then the uid mapping is denied -- `unshare: write failed /proc/self/uid_map:
    # Operation not permitted`, which is what CI reported on the first run of M4.10.
    #
    # ``-n`` is what keeps this from being a surprise: it makes sudo fail immediately rather
    # than prompt, so on a machine without passwordless sudo this costs one failed exec and
    # nothing else. ``-E`` is what keeps the child's environment, and the probe checks that
    # it actually did rather than trusting the flag. It is still only tried when the caller
    # says isolation is required here -- see :func:`find_isolation`.
    (
        ("sudo", "-n", "-E", "unshare", "--net", "--"),
        "Linux network namespace via passwordless sudo (sudo -n -E unshare --net)",
    ),
)


def find_isolation(*, allow_sudo: bool = False) -> Isolation | Unavailable:
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

    failures: list[str] = []
    for prefix, description in _CANDIDATES:
        if prefix[0] == "sudo" and not allow_sudo:
            # Escalation is never a silent default. Tied to the caller's "isolation is
            # required here" rather than tried opportunistically, so a developer running the
            # suite on a laptop with cached sudo credentials does not have part of it
            # quietly run as root; CI, which sets that flag, gets the real coverage.
            failures.append("passwordless sudo not attempted (isolation was not required here)")
            continue
        candidate = Isolation(prefix=prefix, description=description)
        verdict = _verify(candidate)
        if verdict is None:
            return candidate
        failures.append(f"{prefix[0]} -- {verdict}")
    return Unavailable("no working network namespace: " + "; ".join(failures))


def _verify(candidate: Isolation) -> str | None:
    """``None`` if ``candidate`` really isolates a child, else why it does not.

    Every branch here is a way for a mechanism to look like it worked. The command can be
    missing, the kernel can refuse it, it can exit zero having changed nothing, and -- once
    ``sudo`` is a candidate -- it can isolate the network while dropping the environment the
    caller needs. A mechanism that fails any of these is refused rather than returned,
    because an isolation that does nothing makes every test built on it pass.
    """
    token = uuid.uuid4().hex
    try:
        probe = candidate.run(
            [sys.executable, "-c", _PROBE],
            env={**os.environ, _PROBE_TOKEN_ENV: token},
        )
    except FileNotFoundError:
        return f"`{candidate.prefix[0]}` is not installed"
    except subprocess.TimeoutExpired:
        return f"no answer within {PROBE_TIMEOUT}s"

    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip().splitlines()
        return detail[-1] if detail else f"exit {probe.returncode}"

    try:
        answer = json.loads(probe.stdout)
    except json.JSONDecodeError:
        return f"unreadable probe output {probe.stdout.strip()[:80]!r}"

    interfaces = answer.get("interfaces")
    if interfaces not in ([], ["lo"]):
        return f"reported success but the child still sees {interfaces}, so it was not isolated"
    if answer.get("token") != token:
        return "isolated the network but did not pass the environment through"
    return None
