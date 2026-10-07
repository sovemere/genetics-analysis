# Full imputation-reference preparation (M8.2)

`refs fetch --only thousand_genomes_phase3_grch37` now prepares the complete
GRCh37 Phase 3 release as one bref3 panel per supported chromosome: 1–22 and X.
It retains every VCF record, allele and reference sample in source order. It accepts
no consumer export, array marker list, PCA subset, MAF threshold or LD pruning.
The original 24 chromosome VCFs and sample panel remain untouched.

## Setup and commands

Install a 64-bit Java **11 or newer** runtime and configure `JAVA_HOME` or `PATH`.
Java 17 is used in CI. The Beagle imputation jar supports Java 8, but the separately
compiled converter and decoder require Java 11; preparation checks this before launch.
[Temurin's installation guide](https://adoptium.net/installation) includes portable
archives and Windows installers.

```text
genetics tools install --only bref3
genetics tools install --only unbref3
genetics refs fetch --only hapmap_genetic_maps_grch37
genetics refs fetch --only thousand_genomes_phase3_grch37
genetics refs verify --only hapmap_genetic_maps_grch37 --only thousand_genomes_phase3_grch37
genetics refs status --json
```

The converter and decoder are pinned independently to `27Feb25.75f`, with download
sizes and SHA256 hashes in `data/tools.yaml`. They are the publisher's
[bref3 utilities](https://faculty.washington.edu/browning/beagle/beagle.html), rather
than the Beagle imputation jar or someone else's prebuilt reference panel. The manifest
sets an 8,192 MiB heap. Custom declarations can change `memory_mb` and chromosome scope.
The committed declaration always includes all 23 supported chromosomes.

This is a large local streaming operation, with conversion followed by full decoding
for verification. It never writes an expanded VCF to disk or sends reference genotypes
to the terminal. Progress exposes chromosome, stage and processed-record count;
diagnostic logs stay in the ignored reference workspace.

## Storage and verification

Within the fetched source directory, `bref3/panel.bref3.json` indexes each chromosome's
`chrN.bref3-work/complete/panel.bref3`, checkpoint, record count, sample count and digests.
Its provenance binds the source release, ordered chromosome source SHA256s and manifest
parameters. Each checkpoint additionally binds converter, decoder and Java identities.

Before publishing a completed chromosome, the decoder reads its entire bref3 file.
The ordered sample header and **every CHROM/POS/REF/ALT/END and GT observation** must
match the input stream. Multiallelic, symbolic and sequence-resolved indel records are
retained. The source and tool hashes are checked again before atomic directory publication.
bref3 is a genotype-reference format, so other INFO/FORMAT annotations are not guaranteed
to survive; they remain in the original source VCF. The
[publisher's format specification](https://faculty.washington.edu/browning/beagle/bref3.24May18.pdf)
describes the stored marker and haplotype representation.

Kernel locks prevent concurrent writers and release after process death. An interruption
leaves an incomplete attempt, which is never treated as usable. Restart repeats that
chromosome from the original input and reuses fully checked completed chromosomes.
A missing final catalog can be rebuilt from valid checkpoints. Corrupt or stale completed
checkpoints fail explicitly; remove only the identified chromosome workspace to rebuild.
Do not splice binary output or reuse an interrupted converter stream.

`refs verify` is read-only. It hashes all catalog companions, validates checkpoint and
source contracts, and reports unbuilt outputs as pending without launching Java. Reuse
requires the same input/parameter contract and current pinned converter/decoder. These
checks attest previously completed full round trips; verification does not decode the
whole release again. `refs status` exposes resumable chromosome workspaces.

## Chromosome X and unsupported scope

The published X VCF switches from phased diploid PAR calls to haploid non-PAR calls
for some reference samples. bref3 stores diploid haplotypes. Preparation explicitly
encodes each haploid allele twice and records the number of doubled calls, preserving
the original source and comparing the decoded panel against this declared encoding.
It rejects missing or unphased calls, rather than discarding records or inventing phase.

This encoding is a storage contract, not a ploidy inference about a consumer.
**M8.3 must partition X PAR/non-PAR analysis jobs** using the existing GRCh37 PAR bounds,
sample QC/ploidy and the matching X/PAR maps. It must not analyze doubled haploid calls
as evidence of diploid homozygosity.

Y is fetched but deliberately not converted: its release has missing haploid calls and
the map collection supplies no Y map. It is not a complete phased, nonmissing Beagle
reference. The catalog states this limitation; Y haplogroup and direct-call analysis
continue through their existing engines. MT is absent from this panel/map collection.
No marker or sample is silently removed to make unsupported chromosomes appear ready.

## Genetic maps

`hapmap_genetic_maps_grch37` fetches the pinned publisher archive
[`plink.GRCh37.map.zip`](https://bochet.gcc.biostat.washington.edu/beagle/genetic_maps/plink.GRCh37.map.zip).
All **25 maps** are retained byte-for-byte: 22 autosomes, X, X_PAR1 and X_PAR2.
Validation checks chromosome labels, four-column PLINK representation, finite
nonnegative/nondecreasing cM values, strictly increasing physical positions and GRCh37
chromosome limits. Missing/duplicate archive members or invalid maps prevent completion.
`maps/index.bref3.json` records companion hashes, sizes and row counts, with source-bound
provenance. There is no constant-rate map fallback.

The archive attributes HapMap Phase II build-35-to-GRCh37 liftOver and corrections to
Adam Auton, and PLINK formatting to Brian Browning. The license registry records the
[NHGRI public-domain statement for HapMap data](https://www.genome.gov/11511175/about-the-international-hapmap-project-fact-sheet)
and attribution to those transforms. The numerical maps are fetched, not vendored;
the archive and README texts also remain uncommitted.

M8.2 prepares references only. M8.3 owns sample harmonization and phasing/imputation;
M8.5 owns quality propagation and M8.6 owns run-bundle provenance. Bundle format 13
and `genetics run` behavior are unchanged by this step.

Full-release acceptance on 2026-10-07 prepared **23 panels with 84,739,838 records and
2,504 samples each**, with identical ordered sample headers and **8,312,115,275 bref3
bytes**. Every chromosome passed full decoding comparison and final source/companion
verification. The complete map collection has **3,395,051 rows**. These are properties
of the fetched public references, not measurements of a consumer genome.
