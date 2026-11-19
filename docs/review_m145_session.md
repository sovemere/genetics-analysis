# M14.5 session diff review

Scope: M14.5's working tree before its commit, on top of the M14.4 second-review commit.
That is the `/runs/{run_id}/qc` route and `_render(..., scanned=True)` in `web.app`, the
`dig` template global, `qc.html`, the nav link, the stylesheet rules,
`reads.coverage_report` and `score_coverage`, `runs qc`'s `current_context` and text form,
agent schema 9, the parity rows (`PAGES`, `CONTEXT["qc.html"]`, `_whole`, the visit in
`check_run`) and the tests. Every changed source line was re-read, and the page was opened
in a browser, in dark mode, on a synthetic run built from the committed pack against an
invented table, with the committed reference lock as its provenance. No personal export and
no saved real run was opened.

## Findings and fixes

- **P2, found while testing: a ClinVar lookup that did not run was called "saved before
  format 13".** The low-level bundle writer saves `ClinVarLookup.not_run(...)` with no
  coverage, so the first cut's three states put it under "not recorded", a statement about
  the run's age that was false. `clinvar_status` now has a fourth value, `lookup-not-run`,
  with the lookup's own reason in `clinvar_reason`; the page and the text form say it in
  those words. Removing the branch fails three tests.
- **P3, found in the browser: the "No tier" badge wrapped onto two lines** in the coverage
  table's narrow tier column, and a not-placed score's reason inherited the row header's
  bold. The tier cell no longer wraps and the reason is set in normal weight.
- **P3, found in the browser: a stray `-`** followed the title of a score that was never
  computed, standing for its absent PGS ID. The ID is now shown only when the result has one.

## Re-read and unchanged

- **Nothing is recounted.** Every figure on the coverage table is a key of the card's saved
  `computation.result` or of the saved ClinVar coverage record; `coverage_report` adds only
  three counts over the list it returns.
- **No card is left out for its tier or status.** `coverage_report` takes every card of kind
  `polygenic` in saved order. Restricting it to computed cards fails two tests.
- **Position-level imputation decisions stay off the page.** The template reads the stage's
  `regions` (outcome counts) and each job's `region`, `impute.contract.options` and elapsed
  times; it never iterates `decisions`. The target fingerprint is not shown; a test checks it.
- **The page holds what it is handed, whole.** `_whole` compares each document with its
  command's, every key; a test drops one key from the page's copy only and the check fails
  for each command.

Five guards were removed in turn and each failed a test: the page scan (one), the QC page
visit in `check_run` (one), the polygenic filter (two), the `_whole` comparison (two), and
the `lookup-not-run` branch (three).

## Validation

The full native suite on 2026-11-20 passed **4,435 tests with nine skips** in 1,024 s and
failed one: `test_agent_usage.py` pins the number of keys its walk-through names for `runs
qc`, and the page gained a row for `current_context.coverage`. The pin and an assertion on
the example run's ClinVar state were updated, and that file passes (14 tests). Three parity
tests were added after the run, and the parity, web, walk-through, schema, imputation
snapshot and PGS card suites pass on the final tree. Strict mypy on `src` and `tests`, ruff
and format pass. Python source changed, so saved runs repeat their deep checks once.

Not done: the page has not been opened on the real imputed run, whose provenance holds
about 25 regions; the synthetic stages hold one.
