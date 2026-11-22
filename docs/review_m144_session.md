# M14.4 session diff review

Scope: M14.4's working tree before its commit, on top of the M14.3 review commit. That is
the `/runs/{run_id}/search` route and `_open` in `web.app`, `search.html`, the search box in
`_sectionnav.html`, the stylesheet rules, the parity rows (`PAGES`, `CONTEXT`, the visits
in `check_run`, `Documents.search` and `Documents.refusal`) and the tests. Every changed
source line was re-read, and the page was opened in a browser, in dark mode, on a synthetic
run built from the committed pack against an invented table. No personal export and no
saved real run was opened.

## Findings and fixes

- **P3, found in the browser: the matched line overflowed its grid cell.** A card face
  fills its cell (`.card { height: 100% }`), so the "Matched 2 of 2 word(s) in ..." line
  under it spilled onto the next panel's heading. Each hit's cell is now a column that the
  face and the line share (`.searchhit`). A test pins the class on every hit and the rule.
- **P3, found by the suite: a dashboard test took the first `<form>` on the page** to be the
  grid's controls. The nav's search form now comes first. The test finds the controls form
  by its class; the controls are unchanged.

## Re-read and unchanged

- **The query is never handed to the template.** The route passes the template the search
  document (built only after `parse_query` accepted the text), the run's card views for its
  results, and, for a refused query, `str(exc)` alone. The genotype and empty-query
  messages name the rule and never the text; the parity check compares the page's sentence
  with the error document `runs search` prints and fails if the refused query's rsID is on
  the page.
- **One bundle per page.** `_open` returns the bundle the shell was built from, so
  `search_view` reads the same copy whose cards the page shows. A second `opened.load` could
  have read a changed bundle between the two calls.
- **No limit.** The page lists every hit, as the grid lists every card; the parity check
  compares with `runs search` without `--limit`, so a page that cut the list fails it.
- **A blank box is not an error.** Whitespace alone shows the prompt; the command refuses
  it as `empty-query`. Submitting an empty box is not a malformed query. Punctuation alone
  gets the `empty-query` sentence on both.
- **The query is in the address.** The form is a plain GET, like the grid's controls, so it
  works without JavaScript and comes back with the back button. `Referrer-Policy:
  no-referrer` keeps the address out of any request a citation link causes, and a refused
  query is in the address only because the reader typed it there.

## Guards removed in turn

Each was removed and the search-page tests, or the parity check, run again. All nine
failed a test:

| Removed | Caught by |
|---|---|
| The refusal kept the query (`f"{exc} {q}"`) | `test_a_query_that_reads_as_a_genotype_is_refused_and_not_shown_again`, and parity |
| Results in another order | `test_the_page_lists_what_runs_search_lists_in_its_order` |
| The grid's tier filter narrowed the results | `test_the_grid_s_filters_ride_along_and_do_not_narrow_the_search` |
| Every hit counted as a full match | `test_partial_matches_are_listed_below_full_ones_under_their_own_heading` |
| The refusal sentence not shown | `test_the_refusal_is_the_engine_s_own_sentence` |
| No box in the nav | `test_every_page_of_an_open_run_has_the_box_in_its_nav` |
| The grid's arrangement dropped from the form | `test_the_grid_s_filters_ride_along_and_do_not_narrow_the_search` |
| A limit of two on the page | parity: "differs from what `runs search` prints" |
| The refusal reworded on the page | parity: "refuses a query in other words" |

## Second pass, after the commit

A diff-driven pass over `e42f268`, re-reading each changed line against the code it calls
and each documentation sentence against the code it describes.

- **P3, stale documentation:** the `engine/search.py` docstring and the roadmap's M13.3
  summary still said the dashboard's search "must call" the ranking function. Both now
  say it does. `agent_cli.md`'s list of what the parity check treats as display lacked the
  refusal sentence and how `check_run` compares it; added.
- **Re-read and unchanged:** every saved card has a `CardView` (`views.card_views` maps
  `bundle.cards` one to one), so the route's `LookupError` is unreachable as its comment
  says; a run that fails to open never reaches `search_view`, since `_open` returns no
  bundle; a parity run with no cards visits only the fixed searches.
- **Handed to M14.7, not changed:** the search page carries two `role="search"` forms with
  the same label, and the `empty-query` sentence keeps the CLI's backticks. Both are in
  the M14.5 hand-over in [the handoff](handoff_history.md#next-open-step-m145-qc-provenance-page).

## Validation

The full native suite passes 4,426 tests with the existing nine skips in 962 s. The
overflow fix and its test landed during that run; the web, parity and walk-through suites
pass on the final tree (326 tests). Strict mypy on Windows and Linux under Python 3.11 and
3.13, ruff and format pass.
