"""Frozen PGx reference contract, GRCh37 mapping proofs and shared inspection.

No consumer file, dosage, confidence or run-bundle code is reachable here. A
resolved reference constraint is not a callable sample diplotype.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from genetics import paths
from genetics.ingest.keys import MergeTable
from genetics.pgx.archives import MEMBERS
from genetics.pgx.sources import (
    digest,
    load_source,
    object_field,
    validate_archive_metadata,
    validate_identity,
    validate_source,
)
from genetics.refs import postprocess
from genetics.refs.postprocess import ProcessError

TRACTABLE = ("CYP2C19", "CYP2C9", "VKORC1", "SLCO1B1", "TPMT", "DPYD", "NUDT15", "G6PD")
VERSION = 1
_GR37_VERSIONS = (
    10,
    11,
    11,
    11,
    9,
    11,
    13,
    10,
    11,
    10,
    9,
    11,
    10,
    8,
    9,
    9,
    10,
    9,
    9,
    10,
    8,
    10,
    10,
    9,
)
_GR38_VERSIONS = (
    11,
    12,
    12,
    12,
    10,
    12,
    14,
    11,
    12,
    11,
    10,
    12,
    11,
    9,
    10,
    10,
    11,
    10,
    10,
    11,
    9,
    11,
    11,
    10,
)
_RSID = re.compile(r"rs[1-9]\d*")
_SNV = re.compile(r"g\.([1-9]\d*)([ACGT])>([ACGT])")
_HGVS = re.compile(r"(NC_\d{6}\.\d+):g\.([1-9]\d*)([ACGT])>([ACGT])")


def accession(chrom: str, build: str) -> str | None:
    number = 23 if chrom == "X" else 24 if chrom == "Y" else int(chrom) if chrom.isdigit() else 0
    if not 1 <= number <= 24:
        return None
    versions = _GR37_VERSIONS if build == "GRCh37" else _GR38_VERSIONS
    return f"NC_{number:06d}.{versions[number - 1]}"


def _dbsnp(root: Path, rsids: set[str], *, bind: bool) -> dict[str, Any]:
    directory = root / "dbsnp_b157_grch37"
    names = ("dbsnp_variants.parquet", "rsid_merges.parquet", "rsid_unresolvable.parquet")
    stats = {
        name: ((directory / name).stat().st_size, (directory / name).stat().st_mtime_ns)
        for name in names
    }
    proofs = {}
    for name in names:
        step = "extract_dbsnp_variant_index" if name == names[0] else "extract_rsid_merge_table"
        contract = (
            postprocess.declared_artifact_provenance(
                "dbsnp_b157_grch37",
                step,
                output_param="unresolvable_output" if name == names[2] else "output",
                output_name=name,
            )
            if bind
            else None
        )
        proofs[name] = postprocess.validate_provenance(
            directory / name,
            expected=contract,
            expected_step=step,
            expected_transform_version=postprocess.get(step).transform_version,
        )
    merges = MergeTable.from_parquet(
        directory / names[1], rsids=rsids, unresolved_path=directory / names[2]
    )
    resolutions = {
        rsid: {
            "status": resolution.status.value,
            "current_rsid": resolution.current_rsid,
            "targets": list(resolution.targets),
        }
        for rsid, resolution in sorted(merges.resolve_all_results(rsids).items())
    }
    current = sorted(
        {r["current_rsid"] for r in resolutions.values() if r["current_rsid"] is not None}
    )
    frame = pl.scan_parquet(directory / names[0]).filter(pl.col("rsid").is_in(current)).collect()
    records = frame.select("rsid", "chrom", "pos_grch37", "ref", "alts").to_dicts()
    if stats != {
        name: ((directory / name).stat().st_size, (directory / name).stat().st_mtime_ns)
        for name in names
    }:
        raise ProcessError("dbSNP source changed during PGx normalization.")
    return {"provenance": proofs, "resolutions": resolutions, "variants": records}


def _validate_dbsnp(proof: Mapping[str, Any], rsids: set[str]) -> None:
    resolutions, variants, provenance = (
        proof.get("resolutions"),
        proof.get("variants"),
        proof.get("provenance"),
    )
    if (
        not isinstance(resolutions, dict)
        or set(resolutions) != rsids
        or not isinstance(variants, list)
        or not isinstance(provenance, dict)
    ):
        raise ProcessError("PGx dbSNP snapshot has incomplete identities.")
    expected_names = {"dbsnp_variants.parquet", "rsid_merges.parquet", "rsid_unresolvable.parquet"}
    if set(provenance) != expected_names:
        raise ProcessError("PGx dbSNP snapshot lacks provenance.")
    for name, item in provenance.items():
        step = (
            "extract_dbsnp_variant_index"
            if name == "dbsnp_variants.parquet"
            else "extract_rsid_merge_table"
        )
        if (
            not isinstance(item, dict)
            or type(item.get("schema_version")) is not int
            or item["schema_version"] != postprocess._PROVENANCE_VERSION
            or item.get("step") != step
            or item.get("output") != name
            or type(item.get("transform_version")) is not int
            or item["transform_version"] != postprocess.get(step).transform_version
            or type(item.get("rows")) is not int
            or item["rows"] < 0
            or not isinstance(item.get("input"), dict)
            or not isinstance(item.get("params"), dict)
            or not isinstance(item.get("output_sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", item["output_sha256"]) is None
            or not isinstance(item["input"].get("sha256"), str)
            or re.fullmatch(r"[a-f0-9]{64}", item["input"]["sha256"]) is None
        ):
            raise ProcessError("PGx dbSNP snapshot provenance is malformed.")
    merge_keys = ("input", "params", "step", "transform_version")
    if any(
        provenance["rsid_merges.parquet"][k] != provenance["rsid_unresolvable.parquet"][k]
        for k in merge_keys
    ):
        raise ProcessError("PGx dbSNP merge artifacts disagree.")
    current = set()
    for resolution in resolutions.values():
        if not isinstance(resolution, dict) or set(resolution) != {
            "status",
            "current_rsid",
            "targets",
        }:
            raise ProcessError("Malformed PGx rsID resolution.")
        status, target, targets = (
            resolution["status"],
            resolution["current_rsid"],
            resolution["targets"],
        )
        if not isinstance(targets, list) or any(
            not isinstance(t, str) or _RSID.fullmatch(t) is None for t in targets
        ):
            raise ProcessError("Malformed PGx rsID targets.")
        if status == "current":
            if not isinstance(target, str) or _RSID.fullmatch(target) is None or targets:
                raise ProcessError("Malformed current PGx rsID.")
            current.add(target)
        elif (
            target is not None
            or status not in {"no-current-target", "multiple-current-targets", "cycle"}
            or (status == "multiple-current-targets" and len(set(targets)) < 2)
            or (status != "multiple-current-targets" and targets)
        ):
            raise ProcessError("Malformed ambiguous PGx rsID.")
    for row in variants:
        if (
            not isinstance(row, dict)
            or row.get("rsid") not in current
            or row.get("chrom") not in {*(str(i) for i in range(1, 23)), "X", "Y", "MT", "PAR"}
            or type(row.get("pos_grch37")) is not int
            or row["pos_grch37"] < 1
            or not isinstance(row.get("ref"), str)
            or not row["ref"]
            or not isinstance(row.get("alts"), list)
            or not row["alts"]
            or any(not isinstance(a, str) or not a for a in row["alts"])
        ):
            raise ProcessError("Malformed PGx dbSNP reference variant.")


def _rsids(cpic: Mapping[str, Any]) -> set[str]:
    return {
        r["dbsnpid"]
        for r in cpic["tables"]["sequence_location"]
        if isinstance(r["dbsnpid"], str) and _RSID.fullmatch(r["dbsnpid"])
    }


def normalize(
    cpic: Mapping[str, Any], variants: list[dict[str, str]], dbsnp: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    genes = {g["symbol"]: g for g in cpic["tables"]["gene"]}
    by_rsid: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in variants:
        labels = {row["Variant Name"], *row["Synonyms"].split(", ")}
        for label in labels:
            if _RSID.fullmatch(label):
                by_rsid[label].append(row)
    reference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in dbsnp["variants"]:
        reference[row["rsid"]].append(row)
    locations = {}
    for location in cpic["tables"]["sequence_location"]:
        gene = genes[location["genesymbol"]]
        chrom = (gene["chr"] or "").removeprefix("chr")
        source_accession = gene["chromosequenceid"]
        source_build = (
            "GRCh37"
            if source_accession == accession(chrom, "GRCh37") and source_accession
            else "GRCh38"
            if source_accession == accession(chrom, "GRCh38") and source_accession
            else None
        )
        rsid = location["dbsnpid"]
        resolution = dbsnp["resolutions"].get(rsid)
        record: dict[str, Any] = {
            "source_location": dict(location),
            "source_accession": source_accession,
            "source_build": source_build,
            "rsid_resolution": resolution,
            "state": "unresolved",
            "key": None,
            "ref": None,
            "alt": None,
            "mapping_evidence": [],
        }
        snv = _SNV.fullmatch(location["chromosomelocation"] or "")
        if source_build is None:
            record["state"] = "unknown-source-build"
        elif snv is None or snv[2] == snv[3]:
            record["state"] = "unsupported-allele-representation"
        elif int(snv[1]) != int(location["position"]):
            record["state"] = "conflicting-source-coordinate"
        elif resolution is None:
            record["state"] = "missing-rsid"
        elif resolution["current_rsid"] is None:
            record["state"] = "unresolved-rsid"
        else:
            current = resolution["current_rsid"]
            candidates: set[tuple[str, int, str, str]] = set()
            evidence = []
            if source_build == "GRCh37":
                candidates.add((chrom, int(snv[1]), snv[2], snv[3]))
                evidence.append(
                    {
                        "source": "cpic",
                        "accession": source_accession,
                        "hgvs": location["chromosomelocation"],
                    }
                )
            else:
                for annotation in by_rsid.get(rsid, []) + (
                    by_rsid.get(current, []) if current != rsid else []
                ):
                    hgvs = [
                        m.groups()
                        for synonym in annotation["Synonyms"].split(", ")
                        if (m := _HGVS.fullmatch(synonym))
                    ]
                    source_key = (source_accession, snv[1], snv[2], snv[3])
                    if source_key not in hgvs:
                        continue
                    for acc, pos, ref, alt in hgvs:
                        if acc == accession(chrom, "GRCh37") and (ref, alt) == (snv[2], snv[3]):
                            candidates.add((chrom, int(pos), ref, alt))
                            evidence.append(
                                {
                                    "source": "pharmgkb",
                                    "variant_id": annotation["Variant ID"],
                                    "source_hgvs": (
                                        f"{source_accession}:{location['chromosomelocation']}"
                                    ),
                                    "grch37_hgvs": f"{acc}:g.{pos}{ref}>{alt}",
                                }
                            )
            record["mapping_evidence"] = evidence
            if not candidates:
                record["state"] = "missing-grch37-mapping"
            elif len(candidates) != 1:
                record["state"] = "conflicting-grch37-mapping"
            else:
                mapped_chrom, pos, ref, alt = next(iter(candidates))
                hits = reference.get(current, [])
                if len(hits) != 1:
                    record["state"] = (
                        "missing-dbsnp-variant" if not hits else "ambiguous-dbsnp-variant"
                    )
                elif not (
                    hits[0]["chrom"] == mapped_chrom
                    and hits[0]["pos_grch37"] == pos
                    and hits[0]["ref"] == ref
                    and alt in hits[0]["alts"]
                ):
                    record["state"] = "conflicting-dbsnp-variant"
                else:
                    record.update(
                        state="resolved-snv",
                        key={"chrom": chrom, "pos_grch37": pos, "alleles": sorted([ref, alt])},
                        ref=ref,
                        alt=alt,
                    )
        locations[location["id"]] = record
    constraints: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for value in cpic["tables"]["allele_location_value"]:
        locus = locations[value["locationid"]]
        allele = value["variantallele"]
        constraints[value["alleledefinitionid"]].append(
            {
                "source_value": dict(value),
                "location_id": value["locationid"],
                "required_allele": allele,
                "state": locus["state"]
                if locus["state"] != "resolved-snv"
                else "resolved-snv"
                if allele in {locus["ref"], locus["alt"]}
                else "unsupported-allele-representation",
                "key": locus["key"]
                if locus["state"] == "resolved-snv" and allele in {locus["ref"], locus["alt"]}
                else None,
            }
        )
    functions: dict[str, list[Any]] = defaultdict(list)
    for function in cpic["tables"]["allele"]:
        functions[function["definitionid"]].append(dict(function))
    definitions = {}
    names = Counter((d["genesymbol"], d["name"]) for d in cpic["tables"]["allele_definition"])
    for definition in cpic["tables"]["allele_definition"]:
        identity = definition["id"]
        values = constraints[identity]
        state = "resolved-snv-definition"
        if definition["structuralvariation"] == "t" or definition["genesymbol"] == "CYP2D6":
            state = "unsupported-structural-or-copy-number"
        elif not values:
            state = (
                "reference-definition"
                if definition["matchesreferencesequence"] == "t"
                else "missing-definition"
            )
        elif any(v["state"] != "resolved-snv" for v in values):
            state = "partially-resolved-definition"
        required_by_locus: dict[tuple[str, int], set[str]] = defaultdict(set)
        for value in values:
            if value["key"] is not None:
                key = value["key"]
                required_by_locus[(key["chrom"], key["pos_grch37"])].add(value["required_allele"])
        if names[(definition["genesymbol"], definition["name"])] > 1 or any(
            len(alleles) > 1 for alleles in required_by_locus.values()
        ):
            state = "conflicting-definition"
        definitions[identity] = {
            "source_definition": dict(definition),
            "state": state,
            "constraints": values,
            "functions": functions[identity],
            "function_state": "missing-function"
            if not functions[identity]
            else "available"
            if len(functions[identity]) == 1
            else "multiple-functions",
            "calling_scope": "M10.2"
            if definition["genesymbol"] in TRACTABLE
            else "outside-tractable-scope",
        }
    return locations, definitions


def _annotations(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": payload["source"],
        "archives": [
            {
                **{k: v for k, v in a.items() if k not in {"tables", "columns"}},
                "table_rows": {n: len(t) for n, t in a["tables"].items()},
            }
            for a in payload["archives"]
        ],
        "variants": next(
            a["tables"]["variants.tsv"]
            for a in payload["archives"]
            if a["filename"] == "variants.zip"
        ),
    }


def assemble(
    cpic: Mapping[str, Any], annotations: Mapping[str, Any], dbsnp: Mapping[str, Any]
) -> dict[str, Any]:
    validate_source(cpic)
    validate_source(annotations)
    _validate_dbsnp(dbsnp, _rsids(cpic))
    saved_annotations = _annotations(annotations)
    locations, definitions = normalize(cpic, saved_annotations["variants"], dbsnp)
    return {
        "schema_version": VERSION,
        "kind": "pgx_reference",
        "build": "GRCh37",
        "strand": "+",
        "cpic": dict(cpic),
        "annotations": saved_annotations,
        "dbsnp": dict(dbsnp),
        "locations": locations,
        "definitions": definitions,
        "sample_calling_implemented": False,
    }


def validate_record(record: Mapping[str, Any]) -> None:
    if (
        type(record.get("schema_version")) is not int
        or record["schema_version"] != VERSION
        or record.get("kind") != "pgx_reference"
        or record.get("build") != "GRCh37"
        or record.get("strand") != "+"
        or record.get("sample_calling_implemented") is not False
    ):
        raise ProcessError("Incompatible PGx reference contract.")
    cpic, annotations, dbsnp = record.get("cpic"), record.get("annotations"), record.get("dbsnp")
    if (
        not isinstance(cpic, dict)
        or not isinstance(annotations, dict)
        or not isinstance(dbsnp, dict)
    ):
        raise ProcessError("PGx reference lacks source snapshots.")
    validate_source(cpic)
    _validate_dbsnp(dbsnp, _rsids(cpic))
    validate_identity(annotations.get("source"), "pharmgkb")
    variants = annotations.get("variants")
    archives = annotations.get("archives")
    if not isinstance(variants, list) or any(
        not isinstance(r, dict)
        or not {"Variant ID", "Variant Name", "Location", "Gene Symbols", "Synonyms"} <= set(r)
        or any(not isinstance(v, str) for v in r.values())
        for r in variants
    ):
        raise ProcessError("Malformed frozen ClinPGx mapping rows.")
    if (
        not isinstance(archives, list)
        or len(archives) != 5
        or {a.get("filename") for a in archives if isinstance(a, dict)}
        != {
            "variants.zip",
            "clinicalVariants.zip",
            "clinicalAnnotations.zip",
            "relationships.zip",
            "drugLabels.zip",
        }
    ):
        raise ProcessError("Incomplete frozen ClinPGx release metadata.")
    for archive in archives:
        validate_archive_metadata(archive)
        if not isinstance(archive.get("table_rows"), dict) or any(
            type(n) is not int or n < 0 for n in archive["table_rows"].values()
        ):
            raise ProcessError("Malformed frozen annotation counters.")
        if set(archive["table_rows"]) != set(MEMBERS[archive["filename"]]):
            raise ProcessError("Frozen annotation table coverage changed.")
    if next(
        a["table_rows"].get("variants.tsv") for a in archives if a["filename"] == "variants.zip"
    ) != len(variants):
        raise ProcessError("Frozen ClinPGx mapping row count disagrees.")
    locations, definitions = normalize(cpic, variants, dbsnp)
    if digest(record.get("locations")) != digest(locations) or digest(
        record.get("definitions")
    ) != digest(definitions):
        raise ProcessError(
            "Frozen PGx definitions/mapping states disagree with their source evidence."
        )


@dataclass(frozen=True)
class Catalog:
    record: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path, *, bind_to_manifest: bool = False) -> Catalog:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                raise ProcessError("PGx reference must be an object.")
            validate_record(record)
            sidecar = postprocess.validate_provenance(
                path,
                expected_step="prepare_pgx_reference",
                expected_transform_version=VERSION,
                actual_rows=len(record["definitions"]),
            )
            if (
                type(sidecar.get("schema_version")) is not int
                or type(sidecar.get("rows")) is not int
                or type(sidecar.get("transform_version")) is not int
                or sidecar.get("params") != {"build": "GRCh37", "strand": "+"}
            ):
                raise ProcessError("Malformed PGx catalog publication contract.")
            inputs = {
                "cpic": record["cpic"]["source"],
                "pharmgkb": record["annotations"]["source"],
                "dbsnp": record["dbsnp"]["provenance"],
            }
            if sidecar["input"]["sha256"] != digest(inputs):
                raise ProcessError("PGx catalog input identities disagree with provenance.")
            if bind_to_manifest:
                for source_id, step in (
                    ("cpic", "parse_cpic_database"),
                    ("pharmgkb", "parse_pharmgkb_annotations"),
                ):
                    expected = postprocess.declared_artifact_provenance(source_id, step)
                    identity = inputs[source_id]
                    if (
                        identity["version"] != expected["source_version"]
                        or identity["license_id"] != expected["license_id"]
                        or digest(identity["files"]) != expected["input"]["sha256"]
                    ):
                        raise ProcessError("PGx catalog is stale for the declared source/license.")
                for name, proof in inputs["dbsnp"].items():
                    expected = postprocess.declared_artifact_provenance(
                        "dbsnp_b157_grch37",
                        proof["step"],
                        output_param="unresolvable_output"
                        if name == "rsid_unresolvable.parquet"
                        else "output",
                        output_name=name,
                    )
                    if {k: proof.get(k) for k in expected} != expected:
                        raise ProcessError("PGx catalog is stale for the declared dbSNP source.")
            return cls(record)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProcessError(f"Cannot validate PGx catalog {path.name}: {exc}") from exc

    @classmethod
    def default(cls) -> Catalog:
        return cls.load(
            paths.references_dir() / "cpic" / "pgx_reference.json", bind_to_manifest=True
        )

    def inspect(
        self, *, gene: str | None = None, allele: str | None = None, diplotype: str | None = None
    ) -> dict[str, Any]:
        if (allele is not None or diplotype is not None) and gene is None:
            raise ProcessError("Allele/diplotype inspection requires --gene.")
        tables = self.record["cpic"]["tables"]
        genes = {g["symbol"]: g for g in tables["gene"]}
        if gene is not None and gene not in genes:
            raise ProcessError("Gene is absent from this CPIC release.")
        selected = [
            d
            for d in self.record["definitions"].values()
            if gene is None or d["source_definition"]["genesymbol"] == gene
        ]
        selected_locations = [
            location
            for location in self.record["locations"].values()
            if gene is None or location["source_location"]["genesymbol"] == gene
        ]
        result: dict[str, Any] = {
            "schema_version": VERSION,
            "build": "GRCh37",
            "strand": "+",
            "sample_calling_implemented": False,
            "sources": {
                "cpic": self.record["cpic"]["source"],
                "pharmgkb": self.record["annotations"]["source"],
                "archives": self.record["annotations"]["archives"],
            },
            "counts": {
                "scope": gene if gene is not None else "all-source-genes",
                "genes": 1 if gene is not None else len(genes),
                "definitions": len(selected),
                "definition_states": dict(Counter(d["state"] for d in selected)),
                "locations": len(selected_locations),
                "location_states": dict(
                    Counter(location["state"] for location in selected_locations)
                ),
            },
            "tractable_genes": list(TRACTABLE),
            "limitations": [
                "Reference definition completeness is not array coverage or a sample call.",
                "Unlisted/no-call markers cannot establish a reference allele.",
                "Structural/CNV alleles and CYP2D6 are not callable from this assay.",
                "Reference constraints retain sparse source semantics; "
                "do not fill unspecified bases silently.",
            ],
        }
        if gene is None:
            result["counts"]["diplotype_rows"] = len(tables["gene_result_diplotype"])
            result["genes"] = sorted(genes)
            return result
        result["gene"] = genes[gene]
        result["definitions"] = [
            d for d in selected if allele is None or d["source_definition"]["name"] == allele
        ]
        result["definition_status"] = "available" if result["definitions"] else "not-defined"
        results = {r["id"]: r for r in tables["gene_result"] if r["genesymbol"] == gene}
        lookups = {r["id"]: r for r in tables["gene_result_lookup"] if r["phenotypeid"] in results}
        result["phenotypes"] = list(results.values())
        result["function_lookups"] = list(lookups.values())
        result["phenotype_mapping_status"] = "available" if lookups else "not-provided"
        if len(result["definitions"]) > 1 and allele is not None:
            result["definition_status"] = "conflicting-definitions"
        citations = {
            citation.strip('"')
            for definition in result["definitions"]
            for function in definition["functions"]
            for citation in (function["citations"] or "").strip("{}").split(",")
            if citation
        }
        gene_guidelines = {p["guidelineid"] for p in tables["pair"] if p["genesymbol"] == gene}
        result["guidelines"] = [g for g in tables["guideline"] if g["id"] in gene_guidelines]
        result["publications"] = [
            p
            for p in tables["publication"]
            if p["pmid"] in citations or p.get("guidelineid") in gene_guidelines
        ]
        mappings = [
            m for m in tables["gene_result_diplotype"] if m["functionphenotypeid"] in lookups
        ]
        result["diplotype_rows"] = len(mappings)
        result["counts"]["diplotype_rows"] = len(mappings)
        if diplotype is not None:
            labels = diplotype.split("/")
            if any(not label for label in labels):
                raise ProcessError("Diplotype must name nonempty reference alleles.")
            wanted = dict(Counter(labels))
            matches = [m for m in mappings if object_field(m["diplotypekey"])[gene] == wanted]
            result["diplotype_mappings"] = [
                {
                    "source_mapping": m,
                    "function_lookup": lookups[m["functionphenotypeid"]],
                    "phenotype": results[lookups[m["functionphenotypeid"]]["phenotypeid"]],
                }
                for m in matches
            ]
            result["mapping_status"] = (
                "missing-mapping"
                if not matches
                else "available"
                if len({lookups[m["functionphenotypeid"]]["phenotypeid"] for m in matches}) == 1
                else "conflicting-mappings"
            )
        return result


def prepare(root: Path | None = None, *, bind_to_manifest: bool = True) -> tuple[Path, str]:
    from genetics.pgx.locking import publication_lock

    directory = root or paths.references_dir()
    output = postprocess._inside(directory / "cpic", "pgx_reference.json", label="output")
    if not output.parent.is_dir():
        raise ProcessError("CPIC references are absent; run refs fetch --only cpic --opt-in cpic.")
    with publication_lock(output):
        return _prepare(directory, bind_to_manifest=bind_to_manifest)


def _prepare(directory: Path, *, bind_to_manifest: bool) -> tuple[Path, str]:
    cpic_path = directory / "cpic" / "pgx_cpic.json"
    annotation_path = directory / "pharmgkb" / "pgx_annotations.json"
    output = postprocess._inside(directory / "cpic", "pgx_reference.json", label="output")
    cpic = load_source(
        cpic_path,
        expected=postprocess.declared_artifact_provenance("cpic", "parse_cpic_database")
        if bind_to_manifest
        else None,
    )
    annotations = load_source(
        annotation_path,
        expected=postprocess.declared_artifact_provenance("pharmgkb", "parse_pharmgkb_annotations")
        if bind_to_manifest
        else None,
    )
    dbsnp = _dbsnp(directory, _rsids(cpic), bind=bind_to_manifest)
    inputs = {
        "cpic": cpic["source"],
        "pharmgkb": annotations["source"],
        "dbsnp": dbsnp["provenance"],
    }
    stamp = digest(inputs)
    if output.is_file():
        try:
            catalog = Catalog.load(output, bind_to_manifest=bind_to_manifest)
            existing = {
                "cpic": catalog.record["cpic"]["source"],
                "pharmgkb": catalog.record["annotations"]["source"],
                "dbsnp": catalog.record["dbsnp"]["provenance"],
            }
            if digest(existing) == stamp:
                return output, "already-present"
        except ProcessError:
            pass
    record = assemble(cpic, annotations, dbsnp)
    # The record owns independent copies after JSON publication. Default reading
    # verifies declared input hashes without depending on caches still being present.
    postprocess._write_json_atomic(output, record)
    postprocess._write_provenance(
        output,
        {
            "schema_version": 1,
            "step": "prepare_pgx_reference",
            "transform_version": VERSION,
            "input": {"filename": "PGx complete public reference set", "sha256": stamp},
            "params": {"build": "GRCh37", "strand": "+"},
            "output": output.name,
        },
        len(record["definitions"]),
    )
    Catalog.load(output, bind_to_manifest=bind_to_manifest)
    return output, "created"
