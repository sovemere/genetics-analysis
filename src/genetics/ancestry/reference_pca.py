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
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Final

from genetics.external.harmonize import PanelSites, read_panel_sites
from genetics.external.plink2 import Plink2, Plink2ResultInfo
from genetics.ingest.schema import AUTOSOMES, Chrom, GenotypeTable
from genetics.paths import cache_dir
from genetics.privacy import NoGenotypeRepr

__all__ = [
    "ARTIFACT_VERSION",
    "EigenSettings",
    "ReferencePCA",
    "ReferencePcaError",
    "array_marker_positions",
    "build_reference_pca",
]

ARTIFACT_VERSION: Final = 1
"""Bumped when the *shape* of what this writes changes.

Distinct from :attr:`EigenSettings`, which is recorded separately: a settings change and a
format change invalidate a cached artifact for different reasons, and collapsing them into
one number means a reader cannot tell which happened.
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
"""A floor on the intersection, below which the coordinates are not worth computing.

Not a statistical threshold -- there is no clean one -- but a guard against the failure that
actually happens: a build mismatch or a chromosome-naming disagreement between the panel and
the array intersects to almost nothing, and a PCA over two hundred markers still returns
numbers. It returns them with error bars nobody sees.
"""


class ReferencePcaError(RuntimeError):
    """The reference PCA cannot be built, or a cached one cannot be trusted."""


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
    n_components: int
    n_panel_samples: int
    panel_source: str
    """The subset fileset's *name*, never its path (the harmonize.PanelSites rule)."""

    settings: EigenSettings
    reused: bool
    """True when a valid cached artifact was found and nothing was recomputed."""

    plink: Plink2ResultInfo | None
    """``None`` on reuse."""

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
                "`genetics refs fetch --only thousand_genomes_phase3_grch37`."
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
    n_panel_samples: int,
) -> dict[str, Any]:
    return {
        "artifact": "reference_pca",
        "artifact_version": ARTIFACT_VERSION,
        "panel_pvar_sha256": panel_digest,
        "array_markers_sha256": array_digest,
        "settings": settings.as_dict(),
        "n_markers": n_markers,
        "n_panel_samples": n_panel_samples,
        # Recorded even though the panel set is currently fixed, because widening it later
        # produces a different artifact and without this field it would look current. The
        # same failure the r2 setting fix prevents for the marker subset.
        "reference_panels": ["thousand_genomes_phase3_grch37"],
    }


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


def build_reference_pca(
    table: GenotypeTable,
    subset_pgen: Path,
    *,
    plink: Plink2,
    settings: EigenSettings | None = None,
    workspace: Path | None = None,
    chroms: Sequence[Chrom] = AUTOSOMES,
) -> ReferencePCA:
    """Compute (or reuse) the reference PCA over the markers ``table``'s array carries.

    ``subset_pgen`` is the ``.pgen`` of M5.3's LD-pruned marker subset; its ``.pvar`` and
    ``.psam`` must sit beside it. The result is cached under ``cache_dir()`` keyed by the
    panel, the array's marker set and the settings together, so re-running for the same chip
    is free and re-running for a different one does not overwrite it.
    """
    settings = settings or EigenSettings()
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
        raise ReferencePcaError(
            "the export carries no autosomal markers, so there is nothing to intersect "
            "the reference panel with."
        )

    sites = read_panel_sites(pvar, chroms=chroms, wanted=positions)
    if sites.n_sites < _MIN_MARKERS:
        raise ReferencePcaError(
            f"only {sites.n_sites:,} of the panel's markers are carried by this array "
            f"(minimum {_MIN_MARKERS:,}). That is usually a build or chromosome-naming "
            "disagreement between the export and the panel rather than a sparse chip: the "
            f"export offered {len(positions):,} autosomal positions and the panel read "
            f"{sites.n_read:,} sites on those chromosomes."
        )
    _check_ids(sites)

    expected = _expected_provenance(
        panel_digest=_file_digest(pvar),
        array_digest=_positions_digest(positions),
        settings=settings,
        n_markers=sites.n_sites,
        n_panel_samples=n_panel_samples,
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
            settings=settings,
            reused=True,
            plink=None,
        )

    prefix.parent.mkdir(parents=True, exist_ok=True)
    ranges = prefix.with_name(prefix.name + ".extract.bed")
    _write_extract_ranges(ranges, sites)

    result = plink.run(
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
    ranges.unlink(missing_ok=True)

    return ReferencePCA(
        allele_weights=files["eigenvec_allele"],
        frequencies=files["afreq"],
        eigenvalues=files["eigenval"],
        n_markers=sites.n_sites,
        n_components=settings.n_components,
        n_panel_samples=n_panel_samples,
        panel_source=sites.source,
        settings=settings,
        reused=False,
        plink=result,
    )
