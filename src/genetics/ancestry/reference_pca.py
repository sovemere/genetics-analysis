"""The reference PCA, computed on the markers the array actually carries (roadmap M5.3).

:func:`genetics.refs.postprocess.build_pca_marker_subset` produced the panel side of this:
common, autosomal, biallelic ACGT SNPs outside the long-range LD regions, LD-pruned, merged
across the twenty-two autosomes. That artifact is a function of public 1000 Genomes data
alone, which is why it may live under ``data/references/``. This module is the other half,
and it is where the array enters.

**Why the array intersection is here and not there.** M5.3's registry entry carries the
argument in full; the short of it is that a marker subset cut to one person's chip is wrong
for the next person's, and an artifact stops being a function of public data the moment an
export chooses its contents. So the panel is pruned once, publicly, and *this* step -- run
when an export is genuinely in hand -- narrows it to the markers that export carries. The
output therefore lands in ``cache_dir()`` and is keyed by the chip's marker set, so two
people with different arrays get different artifacts and neither silently reads the
other's.

**The intersection is not re-pruned, and that is a deviation from the roadmap's wording.**
M5.3's note says the eigenvector build can "intersect this subset with the array and prune
again". Intersecting cannot create linkage: LD pruning guarantees that no two *retained*
markers exceed the r^2 threshold, and any subset of a set with that property still has it.
A second pass would cost a pass over the panel to remove markers it has no reason to
remove. What the intersection *can* do is thin the panel unevenly -- which is a coverage
fact about the chip, reported in :attr:`ReferencePCA.n_markers`, not something a second
pruning would fix.

**``--pca`` and ``--freq`` run in one invocation, and that is a correctness requirement
rather than a saved subprocess.** M5.4 projects a single sample with ``--score``, and PLINK
refuses to impute allele frequencies from fewer than fifty samples -- measured during the
M5.3 trial run, where the error names allele frequencies and says nothing that sounds like
a missing artifact. So the projection must pass ``--read-freq`` against the reference's own
``.afreq``, which means this step has to emit one. Emitting it from the same invocation that
computes the eigenvectors is what guarantees the two describe the same markers over the same
samples; two invocations would leave a flag drifting between them able to produce weights
and frequencies that disagree, and nothing downstream would notice.

**Markers are selected by position, not by variant ID.** ``--extract bed1`` takes ranges, so
the intersection does not depend on the panel having usable IDs -- and it is the same
mechanism the subset step already uses for ``--exclude bed1``. IDs are still *checked*,
because M5.4's ``--score`` joins on them: a panel whose IDs are absent or duplicated
produces a projection that is silently wrong rather than one that fails, so it is refused
here where the message can say so.

**The intersection is narrowed again, to the sites a sample could actually supply, and
that is the M5.4 finding turned into code.** M5.2 drops strand-ambiguous A/T and C/G sites
whole, because with one sample nothing can decide which strand the letters were read on.
Those sites are about a sixth of common SNPs, so an eigenvector build that kept them
carried loadings no export could ever score: the first real-panel run projected at **83.6%
coverage** with 8,199 sites reported ``ambiguous_site``, and every sample on this chip would
have come back at the same 83.6% whatever its call rate. A confidence model reading that as
call quality under-rates everyone by an identical, meaningless margin.

So the same panel-only predicate the harmonizer applies -- :func:`~genetics.external.
harmonize.panel_exclusion`, imported rather than restated -- runs here too, and the
markers with loadings are the markers a sample can bring. ``coverage`` then measures the
sample again. The alternative considered and rejected was to leave the build alone and
grade coverage against a second, smaller denominator: that keeps a number in the artifact
that no consumer of the artifact should use, and the first person to divide by
``n_markers`` gets the wrong answer with nothing to warn them.

**Only panel-only reasons are applied.** Whether a site is ambiguous or is a well-formed
biallelic SNP is a fact about the reference's alleles, identical for every export, so it can
narrow a reference artifact without keying it to a person. A no-call, a duplicate probe
conflict or an allele mismatch is a fact about one sample or one chip's probe set, and
excluding on those would make the eigenvectors themselves depend on who ran the pipeline.
Those stay in the projection's coverage, where they belong.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Final

from genetics.external.harmonize import (
    PanelSites,
    SiteOutcome,
    harmonizable_sites,
    read_panel_sites,
)
from genetics.external.plink2 import Plink2, Plink2ResultInfo
from genetics.ingest.schema import AUTOSOMES, Chrom, GenotypeTable
from genetics.paths import cache_dir
from genetics.privacy import NoGenotypeRepr

__all__ = [
    "ARTIFACT_VERSION",
    "EigenSettings",
    "InsufficientOverlapError",
    "ReferencePCA",
    "ReferencePcaError",
    "array_marker_positions",
    "build_reference_pca",
]

ARTIFACT_VERSION: Final = 2
"""Bumped when the *shape* of what this writes changes.

Distinct from :attr:`EigenSettings`, which is recorded separately: a settings change and a
format change invalidate a cached artifact for different reasons, and collapsing them into
one number means a reader cannot tell which happened.

**2 (M5.5): strand-ambiguous and non-SNP sites are excluded from the build.** The file
layout is unchanged, so this is the looser sense of "shape" -- but ``n_markers`` now means
"markers a sample can score" rather than "markers in the intersection", and
:attr:`~genetics.ancestry.projection.Projection.coverage` divides by it. A version 1
artifact reused under version 2 semantics would report a coverage near 84% and call it a
property of the sample. The marker count moves too, so the cache key would separate them
anyway; this states the reason rather than relying on a side effect to enforce it.
"""

_MIN_PANEL_SAMPLES: Final = 50
"""Below this PLINK will not do the statistics this step needs.

Measured, not assumed, during the M5.3 trial: ``--indep-pairwise`` refuses a panel with
fewer than fifty samples outright, and ``--score`` refuses to impute allele frequencies from
fewer. 1000 Genomes phase 3 has 2,504, so this is a tripwire for a truncated or
mis-subsetted panel rather than a limit anyone meets in normal use -- and it is checked here
because the alternative is a PLINK error three steps later that names neither the panel nor
the reason.
"""

_MIN_MARKERS: Final = 1_000
"""A floor on the *usable* intersection, below which the coordinates are not worth computing.

Not a statistical threshold -- there is no clean one -- but a guard against the failure that
actually happens: a build mismatch or a chromosome-naming disagreement between the panel and
the array intersects to almost nothing, and a PCA over two hundred markers still returns
numbers. It returns them with error bars nobody sees.

Counted after the ambiguity exclusion rather than before, because the excluded markers are
exactly the ones that cannot reach ``--score``. Checking the wider count would let a build
that intersects at 1,100 markers and can score 900 of them through.
"""


class ReferencePcaError(RuntimeError):
    """The reference PCA cannot be built, or a cached one cannot be trusted."""


class InsufficientOverlapError(ReferencePcaError):
    """The export and the panel share too few usable markers to build a space from.

    A subclass rather than a message, because M5.8 has to tell this refusal from the others
    this module makes. The rest describe a broken artifact or a failed tool -- things that
    are wrong with the installation and would be wrong for every run. This one describes the
    export: a synthetic fixture whose coordinates are invented, or a chip that carries too
    little of the panel. A run records that as ancestry not inferred, with this message as
    the reason, instead of failing outright over a fact about one file.
    """


@dataclass(frozen=True)
class EigenSettings:
    """What the eigenvector build was asked for, recorded rather than assumed.

    In the provenance sidecar for the same reason M5.3's filter settings are: a changed
    default would otherwise leave every existing artifact looking current, and this is one
    somebody waits on.
    """

    n_components: int = 10
    """How many principal components to retain.

    Ten rather than the four the M5.3 trial used. Four is enough to separate continents and
    that is where the trial stopped; M5.5 wants to place a sample *within* a continent, and
    the axes that do that are the later ones. Retaining more than are used costs a column
    each in one file.
    """

    def __post_init__(self) -> None:
        if self.n_components < 1:
            raise ReferencePcaError(f"n_components must be at least 1, got {self.n_components}")
        if self.n_components > 100:
            raise ReferencePcaError(
                f"n_components must be at most 100, got {self.n_components}; beyond the first "
                "few dozen the components describe the panel's sampling rather than ancestry."
            )

    def as_dict(self) -> dict[str, Any]:
        return {"n_components": self.n_components}


@dataclass(frozen=True)
class ReferencePCA(NoGenotypeRepr):
    """A built (or reused) reference PCA, and the files M5.4 scores against.

    Carries no genotypes -- allele weights and frequencies are properties of the panel --
    but inherits the safe ``__repr__`` because this is the object a caller logs, and the
    paths under ``cache_dir()`` contain the user's account name on Windows.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_markers", "n_components", "n_panel_samples")

    allele_weights: Path
    """``.eigenvec.allele`` -- per-variant, per-allele loadings. M5.4's ``--score`` input."""

    frequencies: Path
    """``.afreq`` -- what M5.4 must pass to ``--read-freq``. Without it PLINK refuses to
    project a single sample."""

    eigenvalues: Path
    """``.eigenval`` -- variance explained, which M5.5 needs to say how much of the
    structure the plotted axes actually carry."""

    n_markers: int
    """Markers the loadings cover -- the intersection *after* the panel-only exclusions.

    The denominator :attr:`~genetics.ancestry.projection.Projection.coverage` divides by,
    and it is a count of markers a harmonized sample can actually bring. See
    :data:`ARTIFACT_VERSION` for why that distinction earned a version bump.
    """

    n_components: int
    n_panel_samples: int
    panel_source: str
    """The subset fileset's *name*, never its path (the harmonize.PanelSites rule)."""

    n_intersected: int
    """Markers on both the array and the panel, before the exclusions below.

    Kept because ``n_intersected - n_markers`` is a fact about the *chip and panel* worth
    reporting -- how much of the overlap is unreadable by construction -- and because a
    reader comparing this artifact against M5.2's report needs both numbers to reconcile
    them.
    """

    marker_positions: tuple[tuple[str, int], ...]
    """The ``(chrom, pos)`` pairs the loadings cover, sorted.

    Carried because a consumer that has to line another source up against *these* markers
    otherwise has to re-derive them, and re-deriving them is where M5.6 first went wrong:
    the ancient coverage floor was applied over the AADR-and-array overlap (129,840
    positions) rather than over the markers this artifact actually holds (11,128), so
    individuals passed the floor and then projected below it. Computed on both the fresh and
    the reused path, because the intersection is read before the cache is consulted.
    """

    excluded_sites: Mapping[SiteOutcome, int]
    """Why the difference: strand-ambiguous sites, and panel records that are not SNPs.

    Only the outcomes :func:`~genetics.external.harmonize.panel_exclusion` can return ever
    appear here. Zeros are omitted, matching
    :attr:`~genetics.external.harmonize.HarmonizationReport.counts`.
    """

    space: str
    """Which marker space this artifact is over -- ``"array"`` for the full chip
    intersection, or a name M5.6 gives the narrower one it shares with AADR."""

    settings: EigenSettings
    reused: bool
    """True when a valid cached artifact was found and nothing was recomputed."""

    plink: Plink2ResultInfo | None
    """``None`` on reuse."""

    @property
    def n_excluded(self) -> int:
        """Intersected markers no sample could have scored. ``n_intersected - n_markers``."""
        return sum(self.excluded_sites.values())

    @property
    def prefix(self) -> Path:
        return self.allele_weights.with_suffix("").with_suffix("")


def array_marker_positions(table: GenotypeTable) -> list[tuple[str, int]]:
    """The autosomal positions this export actually carries, sorted and deduplicated.

    No-call rows are kept. Whether a marker was *read* successfully is a fact about this
    sample; whether the chip carries it at all is a fact about the chip, and it is the
    second one that decides which markers the reference PCA is computed on. Dropping
    no-calls here would make the eigenvector artifact depend on one person's call rate, so
    two people with the same chip would no longer share it -- and the artifact would encode
    something about the individual rather than about the hardware.
    """
    frame = table.filter_chrom(*AUTOSOMES)
    rows = frame.select("chrom", "pos_grch37").unique().sort("chrom", "pos_grch37").iter_rows()
    return [(str(chrom), int(pos)) for chrom, pos in rows]


def _positions_digest(positions: Sequence[tuple[str, int]]) -> str:
    """A digest over the marker *set*, which is what the artifact is keyed by.

    Fed the sorted, deduplicated pairs so that two exports carrying the same markers in a
    different file order share a cache entry -- the point of keying on the chip rather than
    on the file.
    """
    digest = hashlib.sha256()
    for chrom, pos in positions:
        digest.update(f"{chrom}:{pos}\n".encode())
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _subset_paths(subset_pgen: Path) -> tuple[Path, Path, Path]:
    """The pgen trio, or a clear error naming the one that is missing."""
    pvar = subset_pgen.with_suffix(".pvar")
    psam = subset_pgen.with_suffix(".psam")
    for path in (subset_pgen, pvar, psam):
        if not path.is_file():
            raise ReferencePcaError(
                f"the PCA marker subset is incomplete: {path.name} is missing. Build it with "
                "`genetics refs fetch --only thousand_genomes_phase3_grch37` for the 1000 "
                "Genomes subset, or `--only aadr` for the Human Origins modern panel."
            )
    return subset_pgen, pvar, psam


def _count_panel_samples(psam: Path) -> int:
    """Sample rows in a ``.psam``. Header lines start with ``#``."""
    count = 0
    with psam.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip() and not line.startswith("#"):
                count += 1
    return count


def _check_ids(sites: PanelSites) -> None:
    """Refuse a panel whose variant IDs cannot carry M5.4's join.

    ``--score`` matches the sample's variants to the reference's allele weights by ID. A
    missing ID (``.``) or a duplicated one does not make ``--score`` fail; it makes it match
    the wrong row or none, and a projection built on that is wrong in a way that still plots.
    Checked here, over the intersection only, because a duplicate at a marker this chip does
    not carry is not a fact about this run.
    """
    ids = sites.frame.get_column("panel_id")
    missing = int((ids.is_null() | ids.is_in(["", "."])).sum())
    if missing:
        raise ReferencePcaError(
            f"{missing:,} of {sites.n_sites:,} markers in the intersection have no variant ID. "
            "M5.4 joins the sample to the reference weights by ID, so these would be dropped "
            "or mismatched silently. Rebuild the marker subset with IDs set."
        )
    n_unique = int(ids.n_unique())
    if n_unique != sites.n_sites:
        raise ReferencePcaError(
            f"{sites.n_sites - n_unique:,} duplicated variant ID(s) in the intersection. "
            "`--score` would match a sample's call against whichever row came first."
        )


def _provenance_path(prefix: Path) -> Path:
    return prefix.with_name(prefix.name + ".provenance.json")


def _expected_provenance(
    *,
    panel_digest: str,
    array_digest: str,
    settings: EigenSettings,
    n_markers: int,
    n_intersected: int,
    excluded: Mapping[SiteOutcome, int],
    n_panel_samples: int,
    space: str,
    reference_panels: Sequence[str],
) -> dict[str, Any]:
    return {
        "artifact": "reference_pca",
        "artifact_version": ARTIFACT_VERSION,
        # In the key as well as the record. Two spaces over the same chip differ in their
        # marker digest already, so this adds no separation -- what it adds is that a
        # sidecar says which of them a directory holds.
        "space": space,
        "panel_pvar_sha256": panel_digest,
        "array_markers_sha256": array_digest,
        "settings": settings.as_dict(),
        "n_markers": n_markers,
        # Both recorded, and both compared: they are determined by the two digests above,
        # so they add no entropy to the key -- what they add is that a cached artifact
        # built when the exclusion rule said something else stops matching instead of
        # being reused under the new rule's reading of `n_markers`.
        "n_intersected": n_intersected,
        "excluded_sites": {outcome.value: count for outcome, count in sorted(excluded.items())},
        "n_panel_samples": n_panel_samples,
        # **This field is what M5.9 needed and the reason it was written down early.** It
        # was recorded when the panel set was fixed, on the grounds that widening it later
        # produces a different artifact that would otherwise look current. Widening it
        # later is exactly what happened, and because this was in the cache key a
        # 1000 Genomes artifact and a Human Origins one over the same chip cannot be
        # confused for one another -- their marker counts differ too, but a count is a
        # coincidence and a name is a statement.
        "reference_panels": list(reference_panels),
    }


def _reference_panel_names(reference_panels: Sequence[str]) -> tuple[str, ...]:
    """Validate and freeze the panel identities that enter provenance and the cache key.

    A bare string is itself a sequence, so without the explicit check ``"aadr"`` becomes
    four panel names. Empty and repeated names are no better: both let a sidecar appear to
    describe its inputs without identifying one distinct source per entry.
    """
    if isinstance(reference_panels, (str, bytes)):
        raise ReferencePcaError(
            "reference_panels must be a sequence of panel names, not one bare string"
        )
    names = tuple(reference_panels)
    if not names:
        raise ReferencePcaError(
            "reference_panels names no source. A pgen path is a location, not provenance, "
            "so the reference PCA must record which panel produced it."
        )
    malformed = [
        name for name in names if not isinstance(name, str) or name != name.strip() or not name
    ]
    if malformed:
        raise ReferencePcaError(
            f"reference_panels contains blank or padded names: {malformed!r}. Panel "
            "identities are recorded exactly and must be non-empty."
        )
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ReferencePcaError(
            f"reference_panels repeats {', '.join(repeated)}. Each source must be named "
            "once so equivalent builds have one cache identity."
        )
    return names


def _marker_positions(sites: PanelSites) -> tuple[tuple[str, int], ...]:
    """The surviving intersection as ``(chrom, pos)`` pairs, sorted.

    Sorted here rather than left in the panel's file order, because the field promises it
    and a consumer lining another source up against these markers is exactly who would
    bisect or merge on that promise. 1000 Genomes phase 3 ships a position-ordered ``.pvar``,
    so today the two agree by luck -- which is the kind of agreement that holds until the
    panel widens. ``chrom`` is a :class:`polars.Enum` over
    :data:`~genetics.ingest.schema.CHROM_ORDER`, so this sorts 1..22 rather than
    lexicographically putting chromosome 10 before chromosome 2.
    """
    frame = sites.frame.select("chrom", "pos").sort("chrom", "pos")
    return tuple((str(chrom), int(pos)) for chrom, pos in frame.iter_rows())


def _read_excluded(recorded: Mapping[str, Any]) -> dict[SiteOutcome, int]:
    """The exclusion counts back out of a sidecar, as the enum the fresh path returns.

    A cached result whose ``excluded_sites`` came back as bare strings would be the same
    dataclass field holding two different key types depending on whether PLINK had run,
    which is the kind of difference a caller only discovers in production.
    """
    raw = recorded.get("excluded_sites")
    if not isinstance(raw, dict):
        return {}
    return {SiteOutcome(name): int(count) for name, count in raw.items()}


def _outputs(prefix: Path) -> dict[str, Path]:
    """Every file this artifact consists of.

    All three are hashed into the sidecar. A ``.eigenvec.allele`` left beside an ``.afreq``
    computed over different markers projects every sample slightly wrong while both files
    look present and parse cleanly -- the same reasoning that made the marker subset's
    sidecar cover all three of its pgen files rather than only the ``.pgen``.
    """
    return {
        "eigenvec_allele": prefix.with_name(prefix.name + ".eigenvec.allele"),
        "afreq": prefix.with_name(prefix.name + ".afreq"),
        "eigenval": prefix.with_name(prefix.name + ".eigenval"),
    }


def _read_provenance(prefix: Path) -> dict[str, Any] | None:
    path = _provenance_path(prefix)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _cached(prefix: Path, expected: dict[str, Any]) -> dict[str, Any] | None:
    """A cached artifact that still matches, or None. Never raises on a stale one.

    A cache miss is not an error: the caller rebuilds. Failing instead would mean a changed
    default, or a widened panel, turned into a crash rather than into work.
    """
    recorded = _read_provenance(prefix)
    if recorded is None:
        return None
    if any(recorded.get(key) != value for key, value in expected.items()):
        return None
    digests = recorded.get("outputs")
    if not isinstance(digests, dict):
        return None
    for name, path in _outputs(prefix).items():
        if not path.is_file() or digests.get(name) != _file_digest(path):
            return None
    return recorded


def _write_extract_ranges(path: Path, sites: PanelSites) -> None:
    """The intersection as a ``--extract bed1`` range file: 1-based, fully closed.

    One line per marker rather than merged intervals. Merging would be smaller and would
    also silently include any panel marker falling between two array markers, which is the
    opposite of what this step is for.
    """
    frame = sites.frame.select("chrom", "pos")
    lines = [f"{chrom}\t{pos}\t{pos}" for chrom, pos in frame.iter_rows()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _run_pca(
    plink: Plink2, pgen: Path, ranges: Path, prefix: Path, settings: EigenSettings
) -> Plink2ResultInfo:
    """The single invocation. Split out so the range file can be cleaned up around it."""
    return plink.run(
        [
            "--pfile",
            str(pgen.with_suffix("")),
            "--extract",
            "bed1",
            str(ranges),
            # One invocation, deliberately: see the module docstring. The weights and the
            # frequencies M5.4 pairs them with are computed over the same markers and the
            # same samples because there is only one pass in which they could differ.
            "--pca",
            str(settings.n_components),
            "allele-wts",
            "--freq",
        ],
        out=prefix,
    )


def build_reference_pca(
    table: GenotypeTable,
    subset_pgen: Path,
    *,
    plink: Plink2,
    settings: EigenSettings | None = None,
    workspace: Path | None = None,
    chroms: Sequence[Chrom] = AUTOSOMES,
    restrict_to: Iterable[tuple[str, int]] | None = None,
    space: str = "array",
    reference_panels: Sequence[str] = ("thousand_genomes_phase3_grch37",),
) -> ReferencePCA:
    """Compute (or reuse) the reference PCA over the markers ``table``'s array carries.

    ``subset_pgen`` is the ``.pgen`` of M5.3's LD-pruned marker subset; its ``.pvar`` and
    ``.psam`` must sit beside it. The result is cached under ``cache_dir()`` keyed by the
    panel, the array's marker set and the settings together, so re-running for the same chip
    is free and re-running for a different one does not overwrite it.

    ``restrict_to`` narrows the array's positions further, and exists for
    [M5.6](../../phase1_roadmap.md). Affinity to ancient populations needs the sample, the
    modern panel and the ancient individuals in **one** space, and the AADR Human Origins
    array shares only 11,128 of this chip's 52,411 reference markers -- an Affymetrix design
    against an Illumina one. Projecting ancients onto axes computed from markers most of
    them lack would compare coordinates resting on systematically different marker subsets,
    which the ``_AVG`` normalisation does not fix because the overlap is not a random draw.
    So M5.6 builds a second, smaller space on what all three carry.

    ``space`` names the resulting space in the provenance sidecar. It is not decoration:
    two artifacts over the same chip differing only in restriction would otherwise be
    distinguishable in the cache (their marker counts differ) but indistinguishable to
    somebody reading the sidecar to find out what they are looking at.

    ``reference_panels`` names the source (or sources) ``subset_pgen`` was built from, and
    it goes into the cache key. The default is the 1000 Genomes subset M5.3 built; callers
    using [M5.9](../../phase1_roadmap.md)'s widened Human Origins artifact pass ``("aadr",)``.
    This is not derivable from ``subset_pgen`` -- a path is a location, not a provenance --
    and it is what stops two panels over the same chip from sharing a cache entry on the
    strength of having intersected to the same number of markers.
    """
    settings = settings or EigenSettings()
    reference_panels = _reference_panel_names(reference_panels)
    pgen, pvar, psam = _subset_paths(subset_pgen)

    n_panel_samples = _count_panel_samples(psam)
    if n_panel_samples < _MIN_PANEL_SAMPLES:
        raise ReferencePcaError(
            f"the marker subset holds {n_panel_samples} sample(s); PLINK needs at least "
            f"{_MIN_PANEL_SAMPLES} to compute the allele frequencies this step emits and "
            "M5.4 reads back. A panel this small is a truncated build, not a small cohort."
        )

    positions = array_marker_positions(table)
    if not positions:
        raise InsufficientOverlapError(
            "the export carries no autosomal markers, so there is nothing to intersect "
            "the reference panel with."
        )
    n_array_positions = len(positions)
    if restrict_to is not None:
        allowed = frozenset(restrict_to)
        positions = [position for position in positions if position in allowed]
        if not positions:
            raise InsufficientOverlapError(
                f"the {space!r} restriction and this array share no autosomal position. The "
                f"export offered {n_array_positions:,} and the restriction named "
                f"{len(allowed):,}; a disjoint pair is usually a build or chromosome-naming "
                "disagreement rather than two genuinely unrelated marker sets."
            )

    # Only when a restriction was actually applied. Unconditionally, a default-mode failure
    # reads "the export offered 1,100 autosomal positions (1,100 after the 'array'
    # restriction)" -- naming a restriction nobody passed, with two identical numbers as
    # apparent evidence of it, and `array` is the name of the *unrestricted* space.
    narrowed = (
        f" ({len(positions):,} after the {space!r} restriction)" if restrict_to is not None else ""
    )

    intersected = read_panel_sites(pvar, chroms=chroms, wanted=positions)
    # The ambiguity exclusion runs before the floor and before the ID check, because both
    # ask about the markers that will carry a loading and neither should be answered about
    # markers that are on their way out. See the module docstring.
    sites, excluded = harmonizable_sites(intersected)
    if sites.n_sites < _MIN_MARKERS:
        raise InsufficientOverlapError(
            f"only {sites.n_sites:,} of the panel's markers are carried by this array and "
            f"usable (minimum {_MIN_MARKERS:,}). That is usually a build or "
            "chromosome-naming disagreement between the export and the panel rather than a "
            f"sparse chip: the export offered {n_array_positions:,} autosomal "
            f"positions{narrowed}, the "
            f"panel read {intersected.n_read:,} sites on those chromosomes, "
            f"{intersected.n_sites:,} of them intersected, and {sum(excluded.values()):,} "
            "of those were strand-ambiguous or not biallelic SNPs."
        )
    _check_ids(sites)

    expected = _expected_provenance(
        panel_digest=_file_digest(pvar),
        array_digest=_positions_digest(positions),
        settings=settings,
        n_markers=sites.n_sites,
        n_intersected=intersected.n_sites,
        excluded=excluded,
        n_panel_samples=n_panel_samples,
        space=space,
        reference_panels=reference_panels,
    )

    root = workspace if workspace is not None else cache_dir() / "ancestry"
    key = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    prefix = root / f"refpca-{key[:16]}"

    recorded = _cached(prefix, expected)
    if recorded is not None:
        files = _outputs(prefix)
        return ReferencePCA(
            allele_weights=files["eigenvec_allele"],
            frequencies=files["afreq"],
            eigenvalues=files["eigenval"],
            n_markers=int(recorded["n_markers"]),
            n_components=settings.n_components,
            n_panel_samples=int(recorded["n_panel_samples"]),
            panel_source=sites.source,
            n_intersected=int(recorded["n_intersected"]),
            marker_positions=_marker_positions(sites),
            excluded_sites=_read_excluded(recorded),
            space=space,
            settings=settings,
            reused=True,
            plink=None,
        )

    prefix.parent.mkdir(parents=True, exist_ok=True)
    ranges = prefix.with_name(prefix.name + ".extract.bed")
    _write_extract_ranges(ranges, sites)

    try:
        result = _run_pca(plink, pgen, ranges, prefix, settings)
    finally:
        # Removed even when PLINK failed. It is a line per marker and a failed run is
        # exactly the situation where scratch gets left behind and forgotten -- the same
        # reasoning `to_pgen` applies to its harmonized VCF, one directory over.
        ranges.unlink(missing_ok=True)

    files = _outputs(prefix)
    for name, path in files.items():
        if not path.is_file():
            raise ReferencePcaError(
                f"PLINK 2 reported success but wrote no {path.name} ({name}). "
                f"Its log is at {result.log_path.name}."
            )

    payload = {**expected, "outputs": {name: _file_digest(p) for name, p in files.items()}}
    _provenance_path(prefix).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    return ReferencePCA(
        allele_weights=files["eigenvec_allele"],
        frequencies=files["afreq"],
        eigenvalues=files["eigenval"],
        n_markers=sites.n_sites,
        n_components=settings.n_components,
        n_panel_samples=n_panel_samples,
        panel_source=sites.source,
        n_intersected=intersected.n_sites,
        marker_positions=_marker_positions(sites),
        excluded_sites=excluded,
        space=space,
        settings=settings,
        reused=False,
        plink=result,
    )
