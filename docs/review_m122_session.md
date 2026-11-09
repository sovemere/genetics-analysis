# M12.2 session diff review

Scope: `d1a26d4..f8eebb0`. That is M12.2's four MTHFR C677T cards, the section pointers and
blurbs, their tests and documentation, and the dashboard launcher's `--verify` option. The
review re-read every card sentence against the source texts fetched for the audit: Holmes
2011, Clarke 2012, Grarup 2013 and Border 2019 in full; the ACMG 2013 guideline page and its
Box 1 image; the 2020 addendum; and the abstracts of the other cited papers. It opened no
personal genotype. It found no defect in matching, confidence, saved evidence, the pointers or
the launcher's control flow. The findings were in card text, documentation and one launcher
message.

## Findings and fixes

- **P2: the depression card asserted something no cited source says.** Its CT detail said
  Border et al. "tested rs1801133 additively, which covers one copy". Border's "additive"
  refers to the scale of interaction tests, not to genotype coding, and the main text does not
  say how one copy was coded. This is the same error class as M12.1's P2: an inference written
  as a source's statement. The detail now says the paper tested the main effect on eight
  outcomes and that its coding of one copy is not stated.
- **P3: the homocysteine card gave only an absolute difference.** "2.1 micromol/L more" has no
  scale for a reader without a typical level. AGENTS.md §0.1B asks for the base rate beside
  the effect. The TT detail now adds Clarke 2012 Table 1's relative figure: TT averaged 18%
  (99% CI 17-19%) more than CC across 70 general-population studies and 68,369 people,
  ranging from 25% in Asia to 7% in the US, Australia and New Zealand after fortification.
  Clarke 2012 is now cited on that card too.
- **P3: the depression card said nothing about absolute risk.** The physical-health claim cards
  carry `risk_context`, which mental health does not require. The TT detail now says both
  studies give odds ratios or P values, not rates, so no absolute risk is assigned.
- **P3: wording that went beyond the sources.**
  - The heart-disease card and the audit said Clarke's 19 datasets were "never published".
    Clarke says their MTHFR results had not yet been published when requested.
  - The audit said Holmes found "strong" small-study bias in Asia and an OR of 1.28 "in
    studies with 400 or more stroke events". The paper reports evidence of bias (Egger P =
    0.002), and the 1.28 is the Asian studies restricted to that size.
  - The audit said Clarke's datasets "came from" five named sources. The paper lists those as
    included, not as exhaustive.
- **P3: the launcher's verify-first shortcut repeats checks that are already current.**
  `runs list --verify` always repeats the deep checks. Clicking the shortcut out of habit
  would cost about an hour per imputed run even when nothing had changed. The console
  message and the README now say to use it after the code changes.
- **P4: tidying.**
  - The ACMG citation note attributed a main-text statement (which genotypes are unlikely to
    be clinically significant) to Box 1. It is now attributed to the main text.
  - "Women who may become pregnant" is now Box 1's own "women of childbearing age".
  - A new test checks that each claim card's first caveat explains what its limited tier
    means, since the calibration depends on that sentence.

## Recorded rather than changed

- **The physical-health blurb does not name its interpretation cards.** It reads "ClinVar
  findings and polygenic scores", and HFE, factor V Leiden and APOE were already absent from
  it before this session. Rewriting it is outside M12.2.
- **Gilbody 2007's study populations remain unverified.** The publisher paywalls the paper and
  it is not in PMC. The card records `UNKNOWN` and says so. If the full text becomes
  readable, that is the one value to revisit.
- **The launcher has no automated test.** No test compiles C#. It was rebuilt and run with
  `--verify` and without, against an empty temporary data directory. The check, the server
  start and a 200 from the first page were confirmed by hand.

## Checked without change

- **Numbers.** Every figure on the four cards was re-read against its source. Those sources are
  Holmes 2011's results text, Clarke 2012's abstract, results and Table 1, Grarup 2013's
  Table 2, and Border 2019's Table 2 and methods. Also re-read were the ACMG text and Box 1,
  and the Frosst, Bezemer, Blom, Klerk, van Meurs, Gilbody, Tsang, Crider, Rey, Friso, van der
  Put and Botto–Yang abstracts.
- **Strand.** The native tests re-check forward A as 677T against gnomAD and ClinVar.
- **Null outcomes.** Each `evidence: null` is a comparator or a genotype with no verified
  estimate, and a mutation test fails if a comparator inherits the TT odds ratio.
- **Pointers.** The pointers resolve in both directions, and the count of sections that
  declare pointers is pinned.

## Operational note

The review changed only card text, tests, documentation and the launcher; no engine source
changed. The first read of each saved run after M12.2's source change still repeats its deep
checks once.

## Validation

See the [handoff](handoff.md#accepted-m122-mthfr) for the reviewed state's validation.
