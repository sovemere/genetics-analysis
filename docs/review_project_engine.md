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

- [x] **B. Confidence** -- one tier model or several; rarity inversion identical for chip and
  imputed calls (§4.1); ceilings compose by minimum; no hand-set numbers (§6); PPV on the face.
  `engine/confidence.py`, `engine/evidence.py`, `health/frequencies.py`, `health/secondary.py`,
  `ancestry/card_match.py`, `pgs/portability.py`, `imputation/quality.py`.
- [x] **F. Save, read and resume** -- what `analyse` builds equals what `runs card` and the
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

### B. Confidence (closed 2026-11-21)

Read: `engine/confidence.py`, `engine/evidence.py`, `engine/ppv.py`,
`engine/observation_snapshot.py`, `engine/multimarker.py`, `health/frequencies.py`,
`health/secondary.py` (tier use only), `ancestry/card_match.py`, `pgs/portability.py`,
`imputation/quality.py` (`card_quality`), the PGx rarity block in `pgx/calling.py`, and the
PPV lines of `_cardface.html`.

**The model is one model.** `single_call_ceilings` states the single-call ceilings for both
the calculator and `run/explain.py`; polygenic and HLA confidence reuse `QUALITY_CEILINGS`,
`SHARE_CEILINGS` and `ancestry_ceiling`; every composition takes the weakest. Rarity applies
to chip and imputed calls alike, and the PPV line is on the card face from the confidence
record, not from authored templates. The ClinVar screen and PGx rarity use their own
vocabulary but the same boundary, benchmark and (after B1) the same frequency selection.

- **B1, P1, fixed: the likely-artifact gate could not fire for any allele gnomAD had seen.**
  `select_frequencies` took the maximum frequency across every gnomAD population and
  subgroup. Every r2.1.1 exome group except the NFE parent has fewer than 100,000 alleles
  (largest subgroup `nfe_nwe`, 42,222), and every NFE sample also sits in a subgroup, so one
  copy anywhere read above 0.001%. Measured on an 816,000-SNV sample of the public index
  (no personal data): 62% of seen alleles have global AF below 0.001% and the old rule
  screened **none** of them as rare. The same selector feeds cards, ClinVar and PGx, so the
  §4.1 inversion was inert everywhere except at AC=0 rows.
  **Decision:** a population other than the global pool raises the maximum only when its
  allele number reaches 100,000 (derived: `ceil(1 / 0.00001)`) or it holds every observed
  allele at least twice. One copy records where the one carrier was sampled; two in a small
  group is enrichment, so founder alleles keep the protection the maximum was for. On the
  same sample 86% of globally-rare alleles are now screened rare, and 637 of 21,910 alleles
  at 1% or more change band (all lifted by one copy in a group with a tiny allele number).
  **Saved runs:** the ClinVar screen's saved policy text now names its rule
  (`LEGACY_POLICY` → `all-populations-v1`), so a run saved before this is checked under the
  rule that made it; an unknown policy text is refused. PGx call records move to version 2;
  version 1 is re-derived under the old rule. Card snapshots keep the frequency they
  selected, so they need nothing. Rejected: global AF only (would cost variants common in
  one population, e.g. African-specific alleles, a frequency band they earned) and gnomAD's
  `AF_popmax` (its smallest groups have the same resolution problem).
  Tests: singletons in five groups at their real r2.1.1 allele numbers, a resolving group,
  the legacy rule on both paths, a relabelled policy, and a version-1 PGx record.
- **B2, P3, fixed:** the saved imputed-observation and multi-marker validators restated the
  DR2 bounds (0.30/0.60/0.80) as literals. They now read `QUALITY_CEILINGS`.
- **B3, P3, fixed:** PGx rarity wrote `0.00001` and `0.16` as literals; it now uses
  `RARE_CALL_FREQUENCY_CEILING` and `RARE_CALL_EMPIRICAL_PPV`.
- **B4, recorded, after M15.1: an allele absent from gnomAD exomes is unknown, not rare.**
  It caps at moderate, while a singleton now reaches likely-artifact, so absence is treated
  more gently than one observation. That is the documented "missing is never zero" rule: the
  sites VCF cannot tell absent-at-a-covered-site from not-covered. gnomAD's coverage files
  would settle it. Not changed.
- **B5, recorded, no change:** for a single-variant card a mismatched study ancestry moves only
  the 5%-weighted component; it sets no ceiling (M9.13's stated policy). Polygenic cards are
  capped by it.

### F. Save, read and resume (closed 2026-11-21)

Read: `run/parts.py` whole, `run/pipeline.py` `analyse`, the score-reuse path in
`pgs/runner.py`, the skips and filters in `run/bundle.py`, `run/store.py`, `run/reads.py`,
`web/views.py`, `cli/runs_cmd.py`. Round-trip equality of `analyse` and the readers is held by
the parity and bundle tests, which passed; not re-derived by hand.

**The contract holds for what M15.1 does.** Input digest, engine source digest, pack digest,
reference lock, installed tools and the HLA options key the parts. A new imputation drops
every part read from the old one; saved scores and calls are reused only under the same
ancestry record, which includes the 1000 Genomes placement. Every skip found in the save and
read paths skips a file or directory, never a card; the dashboard's tier filter is opt-in,
empty by default, and drops unknown values rather than obeying them.

- **F1, P3, recorded, after M15.1:** the contract does not name the installed Python
  dependencies or the `GENETICS_BEAGLE_JAR`, `GENETICS_RSCRIPT` and `JAVA_HOME` overrides.
  A reused part keeps its own provenance, so the bundle stays truthful, but a resume across
  such a change mixes tool builds between parts. The run sheet now says to keep them fixed
  between sessions (item H).
