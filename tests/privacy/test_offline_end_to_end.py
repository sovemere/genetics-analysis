"""A full run with the network taken away by the operating system (roadmap M4.10).

M2.7 patches this process's ``socket`` module, and ``tests/conftest.py`` installs that for
the whole session. It is the right mechanism for imported code and it reaches nothing that
runs in a child: PLINK 2 arrives at M5, Java and Beagle at M8, R and HIBAG at M11, and a
wrapper that phoned home would do it entirely outside the guard's view while the suite
reported success. This file is the other half of that promise, and it is here rather than at
M15 because a guarantee should be enforced from the moment it is testable -- what made it
testable is M4.0, since the "full run" being asserted is ``genetics run``.

**The isolation is verified before anything is concluded from it.** An isolation that
silently does nothing makes every test built on it pass, which is worse than having none;
:func:`~genetics.testing.isolation.find_isolation` therefore proves the child cannot see
this machine's network interfaces before it hands one back, and refuses otherwise. That
proof costs no traffic: it asks the child what it can see rather than asking it to reach
something.

**Where there is no OS-level mechanism the tests skip, and say so in a sentence.** Windows
has no unprivileged way to take the network off a child process, so the guarantee is
genuinely weaker there and pretending otherwise would be the overclaim this project keeps
correcting. Setting ``GENETICS_REQUIRE_OS_ISOLATION`` turns that skip into a failure, and CI
sets it on the Linux job -- otherwise "skipped everywhere, forever" and "covered" look
identical from the outside.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from genetics.testing.isolation import Isolation, Unavailable, find_isolation

pytestmark = pytest.mark.privacy

REQUIRE_ENV = "GENETICS_REQUIRE_OS_ISOLATION"
"""Set on a platform that must provide isolation, so an unavailable mechanism fails."""

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "ancestry_v2_male.txt"

UNREACHABLE = ("192.0.2.1", 80)
"""TEST-NET-1 (RFC 5737): reserved for documentation and routed to nothing, anywhere.

Chosen so that even in the failure this test is looking for -- isolation that quietly did
not happen -- no real host is contacted. The assertion still distinguishes the two cases,
because the reserved address produces a *timeout* from a machine with a network and an
immediate no-route error from one without.
"""


@pytest.fixture(scope="module")
def isolation() -> Isolation:
    """OS-level network isolation, or a skip that explains itself."""
    found = find_isolation()
    if isinstance(found, Isolation):
        return found
    assert isinstance(found, Unavailable)
    if os.environ.get(REQUIRE_ENV):
        pytest.fail(
            f"{REQUIRE_ENV} is set, so this platform is expected to provide OS-level "
            f"network isolation, and it did not: {found.reason}"
        )
    pytest.skip(f"no OS-level network isolation on this machine: {found.reason}")


def _child(*args: str) -> list[str]:
    """Argv for ``genetics <args>`` in a fresh interpreter.

    ``-c`` rather than the console script because the script's location depends on how the
    package was installed, while ``sys.executable`` is the interpreter already running this
    suite and therefore the one the package is importable from.
    """
    return [sys.executable, "-c", "from genetics.cli.main import app; app()", *args]


def _child_python(source: str) -> list[str]:
    """Argv for a throwaway probe script in the same interpreter."""
    return [sys.executable, "-c", source]


# ---------------------------------------------------------------------------
# The mechanism, before anything is concluded from it
# ---------------------------------------------------------------------------


def test_the_isolated_child_sees_no_network_interface(isolation: Isolation) -> None:
    """The proof, restated here rather than left inside ``find_isolation``.

    ``find_isolation`` makes this check to decide what to return; this asserts it as a
    property of the thing every test below depends on, so the guarantee is visible in the
    file that relies on it rather than only in the helper that produces it.
    """
    probe = isolation.run(
        _child_python("import socket; print(sorted(n for _, n in socket.if_nameindex()))")
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() in ("['lo']", "[]"), (
        f"the child can still see {probe.stdout.strip()}, so it is not isolated"
    )


def test_nothing_is_routable_from_inside_the_isolation(isolation: Isolation) -> None:
    """The consequence, demonstrated rather than assumed.

    Safe to attempt only because the fixture already proved the namespace exists. The
    assertion is on *how* it fails: no route is what an isolated namespace produces, and a
    timeout is what a machine with a working network produces against a reserved address --
    so a check that merely asserted "the connection failed" would pass either way, which is
    the shape of check this project has twice had to fix (M0.6).
    """
    source = (
        "import socket, errno, sys\n"
        f"try:\n"
        f"    socket.create_connection({UNREACHABLE!r}, timeout=5)\n"
        "except OSError as exc:\n"
        "    print(errno.errorcode.get(exc.errno, type(exc).__name__))\n"
        "else:\n"
        "    print('CONNECTED')\n"
    )
    probe = isolation.run(_child_python(source))
    assert probe.returncode == 0, probe.stderr
    outcome = probe.stdout.strip()
    assert outcome in ("ENETUNREACH", "EHOSTUNREACH", "ENETDOWN"), (
        f"expected a no-route error from an isolated namespace, got {outcome!r}"
    )


# ---------------------------------------------------------------------------
# The milestone
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def offline_run(
    isolation: Isolation, tmp_path_factory: pytest.TempPathFactory
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """``genetics run`` executed once, with the network removed by the OS.

    Module-scoped because the assertions below are about one run seen from two angles -- did
    it finish, and did it show any sign of having wanted a network -- and running the whole
    pipeline twice to ask two questions about it would make the second answer describe a
    different run than the first.

    No references are fetched first, because at this milestone none are needed: the pipeline
    is pack-load, ingest, match, assemble, save, and the reference corpus feeds stages that
    do not exist yet. The roadmap's "once references are present" clause therefore has
    nothing to satisfy here, and M15.1 re-verifies this at full pipeline scope once it does.
    """
    data_dir = tmp_path_factory.mktemp("offline") / "data"
    completed = isolation.run(
        _child("run", "--input", str(FIXTURE), "--json"),
        env=os.environ | {"GENETICS_DATA_DIR": str(data_dir)},
        timeout=600,
    )
    return completed, data_dir


def test_a_full_run_completes_with_networking_disabled_at_the_os_level(
    offline_run: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    """``genetics run``, offline in the strong sense, start to finish."""
    result, data_dir = offline_run
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    # A run that parsed nothing and matched nothing would also exit zero. The point of the
    # test is that the analysis *happened* without a network, so it has to have produced
    # something -- otherwise this passes on a pipeline that quietly did no work.
    assert payload["qc"]["call_rates"]["total_markers"] > 0
    assert payload["cards"]["total"] > 0

    saved = Path(payload["path"])
    assert saved.is_dir(), "the bundle was reported saved and is not on disk"
    # Both sides resolved: `GENETICS_DATA_DIR` is resolved on the way in (`paths.py` has to,
    # to answer "is this inside the repo"), so the reported path is canonical while the one
    # built here is whatever the temp directory was called -- a short 8.3 name on Windows, a
    # symlinked /tmp elsewhere. Comparing them raw compares two spellings of one directory.
    assert saved.parent == (data_dir / "runs").resolve()


def test_the_run_leaves_no_trace_of_having_wanted_a_network(
    offline_run: tuple[subprocess.CompletedProcess[str], Path],
) -> None:
    """Success is not enough: a stage may swallow a failed request and carry on degraded.

    The failure this catches is a stage that tries to reach a reference online, fails, and
    falls back to something weaker while still exiting zero -- which is the same finished
    run to every other assertion here, and a different analysis. Stderr is where a swallowed
    connection error surfaces, so it is read rather than discarded.
    """
    result, _ = offline_run
    assert result.returncode == 0, result.stderr
    lowered = result.stderr.lower()
    for symptom in (
        "connection",
        "network is unreachable",
        "temporary failure in name",
        "urlopen",
        "max retries",
    ):
        assert symptom not in lowered, f"the run mentioned {symptom!r} on stderr:\n{result.stderr}"


# ---------------------------------------------------------------------------
# The helper's own refusals, which every platform can check
# ---------------------------------------------------------------------------


def test_isolation_that_did_not_isolate_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The most important branch in the helper, and the one no Linux run exercises.

    A machine where ``unshare`` exits zero and changes nothing would hand every test above a
    green tick for a guarantee that was never enforced. This drives that case directly, on
    whatever platform the suite happens to be running, because it is the failure that cannot
    be allowed to depend on having the right machine to notice it.
    """
    monkeypatch.setattr("genetics.testing.isolation.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        Isolation,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="['lo', 'eth0']\n", stderr=""
        ),
    )
    found = find_isolation()
    assert isinstance(found, Unavailable)
    assert "not isolated" in found.reason


def test_a_working_namespace_comes_back_with_the_flags_that_make_it_unprivileged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The success branch, exercised where the Linux runner is not.

    ``--map-root-user`` is the half that matters: without it ``--net`` needs privileges the
    account running the suite does not have, so dropping it would turn every run of this
    file into a skip on the one platform that can do the work.
    """
    monkeypatch.setattr("genetics.testing.isolation.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        Isolation,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="['lo']\n", stderr=""
        ),
    )
    found = find_isolation()
    assert isinstance(found, Isolation)
    assert "--net" in found.prefix
    assert "--map-root-user" in found.prefix


@pytest.mark.parametrize("system", ["Windows", "Darwin", "FreeBSD"])
def test_every_platform_without_a_mechanism_says_what_would_be_needed(
    system: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skip nobody can read is a skip nobody investigates.

    Parametrized over the platforms rather than asked of whichever one is running, because
    the first version of this test was ``if isinstance(found, Unavailable): assert ...`` --
    which asserts nothing at all on Linux, the one platform where the mechanism works and so
    the one place a regression in the *other* branches would go unnoticed until somebody
    tried to run the suite on a Mac.
    """
    monkeypatch.setattr("genetics.testing.isolation.platform.system", lambda: system)
    found = find_isolation()
    assert isinstance(found, Unavailable)
    assert len(found.reason) > 40, "the reason has to say what would be needed, not just no"
    assert system.lower() in found.reason.lower(), "the reason has to name the platform"


def test_a_kernel_that_refuses_the_namespace_is_reported_with_its_own_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distribution can ship ``unshare`` and forbid the call. The reason has to survive."""
    monkeypatch.setattr("genetics.testing.isolation.platform.system", lambda: "Linux")
    monkeypatch.setattr(
        Isolation,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="unshare: unshare failed: Operation not permitted\n",
        ),
    )
    found = find_isolation()
    assert isinstance(found, Unavailable)
    assert "Operation not permitted" in found.reason


def test_a_missing_unshare_is_reported_rather_than_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("genetics.testing.isolation.platform.system", lambda: "Linux")

    def missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory", "unshare")

    monkeypatch.setattr(Isolation, "run", missing)
    found = find_isolation()
    assert isinstance(found, Unavailable)
    assert "not installed" in found.reason


def test_the_unreachable_probe_target_is_reserved() -> None:
    """Guards the one constant here that could quietly become a real host."""
    import ipaddress

    address = ipaddress.ip_address(UNREACHABLE[0])
    assert not address.is_global, f"{address} is routable; a failed isolation would reach it"
    assert socket.inet_aton(UNREACHABLE[0])
