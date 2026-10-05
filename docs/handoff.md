# Handoff: M7.2 gnomAD frequency gating

As of 2026-10-05, M0?M6 and **M7.1** are complete. Read [AGENTS.md](../AGENTS.md)
first, then [the roadmap](../phase1_roadmap.md); its checklist is authoritative.

## Completed in this handoff

M7.1 builds a complete reference-only SQLite index from the pinned ClinVar GRCh37
VCF, with source checksum, build/date validation and an index checksum sidecar.
The local acceptance indexed **4,461,445 public records** from the 2026-08-04 VCF.
Alternate/unplaced contigs are retained without mapping them onto primary chromosomes;
no-alternate, indel and symbolic records cannot supply an allele match.

Lookup joins normalized sample loci and checks REF/ALT compatibility. Original calls,
source variation/allele identifiers, all INFO annotations, germline classifications,
review statuses, conditions and source provenance survive in the saved snapshot.
Missing, incompatible, excluded and ambiguous results stay explicit. Duplicate probes
cannot select a preferred call; duplicate allele records retain every classification
as ambiguity. Multiallelic aggregate annotations are not assigned to an alternate.

New runs use bundle format **7**, adding private `clinvar.run.json`. Formats 1?6
remain readable with ClinVar marked not recorded. `genetics runs clinvar <run-id> --json`,
whole-run JSON and the dashboard expose the same snapshot. These are
uncalibrated reference annotations, not confirmed personal findings. Source payloads,
the index and personal results must never be committed.

The download debt is resolved. `RemoteFile.immutable` explicitly distinguishes frozen
releases from rolling files; it is never inferred from `unpinned_reason`. The 24 frozen
1000 Genomes chromosome files declare it. Digestless frozen transfers need a fixed
size and a matching URL/size/prefix-hash sidecar before resuming. Changed or damaged
provenance restarts, length drift fails, interrupted transfers preserve valid prefixes,
and complete verified partials avoid end-of-file Range requests. Rolling files still
restart. Publisher-checksummed sources retain their final digest verification.

## Next: M7.2

Wire gnomAD allele frequencies into the existing confidence engine. Rarity lowers
confidence regardless of direct or imputed call source; retain missing-frequency and
ancestry context instead of treating them as reassurance. Low-confidence findings
remain visible. M7.3 owns explicit frequency-band PPV presentation; M7.4 owns ACMG
surfacing, M7.5 common-variant health cards and M7.6 coverage honesty.

The required source is `gnomad_exomes_r2_1_1_grch37` in the manifest: a **63 GB**
GRCh37 v2.1.1 sites VCF, already publisher-MD5-pinned. It was not installed at this
handoff. Its download uses the existing digest-verified resume path:

```text
genetics refs fetch --only gnomad_exomes_r2_1_1_grch37
genetics refs verify --only gnomad_exomes_r2_1_1_grch37 --json
```

Check manifest-declared sizes and disk preflight before fetching. Reference-only full
indexes may live beside fetched sources; anything selected using a personal export
belongs outside the repository. Stream gzip on Windows or use pinned native tools;
do not introduce htslib dependencies. Keep the CLI and dashboard on one engine.

The source-license audit remains M15.4 work. Study-to-sample ancestry mapping remains
M9.5 work. M6's absent chip/population calibration stays attached to its cards. None
of these authorizes loosening saved-result validation or silently reinterpreting runs.

## Validation

M7.1 has synthetic matching, malformed-reference, duplicate/multiallelic/conflict,
provenance, snapshot integrity, compatibility and CLI/dashboard parity checks. Download
regressions cover short transfers, Ctrl-C, prefix damage, changed provenance, ignored
ranges, declared length drift and rolling-source isolation. The full reference was
parsed locally without accessing a personal export.

The full suite passed **1,949 tests, five existing Windows skips**, with pinned native
ROH tests enabled. After adding dashboard pagination, **245 ClinVar/web tests passed**.
Ruff, formatting, strict mypy, fixture reproduction and full card lint passed; the lint
checked 47 cards, 218 template renders and 31 dbSNP keys.

Run the repository checks for the next change:

```text
ruff check .
ruff format --check .
mypy
genetics fixtures --check
genetics cards lint --json
pytest -q
```

Set `GENETICS_ROH_TEST_TOOLS` to the pinned tools directory for native ROH tests.
Before committing, inspect `git status --porcelain` and run `genetics check-staged`;
leave the privacy hook enabled. CLI work commits and pushes directly to `main`.
