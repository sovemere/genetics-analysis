"""Saved run parts: an interrupted run resumes after the last part it saved.

Every export here is synthetic (AGENTS.md 1.2), and every imputation is the invented
``synthetic_stage``; no test reads a real genome or runs Beagle.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.engine.cards import KnowledgePack
from genetics.health.clinvar import ClinVarError, lookup_default
from genetics.imputation import ImputationResult
from genetics.imputation.dosages import DosageRecord
from genetics.ingest.schema import GenotypeTable
from genetics.paths import repo_root, run_parts_dir
from genetics.pgs.engine import index_dosages
from genetics.pgs.records import ScoreRecords
from genetics.privacy import assert_no_genotype
from genetics.run import pipeline
from genetics.run.bundle import _card_payload, read_bundle
from genetics.run.parts import RunParts, RunPartsError, contract, engine_sha256
from genetics.testing.fixtures import FIXTURES, render_fixture
from genetics.testing.imputation_snapshots import anchors, synthetic_stage

PACK = Path(__file__).parents[1] / "fixtures" / "cards"
LOCUS = ("7", 12345678)
"""A card locus in the fixture pack, absent from the synthetic export."""


def dosage(pos: int = LOCUS[1], chrom: str = LOCUS[0]) -> DosageRecord:
    return DosageRecord(
        chrom,
        pos,
        "A",
        ("G",),
        (0, 1),
        (0, 1),
        (1.1,),
        (1.1,),
        (0.9,),
        2,
        "imputed_untyped",
        "resolved",
        None,
        "beagle_DS",
        "beagle_diploid_dosage",
    )


@pytest.fixture
def export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    path = tmp_path / "synthetic.txt"
    path.write_text(render_fixture(spec), encoding="utf-8")
    return path


@pytest.fixture
def imputed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts imputation stages run; each writes the same synthetic dosage files."""
    runs: list[int] = []

    def stage(original: GenotypeTable, **kwargs: Any) -> ImputationResult:
        runs.append(1)
        return synthetic_stage(
            original, tmp_path / "synthetic-complete", records=(*anchors(LOCUS[0]), dosage())
        )

    monkeypatch.setattr(pipeline, "impute", stage)
    return runs


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts full reads of the imputed dose stream."""
    passes: list[int] = []
    original = index_dosages

    def counting(*args: Any, **kwargs: Any) -> Any:
        passes.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "index_dosages", counting)
    return passes


def interrupt_at_clinvar(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Stop runs after the dose read; return the undo."""
    original = lookup_default

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "lookup_default", interrupted)
    return lambda: monkeypatch.setattr(pipeline, "lookup_default", original)


def payloads(analysis: pipeline.Analysis) -> list[dict[str, Any]]:
    return [_card_payload(card) for card in analysis.cards]


def test_an_interrupted_run_resumes_after_its_imputation_and_dose_read(
    export: Path,
    imputed: list[int],
    reads: list[int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fresh = pipeline.analyse(export, knowledge_dir=PACK)
    assert imputed == [1] and reads == [1]
    assert fresh.parts is None and not run_parts_dir().exists()

    resume = interrupt_at_clinvar(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        pipeline.analyse(export, knowledge_dir=PACK, resumable=True)
    assert imputed == [1, 1] and reads == [1, 1]
    resume()

    messages: list[str] = []
    resumed = pipeline.analyse(export, knowledge_dir=PACK, resumable=True, progress=messages.append)
    # Neither the imputation stage nor the dose read ran again.
    assert imputed == [1, 1] and reads == [1, 1]
    assert any(
        m.startswith("Resuming an interrupted run") and "imputation, the dose read" in m
        for m in messages
    )
    assert resumed.imputation_result is not None and resumed.imputation_result.resumed
    # The imputed card observation came from the saved read, and matches a fresh run.
    assert any(
        c.observation is not None and c.observation.imputation is not None for c in resumed.cards
    )
    assert payloads(resumed) == payloads(fresh)
    assert resumed.pgx == fresh.pgx and resumed.hla == fresh.hla

    path = pipeline.save(resumed, runs_root=tmp_path / "runs", progress=messages.append)
    assert read_bundle(path).card_count == len(fresh.cards)
    assert messages[-1].startswith("Removed this run's saved parts")
    assert not run_parts_dir().exists()
    assert_no_genotype("\n".join(messages))


def test_a_damaged_part_is_recomputed_and_restart_discards_every_part(
    export: Path,
    imputed: list[int],
    reads: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interrupt_at_clinvar(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        pipeline.analyse(export, knowledge_dir=PACK, resumable=True)
    (saved,) = run_parts_dir().glob("*/doses.dosages.jsonl.gz")
    saved.write_bytes(b"damaged")

    messages: list[str] = []
    with pytest.raises(KeyboardInterrupt):
        pipeline.analyse(export, knowledge_dir=PACK, resumable=True, progress=messages.append)
    assert "The saved dose read part is missing or damaged; recomputing it" in messages
    assert imputed == [1] and reads == [1, 1]

    with pytest.raises(KeyboardInterrupt):
        pipeline.analyse(
            export, knowledge_dir=PACK, resumable=True, restart=True, progress=messages.append
        )
    assert "Discarded the saved parts of an earlier run of this export" in messages
    assert imputed == [1, 1] and reads == [1, 1, 1]


def test_cli_run_resumes_by_default_and_removes_its_parts_once_saved(
    export: Path,
    imputed: list[int],
    reads: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = lookup_default

    def failed(*args: Any, **kwargs: Any) -> Any:
        raise ClinVarError("synthetic interruption")

    monkeypatch.setattr(pipeline, "lookup_default", failed)
    command = ["run", "--input", str(export), "--knowledge", str(PACK)]
    assert CliRunner().invoke(app, command).exit_code == 2
    assert len(list(run_parts_dir().iterdir())) == 1

    monkeypatch.setattr(pipeline, "lookup_default", original)
    invocation = CliRunner().invoke(app, command)
    assert invocation.exit_code == 0, invocation.output
    assert "Resuming an interrupted run of this export" in invocation.output
    assert imputed == [1] and reads == [1]
    assert not run_parts_dir().exists()
    assert_no_genotype(invocation.output)


def test_parts_are_reused_only_under_the_same_contract(export: Path, tmp_path: Path) -> None:
    pack = KnowledgePack.load(PACK)
    terms = contract(export, pack=pack, no_impute=False, options={"hla_opt_in": False})
    assert terms["engine"]["sources_sha256"] == engine_sha256()
    assert_no_genotype(json.dumps(terms))
    other = tmp_path / "other.txt"
    other.write_bytes(export.read_bytes().replace(b"\n", b"\r\n"))
    variants = [
        contract(other, pack=pack, no_impute=False, options={"hla_opt_in": False}),
        contract(export, pack=pack, no_impute=True, options={"hla_opt_in": False}),
        contract(export, pack=pack, no_impute=False, options={"hla_opt_in": True}),
    ]
    root = tmp_path / "parts"
    key = RunParts.open(terms, root=root).key
    assert RunParts.open(dict(terms), root=root).key == key
    assert len({key, *(RunParts.open(v, root=root).key for v in variants)}) == 4


def test_parts_inside_the_checkout_are_refused() -> None:
    root = repo_root() / "build" / "run-parts"
    with pytest.raises(RunPartsError, match="outside the checkout"):
        RunParts.open({"run": 1}, root=root)
    assert not root.exists()


def test_each_part_round_trips_and_a_failed_save_costs_only_the_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: list[str] = []
    root = tmp_path / "parts"
    parts = RunParts.open({"run": 1}, root=root, progress=messages.append)
    assert messages[-1].startswith("Saving this run's parts as they finish")
    # Nothing is written before the first part, so a run failing earlier leaves nothing.
    assert not root.exists()
    # Two records at one locus stay together and in order; a locus nobody reads is dropped.
    stream = [dosage(10, "1"), dosage(20, "1"), dosage(20, "1"), dosage(30, "2")]
    index = index_dosages(stream, {("1", 20), ("2", 30)})
    parts.save_doses(index)
    records = ScoreRecords()
    records.add("card_a", {"after": {"sum": 1.25}})
    parts.save_score("card_a", records.compressed("card_a"))
    parts.save_calls({"status": "unavailable"}, {"status": "not_run"})

    again = RunParts.open({"run": 1}, root=root, progress=messages.append)
    assert messages[-1].endswith("the dose read, 1 polygenic score(s), PGx and HLA calls")
    restored = again.doses()
    assert restored == index and list(restored.iter_records()) == stream[1:]
    assert ScoreRecords().restore("card_a", again.score("card_a") or b"") == {
        "after": {"sum": 1.25}
    }
    assert again.score("card_b") is None
    assert again.calls() == ({"status": "unavailable"}, {"status": "not_run"})

    with monkeypatch.context() as patched:

        def full(fileno: int) -> None:
            raise OSError(28, "No space left on device")

        patched.setattr("genetics.run.parts.os.fsync", full)
        again.save_score("card_b", b"unsaved")
    assert messages[-1] == (
        "Could not save the card_b score part (No space left on device); "
        "an interruption from here recomputes it"
    )
    assert again.score("card_b") is None
    assert not [p for p in again.directory.iterdir() if p.name.startswith("pending-")]

    # A damaged part is dropped with a message; the others stay.
    (again.directory / "pgs-card_a.run.json.gz").write_bytes(b"damaged")
    assert again.score("card_a") is None
    assert messages[-1] == "The saved card_a score part is missing or damaged; recomputing it"
    assert again.describe() == "the dose read, PGx and HLA calls"

    # A contract that disagrees with its key is damage too, and takes every part with it.
    (again.directory / "contract.run.json").write_text("{}", encoding="utf-8")
    third = RunParts.open({"run": 1}, root=root, progress=messages.append)
    assert "The saved run parts' contract is damaged; discarding them" in messages
    assert third.describe() == ""
    third.discard()
    assert not root.exists()


def test_the_imputation_part_is_reused_only_while_its_files_match(
    export: Path, tmp_path: Path
) -> None:
    from genetics.ingest import ingest

    table = ingest(export).table
    result = synthetic_stage(table, tmp_path / "complete", records=(*anchors("7"), dosage()))
    messages: list[str] = []
    parts = RunParts.open({"run": 1}, root=tmp_path / "parts", progress=messages.append)
    parts.save_imputation(result)
    reopened = parts.imputation(table)
    assert reopened is not None and reopened.resumed
    assert reopened.metadata == result.metadata
    assert list(reopened.iter_dosages()) == list(result.iter_dosages())

    other = ingest(export).table.frame.head(10)
    assert parts.imputation(GenotypeTable(other, vendor=table.vendor)) is None
    assert messages[-1].startswith("The saved imputation no longer matches its dosage files")

    # Parts read from one imputation are not reused after imputation runs again.
    parts.save_imputation(result)
    parts.save_doses(index_dosages(result.iter_dosages(), {LOCUS}))
    parts.save_score("card_a", b"saved")
    assert parts.describe() == "imputation, the dose read, 1 polygenic score(s)"
    parts.save_imputation(result)
    assert messages[-1] == "Imputation ran again, so the parts read from its doses are recomputed"
    assert parts.describe() == "imputation"

    result.dosage_files[0].write_bytes(b"changed")
    assert parts.imputation(table) is None


def test_the_single_dose_read_gives_card_inputs_what_they_filtered_for_themselves(
    export: Path, tmp_path: Path
) -> None:
    from genetics.imputation.observations import card_input
    from genetics.ingest import ingest
    from genetics.qc.report import InferredSex

    table = ingest(export).table
    # A record at the card locus, between anchors and a record no reader asks for.
    stream = (*anchors(LOCUS[0]), dosage(), dosage(LOCUS[1] + 5))
    result = synthetic_stage(table, tmp_path / "complete", records=stream)
    pack = KnowledgePack.load(PACK)
    loci = {
        (variant.key.chrom.value, variant.key.pos_grch37)
        for card in pack.cards
        if card.match is not None
        for variant in card.match.variants
    }
    index = index_dosages(result.iter_dosages(), loci)
    assert index.loci_held == 1
    full = card_input(pack, result, sex=InferredSex.MALE)
    single = card_input(pack, result, sex=InferredSex.MALE, dosages=index.iter_records())
    assert full[1] == single[1] and LOCUS in single[1]
    assert full[0].frame.equals(single[0].frame)
