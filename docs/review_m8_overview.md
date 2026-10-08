# M8 overview review and M9.1 handoff

Reviewed M8.1–M8.7 from `f1c492a` on 2026-10-08. The pass follows reference
preparation, native Beagle execution/reuse, target harmonization and ploidy,
dosage/quality propagation, default-on analysis, full snapshot publication/readers,
CLI/dashboard views and the effect-allele interface for M9. Inputs are generated or
fabricated synthetic boundaries; no personal export was opened.

## Findings and fixes

1. **Saved scalar imputed cards could bypass rarity.** The reader checked dosage
   quality ceilings but did not bind the selected allele frequency to observed
   alleles and confidence inputs, enforce its rarity ceiling, or bind the oriented
   hard call to the reference-oriented observation. An edited/rehashed scalar card
   could upgrade a rare finding, select its common companion, erase the selected
   frequency, change the confidence input or claim a different oriented call.
   Saved validation now shares live assembly's observed-allele selector and checks
   these bindings, including incomplete coverage and unknown-frequency ceilings.
   It does not recompute the weighted confidence score with today's model.
2. **Missing alleles were accepted as allele identities.** `.` could enter native
   output/saved dosage REF and the public quality contract's REF/ALT fields.
   These placeholders now fail explicitly. Complete multiallelic and
   sequence-resolved indel alleles remain supported by the native dosage layer.
3. **Skipped-region ploidy was not bound to recorded sex.** Only computed jobs had
   their full region identity checked. An empty/skipped autosomal region could
   claim haploid scope, or a male X region could claim unresolved ploidy. Every
   region report now agrees with its chromosome and saved inferred sex, including
   zero-job stages. Positive controls retain valid skipped autosomal/X reports.
4. **The phase handoff checked the hash but not byte count.** The second invocation
   could record a target size different from its phase output while retaining the
   same fingerprint. Both recorded hash and size must now agree.
5. **Malformed saved Beagle options escaped the bundle error boundary.** Invalid
   stage/phase/imputation options raised `BeagleError`, bypassing the categorical
   snapshot failure expected by the bundle reader/writer. Both publication and
   validation now translate it; failed publication leaves no completed bundle.
6. **Invalid DEFLATE blocks escaped native error handlers.** A corrupt gzip target
   or Beagle output could raise raw `zlib.error` during target-header reading,
   publication, resumed-output validation or dosage decoding. These paths now
   report the appropriate private Beagle/imputation error. Failed jobs can restart;
   corrupted completed jobs are refused even after their recorded digest is updated.
7. **A dosage removed after opening escaped the iterator's domain error.** The
   saved iterator rehashed the file, but a missing/unreadable payload raised raw IO
   errors. It now raises a categorical `ImputationError`, without exposing paths
   or observations, matching its existing changed-payload behavior.

Thirty new regression/control cases cover these findings. Twenty-eight rejection
cases failed before their respective fixes; two positive controls protect legitimate
skipped regions. The fixes tighten existing contracts: bundle format 16, provenance
schema 1, historical payload meanings, native dosage scales, per-ALT quality, original
array precedence and the default-on/explicit-opt-out policy remain unchanged.

## Validation

**2,591 tests passed, five existing Windows skips**, with pinned native ROH, Beagle,
bref3 and unbref3 tools enabled. All four strict Windows/Linux × Python 3.11/3.13
type targets, ruff/formatting and fixture reproduction pass. Full card lint passes:
51 cards, 268 template renders and 35/35 dbSNP marker references. No personal export
was opened and no new reference payload or tool dependency was introduced.

## M9.1 boundary

M8 supplies execution and validated saved evidence. It does not measure biological
imputation accuracy, calibrate individual imputed-call PPV or implement PGS sums.
The chip confirmation benchmarks remain study-scoped and explicitly uncalibrated
for imputation. QC, ClinVar, chip coverage and genome structure retain original input.

M9.1 should start with the manifest's `pgs_catalog_metadata` source, the pending
`parse_pgs_score_licenses` post-processing step and `refs/licenses.py`. Bind a
scoring file's PGS id to that score's `License/Terms of Use` metadata row, retaining
the metadata/scoring-file identities and declared build. Missing, ambiguous or
unrecognized terms must not default to permissive. The collection-level licence and
a missing scoring-header licence are not substitutes for the metadata row. Check
the current official scoring-format documentation before implementing its columns.

Keep M9.1's parser/licence acceptance separate from M9.2's scoring, M9.3's coverage,
M9.4's distributions and M9.5's ancestry-portability calibration. Test malformed rows,
nonfinite weights, missing fields, conflicting identities/builds and metadata joins
with synthetic inputs; reference downloads do not belong in CI. New derived output
types must be ignored in the same commit and default outside the repository.

M9 consumers should use `RunBundle.iter_dosages()` for saved format-16 stage output.
That stream includes direct, phase-filled and untyped records and is not a complete
original-array table. `ImputationEvidence.from_record()` accepts resolved imputed
records; `allele_dosage()` returns their native dose and its own quality. Direct
records carry exact observed ALT counts, not an imputation-quality estimate.
Unknown phase-filled quality and multiallelic REF quality remain unknown. Do not
filter low DR2, scale doses by quality, average per-ALT DR2 or assume phase.

Before-imputation coverage needs original-array observations or explicitly saved
coverage; stage-direct counts alone cannot reconstruct every original chip marker.
Older bundles without full dosages must not acquire invented observations or coverage.
The pending AADR-population/study-ancestry mapping and the effect of `declined`
ancestry placement belong to M9.5. See [the current handoff](handoff.md).
