# Mental-health polygenic cards (M9.8)

M9.8 is accepted as of 2026-10-11. Two public, permissively licensed additive
models are authored and fetched; synthetic shared-engine, bundle, CLI and
dashboard acceptance and full-panel public-stand-in scoring pass. The native
acceptance suite passes 2,873 tests with five existing Windows skips. No personal
export is used.

## Model and release audit

| Card | Public weights | Discovery release | Quoted result |
| --- | --- | --- | --- |
| Schizophrenia | PGS000134 SCZ_GHS, 830,589 rows | 2014 PGC-based PRS-CS, phi=1, European 1000 Genomes LD. Catalogue source N=87,534; 94% European / 6% East Asian. | Zheutlin 2019 Table 2: Bayesian highest-versus-lowest decile OR 4.6 (95% CI 2.9–7.3), pooled across four cohort-specific implementations in 106,160 European-American patients. This is explicitly not a per-SD or Geisinger-only estimate. |
| Broad mental-health help-seeking | PGS000140 GPpsy, 24,665 rows | UK Biobank-only, European ancestry, Figure 5/catalogue N=332,629; clumping r²<0.1, p-value threshold 0.1. | Cai 2020, Out-of-sample prediction/Figure 7a: full-sample GPpsy Nagelkerke pseudo-R² 0.018, AUC 0.56, predicting major-depression status in independent PGC29 clinical cohorts. |

The [schizophrenia paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC6961974/)
and [depression phenotyping paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC7906795/)
were checked through NCBI's public BioC full-text API. Their text and downloaded
score files remain outside Git. The model headers match
[PGS000134](https://www.pgscatalog.org/score/PGS000134/) and
[PGS000140](https://www.pgscatalog.org/score/PGS000140/).
Both authoritative metadata CSV entries classify as permissive EMBL-EBI default
terms. The harmonized files are pinned by measured bytes/SHA-256 and fetched
through the reference fetcher, with lock records.

The 23andMe restriction is checked per model, rather than attaching a generic
"reduced-N" sentence to every psychiatric score. These are published scoring
models, not newly downloaded restricted summary statistics. SCZ_GHS records its
specific 2014-PGC-based release and catalogue discovery N instead of substituting
the 2014 paper's larger multi-stage headline N. GPpsy is trained on the UK
Biobank stratum; the paper compares a separate 23andMe phenotype, which does
not enter these weights. No 23andMe application, key or restricted cohort
download is needed or used. Future cards built from excluding-23andMe summary
statistics must name their reduced release and N on the card.

## What the associations mean

The schizophrenia model is the Geisinger weight set. Table 2 reports the study's
Bayesian model family across four health systems, whose available variants and
standardization differed. The card keeps that distinction on the published
association context. It reports the study's recorded prevalence alongside the
relative effect: 1.0% in the highest decile, 0.2% in the lowest, and 0.4% in the
remaining 90%. These are retrospectively recorded diagnoses over unequal
observation periods, not lifetime probabilities or a calibration of a reader's
score. The published population comparison is not the 1000 Genomes reference
comparison displayed by the application.

GPpsy is a score for reporting a GP consultation for nerves, anxiety, tension
or depression. It is not a strictly phenotyped major-depression diagnosis score.
The primary paper attributes its prediction advantage to sample size, rather
than specificity for depression. The catalogue performance mapping differs
from the paper's model-specific results; the card uses the primary paper's
explicit full-sample GPpsy result at threshold 0.1, not a downsampled result or
the catalogue's differently mapped entry.

Nagelkerke pseudo-R² is a bounded model-fit ratio: the Cox-Snell fit index divided
by its maximum. The existing `proportion` evidence measure records that ratio
with its numerator, denominator and name in the context. It is not labelled
as biological variance explained, the proportion of patients affected, or a
personal risk. The published AUC is stated separately. No new effect measure,
knowledge schema or bundle format is introduced.

Neither paper supplies a complete matched ten-decile absolute-outcome series
for these selected weights, so neither card invents `decile_outcomes`. No
within-family attenuation is assigned. Its absence stays visible, rather than
borrowing the educational-attainment attenuation for psychiatric phenotypes.
Coverage, imputation quality and ancestry portability remain separate inputs;
all findings stay visible at the resulting reliability tier.

## Acceptance

The synthetic regression sends both shipped card definitions through fabricated
five-row score observations, immutable bundle save/read, CLI JSON and dashboard
routes. It checks the model-specific association context, broad phenotype,
release/N text, unknown calibration and within-family evidence, and both charts.

Full-panel acceptance passes against both fetched models. It reuses M9.7's
completed default-on imputation of a public European-ancestry stand-in, then
scores a second public East Asian stand-in under explicit `--no-impute` semantics.
Every source row, exclusion state and native dose proof is retained. Card
reload validation recomputes coverage, distribution, portability and confidence.
Artifacts and resource measurements are outside Git. Both stand-ins are panel
members: this checks execution and ancestry handling, not predictive calibration.

Observed four-worker cold reference preparation took 4,537.82 seconds, with
3,737,554,944 bytes peak process-tree working set. SCZ_GHS resolved 830,588
reference rows; one source harmonization mismatch was ineligible for extraction.
GPpsy resolved 21,243 rows, with 3,417 strand-ambiguous and one allele mismatch;
four other source rows were ineligible for extraction. These are global source
states, not an individual's coverage.

| Model | Default-imputed scoring, saved validation and write (seconds) | Peak tree working-set bytes | Complete record bytes | Explicit no-impute check (seconds) | No-impute peak bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| SCZ_GHS | 4,372.92 | 10,176,933,888 | 1,847,470,924 | 245.37 | 5,369,671,680 |
| GPpsy | 3,687.74 | 2,537,885,696 | 79,694,199 | 9.76 | 833,527,808 |

Measurements include the complete private evidence path; these are observed
workstation resource costs, not isolated benchmarks or predictive validation.
No term truncation or format change was needed. The pre-review M9.8 native suite passed
2,873 tests with five existing Windows skips in 737.42 seconds. Full dbSNP lint
passed 55 cards, 276 renders and all 35 authored marker keys; strict Windows
Python 3.13 checked 200 source files.

The requested [session diff review](review_m97_m98_session.md) independently
rechecked the model-specific primary-paper results and corrected frozen reference
copy-allocation validation. Final reviewed validation passes **2,875 tests,
five existing Windows skips** in 1,416.58 seconds, all four strict type targets
(200 files), full card lint, formatting, fixture reproduction and staged privacy
scanning. M9.9 psychometrics is the next sequential open step.
