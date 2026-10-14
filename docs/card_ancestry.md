# Card-level ancestry match (M9.13)

## Saved contract (before implementation)

Bundle format 18 adds optional `reference_population` to the ancestry snapshot and
`ancestry_comparison` to interpretation cards. The pipeline computes the 1000
Genomes placement before imputation and shares that exact result with PRS scoring.
AADR sampling countries are never converted into super-population codes; its
decline remains a gate. Existing formats 1–17 retain their saved evidence,
confidence and unknown ancestry, without consulting the current knowledge pack.
No new private output type is introduced.

The selected outcome's evidence supplies study codes. An explicit matching code
means agreement at super-population resolution, not individual predictive
calibration. A nonmatching fully specified study is mismatched; MULTI or UNKNOWN
without an explicit matching code is indeterminate. Declined, not-run and absent
outcome evidence are distinct. The comparison records its study codes, compact
sample/gate states, method, numeric input and complete display wording.

## Confidence decision

For variant cards only, known agreement/disagreement supplies 1/0 to the existing
5% weighted ancestry component. Unknown study, unspecified MULTI, not-run and
absent evidence supply None (neutral 0.5), never measured agreement. A panel
decline supplies 0 when applicable evidence exists. This is an engine heuristic,
not a measured transfer fraction or individual probability. PRS retains its
existing M9.5 study-share calculation and transfer ceilings.

No PRS ancestry ceiling is applied to variant cards. Unknown ancestry retains
the pre-existing strong ceiling. Functional, GWAS, cohort and candidate-gene
cards all retain their evidence, replication, frequency and quality limits:
functional evidence does not prove universal penetrance; a large GWAS effect
does not prove a causal variant; candidate/conflicting findings cannot become
strong through an ancestry match. Null outcome estimates remain limited.

This decision follows the actual corpus: ABCC11 carries independent protein
function evidence ([Toyoda et al.](https://doi.org/10.1096/fj.09-129098)); TCHH
carries a European association with unresolved causality
([Medland et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC2775823/)); lactase
persistence has alternative causal alleles in African populations
([Tishkoff et al.](https://doi.org/10.1038/ng1946)). None provides a general
numeric ancestry-transfer penalty for every single variant. Existing endpoint
and population caveats remain attached; mismatch wording explicitly says the
published effect is not calibrated for the sample. ACE UNKNOWN and ACTN3 MULTI
cannot establish agreement. Cohort-specific HFE/F5/APOE absolute rates remain
cohort context, never transported personal risk.

## Display and validation

`{ancestry}` renders the comparison sentence. Every pipeline interpretation
card shows that sentence on its face and detail even when no template uses it.
CLI and dashboard use the same frozen summary/detail. Reload validates the
comparison against saved selected evidence and saved run placement, verifies
per-marker numeric inputs and confidence, and rejects contradictory snapshots.
Historical cards have no newly inferred comparison.

## Acceptance (2026-10-14)

M9.13 is complete. The current inventory is 3,000 tests: **2,995 unique checks
pass, five existing Windows skips**. The final complete native run passed 2,994
in 447.80 seconds with one tool-discovery failure: an existing native reference
helper discovers bref3 through the default data directory rather than its supplied
tools object. The isolated temporary data root lacked that installation. The
same test passed its corrected default-tools recheck (5.37 seconds); no test or
production behavior was weakened. All native PLINK 2/1.9, Beagle, bref3/decoder,
PRS arithmetic checks and Java 17 were enabled.

All four strict Windows/Linux × Python 3.11/3.13 targets check 203 files.
Lint/format, fixture reproduction, whitespace checks and staged privacy scanning
pass. Full dbSNP card lint passes 69 cards, 320 template renders and 39/39 keys.
Sixty-seven new synthetic cases cover membership/unknown states, both declines,
selected/null evidence, multi-marker inheritance, saved corruption and historical
behavior, frozen CLI/dashboard parity, placement reuse and private repr output.
The endpoint/effect model corpus is unchanged; no new personal input or scoring
reference was used. Synthetic HTTP face/detail checks pass; the renderer markup
is unchanged and no new browser screenshot review is claimed.


## Diff review

The [M9.13 session review](review_m913_session.md) binds measured saved placements
to their retained population/region fits and first admissible threshold result,
with distance/radius checks. Frozen scalar calibration now checks declared allele
membership and strand orientation; numeric comparison rejects booleans while
preserving equivalent JSON number spelling. Card detail and modal views retain
the actual damaged-run refusal. The schema, weighted variant policy and valid
interpretations remain unchanged.

Reviewed validation: **3,015 tests pass, five existing Windows skips**, in one
complete native run. Twenty new synthetic regressions and four strict type targets
pass; full card lint, lint/format and fixture reproduction pass. See the review
record for the reproduced failures and the next-step source-preparation audit.
