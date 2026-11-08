# Nutrition and metabolism (M12.1)

M12.1 fills the nutrition section. It has nine cards: seven new interpretation cards and two
moved from traits. It also points to two cards that stay in their own sections. All the new
cards use knowledge schema 3, and none needs an engine, schema or bundle-format change.
M12.2's MTHFR card is next.

| Card | Marker | Claim | Evidence on the card |
| --- | --- | --- | --- |
| `mcm6_lactase_persistence` | rs4988235 | Adult lactase persistence | Moved from traits, unchanged |
| `aldh2_alcohol_flushing` | rs671 | Alcohol flushing | Moved from traits, unchanged |
| `cyp1a2_coffee_intake` | rs2472297 | Cups of coffee a day | GWAS, independent replication |
| `cyp1a2_rs762551_caffeine` | rs762551 | The "slow metaboliser" marker | Candidate gene, unreplicated |
| `adh1b_alcohol_intake` | rs1229984 | Weekly alcohol intake | 56-study meta-analysis |
| `fut2_secretor_status` | rs601338 | Secretor status and GII.4 norovirus | Functional, meta-analysis |
| `fut2_vitamin_b12` | rs602662 | Serum vitamin B12 | GWAS, independent replication |
| `gc_vitamin_d` | rs2282679 | Serum 25-hydroxyvitamin D | GWAS, independent replication |
| `folr3_serum_folate` | rs652197 | Serum folate (imputed only) | GWAS, independent replication |

## Decisions (owner, 2026-11-08)

Four questions were put to the owner before any card was written. Each answer was the
recommended option.

1. **Lactase and ALDH2 move to nutrition.** A card renders in one section, and the
   roadmap names both under nutrition. The card IDs and text are unchanged, and
   `knowledge/nutrition/lactase_alcohol.yaml` changes only `section`. Saved bundles record
   each card's section, so runs saved earlier still show both under traits. Traits keeps 29
   cards.
2. **HFE and celiac stay where they are, and nutrition points to them.** HFE C282Y carries
   a carrier declaration, which only physical health and reproductive accept. The celiac
   card is `kind: hla`, which only immunogenetics and pharmacogenomics accept. Moving either
   would need a schema change. Instead, `SectionInfo.related`
   (`engine/sections.py`) names them. The dashboard's nutrition panel links to each card in
   its own section, and `genetics runs show` prints the same line. A pointer is not a copy:
   it is not counted in the panel, and it appears only when the grid is grouped by section.
   A run saved before a card existed shows the card's label marked "not in this run" rather
   than a dead link.
3. **Folate goes to M12.2's MTHFR card, after a check for other loci.** The check found one.
   Grarup 2013 reports two genome-wide folate loci: MTHFR and FOLR3. FOLR3 rs652197 is not on
   the array, but cards already read off-array markers from imputation (`rs72921001`
   cilantro, `rs429358` APOE). So the folate item gets the FOLR3 card here, and MTHFR, the
   larger locus, stays with M12.2.
4. **Both CYP1A2 markers get a card.** rs2472297 is the replicated GWAS signal. rs762551 is
   the marker consumer reports use, so its card states its actual evidence. Under the
   synthetic test inputs it lands at "moderate" at best. M12.2 applies the same treatment to
   MTHFR.

## Candidate audit (measured 2026-11-08)

Every marker was checked against the pinned dbSNP b157 GRCh37 index, the AncestryDNA V2.0
marker list (rsID and position only), the pinned ClinVar release (2026-08-04) and the gnomAD
r2.1.1 exomes index. Markers outside exons have no gnomAD exome record, so their population
frequencies were read from the INFO fields of the local 1000 Genomes phase 3 VCFs. All
frequencies are for the forward-strand allele named.

| Marker | dbSNP REF>ALTs | On array | ClinVar | Frequency |
| --- | --- | --- | --- | --- |
| rs2472297 | C>A,T | yes | none | 1000G T: EUR 21.5%, EAS 0%, AFR 1.4% |
| rs762551 | C>A,G | yes | 511079, likely benign, `CYP1A2 c.-9-154C>A` | 1000G A: EUR 68.0% |
| rs1229984 | T>A,C,G | yes | 18182, protective, `ADH1B c.143A= (p.His48=)` | gnomAD T: NFE 3.8%, EAS 73.9% |
| rs601338 | G>A | yes | 12945, benign, `FUT2 c.461G>A (p.Trp154Ter)` | gnomAD A: NFE 47.6%, EAS 0.2% |
| rs602662 | G>A | yes | 996599, `FUT2 c.772G>A (p.Gly258Ser)` | gnomAD A: NFE 50.5%, EAS 0.2% |
| rs2282679 | T>A,C,G | yes | none | 1000G G: EUR 24.7%, AFR 5.0% |
| rs652197 | C>A,T | **no** | none | 1000G C: EUR 13.5%, AFR 58.3% |

Five markers have extra alternates in dbSNP, so every card uses `strand: forward_only`. A
call carrying any other base is an allele mismatch, never a reverse-strand reading. Card lint
resolves all 61 pack marker keys against dbSNP.

### Strand: how each card's allele was bound to its paper

Papers name these alleles on the coding strand, or only as "minor" and "major". Each card's
forward-strand base was fixed by two independent checks, recorded here so a reviewer can
repeat them:

- **ADH1B (reverse strand).** Holmes et al. call His48 the "A allele" and report about 7%
  carriage in Europeans. ClinVar's record for the reference base is `c.143A= (p.His48=)`.
  The forward reference base is T, so His48 is forward T. gnomAD agrees: T is 3.8% of
  European exome alleles, about 7.5% carriage. A native test re-checks this. PharmGKB's
  record for rs1229984 (PA166156507) lists ADH1B*2 as a synonym.
- **FUT2 (forward strand).** ClinVar annotates forward G>A at rs601338 as nonsense
  (Trp154Ter in current RefSeq numbering, Trp143Ter in Kelly 1995 and Hazra 2008), and
  forward G>A at rs602662 as Gly258Ser. Hazra's Table 1 labels G as Gly, which matches.
  The same table labels rs601338's A allele "Trp", which contradicts ClinVar's consequence
  annotation. This card follows ClinVar.
- **CYP1A2 (forward strand).** ClinVar's `c.-9-154C>A` is forward C>A, and Sachse's C/A
  naming is the same, since a reverse-strand gene would read G/T. Sachse's 46% AA matches
  1000 Genomes' 68% A in Europeans. Sachse names the site by its position in intron 1 (734
  bases after the first transcribed base). It is rs762551 because PharmGKB's record for
  rs762551 (PA166154850) lists the intron 1 change `c.-9-154C>A` and the retired name
  CYP1A2*1F. The legacy "−163" counts from the start codon: 9 bases of exon 2 plus 154 of
  intron 1.
- **rs2472297.** The papers' T is forward T: 21.5% in 1000 Genomes Europeans, against 24%
  in the consortium and 27–29% in Iceland and the Netherlands.
- **GC rs2282679.** Wang 2010 names only "minor" (MAF 0.29) and "major". The minor allele
  is forward G (24.7% of European 1000 Genomes alleles). Table 2's minor homozygotes have the
  lowest 25-hydroxyvitamin D.
- **FOLR3 rs652197.** Grarup's effect allele is C, with EAF 0.179 in Iceland. Forward C
  is 13.5% of European 1000 Genomes alleles, and dbSNP lists C/T on the forward strand.

### The CYP1A2 label trap

Cornelis 2006 calls C carriers "*1F" and slow. Their 55% of cases and 54% of controls
carrying the allele matches the C allele: Sachse found 54% C carriers in Germany, and 1000
Genomes gives about 42% in its American samples. It cannot be A, which about 94% would
carry. Sulem 2011 uses *1F for the allele "suggested to correlate with increased CYP1A2
enzymatic activity in smokers", which is A in Sachse's data. The same star allele therefore
names opposite bases in two cited papers, and PharmGKB now lists CYP1A2*1F as retired.
The card uses forward-strand bases only and says so.

## Evidence, card by card

**Coffee, rs2472297.** The card's estimate is the 2015 Coffee and Caffeine Genetics
Consortium's stage 2 European replication: 0.11 cups a day per T allele (SE 0.01, n up to
30,062). Its interval, 0.09 to 0.13, is computed here as ±1.96 SE, and a test recomputes it.
Discovery gave 0.15 (n up to 91,462) and African Americans 0.19 (n up to 7,964). Sulem 2011
found about 0.2 cups a day in 10,661 coffee drinkers, 0.55% of the variance. Sulem's
mechanism, faster clearance, "remains to be proven experimentally", and the card repeats
that wording rather than calling it a metabolism marker.

**The "slow metaboliser" marker, rs762551.** There are two outcome-specific estimates, both
candidate-gene and both recorded as unreplicated:

- **AA:** Sachse 1999 found a difference only among 51 smokers: a 5-hour
  paraxanthine/caffeine ratio of 1.37 for AA against 0.88 for AC (difference 0.48, 95% CI
  0.15–0.81). The 185 non-smokers showed no genotype difference.
- **C carriers:** Cornelis 2006 compared 2,014 cases with 2,014 controls in Costa Rica.
  Four or more cups a day went with nonfatal myocardial infarction among C carriers only,
  OR 1.64 (1.14–2.34) in 2,196 people, with interaction P = 0.04.

Sulem 2011 found that rs762551's nominal association with coffee intake (P = 0.008) did not
survive adjustment for rs2472297 (P = 0.21). This audit did not verify an independent
replication of either estimate, and "none" records that. It does not claim that no
replication exists anywhere.

**ADH1B, rs1229984.** Holmes 2014, Table 1: His48 carriers drank 17.22% fewer units a week
(95% CI 15.55–18.86) in 218,969 people of European descent from 46 studies. Binge drinking
OR 0.78, abstention OR 1.27. The study used a dominant model, so the two-copy outcome says
that no separate estimate exists. The tier is GWAS: P = 5.5e-76 across the 46 of its 56
studies that recorded intake.
ADH1B Arg370Cys (rs2066702), the variant with that role in many people of African ancestry,
is not on the array.

**FUT2 secretor status, rs601338.** The estimate is Kambhampati 2016's GII.4 subgroup:
secretors had 9.89 times the odds of infection of non-secretors (3.94–24.84), across 12
studies. The paper's text does not give the subgroup's size. Its Figure 2 lists each
study's counts. Summed, they are 2,268 participants, and 7 of the 469 infected people were
non-secretors. These are the card's sample size and the 7-of-469 figure, read from the
figure. The overall norovirus OR was 4.2 (18 studies, I2 73%), with publication bias
(P < .001), and GI strains showed no significant difference. Kelly 1995 supplies the
genotype-to-phenotype link: about 20% of randomly chosen people were homozygous, as were all
six non-secretors tested. Thorven 2005 found no non-secretor among 53 symptomatic Swedish
patients, against 20% of 104 blood donors. The tier is functional because the null allele
inactivates the enzyme and the virus binds the antigens the enzyme makes. The meta-analysis
counts carriers of any FUT2 null allele as non-secretors, which the card says.

**FUT2 and vitamin B12, rs602662.** Grarup 2013 gives 0.16 quantile-normalised units per A
allele in 37,283 Icelanders, 0.19 and 0.23 in two Danish cohorts, and P = 2.4e-139 combined.
No standard error is printed, so the card gives no interval and the effect component takes
its neutral value. Hazra 2008, which first reported the locus in Nurses' Health Study women,
gives geometric means of 487.7 pg/ml for AA, 413.4 for AG and 413.5 for GG. That pattern is
recessive in that sample, and the AG card says so beside the additive Icelandic estimate.
rs602662 was chosen over rs601338 and Hazra's proxy rs492602 because both studies report it
directly.

**GC and vitamin D, rs2282679.** The estimates are Wang 2010's Framingham means from Table 2
(n 5,656): 82.6, 74.8 and 64.6 nmol/L for TT, GT and GG. GG and GT carry their own
differences, −18.0 and −7.8 nmol/L, with intervals computed from the two printed standard
errors. A test recomputes both. The per-allele odds ratio for 25-hydroxyvitamin D below 75
nmol/L, 1.63 (1.53–1.73), is quoted in the text rather than used as the estimate. It comes
from four cohorts whose combined size the main text does not state, so pairing it with a
sample size would borrow a denominator. The same allele lowers vitamin D binding protein, and
the card states the authors' caution that lower total 25-hydroxyvitamin D may not mean less
vitamin D reaches tissues.

**FOLR3 and folate, rs652197.** Grarup 2013, Table 2: 0.069 per C allele in 28,913
Icelanders, then 0.066 and 0.071 in the Danish cohorts, combined P = 1.4e-12. A FOLR3 2-base
frameshift associated more strongly (0.087 SD) and is in partial linkage disequilibrium with
rs652197 (r2 0.51). It is an indel and is not in the pinned dbSNP index, so it is not
matched (AGENTS.md §4.2). rs652197 is off the array: a `--no-impute` run reports it as
absent, and an imputed run carries its imputation quality into confidence.

## Considered and not authored

| Candidate | Reason |
| --- | --- |
| ADH1B Arg370Cys (rs2066702) | Not on the array. |
| FOLR3 c.318_319insTA (rs139130389) | Indel (§4.2); not in the dbSNP b157 index. |
| MTHFR C677T (rs1801133) | M12.2. |
| FUT2 385A>T (rs1047781), East Asian weak secretor | On the array, ClinVar benign, gnomAD PASS. No per-genotype secretor or infection estimate was verified this session. Tractable, not authored; the secretor card's caveat names it. |
| FUT2 rs492602 | Hazra's proxy for rs601338. rs602662 is reported directly by both B12 studies. |
| TCN1 rs34324219, CUBN rs1801222, CD320 rs2336573, CLYBL rs41281112 | B12 loci on the array with Grarup 2013 Table 1 estimates. Tractable, not authored: M12.1 has one B12 card. |
| DHCR7 rs12785878, CYP2R1 rs10741657 | Wang 2010's other vitamin D loci, on the array, each OR 1.21 per allele. Tractable, not authored: one vitamin D card, and GC is the largest locus. |
| GC rs7041 and rs4588 (Gc1f/Gc1s/Gc2) | On the array, but the isoforms are cis haplotypes and a double heterozygote cannot be phased from unphased calls. |
| Lactase −13907G (rs41525747), −13915G (rs41380347), −14010C (rs145946881) | On the array, with ClinVar "association" records. They would extend the lactase card beyond European-derived populations. Not authored in M12.1 because no per-genotype estimate was verified and gnomAD exomes has no frequency for them. A follow-up candidate. |
| TMPRSS6 rs855791 | Iron-status locus on the array; outside M12.1's listed items. |

## What the cards do not say

None of these cards estimates a person's intake, blood level or deficiency. Each estimate is
an average difference between genotype groups, beside the group's own absolute values where
the paper gives them. Every card names the populations its estimate comes from. The
confidence tier describes how well the association is supported, not how large or important
it is. For example, a 0.11 cups-a-day effect can rest on very strong evidence.

## Validation

`tests/engine/test_nutrition.py` checks the following:

- **Bindings.** Each card's locus, forward alleles, sample size, effect, measure, tier,
  replication, study population, DOIs and genotype map are bound to the papers, along with
  each outcome-specific estimate.
- **Mutation regressions.** Seven reversed directions and a wrong unit each fail. So do four
  borrowed denominators, effects and populations: Cornelis's full 4,028, Wang's cohort total,
  GG's effect on GT, and a European label on the Costa Rican study.
- **Computed intervals.** Both are recomputed from the printed standard errors.
- **Matching.** Every genotype is matched. Missing and I/D inputs stay unresolved,
  complemented alleles are mismatches, and rarity still forces `likely-artifact`.
- **Moved cards.** The moved cards are unchanged and appear once in the pack.
- **Section pointer.** Every pointer names a card the pack holds in another section.
- **Saved interfaces.** A saved bundle, `runs show` (JSON and text) and the dashboard keep
  each claim, citation and estimate and show the pointer in both of its states. The pointer
  appears once, and not when the grid is grouped by tier.
- **Native.** The ADH1B and FUT2 strand reasoning is re-checked against gnomAD, and the
  ClinVar consequences of the card alleles against ClinVar. Both skip where the indexes are
  absent, as on CI.

The validation record for the milestone is in the [handoff](handoff.md#accepted-m121-nutrition-cards),
and the [session diff review](review_m121_session.md) records what a second read changed.
