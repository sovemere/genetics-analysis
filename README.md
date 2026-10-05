# genetics-analysis

An offline-capable personal genome interpreter with one analysis engine, a CLI and a
local dashboard. Findings carry evidence, citations and explicit uncertainty. This is
an educational instrument, not a diagnostic.

Read [AGENTS.md](AGENTS.md) before working with data or code. This repository is public:
personal exports, measurements, run bundles and logs must stay outside Git. Tests use
synthetic data; reference payloads are fetched, never committed.

## Current state and handoff

M0–M6 are complete. The current slice includes ingest/QC, cited trait and assay-limit
cards, ancestry, long ROH, archaic allele-sharing ranges and sex-chromosome call patterns.
M7.1 adds ClinVar position/allele lookup with preserved source classifications,
ambiguity states and provenance. M7.2 supplies allele-specific gnomAD frequencies to
confidence and a separate ClinVar measurement-reliability screen. M7.3 presents scoped
confirmation benchmarks on the card face and in CLI output, including pathogenic BRCA
annotations. New runs use bundle format **9**; formats 1–8 remain readable without
reinterpreting saved findings.
Imputation remains an upcoming milestone.

**Next: M7.4, ACMG secondary-finding surfacing.**
M7.2 is accepted against the complete 17,209,972-record gnomAD index. The 63.15 GB
download passed its publisher checksum; source/index verification and a synthetic
offline run through the CLI and dashboard passed. Download resumability debt is resolved:
explicitly immutable releases can resume verified prefixes; rolling sources restart.
Start with the
[handoff](docs/handoff.md), then the [living roadmap](phase1_roadmap.md).
The M7.3 implementation passed 2,022 tests with five existing Windows skips,
including native ROH and privacy checks.
The preceding verified checkpoint is `d5c6a9f`, with
[all five CI jobs passed](https://github.com/sovemere/genetics-analysis/actions/runs/37263728402).

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
genetics serve
```

Runs default to the OS user-data directory outside this checkout. Missing structure
prerequisites produce visible `not_run` cards; malformed inputs and wrong tool versions
fail explicitly. Standalone `genetics roh` exposes the same ROH engine with custom
reference and policy options.

The dashboard links to each run's ClinVar reference lookup. These are reference
annotations with explicit match states and a separate frequency reliability screen,
not clinical findings. Missing frequencies stay unknown. Published PPV benchmarks
retain their study scope and are never presented as individual posterior probabilities.

See the [knowledge-pack guide](knowledge/README.md),
[reference-data guide](data/references/README.md), [ROH](docs/roh.md),
[archaic estimation](docs/archaic.md) and [sex-chromosome reporting](docs/sex_chromosomes.md).
