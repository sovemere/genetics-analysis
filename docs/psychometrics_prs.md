# Psychometric polygenic cards (M9.9)

Three public additive models cover cognitive-test performance, educational
attainment and neuroticism. They use the existing shared PRS engine, knowledge
schema 4 and bundle format 17. There is no score approximation, evidence
truncation, new schema or special confirmation gate for this section.

## Exact models and populations

All three models are from [Prive et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC8764121/).
They use UK Biobank-only LDpred2-auto HapMap3 weights, including the published
sparse option. The full released model is evaluated; the engine does not replace
it with a smaller clumped approximation. These models were selected for their
auditable model-specific performance and cross-ancestry evaluation in a common
study design. Performance across differently defined phenotypes and cohorts
cannot establish a universal best model.

Within this study's same UK test samples, the released
`pred-cor-PLR.csv` (Figshare file 31619357) gives partial-r 0.1628 for cognition,
0.1752 for education and 0.1882 for neuroticism, below the LDpred2 point
correlations in the table. We retain the large LDpred2 releases rather than
defaulting to the much smaller penalized-regression scores. Overlapping
confidence intervals do not establish statistically significant method
superiority for every phenotype.

| Card / public model | Released rows | Training observations | Held-out UK-ancestry evaluation | Published partial-r (95% CI) | Derived residual variance explained |
| --- | ---: | ---: | ---: | --- | --- |
| [Fluid intelligence, PGS002135](https://www.pgscatalog.org/score/PGS002135/) | 903,259 | 99,976 | 5,092 | 0.1998 (0.1733-0.2261) | 3.99% (3.00-5.11%) |
| [Qualifications-to-years, PGS002231](https://www.pgscatalog.org/score/PGS002231/) | 950,845 | 320,190 | 16,350 | 0.2008 (0.1860-0.2154) | 4.03% (3.46-4.64%) |
| [Neuroticism, PGS002213](https://www.pgscatalog.org/score/PGS002213/) | 950,183 | 317,218 | 16,206 | 0.2040 (0.1892-0.2188) | 4.16% (3.58-4.79%) |

The catalogue records a **391,124-person Northwestern European training pool**
for all three. The authors' [phenotype-info.csv](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/phenotype-info.csv)
gives the smaller, phenotype-specific counts above. Their [export code](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/export-info.R)
counts nonmissing observations within the training set. Cards distinguish those
counts instead of calling the pool the model's effective phenotype N. Evidence
`sample_size` names the held-out cohort supporting the quoted association.

The numerical correlations and evaluation counts were checked directly against
the authors' **pred-cor-ldpred2.csv** in their [version-2 release](https://doi.org/10.6084/m9.figshare.14074760.v2),
not inferred from a different model's headline result. The phenotype-count audit
uses author-repository commit `14159aed82b430ad165376eaf707ebdce0db06b1`; the
Figshare performance file is file 31619354 in version 2. The paper's Performance
metric section defines partial-r as the correlation after residualizing both
score and phenotype on sex, age, birth date, Townsend deprivation index and
16 PCs. The cards derive `100 * r^2` using the existing
`percent_variance_explained` measure. Because these three UK confidence intervals
are wholly positive, squaring their endpoints is a monotone transformation;
this would not apply to a correlation interval crossing zero. Percentages are
rounded to two decimals and explicitly describe **residual**, not total,
phenotypic variance. Approximately 96% remains unexplained by each score.

The authors' [phenotype preparation](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/prepare-pheno-fields.R)
uses field **20191** for cognition, the online test, rather than touchscreen field
20016. [UK Biobank's field definition](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=20191)
describes 14 reasoning questions with a two-minute limit. This is a brief test,
not a comprehensive IQ assessment. Education uses field 6138 qualifications
mapped to years; neuroticism uses questionnaire field 20127. Neither education
nor neuroticism is interpreted as a direct measurement of ability, character,
current emotions or psychiatric disease.

Testing is held-out **within the same biobank**. Cards therefore declare
`replication: same_cohort`, not independent-cohort replication. Published
cross-ancestry testing does not establish consumer-array calibration or erase
the ancestry confidence ceiling.

## Corpus and within-family limits

All three score-specific `License/Terms of Use` entries in the fetched authoritative
metadata CSV classify as permissive EMBL-EBI default terms. Each harmonized GRCh37
file has measured byte length and SHA-256 in the manifest, with a matching fetched
lock. Harmonization date is 2022-07-28. Reference payloads are downloaded and
gitignored; none is vendored.

Fetch the new weights through the normal reference path:

```powershell
genetics refs fetch --only pgs002135_grch37 --only pgs002231_grch37 --only pgs002213_grch37
```

Metadata and the existing imputation/ancestry references must also be prepared
as described in the [PGS guide](pgs_cards.md). `genetics run --input PATH` then
evaluates these cards alongside the other sections, with imputation on by default.
Missing references leave visible unrun cards with the fetch command.

These are public **UK Biobank-only models**. They are not a newly downloaded
23andMe-inclusive release, nor a reduced-N excluding-23andMe meta-analysis. No
23andMe data or access agreement is used. This distinction matters because
larger flagship behavioural GWAS often have restricted cohorts. Those larger
sample sizes and their performance cannot be assigned to these weights.

[Okbay et al.'s separate EA4 study](https://pmc.ncbi.nlm.nih.gov/articles/PMC9005349/)
reports population R2 of 12-16% and direct association effects roughly half as
large after controlling for parental scores. Its genome-wide public summary
statistics exclude 23andMe; its full-study headline N is not a public reduced
release's N. The education card states the EA4 findings on its face as context,
explicitly identifying them as another model. It does **not** assign that R2,
the attenuation or its college-completion decile rates to PGS002231. Halving an
association coefficient is not halving explained variance.

For the exact three shipped weights, `within_family_attenuation` stays absent;
the engine states on every face that the direct share is unknown. The cards
retain population association, indirect family/environment effects, assortative
mating and residual structure as distinct concepts. None supplies complete,
matched absolute decile-outcome rates, so none invents `decile_outcomes`, a
baseline probability or an individual's outcome estimate. Personality coverage
includes neuroticism; the same model cannot stand in for other personality
dimensions without separately sourced weights and evidence.

## Presentation and validation

The existing renderer shows the reference histogram first, with a shaded
reference-position interval rather than a point. The interval reflects reference
group size only; coverage, imputation quality, portability and within-family
limits are stated separately. The display does not contain an individual sum,
point percentile, IQ conversion or predicted schooling duration. Low confidence
does not suppress a card.

Two new synthetic end-to-end cases exercise the three actual definitions under
matched and mismatched ancestry. They verify frozen bundle reload, CLI JSON,
dashboard faces and details, exact study scope, phenotype N, unknown direct
effects, absent outcome calibration, visible confidence/coverage/portability
and intervals with no personal point estimate. All observations, weights and
panels in these tests are fabricated.

Visual inspection was attempted on a synthetic-only loopback dashboard through
the browser tool. The in-app browser reported unavailable and the surface
inventory contained no browsers. No screenshot review is claimed. HTTP rendering
and existing chart geometry checks are available; the dashboard renderer is
unchanged in M9.9.

## Full-scale acceptance

Four-worker cold reference preparation for all three complete models finished
in **11,818.10 seconds**, with **6,741,729,280 bytes** peak process-tree working
set. Source checksums are verified; no model is reduced to speed up extraction.

| Model | Complete reference cache bytes |
| --- | ---: |
| PGS002135 | 281,640,319 |
| PGS002231 | 296,480,955 |
| PGS002213 | 296,208,909 |

The cognition and education default-imputed checks passed, retaining every source
term and validating card consistency before writing the complete score records.

| Model | Default-imputed scoring, consistency validation and writing (seconds) | Peak tree working-set bytes | Complete record bytes |
| --- | ---: | ---: | ---: |
| PGS002135 | 4,110.40 | 11,082,002,432 | 2,022,102,153 |
| PGS002231 | 3,226.95 | 11,683,201,024 | 2,127,199,014 |

These are observed workstation costs, not predictive calibration. Both public
stand-ins belong to the reference panel. **Acceptance was paused at the owner's
request on 2026-10-11.** Neuroticism was interrupted; that scoring stage must
restart. The three explicit no-impute checks and six retained JSON disk-read
validations remain. M9.9 is not yet accepted.

The durable checkpoint is `%LOCALAPPDATA%/genetics-analysis/acceptance/m99`.
It includes both completed scores, both public-array inputs, all 22 completed
imputation dosage files, provenance, measurements and the resume scripts.
Copied data was verified against the originals, and the runner's integrity-only
check passed. Reference weights and all three reference caches already live in
the durable application directories. The checkpoint contains private genetic
data and hashes; keep its contents outside Git and out of chat.

From the repository root, resume with:

```powershell
$m99Checkpoint = Join-Path $env:LOCALAPPDATA 'genetics-analysis\acceptance\m99'
.venv\Scripts\python.exe "$m99Checkpoint\genetics_m99_acceptance.py" --check-only
.venv\Scripts\python.exe "$m99Checkpoint\genetics_m99_acceptance.py" *> "$m99Checkpoint\resume.log"
```

The runner verifies retained file sizes/hashes and the knowledge-pack digest,
reuses the reference caches and imputation, and skips completed phase markers.
Each newly completed scoring stage is checkpointed; an interrupted stage restarts.
It finishes by validating all six retained JSON records from disk. Require
`passed` in both `acceptance.run.json` and `retained-validation.json`, and
`complete` in `checkpoint.json`, before recording final costs and closing M9.9.

All reference matrices, public stand-in runs, per-phase coverage and resource
measurements stay outside Git, including aggregate genetic summaries.

The implementation suite passed **2,876 tests with six skips** in 479.92 seconds.
The separately enabled native PGS arithmetic check then passed: **2,877 unique
checks passed**, leaving five documented Windows platform skips. All four strict
type targets (Windows/Linux, Python 3.11/3.13) check 200 source files. Ruff,
formatting, byte-identical fixture reproduction and full dbSNP card lint pass:
58 cards, 282 template renders and 35/35 marker keys.
