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


@app.command("check-staged")
def check_staged_cmd() -> None:
    """Block genotype content in the staged index (M0.3). Used by the pre-commit hook.

    Catches the case .gitignore cannot: a legitimately-tracked file that has acquired a
    genotype inside it.
    """
    from genetics.guard import check_staged

    findings = check_staged()
    if not findings:
        typer.secho("No genotype content staged.", fg=typer.colors.GREEN)
        return

    typer.secho("Refusing to commit -- genotype-derived content is staged:", fg=typer.colors.RED)
    for finding in findings:
        typer.echo(finding.render())
    typer.echo("")
    typer.secho(
        "This repository is public. See AGENTS.md section 1.",
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=1)


@app.command("install-hooks")
def install_hooks() -> None:
    """Point git at the tracked hooks in .githooks/ (M0.4)."""
    import subprocess

    from genetics.paths import repo_root

    root = repo_root()
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"],
        cwd=root,
        check=True,
    )
    typer.secho("core.hooksPath set to .githooks", fg=typer.colors.GREEN)
    typer.echo("Pre-commit will now run ruff and the privacy suite.")


@app.command()
def paths(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Show where the app reads and writes.

    Analysis output defaults outside the repository on purpose (AGENTS.md 1.5).
    """
    from genetics.paths import APP_WRITE_PATHS, is_inside_repo

    rows = [
        {
            "label": label,
            "path": str(path),
            "must_be_gitignored": ignored,
            "inside_repo": is_inside_repo(path),
        }
        for label, path, ignored in APP_WRITE_PATHS
    ]

    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return

    for row in rows:
        marker = "repo" if row["inside_repo"] else "user"
        typer.echo(f"{row['label']:<20} [{marker}] {row['path']}")


if __name__ == "__main__":
    app()
