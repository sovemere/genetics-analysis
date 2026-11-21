# Project engine review (before M15.1)

Working file and to-do list. Scope 1 of the four proposed in
[handoff.md](handoff.md#project-review-before-m151): the engine read whole, from ingest to the
saved run, for faults between modules that a per-diff review misses, and AGENTS.md's hard rules
checked across the codebase rather than per diff. Started 2026-11-21 at `7c96208`.

Every input is synthetic or fabricated. No personal export and no saved real run is opened.

## Rules for this review

- **One item at a time**, in the order below. An item is closed when its findings are recorded
  here and its local fixes are committed with tests. Commits are per item; pushes every few
  items, each after `genetics ci-local` and followed by a check of the GitHub run.
- **Fix before M15.1** whatever would make the run wrong: a wrong card or tier, a genotype that
  leaks, a saved part reused when it should not be, a card hidden or uncited. Everything else
  (code health, wording, a slow path) is recorded as **after M15.1** and left.
- **Design decisions are taken here, not deferred**, and each is written down with its reason
  under the finding, so the owner can audit and reverse it.
- **Timebox: about 8 h of reading.** Anything not read in that time is listed under its item
  as unread, never dropped silently.
- Severity: **P1** wrong result, leak or lost card; **P2** a rule held by accident or by one
  caller only; **P3** stale wording, dead code, a test that does not test what it says.

## To-do

- [ ] **B. Confidence** -- one tier model or several; rarity inversion identical for chip and
  imputed calls (§4.1); ceilings compose by minimum; no hand-set numbers (§6); PPV on the face.
  `engine/confidence.py`, `engine/evidence.py`, `health/frequencies.py`, `health/secondary.py`,
  `ancestry/card_match.py`, `pgs/portability.py`, `imputation/quality.py`.
- [ ] **F. Save, read and resume** -- what `analyse` builds equals what `runs card` and the
  dashboard read back; the saved-parts contract names every input that changes a part.
  `run/bundle.py`, `run/store.py`, `run/reads.py`, `run/parts.py`, `run/explain.py`,
  `run/checks.py`.
- [ ] **A. Pipeline seams** -- ancestry before polygenic scoring (§4.4); which table each stage
  reads (chip or imputed) and whether that is consistent; the imputed flag reaching confidence;
  the frequency lookup covering every locus a stage asks for. `run/pipeline.py`.
- [ ] **C. Matching and allele handling** -- sorted genotypes, strand and palindromes, indel
  exclusion (§4.2), no-calls, hemizygous X/Y reaching every consumer, locus key before rsID.
  `ingest/normalize.py`, `ingest/keys.py`, `qc/`, `engine/matcher.py`,
  `engine/multimarker.py`, `external/harmonize.py`.
- [ ] **D. Polygenic scores** -- effect allele against dose allele, coverage before and after
  imputation, DR² into confidence, per-score licence, ancestry gating. `pgs/*`,
  `imputation/dosages.py`.
- [ ] **E. PGx and HLA assembly** -- CYP2D6 as not callable, unresolved alternatives kept, the
  `*5` hemizygous trap, G6PD on X. `pgx/calling.py`, `pgx/guidelines.py`, `hla/calling.py`,
  `hla/cards.py`.
- [ ] **G. Hard rules across the codebase** -- §1: no genotype in a progress line, exception,
  repr or log, and every network call through `outbound.check_url`; §0.1A: nothing drops or
  filters a card on its tier, in the engine or the views; §3/§6: a card without a citation does
  not render, computed cards included.
- [ ] **H. Reconcile** -- cross-item findings, the handoff and roadmap status lines, and what
  M15.1 inherits.

## Findings

(Recorded under each item as it closes.)
