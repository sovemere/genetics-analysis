# M9.9 session diff review

Reviewed on 2026-10-13: `e63fffb..54e2e7d`, covering M9.9's authored knowledge,
reference manifest/lock, synthetic integration tests and acceptance documentation.
The milestone changes no shared engine, knowledge schema, bundle format or
renderer. The review's test and documentation changes are recorded below.

## Finding and correction

**The synthetic integration test could miss swapped models or evidence.** It
replaced all three authored score/source IDs with one fabricated fixture before
checking model identity. CLI assertions compared sets of effects and evaluation
counts, so a correct collection attached to the wrong cards could pass.

An in-memory mutation swapped cognition and education's score/source IDs and
accessions without changing the repository pack. Both ancestry cases passed
before the fix. The same cases now check each authored phenotype's exact score
and source before fixture substitution, and bind its evaluation N and derived
effect/interval to the published correlation. Reloaded CLI results are checked
per card instead of as sets. Both ancestry cases reject the same mutation after
the fix. This strengthens the existing two cases; it adds no new test case.

The shipped cards already have the correct bindings and evidence; no production
card correction was needed. The test-module description now distinguishes
fabricated score inputs from real public study definitions and citations.

## Evidence and reference review

The [PGS002135](https://www.pgscatalog.org/score/PGS002135/),
[PGS002231](https://www.pgscatalog.org/score/PGS002231/) and
[PGS002213](https://www.pgscatalog.org/score/PGS002213/) records match cognition,
qualifications-to-years and neuroticism respectively. The
[primary study](https://pmc.ncbi.nlm.nih.gov/articles/PMC8764121/) supports the
UK Biobank-only, sparse LDpred2-auto model scope and held-out same-biobank
evaluation. These are residualized correlations, not total variance explained,
independent-cohort replication or within-family effects.

The authors' pinned
[phenotype counts](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/phenotype-info.csv),
[count export](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/export-info.R),
[phenotype preparation](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/prepare-pheno-fields.R)
and [model assessment](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/assess-pred-ldpred2.R)
confirm phenotype-specific training N, endpoint identity and released model
scope. Cognition uses online field 20191. The larger common training pool is
not substituted for each phenotype's N. The
[model audit](psychometrics_prs.md#exact-models-and-populations) retains the exact
counts, partial-r intervals and monotone `100 * r^2` transformations.

All three actual cached scoring files match the committed manifest and fetched
lock byte lengths and SHA-256 pins. Their authoritative per-score metadata CSV
licences classify as permissive EMBL-EBI default terms. Source releases and full
row counts are retained; payloads remain outside Git.

Unknown direct effects remain explicit. Education's EA4 attenuation is labelled
as context from another model, not applied to these weights. No complete matched
decile-outcome series, individual IQ/schooling/personality estimate or sensitivity
gate is invented. Existing confidence, both-phase coverage, portability and
reference-distribution presentation remain intact.

## Validation and M9.10 handoff

- All **51 card tests passed** in 39.49 seconds, including both strengthened
  ancestry cases. The swapped-model mutation was accepted before the fix and
  rejected afterward without modifying the authored YAML.
- Full dbSNP card lint passes **58 cards, 282 renders and 35/35 marker keys**.
  Ruff check and formatting pass for the changed test. The configured strict
  `mypy` run passes all 200 source files with the revised test.
- All **six saved native score/card pairs** were read from disk and passed
  frozen validation again. Native sums and full imputation were reused. The
  review validation report stays in the private checkpoint; original accepted
  resource measurements were preserved.
- M9.9's prior implementation validation remains **2,877 unique passed checks**,
  with five documented Windows platform skips, and all four strict type targets
  covering 200 source files. No full-suite test rerun is claimed for this
  test/documentation diff.

The unchanged renderer's browser visual check remains unavailable; existing
synthetic HTTP and chart geometry checks pass. No new browser capture is claimed.
No additional substantive defect was identified in the M9.9 diff.

The [M9.10 handoff](handoff.md#next-open-step-m910-substance-use-and-behavioural-propensity)
now specifies exact-model evidence and pre-substitution binding tests, distinct
substance-use endpoints, reusable durable public execution inputs, full-row
resource measurements and validation of written score/card pairs. M9.10 remains
the next open implementation step. Genetic inputs, dosage files, scores,
coverage summaries and their hashes stay outside Git and out of chat; only
authored source, tests and documentation belong in this review commit.
