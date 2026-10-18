# M11.3 session diff review

Scope: `c737261..818ba1a`. That covers M11.3's ancestry-driven HLA classifier selection
and per-locus call confidence (`a75fe6a`), plus the `genetics ci-local` line-ending fix
(`818ba1a`): 23 files across selection, confidence, calling, bundle, CLI, dashboard,
tests and documentation. The review used synthetic inputs only and opened no personal
export. HLA sample schema 2, selection schema 1 and bundle format 22 are unchanged by it.

## Findings and fixes

- **P2 — Most of the HLA dashboard's selection view was never rendered under test.**
  The only HLA dashboard test saved an explicit classifier with ancestry not run. So the
  template's placed branch never rendered: fit, decline threshold, margin, projection
  coverage, admissible populations and candidates, the lines every real placed run
  shows. The declined, ambiguous and unsupported views never rendered either.
  Reproduced: renaming one field in the uncertainty block, which would return a 500 for
  every placed run, left the session's tests passing. A new test renders a selected
  record, an explicit choice among ambiguous candidates, an explicit override of a
  declined placement, and an unsupported `no-classifier` refusal, through both the
  dashboard and `genetics hla calls`. The same template change now fails it.
- **P3 — The explicit-override wording misdescribed refusals.** For an explicit
  classifier, the dashboard said "the ancestry placement supported no classifier" even
  when the placement had not run, or had declined. The sentence now states the
  automatic outcome and any classifier it chose, for example "automatic selection:
  not_run". The new test pins that wording for the ambiguous and declined cases.
- **P3 — `select()` ignored a cancellation set after `prepare()`.** `prepare()` checks
  the stage's cancel event on entry; `select()` did not. A placement that needed no
  model preparation therefore went ahead after cancellation and produced a normal
  `no-classifier` record. This was reproduced: the regression test failed before the fix.
  `select()` now raises `HIBAGCancelledError` on entry, as `prepare()` does and as the
  M11.1 review required of public entry points.
- **P3 — A module docstring had moved onto the wrong constant.**
  `HLA_SELECTION_FORMAT_VERSION` was inserted between `HLA_FORMAT_VERSION` and the
  payload-file docstring that follows it, so that docstring (the gitignore rationale for
  `*.run.json`) became the new constant's. The constant now sits after that block, with
  its own docstring.
- **P3 — Unused constant.** `selection.STATUSES` was never read: `decide()` derives
  every status, and validation rederives the record. It is removed.

Each reproduced finding failed before its fix and passes after it.

## Checked without change

- **Rederivation.** A saved selection is the fixed point of `source(_expanded(...))`, then
  `decide(...)`. Python's float `repr` round-trips exactly through JSON, so recomputed
  margins compare equal on reload. Editing any field of the selection, of the frozen
  placements or of a locus ceiling is refused (existing tests).
- **Bundle binding.** The writer and reader both compare the selection's placements with
  the same bundle's `ancestry.run.json`. Format 21 records carry no selection and never
  reach that check. A schema/format mismatch is refused in both directions.
- **Decision order and the override table.** A decline takes precedence over not run.
  Ambiguity is tested before unsupported. Explicit matches agree with the contract
  table, including South Asian (unknown even when the explicit choice agrees).
- **Ceilings.** The posterior bands equal `calculate_confidence`'s DR2 ceilings. The
  coverage and ancestry bands are `ancestry_ceiling`'s. `ceilings` records only inputs
  that lowered the result.
- **Stage ordering.** An explicit model is verified before the export is read. An
  automatic one is verified only after selection, and a refused selection verifies
  nothing. Missing R or HIBAG keeps the selection and makes no calls.
- **Privacy.** The selection holds population labels and fits, never coordinates. It is
  saved only in the gitignored `hla.run.json`. `HLAStage` withholds every field from its
  repr (`NoGenotypeRepr`), and `genetics run` prints no HLA result.
- **`ci-local`.** After `git add`, checking the staged index rather than the pre-add
  status is sufficient: deletions are listed, and line-ending-only differences are not.
- **Documentation.** Claims in the contract, roadmap, handoff and README match the code
  and the recorded runs. One roadmap phrase was clarified: the "first draft" it
  mentioned was an uncommitted draft found in the working tree, not a commit.

## Residual risks, recorded rather than fixed

- A population fit of infinity (a reference population with zero radius) would make
  selection raise. This predates M11.3 and cannot occur in a saved run, because
  `ancestry.run.json` is rendered with `allow_nan=False` and such a value fails there
  first.
- `run()` does not re-check cancellation; that is M11.2's behaviour, and HIBAG's own
  bridge checks the event on entry and while waiting.

## Validation

`genetics ci-local` ran the CI workflow in a fresh clone, with an empty data directory
and the review changes overlaid. Every step passed on Windows with Python 3.11 and 3.13:
lint, format, both mypy platforms, card lint, the privacy suite, the pinned-tool
installs, the full test suite and byte-identical fixtures. Each Python ran
**3,513 tests passed, 17 skipped**: Windows OS-isolation and POSIX-mode limits, no
raw export in the tree, native PGS tools unset, and the four published-classifier tests,
whose references are not configured there. Native synthetic HIBAG prediction ran,
because R 4.6.1 + HIBAG 1.48.2 is on PATH. The affected HLA, bundle, web, confidence and
`ci-local` files passed **476 tests**, with four skips (published classifiers), before
the full run.

The review changed no prediction path, so the published-classifier acceptance recorded
in [the contract](hla_selection.md) still holds and was not rerun. The Linux jobs
are not reproducible on this machine and are covered by GitHub CI on push. No personal
export, fetched payload or genotype-derived artifact is included.
