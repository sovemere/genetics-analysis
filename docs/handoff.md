# Handoff: M7.5 common-variant health cards

As of 2026-10-05, M0-M6 and **M7.1-M7.4 are complete**. Full local reference
verification and synthetic/offline acceptance passed. Read [AGENTS.md](../AGENTS.md)
first, then [the roadmap](../phase1_roadmap.md). Next is M7.5.

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

M7.3 puts the published confirmed/unconfirmed percentages on the face and in CLI
summaries. Exact `GENEINFO` symbol/NCBI-ID pairs plus germline pathogenic/likely-pathogenic
`CLNSIG` select the BRCA benchmark; mixed, uncertain, conflicting, somatic and
included-haplotype annotations do not. Missing frequency or unresolved observations
still receive no numerical PPV. Imputation-quality failures without a benchmark say so.

New bundles use **format 10**, with ClinVar lookup schema **4** in the existing private
`clinvar.run.json`. CLI JSON and the dashboard read the same saved records. Formats
1-9 retain their original results and notices, including schema-2 BRCA entries with
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

## Next: M7.5

M7.5 owns common-variant health cards
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

The full suite passed **2,064 tests, five existing Windows skips**, with pinned native
ROH enabled. Ruff/formatting, strict mypy on Windows/Linux and Python 3.11/3.13,
fixture reproduction and full card lint pass (47 cards, 218 renders, 31 dbSNP keys).
M7.3 adds 31 synthetic cases for exact BRCA/classification scope, numerical face/detail
and CLI presentation, unavailable PPV, placeholder contexts and historical schema-2
save/read/CLI/dashboard compatibility. Tests also cover rare thresholds/counts/populations, missing/filtered/split/duplicate
records, direct/imputed gating, malformed headers, checkpoint recovery/corruption,
saved integrity, format-7 compatibility, CLI/dashboard parity and citation privacy.
M7.4 adds 42 synthetic cases for exact gene membership, annotation/reportability
separation, source completeness/checksum refusal, unsuppressed ambiguity and reliability
states, missing-source/empty-screen honesty, saved metadata integrity, format-9
compatibility and CLI/dashboard parity with 101-locus pagination.

Before committing, inspect `git status --porcelain`, stage only code/docs/reference
metadata, run `genetics check-staged`, and keep the privacy hook enabled. Public
references, indexes, personal outputs and temporary synthetic bundles stay uncommitted.
