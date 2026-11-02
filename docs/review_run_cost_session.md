# Run memory, cost and resumability: session diff review

Scope: `fe5d617..5d48b41`, the eight commits after the M11.5 review that made a synthetic
end-to-end `genetics run` fit in memory, cut its cost, and made it resumable:

| Commit | Change |
|---|---|
| `33c2e29` | PLINK 2 is found before polygenic reference preparation |
| `ba94c2e` | one polygenic reference extraction held at a time; faster extraction-cache reads |
| `b9c2f34` | score records kept compressed; bundle format 25 (per-card score files) |
| `0f772ff` | every PLINK call capped at `--memory 4096` unless its caller sets one |
| `6c4643e` | first complete synthetic run recorded |
| `8c8d113` | bundle format 26 (guideline results by reference, records checked on stored bytes), parser and coverage hot paths, one dose read for all scores |
| `ed4f447` | saved run parts (`run/parts.py`); one dose read shared by card inputs, scores and PGx |
| `5d48b41` | saved parts written only once one exists; test sessions keep them private |

The review read every source and test change against the code it replaced, and ran the
first default imputed `genetics run` alongside it. It used synthetic inputs and a public
1000 Genomes stand-in only, and opened no personal genotype. Fixes are in `af40ed1`, and
the save's progress lines in the commit that adds this review.

## The imputed run

The synthetic export cannot be imputed. Its coordinates are invented, so only 9 of its
chromosome 1 markers fall on 1000 Genomes panel sites. Beagle then refused the first window:
"The window ending at 1:18871148 contains no reference markers", 10 minutes into the run.
The run therefore used HG00097, one of the public 1000 Genomes stand-ins retained from the
M9.9 acceptance (290,285 called autosomal markers at the array's positions). It was written
as an AncestryDNA-format export in the session's scratch directory and was never committed.
It has no sex-chromosome markers, so sex is ambiguous and imputation covers the 22
autosomes.

**First attempt (`5d48b41`, 2026-11-02).** Warm caches, 32 GB machine:

| Stage | Time |
|---|---|
| Score references, ingest | 4.5 min |
| Ancestry (both placements) | 2.3 min |
| Imputation, 22 autosomes | 2 h 31 min |
| One dose read: 81,272,000 records at 1,316,215 loci | 29 min (saved part 10.3 MB) |
| ClinVar coverage, runs of homozygosity, archaic | 10.5 min |
| 13 scores, then a PLINK crash on the 14th | 68 min |

Python peaked at 10.9 GB during scoring, and at least 10.8 GB stayed free. The saved
parts held 734 MB: 14 genome-wide imputed score records of about 62 MB each, the dose read
and the imputation metadata.

**The resume.** It took 21 minutes to reach the interrupted score:
- score references 4.5 min and ancestry 2 min;
- the imputation was reused after a 5-second digest check, and the dose read was loaded
  in 18 seconds;
- ClinVar and runs of homozygosity, recomputed, took 10.5 min;
- the 13 saved scores were reused at 10–20 s each.

The 14th score was rescored in 3.7 min, and PGx and HLA took 12 s from the saved read.
The save then failed on the ancestry mismatch below, 18 minutes in.

**The completed run (`af40ed1`).** After the fixes below, the run was started again on the
same export and data directory and saved, 4 h 59 min end to end:

| Stage | Time |
|---|---|
| Score references, ingest, ancestry | 6.5 min |
| Imputation, through its own resume path | 1 h 57 min |
| One dose read | 29 min |
| ClinVar coverage, runs of homozygosity, archaic | 10.5 min |
| 14 scores | 80 min |
| PGx and HLA | 17 s |
| Saving the run | 54 min |

The imputation stage did not reuse the earlier saved part, because the engine's source had
changed and the contract digests it. The stage's own resume path reused the 44 completed
Beagle jobs but re-read every panel's markers and re-validated every output. That took 1 h
57 min, against 2 h 31 min for a fresh imputation, so a fresh run of this export is about
5 h 30 min.

The save broke down as follows:
- 23 min to validate the copied dose evidence;
- 12 min to check the 14 score records against their cards, each record parsed in turn;
- 19 min to check the PGx calls against every saved dose;
- seconds for everything else.

Its last two steps printed nothing for 31 minutes; that is fixed below.

Python peaked at 10.9 GB, PLINK 2 at 1.4 GB, and at least 8.4 GB stayed free (the least was
during the save). The bundle holds 1.3 GB:
- 701 MB of score records;
- 466 MB of dose evidence;
- 132 MB for everything else.

The imputation cache holds 3.9 GB. The saved parts were removed once the bundle was
written. Reopening the saved run (`read_bundle`) took 52 min, with the test suite running
alongside; it repeats the save's checks.

## Findings and fixes

- **P2 — An interrupted run could not be saved after resuming.** Every polygenic record
  carries the run's ancestry, and the bundle refuses a record whose ancestry differs from
  the run's. A resumed run recomputes ancestry, and it was not reproducible: three
  processes placed the same export with three different digests, the 1000 Genomes fit
  values differing by up to 8.8e-16. Polars sums a group's rows in the order its threads
  deliver them, so the centroids, the pooled within-population spread and the ancient-group
  means varied in their last bit; with `POLARS_MAX_THREADS=1` the digests agreed. The
  resumed run reused 13 saved scores, rescored the 14th, and then failed its save on
  "Saved polygenic ancestry disagrees with the shared run placement".
  - Those three sums now use `math.fsum`, which is exactly rounded, through
    `populations.exact_group_means`. Three processes now give identical ancestry. The new
    test builds the model from three row orders and requires identical scale, centroids
    and threshold; it fails on the old code.
  - A saved score is now reused only if it carries the run's ancestry, and the saved PGx
    and HLA calls only if they were made under it (HLA's classifier is chosen from it).
    Otherwise they are recomputed with a progress line rather than failing the save.
    Tested; the score test fails without the check.
  - A saved imputation is also bound to the run's inferred sex.
- **P3 — `genetics run` printed a traceback for a polygenic scoring failure.** `PgsError` was
  missing from the refusals the command reports, so the PLINK crash below surfaced as a
  traceback. It is now reported, as kind `polygenic` under `--json`.
- **P3 — Beagle's failure message did not say where its private logs are.** It now names the
  attempt directory.
- **P3 — Saving an imputed run was silent for 31 minutes.** Checking the score records took
  12 minutes and checking PGx against every saved dose took 19, and neither printed anything
  after "Validating saved imputation dosage evidence". The save now announces each score it
  checks and the PGx pass, and the pass prints a record count at most every 30 seconds.
  Both new tests fail on the old code.
- **P4 — `docs/pgs_cards.md`** still said the single dose read keeps only score loci and is
  built by the polygenic stage; it serves card inputs, scores and PGx and is built by the
  pipeline. A sentence in `docs/pgx_guidelines.md` had been split from its paragraph.
- **P4 — `RunParts.terms` defaulted to empty bytes,** so a directly constructed instance
  could write an empty contract that the next open discards. It is now required.
- **Found before the review, in `5d48b41`:** a CLI test that expects `genetics run` to fail
  sets no data directory, and opening saved parts wrote a contract into the real cache.

## Checked without change

- **Extraction-cache reads (`ba94c2e`).** `bytes.translate(None, b"012")` is empty exactly
  when a dose row holds only 0, 1 and 2, so the dropped `max(d) > 2` check is still made, per
  row, before decoding. A cache removed between preparation and scoring is re-extracted,
  verifying each VCF against its lock again.
- **Format 25 (`b9c2f34`).** Every score file the manifest records is digest-checked with the
  other payloads before `_read_score_files` reads it; the schema-2 index must name exactly
  those files, and a score file below format 25 is refused. Names come from
  `score_file_name`, whose pattern admits no path separator.
- **PLINK cap (`0f772ff`).** The cap is appended only when the caller passed no `--memory`;
  the out-of-memory hint is added only under the wrapper's own cap; an override below
  PLINK 2's 640 MiB floor, or not ASCII digits, is refused naming the variable.
- **Format 26 (`8c8d113`).** A guideline card is restored only if every saved field and the
  rebuilt result's digest reproduce from the frozen PGx record; a result saved in full under
  format 26, or a reference under format 25, is refused. The score-record fast path is sound:
  the stored text's sha256 equalling the card's `score_sha256` proves the text is the
  record's canonical form, so skipping the re-serialisation loses no check.
- **Parser hot path (`8c8d113`).** `_row` validates both coordinate pairs in the same order
  with the same labels as before, and takes the used pair from that validation; `_position`
  accepts ASCII digits only, as `[0-9]+` did; `_all_str` is `all(isinstance(v, str))`.
- **One dose read (`8c8d113`, `ed4f447`).** Card inputs, the polygenic index and PGx each
  kept only the records at their own loci, in stream order, and each still does: the shared
  read holds every record at the union of those loci, grouped by locus in first-seen order,
  which is stream order because records at one locus are adjacent. Saving a run re-reads
  the full saved stream for the PGx check (`validate_execution`), so a read that lost or
  reordered a PGx record would fail the save. Tested directly for card inputs.
- **Saved parts (`ed4f447`, `5d48b41`).** Parts are keyed by the digest of a genotype-free
  contract (export, engine source, knowledge pack, reference lock, tools, options) and each
  file by its digest in the journal; a fresh imputation drops every part read from an earlier
  one; a failed save costs the resume only. The bundle writer checks reused parts exactly as
  it checks fresh ones.
- **Privacy.** Parts live under the cache directory, which `paths.app_write_paths` registers
  and the privacy suite checks; `run-parts/` and the existing `*.run.json`,
  `*.run.json.gz` and `*.dosages.jsonl.gz` rules cover them if copied into a checkout.

## Residual risks, recorded rather than fixed

- **PLINK 2 crashed once.** Scoring the 1000 Genomes reference samples for PGS002124, the
  last of 14 scores, the pinned PLINK 2 alpha exited with 0xC0000005 (access violation)
  and no message, with 15 GB of memory free. The identical rescoring on resume succeeded.
  Its work files are removed on failure, so there is no log to diagnose; resuming made it
  cost 21 minutes instead of the run.
- **Synthetic fixtures cannot exercise imputation.** Their coordinates are invented. A
  default imputed run needs an export at real array positions, such as the public stand-in
  used here.
- **Imputation's cost is in Python, not Beagle.** On chromosome 1, reading the panel's
  markers took 5.2 min and validating and writing the doses 3.5 min; Beagle's phasing and
  imputation took 44 s.
- **Saving and opening an imputed run each read the 81 million saved dose records twice:**
  the snapshot validation and the PGx check. Together with the score-record checks, that
  is the 54-minute save and the 52-minute reopen. Folding the PGx check into the snapshot validation's pass would
  save about 19 minutes on each.
- **This run is a stand-in.** It has 290,285 autosomal markers where the array has 677,436,
  and no X, Y or MT markers. Chromosome X imputation, sex inference and G6PD calling, and
  HLA on real MHC markers have not yet run at full scale. The first run on a real export
  will exercise them, and should take about 5¾–6 hours fresh.
- **Two concurrent runs of one export share a parts directory without a lock.** Each part
  is written whole and checked by digest, so the worst case is recomputation.
- **A reused imputation part is trusted by its file digests** rather than re-derived, as the
  imputation stage's own resume does. Its contract binds the export, sex, engine source,
  references and tools.
