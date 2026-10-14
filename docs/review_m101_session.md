# M10.1 session diff review

Scope: implementation commit `1065ae9` against `3f8c189`, including source
declarations/licences, PGx ingestion/inspection, the shared publication helper,
tests and next-step documentation. This review uses public reference data and
fabricated fixtures. No consumer export was read.

## Reproduced defects and corrections

1. **Null guideline IDs attributed unrelated publications.**
   `Catalog.inspect` included null IDs from gene/drug pairs in its guideline
   set. That matched every publication with a null guideline ID, regardless
   of citation. CYP2C19 inspection returned 1,095 unrelated publication rows.
   Nulls are now excluded; directly cited allele papers with null guideline
   IDs remain included. The regression binds four independent publication/link
   cases rather than comparing the CLI with its own generated expectation.

2. **Predictable JSON scratch paths could alter unrelated files.**
   M10.1's writer used the shared `_write_json_atomic`, which opened a fixed
   `.part` path for truncation. A pre-existing hardlink made that write change
   an unrelated local file before replacement. The shared helper now creates
   an exclusive temporary file beside the destination, flushes/fsyncs it and
   replaces atomically. Interruption preserves the previous output and removes
   the current temporary file. Existing `*.tmp` ignore rules cover crash debris.
   Payload and provenance hardlink regressions reproduce the failure; an
   interruption/retry regression verifies preservation and cleanup.

3. **COPY byte escapes were treated as Unicode code points.**
   Octal UTF-8 for an accented character decoded to two characters rather than
   one, breaking lossless COPY/INSERT agreement. The parser now decodes the
   completed byte stream as UTF-8 and rejects invalid/oversized byte sequences.
   [PostgreSQL 17's COPY specification](https://www.postgresql.org/docs/17/sql-copy.html)
   defines octal/hex escapes as bytes. Tests cover both forms, mixed literal
   Unicode, malformed sequences and independent full SQL encodings.

4. **Malformed table/lookup and frozen metadata could appear valid.**
   TSV parsing silently accepted unfinished quotes; JSON lookup parsing silently
   overwrote duplicate keys that could change allele counts. Strict TSV quoting
   and duplicate-key rejection now fail explicitly. Required definition/function/
   phenotype labels must be nonempty. Frozen sources require the complete archive
   or release-specific COPY/INSERT file set, real calendar dates and unambiguous
   archive notices. Aggregate source terms cannot waive embedded non-commercial
   or share-alike obligations. Digest-consistent mutations exercise these guards.

5. **Valid nested outputs failed before ingestion.**
   The manifest permits a nested relative output path, but its publication lock
   was opened before its parent existed. The lock now creates that contained
   parent. A declared nested source artifact passes creation, reload and read-only
   verification. The lock remains kernel-owned and exclusive.

The review also corrects a provenance error message. Healthy source/catalog
schema-1 snapshots remain readable; these fixes add validation and correct
inspection/publication behavior without changing normalization or reference
versions. Run-bundle format 18 and M9.13 confidence arithmetic are unchanged.

## Source assumptions checked

All nine complete ClinPGx TSVs accept strict quoting and retain **312,006 rows**.
CPIC's two encodings retain **125,945 rows** across the sixteen selected tables.
The definition/function/phenotype counts and **493/1,210** verified GRCh37 locations
remain unchanged. These are source properties, not chip or sample measurements.

CPIC includes **24 CYP2D6 copy-number function aliases** linked to base definition
IDs. Their different names are intentional, so no name-equality rule is added.
Also, **4,124 diplotype rows** reference labels absent from `allele_definition`;
the affected genes are CYP2D6 and HLA-A/B, all outside M10.2's eight-gene scope.
Every source row remains available; no absent definition is silently synthesized.
"Complete ingestion" means every row in the selected release tables, not that
the source supplies every clinically possible allele or phenotype.

## Validation and handoff

The focused PGx/reference suite passes **158 tests**, including **33 new
regressions**. The complete native suite passes **3,137 tests**, with the five
existing Windows skips, in **486.78 seconds**. All pinned native ROH, Beagle,
bref3 and PGS arithmetic checks are enabled. Four strict Windows/Linux × Python
3.11/3.13 type targets pass (211 files), full dbSNP card lint passes
69 cards/320 renders/39 keys, and fixtures, lint/format and privacy checks pass.

Full-source acceptance passes with networking blocked in **55.06 seconds**:
both complete CPIC dumps reparse and agree with each other and the saved tables;
both source artifacts verify; preparation reuses its verified completion;
all eight gene inspections match independently derived publication links and
gene-scoped counters; and the frozen catalog reloads unchanged. The reference
CLI also returns the published CYP2C19 reference mapping with nine relevant
publication rows, without computing a sample call. Raw source pins, reference
versions and normalization counts are unchanged. Audit files stay ignored.

M10.2 remains the next open item. The [handoff](handoff.md#next-open-step-m102-snp-tractable-diplotype-calling)
starts with a versioned sample-call record and saved-bundle plan, then calling for
the eight tractable genes. Missing markers and phase/ploidy/quality uncertainty
must survive. Use DPYD's actual activity-score semantics, expose VKORC1's absent
phenotype table and retain CYP2D6's existing assay-limit card. The
[PGx source guide](pgx_ingestion.md) records the unchanged reference coverage and
setup commands.
