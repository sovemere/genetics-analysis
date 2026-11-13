# M13.5 session diff review

Scope: `f3c8459..3472658`. That is M13.5's parity test: `genetics/testing/parity.py`, the
five record commands and their builders in `run/reads.py`, agent schema version 5,
`tests/test_parity.py`, the `parity_check` fixture and the nine existing tests that call it,
and the documentation. Every changed source line was re-read. The comparison was also
probed: every value of every card view was changed once, on the 103-card run and on the
runs with a placed polygenic score, HLA calls and cards, guideline cards, PGx calls and a
ClinVar lookup, which the committed tests did not do. The review opened no personal
genotype and no saved real run; every run it read is synthetic.

## Findings and fixes

- **P2: a figure changed to another figure in the same record passed.** The views held
  inside a card (variant, evidence, effect, frequencies, citations, carrier, confidence)
  and eleven fields of the polygenic view were compared by whether each string and number
  appeared anywhere in the part of the document the view came from. That is true of a
  wrong figure whenever the record holds the wrong figure somewhere else.
  - On the run with a placed polygenic score, 38 of 170 one-value changes to the polygenic
    view passed: weight coverage, weighted imputation quality, the before-imputation
    coverage, the portability counts, the reliability inputs and the licence flags. Those
    are the figures AGENTS.md §4.3 puts on every score's card.
  - On the same run a card's within-family attenuation could be changed and pass
    (AGENTS.md §4.5 puts it on the card face).
  - On the 103-card run, 8 of 126 changed confidence-row scores passed.
  - The 17 one-sided tests M13.5 shipped could not show it. Each changed a value to one
    chosen by hand (a gene to `ZZZ9`, a position plus one), which was nowhere in the record.
  - Each nested view is now compared field for field with the key it is read from
    (`parity.READ`), and a polygenic view's saved parts with those parts exactly
    (`parity.kept`). The containment comparison is removed.
- **P2: two values a card shows were declared display and never compared.** A polygenic
  card's `ancestry_matched` says whether the score was placed against a reference matched
  to the reader's ancestry (AGENTS.md §4.4). A confidence row's `observed` is the saved
  input the "Why this tier" table shows. The first is now compared with
  `computation.result.reference.ancestry_matched`. The six rows are compared one by one
  with the keys of `card.confidence.inputs` they show (`parity.CONFIDENCE_ROWS`), and a
  seventh row fails until it is placed. A row's label is still display.
- **P2: only the run page's shell was compared, and every other page's was assumed equal.**
  Each route builds its own `Shell`. The check compared the run page's, grouped by section
  and by tier, and a docstring said the shell "is the same on every page". Nothing checked
  that, and the HLA page's card list was held to that page's own unchecked shell. Every
  other page's shell must now equal the compared one in every field but `grid`, which
  holds the page's query. The app has one builder today, so no page was wrong.
- **P3: the check's own blind spots were silent.**
  - The call list followed `from genetics.x import f` and `import genetics.x as m`. A
    relative import or a bare `import genetics.x` was skipped, so an engine call made
    through one would not have been listed. Neither form is used in `genetics.web` or
    `genetics.cli`. Either now fails with the file and line.
  - `/` was rendered to see which run it opened, and the keys it hands its template were
    not held to the table. They are now, and its shell is compared when it opens this run.
  - Only the last template of a request was read. The two scanned partials are rendered
    first; a key handed to one of them and not to the page would not have been placed. It
    now fails.
  - A listed command was checked to exist and take `--json`. Its other options
    (`--section`, `--gene`) were not, so a renamed option left a stale table. Every option
    written in the table is now checked.
- **P3: the scan on `runs imputation` was tested on one branch.** The test's name said
  both. It put a genotype row into the JSON only, and moving the scan inside the JSON
  branch failed nothing. It now covers the text branch as well.
- **P3: wrong or stale statements.**
  - `check_run`'s docstring said nothing is written. A run that passes its deep checks is
    remembered outside the bundle, as on any read. The bundle is unchanged, which the
    guideline test asserts byte for byte.
  - The list of what the check cannot see left out methods. The call list follows imported
    functions, so a method called on an object the page holds is not seen. The engine
    classes the dashboard imports are enums, errors, `RunBundle` and the listing rows,
    none of which computes a result.
  - The parity section said a view that renames keys "is compared value by value with the
    part of the document it was built from". That was the containment comparison.
  - The README's command list had `runs clinvar` and `runs secondary` and not `runs
    imputation`, `pgx calls` or `hla calls`.
  - `docs/imputation_provenance.md` and `docs/secondary_findings.md` described the
    commands' JSON with no mention of the envelope and tag.
- **P4: one name.** `NESTED_DISPLAY` held a field that is compared, not display. It is
  `APART` now, and each entry says which it is.

## The probe, kept as a test

`parity.unnoticed` changes each string, number, flag and absent value a card view holds,
nested views and saved records included, adds an entry to each mapping and list, and
compares the changed view with the same document. Whatever still passes is a value the
dashboard could show wrongly without the check failing.

| Views changed | Changes | Passed before | Pass now |
|---|---|---|---|
| The 103 committed cards | 6,861 | 260 | 126 |
| The placed polygenic score's card | 273 | 1 | 0 |
| That card's polygenic view | 170 | 38 | 0 |

The 126 that pass are one per confidence row: its label, the dashboard's own name for an
input, listed in `parity.UNNOTICED` with that reason. Of the 260, another 126 were the
rows' `observed` and 8 were row scores. The committed probe also changes each card's id,
which makes 6,964 changes on the first run.

The `parity_check` fixture now runs the probe on every run a suite hands it and fails on
anything outside `parity.UNNOTICED`. That is how the within-family figure was found: the
first run of the fixture with the probe failed `tests/refs/test_pgs_cards.py`. The runs
with HLA calls and cards, guideline cards, PGx calls, the CYP2D6 limitation and the ClinVar
lookups pass it.

## Recorded rather than changed

- **Everything the call list counts as reached is any `genetics.cli` module's call**, not
  only a read command's. A function `genetics run` calls and the dashboard called live
  would pass that check. The value comparison is what covers it: the result would land in
  a context key or a view field, which has to be placed and equal what a command prints.
- **`hla calls` builds the linked cards inside the `try` that reports an HLA failure.**
  `cards_report` reads six saved fields and raises none of the caught errors.
- **A genotype found in `runs imputation` output raises, and is not an error document**,
  under `--json` too. `runs qc` behaves the same way.
- **`Report.cards` and `Report.drawn` count each card twice**, once per grouping of the run
  page. The tests say so where they assert on them.
- **The page size of 100 is written in the app and in the check.** A change to one fails
  the paging comparison.
- **The probe changes card views only.** The shell, the banner and the page contexts are
  compared by equality, which has no value to coincide with.
- **Nothing was run on the real imputed run.** Its first read after this change repeats
  its deep checks.

## Checks

- `tests/test_parity.py` holds 43 tests, nine more than M13.5 shipped: two import forms,
  the keys of `/`, a page whose shell differs (two cases), a partial handed its own key,
  the probe on the 103-card run, the probe's own enumeration, and the fixture failing a
  deliberately loose table. The tests of the containment comparison are replaced by tests
  of the field-for-field one. `tests/test_agent_schema.py` and
  `tests/refs/test_pgs_cards.py` each gained assertions in an existing test.
- Nineteen guards were each removed in turn and each removal failed a test: both import
  forms, the option check, the shell comparison on other pages and on `/`, the keys of
  `/`, the partial's keys, `ancestry_matched`, a confidence row's `observed`, its score
  and the row count, a nested view's value, a value shown with none saved, the number of
  entries in a list of views, a citation's link, the sentence that decided the tier, a
  polygenic view's saved parts, the fixture's probe, and the scan on the text branch.
  A clause first written into the `ancestry_matched` comparison could be removed without
  failing anything; it was dead, and was deleted instead of tested.
- The schema's shape is unchanged: version 5, digest as pinned. No command's output
  changed. The only production line this review changes is in `genetics.testing.parity`.
- The first full run after the fixes failed one test, one this review had added: it matched
  a field path in an assertion message that pytest shortens. The fixture now raises its
  own message with every path, and the test passes alone and in the suite.
- The full native suite passes **4,282 tests with the same nine skips** in 898 s, on
  Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools configured. After
  that run only documentation changed. Full dbSNP card lint (119 cards, 594 renders, 65/65
  keys), strict mypy on all four Windows/Linux x Python 3.11/3.13 targets (257 files),
  ruff, format and the fixture check pass.
