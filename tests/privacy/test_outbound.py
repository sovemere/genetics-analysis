"""The outbound-query lint (roadmap M13.7, AGENTS.md 1.3).

Three things are held here. The lint refuses each way a result can be written into a query
and lets through the questions about a variant that docs/agent_usage.md shows. Every
request the engine makes passes through :func:`genetics.outbound.check_url`, found by
reading the source, so a new network call cannot skip it. And ``genetics cards
check-query`` reports the lint's answer without repeating the query.

Queries that hold a call are assembled from parts, as the M13.6 tests do, so this file is
not itself a list of genotype strings. Every value is invented.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from genetics import outbound
from genetics.cli.main import app
from genetics.outbound import Rule, check_query, check_url, problems, reads_as_call
from genetics.privacy import GenotypeLeakError, find_genotypes
from genetics.refs.fetcher import UrllibTransport

pytestmark = pytest.mark.privacy

runner = CliRunner()
ROOT = Path(__file__).parents[2]
SRC = ROOT / "src" / "genetics"

RS = "rs7349332"
"""The worked example's marker (docs/agent_usage.md). Any rsID would do."""

REFUSED: list[tuple[str, Rule]] = [
    (f"{RS} one copy", Rule.ALLELE_COUNT),
    (f"{RS} " + " ".join("CT"), Rule.MARKER_WITH_ALLELES),
    (f"{RS} " + "CT", Rule.MARKER_WITH_ALLELES),
    (f"{RS} " + "ct" + " hair", Rule.MARKER_WITH_ALLELES),
    (f"{RS} " + "/".join("CT"), Rule.MARKER_WITH_ALLELES),
    (f"{RS}(" + ";".join("CT") + ")", Rule.MARKER_WITH_ALLELES),
    (f"{RS} genotype " + "CT", Rule.MARKER_WITH_ALLELES),
    ("CT" + f" at {RS}", Rule.MARKER_WITH_ALLELES),
    ("rs1 " + " ".join("ID"), Rule.MARKER_WITH_ALLELES),
    ("CYP2C19 " + "/".join(("*1", "*17")), Rule.DIPLOTYPE),
    ("HLA-B" + "/".join(("*57:01", "B*44:02")), Rule.DIPLOTYPE),
    ("WNT10A heterozygous hair", Rule.ZYGOSITY),
    ("APOE homozygote risk", Rule.ZYGOSITY),
    ("two copies APOE4", Rule.ALLELE_COUNT),
    (f"one T allele {RS}", Rule.ALLELE_COUNT),
    (f"what does my {RS} mean", Rule.FIRST_PERSON),
    ("do I have curly hair genes", Rule.FIRST_PERSON),
    ("I'm a carrier of HFE", Rule.FIRST_PERSON),
    ("20261105T045104Z-" + "e285851e", Rule.RUN_ID),
    (f"{RS} likely artifact", Rule.CONFIDENCE_TIER),
    ("WNT10A moderate confidence", Rule.CONFIDENCE_TIER),
    ("=".join((RS, "CT")), Rule.GENOTYPE_SHAPE),
]
"""Each query, and one rule that has to refuse it."""

CLEAN: list[str] = [
    f"{RS} WNT10A hair curl",
    "10.1371/journal.pgen.1000993",
    "WNT10A hair shape meta-analysis",
    "WNT10A intronic marker hair shape",
    f"{RS} " + ">".join("CT"),
    f"{RS} T allele",
    f"{RS} at WNT10A",
    "rs429358 APOE AD risk",
    "celiac HLA-DQ2 CD",
    "SMN1 a copy number variant",
    "HLA-B*57:01 abacavir",
    "CYP2C19 *2 loss of function",
    "runs of homozygosity autozygosity",
    "ME/CFS genetics",
    "type I diabetes HLA",
    "rs1801133 MTHFR C677T",
    "carrier frequency CFTR",
    "well-established association lactase persistence",
    "effect per allele copy",
]
"""Questions about a variant, including words that sit close to a rule."""


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("query", "rule"), REFUSED)
def test_each_way_of_telling_a_result_is_refused(query: str, rule: Rule) -> None:
    check = check_query(query)
    assert check.status == "refused"
    assert rule in check.rules
    assert check.unsourced is None


@pytest.mark.parametrize("query", CLEAN)
def test_a_question_about_the_variant_is_not(query: str) -> None:
    assert check_query(query).problems == ()


def test_the_two_queries_m13_6_left_open_are_refused() -> None:
    """docs/agent_usage.md says these passed every check; M13.7 closes both."""
    for query in (f"{RS} one copy", f"{RS} " + " ".join("CT")):
        assert find_genotypes(query) == [], "the privacy scanner was never going to see it"
        assert check_query(query).status == "refused"


def test_a_problem_says_where_and_why_and_never_what() -> None:
    query = "do I have " + f"{RS} " + "CT"
    found = problems(query)
    assert {problem.rule for problem in found} == {Rule.FIRST_PERSON, Rule.MARKER_WITH_ALLELES}
    for problem in found:
        assert 0 <= problem.start < problem.end <= len(query)
        assert query[problem.start : problem.end] not in problem.advice
        assert "CT" not in problem.advice and RS not in problem.advice
    assert set(outbound.ADVICE) == set(Rule)


def test_only_a_call_is_refused_by_a_local_search() -> None:
    assert {rule.kind for rule in outbound.CALL_RULES} == {"call"}
    assert {rule.kind for rule in set(Rule) - outbound.CALL_RULES} == {"result"}
    for query, rule in REFUSED:
        assert reads_as_call(query) is (rule in outbound.CALL_RULES), query


def test_words_the_evidence_does_not_print_are_listed() -> None:
    evidence = [f"variant {RS} WNT10A; hair-curl scale"]
    assert check_query(f"{RS} WNT10A hair curl", evidence).status == "clean"
    unsourced = check_query(f"{RS} WNT10A hair curl dysplasia", evidence)
    assert unsourced.status == "unsourced"
    assert unsourced.unsourced == ("dysplasia",)
    # Without evidence nothing is listed, and a refused query's words never are.
    assert check_query("WNT10A dysplasia").unsourced is None
    assert check_query(f"{RS} one copy dysplasia", evidence).unsourced is None


@pytest.mark.parametrize(
    "query",
    [
        "\uff52\uff53" + "7349332 " + "\uff23\uff34",  # full-width, as an IME types it
        f"{RS}, " + "CT",
        f"{RS}; " + " ".join("CT"),
        "CT" + f", {RS}",
        f"{RS}\u2009" + "CT",
    ],
)
def test_the_m13_7_review_s_bypasses_are_refused(query: str) -> None:
    """Width, punctuation and odd spaces carried a call past the first version."""
    assert check_query(query).status == "refused"
    assert reads_as_call(query)


def test_a_question_word_is_not_listed_as_unsourced() -> None:
    check = check_query(f"what is the effect of {RS}", [f"variant {RS}"])
    assert check.status == "unsourced"
    assert check.unsourced == ("effect",)


def test_a_cited_title_with_a_zygosity_word_is_refused_and_the_advice_says_why() -> None:
    """A recall-first lint refuses the pack's own words too; the DOI is the way round."""
    found = check_query("A Homozygous Nonsense Mutation in the Human Secretor Gene").problems
    assert [problem.rule for problem in found] == [Rule.ZYGOSITY]
    assert "DOI" in found[0].advice


def test_whitespace_is_folded_before_the_offsets_are_counted() -> None:
    check = check_query("  do   I    have  ")
    assert check.length == len("do I have")
    assert check.problems[0].end <= check.length


# ---------------------------------------------------------------------------
# Every request the engine makes is checked
# ---------------------------------------------------------------------------

_NETWORK_CALLS = frozenset(
    {"urlopen", "Request", "HTTPConnection", "HTTPSConnection", "create_connection"}
)
"""Names that open or build an outbound request. ``socket.socket`` is listed apart below."""


def _requests(tree: ast.AST) -> list[tuple[ast.AST | None, ast.Call]]:
    """Each call that builds or opens a request, with the function it sits in."""
    found: list[tuple[ast.AST | None, ast.Call]] = []

    def visit(node: ast.AST, function: ast.AST | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else None
            if isinstance(child, ast.Call):
                name = child.func.attr if isinstance(child.func, ast.Attribute) else None
                if isinstance(child.func, ast.Name):
                    name = child.func.id
                is_socket = (
                    isinstance(child.func, ast.Attribute)
                    and child.func.attr == "socket"
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "socket"
                )
                if name in _NETWORK_CALLS or is_socket:
                    found.append((function, child))
            visit(child, inner or function)

    visit(tree, None)
    return found


def _checks_first(function: ast.AST | None, call: ast.Call) -> bool:
    if function is None:
        return False
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "check_url"
        and node.lineno < call.lineno
        for node in ast.walk(function)
    )


LISTENING: dict[str, int] = {"cli/serve_cmd.py": 1}
"""Sockets that listen and send nothing out: the dashboard binds its own, on loopback
(M4.3). A file here is counted, so a second socket in it fails the test below."""


def test_every_request_the_engine_builds_passes_through_check_url() -> None:
    sites: dict[str, int] = {}
    unchecked: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative.startswith("testing/"):
            continue  # the network guard itself, which refuses rather than requests
        for function, call in _requests(ast.parse(path.read_text(encoding="utf-8"))):
            sites[relative] = sites.get(relative, 0) + 1
            if relative not in LISTENING and not _checks_first(function, call):
                unchecked.append(f"{relative}:{call.lineno}")
    # The fetcher is the only network path today: two requests and two opens.
    assert sites == {"refs/fetcher.py": 4, **LISTENING}, sites
    assert not unchecked, (
        f"an outbound request is built without genetics.outbound.check_url: {unchecked}"
    )


def test_the_source_reader_finds_an_unchecked_request() -> None:
    """Without this, a reader that found nothing would pass the test above."""
    tree = ast.parse(
        "import urllib.request\n"
        "def get(url):\n"
        "    return urllib.request.urlopen(url)\n"
        "def safe(url):\n"
        "    check_url(url)\n"
        "    return urllib.request.urlopen(url)\n"
        "def raw():\n"
        "    import socket\n"
        "    return socket.socket()\n"
    )
    found = _requests(tree)
    assert len(found) == 3
    assert [_checks_first(function, call) for function, call in found] == [False, True, False]


def test_every_url_the_manifests_declare_passes() -> None:
    urls: list[str] = []

    def collect(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)
        elif isinstance(node, str) and node.startswith(("http://", "https://")):
            urls.append(node)

    for manifest in (ROOT / "data" / "references" / "manifest.yaml", ROOT / "data" / "tools.yaml"):
        collect(yaml.safe_load(manifest.read_text(encoding="utf-8")))
    assert len(urls) > 100
    for url in urls:
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/search?q=" + "=".join((RS, "CT")),
        f"https://example.org/search?q={RS}+" + "CT",
        f"https://example.org/search?q={RS}%20" + "%20".join("CT"),
    ],
)
def test_a_url_holding_a_call_is_refused_before_a_socket_opens(url: str) -> None:
    # The suite blocks the network, so reaching urlopen would raise NetworkAccessError.
    with pytest.raises(GenotypeLeakError) as caught:
        UrllibTransport().open(url)
    assert RS not in str(caught.value)


# ---------------------------------------------------------------------------
# genetics cards check-query
# ---------------------------------------------------------------------------


def _check(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["cards", "check-query", *args])
    return result.exit_code, result.stdout


def test_the_command_refuses_without_repeating_the_query(
    agent_schema_check: Callable[[object], str],
) -> None:
    query = f"{RS} " + " ".join("CT")
    code, out = _check(*query.split(), "--json")
    assert code == 1
    document = json.loads(out)
    assert agent_schema_check(document) == "cards.check-query"
    assert document["status"] == "refused"
    assert [p["rule"] for p in document["problems"]] == ["marker-with-alleles"]
    assert document["problems"][0]["kind"] == "call"
    assert document["unsourced"] is None
    assert RS not in out and query not in out
    code, text = _check(*query.split())
    assert code == 1
    assert text.startswith("refused:") and RS not in text


def test_the_command_lists_unsourced_words_against_the_cards_evidence(
    agent_schema_check: Callable[[object], str],
) -> None:
    code, out = _check(RS, "WNT10A", "hair", "curl", "--card", "wnt10a_hair_curl", "--json")
    assert code == 0
    document = json.loads(out)
    agent_schema_check(document)
    assert document["status"] == "clean"
    assert document["cards"] == ["wnt10a_hair_curl"]
    assert document["unsourced"] == []

    code, out = _check("WNT10A", "dysplasia", "--card", "wnt10a_hair_curl", "--json")
    assert code == 0
    assert json.loads(out)["status"] == "unsourced"
    assert json.loads(out)["unsourced"] == ["dysplasia"]

    code, out = _check("WNT10A", "dysplasia", "--card", "wnt10a_hair_curl")
    assert code == 0 and out.startswith("unsourced:") and "dysplasia" in out

    code, out = _check("WNT10A", "--json")
    assert code == 0
    assert json.loads(out)["unsourced"] is None


def test_the_command_reports_a_card_it_cannot_find_and_an_empty_query() -> None:
    code, out = _check("WNT10A", "--card", "curly_hair", "--json")
    assert code == 1
    assert json.loads(out)["error"]["kind"] == "card-not-found"
    code, out = _check("?!", "--json")
    assert code == 2
    assert json.loads(out)["error"]["kind"] == "empty-query"
