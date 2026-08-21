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

import os
import shutil
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from genetics.testing.network import allow_network, block_network

if TYPE_CHECKING:
    from genetics.engine.cards import KnowledgePack
    from genetics.engine.evidence import AssembledCard
    from genetics.external.plink2 import Plink2
    from genetics.qc.report import QCReport


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


@pytest.fixture(scope="session", autouse=True)
def _uncoloured_cli() -> Iterator[None]:
    """Make Typer's help and error output plain text, the same way everywhere.

    Roughly seventy assertions across ``tests/test_cli_*.py`` check for a substring of what
    a command printed. Rich decides per environment whether to emit colour, and when it does
    it splits a styled run wherever the highlighter's spans start -- ``--input`` comes out as
    ``ESC[1;36m-ESC[0mESC[1;36m-inputESC[0m``, which contains no ``--input`` at all.

    Rich treats a GitHub Actions runner as colour-capable even with no TTY attached, so every
    one of those assertions was passing locally and only ever at risk on CI; ``run --help``
    was the first to actually name an option and the first to break. ``TERM=dumb`` is what
    Rich looks at last and overrides the CI detection, so this pins the output format rather
    than teaching each assertion to strip escape codes.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("TERM", "dumb")
        patch.delenv("FORCE_COLOR", raising=False)
        yield


# ---------------------------------------------------------------------------
# Building a saved run (M4.1/M4.2)
# ---------------------------------------------------------------------------
#
# Shared because ``tests/run/test_store.py`` and ``tests/test_cli_runs.py`` both need a
# bundle on disk and neither is testing how one is built. ``tests/run/test_bundle.py``
# keeps its own, richer card fixtures on purpose: it is testing the *format*, so the
# genotypes it writes and the rare card carrying an empirical PPV are the subject matter
# there rather than scaffolding.

SYNTHETIC_EXPORT = Path(__file__).parent / "fixtures" / "synthetic" / "ancestry_v2_male.txt"
SYNTHETIC_CARDS = Path(__file__).parent / "fixtures" / "cards"
SAMPLE_GENOTYPE = "AG"


@pytest.fixture
def sample_genotype() -> str:
    """The call ``sample_cards`` writes, as a fixture rather than an import.

    ``tests/`` is not a package, so a test in another directory cannot import the constant;
    and a test that recovered it from the bundle it is checking would be asserting that the
    output contains the output.
    """
    return SAMPLE_GENOTYPE


@pytest.fixture(scope="session")
def sample_qc() -> QCReport:
    """A real QC report from a real parse. Session-scoped: it is read-only and identical."""
    # Imported here rather than at module scope so a run of the fast unit tests does not
    # pay for Polars and the whole ingest stack during collection.
    from genetics.ingest import ingest

    return ingest(SYNTHETIC_EXPORT).qc


@pytest.fixture
def sample_pack(tmp_path: Path) -> KnowledgePack:
    """A private copy of the synthetic card pack.

    Copied rather than loaded in place because ``knowledge_provenance`` digests the files
    on disk, and a test that edits or deletes the pack must not reach the committed one.
    """
    from genetics.engine.cards import KnowledgePack

    destination = tmp_path / "knowledge"
    shutil.copytree(SYNTHETIC_CARDS, destination)
    return KnowledgePack.load(destination)


@pytest.fixture
def sample_cards(sample_pack: KnowledgePack) -> tuple[AssembledCard, ...]:
    """One matched card, so a bundle has something with a genotype and a citation in it."""
    from genetics.engine.confidence import CallSource
    from genetics.engine.evidence import ObservationEvidence, PopulationFrequency, assemble_card
    from genetics.engine.matcher import MatchResult, MatchStatus, Strand

    card = sample_pack.by_id("synthetic_dominant_trait")
    assert card is not None and card.match is not None
    outcome_name = next(iter(card.match.genotypes.values()))
    match = MatchResult(
        card_id=card.id,
        status=MatchStatus.MATCHED,
        reason="Matched.",
        genotype=SAMPLE_GENOTYPE,
        observed_genotype=SAMPLE_GENOTYPE,
        observed_rsid=card.match.variant.rsid,
        outcome_name=outcome_name,
        outcome=card.outcomes[outcome_name],
        strand=Strand.AS_WRITTEN,
    )
    return (
        assemble_card(
            card,
            match,
            ObservationEvidence(
                call_source=CallSource.DIRECT,
                frequencies=(
                    PopulationFrequency("A", 0.80, "EUR", "synthetic-reference-v1"),
                    PopulationFrequency("G", 0.20, "EUR", "synthetic-reference-v1"),
                ),
                ancestry_match=1.0,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# A stand-in for PLINK 2 (M5.1/M5.2)
# ---------------------------------------------------------------------------
#
# CI installs no external tools -- the workflow runs on synthetic fixtures and fetches
# nothing -- so a test that reached for the real binary would skip on every runner, which
# M4.10 already established is indistinguishable from a test that does not exist. The stub
# is a *real subprocess*: argument passing, exit codes, stream capture and the log file are
# all exercised, and only the program at the far end is fake.
#
# Shared here, beside the run-bundle fixtures and for the same reason: `tests/external/
# test_plink2.py` and `tests/external/test_pgen.py` both need a stub and neither is testing
# how one is built. It cannot live in a `tests/external/conftest.py`, because `tests/` is
# not a package and mypy then sees two modules named `conftest`.

PINNED_PLINK2_VERSION = "PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)"
"""What the build pinned in ``data/tools.yaml`` prints.

Test modules that assert on the version string keep their own copy: one derived from the
same place the code reads would pass no matter what either said.
"""


def write_plink2_stub(directory: Path, body: str) -> Path:
    """Write a runnable stand-in for ``plink2`` that executes ``body`` as Python.

    A launcher rather than the script itself, because a ``.py`` file is not executable on
    Windows and Windows is this project's primary platform (AGENTS.md 4.9). Both forms
    forward every argument and propagate the exit code, which the tests rely on.
    """
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "stub_plink2.py"
    script.write_text(body, encoding="utf-8")
    script_lines: tuple[str, ...]
    if os.name == "nt":
        launcher = directory / "plink2.cmd"
        script_lines = ("@echo off", f'"{sys.executable}" "{script}" %*', "exit /b %ERRORLEVEL%")
        launcher.write_text("\r\n".join(script_lines) + "\r\n", encoding="utf-8")
    else:
        launcher = directory / "plink2"
        script_lines = ("#!/bin/sh", f'exec "{sys.executable}" "{script}" "$@"')
        launcher.write_text("\n".join(script_lines) + "\n", encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


@pytest.fixture
def stub_binary(tmp_path: Path) -> Callable[[str], Path]:
    """The stub as a bare path, for tests that drive discovery rather than invocation."""
    made: list[Path] = []

    def build(body: str) -> Path:
        directory = tmp_path / f"tool{len(made)}"
        made.append(directory)
        return write_plink2_stub(directory, body)

    return build


@pytest.fixture
def stub_plink2(tmp_path: Path) -> Callable[[str], Plink2]:
    """Build a :class:`~genetics.external.plink2.Plink2` around a stub, skipping discovery.

    The dataclass is a plain record on purpose so this is possible; see its docstring. Each
    call gets its own directory so a test may hold two stubs at once.
    """
    from genetics.external.plink2 import Plink2

    made: list[Path] = []

    def build(body: str) -> Plink2:
        directory = tmp_path / f"bin{len(made)}"
        made.append(directory)
        return Plink2(path=write_plink2_stub(directory, body), version=PINNED_PLINK2_VERSION)

    return build


@pytest.fixture
def installed_plink2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Path]:
    """Install a stub where ``Plink2.discover()`` will find it, and point the app at it.

    For code that discovers PLINK itself rather than being handed one -- the M5.3 transform
    runs inside ``genetics.refs.postprocess``, which has no seam to inject a binary through
    and should not grow one just for tests. Writes the installed-state record the real
    installer writes, under a ``GENETICS_DATA_DIR`` outside the checkout.
    """

    def build(body: str) -> Path:
        from genetics.refs import tools

        data_dir = tmp_path / "appdata"
        tools_root = data_dir / "tools"
        tools_root.mkdir(parents=True, exist_ok=True)
        binary = write_plink2_stub(tmp_path / "stub", body)
        (tools_root / tools.INSTALLED_STATE).write_text(
            tools.render_state({"plink2": {"path": str(binary), "version": PINNED_PLINK2_VERSION}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("GENETICS_DATA_DIR", str(data_dir))
        return binary

    return build
