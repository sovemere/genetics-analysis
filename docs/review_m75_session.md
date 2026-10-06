# M7.5 session diff review — 2026-10-06

Reviewed `1fc2f00..537e3c5`, the session's common-health cards, two-marker matching,
confidence/serialization, pipeline integration, CLI/dashboard and documentation changes.
The implementation checkpoint passed [all five CI jobs](https://github.com/sovemere/genetics-analysis/actions/runs/37434344709).
This follow-up fixes the defects below and prepares [M7.6](handoff.md#next-m76).

## Findings and fixes

1. **High: confidence and saved effect evidence used another outcome's estimate.**
   A fabricated APOE e2/e3 result inherited the e4/e4 Alzheimer-disease HR 8.74;
   an e3r-containing pattern inherited the same common-genotype disease evidence.
   HFE one-copy/no-copy and F5 no-copy/homozygote results had the corresponding
   card-wide estimate problem. Two regressions failed before the fix, confirming the
   incorrect effect and evidence inheritance. Knowledge schema 3 adds a complete
   outcome evidence override or explicit null. Assembly selects it before scoring and
   saving. Unestimated/comparator outcomes retain citations and observations, have null
   phenotype inputs and zero phenotype scoring components, and cannot exceed limited
   confidence; rarity and poor quality still produce likely-artifact.
   APOE common outcomes now use the applicable effects in
   [Rasmussen 2018, Table 2](https://doi.org/10.1503/cmaj.180066); F5 homozygotes use
   the homozygote HR in [Juul 2004](https://pubmed.ncbi.nlm.nih.gov/14996674/).
   Absolute-risk contexts and their baseline gaps remain source-specific; no personal
   probability or new demographic inference was introduced.

2. **Medium: saved marker calibration could contradict the observations.**
   The original validator accepted a digest-consistent marker snapshot whose observation
   was imputed while its confidence still claimed a direct call. Loading the original
   validator from `537e3c5` reproduced acceptance; the corrected validator rejects it
   with a genotype-free domain error. Regression cases also cover a common companion
   replacing the rarest called-allele frequency, overstated rarity/unknown-frequency/
   poor-quality tiers, and another outcome's phenotype inputs. Multi-marker schema 2
   binds calibration to the saved phenotype estimate. Constituent matching views now
   have distinct internal IDs and neutral outcomes, preventing reordered matches or
   arbitrary first-outcome evidence from entering assembly.

3. **Medium: the multi-marker detail view omitted observation quality and calibration.**
   Both markers were saved, but the dashboard showed neither their call source nor
   imputation quality/ancestry-match inputs and full reliability breakdown. An unresolved
   aggregate also hid the constituent benchmark. The detail template now exposes these
   saved values, including per-marker PPV when available and explicit unavailable PPV
   for likely-artifact markers without a benchmark. Synthetic saved-view regressions
   cover both resolved and phase-unresolved results.

4. **Low: lint divided marker resolutions by interpretation-card count.**
   The two-marker card made successful full lint display `35/34`. `variant_count` now
   records authored marker references, including repeated occurrences across cards,
   and both CLI text and JSON use that denominator. Full cached dbSNP lint reports
   `35/35`. This is a lint counter, not the unique-position coverage metric for M7.6.

## Compatibility and handoff

New runs use **bundle format 12 / multi-marker schema 2**. Knowledge schemas 1–3 are
supported, and formats 1–11 remain saved snapshots. A synthetic format-11 regression
retains the original APOE card-wide HR 8.74 instead of silently replacing it with the
current outcome estimate. New nullable calibration cannot claim an older bundle format.
ClinVar schemas 1–4 and their measurement-calibration/reportability semantics are unchanged.
Re-run an old M7.5 result to obtain corrected outcome-specific evidence.

The [common-health guide](common_health.md) documents estimate selection and source scope;
the [knowledge guide](../knowledge/README.md#outcome-specific-evidence-schema-3) documents
schema 3. Current-format guides, README and roadmap are synchronized. The M7.6 handoff
defines unique reference/chip positions, both coverage denominators, called versus present
overlap, allele resolution, missing/empty states, snapshot validation and shared interfaces.
M7.6 remains open; no new chip-overlap measurement is claimed here.

## Validation and privacy

- Full suite: **2,158 passed, five existing Windows skips**, pinned native ROH enabled.
- Strict mypy: Windows/Linux × Python 3.11/3.13, all 156 files.
- Ruff checks and formatting, synthetic-fixture reproduction, and full dbSNP lint:
  50 cards, 266 template renders, 35/35 authored marker references.
- Twenty-three additional regressions cover the fixes, evidence-schema boundaries,
  absent-effect rarity/quality gates and format-11 compatibility. Saved CLI/dashboard
  parity and the full pipeline's constituent-locus queries remain covered.
- M7.5's earlier synthetic-only, full-reference offline acceptance remains recorded in
  the handoff. This review changes no reference payload, index transform or source pin;
  it uses fabricated observations and saved-view tests without a personal export.

All temporary test bundles stay outside the checkout. No genotype-derived output,
reference payload or private run is staged. Privacy scanning and the pre-commit hook
remain enabled; no output type or ignore exception was added.
