"""Offline PGS inspection and private, provenance-bound native score sums."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from genetics.pgs.catalog import Catalog, PgsError
from genetics.pgs.scoring import ScoringFile
from genetics.refs.postprocess import ProcessError

pgs_app = typer.Typer(
    name="pgs",
    help="Inspect PGS definitions and compute private PLINK score sums.",
    no_args_is_help=True,
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
        typer.echo("Reference parsed. Use `genetics pgs score` to compute private sums.")
        for feature, count in result["features"].items():
            typer.echo(f"  {feature}: {count} rows")


@pgs_app.command("score")
def score_pgs(
    scoring_file: Annotated[Path, typer.Argument(help="Public PGS scoring file.")],
    input_path: Annotated[
        Path | None, typer.Option("--input", help="Original consumer DNA export.")
    ] = None,
    run_path: Annotated[
        Path | None, typer.Option("--run", help="Saved format-16 run directory with full dosages.")
    ] = None,
    metadata: Annotated[
        Path | None,
        typer.Option("--metadata", help="Explicit metadata archive or validated index."),
    ] = None,
    no_impute: Annotated[
        bool, typer.Option("--no-impute", help="Explicit direct-only development/testing mode.")
    ] = False,
    allow_restricted: Annotated[
        bool,
        typer.Option(
            "--allow-restricted",
            help="Opt in to recognized restricted terms; unknown terms remain refused.",
        ),
    ] = False,
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Private .pgs-score.json; defaults outside the checkout."),
    ] = None,
    allow_in_repo: Annotated[
        bool,
        typer.Option("--allow-in-repo", help="Explicit opt-in for an ignored in-repo result file."),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json", help="Emit private score JSON, including genotype-derived evidence."
        ),
    ] = False,
) -> None:
    """Compute PLINK sums before/after imputation; save private evidence and provenance."""
    from genetics.ancestry.context import AncestryError
    from genetics.external.plink2 import Plink2Error
    from genetics.imputation.target import ImputationError
    from genetics.ingest.errors import IngestError
    from genetics.pgs.engine import write_result
    from genetics.pgs.workflow import score_export, score_saved
    from genetics.run.bundle import BundleError

    try:
        if (input_path is None) == (run_path is None):
            raise PgsError("Choose exactly one of --input or --run.")
        if run_path is not None and no_impute:
            raise PgsError("--no-impute requires the original export, not a saved dosage stream.")
        catalog = (
            Catalog.default()
            if metadata is None
            else Catalog.load(metadata)
            if metadata.suffix == ".json"
            else Catalog.from_archive(metadata)
        )
        scoring = ScoringFile.open(scoring_file, catalog)

        def progress(message: str) -> None:
            typer.echo(message, err=True)

        result = (
            score_export(
                scoring,
                input_path,
                no_impute=no_impute,
                allow_restricted=allow_restricted,
                progress=progress,
            )
            if input_path is not None
            else score_saved(
                scoring, run_path, allow_restricted=allow_restricted, progress=progress
            )
            if run_path is not None
            else None
        )
        assert result is not None
        destination = write_result(result, output, allow_in_repo=allow_in_repo)
    except (
        PgsError,
        ProcessError,
        IngestError,
        AncestryError,
        ImputationError,
        Plink2Error,
        BundleError,
    ) as exc:
        if as_json:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(
            json.dumps({"ok": True, "output": str(destination), **result.to_dict()}, indent=2)
        )
    else:
        typer.echo(f"{result.pgs_id}: {result.status}. Private score saved to {destination}.")
