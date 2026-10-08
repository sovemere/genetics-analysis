"""Offline inspection of public PGS references. No personal score is computed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from genetics.pgs.catalog import Catalog, PgsError
from genetics.pgs.scoring import ScoringFile
from genetics.refs.postprocess import ProcessError

pgs_app = typer.Typer(
    name="pgs", help="Inspect PGS scoring files and per-score terms (M9.1).", no_args_is_help=True
)


@pgs_app.command("inspect")
def inspect_score(
    scoring_file: Annotated[
        Path, typer.Argument(help="Public PGS scoring file (.txt or .txt.gz).")
    ],
    metadata: Annotated[
        Path | None,
        typer.Option(
            "--metadata",
            help="Explicit metadata archive or validated index; defaults to fetched Catalog.",
        ),
    ] = None,
    pgs_id: Annotated[
        str | None, typer.Option("--pgs-id", help="Require this score identity.")
    ] = None,
    build: Annotated[
        str, typer.Option("--build", help="Required effective coordinate build.")
    ] = "GRCh37",
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Validate all rows, report provenance and terms, and flag special models."""
    try:
        catalog = (
            Catalog.default()
            if metadata is None
            else Catalog.load(metadata)
            if metadata.suffix == ".json"
            else Catalog.from_archive(metadata)
        )
        result = ScoringFile.open(
            scoring_file, catalog, pgs_id=pgs_id, expected_build=build
        ).inspect()
    except (PgsError, ProcessError) as exc:
        if as_json:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(json.dumps({"ok": True, **result}, indent=2))
    else:
        terms = result["metadata"]["license"]
        typer.echo(
            f"{result['pgs_id']}: {result['rows']} rows, {result['build']}; "
            f"licence {terms['status']}"
        )
        typer.echo(terms["reason"])
        typer.echo("Parsed reference only; personal scoring is not implemented (M9.2).")
        for feature, count in result["features"].items():
            typer.echo(f"  {feature}: {count} rows")
