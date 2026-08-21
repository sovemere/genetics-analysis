"""The run bundle format (roadmap M4.1).

Organised by the property each test defends. The format's job is to still be readable and
still say the same thing after the code that wrote it has moved on, so most of these
tests change something *after* the write and check that the bundle did not follow.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
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
RARE_GENOTYPE = "CT"
"""The rare card's call. A different pair from OBSERVED_GENOTYPE on purpose: the two cards
declare different alleles, and reusing one genotype across both would have been rejected by
assembly for attaching another variant's calibration -- which it duly was, the first time."""


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


def _rare_matched(pack: KnowledgePack, card_id: str) -> AssembledCard:
    """A matched card rare enough to carry an empirical PPV.

    Included in the bundle fixture because the PPV block is ``None`` for an ordinary
    common variant, so nothing else here ever serialises it -- and ``likely-artifact`` is
    the tier AGENTS.md 4.1 calls the most important thing the interface communicates. A
    round-trip suite that never writes one is testing the easy half.
    """
    card = pack.by_id(card_id)
    assert card is not None and card.match is not None
    outcome_name = next(iter(card.match.genotypes.values()))
    return assemble_card(
        card,
        MatchResult(
            card_id=card.id,
            status=MatchStatus.MATCHED,
            reason="Matched.",
            genotype=RARE_GENOTYPE,
            observed_genotype=RARE_GENOTYPE,
            observed_rsid=card.match.variant.rsid,
            outcome_name=outcome_name,
            outcome=card.outcomes[outcome_name],
            strand=Strand.AS_WRITTEN,
        ),
        ObservationEvidence(
            call_source=CallSource.DIRECT,
            frequencies=(
                PopulationFrequency("C", 0.999999, "global", "synthetic-reference-v1"),
                PopulationFrequency("T", 0.000001, "global", "synthetic-reference-v1"),
            ),
        ),
    )


@pytest.fixture
def cards(pack_dir: Path) -> tuple[KnowledgePack, tuple[AssembledCard, ...]]:
    pack = KnowledgePack.load(pack_dir)
    return pack, (
        _matched(pack, "synthetic_dominant_trait"),
        _impossible(pack, "synthetic_impossibility"),
        _rare_matched(pack, "synthetic_haploid_marker"),
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
    """Edit ``cards.run.json`` *and* refresh its recorded digest.

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
    assert bundle.card_count == 3

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


def _is_ignored(relative: str) -> bool:
    """Ask git, not the file.

    The first version of this test grepped ``.gitignore`` for the literal ``*.run.json``
    and passed -- while the claim it was making was false, because
    ``!/knowledge/**/*.json`` appears *later* in the file and won. A string search cannot
    see precedence, negation, or ordering, which are the only things that decide the
    answer. This is M0.4's finding again: a test written to check a rule that was actually
    checking text.
    """
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", relative],
        cwd=repo_root(),
        capture_output=True,
    )
    if completed.returncode not in (0, 1):
        raise AssertionError(f"git check-ignore failed: {completed.stderr!r}")
    return completed.returncode == 0


@pytest.mark.privacy
@pytest.mark.parametrize(
    "directory",
    ["", "knowledge/", "src/genetics/", "tests/fixtures/", "data/references/"],
)
def test_a_bundle_payload_is_gitignored_everywhere_in_the_checkout(directory: str) -> None:
    """Third line of defence, behind writing outside the repo and refusing in-repo writes.

    It matters for the case those two miss: a bundle copied into the checkout by hand --
    dropping a saved run under ``knowledge/`` to see which cards fired is an entirely
    reasonable thing to do, and ``git add -A`` would then commit per-card genotypes.

    Parametrised over directories with their own allowlists, because a blanket rule plus a
    later negation is exactly how the coverage was lost the first time. ``knowledge/`` is
    in this list because that is where it was actually broken.
    """
    for name in (QC_NAME, CARDS_NAME):
        assert _is_ignored(f"{directory}{name}"), f"{directory}{name} is committable"


@pytest.mark.privacy
def test_the_knowledge_allowlist_still_admits_card_files() -> None:
    """The other half, and the reason the fix is a rule rather than deleting the allowlist.

    Cards are the reviewable corpus and must stay tracked (AGENTS.md 3). A re-ignore rule
    broad enough to catch bundle payloads must not catch them, and that is only checkable
    by asking git about both.
    """
    for card in (
        "knowledge/traits/pigmentation.yaml",
        "knowledge/impossibilities/assay_limits.yaml",
    ):
        assert not _is_ignored(card), f"{card} became untrackable"


def test_the_payload_filenames_carry_the_suffix_the_ignore_rule_keys_on() -> None:
    """The naming half of the coupling above; the ignore rules key on this suffix."""
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


def test_a_nonsense_format_version_is_a_structural_error_not_a_version_one(
    written: Path,
) -> None:
    """Version 0 never existed, so it is damage rather than history."""
    manifest_path = written / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BundleError, match="1 or greater"):
        read_bundle(written)


def test_an_older_bundle_is_read_rather_than_orphaned(
    written: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fix for the review's sharpest finding, tested by pretending to be the future.

    The gate was equality, which reads fine while only one version exists and is a trap the
    moment a second does: adding any payload key bumps the version, M5, M8 and M9 all add
    payload, and a bundle is immutable so no in-place migration is even possible. The first
    bump would have orphaned every run a user had saved.

    There is no version-2 bundle to test with, so the engine is moved forward instead and a
    version-1 bundle -- the one the fixture just wrote -- is read by it. What makes that
    safe is the additive contract, not machinery: keys may be added, never removed or
    repurposed, so an old bundle carries everything a newer reader requires.
    """
    from genetics.run import bundle as bundle_module

    monkeypatch.setattr(bundle_module, "BUNDLE_FORMAT_VERSION", BUNDLE_FORMAT_VERSION + 5)
    older = read_bundle(written)

    assert older.format_version == BUNDLE_FORMAT_VERSION
    assert older.card_count == 3
    assert older.cards[0].summary, "an old bundle still renders"
    assert older.cards[0].citations


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
            "evidence",
            "observation",
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


#: Sub-objects whose *keys* are data rather than schema -- card filenames, source ids,
#: tool ids, payload filenames. Descending into them would pin the fixture's contents
#: instead of the format's shape.
_DYNAMIC = frozenset(
    {
        "files",
        "provenance.knowledge.files",
        "provenance.references.sources",
        "provenance.tools",
    }
)


def _shape(node: Any, prefix: str = "") -> set[str]:
    """Every key path in a JSON document, merged across list elements.

    Lists collapse to one ``[]`` step so two cards with different populated fields
    contribute a union rather than positional noise -- which is what makes the pinned set
    a statement about the format rather than about the fixture.
    """
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.add(path)
            if path not in _DYNAMIC:
                found |= _shape(value, path)
    elif isinstance(node, list):
        for item in node:
            found |= _shape(item, f"{prefix}[]")
    return found


def test_the_whole_nested_payload_shape_is_pinned(written: Path) -> None:
    """The check that actually forces a version bump, and the one the reader does not do.

    ``read_bundle`` rejects unknown keys only at the top level of the manifest and of each
    card. Verified before writing this: adding ``match.phase_set``, ``confidence.polygenic``
    and ``provenance.future_field`` to a bundle and refreshing its digest read back with no
    complaint at all -- while the module docstring and this test's sibling both implied
    otherwise. Making the *reader* recursively strict would mean carrying a full nested
    schema, which is the brittleness the format is designed against; a bundle from a newer
    engine is caught by the version gate long before its keys matter.

    So the enforcement lives here, where the job actually is: stopping this project's next
    commit from adding a field and forgetting the bump.
    """
    manifest = json.loads((written / MANIFEST_NAME).read_text(encoding="utf-8"))
    cards_payload = json.loads((written / CARDS_NAME).read_text(encoding="utf-8"))

    assert _shape(manifest) == {
        "format_version",
        "run_id",
        "created_at",
        "counts",
        "counts.cards",
        "counts.with_interpretation",
        "files",
        "provenance",
        "provenance.engine_version",
        "provenance.knowledge",
        "provenance.knowledge.card_schema_version",
        "provenance.knowledge.card_count",
        "provenance.knowledge.digest",
        "provenance.knowledge.files",
        "provenance.references",
        "provenance.references.present",
        "provenance.references.reason",
        "provenance.references.sources",
        "provenance.tools",
        "provenance.input",
        "provenance.input.vendor",
        "provenance.input.source_path",
        "provenance.input.markers",
    }, "manifest shape changed: bump BUNDLE_FORMAT_VERSION in the same commit"

    card = "cards[]"
    confidence = f"{card}.confidence"
    assert _shape(cards_payload) == {
        "cards",
        f"{card}.card_id",
        f"{card}.section",
        f"{card}.kind",
        f"{card}.title",
        f"{card}.gene",
        f"{card}.status",
        f"{card}.summary",
        f"{card}.detail",
        f"{card}.impossibility_reason",
        f"{card}.variant",
        f"{card}.variant.rsid",
        f"{card}.variant.chrom",
        f"{card}.variant.pos_grch37",
        f"{card}.variant.alleles",
        f"{card}.match",
        f"{card}.match.reason",
        f"{card}.match.genotype",
        f"{card}.match.observed_genotype",
        f"{card}.match.observed_rsid",
        f"{card}.match.call_status",
        f"{card}.match.strand",
        f"{card}.match.outcome_name",
        f"{card}.match.candidate_outcomes",
        f"{card}.evidence",
        f"{card}.evidence.tier",
        f"{card}.evidence.replication",
        f"{card}.evidence.sample_size",
        f"{card}.evidence.ancestry",
        f"{card}.evidence.within_family_attenuation",
        f"{card}.evidence.effect",
        f"{card}.evidence.effect.measure",
        f"{card}.evidence.effect.value",
        f"{card}.evidence.effect.units",
        f"{card}.evidence.effect.ci_low",
        f"{card}.evidence.effect.ci_high",
        f"{card}.evidence.effect.context",
        f"{card}.observation",
        f"{card}.observation.call_source",
        f"{card}.observation.imputation_quality",
        f"{card}.observation.ancestry_match",
        confidence,
        f"{confidence}.tier",
        f"{confidence}.score",
        f"{confidence}.empirical_ppv",
        f"{confidence}.empirical_ppv.estimate",
        f"{confidence}.empirical_ppv.population_frequency_ceiling",
        f"{confidence}.empirical_ppv.applies_to",
        f"{confidence}.inputs",
        f"{confidence}.inputs.evidence_tier",
        f"{confidence}.inputs.evidence_score",
        f"{confidence}.inputs.effect_measure",
        f"{confidence}.inputs.effect_value",
        f"{confidence}.inputs.effect_score",
        f"{confidence}.inputs.replication",
        f"{confidence}.inputs.replication_score",
        f"{confidence}.inputs.population_allele_frequency",
        f"{confidence}.inputs.frequency_score",
        f"{confidence}.inputs.call_source",
        f"{confidence}.inputs.imputation_quality",
        f"{confidence}.inputs.imputation_score",
        f"{confidence}.inputs.ancestry_match",
        f"{confidence}.inputs.ancestry_score",
        f"{card}.frequencies",
        f"{card}.frequencies[].allele",
        f"{card}.frequencies[].frequency",
        f"{card}.frequencies[].population",
        f"{card}.frequencies[].source",
        f"{card}.confidence_frequency",
        f"{card}.confidence_frequency.allele",
        f"{card}.confidence_frequency.frequency",
        f"{card}.confidence_frequency.population",
        f"{card}.confidence_frequency.source",
        f"{card}.citations",
        f"{card}.citations[].type",
        f"{card}.citations[].id",
        f"{card}.citations[].title",
        f"{card}.citations[].database",
        f"{card}.citations[].note",
        f"{card}.authored_caveats",
        f"{card}.computed_caveats",
    }, "card payload shape changed: bump BUNDLE_FORMAT_VERSION in the same commit"


def test_a_likely_artifact_finding_round_trips_with_its_ppv(written: Path) -> None:
    """The rarity inversion has to survive being saved, or the saved run misleads.

    AGENTS.md 4.1 calls this the most important thing the interface communicates, and the
    PPV is what stops a reader taking a rare chip call at face value. It travels labelled
    as a band statistic, exactly as M3.3 computed it.
    """
    rare = read_bundle(written).cards[2]
    assert rare.confidence_tier == "likely-artifact"
    assert rare.confidence is not None
    ppv = rare.confidence["empirical_ppv"]
    assert ppv is not None
    assert 0.0 < ppv["estimate"] < 1.0
    assert ppv["applies_to"]


def test_a_run_id_must_be_a_plain_directory_name(
    tmp_path: Path, qc_report: QCReport, cards: tuple[KnowledgePack, tuple[AssembledCard, ...]]
) -> None:
    """Found on the self-pass, and the interesting part is why the first check missed it.

    The original test blacklisted ``/`` and ``\\``. On Windows ``root / "D:elsewhere"``
    discards ``root`` and lands on another drive, and that string contains neither -- so
    ``destination`` and ``staging`` ended up pointing at different places while the write
    died on ``mkdir`` with an OS error. Nothing escaped, because ``INCOMING_PREFIX``
    neutralises the drive-relative form for the staging path, but the containment
    ``_resolve_root`` establishes was being discarded by a join one line later.

    Checking the outcome rather than enumerating the inputs is the same conclusion M2.5
    reached about archive member names. ``..`` is named explicitly because
    ``Path("..").name`` is ``".."``, so it passes a basename test.
    """
    pack, assembled = cards
    # ".draft" is here from the agent review: only the full INCOMING_PREFIX was refused, so
    # a dot-led id was written successfully and then hidden by M4.2's shape-based listing --
    # a bundle that exists and cannot be found, with no error at write time.
    for bad in ("D:elsewhere", "..", ".", "", "  ", "a/b", "a\\b", f"{INCOMING_PREFIX}x", ".draft"):
        with pytest.raises(BundleError, match="run id"):
            write_bundle(
                qc=qc_report,
                cards=assembled,
                pack=pack,
                runs_root=tmp_path / "runs",
                run_id=bad,
            )
    assert not (tmp_path / "runs").exists() or list((tmp_path / "runs").iterdir()) == []


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
    ``cards.run.json`` holds per-card genotypes by design and is not -- a guard that fails on
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
    """A warning is the realistic vector, and warnings reach ``qc.run.json`` and not the manifest.

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


def test_call_provenance_survives_for_a_card_with_no_confidence(written: Path) -> None:
    """Found by the review, and it only bites after M8 -- which is why it had to be now.

    ``confidence`` is ``None`` for every card that did not match, and ``call_source`` lived
    only inside it. So a saved run could not distinguish "the marker is not on this array"
    from "imputation was attempted and failed" once M8 exists. Recovering that later would
    mean adding a payload key, i.e. a format bump; adding it at version 1, before any
    bundle exists anywhere, costs nothing.
    """
    matched, impossible, _ = read_bundle(written).cards

    assert matched.observation is not None
    assert matched.observation["call_source"] == CallSource.DIRECT.value
    assert matched.observation["imputation_quality"] is None
    # An impossibility genuinely has no observation -- it is not determinable by
    # construction, and assembly refuses to attach runtime evidence to one.
    assert impossible.observation is None


def test_a_pack_whose_files_have_vanished_refuses_to_claim_a_digest(
    tmp_path: Path, qc_report: QCReport, cards: tuple[KnowledgePack, tuple[AssembledCard, ...]]
) -> None:
    """``rglob`` on a missing directory returns nothing rather than raising.

    That would have written a well-formed sha256 of the empty set beside a truthful
    ``card_count``, so two bundles from two different packs would agree on the one field
    whose entire job is answering "was this the same pack I have now?". A digest that can
    only mean one thing is not a digest -- the same shape as M0.6's HIBAG probe.
    """
    pack, assembled = cards
    shutil.rmtree(pack.source_dir)

    with pytest.raises(BundleError, match="no card files on disk"):
        write_bundle(qc=qc_report, cards=assembled, pack=pack, runs_root=tmp_path / "runs")


def test_an_unreadable_lock_degrades_instead_of_losing_the_run(
    tmp_path: Path, qc_report: QCReport, cards: tuple[KnowledgePack, tuple[AssembledCard, ...]]
) -> None:
    """Reference provenance is written to degrade, and it only degraded for one error type.

    A corrupt lock raises ``UnicodeDecodeError`` from ``read_text`` and an unreadable one
    raises ``OSError``; neither is a ``LockError``, so both propagated out of
    ``write_bundle`` and threw away a completed analysis over a file the run never used.
    """
    pack, assembled = cards
    corrupt = tmp_path / "manifest.lock"
    corrupt.write_bytes(b"\xff\xfe\x00binary garbage\x00\xff")

    path = write_bundle(
        qc=qc_report,
        cards=assembled,
        pack=pack,
        runs_root=tmp_path / "runs",
        lock_path=corrupt,
        tools_root=tmp_path / "tools",
    )
    references = read_bundle(path).provenance["references"]
    assert references["present"] is False
    assert "could not be read" in references["reason"]


def test_a_corrupt_manifest_reports_damage_rather_than_crashing(written: Path) -> None:
    """M4.2's CLI will be catching ``BundleError``; anything else reaches the user raw.

    The manifest is read before any digest check, so mangled bytes are on the most common
    corruption path -- and ``read_text`` raises ``UnicodeDecodeError``, which was escaping.
    """
    (written / MANIFEST_NAME).write_bytes(b"\xff\xfe\x00not utf-8 at all\x00")
    with pytest.raises(BundleError, match="could not be read"):
        read_bundle(written)


def test_an_unknown_key_in_the_cards_file_wrapper_is_refused(written: Path) -> None:
    """The cards file has exactly one expected key, and it was the one level left unchecked.

    ``_reject_unknown`` covered the manifest and each card but not the wrapper between
    them, so a future writer adding ``sort_order`` here would be read as whole by a reader
    that ignored it -- the precise failure the strictness exists to prevent.
    """

    def add_wrapper_key(payload: dict[str, Any]) -> None:
        payload["sort_order"] = ["synthetic_dominant_trait"]

    _repack(written, add_wrapper_key)
    with pytest.raises(BundleError, match="sort_order"):
        read_bundle(written)


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
