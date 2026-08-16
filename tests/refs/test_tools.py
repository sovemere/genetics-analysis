"""Tests for external tool acquisition (roadmap M2.5).

Two things here are worth more than the schema checks: that an archive cannot write
outside its destination, and that a version-checked tool actually refuses a build whose
reported version is not the one pinned. AGENTS.md 4.9 asks for an exact PLINK 2 pin, and
a checksum alone does not deliver that -- it proves the download was intact, not that the
binary is the build we meant.
"""

from __future__ import annotations

import io
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from genetics.refs import tools
from genetics.refs.fetcher import Chunked
from genetics.refs.tools import InstallStatus, Kind, ToolError

MINIMAL = """
schema_version: 1
tools:
  - id: widget
    name: Widget
    version: "1.0"
    homepage: https://example.org/
    license: GPL-3.0-or-later
    kind: jar
    required_from: M9
    builds:
      - platform: any
        url: https://example.org/widget.jar
        filename: widget.jar
        sha256: {sha}
        size_bytes: 12
"""

SHA = "b" * 64


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_minimal_tools_manifest_parses() -> None:
    parsed = tools.loads(MINIMAL.format(sha=SHA))
    widget = parsed.get("widget")
    assert widget.kind is Kind.JAR
    assert widget.build_for("windows_x86_64") is not None, "the 'any' build should match"


def test_an_executable_must_declare_a_version_check() -> None:
    """A checksum proves the bytes arrived; it does not prove which build they are."""
    text = MINIMAL.format(sha=SHA).replace("kind: jar", "kind: executable")
    with pytest.raises(ToolError, match="must declare a version_check"):
        tools.loads(text)


def test_unknown_licence_stops_the_tools_manifest_loading() -> None:
    text = MINIMAL.format(sha=SHA).replace("license: GPL-3.0-or-later", "license: Whatever-1.0")
    with pytest.raises(ToolError, match="unknown licence id"):
        tools.loads(text)


def test_non_https_and_bad_digests_are_rejected() -> None:
    with pytest.raises(ToolError, match="must be https"):
        tools.loads(MINIMAL.format(sha=SHA).replace("https://example.org/widget.jar", "http://x/y"))
    with pytest.raises(ToolError, match="64 hex characters"):
        tools.loads(MINIMAL.format(sha="nope"))


def test_an_archive_build_must_name_its_member() -> None:
    text = MINIMAL.format(sha=SHA).replace(
        "        size_bytes: 12", "        size_bytes: 12\n        archive: zip"
    )
    with pytest.raises(ToolError, match="must name the member"):
        tools.loads(text)


def test_duplicate_platforms_are_rejected() -> None:
    text = MINIMAL.format(sha=SHA).replace(
        "        size_bytes: 12\n",
        "        size_bytes: 12\n"
        "      - platform: any\n"
        "        url: https://example.org/other.jar\n"
        "        filename: other.jar\n"
        f"        sha256: {SHA}\n"
        "        size_bytes: 12\n",
    )
    with pytest.raises(ToolError, match="duplicate build platform"):
        tools.loads(text)


def test_an_exact_platform_build_beats_the_any_wildcard() -> None:
    text = MINIMAL.format(sha=SHA).replace(
        "        size_bytes: 12\n",
        "        size_bytes: 12\n"
        "      - platform: linux_x86_64\n"
        "        url: https://example.org/native.jar\n"
        "        filename: native.jar\n"
        f"        sha256: {SHA}\n"
        "        size_bytes: 12\n",
    )
    widget = tools.loads(text).get("widget")
    native = widget.build_for("linux_x86_64")
    portable = widget.build_for("macos_arm64")
    assert native is not None and native.filename == "native.jar"
    assert portable is not None and portable.filename == "widget.jar"


def test_current_platform_is_recognisable() -> None:
    key = tools.current_platform()
    assert key.split("_", 1)[0] in {"windows", "macos", "linux"}


# ---------------------------------------------------------------------------
# Archive safety
# ---------------------------------------------------------------------------


def test_a_zip_member_escaping_the_destination_is_refused(tmp_path: Path) -> None:
    """Zip slip. Cheap to defend, catastrophic to miss, and this code unpacks whatever a
    URL served."""
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../../escaped.txt", "pwned")
        bundle.writestr("plink2", "real content")

    with pytest.raises(ToolError, match="escapes the destination"):
        tools.extract_member(archive, "zip", "plink2", tmp_path / "dest")

    assert not (tmp_path.parent / "escaped.txt").exists()


def test_an_absolute_zip_member_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "abs.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("/etc/passwd", "pwned")
        bundle.writestr("plink2", "real")
    with pytest.raises(ToolError, match="absolute path"):
        tools.extract_member(archive, "zip", "plink2", tmp_path / "dest")


def test_a_tar_link_member_is_refused(tmp_path: Path) -> None:
    """A link can point anywhere, and a resolved-path check cannot see through it."""
    archive = tmp_path / "link.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("payload")
        data = b"real"
        info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("sneaky")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        bundle.addfile(link)

    with pytest.raises(ToolError, match="is a link"):
        tools.extract_member(archive, "tar.gz", "payload", tmp_path / "dest")


def test_extracting_a_missing_member_says_what_was_there(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("something_else", "x")
    with pytest.raises(ToolError, match="does not contain"):
        tools.extract_member(archive, "zip", "plink2", tmp_path / "dest")


def test_extraction_writes_the_member(tmp_path: Path) -> None:
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("plink2.exe", "binary content")
    out = tools.extract_member(archive, "zip", "plink2.exe", tmp_path / "dest")
    assert out.read_bytes() == b"binary content"
    assert out.parent == (tmp_path / "dest")


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits do not apply on Windows")
def test_an_extracted_executable_gets_its_execute_bit(tmp_path: Path) -> None:
    """A zip built for Windows carries no POSIX mode, so the binary lands 0644 and every
    later call fails with 'permission denied' -- pointing at the filesystem rather than at
    the installer. M0.4 was bitten by exactly this with the pre-commit hook."""
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("plink2", "#!/bin/sh\necho hi\n")
    out = tools.extract_member(archive, "zip", "plink2", tmp_path / "dest")
    assert not os.access(out, os.X_OK)
    tools._make_executable(out)
    assert os.access(out, os.X_OK)


# ---------------------------------------------------------------------------
# Version checking -- the half of the pin a checksum cannot provide
# ---------------------------------------------------------------------------


def make_tool(must_contain: str = "v2.0.0-a.7.3") -> tools.Tool:
    return tools.Tool(
        id="probe",
        name="Probe",
        version="v2.0.0-a.7.3",
        homepage="https://example.org/",
        license_id="GPL-3.0-or-later",
        kind=Kind.EXECUTABLE,
        required_from="M5",
        builds=(
            tools.ToolBuild(
                platform="any", url="https://example.org/p", filename="p", sha256=SHA, size_bytes=1
            ),
        ),
        version_check=tools.VersionCheck(
            args=("-c", "print('PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)')"),
            must_contain=must_contain,
        ),
    )


def test_a_matching_version_passes() -> None:
    ok, reported, detail = tools.run_version_check(make_tool(), Path(sys.executable))
    assert ok is True
    assert reported is not None and "a.7.3" in reported
    assert detail == ""


def test_a_build_reporting_the_wrong_version_is_refused() -> None:
    """The case a checksum cannot catch: an intact download of the wrong build."""
    ok, reported, detail = tools.run_version_check(
        make_tool(must_contain="v2.0.0-a.5.9"), Path(sys.executable)
    )
    assert ok is False
    assert "does not contain the pinned" in detail
    assert "alpha software" in detail
    # The version actually found is reported, not just the fact of a mismatch: without it
    # the operator cannot tell whether they have an old build or the wrong tool entirely.
    assert reported is not None and "a.7.3" in reported


def test_a_binary_that_cannot_run_is_reported_not_raised(tmp_path: Path) -> None:
    ok, _, detail = tools.run_version_check(make_tool(), tmp_path / "not-here")
    assert ok is False
    assert "could not run" in detail


def test_a_binary_that_prints_nothing_is_a_failure() -> None:
    """A probe whose success path prints nothing cannot be distinguished from a broken
    one -- the M0.6 HIBAG lesson, where a check could only ever return one answer."""
    tool = tools.Tool(
        id="quiet",
        name="Quiet",
        version="1",
        homepage="https://example.org/",
        license_id="GPL-3.0-or-later",
        kind=Kind.EXECUTABLE,
        required_from="M5",
        builds=(
            tools.ToolBuild(
                platform="any", url="https://example.org/q", filename="q", sha256=SHA, size_bytes=1
            ),
        ),
        version_check=tools.VersionCheck(args=("-c", "pass"), must_contain="anything"),
    )
    ok, _, detail = tools.run_version_check(tool, Path(sys.executable))
    assert ok is False
    assert "printed no version" in detail


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------


class FakeTransport:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, url: str, *, offset: int = 0) -> Chunked:
        return Chunked(
            stream=io.BytesIO(self.payload), total_size=len(self.payload), resumed_from=0
        )


def test_a_jar_installs_and_is_then_already_installed(tmp_path: Path) -> None:
    import hashlib

    payload = b"pretend jar bytes"
    tool = tools.Tool(
        id="beagleish",
        name="Beagle-like",
        version="1",
        homepage="https://example.org/",
        license_id="GPL-3.0-or-later",
        kind=Kind.JAR,
        required_from="M8",
        builds=(
            tools.ToolBuild(
                platform="any",
                url="https://example.org/b.jar",
                filename="b.jar",
                sha256=hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
            ),
        ),
    )
    result = tools.install(tool, tools_root=tmp_path, transport=FakeTransport(payload))
    assert result.status is InstallStatus.INSTALLED
    assert Path(result.path or "").read_bytes() == payload

    again = tools.status(tool, tools_root=tmp_path)
    assert again.status is InstallStatus.ALREADY_INSTALLED


def test_an_installed_jar_is_rechecked_against_its_pin(tmp_path: Path) -> None:
    """Beagle has no version flag, so its sha256 is the *only* thing establishing its
    identity -- and that was true only at download time until this check existed.

    Without it, a jar truncated or replaced after installation reads as present forever
    and rerunning the installer will not repair it, because presence alone satisfied the
    already-installed branch. For an archive build the equivalent guarantee comes from the
    mandatory version_check instead, since the installed file is an extracted member whose
    digest is not the archive's.
    """
    import hashlib

    payload = b"pretend jar bytes"
    tool = tools.Tool(
        id="jarred",
        name="Jarred",
        version="1",
        homepage="https://example.org/",
        license_id="GPL-3.0-or-later",
        kind=Kind.JAR,
        required_from="M8",
        builds=(
            tools.ToolBuild(
                platform="any",
                url="https://example.org/b.jar",
                filename="b.jar",
                sha256=hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
            ),
        ),
    )
    installed = tools.install(tool, tools_root=tmp_path, transport=FakeTransport(payload))
    assert installed.status is InstallStatus.INSTALLED

    target = Path(installed.path or "")
    target.write_bytes(b"TRUNCATED")

    checked = tools.status(tool, tools_root=tmp_path)
    assert checked.status is InstallStatus.FAILED
    assert "does not match its pinned sha256" in checked.detail

    # A corrupted artifact is repairable, not fatal: holding a pin is what makes it so.
    repaired = tools.install(tool, tools_root=tmp_path, transport=FakeTransport(payload))
    assert repaired.status is InstallStatus.INSTALLED
    assert target.read_bytes() == payload


def test_a_corrupted_download_does_not_install(tmp_path: Path) -> None:
    tool = tools.loads(MINIMAL.format(sha=SHA)).get("widget")
    # Same declared length, different bytes: this reaches the digest gate rather than
    # exercising the independent short-transfer/resume path.
    result = tools.install(tool, tools_root=tmp_path, transport=FakeTransport(b"wrong bytes!"))
    assert result.status is InstallStatus.FAILED
    assert "sha256 mismatch" in result.detail


def test_an_unsupported_platform_says_what_is_published(tmp_path: Path) -> None:
    text = MINIMAL.format(sha=SHA).replace("platform: any", "platform: linux_x86_64")
    tool = tools.loads(text).get("widget")
    result = tools.install(tool, tools_root=tmp_path, platform_key="sparc_solaris")
    assert result.status is InstallStatus.UNSUPPORTED_PLATFORM
    assert "linux_x86_64" in result.detail


def test_the_installed_record_carries_the_licence_for_the_audit(tmp_path: Path) -> None:
    import hashlib

    payload = b"jar"
    tool = tools.Tool(
        id="j",
        name="J",
        version="1",
        homepage="https://example.org/",
        license_id="GPL-3.0-or-later",
        kind=Kind.JAR,
        required_from="M8",
        builds=(
            tools.ToolBuild(
                platform="any",
                url="https://example.org/j.jar",
                filename="j.jar",
                sha256=hashlib.sha256(payload).hexdigest(),
                size_bytes=len(payload),
            ),
        ),
    )
    result = tools.install(tool, tools_root=tmp_path, transport=FakeTransport(payload))
    tools.record_install(tmp_path, tool, tool.builds[0], result)

    state = tools.read_state(tmp_path)
    assert state.tools["j"]["license"]["id"] == "GPL-3.0-or-later"
    assert state.tools["j"]["sha256"] == tool.builds[0].sha256


# ---------------------------------------------------------------------------
# The committed manifest
# ---------------------------------------------------------------------------


def test_the_committed_tools_manifest_is_valid() -> None:
    parsed = tools.load()
    assert {t.id for t in parsed.tools} == {"plink2", "beagle"}


def test_plink2_is_pinned_by_both_checksum_and_reported_version() -> None:
    """AGENTS.md 4.9: PLINK 2 is alpha and its behaviour moves between builds."""
    plink2 = tools.load().get("plink2")
    assert plink2.version_check is not None
    assert plink2.version_check.must_contain == plink2.version
    for build in plink2.builds:
        assert build.sha256 and build.url.startswith("https://")


def test_plink2_ships_a_build_for_every_platform_the_project_supports() -> None:
    """Windows is the primary platform (AGENTS.md 6) and CI runs ubuntu too."""
    platforms = {b.platform for b in tools.load().get("plink2").builds}
    assert {"windows_x86_64", "linux_x86_64", "macos_x86_64", "macos_arm64"} <= platforms


def test_beagle_is_platform_independent_and_needs_no_version_probe() -> None:
    beagle = tools.load().get("beagle")
    assert [b.platform for b in beagle.builds] == ["any"]
    assert beagle.kind is Kind.JAR
    assert beagle.version_check is None


def test_java_and_r_are_not_acquired() -> None:
    """Both are system dependencies, and HLA must degrade gracefully without R."""
    ids = {t.id for t in tools.load().tools}
    assert "java" not in ids
    assert "r" not in ids and "hibag" not in ids
