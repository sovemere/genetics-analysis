"""Public gnomAD frequency index and conservative, allele-specific calibration.

The index is built from the entire sites reference. Sample coordinates are queried
in memory; no sample-selected cache is written into the reference tree. Missing,
filtered, incompatible and conflicting records never imply an allele frequency of zero.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genetics.engine.confidence import RARE_CALL_EMPIRICAL_PPV, RARE_CALL_FREQUENCY_CEILING
from genetics.engine.evidence import PopulationFrequency
from genetics.health.clinvar import ClinVarError, ClinVarLookup, _hashes
from genetics.ingest.schema import Chrom
from genetics.paths import references_dir

SOURCE = "gnomad_exomes_r2_1_1_grch37"
INDEX_VERSION = 2
# Saved snapshots describe their own index generation, independently of today's cache.
SUPPORTED_SNAPSHOT_INDEX_VERSIONS = (1, 2)
CHECKPOINT_ROWS = 100_000
POPULATIONS = (
    "global",
    "afr",
    "amr",
    "asj",
    "eas",
    "fin",
    "nfe",
    "oth",
    "sas",
    "eas_jpn",
    "eas_kor",
    "eas_oea",
    "nfe_bgr",
    "nfe_est",
    "nfe_nwe",
    "nfe_onf",
    "nfe_seu",
    "nfe_swe",
)
RELIABILITY_STATES = ("likely-artifact", "frequency_screen_passed", "unknown", "not_applicable")
_FREQUENCY_FIELDS = {
    name + ("_" + population if population != "global" else "")
    for population in POPULATIONS
    for name in ("AF", "AC", "AN", "nhomalt")
} | {"AF_popmax", "popmax"}
POLICY = (
    "Use the highest frequency of the observed allele across represented gnomAD "
    "ancestry groups and reported subgroups (including global), retaining that "
    "population's counts. This is a "
    "conservative rarity screen, not inferred personal ancestry. Missing or filtered "
    "reference entries are unknown, never zero. Exomes do not cover every array locus."
)
NOTICE = (
    "Reference lookup only. ClinVar classifications describe reference variants, not "
    "confirmed personal findings. Allele-frequency measurement reliability is screened "
    "separately from clinical significance; no clinical-risk interpretation is applied. "
    "Only clinical sequencing can establish or exclude a rare variant. This pipeline "
    "is not a clinical test."
)


class FrequencyError(ClinVarError):
    """Invalid public reference or saved frequency calibration; never quotes sample calls."""


@contextmanager
def _building_database(path: Path) -> Iterator[sqlite3.Connection]:
    try:
        with closing(sqlite3.connect(path)) as db:
            yield db
    except sqlite3.Error as exc:
        raise FrequencyError("gnomAD index/checkpoint database is malformed or unreadable") from exc


def _values(text: str | None, count: int, *, integer: bool = False) -> list[Any]:
    if text is None or text == ".":
        return [None] * count
    fields = text.split(",")
    if len(fields) != count:
        raise FrequencyError("gnomAD INFO cardinality does not match its VCF header")
    result: list[Any] = []
    for field in fields:
        if field == ".":
            result.append(None)
            continue
        try:
            value = int(field) if integer else float(field)
        except ValueError:
            raise FrequencyError("gnomAD frequency or count is not numeric") from None
        if not math.isfinite(value) or value < 0 or (not integer and value > 1):
            raise FrequencyError("gnomAD frequency or count is outside its valid range")
        result.append(value)
    return result


def parse_record(line: str) -> dict[str, Any]:
    """Keep REF/ALT, FILTER and global/population counts; respect Number=A versus 1."""
    fields = line.rstrip("\r\n").split("\t")
    if len(fields) != 8:
        raise FrequencyError("gnomAD sites VCF must have eight columns")
    chrom, position, _, ref, alt, _, filters, text = fields
    try:
        pos = int(position)
        Chrom(chrom)
    except ValueError:
        raise FrequencyError("gnomAD sites VCF has an invalid primary coordinate") from None
    alts = alt.split(",")
    if (
        pos <= 0
        or pos > 2**32 - 1
        or chrom == "PAR"
        or not re.fullmatch("[ACGTN]+", ref)
        or any(not re.fullmatch(r"[ACGTN]+|\*", a) for a in alts)
        or len(set(alts)) != len(alts)
        or ref in alts
    ):
        raise FrequencyError("gnomAD sites VCF has malformed alleles or coordinates")
    # Avoid parsing thousands of unrelated annotations per source row.
    info: dict[str, str] = {}
    for field in text.split(";"):
        name, sep, value = field.partition("=")
        if name in _FREQUENCY_FIELDS:
            if not sep or name in info:
                raise FrequencyError("gnomAD contains duplicate or malformed frequency INFO")
            info[name] = value
    populations: dict[str, Any] = {}
    for population in POPULATIONS:
        suffix = "" if population == "global" else "_" + population
        if not any(k + suffix in info for k in ("AF", "AC", "AN", "nhomalt")):
            continue
        af = _values(info.get("AF" + suffix), len(alts))
        ac = _values(info.get("AC" + suffix), len(alts), integer=True)
        an = _values(info.get("AN" + suffix), 1, integer=True)[0]
        hom = _values(info.get("nhomalt" + suffix), len(alts), integer=True)
        if an is not None:
            if any(c is not None and c > an for c in ac):
                raise FrequencyError("gnomAD allele count exceeds allele number")
            if all(c is not None for c in ac) and sum(ac) > an:
                raise FrequencyError("gnomAD alternate counts exceed allele number")
        for f, c, h in zip(af, ac, hom, strict=True):
            # AF is rounded in the publisher's VCF; AC/AN is authoritative at a boundary.
            if (
                an
                and f is not None
                and c is not None
                and not math.isclose(f, c / an, rel_tol=0.001, abs_tol=1e-7)
            ):
                raise FrequencyError("gnomAD allele frequency disagrees with its counts")
            if c is not None and h is not None and 2 * h > c:
                raise FrequencyError("gnomAD homozygote count exceeds alternate allele count")
        populations[population] = {"af": af, "ac": ac, "an": an, "nhomalt": hom}
    labels = info.get("popmax", ".").split(",")
    if labels != ["."] and len(labels) != len(alts):
        raise FrequencyError("gnomAD popmax cardinality does not match ALT")
    return {
        "chrom": chrom,
        "pos_grch37": pos,
        "ref": ref,
        "alts": alts,
        "filter": filters,
        "populations": populations,
        "af_popmax": _values(info.get("AF_popmax"), len(alts)),
        "popmax": [None] * len(alts) if labels == ["."] else labels,
    }


def _records(path: Path, *, skip: int = 0) -> Iterable[dict[str, Any]]:
    header = build = False
    seen = 0
    declarations: dict[str, tuple[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("##contig=<ID=1,"):
                build = "length=249250621," in line and "assembly=gnomAD_GRCh37>" in line
            elif line.startswith("##INFO="):
                match = re.match(r"##INFO=<ID=([^,]+),Number=([^,]+),Type=([^,]+),", line)
                if match:
                    declarations[match[1]] = (match[2], match[3])
            elif line.startswith("#CHROM"):
                if line.strip() != "\t".join(
                    ("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")
                ):
                    raise FrequencyError("gnomAD has an invalid sites VCF column header")
                for population in POPULATIONS:
                    suffix = "" if population == "global" else "_" + population
                    for name, number, kind in (
                        ("AF", "A", "Float"),
                        ("AC", "A", "Integer"),
                        ("AN", "1", "Integer"),
                        ("nhomalt", "A", "Integer"),
                    ):
                        key = name + suffix
                        if (key in declarations or population == "global") and declarations.get(
                            key
                        ) != (number, kind):
                            raise FrequencyError("gnomAD frequency INFO header is incompatible")
                header = True
            elif line.startswith("#"):
                continue
            else:
                if not header or not build:
                    raise FrequencyError("gnomAD requires a verified GRCh37 sites VCF header")
                seen += 1
                if seen > skip:
                    yield parse_record(line)
    if not header or not build:
        raise FrequencyError("gnomAD sites VCF is missing its GRCh37 header")
    if seen == 0 or seen < skip:
        raise FrequencyError("gnomAD sites VCF is empty or shorter than its checkpoint")


@dataclass(frozen=True)
class FrequencyIndex:
    path: Path
    provenance: Mapping[str, Any]

    @classmethod
    def open(
        cls, path: Path, *, expected: Mapping[str, Any], sidecar: Path | None = None
    ) -> FrequencyIndex:
        try:
            provenance_path = sidecar or path.with_name(path.name + ".provenance.json")
            saved = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance = saved["provenance"]
            if any(provenance.get(k) != v for k, v in expected.items()):
                raise ValueError
            if _hashes(path)[0] != saved["index_sha256"]:
                raise ValueError
            if type(provenance["records"]) is not int or provenance["records"] <= 0:
                raise ValueError
            return cls(path, provenance)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise FrequencyError(
                "gnomAD index or provenance is invalid; rebuild references"
            ) from exc

    @classmethod
    def build(
        cls,
        vcf: Path,
        *,
        output: Path,
        version: str,
        input_sha256: str,
        progress: Callable[[str], None] | None = None,
    ) -> FrequencyIndex:
        """Restartable public-reference transform; checkpoints commit every 100k rows.

        The caller verifies the publisher checksum before passing input_sha256. A
        restart replays gzip decompression, skipping already committed records.
        """
        contract = {
            "source": SOURCE,
            "version": version,
            "build": "GRCh37",
            "filename": vcf.name,
            "sha256": input_sha256,
            "index_schema_version": INDEX_VERSION,
        }
        if output.is_file():
            sidecar = output.with_name(output.name + ".provenance.json")
            pending = sidecar.with_name(sidecar.name + ".tmp")
            if pending.is_file():
                try:
                    recovered = cls.open(output, expected=contract, sidecar=pending)
                except FrequencyError:
                    if not sidecar.is_file():
                        raise
                else:
                    os.replace(pending, sidecar)
                    return recovered
            try:
                return cls.open(output, expected=contract)
            except FrequencyError:
                # A verified older transform is obsolete, rather than damaged. Rebuild
                # it atomically from the caller-verified source, preserving the old file
                # until completion. Same-contract corruption remains a loud refusal.
                try:
                    saved = json.loads(sidecar.read_text(encoding="utf-8"))["provenance"]
                    generation = saved["index_schema_version"]
                    obsolete = (
                        type(generation) is int
                        and generation in SUPPORTED_SNAPSHOT_INDEX_VERSIONS
                        and generation < INDEX_VERSION
                        and all(
                            saved.get(k) == v
                            for k, v in contract.items()
                            if k != "index_schema_version"
                        )
                    )
                    if not obsolete:
                        raise ValueError
                    cls.open(output, expected=saved)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise FrequencyError(
                        "gnomAD index/provenance is damaged or incompatible; remove only "
                        "the derived index and sidecar, then rerun refs fetch"
                    ) from exc
                if progress:
                    progress("Rebuilding gnomAD index for the expanded ancestry-group transform")
        stage = output.with_name(output.name + ".building")
        output.parent.mkdir(parents=True, exist_ok=True)
        with _building_database(stage) as db:
            db.execute("CREATE TABLE IF NOT EXISTS variants (chrom TEXT, pos INTEGER, record TEXT)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS checkpoint "
                "(contract TEXT, rows INTEGER, records_sha256 TEXT)"
            )
            checkpoint = db.execute(
                "SELECT contract, rows, records_sha256 FROM checkpoint"
            ).fetchone()
            canonical = json.dumps(contract, sort_keys=True)
            completed = 0
            records_digest = hashlib.sha256()
            if checkpoint:
                if (
                    checkpoint[0] != canonical
                    or db.execute("SELECT COUNT(*) FROM variants").fetchone()[0] != checkpoint[1]
                ):
                    raise FrequencyError("gnomAD index checkpoint does not match this source")
                completed = checkpoint[1]
                for (text,) in db.execute("SELECT record FROM variants ORDER BY rowid"):
                    records_digest.update((text + "\n").encode("utf-8"))
                if records_digest.hexdigest() != checkpoint[2]:
                    raise FrequencyError("gnomAD checkpoint record checksum mismatch")
            else:
                db.execute(
                    "INSERT INTO checkpoint VALUES (?, 0, ?)",
                    (canonical, records_digest.hexdigest()),
                )
                db.commit()
            if progress:
                progress(f"Building gnomAD frequency index; {completed:,} records checkpointed")
            rows = completed
            batch: list[tuple[str, int, str]] = []
            for rows, record in enumerate(_records(vcf, skip=completed), completed + 1):
                text = json.dumps(record, separators=(",", ":"))
                records_digest.update((text + "\n").encode("utf-8"))
                batch.append(
                    (
                        record["chrom"],
                        record["pos_grch37"],
                        text,
                    )
                )
                if len(batch) == CHECKPOINT_ROWS:
                    db.executemany("INSERT INTO variants VALUES (?, ?, ?)", batch)
                    db.execute(
                        "UPDATE checkpoint SET rows=?, records_sha256=?",
                        (rows, records_digest.hexdigest()),
                    )
                    db.commit()
                    batch.clear()
                    if progress:
                        progress(f"gnomAD frequency index: {rows:,} records")
            if rows == 0 or rows < completed:
                raise FrequencyError("gnomAD sites VCF is empty or shorter than its checkpoint")
            db.executemany("INSERT INTO variants VALUES (?, ?, ?)", batch)
            db.execute(
                "UPDATE checkpoint SET rows=?, records_sha256=?", (rows, records_digest.hexdigest())
            )
            db.execute("CREATE INDEX IF NOT EXISTS locus ON variants (chrom, pos)")
            db.commit()
        provenance = {**contract, "records": rows}
        sidecar = output.with_name(output.name + ".provenance.json")
        temporary_sidecar = sidecar.with_name(sidecar.name + ".tmp")
        temporary_sidecar.write_text(
            json.dumps({"provenance": provenance, "index_sha256": _hashes(stage)[0]}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        os.replace(stage, output)
        os.replace(temporary_sidecar, sidecar)
        return cls(output, provenance)

    def lookup(
        self, loci: Iterable[tuple[str, int]]
    ) -> dict[tuple[str, int], list[dict[str, Any]]]:
        """Only memory-only TEMP tables receive sample loci; the index opens read-only."""
        result: dict[tuple[str, int], list[dict[str, Any]]] = {}
        try:
            with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)) as db:
                db.execute("PRAGMA temp_store=MEMORY")
                db.execute("CREATE TEMP TABLE loci (chrom TEXT, pos INTEGER, UNIQUE(chrom, pos))")
                db.executemany("INSERT OR IGNORE INTO loci VALUES (?, ?)", loci)
                for chrom, pos, record in db.execute(
                    "SELECT v.chrom, v.pos, v.record FROM loci l CROSS JOIN variants v "
                    "ON v.chrom=l.chrom AND v.pos=l.pos ORDER BY v.rowid"
                ):
                    result.setdefault((chrom, pos), []).append(json.loads(record))
        except (sqlite3.Error, ValueError) as exc:
            raise FrequencyError("gnomAD frequency index is unreadable") from exc
        return result


def default_index(*, progress: Callable[[str], None] | None = None) -> FrequencyIndex | None:
    from genetics.refs.manifest import load

    source = load().get(SOURCE)
    item = source.files[0]
    path = references_dir() / source.id / item.filename
    if not path.is_file():
        return None
    sha, md5 = _hashes(path)
    if (item.md5 and md5 != item.md5) or (item.sha256 and sha != item.sha256):
        raise FrequencyError("gnomAD VCF does not match its pinned checksum; verify references")
    step = next(s for s in source.post_process if s.step == "build_gnomad_frequency_index")
    return FrequencyIndex.build(
        path,
        output=path.with_name(step.params["output"]),
        version=source.version,
        input_sha256=sha,
        progress=progress,
    )


def select_frequencies(
    records: list[dict[str, Any]], *, alleles: set[str], called: set[str]
) -> tuple[PopulationFrequency, ...]:
    """Exact biallelic SNP, PASS, AC/AN present; choose one consistent population.

    Maximising the rarest observed allele across populations avoids calling an allele
    rare merely because it is diluted in the pooled population. REF is 1 - ALT only
    for a single biallelic record with the same denominator. Duplicates fail closed.
    """
    candidates = [r for r in records if {r["ref"], *r["alts"]} == alleles]
    if len(candidates) != 1 or len(alleles) != 2 or not called or not called <= alleles:
        return ()
    record = candidates[0]
    if (
        record["filter"] != "PASS"
        or len(record["alts"]) != 1
        or any(a not in "ACGT" or len(a) != 1 for a in alleles)
    ):
        return ()
    options: list[tuple[float, str, dict[str, float]]] = []
    for population, counts in record["populations"].items():
        an, ac, af = counts["an"], counts["ac"][0], counts["af"][0]
        if not an or ac is None or af is None:
            continue
        values = {record["alts"][0]: ac / an}
        # gnomAD splits multiallelic loci into biallelic rows. 1-AF on one split
        # row includes the other alternates, so it cannot establish true REF AF.
        # Keep the exact ALT's counts usable, but leave REF unknown at such loci.
        if len(records) == 1:
            values[record["ref"]] = 1 - ac / an
        known = called & values.keys()
        if known:
            options.append((min(values[a] for a in known), population, values))
    if not options:
        return ()
    _, population, values = max(options, key=lambda item: (item[0], item[1] == "global", item[1]))
    return tuple(
        PopulationFrequency(
            a,
            values[a],
            population,
            "gnomAD r2.1.1 exomes; conservative maximum across populations",
        )
        for a in sorted(values)
    )


def reliability(entry: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Screen an observed ClinVar ALT independently from disease penetrance/effect."""
    result: dict[str, Any] = {
        "tier": "unknown",
        "frequency": None,
        "population": None,
        "empirical_ppv": None,
        "reason": "No usable allele-specific frequency; reliability is unknown.",
    }
    if entry["status"] != "alternate_observed":
        return {
            **result,
            "tier": "not_applicable",
            "reason": "No unambiguous alternate observation to calibrate.",
        }
    alt = entry["alts"][0]
    values = select_frequencies(records, alleles={entry["ref"], alt}, called={alt})
    selected = next((v for v in values if v.allele == alt), None)
    if selected is None:
        return result
    result.update(
        frequency=selected.frequency,
        population=selected.population,
        tier="frequency_screen_passed",
        reason=(
            "Outside the empirical rare-call band; this does not establish clinical "
            "significance or confirm the observation."
        ),
    )
    if selected.frequency < RARE_CALL_FREQUENCY_CEILING:
        result.update(
            tier="likely-artifact",
            empirical_ppv={
                "estimate": RARE_CALL_EMPIRICAL_PPV,
                "population_frequency_ceiling": RARE_CALL_FREQUENCY_CEILING,
                "applies_to": (
                    "Published confirmation rate for rare heterozygous SNP-chip "
                    "calls; not an individual posterior probability."
                ),
                "doi": "10.1136/bmj.n214",
            },
            reason=(
                "Below 0.001% even in the highest-frequency represented population. "
                "About 16% of rare heterozygous chip calls were confirmed by sequencing "
                "in the published benchmark."
            ),
        )
    return result


def calibrate(
    lookup: ClinVarLookup,
    *,
    index: FrequencyIndex | None,
    records: Mapping[tuple[str, int], list[dict[str, Any]]],
) -> ClinVarLookup:
    reference: dict[str, Any] = {
        "status": "complete" if index else "not_run",
        "policy": POLICY,
        "provenance": dict(index.provenance) if index else None,
    }
    loci: list[Mapping[str, Any]] = []
    counts: Counter[str] = Counter()
    for locus in lookup.loci:
        found = records.get((locus["chrom"], locus["pos_grch37"]), [])
        entries = []
        for e in locus["records"]:
            enriched = {**e, "frequency_records": found, "reliability": reliability(e, found)}
            if e["status"] == "alternate_observed":
                enriched["reason"] = (
                    "Compatible alternate observed; see the separate "
                    "measurement-reliability screen."
                )
            entries.append(enriched)
            counts[enriched["reliability"]["tier"]] += 1
        loci.append({**locus, "records": entries})
    reference["counts"] = {state: counts[state] for state in RELIABILITY_STATES}
    return ClinVarLookup(
        lookup.status,
        lookup.reason,
        lookup.provenance,
        lookup.counts,
        tuple(loci),
        frequency_reference=reference,
    )


def validate_calibration(raw: Mapping[str, Any]) -> None:
    """Validate the saved schema-2 frequency screen without fetching/reinterpreting."""
    from genetics.health.clinvar import PROVENANCE_KEYS, validate_lookup

    try:
        base = json.loads(json.dumps(raw))
        reference = base.pop("frequency_reference")
        base["schema_version"] = 1
        if (
            set(reference) != {"status", "policy", "provenance", "counts"}
            or reference["status"] not in {"complete", "not_run"}
            or not isinstance(reference["policy"], str)
            or not reference["policy"]
        ):
            raise ValueError
        provenance = reference["provenance"]
        if reference["status"] == "not_run":
            if provenance is not None:
                raise ValueError
        elif (
            not isinstance(provenance, dict)
            or set(provenance) != PROVENANCE_KEYS
            or provenance["source"] != SOURCE
            or provenance["version"] != "r2.1.1"
            or provenance["build"] != "GRCh37"
            or provenance["index_schema_version"] not in SUPPORTED_SNAPSHOT_INDEX_VERSIONS
            or type(provenance["index_schema_version"]) is not int
            or not isinstance(provenance["filename"], str)
            or not provenance["filename"]
            or not re.fullmatch("[0-9a-f]{64}", provenance["sha256"])
            or type(provenance["records"]) is not int
            or provenance["records"] <= 0
        ):
            raise ValueError
        actual_tiers: Counter[str] = Counter()
        for locus in base["loci"]:
            for entry in locus["records"]:
                records = entry.pop("frequency_records")
                recorded = entry.pop("reliability")
                if not isinstance(records, list) or (reference["status"] == "not_run" and records):
                    raise ValueError
                for record in records:
                    if (
                        set(record)
                        != {
                            "chrom",
                            "pos_grch37",
                            "ref",
                            "alts",
                            "filter",
                            "populations",
                            "af_popmax",
                            "popmax",
                        }
                        or record["chrom"] != locus["chrom"]
                        or record["pos_grch37"] != locus["pos_grch37"]
                        or type(record["pos_grch37"]) is not int
                    ):
                        raise ValueError
                    info: list[str] = []
                    for pop, counts in record["populations"].items():
                        if pop not in POPULATIONS or set(counts) != {"af", "ac", "an", "nhomalt"}:
                            raise ValueError
                        suffix = "" if pop == "global" else "_" + pop
                        for field, value in counts.items():
                            values = [value] if field == "an" else value
                            if (
                                not isinstance(values, list)
                                or any(type(v) not in (int, float, type(None)) for v in values)
                                or (
                                    field != "af"
                                    and any(v is not None and type(v) is not int for v in values)
                                )
                            ):
                                raise ValueError
                            info.append(
                                (field.upper() if field != "nhomalt" else field)
                                + suffix
                                + "="
                                + ",".join("." if v is None else str(v) for v in values)
                            )
                    info.extend(
                        (
                            "AF_popmax="
                            + ",".join("." if v is None else str(v) for v in record["af_popmax"]),
                            "popmax=" + ",".join("." if v is None else v for v in record["popmax"]),
                        )
                    )
                    reconstructed = parse_record(
                        "\t".join(
                            (
                                record["chrom"],
                                str(record["pos_grch37"]),
                                ".",
                                record["ref"],
                                ",".join(record["alts"]),
                                ".",
                                record["filter"],
                                ";".join(info),
                            )
                        )
                    )
                    if reconstructed != record:
                        raise ValueError
                if recorded != reliability(entry, records):
                    raise ValueError
                actual_tiers[recorded["tier"]] += 1
        if (
            not isinstance(reference["counts"], dict)
            or set(reference["counts"]) != set(RELIABILITY_STATES)
            or any(type(n) is not int or n < 0 for n in reference["counts"].values())
            or reference["counts"] != {state: actual_tiers[state] for state in RELIABILITY_STATES}
        ):
            raise ValueError
        validate_lookup(base)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise FrequencyError(
            "Saved gnomAD frequency calibration is malformed or inconsistent"
        ) from exc
