"""Resumable, verified reference downloads and the licence gate (roadmap M2.2).

This is the only module in the project that makes a network request, and it runs at setup
time, never at analysis time (AGENTS.md 0: no network call at analysis time). Nothing here
touches genotype data: the payloads are public databases, so the concern is size, licence
and integrity rather than privacy.

Resumability is a correctness feature, not a convenience
--------------------------------------------------------
The corpus runs to hundreds of gigabytes and AGENTS.md 0.1C makes long downloads an
accepted cost, so "start again from zero" is not a viable failure mode. Resuming is also
where the interesting bug lives, and :class:`Transport` exists to make that bug
unrepresentable rather than merely tested for.

A client asks for ``Range: bytes=<n>-``. A server may honour it with ``206`` and a body
starting at ``n``, or ignore it entirely and answer ``200`` with the *whole file*. Code
that assumes the first and appends the body to a partial file produces a corrupt result
whose first ``n`` bytes are duplicated -- and for a file with no published checksum, that
corruption is silent. So :class:`Transport` returns
:attr:`Chunked.resumed_from`: the offset the server actually started at, not the one we
requested. The caller obeys that number, and the failure mode disappears.

The honest limit: a resumed download appends to bytes nobody re-read. For a pinned file
the final digest still catches any corruption, whenever it happened. For an unpinned file
on a first fetch there is nothing to compare against, and that is precisely why
:mod:`genetics.refs.lock` records what arrived -- from the second fetch onward the file is
checkable, and a rolling URL that changes underneath a saved run shows up as a
verification failure instead of as new results.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import IO, Any, Protocol

from genetics.refs import lock as lockfile
from genetics.refs import postprocess
from genetics.refs.manifest import Manifest, RemoteFile, Source

USER_AGENT = "genetics-analysis reference fetcher (+https://github.com/)"
CHUNK_BYTES = 1024 * 1024
READ_TIMEOUT_S = 120
"""Generous. Several of these hosts throttle large transfers, and a timeout that fires on
a slow-but-working connection turns a long download into an infinite retry loop."""


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


@dataclass
class Chunked:
    """An open byte stream, plus what the server actually agreed to."""

    stream: IO[bytes]
    total_size: int | None
    """Size of the *complete* resource, not of this response. On a 206 that number comes
    from ``Content-Range``; ``Content-Length`` there describes only the remaining bytes,
    and reading it as the total is how a resumed download ends up reporting 3% complete
    forever."""

    resumed_from: int
    """Offset this body starts at. Zero when the server ignored our Range header."""


class Transport(Protocol):
    """How bytes are obtained. Injectable so tests never touch the network."""

    def open(self, url: str, *, offset: int = 0) -> Chunked: ...


class UrllibTransport:
    """Default transport, on the standard library.

    ``urllib`` rather than ``requests`` deliberately: this is the project's only network
    code path, and it is not worth a dependency that then ships to every user for the
    lifetime of an offline-first tool.
    """

    def __init__(self, timeout: int = READ_TIMEOUT_S) -> None:
        self._timeout = timeout

    def open(self, url: str, *, offset: int = 0) -> Chunked:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if offset > 0:
            request.add_header("Range", f"bytes={offset}-")

        response = urllib.request.urlopen(request, timeout=self._timeout)
        status = getattr(response, "status", None) or response.getcode()

        if status == 206:
            parsed = _parse_content_range(response.headers.get("Content-Range"))
            if parsed is None:
                # A 206 whose Content-Range we cannot read tells us the body is partial
                # but not where it starts. Defaulting to zero was the original behaviour
                # and it silently truncated the head of the file: the caller would open
                # the part "wb" and write a body beginning at `offset` starting at byte 0.
                # For an unpinned file on a first fetch nothing would ever catch that, and
                # the short content would be recorded in the lock as authoritative.
                response.close()
                raise OSError(
                    "server answered 206 without a parseable Content-Range; refusing to "
                    "guess where the partial body starts"
                )
            resumed_from, total = parsed
            if total is None:
                length = response.headers.get("Content-Length")
                total = (resumed_from + int(length)) if length is not None else None
            return Chunked(stream=response, total_size=total, resumed_from=resumed_from)

        # 200 means the server disregarded the Range header and is sending the whole
        # file. Reporting resumed_from=0 is not a fallback; it is the truth, and the
        # caller restarts on it.
        length = response.headers.get("Content-Length")
        return Chunked(
            stream=response,
            total_size=int(length) if length is not None else None,
            resumed_from=0,
        )


def _parse_content_range(header: str | None) -> tuple[int, int | None] | None:
    """Parse ``bytes <start>-<end>/<total>``. Returns ``(start, total)``, or None.

    None means "could not tell", and the caller must treat that as an error rather than
    as a start offset of zero -- see :meth:`UrllibTransport.open`.
    """
    if not header:
        return None
    try:
        spec = header.split(" ", 1)[1]
        span, _, total_text = spec.partition("/")
        start_text = span.split("-", 1)[0]
        total = None if total_text in {"", "*"} else int(total_text)
        return int(start_text), total
    except (IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgressEvent:
    label: str
    """What the file belongs to -- a manifest source id, or a tool id. Named for the role
    rather than for ``Source`` because tool acquisition shares this machinery."""

    filename: str
    downloaded: int
    total: int | None
    unit: str = "bytes"


ProgressCallback = Callable[[ProgressEvent], None]


class FileStatus(StrEnum):
    DOWNLOADED = "downloaded"
    RESUMED = "resumed"
    ALREADY_PRESENT = "already-present"
    VERIFIED = "verified"
    MISSING = "missing"
    FAILED = "failed"


class SourceStatus(StrEnum):
    COMPLETE = "complete"
    BLOCKED_BY_LICENCE = "blocked-by-licence"
    AWAITING_MANUAL_STEP = "awaiting-manual-step"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class FileResult:
    filename: str
    status: FileStatus
    size_bytes: int = 0
    sha256: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status not in {FileStatus.FAILED, FileStatus.MISSING}


@dataclass(frozen=True)
class SourceResult:
    source_id: str
    status: SourceStatus
    files: tuple[FileResult, ...] = ()
    detail: str = ""
    pending_steps: tuple[str, ...] = ()
    """Post-processing steps that are declared but not implemented yet. Reported rather
    than raised: the download succeeded, and failing the command after 60 GB because M8
    has not happened would be actively unhelpful."""
    process_results: tuple[postprocess.ProcessResult, ...] = ()
    """Executed, verified, pending, or failed derived artifacts in manifest order."""

    @property
    def ok(self) -> bool:
        return self.status in {SourceStatus.COMPLETE, SourceStatus.SKIPPED}


@dataclass(frozen=True)
class FetchReport:
    sources: tuple[SourceResult, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.sources)

    def to_dict(self) -> dict[str, Any]:
        """JSON form. The CLI is the agent interface (AGENTS.md 3)."""
        return {
            "ok": self.ok,
            "warnings": list(self.warnings),
            "sources": [
                {
                    **asdict(result),
                    "status": str(result.status),
                    "files": [{**asdict(f), "status": str(f.status)} for f in result.files],
                    "process_results": [
                        {**asdict(p), "status": str(p.status)} for p in result.process_results
                    ],
                }
                for result in self.sources
            ],
        }


class FetchError(RuntimeError):
    """Raised for a failure that should stop the whole run rather than mark one source."""


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def licence_refusal(source: Source, opt_in: Iterable[str] = ()) -> str | None:
    """Why this source may not be fetched, or None.

    Implements the second half of AGENTS.md 5.5 -- *refuse or loudly flag* anything
    non-permissive. Refusal is reserved for licences that are actually restrictive;
    everything else is flagged in the lock and in the report. Refusing more broadly would
    be worse, not safer: a gate that blocks the PGS Catalog because 31 of its 6,970 scores
    are non-commercial teaches people to pass a blanket opt-in, and then it protects
    nothing.
    """
    terms = source.license
    if not terms.needs_opt_in:
        return None
    if source.id in set(opt_in):
        return None
    return (
        f"{source.name} is {terms.name} ({terms.standing}). "
        f"{terms.notes} Fetching it requires an explicit opt-in for {source.id!r}; "
        f"terms: {terms.terms_url}"
    )


def preflight_disk(sources: Sequence[Source], root: Path) -> str | None:
    """Warn when the declared total will not fit. Returns a message, or None.

    A warning rather than a refusal: the sizes are declared, some are unknown, and a user
    who is about to free space or point ``GENETICS_DATA_DIR`` at another drive should not
    be blocked by an estimate.
    """
    known = [s.total_size_bytes for s in sources if s.total_size_bytes is not None]
    if not known:
        return None
    downloads = sum(known)
    workspace = sum(postprocess.estimated_workspace_bytes(source) for source in sources)
    needed = downloads + workspace
    unmeasured = [s.id for s in sources if s.total_size_bytes is None and s.files]

    probe: Path | None = root
    while probe is not None and not probe.exists():
        probe = probe.parent if probe.parent != probe else None
    if probe is None:
        return None
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return None

    if needed < free:
        return None
    extra = f" plus {len(unmeasured)} source(s) of unknown size" if unmeasured else ""
    return (
        f"selected sources need about {needed / 1e9:.1f} GB at peak "
        f"({downloads / 1e9:.1f} GB downloads + {workspace / 1e9:.1f} GB "
        f"post-process workspace){extra}, but only "
        f"{free / 1e9:.1f} GB is free at {probe}"
    )


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------


def _destination(root: Path, source: Source, item: RemoteFile) -> Path:
    """Resolve where a file lands, refusing anything outside the source's directory.

    The manifest already rejects traversal in a filename, but that check inspects a
    string and this one inspects the resolved path. Only the second is load-bearing: it is
    the one that still holds if the first is ever relaxed, reordered, or bypassed by a
    manifest read from somewhere new.
    """
    source_dir = (root / source.id).resolve()
    target = (source_dir / item.filename).resolve()
    # Must be strictly *inside*. Allowing equality let a filename of "." resolve to the
    # source directory itself, which passes the manifest's string check (no "..", not
    # absolute) and then has the payload written over a directory path.
    if source_dir not in target.parents:
        raise FetchError(
            f"{source.id}: {item.filename!r} resolves to {target}, which is not inside {source_dir}"
        )
    return target


def _digests(path: Path) -> tuple[str, str, int]:
    """Return ``(sha256, md5, size)`` in a single pass over the file."""
    sha = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return sha.hexdigest(), md5.hexdigest(), size


def _expected_sha256(item: RemoteFile, source_id: str, previous: lockfile.Lock) -> str | None:
    """The digest to check against: the manifest's pin, else whatever the lock recorded."""
    if item.sha256:
        return item.sha256
    return previous.file_digest(source_id, item.filename)


def _mismatch(path: Path, label: str, expected: str, observed: str, *, discarded: bool) -> str:
    """Explain a digest mismatch, and say truthfully what happened to the file.

    ``discarded`` is a parameter rather than an assumption because the two call sites do
    different things: a freshly downloaded ``.part`` is deleted (resuming onto bytes known
    to be wrong would fail forever for an invisible reason), while an already-present file
    that fails verification is left alone. Claiming a discard that did not happen would
    tell the reader a rerun fixes it, and a rerun would fail identically.
    """
    tail = (
        "The partial file has been discarded, because resuming onto bytes already known "
        "to be wrong would produce a file that fails forever for a reason nobody can see."
        if discarded
        else "The file on disk has been left in place; delete it, or rerun with the "
        "source's files removed, to fetch a fresh copy."
    )
    return f"{path.name}: {label} mismatch (expected {expected}, got {observed}). {tail}"


def _size_mismatch(
    path: Path,
    expected: int,
    observed: int,
    *,
    discarded: bool,
    partial: bool = False,
) -> str:
    """Explain a manifest-size mismatch without pretending a digest was available."""
    if discarded:
        tail = (
            "The partial file has been discarded because it is longer than the declared "
            "file and cannot be resumed safely."
        )
    elif partial:
        tail = "The partial file has been left in place."
    else:
        tail = (
            "The file on disk has been left in place; delete it, or rerun with the "
            "source's files removed, to fetch a fresh copy."
        )
    return f"{path.name}: size mismatch (expected {expected} bytes, got {observed}). {tail}"


def download(
    url: str,
    target: Path,
    *,
    transport: Transport,
    expected_sha256: str | None = None,
    expected_md5: str | None = None,
    expected_size: int | None = None,
    progress: ProgressCallback | None = None,
    label: str = "",
) -> FileResult:
    """Fetch one URL to one path, resumably and verifiably.

    The core of this module, kept independent of :class:`Source` so that tool acquisition
    (M2.5) reuses it rather than growing a second, subtly different implementation of the
    resume logic. Duplicating this is how the three corruption cases handled below get
    fixed in one copy and not the other.
    """
    name = target.name
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    authenticated = expected_sha256 is not None or expected_md5 is not None

    if target.is_file():
        size = target.stat().st_size
        if expected_size is not None and size != expected_size:
            return FileResult(
                name,
                FileStatus.FAILED,
                size,
                detail=_size_mismatch(target, expected_size, size, discarded=False),
            )
        sha, md5, size = _digests(target)
        if expected_sha256 and sha != expected_sha256:
            return FileResult(
                name,
                FileStatus.FAILED,
                size,
                sha,
                _mismatch(target, "sha256", expected_sha256, sha, discarded=False),
            )
        if expected_md5 and md5 != expected_md5:
            return FileResult(
                name,
                FileStatus.FAILED,
                size,
                sha,
                _mismatch(target, "md5", expected_md5, md5, discarded=False),
            )
        return FileResult(name, FileStatus.ALREADY_PRESENT, size, sha)

    offset = part.stat().st_size if part.is_file() else 0
    if expected_size is not None and offset > expected_size:
        # A part longer than the whole file cannot be a prefix of it.
        part.unlink()
        offset = 0
    elif expected_size is not None and offset == expected_size and offset > 0:
        # The part is already the full length: the transfer finished but the process died
        # before the digest and rename completed. That window is not narrow -- hashing a
        # 63 GB file takes minutes, and an interrupt during it lands exactly here.
        #
        # Asking for `Range: bytes=<size>-` gets a 416 from a correct server, which
        # arrives as a URLError and reports "could not open" *forever*, while the
        # neighbouring message advises rerunning to resume. Verify and promote instead.
        sha, md5, size = _digests(part)
        sha_ok = not expected_sha256 or sha == expected_sha256
        md5_ok = not expected_md5 or md5 == expected_md5
        if sha_ok and md5_ok:
            os.replace(part, target)
            return FileResult(name, FileStatus.DOWNLOADED, size, sha)
        part.unlink()
        offset = 0
    elif offset > 0 and not authenticated:
        # A partial response has no content identity of its own.  Without a publisher
        # digest or a digest from a previous lock, the URL may have changed between
        # invocations; appending the new suffix to the old prefix can manufacture a
        # correctly-sized chimera which would then be recorded in the lock as truth.
        # Restarting costs bandwidth once.  Blessing mixed reference releases can change
        # every downstream result.
        part.unlink()
        offset = 0

    try:
        chunked = transport.open(url, offset=offset)
    except (urllib.error.URLError, OSError) as exc:
        return FileResult(name, FileStatus.FAILED, detail=f"could not open: {exc}")

    if chunked.resumed_from > offset:
        # The server started *later* than we have bytes for, leaving a hole. Truncating to
        # that offset would zero-extend the file and the append would land past a run of
        # NUL bytes -- corruption that a pinned file catches at the end and an unpinned one
        # never does. No compliant server does this, which is exactly why it is worth
        # handling: the failure would be rare, silent and baffling.
        chunked.stream.close()
        part.unlink(missing_ok=True)
        try:
            chunked = transport.open(url, offset=0)
        except (urllib.error.URLError, OSError) as exc:
            return FileResult(name, FileStatus.FAILED, detail=f"could not reopen: {exc}")

    resumed = chunked.resumed_from > 0
    mode = "ab" if resumed else "wb"
    if resumed and chunked.resumed_from < offset:
        # The server met us earlier than we asked. Trust the server and trim the local
        # part to match, rather than writing its body into the wrong place.
        with open(part, "r+b") as handle:
            handle.truncate(chunked.resumed_from)

    written = chunked.resumed_from
    try:
        with chunked.stream as stream, open(part, mode) as handle:
            while chunk := stream.read(CHUNK_BYTES):
                handle.write(chunk)
                written += len(chunk)
                if progress is not None:
                    progress(ProgressEvent(label or name, name, written, chunked.total_size))
    except (urllib.error.URLError, OSError) as exc:
        # Only an authenticated prefix is safe to resume.  A digest-less partial may be
        # from a rolling entity which changes before the next invocation.
        if not authenticated:
            part.unlink(missing_ok=True)
            suffix = "; unauthenticated partial discarded, rerun to restart"
        else:
            suffix = "; rerun to resume"
        return FileResult(
            name,
            FileStatus.FAILED,
            written,
            detail=f"transfer interrupted after {written} bytes ({exc}){suffix}",
        )

    size = part.stat().st_size
    if expected_size is not None and size != expected_size:
        # A short response may still be a valid prefix: keep it so the next invocation
        # can resume. A response longer than the manifest declaration cannot be a prefix
        # of the declared file and is discarded before it can poison future retries.
        oversized = size > expected_size
        if oversized:
            part.unlink(missing_ok=True)
            detail = _size_mismatch(
                part,
                expected_size,
                size,
                discarded=True,
                partial=True,
            )
        elif not authenticated:
            part.unlink(missing_ok=True)
            detail = (
                f"{part.name}: size mismatch (expected {expected_size} bytes, got {size}). "
                "The short partial has been discarded because no digest can prove a "
                "later response is the same entity; rerun to restart."
            )
        else:
            detail = _size_mismatch(
                part,
                expected_size,
                size,
                discarded=False,
                partial=True,
            )
            detail += " Rerun to resume the short transfer."
        return FileResult(name, FileStatus.FAILED, size, detail=detail)
    sha, md5, size = _digests(part)
    if expected_sha256 and sha != expected_sha256:
        detail = _mismatch(part, "sha256", expected_sha256, sha, discarded=True)
        part.unlink(missing_ok=True)
        return FileResult(name, FileStatus.FAILED, size, sha, detail)
    if expected_md5 and md5 != expected_md5:
        detail = _mismatch(part, "md5", expected_md5, md5, discarded=True)
        part.unlink(missing_ok=True)
        return FileResult(name, FileStatus.FAILED, size, sha, detail)

    os.replace(part, target)
    status = FileStatus.RESUMED if resumed else FileStatus.DOWNLOADED
    return FileResult(name, status, size, sha)


def fetch_file(
    source: Source,
    item: RemoteFile,
    *,
    root: Path,
    transport: Transport,
    previous: lockfile.Lock,
    progress: ProgressCallback | None = None,
) -> FileResult:
    """Download one manifest file if needed, verify it, and report what happened.

    Resolves *where* it goes and *what to check it against*; :func:`download` does the
    rest.
    """
    target = _destination(root, source, item)
    result = download(
        item.url,
        target,
        transport=transport,
        expected_sha256=_expected_sha256(item, source.id, previous),
        expected_md5=item.md5,
        expected_size=item.size_bytes,
        progress=progress,
        label=source.id,
    )
    # Report the manifest's filename, which may include a subdirectory, rather than the
    # basename download() knows about.
    result = FileResult(
        item.filename, result.status, result.size_bytes, result.sha256, result.detail
    )
    if result.ok and not item.pinned and not result.detail:
        return FileResult(
            item.filename,
            result.status,
            result.size_bytes,
            result.sha256,
            "unpinned by the manifest; digest recorded in the lock",
        )
    return result


def verify_file(
    source: Source, item: RemoteFile, *, root: Path, previous: lockfile.Lock
) -> FileResult:
    """Check an on-disk file without downloading anything."""
    target = _destination(root, source, item)
    if not target.is_file():
        return FileResult(item.filename, FileStatus.MISSING, detail="not fetched")

    expected_sha = _expected_sha256(item, source.id, previous)
    size = target.stat().st_size
    if item.size_bytes is not None and size != item.size_bytes:
        return FileResult(
            item.filename,
            FileStatus.FAILED,
            size,
            detail=_size_mismatch(target, item.size_bytes, size, discarded=False),
        )
    sha, md5, size = _digests(target)
    if expected_sha and sha != expected_sha:
        return FileResult(
            item.filename,
            FileStatus.FAILED,
            size,
            sha,
            _mismatch(target, "sha256", expected_sha, sha, discarded=False),
        )
    if item.md5 and md5 != item.md5:
        return FileResult(
            item.filename,
            FileStatus.FAILED,
            size,
            sha,
            _mismatch(target, "md5", item.md5, md5, discarded=False),
        )
    # Keyed on both digests, not just sha256. All 24 gnomAD files are pinned by the
    # publisher's md5 and carry no sha256, so reporting "no digest to check against" for
    # them understated a check that had in fact just passed -- and an audit that
    # under-reports its own coverage is one nobody can act on.
    detail = (
        "" if (expected_sha or item.md5) else "no digest to check against; recorded on next fetch"
    )
    return FileResult(item.filename, FileStatus.VERIFIED, size, sha, detail)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def manual_step_satisfied(source: Source, root: Path) -> bool:
    """True when the human has done what a Tier B source needs.

    Presence of the expected files, plus the credential where one is required. A source
    that declares neither cannot be detected as done, and is reported as pending forever
    -- which is the honest answer, not a bug.
    """
    manual = source.manual
    if manual is None:
        return True
    if manual.env_var and not os.environ.get(manual.env_var):
        return False
    if not manual.expected_files:
        return False
    source_dir = root / source.id
    return all((source_dir / name).is_file() for name in manual.expected_files)


def _pending_steps(source: Source) -> tuple[str, ...]:
    return tuple(
        f"{step.step} (owned by {step.definition.milestone or 'an unassigned milestone'})"
        for step in source.post_process
        if not step.definition.implemented
    )


def fetch_source(
    source: Source,
    *,
    root: Path,
    transport: Transport,
    previous: lockfile.Lock,
    opt_in: Iterable[str] = (),
    progress: ProgressCallback | None = None,
    verify_only: bool = False,
) -> SourceResult:
    """Fetch (or verify) every file in one source, after clearing the gates."""
    # The licence gate governs *acquiring* data, not inspecting what is already on disk.
    # Applying it to verification made the integrity check unreachable for exactly the
    # sources whose licence someone had already accepted: after
    # `refs fetch --only pharmgkb --opt-in pharmgkb`, a plain `refs verify` answered
    # "blocked-by-licence" and never looked at the files. It also meant a full verify could
    # never exit 0, which makes the exit code useless as a health signal.
    if not verify_only:
        refusal = licence_refusal(source, opt_in)
        if refusal is not None:
            return SourceResult(source.id, SourceStatus.BLOCKED_BY_LICENCE, detail=refusal)

    if source.manual is not None and not manual_step_satisfied(source, root):
        return SourceResult(
            source.id,
            SourceStatus.AWAITING_MANUAL_STEP,
            detail=f"{source.manual.instructions} See {source.manual.url}",
        )

    results: list[FileResult] = []
    for item in source.files:
        if verify_only:
            results.append(verify_file(source, item, root=root, previous=previous))
        else:
            results.append(
                fetch_file(
                    source,
                    item,
                    root=root,
                    transport=transport,
                    previous=previous,
                    progress=progress,
                )
            )

    failed = [r for r in results if not r.ok]
    process_results: tuple[postprocess.ProcessResult, ...] = ()
    if not failed:
        process_callback: postprocess.ProcessProgressCallback | None = None
        if progress is not None:

            def on_process(event: postprocess.ProcessProgressEvent) -> None:
                progress(
                    ProgressEvent(
                        source.id,
                        event.step,
                        event.processed_rows,
                        None,
                        unit="rows",
                    )
                )

            process_callback = on_process

        process_results = postprocess.run(
            source,
            root=root,
            verify_only=verify_only,
            progress=process_callback,
            input_digests={
                result.filename: result.sha256 for result in results if result.sha256 is not None
            },
        )
    process_failed = [r for r in process_results if not r.ok]
    status = SourceStatus.FAILED if (failed or process_failed) else SourceStatus.COMPLETE
    detail = "; ".join(
        [r.detail for r in failed if r.detail]
        + [f"{r.step}: {r.detail}" for r in process_failed if r.detail]
    )
    pending = tuple(
        f"{result.step} ({result.detail})"
        for result in process_results
        if result.status is postprocess.ProcessStatus.PENDING
    )
    return SourceResult(
        source.id,
        status,
        tuple(results),
        detail,
        pending_steps=pending or _pending_steps(source),
        process_results=process_results,
    )


def select_sources(
    manifest: Manifest, only: Iterable[str] | None, include_optional: bool
) -> list[Source]:
    if only is not None:
        wanted = list(only)
        return [manifest.get(source_id) for source_id in wanted]
    return [s for s in manifest.sources if s.required or include_optional]


def fetch(
    manifest: Manifest,
    *,
    root: Path,
    transport: Transport | None = None,
    lock_path: Path | None = None,
    only: Iterable[str] | None = None,
    include_optional: bool = False,
    opt_in: Iterable[str] = (),
    progress: ProgressCallback | None = None,
    verify_only: bool = False,
    today: str | None = None,
) -> FetchReport:
    """Fetch the selected sources and rewrite the lock.

    The lock is updated even when some sources fail: the successful ones are facts worth
    keeping, and discarding them would mean a single flaky host cost the whole run's
    record of what it received.

    **``verify_only`` writes nothing.** Verification exists to answer "does what is on
    disk still match what we recorded?", and a check that rewrites its own reference
    answers that question with "yes" by construction. The first version did rewrite the
    lock, which showed up immediately: running the CLI tests created a committed-path
    ``manifest.lock`` describing sources with no files -- a lock asserting facts about
    downloads that had never happened, which is exactly what this file must never contain.
    """
    transport = transport or UrllibTransport()
    if not verify_only:
        root.mkdir(parents=True, exist_ok=True)
    lock_target = lock_path if lock_path is not None else _default_lock_path()
    previous = lockfile.read(lock_target)
    stamp = today or date.today().isoformat()

    selected = select_sources(manifest, only, include_optional)
    warnings: list[str] = []
    if not verify_only:
        shortfall = preflight_disk(selected, root)
        if shortfall:
            warnings.append(shortfall)

    # Per-record licences are named individually: each one is a distinct obligation
    # landing on a distinct downstream module.
    for source in selected:
        if not source.license.authoritative:
            warnings.append(
                f"{source.id}: {source.license.name} -- the collection licence does not "
                f"bind individual records; each must be checked at the point of use."
            )

    # Unreviewed classifications are aggregated into one line instead of one per source.
    # Most entries in the licence table are honestly marked 'needs-review', so emitting a
    # warning apiece would put ten near-identical lines in front of someone who is
    # watching a download -- and this repository already learned in M0.3 that a check
    # which cries wolf gets bypassed. One line carries the same facts and stays readable.
    unreviewed = sorted(
        {
            s.id
            for s in selected
            if s.license.authoritative and s.license.review_status != "confirmed"
        }
    )
    if unreviewed:
        warnings.append(
            f"{len(unreviewed)} source(s) carry a licence classification that has not been "
            f"checked against the published terms, and are the worklist for the M15.4 "
            f"licence audit: {', '.join(unreviewed)}."
        )

    results: list[SourceResult] = []
    locked: dict[str, lockfile.LockedSource] = dict(previous.sources)

    for source in selected:
        result = fetch_source(
            source,
            root=root,
            transport=transport,
            previous=previous,
            opt_in=opt_in,
            progress=progress,
            verify_only=verify_only,
        )
        results.append(result)

        files: dict[str, lockfile.LockedFile] = {}
        for file_result in result.files:
            if file_result.sha256 is None or not file_result.ok:
                continue
            item = next(f for f in source.files if f.filename == file_result.filename)
            files[file_result.filename] = lockfile.record_file(
                previous,
                source.id,
                file_result.filename,
                url=item.url,
                sha256=file_result.sha256,
                size_bytes=file_result.size_bytes,
                today=stamp,
            )
        # Merge over what was already recorded, rather than replacing it. Replacing lost
        # the digest of precisely the files that failed this run, and that failed *open*:
        # with no recorded digest, the next run had nothing to compare the file against,
        # reported it already-present, and wrote the corrupt content into the lock as
        # truth. One detected corruption was enough to launder itself into the record.
        carried = previous.sources.get(source.id)
        merged = dict(carried.files) if carried else {}
        merged.update(files)

        # Written unconditionally. The previous condition skipped a source that completed
        # with no files -- which is exactly a satisfied tier B source, so OMIM and SNPedia
        # dropped out of the lock at the moment their data was actually present. Those are
        # the two most licence-encumbered entries in the manifest, and manifest.lock is
        # what the M15.4 audit reads to confirm nothing non-permissive was vendored.
        locked[source.id] = lockfile.LockedSource(
            version=source.version,
            license_id=source.license_id,
            files=merged,
            opt_in_granted=source.id in set(opt_in),
            manual_step_pending=result.status is SourceStatus.AWAITING_MANUAL_STEP,
        )

    if not verify_only:
        lockfile.write(lock_target, lockfile.Lock(sources=locked))
    return FetchReport(tuple(results), tuple(warnings))


def _default_lock_path() -> Path:
    from genetics.paths import reference_lock

    return reference_lock()


def cleanup_partials(root: Path) -> list[Path]:
    """Delete every ``.part`` under ``root``. For when a resume is not wanted."""
    removed: list[Path] = []
    for path in sorted(root.rglob("*.part")):
        with suppress(OSError):
            path.unlink()
            removed.append(path)
    return removed
