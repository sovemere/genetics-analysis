# Roadmap history: M0 to M14

The checklists, design notes and decisions of milestones M0 to M14, moved here
verbatim from [phase1_roadmap.md](../phase1_roadmap.md) on 2026-11-23, when that file
was cut back to what is still open. The roadmap keeps the definition of done, the
design sections, M15 and the risk register; the dated record is the
[progress log](progress_log.md).

## Earlier status paragraphs

The roadmap's "Next up" section as each milestone left it, newest first.

M14.7 is the accessibility pass. A card face's link is now its title, named by the title,
described by the tier and stretched over the face, where it had been one link whose name was
the whole face. Arrow keys on the run selector and the grid's selects no longer leave the
page; Enter, Open and Apply act. Form controls have a 3:1 edge, every text pair is held to
4.5:1 in both themes, the search page has one search landmark, and counts, the theme toggle
and the ancestry scatter's points are named for a screen reader.
`genetics.testing.accessibility.audit` checks the markup of every page and every card's
page and dialog. No command, schema, view field or card changed.

M14.6 keeps the twelve impossibility cards with the findings they qualify, whatever the grid's
arrangement. Each section names its assay limits at its head ("Not determinable from this
array:", a link to each card) whatever the filter, and renders those cards as their own block
below its findings rather than in the sort, where a card with no tier went last among the
cards that did not match. Grouped by tier, the untiered panel has the same block.
`runs show --section` prints the list (`assay_limits`, agent schema 10), with the current
pack's limits a run saved before them lacks.

M14.5 adds the QC and provenance page, `/runs/{run_id}/qc`, which shows what `genetics runs
qc <run> --json` and `runs imputation <run> --json` print, whole: every QC field and warning
with the call rate by chromosome; the run's coverage, every polygenic score's on the
original array and after imputation and the saved ClinVar fractions, never combined; the
imputation execution, parameters and a row per region and per job; and the reference, tool
and knowledge-pack versions. Coverage is new on `runs qc` (`current_context.coverage`,
agent schema 9). The route scans the whole page for genotypes, as both commands do.

M14.4 adds the dashboard's search: a box at the top of every open run's nav opens
`/runs/{run_id}/search`, which lists what `genetics runs search <run> <query> --json`
prints, the same cards in the same order from the same function, each as the face the grid
shows with the words it matched. Partial matches are listed below full ones; the grid's
filters do not narrow it. A query that reads as a genotype is refused in the command's
words and never shown again. No command, schema or bundle format changed.

M14.3 adds the reading guide: `/guide` and `genetics cards guide`, which prints what the
page shows. It gives the six badges and what earns each, how a tier is decided (the
weights, the bands and every ceiling), why rarity lowers confidence with the published
benchmarks, what a polygenic score can say (coverage, portability, within-family
attenuation) and what the array cannot tell. Every threshold is read from the confidence
engine, and the ceilings are listed by asking the functions that apply them. Every page's
nav carries the legend, each badge linking to its row in the guide. Agent schema version 8.

M14.2 adds the ancestry page and `genetics runs ancestry`: a PCA scatter of the run against
the reference populations it was placed among, the nearest populations by full distance,
ancient affinity, and both haplogroups with their marker counts. Bundle format 29 records
the reference positions, so a saved run is drawn against its own reference; an older run
lists its fits and says why it has no scatter. Agent schema version 7.

M14.1 makes every empty section say why. The sentence comes from one function, which the
nav, the grid and `runs show --section` share: a run saved with a pack that held no card
here (with the current pack's count), cards that produced no interpretation (statuses
counted, the engine's not-run reasons quoted), or no run open. "Not built yet" is gone,
since every section has cards in the pack.

M13.7 adds `genetics cards check-query`, which an agent runs on every web search before
sending it. It refuses a genotype written out (an rsID beside two alleles, a diplotype,
the privacy scanner's shapes) and a result told in words (zygosity, a count of copies, the
first person, a run id, a tier), and never prints the query back. With `--card` it lists
each word the card's evidence does not print. The search commands now refuse the call
shapes too, and every request the fetcher makes passes the same check, which a test holds
by reading the source. Agent schema version 6. The two queries M13.6 left open are
refused.

M13.6 documents how an agent reviews a run, as
[Reviewing a run as an agent](agent_usage.md): eight steps from picking the run to
the answer, the keys a review reads, the rule for what may leave the machine, and what an
answer has to carry. The brief's curly-hair example is worked through with real output
from a run built from committed cards and an invented table, the card is checked against
its two cited papers, and the ten facts each name where they were read. A test runs every
command on the page and compares each output shown with what the command prints. No
command, schema, bundle-format or knowledge-schema change. The
[M13.6 diff review](review_m136_session.md) found the page claimed more for its
query check than the check does: a result told in the card's own words ("one copy")
passes it. The page now says so, and M13.7 inherits the case.

M13.5 adds the test that every analysis a dashboard page shows is in a command's JSON. It
checks three things, each read from the dashboard's own code: every route has commands
beside it, every engine function the dashboard calls is one the CLI's read side calls, and
every value a page of a saved run is handed is in what the commands print for that run. The
five commands that print a run's other saved records are now described by the agent schema,
which is version 5. No bundle-format or knowledge-schema change. See
[the parity section](agent_cli.md#parity-m135). The
[M13.5 diff review](review_m135_session.md) made the check's comparisons exact: a
figure changed to another figure in the same saved record had passed.

M13.4 makes `genetics runs card` say what decided a card's confidence tier.
`current_context.confidence` has one shape for every kind of card: the saved tier and score,
each input with its weight and what it cost the score, every ceiling that applies, which of
them set the tier, and a sentence saying so. A card with no tier says why it has none. The
block is built when the run is read and is checked against the saved tier first; a run
saved under other rules gets no explanation, not a wrong one. The agent schema became version 4.
No bundle-format or knowledge-schema change. See
[the confidence contract](agent_cli.md#confidence-m134). The
[M13.4 diff review](review_m134_session.md) fixed the check, which had summed rounded
figures and failed about one honest polygenic score in a thousand.

M13.3 adds card search, so an agent can find "curly hair" without knowing the card id.
`genetics cards search <query>` searches the knowledge pack, holds no genotype and is checked
for one before printing. `genetics runs search <run> <query>` searches one saved run's cards
and returns each one's saved face. Both rank with one function, which the dashboard's search
(M14.4) calls too. A card matching only some of the query's words is listed below the
cards matching all of them, each hit says which fields matched, and status and confidence
play no part in the order. A query that reads as a genotype is refused. The agent schema is
version 3. No bundle-format or knowledge-schema change. See
[the search contract](agent_cli.md#search-m133).

M13.2 describes the agent commands' JSON in one versioned JSON Schema document, which
`genetics schema` prints. Each document names its payload and version. See
[the agent schema](agent_schema.md).

M13.1 adds four read commands, so an agent can read one card, one section, a run's QC record
or a card's evidence without printing a whole bundle (about 1 GB for the real imputed run).
`genetics runs show <run> --section S` prints that section's cards and the frame the dashboard
draws around them: counts, the empty-section reason, pointers to cards other sections hold,
section notices and the commands for the section's other saved records. `genetics runs card
<run> <card-id>` prints one saved card in full. `genetics runs qc <run>` prints the QC report,
imputation record and provenance. `genetics cards evidence <card-id>` prints a card's
variants, published effect, citations with links and caveats from the knowledge pack alone,
with no genotype, so a web search can start from it (AGENTS.md §1.3). Saved records and
current context are kept apart in every payload. No schema or bundle-format change. See
[the read-command contract](agent_cli.md). The [M13.1 diff review](review_m131_session.md)
fixed `runs card` text calling computed, polygenic and guideline cards "Not scored", and
removed stale "what remains" text.

M12.2 is the MTHFR C677T calibration case: four cards on one marker, each scored on the evidence
for its own claim. The nutrition card says what the variant does. TT averages 2.10 micromol/L more
homocysteine than CC (53,643 people), 3.12 in Asia and 0.13 where food is fortified, and it lands
well-established. Three cards state the health claims made for it, with the studies that tested
them: venous thrombosis (MEGA, OR 0.94) and coronary heart disease (Clarke 2012's unpublished
datasets, OR 1.02, against 1.15 in published studies) in physical health, and depression
(Gilbody 2007's OR 1.36, not replicated in Border 2019) in mental health. Each lands at limited
because its replication conflicts. Section pointers link the four. ACMG's advice, pregnancy loss,
folic acid and "methylation" are stated on the nutrition card with their sources. A1298C is
mentioned, not carded. No schema or bundle-format change. See
[the calibration audit](mthfr.md).

M12.1 fills the nutrition section with nine cards. Seven are new: coffee intake at the
CYP1A1–CYP1A2 locus, the CYP1A2 −163C>A "slow metaboliser" marker (candidate-gene,
unreplicated, landing at moderate at best), ADH1B intake, FUT2 secretor status and norovirus,
FUT2 vitamin B12, GC vitamin D and FOLR3 folate (off-array, imputed only). The lactase and ALDH2
cards move from traits, unchanged apart from their section. HFE and celiac stay in their own
sections, and a new `SectionInfo.related` pointer links to them from the dashboard and
`runs show`. No schema or bundle-format change. Each card's forward-strand allele is bound to
its paper by two independent checks, and one CYP1A2 star-allele label names opposite bases in
two cited papers. See [the nutrition audit](nutrition.md). The
[M12.1 diff review](review_m121_session.md) removed four unsourced card sentences and sourced
two allele names to PharmGKB; saved format numbers are unchanged.

M11.7 adds seven public polygenic cards to the reproductive section: age at menarche, age at
menopause, age at first live birth, age at first sexual intercourse, menstrual cycle length and
serum testosterone in women and in men. Two catalogue labels name another model's endpoint, so
each card is bound to its file's own model name. The menopause evaluation's standard error implies
a 13.4-year phenotype spread where the field's deciles imply about 4.7, which is what leaving UK
Biobank's -1 and -3 answer codes in as ages would produce, so that card says its published R2 is
probably too low. Knowledge schema 9 and bundle format 28; the carrier statement is unchanged. See
the [model audit](reproductive_prs.md).

M11.6 adds one computed card stating that the reproductive section is not a carrier screen, and
counting what it leaves out: 16 typed markers over 9 conditions against ACMG Tier 3's 113 genes
(8 typed, 7 assay limits, 98 with no card, a gap in this report and not a limit of the array),
plus how many markers gave a result in this run. Knowledge schema 8 and bundle format 27 rebuild
it from the bundle's own carrier records. See
[section-level scope](carrier_status.md#section-level-scope-m116). The
[M11.6 diff review](review_m116_session.md) fixes a crash when CLI output is redirected on
Windows, counts imputed results apart from array reads and binds the audit's re-check to each
allele; saved format numbers are unchanged.

M11.5 adds knowledge schema 7's `carrier` declaration and 15 reproductive carrier cards over
eight conditions; HFE C282Y joins the panel from physical health, making nine. Every marker was measured
against dbSNP, the array's marker list, ClinVar and gnomAD; indels, untyped alleles,
conflicting classifications and unsourced candidates are recorded as excluded rather than
dropped. The carrier state is derived from the call and re-derived from the saved match in
bundle format 24; an unmatched card is "not determined", never non-carrier, and A/T or C/G
homozygotes stay strand-ambiguous while heterozygous carriers are still reported.
`genetics cards carriers --json` is the panel. See
[carrier status](carrier_status.md). The
[M11.5 diff review](review_m115_session.md) tightens five card statements against
their sources, refuses saved carrier records on a non-autosome and records that most panel
markers are multiallelic in dbSNP; saved formats are unchanged.

M11.4 turns the frozen M11.3 classifier calls into eight cited HLA-linked cards (knowledge
schema 6, `kind: hla`): celiac DQ2.5/DQ8, type 1 diabetes DR3/DR4-DQB1\*03:02, ankylosing
spondylitis B27 and narcolepsy DQB1\*06:02 in immunogenetics; B\*57:01, B\*15:02, A\*31:01
and B\*58:01 in pharmacogenomics. A drug card's carrier state selects the frozen CPIC
`positive`/`negative` lookup, resolves other HLA genes in a CPIC key from the same record
and leaves CYP2C9 explicit and unassessed; recommendation text is never authored. A stage
that did not run, a named locus without a prediction, or an allele the classifier cannot
emit makes a card not determinable, never negative. Confidence takes the weakest named
locus posterior, M9.13's study comparison and M11.3's call ceiling, and stays capped at
moderate without an HLA frequency source. Phase-dependent claims cannot be authored. Bundle
format 23 rebuilds every HLA card from its frozen definition and the bundle's own HLA, PGx
and ancestry records; formats 1–22 are read unchanged. See
[the card contract](hla_cards.md). The
[M11.4 diff review](review_m114_session.md) stops one-field groups counting null
alleles, lists the HLA drug cards on the PGx overview and in `genetics pgx calls`, and
tightens three card sentences against their sources; saved formats are unchanged.

### Completed milestones (historical checkpoints)

M0-M4 are done and the M4 slice checkpoint passed. **M5 is complete.** M5.1-M5.9 are done
and every one of them is verified against real data rather than fixtures: the panel is
fetched, the LD-pruned subset is built (290,285 markers over 2,504 samples), the M5.2 -> M5.3 -> M5.4 chain runs end to end, both haplogroup callers
are validated against 1000 Genomes chrY, M5.5 places a sample among the modern populations
and refuses when none fits, and M5.6 places it against 442 ancient groups from the AADR.

**[M5.8](#m5--ancestry) was accepted on the real export on 2026-09-24.** `genetics run` now
infers ancestry before any card is assembled and saves it in the bundle (format 3), with "not
inferred" and "inferred, and no population fits" kept apart by explicit statuses rather than by
a `None`. On the real export: population placed, haplogroups called, ancient computed, in
about a minute with the reference PCAs cached.

**M6 is complete.** ROH is validated against the pinned native tools on synthetic
panels; archaic estimation is checked against the pinned AADR archive and a public reference
individual, with synthetic statistical and integration tests. Sex-chromosome call patterns
are validated on synthetic profiles, with shared PAR-aware QC and explicit karyotype limits.
M7 is complete: position/allele ClinVar lookup, allele-specific gnomAD
calibration, scoped PPV, ACMG gene-list surfacing and common-variant health cards are saved
and available to the CLI and dashboard. APOE preserves both markers and unresolved phase;
HFE C282Y and F5 Leiden carry published cohort absolute-risk context.
M7.6 adds quantitative position coverage, calls obtained and allele-resolved matches,
with separate reference/chip denominators and source-bound snapshots.
M8 is complete: pinned Beagle/Java and full autosomal/X panels/maps, shared default-on
phasing/imputation, native dosage quality, durable format-16 provenance and dedicated
imputed rare-call gate regressions. The [M8 overview review](review_m8_overview.md)
fixes saved rarity/provenance validation and error paths before the M9 handoff.
The final reviewed native suite passes **2,875 tests, five existing Windows skips**;
strict four-way types, lint/format, fixture reproduction and full dbSNP card lint pass.
M9.1 is implemented: streaming format-2 scoring-file ingestion, authoritative per-score
metadata licences, source-bound reference processing and offline CLI inspection.
M9.2 adds native PLINK sums, preserving original and imputed effect-dose/quality evidence,
private provenance and explicit unavailable/partial/unsupported states. M9.3 adds versioned
per-score coverage before and after imputation ([PGS coverage](pgs_coverage.md)).
M9.4 adds 1000 Genomes reference distributions and ancestry-matched percentiles
([PGS reference](pgs_reference.md)). The [M9.3–M9.4 review](review_m94_session.md)
moves panel verification ahead of personal input and tightens reload validation;
[the handoff](handoff.md) held M9.5's entry contract. **M9.5 adds cited
study-to-sample ancestry portability** to every schema-4 score result
([PGS portability](pgs_portability.md)). **M9.6 renders polygenic cards** in runs and
on the dashboard as a reference distribution with the person's interval, never a point
([PGS cards](pgs_cards.md)). **M9.7 physical-health and M9.8 mental-health
cards are accepted**, including full-panel extraction and both default-imputed
and explicit no-impute public-stand-in scoring. The
[session review](review_m97_m98_session.md) tightens frozen duplicate-proof
allocation and corrects CAD's European subgroup association.
**M9.9 psychometrics is complete**: three public UK Biobank-only models are authored
and pinned, with exact model evidence and unknown within-family effects explicit.
All full reference preparations, three default-imputed and three no-impute checks,
and six retained JSON disk-read validations passed. See the
[psychometric model audit and acceptance](psychometrics_prs.md).
The [M9.9 diff review](review_m99_session.md) confirms model-specific evidence
and pins, closes a swapped-model test gap and revalidates all six saved pairs.
**M9.10 substance use and behavioural propensity is complete**: three
UK Biobank-only models are authored, licensed, fetched and pinned; exact-model
effects and phenotype coding are audited. All complete reference preparations,
six native scoring checks and six written-record reload validations pass.
See the [model audit](substance_use_prs.md).
**M9.11 sleep and circadian is complete**. All three full references, six
scoring checks and six written-record reload validations pass; all 2,885
unique checks pass with five Windows skips. See the
[model audit](sleep_circadian_prs.md). **M9.12 fitness and physiology is
complete**: four variant cards and complete mean-grip PGS002143, with full
reference preparation, both scoring modes and both disk-read validations
passed. All 2,923 unique checks pass, five existing Windows skips.
See the [evidence audit](fitness_physiology.md). **M9.13 card-level
ancestry match is complete**: selected-outcome variant cards and PRS share one
1000 Genomes placement; explicit comparison states appear on the face and detail.
Format 18 preserves old snapshots and verifies saved comparisons/confidence.
All 2,995 unique checks pass, five existing Windows skips; four strict type
targets, full card lint, fixtures and privacy gates pass.
See [the evidence/contract audit](card_ancestry.md). **M10.1 is complete:**
all supplied CPIC definition/function/phenotype tables and ClinPGx annotation
tables are ingested, with source-bound GRCh37 proofs and offline inspection.
The [diff review](review_m101_session.md) corrects publication attribution,
atomic publication and parsing/validation defects. **M10.2 SNP-tractable diplotype
calling is implemented**, with all compatible alternatives, native ploidy and
source-specific phenotype joins retained in format 19. See the
[calling contract](pgx_calling.md). **M10.3 placement and M10.4 guideline
cards are complete.** M10.5 adds shared section framing; **M10 is complete**.
Start with the [current handoff](handoff_history.md#m112-entry-contract-implemented-retained-for-review).
The [M10.2 diff review](review_m102_session.md) records saved-evidence,
validation and presentation corrections with healthy calling results unchanged.
See [PGS scoring](pgs_scoring.md).
The [M9 diff review](review_m9_session.md) fixes parser/evidence/error-boundary and
native-report validation defects; [the handoff](handoff.md) defines M9.3's coverage
denominators, saved-input compatibility and synthetic acceptance matrix.
The [handoff](handoff.md) retains historical M8 acceptance and M9 entry contracts.
The [M7.5 session diff review](review_m75_session.md) records outcome-specific
confidence, saved-record consistency, marker-detail and lint-denominator fixes.
Download resumability debt is resolved and gnomAD's 63 GB exome file is verified.
The study-to-sample ancestry mapping M5.8 surfaced
belongs to [M9.5](#m9--prs-engine--score-driven-sections), and does not block M7.1 or M7.2.

**Current bundle format: 20**, with formats 1–19 preserved. The pack has 77 cards;
full local dbSNP lint resolves all 39 authored marker references (320 template renders).
M7.6: **2,188 tests passed, five existing Windows skips**, pinned native ROH enabled.
Strict mypy matrix, ruff/format and fixture reproduction pass. Thirty synthetic
regressions cover count/denominator honesty, exclusions, source states, saved integrity,
historical compatibility, unchanged rare-call reliability and CLI/dashboard parity.
Scoped synthetic-only M7.6 acceptance against the complete ClinVar/gnomAD/ACMG caches
passed offline through format-13 save/read and both interfaces; ancestry and structure
reference preparation are excluded from this acceptance, with native ROH tested separately.
M7.5 follow-up review: **2,158 tests passed, five existing Windows skips**, native ROH
enabled; strict mypy matrix, ruff/format, fixtures and full dbSNP lint pass. Knowledge
schema 3 / multi-marker schema 2 select outcome-specific phenotype evidence, retaining
null estimates and observation quality without rescoring historical snapshots.
M7.5 acceptance (2026-10-06): **2,135 tests passed, five existing Windows skips**,
pinned native ROH enabled; ruff/format, strict mypy platform/Python matrix and fixture
reproduction passed. Synthetic-only full-reference offline CLI/dashboard acceptance
passed with format-11 save/read. No personal export was used.
M7.4 review checkpoint (2026-10-05): **2,076 tests passed, five existing Windows skips**,
with native ROH checks enabled. Ruff, formatting, strict mypy on Windows/Linux and
Python 3.11/3.13, fixture reproduction and full card lint passed. The required gnomAD
exomes source passed its publisher MD5, and the complete **17,209,972-record** index
passed source/index verification and synthetic-only offline CLI/dashboard acceptance.
The preceding reviewed checkpoint (2026-10-04) is `690ea41`: **1,898 tests passed, five existing Windows
skips**, and [all five CI jobs passed](https://github.com/sovemere/genetics-analysis/actions/runs/37191147216).
Earlier milestone acceptance counts and format numbers below record what shipped then.

**M5.5's coverage gap is now closed as far as the available panel can honestly close it.**
[M5.9](#m5--ancestry) selects AADR Human Origins' present-day, diploid individuals into a
100-population panel covering the Middle East, North Africa, Oceania, Central Asia, Siberia,
unadmixed Indigenous American and deep-branching African populations. The refusal remains:
Aboriginal Australian and Khoisan references still sit below the population-size floor, and
the coverage statement names those gaps instead of rounding them off.

<details><summary>Settled: the sources that used to stand in front of M5 (2026-08-22 and
2026-08-23)</summary>

1. ~~**Fetch 1000 Genomes.**~~ **Done 2026-08-22: 25/25 fetched, marker subset built
   (290,285 markers over 2,504 samples), M5.2->M5.3->M5.4 verified end to end against it.**
   The lock gained 24 new digests. Took five passes: EBI truncated large transfers
   repeatedly and the fetcher discards an unpinned partial rather than resuming it, so each
   failure restarted from zero. That is correct for a *rolling* file and wrong for a frozen
   release that merely publishes no checksum -- `RemoteFile.unpinned_reason` is the field
  that could tell them apart. **Worth fixing before gnomAD exomes**, which is 63 GB in a
   single file where one truncation costs far more than a gigabyte.

2. ~~**Resolve HGDP, and decide whether M5.3 waits for it.**~~ **Settled 2026-08-22:
   M5.3 ships 1000G-only.** HGDP **cannot** be resolved -- CEPH withdrew individual
   genotypes for GDPR and serves only allele frequencies, `hagsc.org/hgdp/files.html` is
   404 while the site root still answers 200, the Rosenberg lab has only 517-2,810-marker
   subsets, and the CEPH panel page distributes *DNA samples* under a purchase order. The
   entry is marked `withdrawn-by-publisher` rather than left as a to-do nobody can
   complete. **SGDP is resolvable and deliberately deferred**: live, PLINK-format, measured
   to be GRCh37 -- but 70 of 345 samples need a signed letter and the 279 public ones span
   130 populations, about two samples each. Breadth in PCA space, useless as a centroid.

3. ~~**Resolve AADR.**~~ **Done 2026-08-23: fetched, and it was never gone.** The belief
   that it needed a human step rested on a 202 from the *DOI redirector*; the Dataverse API
   answers 200. v66.p1, CC0-1.0, all files public. Reclassified **tier B -> A**. See
   [M5.6](#m5--ancestry).

4. ~~**Resolve the Y tree.**~~ **Done 2026-08-23, and the answer was a licence rather than
   a URL.** `yhaplo` forbids redistribution outright, isogg.org sits behind a Cloudflare
   challenge, and Yleaf is GPL-3.0 over YFull/FTDNA data. The ISOGG table as redistributed
   under **MIT** by Y-LineageTracker is what made [M5.7](#m5--ancestry) shippable.

</details>

Download debt and the remaining probe limit:

- **Resolved 2026-10-05:** digestless frozen releases can resume with explicit
  `RemoteFile.immutable`, fixed size and verified URL/length/prefix-hash provenance.
  The 24 frozen 1000 Genomes chromosome files declare the policy. Rolling releases
  still discard unverifiable prefixes; a reason string is never treated as a policy.
  gnomAD exomes already has a publisher MD5 pin and uses final digest verification.

- **`refs probe` reads status codes, not meaning, and an entry carrying only a homepage
  cannot be probed into truth.** hgdp_grch37 showed the false green on a withdrawn source;
  aadr showed it on a source that was *fine* while every declared fact about it had gone
  stale. Neither is a bug in `probe` -- it is a limit on what a URL check can know, and
  both entries now say so.

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
      [AGENTS.md §2](../AGENTS.md). Four decisions are load-bearing, each a place where the
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
      - *Acceptance (local):* **passed 2026-08-15** — 677,436 markers and 8,830 indels via
        `genetics ingest --expect-counts`. The sample's own counts are not recorded here.
        Array panels: MT 263; PAR 36. `Adapter.verified_against_real_export` records that this ran, and
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
        ploidy unresolved rather than guessing: missingness, assay errors and chromosome
        variation can produce disagreement (M6.4); an unresolved locus is visibly unresolved while
        a wrongly resolved one is not.
      - `HET_HAPLOID` is its own status, so a heterozygous call at a single-copy locus
        stays countable instead of being dropped or read as a diploid genotype.
      - Build check has three layers: header assertion, coordinate bounds against GRCh37
        chromosome lengths (needs no reference data), and rsID anchors. **The committed
        anchor table ships empty** — writing coordinates from memory would be invented data
        ([AGENTS.md §6](../AGENTS.md)). Only anchors carrying a `source` may fail a run, so a
        wrong coordinate can lose information but never raise a false alarm. Same precedent
        as the empty `spike_ins` hook in M0.2.
        **Filled in M3.5, and not from dbSNP as written here**: the GRCh37 VCF cannot prove
        a GRCh38 coordinate, so the pairing comes from ClinVar's `variant_summary.txt.gz`,
        which publishes both assemblies per variant. 200 anchors, derived and uncommitted,
        loaded by `default_anchors()`; absent artifact leaves the check indeterminate,
        malformed artifact fails loudly.
      - QC **labels, never filters** ([AGENTS.md §0.1A](../AGENTS.md)): nothing here drops a
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
      - [x] HGDP + SGDP — **demoted to tier B with instructions, and resolved at M5.3.**
            Writing a plausible URL would have been the same failure as inventing a
            coordinate, so M2.3 wrote none. That restraint paid: chased down on 2026-08-22,
            **HGDP turned out to be withdrawn rather than unresolved** (CEPH removed
            individual genotypes for GDPR; `hagsc.org` is 404) and SGDP's real obstacle is
            that 70 of 345 samples need a signed letter, not that the release was ambiguous.
            A plausible URL would have sent someone hunting for a file that no longer
            exists. Both entries now carry the evidence.
      - [x] GWAS Catalog — real filenames differ from the obvious guess
            (`...-full.zip`, `gwas-catalog-studies.tsv`); only a rolling `latest/` exists.
      - [x] PGS Catalog metadata — see the §4.8 refinement below.
      - [x] PharmGKB + CPIC — **PharmGKB now serves under ClinPGx**; `api.pharmgkb.org` no
            longer resolves. Pinned to the redirect targets on `s3.pgkb.org` so a fetch
            does not depend on a redirect persisting. CPIC pinned at v1.60.0 by sha256.
      - [x] AADR — ~~tier B. Harvard Dataverse answered every API request with a bare 202.~~
            **Resolved at M5.7 (2026-08-23): tier A.** The 202 came from the DOI redirector;
            the Dataverse API answers 200 and every file is public. See AGENTS.md §5.2.
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
        ([AGENTS.md §4.9](../AGENTS.md)). `doctor` reports on them; nothing installs them.
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
- [x] **M2.6** `genetics refs fetch|status|verify|probe|licenses` CLI, plus `genetics tools
      list|install|status` as M2.5's entry point. Every command is `--json`-capable
      ([AGENTS.md §3](../AGENTS.md)) — a command reachable only as human text is one an agent
      cannot review, and M13.5's parity test starts being true or false here.
      - `refs status` reports **what a missing source costs**, not just that it is absent:
        "the rare-variant frequency gate (M7.2)" rather than "0/1 files".
      - `refs fetch --dry-run` exists because the required set is 92 GB and learning that
        afterwards is not useful. It also shows licence blocks before any bytes move.
      - Progress goes to **stderr**, throttled, so piping `--json` stays clean and a
        per-megabyte callback on a 63 GB file does not spend real time on terminal writes.
- [x] **M2.8** `genetics refs probe` — reachability and size-drift check over every
      declared URL, no payload transferred. **Added after HGDP, because HGDP is the failure
      it exists to catch.**
      - **`verify` was pointed the wrong way to catch it.** It hashes files already on
        disk, so it answers "does what we fetched still match what we recorded?" — a good
        question that is structurally incapable of noticing that a URL nothing has fetched
        yet has become a 404. The HGDP-CEPH genotype panel was withdrawn from the host the
        manifest named and no command in the repository could have seen it, because seeing
        it required a network request none of them was allowed to make.
      - **Catches three things**: a URL gone 404, a host that has gone away, and a *pinned*
        file whose size on the server no longer matches the manifest. The third is the one
        worth the code — that fetch is already doomed, the digest will fail, but only after
        the whole file transfers. gnomAD exomes is 63 GB and finding out at the end is not
        the same as finding out now.
      - **Does not catch a 200 that has stopped meaning yes**, and the docstring says so
        rather than letting a green probe read as proof the corpus is healthy. `cephb.fr`
        answers 200 today with every genotype removed behind GDPR; the Reich Lab data
        server answers 200 with a body reading `no access (s:code104)`. A probe reads
        status codes, not meaning. It narrows where a surprise can hide; it does not empty
        it.
      - **Exit code splits on pinned, not on drift.** Drift on an unpinned file is the
        manifest working as designed — ClinVar's `variant_summary.txt.gz` and the four
        rolling GWAS Catalog files are declared unpinnable *because* they move — and
        failing on them would make a scheduled probe permanently red, which is the same as
        having no probe. Unreachability is non-fatal for the same reason: a job that goes
        red when a public mirror hiccups is a job whose red gets ignored (M0.3).
        404 and pinned-file drift are what fail.
      - **`Prober` is a separate protocol from `Transport`, not a method on it.** A prober
        has no way to return a body, so "the probe accidentally downloaded 495 GB of
        gnomAD" is not a representable state — the same reasoning that made `Transport` a
        protocol in the first place, and the reason the test asserting it can check for the
        *absence* of an `open` method.
      - **HEAD is not universally answered, so there is a one-byte fallback.** Some hosts
        return 405 to HEAD and serve GET perfectly well; others answer 200 with no
        `Content-Length`. Both leave the probe unable to check the file it was pointed at,
        so it re-asks with `Range: bytes=0-0` and reads the total out of `Content-Range` —
        *not* out of that response's `Content-Length`, which describes the one byte and
        would report every file in the corpus as having shrunk to a single byte. That is
        `UrllibTransport.open`'s own bug, met again on the way out.
      - **Tier B sources are probed on their instructions URL**, since tier B is where the
        one real surprise came from and would otherwise be the only unprobed part of the
        manifest. Tool builds are probed too — PLINK 2 is pinned to an alpha, and alpha
        assets get pulled from `plink2-assets/` when the next one lands.
      - `--only` names sources, so it drops the tool URLs with them; returning plink2 and
        beagle rows from `refs probe --only clinvar_grch37` would answer a question nobody
        asked, in a report meant to be read by eye.
      - **Run live against the real corpus on 2026-08-22: 75 URLs in 7.9 seconds.** 73
        unchanged; two findings, both non-fatal and both already known to be so —
        `variant_summary.txt.gz` drifted +447,052 bytes (the manifest's one declared
        unpinnable ClinVar file, doing exactly what it was declared to do), and
        `omim/<manual instructions>` answers 403 because `api.omim.org` is credential-gated.
        Nothing pinned had moved.

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
      - **Except loopback that a proxy listens on (fixed 2026-09-24).** In a cloud container
        whose traffic all leaves through a proxy on `127.0.0.1`, urllib honoured
        `HTTPS_PROXY`, connected to loopback — allowed by the bullet above — and the proxy
        carried the request out. Two of this suite's own tests failed there while passing on
        every machine without a proxy. Closed twice: under the guard urllib sees an empty
        proxy table, so it connects directly and is refused by name; and a loopback `connect`
        to a configured proxy's port is refused whatever made it, which covers httpx and
        requests too. The regression tests stand up their own listener as the proxy, so the
        hole cannot reopen on machines where it would be invisible.
      - Resolution is blocked as well as connection: DNS is itself traffic, it is the step
        that discloses *what* is being fetched, and it still has the hostname in hand for
        the error message where `connect` has only an anonymous IP.
      - `NetworkAccessError` derives from `RuntimeError`, **not `OSError`** — `urllib`
        wraps `OSError` into `URLError`, so as an `OSError` the refusal would arrive
        disguised as an ordinary connection failure, which is precisely what fetch code is
        written to retry or report calmly.
      - *Demonstrated, not assumed* ([M0's lesson](progress_log.md#progress-log)): with `block_network`
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
        [AGENTS.md §6](../AGENTS.md) requires confidence to be computed; if a card could
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
        fabrication [§6](../AGENTS.md) forbids — unresolvable, so nobody checks it. `title` is
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
        coordinates from memory, the invented-data failure [§6](../AGENTS.md) forbids and the
        same reason `qc/build_anchors` and the `spike_ins` hook shipped empty. A test
        asserts the emptiness so whoever adds the first card meets the reasoning.
      - **Indel alleles are refused** ([§4.2](../AGENTS.md)) and **multi-variant cards are
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
      - **Every card gets a result** ([§0.1A](../AGENTS.md)). `match_pack` returns one
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
        `A`/`G`). That is [`ingest/keys.py`](../AGENTS.md)'s LocusKey/VariantKey asymmetry
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
      ([AGENTS.md §6](../AGENTS.md)). Inputs: evidence tier, effect size, replication,
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
      ([AGENTS.md §0.1A](../AGENTS.md)).
      - Assembly is cardinality-preserving: every matcher result becomes one evidence
        record, including absent, no-call, ambiguous, excluded, and likely-artifact
        results. It applies the rarest observed frequency and retains
        genotype/call-source/reference provenance without embedding a confidence shortcut
        in authored data.
      - **An incomplete frequency set degrades one card, not the pack** (review fix). It
        first *raised* when the reference had no frequency for an observed allele — which
        loses all 31 findings because one gnomAD row was thin, and that is the
        low-confidence filtering [§0.1A](../AGENTS.md) forbids, arriving as an exception
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
- [x] **M3.7** Impossibility cards for [AGENTS.md §3.2](../AGENTS.md): methylation/epigenetic
      age, somatic/tumour, CNVs (SMN1, RHD, alpha-thal, CYP2D6 hybrids), Y-STRs, mtDNA
      heteroplasmy, de novo mutations, telomere length, relative matching.
      - **12 cards under `knowledge/impossibilities/`**, one per §3.2 entry except the
        copy-number bullet, which names four specific findings inline and therefore gets
        five cards — the general limit plus SMN1, alpha-globin, RHD and CYP2D6.
      - **§3.2 is read out of AGENTS.md and compared against the pack, both ways.** §3.2
        asks for a "live register"; a register in one file and the cards it describes in
        another is [M0.4's lesson](progress_log.md#progress-log) waiting to happen — two ways of naming one
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
        "these were not known" rather than "these were known and average". On a real
        export, matched cards land below `strong`. The
        tempting fix — assume a frequency — is the rarity inversion in
        [AGENTS.md §4.1](../AGENTS.md) going quiet.
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
        on correct output is one somebody switches off ([M0.3](progress_log.md#progress-log)). The manifest
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
        on correct output is one somebody switches off ([M0.3](progress_log.md#progress-log)). Both halves
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
        ([AGENTS.md §3](../AGENTS.md): one engine, two front-ends) — and *reports* an unusable
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
        that is wrong about correct code on day one ([M0.3](progress_log.md#progress-log)). So: **what
        reaches a browser** (rendered HTML of every route, templates, first-party static
        files) is held to the literal rule; **everything else under `web/`**, vendored
        bundles and our own Python alike, is scanned for the shapes that *fetch* — `src=`,
        `href=`, `url(`, `@import`, `fetch(`, `new Worker(`. Holding Python to the literal
        rule would have made the docstring explaining the rule its own first casualty.
        The scanner is driven with seven references it must catch, including the
        protocol-relative `//host` form that reads as a comment and fetches anyway.
      - **Committed, not fetched** — the opposite of [AGENTS.md §1.4](../AGENTS.md) for
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
        failing on correct output the day cards land, and [M0.3](progress_log.md#progress-log) settled what
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
      ([AGENTS.md §0.1A](../AGENTS.md)). Detail view shows effect size, base rate, source
      population, caveats, and clickable citations.
      - **The milestone moved the bundle format, and that is the entry's main content.**
        "Effect size, base rate, source population" is a display requirement that version 1
        could not meet: it stored `confidence.inputs.effect_measure` and `effect_value`,
        which are the *scoring* inputs, and dropped everything that does not affect a score
        — units, the confidence interval, the sample size, the study population, and the
        `context` sentence saying what the number is a proportion *of*. Rendering
        `proportion 0.992` as "the effect size" would have been the vaguer sensitive card
        [§0.1B](../AGENTS.md) names as a defect, and the alternative — reaching back into
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
        on the argument that a variant plus a person is the genotype ([§1.3](../AGENTS.md)).
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
        `ubuntu-latest` was Ubuntu 24.04, which restricts unprivileged user namespaces through
        AppArmor: `unshare --map-root-user --net` creates the namespace and is then denied
        the uid mapping (`write failed /proc/self/uid_map: Operation not permitted`). A
        detector that looked for `unshare` on `PATH` would have called that machine capable —
        the probe is the reason this surfaced as a named failure instead of a green tick. The
        fallback is `sudo -n -E unshare --net`, and both halves of that are deliberate: `-n`
        makes sudo fail instead of prompt, and it is **only attempted when the caller says
        isolation is required here**, so a developer with cached credentials never has part of
        the suite silently run as root while CI still gets the real thing.
        **Changed 2026-11-15:** the fallback is now
        `sudo -n --preserve-env=<names> unshare --net`. `ubuntu-latest` is Ubuntu 26.04
        since some time between this repository's runs of 2026-11-13 and 2026-11-14 (UTC).
        It refuses the unprivileged namespace as 24.04 did, and its `sudo -E` no longer
        passes the environment, so the probe's second question failed both Linux jobs by
        name. The new form passed on 26.04. See the progress log.
      - **The probe asks two questions, not one**, and the second only became necessary when
        `sudo` joined the list: sudo resets the environment by default, so a mechanism could
        take the network away and quietly drop `GENETICS_DATA_DIR`, running the pipeline
        against the wrong store and passing. The child reports its interfaces *and* echoes a
        per-call token, in one process, so neither answer can come from a different one.
      - Re-verified at full pipeline scope by [M15.1](../phase1_roadmap.md#m15--v1-release-gate).

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

- [x] **M5.1** PLINK 2 wrapper (`external/plink2.py`): subprocess, argument building,
      error surfacing, version pinning.
      - **The pin is enforced, not documented.** `Plink2.discover()` runs the version probe
        from `data/tools.yaml` and refuses anything else, because a wrapper that executed
        whatever answered to the name `plink2` would quietly undo AGENTS.md §4.9 — and
        ancestry coordinates from an untested alpha build look exactly like ancestry
        coordinates from the pinned one.
      - **Errors are relayed from stderr; warnings are parsed out of the log.** The two
        differ because PLINK's channels differ. Its whole error goes to stderr and nothing
        else does, so quoting it is exact — and it has to be, since the second line of
        `Error: Unrecognized flag (...)` is `For more info, try ...`, unwrapped and
        unprefixed, and a length-based continuation rule would drop the actionable half.
        Warnings have no channel of their own and arrive interleaved with progress output,
        so they are recovered from PLINK's fixed-width wrapping. That heuristic is biased
        toward truncating on purpose: the lines after a warning are `Writing <absolute
        path> ... done.`, so over-reading puts the machine's directory layout into every
        warning. The first implementation did exactly that, which is why there is a
        regression test built from a real log.
      - **The log's header is never surfaced.** It opens with the machine's hostname and
        working directory. `.gitignore` blocks `*.log`, but an exception travels further
        than a file does.
      - Exit codes were read off the pinned build rather than guessed: 3 unreadable file,
        8 unrecognised flag, 13 empty input.
      - `find_executable` moved to `refs/tools.py` so `doctor` and this share one lookup.
        Two copies is how M2.5 produced a `doctor` that reported PLINK 2 missing straight
        after installing it.
- [x] **M5.2** Convert normalized table → PLINK pgen; harmonize alleles against the
      reference panel; handle strand and allele-order mismatches explicitly.
      - **The intermediate is a VCF because a single sample cannot establish REF.** PLINK 1
        `.ped`/`.map` has no REF/ALT concept, so PLINK assigns them from allele frequency —
        and with one sample that is a coin toss between 0, 0.5 and 1. Every marker's
        reference allele would be decided by that sample's own genotype, which is backwards:
        M5.4 subtracts reference means and multiplies by reference loadings, so an allele
        coded against the wrong reference is a coordinate with its sign flipped.
      - **Allele order is not information.** `a1`/`a2` are alphabetically sorted by M1, so
        pairing `a1` with REF would read an artefact of sorting as biology. Orientation is
        decided by set membership and emitted as allele indices.
      - **Strand-ambiguous sites are dropped whole, heterozygotes included.** `AT` encodes
        to `0/1` on either strand, so keeping it looks free — and M3.2's matcher does keep
        it, correctly, because there the question is which outcome one card reports. Here
        the question is distributional: keeping only the heterozygotes makes missingness
        depend on genotype, so the site's surviving dosages are all exactly 1, and
        mean-imputation then pulls the projection toward a value the data never supported.
      - **Two consequences worth carrying to M5.3.** A/C/G/T is two complementary pairs, so
        any allele set of three or more contains one and is ambiguous: **every surviving
        site is biallelic**, one of A/C, A/G, C/T, G/T. And each of those unioned with its
        own complement is all four bases, so **a homozygote can never be an allele
        mismatch** — only a heterozygote can. A suite that used homozygotes throughout
        would look thorough and never exercise that branch.
      - **Autosomes only, and not as a parameter.** PLINK refuses a chrX record outright
        (`Error: chrX is present in the input file, but no sex information was provided`),
        and a doubled hemizygous call written as a diploid homozygote would be a fabricated
        second allele. M6.4 now shares PAR-aware QC and ploidy handling; extending this
        converter to non-autosomes still needs an explicit sex/ploidy-aware export contract.
      - The report's ten outcomes **partition the array's autosomal positions exactly
        once**, so the count is readable as coverage rather than as overlapping tallies —
        which is what M9.3's per-score coverage figure has to be built from.
      - Verified against the real pinned binary: a synthetic panel over the committed male
        fixture gave 2,896 records from 11,519 autosomal positions, and **every written
        record decoded back to the original call or its exact complement, none wrong**.
      - `.gitignore` gained `*.pvar.zst` and `*-temporary.*`: PLINK's conversion
        intermediates are zstd-compressed, so `*.pvar` does not see them, and they survive
        a crash.
- [x] **M5.3** Build reference PCA from **1000 Genomes** on array-overlapping markers;
      LD-prune first. Cache the eigenvectors as a fetched-reference artifact.
      - **Originally scoped to 1000G-only on 2026-08-22, then superseded by M5.9.** HGDP is
        withdrawn and SGDP is ~2 samples per population, so 1000 Genomes remains the
        reproducible baseline this milestone built. M5.5 measured its cost: hold an entire
        super-population out and it correctly refuses 100% of South Asians, 100% of East
        Asians and 99.7% of Africans. M5.6 then established that the already-fetched AADR
        Human Origins set carries 8,474 present-day individuals across the missing regions;
        [M5.9](#m5--ancestry) turns those into the widened production reference artifact.
      - **Done: the marker subset.** `build_pca_marker_subset` is implemented and no longer
        the registry's only lie — it was marked `implemented=False` while the manifest
        declared it, so `refs fetch` reported it PENDING forever. Per autosome: convert to
        pgen keeping only common biallelic ACGT SNPs, drop the long-range LD regions,
        LD-prune, extract; then one `--pmerge-list` across the twenty-two.
      - **The step is deliberately *not* array-restricted, and that reverses the flag the
        registry carried.** `output_is_genotype_derived=True` forces an output outside the
        checkout, and it means "this transform reads a genotype export" — which the
        milestone's own wording ("array-overlapping markers") made look true, since an
        array's marker list has to come from somebody's file. Pruning the panel alone keeps
        the artifact a function of public 1000G data, so it lives beside the payload exactly
        as the manifest entry already said it could. **The array intersection moves to the
        eigenvector build**, where an export is genuinely in hand and where a subset chosen
        by one person's chip is not silently reused for the next person's. Give this step a
        marker list and the flag goes back to True with the output following it out of the
        tree.
      - **Long-range LD regions are excluded before pruning.** Not a refinement: a single
        inversion spanning tens of megabases contributes enough correlated markers to claim
        a principal component outright, and the resulting axis separates inversion carriers
        from non-carriers while looking exactly like an ancestry axis. LCT, MHC, 8p23 and
        17q21.31 — the conservative core of Price et al. (2008, *Am J Hum Genet*), not the
        whole table, because reproducing the rest from memory is the fabrication AGENTS.md
        §6 forbids.
      - **The effective settings are written into the provenance sidecar**, not left to
        `transform_version`. A changed default would otherwise leave every existing artifact
        looking current, and this is an artifact somebody waits hours for and will not
        rebuild on a hunch. Verified: flipping `r2` from 0.2 to 0.1 invalidates and rebuilds
        to a different marker count with no version bump.
      - **A pgen is three files and the sidecar covers all three.** `validate_provenance`
        hashes what it is pointed at; a `.psam` swapped for one naming different samples
        leaves the `.pgen` byte-identical and every projection silently mislabelled. Row
        count is read from the `.pvar` for the same reason.
      - Restartable per chromosome, with the stamp bound to the input digest *and* the
        settings — twenty-two passes of minutes each, so losing the lot to an interruption
        three hours in is not a theoretical cost. The work directory survives a failure and
        is removed only on success, where it would otherwise hold a second copy of every
        marker in the artifact.
      - `estimated_workspace_bytes` now falls back to the whole source for a step that names
        no `input`; it had been reporting a 16.75 GB transform as needing no disk at all.
      - **The whole chain was run once, end to end, against the real pinned binary.** Over a
        panel synthesised on the committed fixture's own coordinates: subset built (6,288
        markers), `--pca 4 allele-wts` over it, M5.2 harmonised the fixture against the
        resulting `.pvar` (6,288 records, every one `as_written`, 5,231 array positions
        correctly reported `not_in_panel`, and the two summing to the fixture's 11,519
        autosomal positions), and `--score` produced PC coordinates for the sample. So the
        artifact this step writes is one M5.4 can actually consume.
      - **Two things that only showed up by running it, both for M5.4/M5.3's remaining
        half.** `--indep-pairwise` refuses a panel with fewer than 50 samples, and `--score`
        refuses to impute frequencies from fewer than 50 — which for a *single* sample means
        **the projection needs `--read-freq` against a reference `.afreq`**. The eigenvector
        build must therefore emit `--freq` alongside `--pca allele-wts`; without it M5.4
        fails at the last step with an error about allele frequencies rather than anything
        that sounds like a missing artifact.
      - **Done: the eigenvector build** (`ancestry/reference_pca.py`). `--pca N allele-wts`
        plus `--freq` over the subset, narrowed to the markers the export's array carries,
        cached under `cache_dir()` and keyed by panel + marker set + settings together.
      - **It lives in a new `genetics.ancestry` package rather than in `refs/postprocess`,
        and that follows from where the array enters.** A post-process step runs at *fetch*
        time, before any export exists, and its output lands under `data/references/`. This
        step takes the array's marker list, so it is a function of the user's file and
        belongs in `cache_dir()` ([AGENTS.md §1.5](../AGENTS.md)). M5.4–M5.8 land beside it.
      - **The intersection is not re-pruned, which reverses this milestone's own wording
        above** ("intersect this subset with the array and prune again"). Intersecting
        cannot create linkage: pruning guarantees no two *retained* markers exceed the r²
        threshold, and every subset of a set with that property still has it. A second pass
        would spend a pass over the panel removing markers it has no reason to remove.
      - **`--pca` and `--freq` are one invocation, and that is correctness rather than a
        saved subprocess.** M5.4 pairs the weights with these frequencies; two invocations
        leave a flag able to drift between them and produce a pair that disagrees about
        which markers or samples they describe, which nothing downstream would notice.
      - **Markers are selected by `--extract bed1` ranges, not by variant ID** — the same
        mechanism the subset step uses for `--exclude bed1`, and it does not depend on the
        panel having usable IDs. IDs are still *checked*, because M5.4's `--score` joins on
        them: a missing or duplicated ID does not fail the projection, it makes it match the
        wrong row or none, and the coordinates still plot. Refused here where the message
        can say so.
      - **The sidecar covers all three outputs and records which panels went into it.** An
        `.eigenvec.allele` beside an `.afreq` computed over different markers projects every
        sample slightly wrong while both parse cleanly — the marker subset's three-file
        lesson. The panel list is there because widening to SGDP later produces a different
        artifact that would otherwise look current, the same failure the `r2` provenance fix
        prevents for LD settings.
      - **Keyed so one person's chip cannot be reused for the next person's**, which is the
        requirement that moved the intersection here in the first place. Two arrays that
        intersect the panel at the same *count* but different markers must still get
        separate artifacts — and the first version of that test asserted only the count, so
        it passed with the marker-set digest neutered. Found by neutering, then sharpened;
        all ten guards are verified that way.
      - Two floors, both from measurement rather than taste: a panel under 50 samples is
        refused here because PLINK will not compute the frequencies M5.4 reads back, and an
        intersection under 1,000 markers is refused because the realistic cause is a build
        or chromosome-naming disagreement rather than a sparse chip — and a PCA over two
        hundred markers still returns numbers.
      - The `--extract` range file is removed in a `finally`, so a failed PLINK run does not
        leave a line-per-marker file behind in the cache — the reasoning `to_pgen` already
        applies to its harmonized VCF one directory over.
      - **Verified against the real binary in the M5.4 review pass**: the array intersection
        came back at exactly the expected marker count, the artifact was accepted by
        `--score`, and a second call reused the cache.
      - **[x] Run against the real 1000 Genomes panel, 2026-08-22 — and it failed first
        time, on something no synthetic fixture could have shown.** `--indep-pairwise`
        refused with exit 7: *"requires unique variant IDs"*. **1000 Genomes phase 3 ships
        no variant IDs at all** — a full scan of the real chromosome 1 VCF found zero
        non-`.` IDs in any record. The existing `--rm-dup exclude-all` did not help, because
        it deduplicates by position and alleles rather than by ID, and its comment ("1000
        Genomes carries repeated variant IDs") was simply wrong about the data.
      - **Only half of that failure announced itself, which is the part worth remembering.**
        `--indep-pairwise` stops. [M5.4](#m5--ancestry)'s `--score` joins the sample to the
        reference weights *by ID* and would have matched nothing at all — returning
        coordinates rather than an error. The `_check_ids` guard written into the eigenvector
        build during the M5.4 review would have caught that silent half; the fix belongs
        upstream, and is now here.
      - **IDs are synthesised as `chrom:pos:ref:alt`** via `--set-all-var-ids`, with
        `--new-id-max-allele-len 23 missing` because IDs are assigned at load, before
        `--snps-only` filters, so one long indel allele would otherwise abort the whole
        conversion. Unique by construction for the biallelic ACGT SNPs kept here, and
        automatically shared with the sample because M5.2's harmonizer copies `panel_id`
        into the sample's VCF. `transform_version` bumped to 2: every artifact built before
        this carries `.` for every marker.
      - **The real artifact: 290,285 markers over 2,504 samples**, all IDs unique, none
        blank. Measured on chr22 alone before committing the fix: 1,055,454 biallelic ACGT
        SNPs → 97,216 after MAF and missingness → 5,954 after LD pruning.
- [x] **M5.4** Project the sample onto reference PCs via `--score`
      ([AGENTS.md §4.6](../AGENTS.md) — PLINK 2, **not** ADMIXTURE).
      `ancestry/projection.py`.
      - **Needs `--read-freq` pointing at the reference's own `.afreq`.** Measured, not
        assumed: with one sample PLINK refuses to impute allele frequencies and stops with
        "less than 50 samples are available to impute them from". Flags that worked in the
        M5.3 trial run: `--score <ref>.eigenvec.allele 2 5 header-read no-mean-imputation
        variance-standardize --score-col-nums 6-<n>`.
      - **`project()` takes any pgen, not "the sample's", and that is the design rather
        than generality for its own sake.** PLINK reports `SCORE1_AVG`-style averages whose
        absolute scale relative to the reference's own `.eigenvec` this module does not
        assert — deriving that constant from memory is the plausible-looking fabrication
        [AGENTS.md §6](../AGENTS.md) forbids, and getting it subtly wrong would move every
        sample the same distance in a way no test would catch. **The scale does not need to
        be known.** What M5.5 needs is that the sample and the reference populations are
        *comparable*, which is guaranteed by construction if both go through this same
        function: whatever the constant is, it is the same one on both sides. So M5.5
        projects the panel through here too rather than reading coordinates out of
        `.eigenvec` and hoping the units agree.
      - **`no-mean-imputation` is a stance, not a default.** A no-call contributes nothing
        instead of contributing the mean. Mean imputation pulls every sparsely-called
        sample toward the origin, which on an ancestry plot reads as "averagely admixed"
        rather than as "we know less about this person" — the euphemism
        [AGENTS.md §0.1B](../AGENTS.md) forbids, expressed as a flag.
      - **Coverage is reported as a number, not a verdict.** `Projection.coverage` is the
        fraction of the reference's markers that actually scored, and it is M5.5's input to
        confidence ([AGENTS.md §6](../AGENTS.md): confidence is computed, not authored). A
        separate hard floor at 50% catches the *structural* failure instead — genotypes
        harmonized against a different panel carry variant IDs the reference lacks, so
        `--score` matches almost nothing and still returns finite coordinates that plot
        somewhere plausible.
      - **The `.sscore`'s component columns are located by name, not by position.** Its
        leading columns vary with the flags in play (`ALLELE_CT`,
        `NAMED_ALLELE_DOSAGE_SUM` and friends appear conditionally), so counting from the
        left is a way to read a dosage total as a principal component. Verified by
        neutering: reading positionally passes every other test in the file.
      - **A ragged `.sscore` is refused rather than padded**, found by writing a test whose
        stub header and rows disagreed. Padding put an empty string where a coordinate
        belongs and the failure surfaced as a Polars cast error naming a column rather than
        a truncated file.
      - **Two bugs in the first version, both found by the review pass running the real
        binary, and both of which every test in the file passed — because the stub encoded
        the same assumptions the code did.** Recorded here because the pattern matters more
        than either bug: a stub written from the same belief as the code under test verifies
        the belief, not the behaviour.
        1. **The component columns are `PC1_AVG`, not `SCORE1_AVG`.** `header-read` makes
           PLINK name each output column after the score file's own, and a
           `.eigenvec.allele` names its columns `PC1..PCk`. The reader looked for `SCORE`,
           found nothing, and would have raised on the first real projection.
        2. **`ALLELE_CT` counts alleles, not markers.** A sample with 5 of 100 variants
           no-called reports 190 — twice the 95 that scored. Read as a marker count it made
           `coverage` report **1.9 for a 95%-called sample**: not merely wrong but
           impossible, and it fed M5.8's PRS confidence.
      - **Now verified end to end against the pinned binary, both directions.** Over a
        synthetic 60-sample panel: reference PCA built on the 2,000-marker array
        intersection, cache reuse confirmed, one sample projected to 3,800 alleles → 1,900
        markers → **95.0% coverage**, and the whole 60-sample panel pushed through the same
        `project()` at 100% — which is the path M5.5 depends on for comparable coordinates.
        The measured `.sscore` header is pinned in a test so neither fact can drift back.
      - Seventeen guards, each verified by neutering it.
      - **[x] Run end to end against the real 1000 Genomes panel, 2026-08-22.** A synthetic
        650,000-marker array whose positions are drawn from the real pruned subset (the
        committed fixture's coordinates are invented and intersect nothing real):
        intersection 50,018 markers, ten components over 2,504 samples, eigenvalues
        202.0 / 85.3 / 26.2 / 19.5 — the steep first gap global human structure should give.
        M5.2 harmonised 41,816 of the 50,018, and M5.4 projected them at **83.6% coverage**
        with every panel site accounted for: 41,806 `as_written`, 10 `complemented`, 8,199
        `ambiguous_site`, 1 `allele_mismatch`, 2 `duplicate_conflict`.
      - **That 83.6% was a warning for [M5.5](#m5--ancestry), not a defect here — and M5.5
        took the second of the two ways out.** The shortfall is strand-ambiguous A/T and C/G
        sites, which M5.2 drops by design, so `coverage` had a floor unrelated to call
        quality and a confidence model reading it as quality would under-rate every sample
        by the same margin. The options were to grade coverage against the markers M5.2
        could *use*, or to exclude ambiguous sites from the eigenvector build. **The second
        shipped**: it costs a rebuild of the cached artifact and leaves no second denominator
        in the artifact for somebody to divide by wrongly. Real-export coverage went
        **83.6% → above 99%**.
      - **The "~16% of common SNPs" in the paragraph above was right about SNPs and wrong
        about this chip**, which is the lasting lesson. The real array lost only **4.2%** to
        ambiguity, because a consumer array avoids A/T and C/G probes by design. The 16%
        came from *this milestone's own synthetic array*, whose positions were drawn
        uniformly from the panel — so it had the panel's ascertainment rather than a chip's.
        A synthetic fixture sampled uniformly from a reference does not inherit the
        reference's design properties, and a number measured on one is a number about the
        fixture.
- [x] **M5.5** Continuous ancestry coordinates + nearest reference populations with
      distances. `ancestry/populations.py`. **No percentages at all** — a pie chart implies
      an admixture decomposition this module does not compute.
      - **It must be able to refuse to name a population, and that was the load-bearing
        requirement.** With 1000G alone (M5.3) there is no correct answer for Middle
        Eastern, North African, Oceanian, Central Asian, Siberian, unadmixed Indigenous
        American, or Khoisan/Mbuti ancestry — those populations are simply absent. A
        nearest-neighbour report over an incomplete panel does not return "no match"; it
        returns the least-bad label with a distance attached, which reads as an answer.
        Lebanese comes back as Tuscan.
      - **The reason this is not cosmetic is [M5.8](#m5--ancestry).** Ancestry feeds PRS
        confidence ([AGENTS.md §4.4](../AGENTS.md)), so a Middle Eastern sample quietly
        labelled European gets PRS confidence that is *too high*. A wrong ancestry call does
        not stay on the ancestry card.
      - **The M5.4 coverage decision was taken the tidy way: strand-ambiguous sites are now
        excluded from the eigenvector build**, so `coverage` measures the sample again. The
        same panel-only predicate the harmonizer applies (`harmonize.panel_exclusion`) is
        imported rather than restated, because two copies of that rule drifting apart *is*
        the gap. `ARTIFACT_VERSION` 1 → 2. Measured on the real export: intersection
        **54,725 → 52,411** usable, and **coverage 83.6% → above 99%**.
      - **The 16% estimate was wrong about this chip, and the reason is worth keeping.**
        Only **2,314 markers (4.2%)** were strand-ambiguous, not ~16%. The 16% figure came
        from the M5.4 run's *synthetic* array, whose positions were a uniform draw from the
        panel; a real consumer array avoids A/T and C/G probes by design. **A synthetic
        fixture drawn uniformly from a reference does not have the reference's ascertainment
        properties**, which is the same shape of error as the M5.4 stub lesson.
      - **Distances are in pooled within-population standard deviations, and that removes a
        constant this project refuses to assert.** M5.4 will not claim the scale relating
        PLINK's `--score` averages to the reference's own `.eigenvec`; dividing every axis by
        the panel's own within-population spread cancels it, whatever it is. *Within*, not
        total: total spread on an axis is mostly the separation between populations, so
        dividing by it would shrink precisely the axes that separate. Diagonal, not a
        covariance matrix — the smallest 1000G population is 61 samples.
      - **Ranked by distance, admitted by fit — two numbers on purpose.** `fit` is distance
        over that population's own median member distance, so 1 is a typical member. It is
        right for *"could this sample be from there"* and wrong for *"what is nearest"*,
        because a diffuse population has a large radius and attracts anything unusual:
        ranked on fit, a held-out **Finnish sample's nearest population comes back as MXL**.
        Ranked on distance it comes back as CEU. So the list is ordered by distance and the
        call is the **closest population that fits** — not "the closest one, if it fits",
        which measured worse: it refused 17% of held-out ACB, 23% of PJL and 19% of CHS,
        each with a good sibling one step down, while refusing nothing extra where refusing
        is the point.
      - **The threshold is measured from the panel, not chosen.** It is the 99.5th
        percentile of the panel's own members' fit to their nearest population, computed at
        build time with a closed-form leave-one-out correction, so it is a sentence rather
        than a constant — *decline when this sample sits farther from every reference
        population than 99.5% of the panel's own members sit from theirs* — and it moves on
        its own when the panel widens. **On the real panel it is 2.65.** `n_beyond_threshold`
        reports how many members sit above it (11 of 2,504), because on a small panel the
        same quantile lands on the maximum and the bar becomes "farther than the single most
        extreme member we happen to have".
      - **Validated by holding populations out, which is the Lebanese case reproduced inside
        the panel.** Of 2,504 members, 9 are declined (0.36%); of those named, 82.0% get
        their own population and **99.3% their own region**.

        | Held out | Declined | Nearest named |
        |---|---|---|
        | ACB, BEB, CEU, CLM, GBR, IBS, ITU, MXL, PJL, PUR, STU, TSI, YRI | 0% | correct sibling |
        | CHS 5%, ESN 5%, CDX 6%, ASW 10% | low | correct sibling |
        | **GIH 65%, CHB 63%, GWD 97%, JPT 99%, FIN 100%, LWK 100%, MSL 100%** | high | *refuses* |
        | **whole region: SAS 100%, EAS 100%, AFR 99.7%, AMR 96.8%, EUR 85.3%** | | *refuses* |

        The whole-region rows are the closest this panel offers to the Oceanian, Central
        Asian or MENA case. EUR is the weak one at 85.3%, for an honest reason: held-out
        Europeans land nearest PUR, which genuinely carries substantial European ancestry.
      - **Ten components, not four, and the eigenvalues are not a reason to truncate.** They
        fall 192.6 / 101.6 / 29.4 / 23.3 / 4.6 / 4.1, which reads as an invitation to keep
        four. Measured, four breaks the refusal outright: **held-out JPT, LWK, MSL, GWD and
        GIH are all named anyway at 0% declined**, at a fit near 1 — the Lebanese failure
        reproduced — and naming the right population drops from 82.0% to 69.4%. The small
        eigenvalues are small because within-continent structure is a small share of
        *global* variance, and within-continent is the whole question.
      - **The region rides with the population call rather than getting a looser rule, and
        that was measured too.** "We cannot name a population, but this is broadly European"
        is exactly the over-call §4.4 warns about. A held-out FIN sample — a European whose
        population is genuinely absent — sits at fit **9.0** from CEU, while held-out
        *whole-region* samples with no representation at all reach their nearest population
        at **5.3** (South Asian) and **9.1** (East Asian). Any bar loose enough to keep the
        Finn admits every one of them, so no threshold separates the two cases.
      - **The coverage-honesty statement is attached to the population set it describes.**
        `PanelCoverage` names all 26 phase-3 codes and `coverage_for` returns it only on an
        exact match. M5.9 adds a separately measured statement for its exact 100-population
        set; an arbitrary third panel still returns `None`, which callers must render as
        "nobody has written down what this panel cannot answer for" and **not** as "no
        gaps". That is [AGENTS.md §5.2](../AGENTS.md)'s `refs probe` lesson pointed at a
        different declared fact: a claim nothing re-verifies stays green while going stale.
      - `Projection` gained `reference` — the artifact prefix's name — so a sample projected
        against one eigenvector set cannot be placed against centroids built from another.
        Two such coordinate sets have the same columns, the same count and the same order of
        magnitude, and they plot.
- [x] **M5.6** AADR projection: affinity to ancient populations, labelled *affinity* and
      not descent. `ancestry/eigenstrat.py` reads the archive; `ancestry/aadr.py` is the
      milestone.
      - **Four facts had to be measured off the 4 GB archive, and two of them would have
        been wrong from the format description.**
        1. **The genotype file is `TGENO`, not `GENO` — a transpose.** Records run one per
           *individual*, not one per SNP. Measured layout, and it divides exactly:
           `48-byte header + 27,594 × 146,033 = 4,029,634,650 bytes`, record length
           `ceil(n_snps / 4)`. That shape is lucky here: selecting a few thousand ancient
           individuals costs a seek each rather than a pass over four gigabytes. **`GENO` is
           refused rather than guessed at** — its layout is documented and would be a dozen
           lines, but no `GENO` file is pinned, so those lines would be untested code
           standing between an archive and an ancestry claim.
        2. **Codes are 0/1/2 = copies of the `.snp` row's first allele, 3 = no call.** Not
           EIGENSTRAT's textual `9`; two bits cannot spell it.
        3. **The ancient genotypes are pseudo-haploid, and the file says so if you count.**
           Of 13,832 well-covered ancient individuals, **13,757 carry no heterozygous call
           at all** (99.2%) — capture data is published as one randomly drawn read per site,
           doubled. Loschbour decodes to 273,929 twos, 93,902 zeros and **zero ones**. So an
           ancient *group centroid* is meaningful and an ancient *individual's* position is
           not, which is why nothing reports a per-individual match. Counted per individual
           rather than read off the `.DG`/`.SG` suffix, because those shotgun genomes
           genuinely are diploid.
        4. **Present-day individuals are marked by a date of 0**, not by a missing one:
           8,474 living Human Origins samples against 19,119 ancient. Collapsing "sampled
           today" into "date unresolved" would put the living ones in an ancient panel.
      - **It needs its own PC space, and that is the milestone's one real design decision.**
        AADR Human Origins is an Affymetrix design and the export is Illumina: they share
        **11,128 of the 52,411** markers M5.5's reference PCA covers. Projecting ancients
        onto axes computed from markers most of them lack would put ancient and modern
        coordinates on systematically different marker subsets, and the overlap is not a
        random draw of the whole, so `--score`'s `_AVG` normalisation does not rescue it.
        `build_reference_pca` gained `restrict_to` and `space`; the shared space is built on
        what the array, 1000G and AADR all carry. **Its eigenvalues are 196.7 / 100.0 / 29.3
        / 23.3 against the full space's 192.6 / 101.6 / 29.4 / 23.3** — the structure
        survives the cut. It is also what ancient-DNA practice does for an unrelated reason:
        axes come from modern diploid samples and ancients are projected, never allowed to
        define the axes they are placed on.
      - **The packed header carries its own integrity check, and the first version of the
        reader discarded it (fixed 2026-08-24).** `TGENO`'s two trailing header fields are
        EIGENSOFT's `hasharr` over the `.ind` identifiers and the `.snp` rsIDs; both were
        reproduced bit for bit against the pinned file before the algorithm was trusted.
        `open_packed` now verifies them, which is the only one of its four checks with any
        power over a **same-shaped wrong** companion file -- and the release ships exactly
        that hazard, since the HO and compatibility-HO `.ind` files are byte-identical and
        the individual count therefore discriminates nothing between the two datasets.
      - **Zero of those 11,128 markers are strand-ambiguous**, which is not luck: an aDNA
        capture panel excludes A/T and C/G sites because C→T deamination makes them
        undecidable. The M5.5 exclusion therefore costs nothing here and the flip in
        `write_ancient_vcf` is decidable with no tie-break.
      - **Distances are scaled by the modern panel, not the ancient one.** The metric is
        M5.5's `PopulationModel` fitted in this same space — diploid samples with
        essentially complete data. Scaling by the ancients instead would let pseudo-haploid
        noise and missingness set the ruler, shrinking every axis on which ancient data is
        noisiest, which is backwards.
      - **Two floors, both measured.** An ancient individual must call **half** the shared
        markers (median is 7,444 of 11,128; lower quartile 4,985), which keeps **9,700 of
        13,832**. A group needs **5** individuals — not M5.5's 20, because nothing here
        estimates a spread or names anything, only places a centre. AADR's group labels are
        archaeological contexts with a **median size of two**: of 2,311 groups with a
        well-covered member, 442 reach five and 92 reach twenty. Twenty would drop most of
        the archaeological record; five keeps 442 groups over 6,672 individuals and reports
        the count beside every distance.
      - **Validated against modern samples of known ancestry, and the validation also
        measures the method's own limit.** Ten samples from each of fifteen 1000 Genomes
        populations. Unadmixed populations land where they should: GBR → Denmark_Viking /
        Germany (d=1.53), TSI → Italy / Spain (1.83), **CHB → China 10/10** (2.36), **JPT →
        RepublicofKorea_ThreeKingdoms 10/10** (4.30), CDX → Taiwan_IA 9/10, **LWK →
        Cameroon_ShumLaka 10/10**, STU → Pakistan_Historic 10/10. And the recently admixed
        ones fail exactly as a nearest-centroid report must: **MXL, roughly half European
        and half Indigenous American, comes back nearest to medieval Germany and
        Avar-period Hungary** — groups it descends from not at all, because the midpoint of
        its two sources lands there. That is not a bug to fix; it is what the method *is*,
        and it is the measured reason the output says affinity. `AncientAffinity` has no
        `nearest_group` accessor for the same reason: a single accessor is how a ranked list
        quietly becomes a claim.
      - **No ancestry model, deliberately.** Proportions need f-statistics or qpAdm over
        outgroups this project does not fetch, and deriving them from distances is the
        fabrication [AGENTS.md §6](../AGENTS.md) forbids. What ships is a distance, in units,
        ranked, with `spread` (nearest to median) so a card can say whether the ranking
        separates anything.
      - **Two defects found by running it, both now guarded.** (1) `project()`'s 50%
        coverage floor rejected the ancient panel with a *confidently wrong* diagnosis —
        "harmonized against a different panel" — for a cohort whose missingness is a
        property of the archive; it now takes `min_coverage` and its message says what a
        lowered floor means. (2) The ancient coverage floor was counted over the wrong
        marker set (the 129,840-position AADR∩array overlap instead of the space's 11,128),
        so individuals passed selection and then projected below the floor two steps later,
        surfacing as a panel-mismatch error naming the wrong cause. `ReferencePCA.
        marker_positions` and a refusal in `write_ancient_vcf` make that ordering mistake
        impossible to repeat.
      - **The source is fetched and no longer a question (2026-08-23).** The entry was
        wrong in every particular: it declared v54.1, guessed filenames that do not exist,
        recorded CC-BY-4.0, and called the source manual-only because "Dataverse returns
        202". The 202 is the *DOI redirector*; the Dataverse API answers 200 with full
        metadata. Live record is **v66.p1** (released 2026-06-08), licence **CC0-1.0**,
        and all 25 files are `restricted: false` — no form, no signed letter. Reclassified
        **tier B → A**, since there is no human step left to describe.
      - On disk now: the **Human Origins** set — 584,131 markers over **27,594 samples in
        4,266 populations**, GRCh37 confirmed by inspection (`rs3094315` at chr1:752566),
        4.03 GB, md5-pinned from the digests Dataverse publishes per file, so it cost no
        lock review. The 1240K set (7.1 GB) is the same record if M5.6 ever wants it, but
        HO is the panel that matches what an array carries.
      - **A green `refs probe` had been calling this source healthy** while every declared
        fact about it was stale, because the one URL it had to probe was the homepage.
        That is the hgdp_grch37 lesson pointed the other way, and it is now written into
        the manifest entry.
- [x] **M5.7** Y haplogroup from 1,665 markers and mtDNA haplogroup from 263 markers via
      PhyloTree 17. **Report the supporting marker count and state the resolution
      ceiling on the card** ([AGENTS.md §4.7](../AGENTS.md)).
      - **The licence note in the original entry was the whole difficulty, and `yhaplo` is
        not usable here.** Its §3(b) *No Redistribution or Sharing* says the Licensed
        Materials "may not be used for redistribution purposes"; §3(a)(i) permits sharing
        only "internally"; §2(a) limits use to "internal Non-Commercial Research"; and
        §1(a) defines a Derivative Work to include an "abridgement, condensation", so
        extracting a marker subset does not escape it. A public checkout cannot carry it
        under any reading. **isogg.org itself is unfetchable** — a Cloudflare managed
        challenge, 403 to every client. **Yleaf** is GPL-3.0 (incompatible with this MIT
        tree) and bundles YFull and FTDNA trees besides.
      - **Resolved with `y_tree_isogg_grch37`: the ISOGG table as redistributed under MIT
        by Y-LineageTracker**, pinned to commit `82b14c7`. 74,569 markers over 10,205
        haplogroups **with GRCh37 positions already in a column** — no lifting. The one
        honest caveat, recorded in the manifest rather than buried: the MIT grant is the
        redistributor's over ISOGG's compilation, which is the same standing question
        `yhaplo` raises — but pointed the opposite way, and what is taken is factual.
      - `ancestry/haplogroup.py` holds the tree model and the caller; `phylotree.py` and
        `ytree.py` are the two loaders. **One algorithm, both lineages** — they are haploid
        and non-recombining, so a sample's history is a single root-to-tip path.
      - **Measured ceilings (AGENTS.md §4.7), and they are properties of the array rather
        than of the trees**: mtDNA **141 of 262** MT markers land on a defining site;
        chrY **1,129 of 1,665 (67.8%)**. *Corrected at M5.8's acceptance run (2026-09-24):
        this read 139 and 1,141 (reaching 700 and 629), measured before the parse was
        final; see AGENTS.md §4.7 for the current reachable counts.* PhyloTree
        parses to 5,154 nodes over 4,058 positions in 0.6 s; the Y tree to 9,699 nodes over
        72,893 positions in 0.3 s. Both cached per process rather than given a
        post-process artifact — a few tenths of a second did not justify the machinery.
      - **The defect worth carrying forward: greedy root-to-tip descent is wrong for an
        array, and every synthetic test passed while it was wrong.** The first
        implementation required a derived marker at every branch it crossed — correct for a
        sequenced genome. On a chip most branches are defined by markers that are simply
        absent, so an unbroken supported chain does not exist: it stopped near the root of
        its tree. A branch with no typed
        marker is silence, not evidence against. The caller now takes the best-corroborated
        node and reads the path off the tree. Ranking is **total support along the path,
        depth as tie-break** — depth alone lets one erroneous deep call in an unrelated
        clade beat a call resting on eighty concordant markers.
      - **Validated against 1000 Genomes, which was already on disk**: 1,233 chrY samples,
        restricted to array positions. Every population lands where the literature puts it
        — R1b1 dominant in GBR/CEU/IBS, E1b1 in YRI/LWK, Q1b1 in PEL, and the two
        diagnostic cases a broken caller would miss: **JPT splitting D1a2 (20) / O1b2 (18)**
        and **FIN's N1a1 (23)** separating it from every other European panel.
      - Real export: run through the callers. The calls are not recorded here (AGENTS.md
        §1.1).
- [x] **M5.9** Widen M5.5's modern reference panel with AADR Human Origins' present-day
      individuals. `ancestry/modern_panel.py`; `build_modern_reference_panel` in the AADR
      manifest entry.
      - **The resource was already fetched for M5.6.** Its Human Origins set carries 8,474
        individuals dated to the present beside the ancients. Selection uses a known
        non-positive date, AADR's own QC/outlier labels, measured heterozygosity to exclude
        pseudo-haploid records, and the same 20-member floor the population model uses.
      - **The widened artifact holds 5,553 diploid individuals in 100 populations.** In the
        same 44,872-marker PC space, swapping only the available populations takes refusal
        over its members from **32.1% to 0.2%**, 90th-percentile geographic naming error
        from **3,778 km to 1,212 km**, and names within 1,000 km from 78% to 89%.
      - **Coverage did not replace refusal.** Held-out Nganasan, Kalash, Pima, Mbuti, Biaka
        and Nasioi are still refused at 100%; Papuan at 98%; Mozabite and Karitiana at 96%.
        All 11 Khomani and all 10 Aboriginal Australian samples are refused. The new
        `HUMAN_ORIGINS_COVERAGE` statement records the Maghreb/Nile, Aboriginal Australian,
        Khoisan and below-floor Levantine gaps and attaches only to this exact population
        set.
      - **The transform is reproducible reference-data post-processing, not user-derived
        output.** It transposes the individual-major packed archive into PLINK binary,
        filters and LD-prunes with M5.3's settings, carries population labels in the
        fileset's family column, and records all four input digests plus selection counts,
        admitted groups and companion-file digests in provenance.
      - **One extra PLINK column exposed the integration defect.** An EIGENSTRAT panel has
        no established REF allele, so `--pca allele-wts` emits `PROVISIONAL_REF?` and moves
        A1/PC1 one column right. M5.4 now locates ID, A1 and PC columns by header name and
        verifies that the components begin at PC1 rather than scoring fixed positions.
      - The transpose is tested cell by cell against a separately written BED decoder,
        including missing calls and a partial final sample byte. The full-size real archive
        produced a BED byte-identical to an independent implementation.
      - **The completion review closed two provenance holes.** Both packed-header hashes now
        reach the transpose: the first version passed the SNP hash and omitted the individual
        hash, so a same-shaped wrong `.ind` could silently select records by the wrong row.
        The locality join now verifies every `.psam` sample ID and its group against the
        annotation sheet before computing modal countries; matching group names from a
        different release are no longer enough. Panel-source names and the manifest's group
        floor are also validated rather than coerced into plausible provenance.
- [x] **M5.8** Ancestry output feeds the shared context object — **PRS confidence depends
      on it** ([AGENTS.md §4.4](../AGENTS.md)). This ordering dependency is load-bearing.
      `ancestry/context.py`; wired into `run/pipeline.py`, the bundle, and both CLI commands.
      - **Accepted 2026-09-24 on the machine that holds the export.** All four references
        verify. `genetics run`: population `placed` (100 reference populations, above 99% of
        44,872 markers scored — M5.9's panel and space exactly), haplogroups `called`, ancient
        `computed` over 442 groups. Wall-clock
        **71 s** first run, **65 s** second: the modern-panel PCA was already cached from
        M5.9 and reused by both; the 11,128-marker ancient shared-space PCA was built in the
        first run and reused by the second (sidecar untouched); the ancient projection is the
        uncached remainder. No per-run sample intermediates survived either run.
        `runs show` names the same population as `--json`. **The expected haplogroup
        denominators were stale**: M5.7 recorded 139 / 1,141, but the unchanged loaders give
        141 / 1,129 on this chip — M5.7's figures predate its final parse; AGENTS.md §4.7
        corrected.
      - **Code-complete 2026-09-24, in a cloud session.**
        The real export and the real references are not in the cloud and the export must not
        go there (AGENTS.md §1.3), so what is verified is synthetic: the unit suite, and one
        run through the pinned PLINK 2 binary described below. **Remaining acceptance, on
        the machine that holds the export:**
        1. `genetics refs verify` -- `aadr` (for `modern_panel_ldpruned.pgen`),
           `thousand_genomes_phase3_grch37` (for `pca_markers_ldpruned.pgen`), `phylotree_17`
           and `y_tree_isogg_grch37` should all verify; `genetics refs fetch --only <id>`
           builds whatever does not.
        2. `genetics run --input <export>` -- expect `population` to be `placed` or
           `declined`, never `not_run`, with coverage near the figure M5.5 measured on this
           chip; haplogroups `called` on the marker counts M5.7 reported; and `ancient
           computed`. Note the wall-clock: the first run on a chip builds two reference PCAs
           and projects ~9,700 ancients.
        3. Run it again and note the wall-clock: the two PCAs should be reused (`reused=True`
           in the cache sidecars); the ancient projection is not cached yet (see below).
        4. `genetics runs show <run-id>` -- the ancestry line should name the population M5.9's
           panel places this export in; compare `--json`'s `ancestry` with M5.9's own figures.
        Then tick the box and record the timings in the progress log.
      - **The shared context object is `AncestryContext`, and a refusal is not a missing
        value.** Four parts, each with a status: the population placement (`not_run`,
        `placed`, `declined`), mtDNA and Y (`not_run`, `called`, `not_applicable`) and
        ancient affinity (`not_run`, `computed`). The placement's status is *derived* from
        what the result holds rather than stored beside it, so `placed` without a population
        and `declined` without the decline sentence cannot be constructed, and nothing is
        built empty without a reason. Y is `not_applicable`, not `not_run`, for a sample QC
        inferred female -- a result about the sample, not a missing reference.
      - **Absent is `not_run`; wrong is loud.** A reference not fetched or not built, and a
        PLINK 2 not installed, are what a fresh checkout looks like, and record `not_run`
        with the command that fixes it. A reference present and failing `refs verify`'s own
        check, a tree that cannot be parsed, or a PLINK 2 that is not the pinned build raise
        `AncestryError` and stop the run -- `default_anchors()`'s line. The artifacts are
        verified by `postprocess.run(verify_only=True)` with the lock's digests, the same
        check `refs verify` makes, so the two cannot disagree.
      - **One refusal stays quiet, and it is about the export.** `InsufficientOverlapError`
        (new, a `ReferencePcaError` subclass for the three overlap floors) means the chip
        carries too little of the panel. Every synthetic fixture meets it on a machine with
        references built, so it records `not_run` with the reason instead of failing the run
        over a fact about one file; M15.2's structurally different fixture depends on that.
      - **Ordering is pinned by a test**: the stage runs after ingest and before
        `assemble_pack`, and a refactor that moved it would fail
        `test_ancestry_is_inferred_before_any_card_is_assembled`.
      - **Bundle format 3 adds `ancestry.run.json`**, digested and genotype-scanned like
        `qc.run.json`. Required only at format 3 and later (`required_payload_files`), so
        format 1 and 2 bundles still read and list; their `RunBundle.ancestry` is `None`,
        rendered as "not recorded" -- a different fact from a format 3 bundle recording
        `not_run`. The whole nested shape is pinned in `test_bundle.py`.
      - **`genetics run` prints each part's status, never its answer.** A haplogroup
        restates genotypes at its defining sites and a population is an inference about the
        person; `genetics runs show` names them. Progress lines go to stderr so `--json`
        stays one document.
      - **The sample's own intermediates do not outlive the run**: its harmonized pgen and
        projections go in a per-run directory under `cache_dir()` that is removed on success
        and on failure, and is created only when a part actually computes -- a run with
        nothing fetched, which is every test run, writes nothing to the user's data directory.
        The two reference PCAs are kept, keyed to panel and chip as before. **A run killed
        outright** (closed console, power cut) never reaches `finally`, so each run first
        sweeps `.run-*` directories older than a day -- added in the M5.8 review; a day, not
        "all of them", because a second run may be live beside this one.
      - **The suite is pinned to an empty reference tree** (conftest), because the stage
        reads whatever this checkout has fetched and would otherwise run for real over
        synthetic fixtures on a machine with references built. A test asserts the pin.
      - **Found by running it, not by the tests.** The first real-binary run failed with
        PLINK's "All genotypes in single-sample VCF contain at least one ALT allele". The
        cause was the synthetic archive, not the stage: it listed the sample's own allele
        first at every site, so every call carried the panel's ALT. Real allele order is
        unrelated to any one person, and M5.9 ran this path on the real export. Recorded
        because it is the one refusal a synthetic panel built *from* the sample will always
        meet.
      - **Real-binary smoke run (synthetic data, pinned PLINK 2).** A synthetic AADR archive
        and a synthetic 1000 Genomes release on the male fixture's own coordinates (~10,000
        sites), both reference artifacts built by the real post-process steps, then the stage
        end to end. With a population the sample is a typical member of: **placed**, fit
        1.08 against a threshold of 2.02 over 9,290 markers at 100% coverage, region read
        from the annotation sheet; the ancient group built from the same frequencies ranked
        first at 3.3 against 41.9. With that population removed: **declined**, nearest fit
        22.8 against 1.48, and the decline sentence names both. Both runs saved and read back
        at format 3; no per-run scratch left behind. Mechanics only -- M5.4's lesson is that
        numbers measured on a synthetic array describe the fixture.
      - **Deliberately not done here.** `ancestry_match` stays `None` on every card: turning
        a placement into a number needs a mapping from the 100 AADR populations (whose region
        is a sampling *country*) onto the five study-ancestry codes cards declare, and a
        rule for what a *declined* placement does to it. Both are
        [M9.5](#m9--prs-engine--score-driven-sections)'s; the `{ancestry}` card placeholder
        now points there too, and the `Ancestry` enum's docstring, which still said M5.3
        would add finer labels, says so. The ancient model is recomputed each run (minutes
        on the real archive) rather than cached per chip -- worth doing if the local timing
        says so.

---

## M6 — Genome structure

- [x] **M6.1** ROH via **PLINK 1.9** `--homozyg` (PLINK 2 handles preparation). LD-prune and MAF-filter first; **do not use the
      defaults** — tune window/length parameters for 677k density and document the
      choice. Report total ROH length, count, longest segment, and F_ROH.
      - **Completed 2026-09-25.** `genetics roh --input <export>` calls the shared
        `structure.roh.compute_roh` engine and emits JSON, or saves `.roh.json` outside
        the checkout. [Method and usage](roh.md) document every parameter and the
        assayed-autosomal-span denominator; this is observed long-ROH F_ROH, not a whole-genome
        coefficient. Missing/insufficient calls are explicit, never silently a zero score.
      - **Toolchain correction:** the pinned PLINK 2 build has no `--homozyg`.
        Official PLINK 1.9 v1.9.0-rc3 (23 Sep 2026) archives were downloaded and hashed
        for Windows, Linux and Intel macOS; the Windows binary was installed and verified.
        The shared subprocess wrapper preserves version checking and error redaction.
      - **Reference filtering precedes sample conversion.** Unpruned GRCh37 cohorts,
        at least 50 reference members, MAF 0.05, missingness 0.02, LD 500 kb / step 1 /
        r-squared 0.2. Defaults use the fetched pooled 1000G panel, explicitly labelled;
        `--keep` allows a named ancestry-matched cohort. No MAF or LD is estimated from
        the subject. PCA subsets are not reused. All reference hashes and settings persist.
      - **Validation:** fixed-seed synthetic panels with planted long runs, correlated
        markers, rare sites, gaps, missing calls and random controls. Real pinned binaries
        verify reference filtering, detection, gap splitting, no-call handling, call-independent
        marker selection, CLI serialization, and scratch cleanup after late failures.
        CI installs both pinned tools to run these checks on Windows and Linux.
        Full local suite: **1,740 passed, 5 platform skips**; ruff, format and strict
        mypy clean. Synthetic fixture reproduction and card-schema lint also pass.
      - **Diff-driven review (2026-09-25):** schema 2 checks potential scanning-window
        support within denominator blocks, including density and local missingness. Scattered
        calls or well-called islands outside those blocks no longer establish a numeric zero.
        Unsupported blocks remain visible beside valid findings with an underestimation warning.
        Empty/sub-window reference intersections and wholly unresolvable calls are explicit
        reference statuses; malformed sources still fail. Hashes are keyed by input role to
        prevent same-filename collisions. Invalid exports use normal CLI errors; JSON fractions
        reject booleans and accept zero reference missingness. Result publication is atomic and
        never overwrites another writer. Synthetic missing-call fixtures use the actual enum.
        Review suite: **1,759 passed, 5 platform skips**; the final numeric-range hardening
        also passes the focused **44-test ROH suite**, ruff, format and strict mypy.
      - **Remaining limits are explicit:** no short-run sensitivity claim or empirical
        chip/population calibration yet; interpretation belongs to M6.2. Scratch is cleaned
        on completion/errors, but interrupted reference processing is not resumable in this
        first engine. No personal results or reference payloads are committed.
- [x] **M6.2** Autozygosity interpretation card. Sensitive and occasionally surprising —
      include it, compute it properly, state it plainly
      ([AGENTS.md §0.1B](../AGENTS.md)). No euphemism, no advice.
      - **Completed 2026-10-04.** `long_roh_autozygosity` is a cited, declarative
        `computed` card in `knowledge/structure/`. `genetics run` calls the shared M6.1
        engine once when the pack requests it and the full 22-autosome reference and
        pinned tools are present. Missing dependencies render `not_run` with a fix-it
        command; wrong versions and malformed references fail. No PCA subset is reused.
      - Bundle **format 4** adds the per-card `computation` record: measurements,
        intervals, local observability, reference hashes, parameters, tool versions,
        method evidence and computed reliability inputs. Formats 1–3 still read. CLI
        `runs show --json` and dashboard card detail expose the same saved record.
      - **Interpretation is limited by the uncalibrated assay.** The face states count,
        total length, observed F_ROH and its assayed denominator, with missing-call,
        partial-coverage and unsupported-span limitations. The detail states what
        autozygosity means and why this result cannot identify a particular parental
        relationship, percentile or individual disease risk. McQuillan (2008; n=2,618)
        and Pemberton (2012; n=1,839) support the method explanation, not numeric
        calibration of this caller. Supported zero and unavailable results are distinct.
      - Validation covers schema refusal, all result states, native planted runs,
        dependency handling, immutable bundle round-trip, CLI/HTTP agreement,
        corruption refusal and genotype-safe repr. **1,790 passed, 5 platform skips**;
        ruff, format, strict mypy, fixture reproduction and full card lint pass
        (44 cards, 212 template renders, 31/31 dbSNP keys resolved).
        [Method and usage](roh.md).
- [x] **M6.3** Archaic introgression (Neanderthal/Denisovan) against public Vindija/Altai
      references. Array-based estimates are coarser than sequence-based — say so, and
      give a range rather than a false-precision percentage.
      - Implemented 2026-10-04: local f4 estimators against the existing, checksum-pinned
        AADR high-coverage Altai/Vindija/Denisova references, Mbuti/Han and chimp. Weighted
        block-jackknife intervals, transition sensitivity and a Denisovan-ancestral primary
        Neanderthal filter; signed ranges and coverage/denominator failures remain visible.
        Model assumptions and uncalibrated array bias are on the card face. These are
        allele-sharing model ranges, not measured genome-wide DNA percentages or tracts.
      - Both cards reach `genetics run`, immutable bundle format 5, CLI JSON and dashboard
        details; formats 1-4 remain readable. Synthetic maths, harmonization, missing
        dependencies, corruption refusal, CLI/HTTP agreement and privacy-safe repr are
        covered. Pinned AADR loader and default estimator checks used public references
        only. Full regression and final targeted guard checks pass (five existing Windows
        skips); ruff, format, strict mypy, fixture reproduction and full card lint pass
        (46 cards, 216 template renders, 31/31 dbSNP keys resolved).
        [Method and usage](archaic.md).
- [x] **M6.4** Sex chromosome findings + karyotype-adjacent caveats. Be careful and
      literal; this is an inference from het rates, not a karyotype.
      - Added the computed `sex_chromosome_call_pattern` card, showing direct-call
        non-PAR X heterozygosity and Y call rate with counts and denominators on its
        face. Disagreement, sparse inputs and missing Y probes stay visible. Reliability
        is limited; chromosome count, aneuploidy and mosaicism are not inferred.
      - QC and structure reporting share verified, inclusive GRCh37 GRC PAR boundaries.
        Coordinate-defined PAR on X/Y is excluded from both signals and remains diploid,
        including in layouts that do not label PAR separately. No-call/indel policies and
        duplicate-probe caveats are explicit. No new tools or reference downloads.
      - CLI and dashboard read the same bundle-format-6 measurements, method evidence,
        thresholds and caveats; older bundles remain readable without reinterpretation.
        Synthetic checks cover threshold edges, discordance, missing/sparse signals,
        PAR endpoints, ploidy, duplicates, indels, corrupted payloads and saved UI/CLI
        agreement. Acceptance: 1,857 tests passed with five existing Windows skips;
        ruff, format, strict mypy (142 files), fixture reproduction and full card lint
        passed (47 cards, 218 template renders, 31/31 dbSNP keys resolved).
        [Method and usage](sex_chromosomes.md).

---

## M7 — Monogenic health & frequency gating

- [x] **M7.1** ClinVar lookup against the normalized table, position-keyed.
      - Full reference-only SQLite index of the pinned GRCh37 VCF; source and index
        checksums, build/date validation and atomic publication. No htslib dependency.
      - Locus join plus compatible REF/ALT alleles; rsID is secondary metadata. Missing,
        incompatible, excluded indel/symbolic, duplicate-probe and duplicate-record
        ambiguity states remain explicit. Multiallelic aggregate annotations are retained
        without assigning them to an alternate. All classifications, conflicts, review
        statuses, conditions and source identifiers are preserved.
      - Bundle format 7 adds private `clinvar.run.json`; formats 1–6 remain readable.
        `genetics runs clinvar <run-id> --json`, whole-run JSON and the dashboard read the
        same snapshot. This is lookup only; M7.2–M7.3 own calibrated finding presentation.
- [x] **M7.2** **Frequency gate wired to gnomAD** — the single most important correctness
      requirement in the project ([AGENTS.md §4.1](../AGENTS.md)). Rarity lowers confidence.
      - Complete public-reference SQLite index of r2.1.1 GRCh37 exomes, accepted on
        **17,209,972 records**. Publisher MD5 and source/index SHA256 verification pass.
        Header/cardinality/count checks, source-bound resumable checkpoints and atomic
        publication work on Windows without htslib. Sample loci remain in memory.
      - Exact biallelic PASS records supply AC/AN frequencies through the shared
        confidence engine and a separate ClinVar measurement-reliability screen.
        Selection uses the conservative maximum across global, eight major ancestry
        groups and nine reported subgroups, disclosing the selected population rather
        than inferring personal ancestry. Missing, filtered, incompatible and ambiguous
        entries remain unknown; split loci leave REF frequency unknown.
      - Measured rare alleles still trigger `likely-artifact` when a companion frequency
        is missing or imputation quality is high. Findings remain visible. The generic
        16% benchmark is attached; M7.3 still owns the complete PPV presentation and the
        separate BRCA1/BRCA2 benchmark.
      - Format 8 saves ClinVar schema-2 calibration/counts/provenance; formats 1–7
        retain their saved results. Synthetic-only full-reference acceptance passed
        with networking blocked, including reloading, CLI JSON and dashboard parity.
- [x] **M7.3** `likely-artifact` rendering: the card **states the empirical PPV for its
      frequency band** (~16% below 0.001%; ~4% for BRCA1/2). "Low confidence" is too weak
      — give the number.
      - Published confirmed/unconfirmed rates appear on card faces, in details and
        CLI summaries, with a sequencing limitation and a citation. No personal
        posterior probability is inferred, and no PPV is invented for missing
        frequency or imputation-quality-only failures.
      - Exact BRCA1/BRCA2 symbol/gene-ID pairs and solely pathogenic/likely-pathogenic
        germline annotations select 4.2%; its pooled-study scope is explicit rather
        than being mislabelled a frequency-bin estimate. Other rare observations
        retain the 16% benchmark. Conflicts, uncertainty, unrelated genes, somatic and
        included-haplotype annotations do not receive the BRCA calibration.
      - Format 9 records lookup schema 3, including benchmark scope/cohort/DOI.
        Formats 1–8 preserve their saved results, including schema-2 BRCA snapshots
        with the original generic benchmark. `{frequency}` and `{ppv}` templates
        now render explicit values or unavailable states through production assembly.
- [x] **M7.4** ACMG secondary-finding genes: surfaced, tiered, and accompanied by an
      explicit "only clinical sequencing can establish or exclude this; this is not a
      clinical test". Not suppressed, not presented as established.
      - Complete 84-gene ClinGen SF v3.3 roster and guidance fetched under CC0,
        hash-pinned and verified. Exact symbol matches retain HGNC/NCBI identifiers.
      - Shared saved-data dashboard and `runs secondary` views show all overlaps,
        including likely artifacts, unknown reliability, uncertain/conflicting
        annotations and unresolved calls. Existing measurement calibration is unchanged.
      - Gene membership/P/LP does not establish clinical reportability; disease,
        inheritance, phase and variant restrictions remain explicitly unadjudicated.
        Missing sources and no-overlap results cannot imply a negative clinical screen.
      - Format 10/schema 4 save the complete roster, guidance and overlap provenance;
        validation uses saved metadata only. Formats 1–9 remain unchanged.
- [x] **M7.5** Well-established common-variant health cards (APOE, HFE, F5 Leiden, etc.)
      with proper absolute-risk framing, not relative risk alone.
      - Three declarative cards under `knowledge/health/`, with primary citations, cohort
        populations/sample sizes, genotype-specific claims and literal outcome `risk_context`
        on the face, detail view and CLI. Published absolute rates retain their endpoint,
        strata and horizon; unprovided baselines and inapplicable rates are explicit. No
        conversion of relative effects or measurement PPV into a person's disease risk.
      - Schema 2 supports small unphased SNP diplotypes and preserves schema-1 single-marker
        packs. APOE declares all four haplotypes and all ten pairs; the double heterozygote
        remains `phase_ambiguous` with both candidates. Missing, conflicting and non-diploid
        observations stay visible. Confidence inherits the weakest marker's locus-specific
        calibration, including rare/unknown-frequency and imputation-quality gates.
      - Full dbSNP lint verifies all four health loci, including GRCh37's F5 reference-state
        inversion: T is the Leiden allele, C is non-Leiden. Bundle format 11 saves risk
        context and multi-marker evidence; formats 1–10 and ClinVar schemas 1–4 keep their
        original meanings. See [common health cards](common_health.md).
      - HFE and F5 declare `strand: forward_only`: both sites have additional dbSNP
        alleles, so complementing an unexpected base could manufacture the target health
        allele. Unexpected calls remain visible mismatches, with synthetic regressions.
      - Follow-up review: knowledge schema 3 selects complete outcome-specific evidence
        or null before scoring/saving; comparator and unestimated outcomes cannot borrow
        a disease effect. Format 12 / multi-marker schema 2 bind saved confidence to the
        recorded observation, allele frequency and phenotype evidence. Formats 1–11 remain
        immutable. Marker details expose quality/calibration, and lint reports 35/35.
- [x] **M7.6** Coverage honesty card: how many ClinVar positions the array covers
      (~76k), and what that does and does not mean.
      - Measure unique normalized GRCh37 positions from the chip and full pinned reference;
        do not reuse ~76k as a constant. Disclose both overlap/reference and overlap/chip
        denominators, distinct allele counts, probe duplicates and reference filters.
      - Separate present, called and allele-resolved overlap. Preserve no-call, indel,
        strand/ploidy and conflict states; coverage does not establish clinical sensitivity
        or confirmed pathogenic findings. Missing/empty sources and zero overlap differ.
      - Save counts, definitions and provenance once in the shared pipeline; validate
        snapshot relationships without recounting newer references. Cover synthetic edge
        cases and CLI/dashboard parity. See [the handoff](handoff_history.md#accepted-m76-scope-retained-for-review).
      - **Completed 2026-10-07.** `health/coverage.py` measures the entire installed
        reference with a read-only index and memory-only sample positions. The
        declarative Physical-health card and ClinVar view share the format-13,
        schema-5 snapshot, validated without consulting current caches. Full-reference
        acceptance uses synthetic input only; see [the guide](clinvar_coverage.md).

---

## M8 — Imputation

*[AGENTS.md §0.1C](../AGENTS.md): compute cost is not a constraint. Imputation is
default-on.*

- [x] **M8.1** Beagle wrapper: Java detection, memory configuration, progress reporting,
      **resumability** (long runs must survive interruption).
      - **Completed 2026-10-07.** `external/beagle.py` verifies the manifest jar SHA256
        and Java 8+, records heap/threads/seed/mode, requires a genetic map, and runs
        without a shell or an implicit timeout. Raw output remains private; callbacks
        expose fixed stages, window numbers and heartbeats. Atomic completion binds
        full input/tool/runtime hashes and validated output. Kernel locks release on
        process death. Interrupted jobs restart; completed chromosome jobs are verified
        and reused, never partial VCFs or spliced Beagle windows. Doctor shares the pin;
        workspaces/locks are ignored, including beneath the knowledge allowlist.
        **2,226 passed, five existing Windows skips**, native ROH and Beagle enabled;
        strict type matrix, ruff/format, fixtures and full card lint pass. Native
        acceptance uses one generated target with twenty synthetic reference samples,
        confirms phasing, newly imputed marker DR2/dosages, phase-only behavior and
        verified reuse. CI enables native Beagle on both OSes. See [the guide](beagle.md).
- [x] **M8.2** Reference panel prep → bref3, per chromosome. Full panel, not subset.
      - **Completed 2026-10-07.** Independently pinned converter/decoder `27Feb25.75f`,
        Java 11+ readiness and an 8,192 MiB heap. Full phased 1000 Genomes autosomes/X,
        no array intersection, LD/MAF filtering or sample removal. Every ordered marker,
        allele and GT is compared through full decoding before atomic chromosome
        publication. Source/tool/runtime hashes, kernel locks and verified checkpoints
        support restart and completed-job reuse; catalogs validate all companions and
        bind the current manifest/lock. `refs verify` is read-only.
        Local full-release acceptance: **23 chromosomes, 84,739,838 records, 2,504 samples
        each**, preserving sample order; **8,312,115,275 bref3 bytes**. X haploid calls are
        explicitly doubled for storage and counted, with PAR bounds recorded. M8.3 must
        respect biological ploidy and partition X jobs. Y lacks a complete nonmissing
        reference/map and MT is absent; both limitations are explicit, with direct-call
        engines retained. All **25 GRCh37 HapMap maps / 3,395,051 rows** are fetched,
        preserved, source-pinned and numerically verified. No constant-rate fallback.
        **2,277 passed, five existing Windows skips**, native tools enabled; 51 new
        synthetic cases include conversion, exact round trips, cancellation, locking,
        partial recovery, corruption/metadata forgery, source/tool contracts and native
        Beagle consumption. Strict type matrix, ruff/format, fixtures and full card lint
        pass. No personal export. See [reference preparation](imputation_reference.md).
- [x] **M8.3** Phasing then imputation pipeline; write dosages plus per-variant quality
      (r²/DR²).
      - **Completed 2026-10-07.** Shared `imputation.impute` and `genetics impute` decode
        complete source-bound bref3 markers, harmonize targets, then phase and impute
        against the full panel with matching maps. Exact eligible typed-call retention,
        sample/region/allele identity and finite per-ALT DS/DR2 are required. X PAR and
        non-PAR jobs use QC ploidy and native haploid targets/dosage/DR2; wrong-copy-count
        output is refused. Printed dosage sums permit the pinned writer's rounding.
        Direct, phase-filled no-call and
        untyped-imputed sources stay separate; phase-filled quality remains unknown and
        low DR2 is preserved. Atomic private outputs, kernel locks and regenerated
        observation checks support verified reuse; no partial-window splicing.
        **2,369 passed, five existing Windows skips**; 77 new cases, including native
        male/female synthetic targets with 800 records each over autosomal/PAR/non-PAR
        jobs, unchanged full panels and completed reuse. Four-way typing, lint/format,
        fixtures and full card lint pass. All installed panels/maps validate read-only.
        No personal export. Application default-on orchestration/escape hatch remain M8.4;
        quality propagation and bundle provenance remain M8.5/M8.6. Format 13 unchanged.
        See [the stage guide](imputation_pipeline.md).
- [x] **M8.4** `--no-impute` escape hatch for dev/testing. Never the default, never
      silent — the run bundle and every affected card record which mode was used.
      - **Completed 2026-10-07.** Default-on shared stage after ancestry, with explicit
        opt-out and failure reporting, never silent fallback. Format 14 records requested
        mode/execution outcome and per-card mode, validated for counts/status/ploidy and
        card/run agreement. Historical formats 1–13 retain unknown mode. CLI/dashboard
        banner, face and detail read the same snapshot. Original-array card/ClinVar/
        structure observations stay separate pending M8.5; full provenance remains M8.6.
        **2,417 passed, five existing Windows skips**; 48 new synthetic cases include
        default native CLI execution, 800-record save and completed-job reuse. Native
        acceptance fixed Windows long-working-directory launches without changing paths
        or contracts. Four-way types, lint/format, fixture reproduction and full card
        lint pass. No personal export. [Guide](imputation_mode.md).
- [x] **M8.5** Carry imputation quality through to scoring so poorly imputed variants
      degrade confidence rather than silently entering sums.
      - **Completed 2026-10-07.** Shared card-locus bridge preserves original direct
        probes and supplies exact biallelic imputed SNVs for absent/no-call loci.
        Reference allele contracts establish imputed forward orientation; original
        strand/ploidy/conflict rules remain intact. Per-ALT dosage/DR2, native ploidy,
        source and model scope remain attached to scalar and multi-marker evidence.
        Low DR2 uses existing ceilings; phase-filled unknown quality contributes zero
        and caps confidence at limited. No quality filtering or dosage attenuation.
        Format 15 / execution schema 2 saves and validates quality-aware card inputs;
        formats 1–14 preserve their original snapshots. CLI/dashboard agree without
        caches. Effect-allele dose/quality contract supports M9; multiallelic REF quality
        stays unknown without covariance. Synthetic boundaries and native acceptance,
        strict four-way typing, lint/format, fixture reproduction and full card lint
        verify the integration. No personal export. Next M8.6 full provenance and
        M8.7 dedicated rare-call gates. [Guide](imputation_quality.md).
- [x] **M8.6** Record panel version, tool version and parameters in the run bundle.
      - **Completed 2026-10-07.** Format 16 / full provenance schema 1 durably copies
        complete native dosages and byte-identical panel/map catalogs, binding exact
        used releases, artifact/tool/runtime hashes and phase/imputation parameters
        to the saved stage. Card/full-dosage agreement, native ploidy/per-ALT quality,
        typed retention, source/count/region arithmetic and phase handoff are validated
        without current caches or manifests. Atomic independent copies reject changed
        inputs and failed publication; progress is genotype-free. Historical formats
        1–15 retain their meanings. Shared saved iterator, CLI imputation/provenance/
        dosage access and dashboard status use the same snapshot. Opt-out, zero jobs
        and unrecorded low-level writers remain explicit. Synthetic corruption/privacy/
        historical checks and native 800-record saved acceptance cover the contract.
        **2,524 passed, five existing Windows skips**; 53 added cases, strict four-way
        types, lint/format, fixtures and full card lint pass. No personal export.
        Next M8.7. [Guide](imputation_provenance.md).
- [x] **M8.7** Assert the rare-variant frequency gate still applies to imputed calls —
      imputation does **not** rescue rare-variant reliability.
      Acceptance covers strict frequency boundaries, both imputed sources/native ploidies,
      missing observed-allele companions, weakest-marker inheritance and saved CLI/dashboard
      parity. Keep chip PPVs explicitly uncalibrated for imputation and ClinVar on its
      original-array basis. See [the implementation handoff](handoff_history.md#m87-implementation-handoff)
      and [the completed M8.6 diff review](review_m86_session.md).
      - **Completed 2026-10-08.** Thirty-two synthetic cases verify nextafter/equal/above
        boundaries with strong replicated evidence and DR2 1, both imputed sources and
        native ploidies, unknown phase-filled quality, incomplete observed-allele
        frequencies, unobserved-rare controls and weakest-marker inheritance. Full
        format-16 save/reopen and CLI/dashboard parity retain the tier, frequency,
        native evidence and scoped benchmark after synthetic cache/index removal.
        Enabled direct probes and explicit opt-out retain original-array observations;
        ClinVar never receives imputed calls. Isolated guard mutations fail four rarity
        cases and both missing-companion cases. No engine or persisted meaning change.
        **2,561 passed, five existing Windows skips**, native tools enabled; strict
        four-way types, lint/format, fixtures and full card lint pass. No personal export.
        M8 complete; next M9.1. [Guide](imputation_quality.md#rare-call-frequency-gate-m87).

**M8 overview reviewed 2026-10-08.** Seven groups of defects fixed, with 30 added
synthetic cases (28 reproduced rejection cases and two valid skipped-region controls).
Saved scalar rarity/frequency/hard-call binding, missing alleles, skipped-region ploidy,
phase handoff sizes and categorical option/gzip/iterator failures are checked without
changing format 16/schema 1 or historical meanings. **2,591 passed, five existing
Windows skips**, native tools enabled; strict four-way types, lint/format, fixtures and
full card lint pass. No personal export. [Review](review_m8_overview.md) and
[M9.1 handoff](handoff_history.md#m91-accepted-implementation-scope).

---

## M9 — PRS engine & score-driven sections

- [x] **M9.1** PGS Catalog scoring-file parser, with authoritative **per-score licences
      from the metadata CSV's `License/Terms of Use` column**, not assumed from headers
      ([AGENTS.md §4.8](../AGENTS.md)).
       Refuse or flag non-permissive scores.
      - Streaming format-2 parser retains raw columns, allele/weight definitions,
        original/harmonized builds, special-model features and source fingerprints.
        Header/row/count/finite-value and metadata identity/build checks fail loudly.
        Metadata archive processing is implemented in the fetch/verify registry with
        source-bound atomic JSON/provenance and no archive extraction. Missing, unknown
        and duplicate terms never default to permissive; restricted terms remain flagged.
        `genetics pgs inspect --json` validates the full public score offline. Live
        reference acceptance parses 77 PGS000001 GRCh37 rows and 6,991 metadata scores.
        Personal scoring, coverage and calibration remain M9.2–M9.5; format 16 unchanged.
        [Guide](pgs_ingestion.md).
- [x] **M9.2** Scoring via PLINK 2 `--score`, pre- and post-imputation.
      - Shared numeric effect-dose matrix preserves biological copy count, per-ALT DR2,
        unknown phase/multiallelic REF quality and original-call precedence. Raw indels,
        strand/duplicate/ploidy conflicts and unsupported models remain explicit; exact
        sequence-resolved imputed indels can contribute. Native target/term/count checks
        and independent arithmetic bound the reported sum's PGEN/text precision.
        `genetics pgs score` reuses ancestry-first/default-on imputation or saved format-16
        full dosages; saved-only original sums stay unavailable. Immutable private score
        JSON records all used source/tool/input/provenance identities, with privacy ignores.
        No card, distribution, portability adjustment or bundle-format bump is introduced.
        [Guide](pgs_scoring.md).
- [x] **M9.3** **Per-score variant coverage reported on every card**, before and after
      imputation ([AGENTS.md §4.3](../AGENTS.md)).
      - Shared versioned coverage in every schema-2 score result, for the M9.6 renderer:
        authored-row, allele-defined variant and position denominators, undefined rows with
        raw definitions, independent before/after states, original-probe duplicates and
        described (never applied) quality. Unavailable is null, not 0%. `genetics pgs
        coverage` recomputes and refuses mismatches; schema-1 results are recomputed with
        missing proof left unknown. Placing it on the card face is M9.6's.
        [Guide](pgs_coverage.md).
- [x] **M9.4** Reference distribution + percentile placement, computed within the
      ancestry-matched reference group where possible.
      - 1000 Genomes phase 3 scored over the person's comparable rows through the same
        matrix and PLINK invocation; group from a 1000 Genomes placement with M5.5's decline
        rule (super-population primary; declined/saved-only pooled and labelled unmatched).
        Mid-rank percentile, Wilson interval, quantiles and histogram per group; lock-verified,
        cached public extraction; `genetics pgs placement` recomputes and refuses tampering.
        Independent PLINK cross-check on the real panel agrees within 8.4e-6.
        [Guide](pgs_reference.md).
- [x] **M9.5** Ancestry-portability adjustment to confidence
      ([AGENTS.md §4.4](../AGENTS.md)).
      - Every schema-4 score result carries a versioned `portability` block and the numeric
        `ancestry_match` the calculator accepts. Sample side: the placed 1000 Genomes
        *population* -> Morales et al. 2018 Table 1 category (doi:10.1186/s13059-018-1396-2;
        KHV is South East Asian, ACB/ASW African American) -> PGS Catalog display category
        (catalog's own table). Study side: all three catalog distributions parsed with
        every share kept; GWAS source drives, development only when GWAS is empty. The
        number is the demonstrated matched share; Not Reported, multi-ancestry and
        unreported stages are indeterminate and only raise the upper bound. AADR or 1000
        Genomes `declined` -> 0 (unrepresented); not run/saved-only -> `None`. The ceiling
        is the calculator's own `ancestry_ceiling`. Nothing is filtered; `genetics pgs
        portability` recomputes and refuses tampering; schema 1-3 results are recomputed and
        labelled. [Guide](pgs_portability.md).
      - **Owned the mapping M5.8 left open** (resolved as above; the AADR placement is a
        decline gate, not a mapped category). Original entry text: `AncestryContext.population` names one of M5.9's
        100 AADR populations, with a sampling country as its region; cards declare study
        ancestry as five continental codes. Something has to map one onto the other before
        `ancestry_match` can be a number, and it must not be written from memory
        ([AGENTS.md §6](../AGENTS.md)). It also has to decide what `declined` does -- a finding
        that the sample is unrepresented, which should lower portability, not leave it at
        the neutral `None` the calculator uses for "not computed". The `{ancestry}` card
        placeholder is locked until this lands.
- [x] **M9.6** PRS card renderer: distribution-dominant visual, **no point estimates about
      the person**, absolute outcome rates by decile where available, within-family
      attenuation stated on the card face where known.
      - Knowledge schema 4 adds `kind: polygenic` (`pgs: {id, source}`, trait, plain
        summary/detail, evidence, optional cited `decile_outcomes`). `genetics run` scores
        every polygenic card through the M9.2-M9.5 engine (public work before ingest, one
        1000 Genomes placement per run); bundle format 17 saves each private record in
        `pgs.run.json` and re-derives display, reliability and face on read. The display
        carries the reference histogram and the person's interval only -- no sum, no point
        percentile. The face states reference group, interval basis, coverage, portability,
        within-family attenuation and decile rates with the base rate (or that a position is
        not a risk). Dashboard: histogram with a washed interval band, validated colour pair,
        decile and input tables. Confidence reuses the calculator's weights and thresholds
        (coverage in the frequency slot). [Guide](pgs_cards.md).
      - Single-marker ancestry match and the `{ancestry}` placeholder moved to M9.13.
      - [Session review](review_m96_session.md): a score missing from metadata no longer
        aborts a run; damaged polygenic records are `BundleError`; within-family estimates
        above 1 are worded correctly. [Handoff](handoff.md) holds M9.7's contract.
- [x] **M9.7** Section: **Physical health** PRS cards.
      - PRS3820 breast cancer and GPS_Mult coronary artery disease cards authored;
        permissive score licences checked, GRCh37 weights fetched/pinned/locked.
      - Streaming coordinate-group extraction and catalogue assembly aliases address
        real-file scale/compatibility findings. No bundle-format change.
      - Full card lint and synthetic shared-engine/bundle/CLI/dashboard checks pass.
        Full-panel scale, default-on native imputation across 22 autosomes, both
        public scoring stand-ins and retained-score reload validation pass.
        Pre-review M9.7 suite: 2,872 passed, five existing Windows skips; all four
        strict type targets, lint/format and fixtures pass. Owner screenshot
        review corrected compact labels; the guide records the post-fix browser
        gap. [Session review](review_m97_m98_session.md).
        [Guide](physical_health_prs.md).
- [x] **M9.8** Section: **Mental health**. Record reduced-N (excluding-23andMe) releases
      on the card ([AGENTS.md §5.3](../AGENTS.md)).
      - Public SCZ_GHS and UK Biobank-only GPpsy models authored and fetched;
        source versions, discovery N, study populations and calibration limits
        are explicit. No restricted 23andMe summary statistics are downloaded.
      - Synthetic shared-engine/bundle/CLI/dashboard parity and full-panel scoring
        on both default-imputed and explicit no-impute public stand-ins pass.
        Pre-review suite: 2,873 passed, five existing Windows skips; lint: 55 cards,
        276 renders, 35/35 marker keys. The session review also tightens frozen
        duplicate-proof allocation, with failing-before-fix and valid-group tests.
        Final reviewed suite: 2,875 passed, five existing Windows skips; all four
        strict type targets, full card lint, fixtures and staged privacy checks pass.
        [Model audit and acceptance](mental_health_prs.md).
- [x] **M9.9** Section: **Psychometrics**. Most constrained on both corpus and science —
      both constraints stated on the cards ([AGENTS.md §4.5](../AGENTS.md)). Ships in full,
      unflattering results included.
      Authored and pinned: cognitive test performance, qualifications-to-years and
      neuroticism. Accepted on 2026-10-12: all full reference preparations, three
      default-imputed and three explicit no-impute public-stand-in checks, and six
      retained JSON disk-read validations pass. Schema 4 and bundle format 17 are
      unchanged. 2,877 unique implementation checks pass, with five Windows skips;
      all four strict type targets and full card lint (58/282/35 keys) pass.
      [Model audit and scale acceptance](psychometrics_prs.md).
      [Diff review](review_m99_session.md): shipped evidence and pins confirmed;
      model-binding mutation rejected by both ancestry cases, all 51 card tests
      and all six saved score/card revalidations pass. No engine/schema change.
- [x] **M9.10** Section: **Substance use & behavioural propensity**. GSCAN public
      excluding-23andMe stats are well powered (smoking initiation N=805,431;
      drinks/week N=666,978). These are context, not selected-score sample sizes.
      Follow the [entry and acceptance contract](handoff_history.md#next-open-step-m910-substance-use-and-behavioural-propensity).
      Three UK Biobank-only models are authored and fetched: ever smoking,
      alcohol frequency (higher means less frequent), and self-reported substance
      or behavioural addiction excluding cigarettes/coffee. Exact-model N and
      partial-r evidence are audited; GSCAN's public-release performance binding
      could not be established, so its full-study metrics are not substituted.
      Accepted 2026-10-13: all full references, three default-imputed and three
      explicit no-impute checks, and six written score/card reload validations
      pass. All 2,881 unique checks pass, five existing Windows skips; all four
      strict type targets, lint/format, fixtures, privacy gates, 55 card tests and
      full card lint (61/288/35 keys) pass. Schema 4 / bundle format 17 unchanged.
      [Model audit](substance_use_prs.md).
- [x] **M9.11** Section: **Sleep & circadian**.
      Three public UK Biobank-only LDpred2 models are authored, licence-checked,
      fetched and pinned: evening preference, log-transformed daily sleep
      including naps, and ordinal sleeplessness. Exact phenotype coding,
      direction, effective training/evaluation N and residual variance
      associations are audited. Four synthetic interface checks, full card
      lint (64/294/35 keys), all four strict type targets, lint/format and
      fixture reproduction pass. Full-model acceptance is complete in a
      separate private checkpoint, reusing all 22 verified dosage files:
      all three full references, six scoring checks and six written-record
      reload validations pass. All 2,885 unique checks pass, five existing
      Windows skips; staged privacy scanning passes.
      Schema 4 / bundle format 17 and the renderer are unchanged.
      [Model audit and acceptance](sleep_circadian_prs.md).
- [x] **M9.12** Section: **Fitness & physiology** (ACTN3, ACE, injury, trainability).
      Weak evidence — include and flag honestly.
      Five declarative cards are authored: ACTN3 resistance training, ACE
      serum concentration, COL5A1 chronic Achilles tendinopathy, ACSL1 aerobic
      response and complete PGS002143 mean grip strength. Exact endpoints,
      model evidence, population and replication limits are audited; source
      terms are permissive and the fetched full model is checksum-pinned.
      All 97 focused card checks, four strict type targets, full dbSNP lint
      (69/320/39 keys), style, fixtures and staged privacy scan pass.
      All 2,923 unique checks pass, five existing Windows skips; Java-dependent
      checks passed with portable Java 17 after the initial run used Java 8.
      Full-model acceptance passed in the separate private M9.12 checkpoint:
      complete reference preparation, both scoring modes and both written-record
      disk-read validations. Every source term is retained; completed imputation
      and all verified inputs were reused. Schema 3/4, bundle format 17 and
      renderer unchanged. [Evidence audit and measured acceptance](fitness_physiology.md).
      The [diff review](review_m912_session.md) adds five mutation regressions
      binding published variant directions and effect units; all 102 focused
      card tests pass and both retained native evidence bindings agree.
- [x] **M9.13** Card-level ancestry match and the `{ancestry}` placeholder.
      Complete on 2026-10-14: one run-owned 1000 Genomes placement, shared before
      imputation with variant/PRS evaluation; AADR decline gates without country
      mapping. Selected-outcome study codes produce matched/mismatched, declined,
      not-run, UNKNOWN, unspecified MULTI and null-evidence states. Variant
      confidence uses the existing weighted component and unknown cap, without
      PRS transfer ceilings; rarity, quality and evidence limits remain intact.
      Format 18 saves the comparison/run context, validates scalar/multi-marker
      confidence and shared PRS placement, and preserves formats 1–17.
      All 2,995 unique checks pass with five existing Windows skips; 67 new
      synthetic cases. Strict four-way types, lint/format, fixtures, staged privacy
      and full dbSNP lint (69/320/39 keys) pass.
      [Evidence decisions, contract and exact acceptance](card_ancestry.md).
      The [M9.13 diff review](review_m913_session.md) fixes retained-fit,
      allele/type validation and card-detail refusal messages. All 3,015 tests
      pass, five existing Windows skips; 20 new cases, strict four-way types,
      full card lint, fixtures and lint/format pass. The
      [M10.1 entry contract](handoff_history.md#next-open-step-m101-pharmacogenomics-ingestion)
      covers existing PGx sources, pending extraction and actual definition coverage.

---

## M10 — Pharmacogenomics

*Highest actionable value; corpus entirely free. See [AGENTS.md §3.1](../AGENTS.md).*

- [x] **M10.1** PharmGKB + CPIC ingestion → star-allele definitions and phenotype mapping.
      Complete source tables, independent SQL encoding checks, source-bound GRCh37
      normalization and offline `pgx prepare`/`pgx inspect` are implemented. Missing,
      conflicting and structural definitions remain explicit. See the
      [source audit and acceptance](pgx_ingestion.md).
- [x] **M10.2** Diplotype calling for **SNP-tractable genes only**: CYP2C19, CYP2C9,
      VKORC1, SLCO1B1, TPMT, DPYD, NUDT15, G6PD.
      Shared conservative calling, versioned private snapshots, offline saved-call
      CLI/dashboard inspection and synthetic full-source acceptance are implemented.
      Missing/partial/structural alternatives and measurement uncertainty remain
      explicit; no reference allele is supplied from missing data. Bundle format
      19 is additive; M9.13 confidence remains frozen. See [the contract](pgx_calling.md).
      The [diff review](review_m102_session.md) binds saved native dosages and
      corrects input validation, error categories and candidate presentation.
- [x] **M10.3** **CYP2D6 explicit "not callable" card.** PharmCAT declines to call it from
      a VCF because structural/CNV variation dominates, and a `*5` whole-gene deletion
      makes the other allele read as homozygous (`*5/*29` → `*29/*29`). Render the
      limitation; do not omit the gene silently.
      - **The card itself shipped in [M3.7](#m3--card-engine--knowledge-pack)**
        (`cyp2d6_structural_variation`), because §3.2's copy-number entry names CYP2D6
        hybrids and the register has to be complete. What is left here is placement: it must
        render beside the diplotypes M10.2 calls, so the gap is visible where a reader is
        looking at the genes that *were* called. Do not author a second card.
      - Implemented beside saved calls on the dashboard, overview and every gene
        detail, independently of knowledge-card filters. CLI text/JSON carries
        frozen limitation evidence; missing saved cards and historical sample
        stages remain explicit. Six synthetic cases cover saved/missing cards,
        three stage states, filters, all eight genes, multi-page retention and
        bundle immutability. See [the contract](pgx_calling.md#m103-cyp2d6-placement).
- [x] **M10.4** CPIC guideline-linked cards: phenotype → dosing implication, with the
      guideline cited and its evidence level shown.
      Eight declarative schema-5 selectors retain all conditional source branches,
      exact definition/mapping/result and drug/guideline joins, multi-gene requirements,
      native copy models, separate evidence fields and explicit gaps. Format 20
      reproduces saved cards offline from sample schema 1; VKORC1's absent keys
      remain explicit. See [the contract, audit and acceptance](pgx_guidelines.md)
      and the [M10.5 handoff](handoff_history.md#next-open-step-m105-section-framing).
- [x] **M10.5** Prominent framing that this is not a prescribing tool, stated once and
      precisely — not repeated as filler on every card. Shared current context
      now appears once across section/overview/gene views and CLI; JSON separates
      it from frozen findings. Display schemas 1–2 and saved/unavailable/historical
      evidence are preserved. See [the contract and validation](pgx_framing.md).

---

## M11 — HLA, immunogenetics & carrier status

- [x] **M11.1** R + HIBAG detection and subprocess bridge. Optional module that degrades
      gracefully with a clear "R not installed" state. Share readiness with doctor,
      preserve probe failures separately from missing dependencies and report R/HIBAG
      identities. Shared isolated execution, strict protocol, timeout/cancellation
      and private diagnostics are implemented. See the [runtime contract](hla_runtime.md).
- [x] **M11.2** HLA imputation using **HIBAG pre-fit classifiers** (European/Asian/
       Hispanic/African). Explicit, opt-in hg19 model ingestion validates pinned source
       bytes, metadata and dbSNP/1000 Genomes strand proofs before accepting per-locus
       calls, posteriors and coverage in frozen bundle-format-21 evidence. `no-markers`
       and `no-prediction` are not negative calls. **Do not use SNP2HLA** — its T1DGC
       panel was withdrawn over individual-level genotype concerns and now needs a NIDDK
       request. See the [implementation contract](hla_imputation.md).
- [x] **M11.3** Ancestry-matched classifier selection, driven by M5 output. Report
      posterior probability per call and fold it into confidence. AADR decline gate plus
      1000 Genomes → Morales category → publisher training description; declined, not
      run, ambiguous and unsupported placements select nothing. Explicit classifiers run
      with their ancestry mismatch recorded. Per-locus ceilings use the calculator's own
      posterior/coverage/ancestry bands. Schema 2, format 22. See the
      [selection contract](hla_selection.md).
- [x] **M11.4** HLA-linked cards: celiac (DQ2/DQ8), type 1 diabetes, ankylosing
      spondylitis, narcolepsy (DQB1\*06:02), drug hypersensitivity (B\*57:01/abacavir,
      B\*15:02/carbamazepine), plus A\*31:01/carbamazepine and B\*58:01/allopurinol, which
      the frozen CPIC release keys the same way. Knowledge schema 6 `kind: hla`; one engine
      for the PGx overlap; declared phase policy; bundle format 23. See the
      [card contract](hla_cards.md).
- [x] **M11.5** Carrier status cards for array-tractable recessive conditions. Knowledge
      schema 7 `carrier` declaration bound to the genotype map; 15 reproductive cards plus
      HFE C282Y; panel schema 1 (`genetics cards carriers`); bundle format 24 re-derives
      each saved state. Measured candidate audit with every exclusion recorded. See
      [carrier status](carrier_status.md).
- [x] **M11.6** **Carrier-screening incompleteness card**: CNV-based conditions (SMN1/SMA,
      alpha-thalassemia) are invisible to this data. State it, or the section implies a
      completeness it does not have. Computed card `carrier_screening_scope` against Gregg
      2021's 113 genes; knowledge schema 8, bundle format 27,
      `genetics cards carrier-scope`. See
      [section-level scope](carrier_status.md#section-level-scope-m116).
      - **The two per-gene cards shipped in [M3.7](#m3--card-engine--knowledge-pack)**
        (`smn1_copy_number`, `alpha_globin_deletions`), each carrying the "no result is not
        a negative result" caveat this box exists for. What is left is the *section-level*
        statement — carrier screening from an array is incomplete as a category, not only
        for the two conditions §3.2 happens to name — which is a different claim and needs
        M11.5's callable set to exist before it can say what it excludes.
- [x] **M11.7** Reproductive section beyond carrier status: age at menarche/menopause and
      related traits. Seven polygenic cards, each with its own endpoint, on knowledge schema 9
      and bundle format 28. Models chosen by a stated rule between Ding 2023 and Prive 2022 per
      trait, and by measured R2 among ExPRSweb's menopause models; number of children and
      childlessness are recorded as left out, because their phenotype coding could not be read.
      See the [model audit](reproductive_prs.md).

---

## M12 — Nutrition & metabolism

- [x] **M12.1** Cards: MCM6 lactase persistence, CYP1A2 caffeine, ADH1B/ALDH2 alcohol,
      HFE hemochromatosis, celiac HLA-DQ (reuse M11), FUT2 secretor status, vitamin D
      (GC), B12, folate. Seven new schema-3 cards, with lactase and ALDH2 moved from traits.
      HFE and celiac are reached by a section pointer rather than moved or copied. Folate is
      FOLR3 rs652197, the one non-MTHFR genome-wide locus found, read from imputation. MTHFR
      stays with M12.2. See [the nutrition audit](nutrition.md).
- [x] **M12.2** **MTHFR card as a deliberate calibration test case.** Heavily overhyped in
      wellness marketing. Include it, state the actual evidence, and let the confidence
      calculator land where it lands. This card is the reference example for how the
      project handles popular claims with thin support.
      Four cards on rs1801133, by owner decision: homocysteine and folate in nutrition
      (well-established), and the venous-thrombosis, coronary-heart-disease and depression
      claims in their own sections (each limited, because replication conflicts). See
      [the calibration audit](mthfr.md).

---

## M13 — Agent interface

*The CLI is the contract. Every analysis must be reachable as JSON
([AGENTS.md §3](../AGENTS.md)).*

- [x] **M13.1** `genetics list-runs`, `show <run> [--section S]`,
      `card <run> <card-id> --json`, `evidence <card-id>`, `qc <run>`, `refs licenses`.
      - **Done 2026-11-10** as `runs show --section` (repeatable), `runs card`, `runs qc` and
        `cards evidence`. Run-scoped reads stay under `runs`; `evidence` reads only the pack,
        so it is under `cards`. AGENTS.md §3 now gives these names. Each payload keeps the
        saved record apart from a `current_context` block (section frames, M12.1 pointers,
        citation links, the PGx notice). `runs qc` and `cards evidence` are scanned for
        genotypes; `runs card` is not, like `runs show`. See
        [the read-command contract](agent_cli.md).
      - **Delivered before M13.1:** [M4.2](#m4--run-bundle--first-ui) shipped `genetics runs
        list` (this item's `list-runs`, under the `runs` group), and `refs licenses` landed
        in M2.6.
      - **The [M13.1 diff review](review_m131_session.md)** fixed `runs card` text
        calling computed, polygenic and guideline cards "Not scored": they keep their tier
        in `computation.reliability`.
- [x] **M13.2** Stable JSON schema, versioned, documented. Card JSON **must include
      citations** so an agent can verify rather than confabulate.
      - **Done 2026-11-11.** `src/genetics/cli/agent_schema.json` (JSON Schema 2020-12)
        describes seven payloads: `runs.list`, `runs.show`, `runs.section`, `runs.card`,
        `runs.qc`, `cards.evidence` and `error`. Each document starts with
        `"schema": {"name", "version"}`, and `genetics schema` prints the document. Now
        version 2 (see the review below).
        Changes are additions only and take the next version; a test pins each version's
        shape. See [the agent schema](agent_schema.md).
      - **Settled from the M13.1 handoff:** `run_id` is the directory name in every command
        (`runs show --json` keeps the manifest's as `recorded_run_id`); every command that
        printed an error document prints `{kind, message}` (`pgx` and `pgs` printed a
        string); the read commands exit 1 or 2 by a stated rule; and the saved record is
        kept apart from `current_context` by rule.
      - **Citations** are required on every saved card and evidence declaration, with `type`
        and `id` on each.
      - **The [M13.2 diff review](review_m132_session.md)** moved the schema to version 2:
        version 1's `error.kind` pattern refused `run_parts` and `frequency_reference`, which
        `genetics run` prints. `pgx calls` and `hla calls` now give the same kind as `runs`
        for a run that cannot be opened.
      - **Left as it is, and recorded:** `run`, `impute` and `serve` exit 2 for every
        failure; `ingest`, `refs`, `tools` and `paths` print failures as text under
        `--json`, and `roh` has no `--json`; the saved records behind `runs clinvar`, `pgx calls` and `hla calls` are
        not in version 1.
- [x] **M13.3** `genetics search <query>` across cards, so an agent can find "curly hair"
      without knowing the card id.
      - **Done 2026-11-12** as `genetics cards search <query>` (the knowledge pack; no
        genotype, scanned) and `genetics runs search <run> <query>` (one saved run's cards,
        with each one's saved face). Not a top-level command: M13.1 put pack reads under
        `cards` and run reads under `runs`, and the two differ in privacy. See
        [the search contract](agent_cli.md#search-m133).
      - **One ranking,** `genetics.engine.search.search`: fourteen weighted fields; a query
        word matches exactly, by stem or as a prefix; order is words matched, then score,
        then listing order. Partial matches are listed, each hit names the fields that
        matched, and status and confidence play no part.
      - **A query that reads as a genotype is refused** by both commands, before anything
        is read (kind `genotype-in-query`).
      - **Agent schema version 3:** payloads `cards.search` and `runs.search`. No existing
        payload changed.
      - **Left for later:** the dashboard's search (M14.4) should call
        `reads.search_view` (done at M14.4); guideline recommendation rows and saved score
        records are not searched.
      - **The [M13.3 diff review](review_m133_session.md)** fixed a stemming rule that
        cut `note` to `not`, so that `cards search note` listed 109 of 119 cards, and made
        the side-by-side bonus read the query as typed, dropped words included.
- [x] **M13.4** Machine-readable confidence: tier plus the numeric inputs that produced
      it, so an agent can explain *why* a card is low confidence.
      - **Done 2026-11-12** as `current_context.confidence` on `genetics runs card`: one
        block for every kind of card, built when the run is read by
        `genetics.run.explain.explain_confidence`. See
        [the confidence contract](agent_cli.md#confidence-m134).
      - **The saved record is unchanged.** M4.1 stores the inputs beside the tier, in two
        places by card kind: `confidence` (six scored inputs, PPV) for interpretation and
        HLA cards, and `computation.reliability` (inputs, ceilings, reason) for computed,
        polygenic and guideline cards. Both stay, and stay described.
      - **What decided the tier is stated:** `basis` (`score`, `ceiling`, `method`,
        `not_reproduced`, `none`), each input's weight and what it cost the score, every
        ceiling that applies, the inputs whose ceiling is the tier, and a sentence. A card
        with no tier says why.
      - **One statement of the ceilings.** Both calculators take them from
        `single_call_ceilings` and `polygenic_ceilings`, which the reader calls too. No
        tier changed; a test compares 22,848 results with a copy of the earlier rules.
      - **Checked before it is offered.** The saved inputs are replayed; a tier or score
        that does not come out as saved is reported as `not_reproduced`, unexplained.
      - **Agent schema version 4.** No other payload changed.
      - **Left for later:** the block is not on `runs show --section` or `runs search`; the
        dashboard prints the sentence and its six rows, not the weights or the ceiling
        list (M14.3).
      - **The [M13.4 diff review](review_m134_session.md)** fixed the replay, which
        summed rounded figures and so reported 23 of 20,000 polygenic scores with arbitrary
        decimals as `not_reproduced`, and stopped a rare call's rate being printed twice.
- [x] **M13.5** Parity test: every UI-reachable analysis is CLI-reachable. Wire into CI —
      this is the requirement most likely to silently rot.
      - **Done 2026-11-13** as `genetics.testing.parity`, run by `tests/test_parity.py`. See
        [the parity section](agent_cli.md#parity-m135).
      - **Reachable means in a command's JSON** (AGENTS.md §0), checked three ways, each
        listed from the dashboard's code so that something new fails until it is placed:
        all eight routes have commands in `parity.PAGES`; every engine function
        `genetics.web` calls is one the CLI's read side calls (two stated exemptions); and
        for a saved run, each context key, each `Shell` field and each field of every card
        a page is handed equals what the real commands print.
      - **The five record commands are described** (`runs clinvar`, `runs secondary`,
        `runs imputation`, `pgx calls`, `hla calls`): run envelope, schema tag, agent
        schema version 5. This was the decision M13.2 left here.
      - **Found:** `hla calls --json` did not say whether HLA-linked cards were recorded;
        the bundle format in the dashboard's footer was in no command; `pgx calls`'
        `current_context` had no `context` key. All three are fixed. No page showed a
        value missing from every command.
      - **In CI as part of the suite.** It needs no native tool and no reference. The
        suites that build runs with PGx calls, guideline cards, HLA calls, a placed score
        and a ClinVar lookup run the same check on them through `parity_check`.
      - **The [M13.5 diff review](review_m135_session.md)** changed every value of
        every card view once. Views held inside a card and a polygenic view's saved parts
        had been compared by whether a value appeared anywhere in the record, so 38 of 170
        changes to a placed score's view passed. They are compared field for field now, the
        probe is `parity.unnoticed`, and `parity_check` runs it on every suite's run.
      - **Left for later:** a view property's arithmetic is listed, not checked; what the
        CLI prints and no page shows is not looked for (`ancestry_comparison` is on no
        page); a page added in M14 needs a row in `parity.PAGES`.
- [x] **M13.6** Document the review workflow in `AGENTS.md` or a `docs/agent-usage.md`,
      with the worked example from the project brief (*"it says I'm predisposed to curly
      hair — review the cited information and give me 10 interesting facts"*).
      - **Done 2026-11-15** as [Reviewing a run as an agent](agent_usage.md), with a
        pointer in AGENTS.md §3. The file name has an underscore, like `agent_cli.md` and
        `agent_schema.md` beside it.
      - **Eight steps:** pick the run, check its QC, find the card, read the result, read
        the claim without the result, read the cited papers, search further, answer. Then
        what an answer carries, which command starts each other kind of question, and what
        to do when a step fails.
      - **What may leave the machine is a rule about sources:** a search, a fetch or a file
        is written from `cards search`, `cards evidence` and papers already read, never
        from a `runs`, `pgx` or `hla` command, and each query is written as if the result
        were unknown.
      - **The example is real output from a run that is nobody's:** five committed cards
        matched against an invented table. The WNT10A card was checked against the full
        text of both cited papers; every figure agreed. The ten facts each name the table
        or section they were read in.
      - **The page is tested** (`tests/test_agent_usage.py`): every command written on it
        exists with its options, each marked output is what the command prints, each key
        named is in the document, and each example query uses only words `cards evidence`
        prints. `parity.command_problem` is now public and can check a command written
        without `--json`.
      - **The [M13.6 diff review](review_m136_session.md)** found that the query
        check reads words and not meaning: the marker with "one copy", or followed by its
        two alleles apart, uses only words the evidence prints and passes. The page had
        said a query built from the result fails. It now states the limit, and the test
        asserts it so the sentence fails when M13.7 closes it. The review also holds the
        statuses, tier bases and error kinds the page names in prose to the schema and the
        code, checks the twelve commands written without `genetics`, and corrects the
        source of one fact.
      - **Left for later:** nothing checks a web search (M13.7). The comparison with the
        papers and the ten facts are prose and no test holds them. Whether a hosted agent
        reading `runs card` is within AGENTS.md §1.3 is settled on the page as "the cards
        asked about, read narrowly", which the owner may want otherwise.
- [x] **M13.7** Reinforce [AGENTS.md §1.3](../AGENTS.md): agents research the **variant**,
      never the user's genotype at it. Add a lint/test for genotype strings in outbound
      query construction.
      - **Done 2026-11-19** as `genetics cards check-query <query> [--card ID] [--json]`,
        on a new module, `genetics.outbound`. See
        [Query check](agent_cli.md#query-check-m137) and
        [step 7 of the walk-through](agent_usage.md#7-search-further).
      - **Eight rules, two kinds.** `call`: the privacy scanner's shapes, an rsID beside two
        alleles, a diplotype. `result`: zygosity, a count of copies, the first person, a
        run id, a confidence tier. The query check refuses both and exits 1, and never
        prints the query. `cards search` and `runs search` now refuse the three `call`
        rules (an rsID beside two alleles was searched before), and still search result
        words, which leave nothing.
      - **Shapes and sources.** With `--card`, each query word the card's
        `cards evidence` does not print is listed as `unsourced`: advice, since a word read
        in a cited paper is fair to search. A haplogroup, an HLA type or a tier has no
        shape, and this is where one shows up.
      - **The two queries M13.6 left open are refused**: the marker with "one copy", and
        the marker with its two alleles apart. The walk-through's test now asserts that.
      - **The engine's own requests are checked.** The fetcher passes each URL through
        `outbound.check_url`, and `tests/privacy/test_outbound.py` reads the source for
        every call that builds or opens a request and fails one that skips it.
      - **Agent schema version 6**: one payload, `cards.check-query`. AGENTS.md §1.3 says
        to run every outbound query through the check, and that its rules are a floor.
      - **Left for later:** no rule list is complete, and the source check is advice. The
        hosted-agent reading of §1.3 that M13.6 recorded is still the owner's to confirm.

---

## M14 — UI completion

- [x] **M14.1** All thirteen sections wired, each with an explicit empty state explaining
      *why* it is empty when it is.
      - **Done 2026-11-19.** The thirteen sections already rendered in the nav and the grid
        whatever a run held (M4.5). What was wrong was the sentence: a section with no card
        said "Not built yet — roadmap M…", and since M12 every section has cards in the
        pack.
      - **Three sentences, one function** (`reads.empty_reason`, shared by the nav, the
        grid and `runs show --section`, which the parity test now compares field for
        field). No card in the run: it was saved with a pack that held none here, and the
        current pack's count is what a new run would show. Cards and no interpretation:
        each status counted by its label, each distinct `not_run` reason quoted (the
        engine's sentence about a module, up to three), and a section of assay limits says
        so; a failed match's reason is about the call and stays on the card. No run open:
        one sentence that claims nothing about a run.
      - **Left for later:** the ancestry section holds only assay-limit cards; its analysis
        is a run-wide record with no page until M14.2.
- [x] **M14.2** Ancestry visualisations: PCA scatter with reference populations, ancient
      affinity, haplogroup display with marker counts.
      - **Done 2026-11-19** as the `/runs/{run_id}/ancestry` page and `genetics runs
        ancestry <run> [--json]`, which prints what it draws. See
        [Ancestry](agent_cli.md#ancestry-m142).
      - **Bundle format 29 records reference positions.** The ancestry record's placement
        gains the model's `scale` and each fit its population's `centroid`, so a saved run
        is drawn against the reference it was placed in, never the one installed when it is
        opened. A run saved before 29 lists its fits by rank and says why there is no
        scatter. A format before 29 that claims positions is refused.
      - **Three marks, no region colours.** A scatter takes at most three categorical hues
        (the dataviz rule; the two used are validated all-pairs in both modes), and the
        panel has a dozen regions. References are neutral rings, the five nearest are
        filled, the run is a cross in a ring; names and regions are in hover text and the
        table. Only the nearest population and the run are labelled.
      - **Haplogroups show both counts** (§4.7): supporting markers, and this array's
        markers on defining sites. Ancient affinity is listed by distance and called
        affinity, not ancestry proportions.
      - **Agent schema version 7** (`runs.ancestry`). The nav links the page from every run.
      - **Left for later:** the scatter shows the first two of the model's components only;
        the table ranks on all of them, and the caption says so.
- [x] **M14.3** Confidence legend and a "how to read these results" page covering the
      rarity-inversion, PRS attenuation, and array limitations.
      - **Done 2026-11-19** as the `/guide` page and `genetics cards guide [--json]`, which
        prints what it shows. See [Reading guide](agent_cli.md#reading-guide-m143).
      - **One document, from the engine.** `genetics.run.guide.reading_guide` reads the
        weights, bands, evidence and replication components, frequency components and
        quality and share bounds from tables in `engine/confidence.py` that the
        calculators use, and lists the ceilings by calling `single_call_ceilings` and
        `polygenic_ceilings`; a test fails on any ceiling the engine can apply that the
        guide does not list. The two benchmarks are `engine.ppv.benchmark`. No tier
        changed: the M13.4 comparison of 22,848 results with the earlier rules passes.
      - **What is authored is prose and the figures it quotes**, each with its paper in
        `sources`: Weedon 2021, Tandy-Connor 2018, Okbay 2022 (EA4) and Ding 2023, read
        from their abstracts.
      - **The legend is in every page's nav**, the card faces' own badges, each linking to
        its row in the guide; the grid's tier headings and the card page's "Why this tier"
        link in too. Not on the faces, which are already one link each.
      - **The page holds no run**: its shell is the run listing alone. Agent schema
        version 8 (`cards.guide`). The tier labels moved to `genetics.run.guide`.
      - **Left for later:** the card page still prints the sentence and six rows M13.4 gave
        it, not each card's weights and ceiling list, which `runs card --json` holds.
- [x] **M14.4** Global search across cards.
      - **Done 2026-11-19** as `/runs/{run_id}/search` and a search box at the top of every
        open run's nav. See [Dashboard search](agent_cli.md#dashboard-search-m144).
      - **One function.** The route calls `reads.search_view`, which `genetics runs search
        <run> <query> --json` prints, so the dashboard and the CLI rank identically
        ([AGENTS.md §3](../AGENTS.md)); the parity check compares them key for key.
      - **Faces as the grid shows them**, tier first, with the words each matched. Partial
        matches are listed below full ones; every section is searched whatever the grid's
        filters say (§0.1A).
      - **A refused query is not shown again.** The page gives the engine's sentence, which
        names the rule and not the text, and leaves the box empty; the parity check compares
        it with the error `runs search` prints.
      - **Left for later:** a page with no run open (the guide, an empty store) has no box;
        the pack is searched by `genetics cards search`, and a pack card has no page here.
- [x] **M14.5** QC / provenance page: reference versions, tool versions, imputation
      parameters, coverage stats.
      - **Done 2026-11-20** as `/runs/{run_id}/qc`, linked from every run page's nav. See
        [QC and provenance page](agent_cli.md#qc-and-provenance-page-m145).
      - **Two documents, whole.** The page holds what `genetics runs qc <run> --json` and
        `runs imputation <run> --json` print; the parity check compares each key for key.
        Both commands scan for genotypes, and the route scans the whole page.
      - **Coverage is both records, kept apart** (`runs qc`'s `current_context.coverage`,
        agent schema 9): every polygenic card's saved coverage before and after imputation,
        placed or not (§0.1A), and the saved ClinVar coverage record, with a status naming
        which of four states a run is in. Nothing is recounted.
      - **Imputation is summarised, not paged.** A full run has about 25 regions; the page
        gives the parameters, a row per region and a row per job. Position-level decisions
        and every digest stay in the command's document.
      - **Left for later:** the page shows what the manifest recorded as installed at save
        time beside what the imputation stage used; it does not compare either with today's
        installation.
- [x] **M14.6** Impossibility cards surfaced in their relevant sections, not hidden in an
      appendix.
      - **Done 2026-11-20.** See
        [Assay limits in their sections](agent_cli.md#assay-limits-in-their-sections-m146).
      - **What was wrong:** sorted by tier (the default), a limit went last, beneath every
        marker-absent card of its section; grouped by tier, all twelve sat among the
        unmatched cards; a filter hid them while their section's findings stayed.
      - **Named at the section's head, whatever the filter.** A line of links, not copies, so
        a filter still hides and counts a card (M4.7) and the section never reads as
        complete. `runs show --section` prints the same list as `assay_limits` (agent
        schema 10), with the current pack's limits a run lacks marked `in_run: false`.
      - **Their own block** below a section's findings, and below the unmatched cards in the
        untiered panel when grouped by tier.
      - **Register checked:** AGENTS.md §3.2's eight bullets map to the twelve cards, both
        ways, by `tests/engine/test_impossibilities.py`. None missing.
      - **Left for later:** grouped by tier, the block follows the reader's sort (title by
        default), not section order; each card names its section.
- [x] **M14.7** Accessibility pass: keyboard navigation, contrast, screen-reader labels.
      - **Done 2026-11-20.** See [Accessibility](agent_cli.md#accessibility-m147).
      - **Audited, not eyeballed:** `genetics.testing.accessibility.audit` parses each page
        (ids, references, names, labels, focusables in images, headings, landmarks); contrast
        is computed from `app.css`'s tokens with WCAG's formula.
      - **Keyboard:** a select acts on a pointer's choice or Enter, never on an arrow press
        (WCAG 3.2.2); the run selector gained Open. One Tab stop per card, ringed.
      - **Contrast:** text already passed; control edges went from about 1.3:1 to 3.6:1.
      - **Labels:** card link named by title, described by tier; counts in words; one search
        landmark per page; theme toggle named by what it shows; scatter points named.
      - **Left for later:** no screen-reader session was run; the theme toggle's new state is
        not announced; some HLA, PGx and ClinVar tables lack captions.

---
