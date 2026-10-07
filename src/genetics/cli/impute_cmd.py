"""Genotype-free CLI summary for the shared private M8.3 stage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer


def impute_command(
    input_path: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    panel_catalog: Annotated[Path | None, typer.Option("--panel-catalog")] = None,
    map_catalog: Annotated[Path | None, typer.Option("--map-catalog")] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Stable private job prefix outside the repository."),
    ] = None,
    memory_mb: Annotated[int, typer.Option("--memory-mb", min=512)] = 8192,
    threads: Annotated[int, typer.Option("--threads", min=1)] = 1,
    seed: Annotated[int, typer.Option("--seed")] = -99999,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Phase then impute with full prepared panels; save private dosages and quality."""
    from genetics.external.beagle import BeagleError, BeagleOptions
    from genetics.imputation import ImputationError, PreparedReference, impute
    from genetics.ingest import IngestError, ingest
    from genetics.privacy import assert_no_genotype
    from genetics.refs.postprocess import ProcessError

    def progress(message: str) -> None:
        assert_no_genotype(message, context="imputation progress")
        typer.echo(message, err=True)

    try:
        if (panel_catalog is None) != (map_catalog is None):
            raise ValueError("Custom imputation requires both prepared catalogs.")
        reference = (
            PreparedReference(panel_catalog, map_catalog)
            if panel_catalog is not None and map_catalog is not None
            else None
        )
        parsed = ingest(input_path)
        result = impute(
            parsed.table,
            sex=parsed.qc.sex.inferred,
            reference=reference,
            options=BeagleOptions(memory_mb=memory_mb, nthreads=threads, seed=seed),
            out=out,
            progress=progress,
        )
        payload = {"ok": True, "directory": str(result.directory), **result.summary()}
        text = json.dumps(payload, indent=2, allow_nan=False)
        assert_no_genotype(text, context="imputation summary")
        if as_json:
            typer.echo(text)
        else:
            typer.echo(
                f"Imputation: {payload['status']}; {payload['jobs']} completed region jobs.\n"
                f"Private outputs: {result.directory}"
            )
    except (ValueError, OSError, BeagleError, ProcessError, IngestError) as exc:
        # Raw IO/tool diagnostics and source filenames can themselves contain calls.
        message = (
            str(exc)
            if isinstance(exc, ImputationError | BeagleError)
            else "Imputation failed; verify input, prepared panels/maps and pinned tools."
        )
        assert_no_genotype(message, context="imputation failure")
        if as_json:
            typer.echo(
                json.dumps({"ok": False, "error": {"kind": "imputation", "message": message}})
            )
        else:
            typer.echo(message, err=True)
        raise typer.Exit(2) from None
