"""GRCh37 pseudoautosomal boundaries, shared by QC and structure reporting.

Coordinates are 1-based, inclusive, from the Genome Reference Consortium:
https://www.ncbi.nlm.nih.gov/grc/human (GRCh37, GCF_000001405.13).
Vendor-labelled PAR is excluded regardless of its coordinate convention.
"""

import polars as pl

PAR_SOURCE = "https://www.ncbi.nlm.nih.gov/grc/human"
PAR_GRCH37 = {
    "X": ((60_001, 2_699_520), (154_931_044, 155_260_560)),
    "Y": ((10_001, 2_649_520), (59_034_050, 59_363_566)),
}


def coordinate_par_expr(chrom: str) -> pl.Expr:
    """PAR rows labelled X or Y, using the verified assembly coordinates."""
    first, second = PAR_GRCH37[chrom]
    position = pl.col("pos_grch37")
    return (pl.col("chrom").cast(pl.String) == chrom) & (
        position.is_between(*first, closed="both") | position.is_between(*second, closed="both")
    )


def nonpar_expr(chrom: str) -> pl.Expr:
    return (pl.col("chrom").cast(pl.String) == chrom) & ~coordinate_par_expr(chrom)
