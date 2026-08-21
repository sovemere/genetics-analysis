"""Harmonized calls into a PLINK 2 pgen (roadmap M5.2, second half).

:mod:`genetics.external.harmonize` decides what the sample's calls mean on the panel's
alleles and writes them as a VCF; this module hands that VCF to PLINK 2 and gets back the
``.pgen``/``.pvar``/``.psam`` trio that M5.3's PCA and M5.4's projection read.

**The VCF is an intermediate, not an output.** It holds the same genotypes as the pgen in a
larger and more quotable form, so it is deleted once the conversion succeeds unless the
caller asks to keep it for debugging. ``.gitignore`` blocks ``*.vcf`` and ``*.pgen`` alike;
deleting is the second line, not the first.

**The workspace defaults outside the checkout.** ``cache_dir()`` is where AGENTS.md 1.5 puts
genotype-derived intermediates, and it is one of the paths the privacy suite asserts is
gitignored. The PLINK wrapper deliberately does not police this -- M5.3 writes a reference
panel subset under ``data/references/`` and is right to -- so the sample's side of the line
is drawn here, where it is known that the data is a person's.

**``--sort-vars`` is passed, and the records are sorted before writing anyway.** Neither is
redundant. Sorting here makes the intermediate deterministic and reviewable, and it is what
this repository can be held to; the flag covers the case that a panel's own ordering
disagrees with ours, which PLINK reports as a warning and otherwise proceeds past.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from genetics.external.harmonize import (
    HarmonizationReport,
    PanelSites,
    write_harmonized_vcf,
)
from genetics.external.plink2 import Plink2, Plink2ResultInfo
from genetics.ingest.schema import GenotypeTable
from genetics.paths import cache_dir
from genetics.privacy import NoGenotypeRepr

__all__ = ["ConversionResult", "EmptyHarmonizationError", "to_pgen"]

_DEFAULT_STEM = "sample"


class EmptyHarmonizationError(RuntimeError):
    """Harmonization produced no records, so there is nothing to convert.

    Raised here rather than left to PLINK, which answers "Error: No variants in --vcf
    file." -- true, and useless for finding the cause. The message carries the
    harmonization counts instead, which say whether the panel and the array disagree about
    chromosome naming (everything ``not_in_panel``), whether the panel is the wrong build
    (the same), or whether the panel file simply parsed to nothing.
    """

    def __init__(self, report: HarmonizationReport) -> None:
        super().__init__(
            "harmonization against "
            f"{report.panel_source} produced no usable records.\n{report.render()}"
        )
        self.report = report


@dataclass(frozen=True)
class ConversionResult(NoGenotypeRepr):
    """The pgen trio, plus how it was arrived at.

    Inherits the genotype-safe ``__repr__``: the paths themselves are harmless, but this
    object is the natural thing to log at the end of a conversion and it carries the report
    and the PLINK result along with them.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_variants", "plink_version")

    pgen: Path
    pvar: Path
    psam: Path
    vcf: Path | None
    """The intermediate, if it was kept. ``None`` when it was deleted, which is the
    default."""

    report: HarmonizationReport
    plink: Plink2ResultInfo
    plink_version: str

    @property
    def n_variants(self) -> int:
        return self.report.n_written


def to_pgen(
    table: GenotypeTable,
    panel: PanelSites,
    *,
    plink: Plink2,
    workspace: Path | None = None,
    stem: str = _DEFAULT_STEM,
    keep_vcf: bool = False,
) -> ConversionResult:
    """Harmonize ``table`` against ``panel`` and convert the result to a PLINK 2 pgen.

    Returns the paths written and the :class:`HarmonizationReport` describing what became
    of every autosomal position on the array -- which is the number M5.3 and M9.3 have to
    report on a card, since "your PRS used 412 of this score's 1,140 variants" is a
    statement about this step.

    Raises :class:`EmptyHarmonizationError` when nothing survived harmonization, and
    :class:`genetics.external.plink2.Plink2RunError` when PLINK itself refuses the input.
    """
    root = workspace if workspace is not None else cache_dir() / "plink"
    root.mkdir(parents=True, exist_ok=True)

    vcf_path = root / f"{stem}.harmonized.vcf"
    report = write_harmonized_vcf(table, panel, vcf_path)

    if report.n_written == 0:
        vcf_path.unlink(missing_ok=True)
        raise EmptyHarmonizationError(report)

    out_prefix = root / stem
    try:
        result = plink.run(
            ["--vcf", str(vcf_path), "--make-pgen", "--sort-vars"],
            out=out_prefix,
        )
    finally:
        # Deleted even when PLINK failed. The intermediate is a full copy of the person's
        # autosomal genotypes, and a failed run is exactly the situation in which files get
        # left behind and forgotten; `keep_vcf` is the deliberate opt-out for debugging.
        if not keep_vcf:
            vcf_path.unlink(missing_ok=True)

    return ConversionResult(
        pgen=out_prefix.with_name(f"{stem}.pgen"),
        pvar=out_prefix.with_name(f"{stem}.pvar"),
        psam=out_prefix.with_name(f"{stem}.psam"),
        vcf=vcf_path if keep_vcf else None,
        report=report,
        plink=result,
        plink_version=plink.version,
    )
