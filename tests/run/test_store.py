"""The run store (roadmap M4.2).

Organised by the property each test defends. The store's job is to stay usable when a
bundle is not, so most of these damage something on disk and then check that the *rest* of
the store still answers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from genetics.engine.cards import KnowledgePack
from genetics.engine.evidence import AssembledCard
from genetics.privacy import find_genotypes
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    CARDS_NAME,
    INCOMING_PREFIX,
    MANIFEST_NAME,
    QC_NAME,
    BundleError,
    write_bundle,
)
from genetics.run.store import (
    BUNDLE_MEMBERS,
    RunNotFoundError,
    RunStatus,
    delete_run,
    list_runs,
    load_run,
    prune_incomplete,
    resolve_run,
    summarise_run,
)


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


def _save(
    root: Path,
    qc: QCReport,
    pack: KnowledgePack,
    *,
    run_id: str | None = None,
    cards: tuple[AssembledCard, ...] = (),
    created_at: datetime | None = None,
) -> Path:
    return write_bundle(
        qc=qc,
        cards=cards,
        pack=pack,
        runs_root=root,
        run_id=run_id,
        created_at=created_at,
        lock_path=root.parent / "absent.lock",
        tools_root=root.parent / "tools",
    )


def _edit_manifest(directory: Path, **changes: object) -> None:
    """Change the manifest without touching the payload digests it records."""
    path = directory / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(changes)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_a_saved_run_is_listed_with_what_its_manifest_recorded(
    runs_root: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
) -> None:
    path = _save(runs_root, sample_qc, sample_pack, cards=sample_cards)

    listing = list_runs(runs_root)
    assert listing.root == runs_root.resolve()
    assert listing.verified is False
    (run,) = listing.runs
    assert run.run_id == path.name
    assert run.status is RunStatus.READABLE
    assert run.format_version == BUNDLE_FORMAT_VERSION
    assert run.card_count == 1
    assert run.with_interpretation == 1
    assert run.vendor == "ancestrydna_v2"
    assert run.created_at is not None and run.created_at.endswith("Z")
    assert run.detail is None


def test_no_runs_yet_is_a_state_rather_than_an_error(tmp_path: Path) -> None:
    """M0.6's rule, one milestone later: a fresh checkout has saved nothing, and that is
    the expected condition rather than a fault to report in red."""
    missing = list_runs(tmp_path / "never-created")
    assert missing.runs == () and missing.incomplete == ()

    empty = tmp_path / "runs"
    empty.mkdir()
    assert list_runs(empty).runs == ()


def test_one_damaged_bundle_does_not_take_the_listing_with_it(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """The property the whole module is shaped around.

    ``read_bundle`` raises on damage, which is right for a read and wrong for a listing:
    building the list on it would mean one corrupt directory out of forty hides the other
    thirty-nine, at exactly the moment somebody is looking for them.
    """
    _save(runs_root, sample_qc, sample_pack, run_id="run_a")
    broken = _save(runs_root, sample_qc, sample_pack, run_id="run_b")
    _save(runs_root, sample_qc, sample_pack, run_id="run_c")
    (broken / MANIFEST_NAME).write_bytes(b"\xff\xfe\x00not json at all\x00")

    listing = list_runs(runs_root)
    assert {run.run_id for run in listing.runs} == {"run_a", "run_b", "run_c"}
    by_id = {run.run_id: run for run in listing.runs}
    assert by_id["run_b"].status is RunStatus.DAMAGED
    assert by_id["run_b"].detail is not None and "could not be read" in by_id["run_b"].detail
    assert by_id["run_a"].ok and by_id["run_c"].ok
    assert listing.damaged == (by_id["run_b"],)


def test_a_newer_format_is_reported_as_a_version_problem_not_as_damage(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """Two different remedies: find the other version of the tool, or restore a backup.

    The fields a v1 reader can still recognise are reported anyway. Under the additive
    contract a newer manifest is a superset, so the timestamp and the counts are readable
    even when the bundle is not -- and a bare id here would make "which of these is the one
    from Tuesday" unanswerable at the moment the user needs to find it.
    """
    path = _save(runs_root, sample_qc, sample_pack, run_id="future")
    _edit_manifest(path, format_version=BUNDLE_FORMAT_VERSION + 1)

    (run,) = list_runs(runs_root).runs
    assert run.status is RunStatus.FUTURE_VERSION
    assert run.detail is not None and "Use the version of the tool that wrote it" in run.detail
    assert run.created_at is not None
    assert run.card_count == 0, "still readable from a manifest this engine cannot honour"


def test_a_missing_payload_file_is_damage_even_though_the_manifest_parses(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """A stat call, not a read -- so the cheap listing still catches a half-deleted bundle."""
    path = _save(runs_root, sample_qc, sample_pack, run_id="half")
    (path / QC_NAME).unlink()

    (run,) = list_runs(runs_root).runs
    assert run.status is RunStatus.DAMAGED
    assert run.detail is not None and QC_NAME in run.detail


def test_a_manifest_recording_no_payload_at_all_is_damage_not_a_readable_run(
    runs_root: Path,
) -> None:
    """Listing and reading have to mean the same thing by "damaged", and they did not.

    A manifest with no ``files`` key produced no names to check, so nothing was found absent
    and the row came back ``readable`` -- complete with a card count -- for a directory
    holding no payload whatsoever, while ``read_bundle`` on the same path refused it. The
    listing was vouching for a bundle nothing could open. Both sides now require the same
    set, taken from the writer's own ``PAYLOAD_FILES``.
    """
    from genetics.run.bundle import read_bundle

    hollow = runs_root / "hollow"
    hollow.mkdir()
    (hollow / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "format_version": BUNDLE_FORMAT_VERSION,
                "run_id": "hollow",
                "created_at": "2026-08-17T00:00:00Z",
                "provenance": {},
                "counts": {"cards": 3},
            }
        ),
        encoding="utf-8",
    )

    (run,) = list_runs(runs_root).runs
    assert run.status is RunStatus.DAMAGED
    assert run.detail is not None and "no digest recorded" in run.detail
    with pytest.raises(BundleError):
        read_bundle(hollow)


def test_a_payload_name_that_points_outside_the_bundle_is_damage(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack, tmp_path: Path
) -> None:
    """The reader is reading a file it did not write, and ``manifest.files`` is turned into
    a path.

    Left unchecked, an edited manifest naming ``../elsewhere`` sends the listing to stat --
    and ``read_bundle`` to *hash* -- a file outside the bundle, then reports the result as
    this run's integrity. Tampering is outside the format's threat model and this is not a
    hole in it; the point is duller. A manifest naming a file somewhere else is damaged, and
    saying so beats a digest mismatch against a file the user never associated with the run.
    """
    from genetics.run.bundle import read_bundle

    outsider = tmp_path / "elsewhere.json"
    outsider.write_text("{}", encoding="utf-8")
    path = _save(runs_root, sample_qc, sample_pack, run_id="crooked")
    # Added beside the real entries rather than replacing them: `read_bundle` checks that
    # the required payload files are recorded *before* it turns any name into a path, so
    # wiping the map trips that earlier check and never reaches the one under test.
    recorded = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))["files"]
    _edit_manifest(path, files={**recorded, "../../elsewhere.json": "0" * 64})

    (run,) = list_runs(runs_root).runs
    assert run.status is RunStatus.DAMAGED
    assert run.detail is not None and "plain filename" in run.detail

    with pytest.raises(BundleError, match="plain filename"):
        read_bundle(path)


def test_readable_does_not_claim_intact_and_verify_is_what_does(
    runs_root: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
) -> None:
    """The two questions are different, and the status names have to keep them apart.

    An edited payload is invisible to a manifest-only listing by construction -- that is the
    cost of not digesting gigabytes to draw a list. Calling the fast answer ``ok`` would have
    promised the slow one. This drives both paths over the same tampered bundle so the
    distinction is demonstrated rather than described.
    """
    path = _save(runs_root, sample_qc, sample_pack, cards=sample_cards)
    payload = json.loads((path / CARDS_NAME).read_text(encoding="utf-8"))
    payload["cards"][0]["summary"] = "Something the engine never said."
    (path / CARDS_NAME).write_text(json.dumps(payload), encoding="utf-8")

    fast = list_runs(runs_root)
    assert fast.verified is False
    assert fast.runs[0].status is RunStatus.READABLE

    checked = list_runs(runs_root, verify=True)
    assert checked.verified is True
    assert checked.runs[0].status is RunStatus.DAMAGED
    assert checked.runs[0].detail is not None
    assert "does not match the digest" in checked.runs[0].detail


def test_an_unreadable_payload_does_not_take_the_verify_listing_with_it(
    runs_root: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Found on the self-pass, and it is this module's own governing property, broken.

    ``--verify`` calls ``read_bundle``, which *digests* each payload -- so it opens files,
    and a locked file on Windows, a permission change or a bad sector raises ``OSError``,
    which is not a ``BundleError``. Catching only the latter let it escape ``list_runs``
    entirely: one unreadable bundle hid the other thirty-nine, which is precisely the failure
    the manifest-only path was designed to avoid, reintroduced on the one path that opens
    anything. Reproduced by execution before the fix.
    """
    from genetics.run import bundle as bundle_module

    _save(runs_root, sample_qc, sample_pack, run_id="locked")
    _save(runs_root, sample_qc, sample_pack, run_id="fine")

    # Patched at ``_digest`` because that is where the open happens: it is the only thing on
    # the verify path that touches file *contents*, and therefore the only place the disk
    # gets to say no.
    real_digest = bundle_module._digest

    def refuse_locked(path: Path) -> str:
        if path.name == CARDS_NAME and path.parent.name == "locked":
            raise PermissionError(13, "The process cannot access the file")
        return real_digest(path)

    monkeypatch.setattr(bundle_module, "_digest", refuse_locked)
    listing = list_runs(runs_root, verify=True)

    by_id = {run.run_id: run for run in listing.runs}
    assert set(by_id) == {"locked", "fine"}, "the readable bundle survived its neighbour"
    assert by_id["locked"].status is RunStatus.DAMAGED
    assert by_id["locked"].detail is not None and "cannot access" in by_id["locked"].detail
    assert by_id["fine"].ok


def test_prune_reports_what_it_actually_removed(
    runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ignore_errors=True`` is right, and it has to be paid for by looking afterwards.

    One locked directory must not stop the others being cleaned -- but paired with an
    unconditional append it made this function report removing a directory still sitting on
    disk, and the CLI print a byte count for space that was never freed. A swallowed error
    is only safe if somebody checks.
    """
    stuck = runs_root / f"{INCOMING_PREFIX}stuck"
    stuck.mkdir()
    (stuck / QC_NAME).write_text("{}", encoding="utf-8")

    def swallow(path: Path, ignore_errors: bool = False, **kwargs: object) -> None:
        return None  # what rmtree(..., ignore_errors=True) does against a locked tree

    monkeypatch.setattr("genetics.run.store.shutil.rmtree", swallow)
    assert prune_incomplete(runs_root) == ()
    assert stuck.is_dir(), "the fixture must leave it there, or this proves nothing"


def test_an_interrupted_save_is_reported_separately_rather_than_listed_or_hidden(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """Skipping it by shape is required; skipping it *silently* is the refs-status failure.

    The M3.3--M3.6 review found a stale multi-gigabyte intermediate reported as nothing at
    all, with no line telling the user it existed. After M8 an interrupted save is the same
    size and the same shape of mistake, so it is counted, sized, and given a command.
    """
    _save(runs_root, sample_qc, sample_pack, run_id="real")
    staging = runs_root / f"{INCOMING_PREFIX}20260817T101112Z-deadbeef"
    staging.mkdir()
    (staging / CARDS_NAME).write_text("x" * 4096, encoding="utf-8")

    listing = list_runs(runs_root)
    assert [run.run_id for run in listing.runs] == ["real"]
    (orphan,) = listing.incomplete
    assert orphan.run_id == "20260817T101112Z-deadbeef"
    assert orphan.size_bytes == 4096


def test_runs_are_ordered_by_the_timestamp_they_recorded_not_by_their_name(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """``new_run_id`` sorts chronologically, but ``--run-id`` exists and a chosen name does
    not -- which would scatter named runs through a list the reader takes as chronological."""
    _save(
        runs_root,
        sample_qc,
        sample_pack,
        run_id="aaa-oldest",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    _save(
        runs_root,
        sample_qc,
        sample_pack,
        run_id="zzz-newest",
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
    )

    assert [run.run_id for run in list_runs(runs_root).runs] == ["zzz-newest", "aaa-oldest"]


def test_a_renamed_bundle_is_addressed_by_its_directory_name_and_says_so(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """One id, not two. The directory name is what ``load`` and ``delete`` resolve against,
    so it is what the listing shows -- and the disagreement is reported rather than one of
    the two names being silently preferred."""
    path = _save(runs_root, sample_qc, sample_pack, run_id="original")
    path.rename(runs_root / "renamed")

    (run,) = list_runs(runs_root).runs
    assert run.run_id == "renamed"
    assert run.status is RunStatus.READABLE, "renaming does not damage anything"
    assert run.detail is not None and "original" in run.detail
    assert load_run("renamed", runs_root).run_id == "original", "the manifest still says so"


# ---------------------------------------------------------------------------
# Resolving and loading
# ---------------------------------------------------------------------------


def test_load_run_reads_a_saved_run_by_id(
    runs_root: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
) -> None:
    path = _save(runs_root, sample_qc, sample_pack, cards=sample_cards)
    bundle = load_run(path.name, runs_root)

    assert bundle.run_id == path.name
    assert bundle.card_count == 1
    assert bundle.cards[0].citations, "citations survive the trip through the store"


def test_an_unknown_id_is_not_found_rather_than_damaged(runs_root: Path) -> None:
    """Different question, different answer: nothing is broken, there is simply no such run."""
    with pytest.raises(RunNotFoundError, match="no run 'nope'"):
        load_run("nope", runs_root)


@pytest.mark.parametrize(
    "bad", ["D:elsewhere", "..", ".", "", "a/b", "a\\b", f"{INCOMING_PREFIX}x", ".draft"]
)
def test_reading_and_deleting_refuse_the_same_ids_the_writer_does(
    runs_root: Path, bad: str
) -> None:
    """One check, shared with ``write_bundle``, rather than a second rule that looks alike.

    A deletion validating its target by its own similar-but-separate rule is the
    two-names-for-one-thing failure this project has now hit at M0.4, M3.7 and M4.1. The
    ids here are the writer's own refused set, including the drive-relative form that
    contains no separator at all.
    """
    for operation in (resolve_run, delete_run):
        with pytest.raises(BundleError, match="run id"):
            operation(bad, runs_root)


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def test_delete_removes_one_run_and_leaves_the_others(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    _save(runs_root, sample_qc, sample_pack, run_id="keep")
    doomed = _save(runs_root, sample_qc, sample_pack, run_id="drop")

    assert delete_run("drop", runs_root) == doomed
    assert not doomed.exists()
    assert [run.run_id for run in list_runs(runs_root).runs] == ["keep"]


def test_delete_refuses_a_directory_that_is_not_a_bundle(runs_root: Path) -> None:
    """The check that stops ``runs delete`` being a recursive remove pointed at an argument.

    The runs root is a directory on the user's own disk. A name arriving from the command
    line names *something*, and without this the something is whatever happens to be there.
    """
    intruder = runs_root / "my-notes"
    intruder.mkdir()
    (intruder / "important.txt").write_text("not a bundle", encoding="utf-8")

    with pytest.raises(BundleError, match="not one"):
        delete_run("my-notes", runs_root)
    assert (intruder / "important.txt").is_file(), "refusing must not half-delete"


def test_delete_accepts_the_wreckage_of_a_bundle(runs_root: Path) -> None:
    """An empty directory is what a bundle looks like after somebody emptied it by hand.

    Refusing that would leave the store with a row that ``list`` reports as damaged and
    nothing in the tool can remove -- a state whose only remedy is a file manager.
    """
    empty = runs_root / "gutted"
    empty.mkdir()

    assert delete_run("gutted", runs_root) == empty
    assert not empty.exists()


def test_a_newer_format_run_is_not_counted_as_damaged(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """The status distinction has to survive being summarised, or it buys nothing.

    ``damaged`` was "anything not readable", so a single newer-format bundle produced a
    footer reading "1 of 1 run(s) could not be read" -- pointing the user at a backup when
    the remedy is the tool that wrote it. The status said one thing and the summary of it
    said the other.
    """
    path = _save(runs_root, sample_qc, sample_pack, run_id="newer")
    _edit_manifest(path, format_version=BUNDLE_FORMAT_VERSION + 1)
    broken = _save(runs_root, sample_qc, sample_pack, run_id="broken")
    (broken / MANIFEST_NAME).write_bytes(b"\xff\xfe not json")

    listing = list_runs(runs_root)
    assert [run.run_id for run in listing.damaged] == ["broken"]
    assert [run.run_id for run in listing.needs_a_newer_engine] == ["newer"]


def test_an_alias_inside_the_store_is_refused_the_way_the_listing_refuses_it(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """``list_runs`` excluded symlinks; ``resolve_run`` accepted ones resolving inside root.

    So ``runs/alias -> runs/real`` was invisible to the listing, passed every check in
    ``delete``, and then died in ``shutil.rmtree``, which refuses a link -- an OSError from
    a command that had already decided the target was fine. Two rules, one of which nobody
    could see.
    """
    real = _save(runs_root, sample_qc, sample_pack, run_id="real")
    alias = runs_root / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(real)],
            capture_output=True,
            check=False,
        )
        if not alias.is_dir():
            pytest.skip("this platform grants neither a symlink nor a junction here")

    assert [run.run_id for run in list_runs(runs_root).runs] == ["real"]
    with pytest.raises(BundleError, match="is a link, not a run"):
        delete_run("alias", runs_root)
    assert real.is_dir(), "the bundle the alias pointed at must survive"


def test_a_bundle_from_a_newer_engine_can_still_be_deleted(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """The case that made the filename rule insufficient, found by running the CLI.

    A v2 bundle carries payload this version has never heard of. Identifying a bundle by its
    contents alone would therefore refuse to delete it -- and it cannot be *read* either,
    because the version gate stops that. A run you can neither read nor remove is a worse
    outcome than either failure on its own, so the manifest is asked first: a directory that
    declares a bundle format version is a bundle, whatever else is in it.
    """
    path = _save(runs_root, sample_qc, sample_pack, run_id="from_the_future")
    _edit_manifest(path, format_version=BUNDLE_FORMAT_VERSION + 1)
    (path / "dosages.run.parquet").write_bytes(b"payload this engine has never heard of")

    assert list_runs(runs_root).runs[0].status is RunStatus.FUTURE_VERSION
    assert delete_run("from_the_future", runs_root) == path
    assert not path.exists()


def test_the_wreckage_member_set_is_pinned_to_what_the_writer_writes() -> None:
    """A bundle with no manifest has nothing left to identify it but its filenames.

    That fallback is the only thing :data:`BUNDLE_MEMBERS` governs, and it is the half that
    goes stale: a milestone adding a payload file without adding it here would make that
    file's presence enough to refuse the wreckage of a bundle it wrote itself. Pinned
    against the writer's own list so the drift fails in the commit that causes it.
    """
    from genetics.run import bundle

    assert {bundle.MANIFEST_NAME, *bundle.PAYLOAD_FILES} == BUNDLE_MEMBERS


def test_delete_refuses_a_link_pointing_out_of_the_runs_root(
    runs_root: Path, tmp_path: Path
) -> None:
    """A plain name can still be a symlink, which is why containment is checked on the
    *resolved* path. ``check_run_id`` proves the id is not a path; it cannot prove the
    directory it names is really here."""
    outside = tmp_path / "not-the-store"
    outside.mkdir()
    (outside / "keepme.txt").write_text("elsewhere", encoding="utf-8")
    link = runs_root / "sneaky"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Windows refuses symlinks without Developer Mode or elevation, and this is the
        # platform the project targets (AGENTS.md 4.9) -- so falling back to a directory
        # junction, which needs neither, is what keeps the check verified on the machine it
        # matters most on rather than only in Linux CI.
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            check=False,
        )
        if not link.is_dir() or link.resolve() == link:
            pytest.skip("this platform grants neither a symlink nor a junction here")

    with pytest.raises(BundleError, match="not under the runs root"):
        delete_run("sneaky", runs_root)
    assert (outside / "keepme.txt").is_file()


def test_prune_removes_staging_directories_and_nothing_else(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    kept = _save(runs_root, sample_qc, sample_pack, run_id="kept")
    staging = runs_root / f"{INCOMING_PREFIX}abandoned"
    staging.mkdir()
    (staging / QC_NAME).write_text("{}", encoding="utf-8")

    (removed,) = prune_incomplete(runs_root)
    assert removed.run_id == "abandoned"
    assert not staging.exists()
    assert kept.is_dir()
    assert list_runs(runs_root).incomplete == ()


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_a_run_summary_cannot_print_a_genotype(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """Manifest-derived fields are scanned by the writer, but that is the *writer's*
    property -- a bundle read here may have been written by another version or hand-edited,
    so the summary carries the mixin rather than an assumption about somebody else's code."""
    path = _save(runs_root, sample_qc, sample_pack, run_id="private")
    summary = summarise_run(path)
    dirty = "\t".join(("rs4988235", "2", "136608646", "A", "G"))
    poisoned = type(summary)(
        run_id=summary.run_id, path=summary.path, status=summary.status, vendor=dirty
    )

    assert find_genotypes(repr(poisoned)) == []
    assert "private" in repr(summary), "identifiers stay visible"


@pytest.mark.privacy
def test_the_store_never_writes_inside_the_repository(tmp_path: Path) -> None:
    """Every entry point resolves its root through the writer's own check, so an unsafe
    location is refused by ``list`` and ``delete`` exactly as it is by ``write_bundle``."""
    from genetics.paths import UnsafeDataDirError, repo_root

    inside = repo_root() / "scratch_runs"
    for call in (lambda: list_runs(inside), lambda: resolve_run("x", inside)):
        with pytest.raises(UnsafeDataDirError, match="inside the repository"):
            call()
    assert not inside.exists()


def test_a_bundle_removed_from_disk_disappears_from_the_listing(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    """Save/load/list/delete has to close: what delete removed, list must stop offering."""
    path = _save(runs_root, sample_qc, sample_pack, run_id="ephemeral")
    assert list_runs(runs_root).runs[0].run_id == "ephemeral"

    shutil.rmtree(path)
    assert list_runs(runs_root).runs == ()
    with pytest.raises(RunNotFoundError):
        load_run("ephemeral", runs_root)
