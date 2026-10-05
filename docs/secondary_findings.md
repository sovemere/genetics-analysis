# ACMG secondary-finding gene overlaps (M7.4)

The dashboard's **ACMG secondary-finding gene overlaps** link and
`genetics runs secondary <run-id> [--json]` read the same saved ClinVar records.
Every ACMG overlap remains visible, including `likely-artifact`, unknown reliability,
uncertain/conflicting annotations, missing calls and unresolved alleles. The full
ClinVar view remains available separately. Neither view suppresses low-confidence
records or converts a reference classification into a confirmed personal finding.

**Only clinical sequencing can establish or exclude the variant. This pipeline is
not a clinical test.** This statement appears on each overlap's face and in CLI output.
Existing gnomAD measurement-reliability tiers and scoped confirmation benchmarks
remain unchanged. Missing frequency remains unknown, never zero.

The source is the complete **84-gene ACMG SF v3.3** roster and gene-specific guidance
published by [ClinGen](https://search.clinicalgenome.org/kb/genes/acmgsf), accessed
2026-10-05, under its [CC0 terms](https://clinicalgenome.org/docs/terms-of-use/).
The policy is [Lee et al., Genetics in Medicine 2025](https://doi.org/10.1016/j.gim.2025.101454).
This version adds ABCD1, CYP27A1 and PLN. NCBI's older ACMG help page still describes
v3.2 and is not used as the roster source.

```text
genetics refs fetch --only acmg_sf_v3_3
genetics refs verify --only acmg_sf_v3_3 --json
genetics runs secondary <run-id> --json
genetics runs clinvar <run-id> --json
```

The manifest pins the complete public API payload by SHA256 and exact size. The
payload is fetched into the ignored reference cache, never vendored. The API is
rolling: changed content requires an explicit manifest update. Analysis performs
no network request, and a damaged installed source fails explicitly. Missing ClinGen
or ClinVar is recorded as `not_run`; an empty result does not become a negative screen.

Membership matches the exact symbol in each numeric `GENEINFO` symbol/NCBI-ID pair.
It retains the NCBI identifier and source HGNC identifier; it does not independently
verify the cross-database identifier mapping. Substrings and malformed identifiers do
not match. This differs from the stricter symbol/NCBI-ID checks that scope the BRCA
confirmation benchmark; those checks remain unchanged.

The view distinguishes solely pathogenic/likely-pathogenic germline annotations
from other or unresolved annotations. Somatic and included-haplotype annotations
cannot replace a germline classification. **Clinical reportability is not
adjudicated.** Gene membership plus P/LP is insufficient: disease, inheritance, phase,
variant type and gene-specific restrictions matter. The source guidance is retained
and displayed, including restrictions on TTN, HFE and recessive conditions; no
automated positive clinical report, penetrance or absolute risk is inferred here.

No overlap does not exclude a variant or a condition. The array does not sequence
these genes, and its structural-variant blind spots remain. M7.6 owns the separate
quantitative coverage card.

New analyses save ClinVar schema **4** in bundle format **10**, including the complete
source roster, guidance, source/access/license provenance, surfacing policy, counts
and annotations. Integrity checks reconstruct annotations from that saved roster,
without consulting a newer reference cache. Formats 1–9 retain their original results;
the ACMG view explicitly says when an older run did not record this stage.

Verification uses invented loci/calls and synthetic public-reference stubs. Local
acceptance also uses fabricated calls against the complete public ClinVar and gnomAD
indexes, with networking disabled. No personal export is used.
