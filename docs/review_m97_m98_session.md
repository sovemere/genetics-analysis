# M9.7–M9.8 session diff review

Independent sub-agent review on 2026-10-11 covered the complete working-tree
diff from `0a72d6c`, including staged, unstaged and untracked source, tests,
knowledge records, manifests and documentation. The user requested this review
after both milestones' native/public-stand-in acceptance. No branch, PR, commit
or push was created by the reviewer.

## Findings and corrections

1. **Frozen duplicate proofs admitted impossible allocations.** A source identity
   declaring three records could claim two distinct END groups with two copies
   each. The old removed-copy arithmetic accepted that proof even though four
   source records are required. A synthetic regression failed before the fix.
   Validation now checks the sum of copies allocated to distinct folded groups
   against the original identity's multiplicity. A second, valid fixed-seed case
   supplies two two-copy END groups and verifies that both distinct observations
   survive semantic hashing and frozen-proof validation. Normal single-group
   proofs and existing native reference caches keep their format and identity.

2. **CAD's quoted association belonged to the wrong population.** The authored
   card paired European-only N=297,772 with the overall validation incident HR
   1.73 (95% CI 1.70–1.76). The
   [primary Results and Figure 5](https://pmc.ncbi.nlm.nih.gov/articles/PMC10353935/)
   give European HR 1.74 (1.71–1.78). The card retains its European-only scope,
   corrects the effect and interval, and explicitly distinguishes the overall
   estimate. The synthetic shared pipeline/bundle/CLI/dashboard regression failed
   before the correction and now checks the effect, interval and population N.
   Native imputation and sums are unchanged; corrected cards are assembled from
   retained acceptance score records without recomputing scores.

Documentation also now marks both milestones accepted, identifies M9.9
psychometrics as the next open step, records M9.8's full-scale resource costs,
and corrects the roadmap's current bundle/card/lint summary. Historical checkpoint
numbers remain labelled as historical. The decoder docstring and imputation guide
now describe coordinate-local buffering and the lossless native exception precisely.

## Scientific and compatibility checks

The reviewer independently checked the health associations and mental-health
model-specific results against public primary-paper text through NCBI BioC.
The [breast-cancer Table 2](https://pmc.ncbi.nlm.nih.gov/articles/PMC6323553/)
supports PRS3820's independent prospective OR and sampled cohort counts.
The [schizophrenia Table 2](https://pmc.ncbi.nlm.nih.gov/articles/PMC6961974/)
supports Bayesian top-versus-bottom-decile OR 4.6 (2.9–7.3) and recorded prevalence
1.0% versus 0.2%, with 0.4% in the remaining 90%. The card explicitly identifies
that cross-site model-family comparison rather than claiming Geisinger-only or
per-SD calibration. It does not convert the displayed reference position to risk.

The [GPpsy paper's out-of-sample section and Figure 7a](https://pmc.ncbi.nlm.nih.gov/articles/PMC7906795/)
explicitly report full-sample Nagelkerke pseudo-R² 0.018 and AUC 0.56 at p-value
threshold 0.1. The broad help-seeking endpoint, independent depression evaluation,
full-sample versus downsampled distinction and UK Biobank-only release are retained.
The existing bounded `proportion` measure is qualified by the fit-index numerator
and normalization denominator; presentation does not call it biological variance
explained, a patient proportion or personal risk. Neither card invents a complete
matched ten-decile outcome series or within-family attenuation.

Review also covered full-reference coordinate streaming and lock digest validation;
native-equal folding only for identical complete phased GT vectors; distinct-END
preservation and conflicting-vector refusal; actual native-input/source binding
in frozen snapshots; typed/unverified/excess/collapsed output duplicate refusal;
and historical display-1 arithmetic versus display-2 both-phase coverage/quality.
No additional substantive defect was found in those paths.

## Validation and handoff

M9.8's pre-review native acceptance passed **2,873 tests, five existing Windows
skips** in 737.42 seconds. Both public stand-ins passed both mental-health models,
including saved-card validation. Full dbSNP lint passed 55 cards, 276 renders and
35/35 authored marker keys. Strict Windows Python 3.13 checked 200 files.

Post-fix card/display checks pass all **49 tests**. The combined card/proof run
passed 63 checks with one optional native check skipped; running that proof module
separately with the pinned Beagle/bref3 and Java 17 passed all **15 tests** in
22.09 seconds, including native duplicate failure, lossless execution/resume,
frozen snapshot checks and corrupt-cache refusal. Extended compatibility, saved
snapshot, streaming, parser and card checks passed 315 tests with one optional
native PGS skip. That earlier process retained the pre-correction CAD assertion
while authoring changed; its single stale assertion failure is superseded by
the fresh 49-test card run. Ruff check and formatting pass (236 files), as does
`git diff --check`.

Final parent verification passes **2,875 tests, five existing Windows skips** in
1,416.58 seconds. All four strict Windows/Linux Python 3.11/3.13 targets check
200 files; full card lint passes 55 cards/276 renders/35 marker keys. Lint/format,
fixture reproduction, whitespace and staged privacy checks pass. Corrected CAD
cards for both retained default-imputed and explicit no-impute score results pass
saved validation; the completed public imputation proofs pass the stricter
allocation check. These are the required checks before committing and pushing
directly to `main`. No acceptance artifacts or fetched payloads are included in
the diff. The reviewer used source code, public papers and fixed-seed synthetic
fixtures. No owner genome or private owner run, and no public-stand-in dosage,
score, percentile or individual-coverage artifacts, were opened or printed.
The synthetic dashboard screenshot exposed the compact-label issue addressed in
M9.7; no post-fix automated browser capture or manual detail confirmation is claimed.
