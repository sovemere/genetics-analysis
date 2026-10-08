# M9.1–M9.2 diff review

Reviewed `7ca87aa..94a3b22`, completed 2026-10-09: the M9.1 parser/licence/reference
transform and M9.2 native scoring/workflows/CLI, together with their tests, privacy
ignores and handoff. Review probes use fabricated observations only. No personal
export, private saved run or new reference payload was opened or fetched.

## Findings and fixes

| Finding | Resulting behavior |
| --- | --- |
| The parser validated authored `other_allele` but accepted malformed `hm_inferOtherAllele`, including an inferred allele equal to the effect allele. | Both columns receive the same syntax/distinctness validation. Multiple authored/inferred alleles remain preserved; they do not become an invented biallelic contract. |
| Excluded native observations and model-ineligible rows lost their evidence. Unsupported models also overwrote disabled/unrecorded phase states. | Exclusions retain original probes or the complete native record, including native per-ALT quality. Multiple panel records are retained in an explicit `ambiguous_panel_records` envelope. Saved-only before states remain `not_recorded`; opted-out after states remain `disabled`, even for unsupported models. |
| Matrix preparation and output-parent failures escaped the categorical error boundary, and partially prepared matrices could remain after a write failure. | Preparation, workspace/publication and cleanup failures raise genotype-free `PgsError`; matrix cleanup covers preparation as well as execution. |
| Workflow flags were checked only after ingest, ancestry and possibly imputation. A truthy nonboolean restricted-source opt-in could pass the initial licence gate. | Export and saved workflows validate explicit booleans before licence gates or personal-input work. |
| Invalid output suffixes, checkout paths, existing destinations and nondirectory parents were rejected only after analysis. | The CLI preflights its private destination before analysis. Publication repeats validation and retains atomic no-overwrite semantics against concurrent creation. Permission changes can still fail at publication. |
| A reused workspace could accept old `.sscore`/`.sscore.vars` files when an invocation returned success without producing new reports. | Both expected reports are removed before native execution; missing new reports fail validation. |
| Finite individual weights could overflow weighted contributions and make the independent verification bound infinite. | Nonfinite products, accumulated arithmetic or verification bounds are refused. A finite native report cannot bypass verification through overflow. |

All **19 new regression cases** reproduced their respective defects before the fixes.
One allele-mismatch probe was corrected to avoid representing a valid reverse-strand
match, then reproduced the missing-evidence defect before its fix. The focused M9 suite
passes **135 cases**, including pinned native PLINK arithmetic.

The authoritative metadata licence gate, source-change checks, original-call precedence,
raw dose/DR2 separation, haploid biological counts, null-versus-zero policy and exact
sequence-indel rule remain intact. The Catalog's definitions of inferred alleles and
same-build match flags were cross-checked against its
[official format specification](https://www.pgscatalog.org/downloads/#hm_pos_columns).

## Validation

The full offline native suite passes **2,726 tests, five existing Windows skips**,
with pinned PLINK 2/PLINK 1.9/Beagle/bref3 tools and Java 17. All four strict
Windows/Linux × Python 3.11/3.13 type targets pass, as do lint/format, fixture
reproduction and full dbSNP card lint (51 cards, 268 renders, 35 marker references).
The cached public Catalog still parses 6,991 metadata scores and 77 PGS000001
GRCh37 rows with networking blocked. Staged privacy scanning finds no genotype
content. No personal export or private run was used.

## M9.3 handoff

There is no known blocker to implementing per-score coverage. Start with
`ScoringFile.iter_variants()`, `ScoreResult.record["terms"]` and the before/after phase
states, using the shared engine/workflows rather than a CLI-only calculation.
The detailed denominator and acceptance contract is in [handoff.md](handoff.md).

Keep weighted rows, allele-defined variants, positions and array probes distinct.
PLINK matrix `ALLELE_CT`/`DENOM` and biological `native_alleles` are neither unique
variant coverage nor an original-chip denominator. Model-ineligible definitions stay
in the source denominator, with their reason attached.

Existing standalone score artifacts remain schema 1 and run bundles remain format 16.
The fixes preserve raw sum semantics and enrich evidence; they do not retroactively
repair older artifacts that lost excluded records or phase availability. M9.3 must
validate saved coverage inputs and represent unavailable evidence explicitly, or
recompute with the current engine. Missing proof in an older artifact is not evidence
that a marker was absent. Coverage persistence needs its own versioned contract.

Reference distributions, study-to-sample ancestry mapping, calibrated confidence and
the card renderer remain M9.4–M9.6. Low/unknown quality is retained for those steps;
neither this review nor M9.3 may silently filter or rescale dose.
