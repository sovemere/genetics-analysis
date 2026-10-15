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
with dosing interpretation reserved for M10.4. CYP2D6 is outside this caller.

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
