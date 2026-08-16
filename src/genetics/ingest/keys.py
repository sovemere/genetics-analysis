"""Variant keying and rsID resolution (roadmap M1.7, AGENTS.md section 2).

**rsIDs are not stable identifiers.** dbSNP merges records when two submitted variants
turn out to be the same, and the loser is retired: it still appears in an export produced
before the merge, but it is absent from any reference built after. A card keyed on the
retired ID silently matches nothing, and "no result" is indistinguishable from "no
variant" unless something knows about the merge. That is what :class:`MergeTable` is for.

So the primary key is positional -- ``(chrom, pos_grch37, alleles)`` -- and the rsID is a
secondary index. Position plus alleles is what reference data actually agrees on.

Two shapes, and the distinction matters:

* :class:`LocusKey` -- ``(chrom, pos)``. What a *sample* offers. An export records the two
  alleles observed, not the full allele set at the locus, so a homozygote reveals only one
  of them and the sample side cannot construct a complete allele key.
* :class:`VariantKey` -- ``(chrom, pos, alleles)``. What a *card or reference row* offers,
  where the allele set is known.

Matching therefore joins on locus and checks allele compatibility separately. That
separation is also where M3.2's strand check belongs: the vendor claims forward-strand
calls, but an A/T or C/G site is its own complement, so a strand flip there is invisible
to any comparison of the letters alone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl

from genetics.ingest.schema import Chrom, GenotypeTable


@dataclass(frozen=True, order=True)
class LocusKey:
    """A genomic position. What a sample can offer as a join key."""

    chrom: Chrom
    pos_grch37: int

    def __str__(self) -> str:
        return f"{self.chrom.value}:{self.pos_grch37}"


@dataclass(frozen=True)
class VariantKey:
    """A position plus its allele set. The primary key for reference data and cards.

    Alleles are sorted at construction, for the same reason genotypes are sorted at
    ingest: ``A/G`` and ``G/A`` are one variant, and normalising once here means no
    consumer has to remember that.
    """

    chrom: Chrom
    pos_grch37: int
    alleles: tuple[str, ...]

    def __init__(self, chrom: Chrom, pos_grch37: int, alleles: Iterable[str]) -> None:
        normalized = tuple(sorted({a.strip().upper() for a in alleles}))
        if not normalized:
            raise ValueError(f"{chrom.value}:{pos_grch37}: a variant key needs alleles")
        object.__setattr__(self, "chrom", chrom)
        object.__setattr__(self, "pos_grch37", pos_grch37)
        object.__setattr__(self, "alleles", normalized)

    @property
    def locus(self) -> LocusKey:
        return LocusKey(self.chrom, self.pos_grch37)

    def __str__(self) -> str:
        return f"{self.chrom.value}:{self.pos_grch37}:{'/'.join(self.alleles)}"


class RsidResolutionStatus(StrEnum):
    CURRENT = "current"
    NO_CURRENT_TARGET = "no-current-target"
    MULTIPLE_CURRENT_TARGETS = "multiple-current-targets"
    CYCLE = "cycle"


@dataclass(frozen=True)
class RsidResolution:
    queried_rsid: str
    status: RsidResolutionStatus
    current_rsid: str | None
    targets: tuple[str, ...] = ()


class ReferenceDataError(ValueError):
    """A fetched dbSNP merge artifact is present but cannot be trusted.

    Distinct from :class:`UnresolvableRsidError`, which is a fact *about an rsID*. This is
    a fact about the local reference setup -- absent companion artifact, stale provenance,
    schema drift -- and a caller that catches it can say so instead of reporting a matching
    failure. A ``ValueError`` subclass so existing handlers keep working.
    """


class UnresolvableRsidError(ValueError):
    """dbSNP explicitly says an rsID has no unique current target."""

    def __init__(self, resolution: RsidResolution) -> None:
        self.resolution = resolution
        super().__init__(f"{resolution.queried_rsid}: rsID resolution is {resolution.status.value}")


class MergeTable:
    """Retired rsID to current rsID, from dbSNP's merge records.

    Chains are followed transitively -- dbSNP merges in sequence, so a retired ID can
    point at another retired ID -- with a visited set guarding against a cycle. A cycle
    should not exist in a well-formed dbSNP release, but "should not exist in the input"
    is a poor reason for an infinite loop in a parser, and this table is loaded from a
    fetched file that no one in this project controls.

    The empty table is the identity, which is the correct behaviour before M2 fetches
    dbSNP: unknown rsIDs resolve to themselves rather than to nothing.
    """

    def __init__(
        self,
        merges: Mapping[str, str] | None = None,
        unresolved: Mapping[str, tuple[RsidResolutionStatus, tuple[str, ...]]] | None = None,
    ) -> None:
        self._merges = dict(merges or {})
        self._unresolved = dict(unresolved or {})

    def __len__(self) -> int:
        return len(self._merges) + len(self._unresolved)

    @classmethod
    def empty(cls) -> MergeTable:
        return cls()

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, str]]) -> MergeTable:
        """Build from ``(retired_rsid, current_rsid)`` pairs."""
        return cls({retired: current for retired, current in pairs})

    @classmethod
    def from_parquet(
        cls,
        path: Path,
        *,
        rsids: Iterable[str],
        unresolved_path: Path | None = None,
        require_provenance: bool = True,
        provenance_contracts: tuple[Mapping[str, Any], Mapping[str, Any]] | None = None,
    ) -> MergeTable:
        """Load the artifact written by ``extract_rsid_merge_table``.

        Loading is query-scoped: each scan selects only requested retired IDs, then scans
        again for the next link in any chain. This keeps a tens-of-millions-row artifact
        out of Python memory. Duplicate rows are refused, and zero/multiple-target records
        are loaded from the companion artifact as explicit unresolved states.
        """
        expected = {"retired_rsid": pl.String, "current_rsid": pl.String}
        if dict(pl.read_parquet_schema(path)) != expected:
            raise ReferenceDataError(
                f"{path.name}: merge table schema is {dict(pl.read_parquet_schema(path))}, "
                f"expected {expected}"
            )
        unresolved_path = unresolved_path or path.with_name("rsid_unresolvable.parquet")
        unresolved_schema = {
            "retired_rsid": pl.String,
            "status": pl.String,
            "targets": pl.List(pl.String),
        }
        if dict(pl.read_parquet_schema(unresolved_path)) != unresolved_schema:
            raise ReferenceDataError(
                f"{unresolved_path.name}: incompatible unresolvable table schema"
            )
        if provenance_contracts is not None and not require_provenance:
            raise ReferenceDataError("provenance_contracts require provenance validation")
        if require_provenance:
            from genetics.refs.postprocess import ProcessError, get, validate_provenance

            try:
                expected_merge = provenance_contracts[0] if provenance_contracts else None
                expected_unresolved = provenance_contracts[1] if provenance_contracts else None
                merge_provenance = validate_provenance(
                    path,
                    expected=expected_merge,
                    expected_step="extract_rsid_merge_table",
                    expected_transform_version=get("extract_rsid_merge_table").transform_version,
                )
                unresolved_provenance = validate_provenance(
                    unresolved_path,
                    expected=expected_unresolved,
                    expected_step="extract_rsid_merge_table",
                    expected_transform_version=get("extract_rsid_merge_table").transform_version,
                )
            except ProcessError as exc:
                raise ReferenceDataError(str(exc)) from exc
            shared_keys = ("schema_version", "step", "transform_version", "input", "params")
            if any(merge_provenance[key] != unresolved_provenance[key] for key in shared_keys):
                raise ReferenceDataError(
                    f"{path.name} and {unresolved_path.name} were not derived by the same transform"
                )

        merges: dict[str, str] = {}
        unresolved: dict[str, tuple[RsidResolutionStatus, tuple[str, ...]]] = {}
        frontier = set(rsids)
        visited: set[str] = set()
        while frontier:
            query = sorted(frontier - visited)
            if not query:
                break
            visited.update(query)
            frame = pl.scan_parquet(path).filter(pl.col("retired_rsid").is_in(query)).collect()
            ambiguous = (
                pl.scan_parquet(unresolved_path)
                .filter(pl.col("retired_rsid").is_in(query))
                .collect()
            )
            if frame.get_column("retired_rsid").n_unique() != frame.height:
                raise ReferenceDataError(f"{path.name}: queried retired rsID has multiple rows")
            if ambiguous.get_column("retired_rsid").n_unique() != ambiguous.height:
                raise ReferenceDataError(
                    f"{unresolved_path.name}: queried retired rsID has multiple rows"
                )
            overlap = set(frame.get_column("retired_rsid")) & set(
                ambiguous.get_column("retired_rsid")
            )
            if overlap:
                raise ReferenceDataError(
                    f"rsID(s) occur in both merge artifacts: {sorted(overlap)}"
                )
            next_frontier: set[str] = set()
            for retired, current in frame.iter_rows():
                if (
                    not isinstance(retired, str)
                    or not isinstance(current, str)
                    or not retired.startswith("rs")
                    or not retired[2:].isdigit()
                    or not current.startswith("rs")
                    or not current[2:].isdigit()
                    or retired == current
                ):
                    raise ReferenceDataError(f"{path.name}: malformed or self-merge row")
                merges[retired] = current
                next_frontier.add(current)
            for retired, status_text, targets in ambiguous.iter_rows():
                try:
                    status = RsidResolutionStatus(status_text)
                except ValueError as exc:
                    raise ReferenceDataError(
                        f"{unresolved_path.name}: invalid status {status_text!r}"
                    ) from exc
                if status not in {
                    RsidResolutionStatus.NO_CURRENT_TARGET,
                    RsidResolutionStatus.MULTIPLE_CURRENT_TARGETS,
                }:
                    raise ReferenceDataError(
                        f"{unresolved_path.name}: invalid unresolved status {status.value!r}"
                    )
                if (
                    not isinstance(retired, str)
                    or not retired.startswith("rs")
                    or not retired[2:].isdigit()
                    or not isinstance(targets, list)
                    or any(
                        not isinstance(target, str)
                        or not target.startswith("rs")
                        or not target[2:].isdigit()
                        for target in targets
                    )
                    or (status is RsidResolutionStatus.NO_CURRENT_TARGET and targets)
                    or (
                        status is RsidResolutionStatus.MULTIPLE_CURRENT_TARGETS and len(targets) < 2
                    )
                ):
                    raise ReferenceDataError(
                        f"{unresolved_path.name}: malformed unresolved row for {retired!r}"
                    )
                unresolved[retired] = (status, tuple(targets))
            frontier = next_frontier
        return cls(merges, unresolved)

    @classmethod
    def default(cls, rsids: Iterable[str]) -> MergeTable:
        """Load fetched dbSNP merges when available; identity before reference setup."""
        from genetics.paths import references_dir
        from genetics.refs.postprocess import ProcessError, declared_artifact_provenance

        path = references_dir() / "dbsnp_b157_grch37" / "rsid_merges.parquet"
        unresolved = path.with_name("rsid_unresolvable.parquet")
        if not path.is_file():
            return cls.empty()
        if not unresolved.is_file():
            raise ReferenceDataError(
                f"{unresolved.name} is missing; refetch dbSNP before resolving rsIDs"
            )
        try:
            contracts = (
                declared_artifact_provenance(
                    "dbsnp_b157_grch37",
                    "extract_rsid_merge_table",
                    output_name=path.name,
                ),
                declared_artifact_provenance(
                    "dbsnp_b157_grch37",
                    "extract_rsid_merge_table",
                    output_param="unresolvable_output",
                    output_name=unresolved.name,
                ),
            )
        except ProcessError as exc:
            raise ReferenceDataError(str(exc)) from exc
        return cls.from_parquet(
            path,
            rsids=rsids,
            unresolved_path=unresolved,
            provenance_contracts=contracts,
        )

    def resolve_result(self, rsid: str) -> RsidResolution:
        """Resolve without erasing explicit ambiguity or corrupt merge cycles."""
        seen = {rsid}
        current = rsid
        while True:
            ambiguous = self._unresolved.get(current)
            if ambiguous is not None:
                status, targets = ambiguous
                return RsidResolution(rsid, status, None, targets)
            nxt = self._merges.get(current)
            if nxt is None:
                return RsidResolution(rsid, RsidResolutionStatus.CURRENT, current)
            if nxt in seen:
                return RsidResolution(rsid, RsidResolutionStatus.CYCLE, None)
            seen.add(nxt)
            current = nxt

    def resolve(self, rsid: str) -> str:
        """Follow the merge chain to the current rsID.

        Returns ``rsid`` unchanged when dbSNP has no merge record for it. Explicit
        zero/multiple-target records and cycles raise :class:`UnresolvableRsidError`;
        returning the original ID for either would falsely turn ambiguity into identity.
        """
        resolution = self.resolve_result(rsid)
        if resolution.current_rsid is None:
            raise UnresolvableRsidError(resolution)
        return resolution.current_rsid

    def resolve_all(self, rsids: Iterable[str]) -> dict[str, str]:
        """Resolve each rsID, raising on any dbSNP cannot resolve to a single current ID."""
        return {rsid: self.resolve(rsid) for rsid in rsids}

    def resolve_all_results(self, rsids: Iterable[str]) -> dict[str, RsidResolution]:
        """Resolve each rsID, reporting rather than raising on the unresolvable ones.

        For a caller processing every row of an export rather than asking about one
        marker: b157 carries tens of thousands of retired IDs with zero or several current
        targets, and one of them appearing in a 677k-row file must not abort the run.
        """
        return {rsid: self.resolve_result(rsid) for rsid in rsids}


def locus_keys(table: GenotypeTable) -> pl.DataFrame:
    """``(chrom, pos_grch37)`` for every row, in table order."""
    return table.frame.select("chrom", "pos_grch37")


def add_current_rsid(table: GenotypeTable, merges: MergeTable) -> pl.DataFrame:
    """Return the frame with a ``rsid_current`` column resolved through ``merges``.

    Added as a *new* column rather than rewriting ``rsid``: the original identifier is
    what the export actually said, and a card citing a retired ID should still be able to
    show that this is the marker it matched. Overwriting would erase the provenance the
    merge table exists to supply.

    The normalized table's own schema is untouched -- this returns a plain frame, so
    :data:`~genetics.ingest.schema.NORMALIZED_SCHEMA` stays the single contract.

    An rsID dbSNP cannot resolve to a single current identifier gets **null**, not its
    original value. This runs over every row of the user's export, so raising would let
    one of b157's ~23k ambiguous retirements abort the whole ingest; but writing the
    original back would state that the retired ID *is* current, which is the false
    identity :meth:`MergeTable.resolve` refuses for exactly this reason. Null is the third
    answer, and it propagates the way M1.1 made no-calls propagate.
    """
    if len(merges) == 0:
        return table.frame.with_columns(pl.col("rsid").alias("rsid_current"))

    mapping = merges.resolve_all_results(table.frame.get_column("rsid").unique().to_list())
    changed: dict[str, str | None] = {
        rsid: resolution.current_rsid
        for rsid, resolution in mapping.items()
        if resolution.current_rsid != rsid
    }
    if not changed:
        return table.frame.with_columns(pl.col("rsid").alias("rsid_current"))

    return table.frame.with_columns(pl.col("rsid").replace(changed).alias("rsid_current"))


def lookup_loci(
    table: GenotypeTable,
    keys: Iterable[LocusKey],
) -> pl.DataFrame:
    """Rows of ``table`` at the given loci.

    A join rather than a Python loop: at 677k rows against a knowledge pack of any size,
    per-key filtering is quadratic in the worst case and a join is not.
    """
    # Materialised once. The two column comprehensions below each consume ``keys``, so a
    # generator -- which the ``Iterable`` annotation invites -- was exhausted by the first
    # and left the second empty, surfacing as a ShapeError about mismatched column heights
    # rather than as anything resembling the actual mistake.
    materialised = list(keys)

    wanted = pl.DataFrame(
        {
            "chrom": [k.chrom.value for k in materialised],
            "pos_grch37": [k.pos_grch37 for k in materialised],
        },
        schema={"chrom": pl.String, "pos_grch37": pl.UInt32},
    )
    return table.frame.with_columns(pl.col("chrom").cast(pl.String)).join(
        wanted, on=["chrom", "pos_grch37"], how="inner"
    )


def lookup_rsids(
    table: GenotypeTable,
    rsids: Iterable[str],
    merges: MergeTable | None = None,
) -> pl.DataFrame:
    """Rows matching any of ``rsids``, resolving retired identifiers through ``merges``.

    Resolution runs on *both* sides. Resolving only the query would miss an export that
    predates the merge -- which is the common case, since the export is fixed at the date
    it was generated and the reference keeps moving.

    The two sides handle an unresolvable identifier differently, on purpose. A *queried*
    rsID that dbSNP says has no single current target raises: the caller asked a specific
    question and the honest answer is that it cannot be answered. A *table* rsID gets null
    (see :func:`add_current_rsid`): the user did not choose those 677k identifiers, and one
    ambiguous retirement among them is not a reason to refuse to read their file.
    """
    table_merges = merges or MergeTable.empty()
    frame = add_current_rsid(table, table_merges)
    wanted = {table_merges.resolve(r) for r in rsids}
    return frame.filter(pl.col("rsid_current").is_in(list(wanted)))
