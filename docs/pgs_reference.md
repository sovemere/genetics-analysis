# Reference distributions and percentiles (M9.4)

M9.4 places each private score result against a reference distribution. The default
comparison is within the person's ancestry-matched group. The module is
`pgs/reference.py`. Its output is stored in every **schema-3** `.pgs-score.json` as
`reference_distribution`, with the primary percentile for each phase in
`percentile.before` and `percentile.after`. Nothing here estimates a phenotype, and nothing
adjusts for portability; that is M9.5. Rendering is M9.6.

## Commands

```text
genetics pgs score path/to/score.txt.gz --input path/to/export.txt          # on by default
genetics pgs score path/to/score.txt.gz --input path/to/export.txt --no-reference
genetics pgs placement path/to/result.pgs-score.json --json
genetics pgs placement path/to/result.pgs-score.json --scoring-file path/to/score.txt.gz
```

The distribution is calculated by default. `--no-reference` is an explicit opt-out, and
it is recorded as `status: disabled`. If the 1000 Genomes files have not been fetched and
locked, the result records `not_run` along with the fetch command. A file that is present
but does not match its lock digest is treated as wrong and raises an error.
`pgs placement` reloads a result, first runs the M9.3 coverage validation, and then
recalculates every group statistic from the saved sums. It refuses the result if anything
disagrees. A result older than schema 3 reports that it has no distribution; to get one,
score it again.

## The reference panel and the comparison group

The reference is **1000 Genomes phase 3**: 2,504 unrelated samples in 26 populations and
five super-populations. It is the only panel here with genome-wide genotypes. It is also
the panel the person's genotypes were imputed against. The AADR Human Origins panel that
M5.9 places people in carries array markers only, so it cannot supply a polygenic
distribution.

The comparison group comes from placing the person among 1000 Genomes' own populations.
This uses the M5.5 placement and decline machinery, projecting in 1000 Genomes' own PCA
space (`place_among_reference_populations`). It is not a label mapping written from
memory. The groups are:

- **Primary group.** When the person is placed, the primary group is the super-population
  of the named population, as the panel's own `super_pop` column defines it. The
  population itself and the pooled panel are reported alongside it.
- **Fallback.** A person who is declined, cannot be placed, or was scored from a saved run
  (which has no original array to place) is compared with the **pooled** 2,504 samples.
  The result says `ancestry_matched: false` and gives the reason. This is a labelled
  fallback, not a silent one, and M9.5 owns how it affects confidence.

The run's own AADR placement is recorded separately and is unchanged by any of this.

## Same rows, same definition

Each phase compares like with like.

- **Which rows.** Reference samples are scored only over the rows the person's phase
  actually scored *and* the panel can resolve. The person's sum is recalculated over that
  same set (`person_sum`), and the full-phase sum stays where M9.2 put it. Rows dropped
  for comparability are counted by reason in `excluded_for_reference`. The record also
  gives the comparable rows' share of the person's scored weight and of the score's total
  weight.
- **How alleles are matched.** The engine's shared `orient()` rule, used for both the
  person and the reference, matches the score's allele pair to the panel record:
  - It can match as written, or complemented for a non-palindromic SNV.
  - Sequence indels must match exactly.
  - A four-allele locus cannot be oriented.
  - If more than one record at the locus is compatible, the row is ambiguous.
  - A **palindromic** (A/T or C/G) pair is excluded from the reference. A homozygous panel
    call cannot reveal its strand. The person's heterozygous palindromic observation was
    usable only because it reads the same on either strand.
- **Ploidy and missing calls.** Panel ploidy is checked against each sample's recorded sex
  and the GRCh37 PAR boundaries, so males are haploid on non-PAR X and everyone is diploid
  in PAR. A row with any missing or ploidy-inconsistent panel call is excluded.
- **How sums are calculated.** Reference samples go through the **same effect-dose matrix
  encoding and the same PLINK invocation** as the person, with one integer biological dose
  per sample; integers are exact in PGEN. Each report is checked:
  - every reported count and term ID;
  - the cross-sample totals against exact arithmetic;
  - each audited sample's sum, exactly. Every sample is audited unless terms × samples
    exceeds 50M. Above that, a recorded deterministic stride of samples is audited.

## Statistics

For each group the record gives:

- `n`, `mean`, sample `sd`, `min` and `max`;
- quantiles from 1 to 99, using linear interpolation (Hyndman-Fan type 7);
- a 20-bin histogram whose last bin includes the maximum;
- a **mid-rank percentile**: (below + ties/2)/n.

The percentile comes with a **Wilson 95% interval**. That interval reflects only the
finite size of the reference group. Coverage, the dose basis and portability are reported
beside it, not folded in.

`person_dose_basis` records the sources of the comparable rows and the share of absolute
weight that came from imputed dosages. Reference sums are **sequenced hard calls**.
Imputed dosages at low DR2 shrink toward the mean, so a heavily imputed person's sum has
a narrower spread than the reference. This is recorded and not corrected; weighing it is
M9.5's job.

## Cost, caching and privacy

Panel extraction streams each needed chromosome VCF once, in parallel processes, and
verifies the lock's SHA-256 in the same pass. The result is cached under the user-data
cache as `<key>.pgs-reference.tsv.gz`. The key is the public score's identity plus the
panel's lock digests. The cache holds public data only: the public score's rows in the
public panel. A corrupt cache is rebuilt.

For PGS000001 (77 rows, 20 chromosomes), the first run took **228 s** on a 16-core
machine and a cached rerun took **1.3 s**. Large scores scale with row count:

- The reference matrix is held as one byte per sample per comparable row, roughly
  2.5 KB per row.
- Resolving each row is a Python pass over 2,504 calls.

Everything restricted to a person is private and stays in the score result: the
comparable rows, the person's sums, the reference sums over those rows, the placement
coordinates and the percentiles. Temporary matrices are deleted. New ignore patterns
cover the extraction cache and the matrix files.

## Acceptance

`tests/refs/test_pgs_reference.py` has 19 synthetic cases. Together they cover:

- allele and ploidy resolution: as written, complemented, palindromic, absent,
  multi-record, ambiguous, four-allele, missing call, exact indel and mismatch, plus
  haploid male X, an X ploidy conflict and PAR;
- the panel itself: lock/fetch absence, a valid but unlocked rewrite of a VCF, and cache
  reuse and rebuild;
- the statistics, checked by hand;
- the comparison: placed (super-population primary), declined and saved-only (pooled,
  unmatched) people, `not_run`, disabled and unavailable phases, and source mismatch;
- the matrix audit: a wrong sum, a wrong sample set, invalid doses and the audit stride;
- persisted API/CLI equality, seven tamper cases and the schema-2 reader;
- the CLI and workflow flags;
- pinned-native matrix arithmetic.

Mutation checks confirmed that removing each of these breaks a test:

- the palindrome guard
- the ploidy guard
- the group restriction
- the lock-digest check

**Real-panel acceptance**, with a synthetic person only, scored the public PGS000001
against the real 2,504-sample panel:

- 70 of 77 rows resolved. Six are palindromic and one is absent from the panel.
- An **independent** PLINK run scored the raw 1000 Genomes VCFs directly, complementing
  the three rows that needed it.
- Every reference sum agreed to within **8.4 × 10⁻⁶**, which is the six-significant-digit
  report rounding summed over 19 chromosomes.
