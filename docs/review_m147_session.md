# M14.7 diff review

Scope: commit `764b80c`, the accessibility pass, reviewed after it was pushed. That is the
card face (`_cardface.html`, the `.card` and `.cardlink` rules), the keyed selects
(`_runselector.html`, `_controls.html`, `keyedSelect()` in `app.js`), `--control-line`, the
nav's landmark and `aria-current` (`_sectionnav.html` and the pages that include it),
`views.domid` and `views.codespans`, the ancestry scatter's roles,
`genetics.testing.accessibility`, the new and changed tests, and the M14.7 docs. Every
changed line was re-read. No personal export and no saved real run was opened.

## Findings and fixes

- **P2: the face's layout restyled two things that are not card faces.** M14.7 moved the
  face's padding, flex column and `position: relative` from `.cardlink` onto `.card`, so the
  stretched link had a positioned face to cover. Two other templates use `.card`: the
  ClinVar page's coverage and locus sections, and the PGx gene faces in the
  pharmacogenomics panel. Both took the new padding and flex column, and their paragraph
  margins no longer collapsed. Without `:has`, the focus-within ring would also have drawn
  round a whole ClinVar locus whenever one of its links had focus. The audit could not see
  this: it reads markup, not layout, and neither page's tests compare styling. The layout
  now sits on a new class, `cardface`, which only `_cardface.html` sets, and `.card` is
  back to its pre-M14.7 rule. A test holds `.card` free of `position`, `padding` and
  `display`, and holds `cardface` out of the two other templates.
- **P3, found while adding that test: the test helper matched the wrong rule.**
  `_rule(".card")` took the first `.card {` in the stylesheet, which is
  `.searchhit .card {`, so the first version of the new test passed with `.card` given
  `position: relative` again. `_rule` now matches a selector only at the start of a line,
  and the same change now fails the test. The six control-edge selectors it already checked
  had no earlier match, so their results stand.
- **P3: the audit ignored an SVG `<title>` when computing a name.** A lint fix during
  M14.7 changed the check from skipping `<title>` only outside an SVG to skipping it
  everywhere. No name this audit computes depends on it today, but a link or button that
  held a titled SVG would have been called nameless. It now skips only the document's own
  `<title>`.
- **P3: the audit did not compare `complementary` landmarks.** `aside` was mapped to the
  role but the role was left out of the set compared. Added; no page has an `aside`.
- **P3, stale wording: "a face is one link".** The M14.3 comment on the nav's legend, the
  matching decision in `agent_cli.md` and `app.js`'s header still gave a face being one link
  as the reason the legend is not on the faces. That is no longer the reason: the title's
  link is stretched over the face, so a badge link would sit under it and still not take a
  click. All three updated.

## Re-read and unchanged

- **No compared value changed.** `domid` and `codespans` are display filters in
  `genetics.web`, not engine functions, so `parity.check_engine_calls` has nothing to place.
  `nav_page` and `nav_search_landmark` are set by `{% with %}` in templates and are not
  context keys. The refusal sentence handed to the template is the engine's, unchanged.
- **The keyed flag.** A pointer press clears it, any key except Tab, Shift, Escape and Enter
  sets it, and Enter acts. With the native popup open, its keys do not reach the page, so a
  choice made there by keyboard leaves the select keyed and waits for Enter, Open or Apply.
  That is the intended cost.
- **`domid` collisions.** Sixteen hex digits of SHA-256 over the card's address; a page
  shows each card once, and the audit's duplicate-id check runs over every page and every
  card's page and dialog.
- **The `test_pgx` assertion** on `class="card tier-likely-artifact"` is about a PGx gene
  face, so adding `cardface` to the end of the face's class list does not affect it.

## Validation

The full native suite passes **4,498 tests with nine skips** in 1,033 s, one more than the
M14.7 run (the layout test). Strict mypy, ruff and format pass. The layout test was checked
against the regression it is for: `.card` given `position: relative` again fails it.

## Left for later

Unchanged from the M14.7 record: no screen-reader session, the theme toggle's new state is
not announced, and some HLA, PGx and ClinVar tables have no caption. Nothing checks layout
except the stylesheet tests; a class shared by two kinds of element is found by reading.
