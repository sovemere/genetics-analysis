# Code health review (before M15.1)

Working file and to-do list for scope 4 of the
[project review](handoff.md#project-review-before-m151): test-suite time, duplication and
dead code. Scoped on 2026-11-22 at `02603e3` and run before M15.1 at the owner's request,
since no saved part of M15.1 exists yet and session 1 starts with `--restart`, so a source
change now costs that run nothing. The rules are
[scope 1's](review_project_engine.md#rules-for-this-review), with one more: **a change to
`src/genetics` must leave every output unchanged.** Code health is not a reason to change
what a run says.

Timebox: about 10 hours. Splitting the four modules over 2,000 lines (`refs/postprocess.py`,
`engine/cards.py`, `web/views.py`, `run/bundle.py`) is out of scope: high risk before the
release-gate run, low return. Recorded for after M15.1.

Every input is synthetic, fabricated or public. No personal export and no saved real run was
opened.

## To-do

- [x] **1. Test-suite time.** Parallel workers, and the slowest tests.
- [x] **2. Duplication.** The file lock copied in `external/beagle.py` and
  `pgx/locking.py`; the computed-card assembly repeated across six modules; the polygenic
  declaration built twice.
- [ ] **3. Dead code.** About four unreferenced members and about ten used only by tests.
- [ ] **4. Reconcile.** Status lines, `ci-local`, push, and the CI run.

## 1. Test-suite time (closed 2026-11-22)

**Measured first.** The full suite took **17 min 10 s** on one core here (4,474 passed,
53 skipped, `--durations=60`), and CI's test step about 21 minutes a job. The 60 slowest
tests summed to about 6 minutes; the other 11 were 4,400 tests at a fraction of a second each.
So no single test was the problem, and the lever was running them at once.

**Fixed: the suite runs across worker processes.** `pytest-xdist` is a dev dependency, and
CI's test step is `pytest -q -n auto`, which `genetics ci-local` follows since it reads the
workflow. With every native tool enabled (the three `GENETICS_*_TEST_TOOLS` variables and
Java 17), the full suite passed **4,518 with 9 skips** in:

| Workers | Wall-clock |
|---|---|
| 1 (before) | 17 min 10 s (without native tools) |
| 4, as on a CI runner | 5 min 57 s |
| 16 (`auto`, this machine) | 2 min 54 s to 3 min 6 s, three runs |

No test failed or needed isolating in four parallel runs. The suite already gave every test
its own temporary directory and `GENETICS_DATA_DIR`, and the session fixtures that redirect
run parts and checks are per worker, so there was nothing shared to collide on. **Decision:**
`-n auto` is not in `addopts`. A single test file would then start 16 workers, each
collecting the whole suite (about 12 s), which is slower than running it directly.

**Fixed: four slow tests**, measured on one core:

- **Search, 17 s and 14 s to 6 s each.** Every query tokenized and stemmed every card's
  text again, and that was nearly all of a search's time. `engine/search.py` caches a
  passage's words and stems by its text (`_passage`). It depends on the text alone, so a
  cached answer is the answer and every result is unchanged; the dashboard's search gets the
  same speed-up. This is the one source change, and it lands before M15.1's first session.
- **Carrier references, 3 × 11 s to 11 s.** Each test scanned the dbSNP index for its own
  rsIDs. One scan now reads every rsID the scope declares, and a test asking for one it does
  not declare fails rather than reading nothing. These run only where the references are
  fetched, so never on CI.
- **Repository content scan, 9.5 s to about 1 s.** It ran one `git show` per tracked file.
  It now reads every blob through one `git ls-tree` and one `git cat-file --batch`, still
  from `HEAD` rather than the working tree. Checked: for all 449 tracked files the bytes are
  identical to what `git show` returned.
- **PLINK timeout, 30 s to 3 s.** On Windows the stub is a `.cmd` launcher; killing it on
  timeout leaves its Python child holding the output pipes until the child's sleep ends, so
  the test always took the whole 30 s sleep. The stub now sleeps 3 s. Not a product defect:
  the real binary has no launcher between it and the kill, and M15.1 sets no timeout.

**Not changed: the parity tests**, about ten at 8–10 s each. Each re-renders every page
and runs the CLI about 126 times, because each proves that a changed value is caught. A
cache inside that checker could serve an unchanged answer to a test that changed one, so
the cost stays. Spread across workers, it no longer sets the suite's length.

**Also committed: `uv.lock`.** It predated the `jsonschema` and `types-jsonschema` dev
dependencies (M13.2), so every `uv run` in the checkout rewrote it. It now matches
`pyproject.toml`, including `pytest-xdist`. CI installs with `uv pip install -e ".[dev]"`
and does not read it.

## 2. Duplication (closed 2026-11-22)

**Measured first.** `pylint --enable=duplicate-code` (8 or more similar lines, imports,
docstrings and comments ignored) found 9 similar blocks in 63,000 lines of source, in five
clusters. That is little; three were worth removing, because in each a fix to one copy would
have missed the other.

**Fixed: one file lock.** Beagle's job lock and the PGx publication lock were the same
30 lines: a kernel lock on one byte, `msvcrt` on Windows and `flock` elsewhere, released by
the kernel when a process dies. Both now call `genetics/filelock.py`'s `exclusive_lock`,
each with its own refusal (`BeagleBusyError`, `ProcessError`) and message. The tests that
hold a lock in one process and expect refusal in another, and that kill a holder and expect
release, pass unchanged.

**Fixed: one constructor for computed cards.** Six modules built an `AssembledCard` for a
card whose result is a stage's computation rather than a matched genotype, each in 26
lines that differed only in the values: carrier scope, ClinVar coverage, long ROH, archaic
ranges, sex chromosomes and polygenic scores. They now call
`engine.evidence.computed_card`, which takes those values by name and builds the
`computation` record with the same six keys in the same order, since a bundle's digest
reads it. PGS is the one whose match reason differs from its summary, and passes
`match_reason`.

**Fixed: one polygenic declaration.** `genetics cards evidence` printed a polygenic card's
score, trait and decile outcomes from `engine/declaration.py`, and scoring built its result
from a copy of the same record in `pgs/cards.py`. Both now call
`engine.declaration.polygenic`, so what the card says it scores and what it scores cannot
drift apart.

**Not changed, with reasons:**

- **HLA and PGx cards** also build an `AssembledCard` by hand, but differ from the six in
  five fields (the card shown, confidence, citations, outcome name, risk context). Folding
  them in would give the helper as many options as the constructor.
- **The two vendor adapters'** shared lines are each one's closing call to
  `normalize_rows` and `ParseResult`. AGENTS.md §2 keeps adapters independent, and a base
  class to save twelve lines would couple them.
- **`engine/evidence.py`'s own four constructions** are the genotype-matching path, each
  with an observation, confidence and frequencies of its own.

**Output unchanged.** Every argument maps one to one onto the field it replaced (reviewed
line by line in the diff). The full native suite passed: 4,518 passed, 9 skipped. It
includes the parity tests, the saved-run round trips and the frozen historical bundles
that are re-read and re-assembled.
