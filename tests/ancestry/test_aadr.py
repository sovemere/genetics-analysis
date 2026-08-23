"""Affinity to ancient populations (roadmap M5.6, second half).

Synthetic throughout, for the reason :mod:`tests.ancestry.test_populations` gives about
M5.5: the decisions here are arithmetic and refusals, and a fixture drawn from the real
archive could not produce the cases that matter -- an ancient group of four, a pseudo-haploid
individual beside a diploid one, an AADR row whose alleles are the panel's complement.

What the real archive established is recorded where it belongs: the ``TGENO`` layout in
:mod:`genetics.ancestry.eigenstrat`, and the pseudo-haploid fraction, the group-size
distribution and the modern-sample validation in :mod:`genetics.ancestry.aadr`'s docstring
and on M5.6.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import polars as pl
import pytest

from genetics.ancestry.aadr import (
    MIN_GROUP_INDIVIDUALS,
    AadrError,
    AncientPanel,
    affinity,
    build_ancient_model,
    select_ancient_individuals,
    shared_positions,
    write_ancient_vcf,
)
from genetics.ancestry.eigenstrat import CODE_MISSING, AadrIndividual, EigenstratSites, open_packed
from genetics.ancestry.populations import PopulationLabels, build_population_model
from genetics.ancestry.projection import Projection
from genetics.external.harmonize import read_panel_sites

# ``tests/`` is not a package (see tests/conftest.py), so the fixture writers in the
# sibling module are loaded by path rather than imported. Sharing them is right: a second
# packed-file writer here would be a second description of the layout, and the two would
# drift the first time one of them was corrected.
_spec = spec_from_file_location(
    "aadr_fixture_writers", Path(__file__).with_name("test_eigenstrat.py")
)
assert _spec is not None and _spec.loader is not None
_eigenstrat = module_from_spec(_spec)
_spec.loader.exec_module(_eigenstrat)
write_geno = _eigenstrat.write_geno
write_snp = _eigenstrat.write_snp

K = 4
PCS = [f"PC{i + 1}" for i in range(K)]


def at(*point: float) -> pl.DataFrame:
    """A one-row coordinate frame, which is what ``affinity`` takes."""
    values = point or (0.0,) * K
    return pl.DataFrame({"sample_id": ["S"], **{pc: [values[i]] for i, pc in enumerate(PCS)}})


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def sites_from(rows: list[tuple[str, str, int, str, str]], tmp_path: Path) -> EigenstratSites:
    from genetics.ancestry.eigenstrat import read_snp

    return read_snp(write_snp(tmp_path, rows))


def only_record(vcf: Path) -> list[str]:
    """The one data line of a written VCF, split on tabs."""
    line = next(row for row in vcf.read_text().splitlines() if not row.startswith("#"))
    return line.split("	")


def sample_columns(vcf: Path) -> list[str]:
    header = next(line for line in vcf.read_text().splitlines() if line.startswith("#CHROM"))
    return header.split("	")[9:]


def panel_pvar(tmp_path: Path, rows: list[tuple[str, int, str, str, str]]) -> Path:
    path = tmp_path / "panel.pvar"
    lines = ["#CHROM\tPOS\tID\tREF\tALT"]
    lines += ["\t".join((c, str(p), i, r, a)) for c, p, i, r, a in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def individual(index: int, group: str, *, bp: float = 4000.0, ho: int = 500_000) -> AadrIndividual:
    return AadrIndividual(
        index=index, sample_id=f"I{index}", sex="U", group=group, date_bp=bp, ho_snps=ho
    )


def ancient_panel(
    individuals: list[AadrIndividual],
    codes: list[list[int]],
    sites: EigenstratSites,
) -> AncientPanel:
    return AncientPanel(
        individuals=tuple(individuals),
        codes=tuple(tuple(row) for row in codes),
        sites=sites,
        called=tuple(sum(1 for c in row if c != CODE_MISSING) for row in codes),
        n_heterozygous=tuple(sum(1 for c in row if c == 1) for row in codes),
        n_considered=len(individuals),
        n_below_coverage=0,
        source=sites.source,
    )


def projection(
    coordinates: pl.DataFrame, *, reference: str = "refpca-shared", n_components: int = K
) -> Projection:
    return Projection(
        coordinates=coordinates,
        n_scored_alleles=2 * 11_128,
        n_reference_markers=11_128,
        n_components=n_components,
        reference=reference,
        sscore=Path("unused.sscore"),
        plink=None,  # type: ignore[arg-type]
    )


def modern_model(reference: str = "refpca-shared"):  # type: ignore[no-untyped-def]
    """A modern population model in the shared space, which is what sets the metric."""
    ids: list[str] = []
    pops: list[str] = []
    rows: list[tuple[float, ...]] = []
    for name, centre in {"AAA": (0.0, 0.0, 0.0, 0.0), "BBB": (40.0, 0.0, 0.0, 0.0)}.items():
        for i in range(60):
            ids.append(f"{name}{i:03d}")
            pops.append(name)
            rows.append(tuple(c + math.sin((i + 1) * (a + 1.7)) for a, c in enumerate(centre)))
    coordinates = pl.DataFrame(
        {"sample_id": ids, **{pc: [r[i] for r in rows] for i, pc in enumerate(PCS)}}
    )
    labels = PopulationLabels(
        frame=pl.DataFrame({"sample_id": ids, "population": pops, "region": ["REG"] * len(ids)}),
        source="test.panel",
    )
    return build_population_model(projection(coordinates, reference=reference), labels)


def ancient_coordinates(groups: Mapping[str, tuple[float, ...]], n: int) -> pl.DataFrame:
    ids: list[str] = []
    rows: list[tuple[float, ...]] = []
    for seed, (name, centre) in enumerate(groups.items()):
        for i in range(n):
            ids.append(f"{name}-{i}")
            rows.append(
                tuple(c + 0.3 * math.sin((i + 1) * (a + 1.3) + seed) for a, c in enumerate(centre))
            )
    return pl.DataFrame(
        {"sample_id": ids, **{pc: [r[i] for r in rows] for i, pc in enumerate(PCS)}}
    )


def ancient_for(
    groups: Mapping[str, tuple[float, ...]], n: int, sites: EigenstratSites
) -> AncientPanel:
    individuals = [
        AadrIndividual(
            index=i,
            sample_id=f"{name}-{j}",
            sex="U",
            group=name,
            date_bp=1000.0 + 100 * j,
            ho_snps=500_000,
        )
        for i, (name, j) in enumerate((name, j) for name in groups for j in range(n))
    ]
    codes = [[2] * sites.n_sites for _ in individuals]
    return ancient_panel(individuals, codes, sites)


# ---------------------------------------------------------------------------
# Selecting individuals
# ---------------------------------------------------------------------------


def test_only_ancient_individuals_are_read(tmp_path: Path) -> None:
    """Present-day Human Origins samples carry a date of 0 and are 8,474 of the archive.
    They are a reference panel, not an ancient one."""
    sites = sites_from([("rs1", "1", 100, "A", "G"), ("rs2", "1", 200, "A", "G")], tmp_path)
    geno = write_geno(tmp_path, [[2, 2], [2, 2], [2, 2]], n_sites=2)
    packed = open_packed(geno, n_individuals=3, n_sites=2)
    individuals = [
        individual(0, "ancient_one"),
        AadrIndividual(index=1, sample_id="I1", sex="U", group="modern", date_bp=0.0, ho_snps=9),
        AadrIndividual(index=2, sample_id="I2", sex="U", group="undated", date_bp=None),
    ]

    panel = select_ancient_individuals(packed, individuals, sites, prefilter_ho_snps=0)

    assert [i.sample_id for i in panel.individuals] == ["I0"]
    assert panel.n_considered == 1


def test_an_individual_below_the_coverage_floor_is_dropped_and_counted(tmp_path: Path) -> None:
    """A pseudo-haploid individual with a few hundred markers still projects, and it
    projects to somewhere. That is the failure this floor exists to prevent."""
    sites = sites_from([(f"rs{i}", "1", 100 * (i + 1), "A", "G") for i in range(8)], tmp_path)
    rich = [2] * 8
    poor = [2, 2] + [CODE_MISSING] * 6
    geno = write_geno(tmp_path, [rich, poor], n_sites=8)
    packed = open_packed(geno, n_individuals=2, n_sites=8)

    panel = select_ancient_individuals(
        packed, [individual(0, "g"), individual(1, "g")], sites, prefilter_ho_snps=0
    )

    assert [i.sample_id for i in panel.individuals] == ["I0"]
    assert panel.n_below_coverage == 1
    assert panel.n_considered == 2


def test_the_published_marker_count_only_prefilters_and_is_not_the_criterion(
    tmp_path: Path,
) -> None:
    """It counts a different and much larger marker set, so it is a cost control on how many
    146 KB reads happen -- not a statement about coverage on the shared markers."""
    sites = sites_from([(f"rs{i}", "1", 100 * (i + 1), "A", "G") for i in range(4)], tmp_path)
    geno = write_geno(tmp_path, [[2] * 4, [2] * 4], n_sites=4)
    packed = open_packed(geno, n_individuals=2, n_sites=4)
    people = [individual(0, "g", ho=500_000), individual(1, "g", ho=10)]

    wide = select_ancient_individuals(packed, people, sites, prefilter_ho_snps=0)
    narrow = select_ancient_individuals(packed, people, sites, prefilter_ho_snps=1000)

    assert wide.n_individuals == 2
    assert narrow.n_individuals == 1


def test_pseudo_haploidy_is_counted_rather_than_read_off_the_identifier(tmp_path: Path) -> None:
    """99.2% of the real archive's well-covered ancients carry no heterozygote, but the
    ``.DG``/``.SG`` shotgun genomes genuinely are diploid, so the suffix is not the answer."""
    sites = sites_from([(f"rs{i}", "1", 100 * (i + 1), "A", "G") for i in range(4)], tmp_path)
    geno = write_geno(tmp_path, [[2, 0, 2, 0], [1, 1, 2, 0]], n_sites=4)
    packed = open_packed(geno, n_individuals=2, n_sites=4)

    panel = select_ancient_individuals(
        packed, [individual(0, "g"), individual(1, "g")], sites, prefilter_ho_snps=0
    )

    assert panel.n_heterozygous == (0, 2)
    assert panel.pseudo_haploid_fraction == pytest.approx(0.5)


def test_an_empty_shared_marker_set_is_refused(tmp_path: Path) -> None:
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    empty = EigenstratSites(frame=sites.frame.head(0), source=sites.source, n_read=1)
    geno = write_geno(tmp_path, [[2]], n_sites=1)
    packed = open_packed(geno, n_individuals=1, n_sites=1)

    with pytest.raises(AadrError, match="shared marker set is empty"):
        select_ancient_individuals(packed, [individual(0, "g")], empty)


# ---------------------------------------------------------------------------
# Onto the panel's alleles
# ---------------------------------------------------------------------------


def test_a_code_is_written_as_copies_of_aadrs_first_allele(tmp_path: Path) -> None:
    """The whole conversion rests on this reading of the code, and getting it inverted
    would mirror every ancient individual through the origin while still plotting."""
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    panel = read_panel_sites(panel_pvar(tmp_path, [("1", 100, "1:100:A:G", "A", "G")]))
    ancient = ancient_panel(
        [individual(0, "g"), individual(1, "g"), individual(2, "g")], [[2], [1], [0]], sites
    )

    out = tmp_path / "ancient.vcf"
    counts = write_ancient_vcf(panel, ancient, out)

    assert counts["written"] == 1
    # REF=A is index 0 and AADR's first allele is A, so code 2 is two copies of A.
    assert only_record(out)[9:] == ["0/0", "0/1", "1/1"]


def test_a_no_call_is_written_as_missing(tmp_path: Path) -> None:
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    panel = read_panel_sites(panel_pvar(tmp_path, [("1", 100, "1:100:A:G", "A", "G")]))
    ancient = ancient_panel([individual(0, "g")], [[CODE_MISSING]], sites)

    out = tmp_path / "ancient.vcf"
    write_ancient_vcf(panel, ancient, out)

    assert only_record(out)[9] == "./."


def test_an_opposite_strand_aadr_row_is_flipped_onto_the_panel(tmp_path: Path) -> None:
    """AADR is forward-strand and so is the panel, but nothing enforces that between two
    array designs, and the reference PCA's markers are ambiguity-free so the flip is
    decidable without a tie-break."""
    sites = sites_from([("rs1", "1", 100, "T", "C")], tmp_path)
    panel = read_panel_sites(panel_pvar(tmp_path, [("1", 100, "1:100:A:G", "A", "G")]))
    ancient = ancient_panel([individual(0, "g")], [[2]], sites)

    out = tmp_path / "ancient.vcf"
    counts = write_ancient_vcf(panel, ancient, out)

    assert counts["written"] == 1
    # AADR's first allele T complements to A, which is the panel's REF: two copies of index 0.
    assert only_record(out)[9] == "0/0"


def test_a_row_the_panel_disagrees_with_is_counted_not_written(tmp_path: Path) -> None:
    sites = sites_from([("rs1", "1", 100, "A", "C")], tmp_path)
    panel = read_panel_sites(panel_pvar(tmp_path, [("1", 100, "1:100:A:G", "A", "G")]))
    ancient = ancient_panel([individual(0, "g")], [[2]], sites)

    with pytest.raises(AadrError, match="no shared marker could be placed"):
        write_ancient_vcf(panel, ancient, tmp_path / "ancient.vcf")


def test_a_monomorphic_aadr_row_carries_no_allele_pair_to_orient(tmp_path: Path) -> None:
    sites = sites_from([("rs1", "1", 100, "A", "X"), ("rs2", "1", 200, "A", "G")], tmp_path)
    panel = read_panel_sites(
        panel_pvar(tmp_path, [("1", 100, "1:100:A:G", "A", "G"), ("1", 200, "1:200:A:G", "A", "G")])
    )
    ancient = ancient_panel([individual(0, "g")], [[2, 2]], sites)

    counts = write_ancient_vcf(panel, ancient, tmp_path / "ancient.vcf")

    assert counts == {"written": 1, "not_in_panel": 0, "aadr_not_snp": 1, "allele_mismatch": 0}


def test_sites_wider_than_the_reference_pca_are_refused_with_the_reason(tmp_path: Path) -> None:
    """The defect this guard was written for: the coverage floor counted over the
    AADR-and-array overlap admitted individuals that then projected below
    ``project()``'s floor, two steps later, as a panel-mismatch error naming the wrong cause."""
    sites = sites_from([("rs1", "1", 100, "A", "G"), ("rs2", "1", 999, "A", "G")], tmp_path)
    panel = read_panel_sites(panel_pvar(tmp_path, [("1", 100, "1:100:A:G", "A", "G")]))
    ancient = ancient_panel([individual(0, "g")], [[2, 2]], sites)

    with pytest.raises(AadrError, match="marker_positions"):
        write_ancient_vcf(panel, ancient, tmp_path / "ancient.vcf")


def test_the_sample_columns_are_aadrs_own_public_identifiers(tmp_path: Path) -> None:
    """Unlike the single-sample writer's constant: these name published archive individuals
    rather than the person running this, and a centroid has to be traceable to who is in it."""
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    panel = read_panel_sites(panel_pvar(tmp_path, [("1", 100, "1:100:A:G", "A", "G")]))
    ancient = ancient_panel([individual(0, "g"), individual(1, "g")], [[2], [0]], sites)

    out = tmp_path / "ancient.vcf"
    write_ancient_vcf(panel, ancient, out)

    assert sample_columns(out) == ["I0", "I1"]


# ---------------------------------------------------------------------------
# Groups and affinity
# ---------------------------------------------------------------------------


GROUPS = {"NEAR": (2.0, 0.0, 0.0, 0.0), "FAR": (38.0, 0.0, 0.0, 0.0)}


def built(tmp_path: Path, n: int = 6):  # type: ignore[no-untyped-def]
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    ancient = ancient_for(GROUPS, n, sites)
    coordinates = ancient_coordinates(GROUPS, n)
    return build_ancient_model(projection(coordinates), ancient, modern_model()), coordinates


def test_groups_become_centroids_on_the_modern_panels_scale(tmp_path: Path) -> None:
    model, _coords = built(tmp_path)

    assert model.n_groups == 2
    assert {group.group for group in model.groups} == {"NEAR", "FAR"}
    assert model.scale == modern_model().scale
    assert model.n_individuals_used == 12


def test_a_group_below_the_floor_is_dropped_and_counted(tmp_path: Path) -> None:
    """AADR group labels are archaeological contexts with a median of two individuals. A
    centroid of two pseudo-haploid people has error bars wider than the distances reported,
    and a ranked list is exactly the presentation that hides that."""
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    groups = {"BIG": (0.0, 0.0, 0.0, 0.0), "TINY": (10.0, 0.0, 0.0, 0.0)}
    individuals = [
        AadrIndividual(index=i, sample_id=name, sex="U", group=name.split("-")[0], date_bp=900.0)
        for i, name in enumerate([f"BIG-{j}" for j in range(6)] + [f"TINY-{j}" for j in range(2)])
    ]
    codes = [[2] for _ in individuals]
    panel = ancient_panel(individuals, codes, sites)
    coordinates = pl.DataFrame(
        {
            "sample_id": [i.sample_id for i in individuals],
            **{
                pc: [groups[i.group][a] + 0.1 * n for n, i in enumerate(individuals)]
                for a, pc in enumerate(PCS)
            },
        }
    )

    model = build_ancient_model(projection(coordinates), panel, modern_model())

    assert [group.group for group in model.groups] == ["BIG"]
    assert model.dropped_groups == {"TINY": 2}
    assert MIN_GROUP_INDIVIDUALS == 5


def test_groups_come_back_ranked_by_distance(tmp_path: Path) -> None:
    model, _coords = built(tmp_path)

    result = affinity(projection(at()), model)

    assert [group.group for group in result.groups] == ["NEAR", "FAR"]
    assert result.groups[0].distance < result.groups[1].distance
    assert result.n_groups == 2


def test_each_group_carries_its_size_and_dates_beside_its_distance(tmp_path: Path) -> None:
    """A distance to a group of five is a different claim from a distance to a group of
    eighty, and a ranked list without the count next to it hides which one it is."""
    model, _coords = built(tmp_path)

    result = affinity(projection(at()), model)
    nearest = result.groups[0]

    assert nearest.n_individuals == 6
    assert nearest.date_bp_range == (1000.0, 1500.0)
    assert nearest.date_bp_median == pytest.approx(1250.0)
    assert nearest.mean_called > 0


def test_the_spread_says_whether_the_ranking_separates_anything(tmp_path: Path) -> None:
    """If the closest group is a hair nearer than the median one, the order is noise, and a
    card that printed a leaderboard would be printing noise."""
    model, _coords = built(tmp_path)

    result = affinity(projection(at()), model)

    assert result.spread > 0
    assert result.spread == pytest.approx(result.groups[1].distance - result.groups[0].distance)


def test_the_pseudo_haploid_fraction_reaches_the_result(tmp_path: Path) -> None:
    model, _coords = built(tmp_path)

    result = affinity(projection(at()), model)

    assert result.pseudo_haploid_fraction == pytest.approx(1.0)
    assert result.n_ancient_individuals == 12


# ---------------------------------------------------------------------------
# Refusals that keep two spaces apart
# ---------------------------------------------------------------------------


def test_ancient_individuals_from_another_space_are_refused(tmp_path: Path) -> None:
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    ancient = ancient_for(GROUPS, 6, sites)
    coordinates = ancient_coordinates(GROUPS, 6)

    with pytest.raises(AadrError, match="one space, and these are two"):
        build_ancient_model(
            projection(coordinates, reference="refpca-m55"), ancient, modern_model()
        )


def test_a_sample_from_m5_5s_space_cannot_be_given_ancient_affinity(tmp_path: Path) -> None:
    """The whole reason M5.6 builds its own space: 11,128 markers against 52,411, and two
    sets of coordinates from different eigenvector sets plot together perfectly well."""
    model, _coords = built(tmp_path)
    with pytest.raises(AadrError, match="restricted reference PCA"):
        affinity(projection(at(), reference="refpca-m55"), model)


def test_a_component_count_mismatch_is_refused(tmp_path: Path) -> None:
    model, _coords = built(tmp_path)
    with pytest.raises(AadrError, match="component"):
        affinity(projection(at(), n_components=K + 1), model)


def test_affinity_takes_one_sample(tmp_path: Path) -> None:
    model, coords = built(tmp_path)

    with pytest.raises(AadrError, match="single sample"):
        affinity(projection(coords), model)


def test_an_individual_missing_from_the_projection_is_refused(tmp_path: Path) -> None:
    """A centroid over whoever survived both files is a centroid of that, and nothing about
    the number that comes out would look wrong."""
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    ancient = ancient_for(GROUPS, 6, sites)
    coordinates = ancient_coordinates(GROUPS, 6).head(11)

    with pytest.raises(AadrError, match="missing from the projection"):
        build_ancient_model(projection(coordinates), ancient, modern_model())


def test_no_group_reaching_the_floor_is_refused_rather_than_returning_nothing(
    tmp_path: Path,
) -> None:
    sites = sites_from([("rs1", "1", 100, "A", "G")], tmp_path)
    ancient = ancient_for(GROUPS, 2, sites)
    coordinates = ancient_coordinates(GROUPS, 2)

    with pytest.raises(AadrError, match="no ancient group has"):
        build_ancient_model(projection(coordinates), ancient, modern_model())


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_the_affinity_repr_carries_neither_a_group_nor_a_distance(tmp_path: Path) -> None:
    """A ranked list of ancient affinities is an ancestry inference about a person, which
    AGENTS.md 1.1 names in the same breath as PCA coordinates."""
    model, _coords = built(tmp_path)

    result = affinity(projection(at()), model)
    text = repr(result)

    assert "NEAR" not in text
    assert "n_groups" in text


@pytest.mark.privacy
def test_a_group_affinity_repr_does_not_name_its_group(tmp_path: Path) -> None:
    """``AncientAffinity`` refuses a ``nearest_group`` accessor because a single accessor is
    how a ranked list becomes a claim. ``groups`` is ordered nearest-first, so printing one
    of them -- or the tuple -- is that accessor by another route."""
    model, _coords = built(tmp_path)

    result = affinity(projection(at()), model)

    assert "NEAR" not in repr(result.groups[0])
    assert "n_individuals" in repr(result.groups[0])
    assert "NEAR" not in repr(result.groups)


def test_shared_positions_are_what_the_restriction_takes(tmp_path: Path) -> None:
    sites = sites_from([("rs1", "1", 100, "A", "G"), ("rs2", "2", 200, "C", "T")], tmp_path)

    assert shared_positions(sites) == [("1", 100), ("2", 200)]
