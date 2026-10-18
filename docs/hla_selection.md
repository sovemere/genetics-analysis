# HLA classifier selection and call confidence (M11.3)

M11.2 ran one explicitly named HIBAG HLARES classifier. M11.3 chooses the classifier from
the run's persisted M5 ancestry placements, records the choice and its rationale in the
saved HLA evidence, and folds each call's joint posterior, marker coverage and the
classifier's ancestry match into an observation ceiling. Every locus is still saved, and
low-confidence calls stay visible. M11.4 turns this frozen evidence into HLA-linked cards.

## Contract recorded before implementation

HLA sample schema 2 adds a top-level `selection` record and a `confidence` record on each
locus. Bundle format 22 writes schema 2 only; format 21 bundles hold schema 1 only and are
read unchanged, as an explicit classifier with neither field recorded. Formats 1–20 remain
HLA-not-recorded. No earlier evidence is reinterpreted, and no card, PGx or imputation
schema changes.

Selection reads no genotype. It consumes the two placements M5 already saved: the Human
Origins (AADR, M5.9) placement and the 1000 Genomes placement (M9.4/M9.13). The saved
selection keeps their statuses, names and reasons, the 1000 Genomes fit, decline
threshold, margin and projection coverage, and every admissible population's fit. It
keeps no PCA coordinates. On reload the selection is recomputed from its frozen
placements, and those placements must equal what the same bundle's `ancestry.run.json`
records. A record copied from another run, or one whose inputs were edited, is refused.

## Selection rule

Both ends of the mapping are cited, as M9.5's portability mapping is:

1. The 1000 Genomes population maps to its Morales et al. 2018 category
   ([DOI 10.1186/s13059-018-1396-2](https://doi.org/10.1186/s13059-018-1396-2), Table 1),
   the table `genetics.pgs.portability` already cites and uses.
2. A category maps to a classifier only where the publisher's own training description
   names it. The descriptions are quoted from the
   [HLARES index](https://hibag.s3.amazonaws.com/hlares_index.html) (verified 2026-10-18):

| Classifier | Publisher's training description | Categories | Ancestry match |
|---|---|---|---|
| european | "HLARES data of European ancestry" | European | 1 |
| asian | "HLARES data of Asian ancestry (East & South Asia) and HapMap CHB+JPT" | East Asian | 1 |
| asian | (same) | South Asian | unknown |
| hispanic | "HLARES data of Hispanic ancestry" | Hispanic or Latin American | 1 |
| african | "African American HLARES data and 60 African parents of HapMap YRI" | African American or Afro-Caribbean; Sub-Saharan African | 1 |
| none | none names it | South East Asian (KHV) | — |

The Asian description names South Asia but publishes no split. Zheng et al. 2014
([DOI 10.1038/tpj.2013.18](https://doi.org/10.1038/tpj.2013.18)) reports 720 Asian
HLARES subjects, self-reported, with no breakdown. A South Asian placement therefore
selects the Asian model with an *unknown* match, never a perfect one. *South East Asian* is
a separate Morales category that no description names, so KHV has no classifier. African
American and Sub-Saharan African are matched at category level, as M9.5 matches them.

Automatic selection then applies these rules, in this order:

- **Decline.** If either placement declined to name a population, the sample is
  unrepresented and nothing is selected (`declined`). A coarser 1000 Genomes placement
  cannot rescue an AADR decline.
- **Not run.** If either placement was not run, nothing is selected (`not_run`). Without
  the AADR gate, an ancestry that 1000 Genomes lacks (for example Middle Eastern or
  Central Asian, §4.6) cannot be excluded.
- **Ambiguous.** Every other 1000 Genomes population whose fit is also within the decline
  threshold is a candidate the placement could not rule out. When the candidates point at
  different classifiers, or at none, nothing is selected (`ambiguous`).
- **Unsupported.** A category with no classifier selects nothing (`unsupported`).
- Otherwise the category's classifier is `selected`.

No HLA-specific margin is added on top of the panel's measured 99.5% decline threshold.
A second threshold chosen here would be an uncalibrated number. The margin is recorded
for display instead.

## Explicit classifiers

`--hla-classifier` still runs the named model, and the record keeps what the placement
supported beside it (AGENTS.md §0.1A: label, never suppress). The explicit choice gets an
ancestry match from the same rule:

| Automatic outcome | Explicit classifier | Ancestry match |
|---|---|---|
| selected | the same classifier | the category's match (1, or unknown for South Asian) |
| selected | a different classifier | 0 |
| declined or unsupported | any | 0 |
| ambiguous | one of the candidates | unknown |
| ambiguous | not a candidate | 0 |
| not run | any | unknown |

Both paths still require the model-terms opt-in (`--hla-model-opt-in`). The opt-in on its
own now means "use the classifier the placement selects". When nothing is selected, the
stage records `no-classifier` with the full selection and makes no calls. That is a
refusal to guess, not a negative HLA result.

## Call confidence

Each locus carries `confidence`. A `no-markers` or `no-prediction` locus is `not_computed`
and has no ceiling; it is not evidence against any allele. A predicted locus records its
joint posterior, its marker coverage (observed / model markers), the classifier's ancestry
match, and the ceiling those three impose. `engine.confidence.calculate_hla_call_reliability`
computes it. **It introduces no new number:**

- **Posterior.** The joint posterior goes in the imputation-quality slot, with the
  single-variant DR2 ceilings: below 0.30 likely-artifact, below 0.60 limited, below
  0.80 moderate. That is where `calculate_confidence` will place it once an M11.4 card
  supplies literature evidence, so M11.3 and M11.4 apply one rule.
- **Marker coverage.** Reuses `ancestry_ceiling`'s bands, as polygenic weight coverage
  does: below 0.25 limited, below 0.50 moderate.
- **Ancestry match.** Uses `ancestry_ceiling` itself: 0 caps at limited, and unknown caps
  at strong.

The ceiling is the weakest of the three. `ceilings` lists the inputs that lowered it, in
order. There is no score, because without a claim there is nothing to weight.

Zheng et al. 2014 chose a 0.5 call threshold and report that it corresponds to about 80%
prediction accuracy. Each call records whether it meets that threshold, for display only.
It filters nothing and sets no tier. A posterior of 0.5 and one of 0.49 share the
`limited` ceiling.

HIBAG's per-sample "matching proportion" would be a third, direct measure of how well the
training haplotypes represent the sample. Its vignette says only that a very low value
indicates under-representation and publishes no threshold. M11.2's frozen output does not
capture it, so it is left for a later step rather than turned into a tier with an invented
cut-off.

## Validation

Selection, confidence and the bundle binding are covered by synthetic tests that build real
`PopulationResult`/`Placement` objects, so the parser reads exactly what M5.8 writes:

- all 26 1000 Genomes populations map through their category;
- each refusal path (decline, not run, ambiguous, unsupported) holds;
- each explicit override records its ancestry match;
- tampering with any selection field, frozen placement or locus confidence is refused;
- the ceilings hold at every band edge;
- a format-21 schema-1 record still loads, and a schema mismatch is refused in both
  directions;
- a selection copied from another run is refused at write time and at read time.

Every one of ten guards was neutered in turn, and each change failed a test.

The pipeline test runs the real selection on the real `analyse()` context. The stage test
shows that only the selected model is verified: an automatically chosen model is not
prepared until ancestry has chosen it, and a declined placement prepares none.

Native acceptance, run locally on 2026-10-18 with R 4.6.1 and HIBAG 1.48.2, passed all
five native tests in 255 seconds:

- the synthetic classifier round trip;
- all four published classifiers, each prepared against the real dbSNP and 1000 Genomes
  references (47–87 seconds per model).

These tests now write schema-2 records with an explicit selection. The genotypes are
synthetic, so this shows the path runs end to end, not that any call is accurate.

The broad local suite: 3,465 passed, ten failed, 53 skipped. The skips are native
ROH/Beagle tool roots and published-classifier references, none configured for that
run. All ten failures were tests pinning bundle format 21 as the current version; after
the bump to 22, their four files pass 245 tests. Four strict type targets (228 files),
lint and format pass.

The [session diff review](review_m113_session.md) added a test that renders every
selection outcome through the dashboard and CLI. It also corrected the explicit-override
wording, and made `select()` honour cancellation.

## Local use

```text
genetics refs fetch --only hibag_hlares_european_hg19 --opt-in hibag_hlares_european_hg19
genetics run --input <local-input> --hla-model-opt-in            # ancestry-selected
genetics run --input <local-input> --hla-model-opt-in --hla-classifier european   # explicit
genetics hla calls <run-id> --json
```

Automatic selection needs both placements: the AADR modern panel (M5.9) and the
1000 Genomes panel. It also needs the selected classifier to have been fetched. A missing
model records `model-missing` with the selection kept.
