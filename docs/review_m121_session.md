# M12.1 session diff review

Scope: `243aa3e..9f3d6ab`, M12.1's nutrition cards. That covers the seven new cards, the two
cards moved from traits, the `SectionInfo.related` pointer in the dashboard and
`genetics runs show`, the tests and the documentation. The review re-read every card
sentence against the source texts fetched for the audit. It checked identifications against
the fetched public references (dbSNP b157, ClinVar 2026-08-04, gnomAD r2.1.1 exomes, the
ClinPGx variant archive) and opened no personal genotype. It found no defect in matching,
saved evidence or the pointer code. All the findings were in card text, sourcing and tests.

## Findings and fixes

- **P2: four card details made claims no cited paper supports.** AGENTS.md §6 forbids
  speculation, and §0.1B makes precision the duty of care. The sentences were:
  - coffee: "most of the variation in coffee drinking is cultural and personal";
  - B12: "which diet, absorption, age and medicines dominate";
  - folate: "serum folate also reflects recent intake rather than stores";
  - vitamin D: "season, sunlight, skin ... move 25-hydroxyvitamin D far more than this
    marker". That one is also overstated: in the cited cohort GG and TT differ by 18 nmol/L,
    and summer and winter by 34.2.

  Each is now replaced by figures from the card's own sources. Those are the consortium's
  statement on cultural influences, Grarup's variance explained and heritability, and
  Framingham's season and supplement means. **The first replacement made the same mistake.**
  It read Grarup's sibling-pair heritability (27% and 17%) as "most of the variation is not
  genetic". The same paper cites twin estimates of 59% and 56%. The cards now give both
  figures and draw no conclusion from them.
- **P2: the FOLR3 card overstated two things.** It said the array "cannot read" the FOLR3
  frameshift, but the array's indel content at FOLR3 was never checked. What is true is that
  this pipeline does not match indels (§4.2). It also called the frameshift "the likelier
  cause", where Grarup et al. say "lead signal". Both are reworded.
- **P3: two identifications rested on nomenclature the audit had not sourced.**
  - Sachse names its site "position 734 in intron 1", and the audit had treated that as
    rs762551 by convention.
  - "ADH1B*2" was used for rs1229984's His48.

  PharmGKB's variant records in the fetched ClinPGx archive list both synonyms. PA166154850
  gives `c.-9-154C>A` in intron 1 and "CYP1A2*1F (retired)", and PA166156507 gives "ADH1B*2".
  Both cards now cite them. The same record shows that CYP1A2*1F is retired, which the
  label-trap caveat now says. The audit also records why the legacy "−163" equals
  `c.-9-154`: 9 bases of exon 2 plus 154 of intron 1.
- **P3: the audit said P = 5.5e-76 "in a 56-study meta-analysis".** Holmes et al.'s intake
  estimate comes from the 46 of 56 studies that recorded intake.
- **P4: tidying.**
  - The rs762551 face said "unreplicated here", which reads as a claim about the run; it
    now says no replication was verified.
  - One test called another test function; both now share `assert_bindings`.
  - No test covered the pointer under a filter that hides its target card. One now checks
    that the link still renders and the detail page opens.

## Recorded rather than changed

- **`runs show --json` carries no pointer.** That command prints the frozen saved record and
  holds no current context, by the decision recorded in the
  [M11.6 review](review_m116_session.md) and [PGx framing](pgx_framing.md). The pointer is in
  the text output and in `engine/sections.py`. M13 owns the agent surface.
- **The pointer is resolved twice**, in `views.related_links` for `CardView` and in
  `runs_cmd._related_lines` for `StoredCard`. The declaration exists once, in
  `sections.py`; only the rendering differs, and each copy is about 15 lines.
- **A run saved before M12.1 shows Nutrition as "Not built yet — roadmap M12"** when it has
  no nutrition cards. The wording predates M12.1: it is right for the tool's state when the
  run was saved and wrong for the tool's state now. Seeing nutrition cards on real data
  needs a new run.
- **The coffee card rates well-established for a 0.11 cups-a-day effect.** The effect
  component scores signal against uncertainty, by design, so a certain small association
  scores high. The card's face gives the magnitude, and the audit says so.

## Checked without change

- **Card numbers.** Every number on the seven cards was re-read against the source text:
  CCGC 2015 Table 1, Sulem 2011 Table 1, Sachse 1999, the Cornelis 2006 abstract, Holmes
  2014 Table 1, Kambhampati 2016 and its Figure 2, Kelly 1995 and Thorven 2005 abstracts,
  Hazra 2008 Table 1, Grarup 2013 Tables 1 and 2, and Wang 2010 Tables 1–3.
- **Strand.** ADH1B and FUT2 are re-checked natively against gnomAD and ClinVar.
- **Escaping.** Jinja's autoescape covers `.html`, so card titles in the pointer are
  escaped.
- **Redirected output.** The CLI switches a non-UTF-8 stdout to UTF-8 at entry (M11.6), so
  the two citation titles with "→" are safe in redirected output.

## Operational note

The session changed Python source, so the first read of each saved run repeats its deep
checks once. That is about 54 minutes for the real imputed run. Run
`genetics runs list --verify` before opening the dashboard on it.

## Validation

See the [handoff](handoff.md#accepted-m121-nutrition-cards) for the reviewed state's
validation.
