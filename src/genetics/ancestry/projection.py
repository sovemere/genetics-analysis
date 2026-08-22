"""Projecting a genotype set onto the reference PCs (roadmap M5.4).

:mod:`genetics.ancestry.reference_pca` computed the loadings; this applies them, through
PLINK 2's ``--score`` as AGENTS.md 4.6 requires (**not** ADMIXTURE). The output is the
continuous ancestry coordinates M5.5 renders and M5.8 feeds into PRS confidence.

**``--read-freq`` is mandatory and its absence is the failure mode to know about.**
Measured during the M5.3 trial: given a single sample, PLINK refuses to impute allele
frequencies and stops with "less than 50 samples are available to impute them from". That
error names allele frequencies and says nothing that sounds like a missing artifact, so
somebody hitting it looks at the sample rather than at the reference. The eigenvector build
emits an ``.afreq`` precisely so this step can pass it, and :class:`ReferencePCA` carries
its path rather than leaving the pairing to a caller.

**This takes any pgen, not "the sample's" pgen, and that is the whole design.** PLINK's
``--score`` reports per-component averages (``PC1_AVG``..) whose absolute scale relative to
the reference's own ``.eigenvec`` this module does not assert -- deriving that constant from
memory is exactly the plausible-looking fabrication AGENTS.md 6 forbids, and getting it
subtly wrong would move every sample the same distance in a way no test would catch. The
scale does not have to be known. What M5.5 needs is that the sample and the reference
populations are *comparable*, and that is guaranteed by construction if both are projected
through this same function: whatever the constant is, it is the same one on both sides. So
M5.5 projects the reference panel through here too, rather than reading coordinates out of
``.eigenvec`` and hoping the units agree.

**Coverage is reported, not silently absorbed.** ``no-mean-imputation`` means a no-call
contributes nothing rather than contributing the mean, which is the honest choice -- mean
imputation pulls every sparse sample toward the origin, i.e. toward looking "averagely
admixed" -- but it means the coordinates of a poorly-called sample rest on fewer markers.
:attr:`Projection.coverage` is what M5.5 turns into confidence, and AGENTS.md 6 says
confidence is computed rather than authored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

import polars as pl

from genetics.ancestry.reference_pca import ReferencePCA
from genetics.external.plink2 import Plink2, Plink2ResultInfo
from genetics.paths import cache_dir
from genetics.privacy import NoGenotypeRepr

__all__ = ["Projection", "ProjectionError", "project"]

_SCORE_COLUMN: Final[re.Pattern[str]] = re.compile(r"^(?:PC|SCORE)(\d+)_(?:AVG|SUM)$")
"""Which ``.sscore`` columns carry the components.

**``PC`` and not only ``SCORE``, and that was measured rather than assumed.** With
``header-read`` PLINK names each output column after the corresponding column in the score
file, and the score file here is a ``.eigenvec.allele`` whose columns are ``PC1``..``PCk``.
So the real output is ``PC1_AVG``, not ``SCORE1_AVG``. Run against the pinned build
(v2.0.0-a.7.3) over a synthetic 60-sample panel::

    #IID  ALLELE_CT  NAMED_ALLELE_DOSAGE_SUM  PC1_AVG  PC2_AVG  PC3_AVG  PC4_AVG

``SCORE`` is kept for the case where the score file carries no header and PLINK falls back
to numbering.

Matched by pattern and ordered by the captured number rather than taken positionally: the
leading columns vary with the flags in play (``ALLELE_CT``, ``NAMED_ALLELE_DOSAGE_SUM`` and
friends appear conditionally), so counting from the left is a way to silently read a dosage
total as a principal component. Note that ``NAMED_ALLELE_DOSAGE_SUM`` ends in ``_SUM``,
which is why the pattern is anchored on the prefix as well as the suffix.
"""

_ALLELES_PER_MARKER: Final = 2
"""``ALLELE_CT`` counts alleles, not markers, and this pipeline is diploid throughout.

Measured against the pinned build: a sample with 5 of 100 variants no-called reported
``ALLELE_CT`` 190 -- twice the 95 markers that actually scored, because
``no-mean-imputation`` drops the missing ones and each remaining call contributes two
alleles. Dividing is safe here specifically because everything upstream is autosomal:
:func:`genetics.ancestry.reference_pca.array_marker_positions` filters to
:data:`~genetics.ingest.schema.AUTOSOMES` and the marker subset is built from the autosomes
alone, so there is no haploid region in play. **Reading ``ALLELE_CT`` as a marker count
directly is what this constant exists to prevent** -- it made ``coverage`` report 1.9 for a
95%-called sample, a number that is both wrong and impossible.
"""

_MIN_COVERAGE: Final = 0.5
"""Floor on the fraction of reference markers a projection actually scored.

Not a quality threshold -- M5.5 grades quality from :attr:`Projection.coverage`, which is a
continuous number and is reported whatever it is. This is the tripwire for the structural
failure: a sample harmonized against a different panel, or one whose variant IDs do not
match the reference's, scores a handful of markers and still returns finite coordinates
that plot somewhere plausible. Half is far below anything a working pipeline produces and
far above what a mismatch produces.
"""


class ProjectionError(RuntimeError):
    """The sample could not be projected onto the reference PCs."""


@dataclass(frozen=True)
class Projection(NoGenotypeRepr):
    """Per-sample coordinates on the reference PCs.

    The coordinates *are* derived from a person's genotypes, so this inherits the
    genotype-safe ``__repr__``: they are a lossy summary rather than calls, but they are
    still an inference about an individual and this is the object a caller logs.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_samples", "n_components", "coverage")

    coordinates: pl.DataFrame
    """One row per sample: ``sample_id`` plus ``PC1``..``PCk`` as floats."""

    n_scored_alleles: int
    """PLINK's ``ALLELE_CT``: *alleles*, not markers, and the minimum across samples.

    Kept in PLINK's own units so the name cannot be misread. Use :attr:`n_scored_markers`
    for a marker count."""

    n_reference_markers: int
    n_components: int
    sscore: Path
    plink: Plink2ResultInfo

    @property
    def n_samples(self) -> int:
        return self.coordinates.height

    @property
    def n_scored_markers(self) -> int:
        """Reference markers that contributed, for the worst-covered sample.

        ``ALLELE_CT`` halved -- see :data:`_ALLELES_PER_MARKER` for the measurement and for
        why halving is valid here.
        """
        return self.n_scored_alleles // _ALLELES_PER_MARKER

    @property
    def coverage(self) -> float:
        """Fraction of the reference's markers this projection actually used.

        M5.5's input to confidence. One number rather than a verdict, because the threshold
        at which coverage stops supporting a population call is a question about the
        populations, not about this step.
        """
        if self.n_reference_markers == 0:
            return 0.0
        return self.n_scored_markers / self.n_reference_markers


def _score_columns(frame: pl.DataFrame) -> list[str]:
    """The component columns, in component order."""
    matched: list[tuple[int, str]] = []
    for name in frame.columns:
        found = _SCORE_COLUMN.match(name)
        if found is not None:
            matched.append((int(found.group(1)), name))
    return [name for _, name in sorted(matched)]


def _read_sscore(path: Path, *, n_components: int) -> tuple[pl.DataFrame, int]:
    """Parse a ``.sscore`` into coordinates plus the allele count PLINK actually used.

    The header line begins with ``#``; PLINK writes ``#IID`` or ``#FID\tIID`` depending on
    whether the input carried family IDs, so the sample column is located by name rather
    than by position for the same reason the score columns are.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ProjectionError(f"could not read {path.name}: {exc}") from exc

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ProjectionError(
            f"{path.name} holds no scored samples. PLINK wrote a header and nothing else, "
            "which means every variant was dropped before scoring."
        )

    header = [column.lstrip("#") for column in lines[0].split("\t")]
    rows = [line.split("\t") for line in lines[1:]]
    # Padding a short row instead would put an empty string where a coordinate belongs, and
    # the failure would surface as a cast error naming a Polars column rather than a
    # truncated file. AGENTS.md 6: fail loudly on malformed input.
    ragged = next((i for i, row in enumerate(rows) if len(row) != len(header)), None)
    if ragged is not None:
        raise ProjectionError(
            f"{path.name} is malformed: data row {ragged + 1} has {len(rows[ragged])} field(s) "
            f"where the header declares {len(header)}. The file was most likely truncated."
        )
    frame = pl.DataFrame({name: [row[i] for row in rows] for i, name in enumerate(header)})

    if "IID" not in frame.columns:
        raise ProjectionError(f"{path.name} has no IID column; got {', '.join(frame.columns)}.")

    score_columns = _score_columns(frame)
    if len(score_columns) != n_components:
        raise ProjectionError(
            f"{path.name} carries {len(score_columns)} component column(s) but the reference "
            f"PCA has {n_components}. The score file and the reference have diverged; rebuild "
            "the reference PCA."
        )

    # ALLELE_CT only. NAMED_ALLELE_DOSAGE_SUM is a dosage total that happens to equal it on
    # some inputs and is not a count of anything scored, so falling back to it would put a
    # different quantity behind the same name whenever the first column were absent.
    #
    # The minimum across samples, not the first row's: for a single sample they are the
    # same, and for the whole reference panel -- which M5.5 projects through this function
    # too -- the coverage floor below should be judged on the worst-covered sample rather
    # than on whichever one PLINK happened to write first.
    #
    # Its absence is an error rather than a zero. Defaulting to zero would make coverage 0%
    # and trip the mismatch floor below, reporting "harmonized against a different panel"
    # for a file that is merely missing a column -- a confident diagnosis of the wrong
    # problem, which is worse than no diagnosis.
    if "ALLELE_CT" not in frame.columns:
        raise ProjectionError(
            f"{path.name} has no ALLELE_CT column, so how many markers were scored cannot be "
            f"determined. Columns present: {', '.join(frame.columns)}."
        )
    counts = frame.get_column("ALLELE_CT").cast(pl.Float64, strict=False)
    smallest = counts.min()
    if not isinstance(smallest, (int, float)):
        raise ProjectionError(f"{path.name}: ALLELE_CT holds no readable number.")
    scored_alleles = int(smallest)

    coordinates = frame.select(
        pl.col("IID").alias("sample_id"),
        *[
            pl.col(name).cast(pl.Float64).alias(f"PC{index + 1}")
            for index, name in enumerate(score_columns)
        ],
    )
    return coordinates, scored_alleles


def project(
    pgen: Path,
    pca: ReferencePCA,
    *,
    plink: Plink2,
    workspace: Path | None = None,
    stem: str = "projection",
) -> Projection:
    """Score ``pgen`` against ``pca``'s allele weights and return the coordinates.

    ``pgen`` is a ``.pgen`` whose ``.pvar``/``.psam`` sit beside it -- the sample's, from
    :func:`genetics.external.pgen.to_pgen`, or the reference panel's when M5.5 needs the
    populations on the same scale. It must have been harmonized against the same panel the
    reference PCA was built from, because ``--score`` joins on variant ID.
    """
    for suffix in (".pgen", ".pvar", ".psam"):
        companion = pgen.with_suffix(suffix)
        if not companion.is_file():
            raise ProjectionError(
                f"the genotype fileset is incomplete: {companion.name} is missing."
            )
    for path in (pca.allele_weights, pca.frequencies):
        if not path.is_file():
            raise ProjectionError(
                f"the reference PCA is incomplete: {path.name} is missing. Rebuild it with "
                "`build_reference_pca`."
            )

    root = workspace if workspace is not None else cache_dir() / "ancestry"
    root.mkdir(parents=True, exist_ok=True)
    out = root / stem

    last_column = 5 + pca.n_components
    result = plink.run(
        [
            "--pfile",
            str(pgen.with_suffix("")),
            # Without this PLINK refuses to project a single sample, and says so in terms
            # that point at the sample rather than at the reference. See the module note.
            "--read-freq",
            str(pca.frequencies),
            "--score",
            str(pca.allele_weights),
            # Column 2 is the variant ID, column 5 the effect allele: the layout PLINK
            # itself writes for `--pca allele-wts`, confirmed in the M5.3 trial run.
            "2",
            "5",
            "header-read",
            # A no-call contributes nothing rather than contributing the mean. Mean
            # imputation would pull every sparsely-called sample toward the origin, which
            # on an ancestry plot reads as "averagely admixed" rather than as "we know
            # less about this person".
            "no-mean-imputation",
            "variance-standardize",
            "--score-col-nums",
            f"6-{last_column}",
        ],
        out=out,
    )

    sscore = out.with_name(out.name + ".sscore")
    if not sscore.is_file():
        raise ProjectionError(
            f"PLINK 2 reported success but wrote no {sscore.name}. Its log is at "
            f"{result.log_path.name}."
        )

    coordinates, scored_alleles = _read_sscore(sscore, n_components=pca.n_components)
    scored_markers = scored_alleles // _ALLELES_PER_MARKER
    coverage = scored_markers / pca.n_markers if pca.n_markers else 0.0
    if coverage < _MIN_COVERAGE:
        raise ProjectionError(
            f"only {scored_markers:,} of the reference's {pca.n_markers:,} markers were "
            f"scored ({coverage:.1%}). That is a mismatch rather than a poorly-called sample: the "
            "genotypes were most likely harmonized against a different panel, so their "
            "variant IDs do not match the reference's and `--score` matched almost nothing."
        )

    return Projection(
        coordinates=coordinates,
        n_scored_alleles=scored_alleles,
        n_reference_markers=pca.n_markers,
        n_components=pca.n_components,
        sscore=sscore,
        plink=result,
    )
