# M10.5 pharmacogenomics section framing

Implemented 2026-10-16. The shared current context lives in
`pgx/presentation.py::section_framing`. Its wording is:

> This is not a prescribing tool. Array-derived calls and conditional CPIC
> guidance are educational evidence; they do not establish a clinical phenotype
> or select a medicine or dose. Prescribing based on these findings requires
> clinical confirmation and the person's full clinical context.

The dashboard presents this notice before the saved CYP2D6 limitation and
sample calls, once in the pharmacogenomics section. Grouping by reliability
or filtering knowledge cards retains one notice beside the independent sample
calls. The PGx overview and each gene page use the same template and wording,
including every candidate page. The notice uses the existing accessible,
visually distinct notice style. It is not repeated in individual card details,
gene rows, candidates or guideline summaries.

`genetics pgx calls RUN`, with or without `--gene`, prints the same wording
once before the saved report. Its JSON exposes
`current_context.section_framing`, whose `context: current` and
`section: pharmacogenomics` identify presentation context separately from
frozen `guideline_cards`, sample calls and saved CYP2D6 evidence.
`genetics runs show RUN --json` remains the frozen bundle inspection interface.

The notice does not require a completed PGx stage or a particular knowledge
pack. Completed, unavailable-reference and historical runs receive the same
current context; missing saved calls/cards remain explicitly absent. No
current interpretation is written into a historical run. Bundle format 20,
knowledge schema 5, source/sample schema 1, guideline display schemas 1–2 and
confidence calculations are unchanged. Existing conditional, measurement,
phase, population and clinical-context evidence remains beside each finding.
No output file type, source download, citation or fixture is added.

## Validation

The synthetic interface matrix checks all eight genes, candidate pagination,
section/tier grouping and supported filters, saved/missing CYP2D6 cards, and
completed/unavailable/historical stages. It asserts exact-once shared wording,
CLI JSON separation and byte-identical bundles after inspection. Guideline
save/reload and corruption checks now exercise both display schemas and retain
exact saved summaries, computations, citations and missing-source states.
All ten focused cases pass offline. Server-rendered HTTP checks verify placement;
no interactive browser visual review is claimed.

Native validation uses the pinned PLINK/Beagle tools and portable Java 17.
The sandbox needs `POLARS_SKIP_CPU_CHECK=1` for its CPU-probe incompatibility;
this is a test-process setting, not a project dependency or application change.
Test output stays in an OS temporary directory outside the checkout.

Final combined validation covers **3,294 unique passing tests**, with five
existing Windows skips. The broad native run passed 3,274 tests in 595.28
seconds; its twenty failures were sandbox cache-write, process-tree termination
and platform-detection restrictions. All **101 checks** in the three affected
files pass with normal Windows process access and a private temporary cache
in **35.23 seconds**, including all twenty failures. This is combined coverage,
not a second complete-suite run. The final shared wording also passes all ten
focused interface cases in 9.79 seconds. All four strict Windows/Linux ×
Python 3.11/3.13 type targets check 214 files. Full dbSNP card lint passes
77 cards / 320 template renders / 39 resolved keys. Fixtures, lint/format,
local documentation links, whitespace and staged privacy scanning pass.
No personal export was opened or genotype-derived artifact staged.

## Diff review, 2026-10-16

The [session diff review](review_m105_session.md) finds no production defect
and strengthens the saved-guideline CLI checks after reproducing a test gap.
The complete CLI card projection must equal the loaded saved evidence, the
text report must contain one section notice even with guideline cards, and
raw bundle JSON must remain free of current-context metadata. All four
reversible mutation scenarios are rejected. Runtime code, saved schemas,
source pins and the original combined native acceptance remain unchanged.
M11.1's handoff now records the existing HIBAG probe's timeout/absence
conflation and missing package-version reporting.
Review validation passes **516 affected tests**, the four final CLI cases,
four strict type targets, full dbSNP card lint, fixtures and style checks.
See the review for exact scope; the broad native run was not repeated.
