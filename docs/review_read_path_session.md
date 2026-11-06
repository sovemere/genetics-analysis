# Opening saved runs and the history rewrite: session diff review

Scope: `3463902..209c2a9`:

| Commit | Change |
|---|---|
| `2cc42a6` | the current docs' commit citations pointed at the rewritten history |
| `37e9a37` | records of passed deep checks (`run/checks.py`); one opened copy in the dashboard |
| `209c2a9` | the read path's acceptance on the real run recorded |

The review read every source and test change against the code it replaced. It used
synthetic inputs and the committed knowledge pack, and neither opened a personal genotype
nor read the saved real run. The fixes change no check and no saved format.

## Findings and fixes

- **P2 — A record could name code that never ran the checks.** `checks.record` read the
  engine's source when the checks ended, not when they began. They take about an hour, a
  run takes about eight and a dashboard stays up for days, so source edited meanwhile was
  recorded as having passed. Later reads under that edit then skipped checks it had never
  run, including any check the edit had just tightened. A scratch script reproduced it
  first: with the file changed before `record`, `passed` answered true for the edited
  source. `engine_sha256` is now read once per process, at import, before any check can
  start, which is how the manifest's digest was already handled. A dashboard left up across
  an edit is still running the old code, so it records the old digest, and the next process
  repeats the checks. Saved parts' contract uses the same digest and gains the same
  property.
- **P3 — `checks.passed` could raise on a source file it could not read**, against the
  module's promise that a record's failure never fails a read. That now counts as no
  record, so it costs one repeat of the checks.
- **Test gap — nothing checked that pages leave the shared copy alone.** Before this change
  each page had its own copy, so a page that changed one harmed nothing. None does:
  `secondary_view` builds new mappings, and `validate_secondary`, the one `pop` near this
  path, works on a deep copy. A new test renders every page of a synthetic run twice,
  compares the two, and compares the held copy with a fresh read. It covers the card kinds
  in that fixture, not a full imputed run.
- **Documentation gap.** Nothing said that the dashboard's first page pays a repeat of the
  checks, or that a saved run never gains a section added later. The README and handoff now
  do.

Each of the four guards was removed in turn and its test failed; that covers the fresh
source read, the comparison outside the `try`, the digest at import, and a page changing
the shared copy. `genetics ci-local` passes 29 of 29 steps.

## What this costs

The fix changes the engine's source, so no saved run's record matches it. The first read of
each saved imputed run repeats its checks once, about 54 minutes on the real export, or
`genetics runs list --verify` does all four saved runs in about 58. That was not run for this
review: the acceptance figures in [the handoff](handoff.md) describe the engine at `209c2a9`,
and the fix does not change what a read does once a record matches. Any later source change,
M11.6's included, would have had the same effect.

## Checked, no change

- **A save runs all four deep checks before writing a record.** `write_bundle` calls
  `imputation_snapshot.publish` (which ends in `validate_snapshot`), `validate_lookup`,
  `_check_polygenic` and `validate_execution` over the staged doses.
- **Their verdict depends on nothing a record does not cover.** None of them reads a
  reference, the knowledge pack or the tools directory. The only non-Python files under
  `src/genetics` belong to the dashboard's pages, so hashing `.py` files alone misses nothing
  they use.
- **The 114 dashboard pages recorded from the real run are not a per-sample count:** 100
  cards, 8 PGx genes and 6 other pages, all set by the knowledge pack.
- **Every citation of this repository's commits in the current docs resolves.** The three
  strings that do not are not its commits: Y-LineageTracker's pin (`82b14c7`), an MD5 and an
  external repository's commit.
- **Every commit in the range has the noreply address** as author and committer.

## Known limits, unchanged

- The engine digest covers this package's source, not its dependencies. A library upgrade
  that changed a verdict would go unnoticed until `genetics runs list --verify`.
- A module imported late could load source edited after the process started. The record then
  names the older digest, so the next process repeats the checks; it errs towards a repeat.
- The dashboard keeps a deleted run's copy in memory, about 2.4 GB, until it opens another.
  It stops serving that run at once.
