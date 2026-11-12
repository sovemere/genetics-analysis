# M13.3 session diff review

Scope: `96760e0..a8b80d1`. That is M13.3's card search: `genetics/engine/search.py`, the
search view in `run/reads.py`, the `cards search` and `runs search` commands, their text
renderers, `contract.search_query`, agent schema version 3, three test files and the
documentation. Every changed source line was re-read. The stemmer was also run over every
word the committed pack's cards hold, and each stem shared by two or more words was read.
The review opened no personal genotype and no saved real run; it used synthetic runs and the
committed pack.

## Findings and fixes

- **P2: a search for `note` listed 109 of the pack's 119 cards.** The stemmer's last rule
  took a final `e` or `y` off any word of four letters or more. On a four-letter word that
  leaves three letters, and several of those are whole words that are never stemmed
  themselves: `note` became `not`, `none` became `non`, `rate` became `rat`, `site` became
  `sit`. So `note` matched every card whose text says "not", at quality 0.75. The docstring
  already said short stems were refused; every other rule kept at least three or four
  letters and this one did not.
  - The rule now needs five letters. `note`, `none`, `rate` and `site` keep their own
    stems, and their plurals still join them. `curly`, `hairy`, `taste` and `smoke` are
    five letters and stem as before.
  - `cards search note` now lists 3 cards, `none` 8 (34 before) and `site` 10 (14 before).
    The committed module and the fixed one were run side by side on 28 other queries: every
    one returns the same cards in the same order. The pack holds no "rat", so `rate` was
    never a false match here; it is fixed by the same rule.
  - Two tests fail on the first version: one on the stems, and one that searches the pack
    for `note` and checks every hit holds a word starting with `note`.
- **P3: the side-by-side bonus left out the query's dropped words.** For
  `risk of heart disease` the searched terms are `risk`, `heart`, `disease`, and the bonus
  looked for those three side by side. Text saying "risk of heart disease" does not hold
  them side by side, so the text that says exactly what was asked earned nothing, and text
  reading "risk heart disease" would have. `Query` now keeps the words as typed, and the
  bonus compares those. A query with one searched term earns no bonus, whatever common words
  came with it. `age at menopause` now scores 12.5 on the menopause card, not 10.
- **P3: a query word that starts with a hyphen read as an option.** `-163C>A` is the name a
  card gives its marker. `genetics cards search -163C>A` fails with "No such option: -1".
  This is how the command line works, and `--` before the query is the answer; the search
  contract now says so and a test covers it. Inside a longer quoted query it needs nothing.
- **P3: wrong or stale statements.**
  - The README's status line still said "M0–M12, M13.1 and M13.2 are implemented", while a
    later paragraph of the same file said M13.3 was. The M13.1 and M13.2 reviews each found
    the same line stale.
  - `stem`'s docstring said identifiers "match exactly or not at all". They also match as a
    prefix, which a test in the same commit asserted.
  - The handoff's example of a stemming miss was `obese` and `obesity`. No card holds
    either word. The example is now `depressed` and `depression`, which the pack does hold.
  - The search contract described `query` as "the query as given". Runs of whitespace are
    collapsed, as the schema already said.
  - The schema's description of `score` left out the side-by-side bonus. Rewording a
    description does not take a version, and the digest test passes unchanged.
  - The search's validation paragraphs had been put at the top of M13.1's "Validation"
    section, so M13.1's own figures read as if they were the search's. They now sit under
    the search contract.

## Recorded rather than changed

- **The stemmer still joins a few unrelated words.** On the pack's own text: `even` and
  `evening`, `ever` and `every`, `german` and `germany`, `unit` and `united`, `mean` and
  `meaning`, `fast` and `fasting`. Each costs a match at quality 0.75 on a word the query
  did not mean. The search contract now lists them.
- **It has no rule for `-ion`, `-ic` or `-ive`.** `depressed` does not find `depression`.
  `depress` does, as a prefix. Matching a query's stem as a prefix would close most of
  these; it was not added in a review.
- **A hit does not say how each word matched.** `matched` names fields and words. The
  quality of each match and whether the bonus applied are not reported, so a score cannot
  be rebuilt from a hit. Adding them would be a shape change and version 4.
- **A query of only common words is searched as given.** `is` lists 111 cards. `ignored` is
  empty in that case, which is how a reader can tell.
- **`contract.search_query` catches the two query errors by class.** A third subclass of
  `QueryError` would reach the user as a traceback until it is given a kind there.
- **Outside the diff: a failed tool download can fail CI.** The first CI run on `a8b80d1`
  failed two of four jobs because the bref3 download returned HTTP 502. Re-running the two
  jobs passed with no change. On the Linux job the install step stopped the job. On the
  Windows job it did not: the step runs five installs and the last one succeeded, so the
  failure appeared eight minutes later as tests that could not find bref3. `ci.yml` was not
  changed in this review.

## Checked without change

- **The query cannot reach the output as a genotype.** `parse_query` refuses it before the
  pack or the run is read. What is echoed afterwards is the collapsed query, through
  `repr` in the text and JSON escaping in the payload; both only add characters the
  scanner's patterns do not start from. The pack test scans the JSON and text for every
  card's id, title, gene and rsIDs, and for each rsID followed by its alleles.
- **Saved record and current context in `runs.search`.** `results` holds eight keys of the
  saved card, compared key for key with `runs card` and with the schema's own definitions.
  Everything ranked or counted is under `current_context`.
- **Confidence and status do not rank.** `search_document` reads neither. The test that
  changes a card's status and tier compares the whole `current_context` before and after.
- **What a run search reads from a large card.** `search_document` looks up two keys under
  `computation.result` and walks nothing. A guideline card's saved result, the largest
  record in a run, is not traversed. This was read from the code, not timed on a real run.
- **Error kinds stay literals.** Both are written in `contract.search_query`, and the kind
  test finds them in the source.
- **Schema version 3.** The digest matches after the description change. Version 2's entry
  is untouched.

## Operational note

The review changed Python source, so the first read of each saved run after it repeats its
deep checks once (about 54 minutes for the real imputed run). Run `genetics runs list
--verify`, or the launcher's verify-first shortcut, first.

## Validation

Run on 2026-11-12, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **4,191 tests with the same nine skips** in 748 s:
the five Windows skips and the four published-classifier HIBAG tests. Nothing but
documentation changed between that run and the commit. The eight new tests are seven in
`tests/engine/test_search.py` (65 in all) and one in `tests/test_cli_search.py` (37).

Twenty-seven guards were each removed in turn and each removal failed a test: the 24 from
M13.3, and three for this review's fixes (the five-letter rule, the bonus reading the query
as typed, and one searched term earning no bonus). Full dbSNP card lint (119 cards, 594
renders, 65/65 keys), strict mypy on all four Windows/Linux x Python 3.11/3.13 targets (253
files), ruff, format and the fixture check pass.
