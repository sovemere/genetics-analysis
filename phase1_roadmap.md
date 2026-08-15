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
| Genomics workhorse | **PLINK 2** (pin `2.00a5.x`) | Native Windows binary; covers conversion, LD prune, PCA projection, `--score`, `--homozyg`, freq, sex check |
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
├── data/references/     manifest.yaml COMMITTED, payloads gitignored
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
- [x] **M0.3** Privacy test suite (`tests/privacy/`, 46 tests). Two enabling modules:
      `genetics.privacy` (leak detection, redaction, `NoGenotypeRepr`) and
      `genetics.paths` (canonical write locations + `APP_WRITE_PATHS` registry).
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
      - **Verified adversarially, not assumed:** staged a markdown file containing a
        genotype row and confirmed the commit was blocked and HEAD unchanged.
      - Hook documents that `--no-verify` is not acceptable, and why: a genotype pushed
        to a public repo cannot be recalled — history rewriting does not reach forks,
        clones, or mirrors.
- [x] **M0.5** CI (`.github/workflows/ci.yml`): 2 OS × 2 Python matrix
      (windows/ubuntu × 3.11/3.13) running ruff, `mypy --strict`, the privacy suite,
      the full suite, and a fixture-reproducibility check.
      - Second job `no-data-in-ci` asserts the checkout holds no raw export, no
        genotype-derived artifact, and no reference payload beside the manifest.
      - The matrix is not ceremony: the htslib constraint (§4.9) means a dependency can
        pass on Linux and fail on Windows, and M0.3 already caught one such bug
        (see progress log).
- [ ] **M0.6** `genetics doctor` command: reports Python version, OS, presence and
      versions of PLINK2 / Java / Beagle / R+HIBAG, reference manifest state, and free
      disk. This is the first thing to run when an agent picks up the project.

---

## M1 — Ingest & QC

- [ ] **M1.1** Normalized table schema (Polars), exactly as
      [AGENTS.md §2](AGENTS.md): `rsid, chrom, pos_grch37, a1, a2, genotype, call_status`.
      `chrom` is an enum `1..22, X, Y, PAR, MT` — **never** the numeric vendor codes.
- [ ] **M1.2** AncestryDNA V2 adapter. Handle every measured fact: 17-line `#` header,
      chrom codes `23→X 24→Y 25→PAR 26→MT`, `0 0` no-calls, `I`/`D` indels, unordered
      allele pairs (sort them), doubled hemizygous calls.
      - *Acceptance (CI):* parses all six synthetic fixtures; rejects the malformed-header
        and wrong-build ones with actionable errors.
      - *Acceptance (local only):* parses the owner's real export to exactly 677,436 rows
        with 550 no-calls and 8,830 indel markers. **This check cannot live in CI** — the
        file can never be committed. Implement it as `genetics ingest --expect-counts`,
        run manually, asserting counts without emitting any genotype.
- [ ] **M1.3** Vendor sniffing + adapter registry. Adding a vendor must not touch any
      analysis module. Ship a stub 23andMe adapter to prove the seam.
- [ ] **M1.4** Strict validation: assert build 37, assert column count, assert header
      shape, reject with an actionable error on mismatch. **Fail loudly**
      ([AGENTS.md §6](AGENTS.md)) — a mis-parse becomes a confident wrong health claim.
- [ ] **M1.5** QC module:
      - call rate (overall and per chromosome)
      - autosomal heterozygosity rate
      - **sex inference** from X het rate + Y call rate → drives hemizygous handling
      - build sanity check against known reference positions
      - QC report object, surfaced in the UI and CLI
- [ ] **M1.6** Indel policy: exclude `I`/`D` from allele matching by default
      ([AGENTS.md §4.2](AGENTS.md)); support an explicit whitelist with verified rsID→
      representation mapping.
- [ ] **M1.7** Variant keying: primary key `(chrom, pos_grch37, alleles)`, rsID secondary,
      plus a dbSNP merge table so retired rsIDs still resolve
      ([AGENTS.md §2](AGENTS.md)).
- [ ] **M1.8** CLI `genetics ingest --input <file> [--json]`.

---

## M2 — Reference fetcher

- [ ] **M2.1** `manifest.yaml` schema: per source — id, URL, version, checksum, license
      SPDX/text, size estimate, tier (A/B/C per [AGENTS.md §5](AGENTS.md)), required-vs-
      optional, post-download processing step.
- [ ] **M2.2** Fetcher with resumable downloads, checksum verification, progress
      reporting, and a written `manifest.lock` recording resolved licenses.
      - **Refuse or loudly flag non-permissive sources.** SNPedia and any non-commercial
        PGS score must be opt-in and labelled.
- [ ] **M2.3** Tier A sources, in dependency order:
      - [ ] gnomAD allele frequencies — **load-bearing**, the frequency gate in
            [AGENTS.md §4.1](AGENTS.md) cannot be computed without it. Subset to array
            positions + card positions to keep it manageable.
      - [ ] ClinVar (VCF + variant summary)
      - [ ] 1000 Genomes phase 3 GRCh37 (PCA subset **and** full panel for imputation —
            do not subset the imputation panel, [AGENTS.md §5.5](AGENTS.md))
      - [ ] HGDP + SGDP
      - [ ] GWAS Catalog associations
      - [ ] PGS Catalog scoring files — **parse the per-score license header**
      - [ ] PharmGKB + CPIC
      - [ ] AADR
      - [ ] PhyloTree 17 (mtDNA)
      - [ ] Pan-UKBB (selected traits)
- [ ] **M2.4** Tier B optional sources with one-time human step: FinnGen (web form),
      OMIM (user-supplied API key, never cached long-term, never vendored).
- [ ] **M2.5** Tool acquisition: PLINK 2 (pinned build), Beagle jar, optional R+HIBAG
      detection. Verify checksums. Install under a user-data dir, not the repo.
- [ ] **M2.6** `genetics refs fetch|status|verify|licenses` CLI.
- [ ] **M2.7** Offline guarantee test: with networking disabled, a full run succeeds
      once references are present.

---

## M3 — Card engine & knowledge pack

*This is the heart of the product. Get the schema right before writing many cards.*

- [ ] **M3.1** Card schema (YAML), versioned. Fields:
      - `id`, `section`, `title`, `summary_template`, `detail_template`
      - `match`: variant keys + genotype→outcome mapping
      - `evidence`: tier, effect size + units, sample size, study population ancestry,
        replication status, within-family attenuation where known
      - `citations`: DOI / PMID / accession — **required, a card without one cannot ship**
      - `caveats`, `impossibility_reason` (for §3.2 cards)
- [ ] **M3.2** Matcher: resolves card variant keys against the normalized table. Handles
      unordered genotypes, hemizygous calls, no-calls, missing markers, strand checks
      against the reference allele (do not trust the vendor's forward-strand claim
      blindly for A/T and C/G sites).
- [ ] **M3.3** **Confidence calculator** — computed, never authored
      ([AGENTS.md §6](AGENTS.md)). Inputs: evidence tier, effect size, replication,
      **population allele frequency (inverted — rarity lowers confidence)**, imputation
      quality where applicable, ancestry match to the source study.
      Output: a tier from `well-established` → `likely-artifact`, plus the numeric inputs
      for display.
      - *Acceptance:* a rare ClinVar pathogenic hit scores `likely-artifact` and carries
        the empirical PPV for its frequency band; a common large-effect trait variant
        (e.g. HERC2 eye colour) scores `well-established`.
- [ ] **M3.4** Evidence assembly: bundle genotype + card + frequency + citations into a
      renderable result object. Never drop a card for low confidence
      ([AGENTS.md §0.1A](AGENTS.md)).
- [ ] **M3.5** Card linting: `genetics cards lint` verifies schema, citation presence,
      resolvable variant keys, and template rendering. Wire into CI.
- [ ] **M3.6** **Seed pack: Traits, morphology & sensory** (~25–40 cards). Highest
      confidence content and the best demo: HERC2/OCA2 eye colour, ABCC11 earwax + body
      odour, TAS2R38 bitter taste, MCM6 lactase persistence, ALDH2 flush, asparagus
      anosmia, cilantro aversion, photic sneeze, hair texture/colour, freckling, male
      pattern baldness, morning/evening preference.
- [ ] **M3.7** Impossibility cards for [AGENTS.md §3.2](AGENTS.md): methylation/epigenetic
      age, somatic/tumour, CNVs (SMN1, RHD, alpha-thal, CYP2D6 hybrids), Y-STRs, mtDNA
      heteroplasmy, de novo mutations, telomere length, relative matching.

---

## M4 — Run bundle & first UI

*End of the vertical slice: after this milestone there is a working app, with one
section, that proves every layer.*

- [ ] **M4.1** Run bundle format (directory or single file). Immutable. Records: engine
      version, knowledge-pack version, every reference version, tool versions, QC report,
      all scored cards, timestamps. **Gitignored; written outside the repo by default.**
- [ ] **M4.2** Save / load / list / delete runs. Bundles must be re-readable months later
      with a different code version, or fail with a clear version error.
- [ ] **M4.3** FastAPI app skeleton, binds localhost only, no external requests.
- [ ] **M4.4** Vendor htmx + Alpine.js into `web/static/`. Add a test asserting no
      external URL appears in any template or static asset.
- [ ] **M4.5** Dashboard shell: section nav, run selector, QC banner.
- [ ] **M4.6** Card grid + detail modal. **Confidence tier is visible on the card face**,
      not only in the modal ([AGENTS.md §0.1A](AGENTS.md)). Modal shows effect size, base
      rate, source population, caveats, and clickable citations.
- [ ] **M4.7** Sort/filter/group by confidence tier and section. **Filtering must never be
      the only way to see a card** — no default filter hides low-confidence results.
- [ ] **M4.8** Light/dark theming, responsive layout.
- [ ] **M4.9** `genetics serve` command.

> **Slice checkpoint:** ingest a synthetic fixture → traits cards → browse in the UI →
> save → reload. If this works, the architecture is proven. Do not proceed until it does.

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

- [ ] **M13.1** `genetics list-runs`, `show <run> [--section S]`,
      `card <run> <card-id> --json`, `evidence <card-id>`, `qc <run>`, `refs licenses`.
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
      peak memory in the progress log.
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
| PGS per-score licences ignored | M9.1 | Parse header per score, not per catalogue | [§4.8](AGENTS.md) |
| Imputation run un-resumable, blocking progress | M8.1 | Resumability is an acceptance criterion | [§0.1C](AGENTS.md) |
| CLI/UI parity rots | M13.5 | Parity test in CI | [§3](AGENTS.md) |
| Reduced-N sumstats silently weaken psychometrics | M9.8–9.9 | Record release version on the card | [§5.3](AGENTS.md) |
| Carrier section implies false completeness | M11.6 | Explicit incompleteness card | [§3.2](AGENTS.md) |
| PLINK 2 alpha build changes behaviour | M2.5 | Pin exact build in manifest | [§4.9](AGENTS.md) |

---

## Progress log

Append dated entries as milestones complete. Record surprises, parameter choices that
needed tuning, and anything that contradicts AGENTS.md (then fix AGENTS.md).

| Date | Milestone | Notes |
|---|---|---|
| 2026-08-15 | M0 review | Diff-driven review of the session (`/code-review high`) plus a self-pass. 15 findings, 8 reproduced empirically; all fixed. 116 tests. **The pattern across them: the guards failed *open*.** Several were cases where a privacy check silently passed on input it was written to catch — worse than no check, because it manufactures confidence. Worth remembering: (1) the fixture allowlist was an fnmatch glob, and fnmatch's `*` crosses `/`, so `synthetic/<any>/<real export>` was exempt from the name rule *and* the content scan *and* `.gitignore`'s `**` negation *and* the sealing test's non-recursive `iterdir()` — four layers with one blind spot, because all four were written from the same mental model. (2) The scanner matched only *real* tab separators, so a row inside a Python string literal or any `repr()`/traceback — the module docstring's own stated threats — sailed through; the redaction test passed vacuously for the same reason and would have passed with the redaction deleted. (3) `NoGenotypeRepr` was silently voided by `@dataclass`, which generates `__repr__` on the subclass; fixed by claiming the slot in `__init_subclass__`, since `dataclasses` never overwrites a name already in `cls.__dict__`. (4) The hook was committed mode 100644, so git skipped it on Linux/macOS while `install-hooks` reported success. (5) `verify_all` compared via `read_text()`, whose universal-newline mode folds CRLF, so the check `.gitattributes` exists to protect could never fail. (6) `staged_files` lacked `-z`, so a non-ASCII path was quoted, `git show` failed, the error was swallowed, and the file was skipped unscanned. Also fixed my own `GENETICS_DATA_DIR` hole: pointing it inside the checkout relocated run bundles into the repo, where gitignore covers them only unevenly. Lesson for M1: a guard that has not been *demonstrated* failing on real input is not evidence of anything. |
| 2026-08-15 | — | Roadmap created. AGENTS.md and .gitignore in place; no code yet. |
| 2026-08-15 | M0.3–M0.5 | Privacy suite, pre-commit hook, CI. 90 tests total. **The suite caught a real cross-platform bug on its first run:** the fixture named `other_vendor_23andme.txt` matched the forbidden pattern `*23andMe*.txt`, and because `fnmatch` normcases via the OS, that check folded case on Windows but not on Linux — it would have passed CI on ubuntu and blocked on windows. Fixed three ways: matching is now explicitly case-insensitive everywhere, the fixture was renamed to `other_vendor_layout.txt` (a fixture that trips the guard teaches people to ignore the guard), and allowlisted paths are exempt from name rules. That exemption made `tests/fixtures/synthetic/` a trust hole, so it is now sealed by `test_synthetic_dir_holds_only_known_fixtures`. Also: writing genotype rows as literals in test files would fail our own content scan, so tests assemble rows at runtime from parts — and the AGENTS.md format block now spells out `<TAB>` instead of using real tabs, which is better documentation anyway. |
| 2026-08-15 | M0.1, M0.2 | Scaffold + fixture generator done. 24 tests, ruff and `mypy --strict` clean. Six fixtures at ~330KB each (12k markers). Two findings worth carrying forward: (1) `.gitattributes` with `eol=lf` turned out to be a correctness requirement, not tidiness — without it git rewrites fixtures to CRLF on Windows checkout and byte-identity fails; (2) M1.2's "parses the real file" criterion cannot be a CI test, so it is now split into a CI half (fixtures) and a manual local half. |
