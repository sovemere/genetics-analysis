"""Published SNP-chip confirmation benchmarks, kept separate from personal probability."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DOI = "10.1136/bmj.n214"
CLINICAL_NOTICE = (
    "Only clinical sequencing can establish or exclude the variant. "
    "This pipeline is not a clinical test."
)


def confirmation_text(estimate: float, ceiling: float | None) -> str:
    """Display a recorded study rate without implying an individual posterior."""
    band = "" if ceiling is None else f" for allele frequency below {100 * ceiling:g}%"
    return (
        f"Published SNP-chip benchmark: about {100 * estimate:g}% confirmed and "
        f"{100 * (1 - estimate):g}% unconfirmed by sequencing{band}."
    )


def clinvar_benchmark(info: Mapping[str, Any]) -> dict[str, Any]:
    """The BRCA study concerns pathogenic/likely-pathogenic germline annotations.

    Exact symbol/NCBI gene-ID pairs prevent substring or unrelated-gene matches.
    Included-haplotype and somatic classifications are never promoted to CLNSIG.
    Mixed benign/uncertain/conflicting classifications retain the general benchmark.
    """
    genes = info.get("GENEINFO")
    classification = info.get("CLNSIG")
    brca = (
        isinstance(genes, str)
        and bool(set(genes.split("|")) & {"BRCA1:672", "BRCA2:675"})
        and isinstance(classification, str)
        and bool(classification)
        and all(
            part in {"Pathogenic", "Likely_pathogenic"}
            for group in classification.split("|")
            for part in group.split("/")
        )
        and not info.get("CLNSIGCONF")
    )
    estimate = 0.042 if brca else 0.16
    ceiling = None if brca else 0.00001
    applies_to = (
        "UK Biobank pathogenic/likely-pathogenic BRCA1/BRCA2 SNP-chip calls, "
        "pooled across the study's assayed variants, not a frequency-bin estimate."
        if brca
        else "UK Biobank heterozygous SNP-chip calls below 0.001% population frequency."
    )
    return {
        "estimate": estimate,
        "population_frequency_ceiling": ceiling,
        "scope": "brca_pathogenic" if brca else "rare_heterozygous",
        "confirmation_text": confirmation_text(estimate, ceiling),
        "applies_to": applies_to
        + " Study benchmark, not an individual posterior probability; not calibrated "
        "for this vendor, homozygous/hemizygous calls or imputation.",
        "study_sample_size": 49908,
        "doi": DOI,
    }
