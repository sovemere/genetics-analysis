"""``genetics runs`` -- list, read and delete saved runs (roadmap M4.2).

Scope, so the next author does not build it twice: this is the *store* surface. M13.1 owns
the analysis surface on top of it -- ``show --section``, ``card <run> <card-id>``,
``evidence``, ``search`` -- and M13.2 owns pinning the JSON as a versioned schema. ``runs
show`` here is deliberately thin: it exists because a store you can list and delete but
never read is not a store, and because M4.2's "or fail with a clear version error" is a
promise about what a *user* sees, which takes a command someone can actually run.

**The privacy split is inherited from the bundle format rather than reinvented.** ``runs
list`` is scanned with ``assert_no_genotype`` on both output paths; ``runs show`` is not.
That is a decision in both directions, not an oversight in one:

* Listing is manifest-derived, and the manifest is the file a person pastes into a bug
  report. The writer already scans it, but that scan is a property of the writer -- a bundle
  read here may have been written by another version or edited by hand, so the boundary is
  checked where data leaves the process, which is what :mod:`genetics.privacy` is for. Both
  branches are scanned because M1.8 got exactly this wrong: the first cut of ``genetics
  ingest`` guarded the JSON branch and left the human render open, which is the branch a
  person is *more* likely to edit.
* ``show`` renders per-card results, and a card's summary states what the reader's genotype
  is -- that is the product, not a leak. Scanning it would be a guard that fails on correct
  output, and M0.3 settled what happens to those: they get switched off, including on the
  day they were right. A bundle is raw DNA (AGENTS.md 1.1) and belongs to the person running
  the command; keeping it off their own screen protects nobody.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, NoReturn

import typer

from genetics.privacy import assert_no_genotype
from genetics.run import store
from genetics.run.bundle import (
    BundleError,
    BundleIntegrityError,
    BundleVersionError,
    RunBundle,
)
from genetics.run.store import RunNotFoundError, RunStatus

runs_app = typer.Typer(
    name="runs",
    help="List, inspect and delete saved analysis runs (M4.2).",
    no_args_is_help=True,
)

_STATUS_COLOURS: dict[RunStatus, str] = {
    RunStatus.READABLE: typer.colors.GREEN,
    RunStatus.FUTURE_VERSION: typer.colors.YELLOW,
    RunStatus.DAMAGED: typer.colors.RED,
}


def _size(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1e9:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1e6:.1f} MB"
    return f"{n:,} B"


def _error_kind(exc: Exception) -> str:
    """A stable machine-readable name for a failure.

    ``version`` is the one that has to survive: M4.2 requires "written by a newer engine"
    to be distinguishable from "this file is damaged", and an agent reading ``--json``
    cannot draw that distinction out of prose.

    ``io`` exists because the store raises ``OSError``, not ``BundleError``, when the disk
    refuses -- a locked file on Windows, a permission change, a removable drive that is no
    longer there. Catching only ``BundleError`` here meant the commands most likely to meet
    that (``show`` opens every payload to digest it, ``delete`` removes a directory tree)
    printed a traceback instead of a sentence.
    """
    if isinstance(exc, BundleVersionError):
        return "version"
    if isinstance(exc, RunNotFoundError):
        return "not-found"
    if isinstance(exc, BundleIntegrityError):
        return "integrity"
    if isinstance(exc, OSError):
        return "io"
    return "bundle"


def _refuse(kind: str, message: str, *, as_json: bool, code: int = 1) -> NoReturn:
    if as_json:
        payload = {"ok": False, "error": {"kind": kind, "message": message}}
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=code)


def _fail(exc: Exception, *, as_json: bool) -> NoReturn:
    _refuse(_error_kind(exc), str(exc), as_json=as_json)


# ---------------------------------------------------------------------------
# runs list
# ---------------------------------------------------------------------------


@runs_app.command("list")
def runs_list(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
    verify: Annotated[
        bool,
        typer.Option(
            "--verify",
            help=(
                "Re-read every bundle and check its payload digests. Slower; the default "
                "reads manifests only."
            ),
        ),
    ] = False,
) -> None:
    """List saved runs, newest first.

    Reports rather than fails. A damaged or newer-format bundle becomes a row with a status,
    because this is the command someone runs when something is already wrong -- and a
    listing that refused to render because one directory out of forty is corrupt would hide
    the other thirty-nine.

    Without ``--verify``, ``readable`` means the manifest parsed and the payload files it
    names are present. It does not mean they are intact.
    """
    listing = store.list_runs(verify=verify)

    if as_json:
        text = json.dumps(listing.to_dict(), indent=2)
        assert_no_genotype(text, context="runs list JSON output")
        typer.echo(text)
        return

    rows: list[tuple[str, str | None]] = [(f"runs in {listing.root}", None)]
    if not listing.runs:
        rows.append(("  (none saved yet)", None))

    for run in listing.runs:
        cards = "-" if run.card_count is None else f"{run.card_count} card(s)"
        interpreted = (
            "" if run.with_interpretation is None else f", {run.with_interpretation} interpreted"
        )
        rows.append(
            (
                f"  {run.status:<15}{run.run_id:<28} "
                f"{run.created_at or '(no timestamp)':<22} {cards}{interpreted}  "
                f"{run.vendor or ''}".rstrip(),
                _STATUS_COLOURS[run.status],
            )
        )
        if run.detail:
            rows.append((f"      {run.detail}", None))

    if listing.incomplete:
        total = sum(item.size_bytes for item in listing.incomplete)
        rows.append(("", None))
        rows.append(
            (
                f"{len(listing.incomplete)} interrupted save(s) holding {_size(total)}. "
                "Nothing was saved under those ids; remove them with `genetics runs prune`:",
                typer.colors.YELLOW,
            )
        )
        rows.extend(
            (f"      {item.path.name}  {_size(item.size_bytes)}", None)
            for item in listing.incomplete
        )

    if listing.damaged:
        rows.append(("", None))
        rows.append(
            (
                f"{len(listing.damaged)} of {len(listing.runs)} run(s) could not be read.",
                typer.colors.YELLOW,
            )
        )
    if listing.needs_a_newer_engine:
        # A separate line with a separate remedy. Counting these as "could not be read"
        # pointed the user at a backup when what they need is the version of the tool that
        # wrote the bundle -- the distinction RunStatus exists to preserve, thrown away in
        # the footer that summarises it.
        rows.append(("", None))
        rows.append(
            (
                f"{len(listing.needs_a_newer_engine)} run(s) were written by a newer version "
                "of this tool. They are intact; open them with the version that wrote them.",
                typer.colors.YELLOW,
            )
        )

    # Assembled, scanned, then written. A per-line echo would have put half the output on
    # stdout before the first check ran, which is a guard that only works on short lists.
    assert_no_genotype("\n".join(text for text, _ in rows), context="runs list output")
    for text, colour in rows:
        typer.secho(text, fg=colour)


# ---------------------------------------------------------------------------
# runs show
# ---------------------------------------------------------------------------


def _bundle_payload(bundle: RunBundle) -> dict[str, Any]:
    """The whole record, as data.

    Mappings are copied into plain dicts rather than re-serialised through a schema: what
    was written is what a reader of a months-old bundle must get back, and a projection
    maintained here would be a second description of the payload, drifting against the one
    in :mod:`genetics.run.bundle`.
    """
    return {
        "run_id": bundle.run_id,
        "path": str(bundle.path),
        "format_version": bundle.format_version,
        "created_at": bundle.created_at,
        "provenance": dict(bundle.provenance),
        "qc": dict(bundle.qc),
        "cards": [
            {
                "card_id": card.card_id,
                "section": card.section,
                "kind": card.kind,
                "title": card.title,
                "gene": card.gene,
                "status": card.status,
                "confidence_tier": card.confidence_tier,
                "summary": card.summary,
                "detail": card.detail,
                "impossibility_reason": card.impossibility_reason,
                "variant": None if card.variant is None else dict(card.variant),
                "match": dict(card.match),
                "confidence": None if card.confidence is None else dict(card.confidence),
                "evidence": None if card.evidence is None else dict(card.evidence),
                "observation": None if card.observation is None else dict(card.observation),
                "frequencies": [dict(f) for f in card.frequencies],
                "confidence_frequency": None
                if card.confidence_frequency is None
                else dict(card.confidence_frequency),
                "citations": [dict(c) for c in card.citations],
                "authored_caveats": list(card.authored_caveats),
                "computed_caveats": list(card.computed_caveats),
            }
            for card in bundle.cards
        ],
    }


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument(help="Run id, as reported by `genetics runs list`.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit the whole bundle as JSON.")] = False,
) -> None:
    """Read one saved run and print it. Payload digests are checked on the way in.

    The output states your genotype at every matched marker -- that is what a card says.
    Treat it as raw DNA (AGENTS.md 1.1): it belongs outside the repository, and redirecting
    it into a file inside the checkout is the one route the ignore rules cannot fully cover.
    """
    try:
        bundle = store.load_run(run_id)
    except (BundleError, OSError) as exc:
        _fail(exc, as_json=as_json)

    if as_json:
        # Deliberately not scanned -- see the module docstring.
        typer.echo(json.dumps(_bundle_payload(bundle), indent=2, ensure_ascii=False))
        return

    typer.secho(f"run {bundle.run_id}", bold=True)
    typer.echo(f"  saved       {bundle.created_at}")
    typer.echo(f"  format      {bundle.format_version}")
    typer.echo(f"  engine      {bundle.provenance.get('engine_version')}")
    knowledge = bundle.provenance.get("knowledge")
    if isinstance(knowledge, dict):
        typer.echo(f"  knowledge   {knowledge.get('card_count')} card(s)")
    source = bundle.provenance.get("input")
    if isinstance(source, dict):
        typer.echo(f"  input       {source.get('vendor')}, {source.get('markers')} markers")
    typer.echo("")

    for card in bundle.cards:
        tier = card.confidence_tier or card.status
        typer.secho(f"  {tier:<16}", fg=typer.colors.CYAN, nl=False)
        typer.echo(f"{card.section:<14} {card.card_id:<34} {card.title}")

    typer.echo("")
    typer.echo(f"  {len(bundle.cards)} card(s). `--json` for the full record and its citations.")


# ---------------------------------------------------------------------------
# runs delete / prune
# ---------------------------------------------------------------------------


@runs_app.command("delete")
def runs_delete(
    run_id: Annotated[str, typer.Argument(help="Run id to delete.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Delete one saved run. There is no undo and no trash.

    Confirms first unless ``--yes``. With ``--json`` there is nobody to answer a prompt, so
    ``--yes`` is *required* rather than assumed: a non-interactive caller that meant to
    delete says so, and one that did not gets an error instead of a deletion.
    """
    if as_json and not yes:
        _refuse(
            "confirmation-required",
            "--json cannot prompt for confirmation; pass --yes to confirm the deletion.",
            as_json=True,
            code=2,
        )

    try:
        target = store.resolve_run(run_id)
    except (BundleError, OSError) as exc:
        _fail(exc, as_json=as_json)

    if not yes:
        summary = store.summarise_run(target)
        cards = "unknown" if summary.card_count is None else str(summary.card_count)
        typer.echo(str(target))
        typer.echo(f"  saved {summary.created_at or 'unknown'}, {cards} card(s)")
        typer.confirm("Delete this run permanently?", abort=True)

    try:
        removed = store.delete_run(run_id)
    except (BundleError, OSError) as exc:
        _fail(exc, as_json=as_json)

    if as_json:
        typer.echo(json.dumps({"ok": True, "deleted": str(removed)}, indent=2))
    else:
        typer.secho(f"deleted {removed}", fg=typer.colors.GREEN)


@runs_app.command("prune")
def runs_prune(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Remove staging directories left behind by interrupted saves.

    These hold no run: a save that did not finish was never promoted to a run id, so nothing
    refers to what is inside them. ``runs list`` reports them rather than silently skipping
    them, because after M8 an interrupted save can be gigabytes, and a listing that hides
    them is a listing that lets them accumulate unseen.
    """
    listing = store.list_runs()
    if not listing.incomplete:
        if as_json:
            typer.echo(json.dumps({"ok": True, "removed": []}, indent=2))
        else:
            typer.echo("No interrupted saves to remove.")
        return

    total = sum(item.size_bytes for item in listing.incomplete)
    if not yes:
        if as_json:
            _refuse(
                "confirmation-required",
                "--json cannot prompt for confirmation; pass --yes to confirm.",
                as_json=True,
                code=2,
            )
        for item in listing.incomplete:
            typer.echo(f"  {item.path.name}  {_size(item.size_bytes)}")
        typer.confirm(
            f"Remove {len(listing.incomplete)} staging directory/ies ({_size(total)})?",
            abort=True,
        )

    removed = store.prune_incomplete()
    # Reported from what actually went, not from what was offered. `prune_incomplete`
    # removes with `ignore_errors=True` so one locked directory does not stop the others,
    # which means the two lists can differ -- and printing the offered total would announce
    # freeing space that is still occupied.
    freed = sum(item.size_bytes for item in removed)
    remaining = [item for item in listing.incomplete if item not in removed]

    if as_json:
        payload = {
            "ok": not remaining,
            "removed": [item.to_dict() for item in removed],
            "remaining": [item.to_dict() for item in remaining],
        }
        typer.echo(json.dumps(payload, indent=2))
    else:
        typer.secho(
            f"removed {len(removed)} staging directory/ies, {_size(freed)}",
            fg=typer.colors.GREEN,
        )
        for item in remaining:
            typer.secho(
                f"  could not remove {item.path.name} -- something still has it open",
                fg=typer.colors.YELLOW,
            )
    if remaining:
        raise typer.Exit(code=1)
