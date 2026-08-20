"""The analysis pipeline (roadmap M4.0).

What is being tested here is the *composition*: ingest, matching, assembly and the bundle
writer each have their own suite already, and re-asserting their behaviour through this
seam would be a second, weaker copy of those. What only this module can be wrong about is
the observation layer it decides, the order it applies the stages in, and the promise that
:func:`analyse` writes nothing.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from genetics.engine.cards import CardKind, KnowledgePack
from genetics.engine.confidence import CallSource
from genetics.engine.evidence import EvidenceAssemblyError, assemble_pack
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.paths import runs_dir
from genetics.run.bundle import read_bundle
from genetics.run.pipeline import analyse, observations, save
from genetics.testing.fixtures import FIXTURES, render_fixture

SYNTHETIC_CARDS = Path(__file__).parents[1] / "fixtures" / "cards"

# The two markers the fixture card pack declares, with genotypes chosen to land on a named
# outcome in each: AG -> "present" on the autosomal card, TT -> "derived" on the Y-linked
# one. Spelled out here rather than read back off the pack, so a test that says "matched"
# is asserting against a genotype this file chose.
SPIKED_GENOTYPE = "AG"
SPIKE_INS = {
    "rs900000001": (7, 12345678, "A", "G"),
    "rs900000002": (24, 2655180, "T", "T"),
}


@pytest.fixture
def store_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at a scratch directory the way a user would (M4.2: no flag)."""
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    root = runs_dir()
    root.mkdir(parents=True)
    return root


@pytest.fixture
def export(tmp_path: Path) -> Path:
    """A synthetic export carrying the markers the fixture card pack asks about.

    Rendered rather than committed: the committed fixtures deliberately carry no spike-ins
    (``genetics.testing.fixtures`` leaves them empty rather than invent GRCh37 coordinates),
    so nothing in ``tests/fixtures/synthetic`` can produce a matched card. Without this the
    pipeline suite could only ever prove that nothing matched, which is exactly the state a
    broken matcher also produces.
    """
    base = next(spec for spec in FIXTURES if spec.name == "ancestry_v2_male.txt")
    path = tmp_path / "spiked.txt"
    path.write_text(
        render_fixture(replace(base, spike_ins=SPIKE_INS)), encoding="utf-8", newline="\n"
    )
    return path


@pytest.fixture
def plain_export() -> Path:
    """A committed fixture, which by construction matches none of the pack's markers."""
    return Path(__file__).parents[1] / "fixtures" / "synthetic" / "ancestry_v2_male.txt"


# ---------------------------------------------------------------------------
# The observation layer -- the only thing this module actually decides
# ---------------------------------------------------------------------------


def test_observations_cover_every_interpretation_card_and_no_impossibility_card() -> None:
    """The split ``assemble_card`` enforces from the other side.

    An interpretation card without an observation is refused; an impossibility card *with*
    one is also refused. Covering both directions here means a change to either rule fails
    a test that names it, rather than surfacing as a pipeline that cannot assemble.
    """
    pack = KnowledgePack.load(SYNTHETIC_CARDS)
    supplied = observations(pack)

    interpretation = {c.id for c in pack.cards if c.kind is not CardKind.IMPOSSIBILITY}
    impossibility = {c.id for c in pack.cards if c.kind is CardKind.IMPOSSIBILITY}

    assert interpretation, "the fixture pack must contain an interpretation card"
    assert impossibility, "the fixture pack must contain an impossibility card"
    assert set(supplied) == interpretation
    assert not (set(supplied) & impossibility)


def test_every_observation_is_a_direct_call_with_no_imputation_quality() -> None:
    """The M4-era claim, pinned so M8 has to change it deliberately.

    There is no imputation stage yet, so no genotype in a run can have been imputed. When
    M8 adds one this test fails, which is the point: the constant lives in one place and
    the test that describes it names the milestone that will replace it.
    """
    pack = KnowledgePack.load(SYNTHETIC_CARDS)
    for card_id, observation in observations(pack).items():
        assert observation.call_source is CallSource.DIRECT, card_id
        assert observation.imputation_quality is None, card_id
        assert observation.ancestry_match is None, card_id
        assert observation.frequencies == (), card_id


def test_assembly_refuses_without_the_observations_this_module_supplies(
    plain_export: Path,
) -> None:
    """Why :func:`observations` exists at all.

    If ``assemble_pack`` ever grows a default, this test passes while the pipeline starts
    scoring imputed observations as perfect calls -- so it asserts the refusal itself, not
    just that the pipeline works.
    """
    from genetics.ingest import ingest

    pack = KnowledgePack.load(SYNTHETIC_CARDS)
    matches = match_pack(pack, ingest(plain_export).table)

    with pytest.raises(EvidenceAssemblyError, match="requires ObservationEvidence"):
        assemble_pack(pack, matches)


def test_an_absent_marker_still_records_that_it_was_not_imputed(plain_export: Path) -> None:
    """The distinction M4.1 added ``observation`` to the bundle to preserve.

    A card whose marker is not on the array has no confidence, so without the observation a
    saved run cannot tell "not on this array" from "imputation was attempted and failed".
    """
    analysis = analyse(plain_export, knowledge_dir=SYNTHETIC_CARDS)
    absent = [c for c in analysis.cards if c.status is MatchStatus.MARKER_ABSENT]

    assert absent, "the committed fixture carries none of the pack's markers"
    for card in absent:
        assert card.confidence is None
        assert card.observation is not None
        assert card.observation.call_source is CallSource.DIRECT


# ---------------------------------------------------------------------------
# analyse
# ---------------------------------------------------------------------------


def test_analyse_returns_one_card_per_pack_card_in_pack_order(export: Path) -> None:
    """No filtering, at any stage (AGENTS.md 0.1A).

    A caller that receives fewer cards than the pack has no way to reconstruct which went
    missing or why, so "did not match" would be indistinguishable from "was dropped".
    """
    pack = KnowledgePack.load(SYNTHETIC_CARDS)
    analysis = analyse(export, knowledge_dir=SYNTHETIC_CARDS)

    assert [c.card_id for c in analysis.cards] == [c.id for c in pack.cards]
    assert [m.card_id for m in analysis.matches] == [c.id for c in pack.cards]


def test_analyse_produces_a_real_interpretation(export: Path) -> None:
    """The slice, end to end: a genotype on the array becomes a rendered card.

    Everything else in this file can pass against a pipeline that matches nothing, because
    "nothing matched" is a legitimate result. This is the test that fails if the stages are
    composed in a way that never reaches an outcome.
    """
    analysis = analyse(export, knowledge_dir=SYNTHETIC_CARDS)
    matched = {c.card_id: c for c in analysis.cards if c.status is MatchStatus.MATCHED}

    assert set(matched) == {"synthetic_dominant_trait", "synthetic_haploid_marker"}
    assert analysis.with_interpretation == 2

    card = matched["synthetic_dominant_trait"]
    assert SPIKED_GENOTYPE in card.summary, "the outcome template should be rendered"
    assert card.confidence is not None
    assert card.citations, "a rendered interpretation carries its citations"


def test_confidence_records_the_two_inputs_this_milestone_cannot_supply(
    export: Path,
) -> None:
    """The visible cost of the M4 observation layer, asserted rather than assumed.

    No frequency reference is wired in (M2's extracts) and no ancestry fit exists (M5), so
    both score the neutral 0.5 rather than a value anyone measured. What matters is that
    the breakdown says ``None`` for each: a saved run has to be readable as "these were not
    known", not as "these were known and average". Note this is *not* a cap -- a neutral
    contribution can still be beaten upward by strong evidence -- so the assertion is on
    the recorded inputs, which are the honest claim, and not on the tier they produce.
    """
    analysis = analyse(export, knowledge_dir=SYNTHETIC_CARDS)
    card = next(c for c in analysis.cards if c.card_id == "synthetic_dominant_trait")

    assert card.confidence is not None
    assert card.confidence.inputs.population_allele_frequency is None
    assert card.confidence.inputs.ancestry_match is None
    assert card.confidence.inputs.frequency_score == 0.5
    assert card.confidence.inputs.ancestry_score == 0.5
    assert card.confidence_frequency is None
    assert card.frequencies == ()


def test_a_broken_knowledge_pack_is_reported_before_the_export_is_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordering, asserted rather than left to read off the source.

    `KnowledgePack.load` parses a handful of YAML files; `ingest` parses 677,000 rows. With
    the stages the other way round, a typo in a card file is reported after a full parse of
    somebody's genome -- the slowest way to learn about the cheapest mistake, and card
    authoring is exactly when it gets made.
    """
    from genetics.engine.cards import CardError
    from genetics.run import pipeline

    def refuse(_: Path) -> None:
        raise AssertionError("the export was parsed before the knowledge pack was loaded")

    monkeypatch.setattr(pipeline, "ingest", refuse)
    with pytest.raises(CardError):
        analyse(tmp_path / "absent-export.txt", knowledge_dir=tmp_path / "absent-pack")


def test_analyse_writes_nothing(export: Path, store_root: Path) -> None:
    """The reason :func:`analyse` and :func:`save` are two functions.

    M4.10 runs the pipeline with networking disabled and any future ``--dry-run`` wants the
    result without a bundle; both need analysis to be free of side effects.
    """
    analyse(export, knowledge_dir=SYNTHETIC_CARDS)
    assert list(store_root.iterdir()) == []


def test_analyse_reports_which_sections_have_no_cards(export: Path) -> None:
    """No silent empty sections: the pack knows, so the pipeline's caller can be told."""
    analysis = analyse(export, knowledge_dir=SYNTHETIC_CARDS)
    covered = {c.section for c in analysis.cards}

    assert covered.isdisjoint(analysis.pack.empty_sections)
    assert analysis.pack.empty_sections, "the fixture pack covers two sections of thirteen"


def test_status_and_tier_counts_keep_their_zeros(export: Path) -> None:
    """A status that vanishes when empty makes "none" look like "not checked"."""
    analysis = analyse(export, knowledge_dir=SYNTHETIC_CARDS)

    assert set(analysis.status_counts) == set(MatchStatus)
    assert analysis.status_counts[MatchStatus.MATCHED] == 2
    assert analysis.status_counts[MatchStatus.NO_CALL] == 0
    assert sum(analysis.tier_counts.values()) == analysis.with_interpretation


def test_the_analysis_repr_does_not_carry_a_genotype(export: Path) -> None:
    """It holds every assembled card, so the default dataclass repr would print calls."""
    analysis = analyse(export, knowledge_dir=SYNTHETIC_CARDS)
    text = repr(analysis)

    assert SPIKED_GENOTYPE not in text
    assert "ancestrydna_v2" in text


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


def test_save_round_trips_what_was_analysed(export: Path, store_root: Path) -> None:
    """What a reader gets back months later is what this run produced."""
    analysis = analyse(export, knowledge_dir=SYNTHETIC_CARDS)
    path = save(analysis)
    bundle = read_bundle(path)

    assert [c.card_id for c in bundle.cards] == [c.card_id for c in analysis.cards]
    assert bundle.provenance["input"]["vendor"] == analysis.source.vendor

    stored = next(c for c in bundle.cards if c.card_id == "synthetic_dominant_trait")
    assert stored.status == MatchStatus.MATCHED.value
    assert SPIKED_GENOTYPE in stored.summary
    assert stored.observation is not None
    assert stored.observation["call_source"] == CallSource.DIRECT.value


def test_two_runs_of_the_same_export_get_two_ids(export: Path, store_root: Path) -> None:
    """Immutability is refusal, not overwrite: re-running never rewrites a saved run."""
    analysis = analyse(export, knowledge_dir=SYNTHETIC_CARDS)
    first = save(analysis)
    second = save(analysis)

    assert first != second
    assert first.exists() and second.exists()
