"""Affinity to ancient populations, and why that word is not a hedge (roadmap M5.6).

:mod:`genetics.ancestry.populations` places a sample among *living* reference populations
and will refuse to name one. This module does something related and weaker: it reports how
close the sample sits to the centre of each ancient group in the Allen Ancient DNA Resource.
The milestone requires that be labelled **affinity, not descent**, and the four measurements
below are why that is a statement about the data rather than a disclaimer.

**1. The ancient genotypes are pseudo-haploid.** Of the 13,832 ancient individuals
``v66.p1_HO`` offers at the prefilter, **13,757 carry no heterozygous call at all** (99.5%);
of the 9,700 that clear the coverage floor and are actually used, 99.2% do. Capture data is
published as one randomly drawn read per site, doubled.

A pseudo-haploid individual is an unbiased but noisy draw around where a diploid one would
sit, carrying roughly twice the per-site variance. So an ancient *group centroid* is
meaningful and an ancient *individual*'s position is not, which is why nothing here reports a
per-individual match.

**2. There is no ancestry model in here, and the failure that would need one is measured
rather than argued.** Distance to a Bronze Age Hungarian centroid is not a fraction of
Bronze Age Hungarian ancestry, and the two are not monotonically related: a sample formed by
mixing two distant sources lands *between* them, near groups it descends from not at all.

Ten samples from each of fifteen 1000 Genomes populations were run through this module in
the shared space. For unadmixed populations the nearest group is geographically right, often
strikingly so::

    GBR -> Denmark_Viking, Germany, FaroeIslands       d=1.53
    TSI -> Italy, Spain_LatePunic, Hungary             d=1.83
    CHB -> China_Weifang_XinZhi_Zhou (10/10)           d=2.36
    JPT -> RepublicofKorea_ThreeKingdoms (10/10)       d=4.30
    CDX -> Taiwan_IA (9/10)                            d=3.41
    LWK -> Cameroon_ShumLaka_SMA (10/10)               d=6.84
    STU -> Pakistan_Historic (10/10)                   d=5.56

And for the recently admixed ones it is wrong in exactly the way the paragraph above
predicts -- **MXL, roughly half European and half Indigenous American, comes back nearest to
medieval Germany and Avar-period Hungary**, groups it descends from not at all, because the
midpoint of its two sources lands there::

    PEL -> USA_California_800BP (5/10)                 d=7.17
    MXL -> Hungary, USA, Germany_Medieval              d=7.52
    PUR -> Hungary_MiddleLateAvar, Germany             d=4.99

That is not a bug to fix here; it is what a nearest-centroid report *is*. Estimating actual
ancestry proportions needs f-statistics or qpAdm over outgroups this module does not fetch,
and inventing one from distances is the fabrication [AGENTS.md 6](../../AGENTS.md) forbids.
What is reported is a distance, in units, ranked -- and :attr:`AncientAffinity.spread` is
there so a card can say whether the ranking separates anything at all.

**3. The space is smaller than M5.5's and has to be its own.** AADR Human Origins is an
Affymetrix design and the export is Illumina; they share **11,128** of the 52,411 markers
M5.3's reference PCA covers. Projecting ancients onto axes computed from markers most of
them lack would put ancient and modern coordinates on systematically different marker
subsets -- and the overlap is not a random draw of the whole, so the ``_AVG`` normalisation
does not rescue it. This module therefore builds a **second** reference PCA over what the
array, the 1000 Genomes panel and AADR all carry, and projects the sample, the modern panel
and the ancient individuals through that one space. It is also what ancient-DNA practice
does for an unrelated and equally good reason: axes are computed from modern diploid samples
and ancients are *projected*, never allowed to define the axes they are placed on.

Because it is a different space, its coordinates are not comparable with M5.5's, and
:attr:`~genetics.ancestry.projection.Projection.reference` is what stops them being
compared: an :class:`AncientAffinity` from here cannot be handed to
:func:`~genetics.ancestry.populations.place`.

**4. Distances are scaled by the modern panel, not by the ancient one.** The metric comes
from :class:`~genetics.ancestry.populations.PopulationModel` built on 1000 Genomes in this
same space -- pooled within-population spread per component, from diploid samples with
essentially complete data. Deriving the scale from the ancient individuals instead would let
their pseudo-haploid noise and their missingness set the ruler, and the ruler would then
shrink every axis on which ancient data is noisiest, which is the opposite of what it should
do.

**Groups below :data:`MIN_GROUP_INDIVIDUALS` are dropped and counted.** AADR's group labels
are archaeological contexts, and their median size in this release is **two individuals**:
of 2,311 groups with a well-covered member, 442 reach five and 92 reach twenty. A centroid
of two pseudo-haploid individuals is a point with error bars wider than the distances being
reported, and a ranked list is exactly the presentation that hides that. So the floor is
real and what it costs is reported alongside what it keeps.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

import polars as pl

from genetics.ancestry.eigenstrat import (
    CODE_MISSING,
    AadrIndividual,
    EigenstratSites,
    PackedGenotypes,
    read_individuals,
)
from genetics.ancestry.populations import PopulationModel
from genetics.ancestry.projection import Projection
from genetics.engine.matcher import complement
from genetics.external.harmonize import PanelSites, is_snp_site, orient
from genetics.privacy import NoGenotypeRepr

__all__ = [
    "MIN_GROUP_INDIVIDUALS",
    "MIN_SHARED_COVERAGE",
    "AadrError",
    "AncientAffinity",
    "AncientGroup",
    "AncientModel",
    "AncientPanel",
    "GroupAffinity",
    "affinity",
    "build_ancient_model",
    "select_ancient_individuals",
    "shared_positions",
    "write_ancient_vcf",
]


MIN_SHARED_COVERAGE: Final = 0.5
"""Fraction of the shared markers an ancient individual must call to be used at all.

Measured on ``v66.p1_HO`` over the 11,128 markers this project shares with it: the median
ancient individual calls 7,444 of them, the lower quartile 4,985. A floor of one half keeps
**9,700 of 13,832** and removes the long tail whose coordinates are dominated by which few
hundred markers happened to survive rather than by ancestry.

Not a statistical threshold. A pseudo-haploid individual with 2,000 markers still projects,
and it projects to somewhere -- that is the failure this exists to prevent, and it is the
same shape as the coverage floor in :mod:`genetics.ancestry.projection`.
"""

MIN_GROUP_INDIVIDUALS: Final = 5
"""Individuals a group needs before it gets a centroid.

Five rather than twenty, and the difference from
:data:`~genetics.ancestry.populations.MIN_POPULATION_SAMPLES` is deliberate. That floor
guards a *radius* -- a spread estimated from members, used to decide whether to name a
population. Nothing here estimates a spread or names anything: a group needs only to place
its centre, and averaging five pseudo-haploid individuals already halves the per-individual
noise. Twenty would leave 92 groups out of 2,311 and would drop most of the archaeological
record this milestone exists to reach; five leaves 442 and keeps the claim honest by
reporting the count beside every distance.
"""

_UNKNOWN_ALLELES: Final[frozenset[str]] = frozenset({"0", "X", "N", ".", ""})
"""What AADR writes at a site whose second allele is not observed in the resource.

Such a row is monomorphic as far as this file is concerned, so it cannot be oriented against
the panel: there is no allele pair to compare. Counted, not silently skipped.
"""


class AadrError(RuntimeError):
    """The ancient panel could not be built, or a sample could not be compared to it."""


# ---------------------------------------------------------------------------
# Selecting individuals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AncientPanel:
    """Ancient individuals kept, their codes at the shared markers, and what was dropped.

    Ancient genotypes are public archive data rather than anybody's personal export, so this
    holds real calls and is not genotype-safe in the AGENTS.md 1.1 sense. It is still not
    something to print: it is tens of millions of codes.
    """

    individuals: tuple[AadrIndividual, ...]
    codes: tuple[tuple[int, ...], ...]
    """Per individual, one code per row of :attr:`sites`, in that row order."""

    sites: EigenstratSites
    called: tuple[int, ...]
    """Per individual, how many of the shared markers were called."""

    n_heterozygous: tuple[int, ...]
    """Per individual, how many calls were heterozygous. Nearly always zero -- see this
    module's docstring. Counted rather than assumed from the identifier's suffix, because
    the ``.DG``/``.SG`` shotgun genomes genuinely are diploid."""

    n_considered: int
    n_below_coverage: int
    source: str

    @property
    def n_individuals(self) -> int:
        return len(self.individuals)

    @property
    def pseudo_haploid_fraction(self) -> float:
        if not self.individuals:
            return 0.0
        return sum(1 for count in self.n_heterozygous if count == 0) / len(self.individuals)


def select_ancient_individuals(
    packed: PackedGenotypes,
    individuals: Sequence[AadrIndividual],
    sites: EigenstratSites,
    *,
    min_coverage: float = MIN_SHARED_COVERAGE,
    prefilter_ho_snps: int = 100_000,
) -> AncientPanel:
    """Read the ancient individuals worth using, at the shared markers only.

    ``sites`` must be the marker set the reference PCA actually covers --
    :attr:`~genetics.ancestry.reference_pca.ReferencePCA.marker_positions` -- and not the
    wider AADR-and-array overlap it was restricted *from*. The coverage floor below is
    counted over whatever it is given, so the wrong set here admits individuals that later
    project below :func:`~genetics.ancestry.projection.project`'s own floor, and that failure
    reports a panel mismatch. :func:`write_ancient_vcf` refuses the wider set outright.

    ``prefilter_ho_snps`` skips individuals the resource itself publishes as hitting fewer
    than that many autosomal HO markers, *before* spending a read on each. It is a cost
    control rather than a criterion -- the criterion is ``min_coverage``, counted over the
    markers actually shared with the reference, which is a different and much smaller set.
    Set it to zero to read every ancient individual; on ``v66.p1_HO`` that is 19,119 reads
    instead of 13,832 to keep the same 9,700.
    """
    if not 0.0 <= min_coverage <= 1.0:
        raise AadrError(f"min_coverage must lie between 0 and 1, got {min_coverage}")
    if sites.n_sites == 0:
        raise AadrError(
            "the shared marker set is empty, so no ancient individual can be placed. The "
            "AADR .snp and the reference panel disagree about positions entirely, which is "
            "usually a build mismatch rather than two unrelated arrays."
        )

    candidates = [
        individual
        for individual in individuals
        if individual.is_ancient and (individual.ho_snps or 0) >= prefilter_ho_snps
    ]
    floor = min_coverage * sites.n_sites
    by_index = {individual.index: individual for individual in candidates}

    kept: list[AadrIndividual] = []
    kept_codes: list[tuple[int, ...]] = []
    called: list[int] = []
    hets: list[int] = []
    below = 0
    for index, codes in read_individuals(packed, [i.index for i in candidates], sites.indices):
        n_called = sum(1 for code in codes if code != CODE_MISSING)
        if n_called < floor:
            below += 1
            continue
        kept.append(by_index[index])
        kept_codes.append(tuple(codes))
        called.append(n_called)
        hets.append(sum(1 for code in codes if code == 1))

    return AncientPanel(
        individuals=tuple(kept),
        codes=tuple(kept_codes),
        sites=sites,
        called=tuple(called),
        n_heterozygous=tuple(hets),
        n_considered=len(candidates),
        n_below_coverage=below,
        source=sites.source,
    )


# ---------------------------------------------------------------------------
# Onto the panel's alleles
# ---------------------------------------------------------------------------


_VCF_FIXED: Final[str] = "\t".join(
    ("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT")
)


def _aadr_alleles(a1: str, a2: str) -> tuple[str, str] | None:
    """AADR's allele pair, or ``None`` when the row does not carry two real bases."""
    if a1 in _UNKNOWN_ALLELES or a2 in _UNKNOWN_ALLELES:
        return None
    if not is_snp_site([a1, a2]):
        return None
    return a1, a2


def _panel_indices(a1: str, a2: str, panel_alleles: Sequence[str]) -> tuple[int, int] | None:
    """Where AADR's two alleles land among the panel's, flipping strand if that is what fits.

    Returns ``(index of a1, index of a2)`` or ``None`` when the pair is not the panel's under
    either reading. Reuses :func:`~genetics.external.harmonize.orient`'s rule rather than a
    second copy of it, and can do so safely because **the reference PCA's markers are already
    free of strand-ambiguous sites** -- M5.5 excluded them from the eigenvector build, so at
    every marker reaching this function at most one strand reading fits and there is no tie
    to break.
    """
    indices, _outcome = orient(a1 + a2, panel_alleles)
    if indices is None:
        return None
    # `orient` sorts, which loses which index belonged to a1. Recover it by asking the
    # question directly under whichever reading fitted.
    lookup = {allele: position for position, allele in enumerate(panel_alleles)}
    if a1 in lookup and a2 in lookup:
        return lookup[a1], lookup[a2]
    flipped_1, flipped_2 = complement(a1), complement(a2)
    if flipped_1 in lookup and flipped_2 in lookup:
        return lookup[flipped_1], lookup[flipped_2]
    return None


def write_ancient_vcf(
    panel_sites: PanelSites, ancient: AncientPanel, destination: Path
) -> dict[str, int]:
    """Write the ancient individuals as one multi-sample VCF on the panel's alleles.

    Returns counts of what became of each shared marker. The single-sample writer in
    :mod:`genetics.external.harmonize` cannot be reused: it decides one call per position
    from vendor probe rows, while here a position carries one code per individual and the
    orientation question is asked once for the whole column rather than once per sample.

    **A pseudo-haploid call is written as the diploid homozygote the resource encodes**, not
    as a haploid ``GT``. That is what the codes mean -- the drawn allele, doubled -- and
    writing ``0`` instead would make PLINK treat the record as half a genome and halve every
    ``ALLELE_CT``, which feeds coverage. The doubling is a property of the archive and it is
    reported by :attr:`AncientPanel.pseudo_haploid_fraction` rather than hidden here.
    """
    panel = panel_sites.frame.select("chrom", "pos", "panel_id", "ref", "alt")
    lookup = {
        (str(chrom), int(pos)): (str(panel_id), str(ref), str(alt))
        for chrom, pos, panel_id, ref, alt in panel.iter_rows()
    }
    counts = {"written": 0, "not_in_panel": 0, "aadr_not_snp": 0, "allele_mismatch": 0}

    rows = list(ancient.sites.frame.select("chrom", "pos", "a1", "a2").iter_rows())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        handle.write("##fileformat=VCFv4.2\n##reference=GRCh37\n")
        handle.write(f"##source=AADR {ancient.source} (M5.6 ancient projection)\n")
        handle.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        handle.write(_VCF_FIXED + "\t" + "\t".join(_vcf_names(ancient)) + "\n")

        for row, (chrom, pos, a1, a2) in enumerate(rows):
            record = lookup.get((str(chrom), int(pos)))
            if record is None:
                counts["not_in_panel"] += 1
                continue
            pair = _aadr_alleles(str(a1), str(a2))
            if pair is None:
                counts["aadr_not_snp"] += 1
                continue
            panel_id, ref, alt = record
            alleles = [ref, *(a for a in alt.split(",") if a != ".")]
            placed = _panel_indices(pair[0], pair[1], alleles)
            if placed is None:
                counts["allele_mismatch"] += 1
                continue
            first, second = placed
            calls = []
            for codes in ancient.codes:
                code = codes[row]
                if code == CODE_MISSING:
                    calls.append("./.")
                    continue
                # The code counts copies of AADR's first allele; the rest are its second.
                left, right = sorted((first,) * code + (second,) * (2 - code))
                calls.append(f"{left}/{right}")
            handle.write(
                f"{chrom}\t{pos}\t{panel_id}\t{ref}\t{alt}\t.\t.\t.\tGT\t" + "\t".join(calls) + "\n"
            )
            counts["written"] += 1

    if counts["not_in_panel"]:
        destination.unlink(missing_ok=True)
        raise AadrError(
            f"{counts['not_in_panel']:,} of the {len(rows):,} AADR sites handed in are not "
            "markers of this reference PCA. ``ancient`` must already be restricted to "
            "``ReferencePCA.marker_positions`` -- the same set its coverage floor was "
            "counted over. Handing in the wider AADR-and-array overlap lets an individual "
            "pass the floor on markers this space does not carry and then project below it, "
            "which surfaces two steps later as a panel-mismatch error naming the wrong cause."
        )
    if not counts["written"]:
        destination.unlink(missing_ok=True)
        raise AadrError(
            "no shared marker could be placed on the panel's alleles: "
            f"{counts['not_in_panel']:,} were not panel sites, {counts['aadr_not_snp']:,} "
            f"carried no allele pair in AADR and {counts['allele_mismatch']:,} disagreed "
            "with the panel about which variant lives there."
        )
    return counts


def _vcf_names(ancient: AncientPanel) -> list[str]:
    """Sample column names, which are AADR's own public identifiers.

    Unlike :data:`~genetics.external.harmonize.SAMPLE_ID`, these are not replaced by a
    constant: they name published archive individuals rather than the person running this,
    and the group centroids downstream have to be traceable back to who is in them.
    """
    return [individual.sample_id for individual in ancient.individuals]


# ---------------------------------------------------------------------------
# Groups and affinity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AncientGroup:
    """One AADR group label with enough well-covered individuals to place a centre."""

    group: str
    n_individuals: int
    date_bp_median: float
    date_bp_range: tuple[float, float]
    centroid: tuple[float, ...]
    """In the same scaled units :class:`~genetics.ancestry.populations.PopulationModel` uses,
    so a distance to here is comparable with a distance to a modern population."""

    mean_called: float
    """Mean shared markers called across the group's members. A group whose individuals each
    called a third of the markers has a centroid that wandered, and the number saying so
    belongs beside it rather than in a log."""


@dataclass(frozen=True)
class AncientModel:
    """Ancient group centroids in the shared space, plus what it cost to get them."""

    reference: str
    n_components: int
    scale: tuple[float, ...]
    groups: tuple[AncientGroup, ...]
    n_individuals_used: int
    dropped_groups: Mapping[str, int]
    """Group labels left out for having fewer than :data:`MIN_GROUP_INDIVIDUALS` well-covered
    individuals, and how many each had."""

    pseudo_haploid_fraction: float
    n_shared_markers: int
    source: str

    @property
    def n_groups(self) -> int:
        return len(self.groups)


@dataclass(frozen=True, slots=True)
class GroupAffinity(NoGenotypeRepr):
    """How close the sample sits to one ancient group's centre."""

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_individuals",)
    """The group name is withheld for the reason :class:`AncientAffinity` refuses a
    ``nearest_group`` accessor: :attr:`AncientAffinity.groups` is ordered nearest-first, so
    printing one of them -- or the tuple -- is that accessor by another route."""

    group: str
    n_individuals: int
    date_bp_median: float
    date_bp_range: tuple[float, float]
    distance: float
    """In pooled within-population standard deviations of the modern panel, so it is the
    same unit :class:`~genetics.ancestry.populations.PopulationFit` reports."""

    mean_called: float


@dataclass(frozen=True)
class AncientAffinity(NoGenotypeRepr):
    """The M5.6 result: ancient groups ranked by distance, and nothing called descent.

    There is deliberately no ``nearest_group`` convenience and no naming decision. M5.5 has
    one because "which living population is this" has an answer the panel can refuse; "which
    archaeological group is this person descended from" has no answer at all from a distance,
    and a single accessor is how a ranked list quietly becomes a claim.
    """

    _repr_fields: ClassVar[tuple[str, ...]] = ("n_groups", "coverage")

    sample_id: str
    groups: tuple[GroupAffinity, ...]
    """Every retained group, nearest first."""

    coverage: float
    n_scored_markers: int
    n_shared_markers: int
    n_ancient_individuals: int
    dropped_groups: Mapping[str, int]
    pseudo_haploid_fraction: float
    source: str

    @property
    def n_groups(self) -> int:
        return len(self.groups)

    @property
    def spread(self) -> float:
        """Distance from the nearest group to the median one.

        The number that says whether the ranking means anything. If the closest group is a
        hair nearer than the fiftieth, the order is noise and a card should say so rather
        than print a leaderboard.
        """
        if len(self.groups) < 2:
            return 0.0
        ordered = [group.distance for group in self.groups]
        return ordered[len(ordered) // 2] - ordered[0]


def build_ancient_model(
    ancient_projection: Projection,
    ancient: AncientPanel,
    modern: PopulationModel,
    *,
    min_individuals: int = MIN_GROUP_INDIVIDUALS,
) -> AncientModel:
    """Group the projected ancient individuals into centroids on the modern panel's scale.

    ``modern`` must have been built from the 1000 Genomes panel projected into **this same
    space** -- the restricted one M5.6 builds, not M5.5's. The check is the reference name,
    for the reason :func:`~genetics.ancestry.populations.place` gives.
    """
    if ancient_projection.reference != modern.reference:
        raise AadrError(
            f"the ancient individuals were projected against {ancient_projection.reference!r} "
            f"and the modern population model was built from {modern.reference!r}. Ancient "
            "affinity needs one space, and these are two."
        )
    if ancient_projection.n_components != modern.n_components:
        raise AadrError(
            f"the ancient projection carries {ancient_projection.n_components} component(s) "
            f"and the modern model {modern.n_components}."
        )

    pcs = [f"PC{i + 1}" for i in range(modern.n_components)]
    metadata = pl.DataFrame(
        {
            "sample_id": [individual.sample_id for individual in ancient.individuals],
            "group": [individual.group for individual in ancient.individuals],
            "date_bp": [float(individual.date_bp or 0.0) for individual in ancient.individuals],
            "called": [float(value) for value in ancient.called],
        }
    )
    frame = ancient_projection.coordinates.select("sample_id", *pcs).join(
        metadata, on="sample_id", how="inner"
    )
    if frame.height != ancient.n_individuals:
        raise AadrError(
            f"{ancient.n_individuals - frame.height:,} of the ancient individuals handed in "
            "are missing from the projection. The .sscore and the panel describe different "
            "sets of people, so a centroid would be over whoever survived both."
        )

    scaled = frame.with_columns(
        [(pl.col(name) / value).alias(name) for name, value in zip(pcs, modern.scale, strict=True)]
    )
    sizes = scaled.group_by("group").len()
    small = {
        str(row["group"]): int(row["len"])
        for row in sizes.filter(pl.col("len") < min_individuals).iter_rows(named=True)
    }
    kept = scaled.filter(~pl.col("group").is_in(list(small)))
    if kept.is_empty():
        raise AadrError(
            f"no ancient group has {min_individuals} well-covered individuals. "
            f"{len(small):,} group(s) were considered and the largest held "
            f"{max(small.values(), default=0)}."
        )

    aggregated = kept.group_by("group").agg(
        pl.len().alias("n"),
        pl.col("date_bp").median().alias("date_median"),
        pl.col("date_bp").min().alias("date_min"),
        pl.col("date_bp").max().alias("date_max"),
        pl.col("called").mean().alias("mean_called"),
        *[pl.col(name).mean().alias(name) for name in pcs],
    )
    groups = tuple(
        AncientGroup(
            group=str(row["group"]),
            n_individuals=int(row["n"]),
            date_bp_median=float(row["date_median"]),
            date_bp_range=(float(row["date_min"]), float(row["date_max"])),
            centroid=tuple(float(row[name]) for name in pcs),
            mean_called=float(row["mean_called"]),
        )
        for row in aggregated.sort("group").iter_rows(named=True)
    )
    return AncientModel(
        reference=modern.reference,
        n_components=modern.n_components,
        scale=modern.scale,
        groups=groups,
        n_individuals_used=int(kept.height),
        dropped_groups=small,
        pseudo_haploid_fraction=ancient.pseudo_haploid_fraction,
        n_shared_markers=ancient.sites.n_sites,
        source=ancient.source,
    )


def affinity(projection: Projection, model: AncientModel) -> AncientAffinity:
    """Rank the ancient groups by distance from one projected sample.

    Refuses a sample from a different space, the same way
    :func:`~genetics.ancestry.populations.place` does and for the same reason: two sets of
    coordinates from different eigenvector sets have the same shape and plot together.
    """
    if projection.reference != model.reference:
        raise AadrError(
            f"the sample was projected against {projection.reference!r} and the ancient "
            f"groups were built in {model.reference!r}. M5.6 needs the sample, the modern "
            "panel and the ancient individuals in one space; project the sample against the "
            "restricted reference PCA rather than M5.5's."
        )
    if projection.n_components != model.n_components:
        raise AadrError(
            f"the sample carries {projection.n_components} component(s) and the ancient "
            f"groups {model.n_components}."
        )
    if projection.n_samples != 1:
        raise AadrError(
            f"affinity() takes a single sample's projection; this one holds {projection.n_samples}."
        )

    pcs = [f"PC{i + 1}" for i in range(model.n_components)]
    missing = [name for name in ("sample_id", *pcs) if name not in projection.coordinates.columns]
    if missing:
        raise AadrError(f"the sample projection is missing {missing}.")

    row = next(iter(projection.coordinates.select("sample_id", *pcs).iter_rows()))
    sample_id = str(row[0])
    point = tuple(float(value) / scale for value, scale in zip(row[1:], model.scale, strict=True))

    ranked = sorted(
        (
            GroupAffinity(
                group=group.group,
                n_individuals=group.n_individuals,
                date_bp_median=group.date_bp_median,
                date_bp_range=group.date_bp_range,
                distance=_distance(point, group.centroid),
                mean_called=group.mean_called,
            )
            for group in model.groups
        ),
        key=lambda item: item.distance,
    )
    return AncientAffinity(
        sample_id=sample_id,
        groups=tuple(ranked),
        coverage=projection.coverage,
        n_scored_markers=projection.n_scored_markers,
        n_shared_markers=model.n_shared_markers,
        n_ancient_individuals=model.n_individuals_used,
        dropped_groups=model.dropped_groups,
        pseudo_haploid_fraction=model.pseudo_haploid_fraction,
        source=model.source,
    )


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))


def shared_positions(sites: EigenstratSites) -> list[tuple[str, int]]:
    """The ``(chrom, pos)`` pairs an :class:`EigenstratSites` covers.

    What :func:`~genetics.ancestry.reference_pca.build_reference_pca` takes as
    ``restrict_to`` to build the shared space this module works in.
    """
    return [(str(chrom), int(pos)) for chrom, pos in sites.frame.select("chrom", "pos").iter_rows()]
