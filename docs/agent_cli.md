# Agent read commands (M13.1, M13.3, M13.4, M13.5, M13.7, M14.2, M14.3, M14.4, M14.5)

Implemented 2026-11-10. Four commands let an agent read one card, one section, a run's QC
record, or a card's evidence without printing a whole bundle. On the real imputed run
`runs show --json` prints about 1 GB. M13.3 (2026-11-12) added two search commands, so an
agent can find a card without knowing its id. M13.4 (2026-11-12) made `runs card` say what
decided a card's confidence tier, in one shape for every kind of card; see
[Confidence](#confidence-m134). M13.5 (2026-11-13) added a test that every analysis a
dashboard page shows is in a command's JSON, and described the five commands that print a
run's other saved records; see [Parity with the dashboard](#parity-m135). M13.7
(2026-11-19) added `cards check-query`, which says whether a query may leave the machine;
see [Query check](#query-check-m137). M14.2 (2026-11-19) added `runs ancestry`, the ancestry
page's command; see [Ancestry](#ancestry-m142). M14.3 (2026-11-19) added `cards guide`, the
reading guide and confidence legend; see [Reading guide](#reading-guide-m143). M14.4
(2026-11-19) gave the dashboard a search page, which calls what `runs search` prints; see
[Dashboard search](#dashboard-search-m144).

| Command | Reads | Holds a genotype | Scanned |
|---|---|---|---|
| `genetics runs show <run> --section S [--section T] [--json]` | saved run | yes | no |
| `genetics runs card <run> <card-id> [--json]` | saved run | yes | no |
| `genetics runs qc <run> [--json]` | saved run | no | both branches |
| `genetics cards evidence <card-id> [--json]` | knowledge pack | no | both branches |
| `genetics cards search <query> [--limit N] [--json]` (M13.3) | knowledge pack | no | both branches |
| `genetics runs search <run> <query> [--limit N] [--json]` (M13.3) | saved run | yes | no |
| `genetics cards check-query <query> [--card ID] [--json]` (M13.7) | knowledge pack | no | both branches |
| `genetics cards guide [--json]` (M14.3) | knowledge pack, confidence engine | no | both branches |

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
                         empty_reason, related, assay_limits, saved_records,
                         section_framing (pharmacogenomics only),
                         carrier_scope (reproductive only)}
```

Section names are the thirteen `Section` values, case-insensitive. An unknown name exits 2
with `error.kind: unknown-section` and lists the thirteen. A section with no cards is still
reported, with the dashboard's reason. Since M14.1 that reason is one of three sentences
from `reads.empty_reason`: the run holds no card here (saved with a pack that held none;
the current pack's count is given), the cards here produced no interpretation (each
status counted, and each distinct `not_run` reason quoted, up to three), or `null` when the
section has a finding. "Not built yet — roadmap M…" is gone: every section has cards in the
pack. `saved_records` names the commands for records beyond
the cards, which the dashboard links as pages: `runs clinvar` and `runs secondary` for physical
health, `pgx calls` for pharmacogenomics, and `hla calls` for immunogenetics. The PGx notice appears once, in its section, and is not repeated per card
(see [PGx framing](pgx_framing.md)). `assay_limits` (agent schema 10) lists what the array
cannot determine in the section; see [Assay limits in their sections](#assay-limits-in-their-sections-m146).

### `runs qc`

```text
run_id, path, format_version, created_at
qc                              the saved QC report (qc.run.json)
imputation                      the saved execution record, or null
imputation_provenance_status    "recorded", another status, or null; the full record is
                                `genetics runs imputation <run>`
provenance                      engine version, knowledge digest, reference and tool versions,
                                input vendor and marker count
current_context                 (M14.5, agent schema 9)
  context                       "current"
  coverage                      polygenic[], polygenic_counts, clinvar_status,
                                clinvar_reason, clinvar
```

The text form lists every QC warning in QC's order. A field another version did not write
prints as `-`. `current_context.coverage` is described under
[QC and provenance page](#qc-and-provenance-page-m145).

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

A query that holds a call is refused before anything is searched, with `error.kind:
genotype-in-query` and exit 2. The message does not repeat the query. Search for the
variant, gene or trait (AGENTS.md §1.3). Both commands refuse it, so that the habit is the
same in each. A call is what the outbound lint's three `call` rules find
(`genetics.outbound.reads_as_call`): the privacy scanner's shapes, and since M13.7 an rsID
beside two alleles and a diplotype. A result told in words ("homozygous", "one copy") is
searched, since nothing a search reads leaves the machine; `cards check-query` refuses it
before a web search. See [Query check](#query-check-m137).

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

### For M14.4 (done)

The dashboard's search calls `genetics.run.reads.search_view(bundle, query)`, which is what
`runs search` prints, and `genetics.engine.search.parse_query` for the query. The parity
test compares the two directly; see [Dashboard search](#dashboard-search-m144).

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
| `/guide` | How to read the results: the confidence legend, how a tier is decided, the rarity inversion, what a polygenic score can say and the array's limits (M14.3). Holds no run | `genetics cards guide --json` |
| `/runs/{run_id}` | The run selector, the QC banner, the thirteen sections, every card's face | `genetics runs list --json`, `genetics runs qc <run> --json`, `genetics runs imputation <run> --json`, `genetics runs show <run> --section <section> --json`, `genetics runs show <run> --json`, `genetics runs card <run> <card-id> --json`, `genetics pgx calls <run> --json` |
| `/runs/{run_id}/cards/{card_id}` | One card in full, with what decided its tier | `genetics runs card <run> <card-id> --json` |
| `/runs/{run_id}/clinvar` | The saved ClinVar reference lookup | `genetics runs clinvar <run> --json` |
| `/runs/{run_id}/secondary-findings` | The lookup's ACMG gene-list overlaps | `genetics runs secondary <run> --json` |
| `/runs/{run_id}/qc` | The QC report, the run's coverage (each polygenic score's before and after imputation, and ClinVar's), the imputation parameters and region jobs, and the reference, tool and knowledge-pack versions (M14.5) | `genetics runs qc <run> --json`, `genetics runs imputation <run> --json` |
| `/runs/{run_id}/ancestry` | The PCA scatter, the nearest reference populations, ancient affinity and both haplogroups with their marker counts (M14.2) | `genetics runs ancestry <run> --json` |
| `/runs/{run_id}/search` | The run's cards that match a query, ranked as `runs search` ranks them, each with its saved face; a query that reads as a genotype is refused in the command's words (M14.4) | `genetics runs search <run> <query> --json` |
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
  exists and takes `--json` and each other option it is written with.
- **Engine calls.** Every engine function a `genetics.web` module calls, at module level or
  inside a route, is one a `genetics.cli` module or the read side (`run/reads.py`,
  `run/explain.py`, `pgx/presentation.py`) calls too. Two are exempt, each with its reason
  in `parity.DISPLAY_ONLY`: `phase_coverage_text`, which words a polygenic card's saved
  before-and-after coverage, and `run_signature`, the key for keeping one opened run in
  memory. A relative import or a bare `import genetics.x` cannot be followed and fails.
- **Values.** For a saved run, every page is rendered through the real app and what it
  hands its template is recorded: each context key, each of the twenty fields of `Shell`,
  each of the 32 fields of every card's `CardView`, and the polygenic view a card draws.
  Each is compared with the place a command's document holds it, read through the real CLI.
  A view held inside a card (variant, evidence, effect, frequency, citation, carrier,
  confidence) is compared field for field with the key of the saved record it is read
  from (`parity.READ`), and the six rows of the confidence table with the saved inputs
  and scores they show (`parity.CONFIDENCE_ROWS`). The run page's shell is compared with
  the commands; every other page's shell has to equal it.
- **The tables themselves.** All 24 view classes in `genetics.web.views` and
  `genetics.web.polygenic` must be accounted for, field for field, and every property of
  every class must be listed.
- **The comparison.** `parity.unnoticed` changes every value of every card view a run
  shows, one at a time, and lists each change the comparison lets pass. The `parity_check`
  fixture fails on any outside `parity.UNNOTICED`, which holds one: a confidence row's
  label.

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
  only the run's cards, each once, with counts that are counts of them, and each section
  panel's pointers and assay limits are compared with `runs show --section`'s `related`
  and `assay_limits` (M14.6);
- the sentence a page gives when a run or a card cannot be opened. The command reports the
  same failure as an error document with a kind;
- the sentence the search page gives for a refused query (M14.4). `check_run` compares it
  with the message of the error document `runs search` prints for the same query, and
  fails if the query's rsID appears anywhere on the page.

Links are compared by what they point to: a benchmark link must end in the DOI the saved
record gives for that variation, and the ACMG policy link in the DOI the saved roster cites.

### What the check cannot see

- **A property's arithmetic.** A view's properties word, label, count or arrange what the
  object already holds, and all 67 are listed in `parity.PROPERTIES`. A new one fails until
  it is added, which puts it in front of a reviewer. Nothing checks what a property
  computes. An analysis written inside a property or a template, from saved fields and no
  engine function, is found only by reading the diff. AGENTS.md §3 is the rule: it belongs
  in the engine.
- **The other direction.** The check is that the dashboard shows nothing the CLI lacks. It
  does not look for what the CLI prints and no page shows. One case is known: a card's
  `ancestry_comparison` is printed by `runs show` and `runs card` and is on no page.
- **A method.** The call list follows imported functions. A method called on an object
  the page already holds is not seen. The engine classes the dashboard imports are enums,
  errors, `RunBundle` and the listing rows, and none of them computes a result.
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

The [session diff review](review_m135_session.md) changed every value of every card view
once and found that a figure changed to another figure in the same record passed: the
nested views and eleven fields of the polygenic view were compared by whether each value
appeared anywhere in the record. On the run with a placed score, 38 of 170 changes to
the polygenic view passed, among them weight coverage and imputation quality, and so did
a changed within-family attenuation. Those views are now compared field for field. The
review also found `ancestry_matched` and a confidence row's saved input declared display
and uncompared, and every page's shell but the run page's assumed equal and unchecked;
all three are compared now. `tests/test_parity.py` holds 43 tests, the probe is one of
them, and the `parity_check` fixture runs it on every run a suite hands it. Nineteen more
guards were removed in turn, each caught. No command's output and no schema shape
changed. The full native suite passes 4,282 tests with the existing nine skips.

## Ancestry (M14.2)

`genetics runs ancestry <run> [--json]` prints a run's ancestry record and the scatter the
dashboard's ancestry page draws from it. It states an inference about the reader and is
not scanned, like `runs card`.

```text
run_id, path, format_version, created_at
ancestry                the saved record, whole: population, mt, y, ancient, and from
                        format 18 reference_population; null before format 3
current_context
  context               "current"
  pca                   status, drawn, why_not, axes, units, sample, references[],
                        regions, bounds
```

**The scatter is drawn against the run's own reference.** From bundle format 29 (M14.2) a
placement records the model's `scale` and each fit its population's `centroid`, in the
pooled within-population standard deviations distance is measured in. `pca.sample` is the
saved coordinates divided by the scale, and each reference's `point` is its centroid; the
distance between them is the fit's `distance` on the first two of all components. Reading
the reference installed today would draw a months-old run against a panel it was not placed
in, so a run saved before format 29 is not drawn: `pca.why_not` says so, and its fits are
still listed by rank.

**The page shows three marks, and no colour for regions.** The dataviz rule for a scatter
is at most three categorical hues, and the panel has a dozen regions. Reference populations
are neutral rings, the five nearest are filled, and the run is a cross in a ring; a
population's name and region are in its hover text and the table. Only the nearest
population and the run are labelled on the plot.

**Haplogroups carry both marker counts** (AGENTS.md §4.7): the markers that support the
call, and how many of this array's markers sit on a defining site at all. Ancient affinity
is listed by distance and called affinity, not ancestry proportions.

## Reading guide (M14.3)

`genetics cards guide [--json]` prints how to read a run's results. The dashboard's `/guide`
page shows the same document, and every page's nav shows its `legend`: the six badges a
card can carry, each linking to its row in the guide. It reads the knowledge pack and the
confidence engine, no run, and its output is scanned on both branches.

```text
legend[]      key, label, blurb, min_score, earned_by: the five tiers strongest first, then
              `untiered`. The labels and blurbs are the dashboard's badges and grid headings
reading       title, paragraphs, statuses[]: how to read a card, and each status badge
confidence    title, paragraphs, inputs[] (the six rows and their weights), bands[],
              evidence_components[], replication_components[], ceilings[]
rarity        title, paragraphs, frequency_components[], unknown_frequency_component,
              rare_call_band, benchmarks[]: the rarity inversion (AGENTS.md §4.1)
polygenic     title, paragraphs, cards[]: coverage, portability, within-family attenuation
              and what a position in a distribution says, with every polygenic card in
              the pack, its study ancestry and whether it has its own within-family figure
array         title, paragraphs, limits[], not_determinable[]: the array's limits, and every
              impossibility card in the pack with the section it sits in (AGENTS.md §3.2)
sources[]     type, id, title, url, supports: the papers the paragraphs quote, and the
              figures read from each
```

**No threshold is written twice.** The weights, bands, evidence and replication components,
frequency components and quality and share bounds are tables in `engine/confidence.py` that
the calculators read, and the guide reads the same tables. The ceilings are listed by
calling `single_call_ceilings` and `polygenic_ceilings` with inputs that meet one rule each,
so `ceilings[].rule` is the sentence `runs card` gives in
`current_context.confidence.ceilings[].rule`. A test runs both functions over a grid of
inputs and fails on any ceiling the guide does not list. The two benchmarks are
`engine.ppv.benchmark`, which a ClinVar record's reliability block also comes from.

**What is authored is prose and the figures it quotes.** Each figure is in `sources[].supports`
with the paper it was read from. The figures were read from the PubMed abstracts on
2026-11-19: Weedon et al. 2021 (doi:10.1136/bmj.n214) for 16% of 4,757 rare heterozygous calls,
4.2% for BRCA1/BRCA2 and 20 of 21 Personal Genome Project participants; Tandy-Connor et al.
2018 (doi:10.1038/gim.2018.38) for 40% of variants from 49 patients' raw data; Okbay et al. 2022
(doi:10.1038/s41588-022-01016-z) for 12-16% of variance and direct effects roughly half the
association; and Ding et al. 2023 (doi:10.1038/s41586-023-06079-4) for the -0.95 correlation
and 14% lower accuracy in the farthest decile of genetic distance. Counts of the pack's own
cards (polygenic cards trained in European-ancestry cohorts alone, cards with a within-family
figure) are computed when the guide is built.

### Decisions

- **One page, and a legend on every page.** The legend is in the nav of every page that has
  one, because a reader meets a badge on the run page, not on the guide. Each badge links to
  its row in the guide. It is not on the card faces: a face was one link, to the card, and a
  link inside a link is not valid HTML. Since M14.7 the face's title is the link, stretched
  over the face, so a badge link would sit under it and still not take a click. The grid's tier headings and the card page's
  "Why this tier" link into the guide too.
- **Under `cards`.** It reads the pack and no run, which is what `cards` means (M13.1).
- **The tier labels moved** from `web.views` to `genetics.run.guide`, so the command prints
  the words the badges show. `views._TIER_LABELS` and `views.NO_TIER` are the same objects.
- **The guide page lists runs and opens none.** Its shell is built from the run listing
  alone, so it costs a directory listing and never a bundle read. The run selector shows
  "Open a saved run" when no run is selected.
- **The card page is unchanged** beyond its link: it prints the sentence and the six rows
  M13.4 gave it, and the weights and the ceiling list are on the guide.

<a id="dashboard-search-m144"></a>

## Dashboard search (M14.4)

Every page of an open run has a search box at the top of its nav. It opens
`/runs/{run_id}/search?q=<query>`, which lists the run's cards that match, best first, each
as the face the grid shows: tier badge, status, summary, and a line saying which of the
query's words it matched in which fields. The page holds what
`genetics runs search <run> <query> --json` prints, with no `--limit`: the same cards in the
same order, from the same function (`reads.search_view`), and the parity test compares them
field for field.

- **Every section is searched, whatever the grid's filters say.** Search finds cards; a tier
  filter arranges the grid. No card is ranked or left out for its tier or status (AGENTS.md
  §0.1A), and a card matching some of the words is listed under "Matching some of the
  words", below every card that matches all of them.
- **A refused query is not shown again.** A query that reads as a genotype is refused by
  `parse_query` before anything is searched, as `runs search` refuses it. The page shows the
  engine's sentence, which names the rule and not the text, leaves the box empty, and its
  title never holds a query. The command exits 2 with kind `genotype-in-query`; the page
  answers 200, as every other page that explains why it shows nothing does. A query of
  punctuation alone gets the `empty-query` sentence the same way.
- **A searched query is shown** in the box and the heading. It is the reader's own words and
  passed the same check. It is in the address too, because the form is a plain GET that
  works without JavaScript, can be bookmarked and comes back with the back button; the
  `Referrer-Policy: no-referrer` header keeps it out of any request a citation link causes.
- **The grid's arrangement rides along.** The box carries the grid's group, sort and filters
  as hidden fields, so a card opened from the results and "Back to the run" keep them. They
  do not narrow the search.
- **No box on a page with no run open** (the guide, an empty store). There is nothing to
  search, and the knowledge pack has `genetics cards search`; a pack card has no page here to
  link to.

## QC and provenance page (M14.5)

`/runs/{run_id}/qc`, linked from the nav of every run page, shows two documents whole:
what `genetics runs qc <run> --json` prints and what `genetics runs imputation <run> --json`
prints. The parity check compares each with its command, key for key. Both commands scan
their output for genotypes, and the route scans the whole page too.

- **The export:** every field of the QC report, the call rate by chromosome, the sex
  inference's evidence and notes, the build check's anchors, and every warning in QC's order.
- **Coverage** is `current_context.coverage` on `runs qc` (agent schema 9), collected from
  the two records that hold coverage, each with its own denominator and never combined:

  ```text
  polygenic[]           every polygenic card in saved order, placed or not: card_id, title,
                        section, status, confidence_tier, pgs_id, trait, placed, phase,
                        phase_coverage {before, after}, comparable_weight_fraction, reason
  polygenic_counts      scores, placed, with_phase_coverage
  clinvar_status        "recorded"; "no-lookup"; "lookup-not-run" (the lookup did not run);
                        or "not-recorded" (a lookup that ran, saved before format 13)
  clinvar_reason        the lookup's reason when it did not run, else null
  clinvar               the saved ClinVar coverage record (M7.6), whole, or null
  ```

  `phase_coverage` is what the card's result saved: for the original array and after
  imputation, the variants the data could dose and the share of the score's weight they
  carry (AGENTS.md §4.3). A score that was never computed, or a result saved under display
  schema 1, has none, and the page says so. Nothing is recounted.
- **Imputation:** the execution record (mode, status, card input, jobs, records, sources,
  unsupported positions), then the full provenance: panel and map sources, Beagle, Java and
  bref versions, the requested parameters, a row per region (status, ploidy, typed
  positions and their outcomes) and a row per job (interval, ploidy, seed, threads, heap,
  and each Beagle run's elapsed time). A full run has about 25 regions, so nothing is paged.
  Each region's position-level `decisions`, and every input, output and tool digest, stay in
  the command's document.
- **References, tools and knowledge pack:** what the manifest recorded as installed at save
  time, with each reference's licence and each tool's digest. The imputation stage records
  what it used, which can differ after an install changes; the page says so.

## Assay limits in their sections (M14.6)

The twelve impossibility cards (AGENTS.md §3.2) have sat in the section each qualifies since
M3.7. M14.6 keeps them there, and visible, whatever the reader does to the grid.

**What was wrong.** Three arrangements took a limit away from the findings it qualifies:

- **Sorted by tier**, the default, a card with no tier goes last. An assay limit has no
  tier, so the SMN1 card sat beneath every marker-absent carrier card, looking like one more
  card that did not match.
- **Grouped by tier**, all twelve went to the untiered panel, mixed in with the cards that
  did not match.
- **Filtered** by tier, by section or to "only cards with an interpretation", a limit was
  hidden and counted (M4.7), while its section's findings stayed on screen. That left the
  carrier section reading as complete, which is the failure M3.7 placed the cards to stop.

**What changed.**

- **Each section names its limits at its head**, after the blurb and before any card:
  "Not determinable from this array:" and a link to each limit card. The line is drawn
  whatever the filter, as M10.3 keeps the CYP2D6 limitation beside the PGx calls. It points
  to the cards and does not copy them, so a filter still hides a limit card and counts it.
- **The cards render as their own block** below the section's findings, under "What this
  array cannot determine", whatever the sort. Grouped by tier, the untiered panel has the
  same block below its unmatched cards, and each card names its section.
- **`runs show --section` prints the same list** as `current_context.sections[].assay_limits`
  (agent schema 10), from `reads.assay_limits`, and its text form prints the line. Each
  entry is `{card_id, in_run, title}`.
- **A limit the run does not hold is still named.** The list is the run's own limit cards in
  this section, in saved order, then the current pack's limit cards for the section that the
  run does not hold, with `in_run: false`. A limit is about the array, so one written after
  a run was saved is still true of that run. The dashboard names it without a link, and the
  text form names `genetics cards evidence <card-id>`, which prints the pack's card.

**Decisions.**

- **Pointers at the head, not the cards themselves.** Moving the cards to the top of a
  section would put five assay limits ahead of physical health's findings. A line of links
  is enough to say the section is incomplete, and the cards stay where the reader expects
  detail.
- **The filters stay as they are.** M4.7's rule is that a filter hides a card and counts it;
  the line at the head is what keeps a limit stated, so no filter needed an exception.
- **No new grouping.** Grouped by tier, the limits stay in the untiered panel, where
  `?tier=untiered` finds them, so URLs and filter counts are unchanged. The block sets them
  apart within it.
- **The register was compared with the cards.** `tests/engine/test_impossibilities.py`
  reads AGENTS.md §3.2 and the pack and holds them equal both ways: eight bullets, twelve
  cards (the copy-number bullet names four findings and gets five). None is missing.

**Parity.** `CardGroup.limits` holds `LimitLink`s. `_check_grid` compares each section
panel's limits with `runs show --section`'s `assay_limits` (id, title, and whether there is
a link) and fails a tier group that has any. `CardGroup.findings` and `limit_cards` are
properties that split the shown cards; they are listed in `parity.PROPERTIES`.

<a id="accessibility-m147"></a>

## Accessibility (M14.7)

M14.7 changes how the dashboard's pages are marked up and styled, not what they show: no
command, view field, context key, agent schema, bundle format or card changed, and the
parity tables are untouched. It is recorded here because the dashboard is the CLI's other
front-end, and an agent reading a page's markup meets these choices.

**What was checked, and how.** `genetics.testing.accessibility.audit` parses a rendered page
with the standard library and lists what it finds: duplicate ids; an `aria-labelledby`,
`aria-describedby` or label `for` that points nowhere; a positive `tabindex`; something
focusable inside a `role="img"` or `aria-hidden` subtree; a link or button with no name; a
control with no label; a `role="img"` with no name; and, on a page, no `lang` or title, other
than one `h1` in `main`, a skipped heading level, or two landmarks of one role that a screen
reader cannot tell apart. `tests/web/test_accessibility.py` runs it on every page of a run
holding the whole pack less its HLA and guideline cards, on every card's page and dialog,
and on a page per rule that should fail. The drawn ancestry scatter is audited by
`tests/web/test_ancestry_page.py`, since only that suite saves a placement. Contrast is
computed from `app.css`'s colour tokens with WCAG's formula, in the light theme and both
copies of the dark one.

**What was wrong, and what changed.**

- **A card face was one link.** Its accessible name was the whole face (badge, summary,
  chart, every caution), read in full at every Tab. The title is now the link, inside the
  face's heading; its description is the tier badge (`aria-describedby`); `.cardlink::after`
  stretches it over the face, so a click anywhere still opens the card, and the focus ring
  is drawn round the face. The face's layout is on `.cardface`, not `.card`, which the
  ClinVar sections and the PGx gene faces also wear. The ids come from
  `views.domid(card.url)`, since a card id is authored text and need not be a valid id.
- **Arrow keys left the page.** An arrow press on a closed select changes its value and
  fires `change`, so the run selector navigated, and the group and sort selects reloaded
  the page, at the first press (WCAG 3.2.2). A pointer's choice still acts at once; from the
  keyboard, Enter acts, and the run selector has an Open button (shown with scripting) as
  the controls have Apply. `keyedSelect()` in `app.js` holds the rule for both.
- **Form controls had no visible edge.** Their borders used `--line`, a divider at about
  1.3:1. A new token, `--control-line`, is 3.6:1 or more on every surface in both themes
  (WCAG 1.4.11), and placeholder text uses `--muted`. Every text colour already met 4.5:1;
  the test now holds it.
- **Two identical search landmarks** on the search page (M14.4's hand-over). The nav's box
  stays on every page of an open run, but on the search page only the page's own box is a
  search landmark; elsewhere the nav's is, named by its label.
- **Names that said less than the screen.** The theme toggle's `aria-label` ("Colour
  theme") hid which theme was on and was a name a speech-input user could not say (WCAG
  2.5.3); it is now named by what it shows. Counts such as "3/10" are read as "3 of 10
  card(s) interpreted". The dialog's close button is "Close card".
- **Structure.** The dashboard and the card page gained an `h1` (visually hidden: the run
  bar says what the page is), the guide's nav is named "On this page" rather than
  "Sections", the nav marks the page it is on with `aria-current`, and the skip link's
  target takes focus.
- **The ancestry scatter was a `role="img"`** holding six focusable points, which an image
  makes nameless. It is a `group` named by its caption; the six points are images named by
  their hover text, and the unfocusable rings are hidden, since the table holds them.
- **The `empty-query` sentence's backticks** (M14.4's hand-over) are shown as code by the
  `codespans` filter. The template is handed the engine's sentence unchanged, so the parity
  check still compares it with the error `runs search` prints.

**Decisions.**

- **The title, not the face, is the link.** The usual fix for a block link. The cost: the
  stretched link lies over the face, so the compact chart's hover text no longer shows on a
  face, and face text cannot be selected with the mouse; the card's own page has both.
- **Keyboard, not timing.** A delay before a select acts would still act on an arrow press
  that paused; the keyed flag acts on intent.
- **No screen-reader run.** The audit checks the markup a screen reader reads; nothing here
  was tried with NVDA or Narrator. Looked at in Chrome on a synthetic run: the focus ring,
  arrow and Enter on the sort select, Enter and Escape on a card, and the control edges in
  both themes.

## Query check (M13.7)

`genetics cards check-query <query> [--card ID ...] [--json]` is the last step before a
query leaves the machine (AGENTS.md §1.3). The engine builds no web search; an agent
writes its own, and this is what it runs them through. The rules, what each finds and the
worked example are in [the walk-through](agent_usage.md#7-search-further).

```text
status       refused, unsourced or clean; exit 1 for refused, 0 otherwise
length       characters checked (NFKC, whitespace folded); problems count in it
problems[]   rule, kind (call or result), start, end, advice
cards        the --card ids
unsourced    query words the cards' evidence does not print; null without --card,
             and null when refused
```

**It never prints the query.** A problem carries the rule and the character span, as the
privacy scanner's `Hit` does, and advice that quotes nothing. A refused query's words are
not listed as unsourced, since they may hold the call. The output is scanned like the
other pack reads.

**Shapes and sources.** The rules match shapes, and favour recall over precision, the
opposite of the file scanner: a query is rewritten in a second, and a file scanner that
cries wolf gets bypassed. A haplogroup, an HLA type or a tier word has no shape, so
`--card` adds a check of sources: each word the named cards' `cards evidence` does not
print is listed. That is advice, not refusal, because a word read in a cited paper is a
fair word to search and only the agent knows which papers it read.

**Every request the engine makes is checked too.** `genetics.outbound.check_url` runs on
each URL the fetcher opens or probes, and `tests/privacy/test_outbound.py` reads the source
for every call that builds or opens a request and fails one without it. The fetcher is the
only network path; the dashboard's listening socket sends nothing.

### Decisions

- **A command, not only a test.** The roadmap asked for "a lint/test for genotype strings
  in outbound query construction", and the engine constructs no query. An agent writes
  them, so the lint has to be something an agent can run. The tests hold the command, the
  fetcher's URLs, and the walk-through's example queries to it.
- **Under `cards`.** It reads the pack and nothing of a run, which is what `cards` means
  (M13.1). The verdict is a payload, `cards.check-query`, not an error document: the
  check ran. Exit 1 on `refused` lets a script stop on it without reading JSON.
- **The search commands refuse calls, not results.** "Homozygous" and "carrier" are words
  a reader may want to find cards by, and a local search sends nothing anywhere.
- **`C>T` passes; `C/T` does not.** dbSNP writes a variant's alleles with a slash, and so
  does a genotype. A change written with `>` is only ever a variant, so the advice names it.
- **A nucleotide never pairs with an indel code.** `AD` and `CD` are diseases far more
  often than an impossible genotype.

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
- **M13.6** (done 2026-11-15) is the review walk-through with the worked curly-hair
  example, [Reviewing a run as an agent](agent_usage.md). A test runs every command on it.
  The [session diff review](review_m136_session.md) found that its query check reads
  words and not meaning, so a result told in the card's own words passes; M13.7 inherits that.
- **M13.7** (done 2026-11-19) is `cards check-query`, described under
  [Query check](#query-check-m137). It closes the two queries M13.6 left open.
- **M14.6** (done 2026-11-20) is each section's assay limits, named at its head and in
  `runs show --section`'s `assay_limits`, described under
  [Assay limits in their sections](#assay-limits-in-their-sections-m146). Agent schema 10.
- **M14.5** (done 2026-11-20) is the QC and provenance page and `runs qc`'s coverage,
  described under [QC and provenance page](#qc-and-provenance-page-m145). Agent schema 9.
- **M14.4** (done 2026-11-19) is the dashboard's search page, described under
  [Dashboard search](#dashboard-search-m144). No command or schema changed.
- **M14.3** (done 2026-11-19) is `cards guide` and the `/guide` page, described under
  [Reading guide](#reading-guide-m143).
- **M14.2** (done 2026-11-19) is `runs ancestry` and the ancestry page, described under
  [Ancestry](#ancestry-m142).
- **M14** the dashboard does not show a card's `ancestry_comparison`, which `runs show` and
  `runs card` print. A page added in M14 needs a row in `parity.PAGES`, and a new view field
  a place in its table; the tests say which.
