# Imputation quality propagation (M8.5)

Enabled `genetics run` analyses now use imputed observations at absent or no-call
interpretation-card loci. Any original called probe takes precedence, including an
indel, contradictory ploidy, duplicate conflict or unresolved strand. The original
table remains unchanged for QC, ClinVar, chip coverage and genome structure.

Card matching accepts only exact biallelic SNV allele definitions. It uses Beagle's
validated hard call, not rounded dosage. Exact reference allele contracts establish
forward orientation for imputed calls, including palindromic SNPs; original consumer
calls keep their existing strand checks. Unphased multi-marker constraints still apply.
Multiple panel records at a position remain ambiguous. Imputation never
supplies an allele-specific interpretation for an indel or incompatible panel variant.
No confidence threshold removes a finding.

## Quality and confidence

Each imputed card/marker records source (`imputed_untyped` or `imputed_no_call`),
REF/ALT definitions, native per-ALT dosage, per-ALT DR2 where estimated, biological
ploidy, dosage method and quality scope. DR2 is reference-model dosage quality, not
the posterior probability of this individual's hard call.

The existing confidence model retains its quality gates: DR2 below 0.30 means
likely artifact; below 0.60 caps confidence at limited; below 0.80 caps it at moderate.
Quality contributes its numeric value to the weighted confidence calculation.
Other evidence, allele frequency and ancestry ceilings continue to apply.

Phase-filled no-calls carry `dr2=null`, `phased_hardcall_only` and `not_estimated`.
The second Beagle invocation treating them as typed does not recover their missing
uncertainty. Their raw quality remains unknown, their quality contribution is zero,
and confidence cannot exceed limited. Numeric-quality-free imputation requires this
explicit provenance; a bare missing quality is still an error.

Single-copy X observations retain a 0–1 dosage scale and native haploid quality;
normalizing their allele string to the doubled table representation does not change
dosage, ploidy or quality. Wrong biological ploidy or storage conversions are refused.
Multi-marker cards inherit the weakest constituent's confidence and retain every
marker's metadata. Beagle phase is not used to assume a unique diplotype.

## Effect-allele contract for M9 scoring

`ImputationEvidence.allele_dosage(allele)` returns dose and that allele's quality
together. It never filters low-quality variants or scales their doses by DR2.
Each ALT receives its own DR2. A biallelic REF dose is the ploidy-complement of ALT
and shares its dosage quality. A multiallelic REF dose is complementary to the sum,
but its quality is unknown without covariance; per-ALT DR2 values are never averaged.
Independent ALT writer rounding can make their sum exceed ploidy within the validated
tolerance; complementary REF dosage is clamped at zero in that case.

M9 owns PGS weights, score sums, coverage and ancestry calibration. This milestone
connects imputation to the current confidence scoring and exposes the allele-oriented
quality contract those score consumers must retain.

## Saved observations and front ends

Bundle format **15** stores imputed observation detail beside each scalar or constituent
marker. Execution schema **2** identifies `card_input=original_array_with_imputed`.
Reader/writer checks bind quality to the dosage model, source and ploidy, validate
phase-filled allele counts and ensure confidence cannot bypass its quality ceiling.
Saved reads require neither dosage caches nor reference databases. Formats **1–14**
retain their original confidence and observation basis, including schema 1's array-only
execution record. New fields cannot be relabelled as format 14.

CLI card JSON and dashboard detail use the same saved evidence. The banner states the
observation basis; the face states confidence and imputed/unknown quality, and detail explains source, native
ploidy, dosage quality and unknown estimates. `--no-impute` remains explicit and recorded.

Tests use generated targets, fabricated boundary observations and fixed-seed native
references. They cover quality thresholds, direct-call preservation, unknown quality,
per-ALT contracts, haploid scope, weakest-marker inheritance, historical snapshots,
damaged saved metadata and CLI/dashboard parity. Native acceptance runs the pinned
Beagle stage and checks both untyped quality and phase-filled unknown quality.

M8.6 supplies durable full dosage files and exact used-panel/tool/parameter provenance;
see [the provenance guide](imputation_provenance.md). Format 16 retains this format-15
card/marker contract while adding the full snapshot.

## Rare-call frequency gate (M8.7)

An observed allele frequency strictly below **0.00001 (0.001%)** caps the finding at
`likely-artifact`, even with DR2 1 and strong replicated literature. Equality falls
outside that band; other evidence and quality ceilings still apply. This holds for
both untyped and phase-filled observations and for native haploid/diploid calls.
Unknown phase-filled quality remains unknown, contributes zero and cannot rescue rarity.

A known rare allele retains the ceiling when its observed companion has no usable
frequency. Common-only incomplete coverage stays unknown; an unobserved rare allele
does not penalize the call. A multi-marker finding inherits its weakest marker's tier,
without averaging quality or assuming phase. Original called probes remain direct;
explicit `--no-impute` neither discovers imputation prerequisites nor invents observations.

The 16% rare-heterozygous and 4.2% pathogenic BRCA chip-confirmation rates remain
study-specific benchmarks, explicitly uncalibrated for imputation and never individual
posterior probabilities. BRCA-specific calibration belongs to original-array ClinVar
annotations; M8.7 does not add imputed ClinVar calling.

Thirty-two synthetic regression cases exercise these boundaries, missing frequency
companions, multi-marker inheritance, original-array controls and full format-16
save/reopen parity. CLI JSON and dashboard face/detail retain the tier, selected
frequency, native dosage/quality/source, benchmark scope and caveats after stage caches
and the synthetic frequency index are removed. Bypassing either the imputed rarity
ceiling or the missing-companion protection in isolated processes makes the respective
regressions fail. No personal export was opened and no reference download is required.
