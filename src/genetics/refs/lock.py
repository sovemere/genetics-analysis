"""``data/references/manifest.lock`` -- what was actually fetched (roadmap M2.2).

AGENTS.md 5.5 asks the fetcher to write each source's resolved licence into a
machine-readable lock file. M15.4 is the consumer: the release gate reviews this file to
confirm nothing non-permissive was vendored and that the PGS per-score obligation was
honoured. It has a second job the manifest cannot do -- recording the digest of files the
publisher serves from a rolling URL, so that the first fetch pins them for every fetch
afterwards.

The lock is committed. The payloads it describes are not.

Why there is no timestamp at the top
------------------------------------
The lock records **facts about content, not about when a command ran**. Re-fetching
unchanged files produces a byte-identical lock, and ``first_seen`` on an entry survives
re-verification as long as the digest does. That is a deliberate constraint: a lock that
churned a fresh timestamp on every run would produce a diff on every run, and a diff that
is always noise is a diff nobody reads -- which would quietly cost us the one review step
that catches a reference silently changing underneath a saved run.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from genetics.refs import licenses

LOCK_SCHEMA_VERSION = 1


class LockError(ValueError):
    """Raised when the lock file cannot be read or is of an unknown version."""


@dataclass(frozen=True)
class LockedFile:
    """One file as it was actually received."""

    url: str
    sha256: str
    size_bytes: int
    first_seen: str
    """ISO date the digest below was first recorded. A date rather than a timestamp: it is
    an audit trail, and second-level precision would only add churn."""

    def to_json(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "first_seen": self.first_seen,
        }


@dataclass(frozen=True)
class LockedSource:
    """One source's resolved licence and file digests."""

    version: str
    license_id: str
    files: Mapping[str, LockedFile] = field(default_factory=dict)
    opt_in_granted: bool = False
    manual_step_pending: bool = False

    def to_json(self) -> dict[str, Any]:
        terms = licenses.get(self.license_id)
        obligations: list[str] = []
        if terms.attribution_required:
            obligations.append("attribution required on every card citing this source")
        if terms.share_alike:
            obligations.append("share-alike: derivatives inherit the licence")
        if not terms.derivative_ok:
            obligations.append("no derivative works permitted")
        if not terms.commercial_ok:
            obligations.append("non-commercial use only")
        if not terms.authoritative:
            obligations.append(
                "collection licence is not authoritative -- each record carries its own terms"
            )
        if terms.review_status != "confirmed":
            obligations.append("classification not yet checked against the published terms (M15.4)")

        return {
            "version": self.version,
            "license": {
                "id": terms.id,
                "name": terms.name,
                "terms_url": terms.terms_url,
                "standing": str(terms.standing),
                "review_status": terms.review_status,
                "commercial_ok": terms.commercial_ok,
                "derivative_ok": terms.derivative_ok,
                "redistribution_ok": terms.redistribution_ok,
                "share_alike": terms.share_alike,
                "attribution_required": terms.attribution_required,
                "authoritative": terms.authoritative,
            },
            "obligations": obligations,
            "opt_in_required": terms.needs_opt_in,
            "opt_in_granted": self.opt_in_granted,
            "manual_step_pending": self.manual_step_pending,
            "files": {name: item.to_json() for name, item in sorted(self.files.items())},
        }


@dataclass(frozen=True)
class Lock:
    """The whole lock file."""

    sources: Mapping[str, LockedSource] = field(default_factory=dict)
    schema_version: int = LOCK_SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sources": {name: src.to_json() for name, src in sorted(self.sources.items())},
        }

    def render(self) -> str:
        """Deterministic serialisation. Same inputs, same bytes, no diff."""
        return json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n"

    def file_digest(self, source_id: str, filename: str) -> str | None:
        """The digest previously recorded, if any.

        This is what turns an unpinnable rolling URL into something checkable: the
        manifest cannot pin ``clinvar.vcf.gz``, but once the lock has seen it, a later
        change shows up as a verification failure rather than as new results.
        """
        source = self.sources.get(source_id)
        if source is None:
            return None
        item = source.files.get(filename)
        return item.sha256 if item else None


def _parse_file(raw: Mapping[str, Any], where: str) -> LockedFile:
    try:
        return LockedFile(
            url=str(raw["url"]),
            sha256=str(raw["sha256"]),
            size_bytes=int(raw["size_bytes"]),
            first_seen=str(raw["first_seen"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LockError(f"{where}: malformed file entry ({exc})") from exc


def loads(text: str, *, where: str = "manifest.lock") -> Lock:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LockError(f"{where}: not valid JSON: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise LockError(f"{where}: top level must be an object")

    version = raw.get("schema_version")
    if version != LOCK_SCHEMA_VERSION:
        raise LockError(
            f"{where}: schema_version {version!r}, this build understands {LOCK_SCHEMA_VERSION}"
        )

    raw_sources = raw.get("sources") or {}
    if not isinstance(raw_sources, Mapping):
        raise LockError(f"{where}: 'sources' must be an object")

    sources: dict[str, LockedSource] = {}
    for source_id, raw_source in raw_sources.items():
        if not isinstance(raw_source, Mapping):
            raise LockError(f"{where}: source {source_id!r} must be an object")
        raw_files = raw_source.get("files") or {}
        if not isinstance(raw_files, Mapping):
            raise LockError(f"{where}: source {source_id!r} files must be an object")
        license_block = raw_source.get("license") or {}
        if not isinstance(license_block, Mapping):
            raise LockError(f"{where}: source {source_id!r} license must be an object")

        sources[str(source_id)] = LockedSource(
            version=str(raw_source.get("version", "")),
            license_id=str(license_block.get("id", "")),
            files={
                str(name): _parse_file(item, f"{where}:{source_id}:{name}")
                for name, item in raw_files.items()
                if isinstance(item, Mapping)
            },
            opt_in_granted=bool(raw_source.get("opt_in_granted", False)),
            manual_step_pending=bool(raw_source.get("manual_step_pending", False)),
        )
    return Lock(sources=sources)


def read(path: Path) -> Lock:
    """Read the lock, or return an empty one if it does not exist yet."""
    if not path.is_file():
        return Lock()
    return loads(path.read_text(encoding="utf-8"), where=path.name)


def write(path: Path, lock: Lock) -> None:
    """Write the lock, creating the directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(lock.render(), encoding="utf-8")


def record_file(
    previous: Lock,
    source_id: str,
    filename: str,
    *,
    url: str,
    sha256: str,
    size_bytes: int,
    today: str | None = None,
) -> LockedFile:
    """Build the new entry for a file, preserving ``first_seen`` where the digest held.

    The preservation is what keeps re-fetching from producing a diff. A *changed* digest
    is a different fact and gets today's date -- which is exactly the line an auditor
    wants to see in the diff.
    """
    stamp = today or date.today().isoformat()
    existing = previous.sources.get(source_id)
    if existing is not None:
        prior = existing.files.get(filename)
        if prior is not None and prior.sha256 == sha256:
            stamp = prior.first_seen
    return LockedFile(url=url, sha256=sha256, size_bytes=size_bytes, first_seen=stamp)
