# Beagle subprocess jobs (M8.1)

M8.1 implements the Beagle wrapper, Java/readiness checks and verified job reuse.
`genetics impute` now performs shared-stage phasing/imputation in M8.3; see the
[pipeline guide](imputation_pipeline.md). `genetics run` integration and its recorded
escape hatch are delivered in M8.4; see [the mode guide](imputation_mode.md).
Quality propagation is delivered in M8.5; [the quality guide](imputation_quality.md)
describes its native allele contract. Full used provenance remains M8.6. New bundles
use format 15; private job checkpoints retain schema 1.

## Installation and execution

Install Java 8 or later, then run `genetics tools install --only beagle` and
`genetics doctor`. The existing manifest pins Beagle 5.5 / `27Feb25.75f` by SHA256.
The wrapper and doctor check that exact jar; they do not choose whichever file has
the newest timestamp. `GENETICS_BEAGLE_JAR` may relocate that same pinned jar, but
cannot select a different build. Java uses an explicit executable when supplied,
otherwise `JAVA_HOME/bin/java`, otherwise PATH; an invalid configured home fails.

Call the shared wrapper from Python with already prepared, allele-aligned inputs:

```python
from pathlib import Path
from genetics.external.beagle import Beagle, BeagleOptions

inputs = Path.home() / "genetics-inputs"
result = Beagle.discover().run(
    gt=inputs / "target.chr1.vcf.gz",
    ref=inputs / "reference.chr1.bref3",
    genetic_map=inputs / "genetic_map.chr1.map",
    options=BeagleOptions(memory_mb=8192, nthreads=4, chrom="1"),
    progress=print,
)
# result.vcf, result.log and result.checkpoint are local private artifacts.
```

Imputation is **on by default**, and requires a reference. A genetic map is required
so the wrapper cannot silently substitute a constant recombination rate. Default
heap is 8192 MiB, seed is -99999 and thread count is explicitly 1. Callers can set
memory and threads; the fixed thread default makes results reproducible across host
CPU counts. Beagle's accuracy-related algorithm defaults are retained. No run timeout
is imposed unless requested. JVM option-injection environment variables are removed
so inherited settings cannot override the recorded heap or load unrecorded JVM agents.

`target_ploidy=2` is the wrapper's default output contract. A native haploid job uses
`target_ploidy=1` and a target VCF containing single-index GTs; the wrapper verifies the
same copy count during publication and reuse. M8.3 selects this contract per X region.
The option validates representation; Beagle infers ploidy from the target VCF itself.

`BeagleOptions(impute=False)` explicitly suppresses untyped reference markers; it
does not prevent Beagle from filling sporadic missing calls during phasing. This is
a wrapper option, distinct from the application's recorded `--no-impute` mode. The preparation
of correct builds, allele order, chromosome/PAR splits and ploidy remains M8.2/M8.3's
responsibility. The wrapper does not invent that missing preparation.

## Progress, cancellation and completion

The subprocess receives a list of arguments, never a shell command. A reader thread
drains output while the caller receives fixed stage messages, window numbers and
periodic running heartbeats. Marker coordinates, identifiers, sample names, paths,
raw arguments and error text are not forwarded. JVM/Beagle output goes to private
`console.log`; failures provide categorical messages and exit codes. Heap failures
identify the memory setting to increase. Timeout, keyboard interruption and callback
failure terminate and reap the child before releasing the job lock.

One invocation is one restart unit; use stable chromosome job prefixes in M8.3.
An interrupted invocation **restarts from its inputs**, without splicing partial
Beagle windows or VCFs. Completed chromosome jobs can be reused. The kernel releases
the lock after process death, so a stale PID file cannot block later recovery.

By default jobs live under the OS user-data cache outside the repository, keyed by
their complete contract. A supplied `out` is a stable job prefix; its workspace is
`<out>.beagle-work`. In-repo output requires explicit `allow_in_repo=True` and remains
ignored, including inside the knowledge-pack allowlist. Failed attempts are retained
privately for inspection and do not become completed results.

Before launch, the wrapper privately reads the target's unique sample header. After
success, it validates gzip integrity, phased nonmissing GTs, exact target sample order,
and any requested chromosome/position bounds. Reuse repeats these checks, including
when an output and its recorded digest are both changed. It verifies inputs, jar and
Java executable stayed unchanged, hashes the VCF and tool
log, writes/fsyncs `beagle.run.json`, then publishes the whole completed directory in
one rename. The checkpoint binds full input hashes, exact jar identity, observed Java
version/executable hash, memory, threads, seed and mode. Reuse verifies that contract
and every recorded output; changed or damaged completed jobs are refused instead of
overwritten. Checkpoints, fingerprints, VCFs and logs are genotype-derived private
outputs and must never be committed or pasted into remote prompts.

Windows process-tree termination falls back to direct termination/reaping if the
`taskkill` command is unavailable or times out. The M8.3 stage additionally validates
eligible typed-marker retention, dosage/DR2 fields and biological ploidy; structural
VCF validation alone does not establish those scientific contracts.

## Verification

Subprocess tests cover tool discovery, arguments with spaces, progress privacy,
failures, input drift, truncated output, concurrency, hard process death, cancellation,
restart, changed identities and corrupted checkpoints. The native acceptance generates
haplotypes from invented frequencies with seed 8101: twenty reference samples and one
target, 200 reference markers and 100 typed target markers. It checks phased output,
100 newly imputed markers with DR2/dosage fields, explicit phase-only behavior, and
verified reuse. No real reference individuals or personal export are used. CI installs
the pinned jar and Java 17 and enables this same native test on Windows and Linux.
This verifies execution and recovery mechanics; full-panel imputation accuracy and
confidence calibration remain later milestones.

Parameter and file semantics come from the [Beagle 5.5 manual](https://faculty.washington.edu/browning/beagle/beagle_5.5_17Dec24.pdf)
and [pinned release page](https://faculty.washington.edu/browning/beagle/beagle.html).
