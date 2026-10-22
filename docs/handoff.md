# Handoff: M11.5 carrier status

As of 2026-10-22, **M0-M10 and M11.1–M11.4 are implemented; M11.5 is next**. Full-reference
and broad native acceptance remain recorded with their original milestones.
The M10.5 review reruns affected tests and does not claim another full native
suite. Read [AGENTS.md](../AGENTS.md) first, then [the roadmap](../phase1_roadmap.md).
The [M9.13 diff review](review_m913_session.md) fixes frozen fit/allele/type
validation and retains damaged-run errors in card detail views. Its full native
suite passes **3,015 tests, five existing Windows skips**, with four strict type
targets, complete card lint, fixtures and lint/format passing. **M10.1 reference
ingestion is now accepted**: complete CPIC/ClinPGx source processing, offline
inspection, frozen GRCh37 mapping proofs and explicit gaps. The M10.1 diff review
passes **3,137 native tests**, with five existing Windows skips; four strict type targets,
full card lint, fixtures and lint/format pass. The [PGx audit and contract](pgx_ingestion.md)
records source licences, partial normalization and the full-source offline acceptance.
The [session diff review](review_m101_session.md) records citation/publication,
parser and frozen-metadata fixes with all source pins and mapping counts unchanged.
**M10.2 calling is implemented**, with a separate schema-1 sample contract and
additive bundle format 19. The [calling contract](pgx_calling.md) records
uncertainty, complete frozen evidence and full-source synthetic acceptance.
**M10.4 guideline-linked interpretation and M10.5 section framing are implemented.**
One shared current notice appears across PGx views and CLI, independently of
filters and stage availability, without modifying frozen findings. See
[the framing contract](pgx_framing.md). Final combined validation covers
**3,294 unique passing tests**, five existing Windows skips: 3,274 broad-run
passes plus all 101 checks in the three files affected by sandbox restrictions.
All ten final interface cases, four strict type targets, full card lint,
fixtures, style and staged privacy checks pass.
The [M10.5 diff review](review_m105_session.md) finds no production defect;
it closes a reproduced CLI saved-summary/notice-count test gap. Production
code, source pins and saved schemas remain unchanged. All 516 affected
PGx/web/doctor tests and four final complete/gene CLI cases pass, with four
strict type targets, full card lint, fixtures and style passing.
**M11.4 HLA-linked cards are implemented; M11.5 is next.** Knowledge schema 6 adds
`kind: hla`, and eight cited cards read the frozen classifier calls: celiac DQ2.5/DQ8, type 1
diabetes DR3/DR4-DQB1\*03:02, ankylosing spondylitis B27 and narcolepsy DQB1\*06:02 in
immunogenetics, and B\*57:01, B\*15:02, A\*31:01 and B\*58:01 in pharmacogenomics, whose
recommendation rows come from the run's frozen CPIC release rather than the knowledge pack.
Bundle format 23 rebuilds every HLA card from its frozen definition and the bundle's own
HLA, PGx and ancestry records. See [the card contract](hla_cards.md).
The [M11.4 diff review](review_m114_session.md) stops one-field allele groups counting
null (`N`) alleles, lists the four HLA drug cards on the PGx overview and in
`genetics pgx calls`, and tightens three card sentences against their sources. Schema 6,
card result schema 1 and bundle format 23 are unchanged.
**M11.3 HLA classifier selection and call confidence are implemented.**
The model-terms opt-in now selects the HIBAG classifier from the run's saved M5
placements and declines rather than guesses; an explicit classifier still runs with its
ancestry mismatch recorded. Each predicted locus carries an observation ceiling from its
posterior, marker coverage and classifier ancestry match. HLA sample schema 2 is bound to
the saved ancestry in bundle format 22. See the
[selection and confidence contract](hla_selection.md).
The [M11.3 diff review](review_m113_session.md) found no defect in selection, saved
evidence or the bundle binding. It closes a dashboard coverage gap: the placed,
declined, ambiguous and unsupported views had never rendered under test, and a broken
uncertainty line passed every test. It also corrects the explicit-override wording
and makes `HLAStage.select()` honour a pre-set cancellation. Schema 2 and format 22
are unchanged.
**M11.2 HLA classifier imputation is implemented.** It uses an
opt-in HIBAG HLARES hg19 model, validates model metadata, proves marker
strand from dbSNP and 1000 Genomes allele sets, and persists frozen per-locus HLA calls
(bundle format 21 for schema 1). See the
[classifier-imputation contract and validation](hla_imputation.md).
The [M11.1 diff review](review_m111_session.md) hardens path redaction, terminal-wait
interruption, regular-file protocol validation and R bootstrap scope. Native R readiness
and bridge-script acceptance are now separate checks. Native prediction through synthetic
classifiers has run in CI since 2026-10-18, and prediction through the published
classifiers passes locally (see the M11.3 step below).
Final reviewed coverage passes **3,344 unique tests**, seven skips, with all four
strict type targets, complete card lint, fixtures and style passing. The
[review validation record](review_m111_session.md#validation) distinguishes the
broad run from the final affected checks.
See [the guideline contract and audit](pgx_guidelines.md) and the
[M10.4 diff review](review_m104_session.md). The reviewed complete native suite
passes **3,292 tests**, five existing Windows skips; 103 focused checks, four
strict type targets, full card lint, fixtures, style and whitespace checks pass.
Full-source legacy comparison and schema-2 reload pass in 109.05 seconds.
Original M10.4 validation covers
3,267 unique passing checks, five existing Windows skips, four strict type
targets, full card lint, fixtures, style and privacy checks.
The [M10.3 diff review](review_m103_session.md) fixes incomplete saved text and
ignored tier-filter acceptance. Validation covers **3,219 unique passing tests**,
five existing Windows skips (3,218 broad-run passes plus the native-tool setup
recheck), four strict type targets, full card lint, fixtures, style and privacy.
Its entry contract below is retained for M10.4 review. Earlier milestone records
below remain historical.
M10.2 acceptance passes **3,188 native tests**, five existing Windows skips,
all four strict type targets, complete card lint, fixtures, style and staged
privacy checks. Full-source offline synthetic calling/reload passes; no
personal export was opened. See [the acceptance record](pgx_calling.md#acceptance).
The [M10.2 diff review](review_m102_session.md) binds PGx observations to saved
native dosages, tightens malformed-input handling and corrects error categories,
allele labels and reliability styling. Sample schema 1 and format 19 remain
unchanged; the next-step contract below includes the review's findings.
Review validation covers **3,208 unique passing tests**, five existing Windows
skips: a 3,202-pass broad run, then all 399 affected integration tests after the
final six cases. Four strict type targets, full card lint, fixtures and style
pass. Full-source synthetic comparison reproduces the original healthy results
and schema-1 JSON reload in 274.26 seconds; see the review for exact scope.

M9.1–M9.6 are implemented and reviewed. M9.7 is implemented and accepted as of
2026-10-11:
physical-health PRS3820/GPS_Mult cards and pinned scoring references are authored;
synthetic pipeline/bundle/CLI/dashboard checks and full card lint pass. Full-panel
reference extraction and default-on native imputation across all 22 autosomes pass
on a public stand-in, as do both default-imputed health scores. The second,
explicitly non-imputed CAD stand-in exposed a display-quality accumulation error;
accurate summation now passes its three synthetic regressions. That stand-in and
both retained default-score reload validations passed on 2026-10-10 at 23:58.
The pre-review M9.7 native suite after the fix passes 2,872 tests with five existing
Windows skips in 497.27 seconds. All four strict type targets (200 files), fixture
reproduction and lint/format pass. The owner-supplied synthetic
dashboard screenshot exposed small compact labels; those are now HTML text above
the chart. Synthetic HTTP tests verify both chart/detail routes; a post-fix manual
refresh/detail confirmation was requested but has not arrived, and no automated
post-fix browser capture is claimed. The quality fix passes all 48 card tests.
M9.8 is accepted: public SCZ_GHS and UK Biobank-only GPpsy cards are authored,
reference-pinned and fetched. Synthetic end-to-end checks, both default-imputed
and explicit no-impute public-stand-in scoring, and saved-record validation pass.
The pre-review M9.8 native acceptance suite passes 2,873 tests with five existing Windows
skips in 737.42 seconds; full dbSNP lint resolves all 35 marker keys over 55 cards
and 276 renders, and strict Windows Python 3.13 checks all 200 source files.
The primary paper's GPpsy result is used rather than copying a conflicting
catalogue performance mapping. The schizophrenia association is explicitly the
paper's cross-site Bayesian model-family result, not Geisinger-only calibration.
The requested [session diff review](review_m97_m98_session.md) reproduced and
fixed impossible source-copy allocation in frozen reference proofs, with a valid
multiple-END-group preservation regression. It also corrected CAD's incident
association to the European subgroup HR 1.74 (1.71–1.78), rather than assigning
the overall-validation HR 1.73 (1.70–1.76) to that subgroup. Native sums and
imputation are unchanged. Both default-imputed and explicit no-impute CAD cards
were reassembled from retained score records and passed saved-card validation;
the completed public imputation proofs pass the stricter allocation validator.
Final reviewed validation: **2,875 tests passed, five existing Windows skips**
in 1,416.58 seconds. All four strict type targets check 200 files; full dbSNP
lint passes 55 cards/276 renders/35 resolved keys. Lint/format, byte-identical
fixtures, whitespace checks and staged privacy scanning pass. No genotype-derived
artifact or fetched payload is staged. Both milestones and the requested review
are complete. M9.9–M9.13, M10 and M11.1–M11.3 are also implemented; M11.4 is next.
See [physical-health PRS cards](physical_health_prs.md) and
[mental-health model audit and scale acceptance](mental_health_prs.md).

<a id="next-open-step-m912-fitness-and-physiology"></a>

## Accepted M9.12 fitness and physiology

Implementation is authored on 2026-10-14: four schema-3 variant cards for
ACTN3 resistance training, ACE serum concentration, COL5A1 chronic Achilles
tendinopathy and ACSL1 aerobic response, plus schema-4 PGS002143 mean grip
strength. No engine, bundle-format or renderer change is needed. Source
population and effect applicability are explicit; conflicting replication
caps the two affected variant cards at limited, and the injury comparator
outcomes retain null evidence. Forward-only variant matching excludes I/D
and unsupported alleles. The complete 966,283-row grip model is fetched,
per-score licence-checked and checksum-pinned. Full dbSNP lint passes
69 cards/320 renders/39 keys; style and fixtures pass. All 97 focused
variant/polygenic-card checks, four strict type targets (201 files) and the
staged privacy scan pass. All 2,923 unique checks pass with five existing
Windows skips: the broad run passed 2,900 checks, and its 23 Java-8 setup
failures/errors passed with the documented portable Java 17 runtime.
Full-model native acceptance passed in a separate `acceptance/m912` checkpoint:
complete reference preparation, default-imputed and explicit no-impute scoring,
and both written-record disk-read validations. Every source term is retained;
all verified inputs and completed imputation were reused. Both acceptance
records report `passed`, the checkpoint is `complete`, and the runner exited
with an empty error log. A final check reverified every reusable input and
retained checkpoint file; nothing remains pending. See the
[evidence audit and measured acceptance](fitness_physiology.md).

The [M9.12 diff review](review_m912_session.md) found that the existing
variant checks accepted four reversed face claims and a wrong effect measure.
Published directions and units are now bound before evaluating fabricated
observations and checked after saved CLI/dashboard reload; five mutation
regressions reject those changes. All 102 focused card tests pass. The
complete grip payload pin/terms and both retained native card evidence
bindings pass locally; the original full-scale acceptance is preserved.
The review changes tests and documentation only. M9.13 remains next.

### M9.12 entry contract (retained for review)

Expand the Fitness & physiology section through the shared engine, knowledge
schema 4 and bundle format 17. ACTN3, ACE, injury and trainability associations
need exact endpoint-specific primary evidence: a functional molecular effect
does not establish elite-athlete status, an injury prediction or a training
prescription. Retain weak findings with their effect units, source population,
sample sizes, replication and calibration limits visible. Do not silently
borrow a performance estimate from a different phenotype or model.

Audit public models and their score-specific licences before authoring. Bind
each actual model/source, citations, evaluation N and effect/interval before
synthetic substitution, then check saved per-card CLI/dashboard evidence.
Keep unknown direct effects and absolute outcomes explicit. For ACE or any
other indel-dependent claim, AGENTS.md §4.2 still applies: consumer I/D labels
cannot be allele-matched without an explicit verified representation mapping.
Do not infer structural variation or a causal effect from a tag association.

Reuse M9.9's durable `standins` inputs, the locator in `standins/imputation.json`
and all 22 verified dosage files with their matching `public-imputation`
provenance. M9.11's completed private runner demonstrates full-model
preparation/scoring, resource measurement and six disk-read validations.
Preserve M9.9–M9.11 and use a separate private `acceptance/m912` directory.
Do not rerun completed imputation or reduce a source model. Genetic values,
coverage summaries and hashes stay outside Git and out of chat. Synthetic
pipeline/bundle/CLI/dashboard checks, types, card lint, fixtures and privacy
gates remain required. Record any necessary engine/schema change here before
implementing it. The unchanged renderer's previous browser visual check
remains unavailable; no new screenshot review is claimed.

<a id="next-open-step-m913-card-level-ancestry-match"></a>

## Accepted M9.13 card-level ancestry match

M9.13 is accepted on 2026-10-14. One run-owned 1000 Genomes placement is shared
before imputation with variant and PRS evaluation. Selected-outcome evidence
controls the comparison; explicit UNKNOWN/MULTI, decline, not-run and null states
are visible. The separate weighted variant policy keeps PRS transfer ceilings
out of single-variant interpretation and preserves frequency/quality limits.
Format 18 verifies frozen scalar/multi-marker comparisons/confidence and PRS/run
placement equality, preserving formats 1–17. All 2,995 unique checks pass with
five existing Windows skips; four strict type targets, full card lint, fixtures,
lint/format, whitespace and staged privacy gates pass. The
[contract and exact acceptance](card_ancestry.md#acceptance-2026-10-14) explains
the native helper's corrected tools-directory recheck and 67 new synthetic cases.

<a id="next-open-step-m101-pharmacogenomics-ingestion"></a>

## Accepted M10.1 pharmacogenomics reference ingestion

M10.1 is accepted on 2026-10-14. Domain-specific ZIP ingestion replaces the
pending PharmGKB extraction step; complete CPIC COPY/INSERT dumps agree
independently without SQL execution. The source artifacts retain raw tables,
licence/release metadata and source-bound checksums. Catalog schema 1 joins
explicit genomic HGVS assembly mappings to verified dbSNP GRCh37 keys and
retains all definitions/functions/phenotype relationships, including gaps and
conflicts. Kernel locks, atomic publication, interruption/reuse and frozen
validation are implemented. CLI `pgx prepare` and `pgx inspect` use the same
reference library. Sample calling and guideline rendering remain upcoming;
bundle format 18 and M9.13 confidence arithmetic are unchanged.

Complete-source ingestion retains **312,006 ClinPGx rows**, **125,945 CPIC
rows**, **1,354 definitions** and **112,820 diplotype rows**. **493/1,210 source
locations** resolve to verified GRCh37 SNP keys; all residual states remain
visible. Eight-gene inspection, exact source mapping joins, frozen reloads and
verified completed-catalog reuse pass with networking blocked in **39.98 seconds**.
Raw/derived source verification passes with no pending steps. No personal export
was opened. See the [full audit and per-gene coverage](pgx_ingestion.md).

Original implementation validation: **3,104 unique checks passed**, five existing Windows skips.
The broad native run passed **3,091** checks in **614.05 seconds**; its one
additional PGS arithmetic skip passed with `GENETICS_PGS_TEST_TOOLS` configured
(all 27 reference tests pass). The final **89 PGx tests** include twelve cases
added after broad-suite collection, all passing in **18.42 seconds**. Four strict
Windows/Linux × Python 3.11/3.13 type targets pass (211 files); full dbSNP card
lint passes 69 cards/320 renders/39 keys. Style, fixture reproduction, whitespace
and privacy gates pass. Fetched payloads, indexes and audit outputs stay ignored.

**The subsequent [M10.1 diff review](review_m101_session.md) is complete.** It fixes
null guideline citation joins, hardlinked scratch publication, COPY UTF-8 byte
decoding, permissive TSV/JSON parsing, incomplete/inconsistent frozen source
metadata and nested output locking. **3,137 tests pass**, five existing Windows
skips, in **486.78 seconds**; four strict type targets, full card lint, fixtures,
style and privacy checks pass. Full-source offline acceptance reparses both SQL
dumps, checks the saved tables, verifies both sources, retains prepared-catalog
reuse and validates all eight gene publication joins/reloads in **55.06 seconds**.
Source pins, normalization counts, catalog/source schema 1 and bundle format 18
remain unchanged. No personal export was opened.

<a id="next-open-step-m102-snp-tractable-diplotype-calling"></a>

### M10.2 entry contract (implemented; retained for review)

Use `pgx/catalog.py` as the versioned public reference interface. Plan and record
a separate versioned sample-call record and saved-bundle extension before
implementing calling. Do not alter M9.13's frozen confidence method.

- Restrict calling to CYP2C19, CYP2C9, VKORC1, SLCO1B1, TPMT, DPYD, NUDT15 and
  G6PD. Preserve every compatible source definition, unresolved constraint,
  function conflict, structural gap and missing phenotype mapping. The reference
  snapshot deliberately keeps alleles it cannot normalize; no callable subset
  may silently eliminate those alternatives.
- GRCh37 normalization remains partial, especially for CYP2C19 and G6PD. Use
  exact position/allele keys and retained rsID identity; add a verified primary
  mapping source if necessary rather than guessing coordinates or strand.
  A missing marker cannot establish a reference allele. CPIC CYP2C19's reference
  sequence is named `*38`, not an assumed `*1`; retain the source definition.
- Enumerate unresolved phase and preserve native sample ploidy, original/imputed
  call source, quality and rarity limits. A dosage or two doubled X calls alone
  do not establish a phased diploid haplotype. G6PD needs the existing sex/QC
  contract; CYP2D6 remains not callable regardless of its SNP definitions.
- Use the source's actual lookup semantics. DPYD declares `ACTIVITY_SCORE` and
  retains gene-specific notes; do not substitute a generic two-star-allele
  sum. VKORC1 has no phenotype lookup rows in v1.60.0; expose that gap and audit
  genotype-linked guideline/recommendation semantics before interpreting it.
- Keep definition-ID joins and raw function names distinct. CPIC's CYP2D6
  copy-number aliases reference base definitions, and 4,124 source diplotype
  rows have absent definition labels in CYP2D6/HLA-A/B. Those genes are outside
  M10.2's calling scope; never synthesize missing definitions. The eight target
  genes have no missing definition labels in their source diplotype rows.
  Citation inspection now excludes null guideline joins; use actual returned
  citations/source records when authoring later guideline cards.
- Maintain one engine with saved CLI/dashboard parity. Add synthetic cases for
  phase ambiguity, missing positions/functions/phenotypes, I/D exclusions,
  biological ploidy, partial/conflicting definitions, rare/imputed reliability
  and corruption/historical compatibility. All low-confidence findings remain
  visible. M10.3 reuses `cyp2d6_structural_variation`; do not author a duplicate.

<a id="next-open-step-m103-cyp2d6-placement"></a>

### M10.3 entry contract (implemented; retained for review)

M10.2 computes phase-unresolved definition-ID candidates for the eight tractable
genes. Each result retains coverage, unresolved/missing/unassigned constraints,
source functions, exact phenotype joins, DPYD activity semantics and native G6PD
ploidy alternatives. Unknown/poor imputation quality and rare-call bands lower
reliability without suppressing candidates. `pgx.run.json` saves the complete
catalog and private observations; readers reproduce the results and bind sex
and imputation mode to the run. Formats 1–18 expose PGx as not recorded.
The review additionally compares the complete PGx dosage records with the
independent native payload on both save and reload. A locally consistent PGx
record cannot substitute a different genotype, quality or duplicate count.
Original probe presence, eligible direct calls and no-call provenance must also
agree with that native evidence, accounting for recorded complementation and
the array's doubled representation of single-copy calls.
`genetics pgx calls RUN --gene GENE --json` includes source and observation
provenance. The dashboard shows all gene faces, including when grouping by
confidence, and paginates all candidates with their total stated.

M10.3 verifies and finishes the placement of the already-authored
`cyp2d6_structural_variation` card beside these calls. It is already assigned to
pharmacogenomics; do not author a second card, reinterpret its SNP definitions,
or duplicate the source snapshot contract. Verify the dashboard section, the
`/runs/<id>/pgx` overview and gene-detail routes, plus saved CLI inspection.
Check tier grouping and filters: sample calls remain displayed independently
of knowledge-card filters, so the assay limitation must remain visible beside
them. Inspect unavailable-reference and historical/nonstandard packs too;
report missing saved card evidence explicitly instead of claiming it was
recorded or mutating the run. Keep all eight genes and every candidate visible.
Use definition IDs to attach uncertainty to its actual source allele, and
retain the existing reliability badge styles and scoped numerical PPV. M10.4
then owns guideline-linked interpretation; M10.2 returns source mappings only,
with no dosing claims. VKORC1's genotype-linked recommendation keys are exposed
for that audit, while its absent phenotype table remains explicit.

M10.3 now uses one saved-evidence adapter for CLI and dashboard inspection.
The adjacent limitation survives section/tier filters and appears on the PGx
overview and every gene detail, including missing-reference and historical
stages. Missing saved cards are explicit; no current card is substituted.
Six synthetic cases cover both card states and all three stage states, all
eight genes, 136 candidates over two pages and unchanged bundle bytes.
See [the placement contract](pgx_calling.md#m103-cyp2d6-placement).
Validation covers **3,214 unique passing tests**, five existing Windows skips:
3,194 passed in the broad sandbox run, and all 20 environment-restricted
failures pass in targeted checks with writable cache/process/architecture
access. All 449 affected interface checks and the final six strengthened
placement cases pass. Four strict type targets, full card lint, fixtures,
style and privacy gates pass; the guide records exact run boundaries.

## Next open step: M11.5 carrier status

M11.5 adds carrier cards for recessive conditions the array can actually type, in the
**reproductive** section (§3.1: about offspring, not self). M11.6's section-level
incompleteness card needs M11.5's callable set to exist first, so record that set as data
the next step can read, not only as prose.

What a carrier card has to carry, and what is not yet decided:

- **§4.1 governs every rare call.** A heterozygous call for a rare pathogenic allele is
  usually a chip artifact; the M7.2 gnomAD calibration and the scoped M7.3 PPV already
  apply to interpretation cards through `calculate_confidence`. A carrier card must show
  the frequency-banded PPV on its face exactly as M7 cards do, never a softer tier because
  carrier status "is only about offspring".
- **Card shape.** The existing interpretation schema (2/3) already expresses a curated
  carrier variant: an exhaustive genotype map, outcome-specific evidence, `risk_context`
  and forward-only strand. Prefer authored cards over a new computed kind unless a clear
  need appears; the ClinVar lookup (M7.1) is a reference annotation, not a card source.
- **"Array-tractable" must be measured.** Candidates need a typed SNV on this chip, a
  ClinVar P/LP recessive assertion and a usable gnomAD frequency. Several of the best-known
  carrier variants fail one of these: CFTR F508del and GJB2 c.35delG are indels (§4.2;
  matching needs a verified whitelist entry, M1.6), and SMN1 and alpha-globin are copy-number
  states with impossibility cards already (M3.7). Check each candidate against dbSNP and the
  real chip's marker list before authoring, and state on the card when the gene's other
  pathogenic variants are not typed.
- **"No variant found" is not "not a carrier".** Each card's non-carrier outcome must say
  it covers only the typed variant(s). The section-level statement is M11.6.
- **X-linked conditions** need M6.4's sex call and PAR-aware ploidy: a hemizygous call is
  not a homozygote (§2), and a heterozygous X call in a sample inferred male is reported,
  not interpreted (M1.5).
- **Overlap with existing cards.** HFE C282Y and APOE already live in physical health;
  G6PD is an M10.2 PGx gene. Decide placement once, with one card per fact, as M11.4 did
  for HLA-B.
- **Absolute context.** Carrier frequency and the couple-level risk (both partners
  carriers, one in four per pregnancy) are population facts that need citations per
  condition; do not compute offspring risk for an unknown partner.

<a id="next-open-step-m114-hla-linked-cards"></a>

## M11.4 entry contract (implemented; retained for review)

M11.4 turned the frozen classifier choice and per-locus ceilings into eight cited cards;
see [the card contract](hla_cards.md). Recorded deviation: the M9.13 study comparison,
not the classifier match, enters the calculator's ancestry slot, because the classifier
match already caps every locus ceiling. The entry text follows.

M11.3 supplies a frozen classifier choice and a per-locus observation ceiling, reviewed
in [the M11.3 diff review](review_m113_session.md). M11.4 turns them into cards: celiac (DQ2/DQ8), type 1 diabetes, ankylosing spondylitis,
narcolepsy (DQB1\*06:02) and drug hypersensitivity (B\*57:01/abacavir,
B\*15:02/carbamazepine). Start with the [selection and confidence contract](hla_selection.md)
and read schema-2 `hla.run.json` through `genetics.hla.calling.report`. Do not rerun HIBAG
or reselect a classifier from a card.

What a card has to carry, and what is not yet decided:

- **Confidence.** Call `calculate_confidence` with `call_source=IMPUTED`, the locus joint
  posterior as `imputation_quality` and the selection's `ancestry_match`. Then apply the
  locus `confidence.ceiling`, which also holds the marker-coverage cap the calculator
  lacks. Never filter: a likely-artifact call still renders, tiered.
- **Absence is not a negative.** `no-markers`, `no-prediction`, `no-classifier`,
  runtime-unavailable and not-requested states render as not determinable, never as
  "allele absent". A predicted pair that lacks an allele is a negative *model call* with
  that call's posterior and ceiling, not a clinical exclusion.
- **Unphased, per-locus calls.** DQ2.5 and DQ8 are DQA1–DQB1 haplotypes, and HIBAG calls
  each locus separately and unphased. Where cis/trans phase changes the claim, state the
  ambiguity. Do not multiply the two loci's posteriors as if they were independent; take
  the weaker locus unless a cited method says otherwise.
- **Resolution.** Calls are two-field, so B\*57:01 and B\*15:02 are representable. Check
  that each card's allele is in the classifier's frozen allele list. An allele the model
  cannot emit is not determinable from that model, not absent.
- **Population allele frequency.** gnomAD has no HLA allele frequencies, so
  `population_allele_frequency=None` caps at moderate under the calculator's existing
  rule. Any frequency source (for example the Allele Frequency Net Database) needs a
  licence audit and a manifest entry before use.
- **PGx overlap.** HLA-B\*57:01 and HLA-B\*15:02 carry CPIC guidelines. Decide whether
  these cards live in pharmacogenomics, immunogenetics or both, with one shared engine
  rather than two claims (compare M10.4 guideline cards and the M10.5 framing).
- **Historical runs.** Format-21 schema-1 runs have neither a selection nor a locus
  ceiling. Their cards must say so rather than invent an ancestry match.
- **Matching proportion.** HIBAG's per-sample matching proportion directly measures
  training-set representation, but has no published threshold and is not in M11.2's
  frozen output. Adding it changes the R script and the scientific output contract;
  record it, at most, as a displayed fact.

<a id="next-open-step-m113-hla-ancestry-selection-and-confidence"></a>

## M11.3 entry contract (implemented; retained for review)

M11.3 selects the classifier from the saved AADR and 1000 Genomes placements through the
cited Morales category and the publisher's training descriptions. It records decline,
not-run, ambiguous and unsupported refusals and explicit overrides with their ancestry
match, and folds posterior, coverage and ancestry into per-locus ceilings. See
[the contract and validation](hla_selection.md). The entry text follows.

M11.2 supplies validated, immutable HLA evidence but deliberately requires an
explicit `--hla-classifier`; it must not infer a classifier from raw genotypes.
M11.3 should use the persisted M5 ancestry placement and its uncertainty to select an
eligible HLARES population model, record both the mapping and rationale in saved HLA
evidence, and decline where placement is ambiguous or outside supported coverage. Do
not silently force a marginal placement into a model.

Preserve every locus in the result. Fold posterior probability and marker coverage
into its confidence while keeping low-confidence calls visible. `no-markers`,
`no-prediction`, unavailable stages and failed jobs are not negative allele claims.
M11.4, rather than this step, turns the frozen evidence into HLA-linked cards.

R and HIBAG remain user-installed. Since 2026-10-18, CI installs the current R release
and HIBAG on Windows and Linux, so the bridge checks and the synthetic native round trip
run on every push. HIBAG trains synthetic classifiers, and `calling.impute` predicts
through them. They first passed with R 4.6.1 and HIBAG 1.48.2. That first run found a
Windows-only bridge defect: R 4.6.1's `Rscript` cuts an `-e` argument at its first
newline, so every probe failed to parse. The bootstrap now runs from a file in the
private workspace.

Prediction through the published classifiers passes locally on Windows, with R 4.6.1
and HIBAG 1.48.2 installed for the current user (2026-10-18). All four populations
prepare against the real dbSNP and 1000 Genomes references and return predicted loci,
in 38–60 seconds per model. The input is synthetic genotypes at the model markers. So
this proves the path runs end to end, not that the calls are accurate. CI cannot run
it, because CI never downloads references. To rerun it, set `GENETICS_HIBAG_TEST_REFERENCES`
to a reference root holding the fetched classifiers, the dbSNP index, the 1000 Genomes
chr6 VCF and `manifest.lock`. `Rscript` is found on `PATH`, or set `GENETICS_RSCRIPT`
(or `GENETICS_HIBAG_TEST_RSCRIPT` for tests only).

The real pinned models, dbSNP and 1000 Genomes now pass reference preparation outside R.
That check found two defects the synthetic fixtures hid: a dbSNP provenance version the
producer never writes, and dbSNP-only strand proof losing 43% of markers to
tetra-allelic sites. See the [real-reference acceptance](hla_imputation.md#real-reference-acceptance-2026-10-16).
When M11.3 folds marker coverage into confidence, use the frozen per-marker
`state` and `strand_evidence`, not a re-derivation.

## M11.2 entry contract (implemented; retained for review)

M11.2 audits the four HLARES hg19 model releases, pins their bytes, validates model
metadata and dbSNP/1000 Genomes strand proofs, and records complete HLA sample schema
1 evidence in additive bundle format 21. Model payloads and all per-run temporary data
remain outside Git. The shared engine serves CLI and dashboard readers; formats 1–20
remain explicitly HLA-not-recorded. See [the implementation contract](hla_imputation.md).

<a id="next-open-step-m111-r-and-hibag"></a>

### M11.1 entry contract (implemented; retained for review)

M10 is complete. M10.5's [section framing](pgx_framing.md) is current report
context; it does not change saved evidence or source/sample/display versions.

M11.1 owns optional R/HIBAG readiness and the subprocess bridge. Start with
`doctor.py::_check_r`, the existing `Rscript`/`requireNamespace("HIBAG")` probe,
its synthetic tests, and the external-tool wrappers' timeout, cancellation,
private diagnostics and offline contracts. Share readiness with doctor rather
than creating a second definition of installed/usable. Distinguish missing R,
missing HIBAG, probe failures and a usable runtime explicitly. Native Windows
support and graceful absence are required; R is user-installed, not silently
added by the pinned binary installer.

The current doctor probe is only a starting point. It returns `missing` for
every failed HIBAG probe, including a timeout, losing the actual error. This
was reproduced with a synthetic timeout during the M10.5 review. Preserve
failed-execution/timeout/malformed-output states as errors rather than
claiming the package is absent. The success output is a fixed sentinel, not
a HIBAG package version. Record both R and HIBAG identities and design an
explicit, validated bridge result. Isolate R startup configuration (for
example, `Rscript --vanilla`), validate subprocess outputs, bound execution
and cancellation, and keep diagnostics private. A readiness check must not
load personal input, fetch classifiers or infer an HLA call.

Keep this item separate from M11.2 classifier ingestion/imputation and M11.3
ancestry-matched selection. HLA models remain fetched references with recorded
licences; use HIBAG pre-fit classifiers, never SNP2HLA's withdrawn panel. No HLA
call may be inferred from a successful dependency probe. Record a versioned
sample/bundle contract before adding new saved HLA evidence, and keep one
shared CLI/dashboard engine. Exercise malformed subprocess output, nonzero
exit, timeout/cancellation and optional absence with synthetic inputs; keep
personal data and diagnostics outside Git.

<a id="next-open-step-m105-section-framing"></a>

### M10.5 entry contract (implemented; retained for review)

M10.4 adds eight declarative guideline selectors in knowledge schema 5 and
reproducible card computations in bundle format 20. Its
[diff review](review_m104_session.md) hardens exact numeric validation and
incomplete-source evidence handling. New cards use guideline display schema 2;
schema-1 cards retain their original frozen rules and text. Source/catalog schema 1,
sample-call schema 1 and M9.13 confidence remain unchanged. All conditional
source branches, exact definition/mapping/result joins, multi-gene conditions,
native copy models, clinical context and distinct evidence labels survive
saved CLI/dashboard inspection. Missing recommendation/citation/source rows
remain explicit. VKORC1 has no recommendation lookup keys in v1.60.0; no
warfarin dose or reverse-strand genotype bridge is manufactured. See
[the audit and acceptance](pgx_guidelines.md).

M10.5 owns the once-per-section statement that this is not a prescribing tool.
Place it where readers encounter PGx calls and guideline cards, with precise
scope and shared wording across the section, overview/gene views and CLI.
Use one shared current-context representation, with the CLI and dashboard
adapting that same wording. JSON should identify section framing as current
context, separate from frozen card results. Place it once in the PGx section,
once on a PGx overview/gene view, and once in the relevant CLI report; do not
emit it per candidate, gene row or guideline card. Preserve explicit missing
source evidence and display-schema-1/2 compatibility.
Keep candidate-specific measurement/phase/context uncertainty beside the
conditional evidence. Do not repeat a generic disclaimer as card filler or
replace quantitative reliability, source conditions or the adjacent CYP2D6
limitation. Preserve old runs as recorded: section framing may be current UI
context, but do not write current findings into historical bundles. Validate
saved/unavailable/historical views, filters and CLI/dashboard parity offline.

<a id="next-open-step-m104-guideline-linked-cards"></a>

### M10.4 entry contract (implemented; retained for review)

The [M10.3 diff review](review_m103_session.md) fixes incomplete saved-text
reporting and strengthens real-filter acceptance. Complete saved evidence is
required for the adjacent recorded notice; partial text stays explicit without
mutating the run. The eight-gene caller and saved schema contracts are unchanged.

Audit the frozen CPIC/ClinPGx guideline, recommendation, publication and
lookup joins before authoring phenotype-to-dosing interpretation. Keep
source annotations distinct from clinically established sample phenotypes.
Carry guideline evidence levels and actual cited publications; null guideline
IDs must never attribute unrelated publications. DPYD uses its source
activity-score lookup semantics, G6PD retains native copy count and phenotype
limits, and VKORC1 requires the genotype-linked recommendation audit because
v1.60.0 has no phenotype lookup table. Preserve every conditional candidate
and attach uncertainty by source definition ID. Reuse M10.3's saved CYP2D6
limitation and M10.2's immutable schema-1 evidence rather than inferring
CYP2D6 or manufacturing absent mappings. Record any needed card/bundle schema
extension before implementation; M9.13 confidence remains frozen.

Use the complete frozen `reference.cpic.tables`, not just the small per-gene
`recommendation_keys` projection. Resolve candidate definition IDs to saved
source allele labels and native copy counts; follow their exact `mapping_ids`
and `lookup_ids` through `gene_result_diplotype` → `gene_result_lookup` →
`gene_result`, rather than comparing definition IDs with allele names. Bind
recommendations to the actual `lookupkey`, guideline and drug IDs. A source
recommendation may require multiple genes or extra context: retain all required
conditions, and do not apply it just because one gene overlaps. Keep gene–drug
`pair.cpiclevel`, `recommendation.classification`, and allele-function `strength`
distinct; audit which source field supplies each displayed evidence label.

Every guideline card must retain its source release, row identities, source
population/context limits where supplied, explicit gaps, guideline URL and
actual DOI/PMID evidence. Preserve all compatible phenotype/recommendation
branches; neither a first candidate nor
a first lookup row establishes a person's dosing implication. Use declarative
knowledge entries evaluated by the shared engine, with frozen evidence for both
CLI and dashboard. Existing kinds stop at interpretation, impossibility, computed
and polygenic: record the proposed representation and additive validation contract
before extending them. Do not force a guideline recommendation into an invented
effect size to satisfy an unrelated evidence shape. Keep source licence/opt-in
provenance attached; fetched recommendation payloads must remain outside Git.

Acceptance should bind real public source identities/joins before synthetic
substitution, then cover phase/candidate conflicts, multi-gene requirements,
missing phenotype/recommendation/publication rows, drug-specific functions,
DPYD activity expressions, G6PD copy models and VKORC1 genotype keys. Preserve
rarity/imputation uncertainty and numeric PPV scope. Verify cache-independent
save/reload, unavailable/historical states and CLI/dashboard parity offline.
M10.5 remains the separate once-per-section prescribing-tool framing item.

### M10.1 entry contract (implemented; retained for review)

Historical contract from `3f8c189`, before M10.1 source fetching. The accepted
state and M10.2 instructions above supersede this checkpoint's local conditions.

M10.1 builds public reference ingestion and offline allele-definition/phenotype
inspection. Sample diplotype calling is M10.2; guideline-linked cards are M10.4.
Follow the [M10 roadmap](../phase1_roadmap.md#m10--pharmacogenomics).

- Reuse the existing optional manifest IDs `pharmgkb` and `cpic`; do not add
  duplicate sources. Neither source directory was present at the original handoff.
  PharmGKB/ClinPGx archives have rolling filenames and explicit share-alike opt-in.
  Recheck URLs, current sizes, terms and archive contents before refreshing pins.
  CPIC declares the pinned v1.60.0 full/inserts SQL dumps; inspect their actual
  schemas, definitions and licence rather than assuming the manifest's capability
  descriptions establish coverage.
- At entry, PharmGKB declared `extract_zip`, an unimplemented
  post-process step. Supply a verified executor or an explicit domain-specific
  ingestion step with safe archive containment, atomic outputs, source/checksum
  binding and offline verification. Keep fetched payloads and derived reference
  caches outside Git; do not vendor archives or definition tables.
- Establish where complete star-allele definitions, allele functions and
  diplotype-to-phenotype tables actually reside. Clinical annotation/variant ZIPs
  alone must not be treated as proof of full definition coverage. Audit any extra
  required primary source and its licence before extending the manifest.
- Normalize definition coordinates/alleles to verified GRCh37 forward-strand keys,
  retaining rsID merge identity, source release, definition version and citations.
  Preserve absent/conflicting definitions and unsupported structural/CNV alleles
  as explicit states. Build one versioned data contract and offline CLI inspection
  with provenance, for later use by the shared engine and both front-ends.
  Keep M9.13's v1 frozen confidence arithmetic stable; any later PGx-specific
  method or saved-contract extension needs a recorded versioned schema/format plan.
- Synthetic tests must cover malformed/unsafe archives and SQL/tabular input,
  ambiguous allele/build representations, missing mappings, licence opt-in,
  checksum/source drift, restart/reuse and complete saved reference validation.
  Validate ingestion against the full fetched sources before acceptance; Windows
  compatibility and privacy gates remain mandatory.

The tractable calling scope for M10.2 is CYP2C19, CYP2C9, VKORC1, SLCO1B1, TPMT,
DPYD, NUDT15 and G6PD. CYP2D6's `cyp2d6_structural_variation` limitation card
already shipped in M3.7; M10.3 must place it beside called diplotypes, not author
a duplicate. M9.13's selected-evidence ancestry comparison is available to later
cards; PRS transfer ceilings remain specific to PRS.

Useful source-preparation commands (audit rolling metadata before fetching):

```text
genetics refs probe --only pharmgkb --only cpic --json
genetics refs fetch --only pharmgkb --opt-in pharmgkb
genetics refs fetch --only cpic --opt-in cpic
genetics refs verify --only pharmgkb --only cpic --json
```

The [M9.13 session review](review_m913_session.md) records saved-fit/allele/type
validation fixes and preservation of damaged-run refusals in card detail views.

### M9.13 entry contract (retained for review)


M9.13 saved contract and confidence decisions are recorded in
[card-level ancestry match](card_ancestry.md) before implementation: format 18,
shared 1000 Genomes placement, selected-outcome comparisons and variant-specific
weighted confidence without borrowing PRS transfer ceilings.

Card-level ancestry match and the `{ancestry}` placeholder are the remaining
M9 task. Use the run's own 1000 Genomes placement and its reported
super-population; do not invent a mapping from AADR sampling-country labels.
Share one placement between single-marker and polygenic evaluation and keep
CLI/dashboard computation identical. State matched, mismatched, declined,
not-run and unknown-study-population states explicitly. M9.12's ACE study
population is `UNKNOWN` and ACTN3 is `MULTI`: neither means measured agreement.

Audit the actual evidence before choosing confidence consequences for common
large-effect or functional variants; PRS transfer ceilings cannot be applied
mechanically to their different claims. Preserve low-confidence findings,
per-marker frequency/quality gates and outcome-specific null evidence. Bind
the selected study population to the matched outcome, not an unused parent
estimate. Verify the placeholder on the face and detail, plus frozen
CLI/dashboard parity and historical-bundle behavior. Record any new saved
contract here before changing schema or format; immutable saved runs must
retain their original evidence and unknown ancestry state.

Start by tracing `run/pipeline.py::observations`, the existing
`ancestry/context.py::_reference_population` placement, `pgs/portability.py`
and `engine/evidence.py` template context. Interpretation observations
currently leave ancestry match unknown; the run's AADR result cannot supply
1000 Genomes super-population labels. Define the shared 1000 Genomes context
and selected-outcome study comparison first, then wire `{ancestry}` and saved
CLI/dashboard output. Document how unknown, mixed and declined populations
affect each evidence class before changing confidence or the saved contract.
Use the portable Java 17 setup recorded in the M9.12 audit for native checks;
the system Java 8 is insufficient for bref3.

<a id="next-open-step-m911-sleep-and-circadian"></a>

## Accepted M9.11 sleep and circadian

M9.11 is accepted on 2026-10-13:
PGS002209 evening preference, PGS002196 log sleep duration including naps,
and PGS002149 ordinal sleeplessness. Exact release evidence, phenotype coding,
direction and calibration limits are documented in the
[model audit](sleep_circadian_prs.md). All 2,885 unique checks pass with five
existing Windows skips, including the four new synthetic interface cases.
Full card lint (64/294/35 keys), all four strict type targets, lint/format,
fixture reproduction and staged privacy scanning pass. Full-model acceptance
completed in the separate private `acceptance/m911` checkpoint, reusing all
verified M9.9 inputs and full-autosomal dosages: all three full reference
preparations, six scoring checks and six disk-read validations pass. Both
acceptance records report `passed`, the checkpoint is `complete`, and the
runner finished with an empty error log. A final check reverified all reusable
inputs and retained checkpoint files. No imputation was rerun or model reduced;
no engine/schema/renderer change was needed.

The [M9.11 diff review](review_m911_session.md) confirms the exact releases,
evidence and pins, and fixes a test gap that accepted all three reversed
face directions. Directed phenotypes are now bound before synthetic
substitution and in saved CLI/dashboard output; three mutation regressions
reject those inversions. All 62 card tests, all four strict type targets and
full card lint pass. Six retained native card model/direction/evidence
bindings pass without changing or rescoring their frozen records. M9.12
subsequently completed and carried these direction checks into model authoring;
M9.13 is now the next open step.

### M9.11 entry contract (retained for review)

Author and pin cited public sleep/circadian models on the shared PRS engine,
knowledge schema 4 and bundle format 17. Distinguish chronotype, reported sleep
duration and insomnia; do not convert a reference score into a person's bedtime,
sleep hours or a diagnosis. HLA-linked narcolepsy needs the separate HLA
capability, not an inferred diagnosis from one tag SNP.

Audit each exact model's phenotype coding and direction, training/evaluation N,
ancestry, per-score licence, performance and public release against primary
sources. Retain all source rows and state unknown direct effects and outcome
calibration. Bind each actual model and evidence before synthetic substitution;
verify per-card saved CLI and dashboard evidence rather than aggregate sets.

Reuse the verified durable inputs in `acceptance/m99/standins` and all 22 full
autosomal dosage files located by its `imputation.json`, with matching provenance
in `public-imputation`. M9.10's completed private runner demonstrates reuse,
full-row preparation/scoring, process-tree resource measurement and disk-read
validation. Preserve both accepted checkpoints and use a separate private M9.11
directory. Do not rerun completed imputation or reduce a model for speed.
Genetic values, coverage summaries and input/output hashes stay outside Git
and out of chat. Synthetic/interface, card/type/lint/fixture and privacy gates
remain required. The unchanged renderer's prior browser visual check is still
unavailable; no new screenshot review is claimed.

<a id="next-open-step-m910-substance-use-and-behavioural-propensity"></a>

## Accepted M9.10 substance use and behavioural propensity

The entry and acceptance contract below is retained for review.

Author and pin public models on the existing shared PRS engine. The roadmap's
GSCAN excluding-23andMe sample sizes are context, not automatically the N of a
selected score. Verify each exact public model/release, score-specific licence,
phenotype, discovery/evaluation N, study ancestry and reported performance against
primary sources. Keep population association distinct from causal/direct effects;
state unknown within-family attenuation and outcome calibration explicitly.
Use complete matched absolute outcome rates only where actually published.
Retain every source row and keep confidence, coverage and portability visible.
Include sourced unflattering results without moralising or a confirmation gate.

Distinguish initiation, consumption quantity and dependence: weights and evidence
for one endpoint do not establish another, current substance exposure or a
diagnosis. Preserve published effect units, source population and absolute/base
rates where available; state missing calibration instead of inventing it. Do not
apply education's contextual within-family attenuation to these models.

### M9.10 implementation and acceptance contract

- Start with knowledge authoring and manifest/lock pinning on schema 4, bundle
  format 17 and the shared engine. Record any needed engine/schema change here
  before implementing it. Missing references must leave visible unrun cards with
  their fetch command; confidence must never filter a card.
- Bind each authored card to its exact score ID, source, phenotype, citations,
  evaluation N, effect and interval **before** normalizing model IDs to a synthetic
  fixture. Check those quantities per card after bundle reload and in CLI and
  dashboard output. The [M9.9 review](review_m99_session.md) shows why aggregate
  sets of effects/counts miss swapped models.
- Reuse the durable public execution inputs under
  `%LOCALAPPDATA%/genetics-analysis/acceptance/m99`: the two normalized
  `standins/*.public-array.parquet` inputs and `standins/imputation.json` locator.
  Its `directory` and `dosage_files` fields point to the copied full-autosomal
  dosage files under `public-imputation`; load the matching `imputation.run.json`
  provenance there. The retained private runner demonstrates reconstruction of
  `ImputationResult` and reuse of its `iter_dosages` factory. Verify integrity
  locally, retain all 22 complete dosage files and the unchanged provenance, and
  keep all genetic artifacts and hashes outside Git and out of chat. Do not dump
  the locator or checkpoint JSON into chat.
- Prepare each new model's full reference, retaining every source row. Measure
  extraction, scoring, record size and peak process-tree memory. Check default-on
  imputed scoring and explicitly non-imputed scoring on the two public ancestry
  stand-ins; record mode, both-phase coverage and portability. Do not rerun
  completed imputation or reduce its panel. These panel members test execution,
  not predictive calibration.
- Write complete score/card records, then read each pair from disk and run frozen
  validation. Keep acceptance outputs in a separate private M9.10 directory;
  preserve M9.9's accepted records and measurements. Run the relevant synthetic
  pipeline/bundle/CLI/dashboard checks, card lint, type/lint/fixture and privacy
  gates for the actual diff before acceptance.

M9.10 is accepted as of 2026-10-13. Three public
UK Biobank-only models are authored, licence-checked, fetched and pinned:
PGS002126 ever smoking, PGS002152 less-frequent alcohol intake and PGS002124
self-reported substance/behavioural addiction. Exact phenotype counts,
partial-r evidence and alcohol direction are verified against the authors'
release/code. GSCAN public weights exclude 23andMe, whereas its performance
methods use all studies except Add Health; exact public-release performance
binding could not be established, so those metrics are not substituted.
All 55 card tests and full local dbSNP lint (61/288/35 keys) pass. Full-scale
public-stand-in acceptance passed in a separate private `acceptance/m910`
checkpoint, reusing all 22 verified durable dosage files and both normalized
inputs without rerunning imputation or changing M9.9's accepted records.
All three complete references, three default-imputed and three explicit
no-impute checks, and six written-record reload validations pass. Both acceptance
records report `passed`; the checkpoint reports `complete` and the runner
completed successfully. All 2,881 unique checks pass with five Windows skips;
all four strict type targets, lint/format, fixtures and privacy gates pass.
See the [model audit and acceptance record](substance_use_prs.md).
The unchanged renderer's prior browser visual check remains unavailable.

## Accepted M9.9 psychometrics

Three public UK Biobank-only LDpred2 models are authored and reference-pinned:
cognition (PGS002135), qualifications-to-years (PGS002231), and neuroticism
(PGS002213). They use schema 4, bundle format 17 and the existing renderer;
no shared-engine/schema change was needed. Phenotype-specific training counts,
held-out residual-variance associations and unknown within-family effects are
explicit. The synthetic suite and native arithmetic check pass 2,877 unique
checks, with five documented Windows platform skips remaining. All four strict
type targets, lint/format, fixture reproduction and full card lint pass
(58 cards, 282 renders, 35/35 marker keys).

Accepted on 2026-10-12. All three complete reference preparations, three
default-imputed and three explicit no-impute public-stand-in scores passed.
All six written score/card pairs were read from disk and passed frozen validation
of their retained digest, coverage, distribution, portability, display and
reliability. No source term was truncated. The checkpoint was paused on
2026-10-11, then resumed with both completed scores and full imputation reused.

The completed durable checkpoint remains at
`%LOCALAPPDATA%/genetics-analysis/acceptance/m99`, outside Git. Both acceptance
and retained-validation records report `passed`; the checkpoint reports
`complete`, and the runner exited successfully. Keep all contents private,
including hashes; do not paste genetic summaries into chat. The
[model audit and resource record](psychometrics_prs.md) records measured costs
and the unavailable browser visual check. The renderer is unchanged; synthetic
HTTP and chart geometry checks pass. Broad code checks already pass; repeat
them only when new changes, failures or unresolved concerns justify it.

The [2026-10-13 diff review](review_m99_session.md) confirms the shipped model
bindings, primary-source evidence, reference pins and score-specific licences.
It strengthens the synthetic test to reject swapped model IDs and per-card
evidence: both ancestry cases accepted a model swap before the fix and reject
it now. All 51 card tests and all six retained score/card revalidations pass;
full dbSNP lint remains 58 cards, 282 renders and 35/35 keys. No scoring,
imputation, schema or renderer change was needed.

### M9.9 entry contract (retained for review)

M9.9 is authoring and reference pinning on the existing engine. Verify each
selected model's permissive score-specific licence and exact public release,
including reduced-N excluding-23andMe cohorts where applicable; do not replace
that model's N with a larger publication headline. Check effect and within-family
attenuation against primary papers for the same phenotype/model. State unknown
direct effects explicitly instead of borrowing an attenuation from another score.
Keep reference distributions and intervals visually dominant, with no individual
point estimate or diagnosis. Use complete matched absolute decile rates only
where actually published; keep confidence, coverage and portability visible.
Retain every source row/evidence term and measure full-scale extraction/scoring
cost before acceptance. Record any needed engine/schema change here before making
it. The existing full public-stand-in imputation may be reused without rerunning
the completed native jobs; private artifacts stay outside Git.

## M9.5–M9.6 review and M9.7 entry contract

The [diff review](review_m96_session.md) of `b2bde81..317c825` fixed three defects, each
reproduced by a regression first:

- **A score missing from the fetched metadata aborted the whole run.** It now leaves only
  its own card `not_run`, with the refetch command.
- **Some structural damage escaped the bundle reader.** `AttributeError` and `IndexError`
  in polygenic validation now become `BundleError`.
- **The face text was false above an attenuation of 1.** Within-family estimates above 1
  are now worded as such, not as attenuation.

Review acceptance: **2,837 tests passed, five existing Windows skips**, with pinned PLINK
2/PLINK 1.9/Beagle/bref3 and Java 17. All four strict type targets, lint/format, fixture
reproduction, full dbSNP card lint (51 cards, 268 renders) and staged privacy scanning
pass. No known blocker remains for M9.7.

**M9.7 goal:** Physical-health PRS cards. This should be authoring and reference pinning
only; the engine path, bundle format and renderer exist. If a change to the engine turns
out to be needed, record why in this file before making it.

Contract for M9.7:

- **Scale findings recorded before implementation (2026-10-10).** The reference extractor
  retains the raw VCF calls for every requested locus until the chromosome finishes.
  For a genome-wide score this holds thousands of Python objects per locus, beyond
  the already necessary compact effect-dose matrix. Before authoring the large CAD
  card, change extraction to resolve one coordinate group at a time, preserving all
  duplicate records at that coordinate, full-file digest verification and every
  row's exclusion state. Reject out-of-order panel coordinates rather than resolving
  incomplete groups. This changes memory use, not the scoring method, cached evidence
  or bundle format. A synthetic memory regression must demonstrate the reduction.
  The live GPS_Mult file also declares its original build as `hg19`, with explicit
  harmonized `GRCh37` coordinates. The parser currently rejects this documented
  assembly synonym before considering harmonization. Accept the hg19/hg38 synonyms
  with canonical build selection while retaining the source headers verbatim; an
  unknown build must still fail. Cover both original and harmonized paths.
  Final presentation review also found that display schema 1 carries only the
  currently displayed phase's coverage. Before shipping actual health cards,
  display schema 2 must carry both phases' row/variant coverage, scored-weight
  shares and explicit unavailable states, and show them on the face/detail.
  Continue deriving historical schema-1 cards exactly as before on reload;
  bundle format 17 need not change because the existing display is versioned.
  Genuine full-panel imputation then exposed an M8 reader assumption on chr3:
  Beagle emitted the same variant twice because the pinned reference itself
  contains it twice (verified against the reference, without logging calls).
  Preserve source-verified untyped duplicates up to their exact multiplicity;
  continue refusing typed repeats and any unverified/excess repeat. Discover
  the multiplicities during the existing full, semantically verified decode.
  Retain both dosage records so the existing card/PRS ambiguity handling applies,
  rather than deduplicating or choosing one. No saved record format changes.
  The resumed full-panel run then reached chr8, where Beagle itself refuses
  two native-equal markers (same chromosome/position/alleles/END). Local comparison
  verified that their complete phased reference GT vectors are identical.
  Before continuing, add a lossless native-input representation: fold only these
  redundant copies, retain every sample and every distinct genetic observation,
  and keep the original panel plus source/multiplicity/semantic-hash proof.
  Conflicting phased vectors must fail, never select one. Bind the actual native
  input in frozen provenance and validate both this proof and source-verified
  output multiplicities on saved reload; the current saved dosage reader still
  rejects all repeats. Cover native duplicate failure, unchanged genetic data,
  conflicting duplicates and tampering before resuming acceptance.
  The full default-imputed health-score checks then passed, but the second,
  explicitly non-imputed CAD stand-in exposed another scale defect: display
  quality accumulates weights with ordinary addition while its denominator uses
  `math.fsum`, so all-direct observations can round above the unit interval and
  abort confidence assembly. Before continuing, use accurate summation for both
  quality numerators in the new display schema 2; preserve schema 1's historical
  arithmetic on reload. Keep strict confidence input validation. Reproduce the
  defect with fabricated weights and rerun the second stand-in without repeating
  the completed full-panel imputation or default-imputed native sums.

- **Choosing scores.**
  - Use PGS Catalog scores whose metadata licence classifies as `permissive`, because a
    run cannot opt in to restricted terms (AGENTS.md §4.8).
  - Prefer additive models. Interaction, haplotype or dominance terms make the score
    `unsupported_model`, and the card then renders unplaced.
  - Record the score's GWAS and development ancestry on the card's evidence. M9.5's
    portability will grade it whatever is written, but the card should not contradict
    the catalog.
- **Pinning.** Add one manifest entry per score, modelled on `pgs000001_grch37`: the
  harmonized GRCh37 file `PGSxxxxxx_hmPOS_GRCh37.txt.gz`, fetched and locked.
  `cards lint` refuses a card whose `pgs.source` does not fetch that score.
- **Evidence and citations.** Every number on a card must be cited from the primary
  paper and checked against it, not recalled (AGENTS.md §6).
  - `effect` is the published per-SD (or per-unit) estimate, with its interval and a
    `context` sentence.
  - `ancestry` uses the cards' super-population codes for the derivation study.
  - Set `within_family_attenuation` only where a within-family estimate is published.
- **Absolute rates.** Use `decile_outcomes` only when a paper reports the outcome by
  score decile, with the same measure and population for `base_rate`.
  - Quintiles, percentile bands or odds ratios against the middle are not deciles. Never
    interpolate them into deciles; leave `decile_outcomes` out, and the face says a
    position is not a risk.
  - Health cards are §0.1B's precision case: state the measure, its horizon (`context`)
    and the population exactly.
- **Measure scale before shipping a large score.**
  - Real-panel acceptance so far is PGS000001, 77 rows. Most physical-health scores
    have 10^5–10^6 rows.
  - Before shipping one, measure the reference extraction (time, memory, cache size).
  - Measure the per-score dosage pass in a default imputed run.
  - Measure the size of its `pgs.run.json` record: it keeps every term with its native
    evidence. If a million-row record is impractical, propose a storage change (with a
    bundle format bump) here first. Do not quietly drop evidence.
  - Report coverage before and after imputation for each score on the real panel.
- **Acceptance.** Run the full `cards lint`, fetch and lock every new score, and put
  public 1000 Genomes stand-ins through the polygenic stage. Then **look at the
  dashboard**: browser screenshots timed out in M9.6, so the fixed chart has been checked
  only by geometry assertions.
- **Still open.** The M9.13 decision on single-marker ancestry match and `{ancestry}`.

## Implemented M9.6

`pgs/cards.py`, `pgs/runner.py` and `web/polygenic.py` put polygenic scores on cards. See
[the guide](pgs_cards.md).

- **Schema.** Knowledge schema 4 adds `kind: polygenic`: `pgs: {id, source}` naming a
  manifest entry, `trait`, plain-text `summary`/`detail` (no placeholders), evidence, and
  optional `decile_outcomes` (ten absolute rates plus base rate, cited to one of the card's
  citations). `cards lint` checks the manifest source fetches that score.
- **Run.** `genetics run` prepares every polygenic card before the export is read
  (scoring-file lock, licence gate, public 1000 Genomes extraction), places the sample once,
  then scores each card with the M9.2-M9.5 functions. Absent inputs give `not_run` with the
  fix; a lock mismatch raises. A run gives no restricted-licence opt-in.
- **Bundle format 17.** `pgs.run.json` holds each card's private score record. Reading
  re-derives the record's coverage, distribution and portability, then the card's display,
  reliability and face text, and refuses any disagreement or an unpaired record.
- **No point estimate.** The display carries the reference histogram and quantiles and the
  person's 95% interval, deciles and score-unit range. The person's sum and point
  percentile never leave the private record. The face states the interval basis, coverage,
  portability, within-family attenuation and decile rates with the base rate, or that a
  position is not a risk.
- **Confidence.** `calculate_polygenic_confidence` reuses the calculator's weights, with
  comparable score weight in the frequency slot. Ceilings reuse existing thresholds:
  evidence, DR2 on weighted quality, `ancestry_ceiling` bands for coverage and ancestry.
- **Dashboard.** The face has a compact histogram with the interval band. The detail has a
  full chart, then tables for coverage, quality, portability, decile rates and every
  confidence input. The colour pair passed the dataviz validator in both themes.
- **Fixed while there.** The section nav counted only `matched` cards as interpretations,
  disagreeing with the run manifest and the grid for every computed card. It now counts
  `computed` too. An unknown manifest source raised `ManifestError` uncaught in the runner;
  it is now a reason.
- **Carved out.** Single-marker `ancestry_match` and `{ancestry}` are now **M9.13**. They
  are a decision about the evidence: they would re-tier every card in the pack.

Acceptance: **2,834 tests passed, five existing Windows skips**, with pinned PLINK
2/PLINK 1.9/Beagle/bref3 and Java 17.

Thirty-five new synthetic cases cover:

- schema refusals;
- the confidence ceilings;
- a run through the bundle, CLI JSON and dashboard;
- not-fetched, restricted-licence and no-panel cards that still render;
- nine tamper refusals, plus a format-16 bundle carrying a polygenic card;
- lock verification of the scoring file;
- manifest-source lint;
- chart geometry;
- the nav count.

Real-data checks used public data only. Public PGS000001 and the real 1000 Genomes panel
were run through the polygenic stage with two public samples' own genotypes:

- HG00096 (GBR) placed in EUR (503 samples), interval at the 41st to 49th percentile;
- HG00403 (CHS) placed in EAS (504 samples), interval at the 90th to 95th percentile,
  with its tier capped by ancestry, as M9.5 intends for a European-only GWAS.

A browser render of a synthetic run showed two defects, both since fixed: SVG labels
scaled with chart width, and the leftmost tick label clipped. Screenshots of the fixes timed
out in the browser tool, so the fix is covered by geometry assertions rather than re-viewed.
Other gates: all four strict type targets, lint/format, fixture reproduction and the full
dbSNP card lint (51 cards, 268 renders) pass. No personal export or private run was used.

M9.7's entry contract is at the top of this file.

## Implemented M9.5 (M9.6 entry contract, done)

`pgs/portability.py` gives every **schema-4** score result a versioned `portability`
block and the numeric `ancestry_match` that `calculate_confidence` accepts. `score()`
builds it, and `attach_reference()` rebuilds it once the 1000 Genomes placement exists.
`genetics pgs portability RESULT --json` recomputes it and refuses any disagreement.
Schema 1–3 results are recomputed and labelled `recomputed_legacy`. See
[the guide](pgs_portability.md).

- **Cited mapping, not memory.** The placed 1000 Genomes *population* is mapped to a
  Morales et al. 2018 Table 1 category (doi:10.1186/s13059-018-1396-2, verified against
  the Europe PMC full text). That category is mapped to a PGS Catalog display category
  using the catalog's own ancestry documentation (verified the same day).
  Super-populations are not used: KHV is South East Asian, and ACB/ASW are African
  American or Afro-Caribbean. Categories with no 1000 Genomes population are never given
  a nearest code.
- **Lower bound, not renormalised.** The GWAS-source stage drives; development drives only
  when GWAS is empty; evaluation, which is weighted by sample sets, never drives. Not
  Reported, multi-ancestry, unrecognised labels and unreported stages are kept as an
  indeterminate share. They raise only `match.upper_bound`.
- **Sample states.** A decline by either panel gives `0.0`, judgment
  `sample_unrepresented`; a 1000 Genomes placement cannot rescue an AADR decline. A
  not-run or saved-only sample gives `None`, judgment `not_computed`. Placed populations
  in another display category within the decline threshold are recorded as alternatives.
- `confidence_ceiling` comes from the new `engine/confidence.py::ancestry_ceiling`, which
  `calculate_confidence` now also uses, so the record and the calculator cannot disagree.
- One real-data defect was found and fixed: PGS004230 publishes `Not Reported:0`, and the
  first parser refused zero shares. All 6,991 metadata rows now parse; 16 report neither
  GWAS nor development ancestry.

Acceptance: **2,799 tests passed, five existing Windows skips**, with pinned PLINK
2/PLINK 1.9/Beagle/bref3 and Java 17. Twenty-seven new synthetic cases cover:

- the full contract matrix: matched, mismatched, multi-ancestry (including and excluding
  European), unreported, development fallback, nothing reported, KHV against an East
  Asian study, declined by each panel, not run and saved-only;
- non-filtering: sums, terms, coverage and percentiles are unchanged, and the calculator
  still returns a result at every tier;
- equality across the API, the CLI and the persisted file, with a cold and a warm
  extraction cache;
- seven tamper refusals and legacy recomputation.

Six mutations each fail a test: AADR rescue, KHV as East Asian, renormalising Not
Reported, multi-excluding-European as indeterminate, declined as neutral, and no
development fallback.

Two real-data checks used public data only:

- Every one of the 6,991 catalog metadata rows went through the mapping for six stand-in
  placements.
- Six public 1000 Genomes samples were built from their own genotypes, keeping a random
  70% of PCA markers, and placed through the real placement with public PGS000001. Each
  placed in its own population or its nearest neighbour (HG00096 GBR as CEU). Only CEU
  matches PGS000001's European-only GWAS; the rest are `mismatched`.

  Admissible neighbours are broad: GBR also admits CLM and PUR, and CHS admits KHV. That
  is why the number follows the named population and the alternatives are recorded beside
  it, rather than taking the worst case. These samples are in the panel, so this checks
  the wiring, not calibration.

A real `genetics.exe pgs score --no-impute` on the synthetic fixture reloads as
`persisted_verified`, with `not_computed`, because the fixture shares too little with
1000 Genomes to be placed. All four strict type targets, lint/format, fixture reproduction
and full dbSNP card lint (51 cards, 268 renders) pass. No personal export or private run
was used.

**M9.6 entry contract** (PRS card renderer):

- **Card face.** Put the portability judgment, the matched share *and* the upper bound,
  the ceiling and the reason on the card face. When `alternative_display_categories` is
  non-empty, say so. When `merged_morales_categories` has more than one entry, state that
  the catalog does not separate those groups. Never show `ancestry_match` alone, since 0
  means "not demonstrated" as well as "mismatched".
- **Card confidence.** Build it with `calculate_confidence(...,
  ancestry_match=portability["ancestry_match"])`. Coverage
  (`fraction_of_score_weight`), imputed weight share and DR2 bins from M9.3/M9.4 are
  confidence inputs the card must also weigh; M9.5 recorded them, it did not fold them in.
  No new threshold may be invented without a cited basis.
- **Run pipeline.** The `{ancestry}` template placeholder now names M9.6, and single-marker
  card `ancestry_match` is still unset. Both need the 1000 Genomes placement carried into
  `genetics run`, which today holds only the AADR context. Reuse
  `pgs.portability`'s mapping rather than writing a second one.

## M9.3–M9.4 review and M9.5 entry contract (done)

The [diff review](review_m94_session.md) moves all public panel verification and
extraction ahead of personal input, removes the private reference workspace, binds a
prepared reference to its score, and makes `pgs placement` refuse structurally damaged or
phase-contradictory blocks. Six regressions reproduced the defects before the fixes.
It also ran the two paths earlier acceptance had not: five public 1000 Genomes samples
(their own genotypes, 70% of PCA markers) were placed in their true super-populations, and
parallel extraction ran under the real `genetics.exe` (3 min 52 s cold, 12 s cached).
Review acceptance: **2,772 tests passed, five existing Windows skips**, pinned native tools
and Java 17; four strict type targets, lint/format, fixtures, full card lint and staged
privacy scan pass. No known blocker remains for M9.5.

**M9.5 goal:** turn study-to-sample ancestry into the numeric `ancestry_match` that
`engine/confidence.py::calculate_confidence` already accepts (a fraction in [0, 1], or
`None` for "not computed"), and record a per-score portability judgment on every PRS
result, per AGENTS.md §4.4. Calibration, not suppression: nothing may filter a card.

Inputs that now exist, all in each schema-3 score result:

- **Sample, 1000 Genomes vocabulary:** `reference_distribution.placement` and `.group`.
  When placed, `group.super_population` is one of AFR/AMR/EAS/EUR/SAS, the panel's own
  `super_pop` label, which is exactly the vocabulary cards declare for study ancestry
  (`engine/cards.py::Ancestry`). This closes the vocabulary gap M5.8 recorded for the
  *sample* side without any hand-written mapping. `declined` and `not_run` carry reasons.
- **Sample, AADR:** the run's `ancestry` block (M5.9's 100 Human Origins populations,
  region = sampling country). Finer than 1000 Genomes and the place where unrepresented
  groups (Aboriginal Australian, Khoisan, parts of MENA) are *declined*. A sample the AADR
  placement declines must not be rescued to "matched" by a coarser 1000 Genomes call.
- **Study, PGS Catalog:** `score_definition.metadata` rows carry three GWAS Catalog
  ancestry-distribution columns: `Ancestry Distribution (%) - Source of Variant
  Associations (GWAS)`, `- Score Development/Training`, `- PGS Evaluation`, as
  `Label:percent|...` text (PGS000001: GWAS `European:100`; evaluation
  `European:72.7|Not Reported:18.2|East Asian:9.1`). Empty and `Not Reported` occur.
- **Comparability:** per-phase `fraction_of_person_scored_weight`,
  `fraction_of_score_weight`, `person_dose_basis.imputed_absolute_weight_fraction` and
  M9.3 coverage. These are confidence inputs beside ancestry, not ancestry itself.

Contract for M9.5:

- **The study-label mapping must be cited, not written from memory** (AGENTS.md §6). The
  catalog's labels are the GWAS Catalog ancestry framework's broad categories; its
  published definition (Morales et al., Genome Biology 2018) is the candidate source.
  Verify the DOI and the category list against the paper before encoding them. Categories
  with no 1000 Genomes super-population counterpart (e.g. Greater Middle Eastern,
  Oceanian, African American or Afro-Caribbean as distinct from African) must map to an
  explicit partial or unknown state, never to the nearest code.
- Parse distributions per stage. Decide and document which stage drives the match;
  GWAS-source ancestry is what effect sizes were estimated in. `Not Reported` and empty
  stay visible as unknown share, never renormalized away.
- `declined` lowers portability and is never neutral. `not_run` stays `None` (unknown).
  Saved-only results (no reference placement) must say so rather than reuse a pooled
  comparison as if it were matched.
- Keep every input and the derived number in the result, versioned, and revalidate on
  reload as M9.3/M9.4 do. Replace the `portability: "not_computed_M9.5"` placeholder.
- Acceptance should cover matched, mismatched, multi-ancestry, unreported, declined
  (both panels), not-run and saved-only cases, plus a non-filtering assertion and
  cache-independent CLI/API/persisted equality, all on synthetic data.

## Implemented M9.4

`pgs/reference.py` scores 1000 Genomes phase 3 (2,504 samples) over exactly the rows the
person's phase scored and the panel resolves, through the person's effect-dose matrix and
PLINK invocation, then places the person by mid-rank percentile with a Wilson 95% interval.
Score artifacts move to **schema 3** (`reference_distribution`, per-phase `percentile`).
`genetics pgs score` computes it by default (`--no-reference` is the recorded opt-out);
`genetics pgs placement RESULT --json` recomputes every statistic and refuses mismatches.
See [the guide](pgs_reference.md).

- The comparison group comes from a new 1000 Genomes placement
  (`ancestry.context.place_among_reference_populations`, M5.5's decline rule in 1000
  Genomes' own PCA space). Placed: super-population primary, population and pooled beside
  it. Declined, unplaced or saved-only: pooled, `ancestry_matched: false` with the reason.
- Allele orientation is the engine's shared `orient()`; palindromic rows, ambiguous or
  four-allele loci, missing calls and ploidy conflicts are excluded and counted. Panel
  VCFs are verified against the lock in the extraction pass; the public extraction is
  cached by score and panel identity.
- `person_dose_basis` records imputed weight share against sequenced hard-call references;
  shrinkage is recorded, not corrected.

Acceptance: **2,766 tests passed, five existing Windows skips**, with pinned PLINK 2/PLINK
1.9/Beagle/bref3 and Java 17. Nineteen new synthetic cases; mutations of the palindrome,
ploidy, group-restriction and lock-digest guards each fail a test. Real-panel acceptance
(public PGS000001, synthetic person): 70/77 rows resolve and every one of 2,504 reference
sums matches an independent PLINK scoring of the raw 1000 Genomes VCFs within 8.4e-6.
All four strict type targets, lint/format, fixture reproduction and full dbSNP card lint
pass. No personal export, private run or new reference payload was used.

M9.5's entry contract follows above; M9.5 is implemented (top of this file).

## Implemented M9.3 and M9.4 entry

`pgs/coverage.py` derives versioned per-score coverage (`schema_version` 1) from the term
evidence in every score result. Score artifacts move to **schema 2**, which guarantees
retained exclusion proof and phase states. `genetics pgs score` embeds it and prints one
line per phase; `genetics pgs coverage RESULT [--scoring-file F] --json` reloads, recomputes
and refuses any mismatch. See [the guide](pgs_coverage.md).

- Source denominators: all authored weighted rows, model-eligible/ineligible by reason,
  unique allele-defined variants, unique positions, repeated rows, multiple effect alleles,
  multi-variant positions, and undefined rows with their raw definitions.
- Before and after are independent. `not_recorded`/`disabled` phases are `unavailable`
  with null metrics; no-overlap is a real 0.0. Unsupported models keep observed rows but
  have null scored fractions. Position presence and usable-dose coverage are separate.
- Original probes (before only): probe count, called positions and duplicate positions as
  identical, complement-concordant, conflicting, insufficient-calls or unclassified.
- Quality is described, never applied: sources, ploidy, methods, DR2 min/max, descriptive
  tenths with absolute weight, and unknown-quality reasons (`not_estimated:<method>`,
  `allele_quality_unknown` for multiallelic REF).
- Schema-1 files are recomputed as `recomputed_legacy`; phase availability comes from the
  table hash and imputation mode, and missing excluded-row proof stays `unknown` with
  evidence-fraction bounds. Bundle format stays 16.

Acceptance: **2,746 tests passed, five existing Windows skips**, with pinned PLINK 2/PLINK
1.9/Beagle/bref3 and Java 17. Twenty new synthetic cases cover the M9.3 contract below,
including nine corruption cases each confirmed to fail at its intended check. All four
strict type targets, lint/format, fixture reproduction and full dbSNP card lint (51 cards,
268 renders, 35 references) pass. No personal export, private run or new reference was used.

**M9.4 entry (implemented; see the top of this file):** a reference distribution and percentile placement for each score, computed
within the ancestry-matched reference group where possible. Score the reference panel with
the same `pgs/engine.py` matrix path and the same allele/ploidy rules so the person and
the distribution share one definition; record the panel, group and per-score coverage of
the reference itself. Where the person's coverage (M9.3) differs from the reference's,
the placement must say so rather than compare unlike sums. A declined or unrepresented
ancestry is M9.5's to interpret; M9.4 must not fall back silently to a pooled group.

## M9.1–M9.2 review and M9.3 entry contract

The [diff review](review_m9_session.md) fixes inferred-allele validation, excluded-term
evidence loss, phase-state overwrites, early flag/output validation, filesystem error
boundaries, stale native reports and arithmetic overflow. Nineteen new synthetic cases
reproduced the defects before their fixes; the focused M9 suite passes 135 cases,
including pinned PLINK arithmetic. No known blocker remains for M9.3.
Review acceptance: **2,726 tests passed, five existing Windows skips**, with all pinned
native tools and Java 17. All four strict type targets, lint/format, fixture reproduction,
full dbSNP card lint (51 cards, 268 renders, 35 references) and staged privacy scanning pass.
Cached public-reference parsing also passes offline; no personal export or run was used.

M9.3 should implement coverage in the shared engine and expose it through private
score JSON/CLI for the M9.6 card renderer. Use `ScoringFile.iter_variants()` for the
source denominator and `ScoreResult.record["terms"]` for per-phase observations.
Keep a versioned persisted coverage contract and validate it when reloading.

- Define both the numerator and denominator. Count all authored weighted rows, including
  unresolved/excluded/model-ineligible rows; distinguish those rows from allele-defined
  unique variants, unique positions and duplicate original probes. Preserve raw definitions
  where a stable allele/locus identity cannot be established.
- Report before and after independently. An `observed` zero dose is covered; a no-call,
  absent marker, allele/strand/ploidy conflict or unsupported definition is not a scored
  term. Position presence and usable allele-dose coverage are separate claims.
- `not_recorded` and `disabled` require unavailable coverage rather than 0%. Saved stage
  direct records are not a complete original-chip inventory. Preserve whole-model
  unsupported and partially scored states even when some individual rows have observations.
- Preserve per-ALT quality and method alongside contributions, including low DR2,
  phase-filled unknown quality, unknown multiallelic REF quality and native haploid doses.
  Quality must not scale dose or hide rows; its confidence use belongs to M9.5.
- Retained exclusion proof may be an original-array probe envelope, one native record or
  an `ambiguous_panel_records` envelope. Older schema-1 score files can lack this proof
  or have overwritten phase states; missing proof must stay unknown or be recomputed.
  PLINK matrix counts and `native_alleles` must never substitute for variant coverage.

Acceptance must cover repeated rows at one locus, multiple effect alleles, concordant and
conflicting duplicate probes, missing/no-call versus observed zero, low/unknown quality,
multiallelic REF, haploid X/PAR, unresolved/special-model rows, original-call precedence,
saved-only input and explicit no-impute. Verify CLI/API/persisted equality and corruption
rejection with synthetic data. M9.4–M9.6 still own distributions, portability and rendering;
M9.3 need not invent a percentile or phenotype interpretation to supply renderer data.

## Implemented M9.2 and next scope

`pgs/engine.py` computes original and post-imputation sums with the pinned PLINK `--score`,
using validated native effect-allele doses in a numeric matrix. The actual locus/alleles,
biological ploidy, original probe evidence and native per-ALT quality remain in the private
record; matrix counts are not coverage. Low/unknown quality never filters or scales dose.
SNP strand, duplicate and ploidy conflicts remain explicit; sequence-resolved imputed
indels require exact sequences, while raw I/D remains excluded. Unsupported models
receive null sums. Used IDs/counts and independent signed-dose arithmetic validate the
native report within the recorded PGEN/text precision bound.

`pgs/workflow.py` reuses shared ingest/ancestry/default-on imputation. `genetics pgs score`
accepts an export (with explicit `--no-impute` only) or a validated saved full stage.
Saved-only scoring cannot invent the original-array sum. Each immutable private
`.pgs-score.json` retains score/metadata/input/stream identities, full used imputation
provenance, PLINK version/binary hash, tool-manifest hash and method/engine versions.
No bundle-format bump or interpretation card is introduced. See [the guide](pgs_scoring.md).

Acceptance: **2,707 tests passed, five existing Windows skips**, with pinned PLINK/ROH/
Beagle/bref3 tools and Java 17. Forty-seven new synthetic cases cover source/dose/quality,
native arithmetic, exact indels, licence/model boundaries, privacy, workflow ordering,
categorical failures and cache-independent saved/CLI equality. All four strict
Windows/Linux × Python 3.11/3.13 type targets, lint/format, fixture reproduction and
full dbSNP card lint pass (51 cards, 268 renders, 35 marker references). No personal
export or new reference/tool payload was used.

**Next M9.3:** turn the saved term observations into per-score before/after variant
coverage with explicit denominators, distinguishing weighted rows from distinct variants,
positions and duplicate probes. Present low-quality and unknown-quality contributions
without filtering them. Before coverage requires the original-array evidence; a saved
stage alone records it as unavailable. Preserve null/no-overlap, unsupported and partial
states. Distribution, ancestry portability and renderer remain M9.4–M9.6.

## Implemented M9.1 and next scope

`pgs/catalog.py` reads the authoritative scores CSV inside the public metadata archive,
retaining every metadata column and duplicate row. `refs/licenses.py` classifies complete
reviewed EBI/CC terms, with explicit restricted, missing, unknown and ambiguous states.
Unknown terms cannot be enabled by restricted-source opt-in. The metadata transform
is now executable in the existing fetch/verify registry and binds its JSON output to
the exact archive and transform through the common checksum/provenance contract.

`pgs/scoring.py` streams format-2 rows, preserving source identities, original/harmonized
builds, all allele/weight columns and special-model features. It rejects malformed/nonfinite
weights and conflicting identities/builds/counts without echoing rows. `genetics pgs inspect`
is the shared offline CLI consumer; parsing computes no personal score and changes no
bundle format. The first selected public source, `pgs000001_grch37`, is in the manifest.
Public acceptance: 6,991 metadata scores and 77 PGS000001 GRCh37 rows, with both hashes
recorded in the lock. No personal export was opened. See [the guide](pgs_ingestion.md).

Validation: **2,660 tests passed, five existing Windows skips**, with pinned native tools
and Java 17. Sixty-nine new synthetic cases cover parser/licence/provenance boundaries,
CLI and privacy ignores. All four strict Windows/Linux × Python 3.11/3.13 type targets,
ruff/format, fixture reproduction and full dbSNP card lint pass (51 cards, 268 renders,
35 marker references). Public-reference CLI/API parity passes with networking blocked.

**M9.1's original M9.2 handoff (now implemented):** implement PLINK score sums from original calls and native imputed dosages.
Call the score-specific licence gate and explicitly support or report special models.
Verify effect-allele orientation, biological ploidy, sum/average and missing-data policy
against the pinned PLINK build using synthetic arithmetic. Preserve dose and quality
separately; DR2 never scales dose. Exhaust/validate parsed streams before accepting results.
M9.3 needs original-array coverage or a saved record, not stage-direct counts alone.
Reference distributions and study-ancestry mapping/`declined` treatment remain M9.4–M9.5.

## M8 overview review

The [overview review](review_m8_overview.md) fixes seven groups of defects: saved scalar
rarity/frequency/hard-call binding, missing allele placeholders, skipped-region ploidy,
phase-handoff byte counts, invalid Beagle option error boundaries, corrupt DEFLATE
handling and missing saved-dosage iterator errors. Thirty new synthetic cases cover
the fixes; all 28 rejection cases reproduced defects before their respective fixes.
Format 16/provenance schema 1 and historical payload meanings remain unchanged.

The final native suite passes **2,591 tests, five existing Windows skips**. All four
strict Windows/Linux × Python 3.11/3.13 type targets, lint/format, fixture reproduction
and full dbSNP card lint pass (51 cards, 268 renders, 35 marker references).
No personal export was opened. There is no known blocker to M9.1's parser/licence work.

### M9.1 accepted implementation scope

The implementation starts with `data/references/manifest.yaml`'s `pgs_catalog_metadata` entry, the
`parse_pgs_score_licenses` step in `refs/postprocess.py` and `refs/licenses.py`.
Implement scoring-file parsing and per-score metadata joins using the current
official scoring-format specification. Preserve PGS id, declared build, allele/weight
definitions and source identities. Bind licences to the metadata CSV's
`License/Terms of Use` column; collection-level permission and scoring-header absence
cannot establish a score's licence. Missing, ambiguous or unknown terms stay explicit
and never default to permissive. Do not hard-code a historical count of licence values.

Exercise malformed rows, nonfinite weights, missing fields, conflicting score/build
identities and licence joins with synthetic inputs. Keep acquisition/provenance within
the existing manifest/fetcher framework, with no reference download required in CI.
Scoring, coverage, distributions and ancestry calibration remain M9.2–M9.5.

`RunBundle.iter_dosages()` streams the full saved stage, including all three sources;
it is not the complete original array. `ImputationEvidence.from_record()` accepts
resolved imputed sources only. Its allele-dose method keeps native dosage and quality
together; direct stage records retain exact observed counts. Phase-filled and
multiallelic REF quality stay unknown. Before-imputation coverage needs original-array
observations or saved coverage; stage-direct counts alone are insufficient. Older
formats must not be given invented full dosages or coverage. The existing population
mapping/`declined` ancestry portability work remains M9.5.

## Implemented M8.7 and next scope

Thirty-two synthetic regressions in `tests/imputation/test_quality.py` prove the
strict rarity ceiling across untyped/phase-filled sources and native haploid/diploid
observations. DR2 1 and strong replicated literature cannot rescue a frequency below
0.00001; equality and the next higher float remain outside that band. Unknown
phase-filled quality stays unknown and contributes zero. Known rare alleles survive
missing companion frequencies; common-only incomplete coverage stays unknown and an
unobserved rare allele does not penalize the call. Multi-marker findings inherit the
weakest marker without averaging quality or assuming phase.

Fully saved format-16 runs retain rarity, selected frequency, source/native dosage and
quality, benchmark scope and caveats in CLI JSON and dashboard face/detail after the
synthetic stage cache and frequency index are removed. Enabled direct probes and
explicit opt-out preserve original observations. ClinVar still consumes original-array
input. Chip 16% and BRCA 4.2% benchmarks stay study-specific and explicitly uncalibrated
for imputation, never individual posterior probabilities. Isolated in-memory bypasses
fail all four below-boundary cases and both missing-companion cases. The shared engine
needed no fix; bundle format 16 and persisted meanings are unchanged.

Validation: **2,561 tests passed, five existing Windows skips**, with pinned native ROH,
Beagle and bref3 tools enabled. All four strict Windows/Linux × Python 3.11/3.13 type
targets, lint/format, fixture reproduction and full dbSNP card lint pass (51 cards,
268 renders, 35 marker references). No personal export was opened; new tests need no
reference downloads. See [the quality guide](imputation_quality.md#rare-call-frequency-gate-m87).

**M8.7's original M9.1 handoff (now implemented):** parse PGS Catalog scoring files and bind each score to its authoritative
licence in `pgs_all_metadata_scores.csv`'s `License/Terms of Use` column. The scoring
header is not the licence authority (AGENTS.md §4.8); do not assume catalogue-wide
permission. M9 then owns PLINK scoring, pre/post-imputation per-score coverage,
ancestry-matched distributions and portability calibration. Preserve the existing
native effect-allele dosage/quality interface: no DR2 dose scaling, no per-ALT quality
averaging and no invented multiallelic REF quality. The pending AADR-population to
study-ancestry mapping and `declined` portability treatment belong to M9.5.

## Implemented M8.6 and next scope

Format 16 adds durable full dosage files, byte-identical panel/map catalogs and
`imputation.provenance.run.json` schema 1. Used source releases, catalog/target/tool/
runtime hashes and each region's actual phase/imputation parameters come from the
completed stage. The general installed-reference/tool inventory does not substitute
for them. Independent copies and atomic staging preserve the source and reject partial
publication. Normal enabled analysis saves require their complete stage; disabled,
no-eligible-job and low-level not-recorded states remain distinct.

Readers validate saved bytes without caches or current manifests: counts, typed
retention, region/ploidy/native dosage contracts, source/quality, phase handoff,
catalog/artifact identities and card/full-dosage agreement. Full multiallelic records
and native haploid quality remain intact. Formats 1–15 retain original meanings.
`RunBundle.iter_dosages()` and `runs imputation --dosages` share the native record
contract. `runs imputation --json`, `runs show` and the dashboard expose saved provenance.
Copy/validation progress is genotype-free. See [the provenance guide](imputation_provenance.md).

Synthetic verification covers cache removal, installed-inventory differences,
corruption after rehash, failed copies, zero-job execution, opt-out, historic shapes,
privacy ignores and native/multiallelic contracts. Native CLI acceptance saves all
800 records over four jobs, verifies 396 direct/four phase-filled/400 untyped sources,
per-ALT/native haploid scope and completed reuse. No personal export was opened.

Validation: **2,524 tests passed, five existing Windows skips**, with native tools
enabled. Fifty-three new synthetic cases cover the full snapshot contract. All four
strict Windows/Linux × Python 3.11/3.13 type checks, lint/format, fixture reproduction
and full dbSNP card lint pass (51 cards, 268 renders, 35 marker references).

The subsequent [M8.6 diff review](review_m86_session.md) fixes per-card/per-marker
full-record binding at shared loci, strict native storage vector types and categorical
publication errors for malformed stage regions. Five regressions reproduced the defects
before the fixes. Format 16 and provenance schema 1 are unchanged.
The review's complete native suite passed **2,529 tests, five existing Windows skips**;
all four strict type combinations, lint/format, fixture reproduction and full card lint
also pass. There were no known blockers before M8.7 acceptance.

**M8.7 acceptance (completed):** dedicated regressions prove the frequency gate applies to
imputed observations, regardless of high DR2, strong literature or enabled mode.
Cover untyped and phase-filled sources, native haploid/diploid observations, missing
frequency companions and multi-marker inheritance. Show rare findings as likely artifacts;
never filter them. Keep the 16%/BRCA 4.2% chip benchmarks scoped to their studies and
explicitly uncalibrated for imputation, never an imputed-call posterior probability.
Current ClinVar/QC/coverage/structure still use original array input. M9 owns PGS sums,
coverage and ancestry portability; preserve the native effect-allele dose/quality contract.

### M8.7 implementation handoff

Completed 2026-10-08; the matrix below records the accepted scope. The current handoff
is M9.3 above.

Start in `engine/confidence.py` (`calculate_confidence`), `engine/evidence.py`
(`_confidence_frequency` / `assemble_card`) and `run/pipeline.py` (`observations`).
The current gate already caps a known observed-allele frequency **strictly below
0.00001 (0.001%)** at `likely-artifact`, independently of source and DR2. Extend
the existing quality tests and add integration regressions; change the shared engine
only where a reproduced failure warrants it.

| Boundary | Required evidence |
|---|---|
| Frequency below, exactly at and above 0.00001 | Below remains `likely-artifact` with strong replicated literature and high DR2; equality is outside this rare-call band. Other confidence ceilings still apply. |
| Imputed-untyped and phase-filled no-call; ploidy 1 and 2 | All four combinations retain the rarity ceiling. Phase-filled quality stays unknown, with zero quality contribution; no fabricated DR2. |
| Observed alleles with missing frequency companions | A known rare allele retains the rarity gate even if its companion is missing. Common-only incomplete coverage remains unknown and cannot establish strong confidence. An unobserved rare allele must not penalize the call. |
| Multi-marker findings | A rare imputed marker caps the whole finding through weakest-marker inheritance. No implicit phase or quality averaging. |
| Save/reopen and both front ends | Tier, selected allele frequency, source, native dosage/quality, empirical benchmark scope and caveats agree in CLI JSON and dashboard face/detail. Findings remain present. |
| Original-array control and opt-out | Direct observations stay original. Explicit `--no-impute` does not discover imputation prerequisites or synthesize an imputed observation. |

Use generated inputs and synthetic frequency lookups, including fully saved format-16
snapshots where relevant. Do not require reference downloads in CI. The 16% rare-call
and BRCA1/2 4.2% numbers remain study-specific chip benchmarks; an imputed observation
must not present either as its confirmation probability. BRCA-specific calibration
currently belongs to original-array ClinVar findings, so this milestone does not create
an imputed ClinVar calling path. No bundle-format bump is needed for regressions alone;
any changed persisted meaning needs its own compatibility decision and corruption tests.
These checks pass and M8.7 is recorded complete in the roadmap and this handoff.

## Implemented M8.5 and next scope

Quality-aware interpretation cards retain original direct probes and can use exact
biallelic SNV imputation for absent/no-call loci. Native DS/per-ALT DR2, source, biological
ploidy, method and quality scope remain attached to each marker. Low DR2 uses existing
confidence ceilings without filtering; phase-filled no-calls stay unknown quality with
a zero quality contribution and limited ceiling. Multi-marker confidence inherits its
weakest marker, without assuming phase. ClinVar/QC/coverage/structure retain original
array input. The allele-dose interface for M9 scoring preserves each ALT's quality;
multiallelic REF quality remains unknown without covariance, never averaged.

Format 15 / execution schema 2 saves the quality-aware observation basis and scalar/
marker evidence. Saved validation binds native quality/source/ploidy and confidence
ceilings; CLI/dashboard use the same snapshots. Formats 1–14 retain original meanings.
See [the quality guide](imputation_quality.md).

Validation adds 54 synthetic cases, including native Beagle quality propagation,
saved unknown quality, direct-probe preservation, per-ALT contracts, native haploid
scope, weakest-marker inheritance, reference-oriented palindromic sites, corruption
and CLI/dashboard parity. Full native tests and all four strict type combinations,
lint/format, fixture reproduction and full dbSNP card lint cover the changes. The
additional format-13 downgrade guard is checked separately from the full local run.
No personal export was opened.

**M8.5 handoff (implemented in M8.6):** durably copy full dosage records into the private bundle with exact
used-panel/map/tool/runtime versions, hashes and parameters from the stage contract,
including per-region/ploidy options. Current execution summaries and used-card evidence
are not full provenance. Validate publication/reuse and preserve historical formats;
reopening a run must not depend on its stage cache or a newer reference lock. M9 score
consumers must receive dosage and allele quality together. M8.7 owns dedicated
imputed rare-call gate regressions. Keep all generated data outside Git.

## Implemented M8.4 and next scope

`analyse` / `genetics run` now execute the M8.3 stage by default after ancestry and
before card assembly. `--no-impute` is explicit, defaults false, skips stage/reference/
tool discovery, and records disabled mode on the run and every card. Prerequisite and
execution failures report an imputation error without a saved bundle or automatic
fallback. Existing development fixtures now choose the escape hatch explicitly.

Format 14 adds private `imputation.run.json` schema 1 and per-card mode. It distinguishes
enabled/computed, enabled/no-eligible-jobs, explicit disabled and not-recorded execution.
Source/region/job counts, ploidy and status are validated; reader/writer require card/run
mode and observation-basis consistency. Formats 1–13 keep null mode, never an inferred
opt-out. Low-level writers without a stage context record unknown mode. CLI JSON/human
output, dashboard banner, card face/detail read the same saved snapshot without caches.

**2,417 tests passed, five existing Windows skips**, native tools enabled; 48 new cases
cover default ordering, explicit opt-out, missing prerequisites, failures, saved damage,
historical formats, privacy, CLI/dashboard parity and a native default CLI run producing
800 records and reusing completed jobs. Native acceptance exposed Windows error 267
at a 265-character working directory; the wrapper selects a shorter ancestor while
keeping absolute job paths/contracts unchanged. Synthetic preparation is shared with
M8.3 acceptance. Strict four-way types, lint/format, fixtures and full card lint pass.
No personal export was opened. See [the mode guide](imputation_mode.md).

**M8.4 handoff (implemented in M8.5):** consume the separate `Analysis.imputation_result` through quality-aware
card/score observations. Current findings, ClinVar, coverage and structure still use the
original array table; the UI states that basis. Do not replace original direct calls,
price phase-filled no-calls as perfectly typed, average per-ALT DR2 without an allele
contract, convert native haploid quality into diploid quality, or filter low-quality
findings. `ObservationEvidence` currently requires numeric imputed quality, so its
unknown-quality contract must be resolved before phase-filled calls enter cards.
Context schema 1 currently records `card_input=original_array`; extend that contract
when findings begin using imputed observations. M8.6 owns durable full dosages and
exact used-panel/tool/parameter provenance; current mode snapshots promise execution
outcome only. M8.7 owns explicit imputed rare-variant gate regressions.

## Implemented M8.3 and next scope

`genetics.imputation.impute` is the shared phasing-then-imputation stage, exposed by
`genetics impute`. It streams allele definitions from the complete bref3, checks its
decoded semantic summary, harmonizes normalized calls using existing strand/indel
rules, and gives both Beagle invocations the full panel. Default catalogs bind to the
current manifest/lock; there is no rate-map or direct-overlap fallback.

Autosomal jobs and five inclusive X intervals partition biological scope. PAR1/PAR2
use their own maps; non-PAR follows QC sex. Unknown ploidy, contradictory calls,
duplicate positions and regions without two observed anchors remain explicit.
Original input stays separate from direct, phase-filled no-call and imputed-untyped
observations. Each ALT retains its dosage and finite DR2 where estimated. Phase-filled
no-calls have unknown quality even if the second invocation labels them typed.
Male non-PAR targets use native haploid GT/dosage/DR2, with a 0-1 dose scale and a
recorded haploid model; wrong-copy-count output is refused. The full reference keeps
its required diploid encoding. Independent dosage rounding is allowed at the pinned
writer's hundredth precision. Low DR2 is never a filter.

Schema-1 private outputs/checkpoints stay under the outside-repo cache by default.
Kernel locks and stable region prefixes permit completed-job reuse and incomplete-job
restart. Exact typed-marker retention, sample/region identity, allele orientation,
dosage/quality cardinality/ranges and genotype preservation across both stages are
checked before atomic dosage publication. Reuse regenerates observations and compares
them with saved files/metadata, catching even a changed dosage with an updated hash.

**2,369 tests passed, five existing Windows skips**, with native ROH, Beagle and bref3
tools enabled. Seventy-seven M8.3 cases include native fixed-seed male/female targets:
each produces 800 records over an autosomal and three X region jobs, with 396 direct
calls, four phase-filled no-calls and 400 newly imputed markers. Full references stay
unchanged and completed reuse passes. The two Windows launcher-cancellation checks
require working OS process-control permissions; both pass outside the restricted
sandbox. Strict four-way types, lint/format, fixture reproduction and full card lint
pass. All installed 23 panels / 84,739,838 records and 25 maps / 3,395,051 rows pass
read-only default-contract validation. No personal export was opened.

**M8.3 handoff (implemented in M8.4):** integrate the stage into default-on `analyse`/`genetics run`, add the
explicit recorded `--no-impute` escape hatch, and ensure every affected card/run states
the mode. The M8.3 command/stage is already available; do not build another imputation
engine. Existing analysis and bundle format 13 remain unchanged until that integration.
M8.5 owns quality propagation, M8.6 bundle provenance and M8.7 imputed rare-call gate
regressions. M8.4 must preserve the unknown quality of phase-filled no-calls, keep
original direct calls for ClinVar/structure and retain the native target ploidy and
quality-model scope. See [the pipeline guide](imputation_pipeline.md).

## Implemented M8.2 and next scope

The [session diff review](review_m8_session.md) covers M7.6 through M8.2 and fixes
Beagle output sample/region binding, cleanup fallback, reference kind/transform/input-set
validation, catalog recovery without the original Java installation, reordered build
metadata and runtime drift before publication. Prepared references remain intact.
The reviewed suite passes **2,292 tests, five existing Windows skips**, with native
tools enabled; strict four-way types, lint/format, fixtures and full card lint pass.
Fifteen added regressions cover the fixes. Full panel/map verification passes.

`refs/imputation.py` and executable reference post-processing prepare the full 1000
Genomes autosomes and X as chromosome bref3 panels. No array intersection, LD/MAF
filter or sample removal is permitted. Converter and decoder are independently pinned
to `27Feb25.75f`; the converter requires Java 11+, even though Beagle itself supports
Java 8. Local acceptance uses a checksum-verified portable Temurin Java 17 runtime,
configured through `JAVA_HOME` for the work commands; system Java remains unchanged.

Each completed chromosome has full source-to-decoder semantic comparison, sample-order
identity, input/tool/runtime hashes and an atomic checkpoint. Incomplete attempts restart;
completed chromosomes are reused after verification. Source/tool drift, corruption,
stale contracts and malformed catalogs fail explicitly. Kernel locks prevent concurrent
writers. `refs verify` remains read-only and validates all catalog companions.

The separate pinned HapMap archive supplies all **25 GRCh37 maps / 3,395,051 rows**.
Maps are preserved byte-for-byte and checked for labels, ordering, cM validity and
physical bounds. Catalog counts are checked against actual map files. Source version,
archive SHA and companion hashes bind map reuse; no constant-rate map is invented.
See [the reference guide](imputation_reference.md).

Full-release acceptance completed **23 chromosomes / 84,739,838 records / 2,504 samples
each**, preserving sample order and producing **8,312,115,275 bref3 bytes**. Every
chromosome passed decoded semantic comparison and input/tool-drift checks. Final
source/catalog/companion verification passed. These are public-reference properties;
no consumer export was used. All reference payloads and workspaces remain ignored.

X haploid reference calls are explicitly doubled for storage and counted in metadata.
This does not establish diploid consumer ploidy. Y is fetched but excluded from Beagle
preparation because of missing haploid calls and no supplied genetic map; MT is absent.
Those limitations are explicit in the panel catalog. Existing direct-call and haplogroup
engines retain their scope.

**M8.2 handoff (implemented in M8.3).** Start with consumer-target VCF harmonization against the prepared
GRCh37 reference alleles, using the existing strand/indel/QC rules. Partition X PAR and
non-PAR jobs using sample ploidy, recorded bounds and matching maps. Call the M8.1
wrapper through a shared phasing/imputation stage, write private dosages and per-variant
DR2, and test the full stage offline with generated targets. Reuse completed jobs;
never splice interrupted Beagle windows. M8.5 owns quality propagation into scores;
M8.6 owns saved run-bundle provenance and M8.7 owns imputed rare-call gate regressions.
M8.2 changes neither bundle format 13 nor `genetics run` behavior.

M8.3 acceptance must check exact target sample identity and requested regions (now
enforced by the wrapper), preservation of every eligible typed marker, explicit exclusions,
dosage scale/allele orientation and finite per-variant DR2. Keep original direct calls
separate from imputed calls and preserve the source/quality needed by M8.5–M8.7. Verify
PAR/non-PAR output against biological ploidy before interpreting doubled X storage.
Exercise missing references/tools/maps, malformed output, cancellation, recovery and
shared CLI/dashboard behavior. Do not infer correct dosage or marker retention merely
from a valid phased VCF. Application `--no-impute` remains the separately recorded M8.4
escape hatch; Beagle phase-only mode can still fill sporadic missing target calls.

Validation: **2,277 passed, five existing Windows skips**, with native ROH, Beagle,
converter and decoder enabled. Fifty-one new synthetic cases cover exact full-record
retention, multiallelic/indel/symbolic alleles, X encoding, malformed inputs/build metadata,
map corruption and counter forgery, cancellation, lock release, checkpoint recovery,
stale tools, Java readiness and native Beagle consumption. Default consumer contracts
bind the current manifest and lock without reading raw VCFs. Strict Windows/Linux ×
Python 3.11/3.13 typing, ruff/format, fixture reproduction and full card lint pass
(51 cards, 268 renders, 35/35 marker references). No personal export was used.

## Implemented M8.1 and next scope

`external/beagle.py` supplies exact-jar discovery, Java 8+ checks, typed memory/seed/
thread/mode options, streamed private diagnostics and safe progress. Doctor uses the
same readiness rules. Inputs, jar and runtime identity are recorded in a schema-1
private checkpoint; a completed output directory is published atomically after VCF
integrity and input-drift checks. Reuse verifies all recorded outputs and rejects changed
contracts. Kernel locks survive process crashes without stale lock ownership. Timeout
and cancellation terminate the child before releasing the lock. Interrupted jobs restart
from their inputs; M8.3 must reuse completed chromosome jobs rather than splice Beagle
windows. Workspaces and locks are ignored even inside the knowledge-pack allowlist.

The suite passes **2,226 tests, five existing Windows skips**, with pinned native ROH
and Beagle enabled. Strict Windows/Linux × Python 3.11/3.13 typing, ruff/format,
fixture reproduction and full card lint pass. Thirty-eight new synthetic cases cover
discovery, private progress, failures, cancellation, crash-released locks, changed inputs,
corrupt checkpoints, restart and native execution. Native Beagle 5.5 / `27Feb25.75f`
on Java `1.8.0_491` phases and imputes one generated target against twenty generated
reference samples, retains DR2/dosages, checks phase-only mode and reuses completion.
CI installs Java 17 and the same pinned jar for Windows/Linux acceptance. No personal
export or real reference individual was used. See [the wrapper guide](beagle.md).

M8.2 implements the full-panel preparation described above. The original M8.1 checkpoint
changes no existing bundle format or `genetics run` imputation behavior.

## Implemented M7.6 and next scope

`health/coverage.py` and the declarative `clinvar_array_coverage` card measure unique
normalized positions and distinct REF/ALT variants from the full pinned ClinVar index.
Both reference-position and chip-position fractions save explicit denominators.
Calls obtained stay separate from resolved alleles; duplicate/conflicting probes,
no-calls, excluded indels, strand ambiguity and unresolved sex-chromosome ploidy are
counted explicitly. Missing references, empty primary-reference scope and zero overlap
remain distinct. Coverage does not estimate clinical sensitivity or confirmed findings.

Format **13** / lookup schema **5** saves these counts, definitions and source identity
in the existing private payloads. Readers check arithmetic, overlapping observations
and card/lookup equality without consulting newer caches. Formats **1–12** retain
their original snapshots. No new output type or privacy exception was introduced.
See [the coverage guide](clinvar_coverage.md).

The suite passes **2,188 tests, five existing Windows skips**, with pinned native ROH
enabled. Strict mypy on Windows/Linux and Python 3.11/3.13, ruff/formatting, fixture
reproduction and full dbSNP lint pass: **51 cards, 268 renders, 35/35 marker references**.
Thirty new regressions cover source/count states, exclusions, saved consistency,
historical formats, rare-call preservation and CLI/dashboard equality.

Scoped M7.6 offline acceptance passed on the committed synthetic fixture against the
complete ClinVar, gnomAD and 84-gene ACMG caches, through format-13 save/read, CLI JSON
and dashboard/detail rendering, with networking blocked (**249.4 seconds**). It excludes
ancestry and ROH/archaic reference preparation; those modules have separate acceptance
and the native ROH tests are enabled in the suite. No personal export was used.
The pinned ClinVar release contains **3,933,850 primary-chromosome positions**,
**4,460,684 distinct REF/ALT variants**, and **4,155,065 matchable biallelic SNV variants**;
eight alternate/unplaced-contig records are excluded from this position denominator.
These are full-reference properties, not measurements of a person's chip coverage.

**M8.1-M8.3 are implemented.** Next integrate default-on imputation and
save panel/tool/parameter provenance. Imputation must be
default-on; `--no-impute` is an explicit, recorded escape hatch. Rare-call reliability
must remain frequency-gated after imputation. M8.5–M8.7 remain upcoming.

## Prior checkpoint
M7.5 checkpoint: `537e3c5`, with [all five CI jobs passed](https://github.com/sovemere/genetics-analysis/actions/runs/37434344709).
The [M7.5 diff-driven review](review_m75_session.md) records outcome-calibration,
saved-record validation, marker-detail and lint-denominator fixes. The earlier
[M7.1–M7.4 review](review_m7_session.md) remains historical context.

## Current local acceptance

The required `gnomad_exomes_r2_1_1_grch37` download is complete. The payload is
63,145,056,967 bytes, publisher MD5 `f034173bf6e57fbb5e8ce680e95134f2`.
Source SHA256: `b5218277d30c0747cfef38bbc8ee4f735ba8b31695fd343cf9f31ff77cfaf9f3`.
The complete `build_gnomad_frequency_index` transform parsed **17,209,972 public
records**. The index is 23,837,532,160 bytes, schema generation 2, SHA256
`1c8a5a4e4cd31de06a9fb7a05f0db255ceff4d1380af6069d3aba17cfeb8caf7`.
`refs verify` rechecked the source and index successfully, with no pending steps or
temporary build files. At M7.2 acceptance, a synthetic-only run against the complete ClinVar and gnomAD
caches passed with networking blocked: five synthetic lookup entries received
frequencies, every card remained present, format-8 reloading matched the saved
snapshot, and CLI JSON/dashboard parity passed. No personal export has been used.

```text
genetics refs fetch --only gnomad_exomes_r2_1_1_grch37
genetics refs verify --only gnomad_exomes_r2_1_1_grch37 --json
```

Keep the required exomes source separate from the optional 495 GB genomes source.
The optional genomes payload is not needed for this accepted milestone.

## Implemented M7.2

`gnomad_frequencies.sqlite` contains the entire public sites reference, with REF/ALT,
FILTER, global/population AF/AC/AN/homozygote counts and publisher popmax annotations.
Header assembly/cardinality, counts and rounded AF are validated. Committed SQLite
checkpoints bind source identity and a cumulative record checksum; restart replays
gzip and skips already committed parsing. Final output/provenance are checksum-bound.
`refs status` reports a partial index as resumable processing.

Queries use memory-only sample loci against a read-only index. A sample-selected
reference subset never lands in the repository. Missing, filtered, incompatible,
duplicate and unresolved multiallelic/indel records remain unknown, never zero.
Usable alternates are screened at their highest available population frequency;
all nine reported East Asian/European subgroups are included alongside the major groups.
The population is disclosed and is not inferred ancestry. Split source loci leave
REF frequency unknown rather than assigning other alternates to REF.

Interpretation cards use the same source through the existing confidence engine.
A measured rare allele cannot escape `likely-artifact` because its companion's
frequency is missing or its imputation quality is high. ClinVar receives a separate
measurement-reliability screen, without fabricated penetrance or claim evidence.
Below 0.001%, the generic 16% heterozygous-chip confirmation benchmark is attached
and explicitly distinguished from an individual's posterior probability.

M7.3 puts the published confirmed/unconfirmed percentages on the face and in CLI
summaries. Exact `GENEINFO` symbol/NCBI-ID pairs plus germline pathogenic/likely-pathogenic
`CLNSIG` select the BRCA benchmark; mixed, uncertain, conflicting, somatic and
included-haplotype annotations do not. Missing frequency or unresolved observations
still receive no numerical PPV. Imputation-quality failures without a benchmark say so.

New bundles use **format 14**, with ClinVar lookup schema **5** in the existing private
`clinvar.run.json`. CLI JSON and the dashboard read the same saved records. Formats
1–12 retain their original results and notices, including schema-2 BRCA entries with
the original generic benchmark. See [the frequency guide](health_frequencies.md).

M7.1's complete pinned ClinVar index contains **4,461,445 records** from 2026-08-04.
All INFO classifications/conflicts/review status and ambiguity states remain intact.

## Implemented M7.4

The complete 84-gene ClinGen ACMG SF v3.3 roster and reporting guidance is fetched,
hash-pinned and verified under CC0. Its 54,071-byte payload SHA256 is
`8089748ab8645336eedab56e4f548f7c902e2f7d163fa3a559b49c9fbd93151d`.
All overlaps remain visible in a dedicated dashboard view and `runs secondary` CLI
view, with the existing reliability and PPV calculations unchanged. P/LP reference
annotations remain distinct from clinical reportability, which is not adjudicated.
Each overlap states the clinical-sequencing limitation; missing prerequisites are
explicit and an empty result cannot be interpreted as a negative screen.

Schema 4 saves the complete source roster, guidance, provenance and overlap metadata.
Validation uses the saved roster without consulting today's source. Older runs retain
their original results and explicitly lack this stage. See [the ACMG guide](secondary_findings.md).
Offline acceptance passed against the complete ClinVar/gnomAD caches using five
fabricated calls spanning BRCA1, TTN, ABCD1, CYP27A1 and PLN, with the full 84-gene
roster. Networking was disabled; snapshot validation and the shared view passed.

<a id="next-m75"></a>

## M7.5 implementation and accepted scope

M7.5 adds three declarative cards under `knowledge/health/`: HFE C282Y, Factor V Leiden
and APOE. These authored associations remain distinct from ClinVar/ACMG reference lookups.
The following requirements are implemented; [the guide](common_health.md) records source
scope and the numerical rates/baselines this curated pack does and does not transcribe.

1. Add declarative `knowledge/health/` entries for tractable single-marker claims first,
   using dbSNP-verified GRCh37 keys and primary sources. Each card needs effect units,
   population, sample size, replication, DOI/accession, and genotype-specific wording.
2. State published absolute outcome rates, baseline, time horizon, and applicable
   age/sex/population strata on the face. Do not turn a ClinVar classification or a
   SNP-chip PPV into disease risk, or convert an odds ratio into absolute risk without
   a defensible baseline. Explicitly state when a source supplies no applicable rate.
3. APOE allele interpretation uses both rs429358 and rs7412, not a one-marker shortcut.
   Schema 2 extends declarative matching with exhaustive haplotypes/diplotypes, retaining
   both observations before reporting a uniquely compatible SNP pattern.
   Preserve missing calls, discordance, and phase ambiguity as visible outcomes. The
   rare fourth haplotype cannot be ruled out merely because the common three are more
   frequent ([Seripa et al., 2011](https://doi.org/10.1089/rej.2011.1169)). Imputation/
   phasing remains upcoming M8; do not assume it has run.
   Format 11 saves both marker observations, locus-specific frequency/calibration and
   phase candidates. Formats 1–10 and ClinVar schemas 1–4 retain their original meanings.

The review adds **knowledge schema 3**, supporting complete outcome-specific evidence
overrides or explicit `evidence: null`. Evidence is selected before confidence is computed
and saved. APOE common outcomes use their corresponding Rasmussen cohort effects;
F5 homozygotes use the homozygote estimate. Comparator, rare-pattern and unestimated
HFE/F5 outcomes carry no borrowed phenotype estimate and receive limited confidence,
with rarity/quality gates still active. Unresolved APOE phase receives no phenotype
estimate. Each marker's call source, quality, ancestry-match input, reliability inputs
and available benchmark are visible in detail. Full lint counts marker references,
giving **35/35**, rather than dividing them by 34 interpretation cards.

**Format 12 / multi-marker schema 2** records these meanings. Saved validation binds
marker confidence to recorded observation metadata, the rarest usable called allele,
and the saved phenotype effect, preserving frequency/quality limits. Formats 1–11 remain
immutable snapshots; a format-11 run keeps its original card-wide effect even when the
current pack has a different outcome estimate. Re-run to obtain the correction.

Synthetic checks must cover all supported allele combinations, missing/discordant
observations, phase ambiguity, unknown frequencies, rarity gating, and save/read/CLI/
dashboard parity. Existing `{frequency}`/`{ppv}` placeholders and the confidence engine
are available. Run full card lint against the cached dbSNP index and keep all personal
outputs outside the checkout.

## Accepted M7.6 scope (retained for review)

Add a quantitative coverage-honesty card: how many ClinVar positions the array actually
covers and what that does and does not establish. Compute the denominator and overlap
from the sample's chip positions and fetched reference; the roadmap's ~76k is an earlier
chip measurement, not a universal constant. Distinguish positions from allele-specific
matchable variants, markers present from calls obtained, and reference annotations from
clinically confirmed findings. Missing references must stay explicit; an empty overlap
cannot imply a negative clinical screen. Preserve the same saved CLI/dashboard contract.

Use the complete pinned GRCh37 ClinVar index through the existing shared pipeline,
and save a source-bound counting record rather than counting again when a run is opened.
Define the counters and denominators in that record:

- Deduplicate reference positions by normalized chromosome/GRCh37 coordinate; multiple
  records or alternate alleles at one site count once as a position. Define separate
  variant/allele counters and disclose any reference filtering.
- Deduplicate chip positions across probe aliases; disclose duplicate/conflicting probes.
  A listed no-call position is present on the export but is not a successful call.
- Report both reference-position coverage (overlap / reference positions) and the share
  of chip positions annotated by ClinVar (overlap / chip positions). Label both denominators.
- Separate present-position overlap, called-position overlap and allele-resolved matches.
  Keep no-calls, indels, unresolved strand/ploidy and conflicting observations explicit;
  positional overlap alone never establishes a particular allele.
- Preserve classifications and the assay/rare-call limits. Coverage is neither sensitivity
  nor a count of confirmed pathogenic findings. Scope the ACMG roster separately.
- Distinguish missing source, empty reference, zero overlap and incomplete/bad input;
  avoid division by zero or a fabricated negative screen.

Synthetic regressions should exercise repeated reference alleles, duplicate chip probes,
no-calls, excluded indels, missing/empty references, zero overlap, digest-consistent
malformed counts, and save/read/CLI/dashboard equality. The saved reader must validate
counter relationships and provenance using the snapshot, without consulting newer caches.
M7.6 is now implemented. Its overlap is computed per export; no new personal-chip
measurement is claimed. The original ~76k figure remains historical context only.

M7.6 owns quantitative coverage honesty. All low-confidence findings
remain visible. Study-to-sample ancestry calibration remains M9.5; source-license
audit remains M15.4. M6's missing chip/population calibration stays attached.

## Download contract

Publisher-checksummed sources resume and verify their final digest. Digestless frozen
sources require an explicit immutable flag, fixed size and matching URL/size/prefix-hash
sidecar. Changed or damaged provenance restarts; rolling files restart. The 24 frozen
1000 Genomes chromosome files declare immutability. None of this permits weakening
privacy, pinning or the pre-commit checks.

## Validation

The M7.5 implementation suite passed **2,135 tests, five existing Windows skips**, with pinned native
ROH enabled. Ruff/formatting, strict mypy on Windows/Linux and Python 3.11/3.13,
fixture reproduction and full card lint pass (50 cards, 266 renders, 35 dbSNP keys).
Synthetic-only acceptance against the complete ClinVar/gnomAD caches passed with networking
blocked, through format-11 save/read and CLI/dashboard parity. No personal export was used.
M7.5 adds 59 cases covering all APOE observation combinations, rare-haplotype/phase
preservation, missing/discordant/non-diploid calls, HFE/F5 forward-strand and duplicate
matching, unknown/rare frequencies, per-marker quality, malformed saved evidence,
format-10 compatibility and both interfaces.
The follow-up review passes **2,158 tests, five existing Windows skips**, including pinned
native ROH. Its 23 new regressions cover outcome-specific and absent effects, rarity/quality
gates, constituent identity, lint denominators, schema-3 boundaries, saved consistency,
format-11 immutability and marker-detail metadata/PPV. See the review record for checks.
M7.3 adds 31 synthetic cases for exact BRCA/classification scope, numerical face/detail
and CLI presentation, unavailable PPV, placeholder contexts and historical schema-2
save/read/CLI/dashboard compatibility. Tests also cover rare thresholds/counts/populations,
missing/filtered/split/duplicate
records, direct/imputed gating, malformed headers, checkpoint recovery/corruption,
saved integrity, format-7 compatibility, CLI/dashboard parity and citation privacy.
M7.4 adds 42 synthetic cases for exact gene membership, annotation/reportability
separation, source completeness/checksum refusal, unsuppressed ambiguity and reliability
states, missing-source/empty-screen honesty, saved metadata integrity, format-9
compatibility and CLI/dashboard parity with 101-locus pagination.
The review adds twelve malformed-cache/snapshot regressions, including schema-2/3/4
bundle, CLI and dashboard error handling, and verifies the ACMG title/count scopes.
The cache-reuse test now keeps its gzip source unchanged: regenerating it changed the
header timestamp/checksum and caused a legitimate rebuild, producing a flaky CI failure.

Before committing, inspect `git status --porcelain`, stage only code/docs/reference
metadata, run `genetics check-staged`, and keep the privacy hook enabled. Public
references, indexes, personal outputs and temporary synthetic bundles stay uncommitted.
