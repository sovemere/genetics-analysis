# Agent read commands (M13.1, M13.3, M13.4)

Implemented 2026-11-10. Four commands let an agent read one card, one section, a run's QC
record, or a card's evidence without printing a whole bundle. On the real imputed run
`runs show --json` prints about 1 GB. M13.3 (2026-11-12) added two search commands, so an
agent can find a card without knowing its id. M13.4 (2026-11-12) made `runs card` say what
decided a card's confidence tier, in one shape for every kind of card; see
[Confidence](#confidence-m134).

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
with no tier says "Not scored" and why.
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
`engine/confidence.py`). If the replayed tier differs from the saved one, or the weights do
not sum to the saved score within 0.00015, the basis is `not_reproduced`. A run saved under
other weights or thresholds therefore gets no explanation, not a wrong one.

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
- **M13.5** the parity test over every dashboard route. `SAVED_RECORDS` and the section-frame
  test are a start, not that test.
- **M13.6** the worked review example; **M13.7** the outbound-query lint.
