# ClinVar measurement reliability (M7.2-M7.3)

ClinVar supplies classifications of reference variants. A compatible alternate in an
array export does not establish that variant in the person, and a pathogenic classification
does not supply penetrance, absolute risk or a clinical diagnosis. The frequency screen
is separate from those claims. Every lookup remains visible.

The required frequency source is the publisher-MD5-pinned gnomAD r2.1.1 **GRCh37 exomes**
sites VCF in the manifest (63,145,056,967 bytes). The optional 495 GB genomes release
is separate. Exomes leave many noncoding array loci without usable frequencies.
Local acceptance on 2026-10-05 parsed all **17,209,972 records** and passed source/index
verification plus a synthetic-only offline run through the CLI and dashboard. Exact
digests and index size are recorded in the [handoff](handoff.md).

```text
genetics refs fetch --only gnomad_exomes_r2_1_1_grch37
genetics refs verify --only gnomad_exomes_r2_1_1_grch37 --json
genetics runs clinvar <run-id> --json
```

Fetch verifies the publisher checksum before building `gnomad_frequencies.sqlite`.
This complete public index lives beside the source VCF. It preserves REF/ALT, FILTER,
global and population AF/AC/AN/homozygote counts, and the publisher's AF_popmax and
popmax annotations. The VCF header declares AF/AC/homozygote counts as Number=A and
AN as Number=1; cardinality, counts, rounded AF and the GRCh37 assembly are checked.
Checkpointed SQLite transactions let interrupted indexing resume after gzip replay,
with source identity and a cumulative record checksum checked before reusing rows.
The final index and provenance are checksum-bound and promoted only after completion.

Sample coordinates enter only an in-memory temporary table against a read-only index.
The index never becomes a sample-selected subset. Lookup/calibration snapshots belong
in private run bundles outside the repository.

Only an exact, unique, biallelic A/C/G/T record with FILTER=PASS and usable AF, AC and
positive AN supplies a confidence frequency. Missing entries, unmatched alleles,
filtered entries, duplicate records and unresolved multiallelic/indel observations
stay unknown. An absent record is never assigned zero. A reported zero with positive
AN is a measured reference count and remains distinct from missing coverage.

For a ClinVar alternate, the screen selects its highest available frequency across
global and named gnomAD populations, using AC/AN rather than rounded AF at the threshold.
The index includes the eight major ancestry groups and all nine reported Japanese,
Korean/other East Asian and European subgroups, using sex-pooled ancestry counts.
This deliberately avoids labelling an allele rare solely because pooling diluted a
population-specific frequency. It includes Finnish and Ashkenazi populations rather
than treating the publisher's more selective AF_popmax as the universal maximum.
The selected population and all source counts remain available in JSON and the dashboard.
This population is a conservative rarity-screen context, **not inferred personal
ancestry**; study-to-sample ancestry calibration still belongs to M9.5. Populations with
missing or unusable counts cannot be assessed by this reference.

An unambiguous observed alternate below 0.00001 (0.001%) even at that maximum is
`likely-artifact`. The attached 16% figure is the published confirmation rate for rare
heterozygous SNP-chip calls, not an individual's posterior probability, and not a
calibrated probability for a homozygous, hemizygous or imputed observation.
[Weedon et al., BMJ 2021](https://doi.org/10.1136/bmj.n214).
Above the boundary, `frequency_screen_passed` means only that the empirical rare-call
band was not triggered. It does not confirm a call or establish clinical significance.

M7.3 displays confirmed and unconfirmed percentages before opening a detail view.
For rare unambiguous observations with exact BRCA1/BRCA2 gene identifiers and solely
pathogenic/likely-pathogenic germline classifications, the benchmark is 4.2% confirmed
and 95.8% unconfirmed. That figure pools the study's pathogenic BRCA variants; it is
not an estimate for the below-0.001% frequency bin. Other rare observations retain
the general benchmark. Mixed, uncertain or conflicting annotations do not select BRCA
calibration, and neither somatic nor included-haplotype classifications replace CLNSIG.
Both figures retain the UK Biobank study scope, its 49,908 participants and DOI.
They are not calibrated personal probabilities for this vendor or for imputed,
homozygous or hemizygous observations. The gnomAD screening population is distinct
from the population in which the study benchmark was measured.

Interpretation cards receive the same allele-specific frequencies through the existing
confidence engine. A single population supplies both alleles, REF=1-ALT uses that same
denominator, and selection maximises the frequency of the rarest observed allele across
available populations. Unknown frequency still caps confidence. A known rare allele
cannot evade the gate because its companion's frequency is missing, and imputation
quality cannot upgrade a rare observation out of `likely-artifact`.
When several source rows share a locus, REF frequency is left unknown: gnomAD splits
multiallelic sites, and 1-AF from one split row includes other alternates. The exact
alternate's frequency can still be used without attributing those alternates to REF.

Bundle format **12** records the calibrated ClinVar lookup as schema **4** in
`clinvar.run.json`, with source/index provenance, population counts, screening policy
and reliability. CLI JSON and the dashboard read the same saved snapshot. Formats
1-11 remain readable with their original results and notices; schema-2 snapshots keep
their original generic benchmark, and no saved run is recalibrated against newer
references. M7.4 adds [ACMG gene-list surfacing](secondary_findings.md), preserving
these reliability calculations and keeping clinical reportability separate.
