# Handoff: M8.7 imputed rare-variant frequency gates

As of 2026-10-07, **M0-M7 and M8.1-M8.6 are implemented**. Full local reference
verification and synthetic/offline acceptance passed. Read [AGENTS.md](../AGENTS.md)
first, then [the roadmap](../phase1_roadmap.md). Next is M8.7.

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
also pass. There are no known blockers for starting M8.7.

**Next M8.7:** add dedicated regressions proving the frequency gate applies to
imputed observations, regardless of high DR2, strong literature or enabled mode.
Cover untyped and phase-filled sources, native haploid/diploid observations, missing
frequency companions and multi-marker inheritance. Show rare findings as likely artifacts;
never filter them. Keep the 16%/BRCA 4.2% chip benchmarks scoped to their studies and
explicitly uncalibrated for imputation, never an imputed-call posterior probability.
Current ClinVar/QC/coverage/structure still use original array input. M9 owns PGS sums,
coverage and ancestry portability; preserve the native effect-allele dose/quality contract.

### M8.7 implementation handoff

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
M8.7 remains incomplete until these checks pass and the roadmap/handoff records the result.

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
