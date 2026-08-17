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

**The compatibility contract is additive: a payload key may be added, never removed and
never repurposed.** That single rule is what lets :func:`read_bundle` accept any bundle at
or below this version, which matters more than it looks. Adding a key bumps the version;
M5, M8 and M9 all add payload; and a bundle is immutable, so there is no in-place
migration even in principle. A gate that demanded equality would therefore have orphaned
every run a user had already saved, permanently, at the first bump. Under the additive
rule an old bundle carries everything a newer reader requires, and carries nothing a newer
reader does not recognise -- so nothing has to be relaxed to read it. A key whose meaning
changes gets a *new name* rather than a new interpretation.

Two mechanisms enforce the bump, and it is worth being exact about which does what,
because the first claims less than it looks like it does.

:func:`read_bundle` rejects unknown keys at the top level of the manifest, of the cards
file, and of each card -- not inside ``provenance``, ``match`` or ``confidence``. That is
deliberate: a bundle from a *newer* engine is refused at the version gate before any key is
examined, so recursive strictness would buy almost nothing on read while requiring the
reader to carry a full nested schema -- the brittleness this format is explicitly designed
against (see the module docstring on why reading returns strings rather than enums).

What actually forces the bump is ``test_bundle.py``, which pins the payload's whole nested
key structure. That is the right home for it: the job is to stop *this* project's next
commit from adding a field silently, and that is a developer-facing check, not a
data-facing one.
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

PAYLOAD_FILES: Final[tuple[str, ...]] = (QC_NAME, CARDS_NAME)
"""The files a bundle must record a digest for.

Public because M4.2's listing has to require exactly the same set. When it did not, a
manifest with no ``files`` key at all listed as ``readable`` while ``read_bundle`` refused
it -- the listing/read divergence the store's own docstring sets out to prevent."""


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
        # Recorded separately from `confidence` because `confidence` is None for every card
        # that did not match, and these three are facts about the *observation* rather than
        # about the finding. Without them a saved run cannot say whether an absent result
        # was a marker the array never carried or an imputation that was attempted and
        # failed -- a distinction that does not exist yet and becomes load-bearing at M8.
        # Added now because at format version 1, with no bundle yet saved anywhere, it is
        # free; after M5 it costs a version bump.
        "observation": None
        if assembled.observation is None
        else {
            "call_source": assembled.observation.call_source.value,
            "imputation_quality": assembled.observation.imputation_quality,
            "ancestry_match": assembled.observation.ancestry_match,
        },
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
        "observation",
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
    if pack.cards and not files:
        # `rglob` on a missing directory returns nothing rather than raising, so this would
        # otherwise emit a *well-formed* digest of the empty set beside a truthful
        # card_count -- and two bundles from two different packs would then agree on the
        # one field whose whole job is answering "was this the same pack I have now?".
        # Reachable whenever the pack was loaded from a temp directory or a wheel path that
        # is gone by save time. A digest that can only mean one thing is not a digest.
        raise BundleError(
            f"knowledge pack at {pack.source_dir} holds {len(pack.cards)} card(s) in memory "
            "but no card files on disk, so its provenance digest would describe nothing. "
            "Save the run from a checkout where the pack is still readable."
        )
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
    except (refs_lock.LockError, OSError, UnicodeDecodeError) as exc:
        # Catching LockError alone made the graceful degradation this function is built for
        # conditional on the *kind* of unreadable: a corrupt or binary lock raises
        # UnicodeDecodeError from read_text and an unreadable one raises OSError, neither of
        # which is a LockError. Both would have propagated out of write_bundle and thrown
        # away a completed analysis over a file the run did not depend on.
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
    observation: Mapping[str, Any] | None
    """How the call entered the engine. Present even when ``confidence`` is not, which is
    every card that did not match -- see ``_card_payload`` for why the two are separate."""

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


def check_run_id(identifier: str) -> None:
    """Refuse any run id that is not a plain directory name.

    Public because M4.2's store reads and *deletes* by run id, and a deletion that
    validated its target by a second, similar-looking rule would be the two-names-for-one-
    thing failure this project has now hit three times. One check, one caller-visible name.

    Written as a *structural* check rather than a blacklist of separators, because the
    blacklist it replaces was wrong in a way only Windows shows. ``root / "D:elsewhere"``
    discards ``root`` entirely and yields a path on another drive -- and that string
    contains neither ``/`` nor ``\\``, so the character test waved it through. Nothing
    escaped in practice: the staging directory is built from ``INCOMING_PREFIX +
    identifier``, and the prefix neutralises the drive-relative form, so the write died on
    ``mkdir`` with a confusing OS error instead. But ``destination`` and ``staging`` were
    by then pointing at different places, and ``destination.exists()`` had already been
    asked about a path outside the runs root.

    So the check is on the *outcome*: a run id must be exactly its own basename, which is
    the same thing M2.5's archive extractor concluded about member names after enumerating
    zip-slip forms. ``.`` and ``..`` need naming explicitly -- ``Path("..").name`` is
    ``".."``, so they pass the basename test while denoting a directory that is not one.
    """
    if not identifier or identifier != identifier.strip():
        raise BundleError(f"invalid run id {identifier!r}: must be a non-blank name")
    if identifier.startswith("."):
        # Any leading dot, not just INCOMING_PREFIX. The prefix is dot-led precisely so
        # M4.2 can skip staging directories *by shape*, which means a run legitimately
        # named ".draft" would be written successfully and then be invisible to listing --
        # no error at write time, and a bundle nobody can find. Refusing the whole shape
        # keeps the listing rule and the naming rule from disagreeing.
        raise BundleError(
            f"invalid run id {identifier!r}: a leading '.' marks a directory that listing "
            f"skips ({INCOMING_PREFIX!r} marks a bundle still being written), so a run "
            "named that way would be written and then never found"
        )
    if identifier in {".", ".."} or identifier != Path(identifier).name:
        raise BundleError(
            f"invalid run id {identifier!r}: a run id is a single directory name, not a "
            "path. Separators, drive letters and '..' are refused rather than normalised."
        )


def resolve_runs_root(runs_root: Path | None) -> Path:
    """The runs directory, resolved and proved to be outside the checkout.

    Public for the same reason as :func:`check_run_id`: M4.2 lists, reads and deletes under
    this root, and every one of those must agree with the writer about where it is. A
    second resolver would be a second answer.
    """
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
    than a run id with a truncated ``cards.run.json`` under it. The staging directory is a
    sibling and not a system temp directory for two reasons: a rename across filesystems
    is a copy that can fail halfway, and the system temp directory is not one of the paths
    :mod:`genetics.paths` registers as genotype-bearing.
    """
    root = resolve_runs_root(runs_root)
    stamp = (created_at or datetime.now(UTC)).astimezone(UTC)
    # `run_id or new_run_id(...)` would treat an explicit "" as "not supplied" and quietly
    # generate one, so a caller passing a blank --run-id would get a bundle under a name it
    # did not choose instead of an error. Falsy is not the same as absent.
    identifier = new_run_id(stamp) if run_id is None else run_id
    check_run_id(identifier)

    destination = root / identifier
    if destination.parent != root:
        # Belt and braces behind _check_run_id, and cheap. The failure this catches is a
        # join that lands somewhere other than where the caller was told it would: it is
        # `root` that _resolve_root proved to be outside the checkout, so a destination
        # that is not directly under it inherits none of that.
        raise BundleError(f"run id {identifier!r} does not resolve to a directory under {root}")
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
            "files": {name: _digest(staging / name) for name in PAYLOAD_FILES},
        }
        manifest_text = _render(manifest)

        # The manifest is the file a person pastes into a bug report, so it is the one
        # that must never carry a genotype. cards.run.json deliberately is not scanned: it
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
            "here would read part of a record and call it whole. Note this check is "
            "top-level only -- see BUNDLE_FORMAT_VERSION for which mechanism covers "
            "nested keys, and why it is not this one."
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
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        # Mapping only JSONDecodeError left the two most likely corruption routes escaping
        # as something other than a BundleError: mangled bytes raise UnicodeDecodeError from
        # read_text, an unreadable file raises OSError. The manifest is read *before* any
        # digest check, so this is on the common path, and M4.2's CLI will be catching
        # BundleError -- it would have crashed rather than reported damage.
        raise BundleError(f"{path}: could not be read as JSON -- {exc}") from None
    return _mapping(raw, path.name)


def payload_name(raw: Any, where: str) -> str:
    """A name recorded in ``manifest.files``, checked to be a plain filename.

    ``manifest["files"]`` maps a name to a digest, and the reader turns each into
    ``directory / name``. The writer only ever puts plain filenames there, but the reader is
    reading a file it did not write -- so an edited manifest naming ``../something`` would
    have sent it to stat, and then to *hash*, a file outside the bundle, and report the
    result as this bundle's integrity. Tampering is outside the threat model (see the module
    docstring) and this is not a hole in it; the point is narrower and duller. A manifest
    naming a file somewhere else is a damaged manifest, and saying so is more useful than a
    digest mismatch against a file the user never associated with this run.

    Same conclusion as :func:`check_run_id` and as M2.5's archive extractor, checked the same
    way: on the outcome, not by enumerating the forms a path can take.
    """
    text = str(raw)
    if not text or text in {".", ".."} or text != Path(text).name:
        raise BundleError(
            f"{where}: {text!r} is not a plain filename. A bundle records files that sit "
            "beside its manifest, so a name resolving anywhere else is a damaged manifest."
        )
    return text


def read_manifest(directory: Path) -> Mapping[str, Any]:
    """Load ``manifest.json`` alone, with damage reported as :class:`BundleError`.

    Split out for M4.2's listing, which must describe a whole directory of bundles without
    reading -- or digesting -- any payload. Sharing the loader rather than reimplementing
    it is what keeps "this bundle is damaged" meaning the same thing in a listing as it
    does in a read: the review that widened the caught exception set here would otherwise
    have had to be repeated, and would have been missed.
    """
    return _load_json(directory / MANIFEST_NAME)


def _stored_card(raw: Any, where: str) -> StoredCard:
    data = _mapping(raw, where)
    _reject_unknown(data, CARD_KEYS, where)
    confidence = data.get("confidence")
    confidence_map = None if confidence is None else _mapping(confidence, f"{where}.confidence")
    tier = confidence_map.get("tier") if confidence_map is not None else None
    variant = data.get("variant")
    observation = data.get("observation")
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
        observation=None if observation is None else _mapping(observation, f"{where}.observation"),
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

    manifest = read_manifest(directory)
    declared = _require(manifest, "format_version", MANIFEST_NAME)
    if not isinstance(declared, int) or isinstance(declared, bool):
        raise BundleError(f"{MANIFEST_NAME}: format_version must be an integer")
    if declared < 1:
        raise BundleError(f"{MANIFEST_NAME}: format_version must be 1 or greater, got {declared}")
    if declared > BUNDLE_FORMAT_VERSION:
        raise BundleVersionError(
            f"bundle at {directory} declares format_version {declared}; this engine "
            f"implements {BUNDLE_FORMAT_VERSION}. Use the version of the tool that wrote it."
        )
    # An *older* bundle is read, not refused. Equality here was wrong in a way that only
    # shows up later: adding any payload key bumps the version, M5, M8 and M9 all add
    # payload, and bundles are immutable -- so the first bump would have orphaned every run
    # a user had already saved, permanently, with no migration path even possible. What
    # makes reading an old bundle safe is a contract rather than machinery: **payload keys
    # may be added, never removed and never repurposed.** A v1 bundle therefore carries
    # everything a later reader requires, and can carry nothing a later reader does not
    # know -- which is also why _reject_unknown below stays strict rather than being
    # relaxed for old bundles. A key whose meaning changes gets a new name instead.
    _reject_unknown(manifest, MANIFEST_KEYS, MANIFEST_NAME)

    recorded = _mapping(_require(manifest, "files", MANIFEST_NAME), f"{MANIFEST_NAME}.files")
    missing = sorted(set(PAYLOAD_FILES) - set(recorded))
    if missing:
        raise BundleError(f"{MANIFEST_NAME}.files: no digest recorded for {', '.join(missing)}")
    for name, expected in sorted(recorded.items()):
        target = directory / payload_name(name, f"{MANIFEST_NAME}.files")
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
    _reject_unknown(cards_raw, frozenset({"cards"}), CARDS_NAME)
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
