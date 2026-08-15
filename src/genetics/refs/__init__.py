"""Reference data: the manifest, the licence gate, and the fetcher (roadmap M2).

AGENTS.md 1.4 and 5.5 set the shape of this package: reference databases are **fetched,
never vendored**. What the repository commits is the *description* of the corpus -- URLs,
versions, checksums, licences -- and what it never commits is a byte of the payload.

Three modules, in dependency order:

* :mod:`genetics.refs.licenses` -- what each licence permits. Consulted, never authored
  per-source; see its docstring for why that distinction is the whole point.
* :mod:`genetics.refs.manifest` -- the schema for ``data/references/manifest.yaml`` and
  its validation.
* :mod:`genetics.refs.fetcher` -- resumable download, checksum verification, and the
  licence gate that decides what may be fetched at all.
"""
