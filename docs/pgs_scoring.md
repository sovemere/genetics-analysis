# Native PGS sums (M9.2)

M9.2 computes signed weighted sums through the pinned PLINK 2 build. It supports
original-array observations and native imputed effect-allele doses. The shared
engine is `pgs/engine.py`; `pgs/workflow.py` orchestrates the same ingest, ancestry
and imputation functions used by the analysis engine. The CLI calls those functions.

## Commands and private output

```text
genetics pgs score path/to/selected-score.txt.gz --input path/to/export.txt --json
genetics pgs score path/to/selected-score.txt.gz --input path/to/export.txt --no-impute --json
genetics pgs score path/to/selected-score.txt.gz --run path/to/saved-run --json
```

References are acquired through the existing manifest/fetcher. Metadata defaults to
the validated M9.1 catalogue; `--metadata` can supply an explicit archive/index.
Every computation checks the score-specific licence. Recognized restricted terms
require `--allow-restricted`; that flag cannot grant missing, unknown or ambiguous terms.

The export workflow validates the reference before ingest, runs ancestry first, then
performs imputation by default. `--no-impute` is an explicit, recorded development/testing
mode; it never happens automatically after a prerequisite or execution failure.
The saved-run workflow validates an existing full format-16 dosage snapshot, including
its independent files and recorded provenance. Older, disabled or unrecorded stages
cannot provide those observations. The original chip table is not reconstructed from
the stage-direct stream: saved-only scoring reports its original-array sum as
`not_recorded` and its value as null.

Each successful command writes an immutable **private** `.pgs-score.json`, by default
under the OS user-data cache outside the checkout. `--output` selects a new file with
that suffix. An in-repo destination needs explicit `--allow-in-repo` and remains ignored.
Publication uses a same-directory temporary file and an atomic no-overwrite link;
an interruption or failed write does not publish a partial result.
The CLI checks the destination suffix, checkout opt-in, existing file and parent-directory
constraints before analysis. Publication rechecks them; concurrent creation or permission
changes still fail without overwriting an existing result.

`--json` emits the private record: scores, original probe evidence, native per-ALT
observations, source/quality/ploidy, exclusions, raw score metadata, study citations,
reference fingerprints, input/stream fingerprints, used imputation provenance,
PLINK version/binary hash, tool-manifest hash and engine/method versions. These are
genotype-derived data, including the hashes and aggregates. Never commit or publish
them. Default text output reports the result status and private destination.
The existing run-bundle format remains **16**; these are separate score artifacts.

## Matching and supported models

Matching uses the GRCh37 chromosome/position and the score's allele contract; rsIDs
remain secondary identifiers. An exact `other_allele`, or the retained harmonized
inferred other allele, must establish a distinct sequence pair. No missing allele is
invented from a homozygous observation. All parsed score rows retain their raw fields.

Original called probes retain precedence after imputation, including indels, conflicts,
strand ambiguity and contradictory ploidy. Duplicate calls must agree, allowing a
complemented representation at non-palindromic SNPs. Complement inference is recorded;
homozygous reverse inference is distinguished from a two-allele observation.
Palindromic outcomes whose effect count changes with strand stay unresolved. Both
possible orientations at a four-allele reference locus also stay unresolved.

Native records must be resolved, have valid allele/dosage/quality contracts and agree
with the recorded sex and GRCh37 PAR boundaries. Autosomes are diploid; female non-PAR X
is diploid, male non-PAR X haploid, and X PAR diploid. Unknown non-PAR X ploidy stays
unresolved. Y/MT/vendor-PAR score terms are explicit unsupported-chromosome states in
this milestone. Multiple panel records at a score locus remain ambiguous.

For sequence-resolved imputed indels, both sequences must match the recorded reference
locus exactly. They are not complemented or reanchored by assumption. Raw `I`/`D` calls
remain excluded; a present called probe is not replaced to resolve its missing sequence.

Additive scalar-weight models are implemented. Haplotype/diplotype, interaction,
dominant/recessive, dosage-specific, special-calling and conditional models are reported
as `unsupported_model` with null sums, preserving their definitions. Dominant/recessive
expectations generally need genotype probabilities; clipping an expected dose would not
compute the expected genetic contribution. They are not flattened into additive rows.

Every row has an explicit before/after state. Missing, incompatible or unresolved
observations do not contribute a fabricated mean dose. A zero observed dose contributes
zero and remains a scored term. Zero usable observations yield null, not a numerical
zero score. A sum from some rows is labeled `scored_partial`; these counters describe
weighted terms, not distinct marker-position coverage.
Excluded terms retain their original probes or native record. Multiple native records
use an `ambiguous_panel_records` envelope with every candidate retained. Unsupported
models preserve saved-only `not_recorded` before and opted-out `disabled` after states.

## Native dose, quality and numerical verification

`ImputationEvidence.allele_dosage()` supplies the actual effect dose with its own quality.
Each ALT keeps its DR2; a biallelic REF shares the complementary dosage quality, while
multiallelic REF quality remains unknown without covariance. Phase-filled calls retain
unknown quality and their hard-call-only method. **No quality threshold filters a row;
DR2 never scales its dose.** Native single-copy doses remain on their 0–1 scale.

The PLINK input is a **numeric effect-dose matrix**, not a genomic reinterpretation of
the sample. Each selected score row has a unique term ID, synthetic chromosome-1
coordinates and synthetic C/A labels; its A dosage is the already validated biological
effect count. This prevents PLINK's haploid/X import encoding from altering that count.
The actual chromosome, position, alleles, original probes and biological ploidy stay in
the private term record. These internal matrix files must never be fed to other genomic
modules. Repeated score positions/alleles remain distinct weighted rows.

The pinned invocation explicitly imports DS, sets `--dosage-erase-threshold 0`, uses
`--score ... header-read no-mean-imputation`, requests sums and used-term IDs, and uses
one thread/1024 MB. No centering, variance standardization, dosage rounding to hard calls
or implicit frequency-based filling is applied. Temporary matrices and sample-selected
weights are deleted on success or failure; any remaining native artifacts remain private
and ignored. Progress contains no observations or score values.

Readers require one target, exact report columns, all expected term IDs and the exact
matrix allele count/denominator. The matrix count is **two per term**, even when the
biological observation is haploid; it is not chip coverage. `native_alleles` separately
sums the recorded biological ploidy across scored terms, not unique genomic loci.

PLINK's diploid dosage storage has resolution 1/16384, and its score report prints six
significant digits. Disabling dosage erasure preserves the available fractional precision,
not arbitrary decimal precision. Each sum is checked against `math.fsum(weight × native
dose)` within a recorded bound: half the dosage-storage unit times the absolute weights,
plus report rounding and a small floating-point tolerance. The native report sum, exact
input-dose arithmetic audit and bound are saved separately. The dosage total is also
checked. Nonfinite, wrong-target, missing-term, count or arithmetic failures accept no
score. The executable is hashed before/after both phases to reject a changed producer.
Expected native reports are removed before execution so a reused workspace cannot supply
stale results. Weighted products and verification bounds must also remain finite.

## Acceptance and next scope

Synthetic tests cover independent native arithmetic for signed weights, fractional
near-integer doses, male haploid X and diploid PAR, allele-specific/missing quality,
multiallelic REF complements, exact imputed indels, original-call precedence,
duplicates/strand/ploidy, licence gates, malformed reports, explicit opt-out,
default ancestry/imputation ordering and categorical imputation failure. A real synthetic
format-16 bundle is scored after its stage cache is removed, with CLI/engine/saved-JSON
equality. No personal export or new reference payload is used.

M9.2's original native acceptance passed **2,707 tests, five existing Windows skips**. Forty-seven
new synthetic cases cover this milestone. All four strict Windows/Linux × Python
3.11/3.13 type targets, lint/format, fixture reproduction and full card lint pass
(51 cards, 268 renders, 35 dbSNP marker references). The pinned native arithmetic case
includes both fractional haploid X and diploid PAR, low/unknown quality and multiple
ALT alleles; observed matrix/report precision agrees with its analytical controls.

M9.3 owns per-score variant coverage on cards, including before/after denominators,
duplicate terms/probes and exclusion states. The stored term observations provide its
inputs; stage-direct counts still cannot stand in for the original chip. M9.4 owns
reference distributions/percentiles, M9.5 owns study-to-sample ancestry portability and
confidence, and M9.6 owns the calibrated card renderer. Raw sums carry neither a
phenotype point estimate nor an outcome probability; `percentile` is null and portability
is explicitly not computed. Low-quality evidence remains available for those later stages.
See the [M9 review](review_m9_session.md) and [M9.3 entry contract](handoff.md) for saved
evidence compatibility and coverage acceptance requirements.
The reviewed implementation passes **2,726 tests, five existing Windows skips**, including
19 new defect regressions; the same four type targets, lint/format, fixtures and full card
lint pass. No known blocker remains for M9.3.

Sources: [PLINK score semantics](https://www.cog-genomics.org/plink/2.0/score),
[dosage import/storage](https://www.cog-genomics.org/plink/2.0/input),
[report columns](https://www.cog-genomics.org/plink/2.0/formats#sscore),
[X dosage models](https://www.cog-genomics.org/plink/2.0/assoc#xchr-model).
