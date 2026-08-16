"""Offline card-pack linting (roadmap M3.5).

Loading a :class:`~genetics.engine.cards.KnowledgePack` already validates its schema,
citation shape and template syntax.  Lint adds the two checks that need more context:

* every outcome template is actually rendered with values the engine can supply; and
* each authored ``(rsID, GRCh37 position, alleles)`` tuple agrees with dbSNP.

Variant resolution is deliberately injected.  Tests use an in-memory resolver, while the
CLI uses the compact Parquet index derived from the fetched, checksum-pinned dbSNP VCF.
The index is reference data and is never committed.  If it is absent, full lint fails
closed; ``--schema-only`` is an explicit CI escape hatch which still exercises every
check that does not require the 28 GB download and says in its output that resolution was
skipped.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import polars as pl

from genetics.engine.cards import (
    Card,
    CardError,
    CardKind,
    CardVariant,
    KnowledgePack,
    Outcome,
)
from genetics.engine.evidence import EvidenceAssemblyError, render_template
from genetics.ingest.keys import LocusKey, VariantKey
from genetics.ingest.schema import Chrom
from genetics.paths import references_dir

DBSNP_SOURCE_ID = "dbsnp_b157_grch37"
DBSNP_VARIANT_INDEX = "dbsnp_variants.parquet"


class VariantResolverError(RuntimeError):
    """The reference index is missing, corrupt, or has an incompatible schema."""


@dataclass(frozen=True)
class ReferenceVariant:
    """One dbSNP assertion, normalized to the engine's primary key."""

    rsid: str
    key: VariantKey


class VariantResolver(Protocol):
    """Lookup boundary used by lint.

    Implementations return every record matching either an authored rsID or an authored
    locus.  Looking up both directions is what distinguishes a wrong coordinate from a
    wrong rsID; querying by rsID alone can only say that the combined assertion failed.
    """

    @property
    def label(self) -> str: ...

    def lookup(self, variants: Sequence[CardVariant]) -> tuple[ReferenceVariant, ...]: ...


@dataclass(frozen=True)
class InMemoryVariantResolver:
    """Small resolver for tests and callers that already hold reference rows."""

    records: tuple[ReferenceVariant, ...]
    label: str = "in-memory variant reference"

    def __init__(
        self,
        records: Iterable[ReferenceVariant],
        label: str = "in-memory variant reference",
    ) -> None:
        object.__setattr__(self, "records", tuple(records))
        object.__setattr__(self, "label", label)

    def lookup(self, variants: Sequence[CardVariant]) -> tuple[ReferenceVariant, ...]:
        rsids = {variant.rsid for variant in variants}
        loci = {variant.key.locus for variant in variants}
        return tuple(
            record for record in self.records if record.rsid in rsids or record.key.locus in loci
        )


@dataclass(frozen=True)
class ParquetVariantResolver:
    """Resolver backed by M3.5's compact dbSNP-derived Parquet index.

    Required columns are ``rsid``, ``chrom``, ``pos_grch37``, ``ref`` and ``alts``;
    ``alts`` is a Parquet list of strings, not a delimited string.  Requiring a real list
    avoids choosing a separator that can later collide with a symbolic allele.  Only rows
    matching the requested rsIDs or loci are collected.  The post-process provenance and
    output digest are verified before any row is trusted.
    """

    path: Path
    bind_to_manifest: bool = False

    @property
    def label(self) -> str:
        return str(self.path)

    def lookup(self, variants: Sequence[CardVariant]) -> tuple[ReferenceVariant, ...]:
        if not self.path.is_file():
            raise VariantResolverError(
                f"dbSNP variant index not found: {self.path}. Fetch and post-process "
                f"{DBSNP_SOURCE_ID}, or use --schema-only when reference data is "
                "intentionally unavailable."
            )
        if not variants:
            return ()

        # A schema-shaped Parquet file is not enough: it may be stale, truncated in a
        # way Parquet can still read, or simply come from another transform.  The
        # post-process sidecar binds this exact output to the checksum-pinned dbSNP input
        # and records its own digest.  Full lint is the release gate for authored variant
        # keys, so it must fail closed on that provenance just as ``refs verify`` does.
        from genetics.refs.postprocess import (
            ProcessError,
            declared_artifact_provenance,
            get,
            validate_provenance,
        )

        try:
            expected = (
                declared_artifact_provenance(
                    DBSNP_SOURCE_ID,
                    "extract_dbsnp_variant_index",
                    output_name=self.path.name,
                )
                if self.bind_to_manifest
                else None
            )
            validate_provenance(
                self.path,
                expected=expected,
                expected_step="extract_dbsnp_variant_index",
                expected_transform_version=get("extract_dbsnp_variant_index").transform_version,
            )
        except ProcessError as exc:
            raise VariantResolverError(
                f"dbSNP variant index provenance is invalid: {exc}"
            ) from None

        rsids = sorted({variant.rsid for variant in variants})
        loci = sorted({(variant.key.chrom.value, variant.key.pos_grch37) for variant in variants})

        locus_filter = pl.lit(False)
        for chrom, pos in loci:
            locus_filter = locus_filter | (
                (pl.col("chrom").cast(pl.String) == chrom) & (pl.col("pos_grch37") == pos)
            )

        try:
            frame = (
                pl.scan_parquet(self.path)
                .select("rsid", "chrom", "pos_grch37", "ref", "alts")
                .filter(pl.col("rsid").is_in(rsids) | locus_filter)
                .collect()
            )
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise VariantResolverError(
                f"could not read dbSNP variant index {self.path}: {exc}"
            ) from None

        records: list[ReferenceVariant] = []
        for row_number, row in enumerate(frame.iter_rows(named=True), start=1):
            records.append(_reference_variant(row, self.path, row_number))
        return tuple(records)


def _reference_variant(row: Mapping[str, Any], path: Path, row_number: int) -> ReferenceVariant:
    """Validate one requested reference row before trusting it."""

    where = f"{path} matching row {row_number}"
    rsid = row.get("rsid")
    chrom = row.get("chrom")
    pos = row.get("pos_grch37")
    ref = row.get("ref")
    alts = row.get("alts")

    if not isinstance(rsid, str) or not rsid.startswith("rs"):
        raise VariantResolverError(f"{where}: rsid is missing or malformed")
    try:
        normalized_chrom = Chrom(str(chrom).strip().upper())
    except ValueError:
        raise VariantResolverError(f"{where}: unknown chromosome {chrom!r}") from None
    if isinstance(pos, bool) or not isinstance(pos, int) or pos <= 0:
        raise VariantResolverError(f"{where}: pos_grch37 is not a positive integer")
    if not isinstance(ref, str) or not ref.strip():
        raise VariantResolverError(f"{where}: ref is empty or not a string")
    if (
        not isinstance(alts, list)
        or not alts
        or not all(isinstance(alt, str) and alt.strip() for alt in alts)
    ):
        raise VariantResolverError(
            f"{where}: alts must be a non-empty Parquet list of non-empty strings"
        )

    try:
        key = VariantKey(normalized_chrom, pos, [ref, *alts])
    except ValueError as exc:
        raise VariantResolverError(f"{where}: invalid allele set -- {exc}") from None
    return ReferenceVariant(rsid=rsid, key=key)


def default_variant_index() -> Path:
    """The derived index beside the fetched dbSNP source."""

    return references_dir() / DBSNP_SOURCE_ID / DBSNP_VARIANT_INDEX


class VariantResolution(StrEnum):
    CHECKED = "checked"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LintIssue:
    code: str
    message: str
    card_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LintReport:
    source: str
    card_count: int
    interpretation_count: int
    rendered_templates: int
    resolved_variants: int
    variant_resolution: VariantResolution
    resolver: str | None
    issues: tuple[LintIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": self.source,
            "card_count": self.card_count,
            "interpretation_count": self.interpretation_count,
            "rendered_templates": self.rendered_templates,
            "resolved_variants": self.resolved_variants,
            "variant_resolution": self.variant_resolution.value,
            "resolver": self.resolver,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def lint_directory(
    directory: Path,
    *,
    resolver: VariantResolver | None = None,
    resolve_variants: bool = True,
) -> LintReport:
    """Load and lint a knowledge directory, returning errors as data for the CLI."""

    try:
        pack = KnowledgePack.load(directory)
    except (CardError, OSError, UnicodeError) as exc:
        return LintReport(
            source=str(directory),
            card_count=0,
            interpretation_count=0,
            rendered_templates=0,
            resolved_variants=0,
            variant_resolution=(
                VariantResolution.UNAVAILABLE if resolve_variants else VariantResolution.SKIPPED
            ),
            resolver=resolver.label if resolver is not None else None,
            issues=(LintIssue("schema", str(exc)),),
        )
    return lint_pack(pack, resolver=resolver, resolve_variants=resolve_variants)


def lint_pack(
    pack: KnowledgePack,
    *,
    resolver: VariantResolver | None = None,
    resolve_variants: bool = True,
) -> LintReport:
    """Lint a parsed pack without suppressing any problem after the first."""

    issues: list[LintIssue] = []
    rendered = 0
    interpretations = tuple(card for card in pack.cards if card.kind is CardKind.INTERPRETATION)

    for card in pack.cards:
        if card.kind is CardKind.INTERPRETATION and not card.citations:
            issues.append(
                LintIssue(
                    "citation-missing",
                    "interpretation cards require at least one structured citation",
                    card.id,
                )
            )
        card_issues, card_rendered = _lint_templates(card)
        issues.extend(card_issues)
        rendered += card_rendered

    resolved = 0
    if not resolve_variants:
        resolution = VariantResolution.SKIPPED
    elif not interpretations:
        resolution = VariantResolution.CHECKED
    elif resolver is None:
        resolution = VariantResolution.UNAVAILABLE
        issues.append(
            LintIssue(
                "variant-index-unavailable",
                "variant resolution was requested but no dbSNP resolver was supplied; "
                "full lint fails closed rather than treating unchecked keys as valid",
            )
        )
    else:
        variants = tuple(card.match.variant for card in interpretations if card.match is not None)
        try:
            records = resolver.lookup(variants)
        except VariantResolverError as exc:
            resolution = VariantResolution.UNAVAILABLE
            issues.append(LintIssue("variant-index-unavailable", str(exc)))
        else:
            resolution = VariantResolution.CHECKED
            by_rsid: dict[str, list[ReferenceVariant]] = defaultdict(list)
            by_locus: dict[LocusKey, list[ReferenceVariant]] = defaultdict(list)
            for record in records:
                by_rsid[record.rsid].append(record)
                by_locus[record.key.locus].append(record)
            for card in interpretations:
                if card.match is None:  # Defensive: Card.parse makes this impossible.
                    issues.append(
                        LintIssue("match-missing", "interpretation has no match", card.id)
                    )
                    continue
                variant = card.match.variant
                issue = _resolve_variant(variant, by_rsid, by_locus, card.id)
                if issue is None:
                    resolved += 1
                else:
                    issues.append(issue)

    return LintReport(
        source=str(pack.source_dir),
        card_count=len(pack),
        interpretation_count=len(interpretations),
        rendered_templates=rendered,
        resolved_variants=resolved,
        variant_resolution=resolution,
        resolver=resolver.label if resolver is not None else None,
        issues=tuple(issues),
    )


def _resolve_variant(
    variant: CardVariant,
    by_rsid: Mapping[str, Sequence[ReferenceVariant]],
    by_locus: Mapping[LocusKey, Sequence[ReferenceVariant]],
    card_id: str,
) -> LintIssue | None:
    """Cross-check both names for a variant and explain which half disagreed."""

    named = tuple(by_rsid.get(variant.rsid, ()))
    at_locus = tuple(by_locus.get(variant.key.locus, ()))
    authored_alleles = set(variant.key.alleles)

    def includes_authored_alleles(record: ReferenceVariant) -> bool:
        # dbSNP can retain rare additional ALT alleles at an otherwise established
        # biallelic array marker. A card describes the alleles the chip can report; making
        # it map every theoretical dbSNP alternate would create genotype outcomes the
        # sample format cannot produce. The authored pair must be present, not exhaustive
        # of dbSNP's record.
        return authored_alleles <= set(record.key.alleles)

    named_at_locus = tuple(record for record in named if record.key.locus == variant.key.locus)
    if any(includes_authored_alleles(record) for record in named_at_locus):
        return None
    compatible_at_locus = tuple(record for record in at_locus if includes_authored_alleles(record))
    if compatible_at_locus:
        observed = ", ".join(sorted({record.rsid for record in compatible_at_locus}))
        return LintIssue(
            "variant-rsid-mismatch",
            f"{variant.key} resolves in dbSNP as {observed}, not {variant.rsid}",
            card_id,
        )
    if named_at_locus:
        observed = ", ".join(sorted(str(record.key) for record in named_at_locus))
        return LintIssue(
            "variant-allele-mismatch",
            f"{variant.rsid} is at the authored locus, but dbSNP reports {observed}",
            card_id,
        )
    if named:
        observed = ", ".join(sorted(str(record.key.locus) for record in named))
        return LintIssue(
            "variant-coordinate-mismatch",
            f"{variant.rsid} resolves to {observed}, not {variant.key.locus}",
            card_id,
        )
    return LintIssue(
        "variant-unresolved",
        f"neither {variant.rsid} nor {variant.key} resolves in the supplied dbSNP index",
        card_id,
    )


def _lint_templates(card: Card) -> tuple[list[LintIssue], int]:
    """Render every outcome with synthetic non-personal values.

    M3.4 owns the shared production renderer and context vocabulary. Lint still needs to
    exercise *every* outcome, including outcomes no current sample has, so it cannot
    depend solely on a matched run result.
    """

    issues: list[LintIssue] = []
    rendered = 0
    if card.kind is CardKind.IMPOSSIBILITY:
        context: dict[str, object] = {"gene": card.gene or "GENE"}
        for field_name, template in (("summary", card.summary), ("detail", card.detail)):
            if template is None:
                issues.append(
                    LintIssue("template-missing", f"{field_name} template is missing", card.id)
                )
                continue
            issue = _render_one(template, context, field_name, card.id)
            if issue is None:
                rendered += 1
            else:
                issues.append(issue)
        return issues, rendered

    if card.match is None or card.evidence is None:
        return [LintIssue("match-missing", "interpretation has no match/evidence", card.id)], 0

    variant = card.match.variant
    effect = card.evidence.effect
    base_context: dict[str, object] = {
        "rsid": variant.rsid,
        "rsid_current": variant.rsid,
        "gene": card.gene or "GENE",
        "chrom": variant.key.chrom.value,
        "pos": variant.key.pos_grch37,
        "effect_value": effect.value,
        "effect_units": effect.units or "",
        "sample_size": card.evidence.sample_size,
        # Forward-compatible synthetic values. Card.parse still decides which placeholders
        # are currently legal; carrying later values here makes a milestone flip exercise
        # rendering immediately instead of failing because lint forgot the new context key.
        "confidence": "well-established",
        "frequency": 0.5,
        "ppv": 1.0,
        "ancestry": "EUR",
        "imputation_quality": 1.0,
        "percentile": 50,
    }
    for genotype, outcome_name in card.match.genotypes.items():
        outcome: Outcome | None = card.outcomes.get(outcome_name)
        if outcome is None:
            issues.append(
                LintIssue(
                    "outcome-unresolved",
                    "a constructible genotype maps to an outcome that is not defined",
                    card.id,
                )
            )
            continue
        context = {**base_context, "genotype": genotype}
        for field_name, template in (("summary", outcome.summary), ("detail", outcome.detail)):
            issue = _render_one(template, context, f"outcomes.{outcome_name}.{field_name}", card.id)
            if issue is None:
                rendered += 1
            else:
                issues.append(issue)
    return issues, rendered


def _render_one(
    template: str,
    context: Mapping[str, object],
    field_name: str,
    card_id: str,
) -> LintIssue | None:
    try:
        rendered = render_template(template, context)
    except EvidenceAssemblyError as exc:
        return LintIssue(
            "template-render",
            f"{field_name} could not render with the engine context: {exc}",
            card_id,
        )
    if not rendered.strip():
        return LintIssue(
            "template-render",
            f"{field_name} rendered to empty text",
            card_id,
        )
    return None
