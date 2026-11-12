"""CLI for reviewing the committed knowledge pack (roadmap M3.5, M13.1, M13.3).

``lint``, ``carriers`` and ``carrier-scope`` review the pack. ``evidence`` and ``search``
are agent reads: they open no run, hold no genotype, and scan their output to keep that
true. ``search`` finds a card id from a phrase; ``evidence`` prints what that card rests on.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import typer

cards_app = typer.Typer(
    name="cards",
    help="Validate and read the declarative knowledge pack.",
    no_args_is_help=True,
    add_completion=False,
)


@cards_app.command("lint")
def lint(
    knowledge: Annotated[
        Path | None,
        typer.Option(
            "--knowledge",
            file_okay=False,
            readable=True,
            help="Knowledge directory. Defaults to the committed knowledge/ pack.",
        ),
    ] = None,
    variant_index: Annotated[
        Path | None,
        typer.Option(
            "--variant-index",
            dir_okay=False,
            readable=True,
            help="dbSNP-derived Parquet index. Defaults beside the fetched dbSNP source.",
        ),
    ] = None,
    schema_only: Annotated[
        bool,
        typer.Option(
            "--schema-only",
            help=(
                "Skip dbSNP key resolution explicitly. Intended for offline CI; full lint "
                "fails if the reference index is unavailable."
            ),
        ),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Check schema, citations, templates, and dbSNP variant keys."""

    from genetics.engine.card_lint import (
        ParquetVariantResolver,
        default_variant_index,
        lint_directory,
    )
    from genetics.engine.cards import default_knowledge_dir

    if schema_only and variant_index is not None:
        raise typer.BadParameter(
            "--variant-index and --schema-only are mutually exclusive: one requests "
            "resolution and the other disables it"
        )

    root = knowledge or default_knowledge_dir()
    resolver = None
    if not schema_only:
        resolver = ParquetVariantResolver(
            variant_index or default_variant_index(),
            bind_to_manifest=variant_index is None,
        )
    report = lint_directory(root, resolver=resolver, resolve_variants=not schema_only)

    if as_json:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        colour = typer.colors.GREEN if report.ok else typer.colors.RED
        label = "PASS" if report.ok else "FAIL"
        typer.secho(
            f"{label}  {report.card_count} card(s), {report.rendered_templates} template render(s)",
            fg=colour,
            bold=True,
        )
        if report.variant_resolution.value == "skipped":
            typer.secho(
                "  variant keys: SKIPPED (--schema-only)",
                fg=typer.colors.YELLOW,
            )
        else:
            typer.echo(
                f"  variant keys: {report.resolved_variants}/"
                f"{report.variant_count} resolved via {report.resolver or 'no resolver'}"
            )
        for issue in report.issues:
            owner = f" [{issue.card_id}]" if issue.card_id else ""
            typer.secho(f"  {issue.code}{owner}: {issue.message}", fg=typer.colors.RED)

    if not report.ok:
        raise typer.Exit(code=1)


@cards_app.command("carrier-scope")
def carrier_scope(
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
    """Compare the carrier panel with a published screening gene list (M11.6).

    A property of the knowledge pack, not of a run: no genotype is read.
    """

    from genetics.engine.cards import CardError, KnowledgePack
    from genetics.engine.carrier_scope import ALLELE_CLASSES, MECHANISMS, pack_scope, scope_summary

    try:
        scope = pack_scope(KnowledgePack.load(knowledge))
    except CardError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None
    if scope is None:
        typer.secho(
            "error: this pack has no carrier-screening scope card", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(code=1)

    if as_json:
        typer.echo(json.dumps(scope, indent=2))
        return
    typer.echo(scope_summary(scope))
    typer.echo("")
    typer.secho("Typed", bold=True)
    for gene in scope["genes"]["typed"]:
        typer.echo(f"  {gene['gene']:<9} {gene['markers']} marker(s)  {gene['condition']}")
    if scope["genes"]["typed_outside_reference"]:
        names = ", ".join(scope["genes"]["typed_outside_reference"])
        typer.echo(f"  Also typed, not on this list: {names}")
    typer.secho("Assay limits", bold=True)
    for gene in scope["genes"]["assay_limited"]:
        typer.echo(f"  {gene['gene']:<9} {MECHANISMS[gene['mechanism']]}: {gene['statement']}")
    typer.secho("No card in this report", bold=True)
    typer.echo("  " + ", ".join(gene["gene"] for gene in scope["genes"]["no_card"]))
    typer.secho("Excluded alleles", bold=True)
    for name, label in ALLELE_CLASSES.items():
        typer.echo(f"  {label}: {scope['excluded_alleles'][name]}")
        for allele in scope["declaration"]["excluded_alleles"]:
            if allele["class"] == name:
                typer.echo(f"    {allele['gene']:<9} {allele['variant']} ({allele['rsid']})")


@cards_app.command("carriers")
def carriers(
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
    """List the carrier panel: every recessive-condition marker the pack types (M11.5).

    A property of the knowledge pack, not of a run: no genotype is read.
    """

    from genetics.engine.cards import CardError, KnowledgePack
    from genetics.engine.carrier import carrier_panel

    try:
        panel = carrier_panel(KnowledgePack.load(knowledge))
    except CardError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None

    if as_json:
        typer.echo(json.dumps(panel.to_dict(), indent=2))
        return
    typer.secho(
        f"{len(panel.entries)} typed marker(s) across {len(panel.conditions)} condition(s)",
        bold=True,
    )
    for condition in panel.conditions:
        typer.echo(f"  {condition}")
        for entry in panel.entries:
            if entry.declaration.condition == condition:
                note = (
                    "  (strand-symmetric: homozygotes not oriented)"
                    if entry.strand_symmetric
                    else ""
                )
                typer.echo(
                    f"    {entry.rsid:<13} {entry.declaration.variant}  [{entry.card_id}]{note}"
                )
    typer.echo(
        "Each card types only the marker listed. Copy-number, structural and indel alleles, "
        "and every untyped variant in these genes, are outside this panel. "
        "`genetics cards carrier-scope` sets it against a published screening list."
    )


@cards_app.command("evidence")
def evidence(
    card_id: Annotated[
        str, typer.Argument(help="Card id, as `runs show` and `runs card` print it.")
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
    """Print what a card rests on: variants, published effect, citations, caveats (M13.1).

    A property of the knowledge pack, not of a run: no genotype is read, and the output is
    checked for one before it is printed. Research a card from this, never from a run's
    output (AGENTS.md 1.3).
    """
    from genetics.cli import contract
    from genetics.engine.cards import CardError, KnowledgePack
    from genetics.engine.declaration import declaration
    from genetics.privacy import assert_no_genotype

    try:
        pack = KnowledgePack.load(knowledge)
    except CardError as exc:
        contract.refuse("knowledge", f"error: {exc}", as_json=as_json)
    card = pack.by_id(card_id)
    if card is None:
        contract.refuse(
            "card-not-found",
            f"No card called {card_id!r} is in the knowledge pack at {pack.source_dir}.",
            as_json=as_json,
        )
    data = declaration(card)

    if as_json:
        text = json.dumps(contract.tagged("cards.evidence", data), indent=2, ensure_ascii=False)
        assert_no_genotype(text, context="cards evidence JSON output")
        typer.echo(text)
        return

    text = evidence_text(data)
    assert_no_genotype(text, context="cards evidence output")
    typer.echo(text)


@cards_app.command("search")
def search(
    query: Annotated[
        list[str],
        typer.Argument(help="A trait, gene, rsID or phrase, such as `curly hair`."),
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
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Show only the best N. The total is still stated."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit JSON.")] = False,
) -> None:
    """Find cards in the knowledge pack by what they are about (M13.3).

    Searches every card's id, title, gene, rsIDs, trait, condition, HLA alleles, authored
    text, caveats and citations, and says which of those each hit matched. A card matching
    only some of the query's words is listed below the cards matching all of them.

    A property of the knowledge pack, not of a run: no genotype is read, and the output is
    checked for one before it is printed. A query that reads as a genotype is refused:
    search for the variant, never for a call at it (AGENTS.md 1.3). To search one saved
    run's cards and results, use ``genetics runs search <run> <query>``.
    """
    from genetics.cli import contract
    from genetics.engine import search as engine
    from genetics.engine.cards import CardError, KnowledgePack
    from genetics.privacy import assert_no_genotype

    parsed = contract.search_query(query, as_json=as_json)
    try:
        pack = KnowledgePack.load(knowledge)
    except CardError as exc:
        contract.refuse("knowledge", f"error: {exc}", as_json=as_json)
    view = engine.pack_view(pack.cards, parsed, limit)

    if as_json:
        text = json.dumps(contract.tagged("cards.search", view), indent=2, ensure_ascii=False)
        assert_no_genotype(text, context="cards search JSON output")
        typer.echo(text)
        return

    text = search_text(view)
    assert_no_genotype(text, context="cards search output")
    typer.echo(text)


def search_text(view: Mapping[str, Any]) -> str:
    """``cards search`` as text, from :func:`genetics.engine.search.pack_view`."""
    from genetics.cli.render import search_heading, search_hit_lines

    lines = [search_heading(view, "the knowledge pack")]
    for hit in view["hits"]:
        lines.append(f"  {hit['section']:<17}{hit['card_id']:<36} {hit['title']}")
        lines.extend(search_hit_lines(hit, len(view["terms"])))
    if view["hits"]:
        lines.append("`genetics cards evidence <card-id>` prints what a card rests on.")
    return "\n".join(lines)


def evidence_text(data: Mapping[str, Any]) -> str:
    """``cards evidence`` as text, from :func:`genetics.engine.declaration.declaration`."""
    from genetics.cli.render import bullet_lines, citation_lines, evidence_lines, variant_line
    from genetics.engine import sections

    lines = [
        data["title"],
        f"  card      {data['card_id']}",
        f"  section   {data['section']} ({sections.get(data['section']).title})",
        f"  kind      {data['kind']}",
    ]
    if data["gene"]:
        lines.append(f"  gene      {data['gene']}")
    lines.extend(f"  variant   {variant_line(v)}" for v in data["variants"])
    if data["impossibility_reason"]:
        lines += ["", "Not determinable from this data", f"  {data['impossibility_reason']}"]
    lines += [
        "",
        "Evidence",
        *evidence_lines(data["evidence"], absent="No published-effect block on this card."),
    ]
    for name, block in data["outcome_evidence"].items():
        lines += [
            "",
            f"Evidence for outcome {name}",
            *evidence_lines(
                block,
                absent=(
                    "No phenotype estimate applies to this outcome; "
                    "its confidence cannot exceed limited."
                ),
            ),
        ]
    polygenic = data["polygenic"]
    if polygenic is not None:
        lines += [
            "",
            "Polygenic score",
            f"  {polygenic['pgs_id']} ({polygenic['scoring_source']}); trait: {polygenic['trait']}",
        ]
        deciles = polygenic["decile_outcomes"]
        if deciles is not None:
            lines.append(
                f"  outcome by decile: {deciles['measure']} in {deciles['population']}, "
                f"n = {deciles['sample_size']:,}, base rate {deciles['base_rate']:g} "
                f"({deciles['source']})"
            )
    if data["hla"] is not None:
        names = ", ".join(alt["name"] for alt in data["hla"]["alternatives"])
        lines += ["", "HLA alleles read", f"  {names}"]
    if data["carrier"] is not None:
        carrier = data["carrier"]
        lines += [
            "",
            "Carrier declaration",
            f"  {carrier['variant']}; {carrier['condition']}, {carrier['inheritance']}; "
            f"ClinVar {carrier['clinvar']}",
            f"  {carrier['typed_scope']}",
        ]
    if data["method_evidence"] is not None:
        lines += ["", f"Computed by {data['computation']}; method evidence in --json."]
    lines += ["", "Citations", *citation_lines(data["citations"])]
    lines += ["", "Caveats", *(bullet_lines(data["caveats"]) or ["  None authored."])]
    return "\n".join(lines)
