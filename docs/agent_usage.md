# Reviewing a run as an agent (M13.6, M13.7)

Written 2026-11-15. This page is the walk-through for an agent asked to review a saved run:
which command to run at each step, which keys to read, what may be searched online, and
what an answer has to carry. It ends with the worked example from the project brief: *"it
says I'm predisposed to curly hair — review the cited information and give me 10
interesting facts"*.

It is a walk-through, not a reference. [The read commands](agent_cli.md) says what each
command prints, and [the agent schema](agent_schema.md) gives the field types, the error
document and the exit codes. Every command on this page is run by a test, and every
output shown is compared with what the command prints; see
[How this page is kept true](#how-this-page-is-kept-true).

## What may leave the machine

Read this before the first command. A run is one person's DNA ([AGENTS.md §1](../AGENTS.md)).

| Command | States the reader's results | Its output may go into a search, a fetch or a file |
|---|---|---|
| `genetics cards search <query>` | no | yes |
| `genetics cards evidence <card-id>` | no | yes |
| `genetics cards check-query <query>` | no | yes |
| `genetics schema`, `genetics version --json` | no | yes |
| `genetics runs list` | no, but it names the runs | no |
| `genetics runs qc <run>` | no genotype; it holds the inferred sex and call rates | no |
| `genetics runs card`, `runs show`, `runs search`, `runs clinvar`, `runs secondary`, `runs ancestry`, `pgx calls`, `hla calls` | yes | no |
| `genetics runs imputation <run> --dosages` | yes, the whole imputed genome | no, and a review never needs it |

Four rules follow.

- **Everything that leaves the machine is written from `cards` output.** A search query,
  a URL, a file, an issue, a commit message and a memory note are built from
  `cards search`, `cards evidence` and papers already read. Nothing in them comes from a
  `runs`, `pgx` or `hla` command: not the genotype, not the count of alleles, not the
  outcome, not the tier a call earned, not the run id, not the inferred sex or ancestry.
- **Write each query as if the result were unknown.** `rs7349332 WNT10A hair curl` is a
  question about a variant. The same words with the reader's alleles, or narrowed to
  "one copy", tell a search engine a result. If the reader's result makes one question
  more interesting than another, ask both.
- **Check each query before it is sent.** `genetics cards check-query <query> --card
  <card-id>` refuses a call written out and a result told in words, and exits 1. It also
  lists each word the card's evidence does not print. Such a word may be sent only if it
  came from a paper already read. See [step 7](#7-search-further).
- **Read the narrowest run command that answers the question.** An agent on a hosted model
  sends what it reads to that model's provider, and AGENTS.md §1.3 lists a prompt to a
  remote model among the places a genotype must not go. The owner asking a hosted agent
  to review a run is the owner's decision to send those cards there. It covers the cards
  the question is about. So read `runs card` for one card, or `runs show --section` for
  one section. Do not read `runs show --json` without a section (about 1 GB on an imputed
  run), the dosages, or the raw export, and do not open a run nobody asked about.

The answer itself goes to the reader, in the terminal. It states their result plainly.

## The steps

1. **Pick the run.** `genetics runs list --json`. Take the `run_id` the reader named, or
   the newest whose `status` is `readable`. After the engine's source has changed, the
   first read of a run repeats its deep checks, which takes about an hour for an imputed
   run; `genetics runs list --verify` does that once, ahead of time.
2. **Check the run.** `genetics runs qc <run> --json`. Read `qc.warnings`,
   `qc.call_rates.call_rate`, `qc.build.verdict` and `imputation.status`. A warning there
   belongs in the answer before any card does.
3. **Find the card.** `genetics cards search <query>` with the reader's own words. It
   needs no run and holds no genotype. Take every card that matches all the words, not
   only the first: one trait is often several cards.
4. **Read the result.** `genetics runs card <run> <card-id> --json` for each card. The
   keys to read are listed under [the worked example](#4-read-the-result).
5. **Read the claim without the result.** `genetics cards evidence <card-id> --json`. This
   is the card as the knowledge pack wrote it: variant, effect size, study population,
   sample size, replication, citations with links, caveats. It is what the next two steps
   work from.
6. **Read the cited papers.** Open each citation's `url`. For each paper check four
   things against the card: the variant and the allele the effect is counted on, the
   effect size and its units, the sample size and population, and whether a second paper
   really is an independent replication. Read the table the number comes from. An abstract
   often rounds it or leaves it out.
7. **Search further, if the question needs it.** Queries follow the rules above, and
   each passes `genetics cards check-query` before it is sent. A fact from a search
   result is a lead, not a source: open the paper and read it there.
8. **Answer.** See [What an answer carries](#what-an-answer-carries).

## What an answer carries

- **The result, as the card states it**, with its tier and what decided the tier
  (`current_context.confidence.reason`). A `likely-artifact` card is reported as one, with
  its benchmark figure. It is not left out and not softened (AGENTS.md §0.1A).
- **The effect size with its units, the study's population and its sample size.** "Slightly
  curlier" is the card's face; the answer gives the number behind it. For a risk, give the
  base rate and the absolute figure where the card has them (AGENTS.md §0.1B).
- **A source for every fact.** Each one names the paper and where in it: a table, a
  section. A fact the agent did not read in a source is not in the answer. Say which
  facts are the card's and which came from further reading.
- **Which facts are about the variant and which are about the reader.** Most are about the
  variant, and would be the same for anyone.
- **The card's caveats that bear on the question.** They are part of the finding.
- **What was not checked.** A paper that could not be opened, a supplementary table not
  read, a citation whose text does not show the card's figure.
- **No advice and no reassurance** the reader did not ask for (AGENTS.md §0.1B).

If a paper disagrees with the card, say so in the answer and give both figures. That is a
defect in the knowledge pack: report it to the owner with the card id, the citation and
the place in the paper. The report names the card and the paper, and needs nothing from
the run.

## Worked example: curly hair

The outputs below come from a run built for this page: five committed cards matched
against an invented table in which every marker holds one of each allele the card
declares. No export was read, and the result shown is nobody's. `<run>` stands for the
run id.

### 2. Check the run

<!-- keys: genetics runs qc <run> --json -->
| Key | Holds |
|---|---|
| `qc.warnings` | QC's warnings, in its order. Empty here |
| `qc.call_rates.call_rate` | The share of markers that were called |
| `qc.build.verdict` | Whether the coordinates were confirmed as GRCh37. `indeterminate` here: the example's invented positions land on none of the check's anchors |
| `qc.sex.inferred` | The inferred sex, which decides how X and Y calls are read |
| `imputation.status` | Whether imputation ran. `not_recorded` here; the example run imputed nothing |
| `provenance.knowledge.digest` | The knowledge pack the run's cards were written from |

None of this goes into a search or a file. It decides how much weight the cards can bear:
a low call rate or a build that was not confirmed is stated in the answer before any card.

### 3. Find the card

<!-- run: genetics cards search curly hair --limit 4 -->
```text
  traits           wnt10a_hair_curl                     WNT10A hair-curl association
      2 of 2 term(s), score 10.25; card_id: curly, hair; title: curly, hair; summary: curly, hair; detail: curly, hair; evidence: curly, hair; caveats: curly, hair; citations: hair
  traits           lce3e_region_hair_curl               LCE3E-region hair-curl association
      2 of 2 term(s), score 10.25; card_id: curly, hair; title: curly, hair; summary: curly, hair; detail: curly, hair; evidence: curly, hair; caveats: curly, hair; citations: hair
  traits           tchh_hair_morphology                 Hair straightness and curl
      2 of 2 term(s), score 9.75; card_id: hair; title: curly, hair; summary: hair; detail: curly, hair; caveats: hair; citations: hair
  traits           ofcc1_region_hair_curl               OFCC1-region hair-curl association
      2 of 2 term(s), score 8.75; card_id: curly, hair; title: curly, hair; summary: hair; detail: curly, hair; evidence: curly, hair; caveats: curly, hair; citations: hair
```

Four cards match both words, and the pack has no fifth. "Predisposed to curly hair" could
be any of them, so a full review reads all four. The rest of this example follows the
first, `wnt10a_hair_curl`. `genetics runs search <run> curly hair` lists the same cards
with this run's result for each, and is the quicker way to see which one the reader means.

### 4. Read the result

<!-- run: genetics runs card <run> wnt10a_hair_curl -->
```text
WNT10A hair-curl association
  card        wnt10a_hair_curl
  section     traits (Traits, morphology & sensory)
  kind        interpretation
  gene        WNT10A
  status      matched
  confidence  moderate
...
Summary
  Your CT has one T allele associated with a slightly curlier hair-shape score.
...
Confidence
  tier moderate; score 0.72 (on its own the score gives strong)
  The tier is moderate because no population allele frequency was available, so rarity could not be checked. The weighted score 0.72 alone falls in the strong band (0.70 up to 0.85).
...
  ceiling from allele_frequency: at most moderate, because no population allele frequency was available, so rarity could not be checked; sets the tier
  ceiling from ancestry_match: at most strong, because ancestry match to the study is unknown
```

The text form is for reading. A program reads `--json`, and these are the keys a review
uses:

<!-- keys: genetics runs card <run> wnt10a_hair_curl --json -->
| Key | Holds |
|---|---|
| `card.status` | `matched` here. Any other status means the card states no result for this run, and `card.match.reason` says why |
| `card.summary`, `card.detail` | The claim as the reader saw it, with their result filled in |
| `card.match.outcome_name` | Which of the card's outcomes the call selected |
| `card.observation.call_source` | `direct` for a chip call, `imputed` for an imputed one |
| `card.evidence` | Tier, replication, sample size, study ancestry and the effect with its units |
| `card.confidence_tier` | The saved tier |
| `current_context.confidence.basis` | What decided the tier: `score`, `ceiling`, `method`, `not_reproduced` or `none` |
| `current_context.confidence.limiting` | The inputs whose ceiling is the tier |
| `current_context.confidence.reason` | The same in a sentence. Quote it; do not paraphrase a tier |
| `current_context.confidence.inputs` | Each input with its weight and what it cost the score |
| `card.frequencies` | Population allele frequencies, where the run had a reference for them |
| `card.authored_caveats`, `card.computed_caveats` | The pack's caveats, and the ones this run added |
| `card.citations` | Every source, with `type` and `id` |
| `current_context.citation_links` | A link for each, in the same order; `url` is null where the engine will not link it |
| `current_context.related`, `current_context.pointed_from` | Other cards on the same question |

Two things in this output are about the example run and not about the card. The tier is
moderate because the run had no frequency reference, and the ancestry match is unknown
because ancestry did not run. A real run has both, and its tier and reason will differ.
That is why the tier is read from the run and never from the pack.

### 5. Read the claim without the result

<!-- run: genetics cards evidence wnt10a_hair_curl -->
```text
WNT10A hair-curl association
  card      wnt10a_hair_curl
  section   traits (Traits, morphology & sensory)
  kind      interpretation
  gene      WNT10A
  variant   rs7349332 at 2:219756383 (GRCh37), alleles C and T

Evidence
  tier gwas; replication independent; n = 5,385; study ancestry EUR
  effect beta 0.193 points per T-allele copy on a self-reported 0-to-5 hair-curl scale

Citations
  doi:10.1371/journal.pgen.1000993  Web-Based, Participant-Driven Studies Yield Novel Genetic Associations for Common Traits
    https://doi.org/10.1371/journal.pgen.1000993
  doi:10.1093/hmg/ddx416  Meta-analysis of genome-wide association studies identifies 8 novel loci involved in shape variation of human head hair
    note: Independent European meta-analysis confirming the previously reported WNT10A hair-shape locus.
    https://doi.org/10.1093/hmg/ddx416

Caveats
  - Hair shape is polygenic and varies strongly among populations; this one marker cannot classify hair as straight, wavy, or curly.
  - The numerical effect comes from self-reported hair categories in a northern-European cohort and may not transfer to other ancestries or grooming practices.
  - The associated intronic marker does not by itself establish that altered WNT10A activity causes the phenotype.
  - This card declares the forward-strand C/T study pair; other rare dbSNP alleles are outside this interpretation.
```

Everything here is the same for every reader, so all of it may be searched.

### 6. Read the cited papers

Both papers are open in PubMed Central: Eriksson et al. 2010 as PMC2891811 and Liu et al.
2018 as PMC5886212. A request for either carries a DOI or a PMC number and nothing else.
Publisher pages often refuse an automated client. The NCBI E-utilities do not:
`esearch.fcgi?db=pmc&term=<doi>[doi]` gives the PMC number and
`efetch.fcgi?db=pmc&id=<number>&rettype=xml` the full text, tables included. The first
call can also return a paper that cites the one asked for, so check the title.

What the check found, on 2026-11-15:

| The card says | The paper says | Where |
|---|---|---|
| rs7349332, alleles C and T, effect counted per T | C major, T minor; "each T is associated with a 0.2 point change" toward curlier hair | Eriksson, Results, "Hair curl"; Table 2 |
| beta 0.193 on a 0-to-5 scale | 0.193; six pictured answers coded 0 ("stick straight") to 5 ("very tight curls"), linear regression | Eriksson, Table 2 and Methods |
| n = 5,385, northern-European ancestry | 5,385 for hair curl; unrelated customers assessed as northern European | Eriksson, Table 1 and Methods |
| self-reported | a web survey: "Is your hair naturally straight or curly?" | Eriksson, Methods |
| replication independent | 2q35 *WNT10A* is genome-wide significant in a meta-analysis of three other European cohorts (QIMR, Rotterdam Study, TwinsUK; 16,763 people) | Liu, Results and Table 1 |

Nothing needed correcting. One thing is worth stating in an answer. Liu's lead marker at
the locus is rs74333950, not the card's rs7349332. The text says the previously reported
*WNT10A* marker also reached genome-wide significance, and gives the figures in its
Supplementary Table S6, which this check did not open. The card's note says the *locus*
was confirmed, which is what the paper's main text shows.

### 7. Search further

Queries that could follow, each written from the output of step 5:

<!-- queries: wnt10a_hair_curl -->
- `rs7349332 WNT10A hair curl`
- `10.1371/journal.pgen.1000993`
- `WNT10A hair shape meta-analysis`
- `WNT10A intronic marker hair shape`

Each one is checked before it is sent:

<!-- run: genetics cards check-query rs7349332 WNT10A hair curl --card wnt10a_hair_curl -->
```text
clean: no rule refuses this query, and every word is in the cards' evidence.
```

`cards check-query` refuses a query, exits 1 and never repeats it, when one of these rules
finds something:

| Rule | Finds | Kind |
|---|---|---|
| `genotype-shape` | Any shape the privacy scanner knows, such as an rsID with a call attached by an equals sign | call |
| `marker-with-alleles` | An rsID beside two alleles: merged, apart, or joined by a slash, pipe, semicolon or comma | call |
| `diplotype` | Two star or HLA alleles joined by a slash | call |
| `zygosity` | "heterozygous", "homozygote" and the like | result |
| `allele-count` | "one copy", "two copies", "one T allele" | result |
| `first-person` | "my", "do I", "I have" | result |
| `run-id` | A run id in the engine's format | result |
| `confidence-tier` | A tier, such as "likely artifact" or "moderate confidence" | result |

A variant's alleles written as a change, `C>T`, are a variant and pass. `rs7349332 one
copy` is made of words step 5 prints, and `allele-count` refuses it. `genetics cards
search` and `genetics runs search` refuse the three `call` rules, with `error.kind:
genotype-in-query`. They search the `result` words, because nothing they read leaves the
machine and a reader may want the cards that say "homozygous".

With `--card`, the check also lists each query word that card's evidence does not
print, as `unsourced`. That is advice and not a refusal. `WNT10A odonto-onycho-dermal
dysplasia` lists four words, and each comes from Eriksson et al., read in step 6. A
haplogroup, an HLA type or a tier has no shape of its own, so this list is where one
shows up. A word that came from the run is never sent.

No rule list is complete, so the rules above still apply to a query the check passes.

This example needed no search beyond the two cited papers.

### 8. Answer

An answer to the brief's question, for the example run. Facts 1 to 8 are from Eriksson et
al. 2010 (doi:10.1371/journal.pgen.1000993) and facts 9 and 10 from Liu et al. 2018
(doi:10.1093/hmg/ddx416). Every figure was read in the place named.

> **Your result.** The run holds one T allele at rs7349332, in *WNT10A*, called directly
> on the chip. In the study the card cites, each T went with 0.193 points more curl on a
> 0-to-5 scale. That is a small average shift across a population and does not predict
> one person's hair. The card's tier is **moderate**: "no population allele frequency was
> available, so rarity could not be checked". Three other cards cover hair curl in this
> run, and they are not reviewed here.
>
> 1. **The finding came from a web survey.** 23andMe customers answered "Is your hair
>    naturally straight or curly?" by picking one of six pictures, from "stick straight"
>    to "very tight curls". The answers were coded 0 to 5. (Methods)
> 2. **5,385 people answered**, all unrelated and assessed as northern European. Hair curl
>    was one of 22 traits tested in the same paper, alongside asparagus anosmia and the
>    photic sneeze reflex. (Table 1)
> 3. **T is the less common allele.** Its frequency in the study was 0.14. (Table 2)
> 4. **The size of the effect is 0.193 points per T**, about a fifth of the distance from
>    one answer to the next. Its score, the negative log₁₀ of the p-value, was 13.48; the paper
>    called a locus significant above 8.4. (Table 2; the threshold is in Table 1's note)
> 5. **Straight hair was reported by 36.1% of people with no T, 28.3% with one and 26.3%
>    with two.** Only 95 people had two. (Table 7)
> 6. **Most people in every group reported straight or slightly wavy hair:** 81.8% with no
>    T, 74.5% with one, 69.5% with two. This is the card's first caveat as numbers: the
>    marker moves the odds and cannot classify anyone's hair. (Table 7; the sums are this
>    review's)
> 7. **It is the second-largest of the paper's four hair-curl signals.** The largest, near
>    *TCHH*, is 0.294 points per allele toward straighter hair. The smallest, near *OFCC1*,
>    is 0.1 points and fell short of the paper's significance line. All four together
>    explained about 6% of the variance in hair curl among northern Europeans. (Table 2
>    for three; Results, "Hair curl", for *OFCC1*; Discussion)
> 8. **The marker sits in an intron of *WNT10A*.** The authors point out that mutations in
>    the gene cause odonto-onycho-dermal dysplasia, whose signs include dry, misformed
>    hair, and that the gene is switched on in hair follicles at the start of a growth
>    cycle. The card's caveat applies: an intronic marker does not show that *WNT10A* is
>    the cause. (Results and Discussion)
> 9. **The locus held up in other cohorts.** A 2018 meta-analysis of 16,763 Europeans from
>    Australia, the Netherlands and the UK found 2q35 *WNT10A* at P = 3.98 × 10⁻¹⁵. Its
>    lead marker there is rs74333950, a different one from this card's. The paper says the
>    earlier marker was also genome-wide significant; that figure is in a supplementary
>    table this review did not open. (Liu, Table 1 and Results)
> 10. **Hair shape is still poorly predicted from DNA.** The same paper's best model used
>     14 markers and reached an AUC of 0.66 for straight against non-straight hair, and
>     0.64 in a separate cohort, where 0.5 is a coin toss. It reports that an earlier
>     three-marker model that included rs7349332 reached 0.62 in 528 Polish people. (Liu,
>     Discussion)
>
> **Not checked:** Liu's supplementary tables, and the three other hair-curl cards.

Facts 1 to 10 are about the variant and the studies and would be the same for any reader.
Only the first paragraph is about the run.

## Other questions

| The reader asks | Start with |
|---|---|
| Why is this card low confidence? | `genetics runs card <run> <card-id> --json`: `current_context.confidence`, described under [Confidence](agent_cli.md#confidence-m134) |
| Review a whole section | `genetics runs show <run> --section <section> --json`, then `runs card` for each card worth a closer look |
| Is the run itself sound? | `genetics runs qc <run> --json`, and `genetics runs imputation <run> --json` for an imputed run |
| What does the run say about a drug or a gene? | `genetics runs search <run> <query>`, then `genetics pgx calls <run> --gene <gene> --json` |
| What does a ClinVar hit mean? | `genetics runs clinvar <run> --json` and `genetics runs secondary <run> --json`. A rare hit is more likely an array artifact than a finding (AGENTS.md §4.1); give the benchmark figure the card gives |
| What are my HLA types? | `genetics hla calls <run> --json` |
| Where does the run sit among reference populations? What are its haplogroups? | `genetics runs ancestry <run> --json`: the placement, every population's distance, ancient affinity, and each haplogroup with its supporting markers (M14.2) |
| Why is there no card for a test I read about? | `genetics cards search <query>`. An assay-limit card says why the array cannot determine it (AGENTS.md §3.2) |
| What does the page I am looking at show? | [Which command stands for which page](agent_cli.md#parity-m135) |

## When a step fails

A failing command prints one error document under `--json`. Branch on `error.kind`.

- **`card-not-found`.** The id is wrong, or the run was saved under a pack that did not
  hold the card. `genetics cards search` finds the id, and `genetics runs show <run>`
  lists what the run holds. A card missing from an older run is a fact to report. The
  pack's card says nothing about that run.
- **`not-found`, `version`, `integrity`, `io`, `bundle`.** The run could not be opened.
  Report the kind and stop. Do not answer from the pack as though it were the run.
- **`genotype-in-query`.** The query held a result. Search for the variant, gene or trait.
- **The card's status is not `matched`.** The marker is absent, uncalled or ambiguous, or
  the card is an assay limit. There is no result to review. `cards evidence` and the
  papers can still be read, and the answer says the run holds no call.
- **`basis` is `not_reproduced`.** The saved tier stands, and this engine cannot say what
  decided it. Say that, and do not work a reason out by hand.
- **A paper cannot be opened.** Say which. Do not give a number from memory, or from a
  page that only cites the paper.

## Decisions

No owner question was asked. The M13.6 entry contract listed four open points:

- **It lives here, with a pointer in AGENTS.md §3.** AGENTS.md is read at the start of
  every session and is already long; a walk-through with outputs would add several
  hundred lines to it. The file is `agent_usage.md`, with an underscore like its two
  neighbours, where the roadmap wrote `agent-usage.md`.
- **The example uses a run built from committed cards and an invented table**, the same
  construction the CLI tests use. It shows real output, and the result in it is nobody's.
- **The example is tested.** A walk-through that is only prose goes stale when a command
  changes. See below.
- **What may be searched is stated as a rule about sources**, not as a list of forbidden
  strings: what leaves the machine is written from `cards` output. M13.7 added the lint
  (`cards check-query`) under that rule; it does not replace it.

One thing here is new and the owner may want it otherwise. The fourth rule under
[What may leave the machine](#what-may-leave-the-machine) reads AGENTS.md §1.3's "a prompt
to a remote model" beside §0's "a CLI agent can be pointed at a saved run", and settles
it as: the owner's request covers the cards asked about, read narrowly.

## How this page is kept true

`tests/test_agent_usage.py` reads this file.

- **Every `genetics` command written on the page exists** and takes each option it is
  written with, the ones written short (`runs show --section`) included.
- **Each block marked `run:` is run** against a saved run built as described above, and
  its lines must appear in the command's output, in order. A line of `...` stands for
  lines left out.
- **Each key in a table marked `keys:` exists** in the document that command prints,
  and the document is checked against the agent schema.
- **Each query in the list marked `queries:` is made only of words that
  `cards evidence --json` prints** for that card, and `cards check-query --card` calls it
  clean. A fifth query holding the run's genotype, its tier or the word "heterozygous"
  fails. So do the two that M13.6 left open: the marker with "one copy", and the marker
  followed by its two alleles apart. Their words are all ones the evidence prints, and
  `cards check-query` refuses both.
- **The rule table under step 7 is the lint's own**: its rules, in order, with each
  one's kind.
- **The statuses, tier bases and error kinds the page names in prose** are the agent
  schema's, and the kinds are the ones the commands report.
- **The page holds nothing the privacy scanner reads as a genotype**, and no command that
  prints a result is marked as safe to send out.
- **AGENTS.md links here.**

The comparison of the card with its papers, and the ten facts, are prose. They were read
from the papers' full text on 2026-11-15 and no test holds them. A change to the card's
evidence fails the `cards evidence` block above, which is the prompt to read them again.

No saved real run and no personal export was opened to write or test this page.
