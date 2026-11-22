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
- [x] **M15.4 Licences.** `manifest.lock` reviewed; nothing non-permissive vendored;
  per-score PGS licences honoured.
- [x] **M15.6 Citations.** Every shipped card's DOI, PMID or accession resolves.

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

## M15.4 Licences (closed 2026-11-22)

Terms pages were read on 2026-11-22. Two of them render only with JavaScript: gnomAD's was
read from its source in the gnomAD browser repository, and ClinPGx's could not be read at all.
No request carried anything about the user.

### The lock

**All 33 locked sources agree with the manifest and the licence registry:** licence id,
every flag, standing, review status, version, obligations, and whether an opt-in is
required. The two restricted sources fetched, `pharmgkb` (CC BY-NC-SA 4.0) and `cpic`, both
record the opt-in. The lock holds public URLs, digests and licences only.

- **P2, fixed: a fetched source the pipeline reads had no lock entry.** The ISOGG Y tree
  (`y_tree_isogg_grch37`, MIT, read by the Y haplogroup caller) was complete on disk but
  had never been in the committed lock, so its licence and digests were recorded nowhere
  this audit reads. Git history does not show why. `genetics refs fetch --only
  y_tree_isogg_grch37` verified the files already on disk against the manifest's pins and
  recorded them. `refs status` now prints a line under any complete source missing from
  the lock; a test holds it.

### The worklist

Nine licences were still `needs-review`, which is the worklist the registry was built to
leave for this step. Each was read against its published terms:

| Licence | Sources | Outcome |
|---|---|---|
| US Government public domain | ClinVar, dbSNP | **Confirmed.** NCBI "places no restrictions on the use or distribution of the data"; submitters may claim rights, and NCBI grants none of its own |
| gnomAD | exomes (fetched), genomes | **Confirmed, and the reason corrected.** The primary data are **CC0**, plus a term CC0 does not carry: users "agree to not attempt to reidentify participants". It stays a `LicenseRef-` for that term. SpliceAI annotations (CC BY-NC) are not in the r2.1.1 VCFs read here |
| Fort Lauderdale | 1000 Genomes (fetched); HGDP, SGDP (not) | **Confirmed.** "Available without embargo", cite; EMBL-EBI adds no restriction on use or redistribution |
| PhyloTree | phylotree_17 (fetched) | **Confirmed, two corrections.** The site states no licence, no copyright notice and **no academic restriction**; AGENTS.md §5.1 said "academic use". `redistribution_ok` becomes false, since nothing grants it (the gate does not read it, and the tree is fetched, never vendored) |
| FinnGen | finngen_r12 (not fetched) | **Confirmed, note corrected.** "May be freely used"; commercial use is the user's responsibility. The registry said FinnGen asks users not to re-identify participants, and the page says nothing of the kind. `redistribution_ok` becomes false |
| CPIC database | cpic (fetched, opt-in) | **Confirmed at the stricter reading.** See below |
| HIBAG HLARES | four classifiers (not fetched) | **Confirmed as unestablished permission.** Still no licence for the model files, which "can be used by researchers"; the opt-in stays |
| OMIM | omim (not fetched) | **Left `needs-review`.** Never fetched, key-only, and already the most restrictive classification the table has |
| PharmGKB BY-SA, CPIC open | none | **Not applicable.** Superseded at M10.1 and used by no source; kept so older locks and saved runs still read, now noted as such |

**The CPIC scope conflict M10.1 left here:** paragraph 6 of the v1.60.0 licence says "The
CPIC database and API are also bound by these licensing and terms of use", with the words
linked to the ClinPGx data usage policy. That policy renders only with JavaScript and could
not be read; ClinPGx's own archive notices say BY-NC-SA. **Decision:** keep the stricter
classification (non-commercial, share-alike, opt-in) rather than choose between the
readings, because this project meets both. The use is personal and non-commercial, and
nothing derived from the database is committed or redistributed. Rejected: reclassifying
as CC0 on the strength of the licence file's first paragraph, which paragraph 6 qualifies.

After this, no source is left in `needs-review` standing (`genetics refs licenses`).

### Nothing non-permissive is vendored

- **Front-end:** htmx 2.0.10 (0BSD) and the Alpine CSP build 3.16.1 (MIT) match their npm
  tarballs byte for byte. The htmx licence text matches its tarball's; Alpine's tarball ships
  none, and the vendored text matches the repository's `LICENSE.md` at `v3.16.1`.
- **Nothing committed is derived from a restricted source.** The PGx guideline cards hold
  selectors and paper citations; their guideline content is read from the local fetch at
  run time, and the PGx code embeds no allele tables. No card carries score weights. The
  fixtures use invented frequencies.
- **Runtime dependencies** are MIT or BSD (typer, polars, PyYAML, FastAPI, uvicorn, Jinja2).
  PLINK, Beagle and the JRE are downloaded and executed, never vendored or linked
  (`refs/tools.py` records why GPL does not reach output).

### Per-score PGS licences were honoured

The pack names 24 score ids. 21 are shipped cards' scores; three (PGS002128, PGS002215,
PGS002822) appear only in prose as alternatives considered. **All 24 carry the EBI default
terms** in `pgs_all_metadata_scores.csv`'s `License/Terms of Use` column, so none needs an
opt-in. The gate holds anyway: `pgs/runner.py` refuses any score whose terms are not
permissive before preparing its reference or reading any personal input, a run never
grants the opt-in, and `test_not_fetched_unlicensed_and_unplaced_cards_still_render_with_reasons`
holds the refusal. PGS000001 is fetched for the scoring tests and ships in no card.

### For the owner

- **The repository has no licence file.** `pyproject.toml` declares MIT and AGENTS.md
  calls this "an MIT tree", but there is no `LICENSE`, and GitHub reports none. Without
  one the code is all rights reserved, whatever `pyproject.toml` says. Adding one is a
  grant only the copyright holder can make, and its first line names them, so it was not
  done here. It belongs before the v1 tag (M15.7 or M15.8).

### Effect on M15.1

The lock changed (six licence blocks and the Y tree entry), and so did Python source
(`refs/licenses.py`, `cli/refs_cmd.py`). Both are part of the saved-parts key, which is fine
before session 1.

## M15.6 Citations (closed 2026-11-22)

**Every citation resolves, each to the record its card says it is, and none is retracted.**
No fabricated reference was found.

### What was checked

The pack holds 119 cards and 196 distinct citations: 123 DOIs, 8 PMIDs, 51 accessions (22
dbSNP, 21 PGS Catalog, 6 ClinVar, 2 PharmGKB) and 14 UK Biobank showcase URLs. The 12 cards
without a citation are the impossibility cards, which are exempt (AGENTS.md §7.6). Seven
more DOIs are written into engine code rather than the pack (the Weedon PPV benchmark,
HIBAG, ACMG SF v3.3, Tandy-Connor, Okbay, Ding, and the ancestry framework in
`pgs/portability.py`); three of them are also in the pack, so 200 identifiers in all.

Each was resolved against its registry, every request through `outbound.check_url`:
Crossref for DOIs (DataCite for the figshare DOI), NCBI E-utilities for PMIDs, dbSNP and
ClinVar, the PGS Catalog REST API, ClinPGx for PharmGKB, and the showcase pages for UK
Biobank fields. **Resolving is not the test on its own,** because an invented citation can
still be a real DOI for a different paper. So each stated title was compared with the
registry's; for accessions, whose titles are descriptions, the record was checked against
what the card says it is.

- **DOIs and PMIDs:** all resolve. Every title matches the registry's to within
  punctuation, case and markup (`O<sub>2</sub>`, "106160" for "106,160", where "(CPIC)"
  sits in a CPIC title), except one fixed below. FUT2's (Kelly 1995) is longer than
  Crossref's because it carries the title's second sentence, which PubMed has. The seven
  engine DOIs are each the paper the code describes.
- **Accessions:** each of the six ClinVar titles equals ClinVar's. Each dbSNP rsID exists,
  is not merged, and sits on the gene its card names; rs2472297, rs4481887 and rs10427255
  are intergenic. Each PGS id's name, trait and publication match its card (PRS3820_BC,
  breast cancer, Mavaddat; GPS_Mult, coronary artery disease, Patel; the
  `portability-ldpred2_*` scores, Privé; the `cont-decay-*` scores, Ding). Both PharmGKB
  ids are the variant records for the rsIDs named.
- **UK Biobank fields:** all 14 pages resolve to the field described.

### Retractions and corrections

Crossref lists no retraction for any of them. Eight have a later notice, and each was read
for whether it changes anything a card states:

| Cited | Notice | Effect |
|---|---|---|
| Weedon 2021, BMJ (the PPV benchmark) | correction n792 | Licence only (CC BY, not CC BY-NC); the 16% and 4.2% figures are untouched |
| Pilling 2019, BMJ (HFE) | correction l6157 | A coauthor's name misspelt |
| Privé 2022, AJHG | erratum | Two equations corrupted in print, corrected; the cards use the released weights, not the formula |
| Hung 2005, PNAS (HLA-B\*58:01) | correction | Affiliation symbols only |
| Gregg 2021, ACMG carrier screening | correction | Non-inclusive wording replaced; recommendations unchanged |
| ACMG 2013 MTHFR guideline | 2020 addendum | Already cited beside it by the MTHFR cards |
| ACMG 2020 MTHFR addendum | 2020 correction | **Not read:** the publisher refuses automated access, and PubMed holds only its title |
| Watson 2004, ACMG CF panel | errata 2004 and 2005 | **Not read**, for the same reason |

The three unread notices are left for a reading in a browser. The two CF carrier cards rest
on G542X and 621+1G>T, which are on every version of the ACMG panel.

### Fixed

- **P3: one citation's title was a description.** The figshare DOI that twelve UK Biobank
  LDpred2 citations share was titled "Author-released UKBB-PGS weights and model-specific
  prediction correlations"; the record's title is "Effect sizes for 200+ polygenic scores".
  The title is now the record's and the description is its `note`. This changes the pack,
  and so the M15.1 parts key, which is fine before session 1.

**Not done:** the resolver is not committed. It is network code the offline engine has no
use for, and the method is written above for the next audit.
