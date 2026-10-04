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

ClinVar's dated GRCh37 VCF is ready for [M7.1](../../docs/handoff.md). Its existing
post-processing output is a build-anchor table; the runtime ClinVar lookup remains to be
implemented. The roadmap's fetcher resumability debt remains open before M7.2's large
gnomAD exome download.

## Adding a source

Read `genetics/refs/licenses.py` first. A source names a licence id; it does not describe
one, and an id that module does not know refuses to load rather than defaulting to
permissive. Adding a source under an unfamiliar licence means reading the terms and
writing an entry there — which is a diff a reviewer will actually see.

Every URL, size and digest in the manifest was verified against the live server. Nothing
in it was written from memory. Keep it that way: a wrong checksum committed to a public
repo is the same class of error as an invented coordinate (AGENTS.md 6).
