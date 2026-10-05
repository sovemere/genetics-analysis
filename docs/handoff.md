# Handoff: M7.3 empirical PPV presentation

As of 2026-10-05, M0-M6, M7.1 and **M7.2 are complete**. Full local reference
verification and synthetic/offline acceptance passed. Read [AGENTS.md](../AGENTS.md)
first, then [the roadmap](../phase1_roadmap.md). Next is M7.3.

## Current local acceptance

The required `gnomad_exomes_r2_1_1_grch37` download is complete. The payload is
63,145,056,967 bytes, publisher MD5 `f034173bf6e57fbb5e8ce680e95134f2`.
Source SHA256: `b5218277d30c0747cfef38bbc8ee4f735ba8b31695fd343cf9f31ff77cfaf9f3`.
The complete `build_gnomad_frequency_index` transform parsed **17,209,972 public
records**. The index is 23,837,532,160 bytes, schema generation 2, SHA256
`1c8a5a4e4cd31de06a9fb7a05f0db255ceff4d1380af6069d3aba17cfeb8caf7`.
`refs verify` rechecked the source and index successfully, with no pending steps or
temporary build files. A synthetic-only run against the complete ClinVar and gnomAD
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

New bundles use **format 8**, with ClinVar lookup schema **2** in the existing private
`clinvar.run.json`. CLI JSON and the dashboard read the same saved records. Formats
1-7 retain their original results and notices. See [the frequency guide](health_frequencies.md).

M7.1's complete pinned ClinVar index contains **4,461,445 records** from 2026-08-04.
All INFO classifications/conflicts/review status and ambiguity states remain intact.

## Next: M7.3

Complete `likely-artifact` frequency-band PPV presentation, especially the separate
BRCA1/BRCA2 benchmark. M7.4 owns ACMG surfacing, M7.5 common-variant health cards
with absolute-risk framing, and M7.6 coverage honesty. All low-confidence findings
remain visible. Study-to-sample ancestry calibration remains M9.5; source-license
audit remains M15.4. M6's missing chip/population calibration stays attached.

## Download contract

Publisher-checksummed sources resume and verify their final digest. Digestless frozen
sources require an explicit immutable flag, fixed size and matching URL/size/prefix-hash
sidecar. Changed or damaged provenance restarts; rolling files restart. The 24 frozen
1000 Genomes chromosome files declare immutability. None of this permits weakening
privacy, pinning or the pre-commit checks.

## Validation

The full suite passed **1,991 tests, five existing Windows skips**, with pinned native
ROH enabled. Ruff/formatting, strict mypy on Windows/Linux and Python 3.11/3.13,
fixture reproduction and full card lint pass (47 cards, 218 renders, 31 dbSNP keys).
Tests cover rare thresholds/counts/populations, missing/filtered/split/duplicate
records, direct/imputed gating, malformed headers, checkpoint recovery/corruption,
saved integrity, format-7 compatibility, CLI/dashboard parity and citation privacy.

Before committing, inspect `git status --porcelain`, stage only code/docs/reference
metadata, run `genetics check-staged`, and keep the privacy hook enabled. Public
references, indexes, personal outputs and temporary synthetic bundles stay uncommitted.
