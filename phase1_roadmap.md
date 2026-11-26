# Phase 1 Roadmap — to v1

Implementation guide **and** living checklist. Update the boxes as you go; this file is
the source of truth for build state.

> **Read [`AGENTS.md`](AGENTS.md) first.** It holds the privacy rules (§1), the measured
> input format (§2), the editorial stance (§0.1), the confirmed roadblocks (§4), and the
> corpus map (§5). This roadmap tells you *what to build and in what order*; AGENTS.md
> tells you *what is true and what is forbidden*. Where they appear to conflict,
> AGENTS.md wins and this file is the thing that needs fixing.

**Status legend:** `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked ·
`[-]` descoped (say why inline)

---

## Next up

**M15.1 passed on 2026-11-26** at `325116e` ([record](docs/handoff.md#m151-record)): the full
offline run on the real export completed in three sessions (7 h 55.9 min total wall-clock,
~6 h 12 min unique stages with cached Beagle jobs; 14.55 GB peak tree RAM; 2.27 GB saved
bundle; 0 outbound attempts by the run's own processes under Windows Firewall option A with
Google Antigravity exempted). M0–M14, M15.1, M15.2, M15.3, M15.4 and M15.6 are complete.

What remains before the v1 tag ([listed in the handoff](docs/handoff.md#after-m151)):

- **Deferred code-health split (scope 4):** split the four modules over 2,000 lines
  (`refs/postprocess.py`, `engine/cards.py`, `web/views.py`, `run/bundle.py`). Note that any
  engine change after M15.1 means the tagged code differs from what M15.1 ran (record that
  or re-run).
- **M15.5 (second half):** real-run calibration review (pre-run half done 2026-11-23).
- **Deferred scope-1 engine items** ([record](docs/review_project_engine.md)).
- **M15.7:** README rewrite from M15.1's measurements (closes scope 3).
- **Owner action:** add a `LICENSE` file (`pyproject.toml` declares MIT).
- **M15.8:** tag v1.

---

## Table of contents

- [Next up](#next-up)
- [Definition of done](#definition-of-done-for-v1)
- [Tech stack](#tech-stack-decided)
- [Repository layout](#repository-layout)
- [Data flow](#data-flow)
- [Completed milestones](#completed-milestones), M0 to M14
- [M15 — v1 release gate](#m15--v1-release-gate)
- [Risk register](#risk-register)
- [Progress log](docs/progress_log.md), its own file

---

## Definition of done for v1

v1 ships when all of the following are true:

1. `genetics run --input AncestryDNA.txt` completes offline (after a one-time fetch) and
   produces a saved run bundle.
2. The dashboard opens that bundle and renders all thirteen sections from
   [AGENTS.md §3.1](AGENTS.md), each with summary cards, confidence tiers on the card
   face, and detail modals carrying real citations.
3. Every section either has cards or an explicit "nothing determinable here, because X"
   state. No silent empty sections.
4. §3.2 impossibilities render as explicit "not determinable" cards.
5. Save/load works across runs and across app restarts.
6. Every analysis is reachable from the CLI as JSON, and an agent can answer
   *"review this run, look at card X, check its citations"* using only CLI output.
7. A second, structurally different input file (synthetic, different vendor layout,
   different sex) runs end-to-end without code changes.
8. The privacy test suite passes and `git status` is clean of genotype-derived paths.

**Explicitly out of v1:** relative matching/IBD, static self-contained HTML export,
multi-user support, any network call at analysis time.

---

## Tech stack (decided)

Chosen against the Windows constraint in [AGENTS.md §4.9](AGENTS.md). Do not substitute
without reading it.

| Layer | Choice | Why |
|---|---|---|
| Core language | Python 3.11+ | Ecosystem; single language front-to-back |
| Dataframes | **Polars** | Fast on 677k rows; good Windows story; lazy scan for big reference files |
| Genomics workhorse | **PLINK 2** (pinned exactly; `v2.0.0-a.7.3` as of M2.5 — the original `2.00a5.x` note is stale, see [AGENTS.md §4.9](AGENTS.md)) | Native Windows binary; covers conversion, LD prune, PCA projection, `--score`, freq, sex check; ROH uses separately pinned PLINK 1.9 `--homozyg` |
| VCF reading in Python | **scikit-allel** | Cython, no htslib — the documented Windows path |
| Imputation / phasing | **Beagle 5.x** (Java) | GPLv3, cross-platform, bref3 panels |
| HLA imputation | **HIBAG** (R, via subprocess) | Ships pre-fit multi-ancestry classifiers; optional module |
| CLI | **Typer** | Typed commands, auto help, easy JSON output |
| Web framework | **FastAPI** + **Jinja2** | Local server, server-rendered cards |
| Front-end interactivity | **htmx** + **Alpine.js**, both vendored | No node toolchain, no CDN, fully offline |
| Styling | Hand-written CSS with design tokens | Light/dark, no build step |
| Testing | pytest + hypothesis | Property tests for the parser |
| Packaging | uv or pip + `pyproject.toml` | — |

**Banned dependencies:** `pysam`, `cyvcf2`, native `bcftools`/`tabix`, anything requiring
a CDN at runtime. See [AGENTS.md §4.9](AGENTS.md).

---

## Repository layout

```
genetics-analysis/
├── AGENTS.md
├── phase1_roadmap.md
├── pyproject.toml
├── src/genetics/
│   ├── *.py             cross-cutting singles: paths, privacy, guard, netaddr, doctor
│   ├── testing/         fixture generator + the offline guard the suite installs
│   ├── ingest/          vendor adapters, sniffing, normalized table
│   ├── qc/              sex inference, call rate, build assertion
│   ├── refs/            manifest, fetcher, license lock, tool acquisition
│   ├── engine/          card matching, confidence, evidence assembly
│   ├── modules/         one module per section (ancestry, pgx, hla, …)
│   ├── external/        PLINK2 / Beagle / R subprocess wrappers
│   ├── run/             run bundle read/write, versioning
│   ├── cli/             Typer app
│   └── web/             FastAPI app, templates/, static/ (vendored htmx+alpine)
├── knowledge/           card definitions (YAML) — COMMITTED
│   ├── traits/  pgx/  nutrition/  health/  …
│   └── impossibilities/
├── data/                tools.yaml COMMITTED
│   └── references/      manifest.yaml + manifest.lock COMMITTED, payloads gitignored
├── tests/
│   ├── fixtures/synthetic/   COMMITTED, generated only
│   └── privacy/              leak-prevention suite
└── scripts/
```

---

## Data flow

```
raw export ──► ingest ──► normalized table ──► QC report
                                 │
                                 ├──► PLINK2 pgen ──► ancestry / ROH / PRS
                                 ├──► Beagle ──► imputed dosages ──► PRS, HLA
                                 └──► direct lookup ──► ClinVar, PGx, traits
                                              │
                                    evidence assembly (+ gnomAD freq, ancestry match)
                                              │
                                    scored cards ──► run bundle ──► UI / CLI
```

---

## Completed milestones

M0 to M14 are done. Their checklists, design notes and the decisions taken in
them are kept verbatim in [roadmap_history.md](docs/roadmap_history.md):

- [M0 — Foundations & guardrails](docs/roadmap_history.md#m0--foundations--guardrails)
- [M1 — Ingest & QC](docs/roadmap_history.md#m1--ingest--qc)
- [M2 — Reference fetcher](docs/roadmap_history.md#m2--reference-fetcher)
- [M3 — Card engine & knowledge pack](docs/roadmap_history.md#m3--card-engine--knowledge-pack)
- [M4 — Run bundle & first UI](docs/roadmap_history.md#m4--run-bundle--first-ui)
- [M5 — Ancestry](docs/roadmap_history.md#m5--ancestry)
- [M6 — Genome structure](docs/roadmap_history.md#m6--genome-structure)
- [M7 — Monogenic health & frequency gating](docs/roadmap_history.md#m7--monogenic-health--frequency-gating)
- [M8 — Imputation](docs/roadmap_history.md#m8--imputation)
- [M9 — PRS engine & score-driven sections](docs/roadmap_history.md#m9--prs-engine--score-driven-sections)
- [M10 — Pharmacogenomics](docs/roadmap_history.md#m10--pharmacogenomics)
- [M11 — HLA, immunogenetics & carrier status](docs/roadmap_history.md#m11--hla-immunogenetics--carrier-status)
- [M12 — Nutrition & metabolism](docs/roadmap_history.md#m12--nutrition--metabolism)
- [M13 — Agent interface](docs/roadmap_history.md#m13--agent-interface)
- [M14 — UI completion](docs/roadmap_history.md#m14--ui-completion)

---

## M15 — v1 release gate

- [x] **M15.1** Full run on the real file, offline, start to finish. Record wall-clock and
      peak memory in the progress log. **Done 2026-11-26** at `325116e` (`--hla-model-opt-in`,
      imputation on, Windows Firewall option A with Google Antigravity exempted): 3 sessions,
      7 h 55.9 min total wall-clock (~6 h 12 min unique stages with cached Beagle jobs),
      14.55 GB peak tree RAM (0.81 GB min free), 2.27 GB saved bundle, 0 outbound attempts by
      the run's own processes (with the Security-log wrap and DNS/Store-`pwsh` caveats
      recorded). See [the record](docs/handoff.md#m151-record).
- [x] **M15.2** Full run on a structurally different synthetic fixture (different sex,
      different vendor layout) with **no code changes** — proves plug-and-play. Done
      2026-11-23: a female export in the 23andMe-like layout ran end to end with no adapter,
      analysis module or card changed, and both front-ends read it. It found two defects
      outside the adapter seam, both fixed before M15.1: a region too sparse for Beagle's
      windows ended the run, and `genetics run --restart` was not declared on the command.
      See [the record](docs/handoff.md#m152-record).
- [x] **M15.3** Privacy audit: `git log --all` reviewed for any genotype-derived blob ever
      committed; `.gitignore` re-verified against every path the app writes. Done
      2026-11-21: nothing genotype-derived was ever committed; two routes that could have
      leaked were closed. See [the audit](docs/review_release_audits.md#m153-privacy-closed-2026-11-21).
- [x] **M15.4** Licence audit: `manifest.lock` reviewed; confirm nothing non-permissive is
      vendored and that per-score PGS licences were honoured. Done 2026-11-22: all three
      hold; the Y tree was missing from the lock and is now recorded; seven of the ten
      unreviewed licences were read and confirmed, three with corrections. The repository
      itself has no `LICENSE` file, which is the owner's to add. See
      [the audit](docs/review_release_audits.md#m154-licences-closed-2026-11-22).
- [~] **M15.5** **Calibration review** — the most important gate. Sample cards across all
      confidence tiers and check the stated confidence matches the actual evidence.
      Specifically verify a rare pathogenic call renders as `likely-artifact` with its
      PPV, and that no code path filters cards by confidence.
      *Pre-run half done 2026-11-23* ([record](docs/review_m155_prerun.md)): 21 trait and
      nutrition cards could not rise above moderate for want of a frequency, now priced from
      1000 Genomes; an unreplicated finding can no longer be strong; no filter by confidence;
      the PPV is on the face. The real-run half follows M15.1.
- [x] **M15.6** Citation audit: every shipped card resolves to a real DOI/PMID/accession.
      Zero fabricated references. Done 2026-11-22: all 200 identifiers resolve to the
      record their card describes, none is retracted, and one figshare title that was a
      description now holds the record's title. See
      [the audit](docs/review_release_audits.md#m156-citations-closed-2026-11-22).
- [ ] **M15.7** README with setup, fetch, run, and the privacy warning. Also carries the rest
      of scope 3 of the [project review](docs/handoff.md#project-review-before-m151): the
      README's milestone paragraphs give way to the guide. (The handoff and this roadmap
      were cut back to current state on 2026-11-23, their history moved verbatim to
      [handoff_history.md](docs/handoff_history.md), [roadmap_history.md](docs/roadmap_history.md)
      and [progress_log.md](docs/progress_log.md).)
- [ ] **M15.8** Tag v1.

---

## Risk register

| Risk | Milestone | Mitigation | Ref |
|---|---|---|---|
| Rare-variant false positives presented as findings | M7 | Frequency gate + PPV on card face | [§4.1](AGENTS.md) |
| An agent adds `pysam`/`cyvcf2` and breaks Windows | M0, M5 | Banned-dependency list + CI on Windows | [§4.9](AGENTS.md) |
| Genotype-derived artifact committed | M0 | Privacy suite + pre-commit + M15.3 audit | [§1](AGENTS.md) |
| Confidence used as a filter, hiding results | M3, M15.5 | Explicit test that no code path drops on confidence | [§0.1A](AGENTS.md) |
| Fabricated citations | M3.5, M15.6 | Card lint in CI; card without citation cannot ship | [§6](AGENTS.md) |
| Non-permissive source vendored | M2.2 | Fetcher refuses/flags; licence lock; M15.4 | [§4.8](AGENTS.md) |
| A rolling "latest" URL changes under a saved run, silently altering results | M2.2 | Lock records the digest on first fetch. **Drift is reported and re-recorded on a fresh download, and fails on bytes already on disk** — enforcing it on the download made a file the manifest declares unpinnable unfetchable for every clone, since the committed lock hands one machine's digest to all of them; enforcing it on disk is what catches corruption, because a fetch re-records drift in the same run, so a later disagreement is something nothing fetched. Re-recording stamps today's date, so the change is a line in the committed lock's diff. **The lock merges rather than replaces** — replacing let one detected corruption erase its own evidence and be re-recorded as truth | [§5.5](AGENTS.md) |
| A declared post-processing step is never executed but reports as done | M2.1, M3.5 | The registry may mark a step implemented only when the executor dispatch names it; a structural test proves the sets are identical, fetch runs it, and verify reports the derived output's state — `pending` when it has not been built (which `refs status` calls "processing-required"), `failed` only when a present artifact does not validate. Unimplemented steps remain visibly pending | — |
| gnomAD's real size (63 GB exomes / 495 GB genomes) stalls a first setup | M2.3 | Exomes required and genomes optional; sizes declared exactly so the preflight can warn before the download, not after | [§4.1](AGENTS.md) |
| PGS per-score licences ignored | M9.1 | Join each PGS ID to the authoritative metadata CSV terms; never assume header or catalogue permission | [§4.8](AGENTS.md) |
| Imputation run un-resumable, blocking progress | M8.1 | Resumability is an acceptance criterion | [§0.1C](AGENTS.md) |
| CLI/UI parity rots | M13.5 | Parity test in CI | [§3](AGENTS.md) |
| Reduced-N sumstats silently weaken psychometrics | M9.8–9.9 | Record release version on the card | [§5.3](AGENTS.md) |
| Carrier section implies false completeness | M11.6, M14.6 | Explicit incompleteness card; the section names its assay limits at its head whatever the grid's filters | [§3.2](AGENTS.md) |
| PLINK 2 alpha build changes behaviour | M2.5 | Pin exact build in manifest | [§4.9](AGENTS.md) |
| A `.gitignore` negation silently re-admits genotype output | M4.1 | A later un-ignore rule wins over an earlier ignore rule, and `!/knowledge/**/*.json` did exactly that to the run-bundle payload. The mitigation is not another rule but **how it is checked**: tests ask `git check-ignore` rather than searching `.gitignore` for text, since a string search cannot see precedence, negation or ordering — the only things that decide the answer. A companion test asserts the card corpus stays trackable, so a re-ignore rule cannot be widened until it breaks what must be committed | [§1.1](AGENTS.md) |
| A bundle-format bump orphans every run a user has already saved | M4.1, M4.2 | Bundles are immutable, so no in-place migration is possible even in principle. Guaranteed by contract instead: **payload keys may be added, never removed or repurposed**, so a reader accepts any bundle at or below its own version and an old bundle still carries everything a newer reader requires. A test moves the engine version forward and reads a current bundle through it | — |
| A network call creeps into analysis code and is only found at the release gate | M2.7, M4.10 | Autouse guard fails the suite in the commit that adds one, naming the test; the OS-level run at M4.10 covers the subprocesses the in-process guard cannot see | [§6](AGENTS.md) |

---

## Progress log

Kept in its own file, [docs/progress_log.md](docs/progress_log.md): a dated row per
milestone and review, newest first. Add each new row there.
