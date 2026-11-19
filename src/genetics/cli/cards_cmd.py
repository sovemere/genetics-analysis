"""CLI for reviewing the committed knowledge pack (roadmap M3.5, M13.1, M13.3, M13.7, M14.3).

``lint``, ``carriers`` and ``carrier-scope`` review the pack. ``evidence`` and ``search``
are agent reads: they open no run, hold no genotype, and scan their output to keep that
true. ``search`` finds a card id from a phrase; ``evidence`` prints what that card rests on.
``check-query`` is the agent's last step before a web search: it says whether a query
written from that evidence may leave the machine. ``guide`` prints how to read a run's
results, which the dashboard's ``/guide`` page shows.
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


@cards_app.command("check-query")
def check_query(
    query: Annotated[
        list[str],
        typer.Argument(help="The search query, URL or text about to leave the machine."),
    ],
    card: Annotated[
        list[str] | None,
        typer.Option(
            "--card",
            help="A card the query was written from. Repeatable. Lists each query word "
            "its `cards evidence` does not print.",
        ),
    ] = None,
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
    """Check a query before it leaves the machine (M13.7, AGENTS.md 1.3).

    Run this on every web search, URL or text an agent is about to send while researching
    a card. It refuses a genotype written out (an rsID beside two alleles, a diplotype, any
    shape the privacy scanner knows) and a result told in words (zygosity, a count of
    copies, the first person, a run id, a confidence tier), and exits 1. With ``--card``,
    it also lists each word the cards' evidence does not print: such a word has to come
    from a paper already read.

    Reads the knowledge pack only. The query is never printed back.
    """
    from genetics import outbound
    from genetics.cli import contract
    from genetics.engine.cards import CardError, KnowledgePack
    from genetics.engine.declaration import declaration
    from genetics.privacy import assert_no_genotype

    text = " ".join(" ".join(query).split())
    if not outbound.words(text):
        contract.refuse(
            "empty-query",
            "The query has no letter or digit to check.",
            as_json=as_json,
            code=2,
        )
    evidence: list[str] = []
    card_ids = list(dict.fromkeys(card or ()))
    if card_ids:
        try:
            pack = KnowledgePack.load(knowledge)
        except CardError as exc:
            contract.refuse("knowledge", f"error: {exc}", as_json=as_json)
        for card_id in card_ids:
            authored = pack.by_id(card_id)
            if authored is None:
                contract.refuse(
                    "card-not-found",
                    f"No card called {card_id!r} is in the knowledge pack at {pack.source_dir}.",
                    as_json=as_json,
                )
            evidence.append(json.dumps(declaration(authored), ensure_ascii=False))
    view = check_view(outbound.check_query(text, evidence), card_ids)

    if as_json:
        out = json.dumps(contract.tagged("cards.check-query", view), indent=2, ensure_ascii=False)
        assert_no_genotype(out, context="cards check-query JSON output")
    else:
        out = check_text(view)
        assert_no_genotype(out, context="cards check-query output")
    typer.echo(out)
    if view["status"] == "refused":
        raise typer.Exit(code=1)


@cards_app.command("guide")
def guide(
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
    """How to read these results: the confidence legend and the reading guide (M14.3).

    The six tiers and what earns each, how a tier is decided (the score's weights and bands
    and every ceiling), why rarity lowers confidence, what a polygenic score can say, and
    what this array cannot tell you. The dashboard's ``/guide`` page shows the same
    document. Its thresholds are the confidence engine's own; no run is read, and the
    output is checked for a genotype before it is printed.
    """
    from genetics.cli import contract
    from genetics.engine.cards import CardError, KnowledgePack
    from genetics.privacy import assert_no_genotype
    from genetics.run.guide import reading_guide

    try:
        pack = KnowledgePack.load(knowledge)
    except CardError as exc:
        contract.refuse("knowledge", f"error: {exc}", as_json=as_json)
    data = reading_guide(pack)

    if as_json:
        text = json.dumps(contract.tagged("cards.guide", data), indent=2, ensure_ascii=False)
        assert_no_genotype(text, context="cards guide JSON output")
        typer.echo(text)
        return

    text = guide_text(data)
    assert_no_genotype(text, context="cards guide output")
    typer.echo(text)


def guide_text(data: Mapping[str, Any]) -> str:
    """``cards guide`` as text, from :func:`genetics.run.guide.reading_guide`."""
    import textwrap

    def para(text: str, indent: str = "  ") -> list[str]:
        return textwrap.wrap(text, width=88, initial_indent=indent, subsequent_indent=indent)

    lines = ["How to read these results", "", "Confidence tiers, strongest first"]
    for entry in data["legend"]:
        lines.append(f"  {entry['label']}")
        lines += para(entry["blurb"], "    ")
        lines += para(entry["earned_by"], "    ")
    reading = data["reading"]
    lines += ["", reading["title"]]
    for paragraph in reading["paragraphs"]:
        lines += [*para(paragraph), ""]
    lines.append("  Status badges:")
    lines += [f"    {row['label']:<34} {row['status']}" for row in reading["statuses"]]

    confidence = data["confidence"]
    lines += ["", confidence["title"]]
    for paragraph in confidence["paragraphs"]:
        lines += [*para(paragraph), ""]
    lines.append("  Inputs (one call / polygenic score), weight:")
    lines += [
        f"    {row['single_call_label']} / {row['polygenic_label']}: {row['weight']:.2f}"
        for row in confidence["inputs"]
    ]
    lines.append("  Ceilings, weakest tier first:")
    for rule in confidence["ceilings"]:
        applies = ", ".join(rule["applies_to"])
        lines.append(f"    at most {rule['tier_label'].lower()}: {rule['rule']} ({applies})")

    rarity = data["rarity"]
    lines += ["", rarity["title"]]
    for paragraph in rarity["paragraphs"]:
        lines += [*para(paragraph), ""]
    lines.append("  Allele-frequency component:")
    for row in rarity["frequency_components"]:
        if row["below"] is None:
            band = f"{100 * row['from']:g}% or more"
        elif row["from"] is None:
            band = f"below {100 * row['below']:g}%"
        else:
            band = f"{100 * row['from']:g}% to below {100 * row['below']:g}%"
        lines.append(f"    {band:<28} {row['component']:.2f}")
    lines.append(f"    {'not available':<28} {rarity['unknown_frequency_component']:.2f}")

    polygenic = data["polygenic"]
    lines += ["", polygenic["title"]]
    for paragraph in polygenic["paragraphs"]:
        lines += [*para(paragraph), ""]
    lines.append(f"  {len(polygenic['cards'])} polygenic cards; the list is in --json.")

    array = data["array"]
    lines += ["", array["title"]]
    lines += para(array["paragraphs"][0])
    for limit in array["limits"]:
        lines += ["", f"  {limit['title']}", *para(limit["text"], "    ")]
    lines.append("")
    for paragraph in array["paragraphs"][1:]:
        lines += para(paragraph)
    lines += [
        f"    {card['title']} ({card['section_title']}): `{card['card_id']}`"
        for card in array["not_determinable"]
    ]

    lines += ["", "Sources"]
    for source in data["sources"]:
        lines += para(f"{source['title']}. doi:{source['id']}. {source['supports']}")
    return "\n".join(lines)


def check_view(check: Any, card_ids: list[str]) -> dict[str, Any]:
    """``cards check-query`` as data, from :class:`genetics.outbound.QueryCheck`."""
    return {
        "status": check.status,
        "length": check.length,
        "problems": [
            {
                "rule": problem.rule.value,
                "kind": problem.rule.kind,
                "start": problem.start,
                "end": problem.end,
                "advice": problem.advice,
            }
            for problem in check.problems
        ],
        "cards": card_ids,
        "unsourced": None if check.unsourced is None else list(check.unsourced),
    }


def check_text(view: Mapping[str, Any]) -> str:
    """``cards check-query`` as text. Never repeats the query."""
    status = view["status"]
    if status == "refused":
        lines = ["refused: do not send this query."]
        for problem in view["problems"]:
            lines.append(
                f"  {problem['rule']} at characters {problem['start']}-{problem['end']}: "
                f"{problem['advice']}"
            )
        return "\n".join(lines)
    if status == "unsourced":
        listed = ", ".join(view["unsourced"])
        return (
            f"unsourced: no rule refuses this query, but `cards evidence` for "
            f"{', '.join(view['cards'])} does not print: {listed}. Send it only if each "
            "word comes from a paper already read."
        )
    if view["cards"]:
        return "clean: no rule refuses this query, and every word is in the cards' evidence."
    return (
        "clean: no rule refuses this query. Pass --card to check its words against the "
        "evidence it was written from."
    )


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
