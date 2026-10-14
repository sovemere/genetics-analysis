"""Conservative, phase-unresolved SNP calling and reproducible private snapshots.

Sparse definitions are constraints, never complete invented haplotypes. All
compatible alternatives survive; source mappings describe candidates, not prescriptions.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations_with_replacement
from typing import Any

from genetics.health.frequencies import select_frequencies
from genetics.imputation.dosages import DosageRecord, parse_record
from genetics.ingest.schema import CallStatus, GenotypeTable
from genetics.paths import references_dir
from genetics.pgx.catalog import TRACTABLE, Catalog, validate_record
from genetics.pgx.sources import digest, object_field
from genetics.privacy import NoGenotypeRepr
from genetics.qc.report import InferredSex
from genetics.refs.postprocess import ProcessError

VERSION = 1
Locus = tuple[str, int]
NOTICE = (
    "SNP-compatible candidates only; structural/CNV variation remains unmeasured. "
    "Missing markers, unresolved phase and incomplete definitions cannot establish an allele."
)


class CallingError(ValueError):
    """Invalid PGx input or snapshot; messages never contain sample observations."""


def loci(catalog: Catalog) -> set[Locus]:
    return {
        (location["key"]["chrom"], location["key"]["pos_grch37"])
        for location in catalog.record["locations"].values()
        if location["source_location"]["genesymbol"] in TRACTABLE and location["key"] is not None
    }


@dataclass(frozen=True, repr=False)
class SampleCalls(NoGenotypeRepr):
    record: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.record)


def unavailable(reason: str, *, sex: str | None = None) -> SampleCalls:
    return SampleCalls(
        {
            "schema_version": VERSION,
            "status": "unavailable",
            "reason": reason,
            "sex": sex,
            "reference": None,
            "reference_sha256": None,
            "observations": [],
            "genes": {
                gene: {"status": "unavailable", "reason": reason, "candidates": []}
                for gene in TRACTABLE
            },
        }
    )


def collect(
    catalog: Catalog,
    table: GenotypeTable,
    *,
    dosages: Iterable[DosageRecord] = (),
    frequencies: Mapping[Locus, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    requested = loci(catalog)
    probes: dict[Locus, list[dict[str, Any]]] = defaultdict(list)
    for row in table.frame.iter_rows(named=True):
        key = (row["chrom"], row["pos_grch37"])
        if key in requested:
            probes[key].append({name: row[name] for name in ("rsid", "a1", "a2", "call_status")})
    imputed: dict[Locus, list[dict[str, Any]]] = defaultdict(list)
    for record in dosages:
        key = (record.chrom, record.pos_grch37)
        if key in requested:
            imputed[key].append(parse_record(record.to_dict()).to_dict())
    return [
        {
            "chrom": chrom,
            "pos_grch37": pos,
            "probes": probes[(chrom, pos)],
            "dosages": imputed[(chrom, pos)],
            "frequencies": (frequencies or {}).get((chrom, pos), []),
        }
        for chrom, pos in sorted(requested)
    ]


def _frequency_check(records: list[Any], key: Locus) -> None:
    for r in records:
        if (r["chrom"], r["pos_grch37"]) != key or type(r["pos_grch37"]) is not int:
            raise CallingError("PGx frequency coordinates disagree.")
        if not isinstance(r["ref"], str) or not isinstance(r["alts"], list) or not r["alts"]:
            raise CallingError("PGx frequency alleles are malformed.")
        for counts in r["populations"].values():
            an = counts["an"]
            if an is not None and (type(an) is not int or an < 0):
                raise CallingError("PGx frequency denominator is invalid.")
            for name in ("af", "ac", "nhomalt"):
                vector = counts[name]
                if len(vector) != len(r["alts"]):
                    raise CallingError("PGx frequency cardinality is invalid.")
                for value in vector:
                    if value is None:
                        continue
                    if (
                        type(value) not in (int, float)
                        or not math.isfinite(value)
                        or value < 0
                        or (name == "af" and value > 1)
                        or (name != "af" and type(value) is not int)
                        or (name == "ac" and an is not None and value > an)
                    ):
                        raise CallingError("PGx frequency counts are invalid.")
            for af, ac in zip(counts["af"], counts["ac"], strict=True):
                if (
                    an
                    and af is not None
                    and ac is not None
                    and not math.isclose(af, ac / an, rel_tol=0.001, abs_tol=1e-7)
                ):
                    raise CallingError("PGx frequency values disagree with counts.")


def _observed(raw: Mapping[str, Any], alleles: set[str], ploidy: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": "untyped",
        "bases": None,
        "source": None,
        "quality": None,
        "probe_ids": [p["rsid"] for p in raw["probes"]],
    }
    probes = [p for p in raw["probes"] if p["call_status"] != CallStatus.NO_CALL.value]
    if probes:
        bases = {(p["a1"], p["a2"]) for p in probes}
        if any(p["call_status"] == CallStatus.HET_HAPLOID.value for p in probes):
            result["state"] = "ploidy-conflict"
        elif len(bases) != 1:
            result["state"] = "conflicting-probes"
        else:
            pair = next(iter(bases))
            if not set(pair) <= set("ACGT"):
                result["state"] = "excluded-indel"
            elif not set(pair) <= alleles:
                result["state"] = "incompatible-alleles"
            elif (ploidy == 1 and pair[0] != pair[1]) or (
                ploidy == 2 and any(p["call_status"] == CallStatus.HEMIZYGOUS.value for p in probes)
            ):
                result["state"] = "ploidy-conflict"
            else:
                result.update(state="observed", bases=list(pair[:ploidy]), source="direct")
    elif len(raw["dosages"]) > 1:
        result["state"] = "ambiguous-imputation"
    elif raw["dosages"]:
        record = parse_record(raw["dosages"][0])
        if record.source == "direct":
            result["state"] = "no-original-call"
        elif record.ploidy != ploidy:
            result["state"] = "ploidy-conflict"
        elif set((record.ref, *record.alt)) != alleles or any(
            len(a) != 1 or a not in "ACGT" for a in (record.ref, *record.alt)
        ):
            result["state"] = "incompatible-imputation"
        elif (record.source == "imputed_no_call") != bool(raw["probes"]):
            raise CallingError("PGx imputation source disagrees with original probes.")
        else:
            assert record.genotype is not None
            native_bases = (record.ref, *record.alt)
            result.update(
                state="observed",
                bases=sorted(native_bases[a] for a in record.genotype),
                source=record.source,
                quality=None if record.dr2 is None else min(record.dr2),
            )
    if result["state"] == "untyped" and raw["probes"]:
        result["state"] = "no-call"
    values = select_frequencies(
        raw["frequencies"], alleles=alleles, called=set(result["bases"] or [])
    )
    result["frequencies"] = [
        v.to_dict()
        if hasattr(v, "to_dict")
        else {
            "allele": v.allele,
            "frequency": v.frequency,
            "population": v.population,
            "source": v.source,
        }
        for v in values
    ]
    called = set(result["bases"] or [])
    known = {v.allele for v in values}
    result["rarity"] = (
        "likely-artifact"
        if any(v.allele in called and v.frequency < 0.00001 for v in values)
        else "frequency_screen_passed"
        if called and called <= known
        else "unknown"
    )
    result["rare_call_benchmark"] = (
        None
        if result["rarity"] != "likely-artifact"
        else {
            "estimate": 0.16,
            "doi": "10.1136/bmj.n214",
            "scope": "Rare heterozygous SNP-chip calls; not a personal posterior "
            "or an imputation validation.",
        }
    )
    return result


def _requirements(
    definition: Mapping[str, Any], locations: list[Any]
) -> tuple[dict[Locus, str], list[str]]:
    required: dict[Locus, str] = {}
    unresolved = []
    if definition["state"] in {
        "conflicting-definition",
        "unsupported-structural-or-copy-number",
        "missing-definition",
    }:
        return {}, [definition["state"]]
    constraints = definition["constraints"]
    for value in constraints:
        if value["key"] is None:
            unresolved.append(value["location_id"])
        else:
            key = value["key"]
            required[(key["chrom"], key["pos_grch37"])] = value["required_allele"]
    if definition["source_definition"]["matchesreferencesequence"] == "t":
        if not locations:
            unresolved.append("missing-gene-locations")
        for location in locations:
            key = location["key"]
            if key is None:
                unresolved.append(location["source_location"]["id"])
            else:
                locus = (key["chrom"], key["pos_grch37"])
                if locus in required and required[locus] != location["ref"]:
                    return {}, ["conflicting-reference-definition"]
                required[locus] = location["ref"]
    return required, sorted(set(unresolved))


def derive(catalog: Catalog, observations: list[dict[str, Any]], sex: str) -> dict[str, Any]:
    by_locus = {(r["chrom"], r["pos_grch37"]): r for r in observations}
    tables = catalog.record["cpic"]["tables"]
    genes: dict[str, Any] = {}
    for gene in TRACTABLE:
        info = (
            catalog.inspect(gene=gene) if any(g["symbol"] == gene for g in tables["gene"]) else None
        )
        if info is None:
            genes[gene] = {
                "status": "missing-gene",
                "reason": "Gene absent from the source release.",
                "candidates": [],
            }
            continue
        definitions = info["definitions"]
        locations = [
            r
            for r in catalog.record["locations"].values()
            if r["source_location"]["genesymbol"] == gene
        ]
        allele_sets: dict[Locus, set[str]] = defaultdict(set)
        for location in locations:
            if location["key"] is not None:
                key = location["key"]
                allele_sets[(key["chrom"], key["pos_grch37"])].update(key["alleles"])
        requirements = {
            d["source_definition"]["id"]: _requirements(d, locations) for d in definitions
        }
        definition_ids = sorted(requirements)
        names = {d["source_definition"]["id"]: d["source_definition"]["name"] for d in definitions}
        function_issues = [
            d["source_definition"]["id"]
            for d in definitions
            if d["function_state"] != "available"
            or any(not f["functionalstatus"] for f in d["functions"])
        ]
        phenotypes = {r["id"]: r for r in info["phenotypes"]}
        lookups = {r["id"]: r for r in info["function_lookups"]}
        mapping_index: dict[tuple[tuple[str, int], ...], list[Any]] = defaultdict(list)
        for row in tables["gene_result_diplotype"]:
            if row["functionphenotypeid"] in lookups:
                counts = object_field(row["diplotypekey"])[gene]
                mapping_index[tuple(sorted(counts.items()))].append(row)
        ploidies = [2] if gene != "G6PD" or sex == "female" else [1] if sex == "male" else [1, 2]
        models: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        for ploidy in ploidies:
            observed = {
                key: _observed(by_locus[key], alleles, ploidy)
                for key, alleles in allele_sets.items()
            }
            usable = {key: r["bases"] for key, r in observed.items() if r["state"] == "observed"}
            models.append(
                {
                    "ploidy": ploidy,
                    "observations": [
                        {"chrom": key[0], "pos_grch37": key[1], **r}
                        for key, r in sorted(observed.items())
                    ],
                    "coverage": {
                        "source_locations": len(locations),
                        "resolved_loci": len(allele_sets),
                        "observed_loci": len(usable),
                        "unresolved_locations": sum(r["key"] is None for r in locations),
                    },
                }
            )
            compatible = [
                i
                for i in definition_ids
                if all(
                    key not in usable or base in usable[key]
                    for key, base in requirements[i][0].items()
                )
            ]
            pairs = (
                ((i,) for i in compatible)
                if ploidy == 1
                else combinations_with_replacement(compatible, 2)
            )
            for pair in pairs:
                reqs = [requirements[i][0] for i in pair]
                if any(
                    not any(
                        all(
                            req.get(key) is None or req[key] == base
                            for req, base in zip(reqs, order, strict=True)
                        )
                        for order in (bases, list(reversed(bases)))
                    )
                    for key, bases in usable.items()
                ):
                    continue
                required_loci = set().union(*(set(r) for r in reqs))
                missing = sorted(required_loci - usable.keys())
                unresolved = {i: requirements[i][1] for i in pair if requirements[i][1]}
                unassigned = sorted(key for key in usable if any(key not in r for r in reqs))
                counts = tuple(sorted(Counter(names[i] for i in pair).items()))
                matches = mapping_index.get(counts, [])
                mapping_ids = sorted(r["id"] for r in matches)
                lookup_ids = sorted({r["functionphenotypeid"] for r in matches})
                result_ids = sorted({lookups[i]["phenotypeid"] for i in lookup_ids})
                candidates.append(
                    {
                        "definition_ids": list(pair),
                        "alleles": [names[i] for i in pair],
                        "ploidy": ploidy,
                        "supported_constraints": sum(key in usable for req in reqs for key in req),
                        "missing_loci": [list(key) for key in missing],
                        "unresolved_constraints": unresolved,
                        "unassigned_loci": [list(key) for key in unassigned],
                        "function_issues": sorted(set(pair) & set(function_issues)),
                        "support": "complete"
                        if not missing and not unresolved and not unassigned
                        else "conditional",
                        "mapping_status": "missing-mapping"
                        if not matches
                        else "conflicting-mappings"
                        if len(result_ids) > 1
                        else "available",
                        "mapping_ids": mapping_ids,
                        "lookup_ids": lookup_ids,
                        "phenotypes": [phenotypes[i]["result"] for i in result_ids],
                        "activity_scores": sorted(
                            {lookups[i]["totalactivityscore"] for i in lookup_ids}, key=str
                        ),
                    }
                )
        all_observed = [o for m in models for o in m["observations"] if o["state"] == "observed"]
        tier = (
            "likely-artifact"
            if any(o["rarity"] == "likely-artifact" for o in all_observed)
            else "limited"
        )
        reasons = [NOTICE]
        if any(
            o["source"] != "direct" and (o["quality"] is None or o["quality"] < 0.8)
            for o in all_observed
        ):
            reasons.append("Imputed hard calls include unknown or low dosage quality (DR2 < 0.8).")
        if any(o["rarity"] == "unknown" for o in all_observed):
            reasons.append("Some observed alleles have unknown frequency; rarity is not ruled out.")
        if tier == "likely-artifact":
            reasons.append(
                "Rare-call band: ~16% of rare heterozygous chip calls confirmed in the "
                "benchmark; imputation does not resolve rare-call reliability."
            )
        complete = len(candidates) == 1 and candidates[0]["support"] == "complete"
        if (
            complete
            and (gene != "G6PD" or sex != "ambiguous")
            and tier != "likely-artifact"
            and not candidates[0]["function_issues"]
            and candidates[0]["mapping_status"] == "available"
            and all_observed
            and all(
                o["rarity"] != "unknown"
                and (o["source"] == "direct" or (o["quality"] is not None and o["quality"] >= 0.8))
                for o in all_observed
            )
        ):
            tier = "provisional"
        genes[gene] = {
            "status": "unique-compatible"
            if complete
            else "ambiguous"
            if candidates
            else "no-compatible-definition",
            "reason": "Candidate compatibility is conditional on the saved source definitions.",
            "phase": "single-copy" if ploidies == [1] else "unresolved",
            "ploidy_status": "unresolved" if len(ploidies) > 1 else "qc-resolved",
            "reliability": {"tier": tier, "reasons": reasons},
            "models": models,
            "definitions": definitions,
            "candidates": candidates,
            "lookup_method": info["gene"]["lookupmethod"],
            "phenotype_mapping_status": info["phenotype_mapping_status"],
            "phenotypes": info["phenotypes"],
            "function_lookups": info["function_lookups"],
            "notes": [r for r in tables["file_note"] if r["entityid"] == gene],
            "gene_notes": {k: v for k, v in info["gene"].items() if k.startswith("notes")},
            "guidelines": info["guidelines"],
            "publications": info["publications"],
            "recommendation_keys": [
                {
                    "id": r["id"],
                    "guidelineid": r["guidelineid"],
                    "lookupkey": object_field(r["lookupkey"]),
                }
                for r in tables["recommendation"]
                if gene in object_field(r["lookupkey"])
            ],
        }
    return genes


def call(
    catalog: Catalog,
    table: GenotypeTable,
    *,
    sex: InferredSex,
    dosages: Iterable[DosageRecord] = (),
    frequencies: Mapping[Locus, list[dict[str, Any]]] | None = None,
) -> SampleCalls:
    observations = collect(catalog, table, dosages=dosages, frequencies=frequencies)
    record = {
        "schema_version": VERSION,
        "status": "completed",
        "reason": None,
        "sex": sex.value,
        "reference": dict(catalog.record),
        "reference_sha256": digest(catalog.record),
        "observations": observations,
        "genes": derive(catalog, observations, sex.value),
    }
    validate(record)
    return SampleCalls(record)


def validate(raw: Mapping[str, Any]) -> None:
    """Reproduce from immutable inputs; corruption never becomes a partial healthy call."""
    try:
        if (
            set(raw)
            != {
                "schema_version",
                "status",
                "reason",
                "sex",
                "reference",
                "reference_sha256",
                "observations",
                "genes",
            }
            or type(raw["schema_version"]) is not int
            or raw["schema_version"] != VERSION
        ):
            raise ValueError
        if raw["status"] == "unavailable":
            if (
                not isinstance(raw["reason"], str)
                or not raw["reason"].strip()
                or raw["sex"] not in (None, *list(InferredSex))
            ):
                raise ValueError
            if digest(raw) != digest(unavailable(raw["reason"], sex=raw["sex"]).record):
                raise ValueError
            return
        if (
            raw["status"] != "completed"
            or raw["reason"] is not None
            or raw["sex"] not in list(InferredSex)
        ):
            raise ValueError
        validate_record(raw["reference"])
        if digest(raw["reference"]) != raw["reference_sha256"]:
            raise ValueError
        catalog = Catalog(raw["reference"])
        observations = raw["observations"]
        if not isinstance(observations, list) or len(observations) != len(loci(catalog)):
            raise ValueError
        keys = set()
        for r in observations:
            if (
                set(r) != {"chrom", "pos_grch37", "probes", "dosages", "frequencies"}
                or type(r["pos_grch37"]) is not int
            ):
                raise ValueError
            key = (r["chrom"], r["pos_grch37"])
            if key in keys:
                raise ValueError
            keys.add(key)
            if any(not isinstance(r[k], list) for k in ("probes", "dosages", "frequencies")):
                raise ValueError
            for p in r["probes"]:
                if set(p) != {"rsid", "a1", "a2", "call_status"} or (
                    p["rsid"] is not None and not isinstance(p["rsid"], str)
                ):
                    raise ValueError
                status = CallStatus(p["call_status"])
                if status == CallStatus.NO_CALL:
                    if p["a1"] is not None or p["a2"] is not None:
                        raise ValueError
                elif (
                    any(a not in set("ACGTID") for a in (p["a1"], p["a2"]))
                    or p["a1"] > p["a2"]
                    or (status == CallStatus.HEMIZYGOUS and p["a1"] != p["a2"])
                ):
                    raise ValueError
            for d in r["dosages"]:
                native = parse_record(d)
                if (native.chrom, native.pos_grch37) != key:
                    raise ValueError
            _frequency_check(r["frequencies"], key)
        if keys != loci(catalog) or digest(raw["genes"]) != digest(
            derive(catalog, observations, raw["sex"])
        ):
            raise ValueError
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        OverflowError,
        ProcessError,
    ):
        raise CallingError("Saved PGx sample-call record is malformed or inconsistent.") from None


def report(raw: Mapping[str, Any] | None, gene: str | None = None) -> dict[str, Any]:
    if gene is not None and gene not in TRACTABLE:
        raise CallingError("PGx calling is restricted to the eight SNP-tractable genes.")
    if raw is None:
        return {
            "schema_version": None,
            "status": "not-recorded",
            "reason": "PGx was not recorded by this run format.",
            "genes": {},
        }
    return {k: raw[k] for k in ("schema_version", "status", "reason", "sex")} | {
        "reference_sha256": raw["reference_sha256"],
        "genes": dict(raw["genes"]) if gene is None else {gene: raw["genes"][gene]},
        "sources": None
        if raw["reference"] is None
        else {
            "cpic": raw["reference"]["cpic"]["source"],
            "pharmgkb": raw["reference"]["annotations"]["source"],
        },
        "observations": [
            r
            for r in raw["observations"]
            if gene is None
            or any(
                (r["chrom"], r["pos_grch37"]) == (o["chrom"], o["pos_grch37"])
                for model in raw["genes"][gene].get("models", [])
                for o in model["observations"]
            )
        ],
    }


def validate_execution(raw: Mapping[str, Any], *, sex: str, imputation_mode: str) -> None:
    validate(raw)
    if raw["sex"] != sex:
        raise CallingError("PGx ploidy disagrees with run QC.")
    if imputation_mode != "enabled" and any(
        d["source"] != "direct" for r in raw["observations"] for d in r["dosages"]
    ):
        raise CallingError("PGx has imputed observations without enabled run imputation.")


class CallingStage:
    """Optional public reference, with present damage treated as an error."""

    def __init__(self, catalog: Catalog | None = None) -> None:
        self.catalog = catalog

    def prepare(self) -> None:
        if self.catalog is None and (references_dir() / "cpic" / "pgx_reference.json").exists():
            self.catalog = Catalog.default()
        elif self.catalog is not None:
            validate_record(self.catalog.record)

    def run(
        self,
        table: GenotypeTable,
        *,
        sex: InferredSex,
        dosages: Callable[[], Iterable[DosageRecord]] | None = None,
        frequencies: Mapping[Locus, list[dict[str, Any]]] | None = None,
    ) -> SampleCalls:
        if self.catalog is None:
            return unavailable(
                "Prepared PGx reference absent; run genetics pgx prepare.", sex=sex.value
            )
        return call(
            self.catalog,
            table,
            sex=sex,
            dosages=() if dosages is None else dosages(),
            frequencies=frequencies,
        )
