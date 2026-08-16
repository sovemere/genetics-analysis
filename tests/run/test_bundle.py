"""The run bundle format (roadmap M4.1).

Organised by the property each test defends. The format's job is to still be readable and
still say the same thing after the code that wrote it has moved on, so most of these
tests change something *after* the write and check that the bundle did not follow.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from genetics.engine.cards import CardKind, KnowledgePack
from genetics.engine.confidence import CallSource
from genetics.engine.evidence import (
    AssembledCard,
    ObservationEvidence,
    PopulationFrequency,
    assemble_card,
)
from genetics.engine.matcher import MatchResult, MatchStatus, Strand
from genetics.ingest import ingest
from genetics.paths import UnsafeDataDirError, repo_root
from genetics.privacy import find_genotypes
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    CARD_KEYS,
    CARDS_NAME,
    INCOMING_PREFIX,
    MANIFEST_KEYS,
    MANIFEST_NAME,
    QC_NAME,
    BundleError,
    BundleIntegrityError,
    BundleVersionError,
    knowledge_provenance,
    new_run_id,
    read_bundle,
    write_bundle,
)

CARD_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cards"
EXPORT = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "ancestry_v2_male.txt"

OBSERVED_GENOTYPE = "AG"


@pytest.fixture(scope="module")
def qc_report() -> QCReport:
    """A real QC report, from a real parse of a synthetic export."""
    return ingest(EXPORT).qc


@pytest.fixture
def pack_dir(tmp_path: Path) -> Path:
    """A private copy of the synthetic card pack, so a test may edit it after a write."""
    destination = tmp_path / "knowledge"
    shutil.copytree(CARD_FIXTURES, destination)
    return destination


def _matched(pack: KnowledgePack, card_id: str) -> AssembledCard:
    card = pack.by_id(card_id)
    assert card is not None and card.match is not None
    outcome_name = next(iter(card.match.genotypes.values()))
    match = MatchResult(
        card_id=card.id,
        status=MatchStatus.MATCHED,
        reason="Matched.",
        genotype=OBSERVED_GENOTYPE,
        observed_genotype=OBSERVED_GENOTYPE,
        observed_rsid=card.match.variant.rsid,
        outcome_name=outcome_name,
        outcome=card.outcomes[outcome_name],
        strand=Strand.AS_WRITTEN,
        caveats=("Synthetic computed caveat.",),
    )
    return assemble_card(
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
    )


def _impossible(pack: KnowledgePack, card_id: str) -> AssembledCard:
    card = pack.by_id(card_id)
    assert card is not None
    return assemble_card(
        card,
        MatchResult(
            card_id=card.id,
            status=MatchStatus.NOT_DETERMINABLE,
            reason="Not determinable from array genotypes.",
        ),
    )


@pytest.fixture
def cards(pack_dir: Path) -> tuple[KnowledgePack, tuple[AssembledCard, ...]]:
    pack = KnowledgePack.load(pack_dir)
    return pack, (
        _matched(pack, "synthetic_dominant_trait"),
        _impossible(pack, "synthetic_impossibility"),
    )


@pytest.fixture
def written(
    tmp_path: Path,
    qc_report: QCReport,
    cards: tuple[KnowledgePack, tuple[AssembledCard, ...]],
) -> Path:
    pack, assembled = cards
    return write_bundle(
        qc=qc_report,
        cards=assembled,
        pack=pack,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )


def _repack(directory: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    """Edit ``cards.json`` *and* refresh its recorded digest.

    Without the refresh every payload test would fail on the digest check and prove only
    that the digest check works. Refreshing it is what lets a test reach the schema
    checks behind it, and demonstrates the two guards are independent.
    """
    cards_path = directory / CARDS_NAME
    payload = json.loads(cards_path.read_text(encoding="utf-8"))
    mutate(payload)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with cards_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)

    manifest_path = directory / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][CARDS_NAME] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# What a bundle records
# ---------------------------------------------------------------------------


def test_a_bundle_round_trips_the_whole_card_record(written: Path) -> None:
    bundle = read_bundle(written)

    assert bundle.format_version == BUNDLE_FORMAT_VERSION
    assert bundle.run_id == written.name
    assert bundle.created_at.endswith("Z")
    assert bundle.card_count == 2

    matched = bundle.cards[0]
    assert matched.card_id == "synthetic_dominant_trait"
    assert matched.section == "traits"
    assert matched.kind == "interpretation"
    assert matched.status == "matched"
    assert (
        matched.summary == f"Your {OBSERVED_GENOTYPE} at rs900000001 carries the synthetic allele."
    )
    assert matched.gene == "SYNTH1"
    assert matched.confidence_tier is not None
    assert matched.match["observed_genotype"] == OBSERVED_GENOTYPE
    assert matched.match["strand"] == Strand.AS_WRITTEN.value
    assert matched.variant is not None and matched.variant["rsid"] == "rs900000001"
    assert [c["id"] for c in matched.citations] == ["10.1038/s41586-000-00000-0", "12345678"]
    assert matched.computed_caveats == ("Synthetic computed caveat.",)
    assert matched.authored_caveats

    impossible = bundle.cards[1]
    assert impossible.kind == "impossibility"
    assert impossible.status == MatchStatus.NOT_DETERMINABLE.value
    assert impossible.confidence is None and impossible.confidence_tier is None
    assert impossible.impossibility_reason


def test_confidence_travels_with_the_inputs_that_produced_it(written: Path) -> None:
    """M13.4: an agent must be able to say *why* a card is low confidence.

    A tier alone is the unaccountable number AGENTS.md 6 forbids a card from authoring;
    saving only the tier would reintroduce it at the storage layer, one milestone after
    the schema refused it at the authoring layer.
    """
    matched = read_bundle(written).cards[0]
    assert matched.confidence is not None
    inputs = matched.confidence["inputs"]
    assert inputs["population_allele_frequency"] == 0.20
    assert inputs["call_source"] == CallSource.DIRECT.value
    assert inputs["evidence_tier"] and inputs["replication"]
    assert set(matched.confidence) == {"tier", "score", "inputs", "empirical_ppv"}


def test_provenance_pins_engine_knowledge_references_tools_and_input(written: Path) -> None:
    provenance = read_bundle(written).provenance

    assert provenance["engine_version"]
    assert provenance["knowledge"]["card_count"] == 3
    assert provenance["knowledge"]["digest"]
    assert provenance["input"]["vendor"] == "ancestrydna_v2"
    assert provenance["input"]["markers"] > 0
    assert provenance["tools"] == {}


def test_absent_references_are_recorded_as_absent_not_omitted(written: Path) -> None:
    """ "No references were fetched" and "this bundle does not say" are different facts.

    Only one of them means the run had no frequency gate behind it (AGENTS.md 4.1), and a
    reader months later cannot tell them apart from a missing key.
    """
    references = read_bundle(written).provenance["references"]
    assert references["present"] is False
    assert references["reason"]
    assert references["sources"] == {}


def test_knowledge_provenance_follows_the_corpus_rather_than_a_maintained_version(
    pack_dir: Path,
) -> None:
    before = knowledge_provenance(KnowledgePack.load(pack_dir))
    target = pack_dir / "valid_pack.yaml"
    target.write_text(
        target.read_text(encoding="utf-8").replace("SYNTH1", "SYNTH2"), encoding="utf-8"
    )
    after = knowledge_provenance(KnowledgePack.load(pack_dir))

    assert before["digest"] != after["digest"]
    assert before["card_count"] == after["card_count"], "a content edit, not a count change"


# ---------------------------------------------------------------------------
# Self-containment
# ---------------------------------------------------------------------------


def test_a_saved_run_does_not_change_when_the_knowledge_pack_does(
    written: Path, pack_dir: Path
) -> None:
    """The property the whole format exists for.

    A bundle that stored card ids and re-rendered at read time would be cheaper and would
    pass every other test here. It would also mean editing a card tomorrow silently
    rewrites what a run said today -- and a saved run is the thing a person read, and may
    have made a decision on. So the pack is *destroyed* after the write and the bundle is
    read anyway.
    """
    before = read_bundle(written).cards[0].summary
    shutil.rmtree(pack_dir)

    after = read_bundle(written)
    assert after.cards[0].summary == before
    assert after.cards[0].citations
    assert after.provenance["knowledge"]["digest"], "provenance survives its source"


def test_reading_a_bundle_needs_no_engine_enum(written: Path) -> None:
    """Sections, statuses and tiers come back as strings, deliberately.

    Re-hydrating an enum is what breaks when a later version renames a member, and M4.2
    wants a months-old bundle to fail with a version error or not at all -- never with
    ``'traits' is not a valid Section`` from four frames down.
    """
    card = read_bundle(written).cards[0]
    for value in (card.section, card.kind, card.status, card.confidence_tier):
        assert isinstance(value, str)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_writing_over_an_existing_run_is_refused(
    tmp_path: Path,
    qc_report: QCReport,
    cards: tuple[KnowledgePack, tuple[AssembledCard, ...]],
    written: Path,
) -> None:
    pack, assembled = cards
    with pytest.raises(BundleError, match="already exists"):
        write_bundle(
            qc=qc_report,
            cards=assembled,
            pack=pack,
            runs_root=written.parent,
            run_id=written.name,
        )


def test_an_edited_payload_is_caught_by_its_digest(written: Path) -> None:
    cards_path = written / CARDS_NAME
    payload = json.loads(cards_path.read_text(encoding="utf-8"))
    payload["cards"][0]["summary"] = "Something the engine never said."
    cards_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BundleIntegrityError, match="does not match the digest"):
        read_bundle(written)


def test_a_deleted_payload_file_is_caught(written: Path) -> None:
    (written / QC_NAME).unlink()
    with pytest.raises(BundleIntegrityError, match="absent"):
        read_bundle(written)


def test_an_interrupted_write_leaves_no_run_id_and_no_staging_directory(
    tmp_path: Path,
    qc_report: QCReport,
    cards: tuple[KnowledgePack, tuple[AssembledCard, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half-written bundle must never bear a run id.

    Checked by making the write fail after the first payload file lands, which is exactly
    the shape of a process killed mid-save. The staging directory is cleaned up too, so a
    retry with the same id is not blocked by the wreckage of the first attempt.
    """
    from genetics.run import bundle as bundle_module

    pack, assembled = cards
    root = tmp_path / "runs"
    real_write = bundle_module._write_text

    def explode(path: Path, text: str) -> None:
        if path.name == CARDS_NAME:
            raise OSError("disk full")
        real_write(path, text)

    monkeypatch.setattr(bundle_module, "_write_text", explode)
    with pytest.raises(OSError, match="disk full"):
        write_bundle(qc=qc_report, cards=assembled, pack=pack, runs_root=root, run_id="run_a")

    assert not (root / "run_a").exists()
    assert list(root.iterdir()) == [], "staging directory left behind"


def test_a_staging_directory_is_never_mistaken_for_a_run(written: Path) -> None:
    """Named so listing (M4.2) can skip it by shape rather than by remembering to."""
    assert not written.name.startswith(INCOMING_PREFIX)
    assert INCOMING_PREFIX.startswith(".")


@pytest.mark.privacy
def test_the_payload_filenames_land_on_an_existing_gitignore_rule() -> None:
    """Third line of defence, and the one a rename would silently remove.

    A bundle is written outside the repo and an in-repo destination is refused, so this
    only matters for a bundle copied into the checkout by hand. The coupling is checked
    here rather than trusted because it is invisible from either end: nothing about
    ``qc.run.json`` says why it is not ``qc.json``, and nothing in ``.gitignore`` says
    which files it was written for.
    """
    ignore = (repo_root() / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.run.json" in ignore
    for name in (QC_NAME, CARDS_NAME):
        assert name.endswith(".run.json"), name
    assert not MANIFEST_NAME.endswith(".run.json"), "the manifest carries no genotype"


# ---------------------------------------------------------------------------
# Versioning and strictness
# ---------------------------------------------------------------------------


def test_a_future_format_version_raises_a_version_error_before_anything_else(
    written: Path,
) -> None:
    """The version gate must fire before the shape checks, or its message is useless.

    The manifest here is given a future version *and* nonsense elsewhere. A reader that
    parsed first would report the nonsense, sending someone to debug a file that is simply
    newer than their code.
    """
    manifest_path = written / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = BUNDLE_FORMAT_VERSION + 1
    manifest["provenance"] = "not an object"
    manifest["files"] = {}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BundleVersionError) as caught:
        read_bundle(written)
    message = str(caught.value)
    assert str(BUNDLE_FORMAT_VERSION + 1) in message
    assert "wrote it" in message


def test_an_older_format_version_says_so_rather_than_guessing(written: Path) -> None:
    manifest_path = written / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BundleVersionError, match="predates this format"):
        read_bundle(written)


def test_an_unknown_payload_key_is_refused_rather_than_ignored(written: Path) -> None:
    """Same rule as the card schema, and the same reason.

    In a record this full of optional fields, a silently ignored key is indistinguishable
    from one that had no effect -- so a bundle carrying a field this reader does not
    understand is a bundle this reader cannot honestly claim to have read.
    """

    def add_key(payload: dict[str, Any]) -> None:
        payload["cards"][0]["risk_score"] = 0.9

    _repack(written, add_key)
    with pytest.raises(BundleError, match="risk_score"):
        read_bundle(written)


def test_a_missing_required_card_key_is_located(written: Path) -> None:
    def drop_summary(payload: dict[str, Any]) -> None:
        del payload["cards"][0]["summary"]

    _repack(written, drop_summary)
    with pytest.raises(BundleError) as caught:
        read_bundle(written)
    assert "cards[0]" in str(caught.value) and "summary" in str(caught.value)


def test_the_payload_key_sets_are_pinned_to_the_format_version() -> None:
    """Adding a key to the payload is a format change, and this is what says so.

    ``read_bundle`` rejects unknown keys, so a bundle written with a new field is
    unreadable by any engine that predates it. That is correct for an immutable record and
    it means the version must move in the same commit -- which is precisely the thing
    nobody remembers. Changing the payload fails here, with the reason attached.
    """
    expected_card = frozenset(
        {
            "card_id",
            "section",
            "kind",
            "title",
            "gene",
            "status",
            "summary",
            "detail",
            "impossibility_reason",
            "variant",
            "match",
            "confidence",
            "frequencies",
            "confidence_frequency",
            "citations",
            "authored_caveats",
            "computed_caveats",
        }
    )
    expected_manifest = frozenset(
        {"format_version", "run_id", "created_at", "provenance", "files", "counts"}
    )
    bump = "bump BUNDLE_FORMAT_VERSION in the same commit"
    assert expected_card == CARD_KEYS, f"card payload changed: {bump}"
    assert expected_manifest == MANIFEST_KEYS, f"manifest changed: {bump}"


def test_run_ids_are_unique_sortable_and_not_derived_from_the_input() -> None:
    """A digest of the export would be stable across runs, which is the problem.

    Stable means a persistent pseudonymous identifier for one person's genome, sitting in
    every directory listing, log line and error message -- genotype-derived (AGENTS.md 1.1)
    in the one place a bundle's contents are not.
    """
    stamp = datetime(2026, 8, 16, 14, 22, 33, tzinfo=UTC)
    ids = {new_run_id(stamp) for _ in range(50)}
    assert len(ids) == 50
    assert all(i.startswith("20260816T142233Z-") for i in ids)
    assert sorted(ids) == sorted(ids, key=str)


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_a_bundle_refuses_to_be_written_inside_the_repository(
    qc_report: QCReport, cards: tuple[KnowledgePack, tuple[AssembledCard, ...]]
) -> None:
    """AGENTS.md 1.1 and 1.5: a bundle is raw DNA, and .gitignore is the second line.

    ``.gitignore`` covers the paths :mod:`genetics.paths` declares. A bundle under some
    arbitrary in-repo directory is only partly caught -- ``x.run.json`` matches a pattern,
    ``run_001/cards.json`` does not -- so the destination is refused rather than trusted to
    the ignore file.
    """
    pack, assembled = cards
    with pytest.raises(UnsafeDataDirError, match="inside the repository"):
        write_bundle(
            qc=qc_report,
            cards=assembled,
            pack=pack,
            runs_root=repo_root() / "scratch_runs",
        )


@pytest.mark.privacy
def test_the_manifest_carries_no_genotype_while_the_cards_file_does(written: Path) -> None:
    """The split is the point, and both halves are asserted.

    The manifest is the file a person pastes into a bug report, so it is scanned.
    ``cards.json`` holds per-card genotypes by design and is not -- a guard that fails on
    correct output is a guard someone switches off. Asserting the genotype really is in
    the payload is what stops this test passing because the bundle recorded nothing.
    """
    assert find_genotypes((written / MANIFEST_NAME).read_text(encoding="utf-8")) == []
    assert find_genotypes((written / QC_NAME).read_text(encoding="utf-8")) == []
    assert OBSERVED_GENOTYPE in (written / CARDS_NAME).read_text(encoding="utf-8")


def _genotype_row() -> str:
    """Assembled at runtime, never written as a literal.

    A genotype row pasted into a test file would fail this project's own pre-commit
    content scan -- M0.3 established the practice and it applies here as much as anywhere.
    """
    return "\t".join(("rs4988235", "2", "136608646", "A", "G"))


@pytest.mark.privacy
def test_the_manifest_genotype_guard_actually_fires(
    tmp_path: Path, qc_report: QCReport, cards: tuple[KnowledgePack, tuple[AssembledCard, ...]]
) -> None:
    """The scan above is a negative assertion, and negative assertions pass when broken.

    So the guard is driven with input it must reject, through the one free-text field that
    actually reaches the manifest. Without this, deleting the ``assert_no_genotype`` call
    would leave every privacy test in this file green.
    """
    from dataclasses import replace

    from genetics.privacy import GenotypeLeakError

    pack, assembled = cards
    dirty = replace(qc_report, source_path=_genotype_row())
    with pytest.raises(GenotypeLeakError, match="manifest"):
        write_bundle(qc=dirty, cards=assembled, pack=pack, runs_root=tmp_path / "runs")
    assert not (tmp_path / "runs").exists() or list((tmp_path / "runs").iterdir()) == []


@pytest.mark.privacy
def test_the_qc_genotype_guard_fires_independently_of_the_manifest_one(
    tmp_path: Path, qc_report: QCReport, cards: tuple[KnowledgePack, tuple[AssembledCard, ...]]
) -> None:
    """A warning is the realistic vector, and warnings reach ``qc.json`` and not the manifest.

    Driving it through a field the manifest never sees is what proves the two scans are
    separate calls rather than one call the other test already covered.
    """
    from dataclasses import replace

    from genetics.privacy import GenotypeLeakError

    pack, assembled = cards
    dirty = replace(qc_report, warnings=(f"unparsed row: {_genotype_row()}",))
    with pytest.raises(GenotypeLeakError, match="QC report"):
        write_bundle(qc=dirty, cards=assembled, pack=pack, runs_root=tmp_path / "runs")


@pytest.mark.privacy
def test_neither_a_bundle_nor_a_stored_card_can_print_a_genotype(written: Path) -> None:
    bundle = read_bundle(written)
    card = bundle.cards[0]

    assert OBSERVED_GENOTYPE in str(card.match["observed_genotype"])
    for text in (repr(bundle), repr(card)):
        assert OBSERVED_GENOTYPE not in text
        assert find_genotypes(text) == []
    assert "synthetic_dominant_trait" in repr(card), "identifiers stay visible"


@pytest.mark.privacy
def test_the_default_runs_root_is_outside_the_checkout() -> None:
    from genetics.paths import runs_dir

    assert not str(runs_dir()).startswith(str(repo_root()))


def test_an_impossibility_card_stores_no_observation(written: Path) -> None:
    impossible = read_bundle(written).cards[1]
    assert impossible.frequencies == ()
    assert impossible.confidence_frequency is None
    assert impossible.match["genotype"] is None
    assert impossible.variant is None


def test_a_directory_that_is_not_a_bundle_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="not a run bundle directory"):
        read_bundle(tmp_path / "nope")

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(BundleError, match=MANIFEST_NAME):
        read_bundle(empty)


def test_cards_from_a_pack_with_no_interpretation_still_round_trip(
    tmp_path: Path, qc_report: QCReport, cards: tuple[KnowledgePack, tuple[AssembledCard, ...]]
) -> None:
    """Cardinality again (AGENTS.md 0.1A), one layer further out.

    M3.2 refuses to drop a card at match time and M3.4 refuses at assembly time. A
    serializer that skipped unresolved cards would undo both at the last possible moment,
    where the omission is hardest to notice: the bundle simply has fewer cards.
    """
    pack, _ = cards
    impossible = tuple(
        _impossible(pack, card.id) for card in pack.cards if card.kind is CardKind.IMPOSSIBILITY
    )
    path = write_bundle(
        qc=qc_report,
        cards=impossible,
        pack=pack,
        runs_root=tmp_path / "runs",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    bundle = read_bundle(path)
    assert bundle.card_count == len(impossible)
    assert json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))["counts"] == {
        "cards": len(impossible),
        "with_interpretation": 0,
    }
