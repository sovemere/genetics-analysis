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

## Table of contents

- [Definition of done](#definition-of-done-for-v1)
- [Tech stack](#tech-stack-decided)
- [Repository layout](#repository-layout)
- [Data flow](#data-flow)
- [M0 — Foundations & guardrails](#m0--foundations--guardrails)
- [M1 — Ingest & QC](#m1--ingest--qc)
- [M2 — Reference fetcher](#m2--reference-fetcher)
- [M3 — Card engine & knowledge pack](#m3--card-engine--knowledge-pack)
- [M4 — Run bundle & first UI *(end of vertical slice)*](#m4--run-bundle--first-ui)
- [M5 — Ancestry](#m5--ancestry)
- [M6 — Genome structure](#m6--genome-structure)
- [M7 — Monogenic health & frequency gating](#m7--monogenic-health--frequency-gating)
- [M8 — Imputation](#m8--imputation)
- [M9 — PRS engine & score-driven sections](#m9--prs-engine--score-driven-sections)
- [M10 — Pharmacogenomics](#m10--pharmacogenomics)
- [M11 — HLA, immunogenetics & carrier status](#m11--hla-immunogenetics--carrier-status)
- [M12 — Nutrition & metabolism](#m12--nutrition--metabolism)
- [M13 — Agent interface](#m13--agent-interface)
- [M14 — UI completion](#m14--ui-completion)
- [M15 — v1 release gate](#m15--v1-release-gate)
- [Risk register](#risk-register)
- [Progress log](#progress-log)

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
| Genomics workhorse | **PLINK 2** (pinned exactly; `v2.0.0-a.7.3` as of M2.5 — the original `2.00a5.x` note is stale, see [AGENTS.md §4.9](AGENTS.md)) | Native Windows binary; covers conversion, LD prune, PCA projection, `--score`, `--homozyg`, freq, sex check |
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

## M0 — Foundations & guardrails

*Nothing else starts until the privacy harness exists. A leak committed in week one is
permanent in git history.*

- [x] **M0.1** Scaffold `pyproject.toml`, `src/genetics/` package, Typer entry point
      `genetics`, ruff + mypy config, pytest config.
      - Python 3.13.5 / uv. Deps deliberately minimal (`typer` only); each milestone adds
        its own. Banned-dependency note recorded in `pyproject.toml` itself, where an
        agent reaching for `pysam` will actually see it.
      - `ruff` (E/F/W/I/UP/B/SIM/RUF, line-length 100) and `mypy --strict` both clean.
      - Also added `.gitattributes` (`eol=lf`) — required, not cosmetic: fixture
        byte-identity breaks if git rewrites line endings on Windows checkout.
- [x] **M0.2** **Synthetic fixture generator.** Logic in
      `src/genetics/testing/fixtures.py` (so ruff + strict mypy cover it and tests can
      import it); `scripts/make_fixtures.py` and `genetics fixtures` are thin wrappers.
      Six fixtures generated: male, female, high-no-call, wrong-build, malformed-header,
      other-vendor — plus `MANIFEST.json` with per-file sha256.
      - *Acceptance met:* `genetics fixtures --check` re-derives and byte-compares;
        24 tests pass.
      - Per-fixture RNG derived from `(seed, name)`, so adding a fixture cannot perturb
        the bytes of existing ones.
      - Chip-shape constants (per-chromosome marker density, 1.3% indel rate, 0.08%
        no-call rate) describe the **array design**, identical for everyone tested on it,
        so they carry no individual information. Genotypes are drawn under Hardy-Weinberg
        from invented allele frequencies; rsIDs are synthetic, counting from `rs900000001`.
      - Heterozygote column order is **randomised on purpose** — the format guarantees no
        ordering, so a parser that compares positionally instead of sorting fails here
        rather than in production.
      - `spike_ins` hook exists but is empty: the card engine (M3) will need known markers
        with chosen genotypes, but populating it now would mean inventing GRCh37
        coordinates. Fill it once M2 lands real reference data.
      - Two privacy tests guard the module: fixtures must self-label as `SYNTHETIC`, and
        the generator source must contain no file-reading call at all, so it cannot
        acquire a "path to a real export" argument later.
- [x] **M0.3** Privacy test suite — **selected by the `privacy` marker, not by directory**
      (see M0.4; 189 marked tests, of which 140 live in `tests/privacy/` and the rest beside
      the code they guard). Two enabling modules:
      `genetics.privacy` (leak detection, redaction, `NoGenotypeRepr`) and
      `genetics.paths` (canonical write locations + `APP_WRITE_PATHS` registry), surfaced
      as `genetics paths --json` so the registry is inspectable rather than only asserted.
      - [x] no tracked file matches genotype-derived name patterns
      - [x] **no tracked file *contains* genotype content** — the check that matters most.
            `.gitignore` only catches files whose name gives them away; this catches a
            row pasted into a doc, a debug print, or a fixture trimmed from a real export.
            It is the check that would have caught the two real rows in AGENTS.md.
      - [x] `.gitignore` covers every path in `APP_WRITE_PATHS`; manifest/lock stay tracked
      - [x] `__repr__` cannot emit a genotype — `NoGenotypeRepr` shows declared fields
            only, omits (never summarises) the rest, and redacts a declared field that
            turns out dirty. Genotype-bearing classes in M1 must inherit it.
      - [x] `GenotypeLeakError` messages never echo the offending text
      - [x] runs/ and cache/ resolve outside the repo; `GENETICS_DATA_DIR` override
            preserves that guarantee
      - Precision is deliberately favoured over recall — 9 negative cases assert ordinary
        prose, bare rsIDs and code don't trip it. A scanner that cries wolf gets bypassed.
- [x] **M0.4** Pre-commit hook (`.githooks/pre-commit`, tracked; `genetics install-hooks`
      sets `core.hooksPath`). Runs `check-staged` → privacy suite → ruff, cheapest and
      most consequential first. Refuses to run at all if the package is not importable,
      rather than passing silently unverified.
      - **Selects the privacy suite by marker, not by directory** — corrected during M3.1,
        see the progress log. `pytest tests/privacy` had been skipping **17 privacy-marked
        tests living beside the code they guard**, including M1.8's two CLI genotype-output
        guards and M1.4's "an error message must not echo a data row" tests. The marker had
        also drifted the other way, with one module inside `tests/privacy/` carrying no
        marker at all, so neither selector ran the whole suite and nothing said so.
        `tests/privacy/test_suite_selection.py` now holds both ends honest, including an
        assertion about the hook's own text.
      - **Verified adversarially, not assumed:** staged a markdown file containing a
        genotype row and confirmed the commit was blocked and HEAD unchanged.
      - Hook documents that `--no-verify` is not acceptable, and why: a genotype pushed
        to a public repo cannot be recalled — history rewriting does not reach forks,
        clones, or mirrors.
- [x] **M0.5** CI (`.github/workflows/ci.yml`): 2 OS × 2 Python matrix
      (windows/ubuntu × 3.11/3.13) running ruff, `mypy --strict`, `genetics cards lint
      --schema-only` (added in M3.5), the privacy suite **by marker** (corrected in
      M3.3–M3.6: the workflow still selected by directory long after M3.1 fixed the hook,
      so CI had been skipping the distributed privacy tests on every push), the full suite,
      and a fixture-reproducibility check.
      - Second job `no-data-in-ci` asserts the checkout holds no raw export, no
        genotype-derived artifact, and no reference payload beside the manifest.
      - The matrix is not ceremony: the htslib constraint (§4.9) means a dependency can
        pass on Linux and fail on Windows, and M0.3 already caught one such bug
        (see progress log).
- [x] **M0.6** `genetics doctor` (`src/genetics/doctor.py`): Python, OS, PLINK2 / Java /
      Beagle / R+HIBAG, reference manifest state, free disk. JSON-capable.
      - **Reports; never installs, fetches, or fails on absence.** A missing PLINK 2 on a
        fresh checkout is the expected state, and an exit code meaning "you have not done
        M2 yet" would greet every newcomer in red and teach them to ignore it. Non-zero is
        reserved for things that are *wrong*: an unsafe `GENETICS_DATA_DIR`, or a tool
        present but unable to report a version.
      - Searches the app's own tools dir before PATH, since M2.5 installs pinned builds
        there rather than expecting a system install.
      - Java version goes to **stderr**, PLINK 2 and R use stdout; reading only stdout
        would call a working JVM broken. Every probe survives a timeout, a non-executable
        file, and a non-zero exit — `doctor` runs precisely when the environment is
        suspect.
      - Two review findings, both the same shape — *a check that can only return one
        answer*: the HIBAG probe printed nothing on success while empty output is treated
        as failure, so the "HIBAG present" branch was unreachable on every machine; and
        Beagle jar selection sorted filenames, but Beagle names jars by date
        (`05May22` sorts before `28jun21`), so the **older** of two installs won. Both now
        have tests covering the branch that could not previously be reached.

---

## M1 — Ingest & QC

- [x] **M1.1** Normalized table schema (`ingest/schema.py`), exactly as
      [AGENTS.md §2](AGENTS.md). Four decisions are load-bearing, each a place where the
      plausible alternative fails silently rather than loudly:
      - `chrom` is a Polars **`Enum` with no `23`–`26` members at all**, so a leaked
        vendor code raises at construction instead of making every `chrom <= 22` filter
        quietly include the sex chromosomes. `PAR` stays distinct from `X` — folding them
        would give every male a nonzero X het rate and blunt the sex-inference signal.
      - **No-calls are null, not `"0"`.** As `"0"` a no-call joins cleanly against a
        reference table and compares equal to every other no-call; as null it propagates.
      - Alleles sorted once, here, so no consumer has to remember.
      - `call_status` carries ploidy, because the genotype string cannot — and it is
        filled in only *after* sex inference, since until then it is not known.
      - `GenotypeTable` wraps the frame and inherits `NoGenotypeRepr`: a bare Polars frame
        prints rows.
- [x] **M1.2** AncestryDNA V2 adapter (`ingest/ancestry.py`), with the allele-level
      handling shared in `ingest/normalize.py` — the AGENTS.md §2 encoding facts are
      vendor-independent enough that re-implementing them per adapter would mean
      re-making the same mistake per adapter.
      - *Acceptance (CI):* all six fixtures parse or are rejected as specified.
      - *Acceptance (local):* **passed 2026-08-15** — 677,436 markers / 550 no-calls /
        8,830 indels via `genetics ingest --expect-counts`. The sex-chromosome counts in
        AGENTS.md §2 reconcile exactly once you notice its Y figure counts *homozygous*
        calls: X 25,231 called − 4 het = 25,227 hom; Y 1,661 called − 3 het = 1,658;
        MT 263; PAR 36. `Adapter.verified_against_real_export` records that this ran, and
        the CLI prints a warning for any adapter where it has not.
- [x] **M1.3** Vendor sniffing + registry (`ingest/registry.py`) with a 23andMe stub
      (`ingest/vendor_23andme.py`) that really parses the other-vendor fixture: merged
      genotype column, letter chromosomes, `--` no-calls, single-character haploid calls.
      - Detection is **exclusive** — two adapters claiming one file is a conflict to fail
        on, not something to resolve by registration order.
      - The coupling claim is checked structurally: a test parses the imports of every
        analysis module and asserts none reaches a vendor adapter. Intention alone would
        pass every other test in the suite and only surface at the third vendor.
      - Two documented gaps in the stub, both deliberate: `i`-prefixed probes resolve
        against no reference, and the layout has no PAR, so QC's PAR exclusion cannot
        apply. Noted rather than silently corrected.
      - Adapters declare `SourceInfo.representable_chroms`, so QC can distinguish a
        chromosome the *format* never labels from one genuinely missing from the file —
        without importing a vendor module, which the structural test forbids.
- [x] **M1.4** Strict validation (`ingest/errors.py`). Build 37 asserted from the header,
      column header matched by name, allele tokens, positions, and coordinate bounds all
      checked with a **file line number** in the message.
      - Every error message is scanned by `assert_no_genotype` **in the base class
        constructor**, so an error type added later cannot reintroduce the leak.
      - This caught a live one: the truncated fixture's first uncommented line *is* a
        genotype row, and the obvious `f"expected {EXPECTED}, got {observed}"` would have
        put it in an exception message — where the scanner would *not* have caught it,
        because a Python list renders comma-separated. Hence `errors.describe_columns`.
- [x] **M1.5** QC module (`genetics/qc/`). Call rates overall and per chromosome,
      autosomal and non-PAR-X heterozygosity on SNP loci, sex inference, build check,
      indel and duplicate summaries, warnings — and `resolve_ploidy`, which is what makes
      a doubled `A A` on the male X readable.
      - **Sex inference requires two signals to agree** (X het ≤ 0.05 with Y call ≥ 0.30,
        or X het ≥ 0.15 with Y call ≤ 0.15). Disagreement yields `AMBIGUOUS` and leaves
        ploidy unresolved rather than guessing: that disagreement is what a sex-chromosome
        aneuploidy looks like (M6.4), and an unresolved locus is visibly unresolved while
        a wrongly resolved one is not.
      - `HET_HAPLOID` is its own status, so a heterozygous call at a single-copy locus
        stays countable instead of being dropped or read as a diploid genotype.
      - Build check has three layers: header assertion, coordinate bounds against GRCh37
        chromosome lengths (needs no reference data), and rsID anchors. **The committed
        anchor table ships empty** — writing coordinates from memory would be invented data
        ([AGENTS.md §6](AGENTS.md)). Only anchors carrying a `source` may fail a run, so a
        wrong coordinate can lose information but never raise a false alarm. Same precedent
        as the empty `spike_ins` hook in M0.2.
        **Filled in M3.5, and not from dbSNP as written here**: the GRCh37 VCF cannot prove
        a GRCh38 coordinate, so the pairing comes from ClinVar's `variant_summary.txt.gz`,
        which publishes both assemblies per variant. 200 anchors, derived and uncommitted,
        loaded by `default_anchors()`; absent artifact leaves the check indeterminate,
        malformed artifact fails loudly.
      - QC **labels, never filters** ([AGENTS.md §0.1A](AGENTS.md)): nothing here drops a
        marker or rejects a sample.
- [x] **M1.6** Indel policy (`ingest/indels.py`). Default excludes all `I`/`D` from allele
      matching; `IndelRepresentation` **refuses to construct without a `source`**, because
      an unsourced mapping is precisely the guess the whitelist exists to prevent — `D`
      means "the deletion allele", not "the reference", and a wrong guess reports the
      opposite genotype rather than failing. **M3.2 must call `matchable_mask`.**
- [x] **M1.7** Variant keying (`ingest/keys.py`): `LocusKey` is what a *sample* can offer
      (a homozygote reveals only one allele, so no complete allele key exists on that
      side); `VariantKey` is what a card or reference row offers. `MergeTable` chases
      dbSNP merge chains transitively with a cycle guard, resolves **both sides** of a
      lookup, and adds `rsid_current` beside the original rather than overwriting it.
      - Populated in M3.5 from the pinned `refsnp-merged.json.bz2`: **21,562,332** one-to-one
        mappings, and **23,340** records dbSNP cannot resolve to a single current rsID.
        Those 23,340 are kept as an explicit `RsidResolutionStatus`
        (`no-current-target` / `multiple-current-targets` / `cycle`) rather than falling
        through the "unknown rsIDs resolve to themselves" default — a retired rsID that
        dbSNP says has *two* current targets is not the same fact as one dbSNP has never
        heard of, and self-resolving it would silently look the wrong variant up.
- [x] **M1.8** CLI `genetics ingest --input <file> [--json] [--expect-counts ...]`, plus
      `genetics adapters`. **Both** output paths run through `assert_no_genotype` — this
      command's input is a whole genome, and "just show me a few rows to check the parse"
      would land exactly there. The first cut guarded only the JSON branch, which is the
      one a person is *less* likely to edit; review caught that the human render was
      unprotected while the docstring claimed otherwise. Tests feed both a crafted payload
      and require the emit to fail.

---

## M2 — Reference fetcher

- [x] **M2.1** `manifest.yaml` schema (`refs/manifest.py`, `refs/licenses.py`,
      `refs/postprocess.py`). Per source: id, URL, version, checksum, licence, size, tier,
      required-vs-optional, post-download step. Four decisions are load-bearing:
      - **A source names its licence; it does not describe one.** `license: CC-BY-SA-4.0`
        resolves through `refs/licenses.py`, so no manifest edit can widen what a licence
        permits — the alternative puts the gate under the control of the one person
        motivated to get past it. An unknown id **refuses to load** rather than defaulting
        to permissive: the same fail-closed lesson as M0 and M1, applied to licensing.
      - **A file is pinned, or it says why not.** `unpinned_reason` is mandatory when no
        digest exists, so "genuinely unpinnable rolling URL" stays distinguishable from
        "nobody bothered". The lock then records it on first fetch.
        **Corrected in the M3.3–M3.6 review**: for an unpinnable file the lock digest and
        the manifest size are *advisory on a fresh download* — reported and re-recorded,
        never fatal. Enforcing them made `variant_summary.txt.gz` unfetchable for every
        clone the week after the manifest was written, because the committed lock hands
        one machine's digest to everybody. What stays strict is bytes already on disk: an
        already-present or `refs verify` mismatch is still a failure, since a fetch
        re-records drift in the same run, so a later disagreement is something nothing
        fetched — which is the definition of corruption.
      - **No URL templating.** 1000G names chromosome X `...v1c...` where the autosomes are
        `...v5b...`, and every file has its own size — a template invites adding a
        chromosome nobody checked exists. In a file whose whole job is pinning, verbosity
        is the feature.
      - Post-processing steps were **declared and validated, not executed** — no runner
        existed, so every step was `implemented=False` and the fetcher reported each one as
        outstanding. A typo still failed at manifest load rather than after a 60 GB
        download, which is the part that had to exist then.
        **M3.5 built the runner** (`refs/postprocess.run`) and three steps are now executed
        for real: `extract_rsid_merge_table`, `extract_dbsnp_variant_index` and
        `extract_build_anchors`. The other seven remain `implemented=False` and visibly
        pending, and `assert_registry_is_honest` makes the claim structural — a step may
        call itself implemented only if the executor's dispatch names it, so the M2 review's
        "three steps marked implemented with no executor anywhere" cannot recur.
      - `imputation_panel` names a **role**, not a ban on subsetting. The blunter rule was
        written first and was wrong: 1000G is simultaneously the imputation panel and the
        source of the PCA subset (M5.3), so "may not be subsetted" would forbid something
        the roadmap requires. What is forbidden is *replacing* the panel.
- [x] **M2.2** Fetcher (`refs/fetcher.py`) + lock (`refs/lock.py`): resumable downloads,
      checksum verification, progress callback, disk preflight, and `manifest.lock`
      recording each source's resolved licence and derived obligations.
      - **Refused, not merely flagged:** PharmGKB (share-alike), OMIM (no-derivatives) and
        SNPedia (NC+SA) need an explicit per-source opt-in. PGS Catalog is deliberately
        *flagged and not blocked* — refusing 6,970 scores because 31 are CC BY-NC-ND would
        train people to pass a blanket opt-in, and then the gate protects nothing.
      - `Transport` reports **`resumed_from`: the offset the server actually used**, not
        the one requested. A server may answer a Range request with `200` and the whole
        file; appending that to a partial download duplicates the prefix, and on an
        unpinned file nothing would ever notice. Reporting reality makes the bug
        unrepresentable rather than merely tested for. Also handled: `Content-Length` on a
        `206` is the *remaining* bytes, so the total comes from `Content-Range`.
      - The lock is **byte-identical across re-runs** — `first_seen` survives an unchanged
        digest. A lock that churned every run would produce a diff nobody reads, which
        would cost exactly the review step that catches a reference changing under a
        saved run.
      - *Verified live, not just against the fake transport:* fetched five real sources,
        confirmed the authored sha256 values matched, then seeded a truncated `.part` and
        confirmed a genuine HTTP Range resume reassembled a file matching its pin.
- [x] **M2.3** Tier A sources. **Every URL, size and digest verified against the live
      server on 2026-08-15 or 2026-08-16; nothing written from memory.** 604 GB declared across 17
      sources, 92 GB of it required.
      - [x] gnomAD — **two entries, and the roadmap's assumption needed correcting.** v4 is
            GRCh38-only, so the GRCh37 release is v2.1.1: exomes are one 63 GB file
            (required — they cover the coding regions where ClinVar's pathogenic
            assertions live, which is what the §4.1 gate needs), genomes are **495 GB**
            across 23 files (optional, for non-coding frequencies). Subsetting keeps the
            *storage* manageable but not the download, which the roadmap conflated. All 24
            files are md5-pinned from the base64 digest GCS returns in `x-goog-hash` — the
            whole 558 GB pinned without downloading a byte.
      - [x] ClinVar — the **dated archive** release, not the weekly rolling file, so it can
            carry the publisher's md5. `variant_summary.txt.gz` has no dated equivalent
            and is the one unpinned file there. Its paired GRCh37/GRCh38 rows now produce
            M1.5's build anchors; a single-build VCF cannot truthfully supply them.
      - [x] dbSNP b157 — from the **build-pinned archive path**, not `latest_release/`
            which silently becomes b158. The GRCh37 VCF produces M3.5's current
            rsID/coordinate/allele index, while the separately pinned
            `refsnp-merged.json.bz2` produces M1.7's retired-to-current merge table.
      - [x] 1000 Genomes phase 3 GRCh37 — 16.75 GB, `imputation_panel: true`, declaring
            both `build_pca_marker_subset` and `convert_to_bref3`. EBI publishes no
            checksums, so these are lock-pinned on first fetch.
      - [~] HGDP + SGDP — **demoted to tier B with instructions.** The HGDP collection on
            the 1000G FTP is GRCh38 high-coverage sequence, not the GRCh37 genotype panel
            M5 needs, and SGDP publishes several differently-processed releases (one named
            `knownbugs.not_recommended`) whose selection is an M5.3 decision. Writing a
            plausible URL would be the same failure as inventing a coordinate.
      - [x] GWAS Catalog — real filenames differ from the obvious guess
            (`...-full.zip`, `gwas-catalog-studies.tsv`); only a rolling `latest/` exists.
      - [x] PGS Catalog metadata — see the §4.8 refinement below.
      - [x] PharmGKB + CPIC — **PharmGKB now serves under ClinPGx**; `api.pharmgkb.org` no
            longer resolves. Pinned to the redirect targets on `s3.pgkb.org` so a fetch
            does not depend on a redirect persisting. CPIC pinned at v1.60.0 by sha256.
      - [~] AADR — tier B. Harvard Dataverse answered every API request with a bare 202.
      - [x] PhyloTree 17 (mtDNA) — 421 KB, sha256-pinned, frozen since 2016-02-18.
      - [x] Pan-UKBB — the phenotype manifest only; per-trait files are fetched in M9 from
            its `path_https` column rather than from hard-coded URLs.
- [x] **M2.4** Tier B sources with a one-time human step, modelled as **data rather than
      prose** so `refs status` can act on them: instructions, URL, expected files, an
      optional credential env var, and a retention policy.
      - OMIM: user-supplied `OMIM_API_KEY`, never written to the lock, never logged, with
        an explicit seven-day retention note (its terms forbid a derivative database).
      - **FinnGen turned out not to need a human step at all** — see the AGENTS.md §5.2
        correction. It is tier A.
      - SNPedia added as tier C so its absence is documented rather than mysterious.
- [x] **M2.5** Tool acquisition (`refs/tools.py`, `data/tools.yaml`). PLINK 2 and Beagle,
      pinned by sha256 and installed under `tools_dir()`, never the repo.
      - **Pinned twice, because a checksum answers the wrong question.** It proves the
        download was intact, not that the build is the one whose behaviour we tested
        against — an intact download of a *different* alpha verifies perfectly. So an
        executable must also declare a `version_check` that runs the binary and confirms
        the version it reports, and the schema refuses to load one that does not.
      - The roadmap's `2.00a5.x` pin is stale: alpha5 is no longer linked from the
        download page, and PLINK has changed its version string format. Pinned to alpha7
        `20260808`, whose binary reports `PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)` — read
        off the binary, not guessed. AGENTS.md §4.9 updated.
      - **Java and R are deliberately not acquired.** Both are system-level dependencies
        with their own installers, and HLA must degrade gracefully when R is absent
        ([AGENTS.md §4.9](AGENTS.md)). `doctor` reports on them; nothing installs them.
      - Only baseline builds are listed, not the AVX2 variants: an AVX2 binary on a CPU
        without it dies with an illegal instruction partway through a long pipeline rather
        than failing clearly at install time.
      - Archive extraction refuses zip-slip members, absolute paths and tar links, and
        sets the execute bit on POSIX — a zip built for Windows carries no mode, and M0.4
        was already bitten by exactly that with the pre-commit hook.
      - Reuses the M2.2 downloader rather than reimplementing resume; `fetch_file` was
        refactored onto a shared `download()` so the three corruption cases are fixed in
        one place and not two.
      - *Verified live:* installed both tools, confirmed PLINK reports the pinned version
        and Beagle matches its digest, and confirmed the archive is cleaned up afterwards.
- [x] **M2.6** `genetics refs fetch|status|verify|licenses` CLI, plus `genetics tools
      list|install|status` as M2.5's entry point. Every command is `--json`-capable
      ([AGENTS.md §3](AGENTS.md)) — a command reachable only as human text is one an agent
      cannot review, and M13.5's parity test starts being true or false here.
      - `refs status` reports **what a missing source costs**, not just that it is absent:
        "the rare-variant frequency gate (M7.2)" rather than "0/1 files".
      - `refs fetch --dry-run` exists because the required set is 92 GB and learning that
        afterwards is not useful. It also shows licence blocks before any bytes move.
      - Progress goes to **stderr**, throttled, so piping `--json` stays clean and a
        per-megabyte callback on a 63 GB file does not spend real time on terminal writes.
- [x] **M2.7** Offline guarantee, **in-process half** (`genetics/testing/network.py`,
      `tests/conftest.py`). An autouse fixture refuses every non-loopback connection and
      name lookup for the whole suite; `@pytest.mark.network` is the opt-out and nothing
      carries it.
      - **The end-to-end half moved to [M4.10](#m4--run-bundle--first-ui)**, because it
        cannot be true yet: "a full run succeeds" needs a run, and the run bundle is M4.1.
        Checking this box on a narrower test than the words describe is the exact failure
        the M2 review was about — a claim the code does not honour.
      - Split rather than deferred whole, because the property is cheap to *keep* and
        expensive to *recover*. Today exactly one module in `src/` opens a socket
        (`refs/fetcher.py`'s `UrllibTransport`) and no test touches the network at all.
        Every milestone from M3 on adds modules; a stray `urlopen` in a card loader or a
        per-trait PGS fetch would otherwise surface at M15.1 with work built on top of it.
      - **Installed at session scope, lifted per test** (agent-review fix). A function-scoped
        fixture left every session- and module-scoped fixture uncovered, because pytest
        builds higher-scoped ones first — and a module-scoped "fetch the reference once"
        fixture is the likeliest home a stray network call will ever have. Verified failing
        before the fix. `allow_network()` is the per-test lift for `@pytest.mark.network`.
      - **Loopback is allowed on purpose.** M4.3 binds FastAPI to localhost and M13.5
        drives it; a guard that broke the local server would be deleted rather than
        narrowed by whoever hit it first — M0.3's "a scanner that cries wolf gets
        bypassed" applied to this one.
      - Resolution is blocked as well as connection: DNS is itself traffic, it is the step
        that discloses *what* is being fetched, and it still has the hostname in hand for
        the error message where `connect` has only an anonymous IP.
      - `NetworkAccessError` derives from `RuntimeError`, **not `OSError`** — `urllib`
        wraps `OSError` into `URLError`, so as an `OSError` the refusal would arrive
        disguised as an ordinary connection failure, which is precisely what fetch code is
        written to retry or report calmly.
      - *Demonstrated, not assumed* ([M0's lesson](#progress-log)): with `block_network`
        stubbed to a no-op all six guard-asserting tests fail — and the run takes 23s
        instead of 0.17s, because those are real DNS timeouts. The tests drive
        `UrllibTransport` itself, not a bare socket no shipped code resembles.
      - **Cannot see a subprocess, by construction.** PLINK 2, Beagle, Java and R get
        their own address spaces. That gap is what [M4.10](#m4--run-bundle--first-ui) closes,
        with a Linux network namespace — and only on Linux, so on Windows this guard is still
        the whole of the offline story.

---

## M3 — Card engine & knowledge pack

*This is the heart of the product. Get the schema right before writing many cards.*

- [x] **M3.1** Card schema (`engine/cards.py`, `engine/sections.py`, `engine/citations.py`),
      versioned, with `knowledge/README.md` as the authoring guide. Unknown keys are
      rejected at every level: in a format this full of optional fields, a silently ignored
      key looks exactly like one that had no effect.
      - **A card cannot author its own confidence.** `confidence`, `tier`, `score` and
        `reliability` are refused as card-level keys, with an error naming M3.3.
        [AGENTS.md §6](AGENTS.md) requires confidence to be computed; if a card could
        assert `confidence: high` somebody eventually would, the calculator would become
        decorative, and the rarity inversion §4.1 calls the most important thing the
        interface communicates would be overridable by whoever authored the card. Evidence
        *inputs* are authored; the output is not. `evidence.tier` therefore uses a
        deliberately **disjoint vocabulary** from M3.3's output ladder — a test asserts the
        two share no value, because two ladders with one name get conflated in a week.
      - **The genotype map must be exhaustive.** Every genotype the declared alleles can
        produce needs an outcome. `ingest/keys.py` states the governing problem — "no
        result" is indistinguishable from "no variant" — so an author with nothing to say
        about heterozygotes has to say *that*, where a reader can see it. This is the
        card-level form of the ban on silently empty sections. It is decidable at load
        with no reference data and no QC result, because the normalized table writes a
        haploid call **doubled** and keeps ploidy in `call_status` (M1.1): there is one
        genotype vocabulary, not one per chromosome, so a card need not know the sample's
        sex to be complete.
      - **Citations are structured and format-checked**, not prose. A free-text field
        satisfies "has a citation" while carrying `see Smith et al.`, which is exactly the
        fabrication [§6](AGENTS.md) forbids — unresolvable, so nobody checks it. `title` is
        required beside the identifier because a title that does not match its DOI is the
        most visible sign of a fabricated reference in a diff, which is what M15.6 audits.
        A resolver-prefixed DOI is **stripped, not rejected**: telling an author their
        working DOI is malformed makes them edit until the message stops, which is how a
        good citation becomes a wrong one.
      - **Impossibility cards need no citation, deliberately.** Their claim is about the
        assay, not the person; demanding a DOI for "an array does not measure methylation"
        pushes an author toward citing something tangentially related, which serves a
        reader worse than citing nothing. `impossibility_reason` is the requirement
        instead.
      - **Both rsID and coordinates are required**, so M3.5 can cross-check them against
        dbSNP — either alone is unverifiable and a disagreement means one is wrong. This is
        also why **`knowledge/` ships empty**: a card written today needs GRCh37
        coordinates from memory, the invented-data failure [§6](AGENTS.md) forbids and the
        same reason `qc/build_anchors` and the `spike_ins` hook shipped empty. A test
        asserts the emptiness so whoever adds the first card meets the reasoning.
      - **Indel alleles are refused** ([§4.2](AGENTS.md)) and **multi-variant cards are
        refused** with a pointer to M10.1–M10.2: haplotype interpretation needs phase, and
        a genotype cross-product is a different, wrong answer. `variants:` stays a list so
        the shape survives — declared, validated, not executed, the M2.1 precedent.
      - **Outcome names must be quoted strings** (review fix). `yes`/`no` are the obvious
        names for a binary trait and unquoted they are YAML 1.1 *booleans*; `str()`-coercing
        both sides "worked" while renaming the outcome to `False`, and quoting one side only
        produced an error blaming an outcome plainly present in the file. Refused now, with
        a message that says what to type. Names colliding after trimming are refused too —
        a dict comprehension had been keeping the last, dropping a whole outcome silently.
      - Templates are plain `{name}` substitution, not Jinja: knowledge files are data, and
        the check is a parse with no evaluation. Placeholders resolve against a registry
        where each **declares the milestone that supplies it**, so `{frequency}` is refused
        by name ("supplied by M7.2") rather than rendering blank or reading as a typo.
      - Diverges from this roadmap's original sketch in one place: `summary_template` /
        `detail_template` live **per outcome**, not per card, because the interpretation is
        precisely what differs between genotypes.
      - Study population is a controlled vocabulary (1000G superpopulation codes) rather
        than free text, because M9.5 has to *compare* it against inferred ancestry and
        "European" / "EUR" / "White British" cannot be compared. `UNKNOWN` is a valid value:
        an unstated study population is a real property of the literature, and M9.5 needs
        to see it rather than a guess. Finer labels arrive with the panel in M5.3.
      - *Verified, not assumed:* a **card file does not trip the genotype scanner**. Cards
        are committed and a card names an rsID, chromosome, position and several genotypes
        — the shape of an export row. Had the natural YAML layout tripped it, every card
        commit would be blocked and the reach would be for `--no-verify`, which M0.4 says
        is never acceptable. Now a permanent privacy test. Neutering the confidence
        refusal fails all four of its cases, so that guard is real.
      - One fail-open found on the self-pass and fixed: a card file saved as `.yml` fell
        outside the loader's glob and its cards vanished with no error — a missing card
        being indistinguishable from an unmatched one is the exact confusion the schema is
        organised against. Refused loudly rather than the glob widened, which would have
        blurred the duplicate-id check and the lint target.
- [x] **M3.2** Matcher (`engine/matcher.py`). Resolves card variant keys against the
      normalized table; handles unordered genotypes, hemizygous calls, no-calls, missing
      markers, duplicate probes and strand.
      - **Every card gets a result** ([§0.1A](AGENTS.md)). `match_pack` returns one
        `MatchResult` per card in pack order, never fewer. That is why `MatchStatus` has
        nine members: "no interpretation" has at least seven distinct causes — marker not
        on the array, no call, allele disagreement, indel excluded by policy, contradictory
        call at a single-copy locus, probes that disagree, strand undecidable — and they
        mean entirely different things to a reader. A caller receiving fewer results than
        cards could not reconstruct which went missing or why.
      - **Strand ambiguity escalates only when it changes the answer.** At an A/G site a
        flipped call reads C/T, which the card declares nowhere, so the error announces
        itself. At an A/T or C/G site the complement is the same letter pair and a flip is
        invisible — but a heterozygote is *its own complement*, and where both readings map
        to the same outcome the answer is identical either way. So: complement the genotype
        and escalate only if the outcome would differ. Anything blunter either misses real
        inversions or flags thousands of harmless ones, which is M0.3's cries-wolf lesson.
      - **Duplicate probes are resolved by agreement, never by choice** — the decision M1
        explicitly deferred here after finding 656 repeated positions in the real export.
        Agreement gives one answer with a note; disagreement is `DUPLICATE_CONFLICT`,
        because picking the first or the "better" row would manufacture an answer the data
        does not contain. A no-call beside a call is not a disagreement. Agreement is
        judged on a **strand-independent** form (review fix): two probes for one variant can
        sit on opposite strands, so `AG` beside `CT` is agreement written twice, and raw
        string comparison had been reporting it as a conflict — the vendor's forward-strand
        claim sneaking back in one function below where the module rejects it.
      - `MatchResult` carries `genotype` (on the card's strand, `None` whenever no strand
        was established) **and** `observed_genotype` (as the export wrote it). One field
        meaning both, depending on status, is read wrongly the first time a card renders.
      - **The indel rule is called, not reimplemented** — `matchable_mask` exactly as M1.6
        asked. An excluded indel gets its own status rather than reading as an allele
        mismatch: a policy limit and a card describing the wrong variant are different
        facts. A test with a populated whitelist proves the policy is read rather than the
        default hard-coded.
      - **A homozygous strand flip is corrected but labelled as weaker evidence.** Working
        this through produced the milestone's one genuine surprise: for a biallelic card
        the declared pair and its complement together cover all four bases, so a
        *homozygote* always has some reading available and `ALLELE_MISMATCH` is unreachable
        for one — while a heterozygote can and does fail both strands (`A`/`C` against
        `A`/`G`). That is [`ingest/keys.py`](AGENTS.md)'s LocusKey/VariantKey asymmetry
        showing up as behaviour: one visible letter cannot separate "reverse strand" from
        "a different variant here". The flip is still applied, because an off-strand marker
        is ordinary and a mis-placed card is M3.5's job to catch, but the two cases carry
        different caveats and a test asserts they differ.
      - `MatchResult` and the row records inherit `NoGenotypeRepr`; computed caveats are
        kept separate from the card's authored ones, since one is a fact about this
        sample's data and the other about the literature. A privacy test asserts no
        generated `reason` or caveat is export-row-shaped — these strings reach the CLI and
        the run bundle, both of which are scanned.
      - Tested end to end through real ingest, not only against hand-built frames, so an
        assumed dtype or allele-order convention cannot pass unnoticed.
- [x] **M3.3** **Confidence calculator** — computed, never authored
      ([AGENTS.md §6](AGENTS.md)). Inputs: evidence tier, effect size, replication,
      **population allele frequency (inverted — rarity lowers confidence)**, imputation
      quality where applicable, ancestry match to the source study.
      Output: a tier from `well-established` → `likely-artifact`, plus the numeric inputs
      for display.
      - *Acceptance:* a rare ClinVar pathogenic hit scores `likely-artifact` and carries
        the empirical PPV for its frequency band; a common large-effect trait variant
        (e.g. HERC2 eye colour) scores `well-established`.
      - Implemented as an immutable, structured result: authored evidence, effect,
        replication, allele frequency, ancestry fit, and direct/imputed call provenance
        remain inspectable inputs beside the computed five-tier result. Population AF
        below `0.001%` is a hard `likely-artifact` ceiling with the measured `0.16` PPV;
        ancestry and imputation quality can only lower confidence. Acceptance cases cover
        both the rare-pathogenic and common-large-effect ends of the ladder.
- [x] **M3.4** Evidence assembly: bundle genotype + card + frequency + citations into a
      renderable result object. Never drop a card for low confidence
      ([AGENTS.md §0.1A](AGENTS.md)).
      - Assembly is cardinality-preserving: every matcher result becomes one evidence
        record, including absent, no-call, ambiguous, excluded, and likely-artifact
        results. It applies the rarest observed frequency and retains
        genotype/call-source/reference provenance without embedding a confidence shortcut
        in authored data.
      - **An incomplete frequency set degrades one card, not the pack** (review fix). It
        first *raised* when the reference had no frequency for an observed allele — which
        loses all 31 findings because one gnomAD row was thin, and that is the
        low-confidence filtering [§0.1A](AGENTS.md) forbids, arriving as an exception
        rather than as a policy. gnomAD does not price every allele of every variant, and a
        strand-ambiguous site legitimately adds a complemented allele the reference never
        reported. The card now renders with no frequency, a caveat naming the missing
        allele, and M3.3's `moderate` ceiling for unknown frequency — so the gap is visible
        and nothing is scored common on the strength of a missing number. A frequency for
        an allele the card does not declare is still refused: that is another variant's
        calibration, not thin coverage.
- [x] **M3.5** Card linting: `genetics cards lint` verifies schema, citation presence,
      resolvable variant keys, and template rendering. Wire into CI.
      - `genetics cards lint` has explicit schema-only and full-reference modes; the full
        mode fails closed if dbSNP or provenance is absent/stale and is wired into CI for
        schema checks. The real build-157 fetch produced **1,145,977,318** indexed rows,
        **21,562,332** one-to-one merge mappings, and **23,340** explicitly unresolved
        merge records. Output digests, row counts, input digests, parameters, and transform
        versions are provenance-bound. Full lint resolves all 31 authored variants.
- [x] **M3.6** **Seed pack: Traits, morphology & sensory** (~25–40 cards). Highest
      confidence content and the best demo: HERC2/OCA2 eye colour, ABCC11 earwax + body
      odour, TAS2R38 bitter taste, MCM6 lactase persistence, ALDH2 flush, asparagus
      anosmia, cilantro aversion, photic sneeze, hair texture/colour, freckling, male
      pattern baldness, morning/evening preference.
      - Shipped **31** single-variant, direct-call-compatible, primary-literature-backed
        cards across
        pigmentation, hair/morphology, sensory traits, metabolism, and circadian biology.
        The pack renders 186 genotype-specific templates and records effect units, study
        population, sample size, replication status, caveats, and DOI/accession citations.
        A coordinate/allele/DOI/effect audit and the full dbSNP lint both pass.
- [x] **M3.7** Impossibility cards for [AGENTS.md §3.2](AGENTS.md): methylation/epigenetic
      age, somatic/tumour, CNVs (SMN1, RHD, alpha-thal, CYP2D6 hybrids), Y-STRs, mtDNA
      heteroplasmy, de novo mutations, telomere length, relative matching.
      - **12 cards under `knowledge/impossibilities/`**, one per §3.2 entry except the
        copy-number bullet, which names four specific findings inline and therefore gets
        five cards — the general limit plus SMN1, alpha-globin, RHD and CYP2D6.
      - **§3.2 is read out of AGENTS.md and compared against the pack, both ways.** §3.2
        asks for a "live register"; a register in one file and the cards it describes in
        another is [M0.4's lesson](#progress-log) waiting to happen — two ways of naming one
        set diverge, and the one the automation reads is the one that matters. A new bullet
        with no card fails, and a card no bullet declares fails.
      - **Placed in the section each one qualifies, not in an appendix** (M14.6). CYP2D6
        sits with the pharmacogenes because §3.1 asks for it there by name; SMN1 and
        alpha-globin sit with carrier status, where §3.2's "invisible unless stated"
        incompleteness actually bites. This is why `physical_health`, `genome_structure`,
        `reproductive`, `pharmacogenomics` and `ancestry` stop being empty sections.
      - **The pack ships zero citations, deliberately.** M3.1 exempted these cards because
        the claim is about the assay rather than the person; a test now asserts the
        exemption stays unused, since an author reaching for a reference to make an
        impossibility card look better is exactly the tangential-citation failure the
        exemption was written to prevent. `impossibility_reason` carries the justification.
      - **Overlap with M10.3 and M11.6 resolved here rather than discovered twice.** Both
        boxes describe a card this milestone had to write anyway. M3.7 owns the §3.2
        register entry; what remains for [M10.3](#m10--pharmacogenomics) is rendering
        `cyp2d6_structural_variation` beside the called diplotypes, and for
        [M11.6](#m11--hla-immunogenetics--carrier-status) the *section-level* completeness
        statement, which is a different claim from the two per-gene cards.
      - Each card's caveat points at the adjacent question that **is** answerable — Y-SNP
        haplogroups beside Y-STRs, mtDNA haplogroup beside heteroplasmy, ROH beside both
        CNVs and relative matching. Without it "not determinable" reads as "nothing here is
        knowable", which is its own kind of wrong.

---

## M4 — Run bundle & first UI

*End of the vertical slice: after this milestone there is a working app, with one
section, that proves every layer.*

- [x] **M4.0** The pipeline command (`run/pipeline.py`, `cli/run_cmd.py`): `genetics run
      --input <export>` — ingest, QC, match, assemble, save. **Added after M4.4, numbered
      before M4.1, and built out of order on purpose.** It was missing: the definition of
      done names `genetics run` and no milestone item owned it, so `write_bundle` had no
      caller outside the test suite. M4.5 would then have been built against bundles a
      conftest wrote by hand — the failure [M4.2](#m4--run-bundle--first-ui) named when it
      refused a `--runs-root` flag, one layer up. Numbered 4.0 rather than inserted as a new
      4.5 because `M4.5` is referenced from eight places outside this file, one of them a
      live test assertion, and renumbering would have edited working code to relabel work
      that had not changed.
      - **The stages compose without adapters** — `ingest` → `match_pack` → `assemble_pack`
        → `write_bundle`, each consuming exactly what the last returns. Nothing is reshaped
        at the seams, because a translation layer here would be a second description of
        formats that already have one, which is the M0.4 / M3.7 / M4.1 failure again.
      - **The one thing the pipeline actually decides is the observation layer**, and it is
        a decision rather than a default. `assemble_pack` refuses an interpretation card
        without `ObservationEvidence` — "silently assuming a direct call could score an
        imputed observation as perfect" — so somebody has to state it. At this milestone
        there is no imputation stage and no ancestry fit, so the honest observation is
        `CallSource.DIRECT`, no frequencies, no ancestry match, written once in
        `pipeline.observations()` where **M5 and M8 have an obvious place to change it**.
        A test pins it and names the milestone that will replace it.
      - **The visible cost is that nothing scores above `moderate` yet, and that is
        correct.** An unknown frequency and an unknown ancestry fit each contribute a
        neutral 0.5, and the breakdown records both as `None` — so a saved run reads as
        "these were not known" rather than "these were known and average". Against the
        owner's real export, 26 matched cards land at `moderate` and one at `limited`. The
        tempting fix — assume a frequency — is the rarity inversion in
        [AGENTS.md §4.1](AGENTS.md) going quiet.
      - **A `DIRECT` observation is recorded even for a card whose marker is absent.** It
        reads oddly until you read it as a statement about the *run*: this pipeline has no
        imputation stage, so nothing in it could have been imputed. That is exactly the
        distinction M4.1 added `observation` to the bundle to preserve, and dropping the
        record for unmatched cards would discard it for the only cards it can distinguish.
      - `analyse()` and `save()` are two functions so the pipeline can be run without
        writing: M4.10 needs that, and a test asserting on card content should not have to
        create a directory. A test asserts the store is still empty after `analyse`.
      - **Output is aggregates, and scanned on both branches.** Counts by status, counts by
        tier, the run id. This is the command whose whole input is a genome and the natural
        "show me what matched" edit lands right here, so both paths go through
        `assert_no_genotype` — M1.8's lesson, where the first cut guarded JSON and left the
        human render open. `genetics runs show` prints the genotypes, deliberately exempt
        ([M4.2](#m4--run-bundle--first-ui)). Both halves are asserted, in both directions,
        so neither can be "fixed" into the other.
      - **Every match status prints, including the zeros**, for the same reason `runs list`
        reports a staging directory: "nothing was strand-ambiguous" must not read as
        "strand ambiguity is not checked".
      - **No committed fixture can produce a matched card**, which was not obvious and cost
        a rewrite of the test plan. `genetics.testing.fixtures` leaves `spike_ins` empty on
        every fixture on purpose ("populating it now would mean inventing GRCh37
        coordinates"), so the whole synthetic corpus returns `marker_absent` for every
        interpretation card — indistinguishable from a broken matcher. The pipeline suite
        renders its own spiked export from the same generator instead. **M4.5 needs to know
        this**: the dashboard cannot be developed against `tests/fixtures/synthetic` and see
        a single card face.
      - No `--runs-root` and no `--run-id`: `GENETICS_DATA_DIR` addresses the store (M4.2)
        and ids are generated (M4.1). A flag whose only caller is a test is the same mistake
        wearing a different hat.
- [x] **M4.1** Run bundle format (directory or single file). Immutable. Records: engine
      version, knowledge-pack version, every reference version, tool versions, QC report,
      all scored cards, timestamps. **Gitignored; written outside the repo by default.**
      - **A directory** (`genetics/run/bundle.py`): `manifest.json` plus `qc.run.json` and
        `cards.run.json`. M5 adds PCA coordinates, M8 dosages and M9 per-score tables, none
        of which belong in one blob that must be parsed whole to read a card.
      - **The format's job is to still say the same thing after the code moves on, so a
        bundle stores rendered results rather than card ids.** Re-rendering from the
        knowledge pack at read time is cheaper and would pass every other test; it also
        means editing a card tomorrow silently rewrites what a run said today, and a saved
        run is the thing a person read and may have acted on. *Demonstrated by deleting the
        pack after the write and reading the bundle anyway.*
      - **Reading returns strings, not engine enums.** Re-hydrating a `Section` is what
        breaks when a later version renames a member, and M4.2 wants a months-old bundle to
        fail with a *version* error or not at all — never `'traits' is not a valid Section`
        four frames down.
      - **Immutability is refusal plus detection, not permissions.** A write refuses an
        existing run id, the payload is built under `.incoming-<id>` and promoted by one
        rename, and every payload digest is re-checked on read. Mode bits were rejected:
        M0.4 was already bitten by cross-platform mode handling, and a read-only flag on
        someone's own data directory is advisory. The manifest is deliberately **not**
        self-digested — that regress ends in a file whose own integrity is unverifiable
        while looking like a guarantee. What this catches is corruption, truncation and
        hand-editing; tampering is out of the threat model and the docstring says so.
      - **The genotype scan covers the manifest and the QC report, and deliberately not the
        cards.** `cards.run.json` holds per-card genotypes by design, and a guard that fails
        on correct output is one somebody switches off ([M0.3](#progress-log)). The manifest
        is the file a person pastes into a bug report, which is exactly why it is the one
        scanned. Both scans are driven with input they must reject, so neither can pass
        vacuously.
      - **`read_bundle` landed here rather than in M4.2**, because a format with no reader
        cannot demonstrate any of the above. So did the cross-version rule, once review
        showed the gate was wrong. M4.2's remaining work is list, delete and the CLI
        surface.
      - **A bundle is readable by any engine at or above the version that wrote it**, under
        one rule: payload keys may be added, never removed and never repurposed. The first
        cut gated on equality, which reads fine while one version exists and orphans every
        saved run at the first bump — and since adding a key *is* a bump, and M5, M8 and M9
        all add payload, that bump is scheduled. Corrected in review; a key whose meaning
        changes gets a new name instead.
      - Run ids are timestamp-plus-random, never a digest of the input: a stable digest is a
        persistent pseudonymous identifier for one genome sitting in every directory
        listing and log line — genotype-derived in the one place a bundle's contents are not.
        A run id must also be a **plain directory name**, checked on the outcome rather than
        by blacklisting separators: `root / "D:elsewhere"` discards `root` on Windows and
        contains neither `/` nor `\`, so the character test the self-pass replaced would
        have let destination and staging point at different places.
      - `observation` (call source, imputation quality, ancestry fit) is recorded beside
        `confidence` rather than inside it, because `confidence` is `None` for every card
        that did not match. Without it a saved run cannot tell "the marker is not on this
        array" from "imputation was attempted and failed" — a distinction that starts
        mattering at M8, by which point adding it would cost a format bump.
      - Payload filenames carry a `.run.json` suffix so `.gitignore` can key on them. **The
        pre-existing `*.run.json` rule was not enough**, and the first test of it could not
        tell: `!/knowledge/**/*.json` appears later in the file and wins, so a bundle
        dropped under `knowledge/` was committable while a test grepping for the rule's text
        passed. A re-ignore rule now covers it, the test asks `git check-ignore` across five
        directories, and a companion test asserts card files stay trackable so the fix
        cannot be made by breaking the corpus. Third line of defence behind writing outside
        the repo and refusing an in-repo destination outright.
- [x] **M4.2** Save / load / list / delete runs (`run/store.py`, `cli/runs_cmd.py`):
      `genetics runs list|show|delete|prune`. Save and load had shipped with
      [M4.1](#m4--run-bundle--first-ui); this is the store around them — the directory the
      bundles live in — plus the CLI. Four decisions are load-bearing:
      - **Listing reports; it does not validate.** It reads each `manifest.json` and opens
        no payload. The cost argument is the obvious one (M8 dosages, M9 score tables), but
        the real one is that `read_bundle` *raises* on damage, so a listing built on it
        would fail entirely because one directory out of forty is corrupt — and listing is
        the command someone runs *because* something is wrong. Damage becomes a row with a
        status, the way `doctor` reports a missing tool rather than exiting red on a fresh
        checkout. `--verify` asks the stronger question, and `RunListing.verified` records
        which was asked, so `readable` can never be read as `verified`. The status is named
        `readable` and not `ok` for that reason.
      - **A staging directory is skipped as a run and reported as itself.** Skipping
        `.incoming-` by shape was the requirement; skipping it *silently* would be the
        M3.3–M3.6 finding about `refs status` — a stale multi-GB intermediate reported as
        nothing at all, with no line saying it was there. So it is counted, sized, and given
        a command (`runs prune`).
      - **Deletion identifies its target rather than trusting the name.** The writer's own
        `check_run_id`, then containment on the *resolved* path (a plain name can still be a
        symlink out of the store, which a name check cannot see), then the directory must
        declare itself a bundle. **The order of that last check was wrong first, and running
        the CLI is what showed it**: identifying a bundle by its filenames alone refuses to
        delete one written by a *newer* engine, because it carries payload this version has
        never heard of — leaving a run the user can neither read (version gate) nor remove.
        The manifest is asked first; filenames are the fallback for wreckage that has no
        manifest left to speak for it.
      - **The store is addressed through `GENETICS_DATA_DIR`, with no `--runs-root` flag.**
        A test-only way to name the store would be a second name for one thing — the failure
        this project has now hit at M0.4, M3.7 and M4.1 — and the tests would then exercise a
        path no user takes.
      - One defect fixed in M4.1's reader while building on it: `manifest["files"]` maps a
        name to a digest and both readers turn it into `directory / name`, so an edited
        manifest naming `../elsewhere` sent the listing to stat — and `read_bundle` to
        *hash* — a file outside the bundle, reporting the result as this run's integrity.
        Not a hole in the threat model (tampering is explicitly outside it); the point is
        duller. A manifest naming a file somewhere else is **damaged**, and saying so beats
        a digest mismatch against a file the user never associated with the run. Checked on
        the outcome, same as `check_run_id`.
      - Privacy split inherited from the bundle format rather than reinvented: `runs list`
        is scanned with `assert_no_genotype` on **both** branches (M1.8's lesson — the first
        cut there guarded JSON and left the human render open), `runs show` is not, because
        a card's summary states the reader's own genotype *by design* and a guard that fails
        on correct output is one somebody switches off ([M0.3](#progress-log)). Both halves
        are asserted, so neither can be "fixed" by accident.
      - Standing constraint from M4.1, unchanged: `read_bundle` rejects unknown payload keys,
        so **adding a field to the payload requires bumping `BUNDLE_FORMAT_VERSION` in the
        same commit**. A test pins the payload's whole nested shape. The compatibility rule
        is additive — **keys may be added, never removed and never repurposed** — which is
        what lets a reader accept any bundle at or below its own version.
- [x] **M4.3** FastAPI app skeleton (`web/config.py`, `web/app.py`), binds localhost only,
      no external requests. A skeleton on purpose — one placeholder page and `/healthz` —
      but every claim in that sentence is enforced rather than documented:
      - **The bind address is validated at construction and the wildcard is refused however
        it is spelled.** The realistic route to `0.0.0.0` is not malice, it is someone
        hitting a connection refused from a VM or a phone and fixing it — which publishes an
        unauthenticated genome browser to the LAN. `is_local_address` treats the wildcard as
        local, correctly, because it answers *"does this leave the machine"* about an
        outbound connection; as a **bind** address it means the opposite, so that is a
        second check rather than a weakening of the shared predicate.
        **The first cut compared against a literal set of three spellings and the review
        walked six more past it** — `::0`, `0::0`, `0000::0`, `0:0:0:0:0:0:0:0`, `[0.0.0.0]`
        and `::ffff:0.0.0.0`, each of which binds every interface. Now parsed with
        `ipaddress` and refused on `.is_unspecified`. That is the same lesson `check_run_id`
        reached about paths, `payload_name` about manifest entries and M2.5 about archive
        members: **check the outcome, not the input forms.** A blacklist of spellings is a
        claim that somebody enumerated a notation exhaustively.
      - **"Binds localhost only" is not the same as "only this machine can reach it", and
        saying it was would have been the overclaim this project keeps correcting.** A page
        on the open internet can point a hostname it controls at `127.0.0.1` and have the
        visitor's own browser read this app — DNS rebinding, and the request genuinely
        arrives on loopback. The only thing that distinguishes it is the `Host` header, so
        the app checks it (421). Starlette's own `TrustedHostMiddleware` splits that header
        on `:` and turns `[::1]:8765` into `[`, so a user binding to `::1` would be refused
        by their own server; hand-rolled for that reason, and the case is tested.
      - **"No external requests" has two halves and needs two mechanisms.** Server side is
        structural — a test parses the imports of every module under `web/` and fails if one
        reaches urllib, http.client, socket, requests, httpx or the project's own fetcher
        (M1.3's reasoning about vendor adapters, at a boundary where the leak is a genome).
        Browser side is a `Content-Security-Policy` of `default-src 'self'`, sent on **every**
        response including errors, because the miss that matters is a template referencing a
        CDN: that is an outbound request from the *user's* machine, about that user's genome,
        which nothing in this process would ever see. M4.4's static check is the other half
        of the same claim. FastAPI's interactive docs are **off** for exactly this reason —
        Swagger UI and ReDoc load from a CDN by default.
      - **`is_local_address` moved to `genetics/netaddr.py`** so the offline guard (M2.7) and
        the server's binding policy share one definition. Two copies would eventually
        disagree, and the symptom would be the suite blocking the very server it drives.
      - `create_app` is a factory, not a module-level `app`: an import-time instance runs
        this app's configuration checks during `genetics --help`, and a test could not give
        it a different runs root without reaching into globals. `/healthz` counts runs by
        calling `store.list_runs` — the same function `genetics runs list` calls
        ([AGENTS.md §3](AGENTS.md): one engine, two front-ends) — and *reports* an unusable
        `GENETICS_DATA_DIR` rather than failing to construct, since an app that cannot start
        cannot serve the page explaining why.
      - `genetics serve` is **M4.9**, not here. Verified against a real uvicorn process by
        hand (`uvicorn --factory genetics.web.app:create_app`), and by a test that starts the
        server on an ephemeral port and reads back the address the kernel actually bound —
        `TestClient` never opens a socket, so nothing else in the file could tell a real bind
        from a config value carried around and ignored.
- [x] **M4.4** Vendor htmx + Alpine.js into `web/static/vendor/` (`web/assets.py`,
      `web/vendor.yaml`), with the no-external-URL test. htmx 2.0.10 (0BSD) and
      Alpine 3.16.1 (MIT), pinned by sha256 and served from `/static`.
      - **The Alpine *CSP build*, not the standard one, and the difference was counted
        rather than assumed.** The standard bundle contains a `new Function` and so needs
        `script-src 'unsafe-eval'`; `@alpinejs/csp` contains none and calls no `eval`.
        Weakening the policy was the easier road and the one [M4.3](#m4--run-bundle--first-ui)'s
        own docstring warns about — a strict CSP relaxed later under pressure from a single
        asset, on a page whose subject is somebody's genome. **The cost lands on M4.5+ and is
        real:** component logic must be registered with `Alpine.data('name', …)` and
        referenced by name; inline expressions like `x-on:click="open = !open"` do not work.
        Stated in `vendor.yaml` rather than left to be discovered.
      - htmx keeps one eval path, reached only by `hx-on:` and the `js:` prefix, gated behind
        `htmx.config.allowEval`. The page sets it false **through a `meta` tag, because
        `script-src 'self'` blocks inline scripts** — configuring htmx the ordinary way would
        have been the first thing on the page to violate the policy the page advertises.
      - **"No external URL" is not quite the property that matters, and the test says so.**
        Alpine's bundle contains `https://alpinejs.dev/plugins/…` inside the text of an error
        it throws — a documentation pointer, not a fetch. Failing on it would be a guard
        that is wrong about correct code on day one ([M0.3](#progress-log)). So: **what
        reaches a browser** (rendered HTML of every route, templates, first-party static
        files) is held to the literal rule; **everything else under `web/`**, vendored
        bundles and our own Python alike, is scanned for the shapes that *fetch* — `src=`,
        `href=`, `url(`, `@import`, `fetch(`, `new Worker(`. Holding Python to the literal
        rule would have made the docstring explaining the rule its own first casualty.
        The scanner is driven with seven references it must catch, including the
        protocol-relative `//host` form that reads as a comment and fetches anyway.
      - **Committed, not fetched** — the opposite of [AGENTS.md §1.4](AGENTS.md) for
        reference data, and the difference is what the file is for: 114 KB the *browser*
        needs before the first paint. Fetching at runtime is the CDN request M4.3 forbids;
        fetching at install time makes an offline-first tool's UI need the network.
      - **Alpine's npm package ships no LICENSE**, and MIT requires the notice to travel
        with copies — so it was fetched from the matching `v3.16.1` git tag, not `main`,
        which would have pinned a notice describing different code. A test asserts every
        asset has non-trivial licence text.
      - Two files were moved out of `static/` because everything in it is fetchable: the
        `__init__.py` (which would have served this project's source and its `__pycache__`),
        and the vendor manifest (the one file whose job is to hold external URLs — leaving it
        there would have forced the no-external-URL test to carve out an exception on the day
        it was written). Both have tests.
      - Verified against a real uvicorn process, not only `TestClient`: both bundles served
        byte-for-byte by sha256, `Cache-Control: no-store`, the security headers present, and
        the `Host` check covering the mount — a static mount outside it would reopen the
        DNS-rebinding hole for the part of an app easiest to forget.
- [x] **M4.5** Dashboard shell (`web/views.py`, `web/templates/`, `web/static/app.{css,js}`):
      section nav, run selector, QC banner. Two routes — `/` opens the newest readable run,
      `/runs/{id}` opens one by name. Jinja2 arrives here and is now a dependency; `web/app.py`
      kept its markup inline until there was something to render.
      - **The scan covers two *regions*, not the page, and that is the decision the whole
        file is arranged around.** M4.6 puts card faces here and a card's summary states the
        reader's genotype by design — so a whole-page `assert_no_genotype` would start
        failing on correct output the day cards land, and [M0.3](#progress-log) settled what
        happens to such a guard. So the banner and the selector are rendered **as their own
        templates, scanned, and passed in as already-safe markup**. `{% include %}` was the
        obvious spelling and would have made the scanned region a comment rather than a
        fact: there is no way to scan half of one render pass. Both scans are
        mutation-tested. This is M4.2's `runs list` / `runs show` split, one layer up.
      - **A view model field is only real if a *real* payload populates it.** The banner
        read `duplicates.duplicate_rows`, a key no QC report has ever had — `DuplicateSummary`
        carries `duplicate_rsids` and `duplicate_positions` — so the cell rendered `-` on
        every run ever saved, reading as "not measured" when it had been measured. It
        survived a self-pass *and* a field-coverage test because the test invented its own
        payload and therefore agreed with the reader about a shape neither shared with QC.
        The banner tests are driven by `QCReport.to_dict()` now, with one asserting every
        field resolves. On the owner's real export the cell says 656.
      - **A view model sits between the bundle and the templates.** `read_bundle` returns
        strings and mappings, not engine enums, precisely so a months-old run fails with a
        *version* error or not at all ([M4.1](#m4--run-bundle--first-ui)) — and a template
        reaching into `bundle.qc["call_rates"]["call_rate"]` puts that fragility straight
        back, now surfacing as a Jinja error mid-page. Everything is read with `.get`, so a
        QC payload missing every key still renders a banner: the run worth looking at is
        the damaged one.
      - **"No silent empty sections" is a property of `section_views`, not of markup.** All
        thirteen render always, in AGENTS.md §3.1 order, whether or not the run has anything
        in them — a nav built by grouping the cards present is a nav of however many sections
        happen to be populated, and the reader cannot tell empty from nonexistent. The two
        empty states get **different sentences**: *not built yet, roadmap M9.8* is a fact
        about this tool, *N cards here, none produced an interpretation* is a fact about this
        genome. Collapsing them tells a reader their array lacks a marker when the truth is
        nobody wrote the card. One test asserts the disjunction over the whole nav.
      - **A section this version does not define is reported rather than dropped.** A bundle
        from a newer engine may carry a fourteenth; its cards would otherwise vanish from a
        thirteen-section nav, which is indistinguishable from cards that did not match — the
        confusion `UnknownSectionError` prevents at card-load time, arriving through the nav.
      - **Every state where there is nothing to show is a page, not a stack trace**:
        unusable data directory, empty store, unknown id, unopenable bundle. All four are
        states a person actually arrives in. `/` defaults to the newest **readable** run and
        not the newest run, or a failed last save would open the dashboard on an error.
      - Damaged and newer-format runs stay in the selector as disabled rows with their
        reason, and interrupted saves are named with their size and `genetics runs prune` —
        hiding either is how somebody concludes their analysis was deleted. `future-version`
        gets its own remedy sentence, because calling it damage sends them to a backup they
        do not need.
      - `StrictUndefined` and autoescape are both on. Autoescape because a QC warning is
        generated text and a card title authored text, neither trusted markup; `StrictUndefined`
        because a renamed context key should be an error, not a banner that silently loses
        its call rate and looks like a data problem.
      - **A URL per run, not a client-side swap.** A run is the whole page's state, so this
        is what makes one linkable, reloadable and reachable with Back. htmx earns its place
        at M4.6, where a card modal is genuinely a fragment. The one Alpine component is
        registered with `Alpine.data('runselector', …)` on `alpine:init`, because the CSP
        build evaluates no strings — an inline expression there is silently inert with *no
        console error*. `app.js` loads before the Alpine bundle; swapping those two
        `<script>` lines is a working page that quietly loses every control.
      - **The selector has a `<noscript>` list of plain links, and that is not politeness.**
        A CSP refusal leaves the page in exactly the no-JavaScript state, so the fallback is
        what stops a policy mistake turning into an unusable dashboard.
      - **What is verified and what is not.** Verified against a real uvicorn process, not
        only `TestClient`: page plus all four assets 200 with the security headers, against
        the owner's real 677k export. **Not** verified in a browser — no test here executes
        Alpine, so "the selector navigates on change" rests on reading the CSP build's
        contract, not on watching it work. The `<noscript>` links are the reason that gap is
        tolerable rather than blocking; M4.9 (`genetics serve`) now makes looking at it by
        hand a single command, and the gap is still open.
- [x] **M4.6** Card grid + detail modal (`web/templates/_card*.html`, `views.CardView`).
      **Confidence tier is visible on the card face**, not only in the modal
      ([AGENTS.md §0.1A](AGENTS.md)). Detail view shows effect size, base rate, source
      population, caveats, and clickable citations.
      - **The milestone moved the bundle format, and that is the entry's main content.**
        "Effect size, base rate, source population" is a display requirement that version 1
        could not meet: it stored `confidence.inputs.effect_measure` and `effect_value`,
        which are the *scoring* inputs, and dropped everything that does not affect a score
        — units, the confidence interval, the sample size, the study population, and the
        `context` sentence saying what the number is a proportion *of*. Rendering
        `proportion 0.992` as "the effect size" would have been the vaguer sensitive card
        [§0.1B](AGENTS.md) names as a defect, and the alternative — reaching back into
        `knowledge/` at display time for the rest — is the re-rendering
        [M4.1](#m4--run-bundle--first-ui) built this format to refuse. So **bundle format
        version 2** adds an `evidence` block per card. The additive contract made the bump
        cheap and `test_bundle.py`'s pinned nested shape is what forced it: the first run of
        the suite after adding the key failed with *bump BUNDLE_FORMAT_VERSION in the same
        commit*, which is exactly the job that test was written for.
      - **Base rate is the one of the four that is still missing, and it is named on the
        card rather than approximated.** No card records how common an *outcome* is — that
        is absent from the card schema, not merely from the bundle — so an odds ratio is
        labelled as relative and the detail view says what would be needed to make it
        absolute (M7, M9). The population **allele** frequency sits below under its own
        heading and is never called a base rate: how common an allele is and how common an
        outcome is are different quantities, and letting one stand in for the other is
        precisely the euphemism §0.1B calls a defect. Adding a `base_rate` key that all 43
        cards would leave empty would have been a second name for something nobody has
        written.
      - **Clickable citations are the first thing on this page that points outward, and the
        M4.4 rule had to be re-stated rather than waived.** A card page now carries
        `https://doi.org/…` in an `href`. That is not the property M4.4 protects: an anchor
        causes no request until a person clicks it, and what M4.4 refuses is a *subresource*
        — a script, font or image the page fetches itself, unasked, while a genome is on
        screen. So external hosts are permitted **only** inside an anchor carrying
        `class="citelink"`, `target="_blank"` and `rel="noreferrer noopener"`, and every
        other appearance still fails in every file and every rendered response. The
        exemption is structural rather than a host allowlist, because a `url` citation may
        legitimately point wherever a card author cited. `/` stays on the unrefined list:
        citations are detail-view content, so a resolver URL appearing on the grid fails
        rather than passing by association. Driven with five forms it must still catch,
        including an anchor missing its `rel`.
      - **`Referrer-Policy: no-referrer` stopped being belt-and-braces here.** Until a
        citation was clickable the CSP meant the page could cause no cross-origin request at
        all. Now, without it, the publisher receives the URL the reader came from — which is
        `/runs/<id>/cards/<card_id>`, a card id naming the variant, handed to a third party
        because somebody wanted to read the paper. Two mechanisms, since one is an attribute
        a tidy-up can drop.
      - **Citation URLs are built in Python from a re-validated identifier**
        (`engine.citations.citation_url`), never authored in a template. A stored citation
        is whatever some version of this engine wrote, read back without re-parsing, and for
        a `url` citation the stored `id` *is* the href — so an unvalidated one becomes a
        clickable `javascript:`. Anything that fails the schema's own format patterns, or
        names an accession database with no resolver, renders as text with its identifier
        visible rather than as a link to somewhere plausible. A test asserts every accession
        in the committed pack resolves.
      - **One URL per card, two representations.** htmx sends `HX-Request` and gets the
        modal body; a browser with scripting off follows the same `href` and gets a whole
        page through the same `_carddetail.html`. Two addresses would have routed more
        simply and would have been two names for one card — the failure this project has hit
        at M0.4, M3.7 and M4.1 — and the anchor's `href` would then differ from its
        `hx-get`, which is how a no-JavaScript path rots while every test still passes.
        `Vary: HX-Request` rides on **both** answers; declaring it on one is not declaring
        it.
      - The scan split [M4.5](#m4--run-bundle--first-ui) built is what made this cheap: card
        faces state the reader's call by design and are outside it, the banner and selector
        are inside it. M4.5's test asserting the *whole page* held no genotype was narrowed
        to the two scanned regions rather than deleted, and a second test now asserts the
        card face **does** state the call — without it, the first could be satisfied by a
        page showing nothing at all.
      - **Nothing in the detail view states something it cannot know.** An impossibility
        card renders no effect-size, allele-frequency or how-it-was-called block at all,
        because the first cut filled all three with sentences that were false rather than
        empty — an effect size a card of that kind could not have, and a rarity caveat
        naming a confidence tier it does not have. A card that *did not match* still shows
        the published claim, since a reader is owed what they are being told nothing about,
        but it says so above the figures.
      - **Every URL is built in the view model, never concatenated in a template**
        (`run_path`, `card_path`, `Shell.run_url`, `CardView.url`). Found in review: a run
        id is a directory name and `list_runs` reports whatever it finds, so one containing
        `?` injected a query string into every nav link on its page and one containing `#`
        truncated a card URL into an unopenable one. Six templates were concatenating, and a
        rule enforced in six places is the failure shape this project keeps recording.
      - **A static check for the Alpine CSP build's one trap.** `x-on:click="open = !open"`
        is silently inert under that build: no console error, no violation report, just a
        control that does nothing. M4.4 wrote it down; M4.6 turned it into three tests — no
        directive value that is not a bare reference, no `x-data` naming an unregistered
        component, no method reference app.js does not define. All three verified by
        mutation. It immediately caught a real defect of my own: `cardmodal.close()` used
        `this.$el`, which is the element the *directive* is on — the close button inside the
        swapped fragment — so it would have emptied the button and left the modal standing.
- [x] **M4.7** Sort/filter/group by confidence tier and section (`views.GridQuery`,
      `web/templates/_controls.html`). **Filtering is never the only way to see a card** —
      no default filter, and every hidden card is counted with one click back.
      - **Server-side, in the URL, and never a default**, and each third of that is a
        decision. *In the URL* because an arrangement is state somebody wants to link and
        return to — M4.5's argument for a run having its own address, one level down.
        *Server-side* because M4.7's rule is a rule about what the page must show, and the
        only place such a rule can be asserted is where it is computed; in Alpine it would
        live in a browser where the Python suite cannot see it. *Never a default* because
        the way to break §0.1A is not a bad filter, it is a default one — applied before the
        reader knew there was a decision.
      - **An unrecognised filter value is dropped and reported, not obeyed.** `?tier=strng`
        treated as a filter matches nothing and shows an empty grid, which reads as *this
        run found nothing*; dropped, it shows everything, which is merely unfiltered. Under
        §0.1A the safe failure for a filter is always to show more — and then to say so,
        because silently ignoring it is how somebody concludes the control is broken.
      - **The self-pass found the controls and the parser disagreeing.** Tier checkboxes
        were built from the tiers *present in the run*, so a bundle from a newer engine got
        a checkbox for a tier the parser rejects: ticking it produced "ignored tier=…" and
        no filtering — a control that renders, looks live, and lies. One function now
        defines the filterable set for both, and its cards remain visible, grouped under
        their own heading, and counted in `Grid.hidden` when an explicit filter excludes
        them.
      - **Grouping by tier takes the section panels off the page, and the sentence each
        empty one was carrying with them.** The definition of done (item 3) is about a
        reader telling *not built yet* from *nothing matched*, not about the shape of the
        panel saying so, so a "Sections with nothing to show" block collects the same
        reasons in that mode. Dropping them because the layout changed would have been the
        rule quietly following the layout.
      - **Filters never touch the navigation counts.** The nav describes the run; the grid
        describes an arrangement of it. Had a filter reached the nav, hiding the low tiers
        would make a section report `0/0` — read as *this section found nothing*, the exact
        confusion the no-silent-empty rule exists to prevent, arriving through the one
        control that is supposed to be reversible. Asserted in the view model and again over
        HTTP, because the two are rendered from different objects.
      - A card is resolvable by URL even while the reader's own filter hides it; the card
        route looks in the run, not in the grid. Otherwise a link would work or not
        depending on a control setting elsewhere on the page.
      - Sorting offers tier, **section** and title. Section is a no-op inside a
        section-grouped page and is the useful one on a tier-grouped page — which is the
        arrangement §0.1A actually recommends — so the two controls are worth having
        independently.
- [x] **M4.8** Light/dark theming, responsive layout (`static/theme.js`, `static/app.css`).
      - **Three theme states, not two.** `system` is a real choice and the default, so a
        two-way toggle would make following the OS setting unreachable once somebody had
        picked either explicit theme. The cascade needs both guards and only one of them is
        obvious: `@media (prefers-color-scheme: dark)` is qualified with
        `:root:not([data-theme="light"])` so an explicit light choice wins on a machine set
        to dark, and `:root[data-theme="dark"]` restates the palette so an explicit dark
        choice wins on a machine set to light. Every token is defined on bare `:root` first,
        so no colour has its only definition inside a media query — the failure where an
        untested theme renders half-unstyled.
      - **`theme.js` is the one script not deferred**, and it is kept tiny for exactly that
        reason. It writes `data-theme` before the first paint; deferred, every load under an
        explicit theme would flash the system one. It also sets `data-js`, which is what
        reveals the toggle: a control that needs scripting and renders anyway is a control
        that silently does nothing, which reads as a broken page rather than an unavailable
        feature. Without scripting the system preference still applies.
      - **A confidence tier is never communicated by colour alone.** Each tier has a hue and
        every badge carries its own text, because the one attribute §0.1A makes
        non-negotiable must not be invisible to a reader with a colour vision deficiency.
      - The nav collapses to a header rather than disappearing on a narrow screen: it is the
        only thing on the page listing all thirteen sections whether or not this run filled
        them, so hiding it would make the no-silent-empty-sections rule true only on a
        desktop. Wide content (the confidence breakdown table) scrolls inside its own
        container, and the modal goes full-bleed below 40rem.
- [x] **M4.9** `genetics serve` command (`cli/serve_cmd.py`).
      - **The command binds the socket itself, and that closed a real hole rather than
        tidying one.** `WebConfig` validates the host it is *given*, and `is_local_address`
        accepts `localhost` by name because a Host header writes it that way. `localhost`
        resolves through the hosts file — [M4.3](#m4--run-bundle--first-ui) picked the
        numeric literal as the default for exactly that reason and then checked nothing on
        the other side of it. Every existing test asks the config object, and a config
        object cannot report what the kernel handed out, so a machine whose hosts file
        pointed `localhost` at its LAN address would have published an unauthenticated
        genome dashboard to the network with the whole suite green. The address is now
        checked twice against the *outcome* — once on what `getaddrinfo` resolved, before
        any socket exists, and once on `getsockname` after the bind, which is the only
        authoritative answer. `is_wildcard_address`'s own lesson ("check the outcome, not
        the input forms"), one layer down at the layer that opens the port.
      - **The host rule is imported, not restated.** `check_bind_host` came out of
        `WebConfig.__post_init__` so the CLI and the app cannot reach different conclusions
        about what loopback means — the six-templates-one-rule shape from
        [M4.6](#m4--run-bundle--first-ui), caught before it was written a second time.
      - **`--port 0` is a serve concept, not a config one**, and the split is deliberate:
        `WebConfig` describes an address a URL can name and `http://127.0.0.1:0` names
        nothing, so zero belongs to the code doing the asking. The config is then built
        *from the bound socket*, which means `allowed_hosts` describes what is actually
        listening rather than what was requested.
      - **The access log is off by default.** A request line names the URL, a card's URL is
        `/runs/<id>/cards/<card_id>`, and M4.6 already sends `Referrer-Policy: no-referrer`
        on the argument that a variant plus a person is the genotype ([§1.3](AGENTS.md)).
        Having established that a card URL must not reach a third party through a header,
        printing the same URLs to a console — the text people paste into bug reports — is
        that disclosure through the likelier route. `--access-log` turns it on per
        invocation.
      - No `--runs-root`, per [M4.0](#m4--run-bundle--first-ui) and M4.2: the store is
        addressed through `GENETICS_DATA_DIR`.
      - **The self-pass found one overclaim of my own**: an explicit `sys.stdout.flush()`
        with a comment explaining why the startup report needed it. `click.echo` always
        flushes and documents that it does, so the line changed nothing — a claim nothing
        behind it honoured, which is the exact pattern the M4.6–M4.8 review recorded. The
        line is gone and the requirement is held by a test that reads the report off a pipe
        while the server is still running.
- [x] **M4.10** **Offline guarantee, end-to-end half** — moved here from M2.7, which now
      holds the in-process guard. With networking disabled **at the OS level**, a full run
      succeeds once references are present.
      - It belongs here and not at M15 because the guarantee should be enforced from the
        moment it is testable, not audited once at the end. **What made it testable is
        [M4.0](#m4--run-bundle--first-ui)** — the "full run" this item waits on is
        `genetics run`, which is why nothing earlier could have carried this test.
      - The OS-level part is the point: M2.7 patches this process's `socket` module, which
        has no reach into PLINK 2, Beagle, Java or R. A subprocess phoning home is the
        failure only this test can see. `genetics/testing/isolation.py` runs the child in a
        **Linux network namespace** (`unshare --map-root-user --net`), which takes the
        network from the child and everything the child starts.
      - **The isolation is verified before anything is concluded from it, and verified
        without sending a packet.** An isolation that silently does nothing makes every test
        built on it pass, which is worse than having none — so `find_isolation` asks the
        child which interfaces it can see (`lo` and nothing else inside a fresh namespace)
        and refuses to hand back a mechanism that reported success while the child could
        still see `eth0`. Proving it by connecting somewhere would send real traffic on
        precisely the machine the check exists to detect. The refusal branch is driven
        directly, on every platform, because it is the failure that must not depend on
        having the right machine to notice it.
      - **The reachability demonstration asserts the failure *mode*, not just failure.**
        Against TEST-NET-1 (`192.0.2.1`, RFC 5737, routed nowhere) an isolated namespace
        gives an immediate `ENETUNREACH` and a machine with a network gives a timeout, so
        "the connection failed" would have passed either way — the one-answer check this
        project has had to fix twice ([M0.6](#m0--foundations--guardrails)).
      - **Windows skips, and the roadmap says so rather than implying coverage.** Every
        OS-level mechanism Windows offers — firewall rule, Hyper-V sandbox — needs
        elevation, and a check that runs only for administrators does not run. There the
        in-process guard is all there is, and it covers less. To stop "covered" and "skipped
        everywhere, forever" from looking identical, `GENETICS_REQUIRE_OS_ISOLATION` turns
        the skip into a failure and **CI sets it on the Linux job**.
      - **Two candidates, because the first CI run refused the first one.** GitHub's
        `ubuntu-latest` is Ubuntu 24.04, which restricts unprivileged user namespaces through
        AppArmor: `unshare --map-root-user --net` creates the namespace and is then denied
        the uid mapping (`write failed /proc/self/uid_map: Operation not permitted`). A
        detector that looked for `unshare` on `PATH` would have called that machine capable —
        the probe is the reason this surfaced as a named failure instead of a green tick. The
        fallback is `sudo -n -E unshare --net`, and both halves of that are deliberate: `-n`
        makes sudo fail instead of prompt, and it is **only attempted when the caller says
        isolation is required here**, so a developer with cached credentials never has part of
        the suite silently run as root while CI still gets the real thing.
      - **The probe asks two questions, not one**, and the second only became necessary when
        `sudo` joined the list: sudo resets the environment by default, so a mechanism could
        take the network away and quietly drop `GENETICS_DATA_DIR`, running the pipeline
        against the wrong store and passing. The child reports its interfaces *and* echoes a
        per-call token, in one process, so neither answer can come from a different one.
      - Re-verified at full pipeline scope by [M15.1](#m15--v1-release-gate).

> **Slice checkpoint — [x] passed 2026-08-21.** Ingest a synthetic fixture → traits cards →
> browse in the UI → save → reload. Run by hand end to end once M4.9 made it a single
> command: a spiked synthetic export produced **43 cards, 30 interpreted** (29 moderate, 1
> limited); the dashboard listed the run, the run page rendered every card with its tier
> badge, a card page carried the reader's genotype on the face and two resolving DOIs; the
> run survived an app restart and `genetics runs list` reported the same id the UI showed.
> **The architecture is proven and M5 may start.**
>
> One thing worth carrying forward: the *committed* fixtures produce 0 interpreted cards,
> because they carry no spike-ins and so land on none of the pack's markers. That is correct
> — M0.2 generates from allele frequencies, not from the knowledge pack — but it means "run
> the fixture and look at the UI" shows an empty grid, and the honest demo needs an export
> rendered with the pack's own variants. The same reason `tests/test_cli_run.py` builds one.

---

## M5 — Ancestry

- [ ] **M5.1** PLINK 2 wrapper (`external/plink2.py`): subprocess, argument building,
      error surfacing, version pinning.
- [ ] **M5.2** Convert normalized table → PLINK pgen; harmonize alleles against the
      reference panel; handle strand and allele-order mismatches explicitly.
- [ ] **M5.3** Build reference PCA from 1000G + HGDP (+SGDP) on array-overlapping markers;
      LD-prune first. Cache the eigenvectors as a fetched-reference artifact.
- [ ] **M5.4** Project the sample onto reference PCs via `--score`
      ([AGENTS.md §4.6](AGENTS.md) — PLINK 2, **not** ADMIXTURE).
- [ ] **M5.5** Continuous ancestry coordinates + nearest reference populations with
      distances. Prefer this over pie-chart percentages; if percentages are shown, show
      their uncertainty.
- [ ] **M5.6** AADR projection: affinity to ancient populations. Label clearly as
      *affinity*, not descent.
- [ ] **M5.7** Y haplogroup from 1,665 markers and mtDNA haplogroup from 263 markers via
      PhyloTree 17. **Report the supporting marker count and state the resolution
      ceiling on the card** ([AGENTS.md §4.7](AGENTS.md)). Note the open ISOGG Y-tree is
      frozen at v15.73 (2020); `yhaplo` is non-commercial-licensed — if used at all, keep
      it optional and label the licence.
- [ ] **M5.8** Ancestry output feeds the shared context object — **PRS confidence depends
      on it** ([AGENTS.md §4.4](AGENTS.md)). This ordering dependency is load-bearing.

---

## M6 — Genome structure

- [ ] **M6.1** ROH via PLINK `--homozyg`. LD-prune and MAF-filter first; **do not use the
      defaults** — tune window/length parameters for 677k density and document the
      choice. Report total ROH length, count, longest segment, and F_ROH.
- [ ] **M6.2** Autozygosity interpretation card. Sensitive and occasionally surprising —
      include it, compute it properly, state it plainly
      ([AGENTS.md §0.1B](AGENTS.md)). No euphemism, no advice.
- [ ] **M6.3** Archaic introgression (Neanderthal/Denisovan) against public Vindija/Altai
      references. Array-based estimates are coarser than sequence-based — say so, and
      give a range rather than a false-precision percentage.
- [ ] **M6.4** Sex chromosome findings + karyotype-adjacent caveats. Be careful and
      literal; this is an inference from het rates, not a karyotype.

---

## M7 — Monogenic health & frequency gating

- [ ] **M7.1** ClinVar lookup against the normalized table, position-keyed.
- [ ] **M7.2** **Frequency gate wired to gnomAD** — the single most important correctness
      requirement in the project ([AGENTS.md §4.1](AGENTS.md)). Rarity lowers confidence.
- [ ] **M7.3** `likely-artifact` rendering: the card **states the empirical PPV for its
      frequency band** (~16% below 0.001%; ~4% for BRCA1/2). "Low confidence" is too weak
      — give the number.
- [ ] **M7.4** ACMG secondary-finding genes: surfaced, tiered, and accompanied by an
      explicit "only clinical sequencing can establish or exclude this; this is not a
      clinical test". Not suppressed, not presented as established.
- [ ] **M7.5** Well-established common-variant health cards (APOE, HFE, F5 Leiden, etc.)
      with proper absolute-risk framing, not relative risk alone.
- [ ] **M7.6** Coverage honesty card: how many ClinVar positions the array covers
      (~76k), and what that does and does not mean.

---

## M8 — Imputation

*[AGENTS.md §0.1C](AGENTS.md): compute cost is not a constraint. Imputation is
default-on.*

- [ ] **M8.1** Beagle wrapper: Java detection, memory configuration, progress reporting,
      **resumability** (long runs must survive interruption).
- [ ] **M8.2** Reference panel prep → bref3, per chromosome. Full panel, not subset.
- [ ] **M8.3** Phasing then imputation pipeline; write dosages plus per-variant quality
      (r²/DR²).
- [ ] **M8.4** `--no-impute` escape hatch for dev/testing. Never the default, never
      silent — the run bundle and every affected card record which mode was used.
- [ ] **M8.5** Carry imputation quality through to scoring so poorly imputed variants
      degrade confidence rather than silently entering sums.
- [ ] **M8.6** Record panel version, tool version and parameters in the run bundle.
- [ ] **M8.7** Assert the rare-variant frequency gate still applies to imputed calls —
      imputation does **not** rescue rare-variant reliability.

---

## M9 — PRS engine & score-driven sections

- [ ] **M9.1** PGS Catalog scoring-file parser, incl. **per-score licence header**.
      Refuse or flag non-permissive scores.
- [ ] **M9.2** Scoring via PLINK 2 `--score`, pre- and post-imputation.
- [ ] **M9.3** **Per-score variant coverage reported on every card**, before and after
      imputation ([AGENTS.md §4.3](AGENTS.md)).
- [ ] **M9.4** Reference distribution + percentile placement, computed within the
      ancestry-matched reference group where possible.
- [ ] **M9.5** Ancestry-portability adjustment to confidence
      ([AGENTS.md §4.4](AGENTS.md)).
- [ ] **M9.6** PRS card renderer: distribution-dominant visual, **no point estimates about
      the person**, absolute outcome rates by decile where available, within-family
      attenuation stated on the card face where known.
- [ ] **M9.7** Section: **Physical health** PRS cards.
- [ ] **M9.8** Section: **Mental health**. Record reduced-N (excluding-23andMe) releases
      on the card ([AGENTS.md §5.3](AGENTS.md)).
- [ ] **M9.9** Section: **Psychometrics**. Most constrained on both corpus and science —
      both constraints stated on the cards ([AGENTS.md §4.5](AGENTS.md)). Ships in full,
      unflattering results included.
- [ ] **M9.10** Section: **Substance use & behavioural propensity**. GSCAN public
      excluding-23andMe stats are well powered (smoking initiation N=805,431;
      drinks/week N=666,978).
- [ ] **M9.11** Section: **Sleep & circadian**.
- [ ] **M9.12** Section: **Fitness & physiology** (ACTN3, ACE, injury, trainability).
      Weak evidence — include and flag honestly.

---

## M10 — Pharmacogenomics

*Highest actionable value; corpus entirely free. See [AGENTS.md §3.1](AGENTS.md).*

- [ ] **M10.1** PharmGKB + CPIC ingestion → star-allele definitions and phenotype mapping.
- [ ] **M10.2** Diplotype calling for **SNP-tractable genes only**: CYP2C19, CYP2C9,
      VKORC1, SLCO1B1, TPMT, DPYD, NUDT15, G6PD.
- [ ] **M10.3** **CYP2D6 explicit "not callable" card.** PharmCAT declines to call it from
      a VCF because structural/CNV variation dominates, and a `*5` whole-gene deletion
      makes the other allele read as homozygous (`*5/*29` → `*29/*29`). Render the
      limitation; do not omit the gene silently.
      - **The card itself shipped in [M3.7](#m3--card-engine--knowledge-pack)**
        (`cyp2d6_structural_variation`), because §3.2's copy-number entry names CYP2D6
        hybrids and the register has to be complete. What is left here is placement: it must
        render beside the diplotypes M10.2 calls, so the gap is visible where a reader is
        looking at the genes that *were* called. Do not author a second card.
- [ ] **M10.4** CPIC guideline-linked cards: phenotype → dosing implication, with the
      guideline cited and its evidence level shown.
- [ ] **M10.5** Prominent framing that this is not a prescribing tool, stated once and
      precisely — not repeated as filler on every card.

---

## M11 — HLA, immunogenetics & carrier status

- [ ] **M11.1** R + HIBAG detection and subprocess bridge. Optional module that degrades
      gracefully with a clear "R not installed" state.
- [ ] **M11.2** HLA imputation using **HIBAG pre-fit classifiers** (European/Asian/
      Hispanic/African). **Do not use SNP2HLA** — its T1DGC panel was withdrawn over
      individual-level genotype concerns and now needs a NIDDK request.
- [ ] **M11.3** Ancestry-matched classifier selection, driven by M5 output. Report
      posterior probability per call and fold it into confidence.
- [ ] **M11.4** HLA-linked cards: celiac (DQ2/DQ8), type 1 diabetes, ankylosing
      spondylitis, narcolepsy (DQB1\*06:02), drug hypersensitivity (B\*57:01/abacavir,
      B\*15:02/carbamazepine).
- [ ] **M11.5** Carrier status cards for array-tractable recessive conditions.
- [ ] **M11.6** **Carrier-screening incompleteness card**: CNV-based conditions (SMN1/SMA,
      alpha-thalassemia) are invisible to this data. State it, or the section implies a
      completeness it does not have.
      - **The two per-gene cards shipped in [M3.7](#m3--card-engine--knowledge-pack)**
        (`smn1_copy_number`, `alpha_globin_deletions`), each carrying the "no result is not
        a negative result" caveat this box exists for. What is left is the *section-level*
        statement — carrier screening from an array is incomplete as a category, not only
        for the two conditions §3.2 happens to name — which is a different claim and needs
        M11.5's callable set to exist before it can say what it excludes.
- [ ] **M11.7** Reproductive section beyond carrier status: age at menarche/menopause and
      related traits.

---

## M12 — Nutrition & metabolism

- [ ] **M12.1** Cards: MCM6 lactase persistence, CYP1A2 caffeine, ADH1B/ALDH2 alcohol,
      HFE hemochromatosis, celiac HLA-DQ (reuse M11), FUT2 secretor status, vitamin D
      (GC), B12, folate.
- [ ] **M12.2** **MTHFR card as a deliberate calibration test case.** Heavily overhyped in
      wellness marketing. Include it, state the actual evidence, and let the confidence
      calculator land where it lands. This card is the reference example for how the
      project handles popular claims with thin support.

---

## M13 — Agent interface

*The CLI is the contract. Every analysis must be reachable as JSON
([AGENTS.md §3](AGENTS.md)).*

- [~] **M13.1** `genetics list-runs`, `show <run> [--section S]`,
      `card <run> <card-id> --json`, `evidence <card-id>`, `qc <run>`, `refs licenses`.
      - **Partly delivered early, and recorded here so it is not built twice.**
        [M4.2](#m4--run-bundle--first-ui) shipped `genetics runs list` (this item's
        `list-runs`, under the `runs` group), `refs licenses` landed in M2.6, and `runs show
        --json` already emits the whole bundle including per-card citations and the
        confidence breakdown — which is [M13.4](#m13--agent-interface) in substance, since
        M4.1 stores the numeric inputs beside the tier.
      - **What remains:** `--section` filtering, `card <run> <card-id>`, `evidence
        <card-id>`, `qc <run>` as its own command, and deciding whether those live under
        `runs` or at the top level. `runs show` was kept deliberately thin — a bundle header
        and one line per card — precisely so this item still owns the analysis surface.
- [ ] **M13.2** Stable JSON schema, versioned, documented. Card JSON **must include
      citations** so an agent can verify rather than confabulate.
- [ ] **M13.3** `genetics search <query>` across cards, so an agent can find "curly hair"
      without knowing the card id.
- [ ] **M13.4** Machine-readable confidence: tier plus the numeric inputs that produced
      it, so an agent can explain *why* a card is low confidence.
- [ ] **M13.5** Parity test: every UI-reachable analysis is CLI-reachable. Wire into CI —
      this is the requirement most likely to silently rot.
- [ ] **M13.6** Document the review workflow in `AGENTS.md` or a `docs/agent-usage.md`,
      with the worked example from the project brief (*"it says I'm predisposed to curly
      hair — review the cited information and give me 10 interesting facts"*).
- [ ] **M13.7** Reinforce [AGENTS.md §1.3](AGENTS.md): agents research the **variant**,
      never the user's genotype at it. Add a lint/test for genotype strings in outbound
      query construction.

---

## M14 — UI completion

- [ ] **M14.1** All thirteen sections wired, each with an explicit empty state explaining
      *why* it is empty when it is.
- [ ] **M14.2** Ancestry visualisations: PCA scatter with reference populations, ancient
      affinity, haplogroup display with marker counts.
- [ ] **M14.3** Confidence legend and a "how to read these results" page covering the
      rarity-inversion, PRS attenuation, and array limitations.
- [ ] **M14.4** Global search across cards.
- [ ] **M14.5** QC / provenance page: reference versions, tool versions, imputation
      parameters, coverage stats.
- [ ] **M14.6** Impossibility cards surfaced in their relevant sections, not hidden in an
      appendix.
- [ ] **M14.7** Accessibility pass: keyboard navigation, contrast, screen-reader labels.

---

## M15 — v1 release gate

- [ ] **M15.1** Full run on the real file, offline, start to finish. Record wall-clock and
      peak memory in the progress log. Re-runs [M4.10](#m4--run-bundle--first-ui)'s
      OS-level network block at full pipeline scope — imputation, PRS and HLA all shell
      out, and they are the parts M2.7's in-process guard cannot see.
- [ ] **M15.2** Full run on a structurally different synthetic fixture (different sex,
      different vendor layout) with **no code changes** — proves plug-and-play.
- [ ] **M15.3** Privacy audit: `git log --all` reviewed for any genotype-derived blob ever
      committed; `.gitignore` re-verified against every path the app writes.
- [ ] **M15.4** Licence audit: `manifest.lock` reviewed; confirm nothing non-permissive is
      vendored and that per-score PGS licences were honoured.
- [ ] **M15.5** **Calibration review** — the most important gate. Sample cards across all
      confidence tiers and check the stated confidence matches the actual evidence.
      Specifically verify a rare pathogenic call renders as `likely-artifact` with its
      PPV, and that no code path filters cards by confidence.
- [ ] **M15.6** Citation audit: every shipped card resolves to a real DOI/PMID/accession.
      Zero fabricated references.
- [ ] **M15.7** README with setup, fetch, run, and the privacy warning.
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
| PGS per-score licences ignored | M9.1 | Parse header per score, not per catalogue | [§4.8](AGENTS.md) |
| Imputation run un-resumable, blocking progress | M8.1 | Resumability is an acceptance criterion | [§0.1C](AGENTS.md) |
| CLI/UI parity rots | M13.5 | Parity test in CI | [§3](AGENTS.md) |
| Reduced-N sumstats silently weaken psychometrics | M9.8–9.9 | Record release version on the card | [§5.3](AGENTS.md) |
| Carrier section implies false completeness | M11.6 | Explicit incompleteness card | [§3.2](AGENTS.md) |
| PLINK 2 alpha build changes behaviour | M2.5 | Pin exact build in manifest | [§4.9](AGENTS.md) |
| A `.gitignore` negation silently re-admits genotype output | M4.1 | A later un-ignore rule wins over an earlier ignore rule, and `!/knowledge/**/*.json` did exactly that to the run-bundle payload. The mitigation is not another rule but **how it is checked**: tests ask `git check-ignore` rather than searching `.gitignore` for text, since a string search cannot see precedence, negation or ordering — the only things that decide the answer. A companion test asserts the card corpus stays trackable, so a re-ignore rule cannot be widened until it breaks what must be committed | [§1.1](AGENTS.md) |
| A bundle-format bump orphans every run a user has already saved | M4.1, M4.2 | Bundles are immutable, so no in-place migration is possible even in principle. Guaranteed by contract instead: **payload keys may be added, never removed or repurposed**, so a reader accepts any bundle at or below its own version and an old bundle still carries everything a newer reader requires. A test moves the engine version forward and reads a current bundle through it | — |
| A network call creeps into analysis code and is only found at the release gate | M2.7, M4.10 | Autouse guard fails the suite in the commit that adds one, naming the test; the OS-level run at M4.10 covers the subprocesses the in-process guard cannot see | [§6](AGENTS.md) |

---

## Progress log

Append dated entries as milestones complete. Record surprises, parameter choices that
needed tuning, and anything that contradicts AGENTS.md (then fix AGENTS.md).

| Date | Milestone | Notes |
|---|---|---|
| 2026-08-21 | M4.9–M4.10 review | Diff-driven self-pass over the session's changes. **Six findings, all fixed, each reproduced by execution before the fix and each new guard verified by neutering it** -- the sixth by the pre-commit hook rather than by me. **1241 tests + 5 skips**; ruff, `ruff format` and `mypy --strict` clean. **The pattern was mine and it was the last review's pattern again: a comment claiming behaviour nothing behind it honoured** -- three of the five are that shape, written by me in the same session that recorded the lesson. **(1) A comment justified `log_level="warning"` by saying uvicorn would otherwise print a banner naming the *requested* host and port, announcing port 0 next to the real one.** It would not: `Server.startup` skips `_log_started_message` entirely whenever it is handed sockets, at every level. Confirmed by running the command at `info` and by reading the branch. The real reason is plainer -- three lines of framework chatter -- and the comment now says so. **(2) The address was announced before the app existed.** `_report` ran ahead of `create_app`, which mounts the static directory and raises on an installation missing its package data, so the failure printed "here is your dashboard, at this URL" and then a traceback for a server that never was. Reordered; the guard fails when the old order is put back. **(3) `genetics serve --json` printed prose on failure** while `genetics run --json` next door emitted `{"ok": false, "error": {...}}` for the same class of refusal -- an agent driving both had to special-case one, which is what [§3](AGENTS.md)'s "keep every command JSON-capable" exists to prevent. Now mirrors `run_cmd`, with `config` and `serve` as the two kinds. **(4) A test that asserts nothing on the platform that matters:** `if isinstance(found, Unavailable): assert ...` is a no-op on Linux, the one platform where the isolation works and so the only place a regression in the *other* branches would go unnoticed. Parametrized over Windows/Darwin/FreeBSD instead, so all three reasons are checked everywhere. **(5) The Ctrl+C comment overclaimed a "clean exit".** Measured instead of assumed: CTRL_BREAK to the running command on Windows stops it with no traceback and nothing on stderr, and an exit status of `0xC000013A` -- Windows' STATUS_CONTROL_C_EXIT, not a value this command chooses. A true CTRL_C_EVENT cannot be delivered to a child from a harness, so the comment now says which half is verified and which is not. **(6) `genetics check-staged` refused the first commit**, and it was right: `tests/test_cli_serve.py` spelled a tab-separated genotype row out in full to prove the startup report is scanned, which is a genotype row in a public repo whatever the surrounding test says it is for. Assembled at runtime with `"	".join(...)` instead, which is what `test_cli_run.py` already does for the same reason -- worth recording because the guard caught a file written by the person who had just finished reading the guard's own rules. **Also verified and clean:** the `check_bind_host` extraction is behaviour-preserving (the whole web suite passes unchanged); the socket is listening before the URL is printed, so a caller that connects the instant it reads the report lands in the accept backlog rather than being refused -- which the end-to-end test depends on and therefore demonstrates. |
| 2026-08-21 | M4.9 + M4.10 | `genetics serve` and the OS-level offline guarantee. **1242 tests + 5 skips** (36 more); ruff, `ruff format` and `mypy --strict` clean; the M4 slice checkpoint run by hand and passed. **M4.9 turned out to be closing a hole rather than wrapping uvicorn.** `WebConfig` validates the host it is *given* and `is_local_address` accepts `localhost` by name -- it has to, a Host header writes it that way -- while `localhost` resolves through the hosts file, which a machine can be made to lie about. M4.3's `DEFAULT_HOST` docstring says exactly that and picks the numeric literal for exactly that reason, and then nothing checked the other side of it: every existing test asks the config object, which cannot know what the kernel handed out. A machine whose hosts file pointed `localhost` at its LAN address would have served an unauthenticated genome dashboard to the network with the suite green. The command now binds the socket itself and checks the *outcome* twice -- what `getaddrinfo` resolved, before any socket exists, and what `getsockname` reports after -- which is `is_wildcard_address`'s own lesson one layer down. `check_bind_host` was lifted out of `WebConfig.__post_init__` so the CLI and the app cannot disagree about what loopback means. **Three new guards verified by neutering them**, and the ordering one caught its own point: moving the resolved-address check below `socket()` fails the test that asserts nothing is bound while the address is being judged. **The self-pass caught one overclaim of mine**: an explicit `sys.stdout.flush()` documented as what lets a supervising process read the startup report off a pipe. `click.echo` always flushes and says so in its own docstring, so the line did nothing -- a claim nothing behind it honoured, the M4.6-M4.8 pattern again, mine this time. Removed; the requirement is held by a test that reads the report from a live process instead. **M4.10 is Linux-only and the roadmap now says so rather than implying coverage.** `unshare --map-root-user --net` takes the network from a child and everything it starts, which is the half M2.7's in-process patch can never reach; Windows has no unprivileged equivalent, so it skips with the reason printed. The isolation is **verified before anything is concluded from it and without sending a packet** -- the child is asked which interfaces it can see, not asked to reach something, because proving it by connecting would send real traffic on exactly the machine where the isolation silently did nothing. `GENETICS_REQUIRE_OS_ISOLATION` turns the skip into a failure and CI sets it on the Linux job, so "covered" and "skipped everywhere, forever" stop looking identical. **One defect found by running the test body rather than reading it**: the bundle-path assertion compared a resolved path against an unresolved temp dir, which passes nowhere -- Windows hands back an 8.3 short name and macOS a symlinked /tmp. **Not verified locally:** the Linux branch itself, since this machine has no WSL distro and no Docker; it runs first on CI. |
| 2026-08-21 | M4.6–M4.8 review | Diff-driven self-pass over the session's changes. **Six findings, all fixed, each reproduced by execution before the fix and each new guard verified by neutering it.** **1206 tests + 1 platform skip** (8 more); ruff, `ruff format` and `mypy --strict` clean. **The pattern this time was a claim the markup or a docstring made that nothing behind it honoured** — three of the six are that shape, which is the M2 review's pattern arriving in a template layer rather than in Python. **(1) The one that mattered: run ids and card ids were concatenated into URLs.** A run id is a *directory name on disk* and `list_runs` reports whatever it finds, not only the names `check_run_id` would have written — so `/runs/evil%3Fgroup=tier` rendered every nav link on the page as `/runs/evil?group=tier#section-ancestry`, a query string injected into links the reader never set, and a `#` in a card id truncated the card URL and made the card unopenable. Autoescaping held, so it is not an escape; it is a URL built from unvalidated page content, which is exactly the habit `runselector` in app.js already had a comment written against ("the id here came out of a `<select>` in a document, not out of the store"). Fixed by moving URL construction into the view model as `run_path`/`card_path` and giving `Shell` and `CardView` their own addresses, so no template concatenates one — six templates were doing it, and a rule enforced in six places is the shape of problem this project keeps recording. **(2) `aria-modal="true"` was a false claim.** It tells a screen reader that everything outside the dialog is unavailable, and nothing made that true: a keyboard user could tab straight out into the grid behind it. Same defect class as the impossibility card's fabricated explanations, one layer up. The background is now `inert` while a card is open. **(3) A dead function with a docstring naming a caller that does not exist** — `resolvable_databases()`, "public for the tests that check…", and no test ever called it. Deleted. **(4) My own new guard was fail-open, and it is worth recording because it is the third time this project has hit it.** The test backing (2) asserted `"inert" in app_js`, which passes with the mechanism replaced by `data-x` because the word survives in the comment explaining it — a guard whose first casualty is its own documentation, the same trap M4.4 avoided for Python and I walked into for JavaScript. It now matches the `setAttribute('inert'` / `removeAttribute('inert'` calls. **(5) Two entries in the card field-coverage test were vacuous**, and they were vacuous for exactly the two fields whose rendering is *conditional*: `kind` and `bundle_format_version` only choose which sentence appears, so any fixed marker for them was satisfied by text present regardless. They are now excluded by name, each asserted by its own test, and the coverage check still counts them so a third such field cannot be dropped in silently. **(6) Two keys for one registry** — `"pgs catalog"` and `"pgscatalog"` both mapped to the PGS Catalog, and `PGS-Catalog` mapped to nothing and would have rendered as text with nothing to say why. The database name is now reduced to letters and digits before lookup. **Also verified and clean:** a card whose every optional block is the wrong shape (a string where a mapping belongs, `NaN`, `Infinity`, a negative frequency, a mapping where a title belongs) renders without raising, without printing a Python repr, without an unescaped tag and without `nan` on the page — the `.get`/`_number`/`_text` discipline holds; and a 22-URL sweep of every route and parameter combination against a real uvicorn process produced no 5xx, with path traversal 404ing. |
| 2026-08-21 | M4.6–M4.8 | Card grid, detail modal, sort/filter/group, theming. **1198 tests + 1 platform skip** (84 new, 177 privacy-marked); ruff, `ruff format` and `mypy --strict` clean. **Bundle format version 2** — the first bump, and a UI milestone caused it, which is the entry's main content. M4.6 asks the detail view for effect size, base rate and source population; version 1 stored none of them. It stored `confidence.inputs.effect_measure` and `effect_value` — the *scoring* inputs — and dropped units, the interval, the sample size, the study population and the `context` sentence saying what the number is a proportion *of*, because none of those move a score. `proportion 0.992` rendered as "the effect size" is the vaguer sensitive card [§0.1B](AGENTS.md) calls a defect, and the alternative — reading the rest back out of `knowledge/` at display time — is the re-rendering M4.1 built the format to refuse. The bump cost almost nothing because the additive contract had already been settled, and `test_bundle.py`'s pinned nested shape is what forced it: the first run after adding the key failed with *bump BUNDLE_FORMAT_VERSION in the same commit*, which is the job that test exists to do. **The base rate is still missing and is named rather than approximated.** No card records how common an *outcome* is — that gap is in the card schema, not the bundle — so a ratio is labelled relative and the page says what would make it absolute (M7, M9); the population **allele** frequency sits under its own heading and is never called a base rate, because how common an allele is and how common an outcome is are different quantities and letting one stand for the other is the euphemism §0.1B forbids. A `base_rate` key that all 43 cards left empty would have been a second name for something nobody wrote. **The hardest call was the citation links, because M4.6 and M4.4 read as contradicting each other.** "Clickable citations" against "no external URL in any template or rendered response". They do not actually conflict: what M4.4 protects is that *the browser makes no request to a third party while a genome is on screen*, and an anchor makes none until a person clicks it — on a published identifier, with no referrer, carrying nothing about them. What M4.4 refuses is a subresource fetched unasked. So the rule was refined rather than waived: an external host may appear **only** inside an anchor with `class="citelink"`, `target="_blank"` and `rel="noreferrer noopener"`, everywhere else still fails, and `/` stays on the unrefined list so a resolver URL on the card grid fails rather than passing by association. Structural rather than a host allowlist, because a `url` citation may legitimately point anywhere a card author cited. Driven with five forms it must still catch, all mutation-verified. Two consequences worth recording: `Referrer-Policy: no-referrer` stopped being belt-and-braces the moment this landed — without it the publisher learns the reader came from `/runs/<id>/cards/<card_id>`, a card id naming the variant — and the URLs are built in Python from a **re-validated** identifier, because a `url` citation's stored id *is* the href and a bundle is read back without re-parsing, so an unvalidated one is a clickable `javascript:`. **The Alpine CSP-build trap became a test and immediately caught me.** M4.4 recorded that `x-on:click="open = !open"` is silently inert under that build — no error, no violation, just a dead control. Three static checks now cover it (no non-bare directive value, no `x-data` naming an unregistered component, no method reference app.js does not define), all mutation-verified, and the first thing they found was mine: `cardmodal.close()` used `this.$el`, which is the element the *directive* is on — the close button inside the swapped fragment — so it would have emptied the button and left the modal standing. **The self-pass found four defects, and the two worth recording are both sentences that were false rather than merely empty.** (1) An impossibility card rendered an *Effect size* heading over "this card records no effect size", and an *Allele frequency* heading over "no population frequency was available, so the rarity check could not be applied and the confidence tier is capped" — on a card that has no variant and no confidence tier. The second sentence was equally wrong on every marker-absent card. A false explanation is worse than the blank it replaced, because a reader cannot tell it from the case where it is true, and this project's whole editorial stance is that a reader can trust what the page says about what it does not know. Those blocks are now suppressed where they have nothing true to say, and the rarity sentence is produced only for a card that actually matched and scored. (2) The same card rendered *How this was called* over *Call source: direct* — because `call_source` is recorded for every observation including the ones that produced nothing, and its value there is `direct`, so the page asserted a direct call at a position the array does not carry. The test is now an observed rsID or an imputation quality: something actually answered, or something was actually attempted. Also added while fixing these: a card that did not match still shows the published claim, because a reader is owed what they are being told nothing about, but it now says so above the figures — a number under a heading on a genome dashboard reads as personal unless something says otherwise. **The self-pass also found the M4.7 controls lying.** Tier checkboxes were built from the tiers present in the run, so a newer engine's tier got a box the parser rejects: ticking it produced "ignored tier=…" and no filtering. One function now defines the filterable set for both. **Two decisions I expected to be harder than they were, and one that was harder.** Easy: one URL per card with two representations (`HX-Request` picks), since two addresses would have been two names for one card and would have let the no-JavaScript path rot silently; and filtering server-side in the query string, since M4.7's rule is a rule about what the page shows and can only be asserted where it is computed. Harder: grouping by tier removes the section panels, and with them the sentence each empty section was carrying — the definition of done is about the reader telling *not built yet* from *nothing matched*, not about the panel shape, so those reasons are collected into their own block in that mode rather than allowed to follow the layout out of existence. **M4.5's whole-page no-genotype test was narrowed, not deleted**: card faces state the reader's call by design, so the assertion moved to the two scanned regions and a second test now asserts the face **does** state it — without which the first would be satisfied by a page showing nothing. **Verified beyond the suite** against a real uvicorn process: index, tier-grouped, filtered and bogus-parameter pages plus both card representations all 200, five static assets served, `Vary: HX-Request` and the security headers present, `runs show --json` carrying the new `evidence` block, `cards lint` still 43 cards / 210 renders. **Not** verified in a browser — nothing here executes Alpine or htmx, so the modal, the theme toggle and the auto-submit rest on documented contracts plus the three new static checks; every one of them has a server-side path that works without scripting, which is why that gap is tolerable and M4.9 (`genetics serve`) is still the natural place to look at it properly. |
| 2026-08-21 | Agent review of M4.0/M4.5 | `/code-review high` over the same diff, after the self-pass had already fixed six. **Five more findings, all verified and all fixed**; **1114 tests + 1 platform skip** (10 new). The one that matters is a lesson about test construction rather than about this code. `banner_for` read `duplicates.duplicate_rows`; `DuplicateSummary` has `duplicate_rsids` and `duplicate_positions` and never had a `duplicate_rows`. So the banner rendered `-` for it on every run ever written — and a dash reads as *not measured*, which is the specific wrong impression this project keeps trying not to give. **It survived both my self-pass and the field-coverage test I had just added for exactly this class of bug**, because that test writes its own QC payload: a test that invents the input agrees with the reader about a shape neither of them shares with the producer, and the agreement is the bug. The banner tests take `QCReport.to_dict()` now and one of them demands every field resolve to something. On the real export the cell says 656, matching the QC warning that was already on the page beside it. **The other four:** `total_markers` was unguarded while its sibling `call_rate` went through `_number`, and `markers_display` formats with `:,` — which raises `ValueError` on a string, so a `qc.run.json` from another engine 500'd the whole dashboard instead of showing a dash, in the module whose docstring says rendering such a file is its job; `selected_id` came from the manifest's `run_id` while every other operation addresses a run by directory name, so a renamed bundle rendered with no option marked current and printed a `genetics runs show <id>` that cannot resolve; `Shell.total_cards` summed the thirteen known sections while the selector showed the manifest's count, so a newer engine's fourteenth section made two numbers on one page disagree in silence; and `_number` promised "a finite number" while accepting `NaN`, which `json.loads` parses by default, rendering `nan%`. Worth recording that the agent found all five *after* a self-pass that found six, and that its sharpest finding was aimed at the test I wrote during that self-pass. |
| 2026-08-21 | M4.5 | Dashboard shell. **1100 tests + 1 platform skip** (41 new); ruff, `ruff format` and `mypy --strict` clean. Jinja2 added. **The design question that took the time was where the genotype scan stops.** `runs list` is scanned and `runs show` is not (M4.2), and this page is about to become both: the banner and selector are manifest-derived, and M4.6's card faces state the reader's genotype by design. A whole-page scan would have been correct today and would have started failing on correct output the day cards land — M0.3's guard-that-gets-switched-off, walked into deliberately. So the two safe regions are rendered as their own templates, scanned, and passed into the page as already-safe markup. `{% raw %}{% include %}{% endraw %}` was the obvious spelling and I rejected it for a specific reason: one render pass produces one string and there is no way to scan half of it, so the scanned region would have been a comment rather than a fact. Both scans mutation-tested by deleting the call and confirming the parametrised test fails. **A view model went in between the bundle and the templates**, which was not in the plan and earns its place: `read_bundle` deliberately returns strings and mappings so an old run fails with a version error or not at all, and a template indexing `bundle.qc["call_rates"]` puts that fragility back as a Jinja error mid-page. It also makes every rule testable without HTTP — "no silent empty sections" is now one assertion over `section_views` rather than a grep for a heading somebody will reword. **The rule that needed the most thought was what an empty section says.** There are two empty states and they are not the same fact: *not built yet, roadmap M9.8* is about this tool, *N cards here, none produced an interpretation* is about this genome. Collapsing them would tell a reader their array lacks a marker when the truth is nobody has written the card, which is precisely the misreading AGENTS.md 0.1A is written against. **Two things the tests caught that I had wrong:** the `RunOption` model carried `vendor` and the selector template never rendered it — found because the privacy mutation test poisoned `vendor` and nothing leaked, which is a passing test proving the guard untested rather than the code safe; and I asserted a raw `Fitness & physiology` in the markup, which autoescape correctly renders as `&amp;` — asserting the raw form would have quietly required turning autoescape off on a page rendering authored text. Also handled: a `warnings` field that is a bare string is a `Sequence`, so the obvious isinstance check turns "oops" into four warnings reading o, o, p, s. **Verified beyond the suite** against a real uvicorn process and the owner's real 677k export: page plus all four assets 200 with the security headers, 13 sections in the nav, both QC warnings rendered, 99.92% call rate. **Not** verified in a browser — nothing here executes Alpine, so the selector's navigate-on-change rests on the CSP build's documented contract rather than on watching it work; the `<noscript>` list of plain links is why that gap is tolerable rather than blocking. **Self-pass afterwards found four more**, all fixed: `QCBanner` collected `het_haploid_calls` and `duplicate_rows` and the template rendered neither — the same dead-field slip as `vendor`, which means finding it by mutation test the first time was luck, so there are now two tests asserting every field of both view models reaches the page, checked by *rendering* rather than by grepping the template (two fields arrive through formatting properties, and a name check calls those missing while they are on screen); `Shell` carried a `_repr_fields` that does nothing because it does not inherit `NoGenotypeRepr`, which is worse than absent since it reads as a genotype-safe repr; `name.lstrip('_')` strips a character set rather than a prefix, the exact habit `check_run_id` and `is_wildcard_address` were corrected for; and `analyse` loaded the knowledge pack *after* ingest, so a typo in a card file was reported after a full parse of 677,000 rows — the slowest way to learn about the cheapest mistake, and card authoring is when it gets made. |
| 2026-08-20 | M4.0 | `genetics run` — the pipeline command that was missing. **1059 tests + 1 platform skip** (28 new); ruff, `ruff format` and `mypy --strict` clean. Found while planning M4.5: the definition of done names `genetics run`, no milestone item owned it, and `write_bundle` had no caller outside the test suite — so the dashboard would have been built against bundles a conftest wrote by hand, which is the failure M4.2 named when it refused a `--runs-root` flag. **The wiring was genuinely five calls; two things were not.** **(1) The observation layer is a decision, not glue.** I expected `assemble_pack` to take matches and go. It refuses an interpretation card without `ObservationEvidence`, on the grounds that assuming a direct call would score an imputed observation as perfect — so the pipeline has to *state* that this milestone does no imputation and has no ancestry fit. That constant now lives in `pipeline.observations()` with a test that names M5 and M8 as the milestones that will replace it, rather than becoming a default inside `assemble_card` where it would be invisible. The visible price: an unknown frequency and an unknown ancestry fit each score a neutral 0.5, so against the owner's real export 26 matched cards land at `moderate` and one at `limited`, and nothing reaches `strong`. That is the correct reading of what is known today; the tempting fix is AGENTS.md §4.1's rarity inversion going quiet. **(2) No committed fixture can produce a matched card.** `spike_ins` is empty across the whole synthetic corpus by design — inventing GRCh37 coordinates was rejected back in M0 — so every interpretation card returns `marker_absent`, which is exactly what a broken matcher also returns. My first test plan would have asserted "the pipeline runs" against a result that could not distinguish the two. The suites render their own spiked export from the same generator instead, and M4.5 now carries a warning not to develop the dashboard against the committed fixtures. **One assumption I got wrong and checked:** I wrote a test asserting an empty frequency list produces the "no population frequency" caveat. It does not — that caveat is for a *partially* priced locus; a locus with no frequencies at all returns no missing alleles and scores the neutral 0.5. The test now pins the breakdown recording `None` for both inputs, which is the honest claim: a saved run must read as "these were not known", not "these were known and average". **Verified beyond the suite:** the real 677,436-marker export runs end to end in 2.8 s — 26 matched, 12 not-determinable, 3 strand-ambiguous, 2 marker-absent — and both privacy guards were mutation-tested by deleting each `assert_no_genotype` call in turn and confirming the parametrised test fails. Numbered M4.0 rather than inserted as a new M4.5: `M4.5` is referenced from eight places outside this file, one of them a live test assertion, and renumbering would have edited working code to relabel work that had not changed. |
| 2026-08-17 | M4.4 | Vendored front-end. **1031 tests + 1 platform skip** (20 new); ruff, `ruff format` and `mypy --strict` clean. htmx 2.0.10 (0BSD) and Alpine 3.16.1 (MIT), 114 KB, pinned by sha256 in `web/vendor.yaml` and served from `/static/vendor/`. **Two decisions took the thinking; the downloading took ten minutes.** **(1) Which Alpine.** The standard bundle needs `script-src 'unsafe-eval'` — I checked rather than assumed, by counting `new Function` in each build: standard has one, `@alpinejs/csp` has none and no `eval` either. Adding `unsafe-eval` would have been a one-word change to the policy and is exactly the move M4.3's own docstring warns about, a strict CSP relaxed under pressure from a single asset on a page whose subject is somebody's genome. So the CSP build ships, and the price is paid in syntax by the milestones that come next: `Alpine.data('name', …)` and named references, no inline `x-on:click="open = !open"`. That is a real constraint on M4.5–M4.7 and it is recorded in `vendor.yaml` where the next author meets it, not here where they will not look. htmx keeps one eval path behind `htmx.config.allowEval`, set false through a **meta tag** — because `script-src 'self'` blocks inline scripts, so configuring htmx the documented way would have been the first thing on the page to break the policy the page advertises. **(2) What "no external URL" should actually mean.** The roadmap's sentence is literal and the literal reading is wrong: Alpine's bundle contains `https://alpinejs.dev/plugins/…` inside the text of an error it throws when a plugin is missing. That is a documentation pointer, not a request. A test failing on it would be wrong about correct code on the day it was written, which is M0.3's crying-wolf lesson arriving at a new boundary. So the scan splits by *what the file does*, not by who wrote it: everything that reaches a browser — the rendered HTML of every route, templates, first-party static files — is held to the literal rule, and everything else under `web/` is scanned for shapes that cause a load (`src=`, `href=`, `url(`, `@import`, `fetch(`, `new Worker(`). Two things fall out of that split and both are worth recording. Holding *Python* to the literal rule would mean the docstring explaining the rule could not name `cdn.example.com` while explaining why naming it is forbidden — a guard whose first casualty is its own documentation. And the rendered-output scan turns out to be strictly better than reading source, because it sees what was emitted rather than what was written, which is what matters once M4.5 starts interpolating. The scanner is itself driven with seven references it must catch and four it must not, including the protocol-relative `//host` form that reads as a comment and gets fetched anyway. **The licence work was not paperwork.** Alpine is MIT, which requires the notice to travel with copies, and `@alpinejs/csp` ships dist, src, builds and package.json with **no LICENSE at all** — so it came from the matching `v3.16.1` tag on GitHub rather than `main`, which would have pinned a notice describing different code. htmx is 0BSD and needs no notice; its licence is vendored anyway, because M15.4's audit reads these files and "the one licence that happens to require nothing" is not a distinction worth making an auditor rediscover. **Two files moved out of `static/` for the same reason, and the reason generalises:** everything in that directory is handed to a browser, so an `__init__.py` there would publish this project's source and its `__pycache__` the compiled form, and the vendor manifest — the one file in the project whose job is to contain external URLs — would have forced the no-external-URL test to carve out an exception on its first day. Nothing in either is secret, which is exactly why neither would have been noticed. **Committed rather than fetched**, which inverts [§1.4](AGENTS.md) and is the right call for a different kind of file: a reference panel is 63 GB the analysis reads, these are 114 KB the browser needs before the first paint. Fetching at runtime is the CDN request M4.3 forbids; fetching at install time makes an offline-first tool whose interface does not work offline. There is deliberately **no fetch script** — this happens about once a year, and a downloader nobody runs is a downloader nobody maintains, while the check that matters day to day (do the bytes still match the pin) needs no network and runs on every commit. Verified against a real uvicorn process as well as `TestClient`: both bundles served byte-for-byte by sha256, `Cache-Control: no-store`, security headers present, and the `Host` check covering the mount — a static mount outside the middleware would reopen M4.3's DNS-rebinding hole for the part of an app easiest to forget about. A packaging test pins that `static/` ships via `packages = ["src/genetics"]` rather than a force-include, because that is the quieter arrangement: moving these assets above `src/genetics/` would drop them from the wheel with nothing failing until somebody installed it and got a dashboard with no interactivity. All 6 guards verified by neutering each in turn — a CDN `<script src>` (caught three independent ways), a protocol-relative host in a first-party asset, the static mount itself, the sha256 pin, the htmx meta tag, and the missing-licence check. |
| 2026-08-17 | M4.2–M4.3 review | Self-pass plus `/code-review high` over the same uncommitted diff. **15 findings, all fixed** (4 found by both, 7 by the agent alone, 4 by the self-pass alone); each reproduced by execution before the fix and each new guard verified by neutering it. **1011 tests + 1 platform skip** (15 new); ruff, `ruff format` and `mypy --strict` clean. **The pattern, and it is not the same one as last time: a rule enforced against the *spelling* of something rather than against what it resolves to.** (1) **The one that mattered.** M4.3's wildcard refusal compared the host against a literal `{"0.0.0.0", "::", "[::]"}`, and six more spellings walked past it — `::0`, `0::0`, `0000::0`, `0:0:0:0:0:0:0:0`, `[0.0.0.0]`, `::ffff:0.0.0.0` — every one of which binds every interface and publishes an unauthenticated genome dashboard to the LAN. That is the single failure the module exists to prevent, and I had written the blacklist in the same file whose docstrings say to check outcomes rather than enumerate forms, two milestones after `check_run_id` learned it from the Windows drive-letter case and one commit after `payload_name` learned it again. Parsed with `ipaddress` and refused on `.is_unspecified` now, with all nine spellings in the parametrised test. **The self-pass missed it entirely**, which is the argument for running both passes rather than either. (2) **My own version of the bug I had documented against somebody else.** `config.py`'s docstring accuses Starlette's `TrustedHostMiddleware` of mangling IPv6 host headers — and the allowlist beside it was a fixed list of the *common* loopback names, so `WebConfig(host="127.0.0.5")`, which the class accepts and which is the ordinary way to dodge a port conflict, produced a server that refused every request to itself citing DNS rebinding. Derived from the bind address now, because a caller who has to remember to add their own address will not. (3) **`--verify` could be killed by one unreadable bundle** — the module's whole governing property, broken on the one path that opens anything. `read_bundle` digests payloads, so a locked file on Windows or a permission change raises `OSError`, which is not a `BundleError`; catching only the latter let it escape `list_runs` and take the other thirty-nine rows with it. Same root cause reached `runs show` and `runs delete`, where it printed a traceback instead of a sentence, so `_error_kind` gained `io`. This is the M3.7–M4.1 review's `_reference_provenance` finding again: a function whose job is to *report* had its degradation made conditional on the kind of unreadable. (4) **The listing vouched for a bundle nothing could open.** A manifest with no `files` key produced no names to check, so nothing was absent and the row came back `readable` with a card count — while `read_bundle` on the same directory refused it. Both sides take the required set from the writer's `PAYLOAD_FILES` now, which also promoted it out of private. (5) **`prune` reported removing directories still on disk.** `ignore_errors=True` is right — one locked directory should not stop the others — but paired with an unconditional append it printed "removed 3, 4.2 GB" for space that was never freed, and the CLI summed bytes from the pre-prune listing so it could print a byte count beside a count of zero. A swallowed error has to be looked for; that is the price of swallowing it. (6) **The 500 was the one response that escaped the policy.** Starlette's error handling wraps `@app.middleware("http")` from the outside, so a route that raises never reaches the line attaching the security headers — the docstring said "every response, including errors" and the parametrised test only ever produced 200s and 404s. Now an `exception_handler(Exception)` that carries them, and says nothing about what failed: an exception string is unbounded text from inside a process holding a genome ([§1.3](AGENTS.md)). (7) **`damaged` meant "not readable", which threw away the distinction `RunStatus` exists to preserve** — one newer-format bundle produced a footer reading "1 of 1 run(s) could not be read", pointing the user at a backup when the remedy is the tool that wrote it. Split, in both the CLI footer and `/healthz`. (8) **Two rules for what a link is.** `list_runs` excluded symlinks; `resolve_run` accepted any that resolved inside the root, so `runs/alias -> runs/real` was invisible to the listing, passed every check in `delete`, and died in `rmtree`. Following that up found the deeper half myself: **a Windows directory junction is not a symlink**, so `is_symlink()` returns False for one and it was listed as a run and then undeletable. Verified that `rmtree` does refuse a junction — nothing was ever at risk of being deleted through one — and both sites now ask one `is_link`. The containment check moved *ahead* of it so both stay reachable rather than one becoming dead code with a comment on it. (9) A test called `create_app()` bare, so its `/healthz` probe walked the **developer's real** `GENETICS_DATA_DIR` — reading whatever genome bundles happened to be saved on the machine, with a result that depended on them. (10) `main.py` claimed the runs command group was "stdlib only — no Polars, no yaml", which is false: it reaches `run.store` → `run.bundle` → `engine.cards`. Corrected rather than deleted, since the next person trying to make `--help` fast deserves to know what the deferred import does and does not buy. Smaller: `/healthz` was `async def` around a synchronous filesystem walk that sizes staging directories, so it blocked the event loop — a plain `def` puts it in FastAPI's threadpool for one keyword; `WebConfig` now stores the bare host because `"[::1]"` is not an address `socket.bind` accepts; and `_verify` rebuilds its summary with `replace` so a new field cannot be dropped on that path alone. **Worth recording about the process:** the agent found the highest-severity item and six others the self-pass did not, the self-pass found four the agent did not, and the two overlapped on four — so neither pass would have been sufficient, and the overlap is small enough that the second pass is not ceremony. |
| 2026-08-17 | M4.3 | FastAPI skeleton. **996 tests + 1 platform skip** (34 new); ruff, `ruff format` and `mypy --strict` clean. New deps: `fastapi`, `uvicorn` (runtime), `httpx2` (dev, for `TestClient`). **The milestone is three sentences long and two of them are weaker than they sound, which is most of the work.** *"Binds localhost only"* — the realistic route to `0.0.0.0` is not malice, it is someone hitting a connection refused from a VM or a phone and fixing the symptom, which publishes an unauthenticated genome browser to the LAN. So the host is validated at construction and the wildcard is refused **by name**, with a message that says what would be exposed rather than "invalid host". That needed a second check rather than a stricter predicate: `is_local_address` calls the wildcard local, and is right to, because it answers *"does this leave the machine"* about an outbound connection — as a *bind* address it means every interface, so the two questions genuinely differ at exactly one value. **And a loopback bind is still not the guarantee the sentence implies.** A page on the open internet can point a hostname it controls at `127.0.0.1` and have the visitor's own browser read this app; the request arrives on loopback and looks entirely ordinary. The only place the difference shows is the `Host` header, which still carries the attacker's domain — so the app checks it and answers 421. Worth noting *why* it is hand-rolled: Starlette's own `TrustedHostMiddleware` does `header.split(":")[0]`, which turns `[::1]:8765` into `"["`, so a user who binds to `::1` would be refused by their own server on every request, with a message about DNS rebinding. That case has a test. **The third sentence, *"no external requests"*, has two halves and only one of them is about this process.** A template referencing a CDN produces an outbound request from the *user's* machine to a third party, on a page whose subject is that user's genome, and nothing in the server would ever observe it. So: the server half is structural — a test parses the imports of every module under `web/` and fails if any reaches urllib, http.client, socket, requests, httpx or the project's own fetcher, which is M1.3's vendor-adapter reasoning applied where the consequence is worse than a layering violation — and the browser half is a `Content-Security-Policy` of `default-src 'self'` sent on **every** response, errors included, because a 404 is still a page a browser renders and it is the path least likely to be looked at. M4.4's static check is the other half of the same claim; two independent mechanisms for one promise, which is where M4.1 landed on the bundle destination. **FastAPI's interactive docs are off for precisely this reason** and it is the kind of thing that arrives switched on: Swagger UI and ReDoc load their assets from a CDN by default, so the promise would have been broken by a feature nobody enabled deliberately. **One refactor was forced and is the better outcome:** `is_local_address` moved out of `genetics/testing/network.py` into `genetics/netaddr.py`, because the offline guard and the server's binding policy must draw the same line — two copies would eventually disagree and the symptom would be the suite blocking the very server it is meant to drive. Smaller decisions: `create_app` is a factory rather than a module-level `app`, since an import-time instance would run this app's configuration checks during `genetics --help` and no test could give it a different runs root without reaching into globals; `/healthz` counts runs through `store.list_runs`, the same call `genetics runs list` makes ([AGENTS.md §3](AGENTS.md)), rather than a second traversal that agrees today; and it *reports* an unusable `GENETICS_DATA_DIR` instead of refusing to construct, because an app that cannot start cannot serve the page that explains why — M0.6's rule for `doctor`, on the surface someone is most likely looking at when they hit it. `httpx2` rather than `httpx` in the dev extra because current Starlette deprecates the latter loudly on every test run, and a warning nobody can act on is one everybody learns to skim — including on the day it says something else; it also went in `[project.optional-dependencies]` and not the `[dependency-groups]` table `uv add --dev` creates, since CI installs with `uv pip install -e ".[dev]"` and would not have seen it there, so the web tests would have failed on the runner and passed on every developer's machine. **The live-bind test is the one that could not be faked:** `TestClient` never opens a socket, so every other test in the file would pass against a config value that is carried around and ignored. It starts a real uvicorn on an ephemeral port, reads back the address the kernel actually bound, and speaks HTTP to it — M2.7's guard permits loopback explicitly and names this milestone as the reason it does. Also verified by hand against a real `uvicorn --factory` process, where the rebinding refusal answered 421 as designed. All 12 guards verified by neutering each in turn — the Host check, the IPv6 header parsing, both bind refusals, the port range, the empty allowlist, the CDN docs, the headers-on-every-response, the structural import check, the store-backed run count, the unusable-data-dir report, and the live bind assertion (fed `0.0.0.0` to prove it has teeth) — each failing exactly the test written for it. |
| 2026-08-17 | M4.2 | Save/load/list/delete. **962 tests + 1 platform skip** (50 new, 168 privacy-marked); ruff, `ruff format` and `mypy --strict` clean. **The governing question was what a listing is for, and the answer is that it has to work when a bundle does not.** The obvious implementation calls `read_bundle` per directory and is wrong in a way that only shows up on a bad day: `read_bundle` raises on damage, so one corrupt directory out of forty would take the listing for the other thirty-nine with it — and listing is precisely the command someone runs *because* something is already wrong. So the listing reads manifests only, reports damage as a row with a status, and never opens a payload. That is also the M0.6 shape (`doctor` reports a missing tool rather than exiting red on a fresh checkout) arriving one milestone later. The cost is that a manifest-only listing cannot see an edited payload, so the status is named **`readable`, not `ok`** — it claims the manifest parsed and the files it names are present, and nothing more — with `--verify` for the stronger question and `RunListing.verified` recording which question was asked, because a consumer cannot tell the two strengths apart from the rows alone. **The staging-directory decision is where the roadmap's own instruction was not sufficient.** It said listing must skip `.incoming-` by shape, and skipping it is right; skipping it *silently* is [the `refs status` finding from the M3.3–M3.6 review](#progress-log) with different nouns — a stale multi-gigabyte intermediate reported as nothing at all, with no line telling the user it existed or what to do. After M8 an interrupted save is the same size and the same mistake, so it is counted, sized and given `runs prune`. **One real defect came out of running the CLI rather than the tests, which is the part worth recording.** Deletion identifies its target instead of trusting the name: writer's own `check_run_id`, then containment checked on the *resolved* path (a plain name can still be a symlink out of the store, and a name-based check cannot see that), then "is this actually a bundle". I implemented that last check as *filenames only* — and a smoke test against a hand-made v2 bundle showed it refuses to delete a bundle written by a **newer** engine, because that bundle carries payload files this version has never heard of. The user is then left a run they can neither read (the version gate stops that, correctly) nor remove — strictly worse than either failure alone, and invisible to every test I had written, because every bundle in them was written by this engine. Fixed by asking the manifest first: a directory declaring a bundle format version *is* a bundle whatever else is in it, and the filename rule drops to being the fallback for wreckage with no manifest left to speak for it. That also narrowed a claim — `BUNDLE_MEMBERS` now governs only the wreckage path, so the "M5/M8/M9 must add their payload here" coupling is real but weaker than I first wrote it, and the test says the weaker thing. **The privacy split is inherited from M4.1 rather than reinvented, and both halves are asserted.** `runs list` is scanned with `assert_no_genotype` on **both** branches — M1.8 is the precedent and the warning, since its first cut guarded the JSON branch and left the human render open, which is the branch a person is more likely to edit; the test is parametrised over the two so removing either call fails. `runs show` is deliberately *not* scanned: a card's summary states the reader's own genotype because that is the product, and a guard that fails on correct output is one somebody switches off ([M0.3](#progress-log)). Both directions have a test, so neither can be "fixed" by accident. Two smaller decisions. The store is addressed through `GENETICS_DATA_DIR` with **no `--runs-root` flag** — a test-only way to name the store is a second name for one thing (M0.4, M3.7, M4.1, three times now), and the tests would then exercise a path no user takes; the library functions keep the parameter, the CLI does not. And `--json` on a destructive command **requires `--yes`** rather than assuming it: there is nobody to answer a prompt, so a non-interactive caller that meant to delete says so and one that did not gets an error instead of a deletion. `runs show` was kept thin on purpose (bundle header, one line per card, whole record on `--json`) because [M13.1](#m13--agent-interface) owns the analysis surface; that item is now marked `[~]` with what M4.2 delivered and what remains, on M3.7's precedent that the failure mode is two commands for one job and the second author has no way to know. **One defect in M4.1's own reader fell out of building on it.** `manifest["files"]` maps a name to a digest and both readers turn it into `directory / name` — so an edited manifest naming `../elsewhere` sends the new listing to stat, and `read_bundle` to *hash*, a file outside the bundle, and reports the result as this run's integrity. That is not a hole in the threat model, which excludes tampering explicitly and says so; the point is duller and worth stating precisely rather than dressing up. A manifest naming a file somewhere else is a **damaged manifest**, and reporting it as one beats an integrity failure against a file the user never associated with this run. Checked on the outcome — a payload name must equal its own basename — which is `check_run_id`'s conclusion and M2.5's archive extractor's before it, applied to the third place in this codebase that turns untrusted text into a path. Also the reason the test adds the bad entry *beside* the real ones: `read_bundle` checks the required files are recorded before it builds any path, so replacing the map trips the earlier check and never reaches the one under test — a first draft that passed while proving nothing. All 14 guards verified by neutering each in turn — both genotype scans, the membership rule, the resolved-path containment, the version/damage distinction, the `--yes` requirement, staging reporting, `--verify`, payload presence, the future-version status, the `BUNDLE_MEMBERS` pin, the shared run-id check, manifest-first identification, and the payload-name check — each failing exactly the test written for it, and the parametrised privacy test failing only the branch that was neutered. The symlink containment test falls back to a Windows directory junction when `symlink` is refused, so the check is verified on the platform §4.9 says this project actually runs on rather than only in Linux CI. |
| 2026-08-16 | M3.7–M4.1 agent review | `/code-review high` over the same two commits, run alongside the self-pass. **9 findings, 8 confirmed and fixed, 1 sub-claim wrong.** 912 tests (163 privacy); ruff, `ruff format` and `mypy --strict` clean. Again every finding was in M4.1 — the impossibility cards drew none from either pass, which is what a milestone with no executable logic should look like. **(1) The sharpest one, and it made a test of mine vacuous.** M4.1 named the payload files `qc.run.json` / `cards.run.json` to land on `.gitignore`'s `*.run.json` rule, and asserted the coupling with `assert "*.run.json" in ignore` — a *string search over the file*. But `!/knowledge/**/*.json` sits 114 lines later and wins: `git check-ignore -v knowledge/x/cards.run.json` reports the negation, and `git status` offers the file for commit. So a user dropping a saved run under `knowledge/` to see which cards fired, then running `git add -A`, commits per-card genotypes — the exact [§1.1](AGENTS.md) failure the rule exists to stop. A string grep cannot see precedence, negation or ordering, which are the only things that decide the answer; the test now shells out to `git check-ignore` and is parametrised over five directories, and a companion test asserts card files are *still* trackable so the re-ignore rule cannot be fixed by breaking the corpus. This is M0.4 again — "a test written to check a command survived as a test that checks a comment" — and it is the second time in this project a guard-for-a-guard has been the thing that was broken. **(2) The version gate was equality, which is a trap that springs later.** `declared != BUNDLE_FORMAT_VERSION` refuses *older* bundles as well as newer. Adding any payload key bumps the version, M5/M8/M9 all add payload, and a bundle is immutable — so no in-place migration is even possible, and the first bump would have permanently orphaned every run a user had saved. The fix is a **contract, not machinery**: payload keys may be added, never removed, never repurposed, so an old bundle carries everything a newer reader requires and nothing it does not recognise — which means `read_bundle` can accept anything at or below its version with the strict unknown-key check left untouched. A key whose meaning changes gets a new name. Tested by monkeypatching the engine version forward and reading the v1 bundle the fixture just wrote, since there is no v2 bundle to test with. Worth noting the agent proposed accepting `<=` without saying what makes it safe; accepting it without the additive rule would only have moved the failure from a clear version error to a shape error. **(3) `knowledge_provenance` emitted a well-formed digest of the empty set** when the pack directory was gone, because `rglob` on a missing path returns nothing rather than raising — so two bundles from two different packs would agree on the one field whose whole job is answering "was this the same pack I have now?", beside a truthful `card_count`. Same shape as M0.6's HIBAG probe: a check that can only return one answer. Raises now. **(4) and (5) are one mistake in two places:** `_reference_provenance` caught only `LockError` and `_load_json` only `JSONDecodeError`, while both functions exist to turn a damaged file into a *report*. A corrupt lock raises `UnicodeDecodeError` from `read_text` and an unreadable one `OSError`; neither is a `LockError`, so both propagated out of `write_bundle` and discarded a completed analysis over a file the run never used. On the read side the manifest is parsed *before* any digest check, so mangled bytes are the common corruption path — and M4.2's CLI will be catching `BundleError`, so it would have crashed rather than reported damage. **(6)** The cards file's one-key wrapper was the level `_reject_unknown` never covered — the manifest and each card were checked, the object between them was not. My own self-pass had found the *nested* gap and narrowed the claim; this is the same class one level out, and here enforcement was cheap and right. **(7) `AssembledCard.observation` was dropped for every non-matched card**, where `confidence` is `None` and therefore carries no `call_source`. After M8 a saved run could not distinguish "the marker is not on this array" from "imputation was attempted and failed". Recovering it later means a payload key, i.e. a version bump; adding it now, at format 1 with no bundle existing anywhere, is free. **(8)** Run-id validation refused the full `.incoming-` prefix but permitted any other leading dot, so a run named `.draft` would be written successfully and then hidden by the shape-based listing M4.2 is about to build — a bundle that exists and cannot be found. **(9) A regression I introduced in M4.1 itself.** Teaching `read_state` to filter non-record values was right; `record_install` does read-modify-write, so filtering on read *and* writing the filtered view back meant the next install of any unrelated tool permanently erased a malformed entry, including the licence block kept for the M15.4 audit. **That is the M2 lock bug in a new place** — "recording only the current run's successes replaced the file map, so the digest of the file that just failed was dropped" — and the resolution is the one the lock already reached: the write merges over what is on disk, so success elsewhere cannot erase evidence here. Writing now goes through `render_state(Mapping[str, Any])` rather than the dataclass, because routing preserved-but-unvalidated entries through a field typed `dict[str, dict[str, Any]]` would put the annotation-that-lies back one layer over, which is the defect the whole change started from. **One sub-claim was wrong and was checked rather than accepted:** the review called `recorded_path`'s `isinstance(entry, Mapping)` dead code after the filtering change. It is not — `.get()` returns `None` for an absent tool and `None` is not a `Mapping`, so the check still does real work. `mypy --strict` confirms it, having flagged the genuinely unreachable version of exactly this check when I wrote it in `_tool_provenance`. All eight fixes verified by neutering each in turn; each failed exactly the test written for it. |
| 2026-08-16 | M3.7–M4.1 review | Self-pass over the two commits. **5 findings, all fixed, each reproduced by execution before the fix.** 899 tests; ruff, `ruff format` and `mypy --strict` clean. **Every one was in M4.1, and four of the five are the same shape: a value or a path treated as equivalent to another that it merely resembles.** (1) **The run-id check blacklisted separators, and on Windows that is not what containment means.** `root / "D:elsewhere"` *discards* `root` and yields a path on another drive, and that string contains neither `/` nor `\` — so `destination` pointed at another volume while `staging` (built from `INCOMING_PREFIX + identifier`, which neutralises the drive-relative form) stayed under the root. Nothing escaped: the write died on `mkdir` with a confusing OS error, and `destination.exists()` had by then been asked about a path outside the runs root. So this is a validation gap and a latent trap for M4.2's `--run-id`, **not** a demonstrated leak, and it is worth saying so precisely rather than dressing it up. The fix checks the *outcome* — a run id must equal its own basename — which is the conclusion M2.5's archive extractor already reached about member names, unapplied here. `.` and `..` are named explicitly because `Path("..").name` is `".."`, so they pass a basename test. (2) **`run_id or new_run_id(stamp)` treated an explicit empty string as "not supplied"** and generated one, so a CLI passing a blank `--run-id` would get a bundle under a name it did not choose, silently. Falsy is not absent; found because the new validation test asserted `""` was refused and it was not. (3) **The strictness claim was one layer wider than the code.** `read_bundle` rejects unknown keys at the top level of the manifest and of each card — but not inside `provenance`, `match` or `confidence`, and the key-pinning test only pinned the two top-level sets. Confirmed by adding `match.phase_set`, `confidence.polygenic` and `provenance.future_field` to a bundle, refreshing its digest, and reading it back with no complaint at all. **The fix is to narrow the claim rather than widen the code**, which is the opposite of the usual reflex and is right here: a bundle from a newer engine is refused by the version gate before any key is examined, so recursive strictness on read buys almost nothing while forcing the reader to carry the full nested schema this format is explicitly designed not to have. What actually needed to exist is a developer-facing check, so the enforcement moved to a test that pins the payload's entire nested key shape at any depth. (4) **The round-trip suite had never serialised an `empirical_ppv`**, because it is `None` for a common variant and every fixture card was common — so the `likely-artifact` path, which [§4.1](AGENTS.md) calls the most important thing the interface communicates, was the one thing the format had never been shown to preserve. A rare card joined the fixture; its PPV block is now pinned by shape and asserted by value. (5) Stale docstrings after the `cards.json` → `cards.run.json` rename, in both the module and the tests — the claims-the-code-does-not-honour class, in its most trivial form, in the commit that renamed them. |
| 2026-08-16 | M4.1 | Run bundle format. **896 tests + 1 platform skip** (28 new, 158 privacy-marked); ruff, `ruff format` and `mypy --strict` clean. **The governing question was what a bundle is *for*, and the answer is that it must still say the same thing after the code that wrote it has moved on.** Everything else follows. The obvious design stores a card id per finding and re-renders from the knowledge pack at read time — half the bytes, one copy of the text, and it passes every test you would naturally write. It also means editing a card tomorrow silently rewrites what a run said today, and a saved run is the thing a person read, discussed, and may have made a decision on. So the bundle records rendered summary, detail, citations, caveats, confidence tier *and* the numeric inputs behind it, and nothing in `read_bundle` touches `knowledge/`. The test deletes the pack after the write and reads the bundle anyway, because a property this easy to lose deserves a demonstration rather than a docstring. **The same reasoning produced the one decision that looks like laziness and is not: reading returns plain strings, not engine enums.** Re-hydrating a `Section` or a `ConfidenceTier` is precisely what breaks when a later version renames a member, and M4.2 asks for a months-old bundle to re-read *or fail with a clear version error* — not to fail with `'traits' is not a valid Section` from four frames down. The format version is the compatibility gate; the payload is data. Every dataclass the reader insists on is another way for an old bundle to fail with a shape error instead of a version error, so `match`, `confidence` and `variant` stay mappings. `confidence_tier` is promoted to the top level as the one exception, because M4.6 puts it on the card face and M4.7 sorts by it, and a renderer digging three levels for the field it always needs is a renderer that caches it wrong. **Immutability is refusal plus detection, and deliberately not file permissions.** M0.4 was already bitten by cross-platform mode handling, and a read-only bit on a user's own data directory is advisory anyway. So a write refuses an existing run id, the payload is built under `.incoming-<id>` and promoted by a single rename — M3.5's pattern for the multi-GB dbSNP transforms, applied where the same failure (a killed process leaving a plausible-looking artifact) has worse consequences — and every payload digest is re-checked on read. **The manifest is deliberately not self-digested**: that regress ends in a file whose own integrity is unverifiable while looking like a guarantee, which is the confidence-manufacturing failure M0's review was about. What the digests catch is corruption, truncation and hand-editing. Tampering is not in the threat model and the docstring says so rather than implying otherwise. **The privacy split is the part worth arguing about.** The manifest and the QC report are scanned with `assert_no_genotype`; `cards.run.json` is not, because it holds per-card genotypes *by design* and a guard that fails on correct output is a guard someone switches off — M0.3's cries-wolf lesson landing on the one boundary where scanning everything is the obvious move. Both scans are then driven with input they must reject (a genotype row in `source_path` for the manifest, one in a QC warning for the report — reaching the two files by different routes, which is what proves they are two calls), because a negative assertion passes when it is broken. Deleting the manifest scan leaves every other privacy test in the file green. Two smaller decisions: run ids are timestamp-plus-random rather than a digest of the export, since a stable digest is a persistent pseudonymous identifier for one person's genome sitting in every directory listing and log line — genotype-derived ([§1.1](AGENTS.md)) in the one place a bundle's contents are not; and the payload filenames were renamed onto `.gitignore`'s existing `*.run.json` rule, a third line of defence behind writing outside the repo and refusing an in-repo destination outright, with a test asserting the coupling from both ends because nothing about `qc.run.json` explains why it is not `qc.json`. **One latent bug fell out, and its shape is the interesting part.** `refs.tools.read_state` annotates `dict[str, dict[str, Any]]` but validated only the outer mapping, so a hand-edited state file could put a string where a record belongs. The bundle's tool-provenance reader wrote the defensive `isinstance` a caller naturally writes — and `mypy --strict` called it **unreachable**, correctly, according to the very annotation the function was not enforcing. A type that lies is worse than no type, because it disarms the caller who would otherwise have checked. Fixed at the source rather than worked around at the call site. `read_bundle` **rejects unknown payload keys**, on the card schema's reasoning, which makes adding a field a format change: a test pins both key sets with "bump BUNDLE_FORMAT_VERSION in the same commit" attached, since that is exactly the coupling nobody remembers. All 28 tests verified non-vacuous by neutering seven guards in turn — digest comparison, version gate, unknown-key rejection, staging cleanup, in-repo refusal, manifest scan, overwrite refusal — each failing exactly the test written for it. **The in-repo neutering proved the point better than the argument did.** With that one check disabled the test wrote a real bundle to `<repo>/scratch_runs/`, and `git status` listed it as untracked — no `.gitignore` rule covers a directory nobody predicted, which is exactly why the destination is refused rather than trusted to the ignore file. The contents were synthetic and the pre-commit content scan would have caught a real genotype, but the artifact reached the working tree of a public repo in the ordinary course of running tests. Caught by `git status` before staging, which is [M2.5's lesson](#progress-log) recurring: some things are only visible from outside the test suite. |
| 2026-08-16 | M3.7 | Impossibility cards. **868 tests + 1 platform skip** (9 new); ruff, `ruff format` and `mypy --strict` clean; `genetics cards lint --schema-only` passes 43 cards and 210 template renders, up from 31 and 186. No engine change was needed — M3.1 built the schema, M3.2 the `NOT_DETERMINABLE` status, M3.4 the assembly branch and M3.5 the lint path — so this was authoring, and the work was in deciding what the cards had to *not* do. **The governing decision was to read §3.2 out of AGENTS.md at test time rather than transcribe it.** §3.2 says "maintain this as a live register", and the natural implementation is a directory of cards that somebody remembers to update. That is [M0.4's failure](#progress-log) with different nouns: two ways of naming one set, no comparison between them, and the divergence only visible to whoever happens to look. So the test parses the bullets out of §3.2 and holds the mapping in both directions — a new bullet with no card fails, and a card no bullet declares fails. Verified by inserting a fake bullet, which failed exactly one test with a useful message. **The second decision was placement, and it is what makes these cards worth shipping at all.** An appendix of "things we cannot do" is read by nobody; the reader who needs the SMA card is the one scrolling the carrier-status section looking for SMA and finding nothing, and concluding they are clear. So each card sits in the section that would otherwise look complete — CYP2D6 with the pharmacogenes, SMN1 and alpha-globin with carrier status, Y-STRs and heteroplasmy and relative matching with ancestry — which is M14.6 arriving early because it costs nothing to get right now and is invisible to fix later. A side effect worth noting: five sections stopped being empty, and a section whose only content is "here is what this data cannot tell you, and why" is a better answer than a blank one. **Three things came up in the writing.** (1) **The CYP2D6 card is not about uncertainty, and saying so is the whole card.** A `*5` deletion leaves one gene copy, so everything on it reads homozygous and `*5/*29` is reported as `*29/*29` — a specific, confident diplotype with a different predicted phenotype from the truth. "We cannot call this reliably" would be the wrong sentence; the card says the answer comes out *wrong*, which is the same distinction [§4.1](AGENTS.md) draws for rare pathogenic calls. (2) **Every card names the adjacent question that is answerable**, in a caveat: Y-SNP haplogroups beside Y-STRs, mtDNA haplogroup beside heteroplasmy, ROH beside both the CNV card and relative matching. Without it "not determinable" generalises in the reader's head to "nothing here is knowable", and the ancestry section in particular would read as though the whole mitochondrial genome were off limits. (3) **The pack ships zero citations and a test keeps it that way.** M3.1 exempted these cards on the reasoning that demanding a DOI for "an array does not measure methylation" pushes an author toward citing something tangentially related. That reasoning only holds while the exemption is unused — one cited impossibility card and the next author infers that citing is expected — so the invariant is asserted rather than trusted, and `impossibility_reason` is where the justification goes. **Two roadmap boxes turned out to describe cards this milestone had to write anyway**: M10.3 (CYP2D6 not-callable) and M11.6 (carrier-screening incompleteness). Both are now annotated with what actually remains — placement beside the called diplotypes for M10.3, and the section-level completeness statement for M11.6, which is a different claim from the two per-gene cards and needs M11.5's callable set to exist first. Recorded in the roadmap rather than left to be rediscovered, because the failure mode is two cards for one fact, and the second author has no way to know the first exists. Smaller things: `impossibility_reason` is *not* template-checked (only `summary` and `detail` are), so a `{gene}` written there would render literally — avoided, and worth knowing before the next author tries it; and the privacy scan that existed over `tests/fixtures/cards` now also covers `knowledge/` itself, which is the corpus the pre-commit hook actually runs over and was not being scanned by any test. All nine new tests were verified failing by neutering each guard in turn — wrong section, deleted card, invented §3.2 bullet, added citation, removed carrier caveat. **One AGENTS.md correction**, per this log's own instruction to fix AGENTS.md when something contradicts it: §7's pre-commit checklist said flatly "new cards carry real citations", which twelve correct cards now violate. Left as written it is a checklist item that reads as failed on every impossibility commit, and M0.3 already established what happens to a check that cries wolf — it gets ignored, including on the commit where it was right. Item 6 now distinguishes the two kinds and says why the exemption exists, so the next author meets the reasoning at the moment they would otherwise go looking for a DOI. |
| 2026-08-16 | M3.3–M3.6 review | `/code-review` over the M3.3–M3.6 commit (44 files, ~8.1k lines). **15 findings, all fixed, each verified by execution before the fix and each new test confirmed failing against the pre-fix code by neutering the fix in turn.** 859 tests; ruff, `ruff format` and `mypy --strict` clean; the full dbSNP lint re-run against the real 10.7 GB index (31/31 variants resolved) and `refs verify` re-run against the real ClinVar tree. **The pattern this time was a rule that was right for one kind of input being applied to a second kind it silently damages** — and the sharpest instance was in the previous session's own work, plus one in the commit that shipped it. (1)+(2) **The two that would have broken every fresh clone, and neither is visible from the machine that made them.** ClinVar's `variant_summary.txt.gz` is the one file the manifest explicitly declares unpinnable, "regenerated weekly under a fixed name" — and it had just been pinned twice: M3.5 added a hard `size != expected_size` check, and committing `manifest.lock` handed every clone the sha256 one machine recorded on 2026-08-16, because `_expected_sha256` falls back to the lock when the manifest has no digest. The week the publisher regenerates that file, a fresh clone's fetch fails on both counts, `fetch_source` skips post-processing, the build anchors are never produced, and `default_anchors()` quietly degrades to empty — while the machine that wrote the lock reproduces none of it, short-circuiting on already-present. **The fix is a scope, not a switch**: drift is tolerated for bytes that *just arrived over the wire* and never for bytes already on disk. That keeps the M2 review's hardest-won property intact — a corrupted local file still fails and still cannot launder its digest into the lock — while unblocking the clone, and it is checkable: after a fetch the lock always agrees with the disk, so a `verify` disagreement can only be something nothing fetched. Truncation is caught by the length *the response itself declared*, since the manifest's size is stale by design for these files. (3) The same commit's `_run_anchors` and the merge loader had the mirror-image problem: `resolve()` was correctly made to **raise** on an rsID dbSNP says has zero or several current targets, but `resolve_all`/`add_current_rsid` were not updated, and those run over **every row of the user's export**. One of b157's ~23k ambiguous retirements appearing in a 677k-row file would have aborted the ingest. The table side now writes **null** — not the original ID, which is the false identity the raise exists to prevent, and not an exception, which refuses to read a file the user did not author. Nulls propagate, exactly as M1.1 made no-calls propagate. The *query* side still raises, because an explicit question about an ambiguous ID deserves a loud answer. (4) `default_anchors()` hard-coded `expected_count=200` while the manifest declares `count: 200` — so editing the manifest produced a valid artifact that every subsequent `genetics ingest` rejected, aborting on the user's genotype file for a reference-configuration change. Two copies of one number, and the wrong copy was in the layer with the least right to it. (5) The provenance sidecar recorded the manifest-relative output path while the reader compared it against the basename, so any step declaring `sub/out.parquet` — which `_check_relative_filename` permits and `implementation_paths` goes out of its way to support — would write its artifact successfully and then be refused on every later read, by every runtime consumer, forever. (6) **Lint was strictly weaker than production while claiming to be forward-compatible.** Its synthetic context supplied `{frequency}`, `{ppv}`, `{ancestry}` and more, which `evidence._template_values` does not; the moment M7.2 flips `frequency` to available, an author using it would get `PASS` from the release gate and a runtime `KeyError` from the renderer whose own message says to treat it as an engine bug. The context is now filtered to the registry's available set, with a test asserting lint, production and registry name the same placeholders — the forward-compatibility the original reached for, in the direction that cannot certify a broken pack. (7) **`_effect_score`'s docstring described the half-width and the code divided by the full width.** Not cosmetic: the difference moves saturation from z≈1.96 to z≈3.92, so under the documented rule every nominally significant effect would score 1.0 and the component could not separate "just reached p<0.05" from "unmistakable". The code's calibration was the better one and is now the documented one, with three pinned points and the crossover made explicit — an authored interval beats the interval-free 0.5 default exactly when the effect becomes significant. (8) One missing gnomAD allele frequency raised out of `assemble_card` and **took the whole pack with it**: 31 findings discarded because one reference row was thin. That is the low-confidence filtering [§0.1A](AGENTS.md) forbids, arriving as an exception rather than as a policy. It degrades per card now, with a caveat naming the allele, and `calculate_confidence` already caps an unknown frequency at `moderate`. (9) `refs verify` reported FAILED for a source whose downloads were all intact but whose transform had not run, while `refs status` called the same tree "processing-required" and stayed green — two commands disagreeing about whether the tree was broken, at exactly the moment someone runs one to decide whether to resume. Absent output is `PENDING` now; present-but-unvalidatable is still FAILED. (10) A stale multi-GB intermediate from a killed transform is indistinguishable on disk from a live one, so "processing" was reported forever with no line saying a rerun was needed. `_run_merges` keeps that file deliberately, so the state now says what the user must do and the partials are reported as the detail they are. Three smaller ones: every resolver lookup SHA-256'd the *entire* artifact, so `cards lint` streamed 10.7 GB to read 31 rows and `MergeTable.default` did it twice more per matcher build — memoised per process by path, size and mtime, with a test proving a changed artifact is still caught; `Effect.parse` hand-rolled the numeric validation `_number` already performs, which is why the finite check existed twice with two different messages; and `_run_anchors` took a `Source` it never read while validating its output twice over. **The through-line:** none of the fifteen was a missing idea. Each was a rule applied one input-kind, one layer, or one direction wider than the reasoning that justified it — pinning applied to a file declared unpinnable, a raise applied to rows the user never chose, a count copied into the layer that cannot know it, a lint context generous where generosity is what certifies the break. |
| 2026-08-16 | M3.3–M3.6 | Confidence, evidence assembly, card lint, the post-processing runner, and the first seed pack. **845 tests + 1 platform skip, 150 of them privacy-marked**; ruff, `ruff format` and `mypy --strict` clean. *(The implementing session ran out of budget before it could commit; a later session ran the checks, applied `ruff format` to three files, and wrote this entry. Every number here is measured on the committed tree, not carried over from the earlier session's notes.)* **M3.3's governing decision is that reliability is a ceiling, not a term in the average.** The weighted score (evidence 0.30, replication 0.20, frequency 0.20, effect 0.15, imputation 0.10, ancestry 0.05) describes how strong an otherwise-trustworthy finding is; a very rare chip call or a badly imputed one caps the result at `likely-artifact` outright. Averaging rarity into a prestigious ClinVar evidence tier would let excellent literature about a variant conceal a weak *observation* of it, which is [§4.1](AGENTS.md) inverted — the single thing the roadmap calls the most important correctness requirement in the project. The 0.16 figure travels with the tier as an **empirical band statistic and is labelled as one**: it is the observed confirmation rate for rare heterozygous SNP-chip calls, not this person's posterior probability, and a card that renders it as the latter is wrong in the direction that scares people. Ancestry mismatch and poor imputation may only ever lower, never raise. **M3.4's rule is cardinality**: `assemble_pack` returns exactly one record per card in pack order, so absent markers, no-calls, excluded indels, impossibilities and `likely-artifact` results are display states rather than filters ([§0.1A](AGENTS.md)) — the same rule M3.2 imposed on the matcher, carried one layer up where dropping something would be easiest to justify. Frequencies enter as a `PopulationFrequency` carrying allele, population and source rather than a bare float, because M7.2 supplies these from gnomAD and a float loses which allele in which population it described somewhere between the gate and the run bundle. **M3.5 turned out to be mostly M2.1's unfinished business.** Linting a card against dbSNP needs dbSNP *in a queryable form*, so the milestone had to build the post-process runner the manifest had been declaring at for two milestones. Three steps are now executed for real — `extract_dbsnp_variant_index`, `extract_rsid_merge_table`, `extract_build_anchors` — and the M2 review's finding (three steps marked `implemented=True` with no executor anywhere) is now structurally unrepeatable: `assert_registry_is_honest` asserts the set of steps claiming implementation equals the set the dispatch names, and a test holds it. The remaining seven stay `implemented=False` and visibly pending. Transforms are restartable by construction: chunked Parquet with a checkpoint, promotion by `os.replace`, so a killed process can leave a `.part` or a chunk directory but never a file bearing the declared output name — which matters because the dbSNP VCF is 28.2 GB and a decompression pass is measured in hours. Every artifact carries a provenance sidecar binding the input digest, the parameters, the transform version, the row count and the output digest, and a present artifact whose sidecar is missing, mismatched or built by a different transform version is **refused rather than used** — a not-yet-fetched dbSNP still leaves `MergeTable` at identity, which is the honest state before reference setup, but a *stale* index is a wrong answer wearing a right one's filename. The manifest gained a validator for the *program* as well as the steps: an input must already exist as a download or an earlier output, and no output may overwrite a publisher payload or another derived artifact — without it a one-word typo replaces a checksum-pinned 28 GB source after fetch verified it, while the lock still records the original digest. **Two real corrections came out of running it.** (1) The roadmap said M1.5's build anchors would come from dbSNP; they cannot. A GRCh37-only VCF cannot prove a GRCh38 coordinate, and an anchor is *by definition* a pair of coordinates for one rsID. They come from ClinVar's `variant_summary.txt.gz`, which publishes both assemblies per variant — 200 anchors derived, uncommitted, and M1.5's deliberately empty table finally has data behind it without a single coordinate written from memory. (2) dbSNP's merge records are not a function: of the b157 file's records, **21,562,332** map one retired rsID to exactly one current one, and **23,340** do not — zero targets, several targets, or a cycle. M1.7's stated default ("unknown rsIDs resolve to themselves") is right for an rsID dbSNP has never heard of and *wrong* for one dbSNP explicitly says has two current targets; self-resolving the latter turns ambiguity into identity and looks up the wrong variant with no visible failure. Those 23,340 now load into their own artifact and `resolve()` raises on them. The variant index itself is **1,145,977,318 rows** at 10.7 GB of Parquet, queried by scan rather than loaded. **M3.6 is 31 cards rendering 186 genotype-specific templates**, every one resolved against that index for rsID, GRCh37 position and alleles, each tied to primary literature with quantitative effects, sample sizes, study populations and caveats. Deliberately a curated pack rather than a bulk import: the corpus is committed and reviewable as a diff ([§3](AGENTS.md)), which is only true while a human can actually read it. Packaging caught one thing worth recording — `knowledge/` sits at the repo top level so it stays reviewable, which means an installed wheel would not contain it at all; hatch force-includes it at `genetics/knowledge`, `default_knowledge_dir()` prefers the checkout and falls back to that path, and a test pins the force-include contract and the three card files, because "works from a checkout" is exactly the bug that survives every test written from a checkout. The test is structural rather than building a wheel at pytest time; the release gate is where an actual built artifact should be opened. **CI had M0.4's bug.** The hook was fixed in M3.1 to select privacy tests by marker instead of by directory; the workflow still ran `pytest tests/privacy` and was therefore skipping the same distributed privacy tests on every push. Fixed, with a test that reads `ci.yml` and asserts the selector — the same shape as the one already reading `.githooks/pre-commit`, and a reminder that fixing an instance is not fixing the class. CI also now runs `genetics cards lint --schema-only`, which exercises every card check except the reference lookup that needs the 28 GB download. **The honest gap at the time of this commit:** these four milestones had not yet had the diff-driven review pass that M0, M1, M2 and M3.1–M3.2 each got. It ran immediately afterwards and found fifteen — see the entry above. |
| 2026-08-16 | M2.7–M3.2 agent review | `/code-review high` over the same four commits, run alongside the self-pass. It correctly excluded the eight the self-pass had already fixed and found **9 more, all confirmed by execution before fixing, all fixed**. 672 tests; ruff, `ruff format` and `mypy --strict` clean. **Two of them were guards that had grown a blind spot exactly where the surrounding code was most careful.** (1) `_orient` returned early for self-complementary sites *without checking the observed alleles were declared at all*, so a card declaring A/T against a row reading `C`/`C` skipped the mismatch branch and fell into the "the schema should have made this impossible" one — telling the reader to file a bug report about their own mis-coordinated card. **Roughly a third of SNPs are A/T or C/G, so that was the normal mismatch path for them.** The fix is one membership check, and it is cheap precisely because the complement of {A,T} is {A,T}: one test covers both strands. (2) The MATCHED result set `genotype` even when the strand was ambiguous, contradicting the field docstring written *in the same review session* — which says it is `None` "whenever no strand could be established, which includes a self-complementary site where the reading is undecided". A renderer honouring the documented invariant would have printed `TT` for a call that may equally be `AA`. The invariant was right and the code did not keep it; now the answer comes from `outcome` and the letters from `observed_genotype`. (3) The self-pass's own strand-canonical duplicate fix **overreached at self-complementary sites**: `AA` and `TT` collapse to one form there, so two probes reading opposite homozygotes were announced to the reader as agreeing, and the `observed_genotype` shown was whichever row the join returned first — polars guarantees no order. Compared literally at ambiguous sites now. That is a fix to a fix from four hours earlier, and the pattern is worth naming: a normalisation that is correct in one regime silently changes meaning in another. (4) The duplicate-conflict reason interpolated the *total* probe count while the conflict was decided over the called ones, so three probes with one no-call read as "3 probes produced different genotypes" when only two had produced any. (5) `ci_low`/`ci_high` went straight to `float()` while every other numeric field carried an isinstance guard: a string raised an unlocated `ValueError` naming neither file nor key, and a list raised **`TypeError`, which is not a `ValueError` at all** and so escaped every `except CardError` in the call chain — breaking the loader's contract that a malformed card yields a located error. (6) `_check_template` validated against the global registry only, so an impossibility card could use `{genotype}` and any card could use `{gene}` without declaring one — both render blank, which is exactly what the milestone gate three lines above exists to prevent. The same rule, left unapplied to the per-card case. (7) `gene` was parsed and then silently dropped for impossibility cards — a key accepted with no effect, which this module's own docstring calls out by name. Passed through rather than refused, because AGENTS.md 3.2's examples are gene-named (SMN1, RHD, CYP2D6). (8) The stray-file guard globbed `*.yml` only, and `rglob` is case-insensitive on Windows but case-**sensitive** on Linux, so `traits.YAML` loads on the author's machine and vanishes in CI — the precise failure the guard was written for, reintroduced by the guard's own glob. (9) **The most consequential.** The offline fixture was function-scoped, and pytest builds session- and module-scoped fixtures *first*, so the guard was not installed while any of them ran — verified empirically, `guard_is_active()` returned False inside both. A module-scoped "fetch the reference once" fixture is the most natural home a stray network call could ever find, and it would have sailed past M2.7 with the whole guard suite still green. The block now goes on once at session scope and `allow_network()` lifts it for a `network`-marked test. **The through-line across all nine, and across the eight before them: every one sits at a boundary the surrounding code had already reasoned about correctly** — ambiguous sites, strand normalisation, the loader's error contract, the placeholder gate, the stray-file guard, fixture scope. None was a missing idea; each was an idea applied one scope, one branch, or one platform short of where it needed to reach. |
| 2026-08-16 | M2.7–M3.2 review | Self-pass over the session's four commits. **8 defects, all fixed, each with a test that fails against the pre-fix code** (verified by neutering each fix in turn). 656 tests; ruff, `ruff format` and `mypy --strict` clean. **The pattern this time was assumptions re-entering one layer below where they had been rejected, and fields whose meaning depended on something else.** (1) **Duplicate probes on opposite strands read as a conflict.** `_resolve_duplicates` compared raw genotype strings, so `AG` beside `CT` — one call written twice on different strands — came out as `DUPLICATE_CONFLICT` and suppressed an answer the data plainly contains. The matcher exists *because* the vendor's forward-strand claim is not trusted, and the duplicate check had quietly trusted it one function lower. Now compared on a strand-independent canonical form, which provably cannot invent an answer at a self-complementary site: `AA` and `TT` collapse together there, and if the card's two readings disagree the strand check downstream still refuses to pick one. (2) **`MatchResult.genotype` meant two different things.** For a matched card it held the genotype on the *card's* strand; for everything else, the raw observed value — one field whose meaning depended on a sibling, which is read wrongly the first time a card is rendered. Split into `genotype` (card strand, `None` whenever no strand was established) and `observed_genotype` (as the export wrote it), so a complemented match shows both and the provenance stays traceable. (3) **`complement()` raised a bare `KeyError` on an indel code.** A whitelisted `I`/`D` row reaches the module with genotype `II`, and nothing calls `complement` on one today *only* because of the order of checks in `_evaluate` — a property of current control flow, not a guarantee, and a KeyError two frames up says nothing about indels carrying no sequence. (4) **`yes`/`no` outcome names silently became booleans.** They are the most natural names in the world for a binary trait and unquoted they are YAML 1.1 *booleans* — as are `on`, `off`, `true`, `false`; `null`/`~` become None and a bare number an int. `str()`-coercing both sides "worked": the card rendered with an outcome literally named `False` and nobody would find out. Quote one side and not the other and they stop matching, with an error blaming an outcome the author can see is right there in the file. Refused now, with a message that says to quote it. (5) **`section:` was the only enum field not case-normalised**, so `kind: Interpretation` parsed while `section: Traits` failed — an inconsistency an author discovers one field at a time. (6) **Outcome names colliding after trimming silently dropped one**, a dict comprehension keeping the last, so an entire outcome with its own summary and detail would never render — the same shape as the genotype-mapped-twice check already in the schema, missing on the other side. (7) **`guard_is_active()` was a bool, so a nested `block_network()` cleared it on the inner exit** while the patches were still installed; that function exists precisely so a test can trust the answer, so it is a depth counter now. (8) **The most instructive one, and it was self-inflicted earlier the same session.** `test_pre_commit_hook_exists_and_is_wired` asserted `"tests/privacy" in body`. When the hook was rewritten to select by marker, the only remaining occurrence of that path in the file was inside the explanatory *comment* about why selection is by marker — so the assertion passed while verifying nothing, and deleting the pytest line outright would not have failed it. A test written to check a command survived as a test that checks a comment. The session had already found one mis-wired guard-for-a-guard (the hook skipping 17 privacy tests); this is the same failure introduced by the fix for it, which is worth recording as evidence that the class recurs rather than gets solved. |
| 2026-08-16 | M3.2 | Matcher. 634 tests; ruff, `ruff format` and `mypy --strict` clean. **The design centre is that "no interpretation" is not one answer but seven**, and collapsing them would undo most of what M1 and M3.1 were for. A marker the array never carried, a marker that failed to call, a position where card and array disagree about which variant lives there, an indel excluded by policy, a contradictory call at a single-copy locus, two probes that disagree, and a site whose strand cannot be established — those mean entirely different things to a reader, and only the first is a statement about the chip rather than the person. So `match_pack` returns one result per card, always, and `MatchStatus` is long on purpose. **The strand rule needed the most thought and ended up sharper than the roadmap's phrasing.** The roadblock list says not to trust the vendor's forward-strand claim for A/T and C/G sites, but the untrustworthiness is not uniform: at an A/G site a flip reads C/T, which the card declares nowhere, so the error announces itself as a mismatch; at a self-complementary site a flip is invisible and a homozygote would read as the *opposite* homozygote. Even there it only sometimes matters — a heterozygote at an A/T site is its own complement, and where both readings map to the same outcome the answer is identical either way. So the check complements the genotype and escalates only if that would change which outcome applies. Blunter would either miss real inversions or fire on thousands of harmless sites, and M0.3 already established which of those failure modes actually gets the check bypassed. **The surprise came from working out when `ALLELE_MISMATCH` can fire at all.** A test asserting `CC` against a declared A/G was a mismatch failed, because `comp(C) = G` and the matcher had correctly flipped it. Enumerating the cases showed why: for a biallelic card the declared pair and its complement cover all four bases, so a **homozygote always has some reading available** and can never produce "neither strand fits" — while a heterozygote can, and does, for `A`/`C` against `A`/`G`. That is `ingest/keys.py`'s LocusKey/VariantKey asymmetry surfacing as behaviour rather than as a docstring: a homozygote reveals one allele, and one letter cannot separate "reverse strand" from "a different variant at this position". The flip is still applied — an off-strand marker is ordinary, a mis-placed card is what M3.5's dbSNP cross-check exists to catch — but the homozygous case now carries a caveat saying the inference rests on less evidence and that a reference allele would settle it, and a test asserts the two caveats differ. Writing one caveat for both would have been recording the distinction nowhere, which is the same as not having made it. **M1's deferred decision came due**: 656 positions in the real export carry more than one row, and M1 said explicitly that choosing between duplicate probes is a matching decision. The rule is agreement, never preference — agreeing probes give one answer with a note, disagreeing probes give `DUPLICATE_CONFLICT`, because picking the first row or the "better" one manufactures an answer the data does not contain. A no-call beside a call is not a disagreement; an uncalled probe has no genotype to conflict with. M1.6's request was honoured literally: the matcher calls `matchable_mask` rather than filtering indels itself, and a test with a populated whitelist proves the policy is *read* rather than the default hard-coded — without it, the exclusion test would pass against a matcher that refused every I/D row forever and the whitelist M1.6 built would be unreachable. Smaller things: computed caveats are kept separate from the card's authored ones, since one is a fact about this sample and the other about the literature, and merging them would leave a rendered card unable to say which is which; the locus index covers only the loci the pack asks about, because indexing 677k rows to answer a hundred questions is a great deal of memory for nothing; and a privacy test asserts no generated reason or caveat is export-row-shaped, since these strings reach both the CLI and the run bundle. The suite is structurally non-vacuous by construction — every rule is tested as a *pair* (probes agree/disagree, ambiguity escalates/does not, indel excluded/whitelisted), so a condition stuck on one answer fails one half. Finally, one test runs the whole path through real ingest rather than hand-built frames, because every other test in the file assembles the normalized table by hand and could drift from what the adapters actually produce. |
| 2026-08-16 | M0.4 fix | **Found while committing M3.1, and the finding is worse than the milestone it interrupted.** The new card-file privacy test was written, marked `privacy`, and placed beside the card tests — and the pre-commit hook's output showed the same 122 privacy tests as before. The hook ran `pytest tests/privacy`, selecting by **directory**, so it had never run any privacy-marked test living beside the code it guards. Seventeen of them: M1.8's `test_the_json_guard_actually_fires` and `test_the_human_render_path_is_guarded_too`, M1.4's two "an error message must not echo a data row" tests, `NoGenotypeRepr`'s two, the QC report scan, the CLI output scans across four fixtures, and the fixture-purity checks. **The sharpest part is which tests these were.** The M1 review's headline finding was that `_render` bypassed the genotype guard its own docstring claimed covered it; the test written to close that hole was itself not running at commit time. The guard for the guard was mis-wired, and the symptom was a test count nobody was watching. The marker had drifted in the other direction too: `tests/privacy/test_leak_detection.py` sat in the directory carrying no marker, so directory selection ran 122 and marker selection ran 96 — **neither selector was the whole suite**. Fixed by making the marker authoritative: the module is marked, the hook now runs `pytest -m privacy` (142 tests, a strict superset of the 125 the directory holds), and `tests/privacy/test_suite_selection.py` asserts every module in the directory carries the marker *and* reads `.githooks/pre-commit` to assert it still selects by marker — because the hook is a shell script no test would otherwise touch, and reverting it would be silent. Same shape as M1.3's structural import test: a convention nobody checks is a convention that has already drifted. The general lesson is narrower than "check your selectors" — it is that **two ways of naming the same set will diverge, and the one the automation uses is the one that matters**. The privacy marker's own docstring says these checks must never be skipped, and for seventeen of them the hook had been skipping exactly that. |
| 2026-08-16 | M3.1 | Card schema. 588 tests; ruff, `ruff format` and `mypy --strict` clean. **The schema's job turned out to be refusing things, so the design work was in choosing what to refuse.** A permissive schema would pass a "does a valid card parse?" suite completely, which is why the tests are organised one-per-rule rather than by module. **The central refusal is that a card cannot author its own confidence.** AGENTS.md §6 says confidence is computed; the schema has to make that unavailable rather than merely unfashionable, because `confidence: high` in a YAML file would work, would be easier than getting the evidence right, and would silently override the rarity inversion §4.1 calls the most important thing the interface communicates. `confidence`, `tier`, `score` and `reliability` are refused at card level with an error naming M3.3. The knock-on decision matters as much: `evidence.tier` is an authored *input* and M3.3's tier is a computed *output*, so they were given **disjoint vocabularies** — a test asserts no value appears in both. Two ladders sharing a name get conflated in a week, and the conflation would read exactly like a card setting its own confidence. **The second refusal is exhaustiveness**: every genotype the declared alleles can produce needs an outcome. `ingest/keys.py` had already written down why — "no result" is indistinguishable from "no variant" — and a card mapping only `AA` and `GG` renders nothing at all for a heterozygote. An author with nothing to say about hets has to say so in an outcome, where a reader sees it. This turned out to be **decidable at load with no reference data and no QC result**, which was not obvious: M1.1 writes a haploid call *doubled* and keeps ploidy in `call_status`, so there is one genotype vocabulary rather than one per chromosome, and a card does not need to know the sample's sex to be complete. **Third, citations are structured rather than prose.** "A card without a citation does not render" is satisfied by `see Smith et al.`, which is precisely the fabrication the rule exists to stop — unresolvable, so nobody checks it. Type plus identifier plus a format check makes "this card is cited" mechanically verifiable; `title` is required beside the identifier because a title that does not match its DOI is the most visible sign of a fabricated reference in a diff, which is what M15.6 audits. Calibration point in the same place, from M0.3's "a scanner that cries wolf gets bypassed": a DOI pasted as `https://doi.org/10.1038/...` is **stripped, not rejected**, because telling an author their working DOI is malformed makes them edit until the message stops, and that is how a good citation becomes a wrong one. Impossibility cards are exempt from the citation requirement, deliberately — their claim is about the assay rather than the person, and demanding a DOI for "an array does not measure methylation" pushes toward citing something tangentially related, which serves a reader worse than citing nothing. **`knowledge/` ships empty and a test asserts it.** Requiring both an rsID and coordinates (so M3.5 can cross-check them against dbSNP — either alone is unverifiable) means a card cannot be written until its coordinates come from a real source, and writing GRCh37 positions from memory is the §6 failure. Same precedent as `build_anchors` and `spike_ins`; the test exists so whoever adds the first card meets the reasoning rather than an empty directory of unclear intent. Multi-variant cards and indel alleles are refused for the same class of reason — a genotype cross-product is not haplotype calling (M10 needs phase), and an `I`/`D` allele has no sequence so a wrong guess reports the opposite genotype rather than failing. Both keep their field shape and refuse the data, which is M2.1's declared-but-not-implemented pattern. **One thing worth checking rather than assuming, and it could have forced a redesign:** cards are committed, and a card names an rsID, a chromosome, a position and several genotypes — the shape of an export row. Had the natural YAML layout tripped the privacy scanner, every card commit would have been blocked and the fix people reach for is `--no-verify`, which M0.4 says is never acceptable. It does not trip it; that is now a permanent privacy test rather than a lucky property. The self-pass found one fail-open: a card file saved `.yml` fell outside the loader's glob and its cards vanished silently — a missing card being indistinguishable from an unmatched one is the precise confusion this schema is built against. Refused loudly rather than widening the glob, which would have blurred both the duplicate-id check and M3.5's lint target. Neutering the confidence refusal fails all four of its test cases, so that guard is demonstrated rather than asserted. One roadmap divergence: `summary_template`/`detail_template` moved **per outcome**, since the interpretation is exactly what differs between genotypes. |
| 2026-08-16 | M2.7 | Offline guard, in-process half. 454 tests; ruff, `ruff format` and `mypy --strict` clean. **The milestone was split rather than done or deferred, and the split is the decision worth recording.** M2.7 as written — "with networking disabled, a full run succeeds" — cannot be true before M4.1 defines a run, so doing it now meant either testing a fiction or checking a box against a narrower test than its words describe. That is the failure the whole M2 review was about. But deferring it whole would have been wrong in the other direction: the property is cheap to *keep* and expensive to *recover*. Right now exactly one module in `src/` opens a socket and **no test touches the network at all**, so the guard cost 20 lines of conftest and broke nothing; after M9 it would mean auditing a dozen modules and arguing about a PGS fetch someone had already built on. So the in-process guard ships now as M2.7 and the OS-level run moves to M4.10, where a full run first exists. **Two design points.** (1) **Loopback is allowed deliberately.** M4.3 binds FastAPI to localhost and M13.5 drives it; a guard that broke the local server would be switched off wholesale by whoever hit it first, which is M0.3's "a scanner that cries wolf gets bypassed" applied to this guard rather than to the leak scanner. Same reasoning put DNS inside the block: resolution is itself traffic, it is the step that discloses what is being fetched, and it is the point where the hostname is still in hand — by `connect` time the message can only name an anonymous IP. (2) **`NetworkAccessError` derives from `RuntimeError`, not `OSError`.** `urllib` catches `OSError` around its transport and re-raises it as `URLError`, so as an `OSError` the refusal would arrive wrapped and worded as a connection failure — indistinguishable from the genuine offline case that fetch code is written to retry or report calmly. A rule violation that disguises itself as the condition the code already handles is worse than no rule. **Demonstrated rather than assumed**, per M0: with `block_network` stubbed to a no-op, all six guard-asserting tests fail, and the run goes from 0.17s to 23s — the extra 23 seconds *are* real DNS timeouts against ncbi and ebi plus a real TCP attempt, which is the most direct evidence available that the suite would otherwise reach out. The tests drive `UrllibTransport` itself rather than a bare socket, since no shipped code looks like a bare socket. One vacuity hole was closed on the self-pass: `guard_is_active()` alone would be satisfied by a bookkeeping flag set beside a `block_network` that patched nothing — the same one-possible-answer shape as M0.6's HIBAG probe — so the tests also compare `socket.getaddrinfo` against the saved original. Finally, restore is by `__dict__` check and `delattr`: `connect` is *inherited* from `_socket.socket`, so writing the original back onto `socket.socket` would leave a permanent override that looks identical from outside and survives every later teardown. **The honest gap, written down rather than papered over:** this cannot see a subprocess. PLINK 2, Beagle, Java and R get their own address spaces. That is exactly what M4.10 is for, and why it is an open box and not a formality. |
| 2026-08-15 | M2 review | Diff-driven review of the whole M2 session (`/code-review high`) plus a self-pass, same practice as M0 and M1. **11 findings, all fixed, the serious ones reproduced before fixing; 430 tests.** The pattern this time was not fail-open guards but **claims the code did not honour** — three separate places asserted a property in a docstring or a message that the implementation did not actually provide. (1) **The lock failed open after a single detected corruption.** Recording only the current run's successes *replaced* the file map, so the digest of the file that just failed was dropped; with nothing left to compare against, the next run reported it already-present and wrote the corrupt content in as truth. Reproduced end to end: one bad file laundered itself into the record in three runs. The lock now merges over what was there, so a failure can never erase the evidence of what the file should be. (2) **A satisfied tier B source vanished from the lock** — the write was conditional on having files or not being complete, which is exactly a manual source once the human has done the step. OMIM and SNPedia, the two most encumbered entries in the manifest, dropped out of the audit record at the precise moment their data was present. (3) **`refs verify` was gated on the licence**, so after `--opt-in pharmgkb` the integrity check it existed to provide answered "blocked-by-licence" and never looked at the files; a full verify could never exit 0, making the exit code useless as a health signal. The gate governs *acquiring* data, not inspecting what is already on disk. (4) **A `.part` that was already complete wedged permanently**: the guard used `>` rather than `>=`, so a process killed during the minutes-long hash of a 63 GB file left a full-length part, the next run asked for `Range: bytes=<size>-`, got a 416, and reported "could not open" forever — while the neighbouring message advised rerunning to resume. (5) **A 206 with an unreadable `Content-Range` was treated as a fresh 200**, truncating the head of the file; the module docstring claims `resumed_from` makes exactly that unrepresentable, and it did not, because the parser returned `0` for "could not tell". It now returns `None` and the caller refuses to guess. (6) **Three post-processing steps were marked `implemented=True` with no executor anywhere** — nothing reads `Source.post_process` except validation and the pending-work report, so those three were the only steps *not* listed as outstanding: `refs fetch --only phylotree_17` downloaded a zip, never unpacked it, and reported complete with no work left. A claim of implementation that no code backs is worse than an honest gap, because the gap at least shows up in the report. All are `implemented=False` until a runner exists. **The self-pass found two more of the same shape.** An already-installed *jar* was never re-checked against its sha256 — and `data/tools.yaml` says of Beagle that "the sha256 is what establishes identity here", which was true only at download time; a truncated jar read as present forever and reinstalling would not repair it. Non-archive builds are now re-verified (for an archive build the installed file is an extracted member whose digest is not the archive's, so identity rests on the mandatory version probe instead). And **`doctor` could not find what the installer had just placed**: `_which` scanned the tools directory one level deep while M2.5 installs two levels down, so `genetics doctor` reported PLINK 2 missing immediately after `genetics tools install` reported success — two modules written from the same mental model and never connected, with a stale message pointing at `genetics refs fetch`, a command that does not install tools. `doctor` now reads the record the installer writes. Four smaller ones: the containment checks admitted the directory itself (`filename: "."`); `installed_path` took a member's basename while `extract_member` wrote its full relative path, so any future build with a nested member would install and then report missing forever; the digest-mismatch message claimed a discard that only happens on one of its three call sites; and `verify` reported "no digest to check against" for all 24 md5-pinned gnomAD files whose md5 it had just checked. |
| 2026-08-15 | M2.5, M2.6 | Tool acquisition and the `refs`/`tools` CLI. 420 tests; ruff, `ruff format` and `mypy --strict` clean. **The design point worth keeping is that a checksum answers the wrong question for a pinned tool.** AGENTS.md §4.9 asks for the exact PLINK 2 build to be pinned because alpha behaviour moves, but sha256 only proves the download was intact — an intact download of a *different* alpha verifies perfectly and then silently changes results. So an executable must also declare a `version_check` that runs the binary and confirms what it reports, and the schema refuses to load one without it. That turned up the roadmap's pin being stale in two ways at once: alpha5 is no longer linked from the download page, and PLINK has changed its version string format, so the literal instruction (`2.00a5.x`) would now pin an undocumented build *and* fail to match any modern version string. Pinned to alpha7 `20260808`; the expected string `v2.0.0-a.7.3` was read off the binary by running it. **A second modelling distinction fell out of the licence table**: PLINK 2 and Beagle are GPLv3, and the table correctly classifies copyleft as restricted, which would have forced an opt-in for a tool required from M5. The gate asks a *data* question — would folding this into the corpus impose its licence on our output? — and the answer differs for a binary we neither link against nor redistribute but merely execute. The truth stays in the table and the exemption lives in the installer, each documented where the decision is made, rather than quietly weakening the classification. Smaller things worth recording: the M2.2 downloader was refactored to a shared `download()` before tools reused it, because a second copy of the resume logic is how three corruption fixes end up in one copy and not the other; extraction refuses zip-slip members, absolute paths and tar links, and sets the execute bit on POSIX, since a zip built for Windows carries no mode and **M0.4 was already bitten by exactly that** with the pre-commit hook; only baseline builds are pinned, not the AVX2 ones, because an AVX2 binary on a CPU without it dies with an illegal instruction partway through a long run instead of failing clearly at install. `mypy --strict` also flagged something real: `sys.platform` comparisons get narrowed to the host, so the macOS and Linux branches of the platform mapping were reported unreachable on Windows and would have gone type-unchecked on every platform but one — switched to `platform.system()`, which is the reason CI runs two operating systems in the first place. Both tools were installed for real to verify the whole path end to end, including that PLINK reports the pinned version and the archive is cleaned up afterwards. One transient DNS failure on the Beagle host was worth seeing: it surfaced as a clear `FAILED` with the reason rather than a traceback, and a rerun succeeded — there is deliberately no automatic retry, since resumability is the retry story. **Finally, building the CLI immediately exposed a bug in M2.2 that no unit test had**: `refs verify` rewrote `manifest.lock`, so merely running the CLI test suite created a lock at the committed path describing sources with empty file lists — a lock asserting facts about downloads that had never happened, which is the one thing that file must never contain. Caught by `git status`, not by a test, which is its own lesson. Verification now writes nothing at all, not even the references directory: a check that rewrites its own reference answers "does this still match?" with "yes" by construction. |
| 2026-08-15 | M2.1–M2.4 | Manifest schema, licence gate, fetcher, lock, and 17 sources. 380 tests; ruff, `ruff format` and `mypy --strict` clean. **The governing decision was to verify every URL, size and digest against the live server rather than write any of it from memory** — the same rule `qc/build_anchors.py` and the `spike_ins` hook were left empty for, applied to a file whose entire purpose is pinning. That produced five findings that memory would have gotten wrong. (1) **gnomAD v4 is GRCh38-only**, and this pipeline is GRCh37 end to end, so the usable release is v2.1.1 — AGENTS.md §5.1 cited v4's variant counts for a build we cannot use. (2) Its real size is **63 GB for exomes and 495 GB for genomes**, so M2.3's "subset to array positions to keep it manageable" was addressing storage, not the download; split into a required exomes entry (which is what the §4.1 gate actually needs, since ClinVar's pathogenic assertions are overwhelmingly coding) and an optional genomes entry. (3) **PharmGKB now serves under ClinPGx** and `api.pharmgkb.org` no longer resolves. (4) **FinnGen R12 summary statistics need no web form** — manifest and a 755 MB endpoint file both fetched anonymously off public GCS, so AGENTS.md §5.2 was wrong and is corrected. (5) **§4.8 trap 1 is real but mislocated**: the authoritative per-score licence is the `License/Terms of Use` column of `pgs_all_metadata_scores.csv`, not the scoring file header (PGS000001's has none), and it holds ten distinct values — mostly the EBI default, but CC BY-NC-**ND** for a few dozen, where NoDerivatives bites harder than NonCommercial because computing a score from the weights is plausibly a derivative. Two pieces of luck worth writing down: NCBI ships `.md5` sidecars and **GCS returns a base64 md5 in `x-goog-hash`**, so all 558 GB of gnomAD is checksum-pinned without a byte downloaded. **The design lesson carried from M0/M1 was fail-closed, and it landed on licensing**: a manifest that could declare its own `permissive: true` would put the gate under the control of the person motivated to get past it, so a source names a licence id and the properties are looked up — an unknown id refuses to load rather than defaulting to permissive. The inverse error was also avoided: refusing the PGS Catalog because 31 of 6,970 scores are non-commercial would train people to pass a blanket opt-in, and a gate that is always bypassed protects nothing, so per-record licences warn and only genuinely restrictive ones block. **The most instructive implementation finding was in resume**: a server may answer `Range` with `200` and the whole body, and appending that to a partial file duplicates the prefix — silently, for any file without a published checksum. Fixed structurally rather than defensively, by having the transport report the offset the server *actually* used instead of the one requested; the same code path also had to take the total from `Content-Range`, since `Content-Length` on a `206` is only the remaining bytes. Both are covered by tests, and both were then confirmed against a real server. A third case in the same family was found while reviewing that code and is the sharpest of the three: a server that resumes *past* the requested offset would have had the partial file truncated up to meet it, zero-extending it and appending beyond a run of NULs. Reproduced before fixing, and the striking part is that **the corrupted file came out at exactly the right byte count** — a length check passes it, only the digest catches it, and an unpinned file has no digest. No compliant server does this, which is precisely why it was worth handling: the failure would be rare, silent and permanent. One calibration fix on review: the licence-review warning originally fired once per source, which would have put ten near-identical lines in front of someone watching a download — M0.3's "a check that cries wolf gets bypassed" applies to warnings too, so it aggregates into one line. Three sources are **honestly demoted to tier B** rather than given invented URLs: HGDP (the 1000G collection is GRCh38 sequence, not the GRCh37 genotype panel), SGDP (several releases, one named `knownbugs.not_recommended` — choosing is an M5.3 decision), and AADR (Harvard Dataverse returns a bare 202 to every API request). `manifest.lock` is deliberately **not committed** until the owner runs a real fetch: it records what a machine received, and committing one from an authoring session would assert facts about a download that never happened here. |
| 2026-08-15 | M1 review | Diff-driven review (`/code-review high`) plus a self-pass, same as M0. 11 findings, all fixed, all reproduced before fixing; 301 tests. The self-pass and the agent independently found the same two, which is the useful signal here — both were **fail-open guards**, the identical class as M0's. (1) `_first_bad` filled the rsID column with a placeholder *before* evaluating a predicate that tests `rsid.is_null()`, so the empty-field check could never see a missing identifier and a row with no rsID reached the normalized table. Fill after the filter, not before. (2) `_load_builtin_adapters` set its "loaded" flag before importing, so a broken adapter failed once with a real ImportError and then reported "does not match any known vendor layout" forever after — sending the reader after a missing adapter instead of the import that failed. **The single most instructive finding was in `doctor`:** the HIBAG probe `if (!requireNamespace("HIBAG")) quit(status=1)` prints *nothing* on success, and `_run_version` treats empty output as an error — so the success path was unreachable and every machine on earth reported "R is installed but HIBAG is not", including machines with HIBAG. A check that can only ever return one answer is not a check. It now prints on success. Also: `lookup_loci` consumed its `Iterable` argument twice, so any generator silently produced an empty column and a `ShapeError` naming nothing relevant; `_render` bypassed the genotype guard the module docstring claimed covered the command, leaving the *more* likely edit site ("just show me a few rows") unguarded — both output paths are scanned now; the 23andMe bad-genotype error raised `MalformedHeaderError` for a data row and printed a 0-based body index as a "line"; Beagle jar selection sorted by filename, but Beagle names jars by date (`05May22` sorts before `28jun21`), so the *older* of two installs won. Two design cleanups worth recording: `IngestResult.qc` was typed `object` to dodge an import cycle, which pushed an `assert isinstance` onto every caller — `TYPE_CHECKING` gives the real type for free. And the "no markers at all on X" warning fired on every 23andMe run for PAR, which that layout simply does not label; adapters now declare `representable_chroms` on `SourceInfo`, so QC can tell *structurally absent* from *actually missing* without importing a vendor module. That is the same distinction `infer_sex` already made for a layout with no Y markers, and it should have been made in both places at once. |
| 2026-08-15 | M0.6, M1 | Ingest and QC complete. 288 tests; ruff, `ruff format` and `mypy --strict` clean. **M1.2's local acceptance passed on the real export** — 677,436 / 550 / 8,830 — and reconciling it against AGENTS.md §2 resolved an apparent 3-marker discrepancy on the Y: §2's "1,658 calls" counts *homozygous* calls, and 1,661 called − 3 het = 1,658. X matches exactly the same way (25,231 − 4 = 25,227). Two genuine findings in that file worth carrying to M3: **656 rows repeat a (chrom, position)** already present, and 7 heterozygous calls sit at loci inferred single-copy. Both are reported, neither is deduplicated or dropped — choosing between duplicate probes is a matching decision (M3.2), not an ingest one. **The M0 lesson recurred twice, in a new form each time.** (1) Writing the first genotype-bearing dataframe exposed a hole in the privacy scanner: `polars` renders a row with `U+2506` between cells, so `repr(frame)` printed rsIDs and genotypes in plain sight and matched none of the whitespace-separated patterns — it would have passed `assert_no_genotype` *and* the pre-commit content scan. Fixed by adding a vertical-rule separator form, which also closes the likelier route: a genotype row in a **markdown table** was equally invisible. Four negative controls guard against the scanner now flagging ordinary tables. (2) Null is Polars' fail-open value: `null.is_in([...])` is null, not False, and a null predicate matches nothing. That silently dropped **every no-call** from the indel-policy matchable set — the indel policy was quietly deciding what happens to missing genotypes, which is the card engine's call. Same trap found and closed in `_is_snp` and in row validation, where a blank field would have skipped the allele check unreported. The pattern to carry forward: in Polars, three-valued logic turns a guard into a no-op exactly on the rows that are already anomalous. Also worth noting: the build-anchor table and the dbSNP merge table both ship as tested mechanisms with empty data, following M0.2's `spike_ins` precedent — inventing GRCh37 coordinates to make a check look complete would be the exact failure the check exists to catch. |
| 2026-08-15 | M0 review | Diff-driven review of the session (`/code-review high`) plus a self-pass. 15 findings, 8 reproduced empirically; all fixed. 116 tests. **The pattern across them: the guards failed *open*.** Several were cases where a privacy check silently passed on input it was written to catch — worse than no check, because it manufactures confidence. Worth remembering: (1) the fixture allowlist was an fnmatch glob, and fnmatch's `*` crosses `/`, so `synthetic/<any>/<real export>` was exempt from the name rule *and* the content scan *and* `.gitignore`'s `**` negation *and* the sealing test's non-recursive `iterdir()` — four layers with one blind spot, because all four were written from the same mental model. (2) The scanner matched only *real* tab separators, so a row inside a Python string literal or any `repr()`/traceback — the module docstring's own stated threats — sailed through; the redaction test passed vacuously for the same reason and would have passed with the redaction deleted. (3) `NoGenotypeRepr` was silently voided by `@dataclass`, which generates `__repr__` on the subclass; fixed by claiming the slot in `__init_subclass__`, since `dataclasses` never overwrites a name already in `cls.__dict__`. (4) The hook was committed mode 100644, so git skipped it on Linux/macOS while `install-hooks` reported success. (5) `verify_all` compared via `read_text()`, whose universal-newline mode folds CRLF, so the check `.gitattributes` exists to protect could never fail. (6) `staged_files` lacked `-z`, so a non-ASCII path was quoted, `git show` failed, the error was swallowed, and the file was skipped unscanned. Also fixed my own `GENETICS_DATA_DIR` hole: pointing it inside the checkout relocated run bundles into the repo, where gitignore covers them only unevenly. Lesson for M1: a guard that has not been *demonstrated* failing on real input is not evidence of anything. |
| 2026-08-15 | — | Roadmap created. AGENTS.md and .gitignore in place; no code yet. |
| 2026-08-15 | M0.3–M0.5 | Privacy suite, pre-commit hook, CI. 90 tests total. **The suite caught a real cross-platform bug on its first run:** the fixture named `other_vendor_23andme.txt` matched the forbidden pattern `*23andMe*.txt`, and because `fnmatch` normcases via the OS, that check folded case on Windows but not on Linux — it would have passed CI on ubuntu and blocked on windows. Fixed three ways: matching is now explicitly case-insensitive everywhere, the fixture was renamed to `other_vendor_layout.txt` (a fixture that trips the guard teaches people to ignore the guard), and allowlisted paths are exempt from name rules. That exemption made `tests/fixtures/synthetic/` a trust hole, so it is now sealed by `test_synthetic_dir_holds_only_known_fixtures`. Also: writing genotype rows as literals in test files would fail our own content scan, so tests assemble rows at runtime from parts — and the AGENTS.md format block now spells out `<TAB>` instead of using real tabs, which is better documentation anyway. |
| 2026-08-15 | M0.1, M0.2 | Scaffold + fixture generator done. 24 tests, ruff and `mypy --strict` clean. Six fixtures at ~330KB each (12k markers). Two findings worth carrying forward: (1) `.gitattributes` with `eol=lf` turned out to be a correctness requirement, not tidiness — without it git rewrites fixtures to CRLF on Windows checkout and byte-identity fails; (2) M1.2's "parses the real file" criterion cannot be a CI test, so it is now split into a CI half (fixtures) and a manual local half. |
