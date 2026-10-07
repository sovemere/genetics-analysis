# genetics-analysis

An offline-capable personal genome interpreter with one analysis engine, a CLI and a
local dashboard. Findings carry evidence, citations and explicit uncertainty. This is
an educational instrument, not a diagnostic.

Read [AGENTS.md](AGENTS.md) before working with data or code. This repository is public:
personal exports, measurements, run bundles and logs must stay outside Git. Tests use
synthetic data; reference payloads are fetched, never committed.

## Current state and handoff

M0–M7 are complete. The current slice includes ingest/QC, cited trait and assay-limit
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
New runs use bundle format **13**; formats 1–12 remain readable without reinterpreting saved findings.

**M8.1 is complete:** the pinned Beagle wrapper checks Java, configures memory,
reports progress and reuses verified completed jobs. Interrupted jobs restart from
their inputs. The [Beagle guide](docs/beagle.md) documents the private checkpoint contract.
Imputation is not yet integrated into `genetics run`.

**M8.2 implements full per-chromosome reference preparation:** pinned bref3
conversion and full decoded verification, resumable chromosome checkpoints, source/tool
provenance and complete GRCh37 genetic maps. See [reference preparation](docs/imputation_reference.md)
for setup, Java 11+ and explicit X/Y/MT scope.

**M8.3 supplies shared phasing then imputation:** `genetics impute` harmonizes the target,
preserves eligible typed calls, partitions X PAR/non-PAR jobs, and writes private per-ALT
dosages/DR2 with explicit biological ploidy, source and missing-quality states. Completed
jobs and observations are verified before reuse. See the [pipeline guide](docs/imputation_pipeline.md).
**Next: M8.4, default-on `genetics run` orchestration and its recorded `--no-impute` mode.**
M7.2 is accepted against the complete 17,209,972-record gnomAD index. The 63.15 GB
download passed its publisher checksum; source/index verification and a synthetic
offline run through the CLI and dashboard passed. Download resumability debt is resolved:
explicitly immutable releases can resume verified prefixes; rolling sources restart.
Start with the
[handoff](docs/handoff.md), then the [living roadmap](phase1_roadmap.md).
The M8.3 suite passed **2,369 tests with five existing Windows skips**,
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
