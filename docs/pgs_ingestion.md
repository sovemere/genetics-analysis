# PGS scoring-file ingestion (M9.1)

M9.1 reads public reference weights and authoritative per-score terms. Inspection
computes no personal score. [M9.2 now computes private PLINK sums](pgs_scoring.md);
percentiles, outcome calibration and ancestry adjustment remain M9.4–M9.6.
No bundle-format change is introduced.

## Acquisition and inspection

Use the existing manifest, fetcher and lock; payloads and derived indexes are ignored:

```text
genetics refs fetch --only pgs_catalog_metadata
genetics refs fetch --only pgs000001_grch37
genetics refs verify --only pgs_catalog_metadata --json
genetics refs verify --only pgs000001_grch37 --json
genetics pgs inspect data/references/pgs000001_grch37/PGS000001_hmPOS_GRCh37.txt.gz --json
```

The first fetch executes `parse_pgs_score_licenses`, reading exactly one regular
`pgs_all_metadata_scores.csv` member without extracting the archive. It writes
`pgs_score_licenses.json` with a checksum/provenance sidecar. Reuse and verification
bind it to the exact input, transform and parameters; a bad index cannot report as
verified. A fresh fetch rebuilds an invalid or stale derived index.

Additional selected scores should have explicit manifest entries with their actual
URLs and measured identities. Do not bulk-download the catalogue or template URLs
without checking them. PGS000001 is the first parser-acceptance reference, not a card
selection or a claim that it is the best score for its phenotype.

`pgs inspect` is offline. It exhausts the streaming parser before returning a successful
summary. `--metadata` accepts an explicit metadata archive or a provenance-validated
derived index; its default index is additionally bound to the manifest and lock.
`--pgs-id` asserts the expected identity, and `--build` asserts the effective coordinate
build (default GRCh37). JSON includes original headers, column definitions, raw metadata,
file hashes/sizes, licence status and row-feature counts, never a computed personal score.

## Licence authority

Join the scoring header's PGS ID to the metadata CSV's `License/Terms of Use` column.
Neither the collection-level permission nor the scoring header can override that row.
Raw terms and every metadata column remain available for later evidence/calibration work.

Complete reviewed EBI-default and supported Creative Commons wording is classified
using the licence registry. Restricted CC terms stay flagged with their obligations.
Unfamiliar bespoke academic/research/re-identification wording remains `unknown` and
requires review; familiar licence text embedded in additional conditions is insufficient.
Empty terms are `missing`; repeated score rows are `ambiguous`, even if their terms match.
No historical count of licence values controls recognition.

`ScoreMetadata.license.require_usable()` refuses restricted scores by default. The
repository's explicit restricted-source opt-in can be passed to this API; it cannot
turn unknown, missing or ambiguous terms into permission. Inspection itself reports
these states without computing a score. M9.2 must call this gate before computation.

## Parser contract

The parser supports the current official **format 2.0**, plain UTF-8/BOM or gzip,
with streaming rows. Other formats fail explicitly. It checks unique header/column
fields, score identity, declared build, metadata count/build agreement, field counts,
finite weights, positive positions/ratios, model flags and the final declared row count.
Errors name a category and row number without echoing input rows.

Harmonized coordinates use `hm_chr`/`hm_pos` and `HmPOS_build`, while original coordinates
and build remain intact. Partial author coordinates can accompany valid harmonized
coordinates. An unresolved locus stays unresolved; rsIDs are retained as secondary
identifiers, never converted to coordinates by assumption. Alleles are not flipped,
inferred, sorted into genotypes or interpreted as REF/ALT at this stage.

All columns survive, including signed effect weights, weight type, author ratio fields,
unknown annotations and dosage-specific weights. Haplotype/diplotype, interaction,
dominant/recessive, special-calling, conditional-inclusion, unresolved-indel, non-SNV and
harmonization-mismatch features remain explicit. Compound coordinate encodings outside
the supported location vocabulary fail rather than being flattened into a SNP.
Presence of parsed weights does not establish that M9.2 supports that model.

`ScoringFile.iter_variants()` binds iteration to the original file fingerprint and
validates the final count and unchanged bytes on exhaustion. Consumers must exhaust
and validate the stream before publishing a result; early termination is not acceptance.
Raw metadata, weights and build identities must accompany any later saved score.

## Acceptance and next boundary

On 2026-10-08, the fetched metadata archive contains **6,991 scores**: 6,951 recognized
permissive, 31 recognized restricted and nine unrecognized bespoke-term records.
These are properties of that public reference release, not personal measurements.
The archive is 4,755,134 bytes, SHA256
`dfa7ebe71d46b0bcaf3239e01b99ca232ea261da7be7416be6f52133c4d80b9a`.
The GRCh37 PGS000001 file is 3,276 bytes, SHA256
`5a3069e1a1844df02f3d24e889f97dfad03ee0c40888fc5ecf5f44dc5c36ffc3`,
and parses **77 rows**. Neither payload is committed; the lock records both identities.
Tests fabricate reference shapes and block networking; no reference download belongs in CI.

The full native suite passes **2,660 tests, five existing Windows skips**, with pinned
tools and Java 17 enabled. Sixty-nine new synthetic cases cover malformed rows and
weights, identity/build/count conflicts, licence authority and opt-in boundaries,
special-model preservation, changed sources, corrupt/stale index verification and
repair, CLI summaries/errors and privacy ignores. All four strict Windows/Linux ×
Python 3.11/3.13 type targets, lint/format, fixture reproduction and full card lint pass
(51 cards, 268 renders, 35 dbSNP marker references). CLI/API equality against both
complete public references passes with the in-process network guard enabled.

M9.2 retains native effect-allele dosage/quality, checks score-specific permission and
model support, uses explicit PLINK sum/missing-data behavior and verifies scoring with
synthetic arithmetic. Do not scale dosage by DR2 or filter low-quality observations.
Before-imputation coverage still needs original-array observations or a saved coverage
record: format-16 stage-direct dosages cannot reconstruct the complete chip.
Distributions and AADR/study-ancestry portability remain M9.4–M9.5.

Sources: [official scoring specification](https://www.pgscatalog.org/downloads/),
[Catalog author restrictions](https://www.pgscatalog.org/about/),
[EMBL-EBI terms](https://www.ebi.ac.uk/about/terms-of-use/).
