"""Known-coordinate anchors for the build sanity check (part of roadmap M1.5).

The idea is simple and strong: pick rsIDs whose GRCh37 *and* GRCh38 coordinates are known,
and look at where the file puts them. A file that places them at their GRCh38 positions is
on build 38 no matter what its header says -- and a mislabelled build is the failure mode
that produces confident cards about entirely the wrong genes.

**The committed table is empty, deliberately.** Filling it by hand would mean writing
coordinates from memory.  The reference fetcher instead derives an uncommitted JSON
artifact by pairing ClinVar's GRCh37 and GRCh38 rows, and :func:`default_anchors` loads it
when present.  A missing artifact leaves the check indeterminate; a malformed artifact
fails loudly rather than silently disabling the strongest build check.

Until then the mechanism is tested with injected anchors and the real build check rests on
the two layers that need no external data: the header assertion (M1.4) and the
coordinate-bounds check in :mod:`genetics.ingest.normalize`.

The gate below matters even once the table is populated: only anchors marked ``verified``
can trigger a hard build failure. An unverified coordinate can then only ever fail to
match, which reads as "indeterminate" -- a wrong anchor loses information rather than
manufacturing a false alarm.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from genetics.ingest.schema import Chrom

MIN_ANCHORS_FOR_VERDICT = 2
"""One matching anchor is a coincidence waiting to happen -- two positions can collide
across builds. Two concordant anchors is enough to be a fact about the file."""


@dataclass(frozen=True)
class BuildAnchor:
    """One marker whose coordinates are known on both builds."""

    rsid: str
    chrom: Chrom
    pos_grch37: int
    pos_grch38: int
    gene: str
    source: str | None = None
    """Where the coordinates were taken from -- a dbSNP build, a ClinVar release. Required
    for :attr:`verified` to mean anything."""

    @property
    def verified(self) -> bool:
        """True only when the coordinates came from a fetched reference, not from memory.

        Only verified anchors may fail a run. See the module docstring.
        """
        return self.source is not None


ANCHORS: tuple[BuildAnchor, ...] = ()
"""Injected-test/committed fallback. Real anchors are fetched and remain uncommitted."""


class AnchorError(ValueError):
    """A fetched anchor artifact is present but cannot be trusted."""


def load_anchors(
    path: Path,
    *,
    expected_count: int | None = None,
    expected_provenance: Mapping[str, Any] | None = None,
) -> tuple[BuildAnchor, ...]:
    """Load the versioned JSON written by ``extract_build_anchors``."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise AnchorError(f"{path.name}: unsupported build-anchor schema")
        rows = raw.get("anchors")
        if not isinstance(rows, list) or not rows:
            raise AnchorError(f"{path.name}: 'anchors' must be a non-empty list")
        if expected_count is not None and len(rows) != expected_count:
            raise AnchorError(
                f"{path.name}: contains {len(rows)} anchors; expected {expected_count}"
            )
        anchors: list[BuildAnchor] = []
        seen: set[str] = set()
        for number, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise AnchorError(f"{path.name}: anchor #{number} must be an object")
            rsid = row["rsid"]
            chrom = row["chrom"]
            gene = row["gene"]
            source = row["source"]
            if not isinstance(rsid, str):
                raise AnchorError(f"{path.name}: anchor #{number} rsID must be a string")
            if not isinstance(chrom, str):
                raise AnchorError(f"{path.name}: anchor #{number} chromosome must be a string")
            if not isinstance(gene, str) or not gene:
                raise AnchorError(f"{path.name}: anchor #{number} gene must be a string")
            if not isinstance(source, str) or not source:
                raise AnchorError(f"{path.name}: anchor #{number} source must be a string")
            if re.fullmatch(r"rs[1-9][0-9]*", rsid) is None:
                raise AnchorError(f"{path.name}: anchor #{number} has invalid rsID")
            if rsid in seen:
                raise AnchorError(f"{path.name}: duplicate anchor {rsid}")
            seen.add(rsid)
            anchors.append(
                BuildAnchor(
                    rsid=rsid,
                    chrom=Chrom(chrom),
                    pos_grch37=int(row["pos_grch37"]),
                    pos_grch38=int(row["pos_grch38"]),
                    gene=gene,
                    source=source,
                )
            )
    except AnchorError:
        raise
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AnchorError(f"{path}: malformed build-anchor artifact ({exc})") from exc
    if any(anchor.pos_grch37 <= 0 or anchor.pos_grch38 <= 0 for anchor in anchors):
        raise AnchorError(f"{path.name}: anchor coordinates must be positive")
    if any(anchor.pos_grch37 == anchor.pos_grch38 for anchor in anchors):
        raise AnchorError(f"{path.name}: every anchor must distinguish GRCh37 from GRCh38")
    if any(not anchor.source for anchor in anchors):
        raise AnchorError(f"{path.name}: every anchor requires source provenance")
    try:
        from genetics.refs.postprocess import ProcessError, get, validate_provenance

        validate_provenance(
            output=path,
            expected=expected_provenance,
            expected_step="extract_build_anchors",
            expected_transform_version=get("extract_build_anchors").transform_version,
        )
    except ProcessError as exc:
        raise AnchorError(str(exc)) from exc
    return tuple(anchors)


def default_anchors() -> tuple[BuildAnchor, ...]:
    """Load the fetched ClinVar artifact, or use the empty pre-fetch fallback."""
    from genetics.paths import references_dir
    from genetics.refs.postprocess import (
        ProcessError,
        declared_artifact_provenance,
    )

    path = references_dir() / "clinvar_grch37" / "build_anchors.json"
    if not path.is_file():
        return ANCHORS
    try:
        expected = declared_artifact_provenance(
            "clinvar_grch37",
            "extract_build_anchors",
            output_name=path.name,
        )
    except ProcessError as exc:
        raise AnchorError(str(exc)) from exc
    return load_anchors(path, expected_count=200, expected_provenance=expected)
