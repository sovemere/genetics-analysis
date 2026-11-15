"""The agent review walk-through, docs/agent_usage.md (roadmap M13.6).

The page shows commands, their output and the keys a review reads. This module runs each
one, so the page fails here when a command, an option, a key or a card's wording changes.

The saved run is the one the page describes: committed cards matched against an invented
table holding each card's first and last declared allele. No export is read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli import contract
from genetics.cli.main import app
from genetics.engine.cards import KnowledgePack, default_knowledge_dir
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import match_pack
from genetics.engine.search import tokenize
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.paths import runs_dir
from genetics.privacy import find_genotypes
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BundleError,
    BundleIntegrityError,
    BundleVersionError,
    write_bundle,
)
from genetics.run.pipeline import observations
from genetics.run.store import RunNotFoundError
from genetics.testing.parity import command_problem

runner = CliRunner()

ROOT = Path(__file__).parents[1]
PAGE = ROOT / "docs" / "agent_usage.md"

CARD_IDS = (
    "wnt10a_hair_curl",
    "lce3e_region_hair_curl",
    "ofcc1_region_hair_curl",
    "tchh_hair_morphology",
    "methylation_epigenetic_age",
)
"""The four cards `cards search curly hair` puts first, and one assay-limit card."""

GAP = "..."
"""A line of a shown output that stands for lines left out."""

_MARKER = re.compile(r"<!-- (run|keys|queries): (.+?) -->")
FENCE = "```"
_WRITTEN = re.compile(r"`(genetics [^`\n]+)`")
_SHORT = re.compile(r"`((?:runs|cards|pgx|hla) [^`\n]+)`")
"""A command the page writes without its first word, as in ``runs show --section``."""
_RESULT_COMMANDS = (
    "runs card",
    "runs show",
    "runs search",
    "runs clinvar",
    "runs secondary",
    "pgx calls",
    "hla calls",
)
"""Commands whose output states the reader's results (docs/agent_cli.md)."""


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def marked(kind: str, text: str | None = None) -> list[tuple[str, str]]:
    """Each ``<!-- kind: argument -->`` on the page with the block that follows it."""
    lines = (page() if text is None else text).split("\n")
    found: list[tuple[str, str]] = []
    for at, line in enumerate(lines):
        marker = _MARKER.fullmatch(line)
        if marker is None or marker.group(1) != kind:
            continue
        # A fenced block runs to its closing fence and may hold blank lines; a table or a
        # list runs to the first blank line.
        fenced = lines[at + 1].startswith(FENCE)
        end = at + 2 if fenced else at + 1
        while lines[end] != (FENCE if fenced else ""):
            end += 1
        found.append((marker.group(2), "\n".join(lines[at + 1 : end + fenced]) + "\n"))
    return found


def shown(block: str) -> list[list[str]]:
    """A fenced block's lines, as the runs of lines between its gaps."""
    lines = block.rstrip("\n").split("\n")
    assert lines[0] == FENCE + "text" and lines[-1] == FENCE, "a run: block is a text fence"
    segments: list[list[str]] = [[]]
    for line in lines[1:-1]:
        if line.strip() == GAP:
            segments.append([])
        else:
            segments[-1].append(line.rstrip())
    return [segment for segment in segments if segment]


def missing(segments: list[list[str]], output: str) -> list[str] | None:
    """The first shown run of lines the output does not hold, in order, or ``None``."""
    printed = [line.rstrip() for line in output.split("\n")]
    start = 0
    for segment in segments:
        for at in range(start, len(printed) - len(segment) + 1):
            if printed[at : at + len(segment)] == segment:
                start = at + len(segment)
                break
        else:
            return segment
    return None


def first_cells(table: str) -> list[str]:
    """The backticked names in the first column of a markdown table's body rows."""
    names: list[str] = []
    for row in table.strip().split("\n")[2:]:
        names.extend(re.findall(r"`([^`]+)`", row.split("|")[1]))
    return names


def dig(document: Any, path: str) -> Any:
    """``card.match.reason`` in a document. Raises ``KeyError`` where a key is absent."""
    for key in path.split("."):
        if not isinstance(document, dict):
            raise KeyError(path)
        document = document[key]
    return document


@pytest.fixture(scope="module")
def full_pack() -> KnowledgePack:
    return KnowledgePack.load(default_knowledge_dir())


@pytest.fixture
def run_id(
    full_pack: KnowledgePack,
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    pack = KnowledgePack(
        tuple(card for card in full_pack.cards if card.id in CARD_IDS), full_pack.source_dir
    )
    rows: list[dict[str, Any]] = []
    for card in pack.cards:
        if card.match is None:
            continue
        variant = card.match.variants[0]
        first, last = variant.key.alleles[0], variant.key.alleles[-1]
        rows.append(
            {
                "rsid": variant.rsid,
                "chrom": variant.key.chrom.value,
                "pos_grch37": variant.key.pos_grch37,
                "a1": first,
                "a2": last,
                "genotype": "".join(sorted(first + last)),
                "call_status": "called",
            }
        )
    table = GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")
    matches = match_pack(pack, table)
    path = write_bundle(
        qc=sample_qc,
        cards=assemble_pack(pack, matches, observations(pack, matches)),
        pack=pack,
        ancestry=AncestryContext.not_run("synthetic test bundle"),
        runs_root=runs_dir(),
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    return path.name


def run(command: str, run_id: str) -> str:
    """What ``command`` prints, with the run's id written as the page writes it."""
    words = command.replace("<run>", run_id).split()
    assert words[0] == "genetics", command
    result = runner.invoke(app, words[1:])
    assert result.exit_code == 0, f"`{command}` exited {result.exit_code}"
    return result.stdout.replace(run_id, "<run>")


# ---------------------------------------------------------------------------
# The page as written
# ---------------------------------------------------------------------------


def test_every_command_the_page_writes_is_one_the_cli_runs() -> None:
    short = {f"genetics {command}" for command in _SHORT.findall(page())}
    assert {"genetics runs show --json", "genetics cards evidence --json"} <= short
    written = (
        set(_WRITTEN.findall(page()))
        | short
        | {command for kind in ("run", "keys") for command, _ in marked(kind)}
    )
    assert len(written) >= 30, "the page's commands were not found"
    problems = {
        command: problem
        for command in sorted(written)
        if (problem := command_problem(command, needs_json=False)) is not None
    }
    assert not problems, problems


@pytest.mark.parametrize(
    ("command", "problem"),
    [
        ("genetics runs facts <run>", "is not a command"),
        ("genetics runs", "is not a command"),
        ("genetics cards search curly hair --best 4", "--best, which the command does not take"),
    ],
)
def test_a_command_or_an_option_that_is_gone_is_found(command: str, problem: str) -> None:
    found = command_problem(command, needs_json=False)
    assert found is not None and problem in found
    assert command_problem("genetics cards search curly hair --limit 4", needs_json=False) is None
    # A flag's off form is an option too.
    assert command_problem("genetics serve --no-access-log", needs_json=False) is None
    # A page's data must be in JSON, so the parity table keeps the stricter reading.
    assert command_problem("genetics cards search curly hair --limit 4") is not None


def test_the_page_marks_what_it_shows() -> None:
    """A marker that stops matching would pass every check below by checking nothing."""
    assert [command for command, _ in marked("run")] == [
        "genetics cards search curly hair --limit 4",
        "genetics runs card <run> wnt10a_hair_curl",
        "genetics cards evidence wnt10a_hair_curl",
    ]
    assert [command for command, _ in marked("keys")] == [
        "genetics runs qc <run> --json",
        "genetics runs card <run> wnt10a_hair_curl --json",
    ]
    assert [card for card, _ in marked("queries")] == ["wnt10a_hair_curl"]
    assert page().count("<!--") == 6


def test_the_page_holds_no_genotype_and_sends_no_result_out() -> None:
    text = page()
    assert not find_genotypes(text), "docs/agent_usage.md reads as holding a genotype"
    rows = [
        [cell.strip() for cell in line.split("|")[1:4]]
        for line in text.split("## The steps")[0].split("\n")
        if line.startswith("| `genetics")
    ]
    assert len(rows) == 7
    # Only output that states no result may be sent out, and that is the three pack reads.
    safe = [commands for commands, _, may_leave in rows if may_leave == "yes"]
    assert len(safe) == 3
    assert all(states == "no" for _, states, may_leave in rows if may_leave == "yes")
    assert not any(word in " ".join(safe) for word in ("runs", "pgx", "hla"))
    assert all(may_leave.startswith("no") for _, _, may_leave in rows if may_leave != "yes")
    # Every command that states a result is in a row that says so.
    stating = " ".join(commands for commands, states, _ in rows if states.startswith("yes"))
    assert all(name in stating for name in _RESULT_COMMANDS)


def test_agents_md_points_to_the_page() -> None:
    assert "(docs/agent_usage.md)" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_the_values_the_page_names_in_prose_are_ones_a_command_prints(run_id: str) -> None:
    """Statuses, bases and error kinds that no shown output holds, so no block checks them."""
    text = page()
    defs = contract.document()["$defs"]
    assert "whose `status` is `readable`" in text
    assert "readable" in defs["run_status"]["enum"]
    assert "`matched` here. Any other status" in text
    assert "matched" in defs["card_status"]["enum"]

    def named(row: str) -> list[str]:
        found = re.search(rf"^\| `{re.escape(row)}` \| (.+) \|$", text, re.MULTILINE)
        assert found is not None, row
        return re.findall(r"`(\w+)`", found.group(1))

    assert named("current_context.confidence.basis") == defs["confidence_basis"]["enum"]
    assert named("card.observation.call_source") == defs["call_source"]["enum"]

    # Under "When a step fails", a bullet headed by kinds alone names what a command reports.
    failing = text.split("## When a step fails")[1].split("\n## ")[0]
    headed = [
        re.findall(r"`([a-z-]+)`", head.group(1))
        for head in re.finditer(r"^- \*\*((?:`[a-z-]+`(?:, )?)+)\.\*\*", failing, re.MULTILINE)
    ]
    assert [kinds[0] for kinds in headed] == ["card-not-found", "not-found", "genotype-in-query"]
    cannot_open = (
        BundleVersionError("x"),
        RunNotFoundError("x"),
        BundleIntegrityError("x"),
        OSError("x"),
        BundleError("x"),
    )
    assert sorted(headed[1]) == sorted(contract.run_error_kind(exc) for exc in cannot_open)
    absent = runner.invoke(app, ["runs", "card", run_id, "curly_hair", "--json"])
    assert absent.exit_code == 1
    assert json.loads(absent.stdout)["error"]["kind"] == "card-not-found"


# ---------------------------------------------------------------------------
# The worked example
# ---------------------------------------------------------------------------


def test_each_output_the_page_shows_is_what_the_command_prints(run_id: str) -> None:
    for command, block in marked("run"):
        segments = shown(block)
        assert segments, command
        absent = missing(segments, run(command, run_id))
        # The lines are the page's own, so quoting them names no saved run's value.
        assert absent is None, (
            f"docs/agent_usage.md shows lines `{command}` no longer prints, "
            f"starting {absent[0]!r}. Run the command and correct the page."
        )


def test_a_shown_line_the_command_does_not_print_fails(run_id: str) -> None:
    command, block = marked("run")[1]
    output = run(command, run_id)
    segments = shown(block)
    assert missing(segments, output) is None
    assert len(segments) == 4, "the gaps were not read"
    reworded = [[line.replace("moderate", "strong") for line in s] for s in segments]
    assert missing(reworded, output) == reworded[0]
    # Order counts: the last lines shown first are not found again after them.
    assert missing([segments[-1], segments[0]], output) == segments[0]
    # A run of lines must be side by side in the output, not merely each present.
    apart = [[segments[0][0], segments[1][0]]]
    assert missing(apart, output) == apart[0]


def test_each_key_the_page_names_is_in_the_document(
    run_id: str, agent_schema_check: Callable[[object], str]
) -> None:
    documents: dict[str, Any] = {}
    for (command, table), count in zip(marked("keys"), (6, 18), strict=True):
        document = json.loads(run(command, run_id))
        documents[agent_schema_check(document)] = document
        keys = first_cells(table)
        assert len(keys) == count, command
        for key in keys:
            dig(document, key)
    assert list(documents) == ["runs.qc", "runs.card"]
    qc, document = documents["runs.qc"], documents["runs.card"]
    with pytest.raises(KeyError):
        dig(document, "card.match.zygosity")
    # What the page says of the example run is what the run holds.
    assert dig(qc, "qc.warnings") == []
    assert dig(qc, "qc.build.verdict") == "indeterminate"
    assert dig(qc, "imputation.status") == "not_recorded"
    assert dig(document, "card.status") == "matched"
    assert dig(document, "card.observation.call_source") == "direct"
    assert dig(document, "current_context.confidence.basis") == "ceiling"
    assert dig(document, "current_context.confidence.limiting") == ["allele_frequency"]
    links = dig(document, "current_context.citation_links")
    assert [link["id"] for link in links] == [c["id"] for c in dig(document, "card.citations")]


def test_the_search_finds_four_cards_for_both_words_and_no_fifth() -> None:
    result = runner.invoke(app, ["cards", "search", "curly", "hair", "--json"])
    assert result.exit_code == 0
    both = [
        hit["card_id"] for hit in json.loads(result.stdout)["hits"] if hit["terms_matched"] == 2
    ]
    assert sorted(both) == sorted(CARD_IDS[:4])
    assert both[0] == "wnt10a_hair_curl"
    assert "Four cards match both words, and the pack has no fifth." in page()


def test_each_example_query_is_written_from_the_evidence_alone(run_id: str) -> None:
    ((card_id, listing),) = marked("queries")
    queries = re.findall(r"^- `([^`]+)`$", listing, re.MULTILINE)
    assert len(queries) == 4
    evidence = runner.invoke(app, ["cards", "evidence", card_id, "--json"])
    assert evidence.exit_code == 0
    known = set(tokenize(evidence.stdout))

    def strangers(query: str) -> set[str]:
        return set(tokenize(query)) - known

    for query in queries:
        assert not find_genotypes(query), "an example query reads as a genotype"
        assert not strangers(query), f"{query!r} uses words `cards evidence` does not print"
        accepted = runner.invoke(app, ["cards", "search", *query.split(), "--json"])
        assert accepted.exit_code == 0, query

    # The rule has teeth: words that only the run's result holds are strangers.
    card = json.loads(run(f"genetics runs card <run> {card_id} --json", run_id))["card"]
    assert strangers(f"rs7349332 {card['match']['genotype']}")
    assert strangers(f"WNT10A {card['confidence_tier']} hair curl")
    assert strangers("rs7349332 heterozygous hair curl")
    # And a limit, which the page states: a result told in words the evidence also prints
    # passes this check and the scanner. Only the rule stops it until M13.7. When one of
    # these starts failing, the page's sentence about them is the thing to correct.
    for told in ("rs7349332 one copy", "rs7349332 " + " ".join(card["match"]["genotype"])):
        assert not strangers(told) and not find_genotypes(told)
    assert "pass that check" in page()
    # And a result in the scanner's own shape is refused by the search commands.
    call = "=".join(("rs7349332", card["match"]["genotype"]))
    for words in (["cards", "search"], ["runs", "search", run_id]):
        refused = runner.invoke(app, [*words, call, "--json"])
        assert refused.exit_code == 2
        assert json.loads(refused.stdout)["error"]["kind"] == "genotype-in-query"
