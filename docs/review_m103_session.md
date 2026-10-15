# M10.3 session diff review

Scope: `1bee233..a98124d`, covering saved CYP2D6 limitation presentation,
CLI/dashboard integration, the six acceptance cases and next-step documentation.
All reproductions use the shipped assay-limit card and fabricated or synthetic
runs; no consumer export is opened.

## Reproduced findings and corrections

1. **Incomplete saved text could be called recorded evidence.** The adapter
   checked only card ID, kind and status. A readable saved snapshot with a null
   impossibility reason, or a blank reason/title/summary/detail, still returned
   `status: recorded`. The notice or CLI could then display an empty explanation
   or `None`. Five disk-read reproductions fail before the fix. The adapter now
   requires nonblank saved title, summary, detail and impossibility reason before
   reporting complete evidence. Otherwise it returns `not-recorded`, `card: null`
   and an explicit complete-evidence-not-recorded explanation. It neither consults
   today's pack nor edits the run. Tests verify CLI JSON and dashboard, tier,
   overview and gene-detail views, including byte-identical bundle files afterward.

2. **Tier-filter acceptance was using an ignored value.** The six-case matrix
   requested `tier=high`; the parser supports `strong` and explicitly ignores
   `high`. A new assertion against ignored-filter notices reproduced this test
   gap. The matrix now uses `tier=strong`, adds interpreted-only and combined
   controls, and checks that the ordinary saved card is counted as hidden and
   has no grid link while its adjacent assay limitation remains visible. The
   seven dashboard arrangements, overview, all eight genes and both candidate
   pages pass. This corrects coverage; no production filter behavior changed.

The normal complete-card snapshot, sample schema 1, catalog schema 1, bundle
format 19, source pins, candidate enumeration and M9.13 confidence are unchanged.
The review adds no guideline or dosing interpretation. Five new cases plus the
six strengthened cases pass together. Server-rendered HTTP checks are used;
no interactive browser review is claimed.

## Documentation and next step

The ingestion guide now distinguishes its reference-only inspection from the
implemented caller and states the current bundle format. README, roadmap and
handoff point to M10.4. Its entry contract names the actual frozen CPIC tables,
requires exact drug/guideline/lookup joins and multi-gene conditions, keeps
pair-level CPIC evidence separate from recommendation classification and allele
function strength, and retains every conditional candidate branch. New card or
bundle representation must be documented before implementation. M10.5 remains
the separate once-per-section prescribing-tool framing item.

## Validation

Validation covers **3,219 unique passing tests**, with five existing Windows
skips. The broad native run passed **3,218** tests in **665.37 seconds** and had
one setup failure: the isolated `GENETICS_DATA_DIR` hid the default-installed
bref3 tools used internally by the existing native-reference helper. That
native compatibility test passes with the expected default tool directory
restored (**6.79 seconds**). These are combined results, not a second complete
suite run. The helper and production imputation code are unchanged.

The eleven focused review cases pass in **12.37 seconds**. All four strict
Windows/Linux × Python 3.11/3.13 targets check 213 files; full dbSNP card lint
passes 69 cards/320 renders/39 resolved keys. Fixture reproduction, repository
lint/format, whitespace and staged privacy checks pass. Native PLINK, Beagle,
bref3 and PGS arithmetic checks are enabled with the pinned tools and Java 17.
No fetched payload, personal export or genotype-derived output is committed.
