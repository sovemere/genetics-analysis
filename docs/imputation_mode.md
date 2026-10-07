# Default-on analysis imputation (M8.4)

`genetics run --input <export>` now runs ancestry, then the shared full-panel
[phasing/imputation stage](imputation_pipeline.md), before assembling findings.
References, genetic maps, Java and pinned tools must already be installed. Missing or
damaged prerequisites fail the run with an `imputation` error; no bundle is saved and
the pipeline never silently switches to direct-overlap analysis. Ancestry remains first.

```text
genetics run --input <outside-repo-export> --json
genetics run --input <synthetic-export> --no-impute --json
```

`--no-impute` explicitly skips reference/tool discovery and the imputation stage. It is
intended for development/testing and is always recorded as `disabled`. The Python
entry point is `analyse(..., no_impute=True)`; its default is `False`, and truthy
non-booleans are refused. CLI progress remains genotype-free on stderr; JSON stdout
is one document and contains the execution record.

## What findings consume

M8.4 snapshots use original array observations. M8.5 introduces quality-aware card
matching for absent/no-call biallelic SNVs, with original direct calls preserved.
ClinVar lookup, array coverage, ROH, archaic and sex-chromosome modules continue to
consume the original array table. Execution mode is separate from observation source.
See [quality propagation](imputation_quality.md) for the per-ALT/native-ploidy contract
and explicit unknown-quality confidence ceiling.

The library keeps the complete `ImputationResult` on `Analysis.imputation_result` for
quality-aware matching and future scoring. Explicit opt-out sets it to `None`. The independent `genetics impute`
command uses the same stage and remains available for direct inspection.

## Saved execution contract

Bundle **format 14** added the private `imputation.run.json` payload (schema 1), containing
requested mode, execution status, original-array card-input basis and a validated stage
summary. Every card records its run's `enabled` or `disabled` mode separately from
`observation.call_source`. Reader/writer checks require agreement with the run, including
multi-marker observations. Source counts, region counts, typed/no-call retention counts,
job counts, ploidy and execution status must agree arithmetically. No low-quality record
or finding is filtered.

An enabled stage with no usable region jobs records `enabled` / `no_eligible_jobs`,
with explicit region reasons. This is different from opting out. Low-level bundle
writers without an execution context record `not_recorded`, with null card modes;
they do not invent an opt-out or a successful stage. Formats **1–13** preserve their
saved meanings and expose null execution/mode as “not recorded.” Saved reads use only
the bundle, even after its cache or current references disappear.

Format **15** adds native dosage evidence and schema 2's `original_array_with_imputed`
card-input basis for enabled quality-aware execution. Format-14/schema-1 snapshots
retain their original-array meaning. Disabled and unrecorded execution retain schema 1.
The CLI `runs show --json`, human summary, dashboard banner, card face and detail read
the same saved record. The mode and recorded observation basis are visible before opening a
card. No topic confirmation gate is added.

This payload records execution mode/outcome. Full used-panel/tool/parameter provenance
and durable dosage inclusion belong to M8.6. Existing schema-1 job contracts already
retain those exact identities privately in the outside-repo cache. `*.run.json` and its
knowledge-pack re-ignore already cover the new payload; in-repo output remains refused.

## Native acceptance and Windows launch paths

Offline acceptance generates a twenty-sample, two-chromosome reference from fixed-seed
frequencies and a synthetic male export with enough X/Y observations for QC inference.
The default CLI produces 800 dosage records across autosomal, PAR and non-PAR jobs,
saves format 14, then reuses its completed jobs. No personal export or real reference
individual is used. The shared synthetic preparation helper also serves M8.3 tests.

That acceptance exposed Windows error 267 when the nested default-cache subprocess
working directory reached 265 UTF-16 characters. The wrapper now selects a shorter
ancestor for launch when needed. Inputs/output paths remain absolute and unchanged,
so complete contracts and job reuse remain stable. Native acceptance covers launch,
output validation, save and reuse with the deep cache path; this is not an imputation
accuracy benchmark.
