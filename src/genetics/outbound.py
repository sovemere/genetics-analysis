"""The outbound-query lint (roadmap M13.7, AGENTS.md 1.3).

An agent researching a card writes its own web searches; the engine builds none. What it
can do is check a query before the query leaves the machine. ``genetics cards check-query``
runs :func:`check_query`, ``cards search`` and ``runs search`` refuse what
:func:`reads_as_call` finds, and the fetcher passes every URL through :func:`check_url`.

**Why this is not** :mod:`genetics.privacy`. That scanner reads files, where a false alarm
gets a scanner bypassed, so it matches only the shapes a genotype row takes and favours
precision. A query is a line an agent can rewrite in a second, and what it gives away is
not a row but a result told in a few words: the marker with "one copy", the marker with
its two alleles written apart, a diplotype, "heterozygous", "my". This lint is built the
other way round. It favours recall, and every rule it refuses on says how to ask the same
question about the variant instead.

**Two kinds of rule.**

* ``call`` rules find a genotype written out: the privacy scanner's shapes, an rsID next
  to two alleles, a diplotype. A search over the pack refuses these too, because a call
  is never what a card is called.
* ``result`` rules find a result told in words: zygosity, a count of copies, the first
  person, a run id, a confidence tier. They are refused for a query that leaves the
  machine and allowed in a local search, where "carrier" or "homozygous" can be what a
  reader wants to find.

**Shapes and sources.** No list of shapes covers every result. A haplogroup, an HLA type
or a tier word has no shape of its own and is the reader's result only because the run
said so. :func:`check_query` therefore also takes the text of the ``cards evidence``
documents the query was written from, and lists each query word those documents do not
print as ``unsourced``. That is advice and not a refusal: a word read in a cited paper is
a fair word to search, and only the agent knows which paper it read. An unsourced word is
one the agent has to be able to name the paper for.

Nothing here returns or prints the query's text. A problem carries the rule and the
character span, as :class:`genetics.privacy.Hit` does.
"""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from genetics.privacy import GenotypeLeakError, assert_no_genotype, find_genotypes


class Rule(StrEnum):
    """Why a query was refused. The value is the name a ``--json`` reader sees."""

    GENOTYPE_SHAPE = "genotype-shape"
    MARKER_WITH_ALLELES = "marker-with-alleles"
    DIPLOTYPE = "diplotype"
    ZYGOSITY = "zygosity"
    ALLELE_COUNT = "allele-count"
    FIRST_PERSON = "first-person"
    RUN_ID = "run-id"
    CONFIDENCE_TIER = "confidence-tier"

    @property
    def kind(self) -> str:
        """``call`` for a genotype written out, ``result`` for a result told in words."""
        return "call" if self in CALL_RULES else "result"


CALL_RULES: Final[frozenset[Rule]] = frozenset(
    {Rule.GENOTYPE_SHAPE, Rule.MARKER_WITH_ALLELES, Rule.DIPLOTYPE}
)

ADVICE: Final[dict[Rule, str]] = {
    Rule.GENOTYPE_SHAPE: (
        "it holds a genotype in a shape the privacy scanner knows. Name the variant alone."
    ),
    Rule.MARKER_WITH_ALLELES: (
        "an rsID beside two alleles reads as the call at it. Name the variant alone, or "
        "write its alleles as a change (C>T)."
    ),
    Rule.DIPLOTYPE: (
        "two star alleles or HLA alleles joined by a slash read as a diplotype. Search each "
        "allele on its own."
    ),
    Rule.ZYGOSITY: (
        "a zygosity word says what the reader carries. Ask about the variant by genotype "
        "(penetrance by genotype), and find a paper by its DOI rather than its title."
    ),
    Rule.ALLELE_COUNT: (
        "a count of copies or of one allele says what the reader carries. Ask about the "
        "effect per allele, as the card states it."
    ),
    Rule.FIRST_PERSON: (
        "the first person says the query is about someone's own result. Write it as a "
        "question about the variant."
    ),
    Rule.RUN_ID: "it names a saved run. A run id never leaves the machine.",
    Rule.CONFIDENCE_TIER: (
        "a confidence tier is what the run earned, not what the literature says. Leave it out."
    ),
}
"""One sentence per rule, completing "Refused because ...". None quotes the query."""

_RSID: Final = r"(?:rs|i)\d+"
_BETWEEN: Final = r"(?:[\s,;:]+[\w'-]+){0,2}?"
"""Up to two words between an rsID and the alleles: ``rs1 genotype CT``, ``rs1 is C T``.
A comma, colon or semicolon may stand in for the space (found by the M13.7 review)."""

_SEP: Final = r"(?:\s*[/|;,]\s*|[ \t]+)"
_PAIR: Final = (
    r"(?:[ACGT]{2}|II|DD|ID|DI"  # merged, upper case
    r"|(?!at\b)[acgt]{2}"  # merged, lower case; "at" is a word
    rf"|[ACGT]{_SEP}[ACGT]|[ID]{_SEP}[ID]|[acgt]{_SEP}[acgt])"
)
"""Two alleles: merged, joined by a slash, pipe, semicolon or comma, or apart. A change
written with ``>`` is a variant and is not a pair. A nucleotide never pairs with an indel
code, so ``AD`` (Alzheimer's disease) and ``CD`` (coeliac disease) are not pairs."""

_PATTERNS: Final[tuple[tuple[Rule, re.Pattern[str]], ...]] = (
    (
        Rule.MARKER_WITH_ALLELES,
        re.compile(
            rf"\b{_RSID}\b{_BETWEEN}(?:[\s,;:]+|[\s,;:]*[(\[]\s*){_PAIR}\s*[)\]]?(?![\w>*])"
        ),
    ),
    (Rule.MARKER_WITH_ALLELES, re.compile(rf"(?<![\w>]){_PAIR}(?:[ \t]+at)?[\s,;:]+{_RSID}\b")),
    (
        Rule.MARKER_WITH_ALLELES,
        re.compile(r"\(\s*[ACGTIDacgtid]\s*;\s*[ACGTIDacgtid]\s*\)"),
    ),
    (
        Rule.DIPLOTYPE,
        re.compile(r"\*\d+[A-Za-z]?(?::\d+)*\s*[/|]\s*(?:[A-Z][\w-]*)?\*\d+"),
    ),
    (
        Rule.ZYGOSITY,
        re.compile(r"\b(?:hetero|homo|hemi)zyg(?:ous|otes?)\b", re.IGNORECASE),
    ),
    (
        Rule.ALLELE_COUNT,
        re.compile(
            r"\b(?:one|two|both|single|double|no|zero|a|an|1|2)[ \t]+"
            r"(?:(?:[ACGTacgt]|risk|effect|minor|major|alt|alternate|ref|reference|derived"
            r"|ancestral|mutant|variant)[ \t-]+)?cop(?:y|ies)\b(?![ \t-]*number)",
            re.IGNORECASE,
        ),
    ),
    (
        Rule.ALLELE_COUNT,
        re.compile(r"\b(?:one|two|both|no|zero|1|2)[ \t]+[ACGTacgt][ \t-]+alleles?\b"),
    ),
    (Rule.FIRST_PERSON, re.compile(r"\b(?:[Mm][Yy]|[Mm]ine|[Mm]yself|me)\b")),
    (
        Rule.FIRST_PERSON,
        re.compile(
            r"\b[Ii](?:'m|'ve|[ \t]+(?:am|have|carry|got|had))\b"
            r"|\b(?:[Aa]m|[Dd]o|[Dd]id|[Ss]hould|[Ww]ill|[Cc]ould|[Cc]an)[ \t]+[Ii]\b"
        ),
    ),
    (Rule.RUN_ID, re.compile(r"\b\d{8}T\d{6}Z-[0-9a-f]{8}\b")),
    (
        Rule.CONFIDENCE_TIER,
        re.compile(
            r"\blikely[- ]artifact\b"
            r"|\b(?:well[- ]established|strong|moderate|limited)[ \t]+(?:confidence|tier)\b"
            r"|\b(?:confidence|tier)[ \t]*[:=]?[ \t]*"
            r"(?:well[- ]established|strong|moderate|limited)\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class Problem:
    """One refused span: the rule and where, never the text."""

    rule: Rule
    start: int
    end: int

    @property
    def advice(self) -> str:
        return ADVICE[self.rule]


@dataclass(frozen=True)
class QueryCheck:
    """What :func:`check_query` found.

    ``unsourced`` is ``None`` when no evidence was given, and when the query was refused:
    the words of a refused query are not listed, since they may hold the call.
    """

    length: int
    problems: tuple[Problem, ...]
    unsourced: tuple[str, ...] | None

    @property
    def status(self) -> str:
        """``refused``, ``unsourced`` (words to account for) or ``clean``."""
        if self.problems:
            return "refused"
        return "unsourced" if self.unsourced else "clean"

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(dict.fromkeys(problem.rule for problem in self.problems))


_WORD: Final = re.compile(r"[^\W_]+")


def words(text: str) -> list[str]:
    """``text`` as lowercase words, split as card search splits them."""
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def problems(text: str, rules: Iterable[Rule] = tuple(Rule)) -> tuple[Problem, ...]:
    """Every span of ``text`` a rule in ``rules`` refuses, in order."""
    wanted = frozenset(rules)
    found: list[Problem] = []
    if Rule.GENOTYPE_SHAPE in wanted:
        found.extend(Problem(Rule.GENOTYPE_SHAPE, h.start, h.end) for h in find_genotypes(text))
    for rule, pattern in _PATTERNS:
        if rule in wanted:
            found.extend(Problem(rule, m.start(), m.end()) for m in pattern.finditer(text))
    return tuple(sorted(set(found), key=lambda p: (p.start, p.end, p.rule)))


def fold(text: str) -> str:
    """``text`` as the rules read it: NFKC, so full-width letters are letters, and each run
    of whitespace one space. Offsets in a :class:`QueryCheck` count in this."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def reads_as_call(text: str) -> bool:
    """True if ``text`` holds a genotype written out. A local search refuses this."""
    return bool(problems(fold(text), CALL_RULES))


def check_query(text: str, evidence: Iterable[str] = ()) -> QueryCheck:
    """Check a query before it leaves the machine.

    ``evidence`` is the text of the ``cards evidence`` documents the query was written
    from. Without it, only the rules run.
    """
    from genetics.engine.search import STOPWORDS

    text = fold(text)
    found = problems(text)
    sources = list(evidence)
    unsourced: tuple[str, ...] | None = None
    if sources and not found:
        # Card search's stopwords ("what", "is") tell nothing, and listing them made the
        # list noise the agent learns to skip (found by the M13.7 review).
        known = {word for source in sources for word in words(source)} | STOPWORDS
        unsourced = tuple(word for word in dict.fromkeys(words(text)) if word not in known)
    return QueryCheck(len(text), found, unsourced)


def check_url(url: str) -> None:
    """Raise :class:`genetics.privacy.GenotypeLeakError` if ``url`` holds a call.

    Every request the engine makes passes through here; ``tests/privacy/test_outbound.py``
    holds that. The URLs today are the manifest's own, so this is a second line: it is
    what stops a later change from writing a run's value into a query string.
    """
    decoded = urllib.parse.unquote_plus(url)
    for text in dict.fromkeys((url, decoded)):
        assert_no_genotype(text, context="an outbound request")
        if reads_as_call(text):
            raise GenotypeLeakError(
                "Refusing to send an outbound request that reads as a genotype call. "
                "Name the variant alone (AGENTS.md 1.3)."
            )
