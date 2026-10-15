# M11.1 session diff review

Scope: `60b38e7..3a7c32d`, covering optional R/HIBAG readiness, doctor JSON,
subprocess execution, the shared termination helper, ignore rules, tests and
documentation. The review uses synthetic inputs only and does not install R,
HIBAG or classifiers. Bundle format 20 and knowledge schema 5 remain unchanged.

## Findings and fixes

- **P2 — Private path errors escaped on Python 3.11/3.12.**
  `HIBAGRuntime.run_script()` caught `OSError` and `ValueError` around source
  resolution and cache creation, but those supported Python versions report a
  symlink loop as `RuntimeError` containing its path. A synthetic reproduction
  escaped with the private marker in the exception. Both source and cache path
  failures now become categorical public-safe errors, while the bridge's own
  already-safe errors remain intact. The Python-version distinction is documented
  by [Path.resolve](https://docs.python.org/3.13/library/pathlib.html#pathlib.Path.resolve).
- **P2 — The terminal wait could override cancellation or a deadline.**
  `_execute()` checked interruption before waiting, then accepted a zero exit
  immediately. Deterministic reproductions signalled cancellation or advanced
  the clock beyond the deadline during the final wait; both returned success.
  Both conditions are checked again before accepting the exit. Existing child
  termination, keyboard-interruption and native Beagle checks remain required.
  Two additional reproductions showed that a pre-set cancellation event could
  return optional R absence or a missing-script error rather than cancellation.
  The shared cancellation check now also runs at both public entry points,
  before dependency discovery or script/path validation.
- **P2 — A non-regular protocol could block outside the process timeout.**
  `_protocol()` bounded file length and rejected symlinks but did not establish
  that its input was a regular file. A FIFO can report a small size and then
  block on open after the child has already exited. A simulated FIFO reached
  the forbidden open in the original code. The parser now uses `lstat()` and
  rejects every non-regular file before attempting to read it. The reproduction
  mocks file metadata so it runs on Windows without creating a named pipe or
  allowing a test to hang.
- **P2 — Bootstrap bindings leaked into sourced R code.**
  The helper named `identity` and the argument vector `a` were defined in R's
  global environment, which is the parent of the sourced script's environment.
  An unqualified `identity` in a script therefore selected the protocol writer
  rather than `base::identity`. Both bootstrap expressions now run in `local()`;
  the script retains its own environment and normal global/base lookup.
  This is a source-level finding supported by R's
  [sys.source](https://stat.ethz.ch/R-manual/R-devel/library/base/html/sys.source.html)
  and [local](https://stat.ethz.ch/R-manual/R-devel/library/base/html/eval.html)
  semantics. Native verification remains unavailable locally; the native script
  now asserts that `identity` resolves to the base function and that bootstrap
  arguments do not appear in the global environment.

Five focused cases failed against the original implementation before fixes:
the source-path exception, both terminal-wait conditions, the non-regular
protocol and the native acceptance gap below. Two further entry-cancellation
cases failed before their fixes, for seven reproduced failing cases in total.
Cache-path error handling and the documented runtime override have additional
regression coverage. The R scope change is not presented as a locally executed
native reproduction.

## Native acceptance gap

The original single native test passed when R was present but HIBAG was absent,
without ever executing a bridge script. That behavior was reproduced with the
synthetic package-absence subprocess. Native readiness and bridge-script
acceptance are now separate tests: an absent package may pass R readiness, but
the script test explicitly skips. Both honor `GENETICS_RSCRIPT`, with an optional
`GENETICS_HIBAG_TEST_RSCRIPT` override for test-only selection. A synthetic check
verifies that the documented runtime override works even when Rscript is absent
from PATH. Neither test installs dependencies or loads a classifier.

## Handoff audit

**M11.2 remains next:** audit and fetch HIBAG pre-fit classifiers, then implement
validated offline HLA imputation. Start with user-installed native R/HIBAG and
run the two native smoke tests, including the new script-scope assertions.
Separate classifier licensing, build/strand/marker identity and checksums must
be established before adding fetched references. No HIBAG classifier source is
currently declared in the manifest. Record the versioned sample-call and
additive saved-bundle contract before persisting HLA evidence. Validate scientific
outputs independently of process success. Ancestry-matched classifier selection
and confidence integration remain M11.3; linked cards remain M11.4.

## Validation

Combined final review coverage passes **3,344 unique tests**, with **seven skips**.
The broad native-tool run passes **3,342 tests** in **542.74 seconds**; all
**123 final HIBAG/doctor/Beagle checks** pass in **23.87 seconds**, including both
entry-cancellation cases added after broad-suite collection. This is combined
coverage, not a claim that the broad run collected those last two tests.
The seven skips are the five existing Windows OS-network-isolation/POSIX-mode
limitations and the two separately reported native R checks. Rscript remains
unavailable locally; no native R/HIBAG positive-path success is claimed.

All four strict Windows/Linux × Python 3.11/3.13 targets check **217 source files**.
Full dbSNP lint passes **77 cards / 320 template renders / 39 resolved keys**;
fixtures reproduce byte-for-byte. Lint/format, local documentation targets and
whitespace checks pass. Native checks use the pinned tools and portable Java 17,
with private OS temporary output and the previously documented test-process
`POLARS_SKIP_CPU_CHECK=1` workaround. The shared Beagle termination helper,
doctor adapter, reference pins, knowledge entries and saved schemas are unchanged
from the reviewed commit. Staged privacy scanning and the complete enabled
pre-commit hook are required before publication. No personal export, fetched
payload or genotype-derived artifact is included.
