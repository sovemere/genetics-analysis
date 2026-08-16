"""Quality control (roadmap M1.5).

QC is not a gate here. Nothing in this package drops a marker, rejects a sample, or hides
a result -- it measures, and it labels (AGENTS.md 0.1A). The one thing it *decides* is
chromosomal sex, and it decides that because the file cannot: a hemizygous call is written
as a doubled homozygote, so how the entire X and Y are read depends on an inference made
here.
"""

from __future__ import annotations

from genetics.qc.build_anchors import (
    ANCHORS,
    AnchorError,
    BuildAnchor,
    default_anchors,
    load_anchors,
)
from genetics.qc.metrics import (
    call_rates,
    check_build,
    duplicate_summary,
    heterozygosity,
    indel_summary,
    infer_sex,
    resolve_ploidy,
    run_qc,
)
from genetics.qc.report import (
    BuildCheck,
    CallRates,
    ChromCallRate,
    DuplicateSummary,
    Heterozygosity,
    IndelSummary,
    InferredSex,
    QCReport,
    SexInference,
)

__all__ = [
    "ANCHORS",
    "AnchorError",
    "BuildAnchor",
    "BuildCheck",
    "CallRates",
    "ChromCallRate",
    "DuplicateSummary",
    "Heterozygosity",
    "IndelSummary",
    "InferredSex",
    "QCReport",
    "SexInference",
    "call_rates",
    "check_build",
    "default_anchors",
    "duplicate_summary",
    "heterozygosity",
    "indel_summary",
    "infer_sex",
    "load_anchors",
    "resolve_ploidy",
    "run_qc",
]
