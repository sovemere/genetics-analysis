# M14.3 session diff review

Scope: M14.3's working tree before its commit, on top of the M14.2 handoff commit. That is
`genetics.run.guide`, the threshold tables in `engine/confidence.py`, `engine.ppv.benchmark`,
`genetics cards guide`, the `/guide` route and template, the nav legend, the links from the
grid's tier headings and the card page, agent schema version 8, the parity rows and the
tests. Every changed source line was re-read, and the guide and the nav legend were opened
in a browser, in dark mode, against an empty data directory. No personal export and no
saved real run was opened.

## Findings and fixes

- **P2, found while reading the output: the ancestry ceilings were overstated for
  membership cards.** The first draft said every single call takes the 0.25 and 0.50
  ancestry ceilings. A card compared with its study population by membership (a saved
  ancestry comparison, and every HLA card) takes none once the match is known; the match
  enters the score. Checked against `single_call_ceilings` with `variant_ancestry=True`, and
  the confidence section now says so.
- **P3: the Tandy-Connor sentence read as 40% of patients.** The abstract reports 40% of
  the variants in 49 patients' raw data. Reworded.
- **P3: a guide test was vacuous.** "The guide opens no run" patched `store.load_run` on an
  empty runs directory, where nothing could be opened anyway. Removed; the parity check
  opens `/guide` beside a saved run and fails if its shell selects one.
- **P3: the run selector looked as though the newest run were open** on a page with no run
  selected, and choosing that run fired no change. It now offers "Open a saved run" first.

## Re-read and unchanged

- **No tier changed.** The frequency, quality and share bounds moved into tables that the
  calculators loop over; the M13.4 comparison of 22,848 results with a copy of the earlier
  rules passes.
- **The figures quoted** were read from the PubMed abstracts of Weedon 2021, Tandy-Connor
  2018, Okbay 2022 and Ding 2023 on 2026-11-19. Each search sent only the paper's DOI, and
  the two free-text queries passed `genetics cards check-query`.
- **The legend is not on the card faces**: a face is one link, to the card, and a link
  inside a link is not valid HTML. It is in the nav of every page instead.
- **The card page keeps M13.4's sentence and six rows.** The weights and the ceiling list
  are on the guide, and `runs card --json` holds each card's own.

## Validation

Seven guards were removed in turn, and each removal failed a test: two ceiling probes (the
missing-frequency and coverage rules), the weakest-first order of the ceilings, the badges
sharing the guide's labels, the guide's tier anchors, the nav legend's links, and the
parity placement of `legend`.

The full native suite passes **4,412 tests with nine skips** in 977 s (25 new). Strict
mypy (`--platform win32`, `src` and `tests`), ruff and format pass.
