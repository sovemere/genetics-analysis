"""External tool acquisition (roadmap M2.5).

Four programs, each optional in a different way (see :mod:`genetics.doctor`). This module
installs the two that can be installed, and deliberately does not touch the two that
cannot:

* **PLINK 2** -- fetched and unpacked. Native Windows build, which is the whole reason it
  was chosen over ADMIXTURE (AGENTS.md 4.6, 4.9).
* **Beagle** -- a single jar; "installing" it means putting the file somewhere known.
* **Java** -- not installed. A JVM is a system-level dependency with its own installer,
  licensing and update story, and silently dropping a private JDK into an app data
  directory would be a surprising thing for a genome tool to do.
* **R + HIBAG** -- not installed, for the same reason plus a stronger one: HLA imputation
  is an optional module that must degrade gracefully when R is absent (AGENTS.md 4.9).
  ``genetics doctor`` reports on both; neither is acquired here.

Installed under ``tools_dir()``, never the repository
-----------------------------------------------------
AGENTS.md 1.5 puts app-written data outside the checkout, and ``.gitignore`` blocks
``*.exe``, ``*.jar`` and friends as a second line of defence. Both matter: a 38 MB
``plink2.exe`` committed to a public repo is a licensing and bloat problem rather than a
privacy one, but it is still not something to leave to a single guard.

Why the licence gate does not apply here
----------------------------------------
PLINK 2 and Beagle are GPLv3, which :mod:`genetics.refs.licenses` classifies as
restricted because copyleft on a *data* source would impose itself on a derived knowledge
pack. That reasoning does not transfer to a program we execute as a subprocess: we do not
link against it and we do not redistribute it, so running it imposes nothing on the output.
Applying the data gate here would have forced an opt-in for PLINK 2 -- a tool that is
required from M5 -- which would have been ceremony teaching people to pass a blanket
opt-in. The licence is still recorded in the installed-state file so the M15.4 audit sees
it.

Pinning
-------
AGENTS.md 4.9 says PLINK 2 is alpha and the exact build must be pinned. That is enforced
twice over: by sha256 on the archive, and by :attr:`Tool.version_check`, which runs the
installed binary and confirms it reports the version we pinned. The digest alone would not
catch the case that actually matters -- a correct download of a build whose behaviour has
moved -- because the archive would verify perfectly.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from genetics.refs import licenses
from genetics.refs.fetcher import FileStatus, Transport, UrllibTransport, download
from genetics.refs.manifest import ManifestError, _check_relative_filename, _require

TOOLS_SCHEMA_VERSION = 1

ANY_PLATFORM = "any"
"""Build key for a platform-independent artifact, such as a jar."""

INSTALLED_STATE = "installed.json"
"""Record of what is installed, written inside ``tools_dir()``.

Not committed, unlike ``manifest.lock``. A reference digest is a fact about content and is
the same everywhere; an installed tool is platform-specific by construction, so a
committed record would be a merge conflict between every contributor on a different OS.
"""

_VERIFY_TIMEOUT_S = 60


class ToolError(ValueError):
    """Raised for a malformed tools manifest or a failed install."""


class Kind(StrEnum):
    EXECUTABLE = "executable"
    JAR = "jar"


class InstallStatus(StrEnum):
    INSTALLED = "installed"
    ALREADY_INSTALLED = "already-installed"
    MISSING = "missing"
    UNSUPPORTED_PLATFORM = "unsupported-platform"
    VERSION_MISMATCH = "version-mismatch"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Platform identification
# ---------------------------------------------------------------------------


def current_platform() -> str:
    """This machine's build key, e.g. ``windows_x86_64``.

    Deliberately coarse. PLINK also publishes AVX2 builds that are meaningfully faster,
    and this does not select them: an AVX2 binary on a CPU without AVX2 dies with an
    illegal-instruction fault, which surfaces as an unexplained crash in the middle of a
    long pipeline rather than as a clear "wrong build" message. Detecting the capability
    reliably across three operating systems is more machinery than the speed is worth
    here, and AGENTS.md 0.1C is explicit that compute cost is not the binding constraint.
    """
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        arch = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        arch = machine or "unknown"

    # platform.system() rather than sys.platform: mypy narrows sys.platform to the host
    # it is running on, so the branches for the other two operating systems get reported
    # as unreachable under `warn_unreachable`. Comparing a plain string keeps all three
    # branches type-checked on every platform, which is the point of running CI on two.
    system = platform.system().lower()
    if system == "windows":
        return f"windows_{arch}"
    if system == "darwin":
        return f"macos_{arch}"
    return f"linux_{arch}"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolBuild:
    """One platform's download."""

    platform: str
    url: str
    filename: str
    sha256: str
    size_bytes: int
    member: str | None = None
    """Path inside the archive to the file we actually want. ``None`` for a bare download
    that is already the artifact, such as a jar."""

    archive: str | None = None
    """``zip``, ``tar.gz``, or ``None`` when the download is not an archive."""

    @classmethod
    def parse(cls, raw: Mapping[str, Any], where: str) -> ToolBuild:
        if not isinstance(raw, Mapping):
            raise ToolError(f"{where}: each build must be a mapping")
        filename = str(_require(raw, "filename", where))
        try:
            _check_relative_filename(filename, where)
        except ManifestError as exc:
            raise ToolError(str(exc)) from None

        url = str(_require(raw, "url", where))
        if not url.startswith("https://"):
            raise ToolError(f"{where}: url must be https, got {url!r}")

        sha = str(_require(raw, "sha256", where)).strip().lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ToolError(f"{where}: sha256 must be 64 hex characters")

        size = raw.get("size_bytes")
        if not isinstance(size, int) or size <= 0:
            raise ToolError(f"{where}: size_bytes must be a positive integer")

        archive = raw.get("archive")
        if archive is not None and archive not in {"zip", "tar.gz"}:
            raise ToolError(f"{where}: archive must be 'zip' or 'tar.gz', got {archive!r}")

        member = raw.get("member")
        if archive is not None and not member:
            raise ToolError(f"{where}: an archive build must name the member to extract")
        if member is not None:
            try:
                _check_relative_filename(str(member), f"{where}.member")
            except ManifestError as exc:
                raise ToolError(str(exc)) from None

        return cls(
            platform=str(_require(raw, "platform", where)),
            url=url,
            filename=filename,
            sha256=sha,
            size_bytes=size,
            member=str(member) if member else None,
            archive=str(archive) if archive else None,
        )


@dataclass(frozen=True)
class VersionCheck:
    """How to confirm the thing we installed is the thing we pinned."""

    args: tuple[str, ...]
    must_contain: str

    @classmethod
    def parse(cls, raw: Mapping[str, Any], where: str) -> VersionCheck:
        args = raw.get("args") or []
        if not isinstance(args, Sequence) or isinstance(args, str):
            raise ToolError(f"{where}: version_check.args must be a list")
        return cls(
            args=tuple(str(a) for a in args),
            must_contain=str(_require(raw, "must_contain", where)),
        )


@dataclass(frozen=True)
class Tool:
    """One external program."""

    id: str
    name: str
    version: str
    homepage: str
    license_id: str
    kind: Kind
    required_from: str
    builds: tuple[ToolBuild, ...]
    version_check: VersionCheck | None = None
    notes: str = ""

    @property
    def license(self) -> licenses.LicenseTerms:
        return licenses.get(self.license_id)

    def build_for(self, platform_key: str) -> ToolBuild | None:
        """The build to install here.

        An exact platform match wins over the ``any`` wildcard, so a tool that ships both
        a portable artifact and a native one for this machine gets the native one. Beagle
        is the wildcard case: one jar, identical everywhere.
        """
        for build in self.builds:
            if build.platform == platform_key:
                return build
        for build in self.builds:
            if build.platform == ANY_PLATFORM:
                return build
        return None

    @classmethod
    def parse(cls, raw: Mapping[str, Any], where: str) -> Tool:
        if not isinstance(raw, Mapping):
            raise ToolError(f"{where}: each tool must be a mapping")
        tool_id = str(_require(raw, "id", where))
        where = f"tool {tool_id!r}"

        license_id = str(_require(raw, "license", where))
        try:
            licenses.get(license_id)
        except licenses.UnknownLicenseError as exc:
            raise ToolError(f"{where}: {exc.args[0]}") from None

        kind_raw = str(_require(raw, "kind", where))
        try:
            kind = Kind(kind_raw)
        except ValueError:
            raise ToolError(f"{where}: kind must be 'executable' or 'jar'") from None

        raw_builds = raw.get("builds") or []
        if not isinstance(raw_builds, Sequence) or isinstance(raw_builds, str):
            raise ToolError(f"{where}: builds must be a list")
        builds = tuple(
            ToolBuild.parse(item, f"{where} build #{i + 1}") for i, item in enumerate(raw_builds)
        )
        if not builds:
            raise ToolError(f"{where}: declares no builds")

        seen: set[str] = set()
        for build in builds:
            if build.platform in seen:
                raise ToolError(f"{where}: duplicate build platform {build.platform!r}")
            seen.add(build.platform)

        check_raw = raw.get("version_check")
        check = (
            VersionCheck.parse(check_raw, f"{where}.version_check")
            if isinstance(check_raw, Mapping)
            else None
        )
        if kind is Kind.EXECUTABLE and check is None:
            raise ToolError(
                f"{where}: an executable must declare a version_check. AGENTS.md 4.9 "
                "requires the exact build to be pinned, and a checksum only proves the "
                "download was intact -- not that the binary reports the version we pinned."
            )

        return cls(
            id=tool_id,
            name=str(_require(raw, "name", where)),
            version=str(_require(raw, "version", where)),
            homepage=str(_require(raw, "homepage", where)),
            license_id=license_id,
            kind=kind,
            required_from=str(raw.get("required_from", "")),
            builds=builds,
            version_check=check,
            notes=str(raw.get("notes", "")),
        )


@dataclass(frozen=True)
class ToolManifest:
    schema_version: int
    tools: tuple[Tool, ...]

    def get(self, tool_id: str) -> Tool:
        for tool in self.tools:
            if tool.id == tool_id:
                return tool
        known = ", ".join(t.id for t in self.tools)
        raise ToolError(f"no tool {tool_id!r}. Known: {known}.")


def loads(text: str, *, where: str = "<string>") -> ToolManifest:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ToolError(f"{where}: not valid YAML: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ToolError(f"{where}: top level must be a mapping")

    version = raw.get("schema_version")
    if version != TOOLS_SCHEMA_VERSION:
        raise ToolError(
            f"{where}: schema_version is {version!r}, this build understands {TOOLS_SCHEMA_VERSION}"
        )

    raw_tools = raw.get("tools")
    if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, str) or not raw_tools:
        raise ToolError(f"{where}: 'tools' must be a non-empty list")

    tools = tuple(Tool.parse(item, f"{where} tool #{i + 1}") for i, item in enumerate(raw_tools))
    seen: set[str] = set()
    for tool in tools:
        if tool.id in seen:
            raise ToolError(f"{where}: duplicate tool id {tool.id!r}")
        seen.add(tool.id)
    return ToolManifest(schema_version=TOOLS_SCHEMA_VERSION, tools=tools)


def load(path: Path | None = None) -> ToolManifest:
    from genetics.paths import tools_manifest

    target = path or tools_manifest()
    if not target.is_file():
        raise ToolError(f"no tools manifest at {target}; it is committed to the repository")
    return loads(target.read_text(encoding="utf-8"), where=target.name)


# ---------------------------------------------------------------------------
# Archive extraction
# ---------------------------------------------------------------------------


def _safe_member_path(destination: Path, name: str) -> Path:
    """Resolve an archive member under ``destination``, refusing to escape it.

    Archives are attacker-controlled in the general case and merely publisher-controlled
    here, but "zip slip" -- a member named ``../../.bashrc`` -- is cheap to defend against
    and catastrophic to get wrong, and this code unpacks whatever a URL served. The check
    is on the *resolved* path rather than the name, so a member that escapes via a symlink
    component or a doubled separator is caught too.
    """
    if PurePosixPath(name).is_absolute() or name.startswith(("/", "\\")):
        raise ToolError(f"archive member {name!r} is an absolute path")
    target = (destination / name).resolve()
    root = destination.resolve()
    # Strictly inside: a member named "." or "" resolves to the destination itself, which
    # is not a file we can write and not something to wave through.
    if root not in target.parents:
        raise ToolError(f"archive member {name!r} escapes the destination directory")
    return target


def extract_member(archive_path: Path, kind: str, member: str, destination: Path) -> Path:
    """Pull one named member out of an archive. Returns the written path."""
    destination.mkdir(parents=True, exist_ok=True)

    if kind == "zip":
        with zipfile.ZipFile(archive_path) as bundle:
            names = bundle.namelist()
            if member not in names:
                raise ToolError(
                    f"{archive_path.name} does not contain {member!r}. Members: "
                    f"{', '.join(names[:10])}"
                )
            for name in names:
                _safe_member_path(destination, name)
            out = _safe_member_path(destination, member)
            out.parent.mkdir(parents=True, exist_ok=True)
            # Streamed rather than read whole: plink2.exe is 38 MB uncompressed, and
            # holding a decompressed binary in memory buys nothing.
            with bundle.open(member) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
        return out

    if kind == "tar.gz":
        with tarfile.open(archive_path, "r:gz") as bundle:
            names = bundle.getnames()
            if member not in names:
                raise ToolError(f"{archive_path.name} does not contain {member!r}")
            for entry in bundle.getmembers():
                if entry.issym() or entry.islnk():
                    # A link can point anywhere; the resolved-path check above cannot see
                    # through it, so links are refused rather than followed.
                    raise ToolError(f"archive member {entry.name!r} is a link")
                _safe_member_path(destination, entry.name)
            out = _safe_member_path(destination, member)
            out.parent.mkdir(parents=True, exist_ok=True)
            extracted = bundle.extractfile(member)
            if extracted is None:
                raise ToolError(f"{member!r} is not a regular file")
            with extracted as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
        return out

    raise ToolError(f"unsupported archive kind {kind!r}")


def _make_executable(path: Path) -> None:
    """Set the execute bit on POSIX.

    Not cosmetic. A zip built on or for Windows carries no POSIX mode, so the extracted
    binary lands mode 0644 and every later invocation fails with 'permission denied' --
    a message that points at filesystem permissions rather than at the installer. This
    repository has already been bitten once by exactly this: M0.4's pre-commit hook was
    committed mode 100644, so git skipped it on Linux and macOS while ``install-hooks``
    cheerfully reported success.
    """
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# Installing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallResult:
    tool_id: str
    status: InstallStatus
    path: str | None = None
    version: str | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in {InstallStatus.INSTALLED, InstallStatus.ALREADY_INSTALLED}


def tool_home(tools_root: Path, tool: Tool) -> Path:
    """Where a tool's files live. Versioned, so two builds can coexist."""
    return tools_root / tool.id / tool.version


def installed_path(tools_root: Path, tool: Tool, build: ToolBuild) -> Path:
    """The artifact we ultimately want to invoke.

    Resolves the member's **full relative path**, matching what :func:`extract_member`
    actually writes. Taking only the basename happened to agree with it for every build in
    today's manifest, because all of them name a bare file -- but the schema permits a
    member with a directory prefix, which several PLINK releases have used
    (``plink2_linux_x86_64/plink2``). With such a build the installer would write to
    ``home/plink2_linux_x86_64/plink2`` while every lookup checked ``home/plink2``, so the
    tool would install successfully and then report missing forever, re-downloading on
    every invocation.
    """
    home = tool_home(tools_root, tool)
    if build.member:
        return home / PurePosixPath(build.member)
    return home / build.filename


def verify_installed(build: ToolBuild, target: Path) -> str:
    """Re-check an already-present artifact against its pin. Returns a problem, or ``""``.

    Only meaningful for a **non-archive** build, where the installed file *is* the thing
    that was downloaded and ``build.sha256`` therefore describes it. For an archive build
    the installed file is an extracted member whose digest is not the archive's, and the
    archive is deleted after unpacking -- there identity rests on the mandatory
    ``version_check``, which is why the schema will not accept an executable without one.

    This exists because the two halves of the pin cover different tools. Beagle has no
    version flag, so ``data/tools.yaml`` says of it that "the sha256 is what establishes
    identity here" -- and that was true only at download time until this was added: a jar
    truncated or replaced after installation read as present forever, and rerunning the
    installer would not repair it.
    """
    if build.archive:
        return ""
    digest = hashlib.sha256()
    try:
        with target.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        return f"could not read the installed file: {exc}"
    if digest.hexdigest() != build.sha256:
        return (
            f"{target.name} does not match its pinned sha256. Reinstall with --force; the "
            "file on disk has been truncated, replaced, or corrupted since it was fetched."
        )
    return ""


def run_version_check(tool: Tool, target: Path) -> tuple[bool, str | None, str]:
    """Run the pinned version probe. Returns ``(ok, reported, detail)``."""
    check = tool.version_check
    if check is None:
        return True, None, ""
    try:
        result = subprocess.run(
            [str(target), *check.args],
            capture_output=True,
            text=True,
            timeout=_VERIFY_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, None, f"could not run the installed binary: {exc}"

    # Some tools report a version to stderr; take whichever spoke, as doctor does.
    reported = (result.stdout or result.stderr).strip().splitlines()
    first = reported[0].strip() if reported else ""
    if not first:
        return False, None, f"the binary printed no version (exit {result.returncode})"
    if check.must_contain not in first:
        return (
            False,
            first,
            (
                f"installed build reports {first!r}, which does not contain the pinned "
                f"{check.must_contain!r}. AGENTS.md 4.9 pins the exact build because PLINK 2 "
                f"is alpha software whose behaviour moves between them."
            ),
        )
    return True, first, ""


def install(
    tool: Tool,
    *,
    tools_root: Path,
    transport: Transport | None = None,
    platform_key: str | None = None,
    progress: Any = None,
    force: bool = False,
) -> InstallResult:
    """Download, verify, unpack and version-check one tool."""
    transport = transport or UrllibTransport()
    key = platform_key or current_platform()
    build = tool.build_for(key)
    if build is None:
        available = ", ".join(sorted(b.platform for b in tool.builds))
        return InstallResult(
            tool.id,
            InstallStatus.UNSUPPORTED_PLATFORM,
            detail=f"no {tool.name} build for {key}. Published builds: {available}.",
        )

    home = tool_home(tools_root, tool)
    target = installed_path(tools_root, tool, build)

    if target.is_file() and not force:
        problem = verify_installed(build, target)
        if problem:
            # Fall through and refetch rather than reporting a failure: a corrupted
            # artifact is a repairable condition, and the whole point of holding a pin is
            # being able to restore the file it describes.
            target.unlink(missing_ok=True)
        else:
            ok, reported, detail = run_version_check(tool, target)
            if ok:
                return InstallResult(
                    tool.id, InstallStatus.ALREADY_INSTALLED, str(target), reported or tool.version
                )
            return InstallResult(
                tool.id, InstallStatus.VERSION_MISMATCH, str(target), reported, detail
            )

    archive_target = home / build.filename
    outcome = download(
        build.url,
        archive_target,
        transport=transport,
        expected_sha256=build.sha256,
        expected_size=build.size_bytes,
        progress=progress,
        label=tool.id,
    )
    if outcome.status is FileStatus.FAILED:
        return InstallResult(tool.id, InstallStatus.FAILED, detail=outcome.detail)

    if build.archive:
        try:
            extracted = extract_member(archive_target, build.archive, build.member or "", home)
        except (ToolError, zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
            return InstallResult(tool.id, InstallStatus.FAILED, detail=f"could not unpack: {exc}")
        # The archive has served its purpose and is often larger than what it held.
        archive_target.unlink(missing_ok=True)
    else:
        extracted = archive_target

    if tool.kind is Kind.EXECUTABLE:
        _make_executable(extracted)

    ok, reported, detail = run_version_check(tool, extracted)
    if not ok:
        return InstallResult(
            tool.id, InstallStatus.VERSION_MISMATCH, str(extracted), reported, detail
        )

    return InstallResult(tool.id, InstallStatus.INSTALLED, str(extracted), reported or tool.version)


def status(tool: Tool, *, tools_root: Path, platform_key: str | None = None) -> InstallResult:
    """Report whether a tool is installed, without downloading anything."""
    key = platform_key or current_platform()
    build = tool.build_for(key)
    if build is None:
        available = ", ".join(sorted(b.platform for b in tool.builds))
        return InstallResult(
            tool.id,
            InstallStatus.UNSUPPORTED_PLATFORM,
            detail=f"no build for {key}. Published: {available}.",
        )
    target = installed_path(tools_root, tool, build)
    if not target.is_file():
        return InstallResult(
            tool.id,
            InstallStatus.MISSING,
            detail=f"not installed; needed from {tool.required_from or 'an unassigned milestone'}",
        )
    problem = verify_installed(build, target)
    if problem:
        return InstallResult(tool.id, InstallStatus.FAILED, str(target), detail=problem)

    ok, reported, detail = run_version_check(tool, target)
    if not ok:
        return InstallResult(tool.id, InstallStatus.VERSION_MISMATCH, str(target), reported, detail)
    return InstallResult(
        tool.id, InstallStatus.ALREADY_INSTALLED, str(target), reported or tool.version
    )


# ---------------------------------------------------------------------------
# Installed-state record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstalledState:
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)

    def render(self) -> str:
        payload = {"schema_version": TOOLS_SCHEMA_VERSION, "tools": self.tools}
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def recorded_path(tools_root: Path, tool_id: str) -> Path | None:
    """Where the installer last put ``tool_id``, if it is still there.

    The authoritative answer, and the reason it exists: ``genetics doctor`` used to look
    for tools by scanning the tools directory one level deep, while this module installs
    to ``<tools_root>/<id>/<version>/`` -- two levels. So a freshly installed PLINK 2 was
    reported missing by the very command whose job is telling you what you have. Guessing
    at a layout from another module is what broke it; reading what the installer recorded
    is what fixes it.
    """
    entry = read_state(tools_root).tools.get(tool_id)
    if not isinstance(entry, Mapping):
        return None
    raw = entry.get("path")
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_file() else None


def read_state(tools_root: Path) -> InstalledState:
    path = tools_root / INSTALLED_STATE
    if not path.is_file():
        return InstalledState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return InstalledState()
    tools = raw.get("tools") if isinstance(raw, Mapping) else None
    return InstalledState(tools=dict(tools) if isinstance(tools, Mapping) else {})


def record_install(tools_root: Path, tool: Tool, build: ToolBuild, result: InstallResult) -> None:
    """Note what landed, including the licence, for the M15.4 audit."""
    state = read_state(tools_root)
    tools = dict(state.tools)
    terms = tool.license
    tools[tool.id] = {
        "version": tool.version,
        "reported_version": result.version,
        "platform": build.platform,
        "path": result.path,
        "url": build.url,
        "sha256": build.sha256,
        "license": {"id": terms.id, "name": terms.name, "terms_url": terms.terms_url},
    }
    path = tools_root / INSTALLED_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(InstalledState(tools=tools).render(), encoding="utf-8")
