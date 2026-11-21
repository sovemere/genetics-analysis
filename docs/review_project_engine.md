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
- [x] **A. Pipeline seams** -- ancestry before polygenic scoring (§4.4); which table each stage
  reads (chip or imputed) and whether that is consistent; the imputed flag reaching confidence;
  the frequency lookup covering every locus a stage asks for. `run/pipeline.py`.
- [x] **C. Matching and allele handling** -- sorted genotypes, strand and palindromes, indel
  exclusion (§4.2), no-calls, hemizygous X/Y reaching every consumer, locus key before rsID.
  `ingest/normalize.py`, `ingest/keys.py`, `qc/`, `engine/matcher.py`,
  `engine/multimarker.py`, `external/harmonize.py`.
- [x] **D. Polygenic scores** -- effect allele against dose allele, coverage before and after
  imputation, DR² into confidence, per-score licence, ancestry gating. `pgs/*`,
  `imputation/dosages.py`.
- [x] **E. PGx and HLA assembly** -- CYP2D6 as not callable, unresolved alternatives kept, the
  `*5` hemizygous trap, G6PD on X. `pgx/calling.py`, `pgx/guidelines.py`, `hla/calling.py`,
  `hla/cards.py`.
- [x] **G. Hard rules across the codebase** -- §1: no genotype in a progress line, exception,
  repr or log, and every network call through `outbound.check_url`; §0.1A: nothing drops or
  filters a card on its tier, in the engine or the views; §3/§6: a card without a citation does
  not render, computed cards included.
- [x] **H. Reconcile** -- cross-item findings, the handoff and roadmap status lines, and what
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

### A. Pipeline seams (closed 2026-11-21)

Read: `run/pipeline.py` `analyse` and `observations`, `imputation/observations.py`
`card_input`.

No finding. Ancestry is inferred, then the 1000 Genomes placement is made and written into
the context, before any score or HLA classifier is chosen (§4.4). Card matching reads the
chip table with imputed calls filled in only where the chip has no call at a card locus: any
called probe, including a contradictory or indel one, blocks replacement. ClinVar, the ACMG
screen, ROH, archaic and sex-chromosome cards read the chip table only, which is right for
the first two under §4.1 (imputation does not rescue a rare call) and for ROH, where imputed
homozygosity would be the panel's, not the sample's. The imputed flag is set from one map,
keyed by locus, for both the match markers and the observation's call source, so they cannot
disagree. The frequency lookup is the union of ClinVar loci, every card variant (each marker
of a multi-marker card) and every PGx locus.

### C. Matching and allele handling (closed 2026-11-21)

Read: `engine/matcher.py` (index, match, multi, evaluate, duplicates, orient),
`ingest/normalize.py` (no-call, chromosome remap, pair sort), `qc/metrics.py`
(`resolve_ploidy`), the one chrX interpretation card.

Sorted pairs, `0 0` as null, numeric chromosomes refused unless mapped, indels excluded,
duplicate probes compared on a strand-independent form except at palindromic sites,
positional matching with the rsID only reported: all as AGENTS.md §2 requires.

- **C1, P3, recorded, no change:** a homozygote whose one letter is the complement of a
  declared allele is read as a strand flip (e.g. `CC` at an A/G card reads `GG`). One letter
  cannot tell a flip from a third allele, and the card says so in a computed caveat. On a
  forward-strand export the third-allele reading is the likelier of the two, but both are
  rare and the caveat is on the face. Left as designed.
- **C2, P3, recorded, after M15.1:** under `AMBIGUOUS` sex the X stays diploid-called, so the
  one chrX interpretation card (`ar_rs6152_androgenetic_alopecia`) gets no computed caveat
  that ploidy was unresolved. Its authored caveats cover the doubled-call reading. PGx G6PD
  and polygenic scoring already treat ambiguous X as unresolved.

### D. Polygenic scores (closed 2026-11-21)

Read: `pgs/engine.py` (`_direct`, `orient`, `_imputed`, `score`), `pgs/reference.py`
`_phase`, `pgs/portability.py` `_compute`, the saved-score reuse in `pgs/runner.py`.

No finding. The effect allele is oriented against each source's own alleles, a four-allele
locus is refused, and a palindromic pair is kept only where the observation is
strand-invariant. A hemizygous X call doses 0 or 1 on both the chip and imputed paths. An
original called probe takes precedence over any dose, failures included. The reference
distribution is scored over exactly the person's comparable rows, and that share of weight
is the confidence input. The per-score licence is checked before any personal input is read.

### E. PGx and HLA assembly (closed 2026-11-21)

Read: `pgx/calling.py` (observation, rarity, versioning), the CYP2D6 impossibility card,
`hla/cards.py` `_confidence`, `docs/hla_cards.md`.

No new finding. CYP2D6 is a not-determinable card and `pgx` refuses it by name; G6PD is
modelled at ploidy 1 and 2 when sex is ambiguous. HLA card tiers come from the shared
calculator with the posterior in the quality slot and the locus ceiling applied on top. With
no HLA frequency source every HLA card caps at moderate; `docs/hla_cards.md` already states
this. The `*5` hemizygous trap does not arise: no CYP2D6 call is made.

### G. Hard rules across the codebase (closed 2026-11-21)

Searched all of `src/genetics` outside `testing/`.

No finding. **§1:** no progress line, log call, print or exception message interpolates a
genotype, allele pair, dose or observed call; ingest builds its errors from row numbers and
column names, not rows. Outbound requests are held by the existing `check_url` test, which
passed. **§0.1A:** every `continue` and tier comparison in the engine, readers, CLI and views
was read; none drops a card. The dashboard's tier filter is the reader's own choice, empty by
default. **§3/§6:** `KnowledgePack.load` refuses any card other than an impossibility card
without a citation, and polygenic, HLA, coverage, scope, ROH and archaic cards are all pack
cards, so the rule covers computed cards too.
