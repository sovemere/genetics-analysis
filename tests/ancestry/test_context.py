"""The ancestry stage and the context it hands the rest of a run (roadmap M5.8).

Two halves. The result types are tested for the one property the milestone is about: a
*declined* placement and a stage that *did not run* are different answers, and nothing a
caller can build or read lets them collapse into a bare ``None``. The stage is tested for
where it draws the line between absent (``not_run``, with a reason) and wrong
(:class:`AncestryError`), and for what it leaves behind.

The stage's real computation needs PLINK 2 and fetched references, neither of which CI has,
so the orchestration tests replace the heavy calls with fakes and assert the wiring between
them. What the fakes cannot show -- that the real binary accepts what the real functions
hand it -- was checked by a run through the pinned PLINK 2 over a synthetic panel; see the
roadmap's M5.8 entry.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from genetics.ancestry import context as stage
from genetics.ancestry import phylotree, ytree
from genetics.ancestry.context import (
    AffinityResult,
    AffinityStatus,
    AncestryContext,
    AncestryError,
    LineageResult,
    LineageStatus,
    PlacementStatus,
    PopulationResult,
    infer_ancestry,
)
from genetics.ancestry.haplogroup import Mutation, build_tree
from genetics.ancestry.reference_pca import InsufficientOverlapError, ReferencePcaError
from genetics.external.plink2 import Plink2, Plink2NotFoundError, Plink2VersionError
from genetics.ingest import IngestResult, ingest
from genetics.qc.report import InferredSex

SYNTHETIC = Path(__file__).parents[1] / "fixtures" / "synthetic"


@pytest.fixture(scope="module")
def male() -> IngestResult:
    return ingest(SYNTHETIC / "ancestry_v2_male.txt")


@pytest.fixture(scope="module")
def female() -> IngestResult:
    return ingest(SYNTHETIC / "ancestry_v2_female.txt")


@pytest.fixture
def empty_references(tmp_path: Path) -> Path:
    root = tmp_path / "references"
    root.mkdir()
    return root


def _infer(result: IngestResult, root: Path, tmp_path: Path, **kwargs: Any) -> AncestryContext:
    return infer_ancestry(
        result.table,
        result.qc,
        references_root=root,
        workspace=tmp_path / "cache",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# The result types
# ---------------------------------------------------------------------------


def test_a_placed_result_names_a_population_and_owes_no_reason(
    placed_ancestry: AncestryContext, ancestry_names: dict[str, str]
) -> None:
    assert placed_ancestry.status is PlacementStatus.PLACED
    assert placed_ancestry.population.reason == ""
    record = placed_ancestry.to_dict()["population"]
    assert record["population"] == ancestry_names["population"]
    assert record["region"] == ancestry_names["region"]


def test_a_declined_placement_is_a_finding_not_a_missing_value(
    declined_ancestry: AncestryContext,
) -> None:
    """The milestone's whole point, asserted on the record a later stage reads.

    Both a declined placement and a stage that never ran leave ``population`` null. Only the
    status tells them apart, so it has to be there, and it has to differ.
    """
    not_run = AncestryContext.not_run("nothing was fetched")
    declined = declined_ancestry.to_dict()["population"]
    absent = not_run.to_dict()["population"]

    assert declined["population"] is None and absent["population"] is None
    assert declined["status"] == "declined"
    assert absent["status"] == "not_run"
    assert declined_ancestry.status is PlacementStatus.DECLINED
    assert "standard deviations" in declined_ancestry.population.reason
    # A declined result still carries everything the refusal was computed from.
    assert declined["fits"] and declined["decline_threshold"] is not None


def test_nothing_is_constructed_empty_without_a_reason() -> None:
    with pytest.raises(AncestryError, match="no reason"):
        PopulationResult()
    with pytest.raises(AncestryError, match="no reason"):
        AffinityResult()
    with pytest.raises(AncestryError, match="no reason"):
        LineageResult("MT", LineageStatus.NOT_RUN)
    with pytest.raises(AncestryError, match="no reason"):
        LineageResult("Y", LineageStatus.NOT_APPLICABLE, reason="   ")


def test_an_answer_and_a_reason_cannot_be_held_together(
    placed_ancestry: AncestryContext,
) -> None:
    placement = placed_ancestry.population.placement
    affinity = placed_ancestry.ancient.affinity
    call = placed_ancestry.mt.call
    with pytest.raises(AncestryError):
        PopulationResult(placement=placement, not_run_reason="also not run")
    with pytest.raises(AncestryError):
        AffinityResult(affinity=affinity, not_run_reason="also not run")
    with pytest.raises(AncestryError, match="must not hold a call"):
        LineageResult("MT", LineageStatus.NOT_RUN, call=call, reason="why")
    with pytest.raises(AncestryError, match="must hold a call"):
        LineageResult("MT", LineageStatus.CALLED)


def test_the_lineage_slots_cannot_be_swapped(placed_ancestry: AncestryContext) -> None:
    with pytest.raises(AncestryError, match="MT and Y"):
        replace(placed_ancestry, mt=placed_ancestry.y)
    with pytest.raises(AncestryError, match="'MT' or 'Y'"):
        LineageResult("X", LineageStatus.NOT_RUN, reason="no such lineage")


def test_not_run_marks_every_part_with_its_reason() -> None:
    context = AncestryContext.not_run("the stage was not asked to run")
    assert context.status is PlacementStatus.NOT_RUN
    assert context.mt.status is LineageStatus.NOT_RUN
    assert context.y.status is LineageStatus.NOT_RUN
    assert context.ancient.status is AffinityStatus.NOT_RUN
    for part in context.to_dict().values():
        assert part["reason"] == "the stage was not asked to run"


def test_every_part_has_one_shape_whatever_its_status(placed_ancestry: AncestryContext) -> None:
    """A reader of a months-old bundle keys into these, so a status must not change the keys."""
    populated = placed_ancestry.to_dict()
    empty = AncestryContext.not_run("absent").to_dict()
    assert populated.keys() == empty.keys()
    for part in populated:
        assert populated[part].keys() == empty[part].keys(), part


@pytest.mark.privacy
def test_no_repr_names_a_result(
    placed_ancestry: AncestryContext, ancestry_names: dict[str, str]
) -> None:
    """Each part is the object a caller logs, and each part's answer is about a person."""
    shown = " ".join(
        repr(item)
        for item in (
            placed_ancestry,
            placed_ancestry.population,
            placed_ancestry.mt,
            placed_ancestry.y,
            placed_ancestry.ancient,
        )
    )
    for name in ancestry_names.values():
        assert name not in shown


@pytest.mark.privacy
def test_the_summary_carries_statuses_and_counts_not_results(
    placed_ancestry: AncestryContext, ancestry_names: dict[str, str]
) -> None:
    """``summary()`` is what ``genetics run`` prints; ``to_dict()`` is what the bundle keeps."""
    summary = json.dumps(placed_ancestry.summary())
    full = json.dumps(placed_ancestry.to_dict())
    for name in ancestry_names.values():
        assert name not in summary
        assert name in full
    assert placed_ancestry.summary()["population"]["status"] == "placed"


# ---------------------------------------------------------------------------
# The stage: absent is not_run
# ---------------------------------------------------------------------------


def test_the_suite_pins_the_stage_to_an_empty_reference_tree() -> None:
    """The flag *and* the patch, as the network guard's own test puts it.

    Every other test here would pass on CI with the conftest pin deleted, because CI fetches
    nothing -- and then fail, or worse run the real stage, on a machine that has. So the pin
    is asserted directly: the stage's default root is not the checkout's, and it is empty.
    """
    from genetics import paths

    # Read through the module namespace: that is the name the stage resolves at call time,
    # and the name the conftest pin replaces.
    pinned = vars(stage)["references_dir"]()
    assert pinned != paths.references_dir()
    assert pinned.is_dir() and not any(pinned.iterdir())


def test_with_nothing_fetched_every_part_says_why(
    male: IngestResult, empty_references: Path, tmp_path: Path
) -> None:
    context = _infer(male, empty_references, tmp_path)

    assert context.status is PlacementStatus.NOT_RUN
    assert "aadr" in context.population.reason
    assert "genetics refs fetch --only aadr" in context.population.reason
    assert context.ancient.status is AffinityStatus.NOT_RUN
    assert "thousand_genomes_phase3_grch37" in context.ancient.not_run_reason
    assert context.mt.status is LineageStatus.NOT_RUN
    assert "phylotree_17" in context.mt.reason
    assert context.y.status is LineageStatus.NOT_RUN
    assert ytree.DIRECTORY in context.y.reason


def test_a_run_that_computes_nothing_writes_nothing(
    male: IngestResult, empty_references: Path, tmp_path: Path
) -> None:
    """Every test run and every fresh checkout is this case, and the workspace is the user's
    own data directory -- so a run with nothing to compute leaves no trace there at all."""
    _infer(male, empty_references, tmp_path)
    assert not (tmp_path / "cache").exists()


def test_y_is_not_applicable_rather_than_not_run_for_a_sample_inferred_female(
    female: IngestResult, empty_references: Path, tmp_path: Path
) -> None:
    """Not having a Y chromosome is a result about the sample, not a missing reference."""
    assert female.qc.sex.inferred is InferredSex.FEMALE
    context = _infer(female, empty_references, tmp_path)
    assert context.y.status is LineageStatus.NOT_APPLICABLE
    assert "female" in context.y.reason
    assert context.mt.status is LineageStatus.NOT_RUN


def _tree(lineage: str, male: IngestResult) -> Any:
    """A two-branch tree defined at positions this fixture actually called.

    Derived from the fixture rather than invented so the call has real support to find:
    the first called base on the lineage's chromosome becomes the derived state of ``B``.
    """
    rows = male.table.frame.filter(
        (male.table.frame["chrom"] == lineage) & male.table.frame["a1"].is_in(["A", "C", "G", "T"])
    )
    position = int(rows["pos_grch37"][0])
    derived = str(rows["a1"][0])
    ancestral = next(base for base in "ACGT" if base != derived)
    return build_tree(
        lineage,
        f"synthetic {lineage} tree",
        "root",
        {"root": None, "A": "root", "B": "A"},
        {"root": (), "A": (), "B": (Mutation(position, ancestral, derived),)},
    )


def test_fetched_trees_are_called(
    male: IngestResult,
    empty_references: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = empty_references / "phylotree_17" / phylotree.ARCHIVE
    archive.parent.mkdir()
    archive.write_bytes(b"placeholder: the loader is replaced below")
    markers = empty_references / ytree.DIRECTORY / ytree.MARKERS
    markers.parent.mkdir()
    markers.write_text("placeholder\n", encoding="utf-8")

    seen: list[Path] = []

    def mt_loader(path: Path) -> Any:
        seen.append(path)
        return _tree("MT", male)

    monkeypatch.setattr(phylotree, "load_mt_tree", mt_loader)
    monkeypatch.setattr(ytree, "load_y_tree", lambda directory: _tree("Y", male))

    context = _infer(male, empty_references, tmp_path)
    assert seen == [archive], "the tree must be read from the root the stage was given"
    for lineage in (context.mt, context.y):
        assert lineage.status is LineageStatus.CALLED
        assert lineage.call is not None and lineage.call.haplogroup == "B"
        assert lineage.call.supporting == 1


def test_an_unreadable_tree_is_loud_rather_than_not_run(
    male: IngestResult,
    empty_references: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = empty_references / "phylotree_17" / phylotree.ARCHIVE
    archive.parent.mkdir()
    archive.write_bytes(b"not a zip")

    def broken(path: Path) -> Any:
        raise phylotree.PhyloTreeError("truncated archive")

    monkeypatch.setattr(phylotree, "load_mt_tree", broken)
    with pytest.raises(AncestryError, match="mtDNA tree cannot be read"):
        _infer(male, empty_references, tmp_path)


def _aadr_payload(root: Path) -> None:
    """Place the four AADR files the manifest names, as empty stand-ins."""
    from genetics.refs import manifest

    source = manifest.load().get("aadr")
    directory = root / "aadr"
    directory.mkdir(parents=True, exist_ok=True)
    for item in source.files:
        (directory / item.filename).write_bytes(b"")


def test_a_present_artifact_that_fails_verification_is_loud(
    male: IngestResult, empty_references: Path, tmp_path: Path
) -> None:
    """The ``default_anchors`` line: absent leaves a check undone, wrong stops the run."""
    _aadr_payload(empty_references)
    (empty_references / "aadr" / "modern_panel_ldpruned.pgen").write_bytes(b"not a pgen")

    with pytest.raises(AncestryError, match="fails verification"):
        _infer(male, empty_references, tmp_path)


# ---------------------------------------------------------------------------
# The stage: the placement's wiring, with the heavy calls replaced
# ---------------------------------------------------------------------------


@pytest.fixture
def verified_panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend the modern panel verified, so the tests below start past that check."""
    panel = tmp_path / "references" / "aadr" / "modern_panel_ldpruned.pgen"

    def verified_output(self: Any, source_id: str, step: str) -> Path | str:
        if source_id == stage.MODERN_PANEL_SOURCE:
            return panel
        return "the shared space is not under test here"

    monkeypatch.setattr(stage._References, "verified_output", verified_output)
    monkeypatch.setattr(
        stage._References,
        "aadr_inputs",
        lambda self: {
            suffix: tmp_path / f"aadr{suffix}" for suffix in (".snp", ".ind", ".geno", ".anno")
        },
    )
    return panel


def _found_plink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Plink2:
    plink = Plink2(path=tmp_path / "plink2", version="PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)")
    monkeypatch.setattr(Plink2, "discover", classmethod(lambda cls, **kwargs: plink))
    return plink


def test_plink_missing_is_not_run_with_the_install_command(
    male: IngestResult,
    verified_panel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(cls: Any, /, **kwargs: Any) -> Plink2:
        raise Plink2NotFoundError("PLINK 2 is not installed; run `genetics tools install`.")

    monkeypatch.setattr(Plink2, "discover", classmethod(missing))
    context = _infer(male, verified_panel.parents[1], tmp_path)
    assert context.status is PlacementStatus.NOT_RUN
    assert "genetics tools install" in context.population.reason


def test_a_plink_that_is_not_the_pinned_build_is_loud(
    male: IngestResult,
    verified_panel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def wrong(cls: Any, /, **kwargs: Any) -> Plink2:
        raise Plink2VersionError("plink2 is not the pinned PLINK 2 build")

    monkeypatch.setattr(Plink2, "discover", classmethod(wrong))
    with pytest.raises(AncestryError, match="not the pinned"):
        _infer(male, verified_panel.parents[1], tmp_path)


def test_too_little_overlap_is_recorded_as_not_run(
    male: IngestResult,
    verified_panel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fact about the export -- the synthetic fixtures meet it on every machine with
    references fetched -- so it is recorded with its reason instead of failing the run."""
    _found_plink(monkeypatch, tmp_path)

    def build(*args: Any, **kwargs: Any) -> Any:
        raise InsufficientOverlapError("only 12 of the panel's markers are carried by this array")

    monkeypatch.setattr(stage, "build_reference_pca", build)
    context = _infer(male, verified_panel.parents[1], tmp_path)
    assert context.status is PlacementStatus.NOT_RUN
    assert "shares too little" in context.population.reason
    assert "only 12" in context.population.reason


def test_any_other_reference_pca_failure_is_loud(
    male: IngestResult,
    verified_panel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _found_plink(monkeypatch, tmp_path)

    def build(*args: Any, **kwargs: Any) -> Any:
        raise ReferencePcaError("1 duplicated variant ID(s) in the intersection")

    monkeypatch.setattr(stage, "build_reference_pca", build)
    with pytest.raises(AncestryError, match="population placement failed"):
        _infer(male, verified_panel.parents[1], tmp_path)


class _FakePca:
    n_markers = 44_872
    n_components = 2


class _FakeProjection:
    reference = "refpca-0123456789abcdef"


def test_the_placement_is_wired_to_the_modern_panel_and_kept_whole(
    male: IngestResult,
    verified_panel: Path,
    placed_ancestry: AncestryContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plink = _found_plink(monkeypatch, tmp_path)
    calls: dict[str, Any] = {}

    def build(table: Any, subset: Path, **kwargs: Any) -> Any:
        calls["build"] = (subset, kwargs)
        return _FakePca()

    def project(pgen: Path, pca: Any, **kwargs: Any) -> Any:
        calls.setdefault("project", []).append(pgen)
        return _FakeProjection()

    def labels(psam: Path, anno: Path) -> Any:
        calls["labels"] = (psam, anno)
        return object()

    def project_sample(
        table: Any, pca: Any, subset: Path, tool: Any, scratch: Path, name: str
    ) -> Any:
        calls["sample"] = (subset, tool, scratch)
        return _FakeProjection()

    monkeypatch.setattr(stage, "build_reference_pca", build)
    monkeypatch.setattr(stage, "project", project)
    monkeypatch.setattr(stage, "read_aadr_population_labels", labels)
    monkeypatch.setattr(stage, "build_population_model", lambda panel, labels: object())
    monkeypatch.setattr(stage, "_project_sample", project_sample)
    monkeypatch.setattr(stage, "place", lambda sample, model: placed_ancestry.population.placement)

    context = _infer(male, verified_panel.parents[1], tmp_path)

    subset, kwargs = calls["build"]
    assert subset == verified_panel
    assert kwargs["reference_panels"] == (stage.MODERN_PANEL_SOURCE,)
    assert kwargs["plink"] is plink
    assert kwargs["workspace"] == tmp_path / "cache", "the PCA is cached, not scratch"
    assert calls["project"] == [verified_panel], "the panel goes through the sample's function"
    assert calls["labels"] == (verified_panel.with_suffix(".psam"), tmp_path / "aadr.anno")
    assert calls["sample"][0] == verified_panel and calls["sample"][1] is plink

    assert context.status is PlacementStatus.PLACED
    assert context.population.placement is placed_ancestry.population.placement
    assert context.population.reference == _FakeProjection.reference
    assert context.population.reference_markers == _FakePca.n_markers
    assert context.population.n_components == _FakePca.n_components


@pytest.mark.privacy
def test_the_samples_intermediates_do_not_outlive_the_run(
    male: IngestResult,
    verified_panel: Path,
    placed_ancestry: AncestryContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample's pgen and projections are a copy of the person's genotypes and derived
    coordinates. They are written to a per-run directory under the cache and removed with
    it; the reference PCA, a property of the panel and chip, stays for the next run."""
    _found_plink(monkeypatch, tmp_path)
    written: list[Path] = []

    def project_sample(
        table: Any, pca: Any, subset: Path, tool: Any, scratch: Path, name: str
    ) -> Any:
        target = scratch / f"{name}.pgen"
        target.write_bytes(b"the sample's genotypes")
        written.append(target)
        return _FakeProjection()

    monkeypatch.setattr(stage, "build_reference_pca", lambda *a, **k: _FakePca())
    monkeypatch.setattr(stage, "project", lambda *a, **k: _FakeProjection())
    monkeypatch.setattr(stage, "read_aadr_population_labels", lambda *a: object())
    monkeypatch.setattr(stage, "build_population_model", lambda *a: object())
    monkeypatch.setattr(stage, "_project_sample", project_sample)
    monkeypatch.setattr(stage, "place", lambda *a: placed_ancestry.population.placement)

    _infer(male, verified_panel.parents[1], tmp_path)

    assert written, "the fake never ran, so this test checked nothing"
    assert all(not path.exists() for path in written)
    assert all(not path.parent.exists() for path in written)
    assert (tmp_path / "cache").is_dir()
    assert list((tmp_path / "cache").iterdir()) == []


def test_a_failure_mid_placement_still_removes_the_intermediates(
    male: IngestResult,
    verified_panel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _found_plink(monkeypatch, tmp_path)
    written: list[Path] = []

    def project_sample(
        table: Any, pca: Any, subset: Path, tool: Any, scratch: Path, name: str
    ) -> Any:
        target = scratch / f"{name}.pgen"
        target.write_bytes(b"the sample's genotypes")
        written.append(target)
        raise ReferencePcaError("PLINK 2 reported success but wrote no .sscore")

    monkeypatch.setattr(stage, "build_reference_pca", lambda *a, **k: _FakePca())
    monkeypatch.setattr(stage, "project", lambda *a, **k: _FakeProjection())
    monkeypatch.setattr(stage, "read_aadr_population_labels", lambda *a: object())
    monkeypatch.setattr(stage, "build_population_model", lambda *a: object())
    monkeypatch.setattr(stage, "_project_sample", project_sample)

    with pytest.raises(AncestryError):
        _infer(male, verified_panel.parents[1], tmp_path)
    assert written and not written[0].exists()


def _abandoned(cache: Path, name: str, *, age_seconds: float) -> Path:
    directory = cache / name
    directory.mkdir(parents=True)
    (directory / "sample.pgen").write_bytes(b"the sample's genotypes")
    stamp = time.time() - age_seconds
    os.utime(directory, (stamp, stamp))
    return directory


@pytest.mark.privacy
def test_a_killed_runs_intermediates_are_removed_by_the_next_run(
    male: IngestResult, empty_references: Path, tmp_path: Path
) -> None:
    """``finally`` never runs for a process killed outright, so the next run cleans up --
    even one with nothing to compute, since that is the run most likely to come next on a
    machine whose references are not yet built."""
    cache = tmp_path / "cache"
    stale = _abandoned(cache, ".run-killed", age_seconds=2 * stage._STALE_SCRATCH_SECONDS)
    _infer(male, empty_references, tmp_path)
    assert not stale.exists()


@pytest.mark.privacy
def test_a_live_runs_directory_and_the_reference_pcas_are_left_alone(
    male: IngestResult, empty_references: Path, tmp_path: Path
) -> None:
    """A second run may be live beside this one, and the reference PCAs are kept by design;
    only an abandoned per-run directory is swept."""
    cache = tmp_path / "cache"
    live = _abandoned(cache, ".run-live", age_seconds=60)
    old_pca = cache / "refpca-0123456789abcdef.eigenvec"
    old_pca.write_text("PC1\n", encoding="utf-8")
    stamp = time.time() - 2 * stage._STALE_SCRATCH_SECONDS
    os.utime(old_pca, (stamp, stamp))
    lookalike = _abandoned(cache, "run-not-ours", age_seconds=2 * stage._STALE_SCRATCH_SECONDS)

    _infer(male, empty_references, tmp_path)

    assert live.is_dir() and old_pca.is_file() and lookalike.is_dir()


def test_progress_is_reported_once_the_slow_work_begins(
    male: IngestResult,
    verified_panel: Path,
    placed_ancestry: AncestryContext,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _found_plink(monkeypatch, tmp_path)
    monkeypatch.setattr(stage, "build_reference_pca", lambda *a, **k: _FakePca())
    monkeypatch.setattr(stage, "project", lambda *a, **k: _FakeProjection())
    monkeypatch.setattr(stage, "read_aadr_population_labels", lambda *a: object())
    monkeypatch.setattr(stage, "build_population_model", lambda *a: object())
    monkeypatch.setattr(stage, "_project_sample", lambda *a: _FakeProjection())
    monkeypatch.setattr(stage, "place", lambda *a: placed_ancestry.population.placement)

    messages: list[str] = []
    _infer(male, verified_panel.parents[1], tmp_path, progress=messages.append)
    assert any("reference PCA" in message for message in messages)
