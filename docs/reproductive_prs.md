# Reproductive polygenic cards (M11.7)

Seven public polygenic models take the reproductive section beyond carrier status: age at
menarche, age at menopause, age at first live birth, age at first sexual intercourse, menstrual
cycle length, and serum testosterone in women and in men. Each is its own endpoint. None gives an
age, a number of days, a concentration, a fertility estimate or a diagnosis.

No personal export was read for this milestone. Every figure below is a published result or an
identity of a public reference file.

## The models

| Card | Model | Rows | Training | Held-out test | Reported | Stored as |
| --- | --- | ---: | ---: | --- | --- | --- |
| `menarche_age_ldpred2` | [PGS003508](https://www.pgscatalog.org/score/PGS003508/) | 979,739 | 193,057 women | 10,448 white British women | partial-R2 0.10 | 10% |
| `menopause_age_clumped` | [PGS002821](https://www.pgscatalog.org/score/PGS002821/) | 159 | 69,360 women (GWAS) | 69,801, UK Biobank | R2 0.00316 | 0.316% |
| `first_birth_age_ldpred2` | [PGS003505](https://www.pgscatalog.org/score/PGS003505/) | 979,739 | 135,106 women | 7,313 white British women | partial-R2 0.05 | 5% |
| `first_sex_age_ldpred2` | [PGS002156](https://www.pgscatalog.org/score/PGS002156/) | 972,919 | 342,706 | 17,510 UK-ancestry | partial-r 0.2443 (0.2304–0.2582) | 5.97% (5.31–6.67%) |
| `menstrual_cycle_length_ldpred2` | [PGS002129](https://www.pgscatalog.org/score/PGS002129/) | 491,888 | 18,570 women | 987 UK-ancestry women | partial-r 0.1022 (0.0394–0.1641) | 1.04% (0.16–2.69%) |
| `testosterone_female_ldpred2` | [PGS003507](https://www.pgscatalog.org/score/PGS003507/) | 979,739 | 157,915 women | 8,475 white British women | partial-R2 0.06 | 6% |
| `testosterone_male_ldpred2` | [PGS003559](https://www.pgscatalog.org/score/PGS003559/) | 979,739 | 161,314 men | 8,753 white British men | partial-R2 0.09 | 9% |

All are autosomal. All seven `License/Terms of Use` entries classify as the permissive EMBL-EBI
default in the fetched metadata. Each harmonized GRCh37 file's size and SHA-256 are in the
manifest and lock; payloads are gitignored.

Training counts for the Ding models come from the paper's Supplementary Table 1. The catalogue's
development rows differ slightly (193,808, 135,632, 158,529 and 161,936), and the cards state both.
Effect values for those models come from the catalogue, which prints two decimals and no interval,
so those effects have no interval on the card and none was invented.

## Two catalogue labels name the wrong endpoint

The `pgs_name` inside each scoring file is the authority, and a native test binds each card to it:

- **PGS002128** is labelled "Length of menstrual cycle", but its name is
  `portability-ldpred2_F_irregular_menstrual_cycle`: the binary irregular-cycle model. PGS002129 is
  the length model.
- **PGS002215** is labelled "Age first had sexual intercourse", but its name is
  `portability-ldpred2_no_sex`: the binary never-had-sex model, with partial-r 0.0313. PGS002156 is
  the age model.

## Choosing between models

Two releases supply UK Biobank-only LDpred2-auto models of these traits with a result per model and
population: [Prive 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC8764121/), which M9.9–M9.12 used, and
[Ding 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10284707/). Neither has 23andMe exposure. Ding's women-only models train on far more people:
Prive's phenotype table has 110,663 for menarche and 77,356 for first birth, against 193,057 and
135,106.

**The rule used: take Ding where its rounded result exceeds the upper interval of Prive's in the UK
test sample; otherwise keep Prive for its exact interval.**

| Endpoint | Ding, white British | Prive, UK (95% CI) | Choice |
| --- | ---: | --- | --- |
| Menarche | 10% | 8.01% (6.71–9.41%) | Ding |
| First live birth | 5% | 3.35% (2.33–4.53%) | Ding |
| Testosterone, women | 6% | 2.67% (2.06–3.35%) | Ding |
| Testosterone, men | 9% | 2.26% (1.66–2.95%) | Ding |
| First sexual intercourse | 5% | 5.97% (5.31–6.67%) | Prive |
| Cycle length | 1% | 1.04% (0.16–2.69%) | Prive |

Polish and Italian test groups point the same way for menarche (8% and 8%, against 6.00% and
6.63%). These comparisons use different held-out draws, so they support a choice, not a claim of
superiority.

**The testosterone gap is not explained.** Training sizes are close, yet Ding reports two to four
times Prive's figure on the same field in the same biobank. Their estimated heritabilities differ
too: 0.11 and 0.15 in Ding, 0.061 and 0.054 in Prive's table. Ding does not print its phenotype
coding, so a difference in preparation cannot be excluded. Each testosterone card states the other
group's figure on its face.

R-squared has no sign, so the Ding cards' direction was measured: each model's weights correlate
positively with Prive's model of the same phenotype over their shared variants (menarche 0.61 over
807,244; first birth 0.63 over 800,685; women's testosterone 0.40 over 616,043; men's 0.34 over
554,494), and each of those Prive models has a positive held-out correlation. Those comparison files
were read for this check and are not in the manifest, so no test repeats it.

## Age at menopause, and why its R2 is probably too low

Prive and Ding have no menopause model. The catalogue's five are all from
[Ma 2022 (ExPRSweb)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9606385/), built from
[Day 2015](https://pmc.ncbi.nlm.nih.gov/articles/PMC4661791/)'s 69,360 women from 33 studies. The
larger [Ruth 2021](https://doi.org/10.1038/s41586-021-03779-7) analysis has no catalogue model.

| Model | Rows | R2 in the same test half |
| --- | ---: | ---: |
| PGS002821, clumping and thresholding on dosages | 159 | 0.00316 |
| PGS002822, clumping and thresholding on best-guess genotypes | 159 | 0.00316 |
| PGS002824, PRS-CS | 894,484 | 0.00129 |
| PGS002820, lassosum | 99,745 | 0.00118 |
| PGS002823, DBSLMM | 1,379,304 | 0.000705 |

PGS002821 was taken as the best measured. PGS002822 holds the same 159 rows, in another order. The
smaller model is the more accurate one here, so this choice follows AGENTS.md §0.1C rather than
departing from it. Ma tunes on a 50/50 split of UK Biobank, so the threshold came from one half
(N=69,822) and the test from the other (N=69,801). UK Biobank is absent from Day 2015's text, which
matches Ma's stated rule of using outside GWAS. That is why this is the one card here with
`replication: independent`.

Weights are years per allele, rounded to two decimals. A native test binds direction and units to
Day 2015's Table 1: A at 20:5,948,227 is +0.88, and G at 19:55,833,664 is -0.41, their estimates for
rs16991615 and rs11668344.

The reported R2 does not fit the rest of the literature (Day attributes 6% of the variance to its top
54 SNPs), and the catalogue's own numbers suggest why:

1. **The evaluated phenotype's spread.** Ma scales scores to SD 1, so a linear model's standard error
   gives the residual SD: 0.0507 × √69,801 = **13.4 years**.
2. **The field's real spread.** The [Showcase deciles of field 3581](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=3581)
   are 43, 50 and 55, so about **4.7 years**.
3. **What would produce 13.4.** At baseline, 10,348 answers are -1 ("Do not know") and 370 are -3
   ("Prefer not to answer"), of 165,192: 6.5%. Treated as ages, those give a mixture SD of **13.4
   years**.

The same arithmetic on Ma's menarche row gives 2.76 years against about 1.6 from its deciles, and 2.9
predicted from field 2714's 3.1% of coded answers. If the codes are the whole cause, the menopause R2
would be near 2.6% rather than 0.32%. Noise independent of the score scales every model's R2 alike, so
the ranking above would not change.

This is an inference. Ma describes an outlier rule that should have removed such values; it may not
have reached this field, and the supplement was not read. So the card stores the published 0.316%, says
on its face that it is probably too low, gives 2.6% only in the detail view as an inference, and lets
confidence use the published number.

## Endpoint limits on the card

- **Women-only endpoints.** Menarche, menopause, first birth and cycle length were measured in women,
  and the testosterone models are each trained on one recorded sex. As with the breast-cancer score, the
  engine scores every card for every run and does not choose cards by the sex call. The card says that someone who
  has never menstruated has no matching outcome, or that the other testosterone card has its own
  weights. No section-level gate is added (AGENTS.md §0.1B).
- **First live birth.** UK Biobank collected [field 2754](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=2754)
  only from women with more than one child, so women with one child or none are not in the endpoint.
- **First sexual intercourse.** [Field 2139](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=2139)
  defines intercourse to include vaginal, oral or anal. Prive keeps 10 to 40 years and logs it, which
  removes never-had-sex answers.
- **Cycle length.** [Field 3710](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=3710) reached only
  women whose periods had not stopped, all about 40 or older. Prive keeps 15 to 40 days, which removes
  irregular-cycle answers. The test sample of 987 is why its interval spans 0.16–2.69%.
- **Testosterone.** [Field 30850](https://biobank.ndph.ox.ac.uk/showcase/field.cgi?id=30850) is a total
  testosterone assay. The cards do not claim free testosterone, a concentration or a symptom.

## Within-family evidence

No shipped model has a model-specific direct estimate, so `within_family_attenuation` stays absent and
the engine says the direct share is unknown on every face, as M9.9 did. M9.9's rule also holds: another
study's result may be stated as context, identified as such, and is not assigned to these weights.

[Howe 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9110300/) covers three of the seven traits in a
sibling meta-analysis, using scores of GWAS hits. Age at first birth shrinks 52% (95% CI 30–75%) and that
goes on the face. Menarche and menopause are among the 17 phenotypes with "limited evidence" of a
difference; their per-trait values are in its Supplementary Table 3, which was not read. It did not study
first sexual intercourse, cycle length or testosterone.

## Considered and left out

- **Number of children, childlessness** (PGS002309, PGS002317 and others; 0.82% and 0.58% incremental R2
  in non-British Europeans). The evidence is real, and the trait is in scope under AGENTS.md §0.1B. Left
  out because their phenotype coding is only in [Weissbrod 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9009299/)'s
  Supplementary Table 3 and its results directory now returns 404, so the endpoint could not be stated
  precisely. Howe's 67% shrinkage for number of children (95% CI 4–130%) is the first thing such a card
  would need to carry.
- **Weissbrod menarche models** (PGS002310, PGS002627, PGS002676; 9.72–10.08% in non-British Europeans).
  Comparable to Ding, but the test group and metric differ, and the mix-weight file behind the PolyFun figure
  is unavailable.
- **ExPRSweb menarche** (PGS002815–PGS002819). Reported 1.18% at best, with the same phenotype-spread
  problem as menopause.
- **Irregular cycle** (PGS002128, partial-r 0.0848, N=1,185; PGS002079, a phecode, 0.0369). Weaker, and the
  cycle-length card states that it does not cover regularity.
- **Oestradiol, SHBG, endometriosis, fibroids, ovarian cancer, pre-eclampsia, gestational traits.** Biomarker
  or disease-liability endpoints that belong with physical health. Gestational duration's flagship model
  (PGS002806) was not audited for 23andMe exposure. PCOS has no catalogue model in the fetched metadata.
- **Single-marker trait cards.** Not added: the schema still requires a reproductive interpretation card to
  declare `carrier`, and this milestone does not relax that.

## Schema and format

The handoff noted that the schema refused both card forms. M11.7 widens one deliberately:

- **Knowledge schema 9** adds `reproductive` to `POLYGENIC_SECTIONS`. A file on an earlier schema that holds
  a reproductive polygenic card is refused. A reproductive *interpretation* card must still declare `carrier`
  (a test pins it), so no false carrier block is needed anywhere.
- **Bundle format 28** may hold such a card. The record and card are otherwise unchanged. A previous reader
  refuses the format, and a format before 28 that claims to hold one is refused on every read, including
  reads that skip the deep checks. Formats 1–27 are read unchanged.
- **The section statement is unchanged.** `carrier_screening_scope` counts only carrier records, so its tally
  and wording stay the same beside these cards, and its pinned saved wording needs no schema bump. The notice
  names carrier screening, so it does not read as a limit on these scores. A run with polygenic cards but no
  carrier card gets no notice.
- **The section blurb changed.** "About offspring rather than self" is false beside these cards. It is current
  context rather than saved evidence, so no format depends on it. AGENTS.md §3.1 changed with it.
- **The card text is ASCII.** Non-ASCII is safe on CLI output since M11.6, but `CliRunner` cannot show that, so a
  test keeps this file ASCII rather than relying on it.

```powershell
genetics refs fetch --only pgs003508_grch37 --only pgs002821_grch37 --only pgs003505_grch37 --only pgs002156_grch37 --only pgs002129_grch37 --only pgs003507_grch37 --only pgs003559_grch37
```

An absent reference leaves the card visible with its exact fetch command. `genetics run` scores them with the
rest of the pack, with imputation on by default.

## Validation

Recorded in the handoff: [M11.7](handoff.md#accepted-m117-reproductive-traits).
