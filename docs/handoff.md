# Handoff: M7.1 ClinVar lookup

As of 2026-10-04, M0–M6 are complete and the diff-driven review of M6.2–M6.4 and
the CI resolver fix is committed as `1c1c2ec`. Read [AGENTS.md](../AGENTS.md) first,
then [the roadmap](../phase1_roadmap.md). Its milestone checklist remains authoritative.

## Ready to proceed

**M7.1 can start immediately.** The existing ingest, keying, matching, evidence,
confidence, run storage and dashboard layers are available. The pinned ClinVar GRCh37
release is already fetched in this checkout. Verification with
`genetics refs verify --only clinvar_grch37 --json` passed on 2026-10-04,
including both source files and the build-anchor output.
Other checkouts must fetch and verify their own payloads.

The source is `clinvar_grch37` in `data/references/manifest.yaml`. Use its dated
`clinvar_20260804.vcf.gz` for lookup. `variant_summary.txt.gz` is a separate, rolling
source used for the existing build anchors; it does not replace the pinned VCF. The
current ClinVar post-processing step builds anchors, **not a runtime variant-lookup
index**. That lookup is the next implementation task.

The verification command also reports an existing, deferred source-license audit
warning. The manifest's declared license permits the fetch; checking its classification
against published terms remains M15.4's release work, rather than an M7.1 blocker.

## Scope and acceptance

- Look up ClinVar against the normalized GRCh37 table by position and compatible
  reference/alternate alleles. Reuse `ingest/keys.py`: a sample supplies a locus and
  observed alleles, while a reference supplies the full allele key. rsID is secondary;
  do not join by rsID alone or treat a position match as an allele match.
- Preserve source variant identifiers, classifications, review status, condition
  annotations and reference version so the result can be checked. Define and test how
  multiallelic records and conflicting classifications are represented. Ambiguous,
  missing and incompatible calls must remain explicit. Indel matching stays excluded
  except for the verified whitelist allowed by AGENTS.md §4.2.
- Keep lookup independent of the vendor adapter and reachable through the shared
  engine. Retain provenance in private saved results; verify CLI/dashboard agreement
  for any findings exposed by this milestone.
- Use stdlib gzip streaming or the established native-tool path on Windows; do not
  introduce htslib dependencies. A reusable index derived solely from public references
  can live beside those fetched references. Any artifact selected using a personal
  export belongs outside the repository.
- Test with synthetic inputs: allele order, matching and nonmatching alleles at the
  same position, missing calls, duplicate/ambiguous records, multiallelic annotations,
  classification conflicts, malformed references and recorded provenance. Add meaningful
  integration checks for the interfaces changed by the implementation.

M7.1 establishes lookup. gnomAD frequency gating is **M7.2**, frequency-band PPV
presentation is **M7.3**, ACMG surfacing is **M7.4**, curated common-variant health
cards are **M7.5**, and coverage honesty is **M7.6**. Do not treat a pathogenic ClinVar
annotation as a confirmed personal variant or infer clinical risk from lookup alone.
Low-confidence findings remain visible with the required reliability labels.

## Dependencies and preserved contracts

The roadmap carries fetcher resumability debt before M7.2's large gnomAD download.
Resolve it without trusting a digestless partial of a rolling release. The study-to-sample
ancestry mapping is M9.5 work and does not block M7.1. M6's absent chip/population
calibration remains attached to its cards; it does not block ClinVar lookup.

New runs use bundle format **6**. Preserve formats 1–5 and saved interpretations.
The review hardened computed method evidence, ROH consistency and archaic provenance;
sex-chromosome reloads use recorded thresholds and structured assay flags rather than
today's display wording. Exported structure measurements copy their nested metadata.
Do not loosen these checks while adding the health path.

## Validation checkpoint

At `1c1c2ec`: **1,898 passed, five existing Windows skips**; native ROH acceptance,
privacy checks, fixture reproduction, ruff, formatting, full card lint and strict mypy
passed. mypy 2.4.0 was checked for all four CI platform/Python configurations, and
[all five GitHub CI jobs passed](https://github.com/sovemere/genetics-analysis/actions/runs/37191147216).
Full card lint checked 47 cards, 218 template renders and 31 dbSNP variant keys.

For the next change, run the relevant tests and the repository checks:

```text
ruff check .
ruff format --check .
mypy
genetics fixtures --check
genetics cards lint --json
pytest -q
```

Set `GENETICS_ROH_TEST_TOOLS` to the pinned tools directory to include native ROH
tests. CI installs those tools and tests Windows/Linux on Python 3.11 and 3.13.
Before committing, inspect `git status --porcelain` and run `genetics check-staged`;
leave the pre-commit privacy hook enabled. CLI work commits and pushes directly to `main`.
