"""CLI for reviewing the committed knowledge pack (roadmap M3.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

cards_app = typer.Typer(
    name="cards",
    help="Validate the declarative knowledge pack.",
    no_args_is_help=True,
    add_completion=False,
)


@cards_app.command("lint")
def lint(
    knowledge: Annotated[
        Path | None,
        typer.Option(
            "--knowledge",
            file_okay=False,
            readable=True,
            help="Knowledge directory. Defaults to the committed knowledge/ pack.",
        ),
    ] = None,
    variant_index: Annotated[
        Path | None,
        typer.Option(
            "--variant-index",
            dir_okay=False,
            readable=True,
            help="dbSNP-derived Parquet index. Defaults beside the fetched dbSNP source.",
        ),
    ] = None,
    schema_only: Annotated[
        bool,
        typer.Option(
            "--schema-only",
            help=(
                "Skip dbSNP key resolution explicitly. Intended for offline CI; full lint "
                "fails if the reference index is unavailable."
            ),
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Check schema, citations, templates, and dbSNP variant keys."""

    from genetics.engine.card_lint import (
        ParquetVariantResolver,
        default_variant_index,
        lint_directory,
    )
    from genetics.engine.cards import default_knowledge_dir

    if schema_only and variant_index is not None:
        raise typer.BadParameter(
            "--variant-index and --schema-only are mutually exclusive: one requests "
            "resolution and the other disables it"
        )

    root = knowledge or default_knowledge_dir()
    resolver = None
    if not schema_only:
        resolver = ParquetVariantResolver(
            variant_index or default_variant_index(),
            bind_to_manifest=variant_index is None,
        )
    report = lint_directory(root, resolver=resolver, resolve_variants=not schema_only)

    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        colour = typer.colors.GREEN if report.ok else typer.colors.RED
        label = "PASS" if report.ok else "FAIL"
        typer.secho(
            f"{label}  {report.card_count} card(s), {report.rendered_templates} template render(s)",
            fg=colour,
            bold=True,
        )
        if report.variant_resolution.value == "skipped":
            typer.secho(
                "  variant keys: SKIPPED (--schema-only)",
                fg=typer.colors.YELLOW,
            )
        else:
            typer.echo(
                f"  variant keys: {report.resolved_variants}/"
                f"{report.interpretation_count} resolved via {report.resolver or 'no resolver'}"
            )
        for issue in report.issues:
            owner = f" [{issue.card_id}]" if issue.card_id else ""
            typer.secho(f"  {issue.code}{owner}: {issue.message}", fg=typer.colors.RED)

    if not report.ok:
        raise typer.Exit(code=1)
