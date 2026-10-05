"""Benchmark applicability is tested with synthetic annotation combinations only."""

from __future__ import annotations

import pytest

from genetics.engine.ppv import clinvar_benchmark, confirmation_text


@pytest.mark.parametrize("gene", ["BRCA1:672", "BRCA2:675", "OTHER:1|BRCA2:675"])
@pytest.mark.parametrize(
    "classification", ["Pathogenic", "Likely_pathogenic", "Pathogenic/Likely_pathogenic"]
)
def test_brca_benchmark_is_gene_and_germline_classification_specific(
    gene: str, classification: str
) -> None:
    benchmark = clinvar_benchmark({"GENEINFO": gene, "CLNSIG": classification})
    assert benchmark["estimate"] == 0.042
    assert benchmark["scope"] == "brca_pathogenic"
    assert benchmark["population_frequency_ceiling"] is None
    assert "4.2% confirmed" in benchmark["confirmation_text"]
    assert "95.8% unconfirmed" in benchmark["confirmation_text"]
    assert "not a frequency-bin" in benchmark["applies_to"]
    assert "not an individual posterior" in benchmark["applies_to"]
    assert benchmark["doi"] == "10.1136/bmj.n214"


@pytest.mark.parametrize(
    "info",
    [
        {},
        {"GENEINFO": "BRCA1LIKE:672", "CLNSIG": "Pathogenic"},
        {"GENEINFO": "BRCA1:999", "CLNSIG": "Pathogenic"},
        {"GENEINFO": "OTHER:672", "CLNSIG": "Pathogenic"},
        {"GENEINFO": "BRCA1:672", "CLNSIG": "Benign"},
        {"GENEINFO": "BRCA1:672", "CLNSIG": "Uncertain_significance"},
        {"GENEINFO": "BRCA1:672", "CLNSIG": "Pathogenic|Benign"},
        {"GENEINFO": "BRCA1:672", "CLNSIG": "Conflicting_classifications_of_pathogenicity"},
        {"GENEINFO": "BRCA1:672", "CLNSIG": "Pathogenic", "CLNSIGCONF": "Benign(1)"},
        {"GENEINFO": "BRCA1:672", "CLNSIGINCL": "Pathogenic", "ONC": "Oncogenic"},
        {"GENEINFO": "BRCA1:672", "CLNSIG": True},
    ],
)
def test_unrelated_uncertain_conflicting_and_somatic_annotations_keep_generic_benchmark(
    info: dict[str, str | bool],
) -> None:
    benchmark = clinvar_benchmark(info)
    assert benchmark["estimate"] == 0.16
    assert benchmark["scope"] == "rare_heterozygous"
    assert benchmark["population_frequency_ceiling"] == 0.00001


def test_confirmation_display_distinguishes_study_rate_from_personal_probability() -> None:
    text = confirmation_text(0.16, 0.00001)
    assert "16% confirmed" in text and "84% unconfirmed" in text
    assert "below 0.001%" in text
    assert "calls like this" not in text
