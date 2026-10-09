"""M9.4 reference distributions and percentile placement within 1000 Genomes groups.

The reference is 1000 Genomes phase 3 (2,504 unrelated samples, 26 populations in five
super-populations): the only panel here with genome-wide genotypes, and the panel the
person was imputed against. Each reference sample is scored over **exactly the rows the
person's phase scored and the panel can resolve**, through the same effect-dose matrix
encoding and PLINK invocation as the person, so the person and the distribution are sums
of one definition. Rows dropped for comparability are counted, never hidden.

The comparison group is chosen by placing the person among 1000 Genomes' own populations
with M5.5's decline rule; the super-population of a named population is the primary group.
A declined, unplaced or saved-only person is compared with the pooled panel and labelled
``ancestry_matched: false``. Portability is derived from this placement by
:mod:`genetics.pgs.portability` (M9.5); rendering is M9.6's.

Reference genotypes are public. The extraction cache holds only the public score's rows
in the public panel; everything restricted to a person's rows is private score output.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import shutil
import uuid
import zlib
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO, NoReturn, cast

from genetics.ancestry.context import PopulationResult, place_among_reference_populations
from genetics.engine.matcher import is_strand_ambiguous
from genetics.external.plink2 import Plink2
from genetics.ingest.schema import GenotypeTable
from genetics.paths import cache_dir, reference_lock, reference_manifest, references_dir
from genetics.pgs.catalog import PgsError, fingerprint
from genetics.pgs.engine import (
    Dose,
    ScoreResult,
    Term,
    _native_sum,
    allele_pair,
    ineligibility_reason,
    orient,
    reference_matrix_sums,
)
from genetics.pgs.scoring import ScoreVariant, ScoringFile
from genetics.qc.report import InferredSex
from genetics.qc.sex_regions import PAR_GRCH37
from genetics.refs import lock as refs_lock
from genetics.refs import manifest as refs_manifest

PANEL_SOURCE = "thousand_genomes_phase3_grch37"
DISTRIBUTION_SCHEMA_VERSION = 1
METHOD_VERSION = 1
EXTRACTION_VERSION = 1
QUANTILES = (1, 5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95, 99)
HISTOGRAM_BINS = 20
Z95 = 1.959963984540054
_VCF = re.compile(r"ALL\.chr([0-9]+|X)\.phase3_.*\.genotypes\.vcf\.gz")
RESOLVED = "reference_resolved"
REFERENCE_STATES = frozenset(
    {
        RESOLVED,
        "not_in_reference",
        "allele_mismatch",
        "ambiguous_panel_records",
        "strand_ambiguous",
        "reference_missing_call",
        "reference_ploidy_conflict",
        "model_ineligible",
    }
)
PHASE_UNAVAILABLE = {"not_recorded", "disabled", "unsupported_model", "no_usable_observations"}
CORRUPT = "Saved reference distribution is malformed or inconsistent; refused."


@dataclass(frozen=True)
class ReferenceSample:
    population: str
    super_population: str
    sex: InferredSex


@dataclass(frozen=True)
class Panel:
    """The fetched, lock-pinned 1000 Genomes files. Public metadata only."""

    version: str
    license_id: str
    vcfs: Mapping[str, tuple[Path, str]]
    """Chromosome to (path, lock sha256), for every chromosome fetched and locked."""
    labels: str
    labels_sha256: str
    samples: Mapping[str, ReferenceSample]

    def provenance(self, chromosomes: Sequence[str]) -> dict[str, Any]:
        return {
            "source": PANEL_SOURCE,
            "version": self.version,
            "license": self.license_id,
            "labels": {"filename": self.labels, "sha256": self.labels_sha256},
            "files": {
                chrom: {"filename": self.vcfs[chrom][0].name, "sha256": self.vcfs[chrom][1]}
                for chrom in chromosomes
            },
            "n_samples": len(self.samples),
        }


def discover_panel(root: Path | None = None) -> Panel | str:
    """Locate the panel and its lock digests, or say why it is not available.

    Absent files or lock entries are ``not_run`` reasons. A labels file that disagrees
    with its digest or cannot be parsed is wrong, and raises.
    """
    root = root if root is not None else references_dir()
    source = refs_manifest.load(reference_manifest()).get(PANEL_SOURCE)
    lock_path = root / reference_lock().name
    try:
        locked = refs_lock.read(lock_path).sources.get(PANEL_SOURCE)
    except (refs_lock.LockError, OSError, UnicodeDecodeError) as exc:
        raise PgsError("The reference lock cannot be read; no reference distribution.") from exc
    fetch = f"`genetics refs fetch --only {PANEL_SOURCE}`"
    labels = [f for f in source.files if f.filename.endswith(".panel")]
    if len(labels) != 1:
        raise PgsError("The 1000 Genomes manifest entry must declare exactly one sample panel.")
    directory = root / PANEL_SOURCE
    labels_path = directory / labels[0].filename
    if locked is None or not labels_path.is_file() or labels[0].filename not in locked.files:
        return f"The 1000 Genomes sample panel is not fetched and locked. {fetch}."
    labels_sha = locked.files[labels[0].filename].sha256
    if fingerprint(labels_path)["sha256"] != labels_sha:
        raise PgsError("The 1000 Genomes sample panel does not match its lock; refetch it.")
    vcfs: dict[str, tuple[Path, str]] = {}
    for item in source.files:
        match = _VCF.fullmatch(item.filename)
        path = directory / item.filename
        if match and path.is_file() and item.filename in locked.files:
            vcfs[match[1]] = (path, locked.files[item.filename].sha256)
    return Panel(
        source.version,
        locked.license_id,
        vcfs,
        labels_path.name,
        labels_sha,
        _read_labels(labels_path),
    )


def _read_labels(path: Path) -> dict[str, ReferenceSample]:
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError) as exc:
        raise PgsError("The 1000 Genomes sample panel cannot be read.") from exc
    header = lines[0].split("\t") if lines else []
    try:
        columns = [header.index(name) for name in ("sample", "pop", "super_pop", "gender")]
    except ValueError as exc:
        raise PgsError("The 1000 Genomes sample panel lacks its labelled columns.") from exc
    samples: dict[str, ReferenceSample] = {}
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) <= max(columns):
            raise PgsError("The 1000 Genomes sample panel has a malformed row.")
        sample, pop, super_pop, gender = (fields[i].strip() for i in columns)
        sex = {"male": InferredSex.MALE, "female": InferredSex.FEMALE}.get(gender)
        if sex is None or not sample or not pop or not super_pop or sample in samples:
            raise PgsError("The 1000 Genomes sample panel has an invalid or repeated sample.")
        samples[sample] = ReferenceSample(pop, super_pop, sex)
    if not samples:
        raise PgsError("The 1000 Genomes sample panel lists no samples.")
    return samples


# ---------------------------------------------------------------------------
# Extraction: one verified streaming pass per chromosome, cached by public identity
# ---------------------------------------------------------------------------


class _HashingReader:
    """A raw reader that hashes every compressed byte gzip consumes."""

    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self._handle.read(size)
        self.digest.update(data)
        return data

    def finish(self) -> str:
        while chunk := self.read(1 << 20):
            del chunk
        return self.digest.hexdigest()


def _ploidy(chrom: str, position: int, sex: InferredSex) -> int:
    if chrom != "X" or any(start <= position <= end for start, end in PAR_GRCH37["X"]):
        return 2
    return 1 if sex is InferredSex.MALE else 2


def _resolve(
    row: ScoreVariant,
    records: Sequence[tuple[bytes, tuple[bytes, ...], list[bytes]]],
    samples: Sequence[str],
    sexes: Mapping[str, InferredSex],
) -> tuple[str, bytes]:
    """One public score row against the panel's records at its locus."""
    pair = allele_pair(row)
    assert pair is not None and row.chrom is not None and row.position is not None
    if not records:
        return "not_in_reference", b""
    candidates = []
    for ref, alts, calls in records:
        alleles = (ref.decode(), *(a.decode() for a in alts))
        status, effect, _ = orient(pair, row.effect_allele, alleles)
        if status != "allele_mismatch":
            candidates.append((status, effect, alleles, calls))
    if not candidates:
        return "allele_mismatch", b""
    if len(candidates) > 1:
        return "ambiguous_panel_records", b""
    status, effect, alleles, calls = candidates[0]
    if status is not None:
        return status, b""
    if is_strand_ambiguous(pair):
        # A palindromic row's orientation is unknowable from a homozygous reference call,
        # so no reference distribution over it can be built without assuming a strand.
        return "strand_ambiguous", b""
    index = str(alleles.index(effect)).encode()
    expected = [_ploidy(row.chrom, row.position, sexes[s]) for s in samples]
    memo: dict[bytes, tuple[int, int] | None] = {}
    doses = bytearray(len(calls))
    for i, (token, ploidy) in enumerate(zip(calls, expected, strict=True)):
        if token in memo:
            parsed = memo[token]
        else:
            parts = re.split(rb"[|/]", token)
            parsed = None if b"." in parts else (len(parts), parts.count(index))
            memo[token] = parsed
        if parsed is None:
            return "reference_missing_call", b""
        if parsed[0] != ploidy:
            return "reference_ploidy_conflict", b""
        doses[i] = parsed[1]
    return RESOLVED, bytes(doses)


def _extract_chromosome(
    path: str,
    expected_sha256: str,
    chrom: str,
    rows: Sequence[ScoreVariant],
    sexes: Mapping[str, InferredSex],
) -> tuple[list[str], dict[int, tuple[str, bytes]]]:
    """Stream one panel VCF, verifying its lock digest in the same pass."""
    wanted: dict[int, list[tuple[bytes, tuple[bytes, ...], list[bytes]]]] = {
        int(r.position): [] for r in rows if r.position is not None
    }
    samples: list[str] | None = None
    try:
        with open(path, "rb") as raw:
            reader = _HashingReader(raw)
            with gzip.GzipFile(fileobj=cast(BinaryIO, reader), mode="rb") as handle:
                for line in handle:
                    if line.startswith(b"##"):
                        continue
                    if line.startswith(b"#"):
                        header = line.rstrip(b"\r\n").split(b"\t")
                        samples = [s.decode() for s in header[9:]]
                        if header[8:9] != [b"FORMAT"] or set(samples) != set(sexes):
                            raise PgsError("A 1000 Genomes VCF lists a different sample set.")
                        if len(samples) != len(sexes):
                            raise PgsError("A 1000 Genomes VCF repeats a sample.")
                        continue
                    if samples is None:
                        raise PgsError("A 1000 Genomes VCF has records before its header.")
                    first = line.index(b"\t")
                    second = line.index(b"\t", first + 1)
                    position = int(line[first + 1 : second])
                    if position not in wanted:
                        continue
                    fields = line.rstrip(b"\r\n").split(b"\t")
                    if fields[0].decode() != chrom or len(fields) != 9 + len(samples):
                        raise PgsError("A 1000 Genomes VCF record is malformed.")
                    if fields[8].split(b":")[0] != b"GT":
                        raise PgsError("A 1000 Genomes VCF record lacks leading GT.")
                    calls = (
                        fields[9:] if fields[8] == b"GT" else [c.split(b":")[0] for c in fields[9:]]
                    )
                    wanted[position].append((fields[3], tuple(fields[4].split(b",")), calls))
            digest = reader.finish()
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        if isinstance(exc, PgsError):
            raise
        raise PgsError("A 1000 Genomes VCF cannot be read; no reference distribution.") from exc
    if digest != expected_sha256:
        raise PgsError("A 1000 Genomes VCF does not match its lock digest; refetch it.")
    if samples is None:
        raise PgsError("A 1000 Genomes VCF has no sample header.")
    resolved = {
        r.row_number: _resolve(r, wanted[int(r.position or 0)], samples, sexes) for r in rows
    }
    return samples, resolved


@dataclass(frozen=True)
class Extraction:
    """Public: one score's rows resolved against the public panel."""

    key: str
    samples: tuple[str, ...]
    states: Mapping[int, str]
    doses: Mapping[int, bytes]
    provenance: Mapping[str, Any]


def _cache_path(key: str) -> Path:
    return cache_dir() / "pgs" / "reference" / f"{key}.pgs-reference.tsv.gz"


def _read_cache(
    path: Path, key: str, rows: Sequence[ScoreVariant], n_samples: int
) -> Extraction | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            states: dict[int, str] = {}
            doses: dict[int, bytes] = {}
            for line in handle:
                number, state, values = line.rstrip("\n").split("\t")
                states[int(number)] = state
                if state == RESOLVED:
                    doses[int(number)] = bytes(int(v) for v in values)
    except (OSError, EOFError, ValueError, zlib.error, UnicodeError):
        return None
    samples = tuple(header.get("samples", ())) if isinstance(header, dict) else ()
    if (
        not isinstance(header, dict)
        or header.get("key") != key
        or len(samples) != n_samples
        or set(states) != {r.row_number for r in rows}
        or any(s not in REFERENCE_STATES for s in states.values())
        or set(doses) != {n for n, s in states.items() if s == RESOLVED}
        or any(len(d) != n_samples or max(d, default=0) > 2 for d in doses.values())
    ):
        return None
    return Extraction(key, samples, states, doses, header["provenance"])


def _write_cache(path: Path, extraction: Extraction) -> None:
    pending = path.with_name(path.name + f".{uuid.uuid4().hex}.part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(pending, "wt", encoding="utf-8", newline="\n") as handle:
            header = {
                "key": extraction.key,
                "samples": list(extraction.samples),
                "provenance": extraction.provenance,
            }
            handle.write(json.dumps(header, sort_keys=True) + "\n")
            for number in sorted(extraction.states):
                values = "".join(map(str, extraction.doses.get(number, b"")))
                handle.write(f"{number}\t{extraction.states[number]}\t{values}\n")
        os.replace(pending, path)
    except OSError as exc:
        raise PgsError("Could not cache the public reference extraction.") from exc
    finally:
        pending.unlink(missing_ok=True)


def _extraction_key(scoring: ScoringFile, provenance: Mapping[str, Any]) -> str:
    """Public identity of one score's extraction from one locked panel."""
    return hashlib.sha256(
        json.dumps(
            {
                "extraction_version": EXTRACTION_VERSION,
                "scoring_sha256": scoring.source["sha256"],
                "scoring_size": scoring.source["size_bytes"],
                "panel": provenance,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def extract(
    scoring: ScoringFile,
    panel: Panel,
    *,
    workers: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> Extraction | str:
    """Resolve every model-eligible score row in the panel (cached), or say what is absent."""
    eligible = [r for r in scoring.iter_variants() if ineligibility_reason(r) is None]
    chromosomes = sorted({str(r.chrom) for r in eligible}, key=lambda c: (c == "X", c.zfill(2)))
    missing = [c for c in chromosomes if c not in panel.vcfs]
    if missing:
        return (
            "1000 Genomes genotypes are not fetched and locked for chromosome(s) "
            f"{', '.join(missing)}. `genetics refs fetch --only {PANEL_SOURCE}`."
        )
    provenance = panel.provenance(chromosomes)
    key = _extraction_key(scoring, provenance)
    path = _cache_path(key)
    cached = _read_cache(path, key, eligible, len(panel.samples)) if path.is_file() else None
    if cached is not None:
        return cached
    sexes = {sample: info.sex for sample, info in panel.samples.items()}
    jobs = [
        (str(panel.vcfs[c][0]), panel.vcfs[c][1], c, [r for r in eligible if r.chrom == c], sexes)
        for c in chromosomes
    ]
    if progress:
        progress(
            f"Reading 1000 Genomes genotypes for {len(eligible)} score rows on "
            f"{len(jobs)} chromosome(s) (verified against the lock; cached afterwards)"
        )
    count = max(1, min(workers or os.cpu_count() or 1, len(jobs)))
    if count == 1:
        results = [_extract_chromosome(*job) for job in jobs]
    else:
        try:
            with ProcessPoolExecutor(max_workers=count) as pool:
                results = list(pool.map(_extract_chromosome, *zip(*jobs, strict=True)))
        except BrokenProcessPool as exc:
            raise PgsError("A 1000 Genomes extraction worker failed; nothing accepted.") from exc
    orders = {tuple(samples) for samples, _ in results}
    if len(orders) != 1:
        raise PgsError("1000 Genomes VCFs disagree on sample order.")
    states: dict[int, str] = {}
    doses: dict[int, bytes] = {}
    for _, resolved in results:
        for number, (state, values) in resolved.items():
            states[number] = state
            if state == RESOLVED:
                doses[number] = values
    extraction = Extraction(key, next(iter(orders)), states, doses, provenance)
    _write_cache(path, extraction)
    return extraction


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------


def _quantile(ordered: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics (Hyndman-Fan type 7)."""
    h = (len(ordered) - 1) * q
    low = math.floor(h)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (h - low) * (ordered[high] - ordered[low])


def group_statistics(values: Sequence[float], person: float) -> dict[str, Any]:
    """Distribution summary and mid-rank percentile, with a Wilson 95% interval.

    The interval reflects only the finite reference group, not imputation, coverage or
    portability: those are reported beside it (portability in :mod:`genetics.pgs.portability`).
    """
    n = len(values)
    if n == 0:
        raise PgsError("An empty reference group cannot place a score.")
    ordered = sorted(values)
    mean = math.fsum(ordered) / n
    sd = math.sqrt(math.fsum((v - mean) ** 2 for v in ordered) / (n - 1)) if n > 1 else None
    below = sum(v < person for v in ordered)
    ties = sum(v == person for v in ordered)
    p = (below + ties / 2) / n
    centre = (p + Z95**2 / (2 * n)) / (1 + Z95**2 / n)
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n**2)) / (1 + Z95**2 / n)
    low, high = ordered[0], ordered[-1]
    if low == high:
        edges, counts = [low, high], [n]
    else:
        width = (high - low) / HISTOGRAM_BINS
        edges = [low + k * width for k in range(HISTOGRAM_BINS)] + [high]
        counts = [0] * HISTOGRAM_BINS
        for value in ordered:
            counts[min(int((value - low) / width), HISTOGRAM_BINS - 1)] += 1
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "min": low,
        "max": high,
        "quantiles": {str(q): _quantile(ordered, q / 100) for q in QUANTILES},
        "histogram": {"edges": edges, "counts": counts, "last_bin_includes_max": True},
        "below": below,
        "ties": ties,
        "percentile": 100 * p,
        "percentile_interval_95": [100 * max(0.0, centre - half), 100 * min(1.0, centre + half)],
    }


def _group_spec(
    placement: Mapping[str, Any], labels: Mapping[str, Sequence[str]]
) -> dict[str, Any]:
    """Which reference groups exist for this person, from the 1000 Genomes placement."""
    status = placement.get("status")
    population = placement.get("population")
    pops = labels["populations"]
    supers = labels["super_populations"]
    if status == "placed":
        if population not in pops:
            raise PgsError("The reference placement names a population outside the panel.")
        regions = {s for p, s in zip(pops, supers, strict=True) if p == population}
        if len(regions) != 1 or regions != {placement.get("region")}:
            raise PgsError("The reference placement's region disagrees with the panel.")
        return {
            "ancestry_matched": True,
            "primary": "super_population",
            "population": population,
            "super_population": next(iter(regions)),
            "reason": None,
        }
    return {
        "ancestry_matched": False,
        "primary": "pooled",
        "population": None,
        "super_population": None,
        "reason": placement.get("reason") or "No reference-population placement.",
    }


def _groups(
    sums: Sequence[float],
    person: float,
    labels: Mapping[str, Sequence[str]],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    groups: dict[str, Any] = {"pooled": {"label": "ALL", **group_statistics(sums, person)}}
    for name, key, value in (
        ("super_population", "super_populations", spec["super_population"]),
        ("population", "populations", spec["population"]),
    ):
        if value is None:
            groups[name] = None
            continue
        members = [s for s, label in zip(sums, labels[key], strict=True) if label == value]
        groups[name] = {"label": value, **group_statistics(members, person)}
    return groups


def _term(raw: Mapping[str, Any]) -> Term:
    return Term(
        raw["row_number"],
        raw["chrom"],
        raw["position"],
        raw["effect_allele"],
        raw["other_allele"],
        raw["weight"],
        raw["fields"],
        tuple(raw["features"]),
        Dose(**raw["before"]),
        Dose(**raw["after"]),
    )


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "percentile": None}


def _phase(
    phase: str,
    record: Mapping[str, Any],
    extraction: Extraction,
    labels: Mapping[str, Sequence[str]],
    spec: Mapping[str, Any],
    *,
    root: Path,
    plink: Plink2,
) -> dict[str, Any]:
    result = record[phase]
    if result["status"] in PHASE_UNAVAILABLE or result["sum"] is None:
        return _unavailable(
            result["status"] if result["status"] in PHASE_UNAVAILABLE else "no_usable_observations"
        )
    terms = [_term(t) for t in record["terms"]]
    observed = [t for t in terms if getattr(t, phase).status == "observed"]
    comparable = [t for t in observed if extraction.states.get(t.row_number) == RESOLVED]
    excluded = Counter(
        extraction.states.get(t.row_number, "model_ineligible")
        for t in observed
        if extraction.states.get(t.row_number) != RESOLVED
    )
    total_weight = math.fsum(abs(t.weight) for t in terms if t.weight is not None)
    scored_weight = math.fsum(abs(float(t.weight)) for t in observed if t.weight is not None)
    comparable_weight = math.fsum(abs(float(t.weight)) for t in comparable if t.weight is not None)
    sources = Counter(str(getattr(t, phase).source) for t in comparable)
    imputed_weight = math.fsum(
        abs(float(t.weight))
        for t in comparable
        if t.weight is not None and getattr(t, phase).source != "direct"
    )
    base: dict[str, Any] = {
        "person_scored_rows": len(observed),
        "comparable_rows": [t.row_number for t in comparable],
        "excluded_for_reference": dict(sorted(excluded.items())),
        "comparable_absolute_weight": comparable_weight,
        "fraction_of_person_scored_weight": comparable_weight / scored_weight
        if scored_weight
        else None,
        "fraction_of_score_weight": comparable_weight / total_weight if total_weight else None,
        "person_dose_basis": {
            "sources": dict(sorted(sources.items())),
            "imputed_absolute_weight_fraction": imputed_weight / comparable_weight
            if comparable_weight
            else None,
            "reference_basis": "sequenced_hard_calls",
        },
    }
    if not comparable:
        return {"status": "no_comparable_rows", "reason": None, "percentile": None, **base}
    person = _native_sum(comparable, phase, root=root, plink=plink)
    numbers = [t.row_number for t in comparable]
    reference = reference_matrix_sums(
        numbers,
        [float(t.weight) for t in comparable if t.weight is not None],
        extraction.samples,
        [extraction.doses[n] for n in numbers],
        root=root,
        plink=plink,
        stem=f"{phase}-reference",
    )
    sums = reference.pop("sums")
    groups = _groups(sums, person["sum"], labels, spec)
    primary = groups[spec["primary"]]
    return {
        "status": "placed",
        "reason": None,
        **base,
        "person_sum": person["sum"],
        "person_verification": {k: v for k, v in person.items() if k != "sum"},
        "reference_sums": sums,
        "reference_verification": reference,
        "groups": groups,
        "primary_group": spec["primary"],
        "percentile": primary["percentile"],
        "percentile_interval_95": primary["percentile_interval_95"],
    }


@dataclass(frozen=True)
class PreparedReference:
    """The verified public panel and the score's public extraction, before any person."""

    panel: Panel
    extraction: Extraction


def prepare_reference(
    scoring: ScoringFile,
    *,
    enabled: bool = True,
    references_root: Path | None = None,
    workers: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> PreparedReference | dict[str, str]:
    """Discover, verify and extract the public panel for one public score.

    Touches no personal data, so the workflows call it before ingest: a tampered or
    unlocked panel fails, or records ``not_run``, before hours of imputation rather than
    after. Returns the ``disabled``/``not_run`` status block when nothing can be prepared.
    """
    if type(enabled) is not bool:
        raise PgsError("Scoring mode flags must be explicit booleans.")
    if not enabled:
        return {"status": "disabled", "reason": "Reference distribution explicitly disabled."}
    panel = discover_panel(references_root)
    if isinstance(panel, str):
        return {"status": "not_run", "reason": panel}
    extraction = extract(scoring, panel, workers=workers, progress=progress)
    if isinstance(extraction, str):
        return {"status": "not_run", "reason": extraction}
    return PreparedReference(panel, extraction)


def attach_reference(
    result: ScoreResult,
    scoring: ScoringFile,
    *,
    table: GenotypeTable | None,
    enabled: bool = True,
    prepared: PreparedReference | Mapping[str, str] | None = None,
    references_root: Path | None = None,
    tools_root: Path | None = None,
    plink: Plink2 | None = None,
    workspace: Path | None = None,
    workers: int | None = None,
    placement: PopulationResult | None = None,
    progress: Callable[[str], None] | None = None,
) -> ScoreResult:
    """Add the reference distribution and primary-group percentiles to a score result.

    Absent references or tools record ``not_run`` with the fix; present-but-wrong ones
    raise. ``enabled=False`` is the explicit, recorded opt-out. ``prepared`` is the
    result of :func:`prepare_reference`, when a workflow ran it before personal input.
    """
    if type(enabled) is not bool:
        raise PgsError("Scoring mode flags must be explicit booleans.")
    record = dict(result.record)
    if record.get("score_definition", {}).get("scoring_source") != dict(scoring.source):
        raise PgsError("The score result was not computed from this scoring file.")
    block: dict[str, Any] = {
        "schema_version": DISTRIBUTION_SCHEMA_VERSION,
        "method_version": METHOD_VERSION,
        "method": (
            "Reference samples scored over the person's comparable rows through the same "
            "PLINK effect-dose matrix; mid-rank percentile; Wilson 95% interval"
        ),
    }
    root = references_root if references_root is not None else references_dir()
    if prepared is None:
        prepared = prepare_reference(
            scoring, enabled=enabled, references_root=root, workers=workers, progress=progress
        )
    if not isinstance(prepared, PreparedReference):
        block.update(status=prepared["status"], reason=prepared["reason"])
    else:
        panel, extraction = prepared.panel, prepared.extraction
        if extraction.key != _extraction_key(scoring, extraction.provenance):
            raise PgsError("The prepared reference was extracted for a different score.")
        native = plink or Plink2.discover(tools_root=tools_root)
        if placement is None:
            if table is None:
                placement = PopulationResult(
                    not_run_reason=(
                        "Saved-run scoring has no original array to place among "
                        "1000 Genomes populations."
                    )
                )
            else:
                placement = place_among_reference_populations(
                    table, references_root=root, tools_root=tools_root, progress=progress
                )
        placed = placement.to_dict()
        labels = {
            "populations": [panel.samples[s].population for s in extraction.samples],
            "super_populations": [panel.samples[s].super_population for s in extraction.samples],
            "sexes": [panel.samples[s].sex.value for s in extraction.samples],
        }
        spec = _group_spec(placed, labels)
        owned = workspace is None
        work = workspace if workspace is not None else cache_dir() / "pgs" / uuid.uuid4().hex
        try:
            work.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PgsError("Could not prepare the private reference workspace.") from exc
        if progress:
            progress("Scoring 1000 Genomes reference samples with pinned PLINK")
        try:
            phases = {
                phase: _phase(phase, record, extraction, labels, spec, root=work, plink=native)
                for phase in ("before", "after")
            }
        finally:
            if owned:
                # The native reports here hold the person's comparable sums.
                try:
                    shutil.rmtree(work)
                except OSError as exc:
                    raise PgsError("Could not remove the private reference workspace.") from exc
        block.update(
            status="computed",
            reason=None,
            panel=extraction.provenance,
            extraction={
                "key": extraction.key,
                "rows_by_state": dict(sorted(Counter(extraction.states.values()).items())),
            },
            placement=placed,
            group=spec,
            samples=list(extraction.samples),
            sample_labels=labels,
            **phases,
        )
    record["reference_distribution"] = block
    record["percentile"] = {
        phase: block.get(phase, {}).get("percentile") if block["status"] == "computed" else None
        for phase in ("before", "after")
    }
    from genetics.pgs.portability import compute_portability

    # The 1000 Genomes placement is a portability input, so the block is rederived here.
    record["portability"] = compute_portability(record)
    return replace(result, record=record)


# ---------------------------------------------------------------------------
# Reload validation
# ---------------------------------------------------------------------------


def _fail() -> NoReturn:
    raise PgsError(CORRUPT)


def validate_distribution(record: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute every group statistic from the saved sums; refuse any disagreement."""
    try:
        return _validate_distribution(record)
    except PgsError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        raise PgsError(CORRUPT) from exc


def _validate_distribution(record: Mapping[str, Any]) -> dict[str, Any]:
    block = record.get("reference_distribution")
    if not isinstance(block, Mapping) or block.get("schema_version") != (
        DISTRIBUTION_SCHEMA_VERSION
    ):
        _fail()
    status = block.get("status")
    percentile = record.get("percentile")
    if status != "computed":
        if status not in {"not_requested", "disabled", "not_run"} or percentile != {
            "before": None,
            "after": None,
        }:
            _fail()
        return dict(block)
    samples, labels = block.get("samples"), block.get("sample_labels")
    if (
        not isinstance(percentile, Mapping)
        or not isinstance(samples, list)
        or not isinstance(labels, Mapping)
        or any(len(labels.get(k, ())) != len(samples) for k in ("populations", "super_populations"))
    ):
        _fail()
    spec = _group_spec(block["placement"], labels)
    if spec != block.get("group"):
        _fail()
    for phase in ("before", "after"):
        data = block.get(phase)
        if not isinstance(data, Mapping) or percentile.get(phase) != data.get("percentile"):
            _fail()
        observed = {t["row_number"] for t in record["terms"] if t[phase]["status"] == "observed"}
        result = record[phase]
        expected_reason = (
            result["status"]
            if result["status"] in PHASE_UNAVAILABLE
            else "no_usable_observations"
            if result["sum"] is None
            else None
        )
        if (data["status"] == "unavailable") != (expected_reason is not None):
            _fail()
        if data["status"] == "unavailable":
            if data.get("reason") != expected_reason or data.get("percentile") is not None:
                _fail()
            continue
        rows = data.get("comparable_rows")
        if not isinstance(rows, list) or not set(rows) <= observed or len(set(rows)) != len(rows):
            _fail()
        if data["status"] == "no_comparable_rows":
            if rows or data.get("percentile") is not None:
                _fail()
            continue
        sums = data.get("reference_sums")
        if (
            data["status"] != "placed"
            or not isinstance(sums, list)
            or len(sums) != len(samples)
            or data["person_verification"].get("terms") != len(rows)
            or data["reference_verification"].get("terms") != len(rows)
        ):
            _fail()
        expected = json.loads(json.dumps(_groups(sums, data["person_sum"], labels, spec)))
        if (
            expected != data.get("groups")
            or data["percentile"] != (expected[spec["primary"]]["percentile"])
        ):
            _fail()
    return dict(block)


def read_placement(path: Path, *, scoring: ScoringFile | None = None) -> dict[str, Any]:
    """Reload a private score result and return its validated reference placement."""
    from genetics.pgs.coverage import read_coverage

    report = read_coverage(path, scoring=scoring)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if report["artifact_schema_version"] < 3:
        return {**_base(report), "reference_distribution": None, "percentile": None}
    return {
        **_base(report),
        "reference_distribution": validate_distribution(raw),
        "percentile": raw["percentile"],
    }


def _base(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pgs_id": report["pgs_id"],
        "artifact_schema_version": report["artifact_schema_version"],
        "scoring_source_verified": report["scoring_source_verified"],
    }


def summary(record: Mapping[str, Any]) -> Iterator[str]:
    """Plain-text placement lines for local terminal output; no marker identities."""
    block = record.get("reference_distribution") or {}
    if block.get("status") != "computed":
        yield f"Reference distribution: {block.get('status')} ({block.get('reason')})."
        return
    group = block["group"]
    for phase, label in (("before", "Original array"), ("after", "After imputation")):
        data = block[phase]
        if data.get("percentile") is None:
            yield f"{label}: no percentile ({data.get('reason') or data['status']})."
            continue
        primary = data["groups"][data["primary_group"]]
        low, high = data["percentile_interval_95"]
        yield (
            f"{label}: percentile {data['percentile']:.1f} (95% {low:.1f}-{high:.1f}) among "
            f"{primary['n']} {primary['label']} reference samples, over "
            f"{len(data['comparable_rows'])}/{data['person_scored_rows']} scored rows"
            + ("" if group["ancestry_matched"] else "; NOT ancestry-matched")
            + "."
        )
