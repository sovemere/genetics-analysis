# Handoff: M9 PRS engine

As of 2026-10-09, **M0-M8 are implemented**. Full local reference verification was
completed in the preceding milestones; the current synthetic/offline native suite
passes. Read [AGENTS.md](../AGENTS.md) first, then [the roadmap](../phase1_roadmap.md).
M9.1–M9.4 are implemented and reviewed, and M9.5–M9.6 are implemented. Next is M9.7.

## Implemented M9.6 and M9.7 entry contract

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

**M9.7 entry contract** (Physical health PRS cards):

- **Authoring only.** Author cards in `knowledge/health/` with `kind: polygenic`. Each
  score needs a manifest entry pinning its harmonized GRCh37 scoring file. Prefer
  permissive licences, because a run cannot opt in to restricted ones.
- **Citations.** Every effect, within-family estimate and decile rate is cited from the
  primary paper and checked against it (AGENTS.md §6). Without published decile rates,
  omit `decile_outcomes`; the face then says a position is not a risk.
- **Acceptance.** Fetch the scores, run `cards lint` in full, and check one public 1000
  Genomes stand-in through `genetics run` and the dashboard.

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
