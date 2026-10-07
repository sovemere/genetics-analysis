# Handoff: M8.2 full reference-panel preparation

As of 2026-10-07, **M0-M7 and M8.1 are complete**. Full local reference
verification and synthetic/offline acceptance passed. Read [AGENTS.md](../AGENTS.md)
first, then [the roadmap](../phase1_roadmap.md). Next is M8.2.

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

**Next: M8.2**, prepare the full 1000 Genomes reference by chromosome as bref3.
The existing Beagle jar is not the bref3 converter: add a separately pinned, fetched
converter tool and GRCh37 genetic-map source as needed. Keep complete panels separate
from the ancestry/ROH marker subsets, record source/transform/checksum provenance and
make preprocessing resumable. M8.3 owns sample harmonization and pipeline jobs; M8.5
owns per-variant quality propagation; M8.6 owns run-bundle provenance. M8.1 changes no
existing bundle format or `genetics run` imputation behavior.

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

**M8.1 is implemented.** Next prepare the full per-chromosome reference
panel as bref3 (never subset it to array positions), phase/impute, retain dosages and
per-variant quality, and save panel/tool/parameter provenance. Imputation must be
default-on; `--no-impute` is an explicit, recorded escape hatch. Rare-call reliability
must remain frequency-gated after imputation. M8.2–M8.7 remain upcoming.

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

New bundles use **format 13**, with ClinVar lookup schema **5** in the existing private
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
