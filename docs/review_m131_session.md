# M13.1 session diff review

Scope: `441e498..015c41c`. That is M13.1's four agent read commands (`runs show --section`,
`runs card`, `runs qc`, `cards evidence`), the shared `run/reads.py` projection, the text
renderers, the knowledge-pack declaration, the dashboard's empty-section wording, their tests
and documentation. Every changed source line was re-read against the bundle reader, the
dashboard views and the card schema. The review opened no personal genotype and no saved real
run; it used synthetic runs only.

## Findings and fixes

- **P2: `runs card` text called computed, polygenic and guideline cards "Not scored".**
  Those cards save `confidence: null` and keep their tier, score, inputs, ceilings and reason
  in `computation.reliability`; the bundle reader takes their tier from there. The text form
  only read `confidence`, so it printed "Not scored: nothing was matched, or the card states
  an assay limit" under a header that gave the card's tier. The JSON was right; the text
  contradicted itself and hid the inputs. `render.confidence_lines` now reads the card: the
  six scored inputs where `confidence` exists, otherwise the reliability block with its
  reason, inputs and ceilings. A card with neither now says "Not scored" and gives its
  status, or says it states an assay limit. A new test fails on the original code.
- **P3: stale descriptions of what M13.1 still had to do.**
  - The roadmap's M13.1 item was ticked but still listed `--section`, `card`, `evidence` and
    `qc` under "What remains", and called `runs show` "deliberately thin".
  - `runs_cmd`'s module docstring still said M13.1 "owns" those commands, and its privacy
    paragraph named only `runs list` and `runs show`. It now names `runs qc` as scanned and
    `runs card` as unscanned.
  - The README's status line said "M0–M10 are implemented" and pointed to M13.1 as next.
- **P3: `runs show --json` help still said "Emit the whole bundle as JSON."** With
  `--section` it emits those sections. The help now says both.
- **P4: the empty-section wording still had a second copy.** M13.1 moved the section nav's
  wording into `reads.empty_reason`, but the grid's `CardGroup.empty_reason` kept its own
  copy of the same two sentences. It now calls the same function for those two cases and
  keeps its own text for the filter and tier cases. The web tests pass unchanged.
- **P4: tidying.**
  - `render.citation_lines` paired citations with links by index. It now uses
    `zip(strict=True)`, so links built from other citations raise rather than pair a DOI
    with the wrong page. A test covers it.
  - `render.evidence_lines`' docstring still described a null outcome as "a comparison
    group", the wording M13.1 had removed from the output because it is not always true.

## Recorded rather than changed

- **A card's `related` list is its section's pointers, not the card's.** For the HFE card,
  `runs card` lists the physical-health pointer to the MTHFR homocysteine card. The text
  labels it "Physical health also points to", and the contract documents it as the section's
  pointers. Per-card pointers would need a new declaration; M12.1 declared them per section.
- **`runs show --section` text prints the carrier-scope statement only when it was not
  recorded.** When it was, the scope card's own line prints it, as unfiltered `runs show`
  does. The JSON always carries it.
- **Exit codes and error shapes still differ across command groups.** That is in the M13.2
  entry contract rather than fixed here, since M13.2 is the schema item.

## Checked without change

- **Projection.** `reads.card_payload` produces the same JSON as the removed inline
  projection for every field. Only `ancestry_comparison` changed: it is now copied into a
  plain dict rather than passed through, which serialises identically.
- **Privacy split.** `runs qc` and `cards evidence` scan both branches; the mutation tests
  still fail when either scan is removed. The evidence JSON and text of all 119 cards pass
  the scanner.
- **Dashboard parity.** Section titles, blurbs, milestones, counts, empty reasons and pointers
  match the dashboard's views for all thirteen sections.
- **Redirected output.** The four new reads still run as subprocesses with a cp1252 stdout.

## Operational note

The review changed Python source, so the first read of each saved run after it repeats its
deep checks once (about 54 minutes for the real imputed run). Run `genetics runs list
--verify`, or the launcher's verify-first shortcut, first.

## Validation

Run on 2026-11-10, Windows, Python 3.13, with Java 17 and the pinned PLINK/Beagle tools
configured. The full native suite passes **4,032 tests with the same nine skips** in 749 s:
the five Windows skips and the four published-classifier HIBAG tests. Nothing but
documentation changed between that run and the commit. The three new tests include one that
fails on the original confidence text; it was checked by restoring that code. Full dbSNP card
lint (119 cards, 594 renders, 65/65 keys), all four strict type targets (248 files), ruff,
format and the fixture check pass.
