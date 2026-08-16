# Knowledge pack

Card definitions. **Committed** — this is the reviewable corpus, and AGENTS.md §3 wants it
readable as a diff. The schema is `src/genetics/engine/cards.py`; that module is the
authority, this file is orientation.

## It is empty on purpose

M3.1 built the schema. The cards come in **M3.6** (traits seed pack) and **M3.7**
(impossibility cards).

Shipping a card now would mean writing GRCh37 coordinates from memory, which is the
invented-data failure AGENTS.md §6 forbids. `qc/build_anchors.py` and the fixture
`spike_ins` hook shipped empty for the same reason: a mechanism with no data is honest,
and a mechanism with *invented* data is the exact failure the mechanism exists to catch.

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

## Multi-variant cards

Schema v1 matches **one variant per card**. Haplotype and diplotype interpretation needs
phase, which is M10.1–M10.2's work; a genotype cross-product would be a different and
wrong answer. `variants:` is a list so the shape survives, and the validator refuses what
the engine cannot honour.
