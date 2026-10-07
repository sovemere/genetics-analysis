# Session diff review: M8.6

Reviewed `54eb85d..f49433d` on 2026-10-07, following the changed code into its
readers and callers: full dosage/provenance publication, format-16 validation,
shared saved iterators, CLI/dashboard views, deletion recognition, historical
fixtures, privacy ignores and CI hygiene. No personal export was opened. New
inputs are generated from the existing synthetic helpers.

## Findings and fixes

1. **A shared locus could hide an unmatched card or marker.** Full-record validation
   counted any matching allele identity once per locus. Another claim at that locus
   could name an absent allele identity and borrow the first claim's successful match.
   Validation now requires exactly one matching record for each card/marker entry.
   Regressions cover scalar cards and multi-marker entries, accepting legitimate
   shared records before rejecting the second unmatched identity.
2. **Boolean storage values passed native record validation.** Python equality lets
   booleans compare equal to integer indices and numeric dosages. The biological
   vectors were strictly validated, but their storage companions relied on equality.
   Both storage vectors now receive explicit type validation. Two regressions reject
   boolean substitutions that previously passed.
3. **An unknown stage region escaped the publication error boundary.** Region lookup
   raised `StopIteration`, which saved reading caught but publication did not. The
   publisher now shares the reader's categorical exception coverage, including
   `IndexError` and `StopIteration`. A regression verifies a private `BundleError`
   and an empty destination store after rejection.

All five regression cases failed against the reviewed implementation before the
fixes. These tighten existing format-16/schema-1 contracts without changing payload
meanings. Atomic copying, source/cache independence, native per-ALT quality,
historical formats, CLI/dashboard snapshot use and privacy patterns remain covered.
The review does not measure biological imputation accuracy or calibrate rare calls.

## M8.7 boundary

M8.7 remains next: demonstrate that known rare observed alleles cap imputed
findings regardless of DR2 or literature strength. The [handoff](handoff.md#m87-implementation-handoff)
specifies frequency boundaries, native sources/ploidies, incomplete frequency
coverage, multi-marker inheritance and saved front-end parity. ClinVar retains
original-array input; M9 owns scores, coverage and ancestry portability.

## Validation

**2,529 tests passed, five existing Windows skips**, with pinned native ROH,
Beagle, converter and decoder enabled. All 58 snapshot tests pass, including
the five new regressions. Strict mypy passes on Windows/Linux and Python 3.11/3.13;
ruff and formatting pass. Synthetic fixtures reproduce byte-for-byte. Full card
lint passes: 51 cards, 268 template renders and 35/35 dbSNP marker references.
The pre-commit scanner and privacy hook remain required before publication.
