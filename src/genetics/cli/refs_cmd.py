"""``genetics refs`` and ``genetics tools`` (roadmap M2.6, and M2.5's entry point).

Every command emits JSON on ``--json``: the CLI is the contract, not a convenience
wrapper (AGENTS.md 3). The human rendering exists so a person watching a 92 GB download
can tell what is happening; the JSON exists so an agent can answer questions about it.

The commands split along what a person actually needs to know:

* ``status``   -- what is present, what is missing, and what is lost while it is missing.
* ``fetch``    -- get it, resumably. ``--dry-run`` first, because the required set is
                  92 GB and finding that out afterwards is not useful.
* ``verify``   -- check what is on disk against the manifest and the lock, no network.
* ``probe``    -- the reverse: check the manifest's URLs are still there, no payload.
* ``licenses`` -- the obligations, and which sources the gate will refuse.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from genetics.paths import references_dir, tools_dir
from genetics.refs import fetcher, postprocess
from genetics.refs import lock as lockfile
from genetics.refs import manifest as manifest_mod
from genetics.refs import tools as tools_mod

refs_app = typer.Typer(
    name="refs",
    help="Fetch and verify the reference corpus (M2).",
    no_args_is_help=True,
)
tools_app = typer.Typer(
    name="tools",
    help="Install and check the external tools (PLINK 2, Beagle).",
    no_args_is_help=True,
)


def _gb(n: float) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e8 else f"{n / 1e6:.1f} MB"


class _ProgressPrinter:
    """Single-line progress on stderr.

    stderr rather than stdout so that piping ``--json`` somewhere stays clean, and
    throttled to a few updates a second because a megabyte-per-chunk callback on a 63 GB
    file would otherwise spend real time on terminal writes.
    """

    def __init__(self, interval: float = 0.2) -> None:
        self._last = 0.0
        self._interval = interval
        self._active = sys.stderr.isatty()

    def __call__(self, event: fetcher.ProgressEvent) -> None:
        if not self._active:
            return
        now = time.monotonic()
        if now - self._last < self._interval:
            return
        self._last = now
        if event.unit == "rows":
            bar = f"{event.downloaded:,} rows"
        elif event.total:
            pct = 100.0 * event.downloaded / event.total
            bar = f"{pct:5.1f}%  {_gb(event.downloaded)} / {_gb(event.total)}"
        else:
            bar = f"{_gb(event.downloaded)}"
        sys.stderr.write(f"\r  {event.label[:24]:<24} {event.filename[:38]:<38} {bar}   ")
        sys.stderr.flush()

    def done(self) -> None:
        if self._active:
            sys.stderr.write("\r" + " " * 100 + "\r")
            sys.stderr.flush()


def _emit(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _process_work_present(source_dir: Path, output_name: str) -> bool:
    output = source_dir / output_name
    classified = output.with_name(f".{output.name}.classified.parquet")
    return (
        output.with_name(f".{output.name}.chunks").is_dir()
        or output.with_name(f".{output.name}.part").exists()
        or classified.with_name(f".{classified.name}.chunks").is_dir()
        or classified.exists()
    )


@contextmanager
def _clean_errors() -> Iterator[None]:
    """Turn a bad id or a malformed manifest into a message, not a traceback.

    Both errors already say exactly what is wrong and list the valid ids, and a rendered
    traceback buries that under a stack frame -- which is the same reasoning that made
    ``genetics paths`` catch ``UnsafeDataDirError``: these are the commands someone runs
    *because* something is wrong, so the explanation has to be the thing they see.
    """
    try:
        yield
    except (manifest_mod.ManifestError, tools_mod.ToolError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# refs status
# ---------------------------------------------------------------------------


@refs_app.command("status")
def refs_status(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Show which sources are present, and what is unavailable while they are not."""
    with _clean_errors():
        parsed = manifest_mod.load()
    root = references_dir()
    lock = lockfile.read(_lock_path())

    rows: list[dict[str, Any]] = []
    for source in parsed.sources:
        source_dir = root / source.id
        present = sum(1 for item in source.files if (source_dir / item.filename).is_file())
        downloading = any((source_dir / f"{item.filename}.part").is_file() for item in source.files)
        implemented = [step for step in source.post_process if step.definition.implemented]
        outputs = [
            str(value)
            for step in implemented
            for key, value in step.params.items()
            if key == "output" or key.endswith("_output")
        ]
        outputs_present = sum(
            1
            for name in outputs
            if (source_dir / name).is_file()
            and postprocess.provenance_path(source_dir / name).is_file()
        )
        # Partial artifacts mean a transform started; they do not mean one is running now,
        # and nothing on disk can tell the difference. A killed transform leaves the same
        # files as a live one -- `_run_merges` deliberately keeps its multi-GB intermediate
        # so a rerun resumes from it rather than re-reading 28 GB. Reporting that as
        # "processing" left a stale orphan looking like work in progress forever, with no
        # line telling the user a rerun was needed. So the state is the same
        # "processing-required" either way, and the resumable partials become a detail.
        resumable = outputs_present < len(outputs) and any(
            _process_work_present(source_dir, name) for name in outputs
        )
        refusal = fetcher.licence_refusal(source)
        if refusal is not None:
            state = "blocked-by-licence"
        elif source.manual is not None and not fetcher.manual_step_satisfied(source, root):
            state = "manual-step"
        elif source.manual is not None:
            state = "processing-required" if outputs_present < len(outputs) else "complete"
        elif not source.files:
            state = "empty"
        elif present == len(source.files):
            state = "processing-required" if outputs_present < len(outputs) else "complete"
        elif present or downloading:
            state = "partial"
        else:
            state = "missing"

        rows.append(
            {
                "id": source.id,
                "name": source.name,
                "tier": source.tier.value,
                "required": source.required,
                "state": state,
                "files_present": present,
                "files_total": len(source.files),
                "post_process_outputs_present": outputs_present,
                "post_process_outputs_total": len(outputs),
                "post_process_resumable": resumable,
                "pending_post_process": [
                    step.step for step in source.post_process if not step.definition.implemented
                ],
                "size_bytes": source.total_size_bytes,
                "licence_standing": str(source.license.standing),
                "enables": list(source.enables),
                "in_lock": source.id in lock.sources,
            }
        )

    if as_json:
        _emit({"root": str(root), "sources": rows})
        return

    typer.secho(f"reference corpus at {root}", bold=True)
    colours = {
        "complete": typer.colors.GREEN,
        "partial": typer.colors.YELLOW,
        "missing": typer.colors.YELLOW,
        "manual-step": typer.colors.CYAN,
        "blocked-by-licence": typer.colors.RED,
        "empty": typer.colors.YELLOW,
        "processing-required": typer.colors.YELLOW,
    }
    for row in rows:
        mark = "REQ" if row["required"] else "   "
        size = _gb(row["size_bytes"]) if row["size_bytes"] else "-"
        typer.secho(f"  {row['state']!s:<19}", fg=colours.get(str(row["state"])), nl=False)
        typer.echo(
            f"{mark} {row['tier']}  {row['id']:<32} "
            f"{row['files_present']}/{row['files_total']:<3} {size:>10}"
        )
        if row["post_process_resumable"]:
            # Said out loud, because the alternative is a directory quietly holding
            # gigabytes of a transform nobody knows stopped.
            typer.secho(
                "                      partial post-processing artifacts present; "
                "rerun `genetics refs fetch` to resume from the last checkpoint",
                fg=typer.colors.CYAN,
            )

    missing_required = [r for r in rows if r["required"] and r["state"] != "complete"]
    if missing_required:
        typer.echo("")
        typer.secho("not yet available:", bold=True)
        for row in missing_required:
            for capability in row["enables"]:
                typer.echo(f"  - {capability}")


# ---------------------------------------------------------------------------
# refs fetch
# ---------------------------------------------------------------------------


@refs_app.command("fetch")
def refs_fetch(
    only: Annotated[
        list[str] | None,
        typer.Option("--only", help="Fetch just this source id. Repeatable."),
    ] = None,
    include_optional: Annotated[
        bool, typer.Option("--all", help="Include optional sources, not just required ones.")
    ] = False,
    opt_in: Annotated[
        list[str] | None,
        typer.Option("--opt-in", help="Accept a restricted source's licence. Repeatable."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would be fetched and how big it is."),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Download reference sources, resuming any partial transfer.

    Defaults to the required sources only. Interrupting is safe: partial files are kept
    and the next run continues from where the transfer stopped.
    """
    with _clean_errors():
        parsed = manifest_mod.load()
        selected = fetcher.select_sources(parsed, only, include_optional)
    root = references_dir()

    if dry_run:
        total = sum(s.total_size_bytes or 0 for s in selected)
        postprocess_workspace = sum(
            postprocess.estimated_workspace_bytes(source) for source in selected
        )
        unknown = [s.id for s in selected if s.total_size_bytes is None and s.files]
        blocked = {s.id: fetcher.licence_refusal(s, opt_in or []) for s in selected}
        payload = {
            "root": str(root),
            "sources": [
                {
                    "id": s.id,
                    "size_bytes": s.total_size_bytes,
                    "files": len(s.files),
                    "blocked": blocked[s.id],
                }
                for s in selected
            ],
            "total_bytes": total,
            "postprocess_workspace_bytes": postprocess_workspace,
            "estimated_peak_bytes": total + postprocess_workspace,
            "unknown_size": unknown,
            "disk_warning": fetcher.preflight_disk(selected, root),
        }
        if as_json:
            _emit(payload)
            return
        typer.secho(
            f"would fetch {len(selected)} source(s), {_gb(total)} downloads, "
            f"~{_gb(total + postprocess_workspace)} peak disk",
            bold=True,
        )
        for s in selected:
            note = blocked[s.id]
            typer.echo(f"  {s.id:<34} {len(s.files):>3} files  {_gb(s.total_size_bytes or 0):>10}")
            if note:
                typer.secho(f"      blocked: {note}", fg=typer.colors.RED)
        if payload["disk_warning"]:
            typer.secho(f"  ! {payload['disk_warning']}", fg=typer.colors.RED)
        return

    printer = _ProgressPrinter()
    report = fetcher.fetch(
        parsed,
        root=root,
        only=only,
        include_optional=include_optional,
        opt_in=opt_in or [],
        progress=None if as_json else printer,
    )
    printer.done()
    _render_report(report, as_json=as_json)
    raise typer.Exit(code=0 if report.ok else 1)


# ---------------------------------------------------------------------------
# refs verify
# ---------------------------------------------------------------------------


@refs_app.command("verify")
def refs_verify(
    only: Annotated[
        list[str] | None, typer.Option("--only", help="Verify just this source id.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Check on-disk files against the manifest and the lock. Makes no network request."""
    with _clean_errors():
        parsed = manifest_mod.load()
        fetcher.select_sources(parsed, only, include_optional=True)
    report = fetcher.fetch(
        parsed,
        root=references_dir(),
        only=only,
        include_optional=True,
        verify_only=True,
    )
    _render_report(report, as_json=as_json)
    raise typer.Exit(code=0 if report.ok else 1)


def _render_report(report: fetcher.FetchReport, *, as_json: bool) -> None:
    if as_json:
        _emit(report.to_dict())
        return

    for result in report.sources:
        colour = typer.colors.GREEN if result.ok else typer.colors.RED
        typer.secho(f"  {result.status!s:<20}", fg=colour, nl=False)
        typer.echo(result.source_id)
        if result.detail:
            typer.echo(f"      {result.detail}")
        for step in result.pending_steps:
            typer.secho(f"      pending post-processing: {step}", fg=typer.colors.CYAN)
        for process in result.process_results:
            if process.status is postprocess.ProcessStatus.PENDING:
                continue
            colour = typer.colors.GREEN if process.ok else typer.colors.RED
            suffix = f" ({process.rows:,} rows)" if process.rows is not None else ""
            detail = f" — {process.detail}" if process.detail else ""
            typer.secho(
                f"      {process.step}: {process.status}{suffix}{detail}",
                fg=colour,
            )

    for warning in report.warnings:
        typer.echo("")
        typer.secho(f"  ! {warning}", fg=typer.colors.YELLOW)


# ---------------------------------------------------------------------------
# refs probe
# ---------------------------------------------------------------------------


@refs_app.command("probe")
def refs_probe(
    only: Annotated[
        list[str] | None, typer.Option("--only", help="Probe just this source id.")
    ] = None,
    no_tools: Annotated[
        bool, typer.Option("--no-tools", help="Skip the PLINK 2 and Beagle download URLs.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Check every declared URL is still there and still the size we recorded.

    The counterpart to ``verify``, pointed the other way: ``verify`` checks bytes already
    on disk, this checks URLs nothing has fetched yet. It transfers no payload, so it is
    cheap enough to run on a schedule -- which is the point, because the corpus's one real
    failure so far was a dataset withdrawn from its host with nothing in the repository
    able to notice.

    Exits non-zero for a URL that has gone 404 and for a *pinned* file whose size has
    changed, since that pin is now wrong and the next fetch of it is already doomed. Drift
    on an unpinned file and a host that simply did not answer are reported but do not fail
    the command; see ``ProbeResult.fatal``.
    """
    with _clean_errors():
        parsed = manifest_mod.load()
        fetcher.select_sources(parsed, only, include_optional=True)
    report = fetcher.probe(parsed, only=only, include_tools=not no_tools)

    if as_json:
        _emit(report.to_dict())
        raise typer.Exit(code=0 if report.ok else 1)

    findings = report.findings
    clean = len(report.results) - len(findings)
    typer.echo(f"  probed {len(report.results)} URL(s); {clean} unchanged")
    for result in findings:
        colour = typer.colors.RED if result.fatal else typer.colors.YELLOW
        typer.secho(f"  {result.status!s:<14}", fg=colour, nl=False)
        name = f"{result.label}/{result.filename}" if result.filename else result.label
        typer.echo(name)
        if result.detail:
            typer.echo(f"      {result.detail}")
        typer.echo(f"      {result.url}")
    if not findings:
        typer.secho("  every declared URL answered and matched its size.", fg=typer.colors.GREEN)
    raise typer.Exit(code=0 if report.ok else 1)


# ---------------------------------------------------------------------------
# refs licenses
# ---------------------------------------------------------------------------


@refs_app.command("licenses")
def refs_licenses(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Report each source's licence, its obligations, and whether it needs an opt-in.

    This is the input to the M15.4 release audit. It reads the manifest rather than the
    lock, so it answers "what would we be agreeing to?" before anything is downloaded.
    """
    with _clean_errors():
        parsed = manifest_mod.load()
    rows: list[dict[str, Any]] = []
    for source in parsed.sources:
        terms = source.license
        locked = lockfile.LockedSource(version=source.version, license_id=source.license_id)
        rows.append(
            {
                "id": source.id,
                "license": terms.id,
                "name": terms.name,
                "terms_url": terms.terms_url,
                "standing": str(terms.standing),
                "needs_opt_in": terms.needs_opt_in,
                "obligations": locked.to_json()["obligations"],
            }
        )

    if as_json:
        _emit({"sources": rows})
        return

    for row in rows:
        colour = typer.colors.RED if row["needs_opt_in"] else typer.colors.GREEN
        typer.secho(f"  {row['standing']!s:<14}", fg=colour, nl=False)
        typer.echo(f"{row['id']:<34} {row['license']}")
        for obligation in row["obligations"]:
            typer.echo(f"      - {obligation}")

    blocked = [r["id"] for r in rows if r["needs_opt_in"]]
    if blocked:
        typer.echo("")
        typer.secho(
            f"These need an explicit opt-in: {', '.join(blocked)}\n"
            f"  genetics refs fetch --only <id> --opt-in <id>",
            fg=typer.colors.YELLOW,
        )


# ---------------------------------------------------------------------------
# tools (M2.5)
# ---------------------------------------------------------------------------


def _lock_path() -> Path:
    from genetics.paths import reference_lock

    return reference_lock()


@tools_app.command("status")
def tools_status(
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Report which external tools are installed for this platform."""
    with _clean_errors():
        parsed = tools_mod.load()
    root = tools_dir()
    key = tools_mod.current_platform()
    results = [tools_mod.status(tool, tools_root=root) for tool in parsed.tools]

    if as_json:
        _emit(
            {
                "platform": key,
                "tools_dir": str(root),
                "tools": [
                    {**vars(r), "status": str(r.status), "required_from": t.required_from}
                    for r, t in zip(results, parsed.tools, strict=True)
                ],
            }
        )
        return

    typer.secho(f"tools for {key} in {root}", bold=True)
    for result, tool in zip(results, parsed.tools, strict=True):
        colour = typer.colors.GREEN if result.ok else typer.colors.YELLOW
        if result.status in {
            tools_mod.InstallStatus.VERSION_MISMATCH,
            tools_mod.InstallStatus.FAILED,
        }:
            colour = typer.colors.RED
        typer.secho(f"  {result.status!s:<20}", fg=colour, nl=False)
        typer.echo(f"{tool.id:<10} {tool.version:<16} needed from {tool.required_from}")
        if result.version:
            typer.echo(f"      {result.version}")
        if result.detail:
            typer.echo(f"      {result.detail}")


@tools_app.command("install")
def tools_install(
    only: Annotated[
        list[str] | None, typer.Option("--only", help="Install just this tool id.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Reinstall even if already present.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Download and install PLINK 2 and Beagle under the user data directory.

    Never installs Java or R. Both are system-level dependencies, and HLA imputation is
    designed to degrade gracefully when R is absent (AGENTS.md 4.9). Run
    ``genetics doctor`` to see them.
    """
    with _clean_errors():
        parsed = tools_mod.load()
        wanted = [parsed.get(t) for t in only] if only else list(parsed.tools)
    root = tools_dir()

    printer = _ProgressPrinter()
    results: list[tools_mod.InstallResult] = []
    for tool in wanted:
        result = tools_mod.install(
            tool, tools_root=root, progress=None if as_json else printer, force=force
        )
        printer.done()
        results.append(result)
        build = tool.build_for(tools_mod.current_platform())
        if result.ok and build is not None:
            tools_mod.record_install(root, tool, build, result)

    if as_json:
        _emit({"tools": [{**vars(r), "status": str(r.status)} for r in results]})
    else:
        for result in results:
            colour = typer.colors.GREEN if result.ok else typer.colors.RED
            typer.secho(f"  {result.status!s:<20}", fg=colour, nl=False)
            typer.echo(f"{result.tool_id}  {result.version or ''}")
            if result.path:
                typer.echo(f"      {result.path}")
            if result.detail:
                typer.echo(f"      {result.detail}")

    raise typer.Exit(code=0 if all(r.ok for r in results) else 1)
