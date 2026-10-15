# Optional R/HIBAG runtime (M11.1)

M11.1 supplies dependency readiness and an offline subprocess bridge only.
Classifier ingestion/imputation belongs to M11.2 and ancestry selection to M11.3.
A successful probe or script execution establishes no HLA call. Bundle format 20,
knowledge schema 5 and all saved evidence remain unchanged. A versioned HLA
sample/bundle contract must be recorded before M11.2 writes sample evidence.

The bridge and doctor share one readiness function. It distinguishes missing R,
missing HIBAG, a failed probe and a ready runtime, retaining numeric R/HIBAG
versions and the R platform. An installed package whose namespace cannot load is
a probe failure, retaining its installed version. Structured protocol version 1 is strict
and bounded; unrecognized or inconsistent output cannot establish readiness.
Protocol inputs must be regular files; special files and symlinks are rejected
before reading, so a FIFO cannot bypass the subprocess timeout.

R is user-installed. Discovery uses `GENETICS_RSCRIPT`, then `Rscript` on PATH;
an invalid explicit override is an error. Nothing installs R, packages or models.
Every invocation uses `--vanilla`, controlled default packages and a private
working directory. Startup profiles/workspaces are not loaded; configured
`R_LIBS*` paths remain available so a user's installed HIBAG can be found.
Bootstrap bindings stay in a local R environment and cannot shadow base functions
or leak into a sourced script's parent environment.

Run `genetics doctor --json` to inspect readiness. Its R entry includes
`runtime_status`, `runtime_failure`, `r_version`, `hibag_version` and `r_platform`.
Missing dependencies are optional; probe failures set `has_problem` and exit 1.
If Rscript is outside PATH, set `GENETICS_RSCRIPT` to its executable path.
If the package library is normally configured in `.Renviron`, put that location
in the `R_LIBS_USER` environment variable instead; startup files are isolated.

| Runtime status | Meaning | Failure category |
|---|---|---|
| `r-missing` | Rscript was not found | none |
| `hibag-missing` | No discoverable HIBAG package | none |
| `probe-error` | Readiness could not be established | configuration, execution, timeout, protocol or namespace |
| `ready` | Namespace loaded and versions validated | none |

Jobs receive script arguments as a vector, never shell/R string interpolation.
The bridge returns a validated process-completion record with runtime identities
and private output paths. It does not interpret a caller's scientific output;
M11.2 must validate its own versioned output before constructing HLA evidence.
`HIBAGRuntime.discover()` consumes that same probe. Its `run_script()` method
sources trusted local R code into an environment containing `bridge_args`, a
character vector. Both before sourcing and at completion, the R/HIBAG versions
and platform must equal the discovered identity. Script outputs and console
logs remain in the returned private directory; no completed attempt is reused.
Timeouts and cancellation stop the child process (including its Windows tree).
Both are checked again after the terminal wait before accepting process success.
An already-cancelled request raises cancellation at public entry, even when R
or the requested script is absent.
Raw stdout/stderr, job paths, script arguments and subprocess errors never enter
public exceptions or doctor output. This includes Python 3.11/3.12 path-resolution
`RuntimeError` failures. Attempts live under the existing external private cache,
with an ignored `.hibag-work` suffix as a second defense against accidental copies.

Primary API references: [Rscript](https://stat.ethz.ch/R-manual/R-devel/library/utils/html/Rscript.html),
[namespace loading](https://stat.ethz.ch/R-manual/R-devel/library/base/html/ns-load.html),
and [R version identity](https://stat.ethz.ch/R-manual/R-devel/library/base/html/Version.html).
In particular, `requireNamespace()` returning false can mean a load failure;
presence and loadability must be checked separately. The
[package-location API](https://stat.ethz.ch/R-manual/R-devel/library/base/html/find.package.html)
returns a vector, including an empty vector for absence; the probe checks its
length before testing namespace loading. Namespace startup output is redirected
to private stderr, separate from the strict runtime protocol.

## Implementation validation (2026-10-16)

Combined final coverage passes **3,335 unique tests**, with **six skips**. The
broad native run passes 3,331 tests in 530.06 seconds; all 114 final bridge,
doctor and Beagle checks pass in 23.05 seconds, including four argument/source
cases added after broad-suite collection. After the final R bootstrap source
review, all 61 bridge/doctor tests pass in 6.65 seconds. The new native-R test
is skipped because Rscript is unavailable; the other five skips are existing
Windows OS-network-isolation and POSIX-permission limitations. The native
Beagle acceptance uses the pinned tools and portable Java 17.

Four strict Windows/Linux × Python 3.11/3.13 targets pass across 217 source
files. Full dbSNP card lint passes 77 cards, 320 template renders and all 39
marker keys. Synthetic fixtures reproduce byte-for-byte; lint/format, local
documentation targets and whitespace checks pass. The sandbox's known Polars
CPU-probe incompatibility uses `POLARS_SKIP_CPU_CHECK=1` only in test processes.
Process-tree tests run with normal Windows process access and private temporary
outputs. An initial test-launch error omitted the temporary directory's parent;
the corrected broad run above passes completely.

Synthetic subprocess tests cover ready/missing/broken packages, execution errors,
timeout, cancellation and keyboard interruption, malformed/inconsistent protocol,
runtime changes, argument preservation, startup isolation, private errors and
representations, shared doctor JSON and ignored attempt copies. Actual local
discovery reports `r-missing`; standalone probing no longer imports the Beagle
reference-processing stack. No native R/HIBAG positive-path success is claimed.
No R/package/classifier installation, personal export or new HLA sample evidence
is involved.

## Diff review (2026-10-16)

The [session diff review](review_m111_session.md) fixes private path error handling,
terminal-wait interruption, special-file protocol handling and R bootstrap scope.
It also separates native R readiness from native HIBAG script execution and honors
the documented runtime override. Seven cases were reproduced failing before fixes;
native R scope validation remains unexecuted locally.

Final reviewed coverage passes **3,344 unique tests**, with **seven skips**:
3,342 broad native-tool passes in 542.74 seconds, then all 123 final affected
checks in 23.87 seconds, including two later entry-cancellation cases. Four
strict type targets (217 source files), full card lint, fixtures and style pass.
The [review record](review_m111_session.md#validation) states the exact combined
scope and preserves the original implementation acceptance above.

Native acceptance now has two explicit checks:
`test_native_r_readiness_protocol` and `test_native_hibag_script`. Both skip if
Rscript is unavailable; with R installed but HIBAG absent, readiness can pass
while script execution explicitly skips. Set `GENETICS_RSCRIPT` to the user-installed
executable (or use `GENETICS_HIBAG_TEST_RSCRIPT` for test-only selection). The script
checks argument preservation and normal base-function lookup without any classifier
or personal input. M11.2 must run both checks on a ready native installation before
claiming native HLA imputation acceptance.
