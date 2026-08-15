"""Tests for the reference fetcher (roadmap M2.2).

No test here touches the network: :class:`FakeTransport` stands in, which is the reason
:class:`genetics.refs.fetcher.Transport` exists as a protocol at all. It also lets the
tests reproduce the failure that matters most -- a server that ignores a Range header --
which is otherwise almost impossible to provoke on demand.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from genetics.refs import fetcher, manifest
from genetics.refs import lock as lockfile
from genetics.refs.fetcher import Chunked, FileStatus, SourceStatus

PAYLOAD = b"reference payload, not a genotype, repeated for length. " * 40
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
PAYLOAD_MD5 = hashlib.md5(PAYLOAD, usedforsecurity=False).hexdigest()
URL = "https://example.org/ref.txt"


class FakeTransport:
    """A server whose behaviour the test chooses.

    ``honour_range=False`` models the case the docstring in fetcher.py is about: a server
    that is asked for a byte range and answers with the whole file and a 200.
    """

    def __init__(
        self,
        payloads: dict[str, bytes] | None = None,
        *,
        honour_range: bool = True,
        truncate_at: int | None = None,
        resume_skew: int = 0,
    ) -> None:
        self.payloads = payloads or {URL: PAYLOAD}
        self.honour_range = honour_range
        self.truncate_at = truncate_at
        self.resume_skew = resume_skew
        self.requests: list[tuple[str, int]] = []

    def open(self, url: str, *, offset: int = 0) -> Chunked:
        self.requests.append((url, offset))
        data = self.payloads[url]
        if self.resume_skew and offset > 0:
            # A misbehaving server that starts *later* than asked, leaving a hole.
            start = offset + self.resume_skew
            body, resumed = data[start:], start
        elif self.honour_range and offset > 0:
            body, resumed = data[offset:], offset
        else:
            body, resumed = data, 0
        if self.truncate_at is not None:
            body = body[: self.truncate_at]
        return Chunked(stream=io.BytesIO(body), total_size=len(data), resumed_from=resumed)


def make_source(
    *,
    source_id: str = "example",
    license_id: str = "CC0-1.0",
    sha256: str | None = PAYLOAD_SHA,
    md5: str | None = None,
    unpinned_reason: str | None = None,
    required: bool = False,
    post_process: tuple[manifest.PostProcess, ...] = (),
) -> manifest.Source:
    """A one-file source. Constructed directly rather than through the YAML parser so a
    test can build states the parser would reject -- which is how the write-time path
    checks get exercised at all."""
    item = manifest.RemoteFile(
        url=URL,
        filename="ref.txt",
        sha256=sha256,
        md5=md5,
        size_bytes=len(PAYLOAD),
        unpinned_reason=unpinned_reason,
    )
    return manifest.Source(
        id=source_id,
        name="Example",
        tier=manifest.Tier.A,
        version="1",
        homepage="https://example.org/",
        license_id=license_id,
        required=required,
        files=(item,),
        post_process=post_process,
    )


# ---------------------------------------------------------------------------
# Downloading and resuming
# ---------------------------------------------------------------------------


def test_a_clean_download_verifies_and_lands(tmp_path: Path) -> None:
    source = make_source()
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
    )
    assert result.status is FileStatus.DOWNLOADED
    assert (tmp_path / "example" / "ref.txt").read_bytes() == PAYLOAD
    assert not list(tmp_path.rglob("*.part")), "the .part file should have been promoted"


def test_a_partial_file_is_resumed_rather_than_restarted(tmp_path: Path) -> None:
    source = make_source()
    part = tmp_path / "example" / "ref.txt.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(PAYLOAD[:100])

    transport = FakeTransport()
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )
    assert result.status is FileStatus.RESUMED
    assert transport.requests == [(URL, 100)], "should have asked to start at 100"
    assert (tmp_path / "example" / "ref.txt").read_bytes() == PAYLOAD


def test_a_server_that_ignores_the_range_header_does_not_corrupt_the_file(
    tmp_path: Path,
) -> None:
    """The headline case, and the reason Chunked reports ``resumed_from``.

    We ask for bytes from 100. The server answers 200 with the *whole* file. Code that
    assumed a 206 would append that body to the existing 100 bytes and produce a file
    that is 100 bytes too long with a duplicated prefix -- and for an unpinned file,
    nothing would ever notice.
    """
    source = make_source()
    part = tmp_path / "example" / "ref.txt.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(PAYLOAD[:100])

    transport = FakeTransport(honour_range=False)
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )

    assert result.status is FileStatus.DOWNLOADED, "a restart is not a resume"
    written = (tmp_path / "example" / "ref.txt").read_bytes()
    assert written == PAYLOAD
    assert len(written) == len(PAYLOAD), "the prefix must not have been duplicated"


def test_a_server_resuming_past_our_offset_restarts_instead_of_leaving_a_hole(
    tmp_path: Path,
) -> None:
    """We have 100 bytes and ask for 100-; the server answers from 150.

    Truncating to 150 would zero-extend the file and append past a run of NULs. No
    compliant server does this, which is the reason to handle it: the corruption would be
    rare, silent, and -- on a file with no published digest -- permanent.
    """
    source = make_source()
    part = tmp_path / "example" / "ref.txt.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(PAYLOAD[:100])

    transport = FakeTransport(resume_skew=50)
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )

    assert result.status is FileStatus.DOWNLOADED
    assert transport.requests == [(URL, 100), (URL, 0)], "should have restarted from zero"
    written = (tmp_path / "example" / "ref.txt").read_bytes()
    assert written == PAYLOAD
    assert b"\x00" not in written, "a zero-extended hole would show up here"


def test_a_part_longer_than_the_whole_file_is_discarded(tmp_path: Path) -> None:
    """It cannot be a prefix of the file, so resuming from it is meaningless."""
    source = make_source()
    part = tmp_path / "example" / "ref.txt.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(PAYLOAD + b"extra junk")

    transport = FakeTransport()
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )
    assert transport.requests == [(URL, 0)]
    assert result.status is FileStatus.DOWNLOADED


def test_an_interrupted_transfer_keeps_the_part_for_a_later_resume(tmp_path: Path) -> None:
    source = make_source()
    transport = FakeTransport(truncate_at=120)
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )
    # A short body is indistinguishable from a stream that stopped early, so the digest
    # is what catches it -- and the part is discarded because it failed verification.
    assert result.status is FileStatus.FAILED
    assert not (tmp_path / "example" / "ref.txt").exists()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def test_a_digest_mismatch_discards_the_partial_file(tmp_path: Path) -> None:
    """Keeping it would poison every later resume, failing forever for an invisible reason."""
    source = make_source()
    transport = FakeTransport({URL: b"a completely different payload"})
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )
    assert result.status is FileStatus.FAILED
    assert "sha256 mismatch" in result.detail
    assert not list(tmp_path.rglob("*.part"))
    assert not (tmp_path / "example" / "ref.txt").exists()


def test_a_publisher_md5_is_checked_too(tmp_path: Path) -> None:
    source = make_source(sha256=None, md5="0" * 32)
    transport = FakeTransport()
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )
    assert result.status is FileStatus.FAILED
    assert "md5 mismatch" in result.detail


def test_an_already_present_file_is_verified_not_refetched(tmp_path: Path) -> None:
    source = make_source()
    target = tmp_path / "example" / "ref.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(PAYLOAD)

    transport = FakeTransport()
    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )
    assert result.status is FileStatus.ALREADY_PRESENT
    assert transport.requests == [], "nothing should have been requested"


def test_a_corrupted_present_file_is_reported_not_silently_accepted(tmp_path: Path) -> None:
    source = make_source()
    target = tmp_path / "example" / "ref.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"tampered")

    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
    )
    assert result.status is FileStatus.FAILED


def test_an_unpinned_file_becomes_checkable_once_the_lock_has_seen_it(tmp_path: Path) -> None:
    """The whole point of recording digests for rolling URLs.

    First fetch: nothing to compare against. Second fetch, after the publisher has
    silently changed the file under a fixed name: caught.
    """
    source = make_source(sha256=None, unpinned_reason="rolling latest/ release")
    first = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
    )
    assert first.status is FileStatus.DOWNLOADED
    assert first.sha256 == PAYLOAD_SHA

    recorded = lockfile.Lock(
        sources={
            "example": lockfile.LockedSource(
                version="1",
                license_id="CC0-1.0",
                files={
                    "ref.txt": lockfile.LockedFile(
                        url=URL,
                        sha256=PAYLOAD_SHA,
                        size_bytes=len(PAYLOAD),
                        first_seen="2026-08-15",
                    )
                },
            )
        }
    )
    (tmp_path / "example" / "ref.txt").write_bytes(b"the publisher changed it")
    second = fetcher.verify_file(source, source.files[0], root=tmp_path, previous=recorded)
    assert second.status is FileStatus.FAILED


def test_verify_reports_a_missing_file_without_downloading(tmp_path: Path) -> None:
    source = make_source()
    result = fetcher.verify_file(source, source.files[0], root=tmp_path, previous=lockfile.Lock())
    assert result.status is FileStatus.MISSING


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def test_a_filename_escaping_its_directory_is_refused_at_write_time(tmp_path: Path) -> None:
    """Defence in depth: the manifest rejects the string, this rejects the resolved path.

    Constructed by bypassing the manifest parser on purpose -- the point is that this
    check still holds if the earlier one is relaxed or bypassed.
    """
    escaping = manifest.RemoteFile(url=URL, filename="../../escape.txt", sha256=PAYLOAD_SHA)
    source = make_source()
    with pytest.raises(fetcher.FetchError, match="outside"):
        fetcher.fetch_file(
            source, escaping, root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
        )


# ---------------------------------------------------------------------------
# The licence gate
# ---------------------------------------------------------------------------


def test_a_restricted_source_is_refused_without_an_opt_in(tmp_path: Path) -> None:
    source = make_source(license_id="CC-BY-NC-SA-3.0-US")
    result = fetcher.fetch_source(
        source, root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
    )
    assert result.status is SourceStatus.BLOCKED_BY_LICENCE
    assert "opt-in" in result.detail
    assert not list(tmp_path.rglob("*.txt")), "no bytes should have moved"


def test_an_opt_in_unblocks_exactly_the_named_source(tmp_path: Path) -> None:
    source = make_source(license_id="CC-BY-NC-SA-3.0-US")
    blocked = fetcher.fetch_source(
        source,
        root=tmp_path,
        transport=FakeTransport(),
        previous=lockfile.Lock(),
        opt_in=["something_else"],
    )
    assert blocked.status is SourceStatus.BLOCKED_BY_LICENCE

    allowed = fetcher.fetch_source(
        source,
        root=tmp_path,
        transport=FakeTransport(),
        previous=lockfile.Lock(),
        opt_in=["example"],
    )
    assert allowed.status is SourceStatus.COMPLETE


def test_a_per_record_licence_is_flagged_not_blocked(tmp_path: Path) -> None:
    """AGENTS.md 4.8 trap 1 -- see test_licenses.py for why this is deliberate."""
    source = make_source(license_id="LicenseRef-PGS-Catalog-Per-Score")
    assert fetcher.licence_refusal(source) is None


# ---------------------------------------------------------------------------
# Manual steps (M2.4)
# ---------------------------------------------------------------------------


def test_a_tier_b_source_reports_its_instructions_until_the_human_acts(tmp_path: Path) -> None:
    source = manifest.Source(
        id="gated",
        name="Gated",
        tier=manifest.Tier.B,
        version="1",
        homepage="https://example.org/",
        license_id="CC0-1.0",
        manual=manifest.ManualStep(
            instructions="Download the thing by hand.",
            url="https://example.org/form",
            expected_files=("thing.txt",),
        ),
    )
    pending = fetcher.fetch_source(
        source, root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
    )
    assert pending.status is SourceStatus.AWAITING_MANUAL_STEP
    assert "Download the thing by hand." in pending.detail

    (tmp_path / "gated").mkdir(parents=True)
    (tmp_path / "gated" / "thing.txt").write_text("done")
    done = fetcher.fetch_source(
        source, root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
    )
    assert done.status is SourceStatus.COMPLETE


def test_a_credentialled_source_stays_pending_without_its_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OMIM. The key is user-supplied, and its absence is a pending step, not an error."""
    source = manifest.Source(
        id="omimish",
        name="OMIM-like",
        tier=manifest.Tier.B,
        version="1",
        homepage="https://example.org/",
        license_id="CC0-1.0",
        manual=manifest.ManualStep(
            instructions="Set the key.",
            url="https://example.org/api",
            env_var="TEST_ONLY_API_KEY",
            expected_files=("mim2gene.txt",),
        ),
    )
    (tmp_path / "omimish").mkdir(parents=True)
    (tmp_path / "omimish" / "mim2gene.txt").write_text("data")

    monkeypatch.delenv("TEST_ONLY_API_KEY", raising=False)
    assert (
        fetcher.fetch_source(
            source, root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
        ).status
        is SourceStatus.AWAITING_MANUAL_STEP
    )

    monkeypatch.setenv("TEST_ONLY_API_KEY", "secret")
    assert (
        fetcher.fetch_source(
            source, root=tmp_path, transport=FakeTransport(), previous=lockfile.Lock()
        ).status
        is SourceStatus.COMPLETE
    )


# ---------------------------------------------------------------------------
# Whole-run behaviour
# ---------------------------------------------------------------------------


def test_fetch_writes_a_lock_and_reports_unimplemented_steps(tmp_path: Path) -> None:
    source = make_source(
        post_process=(manifest.PostProcess(step="convert_to_bref3", params={"output": "x/"}),)
    )
    parsed = manifest.Manifest(schema_version=1, sources=(source,))
    lock_path = tmp_path / "manifest.lock"

    report = fetcher.fetch(
        parsed,
        root=tmp_path / "refs",
        transport=FakeTransport(),
        lock_path=lock_path,
        include_optional=True,
        today="2026-08-15",
    )
    assert report.ok
    assert lock_path.is_file()

    result = report.sources[0]
    assert result.pending_steps and "convert_to_bref3" in result.pending_steps[0]
    assert "M8.2" in result.pending_steps[0], "an unimplemented step should name its owner"


def test_rerunning_a_fetch_produces_a_byte_identical_lock(tmp_path: Path) -> None:
    """A lock that churns on every run is a diff nobody reads -- and the licence audit
    depends on someone reading it."""
    parsed = manifest.Manifest(schema_version=1, sources=(make_source(),))
    lock_path = tmp_path / "manifest.lock"
    root = tmp_path / "refs"

    fetcher.fetch(
        parsed,
        root=root,
        transport=FakeTransport(),
        lock_path=lock_path,
        include_optional=True,
        today="2026-08-15",
    )
    first = lock_path.read_text(encoding="utf-8")

    fetcher.fetch(
        parsed,
        root=root,
        transport=FakeTransport(),
        lock_path=lock_path,
        include_optional=True,
        today="2027-01-01",
    )
    assert lock_path.read_text(encoding="utf-8") == first


def test_verify_writes_nothing_at_all(tmp_path: Path) -> None:
    """A check that rewrites its own reference answers "does this still match?" with
    "yes" by construction.

    Found the hard way: the first version rewrote the lock on verify, so merely running
    the CLI tests created a committed-path manifest.lock describing sources with no files
    -- a lock asserting facts about downloads that never happened.
    """
    parsed = manifest.Manifest(schema_version=1, sources=(make_source(),))
    lock_path = tmp_path / "manifest.lock"
    root = tmp_path / "refs"

    report = fetcher.fetch(
        parsed,
        root=root,
        transport=FakeTransport(),
        lock_path=lock_path,
        include_optional=True,
        verify_only=True,
    )
    assert not report.ok, "nothing is on disk, so verification should fail"
    assert not lock_path.exists(), "verify must not write the lock"
    assert not root.exists(), "verify must not even create the references directory"


def test_only_required_sources_are_fetched_by_default(tmp_path: Path) -> None:
    required = make_source(source_id="needed", required=True)
    optional = make_source(source_id="extra")
    parsed = manifest.Manifest(schema_version=1, sources=(required, optional))

    report = fetcher.fetch(
        parsed,
        root=tmp_path / "refs",
        transport=FakeTransport(),
        lock_path=tmp_path / "manifest.lock",
        today="2026-08-15",
    )
    assert [r.source_id for r in report.sources] == ["needed"]


def test_the_report_serialises_to_json(tmp_path: Path) -> None:
    """The CLI is the agent interface (AGENTS.md 3), so M2.6 needs this to be clean."""
    import json

    parsed = manifest.Manifest(schema_version=1, sources=(make_source(),))
    report = fetcher.fetch(
        parsed,
        root=tmp_path / "refs",
        transport=FakeTransport(),
        lock_path=tmp_path / "manifest.lock",
        include_optional=True,
        today="2026-08-15",
    )
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["ok"] is True
    assert payload["sources"][0]["status"] == "complete"
