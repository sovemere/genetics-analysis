# M10.4 guideline cards: implementation contract

Recorded before implementation, 2026-10-15. Knowledge schema 5 adds kind
`guideline`, restricted to pharmacogenomics and the eight M10.2 genes. The
declarative selector is the existing `gene` field. Cards carry real citations,
not fabricated effect sizes or population sample sizes for a recommendation.

New guideline cards use display schema **2** after the
[session diff review](review_m104_session.md); schema 1 remains readable with
its original frozen rules. Bundle format 20 adds guideline computations to ordinary saved cards. Public
catalog schema 1 and sample-call schema 1 stay unchanged. The computation
freezes selector, all compatible recommendation branches, source row identities,
publication evidence, conditions, gaps and inherited reliability. Save and reload
rederive the display from the independently validated, immutable PGx sample
record. Formats 1–19 remain readable without adding current interpretations.
No new private file type is needed; existing card and run privacy rules apply.
M9.13 confidence arithmetic is unchanged.

Resolve each candidate's definition IDs to labels and native copy counts, then
follow its mapping IDs through diplotype, lookup and result rows. PHENOTYPE
genes use the result label; ACTIVITY_SCORE genes use the source lookup total,
never a sum of allele activity expressions. Exact numeric scalar equivalence
is allowed, but expressions are not evaluated. Preserve every supporting mapping
and all unmapped candidate IDs. Drug-specific allele function annotations remain
annotations, distinct from the source's phenotype lookup.

Recommendations are bound by guideline ID, drug ID and complete lookup key.
Every required gene gets its own candidate/mapping support or explicit unknown
condition. A missing/noncallable gene or extra clinical context cannot establish
applicability. All retained implications are conditional source annotations, not
clinically established sample phenotypes. Pair CPIC level, recommendation
classification and allele-function strength retain their separate source names.
Only non-null guideline publication joins supply guideline citations. New cards
require a usable HTTPS URL, a titled and format-valid DOI/PMID and nonblank
recommendation text before displaying an implication. Missing or malformed
rows/URLs/citations/text and population/context limits stay explicit. A partial
bad identifier does not erase another valid citation or abort the whole stage.

The frozen v1.60.0 audit finds no VKORC1 recommendation lookup keys and no
phenotype lookup rows. Its warfarin gene–drug link is retained as an explicit
interpretation gap; do not invent a genotype-to-recommendation mapping or infer
a warfarin dose. G6PD candidates retain one/two-copy models and the Variable
phenotype. CYP2D6 remains the existing adjacent assay-limit card. M10.5's
once-per-section prescribing framing is now implemented as separate current context;
see [the section framing contract](pgx_framing.md).

## Source audit and display

The existing complete frozen CPIC v1.60.0 catalog has 2,115 recommendation
rows and 112,820 diplotype mapping rows. All eight authored selectors and their
actual PMID/title bindings were checked against non-null guideline links before
synthetic calling. No source payload or recommendation prose is vendored in
knowledge files. The ClinPGx annotation tables remain frozen source annotations;
they do not replace the CPIC recommendation join or establish a sample phenotype.

The audit used CPIC's [guideline framework](https://www.clinpgx.org/cpic/guidelines)
and the primary [warfarin update](https://pubmed.ncbi.nlm.nih.gov/28198005/).
A gene-drug CPIC level is distinct from a recommendation's classification and
an allele-function row's strength. The cards expose each source field by name.
The warfarin paper requires clinical/genetic inputs beyond this array; the
absence of a VKORC1 lookup in this release is retained rather than replaced by
a guessed reverse-strand genotype key or a dose formula.

Cards remain conditional even for a unique compatible candidate. Source
recommendations that require CYP2D6 or another uncalled gene retain that unknown
condition. Incompatible fully mapped conditions exclude that recommendation;
unmapped alternatives keep it explicitly unassessed. Matching preserves
all conflicting phenotype joins, source activity expressions, allele counts,
drug-specific function/substrate annotations, population fields, comments,
notes, row versions and identifiers. Drug-specific functions are retained as
annotations and never silently substituted into a different lookup method.
Missing guideline URLs or DOI/PMID evidence disable the displayed implication
while retaining the source row and its gap. Clinical population/context limits
are not converted into a measured ancestry match.

The card face states separate counts for conditional and evidence-incomplete
rows, CPIC gene-drug levels,
recommendation classifications and inherited reliability. Rarity keeps the
likely-artifact tier, the approximate 16% benchmark and its heterozygous-chip,
non-personal, non-imputation-validation scope. Low/unknown imputation quality
remains explicit. No M9.13 confidence formula is reused or changed.

Use `genetics pgx calls RUN --gene DPYD --json` for saved calls and guideline
cards, or `genetics runs show RUN --json` for the full bundle. The PGx overview
and each gene page link to saved guideline details. Details retain every
candidate and recommendation, with expandable source evidence and conditions.
Historical runs without guideline cards state that they were not recorded;
no current pack is substituted. Missing prepared references save unavailable
cards. Save and reload validate against the independent native-call evidence
and the frozen catalog, without accessing current caches or the network.

## Acceptance

Complete-source offline acceptance passed in **68.84 seconds**: manifest-bound
source validation, exact public identities/citation joins, fixed-seed synthetic
observations, all eight guideline cards, an independent sample JSON round trip,
and written bundle reload. It uses no personal export and leaves private
synthetic acceptance artifacts in an OS temporary directory outside the repo.
Full dbSNP lint passes **77 cards / 320 template renders / 39 resolved keys**;
synthetic fixtures reproduce byte-identically. Server-rendered HTTP checks
verify the dashboard, PGx overview/gene pages and card details. No interactive
browser visual review is claimed. Validation covers **3,267 unique passing tests**, with five existing Windows
skips. The broad native run passed 3,243 tests and exposed twelve failures in
516.54 seconds: ten assertions still expected format 19, and two static checks
caught the hard-coded publication link. After correcting the assertions and
using the existing validated citation-link view, all **499 affected checks**
pass in 214.27 seconds, and all **78 guideline/static checks** pass in 13.41
seconds. The latter includes twelve schema-version regressions added after
broad-suite collection. This is combined coverage, not a second full-suite run.
All 49 guideline-focused checks pass independently. The privacy selection
passes **248 tests**, with four existing Windows isolation skips; the fifth
broad-suite skip concerns POSIX permission bits. Four strict Windows/Linux ×
Python 3.11/3.13 targets check 214 files. Style, fixture reproduction, full card
lint and whitespace checks pass. Staged privacy scanning passes; no fetched or genotype-derived payload is included.


## Review extension contract (recorded before implementation)

The M10.4 diff review reproduced numeric type substitutions accepted by Python
dictionary equality and incomplete source evidence labelled as conditional.
Guideline display schema **2** requires a usable guideline URL, a titled,
format-valid DOI/PMID citation and nonblank recommendation text before displaying
an implication. Missing or malformed fields remain explicit gaps, with the
complete source rows retained. One invalid publication identifier must not abort
all card assembly when another valid identifier or an explicit gap is available.

New cards use display schema 2; existing display-schema-1 cards reproduce
their frozen original rules. Knowledge schema 5, bundle format 20, public/sample
schema 1 and M9.13 confidence remain unchanged. Numeric validation compares
canonical JSON identities so booleans and floats cannot impersonate integer
fields in either display schema. This is validation tightening for damaged
records, not reinterpretation of healthy saved evidence.


## Reviewed acceptance, 2026-10-15

The [M10.4 diff review](review_m104_session.md) passes the complete native suite:
**3,292 tests**, five existing Windows skips, in **543.30 seconds**. All 103
focused guideline/interface/static checks, four strict type targets, full card
lint, fixtures, style and whitespace checks pass. Full-source seeded-synthetic
acceptance and written reload pass in **109.05 seconds**, including exact
canonical-payload comparison of all eight legacy cards with the original
`0a6f95a` implementation. New cards use display schema 2; historical schema-1
interpretations remain unchanged. M10.5 section framing is now implemented;
M11.1 R/HIBAG detection and bridge is the next open item.
