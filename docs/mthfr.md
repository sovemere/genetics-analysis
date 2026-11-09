# MTHFR C677T: the calibration case (M12.2)

The roadmap calls M12.2 "a deliberate calibration test case". MTHFR is heavily overhyped in
wellness marketing, so the card should state the actual evidence, let the confidence
calculator land where it lands, and serve as the reference example for how the project
handles popular claims with thin support.

The calculator scores one claim per card. A single card about what the variant does would
land well-established, and none of the claims made for it would be scored. So M12.2 has four
cards on one marker, rs1801133. Each states one claim with the studies that measured it, and
each lands where its own evidence puts it:

| Card | Section | Claim | Evidence on the card | Lands |
| --- | --- | --- | --- | --- |
| `mthfr_c677t_homocysteine` | nutrition | TT and CT raise blood homocysteine | Holmes 2011, 53,643 people, functional, meta-analysis | well-established |
| `mthfr_c677t_venous_thrombosis` | physical health | MTHFR causes clots | MEGA, 9,231 people, OR 0.94 | limited |
| `mthfr_c677t_coronary_heart_disease` | physical health | MTHFR causes heart disease | Clarke 2012, 116,136 people, OR 1.02 | limited |
| `mthfr_c677t_depression` | mental health | MTHFR causes depression | Gilbody 2007, OR 1.36, not replicated | limited |

"Lands" is the tier for a common, directly typed call whose ancestry matches the study. With
ancestry not yet computed, the nutrition card is capped at strong. The claim cards are never
above limited, for any genotype or observation, and a rare call still drops any of the four to
likely-artifact. `tests/engine/test_mthfr.py` pins all four landings.

## Decisions (owner, 2026-11-09)

Two questions were put to the owner after the evidence was read and before any card was
written. Each answer was the recommended option.

1. **A biochemistry card plus claim cards.** The nutrition card states what the variant
   measurably does. The three most-studied health claims each get a card in the section
   where the claim belongs, and section pointers link the four. The alternative was one
   nutrition card with every claim given only in its text, so none of them would be scored.
   Pregnancy loss and "methylation" are stated on the nutrition card instead, because a
   reproductive interpretation card must be a carrier card (knowledge schema 7), and no
   claim card was wanted for a single small study.
2. **A1298C is mentioned, not carded.** See [considered and not authored](#considered-and-not-authored).

## Why the claim cards land at limited

Each claim card records `tier: candidate_gene` and `replication: conflicting`. The calculator
caps conflicting replication at limited. These are the reasons for each card's replication
value:

- **Venous thrombosis.** Bezemer et al. note that earlier meta-analyses reported a weak TT
  effect, sensitive to selective publication. MEGA found none: TT OR 0.94 (0.81-1.08), CT 0.99
  (0.91-1.08), in 4,375 patients and 4,856 controls. ACMG describes the association as
  disproven by recent meta-analyses.
- **Coronary heart disease.** Klerk 2002 found TT OR 1.16 (1.05-1.28) in 40 studies and read
  it as support for homocysteine as a cause. Clarke 2012 set 86 published studies (OR 1.15,
  1.09-1.21) against 19 datasets where MTHFR had been genotyped incidentally and never
  published (OR 1.02, 0.98-1.07). The difference was significant (P = 0.001), and the authors
  attribute it to publication bias or methodological problems.
- **Depression.** Gilbody 2007 pooled 1,280 cases and 10,429 controls: TT OR 1.36
  (1.11-1.67). Border 2019 tested rs1801133 among 18 historical candidate genes in samples of
  62,138 to 443,264 people. Its smallest P value across eight main-effect models was 0.034,
  against a preregistered threshold of 0.05/16 = 3.13e-3.

**A limited tier here does not mean the null result is uncertain.** The tier rates support
for the claimed association. Each claim card states this in its first caveat, because a
reader could otherwise take "limited" as "we're not sure there's no effect". The estimate
on each card is the best one available, not the published one the claim rested on. For
heart disease that is 1.02, not 1.15. The claim's original figure is given beside it.

Two calculator behaviours were observed rather than tuned:

- **`replication: none` scores higher than `conflicting`.** A small unreplicated candidate
  study, such as Friso's methylation result, would land at moderate, above the three claims
  that were tested and failed. That ordering is defensible: an untested claim is not the
  same as a refuted one. It is also why "methylation" is not a card. A card would rank one
  study of 292 people above three refuted claims, and its outcome (DNA methylation in blood
  cells) is not a health effect.
- **The comparator genotype is capped at limited.** On the claim cards, CC, and CT where no
  heterozygote estimate was verified, carry `evidence: null`. No other genotype's odds ratio
  may describe them (knowledge schema 3), so they are capped at limited too. On the
  nutrition card CC keeps the card-level estimate it is the comparator for, as the M12.1
  cards do.

## Marker audit (measured 2026-11-09)

| | rs1801133 (C677T) | rs1801131 (A1298C) |
| --- | --- | --- |
| GRCh37 | chr1:11856378 | chr1:11854476 |
| dbSNP b157 REF>ALTs | G>A,C,T | T>A,C,G |
| On the AncestryDNA V2.0 array | yes | yes |
| ClinVar (pinned 2026-08-04) | 3520, `NM_005957.5(MTHFR):c.665C>T (p.Ala222Val)`, drug response, expert panel | 3521, `c.1286A>C (p.Glu429Ala)`, benign/likely benign and other |
| gnomAD r2.1.1 exomes | A: 31.5% all, 34.0% NFE, 50.3% AMR, 29.1% EAS, 14.5% SAS, 10.8% AFR | G: 28.9% all, 31.9% NFE, 41.2% SAS |

The array was read for rsID, chromosome and position only. ClinVar's live record for 3521 now
reads "conflicting classifications"; the pinned release is what the run uses. Neither record
is pathogenic and both alleles are common, so the AGENTS.md §4.1 rare-call gate has nothing to
gate.

### Strand: how 677T was bound to forward A

MTHFR is on the reverse strand, so papers name the coding change C>T and dbSNP's forward
strand reads G>A. Two independent checks, as in M12.1:

- **ClinVar.** Record 3520 is forward G>A at this position and is named `c.665C>T
  (p.Ala222Val)`. The ACMG guideline gives the same change as c.665C→T (p.Ala222Val),
  "historically more commonly referred to as C677T".
- **Frequency.** Forward A is 31.5% of gnomAD exome alleles. Frosst et al. found the mutation
  on about 38% of unselected chromosomes, and Grarup et al. report the folate-raising G (677C)
  at 0.668 in Iceland, so 677T is 0.332. Forward A is also 50.3% of Latino alleles and 10.8%
  of African ones. Botto and Yang give TT at 20% or more among US Hispanics and 1% or less
  among Black people in Africa and the US, and ACMG gives more than 25% of Hispanics.

dbSNP lists C and T as further alternates, so every card uses `strand: forward_only`. A call
of C or T is an allele mismatch, never a reverse-strand reading, and a test checks all three
complemented pairs.

## Evidence, card by card

**Homocysteine and folate.** The estimates are Holmes 2011's genetic meta-analysis: TT
minus CC 2.10 micromol/L (1.71-2.50, I2 83.5%) and CT minus CC 0.42 (0.30-0.54, I2 49.3%).
Both come from the 67 datasets and 53,643 participants without cardiovascular disease.
59,995 is the total with homocysteine data, and a test rejects it as the denominator. The
effect depends on folate. It was 3.12 (2.23-4.01) in Asia without fortification and 0.13
(-0.85 to 1.11) in fortified America, Australia and New Zealand, which is the face's "3.1 in
Asia, 0.1 where food is fortified". Ancestry is recorded as MULTI.

The tier is functional because Frosst 1995 showed the mechanism. The 677T enzyme is
thermolabile with reduced activity in lymphocyte extracts, and in vitro expression of the
mutated cDNA confirmed the thermolability.

The folate figures come from three sources:

- Grarup 2013 Table 2: per 677C allele, 0.096 quantile-normalised units in Iceland and 0.18 in
  each Danish cohort, combined N 37,337, P 9.5e-53.
- Tsang 2015, women aged 12 to 49, microbiological assay: serum and plasma folate CC > TT by
  13% (7-18%) and CC > CT by 7% (1-12%).
- Crider 2011, a trial in 932 Chinese women: TT had lower folate at every folic acid dose,
  and genotype did not significantly change the response to dose.

**Venous thrombosis.** Bezemer 2007 (MEGA), as above. The study's setting comes from an
earlier MEGA report: a population-based case-control study at anticoagulation clinics in the
Netherlands (Blom 2005). Ancestry is EUR.

**Coronary heart disease.** Clarke 2012's unpublished datasets came from C4D, CARDIoGRAM,
ISIS, INTERHEART and Japanese genotyping studies, and include the South Asian LOLIPOP and
PROMIS studies. Ancestry is MULTI. The unsupplemented low-folate estimate was 1.01
(0.95-1.07), where TT raises homocysteine more than elsewhere.

The paper gives no CT estimate in its text: it says adding CT "does not materially alter"
the result. So CT carries `evidence: null` rather than borrowing TT's odds ratio. Van Meurs
2013's 13-locus homocysteine score was not associated with coronary artery disease either
(OR 1.01, 0.98-1.04, 31,400 cases). Its full text was not retrievable, so the abstract's
score-level result is cited, not a per-SNP figure.

**Depression.** Only Gilbody 2007's abstract could be read. The publisher returned a paywall
to every fetch, and the paper is not in PMC. The pooled studies' populations were therefore
not verified, and the card records `ancestry: [UNKNOWN]` and says so. Border 2019's samples
are UK Biobank (unrelated, European ancestry) and the Psychiatric Genomics Consortium with UK
cohorts removed.

## What the nutrition card says about the other claims

These are stated with their sources, not scored:

- **Testing.** ACMG 2013, Box 1: MTHFR genotyping should not be ordered for thrombophilia or
  recurrent pregnancy loss, or for at-risk relatives. The ACMG Board reaffirmed it on 27 April
  2020 and reclassified it as a Clinical Practice Resource, because it no longer meets the
  College's criteria for an evidence-based practice guideline. So the cards cite it for what it
  says, and no card uses the `clinical_guideline` tier on its strength.
- **Folic acid and neural tube defects.** ACMG: MTHFR status does not change the standard
  folic acid recommendation. Botto and Yang: maternal TT spina bifida pooled OR 2.0
  (1.5-2.8). Neither source gives an absolute rate, and the card says so.
- **Pregnancy loss.** ACMG says a TT homozygote with normal homocysteine has no evidence of
  increased risk. Rey 2003 found no significant association across 31 studies; only its
  abstract was read.
- **"Methylation".** Friso 2002: genomic DNA methylation in 105 TT against 187 CC was 32.23
  against 62.24 ng 5-methylcytosine per microgram of DNA, all of the difference among TT with
  low folate. No replication or health outcome was verified.

## Considered and not authored

| Candidate | Reason |
| --- | --- |
| A1298C (rs1801131) | Owner decision. On the array, ClinVar benign/likely benign in the pinned release. Van der Put 1998 found reduced enzyme activity but no rise in homocysteine or fall in folate on its own; its full text is PDF-only in PMC and was not retrieved, so no per-genotype estimate with a denominator was verified. ACMG lists the 1298 homozygote and the 677/1298 compound heterozygote as unlikely to be of clinical significance. A compound-heterozygote call needs both markers, and the multi-marker engine reports a double heterozygote as phase-ambiguous. The nutrition card's caveat covers it. |
| Pregnancy loss card | A reproductive interpretation card must be a carrier card (schema 7). Stated on the nutrition card. |
| "Methylation" card | One study of 292 people, unreplicated, with no health outcome. Stated on the nutrition card. |
| Stroke | Holmes 2011 found TT stroke OR 1.68 (1.44-1.97) in Asia against 1.03 (0.84-1.25) in fortified regions. It also found strong small-study bias in Asia (Egger P = 0.002) and an OR of 1.28 (1.11-1.48) in studies with 400 or more stroke events. A card would need the folate-region split on its face and a decision on which estimate stands. Not authored; the heart-disease card says it does not assess stroke. |
| Schizophrenia, bipolar disorder | Gilbody 2007 reports TT OR 1.44 and 1.82, but this audit verified no large replication test for either. The depression card names them and assesses neither. |
| Neural tube defects card | A real association (Botto and Yang), but the risk concerns a pregnancy, and the reproductive section accepts only carrier cards. Stated on the nutrition card. |

## Validation

`tests/engine/test_mthfr.py` checks the following:

- **Bindings.** Each card's locus, forward alleles, section, sample size, estimate and interval,
  measure, tier, replication, study population and DOIs are bound to the papers, along with
  every outcome-specific estimate and every `evidence: null`.
- **Mutation regressions.** Five reversed directions or nulls and a wrong unit fail. So do
  five borrowed values:
  - Holmes's 59,995 as the denominator;
  - Clarke's published 1.15 in place of the unpublished 1.02;
  - TT's homocysteine difference on CT;
  - a European label on Gilbody's unverified populations;
  - a comparator inheriting the TT odds ratio.
- **Landings.** Every card and genotype lands at the tier in the table above. Across
  frequencies and ancestry matches, no claim card outranks the nutrition card or rises above
  limited.
- **Matching.** Every genotype is matched. Missing and I/D inputs stay unresolved, all
  three complemented pairs are mismatches, and rarity still forces `likely-artifact`.
- **Saved interfaces.** A saved bundle, `runs show` (JSON and text) and the dashboard keep
  each claim, citation and estimate, and a null estimate stays null. The pointers render in
  nutrition, physical health and mental health.
- **Native.** gnomAD binds forward A to 677T's published frequencies, and ClinVar names it as
  the Ala222Val missense, which is not pathogenic. Both skip where the indexes are absent, as
  on CI.

The validation record is in the [handoff](handoff.md#accepted-m122-mthfr).
