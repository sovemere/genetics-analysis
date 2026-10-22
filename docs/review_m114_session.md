# M11.4 session diff review

Scope: `994f70a..03093ad`, M11.4's HLA-linked cards: 25 files across the card schema, the
new `genetics.hla.cards` engine, pipeline, bundle format 23, CLI, dashboard, eight knowledge
cards, tests and documentation. The review used synthetic inputs and the public frozen CPIC
release only, and opened no personal export. Knowledge schema 6, HLA card result schema 1
and bundle format 23 are unchanged by it.

## Findings and fixes

- **P2 (latent) — One-field group patterns counted null alleles.** The frozen HLA allele
  contract (`models.ALLELE`) accepts an expression suffix, and `hla_pattern_matches`
  compared only the first field. A null allele such as `27:06N`, which is not expressed,
  would therefore have counted as B27 carriage, or made a group look emittable by the
  classifier, and produced a positive claim about an antigen the person does not carry.
  No allele list in the tests carried a suffix, and the published HLARES lists are not
  fetched in this checkout, so the defect is latent rather than observed. A group pattern
  now excludes `N` alleles; a card that needs one names it as a two-field pattern. The
  regression test failed before the fix and passes after it.
- **P3 — The HLA drug cards were missing from the PGx views.** The dashboard's PGx
  overview and `genetics pgx calls` listed M10.4 guideline cards only, so a reader on the
  pharmacogenomics page did not see the four HLA drug cards the same section holds. The
  overview now lists them and links the HLA page, and `saved_report` gains an additive
  `hla_cards` list (empty under `--gene`, since the eight SNP genes key nothing on HLA).
  PGx sample schema 1 is unchanged. The new assertions failed before the change.
- **P3 — Three card sentences were looser than their sources.** PREDICT-1's "84% white"
  describes the patients given abacavir, not all 1,956 randomised; its 47.9% positive
  predictive value is among carriers given abacavir; Megiorni et al.'s 437 patients were
  children. The knowledge text now says so. Saved bundles keep their frozen definitions and
  are unaffected.
- **P3 — A schema test accepted any `CardError`** for an `hla` key on another card kind.
  It now matches the specific refusal.

## Checked without change

- **Damaged saved reliability.** A non-mapping `computation.reliability` on an HLA card
  could have reached a raw `AttributeError` in `_stored_card`. Reproduced: it does not,
  because `read_bundle` runs `_check_hla_cards` first and that reports `BundleError`.
- **Rebuild.** A saved card is the fixed point of its frozen definition and the bundle's
  own HLA, PGx and ancestry records; the definition reads back unchanged; another run's
  record is refused through its sample identity; formats 1–22 refuse HLA cards.
- **Confidence slots.** The lowest named-locus posterior is the imputation quality, never
  a product; the M9.13 study comparison is the weighted ancestry component, which the
  "Why this tier" table already labels "Ancestry match to the study"; M11.3's call
  ceiling caps the result; the missing frequency caps every card at moderate.
- **Shared CPIC rows.** The B\*15:02 and A\*31:01 cards both show carbamazepine rows
  keyed on both genes. Each resolves the other gene from the same HLA record, so the two
  cards cannot disagree about a row. `No Result` is excluded whenever the gene is called,
  as in M10.4, and CYP2C9 conditions stay unassessed.
- **Pipeline.** The same HLA, PGx and ancestry records reach card assembly and the bundle
  writer, and each HLA card carries the run's imputation mode.
- **Privacy.** Called alleles appear only in the gitignored `cards.run.json` and in the
  private CLI and dashboard views; the scanned manifest, QC report and dashboard partials
  are unchanged; no new payload or output type was added.
- **Documentation.** The contract, roadmap, handoff, README and knowledge README match the
  code and the recorded runs; the one overstatement found (that every face number came
  from a paper, when one caveat quotes the frozen CPIC allele table) is corrected.

## Residual risks, recorded rather than fixed

- A group pattern is only as complete as the classifier's allele list. A subtype the model
  cannot emit is called as some other allele and reads as a negative model call. The
  detail view lists the emittable alleles, and the face says a model call is not a
  clinical exclusion.
- Re-validation re-parses the frozen definition with the current schema, as M10.4's
  guideline cards do. A future breaking schema change needs a versioned reader.
- A bundle saved between `03093ad` and this fix in which a group pattern matched a null
  allele would now be refused on read. None is known to exist: the change landed the same
  day and only synthetic records have been written.

## Validation

See the [contract's validation record](hla_cards.md#review-validation-2026-10-22).
