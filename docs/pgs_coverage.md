# Per-score variant coverage (M9.3)

AGENTS.md §4.3 says every PRS card must report how much of its score was actually used,
before and after imputation. M9.3 produces that data in the shared engine. It is in every
private `.pgs-score.json` and is available from the CLI. M9.6's renderer puts it on the
card face. The module is `pgs/coverage.py`.
Coverage is calculated from the saved term evidence. It never comes from PLINK's matrix
`ALLELE_CT`/`DENOM` or from the biological `native_alleles` total, because neither one
counts variants or describes the original chip.

## Commands

```text
genetics pgs score path/to/score.txt.gz --input path/to/export.txt      # coverage included
genetics pgs coverage path/to/result.pgs-score.json --json
genetics pgs coverage path/to/result.pgs-score.json --scoring-file path/to/score.txt.gz
```

`genetics pgs score` now prints one coverage line per phase. `pgs coverage` reloads a
saved result and recalculates coverage from that result's own terms. It refuses the
result if the stored coverage differs. With `--scoring-file`, it also checks that the
public source has the recorded SHA-256 and size. It then checks that every saved row
matches `ScoringFile.iter_variants()` exactly. Both outputs are **private**: coverage
counts come from a person's genotypes, just as the sums do.

## Denominators: what is counted

`coverage.source` describes the public score and is the same for every person.

| Field | Meaning |
| --- | --- |
| `rows` | Every authored weighted row, including unresolved, excluded and model-ineligible ones. |
| `model_eligible_rows` / `model_ineligible_rows` | Rows the additive engine can use, and the rest counted by reason (`unsupported_model`, `unsupported_chromosome`, `unresolved_locus`, `allele_contract_missing`, `harmonization_mismatch`). |
| `variants` | Unique allele-defined variants: GRCh37 locus plus the unordered allele pair as written. Reverse-strand spellings are not merged by assumption. |
| `repeated_variants` / `rows_in_repeated_variants` | Variants that have more than one row, and how many rows those variants have in total. |
| `variants_with_multiple_effect_alleles` | Variants whose rows name different effect alleles. |
| `positions`, `positions_with_multiple_rows`, `positions_with_multiple_variants` | Unique loci. A triallelic position can hold two variants. |
| `undefined_rows` | Rows with no stable identity, either because the locus is missing or because the allele pair is missing (for example raw `I`/`D` or several other alleles). Each keeps its raw authored definition and its ineligibility reason. |
| `absolute_weight_total` | Σ\|weight\| over the scalar-weight rows. |

## Each phase: before and after

`coverage.before` and `coverage.after` are calculated independently. A phase's `status` is
one of the following:

- `complete`: every row was scored.
- `partial`: only some rows were scored.
- `no_usable_observations`: no row was scored. The fractions here are a real **0.0**.
- `unsupported_model`: some rows may still be observed, but no sum exists, so
  `row_fraction` and `weight.fraction` are null.
- `unavailable`: the phase did not run. `reason` is `not_recorded` when only a saved stage
  was scored (there is no original chip table), and `disabled` under `--no-impute`.
  Every metric is null. **Unavailable is never 0%.**

A phase that is available reports the following:

- `rows`: `total`, `scored` (rows that entered the PLINK sum), `observed`, `not_scored` and
  `by_state`. An observed zero dose counts as covered. No-calls, absent markers,
  allele/strand/ploidy conflicts, ambiguous panel records and unsupported definitions are
  not scored terms, and they stay separate in `by_state`.
- `row_fraction`, `observed_row_fraction`.
- `variants`: `with_usable_dose` and `partially_observed`, each against the variant count.
- `positions`: two separate claims. `with_usable_dose` counts positions where at least one
  row was observed. `evidence_present`, `evidence_absent` and `evidence_unknown` count
  whether any record existed at the position. Before imputation that means an array probe,
  including a no-call. After imputation it means a panel record or an original probe,
  because original probes are still part of the post-imputation observations.
  `evidence_fraction` is null while any position is unknown, and
  `evidence_fraction_bounds` then gives the range.
- `weight`: the share of total absolute weight carried by scored rows.
- `observations`: counts of observed rows by source, ploidy and dosage method, and their
  quality:
  - `estimated` counts rows that have their own DR2.
  - `unknown` counts the rest by reason: `not_estimated:<method>` for direct and
    phase-filled hard calls, and `allele_quality_unknown` for a multiallelic REF dose,
    which has no DR2 without ALT covariance.
  - `dr2_min`, `dr2_max`, `dr2_bins` (descriptive tenths; the last bin includes 1.0) and
    `absolute_weight_unknown_quality`.

  **Nothing here filters a row or scales a dose.** Low-quality and unknown-quality
  contributions stay in the sum and are only described. M9.5 owns their use in confidence.

`coverage.original_probes` describes the chip at the score's positions. It is available
only when the original table was scored. It reports positions on the array, absent and
unknown positions, the total probe count, called positions, and duplicate positions split
into `identical`, `complement_concordant`, `conflicting`, `insufficient_calls` and
`unclassified`.

- A palindromic (A/T or C/G) pair cannot be reconciled by strand, so differing calls
  there are `conflicting`.
- `unclassified` means no authored allele pair says whether a complement applies.
- These are properties of the chip. They never add to or remove from a row count.
- Saved-only scoring reports this block as `unavailable`/`not_recorded`. The direct
  records saved in the stage are not a complete list of the original chip's probes.

## Versioning and older artifacts

Score artifacts are now **schema 2**. Coverage carries its own `schema_version: 1`, and
`score_schema_version` records the artifact schema it was calculated under.

Schema 2 guarantees two things:

- Each exclusion keeps its proof: the original-array probe envelope, the native record or
  the `ambiguous_panel_records` envelope.
- Unavailable phase states are preserved.

Reload therefore rejects any of the following as corruption, without echoing data:

- a missing or mismatched coverage block
- an evidenced state with no proof
- proof at a different locus
- an invalid native record
- overwritten `not_recorded`/`disabled` states
- disordered rows
- phase counts that contradict the term states
- an unknown schema

Older **schema-1** files have no coverage. They are recalculated with the origin
`recomputed_legacy` and the label `evidence_proof: legacy_excluded_row_proof_may_be_missing`.
Their phase availability comes from `original_table_sha256` and `imputation_mode`, not
from the phase states, which can be overwritten in schema 1. An excluded or ineligible
row with no proof is `unknown`, never absent. When proof is missing, recalculate with the
current engine rather than reading the gap as a missing marker.

Run bundles stay at **format 16**. Score artifacts are separate files.

## Acceptance

`tests/refs/test_pgs_coverage.py` has 20 synthetic cases. They cover:

- repeated rows, multiple effect alleles and triallelic positions
- undefined rows
- identical, complemented, conflicting, palindromic and single-call duplicate probes
- observed zero versus a no-call and an absent marker
- real 0% versus `not_recorded`/`disabled`
- low, unknown, phase-filled and multiallelic-REF quality
- haploid X and diploid PAR
- original-call precedence
- unsupported models that still have observations
- equality across the API, the saved file and the CLI, including `--scoring-file`
- nine corruption cases, each confirmed to fail at its intended check
- source mismatch
- legacy schema-1 recalculation

The [M9.3 entry contract](handoff.md) lists the requirements these cases cover.
