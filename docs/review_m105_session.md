# M10.5 session diff review

Scope: `3b58d18..955487e`, covering the shared PGx current-context adapter,
CLI, shell model, notice template, placement, synthetic checks and handoff.
No personal export is opened. Production code and saved formats are unchanged.

## Findings and verification

No production defect was found in the reviewed diff. The shared notice is
current context outside frozen calls/cards, appears before the saved CYP2D6
limitation, and survives section/tier grouping, filters, candidate pagination,
unavailable sources and historical runs. Individual card details remain free
of the section notice. Guideline display schemas 1–2 retain their saved rules.

One test gap was reproduced: appending current framing to each frozen CLI
guideline summary still passed all four existing saved-guideline interface
cases. They compared computations but did not bind the complete CLI card
projection to the independently loaded saved card, or check the text report's
notice count when guideline cards were present.

The same four cases now compare card ID, summary, computation and citations
exactly, assert one notice in text output beside the saved summary, and verify
that raw bundle JSON has no current-context field. Both display schemas and
completed/unavailable stages are covered. The unmodified code passes; the
same summary-contamination mutation fails all four cases. Three additional
reversible mutations (omitted dashboard notice, duplicated overview/gene
notice and context falsely labelled recorded) each fail the existing matrix.
All mutations were restored; no test fixture or runtime behavior changed.

## Handoff audit

M11.1 remains next: optional R/HIBAG readiness and the subprocess bridge.
The existing `doctor.py::_check_r` already discovers `Rscript`, probes its
version and prints a HIBAG success sentinel. It does not implement the bridge
or report HIBAG's package version. A stubbed HIBAG probe timeout currently
returns `missing` with “R is installed but the HIBAG package is not”, discarding
the probe error. This is pre-existing M11.1 work, not a regression in M10.5.

The updated handoff requires shared readiness with doctor, separate missing
runtime/package and failed-probe states, exact runtime/package identification,
startup isolation and bounded private subprocess handling. Classifier fetching,
imputation, ancestry selection and HLA findings remain M11.2 onward. No runtime
or package is installed during this review.

## Validation

Review validation is scoped to the changed tests and their PGx, web and doctor
consumers; the preceding M10.5 combined native acceptance remains recorded in
[the framing contract](pgx_framing.md#validation). No second full native-suite
run is claimed. The unmodified runtime passes all four targeted cases with
the strengthened assertions; four mutation scenarios are rejected. Server-rendered HTTP checks
cover placement; no interactive browser visual review is claimed.

All **516 affected PGx/web/doctor tests** pass in **119.13 seconds**. The
final four cases, expanded to both complete and gene-specific CLI reports,
pass in **3.92 seconds**; the summary-contamination mutation still fails all
four. Four strict Windows/Linux × Python 3.11/3.13 targets check 214 files.
Full dbSNP lint passes **77 cards / 320 renders / 39 keys**; fixture
reproduction, lint/format, local documentation links and whitespace checks
pass. Production files compare byte-for-byte with the reviewed commit.
Staged privacy scanning and the enabled pre-commit privacy suite are required
before publication. No personal export, fetched payload or genotype-derived
artifact is included.
