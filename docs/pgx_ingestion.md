# Pharmacogenomics reference ingestion (M10.1)

M10.1 ingests public references and exposes offline inspection through one shared
library. It reads no consumer export and calls no sample diplotype. M10.2 owns
calling; M10.4 owns guideline cards. Run bundles remain format 18 and the M9.13
confidence policy is unchanged.

## Setup and inspection

```text
genetics refs fetch --only pharmgkb --opt-in pharmgkb
genetics refs fetch --only cpic --opt-in cpic
genetics refs verify --only pharmgkb --only cpic --json
genetics pgx prepare --json
genetics pgx inspect --json
genetics pgx inspect --gene CYP2C19 --allele "*2" --json
genetics pgx inspect --gene CYP2C19 --diplotype "*1/*2" --json
```

Preparation also requires the existing complete `dbsnp_b157_grch37` variant and
merge indexes. Inspection accepts `--reference <frozen-public-reference.json>`
for an explicit snapshot; the default also verifies current manifest/lock bindings.
The diplotype option looks up a **reference label**, not a person's genome. It
retains every matching source row, including conflicting and missing mappings.

## Source and licence audit, 2026-10-14

The existing `pharmgkb` and `cpic` manifest IDs are reused. No reference payload or
definition table is committed. Complete sources and derived indexes stay in the
ignored `data/references/` tree. `manifest.lock` records download hashes, terms
and opt-ins; the parsers make no network calls.

ClinPGx's five ZIPs contain nine annotation tables. They do **not** supply a
complete star-allele definition corpus. The actual complete definitions,
allele functions and phenotype relationships supplied by the pinned release are
in the CPIC database. Complete ingestion does not establish clinical completeness.
[CPIC's data model](https://github.com/cpicpgx/cpic-data) describes the source
tables and [release history](https://github.com/cpicpgx/cpic-data/releases)
confirms that v1.60.1 is application-only; v1.60.0 remains the pinned dump.

Four ZIPs carry October 5, 2026 **BY-NC-SA 4.0** notices. Clinical annotations
remain July 5, 2025 **BY-SA 4.0**. The manifest previously described all of them
as BY-SA. The combined source is now conservatively non-commercial/share-alike,
and each archive retains its own notice, date and optional version text. The
live [ClinPGx site](https://www.clinpgx.org/chemical/PA449211/prescribingInfo)
also states BY-NC-SA. The JavaScript-only policy could not be read in the
unavailable built-in browser; no browser verification is claimed.

[CPIC's release licence](https://github.com/cpicpgx/cpic-data/blob/v1.60.0/LICENSE.md)
dedicates curated content to CC0 but additionally binds database/API users to
ClinPGx policy. The database gets a separate conservative licence classification
and explicit `cpic` opt-in, with the scope conflict retained as `needs-review`
for M15.4. This does not classify every CPIC resource as BY-NC-SA. Both sources
remain free to download, optional, and unvendored.

## Reference contract

PGx source schema **1** has two artifact kinds: `pgx_annotations` and `pgx_cpic`.
Each records the source ID/release/licence, complete file identities, table
contents and verified row counts. Existing provenance schema 2 binds these
outputs to their exact inputs and transform parameters.

`parse_pharmgkb_annotations` replaces the pending generic `extract_zip` step
for this source. It validates member paths, case-insensitive duplicates,
symlinks, encryption, uncompressed size, CRCs, release notices, licence notices,
table names, headers and row widths. Tables are read directly from ZIP members;
no archive path is extracted. Documentation is CRC-checked but not interpreted.

`parse_cpic_database` reads sixteen complete tables from both the COPY and
INSERT dumps, then compares row multisets independently. SQL is never executed:
there is no PostgreSQL dependency. Source scalars stay strings/null; escapes,
quoted text, activity-score expressions, clinical substrate context, citation
arrays and version fields retain their original meanings. Primary identities,
definition/location/function joins and the diplotype → function-lookup →
phenotype chain are checked. Required labels are nonempty and duplicate lookup
JSON keys are rejected. COPY octal/hex byte escapes decode as UTF-8, preserving
multibyte text. Missing functions/mappings stay explicit. CYP2D6's copy-number
function aliases legitimately reference base definition IDs; names are retained.

Preparation writes `cpic/pgx_reference.json`, catalog schema **1**. It freezes
all selected CPIC tables, the complete ClinPGx variant table and archive
metadata, scoped public dbSNP proofs/resolutions, normalized locations and all
definitions. Readers recompute normalized states from the frozen evidence,
check exact numeric types and source/provenance consistency, and require the
output checksum. Explicit snapshots remain readable without stage caches;
default reads additionally check declared releases/licences/hashes and opt-ins.
Both source and frozen readers require the complete release-specific file set,
valid archive dates and notices, and aggregate terms that retain embedded obligations.

Publication uses kernel-owned Windows/Linux locks and atomic file replacement
through exclusive temporary files; a pre-existing scratch hardlink cannot be
truncated. Nested declared outputs create their contained parent before locking.
Interruption leaves a verifiable completion or an incomplete artifact that
verification refuses; retry restarts the small transform. Valid completions
are reused. Input drift, changed parameters, damaged sidecars and incompatible
snapshots cannot be reused as healthy references.

Gene/allele inspection returns directly cited papers and papers from actual,
non-null gene guideline links. A missing guideline ID never associates unrelated
publications. The [M10.1 diff review](review_m101_session.md) records the reproduced
defects, regressions and full-source checks.

## Coordinate and definition limits

Coordinates use verified chromosome accessions, not rsID-only matching. The 24
primary accession/version pairs were checked against NCBI's
[GRCh37.p13 assembly report](https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.25_GRCh37.p13/GCF_000001405.25_GRCh37.p13_assembly_report.txt)
and
[GRCh38.p14 assembly report](https://ftp.ncbi.nlm.nih.gov/genomes/all/GCF/000/001/405/GCF_000001405.40_GRCh38.p14/GCF_000001405.40_GRCh38.p14_assembly_report.txt).
CPIC's genomic HGVS position must agree with its coordinate and gene accession.
GRCh38 SNPs require exact source and GRCh37 forward-strand HGVS synonyms in a
ClinPGx variant record, followed by independent dbSNP position/REF/ALT agreement.
Original and current merged rsIDs survive alongside the primary position/allele key.
No coordinate offset, strand complement or speculative liftover is applied.

Missing build/rsID/mapping, conflicting coordinates, ambiguous dbSNP matches,
indels, IUPAC bases and structural/CNV alleles remain explicit reference states.
Duplicate named definitions or incompatible required alleles at one locus are
conflicts. Sparse definitions retain their listed constraints; unspecified or
untyped markers cannot be filled as reference. CYP2D6 remains outside calling
scope regardless of a definition's SNP content.

## Complete-source acceptance and M10.2 handoff

Full ingestion retains **312,006 ClinPGx rows** and **125,945 CPIC rows** across
the sixteen required tables. The CPIC encodings agree, with **1,354 definitions**,
**1,378 function records**, **1,210 locations**, **101 phenotypes**, **208 function
lookups**, **112,820 diplotype rows** and **1,155 publications**. Raw and derived
source verification passes with no pending steps.

The prepared reference resolves **493 locations** to verified GRCh37 SNP keys.
Remaining states are 405 missing cross-build mappings, 186 missing rsIDs,
104 unsupported representations and 22 unknown source builds. These are
properties of the public references, not measured consumer-chip coverage.

| M10.2 gene | Source definitions | Fully resolved SNP definitions | Source diplotype rows |
|---|---:|---:|---:|
| CYP2C19 | 49 | 4 | 666 |
| CYP2C9 | 94 | 47 | 2,850 |
| VKORC1 | 2 | 2 | 0 |
| SLCO1B1 | 47 | 16 | 741 |
| TPMT | 49 | 31 | 1,225 |
| DPYD | 84 | 80 | 3,570 |
| NUDT15 | 23 | 3 | 276 |
| G6PD | 187 | 15 | 17,765 |

VKORC1 has no phenotype/function-lookup rows in this release. Do not invent a
metabolizer phenotype for it; inspect its source guideline/recommendation
contract at M10.2/M10.4. DPYD uses `ACTIVITY_SCORE`; G6PD source diplotype counts
do not establish sample sex/ploidy. CYP2C19/G6PD and other partial definitions
must remain candidates with explicit unresolved constraints. A reference allele
must never become a default merely because a chip omits its defining markers.

M10.2 now has a separate [versioned sample-call contract](pgx_calling.md) and
additive bundle format 19, with the previous confidence method unchanged.
Calling is restricted to the eight listed genes and retains phase, coverage,
rare-call and structural uncertainty. The reference artifact's
`sample_calling_implemented: false` continues to describe reference-only
inspection; sample results live in the separate private contract. Reuse the
existing `cyp2d6_structural_variation` card in M10.3 rather than creating a duplicate.

Synthetic validation covers independent SQL encodings, unsafe archives,
malformed rows/joins, ambiguous builds/alleles, licence gates, checksum/source
drift, lock exclusivity, interrupted publication/reuse, missing/conflicting
definitions/phenotypes and frozen CLI parity. **3,104 unique checks pass**, with
five existing Windows skips: the broad native run passed 3,091 tests, its one
extra native PGS skip subsequently passed, and all 89 final PGx tests pass,
including twelve added after broad collection. All four strict type targets
(211 files), full card lint (69 cards/320 renders/39 keys), fixtures and style
pass. Full-source prepare/reuse, eight-gene inspection and frozen reloads pass
with networking blocked in 39.98 seconds. No personal export was opened.

The subsequent [diff review](review_m101_session.md) adds 33 regressions and
passes **3,137 native tests**, with five existing Windows skips, in 486.78 seconds.
Strict four-way typing, complete card lint, fixtures, style and privacy checks pass.
Full-source offline reparse, source verification, corrected publication joins,
verified reuse and frozen reloads pass in 55.06 seconds. Existing schema-1 healthy
snapshots and source pins remain valid; no sample-call or run-bundle change is made.
