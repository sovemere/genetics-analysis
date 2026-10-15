# M10.2 session diff review

Scope: implementation commit `c519c08` against `ae9ada6`, covering the sample
caller, bundle/pipeline integration, CLI, dashboard and handoff. All reproductions
use fabricated references and synthetic observations. No consumer export is read.

## Reproduced defects and corrections

1. **PGx dosages were not bound to the saved native evidence.**
   Internally consistent PGx records could change genotype or DR2, omit a record,
   or duplicate it while the full imputation snapshot retained different evidence.
   The writer accepted all four cases. A reader also accepted a changed PGx record
   after its derived results and manifest digest were refreshed. Writes and reads
   now compare every requested locus's complete dosage records with the independent
   saved native payload, including direct records, quality and duplicate counts.
   Unavailable stages do not consume a dosage stream. The healthy control reloads
   after stage caches are deleted.
   Original probe presence, eligible direct genotypes and no-call provenance are
   also checked. A no-call cannot be promoted to a direct observation. Complemented
   native calls are compared in recorded original orientation, and one-copy calls
   against the array's doubled representation.

2. **Malformed frequencies could pass or escape as uncategorized exceptions.**
   Impossible homozygote counts and alternate totals were accepted. Empty population
   labels, invalid vectors and a missing filter raised errors during derivation,
   before the caller's validation boundary. Public record fields, vector lengths,
   scalar types, population labels, frequency/count agreement, alternate totals and
   homozygote counts are now validated before use. Calling failures remain categorical
   `CallingError` messages; they do not echo observations.

3. **Equal alleles could claim a heterozygous haploid call status.**
   The saved probe validator checked doubled hemizygosity but not the inverse
   contradiction. It now rejects an equal pair marked `het_haploid`.

4. **A damaged PGx reference was classified as an imputation failure.**
   Preparation propagated the shared `ProcessError`, which `genetics run` categorizes
   as imputation. The PGx stage now wraps reference failures as `CallingError`,
   preserving the public-reference explanation and the `pgx` error category.

5. **Unresolved constraints named the wrong candidate allele.**
   The detail table numbered entries in the unresolved-only dictionary. If only the
   second allele was unresolved, it displayed "for allele 1". The display now follows
   the definition-ID join to the actual source allele name.

6. **PGx faces did not use the existing reliability styles.**
   The new `cardface` class had no stylesheet rule. Faces now use the established
   `card` and `tier` classes, including artifact borders and badges. Rendered-response
   regressions check the style hooks and the numeric rare-call benchmark. This is
   server-rendered verification, not a claim of interactive browser inspection.

Sixteen regressions reproduced failures before correction; four further controls
verify diploid/haploid and as-written/complemented original calls. The source
reference contract, sample schema 1, bundle format 19 and healthy calling results
remain unchanged. M9.13 confidence arithmetic and all reference pins are untouched.

## Validation

The complete native suite passed **3,202 tests, five existing Windows skips**
in **690.90 seconds**, before the final original-probe binding follow-up. The
follow-up's two rejecting regressions and four ploidy/orientation controls pass.
Pinned native tools are enabled, with Java 17 available for Beagle. After the
follow-up, all **399 affected PGx, bundle, pipeline, saved-imputation and dashboard
tests pass in 143.17 seconds**. Together these runs cover **3,208 unique passing
tests**, with the five existing Windows skips; this is not a second full-suite run
after the follow-up.

All four strict Windows/Linux × Python 3.11/3.13 targets pass (212 files).
Repository lint/format and whitespace checks pass; complete card lint passes
69 cards/320 renders/39 resolved keys, and synthetic fixtures reproduce.
The pre-commit hook also verifies fixture reproduction, staged privacy, the
privacy suite and repository style before this review is committed.

An offline full-source acceptance compared the original implementation from
`c519c08` with the corrected caller using the same seeded synthetic observations
and public frequencies. Their canonical results are identical; the corrected
schema-1 validator also accepts the original JSON roundtrip. All eight genes
survive. Including checksum verification of the pinned 63 GB frequency source,
this passed in **274.26 seconds**. No personal export or reference payload is
included in the commit.

## Next-step handoff

M10.3 remains next: reuse `cyp2d6_structural_variation`, already authored in
`knowledge/impossibilities/structural_variants.yaml`. Its section assignment is
already pharmacogenomics; the remaining work is consistent placement beside the
eight-gene calls on the overview and gene-detail routes, including grouping/filter
choices, unavailable stages and historical/nonstandard packs. Do not author a
second card or infer CYP2D6 from its SNP definitions. M10.4 owns later guideline-linked
interpretation; this review adds no dosing claims. See the
[current handoff](handoff.md#next-open-step-m103-cyp2d6-placement).
