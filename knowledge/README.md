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
└── impossibilities/
```

## Shape

```yaml
schema_version: 1
cards:
  - id: some_card
    section: traits          # one of the thirteen in AGENTS.md §3.1
    kind: interpretation     # or: impossibility
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
   fabrication the rule exists to prevent. Interpretation cards need at least one;
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

Schema v1 matches **one variant per card**. Haplotype and diplotype interpretation needs
phase, which is M10.1–M10.2's work; a genotype cross-product would be a different and
wrong answer. `variants:` is a list so the shape survives, and the validator refuses what
the engine cannot honour.
