# Long autosomal runs of homozygosity (M6.1)

`genetics roh --input <export> --output <outside-repo>/result.roh.json` calls
the shared `genetics.structure.roh.compute_roh` engine. The default references are
the 22 already-fetched 1000 Genomes phase 3 GRCh37 autosomal VCFs. This is a separate
computation command; **M6.1 is complete**, including the diff-driven review pass.
M6.2 owns its interpretation card and dashboard integration.

Install the pinned native tools with `genetics tools install --only plink19` and
`genetics tools install --only plink2`. PLINK 2 does not implement `--homozyg`.
PLINK 1.9 does; the September 23, 2026 stable build is checksum-pinned in
`data/tools.yaml`. PLINK 2 handles conversion, reference filtering and pruning.

## Reference selection

Do not feed this command the ancestry PCA subset: PCA exclusions and pruning were
chosen for a different statistic. Each input must be an **unpruned, diploid GRCh37
reference cohort**, not the subject's pgen. The engine requires at least 50 cohort
members. It intersects array positions, excludes non-SNP and strand-ambiguous sites,
requires reference MAF >= 0.05 and reference missingness <= 0.02, then prunes LD in
500 kb windows, step 1, r-squared 0.2. Filtering never uses allele frequencies or LD
estimated from the subject. Duplicate reference positions and overlapping analyzed
chromosomes fail explicitly. An empty filtered intersection, a sub-window intersection,
or an intersection that cannot be harmonized is recorded as unavailable for that
reference; it does not abort usable results from other chromosomes. Malformed reference
files and other native errors still fail. A filter that leaves no variants may stop
before the selected cohort size can be measured; that count is then null, not guessed. Unresolved array calls remain missing or are excluded by the
existing harmonizer; alleles are never filled from the reference.

The default uses pooled 1000G frequencies and LD, **not an ancestry-matched cohort**.
That limitation is recorded in the output. Use `--keep <PLINK-sample-list>` with
`--population <label>` for a selected reference population of at least 50 samples.
For another panel, repeat `--reference <cohort.vcf.gz-or-pgen>` and supply
`--reference-version` and `--population`. The caller is responsible for the panel's
GRCh37 build and diploid/unrelated sample selection; filenames cannot prove those facts.
Input SHA256 digests, selected-sample file digest, versions, cohort sizes, retained
marker digests, tool versions and parameters are recorded in the result. Hashes are
keyed by input role (`vcf`, or `pgen`/`pvar`/`psam`, plus optional `keep`), so identical
filenames in different directories cannot overwrite provenance. Per-reference status
and harmonization counts distinguish absent coverage from excluded calls.

## Parameter policy

This first policy targets **long runs (at least 5 Mb)** on a ~677k consumer array,
after substantial reference filtering. It does not claim sensitivity to short ROH.
All native settings are explicit and can be overridden through `--settings <JSON>`.
Fractions must be finite numbers, not JSON booleans. A zero reference-missingness
threshold is valid and requires completely called reference markers:

| Setting | Value | Reason |
|---|---:|---|
| Minimum length | 5,000 kb | Restrict interpretation to long runs supported by array density |
| Minimum markers | 50 | Require substantial independent marker support after pruning |
| Maximum inverse density | 100 kb/SNP | At least 50 markers across a 5 Mb run |
| Maximum internal gap | 500 kb | Do not bridge long unobserved regions or centromeric gaps |
| Maximum heterozygotes per run | 1 | Explicit error tolerance; avoid PLINK's unlimited default |
| Scanning window | 50 SNPs | Match the minimum support count |
| Window heterozygotes / missing | 1 / 2 | Limited chip-error tolerance without imputing calls |
| Window hit threshold | 0.05 | PLINK scanning eligibility rule, explicitly recorded |

These are an engineering policy, not a universal optimum or clinical calibration.
Synthetic planted runs test detection, interruptions, missingness and gap behavior
against the real pinned binary. Population and chip-specific sensitivity still need
empirical calibration before the M6.2 interpretation claims can be established.
Native flag semantics and inclusive segment lengths are documented in the
[PLINK 1.9 ROH manual](https://www.cog-genomics.org/plink/1.9/ibd#homozyg).

## Denominator and coverage

`F_ROH = total_roh_bp / denominator_bp`. The denominator is the sum of **assayed**
autosomal marker spans, broken at gaps larger than 500 kb, retaining blocks with at
least 50 markers and length >=5 Mb under the default settings. Coordinates and lengths
are **1-based inclusive**. Unobserved chromosome ends and large gaps contribute to
neither numerator nor denominator. Density is checked on each ROH, not on an entire
denominator block: a sparse block can contain a dense callable run. A denominator
block is an assay span, not a claim that every part of it was observable.

This is an **observed long-ROH fraction of the assay**, not a whole-genome inbreeding
coefficient or an estimate corrected for missing calls. It should not be compared
unqualified across chips or filtering policies. The result includes intervals,
chromosomes assayed, missing-call count, array/retained/analyzed marker counts,
total length, count and longest run.

Schema **2** adds per-interval `window_support`. Within eligible denominator blocks,
it counts contiguous windows meeting the configured density bound and then those
also meeting the window-missingness bound. Heterozygotes count as observed calls;
the diagnostic does not select regions for their homozygosity. This is a check for
potential support, not a claim that a ROH exists. Actual native segments take
precedence over the conservative fixed-window diagnostic for custom settings.

No eligible span or density-supported window yields `insufficient_coverage` and
`f_roh: null`. Density-supported windows without sufficient local calls yield
`insufficient_calls` and `f_roh: null`. A large genome-wide called-marker count cannot
substitute for a usable local window, and calls outside denominator blocks do not
establish support within them.

When some blocks are usable and others are not, findings and the assay denominator
remain visible. The result explicitly warns that the observed fraction can underestimate
ROH in unobservable regions; per-block counts identify the unsupported spans. A numeric
zero means no run met the policy in a result with some window support. It does not
exclude shorter or poorly covered runs. Schema 1 used a genome-wide count for this
check; rerun those results to obtain the corrected observability status.

## Storage and execution

Scratch directories default to the OS user-data cache outside the checkout. A unique
temporary directory is cleaned on normal completion and Python exceptions. Abrupt
process termination can leave scratch files there; they are never reused as a cache.
Each reference is read and pruned afresh, with progress on stderr. This initial engine
does not resume interrupted chromosome work. Full-reference reads and hashing may
take substantial time. No network request occurs during computation.

JSON stdout is intentional for agents; use `--output` to keep personal results in a
file outside the repository. Invalid vendor exports are reported as normal CLI errors.
Saving first writes and flushes a temporary `.roh-pending-*.roh.json` sibling, then
publishes the complete file with an atomic, no-overwrite hard link. This requires
hard-link support (including NTFS and ordinary Linux filesystems); unsupported targets
fail without a final result file. Concurrent writers cannot replace an existing result.
A failed write removes its staging file; abrupt termination may leave a visibly pending
file, never a truncated final result. `.hom`, `.hom.*`, `.roh.json` and pruning outputs are
gitignored. Results and even their aggregate lengths must never be committed.
