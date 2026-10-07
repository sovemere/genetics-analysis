# Session diff review: M7.6 through M8.2

Reviewed `5f2c75d..f0c756d` on 2026-10-07: quantitative ClinVar coverage and format-13
snapshots, the Beagle wrapper/doctor/CI additions, full reference preparation, manifests,
privacy ignores, tests and documentation. The review follows the diff and its downstream
callers. No personal export was opened, and all new test inputs are generated.

## Findings and fixes

1. **Wrong-sample/region outputs could become completed Beagle jobs.** A syntactically
   valid phased VCF passed without matching its sample header to the target or checking
   the requested chromosome interval. Publication and checkpoint reuse now require the
   original ordered target samples and requested bounds. Regressions include a wrong
   sample in an output whose checkpoint digest was updated.
2. **Windows cleanup could fail before fallback termination.** An unavailable or timed-out
   `taskkill` raised before direct termination/reaping. The fallback now runs in those
   cases. Tests exercise both failures. Native Java remains the production executable;
   this does not promise control over arbitrary external launcher descendants.
3. **Reference catalog kind was not bound to its transform.** A valid genetic-map catalog
   could claim the panel-preparation step. Validation now checks kind/step/version pairing,
   panel input-set hashing, strict producer schema types and a valid Java 11+ identity.
   Tests retain valid artifact hashes while corrupting these relationships.
4. **Lost catalogs unnecessarily depended on the original Java installation.** All
   chromosome files could be complete and verified, yet recovery eagerly discovered Java
   and compared its new identity with the original producer. Recovery now validates and
   preserves each original producer; it discovers Java only for unfinished chromosomes.
5. **Build checks depended on contig attribute order.** Reordered length attributes and
   contig-level assembly declarations could bypass GRCh37 checks. Both are validated
   independently of attribute order, including quoted values.
6. **Runtime identity could drift before publication.** The Java executable was recorded
   before execution but not rechecked alongside inputs/jars afterward. Both Beagle jobs
   and reference preparation now reject executable drift before publishing completion.

No additional defect was identified in the M7.6 counting definitions, source binding,
saved card/lookup relationship, historical-format handling or CLI/dashboard rendering.
This does not extend coverage counts into clinical sensitivity or validate imputation
accuracy; those meanings remain explicit in the documentation.

## M8.3 boundary

Reference preparation is complete; application imputation remains upcoming. Start with
target allele/build harmonization, then shared chromosome jobs with explicit maps and
PAR/ploidy handling. Preserve typed observations and original call sources; validate
eligible-marker retention, per-variant dosage/DR2 representation and the treatment of
missing/excluded markers. Correct sample identity and a valid VCF are necessary, but
do not themselves establish correct genotypes, dosage scale or quality calibration.
Use private outputs and completed-job reuse. See [the handoff](handoff.md).

The prepared public panels remain unchanged: 23 chromosomes, 84,739,838 records and
2,504 samples each. The 25-map collection has 3,395,051 rows. Both pass the stricter
read-only source/catalog/companion verification; their original full decoded round trips
remain recorded. No full panel reconversion is required by these fixes.

## Validation

**2,292 tests passed, five existing Windows skips**, with pinned native ROH, Beagle,
converter and decoder enabled. Fifteen new regressions cover the findings above.
Strict mypy passes on Windows/Linux and Python 3.11/3.13. Ruff and formatting pass;
synthetic fixtures reproduce byte-for-byte. Full card lint passes: 51 cards, 268 template
renders and 35/35 dbSNP marker references. Read-only verification passes against all
prepared panels/maps and their original source downloads. Privacy scanning and the
pre-commit privacy/fixture checks remain required before the push.
