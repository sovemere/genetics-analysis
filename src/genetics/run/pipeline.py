"""One analysis engine: ingest/QC, ancestry, default-on imputation, cards and save.

Ancestry runs before imputation and any finding assembly. M8.4 executes the shared
full-panel stage unless the caller explicitly supplies no_impute=True. Failures are
reported; there is no automatic direct-overlap fallback. Analysis writes private job
caches, while save() publishes the immutable run bundle.

Card matching uses original calls plus exact biallelic imputed SNVs for absent or
no-call loci, retaining native dosage quality. ClinVar, coverage and genome-structure
modules continue to consume the original array. Execution mode is separate from call_source:
an enabled run does not make an original observed call an imputed observation.
Missing allele frequencies remain unknown. Study-to-sample ancestry portability is computed
for PGS results (M9.5) and polygenic cards are scored here (M9.6); single-marker card
observations keep ancestry_match unset until M9.13.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from genetics.ancestry.context import AncestryContext, AncestryStage, infer_ancestry
from genetics.engine.cards import CardKind, KnowledgePack
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import (
    AssembledCard,
    ObservationEvidence,
    PopulationFrequency,
    assemble_pack,
)
from genetics.engine.matcher import (
    MatchResult,
    MatchStatus,
    Strand,
    complement,
    match_pack,
    summarise,
)
from genetics.health.clinvar import ClinVarLookup, lookup_default
from genetics.health.coverage import assemble_coverage_card
from genetics.health.frequencies import calibrate, default_index, select_frequencies
from genetics.health.secondary import default_reference, surface
from genetics.imputation import ImputationResult, impute
from genetics.imputation.context import ImputationContext
from genetics.imputation.observations import card_input, mark_imputed
from genetics.imputation.quality import ImputationEvidence
from genetics.imputation.target import ImputationError
from genetics.ingest import IngestResult, SourceInfo, ingest
from genetics.ingest.keys import LocusKey
from genetics.ingest.schema import Chrom
from genetics.pgs.runner import PolygenicStage
from genetics.privacy import NoGenotypeRepr
from genetics.qc.report import QCReport
from genetics.run.bundle import write_bundle
from genetics.structure.archaic import infer_archaic_cards
from genetics.structure.interpretation import infer_roh_cards
from genetics.structure.sex_chromosomes import infer_sex_chromosome_cards

__all__ = ["Analysis", "analyse", "save"]


@dataclass(frozen=True)
class Analysis(NoGenotypeRepr):
    """One completed analysis, before it is saved.

    Separate from :func:`save` so that a caller can run the pipeline and inspect the result
    without writing to the store -- which is what the offline test and any future
    ``--dry-run`` need, and what a test asserting on card content should not have to create
    a directory to do.

    Inherits the genotype-safe ``__repr__``: ``cards`` carry genotypes, and the default
    dataclass repr would print them into any traceback that happened to carry this object.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("vendor", "n_cards")

    source: SourceInfo
    qc: QCReport
    pack: KnowledgePack
    matches: tuple[MatchResult, ...]
    cards: tuple[AssembledCard, ...]
    ancestry: AncestryContext
    clinvar: ClinVarLookup
    imputation: ImputationContext
    imputation_result: ImputationResult | None = None
    polygenic: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    """Private M9 score records by polygenic card id, saved as ``pgs.run.json``."""

    @property
    def vendor(self) -> str:
        return self.source.vendor

    @property
    def n_cards(self) -> int:
        return len(self.cards)

    @property
    def status_counts(self) -> dict[MatchStatus, int]:
        """Cards per match status, including the zeros.

        Zeros are kept because this is what the CLI and the M4.5 QC banner render, and a
        status that vanishes when it is empty makes "nothing was strand-ambiguous" look
        identical to "strand ambiguity is not checked".
        """
        return summarise(self.matches)

    @property
    def tier_counts(self) -> dict[ConfidenceTier, int]:
        """Matched cards per confidence tier, including the zeros.

        Only matched cards have a tier at all; the rest are counted by
        :attr:`status_counts`, and adding them here as a sixth pseudo-tier would put "not
        on the array" on the same axis as "well established".
        """
        counts = dict.fromkeys(ConfidenceTier, 0)
        for card in self.cards:
            if card.confidence is not None:
                counts[card.confidence.tier] += 1
            elif card.computation is not None:
                tier = card.computation["reliability"]["tier"]
                if tier is not None:
                    counts[ConfidenceTier(tier)] += 1
        return counts

    @property
    def with_interpretation(self) -> int:
        return sum(1 for card in self.cards if card.has_interpretation)


def observations(
    pack: KnowledgePack,
    matches: tuple[MatchResult, ...] = (),
    frequency_records: dict[tuple[str, int], list[dict[str, Any]]] | None = None,
    imputed: dict[tuple[str, int], ImputationEvidence] | None = None,
) -> dict[str, ObservationEvidence]:
    """One observation per interpretation card. See this module's docstring for why.

    Computed and impossibility cards are excluded rather than given an empty observation:
    ``assemble_card`` refuses one outright, on the grounds that a card that is not
    determinable by construction cannot carry genotype-derived runtime evidence. Keyed by
    card id because ``assemble_pack`` rejects a key naming a card the pack does not have,
    which is the check that catches this function drifting out of step with the pack.
    """
    by_id = {match.card_id: match for match in matches}

    def observed(
        locus: tuple[str, int], frequencies: tuple[PopulationFrequency, ...]
    ) -> ObservationEvidence:
        detail = (imputed or {}).get(locus)
        return ObservationEvidence(
            call_source=CallSource.DIRECT if detail is None else CallSource.IMPUTED,
            frequencies=frequencies,
            imputation_quality=None if detail is None else detail.card_quality,
            imputation=detail,
        )

    result: dict[str, ObservationEvidence] = {}
    for card in pack.cards:
        if card.kind is not CardKind.INTERPRETATION:
            continue
        assert card.match is not None
        match = by_id.get(card.id)
        if len(card.match.variants) > 1:
            marker_observations = []
            for i, card_variant in enumerate(card.match.variants):
                marker = match.markers[i] if match is not None else None
                called = set(marker.genotype or "") if marker is not None else set()
                records = (frequency_records or {}).get(
                    (card_variant.key.chrom.value, card_variant.key.pos_grch37), []
                )
                frequencies = (
                    select_frequencies(
                        records, alleles=set(card_variant.key.alleles), called=called
                    )
                    if marker is not None and marker.status is MatchStatus.MATCHED
                    else ()
                )
                marker_observations.append(
                    observed(
                        (card_variant.key.chrom.value, card_variant.key.pos_grch37), frequencies
                    )
                )
            result[card.id] = ObservationEvidence(
                call_source=CallSource.DIRECT, markers=tuple(marker_observations)
            )
            continue
        variant = card.match.variant.key
        if match is None or match.status is not MatchStatus.MATCHED:
            result[card.id] = observed((variant.chrom.value, variant.pos_grch37), ())
            continue
        called = set(match.genotype or match.observed_genotype or "")
        if match.strand is Strand.AMBIGUOUS:
            called.update(complement(match.observed_genotype or ""))
        records = (frequency_records or {}).get((variant.chrom.value, variant.pos_grch37), [])
        frequencies = select_frequencies(records, alleles=set(variant.alleles), called=called)
        result[card.id] = observed((variant.chrom.value, variant.pos_grch37), frequencies)
    return result


def analyse(
    input_path: Path,
    *,
    knowledge_dir: Path | None = None,
    ancestry: AncestryStage | None = None,
    progress: Callable[[str], None] | None = None,
    no_impute: bool = False,
    polygenic: PolygenicStage | None = None,
) -> Analysis:
    """Parse, QC, infer ancestry, impute by default, then evaluate quality-aware cards.

    Writes no run bundle.

    ``ancestry`` replaces the default stage, :func:`~genetics.ancestry.context.
    infer_ancestry`. ``progress`` is handed to that default and receives one line per slow
    step, since the first run on a new chip builds a reference PCA and that takes minutes; a
    replacement stage reports progress however it likes.

    Raises whatever the stages raise -- ``IngestError``, ``AnchorError``, ``AncestryError``,
    ``CardError``, ``EvidenceAssemblyError`` -- unwrapped. A pipeline-specific exception type
    here would hide which stage failed behind one name, and the CLI has to tell a bad export
    from a bad knowledge pack to say anything useful about either.
    """
    # The pack loads first, though nothing about the data requires it: `KnowledgePack.load`
    # parses a few YAML files, while `ingest` parses 677,000 rows. With the other order a
    # typo in a card file is reported after a full parse of somebody's genome, which is the
    # slowest possible way to learn about the cheapest possible mistake -- and card
    # authoring is exactly when that mistake gets made.
    if type(no_impute) is not bool:
        raise ImputationError("no_impute must be an explicit boolean.")
    pack = KnowledgePack.load(knowledge_dir)
    # Polygenic scoring files, licences and the 1000 Genomes extraction are public; verify
    # them before the export is read, so a tampered reference fails before a genome is.
    polygenic_stage = polygenic if polygenic is not None else PolygenicStage()
    polygenic_stage.prepare(pack, progress)
    result: IngestResult = ingest(input_path)
    if ancestry is None:
        context = infer_ancestry(result.table, result.qc, progress=progress)
    else:
        context = ancestry(result.table, result.qc)
    imputation_result = None
    if no_impute:
        imputation_context = ImputationContext.disabled()
        if progress:
            progress("Imputation disabled by explicit --no-impute request")
    else:
        imputation_result = impute(result.table, sex=result.qc.sex.inferred, progress=progress)
        if imputation_result.original is not result.table:
            raise ImputationError("Imputation returned observations for a different target.")
        imputation_context = ImputationContext.enabled(
            imputation_result.summary(), quality_aware=True
        )
    matching_table, imputed = (
        (result.table, {})
        if imputation_result is None
        else card_input(pack, imputation_result, sex=result.qc.sex.inferred)
    )
    matches = match_pack(
        pack,
        matching_table,
        reference_forward_loci=frozenset(LocusKey(Chrom(c), p) for c, p in imputed),
    )
    updated = []
    for card, match in zip(pack.cards, matches, strict=True):
        if card.match is not None:
            if match.markers:
                match = replace(
                    match,
                    markers=tuple(
                        mark_imputed(marker)
                        if (variant.key.chrom.value, variant.key.pos_grch37) in imputed
                        else marker
                        for marker, variant in zip(match.markers, card.match.variants, strict=True)
                    ),
                )
            elif (card.match.variant.key.chrom.value, card.match.variant.key.pos_grch37) in imputed:
                match = mark_imputed(match)
        updated.append(match)
    matches = tuple(updated)
    clinvar = lookup_default(result.table, progress=progress)
    frequency_index = default_index(progress=progress)
    loci = {(locus["chrom"], locus["pos_grch37"]) for locus in clinvar.loci}
    loci.update(
        (v.key.chrom.value, v.key.pos_grch37)
        for c in pack.cards
        if c.match is not None
        for v in c.match.variants
    )
    frequency_records = frequency_index.lookup(loci) if frequency_index else {}
    clinvar = calibrate(clinvar, index=frequency_index, records=frequency_records)
    clinvar = surface(clinvar, default_reference())
    cards = assemble_pack(pack, matches, observations(pack, matches, frequency_records, imputed))
    cards = tuple(
        assemble_coverage_card(c.card, clinvar.coverage)
        if c.card.computation == "clinvar_coverage"
        else c
        for c in cards
    )
    cards = infer_roh_cards(cards, result.table, progress=progress)
    cards = infer_archaic_cards(cards, result.table, progress=progress)
    cards = infer_sex_chromosome_cards(cards, result.table)
    polygenic_cards, polygenic_records = polygenic_stage.score(
        table=result.table,
        sex=result.qc.sex.inferred,
        dosages=None if imputation_result is None else imputation_result.iter_dosages,
        ancestry=context.to_dict(),
        imputation_provenance=None if imputation_result is None else imputation_result.metadata,
        progress=progress,
    )
    cards = tuple(polygenic_cards.get(card.card_id, card) for card in cards)
    cards = tuple(replace(card, imputation_mode=imputation_context.mode) for card in cards)
    matches = tuple(card.match for card in cards)
    return Analysis(
        source=result.source,
        qc=result.qc,
        pack=pack,
        matches=matches,
        cards=cards,
        ancestry=context,
        clinvar=clinvar,
        imputation=imputation_context,
        imputation_result=imputation_result,
        polygenic=polygenic_records,
    )


def save(
    analysis: Analysis,
    *,
    runs_root: Path | None = None,
    run_id: str | None = None,
    created_at: datetime | None = None,
    lock_path: Path | None = None,
    tools_root: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Write ``analysis`` as an immutable bundle and return its directory.

    A pass-through to :func:`~genetics.run.bundle.write_bundle` with the three arguments it
    needs taken off the analysis, so a caller cannot pair one run's QC report with another
    run's cards. The remaining keywords are forwarded rather than re-defaulted: they are
    ``write_bundle``'s own, and restating its defaults here would be a second set to keep
    in step.
    """
    if analysis.imputation.mode == "enabled" and analysis.imputation_result is None:
        raise ImputationError(
            "Enabled analysis cannot be saved without its completed imputation stage."
        )
    return write_bundle(
        qc=analysis.qc,
        cards=analysis.cards,
        pack=analysis.pack,
        ancestry=analysis.ancestry,
        clinvar=analysis.clinvar,
        imputation=analysis.imputation,
        imputation_result=analysis.imputation_result,
        polygenic=analysis.polygenic,
        progress=progress,
        runs_root=runs_root,
        run_id=run_id,
        created_at=created_at,
        lock_path=lock_path,
        tools_root=tools_root,
    )
