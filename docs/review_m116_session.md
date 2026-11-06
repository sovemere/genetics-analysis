# M11.6 session diff review

Scope: `64dc863..99f4998`, M11.6's carrier-screening scope: knowledge schema 8's
`screening_scope` declaration, `genetics.engine.carrier_scope`, bundle format 27, the
`genetics cards carrier-scope` command, `runs show`, the dashboard notice and detail view, the
reference list, tests and documentation. The review used synthetic inputs and the fetched public
references (dbSNP b157, ClinVar 2026-08-04, gnomAD r2.1.1 exomes), and opened no personal
genotype. A multi-angle review of the diff supplied findings alongside a direct read.

No saved run on this machine holds format 27, so the record changed in place. Knowledge schema 8,
the record's schema 1 and bundle format 27 keep their numbers.

## Findings and fixes

- **P1 — Redirected CLI output crashed on Windows.** `scope.yaml` is the only knowledge file with
  characters outside cp1252 (β, α, ≥). Saved in every format-27 run, they made `genetics runs show
  <run> --json > file` raise `UnicodeEncodeError`, as did `genetics cards carrier-scope > file`.
  That is the agent interface on the primary platform. `CliRunner` substitutes a UTF-8 stream, so
  no test, CI job or `ci-local` run could see it. Reproduced first, in real subprocesses with
  `PYTHONIOENCODING=cp1252`; the CLI now switches a non-UTF-8 stdout to UTF-8 at its entry point.
- **P2 — An imputed result read as an array call, and a caveat was false for it.** Imputation is
  on by default and can fill a no-call. The face said such a marker "gave a result" among typed
  markers, and the strand caveat said a homozygote at an A/T or C/G marker is never determined,
  though an imputed one is reference-oriented and is. The tally now counts `imputed_results`, the
  face says how many were not read from the array, the caveat is limited to direct calls, and a
  further caveat says imputation does not make a rare call reliable (AGENTS.md §4.1). The bundle
  re-derives the count from each card's saved call source.
- **P3 — The "gap in this report" wording rested on a per-site check.** At a multiallelic site,
  another alternate's ClinVar or gnomAD record could satisfy it. Rows in the two typed classes now
  declare their forward-strand `allele`, and the native test binds to it. All 24 pass.
- **P3 — A second scope card passed load and failed at save.** That would lose an imputed run of
  about eight hours at its last step. `KnowledgePack.load` now refuses it.
- **P4 — Hardening and tidying.**
  - A run with no carrier card showed a statement about its carrier cards on the dashboard, while
    `runs show` printed nothing. `section_notice` now decides for both.
  - An unhashable `class` or `mechanism` raised `TypeError` rather than a located `CardError`.
  - The notice's `h3` came before any `h2` when grouped by tier; it is now a labelled paragraph.
  - The detail template copied the allele-class labels; it now reads them from the engine, so a
    new class cannot be dropped silently. It also shows each limit's mechanism, as the CLI does.
  - The record held a key per current class, so adding a class would have broken older records. It
    now holds only the classes present.
  - Computed sources and their sections were literals in `cards.py` and `bundle.py`. Both now read
    `COMPUTATION_SECTIONS`.
  - A duplicated test helper was merged.

## Recorded rather than changed

- **`runs show --json` adds no statement for a run without the record.** The review proposed one,
  and the change failed `test_guideline_saved_cli_dashboard_and_corruption`: that command is the
  frozen bundle inspection interface and holds no current context, by decision
  ([PGx framing](pgx_framing.md)). The change was reverted. An agent gets the same limit from
  `genetics cards carrier-scope --json`, and each frozen carrier card keeps its own `typed_scope`.
- **The saved face is bound to the code's wording.** A read rebuilds the summary, caveats and
  reliability and refuses a difference, as HLA cards do. So editing that text would make format-27
  runs unreadable, and an imputed run costs about eight hours to recreate. The strictness stays,
  because a face contradicting its record is the failure these checks exist for.
  `test_the_saved_wording_is_pinned` now fails on any such edit and says what to do: bump the
  record's schema and keep the old wording for the runs that hold it.
- **A new computed source still needs parallel edits** in the `evidence.py` chain, the pipeline
  and `_carddetail.html`, whose `else` falls through to the archaic partial. This predates M11.6.
- **`AUTOSOMAL_RECESSIVE_TABLES` and `X_LINKED_TABLES` are Gregg 2021's numbering in code.** A
  different reference list is refused loudly, not misread, so this waits until one is wanted.
- **`carrier_scope.py` has its own small validators** instead of the private ones in `cards.py`.
  A shared set is a separate tidy-up.

## Checked without change

- **The reference list.** All 113 rows came from the source, and its stated totals (86, 97, 16)
  match. The correction changes wording only. Its updated supplement was not read.
- **The limit sentences.** Bladen 2015, Antonarakis 1995 and Verkerk 1991 were checked against
  their abstracts, not their full text.
- **Bundle reads.** The scope check runs on every open, including reads that skip the deep checks,
  and costs a rebuild of a small record. Formats 1–26 hold no such card and are read unchanged.
- **Privacy.** The record lives in the gitignored `cards.run.json`. The pack-level comparison reads
  no run. No new output type was added.

## Validation

Run on 2026-11-06, Windows, Python 3.13, Java 17 and the pinned PLINK/Beagle tools configured:

- The full native suite passes **3,829 tests with nine skips**: the five existing Windows
  skips and the four published-classifier HIBAG tests, which need a separate reference root.
- The carrier-scope and native reference files pass **106 tests**. Pointing one `not_authored`
  row at another alternate fails the per-allele check. Both redirect regressions failed before
  the entry-point fix.
- Full dbSNP card lint passes **101 cards, 508 renders, 54/54 marker keys**.
- All four strict Windows/Linux × Python 3.11/3.13 type targets pass (241 files), as do ruff,
  format and fixture reproduction.

The dashboard's new notice and detail view were checked through rendered responses in tests, not
in a browser.
