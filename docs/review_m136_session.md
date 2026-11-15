# M13.6 session diff review

Scope: `a8c0023..dc78ac0`. That is M13.6's walk-through (`docs/agent_usage.md`,
`tests/test_agent_usage.py`, `parity.command_problem`, the pointer in AGENTS.md §3 and the
documentation) and the CI fix that followed it (`testing/isolation.py` and two tests in
`tests/privacy/test_offline_end_to_end.py`). Every changed source line was re-read. What
the page states and no test held was checked against the code, and the ten facts were read
again in the saved full text of the two papers. The review opened no personal genotype and
no saved real run; the one run it read is the synthetic one the page's test builds.

## Findings and fixes

- **P2: the page said its query check catches more than it does.** Under "How this page
  is kept true" it said a query built from the run's result fails the check that every
  word of a query is one `cards evidence --json` prints. That check reads words and not
  meaning.
  - `rs7349332 one copy` passes it: the card's caveats print "one" and its effect line
    prints "copy". The page's own second rule gives "one copy" as the example of a query
    that tells a search engine a result.
  - The marker followed by its two alleles written apart passes it too, since the evidence
    prints each allele. `genetics.privacy` does not know that shape, which the M13.3
    record already says.
  - The three cases M13.6 tested (the genotype as one word, the tier, "heterozygous") do
    fail it, so the test passed and the sentence read as general.
  - The page now says what the check holds and what it does not, in "How this page is
    kept true" and under step 7. The test asserts that both cases pass the word check and
    the scanner, so the sentence fails when M13.7 closes either. The M13.7 contract names
    both as cases its lint has to catch.
- **P3: values the page names in prose were held by no test.** The run status `readable`,
  the five tier bases, the two call sources and seven error kinds are written in steps and
  tables, not in a shown output. All were right. A new test compares them with the agent
  schema's enumerations and with `contract.run_error_kind`, and runs `runs card` on an
  absent id for `card-not-found`.
- **P3: a command written without its first word was not checked.** The page writes
  twelve that way (`runs show --json`, `cards evidence --json`, `runs show --section`).
  The test looked only for `genetics ...`. It now checks 33 commands where it checked 24.
- **P3: `command_problem` did not know a flag's off form.** `genetics serve
  --no-access-log` was reported as written with an option the command does not take. No
  page or parity row writes one today. The off forms are now read with the rest.
- **P3: fact 7 named a table that holds three of its four signals.** Table 2 of Eriksson
  et al. lists the hair-curl loci near *TCHH*, *LCE3E* and *WNT10A*. The fourth, near
  *OFCC1*, is in the Results text at 0.1 points per allele with a score of 7.8, under the
  paper's 8.4 line. The fact now says so and names both places.
- **P3: fact 4 called six answers a "six-step scale".** Six answers are five steps. It
  now says a fifth of the distance from one answer to the next.
- **P3: wrong or stale statements about the runner.**
  - Four places said `ubuntu-latest` "became Ubuntu 26.04 on 2026-11-14". What the logs
    show is that this repository's run of 2026-11-13 09:52 UTC used the 24.04 image and
    its run of 2026-11-14 21:21 UTC the 26.04 one. They now say that.
  - `testing/isolation.py`, a test docstring and the roadmap's M4.10 entry said in the
    present tense that `ubuntu-latest` is Ubuntu 24.04.
  - The roadmap's row for the CI fix ended on "whether the fix holds is the Linux jobs'
    result for the commit that carries it". It held: run 43646245473 passed all five jobs
    on `dc78ac0`. The row, the module docstring and the handoff now say so.
  - The handoff's M13.6 record did not mention the CI fix or its two tests.
- **P4.** A comment was written twice in one test, and a variable holding an accepted
  query was named `refused`.

## Re-read and left as it was

- **The figures in the ten facts.** 5,385 and 22 traits; the allele frequency 0.14, the
  effect 0.193 and the score 13.48 (Table 2); the 8.4 line; Table 7's straight-hair shares
  and the three sums M13.6 made from it (81.8, 74.5 and 69.5, and 95
  people with two copies); 0.294 near *TCHH* and "about 6%" (Discussion); 16,763 people in
  three cohorts, rs74333950 at 3.98 × 10⁻¹⁵, 14 markers at AUC 0.66 and 0.64, and 0.62 in
  528 Polish people (Liu et al.). Each is in the text where the fact says it is.
- **`Isolation.command`.** Names only reach the command line. With no environment given
  it names this process's, which is what the child inherits. A name that could not sit in
  a comma-separated list is left out, and the candidate list and the method agree on
  where `-n` sits, which a test holds.
- **`command_problem` on the parity table.** With `needs_json` left on it refuses what it
  refused before. One thing it now accepts: a word after the command is an argument, so
  an option's value (`--section physical_health`) no longer reads as a subcommand.

## Recorded rather than changed

- **The word check is lexical, and M13.7 owns the rest.** A result told in the card's own
  words passes it. The rule on the page is what stops that today.
- **`command_problem` checks the command and its options, not its arguments.** A command
  written without a required argument (`genetics runs card`) or with a stray word after
  it passes. The page writes the first on purpose, in its table of commands.
- **No 24.04 runner has run the `--preserve-env` form.** `ubuntu-latest` is 26.04 now.
  The C sudo documents the option; a job pinned back to 24.04 is where it would be
  proved, and the probe would name a failure.
- **The list names every variable the child is handed**, about as many names as the
  runner exports. A sudoers policy that refuses one would fail the probe by name.
- **Still not confirmed by the owner:** the page's reading of AGENTS.md §1.3 for an agent
  on a hosted model (the cards asked about, read with the narrowest command).
- **Still open from M13.6:** Liu et al.'s Supplementary Table S6 was not opened; the
  comparison with the papers and the ten facts are prose no test holds; `uv.lock` predates
  two development dependencies and was left as committed.
- **Saved runs repeat their deep checks once.** This review edits Python source
  (`testing/parity.py`, `testing/isolation.py`), as M13.6 did.

## Checks

- `tests/test_agent_usage.py` holds 13 tests, one more than M13.6 shipped: the values
  named in prose. Three existing tests gained assertions: the short commands, a flag's off
  form, and the two queries the word check does not catch.
- Fifteen guards or statements were each changed in turn and each change failed a test:
  the off form of a flag, a group written as a command, a short command renamed, a short
  command's option renamed, a tier basis, a call source, the run status, an error kind
  changed, one dropped, `card-not-found` renamed, the sentence about the check's limit,
  an unnameable variable kept in the list, the names put before `-n`, `run` not using
  `command`, and `-E` put back in the candidate.
- No command's output, schema shape, bundle format, knowledge schema or card changed.
  The only production lines this review changes are in `genetics.testing`.
- The full native suite passes **4,297 tests with the same nine skips** in 962 s, on
  Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools configured: M13.6's
  4,294, the CI fix's two and this review's one. After that run only documentation
  changed. Strict mypy on all four Windows/Linux x Python 3.11/3.13 targets (258 files),
  ruff and format pass. No card changed, so the dbSNP card lint was not repeated.
