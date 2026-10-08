# Reference data

This directory is nearly empty on purpose.

`manifest.yaml` and `manifest.lock` are committed. **Everything they describe is not**
(AGENTS.md 1.4, 5.5): reference databases are fetched at setup time, never vendored.
Three reasons, and the third is the one that would actually bite:

1. Size. The manifest describes hundreds of gigabytes, including optional sources;
   consult its per-file sizes before fetching.
2. Licences. Several sources may be used but not redistributed, and a public repository
   that vendored them would be redistributing them.
3. Reproducibility. A pinned URL plus a checksum reconstructs the exact corpus a saved
   run was built against, which a vendored copy at an unknown version does not.

`.gitignore` encodes this as `/data/references/**` plus explicit re-includes for the
manifest, the lock, `*.license.txt`, `CHECKSUMS` and this file. Note the shape: it is
written as `dir/**` with a directory re-include rather than `dir/`, because git will not
re-include a file whose parent directory is excluded. Do not "simplify" it.

## What lands here after a fetch

One directory per source id, named exactly as in the manifest:

```
data/references/
├── manifest.yaml                     committed
├── manifest.lock                     committed -- written by the fetcher
├── clinvar_grch37/                   gitignored
├── dbsnp_b157_grch37/                gitignored
└── ...
```

Post-processing outputs that are keyed to *your* array positions do **not** land here.
They go to the cache directory outside the repository, because a gnomAD table subset to
the positions present in a real export is genotype-derived under AGENTS.md 1.1 even though
every value in it came from a public database. See `genetics/refs/postprocess.py`.

## The committed lock records fetched references

`manifest.lock` records what a fetch actually received: the resolved licence for each
source, its obligations, and the sha256 of every file. It is the input to the M15.4
licence audit. It records the bytes received for sources whose publisher offers a rolling
URL without an advance checksum, as well as digests of release-pinned sources.

The lock is already committed from completed fetches. It is reference provenance, not
proof that the payloads exist in another checkout. Use `genetics refs verify` to check
the local files. For an explicitly unpinned rolling source, a fresh fetch can record a
new release; existing local bytes are still checked against their recorded digests.

M7.1 uses ClinVar's dated GRCh37 VCF for runtime lookup. On first analysis it builds
`clinvar_lookup.sqlite` and its checksum/provenance sidecar beside the fetched VCF.
The index contains the complete public reference, including alternate contigs, and
never a sample-selected subset. The existing build-anchor output remains separate.
Personal lookup results are saved outside the repository in `clinvar.run.json`.

M7.2 executes `build_gnomad_frequency_index` after verifying the required gnomAD
exomes download. `gnomad_frequencies.sqlite` indexes the complete public GRCh37
sites VCF, with global and named-population AF/AC/AN/homozygote counts and FILTER.
Its source/checkpoint/index checksums bind reuse to the exact reference, and committed
checkpoints survive an interruption. Queries use memory-only sample coordinates.
No array subset is written here. See [frequency matching and calibration](../../docs/health_frequencies.md)
for missing/filtered records, split loci and the conservative population policy.

M7.4 fetches `acmg_sf_v3_3`: the complete 84-gene ClinGen ACMG SF v3.3 roster and
reporting guidance, under ClinGen's CC0 terms. The rolling API payload is pinned
by size/SHA256, so updates require a reviewed manifest change. It is read offline
without sample-selected reference files. Saved private runs retain the complete
roster and provenance; see [ACMG surfacing](../../docs/secondary_findings.md).

## Download resumability

M8.2 prepares the complete 1000 Genomes autosomal/X VCFs as chromosome-level bref3
panels and extracts all 25 pinned GRCh37 HapMap maps. It never uses a consumer array
marker list or the separate pruned PCA panel. Completed chromosomes have full decoded
round-trip verification, source/tool/runtime identity and atomic resumable checkpoints.
See [imputation-reference preparation](../../docs/imputation_reference.md) for commands,
the Java 11+ converter requirement, X haploid storage encoding and explicit Y/MT limits.
The maps have **3,395,051 rows** across the entire fetched collection.

Publisher-checksummed sources resume with final digest verification, including M7.2's
63 GB gnomAD exomes file. Frozen sources without a publisher digest must explicitly
declare `immutable: true` and a fixed size in the manifest; this is not inferred from
`unpinned_reason` or a dated URL. The 24 frozen 1000 Genomes chromosome files declare it.
Rolling sources, including ClinVar's `variant_summary.txt.gz`, do not.

A digestless immutable transfer keeps a `.part.resume.json` sidecar recording its URL,
declared size, prefix length and SHA256. A retry rehashes the prefix and resumes only
when those match. Missing, changed or damaged provenance restarts the transfer; server
length drift fails. Ctrl-C and short transfers preserve verifiable prefixes, and a
complete verified partial can be promoted without requesting an invalid end-of-file
range. Success and partial cleanup remove the sidecar. This relies on the declared
publisher immutability contract; a local prefix hash is not a publisher checksum.

See the [handoff](../../docs/handoff.md) for full-reference acceptance and the next milestone.

## Adding a source

M9.1 executes `parse_pgs_score_licenses` for `pgs_catalog_metadata`, reading the authoritative
scores CSV without extracting its archive. The derived JSON retains raw per-score metadata,
classified terms and exact input identity, with the shared checksum/provenance sidecar.
`pgs000001_grch37` is the first selected public scoring-file source. Use `genetics pgs inspect`
to validate all rows and their metadata join offline; it computes no personal score.
See [PGS ingestion](../../docs/pgs_ingestion.md).

Read `genetics/refs/licenses.py` first. A source names a licence id; it does not describe
one, and an id that module does not know refuses to load rather than defaulting to
permissive. Adding a source under an unfamiliar licence means reading the terms and
writing an entry there — which is a diff a reviewer will actually see.

Every URL, size and digest in the manifest was verified against the live server. Nothing
in it was written from memory. Keep it that way: a wrong checksum committed to a public
repo is the same class of error as an invented coordinate (AGENTS.md 6).
