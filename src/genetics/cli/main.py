"""Typer entry point for the ``genetics`` command.

Commands are added per-milestone. Keep every command JSON-capable: the CLI is the
agent interface, not a convenience wrapper (AGENTS.md section 3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from genetics import __version__

app = typer.Typer(
    name="genetics",
    help="Offline-capable personal genome interpreter.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Print the engine version."""
    if as_json:
        typer.echo(json.dumps({"version": __version__}))
    else:
        typer.echo(__version__)


@app.command()
def fixtures(
    out_dir: Annotated[
        Path | None,
        typer.Option("--out-dir", help="Destination. Defaults to tests/fixtures/synthetic/."),
    ] = None,
    seed: Annotated[
        int, typer.Option("--seed", help="RNG seed. Changing it changes output.")
    ] = 20260815,
    markers: Annotated[
        int, typer.Option("--markers", help="Approximate autosomal+sex marker count.")
    ] = 12000,
    check: Annotated[
        bool,
        typer.Option("--check", help="Verify fixtures match a fresh generation; write nothing."),
    ] = False,
) -> None:
    """Generate the synthetic test fixtures (M0.2).

    Fixtures are invented from a seeded RNG. They never derive from a real export.
    """
    from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR, generate_all, verify_all

    target = out_dir or DEFAULT_FIXTURE_DIR

    if check:
        drift = verify_all(target, seed=seed, markers=markers)
        if drift:
            typer.secho("Fixtures do not match a fresh generation:", fg=typer.colors.RED)
            for name in drift:
                typer.echo(f"  drifted: {name}")
            raise typer.Exit(code=1)
        typer.secho("Fixtures match a fresh generation.", fg=typer.colors.GREEN)
        return

    written = generate_all(target, seed=seed, markers=markers)
    for path in written:
        typer.echo(f"wrote {path.name}")
    typer.secho(f"{len(written)} fixtures written to {target}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
