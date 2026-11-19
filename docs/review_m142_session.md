# M14.2 session diff review

Scope: M14.2's working tree before its commit, on top of the M14.1 commit. That is the
reference positions (`PopulationFit.centroid`, `Placement.scale`, bundle format 29 and
its reader check), `reads.ancestry_report` and `ancestry_view`, `genetics runs ancestry`,
the ancestry page and its stylesheet, agent schema version 7, the parity rows and the
tests. Every changed source line was re-read, and the page was rendered with 100 invented
reference populations and looked at. No personal export and no saved real run was opened.

## Findings and fixes

- **P2, found while writing the tests: every saved centroid was the sample's own
  position.** `place_many` cross-joins the scaled sample with the centroids, and polars
  suffixes the centroid's clashing `PC` columns with `_c`. The first version read
  `row["PC1"]`, the sample's column. The new test that the distance from the scaled sample
  to each centroid equals the saved distance failed, and the centroid is now read from the
  suffixed columns.
- **P3: each of the hundred reference rings took a tab stop.** A keyboard user had to tab
  through every population to reach the table. Only the five nearest and the run are
  focusable now; every ring keeps its hover text, and the table holds them all.
- **P3: `region_index` was carried in the scatter and used by nothing.** It was there for
  a colour per region, which the dataviz rule for scatters (at most three categorical
  hues) ruled out. Removed from the view and from schema version 7, which has not shipped.
- **P3: the panel size printed without a thousands separator**, and would have failed on
  a panel whose size was not recorded. Formatted, with a sentence for the missing case.

Two guards were then removed in turn, and each removal failed a test: the refusal of
positions in a format before 29, and the scaling of the sample into distance units.

## Re-read and unchanged

- **A run is drawn against its own reference or not at all.** Reading the installed
  reference at render time would plot a months-old run against a panel it was not placed
  in. Runs saved before format 29 list their fits by rank, and the page says why there is
  no scatter.
- **Two components of many.** The scatter is the first two; the table ranks on all of
  them, and the caption says that nearness on two is not nearness on all.
- **The hues** are the polygenic chart's, validated all-pairs in both modes with the
  dataviz validator (worst CVD ΔE 24.7 light; normal-vision ΔE 33.6 light, 31.8 dark).
  Shape carries identity as well: ring, filled dot, cross in a ring.
- **`runs ancestry` is not scanned**: it states an inference about the reader, as
  `runs card` does, and the walk-through lists it among the commands whose output never
  leaves the machine.
- **An infinite fit** (a zero-radius population) prints as JSON's `Infinity`, as
  `runs show` has always printed it.

## Validation

The ancestry, run, HLA, engine, health and imputation suites pass (2,042 tests) after the
format change, and the page, schema, parity and walk-through suites after the review. The
full native suite passes **4,387 tests with nine skips** in 765 s.
Strict mypy (`--platform win32`, `src` and `tests`), ruff and format pass.
