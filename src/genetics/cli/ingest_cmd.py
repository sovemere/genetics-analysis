"""``genetics ingest`` (roadmap M1.8).

Parse an export, run QC, print what was found. The CLI is the agent interface
(AGENTS.md section 3), so everything here is reachable as JSON.

**Nothing this command prints is a genotype**, and that is enforced rather than intended:
the JSON payload goes through :func:`~genetics.privacy.assert_no_genotype` on the way out.
The command handles the one file in the project that must never be echoed, so the guard
belongs at the boundary where the content would actually escape.

``--expect-counts`` is the local half of the M1.2 acceptance criterion. The owner's real
export must parse to 677,436 markers with 550 no-calls and 8,830 indel markers, and that
check cannot live in CI because the file can never be committed. So it lives here: assert
the counts, emit nothing but counts.

This module is imported lazily by the Typer app, so it may import Polars and the ingest
stack at module level without slowing down ``genetics --help``.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from genetics.ingest import IngestError, IngestResult, ingest
from genetics.ingest.registry import Adapter, detect
from genetics.privacy import assert_no_genotype
from genetics.qc import InferredSex, QCReport

_EXPECTED_KEYS = ("markers", "called", "no_calls", "indels")


def _parse_expectations(raw: str) -> dict[str, int]:
    """Parse ``markers=677436,no_calls=550,indels=8830`` into a dict.

    Named rather than positional because these numbers are easy to transpose, and a
    silently swapped pair would "pass" against the wrong quantity.
    """
    expectations: dict[str, int] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        key = key.strip().lower()
        if not sep:
            raise typer.BadParameter(
                f"{chunk!r} is not key=value. Expected e.g. "
                "'markers=677436,no_calls=550,indels=8830'."
            )
        if key not in _EXPECTED_KEYS:
            raise typer.BadParameter(f"unknown count {key!r}; known counts: {list(_EXPECTED_KEYS)}")
        try:
            expectations[key] = int(value.strip())
        except ValueError:
            raise typer.BadParameter(f"{key}={value.strip()!r} is not an integer") from None

    if not expectations:
        raise typer.BadParameter("--expect-counts was given no counts to check")
    return expectations


def actual_counts(qc: QCReport) -> dict[str, int]:
    """The counts ``--expect-counts`` can assert on. Counts only, by construction."""
    return {
        "markers": qc.call_rates.total_markers,
        "called": qc.call_rates.called,
        "no_calls": qc.call_rates.no_call,
        "indels": qc.indels.indel_markers,
    }


def _emit_json(payload: dict[str, object]) -> None:
    """Serialise and print, refusing to emit anything genotype-shaped.

    The guard is not theatre. This command's whole input is a genome, and the natural
    "just show me a few rows so I can check the parse" change would land right here.
    Failing the emit is the correct outcome for that change.
    """
    text = json.dumps(payload, indent=2, default=str)
    assert_no_genotype(text, context="genetics ingest --json output")
    typer.echo(text)


def run(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            "-i",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Raw vendor export.",
        ),
    ],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
    expect_counts: Annotated[
        str | None,
        typer.Option(
            "--expect-counts",
            help=(
                "Assert marker counts without emitting any genotype, e.g. "
                "'markers=677436,no_calls=550,indels=8830'. The local half of the M1.2 "
                "acceptance check."
            ),
        ),
    ] = None,
) -> None:
    """Parse a raw DNA export into the normalized table and report QC.

    Prints counts, rates and inferred sex. Never prints a genotype.
    """
    expectations = _parse_expectations(expect_counts) if expect_counts else None

    try:
        adapter = detect(input_path)
        result = ingest(input_path)
    except IngestError as exc:
        # The message is genotype-free by construction (see genetics.ingest.errors), so it
        # is safe to show. A traceback here would be noise: these are expected refusals,
        # not crashes.
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None

    qc = result.qc
    assert isinstance(qc, QCReport)
    actual = actual_counts(qc)

    mismatches = (
        {key: expected for key, expected in expectations.items() if actual[key] != expected}
        if expectations
        else {}
    )

    if as_json:
        payload: dict[str, object] = {
            "source": asdict(result.source),
            "adapter": {
                "vendor_id": adapter.vendor_id,
                "display_name": adapter.display_name,
                "verified_against_real_export": adapter.verified_against_real_export,
            },
            "qc": qc.to_dict(),
        }
        if expectations is not None:
            payload["expect_counts"] = {
                "expected": expectations,
                "actual": {key: actual[key] for key in expectations},
                "ok": not mismatches,
            }
        _emit_json(payload)
    else:
        _render(result, adapter, qc, actual, expectations, mismatches)

    raise typer.Exit(code=1 if mismatches else 0)


def _render(
    result: IngestResult,
    adapter: Adapter,
    qc: QCReport,
    actual: dict[str, int],
    expectations: dict[str, int] | None,
    mismatches: dict[str, int],
) -> None:
    typer.secho(f"{adapter.display_name}", bold=True, nl=False)
    typer.echo(f"  ({result.source.path})")

    if not adapter.verified_against_real_export:
        typer.secho(
            "  note: this adapter has only ever been run against a synthetic fixture. "
            "It is not verified against a real export from this vendor.",
            fg=typer.colors.YELLOW,
        )

    array = result.source.array_version or "unspecified"
    typer.echo(f"  build {result.source.build}, array {array}")
    typer.echo("")

    rates = qc.call_rates
    typer.echo(f"  markers      {rates.total_markers:,}")
    typer.echo(f"  called       {rates.called:,}  ({rates.call_rate:.4%})")
    typer.echo(f"  no-calls     {rates.no_call:,}")
    typer.echo(f"  indels       {qc.indels.indel_markers:,}  (excluded from matching by default)")
    typer.echo("")

    het = qc.heterozygosity
    typer.echo(
        f"  autosomal heterozygosity  {het.autosomal_het_rate:.4f} "
        f"over {het.autosomal_loci:,} SNP loci"
    )

    sex_colour = typer.colors.YELLOW if qc.sex.inferred is InferredSex.AMBIGUOUS else None
    typer.secho(f"  inferred sex              {qc.sex.inferred.value}", fg=sex_colour)
    typer.echo(
        f"    X heterozygosity (non-PAR)  {qc.sex.x_het_rate:.4f} "
        f"over {qc.sex.x_nonpar_loci:,} loci"
    )
    typer.echo(
        f"    Y call rate                 {qc.sex.y_call_rate:.4f} over {qc.sex.y_loci:,} loci"
    )
    for note in qc.sex.notes:
        typer.echo(f"    - {note}")

    typer.echo("")
    typer.echo(f"  build check  declared {qc.build.declared}, verdict {qc.build.verdict}")
    if qc.build.anchors_available == 0:
        typer.echo(
            "    no verified coordinate anchors yet -- M2 supplies them from dbSNP. "
            "The header assertion and the coordinate-bounds check both passed."
        )

    if qc.warnings:
        typer.echo("")
        typer.secho("  warnings", bold=True)
        for warning in qc.warnings:
            typer.secho(f"    ! {warning}", fg=typer.colors.YELLOW)

    if expectations is not None:
        typer.echo("")
        typer.secho("  expected counts", bold=True)
        for key, expected in expectations.items():
            ok = actual[key] == expected
            typer.secho(
                f"    {'ok  ' if ok else 'FAIL'} {key:<10} "
                f"expected {expected:,}, got {actual[key]:,}",
                fg=typer.colors.GREEN if ok else typer.colors.RED,
            )
        if mismatches:
            typer.secho(
                "  Counts do not match. Either the adapter is wrong or this is not the "
                "file those counts describe. Do not proceed on the assumption that it "
                "parsed correctly.",
                fg=typer.colors.RED,
            )
