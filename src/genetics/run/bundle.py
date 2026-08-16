"""The run bundle format (roadmap M4.1).

A bundle is the saved record of one analysis: what was run, against which knowledge pack,
which reference releases and which tool builds, what QC found, and every scored card. It
is written outside the repository, it is never rewritten, and it is readable without the
code that produced it.

Four decisions are load-bearing. Each is a place where the obvious alternative fails
quietly rather than loudly.

**A bundle is self-contained; it stores rendered results, not references to cards.** The
tempting design records a card id per finding and re-renders from the knowledge pack at
read time, which halves the file size and keeps one copy of the text. It also means
editing a card tomorrow silently changes what a run saved today said -- and a saved run is
the thing a person read, discussed and may have acted on. So the summary, detail,
citations, caveats, confidence tier and the numeric inputs behind it are all written down
at save time. Nothing in :func:`read_bundle` touches ``knowledge/``.

**Reading does not reconstruct engine objects.** Sections, statuses and tiers come back as
plain strings, not as :class:`~genetics.engine.sections.Section` or
:class:`~genetics.engine.confidence.ConfidenceTier`. Re-hydrating an enum is exactly what
breaks when a later version renames a member, and M4.2 requires a months-old bundle to
re-read or fail with a clear version error -- not to fail with ``ValueError: 'traits' is
not a valid Section`` from four frames down. The format version is the compatibility gate;
the payload is data.

**Immutability is enforced by refusing to overwrite and by detecting change, not by
permissions.** File mode bits are a poor fit here -- M0.4 was already bitten by mode
handling differing across platforms -- and a read-only flag on a user's own data directory
is advisory anyway. So: a write refuses an existing run id, the payload is built under a
``.incoming-`` name and promoted by a single rename, and every payload file's sha256 is
recorded in the manifest and re-checked on read. That detects a partial write, a truncated
copy and a hand-edit. It does not detect tampering, and does not pretend to: a bundle is
local data, and defending it against someone who can write to their own disk is not a
coherent goal.

**A directory, not a single file.** M5 adds PCA coordinates, M8 imputed dosages and M9
per-score tables, and those do not belong in one JSON blob that must be parsed whole to
read a card. The atomicity a single file would have bought is recovered by the
build-then-rename above, which is the same pattern M3.5 used for the multi-gigabyte dbSNP
transforms.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Final

from genetics import __version__ as ENGINE_VERSION
from genetics.engine.cards import SCHEMA_VERSION as CARD_SCHEMA_VERSION
from genetics.engine.cards import KnowledgePack
from genetics.engine.citations import Citation
from genetics.engine.confidence import ConfidenceResult
from genetics.engine.evidence import AssembledCard, PopulationFrequency
from genetics.paths import UnsafeDataDirError, is_inside_repo, reference_lock, runs_dir, tools_dir
from genetics.privacy import NoGenotypeRepr, assert_no_genotype
from genetics.qc.report import QCReport
from genetics.refs import lock as refs_lock
from genetics.refs import tools as refs_tools

BUNDLE_FORMAT_VERSION: Final[int] = 1
"""Bumped whenever a reader of the previous version would misread the payload.

Adding a payload key counts: :func:`read_bundle` rejects unknown keys, on the same
reasoning as the card schema -- in a record this full of optional fields, a silently
ignored key is indistinguishable from one that had no effect. ``test_bundle.py`` pins the
key sets so the bump cannot be forgotten.
"""

MANIFEST_NAME: Final[str] = "manifest.json"
"""Provenance and digests. The one file here with no genotype in it, and therefore the one
that may be pasted into a bug report -- which is why it is scanned before it is written."""

QC_NAME: Final[str] = "qc.run.json"
CARDS_NAME: Final[str] = "cards.run.json"
"""The two genotype-bearing payload files, named to land on ``.gitignore``'s existing
``*.run.json`` rule.

A bundle is written outside the repository and an in-repo destination is refused outright,
so this is the third line of defence, not the first. It costs one suffix and it covers the
case those two miss: a bundle copied into the checkout by hand. ``test_bundle.py`` asserts
the suffix and the presence of the rule together, because a rename here would silently
drop the coverage and nothing else would notice.
"""

INCOMING_PREFIX: Final[str] = ".incoming-"
"""Marks a bundle still being written. Dot-prefixed so listing (M4.2) can skip it by
shape rather than by remembering to, and so a killed process leaves something visibly
unfinished rather than a run id with half a payload under it."""

_PAYLOAD_FILES: Final[tuple[str, ...]] = (QC_NAME, CARDS_NAME)


class BundleError(ValueError):
    """Raised for any structural problem writing or reading a bundle."""


class BundleVersionError(BundleError):
    """Raised for a bundle whose format version this code does not implement.

    Separate from :class:`BundleError` because it is the one failure with an obvious
    remedy -- use the version of the tool that wrote it -- and M4.2 requires it to be
    distinguishable from corruption.
    """


class BundleIntegrityError(BundleError):
    """Raised when a payload file's digest does not match the manifest."""


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _render(payload: Mapping[str, Any]) -> str:
    """Deterministic JSON: same inputs, same bytes, on every platform.

    Determinism is not cosmetic here -- the manifest records a digest of each payload
    file, so two runs that differ only in key ordering would produce different digests and
    the integrity check would have nothing stable to say.
    """
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_text(path: Path, text: str) -> None:
    # newline="" so the "\n" written above survives verbatim on Windows. Left to the
    # default, Python would translate them to CRLF, and the digest recorded by the writing
    # machine would then differ from the one a POSIX machine computes over the same
    # bundle copied across -- an integrity failure with no integrity problem behind it.
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _citation_payload(citation: Citation) -> dict[str, Any]:
    return {
        "type": citation.type.value,
        "id": citation.id,
        "title": citation.title,
        "database": citation.database,
        "note": citation.note,
    }


def _frequency_payload(frequency: PopulationFrequency) -> dict[str, Any]:
    return {
        "allele": frequency.allele,
        "frequency": frequency.frequency,
        "population": frequency.population,
        "source": frequency.source,
    }


def _confidence_payload(confidence: ConfidenceResult) -> dict[str, Any]:
    """Tier, score and every numeric input that produced them.

    The breakdown travels in full because M13.4 requires an agent to be able to explain
    *why* a card is low confidence, and because a tier without its inputs is exactly the
    unaccountable number AGENTS.md 6 forbids a card from authoring in the first place.
    """
    inputs = confidence.inputs
    ppv = confidence.empirical_ppv
    return {
        "tier": confidence.tier.value,
        "score": confidence.score,
        "inputs": {
            "evidence_tier": inputs.evidence_tier.value,
            "evidence_score": inputs.evidence_score,
            "effect_measure": inputs.effect_measure.value,
            "effect_value": inputs.effect_value,
            "effect_score": inputs.effect_score,
            "replication": inputs.replication.value,
            "replication_score": inputs.replication_score,
            "population_allele_frequency": inputs.population_allele_frequency,
            "frequency_score": inputs.frequency_score,
            "call_source": inputs.call_source.value,
            "imputation_quality": inputs.imputation_quality,
            "imputation_score": inputs.imputation_score,
            "ancestry_match": inputs.ancestry_match,
            "ancestry_score": inputs.ancestry_score,
        },
        "empirical_ppv": None
        if ppv is None
        else {
            "estimate": ppv.estimate,
            "population_frequency_ceiling": ppv.population_frequency_ceiling,
            "applies_to": ppv.applies_to,
        },
    }


def _card_payload(assembled: AssembledCard) -> dict[str, Any]:
    card = assembled.card
    match = assembled.match
    variant = card.match.variant if card.match is not None else None
    return {
        "card_id": assembled.card_id,
        "section": assembled.section.value,
        "kind": assembled.kind.value,
        "title": assembled.title,
        "gene": card.gene,
        "status": assembled.status.value,
        "summary": assembled.summary,
        "detail": assembled.detail,
        "impossibility_reason": card.impossibility_reason,
        "variant": None
        if variant is None
        else {
            "rsid": variant.rsid,
            "chrom": variant.key.chrom.value,
            "pos_grch37": variant.key.pos_grch37,
            "alleles": list(variant.key.alleles),
        },
        "match": {
            "reason": match.reason,
            "genotype": match.genotype,
            "observed_genotype": match.observed_genotype,
            "observed_rsid": match.observed_rsid,
            "call_status": None if match.call_status is None else match.call_status.value,
            "strand": match.strand.value,
            "outcome_name": match.outcome_name,
            "candidate_outcomes": list(match.candidate_outcomes),
        },
        "confidence": None
        if assembled.confidence is None
        else _confidence_payload(assembled.confidence),
        "frequencies": [_frequency_payload(f) for f in assembled.frequencies],
        "confidence_frequency": None
        if assembled.confidence_frequency is None
        else _frequency_payload(assembled.confidence_frequency),
        "citations": [_citation_payload(c) for c in assembled.citations],
        "authored_caveats": list(assembled.authored_caveats),
        "computed_caveats": list(assembled.computed_caveats),
    }


CARD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "card_id",
        "section",
        "kind",
        "title",
        "gene",
        "status",
        "summary",
        "detail",
        "impossibility_reason",
        "variant",
        "match",
        "confidence",
        "frequencies",
        "confidence_frequency",
        "citations",
        "authored_caveats",
        "computed_caveats",
    }
)

MANIFEST_KEYS: Final[frozenset[str]] = frozenset(
    {"format_version", "run_id", "created_at", "provenance", "files", "counts"}
)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def knowledge_provenance(pack: KnowledgePack) -> dict[str, Any]:
    """Identify the knowledge pack by content, not by a version somebody maintains.

    There is no ``knowledge/VERSION`` file and there should not be: a hand-written version
    is a second name for the corpus, and M0.4 recorded what happens to two names for one
    thing. A digest over the card files is derived, cannot drift, and answers the question
    a reader of an old bundle actually has -- was this the same pack I have now?
    """
    files = {
        path.relative_to(pack.source_dir).as_posix(): _digest(path)
        for path in sorted(pack.source_dir.rglob("*.yaml"))
    }
    rolled = hashlib.sha256()
    for name, digest in sorted(files.items()):
        rolled.update(name.encode("utf-8"))
        rolled.update(digest.encode("ascii"))
    return {
        "card_schema_version": CARD_SCHEMA_VERSION,
        "card_count": len(pack.cards),
        "digest": rolled.hexdigest(),
        "files": files,
    }


def _reference_provenance(lock_path: Path) -> dict[str, Any]:
    """Every reference release the run could have used, or an explicit statement of none.

    Absence is recorded rather than omitted. "No references were fetched" and "this
    bundle predates reference recording" are different facts about a saved run, and only
    one of them means the results are missing a frequency gate.
    """
    if not lock_path.is_file():
        return {
            "present": False,
            "reason": "no manifest.lock at save time; no references had been fetched",
            "sources": {},
        }
    try:
        lock = refs_lock.read(lock_path)
    except refs_lock.LockError as exc:
        return {
            "present": False,
            "reason": f"manifest.lock could not be read: {exc}",
            "sources": {},
        }
    return {
        "present": True,
        "reason": None,
        "sources": {
            name: {"version": source.version, "license": source.license_id}
            for name, source in sorted(lock.sources.items())
        },
    }


def _tool_provenance(tools_root: Path) -> dict[str, Any]:
    """What the installer recorded, read rather than re-probed.

    Re-running each binary's ``--version`` at save time would report what is installed
    *now*, which is not necessarily what the run used, and would spend seconds of
    subprocess time to say something less true.
    """
    state = refs_tools.read_state(tools_root)
    return {
        tool_id: {
            "version": entry.get("version"),
            "reported_version": entry.get("reported_version"),
            "sha256": entry.get("sha256"),
        }
        for tool_id, entry in sorted(state.tools.items())
    }


# ---------------------------------------------------------------------------
# Reading types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredCard(NoGenotypeRepr):
    """One card as a bundle recorded it. Holds a genotype, so it never prints itself.

    Enum-shaped fields are ``str``, deliberately -- see the module docstring. The nested
    ``match``, ``confidence`` and ``variant`` blocks stay as mappings rather than being
    re-typed into dataclasses that mirror the engine's: a bundle read is a read of what
    another version wrote, and every dataclass this reader insists on is another way for
    an old bundle to fail with a shape error instead of a version error.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("card_id", "section", "status")

    card_id: str
    section: str
    kind: str
    title: str
    status: str
    summary: str
    detail: str
    gene: str | None
    impossibility_reason: str | None
    confidence_tier: str | None
    """Promoted out of the ``confidence`` block because M4.6 puts it on the card face and
    M4.7 sorts by it. A renderer digging three levels down for the one field it always
    needs is a renderer that will cache it wrong."""

    variant: Mapping[str, Any] | None
    match: Mapping[str, Any]
    confidence: Mapping[str, Any] | None
    frequencies: tuple[Mapping[str, Any], ...]
    confidence_frequency: Mapping[str, Any] | None
    citations: tuple[Mapping[str, Any], ...]
    authored_caveats: tuple[str, ...]
    computed_caveats: tuple[str, ...]


@dataclass(frozen=True)
class RunBundle(NoGenotypeRepr):
    """A bundle read back from disk."""

    _repr_fields: ClassVar[tuple[str, ...]] = ("run_id", "format_version", "card_count")

    path: Path
    run_id: str
    format_version: int
    created_at: str
    provenance: Mapping[str, Any]
    qc: Mapping[str, Any]
    cards: tuple[StoredCard, ...]

    @property
    def card_count(self) -> int:
        return len(self.cards)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def new_run_id(now: datetime | None = None) -> str:
    """A sortable, unique, non-identifying run id.

    Timestamp plus random suffix rather than a digest of the input file. A digest would be
    stable across runs, which sounds useful until it is a persistent pseudonymous
    identifier for one person's genome sitting in every directory listing and log line --
    genotype-derived (AGENTS.md 1.1) in the one place a bundle's contents are not.
    """
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def _resolve_root(runs_root: Path | None) -> Path:
    root = (runs_root or runs_dir()).resolve()
    if is_inside_repo(root):
        raise UnsafeDataDirError(
            f"refusing to write a run bundle inside the repository ({root}). A bundle "
            "contains per-card genotype evidence and is raw DNA (AGENTS.md 1.1); .gitignore "
            "covers the paths we declare, not an arbitrary in-repo directory. Write it "
            "under the user data directory, or set GENETICS_DATA_DIR to somewhere outside "
            "the checkout."
        )
    return root


def write_bundle(
    *,
    qc: QCReport,
    cards: Sequence[AssembledCard],
    pack: KnowledgePack,
    runs_root: Path | None = None,
    run_id: str | None = None,
    created_at: datetime | None = None,
    lock_path: Path | None = None,
    tools_root: Path | None = None,
) -> Path:
    """Write one immutable bundle and return its directory.

    The payload is built under ``.incoming-<run_id>`` in the same directory and promoted
    by a single rename, so an interrupted write leaves something visibly unfinished rather
    than a run id with a truncated ``cards.json`` under it. The staging directory is a
    sibling and not a system temp directory for two reasons: a rename across filesystems
    is a copy that can fail halfway, and the system temp directory is not one of the paths
    :mod:`genetics.paths` registers as genotype-bearing.
    """
    root = _resolve_root(runs_root)
    stamp = (created_at or datetime.now(UTC)).astimezone(UTC)
    identifier = run_id or new_run_id(stamp)
    if identifier.startswith(INCOMING_PREFIX) or "/" in identifier or "\\" in identifier:
        raise BundleError(f"invalid run id {identifier!r}")

    destination = root / identifier
    if destination.exists():
        raise BundleError(
            f"run {identifier!r} already exists at {destination}. A bundle is immutable: "
            "overwriting one would change what a saved analysis said after somebody read it."
        )

    staging = root / f"{INCOMING_PREFIX}{identifier}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        _write_text(staging / QC_NAME, _render(qc.to_dict()))
        _write_text(
            staging / CARDS_NAME,
            _render({"cards": [_card_payload(card) for card in cards]}),
        )

        manifest = {
            "format_version": BUNDLE_FORMAT_VERSION,
            "run_id": identifier,
            "created_at": stamp.isoformat().replace("+00:00", "Z"),
            "provenance": {
                "engine_version": ENGINE_VERSION,
                "knowledge": knowledge_provenance(pack),
                "references": _reference_provenance(lock_path or reference_lock()),
                "tools": _tool_provenance(tools_root or tools_dir()),
                "input": {
                    "vendor": qc.vendor,
                    "source_path": qc.source_path,
                    "markers": qc.call_rates.total_markers,
                },
            },
            "counts": {
                "cards": len(cards),
                "with_interpretation": sum(1 for card in cards if card.has_interpretation),
            },
            "files": {name: _digest(staging / name) for name in _PAYLOAD_FILES},
        }
        manifest_text = _render(manifest)

        # The manifest is the file a person pastes into a bug report, so it is the one
        # that must never carry a genotype. cards.json deliberately is not scanned: it
        # holds per-card genotypes by design, and a guard that fails on correct output is
        # a guard someone switches off -- M0.3's lesson, applied to the one boundary here
        # where scanning everything would be the obvious move.
        assert_no_genotype(manifest_text, context="run bundle manifest")
        qc_text = (staging / QC_NAME).read_text(encoding="utf-8")
        assert_no_genotype(qc_text, context="run bundle QC report")
        _write_text(staging / MANIFEST_NAME, manifest_text)

        # Checked again immediately before the rename. Between the check above and here a
        # concurrent writer could have claimed the id; on POSIX a rename onto an empty
        # directory would then succeed silently, where Windows raises. Narrowing the
        # window is all that is available, so the divergence is at least documented.
        if destination.exists():
            raise BundleError(f"run {identifier!r} was created concurrently at {destination}")
        os.rename(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return destination


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _require(raw: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise BundleError(f"{where}: missing required key {key!r}")
    return raw[key]


def _reject_unknown(raw: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unexpected = sorted(set(raw) - allowed)
    if unexpected:
        raise BundleError(
            f"{where}: unexpected key(s) {', '.join(unexpected)}. A bundle written by a "
            "newer engine must declare a higher format_version; silently ignoring a key "
            "here would read part of a record and call it whole."
        )


def _mapping(raw: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise BundleError(f"{where}: expected an object, got {type(raw).__name__}")
    return raw


def _load_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise BundleError(f"{path.name} is missing from {path.parent}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BundleError(f"{path}: not valid JSON -- {exc}") from None
    return _mapping(raw, path.name)


def _stored_card(raw: Any, where: str) -> StoredCard:
    data = _mapping(raw, where)
    _reject_unknown(data, CARD_KEYS, where)
    confidence = data.get("confidence")
    confidence_map = None if confidence is None else _mapping(confidence, f"{where}.confidence")
    tier = confidence_map.get("tier") if confidence_map is not None else None
    variant = data.get("variant")
    frequency_source = data.get("confidence_frequency")
    return StoredCard(
        card_id=str(_require(data, "card_id", where)),
        section=str(_require(data, "section", where)),
        kind=str(_require(data, "kind", where)),
        title=str(_require(data, "title", where)),
        status=str(_require(data, "status", where)),
        summary=str(_require(data, "summary", where)),
        detail=str(_require(data, "detail", where)),
        gene=None if data.get("gene") is None else str(data["gene"]),
        impossibility_reason=None
        if data.get("impossibility_reason") is None
        else str(data["impossibility_reason"]),
        confidence_tier=None if tier is None else str(tier),
        variant=None if variant is None else _mapping(variant, f"{where}.variant"),
        match=_mapping(_require(data, "match", where), f"{where}.match"),
        confidence=confidence_map,
        frequencies=tuple(
            _mapping(item, f"{where}.frequencies[{i}]")
            for i, item in enumerate(data.get("frequencies") or ())
        ),
        confidence_frequency=None
        if frequency_source is None
        else _mapping(frequency_source, f"{where}.confidence_frequency"),
        citations=tuple(
            _mapping(item, f"{where}.citations[{i}]")
            for i, item in enumerate(data.get("citations") or ())
        ),
        authored_caveats=tuple(str(c) for c in data.get("authored_caveats") or ()),
        computed_caveats=tuple(str(c) for c in data.get("computed_caveats") or ()),
    )


def read_bundle(path: Path) -> RunBundle:
    """Read a bundle, checking its format version and its payload digests.

    The version is checked *before* anything else is parsed. A bundle from a future
    format would otherwise fail on whichever field happened to change first, and M4.2
    requires "this was written by a newer version" to be distinguishable from "this file
    is damaged" -- they have completely different remedies.
    """
    directory = Path(path)
    if not directory.is_dir():
        raise BundleError(f"not a run bundle directory: {directory}")

    manifest = _load_json(directory / MANIFEST_NAME)
    declared = _require(manifest, "format_version", MANIFEST_NAME)
    if not isinstance(declared, int) or isinstance(declared, bool):
        raise BundleError(f"{MANIFEST_NAME}: format_version must be an integer")
    if declared != BUNDLE_FORMAT_VERSION:
        raise BundleVersionError(
            f"bundle at {directory} declares format_version {declared}; this engine "
            f"implements {BUNDLE_FORMAT_VERSION}. "
            + (
                "Use the version of the tool that wrote it."
                if declared > BUNDLE_FORMAT_VERSION
                else "The bundle predates this format and cannot be upgraded in place."
            )
        )
    _reject_unknown(manifest, MANIFEST_KEYS, MANIFEST_NAME)

    recorded = _mapping(_require(manifest, "files", MANIFEST_NAME), f"{MANIFEST_NAME}.files")
    missing = sorted(set(_PAYLOAD_FILES) - set(recorded))
    if missing:
        raise BundleError(f"{MANIFEST_NAME}.files: no digest recorded for {', '.join(missing)}")
    for name, expected in sorted(recorded.items()):
        target = directory / name
        if not target.is_file():
            raise BundleIntegrityError(f"{name} is recorded in the manifest but absent from {path}")
        actual = _digest(target)
        if actual != expected:
            raise BundleIntegrityError(
                f"{name} does not match the digest recorded when this run was saved "
                f"(expected {expected}, got {actual}). The bundle has been modified or "
                "truncated since; a run's results are not editable after the fact."
            )

    cards_raw = _load_json(directory / CARDS_NAME)
    entries = _require(cards_raw, "cards", CARDS_NAME)
    if not isinstance(entries, Sequence) or isinstance(entries, str):
        raise BundleError(f"{CARDS_NAME}.cards: expected a list")

    return RunBundle(
        path=directory,
        run_id=str(_require(manifest, "run_id", MANIFEST_NAME)),
        format_version=declared,
        created_at=str(_require(manifest, "created_at", MANIFEST_NAME)),
        provenance=_mapping(
            _require(manifest, "provenance", MANIFEST_NAME), f"{MANIFEST_NAME}.provenance"
        ),
        qc=_load_json(directory / QC_NAME),
        cards=tuple(
            _stored_card(entry, f"{CARDS_NAME}.cards[{i}]") for i, entry in enumerate(entries)
        ),
    )
