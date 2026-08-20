"""The analysis pipeline: an export in, a saved run bundle out (roadmap M4.0).

This is the function ``genetics run`` calls and the one M4.10 will run with networking
disabled at the OS level. It exists as a module rather than as the body of a CLI command
because the dashboard, the agent surface (AGENTS.md section 3) and the offline test all
need to *produce* a run, and a pipeline that only exists inside a Typer callback can be
driven by exactly one of them.

The stages are the ones the earlier milestones already built, in the only order they
compose::

    ingest -> match_pack -> assemble_pack -> write_bundle

Nothing here reshapes what those return. That is deliberate: every adapter written at this
seam would be a second description of a format that already has one, and the failure this
project keeps meeting (M0.4, M3.7, M4.1, M4.2) is two names for one thing drifting apart.

**The one thing this module actually decides is the observation layer**, and it is worth
being explicit about why that is a decision rather than a default.
:func:`~genetics.engine.evidence.assemble_pack` refuses to assemble an interpretation card
without :class:`~genetics.engine.evidence.ObservationEvidence`, because assuming a direct
call would score an imputed observation as perfect. At this milestone there is no
imputation stage and no ancestry fit, so the honest observation is
:attr:`~genetics.engine.confidence.CallSource.DIRECT` with no frequencies and no ancestry
match -- and the caveat that produces on the card face ("no population frequency was
available, so the rarity check could not be applied and confidence is capped") is the
correct thing for a reader to see today, not a placeholder to be quietly removed.

That constant is written here, once, where M8 and M5 have somewhere obvious to change it.
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

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from genetics.engine.cards import CardKind, KnowledgePack
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import AssembledCard, ObservationEvidence, assemble_pack
from genetics.engine.matcher import MatchResult, MatchStatus, match_pack, summarise
from genetics.ingest import IngestResult, SourceInfo, ingest
from genetics.privacy import NoGenotypeRepr
from genetics.qc.report import QCReport
from genetics.run.bundle import write_bundle

__all__ = ["Analysis", "analyse", "save"]


_DIRECT = ObservationEvidence(call_source=CallSource.DIRECT)
"""The whole observation layer at M4, shared because it is frozen and identical.

One instance rather than one per card: :class:`ObservationEvidence` is immutable, so a
per-card copy would differ only in identity, and a reader wondering whether two cards were
observed differently deserves to see that they cannot be.
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
        return counts

    @property
    def with_interpretation(self) -> int:
        return sum(1 for card in self.cards if card.has_interpretation)


def observations(pack: KnowledgePack) -> dict[str, ObservationEvidence]:
    """One observation per interpretation card. See this module's docstring for why.

    Impossibility cards are excluded rather than given an empty observation:
    ``assemble_card`` refuses one outright, on the grounds that a card that is not
    determinable by construction cannot carry genotype-derived runtime evidence. Keyed by
    card id because ``assemble_pack`` rejects a key naming a card the pack does not have,
    which is the check that catches this function drifting out of step with the pack.
    """
    return {card.id: _DIRECT for card in pack.cards if card.kind is not CardKind.IMPOSSIBILITY}


def analyse(input_path: Path, *, knowledge_dir: Path | None = None) -> Analysis:
    """Parse, QC, match and assemble. Writes nothing.

    Raises whatever the stages raise -- ``IngestError``, ``AnchorError``, ``CardError``,
    ``EvidenceAssemblyError`` -- unwrapped. A pipeline-specific exception type here would
    hide which stage failed behind one name, and the CLI has to tell a bad export from a
    bad knowledge pack to say anything useful about either.
    """
    # The pack loads first, though nothing about the data requires it: `KnowledgePack.load`
    # parses a few YAML files, while `ingest` parses 677,000 rows. With the other order a
    # typo in a card file is reported after a full parse of somebody's genome, which is the
    # slowest possible way to learn about the cheapest possible mistake -- and card
    # authoring is exactly when that mistake gets made.
    pack = KnowledgePack.load(knowledge_dir)
    result: IngestResult = ingest(input_path)
    matches = match_pack(pack, result.table)
    cards = assemble_pack(pack, matches, observations(pack))
    return Analysis(
        source=result.source,
        qc=result.qc,
        pack=pack,
        matches=matches,
        cards=cards,
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
        runs_root=runs_root,
        run_id=run_id,
        created_at=created_at,
        lock_path=lock_path,
        tools_root=tools_root,
    )
