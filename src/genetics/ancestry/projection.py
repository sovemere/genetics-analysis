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

**The coordinates carry the identity of the reference they came from.** M5.5 compares a
sample against population centroids built from the panel's own projection, and two
projections against *different* eigenvector sets are coordinates in different spaces that
look identical: same columns, same count, same magnitude, and both plot. :attr:`Projection.
reference` is what lets that comparison be refused rather than silently made.

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


_PC_NAME: Final = re.compile(r"PC[0-9]+")
"""A component column in ``--pca allele-wts`` output: ``PC1``, ``PC2``, ...

Anchored by ``fullmatch`` so it cannot pick up a suffixed name. The ``.sscore`` side has
the mirror-image problem and solves it the same way -- see the note there on
``NAMED_ALLELE_DOSAGE_SUM``, which a suffix-only pattern carried in as an extra component.
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
    reference: str
    """Which reference PCA produced these coordinates -- the artifact prefix's *name*.

    Carried so M5.5 can refuse to compare a sample against population centroids built from
    a different eigenvector set. Two projections against different loadings are coordinates
    in different spaces, and nothing about them looks wrong: they have the same column
    names, the same component count and the same order of magnitude, and they plot. The
    name is the cache key's own (``refpca-<digest>``), so it identifies the artifact without
    carrying the path -- a ``cache_dir()`` path begins with the account name on Windows.
    """

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


_WEIGHT_ID_COLUMN: Final = "ID"
_WEIGHT_ALLELE_COLUMN: Final = "A1"


def _weight_columns(pca: ReferencePCA) -> tuple[int, int, int]:
    """``(id, effect allele, first component)`` as 1-based columns of the weight file.

    **Read from the header rather than counted, because the header is not the same width
    for every panel, and the failure when it moves is silent.** ``--pca allele-wts`` writes
    ``#CHROM ID REF ALT A1 PC1..`` when the panel's REF allele is known -- which is what
    1000 Genomes phase 3 gives, since it was called against the reference -- and
    ``#CHROM ID REF ALT PROVISIONAL_REF? A1 PC1..`` when it is not. M5.9's Human Origins
    panel is the second kind: it arrives as an EIGENSTRAT ``.snp``, which records the two
    alleles of each marker and does not say which of them the reference carries, so PLINK
    marks REF provisional and emits the extra column to say so.

    That one column is the whole bug. With the positions hard-coded at 2 and 5, the effect
    allele read as ``PROVISIONAL_REF?`` -- whose value is the letter ``Y`` -- so **all
    89,744 entries mismatched and PLINK refused the run**. It failed loudly here only
    because *every* entry mismatched; a file where the shifted column happened to hold
    plausible allele letters would have scored a subset and returned coordinates.

    Locating by name is what :func:`~genetics.external.harmonize.read_panel_sites` and
    :func:`~genetics.ancestry.eigenstrat.read_anno` already do, and for this reason.
    ``--score`` takes numbers, so the numbers are derived from the names rather than
    assumed alongside them.
    """
    path = pca.allele_weights
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            header = handle.readline()
    except OSError as exc:
        raise ProjectionError(
            f"could not read {path.name}: {exc.strerror or exc.__class__.__name__}"
        ) from exc
    columns = header.lstrip("#").split()
    if not columns:
        raise ProjectionError(
            f"{path.name} is empty, so the reference PCA has no allele weights to score "
            "against. Rebuild it with `build_reference_pca`."
        )
    try:
        # 1-based: PLINK counts columns from one.
        id_column = columns.index(_WEIGHT_ID_COLUMN) + 1
        allele_column = columns.index(_WEIGHT_ALLELE_COLUMN) + 1
    except ValueError as exc:
        raise ProjectionError(
            f"{path.name} names columns {columns[:8]}, which is missing "
            f"{_WEIGHT_ID_COLUMN!r} or {_WEIGHT_ALLELE_COLUMN!r}. `--score` joins on the "
            "first and weights the second, so neither can be guessed at."
        ) from exc

    components = [name for name in columns if _PC_NAME.fullmatch(name)]
    if len(components) < pca.n_components:
        raise ProjectionError(
            f"{path.name} carries {len(components)} component column(s) and the artifact "
            f"claims {pca.n_components}. One of the two is from a different build."
        )
    wanted_components = [f"PC{i + 1}" for i in range(pca.n_components)]
    if components[: pca.n_components] != wanted_components:
        raise ProjectionError(
            f"{path.name}'s first component columns are {components[:4]}, expected "
            f"{wanted_components[:4]} beginning at PC1. The weight file and artifact are "
            "from different builds."
        )
    first_pc = columns.index(components[0]) + 1
    expected = list(range(first_pc, first_pc + pca.n_components))
    actual = [columns.index(name) + 1 for name in components[: pca.n_components]]
    if actual != expected:
        raise ProjectionError(
            f"{path.name}'s component columns are not contiguous ({actual[:4]}...); "
            "`--score-col-nums` takes a range, so a gap would weight the wrong column."
        )
    return id_column, allele_column, first_pc


def project(
    pgen: Path,
    pca: ReferencePCA,
    *,
    plink: Plink2,
    workspace: Path | None = None,
    stem: str = "projection",
    min_coverage: float = _MIN_COVERAGE,
) -> Projection:
    """Score ``pgen`` against ``pca``'s allele weights and return the coordinates.

    ``pgen`` is a ``.pgen`` whose ``.pvar``/``.psam`` sit beside it -- the sample's, from
    :func:`genetics.external.pgen.to_pgen`, or the reference panel's when M5.5 needs the
    populations on the same scale. It must have been harmonized against the same panel the
    reference PCA was built from, because ``--score`` joins on variant ID.

    ``min_coverage`` is the structural tripwire described at :data:`_MIN_COVERAGE`, and it is
    a parameter rather than a constant only because M5.6 has a cohort the default is wrong
    for: ancient individuals are published with real missingness, so the *worst* of nine
    thousand of them legitimately sits below half. Lowering it is a statement that sparse
    coverage is expected here; leaving it alone is what every other caller should do.
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

    id_column, allele_column, first_pc = _weight_columns(pca)
    last_column = first_pc + pca.n_components - 1
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
            str(id_column),
            str(allele_column),
            "header-read",
            # A no-call contributes nothing rather than contributing the mean. Mean
            # imputation would pull every sparsely-called sample toward the origin, which
            # on an ancestry plot reads as "averagely admixed" rather than as "we know
            # less about this person".
            "no-mean-imputation",
            "variance-standardize",
            "--score-col-nums",
            f"{first_pc}-{last_column}",
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
    if coverage < min_coverage:
        raise ProjectionError(
            f"the worst-covered sample scored only {scored_markers:,} of the reference's "
            f"{pca.n_markers:,} markers ({coverage:.1%}, floor {min_coverage:.1%}). At the "
            "default floor the realistic cause is a mismatch rather than a poorly-called "
            "sample: genotypes harmonized against a different panel carry variant IDs the "
            "reference lacks, so `--score` matches almost nothing and still returns "
            "coordinates that plot. A genuinely sparse cohort -- M5.6 projects pseudo-haploid "
            "ancient individuals whose missingness is a property of the archive -- should "
            "lower `min_coverage` deliberately rather than meet this by accident."
        )

    return Projection(
        coordinates=coordinates,
        n_scored_alleles=scored_alleles,
        n_reference_markers=pca.n_markers,
        n_components=pca.n_components,
        reference=pca.prefix.name,
        sscore=sscore,
        plink=result,
    )
