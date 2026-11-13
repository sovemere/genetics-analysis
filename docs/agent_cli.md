# Agent read commands (M13.1, M13.3, M13.4, M13.5)

Implemented 2026-11-10. Four commands let an agent read one card, one section, a run's QC
record, or a card's evidence without printing a whole bundle. On the real imputed run
`runs show --json` prints about 1 GB. M13.3 (2026-11-12) added two search commands, so an
agent can find a card without knowing its id. M13.4 (2026-11-12) made `runs card` say what
decided a card's confidence tier, in one shape for every kind of card; see
[Confidence](#confidence-m134). M13.5 (2026-11-13) added a test that every analysis a
dashboard page shows is in a command's JSON, and described the five commands that print a
run's other saved records; see [Parity with the dashboard](#parity-m135).

| Command | Reads | Holds a genotype | Scanned |
|---|---|---|---|
| `genetics runs show <run> --section S [--section T] [--json]` | saved run | yes | no |
| `genetics runs card <run> <card-id> [--json]` | saved run | yes | no |
| `genetics runs qc <run> [--json]` | saved run | no | both branches |
| `genetics cards evidence <card-id> [--json]` | knowledge pack | no | both branches |
| `genetics cards search <query> [--limit N] [--json]` (M13.3) | knowledge pack | no | both branches |
| `genetics runs search <run> <query> [--limit N] [--json]` (M13.3) | saved run | yes | no |

`genetics runs list` (M4.2) and `genetics refs licenses` (M2.6) are the rest of M13.1's list.
The two search commands are described under [Search](#search-m133).

Since M13.2 these payloads, `runs list --json` and `runs show --json` are described by a
versioned JSON Schema, and each begins with a `schema` tag naming its payload and version.
Since M13.5 so are `runs clinvar`, `runs secondary`, `runs imputation`, `pgx calls` and
`hla calls`.
The sketches below leave the tag out. See [the agent schema](agent_schema.md) for field types,
vocabularies, the error document and exit codes.

## Where they live

Run-scoped reads are under `runs`, beside `list`, `show` and `delete`, so a saved run has one
command group. `evidence` reads no run, so it sits under `cards`, beside `carriers` and
`carrier-scope`. AGENTS.md §3 named top-level `list-runs`, `show`, `card` and `evidence`. M4.2
had already put listing under `runs`, and top-level aliases would give each command two names,
which this project has removed three times (M0.4, M3.7, M4.1). AGENTS.md §3 now gives the real
names.

## Saved record and current context

Each payload keeps the saved record apart from what this engine adds when it reads the run.
Everything added is under `current_context`, which carries `"context": "current"`. M10.5 set
this split for `pgx calls`, and the M11.6 and M12.1 reviews kept it. `runs show --json`
without `--section` is unchanged: it prints the saved bundle with no current context.

`run_id` is the bundle's directory name, which every command resolves. At M13.1
`runs show --json` still printed the manifest's own `run_id`. M13.2 made it the directory name
there too, and kept the manifest's value as `recorded_run_id`. The two differ only when a
bundle directory has been renamed.

### `runs card`

```text
run_id, path, format_version, created_at
card                    the saved card; the same projection as runs show --json's cards[]
current_context
  context               "current"
  section               {section, title, blurb}
  citation_links        [{type, id, url}] in the order of card.citations; url null when
                        this engine will not link it (re-validated, as the dashboard does)
  confidence            what decided the card's tier (M13.4); see Confidence below
  related               pointers the card's section declares (M12.1), resolved in this run:
                        [{card_id, in_run, title, section}]
  pointed_from          sections whose pointers name this card
```

M12.2's four MTHFR cards use both pointer lists. A claim card's `related` reaches the
nutrition card, whose `pointed_from` is `["physical_health", "mental_health"]`.

An unknown card id exits 1 with `error.kind: card-not-found` and names `runs show` as the way
to list the run's cards. The dashboard says the same thing for a stale card link.

The text form prints the claim, the variant, how the call was made, the evidence block, the
confidence tier with what decided it and every input behind it, any empirical PPV, the
frequencies, every caveat and the citations with links. The confidence lines are
`current_context.confidence` as text, so the text and the JSON say the same thing. A card
with no tier says "Not scored" and why. A rare call's rate is printed once, in the sentence
that says what decided the tier; the benchmark's scope and the clinical notice follow it.
Polygenic, HLA, runs-of-homozygosity and multi-marker detail gets one line pointing to
`--json`, which holds it in full; the dashboard draws those as tables and distributions.
Where a card has no evidence block, the text says which of three reasons applies: an
assay-limit card, a bundle older than format 2, or an outcome with no phenotype estimate.

### `runs show --section`

```text
run_id, path, format_version, created_at
sections                requested sections, deduplicated, in AGENTS.md 3.1 order
cards                   those sections' saved cards, in saved order
current_context
  context               "current"
  sections[]            {section, title, blurb, milestone, card_count, interpreted,
                         empty_reason, related, saved_records,
                         section_framing (pharmacogenomics only),
                         carrier_scope (reproductive only)}
```

Section names are the thirteen `Section` values, case-insensitive. An unknown name exits 2
with `error.kind: unknown-section` and lists the thirteen. A section with no cards is still
reported, with the dashboard's reason. `saved_records` names the commands for records beyond
the cards, which the dashboard links as pages: `runs clinvar` and `runs secondary` for physical
health, `pgx calls` for pharmacogenomics, and `hla calls` for immunogenetics. The PGx notice appears once, in its section, and is not repeated per card
(see [PGx framing](pgx_framing.md)).

### `runs qc`

```text
run_id, path, format_version, created_at
qc                              the saved QC report (qc.run.json)
imputation                      the saved execution record, or null
imputation_provenance_status    "recorded", another status, or null; the full record is
                                `genetics runs imputation <run>`
provenance                      engine version, knowledge digest, reference and tool versions,
                                input vendor and marker count
```

The text form lists every QC warning in QC's order. A field another version did not write
prints as `-`.

### `cards evidence`

```text
card_id, section, kind, title, gene
variants            [{rsid, chrom, pos_grch37, alleles}]
evidence            card-level evidence, in the saved form
outcome_evidence    {outcome: evidence or null} for outcomes that set their own (schema 3)
polygenic           {pgs_id, scoring_source, trait, decile_outcomes} or null
hla, carrier        the authored declarations, or null
computation, method_evidence, impossibility_reason
citations           [{type, id, title, database, note, url}]
caveats             authored caveats
```

Outcome text is left out. It is a template with the reader's genotype still to be filled in,
and `runs card` prints it filled in. A test runs the privacy scanner over the JSON and text
of every card in the pack, so the runtime check cannot refuse correct output.

## Confidence (M13.4)

Implemented 2026-11-12. A saved card keeps what produced its tier in one of two places, by
kind. Neither says which input decided the tier. `runs card` now reads whichever applies
and prints one block, `current_context.confidence`, for every card:

```text
source        "confidence", "computation.reliability", or null: where the saved card keeps it
basis         what decided the tier: score, ceiling, method, not_reproduced or none
tier, score   the saved values; score is null where the tier has none
score_tier    the band the score falls in before any ceiling
score_bands   [{tier, min_score}], the same in every document
inputs[]      {name, values, component, weight, contribution, lost}
ceilings[]    {input, tier, rule}: every ceiling that applies to the saved inputs
limiting      the inputs whose ceiling is the card's own tier
reason        what decided the tier, in a sentence or two
empirical_ppv the saved benchmark, repeated, or null
replay        {tier, score, matches}: this engine's rules applied to the saved inputs
```

### How a tier is decided

A tier is the weaker of two things: the band the weighted score falls in, and every ceiling.

- **The score** is the sum of six inputs, each a component from 0 to 1 times a fixed weight.
  The weights sum to 1. `contribution` is what an input added and `lost` is what it cost.

  | Row (single call) | Row (polygenic score) | Weight |
  |---|---|---|
  | `evidence_tier` | `evidence_tier` | 0.30 |
  | `effect_size` | `effect_size` | 0.15 |
  | `replication` | `replication` | 0.20 |
  | `allele_frequency` | `weight_coverage` | 0.20 |
  | `call_quality` | `weighted_quality` | 0.10 |
  | `ancestry_match` | `ancestry_match` | 0.05 |

- **The bands** are well-established from 0.85, strong from 0.70, moderate from 0.50 and
  limited below that. No score earns `likely-artifact`.
- **A ceiling** is the best tier one input allows, whatever the score. Strong literature
  cannot raise a weak observation (AGENTS.md §4.1).

  | Input | Condition | At most |
  |---|---|---|
  | `evidence_tier` | no phenotype estimate applies to the result, or the tier is anecdotal | limited |
  | `evidence_tier` | candidate_gene | moderate |
  | `replication` | conflicting | limited |
  | `allele_frequency` | below 0.001%, the rare-call band | likely-artifact |
  | `allele_frequency` | no frequency was available | moderate |
  | `call_quality` | imputed with no quality estimate | limited |
  | `call_quality`, `weighted_quality` | below 0.30 / 0.60 / 0.80 | likely-artifact / limited / moderate |
  | `weight_coverage` | below 0.25 / 0.50 | limited / moderate |
  | `ancestry_match` | unknown | strong |
  | `ancestry_match` | below 0.25 / 0.50, for a polygenic score or a card with no saved `ancestry_comparison` | limited / moderate |
  | `hla_call` | an HLA card's weakest classifier call has a ceiling of its own | that ceiling |

  A card compared with its study population by membership (one with a saved
  `ancestry_comparison`, format 18 on, and every HLA card) takes no ancestry ceiling when
  the match is known; the match still enters the score.

### The five bases

| `basis` | Means | Where to look |
|---|---|---|
| `ceiling` | One or more ceilings are below the score's band | `limiting` names the inputs; `reason` states each rule |
| `score` | The score's band is the tier, and no ceiling is below it | The rows with the largest `lost`. If `limiting` is not empty, a ceiling sits at the same tier and a higher score would not raise it |
| `method` | The card's method sets the tier and there is no weighted score: computed cards (always limited when they run) and guideline cards | `reason` repeats the saved reason, and for a guideline card each gene's reasons; `inputs` holds the saved flags, or one row per gene |
| `none` | The card has no tier | `reason` says why: an assay limit, or the status with the saved reason |
| `not_reproduced` | This engine's rules do not give the saved tier and score from the saved inputs | `replay`. The saved tier stands; nothing is said about what decided it |

Every ceiling that applies is listed, including one above the tier, which changes nothing.
A polygenic card's saved `computation.reliability.ceilings` is narrower: it names only the
ceilings that lowered the tier when applied in order, under the names `evidence`,
`imputation_quality`, `coverage` and `ancestry`.

### What is saved and what is this engine's

`tier`, `score`, every `values` entry, every `component` and `empirical_ppv` are the saved
record's. The weights, bands, ceilings, `limiting` and `reason` are this engine's reading of
it, which is why the block is under `current_context` and the saved card is unchanged.

The reading is checked before it is offered. The saved inputs are replayed through the
rules the calculator itself calls (`single_call_ceilings` and `polygenic_ceilings` in
`engine/confidence.py`). If the replayed tier differs from the saved one, or the saved
components times their weights do not sum to the saved score within 0.00015, the basis is
`not_reproduced`. A run saved under other weights or thresholds therefore gets no
explanation, not a wrong one. The sum uses the components, not the rows' `contribution`
figures: each of those is rounded to four places on its own, so the rows can add up to a
figure 0.0002 from `score`.

A multi-marker card takes its weakest marker's confidence; `reason` names that marker. An
HLA card gets an unscored `hla_call` row and, where its weakest call has a ceiling, that
ceiling. The block states no genotype of its own, but `runs card` is unscanned as before.

### Where it appears

Only in `runs card`. `runs show --section` and `runs search` list each card's saved
`confidence_tier` and add nothing. The dashboard's card page prints `reason` under "Why this
tier", from the same function, `genetics.run.explain.explain_confidence`.

### Decisions

No owner question was asked. The M13.4 entry contract listed three open points:

- **One shape, built at read time.** The saved card is frozen, so the block is under
  `current_context`. Both saved places stay as they are and stay described.
- **The values were not enough, so what decided the tier is stated.** That needs the
  ceilings, which no saved block lists in full. The calculators now take theirs from two
  functions that the reader calls too, so the two cannot state different rules.
- **A card with no tier is covered.** It gets the same block, with basis `none` and the
  reason it was not scored.

### Validation

`tests/run/test_explain.py` keeps a separate copy of the rules as they were before the
ceilings moved, and compares 16,800 single calls and 6,048 polygenic scores: the earlier
tier, the saved tier, the saved ceiling names and the replay all agree. It then checks each
basis, a rare call (the reason gives the 16% benchmark), nine ways a saved block can fail
to replay, computed and guideline cards, HLA call ceilings and multi-marker cards.
`tests/test_agent_schema.py` checks the block for every card of a saved run of 103 cards,
and `tests/hla` and `tests/refs` check it for the real HLA and guideline cards.
Thirty-five guards were each removed in turn, and each removal failed a test. The full
native suite passes 4,229 tests with the existing nine skips.

The [session diff review](review_m134_session.md) found that the replay summed the rows'
rounded `contribution` figures, so that 23 of 20,000 polygenic scores drawn with arbitrary
decimals were reported as `not_reproduced`; the grids above use round inputs and could not
show it. It now sums the saved components. The review also stopped a rare call's rate being
printed twice. Two failing scores are pinned as a test, 6,000 results with arbitrary
decimals are replayed, and seven more guards were removed in turn, each caught.
The full native suite passes 4,235 tests with the existing nine skips.

`runs card` has not been run on the real imputed run since this change.

## Search (M13.3)

Implemented 2026-11-12. An agent asked about "curly hair" does not know the card is called
`wnt10a_hair_curl`. Two commands find it, and both rank with one function,
`genetics.engine.search.search`:

```text
genetics cards search curly hair            the knowledge pack; no run, no genotype
genetics runs search <run> curly hair       one saved run's cards, with each one's result
```

The query is every word after the command (and after the run id), quoted or not.
`--limit N` shows the best N and still states the total. A query word that begins with a
hyphen reads as an option, so put `--` before the query: `genetics cards search -- -163C>A`.
Inside a longer quoted query it needs nothing.

### Which one to use

- **`cards search` to find a card id.** It reads the pack only, so it works with no saved
  run, and its output is checked for genotypes on both branches. Follow it with
  `cards evidence <card-id>`, or `runs card <run> <card-id>` for the result.
- **`runs search` to find a result in one run.** It searches what that run saved: the
  summary and detail it recorded, not the pack's other outcomes, and the cards that run
  holds, which may differ from today's pack. Each hit carries the card's saved face, so the
  output states the reader's result and is not scanned, like `runs show`.

### What is searched

| Field | `cards search` | `runs search` | Weight |
|---|---|---|---|
| `title` | the card's title | the saved title | 5 |
| `gene` | the gene symbol | the saved symbol | 5 |
| `variant` | every rsID the card reads | the saved marker's rsID, and each marker of a multi-marker card | 5 |
| `card_id` | the id, split at underscores | the same | 4 |
| `trait` | a polygenic card's trait and PGS id | the same, from the saved score record when the score ran | 4 |
| `condition` | a carrier card's condition and allele name | the same, from the saved declaration | 4 |
| `hla` | the HLA alleles an HLA card reads | not a separate field; the saved title and text are searched | 4 |
| `summary` | every outcome's face, placeholders removed | the one face the run saved | 3 |
| `impossibility_reason` | why the assay cannot determine it | the same | 3 |
| `detail` | every outcome's detail and risk context | the saved detail and risk context | 2 |
| `evidence` | the effect's units and context sentence | the same | 2 |
| `caveats` | authored caveats and the carrier scope | authored and computed caveats, and the carrier scope | 1.5 |
| `citations` | titles, identifiers, databases, notes | the same | 1 |
| `section` | the section's name and title | the same | 1 |

Nothing under a saved card's `computation.result` is searched apart from a score's trait and
id. A guideline card is found by its gene, title and citation titles; the drugs in its saved
recommendation rows are read with `pgx calls`.

### How a card is ranked

- **Words.** Text is lowercased and split into runs of letters and digits, so
  `wnt10a_hair_curl` is three words and `HLA-B*57:01` is four.
- **A query word matches a card's word in one of three ways:** exactly (quality 1); by a
  shared stem (0.75), so `curly` finds `curl` and `curlier`, and `color` finds `colour`; or
  as the start of a longer word (0.5), for words of three characters or more that are not
  bare numbers. Identifiers are never stemmed: `rs7349332` and `WNT10A` match exactly or as a
  prefix.
- **Score.** Each query word scores its best weight times quality over all fields, and a
  card's score is the sum. If the whole query, as typed, appears side by side and in order
  within one field, half that field's weight is added. Dropped common words count there:
  `risk of heart disease` earns it from text that says exactly that. A score orders the hits
  of one search and means nothing across searches.
- **Order.** By how many of the query's words the card matched, then by score, then by the
  order the pack or the run lists its cards.
- **Partial matches are listed.** A card matching one word of two appears below every card
  matching both, with `terms_matched` saying so. Nothing is hidden (AGENTS.md §0.1A).
- **Confidence, status and result play no part.** A likely-artifact card, a card with no
  finding and an assay-limit card are found and ranked like any other. A test changes a
  card's status and tier and checks that the ranking does not move.
- **Common words are dropped** (36 of them, such as `of`, `the`, `my` and `is`) and listed
  as `ignored`. A query of only common words is searched as given. `a` and `i` are among
  them, so `HLA-A` matches on `hla` alone; search the allele (`A*31:01`) or the drug.

Every hit says where it matched: `matched` lists each field with the query words found in
it. It does not say which of the three qualities each word matched at, or whether the
side-by-side bonus applied.

The stemmer is a short suffix list for English (`engine/search.py`). A wrong stem costs a
match at quality 0.75; it cannot change what a card says. Two limits to know:

- **It misses some forms.** There is no rule for `-ion`, `-ic` or `-ive`, so `depressed` does
  not find `depression`. The shorter form does: `depress` matches as a prefix.
- **It joins a few unrelated words.** On the pack's own text: `even` and `evening`, `ever`
  and `every`, `german` and `germany`, `unit` and `united`, `mean` and `meaning`.

### A query is never a genotype

A query that the privacy scanner reads as a genotype (an rsID with a call attached, or an
export row) is refused before anything is searched, with `error.kind: genotype-in-query` and
exit 2. The message does not repeat the query. Search for the variant, gene or trait
(AGENTS.md §1.3). Both commands refuse it, so that the habit is the same in each. The scanner
knows the shapes listed in `genetics/privacy.py`; M13.7 owns anything beyond them.

### `cards search`

```text
query               the query as given, with runs of whitespace collapsed
terms               the words searched for, in order
ignored             common words dropped
searched            cards in the pack
total               cards that matched at least one term
limit               the --limit given, or null
hits[]              {card_id, section, kind, title, gene, score, terms_matched,
                     matched: [{field, terms}]}
```

No match is an answer, not an error: `hits` is empty and the exit code is 0.

### `runs search`

```text
run_id, path, format_version, created_at
results[]           each matched card's saved face, best first:
                    {card_id, section, kind, title, gene, status, confidence_tier, summary}
current_context
  context           "current"
  query, terms, ignored, searched, total, limit      as in cards search
  hits[]            {card_id, score, terms_matched, matched}; hits[i] is about results[i]
```

The saved faces and the ranking are kept apart, as in every run-scoped payload: `results` is
what the run recorded, and the ranking is made by this engine when it reads the run, so it is
under `current_context`. `runs card` does the same with `card.citations` and
`current_context.citation_links`.

The text form prints each card's tier (or its status, where it has no tier), section, id and
title, as `runs show` does, then its saved summary and why it matched.

### Errors

| Kind | Exit | Means |
|---|---|---|
| `empty-query` | 2 | The query has no letter or digit |
| `genotype-in-query` | 2 | The query reads as a genotype; it was not searched or repeated |
| `knowledge` | 1 | `cards search`: the pack could not be loaded |
| `not-found`, `version`, `integrity`, `io`, `bundle` | 1 | `runs search`: the run could not be opened, as for every other read |

The query is checked before the run is opened. A command line with no query at all is
rejected by Typer: exit 2, a usage message on stderr and nothing on stdout.

### Decisions

No owner question was asked. The M13.3 entry contract listed three open points, and each
follows something already settled:

- **Both the pack and a saved run are searched, by separate commands.** The roadmap's use
  ("find 'curly hair' without knowing the card id") needs only the pack, and a pack search is
  the one that can be scanned. M14.4's dashboard search is over one run's cards, and AGENTS.md
  §3 requires it to call the function the CLI calls, so the run search has to exist first.
- **`cards search` and `runs search`, not a top-level `genetics search`.** M13.1 put pack
  reads under `cards` and run reads under `runs` and declined top-level aliases. A top-level
  command would also have to choose between two payloads with different privacy.
- **A stated, deterministic ranking with no index and no dependency.** The pack holds 119
  cards and a run about as many, so every search reads all of them. Field weights, three match
  qualities and term coverage are enough to put the card a phrase names first, and an agent
  can explain a hit from `matched`.

### For M14.4

The dashboard's search should call `genetics.run.reads.search_view(bundle, query, limit)`,
which is what `runs search` prints, and `genetics.engine.search.parse_query` for the query.
M13.5's parity test can then compare the two directly.

### Validation

`tests/engine/test_search.py` tests the ranking on invented documents, one rule at a time,
then searches the committed pack for every card's own id, title, gene, rsIDs, PGS id and
carrier condition. `tests/test_cli_search.py` tests both commands: payloads, text, limits,
errors, the saved-versus-current split, a bundle with odd nested shapes, and both commands
through a cp1252 pipe. A privacy test runs the scanner over the JSON and text of a pack search
for every card's id, title, gene and rsIDs, and for each rsID followed by its alleles, so the
runtime check cannot refuse correct output.

Twenty-four guards were each removed in turn: both scans, both query refusals, the dropped
words, each ordering rule, each match quality, the placeholder stripping, both totals, the
saved summary, the split between `results` and `hits`, the query check before the run is
opened, the exit code, the tag and two edits to the schema under version 3. Twenty-three
removals failed a test. Setting the side-by-side bonus to zero did not, because its test
compared the score with the constant itself. That test now checks the order too, and another
pins the weights and qualities in the table above. The full native suite passes 4,183 tests
with the existing nine skips.

The [session diff review](review_m133_session.md) found that the stemmer cut `note` to `not`,
so `cards search note` listed 109 of the pack's 119 cards, and that the side-by-side bonus
left out the query's dropped words. Both are fixed, with a test each that fails on the first
version. Three more guards were removed for the fixes, and all 27 removals now fail a
test. The full native suite passes 4,191 tests with the existing nine skips.

Neither search command has been run on the real imputed run.

<a id="parity-m135"></a>

## Parity with the dashboard (M13.5)

Implemented 2026-11-13. AGENTS.md §3 requires one engine with two front-ends: a computation
reachable only from the dashboard is one an agent cannot review. A test in the suite now
fails when a page shows something no command prints. The check is
`genetics.testing.parity`, and `tests/test_parity.py` runs it.

Reachable means present in the JSON a command prints. AGENTS.md §0 says the CLI "emits
JSON", so JSON is what is compared. A command's text output is a reading aid: `runs card`
text gives one line for polygenic, HLA, runs-of-homozygosity and multi-marker detail and
points to `--json`, which holds each in full.

### Which command stands for which page

| Page | Shows | Commands whose JSON holds it |
|---|---|---|
| `/healthz` | The engine and bundle-format versions, the runs directory, how many runs it holds | `genetics version --json`, `genetics runs list --json` |
| `/` | The newest readable run, opened as its own page is | `genetics runs list --json` |
| `/runs/{run_id}` | The run selector, the QC banner, the thirteen sections, every card's face | `genetics runs list --json`, `genetics runs qc <run> --json`, `genetics runs imputation <run> --json`, `genetics runs show <run> --section <section> --json`, `genetics runs show <run> --json`, `genetics runs card <run> <card-id> --json`, `genetics pgx calls <run> --json` |
| `/runs/{run_id}/cards/{card_id}` | One card in full, with what decided its tier | `genetics runs card <run> <card-id> --json` |
| `/runs/{run_id}/clinvar` | The saved ClinVar reference lookup | `genetics runs clinvar <run> --json` |
| `/runs/{run_id}/secondary-findings` | The lookup's ACMG gene-list overlaps | `genetics runs secondary <run> --json` |
| `/runs/{run_id}/hla` | Saved HLA classifier calls and the HLA-linked cards | `genetics hla calls <run> --json` |
| `/runs/{run_id}/pgx` | Saved pharmacogenomic calls, one gene's candidates, the section's notices | `genetics pgx calls <run> --json`, `genetics pgx calls <run> --gene <gene> --json` |

The table is `parity.PAGES`. `/static` serves stylesheets and scripts and reads no run. A
test checks that this page names every route and command in the table.

On `/runs/{run_id}` the banner's panel and Beagle versions come from `runs imputation`,
the section pharmacogenomics notice and the CYP2D6 limitation from `pgx calls`, and the
carrier-screening statement from `runs show --section reproductive`. A dashboard page
shows 100 ClinVar loci or 100 PGx candidates at a time; the command's document holds all
of them.

### The saved records beside the cards

Five commands print the records a section's `saved_records` names. Until M13.5 their JSON
had no tag and three shapes of envelope. Each now starts like every other run-scoped
document, and [the agent schema](agent_schema.md) describes it (version 5).

```text
schema, run_id, path, format_version, created_at        every one of the five

runs clinvar <run> --json
  clinvar                 the saved lookup, whole; null before format 7
runs secondary <run> --json
  secondary               {reference, loci}: the lookup's loci that hold a record in an
                          ACMG gene, each with only those records; null with no lookup
runs imputation <run> --json
  execution               the imputation execution record
  provenance              panel, maps, Beagle and Java versions, parameters, region jobs
pgx calls <run> [--gene G] --json
  schema_version, status, reason, sex, reference_sha256, genes, sources, observations
                          the saved call record, as before
  current_context         {context: "current", section_framing}
  cyp2d6_limitation, guideline_status, guideline_cards, hla_cards
hla calls <run> --json
  schema_version, status, reason, genes, selection, reference, reference_sha256, runtime,
  parameters, sample, observations, execution
                          the saved evidence record, as before
  linked_cards_status     "recorded", or "not-recorded" for a run saved before format 23
  linked_cards            [{card_id, section, title, status, tier, summary}]
```

`pgx calls` and `hla calls` keep the record's own keys beside the envelope, where they
have always been. The document lists those keys and is closed, so a key added to either
record has to reach it.

`runs imputation --json` holds no genotype and is now checked for one before it prints, on
both branches, like `runs qc`. `runs imputation --dosages` is a different output: the saved
dosages as JSON Lines, genotype-derived, with no tag. The other four state the reader's
calls and are not scanned, like `runs card`.

`genetics version --json` now also gives `bundle_format_version`, the format this engine
writes, which the dashboard's footer and `/healthz` show.

### What is checked

Each list is read from the dashboard's own code, so something new fails until it is placed.

- **Routes.** Every route the app serves is in the table above, and every command in it
  exists and takes `--json`.
- **Engine calls.** Every engine function a `genetics.web` module calls, at module level or
  inside a route, is one the CLI's read side calls too. Two are exempt, each with its reason
  in `parity.DISPLAY_ONLY`: `phase_coverage_text`, which words a polygenic card's saved
  before-and-after coverage, and `run_signature`, the key for keeping one opened run in
  memory.
- **Values.** For a saved run, every page is rendered through the real app and what it
  hands its template is recorded: each context key, each of the nineteen fields of `Shell`,
  each of the 32 fields of every card's `CardView`, and the polygenic view a card draws.
  Each is compared with the place a command's document holds it, read through the real CLI.
  A view that renames keys is compared value by value with the part of the document it was
  built from.
- **The tables themselves.** All 23 view classes in `genetics.web.views` and
  `genetics.web.polygenic` must be accounted for, field for field, and every property of
  every class must be listed.

A failure names the page, the card and the field. It never quotes a compared value, because
a run is raw DNA (AGENTS.md §1.1).

### What is display

A value is declared display, with its reason, when it is not about the run's analysis:

- an address the dashboard builds (`run_url`, a card's `url`, a page's own URL);
- paging (`clinvar_page`, `pgx_pages`), since the command prints every row;
- a label for a saved value (a confidence input's name, a tier's title and blurb);
- chart geometry for a polygenic card, drawn from `computation.result.distribution` and
  `computation.result.position`, which `runs card --json` holds;
- the reader's own arrangement: grouping, sort and filters. The grid is checked to hold
  only the run's cards, each once, with counts that are counts of them;
- the sentence a page gives when a run or a card cannot be opened. The command reports the
  same failure as an error document with a kind.

Links are compared by what they point to: a benchmark link must end in the DOI the saved
record gives for that variation, and the ACMG policy link in the DOI the saved roster cites.

### What the check cannot see

- **A property's arithmetic.** A view's properties word, label, count or arrange what the
  object already holds, and all 66 are listed in `parity.PROPERTIES`. A new one fails until
  it is added, which puts it in front of a reviewer. Nothing checks what a property
  computes. An analysis written inside a property or a template, from saved fields and no
  engine function, is found only by reading the diff. AGENTS.md §3 is the rule: it belongs
  in the engine.
- **The other direction.** The check is that the dashboard shows nothing the CLI lacks. It
  does not look for what the CLI prints and no page shows. One case is known: a card's
  `ancestry_comparison` is printed by `runs show` and `runs card` and is on no page.
- **Text output.** Only `--json` is compared.
- **The real imputed run.** Every run checked is synthetic.

### Decisions

No owner question was asked. The M13.5 entry contract listed four open points, and each
follows something already settled:

- **Reachable is checked against routes, engine calls and values, not one of them.** A
  route list alone passes when a page gains a figure. A value comparison alone passes when
  a route is added and never requested. The call list is the direct form of AGENTS.md §3's
  sentence about a computation reachable only from the UI.
- **All five record commands are described.** The route table names each as the way to
  reach a page or a banner value, and AGENTS.md §3 says an agent's documents start with a
  `schema` tag. Their records stay open below the top level, as `runs.show` already
  describes the same records, because each carries its own `schema_version`.
- **JSON reachability is enough.** AGENTS.md §0 states the CLI's contract as JSON.
- **It runs in CI as part of the suite.** `ci.yml` runs `pytest -q`, and
  `genetics ci-local` runs the same steps. `tests/test_parity.py` needs no native tool and
  no reference, so it runs on every job of the matrix.

### What the check found

- **`hla calls --json` did not say whether HLA-linked cards were recorded.** The HLA page
  and the command's text both tell a run saved before those cards existed from a run that
  holds none. The JSON gave neither the cards nor that fact. It now gives
  `linked_cards_status` and `linked_cards`, built by `reads.hla_view`, which the text
  output reads too.
- **The bundle format the footer shows was in no command.** `version --json` gives it.
- **`pgx calls`' `current_context` had no `"context": "current"`** of its own, only inside
  `section_framing`. It has one now, as in every other run-scoped document.
- **One engine function was called by the dashboard alone**, `phase_coverage_text`. It
  words saved coverage figures and is exempt with that reason.

No page showed a value that was missing from every command.

### Changed for a caller

`runs clinvar`, `runs secondary`, `runs imputation`, `pgx calls` and `hla calls` print five
more top-level keys under `--json`: `schema` first, then `path`, `format_version` and
`created_at` beside `run_id`, which `pgx calls` and `hla calls` did not have. `hla calls`
adds `linked_cards_status` and `linked_cards`. `pgx calls` adds `current_context.context`.
`version --json` adds `bundle_format_version`. Every tagged document says `"version": 5`.
No key was removed or renamed, and no text output changed. No bundle format, knowledge
schema, card or saved file changed.

### Validation

`tests/test_parity.py` holds 34 tests. Four run the structural checks on the code as it
is, one of them against this page's table. Eight break a structural rule on purpose (a
route, a command, an engine call, an exemption, a field, a property, a view class, an
import inside a function body) and check that the failure names it. Two run every page of
a saved run built from 103 committed cards matched against an invented table, beside a
damaged run and an interrupted save: 121 pages against 121 command documents, more than
5,000 values. Seventeen then change one thing on one side only (a card's gene, a variant's
position, a key dropped from `runs card`, the banner's call rate, a section count, a
section's pointers, the unknown-section list, a selector row, the engine version,
`/healthz`, a context key or a view field or a template removed from its table) and check
that the run fails at that place. Two of them check that the message does not quote the
changed value. Three test the comparisons themselves and the refusal of a run that is not
in a `runs` directory.

The same check runs, through the `parity_check` fixture, on the saved runs other suites
build: completed PGx calls and their historical form (`tests/refs/test_pgx.py`), the CYP2D6
limitation in six stage and card combinations, guideline cards, HLA calls and a run saved
before HLA evidence (`tests/hla/test_calling.py`), eight HLA-linked cards
(`tests/hla/test_hla_cards.py`), a placed polygenic score
(`tests/refs/test_pgs_cards.py`), and a ClinVar lookup with and without a frequency
screen, with 101 ACMG overlaps over two pages and with none (`tests/health`). The fixture
also checks every document each run reads against the agent schema. On the guideline run
the bundle's bytes are compared before and after: reading every page and every command
changes nothing.

Thirty-one guards were each removed in turn: the tag and the envelope on each record
command, the scan on `runs imputation`, the two rules behind `linked_cards`, the ACMG
filter, `current_context.context`, `bundle_format_version`, the schema edited under
version 5, and sixteen inside the check itself (a field compared, a context value
compared, the shell compared, `/healthz` compared, each "not placed" failure, each
structural rule, imports read inside function bodies, the pointers compared, and the value
kept out of the message). Thirty removals failed a test. An unplaced view field passing a
run check did not, because only the structural check covered it; a test now does.
The full native suite passes **4,273 tests with nine skips** in 874 s: the five existing Windows skips and the four published-classifier HIBAG tests. Strict mypy on all four Windows/Linux x Python 3.11/3.13 targets (257 files),
full dbSNP card lint, ruff, format and the fixture check pass.

## Validation

`tests/test_cli_agent_reads.py` builds a saved run from six committed cards matched against an
invented table and checks each command's shape, ordering, pointers, errors and reasons. It
also checks that the card projection carries every `StoredCard` field. Section frames and
pointers are checked against the dashboard's `views` for all thirteen sections. The four new
reads run as subprocesses with a cp1252 stdout. Each guard was removed in turn, and each
removal failed the test written for it: both scans on both scanned commands, report order,
the projection, the PGx notice, `pointed_from`, `in_run`, `--section` JSON, and the warning
list. The full native suite passes 4,029 tests with the existing nine skips, and 4,032 after
the [session diff review](review_m131_session.md), which fixed the text form's confidence for
computed, polygenic and guideline cards.

None of these commands has been run on the real imputed run. That run's first read after this
source change repeats its deep checks (about 54 minutes); later reads take about 13 seconds.

## Left to later items

- **M13.2** (done 2026-11-11) versions and documents these shapes as
  [the agent schema](agent_schema.md).
- **M13.3** (done 2026-11-12) is `cards search` and `runs search`, described under
  [Search](#search-m133).
- **M13.4** (done 2026-11-12) is `current_context.confidence` on `runs card`, described under
  [Confidence](#confidence-m134).
- **M13.5** (done 2026-11-13) is the parity check, described under
  [Parity with the dashboard](#parity-m135).
- **M13.6** the worked review example; **M13.7** the outbound-query lint.
- **M14** the dashboard does not show a card's `ancestry_comparison`, which `runs show` and
  `runs card` print. A page added in M14 needs a row in `parity.PAGES`, and a new view field
  a place in its table; the tests say which.
