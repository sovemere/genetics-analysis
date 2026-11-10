# Agent read commands (M13.1)

Implemented 2026-11-10. Four commands let an agent read one card, one section, a run's QC
record, or a card's evidence without printing a whole bundle. On the real imputed run
`runs show --json` prints about 1 GB.

| Command | Reads | Holds a genotype | Scanned |
|---|---|---|---|
| `genetics runs show <run> --section S [--section T] [--json]` | saved run | yes | no |
| `genetics runs card <run> <card-id> [--json]` | saved run | yes | no |
| `genetics runs qc <run> [--json]` | saved run | no | both branches |
| `genetics cards evidence <card-id> [--json]` | knowledge pack | no | both branches |

`genetics runs list` (M4.2) and `genetics refs licenses` (M2.6) are the rest of M13.1's list.

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

`run_id` in the new payloads is the bundle's directory name, which every command resolves.
`runs show --json` prints the manifest's own `run_id`, as before. The two differ only when a
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
  related               pointers the card's section declares (M12.1), resolved in this run:
                        [{card_id, in_run, title, section}]
  pointed_from          sections whose pointers name this card
```

M12.2's four MTHFR cards use both pointer lists. A claim card's `related` reaches the
nutrition card, whose `pointed_from` is `["physical_health", "mental_health"]`.

An unknown card id exits 1 with `error.kind: card-not-found` and names `runs show` as the way
to list the run's cards. The dashboard says the same thing for a stale card link.

The text form prints the claim, the variant, how the call was made, the evidence block, the
confidence tier with its six scored inputs, any empirical PPV, the frequencies, every caveat
and the citations with links. Polygenic, HLA, runs-of-homozygosity and multi-marker detail
gets one line pointing to `--json`, which holds it in full; the dashboard draws those as
tables and distributions. Where a card
has no evidence block, the text says which of three reasons applies: an assay-limit card, a
bundle older than format 2, or an outcome with no phenotype estimate.

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

## Validation

`tests/test_cli_agent_reads.py` builds a saved run from six committed cards matched against an
invented table and checks each command's shape, ordering, pointers, errors and reasons. It
also checks that the card projection carries every `StoredCard` field. Section frames and
pointers are checked against the dashboard's `views` for all thirteen sections. The four new
reads run as subprocesses with a cp1252 stdout. Each guard was removed in turn, and each
removal failed the test written for it: both scans on both scanned commands, report order,
the projection, the PGx notice, `pointed_from`, `in_run`, `--section` JSON, and the warning
list. The full native suite passes 4,029 tests with the existing nine skips.

None of these commands has been run on the real imputed run. That run's first read after this
source change repeats its deep checks (about 54 minutes); later reads take about 13 seconds.

## Left to later items

- **M13.2** versions and documents these shapes as a schema. Nothing here carries a schema
  version yet.
- **M13.3** `genetics search <query>`.
- **M13.4** is largely present: `card.confidence` holds the tier, score, scored inputs and
  PPV. M13.4 decides whether the components need explaining beyond the six rows.
- **M13.5** the parity test over every dashboard route. `SAVED_RECORDS` and the section-frame
  test are a start, not that test.
- **M13.6** the worked review example; **M13.7** the outbound-query lint.
