# Phasing and imputation stage (M8.3)

The shared `genetics.imputation.impute` engine aligns the normalized consumer table to
the full prepared GRCh37 reference, phases eligible observations, then imputes untyped
reference variants. `genetics impute` calls this engine and prints an execution summary.
It writes private observations and quality beside resumable chromosome/region jobs.

```powershell
genetics impute --input <export> --memory-mb 8192 --threads 1 --json
```

Install the pinned Beagle/bref3 tools, Java 11+, and the full prepared
[panels/maps](imputation_reference.md) first. Default catalogs must match the current
manifest and lock. Missing or damaged references/tools fail explicitly. Custom prepared
catalogs can be supplied together with `--panel-catalog` and `--map-catalog`; their full
companion/provenance validation still applies. There is no constant-rate map or
direct-overlap scoring fallback.

The default output is under the OS user-data cache, outside the repository. `--out`
selects a stable private job prefix; actual files live in `<prefix>.imputation-work`.
The library alone permits explicit `allow_in_repo=True`; every new output type and the
whole workspace remain ignored, including inside the knowledge-pack allowlist.
Neither output, checkpoints, fingerprints nor diagnostics may be committed or sent
to a remote model. The CLI prints counts/statuses; private records are read locally.

## Target observations and chromosome scope

Reference allele definitions are streamed from the prepared bref3 with the pinned
decoder. The full decoded sample/marker/allele/GT summary is compared with its prepared
identity; only requested marker definitions remain in memory. Original source VCFs
are not read. Both Beagle invocations receive the original full chromosome panel;
there is no array, LD, MAF or sample subset.

The target keys on chromosome/GRCh37 position and reference alleles. It reuses the
existing SNP, strand ambiguity and complement rules. Array I/D calls are excluded;
conflicting duplicate probes and duplicate reference positions are declined explicitly.
No-calls at usable reference positions enter as missing GT. Every distinct array
position receives a decision, with counts on each region report. Predictions at an
excluded array position remain imputed observations and never replace its original call.

Autosomes have diploid jobs. X is partitioned into PAR1, PAR2 and the three remaining
intervals using the shared inclusive GRCh37 boundaries. PAR jobs use their separate
maps and diploid biological ploidy. Non-PAR ploidy follows QC's inferred sex; ambiguous
ploidy is reported and those intervals are not inferred. Male heterozygous non-PAR
observations remain explicit ploidy conflicts. Intervals with fewer than two eligible
called anchors have an `insufficient_typed_calls` state, rather than a completed job.
Y, MT and vendor-labelled PAR have no supported reference/coordinate contract; their
original calls remain available to the existing direct-call engines.

The full reference remains in Beagle's required diploid representation, including its
explicitly doubled haploid reference calls. Consumer male non-PAR targets instead use
Beagle's native haploid mode: one allele index per called GT and `.` for a no-call.
Both invocations must emit exactly one allele per marker, dosages on a 0-1 scale and
quality with the `beagle_haploid_dosage` scope. Diploid target regions use a 0-2 scale
and `beagle_diploid_dosage`. Wrong-copy-count outputs are refused. No halving of a
diploid-model dosage or quality reinterpretation is used. This mode is confirmed in the
pinned source's `ImputedVcfWriter`/`ImputedRecBuilder` and in native acceptance.

## Observation and quality files

`complete/<region>.dosages.jsonl.gz` is a streaming, schema-1 private record format.
Each record contains chromosome/position, REF and ordered ALT alleles, biological and
native storage genotypes, per-ALT biological and native storage dosage, per-ALT DR2 when estimated,
ploidy, source, status, original array outcome, dosage method and quality scope.

Three sources remain distinct:

- `direct`: the original eligible call. Dosage is its observed ALT count. Phasing can
  change allele order but must preserve the unordered original call exactly.
- `imputed_no_call`: a missing array observation filled during phasing. Its dosage is
  labelled `phased_hardcall_only`; quality remains unknown. The second invocation sees
  this as typed, so any DR2 it emits cannot price the first invocation's uncertainty.
- `imputed_untyped`: a newly predicted reference variant. It requires finite per-ALT DS
  and DR2 with matching allele cardinality. Low DR2 values are preserved without a filter.

Multiallelic and sequence-resolved indel predictions retain every ALT and its dosage/
quality. They are not matched to unresolved array I/D codes. Direct allele counts do
not assert that a rare chip call is reliable; M8.5-M8.7 must still apply the existing
frequency gate and distinguish measurement confidence from an exact observed count.

Validation checks exact sample identity, interval bounds, allele indices and target ploidy,
marker ordering/uniqueness, every eligible typed marker, unchanged typed calls across
both stages, unchanged phase-filled calls in the second stage, dosage orientation,
finite ranges/cardinality, dosage sums and imputed-source flags. The pinned writer rounds
each ALT dosage independently to hundredths, so the sum check permits at most 0.005
per ALT rounding error and preserves the printed values exactly. A structurally valid
VCF alone cannot complete this stage.

## Recovery and milestone boundary

The private contract binds the entire normalized target, QC sex, full reference/map
catalog identities, pinned tools/runtime and memory/threads/seed. Kernel locks prevent
concurrent writers. Interrupted Beagle jobs restart from their inputs; completed jobs
are verified and reused. All region dosages and metadata publish atomically in a
`complete` directory only after output, reference and tool-drift checks pass.
Completed-stage reuse also regenerates observations from the validated Beagle outputs
and compares them with the saved metadata/files. Damaged outputs or changed contracts
are refused; partial Beagle windows are never spliced.

M8.3 provides the callable stage and independent CLI. M8.4 now calls it by default from
`genetics run`, with an explicit recorded `--no-impute` mode and format-14 execution
snapshots. See [the mode guide](imputation_mode.md). Current findings retain original
array observations. M8.5 owns imputed-card/score quality propagation, M8.6 full bundle
provenance and M8.7 imputed rare-variant gate regressions. All front ends use this stage.

Native offline acceptance generates a full two-chromosome, twenty-sample reference
from fixed-seed frequencies and independent male/female targets. Each target produces
800 records across one autosomal and three X region jobs, including untyped indels and
multiallelic sites, four phase-filled no-calls and 400 newly imputed markers. It verifies
typed retention, biological dosage scale, finite DR2, unchanged full panels and completed
reuse. Synthetic tests additionally exercise corruption, interruption, contract/tool
drift, unusable regions, privacy and CLI/shared-summary parity. This establishes the
execution/data contract, not population-level imputation accuracy.

Parameter and output semantics follow the
[Beagle 5.5 manual](https://faculty.washington.edu/browning/beagle/beagle_5.5_17Dec24.pdf)
and [pinned 27Feb25.75f source archive](https://faculty.washington.edu/browning/beagle/beagle.250227.zip).
