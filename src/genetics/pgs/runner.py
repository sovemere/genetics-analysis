"""The polygenic stage of ``genetics run`` (M9.6): one engine, two front-ends.

Every polygenic card in the knowledge pack is scored by the same M9.2-M9.5 functions
``genetics pgs score`` uses, so the dashboard and the CLI read one computation. Public work
-- locating and lock-verifying the scoring file, the licence gate, the 1000 Genomes
extraction -- happens in :meth:`PolygenicStage.prepare`, which the pipeline calls *before*
reading the export, so a tampered reference fails before a genome is parsed (the M9.4 review
rule). The 1000 Genomes placement is made once per run and shared by every score.

Absent is not wrong: a scoring file that is not fetched, metadata that is not fetched, or a
licence that needs an opt-in leaves the card ``not_run`` with the reason and the fix. A file
that is present and disagrees with its lock digest raises, as every reference does.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from genetics.ancestry.context import PopulationResult, place_among_reference_populations
from genetics.engine.cards import Card, CardKind, KnowledgePack
from genetics.engine.evidence import AssembledCard
from genetics.external.plink2 import Plink2
from genetics.imputation.dosages import DosageRecord
from genetics.ingest.schema import GenotypeTable
from genetics.paths import reference_lock, reference_manifest, references_dir
from genetics.pgs.cards import assemble_polygenic_card
from genetics.pgs.catalog import Catalog, PgsError, fingerprint
from genetics.pgs.engine import score
from genetics.pgs.reference import PreparedReference, attach_reference, prepare_reference
from genetics.pgs.scoring import ScoringFile
from genetics.qc.report import InferredSex
from genetics.refs import lock as refs_lock
from genetics.refs import manifest as refs_manifest
from genetics.refs.postprocess import ProcessError


@dataclass(frozen=True)
class Prepared:
    """One card's public inputs, verified before any personal data is read."""

    card: Card
    scoring: ScoringFile | None = None
    reference: PreparedReference | Mapping[str, str] | None = None
    reason: str | None = None


def locate_scoring_file(card: Card, root: Path) -> Path | str:
    """The card's lock-verified scoring file, or why it is not available."""
    assert card.pgs is not None
    fetch = f"`genetics refs fetch --only {card.pgs.source}`"
    try:
        source = refs_manifest.load(reference_manifest()).get(card.pgs.source)
    except refs_manifest.ManifestError:
        return f"The reference manifest has no source {card.pgs.source!r}."
    files = [f for f in source.files if f.filename.startswith(card.pgs.pgs_id)]
    if len(files) != 1:
        raise PgsError(f"Manifest source {card.pgs.source!r} must hold exactly one scoring file.")
    path = root / card.pgs.source / files[0].filename
    try:
        locked = refs_lock.read(root / reference_lock().name).sources.get(card.pgs.source)
    except (refs_lock.LockError, OSError, UnicodeDecodeError) as exc:
        raise PgsError("The reference lock cannot be read.") from exc
    if locked is None or files[0].filename not in locked.files or not path.is_file():
        return f"The {card.pgs.pgs_id} scoring file is not fetched and locked. {fetch}."
    if fingerprint(path)["sha256"] != locked.files[files[0].filename].sha256:
        raise PgsError(f"The {card.pgs.pgs_id} scoring file does not match its lock; refetch it.")
    return path


@dataclass
class PolygenicStage:
    """Prepare (public, before ingest) and score (after imputation) every polygenic card."""

    references_root: Path | None = None
    tools_root: Path | None = None
    plink: Plink2 | None = None
    catalog: Catalog | None = None
    workers: int | None = None
    placement: PopulationResult | None = None
    """Injected only by tests; otherwise placed once per run from the export."""
    prepared: dict[str, Prepared] = field(default_factory=dict)

    def prepare(self, pack: KnowledgePack, progress: Callable[[str], None] | None = None) -> None:
        cards = [c for c in pack.cards if c.kind is CardKind.POLYGENIC]
        if not cards:
            return
        root = self.references_root if self.references_root is not None else references_dir()
        catalog = self.catalog
        catalog_reason = None
        if catalog is None:
            try:
                catalog = Catalog.default()
            except (PgsError, ProcessError) as exc:
                catalog_reason = (
                    f"PGS Catalog metadata is not available ({exc}). "
                    "`genetics refs fetch --only pgs_catalog_metadata`."
                )
        for card in cards:
            assert card.pgs is not None
            if catalog is None:
                self.prepared[card.id] = Prepared(card, reason=catalog_reason)
                continue
            located = locate_scoring_file(card, root)
            if isinstance(located, str):
                self.prepared[card.id] = Prepared(card, reason=located)
                continue
            if card.pgs.pgs_id not in catalog.scores:
                # Absent, not wrong: a metadata release older than the card. One card's
                # missing row must not abort every other finding in the run (M9.6 review).
                self.prepared[card.id] = Prepared(
                    card,
                    reason=f"The fetched PGS Catalog metadata has no row for {card.pgs.pgs_id}; "
                    "it predates the score or was not refreshed. "
                    "`genetics refs fetch --only pgs_catalog_metadata`.",
                )
                continue
            scoring = ScoringFile.open(located, catalog, pgs_id=card.pgs.pgs_id)
            terms = scoring.metadata.license
            if terms.status != "permissive":
                # `genetics pgs score --allow-restricted` is the explicit opt-in; a run has none.
                self.prepared[card.id] = Prepared(
                    card,
                    reason=f"The score's licence is {terms.status} and needs an explicit "
                    f"opt-in, which a run does not give: {terms.reason}",
                )
                continue
            scoring.inspect()
            if progress:
                progress(f"Preparing public reference for {card.pgs.pgs_id}")
            reference = prepare_reference(
                scoring, references_root=root, workers=self.workers, progress=progress
            )
            self.prepared[card.id] = Prepared(card, scoring, reference)

    def score(
        self,
        *,
        table: GenotypeTable,
        sex: InferredSex,
        dosages: Callable[[], Iterator[DosageRecord]] | None,
        ancestry: Mapping[str, Any],
        imputation_provenance: Mapping[str, Any] | None,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, AssembledCard], dict[str, dict[str, Any]]]:
        """Assembled polygenic cards and their private score records, by card id."""
        cards: dict[str, AssembledCard] = {}
        records: dict[str, dict[str, Any]] = {}
        runnable = [p for p in self.prepared.values() if p.scoring is not None]
        placement = self.placement
        if (
            runnable
            and placement is None
            and any(isinstance(p.reference, PreparedReference) for p in runnable)
        ):
            placement = place_among_reference_populations(
                table,
                references_root=self.references_root,
                tools_root=self.tools_root,
                progress=progress,
            )
        for item in self.prepared.values():
            if item.scoring is None:
                cards[item.card.id] = assemble_polygenic_card(item.card, None, reason=item.reason)
                continue
            if progress:
                progress(f"Scoring {item.scoring.headers['pgs_id']} with pinned PLINK")
            native = self.plink or Plink2.discover(tools_root=self.tools_root)
            result = score(
                item.scoring,
                table=table,
                dosages=None if dosages is None else dosages(),
                sex=sex,
                no_impute=dosages is None,
                plink=native,
                ancestry=ancestry,
                imputation_provenance=imputation_provenance,
                progress=progress,
            )
            result = attach_reference(
                result,
                item.scoring,
                table=table,
                prepared=item.reference,
                references_root=self.references_root,
                tools_root=self.tools_root,
                plink=native,
                placement=placement,
                progress=progress,
            )
            # The JSON form, so the in-memory record is exactly what the bundle persists.
            record = json.loads(json.dumps(result.to_dict(), allow_nan=False))
            records[item.card.id] = record
            cards[item.card.id] = assemble_polygenic_card(item.card, record)
        return cards, records
