# Substance use and behavioural propensity polygenic cards (M9.10)

Three public UK Biobank-only LDpred2-auto HapMap3 models use the existing PRS
engine, knowledge schema 4 and bundle format 17. Smoking exposure, drinking
frequency and broad self-reported addiction remain distinct endpoints. None
establishes current substance use, consumption quantity or a clinical diagnosis.

## Exact models and evidence

The models come from [Prive et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC8764121/).
The authors' [version-2 performance release](https://doi.org/10.6084/m9.figshare.14074760.v2)
contains `pred-cor-ldpred2.csv` (file 31619354). The quoted results below are
its held-out UK-ancestry partial correlations for the exact released models.
Both score and phenotype were residualized on sex, age, birth date, deprivation
index and 16 PCs. Testing within UK Biobank is `same_cohort`, not independent
replication or validation of a consumer array.

| Endpoint / model | Released rows | Phenotype-specific training observations | Held-out UK evaluation N | Partial-r (95% CI) | Derived residual variance explained |
| --- | ---: | ---: | ---: | --- | --- |
| [Ever smoked, PGS002126](https://www.pgscatalog.org/score/PGS002126/) | 931,635 | 389,564: 236,287 cases / 153,277 controls | 19,926 | 0.1431 (0.1295–0.1567) | 2.05% (1.68–2.46%) |
| [Alcohol frequency, PGS002152](https://www.pgscatalog.org/score/PGS002152/) | 946,965 | 390,606 | 19,981 | 0.1645 (0.1509–0.1779) | 2.71% (2.28–3.16%) |
| [Ever addicted, PGS002124](https://www.pgscatalog.org/score/PGS002124/) | 566,292 | 125,617: 7,577 cases / 118,040 controls | 6,380 | 0.0328 (0.0082–0.0573) | 0.11% (0.01–0.33%) |

The [phenotype counts](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/phenotype-info.csv)
and [count export](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/export-info.R)
distinguish nonmissing phenotype counts from the catalogue's 391,124-person
Northwestern European training pool. Binary N is cases plus controls.
Training case fractions are 60.66% for ever smoking and 6.03% for ever addiction.
These are descriptive fractions in selected training participants, not general
population rates, held-out calibration or a reader's probability. The audited
release does not supply corresponding category-specific alcohol baselines.

The existing `percent_variance_explained` effect stores `100*r^2`, rounded to
two decimals. All three correlation intervals are positive, so squaring their
endpoints is monotone. For the binary traits, this describes residual variance
of a coded zero/one outcome, not liability-scale variance, penetrance, an odds
ratio or a proportion of people affected. For alcohol, it describes residual
variance of ordinal category numbers. Approximately 98%, 97% and 99.89%,
respectively, remain unexplained; the very weak addiction finding stays visible.

## Phenotype direction and scope

The authors' pinned [phenotype preparation](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/prepare-pheno-fields.R)
defines the endpoints rather than inferring them from a catalogue ontology:

- [Field 20160](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=20160)
  includes trying tobacco once or twice, past smoking and current smoking.
  It is broader than regular-smoking initiation and does not measure dependence.
- [Field 1558](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=1558)
  retains [coding 100402](https://biobank.ndph.ox.ac.uk/showcase/coding.cgi?id=100402):
  daily/almost daily is 1 and never is 6. The released `less_alcohol` score
  therefore associates higher values with **less frequent drinking**. We keep
  its weight direction and state it on the face; no drinks/week conversion or
  equal spacing of frequency categories is inferred.
- [Field 20401](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=20401)
  asks about self-reported substance or behavioural addiction, including gambling,
  and explicitly excludes cigarettes and coffee. It combines heterogeneous
  experiences and cannot identify the substance/behaviour, severity or a
  clinically diagnosed disorder. Questionnaire participation and disclosure
  limit interpretation of the observed case fraction.

No model-specific within-family attenuation or complete matched absolute
ten-decile outcome series is provided by the audited release. The cards leave
those quantities absent, with the existing engine stating unknown direct
effects and uncalibrated risk on every face. No educational-attainment
attenuation is borrowed, no section confirmation gate is added, and no
low-confidence finding is suppressed.

## GSCAN release audit and selection

The roadmap's GSCAN excluding-23andMe sample sizes are corpus context, not
sample sizes for these three UK Biobank-only models. No restricted 23andMe
data enter the selected weights.

The alternative public GSCAN models PGS003360 (regular-smoking initiation),
PGS003368 (cigarettes/day) and PGS003376 (drinks/week) were investigated.
[Saunders et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9771818/)
and the authors' [release README](https://conservancy.umn.edu/server/api/core/bitstreams/61227ddd-1e1a-417f-ae7b-fc2d29533fc9/content)
confirm that public PRS weights exclude 23andMe. However, the supplementary
score-construction methods describe discovery statistics from all studies
except Add Health. We could not establish that Supplementary Table 12b's
performance evaluates the exact excluding-23andMe weights. Its tested variant
counts also differ from the public files. We therefore do not assign those
results or the paper's 3.4-million-person headline to a public-release card.
This is an evidence-binding choice, not a compute-cost shortcut or a claim
that the selected models are universally better predictors.

Two other catalogue traps reinforce the need to check primary evidence:
Table 12b labels smoking's coefficient as **log-OR**, whereas the catalogue
calls the same number OR; Table 12a gives phenotype-specific evaluation N
instead of the catalogue's generic ancestry-cohort N. For example, EUR
phenotype N is 5,994 for initiation, 2,484 for cigarettes/day and 4,609 for
drinks/week, not 6,092 for each. These audited GSCAN numbers are not used to
calibrate any selected UK Biobank model. Future additions need matched public
release evidence rather than a substitution between endpoints or models.

## References and operation

All three authoritative metadata CSV `License/Terms of Use` entries classify
as permissive EMBL-EBI default terms. The complete harmonized GRCh37 files,
dated 2022-07-28, have measured sizes/SHA-256 pins in the committed manifest
and matching fetched lock records. Payloads are fetched and gitignored.

```powershell
genetics refs fetch --only pgs002126_grch37 --only pgs002152_grch37 --only pgs002124_grch37
```

Prepare the existing metadata, ancestry and imputation references as described
in [PGS cards](pgs_cards.md). `genetics run --input PATH` evaluates the new
cards alongside the pack, with imputation enabled by default. Missing references
leave each card visible with its exact fetch command.

## Validation and full-scale acceptance

Four new synthetic checks cover matched/mismatched ancestry through the shared
pipeline, frozen bundle reload, per-card CLI evidence, dashboard section/detail
routes, alcohol direction, phenotype denominators, unknown direct effects and
calibration, retained weak findings, both-phase coverage, low dosage quality
and missing-reference fetch commands. Model ID/source, field citation,
evaluation N, effect and interval are bound before substituting fabricated
five-row scoring inputs, preventing an undetected swap between cards.

All 55 card tests pass; full dbSNP lint passes 61 cards, 288 template renders
and 35/35 marker keys. Schema 4, bundle format 17 and the renderer are unchanged.
All four strict type targets (Windows/Linux, Python 3.11/3.13) pass for 200
source files. Ruff check/format and byte-identical fixture reproduction pass.
The complete synthetic run passed 2,855 checks with five existing Windows skips;
26 native/doctor failures or setup errors came from an incorrectly configured
`JAVA_HOME`. With the actual pinned runtime directory configured, all 26 pass
in 68.02 seconds: **2,881 unique checks pass**, with five skips remaining.
No production correction or repeated imputation was needed.

Complete four-worker cold reference preparation finished in **9,151.45 seconds**,
with **6,680,506,368 bytes** peak process-tree working set. Every released source
row remains represented; the model is not reduced for extraction.

| Model | Complete reference cache bytes |
| --- | ---: |
| PGS002126 | 290,427,803 |
| PGS002152 | 295,059,799 |
| PGS002124 | 177,982,974 |

All three full default-imputed and three explicit no-impute scoring checks
passed, including in-memory card/score consistency and complete serialization.
These are measured workstation costs, not predictive calibration.

| Model | Default-imputed scoring, consistency validation and writing (seconds) | Peak tree working-set bytes | Complete default record bytes | No-impute check (seconds) | No-impute peak bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| PGS002126 | 3,423.98 | 11,424,882,688 | 2,084,850,623 | 210.78 | 10,013,585,408 |
| PGS002152 | 3,323.99 | 11,600,138,240 | 2,118,717,451 | 194.99 | 10,101,104,640 |
| PGS002124 | 2,858.51 | 9,574,334,464 | 1,277,489,489 | 109.87 | 7,921,524,736 |

**Full-scale acceptance passed on 2026-10-13.** All six complete score/card
pairs were read back from disk and passed frozen validation of the score digest,
coverage, reference distribution, portability, display and reliability.

| Model | Default record disk-read validation (seconds) | No-impute record disk-read validation (seconds) |
| --- | ---: | ---: |
| PGS002126 | 76.01 | 40.56 |
| PGS002152 | 72.83 | 40.94 |
| PGS002124 | 42.32 | 22.42 |

The six disk-read validations took 295.08 seconds in total, with a maximum
observed peak tree working set of 6,241,988,608 bytes. The runner completed
successfully with an empty error log. The checkpoint reports `complete`, and
both acceptance and retained-validation records report `passed`.

The completed private checkpoint remains at
`%LOCALAPPDATA%/genetics-analysis/acceptance/m910`. It reuses M9.9's
two public stand-in inputs and all 22 completed full-autosomal dosage files,
verified against retained integrity records, without rerunning imputation.
Each full source model was prepared and checked under default-imputed and
explicit no-impute modes, with full score/card serialization followed by
disk-read frozen validation. Genetic outputs, coverage summaries and their
hashes remain outside Git and out of chat. The stand-ins belong to the
reference panel: this checks execution, not predictive calibration.
