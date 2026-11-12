# M13.4 session diff review

Scope: `f7f9294..a3d9a47`. That is M13.4's machine-readable confidence: the shared ceiling
functions in `engine/confidence.py`, `run/explain.py`, the block on `runs card`, its text
renderer, the sentence on the dashboard's card page, agent schema version 4, five test files
and the documentation. Every changed source line was re-read. The replay was also run on
40,000 confidence results drawn with arbitrary decimals, which the committed tests did not
do. The review opened no personal genotype and no saved real run; it used synthetic cards
and the committed pack.

## Findings and fixes

- **P2: an honest saved score could be reported as saved under other rules.** The replay
  summed each row's `contribution`. Those are rounded to four places for display, and
  rounded rows do not add up: with four rows that carry decimals, the sum can sit 0.0002
  from the saved score, past the 0.00015 tolerance. The block then said `not_reproduced`
  and "the rules that set the saved tier are not this engine's", which was false.
  - Of 20,000 polygenic scores drawn with arbitrary coverage, quality and ancestry match,
    23 were reported that way. Of 20,000 single calls none was, and the largest difference
    was 0.0001; a single call has three such rows, so its sum reaches the tolerance less
    often.
  - The committed grids could not show it. Their inputs are round numbers (0.24, 0.59,
    0.79), so every row was exact. A real run's DR2, weight coverage and ancestry match
    are not round, and no real run was opened.
  - The replay now sums the saved components times their weights and rounds once. A
    polygenic replay is exact. A single call's can differ by one step in the fourth place,
    because its effect component is saved rounded, and the tolerance allows that step.
  - Two saved scores that failed are pinned as a test, and a second test replays 6,000
    results drawn with arbitrary decimals. Both fail on the first version.
- **P3: a rare call's rate was printed twice.** The sentence that says what decided a
  likely-artifact tier ends with the published benchmark ("about 16% confirmed and 84%
  unconfirmed by sequencing"). `runs card` text printed the same sentence again two lines
  below, from the saved benchmark, and the dashboard's card page did the same in the
  caution paragraph under the new sentence.
  - Both now state the rate once. The scope of the benchmark, the clinical notice and the
    dashboard's link to the paper are still printed.
  - A rare call whose tier is not explained (`not_reproduced`) has no rate in its sentence,
    so it keeps the rate where it was. A test covers each case in each front-end.
  - `current_context.confidence.reason` is unchanged: it still gives the rate, so an agent
    that reads only that sentence does not report a likely-artifact call without it
    (AGENTS.md §4.1).
- **P3: the membership rule was tested only on hand-built cards.** Whether a card takes an
  ancestry ceiling is read from its saved `ancestry_comparison` (M9.13). The schema test's
  saved run has no ancestry stage, so every card there has an unknown match, which is
  capped the same way under either rule. `tests/run/test_card_ancestry.py` saves a card
  through the real assembly with a known match; it now checks that the card replays and
  takes no ancestry ceiling, and that the same test's format 17 bundle replays too.
  Reading the rule as "HLA cards only" fails it.
- **P3: wrong or stale statements.**
  - The handoff said `reads.related` and `reads.card_payload` are called by both
    front-ends. The dashboard builds its pointers in `views.related_links` and its cards in
    `CardView.of`; a test compares the pointers. Only `reads.empty_reason` and
    `explain.explain_confidence` are shared today.
  - The handoff said the computed, polygenic and guideline partials "print the saved
    reason". The polygenic partial prints the saved score, inputs and ceiling names
    ("Capped by coverage"), not a reason.
  - The handoff said `engine/confidence.py` "had been left with CRLF line endings by an
    edit". The cause was not established. The file was CRLF in the working tree when six
    guard removals failed to match it, and LF in the index throughout.
  - The schema described `score` as "the sum of each scored input's `contribution`". It is
    the sum of weight times component; the rounded rows can differ from it. Rewording a
    description does not take a version, and the digest test passes unchanged.
  - The contract said the basis is `not_reproduced` when "the weights do not sum to the
    saved score". It now says what is summed.
  - A test's docstring said 4,200 single calls where the test asserts 16,800.
  - AGENTS.md §3's new sentence had been joined to the next one on a line of 180
    characters.
- **P4: two names for one function.** `score_tier` replaced `_score_tier`, and the old name
  was kept as an alias for two callers in the same module. They now call `score_tier`.

## Recorded rather than changed

- **A polygenic card's page and its `runs card` block name ceilings differently.** The page
  prints the saved names ("Capped by coverage"), which list only the ceilings that lowered
  the tier in order. The block lists every ceiling by input (`weight_coverage`) and names
  the ones at the tier. Both are right. M14.3 is the place to give the page the block.
- **The dashboard builds the explanation for every card it lists.** `CardView.of` calls
  `explain_confidence`, and a section page builds a view per card but prints the sentence
  only on a card's own page. It reads a dozen saved numbers per card, so this was left.
- **A null value prints as "not recorded".** In `runs card` text an `allele_frequency` row
  with no frequency reads "not recorded", though the run recorded that none was
  available. The ceiling line under it says so in words, and the JSON has the null.
- **The block is on `runs card` only**, as the M13.4 record says. A section read gives each
  card's saved tier and no reason.
- **Nothing was run on the real imputed run.** The rounding defect is the kind only real
  values show; the random replay stands in for one. `runs card` on a real run is still
  unchecked, and that run's first read repeats its deep checks.

## Checks

- The review's six new tests are three in `tests/run/test_explain.py` (two pinned scores and
  the random replay), two in `tests/test_cli_agent_reads.py` and one in
  `tests/web/test_dashboard.py`. `tests/run/test_card_ancestry.py` gained assertions in an
  existing test.
- Seven guards were each removed in turn and each removal failed a test: the replay from
  saved components (against the pinned scores and against the random replay), the rate
  printed once in the text, the rate kept when the reason lacks it, the same two on the
  card page, and the membership rule on a really assembled card.
- The schema's shape is unchanged: version 4, digest as pinned.
- The full native suite passes **4,235 tests with the same nine skips** in 907 s, on Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools configured. After that run only documentation and one module docstring changed. Full dbSNP card lint (119 cards, 594 renders, 65/65 keys), strict mypy on all four Windows/Linux x Python 3.11/3.13 targets (255 files), ruff, format and the fixture check pass.
