# Ancestry portability (M9.5)

Polygenic scores lose accuracy outside the ancestry their effect sizes were estimated in
([AGENTS.md §4.4](../AGENTS.md)). M9.5 states, for every score result, how much of the
study population is **demonstrably** in the sample's ancestry category. It turns that into
the numeric `ancestry_match` that `engine/confidence.py::calculate_confidence` accepts.
The module is `pgs/portability.py`. Its output is the `portability` block of every
**schema-4** `.pgs-score.json`.

It labels and never filters. Sums, terms, coverage and percentiles are identical with and
without it, and the lowest outcome is a confidence ceiling, never a missing card.

## Commands

```text
genetics pgs score path/to/score.txt.gz --input path/to/export.txt      # always computed
genetics pgs portability path/to/result.pgs-score.json --json
genetics pgs portability path/to/result.pgs-score.json --scoring-file path/to/score.txt.gz
```

`pgs portability` reloads a result. It first runs the M9.3 coverage and M9.4 placement
validation, then recomputes the block from the result's own inputs and refuses the file if
anything disagrees. A schema-1 to schema-3 result still holds the
`"not_computed_M9.5"` placeholder; it is recomputed from what it carries and labelled
`recomputed_legacy`. A schema-2 or older result has no 1000 Genomes placement, so it
comes back `not_computed`.

## The two cited mappings

Neither mapping was written from memory (AGENTS.md §6). Both were checked against the
source on 2026-10-09.

1. **Sample → category.** Morales et al., *Genome Biology* 19, 21 (2018),
   [doi:10.1186/s13059-018-1396-2](https://doi.org/10.1186/s13059-018-1396-2), Table 1.
   It was read from the Europe PMC full text (PMC5815218). Each category includes
   "individuals who genetically cluster with" named 1000 Genomes populations, and the
   table names all 26 phase 3 populations. The sample's **placed 1000 Genomes population**
   (M9.4) is looked up there. Super-populations are deliberately *not* used, because the
   paper's categories cut across them:
   - `KHV` is South East Asian, while the rest of `EAS` (CDX, CHB, CHS, JPT) is East Asian.
   - `ACB` and `ASW` are African American or Afro-Caribbean, while the rest of `AFR` is
     Sub-Saharan African.
2. **Category → PGS Catalog display category.** The catalog publishes ancestry
   distributions only in its *display* categories. Its
   [ancestry documentation](https://www.pgscatalog.org/docs/ancestry/) maps each Morales
   category onto one. Three of these merges matter here:
   - African American, African unspecified and Sub-Saharan African all become "African".
   - South East Asian, Central Asian and Asian unspecified become "Additional Asian
     Ancestries".
   - Native American, Oceanian, Aboriginal Australian, Other and Other admixed become
     "Additional Diverse Ancestries".

   A match is therefore made at display-category resolution, the finest the catalog
   publishes. `sample.merged_morales_categories` records the merge so a renderer can say
   so.

Some categories have no 1000 Genomes population: Greater Middle Eastern, Native American,
Oceanian, Central Asian and Aboriginal Australian. They are never mapped to a "nearest"
population. A study share in one of them counts as a mismatch for a sample placed in a 1000
Genomes population. A sample that no panel places is `declined` (below).

The AADR placement (M5.9's 100 Human Origins populations, whose region is a sampling
country) is **not** mapped onto a category, because no cited mapping exists for it. It acts
as a decline gate: if AADR declines, the sample counts as declined even when 1000 Genomes
placed it, so a coarser placement cannot rescue a decline.

## The study side

The metadata CSV carries three `Label:percent|...` distributions:

- `gwas`: the source of variant associations;
- `development`: score development/training;
- `evaluation`: PGS evaluation.

Every share is kept. Percentages are divided by their published total only to remove
rounding: the 6,991 scores in the fetched release total 99.7–100.2, and a zero share such
as `Not Reported:0` is valid. Text that cannot be parsed, or whose total is more than one
point from 100, is recorded as `malformed`. An empty column is `empty`, and a missing
column is `column_absent`.

**Driving stage.** The GWAS stage drives the match, because that is where the effect sizes
were estimated. Development/training drives only when the GWAS column reports nothing
(2,095 scores). Evaluation is recorded but never drives: the catalog weights it by
*sample sets*, not people. In the fetched release, 16 scores report neither GWAS nor
development ancestry.

Each share of the driving stage is classified against the sample's display category:

| Share | Relation |
| --- | --- |
| The sample's display category | matched |
| Any other display category | mismatched |
| `Multi-ancestry (excluding European)`, for a European sample | mismatched |
| `Multi-ancestry (excluding European)` for anyone else, `Multi-ancestry (including European)`, `Not Reported`, an unrecognised label | indeterminate |
| A stage that is empty, absent or malformed | wholly indeterminate |

**`ancestry_match` is the matched share: a demonstrated lower bound.** Indeterminate
shares are never renormalised away. They count only toward `match.upper_bound`, which is
`matched + indeterminate`. A score whose study population is unreported therefore gets
`ancestry_match` 0 with an upper bound of 1. That is "portability not demonstrated", and
the judgment says so; it is not presented as a known mismatch.

## The sample side

| `sample.state` | When | `ancestry_match` |
| --- | --- | --- |
| `placed` | 1000 Genomes named a population and AADR did not decline | the matched share |
| `declined` | AADR **or** 1000 Genomes declined (`declined_by` lists which) | `0.0` — unrepresented, never neutral |
| `saved_only` | scored from a saved run, which has no original array to place | `None` — unknown, and the pooled distribution is not matched |
| `not_run` | no placement could be made (reference absent or disabled, or too little overlap) | `None` |
| `placed_unmapped` | a placed population outside the cited table (not reachable with the real panel) | `None` |

A placement names the nearest population whose fit is within M5.5's decline threshold.
Other populations within the threshold are recorded as `admissible_alternatives`. When
any of them falls in a different display category, the record lists it under
`alternative_display_categories`. The usual case is KHV against CDX, which sit either side
of the East / South East Asian line. The number uses the named population, consistent
with M9.4's comparison group, and the alternatives stay visible.

## Judgment and confidence ceiling

`judgment` is one of the following:

- `matched`: matched share = 1;
- `partial`: 0 < matched share < 1;
- `not_demonstrated`: matched share = 0, some share indeterminate;
- `mismatched`: the whole driving stage is another category;
- `sample_unrepresented`: the sample was declined;
- `not_computed`: the sample's category is unknown.

`confidence_ceiling` is `engine/confidence.py::ancestry_ceiling(ancestry_match)`, the
function the calculator itself applies:

| `ancestry_match` | Ceiling |
| --- | --- |
| below 0.25 | `limited` |
| below 0.5 | `moderate` |
| 0.5 or more | no ceiling |
| `None` | `strong` |

The 0.25 and 0.5 thresholds are the ones M3.3 already set. No new threshold was invented.

Public-metadata check: the cited mapping was run over all 6,991 catalog scores with a
stand-in placement for each of six populations. Because the catalog is European-dominated,
a CEU placement leaves 4,615 scores uncapped, a CHB placement 1,728, and a YRI placement
75. A KHV placement leaves none: no score's driving stage reports a majority in "Additional
Asian Ancestries". That asymmetry is the finding §4.4 exists to show, not an artifact.

## What is versioned and checked

The block records:

- `schema_version`, `method_version` and the `sources` (both citations and the
  study-distribution column);
- every parsed stage with its raw text, and per-stage matches;
- both panels' statuses and reasons;
- the sample's category chain;
- the derived number, judgment, ceiling and reason.

Reload equality covers all of it. The block is built by `score()` (where 1000 Genomes is
`not_requested`) and rebuilt by `attach_reference()`, so every result carries one. The
extraction cache does not affect it: a cold run and a warm run give identical blocks.

## Not done here

- **Coverage, imputation quality and reference comparability** (`fraction_of_score_weight`,
  `imputed_absolute_weight_fraction`, DR2 bins) are confidence inputs *beside* ancestry.
  They are recorded by M9.3/M9.4, and they enter a PRS card's confidence when M9.6 builds
  the card.
- **Single-marker cards** keep `ancestry_match` unset, and the `{ancestry}` template
  placeholder stays locked (now naming M9.6). The run pipeline has only the AADR
  placement; supplying either needs the 1000 Genomes placement carried into the run.
