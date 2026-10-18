# HIBAG classifier imputation (M11.2)

## Contract recorded before implementation

HLA sample schema 1 is a new, separate evidence record. Bundle format 21 adds
hla.run.json; formats 1–20 read as HLA not recorded. Existing card, PGx and
imputation schemas and confidence calculations retain their meanings.

M11.2 uses an explicitly chosen European, Asian, Hispanic or African HLARES
hg19 classifier, never an automatic ancestry guess. M11.3 owns matching that
choice to ancestry and integrating posterior probabilities into confidence.
No dependency probe, missing model, unsupported marker or failed job is an
HLA-negative result. Unavailable stages carry a categorical reason and no calls.

Before personal input, verify the manifest-pinned model bytes, inspect the
complete locus/marker/HLA-allele metadata through the isolated R bridge and
validate it. Only diploid forward-strand original array SNVs at exact GRCh37
positions enter the matrix. Duplicate positions, no-calls, indels and incompatible
alleles stay explicit missing/unsupported states; rsID alone never joins a call.
Do not guess strand from the sample's allele frequency. Dosage counts the first
model allele (0/1/2), with missing values passed as NA. No sample frequency-based
strand flipping or independent Beagle hard-call substitution is performed.

Strand is proven from public reference allele sets only, and two sources vote:
the verified dbSNP b157 GRCh37 index and the lock-verified 1000 Genomes phase 3
chr6 VCF. A source proves a strand only when its single-base alleles at the
position fit exactly one reading of the model pair. Indel, MNP and structural
records at the same position abstain. Palindromic pairs, disagreeing sources and
a source whose SNV alleles fit neither reading leave the marker `unresolved-strand`.
Each frozen marker records which sources proved it (`strand_evidence`). Both
sources' rows at model positions are saved, so a run is re-validated offline.

Every locus retains its model SNP denominator, observed/missing/unsupported
counts, exact marker states, allowed HLA alleles, best unphased allele pair and
joint posterior probability. Zero usable markers is recorded as `no-markers`.
When HIBAG cannot issue a call after receiving usable markers, the locus is
recorded as `no-prediction`; its allele pair and posterior remain null. Neither
state is evidence against an allele or a negative clinical result. Low posterior
calls remain visible. The posterior is a model probability, not validated
individual accuracy or a clinical typing result.

Scientific output must match the private random sample token, exact locus set,
model marker order and matrix identity, model checksum and runtime identities.
Validate finite probabilities in [0,1], allele membership, complete output and
coverage before accepting any call. A successful R process alone is insufficient.
Save full frozen model metadata and sample evidence with checksums; saved reading
must need neither R, model payloads nor reference caches. CLI and dashboard
inspect the same validated saved record. Raw R diagnostics and arguments stay
in the existing private .hibag-work attempt directories; public errors are categorical.

## Source audit

The [publisher's HLARES page](https://hibag.s3.amazonaws.com/hlares_index.html)
and four ancestry release pages identify the original published classifiers as
2012-08-05, two-field (four-digit), with hg18/hg19 variants. Only hg19 is used.
The experimental hg38 position liftovers are not used. Training includes HLARES
European; Asian HLARES plus CHB/JPT; Hispanic HLARES; African-American HLARES
plus YRI parents. These are population-specific models, not universal panels.
[Zheng et al.](https://doi.org/10.1038/tpj.2013.18) describes the method.

The HIBAG software is GPL-3. The model pages publish the parameters explicitly
for imputation but do not display a separate model licence. Record this as
unresolved model terms, never inherit the package GPL or paper CC-BY silently.
Classifier acquisition/use therefore requires explicit source opt-in, retains
attribution and keeps payloads outside Git. This opt-in records the unresolved
terms; it does not manufacture permission for redistribution or derivatives.

Audit downloads live outside the checkout. Actual sizes and SHA-256 pins are
recorded in the reference manifest. R/HIBAG remain user-installed dependencies.
Native positive-path acceptance is required before claiming native imputation
has been verified; ordinary missing dependency states remain testable locally.

## Real-reference acceptance (2026-10-16)

Synthetic fixtures alone passed while two defects would have stopped every real
run. Both were found by validating the actual pinned models against the actual
local references, outside R. That check uses no personal data.

Model metadata came from the four pinned `.RData` payloads, parsed outside R in an
audit directory outside the checkout. All four pass `validate_metadata`: seven
loci, `hg19`, 500 classifiers per locus, two-field alleles, distinct positions,
and ACGT allele pairs only. None has a palindromic marker.

1. **The dbSNP proof could never validate.** The frozen-reference validator
   required provenance `schema_version` 1, while the only sidecar the producer
   writes is version 2. The synthetic fixtures used 1, so tests passed while
   `prepare` would refuse every real classifier. The frozen version is now
   `DBSNP_PROVENANCE_VERSION = 2`. Fixtures take the producer's constant, so a
   future producer bump fails the HLA tests instead of every saved run.
2. **dbSNP alone discarded 43% of model markers.** dbSNP b157 lists every
   submitted allele, so 448 of the European model's 1,042 positions are
   tetra-allelic there. Both the model pair and its complement then fit. The
   1000 Genomes panel resolves nearly all of them.

Strand proof per marker slot (a position shared by two loci counts twice):

| Model | Slots | dbSNP + 1000G | 1000G only | dbSNP only | Unresolved | Proven |
|---|---|---|---|---|---|---|
| European | 2,281 | 1,298 | 977 | 2 | 4 | 99.8% |
| Asian | 2,224 | 1,257 | 961 | 2 | 4 | 99.8% |
| Hispanic | 2,278 | 1,295 | 977 | 2 | 4 | 99.8% |
| African | 2,257 | 1,281 | 970 | 2 | 4 | 99.8% |

With dbSNP alone, 57% were proven. Every proven marker is on the forward strand;
none needed complementing. The four unresolved slots are one position
(chr6:32,686,103, model A/C). It is tetra-allelic in both sources and stays missing.
The two "dbSNP only" slots are chr6:31,147,094: 1000G encodes that C/T SNV inside a
longer complex record, which now abstains instead of contradicting dbSNP.
Reference preparation takes 37–50 seconds per model, mostly the full-file dbSNP and
1000G digest checks. Overlap with any particular array is not measured here; that
would need a sample.

## Validation

The final native-tool suite passes **3,417 tests with 12 skips** in 521 seconds.
Seven skips need the absent Rscript (two bridge checks and five HLA imputation
checks: one synthetic, four published-model). Five are existing Windows
OS-isolation and POSIX-mode limitations. Four strict Windows/Linux × Python
3.11/3.13 type targets check 224 files. Full dbSNP card lint passes 77 cards,
320 renders and 39 resolved keys. Fixtures reproduce byte for byte, and lint and
format pass. At that time native R/HIBAG prediction had not run anywhere: the R
scripts had been checked against HIBAG's source (`hlaPredict` accepts a raw
SNP-by-sample matrix aligned to the model), but not executed.

**Update 2026-10-18.** CI now installs R and HIBAG on its Windows and Linux runners.
The bridge checks and the synthetic native round trip pass there with R 4.6.1 and
HIBAG 1.48.2 (CI run 39089215382). In that round trip, R trains synthetic classifiers
and `calling.impute` predicts every locus through them. The first CI run found a
Windows-only defect: R 4.6.1's `Rscript` cut the bridge's multi-line `-e` bootstrap at
its first newline. The bootstrap now runs from a file in the private workspace.
The same day, prediction through all four published classifiers passed locally on
Windows with the same R and HIBAG versions (`test_native_published_classifier`, 38–60
seconds per model). Each model is prepared against the real dbSNP and 1000 Genomes
references, and the run returns predicted loci. The genotypes are synthetic, drawn at
the model markers. That establishes the path runs end to end, not that the calls are
accurate. CI cannot run this test, because it never downloads references.

## Local use

Fetch the classifier through the reference manager, acknowledging its unresolved
model terms, then select one classifier explicitly. Strand proof also needs the
derived dbSNP index (`dbsnp_b157_grch37`) and the lock-pinned 1000 Genomes chr6 VCF
(`thousand_genomes_phase3_grch37`); a missing or damaged copy fails the run loudly.

```text
genetics refs fetch --only hibag_hlares_european_hg19 --opt-in hibag_hlares_european_hg19
genetics run --input <local-input> --hla-classifier european --hla-model-opt-in
genetics hla calls <run-id> --json
```

M11.2 does not select a classifier from a sample. M11.3 will make and record that
choice from ancestry placement, and will decline rather than guess when the placement
cannot support a classifier.
