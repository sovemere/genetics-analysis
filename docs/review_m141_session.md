# M14.1 session diff review

Scope: M14.1's working tree before its commit, on top of the M13.7 commit. That is
`reads.empty_reason`, `reads.empty_reasons` and `reads.pack_section_counts`, the status
labels moved into `reads`, `SectionView.empty_reason` as a field, `CardGroup.section_reason`,
`views.NO_RUN_REASON`, the parity tables, the grid template's sentence, and the tests. Every
changed source line was re-read and each sentence printed for synthetic cards. No personal
export and no saved real run was opened.

## Findings and fixes

- **P3: `runs show --section` computed all thirteen sentences for each section it
  printed.** `section_context` called `empty_reasons(bundle.cards)` and took one entry.
  It now calls `empty_reason` on the section's own cards; `empty_reasons` and
  `section_context` share `_pack_count`.

Three guards were removed in turn, and each removal failed a test: the check that drops a
quoted reason reading as a call (one test), the grid's section sentence (fourteen, in the
empty-state and parity suites), and the assay-limit sentence (one).

## Re-read and unchanged

- **"The knowledge pack it was saved with had none here" is a claim the run supports.**
  Every card in a pack yields a card in the run (AGENTS.md §0.1A: nothing is filtered), so
  a run with none in a section was saved with a pack that held none there, whether that
  was an older committed pack or a `--knowledge` directory.
- **Only `not_run` reasons are quoted.** The engine writes them about a module (a
  reference not fetched, a licence not accepted, a tool absent). A failed match's reason
  can name the call and stays on the card. The quoted text is also checked with
  `outbound.reads_as_call`, since an empty state sits beside the scanned half of the page.
- **The pack's per-section counts are cached for the process.** Loading the pack takes
  about 0.7 s here. A dashboard left running sees a pack change on restart; the pack is
  source, not data.
- **With no run open every section says `NO_RUN_REASON`**, where it used to say "Not
  built yet", which was true of no section by then.

## Validation

The empty-state, view, dashboard, CLI-read, parity and walk-through suites pass (344
tests), and strict mypy (`--platform win32`, `src` and `tests`), ruff and format pass. The
full native suite passes **4,378 tests with nine skips** in 746 s.
