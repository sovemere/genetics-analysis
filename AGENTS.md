# AGENTS.md

Operating guide for AI agents and humans working in this repository.

**This repo is public. It processes real personal genomes. Read §1 before writing code.**

## Git workflow

**In the CLI: commit and push directly to `main`.** Do not create a feature branch, do
not open a pull request, and do not ask whether to branch — unless the request explicitly
says to. This is a solo repository and the branch-then-PR ceremony is friction here.

**Feature branches and pull requests are for the web client only.**

This changes *where* commits go. It changes nothing about *what* may be committed: the
privacy rules in §1 and the pre-commit checklist in §7 apply in full to every push,
and pushing straight to `main` on a public repo makes them matter more, not less. Verify
before you push, because there is no review step to catch it.

---

## 0. What this project is

An offline-capable personal genome interpreter. It ingests a consumer DNA raw-data
export, evaluates it against reference databases downloaded at build time, and renders
an interactive encyclopedia-style dashboard. The four founding sections are **ancestry**,
**physical health**, **mental health**, and **psychometrics**; the full section map —
including pharmacogenomics, traits/morphology, immunogenetics and others — is **§3.1**,
and what the data provably *cannot* support is **§3.2**.

Each finding is a **card** — a short claim ("you likely have a functional copy of
*ABCC11* associated with wet earwax"), a confidence rating, and a detail view with the
supporting genotypes, effect sizes, caveats, and citations.

Everything the dashboard can compute is also reachable from a CLI that emits JSON, so a
CLI agent can be pointed at a saved run and asked to review, cross-check, or research a
card further.

**Design stance: this is an educational instrument, not a diagnostic.** Every module is
built to make its own uncertainty legible. See §4 — the uncertainty is large, well
documented, and non-negotiable.

### 0.1 Editorial stance (owner's judgment calls — do not silently reverse)

These are deliberate decisions by the repository owner. They diverge from how commercial
providers behave. Implement them; do not "helpfully" re-add the guardrails they remove.

**A. Show low-confidence findings. Flag them; never suppress them.**
A finding is not withheld because its confidence is low, its evidence is thin, or its
underlying chip call is unreliable. It is rendered *with that fact attached*. The design
target is calibration, not omission — the reader is trusted to handle "this is probably
a chip artifact" as long as the card says so unmissably.

This means confidence is a **first-class display property**, not a filter threshold.
Every card carries a reliability tier on its face, in the summary view, before the user
clicks through. A card whose tier is "likely artifact" still appears in the section; it
appears looking like what it is. Sorting and grouping by confidence is the right way to
keep a section readable — hiding rows is not.

**B. Include obscure, sensitive, and unflattering findings.**
Coverage is not trimmed for palatability. Traits that 23andMe and Ancestry decline to
report — behavioural, psychiatric, cognitive, morphological, sexual, addiction-related,
"unactionable" disease risk, unflattering trivia — are in scope, subject to the same
evidence and citation requirements as anything else. There is no separate, softer bar
for a sensitive claim and no separate, higher one either: the bar is the evidence.

The corollary is that presentation carries the weight instead. A sensitive card must be
*more* precise, not more vague: state the actual effect size, the base rate, the absolute
(not just relative) risk, and the population the estimate came from. Vagueness in a
sensitive card is a failure mode, not a kindness. Do not add euphemism, do not add
unsolicited advice, do not moralise, and do not gate a section behind a confirmation
click merely because its topic is uncomfortable.

**C. Compute cost is not a design constraint. Thoroughness and accuracy are.**
Long runtimes, multi-gigabyte reference downloads, and heavy dependencies (JVM, large
panels) are acceptable. Do not trade accuracy for speed, and do not default to a cheaper,
less accurate method. Imputation is on by default (§4.3). Where a fast approximation and
a slow exact method both exist, the slow one is the default and the fast one is the
opt-out. Progress reporting and resumability matter more than total wall-clock time.

**What these do *not* override:** §1 (privacy) is unaffected — none of this licenses
committing data. Citation requirements are unaffected: "include obscure findings" means
obscure *sourced* findings, never speculation. And accuracy caveats stay attached; the
owner's priority on accuracy is the reason they exist.

---

## 1. Privacy rules (hard constraints)

The threat model is *accidental commit to a public GitHub repo*.

**1.1 — Never commit genotype-derived data.** Not raw files, not parsed tables, not PCA
coordinates, not polygenic scores, not run bundles, not logs that echoed a genotype.
30–80 independent SNPs uniquely identify a person, and even aggregate allele-frequency
summaries can reveal an individual's presence in a dataset (Homer et al. 2008). There is
no safe "just a summary" tier. `.gitignore` encodes this; do not weaken it.

**1.2 — Test fixtures must be synthetic.** Never create a fixture by subsetting a real
person's file, and never "just a few hundred rows for a unit test." Generate fixtures
from reference allele frequencies with a fixed seed. They live in
`tests/fixtures/synthetic/`, which is the only fixture path git will accept.

**1.3 — Never paste genotypes into anything that leaves the machine.** Not commit
messages, not issue text, not a web search, not a prompt to a remote model, not an
artifact. When an agent needs to research a card online, it searches the *variant*
(`rs17822931`, ABCC11, earwax), never the *user's genotype at that variant*.

**1.4 — Reference data is fetched, never vendored.** See §5.

**1.5 — Default to writing outside the repo.** Analysis runs default to an OS user-data
directory (`%LOCALAPPDATA%/genetics-analysis/runs` on Windows). In-repo paths are
opt-in and gitignored as a second line of defense, not the first.

**1.6 — Before any commit, verify.** `git status --porcelain` must not list any
genotype-derived path. If you added a new output type, add its pattern to `.gitignore`
in the *same* commit that introduces it.

---

## 2. The input format (measured, not assumed)

All parsing targets this exact format. Verified against a real AncestryDNA V2.0 export:

```
#AncestryDNA raw data download
#... 17 more comment lines, including array version and build ...
rsid<TAB>chromosome<TAB>position<TAB>allele1<TAB>allele2
rs1000001<TAB>1<TAB>100001<TAB>G<TAB>G     <- homozygote
rs1000002<TAB>1<TAB>100042<TAB>A<TAB>G     <- heterozygote, alleles unordered
```

*(Illustrative values — invented, not copied from any real export. `<TAB>` is written out
rather than using real tabs for two reasons: invisible whitespace makes bad documentation
for a delimited format, and a literal genotype row here would be flagged by our own
pre-commit scanner — correctly, since §1.1 admits no exceptions for "only two markers".)*

- Tab-delimited, `#`-prefixed header block of ~17 lines, then a column header row.
- **Build GRCh37** (stated as "37.1"). Alleles reported on the **forward (+) strand**
  with respect to the reference.
- Reference export: **677,436 markers**, AncestryDNA array **V2.0**.

### Encoding facts that will bite you

| Fact | Detail | Consequence |
|---|---|---|
| **Numeric chromosomes** | `1`–`22` autosomes, `23`=X, `24`=Y, `25`=PAR, `26`=MT | Remap at ingest. Never treat `23`–`26` as autosomes. |
| **No-calls are `0 0`** | 550 markers in the reference export | Not `--`, not `NN`, not empty. Filter explicitly. |
| **Indels are `I`/`D`** | 8,830 markers | The inserted/deleted *sequence is not recorded*. See §4.2. |
| **Hemizygous is doubled** | X in a male sample: 25,227 hom / 4 het; Y: 1,658 calls | A hemizygous call is written `A A`, indistinguishable from a homozygote by string alone. Infer sex from X heterozygosity + Y call rate, then treat X/Y as hemizygous. Do not read "homozygous" off the X. |
| **Alleles are unordered** | `A G` and `G A` both occur | Sort the pair before comparison. Never compare `allele1` positionally. |
| **Tiny MT/Y panels** | 263 MT, 1,665 Y markers | Coarse haplogroups only. See §4.7. |
| **rsID is not a stable key** | dbSNP merges retire IDs; some are deleted or duplicated | Key on `(chrom, pos_grch37, alleles)`; use rsID as a secondary key with a merge table. |

### Plug-and-play requirement

The parser must sniff the vendor rather than assume AncestryDNA. Add new vendors as
adapters that normalize into the same internal table:

```
rsid | chrom (1-22,X,Y,PAR,MT) | pos_grch37 | a1 | a2 | genotype (sorted) | call_status
```

Everything downstream reads only that table. A new vendor must never require touching an
analysis module.

---

## 3. Architecture

```
AncestryDNA.txt
   ↓  ingest/       vendor adapters → normalized genotype table
   ↓  qc/           sex inference, call rate, build check, strand sanity check
   ↓  modules/      ancestry · health · mental_health · psychometrics
   ↓  evidence/     genotype + reference data → scored assertions
   ↓  run bundle    versioned, saveable, reloadable  (gitignored, stored outside repo)
   ↓
   ├─ ui/           local dashboard: sections → cards → detail modals
   └─ cli/          same analyses, JSON out — the agent interface
```

**Non-negotiable: one engine, two front-ends.** The CLI and the dashboard call the same
functions. If a computation is only reachable from the UI, an agent cannot review it,
and the "review this run" workflow silently breaks.

### Cards are data, not code

A card is a declarative record in `knowledge/` — matching criteria, interpretation
templates, confidence inputs, citations. The engine evaluates them. Adding a finding
means adding a knowledge-pack entry with sources, not writing a new module. This keeps
the citation trail intact and makes the corpus reviewable as a diff.

Every card must carry: evidence tier, effect size with units, study population ancestry,
sample size, replication status, and DOIs/accessions. A card without a citation does not
render.

### 3.1 Section map

The original four sections (ancestry / physical health / mental health / psychometrics)
under-cover what a 677k array plus the free corpus can support. **All thirteen sections
below are in v1 scope by owner decision** — see `phase1_roadmap.md` for build order.

| Section | Notes |
|---|---|
| **Ancestry** | PCA projection, admixture, ancient-DNA affinity, haplogroups (§4.7) |
| **Physical health** | ClinVar + PGS Catalog + GWAS Catalog; gated by §4.1 |
| **Mental health** | Attenuated by the 23andMe sumstat restriction (§5.3) |
| **Psychometrics** | Cognitive + personality. Weakest evidence base (§4.5) |
| **Pharmacogenomics** | *Highest actionable value.* See below |
| **Traits, morphology & sensory** | *Highest confidence in the app.* See below |
| **Nutrition & metabolism** | Lactase, CYP1A2 caffeine, ADH1B/ALDH2, HFE, celiac HLA-DQ2/DQ8, MTHFR |
| **Substance use & behavioural propensity** | Distinct from both psychometrics and mental health |
| **Immunogenetics (HLA)** | A distinct *capability*, not just a topic |
| **Reproductive & carrier status** | About offspring, not self |
| **Genome structure** | Properties of the genome rather than trait predictions |
| **Sleep & circadian** | Chronotype, sleep duration, insomnia, narcolepsy (HLA-linked) |
| **Fitness & physiology** | ACTN3, ACE, soft-tissue injury, trainability — weak evidence, include and flag |

**Pharmacogenomics** is the most genuinely actionable content available and its corpus
(PharmGKB + CPIC) is entirely free (§5.1). Build it early. **Critical caveat:** CYP2D6 —
the single most important PGx gene — is the one arrays call *worst*. PharmCAT explicitly
declines to call CYP2D6 from a VCF because structural and copy-number variation dominate
it, and a `*5` whole-gene deletion makes hemizygous variants on the other allele read as
homozygous (`*5/*29` presents as `*29/*29`). Call the SNP-tractable genes (CYP2C19,
CYP2C9, VKORC1, SLCO1B1, TPMT, DPYD, NUDT15, G6PD) and render CYP2D6 as an explicit
"not callable from this data" card rather than omitting it silently.

**Traits, morphology & sensory** is the encyclopedia core and, counter-intuitively, the
**most reliable section in the app**. Large-effect common variants — HERC2/OCA2 eye
colour, ABCC11 earwax and body odour, TAS2R38 bitter taste, ALDH2 alcohol flush, MCM6
lactase persistence, asparagus anosmia, photic sneeze, cilantro aversion — are precisely
what arrays genotype well. This is the exact inverse of §4.1: common + large effect =
high confidence. It is also where the "obscure and unflattering" mandate (§0.1B) mostly
lives. Lead with it; it demonstrates the product.

**Immunogenetics** is listed as a capability because HLA types are not directly on the
chip — they are **imputed** from SNPs in the MHC region, at >90% accuracy with good
panels. Use **HIBAG**, which ships pre-fit classifiers for European, Asian, Hispanic and
African ancestries, so no restricted training data is needed. Do **not** build on
SNP2HLA: its T1DGC reference panel was pulled from the distribution over individual-level
genotype security concerns and now requires a NIDDK repository request. HLA unlocks
celiac, type 1 diabetes, ankylosing spondylitis, narcolepsy, and drug-hypersensitivity
cards (HLA-B\*57:01/abacavir, HLA-B\*15:02/carbamazepine) that are otherwise unreachable.

**Genome structure** covers facts about the genome itself rather than phenotype
predictions: runs of homozygosity and the autozygosity coefficient (PLINK `--homozyg`;
677k markers is ample — 50k suffices for >5Mb runs — but LD-prune first and do not trust
the defaults), archaic introgression (Neanderthal/Denisovan; Vindija and Altai references
are public, though array-based estimates are coarser than sequence-based ones), and sex
chromosome findings. ROH in particular is sensitive, sometimes genuinely surprising, and
squarely within §0.1B — include it, computed properly and stated plainly.

### 3.2 Declared impossibilities

Maintain this as a live register, and **render the notable ones as explicit
"not determinable" cards** rather than silently omitting them — a user who has read about
a test elsewhere deserves to learn why this tool doesn't do it. Agents: do not attempt
these, and do not accept a card proposal that depends on one.

- **Methylation, epigenetic clocks, "biological age"** — needs a methylation assay. A
  genotype array cannot measure it at all. Common misconception; worth a card.
- **Somatic mutations / tumour profiling** — this is germline saliva DNA.
- **Copy-number and structural variants generally** — including SMN1 (spinal muscular
  atrophy carrier status), RHD (Rh blood group), alpha-thalassemia, and CYP2D6 hybrids.
  Note this makes array-based carrier screening incomplete in a way that is invisible
  unless stated.
- **Y-STRs** — genealogical Y-STR haplotypes are length polymorphisms; the array is
  SNP-only.
- **mtDNA heteroplasmy** — 263 MT markers, genotype calls only.
- **De novo mutations** — requires parental genomes.
- **Relative matching / IBD segment sharing** — requires other people's genomes. Out of
  scope on privacy grounds (§1), not merely technical ones.
- **Telomere length** — a measurement, not a genotype. PRS proxies exist but must be
  labelled as proxies, not measurements.

### The agent interface

The CLI is the contract. Design it so `genetics run --input X`, `genetics list-runs`,
`genetics show <run> --section health`, `genetics card <run> <card-id> --json`, and
`genetics evidence <card-id>` cover the workflow: *"review this run, look at the curly
hair card, check the cited papers, search the web, give me ten facts."* Card JSON must
include the citations so the agent can verify rather than confabulate.

---

## 4. Confirmed roadblocks

Each was verified against primary sources. Treat them as design constraints.

### 4.1 SNP-chip calls for rare pathogenic variants are usually wrong — the big one

Weedon et al., *BMJ* 2021 (UK Biobank, n=49,908 with both chip and sequencing): for
variants under 0.001% frequency, only **16%** of heterozygous chip calls were confirmed
by sequencing. For BRCA1/BRCA2 the positive predictive value was **4.2%**. In Personal
Genome Project data, **20 of 21** individuals had at least one false-positive rare
pathogenic variant. Tandy-Connor et al., *Genetics in Medicine* 2018 found **40%** of
variants in DTC raw data were false positives on clinical confirmation.

Per §0.1A these findings **are shown**, but they are shown as what they are. This is a
*labelling* requirement, not a suppression one:

- Confidence must be an explicit function of population allele frequency (from gnomAD).
  Rarity **lowers** confidence — the opposite of the intuition that a rare hit is a big
  finding. This inversion is the single most important thing the UI must communicate.
- Below the frequency threshold, the card renders with a `likely-artifact` reliability
  tier and states the empirical PPV for its frequency band on the card face: at
  <0.001% frequency, ~16% of such calls are real; for BRCA1/2, ~4%. Give the number.
  "Low confidence" is too weak; a reader deserves "this is about 4 to 1 against."
- ACMG secondary-finding genes are surfaced under the same rule — shown, tiered, and
  accompanied by the explicit statement that only clinical sequencing can establish or
  exclude the variant, and that this pipeline is not a clinical test. Do not suppress
  them; do not present them as established either.
- Imputation does **not** fix this. Imputed rare variants inherit the unreliability of
  the tagging SNPs plus imputation error. Rare-variant confidence stays frequency-gated
  regardless of whether the call came from the chip or from imputation.
- The array *does* cover ~76k ClinVar positions — coverage is not the problem. Per-call
  reliability at low frequency is.

### 4.2 Indels cannot be resolved

8,830 markers are coded `I`/`D` with no sequence recorded, and for many loci either the
insertion or the deletion may be the reference state. Matching these to ClinVar/dbSNP
alleles is not reliably possible from the file alone. **Exclude indels from allele
matching by default**; allow only an explicit whitelist with a verified rsID→
representation mapping.

### 4.3 Polygenic scores need imputation; imputation is the heavy lift

677k array markers versus PGS Catalog scores spanning 10⁵–10⁶ variants. Direct overlap
is partial and non-random, which biases scores rather than merely adding noise.

Confirmed feasible: **impute.me** (Folkersen et al. 2020, LGPL-3.0, self-hostable) is
exactly this architecture — Beagle (GPLv3) imputation against 1000 Genomes phase 3, then
PRS modules. It works, but it costs a multi-GB reference panel, a Java runtime, and long
CPU-bound runs.

**Per §0.1C, imputation is ON by default.** The multi-GB panel, the JVM dependency, and
the long CPU-bound run are accepted costs. Do not add a "fast mode" that silently skips
imputation, and do not make direct-overlap scoring the default because it installs faster.

- Direct-overlap-only scoring remains available as an explicit `--no-impute` escape hatch
  for development and testing. It is never the default and never silent.
- **Report per-score variant coverage on every PRS card regardless**, before and after
  imputation. A score covering 34% of its variants must say so; imputation raising that
  to 96% must also say so. Coverage is a confidence input, not a footnote.
- Carry imputation quality (e.g. r²/DR²) per variant through to the score, and let poorly
  imputed variants degrade the card's confidence rather than silently entering the sum.
- Imputation must be reproducible and recorded in the run bundle: panel version, tool
  version, and parameters. A PRS is not interpretable without them.

### 4.4 PRS do not transfer across ancestries

Scores trained largely in European-ancestry cohorts lose accuracy in other populations.
The ancestry module must therefore run **first**, and its output must gate and annotate
every PRS card's confidence. This is an ordering dependency in the pipeline, not a
footnote.

### 4.5 Psychometrics is the weakest section, and must render differently

The EA4 study (Okbay et al., *Nature Genetics* 2022, n≈3M) produced a polygenic index
explaining **12–16%** of educational-attainment variance — but **direct within-family
effects are roughly half** the population-level association. The remainder is
between-family: assortative mating, ancestry, and environmental transmission. A
population-level R² is not a statement about an individual.

Consequences — note these are **calibration** requirements, not suppression (§0.1B). The
section ships in full, including unflattering results:

- No point estimates about the person. Show the distribution and where the score falls
  in it, with the width of the distribution visually dominant over the point.
- State the within-family attenuation **on the card face**, not buried in the modal. If
  the population R² is 12–16% and the direct effect is roughly half, the card says so.
- Report absolute outcome rates by score decile where available, not just relative
  effects. "Top decile" is meaningless without the base rate next to it.
- Do not gate the section behind a confirmation click for being uncomfortable. Do gate
  individual cards' *confidence tier* on their actual evidence, as everywhere else.

The same reasoning applies to most **mental health** cards. Build these two sections
last — not because they are sensitive, but because they demand the most mature version
of the confidence framework, and shipping them early would mean shipping them badly.

### 4.6 ADMIXTURE is the wrong tool here — use PLINK 2

ADMIXTURE ships Linux (and legacy macOS) binaries only, with no LICENSE file in its
repository and no source distribution. That is a redistribution hazard for a public
repo and a non-starter on Windows.

**Use PLINK 2.0 instead** — GPLv3, actively maintained, native Windows builds, and
supports PCA projection of a sample onto reference eigenvectors via `--score`. Project
onto 1000 Genomes phase 3 + HGDP (both open, GRCh37 available). This yields continuous
ancestry coordinates, which are more honest than percentage pie charts anyway.

### 4.7 Haplogroup resolution is capped by the array

263 MT and 1,665 Y markers support a coarse clade, not a fine subclade — consumer arrays
shotgun a subset of mtDNA rather than sequencing it. Report the clade *with the number of
supporting markers*, and state the ceiling on the card. Do not imply FTDNA-level
resolution.

### 4.8 Source licenses are heterogeneous — three specific traps

Full corpus map, availability tiers, and per-section coverage assessment live in **§5**.
The three things that will actually bite an implementer:

1. **PGS Catalog licenses vary per score**, not per catalogue. Some are non-commercial.
   Parse it per score; do not assume the catalogue-level EBI default applies.
   *Verified and refined at M2.3 (2026-08-15):* the authoritative machine-readable field
   is the **`License/Terms of Use` column of `pgs_all_metadata_scores.csv`**, not the
   scoring file's own header — PGS000001's header carries no licence line at all. That
   column holds **ten distinct values** across the catalogue: the EBI default for the
   great majority, but **CC BY-NC-ND 4.0** for a few dozen scores, academic-research-only
   for a handful, and one with an explicit re-identification prohibition. Note the **ND**:
   no-derivatives is the sharper edge of that licence for us, since computing a score from
   the weights is plausibly a derivative work even on a machine the result never leaves.
2. **SNPedia is CC BY-NC-SA 3.0 US.** Non-commercial *and* share-alike. It is the most
   convenient trait-annotation corpus and the one that most constrains a public,
   permissively-licensed project. Do not vendor it or build a permissive derivative on it.
3. **OMIM forbids derivative databases and redistribution** without a Johns Hopkins
   license, and requires an API key plus weekly refresh. User-supplied key only. See §5.2
   for what replaces it.

---

### 4.9 htslib does not run on Windows — this shapes the whole toolchain

The standard Python genomics stack is unavailable on the primary development platform.
`pysam` ships wheels for macOS and Linux only; `cyvcf2` wraps htslib and has the same
problem. The sgkit documentation states it plainly: *"Reading VCFs is not supported on
Windows, since cyvcf2 and htslib do not currently work on Windows."* Same for `bcftools`
and `tabix` as native binaries.

This is not a blocker, but it is a binding architectural constraint:

- **Do not add `pysam`, `cyvcf2`, or a native `bcftools` dependency.** An agent reaching
  for the obvious library will produce code that cannot run here.
- **Push work into PLINK 2**, which has native Windows builds and reads/writes VCF
  directly. It covers format conversion, LD pruning, PCA projection, `--score` for both
  PCA and PRS, `--homozyg` for ROH, allele frequencies, and sex checks. Most of the
  pipeline is one native binary. PLINK 2 is still alpha — **pin the exact build in the
  manifest.** *Updated at M2.5 (2026-08-15): the "2.00a5.x" originally written here is
  stale, and following it literally would now pin an undocumented build — the download
  page no longer links alpha5 at all, and the version string format has since changed
  (the binary reports `PLINK v2.0.0-a.7.3 64-bit`, not `v2.00a7`). `data/tools.yaml` pins
  the alpha7 build dated 2026-08-08, by sha256 **and** by a version probe that runs the
  installed binary — a checksum only proves the download was intact, not that the build
  is the one whose behaviour was tested against.*
- **Use `scikit-allel` for VCF reading in Python** — Cython, no htslib, installs on
  Windows. This is the documented Windows path.
- BGZF is gzip-compatible for sequential reads, so Python's stdlib `gzip` handles
  `.vcf.gz` streaming. Only random access via tabix genuinely needs htslib — design to
  avoid needing it.
- **Beagle is Java**, so imputation and phasing are cross-platform and unaffected.
- **HIBAG is an R package.** HLA imputation therefore needs R installed plus a subprocess
  bridge. Keep it an optional module that degrades gracefully when R is absent.
- WSL2 is the escape hatch for anything that genuinely requires htslib. Treat it as a
  documented fallback for one or two steps, never as a baseline requirement.

---

## 5. Corpus: what is actually obtainable for free

Assessed against a "public repo, no institutional access, no paywall budget" constraint.
**Headline: the free corpus is deep enough that paywalls are not the binding constraint
on this project. The chip and the underlying science are.**

### 5.1 Tier A — free, permissive, auto-fetchable

These need no account and carry licenses compatible with a public repo (fetched, not
vendored). This tier alone supports the great majority of planned cards.

| Source | Scale | License |
|---|---|---|
| **GWAS Catalog** | ~7,000 publications, 15,000+ traits, 625,000+ curated lead associations, 85,000 full summary-stat datasets, harmonised | EMBL-EBI terms; post-2021 sumstats CC0 |
| **PGS Catalog** | 5,022 scores across 656 traits; harmonised to GRCh37 **and** GRCh38 | EBI default, **per-score varies — parse the header** |
| **ClinVar** | Full variant + classification set | US public domain |
| **gnomAD** | v4: 62.9M SNVs, 6.2M indels with population allele frequencies — but see the build note below | Free; open access |
| **Pan-UK Biobank** | GWAS across thousands of traits, multi-ancestry | **CC BY 4.0**, explicitly unrestricted |
| **PharmGKB + CPIC** | Clinical annotations, dosing guidelines. PharmGKB now serves under **ClinPGx** — `pharmgkb.org/downloads` redirects to `clinpgx.org/downloads` and the historic `api.pharmgkb.org` host no longer resolves (checked 2026-08-15) | PharmGKB CC BY-SA 4.0 (share-alike — opt-in in the fetcher); CPIC free |
| **1000 Genomes / HGDP / SGDP** | Reference panels, GRCh37 available | Open (Fort Lauderdale) |
| **AADR (Allen Ancient DNA)** | >10,000 ancient individuals at ~1.2M SNPs | Freely available, CC BY 4.0 |
| **PhyloTree 17 / Haplogrep 3 trees** | mtDNA phylogeny, 6,380 haplogroups | Public GitHub repos |
| **Europe PMC OA subset** | Full text for agent-side citation checking | CC or similar, per-article |

**gnomAD is load-bearing**, not optional: the frequency-based confidence inversion in
§4.1 cannot be computed without it.

**gnomAD build note (measured at M2.3, 2026-08-15).** The v4 figures above describe a
**GRCh38-only** release. This pipeline is GRCh37 end to end (§2), so the usable release is
**v2.1.1**, and the manifest pins that. The sizes are larger than "multi-GB" implies and
were measured, not estimated: the v2.1.1 **exomes** sites VCF is a single 63 GB file, and
the **genomes** are 495 GB across 23 files. The exomes cover the coding regions where
essentially all ClinVar pathogenic assertions live, so they are what the §4.1 gate
actually needs and they are the required half; the genomes buy non-coding frequencies for
trait and PRS cards and are optional. Every gnomAD file is checksum-pinned from the base64
md5 that Google Cloud Storage returns in `x-goog-hash`, so pinning the whole 558 GB cost
no download at all.

### 5.2 Tier B — free but gated behind a one-time human step

The fetcher cannot fully automate these. Design them as optional modules that degrade
gracefully when absent, and prompt the user once.

- ~~**FinnGen** — requires submitting a web form to receive download instructions by
  email.~~ **Corrected at M2.3 (2026-08-15): this is no longer true of the summary
  statistics, which are tier A.** R12 covers 500,348 individuals, 2,502 endpoints and 21M
  variants, and the release manifest plus every per-endpoint file it lists is served
  straight off public Google Cloud Storage with no account, no form and no credential —
  verified by fetching both the manifest and a 755 MB endpoint file. Individual-level data
  remains restricted, which is presumably what the form covers. The manifest lists FinnGen
  as tier A accordingly.
- **OMIM** — requires a registered API key. Its terms forbid building a derivative
  database or redistributing data without a Johns Hopkins license, and require weekly
  refresh. Therefore: **user-supplied key only, never vendored, never cached long-term.**
  Most of its practical value is recoverable from ClinVar + ClinGen + MedGen + Orphanet,
  all of which are Tier A or free. Treat OMIM as an enrichment, not a dependency.

### 5.3 Tier C — genuinely restricted, and where coverage actually thins

- **Summary statistics containing 23andMe cohorts require a separate approved application
  to 23andMe.** This is the most consequential gap, and it lands precisely on the mental
  health and psychometrics sections: many flagship behavioural and psychiatric GWAS
  (depression, ADHD, and much of the SSGAC/PGC catalogue) include 23andMe samples, and
  the public release is typically the reduced *excluding-23andMe* subset. Lower N, weaker
  scores. Verify per study at fetch time and **record which version was used on the
  card** — a PRS built from a reduced-N release must say so.
  **But check before assuming the worst:** the reduced releases are often still very well
  powered. GSCAN's public excluding-23andMe sumstats cover smoking initiation at
  N=805,431 and drinks-per-week at N=666,978, which is ample for the substance-use
  section (§3.1). The restriction bites hardest on psychometrics, least on substance use.
- **SNPedia** — CC BY-NC-SA 3.0 US. The most convenient trait-annotation corpus and the
  one that most constrains a public, permissively-licensed project. Optional, clearly
  labelled, opt-in fetch; prefer writing the knowledge pack from primary literature.
- **Y-chromosome phylogeny** — the open ISOGG tree is frozen at v15.73 (11 July 2020).
  The actively-maintained trees (YFull, FTDNA Block Tree) are consortium/customer
  resources, not bulk-redistributable. `yhaplo` (23andMe) is **non-commercial licence
  only** and ships an ISOGG-2016-era tree; its own README warns that arrays with few Y
  probes violate its assumptions — and this file has 1,665 Y markers. Compounds §4.7.
- Paywalled *papers* are a minor issue: the summary statistics are open even when the
  publication is not, and Europe PMC's OA subset covers agent-side citation checking.

### 5.4 Coverage assessment by section

- **Ancestry — excellent.** 1000G + HGDP + SGDP + AADR are all open, and PLINK 2 PCA
  projection plus ancient-DNA projection is a strong, fully free stack. Only weak spot
  is haplogroup resolution (§4.7, §5.3), which is a marker-count and tree-freshness
  problem, not a paywall.
- **Physical health — very good.** ClinVar + GWAS Catalog + PGS Catalog + gnomAD cover
  it. **Pharmacogenomics is the strongest and most genuinely actionable area available,
  and is completely free** (PharmGKB + CPIC) — prioritise it. Monogenic findings are
  limited by §4.1, not by corpus.
- **Mental health — good but attenuated**, per the 23andMe restriction. Pan-UKBB and
  FinnGen partially compensate.
- **Psychometrics — most corpus-constrained**, and also the section with the largest
  inherent scientific caveats (§4.5). Both constraints stack. Say so on the cards.

### 5.5 Mechanics

- One fetcher script, driven by a **committed manifest** (`data/references/manifest.yaml`)
  pinning source URL, version, checksum, and license per source.
- **The manifest is committed; the payloads are not.** Reproducible builds, no
  redistribution risk, no 20GB repo.
- The fetcher writes each source's resolved license into a machine-readable lock file and
  **refuses or loudly flags** anything non-permissive (§4.8, §5.3).
- Do **not** subset the imputation reference panel to array positions — imputation needs
  the full panel (§4.3). Subsetting is fine only for PCA projection, which needs just the
  array's markers.
- Every card's provenance names the reference version it came from, so a saved run stays
  interpretable after references update.

---

## 6. Conventions

- **Fail loudly on malformed input.** A silently mis-parsed genotype produces a
  confident, wrong, personal health claim. Validate the header block, assert the build,
  assert the column count, and reject on mismatch.
- **Never invent a citation.** If a card lacks a real DOI or accession, the card is not
  ready to ship.
- **Confidence is computed, not authored.** Derive it from evidence tier, effect size,
  replication, allele frequency (§4.1), imputation quality (§4.3), and ancestry match
  (§4.4). No hand-set numbers.
- **Confidence labels; it does not filter.** Per §0.1A, no code path drops a card because
  its confidence is low. If you find yourself writing `if confidence < x: continue`, you
  are building the wrong thing — sort or group by tier instead.
- **Never soften a sensitive card by making it vaguer.** Per §0.1B, precision *is* the
  duty of care: effect size, base rate, absolute risk, source population. Euphemism and
  unsolicited advice are defects.
- **Runs are versioned and immutable.** Record engine version, knowledge-pack version,
  and reference versions so a saved run can be re-read months later.
- Windows is the primary development platform. Everything must run offline once
  references are fetched — that is the product requirement, not a nice-to-have.

---

## 7. Pre-commit checklist

1. `git status --porcelain` shows no genotype-derived path.
2. New output types have `.gitignore` patterns in this same commit.
3. No fixture derived from a real person's file.
4. No genotype in any log line, error message, commit message, or test name.
5. New reference sources are in the manifest with a recorded license.
6. New interpretation cards carry real citations. Impossibility cards (§3.2) carry
   `impossibility_reason` instead and are expected to cite nothing — their claim is about
   the assay, not the person, and a DOI dragged in to satisfy this line would be the
   tangential citation the exemption exists to prevent.
