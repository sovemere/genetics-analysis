# Reference data

This directory is nearly empty on purpose.

`manifest.yaml` and `manifest.lock` are committed. **Everything they describe is not**
(AGENTS.md 1.4, 5.5): reference databases are fetched at setup time, never vendored.
Three reasons, and the third is the one that would actually bite:

1. Size. The corpus declared in the manifest totals roughly 604 GB.
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

## The lock is not committed until you fetch

`manifest.lock` records what a fetch actually received: the resolved licence for each
source, its obligations, and the sha256 of every file. It is the input to the M15.4
licence audit, and it is what pins the sources whose publisher offers only a rolling
"latest" URL that cannot be checksummed in advance.

It is deliberately absent from this repository until the owner runs a real fetch. A lock
committed from someone else's machine would assert facts about a download that never
happened here.

## Adding a source

Read `genetics/refs/licenses.py` first. A source names a licence id; it does not describe
one, and an id that module does not know refuses to load rather than defaulting to
permissive. Adding a source under an unfamiliar licence means reading the terms and
writing an entry there — which is a diff a reviewer will actually see.

Every URL, size and digest in the manifest was verified against the live server. Nothing
in it was written from memory. Keep it that way: a wrong checksum committed to a public
repo is the same class of error as an invented coordinate (AGENTS.md 6).
