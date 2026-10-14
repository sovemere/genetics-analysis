# M9.12 session diff review

Reviewed on 2026-10-14: `1c4921e..e894b5d`, covering four fitness variant
cards, the PGS002143 grip card, reference manifest/lock, synthetic tests and
milestone documentation. The implementation leaves the engine, knowledge
schemas 3/4, bundle format 17 and renderer unchanged.

## Findings and corrections

**Variant tests could accept opposite displayed claims or wrong effect units.**
Existing checks bound coordinates, alleles, outcome names, values, sample sizes,
study ancestry and replication. They did not bind the published direction in
the displayed text or the effect measure. A correct outcome name could therefore
accompany an incorrect interpretation.

Five in-memory mutations reversed ACTN3's women's training contrast, ACE's
serum concentration association, COL5A1's injury association and ACSL1's
training contrast, or changed ACTN3's variance measure to an odds ratio.
Every mutation passed the original exact-binding check and all twelve
supported-state checks. The new regression cases failed before the correction
with `DID NOT RAISE AssertionError`. Authored cards were never altered by these
experiments.

Tests now bind published claims for every outcome and the appropriate effect
measure before assembling fabricated observations. Saved CLI summaries and
dashboard section/detail views retain the selected direction; frozen evidence
retains the measure. All five mutations are rejected by the published-claim
guard and remain regressions. Shipped directions and units were correct;
no production card correction was needed.

**The handoff retained stale next-step wording.** Its accepted M9.11 review
paragraph still called M9.12 next. It now records M9.12's completion and
M9.13 as the next step. README, roadmap, fitness audit and handoff link this
review. The audit's ambiguous description of ACSL1's P value now explicitly
says it does not meet genome-wide significance.

## Evidence, sources and retained acceptance

[Clarkson 2005](https://pubmed.ncbi.nlm.nih.gov/15718405/) confirms ACTN3's
women-only training association, approximate omnibus variance and male null
result. [Schuler 2017](https://pmc.ncbi.nlm.nih.gov/articles/PMC5523633/)
confirms ACE's group ordering and adjusted R-squared 0.466 in 92 twins.
Concentration remains separate from I/D state and performance; German
recruitment is not converted into a study ancestry claim.

[September 2009](https://doi.org/10.1136/bjsm.2008.048793) supplies COL5A1's
Australian OR 0.42 and interval, distinct from the combined study N.
[Kim 2017](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0170422)
does not confirm rs12722 for its broader endpoint. Its Results report 5,148
cases; the differing number in the Discussion is not substituted. Comparator
outcomes keep null evidence and no invented absolute risk. The existing
[ACSL1 audit](fitness_physiology.md#variant-evidence-and-limits) retains the
exploratory single-locus estimate, failed replication and distinct
multivariable estimate.

The pinned author [preparation code](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/code/prepare-pheno-fields.R)
and [phenotype counts](https://github.com/privefl/UKBB-PGS/blob/14159aed82b430ad165376eaf707ebdce0db06b1/phenotype-info.csv)
confirm mean left/right grip, exclusion of missing hands and means below
1 kg, and training N=388,700. The
[version-2 release](https://doi.org/10.6084/m9.figshare.14074760.v2), file
31619354, confirms the United Kingdom evaluation row: N=19,855,
partial-r 0.2620 (0.2490–0.2749). Squaring these positive values gives the
authored residual-variance estimate and interval. No personal kilogram
conversion, direct effect or absolute outcome calibration is added.

The complete harmonized payload matches the manifest SHA-256 and byte size;
authoritative per-score metadata remains permissive. Both retained native
card snapshots match the current model/source, directed trait, entire evidence
payload and citation identities. Acceptance and disk-read reports remain
passed. Score records and checkpoints are unchanged.

## Validation and next step

- All **102 focused card tests pass** in 46.85 seconds. The five mutation
  regressions pass again after the final type annotation in 0.83 seconds.
- All four strict type targets pass for **201 files**. Full dbSNP card lint
  passes **69 cards, 320 renders and 39/39 keys**; Ruff and whitespace checks pass.
- Required fixture reproduction, staged privacy scanning and privacy tests
  run through the pre-commit hook before publication.
- The implementation's **2,923 unique passed checks**, five existing Windows
  skips and full-model native acceptance remain historical results. This
  review adds five cases and does not claim a new full-suite, full-record
  native validation or scoring run. No new browser visual review is claimed
  for the unchanged renderer.

No other substantive issue was found in the diff. Genetic values, scores,
coverage and private hashes remain outside Git and out of chat; private
validation emits operational pass/fail results only.

**M9.13 is next:** establish a shared run-level 1000 Genomes context for
card-level study-ancestry matching, resolve evidence-specific confidence
policy and populate `{ancestry}` with explicit matched, mismatched, declined,
not-run and unknown states. Selected-outcome null evidence and historical
bundles must stay intact. The [handoff](handoff.md#next-open-step-m913-card-level-ancestry-match)
names current code entry points and acceptance requirements.
