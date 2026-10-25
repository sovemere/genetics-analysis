# M11.5 session diff review

Scope: `1d1dbb5..be0ab35`, M11.5's carrier status cards: the schema-7 `carrier`
declaration, the new `genetics.engine.carrier` module, evidence assembly, bundle format 24,
the `genetics cards carriers` command, `runs show`, the dashboard face and detail views,
fifteen reproductive cards plus the HFE C282Y declaration, tests and documentation. The
review used synthetic inputs, the fetched public references (dbSNP b157, ClinVar
2026-08-04, gnomAD r2.1.1 exomes) and the cited papers' open full text, and opened no
personal genotype. Knowledge schema 7, carrier panel schema 1 and bundle format 24 are
unchanged by it.

## Findings and fixes

No defect was found in state derivation, strand handling, the bundle's write and read
checks, the CLI or the dashboard. The findings are in what the cards say and in what the
documentation claims.

- **P3 — Five card statements were stronger than their sources.** Each was re-read against
  the cited text:
  - Gregg 2021's Tables 1–3 give each gene a "maximum carrier frequency" estimated from
    gnomAD; they do not name the population each maximum comes from. Every carrier card
    said "in the gnomAD population where it is highest" or "across gnomAD populations".
    The cards and citation notes now say "estimated from gnomAD".
  - Scott 2010's Table 5 lists Fanconi anaemia's one monitored pregnancy under "one parent
    DNA-confirmed", not as a carrier couple. The FANCC card said Scott 2010 monitored one
    carrier-couple pregnancy; it now says the study reports no pregnancy in which both
    parents were confirmed carriers, so there is no empirical rate.
  - The pooled 107 affected of 404 both-confirmed pregnancies come from 11 of the panel's
    16 conditions, not 16. The PAH citation note and the contract now say so.
  - The MCAD scope said 25 of Andresen 2001's 124 disease alleles "were other ACADM
    variants". Not all of them were identified; the scope now says they were not K304E
    and that the mild Y42H was among them.
  - The Tay-Sachs two-copy detail called IVS12+1G>C "a splice-donor allele like this one"
    associated with the infantile form, without a source for that link. It now says
    classic Tay-Sachs begins in infancy, later-onset forms exist, and the card assigns no
    form to two copies.

  Saved bundles keep the declarations they were written with and are unaffected.
- **P3 — The documentation miscounted conditions.** The contract, roadmap and handoff said
  the fifteen new cards cover nine conditions. They cover eight; HFE makes nine for the
  panel, which `genetics cards carriers` already reported correctly.
- **P3 — The contract misdescribed the effect component.** It said a proportion "contributes
  little for every carrier card". It does not for MCAD K304E (0.798), whose case share is
  most of the disease; the panel spans 0.0049 to 0.798, up to 0.12 of the weighted score.
  The evidence rule and the residual limit now state the range and what it does and does
  not measure.
- **P3 — Two audit rows overstated.** HBB −29A>G's missing gnomAD record was attributed to
  exome capture, which was not checked; SERPINA1 PiS was described as "pathogenic mainly
  with Z". The rows now say "a promoter variant" and that ClinVar classifies PiS
  "Pathogenic, low penetrance" (read from the pinned release).
- **P4 — Hardening.** `validate_record` now refuses a saved carrier record whose variant is
  not on an autosome, matching the loader's rule; the regression failed with the check
  neutered. The test that reads each card's face against its derived state now anchors
  on the summary's opening ("No …", "consistent with one …", "consistent with two …")
  instead of matching a bare word anywhere in the sentence.
- **P4 — The roadmap's dated log had no M11.5 entry.** Added with this review's.

## Checked without change

- **State derivation.** `pathogenic_copies` counts on the oriented genotype; at an A/T or C/G
  marker it accepts only an ambiguous-strand heterozygote and checks the count is unchanged
  under complement. Absent, no-call, conflicting, mismatched and strand-ambiguous matches
  all save `state: null`.
- **Bundle checks.** `_check_carriers` runs on write and read after the ancestry check,
  refuses carrier records below format 24, and re-derives each state from the saved match
  only; the current knowledge pack is never consulted.
- **Source figures.** Scott 2010's per-condition both-confirmed counts (CF 33/134, Tay-Sachs
  31/102, Gaucher 19/65, Canavan 6/28) match Table 5. Gregg 2021's gene maxima match Tables
  1–3.
- **Privacy.** Carrier records live in the existing gitignored `cards.run.json`; the panel
  carries no genotype; no new output type was added. The array marker list was read from
  the rsID, chromosome and position columns only.

## Residual risks, recorded rather than fixed

- **Twelve of the sixteen panel markers are multiallelic in dbSNP b157.** Only ASPA E285A,
  FANCC IVS4+4A>T, PAH R408W and PAH IVS10-11G>A list two bases. A card matches only its
  declared pair, so another base is an allele mismatch, never a state. But the array's
  probe alleles are unpublished, so a homozygous reference call cannot show that the probe
  tested the card's alternate. Recorded in the contract and handed to M11.6; the no-copy
  text already says it is not a negative screen.
- A no-copy or two-copy call at the four strand-symmetric markers is never interpreted
  from a direct call, as recorded at implementation.

## Validation

Run on 2026-10-25, Windows, Python 3.13, with the native tools configured:

- The affected test files (carrier, carrier references, bundle, dashboard, common cards)
  pass **309 tests**.
- The full native suite passes **3,660 tests with nine skips**: the five existing Windows
  skips and the four published-classifier HIBAG tests, which need a separate reference root.
- Full dbSNP card lint passes **100 cards, 506 renders, 54/54 marker keys**.
- All four strict Windows/Linux × Python 3.11/3.13 type targets pass (233 files), as do
  ruff, format and the staged privacy scan.
