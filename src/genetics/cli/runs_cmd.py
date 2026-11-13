"""``genetics runs`` -- list, read and delete saved runs (roadmap M4.2, M13.1).

M4.2 built the store surface: ``list``, ``show``, ``delete`` and ``prune``. M13.1 added the
agent's reads on top of it: ``show --section``, ``card <run> <card-id>`` and ``qc``, whose
payloads :mod:`genetics.run.reads` builds. ``cards evidence`` is the fourth M13.1 read and
lives in :mod:`genetics.cli.cards_cmd`, because it reads no run. M13.2 pinned their JSON as a
versioned schema: each document is tagged by :func:`genetics.cli.contract.tagged`, and
``run_id`` is the bundle's directory name in every one. M13.3 added ``search <run> <query>``,
which ranks the run's saved cards with the function ``cards search`` uses on the pack
(:func:`genetics.engine.search.search`).

M13.5 gave the saved records beside the cards (``clinvar``, ``secondary``, ``imputation``)
the same envelope and tag, built by the same module.

**The privacy split is inherited from the bundle format rather than reinvented.** ``runs
list``, ``runs qc`` and ``runs imputation`` are scanned with ``assert_no_genotype`` on both
output paths; ``runs show``, ``runs card``, ``runs search``, ``runs clinvar`` and ``runs
secondary`` are not. That is a decision in both directions, not an oversight in one:

* Listing is manifest-derived, and the manifest is the file a person pastes into a bug
  report. The writer already scans it, but that scan is a property of the writer -- a bundle
  read here may have been written by another version or edited by hand, so the boundary is
  checked where data leaves the process, which is what :mod:`genetics.privacy` is for. Both
  branches are scanned because M1.8 got exactly this wrong: the first cut of ``genetics
  ingest`` guarded the JSON branch and left the human render open, which is the branch a
  person is *more* likely to edit.
* ``show``, ``card`` and ``search`` render per-card results, and a card's summary states what
  the reader's genotype is -- that is the product, not a leak. Scanning it would be a guard that
  fails on correct output, and M0.3 settled what happens to those: they get switched off,
  including on the day they were right. A bundle is raw DNA (AGENTS.md 1.1) and belongs to
  the person running the command; keeping it off their own screen protects nobody.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, NoReturn

import typer

from genetics.cli import contract
from genetics.engine.sections import Section, UnknownSectionError
from genetics.privacy import assert_no_genotype
from genetics.run import reads, store
from genetics.run.bundle import (
    BundleError,
    RunBundle,
    StoredCard,
)
from genetics.run.store import RunStatus

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


_refuse = contract.refuse


def _fail(exc: Exception, *, as_json: bool) -> NoReturn:
    """A run that could not be opened or removed, as a sentence rather than a traceback.

    ``OSError`` is caught beside ``BundleError`` at every call site because the store raises
    it when the disk refuses; ``show`` opens every payload to digest it and ``delete``
    removes a directory tree, so those are the commands most likely to meet it. The kind is
    :func:`contract.run_error_kind`'s, which ``pgx calls`` and ``hla calls`` share.
    """
    _refuse(contract.run_error_kind(exc), str(exc), as_json=as_json)


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
                "Re-read every bundle, checking its digests and repeating its deep checks. "
                "About an hour for an imputed run, which later reads then skip until the "
                "engine changes. The default reads manifests only."
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
    listing = store.list_runs(verify=verify, progress=store.report_to_console)

    if as_json:
        text = json.dumps(contract.tagged("runs.list", listing.to_dict()), indent=2)
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
    in :mod:`genetics.run.bundle`. Each card goes through :func:`reads.card_payload`, which
    ``runs card`` and ``runs show --section`` use too.

    ``run_id`` is the directory name, as in every other payload, because that is the id a
    command resolves. The manifest's own id is kept beside it as ``recorded_run_id``; the
    two differ only for a renamed bundle.
    """
    return {
        "run_id": bundle.path.name,
        "recorded_run_id": bundle.run_id,
        "path": str(bundle.path),
        "format_version": bundle.format_version,
        "created_at": bundle.created_at,
        "provenance": dict(bundle.provenance),
        "qc": dict(bundle.qc),
        # None for a bundle saved before format 3 -- "not recorded", which the record
        # itself distinguishes from a stage that ran and recorded not_run.
        "ancestry": None if bundle.ancestry is None else dict(bundle.ancestry),
        "clinvar": None if bundle.clinvar is None else dict(bundle.clinvar),
        "pgx": None if bundle.pgx is None else dict(bundle.pgx),
        "hla": None if bundle.hla is None else dict(bundle.hla),
        "imputation": None if bundle.imputation is None else dict(bundle.imputation),
        "imputation_provenance": None
        if bundle.imputation_provenance is None
        else dict(bundle.imputation_provenance),
        "cards": [reads.card_payload(card) for card in bundle.cards],
    }


@runs_app.command("clinvar")
def runs_clinvar(
    run_id: Annotated[str, typer.Argument(help="Saved run id.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit the saved lookup.")] = False,
) -> None:
    """Read ClinVar reference lookup; classifications are not calibrated findings."""
    _show_clinvar(run_id, as_json=as_json, secondary_only=False)


@runs_app.command("imputation")
def runs_imputation(
    run_id: Annotated[str, typer.Argument(help="Saved run id.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit private saved provenance.")] = False,
    dosages: Annotated[
        bool, typer.Option("--dosages", help="Stream private full dosages as JSON Lines.")
    ] = False,
) -> None:
    """Inspect exact used imputation provenance or stream native dosage evidence."""
    from genetics.imputation.target import ImputationError

    try:
        bundle = store.load_run(run_id, progress=store.report_to_console)
        if dosages:
            for dosage in bundle.iter_dosages():
                typer.echo(json.dumps(dosage.to_dict(), allow_nan=False))
            return
    except (BundleError, ImputationError, OSError) as exc:
        _fail(exc, as_json=as_json)
    record = bundle.imputation_provenance
    if as_json:
        view = contract.tagged("runs.imputation", reads.imputation_view(bundle))
        text = json.dumps(view, indent=2)
    elif record is None or record["status"] != "recorded":
        text = f"Full imputation provenance: {record['status'] if record else 'not recorded'}"
    else:
        stage = record["stage"]
        text = "\n".join(
            (
                f"Panel: {stage['panel_source']['id']} / {stage['panel_source']['version']}",
                f"Maps: {stage['map_source']['id']} / {stage['map_source']['version']}",
                f"Beagle: {stage['contract']['beagle']['version']}",
                f"Java: {stage['contract']['beagle']['java']['version']}",
                f"Parameters: {json.dumps(stage['contract']['options'], sort_keys=True)}",
                f"Saved: {stage['records']} native dosage records / "
                f"{len(stage['jobs'])} region jobs",
                "Each region's phase/imputation parameters are in --json provenance.",
            )
        )
    # Provenance names panels, tools and parameters and holds no genotype, so it is checked
    # on both branches before it is printed, like `runs qc` (M13.5). `--dosages` above is
    # the genotype-derived stream and is not.
    assert_no_genotype(text, context="runs imputation output")
    typer.echo(text)


@runs_app.command("secondary")
def runs_secondary(
    run_id: Annotated[str, typer.Argument(help="Saved run id.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit saved ACMG overlaps and provenance.")
    ] = False,
) -> None:
    """Show all ACMG gene-list overlaps, including likely artifacts and unresolved calls."""
    _show_clinvar(run_id, as_json=as_json, secondary_only=True)


def _show_clinvar(run_id: str, *, as_json: bool, secondary_only: bool) -> None:
    from genetics.health.secondary import secondary_view

    try:
        bundle = store.load_run(run_id, progress=store.report_to_console)
    except (BundleError, OSError) as exc:
        _fail(exc, as_json=as_json)
    if as_json:
        # Deliberately not scanned: a locus lists the probes read there and their calls.
        payload = (
            contract.tagged("runs.secondary", reads.secondary_findings_view(bundle))
            if secondary_only
            else contract.tagged("runs.clinvar", reads.clinvar_view(bundle))
        )
        typer.echo(json.dumps(payload, indent=2))
        return
    if bundle.clinvar is None:
        typer.echo("ClinVar lookup was not recorded by this older bundle.")
        return
    record = bundle.clinvar
    typer.echo(record["notice"])
    typer.echo(f"Status: {record['status']}")
    if record["reason"]:
        typer.echo(record["reason"])
    if not secondary_only:
        coverage = record.get("coverage")
        if coverage is not None:
            from genetics.health.coverage import coverage_summary

            typer.echo(coverage_summary(coverage))
            typer.echo(
                f"Coverage counting policy: {json.dumps(coverage['policy'], sort_keys=True)}"
            )
            typer.echo(f"Chip counts: {json.dumps(coverage['chip_counts'], sort_keys=True)}")
            typer.echo(f"Overlap counts: {json.dumps(coverage['overlap_counts'], sort_keys=True)}")
        else:
            typer.echo(
                "Quantitative ClinVar coverage was not recorded; saved results are unchanged."
            )
    secondary = record.get("secondary_reference")
    if secondary:
        typer.echo(f"ACMG SF v3.3: {secondary['status']}. {secondary['reason']}")
        typer.echo(secondary["notice"])
        typer.echo(secondary["policy"])
        typer.echo(f"ACMG overlap counts: {json.dumps(secondary['counts'], sort_keys=True)}")
        typer.echo(
            f"ClinGen reference provenance: {json.dumps(secondary['provenance'], sort_keys=True)}"
        )
    elif secondary_only:
        typer.echo(
            "This older run did not record ACMG gene-list surfacing; saved results are unchanged."
        )
    loci = secondary_view(record)["loci"] if secondary_only else record["loci"]
    for locus in loci:
        typer.echo(f"{locus['chrom']}:{locus['pos_grch37']}")
        for entry in locus["records"]:
            info = entry["info"]
            typer.echo(
                f"  Variation {entry['variation_id']}: {entry['status']}; "
                f"germline classification: {info.get('CLNSIG', 'not provided')}; "
                f"review: {info.get('CLNREVSTAT', 'not provided')}"
            )
            typer.echo(f"    {entry['reason']}")
            if entry.get("acmg"):
                acmg = entry["acmg"]
                typer.echo(
                    f"    ACMG gene-list overlap: {', '.join(g['symbol'] for g in acmg['genes'])}; "
                    f"annotation: {acmg['classification']}; reportability: {acmg['reportability']}"
                )
                typer.echo(f"    {acmg['notice']}")
                for gene in acmg["genes"]:
                    typer.echo(
                        f"    {gene['symbol']} ({gene['hgnc_id']}; NCBI {gene['ncbi_gene_id']}): "
                        + (
                            gene["guidance"]
                            or "No additional guidance recorded; consult ACMG policy restrictions."
                        )
                    )
            if "reliability" in entry:
                reliability = entry["reliability"]
                typer.echo(
                    f"    Measurement reliability: {reliability['tier']}; "
                    f"frequency: {reliability['frequency']}; "
                    f"population: {reliability['population']}"
                )
                typer.echo(f"    {reliability['reason']}")
                ppv = reliability.get("empirical_ppv")
                if ppv:
                    from genetics.engine.ppv import confirmation_text

                    typer.echo(
                        "    "
                        + confirmation_text(ppv["estimate"], ppv["population_frequency_ceiling"])
                    )
                    typer.echo(f"    {ppv['applies_to']} DOI: {ppv['doi']}")
    typer.echo("Use --json for all annotations, calls and source provenance.")


@runs_app.command("show")
def runs_show(
    run_id: Annotated[str, typer.Argument(help="Run id, as reported by `genetics runs list`.")],
    section: Annotated[
        list[str] | None,
        typer.Option(
            "--section",
            "-s",
            help=(
                "Only this section's cards, with what the dashboard shows around them; "
                "repeatable. With --json, prints those cards rather than the whole bundle."
            ),
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json", help="Emit JSON: the whole bundle, or with --section those sections."
        ),
    ] = False,
) -> None:
    """Read one saved run and print it. Payload digests are checked on the way in.

    The output states your genotype at every matched marker -- that is what a card says.
    Treat it as raw DNA (AGENTS.md 1.1): it belongs outside the repository, and redirecting
    it into a file inside the checkout is the one route the ignore rules cannot fully cover.

    Without ``--section``, ``--json`` is the frozen bundle and nothing else. With it, the
    saved cards of those sections come with a separate ``current_context``: section titles,
    empty-section reasons, pointers to cards other sections hold, and section notices.
    """
    chosen: list[Section] | None = None
    if section:
        try:
            chosen = [reads.parse_section(name) for name in section]
        except UnknownSectionError as exc:
            _refuse("unknown-section", str(exc), as_json=as_json, code=2)

    try:
        bundle = store.load_run(run_id, progress=store.report_to_console)
    except (BundleError, OSError) as exc:
        _fail(exc, as_json=as_json)

    if as_json:
        # Deliberately not scanned -- see the module docstring.
        payload = (
            contract.tagged("runs.show", _bundle_payload(bundle))
            if chosen is None
            else contract.tagged("runs.section", reads.section_view(bundle, chosen))
        )
        typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    from genetics.engine.carrier_scope import SOURCE as SCOPE_SOURCE
    from genetics.engine.carrier_scope import section_notice

    scope = section_notice(bundle.cards)
    typer.secho(f"run {bundle.path.name}", bold=True)
    typer.echo(f"  saved       {bundle.created_at}")
    typer.echo(f"  format      {bundle.format_version}")
    typer.echo(f"  engine      {bundle.provenance.get('engine_version')}")
    knowledge = bundle.provenance.get("knowledge")
    if isinstance(knowledge, dict):
        typer.echo(f"  knowledge   {knowledge.get('card_count')} card(s)")
    source = bundle.provenance.get("input")
    if isinstance(source, dict):
        typer.echo(f"  input       {source.get('vendor')}, {source.get('markers')} markers")
    typer.echo(f"  ancestry    {_ancestry_line(bundle.ancestry)}")
    typer.echo(f"  ClinVar     {bundle.clinvar['status'] if bundle.clinvar else 'not recorded'}")
    typer.echo(
        f"  imputation  {bundle.imputation['mode'] if bundle.imputation else 'not recorded'}"
    )
    typer.echo("")

    names = None if chosen is None else {s.value for s in chosen}
    shown = [card for card in bundle.cards if names is None or card.section in names]
    for card in shown:
        tier = card.confidence_tier or card.status
        # One space wider than the longest tier: "not_determinable" filled 16 exactly and
        # ran into the section name.
        typer.secho(f"  {tier:<17}", fg=typer.colors.CYAN, nl=False)
        typer.echo(f"{card.section:<14} {card.card_id:<34} {card.title}")
        typer.echo(f"    Imputation mode: {card.imputation_mode or 'not recorded'}")
        if card.carrier is not None:
            from genetics.engine.carrier import STATE_LABELS

            typer.echo(
                f"    Carrier: {STATE_LABELS[card.carrier['state']]} -- "
                f"{card.carrier['variant']}; {card.carrier['condition']}, autosomal recessive"
            )
            typer.echo(f"    {card.carrier['typed_scope']}")
        if card.computation is not None and card.computation.get("source") == SCOPE_SOURCE:
            typer.echo(f"    {card.summary}")
        if card.risk_context is not None:
            typer.echo(f"    {card.summary}")
            typer.echo(f"    {card.risk_context}")
        elif card.multi_marker is not None:
            typer.echo(f"    {card.summary}")
        elif card.ancestry_comparison is not None:
            typer.echo(f"    {card.ancestry_comparison['text']}")
        for line in _ppv_lines(card.confidence, card.confidence_tier):
            typer.echo(f"    {line}")

    typer.echo("")
    if chosen is None:
        if scope is not None and scope["status"] == "not-recorded":
            typer.echo(f"  {scope['text']}")
        for line in _related_lines(bundle.cards):
            typer.echo(f"  {line}")
        typer.echo(
            f"  {len(bundle.cards)} card(s). `--json` for the full record and its citations."
        )
        return

    for section_name in reads.in_report_order(chosen):
        for line in _section_lines(reads.section_context(section_name, bundle)):
            typer.echo(f"  {line}")
        typer.echo("")
    typer.echo(
        f"  {len(shown)} of {len(bundle.cards)} card(s). "
        f"`genetics runs card {bundle.path.name} <card-id>` prints one in full."
    )


def _ppv_lines(confidence: Mapping[str, Any] | None, tier: str | None, said: str = "") -> list[str]:
    """The empirical confirmation rate a likely-artifact card states on its face (4.1).

    ``said`` is text already printed above these lines. ``runs card`` passes the sentence
    that says what decided the tier, which gives the rate for a rare call, so that the rate
    is stated once and its scope and the clinical notice still follow.
    """
    from genetics.engine.ppv import CLINICAL_NOTICE, confirmation_text

    if confidence and confidence.get("empirical_ppv"):
        ppv = confidence["empirical_ppv"]
        rate = confirmation_text(ppv["estimate"], ppv["population_frequency_ceiling"])
        return [
            *(() if rate in said else (rate,)),
            f"{ppv['applies_to']} {CLINICAL_NOTICE}",
        ]
    if tier == "likely-artifact":
        return ["No empirical PPV was recorded for this reliability failure.", CLINICAL_NOTICE]
    return []


def _pointer_names(pointers: Sequence[Mapping[str, Any]]) -> str:
    return "; ".join(
        f"{p['card_id']} ({p['section']})" if p["in_run"] else f"{p['title']} (not in this run)"
        for p in pointers
    )


def _related_lines(cards: Sequence[StoredCard]) -> list[str]:
    """The sections' pointers to cards other sections hold (M12.1), as the dashboard shows them.

    A card is listed once, in its own section; a pointer only names it. Resolved against this
    run's cards by :func:`reads.related`, so a run saved before the card existed says so
    instead of naming a card id the run cannot show.
    """
    from genetics.engine import sections

    return [
        f"{sections.SECTIONS[section].title} also points to: "
        f"{_pointer_names(reads.related(section, cards))}"
        for section in sections.SECTION_ORDER
        if sections.SECTIONS[section].related
    ]


def _section_lines(context: Mapping[str, Any]) -> list[str]:
    """One section's frame, as the dashboard draws it around the cards."""
    lines = [
        f"{context['title']}: {context['card_count']} card(s), "
        f"{context['interpreted']} with a finding",
        f"  {context['blurb']}",
    ]
    if context["empty_reason"]:
        lines.append(f"  {context['empty_reason']}")
    framing = context.get("section_framing")
    if framing is not None:
        lines.append(f"  {framing['title']}: {framing['text']}")
    scope = context.get("carrier_scope")
    if scope is not None and scope["status"] == "not-recorded":
        lines.append(f"  {scope['title']}: {scope['text']}")
    if context["related"]:
        lines.append(f"  Also points to: {_pointer_names(context['related'])}")
    lines.extend(
        f"  {record['title']}: `{record['command']}`" for record in context["saved_records"]
    )
    return lines


# ---------------------------------------------------------------------------
# runs card
# ---------------------------------------------------------------------------


@runs_app.command("card")
def runs_card(
    run_id: Annotated[str, typer.Argument(help="Run id, as reported by `genetics runs list`.")],
    card_id: Annotated[str, typer.Argument(help="Card id, as `runs show` prints it.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Print one saved card in full: claim, evidence, confidence inputs, caveats, citations.

    States your genotype at the card's marker, as ``runs show`` does. To research the card
    elsewhere, start from ``genetics cards evidence <card-id>``, which holds no genotype
    (AGENTS.md 1.3).

    ``--json`` holds the saved card under ``card``. Section titles, citation links, the
    pointers between sections and what decided the card's tier are under ``current_context``,
    because this engine adds them when it reads the run.
    """
    try:
        bundle = store.load_run(run_id, progress=store.report_to_console)
    except (BundleError, OSError) as exc:
        _fail(exc, as_json=as_json)
    card = reads.find_card(bundle, card_id)
    if card is None:
        # A sentence, as the dashboard gives for the same stale link.
        _refuse(
            "card-not-found",
            f"Run {bundle.path.name} has no card called {card_id!r}. It may be from another "
            "run, or from a version of the knowledge pack that no longer carries it. "
            f"`genetics runs show {bundle.path.name}` lists this run's cards.",
            as_json=as_json,
        )
    view = reads.card_view(bundle, card)
    if as_json:
        # Deliberately not scanned -- see the module docstring.
        typer.echo(json.dumps(contract.tagged("runs.card", view), indent=2, ensure_ascii=False))
        return
    typer.echo("\n".join(_card_lines(view)))


def _no_evidence(card: Mapping[str, Any], format_version: int) -> str:
    """Why a saved card has no evidence block; three different facts."""
    from genetics.run.bundle import EVIDENCE_FORMAT_VERSION

    if card["kind"] == "impossibility":
        return "None: this card states an assay limit, not a population effect."
    if format_version < EVIDENCE_FORMAT_VERSION:
        return f"Not recorded: this bundle predates format {EVIDENCE_FORMAT_VERSION}."
    return "No phenotype estimate applies to this result; the caveats say why."


def _card_lines(view: Mapping[str, Any]) -> list[str]:
    from genetics.cli.render import (
        bullet_lines,
        citation_lines,
        confidence_lines,
        evidence_lines,
        frequency_lines,
        variant_line,
    )

    card = view["card"]
    context = view["current_context"]
    lines = [
        card["title"],
        f"  card        {card['card_id']}",
        f"  section     {card['section']} ({context['section']['title']})",
        f"  kind        {card['kind']}",
    ]
    if card["gene"]:
        lines.append(f"  gene        {card['gene']}")
    lines.append(f"  status      {card['status']}")
    lines.append(f"  confidence  {card['confidence_tier'] or 'not scored'}")
    if card["variant"] is not None:
        lines.append(f"  variant     {variant_line(card['variant'])}")
    observation = card["observation"] or {}
    if observation:
        call = f"  call        {_shown(observation.get('call_source'))}"
        if observation.get("call_source") == "imputed":
            call += f"; imputation quality {_shown(observation.get('imputation_quality'))}"
        lines.append(
            f"{call}; strand {_shown(card['match'].get('strand'))}; ancestry match to the "
            f"study {_shown(observation.get('ancestry_match'))}"
        )
    lines.append(f"  imputation  {card['imputation_mode'] or 'not recorded'}")
    lines += ["", "Summary", f"  {card['summary']}"]
    if card["detail"] and card["detail"] != card["summary"]:
        lines += ["", "Detail", f"  {card['detail']}"]
    if card["impossibility_reason"]:
        lines += ["", "Not determinable from this data", f"  {card['impossibility_reason']}"]
    if card["risk_context"]:
        lines += ["", "Risk context", f"  {card['risk_context']}"]
    comparison = card["ancestry_comparison"]
    if comparison is not None:
        lines += ["", "Ancestry comparison", f"  {comparison.get('text')}"]
    if card["carrier"] is not None:
        from genetics.engine.carrier import STATE_LABELS

        carrier = card["carrier"]
        state = carrier.get("state")
        lines += [
            "",
            "Carrier status",
            f"  {STATE_LABELS.get(state, state)} -- "
            f"{carrier.get('variant')}; {carrier.get('condition')}",
            f"  {carrier.get('typed_scope')}",
        ]
    if card["multi_marker"] is not None:
        markers = card["multi_marker"].get("markers", [])
        lines += ["", f"Read from {len(markers)} markers; --json has each one's observation."]
    if card["computation"] is not None:
        lines += [
            "",
            f"Computed from {card['computation'].get('source')}; --json has the full record.",
        ]
    lines += [
        "",
        "Evidence",
        *evidence_lines(card["evidence"], absent=_no_evidence(card, view["format_version"])),
        "",
        "Confidence",
        *confidence_lines(context["confidence"]),
        *(
            f"  {line}"
            for line in _ppv_lines(
                card["confidence"], card["confidence_tier"], context["confidence"]["reason"]
            )
        ),
        "",
        "Population frequencies",
        *frequency_lines(card["frequencies"], card["confidence_frequency"]),
        "",
        "Caveats",
        *(
            bullet_lines([*card["authored_caveats"], *card["computed_caveats"]])
            or ["  None recorded."]
        ),
        "",
        "Citations",
        *citation_lines(card["citations"], context["citation_links"]),
    ]
    if context["related"] or context["pointed_from"]:
        lines += ["", "Elsewhere in this report (current sections)"]
        if context["related"]:
            lines.append(
                f"  {context['section']['title']} also points to: "
                f"{_pointer_names(context['related'])}"
            )
        if context["pointed_from"]:
            lines.append(f"  Pointed to from: {', '.join(context['pointed_from'])}")
    return lines


# ---------------------------------------------------------------------------
# runs search
# ---------------------------------------------------------------------------


@runs_app.command("search")
def runs_search(
    run_id: Annotated[str, typer.Argument(help="Run id, as reported by `genetics runs list`.")],
    query: Annotated[
        list[str],
        typer.Argument(help="A trait, gene, rsID or phrase, such as `curly hair`."),
    ],
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Show only the best N. The total is still stated."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Find a saved run's cards by what they are about, with each one's result (M13.3).

    Searches what the run saved for each card: id, title, gene, rsIDs, the summary and
    detail it recorded, caveats and citations. Cards are ranked by the query alone, never by
    status or confidence, and none is left out for either. A card matching only some of the
    query's words is listed below the cards matching all of them.

    Each hit shows the card's saved summary, which states your genotype at its marker, as
    ``runs show`` does. To find a card without opening a run, use ``genetics cards search``,
    which holds no genotype. A query that reads as a genotype is refused by both: search for
    the variant, never for a call at it (AGENTS.md 1.3).

    ``--json`` holds each matched card's saved face under ``results``. The query, the counts
    and each hit's score and matched fields are under ``current_context``, in the same
    order, because this engine ranks when it reads the run.
    """
    from genetics.cli.render import search_heading, search_hit_lines

    parsed = contract.search_query(query, as_json=as_json)
    try:
        bundle = store.load_run(run_id, progress=store.report_to_console)
    except (BundleError, OSError) as exc:
        _fail(exc, as_json=as_json)
    view = reads.search_view(bundle, parsed, limit)
    if as_json:
        # Deliberately not scanned -- see the module docstring.
        typer.echo(json.dumps(contract.tagged("runs.search", view), indent=2, ensure_ascii=False))
        return

    context = view["current_context"]
    typer.echo(search_heading(context, f"run {view['run_id']}"))
    for card, hit in zip(view["results"], context["hits"], strict=True):
        tier = card["confidence_tier"] or card["status"]
        typer.secho(f"  {tier:<17}", fg=typer.colors.CYAN, nl=False)
        typer.echo(f"{card['section']:<14} {card['card_id']:<34} {card['title']}")
        typer.echo(f"      {card['summary']}")
        for line in search_hit_lines(hit, len(context["terms"])):
            typer.echo(line)
    if view["results"]:
        typer.echo(f"`genetics runs card {view['run_id']} <card-id>` prints one in full.")


# ---------------------------------------------------------------------------
# runs qc
# ---------------------------------------------------------------------------


@runs_app.command("qc")
def runs_qc(
    run_id: Annotated[str, typer.Argument(help="Run id, as reported by `genetics runs list`.")],
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Print a saved run's QC report, imputation record and provenance. No genotype.

    Call rates, inferred sex and its evidence, the build check, duplicates and every QC
    warning, then which engine, knowledge pack, references and tools produced the run.
    Checked for genotypes before printing, like ``runs list``.
    """
    try:
        bundle = store.load_run(run_id, progress=store.report_to_console)
    except (BundleError, OSError) as exc:
        _fail(exc, as_json=as_json)
    view = reads.qc_view(bundle)
    if as_json:
        text = json.dumps(contract.tagged("runs.qc", view), indent=2, ensure_ascii=False)
        assert_no_genotype(text, context="runs qc JSON output")
        typer.echo(text)
        return
    text = "\n".join(_qc_lines(view))
    assert_no_genotype(text, context="runs qc output")
    typer.echo(text)


def _get(mapping: Any, *path: str) -> Any:
    """A nested field, or ``None`` where another version wrote a different shape."""
    for key in path:
        if not isinstance(mapping, Mapping):
            return None
        mapping = mapping.get(key)
    return mapping


def _shown(value: Any, spec: str = "") -> str:
    if value is None or isinstance(value, bool):
        return "-"
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return str(value)


def _qc_lines(view: Mapping[str, Any]) -> list[str]:
    """The QC record read defensively: a field another version did not write renders as -."""
    qc = view["qc"]
    provenance = view["provenance"]
    lines = [
        f"run {view['run_id']}",
        f"  saved        {view['created_at']}",
        f"  vendor       {_shown(_get(qc, 'vendor'))}",
        f"  markers      {_shown(_get(qc, 'call_rates', 'total_markers'), ',')}",
        f"  called       {_shown(_get(qc, 'call_rates', 'called'), ',')} "
        f"({_shown(_get(qc, 'call_rates', 'call_rate'), '.4%')})",
        f"  no-calls     {_shown(_get(qc, 'call_rates', 'no_call'), ',')}",
        f"  indels       {_shown(_get(qc, 'indels', 'indel_markers'), ',')} "
        "(excluded from matching by default)",
        "  autosomal heterozygosity  "
        f"{_shown(_get(qc, 'heterozygosity', 'autosomal_het_rate'), '.4f')}",
        f"  inferred sex              {_shown(_get(qc, 'sex', 'inferred'))}",
        f"    X heterozygosity (non-PAR)  {_shown(_get(qc, 'sex', 'x_het_rate'), '.4f')} over "
        f"{_shown(_get(qc, 'sex', 'x_nonpar_loci'), ',')} loci",
        f"    Y call rate                 {_shown(_get(qc, 'sex', 'y_call_rate'), '.4f')} over "
        f"{_shown(_get(qc, 'sex', 'y_loci'), ',')} loci",
    ]
    notes = _get(qc, "sex", "notes")
    if isinstance(notes, list):
        lines.extend(f"    - {note}" for note in notes)
    lines += [
        f"  het calls on haploid chromosomes  {_shown(_get(qc, 'het_haploid_calls'), ',')}",
        f"  duplicate rsIDs {_shown(_get(qc, 'duplicates', 'duplicate_rsids'), ',')}, "
        f"duplicate positions {_shown(_get(qc, 'duplicates', 'duplicate_positions'), ',')}",
        f"  build        declared {_shown(_get(qc, 'build', 'declared'))}, verdict "
        f"{_shown(_get(qc, 'build', 'verdict'))}",
    ]
    warnings = _get(qc, "warnings")
    if isinstance(warnings, list) and warnings:
        # Every warning, in QC's order: AGENTS.md 0.1A labels, it does not filter.
        lines += ["", "Warnings", *(f"  ! {warning}" for warning in warnings)]
    imputation = view["imputation"]
    lines += [
        "",
        "Imputation",
        f"  mode {_shown(_get(imputation, 'mode'))}; status {_shown(_get(imputation, 'status'))}; "
        f"card input {_shown(_get(imputation, 'card_input'))}",
        f"  full provenance {_shown(view['imputation_provenance_status'])}; "
        f"`genetics runs imputation {view['run_id']}` prints it",
        "",
        "Provenance",
        f"  engine       {_shown(_get(provenance, 'engine_version'))}",
        f"  knowledge    {_shown(_get(provenance, 'knowledge', 'card_count'))} card(s), digest "
        f"{_shown(_get(provenance, 'knowledge', 'digest'))}",
    ]
    references = _get(provenance, "references")
    sources = _get(references, "sources")
    if isinstance(sources, Mapping) and sources:
        lines.append(f"  references   {len(sources)} source(s)")
        lines.extend(
            f"    {name}  {_shown(_get(entry, 'version'))}  {_shown(_get(entry, 'license'))}"
            for name, entry in sources.items()
        )
    else:
        lines.append(f"  references   none recorded: {_shown(_get(references, 'reason'))}")
    tools = _get(provenance, "tools")
    if isinstance(tools, Mapping) and tools:
        lines.append("  tools")
        lines.extend(
            f"    {name}  {_shown(_get(entry, 'version'))}" for name, entry in tools.items()
        )
    else:
        lines.append("  tools        none recorded")
    return lines


def _ancestry_line(record: Mapping[str, Any] | None) -> str:
    """The population placement in one line, read from what the bundle recorded.

    Read defensively, as everything in a months-old bundle is: a missing or odd-shaped field
    renders as absent rather than raising, because this is a display of a record that the
    reader already accepted.
    """
    if record is None:
        return "not recorded (saved before the ancestry stage existed)"
    population = record.get("population")
    if not isinstance(population, Mapping):
        return "not recorded"
    status = population.get("status")
    if status == "placed":
        return f"placed: {population.get('population')} ({population.get('region')})"
    if status == "declined":
        return "declined: no reference population fits (see --json for the nearest and why)"
    return f"{status}: {population.get('reason')}"


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
