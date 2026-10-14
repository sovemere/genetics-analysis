# Fitness and physiology (M9.12)

Five declarative cards use the shared engine, knowledge schemas 3/4 and bundle
format 17. No engine or renderer change is needed. The four variant cards
distinguish molecular function, biomarker concentration, chronic tendon injury
and aerobic-training response. The polygenic card measures a fifth endpoint,
mean hand grip strength. None estimates athlete status or prescribes training.

## Variant evidence and limits

| Card / variant | Selected endpoint and estimate | Estimate population | Replication |
| --- | --- | --- | --- |
| ACTN3 / rs1815739 | Approximately 2% of women's 1-RM gain variance, omnibus genotype association | 355 women; 247 men had no association | Same-cohort ethnic subgroup checks |
| ACE / rs4343 | 46.6% serum ACE concentration variance, adjusted R-squared 0.466 | 92 healthy nonobese twins, German recruitment; ancestry unstated | Same cohort for this exact endpoint |
| COL5A1 / rs12722 | CC versus CT/TT chronic Achilles tendinopathy case OR 0.42 (95% CI 0.20–0.86) | Australian 85 cases / 210 controls; the estimate is not from the combined 520 participants | Conflicting: second small population supported it; larger GERA endpoint did not |
| ACSL1 / rs6552828 | 6.1% discovery variance in adjusted VO2max gains | 473 sedentary white adults from 99 HERITAGE families, 20-week programme | Not confirmed in any of three replication cohorts |

[Clarkson 2005](https://pubmed.ncbi.nlm.nih.gov/15718405/) supplies ACTN3's
sex-specific training evidence. Its approximate omnibus variance is not a
per-copy effect or an expected percentage improvement. The mixed study
population is recorded as `MULTI`; European and Asian subgroup analyses are
not independent replication. [Yang 2003](https://pubmed.ncbi.nlm.nih.gov/12879365/)
supports the distinction between R577 protein preservation and X577 deficiency
in healthy people. Molecular function alone does not establish a performance
effect, so the authored training evidence remains `candidate_gene`.

[Schuler 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5523633/) reports the ACE
concentration association. Its other population's blood-pressure analysis
does not validate this exact 46.6% estimate. NUGAT recruitment geography does
not specify ancestry: the card records `UNKNOWN`. rs4343 is a directly
matchable synonymous SNP. The engine does not turn it into I/D state;
population-dependent linkage is not a verified representation mapping under
AGENTS.md §4.2. Consumer I/D remains excluded. Serum concentration is not
enzyme activity, endurance, power or blood pressure.

[September 2009](https://doi.org/10.1136/bjsm.2008.048793) supplies the COL5A1
genotype-group comparison. CT and TT retain explicit null outcome evidence:
neither inherits CC's estimate, a reciprocal per-copy effect or an invented
separate genotype risk. [Kim 2017](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0170422)
failed to confirm this locus in its broader Achilles endpoint. Endpoint
differences are stated without erasing the failed confirmation. Case-control
sampling fractions are not population base rates; absolute risk is unknown.

[Bouchard 2011](https://pmc.ncbi.nlm.nih.gov/articles/PMC3098655/) supplies the
ACSL1 single-locus discovery estimate. Its P=1.31e-6 is below genome-wide
significance. The authors explicitly report no confirmation in HERITAGE black
participants, DREW or STRRIDE. This exploratory finding is `candidate_gene`
with `conflicting` replication, not a genome-wide significant or validated
trainability model. The paper's 3.5% multivariable contribution and 48.6%
21-SNP fit are different estimates and are not substituted. Neither a training
response nor an elite endurance category is calibrated for the reader.

All four keys were measured against the local public dbSNP b157 GRCh37 index.
ACTN3, ACE and COL5A1 are multiallelic there. Every variant card requires
forward-only matching, so an unexpected allele cannot be complemented into a
supported genotype. Every supported pair has an outcome; missing markers,
consumer I/D and unsupported alleles remain visible unresolved states.
Confidence is computed. Conflicting replication caps reliability at limited;
rarity or poor imputation can still lower it to likely-artifact.

## Exact public grip model

[PGS002143](https://www.pgscatalog.org/score/PGS002143/) is the complete
UK Biobank-only LDpred2-auto HapMap3 model from
[Prive 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC8764121/).
All **966,283 source rows** are retained. The authoritative metadata CSV
`License/Terms of Use` entry resolves to the permissive EMBL-EBI default.
The harmonized GRCh37 file is 22,268,195 bytes, SHA-256 pinned in the manifest
and recorded by the fetcher in the lock. Its internal harmonization date is
2022-07-28. No payload is vendored; no restricted 23andMe cohort contributes.

The pinned author [preparation code](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/prepare-pheno-fields.R)
takes the mean of left/right grip fields
[46](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=46) and
[47](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=47), requiring both
hands and excluding means below 1 kg. The pinned
[phenotype counts](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/phenotype-info.csv)
give **388,700 effective training observations**, within the 391,124-person
Northwestern European pool.

The [version-2 author release](https://doi.org/10.6084/m9.figshare.14074760.v2),
`pred-cor-ldpred2.csv` (file 31619354), reports **19,855 held-out UK participants**,
partial-r **0.2620 (95% CI 0.2490–0.2749)**. The card stores `100*r²` as
**6.86% (6.20–7.56%)** residual variance, with **93.14% unexplained**. Both
score and outcome were residualized on sex, age, birth date, deprivation index
and 16 PCs. The metric belongs to these weights and this endpoint, not the
penalized-regression model or a generic training population. Higher score
means greater grip. No personal kilogram conversion, appropriate model
baseline, matched absolute decile series or direct within-family estimate is
provided. Replication is `same_cohort`, not independent consumer validation.

Public PGS metadata was audited for trainability and injury models as well.
No exact training-response or Achilles/ACL model was identified in that fetched
release. The cited exploratory variant findings still render. Grip strength
does not stand in for training response or injury susceptibility.

```powershell
genetics refs fetch --only pgs002143_grch37
```

The existing [PGS card setup](pgs_cards.md) supplies metadata, ancestry and
imputation prerequisites. `genetics run` uses default-on imputation; explicit
`--no-impute` remains recorded. An absent model leaves a visible unrun card
with the exact fetch command. Reference distributions, uncertainty, both-phase
coverage, imputation quality and ancestry portability remain on the face.

## Validation and acceptance

Synthetic checks bind model/source, directed phenotype, citations, effective
N, effect and interval before substituting fabricated weights. Mutations
reject reversed direction, another model and a borrowed denominator. Both
ancestry cases, both-phase coverage, poor dosage quality and missing-reference
fetch instructions are checked through saved CLI/dashboard views. Variant
checks bind exact loci, allele direction, endpoints, estimates and replication;
all supported pairs, unexpected alleles, I/D, missing markers, rarity and saved
per-card evidence are exercised. Null injury estimates stay null after reload.

All **2,923 unique checks pass**, with five existing Windows skips. The broad
run passed 2,900 checks in 863.64 seconds; five failures and eighteen setup
errors all came from using system Java 8 with bref3. Configuring the previously
verified portable Temurin Java 17 makes all 23 affected checks pass in 48.47
seconds, without a code change. All four strict type targets pass for 201
source files. Full dbSNP lint passes **69 cards / 320 template renders / 39
marker keys**; style, fixture reproduction, whitespace and staged privacy
checks pass. All 97 focused variant/polygenic-card checks pass, including the
final population-label assertions. No personal export was opened.

**Full-model acceptance passed on 2026-10-14**, in the separate private
`%LOCALAPPDATA%/genetics-analysis/acceptance/m912` checkpoint. It reuses M9.9's
verified stand-ins and all 22 complete dosage files with matching provenance.
Earlier acceptance records are preserved. Complete sixteen-worker reference
preparation passed in **3,594.23 seconds**, with **5,823,340,544 bytes** peak
process-tree working set and a **300,958,250-byte** complete reference cache.
No model was reduced. Default-imputed and explicit no-impute scoring both
passed, as did both subsequent disk-read validations. Each record retains all
966,283 source terms. Reload checks explicitly bind model/source, directed
phenotype, citations, evaluation N, effect and interval, then run frozen
validation of score digest, coverage, distribution, portability, display and
reliability. Genetic results, coverage summaries and hashes stay
outside Git and chat. These public panel stand-ins test execution, not
predictive calibration. The renderer is unchanged; no browser screenshot
review is claimed.

| Check | Seconds | Peak process-tree working-set bytes | Complete score record bytes |
| --- | ---: | ---: | ---: |
| Default-imputed scoring, consistency validation and writing | 2,927.99 | 11,825,819,648 | 2,161,215,174 |
| Explicit no-impute scoring, consistency validation and writing | 191.53 | 8,408,539,136 | — |
| Default record disk-read validation | 75.91 | 6,361,067,520 | — |
| No-impute record disk-read validation | 38.05 | 3,920,117,760 | — |

Measurements sample process-tree working set every second. They describe
execution costs, not predictive calibration. Both acceptance records report
`passed`, the checkpoint is `complete`, and the runner exited with an empty
error log. A final check independently reverified reusable inputs and every
retained checkpoint file; no scoring or disk-read validation remains pending.
Completed imputation was reused throughout.
