# Common-variant health cards (M7.5)

`knowledge/health/` adds authored disease-association cards alongside the separate
ClinVar reference lookup and ACMG roster overlaps. All three use the shared card engine,
frequency calibration, private run bundles, CLI and dashboard. No personal export is
needed to validate this milestone; all acceptance calls are fabricated.

Each matched outcome carries `risk_context`: published absolute outcome rates and their
population/strata/horizon, or a precise statement that no applicable estimate is assigned.
Missing baselines are stated explicitly. There is no OR-to-risk conversion, PPV-to-disease
conversion, demographic inference or unsolicited treatment advice. The evidence block's
cohort comparison is labelled with the genotype it describes; it is not a per-allele
multiplier for every outcome. Allele frequency describes measurement reliability, not
disease prevalence. Low-confidence and likely-artifact cards remain visible.

The HFE card covers C282Y only, with the sex-specific documented iron-overload disease
proportions from [Allen 2008](https://doi.org/10.1056/NEJMoa073286). It preserves the
endpoint and distinguishes cohort observation from untreated/lifetime penetrance.
One-copy results do not resolve H63D compound heterozygosity; no-copy results do not
exclude iron overload. [Feder 1996](https://doi.org/10.1038/ng0896-399) supports the
variant association; [Pilling 2019](https://doi.org/10.1136/bmj.k5222) provides independent
cohort evidence, with different endpoints and ascertainment.

Factor V Leiden uses the exposure-stratified 10-year cohort estimates from
[Juul 2004](https://doi.org/10.7326/0003-4819-140-5-200403020-00008), retaining the wide
homozygote intervals and the unprovided numerical noncarrier baselines in its abstract.
[Bertina 1994](https://doi.org/10.1038/369064a0) provides the functional evidence.
**GRCh37's reference base at rs6025 is T, already the Leiden allele; C is non-Leiden.**
The transcript convention runs on the opposite strand, and GRCh38 has a different
reference state. Public dbSNP and ClinVar records and full local dbSNP lint verify the
coordinate/allele representation. Reference/alternate alone cannot select the risk allele.
Both HFE and F5 loci are multiallelic in dbSNP. Their schema-2 matches declare
`strand: forward_only`, so another alternate cannot be complemented into a C282Y or
Leiden claim. Unexpected bases remain visible allele mismatches. Other existing cards'
strand-inference behavior is unchanged.

APOE requires rs429358 **and** rs7412. Schema v2 declares all four SNP haplotypes and
all ten unordered diplotypes. The matcher enumerates compatible pairs without a prior.
Double heterozygotes fit both e2/e4 and e3/e3r: phase stays unresolved and neither risk
model is assigned. [Seripa 2011](https://doi.org/10.1089/rej.2011.1169) documents e3r;
rarity cannot justify removing it. e3r-containing patterns stay visible with no disease
rate, and the SNP reliability tier does not calibrate rare-haplotype frequency.

The numeric APOE absolute rates transcribed here are the e4/e4 age/sex-specific estimates
from [Rasmussen 2018](https://doi.org/10.1503/cmaj.180066), preserving competing mortality,
white-Danish population and the distinction between Alzheimer disease and all dementia.
The other common-pattern outcomes use [Farrer 1997](https://doi.org/10.1001/jama.1997.03550160069041)
for relative association context. Its case-control sampling supplies no calibrated
forecast baseline. Rasmussen also plots the other common genotypes, but these curves
and the e3/e3 baseline are not numerically transcribed in this pack; the card says so.
No age/sex stratum is chosen for a person, and none of the cohort rates is a personal
probability. Extending numerical curve transcription requires source verification.

Bundle format **11** saves literal risk context and the multi-marker definition,
observations, phase candidates and locus-specific calibration. Scalar fields remain
empty for multi-marker observations. Saved validation checks the recorded definitions
and weakest-marker aggregation without consulting today's knowledge pack or rescoring
old confidence. Formats 1–10 and ClinVar schemas 1–4 retain their original meanings.

Synthetic tests cover the complete two-marker observation space, the fourth haplotype,
missing/discordant/complemented/non-diploid calls, rarity and missing-frequency gates,
per-marker imputation quality, damaged snapshots, old scalar bundles and saved CLI/UI
parity. M7.6 still owns quantitative ClinVar/chip coverage; M8 owns actual phasing and
imputation, and M9.5 owns study-to-sample ancestry calibration.
