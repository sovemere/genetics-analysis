# Knowledge pack

Card definitions. **Committed** — this is the reviewable corpus, and AGENTS.md §3 wants it
readable as a diff. The schema is `src/genetics/engine/cards.py`; that module is the
authority, this file is orientation.

## Current corpus

M3.6 supplies the first small, hand-reviewable seed pack under `traits/`. It emphasizes
large-effect, array-tractable findings in pigmentation, sensory biology, metabolism,
morphology, and circadian preference. Every locus was checked against the pinned dbSNP
GRCh37 index; dbSNP merge history is fetched alongside that index for runtime matching.
Every interpretation is tied to a primary paper with quantitative evidence and population
context.

M3.7 adds `impossibilities/` — the explicit "not determinable" cards AGENTS.md §3.2 calls
for, one per entry in that register, placed in the section each one qualifies rather than
in an appendix (M14.6). They are the reason `physical_health`, `genome_structure`,
`reproductive`, `pharmacogenomics` and `ancestry` are no longer empty: a section whose only
content is "here is what this data cannot tell you, and why" is more honest than a blank
one, and it is the difference between a limit stated and a limit implied.

This is intentionally a curated pack, not a bulk database import. Later milestones expand
the other sections through the same schema and lint path.

M6 adds four computed genome-structure cards under `structure/`: long ROH,
Neanderthal and Denisovan allele sharing, and sex-chromosome call patterns. The current
pack now has 50 cards: 33 single-variant interpretations, one two-marker interpretation,
12 assay-limit cards and four computed cards. M7.5 adds cited common health associations
under `health/`, with outcome-specific `risk_context` on the card face and in CLI output.

Test fixtures live in `tests/fixtures/cards/` and use synthetic rsIDs from `rs900000001`
up, matching the fixture generator's numbering. They are not knowledge and must never be
copied here.

## Layout

Directories are organisational only. A card's `section:` field is authoritative, so the
path and the field cannot disagree. One file may hold several related cards.

```
knowledge/
├── traits/
├── pgx/
├── nutrition/
├── health/
├── structure/
└── impossibilities/
```

## Shape

Interpretation templates may use `{frequency}` for the selected allele's percentage
and population, and `{ppv}` for a scoped study benchmark. Missing frequency and
unavailable PPV render explicit text. These placeholders require a matched interpretation;
computed and assay-limit cards cannot supply them. Published measurement benchmarks
also appear automatically on the card face, independently of an authored template.

```yaml
schema_version: 1
cards:
  - id: some_card
    section: traits          # one of the thirteen in AGENTS.md §3.1
    kind: interpretation     # or: impossibility / computed
    title: Human-readable title
    gene: GENE

    match:
      variants:
        - rsid: rs900000001
          chrom: "7"
          pos_grch37: 12345678
          alleles: [A, G]
      genotypes:              # every constructible genotype, no exceptions
        AA: outcome_one
        AG: outcome_one
        GG: outcome_two

    outcomes:
      outcome_one:
        summary: "One line for the card face. May use {genotype}, {rsid}, {gene}."
        detail: "The long form for the modal."
      outcome_two:
        summary: "..."
        detail: "..."

    evidence:
      tier: gwas             # strength of the source — NOT the card's confidence
      replication: independent
      sample_size: 12345
      ancestry: [EUR]        # 1000G superpopulation codes
      effect:
        measure: odds_ratio
        value: 1.4
        ci_low: 1.2
        ci_high: 1.6
      within_family_attenuation: 0.5   # optional, where a sibship study exists

    citations:               # required; at least one
      - type: doi
        id: 10.1234/example.5678
        title: The paper's actual title

    caveats:
      - "Anything a reader needs in order to not over-read this."
```

## Five rules that will reject your card

1. **You cannot author confidence.** `confidence`, `tier`, `score` and `reliability` are
   refused as card-level keys. Confidence is computed (M3.3) from evidence, allele
   frequency, imputation quality and ancestry match — AGENTS.md §6. `evidence.tier` is
   the strength of the *source*, which is a different ladder with different words.
2. **The genotype map must be exhaustive.** Every genotype the declared alleles can
   produce needs an outcome. An unmapped genotype renders nothing, and a reader cannot
   tell that from "the variant was not found". If there is nothing to say, say that.
3. **Citations are structured and format-checked.** `{type, id, title}`, not prose. A
   free-text citation satisfies "has a citation" while being unverifiable, which is the
   fabrication the rule exists to prevent. Interpretation and computed cards need at least one;
   impossibility cards do not, because their claim is about the assay rather than the
   person.
4. **Both rsID and coordinates are required.** Positional keys are primary because rsIDs
   get merged and retired; authors know rsIDs. Carrying both is what lets `cards lint`
   (M3.5) cross-check them against dbSNP — either alone is unverifiable.
5. **Indel alleles (`I`/`D`) are refused.** AGENTS.md §4.2: no sequence is recorded and
   either state may be the reference, so a wrong guess reports the opposite genotype
   rather than failing.

Unknown keys are rejected everywhere. In a format this full of optional fields, a
silently-ignored key looks exactly like one that had no effect.

### Outcome-specific evidence (schema 3)

Use `schema_version: 3` when outcomes need different phenotype estimates. An outcome's
optional `evidence` block has the same complete shape as card-level evidence and replaces
it for that matched result, before rendering, confidence calculation and serialization.
Omitting the key retains card-level evidence. Explicit `evidence: null` assigns no
applicable phenotype estimate; citations, observations and measurement-quality inputs
remain available. Its phenotype inputs are null, their scoring components are zero,
and confidence cannot exceed limited; rarity and poor quality still yield likely-artifact.
The effect/sample-size placeholders are unavailable for such an outcome. Do not substitute
an invented zero/unit effect or borrow a different genotype's disease association.

Schema 2 introduced unphased small-SNP diplotypes and explicit forward-only matching;
schema 1 and 2 files remain supported without outcome-evidence overrides. Multi-marker
constituents use the selected parent's evidence and neutral internal marker outcomes,
never an arbitrary first disease outcome. Phase-unresolved results assign no phenotype
estimate and preserve locus-specific rarity and quality. The [common-health guide](../docs/common_health.md)
documents the curated estimates and baseline gaps. New saves use format 12 / multi-marker
schema 2; historical format-11 snapshots retain their original evidence and calibration.

## Impossibility cards

A different shape, because they match nothing:

```yaml
  - id: some_impossibility
    section: physical_health   # the section that would otherwise look complete
    kind: impossibility
    title: Human-readable title
    gene: GENE                 # optional; §3.2's own examples are gene-named
    impossibility_reason: "Why the assay cannot answer this. Not a template."
    summary: "Not determinable: one line for the card face."
    detail: "The long form. May use {gene} if the card declares one."
    caveats:
      - "Usually the adjacent question that *is* answerable, so the card is not over-read."
```

Three things differ from an interpretation card:

- **`match`, `outcomes` and `evidence` are refused.** Carrying any of them is what makes a
  card an interpretation; an impossibility matches no genotype by construction.
- **`{gene}` is the only placeholder available.** Every other one — `{genotype}`, `{rsid}`,
  `{effect_value}` and the rest — needs a matched variant or an evidence block, so naming
  one here would render blank. The loader refuses it by name.
- **Citations are not required, and the shipped pack has none.** The claim is about the
  assay rather than about the person, and demanding a DOI for "an array does not measure
  methylation" pushes an author toward citing something tangentially related, which serves
  a reader worse than citing nothing. `impossibility_reason` carries the justification
  instead. A test asserts the pack stays citation-free, because the exemption is only safe
  while it stays unused.

The set of these cards is checked against AGENTS.md §3.2 in both directions
(`tests/engine/test_impossibilities.py`): a new bullet with no card fails, and a card no
bullet declares fails. §3.2 says to maintain it as a live register, and two ways of naming
one set diverge unless something compares them.

## Multi-variant cards

Schema v1 remains readable for single-marker cards. Schema v2 supports **two to four
biallelic, strand-unambiguous autosomal SNPs**. Declare `haplotypes` (names mapped to
allele strings in marker order) and `diplotypes` (unordered named pairs mapped to outcomes)
instead of `genotypes`. Every possible haplotype and diplotype must be represented;
rarity is not a reason to omit one. The engine enumerates all pairs consistent with the
unphased observations. Multiple pairs yield `phase_ambiguous`, visible candidates and
no assigned diplotype/risk. Missing, conflicting or non-diploid calls remain unresolved.

`health/apoe.yaml` is the complete example, including e3r. Multi-marker templates cannot
use scalar `{genotype}`, `{rsid}`, `{rsid_current}`, `{chrom}`, `{pos}` or `{frequency}`.
The detail record carries each locus's original/oriented observation, strand, call source,
frequency and confidence. A resolved diplotype inherits the weakest marker's reliability;
frequencies are never pooled across loci. This is small SNP-pattern interpretation, not
PGx star-allele calling, structural-variant inference or statistical phasing (M8/M10).

Physical-health interpretation outcomes require a nonempty, literal `risk_context`.
Schema-2 scalar matches may declare `strand: forward_only`. HFE and F5 use it because
their multiallelic sites make an unexpected base indistinguishable from a reverse-strand
reading; only the declared forward alleles are interpreted. The default `infer` preserves
existing single-marker cards' strand behavior. Multi-marker definitions currently require
strand-unambiguous biallelic sites and do not accept this scalar policy field.
Include source-specific absolute rates, baseline/comparator, time horizon, population and
strata; explicitly state unprovided baselines and inapplicable estimates. This text is
saved and shown on the face, in the detail view and in `runs show`, without converting
relative effects or measurement PPV into a person's disease risk. `cohort` is the evidence
tier for prospective population outcome studies; it receives the same source-strength
weight as GWAS. See [common health cards](../docs/common_health.md).

## Computed cards (M6.2–M6.4)

`structure/autozygosity.yaml` defines the first `kind: computed` card, with
`computation: long_roh` in `genome_structure`. It declares static `summary` and `detail`
text, structured citations, caveats and `method_evidence` (measure, units, evidence tier,
replication, study populations and corresponding sample sizes, and the applicability of
published effect estimates). It cannot declare a variant, genotype map, phenotype evidence
block, gene, impossibility reason or confidence. Text placeholders are refused because
none of the single-variant template variables describe a genome-wide computation.

The engine supplies the numeric measurement and coverage warnings. Its interpretation
tier is computed separately from the SNP rarity framework: the current absence of
chip/population calibration caps a computed result at `limited`. Absent prerequisites and
insufficient observations remain visible with their own statuses. The saved computation
record contains all parameters, measurements, provenance and reliability inputs, so an
agent and the dashboard read the same result without consulting today's knowledge pack.
Each `method_evidence` population must be nonempty text with one corresponding positive
integer sample size; booleans and coerced non-text values are rejected. The saved reader
enforces the same metadata contract and refuses SNP observations or phenotype evidence
attached to a computed card. New runs use bundle format 12; formats 1–11 remain readable.
M7.1 stores ClinVar reference lookups in a separate private payload, rather than
turning uncalibrated source classifications into authored interpretation cards.
M7.2 adds a separate allele-frequency reliability screen and supplies usable gnomAD
frequencies to interpretation-card confidence; see [the frequency guide](../docs/health_frequencies.md).
M7.3 enables `{frequency}` and `{ppv}` placeholders, including explicit unknown or
unavailable states. M7.4 saves ACMG gene-list overlaps and their reporting guidance
in the same private ClinVar payload; these are reference annotations, not authored
clinical-risk cards. See [ACMG surfacing](../docs/secondary_findings.md).

`structure/archaic.yaml` adds `neanderthal_f4` and `denisovan_f4` computations with
the same authoring contract. These carry model-dependent array ranges, per-filter
block uncertainty and reference provenance, with the assumptions and absent calibration
visible on the face. See [the method documentation](../docs/archaic.md).

`structure/sex_chromosomes.yaml` adds `sex_chromosome_profile`: non-PAR X heterozygosity
and Y call rate with probe denominators, recorded thresholds, duplicate warnings and
explicit karyotype limitations. See [sex-chromosome reporting](../docs/sex_chromosomes.md).
