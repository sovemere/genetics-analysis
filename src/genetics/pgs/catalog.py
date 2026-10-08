"""Authoritative per-score metadata, read without extracting a tar archive.

Only the metadata CSV grants the score's terms. Header absence, collection-level
permission and a familiar substring in an unfamiliar licence grant nothing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tarfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from genetics.refs import licenses

ID_COLUMN = "Polygenic Score (PGS) ID"
TERMS_COLUMN = "License/Terms of Use"
MEMBER_NAME = "pgs_all_metadata_scores.csv"


class PgsError(ValueError):
    """A public score or its metadata cannot be interpreted reliably."""


def check_id(value: str) -> str:
    if not re.fullmatch(r"PGS[0-9]{6}", value):
        raise PgsError("Expected a PGS identifier in the form PGS followed by six digits.")
    return value


def fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                count += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise PgsError("Cannot read the public PGS source.") from exc
    return {"filename": path.name, "sha256": digest.hexdigest(), "size_bytes": count}


@dataclass(frozen=True)
class ScoreMetadata:
    pgs_id: str
    records: tuple[Mapping[str, str], ...]

    @property
    def license(self) -> licenses.PgsTerms:
        if len(self.records) != 1:
            return licenses.PgsTerms("ambiguous", None, "Multiple metadata rows for this score.")
        return licenses.classify_pgs_terms(self.records[0][TERMS_COLUMN])

    def to_json(self) -> dict[str, Any]:
        return {
            "pgs_id": self.pgs_id,
            "metadata_rows": [dict(row) for row in self.records],
            "license": self.license.to_json(),
        }


@dataclass(frozen=True)
class Catalog:
    scores: Mapping[str, ScoreMetadata]
    source: Mapping[str, Any]
    member: str

    def get(self, pgs_id: str) -> ScoreMetadata:
        check_id(pgs_id)
        found = self.scores.get(pgs_id)
        if found is None:
            raise PgsError("The score has no authoritative metadata row in this release.")
        return found

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "pgs_score_licenses",
            "schema_version": 1,
            "source": dict(self.source),
            "member": self.member,
            "scores": {key: value.to_json() for key, value in sorted(self.scores.items())},
        }

    @classmethod
    def from_archive(cls, path: Path) -> Catalog:
        before = fingerprint(path)
        try:
            with tarfile.open(path, "r:gz") as archive:
                members = [
                    m for m in archive.getmembers() if PurePosixPath(m.name).name == MEMBER_NAME
                ]
                if len(members) != 1 or not members[0].isfile():
                    raise PgsError(
                        "Expected exactly one regular scores CSV in the metadata archive."
                    )
                member = members[0]
                stream = archive.extractfile(member)
                if stream is None:
                    raise PgsError("Cannot read the scores CSV in the metadata archive.")
                with io.TextIOWrapper(stream, encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle, strict=True)
                    columns = reader.fieldnames or []
                    if (
                        len(columns) != len(set(columns))
                        or any(not column for column in columns)
                        or ID_COLUMN not in columns
                        or TERMS_COLUMN not in columns
                    ):
                        raise PgsError(
                            "Metadata must have unique columns including score ID and terms."
                        )
                    grouped: dict[str, list[Mapping[str, str]]] = {}
                    for row in reader:
                        if None in row or any(value is None for value in row.values()):
                            raise PgsError("A metadata row has an incorrect field count.")
                        checked = {key: str(value) for key, value in row.items()}
                        pgs_id = check_id(checked[ID_COLUMN])
                        grouped.setdefault(pgs_id, []).append(checked)
                if not grouped:
                    raise PgsError("The scores metadata CSV is empty.")
        except (OSError, EOFError, UnicodeError, csv.Error, tarfile.TarError, zlib.error) as exc:
            raise PgsError("Cannot decode the PGS metadata archive.") from exc
        if fingerprint(path) != before:
            raise PgsError("The metadata source changed while it was being parsed.")
        return cls(
            {key: ScoreMetadata(key, tuple(rows)) for key, rows in grouped.items()},
            before,
            member.name,
        )

    @classmethod
    def load(cls, path: Path, *, expected_provenance: Mapping[str, Any] | None = None) -> Catalog:
        from genetics.refs.postprocess import ProcessError, validate_provenance

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(raw, dict)
                or raw.get("kind") != "pgs_score_licenses"
                or type(raw.get("schema_version")) is not int
                or raw["schema_version"] != 1
                or not isinstance(raw.get("scores"), dict)
                or not raw["scores"]
                or not isinstance(raw.get("source"), dict)
                or not isinstance(raw.get("member"), str)
                or PurePosixPath(raw["member"]).name != MEMBER_NAME
            ):
                raise PgsError("Malformed PGS metadata index.")
            source = raw["source"]
            if (
                not isinstance(source.get("filename"), str)
                or not isinstance(source.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
                or type(source.get("size_bytes")) is not int
                or source["size_bytes"] <= 0
            ):
                raise PgsError("Malformed PGS metadata source identity.")
            scores: dict[str, ScoreMetadata] = {}
            for key, value in raw["scores"].items():
                check_id(key)
                if not isinstance(value, dict) or value.get("pgs_id") != key:
                    raise PgsError("Malformed score identity in metadata index.")
                rows = value.get("metadata_rows")
                if not isinstance(rows, list) or not rows:
                    raise PgsError("Missing metadata rows in index.")
                for row in rows:
                    if (
                        not isinstance(row, dict)
                        or not all(
                            isinstance(k, str) and isinstance(v, str) for k, v in row.items()
                        )
                        or row.get(ID_COLUMN) != key
                        or TERMS_COLUMN not in row
                    ):
                        raise PgsError("Malformed authoritative metadata row in index.")
                score = ScoreMetadata(key, tuple(rows))
                if value.get("license") != score.license.to_json():
                    raise PgsError("Metadata licence classification disagrees with its raw terms.")
                scores[key] = score
            provenance = validate_provenance(
                path,
                expected=expected_provenance,
                expected_step="parse_pgs_score_licenses",
                expected_transform_version=1,
                actual_rows=len(scores),
            )
            if provenance["input"] != {"filename": source["filename"], "sha256": source["sha256"]}:
                raise PgsError("Metadata source identity disagrees with artifact provenance.")
            return cls(scores, source, raw["member"])
        except (
            OSError,
            UnicodeError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
            ProcessError,
        ) as exc:
            raise PgsError("Cannot validate the PGS metadata index.") from exc

    @classmethod
    def default(cls) -> Catalog:
        from genetics.paths import references_dir
        from genetics.refs.postprocess import declared_artifact_provenance

        expected = declared_artifact_provenance(
            "pgs_catalog_metadata",
            "parse_pgs_score_licenses",
            output_name="pgs_score_licenses.json",
        )
        return cls.load(
            references_dir() / "pgs_catalog_metadata" / "pgs_score_licenses.json",
            expected_provenance=expected,
        )
