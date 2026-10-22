# HLA-linked cards (M11.4)

M11.3 left a frozen classifier choice and a per-locus observation ceiling in `hla.run.json`.
M11.4 turns that evidence into cited cards: celiac disease (DQ2.5/DQ8), type 1 diabetes
(DR3/4-DQB1\*03:02), ankylosing spondylitis (B27), narcolepsy (DQB1\*06:02), and four drug
hypersensitivity alleles that the frozen CPIC release already keys (B\*57:01 abacavir,
B\*15:02 carbamazepine/oxcarbazepine/phenytoin, A\*31:01 carbamazepine, B\*58:01
allopurinol). No card reruns HIBAG or reselects a classifier.

## Contract recorded before implementation

Knowledge schema 6 adds `kind: hla`. Bundle format 23 saves HLA cards in `cards.run.json`
with a `hla_card` computation, and reproduces each one on write and on read from the same
bundle's `hla.run.json`, `pgx.run.json` and `ancestry.run.json`. Formats 1–22 carry no HLA
card and are read unchanged; no current pack is substituted for them. HLA sample schema 2,
selection schema 1, PGx sample schema 1 and guideline display schema 2 do not change. No
new private file type is added: the cards live in the existing gitignored card payload.

### Authoring

```yaml
schema_version: 6
cards:
- id: hla_b5701_abacavir
  section: pharmacogenomics       # immunogenetics or pharmacogenomics
  kind: hla
  title: HLA-B*57:01 and abacavir hypersensitivity
  gene: HLA-B
  hla:
    alternatives:                 # ordered; the first carried alternative selects the state
    - name: B*57:01
      all_of:
      - locus: B                  # one of A, B, C, DRB1, DQA1, DQB1, DPB1
        alleles: ['57:01']        # two-field allele, or a one-field group such as '27'
    states:                       # every alternative and `none` map to an outcome
      B*57:01: carrier
      none: non_carrier
    cpic:                         # required in pharmacogenomics, refused elsewhere
      gene: HLA-B
      allele: '*57:01'
  outcomes:
    carrier: {summary: ..., detail: ..., risk_context: ..., evidence: ...}
    non_carrier: {summary: ..., detail: ..., risk_context: ...}
  evidence: {...}                 # card-level, replaced per outcome as in schema 3
  citations: [...]
  caveats: [...]
```

- **No authored confidence, call or recommendation.** The engine writes the call, the
  matched alternative, the classifier, the reliability and the CPIC rows onto the face.
  Templates may use `{gene}` only. Every outcome needs a literal `risk_context`, as physical
  health requires, because every HLA card states a disease or adverse-reaction risk.
- **Two terms at one locus are two different alleles.** An alternative may name a locus at
  most twice, and the two terms must be met by the two different alleles of the pair, so
  `DRB1 03` + `DRB1 04` means a DR3/DR4 heterozygote.
- **Phase is declared, and a phase-dependent claim cannot be authored.** HIBAG calls each
  locus separately and unphased. An alternative that spans loci must say why phase does
  not change its claim: `heterodimer` (the claim is about an α/β molecule, which forms in
  cis or in trans — Karell et al. 2003 define the celiac DQ2.5/DQ8 risk this way), or
  `genotype` (the cited estimate is defined by unphased allele content at those loci, as
  Emery et al. 2005 type DR3/4-DQB1\*0302). There is no `haplotype` option: a claim that
  needs cis phase is not determinable from these calls, so the schema refuses it rather
  than letting it render as though it were.
- **CPIC binding.** A pharmacogenomics HLA card is exactly one two-field allele at one
  locus, and names the CPIC gene and allele (`HLA-B`, `*57:01`) whose `positive`/`negative`
  lookup values its carrier/none states select. Recommendation text is never authored; it
  comes from the frozen CPIC rows in the run's PGx record (M10.4's rule).

### Derivation

Read only through `genetics.hla.calling.report` and the validated PGx record:

- **Absence is not a negative.** No HLA record, an unavailable stage (not requested, R or
  HIBAG missing, model missing, `no-classifier`) or a needed locus with `no-markers` /
  `no-prediction` makes the card not determinable, with the reason, and no tier. A pattern
  the frozen classifier allele list cannot emit makes it not determinable from that model,
  never absent. A predicted pair without the allele is a negative *model call* with that
  call's posterior and ceiling, and the face says it is not a clinical exclusion.
- **Statuses.** Determined: `matched`. HLA not recorded or the stage produced no calls:
  `not_run`. A needed locus had no observed model marker: `insufficient_calls`. No
  prediction, or an allele the model cannot emit: `insufficient_coverage`.
- **Every locus a card names must be predicted.** A card does not conclude from one locus
  while another it names is missing, even where the missing one could not change the state;
  the weakest named locus already sets the reliability, and a partial conclusion would be a
  second rule.

### Confidence

Each input goes into the slot it already has; nothing here is a new number.

- `calculate_confidence(outcome evidence, population_allele_frequency=None,
  call_source=IMPUTED, imputation_quality=<lowest joint posterior among the card's loci>,
  ancestry_match=<M9.13 study-to-sample membership>, variant_ancestry=True)`. Then the
  tier is capped by the weakest locus `confidence.ceiling`, which M11.3 already folded from
  posterior, marker coverage and the classifier's ancestry match.
- **Recorded deviation from the handoff note.** The handoff suggested passing the
  selection's classifier match to the calculator. That match already caps every locus
  ceiling through `ancestry_ceiling`, so passing it again would use it twice while the
  study population — the other ancestry question, and the one every interpretation card
  answers since M9.13 — was dropped. The study comparison uses M9.13's own `compare` and
  policy, so it enters the weighted component without a PRS transfer ceiling. In practice
  both readings give the same tier: the absent frequency caps every HLA card at moderate.
- **Posteriors are not multiplied.** Loci are not independent and no cited method combines
  them; the weaker locus governs, as the handoff requires.
- **No population allele frequency.** gnomAD carries no HLA alleles, and no HLA frequency
  source has a licence audit or manifest entry, so `population_allele_frequency=None` caps
  the tier at moderate under the calculator's existing rule. The CPIC allele table's
  population frequencies are not used for this: choosing a CPIC population for a sample is
  an unaudited mapping.
- Not determinable cards carry no tier. Nothing is filtered.

### Saved evidence

`computation.result` (schema 1) freezes the authored definition, the HLA sample identity
it was read from (schema, classifier, model SHA-256, selection status, basis and ancestry
match), each named locus's status, pair, posterior and ceiling, the emittable alleles for
each pattern, every alternative's carried state with the matched alleles, the selected
state and outcome, the phase statement, the reliability inputs, the study comparison and
the CPIC block. On write and read the card is rebuilt from that definition and the bundle's
own HLA, PGx and ancestry records, and every saved field must reproduce exactly. A card
copied from another run, an edited allele, a rewritten tier or an altered CPIC row is
refused.

### Placement and the PGx overlap

Disease cards live in **immunogenetics**: §3.1 names HLA as the capability that unlocks
them and the roadmap groups them under M11. Narcolepsy is also listed under sleep and
celiac under nutrition; a card has one section, M12.1 reuses the celiac card rather than
writing a second, and the HLA page links every HLA-linked card wherever it lives.

Drug cards live in **pharmacogenomics**, where the M10.5 framing already appears once.
There is one card per allele and one engine: the HLA card engine resolves its own gene's
lookup from the HLA call, resolves other HLA genes in a CPIC key (carbamazepine's HLA-A ×
HLA-B rows) from the same HLA record, and leaves non-HLA genes (phenytoin's CYP2C9) as
explicit unassessed conditions. M10.4's CYP2C9 guideline card still shows phenytoin's HLA-B
condition as unassessed: its display schema 2 is frozen and is not reinterpreted here.

## Sources

Every number on a card face is from the cited paper's abstract or full text, checked on
2026-10-22 against Europe PMC/PMC records. The CPIC links are the frozen v1.60.0
publication rows.

| Card | Association source | Absolute context |
|---|---|---|
| Celiac DQ2.5/DQ8 | Karell 2003 (10.1016/S0198-8859(03)00027-2): 61 of 1,008 European patients lacked DQ2.5 and DQ8; 57 of those encoded half of DQ2.5 | Singh 2018 (10.1016/j.cgh.2017.06.037) biopsy prevalence 0.7%; Megiorni 2009 (10.1016/j.humimm.2008.10.018) gradient 1:7 to 1:2,518 at 1:100 prevalence |
| T1D DR3/4-DQB1\*03:02 | Emery 2005 (10.1111/j.1399-543X.2005.00117.x): OR 18.14 (14.08–23.37); 30.3% of 1,322 patients vs 2.34% of 3,339 Denver children | Erlich 2008 (10.2337/db07-1331): trans DQA1\*05:01/DQB1\*03:02 heterodimer; genotype in 2.5% of the European-ancestry population |
| AS B27 | van der Linden 1984 (10.1002/art.1780270301): 1.3% of B27-positive people aged 45+ had AS (2,957 surveyed) | Reveille 2012 (10.1002/art.33503): B27 in 7.5% of US non-Hispanic whites |
| Narcolepsy DQB1\*06:02 | Tafti 2014 (10.5665/sleep.3300): OR 251; under 2% of 1,218 European patients lacked it | Same paper: 20% of Europeans carry it; 0.02–0.05% affected |
| B\*57:01 abacavir | Mallal 2008 (10.1056/NEJMoa0706135): PPV 47.9%, NPV 100% for immunologically confirmed reaction | CPIC 2012/2014 (10.1038/clpt.2011.355, 10.1038/clpt.2014.38) |
| B\*15:02 carbamazepine | Tangamornsuksan 2013 (10.1001/jamadermatol.2013.4114): OR 79.84 (28.45–224.06) | Chen 2011 (10.1056/NEJMoa1009717): no SJS/TEN among screened-negative patients vs ~10 expected; CPIC 2013/2018 |
| A\*31:01 carbamazepine | McCormack 2011 (10.1056/NEJMoa1013297): hypersensitivity syndrome OR 12.41 (1.27–121.03); risk 5.0% → 26.0% with, 3.8% without | CPIC 2018 (10.1002/cpt.1004) |
| B\*58:01 allopurinol | Somkrua 2011 (10.1186/1471-2350-12-118): OR 96.60 (24.49–381.00) vs tolerant controls | Hung 2005 (10.1073/pnas.0409500102): 51/51 SCAR patients carried it vs 15% of tolerant patients; CPIC 2013/2015 |

**Evidence tiers.** Drug cards use `clinical_guideline` (each has a CPIC guideline). The
schema has no case-control tier, so the HLA-typing association studies whose effects pass
genome-wide significance (Emery 2005, Tafti 2014) use `gwas`, the Dutch population survey
uses `cohort`, and the celiac card uses `functional` for the heterodimer mechanism Sollid
1989 established. Every one of these is capped at moderate by the missing frequency anyway.

## Validation

Synthetic HLA records are built through the real `calling.impute` path with a synthetic
HIBAG output, so every card reads exactly what M11.2/M11.3 write. The 41 tests in
`tests/hla/test_hla_cards.py` cover the schema refusals (unquoted alleles, undeclared or
haplotype phase, incomplete states, missing risk context, CPIC binding in the wrong section
or for the wrong allele, schema 5 files), every alternative of the celiac and T1D cards,
two terms at one locus, the weakest-locus rule, low posteriors labelled rather than
filtered, a contradicted explicit classifier capping at limited, every not-determinable
path, a schema-1 record, CPIC row selection and cross-gene exclusion, and a bundle round
trip through the CLI and dashboard with four tamper cases and a format-22 refusal.

Fifteen guards were neutered in turn; every change failed a test. The first pass left one
survivor (one allele meeting two same-locus terms), closed by a synthetic homozygosity test.

Real-reference acceptance (2026-10-22, local only, synthetic HLA calls): against the fetched
CPIC v1.60.0 release, B\*57:01 selects only "Abacavir is not recommended", B\*58:01 only
"Allopurinol is contraindicated", A\*31:01 positive with B\*15:02 called absent selects
only that combination's carbamazepine rows, and B\*15:02 negative selects carbamazepine,
oxcarbazepine, phenytoin and fosphenytoin rows with CYP2C9 left unassessed. It skips where
the CPIC reference is not fetched, as in CI.

`genetics ci-local` ran the CI workflow in a fresh clone with an empty data directory and
these changes overlaid. Every Windows step passed on Python 3.11 and 3.13: lint, format,
both mypy platforms, card lint (85 cards, 371 renders), the privacy suite, pinned tool
installs, **3,553 tests passed and 18 skipped** on each, and byte-identical fixtures. Its
first run caught a duplicate `test_cards` module basename that local runs had not exercised.
No personal export was opened and no genotype-derived output is committed.

## Not done here

- **HIBAG's matching proportion.** Still absent from M11.2's frozen output, with no
  published threshold. Adding it changes the R script and the scientific output contract.
- **HLA population frequencies.** Allele Frequency Net Database or another source needs a
  licence audit and a manifest entry first; until then every HLA card stays capped at
  moderate, and says so.
- **Binding M10.4's HLA-B condition.** The CYP2C9 guideline card could resolve phenytoin's
  HLA-B condition from the HLA record, but only under a new guideline display schema.
- **Dose and phase claims.** DQ2.5 homozygosity and haplotype-defined risks need phased
  calls; the schema refuses them.
