# genetics-analysis

An offline-capable personal genome interpreter with one analysis engine, a JSON CLI, and a
local web dashboard. Every finding carries its supporting genotypes, effect sizes,
citations, and an explicit confidence tier on its face. **This is an educational instrument,
not a clinical diagnostic.**

## Privacy warning

**Never commit genotype-derived data to Git or send it over the network.**

- Raw DNA exports, parsed tables, PCA coordinates, polygenic scores, run bundles, and logs
  that echo genotypes must stay outside this repository.
- By default, `genetics` writes runs and caches to the OS user-data directory
  (`%LOCALAPPDATA%\genetics-analysis` on Windows; `$XDG_DATA_HOME/genetics-analysis` on
  Linux) and refuses any data directory that resolves inside the checkout.
- Reference datasets are fetched on demand and never vendored; all tests use synthetic
  fixtures generated from public allele frequencies.
- When researching a finding online, search the *variant* (`rs17822931`, ABCC11, earwax),
  never your genotype or card outcome. Use `genetics cards check-query` before any outbound
  search.

Read [AGENTS.md](AGENTS.md) before working with data or code.

## What it covers

All thirteen sections in [AGENTS.md §3.1](AGENTS.md) are built on one engine and shared by
the dashboard and CLI:

- **Ancestry** — PCA placement against 1000 Genomes, ancient-DNA affinity, and coarse Y/MT
  haplogroups
- **Physical health** — ClinVar lookup, ACMG SF v3.3 secondary-finding gene overlaps,
  monogenic cards (APOE, HFE, Factor V Leiden), and polygenic scores
- **Mental health**, **Psychometrics**, **Substance use & behavioural propensity**,
  **Sleep & circadian**, and **Fitness & physiology** — cited variant and polygenic cards
  with coverage, ancestry portability, and within-family attenuation stated explicitly
- **Pharmacogenomics** — CPIC/ClinPGx diplotype calling for SNP-tractable genes (CYP2C19,
  CYP2C9, VKORC1, SLCO1B1, TPMT, DPYD, NUDT15, G6PD) with CYP2D6 rendered as an explicit
  "not callable from this data" card
- **Traits, morphology & sensory** — high-confidence common variants (eye shade, earwax,
  hair curl, bitter taste, cilantro, asparagus anosmia, photic sneeze, and more)
- **Nutrition & metabolism** — lactase persistence, caffeine, alcohol flush, folate, vitamin
  D, vitamin B12, and the MTHFR calibration cards
- **Immunogenetics (HLA)** — optional HIBAG imputation from MHC SNPs unlocking celiac,
  type 1 diabetes, ankylosing spondylitis, narcolepsy, and HLA drug-hypersensitivity cards
- **Reproductive & carrier status** — cited carrier markers with an explicit screening-scope
  card showing what an array leaves out, plus reproductive-trait polygenic scores
- **Genome structure** — long autosomal runs of homozygosity (PLINK 1.9), archaic
  allele-sharing ranges, and sex-chromosome call patterns

**Calibration and assay limits.** Low-confidence findings are flagged, never hidden. Rare
SNP-chip calls (`AF < 0.001%`) are downgraded to `likely-artifact` with published
sequencing-confirmation benchmarks (Weedon et al. 2021: ~16% overall, ~4.2% for BRCA1/2) on
the card face. What a consumer genotype array cannot determine (methylation/epigenetic age,
somatic variants, copy-number/structural variants including SMN1/CYP2D6/RHD, Y-STRs, mtDNA
heteroplasmy, de novo mutations, relative matching, telomere length) renders as explicit
assay-limit cards inside each section.

## Setup

Python 3.11+ is required (Windows is the primary development platform; Linux is also
tested in CI). From a checkout:

```powershell
uv venv --python 3.11
uv pip install -e ".[dev]"
uv run --no-sync genetics install-hooks
uv run --no-sync genetics doctor
```

External runtimes used by analysis stages:

- **Pinned genomics tools** (PLINK 2, PLINK 1.9, Beagle 5.x, bref3, unbref3): installed via
  `genetics tools install`.
- **Java 17** (`JAVA_HOME`): required by Beagle and the pinned bref3/unbref3 tools (Java 8
  is refused).
- **R + HIBAG** (optional): required only if you opt in to HLA imputation
  (`--hla-model-opt-in`).

## Fetch references and tools

Download the reference databases and pinned tools once (online); after that, analysis runs
completely offline:

```powershell
genetics tools install
genetics refs status
genetics refs fetch
```

Reference downloads are large (for example, gnomAD r2.1.1 exomes is ~63 GB; gnomAD genomes
is optional). Exact sizes, checksums, and licence terms are declared in
[data/references/manifest.yaml](data/references/manifest.yaml) and pinned in
`data/references/manifest.lock`. Sources whose licences require explicit acceptance (such as
PharmGKB/CPIC or the optional HIBAG classifiers) are gated behind opt-in flags. See
[data/references/README.md](data/references/README.md) and
[docs/imputation_reference.md](docs/imputation_reference.md) for preparation details.

## Run an analysis

Point `genetics run` at a raw DNA export stored outside the checkout (AncestryDNA V2.0 and
23andMe-like layouts are supported out of the box):

```powershell
genetics run --input C:\path\to\export.txt
```

- **Imputation is on by default.** Pass `--hla-model-opt-in` to include HIBAG HLA calling.
  `--no-impute` is available for development/testing and is recorded on the run and cards.
- **Resumable by design.** Long stages (imputation, the imputed dose read, each polygenic
  score, PGx, and HLA) are saved as private parts outside the checkout as they finish.
  Re-running the same command resumes from the last saved part; `--restart` discards saved
  parts to start fresh. Parts are removed automatically once the bundle is written.
- **Measured resource profile** (M15.1 on a real 677k AncestryDNA V2.0 export, 21 polygenic
  scores, HLA opted in, offline; see [docs/handoff.md](docs/handoff.md#m151-record)):
  - **Wall-clock:** ~6 h 12 min of unique stages when reusing verified cached Beagle jobs
    (add ~1.5–2 h for cold Beagle imputation; 7 h 55.9 min across three resumed sessions).
  - **Peak memory:** 14.55 GB process-tree peak (`python.exe` 14.54 GB, `plink2.exe` 1.46 GB,
    `rscript.exe` 0.23 GB).
  - **Disk:** 2.27 GB saved run bundle, 11.2 GB cache, 0.23 GB pinned tools.
  - **Reopening a saved run:** seconds once saved (deep checks run at save time; they repeat
    once, ~1 hour, after engine source changes or under `genetics runs list --verify`).

## Explore results (Dashboard & CLI)

Start the local dashboard (bound to loopback `127.0.0.1` only):

```powershell
genetics serve
```

On Windows, `scripts\windows\build_launcher.ps1` builds a local `GeneticsDashboard.exe`
(gitignored) plus a `GeneticsDashboard (verify first).lnk` shortcut that runs
`genetics runs list --verify` before launching the browser.

Everything rendered in the dashboard is also available as versioned JSON from the CLI
(verified by automated CLI/dashboard parity tests):

```text
genetics runs list
genetics runs show <run-id> --section nutrition --json
genetics runs card <run-id> <card-id> --json
genetics runs qc <run-id> --json
genetics runs search <run-id> curly hair --json
genetics runs ancestry <run-id> --json
genetics runs clinvar <run-id> --json
genetics runs secondary <run-id> --json
genetics runs imputation <run-id> --json
genetics pgx calls <run-id> --json
genetics hla calls <run-id> --json
genetics cards evidence <card-id> --json
genetics cards search curly hair --json
genetics cards guide --json
genetics cards check-query <query> --card <card-id>
genetics schema
```

For the step-by-step agent review workflow, see [docs/agent_usage.md](docs/agent_usage.md),
[docs/agent_cli.md](docs/agent_cli.md), and [docs/agent_schema.md](docs/agent_schema.md).

## Development and verification

```powershell
uv run --no-sync pytest -q -n auto
uv run --no-sync genetics ci-local --java-home <path-to-java-17>
```

`-n auto` runs the full suite across worker processes (~3 minutes on 16 cores).
`genetics ci-local` runs the `.github/workflows/ci.yml` steps in a fresh clone with an empty
data directory.

## Documentation

- [AGENTS.md](AGENTS.md) — privacy rules, editorial stance, architecture, and confirmed
  roadblocks
- [phase1_roadmap.md](phase1_roadmap.md) — v1 release checklist and risk register
- [docs/handoff.md](docs/handoff.md) — current state, M15.1/M15.2 records, and post-v1 items
- [docs/progress_log.md](docs/progress_log.md) — dated record of every milestone and review
- [docs/handoff_history.md](docs/handoff_history.md) and
  [docs/roadmap_history.md](docs/roadmap_history.md) — archived M0–M14 history
- Guides: [knowledge/README.md](knowledge/README.md),
  [data/references/README.md](data/references/README.md),
  [docs/common_health.md](docs/common_health.md),
  [docs/clinvar_coverage.md](docs/clinvar_coverage.md),
  [docs/secondary_findings.md](docs/secondary_findings.md),
  [docs/pgx_calling.md](docs/pgx_calling.md),
  [docs/hla_imputation.md](docs/hla_imputation.md),
  [docs/carrier_status.md](docs/carrier_status.md),
  [docs/roh.md](docs/roh.md), [docs/archaic.md](docs/archaic.md),
  [docs/sex_chromosomes.md](docs/sex_chromosomes.md)

## Licence

MIT — see [LICENSE](LICENSE). External reference datasets and tools remain under their own
upstream licences as recorded in [data/references/manifest.yaml](data/references/manifest.yaml)
and [data/tools.yaml](data/tools.yaml).
