# Array/ClinVar coverage (M7.6)

The `clinvar_array_coverage` card in Physical health describes what the input export
covers in the installed ClinVar release. The same saved counts appear in the ClinVar
dashboard and `genetics runs clinvar <run-id> --json`. No universal array-overlap
constant is used. Coverage is not clinical sensitivity, a count of confirmed pathogenic
findings, or a negative clinical screen when no overlap is found.

## Denominators and source scope

Reference positions are distinct normalized `(chromosome, GRCh37 position)` pairs on
1–22, X, Y and MT. All classifications, conflicts, review levels and VCF FILTER values
remain included. Alternate/unplaced-contig records are excluded from this positional
denominator and counted separately. `M` normalizes to `MT`. Vendor-labelled PAR stays
separate from X and Y; its coordinate convention is not guessed.

Chip positions are distinct normalized positions in this export, including listed
no-calls. Probe aliases count once; the record separately reports positions with
duplicates and the number of extra probes. The export cannot tell us about probes
omitted by its vendor, so this measures the supplied export, not an inferred complete
chip design.

Two fractions are saved, each with its numerator, denominator and fractional value:

- **Reference-position coverage:** overlapping positions / reference positions.
- **Chip-position annotation share:** overlapping positions / chip positions.

A missing source has unknown overlap and fractions, while chip counts remain available.
A reference containing only alternate/unplaced contigs has `empty_reference` status,
with an undefined reference-position fraction rather than division by zero. A valid,
nonempty primary reference with no chip overlap has `zero_overlap` status. An actually
empty index, inconsistent source record count or malformed/empty input fails explicitly.

## Positions, observations and variants

`called_positions` means at least one probe at the position has a non-no-call observation.
It can include an indel, a contradictory haploid observation or conflicting probes;
it does not mean the allele has resolved. The exclusive position-state partition, in
priority order, is conflicting probes, no-call, indel-excluded, ploidy-unresolved,
and called SNP. Both the chip and its ClinVar overlap carry these counters.

Reference variants are distinct `(chromosome, position, REF, individual ALT)` tuples.
Multiple alternate alleles expand into separate variants; identical tuples across
records count once. ALT `.` is not a variant. All reference records and their annotations
remain present in the lookup. The separate matchable-SNV reference count includes only
biallelic A/C/G/T single-base records and is not a sensitivity denominator.

Allele-resolved positions and variants use existing `alternate_observed` and
`reference_only` lookup states, then conservatively exclude A/T and C/G strand ambiguity
and unresolved non-PAR sex-chromosome ploidy. Other strand-compatible matches assume
the vendor's forward-strand contract. Coordinate-defined PAR follows shared GRCh37 QC
boundaries. Unknown sex inference leaves non-PAR X/Y unresolved. Indel codes, incompatible
alleles, multiallelic aggregate annotations and duplicated reference-allele ambiguity
do not count as resolved. Existing lookup annotations are retained, including those
excluded from this descriptive count. Reference-only matches are reported separately
from observed alternate matches; neither establishes disease status.

Rare-call reliability and scoped PPV remain separate and unchanged. An allele-resolved
alternate can still be `likely-artifact`. ACMG gene-list overlaps have their own view;
the all-ClinVar coverage card does not measure ACMG whole-gene coverage or reportability.

## Saved contract

Bundle format **13** stores lookup schema **5**, with `lookup_schema_version` preserving
the underlying lookup/frequency/ACMG generation and a `coverage` record. The coverage
record saves the counting policy, chip/overlap/reference counters, both fractions,
QC ploidy assumption, and the exact ClinVar source version, build and SHA256.
The computed card saves the same coverage record. Its limited reliability describes
the absence of calibrated clinical sensitivity, not uncertainty in integer arithmetic.

Readers validate counter relationships, fractions, provenance, overlapping observations
and card/lookup equality using the snapshot. They never read today's reference caches
or recount on opening a run. Formats **1–12** retain their original meanings and do not
gain invented historical coverage. No new output filename is introduced: coverage stays
in the existing gitignored `clinvar.run.json` and `cards.run.json` payloads.

The reference-annotation distinction is supported by [ClinVar's description of its
classification domains](https://doi.org/10.1093/nar/gkae1090). The chip-call limitation
is supported by [Weedon et al.](https://doi.org/10.1136/bmj.n214); that study does not
validate positional coverage as a clinical screen.
