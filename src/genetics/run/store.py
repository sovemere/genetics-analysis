"""The run store: finding saved runs, and getting rid of them (roadmap M4.2).

:mod:`genetics.run.bundle` owns the format of one bundle. This module owns the *directory
the bundles live in* -- listing what is there, resolving a run id to a path, and deleting.
Three decisions are load-bearing.

**Listing reports; it does not validate.** It reads each ``manifest.json`` and nothing
else: no payload is opened and no digest is computed. Two reasons, and the second is the
one that matters. Cost is the obvious one -- M8 adds imputed dosages and M9 per-score
tables, so digesting every bundle to draw a list would grow without bound. The real reason
is that :func:`~genetics.run.bundle.read_bundle` *raises* on a damaged bundle, so a listing
built on it would fail entirely because one directory out of forty is corrupt -- and
listing is precisely the command someone runs *because* something is wrong. So damage
becomes a row with a status, the way ``genetics doctor`` reports a missing tool rather than
exiting red on a fresh checkout. ``--verify`` is available for when the question really is
"is my saved data intact", and :attr:`RunListing.verified` records which question was asked,
so ``readable`` can never be mistaken for ``verified``.

**A staging directory is skipped as a run and reported as itself.** ``write_bundle`` cleans
up after any exception, but a process killed outright (or a machine losing power) leaves
``.incoming-<id>`` behind, and after M8 that could be gigabytes. Silently filtering it out
of the listing is the failure the M3.3--M3.6 review found in ``refs status``: a stale
multi-gigabyte intermediate reported as nothing at all, with no line telling the user it
was there or what to do about it. So :class:`RunListing` carries them separately and
:func:`prune_incomplete` removes them.

**Deletion is the one irreversible operation in the codebase, so its target is checked
structurally rather than trusted.** A run id goes through the writer's own
:func:`~genetics.run.bundle.check_run_id`, the resolved path must still sit directly under
the runs root (which catches a symlink pointing out of it, where a name-based check cannot),
and the directory must identify itself as a bundle. That last one is what stops ``genetics
runs delete`` from being a recursive remove aimed at whatever string arrives on the command
line -- and it asks the manifest before it asks the filenames, because a bundle from a newer
engine carries payload this version has never heard of, and a name-based rule alone would
leave the user a run they can neither read nor remove.
"""

from __future__ import annotations

import shutil
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from genetics.privacy import NoGenotypeRepr
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    INCOMING_PREFIX,
    MANIFEST_NAME,
    PAYLOAD_FILES,
    BundleError,
    RunBundle,
    check_run_id,
    payload_name,
    read_bundle,
    read_manifest,
    resolve_runs_root,
)

BUNDLE_MEMBERS: frozenset[str] = frozenset({MANIFEST_NAME, *PAYLOAD_FILES})
"""Every filename a bundle may contain.

Used only to recognise *wreckage* -- a bundle whose manifest is gone, which has nothing
left to identify it but its filenames. An intact bundle is identified by its manifest
instead, so a payload file added by M5, M8 or M9 does not make new runs undeletable. It
would make their wreckage undeletable, which is why this is pinned against the writer's own
list in ``test_store.py`` rather than maintained by memory."""


class RunStatus(StrEnum):
    """What a listing was able to establish about one directory.

    Note what ``READABLE`` claims: the manifest parsed, its version is one this engine
    implements, and every payload file it names is present. It does *not* claim the payload
    is intact -- that costs a full digest pass and is what ``--verify`` is for. Naming it
    ``ok`` would have quietly promised the stronger thing.
    """

    READABLE = "readable"
    FUTURE_VERSION = "future-version"
    """Written by a newer engine. Distinguished from damage because M4.2 requires it to be:
    the remedy is a different version of the tool, not a restore from backup."""

    DAMAGED = "damaged"


@dataclass(frozen=True)
class RunSummary(NoGenotypeRepr):
    """One run, as much as its manifest could say.

    Inherits :class:`NoGenotypeRepr` even though every field here is manifest-derived and
    the writer scans the manifest before writing it. That scan is a property of *this*
    engine's writer; these fields are read back from a file that may have been written by
    another version, or edited by hand. "It cannot contain a genotype" would be an
    assumption about somebody else's code.

    Every field except ``run_id``, ``path`` and ``status`` is optional, because a damaged
    manifest is exactly the case where they are unavailable and the row still has to render.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("run_id", "status", "card_count")

    run_id: str
    """The directory name, which is the id every other operation here takes.

    ``write_bundle`` makes the two identical. If a manifest disagrees -- someone renamed the
    directory after the fact -- the directory name wins, because it is what ``delete`` and
    ``load`` resolve against, and the disagreement is reported in ``detail`` rather than
    silently picking one.
    """

    path: Path
    status: RunStatus
    created_at: str | None = None
    format_version: int | None = None
    engine_version: str | None = None
    card_count: int | None = None
    with_interpretation: int | None = None
    vendor: str | None = None
    detail: str | None = None
    """Why the status is what it is. ``None`` when there is nothing to explain."""

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.READABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "path": str(self.path),
            "status": str(self.status),
            "created_at": self.created_at,
            "format_version": self.format_version,
            "engine_version": self.engine_version,
            "card_count": self.card_count,
            "with_interpretation": self.with_interpretation,
            "vendor": self.vendor,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class IncompleteWrite:
    """A ``.incoming-`` directory: a save that started and did not finish."""

    run_id: str
    """The id the interrupted write was claiming, prefix stripped. That id is still free --
    nothing was ever promoted to it -- so reporting it is what tells the user the run they
    were saving is simply absent, rather than half-present under some other name."""

    path: Path
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "path": str(self.path), "size_bytes": self.size_bytes}


@dataclass(frozen=True)
class RunListing:
    """Everything under one runs root."""

    root: Path
    runs: tuple[RunSummary, ...]
    incomplete: tuple[IncompleteWrite, ...]
    verified: bool
    """Whether payload digests were checked. Carried on the listing rather than left to be
    inferred from the statuses, because ``readable`` means two different strengths of claim
    depending on the answer and a consumer cannot tell them apart from the rows alone."""

    @property
    def damaged(self) -> tuple[RunSummary, ...]:
        """Runs this engine could not read *and* cannot fix by being a different version.

        Deliberately excludes ``FUTURE_VERSION``, which :class:`RunStatus` goes out of its
        way to separate from damage. Lumping them together made a single newer-format bundle
        produce a footer reading "1 of 1 run(s) could not be read" -- steering the user
        toward a backup when the remedy is the newer tool that wrote it.
        """
        return tuple(run for run in self.runs if run.status is RunStatus.DAMAGED)

    @property
    def needs_a_newer_engine(self) -> tuple[RunSummary, ...]:
        """Runs written by a later version. Intact, and unreadable here."""
        return tuple(run for run in self.runs if run.status is RunStatus.FUTURE_VERSION)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "verified": self.verified,
            "runs": [run.to_dict() for run in self.runs],
            "incomplete": [item.to_dict() for item in self.incomplete],
        }


class RunNotFoundError(BundleError):
    """Raised when a run id names nothing under the runs root.

    A :class:`~genetics.run.bundle.BundleError` so that one ``except`` at the CLI boundary
    covers every way a run can fail to load, and a separate class so the CLI can say
    "no such run" rather than reporting it as damage.
    """


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _count(value: Any) -> int | None:
    # bool is an int in Python and `"cards": true` in a hand-edited manifest would
    # otherwise be reported as a card count of 1.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def is_link(path: Path) -> bool:
    """True for a link of any kind: POSIX symlink, Windows symlink, or Windows junction.

    ``Path.is_symlink()`` alone is not enough on the platform this project targets. A
    Windows directory junction is a reparse point and **not** a symlink, so ``is_symlink()``
    returns False for one -- which meant a junction under the runs root was listed as a run,
    passed every check in ``delete_run``, and then died inside ``shutil.rmtree`` with
    "Cannot call rmtree on a symbolic link". Nothing was lost, because rmtree does recognise
    it, but the store had offered the user a row it could not act on.

    ``os.path.isjunction`` would say this in one call and arrived in 3.12, while this project
    supports 3.11 and CI runs both. The attribute check below is what that function does
    internally, so the answer is the same on either.
    """
    if path.is_symlink():
        return True
    try:
        attributes: int = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        # No `st_file_attributes` outside Windows; an OSError means the entry went away
        # between the listing and this call, which is not a link either.
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _directory_size(directory: Path) -> int:
    """Bytes on disk, tolerating a file that vanishes underneath the walk.

    ``stat`` only -- nothing here opens a file, so this stays cheap even once a bundle
    carries M8's dosages.
    """
    total = 0
    for item in directory.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def summarise_run(directory: Path) -> RunSummary:
    """Describe one bundle directory from its manifest alone. Never raises.

    Everything after the version gate is read with ``.get`` rather than a required-key
    lookup. A manifest that is damaged enough to be missing ``run_id`` still has to produce
    a row -- a listing that raised on it would take the other thirty-nine bundles with it.
    """
    run_id = directory.name
    try:
        manifest = read_manifest(directory)
    except BundleError as exc:
        return RunSummary(run_id=run_id, path=directory, status=RunStatus.DAMAGED, detail=str(exc))

    declared = manifest.get("format_version")
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        return RunSummary(
            run_id=run_id,
            path=directory,
            status=RunStatus.DAMAGED,
            detail=f"{MANIFEST_NAME}: format_version must be an integer of 1 or greater",
        )

    provenance = _mapping_or_empty(manifest.get("provenance"))
    counts = _mapping_or_empty(manifest.get("counts"))
    common: dict[str, Any] = {
        "run_id": run_id,
        "path": directory,
        "created_at": _text(manifest.get("created_at")),
        "format_version": declared,
        "engine_version": _text(provenance.get("engine_version")),
        "card_count": _count(counts.get("cards")),
        "with_interpretation": _count(counts.get("with_interpretation")),
        "vendor": _text(_mapping_or_empty(provenance.get("input")).get("vendor")),
    }

    if declared > BUNDLE_FORMAT_VERSION:
        # Reported from the fields a v1 reader can still recognise, deliberately: under the
        # additive contract a newer manifest is a superset, so the timestamp and the counts
        # are readable even when the bundle as a whole is not. A listing that showed a bare
        # id here would make "which of these is the one from Tuesday" unanswerable at
        # exactly the moment the user needs to find it.
        return RunSummary(
            **common,
            status=RunStatus.FUTURE_VERSION,
            detail=(
                f"written in bundle format {declared}; this engine implements "
                f"{BUNDLE_FORMAT_VERSION}. Use the version of the tool that wrote it."
            ),
        )

    recorded = _mapping_or_empty(manifest.get("files"))
    # The same requirement `read_bundle` enforces, and it has to be the same or the two
    # disagree about what "damaged" means -- which is the divergence this module's docstring
    # promises to avoid. Without it a manifest carrying no `files` key at all listed as
    # `readable`, complete with a card count, while a read of the identical directory raised
    # "missing required key 'files'". The listing was reporting on a bundle nothing could
    # open.
    unrecorded = sorted(set(PAYLOAD_FILES) - set(recorded))
    if unrecorded:
        return RunSummary(
            **common,
            status=RunStatus.DAMAGED,
            detail=f"{MANIFEST_NAME}.files: no digest recorded for {', '.join(unrecorded)}",
        )

    try:
        names = [payload_name(name, f"{MANIFEST_NAME}.files") for name in recorded]
    except BundleError as exc:
        # A recorded name that is not a plain filename would otherwise send this stat, and
        # `read_bundle` a digest, at a file outside the bundle. It is a damaged manifest, and
        # reporting it as one beats reporting an integrity failure against a file the user
        # never associated with this run.
        return RunSummary(**common, status=RunStatus.DAMAGED, detail=str(exc))

    absent = sorted(name for name in names if not (directory / name).is_file())
    if absent:
        return RunSummary(
            **common,
            status=RunStatus.DAMAGED,
            detail=f"payload file(s) recorded in the manifest but absent: {', '.join(absent)}",
        )

    recorded_id = _text(manifest.get("run_id"))
    renamed = (
        None
        if recorded_id is None or recorded_id == run_id
        else (
            f"this directory is named {run_id!r} but the manifest records the run as "
            f"{recorded_id!r}; it was renamed after it was written. Commands here address "
            "it by directory name."
        )
    )
    return RunSummary(**common, status=RunStatus.READABLE, detail=renamed)


def _verify(summary: RunSummary) -> RunSummary:
    """Re-read a readable-looking bundle in full, digests included.

    ``OSError`` is caught alongside ``BundleError``, and that is the whole point rather than
    defensive padding. ``read_bundle`` digests each payload, which means it *opens* files --
    so a locked file on Windows, a permission change, or a bad sector raises something that
    is not a ``BundleError``, and catching only the latter let it escape ``list_runs`` and
    take the entire listing down. One unreadable bundle hiding the other thirty-nine is the
    exact failure this module is built to prevent, reintroduced on the one path that opens
    anything. Same shape as the M3.7-M4.1 review's finding about ``_reference_provenance``:
    a function whose job is to produce a *report* had its degradation made conditional on
    the kind of unreadable.

    Rebuilt with ``replace`` rather than field by field, so a field added to
    :class:`RunSummary` cannot be silently dropped on this path alone.
    """
    if summary.status is not RunStatus.READABLE:
        return summary
    try:
        read_bundle(summary.path)
    except (BundleError, OSError) as exc:
        return replace(summary, status=RunStatus.DAMAGED, detail=str(exc))
    return summary


def _sort_key(summary: RunSummary) -> tuple[str, str]:
    """Newest first, by the timestamp the run *recorded*.

    Not by directory name: ``new_run_id`` is timestamp-led and sorts chronologically, but
    ``--run-id`` exists and a hand-chosen name sorts alphabetically, which would scatter
    named runs through a list the user reads as chronological. A damaged manifest has no
    timestamp and sorts last, where the count in the CLI's footer still accounts for it.
    """
    return (summary.created_at or "", summary.run_id)


def list_runs(runs_root: Path | None = None, *, verify: bool = False) -> RunListing:
    """Every saved run under ``runs_root``, newest first.

    A missing runs directory is an empty listing, not an error: no run has been saved yet
    is the state of every fresh checkout, and M0.6 settled what an error code means here.
    """
    root = resolve_runs_root(runs_root)
    if not root.is_dir():
        return RunListing(root=root, runs=(), incomplete=(), verified=verify)

    summaries: list[RunSummary] = []
    incomplete: list[IncompleteWrite] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or is_link(entry):
            # A link is excluded rather than followed. The store is a set of directories this
            # app wrote; something pointing elsewhere is not one, and listing it would offer
            # `delete` a target it cannot act on -- or, if it pointed outside, one outside
            # the root entirely.
            continue
        if entry.name.startswith(INCOMING_PREFIX):
            incomplete.append(
                IncompleteWrite(
                    run_id=entry.name[len(INCOMING_PREFIX) :],
                    path=entry,
                    size_bytes=_directory_size(entry),
                )
            )
            continue
        if entry.name.startswith("."):
            # Refused at write time, so nothing here made it; skipped rather than reported
            # because a dot directory under the runs root belongs to something else.
            continue
        summaries.append(summarise_run(entry))

    if verify:
        summaries = [_verify(summary) for summary in summaries]

    return RunListing(
        root=root,
        runs=tuple(sorted(summaries, key=_sort_key, reverse=True)),
        incomplete=tuple(incomplete),
        verified=verify,
    )


# ---------------------------------------------------------------------------
# Resolving and loading
# ---------------------------------------------------------------------------


def resolve_run(run_id: str, runs_root: Path | None = None) -> Path:
    """Turn a run id into the directory it names, or raise.

    Two refusals, in this order, because a link can point in two directions and they deserve
    different sentences. ``check_run_id`` proves the id is a plain name; a plain name can
    still be a link, and where it points decides which failure it is:

    * **Out of the store** -- caught by resolving and comparing parents. This is the
      dangerous one, so it says where the path actually went.
    * **Back into the store** -- an alias beside the bundle it points at. Harmless, but
      ``list_runs`` does not show it, so accepting it here would let ``delete`` act on
      something the listing never offered, and ``shutil.rmtree`` refuses a link anyway.

    Ordered containment-first so both stay reachable: with the link check first, no
    non-link path can resolve outside a root that is itself already resolved, and the
    containment branch would be dead code wearing a comment.
    """
    check_run_id(run_id)
    root = resolve_runs_root(runs_root)
    target = root / run_id
    if not target.is_dir():
        raise RunNotFoundError(
            f"no run {run_id!r} under {root}. `genetics runs list` shows what is saved."
        )
    if target.resolve().parent != root:
        raise BundleError(
            f"{target} resolves to {target.resolve()}, which is not under the runs root. "
            "A run must be a real directory in the store, not a link out of it."
        )
    if is_link(target):
        # `list_runs` excludes links outright, so accepting one here made the two disagree
        # about what a run is: an alias pointing at a sibling bundle resolved inside the
        # root, passed every check, and then died in `shutil.rmtree`, which refuses a link --
        # an OSError from a command that had already decided the target was fine. One rule,
        # asked through one function, so the listing and the delete cannot drift apart.
        raise BundleError(
            f"{target} is a link, not a run. The store holds directories this app wrote; "
            "an alias is not one, and `runs list` does not show it either."
        )
    return target


def load_run(run_id: str, runs_root: Path | None = None) -> RunBundle:
    """Read one saved run by id. Digests are checked; see :func:`read_bundle`."""
    return read_bundle(resolve_run(run_id, runs_root))


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def _unexpected_members(directory: Path) -> list[str]:
    return sorted(item.name for item in directory.iterdir() if item.name not in BUNDLE_MEMBERS)


def _declares_itself_a_bundle(directory: Path) -> bool:
    """True when a readable manifest claims a bundle format version.

    This is the identification that has to come first, and getting the order wrong is a
    trap the file-name rule below springs later: a bundle written by a *newer* engine
    carries payload files this version has never heard of, so a name-based check alone
    would refuse to delete it -- leaving the user a run they can neither read (wrong
    version) nor remove (unrecognised contents). A manifest declaring a format version is
    positive identification and does not go stale.
    """
    try:
        manifest = read_manifest(directory)
    except BundleError:
        return False
    declared = manifest.get("format_version")
    return isinstance(declared, int) and not isinstance(declared, bool) and declared >= 1


def delete_run(run_id: str, runs_root: Path | None = None) -> Path:
    """Delete one saved run, irreversibly. Returns the path that was removed.

    The target must be identifiable as a bundle, by either of two rules:

    * its manifest declares a bundle format version -- which covers a bundle from any
      version of this tool, including one newer than the code doing the deleting; or
    * it is empty, or holds only files a bundle is made of. This is the wreckage case: an
      emptied or half-deleted bundle has no manifest to speak for it, and refusing to clean
      that up would leave the store with a row that ``list`` reports as damaged and nothing
      in the tool can remove.

    Anything else is refused. The runs root is a directory on the user's own disk, and a
    command that takes a name and recursively removes whatever it finds under that name is
    one bad argument away from deleting something else.

    There is no undo and no trash. A bundle is the record of an analysis somebody may have
    read and acted on, so the CLI confirms before calling this; the library does not, because
    a prompt buried in a library is a prompt that blocks the first script that calls it.
    """
    target = resolve_run(run_id, runs_root)

    if not _declares_itself_a_bundle(target):
        unexpected = _unexpected_members(target)
        if unexpected:
            shown = ", ".join(unexpected[:5]) + (", ..." if len(unexpected) > 5 else "")
            raise BundleError(
                f"{target} has no readable {MANIFEST_NAME} and contains {shown}, which a run "
                "bundle does not, so this is not one. Refusing to delete it -- remove it "
                "yourself if that is genuinely what you meant."
            )

    shutil.rmtree(target)
    return target


def prune_incomplete(runs_root: Path | None = None) -> tuple[IncompleteWrite, ...]:
    """Remove every ``.incoming-`` staging directory. Returns what was removed.

    Safe by construction rather than by care: the prefix is chosen by ``write_bundle`` and
    refused as a run id, so nothing a user named can appear here. An interrupted save is the
    only thing that creates one, and an interrupted save produced no run -- there is nothing
    in these directories that any bundle refers to.

    **What comes back is what actually went, checked rather than assumed.**
    ``ignore_errors=True`` is right here -- one locked file should not stop the others being
    cleaned -- but paired with an unconditional append it made this function report removing
    a directory still sitting on disk, and the CLI print a byte count for space that was
    never freed. A swallowed error has to be looked for; that is the price of swallowing it.
    """
    listing = list_runs(runs_root)
    removed: list[IncompleteWrite] = []
    for item in listing.incomplete:
        if item.path.parent != listing.root:
            continue
        shutil.rmtree(item.path, ignore_errors=True)
        if not item.path.exists():
            removed.append(item)
    return tuple(removed)
