# Carrier status (M11.5)

M11.5 adds carrier cards for recessive conditions this array can actually type, in the
**reproductive** section (AGENTS.md §3.1: about offspring, not self). Fifteen new cards
cover nine conditions; the existing HFE C282Y card in physical health joins the same
panel without being written twice. The set of typed markers is recorded as data —
**the carrier panel** — so M11.6's section-level incompleteness statement can say exactly
what it excludes.

No personal export was read for this milestone. The array's marker list was measured
from the export's first three columns (rsID, chromosome, position) only; no genotype
column was read, and every test genotype is fabricated.

## Contract recorded before implementation

Knowledge schema 7 adds an optional `carrier` block to single-marker interpretation cards.
Bundle format 24 adds a `carrier` record to every saved card (`null` except on a carrier
card). Formats 1–23 carry no carrier record and are read unchanged. Carrier panel schema 1
is the JSON `genetics cards carriers --json` emits. No new private file type is added:
carrier records live in the existing gitignored `cards.run.json`.

### Authoring

```yaml
schema_version: 7
cards:
  - id: cftr_g542x_carrier
    section: reproductive          # reproductive, or physical_health (see HFE below)
    kind: interpretation
    title: Cystic fibrosis carrier status (CFTR G542X)
    gene: CFTR
    carrier:
      condition: Cystic fibrosis
      inheritance: autosomal_recessive   # the only value; see "X-linked" below
      variant: "CFTR c.1624G>T (p.Gly542Ter), G542X"
      pathogenic_allele: T         # forward-strand GRCh37 base; one of the two alleles
      clinvar: 7115                # ClinVar VariationID classifying that allele
      typed_scope: >-              # literal text, shown on the card face
        This card types G542X only. ...
    match:
      strand: forward_only         # required
      variants:
        - {rsid: rs113993959, chrom: "7", pos_grch37: 117227832, alleles: [G, T]}
      genotypes: {GG: no_g542x, GT: one_g542x, TT: two_g542x}
    outcomes:                      # every outcome needs literal risk_context
      no_g542x: {evidence: null, summary: ..., detail: ..., risk_context: ...}
      one_g542x: {summary: ..., detail: ..., risk_context: ...}
      two_g542x: {evidence: null, summary: ..., detail: ..., risk_context: ...}
    evidence: {...}
    citations: [...]
```

The loader refuses a declaration that is not bound to its genotype map:

- exactly one autosomal, biallelic marker, matched `forward_only`;
- `pathogenic_allele` is one of the marker's two declared alleles;
- zero, one and two copies of it each map to **their own** outcome;
- every outcome carries `risk_context`;
- `typed_scope` is literal (no placeholders);
- any interpretation card in the reproductive section must declare `carrier`;
- `carrier` on any other card kind, or outside reproductive/physical health, is refused.

Outcome names are free text, so the loader cannot see a map that sends a heterozygote to
the *no-copy prose*. `tests/engine/test_carrier.py` reads every committed card's face
against the state its call derives ("no", "one", "two" copies), and a swapped-map mutation
regression proves that check fails.

### The state is derived, never authored

The engine counts copies of the declared pathogenic allele in the matched call and saves
`state` (`non_carrier`, `carrier`, `two_copies`) and `pathogenic_copies` beside the frozen
declaration. Anything that is not a match — marker absent, no-call, conflicting duplicate
probes, allele mismatch, strand ambiguity — saves `state: null`, shown as "Not
determined". **A missing result is never a non-carrier result.** On write and on read the
bundle re-derives the state from the card's own saved match and refuses a record that
disagrees; the current knowledge pack is not consulted, so a saved run keeps the
declaration it was written with.

### Strand-symmetric markers

Four markers are A/T or C/G pairs: HbS (rs334), CFTR N1303K (rs80034486), HEXA IVS12+1G>C
(rs147324677) and FANCC IVS4+4A>T (rs104886456). The matcher does not trust a vendor's
forward-strand claim at such a site, and `forward_only` does not change that: a homozygous
call reads the same on both strands, so "no copy" and "two copies" are indistinguishable,
and the card reports `strand_ambiguous` with both candidate outcomes rather than choosing.
A heterozygote is one copy on either strand, so **a carrier is still reported**; the matcher
leaves the oriented genotype empty there and the state is taken from the observed call,
which the bundle checks is strand-invariant. The panel marks these entries
`strand_symmetric: true`. A no-call at such a marker can still be filled by imputation,
whose alleles are reference-oriented.

### Evidence rule

The carrier outcome uses the card-level evidence; the no-copy and two-copy outcomes assign
no phenotype estimate (`evidence: null`), so their confidence is at most `limited` and
rarity still forces `likely-artifact`. The card-level effect is a `proportion` whose
context says which of two published quantities it is:

- **case composition** — the allele's share of disease alleles in a patient series
  (Watson 2004 for CFTR, Hillert 2020 for PAH, Andresen 2001 for ACADM); or
- **carrier prevalence** — the allele's carrier frequency in a screened population, where
  that is what the literature reports for it (Ojodu 2014 for HbS, Scott 2010 for the
  Ashkenazi-panel alleles).

Neither is a risk for the carrier, and both contexts say so. The calculator scores a
proportion as its value, so the effect component contributes little for every carrier card;
confidence is carried by source tier, replication and measurement reliability. No
calculator change was made. The scoped rare-call PPV (M7.3) applies automatically, as on
every interpretation card; no carrier allele's maximum gnomAD population frequency falls
below the 0.001% band.

### Absolute context

Every outcome's `risk_context` states the population carrier frequency and the
couple-level figure: if a reproductive partner also carries a disease-causing allele in the
same gene, each pregnancy has a 1 in 4 chance of a child with two (the Mendelian
expectation). Scott 2010's DNA-confirmed carrier-couple pregnancies are cited per condition
where it reports one (CF 33/134, Tay-Sachs 31/102, Gaucher 19/65, Canavan 6/28; 107/404
pooled across 16 conditions). **No offspring risk is computed for an unknown partner**, and
the detail view says so. A no-copy outcome states the population carrier frequency without
computing a residual risk from one marker.

### Where a reader sees it

The card face shows "Carrier status: \<state\> · \<condition\>, autosomal recessive" and the
`typed_scope` sentence beside the summary and `risk_context`. The detail view adds a
carrier block with the typed allele, the forward-strand base and a ClinVar link.
`genetics runs show` prints the same line and scope; `--json` includes the record.
`genetics cards carriers [--json]` lists the panel from the knowledge pack alone — it reads
no run and no genotype.

### X-linked conditions

`inheritance` accepts only `autosomal_recessive`. An X-linked carrier claim needs the M6.4
sex call and PAR-aware ploidy before a call means anything, and the X-linked conditions
carrier screening names — fragile X (a repeat expansion), Duchenne (mostly deletions),
haemophilia A (inversions) — are outside what genotype calls can show in any case. G6PD,
the one X-linked gene the array types well, stays a pharmacogenomics call (M10.2). The
value is added when a card needs it, with its own ploidy rule.

## The carrier panel

Sixteen typed markers over nine conditions (`genetics cards carriers`):

| Condition | Card | Marker | Typed allele | Panel effect | Symmetric |
|---|---|---|---|---|---|
| Canavan disease | `aspa_e285a_carrier` | rs28940279 | ASPA E285A | 1.52% AJ carriers | |
| Cystic fibrosis | `cftr_g542x_carrier` | rs113993959 | G542X | 2.28% of NH-white CF chromosomes | |
| Cystic fibrosis | `cftr_621_1g_t_carrier` | rs78756941 | 621+1G>T | 1.57% | |
| Cystic fibrosis | `cftr_g551d_carrier` | rs75527207 | G551D | 2.25% | |
| Cystic fibrosis | `cftr_r553x_carrier` | rs74597325 | R553X | 0.87% | |
| Cystic fibrosis | `cftr_w1282x_carrier` | rs77010898 | W1282X | 1.50% (45.92% AJ) | |
| Cystic fibrosis | `cftr_n1303k_carrier` | rs80034486 | N1303K | 1.27% | C/G |
| Fanconi anaemia C | `fancc_ivs4_4a_t_carrier` | rs104886456 | IVS4+4A>T | 1.00% AJ carriers | A/T |
| Gaucher disease | `gba_n370s_carrier` | rs76763715 | GBA1 N370S | 5.90% AJ carriers | |
| HFE haemochromatosis | `hfe_c282y_iron_overload` | rs1800562 | C282Y | (physical health card) | |
| MCAD deficiency | `acadm_k304e_carrier` | rs77931234 | K304E | 99/124 screen-positive alleles | |
| Phenylketonuria | `pah_r408w_carrier` | rs5030858 | R408W | 22.2% of PKU alleles | |
| Phenylketonuria | `pah_ivs10_11g_a_carrier` | rs5030855 | IVS10-11G>A | 6.4% | |
| Phenylketonuria | `pah_r261q_carrier` | rs5030849 | R261Q | 5.5% | |
| Sickle cell disease | `hbb_hbs_carrier` | rs334 | HbS | 7.31% trait, Black US newborns | A/T |
| Tay-Sachs disease | `hexa_ivs12_1g_c_carrier` | rs147324677 | IVS12+1G>C | 0.49% AJ carriers (5/1,015) | C/G |

### Placement decisions

- **HFE C282Y stays in physical health.** Its two-copy state is the self-relevant claim,
  with cohort penetrance on the card already. It gains a `carrier` block and so joins the
  panel; one card per fact, as M11.4 did for HLA-B.
- **G6PD stays in pharmacogenomics** (X-linked; see above). **APOE** is not a recessive
  carrier state and is not in the panel.
- **GBA1 N370S** sits in reproductive. Its detail states the separately reported Parkinson
  disease association of GBA heterozygosity (Sidransky 2009: L444P or N370S in 15% of
  Ashkenazi patients vs 3% of controls; OR 5.43 for any GBA mutation across 16 centres)
  and says the card does not evaluate it.
- **Ashkenazi estimates carry `EUR`.** The 1000 Genomes vocabulary has no Ashkenazi
  category; every such context names the Ashkenazi New York cohort explicitly.

## Candidate audit (measured 2026-10-25)

Each candidate was checked against the pinned dbSNP b157 GRCh37 index, the AncestryDNA
V2.0 marker list (rsID and position only), the pinned ClinVar release (2026-08-04 GRCh37
VCF) and the gnomAD r2.1.1 exomes index. A candidate is **tractable** when it is a typed
SNV, its pathogenic allele has a non-conflicting ClinVar P/LP classification, and gnomAD
has a PASS record for it. `tests/engine/test_carrier_references.py` re-checks the ClinVar
and gnomAD half for every panel entry against the fetched indexes (it skips where they are
absent, as on CI); `genetics cards lint` resolves all 54 marker keys against dbSNP.

**Not typed as an SNV — excluded by the array or by §4.2:**

| Candidate | Reason |
|---|---|
| CFTR F508del (rs113993960) | Indel on the array (I/D, no sequence; §4.2). About 72% of NH-white CF chromosomes. |
| GJB2 35delG (rs80338939), 167delT (rs80338943) | Indels (§4.2). |
| HEXA 1278insTATC (rs387906309) | Insertion (§4.2); the common Ashkenazi Tay-Sachs allele. |
| SMPD1 fsP330 (rs120074118) | Indel (§4.2). |
| HBB HbC (rs33930165), HbE (rs33950507), IVS-I-1 (rs33971440) | Not on the array. |
| GBA1 L444P (rs421016), HEXA G269S (rs121907954) | Not on the array. |
| DHCR7 IVS8-1G>C (rs138659167), ELP1 IVS20+6T>C (rs111033171) | Not on the array. |
| CFTR 3849+10kbC>T (rs75039782), CBS I278T (rs5742905) | Not on the array. |
| SMN1 (SMA), HBA1/HBA2 (alpha-thalassaemia) | Copy-number states; impossibility cards since M3.7. |

**Typed, but failing a criterion:**

| Candidate | Reason |
|---|---|
| GALT Q188R (rs75391579) | ClinVar aggregate is "conflicting classifications". |
| BTD D444H (rs13078881) | ClinVar G>C aggregate is conflicting. |
| HFE H63D (rs1799945) | ClinVar aggregate is conflicting. |
| HBB −29A>G (rs34598529) | No gnomAD exomes record (promoter, outside the capture). |

**Tractable, not authored in M11.5** — each passes the measured criteria but was not
written, for the reason given. They are not in the panel, and M11.6 must not count them as
typed:

| Candidate | Reason |
|---|---|
| HBB codon 39 (rs11549407), IVS-I-110 (rs35004220), IVS-I-5 (rs33915217) | No per-variant beta-thalassaemia allele share or carrier prevalence was verified from a readable primary source this session. |
| CFTR R1162X (rs74767530), R347P (rs77932196), 1717-1G>A (rs76713772) | Below 0.5% of NH-white CF chromosomes; Watson 2004 prints 1717-1G>A as "1717-1G>T", so its row was not used. |
| CFTR R117H (rs78655421) | Consequence depends on the cis poly-T tract, which the array does not type. |
| PAH IVS12+1G>A (rs5030861) | Its allele share is only in Hillert 2020's supplementary table, which was not read. |
| ASPA Y231X (rs28940574) | Second Ashkenazi Canavan allele; deferred with the other secondary alleles. |
| SERPINA1 PiZ (rs28929474), PiS (rs17580) | Placement undecided: PiZZ is a self-health claim with adult lung and liver risk, PiS is pathogenic mainly with Z. Belongs with physical health or M12. |
| ATP7B H1069Q (rs76151636) | No per-variant source verified this session. |
| MEFV M694V (rs61752717), V726A (rs28940579) | ClinVar names both dominant and recessive FMF; the inheritance a card would state is unsettled. |
| GJB2 V37I (rs72474224), M34T (rs35887622) | Mild or debated penetrance; not authored without a penetrance source. |
| ABCA4 G1961E (rs1800553) | Reported as a mild allele; not authored without a penetrance source. |
| MUTYH Y179C (rs34612342), G396D (rs36053993) | ACMG secondary-finding genes, already surfaced by M7.4. |
| HEXA IVS9+1G>A (rs76173977) | Rare (0/1,015 Ashkenazi carriers in Scott 2010); first mistaken for IVS12+1G>C during this audit. |

## Residual limits, recorded rather than fixed

- **The effect component reflects allele share or prevalence, not consequence.** A minor
  CF allele's carrier call scores lower on that 15% component than HbS's; the tier is
  dominated by source tier, replication and frequency. Recorded so nobody reads the tier
  gap as a difference in how reliable the call is.
- **Homozygous calls at the four symmetric markers are never interpreted from a direct
  call.** A reader with the common homozygote sees "strand ambiguous" on those four cards.
- **Watson 2004's sample size.** The card states the 37,263 non-Hispanic white CF
  chromosomes in the CF Foundation data the working group analysed; Table 1 also draws on CF
  Consortium data described in Palomaki 2004, which was not read.
- **No penetrance is assigned to two-copy outcomes.** Each says what the genotype is
  associated with and that an unexpected two-copy call is more often a genotyping error.

## Validation

Recorded in [the handoff](handoff.md#accepted-m115-carrier-status).
