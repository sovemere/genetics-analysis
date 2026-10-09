# M9.5–M9.6 session diff review

I reviewed `b2bde81..317c825` on 2026-10-09. That range covers:

- **M9.5 ancestry portability:** `pgs/portability.py`, `engine/confidence.py::ancestry_ceiling`,
  schema-4 score results and `genetics pgs portability`.
- **M9.6 polygenic cards:**
  - knowledge schema 4 and `kind: polygenic`;
  - `pgs/cards.py`, `pgs/runner.py` and the `genetics run` stage;
  - bundle format 17 and `pgs.run.json`;
  - `calculate_polygenic_confidence`;
  - the dashboard chart and detail;
  - card lint, docs and tests.

I read the whole diff and probed suspected failure paths with fabricated runs. No personal
export or private run was opened.

## Findings and fixes

| Finding | Resulting behavior |
| --- | --- |
| **A score missing from the fetched metadata aborted the whole run.** `ScoringFile.open` raises when the release has no metadata row for the card's score, which happens when the release predates the score. `PolygenicStage.prepare` let that propagate, so one card stopped `genetics run` and every other finding with it. That breaks the absent-is-not-wrong rule the rest of the stage follows. | The card stays `not_run`, with the reason and the refetch command. Every other card still runs. |
| **Some structural damage escaped `read_bundle` as a raw exception.** Polygenic validation converted `PgsError`, `KeyError`, `TypeError` and `ValueError`, but not `AttributeError` or `IndexError`. A damaged but digest-consistent record could therefore escape as something other than `BundleError`. The M9.4 review fixed the same class of gap in `read_placement`. | Both are now converted to `BundleError` naming the card. |
| **The face text was false above a within-family attenuation of 1.** The schema admits values up to 1.5, but the face said "retain about 120% … the rest reflects ancestry…". | Above 1, the face says the within-family estimate is about that share of the population effect, and that the population association does not overstate the direct effect. |

All three regressions fail on the pre-fix code and pass after.

## Checked and left as is

- **Missing lock files.** A missing `manifest.lock` reads as an empty lock, so an unfetched
  scoring file is a reason, not a crash.
- **One point can be read off the interval.** The interval's centre implies the
  mid-rank percentile. That is inherent to showing any interval. The requirement is
  that the width dominates and that no point is drawn or stored on the card, and both
  hold.
- **A not-placed card's reason text is not re-derived on read.** Its face is recomputed
  from the stored reason, so editing both together goes undetected. Tampering is outside
  the bundle threat model, and the record digest still binds every number.
- **Opting into restricted licences.** There is still no opt-in inside a run;
  `genetics pgs score --allow-restricted` remains the only path, as documented.

## Validation

- The full native suite passes **2,837 tests, five existing Windows skips**, with pinned
  PLINK 2/PLINK 1.9/Beagle/bref3 and Java 17.
- All four strict type targets pass.
- Lint/format, fixture reproduction, full dbSNP card lint (51 cards, 268 renders) and
  staged privacy scanning pass.
