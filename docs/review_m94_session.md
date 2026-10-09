# M9.3–M9.4 diff review

I reviewed `c723e74..78f6db5` on 2026-10-09. That range covers:

- M9.3 per-score coverage: `pgs/coverage.py`, the schema-2 results and `genetics pgs
  coverage`.
- M9.4 reference distributions: `pgs/reference.py`, the shared `orient()` and matrix
  helpers in `pgs/engine.py`, `place_among_reference_populations`, the schema-3 results
  and `genetics pgs placement`.
- The workflow and CLI wiring, the tests, the ignore rules and the docs.

Review probes used only fabricated observations and public reference data. No personal
export or private run was opened.

## Findings and fixes

| Finding | Resulting behavior |
| --- | --- |
| The reference panel was discovered, checked against its lock and extracted only after ingest, ancestry and default-on imputation. A tampered or unlocked panel VCF therefore failed hours into a run, and a personal export had already been read. | `prepare_reference()` does all panel work, which is public, before any personal input. Both workflows call it first. A digest mismatch now fails before `ingest`/`read_bundle`. An absent panel still records `not_run`. |
| `attach_reference` left the private workspace it created behind. That workspace holds PLINK reports of the person's comparable sums. | When the function creates its own workspace, it removes it after scoring, including when scoring fails. A failed removal raises a genotype-free `PgsError`. A caller-supplied workspace is left alone. |
| A prepared reference was not tied to the score it was attached to. | Before attaching, the extraction key (score fingerprint plus panel lock digests) is recalculated and must match. |
| `read_placement` let structural damage (a missing key or the wrong type) escape as `KeyError`/`TypeError`. It also accepted a phase block that disagreed with the score's own phase state: an `unavailable` block for a phase that had a sum, or a percentile on a phase that was disabled. | Structural errors become the categorical refusal. An `unavailable` block must match the score's phase status and reason exactly and carry no percentile. Every other block must belong to a phase that has a sum. |

All **6 new regression cases** fail on the pre-fix code and pass after the fixes:

- the panel check runs before personal input, for both the export and saved-run
  workflows;
- the private workspace is removed;
- a prepared reference from a different score is refused;
- three malformed or contradictory phase blocks are refused.

## Real-data checks this review added

Earlier acceptance never exercised two paths on real data. Both now have been:

- **The "placed" group path.** I built five stand-in people from public 1000 Genomes
  samples' own genotypes, one per super-population, keeping a random 70% of the PCA
  markers. Each was placed in its true super-population:
  - HG00096 (GBR): placed CEU, EUR
  - HG00403 (CHS): placed CHS, EAS
  - HG00551 (PUR): placed PUR, AMR
  - HG01583 (PJL): placed PJL, SAS
  - HG01879 (ACB): placed ASW, AFR

  Population-level calls land on the true population or its nearest neighbour, which is
  why the super-population is the primary group. These samples are part of the panel, so
  this is a smoke test of the wiring, not a held-out calibration.
- **Parallel extraction through the real `genetics.exe`.** I scored the public PGS000001
  against a synthetic fixture export with `--no-impute`.
  - Windows spawn workers ran under the console executable, and the panel was extracted
    before ingest.
  - The cold run took 3 min 52 s; with the cache warm it took 12 s.
  - `pgs placement` and `pgs coverage` revalidated the saved schema-3 result.

## Retained behavior

These are unchanged:

- M9.2 raw sums and the M9.3 coverage contract;
- the shared allele-orientation rule;
- palindromic exclusion from reference comparisons;
- the pooled `ancestry_matched: false` fallback;
- a percentile interval that reflects only the size of the reference group.

Score artifacts stay at schema 3 and run bundles at format 16.

## Validation

- The full offline native suite passes **2,772 tests, five existing Windows skips**, with
  pinned PLINK 2/PLINK 1.9/Beagle/bref3 tools and Java 17.
- All four strict type targets pass.
- Lint/format, fixture reproduction, full dbSNP card lint (51 cards, 268 renders) and
  staged privacy scanning pass.
