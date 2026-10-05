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
ambiguity states and provenance. New runs use bundle format **7**; formats 1–6 remain
readable without reinterpreting their saved findings. Frequency gating and imputation
are upcoming milestones.

**Next: M7.2, gnomAD frequency gating.** Download resumability debt is resolved:
explicitly immutable releases can resume verified prefixes; rolling sources restart.
Start with the
[handoff](docs/handoff.md), then the [living roadmap](phase1_roadmap.md).
The M7.1/download checkpoint passed 1,949 tests with five existing Windows skips,
including native ROH checks; the final ClinVar/web regression suite passed 245 tests.
The preceding reviewed checkpoint is `1c1c2ec`, with
[all five CI jobs passed](https://github.com/sovemere/genetics-analysis/actions/runs/37191147216).

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
annotations with explicit match states, not calibrated clinical findings; M7.2–M7.3
add the frequency-based reliability and empirical PPV presentation.

See the [knowledge-pack guide](knowledge/README.md),
[reference-data guide](data/references/README.md), [ROH](docs/roh.md),
[archaic estimation](docs/archaic.md) and [sex-chromosome reporting](docs/sex_chromosomes.md).
