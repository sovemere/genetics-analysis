# Agent JSON schema (M13.2)

Implemented 2026-11-11; version 5 since M13.5 (2026-11-13), which described the five
commands that print a run's other saved records. The JSON the agent read commands print is described by one JSON
Schema document, [`src/genetics/cli/agent_schema.json`](../src/genetics/cli/agent_schema.json)
(draft 2020-12). Every described document names its payload and the schema version, so a
reader can check it without knowing which command printed it.

```text
genetics schema                 list the payloads and the command that prints each
genetics schema --json          the whole document
genetics schema runs.card       a self-contained JSON Schema for one payload
```

The document is the reference for field names, types and vocabularies. This page gives the
rules around it. [The read-command contract](agent_cli.md) describes what each command is for.

## Payloads

| Name | Command | Reads | Holds a genotype | Scanned |
|---|---|---|---|---|
| `runs.list` | `genetics runs list --json` | run store | no | yes |
| `runs.show` | `genetics runs show <run> --json` | saved run | yes | no |
| `runs.section` | `genetics runs show <run> --section S --json` | saved run | yes | no |
| `runs.card` | `genetics runs card <run> <card-id> --json` | saved run | yes | no |
| `runs.qc` | `genetics runs qc <run> --json` | saved run | no | yes |
| `runs.search` | `genetics runs search <run> <query> --json` | saved run | yes | no |
| `cards.evidence` | `genetics cards evidence <card-id> --json` | knowledge pack | no | yes |
| `cards.search` | `genetics cards search <query> --json` | knowledge pack | no | yes |
| `runs.clinvar` | `genetics runs clinvar <run> --json` | saved run | yes | no |
| `runs.secondary` | `genetics runs secondary <run> --json` | saved run | yes | no |
| `runs.imputation` | `genetics runs imputation <run> --json` | saved run | no | yes |
| `pgx.calls` | `genetics pgx calls <run> --json` | saved run | yes | no |
| `hla.calls` | `genetics hla calls <run> --json` | saved run | yes | no |
| `error` | a failing command with `--json` (listed below) | nothing | no | no |

The same table is in the document as `x-payloads`. "Scanned" means the command checks its
output for genotypes before printing. The eight payloads that hold a genotype state the
reader's own calls, which is what a card and a saved record say, and are not scanned
([why](agent_cli.md)). Find a card with `cards.search` and research it from
`cards.evidence`, never from a run payload (AGENTS.md §1.3).

The last five are the saved records beside a run's cards (M13.5), the ones a section's
`saved_records` names. [The read-command contract](agent_cli.md#parity-m135) says which
dashboard page each stands for.

## The tag

Every described document starts with:

```json
"schema": {"name": "runs.card", "version": 5}
```

`name` is one of the fourteen above. `version` is the version of the schema document, which is
the same for all fourteen. It is separate from `format_version`, which is the bundle format the
run was saved in.

## Rules for a reader

- With `--json`, stdout holds exactly one JSON document, in UTF-8. Progress lines go to
  stderr.
- Check `schema.name` first. `error` means the command failed.
- Ignore a key you do not know, and treat a vocabulary value you do not know as unknown.
  Later versions add both.
- A document whose `schema.version` is higher than the one you were written for still holds
  everything your version described, with the same meaning.
- A null in a saved card usually means the bundle's format did not record that field. The
  document says which format each field arrived in.

## Rules for a change

- **One version covers every payload.** `AGENT_SCHEMA_VERSION` in `genetics/cli/contract.py`
  and `version` in the document move together.
- **Changes are additions.** A key is never removed and never given another meaning. A key
  whose meaning changes gets a new name. This is the bundle's own rule, for the same reason:
  a reader written for an earlier version must keep working.
- **Any change to a described shape takes the next version.** That includes a new key, a new
  vocabulary value, a key becoming required and a type widening. Rewording a description
  does not.
- **A shipped version cannot be edited.** `tests/test_agent_schema.py` holds a digest of each
  version's shape, with descriptions left out. To change the shape: bump the version in both
  places, add the new digest, and add a line to the version history below.
- **The engine and the document cannot drift apart.** The tests compare each vocabulary with
  the engine's enum, compare the card's keys with `StoredCard`, and check every command's
  output against the document. A key added to an output without being added to the document
  fails them.

## Saved record and current context

M13.1 kept the saved record apart from what the engine adds when it reads a run, as a
convention. It is now the rule, and the document's structure states it. In a run-scoped
payload (`runs.show`, `runs.section`, `runs.card`, `runs.qc`, `runs.search`, and since
version 5 `runs.clinvar`, `runs.secondary`, `runs.imputation`, `pgx.calls`, `hla.calls`):

- `schema`, `run_id` and `path` are the envelope. They describe this read.
- `current_context` holds everything this engine adds at read time: section titles and
  blurbs, empty-section reasons, pointers between sections, citation links, section
  notices, a search's query and ranking, and what decided a card's tier. It always carries
  `"context": "current"`.
- Every other top-level key is the saved record, unchanged.

`runs.show` and `runs.qc` have no `current_context`, because they add nothing. In
`runs.search`, `results` holds each matched card's saved face and `current_context.hits`
holds why it matched, in the same order.

`pgx.calls` and `hla.calls` hold a saved record's own keys beside the envelope (`status`,
`genes` and the rest), where those commands have always printed them. `pgx.calls` has a
`current_context` with the section's notice. Its `cyp2d6_limitation`, `guideline_cards` and
`hla_cards` are parts of the run's saved cards, and `guideline_status` says whether the run
holds any. `hla.calls` has `linked_cards`, the faces of the run's saved HLA-linked cards,
and `linked_cards_status`, which is `not-recorded` for a run saved before those cards
existed. `runs.clinvar`, `runs.secondary` and `runs.imputation` add nothing to the record.

## `run_id`

`run_id` is the bundle's directory name in every payload and in the text output. That is the
id every command resolves and `runs list` prints. Before M13.2, `runs show --json`,
`runs clinvar`, `runs secondary` and `runs imputation` printed the manifest's own `run_id`
instead, and before M13.5 `pgx calls` and `hla calls` printed none. The two differ only when a bundle directory has been renamed. `runs.show` keeps the
manifest's value as `recorded_run_id`, so nothing saved is lost.

## Errors and exit codes

A failing command prints this on stdout under `--json`, and a sentence on stderr without it:

```json
{
  "schema": {"name": "error", "version": 5},
  "ok": false,
  "error": {"kind": "not-found", "message": "no run '...' under ..."}
}
```

Branch on `error.kind`. `message` is for a person and may be reworded.

Before M13.2 the `pgx` and `pgs` groups printed `error` as a bare string. Every command that
printed an error document now prints this one, through `contract.refuse`: all of `runs`,
`cards evidence`, `cards search`, `pgx`, `pgs`, `hla`, `run`, `impute`, `serve` and `schema`.

`runs`, `pgx calls` and `hla calls` give the same kind for a run that cannot be opened,
through `contract.run_error_kind`. Before the [session review](review_m132_session.md),
`hla calls` called every such failure `hla` and `pgx calls` called a disk failure `pgx`.

For the read commands and `schema`, the exit code says which kind of failure it was:

| Exit | Meaning | Kinds |
|---|---|---|
| 0 | Success | |
| 1 | The command was well formed but could not be carried out | `not-found`, `card-not-found`, `version`, `integrity`, `io`, `bundle`, `knowledge` |
| 2 | The command line was wrong | `unknown-section`, `unknown-payload`, `confirmation-required`, `empty-query`, `genotype-in-query` |

| Kind | From | Means |
|---|---|---|
| `not-found` | any command that takes a run id | No run with that id is saved. `pgx calls` and `hla calls` give the same kind |
| `card-not-found` | `runs card`, `cards evidence` | The run or the pack has no card with that id |
| `version` | `runs`, `pgx calls`, `hla calls` | The run was saved by a newer version of the tool. It is intact |
| `integrity` | `runs`, `pgx calls`, `hla calls` | A saved file does not match its recorded digest |
| `io` | `runs`, `pgx calls`, `hla calls` | The disk refused: a locked file, a permission, a missing drive |
| `bundle` | `runs`, `pgx calls`, `hla calls` | The run could not be read for another reason |
| `knowledge` | `cards evidence`, `cards search` | The knowledge pack could not be loaded |
| `unknown-section` | `runs show --section` | Not one of the thirteen section names |
| `unknown-payload` | `schema` | Not one of the fourteen payload names |
| `empty-query` | `cards search`, `runs search` | The query has no letter or digit to search for |
| `genotype-in-query` | `cards search`, `runs search` | The query reads as a genotype. It was not searched, and the message does not repeat it (AGENTS.md §1.3) |
| `confirmation-required` | `runs delete`, `runs prune` | `--json` cannot prompt; pass `--yes` |

A command line Typer itself rejects (a missing argument, an unknown option) exits 2 with a
usage message on stderr and nothing on stdout.

The other groups name their own kinds: `pgs`, `pgx`, `hla` and `imputation` for their groups,
`config` and `serve` for `serve`, and one per pipeline stage for `run` (`ingest`, `ancestry`,
`structure`, `polygenic`, `run_parts`, `frequency_reference` and others). A kind is lowercase
letters, digits, hyphens and underscores. `tests/test_agent_schema.py` reads every kind the
CLI modules can print and checks each against the document.

Not unified, and recorded here so that nobody assumes otherwise:

- `run`, `impute` and `serve` exit 2 for every failure, including ones that are not usage
  errors. Their error document is the same.
- `ingest`, `refs`, `tools` and `paths` print a failure as a sentence on stderr even under
  `--json`, with a non-zero exit and nothing on stdout. `roh` has no `--json` flag: it prints
  its result as JSON and a failure as a sentence. None is an agent read command.

## How closely each part is described

- **Closed, key for key:** the envelope, `current_context` (the confidence block
  included), the run listing, the evidence declaration, both search payloads, the error
  document, and the saved card's 26 keys. A saved card always has all 26; a key its
  bundle's format did not have is null.
- **Closed, inside the saved card:** `variant`, `match`, `confidence`, `evidence`,
  `observation`, `frequencies` and `citations`. Their keys were checked against the first
  version of the bundle writer in git history: `variant`, `match`, `confidence`, frequencies
  and citations have had the same keys since format 1, and `evidence` and `observation`
  since they were added. `observation.imputation` (format 15) is the one optional key.
- **Named but open:** records that carry their own `schema_version` and have their own
  documents. These are `computation.result`, `multi_marker`, `ancestry_comparison`, `carrier`
  on a saved card, and the run-wide `qc`, `provenance`, `ancestry`, `clinvar`, `pgx`, `hla`,
  `imputation` and `imputation_provenance`. The document types each as an object, says when
  it is null, and names the document that describes it.
- **Closed at the top, open below (version 5):** the five record payloads. Their top-level
  keys are listed and closed, which for `pgx.calls` and `hla.calls` includes the saved
  record's own keys. The values under them (`clinvar`, a gene's result, an observation, the
  imputation provenance) are the same open records as above. What `pgx.calls` and
  `hla.calls` add is closed: the section notice, the CYP2D6 limitation, and each listed
  card.

**A saved card keeps its confidence in one of two places, and the document describes
both.** Interpretation and HLA cards hold `confidence`: the tier, the score and six scored
inputs, with the empirical PPV where one applies. Computed, polygenic and guideline cards
hold `confidence: null` and keep their tier and what produced it in
`computation.reliability`, whose inputs differ by source. `confidence_tier` on the card is
the tier from whichever applies.

**An agent reads one shape (M13.4).** `runs.card` adds `current_context.confidence`, the
`confidence_explanation` definition: the saved tier and score, each input as a row with its
weight and what it cost the score, every ceiling that applies, which of them set the tier,
and a sentence saying so. It has the same twelve keys for every card, including a card with
no tier. `basis` is the `confidence_basis` vocabulary: `score`, `ceiling`, `method`,
`not_reproduced` or `none`. [The read-command contract](agent_cli.md#confidence-m134) gives
the weights, bands and ceilings. The block is built when the run is read, so the saved card
and both saved places are unchanged.

## Citations

The roadmap names one requirement: card JSON must include citations, so that an agent can
check a claim instead of inventing a source. The document requires `citations` on every saved
card and in every evidence declaration, and requires `type` and `id` on each citation.
`runs.card` adds each citation's public page under `current_context.citation_links`, and
`cards.evidence` adds `url` to each citation. A test checks that every card with a claim has
at least one citation, and that an assay-limit card has none (AGENTS.md §7.6).

## Not described

These commands print JSON that the document does not describe. They carry no tag:

- `run`, `ingest`, `impute`, `serve`, `doctor`, `paths`, `adapters`, `version`, `roh`, `refs`,
  `tools`, `pgs`, `pgx inspect`, `pgx prepare`, `hla inspect`, `cards lint`, `cards carriers`,
  `cards carrier-scope`, `runs delete`, `runs prune`.
- `runs imputation --dosages`, which prints the saved dosages as JSON Lines.

M13.5 decided this list. Its parity check names the commands that stand for a dashboard
page, and those are the ones an agent reads a run through; all of them are now described.
None of the commands above reads a saved run's analysis. `version --json` is the one the
check uses: it gives `version` and, since M13.5, `bundle_format_version`.

## Decisions

No owner question was asked. Each choice follows something already settled:

- **One document in the package, hand-written, not generated.** It is the contract, so it is
  the thing reviewed in a diff. It sits beside its module so an installed wheel can print it.
- **The tag is an object under `schema`.** `format_version` already means the bundle format,
  and `cards.evidence` already uses a top-level `kind` for the card's kind.
- **`run_id` is the directory name.** `runs list` and the four M13.1 payloads already did
  this, and it is the id a command can use.
- **The error is `{kind, message}`.** `runs`, `cards evidence`, `hla`, `run`, `impute` and
  `serve` already printed that; `pgx` and `pgs` printed a string.
- **Exit codes are stated, not changed.** The read commands already followed the 1-or-2 rule.
  `run`, `impute` and `serve` exit 2 for everything, and `tests/test_cli_run.py` pins it.
- **`jsonschema` is a development dependency only.** The tests validate with it. The CLI
  prints the document and never validates at run time.

## Validation

`tests/test_agent_schema.py` holds 52 tests. They check that the document is a valid schema
at the declared version, that every payload is listed, defined and reachable, and that no
definition is unused. They compare thirteen vocabularies with the engine's enums and the
card's keys with `StoredCard`. They build a saved run from 103 committed cards matched
against an invented table and check every read against the document, including `runs card`
for each card. They check the evidence declaration of all 119 cards. They check thirteen
failures for one error document, a stable kind and the stated exit code, and that a damaged
run and a newer-format run are told apart by `runs`, `pgx calls` and `hla calls`. They read
every error kind the CLI modules can print and check each one. A renamed bundle is read
through seven commands to check `run_id`.

HLA and guideline cards need a stage record, so the saved runs that hold them are built in
`tests/hla/test_hla_cards.py` and `tests/refs/test_pgx.py`. Both now check `runs show --json`
and `runs card --json` against the document with the shared `agent_schema_check` fixture.

Sixteen guards were each removed in turn at M13.2, and each removal failed a test: the tag
on three commands and on the error document, the three `run_id` sources, the two error kinds
for an unknown run in `pgx calls` and `hla calls`, the error as a bare string, an unlisted key
in three outputs, the document edited under version 1, the version bumped without a digest,
and the exit code for an unknown payload. The session review removed five more, each caught:
the shared kind in `pgx calls` and `hla calls`, the `version` kind, version 1's kind pattern
(caught by the new kind test on its own, not only by the digest), and the version bumped to 3
without a digest.

The full native suite passed 4,083 tests with the existing nine skips at M13.2, and
4,084 after the session review.

M13.3 took the document to version 3, and `tests/test_agent_schema.py` now holds 57 tests.
The added checks: the `search_field` vocabulary against the engine's enum; both search
payloads against the document for four queries, and a run search that returns every saved
card; `card_face` as eight keys of the saved card with the saved card's own definitions;
`runs.search` in the saved-versus-current, renamed-run, unknown-run and damaged-run tests;
and the two query kinds. Editing the document under version 3 without a new digest fails the
digest test. The full native suite passes 4,183 tests with the same nine skips.

The [M13.3 session review](review_m133_session.md) added the side-by-side bonus to the
description of `search_score`. That is wording, so the document is still version 3 and its
digest is unchanged. The suite passes 4,191 tests after the review.

M13.4 took the document to version 4, and `tests/test_agent_schema.py` now holds 61 tests.
The added checks: the `confidence_basis` vocabulary against the engine's enum; the block
required on `runs.card`, closed at every level, and absent from the saved card's
definition; seven ways of breaking the block in a real document; the block for every card
of the saved run, with its tier equal to the saved tier and its replay matching; and its
absence from `runs.section` and `runs.search`. Removing `confidence` from the required
list, opening the block or adding a basis under version 4 fails the digest test. The full
native suite passes 4,229 tests with the same nine skips.

The [M13.4 session review](review_m134_session.md) reworded the description of
`confidence_explanation.score`: it is the sum of weight times component, and the rows'
rounded `contribution` figures can add up to a figure 0.0002 away. That is wording, so the
document is still version 4 and its digest is unchanged.

M13.5 took the document to version 5, and `tests/test_agent_schema.py` now holds 65 tests.
The added checks: each of the five record commands against the document, on the saved run
and with `--gene`; each one's record against what `runs show --json` holds; the five in the
saved-versus-current, renamed-run and genotype tests; `hla.calls`' listed keys against the
record's own key set in `genetics.hla.calling`; a genotype put into `runs imputation`'s
output, which the command refuses to print; and `version --json`. The runs with completed
PGx calls, HLA calls and cards, a ClinVar lookup and ACMG overlaps are built in
`tests/refs`, `tests/hla` and `tests/health`, which check every document a parity run
reads against the schema, through the `parity_check` fixture. Removing the tag from any of
the five, or `linked_cards_status` from the required list under version 5, fails a test.
The full native suite passes 4,273 tests with the same nine skips.

None of these commands has been run on the real imputed run. This change edits Python
source, so that run's first read repeats its deep checks (about 54 minutes).

## Version history

| Version | Date | Change |
|---|---|---|
| 1 | 2026-11-11 | First version: seven payloads |
| 2 | 2026-11-11 | `error.kind` may contain an underscore. Version 1's pattern refused two kinds `genetics run` prints, `run_parts` and `frequency_reference`. Found by the [session review](review_m132_session.md) |
| 3 | 2026-11-12 | Two payloads, `cards.search` and `runs.search` (M13.3), with the `search_field` vocabulary and `card_face`, eight keys of the saved card. No existing payload changed |
| 4 | 2026-11-12 | `runs.card` gains the required key `current_context.confidence` (M13.4): `confidence_explanation`, with the `confidence_basis` vocabulary. The saved card and every other payload are unchanged |
| 5 | 2026-11-13 | Five payloads for the saved records beside a run's cards (M13.5): `runs.clinvar`, `runs.secondary`, `runs.imputation`, `pgx.calls`, `hla.calls`. Each command already printed its record; it now prints the envelope and tag too. `hla.calls` gains `linked_cards_status` and `linked_cards`, and `pgx.calls` gains `current_context.context`. No existing payload changed |
