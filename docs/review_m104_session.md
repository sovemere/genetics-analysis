# M10.4 session diff review

Scope: `3f7f944..0a6f95a`, covering declarative guideline selectors, conditional
CPIC joins, card assembly, frozen bundle validation, CLI/dashboard presentation,
synthetic acceptance and next-step documentation. No personal export is opened.

## Reproduced findings and corrections

1. **Frozen numeric types could be substituted without detection.** The new
   validator compared Python dictionaries, where booleans equal integers and
   integral floats equal integers. Schema version, candidate index, allele count
   and ploidy substitutions all passed the original comparison. Canonical JSON
   identities now distinguish these types, and display-version selection requires
   an actual supported integer. Both display schemas reject altered numeric types;
   disk-read tests also update the outer payload digest before verifying that the
   reader raises the categorical saved-guideline error.

2. **Incomplete source evidence could look usable, or abort the whole card stage.**
   A publication identifier without a title, blank/invalid guideline URL, or absent
   recommendation text still produced a conditional implication. An invalid PMID
   instead raised a citation parser exception during assembly. Five source-level
   reproductions fail before correction. New display schema 2 requires a usable
   HTTPS guideline URL, a titled and format-valid DOI/PMID citation, and nonblank
   recommendation text. Otherwise the source row stays visible with an explicit
   evidence gap and its implication unavailable. One malformed identifier does not
   discard another valid identifier; both the original row and the problem remain
   recorded. Face counts distinguish conditional branches from evidence-incomplete
   rows instead of counting both as usable conditional implications.

The initial nine reproductions all fail against the original code. Twenty-five
new cases cover exact types in both versions, independent bundle reads, missing
source fields, partial identifiers, saved CLI/dashboard parity and byte-identical
bundle files after inspection. Existing source-join, phase, copy-count,
frequency/quality, historical/unavailable and static privacy checks remain active.

## Frozen compatibility

New cards use guideline display schema **2**, an additive change recorded in the
[guideline contract](pgx_guidelines.md#review-extension-contract-recorded-before-implementation)
before implementation. Schema-1 cards reproduce their original evidence rules
and text. Knowledge schema 5, bundle format 20, public/catalog/sample schema 1,
source pins, candidate enumeration and M9.13 confidence stay unchanged.

Complete-source offline acceptance passes in **109.05 seconds** using seeded
synthetic calls. All eight schema-1 cards compare exactly, by canonical serialized
payload, with the original `0a6f95a` module. Both display versions validate, and
new schema-2 cards survive independent sample JSON and written bundle reload.
This uses the complete frozen public source and no personal data. Server-rendered
HTTP checks verify saved interfaces; no interactive browser review is claimed.

## Documentation and next step

M10.5 remains next: a prominent, precise statement that the pharmacogenomics
section is not a prescribing tool, presented once per section/view rather than
repeated as filler on each card. The handoff distinguishes current section
context from frozen sample findings, preserves both guideline display schemas,
and requires saved/unavailable/historical CLI/dashboard parity and filter checks.
The existing CYP2D6 limitation, quantitative measurement reliability and required
candidate/gene/population/clinical conditions remain beside the evidence.

## Validation

The complete native suite passes **3,292 tests**, with five existing Windows
skips, in **543.30 seconds**. All **103 guideline/interface/static checks** pass
in **22.93 seconds**. The full-source comparison and independent reload pass in
**109.05 seconds**. Twenty-five new synthetic cases are included in the full run.

All four strict Windows/Linux × Python 3.11/3.13 targets check 214 source files.
Full dbSNP lint passes **77 cards / 320 template renders / 39 resolved keys**.
Synthetic fixtures reproduce byte-identically; repository lint/format and
whitespace checks pass. Links in all seven updated overview/contract/review
Markdown files resolve locally. The pre-commit hook repeats staged privacy,
fixture, privacy-suite and style checks before publication. No personal export,
fetched payload or genotype-derived output is included in the commit.
