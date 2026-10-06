# Sex chromosome call patterns (M6.4)

`genetics run` computes `sex_chromosome_call_pattern` in genome structure from
the normalized direct calls. It needs no reference download or external tool.
The CLI and dashboard read the same saved result, including denominators, PAR
exclusions, thresholds and caveats. No new output file is created: the measurement
lives in the existing private `cards.run.json` payload, introduced in bundle format 6.
New runs use format **11**. Versions 1–10 remain readable without reinterpreting their
saved QC or cards; formats 1–5 predate the saved sex-chromosome profile.
Saved profiles are validated against their recorded thresholds and the structured
direct-call, intensity and karyotype flags. Changing current display wording or source-link
wording does not invalidate an older profile. Exported results and recorded settings copy
nested metadata so edits cannot change the source measurement or the engine defaults.

The card face gives non-PAR X SNP heterozygosity and non-PAR Y probe call rate,
with limited reliability and an explicit statement that this is not a karyotype.
Disagreement remains visible and leaves X/Y ploidy unresolved. Intermediate signals
do likewise. Missing X calls and layouts with no Y probes remain visible; absent
probes are not evidence that a chromosome is absent.

## Measurements and ploidy

X heterozygosity is heterozygous SNP calls divided by called SNP probes. No-calls
and indels are excluded. Y call rate is called probes divided by assayed probes;
called indels count toward Y call rate, as in QC. Y SNP heterozygosity is reported
separately. Repeated probes remain in both rates, matching ingest/QC; duplicate
counts and a warning make the possible overweighting explicit. These are probe
fractions, not independent observations, calibrated probabilities or PLINK F values.

QC's existing broad cutoffs are recorded: X <=0.05 with Y >=0.30 gives the `male`
ploidy assumption; X >=0.15 with Y <=0.15 gives `female`. Other combinations remain
`ambiguous`. Fewer than 100 usable X SNPs gives `insufficient_calls`; the actual
counts still render. With no non-PAR Y probes, QC uses X alone and the card says
so. The reporting card additionally warns about fewer than 100 Y probes; that is
a transparency warning, not a newly validated Y-count threshold or a change to
the existing QC inference rule. Thresholds have no chip/population calibration.

Vendor-labelled PAR and coordinate-defined PAR on X or Y are excluded from both
measurements and remain diploid under all QC ploidy assumptions. The shared mask
uses these **1-based inclusive GRCh37** boundaries from the
[Genome Reference Consortium](https://www.ncbi.nlm.nih.gov/grc/human), assembly
GCF_000001405.13:

| Region | X | Y |
| --- | --- | --- |
| PAR1 | 60,001-2,699,520 | 10,001-2,649,520 |
| PAR2 | 154,931,044-155,260,560 | 59,034,050-59,363,566 |

This fixes layouts that label PAR probes X/Y rather than PAR, including the
unverified 23andMe-like adapter. Labels and alleles are preserved at ingest.
The boundaries are assembly definitions, not an imported genotype reference panel.

## What this can establish

The result establishes the observed call pattern and the engine's ploidy
assumption. It does not establish XX/XY, XXY, XYY, chromosome loss, mosaicism,
gender or reproductive phenotype. No aneuploidy probability or phenotype risk is
computed. Missingness, homozygosity, ancestry, errors, cross-hybridisation and mixed
samples can alter the pattern; a discordant profile has no unique explanation.

[Zhao et al. 2022](https://doi.org/10.1016/j.gim.2022.05.011) examined 207,067
European-ancestry UK Biobank men aged 40-70 using probe intensity and sequencing
information to detect and characterize sex-chromosome abnormalities. This raw
export supplies neither intensity nor copy-number measurements. The citation
supports that assay distinction, not the accuracy of our export-only thresholds.
[PLINK's sex-check documentation](https://www.cog-genomics.org/plink/1.9/basic_stats)
also emphasizes PAR exclusion and the allele-frequency and LD requirements for
its X F statistic; this card uses descriptive heterozygosity rather than that statistic.

## Verification and privacy

Tests use fixed-seed frequency-derived synthetic calls and controlled distortions
to check both agreeing profiles, discordant profiles, threshold edges, missing
signals, sparse panels, indels, duplicates, Y heterozygotes and all four inclusive
PAR endpoints. They check agreement with QC, saved CLI/dashboard output, immutable
reloads, rejection of inconsistent stored measurements and safe result reprs.
These rates and counts are personal genome-derived data: store runs outside the
repository and never commit or send the measurements to remote services.
