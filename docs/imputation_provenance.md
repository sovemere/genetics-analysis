# Full imputation snapshots (M8.6)

Bundle format **16** stores the complete validated stage dosage output and exact
used provenance. Reopening or scoring a saved run does not require its stage cache,
reference installation, Java runtime or a current reference/tool manifest.

## Private payloads

`imputation.run.json` retains the existing execution-mode/card-input contract.
`imputation.provenance.run.json` schema 1 records one of:

- `recorded`: the full stage checkpoint, including zero-job enabled execution;
- `disabled`: explicit `--no-impute`, with no stage or dosage payloads;
- `not_recorded`: a low-level writer supplied no completed stage.

Normal enabled analysis saves require their completed stage. A missing or changed
checkpoint fails publication; the pipeline never invents provenance or downgrades to
an array-only run. Historical formats **1–15** keep their saved meanings, with full
provenance absent. Existing per-card dosage/quality evidence is not expanded into an
invented full panel for those older runs.

Recorded runs contain independent byte copies of every `*.dosages.jsonl.gz` file,
plus `imputation.panel.catalog.run.json` and `imputation.map.catalog.run.json`.
Catalog copies preserve their original bytes and hashes. They describe the reference
artifacts; the multi-GB panels themselves are not copied into each run. All these
payloads are covered by the bundle integrity manifest and existing privacy ignore rules.

## What is recorded

The private stage checkpoint retains source ids/releases, catalog fingerprints,
the normalized target fingerprint, exact Beagle and bref3/unbref3 versions/hashes,
Java versions/executable hashes, requested parameters, target sex/ploidy policy,
region decisions, limitations and record/source counts.

Each completed region retains both phase and imputation checkpoints: actual panel,
map and target input hashes/sizes; tool/runtime identity; interval, native target
ploidy, seed, threads and heap; output hashes and elapsed time. The phase output
fingerprint must match the second invocation's target input. Unoverridden tool defaults
are tied to the pinned jar identity. This stage record is authoritative for the used
imputation inputs; the manifest's general installed-reference/tool inventory is not a
substitute for it and may differ after local installations change.

Dosages remain on their native 0–ploidy scale, including every ALT and its own DR2.
Phase-filled no-calls retain unknown quality; original direct stage observations retain
exact allele counts. Full dosages describe the panel stage output, not every original
array marker: unsupported chromosomes and excluded original probes remain outside the
stage's direct dosage scope. QC, ClinVar, chip coverage and structure keep their original
array basis. M9 owns score computation and before/after coverage reporting.

## Validation and atomic publication

Save checks the stage against its checkpoint and original target, copies independent
bytes into the bundle's staging directory, verifies digests and validates native dosage
records. Region decisions, retained typed markers, source counts, allele/dosage/quality
cardinality, biological ploidy and phase/imputation options must agree. Every imputed
card or multi-marker observation must match its own allele identity, hard call and quality
in exactly one full dosage record, even when several claims share a locus. Native storage
vectors reject boolean values rather than accepting numeric equality with allele indices
or dosages. Malformed stages fail with a categorical publication error.
Publication uses the existing atomic directory rename; a failed copy leaves no completed
bundle and preserves its source stage. Genotype-free copy/validation progress goes to
CLI stderr, with heartbeat messages during long validation passes.

Read checks only saved bytes. Missing files, invalid gzip/JSON, inconsistent provenance,
rehashed count/model/quality changes, card/full-dosage disagreement and symbolic links
fail explicitly. These are integrity checks, not cryptographic protection against an
owner rewriting a complete record. Listing remains a manifest/presence check by default;
`runs list --verify` performs full validation. Reading full dosages can take time.

## Shared CLI/library/dashboard interface

```text
genetics runs imputation <run-id>
genetics runs imputation <run-id> --json
genetics runs imputation <run-id> --dosages
genetics runs show <run-id> --json
```

`--json` returns saved execution and provenance. `--dosages` streams private JSON Lines;
it deliberately contains genotype-derived observations. Keep redirected output outside
the checkout. `RunBundle.iter_dosages()` exposes the same native records for future score
consumers and checks payload integrity again before streaming. The dashboard banner
shows recording status, panel release and Beagle version from the saved snapshot.
No front end discovers live tools or references while reopening a run.

Synthetic tests cover independent copies, cache removal, installed-inventory differences,
CLI/dashboard parity, damaged/rehashed metadata, dosage/card disagreement, gzip corruption,
interrupted publication, explicit opt-out, zero-job execution, old formats, privacy ignores
and native haploid/multiallelic contracts. Native acceptance saves all 800 generated records
over four jobs and verifies source counts, per-ALT preservation, native haploid quality and
completed-stage reuse. No personal export was used. M8.7 adds dedicated imputed rare-call
frequency-gate regressions.
