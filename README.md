# genetics-analysis

An offline-capable personal genome interpreter with one analysis engine, a CLI and a
local dashboard. Findings carry evidence, citations and explicit uncertainty. This is
an educational instrument, not a diagnostic.

Read [AGENTS.md](AGENTS.md) before working with data or code. This repository is public:
personal exports, measurements, run bundles and logs must stay outside Git. Tests use
synthetic data; reference payloads are fetched, never committed.

## Current state and handoff

M0–M10 are implemented. The current slice includes ingest/QC, cited trait and assay-limit
cards, ancestry, long ROH, archaic allele-sharing ranges and sex-chromosome call patterns.
M7.1 adds ClinVar position/allele lookup with preserved source classifications,
ambiguity states and provenance. M7.2 supplies allele-specific gnomAD frequencies to
confidence and a separate ClinVar measurement-reliability screen. M7.3 presents scoped
confirmation benchmarks on the card face and in CLI output, including pathogenic BRCA
annotations. M7.4 surfaces all ACMG SF v3.3 gene-list overlaps with their reliability,
reportability limits and gene-specific guidance. M7.5 adds cited APOE, HFE C282Y and
Factor V Leiden cards with cohort absolute-risk context and explicit baseline gaps.
APOE uses both defining SNPs and preserves the rare fourth haplotype and unresolved phase.
The review corrects outcome-specific evidence and exposes each marker's quality inputs.
M7.6 adds a quantitative array/ClinVar coverage card: unique reference and chip positions,
calls obtained, allele-resolved matches, explicit denominators and source-bound saved counts.
Coverage is not clinical sensitivity or confirmed pathogenic findings.
New runs use bundle format **20**; formats 1–19 remain readable without reinterpreting saved findings.

**M8.1 is complete:** the pinned Beagle wrapper checks Java, configures memory,
reports progress and reuses verified completed jobs. Interrupted jobs restart from
their inputs. The [Beagle guide](docs/beagle.md) documents the private checkpoint contract.
`genetics run` now executes the shared imputation stage by default (M8.4).

**M8.2 implements full per-chromosome reference preparation:** pinned bref3
conversion and full decoded verification, resumable chromosome checkpoints, source/tool
provenance and complete GRCh37 genetic maps. See [reference preparation](docs/imputation_reference.md)
for setup, Java 11+ and explicit X/Y/MT scope.

**M8.3 supplies shared phasing then imputation:** `genetics impute` harmonizes the target,
preserves eligible typed calls, partitions X PAR/non-PAR jobs, and writes private per-ALT
dosages/DR2 with explicit biological ploidy, source and missing-quality states. Completed
jobs and observations are verified before reuse. See the [pipeline guide](docs/imputation_pipeline.md).
**M8.4 makes imputation default-on in `genetics run`:** `--no-impute` is an explicit
development/testing mode recorded in the run and every card. Format 14 preserves the
execution summary, CLI/dashboard mode parity and historical unknown states.
**M8.5 propagates imputed dosage quality into card confidence:** absent/no-call
biallelic SNVs can supply observations; direct calls remain original. Low DR2 lowers
confidence, phase-filled unknown quality caps it at limited, and every finding remains
visible. Native ploidy, per-ALT dosages/DR2 and source survive format-15 snapshots.
See [quality propagation](docs/imputation_quality.md) and [the mode guide](docs/imputation_mode.md).
**M8.6 saves full imputation dosages and exact used provenance:** independent dosage
and catalog copies, used panel/map/tool/runtime identities and per-region parameters
remain readable without stage caches. CLI `runs imputation` and the dashboard use the
same saved snapshot. See [full provenance](docs/imputation_provenance.md).
**M8.7 verifies the rare-call frequency gate for imputation:** 32 synthetic cases cover
strict frequency boundaries, native sources/ploidies, missing companions, weakest-marker
inheritance and saved CLI/dashboard parity. Strong literature and high DR2 cannot rescue
rarity; chip confirmation benchmarks remain explicitly uncalibrated for imputation.
The full native suite passed **2,561 tests, five existing Windows skips**; all four
strict type targets, lint/format, fixture reproduction and full dbSNP card lint pass.
No shared-engine or bundle-format change was needed. **M8 is complete; M9.1's PGS
ingestion, M9.2 scoring, M9.3 coverage and M9.4 reference percentiles are now
implemented, as are M9.5 ancestry portability, M9.6 polygenic cards and M9.7
physical-health cards:** [physical-health PRS cards](docs/physical_health_prs.md)
add PRS3820 breast cancer and genome-wide GPS_Mult coronary artery disease.
Full-panel native imputation, both public scoring stand-ins and saved-record
validation pass. The guide records the screenshot review and post-fix browser gap.
M9.8 [mental-health cards](docs/mental_health_prs.md) are complete: SCZ_GHS
schizophrenia and UK Biobank-only GPpsy broad help-seeking models are authored
and fetched, with their model/release and calibration limits stated. Full-panel
acceptance passes for both default-imputed and explicit no-impute public stand-ins.
The [session review](docs/review_m97_m98_session.md) tightens frozen duplicate-proof
allocation and corrects CAD's European subgroup association.
Final reviewed validation passes **2,875 tests, five existing Windows skips**,
all four strict type targets, lint/format, fixtures and staged privacy scanning.
**M9.9 psychometrics is complete:** cognition, education and neuroticism cards
are authored and reference-pinned, with exact model evidence and unknown direct
within-family effects stated. Full reference preparation, all three default-imputed
and explicit no-impute checks, and six retained JSON disk-read validations passed.
See the [model audit and scale acceptance](docs/psychometrics_prs.md).
The [M9.9 diff review](docs/review_m99_session.md) confirms the authored evidence
and pins, strengthens per-card model-binding tests, and revalidates all six saved
score/card pairs. **M9.10 substance use and behavioural propensity is complete**:
ever smoking, less-frequent alcohol intake and broad self-reported addiction
cards are authored and reference-pinned. Exact model evidence, phenotype
direction and release-selection limits are documented in the
[model audit](docs/substance_use_prs.md). Full reference preparation, all six
public-stand-in scoring checks and six written-record reload validations pass,
with complete models and reused full-autosomal imputation. All 2,881 unique
checks pass, with five existing Windows skips. **M9.11 sleep and circadian is
complete**: evening preference,
log-transformed daily sleep including naps and ordinal sleeplessness remain
distinct endpoints. See the [model audit](docs/sleep_circadian_prs.md) and
[handoff](docs/handoff.md#next-open-step-m912-fitness-and-physiology).
All three full references, six scoring checks and six written-record reload
validations pass, with complete models and reused full-autosomal imputation.
All 2,885 unique checks pass with five Windows skips, all four strict type
targets and full card lint (64/294/35 keys). **M9.12 fitness and physiology
is complete**: four endpoint-specific variant cards and complete PGS002143
mean grip strength are authored and source-audited. Full reference preparation,
both native scoring modes and both written-record disk-read validations pass,
with every source term retained and completed imputation reused.
All 2,923 unique checks pass, five existing Windows skips; all four strict type
targets and full dbSNP lint (69/320/39 keys) pass. See the
[evidence audit and measured acceptance](docs/fitness_physiology.md).
**M9.13 card-level ancestry match is complete.** Variant and polygenic cards
share one 1000 Genomes placement. Selected-outcome study populations and
matched, mismatched, declined, not-run and unknown states appear on the face
and detail. Variant confidence uses the weighted comparison while retaining
rarity/quality limits and the existing unknown cap; PRS transfer ceilings remain
specific to PRS. Format 18 validates frozen evidence/context and preserves older
snapshots. All 2,995 unique checks pass with five existing Windows skips;
strict four-way types, lint/format, fixtures, full card lint and privacy gates pass.
See [the contract and evidence audit](docs/card_ancestry.md).
The [M9.13 diff review](docs/review_m913_session.md) hardens frozen fit, allele
and numeric validation and preserves damaged-run errors in card detail. All
3,015 tests pass with five existing Windows skips; types, lint, card lint and
fixtures pass. The
[next-step handoff](docs/handoff.md#next-open-step-m101-pharmacogenomics-ingestion)
records M10.1's original source-ingestion entry contract.

**M10.1 pharmacogenomics ingestion is complete:** all supplied CPIC allele definitions,
functions and phenotype relationships, plus all ClinPGx annotation tables, are ingested
and checksum-bound. SQL is read without execution; COPY and INSERT dumps agree.
`genetics pgx prepare` joins source HGVS assembly mappings to verified dbSNP GRCh37
keys; `genetics pgx inspect` exposes frozen definitions, functions, phenotype mappings,
licences and explicit gaps offline. All 1,354 definitions and 112,820 diplotype rows
are retained. Normalization remains partial and VKORC1 has no source phenotype table.
The archive-specific licence audit corrects ClinPGx's non-commercial terms and records
the CPIC database-policy scope for review. See [PGx ingestion](docs/pgx_ingestion.md)
and the [M10.2 handoff](docs/handoff.md#next-open-step-m102-snp-tractable-diplotype-calling).
**M10.2 sample calling is implemented:** `genetics run` evaluates the eight
SNP-tractable genes and freezes complete candidate evidence in bundle format 19.
`genetics pgx calls RUN --gene CYP2C19 --json` and the dashboard inspect the same
saved calls offline. Phase, ploidy, missing/unresolved constraints, phenotype gaps,
and rare/imputed reliability remain visible. DPYD uses source activity-score
joins; G6PD keeps native copy counts; VKORC1's missing phenotype table is explicit.
An absent prepared reference saves an unavailable stage; a damaged one fails.
Formats 1–18 remain readable and M9.13 confidence arithmetic is unchanged.
See [the calling contract](docs/pgx_calling.md).
**M10.3 CYP2D6 placement is complete:** the existing saved assay-limit card
stays beside calls on the dashboard, PGx overview and every gene detail,
including filtered views and unavailable references. CLI inspection carries
the same saved evidence; historical/nonstandard packs report absent card
evidence explicitly. See [the placement contract](docs/pgx_calling.md#m103-cyp2d6-placement).
Review validation covers 3,219 unique passing tests with five existing Windows skips,
including the native-tool setup recheck; four strict type targets,
full card lint, fixtures, style and privacy checks pass.
The [M10.3 diff review](docs/review_m103_session.md) fixes incomplete saved-text
reporting and replaces ignored filter inputs with actual hide-and-retain checks.
**M10.4 guideline-linked cards are implemented:** eight declarative selectors
preserve every conditional CPIC recommendation branch, exact source joins,
multi-gene requirements, population/clinical context and separate evidence labels.
Bundle format 20 reproduces the cards from frozen sample schema 1 offline.
Complete-source synthetic save/reload and all authored citation bindings pass;
VKORC1's absent recommendation keys remain explicit. Validation covers 3,267
unique passing checks, five existing Windows skips, four strict type targets,
full card lint, fixtures, style and privacy checks. See the
[contract and source audit](docs/pgx_guidelines.md).
The [M10.4 diff review](docs/review_m104_session.md) hardens frozen numeric
validation and incomplete-source evidence handling. New guideline cards use
display schema 2; schema-1 cards retain their original rules and text. Review
validation passes the complete native suite: 3,292 tests, five existing Windows
skips, with four strict type targets, full card lint, fixtures and style passing.
**M10.5 section framing is complete:** one shared prescribing-tool notice appears
once on each PGx section/view and CLI report. JSON labels it as current context;
saved findings, historical runs and guideline display schemas 1–2 are preserved.
See [the framing contract](docs/pgx_framing.md). The
[M10.5 diff review](docs/review_m105_session.md) closes a reproduced CLI
saved-summary test gap; production code and saved formats are unchanged.
**M11.2 HLA imputation is implemented.** It validates an explicitly selected, opt-in
HIBAG HLARES hg19 classifier, proves marker strand from dbSNP and 1000 Genomes allele
sets (99.8% of model markers on the real references), and stores frozen
per-locus calls, posterior probability, marker coverage and provenance in bundle format
21. Unavailable and no-prediction states never imply absence of an allele. See [the
classifier-imputation contract](docs/hla_imputation.md). CI now installs R and HIBAG,
and native prediction through synthetic classifiers passes on Windows and Linux.
Prediction through all four published classifiers passes locally on Windows. That test
runs only where the classifiers are fetched, because CI never downloads references.
[M11.3 HLA ancestry
selection and confidence](docs/handoff.md#next-open-step-m113-hla-ancestry-selection-and-confidence)
is next.
The [M10.2 diff review](docs/review_m102_session.md) binds saved PGx observations
to native dosage evidence, tightens malformed-input validation and fixes error
categories, allele uncertainty labels and reliability styling. See the
[M10.3 handoff](docs/handoff.md#next-open-step-m103-cyp2d6-placement).
The [M10.1 diff review](docs/review_m101_session.md) fixes null guideline citation
joins, safe atomic publication and parsing/frozen-reference validation, and updates
the next-step contract. Complete source tables and verified mapping counts are unchanged.
Final review validation passes **3,137 native tests**, with five existing Windows
skips; four strict type targets, full card lint, fixtures, style and privacy gates pass.
The [M9.12 diff review](docs/review_m912_session.md) adds guards against
reversed variant claims and wrong effect units, with all 102 focused card tests
passing. The [M9.13 handoff](docs/handoff.md#next-open-step-m913-card-level-ancestry-match)
records the ancestry context, confidence decisions and saved-run requirements.
The [M9.11 diff review](docs/review_m911_session.md) confirms the model evidence
and pins and strengthens directed-phenotype bindings on the face and after
reload. All 62 card tests and six retained native card bindings pass; no
production card or engine correction was needed.
The subsequent [M8 overview review](docs/review_m8_overview.md) fixes saved rarity and
provenance validation/error paths and expands the [M9.1 handoff](docs/handoff.md).
It adds 30 cases; the final native suite passes **2,591 tests, five existing Windows
skips**, with strict four-way types, lint/format, fixture reproduction and full card lint.
M7.2 is accepted against the complete 17,209,972-record gnomAD index. The 63.15 GB
download passed its publisher checksum; source/index verification and a synthetic
offline run through the CLI and dashboard passed. Download resumability debt is resolved:
explicitly immutable releases can resume verified prefixes; rolling sources restart.
**M9.1 is implemented:** public PGS format-2 scoring-file parsing, authoritative per-score
metadata terms, source-bound metadata processing and offline `genetics pgs inspect --json`.
The first live public score parses 77 rows; missing/unknown/ambiguous licences cannot
establish permission. See [PGS ingestion](docs/pgs_ingestion.md).
The full native suite passes **2,660 tests, five existing Windows skips**, with strict
four-way types, lint/format, fixtures and full card lint; 69 new synthetic cases cover M9.1.
**M9.2 computes original/post-imputation PLINK sums:** `genetics pgs score` uses shared
ancestry-first/default-on imputation or full saved dosages, preserving native effect doses,
allele quality and private provenance. Explicit `--no-impute` is recorded; saved-only
original sums remain unavailable. Results default outside the checkout as private,
immutable `.pgs-score.json` files. Coverage, percentiles and calibration remain M9.3–M9.6.
See [PGS scoring](docs/pgs_scoring.md).
M9.2 acceptance passes **2,707 tests, five existing Windows skips**, including native
arithmetic and cache-independent saved/CLI scoring, with all four strict type targets,
lint/format, fixtures and full card lint. Forty-seven new cases cover this step.
**M9.3 reports per-score variant coverage** before and after imputation in every private
score result, with separate row/variant/position denominators and null (not 0%) for
unavailable phases; `genetics pgs coverage` revalidates it. See
[PGS coverage](docs/pgs_coverage.md).
**M9.4 places each score against 1000 Genomes** within the person's placed
super-population (pooled and labelled unmatched otherwise), over the same rows and
the same PLINK matrix; `genetics pgs placement` revalidates it. See
[PGS reference](docs/pgs_reference.md). The [M9.3–M9.4 review](docs/review_m94_session.md)
verifies the public panel before personal input.
**M9.5 states each score's ancestry portability:** the placed 1000 Genomes population maps
through a cited category chain (Morales et al. 2018 Table 1, then the PGS Catalog's display
categories) to the share of the score's study population demonstrably in the sample's
category, which becomes `ancestry_match`. A decline by either panel lowers it; unknown stays
unknown; nothing is filtered. `genetics pgs portability` revalidates it. See
[PGS portability](docs/pgs_portability.md).
**M9.6 puts polygenic scores on cards:** `genetics run` scores every `kind: polygenic` card
(knowledge schema 4) and saves the private record in bundle format 17. The card face and
the dashboard show the reference distribution with the person's interval, never a point,
beside coverage, portability, within-family attenuation and absolute rates by decile where
cited. See [PGS cards](docs/pgs_cards.md). The [M9.5–M9.6 review](docs/review_m96_session.md)
fixes three defects; M9.7's entry contract is in the [handoff](docs/handoff.md).
Start with the
[handoff](docs/handoff.md), then the [living roadmap](phase1_roadmap.md).
M8.5 adds 54 synthetic checks for quality propagation, historical compatibility and
native Beagle acceptance. The full local suite retains five existing Windows skips.
M8.6 adds 53 full-snapshot checks; its final native suite passed **2,524 tests**, with
those same five skips, strict four-way typing, privacy gates and full card lint.
The subsequent [diff review](docs/review_m86_session.md) fixes three validation/error
defects and adds five regressions: **2,529 tests passed**, with the same five skips.
The [M8.7 handoff](docs/handoff.md#m87-implementation-handoff) records its completed
acceptance matrix.
The preceding M8.4 suite passed **2,417 tests with five existing Windows skips**,
including native ROH and privacy checks. Strict type checks, ruff/formatting, fixture
reproduction and full dbSNP card lint passed; scoped M7.6 synthetic-only full-reference offline
acceptance verified saved CLI/dashboard parity. Native Beagle acceptance uses one
synthetic target and twenty generated reference samples; CI enables it on Windows/Linux.
New native reference tests cover full conversion, exact round trips, interruption,
checkpoint recovery, corruption refusal and Beagle consumption of the prepared bref3.
M8.3 native acceptance checks independent male/female targets across autosomal and X
jobs, including phase-filled no-calls, multiallelic/indel predictions and verified reuse.
The [session review](docs/review_m8_session.md) records fixes to output identity/region
checks, cleanup, runtime drift, build metadata and reference-catalog validation/recovery.
The M7.5 implementation checkpoint is `537e3c5`, with
[all five CI jobs passed](https://github.com/sovemere/genetics-analysis/actions/runs/37434344709).
The [M7.5 session review](docs/review_m75_session.md) records the preceding fixes;
the [coverage guide](docs/clinvar_coverage.md) describes M7.6's counting and saved contract.

## Development and use

Python 3.11+ is required; Windows is the primary development platform. From a checkout:

```powershell
uv venv --python 3.11
uv pip install -e ".[dev]"
uv run --no-sync genetics install-hooks
uv run --no-sync genetics --help
```

Before pushing, `genetics ci-local` runs the GitHub CI checks in `.github/workflows/ci.yml`
on this machine. It reads the steps from the workflow and runs them in a fresh clone of
what the push would publish, with an empty data directory and cached per-version venvs.
CI uses Java 17; pass `--java-home` if `JAVA_HOME` does not point at it.
`--python 3.13` runs one matrix version instead of all of them. Jobs for other operating
systems (the Linux runners, on Windows) are named but not reproduced. CI also installs R
and HIBAG for the native HLA tests; a local run uses `Rscript` from `PATH` instead, and
says so when it finds no ready HIBAG, since those tests then skip.

Fetch the sources and pinned tools needed for an analysis using `genetics refs` and
`genetics tools`. Downloads can be large; the reference manifest declares sizes and
licenses. Once installed, computation is local. Prefix the following commands with
`uv run --no-sync` when the environment is not activated:

```text
genetics run --input <outside-repo-export>
genetics runs list
genetics runs show <run-id> --json
genetics runs clinvar <run-id> --json
genetics runs secondary <run-id> --json
genetics serve
```

Runs default to the OS user-data directory outside this checkout. Missing structure
prerequisites produce visible `not_run` cards; malformed inputs and wrong tool versions
fail explicitly. Standalone `genetics roh` exposes the same ROH engine with custom
reference and policy options.

Default imputation requires the full prepared panels/maps and pinned Java tools;
[setup](docs/imputation_reference.md) describes installation. Missing imputation
prerequisites fail explicitly. Development/testing can select `--no-impute`, which is
visible in the saved run and cards; it is never selected automatically.

The dashboard links to each run's ClinVar reference lookup. These are reference
annotations; its [ACMG view](docs/secondary_findings.md) retains likely artifacts and
states that only clinical sequencing can establish or exclude a variant. Full lookup
annotations carry explicit match states and a separate frequency reliability screen;
they are not confirmed clinical findings. Missing frequencies stay unknown. Published
PPV benchmarks retain their study scope and are never presented as individual posterior probabilities.

See the [knowledge-pack guide](knowledge/README.md),
[common health-card guide](docs/common_health.md),
[ClinVar coverage](docs/clinvar_coverage.md),
[reference-data guide](data/references/README.md), [ROH](docs/roh.md),
[archaic estimation](docs/archaic.md) and [sex-chromosome reporting](docs/sex_chromosomes.md).
