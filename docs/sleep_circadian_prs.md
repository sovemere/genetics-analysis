# Sleep and circadian polygenic cards (M9.11)

Three public UK Biobank-only LDpred2-auto HapMap3 models use the existing PRS
engine, knowledge schema 4 and bundle format 17 in the Sleep & circadian section.
Reported evening preference, daily sleep duration and sleeplessness remain
separate endpoints. The cards do not turn a reference interval into a bedtime,
number of hours, physiological sleep need or clinical diagnosis.

## Exact public models and evidence

[Prive et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC8764121/) derived
these weights using UK Biobank only. No restricted 23andMe cohort contributes.
The [version-2 author release](https://doi.org/10.6084/m9.figshare.14074760.v2)
provides model-specific partial correlations in `pred-cor-ldpred2.csv`
(file 31619354). The results below are the held-out UK-ancestry rows for the
actual LDpred2 models, not the corresponding penalized-regression models.

| Endpoint / model | Released rows | Phenotype-specific training N | Held-out UK evaluation N | Partial-r (95% CI) | Derived residual variance explained |
| --- | ---: | ---: | ---: | --- | --- |
| [Evening preference, PGS002209](https://www.pgscatalog.org/score/PGS002209/) | 955,439 | 349,238 | 17,895 | 0.2185 (0.2045–0.2324) | 4.77% (4.18–5.40%) |
| [Log sleep duration, PGS002196](https://www.pgscatalog.org/score/PGS002196/) | 927,619 | 387,799 | 19,860 | 0.1451 (0.1315–0.1587) | 2.11% (1.73–2.52%) |
| [Ordinal sleeplessness, PGS002149](https://www.pgscatalog.org/score/PGS002149/) | 926,585 | 390,618 | 19,978 | 0.1411 (0.1275–0.1547) | 1.99% (1.63–2.39%) |

The authors' pinned [phenotype counts](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/phenotype-info.csv)
and [count export](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/export-info.R)
provide phenotype-specific nonmissing observations within the 391,124-person
Northwestern European training pool. That pool is not the effective N for
every phenotype. Held-out testing is within the same biobank, so replication
is `same_cohort`, not independent-cohort or consumer-array validation.

Both score and outcome were residualized on sex, age, birth date, deprivation
index and 16 PCs. The existing `percent_variance_explained` effect stores
`100*r²`, rounded to two decimals. All three quoted correlation intervals
are positive, so squaring their endpoints preserves their order. About 95.23%,
97.89% and 98.01% of residual outcome variance respectively remains unexplained.
These are residual ordinal/log-outcome associations, not raw-hours variance,
liability-scale disease variance, penetrance or individual probabilities.

## Coding, direction and calibration

The authors' pinned [phenotype preparation](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/prepare-pheno-fields.R)
defines the actual endpoints. Published weight directions are retained.

- [Field 1180](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=1180)
  retains ordinal [coding 100342](https://biobank.ndph.ox.ac.uk/showcase/coding.cgi?id=100342):
  definitely morning is 1 and definitely evening is 4. Higher score associates
  with greater evening preference. Category spacing is not a time interval;
  neither bedtime nor circadian phase is measured.
- [Field 1160](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=1160)
  asks for sleep across 24 hours, including naps. The authors exclude missing
  responses and reports below 4 or above 12 hours, then take the natural log.
  Higher score associates with longer reported sleep. This endpoint is not
  actigraphy, objectively measured duration or a physiological need. Taking
  an exponential of the score does not recover an individual's hours.
- [Field 1200](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=1200)
  asks about difficulty falling asleep or waking during the night. The authors
  retain ordinal [coding 100343](https://biobank.ndph.ox.ac.uk/showcase/coding.cgi?id=100343):
  never/rarely is 1, sometimes 2 and usually 3. Higher score associates with
  more frequent sleeplessness. It is not binary clinical insomnia, and does
  not supply diagnostic severity, chronicity or a case prevalence.

No model-specific direct within-family attenuation, complete matched absolute
ten-decile outcome series, category baseline or individual sleep-hour calibration
is supplied by the audited release. Those quantities remain absent and are
stated as unknown. Current Showcase aggregate response summaries are not
calibration of the selected training population or these exact weights; they
are not substituted as base rates. No educational-attainment attenuation is
borrowed, no confirmation gate is added, and weak findings remain visible with
coverage, imputation quality and ancestry portability.

## Narcolepsy and source scope

HLA-linked narcolepsy belongs to the separate HLA capability (M11), not a
single tag-SNP diagnosis. [PGS002212](https://www.pgscatalog.org/score/PGS002212/)
has a catalogue label that includes narcolepsy, but its reported phenotype is
daytime dozing/sleeping; that label cannot bind it to clinically diagnosed
narcolepsy. No narcolepsy diagnostic claim is introduced by M9.11. The authored
sleeplessness card states this distinction.

The chosen models provide public, exact-release evidence for three distinct
sleep endpoints. These weights do not claim the power of larger published
sleep GWAS or a restricted cohort. Their held-out UK correlations are not
transferred to the 1000 Genomes stand-ins as predictive calibration.

## References and operation

All three authoritative metadata CSV `License/Terms of Use` entries classify
as permissive EMBL-EBI default terms. Complete harmonized GRCh37 files are
fetched, with measured sizes and SHA-256 pins in the manifest and fetched lock.
All headers declare `HmPOS_date=2022-07-28`; later HTTP modification dates do
not replace that internal version. Payloads are gitignored, never vendored.
Every source row and its explicit exclusion state remains in the engine.

```powershell
genetics refs fetch --only pgs002209_grch37 --only pgs002196_grch37 --only pgs002149_grch37
```

Prepare metadata, ancestry and imputation prerequisites as described in
[PGS cards](pgs_cards.md). `genetics run --input PATH` evaluates these cards
alongside the pack with default-on imputation. An absent reference leaves the
card visible with its exact fetch command. `--no-impute` stays an explicitly
recorded development/testing escape hatch.

## Validation and full-scale acceptance

Four new synthetic checks cover matched/mismatched ancestry, shared pipeline,
frozen bundle reload, per-card CLI evidence, dashboard section/detail routes,
phenotype coding, direction, training denominators, unknown direct effects and
calibration, both-phase coverage, low dosage quality and missing-reference
fetch commands. Exact model ID/source, field citation, evaluation N, effect
and interval are bound before substituting fabricated five-row inputs.
Per-card evidence and saved computation are checked after reload; an aggregate
set of sample sizes/effects is not the evidence-binding test.

Full card lint passes 64 cards, 294 template renders and all 35 marker keys.
All 2,885 unique checks pass, with five existing Windows skips. The broad run
passed 2,881 checks in 819.02 seconds; it loaded two sleep assertions before
their wording correction, encountered one transient 60-second PLINK 1.9
version-probe timeout, and lacked the native arithmetic test's tool variable.
The targeted recheck with that variable set passes all 15 selected cases in
7.25 seconds, covering the four outstanding cases without a production change.
All four strict type targets (Windows/Linux, Python 3.11/3.13) pass for 200
source files. Ruff check/format, byte-identical fixtures and staged privacy
scanning pass. No engine, schema or renderer change is needed.
The unchanged renderer's prior browser visual check is still
unavailable; no new screenshot review is claimed.

**Full-model acceptance passed on 2026-10-13**, in a separate private
`%LOCALAPPDATA%/genetics-analysis/acceptance/m911` checkpoint. It verifies
and reuses M9.9's durable normalized public stand-ins, all 22 full-autosomal
dosage files and their matching provenance. Previous accepted checkpoints are
preserved. All three reference preparations, three default-imputed and three
explicit no-impute scoring checks, complete record writing and all six
subsequent disk-read validations passed. Genetic results, coverage
summaries and their hashes remain outside Git and out of chat.

Complete sixteen-worker cold reference preparation finished in **8,598.07
seconds**, with **8,025,993,216 bytes** peak process-tree working set. Every
released source row remains represented; no model was reduced for extraction.

| Model | Complete reference cache bytes |
| --- | ---: |
| PGS002209 | 297,617,921 |
| PGS002196 | 289,197,080 |
| PGS002149 | 288,857,351 |

All six full scoring checks passed, including in-memory card/score consistency
and complete serialization. These measured costs are
workstation execution costs, not predictive calibration.

| Model | Default-imputed scoring, consistency validation and writing (seconds) | Peak tree working-set bytes | Complete default record bytes | No-impute check (seconds) | No-impute peak bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| PGS002209 | 2,890.75 | 11,703,742,464 | 2,137,447,102 | 194.28 | 8,575,500,288 |
| PGS002196 | 2,940.63 | 11,369,611,264 | 2,075,962,506 | 187.84 | 8,751,509,504 |
| PGS002149 | 2,881.13 | 11,356,721,152 | 2,073,662,310 | 185.52 | 8,744,849,408 |

All six score/card pairs were read back from disk and passed frozen validation
of their score digest, coverage, reference distribution, portability, display
and reliability.

| Model | Default record disk-read validation (seconds) | No-impute record disk-read validation (seconds) |
| --- | ---: | ---: |
| PGS002209 | 79.58 | 40.05 |
| PGS002196 | 75.76 | 39.03 |
| PGS002149 | 73.64 | 37.86 |

The six disk-read validations took 345.92 seconds in total, with a maximum
observed peak tree working set of 6,281,764,864 bytes. The acceptance and
retained-validation records both report `passed`; the checkpoint is `complete`
and the runner finished with an empty error log. A final check independently
reverified all reusable inputs and retained checkpoint files, with no pending
scores or disk-read validation. No completed imputation was rerun and no source
model was reduced.

The [M9.11 diff review](review_m911_session.md) independently confirms the
exact public releases, source pins, phenotype-specific N and reported
associations. It closes a testing gap: all three inverted face directions
previously passed the integration checks despite correct detail text.
Directed phenotypes are now bound before synthetic substitution and checked
after reload in CLI/dashboard output, with three retained mutation regressions.
All 62 card tests, four strict type targets and full card lint pass; all six
retained native card model/direction/evidence bindings also pass. No authored
card, engine, schema, renderer or native score change was needed. The original
full-scale acceptance measurements above are preserved.
