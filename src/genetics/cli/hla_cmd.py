"""Inspect public HIBAG classifier metadata and private frozen sample evidence."""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer

hla_app = typer.Typer(
    help="HIBAG classifier metadata and saved HLA imputation.", no_args_is_help=True
)


@hla_app.command("calls")
def calls(
    run_id: Annotated[str, typer.Argument(help="Saved run ID.")],
    as_json: Annotated[bool, typer.Option("--json", help="Private frozen HLA evidence.")] = False,
) -> None:
    from genetics.hla.calling import report
    from genetics.hla.models import HLAError
    from genetics.run import store
    from genetics.run.bundle import BundleError

    try:
        data = report(store.load_run(run_id).hla)
    except (BundleError, HLAError, OSError, ValueError):
        _fail(as_json)
    else:
        if as_json:
            typer.echo(json.dumps(data, indent=2, allow_nan=False))
        else:
            typer.echo(f"HLA: {data['status']}")
            if data["reason"]:
                typer.echo(data["reason"])
            choice = data.get("selection")
            if choice is not None:
                typer.echo(
                    f"Ancestry selection: {choice['status']}; classifier "
                    f"{choice['classifier'] or 'none'} ({choice['basis'] or 'not selected'}); "
                    f"ancestry match {_value(choice['ancestry_match'])}"
                )
                typer.echo("  " + choice["reason"])
            elif data.get("reference"):
                typer.echo(
                    "Explicit classifier: "
                    + data["reference"]["source"]["population"]
                    + "; ancestry selection and call confidence not recorded (HLA schema 1)."
                )
            if data.get("reference"):
                typer.echo(
                    "Two-field, unphased model predictions; posterior is not clinical accuracy."
                )
            for gene, row in data["genes"].items():
                pair = " / ".join(row["alleles"]) if row["alleles"] else "unavailable"
                typer.echo(
                    f"{gene}: {row['status']}; {pair}; joint posterior {row['posterior']}; "
                    f"{row['observed_markers']}/{row['model_markers']} model markers observed"
                )
                if "confidence" in row:
                    typer.echo("  " + _ceiling(row["confidence"]))
                typer.echo("  Marker states: " + json.dumps(row["coverage"], sort_keys=True))


def _value(value: float | None) -> str:
    return "unknown" if value is None else f"{value:g}"


def _ceiling(confidence: dict[str, Any]) -> str:
    if confidence["status"] != "computed":
        return "Confidence not computed: no prediction, which is not evidence against any allele."
    ceiling = confidence["ceiling"] or "none"
    lowered = ", ".join(confidence["ceilings"]) or "nothing"
    side = "meets" if confidence["meets_published_call_threshold"] else "is below"
    return (
        f"Observation ceiling: {ceiling} (lowered by {lowered}); posterior {side} the "
        f"published {confidence['published_call_threshold']:g} call threshold; marker "
        f"coverage {confidence['marker_coverage']:.0%}; ancestry match "
        f"{_value(confidence['ancestry_match'])}"
    )


def _fail(as_json: bool) -> None:
    message = "HLA evidence could not be validated; inspect prerequisites and saved-run integrity."
    if as_json:
        typer.echo(json.dumps({"ok": False, "error": {"kind": "hla", "message": message}}))
    else:
        typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@hla_app.command("inspect")
def inspect(
    classifier: Annotated[str, typer.Option("--classifier", help="Explicit model population.")],
    model_opt_in: Annotated[
        bool, typer.Option("--model-opt-in", help="Acknowledge unspecified model terms.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    from genetics.external.hibag import HIBAGError
    from genetics.hla.calling import HLAStage
    from genetics.hla.models import HLAError

    try:
        stage = HLAStage(classifier, model_opt_in)
        stage.prepare()
    except (HLAError, HIBAGError, OSError, ValueError):
        _fail(as_json)
    else:
        data = {
            "status": "available" if stage.reference is not None else "unavailable",
            "reason": None if stage.reference is not None else stage.reason,
            "reference": stage.reference,
        }
        typer.echo(
            json.dumps(data, indent=2)
            if as_json
            else f"HLA classifier: {data['status']}; {data['reason']}"
        )
