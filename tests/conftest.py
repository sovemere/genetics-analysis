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

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from genetics.testing.network import allow_network, block_network

if TYPE_CHECKING:
    from genetics.engine.cards import KnowledgePack
    from genetics.engine.evidence import AssembledCard
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
