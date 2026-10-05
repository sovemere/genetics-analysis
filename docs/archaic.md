# Archaic allele-sharing ranges (M6.3)

`genetics run` evaluates both archaic cards in the genome-structure section when the
knowledge pack includes them. Fetch references with `genetics refs fetch --only aadr`.
The engine uses AADR v66.p1 HO's diploid high-coverage Altai, Vindija and Denisova
individuals, chimp, and HGDP `.DG` Mbuti/Han individuals. HO duplicates and the
Denisova11 hybrid are not pooled into these references. No new native dependency is
required on Windows. All computation is local after fetching.

The Neanderthal ratio is `f4(X,Mbuti;Altai,Chimp) / f4(Vindija,Mbuti;Altai,Chimp)`.
Following [Prüfer 2017, supplement S8](https://www.eva.mpg.de/documents/AAAS/Pruefer_High-coverage_Science_2017_Suppl_2486633.pdf),
the primary filter keeps Denisova homozygous for the chimp allele to reduce Denisovan
confounding. All SNPs and transversions are separate sensitivity diagnostics.
The Denisovan ratio is `f4(Mbuti,Vindija;Han,X) / f4(Mbuti,Vindija;Han,Denisova)`
from [Bergström 2020's supplement](https://reich.hms.harvard.edu/sites/reich.hms.harvard.edu/files/inline-files/aay5012-Bergstrom-SM.pdf).
That model assumes comparable Neanderthal ancestry in Han and the target and a
negligible Denisovan baseline in Han. Its population-specific assumptions are displayed
even when a statistic can be computed elsewhere.

Only exact forward-strand biallelic autosomal SNP matches enter. No-calls, indels,
incompatible alleles and duplicated coordinates are excluded and counted. Each
population needs at least five reference individuals, with 80% called at a site.
Both terms of each ratio use the same sites and calls. No strand guessing or imputed
calls enter. Absent files produce visible `not_run` cards; malformed files fail loudly.
The reader checks companion-file counts and identifier hashes, and records SHA-256
digests of all three input files in the immutable result.

The weighted delete-m jackknife follows [Patterson's equations](https://reich.hms.harvard.edu/sites/reich.hms.harvard.edu/files/inline-files/wjack.pdf).
Weights count sites where either ratio term is nonzero. Blocks are 5 Mb per chromosome,
as in the physical-block default of [popstats](https://github.com/pontussk/popstats).
Each diagnostic needs 2,000 informative sites, 20 blocks and ten chromosomes. These
are explicit observability policies, not empirically calibrated accuracy thresholds.
A zero denominator, a leave-block-out zero denominator, or a denominator interval
including zero produces an unavailable result, never a numeric zero. The reported
range is the outer envelope of available approximate 95% sampling intervals, centred
on the bias-corrected ratios. If the primary diagnostic fails, there is no headline
range even when another diagnostic succeeds. Negative bounds are preserved.

The headline gives a range rounded outwards to 0.1 percentage point, not a precise
point estimate. Reliability has a computed `limited` ceiling because chip/population
calibration and original sequence-quality masks are absent. The range quantifies
sampling and filter sensitivity; it **does not bound array ascertainment or model
error** and is **not a measured genome-wide archaic DNA percentage**. There is no
segment calling, inferred trait effect, or comparison percentile. Bundle format
**5 introduced** each diagnostic, counts, formula, settings, assumptions and reference hashes;
`genetics runs show --json` and the dashboard read that same record. Older bundles
remain readable. New runs now use **format 9**, which also carries sex-chromosome
profiles and ClinVar frequency calibration. The saved archaic reader requires the complete recorded
policy, named archaic genomes and baseline individuals, reference version/quality,
input digests and caveats.
Serialized results copy nested metadata, so editing an export cannot change its source
measurement or the other lineage's saved result.
