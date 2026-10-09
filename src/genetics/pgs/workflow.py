"""Shared application orchestration for M9.2-M9.4; genotype-free progress only."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from genetics.ancestry.context import infer_ancestry
from genetics.imputation import impute
from genetics.ingest import ingest
from genetics.pgs.catalog import PgsError
from genetics.pgs.engine import ScoreResult, score, validate_mode_flags
from genetics.pgs.reference import attach_reference, prepare_reference
from genetics.pgs.scoring import ScoringFile
from genetics.qc.report import InferredSex
from genetics.run.bundle import read_bundle


def score_export(
    scoring: ScoringFile,
    input_path: Path,
    *,
    no_impute: bool = False,
    allow_restricted: bool = False,
    reference: bool = True,
    progress: Callable[[str], None] | None = None,
) -> ScoreResult:
    """Validate references first; infer ancestry before default-on imputation/scoring.

    Uses the same ingest, ancestry and imputation functions as the dashboard/analysis
    engine. A failing default imputation stage never becomes a direct-only score.
    """
    validate_mode_flags(no_impute, allow_restricted, reference)
    try:
        scoring.metadata.license.require_usable(opt_in=allow_restricted)
    except ValueError as exc:
        raise PgsError(str(exc)) from exc
    scoring.inspect()  # malformed reference files fail before reading a personal export
    # Public panel verification and extraction, before any personal input is read.
    prepared = prepare_reference(scoring, enabled=reference, progress=progress)
    result = ingest(input_path)
    ancestry = infer_ancestry(result.table, result.qc, progress=progress)
    stage = (
        None if no_impute else impute(result.table, sex=result.qc.sex.inferred, progress=progress)
    )
    if stage is not None and stage.original is not result.table:
        raise PgsError("Imputation returned observations for a different target.")
    scored = score(
        scoring,
        table=result.table,
        dosages=None if stage is None else stage.iter_dosages(),
        sex=result.qc.sex.inferred,
        no_impute=no_impute,
        allow_restricted=allow_restricted,
        ancestry=ancestry.to_dict(),
        imputation_provenance=None if stage is None else stage.metadata,
        progress=progress,
    )
    return attach_reference(
        scored, scoring, table=result.table, prepared=prepared, progress=progress
    )


def score_saved(
    scoring: ScoringFile,
    run_path: Path,
    *,
    allow_restricted: bool = False,
    reference: bool = True,
    progress: Callable[[str], None] | None = None,
) -> ScoreResult:
    """Score a validated saved full stage; original-array sums stay not recorded.

    With no original array the reference group cannot be placed, so the distribution is
    the pooled panel, labelled not ancestry-matched.
    """
    validate_mode_flags(allow_restricted, reference)
    try:
        scoring.metadata.license.require_usable(opt_in=allow_restricted)
    except ValueError as exc:
        raise PgsError(str(exc)) from exc
    scoring.inspect()
    prepared = prepare_reference(scoring, enabled=reference, progress=progress)
    bundle = read_bundle(run_path)
    if (
        bundle.imputation_provenance is None
        or bundle.imputation_provenance.get("status") != "recorded"
    ):
        raise PgsError(
            "Saved run has no full recorded dosages; use the original export to score it."
        )
    try:
        sex = InferredSex(bundle.qc["sex"]["inferred"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PgsError("Saved run lacks valid inferred-sex metadata.") from exc
    scored = score(
        scoring,
        table=None,
        dosages=bundle.iter_dosages(),
        sex=sex,
        allow_restricted=allow_restricted,
        ancestry=bundle.ancestry,
        imputation_provenance=bundle.imputation_provenance,
        progress=progress,
    )
    return attach_reference(scored, scoring, table=None, prepared=prepared, progress=progress)
