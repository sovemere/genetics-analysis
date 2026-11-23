"""Allele counts from the 1000 Genomes panel, for card loci gnomAD's exomes do not price (M15.5).

The rarity inversion (AGENTS.md 4.1) reads gnomAD r2.1.1 *exomes*, which hold coding
regions. A card on a non-coding variant therefore had no frequency at all, and
:func:`~genetics.engine.confidence.calculate_confidence` caps an unknown frequency at
``moderate``: "rarity could not be checked". The M15.5 calibration review found that this
held 21 of the 64 interpretation cards there, among them the eye-colour, lactase, freckling
and hair cards AGENTS.md 3.1 names as the most reliable in the app, for want of a number
rather than for any doubt about the call.

1000 Genomes phase 3 is already fetched and lock-pinned as the imputation panel, and it is
genome-wide. It cannot measure the rare-call band -- its largest super-population holds 1,322
alleles, and a single copy among them already reads above 0.001% -- so it is used under the
rule gnomAD selection already applies to its small groups (``resolving-populations-v2``): a
population takes part only if it holds **every called allele at least twice**. An allele
priced that way is demonstrably not ultra-rare, so the fallback can raise a common call out
of "unknown" but can never carry a rare one out of ``likely-artifact``, and an allele the
panel cannot show twice stays unknown, exactly as before. Counts are taken from the
genotypes, not the INFO fields, whose per-population frequencies are rounded.

Scope, deliberately narrow: interpretation cards only, autosomes only (a male X is
hemizygous, and the one X card is left on gnomAD alone), and only where gnomAD's exomes
returned nothing. The ClinVar screen and PGx calling stay on gnomAD, since rare variants are
what they screen. Reference genotypes are public, and the cache holds only counts at card
loci, keyed by those public loci and the panel's lock digests.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, BinaryIO, cast

from genetics.engine.evidence import PopulationFrequency
from genetics.paths import cache_dir
from genetics.pgs.catalog import PgsError
from genetics.pgs.reference import Panel, _HashingReader, discover_panel

SOURCE = (
    "1000 Genomes phase 3 allele counts; maximum across super-populations holding each "
    "called allele at least twice"
)
METHOD_VERSION = 1
MINIMUM_COPIES = 2
"""Copies of every called allele a population must hold to take part, as gnomAD's small
groups must (:data:`genetics.health.frequencies.MINIMUM_REPEATED_COUNT`)."""
AUTOSOMES = frozenset(str(n) for n in range(1, 23))
POOLED = "ALL"


class PanelFrequencyError(PgsError):
    """The panel was present but could not be read as locked; nothing was accepted."""


def _count_chromosome(
    path: str, expected_sha256: str, chrom: str, positions: Sequence[int], groups: Mapping[str, str]
) -> dict[int, list[dict[str, Any]]]:
    """Stream one panel VCF, verifying its lock digest, and count alleles at ``positions``."""
    wanted = set(positions)
    found: dict[int, list[dict[str, Any]]] = {}
    columns: list[str] | None = None
    try:
        with open(path, "rb") as raw:
            reader = _HashingReader(raw)
            with gzip.GzipFile(fileobj=cast(BinaryIO, reader), mode="rb") as handle:
                for line in handle:
                    if line.startswith(b"##"):
                        continue
                    if line.startswith(b"#"):
                        header = line.rstrip(b"\r\n").split(b"\t")
                        columns = [s.decode() for s in header[9:]]
                        if header[8:9] != [b"FORMAT"] or set(columns) != set(groups):
                            raise PanelFrequencyError(
                                "A 1000 Genomes VCF lists a different sample set."
                            )
                        continue
                    if columns is None:
                        raise PanelFrequencyError(
                            "A 1000 Genomes VCF has records before its header."
                        )
                    first = line.index(b"\t")
                    second = line.index(b"\t", first + 1)
                    position = int(line[first + 1 : second])
                    if position not in wanted:
                        continue
                    fields = line.rstrip(b"\r\n").split(b"\t")
                    if fields[0].decode() != chrom or len(fields) != 9 + len(columns):
                        raise PanelFrequencyError("A 1000 Genomes VCF record is malformed.")
                    if fields[8].split(b":")[0] != b"GT":
                        raise PanelFrequencyError("A 1000 Genomes VCF record lacks leading GT.")
                    alts = [a.decode() for a in fields[4].split(b",")]
                    counts: dict[str, dict[str, Any]] = {}
                    for sample, call in zip(columns, fields[9:], strict=True):
                        gt = call.split(b":")[0].replace(b"/", b"|").split(b"|")
                        for group in (groups[sample], POOLED):
                            entry = counts.setdefault(group, {"an": 0, "ac": [0] * len(alts)})
                            for allele in gt:
                                if allele == b".":
                                    continue
                                index = int(allele)
                                entry["an"] += 1
                                if index:
                                    entry["ac"][index - 1] += 1
                    found.setdefault(position, []).append(
                        {"ref": fields[3].decode(), "alts": alts, "populations": counts}
                    )
            digest = reader.finish()
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        if isinstance(exc, PgsError):
            raise
        raise PanelFrequencyError("A 1000 Genomes VCF cannot be read; nothing accepted.") from exc
    if digest != expected_sha256:
        raise PanelFrequencyError("A 1000 Genomes VCF does not match its lock digest; refetch it.")
    return found


def _cache_path(key: str) -> Path:
    return cache_dir() / "panel-frequencies" / f"{key}.json"


def lookup(
    loci: Iterable[tuple[str, int]],
    *,
    panel: Panel | str | None = None,
    workers: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Panel allele counts at the autosomal ``loci``, cached; empty when the panel is absent.

    An absent panel is the state CI and a fresh clone are in, and it leaves every card where
    gnomAD alone put it. A present panel that fails its lock digest raises.
    """
    wanted = sorted(
        {(c, int(p)) for c, p in loci if c in AUTOSOMES}, key=lambda x: (int(x[0]), x[1])
    )
    if not wanted:
        return {}
    panel = discover_panel() if panel is None else panel
    if isinstance(panel, str):
        return {}
    chromosomes = sorted({c for c, _ in wanted}, key=int)
    if any(c not in panel.vcfs for c in chromosomes):
        return {}
    provenance = panel.provenance(chromosomes)
    key = hashlib.sha256(
        json.dumps(
            {"method": METHOD_VERSION, "loci": wanted, "panel": provenance}, sort_keys=True
        ).encode()
    ).hexdigest()
    path = _cache_path(key)
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("key") == key:
                return {(c, int(p)): records for c, p, records in saved["loci"]}
        except (OSError, ValueError, KeyError, TypeError):
            pass  # an unreadable cache is rebuilt, never trusted
    groups = {sample: info.super_population for sample, info in panel.samples.items()}
    jobs = [
        (str(panel.vcfs[c][0]), panel.vcfs[c][1], c, [p for cc, p in wanted if cc == c], groups)
        for c in chromosomes
    ]
    if progress:
        progress(
            f"Counting 1000 Genomes alleles at {len(wanted)} card loci on {len(jobs)} "
            "chromosome(s), for the loci gnomAD's exomes do not cover (cached afterwards)"
        )
    count = max(1, min(workers or os.cpu_count() or 1, len(jobs)))
    if count == 1:
        results = [_count_chromosome(*job) for job in jobs]
    else:
        try:
            with ProcessPoolExecutor(max_workers=count) as pool:
                results = list(pool.map(_count_chromosome, *zip(*jobs, strict=True)))
        except BrokenProcessPool as exc:
            raise PanelFrequencyError("A 1000 Genomes counting worker failed.") from exc
    found: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for (_, _, chrom, _, _), result in zip(jobs, results, strict=True):
        for position, records in result.items():
            found[(chrom, position)] = records
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".pending")
    pending.write_text(
        json.dumps(
            {
                "key": key,
                "provenance": provenance,
                "loci": [[c, p, r] for (c, p), r in found.items()],
            }
        ),
        encoding="utf-8",
    )
    pending.replace(path)
    return found


def select_panel_frequencies(
    records: list[dict[str, Any]], *, alleles: set[str], called: set[str]
) -> tuple[PopulationFrequency, ...]:
    """The panel's frequencies for one biallelic SNP, or ``()`` where it cannot show them.

    Mirrors :func:`genetics.health.frequencies.select_frequencies` under its resolving rule:
    one exact biallelic SNP record at the position, a population taking part only when it
    holds every called allele at least :data:`MINIMUM_COPIES` times, and the population
    chosen that maximises the rarest called allele.
    """
    if len(records) != 1 or len(alleles) != 2 or not called or not called <= alleles:
        return ()
    record = records[0]
    if {record["ref"], *record["alts"]} != alleles or len(record["alts"]) != 1:
        return ()
    if any(a not in "ACGT" or len(a) != 1 for a in alleles):
        return ()
    alt = record["alts"][0]
    options: list[tuple[float, str, dict[str, float]]] = []
    for population, counts in record["populations"].items():
        an, ac = counts["an"], counts["ac"][0]
        if not an:
            continue
        copies = {alt: ac, record["ref"]: an - ac}
        if any(copies[a] < MINIMUM_COPIES for a in called):
            continue
        values = {a: copies[a] / an for a in copies}
        options.append((min(values[a] for a in called), population, values))
    if not options:
        return ()
    _, population, values = max(options, key=lambda item: (item[0], item[1] == POOLED, item[1]))
    label = f"1000 Genomes {population}"
    return tuple(PopulationFrequency(a, values[a], label, SOURCE) for a in sorted(values))
