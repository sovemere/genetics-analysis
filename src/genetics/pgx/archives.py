"""Validate ClinPGx ZIPs and ingest tables directly; never extract archive paths."""

from __future__ import annotations

import csv
import io
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from genetics.refs.postprocess import ProcessError

HEADERS = {
    "clinical_annotations.tsv": (
        "Clinical Annotation ID",
        "Variant/Haplotypes",
        "Gene",
        "Level of Evidence",
    ),
    "clinical_ann_alleles.tsv": (
        "Clinical Annotation ID",
        "Genotype/Allele",
        "Annotation Text",
        "Allele Function",
    ),
    "clinical_ann_history.tsv": ("Clinical Annotation ID", "Date (YYYY-MM-DD)", "Type", "Comment"),
    "clinical_ann_evidence.tsv": ("Clinical Annotation ID", "Evidence ID", "Evidence Type", "PMID"),
    "variants.tsv": ("Variant ID", "Variant Name", "Gene Symbols", "Location", "Synonyms"),
    "clinicalVariants.tsv": ("variant", "gene", "type", "level of evidence"),
    "drugLabels.tsv": ("PharmGKB ID", "Name", "Source", "Genes", "Variants/Haplotypes"),
    "drugLabels.byGene.tsv": ("Gene ID", "Gene Symbol", "Label IDs", "Label Names"),
    "relationships.tsv": ("Entity1_id", "Entity2_id", "Entity1_type", "Entity2_type", "PMIDs"),
}
MEMBERS = {
    "clinicalAnnotations.zip": (
        "clinical_annotations.tsv",
        "clinical_ann_alleles.tsv",
        "clinical_ann_history.tsv",
        "clinical_ann_evidence.tsv",
    ),
    "variants.zip": ("variants.tsv",),
    "clinicalVariants.zip": ("clinicalVariants.tsv",),
    "drugLabels.zip": ("drugLabels.tsv", "drugLabels.byGene.tsv"),
    "relationships.zip": ("relationships.tsv",),
}


def read_archive(path: Path) -> dict[str, Any]:
    if path.name not in MEMBERS:
        raise ProcessError("Unexpected ClinPGx archive name.")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names: set[str] = set()
            if len(members) > 128 or sum(m.file_size for m in members) > 512 * 1024**2:
                raise ProcessError("ClinPGx archive exceeds its declared ingestion scope.")
            for member in members:
                name = member.filename
                parts = PurePosixPath(name).parts
                if (
                    not name
                    or "\\" in name
                    or ":" in name
                    or "\x00" in name
                    or name.startswith("/")
                    or any(p in {".", ".."} for p in name.split("/"))
                    or len(parts) != 1
                    or member.is_dir()
                    or name.casefold() in names
                    or stat.S_ISLNK(member.external_attr >> 16)
                    or member.flag_bits & 1
                    or re.match(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name)
                    or name.endswith((".", " "))
                ):
                    raise ProcessError("Unsafe or duplicate ClinPGx archive member.")
                names.add(name.casefold())
            # CRC-check every member, including ignored documentation, without writing it.
            if archive.testzip() is not None:
                raise ProcessError("ClinPGx archive CRC mismatch.")
            actual = {m.filename for m in members}
            dates = [n for n in actual if re.fullmatch(r"CREATED_\d{4}-\d{2}-\d{2}\.txt", n)]
            if len(dates) != 1 or "LICENSE.txt" not in actual:
                raise ProcessError("ClinPGx archive lacks a unique release date or license.")
            allowed = {*MEMBERS[path.name], "LICENSE.txt", "README.pdf", "VERSIONS.txt", dates[0]}
            if not set(MEMBERS[path.name]) <= actual or actual - allowed:
                raise ProcessError("ClinPGx archive table/member coverage changed.")
            notice = archive.read("LICENSE.txt").decode("utf-8-sig")
            ids = [
                identifier
                for identifier, url in (
                    ("CC-BY-SA-4.0", "creativecommons.org/licenses/by-sa/4.0/"),
                    ("CC-BY-NC-SA-4.0", "creativecommons.org/licenses/by-nc-sa/4.0/"),
                )
                if url in notice
            ]
            if len(ids) != 1:
                raise ProcessError("Unknown or conflicting ClinPGx archive license.")
            tables: dict[str, list[dict[str, str]]] = {}
            columns: dict[str, list[str]] = {}
            for name in MEMBERS[path.name]:
                text = archive.read(name).decode("utf-8-sig")
                reader = csv.reader(io.StringIO(text, newline=""), delimiter="\t")
                header = next(reader, [])
                if (
                    not set(HEADERS[name]) <= set(header)
                    or len(set(header)) != len(header)
                    or any(not c for c in header)
                ):
                    raise ProcessError(f"ClinPGx {name}: missing or duplicate columns.")
                rows = []
                for values in reader:
                    if len(values) != len(header):
                        raise ProcessError(f"ClinPGx {name}: column count mismatch.")
                    rows.append(dict(zip(header, values, strict=True)))
                tables[name] = rows
                columns[name] = header
            return {
                "filename": path.name,
                "created": dates[0][8:-4],
                "release_notice": archive.read(dates[0]).decode("utf-8-sig"),
                "license_id": ids[0],
                "license_notice": notice,
                "versions": archive.read("VERSIONS.txt").decode("utf-8-sig")
                if "VERSIONS.txt" in actual
                else None,
                "columns": columns,
                "tables": tables,
            }
    except ProcessError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, UnicodeError, csv.Error) as exc:
        raise ProcessError(f"Cannot read ClinPGx archive {path.name}.") from exc
