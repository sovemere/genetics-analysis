"""``genetics run`` -- the whole pipeline, one command (roadmap M4.0).

Ingest, match, assemble, save. The pipeline itself lives in
:mod:`genetics.run.pipeline`; what is decided here is only what a person and an agent see
when it finishes.

**Nothing this command prints is a genotype**, and it is scanned rather than trusted, on
*both* branches -- the same shape as ``genetics ingest`` (M1.8), for the same reason and
against the same mistake. This command is the one whose whole input is a genome, and the
natural "show me the cards that matched" change lands right here. Failing the emit is the
correct outcome for that change: the cards are on disk and ``genetics runs show`` is the
command that prints them, deliberately exempt from the scan because a card's summary states
the reader's own genotype by design (M4.2).

So the output is aggregates: QC, counts by match status, counts by confidence tier, and the
run id. Counts are the honest thing to show anyway -- what a person wants from a pipeline
command is whether it worked and where the result went, not the result.

**Every status is printed, including the zeros.** A status that disappears when it is empty
makes "nothing was strand-ambiguous" indistinguishable from "strand ambiguity is not
checked", which is the class of silence AGENTS.md 0.1A exists to prevent. The same argument
covers the tier breakdown.

**There is no ``--runs-root``.** The store is addressed through ``GENETICS_DATA_DIR``, as
M4.2 settled: a test-only way to name the store is a second name for one thing, and these
tests would then exercise a path no user takes. There is no ``--run-id`` either -- ids are
generated (M4.1), and a flag whose only caller is a test is the same mistake wearing a
different hat.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from genetics.engine.cards import CardError
from genetics.engine.evidence import EvidenceAssemblyError
from genetics.ingest import IngestError
from genetics.privacy import assert_no_genotype
from genetics.qc import AnchorError, InferredSex
from genetics.run.bundle import BundleError
from genetics.run.pipeline import Analysis, analyse, save


def _echo(text: str = "", **kwargs: object) -> None:
    """Guarded ``typer.secho``. See this module's docstring for what it is guarding."""
    assert_no_genotype(text, context="genetics run output")
    typer.secho(text, **kwargs)  # type: ignore[arg-type]


def _error_kind(exc: Exception) -> str:
    """A stable machine-readable name for a failure, mirroring ``runs_cmd._error_kind``.

    The distinction that has to survive into ``--json`` is *which stage* refused. "Your
    export is malformed", "your knowledge pack is malformed" and "the disk is full" are
    three different things for an agent to do next, and prose is not something it can
    branch on.
    """
    if isinstance(exc, IngestError | AnchorError):
        return "ingest"
    if isinstance(exc, CardError):
        return "knowledge"
    if isinstance(exc, EvidenceAssemblyError):
        return "assembly"
    if isinstance(exc, BundleError):
        return "bundle"
    if isinstance(exc, OSError):
        return "io"
    return "run"


def _fail(exc: Exception, *, as_json: bool) -> NoReturn:
    """Report a refusal without a traceback.

    Every exception named in :func:`_error_kind` carries a genotype-free message by
    construction (``genetics.ingest.errors``, and the engine's own refusals name card ids
    rather than calls), but the message is scanned anyway: this is a boundary where data
    leaves the process, and the guard belongs at the boundary rather than in an argument
    about which of five exception types could ever carry a call.
    """
    message = str(exc)
    assert_no_genotype(message, context="genetics run error output")
    if as_json:
        payload = {"ok": False, "error": {"kind": _error_kind(exc), "message": message}}
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


def _payload(analysis: Analysis, path: Path) -> dict[str, Any]:
    return {
        "ok": True,
        "run_id": path.name,
        "path": str(path),
        "input": {
            "path": analysis.source.path,
            "vendor": analysis.source.vendor,
            "build": analysis.source.build,
            "array_version": analysis.source.array_version,
        },
        "qc": analysis.qc.to_dict(),
        "cards": {
            "total": analysis.n_cards,
            "with_interpretation": analysis.with_interpretation,
            "by_status": {status.value: count for status, count in analysis.status_counts.items()},
            "by_confidence_tier": {
                tier.value: count for tier, count in analysis.tier_counts.items()
            },
        },
    }


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
    knowledge: Annotated[
        Path | None,
        typer.Option(
            "--knowledge",
            file_okay=False,
            readable=True,
            help="Knowledge directory. Defaults to the committed knowledge/ pack.",
        ),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Analyse an export and save the result as an immutable run bundle.

    Prints QC, card counts and the new run id. Never prints a genotype -- read the cards
    with `genetics runs show <run-id>`.
    """
    try:
        analysis = analyse(input_path, knowledge_dir=knowledge)
        path = save(analysis)
    except (
        IngestError,
        AnchorError,
        CardError,
        EvidenceAssemblyError,
        BundleError,
        OSError,
    ) as exc:
        _fail(exc, as_json=as_json)

    if as_json:
        text = json.dumps(_payload(analysis, path), indent=2, default=str)
        assert_no_genotype(text, context="genetics run --json output")
        typer.echo(text)
        return

    _render(analysis, path)


def _render(analysis: Analysis, path: Path) -> None:
    qc = analysis.qc
    rates = qc.call_rates

    _echo(f"{analysis.source.vendor}", bold=True, nl=False)
    _echo(f"  ({analysis.source.path})")
    _echo(f"  {rates.total_markers:,} markers, {rates.call_rate:.4%} called")

    sex_colour = typer.colors.YELLOW if qc.sex.inferred is InferredSex.AMBIGUOUS else None
    _echo(f"  inferred sex  {qc.sex.inferred.value}", fg=sex_colour)

    if qc.warnings:
        _echo("")
        for warning in qc.warnings:
            _echo(f"  ! {warning}", fg=typer.colors.YELLOW)

    _echo("")
    _echo(f"  {analysis.n_cards} card(s) from {analysis.pack.source_dir}")
    for status, count in analysis.status_counts.items():
        _echo(f"    {count:>6}  {status.value}")

    if analysis.with_interpretation:
        _echo("")
        _echo("  confidence tiers", bold=True)
        for tier, count in analysis.tier_counts.items():
            _echo(f"    {count:>6}  {tier.value}")
    else:
        # Not an error, and said plainly rather than left as a table of zeros to interpret.
        # A run where nothing matched is the expected result against a synthetic fixture,
        # and the reason is almost always the one named here.
        _echo("")
        _echo(
            "  No card produced an interpretation. Every card is reported above with the "
            "reason -- marker_absent means the position is not on this array and says "
            "nothing about the person.",
            fg=typer.colors.YELLOW,
        )

    empty = analysis.pack.empty_sections
    if empty:
        _echo("")
        _echo(
            f"  {len(empty)} section(s) have no cards yet: "
            + ", ".join(section.value for section in empty),
        )

    _echo("")
    _echo(f"  saved  {path.name}", fg=typer.colors.GREEN, bold=True)
    _echo(f"         {path}")
    _echo(f"  read it with:  genetics runs show {path.name}")
