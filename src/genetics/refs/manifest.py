"""Schema and validation for ``data/references/manifest.yaml`` (roadmap M2.1).

AGENTS.md 5.5 fixes the shape: one fetcher driven by a committed manifest pinning source
URL, version, checksum and licence per source; the manifest is committed and the payloads
are not. This module is that schema, and the validation is deliberately strict --
everything checkable is checked when the file loads, because the alternative is
discovering a typo after a 60 GB download.

Three decisions here are load-bearing.

**A source names its licence; it does not describe it.** ``license: CC-BY-SA-4.0`` is
resolved through :mod:`genetics.refs.licenses`, so no manifest edit can widen what a
licence permits. See that module for why this is not merely tidier.

**A file is pinned by digest, or it says why it is not.** Some publishers version their
releases (ClinVar's dated archive, dbSNP's per-build path) and those get a real sha256 or
the publisher's own md5. Others serve a rolling "latest" URL whose content changes under a
fixed name, and no honest checksum exists for those. Rather than omit the field and let
the difference disappear, an unpinned file must carry
:attr:`RemoteFile.unpinned_reason`. The fetcher then records what it actually received in
``manifest.lock``, which is committed -- so the first fetch pins the file for everyone
afterwards, and a later silent change shows up as a verification failure instead of new
results.

**No URL templating.** The per-chromosome sources would be shorter with a ``{chrom}``
placeholder, and the two big panels show why that would be a trap: 1000 Genomes names
chromosome X ``...v1c...`` where the autosomes are ``...v5b...``, and every file has its
own size. A template invites adding a chromosome nobody checked exists. In a file whose
entire job is pinning, verbosity is the feature.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from genetics.refs import licenses, postprocess

SCHEMA_VERSION = 1
"""Bumped when a change would make an older reader misinterpret the file. A reader that
does not recognise the version refuses rather than guessing."""

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
"""Source ids appear in directory names, lock keys and card provenance. Restricting them
to lowercase-and-underscore keeps all three trivially safe."""


class ManifestError(ValueError):
    """Raised for any structural or semantic problem in the manifest."""


class Tier(StrEnum):
    """Availability tier, per AGENTS.md section 5."""

    A = "A"
    """Free, permissive, auto-fetchable. No account, no human step."""

    B = "B"
    """Free but gated behind a one-time human step -- a web form, a registered API key."""

    C = "C"
    """Genuinely restricted. Present in the manifest so its absence is documented rather
    than mysterious; never fetched without an explicit opt-in."""


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ManifestError(f"{where}: missing required key {key!r}")
    return mapping[key]


def _check_relative_filename(name: str, where: str) -> None:
    """Reject anything that would let a manifest entry write outside its own directory.

    The manifest is a committed file that names paths the fetcher creates. It is trusted
    input today, but "trusted input that constructs a filesystem path" is exactly the
    shape that stops being trusted the moment someone fetches a manifest from elsewhere or
    a third source is added by copy-paste. Checking here costs nothing; the fetcher
    re-checks after joining, because only the post-join check is actually load-bearing.
    """
    if not name:
        raise ManifestError(f"{where}: filename is empty")
    if "\\" in name or "\x00" in name:
        raise ManifestError(f"{where}: filename {name!r} contains a backslash or NUL")
    pure = PurePosixPath(name)
    if pure.is_absolute() or name.startswith("/"):
        raise ManifestError(f"{where}: filename {name!r} must be relative")
    if ".." in pure.parts:
        raise ManifestError(f"{where}: filename {name!r} escapes its directory")
    # "." has no parts at all, so neither check above sees it, and it names the source's
    # own directory rather than a file inside it.
    if not pure.parts or pure.parts[-1] in {".", ""}:
        raise ManifestError(f"{where}: filename {name!r} does not name a file")
    # A Windows drive-relative name such as "C:data" is not absolute by PurePosixPath's
    # reckoning but is by the platform's, so PurePosixPath alone would pass it through.
    if re.match(r"^[A-Za-z]:", name):
        raise ManifestError(f"{where}: filename {name!r} looks like a Windows drive path")


@dataclass(frozen=True)
class RemoteFile:
    """One downloadable file."""

    url: str
    filename: str
    """Where it lands, relative to the source's directory."""

    sha256: str | None = None
    md5: str | None = None
    """The publisher's own digest where they publish one. NCBI ships ``.md5`` sidecars;
    md5 is weak against a deliberate collision but perfectly good against the failure this
    actually guards -- a truncated or corrupted transfer."""

    size_bytes: int | None = None
    unpinned_reason: str | None = None

    @property
    def pinned(self) -> bool:
        return self.sha256 is not None or self.md5 is not None

    @classmethod
    def parse(cls, raw: Mapping[str, Any], where: str) -> RemoteFile:
        if not isinstance(raw, Mapping):
            raise ManifestError(f"{where}: each file must be a mapping")
        url = str(_require(raw, "url", where))
        filename = str(_require(raw, "filename", where))
        _check_relative_filename(filename, where)

        if not url.startswith("https://"):
            # Plain http and ftp offer no integrity guarantee, and an unpinned file
            # fetched over them is unverifiable in both directions at once.
            raise ManifestError(f"{where}: url must be https, got {url!r}")

        sha256 = raw.get("sha256")
        md5 = raw.get("md5")
        for label, digest, width in (("sha256", sha256, 64), ("md5", md5, 32)):
            if digest is None:
                continue
            text = str(digest).strip().lower()
            if not re.fullmatch(rf"[0-9a-f]{{{width}}}", text):
                raise ManifestError(f"{where}: {label} must be {width} hex characters")

        reason = raw.get("unpinned_reason")
        pinned = sha256 is not None or md5 is not None
        if not pinned and not reason:
            raise ManifestError(
                f"{where}: {filename!r} has no sha256 or md5 and no unpinned_reason. "
                "A file that cannot be pinned is acceptable -- rolling 'latest' URLs "
                "genuinely have no stable digest -- but it has to say so, so that the "
                "difference between 'unpinnable' and 'nobody bothered' survives review."
            )
        if pinned and reason:
            raise ManifestError(f"{where}: {filename!r} is pinned but also carries unpinned_reason")

        size = raw.get("size_bytes")
        if size is not None and (not isinstance(size, int) or size <= 0):
            raise ManifestError(f"{where}: size_bytes must be a positive integer")

        return cls(
            url=url,
            filename=filename,
            sha256=str(sha256).strip().lower() if sha256 is not None else None,
            md5=str(md5).strip().lower() if md5 is not None else None,
            size_bytes=size,
            unpinned_reason=str(reason) if reason else None,
        )


@dataclass(frozen=True)
class PostProcess:
    """A declared transformation, resolved against :mod:`genetics.refs.postprocess`."""

    step: str
    params: Mapping[str, Any] = field(default_factory=dict)

    @property
    def definition(self) -> postprocess.Step:
        return postprocess.get(self.step)

    @classmethod
    def parse(cls, raw: Mapping[str, Any], where: str) -> PostProcess:
        if not isinstance(raw, Mapping):
            raise ManifestError(f"{where}: each post_process entry must be a mapping")
        name = str(_require(raw, "step", where))
        try:
            definition = postprocess.get(name)
        except postprocess.UnknownStepError as exc:
            raise ManifestError(f"{where}: {exc}") from None

        params = raw.get("params") or {}
        if not isinstance(params, Mapping):
            raise ManifestError(f"{where}: params must be a mapping")

        missing = [p for p in definition.required_params if p not in params]
        if missing:
            raise ManifestError(f"{where}: step {name!r} requires param(s) {', '.join(missing)}")
        allowed = set(definition.required_params) | set(definition.optional_params)
        unexpected = sorted(set(params) - allowed)
        if unexpected:
            raise ManifestError(
                f"{where}: step {name!r} got unexpected param(s) {', '.join(unexpected)}. "
                f"Accepted: {', '.join(sorted(allowed)) or 'none'}."
            )
        # These values become filesystem writes/reads in the post-process runner.  They
        # get the same early traversal refusal as downloaded filenames; the runner also
        # performs a resolved-path containment check as the load-bearing second layer.
        for path_param, value in params.items():
            if path_param not in {"input", "output"} and not path_param.endswith("_output"):
                continue
            if not isinstance(value, str):
                raise ManifestError(f"{where}.{path_param}: filesystem path must be a string")
            _check_relative_filename(value, f"{where}.{path_param}")
        return cls(step=name, params=dict(params))


@dataclass(frozen=True)
class ManualStep:
    """The one-time human action a Tier B source needs (roadmap M2.4).

    Modelled as data rather than prose in a README because the fetcher has to *act* on it:
    skip the source, tell the user exactly what to do, and re-check afterwards. A README
    cannot be checked by ``refs status``.
    """

    instructions: str
    url: str
    env_var: str | None = None
    """Environment variable carrying a user-supplied credential, for sources that need
    one. The value is never written to the lock, never logged, and never cached."""

    expected_files: tuple[str, ...] = ()
    """Files the user is expected to place in the source directory. Their presence is how
    ``refs status`` decides the manual step is done."""

    retention: str | None = None
    """Any obligation to *not* keep the data -- OMIM requires weekly refresh and forbids a
    derivative database, so its payload has an expiry rather than a checksum."""

    @classmethod
    def parse(cls, raw: Mapping[str, Any], where: str) -> ManualStep:
        if not isinstance(raw, Mapping):
            raise ManifestError(f"{where}: manual must be a mapping")
        files = raw.get("expected_files") or []
        if not isinstance(files, Sequence) or isinstance(files, str):
            raise ManifestError(f"{where}: expected_files must be a list")
        for name in files:
            _check_relative_filename(str(name), f"{where}.expected_files")
        return cls(
            instructions=str(_require(raw, "instructions", where)),
            url=str(_require(raw, "url", where)),
            env_var=str(raw["env_var"]) if raw.get("env_var") else None,
            expected_files=tuple(str(f) for f in files),
            retention=str(raw["retention"]) if raw.get("retention") else None,
        )


@dataclass(frozen=True)
class Source:
    """One reference database."""

    id: str
    name: str
    tier: Tier
    version: str
    homepage: str
    license_id: str
    required: bool = False
    files: tuple[RemoteFile, ...] = ()
    post_process: tuple[PostProcess, ...] = ()
    manual: ManualStep | None = None
    enables: tuple[str, ...] = ()
    """Plain-language capabilities this source unlocks, for ``refs status`` to explain
    what is lost while it is missing. gnomAD's absence should read as "the frequency gate
    cannot be computed", not as a missing file."""

    imputation_panel: bool = False
    """This source is a phasing/imputation reference panel, which AGENTS.md 5.5 says must
    never be reduced to array positions -- imputation needs the full panel.

    The flag names the *role*, not a blanket ban on subsetting, because the blunter rule
    would have been wrong: 1000 Genomes phase 3 is simultaneously the imputation panel and
    the source of the PCA marker subset (roadmap M5.3), so "this source may not be
    subsetted" would forbid something the roadmap explicitly requires. What is actually
    forbidden is *replacing* the panel with a subset. Validation therefore rejects
    ``subset_vcf_to_array_positions`` here while allowing ``build_pca_marker_subset``,
    which writes a separate artifact and leaves the panel intact."""

    notes: str = ""

    @property
    def license(self) -> licenses.LicenseTerms:
        return licenses.get(self.license_id)

    @property
    def total_size_bytes(self) -> int | None:
        """Sum of declared file sizes, or None if any file is unmeasured.

        None rather than a partial sum on purpose: a preflight disk check that silently
        under-reports is worse than one that admits it does not know.
        """
        if not self.files:
            return None
        if any(f.size_bytes is None for f in self.files):
            return None
        return sum(f.size_bytes or 0 for f in self.files)

    @property
    def needs_manual_step(self) -> bool:
        return self.manual is not None

    @classmethod
    def parse(cls, raw: Mapping[str, Any], where: str) -> Source:
        if not isinstance(raw, Mapping):
            raise ManifestError(f"{where}: each source must be a mapping")

        source_id = str(_require(raw, "id", where))
        if not _ID_RE.match(source_id):
            raise ManifestError(
                f"{where}: id {source_id!r} must be lowercase letters, digits and "
                "underscores, starting with a letter or digit"
            )
        where = f"source {source_id!r}"

        tier_raw = str(_require(raw, "tier", where))
        try:
            tier = Tier(tier_raw)
        except ValueError:
            raise ManifestError(
                f"{where}: tier must be one of A, B, C -- got {tier_raw!r}"
            ) from None

        license_id = str(_require(raw, "license", where))
        try:
            licenses.get(license_id)
        except licenses.UnknownLicenseError as exc:
            raise ManifestError(f"{where}: {exc.args[0]}") from None

        raw_files = raw.get("files") or []
        if not isinstance(raw_files, Sequence) or isinstance(raw_files, str):
            raise ManifestError(f"{where}: files must be a list")
        files = tuple(
            RemoteFile.parse(item, f"{where} file #{i + 1}") for i, item in enumerate(raw_files)
        )
        seen: set[str] = set()
        for item in files:
            if item.filename in seen:
                raise ManifestError(f"{where}: duplicate filename {item.filename!r}")
            seen.add(item.filename)

        raw_steps = raw.get("post_process") or []
        if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, str):
            raise ManifestError(f"{where}: post_process must be a list")
        steps = tuple(
            PostProcess.parse(item, f"{where} post_process #{i + 1}")
            for i, item in enumerate(raw_steps)
        )

        manual_raw = raw.get("manual")
        manual = ManualStep.parse(manual_raw, f"{where}.manual") if manual_raw else None

        required = bool(raw.get("required", False))
        imputation_panel = bool(raw.get("imputation_panel", False))

        enables_raw = raw.get("enables") or []
        if not isinstance(enables_raw, Sequence) or isinstance(enables_raw, str):
            raise ManifestError(f"{where}: enables must be a list")

        source = cls(
            id=source_id,
            name=str(_require(raw, "name", where)),
            tier=tier,
            version=str(_require(raw, "version", where)),
            homepage=str(_require(raw, "homepage", where)),
            license_id=license_id,
            required=required,
            files=files,
            post_process=steps,
            manual=manual,
            enables=tuple(str(e) for e in enables_raw),
            imputation_panel=imputation_panel,
            notes=str(raw.get("notes", "")),
        )
        source._validate(where)
        return source

    def _validate(self, where: str) -> None:
        if self.tier is Tier.A and self.manual is not None:
            raise ManifestError(
                f"{where}: tier A means auto-fetchable, but a manual step is declared. "
                "Move it to tier B."
            )
        if self.tier is not Tier.A and self.manual is None:
            raise ManifestError(
                f"{where}: tier {self.tier.value} exists to describe a source that cannot "
                "simply be downloaded, so it must declare a manual step saying what the "
                "human has to do."
            )
        if self.required and self.tier is not Tier.A:
            raise ManifestError(
                f"{where}: a required source cannot be tier {self.tier.value}. Requiring a "
                "source that is gated behind a web form or an API key makes a fresh "
                "checkout unusable until someone fills in a form, which is not what "
                "'required' should mean."
            )
        if not self.files and self.manual is None:
            raise ManifestError(f"{where}: has neither files nor a manual step")

        # Post-processing is an ordered filesystem program.  Validate that program before
        # any bytes move: an input must already exist as a download or an earlier output,
        # and no output may overwrite either a publisher payload or another derived
        # artifact.  Without this, a one-word typo can atomically replace a checksum-pinned
        # source after fetch verified it while the lock still records the original digest.
        downloaded = {item.filename for item in self.files}
        available = set(downloaded)
        derived: set[str] = set()
        reserved: set[str] = set()

        def implementation_paths(output: str, *, merge_primary: bool) -> set[str]:
            parent, separator, name = output.rpartition("/")

            def sibling(sibling_name: str) -> str:
                return f"{parent}/{sibling_name}" if separator else sibling_name

            paths = {
                output,
                sibling(f"{name}.provenance.json"),
                sibling(f".{name}.provenance.json.part"),
                sibling(f".{name}.part"),
                sibling(f".{name}.chunks"),
            }
            if merge_primary:
                classified = f".{name}.classified.parquet"
                paths.update(
                    {
                        sibling(classified),
                        sibling(f"{classified}.provenance.json"),
                        sibling(f".{classified}.provenance.json.part"),
                        sibling(f".{classified}.part"),
                        sibling(f".{classified}.chunks"),
                    }
                )
            return paths

        for number, step in enumerate(self.post_process, start=1):
            step_where = f"{where} post_process #{number} ({step.step})"
            input_name = step.params.get("input")
            if input_name is not None and input_name not in available:
                raise ManifestError(
                    f"{step_where}: input {input_name!r} is not a downloaded file or an "
                    "output of an earlier post-processing step"
                )

            output_params = [
                (key, str(value))
                for key, value in step.params.items()
                if key == "output" or key.endswith("_output")
            ]
            outputs = [output for _, output in output_params]
            if len(outputs) != len(set(outputs)):
                raise ManifestError(f"{step_where}: two output parameters name the same path")
            step_reserved: set[str] = set()
            for output_param, output in output_params:
                if output in downloaded:
                    raise ManifestError(
                        f"{step_where}: output {output!r} would overwrite a downloaded file"
                    )
                if output in derived:
                    raise ManifestError(
                        f"{step_where}: duplicate post-processing output {output!r}"
                    )
                owned = implementation_paths(
                    output,
                    merge_primary=(
                        step.step == "extract_rsid_merge_table" and output_param == "output"
                    ),
                )
                download_collisions = sorted(owned & downloaded)
                if download_collisions:
                    raise ManifestError(
                        f"{step_where}: output {output!r} reserves implementation-owned "
                        f"path(s) {download_collisions}, which collide with downloaded files"
                    )
                output_collisions = sorted(owned & (reserved | step_reserved))
                if output_collisions:
                    raise ManifestError(
                        f"{step_where}: output {output!r} reserves implementation-owned "
                        f"path(s) {output_collisions}, which collide with another output"
                    )
                derived.add(output)
                available.add(output)
                step_reserved.update(owned)
            reserved.update(step_reserved)

        if self.imputation_panel:
            offenders = [
                step.step
                for step in self.post_process
                if step.step == "subset_vcf_to_array_positions"
            ]
            if offenders:
                raise ManifestError(
                    f"{where}: is an imputation panel but declares {', '.join(offenders)}, "
                    "which reduces it to array positions in place. AGENTS.md 5.5 is "
                    "explicit that imputation needs the full panel. If the goal is a PCA "
                    "marker subset, declare build_pca_marker_subset instead -- it writes a "
                    "separate artifact and leaves the panel whole."
                )


@dataclass(frozen=True)
class Manifest:
    """The parsed manifest."""

    schema_version: int
    sources: tuple[Source, ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for source in self.sources:
            if source.id in seen:
                raise ManifestError(f"duplicate source id {source.id!r}")
            seen.add(source.id)

    def get(self, source_id: str) -> Source:
        for source in self.sources:
            if source.id == source_id:
                return source
        known = ", ".join(s.id for s in self.sources)
        raise ManifestError(f"no source {source_id!r} in the manifest. Known: {known}.")

    def required(self) -> tuple[Source, ...]:
        return tuple(s for s in self.sources if s.required)

    def by_tier(self, tier: Tier) -> tuple[Source, ...]:
        return tuple(s for s in self.sources if s.tier is tier)

    def needing_opt_in(self) -> tuple[Source, ...]:
        """Sources the licence gate will refuse without an explicit opt-in."""
        return tuple(s for s in self.sources if s.license.needs_opt_in)


def loads(text: str, *, where: str = "<string>") -> Manifest:
    """Parse manifest YAML.

    ``yaml.safe_load`` rather than ``yaml.load``: the manifest is a committed file today,
    but full-fat YAML deserialisation constructs arbitrary Python objects, and the one
    thing this file is guaranteed to do is get copied between projects.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{where}: not valid YAML: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ManifestError(f"{where}: top level must be a mapping")

    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ManifestError(
            f"{where}: schema_version is {version!r}, this build understands "
            f"{SCHEMA_VERSION}. Refusing to guess at the differences."
        )

    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, str):
        raise ManifestError(f"{where}: 'sources' must be a list")
    if not raw_sources:
        raise ManifestError(f"{where}: 'sources' is empty")

    sources = tuple(
        Source.parse(item, f"{where} source #{i + 1}") for i, item in enumerate(raw_sources)
    )
    return Manifest(schema_version=SCHEMA_VERSION, sources=sources)


def load(path: Path | None = None) -> Manifest:
    """Load and validate the committed manifest."""
    from genetics.paths import reference_manifest

    target = path or reference_manifest()
    if not target.is_file():
        raise ManifestError(
            f"no manifest at {target}. It is committed to the repository, so its absence "
            "means a broken checkout rather than a missing download."
        )
    return loads(target.read_text(encoding="utf-8"), where=target.name)
