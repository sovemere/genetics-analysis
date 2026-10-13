# M9.11 session diff review

Reviewed on 2026-10-13: `1bebcff..92d2efb`, covering the three sleep/circadian
cards, reference manifest/lock, synthetic integration tests, corpus counts and
acceptance documentation. No shared engine, knowledge schema, bundle format
or renderer changed in that diff.

## Finding and correction

**The integration tests could miss a reversed direction on the card face.**
The existing tests bound each exact model, field citation, evaluation N and
effect interval before synthetic substitution, and checked questionnaire
coding in the detail view. They did not bind the `trait` text used by the
shared engine to construct the face. Reversing that text alone left the
detail and numeric evidence correct while displaying the opposite association.

Three in-memory mutations changed evening to morning preference, longer to
shorter sleep, and more to less frequent sleeplessness. Each mutated pack
passed the existing matched-ancestry pipeline, saved-bundle, CLI and dashboard
checks. The new regression cases therefore failed before the correction with
`DID NOT RAISE AssertionError`. The repository's authored cards were never
modified by this experiment.

The tests now bind each model's complete directed phenotype before fixture
substitution and check that phenotype in the computed face, reloaded CLI
summary, dashboard section and card detail. All three mutations are rejected
with the specific direction-binding assertion; both normal ancestry cases
continue to pass. The three mutation cases remain as regressions.

The shipped card directions were already correct. No card, scoring, schema
or renderer correction was needed.

## Evidence and reference review

The public [PGS002209](https://www.pgscatalog.org/score/PGS002209/),
[PGS002196](https://www.pgscatalog.org/score/PGS002196/) and
[PGS002149](https://www.pgscatalog.org/score/PGS002149/) releases match
`more_evening`, `log_sleep` and `insomnia` LDpred2-auto HapMap3 models.
The author's pinned [prediction assessment](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/assess-pred-ldpred2.R)
explicitly selects sparse predictions for its reported model comparisons.
Their complete harmonized GRCh37 files match the committed manifest and
fetched lock SHA-256 values and byte lengths; internal harmonization dates
remain 2022-07-28. The authoritative per-score metadata CSV entries retain
EMBL-EBI default terms. No reference payload is committed.

The pinned author [phenotype preparation](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/prepare-pheno-fields.R),
[count export](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/export-info.R)
and [phenotype counts](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/phenotype-info.csv)
confirm the three training sample sizes. The count export counts nonmissing
training phenotypes after preparation, including the 4–12-hour restriction
and natural-log transformation for sleep duration. Questionnaire category
direction and the inclusion of naps remain correctly stated.

The [version-2 prediction release](https://doi.org/10.6084/m9.figshare.14074760.v2),
`pred-cor-ldpred2.csv` (file 31619354), independently confirms each held-out UK
evaluation N and partial-r interval. All three intervals are positive, so
the documented `100*r²` transformations are monotone. Residual ordinal/log
variance is kept distinct from raw hours, clinical diagnoses, independent
replication and causal within-family effects. No baseline, individual outcome
conversion or complete absolute decile series is invented.

Corpus counts also agree with the committed pack: 64 cards, comprising 34
interpretations (33 single-marker and one two-marker), five computed cards,
12 assay-limit cards and 13 polygenic cards. M9.12 remains the next open item;
the M9.11 full-model acceptance and reusable-input handoff are consistent.

## Validation and retained acceptance

- All **62 card tests pass** in 39.75 seconds. After tightening the regression
  to require the specific direction assertion, all seven sleep cases pass
  again in 5.40 seconds. The three inversion cases were reproduced before
  the fix and rejected afterward.
- Full dbSNP card lint passes **64 cards, 294 renders and 35/35 marker keys**.
  All four strict type targets (Windows/Linux, Python 3.11/3.13) pass for
  200 source files; Ruff check and formatting pass.
- All six retained native card payloads were read locally and matched to
  their actual authored model, directed phenotype, citations, evaluation N
  and effect/interval. The private binding-review report is saved alongside
  the completed acceptance checkpoint. No genetic values or hashes were
  printed or added to Git.
- M9.11's earlier full-scale acceptance remains valid: all three references,
  six scoring checks and six full score/card disk-read validations passed.
  This review leaves their frozen inputs and records unchanged; native scores,
  imputation and full-record validation were not rerun.
- The implementation's **2,885 unique passed checks**, five existing Windows
  skips and measured resource record remain historical acceptance results.
  This review adds three regression cases; no full-suite rerun is claimed for
  the test/documentation diff.

The unchanged renderer's earlier browser visual check remains unavailable;
no new screenshot review is claimed. No other substantive issue was found in
the reviewed diff. Genetic inputs, dosage files, scores, coverage summaries
and their hashes remain outside Git and out of chat.
