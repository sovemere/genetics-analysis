"""Saved parts of an unfinished ``genetics run``, so an interrupted run resumes.

An imputed run of the default pack is estimated at 3-4 hours. Until this module an
interruption after imputation kept only Beagle's per-job checkpoints and lost the rest. A
resumable run saves each long part as it finishes, and a rerun of the same export by the
same engine source, knowledge pack, reference lock, tools and options reuses them:

1. **Imputation.** The completed result, reopened by its dosage files' digests rather than
   re-derived. Without this part, the imputation stage's own per-job resume still applies.
2. **The dose read.** One pass over the imputed stream, holding every record at a locus a
   card input, a polygenic score or a PGx call reads, and the digest of the whole stream.
3. **Each polygenic score**, saved as it finishes.
4. **PGx and HLA calls.**

ClinVar, runs of homozygosity, archaic and the other array cards take minutes and are
recomputed. The bundle write is the last part and is not split: it is promoted by a single
rename, and the saved parts are removed only after it.

Everything here is private genotype-derived data under
:func:`~genetics.paths.run_parts_dir`, never in the checkout. Each part is written whole,
renamed into place and its digest recorded. One that is missing, damaged or does not decode
is recomputed, with a progress line saying so; a part that cannot be saved costs only the
resume. Reusing a part skips none of the checks the bundle writer makes when it saves.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import os
import shutil
import uuid
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, ClassVar

import genetics
from genetics.engine.cards import KnowledgePack
from genetics.imputation import ImputationResult
from genetics.imputation.dosages import DosageRecord, parse_record
from genetics.ingest.schema import GenotypeTable
from genetics.paths import is_inside_repo, reference_lock, run_parts_dir, tools_dir
from genetics.pgs.engine import DosageIndex
from genetics.pgs.records import is_score_file_name, score_file_name
from genetics.privacy import NoGenotypeRepr
from genetics.run.bundle import _tool_provenance, knowledge_provenance

__all__ = [
    "SCHEMA_VERSION",
    "RunParts",
    "RunPartsError",
    "contract",
    "engine_sha256",
]

SCHEMA_VERSION = 1
CONTRACT_NAME = "contract.run.json"
JOURNAL_NAME = "parts.run.json"
IMPUTATION_NAME = "imputation.run.json"
DOSES_NAME = "doses.dosages.jsonl.gz"
CALLS_NAME = "calls.run.json"
PENDING_PREFIX = "pending-"
_DOSES_HEADER = frozenset({"schema_version", "stream_sha256", "records", "loci"})


class RunPartsError(ValueError):
    """The saved parts cannot be kept safely, so the run does not start."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def engine_sha256() -> str:
    """The engine's source, by content. ``__version__`` has said 0.1.0 from the start, so
    a part saved by other code would otherwise be reused as if this code had made it."""
    root = Path(genetics.__file__).resolve().parent
    rolled = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        rolled.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        rolled.update(hashlib.sha256(path.read_bytes()).digest())
    return rolled.hexdigest()


def contract(
    input_path: Path,
    *,
    pack: KnowledgePack,
    no_impute: bool,
    options: Mapping[str, Any],
) -> dict[str, Any]:
    """What every saved part depends on: digests, versions and options, no genotype.

    ``options`` holds the run's remaining choices, such as the HLA classifier request.
    """
    lock = reference_lock()
    return {
        "schema_version": SCHEMA_VERSION,
        "input_sha256": _file_sha256(input_path),
        "engine": {"version": genetics.__version__, "sources_sha256": engine_sha256()},
        "knowledge_sha256": knowledge_provenance(pack)["digest"],
        "references_lock_sha256": _file_sha256(lock) if lock.is_file() else None,
        "tools": _tool_provenance(tools_dir()),
        "no_impute": no_impute,
        "options": dict(options),
    }


@dataclass(frozen=True, repr=False)
class RunParts(NoGenotypeRepr):
    """The saved parts of one run, keyed by the digest of its :func:`contract`."""

    _repr_fields: ClassVar[tuple[str, ...]] = ("key",)
    directory: Path
    key: str
    progress: Callable[[str], None] | None = None

    @classmethod
    def open(
        cls,
        terms: Mapping[str, Any],
        *,
        root: Path | None = None,
        restart: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> RunParts:
        """The parts saved under ``terms``, after discarding them when ``restart``."""
        text = _canonical(dict(terms))
        key = hashlib.sha256(text).hexdigest()
        base = (root if root is not None else run_parts_dir()).resolve()
        directory = base / key
        if is_inside_repo(directory):
            raise RunPartsError(
                "Saved run parts are genotype data and must live outside the checkout "
                "(AGENTS.md 1.5)."
            )
        if base.is_symlink() or directory.is_symlink():
            raise RunPartsError("A saved run parts directory cannot be a symbolic link.")
        parts = cls(directory, key, progress)
        if restart and directory.exists():
            shutil.rmtree(directory)
            parts._emit("Discarded the saved parts of an earlier run of this export")
        directory.mkdir(parents=True, exist_ok=True)
        try:
            same = json.loads((directory / CONTRACT_NAME).read_bytes()) == json.loads(text)
        except FileNotFoundError:
            same = None
        except (OSError, ValueError):
            same = False
        if same is False:
            # The key is the digest of these terms, so a disagreeing file is a damaged one,
            # and nothing it was saved beside can be told apart from damage either.
            parts._emit("The saved run parts' contract is damaged; discarding them")
            shutil.rmtree(directory)
            directory.mkdir(parents=True)
        if not same:
            parts._replace(CONTRACT_NAME, text)
        held = parts.describe()
        parts._emit(
            f"Resuming an interrupted run of this export from its saved parts: {held}"
            if held
            else f"Saving this run's parts as they finish, so an interruption can resume: "
            f"{directory}"
        )
        return parts

    def _emit(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    # -- files --------------------------------------------------------------------------

    def _replace(self, name: str, data: bytes) -> None:
        """Write ``data`` whole under a pending name, then rename it over ``name``."""
        pending = self.directory / f"{PENDING_PREFIX}{uuid.uuid4().hex}-{name}"
        try:
            with pending.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            pending.replace(self.directory / name)
        finally:
            pending.unlink(missing_ok=True)

    def _journal(self) -> dict[str, str]:
        try:
            raw = json.loads((self.directory / JOURNAL_NAME).read_bytes())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            raw = None
        if (
            not isinstance(raw, dict)
            or set(raw) != {"schema_version", "parts"}
            or raw["schema_version"] != SCHEMA_VERSION
            or not isinstance(raw["parts"], dict)
            or not all(isinstance(v, str) for v in raw["parts"].values())
        ):
            self._emit("The saved run parts' journal is damaged; recomputing every part")
            with contextlib.suppress(OSError):
                self._replace(JOURNAL_NAME, self._journal_text({}))
            return {}
        return dict(raw["parts"])

    @staticmethod
    def _journal_text(parts: Mapping[str, str]) -> bytes:
        return _canonical({"schema_version": SCHEMA_VERSION, "parts": dict(parts)})

    def _record(self, name: str, digest: str | None) -> None:
        journal = self._journal()
        if digest is None:
            journal.pop(name, None)
        else:
            journal[name] = digest
        self._replace(JOURNAL_NAME, self._journal_text(journal))

    def _publish(self, name: str, write: Callable[[IO[bytes]], object], what: str) -> None:
        """Save one part. Failing to save costs the resume, never the run."""
        pending = self.directory / f"{PENDING_PREFIX}{uuid.uuid4().hex}-{name}"
        try:
            try:
                with pending.open("wb") as handle:
                    write(handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                digest = _file_sha256(pending)
                pending.replace(self.directory / name)
            finally:
                pending.unlink(missing_ok=True)
            self._record(name, digest)
        except OSError as exc:
            self._emit(
                f"Could not save the {what} part ({exc.strerror or type(exc).__name__}); "
                "an interruption from here recomputes it"
            )

    def _load(self, name: str, what: str) -> bytes | None:
        expected = self._journal().get(name)
        if expected is None:
            return None
        path = self.directory / name
        try:
            data = None if path.is_symlink() else path.read_bytes()
        except OSError:
            data = None
        if data is None or hashlib.sha256(data).hexdigest() != expected:
            self._drop(name, f"The saved {what} part is missing or damaged; recomputing it")
            return None
        return data

    def _drop(self, name: str, message: str | None) -> None:
        if message is not None:
            self._emit(message)
        try:
            self._record(name, None)
            (self.directory / name).unlink(missing_ok=True)
        except OSError:
            pass

    def describe(self) -> str:
        """The saved parts in words, or empty."""
        journal = self._journal()
        held = [
            label
            for name, label in (
                (IMPUTATION_NAME, "imputation"),
                (DOSES_NAME, "the dose read"),
            )
            if name in journal
        ]
        scores = sum(1 for name in journal if is_score_file_name(name))
        if scores:
            held.append(f"{scores} polygenic score(s)")
        if CALLS_NAME in journal:
            held.append("PGx and HLA calls")
        return ", ".join(held)

    def discard(self) -> None:
        """Remove every saved part, once the run's bundle holds the result."""
        try:
            shutil.rmtree(self.directory)
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._emit(
                f"Could not remove this run's saved parts ({exc.strerror or type(exc).__name__});"
                f" they are private: delete {self.directory}"
            )
            return
        with contextlib.suppress(OSError):  # Another run's parts may still be there.
            self.directory.parent.rmdir()
        self._emit("Removed this run's saved parts; the saved bundle holds the result")

    # -- 1. imputation ------------------------------------------------------------------

    def save_imputation(self, result: ImputationResult) -> None:
        """Save a freshly run imputation, dropping every part read from an earlier one.

        The dose read, scores and calls were read from the imputation saved before this
        one, if any; nothing proves a rerun wrote the same doses, so none is reused.
        """
        journal = self._journal()
        stale = [n for n in journal if n in {DOSES_NAME, CALLS_NAME} or is_score_file_name(n)]
        if stale:
            self._emit("Imputation ran again, so the parts read from its doses are recomputed")
            for name in stale:
                self._drop(name, None)
        payload = {
            "directory": str(result.directory.resolve()),
            "files": [str(path.resolve()) for path in result.dosage_files],
            "metadata": result.metadata,
        }
        text = _canonical(payload)
        self._publish(IMPUTATION_NAME, lambda handle: handle.write(text), "imputation")

    def imputation(self, table: GenotypeTable) -> ImputationResult | None:
        """The completed imputation of ``table``, if its dosage files still match."""
        data = self._load(IMPUTATION_NAME, "imputation")
        if data is None:
            return None
        try:
            raw = json.loads(data)
            metadata = raw["metadata"]
            paths = tuple(Path(p) for p in raw["files"])
            expected = {entry["name"]: entry["sha256"] for entry in metadata["files"]}
            target = hashlib.sha256(table.frame.write_csv().encode()).hexdigest()
            if (
                metadata["contract"]["target_sha256"] != target
                or len(paths) != len(expected)
                or any(
                    path.name not in expected
                    or path.is_symlink()
                    or _file_sha256(path) != expected[path.name]
                    for path in paths
                )
            ):
                raise ValueError
            result = ImputationResult(table, Path(raw["directory"]), paths, metadata, True)
        except (OSError, ValueError, KeyError, TypeError):
            self._drop(
                IMPUTATION_NAME,
                "The saved imputation no longer matches its dosage files; running the "
                "imputation stage, which reuses its own completed jobs",
            )
            return None
        self._emit("Reusing this run's completed imputation; its dosage files match their digests")
        return result

    # -- 2. the dose read ---------------------------------------------------------------

    def save_doses(self, index: DosageIndex) -> None:
        def write(handle: IO[bytes]) -> None:
            header = {
                "schema_version": SCHEMA_VERSION,
                "stream_sha256": index.stream_sha256,
                "records": sum(len(found) for found in index.records.values()),
                "loci": index.loci_held,
            }
            with gzip.GzipFile(filename="", fileobj=handle, mode="wb", mtime=0) as stream:
                stream.write(_canonical(header) + b"\n")
                for record in index.iter_records():
                    stream.write(_canonical(record.to_dict()) + b"\n")

        self._publish(DOSES_NAME, write, "dose read")

    def doses(self) -> DosageIndex | None:
        data = self._load(DOSES_NAME, "dose read")
        if data is None:
            return None
        records: dict[tuple[str, int], list[DosageRecord]] = {}
        count = 0
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                header = json.loads(stream.readline())
                if not isinstance(header, dict) or set(header) != _DOSES_HEADER:
                    raise ValueError
                for line in stream:
                    record = parse_record(json.loads(line))
                    records.setdefault((record.chrom, record.pos_grch37), []).append(record)
                    count += 1
            if (
                header["schema_version"] != SCHEMA_VERSION
                or not isinstance(header["stream_sha256"], str)
                or header["records"] != count
                or header["loci"] != len(records)
            ):
                raise ValueError
        except (OSError, EOFError, ValueError, TypeError, zlib.error):
            self._drop(DOSES_NAME, "The saved dose read does not decode; reading the doses again")
            return None
        self._emit(
            f"Reusing this run's saved read of its imputed doses: {count:,} records at "
            f"{len(records):,} loci"
        )
        return DosageIndex(
            {locus: tuple(found) for locus, found in records.items()}, header["stream_sha256"]
        )

    # -- 3. polygenic scores ------------------------------------------------------------

    def score(self, card_id: str) -> bytes | None:
        """One card's compressed score record (:class:`~genetics.pgs.records.ScoreRecords`)."""
        return self._load(score_file_name(card_id), f"{card_id} score")

    def save_score(self, card_id: str, compressed: bytes) -> None:
        self._publish(
            score_file_name(card_id), lambda handle: handle.write(compressed), f"{card_id} score"
        )

    # -- 4. PGx and HLA -----------------------------------------------------------------

    def calls(self) -> tuple[dict[str, Any], dict[str, Any]] | None:
        data = self._load(CALLS_NAME, "PGx and HLA")
        if data is None:
            return None
        try:
            raw = json.loads(data)
            if (
                not isinstance(raw, dict)
                or set(raw) != {"pgx", "hla"}
                or not isinstance(raw["pgx"], dict)
                or not isinstance(raw["hla"], dict)
            ):
                raise ValueError
        except ValueError:
            self._drop(CALLS_NAME, "The saved PGx and HLA calls do not decode; calling again")
            return None
        self._emit("Reusing this run's saved PGx and HLA calls")
        return raw["pgx"], raw["hla"]

    def save_calls(self, pgx: Mapping[str, Any], hla: Mapping[str, Any]) -> None:
        payload = _canonical({"pgx": pgx, "hla": hla})
        self._publish(CALLS_NAME, lambda handle: handle.write(payload), "PGx and HLA")
