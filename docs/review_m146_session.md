# M14.6 session diff review

Scope: M14.6's working tree before its commit, on top of the M14.5 second-review commit.
That is `reads.assay_limits` and `assay_limits_by_section`, `section_context`'s
`assay_limits` and the text form's line, agent schema 10, `views.LimitLink`, `limit_links`,
`CardGroup.limits`, `findings` and `limit_cards`, `_cardgrid.html`, `_cardface.html`'s
`card_heading`, the stylesheet rules, the parity rows and the tests. Every changed source
line was re-read, and the dashboard was opened in Chrome on a synthetic run built from the
committed pack against an invented table with half its markers dropped, grouped by section
and by tier. No personal export and no saved real run was opened.

## Findings and fixes

- **P3, found by removing guards: a test did not catch the limit cards rendered twice.**
  Iterating `group.cards` instead of `group.findings` put each limit in the sort as well as
  in its block, and the block-order test still passed, since it only compared positions.
  The test now asserts each card's title renders once in its panel.
- **P3: a stray blank line** split the stylesheet's `.gaps` rules after the new rules were
  moved below them. Removed.

## Re-read and unchanged

- **No filter exception.** A limit card is hidden and counted by a filter as before (M4.7);
  the line at the head is what keeps it stated. `Grid.hidden` and the filter counts are
  unchanged, and the parity check still holds them to `runs show`.
- **The line points; it does not count.** `CardGroup.limits` is not in `total`, as
  `related` is not.
- **A limit the run lacks.** `assay_limits` lists the current pack's limit cards a run holds
  nowhere, by the pack's title and without a link. A card the run saved under another section
  is listed there, not as missing here; a test holds both.
- **Tier groups have no limits line.** `_tier_groups` passes none; `_check_grid` fails a
  tier group that has any.
- **A section the engine does not know** gets no line (`assay_limits_by_section` covers the
  thirteen), and its limit cards still render in their block.
- **The register.** AGENTS.md §3.2's eight bullets and the twelve cards match both ways, by
  the existing `tests/engine/test_impossibilities.py`.

Five guards were removed in turn (the head line, the separate block, the pack's missing
limits, the parity comparison, the context key); each failed a test once the P3 above was
fixed.

## Validation

The full native suite (native tool variables set, JDK 17) passed **4,455 tests with nine
skips** in 991 s before the two fixes above; the assay-limit tests pass after them (15).
Strict mypy over `src` and `tests` (`--platform win32`), ruff and format pass.

## Left for later

- Grouped by tier, the limits block follows the reader's sort, which is by title when every
  card ties on tier; each card names its section. Ordering it by section would change the
  sort key for every tier group.

## Second pass after the commit

A diff-driven pass over `2248b4c`, re-reading every changed source line against the code it
calls and every changed sentence against the code it describes. No code defect found.

- **P3, stale documentation.** `agent_cli.md`'s parity section still counted 23 view classes
  (now 24, with `LimitLink`) and, already stale before this change, 66 properties (65 before,
  67 now) and nineteen `Shell` fields (twenty). Its list of what the grid is checked against
  did not name the section pointers or the new assay limits. `agent_usage.md`'s question
  table did not say where a section's assay limits are read. `agent_schema.md`'s opening
  sentence was left unwrapped. The roadmap's risk register named only M11.6 against the
  carrier section reading as complete. All updated.
- **Re-read and unchanged.** `card_heading` does not leak from one panel's limits block
  into a later panel's findings: the synthetic run's page renders 12 limit titles at `h4`
  and its 91 other cards at `h3`, in both groupings and sorted by title, and with a tier
  filter that hides every card all five head lines remain. `runs show` without `--section`
  prints no limits line; it prints every card, the limits among them, and has no section
  frames. `limit_links` cannot meet an `in_run` limit with no view, since both come from one
  bundle's cards, and the parity check would fail one.

The walk-through, parity, schema, card, search and repository-hygiene suites pass (344
tests).
