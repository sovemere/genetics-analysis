# M15.5 calibration review: the half that needs no real file

Started and closed 2026-11-23, before M15.1, at the owner's request. M15.5 asks whether each
card's stated confidence matches its evidence, that a rare pathogenic call renders as
`likely-artifact` with its PPV, and that no code path filters cards by confidence. The part
that reads the engine, the knowledge pack and public reference data is done here, where a
fix costs M15.1 nothing; sampling a real run's cards across tiers waits for M15.1's bundle.

Every input was the committed pack, public reference data (gnomAD r2.1.1 exomes, 1000 Genomes
phase 3) and synthetic data. No personal export and no saved real run was opened. The rules
are [scope 1's](review_project_engine.md#rules-for-this-review): a wrong tier is fixed before
M15.1, design decisions are taken here and written down with their reasons.

**Method.** Every interpretation card's loci were looked up in the gnomAD index, and each
card's authored evidence was put through `calculate_confidence` with the best observation it
could have (a direct, common call with a full ancestry match) and with the observation as the
pipeline actually priced it. The resulting tiers were set against the reading guide's own
definition of each tier (`genetics cards guide`).

## Findings

### C1, P1, fixed: 21 of 64 interpretation cards could never rise above moderate

gnomAD's r2.1.1 **exomes** are the only frequency source, and a card whose locus they do not
hold gets no frequency, which caps it at `moderate` ("no population allele frequency was
available, so rarity could not be checked"). Most trait loci are non-coding. Measured: 14 of
the 29 trait cards and 5 of the 10 nutrition cards were unpriced, among them HERC2 eye shade,
MCM6 lactase persistence, IRF4 freckling and KITLG blond hair, which their evidence puts at
`well-established`. AGENTS.md 3.1 calls this section the most reliable in the app; the run
was showing it at `moderate` for want of a number, not for any doubt about the call. The
limitation was known for ClinVar loci ([health_frequencies.md](health_frequencies.md)); its
effect on the cards was not.

**Fix:** [`health/panel_frequencies.py`](../src/genetics/health/panel_frequencies.py). Where
gnomAD's exomes return nothing for a card locus, the 1000 Genomes phase 3 panel, already
fetched and lock-pinned for imputation, is counted from its genotypes. A super-population
(or the pooled panel) takes part only if it holds **every called allele at least twice**,
gnomAD's own rule for its small groups (`resolving-populations-v2`), and the population that
maximises the rarest called allele is chosen, as in gnomAD selection.

*Why this cannot weaken AGENTS.md 4.1:* the panel cannot measure the rare-call band (its
largest group holds 1,322 alleles), and two copies in at most 6,000 alleles is never below
0.001%. So the fallback can lift a common call out of "unknown" but can never carry a rare one
out of `likely-artifact`; an allele the panel cannot show twice stays unknown, as before. A
test holds this over every allele count at nine allele numbers. The ClinVar screen and PGx
calling stay on gnomAD alone, since rare variants are what they screen; the X chromosome is
left out (hemizygous counting), which leaves its one card where it was.

*Cost:* one pass over the panel for the card loci, 201 s on this machine, then a 0.1 s read
from a cache keyed by the public loci and the panel's lock digests. Absent the panel (CI, a
fresh clone) nothing changes.

*Effect:* all 21 cards are now priced. With a direct call and a full ancestry match: eye shade,
lactase, coffee intake, vitamin D, blond hair and freckling reach `well-established`; the hair
curl, eye shade (SLC24A4, TYR), baldness, asparagus, cilantro, folate and morningness cards
reach `strong`; the weak-evidence fitness, photic sneeze and candidate-gene caffeine cards stay
`limited` or `moderate`, and BNC2 is `moderate` under C2.

### C2, P2, fixed: an unreplicated finding could be strong

The guide defines `strong` as "replicated evidence with a clear effect", but nothing in the
arithmetic required replication: a GWAS card with `replication: none` and an interval-free beta
scored 0.705 and earned `strong` (`bnc2_freckling`, the only such card). A ceiling now holds
`replication: none` at `moderate` ("the finding has not been replicated"), for single calls
and polygenic scores alike. In today's pack it changes BNC2 only; the candidate-gene caffeine
card was already capped there. A saved run explained by this engine shows BNC2's earlier
`strong` as `not_reproduced`, the explainer's designed answer for a tier set by other rules.

*Considered and not done:* the same ceiling for `same_cohort`. It would cap all 15 LDpred2
polygenic cards, whose UK Biobank hold-out validation is what `same_cohort` records, and the
guide's word "replicated" does not settle whether a hold-out counts. That is a policy question
for the owner, not a calibration defect, and it is left as it is.

### C3, P3, fixed: the guide described well-established wrongly

It said "clinical-guideline or expert-curated evidence, replicated". No guideline or curated
card reaches the tier (see C4); the 27 outcomes that can are functional, cohort and GWAS
evidence with a large effect. The description now says what earns it: replicated evidence with
a large effect, on a common call the array makes reliably, whatever the kind of study.

### C4, recorded, after M15.1: carrier cards score an allele share as an effect size

The CFTR and PAH carrier cards author their effect as a `proportion`: the variant's share of
disease alleles (0.9% to 22%). The calculator reads a proportion as an effect size, so these
cards score almost nothing for effect and top out at `strong` (0.82 to 0.85). The share is not
an effect size: the variant's pathogenicity does not depend on it. The error runs in the
conservative direction for rare chip calls, which AGENTS.md 4.1 says to distrust, and a fix
means deciding what "effect" means for a carrier finding, so it is left for after M15.1 with
the Weedon et al. frequency-band PPVs in hand.

## Checked, no finding

- **No code path filters cards by confidence.** The only tier-dependent selection in source is
  the dashboard's opt-in filter (`web/views.py` `GridQuery`): empty by default, it counts what
  it hides and offers one click back, and an unrecognised value shows more, never less. Scope 1
  (item F) found every skip in the save and read paths skips a file, never a card.
- **A rare call renders as `likely-artifact` with its number on the face.** The card face
  (`_cardface.html`) and the ClinVar page print the benchmark as "about 16% confirmed and 84%
  unconfirmed by sequencing for allele frequency below 0.001%", or 4.2% for BRCA1/2, with the
  clinical notice. Held by `tests/engine/test_confidence.py`, `tests/run/test_bundle.py`
  (round trip), `tests/imputation/test_quality.py` (both front-ends) and `tests/engine/test_ppv.py`.

## Left for the post-run half

Sample the real run's cards across every tier and check each against its evidence; confirm a
rare ClinVar call on the real export reads as above; look at where the 1000 Genomes fallback
priced a card in the real run and whether any card is still unpriced, and why.
