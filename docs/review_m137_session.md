# M13.7 session diff review

Scope: M13.7's working tree before its commit, on top of `9a1672a`. That is the new
`genetics.outbound` module, `genetics cards check-query`, the change to
`engine.search.parse_query`, `check_url` in the fetcher, agent schema version 6, the tests
in `tests/privacy/test_outbound.py`, and the documentation. Every changed source line was
re-read, and the lint was probed with invented queries and with every card title, gene and
citation title in the committed pack. No personal export and no saved real run was opened.

## Findings and fixes

- **P2: full-width characters carried a call past every rule.** An input method that types
  full-width Latin letters produces an rsID and a pair the patterns do not read as letters.
  `check_query` and `reads_as_call` now apply NFKC before any rule runs (`outbound.fold`),
  and the problems' offsets count in the folded text. The schema's description of
  `length` says so.
- **P2: a comma, colon or semicolon between the rsID and the pair carried a call past
  `marker-with-alleles`.** The pattern wanted whitespace there. It now takes any of those
  punctuation marks or whitespace, before the pair and between the words that may sit
  between it and the rsID, and the reverse order (pair first) likewise. A thin space was
  already folded.
- **P3: `unsourced` listed question words.** "What is the effect of rs…" listed "what"
  and "is", because the evidence document does not print them. A list an agent learns to
  skip is a list it skips when it matters. Card search's stopwords are no longer listed.
- **P3: the zygosity advice did not cover the case it gets wrong.** One citation title in
  the pack holds "Homozygous" (FUT2), so searching that paper by its title is refused.
  The lint is recall-first and this is the intended trade, but the advice now says to find
  a paper by its DOI, which `cards evidence` prints, and to ask about a variant "by
  genotype" rather than about one zygosity.

Each fix has a test. Three guards were then removed in turn, and each removal failed a
test: `check_url` in the fetcher's `open` (four tests), the NFKC fold (one), and
`marker-with-alleles` from the call rules (twelve, across the search and lint suites).

## Re-read and unchanged

- **The search commands refuse more than before.** `rs… A C`, written as a variant's two
  alleles, was searched before and is refused now. `tests/engine/test_search.py` had used
  that form to check that no search result holds a genotype; it now uses `A>C`, and
  asserts the spaced form is refused. A reader searching a variant by its alleles is told
  to write a change. Recorded as the cost of the rule, not a defect.
- **`check-query` exits 1 on `refused` with its own document**, not the error document.
  The schema's `error` contract ("a failing command prints this") is unaffected: the
  command did not fail. `docs/agent_schema.md` says this in two places.
- **No query text is printed.** The text form names the rule and the character span; the
  JSON form adds the kind and advice. A refused query's words are not listed as
  unsourced, and both outputs are scanned before printing.
- **The source reader is not a general network audit.** It looks for `urlopen`,
  `Request`, `HTTPConnection`, `HTTPSConnection`, `create_connection` and
  `socket.socket`. `requests`, `httpx` and `aiohttp` are not dependencies; a change that
  added one would pass this test, and the M2.7 in-process guard would still refuse it in
  the suite.
- **No card title, gene or id is refused**, and of the pack's citation titles only the
  FUT2 one above.

## Recorded, not changed

- No rule list is complete. AGENTS.md §1.3 now says the check is a floor, and the
  walk-through repeats it.
- The source check is advice: only the agent knows which papers it read.
- The hosted-agent reading of §1.3 that M13.6 recorded is still unconfirmed by the owner.

## Validation

Before the review, the full native suite passed **4,358 tests with nine skips** in 778 s
(the five Windows skips and the four published-classifier HIBAG tests). After the fixes,
the 211 tests in the lint, search, walk-through and schema suites pass, and the full suite
was run again before the commit: **4,365 tests with nine skips** in 752 s. Strict mypy
(`--platform win32` over `src` and `tests`), ruff and format pass.
