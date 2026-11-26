# Handoff: post-M15.1 (code-health split, M15.5 real-run calibration, M15.7, M15.8)

Current state only. Each earlier milestone's entry contract and acceptance record, M7
to M14, is kept verbatim in [handoff_history.md](handoff_history.md); the dated record
of every milestone is the [progress log](progress_log.md).

As of 2026-11-26, **M0–M14, M15.1, M15.2, M15.3, M15.4 and M15.6 are complete**, and so are
scopes 1, 2 and 4 (except the deferred four-module split) of the
[project review](#project-review-before-m151). **[M15.1](#m151-record) passed** on the real
export in three offline sessions at `325116e` (`--hla-model-opt-in`, Windows Firewall option
A with Google Antigravity exempted). What remains before the v1 tag is under
[After M15.1](#after-m151): the deferred four-module code-health split (which the owner asked
to be reminded of as soon as M15.1 finished), the real-run half of **M15.5** (calibration
review), deferred scope-1 engine items, **M15.7** (README rewrite from M15.1's measurements),
the owner's `LICENSE` file, and **M15.8** (tag v1).

<a id="m151-record"></a>

## Accepted M15.1: full offline run on the real export

Run on 2026-11-26 from `325116e` (`--hla-model-opt-in`, imputation on, `--restart` in session
1 only), under Windows Firewall option A (`scripts/windows/m151/`) with Google Antigravity
exempted. **Passed** (exit 0 in session 3; bundle written outside the checkout; all saved
parts removed).

**Antigravity block trial (2026-11-25, before session 1).** Applied with `-AutoRestoreHours
0.5`, verified with `netblock.ps1 check` (Python, a Python child, and Rscript all refused),
confirmed Antigravity kept working on the PC and through phone remote control, and restored
cleanly: 0 refusals of Antigravity programs, 982 refusals of background apps over ~1.5 min.

**Sessions and wall-clock (not uninterrupted).** Total across three sessions: **475.9 min
(7 h 55.9 min)**, exercising the resume path across all saved parts on the real export:

| Session | Local window | Wall-clock | Resumed from | How it ended | Peak tree / min free |
|---|---|---|---|---|---|
| 1 | 08:41 → 11:06 | 145.5 min | fresh (`--restart`) | stopped at `Reading imputed doses once` | 4.09 GB / 13.37 GB |
| 2 | 13:27 → 17:27 | 240.1 min | `imputation` | stopped on `time: 4 h` (partway through save checks) | 14.55 GB / 0.81 GB |
| 3 | 18:02 → 19:33 | 90.3 min | `imputation`, dose read, 21 PGS, PGx, HLA | exit 0; bundle saved, parts removed | 13.87 GB / 3.94 GB |

**Stage timings vs the run-sheet estimate** (unique stages once: **~372.4 min / 6 h 12 min**):

| Stage | Expected | Measured | Notes |
|---|---|---|---|
| Score references, ingest, ancestry, HIBAG check | 10–30 min | 9.1 min | 7.2 min score refs + ingest, 1.9 min ancestry + HIBAG metadata/strand |
| Imputation (23 regions / 46 Beagle jobs) | ~3.5 h | 136.4 min | All 46 Beagle jobs matched and were reused from the verified Beagle job cache; time was reference marker reads, job verification, and saving the part (a cold run without cached Beagle jobs would add ~1.5–2 h) |
| One read of the imputed doses | ~50 min | 31.9 min | Faster than the 2026-11-05 baseline |
| ClinVar coverage, ROH, archaic | ~12 min | 11.0 min | Repeated in session 3 (`11.9 min`), as expected since these are not saved as parts |
| Polygenic scores (21) | ~3 h | 121.6 min | ~5.8 min/score vs the ~8.5 min/score estimate; zero transient PLINK failures |
| PGx + HLA (HIBAG) | seconds + untimed | ~10 s | First timed real-export HLA run; `rscript.exe` peaked at 0.23 GB |
| Saving & deep checks | ~75 min | 62.2 min | Session 3 (`28.1 → 90.3 min`), writing the deep-check record and removing parts |

**Peak memory and disk sizes.** Process-tree peak across all three sessions: **14.55 GB**
(session 2, minute 199.3). Per-program peaks: `python.exe` `14.54 GB`, `plink2.exe`
`1.46 GB`, `java.exe` `0.38 GB` (low because Beagle jobs were reused), `rscript.exe`
`0.23 GB`. Lowest free memory seen: `0.81 GB` (session 2). Disk sizes after completion:
saved bundle **2.27 GB**, cache **11.2 GB** (`0` saved parts remaining), tools **0.23 GB**.

**Network block (option A).** Verified by `netblock.ps1 check` before every session, held
without lifting across all three (`block_lifted_at: null` in all three summaries), and
restored cleanly after each. **Zero** outbound connection attempts by the run's own processes
in all three sessions (session 3's CSV contained 2 `python.exe` refusals outside the run's
process tree). Caveats to keep on the record: (1) Windows' default Security event log wrapped
under high-volume background app traffic, so the exported refusal CSVs covered the final 15 s
of session 1 (24,565 events), the final 11 s of session 2 (24,585 events), and 86 of 90.3 min
of session 3 (22,711 events); (2) DNS lookups via Windows' DNS client and the Store `pwsh`
package remain outside the firewall block, as documented below. Every outbound connection by
the run's processes was refused (none attempted).

<a id="m152-record"></a>

## Accepted M15.2: a structurally different synthetic export, end to end

Run on 2026-11-23 from `f3eb0a0` plus this record's fixes. **Passed**, after finding and
fixing two defects that would otherwise have reached M15.1.

**The export.** A female sample in the 23andMe-like layout (four columns, merged genotype,
letter chromosome codes, `--` no-calls), where every earlier full run was a male
AncestryDNA file. Rendered by the committed generator with no change to it:
`render_fixture(FixtureSpec(name="other_vendor_layout_female.txt", sex="female",
vendor="23andme"))` at the default seed (20260815) and 12,000 markers; written outside the
checkout and never committed. Run with `genetics run --input <it> --restart`, imputation on,
in a data directory of its own that shared only the installed tools and the public
score-reference cache.

**What held with no code change (the plug-and-play claim).** The vendor was sniffed as
`23andme_like`; QC inferred female (non-PAR X heterozygosity 35%, Y call rate 0) with no
warnings; every stage ran; all 119 cards were assembled, none dropped; the run saved, and
every agent read (`runs list --verify`, `runs qc`, `runs imputation`, `runs show`,
`runs clinvar`, `runs secondary`, `pgx calls`, `hla calls`, `runs card`) returned its
schema with exit 0; all twelve dashboard pages rendered and passed the accessibility audit.
No adapter, analysis module or card changed.

**Defect 1, fixed: one sparse chromosome ended the whole run.** Synthetic positions are
random, so chromosome 1 carried 12 typed positions across 249 Mb. That passes the "at least
two anchors" floor, but Beagle phases in windows of genetic distance and refused a window
holding a single position (`Window has only one position`), and on chromosome 6 a window
holding none (`... contains no reference markers`). The stage treated both as fatal. Now
`BeagleSparseTargetError` recognises both from the pinned build's own messages (as a heap
failure is recognised), and a refused region below 1 typed position per megabase is
recorded as `typed_calls_too_sparse`, runs no job and keeps its direct calls, while the
rest of the run goes on. A denser region that Beagle refuses still fails, since the second
message also asks whether reference and target agree: real arrays carry about 200 per
megabase, so this can only ever skip a region that is genuinely sparse. Successful jobs
take exactly the old path, and the policy string and static limitations are unchanged, so
every completed imputation cache and saved run stays valid. Of this run's 27 regions, 5
were imputed, 17 were recorded as too sparse and 5 had fewer than two anchors.

**Defect 2, fixed: `genetics run --restart` was "No such option".** The flag was declared on
`cli/run_cmd.run` but not on the command `cli/main.py` registers, so the M15.1 run sheet's
session-1 command would have failed at once, and nothing in the CLI could discard an
interrupted run's parts. The command now declares it, and a test requires the command to
declare every parameter the pipeline function takes.

**Defect 3, fixed, in the tests: a substituted knowledge pack outlived its test.** Found by
`genetics ci-local` before pushing this record, on Python 3.13 only:
`test_every_section_in_the_committed_pack_has_cards` saw zero cards in nine sections. The
dashboard reads and the reading guide cache the committed pack for the process, and three
tests in `tests/imputation/test_quality.py` replace `KnowledgePack.load` with a small test
pack. Whichever ran first on a worker filled the cache with it; in one process an earlier
test had always filled it with the real pack first, so it never showed until the suite ran
on parallel workers (code health item 1), which vary the order. Reproduced by running
`test_rare_imputed_snapshot_keeps_gate_native_evidence_and_scoped_ppv_in_both_views` just
before it. An autouse fixture in `tests/conftest.py` now clears the three caches after any
test that replaced the loader; with it the pair passes. No product code was involved.

**Not explained: one transient failure.** On the third attempt the reference distribution
for one polygenic score failed ("PLINK reference scoring failed; no reference distribution
accepted.") after three scores had succeeded. Resuming the same run, with identical inputs
and no source change, scored it and the remaining 17 without fault. The error is
categorical by design and PLINK's working files for that step are removed, so its cause
was not recovered; with 141 GB free it was not disk space. For M15.1 the consequence is
covered by the run sheet: a session that ends this way resumes with the same command, and
only the score in progress is repeated.

**Observed, not defects:**

- **Output sizes.** For this sample `runs show` printed 450 MB and `pgx calls` 389 MB of
  JSON, nearly all PGx guideline branches and candidate diplotypes: with so few typed calls
  every unresolved alternative is kept, as designed. A dense export resolves most of them.
- **`runs list --verify` always repeats the deep checks** (22 minutes here) whatever the
  saved record says; ordinary reads use the record and took seconds.

**Review of the fixes** (diff-driven, over every source and test change above):

- *Regression risk for M15.1:* none found. A successful Beagle job takes exactly the old
  path; a refusal in a region at or above the density bar raises, as every refusal did
  before. The fix can only turn an abort into a recorded region, and only for a region a
  real array is about 200 times too dense to be.
- *Resume and saved runs:* the imputation contract's policy string and the static
  limitations are untouched, so no completed imputation cache or saved snapshot stops
  matching. A refusal repeats deterministically, so a resumed stage records the same states
  and its metadata compares equal; a region whose phasing completed before its imputation
  was refused keeps a checkpointed phase job and is recorded the same way.
- *Readers of the new state:* the context validator holds it to resolved ploidy and at least
  two anchors with no job; the snapshot reader, the QC page and the agent schema treat
  region states generically. Older bundles never carry it.
- *Privacy:* neither new message repeats the position Beagle named; tests assert it for
  both stub wordings and the native refusal.
- *Tests:* each guard was neutered in turn and its test failed: the stage's catch (two
  stage tests), the validator branch, and the CLI flag (three CLI tests). Native tests hold
  both refusal wordings to the pinned Beagle build and run on both CI operating systems.
- *Left as is:* the density bar is a constant, not a model of Beagle's windows, on purpose;
  reproducing Beagle's windowing would be more fragile than the margin it protects.

**Timings** (this machine, not comparable with M15.1's): the failed first attempt ended
after 16 minutes; the third ran 2 h 45 min through imputation, ClinVar, ROH, archaic and
three scores; the resume took 1 h 32 min for the other 18 scores, PGx and the save.


<a id="next-open-step-m151-full-run"></a>

## Next open step: M15.1 full run on the real file

M15.1: a full run on the real file, offline, start to finish, recording wall-clock and peak
memory in the progress log, and re-running M4.10's OS-level network block at full pipeline
scope. Nothing has been selected or verified beyond what is listed here.

What already exists:

- **The run.** `genetics run --input <export>` with imputation on by default (AGENTS.md
  §4.3), writing outside the repository (§1.5). `genetics ci-local` and the suites run every
  stage on synthetic data only.
- **The OS-level block (M4.10)** is `genetics/testing/isolation.py`: a Linux network
  namespace (`unshare --map-root-user --net`, or `sudo -n --preserve-env=<names> unshare
  --net` where isolation is required). **Windows has no unprivileged mechanism and skips.**

What is open:

- **This is the owner's step.** It opens the real export, so an agent may run it only when
  the owner asks, and nothing from it (a card, a count that echoes a call, a log line) goes
  into a commit, an issue, a search or a prompt (§1.1, §1.3). Only wall-clock, peak memory,
  stage timings and pass or fail belong in the progress log.
- **The network block is decided: option A, a Windows Firewall block (2026-11-23).** M4.10's
  namespace skips on Windows, and the owner chose a firewall block of every outbound
  connection on the machine, with the coding agent's own programs as the one exception
  (Claude Code then; Google Antigravity since 2026-11-25, [below](#m151-network-block)), over WSL2
  or per-program rules. It is in `scripts/windows/m151/` and was tested; see
  [the network block](#m151-network-block) below.
- **Peak memory** is sampled across the run's whole process tree (Beagle's JVM, PLINK, R) by
  `scripts/windows/m151/run_session.ps1`, which also runs each session (run sheet item 5).
- **When:** the owner will start M15.1 later; it is prepared, not started.

<a id="project-review-before-m151"></a>

### Before M15.1: the overall project review (scopes 1, 2 and 4 done; 3 in part)

Every milestone was reviewed on its own diff; on 2026-11-20 the owner was proposed four
scopes that read the project whole. A change to Python source under `src/genetics` between
M15.1's sessions stops the saved parts being reused, so each scope's engine changes land
before session 1 or wait until M15.1's bundle is saved.

| Scope | State | Record |
|---|---|---|
| 1. Engine correctness and consistency | **Done** 2026-11-21. One P1 fixed: the likely-artifact gate could not fire for any allele gnomAD had seen, so M15.1 will screen far more rare calls as likely artifacts than the 2026-11-05 run did. P3s and later items recorded | [review_project_engine.md](review_project_engine.md) |
| 2. Release-gate audits needing no real file (M15.3, M15.4, M15.6) | **Done** 2026-11-22. Nothing genotype-derived was ever committed and two leak routes were closed; the lock, vendored files and per-score PGS terms hold; all 200 cited identifiers resolve and none is retracted. The three correction notices left for a browser were read on 2026-11-23; none changes a card | [review_release_audits.md](review_release_audits.md) |
| 3. Documentation | **In part** 2026-11-23: this file and the roadmap were cut back to current state, their history moved verbatim to [handoff_history.md](handoff_history.md), [roadmap_history.md](roadmap_history.md) and [progress_log.md](progress_log.md). The README rewrite stays with M15.7, after M15.1 | this file |
| 4. Code health | **Done** 2026-11-22. The suite takes about 3 minutes, not 17; one file lock, computed-card constructor and polygenic declaration replace copies; eight unused members are gone; no output changed. Splitting the four largest modules waits for after M15.1 | [review_code_health.md](review_code_health.md) |

**Owner action before the v1 tag:** the repository has no `LICENSE` file, though
`pyproject.toml` declares MIT.

<a id="m151-run-sheet"></a>

### M15.1 run sheet (prepared 2026-11-20, not yet run)

**Expected duration: about 9–10½ hours of unattended run**, plus HLA (opted in, not yet timed), and
the network-block setup below. This is an extrapolation from the one measured real-export
run (7 h 49 min on 2026-11-05, `e30879d`), scaled for the polygenic cards added since: 21
now, 14 then. That run's own estimate (5¾–6 h) was about 30% low, so read the range as a
floor.

| Stage | Measured 2026-11-05 | Expected for M15.1 | Why |
|---|---|---|---|
| Score references, ingest, ancestry | 7.4 min, warm | 10–30 min | the seven newer scores' 1000 Genomes extractions are not cached |
| Imputation, 23 jobs | 3 h 31 min | about 3.5 h | fresh: the engine changed, so no saved part is reused |
| One read of the imputed doses | 51.5 min | about 50 min | |
| ClinVar coverage, ROH, archaic | 12 min | about 12 min | |
| Polygenic scores | 1 h 59 min for 14 | about 3 h for 21 | about 8.5 min a score on the real export |
| PGx | 11 s | seconds | |
| HLA | did not run | not measured | HIBAG classifiers not fetched; R subprocess |
| Saving | 67 min | about 75 min | about 1 min of checks per added score |

Memory should stay near the last peaks (Python 14.7 GB, Java 4.3 GB, at least 6.9 GB free):
scores load one at a time, so seven more add time, not memory. The save writes the
deep-check record, so the first read afterwards should take seconds, not 54 min.

**Before starting** (checked 2026-11-22 with `genetics refs status`, `genetics tools
status` and `genetics doctor`, after the project review's scopes 1 and 2):

1. **The network block is option A (decided 2026-11-23)**: Windows Firewall refuses every
   outbound connection except the coding agent's (Antigravity's two programs since
   2026-11-25), for the length of each session. See
   [the network block](#m151-network-block) for how it works, how it was tested and what it
   does not cover. WSL2 was not chosen: it needs the references (63 GB of gnomAD exomes
   alone), tools, Java 17 and R inside Linux, and its timings would not be comparable.
2. **HLA is included (decided 2026-11-23).** The owner opted in to the four HIBAG
   classifiers, whose model licence M15.4 confirmed is unestablished rather than
   prohibitive; they are fetched, recorded in the lock with `opt_in_granted`, and `refs
   status` reports them complete. R 4.6.1 and HIBAG 1.48.2 are installed, `doctor` reports
   them ready, and the native HIBAG tests (`tests/hla/test_native.py`, with
   `GENETICS_HIBAG_TEST_REFERENCES` set to the references root) pass against the fetched
   files. **Every session's command therefore carries `--hla-model-opt-in`**, since the
   parts are reused only under the same options.
3. **References.** Every source a shipped stage reads is complete and in the committed
   lock: all 21 polygenic score files, the Y tree (recorded at M15.4; it had been missing),
   and PharmGKB and CPIC with their recorded opt-ins. Missing, and read by no shipped stage:
   `gwas_catalog`, `panukbb_manifest`, `finngen_r12` and the optional gnomAD genomes.
4. **Java 17** on `JAVA_HOME`, at
   `%LOCALAPPDATA%/genetics-analysis/tools/java17/jdk-17.0.20.1+1-jre`: the machine's default
   `java`, which `doctor` reports, is Java 8, and the pinned bref tools refuse it. The other
   pinned tools (PLINK 2, PLINK 1.9, Beagle, bref3, unbref3) are installed.
   `run_session.ps1` sets `JAVA_HOME` and `PATH` to it for the run.
5. **Peak memory is sampled by `run_session.ps1`**: every 5 s it sums the working set of the
   run's whole process tree, and keeps each program's own peak as Windows tracks it
   (`PeakWorkingSetSize`, so a spike between samples still counts) and the lowest free
   memory seen.
6. **Run `genetics runs list --verify` first:** engine source has changed since the last read
   of a saved run (the review's fixes), so the dashboard would otherwise pay that check later.
   It repeats the deep checks for every saved run, about an hour per imputed run, whatever
   their records say (M15.2).
7. **The data directory must be outside the checkout.** Since M15.3 the app refuses one that
   resolves inside it, from `GENETICS_DATA_DIR` or from `LOCALAPPDATA`. Run from an ordinary
   shell, not a sandbox that redirects `LOCALAPPDATA`. `doctor` reported 143 GB free. The
   `.sandbox_localappdata/` a 2026-10-16 sandbox left in the checkout (12 public score
   reference distributions) was deleted on 2026-11-23.
8. **Expect more `likely-artifact` tiers than on 2026-11-05.** The engine review's B1 fix lets
   the rare-call gate fire for alleles gnomAD has seen once; that is the fix working, not a
   regression. **Expect higher tiers on the trait and nutrition cards too:** the M15.5
   pre-run review priced their non-coding loci from 1000 Genomes, so 21 cards are no longer
   held at `moderate` for want of a frequency (the counts are cached; about 3 min uncached).
   `bnc2_freckling` drops to `moderate` under the new replication ceiling. Record the commit
   the run starts from.
9. **Rewrite CRLF working copies as LF first** (found by the code health review; done on
   2026-11-23, re-check before session 1). A run
   digests the engine source, the knowledge pack and the tools manifest as they sit on
   disk, and 60 tracked files here have CRLF or mixed endings, including 24 under
   `src/genetics`, a knowledge file and `data/tools.yaml`. Git normalises them, so status is
   clean, but the run would record digests a fresh clone of its commit cannot reproduce.
   List them with `git ls-files --eol | grep -E "w/(crlf|mixed)"`, then delete each and
   `git checkout -- <path>` it, before session 1 and never between sessions: an editor that
   flips a `.py` file's endings changes `engine_sha256`, and the saved parts are not reused.

**The command:** `genetics run --input <export> --restart --hla-model-opt-in`, with imputation
on (the default).
`--restart` discards parts left by an earlier interrupted run, so the timings are of a run
from the start. Use `--restart` for the first session only; see the next paragraph. Progress goes to stderr; keep it, since it carries the stage timings.
Until M15.2 this flag was not reachable from the command line; it is now, and a test holds it.

**Each session runs through the scripts, in this order** (all in `scripts/windows/m151/`,
started with `powershell -ExecutionPolicy Bypass -File <script> ...`):

1. `netblock.ps1 apply`: a UAC prompt, then the block (see [below](#m151-network-block)).
2. `run_session.ps1 -Export <export> -Session <n>`, from Windows PowerShell, not the Store
   `pwsh` (which its own package rule exempts from the block). It runs the command above
   (`--restart` in session 1 only) after refusing to start unless `netblock.ps1 check`
   proves the block, the checkout is clean with no CRLF working copy (item 9), and, in
   sessions 2 and 3, the commit and environment (installed packages, R and HIBAG, Java, the
   `GENETICS_*` overrides) are those session 1 recorded. Session 1 stops itself at the
   line in the table below; a later session stops itself at once if the run is not
   resuming. `-StopAfterHours 4` ends session 2. Parts are written whole and renamed into
   place, so a stop loses only the part in progress.
3. `netblock.ps1 restore` (a UAC prompt), then `netblock.ps1 report`.

`run_session.ps1` keeps the run's stdout and stderr whole under
`%LOCALAPPDATA%\genetics-analysis\m151` and writes `session-<n>.summary.json` beside them:
wall-clock, how the session ended, whether it resumed, peak memory, whether the block held
throughout, the process ids of the run's tree, and each progress line timed from the start
with every digit and digest masked. An agent reads the summary, never the raw logs. It was
tried on 2026-11-23 on a synthetic export, without the block: session 1 stopped on time and
took its whole process tree down; session 2 saw that nothing was saved and stopped before
redoing work.

**If a session stops on an error, resume it.** M15.2 saw one transient "PLINK reference
scoring failed" that the same command, without `--restart`, then got past; only the score in
progress is repeated. Record the error line (it is categorical and names no genotype).

**Running it in sessions.** The run does not have to be one sitting. `genetics run` saves
its long parts as they finish (`run/parts.py`): the imputation, the dose read, each
polygenic score, and the PGx and HLA calls. Running the same command again without
`--restart` resumes after the last one saved. `genetics run` has no option to stop at a
stage, so `run_session.ps1` ends each session at a line that follows a saved part:

| Session | Covers | About | Stop at |
|---|---|---|---|
| 1 | score references, ingest, ancestry, imputation | 3¾–4 h | `Reading imputed doses once for card inputs, polygenic scores and PGx ...`, which is printed just after the imputation part is saved; `run_session.ps1` stops there by default |
| 2 | dose read, ClinVar, ROH, archaic, most scores | about 4 h | any point once the dose read is done (`-StopAfterHours 4`); each score is saved as it finishes, so only the score in progress is lost |
| 3 | the remaining scores, PGx, HLA, saving | 1½–2½ h | runs to the end; the saved parts are removed once the bundle is written |

- **Start session 2 and 3 with the same command, without `--restart`.** The first line must
  read `Resuming an interrupted run of this export from its saved parts: imputation, ...`.
  If it reads `Saving this run's parts as they finish ...` instead, the parts were not
  matched; stop at once, or imputation runs again from the start.
- **Change nothing between sessions.** Parts are reused only under the same export file,
  the same Python source under `src/genetics` (by content, `checks.engine_sha256`), the same
  knowledge pack, reference lock and tools, and the same options, so `--hla-model-opt-in` is
  decided before session 1. Templates, styles and docs do not count; a `.py` edit does. Any
  code change from a project review waits until the bundle is saved, or lands before
  session 1.
- **Keep the environment fixed too** (project engine review F1). The parts' contract does not
  name the installed Python packages or the `GENETICS_BEAGLE_JAR`, `GENETICS_RSCRIPT` and
  `JAVA_HOME` overrides. A reused part keeps its own provenance, so nothing false is saved,
  but a resume across such a change mixes tool builds between parts. Do not `uv pip install`,
  upgrade R or HIBAG, or change those variables between sessions.
- **Each resume repeats some work:** ingest, ancestry and the score references (from their
  cache), and reopening the saved imputation by its dosage files' digests (4.6 GB to hash;
  not yet timed). ClinVar, ROH and archaic (about 12 min) are not saved as parts, so each
  session that gets past the dose read computes them again. Record each session's start,
  its resume overhead and its stages.
- **The network block** must be in place for every session, not only the first;
  `run_session.ps1` refuses to start without it. Lift it between sessions, since it takes
  the whole machine offline but for the coding agent.
- **What this measures.** The stage timings stay comparable with the table above, and the
  sum of the sessions less their resume overhead estimates an uninterrupted run. It is not
  an uninterrupted wall-clock; say so in the record. It also exercises the resume path on
  the real export, which the 2026-11-05 run did not.

**What to record, and where.** In the [progress log](progress_log.md) and the M15.1 record here: the
commit, wall-clock in total and per stage, peak memory per process and free memory, bundle
and cache sizes, whether every outbound request was refused by the block, and pass or fail.
The session summaries hold all but the sizes; `netblock.ps1 report` gives the refusals,
and the pass for the block is zero connection attempts by the run's own processes.
Never results, card outcomes, per-sample counts or anything a stage printed about the
genome (AGENTS.md §1.1, and the 2026-11-05 history rewrite). Then compare the stage times
with the table above, and say which estimate was off and why if that is known.

<a id="m151-network-block"></a>

### M15.1 network block: option A (decided and tested 2026-11-23)

**What it is.** `netblock.ps1 apply` sets every Windows Firewall profile to block outbound
traffic by default, adds an allow rule for each executable of the coding agent it is run
from, found among its parent processes (so the agent driving the run keeps working;
`-AllowProgram <path>[;<path>...]` names them instead, and `-AllowProgram none` exempts
nothing when the owner runs it alone), and turns on auditing of refused connections (Security event 5157, which
names the program and process id). It saves the settings it replaced and schedules a
restore as SYSTEM after 8 hours, longer than any session, which also runs after a reboot.
`netblock.ps1 restore` puts the saved settings back exactly, removes the rule and the task,
and exports the refusals to `%LOCALAPPDATA%\genetics-analysis\netblock`, outside the
checkout. `netblock.ps1 check` proves the block by connecting to 192.0.2.1 (TEST-NET-1,
routed nowhere) from the run's Python, a child of it and Rscript: the firewall refuses at
once, while without it the attempt can only time out, so no host is contacted either way.

**Why this and not the alternatives.** It covers every program, including ones nobody thought
to list; per-program rules (option B) are only as complete as their list, and the run's
`python.exe` is uv's launcher for a base interpreter elsewhere, which is the process that
would connect. Airplane mode leaves no record of what tried. WSL2 is noted under item 1.

**The trial.** With the block on, from both Git Bash and the Store PowerShell: Python, a
Python child, curl and Rscript were all refused with WinError 10013 (a firewall refusal),
every attempt appeared in the audit with its program, Claude Code kept working, and none of
its connections was refused. The automatic restore then fired on time and left the profiles,
rules and network as they were before.

**The agent is now Google Antigravity (2026-11-25).** The trial above ran under Claude Code,
whose one executable, `claude.exe`, `apply` found among its parent processes. Under
Antigravity no `claude.exe` is there and `apply` would have refused to start. A shell here
runs under Antigravity's `language_server.exe` (which makes the agent's model calls), under
`Antigravity.exe`, and both hold connections of their own; `apply` now finds either agent
and adds one allow rule for each of Antigravity's two executables (`-AllowProgram` takes a
`;`-separated list). A rule exempts an executable path, not a process tree, so the run's
`python.exe`, Java, PLINK and R, started from the agent's shell, are refused as before. The detection was checked without applying a block, and the block itself was **tried under
Antigravity on 2026-11-25** (0.5 h auto-restore, `netblock.ps1 check` passed, Antigravity
kept working on PC and via phone remote control, 0 refusals of Antigravity, clean restore)
before M15.1 ran on 2026-11-26.

**What it does not cover, to state in the record:**

- **DNS lookups still leave the machine**, through Windows' DNS client service, which a
  built-in rule allows and the agent needs. A lookup carries a host name, never data, and
  the connection after it is refused and logged. Say "every outbound connection was refused",
  not "nothing left the machine".
- **The Store build of PowerShell is exempt** through its package's own allow rule. The
  pipeline never starts PowerShell (nothing in `src/` does), programs started from it were
  refused in the trial, and `run_session.ps1` is run with Windows PowerShell for that reason.
- **The whole machine is offline but for the agent** while it is on: the trial's 15 minutes
  refused about 4,700 connections from browsers, chat, game and sync clients.
- **Java and PLINK were not probed by name.** The block refuses every program but one, so a
  probe of each would test the same rule; the audit would name them if they tried.

What M14.7 hands over:

- **`genetics.testing.accessibility.audit(html, page=True)`** lists a page's markup
  problems; a new page or partial is audited by adding its address to `PAGES` in
  `tests/web/test_accessibility.py`, or, for a run only another suite saves, by calling
  `audit` there as `tests/web/test_ancestry_page.py` does.
- **A card face's link is its title** (`h3.cardtitle > a.cardlink`, `h4` in the assay-limit
  block). A test that looked for the title as the heading's whole text now finds it inside
  the link. The face's layout and the stretched link's positioning are on `.cardface`, which
  only `_cardface.html` sets; `.card` is also worn by the ClinVar sections and the PGx gene
  faces, so a face-only rule goes on `.cardface`.
- **`nav_page` and `nav_search_landmark`** are set by a page template with `{% with %}` around
  the nav include; they are not context keys, so parity has nothing to place.
- **Not done:** no screen-reader session (NVDA, Narrator) was run; the audit checks markup.
  *Done 2026-11-23:* the theme toggle now says its new state in a polite live region, every
  table has a caption (ClinVar, HLA, PGx, the polygenic and card reliability tables, four on
  the guide, one in the carrier scope), and the audit fails a table without one.

<a id="after-m151"></a>

### After M15.1

- **Remaining code health work (scope 4), which the owner asked to be reminded of as soon as
  M15.1 is done:** split the four modules over 2,000 lines, `refs/postprocess.py`,
  `engine/cards.py`, `web/views.py` and `run/bundle.py`. It was deferred because a large
  refactor just before the release-gate run risks a late-pipeline failure. Any engine change
  after M15.1 means the tagged code differs from what M15.1 ran; say so in the record, or
  re-run.
- **M15.5**, the calibration review, whose half that needs no real file was done on 2026-11-23
  ([record](review_m155_prerun.md)); **M15.7**, the README rewrite from what M15.1 measured;
  the owner's `LICENSE` file; then **M15.8**, the v1 tag.
- The scope 1 items recorded for after M15.1 ([review_project_engine.md](review_project_engine.md)).
  C2 was fixed before M15.1 instead, and scope 2's three unread correction notices were
  read on 2026-11-23.
