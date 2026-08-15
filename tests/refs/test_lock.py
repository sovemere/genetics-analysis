"""Tests for the licence lock (roadmap M2.2).

The lock's value is entirely in being read -- by M15.4, and by whoever reviews a diff
showing a reference changed. Both depend on it staying quiet when nothing happened.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genetics.refs import lock as lockfile


def make_lock(sha: str = "a" * 64, first_seen: str = "2026-08-15") -> lockfile.Lock:
    return lockfile.Lock(
        sources={
            "example": lockfile.LockedSource(
                version="1",
                license_id="CC-BY-SA-4.0",
                files={
                    "data.txt": lockfile.LockedFile(
                        url="https://example.org/data.txt",
                        sha256=sha,
                        size_bytes=10,
                        first_seen=first_seen,
                    )
                },
            )
        }
    )


def test_render_is_deterministic_and_sorted() -> None:
    rendered = make_lock().render()
    assert rendered == make_lock().render()
    assert rendered.endswith("\n")
    payload = json.loads(rendered)
    assert list(payload) == sorted(payload)


def test_round_trips() -> None:
    original = make_lock()
    parsed = lockfile.loads(original.render())
    assert parsed.render() == original.render()


def test_first_seen_survives_an_unchanged_digest() -> None:
    """Re-fetching an unchanged file must not produce a diff."""
    previous = make_lock(first_seen="2020-01-01")
    entry = lockfile.record_file(
        previous,
        "example",
        "data.txt",
        url="https://example.org/data.txt",
        sha256="a" * 64,
        size_bytes=10,
        today="2026-08-15",
    )
    assert entry.first_seen == "2020-01-01"


def test_a_changed_digest_gets_todays_date() -> None:
    """The one line an auditor actually wants to see in the diff."""
    previous = make_lock(sha="a" * 64, first_seen="2020-01-01")
    entry = lockfile.record_file(
        previous,
        "example",
        "data.txt",
        url="https://example.org/data.txt",
        sha256="b" * 64,
        size_bytes=10,
        today="2026-08-15",
    )
    assert entry.first_seen == "2026-08-15"


def test_obligations_are_derived_from_the_licence_not_authored() -> None:
    """AGENTS.md 6 applied to licensing: computed, never hand-written."""
    payload = make_lock().to_json()["sources"]["example"]
    obligations = " ".join(payload["obligations"])
    assert "share-alike" in obligations
    assert "attribution" in obligations
    assert payload["license"]["share_alike"] is True
    assert payload["opt_in_required"] is True


def test_a_per_record_licence_records_that_its_terms_do_not_bind() -> None:
    lock = lockfile.Lock(
        sources={
            "pgs": lockfile.LockedSource(version="1", license_id="LicenseRef-PGS-Catalog-Per-Score")
        }
    )
    obligations = " ".join(lock.to_json()["sources"]["pgs"]["obligations"])
    assert "each record carries its own terms" in obligations


def test_a_missing_lock_reads_as_empty_rather_than_failing(tmp_path: Path) -> None:
    """A first fetch has no lock, and that is the normal case, not an error."""
    assert lockfile.read(tmp_path / "absent.lock").sources == {}


def test_an_unknown_schema_version_refuses(tmp_path: Path) -> None:
    path = tmp_path / "manifest.lock"
    path.write_text(json.dumps({"schema_version": 99, "sources": {}}), encoding="utf-8")
    with pytest.raises(lockfile.LockError, match="schema_version"):
        lockfile.read(path)


def test_file_digest_lookup_misses_cleanly() -> None:
    lock = make_lock()
    assert lock.file_digest("example", "data.txt") == "a" * 64
    assert lock.file_digest("example", "absent.txt") is None
    assert lock.file_digest("absent", "data.txt") is None
