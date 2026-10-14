# M9.13 diff-driven review (2026-10-14)

Reviewed `3c13ac9..38afe9c`, including implementation, synthetic tests and the
M10.1 handoff. No personal export, saved personal run or genotype-derived public
artifact was read or created. The source model corpus and confidence policy remain
unchanged; bundle format 18 remains the current contract.

## Findings and fixes

1. **Saved ancestry labels were not bound to retained fits.** The new context
   reader accepted a region from another population, a population absent from
   the fits, a named population above the decline threshold, or a decline despite
   an admissible fit. Four mutation probes all failed to reject before the fix.
   The reader now follows the producer's first-admissible-in-distance-order rule,
   checks population/region, numeric threshold/fit values, optional distance/radius
   consistency and unique labels. Measured format-18 run contexts require their
   retained fits. A closer tight population can be skipped; a zero-radius infinite
   fit remains inadmissible. AADR countries remain unmapped.
2. **Numeric dictionary equality admitted booleans.** `True` was accepted as the
   saved ancestry score 1.0. Recursive comparison now distinguishes boolean and
   numeric types while permitting equivalent integer/decimal JSON spelling.
   Oversized numeric inputs produce a domain refusal rather than overflow.
3. **The new scalar calibration check did not bind alleles to the declared
   variant.** An extra foreign frequency, or a replaced called allele plus an
   equal-valued frequency, passed frozen calibration validation. Both mutation
   probes reproduced the defect before the fix. The validator now checks the
   declared variant, frequency allele membership, sorted call shape and recorded
   strand orientation. Ambiguous readings retain both possible allele readings;
   rarity/quality gates and null selected evidence retain their existing meaning.
4. **Card-detail routes hid a damaged-run refusal.** The bundle/CLI/dashboard
   rejected the malformed record, but the full-page and htmx card detail replaced
   the refusal with a missing-card message. Both detail representations now retain
   the shell's actual run-load error, with autoescaping and empty card output.
   Missing cards in readable runs retain their existing message.

The original seven mutation probes all reproduced acceptance before production
changes. Twenty added cases cover those failures, overflow/type boundaries,
positive placement controls and digest-consistent API/CLI/dashboard/modal refusals.
Two fabricated placement helpers now represent valid producer states: declined
samples sit above the threshold, and the selected PGS population's fit carries its
reported region. The coherent shared-PRS-placement swap still reaches and tests
its independent guard. Historical formats 1–17 retain their original snapshots.

## Next-step handoff audit

M10.1 remains next: source ingestion, allele definitions and phenotype mappings.
The manifest already has optional `pharmgkb` and `cpic` entries; their source
directories are absent locally. PharmGKB's rolling archives require explicit
share-alike opt-in and declare `extract_zip`, whose executor is still pending.
CPIC is declared as two pinned v1.60.0 SQL dumps. The handoff now requires checking
actual payload coverage, GRCh37/strand mappings, source-specific licences and
versioned offline inspection. Annotation archives must not be assumed to provide
complete star-allele definitions merely because the manifest's capability label
says so. CYP2D6's `cyp2d6_structural_variation` card already exists; M10.3 concerns
its placement beside callable diplotypes, as the roadmap explicitly states.

## Validation

The full native suite passes **3,015 tests, five existing Windows skips** in
481.74 seconds, with PLINK 2/1.9, Beagle, bref3/decoder, native PRS checks and
portable Java 17 enabled. The default pinned-tools directory is configured, so
the reference helper that needed a separate recheck at original M9.13 acceptance
passes in the complete run here. All four strict Windows/Linux × Python 3.11/3.13
targets check 203 files. Lint/format, full dbSNP card lint (69 cards, 320 renders,
39/39 keys), byte-identical fixture reproduction and whitespace checks pass.
The focused saved API/CLI/dashboard/card-modal regression suite passes 202 tests.
Staged privacy scanning and the enabled pre-commit privacy hook are required
before publication; only source, synthetic test code and documentation are staged.
No genotype-derived file, reference payload, dependency, model or saved schema
has been added to the public repository. All reproduced findings are fixed.
