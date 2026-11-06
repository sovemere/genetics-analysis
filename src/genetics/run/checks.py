"""Remembering that a saved run passed its deep checks.

Opening a saved imputed run used to repeat the save's deep checks on every read: 54 minutes
on a real export, for each ``genetics runs show`` and each dashboard page. Those checks are
a function of two things only, the payload bytes and the engine's source. So the verdict is
kept here, keyed by the digest of the manifest, which names every payload by its digest, and
bound to the digest of the engine:

- every read still checks every payload against the manifest, so changed bytes still raise;
- a rewritten manifest has no record, so it gets the deep checks;
- a changed engine does not match the record, so the next read repeats them, once.

Both digests are taken before the checks start, so a record can only ever name the bytes they
saw and the code that ran them. The same bytes and the same code give the same verdict, so this
loses no accuracy (AGENTS.md 0.1C). The record is kept outside the bundle because a bundle is
immutable. It holds digests only, and deleting it costs one repeat of the checks, so failing to
read or write it never fails a read or a save.

Reads that skip the checks trust a record, and a record of a save trusts the save: that
checked the payloads it was about to write, not what a reader parses back from them. That is
why ``genetics runs list --verify`` always repeats the checks on the stored bytes.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import uuid
from pathlib import Path

import genetics
from genetics.paths import UnsafeDataDirError, run_checks_dir
from genetics.run.bundle import MANIFEST_NAME

SCHEMA_VERSION = 1


@functools.cache
def engine_sha256() -> str:
    """The engine's source, by content, as this process found it when it started.

    ``__version__`` has said 0.1.0 from the start, so a part saved by other code would
    otherwise be reused as if this code had made it. Read once because the checks can outlast
    an edit: they take an hour, a run takes eight and a dashboard stays up for days, and source
    edited meanwhile did not run them. Reading it afresh would hand that edit their verdict.
    """
    root = Path(genetics.__file__).resolve().parent
    rolled = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        rolled.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        rolled.update(hashlib.sha256(path.read_bytes()).digest())
    return rolled.hexdigest()


def key(directory: Path) -> str | None:
    """The digest of a bundle's manifest, or ``None`` if it cannot be read.

    ``None`` is not an error here: :func:`~genetics.run.bundle.read_bundle` is the one that
    explains an unreadable manifest, and every function below treats it as no record.
    """
    try:
        return hashlib.sha256((Path(directory) / MANIFEST_NAME).read_bytes()).hexdigest()
    except OSError:
        return None


def _path(manifest_sha256: str) -> Path:
    return run_checks_dir() / f"{manifest_sha256}.run.json"


def _record(manifest_sha256: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_sha256": manifest_sha256,
        "engine_sha256": engine_sha256(),
    }


def passed(manifest_sha256: str | None) -> bool:
    """Whether this exact manifest passed the deep checks under this exact engine."""
    if manifest_sha256 is None:
        return False
    try:
        raw = json.loads(_path(manifest_sha256).read_text(encoding="ascii"))
        return bool(raw == _record(manifest_sha256))
    except (OSError, ValueError):  # UnsafeDataDirError is a ValueError
        return False


def record(manifest_sha256: str | None) -> None:
    """Remember a pass, replacing any older record. Written whole, or not at all."""
    if manifest_sha256 is None:
        return
    pending: Path | None = None
    try:
        target = _path(manifest_sha256)
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = target.with_name(f".pending-{uuid.uuid4().hex}")
        pending.write_text(json.dumps(_record(manifest_sha256)), encoding="ascii")
        os.replace(pending, target)
    except (OSError, UnsafeDataDirError):
        if pending is not None:
            with contextlib.suppress(OSError):
                pending.unlink(missing_ok=True)


def forget(manifest_sha256: str | None) -> None:
    """Drop a record, for a run that failed its checks or has been deleted."""
    if manifest_sha256 is None:
        return
    with contextlib.suppress(OSError, UnsafeDataDirError):
        _path(manifest_sha256).unlink(missing_ok=True)


# At import, before any check can start: see engine_sha256. A file that cannot be read just
# now is retried at first use, and failing then costs a repeat of the checks, not the read.
with contextlib.suppress(OSError):
    engine_sha256()
