# Release-gate audits that need no real file (before M15.1)

Working file and to-do list for scope 2 of the
[project review](handoff.md#project-review-before-m151): the M15.3, M15.4 and M15.6 audits,
done before M15.1 because none of them opens the real export. Started 2026-11-21 at
`2109b22`. The rules are [scope 1's](review_project_engine.md#rules-for-this-review): one
item at a time, fix before M15.1 whatever would make the run wrong or leak, record the rest,
and write each decision down with its reason.

Every input is synthetic, fabricated or public. No personal export and no saved real run was
opened. Where a scan had to look inside a committed file, it printed paths, pattern names,
identifiers and counts, never an allele.

## To-do

- [x] **M15.3 Privacy.** `git log --all` for any genotype-derived blob ever committed;
  `.gitignore` re-verified against every path the app writes.
- [ ] **M15.4 Licences.** `manifest.lock` reviewed; nothing non-permissive vendored;
  per-score PGS licences honoured.
- [ ] **M15.6 Citations.** Every shipped card's DOI, PMID or accession resolves.

## M15.3 Privacy (closed 2026-11-21)

### History

**Scanned:** every blob introduced by any commit on any ref, 2,280 blobs at 449 paths, each
read from git rather than the working tree. Each was checked by name against the guard's
`FORBIDDEN_NAMES`, by content with `privacy.find_genotypes` (including the pattern P1 below
adds), and for four shapes a run writes that the guard does not look for: a VCF data line
with a `GT` call, a PLINK `.bim` row, a quoted `genotype` field holding a call, and a vendor
export header line.

**No genotype-derived blob was ever committed.**

- No path ever committed matches a forbidden name, and none is ignored under the current
  `.gitignore` (`git check-ignore --no-index` over every path in history). No binary or
  undecodable blob was ever committed.
- The only genotype-shaped content outside the fixtures is in two August versions of
  AGENTS.md (the §2 format example, `rs1000001` and `rs1000002` at invented positions,
  written with real tabs before `<TAB>` replaced them), and fabricated rows in
  `tests/health/test_frequencies.py` and `tests/ancestry/test_haplogroup.py` (`rs900000001`,
  `v100`). The vendor-header hits are AGENTS.md's generic first line of the format.
- **Fixtures:** three commits ever changed `tests/fixtures/synthetic/`, each together with the
  generator. Each was checked out and `genetics fixtures --check` run against its own
  generator: all three versions regenerate byte for byte.
- **Commit messages** across all refs: no genotype shape. Every author and committer address
  is a noreply address.

### Where the app writes

**Static:** every write site in `src/genetics` outside `testing/` was traced to its
directory. Personal data is written only under `cache_dir()`, `runs_dir()`,
`run_parts_dir()` or `run_checks_dir()`, all inside `user_data_dir()`, or to a path the user
chose, and each chosen path is refused inside the checkout (`roh --output`, `impute --out`,
`pgs score --output`, the PLINK, Beagle and HIBAG workspaces); no caller passes
`allow_in_repo=True`. Reference data goes to `data/references/`, ignored wholesale; outputs
keyed to array positions go to the cache, per `data/references/README.md`. The committed
`manifest.lock` holds public URLs, licences and digests only, and no local path.

**Dynamic:** the full suite (4,469 passed) was run in this checkout between two snapshots of
`git status --porcelain --ignored --untracked-files=all` and a file-modification scan. It
created or changed no file in the checkout outside `__pycache__`.

The existing `test_gitignore_covers_every_writable_path` holds the declared locations; the
findings below are the two places that were not held. Both are P2 under scope 1's scale, a
rule held for one route only: neither leaked anything, and either could have.

- **P2, fixed: a platform data directory inside the checkout was honoured.** `user_data_dir`
  refused `GENETICS_DATA_DIR` inside the repository but not the default it falls back to,
  `LOCALAPPDATA` (Windows), `XDG_DATA_HOME` (Linux) or the home directory. A sandbox that
  points one of them at the working directory is ordinary, and one did here on 2026-10-16:
  the app made `.sandbox_localappdata/genetics-analysis/` inside the checkout and wrote its
  cache there. What it wrote was public (polygenic reference distributions from 1000
  Genomes) and is ignored by `*.gz`, but a run bundle under it, `runs/<id>/cards.json`,
  matches no ignore rule and would have been committable.
  **Decision:** the default gets the same refusal as the override, naming the variable and
  `GENETICS_DATA_DIR` as the way out. Every caller already handles `UnsafeDataDirError`.
  Rejected: an ignore rule for `.sandbox_localappdata/`, which covers one sandbox's name and
  not the next. Tests: the default inside the repo is refused for every derived path; one
  outside it is honoured.
- **P2, fixed: the content scan could not see a genotype in JSON or a `dict` repr.**
  `KEYED_FIELDS` needs a key's name to touch its colon (`rsid=`, `rsid:`), and JSON puts a
  quote between them, so `{"rsid": "rs…", …, "genotype": "AG"}` matched no pattern. That is
  the shape `genetics runs card --json` prints (the identifier in `variant`, the call in its
  sibling `match`), so pasting an agent's output into a doc or a test passed the pre-commit
  hook, the repo-hygiene test and `assert_no_genotype`. Nothing in history has this shape
  except the fabricated test rows above.
  **Decision:** `privacy.QUOTED_KEYED_FIELDS`: a quoted `rsid` or `observed_rsid` holding an
  identifier and a quoted call key (`genotype`, `observed_genotype`, `a1`/`a2`,
  `allele1`/`allele2`) holding one or two allele letters, within 600 characters in either
  order. The window crosses braces because the saved record nests the two in sibling
  objects. A card's `alleles` list is not a call key: it is the reference's, not the
  person's. On the current tree it matched one file, the two fabricated rows in
  `test_frequencies.py`, now built from named constants. Tests: compact and indented JSON and
  a `dict` repr of a saved marker record, quoted `a1`/`a2`, and three non-matches (a card's
  reference alleles, a null call, a call with no identifier).
- **Recorded, no change:** `genetics fixtures --out-dir` writes anywhere, including the
  checkout; what it writes is synthetic by construction.

**Not read:** the `tmp/` directory's older test workspaces, three of which deny listing; it
is ignored (`/tmp/`) and nothing writes there now.

### Second pass after the commit (2026-11-22)

A diff-driven pass over `2109b22..ef03f5a`.

- **The new pattern does not refuse correct output.** `assert_no_genotype` scans the
  bundle's manifest, QC report and ancestry record at save time, `runs list`, `runs qc`,
  `runs imputation`, every `cards` command, outbound requests and two dashboard partials. A
  false positive in the save-time scans would fail M15.1 at its last stage, so each was
  checked: none emits a quoted `rsid` beside a call key (the call keys live only in
  `cards.run.json` and the card detail views, which are not scanned by design), and
  `cards evidence`, text and JSON, passes for all 119 cards in the pack, as do `cards guide`
  and `cards search`. `redact` may now cover up to 600 characters around a hit, which errs
  toward hiding more.
- **P3, fixed:** the refusal said "because HOME or the home directory points into the
  checkout" on macOS, and named `LOCALAPPDATA` on Windows when it was unset and the home
  directory was the cause. It now names whichever one it read; a test holds the wording.
- **P3, fixed, stale:** `privacy.py`'s docstring said there were three shapes and listed
  four; it lists five and says how to add a sixth (below). `user_data_dir`'s docstring and
  AGENTS.md §1.5 said only the override was refused.
- **Recorded for the next pattern:** the repo-hygiene test reads the committed copy while
  the pre-commit hook imports `privacy.py` from the working tree, so a pattern that flags
  content already committed cannot land in the same commit as the fix to that content. The
  fix went first (`621ac61`), with the rest of the tree stashed so the hook saw the commit
  as it would be. `--no-verify` was not used.
