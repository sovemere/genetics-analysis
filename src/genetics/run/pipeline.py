"""The analysis pipeline: an export in, a saved run bundle out (roadmap M4.0).

This is the function ``genetics run`` calls and the one M4.10 will run with networking
disabled at the OS level. It exists as a module rather than as the body of a CLI command
because the dashboard, the agent surface (AGENTS.md section 3) and the offline test all
need to *produce* a run, and a pipeline that only exists inside a Typer callback can be
driven by exactly one of them.

The stages are the ones the earlier milestones already built, in the only order they
compose::

    ingest -> infer_ancestry -> match_pack -> reference lookup -> assemble_pack
        -> structure stages -> write_bundle

**Ancestry runs before any card is assembled (M5.8), and that order is the requirement.**
PRS confidence depends on it (AGENTS.md 4.4), so the stage that will consume it -- M9.5,
turning a placement into ``ancestry_match`` -- has to find it already computed. What the
stage returns is :class:`~genetics.ancestry.context.AncestryContext`, whose statuses keep
"not inferred" and "inferred, and no reference population fits" apart; see that module for
why the difference is load-bearing. Nothing in this module yet reads it back into a card.

Nothing here reshapes what those return. That is deliberate: every adapter written at this
seam would be a second description of a format that already has one, and the failure this
project keeps meeting (M0.4, M3.7, M4.1, M4.2) is two names for one thing drifting apart.

**The one thing this module actually decides is the observation layer**, and it is worth
being explicit about why that is a decision rather than a default.
:func:`~genetics.engine.evidence.assemble_pack` refuses to assemble an interpretation card
without :class:`~genetics.engine.evidence.ObservationEvidence`, because assuming a direct
call would score an imputed observation as perfect. At this milestone there is no
imputation stage, and the ancestry stage's result has no mapping onto a card's study
population yet (M9.5), so the observation remains
:attr:`~genetics.engine.confidence.CallSource.DIRECT` with no ancestry match. M7.2 now
supplies allele-specific gnomAD frequencies where an exact, usable reference record
exists. Missing frequencies remain unknown and cap confidence; nothing assumes zero
or infers personal ancestry from the population chosen for the conservative rarity screen.

That observation is supplied here, where M8 and M9 have somewhere obvious to change it.
It is emphatically *not* a default inside ``assemble_card``: a card assembled without an
observation is a card whose provenance nobody stated, and the refusal there is what makes
this module have to say it out loud.

**A DIRECT observation is recorded even for a card whose marker is absent**, which reads
oddly until you read it as a statement about the run rather than the card: this pipeline
has no imputation stage, so no genotype in this run could have been imputed. That is
exactly the distinction M4.1 added ``observation`` to the bundle to preserve -- "the marker
is not on this array" against "imputation was attempted and failed" -- and dropping the
record for unmatched cards would throw it away for the only cards it can distinguish.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from genetics.ancestry.context import AncestryContext, AncestryStage, infer_ancestry
from genetics.engine.cards import CardKind, KnowledgePack
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import AssembledCard, ObservationEvidence, assemble_pack
from genetics.engine.matcher import (
    MatchResult,
    MatchStatus,
    Strand,
    complement,
    match_pack,
    summarise,
)
from genetics.health.clinvar import ClinVarLookup, lookup_default
from genetics.health.frequencies import calibrate, default_index, select_frequencies
from genetics.health.secondary import default_reference, surface
from genetics.ingest import IngestResult, SourceInfo, ingest
from genetics.privacy import NoGenotypeRepr
from genetics.qc.report import QCReport
from genetics.run.bundle import write_bundle
from genetics.structure.archaic import infer_archaic_cards
from genetics.structure.interpretation import infer_roh_cards
from genetics.structure.sex_chromosomes import infer_sex_chromosome_cards

__all__ = ["Analysis", "analyse", "save"]


_DIRECT = ObservationEvidence(call_source=CallSource.DIRECT)
"""The frozen observation for unavailable references or unmatched cards.

One instance rather than one per card: :class:`ObservationEvidence` is immutable, so a
per-card copy of this fallback would differ only in identity. Cards with usable M7.2
frequencies receive their own explicit observations.
"""


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
) -> dict[str, ObservationEvidence]:
    """One observation per interpretation card. See this module's docstring for why.

    Computed and impossibility cards are excluded rather than given an empty observation:
    ``assemble_card`` refuses one outright, on the grounds that a card that is not
    determinable by construction cannot carry genotype-derived runtime evidence. Keyed by
    card id because ``assemble_pack`` rejects a key naming a card the pack does not have,
    which is the check that catches this function drifting out of step with the pack.
    """
    by_id = {match.card_id: match for match in matches}
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
                marker_observations.append(ObservationEvidence(CallSource.DIRECT, frequencies))
            result[card.id] = ObservationEvidence(
                call_source=CallSource.DIRECT, markers=tuple(marker_observations)
            )
            continue
        variant = card.match.variant.key
        if match is None or match.status is not MatchStatus.MATCHED:
            result[card.id] = _DIRECT
            continue
        called = set(match.genotype or match.observed_genotype or "")
        if match.strand is Strand.AMBIGUOUS:
            called.update(complement(match.observed_genotype or ""))
        records = (frequency_records or {}).get((variant.chrom.value, variant.pos_grch37), [])
        frequencies = select_frequencies(records, alleles=set(variant.alleles), called=called)
        result[card.id] = ObservationEvidence(
            call_source=CallSource.DIRECT, frequencies=frequencies
        )
    return result


def analyse(
    input_path: Path,
    *,
    knowledge_dir: Path | None = None,
    ancestry: AncestryStage | None = None,
    progress: Callable[[str], None] | None = None,
) -> Analysis:
    """Parse, QC, infer ancestry, match, assemble and compute structure cards.

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
    pack = KnowledgePack.load(knowledge_dir)
    result: IngestResult = ingest(input_path)
    if ancestry is None:
        context = infer_ancestry(result.table, result.qc, progress=progress)
    else:
        context = ancestry(result.table, result.qc)
    matches = match_pack(pack, result.table)
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
    cards = assemble_pack(pack, matches, observations(pack, matches, frequency_records))
    cards = infer_roh_cards(cards, result.table, progress=progress)
    cards = infer_archaic_cards(cards, result.table, progress=progress)
    cards = infer_sex_chromosome_cards(cards, result.table)
    matches = tuple(card.match for card in cards)
    return Analysis(
        source=result.source,
        qc=result.qc,
        pack=pack,
        matches=matches,
        cards=cards,
        ancestry=context,
        clinvar=clinvar,
    )


def save(
    analysis: Analysis,
    *,
    runs_root: Path | None = None,
    run_id: str | None = None,
    created_at: datetime | None = None,
    lock_path: Path | None = None,
    tools_root: Path | None = None,
) -> Path:
    """Write ``analysis`` as an immutable bundle and return its directory.

    A pass-through to :func:`~genetics.run.bundle.write_bundle` with the three arguments it
    needs taken off the analysis, so a caller cannot pair one run's QC report with another
    run's cards. The remaining keywords are forwarded rather than re-defaulted: they are
    ``write_bundle``'s own, and restating its defaults here would be a second set to keep
    in step.
    """
    return write_bundle(
        qc=analysis.qc,
        cards=analysis.cards,
        pack=analysis.pack,
        ancestry=analysis.ancestry,
        clinvar=analysis.clinvar,
        runs_root=runs_root,
        run_id=run_id,
        created_at=created_at,
        lock_path=lock_path,
        tools_root=tools_root,
    )
