# M7 session diff review — 2026-10-05

Reviewed implementation range **`1a0eadb..4d537f0`**: the M7.1 ClinVar lookup and
download-resume change, M7.2 frequency calibration, M7.3 benchmark presentation, and
M7.4 ACMG surfacing. The review follows the changed code and its callers, readers,
templates, tests and documentation; it is not a new source-license audit or clinical
validation of a personal genome.

Findings fixed in the review follow-up:

| Priority | Finding and trigger | Fix and verification |
|---|---|---|
| P2 | A reference sidecar with a list/null `provenance` reached `.get()` and raised an uncaught `AttributeError`. The same unchecked shape existed in both new index readers; ClinVar also accepted malformed record-count/schema metadata until a later stage. | Validate mapping shape before use, and require ClinVar's complete provenance keys, positive integer record count and integer schema generation. Nine synthetic malformed-cache regressions cover both readers. |
| P2 | An empty saved ALT list in calibrated ClinVar schemas 2–4 reached `ALT[0]` before base validation and raised an uncaught `IndexError`. This bypassed the domain errors handled by bundle readers, CLI and dashboard. | Validate the list before calibration. Three regressions check snapshot validation, digest-consistent malformed bundles, structured CLI failure and a dashboard explanation rather than a server error. |
| P3 | The dedicated ACMG page also displayed full-ClinVar frequency totals without naming their scope; its browser title still said ClinVar. | Label totals as all ClinVar reference overlaps and give the ACMG route its own title. Existing shared-view/pagination tests assert both labels. |
| P3 | ROH, archaic and knowledge-pack guides still claimed current format 9; the sex-chromosome guide did not distinguish introduction in format 6 from current format 10. README linked the preceding checkpoint, and M7.5 handoff omitted the single-marker/APOE constraint. | Align current-format claims, checkpoint/CI links and reference-guide placement; preserve historical milestone descriptions. Expand the M7.5 handoff with declarative matching, absolute-risk sourcing, phase ambiguity and verification requirements. |

The session's privacy boundaries remain intact: indexes contain complete public
references; sample coordinates are queried through memory-only temporary tables on
read-only SQLite connections; personal snapshots stay in private run bundles. The
staged diff contains no reference payload or personal data, and no ignore rule was
weakened. Synthetic fixtures reproduce unchanged.

The download review checked pinned versus rolling/explicitly immutable behavior,
prefix integrity, full-length promotion, changed release/size refusal and partial
cleanup. The focused synthetic suite includes the existing resumability regressions.
Frequency review checked exact allele matching, conservative population/subgroup
selection, split-locus REF uncertainty, missing versus measured zero, and the rarity
gate. Benchmark review checked BRCA/germline scope, unavailable PPV and study versus
personal probability. No additional actionable defect was found in these paths.

Valid historical schemas retain their recorded calculations. The follow-up changes
error handling and presentation, not a finding's interpretation; no new bundle format
is needed. ACMG reportability remains explicitly unadjudicated, and gene membership
does not become a clinical positive or negative screen.

Validation: focused health/download/dashboard suite **411 passed**; full synthetic/
offline suite **2,076 passed, five existing Windows skips**, with native ROH enabled.
Strict mypy passed for Windows/Linux and Python 3.11/3.13 (153 files); ruff/format,
fixture reproduction and full card lint passed (47 cards, 218 renders, 31 dbSNP keys).
The final privacy hook and pushed-commit CI remain required for this follow-up.

M7.5 is ready to start from [the handoff](handoff.md#next-m75). APOE's two-marker
support is implementation work within M7.5; it is not already supplied by the current
single-marker card schema. No further external prerequisite was found by this review.
