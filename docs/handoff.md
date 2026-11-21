# Handoff: M15.1 full run on the real file

As of 2026-11-20, **M0-M14 are implemented; M15.1, the release gate's full run, is next**.
See [the M15.1 entry contract](#next-open-step-m151-full-run),
[the M14.7 record](#accepted-m147-accessibility),
[the M14.7 entry contract](#next-open-step-m147-accessibility),
[the M14.6 record](#accepted-m146-impossibility-cards),
[the M14.6 entry contract](#next-open-step-m146-impossibility-cards),
[the M14.5 record](#accepted-m145-qc-provenance-page),
[the M14.5 entry contract](#next-open-step-m145-qc-provenance-page),
[the M14.4 record](#accepted-m144-global-search),
[the M14.4 entry contract](#next-open-step-m144-global-search),
[the M14.3 record](#accepted-m143-reading-guide),
[the M14.3 entry contract](#next-open-step-m143-confidence-legend),
[the M14.2 record](#accepted-m142-ancestry-visualisations),
[the M14.2 entry contract](#next-open-step-m142-ancestry-visualisations),
[the M14.1 record](#accepted-m141-sections-and-empty-states),
[the M14.1 entry contract](#next-open-step-m141-sections-and-empty-states),
[the M13.7 record](#accepted-m137-outbound-query-lint),
[the M13.7 entry contract](#next-open-step-m137-outbound-query-lint),
[the M13.6 record](#accepted-m136-review-workflow),
[the M13.5 record](#accepted-m135-parity-test),
[the M13.4 record](#accepted-m134-machine-readable-confidence),
[the M13.3 record](#accepted-m133-card-search),
[the M13.2 record](#accepted-m132-agent-json-schema) and
[the M13.1 record](#accepted-m131-agent-read-commands).
**M14.7, the accessibility pass, is implemented.** A card face's link is its title, named by
the title and described by the tier, and stretched over the face; an arrow key on a select
no longer leaves the page; form controls have a 3:1 edge; the search page has one search
landmark; counts, the theme toggle and the ancestry scatter's points are named for a screen
reader. `genetics.testing.accessibility.audit` checks every page's markup and a test
computes every colour pair's contrast. No command, schema, view field or card changed. See
[the record](#accepted-m147-accessibility).
**M14.6, impossibility cards in their sections, is implemented.** Each section of the grid
names its assay limits at its head ("Not determinable from this array:") whatever the
filter, and renders those cards as their own block below its findings; grouped by tier, the
untiered panel has the same block. `genetics runs show --section --json` prints the list as
`assay_limits` (agent schema 10). See [the record](#accepted-m146-impossibility-cards).
**M14.5, the QC and provenance page, is implemented.** `/runs/{run_id}/qc` shows what
`genetics runs qc <run> --json` and `runs imputation <run> --json` print, whole, and the
route scans the page for genotypes as both commands do. `runs qc` gains the run's coverage
(`current_context.coverage`, agent schema 9): every polygenic score's saved coverage before
and after imputation, and the saved ClinVar fractions. See
[the record](#accepted-m145-qc-provenance-page).
**M14.4, the dashboard's search, is implemented.** A box at the top of every open run's nav
opens `/runs/{run_id}/search`, which lists what `genetics runs search <run> <query> --json`
prints: the same cards in the same order, from `reads.search_view`, each as the face the
grid shows with the words it matched. A query that reads as a genotype is refused in the
command's words and never shown again. See [the record](#accepted-m144-global-search).
**M14.3, the reading guide, is implemented.** `/guide` and `genetics cards guide` give the
six badges and what earns each, how a tier is decided, why rarity lowers confidence, what
a polygenic score can say and what the array cannot tell, with every threshold read from
the confidence engine. Every page's nav carries the legend. See
[the record](#accepted-m143-reading-guide).
**M14.2, the ancestry page, is implemented.** `/runs/{run_id}/ancestry` and `genetics runs
ancestry` show the PCA scatter against the run's own reference (bundle format 29 records
the positions), the nearest populations, ancient affinity and both haplogroups with their
marker counts. See [the record](#accepted-m142-ancestry-visualisations).
**M14.1, explicit empty states, is implemented.** Every section with nothing to show says
why, from one function the nav, the grid and `runs show --section` share. See
[the record](#accepted-m141-sections-and-empty-states).
**M13.7, the outbound-query lint, is implemented.** `genetics cards check-query` is what an
agent runs on every web search before sending it. It refuses a genotype written out and a
result told in words, exits 1, never prints the query, and with `--card` lists each word
the card's evidence does not print. The search commands refuse the same call shapes, the
fetcher checks every URL, and agent schema version 6 describes the verdict. The
[M13.7 session review](review_m137_session.md) closed full-width and punctuation
bypasses before the commit.
**M13.6, the agent review walk-through, is implemented.**
[Reviewing a run as an agent](agent_usage.md) gives the eight steps of a review, the keys
to read, the rule for what may leave the machine and what an answer has to carry, and
works the brief's curly-hair example through with real output from a run that is nobody's.
`tests/test_agent_usage.py` runs every command on the page. No command, schema, bundle
format or card changed.
The [M13.6 session review](review_m136_session.md) found the page claimed more for its
query check than the check does: a result told in words the card's evidence prints
("one copy") passes it. The page now states that limit, a test pins it, and M13.7
inherits it. The review also holds the statuses, error kinds and short-form commands the
page names to the code.
**M13.5, the CLI and dashboard parity test, is implemented.** `tests/test_parity.py`
fails when a dashboard page shows something no command prints: a route with no command, an
engine function only the dashboard calls, or a value on a page that is not in a command's
JSON. The five commands that print a run's other saved records (`runs clinvar`, `runs
secondary`, `runs imputation`, `pgx calls`, `hla calls`) now print the run envelope and a
schema tag, and the agent schema is version 5. See
[the parity section](agent_cli.md#parity-m135).
The [M13.5 session review](review_m135_session.md) found that a figure changed to another
figure in the same saved record passed the check, among them a polygenic score's coverage
and a card's within-family attenuation, and made those comparisons exact. It added a probe
that changes every value a card shows, which every suite's run now has to pass.
**M13.4 machine-readable confidence is implemented.** `genetics runs card --json` adds
`current_context.confidence`: one block for every kind of card, giving the saved tier and
score, each input with its weight and what it cost the score, every ceiling that applies,
which of them set the tier, and a sentence saying so. The saved card is unchanged, and the
agent schema became version 4. See [the confidence contract](agent_cli.md#confidence-m134).
The [M13.4 session review](review_m134_session.md) fixed a replay that summed rounded
figures, so that about one honest polygenic score in a thousand was reported as saved under
other rules, and stopped a rare call's rate being printed twice.
**M13.3 card search is implemented** as `genetics cards search <query>` (the knowledge pack,
no genotype) and `genetics runs search <run> <query>` (one saved run's cards, with each
one's result). Both rank with `genetics.engine.search.search`, and the agent schema is now
version 3. See [the search contract](agent_cli.md#search-m133). The
[M13.3 session review](review_m133_session.md) fixed a stemming rule that made
`cards search note` list 109 of 119 cards, and made the side-by-side bonus read the query
as typed. The
[M13.2 session review](review_m132_session.md) moved the schema to version 2, because version 1
refused two error kinds `genetics run` prints, and made `pgx calls` and `hla calls` give the
same kind as `runs` for a run that cannot be opened. Full-reference
and broad native acceptance remain recorded with their original milestones.
The M10.5 review reruns affected tests and does not claim another full native
suite. Read [AGENTS.md](../AGENTS.md) first, then [the roadmap](../phase1_roadmap.md).
The [M9.13 diff review](review_m913_session.md) fixes frozen fit/allele/type
validation and retains damaged-run errors in card detail views. Its full native
suite passes **3,015 tests, five existing Windows skips**, with four strict type
targets, complete card lint, fixtures and lint/format passing. **M10.1 reference
ingestion is now accepted**: complete CPIC/ClinPGx source processing, offline
inspection, frozen GRCh37 mapping proofs and explicit gaps. The M10.1 diff review
passes **3,137 native tests**, with five existing Windows skips; four strict type targets,
full card lint, fixtures and lint/format pass. The [PGx audit and contract](pgx_ingestion.md)
records source licences, partial normalization and the full-source offline acceptance.
The [session diff review](review_m101_session.md) records citation/publication,
parser and frozen-metadata fixes with all source pins and mapping counts unchanged.
**M10.2 calling is implemented**, with a separate schema-1 sample contract and
additive bundle format 19. The [calling contract](pgx_calling.md) records
uncertainty, complete frozen evidence and full-source synthetic acceptance.
**M10.4 guideline-linked interpretation and M10.5 section framing are implemented.**
One shared current notice appears across PGx views and CLI, independently of
filters and stage availability, without modifying frozen findings. See
[the framing contract](pgx_framing.md). Final combined validation covers
**3,294 unique passing tests**, five existing Windows skips: 3,274 broad-run
passes plus all 101 checks in the three files affected by sandbox restrictions.
All ten final interface cases, four strict type targets, full card lint,
fixtures, style and staged privacy checks pass.
The [M10.5 diff review](review_m105_session.md) finds no production defect;
it closes a reproduced CLI saved-summary/notice-count test gap. Production
code, source pins and saved schemas remain unchanged. All 516 affected
PGx/web/doctor tests and four final complete/gene CLI cases pass, with four
strict type targets, full card lint, fixtures and style passing.
**M12.2, the MTHFR calibration case, is implemented.** Four cards share rs1801133, each scored
on its own claim: homocysteine and folate in nutrition (well-established), and the venous
thrombosis, coronary heart disease and depression claims in physical and mental health (each
limited, because replication conflicts). No schema or bundle-format change. See
[the M12.2 record](#accepted-m122-mthfr) and [the calibration audit](mthfr.md). The
[session diff review](review_m122_session.md) removed one unsourced sentence on the depression
card, added a relative homocysteine figure and an absolute-risk statement, and made the
dashboard launcher say when its new verify-first shortcut is worth using.
**M12.1 nutrition cards are implemented.** Nine cards fill the nutrition section,
seven of them new, and a section pointer reaches HFE and celiac in their own sections; no schema
or bundle-format change. See [the M12.1 record](#accepted-m121-nutrition-cards),
[the nutrition audit](nutrition.md) and [the session diff review](review_m121_session.md), which
removed unsourced card sentences and sourced two allele names.
**M11.7 reproductive traits are implemented.** Seven polygenic cards take the
reproductive section beyond carrier status, on knowledge schema 9 and bundle format 28; see
[the M11.7 record](#accepted-m117-reproductive-traits),
[the model audit](reproductive_prs.md) and
[the M12.1 entry contract](#next-open-step-m121-nutrition-cards), now implemented.
**M11.6 carrier-screening scope is implemented.** One computed card states
that the reproductive section is not a carrier screen and counts what it leaves out; see
[the M11.6 record](#accepted-m116-carrier-screening-scope). The
[M11.6 diff review](review_m116_session.md) fixes a crash when CLI output is redirected on
Windows, counts imputed results apart from array reads and binds the audit's re-check to each
allele.
**M11.5 carrier status is implemented.** Knowledge schema 7 adds a
`carrier` declaration to single-marker interpretation cards. Fifteen reproductive cards
cover eight conditions and HFE C282Y joins the panel from physical health, making nine;
bundle format 24 saves each card's derived carrier state and re-derives it from the saved
match. See [carrier status](carrier_status.md).
The [M11.5 diff review](review_m115_session.md) found no defect in state derivation or
the bundle checks. It tightens five card statements against their sources (Gregg 2021's
gnomAD maximum, Scott 2010's carrier-couple pregnancies, the MCAD scope), refuses a saved
carrier record on a non-autosome, and records that 12 of the 16 panel markers are
multiallelic in dbSNP. Schema 7, panel schema 1 and bundle format 24 are unchanged.
**A synthetic end-to-end `genetics run` now fits in memory (2026-10-30 to 11-01).** Two
attempts on a 32 GB machine were stopped for low memory: the polygenic stage held every
score's 2.5 GB public 1000 Genomes extraction from preparation to scoring, then every
private score record (about 1.9 GB parsed per genome-wide score) until saving. Extractions
now reload one at a time from their cache, which reads 16 times faster. Records stay
compressed (`pgs/records.py`), and **bundle format 25** saves each as its own
`pgs-<card id>.run.json.gz`, indexed by `pgs.run.json` schema 2; no evidence is dropped and
the score record schema is unchanged. **A complete run on `34898fa` took 57.8 min**
(synthetic export, `--no-impute`, warm reference caches): 14 score references 10.4 min,
ClinVar coverage 3.5 min, runs of homozygosity 7.7 min, 14 scores 27.9 min, PGx and HLA
16 s, saving 7.7 min. Saving is mostly the write-side check of the 14 score records.
Python peaked at 7.6 GB while one score was loaded, and at least 10.9 GB stayed free.
Opening that run took 8.1 min (peak 5.8 GB). **Bundle format 26** then cut both costs:
guideline results are saved by reference to `pgx.run.json` (`cards.run.json` 402 MB to
0.8 MB; see [guideline cards](pgx_guidelines.md)), and each score record is checked
with one digest, on its stored bytes, instead of three re-serialisations. A format-26
copy of the same run is 593 MB and opens in 5.7 min with identical output. The scoring
parser is 1.8 times faster (PGS002143: 24.9 s to 14.1 s) and a score parses its file
four times rather than five, and an imputed run reads its dosage stream once, not once
per score (unmeasured). See the roadmap log. Every PLINK 2 and PLINK 1.9 call is now capped at
`--memory 4096` unless its caller sets its own; without the flag each reserves half of
physical memory. `GENETICS_PLINK_MEMORY_MB` overrides the cap, and an out-of-memory error
names it (`external/plink2.py`).
**An interrupted `genetics run` now resumes (2026-11-01).** A default imputed run takes
5½–8 hours (measured below), and an interruption after imputation used to keep only Beagle's
per-job checkpoints. `genetics run` now saves its long parts as they finish
(`run/parts.py`), and rerunning the same export picks up after the last one:
1. the completed imputation, reopened by its dosage files' digests rather than re-derived;
2. one read of the imputed doses, which card inputs, polygenic scores and PGx calls now
   share; each used to parse the whole stream, about 20 min apiece;
3. each polygenic score, as it finishes;
4. the PGx and HLA calls.

ClinVar, runs of homozygosity and archaic cards (about 12 min) are recomputed, and the
bundle write stays a single rename. Parts are reused only under the same export, engine
source, knowledge pack, reference lock, tools and options. A damaged part is recomputed
with a progress line saying so, and the bundle writer checks every reused part as it
would a fresh one. Parts are private, under `cache/run-parts/`. Nothing is written there
until the first part is saved, and the parts are removed once the bundle is saved;
`--restart` discards them first. A test session keeps them in a temporary directory
unless the test sets its own data directory (`tests/conftest.py`): one CLI test that
expects a failing run left a contract file in the real cache before this.
**Ancestry is now reproducible to the bit, and saved parts are bound to it (2026-11-02).**
The first resumed imputed run failed its save: every polygenic record carries the run's
ancestry, and the resumed run placed the same export a last bit differently (fit values
up to 8.8e-16 apart). Polars sums a group's rows in the order its threads deliver them,
so the 1000 Genomes centroids, pooled spread and ancient-group means varied by process;
with one polars thread three processes agreed. Those sums now use `math.fsum`
(`populations.exact_group_means`), and three processes give identical ancestry. As a
safety net, a saved score is reused only if it carries this run's ancestry, and the saved
PGx and HLA calls only if they were made under it; otherwise they are recomputed with a
progress line, rather than failing at the save.
**The first default imputed run completed (2026-11-02).** The synthetic fixtures cannot be
imputed: their coordinates are invented, so Beagle finds no panel markers in its first
window. The run used public 1000 Genomes stand-in HG00097, written as an AncestryDNA export
outside the checkout (290,285 autosomal markers, no sex-chromosome or MT markers). On
`a5bf931` it ran and saved in 4 h 59 min; a fresh run is about 5½ hours:
- **imputation:** 22 autosomes, 2 h 31 min fresh, or 1 h 57 min when the imputation stage
  reuses Beagle's completed jobs. Almost all of it is Python reading panel markers and
  validating doses; Beagle itself took 44 s on chromosome 1;
- **one dose read:** 29 min, for 81,272,000 records at 1,316,215 loci;
- **14 scores:** 80 min;
- **saving:** 54 min, made up of dose validation (23 min), score checks (12 min) and the
  PGx pass over every saved dose (19 min).

Python peaked at 10.9 GB and the bundle is 1.3 GB; reopening it takes 52 min, because
it repeats the save's checks. PLINK 2 crashed once (0xC0000005) scoring reference
samples, and the resume rescored that score. The save now reports progress through its
last 31 minutes, which were silent. See the [run-cost diff review](review_run_cost_session.md).
**History was rewritten on 2026-11-05.** Figures and results from the real export were
removed from every commit and commit message, and the author's personal address was
replaced with the GitHub noreply address, so every commit has a new hash. Citations in the
current docs use the new hashes; older versions of these files still cite the old ones. Any
other clone must be re-cloned. From a real run, record array properties, timings and sizes,
never its results or per-sample counts (AGENTS.md §1.1).
**The first real-export run completed (2026-11-05).** `genetics run` on `e30879d`, with
default options and a fresh imputation, ran and saved in 7 h 49 min:
- **score references, ingest, ancestry:** 7.4 min, from warm caches;
- **imputation:** 3 h 31 min, 23 jobs (22 autosomes and X non-PAR);
- **one dose read:** 51.5 min, about 83 million records;
- **ClinVar coverage, runs of homozygosity, archaic:** 12 min;
- **14 scores:** 1 h 59 min;
- **PGx:** 11 s;
- **saving:** 67 min, made up of dose validation (31 min), the ClinVar write (1 min), score
  checks (15 min) and the PGx pass (19 min).

Python peaked at 14.7 GB and Java at 4.3 GB, and at least 6.9 GB stayed free. The bundle
is 2.1 GB: score records 761 MB, the ClinVar lookup 721 MB (24 MB on the stand-in) and
doses 505 MB. The imputation cache is 4.6 GB. The estimate was 5¾–6 hours. Public work
that should not depend on the export also ran slower: scoring the reference samples took
a median 7.7 min per score, against 5.0 on the stand-in. Part of the gap may therefore be
the machine or memory pressure; the cause is not established.

The reopen passed in 54 min. From that one opened copy, all 114 dashboard pages returned
200 and seven CLI reads exited 0, each in under 10 s, with their output discarded unread.
The largest page is a 47 MB guideline card, and `runs show --json` prints 1 GB.
**Three things this run left open; the first is now fixed:**
1. **Reading a saved imputed run cost about 54 min per read. Fixed and accepted on
   2026-11-06.** [`run/checks.py`](../src/genetics/run/checks.py) records that a bundle's exact
   manifest passed its deep checks under this exact engine. The save writes the record, and
   later reads still check every digest but skip the four deep checks: the doses, the score
   records, PGx against every dose, and the ClinVar lookup. That read took 12.8 s on the
   real run, against 54 min in full, and holds 2.4 GB (peak 2.8 GB). The dashboard keeps one
   opened copy and reads again if any file's size or modified time changes.
   `genetics runs list --verify` always repeats the checks and replaces the record. Any change
   to the engine's source makes the next read repeat them, once, with progress on stderr.
   A save's record covers the payloads it checked, not what a reader parses back from them;
   `--verify` checks the stored bytes. **Acceptance on the real run:** `runs list --verify`
   passed all four saved runs in 58 min, running alongside `ci-local` for the first 19, and
   peaked at 11.9 GB with at least 6.2 GB free. With that record, `store.load_run` took
   13.4 s, seven CLI reads exited 0 in 14–26 s each, and all 114 dashboard pages returned
   200: 12.3 s for the first, at most 0.47 s for each later one, 15 s in all. Output was
   discarded unread. `ci-local` itself peaked at about 0.5 GB of Python, sampled every 5 s.
   The [read-path review](review_read_path_session.md) then fixed which engine a record
   names, so the first read of each saved imputed run repeats its checks once more.
   **What source changes cost:** nothing until a saved run is opened, and several changes
   cost one repeat, not one each. The dashboard's first page pays that repeat, so after a
   source change run `genetics runs list --verify` first. A saved run never gains a section
   added later: seeing one on real data takes a new run, about 8 h, since parts saved by
   other code are not reused. That run's save writes its own record.
2. **HLA did not run.** The four HIBAG classifiers are not fetched, because their model terms
   are unspecified and fetching needs the owner's explicit opt-in; the HLA cards record
   that they did not run. Adding it is
   `genetics refs fetch --only <classifier> --opt-in <classifier>` for the selected
   classifier, then a rerun with `--hla-model-opt-in`.
3. **X's pseudoautosomal intervals are not imputed on this vendor's exports.** They report
   `insufficient_typed_calls`, as [the pipeline contract](imputation_pipeline.md) says:
   AncestryDNA labels those markers chromosome 25, which has no coordinate contract. The
   intervals outside them (`X_left`, `X_right`) report the same.
**M11.4 HLA-linked cards are implemented.** Knowledge schema 6 adds
`kind: hla`, and eight cited cards read the frozen classifier calls: celiac DQ2.5/DQ8, type 1
diabetes DR3/DR4-DQB1\*03:02, ankylosing spondylitis B27 and narcolepsy DQB1\*06:02 in
immunogenetics, and B\*57:01, B\*15:02, A\*31:01 and B\*58:01 in pharmacogenomics, whose
recommendation rows come from the run's frozen CPIC release rather than the knowledge pack.
Bundle format 23 rebuilds every HLA card from its frozen definition and the bundle's own
HLA, PGx and ancestry records. See [the card contract](hla_cards.md).
The [M11.4 diff review](review_m114_session.md) stops one-field allele groups counting
null (`N`) alleles, lists the four HLA drug cards on the PGx overview and in
`genetics pgx calls`, and tightens three card sentences against their sources. Schema 6,
card result schema 1 and bundle format 23 are unchanged.
**M11.3 HLA classifier selection and call confidence are implemented.**
The model-terms opt-in now selects the HIBAG classifier from the run's saved M5
placements and declines rather than guesses; an explicit classifier still runs with its
ancestry mismatch recorded. Each predicted locus carries an observation ceiling from its
posterior, marker coverage and classifier ancestry match. HLA sample schema 2 is bound to
the saved ancestry in bundle format 22. See the
[selection and confidence contract](hla_selection.md).
The [M11.3 diff review](review_m113_session.md) found no defect in selection, saved
evidence or the bundle binding. It closes a dashboard coverage gap: the placed,
declined, ambiguous and unsupported views had never rendered under test, and a broken
uncertainty line passed every test. It also corrects the explicit-override wording
and makes `HLAStage.select()` honour a pre-set cancellation. Schema 2 and format 22
are unchanged.
**M11.2 HLA classifier imputation is implemented.** It uses an
opt-in HIBAG HLARES hg19 model, validates model metadata, proves marker
strand from dbSNP and 1000 Genomes allele sets, and persists frozen per-locus HLA calls
(bundle format 21 for schema 1). See the
[classifier-imputation contract and validation](hla_imputation.md).
The [M11.1 diff review](review_m111_session.md) hardens path redaction, terminal-wait
interruption, regular-file protocol validation and R bootstrap scope. Native R readiness
and bridge-script acceptance are now separate checks. Native prediction through synthetic
classifiers has run in CI since 2026-10-18, and prediction through the published
classifiers passes locally (see the M11.3 step below).
Final reviewed coverage passes **3,344 unique tests**, seven skips, with all four
strict type targets, complete card lint, fixtures and style passing. The
[review validation record](review_m111_session.md#validation) distinguishes the
broad run from the final affected checks.
See [the guideline contract and audit](pgx_guidelines.md) and the
[M10.4 diff review](review_m104_session.md). The reviewed complete native suite
passes **3,292 tests**, five existing Windows skips; 103 focused checks, four
strict type targets, full card lint, fixtures, style and whitespace checks pass.
Full-source legacy comparison and schema-2 reload pass in 109.05 seconds.
Original M10.4 validation covers
3,267 unique passing checks, five existing Windows skips, four strict type
targets, full card lint, fixtures, style and privacy checks.
The [M10.3 diff review](review_m103_session.md) fixes incomplete saved text and
ignored tier-filter acceptance. Validation covers **3,219 unique passing tests**,
five existing Windows skips (3,218 broad-run passes plus the native-tool setup
recheck), four strict type targets, full card lint, fixtures, style and privacy.
Its entry contract below is retained for M10.4 review. Earlier milestone records
below remain historical.
M10.2 acceptance passes **3,188 native tests**, five existing Windows skips,
all four strict type targets, complete card lint, fixtures, style and staged
privacy checks. Full-source offline synthetic calling/reload passes; no
personal export was opened. See [the acceptance record](pgx_calling.md#acceptance).
The [M10.2 diff review](review_m102_session.md) binds PGx observations to saved
native dosages, tightens malformed-input handling and corrects error categories,
allele labels and reliability styling. Sample schema 1 and format 19 remain
unchanged; the next-step contract below includes the review's findings.
Review validation covers **3,208 unique passing tests**, five existing Windows
skips: a 3,202-pass broad run, then all 399 affected integration tests after the
final six cases. Four strict type targets, full card lint, fixtures and style
pass. Full-source synthetic comparison reproduces the original healthy results
and schema-1 JSON reload in 274.26 seconds; see the review for exact scope.

M9.1–M9.6 are implemented and reviewed. M9.7 is implemented and accepted as of
2026-10-11:
physical-health PRS3820/GPS_Mult cards and pinned scoring references are authored;
synthetic pipeline/bundle/CLI/dashboard checks and full card lint pass. Full-panel
reference extraction and default-on native imputation across all 22 autosomes pass
on a public stand-in, as do both default-imputed health scores. The second,
explicitly non-imputed CAD stand-in exposed a display-quality accumulation error;
accurate summation now passes its three synthetic regressions. That stand-in and
both retained default-score reload validations passed on 2026-10-10 at 23:58.
The pre-review M9.7 native suite after the fix passes 2,872 tests with five existing
Windows skips in 497.27 seconds. All four strict type targets (200 files), fixture
reproduction and lint/format pass. The owner-supplied synthetic
dashboard screenshot exposed small compact labels; those are now HTML text above
the chart. Synthetic HTTP tests verify both chart/detail routes; a post-fix manual
refresh/detail confirmation was requested but has not arrived, and no automated
post-fix browser capture is claimed. The quality fix passes all 48 card tests.
M9.8 is accepted: public SCZ_GHS and UK Biobank-only GPpsy cards are authored,
reference-pinned and fetched. Synthetic end-to-end checks, both default-imputed
and explicit no-impute public-stand-in scoring, and saved-record validation pass.
The pre-review M9.8 native acceptance suite passes 2,873 tests with five existing Windows
skips in 737.42 seconds; full dbSNP lint resolves all 35 marker keys over 55 cards
and 276 renders, and strict Windows Python 3.13 checks all 200 source files.
The primary paper's GPpsy result is used rather than copying a conflicting
catalogue performance mapping. The schizophrenia association is explicitly the
paper's cross-site Bayesian model-family result, not Geisinger-only calibration.
The requested [session diff review](review_m97_m98_session.md) reproduced and
fixed impossible source-copy allocation in frozen reference proofs, with a valid
multiple-END-group preservation regression. It also corrected CAD's incident
association to the European subgroup HR 1.74 (1.71–1.78), rather than assigning
the overall-validation HR 1.73 (1.70–1.76) to that subgroup. Native sums and
imputation are unchanged. Both default-imputed and explicit no-impute CAD cards
were reassembled from retained score records and passed saved-card validation;
the completed public imputation proofs pass the stricter allocation validator.
Final reviewed validation: **2,875 tests passed, five existing Windows skips**
in 1,416.58 seconds. All four strict type targets check 200 files; full dbSNP
lint passes 55 cards/276 renders/35 resolved keys. Lint/format, byte-identical
fixtures, whitespace checks and staged privacy scanning pass. No genotype-derived
artifact or fetched payload is staged. Both milestones and the requested review
are complete. M9.9–M9.13, M10 and M11.1–M11.3 are also implemented; M11.4 is next.
See [physical-health PRS cards](physical_health_prs.md) and
[mental-health model audit and scale acceptance](mental_health_prs.md).

<a id="next-open-step-m912-fitness-and-physiology"></a>

## Accepted M9.12 fitness and physiology

Implementation is authored on 2026-10-14: four schema-3 variant cards for
ACTN3 resistance training, ACE serum concentration, COL5A1 chronic Achilles
tendinopathy and ACSL1 aerobic response, plus schema-4 PGS002143 mean grip
strength. No engine, bundle-format or renderer change is needed. Source
population and effect applicability are explicit; conflicting replication
caps the two affected variant cards at limited, and the injury comparator
outcomes retain null evidence. Forward-only variant matching excludes I/D
and unsupported alleles. The complete 966,283-row grip model is fetched,
per-score licence-checked and checksum-pinned. Full dbSNP lint passes
69 cards/320 renders/39 keys; style and fixtures pass. All 97 focused
variant/polygenic-card checks, four strict type targets (201 files) and the
staged privacy scan pass. All 2,923 unique checks pass with five existing
Windows skips: the broad run passed 2,900 checks, and its 23 Java-8 setup
failures/errors passed with the documented portable Java 17 runtime.
Full-model native acceptance passed in a separate `acceptance/m912` checkpoint:
complete reference preparation, default-imputed and explicit no-impute scoring,
and both written-record disk-read validations. Every source term is retained;
all verified inputs and completed imputation were reused. Both acceptance
records report `passed`, the checkpoint is `complete`, and the runner exited
with an empty error log. A final check reverified every reusable input and
retained checkpoint file; nothing remains pending. See the
[evidence audit and measured acceptance](fitness_physiology.md).

The [M9.12 diff review](review_m912_session.md) found that the existing
variant checks accepted four reversed face claims and a wrong effect measure.
Published directions and units are now bound before evaluating fabricated
observations and checked after saved CLI/dashboard reload; five mutation
regressions reject those changes. All 102 focused card tests pass. The
complete grip payload pin/terms and both retained native card evidence
bindings pass locally; the original full-scale acceptance is preserved.
The review changes tests and documentation only. M9.13 remains next.

### M9.12 entry contract (retained for review)

Expand the Fitness & physiology section through the shared engine, knowledge
schema 4 and bundle format 17. ACTN3, ACE, injury and trainability associations
need exact endpoint-specific primary evidence: a functional molecular effect
does not establish elite-athlete status, an injury prediction or a training
prescription. Retain weak findings with their effect units, source population,
sample sizes, replication and calibration limits visible. Do not silently
borrow a performance estimate from a different phenotype or model.

Audit public models and their score-specific licences before authoring. Bind
each actual model/source, citations, evaluation N and effect/interval before
synthetic substitution, then check saved per-card CLI/dashboard evidence.
Keep unknown direct effects and absolute outcomes explicit. For ACE or any
other indel-dependent claim, AGENTS.md §4.2 still applies: consumer I/D labels
cannot be allele-matched without an explicit verified representation mapping.
Do not infer structural variation or a causal effect from a tag association.

Reuse M9.9's durable `standins` inputs, the locator in `standins/imputation.json`
and all 22 verified dosage files with their matching `public-imputation`
provenance. M9.11's completed private runner demonstrates full-model
preparation/scoring, resource measurement and six disk-read validations.
Preserve M9.9–M9.11 and use a separate private `acceptance/m912` directory.
Do not rerun completed imputation or reduce a source model. Genetic values,
coverage summaries and hashes stay outside Git and out of chat. Synthetic
pipeline/bundle/CLI/dashboard checks, types, card lint, fixtures and privacy
gates remain required. Record any necessary engine/schema change here before
implementing it. The unchanged renderer's previous browser visual check
remains unavailable; no new screenshot review is claimed.

<a id="next-open-step-m913-card-level-ancestry-match"></a>

## Accepted M9.13 card-level ancestry match

M9.13 is accepted on 2026-10-14. One run-owned 1000 Genomes placement is shared
before imputation with variant and PRS evaluation. Selected-outcome evidence
controls the comparison; explicit UNKNOWN/MULTI, decline, not-run and null states
are visible. The separate weighted variant policy keeps PRS transfer ceilings
out of single-variant interpretation and preserves frequency/quality limits.
Format 18 verifies frozen scalar/multi-marker comparisons/confidence and PRS/run
placement equality, preserving formats 1–17. All 2,995 unique checks pass with
five existing Windows skips; four strict type targets, full card lint, fixtures,
lint/format, whitespace and staged privacy gates pass. The
[contract and exact acceptance](card_ancestry.md#acceptance-2026-10-14) explains
the native helper's corrected tools-directory recheck and 67 new synthetic cases.

<a id="next-open-step-m101-pharmacogenomics-ingestion"></a>

## Accepted M10.1 pharmacogenomics reference ingestion

M10.1 is accepted on 2026-10-14. Domain-specific ZIP ingestion replaces the
pending PharmGKB extraction step; complete CPIC COPY/INSERT dumps agree
independently without SQL execution. The source artifacts retain raw tables,
licence/release metadata and source-bound checksums. Catalog schema 1 joins
explicit genomic HGVS assembly mappings to verified dbSNP GRCh37 keys and
retains all definitions/functions/phenotype relationships, including gaps and
conflicts. Kernel locks, atomic publication, interruption/reuse and frozen
validation are implemented. CLI `pgx prepare` and `pgx inspect` use the same
reference library. Sample calling and guideline rendering remain upcoming;
bundle format 18 and M9.13 confidence arithmetic are unchanged.

Complete-source ingestion retains **312,006 ClinPGx rows**, **125,945 CPIC
rows**, **1,354 definitions** and **112,820 diplotype rows**. **493/1,210 source
locations** resolve to verified GRCh37 SNP keys; all residual states remain
visible. Eight-gene inspection, exact source mapping joins, frozen reloads and
verified completed-catalog reuse pass with networking blocked in **39.98 seconds**.
Raw/derived source verification passes with no pending steps. No personal export
was opened. See the [full audit and per-gene coverage](pgx_ingestion.md).

Original implementation validation: **3,104 unique checks passed**, five existing Windows skips.
The broad native run passed **3,091** checks in **614.05 seconds**; its one
additional PGS arithmetic skip passed with `GENETICS_PGS_TEST_TOOLS` configured
(all 27 reference tests pass). The final **89 PGx tests** include twelve cases
added after broad-suite collection, all passing in **18.42 seconds**. Four strict
Windows/Linux × Python 3.11/3.13 type targets pass (211 files); full dbSNP card
lint passes 69 cards/320 renders/39 keys. Style, fixture reproduction, whitespace
and privacy gates pass. Fetched payloads, indexes and audit outputs stay ignored.

**The subsequent [M10.1 diff review](review_m101_session.md) is complete.** It fixes
null guideline citation joins, hardlinked scratch publication, COPY UTF-8 byte
decoding, permissive TSV/JSON parsing, incomplete/inconsistent frozen source
metadata and nested output locking. **3,137 tests pass**, five existing Windows
skips, in **486.78 seconds**; four strict type targets, full card lint, fixtures,
style and privacy checks pass. Full-source offline acceptance reparses both SQL
dumps, checks the saved tables, verifies both sources, retains prepared-catalog
reuse and validates all eight gene publication joins/reloads in **55.06 seconds**.
Source pins, normalization counts, catalog/source schema 1 and bundle format 18
remain unchanged. No personal export was opened.

<a id="next-open-step-m102-snp-tractable-diplotype-calling"></a>

### M10.2 entry contract (implemented; retained for review)

Use `pgx/catalog.py` as the versioned public reference interface. Plan and record
a separate versioned sample-call record and saved-bundle extension before
implementing calling. Do not alter M9.13's frozen confidence method.

- Restrict calling to CYP2C19, CYP2C9, VKORC1, SLCO1B1, TPMT, DPYD, NUDT15 and
  G6PD. Preserve every compatible source definition, unresolved constraint,
  function conflict, structural gap and missing phenotype mapping. The reference
  snapshot deliberately keeps alleles it cannot normalize; no callable subset
  may silently eliminate those alternatives.
- GRCh37 normalization remains partial, especially for CYP2C19 and G6PD. Use
  exact position/allele keys and retained rsID identity; add a verified primary
  mapping source if necessary rather than guessing coordinates or strand.
  A missing marker cannot establish a reference allele. CPIC CYP2C19's reference
  sequence is named `*38`, not an assumed `*1`; retain the source definition.
- Enumerate unresolved phase and preserve native sample ploidy, original/imputed
  call source, quality and rarity limits. A dosage or two doubled X calls alone
  do not establish a phased diploid haplotype. G6PD needs the existing sex/QC
  contract; CYP2D6 remains not callable regardless of its SNP definitions.
- Use the source's actual lookup semantics. DPYD declares `ACTIVITY_SCORE` and
  retains gene-specific notes; do not substitute a generic two-star-allele
  sum. VKORC1 has no phenotype lookup rows in v1.60.0; expose that gap and audit
  genotype-linked guideline/recommendation semantics before interpreting it.
- Keep definition-ID joins and raw function names distinct. CPIC's CYP2D6
  copy-number aliases reference base definitions, and 4,124 source diplotype
  rows have absent definition labels in CYP2D6/HLA-A/B. Those genes are outside
  M10.2's calling scope; never synthesize missing definitions. The eight target
  genes have no missing definition labels in their source diplotype rows.
  Citation inspection now excludes null guideline joins; use actual returned
  citations/source records when authoring later guideline cards.
- Maintain one engine with saved CLI/dashboard parity. Add synthetic cases for
  phase ambiguity, missing positions/functions/phenotypes, I/D exclusions,
  biological ploidy, partial/conflicting definitions, rare/imputed reliability
  and corruption/historical compatibility. All low-confidence findings remain
  visible. M10.3 reuses `cyp2d6_structural_variation`; do not author a duplicate.

<a id="next-open-step-m103-cyp2d6-placement"></a>

### M10.3 entry contract (implemented; retained for review)

M10.2 computes phase-unresolved definition-ID candidates for the eight tractable
genes. Each result retains coverage, unresolved/missing/unassigned constraints,
source functions, exact phenotype joins, DPYD activity semantics and native G6PD
ploidy alternatives. Unknown/poor imputation quality and rare-call bands lower
reliability without suppressing candidates. `pgx.run.json` saves the complete
catalog and private observations; readers reproduce the results and bind sex
and imputation mode to the run. Formats 1–18 expose PGx as not recorded.
The review additionally compares the complete PGx dosage records with the
independent native payload on both save and reload. A locally consistent PGx
record cannot substitute a different genotype, quality or duplicate count.
Original probe presence, eligible direct calls and no-call provenance must also
agree with that native evidence, accounting for recorded complementation and
the array's doubled representation of single-copy calls.
`genetics pgx calls RUN --gene GENE --json` includes source and observation
provenance. The dashboard shows all gene faces, including when grouping by
confidence, and paginates all candidates with their total stated.

M10.3 verifies and finishes the placement of the already-authored
`cyp2d6_structural_variation` card beside these calls. It is already assigned to
pharmacogenomics; do not author a second card, reinterpret its SNP definitions,
or duplicate the source snapshot contract. Verify the dashboard section, the
`/runs/<id>/pgx` overview and gene-detail routes, plus saved CLI inspection.
Check tier grouping and filters: sample calls remain displayed independently
of knowledge-card filters, so the assay limitation must remain visible beside
them. Inspect unavailable-reference and historical/nonstandard packs too;
report missing saved card evidence explicitly instead of claiming it was
recorded or mutating the run. Keep all eight genes and every candidate visible.
Use definition IDs to attach uncertainty to its actual source allele, and
retain the existing reliability badge styles and scoped numerical PPV. M10.4
then owns guideline-linked interpretation; M10.2 returns source mappings only,
with no dosing claims. VKORC1's genotype-linked recommendation keys are exposed
for that audit, while its absent phenotype table remains explicit.

M10.3 now uses one saved-evidence adapter for CLI and dashboard inspection.
The adjacent limitation survives section/tier filters and appears on the PGx
overview and every gene detail, including missing-reference and historical
stages. Missing saved cards are explicit; no current card is substituted.
Six synthetic cases cover both card states and all three stage states, all
eight genes, 136 candidates over two pages and unchanged bundle bytes.
See [the placement contract](pgx_calling.md#m103-cyp2d6-placement).
Validation covers **3,214 unique passing tests**, five existing Windows skips:
3,194 passed in the broad sandbox run, and all 20 environment-restricted
failures pass in targeted checks with writable cache/process/architecture
access. All 449 affected interface checks and the final six strengthened
placement cases pass. Four strict type targets, full card lint, fixtures,
style and privacy gates pass; the guide records exact run boundaries.

<a id="next-open-step-m151-full-run"></a>

## Next open step: M15.1 full run on the real file

M15.1: a full run on the real file, offline, start to finish, recording wall-clock and peak
memory in the progress log, and re-running M4.10's OS-level network block at full pipeline
scope. Nothing has been selected or verified beyond what is listed here.

What already exists:

- **The run.** `genetics run --input <export>` with imputation on by default (AGENTS.md
  §4.3), writing outside the repository (§1.5). `genetics ci-local` and the suites run every
  stage on synthetic data only.
- **The OS-level block (M4.10)** is `genetics/testing/isolation.py`: a Linux network
  namespace (`unshare --map-root-user --net`, or `sudo -n --preserve-env=<names> unshare
  --net` where isolation is required). **Windows has no unprivileged mechanism and skips.**

What is open:

- **This is the owner's step.** It opens the real export, so an agent may run it only when
  the owner asks, and nothing from it (a card, a count that echoes a call, a log line) goes
  into a commit, an issue, a search or a prompt (§1.1, §1.3). Only wall-clock, peak memory,
  stage timings and pass or fail belong in the progress log.
- **Where the network block runs.** The primary platform is Windows, where M4.10 skips. A
  full run under the namespace needs Linux or WSL2 with the references and tools present
  there; whether that is the route, or a Windows firewall rule run elevated once, is the
  owner's decision.
- **How peak memory is measured** (run sheet item 5) across child processes (Beagle's JVM, PLINK, R) and not
  only the Python process.

<a id="project-review-before-m151"></a>

### Before M15.1: an overall project review (proposed 2026-11-20; scope 1 started 2026-11-21)

**Scope 1 is done (2026-11-21): [review_project_engine.md](review_project_engine.md)** holds
its to-do list, findings and decisions. One P1 was found and fixed before M15.1: the
likely-artifact gate could not fire for any allele gnomAD had seen (B1), so the M15.1 run
will screen far more rare calls as likely artifacts than the 2026-11-05 run did. Everything
else was P3 or recorded for after M15.1. **Scope 2 (the M15.3/M15.4/M15.6 audits) is next**
under the recommendation below; scopes 3–4 have not started.

Every milestone was reviewed on its own diff; nothing has yet looked at the project whole
(about 63,000 lines of source, 60,000 of tests, 41 review records). Four scopes were
proposed to the owner, who has not yet chosen:

1. **Engine correctness and consistency.** Confidence, matching, polygenic scoring and the
   save and read paths, read as a whole for faults between modules that a per-diff review
   misses; and AGENTS.md's hard rules checked across the codebase, not per diff: no
   genotype reaches a commit, log or outbound request (§1), no code path drops a card for
   low confidence (§0.1A, §6), every card carries its citations (§3, §6).
2. **The release gate's audits that need no real file**, done now: M15.3 (privacy: `git
   log --all` for any genotype-derived blob, `.gitignore` against every path the app
   writes), M15.4 (licences: `manifest.lock`, nothing non-permissive vendored, per-score
   PGS terms honoured) and M15.6 (citations: every shipped card's DOI, PMID or accession
   resolves).
3. **Documentation.** This file and the roadmap are mostly accreted history (4,065 and 3,630
   lines), and the README is 504 lines of milestone paragraphs. Proposed to fold into M15.7,
   which rewrites the README as setup, fetch, run and the privacy warning.
4. **Code health.** Dead code, duplication, and the full suite's 17 minutes.

**Recommended: 1 and 2 before M15.1's first session**, 3 with M15.7. The order matters
because of the run sheet's rule: a change to Python source under `src/genetics` between
sessions stops the saved parts being reused, and the next session imputes again. So an
engine change from the review lands before session 1 or waits until M15.1's bundle is
saved.

<a id="m151-run-sheet"></a>

### M15.1 run sheet (prepared 2026-11-20, not yet run)

**Expected duration: about 9–10½ hours of unattended run**, plus HLA if it is opted in, and
the network-block setup below. This is an extrapolation from the one measured real-export
run (7 h 49 min on 2026-11-05, `e30879d`), scaled for the polygenic cards added since: 21
now, 14 then. That run's own estimate (5¾–6 h) was about 30% low, so read the range as a
floor.

| Stage | Measured 2026-11-05 | Expected for M15.1 | Why |
|---|---|---|---|
| Score references, ingest, ancestry | 7.4 min, warm | 10–30 min | the seven newer scores' 1000 Genomes extractions are not cached |
| Imputation, 23 jobs | 3 h 31 min | about 3.5 h | fresh: the engine changed, so no saved part is reused |
| One read of the imputed doses | 51.5 min | about 50 min | |
| ClinVar coverage, ROH, archaic | 12 min | about 12 min | |
| Polygenic scores | 1 h 59 min for 14 | about 3 h for 21 | about 8.5 min a score on the real export |
| PGx | 11 s | seconds | |
| HLA | did not run | not measured | HIBAG classifiers not fetched; R subprocess |
| Saving | 67 min | about 75 min | about 1 min of checks per added score |

Memory should stay near the last peaks (Python 14.7 GB, Java 4.3 GB, at least 6.9 GB free):
scores load one at a time, so seven more add time, not memory. The save writes the
deep-check record, so the first read afterwards should take seconds, not 54 min.

**Before starting** (checked 2026-11-20 with `genetics refs status`):

1. **Choose where the network block runs** (see "What is open" above). The Windows firewall
   route needs an elevated rule that blocks the Python, Java, PLINK and R processes, and a
   check that it does, before the run. The WSL2 route needs references, tools, Java 17 and R
   installed inside Linux (the gnomAD exomes alone are 63 GB), and its timings will not be
   comparable with the table above.
2. **Decide HLA.** The four HIBAG classifiers are `blocked-by-licence` and not fetched. To
   include HLA: `genetics refs fetch --only <classifier> --opt-in <classifier>`, then run with
   `--hla-model-opt-in`. Without it the HLA cards say they did not run, as on 2026-11-05.
3. **All 21 polygenic score files are fetched.** `gwas_catalog`, `panukbb_manifest` and
   `finngen_r12` are missing; no shipped stage reads them.
4. **Java 17** on `JAVA_HOME`: the machine's default `java` is Java 8, which the pinned bref
   tools refuse.
5. **Decide how to sample peak memory** across Python, Java, PLINK and R, for example a
   process sampler every few seconds that sums the run's process tree.
6. **Run `genetics runs list --verify` first** if engine source changed since the last read
   of a saved run, so the dashboard does not pay that check later.

**The command:** `genetics run --input <export> --restart`, with imputation on (the default).
`--restart` discards parts left by an earlier interrupted run, so the timings are of a run
from the start. Use `--restart` for the first session only; see the next paragraph. Progress goes to stderr; keep it, since it carries the stage timings.

**Running it in sessions.** The run does not have to be one sitting. `genetics run` saves
its long parts as they finish (`run/parts.py`): the imputation, the dose read, each
polygenic score, and the PGx and HLA calls. Running the same command again without
`--restart` resumes after the last one saved. There is no option to stop at a stage, so
each session ends with Ctrl+C at a line that follows a saved part:

| Session | Covers | About | Stop at |
|---|---|---|---|
| 1 | score references, ingest, ancestry, imputation | 3¾–4 h | `Reading imputed doses once for card inputs, polygenic scores and PGx ...`, which is printed just after the imputation part is saved |
| 2 | dose read, ClinVar, ROH, archaic, most scores | about 4 h | any point once the dose read is done; each score is saved as it finishes, so only the score in progress is lost |
| 3 | the remaining scores, PGx, HLA, saving | 1½–2½ h | runs to the end; the saved parts are removed once the bundle is written |

- **Start session 2 and 3 with the same command, without `--restart`.** The first line must
  read `Resuming an interrupted run of this export from its saved parts: imputation, ...`.
  If it reads `Saving this run's parts as they finish ...` instead, the parts were not
  matched; stop at once, or imputation runs again from the start.
- **Change nothing between sessions.** Parts are reused only under the same export file,
  the same Python source under `src/genetics` (by content, `checks.engine_sha256`), the same
  knowledge pack, reference lock and tools, and the same options, so `--hla-model-opt-in` is
  decided before session 1. Templates, styles and docs do not count; a `.py` edit does. Any
  code change from a project review waits until the bundle is saved, or lands before
  session 1.
- **Keep the environment fixed too** (project engine review F1). The parts' contract does not
  name the installed Python packages or the `GENETICS_BEAGLE_JAR`, `GENETICS_RSCRIPT` and
  `JAVA_HOME` overrides. A reused part keeps its own provenance, so nothing false is saved,
  but a resume across such a change mixes tool builds between parts. Do not `uv pip install`,
  upgrade R or HIBAG, or change those variables between sessions.
- **Each resume repeats some work:** ingest, ancestry and the score references (from their
  cache), and reopening the saved imputation by its dosage files' digests (4.6 GB to hash;
  not yet timed). ClinVar, ROH and archaic (about 12 min) are not saved as parts, so each
  session that gets past the dose read computes them again. Record each session's start,
  its resume overhead and its stages.
- **The network block** must be in place for every session, not only the first.
- **What this measures.** The stage timings stay comparable with the table above, and the
  sum of the sessions less their resume overhead estimates an uninterrupted run. It is not
  an uninterrupted wall-clock; say so in the record. It also exercises the resume path on
  the real export, which the 2026-11-05 run did not.

**What to record, and where.** In the roadmap's progress log and the M15.1 record here: the
commit, wall-clock in total and per stage, peak memory per process and free memory, bundle
and cache sizes, whether every outbound request was refused by the block, and pass or fail.
Never results, card outcomes, per-sample counts or anything a stage printed about the
genome (AGENTS.md §1.1, and the 2026-11-05 history rewrite). Then compare the stage times
with the table above, and say which estimate was off and why if that is known.

What M14.7 hands over:

- **`genetics.testing.accessibility.audit(html, page=True)`** lists a page's markup
  problems; a new page or partial is audited by adding its address to `PAGES` in
  `tests/web/test_accessibility.py`, or, for a run only another suite saves, by calling
  `audit` there as `tests/web/test_ancestry_page.py` does.
- **A card face's link is its title** (`h3.cardtitle > a.cardlink`, `h4` in the assay-limit
  block). A test that looked for the title as the heading's whole text now finds it inside
  the link. The face's layout and the stretched link's positioning are on `.cardface`, which
  only `_cardface.html` sets; `.card` is also worn by the ClinVar sections and the PGx gene
  faces, so a face-only rule goes on `.cardface`.
- **`nav_page` and `nav_search_landmark`** are set by a page template with `{% with %}` around
  the nav include; they are not context keys, so parity has nothing to place.
- **Not done:** no screen-reader session (NVDA, Narrator) was run; the audit checks markup.
  The theme toggle's new state is not announced when pressed. Data-table captions were not
  added to the HLA, PGx and ClinVar tables that lack one.

<a id="accepted-m147-accessibility"></a>

## Accepted M14.7 accessibility pass

Implemented on 2026-11-20. No owner question was asked: WCAG 2.2 AA decides each point, and
[the accessibility section](agent_cli.md#accessibility-m147) gives the reasoning.

- **Audited, not eyeballed.** `genetics.testing.accessibility.audit` parses a page and lists
  duplicate or dangling ids, unnamed links, buttons and images, unlabelled controls,
  focusables inside an image or hidden subtree, positive `tabindex`, the `h1` count and
  skipped heading levels in `main`, and landmarks of one role a screen reader cannot tell
  apart. It runs on fourteen addresses of a whole-pack run, every card's page and dialog
  (over a hundred), and the drawn ancestry scatter; a test feeds it one bad shape per rule.
- **Contrast computed.** Every text pair met 4.5:1 already and is now held to it in the light
  theme and both dark copies; form-control edges were about 1.3:1 and are 3.6:1 or more
  with `--control-line`; the two dark palettes must be equal.
- **Keyboard.** Arrow keys on the run selector and the group and sort selects no longer
  navigate (WCAG 3.2.2); Enter, Open and Apply do. The skip link moves focus. A card is
  one Tab stop named by its title, with a focus ring round the face. Checked in Chrome:
  arrow then Enter on the sort select, Enter and Escape on a card (focus into the dialog and
  back to the link).
- **Screen-reader labels.** Card links named by title and described by tier; counts read as
  "3 of 10 card(s) interpreted"; the theme toggle named by what it shows; "Close card"; one
  search landmark on the search page; `aria-current` on the nav link of the page shown; the
  guide's nav named "On this page"; a hidden `h1` on the dashboard and the card page; the
  ancestry scatter a named group whose six focusable points are named images; the
  `empty-query` sentence's backticks shown as code.
- **Guards.** Thirteen were removed in turn (the control-edge token and rule, the main's
  `tabindex`, the scatter's role, the search page's landmark, a select's key handler, the
  keyed guard in `app.js`, the toggle's label, the card link's description, the count's
  words, `codespans`, `aria-current`, and a face whose heading holds more than its link);
  each failed a test.

Changed for a caller: none. No command, agent schema, bundle format, knowledge schema, card,
route, view field or context key changed. Validation on 2026-11-20: the full native suite
passed **4,497 tests with nine skips** in 1,034 s (42 new). Strict mypy, ruff and format
pass. No personal export or saved real run was opened. Python source changed, so saved runs
repeat their deep checks once.

The [M14.7 diff review](review_m147_session.md), after the commit, found that the face's new
layout had been put on `.card`, which the ClinVar sections and the PGx gene faces also wear;
it now sits on `.cardface`. It also fixed a stylesheet test helper that matched the wrong
rule, the audit's handling of an SVG `<title>`, and three comments that still gave "a face
is one link" as the reason the legend is not on the faces.

<a id="next-open-step-m147-accessibility"></a>

## M14.7 entry contract (implemented; retained for review)

M14.7: accessibility pass: keyboard navigation, contrast, screen-reader labels. Nothing has
been selected or verified beyond what is listed here.

What earlier milestones hand over:

- **M14.6:** a section's assay limits are a `p.limits` line of links at the panel's head
  (not a list) and a `ul.cards` labelled by the `h3.limitshead` "What this array cannot
  determine"; card titles in that block are `h4` (`_cardface.html` takes `card_heading`,
  default `h3`). Elsewhere a card title is `h3` under the panel's `h2`; on the search page
  it is `h3` too, and that page's heading structure was not checked.
- **M14.5:** the QC page's tables have captions and row headers; its "On this page" list
  is a `nav` landmark, a second one beside the section nav.
- **M14.4:** the search page has two `role="search"` forms, the nav's and the page's, whose
  labels say the same thing, so a screen reader lists two identical search landmarks. The
  `empty-query` sentence the page shows is the CLI's and keeps its backticks around
  `curly hair`.
- **Parity.** A view field added for M14.7 needs a place in `parity`'s tables; a property,
  a row in `parity.PROPERTIES`.

<a id="accepted-m146-impossibility-cards"></a>

## Accepted M14.6 impossibility cards in their sections

Implemented on 2026-11-20. No owner question was asked: the entry contract's open points
were facts to check, and [the section on assay limits](agent_cli.md#assay-limits-in-their-sections-m146)
gives the reasoning for each choice.

- **What the grid did.** Sorted by tier (the default), a card with no tier goes last, so an
  assay limit sat beneath every marker-absent card of its section. Grouped by tier, all
  twelve sat in the untiered panel among the cards that did not match. A tier, section or
  "only interpreted" filter hid them, counted, while the section's findings stayed.
- **Named at each section's head, whatever the filter.** `reads.assay_limits(section,
  cards)` lists the run's impossibility cards saved in the section, in saved order, then the
  current pack's impossibility cards for the section that the run holds nowhere, with
  `in_run: false`. `section_context` carries it as `assay_limits`; the grid's
  `CardGroup.limits` (`LimitLink`: id, title, url or None) draws it as a line of links. The
  line points and does not copy, so a filter still hides and counts the card (M4.7).
- **Their own block.** `CardGroup.findings` and `CardGroup.limit_cards` split the shown
  cards; the template renders the limits below the findings under "What this array cannot
  determine". Grouped by tier, the untiered panel does the same.
- **The register.** AGENTS.md §3.2's eight bullets and the twelve cards match both ways;
  `tests/engine/test_impossibilities.py` already held that. None is missing.
- **Parity.** `ARRANGED` has `CardGroup.limits` and `LimitLink`; `_check_grid` compares each
  section panel's limits with `assay_limits` and fails a tier group that has any. A guard
  test that drops a link fails it.

Changed for a caller: agent schema version 10 (`section_context.assay_limits`, required);
`runs show --section`'s text form prints a "Not determinable from this array" line. No
route, bundle format, knowledge schema or card changed.

Looked at in Chrome on a synthetic run (pack markers, half dropped), grouped by section and
by tier. Validation on 2026-11-20: the full native suite passed **4,455 tests with nine skips**
in 991 s. Five guards were removed in turn and each failed a test, after the
[session review](review_m146_session.md) added the assertion one of them lacked. Strict mypy,
ruff and format pass. No personal export or saved real run
was opened. Python source changed, so saved runs repeat their deep checks once.

Left for later: grouped by tier, the limits block follows the reader's sort (by title,
since every limit ties on tier), not section order; each card names its section.

<a id="next-open-step-m146-impossibility-cards"></a>

## M14.6 entry contract (implemented; retained for review)

M14.6: impossibility cards surfaced in their relevant sections, not hidden in an appendix.
Nothing has been selected or verified beyond what is listed here.

What already exists:

- **Twelve impossibility cards** in `knowledge/impossibilities/`, each assigned to a section:
  three in ancestry (Y-STR haplotypes, mtDNA heteroplasmy, relative matching), five in
  physical health (methylation and epigenetic age, somatic variants, telomere length,
  de novo mutations, RhD zygosity), two in reproductive (SMN1, alpha-globin deletions), one
  in genome structure and one in pharmacogenomics (CYP2D6, placed beside the PGx calls at
  M10.3). They render in their section's grid as cards of kind `impossibility`, with no
  tier ("No tier"), and the reading guide lists them by section (M14.3).
- **The ancestry section holds only assay-limit cards**, and M14.1's empty state says so.
- **The QC page (M14.5)** and the reading guide name the array's limits; neither lists a
  section's impossibility cards beside its findings.

What is open:

- Whether "surfaced" needs more than the grid already gives. Not checked: where an
  impossibility card lands when the grid is grouped or sorted by tier, and whether it then
  sits apart from its section's findings.
- Whether every AGENTS.md §3.2 register entry has its card; compare the register with the
  twelve before deciding that none is missing.
- **Parity.** A new view field needs a place in `parity`'s tables; a new page needs the
  five places M14.2's hand-over lists.

What M14.5 hands over:

- **`dig` is a template global** (`views.dig`): a saved record's nested field, or None where
  another version wrote a different shape. Use it for saved records; context keys stay
  strict.
- **`_render(..., scanned=True)`** scans the whole page for genotypes, for a page that holds
  none. The QC page is the only one that does.
- **A page that shows a command's document whole** is placed with `parity._whole(command,
  document)`, which compares every key and fails on one the page lacks.
- **Agent schema version 9.** A shape change takes version 10, by M14.2's steps below; the
  shape digest is printed by `tests/test_agent_schema.py::_shape_digest(contract.document())`.
- **For M14.7 (accessibility):** the QC page's tables have captions and row headers; its
  "On this page" list is a `nav` landmark, a second one beside the section nav.

<a id="accepted-m145-qc-provenance-page"></a>

## Accepted M14.5 QC and provenance page

Implemented on 2026-11-20. No owner question was asked: each open point of the entry
contract follows from something already settled, and
[the QC page section](agent_cli.md#qc-and-provenance-page-m145) gives the reasoning.

- **A page per run, linked from every run page's nav.** `/runs/{run_id}/qc` shows two
  documents whole: `reads.qc_view` (`runs qc --json`) and `reads.imputation_view` (`runs
  imputation --json`). The parity check compares each with its command, key for key, and
  visits the page on every saved run it checks: the plain one, the placed-score run
  (`tests/refs/test_pgs_cards.py`) and a recorded-imputation run
  (`tests/run/test_imputation_snapshot.py`).
- **Coverage stats means both records, kept apart.** `runs qc` gains `current_context.coverage`
  (`reads.coverage_report`): every polygenic card in saved order, placed or not, with its
  saved `phase_coverage` (original array and after imputation) and comparable weight, and
  the saved ClinVar coverage record. `clinvar_status` names four states, because a low-level
  writer saves a lookup that did not run, which is not the same as one saved before format
  13. Nothing is recounted. Agent schema 9; the text form prints the same.
- **Imputation is summarised, not paged.** A run has about 25 regions (one per autosome and
  X's split), so the page gives the requested parameters, a row per region (status, ploidy,
  typed positions, outcome counts) and a row per job (interval, seed, threads, heap, each
  Beagle run's time). Each region's position-level `decisions` and every digest stay in the
  command's document.
- **Scanned whole.** The page holds what two scanned commands print, so `_render` scans it;
  a test injects a genotype-shaped warning and gets a 500 whose body does not hold it.
- **Read defensively.** Every saved record is read with `dig`; a test renders a sparse
  record and gets `-` and each "not recorded" sentence.

Changed for a caller: agent schema version 9 (`runs.qc` gains `current_context`); a new
route and a nav link on every run page. No bundle format, knowledge schema or card changed.

The [M14.5 session review](review_m145_session.md) gave a ClinVar lookup that did not run
its own state (it was first called "saved before format 13") and fixed two layout faults
found in the browser. Five guards were removed in turn and each failed a test. Validation on
2026-11-20: the full native suite passed **4,435 tests with nine skips** in 1,024 s and
failed one, a walk-through pin on the number of `runs qc` keys it names, since updated;
that file and three parity tests added after the run pass. Strict mypy, ruff and format
pass. No personal export or saved real run was opened. Python source changed, so saved runs
repeat their deep checks once.

<a id="next-open-step-m145-qc-provenance-page"></a>

## M14.5 entry contract (implemented; retained for review)

M14.5: a QC / provenance page showing reference versions, tool versions, imputation
parameters and coverage stats. Nothing has been selected or verified beyond what is listed
here.

What already exists:

- **The commands.** `genetics runs qc <run> --json` prints the saved QC report, the
  imputation execution record, the imputation provenance status and the manifest's
  `provenance` (knowledge pack, references from the lock, tools), from `reads.qc_view`.
  `genetics runs imputation <run> --json` prints the execution record and full imputation
  provenance (`reads.imputation_view`). A page built from those two needs no new payload.
- **The banner.** `views.QCBanner` already shows a slice of both on every run page: vendor,
  markers, call rate, sex, duplicates, build verdict, warnings, imputation mode, status,
  panel and Beagle versions. `parity.BANNER` places each field.
- **Per-card coverage** is on the polygenic cards (`computation.result`), not in a run-wide
  record.

What is open:

- What "coverage stats" means for a run as a whole: per-score coverage collected from the
  polygenic cards, ClinVar position coverage, or both. Each comes from a different saved
  record.
- **The real imputed run's provenance is large** (per-region parameters): whether the page
  pages it, as `/clinvar` pages loci, or summarises it.
- **Parity.** A new route needs a `parity.PAGES` row, a `parity.CONTEXT` table and a visit
  in `check_run`. A page holding no run is visited before the run page (see M14.3's
  hand-over below), a page of the run after it.

What M14.4 hands over:

- **`_open(run_id, query)` in `web.app`** returns the shell and the bundle it was built
  from. A route that calls a `reads` function on the bundle uses it rather than opening the
  run again.
- **The nav has a form first** (`.navsearch`). A test that takes the first `<form>` on a run
  page now gets the search box; find a form by its class.
- **A page whose route takes a query string** is visited in `check_run` with fixed values:
  the search page uses the first card's title, `parity.SEARCHED` and `parity.refused_query()`.
- **`Documents.refusal(*args)`** returns the error document a command prints when it exits 2,
  for a page that refuses what a command refuses.
- **For M14.7 (accessibility):** the search page has two `role="search"` forms, the nav's and
  the page's, whose labels say the same thing, so a screen reader lists two identical search
  landmarks. The `empty-query` sentence the page shows is the CLI's and keeps its backticks
  around `curly hair`.

<a id="accepted-m144-global-search"></a>

## Accepted M14.4 global search

Implemented on 2026-11-19. No owner question was asked: each open point of the entry
contract follows from something already settled, and
[the dashboard search section](agent_cli.md#dashboard-search-m144) gives the reasoning.

- **A page per run, a box in every open run's nav.** `/runs/{run_id}/search?q=<query>`
  searches the open run's cards. The box is at the top of the nav on every page of an open
  run. A page with no run open has no box: there is nothing of a run to search, and a pack
  card has no page to link to (`genetics cards search` covers the pack).
- **One function.** The route calls `reads.search_view(bundle, parse_query(q))`, which is
  what `runs search <run> <query> --json` prints without `--limit`. The parity check
  compares the page's document with the command's, key for key, and the faces shown with
  the command's `results`, in order.
- **Faces as the grid shows them**, tier badge first, from the run's own `CardView`s. Full
  matches are listed under "Matching every word" and partial ones below them under
  "Matching some of the words"; each says which of the query's words it matched in which
  fields. Every section is searched whatever the grid's filters say, and no card is ranked
  or left out for its tier or status. The grid's arrangement rides along in hidden fields.
- **A refused query.** The route catches `QueryError` and hands the template only the
  engine's sentence, which names the rule and never the text; the query itself is never
  handed to the template. The box is left empty and the title never holds a query. The page
  answers 200, as every page that explains why it shows nothing does; the command exits 2.
  The parity check compares the page's sentence with the error document `runs search`
  prints for the same query, and fails if the query's rsID appears on the page.
- **A blank box** (whitespace only) shows the prompt rather than the `empty-query` sentence:
  submitting an empty box is not a malformed query. A query of punctuation alone gets the
  `empty-query` sentence, as the command gives it.

Changed for a caller: a new route and a form at the top of every open run's nav. No command,
agent schema, bundle format, knowledge schema or card changed.

The [M14.4 session review](review_m144_session.md) found, in the browser, that the matched
line overflowed its grid cell onto the next panel, and fixed it. Nine guards were removed in
turn and each failed a test. Validation on 2026-11-19: the full native suite passes **4,426
tests with nine skips** in 962 s; the overflow fix and its test landed during that run, and the
web, parity and walk-through suites pass on the final tree (326 tests). Strict mypy on four
targets, ruff and format pass. No personal export or saved real run was opened. Python source
changed, so saved runs repeat their deep checks once.

<a id="next-open-step-m144-global-search"></a>

## M14.4 entry contract (implemented; retained for review)

M14.4: global search across cards on the dashboard. Nothing has been selected or verified
beyond what is listed here.

What already exists:

- **The ranking and its command (M13.3).** `genetics.run.reads.search_view` is what
  `genetics runs search <run> <query> --json` prints: hits ranked by words matched, then
  score, each naming its matched fields, with each card's saved face. A query that reads
  as a genotype is refused before anything is read (`contract.search_query`, kind
  `genotype-in-query`). Call the same function so the two rank identically.
- **`cards search`** ranks the knowledge pack alone with `engine.search.pack_view`; the
  guide page (M14.3) holds no run and is the one page where a pack search could sit.

What is open:

- Where the box sits (the nav, the controls, or a page of its own), and whether a search
  is of the open run only.
- **A refused query on the dashboard.** The CLI exits 2 and prints nothing of the query;
  a page has to say why it shows no results without echoing the query back.
- **Parity.** A new route needs a `parity.PAGES` row and a visit in `check_run`; a query
  string in the route needs a fixed query in the visit.

What M14.3 hands over:

- **Every page rendered through `_render` gets `legend`** (the nav's confidence legend),
  and `_FRAME` places it, so a new page template that extends `_FRAME` needs nothing more
  for it.
- **A page that holds no run** is built like `/guide`: a shell from `store.list_runs`
  alone, `views.shell_for(listing, None)`. The run selector then shows "Open a saved run".
  In `check_run` such a page is visited after `/` and before the run page, and
  `tests/test_parity.py::test_a_page_whose_shell_is_not_the_compared_one_fails` counts
  shells in the order they are built: a page visited earlier moves its index.
- **Agent schema version 8** (`contract.AGENT_SCHEMA_VERSION`). A new payload takes
  version 9, by the steps M14.2's handoff gives.
- **Tier words** are `genetics.run.guide.TIER_LABELS`, `TIER_BLURBS`, `NO_TIER` and
  `NO_TIER_LABEL`; `web.views` re-exports the same objects.

<a id="accepted-m143-reading-guide"></a>

## Accepted M14.3 reading guide

Implemented on 2026-11-19. No owner question was asked.

- **A page and a command:** `/guide`, linked from every page's nav, and `genetics cards
  guide [--json]`, which prints the document the page shows
  (`genetics.run.guide.reading_guide`). Agent schema version 8 (`cards.guide`).
- **Five parts:** the six badges and what earns each; how a tier is decided (the six
  inputs and weights, the bands, every ceiling); why rarity lowers confidence (the
  frequency components and both published benchmarks); what a polygenic score can say
  (coverage, portability, within-family attenuation, position not prediction, with the
  pack's polygenic cards); and what the array cannot tell (six limits and the pack's
  impossibility cards by section). Sources name each quoted figure's paper.
- **No threshold is written twice.** `engine/confidence.py` gained `FREQUENCY_SCORES`,
  `QUALITY_CEILINGS`, `SHARE_CEILINGS`, `EVIDENCE_SCORES` and `REPLICATION_SCORES`, which
  the calculators read and the guide reads. Ceilings are listed by calling
  `single_call_ceilings` and `polygenic_ceilings`; a test over a grid of inputs fails on
  any ceiling the guide does not list. `engine.ppv.benchmark` gives the two benchmarks a
  ClinVar record carries. No tier changed.
- **Figures quoted** were read from the PubMed abstracts on 2026-11-19: Weedon et al. 2021,
  Tandy-Connor et al. 2018, Okbay et al. 2022 and Ding et al. 2023.
- **The legend** is the card faces' own badges, in every page's nav, each linking to
  `/guide#tier-<key>`; the grid's tier headings and the card page's "Why this tier" link
  into the guide. The faces do not, being one link each already.
- **The guide page opens no run.** Its shell is built from the run listing.

Changed for a caller: agent schema version 8; a new nav section on every page; the run
selector's "Open a saved run" option on a page with no run selected. No bundle format,
knowledge schema or card changed.

The [M14.3 session review](review_m143_session.md) corrected what the guide said about
ancestry ceilings on membership-compared cards and one sentence of Tandy-Connor's figure,
and gave the run selector an "Open a saved run" option. A second pass after the commit
corrected the guide's description of the polygenic chart (a 95% band, never a point) and of
`Indel excluded`, and brought `agent_schema.md` up to version 8. Validation on 2026-11-19: the full
native suite passes **4,412 tests with nine skips** in 977 s; strict mypy, ruff and format
pass. No personal export or saved real run was opened. Python source changed, so saved runs
repeat their deep checks once.

<a id="next-open-step-m143-confidence-legend"></a>

## M14.3 entry contract (implemented; retained for review)

M14.3: a confidence legend and a "how to read these results" page covering the
rarity inversion, PRS attenuation and array limitations. Nothing has been selected or
verified beyond what is listed here.

What already exists:

- **Five tiers and "no tier"** (`engine.confidence.ConfidenceTier`), each with a label and
  a blurb in `web.views` (`_TIER_LABELS`, `_TIER_BLURBS`), shown as group headings when the
  grid is grouped by tier.
- **`runs card` prints the whole confidence block** (M13.4): each input's weight and what
  it cost, every ceiling and which set the tier. The dashboard's "Why this tier" prints
  the reason and six rows, not the weights or the ceiling list; the polygenic partial
  prints only the ceilings that lowered the tier. M13.4 left giving the pages the block
  to here.
- **The figures the page must give exist in the pack and the engine:** the frequency
  bands and empirical PPVs of §4.1 (Weedon 2021; `docs/health_frequencies.md`), the
  within-family attenuation of §4.5, the PRS coverage and portability inputs.

What is open:

- **A new page needs a command** (`tests/test_parity.py`). The legend and the guide hold
  no run, so a pack- or engine-only command would serve, under `cards` or its own name.
- **A new field of a view held inside a card needs a key in `parity.READ`** or a reason
  in `parity.APART`; a seventh confidence row needs `parity.CONFIDENCE_ROWS`.
- Where the legend sits: on every run page, or once with links from each tier badge.

What M14.2 hands over:

- **A new page touches five places in `genetics.testing.parity`**, as the ancestry page
  did: a `PAGES` row naming its command; a `Documents` property that runs the command; a
  `CONTEXT` entry for its template (start from `_FRAME`); a `SHELL` entry for any field
  added to `Shell`; and a `check(...)` visit at the end of `check_run`. `check_run` visits
  pages of one run. A page that holds no run is visited like `/healthz` and `/` near the
  top of `check_run`, not in the list of run pages at its end.
- **The agent schema is version 7** (`contract.AGENT_SCHEMA_VERSION`). A new payload takes
  version 8: bump the constant and the document's `version`, add the digest to
  `SHAPE_DIGESTS` in `tests/test_agent_schema.py`, and add a row to the history in
  [agent_schema.md](agent_schema.md#version-history). Edit `agent_schema.json` as text: it
  is hand-formatted, and `json.dump` rewrites every line.
- **Bundle format 29.** A page that only explains needs no format change. A format change
  means updating the `BUNDLE_FORMAT_VERSION` assertions across the suite (M14.2 changed
  seven test files).
- **Run-page nav links** are in `templates/_sectionnav.html`; the ancestry link was added
  there. A legend reached from every tier badge needs no nav link.
- **Colour tokens** for both modes are on `:root` in `static/app.css`: `--tier-*-bg` and
  `--tier-*-ink` for the six tier badges, and `--pgs-bar`/`--pgs-band`, the two hues the
  polygenic chart and the ancestry scatter share. A legend shows a tier with the badge
  markup the card face uses (`<span class="tier tier-{{ key }}">`), not new hues.

<a id="accepted-m142-ancestry-visualisations"></a>

## Accepted M14.2 ancestry visualisations

Implemented on 2026-11-19. No owner question was asked.

- **A page and a command:** `/runs/{run_id}/ancestry`, linked from the nav of every run
  page, and `genetics runs ancestry <run> [--json]`, which prints the record and the
  scatter the page draws (`reads.ancestry_report`). Agent schema version 7.
- **The run is drawn against its own reference.** Bundle format 29: the ancestry record's
  placement holds the model's `scale`, and each fit its population's `centroid`, in the
  units distance is measured in. A test checks the distance from the scaled sample to each
  centroid equals the saved distance. Writing it found that the cross join in
  `populations.place_many` suffixes the centroid columns, so a first version saved the
  sample's own coordinates as every centroid; the test caught it.
- **Older runs are not drawn against today's reference.** A run saved before 29 lists its
  fits by rank and says why there is no scatter; a format before 29 that claims positions
  is refused.
- **Three marks, two validated hues, no region colours**, per the dataviz rule for
  scatters. Only the nearest population and the run are labelled; every point has hover
  text, and the table is the table view. Rendered and looked at with 100 invented
  populations, in dark mode.
- **Haplogroups show both counts** of §4.7, and ancient affinity is called affinity.

Changed for a caller: bundle format 29 (a previous reader refuses it), agent schema 7, a
new nav link. No knowledge schema or card changed. No personal export or saved real run
was opened.

The [M14.2 session review](review_m142_session.md) records the centroid bug the tests
caught, and limited tab stops to the five nearest populations and the run. Validation on
2026-11-19: the full native suite passes **4,387 tests with nine skips** in 765 s; strict
mypy, ruff and format pass. Python source and the bundle format changed, so saved runs
repeat their deep checks once, and a run saved before format 29 has no scatter until it is
run again.

<a id="next-open-step-m142-ancestry-visualisations"></a>

## M14.2 entry contract (implemented; retained for review)

M14.2: a PCA scatter with reference populations, ancient affinity, and a haplogroup display
with marker counts. Nothing has been selected or verified beyond what is listed here.

What already exists:

- **The ancestry record is saved with every run** (`bundle.ancestry`, M5.8) and printed
  whole by `runs show --json`. It holds the placement (status, reason, the sample's
  scaled coordinates, every reference population's fit with distance, radius and
  percentile, the decline threshold, the panel and its gaps), the mt and Y lineages
  (haplogroup, depth, supporting and contradicting markers, markers on the array and
  typed, why the walk stopped, the path), and ancient affinity (groups with distances,
  dates and sizes, the spread, coverage).
- **No page shows it**, and no command prints it on its own. The ancestry section holds
  three assay-limit cards; M14.1's empty state says so.

What is open:

- **A scatter needs the reference populations' positions, and the run did not save
  them.** The fits hold distances, not coordinates. Reading the reference on disk at
  render time would draw a saved run against whatever reference is installed now.
- **Parity:** a new page needs a command that prints what it shows (`tests/test_parity.py`).
- **Runs saved before the change** have no positions; the page has to say so.

<a id="accepted-m141-sections-and-empty-states"></a>

## Accepted M14.1 sections and empty states

Implemented on 2026-11-19. No owner question was asked.

- **All thirteen sections were already wired** (M4.5): the nav and the grid render every
  one whatever a run holds. What M14.1 changed is what an empty one says.
- **One function, three sentences:** `reads.empty_reason(cards, pack_count)`.
  `reads.empty_reasons(cards)` gives all thirteen from one run's cards and the committed
  pack's per-section counts (`reads.pack_section_counts`, cached for the process).
  - No card in the run: it was saved with a pack that held none here; the current pack's
    count is what a new run would show; nothing about the genome is implied.
  - Cards, none interpreted: each status counted by its label (the labels moved from
    `web.views` to `reads.STATUS_LABELS`), each distinct `not_run` reason quoted up to
    three, and a section of assay limits says so. A failed match's reason is about the
    call and stays on the card; a quoted reason that reads as a call is dropped.
  - No run open: `views.NO_RUN_REASON`, which claims nothing about a run.
- **The nav, the grid and `runs show --section` print the same sentence.**
  `SectionView.empty_reason` is a field now, and `CardGroup.section_reason` carries the
  section's sentence; the parity check compares both with the command.

Changed for a caller: `runs show --section`'s `empty_reason` text. No schema shape, bundle
format, knowledge schema or card changed.

The [M14.1 session review](review_m141_session.md) made `runs show --section` compute only
its own sections' sentences. Validation on 2026-11-19: the full native suite passes
**4,378 tests with nine skips** in 746 s; strict mypy, ruff and format pass. No personal
export or saved real run was opened. Python source changed, so saved runs repeat their deep
checks once.

<a id="next-open-step-m141-sections-and-empty-states"></a>

## M14.1 entry contract (implemented; retained for review)

M14.1: all thirteen sections wired, each with an explicit empty state explaining *why* it
is empty when it is. Nothing has been selected or verified beyond what is listed here.

What already exists:

- **All thirteen sections render** in the nav and the grid whatever a run holds (M4.5,
  `views.section_views`, `_section_groups`), and an empty one carries a sentence from
  `reads.empty_reason`, which `runs show --section` prints too.
- **That sentence is out of date.** For a section with no card it says "Not built yet —
  roadmap M…", and since M12 every section has cards in the committed pack. A run with no
  card in a section was saved before the pack had them, or with a pack that held none. For
  a section whose cards all failed to interpret it says only that each card states its
  reason.
- **The parity test compares the nav's and the grid's sentence with `runs show
  --section`.** A changed sentence has to come from one function.

What is open:

- What a total-zero section says now that every section is built.
- How much of the cards' statuses an empty section summarises, and which reasons it may
  quote. A `not_run` card's reason is the engine's own sentence; a failed match's is about
  the call.
- The ancestry section holds three assay-limit cards and no result: the ancestry analysis
  is a run-wide record no page shows. M14.2 gives it a page.

<a id="accepted-m137-outbound-query-lint"></a>

## Accepted M13.7 outbound-query lint

Implemented on 2026-11-19. No owner question was asked: the entry contract's open points
are settled in [the Query check section](agent_cli.md#query-check-m137)'s Decisions.

- **What there is to lint:** a command, `genetics cards check-query <query> [--card ID]
  [--json]`, because the engine builds no web search and an agent writes its own. It reads
  the pack only, exits 1 on `refused`, and never prints the query.
- **Shapes and sources, both.** Eight rules on `genetics.outbound`: three `call` rules (the
  privacy scanner's shapes, an rsID beside two alleles, a diplotype) and five `result`
  rules (zygosity, a count of copies, the first person, a run id, a confidence tier). With
  `--card`, every query word the cards' evidence does not print is listed as `unsourced`.
  That is advice: a word from a cited paper is fair to search.
- **The two queries M13.6 left open are refused**, and the walk-through's test asserts it.
- **The search commands refuse the call rules** (`engine.search.parse_query` calls
  `outbound.reads_as_call`) and still search result words.
- **The engine's own requests are checked.** The fetcher calls `outbound.check_url` before
  each request, and a test reads the source for every request a module builds.
- **Where §1.3 is reinforced:** AGENTS.md §1.3 itself now says to run every outbound query
  through the check and that its rules are a floor; §3 and the walk-through repeat it.
- **The hosted-agent reading stays as M13.6 wrote it**, still unconfirmed by the owner.

Changed for a caller: agent schema version 6 (one payload, `cards.check-query`, and the
`query_rule` vocabulary). `cards search` and `runs search` refuse an rsID beside two
alleles, which they searched before; write a variant's alleles as `C>T`. No bundle format,
knowledge schema or card changed.

The [M13.7 session review](review_m137_session.md) closed two bypasses (full-width
characters, punctuation between the rsID and the pair), stopped listing question words as
unsourced, and pointed the zygosity advice at DOIs after finding that one cited title in
the pack holds "Homozygous".

Validation on 2026-11-19, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle
tools configured: the full native suite passed 4,358 tests with nine skips in 778 s before
the review, and **4,365 with nine skips** in 752 s after it. Strict mypy, ruff and
format pass.

**Saved runs repeat their deep checks once**, since Python source changed.

<a id="next-open-step-m137-outbound-query-lint"></a>

## M13.7 entry contract (implemented; retained for review)

M13.7 reinforces AGENTS.md §1.3 (an agent researches the variant, never the reader's
genotype at it) and adds a lint or test for genotype strings in outbound query
construction. Nothing has been selected or verified beyond what is listed here.

What already exists:

- **A scanner with five shapes.** `genetics.privacy` recognises an export row in three
  separator forms, an identifier with a call attached by a colon or equals sign, and keyed
  fields. `assert_no_genotype` names outbound web queries as one of its boundaries.
- **Two commands that refuse a genotype as a query.** `cards search` and `runs search`
  check the query with that scanner before anything is read (`engine/search.parse_query`,
  kind `genotype-in-query`).
- **A stated rule.** [The walk-through](agent_usage.md#what-may-leave-the-machine) says
  that whatever leaves the machine is written from `cards` output and from papers already
  read, and that each query is written as if the result were unknown.
- **One test of that rule, on four example queries.** `tests/test_agent_usage.py` checks
  that every word of each example query is a word `cards evidence --json` prints for the
  card, and that a query holding the run's call, its tier or the word "heterozygous" is
  not.

What is open:

- **What there is to lint.** The engine builds no web search. Its only network path is
  `refs/fetcher.py`, which downloads the manifest's pinned URLs. An agent builds its own
  queries outside this code. The lint needs something of the engine's to stand on: a
  command an agent passes a query through, a command that prints queries built from a
  card's evidence, or a function the tests hold to the rule.
- **Shapes or sources.** The scanner matches shapes, and a result has shapes it does not
  know: an rsID followed by two bare alleles, a zygosity word, a star-allele diplotype,
  an HLA type, a haplogroup. The M13.6 test checks sources instead (words `cards evidence`
  does not print). Which one M13.7 builds, or both.
- **Two queries neither check catches today.** The marker with "one copy", and the marker
  followed by its two alleles written apart. Every word of each is one the card's
  evidence prints, and the scanner knows neither shape.
  `test_each_example_query_is_written_from_the_evidence_alone` asserts both pass, and
  [the page](agent_usage.md#how-this-page-is-kept-true) says they do. A lint that catches
  either fails that assertion, which is the prompt to correct the page's sentence.
- **Where §1.3 is reinforced.** AGENTS.md §3 now points to the walk-through and repeats
  its rule in a sentence. §1.3 itself is unchanged.
- **A hosted agent reading a run.** §1.3 lists "a prompt to a remote model" among the
  places a genotype must not go, and §0 says an agent can be pointed at a saved run. The
  walk-through settles it as: the owner's request covers the cards asked about, read
  with the narrowest command. The owner has not confirmed that reading.

What M13.6 hands over:

- **The page is tested through markers.** `<!-- run: command -->` before a fenced output,
  `<!-- keys: command -->` before a table of keys, `<!-- queries: card-id -->` before a
  list of queries. A marker with nothing after it, or a sixth marker, fails
  `test_the_page_marks_what_it_shows` until that test lists it.
- **A change to the four hair-curl cards' wording or evidence fails the page's test.**
  That is the prompt to re-read the page's comparison with the papers, which is prose.
  Run the command the failure names and correct the page.
- **`parity.command_problem(command, needs_json=False)`** checks any command line written
  in documentation: the subcommand exists and takes each option written, a flag's off
  form included. It does not check arguments: a missing one or a stray word passes.
- **`ubuntu-latest` is Ubuntu 26.04 now, and the move broke the Linux jobs once.** The run
  of 2026-11-13 used the 24.04 image and the first push of M13.6, on 2026-11-14 UTC, the
  26.04 one. That push failed both Linux jobs in the privacy suite's OS-isolation fixture:
  the image's `sudo` ignores `-E`, so the isolated child lost its environment and the probe
  refused it. `Isolation.command` (`testing/isolation.py`) now asks for the environment
  by name with `--preserve-env`, and the next run passed all five jobs on 26.04. No 24.04
  runner has run that form. `genetics ci-local` cannot reproduce a Linux runner, so
  after a push read both Linux jobs, not only the run's first minutes.
- **`uv run` rewrites `uv.lock`.** The committed lock predates the `jsonschema` and
  `types-jsonschema` development dependencies in `pyproject.toml`, so `uv run` adds them
  and leaves the file modified. CI installs with `uv pip install -e ".[dev]"` and does
  not read the lock. The lock was left as committed; `.venv/Scripts/python -m pytest`
  does not touch it.

What M13.5 hands over:

- **The schema is version 5, with fourteen payloads.** A new key or payload takes version
  6: bump `AGENT_SCHEMA_VERSION` and the document's `version`, add the digest to
  `SHAPE_DIGESTS`, and add a line to the version history in
  [the agent schema](agent_schema.md).
- **A new dashboard route, context key, view field, view property or engine call fails
  `tests/test_parity.py` until it is placed.** The failure says where: a row in
  `parity.PAGES`, a key in `parity.CONTEXT`, a field in a view's table, a name in
  `parity.PROPERTIES`, or a reason in `parity.DISPLAY_ONLY`. M14 adds pages and fields and
  will meet each of these.
- **`parity_check(run)` checks one saved run** against the commands and checks every
  document it reads against the schema. It then changes every value of every card the run
  shows, one at a time, and fails if a change passes the comparison. A suite that builds a
  new kind of saved run should call it, as `tests/hla`, `tests/refs` and `tests/health` do.
- **A new field of a view held inside a card needs a key in `parity.READ`**, the saved key
  it is read from, or a reason in `parity.APART`. A seventh row of the confidence table
  needs a row in `parity.CONFIDENCE_ROWS`. M14.3 (confidence legend) will meet both.
- **What the check does not cover.** A property's arithmetic; a method called on an object
  the page holds; what the CLI prints and no page shows (a card's `ancestry_comparison` is
  the known case); text output; the real imputed run.
  [The parity section](agent_cli.md#parity-m135) lists them.

What M13.4 left:

- **The confidence block is on `runs card` only.** `runs show --section` and `runs search`
  list each card's saved `confidence_tier` and nothing more.
- **The dashboard shows part of the block.** Its "Why this tier" section prints `reason`
  and the six rows for a card with a `confidence` block. It does not print weights, what
  each input lost, or the list of ceilings. Computed and guideline cards keep their own
  detail partials, which print the saved reason. The polygenic partial prints the saved
  score, inputs and ceiling names ("Capped by coverage"), which list only the ceilings that
  lowered the tier in order; `runs card` lists every one by input. M14.3 (confidence
  legend) is the place to give the pages the block. The parity check compares the sentence
  and the saved inputs, which is what the page holds.
- **A ceiling's wording is the engine's.** `Ceiling.rule` in `engine/confidence.py` is
  printed by the CLI and the dashboard. Rewording one changes both and no saved run.

What M13.2 left, for whichever later item needs it:

- **Exit codes outside the read commands.** `run`, `impute` and `serve` exit 2 for every
  failure, not only usage errors.
- **Failures printed as text under `--json`.** `ingest`, `refs`, `tools` and `paths`. `roh`
  has no `--json` flag; it prints its result as JSON and a failure as text.

What M13.3 left:

- **The dashboard has no search yet.** M14.4 should call `reads.search_view`, which is what
  `runs search` prints. Its route then needs a row in `parity.PAGES` naming `runs search`.
  *Done at M14.4: `/runs/{run_id}/search`.*
- **Guideline recommendation rows and saved score records are not searched.** A guideline
  card is found by its gene, title and citation titles. A drug named only in its saved CPIC
  rows is not a search term for the card.
- **The stemmer is a short English suffix list.** `depressed` does not find `depression`,
  and it joins a few unrelated words (`even` and `evening`, `ever` and `every`). Each hit
  says which fields matched, so a miss is visible as a miss and not as a wrong card.
- **A hit does not say how each word matched.** `matched` names fields and words, not the
  quality (exact, stem or prefix) or whether the side-by-side bonus applied.
- **A failed tool download can fail CI.** The first CI run on `a8b80d1` failed two of four
  jobs because the bref3 download returned HTTP 502; re-running them passed. On the
  Windows job the install step did not stop the job, and the failure showed up eight
  minutes later as failing tests. `ci.yml` was not changed.
- **A genotype in a query is whatever `genetics.privacy` recognises.** An rsID followed by
  two bare alleles, with no chromosome, position, colon or equals sign, is not one of its
  shapes. M13.7 owns the outbound-query lint.

<a id="accepted-m136-review-workflow"></a>

## Accepted M13.6 review workflow

Implemented on 2026-11-15 as [Reviewing a run as an agent](agent_usage.md). No owner
question was asked: three of the entry contract's four open points follow something
already settled, and the page's Decisions section lists them. The fourth produced one
reading the owner has not confirmed, which is flagged there and in the M13.7 contract.

- **It lives in `docs/agent_usage.md`, with a pointer in AGENTS.md §3.** AGENTS.md is read
  at the start of every session; the walk-through is several hundred lines.
- **Eight steps, each with its command:** pick the run, check its QC, find the card, read
  the result, read the claim without the result, read the cited papers, search further,
  answer. Then what an answer carries, which command starts each other kind of question,
  and what to do when a step fails.
- **What may leave the machine is stated as a rule about sources.** A table says which
  commands state the reader's results. A search, a fetch or a file is written from `cards`
  output and from papers already read, and each query as if the result were unknown.
- **The example shows real output from a run that is nobody's:** the four hair-curl cards
  and one assay-limit card, matched against an invented table that holds one of each
  allele a card declares.
- **The card was checked against its sources.** Both papers cited by `wnt10a_hair_curl`
  were read in full text from PubMed Central (PMC2891811, PMC5886212). The marker, the
  allele counted, the 0.193 effect and its scale, the sample of 5,385, its ancestry and
  the independent replication all agree with the card. The later paper's lead marker at
  the locus is a different one; the card's note says the locus was confirmed, which is
  what that paper's main text shows. Its Supplementary Table S6 was not opened.
- **Ten facts, each naming the table or section it was read in.** Two figures in them are
  sums this review made from a published table, and say so.

Changed for a caller: nothing. No command's output, schema shape, bundle format, knowledge
schema or card changed. `genetics.testing.parity._command_problem` is now
`command_problem`, with a `needs_json` flag; the parity check's behaviour is unchanged.
No personal export or saved real run was opened: every command ran against a synthetic run
and the committed pack. The requests to NCBI carried a DOI or a PMC number.

Validation on 2026-11-15, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle
tools configured. The full native suite passes **4,294 tests with nine skips** in 1,071 s: the five existing
Windows skips and the four published-classifier HIBAG tests. After that run the page gained
its QC step and the test its check of that step's keys, and documentation changed;
`tests/test_agent_usage.py` was run again and passes. Its 12 tests are the new ones. The
page was changed in ten ways, one at a time (a shown line reworded, the search order, a
key that is gone from each of two tables, a query built from the result, a result command marked safe to send
out, a marker removed, a command that is gone, an option that is gone, the sentence about
a fifth card); each change failed a test. Strict mypy on all four Windows/Linux x Python
3.11/3.13 targets (258 files), ruff and format pass.

**The first push failed both Linux CI jobs, in code M13.6 did not touch.** `ubuntu-latest`
had moved to Ubuntu 26.04, whose `sudo` ignores `-E`. The fix (`dc78ac0`) asks for the
environment by name, two tests pin the command line on every platform, and its CI run
passed all five jobs. The roadmap's progress log has the account.

The [M13.6 session review](review_m136_session.md), on 2026-11-15, re-read the diff and
the CI fix, and read the ten facts again in the papers' saved text. The page had said a
query built from the run's result fails its word check; the marker with "one copy", or
followed by its two alleles apart, passes it and the scanner. The page states that now and
the test asserts it. A new test holds the run status, tier bases, call sources and error
kinds the page names in prose to the agent schema and `contract.run_error_kind`; the
twelve commands written without `genetics` are checked; `command_problem` reads a flag's
off form; fact 7 names where its fourth signal is; and the statements about when the
runner image moved say what the logs show. Fifteen guards or statements were changed in
turn and each failed a test. The full native suite passes **4,297 tests with nine skips**
in 962 s; strict mypy on four targets (258 files), ruff and format pass.

**Saved runs repeat their deep checks once.** M13.6, the CI fix and the review each edit
Python source (`testing/parity.py`, `testing/isolation.py`), so the first read of each
saved run repeats its deep checks (about 54 minutes for the real imputed run). Run
`genetics runs list --verify`, or the launcher's verify-first shortcut, first.

<a id="next-open-step-m136-review-workflow"></a>

## M13.6 entry contract (implemented; retained for review)

M13.6 documents how an agent reviews a run, in `AGENTS.md` or a `docs/agent-usage.md`, with
the worked example from the project brief: *"it says I'm predisposed to curly hair — review
the cited information and give me 10 interesting facts"*.

What already existed:

- **Every command the example needs.** `cards search "curly hair"` finds the card id with
  no run open. `runs card <run> wnt10a_hair_curl --json` gives the saved card, its
  citations with links, and what decided its tier. `cards evidence wnt10a_hair_curl` gives
  the claim with no genotype, which is what a web search starts from (AGENTS.md §1.3).
  `runs qc` and `runs show --section` give the surroundings.
- **A reference for each command, not a walk-through.** [The read-command
  contract](agent_cli.md) says what each prints, and AGENTS.md §3 named the workflow in one
  sentence.
- **A table of which command stands for which dashboard page** (M13.5), in
  [the parity section](agent_cli.md#parity-m135).

What was open:

- **Where it lives.** The roadmap allows either file. AGENTS.md is read first by every
  agent and is already long.
- **Which run the example uses.** The page is public, so it cannot state a real person's
  result. Whether it shows output from a synthetic run, or the commands with no output.
- **Whether the example is tested.** A walk-through whose commands are run by a test stays
  true when a command changes; one that is prose does not.
- **How much of "search the web" it states.** M13.7 owns the lint on outbound queries.
  M13.6 had to say what may be searched without it.

<a id="accepted-m135-parity-test"></a>

## Accepted M13.5 parity test

Implemented on 2026-11-13 under [the parity section](agent_cli.md#parity-m135). No owner
question was asked: each of the entry contract's four open points follows something
already settled, and that section lists them.

- **The check is a library, `genetics.testing.parity`, run by `tests/test_parity.py`.** It
  compares three things, each listed from the dashboard's own code. Routes: all eight are
  in `parity.PAGES` with the commands whose JSON holds what they show. Engine calls: every
  engine function `genetics.web` calls is one the CLI's read side calls, with two stated
  exemptions. Values: for a saved run, every page is rendered through the real app, what it
  hands its template is recorded, and each context key, each `Shell` field and each field
  of every card is compared with what the real commands print.
- **Reachable means in a command's JSON** (AGENTS.md §0). Text output is not compared.
- **The five record commands are described.** `runs clinvar`, `runs secondary`,
  `runs imputation`, `pgx calls` and `hla calls` print the run envelope and a schema tag,
  as `runs.clinvar`, `runs.secondary`, `runs.imputation`, `pgx.calls` and `hla.calls`.
  Agent schema version 5. `reads.py` builds all five.
- **What the check found.** `hla calls --json` did not say whether HLA-linked cards were
  recorded; it now gives `linked_cards_status` and `linked_cards`. The bundle format the
  dashboard's footer shows was in no command; `version --json` gives it. `pgx calls`'
  `current_context` had no `context` key of its own. One engine function,
  `phase_coverage_text`, was called by the dashboard alone, to word saved figures. No page
  showed a value missing from every command.
- **`runs imputation` is scanned.** Its provenance holds no genotype, so both branches are
  checked for one before printing, like `runs qc`.
- **It runs in CI inside the suite.** `tests/test_parity.py` needs no native tool and no
  reference. The same check runs on the saved runs with completed PGx calls, guideline
  cards, HLA calls and cards, a placed polygenic score, a ClinVar lookup with a frequency
  screen, 101 ACMG overlaps over two pages, and three historical formats, through the
  `parity_check` fixture in the suites that build them.

Changed for a caller: the five record commands print `schema`, `path`, `format_version` and
`created_at` under `--json`, and `pgx calls` and `hla calls` print `run_id`; `hla calls`
adds `linked_cards_status` and `linked_cards`; `pgx calls` adds `current_context.context`;
`version --json` adds `bundle_format_version`; every tagged document says `"version": 5`.
No key was removed, and no text output changed. `create_app` keeps its template environment
on `app.state.environment`. No bundle format, knowledge schema, card or saved-file type
changed. No personal export or saved real run was opened; all checks used synthetic runs
and the committed pack.

Validation on 2026-11-13, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **4,273 tests with nine skips** in 874 s: the five existing Windows skips and the four published-classifier HIBAG tests. After that run only documentation changed. The 38 new tests are 34 in
`tests/test_parity.py` and four in `tests/test_agent_schema.py`; nine existing tests in
`tests/hla`, `tests/refs` and `tests/health` now run the check on their saved runs.
Thirty-one guards were each removed in turn. Thirty removals failed a
test; the thirty-first, an unplaced view field passing a run check, did not, and a test now
covers it. Full dbSNP card lint (119 cards, 594 renders, 65/65 keys), strict mypy on all
four Windows/Linux x Python 3.11/3.13 targets (257 files), ruff, format and the fixture
check pass. `genetics ci-local` passed before the push.

The [M13.5 session review](review_m135_session.md), on 2026-11-13, re-read the diff and
changed every value of every card view once. It found three P2 defects in the check
itself, none in a command: nested views and the polygenic view's saved parts were compared
by whether a value appeared anywhere in the record, so 38 of 170 changes to a placed
score's view passed; `ancestry_matched` and a confidence row's saved input were declared
display; and only the run page's shell was compared. All are fixed, with the probe kept as
`parity.unnoticed` and run by the fixture. Nineteen guards were removed in turn, each
caught. The full native suite passes **4,282 tests with the same nine skips** in
898 s; after that run only documentation changed.
Full dbSNP card lint, strict mypy on all four targets (257 files), ruff, format and the
fixture check pass. No command's output, schema shape, bundle format or card changed.

**Saved runs repeat their deep checks once.** This change edits Python source, so the first
read of each saved run repeats its deep checks (about 54 minutes for the real imputed run).
Run `genetics runs list --verify`, or the launcher's verify-first shortcut, first.

<a id="next-open-step-m135-parity-test"></a>

## M13.5 entry contract (implemented; retained for review)

M13.5 is a test that every analysis reachable from the dashboard is reachable from the CLI,
wired into CI.

What already existed:

- **The dashboard has eight routes.** `/`, `/runs/{run}`, `/runs/{run}/cards/{card}`,
  `/runs/{run}/clinvar`, `/runs/{run}/secondary-findings`, `/runs/{run}/hla`,
  `/runs/{run}/pgx` and `/healthz` (`web/app.py`).
- **Pieces of a parity test, not the test.** `tests/test_cli_agent_reads.py` compares every
  section's title, blurb, milestone, counts, empty reason and pointers with the dashboard's
  views. `reads.SAVED_RECORDS` names the command for each record the dashboard links as a
  page. `tests/web/test_dashboard.py` checks that the card page prints the sentence
  `runs card` gives for what decided a tier.
- **Two shared functions.** `reads.empty_reason` and `explain.explain_confidence` are
  called by both front-ends. The dashboard builds its pointers (`views.related_links`) and
  its card views (`CardView.of`) itself; a test compared the pointers with `reads.related`,
  and nothing compared a card view with `reads.card_payload`.

What was open:

- **What "reachable" is checked against.** A list of routes, a list of the view fields each
  page renders, or the functions each page calls. The roadmap line does not say.
- **Which untagged commands need describing.** `runs clinvar`, `runs secondary`,
  `runs imputation`, `pgx calls` and `hla calls` printed saved records the schema did not
  describe. M13.2 left that decision to this item.
- **What the dashboard draws that the CLI only points to.** `runs card` text gives one line
  for polygenic, HLA, runs-of-homozygosity and multi-marker detail and points to `--json`,
  which holds each in full. Whether JSON reachability is enough was this item's call.
- **How it runs in CI.** The roadmap says to wire it in; `ci.yml` runs `pytest -q`, so a
  test in the suite already runs there.

<a id="accepted-m134-machine-readable-confidence"></a>

## Accepted M13.4 machine-readable confidence

Implemented on 2026-11-12 under [the confidence contract](agent_cli.md#confidence-m134). No
owner question was asked: each of the entry contract's three open points follows something
already settled, and that page lists them.

- **One shape, on `runs card`.** `current_context.confidence` has the same twelve keys for
  every card: `source`, `basis`, `tier`, `score`, `score_tier`, `score_bands`, `inputs`,
  `ceilings`, `limiting`, `reason`, `empirical_ppv` and `replay`. It is built when the run
  is read, by `genetics.run.explain.explain_confidence`. The saved card and both places it
  keeps confidence (`confidence` and `computation.reliability`) are unchanged.
- **What decided the tier is stated.** A tier is the weaker of the score's band and every
  ceiling. `basis` says which it was (`score`, `ceiling`, `method`, `not_reproduced`,
  `none`), `limiting` names the inputs whose ceiling is the tier, and each scored row gives
  its weight and what it cost the score.
- **One statement of the ceilings.** `calculate_confidence` and
  `calculate_polygenic_confidence` now take their ceilings from `single_call_ceilings` and
  `polygenic_ceilings`, which the reader calls too. No tier and no saved record changed: a
  test keeps a copy of the earlier rules and compares 22,848 results with it.
- **The reading checks itself.** The saved inputs are replayed. If the tier or the score
  does not come out as saved, the basis is `not_reproduced` and the block says nothing
  about what decided the tier.
- **A card with no tier is covered.** Basis `none`, with the reason it was not scored.
- **Text and dashboard.** `runs card` text prints the block. The dashboard's card page
  prints its `reason` under "Why this tier", from the same function.
- **Schema version 4.** `runs.card` gains the required key; `confidence_explanation` and
  the `confidence_basis` vocabulary are new. No other payload changed.

Changed for a caller: every tagged document now says `"version": 4`; `runs card --json`
has one more key under `current_context`; the "Confidence" lines of `runs card` text are
laid out differently and name inputs by their row names (`evidence_tier`, not
`evidence tier`). No bundle format, knowledge schema, card or saved-file type changed. No
personal export or saved real run was opened; all checks used synthetic runs and the
committed pack.

Validation on 2026-11-12, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **4,229 tests with nine skips** in 835 s: the five
existing Windows skips and the four published-classifier HIBAG tests. After that run only
documentation and two docstrings changed. The 38 new tests are 29 in
`tests/run/test_explain.py`, four in `tests/test_agent_schema.py`, four in
`tests/test_cli_agent_reads.py` and one in `tests/web/test_dashboard.py`; one existing test
each in `tests/hla` and `tests/refs` now checks the block on its saved run. Thirty-five
guards were each removed in turn, and each removal failed a test. Full dbSNP card lint (119
cards, 594 renders, 65/65 keys), strict mypy on all four Windows/Linux x Python 3.11/3.13
targets (255 files), ruff, format and the fixture check pass.

Three things were found by the tests while this was built. The score replay first summed
the unscored `hla_call` row, so no HLA card reproduced. `limiting` was first empty whenever
the score's own band was the tier, which hid a ceiling sitting at that band (a refuted
claim that also scores low); it now names that ceiling and the reason says a higher score
would not raise the tier. And `engine/confidence.py` was CRLF in the working tree (LF in
the index), which six guard removals failed to match; it is LF again. The cause was not
established.

The [session diff review](review_m134_session.md) (`f7f9294..a3d9a47`) found one defect in
the replay. It summed each row's rounded `contribution`, and rounded rows can add up to a
figure 0.0002 from the saved score, past the 0.00015 tolerance: 23 of 20,000 polygenic
scores drawn with arbitrary decimals were reported as `not_reproduced`. The committed grids
used round inputs and could not show it. The replay now sums the saved components times
their weights. The review also stopped a rare call's rate being printed twice, in `runs
card` text and on the card page; added a check of the ancestry-membership rule on a card
saved through the real assembly; and corrected four statements in the docs, one schema
description (wording only, still version 4) and a test docstring. The full native suite
passes **4,235 tests with the same nine skips** in 907 s, with nothing but documentation
and one module docstring changed between that run and the commit. All seven of the
review's guards fail a test when removed. Full card lint (119 cards, 594 renders, 65/65
keys), the four strict type targets (255 files), ruff, format and the fixture check pass.

**Saved runs repeat their deep checks once.** This change edits Python source, so the first
read of each saved run repeats its deep checks (about 54 minutes for the real imputed run).
Run `genetics runs list --verify`, or the launcher's verify-first shortcut, first.

<a id="next-open-step-m134-machine-readable-confidence"></a>

## M13.4 entry contract (implemented; retained for review)

M13.4 is the tier plus the numeric inputs that produced it, so that an agent can explain why
a card is low confidence.

What already existed:

- **The inputs are saved beside the tier (M4.1), in two places by card kind.**
  Interpretation and HLA cards save `confidence`: the tier, the score and six scored inputs,
  each with the value that was scored, and the empirical PPV where one applies. Computed,
  polygenic and guideline cards save `confidence: null` and keep tier, score, inputs,
  ceilings and reason in `computation.reliability`, whose inputs differ by source.
  `confidence_tier` on the card is the tier from whichever applies.
- **The schema describes both as they are** (`confidence` closed key for key,
  `computation.reliability` open), and `runs card` text printed both (the
  [M13.1 review](review_m131_session.md)).

What was open:

- **One shape or two.** Whether an agent reads one block whatever the card's kind, and if so
  where it goes. The saved card is frozen, so a block this engine builds at read time
  belongs under `current_context`.
- **Whether the values are enough.** "Why is this card low confidence" needs to know which
  input or ceiling decided the tier. The six scores are saved; what limited the tier is not
  stated as such for interpretation cards. `computation.reliability.reason` states it in a
  sentence for the others.
- **A card with no tier.** A card with no finding has `confidence_tier: null` and a status.
  Whether "why" covers those.

<a id="accepted-m133-card-search"></a>

## Accepted M13.3 card search

Implemented on 2026-11-12 under [the search contract](agent_cli.md#search-m133). No owner
question was asked: each of the entry contract's three open points follows something
already settled, and that page lists them.

- **Two commands, one ranking.** `genetics cards search <query>` searches the knowledge pack
  and `genetics runs search <run> <query>` searches one saved run's cards. Both call
  `genetics.engine.search.search` over plain `Document` records, which is the function
  M14.4's dashboard search must call.
- **Not a top-level `genetics search`.** The roadmap wrote it that way. M13.1 put pack reads
  under `cards` and run reads under `runs` and declined top-level aliases, and the two
  searches differ in privacy: the pack search holds no genotype and is scanned on both
  branches; the run search carries each card's saved summary and is not, like `runs show`.
- **The ranking is stated and deterministic.** Fourteen fields with fixed weights; a query
  word matches exactly, by stem or as a prefix; cards are ordered by words matched, then
  score, then listing order. Each hit lists the fields that matched. No index, no new
  dependency.
- **Partial matches are ranked, not hidden, and confidence plays no part.** A test changes a
  card's status and tier and checks that the ranking does not move.
- **A query that reads as a genotype is refused** before anything is read or echoed, with
  kind `genotype-in-query`, by both commands (AGENTS.md 1.3).
- **Schema version 3.** Two payloads, `cards.search` and `runs.search`, the `search_field`
  vocabulary and `card_face`. No existing payload changed. In `runs.search` the saved faces
  are under `results` and the query and ranking under `current_context`.

Changed for a caller: every tagged document now says `"version": 3`. No bundle format,
knowledge schema, card or saved-file type changed. No personal export or saved real run was
opened; all checks used synthetic runs and the committed pack.

Validation on 2026-11-12, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **4,183 tests with nine skips** in 842 s: the five
existing Windows skips and the four published-classifier HIBAG tests. Nothing but
documentation changed between that run and the commit. An earlier run was stopped at about
30% (no failures by then) so that the guard checks could run on a quiet tree. The 99 new
tests are 58 in `tests/engine/test_search.py`, 36 in `tests/test_cli_search.py` and five in
`tests/test_agent_schema.py`. Twenty-four guards were each removed in turn. Twenty-three
removals failed a test. The twenty-fourth, the side-by-side bonus set to zero, passed,
because its test compared the score with the constant itself; the test now also checks the
order, and a new test pins the weights and qualities the documentation states. Full dbSNP
card lint (119 cards, 594 renders, 65/65 keys), strict mypy on all four Windows/Linux x
Python 3.11/3.13 targets (253 files), ruff, format and the fixture check pass.

**Saved runs repeat their deep checks once.** This change edits Python source, so the first
read of each saved run repeats its deep checks (about 54 minutes for the real imputed run).
Run `genetics runs list --verify`, or the launcher's verify-first shortcut, first.

The [session diff review](review_m133_session.md) (`96760e0..a8b80d1`) found two defects in
the ranking. The stemmer took a final `e` or `y` off four-letter words, so `note` became
`not` and `cards search note` listed 109 of 119 cards; it now needs five letters, and the
same search lists 3. The side-by-side bonus compared only the searched terms, so text
saying "risk of heart disease" earned nothing for that query; it now compares the query as
typed. The review also documented `--` for a query word that starts with a hyphen,
corrected four statements in the docs and one docstring, and added the bonus to the
schema's description of `score` (wording only, still version 3). The full native suite
passes **4,191 tests with the same nine skips** in 748 s, with nothing but documentation
changed between that run and the commit. All 27 guards, three of them new, fail a test
when removed. Full card lint (119 cards, 594 renders, 65/65 keys), the four strict type
targets (253 files), ruff, format and the fixture check pass.

<a id="next-open-step-m133-card-search"></a>

## M13.3 entry contract (implemented; retained for review)

M13.3 is `genetics search <query>` across cards, so that an agent can find "curly hair"
without knowing the card id. Nothing has been selected or verified beyond what is listed here.

What is open:

- **What it searches.** The knowledge pack (titles, genes, traits, variants, caveats), a saved
  run (the cards that run holds, with their results), or both. A pack search holds no
  genotype and can be scanned, like `cards evidence`. A run search states results, like
  `runs show`. The roadmap line does not say which.
- **Where it lives.** The roadmap writes it as top-level `genetics search`. M13.1 put
  run-scoped reads under `runs` and pack reads under `cards`, and declined top-level aliases.
- **How a match is ranked and reported.** Nothing exists yet. M14.4 is the dashboard's global
  search, and AGENTS.md §3 requires the two to call the same function.

What M13.2 requires of it:

- **A new payload goes in the schema document.** Add its definition, its `tag.<name>`, an
  `x-payloads` entry stating whether it holds a genotype and is scanned, and the root
  `oneOf` entry. That is a shape change, so it takes version 3: bump
  `AGENT_SCHEMA_VERSION` and the document's `version`, add the digest to `SHAPE_DIGESTS`, and
  add a line to the version history in [the agent schema](agent_schema.md). The tests fail
  until all of that is done.
- **Failures go through `contract.refuse`**, with a kind from the table in
  [the agent schema](agent_schema.md) or a new one added to it. A search that reads a saved
  run reports a run it cannot open with `contract.run_error_kind`, as `runs` does. A kind is
  lowercase letters, digits, hyphens and underscores; a test reads every kind the CLI
  modules print and checks it.

What M13.2 left, for whichever later item needs it:

- **Exit codes outside the read commands.** `run`, `impute` and `serve` exit 2 for every
  failure, not only usage errors.
- **Failures printed as text under `--json`.** `ingest`, `refs`, `tools` and `paths`. `roh`
  has no `--json` flag; it prints its result as JSON and a failure as text.
- **Commands with no tag.** `runs clinvar`, `runs secondary`, `runs imputation`, `pgx calls`
  and `hla calls` print saved records that the schema does not describe. M13.5's parity test
  will list what an agent can reach, and is the place to decide which need describing.
- **Confidence in two places.** The document describes `confidence` and
  `computation.reliability` as they are. M13.4 decides whether an agent sees one shape.

<a id="accepted-m132-agent-json-schema"></a>

## Accepted M13.2 agent JSON schema

Implemented on 2026-11-11 under [the agent schema](agent_schema.md). No owner question was
asked: each choice follows something M13.1 or the bundle format had already settled, and that
page lists them.

- **One document.** `src/genetics/cli/agent_schema.json`, JSON Schema draft 2020-12, describes
  seven payloads: `runs.list`, `runs.show`, `runs.section`, `runs.card`, `runs.qc`,
  `cards.evidence` and `error`. `genetics schema` prints it whole, or one payload as a
  self-contained schema.
- **Every described document names itself.** It starts with
  `"schema": {"name": ..., "version": 1}`. `genetics/cli/contract.py` holds the version, the
  tag and the one error writer.
- **The M13.1 handoff's open points.**
  - `run_id` is the bundle's directory name in every command and in the text output.
    `runs.show` keeps the manifest's value as `recorded_run_id`.
  - One error document, `{"ok": false, "error": {"kind", "message"}}` with the tag, from every
    command that printed an error document. `pgx` and `pgs` printed a bare string before.
    `pgx calls` and `hla calls` now report an unknown run as `not-found`, as `runs` does.
  - Exit codes are stated for the read commands and unchanged: 1 where the command could not
    be carried out, 2 where the command line was wrong.
  - Saved record versus `current_context` is now a rule, stated by the document's structure.
- **Citations.** Required on every saved card and evidence declaration, with `type` and `id`
  on each. `runs.card` and `cards.evidence` give each one's public page.
- **Stability is tested.** A digest of each version's shape is pinned, the vocabularies and
  card keys are compared with the engine's, and every command's output is validated against
  the document, including the saved runs with HLA and guideline cards.

Changed for a caller: `runs show --json`, `runs clinvar --json`, `runs secondary --json` and
`runs imputation --json` print the directory name as `run_id` (the same value unless the
bundle was renamed); the six read payloads gain a leading `schema` key and `runs.show` gains
`recorded_run_id`; `pgx` and `pgs` errors are objects; an unknown run in `pgx calls` and
`hla calls` has kind `not-found`. No bundle format, knowledge schema, card or saved-file type
changed. No personal export or saved real run was opened; all checks used synthetic runs.

Validation on 2026-11-11, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **4,083 tests with nine skips** in 710 s: the five existing
Windows skips and the four published-classifier HIBAG tests. After that run only documentation
and one module docstring changed. Full dbSNP card lint (119 cards, 594 renders, 65/65 keys),
strict mypy over source, scripts and tests (250 files), ruff, format and the fixture check
pass. The 51 new tests are in `tests/test_agent_schema.py`, and two
existing tests in `tests/hla` and `tests/refs` now validate their saved runs against the
document. Sixteen guards were each removed in turn, and each removal failed a test.

**Saved runs repeat their deep checks once.** This change edits Python source, so the first
read of each saved run repeats its deep checks (about 54 minutes for the real imputed run).
Run `genetics runs list --verify`, or the launcher's verify-first shortcut, first.

The [session diff review](review_m132_session.md) (`7a4c4c3..2c90a52`) found two defects.
Version 1's `error.kind` pattern refused `run_parts` and `frequency_reference`, two kinds
`genetics run` prints; the schema is now version 2, which allows underscores, and a test checks
every kind the CLI modules can print. `hla calls` called a newer-format or damaged run `hla`
and `pgx calls` called a disk failure `pgx`; both now share `contract.run_error_kind` with
`runs`. The review also corrected the README status line and the claim that `roh` has a
`--json` flag. The full native suite passes **4,084 tests with the same nine skips** in 691 s: the five Windows skips and the four published-classifier HIBAG tests.

<a id="next-open-step-m132-json-schema"></a>

## M13.2 entry contract (implemented; retained for review)

M13.2 is a stable, versioned and documented JSON schema for the agent CLI, with citations in
card JSON. Nothing has been selected or verified beyond what is listed here.

What M13.1 hands over:

- **The shapes exist and are written down, unversioned.** [The read-command contract](agent_cli.md)
  gives `runs card`, `runs show --section`, `runs qc` and `cards evidence`. No payload carries
  a schema version. The frozen card inside them is `reads.card_payload`, one projection
  shared with `runs show --json`; a test fails if a `StoredCard` field is missing from it.
- **Citations are already in card JSON.** `card.citations` is the saved list.
  `current_context.citation_links` gives each one's public page, re-validated by
  `citation_url`. `cards evidence` adds `url` to each citation directly, since it reads the
  pack and has nothing frozen to keep apart.
- **Frozen versus current is a convention, not a schema.** Everything this engine adds at read
  time is under `current_context` with `"context": "current"` (`runs card`, `runs show
  --section`, `pgx calls`). M13.2 should decide whether that becomes a schema rule.
- **Three inconsistencies a schema would have to settle.**
  - `run_id`: the new payloads give the directory name, which commands resolve.
    `runs show --json` gives the manifest's `run_id`. They differ only for a renamed bundle.
  - Error objects: `runs`, `cards evidence` and `hla calls` print
    `{"ok": false, "error": {"kind", "message"}}`. `pgx calls`, `prepare` and `inspect` print
    `{"ok": false, "error": "<message>"}`.
  - Exit codes: an unknown `--section` exits 2 (usage). An unknown run or card exits 1.
- **Confidence inputs live in two places by card kind.** Interpretation and HLA cards save a
  `confidence` block (six scored inputs, PPV). Computed, polygenic and guideline cards save
  `confidence: null` and keep tier, score, inputs, ceilings and reason in
  `computation.reliability`; the bundle reader takes their tier from there. The
  [M13.1 review](review_m131_session.md) found the text form missing the second place. A
  schema has to describe both, or M13.4 has to give an agent one shape.
- **Which payloads hold a genotype is part of the contract.** `runs show` and `runs card` do,
  by design, and are not scanned. `runs list`, `runs qc` and `cards evidence` are scanned on
  both branches. M13.7's outbound-query lint will rely on that split.

<a id="accepted-m131-agent-read-commands"></a>

## Accepted M13.1 agent read commands

Implemented on 2026-11-10 under [the read-command contract](agent_cli.md). No owner question
was asked: the roadmap left open only where the commands live, and M4.2 had already settled
that a saved run has one command group.

- **Four commands.** `runs show --section` (repeatable, case-insensitive), `runs card`,
  `runs qc` and `cards evidence`. `runs list` (M4.2) and `refs licenses` (M2.6) were already
  there. AGENTS.md §3 and the README now give the real names.
- **One projection of a saved card.** `run/reads.py` holds `card_payload`, which
  `runs show --json` now uses too, and the section, card and QC views.
- **The dashboard and CLI share wording.** `views.SectionView.empty_reason` now calls
  `reads.empty_reason`. A test compares every section's title, blurb, milestone, counts,
  empty reason and pointers with the dashboard's views.
- **Small fixes found by using it.** `runs show` widened its tier column by one, because
  `not_determinable` ran into the section name. `_citation_payload` in `run/bundle.py` is now
  public as `citation_payload`, since a third module uses it.
- **Text output names why evidence is missing.** It is one of three cases: an assay-limit
  card, a bundle older than format 2, or an outcome with `evidence: null`.

No schema, bundle format, card or saved-file type changed. No personal export or saved real
run was opened; all checks used synthetic runs.

Validation on 2026-11-10, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **4,029 tests with nine skips** in 666 s: the five
existing Windows skips and the four published-classifier HIBAG tests. Nothing changed between
that run and the commit except documentation. An earlier run was stopped at 37% (no failures
by then) so two cleanups could land first. The 36 new tests are in
`tests/test_cli_agent_reads.py`. Eleven guards were each removed in turn, and each removal
failed the test written for it. The report-order guard moved during the cleanup and was
checked again in its new place. Full dbSNP card lint (119 cards, 594 renders, 65/65 keys),
all four strict type targets (248 files), ruff, format and the fixture check pass.

**Saved runs repeat their deep checks once.** This change edits Python source, so the first
read of each saved run repeats its deep checks (about 54 minutes for the real imputed run).
Run `genetics runs list --verify`, or the launcher's verify-first shortcut, before using the
new commands or the dashboard on it.

The [session diff review](review_m131_session.md) (`441e498..015c41c`) found one defect:
`runs card` text called computed, polygenic and guideline cards "Not scored", although they
keep their tier, inputs and reason in `computation.reliability`. It now prints them. The
review also removed stale "what remains" text from the roadmap, the `runs` module docstring
and the README. It made the dashboard's grid share the empty-section wording, and made
citation links refuse a mismatched list. JSON payloads are unchanged.

<a id="next-open-step-m131-agent-cli"></a>

## M13.1 entry contract (implemented; retained for review)

M13.1 is the rest of the agent interface's read commands. The roadmap lists `--section`
filtering, `card <run> <card-id>`, `evidence <card-id>` and `qc <run>` as its own command.
It also leaves open whether these live under `runs` or at the top level. Nothing has been
selected or verified beyond what is listed here.

What the code already has:

- **`genetics runs list`, `runs show [--json]`, `refs licenses`.** `runs show` has no
  `--section`. Its text output is a header, one line per card and the sections' pointer
  lines (M12.1, M12.2). `--json` prints the whole frozen bundle, which is about 1 GB on the
  real imputed run (recorded above). A per-card read should not have to print that.
- **Section pointers are not in `runs show --json`.** That command prints the saved record,
  which holds no current context (the [M11.6 review](review_m116_session.md) and the
  [M12.1 review](review_m121_session.md)). The pointers live in `engine/sections.py`. The
  [M12.1 review](review_m121_session.md) left the agent surface to M13. M12.2's four MTHFR
  cards depend on them: a reader of one claim card is meant to find the other three.
- **Reading a saved imputed run takes about 13 s** once its check record is current, and
  about 54 min the first time after a source change. A new command reads through the same
  `store.load_run`.
- **AGENTS.md §1.3 and M13.7 apply to every new output.** An agent researches the variant
  and never the user's genotype at it. Card JSON carries citations so that an agent can
  verify a claim instead of inventing one (M13.2).

<a id="accepted-m122-mthfr"></a>

## Accepted M12.2 MTHFR

Implemented on 2026-11-09 under [the calibration audit](mthfr.md). Two questions were put to
the owner after the evidence was read and before any card was written, and each answer was
the recommended option. First, a biochemistry card plus one card for each well-tested health
claim, so that the calculator scores each claim instead of reading them only in text. Second,
A1298C is mentioned but gets no card.

- **Four schema-3 cards** in `knowledge/nutrition/mthfr.yaml`, all on rs1801133, with
  `strand: forward_only`:
  - `mthfr_c677t_homocysteine` (nutrition);
  - `mthfr_c677t_venous_thrombosis` and `mthfr_c677t_coronary_heart_disease` (physical
    health);
  - `mthfr_c677t_depression` (mental health).

  Knowledge schema stays at 9 and bundle format at 28.
- **Landings, as computed.** For a common, directly typed call with an exact ancestry match,
  the nutrition card lands well-established. Before ancestry is computed it lands strong.
  The three claim cards land limited for every genotype, because each is `candidate_gene`
  with `replication: conflicting`. A test pins every landing, and another checks that no
  claim card outranks the nutrition card under any frequency or ancestry tried.
- **Section pointers both ways.** Nutrition points to the three claim cards. Physical health
  and mental health point to the nutrition card. Two section blurbs name the new content.
- **Recorded, not tuned:** `replication: none` outscores `conflicting`, so a small
  unreplicated study would land above a refuted claim. That is one reason Friso's
  methylation study is stated on the nutrition card rather than carded.

Validation on 2026-11-09, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **3,992 tests with nine skips** in 694 s. The skips are
the five existing Windows skips and the four published-classifier HIBAG tests. An earlier run of
the suite is not counted: card wording changed while it ran, so `test_mthfr.py` checked the new
YAML against the old expected text and failed 52 tests. No code, card or test changed between
the counted run and the commit. The 128 MTHFR and nutrition tests include the native gnomAD and ClinVar strand
checks. Full dbSNP card lint passes **119 cards, 594 renders, 65/65 marker keys**. All four
strict Windows/Linux x Python 3.11/3.13 type targets (244 files), ruff and format pass. No
personal export was opened for any result; the array's marker list was read for rsID and
position only. No browser review is claimed: the pointers are checked through the test client's
HTML.

The [session diff review](review_m122_session.md) (`d1a26d4..f8eebb0`) found no defect in
matching, confidence, saved evidence, the pointers or the launcher's control flow. It
replaced the depression card's claim that Border et al. coded genotypes additively, which the
paper does not say. It added Clarke 2012's relative figure to the homocysteine card: TT
averages 18% (99% CI 17-19%) more than CC. It also added an absolute-risk statement to the
depression card and corrected four wordings that went beyond their sources. A new test pins
each claim card's caveat on what a limited tier means. After the review, on 2026-11-10, the
full native suite passes **3,993 tests with the same nine skips** in 698 s, with nothing
edited during the run. Full dbSNP card lint (119 cards, 594 renders, 65/65 keys), all four
strict type targets, ruff and format pass. The rebuilt launcher was run with `--verify`
against an empty temporary data directory.

**The dashboard launcher can verify first (2026-11-09).** `GeneticsDashboard.exe --verify` runs
`genetics runs list --verify` before starting the server. `build_launcher.ps1` also makes
`GeneticsDashboard (verify first).lnk`, a gitignored shortcut that passes the flag. If the
check exits with an error, the dashboard does not start. The check repeats deep checks even
when they are current, so use it only after the code changes.

**Saved runs repeat their deep checks once.** This session changed Python source, so the first
read of each saved run repeats its deep checks (about 54 minutes for the real imputed run).
Run `genetics runs list --verify`, or the launcher's verify-first shortcut, before opening
the dashboard on it. A saved run never gains these cards: seeing them on real data needs a
new run, about 8 hours.

<a id="next-open-step-m122-mthfr"></a>

## M12.2 entry contract (implemented; retained for review)

M12.2 is the MTHFR card, which the roadmap calls **a deliberate calibration test case**. MTHFR
is heavily overhyped in wellness marketing. The card should state the actual evidence and let
the confidence calculator land where it lands. It is the reference example for how the
project handles popular claims with thin support. Nothing has been selected or verified
beyond what is listed here.

What M12.1 hands over:

- **The marker is measured.** C677T is rs1801133, chr1:11856378 GRCh37, on the array. dbSNP
  b157 lists G>A,C,T, so use `strand: forward_only`. ClinVar VariationID 3520 names it
  `NM_005957.5(MTHFR):c.665C>T (p.Ala222Val)`. MTHFR is on the reverse strand, so 677T/Val222
  is **forward A** (gnomAD exomes: 31.5% of all alleles). A1298C is rs1801131 (forward T>G,
  ClinVar 3521, benign/likely benign), also on the array. ClinVar classes neither as
  pathogenic, so the §4.1 frequency gate does not apply.
- **A folate estimate is already read.** Grarup 2013 Table 2 (doi:10.1371/journal.pgen.1003530):
  effect allele G (677C) raises serum folate by 0.096 quantile-normalised units in Iceland,
  and by 0.18 in each of Inter99 and Health2006. Combined n 37,337, P 9.5e-53, I2 62%
  (P 0.005). The FOLR3 card's text says "the main genetic influence on folate, MTHFR, is a
  separate card". So M12.2 must put the card in nutrition, or that sentence becomes false.
- **The calibration needs sources for the popular claims, not only the folate one.**
  Candidates to verify, none read yet: the thermolabile enzyme (Frosst 1995, Nat Genet),
  homocysteine meta-analyses, and the ACMG practice guideline on the lack of evidence for
  MTHFR polymorphism testing (Hickey 2013, Genet Med). Wellness claims (depression,
  miscarriage, "methylation") need their own primary evidence or an explicit statement that
  there is none. Do not borrow the folate estimate for them.
- **Outcome-specific evidence fits.** Schema 3 lets each genotype carry its own estimate, or
  `evidence: null` where a group is only a comparator. M12.1's rs762551 card is the nearest
  model: two outcomes with different studies, both candidate-gene, and replication recorded
  as `none` with the audit's scope stated.
- **Bind strand twice.** Every M12.1 card fixed its forward base from a ClinVar HGVS name
  and from population frequency. Star-allele and coding-strand labels disagree between
  papers (the CYP1A2 *1F trap in [the audit](nutrition.md#the-cyp1a2-label-trap)).
- **Read a denominator from the analysis that produced the estimate.** Two M12.1 numbers
  had to come from a forest plot and from a per-genotype table, because the headline figure
  had no matching n.

<a id="accepted-m121-nutrition-cards"></a>

## Accepted M12.1 nutrition cards

Implemented on 2026-11-08 under [the nutrition audit](nutrition.md). The owner settled four
questions first, each with the recommended option. Lactase and ALDH2 move from traits. HFE and
celiac stay in place and are linked by a section pointer. Folate goes to M12.2's MTHFR card
unless another locus met the bar; one did, FOLR3. Both CYP1A2 markers get a card.

- **Seven new schema-3 cards** in `knowledge/nutrition/variants.yaml`:
  `cyp1a2_coffee_intake`, `cyp1a2_rs762551_caffeine`, `adh1b_alcohol_intake`,
  `fut2_secretor_status`, `fut2_vitamin_b12`, `gc_vitamin_d` and `folr3_serum_folate`.
  `knowledge/nutrition/lactase_alcohol.yaml` holds the two moved cards, changed only in
  `section`. Knowledge schema stays at 9 and bundle format at 28. Saved bundles record each
  card's section, so earlier runs still show lactase and ALDH2 under traits.
- **`SectionInfo.related`** (`engine/sections.py`) names cards another section holds. The
  dashboard's section panel links to each card in its own section, and `genetics runs show`
  prints the same line. A run without the card says "not in this run". The pointer is not
  counted and is not shown when the grid is grouped by tier.
- **FOLR3 rs652197 is off the array.** A `--no-impute` run reports it as absent, like the
  cilantro and APOE cards before it.

Validation on 2026-11-08, Windows, Python 3.13, Java 17 and the pinned PLINK/Beagle tools
configured: the full native suite passes **3,928 tests with nine skips** in 712 s. The skips
are the five existing Windows skips and the four published-classifier HIBAG tests, which need
a separate reference root and do not touch these cards. Card wording was tightened after that
run started, so all 880 engine, web, `runs` CLI and packaging tests were run again and pass.
The 64 nutrition tests include the native gnomAD and ClinVar strand checks. Full dbSNP card
lint passes **115 cards, 564 renders, 61/61 marker keys**. All four strict Windows/Linux x
Python 3.11/3.13 type targets (243 files), ruff and format pass. No personal export was
opened for any result; the array's marker list was read for rsID and position only. No
browser review is claimed: the pointer is checked through the test client's HTML.

The [session diff review](review_m121_session.md) (`243aa3e..9f3d6ab`) found no defect in
matching, saved evidence or the pointer code. It replaced four card sentences no cited paper
supported with figures from the cards' own sources. It corrected the FOLR3 card, which said
the array "cannot read" the frameshift and called it causal. And it sourced Sachse's site and
"ADH1B*2" to their PharmGKB variant records, which also show CYP1A2*1F is retired. One review
fix repeated the original mistake: it inferred that variation was mostly non-genetic from a
sibling-pair heritability that the same paper's twin estimates contradict. It was caught and
reworded. After the review, the full native suite passes **3,928 tests with the same nine
skips** in 703 s. Full dbSNP card lint (115 cards, 564 renders, 61/61 keys), all four strict
type targets, ruff and format pass.

**Saved runs repeat their deep checks once.** This session changed Python source, so the first
read of each saved run repeats its deep checks (about 54 minutes for the real imputed run).
Run `genetics runs list --verify` before opening the dashboard on it. A saved run never gains
these cards: seeing them on real data needs a new run, about 8 hours.

<a id="next-open-step-m121-nutrition-cards"></a>

## M12.1 entry contract (implemented; retained for review)

The open questions below were settled as recorded in
[the M12.1 record](#accepted-m121-nutrition-cards). The entry text follows.

M12.1 fills the nutrition section, which has no card yet: MCM6 lactase persistence, CYP1A2
caffeine, ADH1B/ALDH2 alcohol, HFE haemochromatosis, celiac HLA-DQ, FUT2 secretor status, vitamin D
(GC), B12 and folate. M12.2's MTHFR card follows it. Nothing has been selected or verified.

What it inherits:

- **Three named items already have a card elsewhere.** `mcm6_lactase_persistence` and
  `aldh2_alcohol_flushing` are in `knowledge/traits/sensory_metabolism.yaml`,
  `hfe_c282y_iron_overload` is in `knowledge/health/common.yaml`, and `hla_celiac_dq2_dq8` is in
  `knowledge/immunogenetics/hla.yaml`. A card has one section and there is no cross-listing. M11.5
  and M11.4 each kept one card per fact, so decide placement deliberately rather than authoring a
  second card with the same claim: moving one changes where a saved reader expects it.
- **The rest have no card.** CYP1A2, ADH1B, FUT2, GC, B12 and folate variants need measuring against
  dbSNP, the array's marker list (first three columns only), ClinVar and gnomAD, as the
  [M11.5 audit](carrier_status.md#candidate-audit-measured-2026-10-25) did. Indels stay excluded
  (AGENTS.md §4.2).
- **Catalogue labels are not endpoints.** [M11.7](reproductive_prs.md) found two labels naming
  another model's trait. Read the scoring file's `pgs_name` if a polygenic card is wanted. Nutrition
  is already in `POLYGENIC_SECTIONS`, so no schema change is needed for one.
- **Field codes can reach a published evaluation.** M11.7's menopause R2 looks depressed by UK
  Biobank's negative answer codes. A reported R2 far below the trait's other published figures is
  worth the same arithmetic: standard error × √N against the field's own spread.
- **Try a long acceptance runner on its smallest model first.** M11.7's first run spent five hours
  preparing references, then stopped at a check copied from an older runner: `Prepared.reference`
  now holds the panel, and `_reload` reads the extraction back from its cache.

<a id="accepted-m117-reproductive-traits"></a>

## Accepted M11.7 reproductive traits

Implemented on 2026-11-07 under [the model audit](reproductive_prs.md). Knowledge schema 9 adds
`reproductive` to `POLYGENIC_SECTIONS`, and bundle format 28 may hold such a card; formats 1–27 are
read unchanged. A reproductive interpretation card must still declare `carrier`.
`carrier_screening_scope` is unchanged: it reads only carrier records, its pinned wording needs no bump,
and a test confirms its tally is the same beside these cards. The section blurb said "about offspring
rather than self", which these cards would make false; it and AGENTS.md §3.1 now say which cards are which.

Three findings shaped it. Two catalogue labels name another model's endpoint (PGS002128, PGS002215). Ding
2023's women-only models beat Prive 2022's for four endpoints, by a stated rule, while Prive stays for two.
And the menopause model's reported R2 is probably about eight times too low because of UK Biobank's answer
codes, which the card says on its face without changing the stored number.

Validation on 2026-11-07, Windows, Python 3.13, Java 17 and the pinned PLINK/Beagle tools
configured: the full native suite passes **3,864 tests with nine skips**: the five existing Windows
skips and the four published-classifier HIBAG tests, which need a separate reference root and do not
touch these cards. The new tests bind each card's model, field, test-sample size, effect and direction
before fabricated inputs replace the scores, with 16 mutation regressions (each reversed direction,
each mislabelled neighbouring model, borrowed denominators and borrowed effects). Native tests bind each
fetched file to its own `pgs_name` and the menopause weights to Day 2015's Table 1. Full dbSNP card lint
passes **108 cards, 522 renders, 54/54 marker keys**; all four strict Windows/Linux x Python 3.11/3.13
type targets (241 files), ruff and format pass. No personal export was opened. The renderer is unchanged
and no browser review is claimed.

Full-model acceptance on public stand-ins passed in the private
`%LOCALAPPDATA%/genetics-analysis/acceptance/m117` checkpoint: all seven models through the default
imputed path and through explicit `--no-impute`, 14 computed records, each validated in memory and
again after being read back from disk. It tests execution, not predictive calibration, and its scores,
percentiles and coverage stay out of Git.

| Stage | Time | Peak working set |
|---|---|---:|
| Cold reference preparation, 16 workers | about 5 h | not recorded |
| Preparation again, from the caches | 168 s | 4.0 GB |
| Scoring all seven, default imputed | 90 min | 10.2 GB |
| Scoring all seven, `--no-impute` | 14 min | 6.6 GB |
| Reading back one genome-wide record, imputed | 47-49 s | up to 7.2 GB |
| Reading back one genome-wide record, `--no-impute` | 22-24 s | up to 4.9 GB |

The cold time comes from the cache files' timestamps: 48-56 min for each of the five largest models, 26
for cycle length and 4 for menopause, with other test runs sharing the machine for part of it. A stale
check in the private runner stopped that run before it wrote its measurements, which is why the stage
has no peak. The caches take 1.65 GB, about 298 MB for a 979,739-row model. Compressed records total
304 MB imputed and 224 MB without imputation; the largest are 63 MB and 49 MB.

On 2026-11-08 a synthetic `genetics run --no-impute` saved a real-size format-28 bundle with all 21
polygenic cards: 54.7 min with warm reference caches, 786 MB. `genetics runs show` reopened it in 9 s
on the check record written at save, and a full deep read took 8.1 min. Nineteen scores were computed.
The 159-row menopause model and PGS000007 share no usable marker with the 12,003-marker synthetic
export, so they render `not_run` with that reason. The synthetic run was then deleted.

<a id="next-open-step-m117-reproductive-traits"></a>

## M11.7 entry contract (implemented; retained for review)

The open questions below were settled as follows: polygenic cards only, widening `POLYGENIC_SECTIONS`
rather than the carrier rule; the section statement left as it was. The entry text follows.

M11.7 is the reproductive section beyond carrier status: age at menarche, age at menopause and
related traits. Nothing has been selected or verified yet: score, source population, licence
and 23andMe exposure all need checking per score, as M9.7–M9.12 did.

What it inherits:

- **The schema refuses both card forms today.** `POLYGENIC_SECTIONS` excludes reproductive, and
  a reproductive interpretation card must declare `carrier` (both in `engine/cards.py`). M11.7
  has to widen one of them deliberately, not declare a false carrier block.
- **The section statement.** `carrier_screening_scope` and its notice say the section is not a
  carrier screen and do not count non-carrier cards. Its tally reads only `carrier` records, so
  a trait card leaves it unchanged. Check the notice still reads correctly beside trait cards.
  Its saved wording is pinned, so changing it needs the record's schema bumped.
- **Non-ASCII card text is now safe in CLI output**, but `CliRunner` cannot show that: it
  substitutes a UTF-8 stream. Test a redirect in a subprocess with `PYTHONIOENCODING=cp1252`.
- **Polygenic cards need what M9.6 requires**: ancestry portability, within-family attenuation
  where it applies, coverage, and decile rates where published.

<a id="accepted-m116-carrier-screening-scope"></a>

## Accepted M11.6 carrier-screening scope

Implemented on 2026-11-06 under the contract in
[carrier status](carrier_status.md#section-level-scope-m116). One computed card,
`carrier_screening_scope`, states that the section is not a screen and counts 16 typed markers
over 9 conditions against ACMG Tier 3's 113 genes: 8 typed, 7 assay limits, 98 with no card.
The last is worded as a gap in this report, never as an assay limit. Knowledge schema 8 holds
its declaration: the source tables' rows, sourced gene-level limits, the M11.5 audit's 38
excluded alleles and the 12 dbSNP-multiallelic markers. Bundle format 27 rebuilds the record
from its frozen declaration and the bundle's own carrier records on write and read; formats 1–26
are read unchanged, and a run with carrier cards but no record still states the limit in the
dashboard and `runs show`. `genetics cards carrier-scope` gives the comparison from the pack alone.

Two checks shaped it. All 113 rows were read from the source, and the paper's stated totals (86,
97, 16) match them; its correction changes wording only. And the audit's classes were re-checked
against the pinned ClinVar, gnomAD and dbSNP indexes, per declared allele: every `not_authored`
allele has a P/LP record and a PASS frequency, so the "gap in this report" wording is measured.
**The saved face's wording is part of the record's schema**, so a later edit needs a schema bump
and the old text retained; a test pins it.

Validation on 2026-11-06, Windows, Python 3.13, Java 17 and the pinned PLINK/Beagle tools
configured: the full native suite passes **3,817 tests with nine
skips**: the five existing Windows skips and the four published-classifier HIBAG tests, which need
a separate reference root and do not touch carrier code. The native reference checks of the
excluded alleles ran against the fetched indexes. Full dbSNP card lint passes **101 cards, 508
renders, 54/54 marker keys**; all four strict Windows/Linux × Python 3.11/3.13 type targets
(241 files), ruff, format and fixture reproduction pass. No personal export was opened.
The [session diff review](review_m116_session.md) records its own validation.

<a id="next-open-step-m116-carrier-screening-incompleteness"></a>

## M11.6 entry contract (implemented; retained for review)

The open questions below were settled as follows: a computed card; Gregg 2021's Tables 1–6 as
the reference set, with no population claimed; limits stated rather than X-linked panel
members; the per-gene cards unchanged. The entry text follows.

M11.6 is the reproductive section's **section-level** statement: carrier screening from a
genotyping array is incomplete as a category, not only for the two conditions with
impossibility cards (`smn1_copy_number`, `alpha_globin_deletions`, M3.7). M11.5 supplies the
callable set it needs; read [carrier status](carrier_status.md) first.

What M11.5 hands over:

- **The panel is data.** `genetics.engine.carrier.carrier_panel(pack)` and
  `genetics cards carriers --json` (panel schema 1) list 16 typed markers over nine
  conditions, each with its condition, inheritance, typed allele, ClinVar VariationID,
  `typed_scope` sentence and `strand_symmetric` flag. It is a property of the knowledge
  pack and carries no genotype.
- **The audit is the exclusion list.** `docs/carrier_status.md` records three classes:
  not typed as an SNV (indels such as F508del, 35delG and 1278insTATC; alleles absent from
  the array such as HbC and HbE; copy-number states), typed but failing a criterion
  (conflicting ClinVar aggregates), and **tractable but not authored** (beta-thalassaemia
  SNVs, SERPINA1, ATP7B and others). The last class is a gap in this pack, not in the
  array; M11.6 must not count it as typed, and should say so differently from an assay
  limit.
- **Per-run results.** A saved carrier record whose `state` is `null` — marker absent,
  no-call, strand-ambiguous homozygote at one of the four A/T or C/G markers — was not
  determined for that person. Counting those from the saved records needs no genotype.

What is not yet decided:

- **Card shape.** An impossibility card is static and citation-free, and the §3.2 register
  test requires a matching AGENTS.md bullet in both directions. A computed card can state
  counts from the panel, but `kind: computed` is restricted to genome structure and the
  ClinVar coverage card; extending it to reproductive needs a computation name, a saved
  record and bundle validation. A static statement cannot say how many markers this pack
  types; prefer computed if the count is on the card.
- **Reference set.** To say what is *excluded*, M11.6 needs a cited list of what carrier
  screening is meant to cover. Gregg et al. 2021 (ACMG practice resource,
  doi:10.1038/s41436-021-01203-z) recommends 97 autosomal recessive genes at carrier
  frequency of at least 1/200 plus X-linked genes, and is already cited by M11.5's cards;
  verify its tables before binding counts to them. The M11.5 review read their structure:
  Tables 1–4 bin autosomal recessive genes by a "maximum carrier frequency" column estimated
  from gnomAD (≥1/50, <1/50 to ≥1/100, <1/100 to ≥1/150, <1/150 to ≥1/200), Table 5 lists
  genes ascertained outside the gnomAD criteria (including SMN1 and ELP1) with published
  frequencies, and Table 6 lists X-linked genes. The tables do not name the population each
  maximum comes from, so a card should not claim one.
- **"No copy" is weaker than it looks at most markers.** 12 of the 16 panel markers have a
  third base in dbSNP, and the array's probe alleles are unpublished, so a homozygous
  reference call cannot show that the probe tested the card's alternate. The section-level
  card should say a no-copy result is not a negative screen even for the typed alleles.
- **X-linked conditions.** Fragile X (repeat expansion), Duchenne (mostly deletions) and
  haemophilia A (inversions) are outside genotype calls; G6PD is a PGx call. State them as
  limits, not as panel members.
- **Existing per-gene cards.** `smn1_copy_number` and `alpha_globin_deletions` stay; the
  section-level card is a different claim and must not duplicate their text.

<a id="accepted-m115-carrier-status"></a>

## Accepted M11.5 carrier status

Implemented on 2026-10-25 under the contract in [carrier status](carrier_status.md).
Knowledge schema 7 binds each `carrier` declaration to its genotype map (one autosomal
biallelic marker, forward-only, the pathogenic allele declared, zero/one/two copies each
on their own outcome, literal `risk_context` everywhere). Bundle format 24 saves and
re-derives the state; formats 1–23 are read unchanged. Two findings shaped it: the matcher
leaves four of the sixteen markers strand-ambiguous for homozygotes regardless of
`forward_only`, so the panel flags them and heterozygous carriers are still reported; and
rs76173977, first taken for the Ashkenazi HEXA IVS12+1G>C allele, is IVS9+1G>A — the
right marker is rs147324677.

Validation on 2026-10-25, Windows, Python 3.13, Java 17 and the pinned PLINK/Beagle tools
configured: the full native suite passes **3,659 tests with nine skips** — the five existing
Windows skips and the four published-classifier HIBAG tests, which need the separate
reference root the native HLA tests document and do not touch carrier code. The 95 new
carrier tests, plus one dashboard outlet test, include the native ClinVar/gnomAD binding of
all 16 panel entries against the fetched indexes. Full dbSNP card lint passes **100 cards, 506 renders, 54/54 marker keys**; all four
strict Windows/Linux × Python 3.11/3.13 type targets (233 files), ruff, format, fixture
reproduction and the staged privacy scan pass. No personal export was opened: the array's
marker list was read from the export's rsID, chromosome and position columns only.
The [session diff review](review_m115_session.md) records its own validation.

<a id="next-open-step-m115-carrier-status"></a>

## M11.5 entry contract (implemented; retained for review)

M11.5 adds carrier cards for recessive conditions the array can actually type, in the
**reproductive** section (§3.1: about offspring, not self). M11.6's section-level
incompleteness card needs M11.5's callable set to exist first, so record that set as data
the next step can read, not only as prose.

What a carrier card has to carry, and what is not yet decided:

- **§4.1 governs every rare call.** A heterozygous call for a rare pathogenic allele is
  usually a chip artifact; the M7.2 gnomAD calibration and the scoped M7.3 PPV already
  apply to interpretation cards through `calculate_confidence`. A carrier card must show
  the frequency-banded PPV on its face exactly as M7 cards do, never a softer tier because
  carrier status "is only about offspring".
- **Card shape.** The existing interpretation schema (2/3) already expresses a curated
  carrier variant: an exhaustive genotype map, outcome-specific evidence, `risk_context`
  and forward-only strand. Prefer authored cards over a new computed kind unless a clear
  need appears; the ClinVar lookup (M7.1) is a reference annotation, not a card source.
- **"Array-tractable" must be measured.** Candidates need a typed SNV on this chip, a
  ClinVar P/LP recessive assertion and a usable gnomAD frequency. Several of the best-known
  carrier variants fail one of these: CFTR F508del and GJB2 c.35delG are indels (§4.2;
  matching needs a verified whitelist entry, M1.6), and SMN1 and alpha-globin are copy-number
  states with impossibility cards already (M3.7). Check each candidate against dbSNP and the
  real chip's marker list before authoring, and state on the card when the gene's other
  pathogenic variants are not typed.
- **"No variant found" is not "not a carrier".** Each card's non-carrier outcome must say
  it covers only the typed variant(s). The section-level statement is M11.6.
- **X-linked conditions** need M6.4's sex call and PAR-aware ploidy: a hemizygous call is
  not a homozygote (§2), and a heterozygous X call in a sample inferred male is reported,
  not interpreted (M1.5).
- **Overlap with existing cards.** HFE C282Y and APOE already live in physical health;
  G6PD is an M10.2 PGx gene. Decide placement once, with one card per fact, as M11.4 did
  for HLA-B.
- **Absolute context.** Carrier frequency and the couple-level risk (both partners
  carriers, one in four per pregnancy) are population facts that need citations per
  condition; do not compute offspring risk for an unknown partner.

<a id="next-open-step-m114-hla-linked-cards"></a>

## M11.4 entry contract (implemented; retained for review)

M11.4 turned the frozen classifier choice and per-locus ceilings into eight cited cards;
see [the card contract](hla_cards.md). Recorded deviation: the M9.13 study comparison,
not the classifier match, enters the calculator's ancestry slot, because the classifier
match already caps every locus ceiling. The entry text follows.

M11.3 supplies a frozen classifier choice and a per-locus observation ceiling, reviewed
in [the M11.3 diff review](review_m113_session.md). M11.4 turns them into cards: celiac (DQ2/DQ8), type 1 diabetes, ankylosing spondylitis,
narcolepsy (DQB1\*06:02) and drug hypersensitivity (B\*57:01/abacavir,
B\*15:02/carbamazepine). Start with the [selection and confidence contract](hla_selection.md)
and read schema-2 `hla.run.json` through `genetics.hla.calling.report`. Do not rerun HIBAG
or reselect a classifier from a card.

What a card has to carry, and what is not yet decided:

- **Confidence.** Call `calculate_confidence` with `call_source=IMPUTED`, the locus joint
  posterior as `imputation_quality` and the selection's `ancestry_match`. Then apply the
  locus `confidence.ceiling`, which also holds the marker-coverage cap the calculator
  lacks. Never filter: a likely-artifact call still renders, tiered.
- **Absence is not a negative.** `no-markers`, `no-prediction`, `no-classifier`,
  runtime-unavailable and not-requested states render as not determinable, never as
  "allele absent". A predicted pair that lacks an allele is a negative *model call* with
  that call's posterior and ceiling, not a clinical exclusion.
- **Unphased, per-locus calls.** DQ2.5 and DQ8 are DQA1–DQB1 haplotypes, and HIBAG calls
  each locus separately and unphased. Where cis/trans phase changes the claim, state the
  ambiguity. Do not multiply the two loci's posteriors as if they were independent; take
  the weaker locus unless a cited method says otherwise.
- **Resolution.** Calls are two-field, so B\*57:01 and B\*15:02 are representable. Check
  that each card's allele is in the classifier's frozen allele list. An allele the model
  cannot emit is not determinable from that model, not absent.
- **Population allele frequency.** gnomAD has no HLA allele frequencies, so
  `population_allele_frequency=None` caps at moderate under the calculator's existing
  rule. Any frequency source (for example the Allele Frequency Net Database) needs a
  licence audit and a manifest entry before use.
- **PGx overlap.** HLA-B\*57:01 and HLA-B\*15:02 carry CPIC guidelines. Decide whether
  these cards live in pharmacogenomics, immunogenetics or both, with one shared engine
  rather than two claims (compare M10.4 guideline cards and the M10.5 framing).
- **Historical runs.** Format-21 schema-1 runs have neither a selection nor a locus
  ceiling. Their cards must say so rather than invent an ancestry match.
- **Matching proportion.** HIBAG's per-sample matching proportion directly measures
  training-set representation, but has no published threshold and is not in M11.2's
  frozen output. Adding it changes the R script and the scientific output contract;
  record it, at most, as a displayed fact.

<a id="next-open-step-m113-hla-ancestry-selection-and-confidence"></a>

## M11.3 entry contract (implemented; retained for review)

M11.3 selects the classifier from the saved AADR and 1000 Genomes placements through the
cited Morales category and the publisher's training descriptions. It records decline,
not-run, ambiguous and unsupported refusals and explicit overrides with their ancestry
match, and folds posterior, coverage and ancestry into per-locus ceilings. See
[the contract and validation](hla_selection.md). The entry text follows.

M11.2 supplies validated, immutable HLA evidence but deliberately requires an
explicit `--hla-classifier`; it must not infer a classifier from raw genotypes.
M11.3 should use the persisted M5 ancestry placement and its uncertainty to select an
eligible HLARES population model, record both the mapping and rationale in saved HLA
evidence, and decline where placement is ambiguous or outside supported coverage. Do
not silently force a marginal placement into a model.

Preserve every locus in the result. Fold posterior probability and marker coverage
into its confidence while keeping low-confidence calls visible. `no-markers`,
`no-prediction`, unavailable stages and failed jobs are not negative allele claims.
M11.4, rather than this step, turns the frozen evidence into HLA-linked cards.

R and HIBAG remain user-installed. Since 2026-10-18, CI installs the current R release
and HIBAG on Windows and Linux, so the bridge checks and the synthetic native round trip
run on every push. HIBAG trains synthetic classifiers, and `calling.impute` predicts
through them. They first passed with R 4.6.1 and HIBAG 1.48.2. That first run found a
Windows-only bridge defect: R 4.6.1's `Rscript` cuts an `-e` argument at its first
newline, so every probe failed to parse. The bootstrap now runs from a file in the
private workspace.

Prediction through the published classifiers passes locally on Windows, with R 4.6.1
and HIBAG 1.48.2 installed for the current user (2026-10-18). All four populations
prepare against the real dbSNP and 1000 Genomes references and return predicted loci,
in 38–60 seconds per model. The input is synthetic genotypes at the model markers. So
this proves the path runs end to end, not that the calls are accurate. CI cannot run
it, because CI never downloads references. To rerun it, set `GENETICS_HIBAG_TEST_REFERENCES`
to a reference root holding the fetched classifiers, the dbSNP index, the 1000 Genomes
chr6 VCF and `manifest.lock`. `Rscript` is found on `PATH`, or set `GENETICS_RSCRIPT`
(or `GENETICS_HIBAG_TEST_RSCRIPT` for tests only).

The real pinned models, dbSNP and 1000 Genomes now pass reference preparation outside R.
That check found two defects the synthetic fixtures hid: a dbSNP provenance version the
producer never writes, and dbSNP-only strand proof losing 43% of markers to
tetra-allelic sites. See the [real-reference acceptance](hla_imputation.md#real-reference-acceptance-2026-10-16).
When M11.3 folds marker coverage into confidence, use the frozen per-marker
`state` and `strand_evidence`, not a re-derivation.

## M11.2 entry contract (implemented; retained for review)

M11.2 audits the four HLARES hg19 model releases, pins their bytes, validates model
metadata and dbSNP/1000 Genomes strand proofs, and records complete HLA sample schema
1 evidence in additive bundle format 21. Model payloads and all per-run temporary data
remain outside Git. The shared engine serves CLI and dashboard readers; formats 1–20
remain explicitly HLA-not-recorded. See [the implementation contract](hla_imputation.md).

<a id="next-open-step-m111-r-and-hibag"></a>

### M11.1 entry contract (implemented; retained for review)

M10 is complete. M10.5's [section framing](pgx_framing.md) is current report
context; it does not change saved evidence or source/sample/display versions.

M11.1 owns optional R/HIBAG readiness and the subprocess bridge. Start with
`doctor.py::_check_r`, the existing `Rscript`/`requireNamespace("HIBAG")` probe,
its synthetic tests, and the external-tool wrappers' timeout, cancellation,
private diagnostics and offline contracts. Share readiness with doctor rather
than creating a second definition of installed/usable. Distinguish missing R,
missing HIBAG, probe failures and a usable runtime explicitly. Native Windows
support and graceful absence are required; R is user-installed, not silently
added by the pinned binary installer.

The current doctor probe is only a starting point. It returns `missing` for
every failed HIBAG probe, including a timeout, losing the actual error. This
was reproduced with a synthetic timeout during the M10.5 review. Preserve
failed-execution/timeout/malformed-output states as errors rather than
claiming the package is absent. The success output is a fixed sentinel, not
a HIBAG package version. Record both R and HIBAG identities and design an
explicit, validated bridge result. Isolate R startup configuration (for
example, `Rscript --vanilla`), validate subprocess outputs, bound execution
and cancellation, and keep diagnostics private. A readiness check must not
load personal input, fetch classifiers or infer an HLA call.

Keep this item separate from M11.2 classifier ingestion/imputation and M11.3
ancestry-matched selection. HLA models remain fetched references with recorded
licences; use HIBAG pre-fit classifiers, never SNP2HLA's withdrawn panel. No HLA
call may be inferred from a successful dependency probe. Record a versioned
sample/bundle contract before adding new saved HLA evidence, and keep one
shared CLI/dashboard engine. Exercise malformed subprocess output, nonzero
exit, timeout/cancellation and optional absence with synthetic inputs; keep
personal data and diagnostics outside Git.

<a id="next-open-step-m105-section-framing"></a>

### M10.5 entry contract (implemented; retained for review)

M10.4 adds eight declarative guideline selectors in knowledge schema 5 and
reproducible card computations in bundle format 20. Its
[diff review](review_m104_session.md) hardens exact numeric validation and
incomplete-source evidence handling. New cards use guideline display schema 2;
schema-1 cards retain their original frozen rules and text. Source/catalog schema 1,
sample-call schema 1 and M9.13 confidence remain unchanged. All conditional
source branches, exact definition/mapping/result joins, multi-gene conditions,
native copy models, clinical context and distinct evidence labels survive
saved CLI/dashboard inspection. Missing recommendation/citation/source rows
remain explicit. VKORC1 has no recommendation lookup keys in v1.60.0; no
warfarin dose or reverse-strand genotype bridge is manufactured. See
[the audit and acceptance](pgx_guidelines.md).

M10.5 owns the once-per-section statement that this is not a prescribing tool.
Place it where readers encounter PGx calls and guideline cards, with precise
scope and shared wording across the section, overview/gene views and CLI.
Use one shared current-context representation, with the CLI and dashboard
adapting that same wording. JSON should identify section framing as current
context, separate from frozen card results. Place it once in the PGx section,
once on a PGx overview/gene view, and once in the relevant CLI report; do not
emit it per candidate, gene row or guideline card. Preserve explicit missing
source evidence and display-schema-1/2 compatibility.
Keep candidate-specific measurement/phase/context uncertainty beside the
conditional evidence. Do not repeat a generic disclaimer as card filler or
replace quantitative reliability, source conditions or the adjacent CYP2D6
limitation. Preserve old runs as recorded: section framing may be current UI
context, but do not write current findings into historical bundles. Validate
saved/unavailable/historical views, filters and CLI/dashboard parity offline.

<a id="next-open-step-m104-guideline-linked-cards"></a>

### M10.4 entry contract (implemented; retained for review)

The [M10.3 diff review](review_m103_session.md) fixes incomplete saved-text
reporting and strengthens real-filter acceptance. Complete saved evidence is
required for the adjacent recorded notice; partial text stays explicit without
mutating the run. The eight-gene caller and saved schema contracts are unchanged.

Audit the frozen CPIC/ClinPGx guideline, recommendation, publication and
lookup joins before authoring phenotype-to-dosing interpretation. Keep
source annotations distinct from clinically established sample phenotypes.
Carry guideline evidence levels and actual cited publications; null guideline
IDs must never attribute unrelated publications. DPYD uses its source
activity-score lookup semantics, G6PD retains native copy count and phenotype
limits, and VKORC1 requires the genotype-linked recommendation audit because
v1.60.0 has no phenotype lookup table. Preserve every conditional candidate
and attach uncertainty by source definition ID. Reuse M10.3's saved CYP2D6
limitation and M10.2's immutable schema-1 evidence rather than inferring
CYP2D6 or manufacturing absent mappings. Record any needed card/bundle schema
extension before implementation; M9.13 confidence remains frozen.

Use the complete frozen `reference.cpic.tables`, not just the small per-gene
`recommendation_keys` projection. Resolve candidate definition IDs to saved
source allele labels and native copy counts; follow their exact `mapping_ids`
and `lookup_ids` through `gene_result_diplotype` → `gene_result_lookup` →
`gene_result`, rather than comparing definition IDs with allele names. Bind
recommendations to the actual `lookupkey`, guideline and drug IDs. A source
recommendation may require multiple genes or extra context: retain all required
conditions, and do not apply it just because one gene overlaps. Keep gene–drug
`pair.cpiclevel`, `recommendation.classification`, and allele-function `strength`
distinct; audit which source field supplies each displayed evidence label.

Every guideline card must retain its source release, row identities, source
population/context limits where supplied, explicit gaps, guideline URL and
actual DOI/PMID evidence. Preserve all compatible phenotype/recommendation
branches; neither a first candidate nor
a first lookup row establishes a person's dosing implication. Use declarative
knowledge entries evaluated by the shared engine, with frozen evidence for both
CLI and dashboard. Existing kinds stop at interpretation, impossibility, computed
and polygenic: record the proposed representation and additive validation contract
before extending them. Do not force a guideline recommendation into an invented
effect size to satisfy an unrelated evidence shape. Keep source licence/opt-in
provenance attached; fetched recommendation payloads must remain outside Git.

Acceptance should bind real public source identities/joins before synthetic
substitution, then cover phase/candidate conflicts, multi-gene requirements,
missing phenotype/recommendation/publication rows, drug-specific functions,
DPYD activity expressions, G6PD copy models and VKORC1 genotype keys. Preserve
rarity/imputation uncertainty and numeric PPV scope. Verify cache-independent
save/reload, unavailable/historical states and CLI/dashboard parity offline.
M10.5 remains the separate once-per-section prescribing-tool framing item.

### M10.1 entry contract (implemented; retained for review)

Historical contract from `bb37486`, before M10.1 source fetching. The accepted
state and M10.2 instructions above supersede this checkpoint's local conditions.

M10.1 builds public reference ingestion and offline allele-definition/phenotype
inspection. Sample diplotype calling is M10.2; guideline-linked cards are M10.4.
Follow the [M10 roadmap](../phase1_roadmap.md#m10--pharmacogenomics).

- Reuse the existing optional manifest IDs `pharmgkb` and `cpic`; do not add
  duplicate sources. Neither source directory was present at the original handoff.
  PharmGKB/ClinPGx archives have rolling filenames and explicit share-alike opt-in.
  Recheck URLs, current sizes, terms and archive contents before refreshing pins.
  CPIC declares the pinned v1.60.0 full/inserts SQL dumps; inspect their actual
  schemas, definitions and licence rather than assuming the manifest's capability
  descriptions establish coverage.
- At entry, PharmGKB declared `extract_zip`, an unimplemented
  post-process step. Supply a verified executor or an explicit domain-specific
  ingestion step with safe archive containment, atomic outputs, source/checksum
  binding and offline verification. Keep fetched payloads and derived reference
  caches outside Git; do not vendor archives or definition tables.
- Establish where complete star-allele definitions, allele functions and
  diplotype-to-phenotype tables actually reside. Clinical annotation/variant ZIPs
  alone must not be treated as proof of full definition coverage. Audit any extra
  required primary source and its licence before extending the manifest.
- Normalize definition coordinates/alleles to verified GRCh37 forward-strand keys,
  retaining rsID merge identity, source release, definition version and citations.
  Preserve absent/conflicting definitions and unsupported structural/CNV alleles
  as explicit states. Build one versioned data contract and offline CLI inspection
  with provenance, for later use by the shared engine and both front-ends.
  Keep M9.13's v1 frozen confidence arithmetic stable; any later PGx-specific
  method or saved-contract extension needs a recorded versioned schema/format plan.
- Synthetic tests must cover malformed/unsafe archives and SQL/tabular input,
  ambiguous allele/build representations, missing mappings, licence opt-in,
  checksum/source drift, restart/reuse and complete saved reference validation.
  Validate ingestion against the full fetched sources before acceptance; Windows
  compatibility and privacy gates remain mandatory.

The tractable calling scope for M10.2 is CYP2C19, CYP2C9, VKORC1, SLCO1B1, TPMT,
DPYD, NUDT15 and G6PD. CYP2D6's `cyp2d6_structural_variation` limitation card
already shipped in M3.7; M10.3 must place it beside called diplotypes, not author
a duplicate. M9.13's selected-evidence ancestry comparison is available to later
cards; PRS transfer ceilings remain specific to PRS.

Useful source-preparation commands (audit rolling metadata before fetching):

```text
genetics refs probe --only pharmgkb --only cpic --json
genetics refs fetch --only pharmgkb --opt-in pharmgkb
genetics refs fetch --only cpic --opt-in cpic
genetics refs verify --only pharmgkb --only cpic --json
```

The [M9.13 session review](review_m913_session.md) records saved-fit/allele/type
validation fixes and preservation of damaged-run refusals in card detail views.

### M9.13 entry contract (retained for review)


M9.13 saved contract and confidence decisions are recorded in
[card-level ancestry match](card_ancestry.md) before implementation: format 18,
shared 1000 Genomes placement, selected-outcome comparisons and variant-specific
weighted confidence without borrowing PRS transfer ceilings.

Card-level ancestry match and the `{ancestry}` placeholder are the remaining
M9 task. Use the run's own 1000 Genomes placement and its reported
super-population; do not invent a mapping from AADR sampling-country labels.
Share one placement between single-marker and polygenic evaluation and keep
CLI/dashboard computation identical. State matched, mismatched, declined,
not-run and unknown-study-population states explicitly. M9.12's ACE study
population is `UNKNOWN` and ACTN3 is `MULTI`: neither means measured agreement.

Audit the actual evidence before choosing confidence consequences for common
large-effect or functional variants; PRS transfer ceilings cannot be applied
mechanically to their different claims. Preserve low-confidence findings,
per-marker frequency/quality gates and outcome-specific null evidence. Bind
the selected study population to the matched outcome, not an unused parent
estimate. Verify the placeholder on the face and detail, plus frozen
CLI/dashboard parity and historical-bundle behavior. Record any new saved
contract here before changing schema or format; immutable saved runs must
retain their original evidence and unknown ancestry state.

Start by tracing `run/pipeline.py::observations`, the existing
`ancestry/context.py::_reference_population` placement, `pgs/portability.py`
and `engine/evidence.py` template context. Interpretation observations
currently leave ancestry match unknown; the run's AADR result cannot supply
1000 Genomes super-population labels. Define the shared 1000 Genomes context
and selected-outcome study comparison first, then wire `{ancestry}` and saved
CLI/dashboard output. Document how unknown, mixed and declined populations
affect each evidence class before changing confidence or the saved contract.
Use the portable Java 17 setup recorded in the M9.12 audit for native checks;
the system Java 8 is insufficient for bref3.

<a id="next-open-step-m911-sleep-and-circadian"></a>

## Accepted M9.11 sleep and circadian

M9.11 is accepted on 2026-10-13:
PGS002209 evening preference, PGS002196 log sleep duration including naps,
and PGS002149 ordinal sleeplessness. Exact release evidence, phenotype coding,
direction and calibration limits are documented in the
[model audit](sleep_circadian_prs.md). All 2,885 unique checks pass with five
existing Windows skips, including the four new synthetic interface cases.
Full card lint (64/294/35 keys), all four strict type targets, lint/format,
fixture reproduction and staged privacy scanning pass. Full-model acceptance
completed in the separate private `acceptance/m911` checkpoint, reusing all
verified M9.9 inputs and full-autosomal dosages: all three full reference
preparations, six scoring checks and six disk-read validations pass. Both
acceptance records report `passed`, the checkpoint is `complete`, and the
runner finished with an empty error log. A final check reverified all reusable
inputs and retained checkpoint files. No imputation was rerun or model reduced;
no engine/schema/renderer change was needed.

The [M9.11 diff review](review_m911_session.md) confirms the exact releases,
evidence and pins, and fixes a test gap that accepted all three reversed
face directions. Directed phenotypes are now bound before synthetic
substitution and in saved CLI/dashboard output; three mutation regressions
reject those inversions. All 62 card tests, all four strict type targets and
full card lint pass. Six retained native card model/direction/evidence
bindings pass without changing or rescoring their frozen records. M9.12
subsequently completed and carried these direction checks into model authoring;
M9.13 is now the next open step.

### M9.11 entry contract (retained for review)

Author and pin cited public sleep/circadian models on the shared PRS engine,
knowledge schema 4 and bundle format 17. Distinguish chronotype, reported sleep
duration and insomnia; do not convert a reference score into a person's bedtime,
sleep hours or a diagnosis. HLA-linked narcolepsy needs the separate HLA
capability, not an inferred diagnosis from one tag SNP.

Audit each exact model's phenotype coding and direction, training/evaluation N,
ancestry, per-score licence, performance and public release against primary
sources. Retain all source rows and state unknown direct effects and outcome
calibration. Bind each actual model and evidence before synthetic substitution;
verify per-card saved CLI and dashboard evidence rather than aggregate sets.

Reuse the verified durable inputs in `acceptance/m99/standins` and all 22 full
autosomal dosage files located by its `imputation.json`, with matching provenance
in `public-imputation`. M9.10's completed private runner demonstrates reuse,
full-row preparation/scoring, process-tree resource measurement and disk-read
validation. Preserve both accepted checkpoints and use a separate private M9.11
directory. Do not rerun completed imputation or reduce a model for speed.
Genetic values, coverage summaries and input/output hashes stay outside Git
and out of chat. Synthetic/interface, card/type/lint/fixture and privacy gates
remain required. The unchanged renderer's prior browser visual check is still
unavailable; no new screenshot review is claimed.

<a id="next-open-step-m910-substance-use-and-behavioural-propensity"></a>

## Accepted M9.10 substance use and behavioural propensity

The entry and acceptance contract below is retained for review.

Author and pin public models on the existing shared PRS engine. The roadmap's
GSCAN excluding-23andMe sample sizes are context, not automatically the N of a
selected score. Verify each exact public model/release, score-specific licence,
phenotype, discovery/evaluation N, study ancestry and reported performance against
primary sources. Keep population association distinct from causal/direct effects;
state unknown within-family attenuation and outcome calibration explicitly.
Use complete matched absolute outcome rates only where actually published.
Retain every source row and keep confidence, coverage and portability visible.
Include sourced unflattering results without moralising or a confirmation gate.

Distinguish initiation, consumption quantity and dependence: weights and evidence
for one endpoint do not establish another, current substance exposure or a
diagnosis. Preserve published effect units, source population and absolute/base
rates where available; state missing calibration instead of inventing it. Do not
apply education's contextual within-family attenuation to these models.

### M9.10 implementation and acceptance contract

- Start with knowledge authoring and manifest/lock pinning on schema 4, bundle
  format 17 and the shared engine. Record any needed engine/schema change here
  before implementing it. Missing references must leave visible unrun cards with
  their fetch command; confidence must never filter a card.
- Bind each authored card to its exact score ID, source, phenotype, citations,
  evaluation N, effect and interval **before** normalizing model IDs to a synthetic
  fixture. Check those quantities per card after bundle reload and in CLI and
  dashboard output. The [M9.9 review](review_m99_session.md) shows why aggregate
  sets of effects/counts miss swapped models.
- Reuse the durable public execution inputs under
  `%LOCALAPPDATA%/genetics-analysis/acceptance/m99`: the two normalized
  `standins/*.public-array.parquet` inputs and `standins/imputation.json` locator.
  Its `directory` and `dosage_files` fields point to the copied full-autosomal
  dosage files under `public-imputation`; load the matching `imputation.run.json`
  provenance there. The retained private runner demonstrates reconstruction of
  `ImputationResult` and reuse of its `iter_dosages` factory. Verify integrity
  locally, retain all 22 complete dosage files and the unchanged provenance, and
  keep all genetic artifacts and hashes outside Git and out of chat. Do not dump
  the locator or checkpoint JSON into chat.
- Prepare each new model's full reference, retaining every source row. Measure
  extraction, scoring, record size and peak process-tree memory. Check default-on
  imputed scoring and explicitly non-imputed scoring on the two public ancestry
  stand-ins; record mode, both-phase coverage and portability. Do not rerun
  completed imputation or reduce its panel. These panel members test execution,
  not predictive calibration.
- Write complete score/card records, then read each pair from disk and run frozen
  validation. Keep acceptance outputs in a separate private M9.10 directory;
  preserve M9.9's accepted records and measurements. Run the relevant synthetic
  pipeline/bundle/CLI/dashboard checks, card lint, type/lint/fixture and privacy
  gates for the actual diff before acceptance.

M9.10 is accepted as of 2026-10-13. Three public
UK Biobank-only models are authored, licence-checked, fetched and pinned:
PGS002126 ever smoking, PGS002152 less-frequent alcohol intake and PGS002124
self-reported substance/behavioural addiction. Exact phenotype counts,
partial-r evidence and alcohol direction are verified against the authors'
release/code. GSCAN public weights exclude 23andMe, whereas its performance
methods use all studies except Add Health; exact public-release performance
binding could not be established, so those metrics are not substituted.
All 55 card tests and full local dbSNP lint (61/288/35 keys) pass. Full-scale
public-stand-in acceptance passed in a separate private `acceptance/m910`
checkpoint, reusing all 22 verified durable dosage files and both normalized
inputs without rerunning imputation or changing M9.9's accepted records.
All three complete references, three default-imputed and three explicit
no-impute checks, and six written-record reload validations pass. Both acceptance
records report `passed`; the checkpoint reports `complete` and the runner
completed successfully. All 2,881 unique checks pass with five Windows skips;
all four strict type targets, lint/format, fixtures and privacy gates pass.
See the [model audit and acceptance record](substance_use_prs.md).
The unchanged renderer's prior browser visual check remains unavailable.

## Accepted M9.9 psychometrics

Three public UK Biobank-only LDpred2 models are authored and reference-pinned:
cognition (PGS002135), qualifications-to-years (PGS002231), and neuroticism
(PGS002213). They use schema 4, bundle format 17 and the existing renderer;
no shared-engine/schema change was needed. Phenotype-specific training counts,
held-out residual-variance associations and unknown within-family effects are
explicit. The synthetic suite and native arithmetic check pass 2,877 unique
checks, with five documented Windows platform skips remaining. All four strict
type targets, lint/format, fixture reproduction and full card lint pass
(58 cards, 282 renders, 35/35 marker keys).

Accepted on 2026-10-12. All three complete reference preparations, three
default-imputed and three explicit no-impute public-stand-in scores passed.
All six written score/card pairs were read from disk and passed frozen validation
of their retained digest, coverage, distribution, portability, display and
reliability. No source term was truncated. The checkpoint was paused on
2026-10-11, then resumed with both completed scores and full imputation reused.

The completed durable checkpoint remains at
`%LOCALAPPDATA%/genetics-analysis/acceptance/m99`, outside Git. Both acceptance
and retained-validation records report `passed`; the checkpoint reports
`complete`, and the runner exited successfully. Keep all contents private,
including hashes; do not paste genetic summaries into chat. The
[model audit and resource record](psychometrics_prs.md) records measured costs
and the unavailable browser visual check. The renderer is unchanged; synthetic
HTTP and chart geometry checks pass. Broad code checks already pass; repeat
them only when new changes, failures or unresolved concerns justify it.

The [2026-10-13 diff review](review_m99_session.md) confirms the shipped model
bindings, primary-source evidence, reference pins and score-specific licences.
It strengthens the synthetic test to reject swapped model IDs and per-card
evidence: both ancestry cases accepted a model swap before the fix and reject
it now. All 51 card tests and all six retained score/card revalidations pass;
full dbSNP lint remains 58 cards, 282 renders and 35/35 keys. No scoring,
imputation, schema or renderer change was needed.

### M9.9 entry contract (retained for review)

M9.9 is authoring and reference pinning on the existing engine. Verify each
selected model's permissive score-specific licence and exact public release,
including reduced-N excluding-23andMe cohorts where applicable; do not replace
that model's N with a larger publication headline. Check effect and within-family
attenuation against primary papers for the same phenotype/model. State unknown
direct effects explicitly instead of borrowing an attenuation from another score.
Keep reference distributions and intervals visually dominant, with no individual
point estimate or diagnosis. Use complete matched absolute decile rates only
where actually published; keep confidence, coverage and portability visible.
Retain every source row/evidence term and measure full-scale extraction/scoring
cost before acceptance. Record any needed engine/schema change here before making
it. The existing full public-stand-in imputation may be reused without rerunning
the completed native jobs; private artifacts stay outside Git.

## M9.5–M9.6 review and M9.7 entry contract

The [diff review](review_m96_session.md) of `857abe4..de6a4d1` fixed three defects, each
reproduced by a regression first:

- **A score missing from the fetched metadata aborted the whole run.** It now leaves only
  its own card `not_run`, with the refetch command.
- **Some structural damage escaped the bundle reader.** `AttributeError` and `IndexError`
  in polygenic validation now become `BundleError`.
- **The face text was false above an attenuation of 1.** Within-family estimates above 1
  are now worded as such, not as attenuation.

Review acceptance: **2,837 tests passed, five existing Windows skips**, with pinned PLINK
2/PLINK 1.9/Beagle/bref3 and Java 17. All four strict type targets, lint/format, fixture
reproduction, full dbSNP card lint (51 cards, 268 renders) and staged privacy scanning
pass. No known blocker remains for M9.7.

**M9.7 goal:** Physical-health PRS cards. This should be authoring and reference pinning
only; the engine path, bundle format and renderer exist. If a change to the engine turns
out to be needed, record why in this file before making it.

Contract for M9.7:

- **Scale findings recorded before implementation (2026-10-10).** The reference extractor
  retains the raw VCF calls for every requested locus until the chromosome finishes.
  For a genome-wide score this holds thousands of Python objects per locus, beyond
  the already necessary compact effect-dose matrix. Before authoring the large CAD
  card, change extraction to resolve one coordinate group at a time, preserving all
  duplicate records at that coordinate, full-file digest verification and every
  row's exclusion state. Reject out-of-order panel coordinates rather than resolving
  incomplete groups. This changes memory use, not the scoring method, cached evidence
  or bundle format. A synthetic memory regression must demonstrate the reduction.
  The live GPS_Mult file also declares its original build as `hg19`, with explicit
  harmonized `GRCh37` coordinates. The parser currently rejects this documented
  assembly synonym before considering harmonization. Accept the hg19/hg38 synonyms
  with canonical build selection while retaining the source headers verbatim; an
  unknown build must still fail. Cover both original and harmonized paths.
  Final presentation review also found that display schema 1 carries only the
  currently displayed phase's coverage. Before shipping actual health cards,
  display schema 2 must carry both phases' row/variant coverage, scored-weight
  shares and explicit unavailable states, and show them on the face/detail.
  Continue deriving historical schema-1 cards exactly as before on reload;
  bundle format 17 need not change because the existing display is versioned.
  Genuine full-panel imputation then exposed an M8 reader assumption on chr3:
  Beagle emitted the same variant twice because the pinned reference itself
  contains it twice (verified against the reference, without logging calls).
  Preserve source-verified untyped duplicates up to their exact multiplicity;
  continue refusing typed repeats and any unverified/excess repeat. Discover
  the multiplicities during the existing full, semantically verified decode.
  Retain both dosage records so the existing card/PRS ambiguity handling applies,
  rather than deduplicating or choosing one. No saved record format changes.
  The resumed full-panel run then reached chr8, where Beagle itself refuses
  two native-equal markers (same chromosome/position/alleles/END). Local comparison
  verified that their complete phased reference GT vectors are identical.
  Before continuing, add a lossless native-input representation: fold only these
  redundant copies, retain every sample and every distinct genetic observation,
  and keep the original panel plus source/multiplicity/semantic-hash proof.
  Conflicting phased vectors must fail, never select one. Bind the actual native
  input in frozen provenance and validate both this proof and source-verified
  output multiplicities on saved reload; the current saved dosage reader still
  rejects all repeats. Cover native duplicate failure, unchanged genetic data,
  conflicting duplicates and tampering before resuming acceptance.
  The full default-imputed health-score checks then passed, but the second,
  explicitly non-imputed CAD stand-in exposed another scale defect: display
  quality accumulates weights with ordinary addition while its denominator uses
  `math.fsum`, so all-direct observations can round above the unit interval and
  abort confidence assembly. Before continuing, use accurate summation for both
  quality numerators in the new display schema 2; preserve schema 1's historical
  arithmetic on reload. Keep strict confidence input validation. Reproduce the
  defect with fabricated weights and rerun the second stand-in without repeating
  the completed full-panel imputation or default-imputed native sums.

- **Choosing scores.**
  - Use PGS Catalog scores whose metadata licence classifies as `permissive`, because a
    run cannot opt in to restricted terms (AGENTS.md §4.8).
  - Prefer additive models. Interaction, haplotype or dominance terms make the score
    `unsupported_model`, and the card then renders unplaced.
  - Record the score's GWAS and development ancestry on the card's evidence. M9.5's
    portability will grade it whatever is written, but the card should not contradict
    the catalog.
- **Pinning.** Add one manifest entry per score, modelled on `pgs000001_grch37`: the
  harmonized GRCh37 file `PGSxxxxxx_hmPOS_GRCh37.txt.gz`, fetched and locked.
  `cards lint` refuses a card whose `pgs.source` does not fetch that score.
- **Evidence and citations.** Every number on a card must be cited from the primary
  paper and checked against it, not recalled (AGENTS.md §6).
  - `effect` is the published per-SD (or per-unit) estimate, with its interval and a
    `context` sentence.
  - `ancestry` uses the cards' super-population codes for the derivation study.
  - Set `within_family_attenuation` only where a within-family estimate is published.
- **Absolute rates.** Use `decile_outcomes` only when a paper reports the outcome by
  score decile, with the same measure and population for `base_rate`.
  - Quintiles, percentile bands or odds ratios against the middle are not deciles. Never
    interpolate them into deciles; leave `decile_outcomes` out, and the face says a
    position is not a risk.
  - Health cards are §0.1B's precision case: state the measure, its horizon (`context`)
    and the population exactly.
- **Measure scale before shipping a large score.**
  - Real-panel acceptance so far is PGS000001, 77 rows. Most physical-health scores
    have 10^5–10^6 rows.
  - Before shipping one, measure the reference extraction (time, memory, cache size).
  - Measure the dosage pass in a default imputed run. Since 2026-11-01 a run reads the
    imputed stream once (`engine.DosageIndex`), for card inputs, every score and PGx,
    instead of once per score (48–69 min each at acceptance) and once each for card
    inputs and PGx. *Measured 2026-11-02 on a public stand-in:* the one read takes
    29 min over 81,272,000 records and keeps those at 1,316,215 loci, from imputation
    until PGx calling. The run peaked at 10.9 GB, while scoring.
  - Measure the size of its saved record: it keeps every term with its native evidence.
    *Measured 2026-11-01 on the synthetic export without imputation:* PGS002143's record
    (966,283 rows) is about 1.9 GB parsed, 743 MB as compact JSON and 46 MB compressed;
    37% of the per-term JSON is the copied scoring-file columns and 41% the two phases'
    doses. Bundle format 25 stores each record compressed in its own file and checks one
    at a time. The terms stay whole because a saved run re-checks coverage, the other
    allele and unusable rows' raw definitions from them without the scoring file. *With
    imputation (2026-11-02):* about 62 MB compressed per genome-wide record, and 701 MB
    for the pack's 14.
  - Report coverage before and after imputation for each score on the real panel.
- **Acceptance.** Run the full `cards lint`, fetch and lock every new score, and put
  public 1000 Genomes stand-ins through the polygenic stage. Then **look at the
  dashboard**: browser screenshots timed out in M9.6, so the fixed chart has been checked
  only by geometry assertions.
- **Still open.** The M9.13 decision on single-marker ancestry match and `{ancestry}`.

## Implemented M9.6

`pgs/cards.py`, `pgs/runner.py` and `web/polygenic.py` put polygenic scores on cards. See
[the guide](pgs_cards.md).

- **Schema.** Knowledge schema 4 adds `kind: polygenic`: `pgs: {id, source}` naming a
  manifest entry, `trait`, plain-text `summary`/`detail` (no placeholders), evidence, and
  optional `decile_outcomes` (ten absolute rates plus base rate, cited to one of the card's
  citations). `cards lint` checks the manifest source fetches that score.
- **Run.** `genetics run` prepares every polygenic card before the export is read
  (scoring-file lock, licence gate, public 1000 Genomes extraction), places the sample once,
  then scores each card with the M9.2-M9.5 functions. Absent inputs give `not_run` with the
  fix; a lock mismatch raises. A run gives no restricted-licence opt-in.
- **Bundle format 17.** `pgs.run.json` holds each card's private score record (from
  format 25, one `pgs-<card id>.run.json.gz` per card, indexed by `pgs.run.json`; from
  format 26, ASCII-escaped so its digest is checked on the stored bytes). Reading
  re-derives the record's coverage, distribution and portability, then the card's display,
  reliability and face text, and refuses any disagreement or an unpaired record.
- **No point estimate.** The display carries the reference histogram and quantiles and the
  person's 95% interval, deciles and score-unit range. The person's sum and point
  percentile never leave the private record. The face states the interval basis, coverage,
  portability, within-family attenuation and decile rates with the base rate, or that a
  position is not a risk.
- **Confidence.** `calculate_polygenic_confidence` reuses the calculator's weights, with
  comparable score weight in the frequency slot. Ceilings reuse existing thresholds:
  evidence, DR2 on weighted quality, `ancestry_ceiling` bands for coverage and ancestry.
- **Dashboard.** The face has a compact histogram with the interval band. The detail has a
  full chart, then tables for coverage, quality, portability, decile rates and every
  confidence input. The colour pair passed the dataviz validator in both themes.
- **Fixed while there.** The section nav counted only `matched` cards as interpretations,
  disagreeing with the run manifest and the grid for every computed card. It now counts
  `computed` too. An unknown manifest source raised `ManifestError` uncaught in the runner;
  it is now a reason.
- **Carved out.** Single-marker `ancestry_match` and `{ancestry}` are now **M9.13**. They
  are a decision about the evidence: they would re-tier every card in the pack.

Acceptance: **2,834 tests passed, five existing Windows skips**, with pinned PLINK
2/PLINK 1.9/Beagle/bref3 and Java 17.

Thirty-five new synthetic cases cover:

- schema refusals;
- the confidence ceilings;
- a run through the bundle, CLI JSON and dashboard;
- not-fetched, restricted-licence and no-panel cards that still render;
- nine tamper refusals, plus a format-16 bundle carrying a polygenic card;
- lock verification of the scoring file;
- manifest-source lint;
- chart geometry;
- the nav count.

Real-data checks used public data only. Public PGS000001 and the real 1000 Genomes panel
were run through the polygenic stage with two public samples' own genotypes:

- HG00096 (GBR) placed in EUR (503 samples), interval at the 41st to 49th percentile;
- HG00403 (CHS) placed in EAS (504 samples), interval at the 90th to 95th percentile,
  with its tier capped by ancestry, as M9.5 intends for a European-only GWAS.

A browser render of a synthetic run showed two defects, both since fixed: SVG labels
scaled with chart width, and the leftmost tick label clipped. Screenshots of the fixes timed
out in the browser tool, so the fix is covered by geometry assertions rather than re-viewed.
Other gates: all four strict type targets, lint/format, fixture reproduction and the full
dbSNP card lint (51 cards, 268 renders) pass. No personal export or private run was used.

M9.7's entry contract is at the top of this file.

## Implemented M9.5 (M9.6 entry contract, done)

`pgs/portability.py` gives every **schema-4** score result a versioned `portability`
block and the numeric `ancestry_match` that `calculate_confidence` accepts. `score()`
builds it, and `attach_reference()` rebuilds it once the 1000 Genomes placement exists.
`genetics pgs portability RESULT --json` recomputes it and refuses any disagreement.
Schema 1–3 results are recomputed and labelled `recomputed_legacy`. See
[the guide](pgs_portability.md).

- **Cited mapping, not memory.** The placed 1000 Genomes *population* is mapped to a
  Morales et al. 2018 Table 1 category (doi:10.1186/s13059-018-1396-2, verified against
  the Europe PMC full text). That category is mapped to a PGS Catalog display category
  using the catalog's own ancestry documentation (verified the same day).
  Super-populations are not used: KHV is South East Asian, and ACB/ASW are African
  American or Afro-Caribbean. Categories with no 1000 Genomes population are never given
  a nearest code.
- **Lower bound, not renormalised.** The GWAS-source stage drives; development drives only
  when GWAS is empty; evaluation, which is weighted by sample sets, never drives. Not
  Reported, multi-ancestry, unrecognised labels and unreported stages are kept as an
  indeterminate share. They raise only `match.upper_bound`.
- **Sample states.** A decline by either panel gives `0.0`, judgment
  `sample_unrepresented`; a 1000 Genomes placement cannot rescue an AADR decline. A
  not-run or saved-only sample gives `None`, judgment `not_computed`. Placed populations
  in another display category within the decline threshold are recorded as alternatives.
- `confidence_ceiling` comes from the new `engine/confidence.py::ancestry_ceiling`, which
  `calculate_confidence` now also uses, so the record and the calculator cannot disagree.
- One real-data defect was found and fixed: PGS004230 publishes `Not Reported:0`, and the
  first parser refused zero shares. All 6,991 metadata rows now parse; 16 report neither
  GWAS nor development ancestry.

Acceptance: **2,799 tests passed, five existing Windows skips**, with pinned PLINK
2/PLINK 1.9/Beagle/bref3 and Java 17. Twenty-seven new synthetic cases cover:

- the full contract matrix: matched, mismatched, multi-ancestry (including and excluding
  European), unreported, development fallback, nothing reported, KHV against an East
  Asian study, declined by each panel, not run and saved-only;
- non-filtering: sums, terms, coverage and percentiles are unchanged, and the calculator
  still returns a result at every tier;
- equality across the API, the CLI and the persisted file, with a cold and a warm
  extraction cache;
- seven tamper refusals and legacy recomputation.

Six mutations each fail a test: AADR rescue, KHV as East Asian, renormalising Not
Reported, multi-excluding-European as indeterminate, declined as neutral, and no
development fallback.

Two real-data checks used public data only:

- Every one of the 6,991 catalog metadata rows went through the mapping for six stand-in
  placements.
- Six public 1000 Genomes samples were built from their own genotypes, keeping a random
  70% of PCA markers, and placed through the real placement with public PGS000001. Each
  placed in its own population or its nearest neighbour (HG00096 GBR as CEU). Only CEU
  matches PGS000001's European-only GWAS; the rest are `mismatched`.

  Admissible neighbours are broad: GBR also admits CLM and PUR, and CHS admits KHV. That
  is why the number follows the named population and the alternatives are recorded beside
  it, rather than taking the worst case. These samples are in the panel, so this checks
  the wiring, not calibration.

A real `genetics.exe pgs score --no-impute` on the synthetic fixture reloads as
`persisted_verified`, with `not_computed`, because the fixture shares too little with
1000 Genomes to be placed. All four strict type targets, lint/format, fixture reproduction
and full dbSNP card lint (51 cards, 268 renders) pass. No personal export or private run
was used.

**M9.6 entry contract** (PRS card renderer):

- **Card face.** Put the portability judgment, the matched share *and* the upper bound,
  the ceiling and the reason on the card face. When `alternative_display_categories` is
  non-empty, say so. When `merged_morales_categories` has more than one entry, state that
  the catalog does not separate those groups. Never show `ancestry_match` alone, since 0
  means "not demonstrated" as well as "mismatched".
- **Card confidence.** Build it with `calculate_confidence(...,
  ancestry_match=portability["ancestry_match"])`. Coverage
  (`fraction_of_score_weight`), imputed weight share and DR2 bins from M9.3/M9.4 are
  confidence inputs the card must also weigh; M9.5 recorded them, it did not fold them in.
  No new threshold may be invented without a cited basis.
- **Run pipeline.** The `{ancestry}` template placeholder now names M9.6, and single-marker
  card `ancestry_match` is still unset. Both need the 1000 Genomes placement carried into
  `genetics run`, which today holds only the AADR context. Reuse
  `pgs.portability`'s mapping rather than writing a second one.

## M9.3–M9.4 review and M9.5 entry contract (done)

The [diff review](review_m94_session.md) moves all public panel verification and
extraction ahead of personal input, removes the private reference workspace, binds a
prepared reference to its score, and makes `pgs placement` refuse structurally damaged or
phase-contradictory blocks. Six regressions reproduced the defects before the fixes.
It also ran the two paths earlier acceptance had not: five public 1000 Genomes samples
(their own genotypes, 70% of PCA markers) were placed in their true super-populations, and
parallel extraction ran under the real `genetics.exe` (3 min 52 s cold, 12 s cached).
Review acceptance: **2,772 tests passed, five existing Windows skips**, pinned native tools
and Java 17; four strict type targets, lint/format, fixtures, full card lint and staged
privacy scan pass. No known blocker remains for M9.5.

**M9.5 goal:** turn study-to-sample ancestry into the numeric `ancestry_match` that
`engine/confidence.py::calculate_confidence` already accepts (a fraction in [0, 1], or
`None` for "not computed"), and record a per-score portability judgment on every PRS
result, per AGENTS.md §4.4. Calibration, not suppression: nothing may filter a card.

Inputs that now exist, all in each schema-3 score result:

- **Sample, 1000 Genomes vocabulary:** `reference_distribution.placement` and `.group`.
  When placed, `group.super_population` is one of AFR/AMR/EAS/EUR/SAS, the panel's own
  `super_pop` label, which is exactly the vocabulary cards declare for study ancestry
  (`engine/cards.py::Ancestry`). This closes the vocabulary gap M5.8 recorded for the
  *sample* side without any hand-written mapping. `declined` and `not_run` carry reasons.
- **Sample, AADR:** the run's `ancestry` block (M5.9's 100 Human Origins populations,
  region = sampling country). Finer than 1000 Genomes and the place where unrepresented
  groups (Aboriginal Australian, Khoisan, parts of MENA) are *declined*. A sample the AADR
  placement declines must not be rescued to "matched" by a coarser 1000 Genomes call.
- **Study, PGS Catalog:** `score_definition.metadata` rows carry three GWAS Catalog
  ancestry-distribution columns: `Ancestry Distribution (%) - Source of Variant
  Associations (GWAS)`, `- Score Development/Training`, `- PGS Evaluation`, as
  `Label:percent|...` text (PGS000001: GWAS `European:100`; evaluation
  `European:72.7|Not Reported:18.2|East Asian:9.1`). Empty and `Not Reported` occur.
- **Comparability:** per-phase `fraction_of_person_scored_weight`,
  `fraction_of_score_weight`, `person_dose_basis.imputed_absolute_weight_fraction` and
  M9.3 coverage. These are confidence inputs beside ancestry, not ancestry itself.

Contract for M9.5:

- **The study-label mapping must be cited, not written from memory** (AGENTS.md §6). The
  catalog's labels are the GWAS Catalog ancestry framework's broad categories; its
  published definition (Morales et al., Genome Biology 2018) is the candidate source.
  Verify the DOI and the category list against the paper before encoding them. Categories
  with no 1000 Genomes super-population counterpart (e.g. Greater Middle Eastern,
  Oceanian, African American or Afro-Caribbean as distinct from African) must map to an
  explicit partial or unknown state, never to the nearest code.
- Parse distributions per stage. Decide and document which stage drives the match;
  GWAS-source ancestry is what effect sizes were estimated in. `Not Reported` and empty
  stay visible as unknown share, never renormalized away.
- `declined` lowers portability and is never neutral. `not_run` stays `None` (unknown).
  Saved-only results (no reference placement) must say so rather than reuse a pooled
  comparison as if it were matched.
- Keep every input and the derived number in the result, versioned, and revalidate on
  reload as M9.3/M9.4 do. Replace the `portability: "not_computed_M9.5"` placeholder.
- Acceptance should cover matched, mismatched, multi-ancestry, unreported, declined
  (both panels), not-run and saved-only cases, plus a non-filtering assertion and
  cache-independent CLI/API/persisted equality, all on synthetic data.

## Implemented M9.4

`pgs/reference.py` scores 1000 Genomes phase 3 (2,504 samples) over exactly the rows the
person's phase scored and the panel resolves, through the person's effect-dose matrix and
PLINK invocation, then places the person by mid-rank percentile with a Wilson 95% interval.
Score artifacts move to **schema 3** (`reference_distribution`, per-phase `percentile`).
`genetics pgs score` computes it by default (`--no-reference` is the recorded opt-out);
`genetics pgs placement RESULT --json` recomputes every statistic and refuses mismatches.
See [the guide](pgs_reference.md).

- The comparison group comes from a new 1000 Genomes placement
  (`ancestry.context.place_among_reference_populations`, M5.5's decline rule in 1000
  Genomes' own PCA space). Placed: super-population primary, population and pooled beside
  it. Declined, unplaced or saved-only: pooled, `ancestry_matched: false` with the reason.
- Allele orientation is the engine's shared `orient()`; palindromic rows, ambiguous or
  four-allele loci, missing calls and ploidy conflicts are excluded and counted. Panel
  VCFs are verified against the lock in the extraction pass; the public extraction is
  cached by score and panel identity.
- `person_dose_basis` records imputed weight share against sequenced hard-call references;
  shrinkage is recorded, not corrected.

Acceptance: **2,766 tests passed, five existing Windows skips**, with pinned PLINK 2/PLINK
1.9/Beagle/bref3 and Java 17. Nineteen new synthetic cases; mutations of the palindrome,
ploidy, group-restriction and lock-digest guards each fail a test. Real-panel acceptance
(public PGS000001, synthetic person): 70/77 rows resolve and every one of 2,504 reference
sums matches an independent PLINK scoring of the raw 1000 Genomes VCFs within 8.4e-6.
All four strict type targets, lint/format, fixture reproduction and full dbSNP card lint
pass. No personal export, private run or new reference payload was used.

M9.5's entry contract follows above; M9.5 is implemented (top of this file).

## Implemented M9.3 and M9.4 entry

`pgs/coverage.py` derives versioned per-score coverage (`schema_version` 1) from the term
evidence in every score result. Score artifacts move to **schema 2**, which guarantees
retained exclusion proof and phase states. `genetics pgs score` embeds it and prints one
line per phase; `genetics pgs coverage RESULT [--scoring-file F] --json` reloads, recomputes
and refuses any mismatch. See [the guide](pgs_coverage.md).

- Source denominators: all authored weighted rows, model-eligible/ineligible by reason,
  unique allele-defined variants, unique positions, repeated rows, multiple effect alleles,
  multi-variant positions, and undefined rows with their raw definitions.
- Before and after are independent. `not_recorded`/`disabled` phases are `unavailable`
  with null metrics; no-overlap is a real 0.0. Unsupported models keep observed rows but
  have null scored fractions. Position presence and usable-dose coverage are separate.
- Original probes (before only): probe count, called positions and duplicate positions as
  identical, complement-concordant, conflicting, insufficient-calls or unclassified.
- Quality is described, never applied: sources, ploidy, methods, DR2 min/max, descriptive
  tenths with absolute weight, and unknown-quality reasons (`not_estimated:<method>`,
  `allele_quality_unknown` for multiallelic REF).
- Schema-1 files are recomputed as `recomputed_legacy`; phase availability comes from the
  table hash and imputation mode, and missing excluded-row proof stays `unknown` with
  evidence-fraction bounds. Bundle format stays 16.

Acceptance: **2,746 tests passed, five existing Windows skips**, with pinned PLINK 2/PLINK
1.9/Beagle/bref3 and Java 17. Twenty new synthetic cases cover the M9.3 contract below,
including nine corruption cases each confirmed to fail at its intended check. All four
strict type targets, lint/format, fixture reproduction and full dbSNP card lint (51 cards,
268 renders, 35 references) pass. No personal export, private run or new reference was used.

**M9.4 entry (implemented; see the top of this file):** a reference distribution and percentile placement for each score, computed
within the ancestry-matched reference group where possible. Score the reference panel with
the same `pgs/engine.py` matrix path and the same allele/ploidy rules so the person and
the distribution share one definition; record the panel, group and per-score coverage of
the reference itself. Where the person's coverage (M9.3) differs from the reference's,
the placement must say so rather than compare unlike sums. A declined or unrepresented
ancestry is M9.5's to interpret; M9.4 must not fall back silently to a pooled group.

## M9.1–M9.2 review and M9.3 entry contract

The [diff review](review_m9_session.md) fixes inferred-allele validation, excluded-term
evidence loss, phase-state overwrites, early flag/output validation, filesystem error
boundaries, stale native reports and arithmetic overflow. Nineteen new synthetic cases
reproduced the defects before their fixes; the focused M9 suite passes 135 cases,
including pinned PLINK arithmetic. No known blocker remains for M9.3.
Review acceptance: **2,726 tests passed, five existing Windows skips**, with all pinned
native tools and Java 17. All four strict type targets, lint/format, fixture reproduction,
full dbSNP card lint (51 cards, 268 renders, 35 references) and staged privacy scanning pass.
Cached public-reference parsing also passes offline; no personal export or run was used.

M9.3 should implement coverage in the shared engine and expose it through private
score JSON/CLI for the M9.6 card renderer. Use `ScoringFile.iter_variants()` for the
source denominator and `ScoreResult.record["terms"]` for per-phase observations.
Keep a versioned persisted coverage contract and validate it when reloading.

- Define both the numerator and denominator. Count all authored weighted rows, including
  unresolved/excluded/model-ineligible rows; distinguish those rows from allele-defined
  unique variants, unique positions and duplicate original probes. Preserve raw definitions
  where a stable allele/locus identity cannot be established.
- Report before and after independently. An `observed` zero dose is covered; a no-call,
  absent marker, allele/strand/ploidy conflict or unsupported definition is not a scored
  term. Position presence and usable allele-dose coverage are separate claims.
- `not_recorded` and `disabled` require unavailable coverage rather than 0%. Saved stage
  direct records are not a complete original-chip inventory. Preserve whole-model
  unsupported and partially scored states even when some individual rows have observations.
- Preserve per-ALT quality and method alongside contributions, including low DR2,
  phase-filled unknown quality, unknown multiallelic REF quality and native haploid doses.
  Quality must not scale dose or hide rows; its confidence use belongs to M9.5.
- Retained exclusion proof may be an original-array probe envelope, one native record or
  an `ambiguous_panel_records` envelope. Older schema-1 score files can lack this proof
  or have overwritten phase states; missing proof must stay unknown or be recomputed.
  PLINK matrix counts and `native_alleles` must never substitute for variant coverage.

Acceptance must cover repeated rows at one locus, multiple effect alleles, concordant and
conflicting duplicate probes, missing/no-call versus observed zero, low/unknown quality,
multiallelic REF, haploid X/PAR, unresolved/special-model rows, original-call precedence,
saved-only input and explicit no-impute. Verify CLI/API/persisted equality and corruption
rejection with synthetic data. M9.4–M9.6 still own distributions, portability and rendering;
M9.3 need not invent a percentile or phenotype interpretation to supply renderer data.

## Implemented M9.2 and next scope

`pgs/engine.py` computes original and post-imputation sums with the pinned PLINK `--score`,
using validated native effect-allele doses in a numeric matrix. The actual locus/alleles,
biological ploidy, original probe evidence and native per-ALT quality remain in the private
record; matrix counts are not coverage. Low/unknown quality never filters or scales dose.
SNP strand, duplicate and ploidy conflicts remain explicit; sequence-resolved imputed
indels require exact sequences, while raw I/D remains excluded. Unsupported models
receive null sums. Used IDs/counts and independent signed-dose arithmetic validate the
native report within the recorded PGEN/text precision bound.

`pgs/workflow.py` reuses shared ingest/ancestry/default-on imputation. `genetics pgs score`
accepts an export (with explicit `--no-impute` only) or a validated saved full stage.
Saved-only scoring cannot invent the original-array sum. Each immutable private
`.pgs-score.json` retains score/metadata/input/stream identities, full used imputation
provenance, PLINK version/binary hash, tool-manifest hash and method/engine versions.
No bundle-format bump or interpretation card is introduced. See [the guide](pgs_scoring.md).

Acceptance: **2,707 tests passed, five existing Windows skips**, with pinned PLINK/ROH/
Beagle/bref3 tools and Java 17. Forty-seven new synthetic cases cover source/dose/quality,
native arithmetic, exact indels, licence/model boundaries, privacy, workflow ordering,
categorical failures and cache-independent saved/CLI equality. All four strict
Windows/Linux × Python 3.11/3.13 type targets, lint/format, fixture reproduction and
full dbSNP card lint pass (51 cards, 268 renders, 35 marker references). No personal
export or new reference/tool payload was used.

**Next M9.3:** turn the saved term observations into per-score before/after variant
coverage with explicit denominators, distinguishing weighted rows from distinct variants,
positions and duplicate probes. Present low-quality and unknown-quality contributions
without filtering them. Before coverage requires the original-array evidence; a saved
stage alone records it as unavailable. Preserve null/no-overlap, unsupported and partial
states. Distribution, ancestry portability and renderer remain M9.4–M9.6.

## Implemented M9.1 and next scope

`pgs/catalog.py` reads the authoritative scores CSV inside the public metadata archive,
retaining every metadata column and duplicate row. `refs/licenses.py` classifies complete
reviewed EBI/CC terms, with explicit restricted, missing, unknown and ambiguous states.
Unknown terms cannot be enabled by restricted-source opt-in. The metadata transform
is now executable in the existing fetch/verify registry and binds its JSON output to
the exact archive and transform through the common checksum/provenance contract.

`pgs/scoring.py` streams format-2 rows, preserving source identities, original/harmonized
builds, all allele/weight columns and special-model features. It rejects malformed/nonfinite
weights and conflicting identities/builds/counts without echoing rows. `genetics pgs inspect`
is the shared offline CLI consumer; parsing computes no personal score and changes no
bundle format. The first selected public source, `pgs000001_grch37`, is in the manifest.
Public acceptance: 6,991 metadata scores and 77 PGS000001 GRCh37 rows, with both hashes
recorded in the lock. No personal export was opened. See [the guide](pgs_ingestion.md).

Validation: **2,660 tests passed, five existing Windows skips**, with pinned native tools
and Java 17. Sixty-nine new synthetic cases cover parser/licence/provenance boundaries,
CLI and privacy ignores. All four strict Windows/Linux × Python 3.11/3.13 type targets,
ruff/format, fixture reproduction and full dbSNP card lint pass (51 cards, 268 renders,
35 marker references). Public-reference CLI/API parity passes with networking blocked.

**M9.1's original M9.2 handoff (now implemented):** implement PLINK score sums from original calls and native imputed dosages.
Call the score-specific licence gate and explicitly support or report special models.
Verify effect-allele orientation, biological ploidy, sum/average and missing-data policy
against the pinned PLINK build using synthetic arithmetic. Preserve dose and quality
separately; DR2 never scales dose. Exhaust/validate parsed streams before accepting results.
M9.3 needs original-array coverage or a saved record, not stage-direct counts alone.
Reference distributions and study-ancestry mapping/`declined` treatment remain M9.4–M9.5.

## M8 overview review

The [overview review](review_m8_overview.md) fixes seven groups of defects: saved scalar
rarity/frequency/hard-call binding, missing allele placeholders, skipped-region ploidy,
phase-handoff byte counts, invalid Beagle option error boundaries, corrupt DEFLATE
handling and missing saved-dosage iterator errors. Thirty new synthetic cases cover
the fixes; all 28 rejection cases reproduced defects before their respective fixes.
Format 16/provenance schema 1 and historical payload meanings remain unchanged.

The final native suite passes **2,591 tests, five existing Windows skips**. All four
strict Windows/Linux × Python 3.11/3.13 type targets, lint/format, fixture reproduction
and full dbSNP card lint pass (51 cards, 268 renders, 35 marker references).
No personal export was opened. There is no known blocker to M9.1's parser/licence work.

### M9.1 accepted implementation scope

The implementation starts with `data/references/manifest.yaml`'s `pgs_catalog_metadata` entry, the
`parse_pgs_score_licenses` step in `refs/postprocess.py` and `refs/licenses.py`.
Implement scoring-file parsing and per-score metadata joins using the current
official scoring-format specification. Preserve PGS id, declared build, allele/weight
definitions and source identities. Bind licences to the metadata CSV's
`License/Terms of Use` column; collection-level permission and scoring-header absence
cannot establish a score's licence. Missing, ambiguous or unknown terms stay explicit
and never default to permissive. Do not hard-code a historical count of licence values.

Exercise malformed rows, nonfinite weights, missing fields, conflicting score/build
identities and licence joins with synthetic inputs. Keep acquisition/provenance within
the existing manifest/fetcher framework, with no reference download required in CI.
Scoring, coverage, distributions and ancestry calibration remain M9.2–M9.5.

`RunBundle.iter_dosages()` streams the full saved stage, including all three sources;
it is not the complete original array. `ImputationEvidence.from_record()` accepts
resolved imputed sources only. Its allele-dose method keeps native dosage and quality
together; direct stage records retain exact observed counts. Phase-filled and
multiallelic REF quality stay unknown. Before-imputation coverage needs original-array
observations or saved coverage; stage-direct counts alone are insufficient. Older
formats must not be given invented full dosages or coverage. The existing population
mapping/`declined` ancestry portability work remains M9.5.

## Implemented M8.7 and next scope

Thirty-two synthetic regressions in `tests/imputation/test_quality.py` prove the
strict rarity ceiling across untyped/phase-filled sources and native haploid/diploid
observations. DR2 1 and strong replicated literature cannot rescue a frequency below
0.00001; equality and the next higher float remain outside that band. Unknown
phase-filled quality stays unknown and contributes zero. Known rare alleles survive
missing companion frequencies; common-only incomplete coverage stays unknown and an
unobserved rare allele does not penalize the call. Multi-marker findings inherit the
weakest marker without averaging quality or assuming phase.

Fully saved format-16 runs retain rarity, selected frequency, source/native dosage and
quality, benchmark scope and caveats in CLI JSON and dashboard face/detail after the
synthetic stage cache and frequency index are removed. Enabled direct probes and
explicit opt-out preserve original observations. ClinVar still consumes original-array
input. Chip 16% and BRCA 4.2% benchmarks stay study-specific and explicitly uncalibrated
for imputation, never individual posterior probabilities. Isolated in-memory bypasses
fail all four below-boundary cases and both missing-companion cases. The shared engine
needed no fix; bundle format 16 and persisted meanings are unchanged.

Validation: **2,561 tests passed, five existing Windows skips**, with pinned native ROH,
Beagle and bref3 tools enabled. All four strict Windows/Linux × Python 3.11/3.13 type
targets, lint/format, fixture reproduction and full dbSNP card lint pass (51 cards,
268 renders, 35 marker references). No personal export was opened; new tests need no
reference downloads. See [the quality guide](imputation_quality.md#rare-call-frequency-gate-m87).

**M8.7's original M9.1 handoff (now implemented):** parse PGS Catalog scoring files and bind each score to its authoritative
licence in `pgs_all_metadata_scores.csv`'s `License/Terms of Use` column. The scoring
header is not the licence authority (AGENTS.md §4.8); do not assume catalogue-wide
permission. M9 then owns PLINK scoring, pre/post-imputation per-score coverage,
ancestry-matched distributions and portability calibration. Preserve the existing
native effect-allele dosage/quality interface: no DR2 dose scaling, no per-ALT quality
averaging and no invented multiallelic REF quality. The pending AADR-population to
study-ancestry mapping and `declined` portability treatment belong to M9.5.

## Implemented M8.6 and next scope

Format 16 adds durable full dosage files, byte-identical panel/map catalogs and
`imputation.provenance.run.json` schema 1. Used source releases, catalog/target/tool/
runtime hashes and each region's actual phase/imputation parameters come from the
completed stage. The general installed-reference/tool inventory does not substitute
for them. Independent copies and atomic staging preserve the source and reject partial
publication. Normal enabled analysis saves require their complete stage; disabled,
no-eligible-job and low-level not-recorded states remain distinct.

Readers validate saved bytes without caches or current manifests: counts, typed
retention, region/ploidy/native dosage contracts, source/quality, phase handoff,
catalog/artifact identities and card/full-dosage agreement. Full multiallelic records
and native haploid quality remain intact. Formats 1–15 retain original meanings.
`RunBundle.iter_dosages()` and `runs imputation --dosages` share the native record
contract. `runs imputation --json`, `runs show` and the dashboard expose saved provenance.
Copy/validation progress is genotype-free. See [the provenance guide](imputation_provenance.md).

Synthetic verification covers cache removal, installed-inventory differences,
corruption after rehash, failed copies, zero-job execution, opt-out, historic shapes,
privacy ignores and native/multiallelic contracts. Native CLI acceptance saves all
800 records over four jobs, verifies 396 direct/four phase-filled/400 untyped sources,
per-ALT/native haploid scope and completed reuse. No personal export was opened.

Validation: **2,524 tests passed, five existing Windows skips**, with native tools
enabled. Fifty-three new synthetic cases cover the full snapshot contract. All four
strict Windows/Linux × Python 3.11/3.13 type checks, lint/format, fixture reproduction
and full dbSNP card lint pass (51 cards, 268 renders, 35 marker references).

The subsequent [M8.6 diff review](review_m86_session.md) fixes per-card/per-marker
full-record binding at shared loci, strict native storage vector types and categorical
publication errors for malformed stage regions. Five regressions reproduced the defects
before the fixes. Format 16 and provenance schema 1 are unchanged.
The review's complete native suite passed **2,529 tests, five existing Windows skips**;
all four strict type combinations, lint/format, fixture reproduction and full card lint
also pass. There were no known blockers before M8.7 acceptance.

**M8.7 acceptance (completed):** dedicated regressions prove the frequency gate applies to
imputed observations, regardless of high DR2, strong literature or enabled mode.
Cover untyped and phase-filled sources, native haploid/diploid observations, missing
frequency companions and multi-marker inheritance. Show rare findings as likely artifacts;
never filter them. Keep the 16%/BRCA 4.2% chip benchmarks scoped to their studies and
explicitly uncalibrated for imputation, never an imputed-call posterior probability.
Current ClinVar/QC/coverage/structure still use original array input. M9 owns PGS sums,
coverage and ancestry portability; preserve the native effect-allele dose/quality contract.

### M8.7 implementation handoff

Completed 2026-10-08; the matrix below records the accepted scope. The current handoff
is M9.3 above.

Start in `engine/confidence.py` (`calculate_confidence`), `engine/evidence.py`
(`_confidence_frequency` / `assemble_card`) and `run/pipeline.py` (`observations`).
The current gate already caps a known observed-allele frequency **strictly below
0.00001 (0.001%)** at `likely-artifact`, independently of source and DR2. Extend
the existing quality tests and add integration regressions; change the shared engine
only where a reproduced failure warrants it.

| Boundary | Required evidence |
|---|---|
| Frequency below, exactly at and above 0.00001 | Below remains `likely-artifact` with strong replicated literature and high DR2; equality is outside this rare-call band. Other confidence ceilings still apply. |
| Imputed-untyped and phase-filled no-call; ploidy 1 and 2 | All four combinations retain the rarity ceiling. Phase-filled quality stays unknown, with zero quality contribution; no fabricated DR2. |
| Observed alleles with missing frequency companions | A known rare allele retains the rarity gate even if its companion is missing. Common-only incomplete coverage remains unknown and cannot establish strong confidence. An unobserved rare allele must not penalize the call. |
| Multi-marker findings | A rare imputed marker caps the whole finding through weakest-marker inheritance. No implicit phase or quality averaging. |
| Save/reopen and both front ends | Tier, selected allele frequency, source, native dosage/quality, empirical benchmark scope and caveats agree in CLI JSON and dashboard face/detail. Findings remain present. |
| Original-array control and opt-out | Direct observations stay original. Explicit `--no-impute` does not discover imputation prerequisites or synthesize an imputed observation. |

Use generated inputs and synthetic frequency lookups, including fully saved format-16
snapshots where relevant. Do not require reference downloads in CI. The 16% rare-call
and BRCA1/2 4.2% numbers remain study-specific chip benchmarks; an imputed observation
must not present either as its confirmation probability. BRCA-specific calibration
currently belongs to original-array ClinVar findings, so this milestone does not create
an imputed ClinVar calling path. No bundle-format bump is needed for regressions alone;
any changed persisted meaning needs its own compatibility decision and corruption tests.
These checks pass and M8.7 is recorded complete in the roadmap and this handoff.

## Implemented M8.5 and next scope

Quality-aware interpretation cards retain original direct probes and can use exact
biallelic SNV imputation for absent/no-call loci. Native DS/per-ALT DR2, source, biological
ploidy, method and quality scope remain attached to each marker. Low DR2 uses existing
confidence ceilings without filtering; phase-filled no-calls stay unknown quality with
a zero quality contribution and limited ceiling. Multi-marker confidence inherits its
weakest marker, without assuming phase. ClinVar/QC/coverage/structure retain original
array input. The allele-dose interface for M9 scoring preserves each ALT's quality;
multiallelic REF quality remains unknown without covariance, never averaged.

Format 15 / execution schema 2 saves the quality-aware observation basis and scalar/
marker evidence. Saved validation binds native quality/source/ploidy and confidence
ceilings; CLI/dashboard use the same snapshots. Formats 1–14 retain original meanings.
See [the quality guide](imputation_quality.md).

Validation adds 54 synthetic cases, including native Beagle quality propagation,
saved unknown quality, direct-probe preservation, per-ALT contracts, native haploid
scope, weakest-marker inheritance, reference-oriented palindromic sites, corruption
and CLI/dashboard parity. Full native tests and all four strict type combinations,
lint/format, fixture reproduction and full dbSNP card lint cover the changes. The
additional format-13 downgrade guard is checked separately from the full local run.
No personal export was opened.

**M8.5 handoff (implemented in M8.6):** durably copy full dosage records into the private bundle with exact
used-panel/map/tool/runtime versions, hashes and parameters from the stage contract,
including per-region/ploidy options. Current execution summaries and used-card evidence
are not full provenance. Validate publication/reuse and preserve historical formats;
reopening a run must not depend on its stage cache or a newer reference lock. M9 score
consumers must receive dosage and allele quality together. M8.7 owns dedicated
imputed rare-call gate regressions. Keep all generated data outside Git.

## Implemented M8.4 and next scope

`analyse` / `genetics run` now execute the M8.3 stage by default after ancestry and
before card assembly. `--no-impute` is explicit, defaults false, skips stage/reference/
tool discovery, and records disabled mode on the run and every card. Prerequisite and
execution failures report an imputation error without a saved bundle or automatic
fallback. Existing development fixtures now choose the escape hatch explicitly.

Format 14 adds private `imputation.run.json` schema 1 and per-card mode. It distinguishes
enabled/computed, enabled/no-eligible-jobs, explicit disabled and not-recorded execution.
Source/region/job counts, ploidy and status are validated; reader/writer require card/run
mode and observation-basis consistency. Formats 1–13 keep null mode, never an inferred
opt-out. Low-level writers without a stage context record unknown mode. CLI JSON/human
output, dashboard banner, card face/detail read the same saved snapshot without caches.

**2,417 tests passed, five existing Windows skips**, native tools enabled; 48 new cases
cover default ordering, explicit opt-out, missing prerequisites, failures, saved damage,
historical formats, privacy, CLI/dashboard parity and a native default CLI run producing
800 records and reusing completed jobs. Native acceptance exposed Windows error 267
at a 265-character working directory; the wrapper selects a shorter ancestor while
keeping absolute job paths/contracts unchanged. Synthetic preparation is shared with
M8.3 acceptance. Strict four-way types, lint/format, fixtures and full card lint pass.
No personal export was opened. See [the mode guide](imputation_mode.md).

**M8.4 handoff (implemented in M8.5):** consume the separate `Analysis.imputation_result` through quality-aware
card/score observations. Current findings, ClinVar, coverage and structure still use the
original array table; the UI states that basis. Do not replace original direct calls,
price phase-filled no-calls as perfectly typed, average per-ALT DR2 without an allele
contract, convert native haploid quality into diploid quality, or filter low-quality
findings. `ObservationEvidence` currently requires numeric imputed quality, so its
unknown-quality contract must be resolved before phase-filled calls enter cards.
Context schema 1 currently records `card_input=original_array`; extend that contract
when findings begin using imputed observations. M8.6 owns durable full dosages and
exact used-panel/tool/parameter provenance; current mode snapshots promise execution
outcome only. M8.7 owns explicit imputed rare-variant gate regressions.

## Implemented M8.3 and next scope

`genetics.imputation.impute` is the shared phasing-then-imputation stage, exposed by
`genetics impute`. It streams allele definitions from the complete bref3, checks its
decoded semantic summary, harmonizes normalized calls using existing strand/indel
rules, and gives both Beagle invocations the full panel. Default catalogs bind to the
current manifest/lock; there is no rate-map or direct-overlap fallback.

Autosomal jobs and five inclusive X intervals partition biological scope. PAR1/PAR2
use their own maps; non-PAR follows QC sex. Unknown ploidy, contradictory calls,
duplicate positions and regions without two observed anchors remain explicit.
Original input stays separate from direct, phase-filled no-call and imputed-untyped
observations. Each ALT retains its dosage and finite DR2 where estimated. Phase-filled
no-calls have unknown quality even if the second invocation labels them typed.
Male non-PAR targets use native haploid GT/dosage/DR2, with a 0-1 dose scale and a
recorded haploid model; wrong-copy-count output is refused. The full reference keeps
its required diploid encoding. Independent dosage rounding is allowed at the pinned
writer's hundredth precision. Low DR2 is never a filter.

Schema-1 private outputs/checkpoints stay under the outside-repo cache by default.
Kernel locks and stable region prefixes permit completed-job reuse and incomplete-job
restart. Exact typed-marker retention, sample/region identity, allele orientation,
dosage/quality cardinality/ranges and genotype preservation across both stages are
checked before atomic dosage publication. Reuse regenerates observations and compares
them with saved files/metadata, catching even a changed dosage with an updated hash.

**2,369 tests passed, five existing Windows skips**, with native ROH, Beagle and bref3
tools enabled. Seventy-seven M8.3 cases include native fixed-seed male/female targets:
each produces 800 records over an autosomal and three X region jobs, with 396 direct
calls, four phase-filled no-calls and 400 newly imputed markers. Full references stay
unchanged and completed reuse passes. The two Windows launcher-cancellation checks
require working OS process-control permissions; both pass outside the restricted
sandbox. Strict four-way types, lint/format, fixture reproduction and full card lint
pass. All installed 23 panels / 84,739,838 records and 25 maps / 3,395,051 rows pass
read-only default-contract validation. No personal export was opened.

**M8.3 handoff (implemented in M8.4):** integrate the stage into default-on `analyse`/`genetics run`, add the
explicit recorded `--no-impute` escape hatch, and ensure every affected card/run states
the mode. The M8.3 command/stage is already available; do not build another imputation
engine. Existing analysis and bundle format 13 remain unchanged until that integration.
M8.5 owns quality propagation, M8.6 bundle provenance and M8.7 imputed rare-call gate
regressions. M8.4 must preserve the unknown quality of phase-filled no-calls, keep
original direct calls for ClinVar/structure and retain the native target ploidy and
quality-model scope. See [the pipeline guide](imputation_pipeline.md).

## Implemented M8.2 and next scope

The [session diff review](review_m8_session.md) covers M7.6 through M8.2 and fixes
Beagle output sample/region binding, cleanup fallback, reference kind/transform/input-set
validation, catalog recovery without the original Java installation, reordered build
metadata and runtime drift before publication. Prepared references remain intact.
The reviewed suite passes **2,292 tests, five existing Windows skips**, with native
tools enabled; strict four-way types, lint/format, fixtures and full card lint pass.
Fifteen added regressions cover the fixes. Full panel/map verification passes.

`refs/imputation.py` and executable reference post-processing prepare the full 1000
Genomes autosomes and X as chromosome bref3 panels. No array intersection, LD/MAF
filter or sample removal is permitted. Converter and decoder are independently pinned
to `27Feb25.75f`; the converter requires Java 11+, even though Beagle itself supports
Java 8. Local acceptance uses a checksum-verified portable Temurin Java 17 runtime,
configured through `JAVA_HOME` for the work commands; system Java remains unchanged.

Each completed chromosome has full source-to-decoder semantic comparison, sample-order
identity, input/tool/runtime hashes and an atomic checkpoint. Incomplete attempts restart;
completed chromosomes are reused after verification. Source/tool drift, corruption,
stale contracts and malformed catalogs fail explicitly. Kernel locks prevent concurrent
writers. `refs verify` remains read-only and validates all catalog companions.

The separate pinned HapMap archive supplies all **25 GRCh37 maps / 3,395,051 rows**.
Maps are preserved byte-for-byte and checked for labels, ordering, cM validity and
physical bounds. Catalog counts are checked against actual map files. Source version,
archive SHA and companion hashes bind map reuse; no constant-rate map is invented.
See [the reference guide](imputation_reference.md).

Full-release acceptance completed **23 chromosomes / 84,739,838 records / 2,504 samples
each**, preserving sample order and producing **8,312,115,275 bref3 bytes**. Every
chromosome passed decoded semantic comparison and input/tool-drift checks. Final
source/catalog/companion verification passed. These are public-reference properties;
no consumer export was used. All reference payloads and workspaces remain ignored.

X haploid reference calls are explicitly doubled for storage and counted in metadata.
This does not establish diploid consumer ploidy. Y is fetched but excluded from Beagle
preparation because of missing haploid calls and no supplied genetic map; MT is absent.
Those limitations are explicit in the panel catalog. Existing direct-call and haplogroup
engines retain their scope.

**M8.2 handoff (implemented in M8.3).** Start with consumer-target VCF harmonization against the prepared
GRCh37 reference alleles, using the existing strand/indel/QC rules. Partition X PAR and
non-PAR jobs using sample ploidy, recorded bounds and matching maps. Call the M8.1
wrapper through a shared phasing/imputation stage, write private dosages and per-variant
DR2, and test the full stage offline with generated targets. Reuse completed jobs;
never splice interrupted Beagle windows. M8.5 owns quality propagation into scores;
M8.6 owns saved run-bundle provenance and M8.7 owns imputed rare-call gate regressions.
M8.2 changes neither bundle format 13 nor `genetics run` behavior.

M8.3 acceptance must check exact target sample identity and requested regions (now
enforced by the wrapper), preservation of every eligible typed marker, explicit exclusions,
dosage scale/allele orientation and finite per-variant DR2. Keep original direct calls
separate from imputed calls and preserve the source/quality needed by M8.5–M8.7. Verify
PAR/non-PAR output against biological ploidy before interpreting doubled X storage.
Exercise missing references/tools/maps, malformed output, cancellation, recovery and
shared CLI/dashboard behavior. Do not infer correct dosage or marker retention merely
from a valid phased VCF. Application `--no-impute` remains the separately recorded M8.4
escape hatch; Beagle phase-only mode can still fill sporadic missing target calls.

Validation: **2,277 passed, five existing Windows skips**, with native ROH, Beagle,
converter and decoder enabled. Fifty-one new synthetic cases cover exact full-record
retention, multiallelic/indel/symbolic alleles, X encoding, malformed inputs/build metadata,
map corruption and counter forgery, cancellation, lock release, checkpoint recovery,
stale tools, Java readiness and native Beagle consumption. Default consumer contracts
bind the current manifest and lock without reading raw VCFs. Strict Windows/Linux ×
Python 3.11/3.13 typing, ruff/format, fixture reproduction and full card lint pass
(51 cards, 268 renders, 35/35 marker references). No personal export was used.

## Implemented M8.1 and next scope

`external/beagle.py` supplies exact-jar discovery, Java 8+ checks, typed memory/seed/
thread/mode options, streamed private diagnostics and safe progress. Doctor uses the
same readiness rules. Inputs, jar and runtime identity are recorded in a schema-1
private checkpoint; a completed output directory is published atomically after VCF
integrity and input-drift checks. Reuse verifies all recorded outputs and rejects changed
contracts. Kernel locks survive process crashes without stale lock ownership. Timeout
and cancellation terminate the child before releasing the lock. Interrupted jobs restart
from their inputs; M8.3 must reuse completed chromosome jobs rather than splice Beagle
windows. Workspaces and locks are ignored even inside the knowledge-pack allowlist.

The suite passes **2,226 tests, five existing Windows skips**, with pinned native ROH
and Beagle enabled. Strict Windows/Linux × Python 3.11/3.13 typing, ruff/format,
fixture reproduction and full card lint pass. Thirty-eight new synthetic cases cover
discovery, private progress, failures, cancellation, crash-released locks, changed inputs,
corrupt checkpoints, restart and native execution. Native Beagle 5.5 / `27Feb25.75f`
on Java `1.8.0_491` phases and imputes one generated target against twenty generated
reference samples, retains DR2/dosages, checks phase-only mode and reuses completion.
CI installs Java 17 and the same pinned jar for Windows/Linux acceptance. No personal
export or real reference individual was used. See [the wrapper guide](beagle.md).

M8.2 implements the full-panel preparation described above. The original M8.1 checkpoint
changes no existing bundle format or `genetics run` imputation behavior.

## Implemented M7.6 and next scope

`health/coverage.py` and the declarative `clinvar_array_coverage` card measure unique
normalized positions and distinct REF/ALT variants from the full pinned ClinVar index.
Both reference-position and chip-position fractions save explicit denominators.
Calls obtained stay separate from resolved alleles; duplicate/conflicting probes,
no-calls, excluded indels, strand ambiguity and unresolved sex-chromosome ploidy are
counted explicitly. Missing references, empty primary-reference scope and zero overlap
remain distinct. Coverage does not estimate clinical sensitivity or confirmed findings.

Format **13** / lookup schema **5** saves these counts, definitions and source identity
in the existing private payloads. Readers check arithmetic, overlapping observations
and card/lookup equality without consulting newer caches. Formats **1–12** retain
their original snapshots. No new output type or privacy exception was introduced.
See [the coverage guide](clinvar_coverage.md).

The suite passes **2,188 tests, five existing Windows skips**, with pinned native ROH
enabled. Strict mypy on Windows/Linux and Python 3.11/3.13, ruff/formatting, fixture
reproduction and full dbSNP lint pass: **51 cards, 268 renders, 35/35 marker references**.
Thirty new regressions cover source/count states, exclusions, saved consistency,
historical formats, rare-call preservation and CLI/dashboard equality.

Scoped M7.6 offline acceptance passed on the committed synthetic fixture against the
complete ClinVar, gnomAD and 84-gene ACMG caches, through format-13 save/read, CLI JSON
and dashboard/detail rendering, with networking blocked (**249.4 seconds**). It excludes
ancestry and ROH/archaic reference preparation; those modules have separate acceptance
and the native ROH tests are enabled in the suite. No personal export was used.
The pinned ClinVar release contains **3,933,850 primary-chromosome positions**,
**4,460,684 distinct REF/ALT variants**, and **4,155,065 matchable biallelic SNV variants**;
eight alternate/unplaced-contig records are excluded from this position denominator.
These are full-reference properties, not measurements of a person's chip coverage.

**M8.1-M8.3 are implemented.** Next integrate default-on imputation and
save panel/tool/parameter provenance. Imputation must be
default-on; `--no-impute` is an explicit, recorded escape hatch. Rare-call reliability
must remain frequency-gated after imputation. M8.5–M8.7 remain upcoming.

## Prior checkpoint
M7.5 checkpoint: `aa75287`, with [all five CI jobs passed](https://github.com/sovemere/genetics-analysis/actions/runs/37434344709).
The [M7.5 diff-driven review](review_m75_session.md) records outcome-calibration,
saved-record validation, marker-detail and lint-denominator fixes. The earlier
[M7.1–M7.4 review](review_m7_session.md) remains historical context.

## Current local acceptance

The required `gnomad_exomes_r2_1_1_grch37` download is complete. The payload is
63,145,056,967 bytes, publisher MD5 `f034173bf6e57fbb5e8ce680e95134f2`.
Source SHA256: `b5218277d30c0747cfef38bbc8ee4f735ba8b31695fd343cf9f31ff77cfaf9f3`.
The complete `build_gnomad_frequency_index` transform parsed **17,209,972 public
records**. The index is 23,837,532,160 bytes, schema generation 2, SHA256
`1c8a5a4e4cd31de06a9fb7a05f0db255ceff4d1380af6069d3aba17cfeb8caf7`.
`refs verify` rechecked the source and index successfully, with no pending steps or
temporary build files. At M7.2 acceptance, a synthetic-only run against the complete ClinVar and gnomAD
caches passed with networking blocked: five synthetic lookup entries received
frequencies, every card remained present, format-8 reloading matched the saved
snapshot, and CLI JSON/dashboard parity passed. No personal export has been used.

```text
genetics refs fetch --only gnomad_exomes_r2_1_1_grch37
genetics refs verify --only gnomad_exomes_r2_1_1_grch37 --json
```

Keep the required exomes source separate from the optional 495 GB genomes source.
The optional genomes payload is not needed for this accepted milestone.

## Implemented M7.2

`gnomad_frequencies.sqlite` contains the entire public sites reference, with REF/ALT,
FILTER, global/population AF/AC/AN/homozygote counts and publisher popmax annotations.
Header assembly/cardinality, counts and rounded AF are validated. Committed SQLite
checkpoints bind source identity and a cumulative record checksum; restart replays
gzip and skips already committed parsing. Final output/provenance are checksum-bound.
`refs status` reports a partial index as resumable processing.

Queries use memory-only sample loci against a read-only index. A sample-selected
reference subset never lands in the repository. Missing, filtered, incompatible,
duplicate and unresolved multiallelic/indel records remain unknown, never zero.
Usable alternates are screened at their highest available population frequency;
all nine reported East Asian/European subgroups are included alongside the major groups.
The population is disclosed and is not inferred ancestry. Split source loci leave
REF frequency unknown rather than assigning other alternates to REF.

Interpretation cards use the same source through the existing confidence engine.
A measured rare allele cannot escape `likely-artifact` because its companion's
frequency is missing or its imputation quality is high. ClinVar receives a separate
measurement-reliability screen, without fabricated penetrance or claim evidence.
Below 0.001%, the generic 16% heterozygous-chip confirmation benchmark is attached
and explicitly distinguished from an individual's posterior probability.

M7.3 puts the published confirmed/unconfirmed percentages on the face and in CLI
summaries. Exact `GENEINFO` symbol/NCBI-ID pairs plus germline pathogenic/likely-pathogenic
`CLNSIG` select the BRCA benchmark; mixed, uncertain, conflicting, somatic and
included-haplotype annotations do not. Missing frequency or unresolved observations
still receive no numerical PPV. Imputation-quality failures without a benchmark say so.

New bundles use **format 14**, with ClinVar lookup schema **5** in the existing private
`clinvar.run.json`. CLI JSON and the dashboard read the same saved records. Formats
1–12 retain their original results and notices, including schema-2 BRCA entries with
the original generic benchmark. See [the frequency guide](health_frequencies.md).

M7.1's complete pinned ClinVar index contains **4,461,445 records** from 2026-08-04.
All INFO classifications/conflicts/review status and ambiguity states remain intact.

## Implemented M7.4

The complete 84-gene ClinGen ACMG SF v3.3 roster and reporting guidance is fetched,
hash-pinned and verified under CC0. Its 54,071-byte payload SHA256 is
`8089748ab8645336eedab56e4f548f7c902e2f7d163fa3a559b49c9fbd93151d`.
All overlaps remain visible in a dedicated dashboard view and `runs secondary` CLI
view, with the existing reliability and PPV calculations unchanged. P/LP reference
annotations remain distinct from clinical reportability, which is not adjudicated.
Each overlap states the clinical-sequencing limitation; missing prerequisites are
explicit and an empty result cannot be interpreted as a negative screen.

Schema 4 saves the complete source roster, guidance, provenance and overlap metadata.
Validation uses the saved roster without consulting today's source. Older runs retain
their original results and explicitly lack this stage. See [the ACMG guide](secondary_findings.md).
Offline acceptance passed against the complete ClinVar/gnomAD caches using five
fabricated calls spanning BRCA1, TTN, ABCD1, CYP27A1 and PLN, with the full 84-gene
roster. Networking was disabled; snapshot validation and the shared view passed.

<a id="next-m75"></a>

## M7.5 implementation and accepted scope

M7.5 adds three declarative cards under `knowledge/health/`: HFE C282Y, Factor V Leiden
and APOE. These authored associations remain distinct from ClinVar/ACMG reference lookups.
The following requirements are implemented; [the guide](common_health.md) records source
scope and the numerical rates/baselines this curated pack does and does not transcribe.

1. Add declarative `knowledge/health/` entries for tractable single-marker claims first,
   using dbSNP-verified GRCh37 keys and primary sources. Each card needs effect units,
   population, sample size, replication, DOI/accession, and genotype-specific wording.
2. State published absolute outcome rates, baseline, time horizon, and applicable
   age/sex/population strata on the face. Do not turn a ClinVar classification or a
   SNP-chip PPV into disease risk, or convert an odds ratio into absolute risk without
   a defensible baseline. Explicitly state when a source supplies no applicable rate.
3. APOE allele interpretation uses both rs429358 and rs7412, not a one-marker shortcut.
   Schema 2 extends declarative matching with exhaustive haplotypes/diplotypes, retaining
   both observations before reporting a uniquely compatible SNP pattern.
   Preserve missing calls, discordance, and phase ambiguity as visible outcomes. The
   rare fourth haplotype cannot be ruled out merely because the common three are more
   frequent ([Seripa et al., 2011](https://doi.org/10.1089/rej.2011.1169)). Imputation/
   phasing remains upcoming M8; do not assume it has run.
   Format 11 saves both marker observations, locus-specific frequency/calibration and
   phase candidates. Formats 1–10 and ClinVar schemas 1–4 retain their original meanings.

The review adds **knowledge schema 3**, supporting complete outcome-specific evidence
overrides or explicit `evidence: null`. Evidence is selected before confidence is computed
and saved. APOE common outcomes use their corresponding Rasmussen cohort effects;
F5 homozygotes use the homozygote estimate. Comparator, rare-pattern and unestimated
HFE/F5 outcomes carry no borrowed phenotype estimate and receive limited confidence,
with rarity/quality gates still active. Unresolved APOE phase receives no phenotype
estimate. Each marker's call source, quality, ancestry-match input, reliability inputs
and available benchmark are visible in detail. Full lint counts marker references,
giving **35/35**, rather than dividing them by 34 interpretation cards.

**Format 12 / multi-marker schema 2** records these meanings. Saved validation binds
marker confidence to recorded observation metadata, the rarest usable called allele,
and the saved phenotype effect, preserving frequency/quality limits. Formats 1–11 remain
immutable snapshots; a format-11 run keeps its original card-wide effect even when the
current pack has a different outcome estimate. Re-run to obtain the correction.

Synthetic checks must cover all supported allele combinations, missing/discordant
observations, phase ambiguity, unknown frequencies, rarity gating, and save/read/CLI/
dashboard parity. Existing `{frequency}`/`{ppv}` placeholders and the confidence engine
are available. Run full card lint against the cached dbSNP index and keep all personal
outputs outside the checkout.

## Accepted M7.6 scope (retained for review)

Add a quantitative coverage-honesty card: how many ClinVar positions the array actually
covers and what that does and does not establish. Compute the denominator and overlap
from the sample's chip positions and fetched reference; the roadmap's ~76k is an earlier
chip measurement, not a universal constant. Distinguish positions from allele-specific
matchable variants, markers present from calls obtained, and reference annotations from
clinically confirmed findings. Missing references must stay explicit; an empty overlap
cannot imply a negative clinical screen. Preserve the same saved CLI/dashboard contract.

Use the complete pinned GRCh37 ClinVar index through the existing shared pipeline,
and save a source-bound counting record rather than counting again when a run is opened.
Define the counters and denominators in that record:

- Deduplicate reference positions by normalized chromosome/GRCh37 coordinate; multiple
  records or alternate alleles at one site count once as a position. Define separate
  variant/allele counters and disclose any reference filtering.
- Deduplicate chip positions across probe aliases; disclose duplicate/conflicting probes.
  A listed no-call position is present on the export but is not a successful call.
- Report both reference-position coverage (overlap / reference positions) and the share
  of chip positions annotated by ClinVar (overlap / chip positions). Label both denominators.
- Separate present-position overlap, called-position overlap and allele-resolved matches.
  Keep no-calls, indels, unresolved strand/ploidy and conflicting observations explicit;
  positional overlap alone never establishes a particular allele.
- Preserve classifications and the assay/rare-call limits. Coverage is neither sensitivity
  nor a count of confirmed pathogenic findings. Scope the ACMG roster separately.
- Distinguish missing source, empty reference, zero overlap and incomplete/bad input;
  avoid division by zero or a fabricated negative screen.

Synthetic regressions should exercise repeated reference alleles, duplicate chip probes,
no-calls, excluded indels, missing/empty references, zero overlap, digest-consistent
malformed counts, and save/read/CLI/dashboard equality. The saved reader must validate
counter relationships and provenance using the snapshot, without consulting newer caches.
M7.6 is now implemented. Its overlap is computed per export; no new personal-chip
measurement is claimed. The original ~76k figure remains historical context only.

M7.6 owns quantitative coverage honesty. All low-confidence findings
remain visible. Study-to-sample ancestry calibration remains M9.5; source-license
audit remains M15.4. M6's missing chip/population calibration stays attached.

## Download contract

Publisher-checksummed sources resume and verify their final digest. Digestless frozen
sources require an explicit immutable flag, fixed size and matching URL/size/prefix-hash
sidecar. Changed or damaged provenance restarts; rolling files restart. The 24 frozen
1000 Genomes chromosome files declare immutability. None of this permits weakening
privacy, pinning or the pre-commit checks.

## Validation

The M7.5 implementation suite passed **2,135 tests, five existing Windows skips**, with pinned native
ROH enabled. Ruff/formatting, strict mypy on Windows/Linux and Python 3.11/3.13,
fixture reproduction and full card lint pass (50 cards, 266 renders, 35 dbSNP keys).
Synthetic-only acceptance against the complete ClinVar/gnomAD caches passed with networking
blocked, through format-11 save/read and CLI/dashboard parity. No personal export was used.
M7.5 adds 59 cases covering all APOE observation combinations, rare-haplotype/phase
preservation, missing/discordant/non-diploid calls, HFE/F5 forward-strand and duplicate
matching, unknown/rare frequencies, per-marker quality, malformed saved evidence,
format-10 compatibility and both interfaces.
The follow-up review passes **2,158 tests, five existing Windows skips**, including pinned
native ROH. Its 23 new regressions cover outcome-specific and absent effects, rarity/quality
gates, constituent identity, lint denominators, schema-3 boundaries, saved consistency,
format-11 immutability and marker-detail metadata/PPV. See the review record for checks.
M7.3 adds 31 synthetic cases for exact BRCA/classification scope, numerical face/detail
and CLI presentation, unavailable PPV, placeholder contexts and historical schema-2
save/read/CLI/dashboard compatibility. Tests also cover rare thresholds/counts/populations,
missing/filtered/split/duplicate
records, direct/imputed gating, malformed headers, checkpoint recovery/corruption,
saved integrity, format-7 compatibility, CLI/dashboard parity and citation privacy.
M7.4 adds 42 synthetic cases for exact gene membership, annotation/reportability
separation, source completeness/checksum refusal, unsuppressed ambiguity and reliability
states, missing-source/empty-screen honesty, saved metadata integrity, format-9
compatibility and CLI/dashboard parity with 101-locus pagination.
The review adds twelve malformed-cache/snapshot regressions, including schema-2/3/4
bundle, CLI and dashboard error handling, and verifies the ACMG title/count scopes.
The cache-reuse test now keeps its gzip source unchanged: regenerating it changed the
header timestamp/checksum and caused a legitimate rebuild, producing a flaky CI failure.

Before committing, inspect `git status --porcelain`, stage only code/docs/reference
metadata, run `genetics check-staged`, and keep the privacy hook enabled. Public
references, indexes, personal outputs and temporary synthetic bundles stay uncommitted.
