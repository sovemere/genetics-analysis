# M13.2 session diff review

Scope: `7a4c4c3..2c90a52`. That is M13.2's agent JSON schema (`src/genetics/cli/agent_schema.json`),
`genetics/cli/contract.py`, the `genetics schema` command, the tag and error changes in nine
CLI modules, `tests/test_agent_schema.py`, the schema checks added to the HLA and PGx bundle
tests, and the documentation. Every changed source line was re-read against the document, and
every error path in `genetics/cli` was traced to the kind it prints. The review opened no
personal genotype and no saved real run; it used synthetic runs only.

## Findings and fixes

- **P2: version 1 refused two error kinds that `genetics run` prints.** The document limited
  `error.kind` to `^[a-z][a-z0-9-]*$`. `run`'s stage mapping returns `run_parts` and
  `frequency_reference`, so a failing `genetics run --json` printed an error document that
  did not match the schema it was tagged with. No test reached either failure: one needs an
  unreadable resumable-parts directory, the other a damaged frequency reference.
  - **Fixed as version 2, not by editing version 1.** Version 1 had been pushed, and the
    document's own rule is that a shipped version is never edited. Version 2 widens the
    pattern to allow underscores. Renaming the two kinds was the other option; it would have
    changed values `genetics run` already prints.
  - **A test now covers every kind.** It reads every string an `*error_kind` function can
    return, and every literal passed to `refuse`, from the source of each CLI module, and
    validates an error document for each. It also asserts the harvest finds `run_parts`,
    `frequency_reference`, `config` and `serve`, so it cannot pass on an empty set. Restoring
    version 1's pattern fails it on its own, not only through the digest pin.
- **P2: one damaged run gave three different kinds.** `pgx calls` and `hla calls` reported an
  unknown run as `not-found` after M13.2, but every other load failure kept its group's kind:
  `hla calls` called a newer-format, damaged or unreadable run `hla`, with a generic sentence,
  and `pgx calls` called a disk failure `pgx`. The new documentation listed `version`,
  `integrity`, `io` and `bundle` as coming from "any command that reads a run", which was
  false for both.
  - `runs_cmd.error_kind` moved to `contract.run_error_kind`. `runs`, `pgx calls` and `hla
    calls` use it for any failure to open the run, with the store's own sentence, as
    `runs show` prints for the same run. Failures after the run is open keep their group's
    kind: `hla` for HLA evidence that does not validate, `pgx` for PGx calling.
  - `pgx_cmd._error` no longer imports from `runs_cmd`, which it had done to reach the mapping.
  - The damaged-run and newer-run test now covers `hla calls`.
- **P3: stale and wrong documentation.**
  - The README's status line still said "M0–M12 and M13.1 are implemented".
  - The schema page, handoff and roadmap said `roh` prints failures as text "under
    `--json`". `roh` has no `--json` flag; it always prints its result as JSON and a failure
    as a sentence.
  - The schema page's list of commands that print untagged JSON left out `adapters` and
    `pgx prepare`, and named the section "Outside version 1".
  - The schema page said `tests and callers rely on` `run`'s exit code 2. The tests pin it;
    nothing was checked about callers.

## Checked without change

- **Privacy at the error boundary.** `run` and `serve` scanned their message and then the
  JSON text; through `contract.refuse` only the message is scanned. The rest of the document
  is the tag, `ok` and a kind from a fixed set, so the second scan checked nothing the first
  did not. `impute` still scans its message before refusing.
- **`hla calls` messages.** Load failures now print the store's sentence rather than the
  generic HLA one. Those sentences are the ones `runs show` prints for the same run, and
  `read_bundle` raises a fixed sentence for invalid saved HLA evidence. HLA validation
  failures, which can follow R output, still print the generic sentence.
- **The schema against saved formats.** The closed blocks inside a saved card (`variant`,
  `match`, `confidence`, `evidence`, `observation`, frequencies, citations) were re-checked
  against the first commit of `run/bundle.py` and of each block's writer. Their keys have not
  changed since each was added.
- **The digest pin.** It ignores `description` and `title` text, and keeps a property named
  `title`. `x-payloads` commands are part of the shape, so renaming a command takes a version.
- **`runs show` text and JSON.** Both print the directory name; `recorded_run_id` is the only
  place the manifest's id appears.

## Recorded rather than changed

- **`run`, `impute` and `serve` exit 2 for every failure.** Stated in the schema page, pinned
  by `tests/test_cli_run.py`, and left for whichever item takes up non-read commands.
- **The kind test reads source.** Most kinds belong to failures that need a broken tool, a
  full disk or a damaged reference to reach. A kind built at run time, rather than written as
  a literal, would escape it; none is today.

## Operational note

The review changed Python source, so the first read of each saved run after it repeats its
deep checks once (about 54 minutes for the real imputed run). Run `genetics runs list
--verify`, or the launcher's verify-first shortcut, first.

## Validation

Run on 2026-11-11, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **4,084 tests with the same nine skips** in 691 s: the five Windows skips and the four published-classifier HIBAG tests. Nothing but documentation changed between that run and the
commit. `tests/test_agent_schema.py` now holds 52 tests. Five more guards
were each removed in turn and each removal failed a test: the shared kind in `pgx calls` and in
`hla calls`, the `version` kind, version 1's kind pattern, and the version bumped to 3 without
a digest. Full dbSNP card lint (119 cards, 594 renders, 65/65 keys), strict mypy over source,
scripts and tests (250 files), ruff, format and the fixture check pass.
