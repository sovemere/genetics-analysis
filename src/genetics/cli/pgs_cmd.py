"""Offline PGS inspection, private native score sums and their variant coverage."""

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
    help=(
        "Inspect PGS definitions, compute private PLINK score sums and report coverage, "
        "reference placement and ancestry portability."
    ),
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
    no_reference: Annotated[
        bool,
        typer.Option(
            "--no-reference",
            help="Explicit opt-out of the 1000 Genomes reference distribution and percentile.",
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json", help="Emit private score JSON, including genotype-derived evidence."
        ),
    ] = False,
) -> None:
    """Compute PLINK sums before/after imputation, coverage and reference percentiles."""
    from genetics.ancestry.context import AncestryError
    from genetics.external.plink2 import Plink2Error
    from genetics.imputation.target import ImputationError
    from genetics.ingest.errors import IngestError
    from genetics.pgs.engine import result_destination, write_result
    from genetics.pgs.workflow import score_export, score_saved
    from genetics.run.bundle import BundleError

    try:
        if (input_path is None) == (run_path is None):
            raise PgsError("Choose exactly one of --input or --run.")
        if run_path is not None and no_impute:
            raise PgsError("--no-impute requires the original export, not a saved dosage stream.")
        destination = result_destination(output, allow_in_repo=allow_in_repo)
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
                reference=not no_reference,
                progress=progress,
            )
            if input_path is not None
            else score_saved(
                scoring,
                run_path,
                allow_restricted=allow_restricted,
                reference=not no_reference,
                progress=progress,
            )
            if run_path is not None
            else None
        )
        assert result is not None
        destination = write_result(result, destination, allow_in_repo=allow_in_repo)
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
        from genetics.pgs import reference
        from genetics.pgs.coverage import summary

        typer.echo(f"{result.pgs_id}: {result.status}. Private score saved to {destination}.")
        for line in summary(result.record["coverage"]):
            typer.echo(line)
        for line in reference.summary(result.record):
            typer.echo(line)
        from genetics.pgs.portability import summary as portability_summary

        for line in portability_summary(result.record["portability"]):
            typer.echo(line)


@pgs_app.command("coverage")
def coverage(
    result_path: Annotated[Path, typer.Argument(help="Private .pgs-score.json result.")],
    scoring_file: Annotated[
        Path | None,
        typer.Option(
            "--scoring-file", help="Also bind the denominator to this public scoring file."
        ),
    ] = None,
    metadata: Annotated[
        Path | None,
        typer.Option("--metadata", help="Explicit metadata archive or validated index."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit private coverage JSON (genotype-derived).")
    ] = False,
) -> None:
    """Validate a saved score's coverage against its term evidence, before and after."""
    from genetics.pgs.coverage import read_coverage, summary

    try:
        scoring = None
        if scoring_file is not None:
            catalog = (
                Catalog.default()
                if metadata is None
                else Catalog.load(metadata)
                if metadata.suffix == ".json"
                else Catalog.from_archive(metadata)
            )
            scoring = ScoringFile.open(scoring_file, catalog)
        report = read_coverage(result_path, scoring=scoring)
    except (PgsError, ProcessError) as exc:
        if as_json:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(json.dumps({"ok": True, **report}, indent=2))
    else:
        typer.echo(
            f"{report['pgs_id']}: coverage {report['coverage_origin']} "
            f"(score artifact schema {report['artifact_schema_version']})."
        )
        for line in summary(report["coverage"]):
            typer.echo(line)


@pgs_app.command("placement")
def placement(
    result_path: Annotated[Path, typer.Argument(help="Private .pgs-score.json result.")],
    scoring_file: Annotated[
        Path | None,
        typer.Option("--scoring-file", help="Also bind the result to this public scoring file."),
    ] = None,
    metadata: Annotated[
        Path | None,
        typer.Option("--metadata", help="Explicit metadata archive or validated index."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the private reference placement JSON.")
    ] = False,
) -> None:
    """Validate a saved score's reference distribution and report its percentiles."""
    from genetics.pgs.reference import read_placement, summary

    try:
        scoring = None
        if scoring_file is not None:
            catalog = (
                Catalog.default()
                if metadata is None
                else Catalog.load(metadata)
                if metadata.suffix == ".json"
                else Catalog.from_archive(metadata)
            )
            scoring = ScoringFile.open(scoring_file, catalog)
        report = read_placement(result_path, scoring=scoring)
    except (PgsError, ProcessError) as exc:
        if as_json:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(json.dumps({"ok": True, **report}, indent=2))
        return
    typer.echo(f"{report['pgs_id']}: score artifact schema {report['artifact_schema_version']}.")
    if report["reference_distribution"] is None:
        typer.echo("This result predates reference distributions; rescore it to place it.")
        return
    for line in summary(report):
        typer.echo(line)


@pgs_app.command("portability")
def portability(
    result_path: Annotated[Path, typer.Argument(help="Private .pgs-score.json result.")],
    scoring_file: Annotated[
        Path | None,
        typer.Option("--scoring-file", help="Also bind the result to this public scoring file."),
    ] = None,
    metadata: Annotated[
        Path | None,
        typer.Option("--metadata", help="Explicit metadata archive or validated index."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the private ancestry portability JSON.")
    ] = False,
) -> None:
    """Revalidate a saved score's study-to-sample ancestry portability (M9.5)."""
    from genetics.pgs.portability import read_portability, summary

    try:
        scoring = None
        if scoring_file is not None:
            catalog = (
                Catalog.default()
                if metadata is None
                else Catalog.load(metadata)
                if metadata.suffix == ".json"
                else Catalog.from_archive(metadata)
            )
            scoring = ScoringFile.open(scoring_file, catalog)
        report = read_portability(result_path, scoring=scoring)
    except (PgsError, ProcessError) as exc:
        if as_json:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(json.dumps({"ok": True, **report}, indent=2))
        return
    typer.echo(
        f"{report['pgs_id']}: score artifact schema {report['artifact_schema_version']}; "
        f"portability {report['portability_origin']}."
    )
    for line in summary(report["portability"]):
        typer.echo(line)
