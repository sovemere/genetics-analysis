"""Offline public PGx reference commands; no personal input or calling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from genetics.refs.postprocess import ProcessError

pgx_app = typer.Typer(
    help="Inspect public pharmacogenomic definitions and phenotype mappings.", no_args_is_help=True
)


@pgx_app.command("prepare")
def prepare(
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit reference provenance JSON.")
    ] = False,
) -> None:
    """Join fetched CPIC/ClinPGx definitions with verified dbSNP GRCh37 keys."""
    from genetics.pgx.catalog import prepare as prepare_catalog

    try:
        output, status = prepare_catalog()
    except (ProcessError, OSError, ValueError, pl.exceptions.PolarsError) as exc:
        _error(exc, as_json)
    else:
        typer.echo(
            json.dumps({"ok": True, "output": str(output), "status": status})
            if as_json
            else f"PGx reference {status}: {output}"
        )


def _error(exc: Exception, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps({"ok": False, "error": str(exc)}))
    else:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1) from exc


@pgx_app.command("inspect")
def inspect(
    reference: Annotated[
        Path | None,
        typer.Option(
            "--reference",
            help="Explicit frozen public reference; otherwise use manifest-bound default.",
        ),
    ] = None,
    gene: Annotated[str | None, typer.Option("--gene", help="CPIC gene symbol.")] = None,
    allele: Annotated[str | None, typer.Option("--allele", help="Reference allele name.")] = None,
    diplotype: Annotated[
        str | None,
        typer.Option(
            "--diplotype", help="Reference diplotype label; this command computes no sample call."
        ),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit public definitions, mappings and provenance.")
    ] = False,
) -> None:
    """Validate and inspect a complete saved public reference offline."""
    from genetics.pgx.catalog import Catalog

    try:
        catalog = Catalog.default() if reference is None else Catalog.load(reference)
        report = catalog.inspect(gene=gene, allele=allele, diplotype=diplotype)
    except (ProcessError, OSError, ValueError) as exc:
        _error(exc, as_json)
    else:
        if as_json:
            typer.echo(json.dumps({"ok": True, **report}, indent=2))
        else:
            counts = report["counts"]
            typer.echo(
                f"GRCh37 forward-strand reference: {counts['definitions']} definitions; "
                "sample calling is M10.2."
            )
            for state, count in counts["definition_states"].items():
                typer.echo(f"  {state}: {count}")
            if gene:
                for definition in report["definitions"]:
                    typer.echo(
                        f"  {gene} {definition['source_definition']['name']}: "
                        f"{definition['state']}; {definition['function_state']}"
                    )
            if diplotype:
                typer.echo(f"Mapping: {report['mapping_status']}")
                for mapping in report["diplotype_mappings"]:
                    typer.echo(f"  CPIC reference phenotype: {mapping['phenotype']['result']}")
