"""What the ancestry stage hands to the rest of a run (roadmap M5.8).

M5.1-M5.7 and M5.9 built every piece of ancestry inference and validated each against real
data. None of it was reachable from ``genetics run``: the pipeline gave every card the same
fixed observation and never asked where the sample sits. This module is the stage that asks,
and :class:`AncestryContext` is what it answers with. It runs before any card is assembled,
because PRS confidence depends on it (AGENTS.md 4.4) -- the ordering is the requirement.

**The whole design is that a refusal is not a missing value.** M5.5 can decline to name a
population, and that is its load-bearing feature: a sample from a region the panel does not
cover would otherwise be labelled with the least-bad neighbour and every later score would be
reported as more portable than it is. A context that stored the population as ``str | None``
would lose that at the first reader, because ``None`` is how an unfilled field reads -- "not
computed yet" -- and "computed, and nothing fits" is the opposite claim. So each part of the
result carries an explicit status, the status is *derived* from what is present rather than
stored beside it, and the combinations that would contradict each other cannot be built:

=================  ======================================================================
``not_run``        No inference was made. The reason says why: a reference not fetched or
                   not built, PLINK 2 not installed, or an export sharing too little with
                   the panel to place it. Ancestry is *unknown*.
``placed``         A reference population fits and is named.
``declined``       The sample fits no reference population. Ancestry is known to be
                   *unrepresented* -- a positive finding that M9.5 must discount every
                   polygenic score for, not a gap to be filled with a default.
=================  ======================================================================

The haplogroups and ancient affinity ride along with their own statuses, because they have
their own prerequisites: a run with PhyloTree fetched and AADR not can still call an mtDNA
haplogroup, and Y is ``not_applicable`` -- not ``not_run`` -- for a sample QC inferred female.

**Absent is not the same as wrong.** A reference that has not been fetched or built, and a
PLINK 2 that is not installed, are the expected state of a fresh checkout and produce
``not_run`` -- ``genetics doctor``'s stance that absence is not an error. A reference that
*is* present and fails verification, or that cannot be parsed, is wrong for every run on this
machine, and raises :class:`AncestryError`: the same line ``qc.build_anchors.default_anchors``
draws, where an absent artifact leaves a check indeterminate and a malformed one fails loudly.

The one refusal that stays quiet is about the export rather than the installation.
:class:`~genetics.ancestry.reference_pca.InsufficientOverlapError` means the chip carries too
little of the panel to build a space from -- the synthetic fixtures, whose coordinates are
invented, are the case every test run meets. That is a fact about one file, so it is recorded
as ``not_run`` with the reason rather than failing the whole run over it.

**Nothing here decides what a card's confidence becomes.** Turning a placement into
``ancestry_match`` needs a mapping from the panel's 100 populations to the five study-ancestry
codes cards declare, and no such mapping exists yet; M9.5 owns it. What M5.8 guarantees is
that when M9.5 arrives, the input it reads cannot be misread.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Final

from genetics.ancestry import phylotree, ytree
from genetics.ancestry.aadr import (
    MIN_SHARED_COVERAGE,
    AadrError,
    AncientAffinity,
    affinity,
    build_ancient_model,
    select_ancient_individuals,
    shared_positions,
    write_ancient_vcf,
)
from genetics.ancestry.eigenstrat import (
    EigenstratError,
    annotate,
    hasharr,
    open_packed,
    read_anno,
    read_ind,
    read_snp,
)
from genetics.ancestry.haplogroup import HaplogroupCall
from genetics.ancestry.haplogroup import call as call_haplogroup
from genetics.ancestry.populations import (
    Placement,
    PopulationsError,
    build_population_model,
    place,
    read_aadr_population_labels,
    read_population_labels,
)
from genetics.ancestry.projection import Projection, ProjectionError, project
from genetics.ancestry.reference_pca import (
    InsufficientOverlapError,
    ReferencePCA,
    ReferencePcaError,
    build_reference_pca,
)
from genetics.external.harmonize import PanelError, read_panel_sites
from genetics.external.pgen import EmptyHarmonizationError, to_pgen
from genetics.external.plink2 import Plink2, Plink2Error, Plink2NotFoundError
from genetics.ingest.schema import GenotypeTable
from genetics.paths import cache_dir, reference_lock, reference_manifest, references_dir
from genetics.privacy import NoGenotypeRepr
from genetics.qc.report import InferredSex, QCReport
from genetics.refs import lock as refs_lock
from genetics.refs import manifest as refs_manifest
from genetics.refs import postprocess

__all__ = [
    "AffinityResult",
    "AffinityStatus",
    "AncestryContext",
    "AncestryError",
    "AncestryStage",
    "LineageResult",
    "LineageStatus",
    "PlacementStatus",
    "PopulationResult",
    "infer_ancestry",
]


MODERN_PANEL_SOURCE: Final = "aadr"
MODERN_PANEL_STEP: Final = "build_modern_reference_panel"
"""Where a sample is placed: M5.9's 100-population Human Origins panel."""

SHARED_SPACE_SOURCE: Final = "thousand_genomes_phase3_grch37"
SHARED_SPACE_STEP: Final = "build_pca_marker_subset"
"""What M5.6's shared space is built from. Ancient affinity needs the modern populations,
the ancient individuals and the sample in one space, and M5.6 built and validated that
space on the 1000 Genomes subset restricted to what AADR also carries."""

SHARED_SPACE: Final = "aadr_shared"
"""The ``space`` name the restricted reference PCA records in its provenance."""

_LABELS_SUFFIX: Final = ".panel"
"""The 1000 Genomes sample-panel file, located in the manifest by suffix -- the same way
:func:`~genetics.refs.postprocess.aadr_input_paths` finds the AADR files -- so the release
named in the filename lives in one place."""

_ANCIENT_PROJECTION_FLOOR: Final = MIN_SHARED_COVERAGE / 2
"""The structural tripwire :func:`~genetics.ancestry.projection.project` applies, lowered for
the ancient cohort on purpose.

The criterion for an ancient individual is applied earlier, by
:func:`~genetics.ancestry.aadr.select_ancient_individuals`: at least
:data:`~genetics.ancestry.aadr.MIN_SHARED_COVERAGE` of this space's markers called. The
projection then scores slightly fewer, because :func:`~genetics.ancestry.aadr.
write_ancient_vcf` drops the few sites whose AADR alleles disagree with the panel -- so an
individual exactly at the selection floor projects a hair below it, and the default floor
would refuse the whole cohort for it. What the tripwire exists to catch, a sample harmonized
against a different panel, scores near zero; half the selection floor still catches that."""


class AncestryError(RuntimeError):
    """A prerequisite is present and wrong.

    An artifact that fails verification, a reference file that cannot be parsed, a PLINK 2
    that is not the pinned build. Never raised for something merely absent -- that is
    ``not_run`` -- because absence is what a fresh checkout looks like and this is for what
    has to be fixed before any run on this machine can be trusted.
    """


# ---------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------


class PlacementStatus(StrEnum):
    NOT_RUN = "not_run"
    PLACED = "placed"
    DECLINED = "declined"


class LineageStatus(StrEnum):
    NOT_RUN = "not_run"
    CALLED = "called"
    NOT_APPLICABLE = "not_applicable"


class AffinityStatus(StrEnum):
    NOT_RUN = "not_run"
    COMPUTED = "computed"


def _require_reason(reason: str, what: str) -> None:
    if not reason.strip():
        raise AncestryError(
            f"{what} carries no reason. A result that says nothing was inferred without "
            "saying why is the silent gap this type exists to prevent."
        )


@dataclass(frozen=True)
class PopulationResult(NoGenotypeRepr):
    """Where the sample sits among living populations, or why that was not inferred.

    Holds either a :class:`~genetics.ancestry.populations.Placement` or a reason, never both
    and never neither. The status is read off which one is present, so ``placed`` without a
    population and ``declined`` without a decline sentence cannot be constructed.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("status",)

    placement: Placement | None = None
    not_run_reason: str = ""
    reference: str = ""
    """The eigenvector set the sample was placed in -- the artifact prefix's name, as
    :attr:`~genetics.ancestry.projection.Projection.reference` records it."""

    reference_markers: int = 0
    n_components: int = 0

    def __post_init__(self) -> None:
        if self.placement is None:
            _require_reason(self.not_run_reason, "a population result with no placement")
        elif self.not_run_reason:
            raise AncestryError("a population result cannot hold a placement and a reason")

    @property
    def status(self) -> PlacementStatus:
        if self.placement is None:
            return PlacementStatus.NOT_RUN
        return PlacementStatus.PLACED if self.placement.named else PlacementStatus.DECLINED

    @property
    def reason(self) -> str:
        """Why no population is named: the not-run reason or M5.5's decline sentence.

        Empty exactly when the status is ``placed``.
        """
        if self.placement is None:
            return self.not_run_reason
        return self.placement.declined_because

    def to_dict(self) -> dict[str, Any]:
        placement = self.placement
        coverage = None if placement is None else placement.panel_coverage
        return {
            "status": self.status.value,
            "reason": self.reason,
            "population": None if placement is None else placement.population,
            "region": None if placement is None else placement.region,
            "reference": self.reference or None,
            "reference_markers": self.reference_markers if placement is not None else None,
            "n_components": self.n_components if placement is not None else None,
            "panel": None
            if placement is None
            else {
                "name": None if coverage is None else coverage.name,
                "labels_source": placement.labels_source,
                "n_samples": placement.n_panel_samples,
                "n_populations": placement.n_populations,
                # None is "nobody has written down what this panel cannot answer for" --
                # never "no gaps". See populations.coverage_for.
                "gaps": None
                if coverage is None
                else [{"region": gap.region, "note": gap.note} for gap in coverage.gaps],
            },
            "decline_threshold": None if placement is None else placement.decline_threshold,
            "coverage": None if placement is None else placement.coverage,
            "n_scored_markers": None if placement is None else placement.n_scored_markers,
            "coordinates": None if placement is None else list(placement.coordinates),
            "fits": None
            if placement is None
            else [
                {
                    "population": fit.population,
                    "region": fit.region,
                    "n_samples": fit.n_samples,
                    "distance": fit.distance,
                    "radius": fit.radius,
                    "fit": fit.fit,
                    "percentile": fit.percentile,
                }
                for fit in placement.fits
            ],
        }


@dataclass(frozen=True)
class LineageResult(NoGenotypeRepr):
    """One uniparental haplogroup, or why there is none.

    ``status`` is stored here rather than derived, because two different reasons leave the
    call empty -- a tree not fetched, and a lineage the sample does not have -- and only the
    status tells them apart. The pairing is checked instead: ``called`` holds a call and
    nothing else does.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("lineage", "status")

    lineage: str
    status: LineageStatus
    call: HaplogroupCall | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.lineage not in {"MT", "Y"}:
            raise AncestryError(f"lineage must be 'MT' or 'Y', got {self.lineage!r}")
        if (self.status is LineageStatus.CALLED) != (self.call is not None):
            raise AncestryError(
                f"a {self.status.value} {self.lineage} result must "
                f"{'hold' if self.status is LineageStatus.CALLED else 'not hold'} a call"
            )
        if self.status is not LineageStatus.CALLED:
            _require_reason(self.reason, f"a {self.status.value} {self.lineage} result")

    def to_dict(self) -> dict[str, Any]:
        call = self.call
        return {
            "status": self.status.value,
            "reason": self.reason,
            "lineage": self.lineage,
            "source": None if call is None else call.source,
            "haplogroup": None if call is None else call.haplogroup,
            "depth": None if call is None else call.depth,
            "supporting": None if call is None else call.supporting,
            "contradicting": None if call is None else call.contradicting,
            "markers_on_array": None if call is None else call.markers_on_array,
            "markers_typed": None if call is None else call.markers_typed,
            "stopped_because": None if call is None else call.stopped_because,
            "path": None
            if call is None
            else [
                {
                    "name": step.name,
                    "supporting": step.supporting,
                    "contradicting": step.contradicting,
                    "uncertain_support": step.uncertain_support,
                    "typed": step.typed,
                }
                for step in call.path
            ],
        }


@dataclass(frozen=True)
class AffinityResult(NoGenotypeRepr):
    """Distances to ancient groups (M5.6), or why they were not computed.

    Labelled affinity and never descent, for the reasons :mod:`genetics.ancestry.aadr` measured.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("status",)

    affinity: AncientAffinity | None = None
    not_run_reason: str = ""
    reference: str = ""

    def __post_init__(self) -> None:
        if self.affinity is None:
            _require_reason(self.not_run_reason, "an affinity result with no affinity")
        elif self.not_run_reason:
            raise AncestryError("an affinity result cannot hold an affinity and a reason")

    @property
    def status(self) -> AffinityStatus:
        return AffinityStatus.NOT_RUN if self.affinity is None else AffinityStatus.COMPUTED

    def to_dict(self) -> dict[str, Any]:
        found = self.affinity
        return {
            "status": self.status.value,
            "reason": self.not_run_reason,
            "reference": self.reference or None,
            "source": None if found is None else found.source,
            "coverage": None if found is None else found.coverage,
            "n_scored_markers": None if found is None else found.n_scored_markers,
            "n_shared_markers": None if found is None else found.n_shared_markers,
            "n_ancient_individuals": None if found is None else found.n_ancient_individuals,
            "pseudo_haploid_fraction": None if found is None else found.pseudo_haploid_fraction,
            "n_dropped_groups": None if found is None else len(found.dropped_groups),
            "spread": None if found is None else found.spread,
            "groups": None
            if found is None
            else [
                {
                    "group": group.group,
                    "n_individuals": group.n_individuals,
                    "date_bp_median": group.date_bp_median,
                    "date_bp_range": list(group.date_bp_range),
                    "distance": group.distance,
                    "mean_called": group.mean_called,
                }
                for group in found.groups
            ],
        }


@dataclass(frozen=True)
class AncestryContext(NoGenotypeRepr):
    """Everything M5 inferred for one run, carried to every stage that runs after it.

    ``_repr_fields`` shows the four statuses and nothing else. A population name, a
    haplogroup and a ranked list of ancient groups are each an inference about a person, and
    a haplogroup restates the genotypes at every site that defines it.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("status",)

    population: PopulationResult
    mt: LineageResult
    y: LineageResult
    ancient: AffinityResult

    def __post_init__(self) -> None:
        if self.mt.lineage != "MT" or self.y.lineage != "Y":
            raise AncestryError("the mt and y slots must hold the MT and Y lineages")

    @property
    def status(self) -> PlacementStatus:
        """The population placement's status: what PRS confidence reads (AGENTS.md 4.4)."""
        return self.population.status

    @classmethod
    def not_run(cls, reason: str) -> AncestryContext:
        """Every part not run, for the same reason."""
        return cls(
            population=PopulationResult(not_run_reason=reason),
            mt=LineageResult("MT", LineageStatus.NOT_RUN, reason=reason),
            y=LineageResult("Y", LineageStatus.NOT_RUN, reason=reason),
            ancient=AffinityResult(not_run_reason=reason),
        )

    def to_dict(self) -> dict[str, Any]:
        """The whole record, for the run bundle (M4.1's ``ancestry.run.json``)."""
        return {
            "population": self.population.to_dict(),
            "mt": self.mt.to_dict(),
            "y": self.y.to_dict(),
            "ancient": self.ancient.to_dict(),
        }

    def summary(self) -> dict[str, Any]:
        """Statuses, reasons and counts -- what ``genetics run`` prints.

        No population, haplogroup or ancient group name. ``genetics run`` reports whether
        the pipeline worked and where the result went, not the result; the names are in
        the saved run, where ``genetics runs show`` reads them.
        """
        population = self.population
        placement = population.placement
        ancient = self.ancient.affinity
        return {
            "population": {
                "status": population.status.value,
                "reason": population.not_run_reason,
                "n_populations": None if placement is None else placement.n_populations,
                "coverage": None if placement is None else placement.coverage,
                "reference_markers": None if placement is None else population.reference_markers,
            },
            **{
                name: {
                    "status": lineage.status.value,
                    "reason": lineage.reason,
                    "supporting": None if lineage.call is None else lineage.call.supporting,
                    "markers_on_array": None
                    if lineage.call is None
                    else lineage.call.markers_on_array,
                }
                for name, lineage in (("mt", self.mt), ("y", self.y))
            },
            "ancient": {
                "status": self.ancient.status.value,
                "reason": self.ancient.not_run_reason,
                "n_groups": None if ancient is None else ancient.n_groups,
            },
        }


AncestryStage = Callable[[GenotypeTable, QCReport], AncestryContext]
"""What :func:`genetics.run.pipeline.analyse` calls. :func:`infer_ancestry` is the one it
uses unless told otherwise."""


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _References:
    """The reference tree this stage reads, and the lock digests that vouch for it."""

    root: Path
    manifest: refs_manifest.Manifest
    digests: Mapping[str, Mapping[str, str]]

    @classmethod
    def load(cls, root: Path) -> _References:
        manifest = refs_manifest.load(reference_manifest())
        lock_path = root / reference_lock().name
        digests: dict[str, dict[str, str]] = {}
        if lock_path.is_file():
            try:
                lock = refs_lock.read(lock_path)
            except (refs_lock.LockError, OSError, UnicodeDecodeError) as exc:
                raise AncestryError(f"{lock_path.name} cannot be read: {exc}") from exc
            digests = {
                source_id: {name: entry.sha256 for name, entry in source.files.items()}
                for source_id, source in lock.sources.items()
            }
        return cls(root=root, manifest=manifest, digests=digests)

    def source(self, source_id: str) -> refs_manifest.Source:
        return self.manifest.get(source_id)

    def verified_output(self, source_id: str, step: str) -> Path | str:
        """The step's output if it verifies, else the reason it is absent.

        Verified by :func:`genetics.refs.postprocess.run` -- the same check ``genetics refs
        verify`` makes, so the two cannot disagree about whether an artifact is usable. The
        lock's digests stand in for re-hashing the inputs, as they do for ``refs fetch``; that
        the files on disk still match the lock is ``refs verify``'s job, not every run's.
        """
        source = self.source(source_id)
        results = postprocess.run(
            source,
            root=self.root,
            verify_only=True,
            input_digests=self.digests.get(source_id, {}),
        )
        result = next((item for item in results if item.step == step), None)
        if result is None:
            # A step earlier in this source's list failed, and `run` stops there.
            failed = next(item for item in results if not item.ok)
            raise AncestryError(
                f"{source_id}: {failed.step} failed verification ({failed.detail}), so "
                f"{step} could not be checked. `genetics refs verify` reports the same."
            )
        if result.status is postprocess.ProcessStatus.PENDING:
            return (
                f"{source_id} has not been built into {result.output or step} "
                f"({result.detail}). `genetics refs fetch --only {source_id}` fetches and "
                "builds it."
            )
        if not result.ok:
            raise AncestryError(
                f"{source_id}: {result.output or step} is present and fails verification "
                f"({result.detail}). `genetics refs fetch --only {source_id}` rebuilds it."
            )
        return (self.root / source_id / str(result.output)).resolve()

    def aadr_inputs(self) -> dict[str, Path] | str:
        """The AADR trio and annotation sheet, or the reason they are not on disk."""
        source = self.source(MODERN_PANEL_SOURCE)
        try:
            return postprocess.aadr_input_paths(source, (self.root / source.id).resolve())
        except postprocess.ProcessError as exc:
            return f"{source.id} is not fully fetched ({exc})."

    def payload(self, source_id: str, suffix: str) -> Path | str:
        """The one payload file of ``source_id`` ending in ``suffix``, or why it is absent."""
        source = self.source(source_id)
        names = [item.filename for item in source.files if item.filename.endswith(suffix)]
        if len(names) != 1:
            raise AncestryError(
                f"{source_id} declares {len(names)} file(s) ending {suffix!r}; exactly one "
                "was expected."
            )
        path = self.root / source_id / names[0]
        if not path.is_file():
            return f"{names[0]} is not fetched. `genetics refs fetch --only {source_id}`."
        return path


class _Plink:
    """PLINK 2, discovered once and only when a stage part actually needs it."""

    def __init__(self, tools_root: Path | None) -> None:
        self._tools_root = tools_root
        self._found: Plink2 | None = None
        self._missing = ""

    def get(self) -> Plink2 | str:
        if self._found is not None:
            return self._found
        if self._missing:
            return self._missing
        try:
            self._found = Plink2.discover(tools_root=self._tools_root)
        except Plink2NotFoundError as exc:
            self._missing = str(exc)
            return self._missing
        except Plink2Error as exc:
            # Present and not the pinned build. Coordinates from an untested alpha look
            # exactly like coordinates from the pinned one (M5.1), so this is wrong rather
            # than absent.
            raise AncestryError(str(exc)) from exc
        return self._found


@contextmanager
def _scratch(parent: Path) -> Iterator[Callable[[], Path]]:
    """A per-run directory for the sample's own intermediates, removed afterwards.

    The sample's harmonized pgen and its projections are a copy of the person's genotypes
    and derived coordinates. They live under ``cache_dir()`` (AGENTS.md 1.5) and do not
    outlive the run -- the same reasoning ``to_pgen`` applies to its VCF. The reference PCA
    beside it is kept: it is a property of the panel and the chip, rebuilt only when either
    changes.

    Created on first use rather than on entry. A run with nothing fetched -- every test run,
    and every fresh checkout -- would otherwise make and remove a directory in the user's
    data directory for no part that computes anything. Removal is not told to ignore errors:
    a copy of the sample's genotypes that could not be deleted is something to hear about.
    """
    made: list[Path] = []

    def get() -> Path:
        if not made:
            parent.mkdir(parents=True, exist_ok=True)
            made.append(Path(tempfile.mkdtemp(prefix=".run-", dir=parent)))
        return made[0]

    try:
        yield get
    finally:
        for directory in made:
            shutil.rmtree(directory)


def _project_sample(
    table: GenotypeTable, pca: ReferencePCA, subset: Path, plink: Plink2, scratch: Path, stem: str
) -> Projection:
    """Harmonize the sample onto the panel's alleles at the PCA's markers, then project it."""
    sites = read_panel_sites(subset.with_suffix(".pvar"), wanted=pca.marker_positions)
    converted = to_pgen(table, sites, plink=plink, workspace=scratch, stem=stem)
    return project(converted.pgen, pca, plink=plink, workspace=scratch, stem=f"{stem}-projection")


_STAGE_ERRORS: Final = (
    AadrError,
    EigenstratError,
    EmptyHarmonizationError,
    OSError,
    PanelError,
    Plink2Error,
    PopulationsError,
    ProjectionError,
    ReferencePcaError,
)
"""What the computation behind a part can raise once its prerequisites are in place. Each
becomes an :class:`AncestryError` naming the part, so the CLI reports one kind of failure."""


# ---------------------------------------------------------------------------
# The parts
# ---------------------------------------------------------------------------


def _population(
    table: GenotypeTable,
    refs: _References,
    plink: _Plink,
    cache: Path,
    scratch_dir: Callable[[], Path],
    report: Callable[[str], None],
) -> PopulationResult:
    panel = refs.verified_output(MODERN_PANEL_SOURCE, MODERN_PANEL_STEP)
    if isinstance(panel, str):
        return PopulationResult(not_run_reason=panel)
    inputs = refs.aadr_inputs()
    if isinstance(inputs, str):
        return PopulationResult(not_run_reason=inputs)
    tool = plink.get()
    if isinstance(tool, str):
        return PopulationResult(not_run_reason=tool)

    try:
        report("ancestry: the reference PCA for this array (built once per chip, then reused)")
        try:
            pca = build_reference_pca(
                table, panel, plink=tool, workspace=cache, reference_panels=(MODERN_PANEL_SOURCE,)
            )
        except InsufficientOverlapError as exc:
            return PopulationResult(
                not_run_reason=f"this export shares too little with the reference panel: {exc}"
            )
        report("ancestry: projecting the reference panel and the sample")
        scratch = scratch_dir()
        model = build_population_model(
            project(panel, pca, plink=tool, workspace=scratch, stem="panel"),
            read_aadr_population_labels(panel.with_suffix(".psam"), inputs[".anno"]),
        )
        sample = _project_sample(table, pca, panel, tool, scratch, "sample")
        placement = place(sample, model)
    except _STAGE_ERRORS as exc:
        raise AncestryError(f"population placement failed: {exc}") from exc
    return PopulationResult(
        placement=placement,
        reference=sample.reference,
        reference_markers=pca.n_markers,
        n_components=pca.n_components,
    )


def _ancient(
    table: GenotypeTable,
    refs: _References,
    plink: _Plink,
    cache: Path,
    scratch_dir: Callable[[], Path],
    report: Callable[[str], None],
) -> AffinityResult:
    subset = refs.verified_output(SHARED_SPACE_SOURCE, SHARED_SPACE_STEP)
    if isinstance(subset, str):
        return AffinityResult(not_run_reason=subset)
    inputs = refs.aadr_inputs()
    if isinstance(inputs, str):
        return AffinityResult(not_run_reason=inputs)
    labels = refs.payload(SHARED_SPACE_SOURCE, _LABELS_SUFFIX)
    if isinstance(labels, str):
        return AffinityResult(not_run_reason=labels)
    tool = plink.get()
    if isinstance(tool, str):
        return AffinityResult(not_run_reason=tool)

    try:
        report("ancestry: the space shared with the ancient archive (built once per chip)")
        try:
            pca = build_reference_pca(
                table,
                subset,
                plink=tool,
                workspace=cache,
                restrict_to=shared_positions(read_snp(inputs[".snp"])),
                space=SHARED_SPACE,
            )
        except InsufficientOverlapError as exc:
            return AffinityResult(
                not_run_reason=f"this export shares too little with the ancient archive: {exc}"
            )
        scratch = scratch_dir()
        modern = build_population_model(
            project(subset, pca, plink=tool, workspace=scratch, stem="shared-panel"),
            read_population_labels(labels),
        )

        report("ancestry: reading and projecting ancient individuals (several minutes)")
        sites = read_snp(inputs[".snp"], wanted=pca.marker_positions)
        listed = read_ind(inputs[".ind"])
        packed = open_packed(
            inputs[".geno"],
            n_individuals=len(listed),
            n_sites=sites.n_read,
            individual_id_hash=hasharr(item.sample_id for item in listed),
            site_id_hash=sites.id_hash,
        )
        ancient = select_ancient_individuals(
            packed, annotate(listed, read_anno(inputs[".anno"])), sites
        )
        vcf = scratch / "ancient.vcf"
        write_ancient_vcf(
            read_panel_sites(subset.with_suffix(".pvar"), wanted=pca.marker_positions),
            ancient,
            vcf,
        )
        try:
            tool.run(["--vcf", str(vcf), "--make-pgen", "--sort-vars"], out=scratch / "ancient")
        finally:
            vcf.unlink(missing_ok=True)
        model = build_ancient_model(
            project(
                scratch / "ancient.pgen",
                pca,
                plink=tool,
                workspace=scratch,
                stem="ancient-projection",
                min_coverage=_ANCIENT_PROJECTION_FLOOR,
            ),
            ancient,
            modern,
        )
        sample = _project_sample(table, pca, subset, tool, scratch, "shared-sample")
        found = affinity(sample, model)
    except _STAGE_ERRORS as exc:
        raise AncestryError(f"ancient affinity failed: {exc}") from exc
    return AffinityResult(affinity=found, reference=sample.reference)


def _lineage(lineage: str, table: GenotypeTable, qc: QCReport, root: Path) -> LineageResult:
    if lineage == "Y" and qc.sex.inferred is InferredSex.FEMALE:
        return LineageResult(
            "Y",
            LineageStatus.NOT_APPLICABLE,
            reason="QC inferred female, so there is no Y chromosome to call a lineage on.",
        )
    if lineage == "MT":
        archive = root / "phylotree_17" / phylotree.ARCHIVE
        if not archive.is_file():
            return LineageResult(
                "MT",
                LineageStatus.NOT_RUN,
                reason="PhyloTree 17 is not fetched. `genetics refs fetch --only phylotree_17`.",
            )
        try:
            tree = phylotree.load_mt_tree(archive)
        except (phylotree.PhyloTreeError, OSError) as exc:
            raise AncestryError(f"the mtDNA tree cannot be read: {exc}") from exc
    else:
        directory = root / ytree.DIRECTORY
        if not (directory / ytree.MARKERS).is_file():
            return LineageResult(
                "Y",
                LineageStatus.NOT_RUN,
                reason=(
                    "The ISOGG Y tree is not fetched. "
                    f"`genetics refs fetch --only {ytree.DIRECTORY}`."
                ),
            )
        try:
            tree = ytree.load_y_tree(directory)
        except (ytree.YTreeError, OSError) as exc:
            raise AncestryError(f"the Y tree cannot be read: {exc}") from exc
    return LineageResult(lineage, LineageStatus.CALLED, call=call_haplogroup(tree, table))


# ---------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------


def infer_ancestry(
    table: GenotypeTable,
    qc: QCReport,
    *,
    references_root: Path | None = None,
    tools_root: Path | None = None,
    workspace: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> AncestryContext:
    """Place the sample, call its haplogroups and rank its ancient affinities.

    Every part is attempted, and each that cannot run says why; nothing here skips a part
    silently. ``table`` must be the ploidy-resolved table :func:`genetics.ingest.ingest`
    returns, and ``qc`` the report beside it -- the Y call reads its inferred sex.

    Raises :class:`AncestryError` for a prerequisite that is present and wrong; see the
    module docstring for where that line is drawn and why.
    """
    root = references_root if references_root is not None else references_dir()
    report = progress if progress is not None else (lambda _message: None)
    refs = _References.load(root)
    plink = _Plink(tools_root)
    cache = workspace if workspace is not None else cache_dir() / "ancestry"
    with _scratch(cache) as scratch_dir:
        population = _population(table, refs, plink, cache, scratch_dir, report)
        ancient = _ancient(table, refs, plink, cache, scratch_dir, report)
    return AncestryContext(
        population=population,
        mt=_lineage("MT", table, qc, root),
        y=_lineage("Y", table, qc, root),
        ancient=ancient,
    )
