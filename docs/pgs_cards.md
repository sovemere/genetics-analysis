# Polygenic score cards (M9.6)

M9.6 turns a private score result (M9.2–M9.5) into a **card** that the dashboard and the
CLI both show. The card is drawn from the distribution of reference scores, and the person
appears only as an interval within it. Physical-health, mental-health and other cards are
authored in M9.7 onwards; M9.6 is the schema, the engine path and the renderer.

## Authoring a polygenic card

A polygenic card lives in `knowledge/` like any other card, in a file with
`schema_version: 4`:

```yaml
schema_version: 4
cards:
  - id: example_polygenic
    section: physical_health          # health, mental health, psychometrics, traits,
    kind: polygenic                   # nutrition, substance use, sleep, fitness
    title: ...
    pgs: {id: PGS000001, source: pgs000001_grch37}   # a reference-manifest entry
    trait: breast cancer
    summary: What the score measures. Plain text; no placeholders.
    detail: How it was built and what it does not capture. Plain text.
    evidence: {tier, effect, sample_size, ancestry, replication, within_family_attenuation}
    decile_outcomes:                  # optional; absolute rates by score decile
      measure: cumulative incidence to age 80
      population: ...
      sample_size: 50000
      source: "10.xxxx/..."           # must be one of this card's citation ids
      base_rate: 0.12                 # proportions, never percentages
      rates: [ten proportions, lowest decile first]
      context: optional text
    citations: [...]
```

Validation rules:

- **`summary` and `detail` take no placeholders.** The engine writes every statement about
  the person, so none of the required ones can be left out.
- **`decile_outcomes.source` must name a citation on the card.** That way each rate can be
  checked against the paper it came from.
- **`genetics cards lint` checks the scoring source.** `pgs.source` must be a manifest
  entry that fetches exactly this score's file. The scoring file's licence is still decided
  by the metadata CSV (AGENTS.md §4.8).

## What a run does

`genetics run` scores every polygenic card with the same functions `genetics pgs score`
uses (`pgs/runner.py`):

1. **Before reading the export,** `PolygenicStage.prepare` locates each scoring file,
   verifies it against `manifest.lock`, applies the licence gate and extracts the public
   1000 Genomes rows. A tampered file therefore fails before any personal data is read.
2. **After imputation,** the stage places the sample among 1000 Genomes populations once
   per run and scores each card.
3. **Each card's private score record** is saved in the bundle as `pgs.run.json`. This
   needs **bundle format 17**; formats 1–16 carry no polygenic cards.

Absence and errors are handled differently:

- **Something absent leaves the card visible.** It is shown `not_run` with the reason and
  the fix. This covers a scoring file that has not been fetched, metadata that has not
  been fetched or has no row for the score, and a licence that needs an opt-in a run
  cannot give. One unrunnable card never stops the others.
- **Something present but wrong raises.** A scoring file whose digest disagrees with its
  lock is the main case.

## The face: no point estimate

**There is no point estimate about the person** (AGENTS.md §4.5). The display derivation
(`derive_position`) never copies the person's sum or their single percentile. What the
card carries is the following:

- **Reference group.** The comparison group's histogram and quantiles, its label and size,
  and whether it is ancestry-matched.
- **The person's interval.** M9.4's Wilson interval, the deciles it overlaps, and the
  matching range in score units. The face states that the interval reflects only the size
  of the reference group.
- **Coverage.** Rows scored and the comparable share of the score's absolute weight.
- **Quality.** A weight-averaged quality (direct calls count as 1, imputed calls as their
  DR2, unknown quality as 0) and the imputed and unknown-quality shares.
- **Portability.** The full M9.5 block. The face shows the judgment, the demonstrated
  match and its upper bound.
- **Within-family attenuation,** or a statement that it is unknown. Above 1 the face
  says the population association does not overstate the direct effect.
- **Absolute rates by decile and the base rate,** or a statement that a position is not a
  risk.

In the dashboard, the reference histogram fills the chart and the interval is a washed
band labelled with its percentile range. The colours are a validated pair for both themes
(`--pgs-bar`, `--pgs-band`); each bar has hover text; and the deciles and inputs are
repeated as tables.

## Confidence

`engine/confidence.py::calculate_polygenic_confidence` uses the single-variant
calculator's own weights and thresholds. No new number is introduced; each reuse is
stated below.

| Input | Treatment |
| --- | --- |
| Evidence, effect, replication | The calculator's scores and evidence ceilings. |
| Comparable score weight | Takes the slot allele frequency holds for one call: whether the observation is really there. Capped by `ancestry_ceiling`'s 0.25 and 0.5 bands, because both are a demonstrated share of the basis. |
| Weighted imputation quality | The single-variant DR2 ceilings (0.3, 0.6, 0.8), applied to the weighted mean. |
| Ancestry match | M9.5's `ancestry_match`, with the calculator's own ceiling. |
| Rarity | No ceiling. A sum over common variants has no rare-call PPV (§4.1). |

The tier sits in `computation.reliability` with every input and the ceilings that applied.
Nothing is filtered by confidence.

## Re-derived on read

`read_bundle` binds and recomputes every polygenic card against its stored score record,
and refuses the run if anything disagrees. This is the same pattern M9.3–M9.5 use. It
checks:

1. **The record.** The digest must match. Coverage, distribution and portability are
   recomputed from the record's own evidence.
2. **The card.** Its display, reliability (rebuilt from the stored evidence) and face text
   are recomputed and must match exactly.
3. **The pairing.** Every polygenic card has its record, and every record has its card.

## Not in M9.6

- **Single-marker ancestry match and the `{ancestry}` placeholder** are carved out as
  **M9.13**. Applying the PRS ancestry ceilings to one large-effect variant would re-tier
  every card in the pack. That is a decision about the evidence, not about rendering, and
  it also needs the run's own 1000 Genomes placement.
- **Opting into restricted licences inside a run.** `genetics pgs score
  --allow-restricted` remains the only opt-in.
