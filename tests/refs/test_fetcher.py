"""Tests for the reference fetcher (roadmap M2.2).

No test here touches the network: :class:`FakeTransport` stands in, which is the reason
:class:`genetics.refs.fetcher.Transport` exists as a protocol at all. It also lets the
tests reproduce the failure that matters most -- a server that ignores a Range header --
which is otherwise almost impossible to provoke on demand.
"""

from __future__ import annotations

import gzip
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
    # The declared size identifies this as a short transfer before a digest decision.
    # Keeping the valid prefix means a later invocation can resume it.
    assert result.status is FileStatus.FAILED
    assert "resume" in result.detail
    assert not (tmp_path / "example" / "ref.txt").exists()
    assert (tmp_path / "example" / "ref.txt.part").read_bytes() == PAYLOAD[:120]


def test_an_unpinned_short_first_fetch_is_discarded_and_restarts(tmp_path: Path) -> None:
    """A size cannot prove two ranged responses came from the same rolling entity."""
    source = make_source(sha256=None, unpinned_reason="rolling latest release")
    first_transport = FakeTransport(truncate_at=120)

    first = fetcher.fetch_file(
        source,
        source.files[0],
        root=tmp_path,
        transport=first_transport,
        previous=lockfile.Lock(),
    )

    assert first.status is FileStatus.FAILED
    assert "size mismatch" in first.detail
    assert "no digest" in first.detail
    assert "left in place" not in first.detail
    assert not (tmp_path / "example" / "ref.txt").exists()
    assert not (tmp_path / "example" / "ref.txt.part").exists()

    second_transport = FakeTransport()
    second = fetcher.fetch_file(
        source,
        source.files[0],
        root=tmp_path,
        transport=second_transport,
        previous=lockfile.Lock(),
    )
    assert second.status is FileStatus.DOWNLOADED
    assert second_transport.requests == [(URL, 0)]
    assert (tmp_path / "example" / "ref.txt").read_bytes() == PAYLOAD


def test_an_existing_unpinned_short_part_is_discarded_before_open(tmp_path: Path) -> None:
    source = make_source(sha256=None, unpinned_reason="rolling latest release")
    part = tmp_path / "example" / "ref.txt.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(PAYLOAD[:120])
    transport = FakeTransport()

    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=transport, previous=lockfile.Lock()
    )

    assert result.status is FileStatus.DOWNLOADED
    assert transport.requests == [(URL, 0)]
    assert (tmp_path / "example" / "ref.txt").read_bytes() == PAYLOAD


def test_an_unpinned_oversized_first_fetch_is_discarded(tmp_path: Path) -> None:
    source = make_source(sha256=None, unpinned_reason="rolling latest release")
    oversized = PAYLOAD + b"unexpected trailing bytes"

    result = fetcher.fetch_file(
        source,
        source.files[0],
        root=tmp_path,
        transport=FakeTransport({URL: oversized}),
        previous=lockfile.Lock(),
    )

    assert result.status is FileStatus.FAILED
    assert "size mismatch" in result.detail
    assert not (tmp_path / "example" / "ref.txt").exists()
    assert not (tmp_path / "example" / "ref.txt.part").exists()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def test_a_digest_mismatch_discards_the_partial_file(tmp_path: Path) -> None:
    """Keeping it would poison every later resume, failing forever for an invisible reason."""
    source = make_source()
    transport = FakeTransport({URL: b"x" * len(PAYLOAD)})
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


def test_an_unpinned_present_file_with_the_wrong_size_is_rejected(tmp_path: Path) -> None:
    source = make_source(sha256=None, unpinned_reason="rolling latest release")
    target = tmp_path / "example" / "ref.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(PAYLOAD[:-1])

    transport = FakeTransport()
    result = fetcher.fetch_file(
        source,
        source.files[0],
        root=tmp_path,
        transport=transport,
        previous=lockfile.Lock(),
    )

    assert result.status is FileStatus.FAILED
    assert "size mismatch" in result.detail
    assert "delete it" in result.detail
    assert transport.requests == []


def test_verify_enforces_manifest_size_without_a_digest(tmp_path: Path) -> None:
    source = make_source(sha256=None, unpinned_reason="rolling latest release")
    target = tmp_path / "example" / "ref.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(PAYLOAD[:-1])

    result = fetcher.verify_file(source, source.files[0], root=tmp_path, previous=lockfile.Lock())

    assert result.status is FileStatus.FAILED
    assert "size mismatch" in result.detail
    assert "delete it" in result.detail


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
    source = make_source()
    for filename in ("../../escape.txt", "."):
        escaping = manifest.RemoteFile(url=URL, filename=filename, sha256=PAYLOAD_SHA)
        with pytest.raises(fetcher.FetchError, match="not inside"):
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


def test_fetch_executes_implemented_post_processing_and_reports_it(tmp_path: Path) -> None:
    events: list[fetcher.ProgressEvent] = []
    vcf = gzip.compress(
        b"##fileformat=VCFv4.2\n"
        b"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        b"NC_000001.10\t101\trs101\tA\tG\t.\t.\tRS=101\n"
    )
    url = "https://example.org/dbsnp.vcf.gz"
    item = manifest.RemoteFile(
        url=url,
        filename="dbsnp.vcf.gz",
        sha256=hashlib.sha256(vcf).hexdigest(),
        size_bytes=len(vcf),
    )
    source = manifest.Source(
        id="dbsnp_test",
        name="Synthetic dbSNP",
        tier=manifest.Tier.A,
        version="test",
        homepage="https://example.org/",
        license_id="CC0-1.0",
        files=(item,),
        post_process=(
            manifest.PostProcess(
                step="extract_dbsnp_variant_index",
                params={"input": "dbsnp.vcf.gz", "output": "dbsnp_variants.parquet"},
            ),
        ),
    )
    report = fetcher.fetch(
        manifest.Manifest(schema_version=1, sources=(source,)),
        root=tmp_path / "refs",
        transport=FakeTransport({url: vcf}),
        lock_path=tmp_path / "manifest.lock",
        include_optional=True,
        progress=events.append,
    )

    assert report.ok
    process = report.sources[0].process_results[0]
    assert process.status == "created"
    assert process.rows == 1
    assert (tmp_path / "refs" / "dbsnp_test" / "dbsnp_variants.parquet").is_file()
    assert any(event.unit == "rows" and event.downloaded == 1 for event in events)


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


def test_a_detected_corruption_does_not_launder_itself_into_the_lock(tmp_path: Path) -> None:
    """The lock's one guarantee, and it used to fail open after a single failure.

    Recording only this run's successes *replaced* the file map, so the digest of the file
    that failed was dropped. With nothing left to compare against, the next run reported
    the corrupt file already-present and wrote its digest in as truth -- one detected
    corruption was enough to bless itself.
    """
    payload_b = b"file B contents, quite distinct"
    url_a, url_b = "https://example.org/a", "https://example.org/b"
    source = manifest.Source(
        id="two",
        name="Two",
        tier=manifest.Tier.A,
        version="1",
        homepage="https://example.org/",
        license_id="CC0-1.0",
        required=True,
        files=(
            manifest.RemoteFile(url=url_a, filename="a.txt", unpinned_reason="rolling"),
            manifest.RemoteFile(url=url_b, filename="b.txt", unpinned_reason="rolling"),
        ),
    )
    parsed = manifest.Manifest(schema_version=1, sources=(source,))
    transport = FakeTransport({url_a: PAYLOAD, url_b: payload_b})
    root, lock_path = tmp_path / "refs", tmp_path / "manifest.lock"

    fetcher.fetch(parsed, root=root, transport=transport, lock_path=lock_path, today="2026-01-01")
    assert set(lockfile.read(lock_path).sources["two"].files) == {"a.txt", "b.txt"}

    (root / "two" / "b.txt").write_bytes(b"CORRUPTED")
    fetcher.fetch(parsed, root=root, transport=transport, lock_path=lock_path, today="2026-01-02")

    recorded = lockfile.read(lock_path)
    assert "b.txt" in recorded.sources["two"].files, "the failed file's digest must survive"
    assert recorded.file_digest("two", "b.txt") == hashlib.sha256(payload_b).hexdigest()

    # And the corruption stays caught on every later run, rather than becoming the record.
    third = fetcher.fetch(
        parsed, root=root, transport=transport, lock_path=lock_path, today="2026-01-03"
    )
    assert not third.ok
    assert (
        lockfile.read(lock_path).file_digest("two", "b.txt")
        != hashlib.sha256(b"CORRUPTED").hexdigest()
    )


def test_a_satisfied_manual_source_still_records_its_licence(tmp_path: Path) -> None:
    """OMIM and SNPedia are the most encumbered entries in the manifest and have no files.

    The lock previously skipped a source that completed with no files, so their obligations
    vanished from the record at exactly the moment their data was present -- and
    manifest.lock is what M15.4 reads to confirm nothing non-permissive was vendored.
    """
    source = manifest.Source(
        id="gated",
        name="Gated",
        tier=manifest.Tier.B,
        version="1",
        homepage="https://example.org/",
        license_id="CC0-1.0",
        manual=manifest.ManualStep(
            instructions="Fetch it by hand.",
            url="https://example.org/form",
            expected_files=("thing.txt",),
        ),
    )
    parsed = manifest.Manifest(schema_version=1, sources=(source,))
    root, lock_path = tmp_path / "refs", tmp_path / "manifest.lock"
    (root / "gated").mkdir(parents=True)
    (root / "gated" / "thing.txt").write_text("done")

    report = fetcher.fetch(
        parsed,
        root=root,
        transport=FakeTransport(),
        lock_path=lock_path,
        include_optional=True,
        today="2026-01-01",
    )
    assert report.ok
    assert "gated" in lockfile.read(lock_path).sources


def test_verify_is_not_gated_on_the_licence(tmp_path: Path) -> None:
    """The gate governs acquiring data, not inspecting what is already on disk.

    Applying it to verification made the integrity check unreachable for exactly the
    sources whose licence had already been accepted, and meant a full verify could never
    exit 0.
    """
    source = make_source(license_id="CC-BY-NC-SA-3.0-US")
    target = tmp_path / "example" / "ref.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(PAYLOAD)

    result = fetcher.fetch_source(
        source,
        root=tmp_path,
        transport=FakeTransport(),
        previous=lockfile.Lock(),
        verify_only=True,
    )
    assert result.status is SourceStatus.COMPLETE
    assert result.files[0].status is FileStatus.VERIFIED


def test_a_complete_part_is_promoted_instead_of_re_requested(tmp_path: Path) -> None:
    """The transfer finished but the process died before hashing and renaming.

    That window is minutes wide on a 63 GB file. Asking for `Range: bytes=<size>-` gets a
    416 from a correct server, which surfaced as "could not open" forever -- while the
    neighbouring message advised rerunning to resume.
    """
    source = make_source()
    part = tmp_path / "example" / "ref.txt.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(PAYLOAD)

    class Refuses416:
        def open(self, url: str, *, offset: int = 0) -> Chunked:
            raise OSError("HTTP Error 416: Requested Range Not Satisfiable")

    result = fetcher.fetch_file(
        source, source.files[0], root=tmp_path, transport=Refuses416(), previous=lockfile.Lock()
    )
    assert result.status is FileStatus.DOWNLOADED
    assert (tmp_path / "example" / "ref.txt").read_bytes() == PAYLOAD
    assert not part.exists()


def test_a_206_without_a_readable_content_range_is_an_error_not_a_restart() -> None:
    """Treating it as a fresh 200 truncated the head of the file.

    The caller would open the part "wb" and write a body that actually begins at `offset`
    starting at byte 0. For an unpinned file on a first fetch nothing would catch it, and
    the short content would be recorded in the lock as authoritative.
    """
    assert fetcher._parse_content_range(None) is None
    assert fetcher._parse_content_range("garbage") is None
    assert fetcher._parse_content_range("bytes 100-199/200") == (100, 200)
    assert fetcher._parse_content_range("bytes 100-199/*") == (100, None)


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
