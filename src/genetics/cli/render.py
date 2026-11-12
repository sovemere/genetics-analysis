"""Plain-text renderings shared by the agent's read commands (roadmap M13.1, M13.3,
M13.4).

Each takes saved or declared data as a mapping and returns lines, so ``genetics runs card``
and ``genetics cards evidence`` say the same thing about the same evidence block. Read
defensively, as everything from a saved bundle is: a missing field renders as absent.

A variant is written as ``rs123 at 2:456 (GRCh37), alleles C and T`` -- never as an
identifier followed by its alleles in columns or after a colon, which is the shape
:mod:`genetics.privacy` treats as a genotype.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def _number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "not recorded"
    return f"{value:,}" if isinstance(value, int) else f"{value:g}"


def variant_line(variant: Mapping[str, Any]) -> str:
    alleles = variant.get("alleles")
    named = (
        " and ".join(str(a) for a in alleles)
        if isinstance(alleles, Sequence) and not isinstance(alleles, str)
        else "not recorded"
    )
    return (
        f"{variant.get('rsid')} at {variant.get('chrom')}:{variant.get('pos_grch37')} (GRCh37), "
        f"alleles {named}"
    )


def evidence_lines(
    evidence: Mapping[str, Any] | None, *, absent: str, indent: str = "  "
) -> list[str]:
    """The published claim: tier, replication, size, study population, effect.

    ``absent`` says why there is none, which only the caller knows: an assay-limit card, an
    outcome with no phenotype estimate (``evidence: null``), or a bundle older than format 2.
    """
    if evidence is None:
        return [f"{indent}{absent}"]
    ancestry = evidence.get("ancestry")
    populations = (
        ", ".join(str(a) for a in ancestry)
        if isinstance(ancestry, Sequence) and not isinstance(ancestry, str) and ancestry
        else "not recorded"
    )
    lines = [
        f"{indent}tier {evidence.get('tier')}; replication {evidence.get('replication')}; "
        f"n = {_number(evidence.get('sample_size'))}; study ancestry {populations}"
    ]
    effect = evidence.get("effect")
    if isinstance(effect, Mapping):
        text = f"{indent}effect {effect.get('measure')} {_number(effect.get('value'))}"
        if effect.get("units"):
            text += f" {effect['units']}"
        low, high = effect.get("ci_low"), effect.get("ci_high")
        if low is not None and high is not None:
            text += f" (CI {_number(low)} to {_number(high)})"
        lines.append(text)
        if effect.get("context"):
            lines.append(f"{indent}  {effect['context']}")
    attenuation = evidence.get("within_family_attenuation")
    if attenuation is not None:
        lines.append(
            f"{indent}within-family attenuation: {_number(attenuation)} of the population "
            "effect survives a within-sibship design"
        )
    return lines


def citation_lines(
    citations: Iterable[Mapping[str, Any]],
    links: Sequence[Mapping[str, Any]] | None = None,
    indent: str = "  ",
) -> list[str]:
    """Each citation with its title, note and public page where one resolves."""
    lines: list[str] = []
    listed = list(citations)
    # zip(strict=True): a link list built from different citations is a caller bug, and
    # pairing a DOI with the wrong page is worse than failing.
    paired = zip(listed, [None] * len(listed) if links is None else links, strict=True)
    for citation, link in paired:
        name = f"{citation.get('type')}:{citation.get('id')}"
        if citation.get("database"):
            name = f"{citation['database']} {name}"
        lines.append(f"{indent}{name}  {citation.get('title') or ''}".rstrip())
        if citation.get("note"):
            lines.append(f"{indent}  note: {citation['note']}")
        url = citation.get("url") if link is None else link.get("url")
        if url:
            lines.append(f"{indent}  {url}")
    if not lines:
        lines.append(f"{indent}None recorded.")
    return lines


def bullet_lines(items: Iterable[str], indent: str = "  ") -> list[str]:
    return [f"{indent}- {item}" for item in items]


def _value(value: Any) -> str:
    if value is None:
        return "not recorded"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return _number(value)
    return json.dumps(value, sort_keys=True)


def _observed(row: Mapping[str, Any]) -> str:
    """A row's saved values. One value under the row's own name prints bare."""
    values = row.get("values")
    values = values if isinstance(values, Mapping) else {}
    if list(values) == [row.get("name")]:
        return _value(values[row["name"]])
    shown = [f"{key} {_value(value)}" for key, value in values.items() if value is not None]
    return ", ".join(shown) or "not recorded"


def confidence_lines(explanation: Mapping[str, Any], indent: str = "  ") -> list[str]:
    """A card's tier, what decided it, and every input behind it (AGENTS.md 6, M13.4).

    ``explanation`` is the block :func:`genetics.run.explain.explain_confidence` builds and
    ``runs card --json`` prints as ``current_context.confidence``, so the text and the JSON
    say the same thing whichever of the two saved places the card keeps its inputs in.
    """
    if explanation["basis"] == "none":
        return [f"{indent}{explanation['reason']}"]
    head = f"{indent}tier {explanation['tier'] or 'none'}"
    if explanation["score"] is not None:
        head += f"; score {_number(explanation['score'])}"
        if explanation["score_tier"] not in (None, explanation["tier"]):
            head += f" (on its own the score gives {explanation['score_tier']})"
    lines = [head, f"{indent}{explanation['reason']}"]
    for row in explanation["inputs"]:
        line = f"{indent}{row['name']:<32} {_observed(row)}"
        if row["weight"] is not None:
            line = (
                f"{indent}{row['name']:<18} {_observed(row):<44} "
                f"component {_number(row['component'])}, weight {_number(row['weight'])}, "
                f"lost {_number(row['lost'])}"
            )
        lines.append(line)
    limiting = set(explanation["limiting"])
    held = (
        "; sets the tier"
        if explanation["basis"] == "ceiling"
        else "; keeps the tier here whatever the score"
    )
    for ceiling in explanation["ceilings"]:
        decides = (
            held if ceiling["input"] in limiting and ceiling["tier"] == explanation["tier"] else ""
        )
        lines.append(
            f"{indent}ceiling from {ceiling['input']}: at most {ceiling['tier']}, because "
            f"{ceiling['rule']}{decides}"
        )
    return lines


def frequency_lines(
    frequencies: Iterable[Mapping[str, Any]],
    used: Mapping[str, Any] | None,
    indent: str = "  ",
) -> list[str]:
    """Population allele frequencies, and which one the confidence calculation used."""

    def one(frequency: Mapping[str, Any]) -> str:
        return (
            f"allele {frequency.get('allele')} {_number(frequency.get('frequency'))} "
            f"in {frequency.get('population')} ({frequency.get('source')})"
        )

    lines = [f"{indent}{one(f)}" for f in frequencies]
    if used is not None:
        lines.append(f"{indent}used for confidence: {one(used)}")
    return lines or [f"{indent}None recorded."]


def search_heading(view: Mapping[str, Any], searched: str) -> str:
    """One line saying what was asked, what was searched for and how much came back (M13.3).

    ``view`` is the query block both search payloads share. Dropped words and a ``--limit``
    are stated here, so neither narrows the result unseen.
    """
    total, shown = view["total"], len(view["hits"])
    count = "No card" if total == 0 else f"{total} of {view['searched']} card(s)"
    verb = "matches" if total <= 1 else "match"
    line = f"{count} in {searched} {verb} {view['query']!r} (terms: {', '.join(view['terms'])}"
    if view["ignored"]:
        line += f"; ignored: {', '.join(view['ignored'])}"
    line += ")."
    if total == 0:
        line += f" {view['searched']} card(s) searched."
    if shown < total:
        line += f" Showing the best {shown}."
    return line


def search_hit_lines(
    hit: Mapping[str, Any], term_count: int, *, indent: str = "      "
) -> list[str]:
    """Why a card matched: how many terms, the score, and each field with its terms."""
    where = "; ".join(f"{match['field']}: {', '.join(match['terms'])}" for match in hit["matched"])
    return [
        f"{indent}{hit['terms_matched']} of {term_count} term(s), score {hit['score']:g}; {where}"
    ]
