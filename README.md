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
New runs use bundle format **6**; formats 1–5 remain readable without reinterpreting their
saved findings. Monogenic-health lookup and imputation are upcoming milestones.

**Next: M7.1, position-keyed ClinVar lookup.** Start with the
[handoff](docs/handoff.md), then the [living roadmap](phase1_roadmap.md).
The reviewed code checkpoint is `1c1c2ec`: 1,898 tests passed locally with five existing
Windows skips, and [all five CI jobs passed](https://github.com/sovemere/genetics-analysis/actions/runs/37191147216).

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
genetics serve
```

Runs default to the OS user-data directory outside this checkout. Missing structure
prerequisites produce visible `not_run` cards; malformed inputs and wrong tool versions
fail explicitly. Standalone `genetics roh` exposes the same ROH engine with custom
reference and policy options.

See the [knowledge-pack guide](knowledge/README.md),
[reference-data guide](data/references/README.md), [ROH](docs/roh.md),
[archaic estimation](docs/archaic.md) and [sex-chromosome reporting](docs/sex_chromosomes.md).
