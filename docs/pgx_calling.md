# M10.2 sample-call contract

Sample schema 1 is separate from public reference schema 1 and from the M9.13
confidence method. Bundle format 19 adds `pgx.run.json`; older runs expose PGx
as not recorded. This private payload contains the complete frozen public
catalog, its digest, QC sex, exact-locus observations (including original probe
identities and native imputation records), public frequency records, and the
derived eight-gene candidate results. Reads validate the catalog and reproduce
the results from the saved inputs without current references or network access.
The [M10.2 diff review](review_m102_session.md) additionally binds every requested
locus's full dosage record list to the independent saved native payload on both
write and read. Internally consistent substitutions, omissions and duplicate
counts cannot become healthy saved calls. This adds a sequential verification
pass over native dosages when a completed PGx stage is recorded.
Original probe presence, eligible direct genotypes and no-call provenance are
also compared, restoring recorded complementation and doubled single-copy array
storage for the comparison without inferring new strand or phase information.
The existing `*.run.json` privacy rule covers this output, including copies
under `knowledge/`. No consumer export is required for development acceptance.

The shared engine enumerates every compatible definition-ID pair, or single
definition for a one-copy G6PD locus. Diploid phase is unresolved: feasibility
is checked jointly at each locus without assigning chromosomes across loci.
Beagle's native GT, DS and DR2 survive as evidence, but its ordered GT is not
treated as established phase. Dosage is never rounded to manufacture a call.
Original non-no-call probes block replacement by imputation; contradictory
duplicates, I/D and incompatible alleles are explicit unusable observations.
Matching is by verified GRCh37 forward position and allele contract; sample
rsIDs are retained as identities, never used as a coordinate fallback.

Unspecified constraints are wildcards, not reference bases. Source reference
definitions additionally require reference bases across the gene's known
locations; missing or unresolved locations remain obligations. Partial,
conflicting and structural definitions remain possible alternatives unless
their usable constraints exclude them. Contradictory reference definitions
are retained as unresolved alternatives, rather than treated as tested.
Candidates record missing/unresolved constraints, unassigned observed loci and
their exact source phenotype-mapping IDs. A unique fully supported candidate
is a provisional array-compatible call, never a clinical confirmation.

Phenotypes and activity scores come only from the source diplotype → lookup →
result joins, using native allele counts, not a generic activity-value sum.
DPYD's `ACTIVITY_SCORE`, notes and expression-valued activity fields survive
unchanged. G6PD's one-copy mappings are queried with one allele. Unknown QC sex
retains both one- and two-copy possibilities. VKORC1's absent phenotype mapping
is explicit; genotype-linked recommendation keys are retained for inspection,
with guideline interpretation supplied by the separate
[M10.4 engine](pgx_guidelines.md). CYP2D6 is outside this caller.

Reliability is independent of the frozen card confidence arithmetic. Every
gene face reports coverage and uncertainty. Allele-specific gnomAD rarity
keeps rare calls at `likely-artifact`, including imputed observations; the
published ~16% heterozygous chip confirmation benchmark is explicitly scoped,
not a personal posterior. Missing frequencies/quality stay unknown and poor
DR2 lowers reliability without deleting candidates. Structural variants remain
unmeasured even if all known SNP constraints are observed.

`genetics run` executes the stage when the prepared reference exists, otherwise
saves an explicit unavailable result. A damaged present reference fails loudly.
Saved calls are inspected with `genetics pgx calls RUN --gene GENE --json` and
the dashboard's pharmacogenomics section. Both consume the same saved record;
no guideline-linked dosing cards or duplicate CYP2D6 card are introduced here.

The missing-position and phase rules were cross-checked against PharmCAT's
[matching method](https://pharmcat.org/methods/NamedAlleleMatcher-101/) and
[example report](https://pharmcat.org/examples/pharmcat.example.report.html).
This caller retains sparse constraints rather than adopting PharmCAT's default
reference-filling convention. CPIC's [G6PD guideline](https://files.cpicpgx.org/data/guideline/publication/G6PD/2022/36049896.pdf)
also distinguishes one-copy calls from heterozygous two-copy genotypes, whose
enzyme phenotype cannot be determined from genotype alone. Source phenotype
labels remain candidate annotations here.

## M10.3 CYP2D6 placement

The existing `cyp2d6_structural_variation` knowledge card now stays beside
sample calls on the dashboard, the PGx overview and all eight gene-detail
pages. A shared saved-evidence adapter reads the frozen card from the run;
knowledge-card filters and tier grouping do not remove this adjacent notice.
Its link opens the original saved detail, including the whole-gene deletion
example. The ordinary knowledge-card grid still follows the selected filters.

`genetics pgx calls RUN [--gene GENE] --json` adds `cyp2d6_limitation` with
`status: recorded` and the saved title, summary, detail, impossibility reason
and caveats. Text inspection states the saved summary and reason. Calling
remains restricted to the eight SNP-tractable genes; CYP2D6 has no fabricated
candidates, phenotype or dosing implication. Sample schema 1, bundle format 19
and confidence arithmetic are unchanged.

Unavailable-reference stages still show all eight genes beside the limitation.
Formats 1–18 keep their explicit sample-calls-not-recorded state. If a historical
or nonstandard pack lacks a saved impossibility card, the adapter reports
`status: not-recorded`, `card: null` and a precise notice; it does not load the
current knowledge pack or modify the bundle. A same-ID record of another kind
or status is not treated as saved assay-limit evidence. The recorded state
also requires nonblank saved title, summary, detail and impossibility reason.
Incomplete text produces an explicit complete-evidence-not-recorded notice
without filling gaps from today's pack or changing the saved files.

Six synthetic acceptance cases cross saved/missing cards with completed,
unavailable and historical stages. They check CLI text/JSON, seven dashboard
filter/group choices, the overview, every gene detail and immutable bundle
bytes. The completed cases retain all 136 compatible CYP2C19 candidates across
two pages, with the limitation on both pages. Existing definition-ID labels,
reliability styles and numerical rare-call benchmark checks remain in force.
This is server-rendered HTTP verification; no interactive browser review is claimed.
No personal export is opened, and no new reference or output type is introduced.

Original M10.3 validation covers **3,214 unique passing tests**, with five existing
Windows skips. The broad native run passed **3,194**, with 20 sandbox-related
failures, in **598.57 seconds**. All 27 PGS reference tests pass with an isolated
writable cache (17.68 seconds); both Beagle cancellation tests pass outside the
sandbox (2.31 seconds), as do all 21 CLI reference tests (8.38 seconds). These
resolve every broad-run failure: 17 cache-write denials, two child-process
cleanup restrictions and one missing machine-architecture probe. This is
combined coverage, not a second full-suite run. All 449 affected PGx, web, saved
CLI and impossibility tests pass (75.71 seconds); the final six placement cases
also pass after adding saved-wording and invalid-kind/status checks (6.30 seconds).

Four strict Windows/Linux × Python 3.11/3.13 targets check 213 files. Full dbSNP
card lint passes 69 cards/320 renders/39 resolved keys; fixture reproduction,
lint/format, whitespace and staged privacy checks pass. Local sandbox Python
reports an empty machine architecture, so its commands use the process-local
`POLARS_SKIP_CPU_CHECK=1` workaround; no installed package or production code
is changed for this environment issue. Native PLINK/Beagle/bref3 checks use the
pinned tools and portable Java 17. No personal export is opened.


The [M10.3 diff review](review_m103_session.md) adds five incomplete-text
regressions and strengthens all six placement cases with real tier and
interpreted-only filters. Validation covers **3,219 unique passing tests**,
five existing Windows skips: 3,218 broad-run passes plus the native helper
setup recheck. Four strict type targets, full card lint, fixtures, style and
privacy checks pass. See the review for exact run boundaries.

## Acceptance

The complete public catalog passed offline calling with seeded synthetic
observations generated from public gnomAD frequencies where available (uniform
synthetic sampling at unknown-frequency sites), plus an empty-marker
sample with ambiguous sex. All eight gene definition sets survived; every
empty-marker candidate stayed conditional; JSON reload reproduced the results.
Including verification of the 63 GB frequency source, this took 223.65 seconds.
No personal export was opened. Sample calling does not extend the reference
mapping coverage established at M10.1; those unresolved source locations remain
visible obligations. The complete catalog is frozen in each run (approximately
40 MB of public-reference JSON before observations/candidates), an accepted
storage cost for reproducibility.

The complete native suite passes **3,188 tests**, with five existing Windows
skips, in **485.77 seconds**. All pinned PLINK, Beagle, bref3 and PGS arithmetic
checks are enabled with Java 17. The 51 added synthetic regressions cover eight
genes, cis/trans ambiguity, missing/partial/conflicting/structural definitions,
unusable probes, one-copy G6PD and unknown sex, DPYD source score expressions,
VKORC1 gaps, rare/imputed reliability, malformed snapshots, run QC/execution
consistency, pipeline integration and saved CLI/dashboard/historical parity.
Four strict Windows/Linux × Python 3.11/3.13 targets pass (212 files); complete
card lint passes 69 cards/320 renders/39 keys. Fixtures, style and staged privacy
checks pass. M9.13 confidence arithmetic and source pins remain unchanged.

The subsequent [diff review](review_m102_session.md#validation) covers 3,208
unique passing tests and five existing Windows skips, including a final 399-test
affected integration run. Full-source offline comparison also preserves the
original healthy calling results and schema-1 reload; four strict type targets,
full card lint, fixtures and style pass. See the review for the run boundaries
and saved-evidence corrections.


## M10.4 guideline interpretation

The sample caller remains schema 1 and records source mappings rather than
clinical phenotypes. The additional [guideline card engine](pgx_guidelines.md)
evaluates eight declarative knowledge selectors from those immutable inputs.
New bundles use format 20; formats 1–19 remain readable without adding current
interpretations. The existing CYP2D6 placement and all M10.2 reliability rules
remain unchanged. M10.5's once-per-section framing is the next open item.

The [M10.4 diff review](review_m104_session.md) adds guideline display schema 2
for complete source-evidence checks while retaining schema-1 card reproduction.
Exact numeric validation rejects boolean/integer and float/integer substitutions.
Sample calling and its schema remain unchanged.
