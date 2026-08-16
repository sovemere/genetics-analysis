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


def _add_refs_commands() -> None:
    """Register the M2 command groups.

    Imported at module scope rather than lazily like the heavier commands below: Typer
    builds its command tree at import time, so ``genetics refs --help`` has to know these
    exist before anything runs. The modules they pull in are cheap -- yaml and stdlib --
    unlike the Polars-backed ingest stack.
    """
    from genetics.cli.refs_cmd import refs_app, tools_app

    app.add_typer(refs_app, name="refs")
    app.add_typer(tools_app, name="tools")


def _add_cards_commands() -> None:
    """Register card tooling without importing the Polars-backed lint engine yet."""
    from genetics.cli.cards_cmd import cards_app

    app.add_typer(cards_app, name="cards")


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
    # Defaults resolve to the library constants rather than restating the literals.
    # Restated literals drift: rotating DEFAULT_SEED would leave the CLI (and CI, which
    # shells through it) verifying against the old seed while tests calling the library
    # directly used the new one -- both sides reporting success about different data.
    seed: Annotated[
        int | None, typer.Option("--seed", help="RNG seed. Changing it changes output.")
    ] = None,
    markers: Annotated[
        int | None, typer.Option("--markers", help="Approximate autosomal+sex marker count.")
    ] = None,
    check: Annotated[
        bool,
        typer.Option("--check", help="Verify fixtures match a fresh generation; write nothing."),
    ] = False,
) -> None:
    """Generate the synthetic test fixtures (M0.2).

    Fixtures are invented from a seeded RNG. They never derive from a real export.
    """
    from genetics.testing.fixtures import (
        DEFAULT_FIXTURE_DIR,
        DEFAULT_MARKERS,
        DEFAULT_SEED,
        generate_all,
        verify_all,
    )

    target = out_dir or DEFAULT_FIXTURE_DIR
    seed = DEFAULT_SEED if seed is None else seed
    markers = DEFAULT_MARKERS if markers is None else markers

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


@app.command()
def ingest(
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
                "'markers=677436,no_calls=550,indels=8830' (M1.2)."
            ),
        ),
    ] = None,
) -> None:
    """Parse a raw DNA export into the normalized table and report QC (M1.8).

    Prints counts, rates and inferred sex. Never prints a genotype.
    """
    # Imported here, not at module scope: this pulls in Polars and the whole ingest
    # stack, and `genetics --help` should not pay for it.
    from genetics.cli.ingest_cmd import run

    run(input_path=input_path, as_json=as_json, expect_counts=expect_counts)


@app.command()
def adapters(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """List the registered vendor adapters (M1.3).

    Shows which have been verified against a real export of their vendor's and which have
    only ever seen a synthetic fixture -- "it parsed" is not "it was validated".
    """
    from genetics.ingest import adapters as registered

    rows = [
        {
            "vendor_id": adapter.vendor_id,
            "display_name": adapter.display_name,
            "verified_against_real_export": adapter.verified_against_real_export,
        }
        for adapter in registered()
    ]

    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return

    for row in rows:
        mark = "verified" if row["verified_against_real_export"] else "stub    "
        typer.echo(f"  {mark}  {row['vendor_id']:<18} {row['display_name']}")


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Report what this machine can run (M0.6).

    Missing optional tools are reported, not treated as failures -- on a fresh checkout
    nothing is installed yet, and that is the expected state rather than a fault.
    """
    from genetics.doctor import collect, to_dict

    report = collect()

    if as_json:
        typer.echo(json.dumps(to_dict(report), indent=2))
        raise typer.Exit(code=1 if report.has_problem else 0)

    typer.secho(f"genetics {report.engine_version}", bold=True)
    typer.echo(f"  python      {report.python_version}  ({report.python_executable})")
    typer.echo(f"  platform    {report.platform_name} {report.platform_release} ({report.machine})")

    if report.data_dir_error:
        typer.secho(f"  data dir    {report.data_dir_error}", fg=typer.colors.RED)
    else:
        disk = f"{report.free_disk_gb} GB free" if report.free_disk_gb is not None else "unknown"
        typer.echo(f"  data dir    {report.data_dir}  [{disk}]")

    refs = "present" if report.references_present else "not fetched"
    manifest = "manifest ok" if report.manifest_present else "no manifest (M2)"
    lock = "lock ok" if report.lock_present else "no lock"
    typer.echo(f"  references  {refs}, {manifest}, {lock}, {report.reference_files} file(s)")

    typer.echo("")
    typer.secho("external tools", bold=True)
    colours: dict[str, str] = {
        "ok": typer.colors.GREEN,
        "missing": typer.colors.YELLOW,
        "error": typer.colors.RED,
    }
    for tool in report.tools:
        typer.secho(f"  {tool.status:<8}", fg=colours[tool.status], nl=False)
        typer.echo(f"{tool.name:<12} needed from {tool.required_from}")
        if tool.version:
            typer.echo(f"           {tool.version}")
        if tool.detail:
            typer.echo(f"           {tool.detail}")

    raise typer.Exit(code=1 if report.has_problem else 0)


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
    from genetics.paths import UnsafeDataDirError, app_write_paths, is_inside_repo

    try:
        registry = app_write_paths()
    except UnsafeDataDirError as exc:
        # This is the command someone runs *because* their data directory is wrong.
        # Letting the traceback through would bury the one message that explains it.
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    rows = [
        {
            "label": label,
            "path": str(path),
            "must_be_gitignored": ignored,
            "inside_repo": is_inside_repo(path),
        }
        for label, path, ignored in registry
    ]

    if as_json:
        typer.echo(json.dumps(rows, indent=2))
        return

    for row in rows:
        marker = "repo" if row["inside_repo"] else "user"
        typer.echo(f"{row['label']:<20} [{marker}] {row['path']}")


_add_refs_commands()
_add_cards_commands()


if __name__ == "__main__":
    app()
