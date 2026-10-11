# Physical-health polygenic cards (M9.7)

The health pack adds two additive scores to the shared M9.6 pipeline. Both use
harmonized GRCh37 weights and the existing distribution, coverage, quality and
ancestry-portability calculation. A percentile position is not a disease probability.

| Card | Score | Authored rows | Published association used |
| --- | --- | ---: | --- |
| Breast cancer | [PGS000007, PRS3820_BC](https://www.pgscatalog.org/score/PGS000007/) | 3,820 | OR per study-standardized SD 1.66 (95% CI 1.61–1.70), European-ancestry women |
| Coronary artery disease | [PGS003725, GPS_Mult](https://www.pgscatalog.org/score/PGS003725/) | 1,296,172 | Incident CAD HR per study-standardized SD 1.74 (1.71–1.78), European-ancestry UK Biobank participants |

## Source audit

Checked against the primary papers on 2026-10-10:

- [Mavaddat et al., Table 2](https://pmc.ncbi.nlm.nih.gov/articles/PMC6323553/#tbl2):
  the overall-disease lasso model, evaluated independently in 11,428 cases and
  18,323 controls from ten prospective studies. PRS3820's overall-disease association
  was stronger than PRS313's in this test set. Those sampled counts are not an
  absolute population base rate. The studies have no common follow-up horizon.
- [Patel et al., Figure 5](https://www.nature.com/articles/s41591-023-02429-x#Fig5):
  incident disease in 297,772 European-ancestry participants: HR 1.74 (1.71–1.78).
  The paper's overall validation HR 1.73 (1.70–1.76) is not this subgroup's
  estimate; the session review corrected that population/effect mismatch.
  Discovery includes
  five ancestries; mixing weights were trained in 116,649 European-ancestry
  participants. The European hazard ratio is not assigned to other populations.

Neither card invents within-family attenuation or absolute decile rates. The
published percentile/quintile comparisons and combined clinical risk models do
not supply a complete, matched decile-rate series for these cards. A male run
still displays the breast-cancer score with its female-study limitation.

The fetched `pgs_all_metadata_scores.csv` classifies both scores under permissive
EMBL-EBI default terms. Article licences do not replace the score-specific metadata
authority. New manifest entries pin the measured file sizes, SHA-256 digests and
harmonization dates; both files were fetched, locked and verified. Payloads remain
uncommitted.

## Scale and compatibility

Authoring and scale acceptance exposed six engine requirements:

- Resolve each coordinate group while streaming the reference VCF. Retain all
  records at that coordinate, then release the raw calls; keep the compact doses
  and every exclusion state. Still verify the entire compressed file against its
  lock. Out-of-order coordinates fail, including unrequested ones.
- Accept the catalogue's `hg19`/`hg38` assembly synonyms and harmonized NCBI36
  sources. Select canonical coordinates without rewriting source headers. Unknown
  builds, contradictory metadata and mismatched requested builds still fail.
- Carry both phases' variant/row coverage and scored-weight shares in display
  schema 2, including explicit unavailable states. The face and detail use the
  same wording. Historical display-1 cards still re-derive their original
  summaries and counts exactly; bundle format 17 remains unchanged.
- Permit repeated untyped Beagle records only up to their verified reference
  multiplicity. The full chr3 panel itself repeats an exact variant; rejecting
  every repeat prevented genuine full-panel imputation from completing. The
  existing full reference decode now records these multiplicities. Both dosage
  records survive for conservative ambiguity handling. Typed repeats, unverified
  repeats, excess records and collapsed duplicates remain errors.
- Represent native-equal redundant reference records losslessly for Beagle.
  The genuine chr8 job rejected two SNP records with the same position,
  alleles and END; local comparison confirmed identical phased GT vectors
  across all 2,504 reference samples. Only such exact genetic redundancies
  are folded. All samples and distinct phased observations remain, the
  original panel is retained, and source/native semantic hashes and
  multiplicities are frozen with the actual native input. Conflicting
  phased vectors fail; different END values remain distinct. Both fresh
  native execution and saved dosage validation use the verified multiplicities.
  The original failure is reproduced on a fixed-seed synthetic panel with
  the pinned tool, followed by successful execution, resume, provenance
  validation and corrupted-cache refusal. No genotype is selected or invented.
- Use accurate summation for both display-quality numerators, matching their
  denominator. Genome-wide ordinary accumulation can otherwise round above one.
  Apply this in display schema 2 while preserving schema 1's historical arithmetic.

The memory regression used 600 fabricated loci and 1,000 synthetic samples.
The original extractor peaked at 28,119,995 traced bytes and failed the 8 MB
limit; the revised extractor passes. The existing duplicate-locus, allele,
ploidy, cache and digest checks remain covered. Neither the public extraction
format nor bundle format 17 changes.

Full extraction against the pinned 2,504-sample panel used four workers. Cold
measurements include full-panel digest verification and cache writing, with
one-second sampling of process-tree working set:

| Score | Seconds | Peak working-set bytes | Compressed cache bytes | Reference row states |
| --- | ---: | ---: | ---: | --- |
| PGS000007 | 721.97 | 345,579,520 | 1,392,868 | 3,334 resolved; 486 strand-ambiguous |
| PGS003725 | 5,824.38 | 5,634,416,640 | 420,329,012 | All 1,296,172 resolved |

These are reference-extraction counts, not an individual's score coverage.
Other acceptance jobs ran concurrently on this workstation; these are observed
resource costs, not isolated benchmark timings.

## Acceptance

Full card lint passes: 53 cards, 272 template renders, 35/35 variant keys resolved.
The authored cards also pass through fabricated score observations, the shared
pipeline, saved bundle, CLI JSON and dashboard. Published associations appear on
the card face. The compact interval label is HTML text above the SVG, so it stays
readable as the card narrows.

The phase-coverage regressions exercise a coverage gain on fabricated
observations, disabled imputation, historical reload, tampering and unknown
display versions. No personal point score or percentile is added to the display.

Native acceptance uses Java 17. Set `JAVA_HOME` to a Java 11+ runtime for bref3;
the older Java 8 runtime on this workstation cannot decode the pinned panels.
The pre-review M9.7 native suite after the quality-aggregation fix passes
**2,872 tests, five existing Windows skips** in 497.27 seconds.
All four strict Windows/Linux Python 3.11/3.13 type targets,
lint/format and byte-identical fixture reproduction pass.

Full-panel extraction and genuine default-on Beagle imputation of a public
1000 Genomes stand-in completed across all 22 autosomes, including both corrected
native references. Both default-imputed health scores passed. Their complete
combined evidence record is 2,857,833,480 bytes; no terms are omitted.
Observed scoring costs were 2,387.60 seconds / 454,098,944 peak working-set bytes
for PRS3820 and 3,007.31 seconds / 15,642,783,744 peak process-tree working-set
bytes for GPS_Mult. Combined record writing took 122.06 seconds. These include
the private evidence path and are execution costs, not predictive validation.
The second, explicit no-impute stand-in passed PRS3820 but exposed ordinary
display-quality accumulation rounding above one on GPS_Mult. Display schema 2
now uses `math.fsum` for both quality numerators, matching its denominator;
historical schema 1 keeps its original arithmetic. Three fabricated regressions
reproduce the failure before the fix; all 48 card tests pass afterward.
The failed stand-in and both retained default-score reload validations passed
on 2026-10-10 at 23:58. CAD saved-record validation took 173.61 seconds with
8,028,385,280 peak working-set bytes; the resumed no-impute CAD scoring/check/write
took 370.58 seconds with 10,901,987,328 peak process-tree working-set bytes.
All four strict type targets check 200 files successfully; fixture reproduction
and lint/format pass. M9.7 is accepted; the requested
[session review](review_m97_m98_session.md) also tightens frozen duplicate-proof
allocation across multiple distinct END groups.
The corrected European CAD effect/interval is reassembled from both retained
default-imputed and explicit no-impute score records; saved-card validation and
the completed imputation proofs pass. Final reviewed native suite: **2,875 passed,
five existing Windows skips** in 1,416.58 seconds, with all four strict type targets,
full card lint, formatting, fixtures and staged privacy scanning passing.
The lossless compatibility and saved-provenance focused checks also pass.
Resource measurements, per-score before/after
coverage and complete private score records stay outside Git. This input uses
public LD-pruned reference calls, not a consumer-array export; because the stand-in
is also in the reference, these checks validate execution, not predictive calibration.

Visual review used an owner-supplied screenshot of the synthetic dashboard, exposing
the compact label issue corrected above. This session has no connected browser,
so there is no automated post-fix browser capture. The updated synthetic demo
also shows before/after coverage. No personal export or private user run was opened.
