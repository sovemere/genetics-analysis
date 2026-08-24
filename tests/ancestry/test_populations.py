"""Nearest reference populations, and the refusal to name one (roadmap M5.5).

**These tests build their own panel geometry rather than using the real one**, and that is
not a compromise here the way a PLINK stub is elsewhere: this module contains no subprocess
and no external file format, so everything it decides can be exercised directly. A synthetic
panel also lets a test put a sample *exactly* where a Lebanese sample sits relative to
1000 Genomes -- between clusters, near none -- which no fixture drawn from the panel itself
could do, since the panel by construction has no such sample in it.

The real-panel behaviour that calibrated the module is recorded in
:data:`~genetics.ancestry.populations.DECLINE_QUANTILE` and on M5.5 in the roadmap. What is
checked here is that the rules those measurements chose are the rules the code implements.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from genetics.ancestry.populations import (
    DECLINE_QUANTILE,
    MIN_POPULATION_SAMPLES,
    THOUSAND_GENOMES_COVERAGE,
    PopulationLabels,
    PopulationModel,
    PopulationsError,
    build_population_model,
    coverage_for,
    place,
    place_many,
    read_population_labels,
)
from genetics.ancestry.projection import Projection

K = 4
PCS = [f"PC{i + 1}" for i in range(K)]

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def projection(
    coordinates: pl.DataFrame,
    *,
    n_components: int = K,
    reference: str = "refpca-test",
    n_markers: int = 50_000,
    scored: int | None = None,
) -> Projection:
    """A :class:`Projection` around coordinates that are simply given.

    Constructed rather than produced, because this module never calls PLINK: what it
    consumes is the coordinate frame, and routing a stub subprocess in front of it would
    test M5.4 again.
    """
    scored = n_markers if scored is None else scored
    return Projection(
        coordinates=coordinates,
        n_scored_alleles=2 * scored,
        n_reference_markers=n_markers,
        n_components=n_components,
        reference=reference,
        sscore=Path("unused.sscore"),
        plink=None,  # type: ignore[arg-type]
    )


def cluster(
    name: str, centre: tuple[float, ...], *, n: int, spread: float = 1.0, seed: int = 0
) -> list[tuple[str, tuple[float, ...]]]:
    """``n`` samples scattered deterministically around ``centre``.

    A fixed low-discrepancy scatter rather than a random one: every number in this file has
    to be reproducible, and a seeded RNG whose implementation changes between Python
    versions is a test that fails on somebody else's machine for no reason.
    """
    steps = (1.7, 2.3, 3.1, 4.7)
    out: list[tuple[str, tuple[float, ...]]] = []
    for i in range(n):
        # The same magnitude on every axis, at different frequencies, so the scatter is
        # decorrelated between components without any axis being systematically tighter --
        # which is what lets a test say something about the *scale* the model derives.
        offset = tuple(
            spread * math.sin((i + 1) * steps[axis % len(steps)] + seed)
            for axis in range(len(centre))
        )
        out.append((f"{name}{i:03d}", tuple(c + o for c, o in zip(centre, offset, strict=True))))
    return out


def panel(
    clusters: dict[str, tuple[float, ...]],
    *,
    n: int = 60,
    spread: float = 1.0,
    regions: dict[str, str] | None = None,
) -> tuple[pl.DataFrame, PopulationLabels]:
    """A projected panel plus its labels, one cluster per population."""
    ids: list[str] = []
    rows: list[tuple[float, ...]] = []
    populations: list[str] = []
    for seed, (population, centre) in enumerate(clusters.items()):
        for sample_id, point in cluster(population, centre, n=n, spread=spread, seed=seed):
            ids.append(sample_id)
            rows.append(point)
            populations.append(population)
    coordinates = pl.DataFrame(
        {"sample_id": ids, **{name: [row[i] for row in rows] for i, name in enumerate(PCS)}}
    )
    region_of = regions or {}
    labels = PopulationLabels(
        frame=pl.DataFrame(
            {
                "sample_id": ids,
                "population": populations,
                "region": [region_of.get(p, "REG") for p in populations],
            }
        ),
        source="test.panel",
    )
    return coordinates, labels


def sample_at(point: tuple[float, ...], *, sample_id: str = "SAMPLE") -> pl.DataFrame:
    return pl.DataFrame(
        {"sample_id": [sample_id], **{name: [point[i]] for i, name in enumerate(PCS)}}
    )


FOUR_CORNERS: dict[str, tuple[float, ...]] = {
    "AAA": (0.0, 0.0, 0.0, 0.0),
    "BBB": (40.0, 0.0, 0.0, 0.0),
    "CCC": (0.0, 40.0, 0.0, 0.0),
    "DDD": (0.0, 0.0, 40.0, 0.0),
}


def built(**kwargs: object) -> tuple[PopulationModel, pl.DataFrame]:
    coordinates, labels = panel(FOUR_CORNERS, **kwargs)  # type: ignore[arg-type]
    return build_population_model(projection(coordinates), labels), coordinates


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def write_labels(
    tmp_path: Path, rows: list[tuple[str, str, str]], *, header: str | None = None
) -> Path:
    path = tmp_path / "samples.panel"
    lines = [header if header is not None else "sample\tpop\tsuper_pop\tgender\t\t"]
    lines += [f"{s}\t{p}\t{r}\tmale" for s, p, r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_published_panel_files_trailing_empty_columns_do_not_shift_the_read(
    tmp_path: Path,
) -> None:
    """The real ``integrated_call_samples`` header ends in two empty column names. Counting
    fields would be a way to read the wrong one, so the columns are found by name."""
    path = write_labels(tmp_path, [("HG1", "GBR", "EUR"), ("HG2", "YRI", "AFR")])

    labels = read_population_labels(path)

    assert labels.n_samples == 2
    assert labels.populations == frozenset({"GBR", "YRI"})
    assert labels.regions == {"GBR": "EUR", "YRI": "AFR"}
    assert labels.source == "samples.panel"


def test_a_file_without_the_population_columns_is_refused(tmp_path: Path) -> None:
    path = write_labels(tmp_path, [("HG1", "GBR", "EUR")], header="sample\tancestry\tgender")

    with pytest.raises(PopulationsError, match="not a 1000 Genomes sample panel"):
        read_population_labels(path)


def test_a_sample_named_twice_is_refused_rather_than_double_weighted(tmp_path: Path) -> None:
    """A repeated row does not fail anything downstream; it quietly gives one individual two
    votes in a centroid."""
    path = write_labels(tmp_path, [("HG1", "GBR", "EUR"), ("HG1", "GBR", "EUR")])

    with pytest.raises(PopulationsError, match="more than once"):
        read_population_labels(path)


def test_a_truncated_row_is_refused_rather_than_padded(tmp_path: Path) -> None:
    path = tmp_path / "short.panel"
    path.write_text("sample\tpop\tsuper_pop\nHG1\tGBR\tEUR\nHG2\tGBR\n", encoding="utf-8")

    with pytest.raises(PopulationsError, match="malformed"):
        read_population_labels(path)


def test_an_empty_label_file_says_so(tmp_path: Path) -> None:
    path = tmp_path / "empty.panel"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(PopulationsError, match="empty"):
        read_population_labels(path)


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def test_the_model_holds_one_centroid_per_population(tmp_path: Path) -> None:
    model, _coords = built()

    assert model.n_populations == 4
    assert model.populations == ("AAA", "BBB", "CCC", "DDD")
    assert model.n_panel_samples == 240
    assert model.n_components == K


def test_coordinates_are_scaled_by_within_population_spread_not_total_spread() -> None:
    """The scale has to cancel PLINK's unasserted constant, and it has to be the *within*
    spread: the total spread on an axis is mostly the separation between populations, so
    dividing by it would shrink exactly the axis doing the separating.

    Here the clusters are 40 apart on PC1-PC3 and identical on PC4, with a scatter of the
    same size on every axis. A within-population scale is therefore near-equal across all
    four components; a total-variance scale would be an order of magnitude larger on the
    three separating ones.
    """
    model, _coords = built()

    assert max(model.scale) / min(model.scale) < 3.0
    assert all(value < 2.0 for value in model.scale)


def test_a_scale_of_zero_on_some_axis_is_refused_rather_than_dividing_by_it() -> None:
    """A component constant within every population is a component the projection and the
    reference disagree about, and it would otherwise be a division by zero."""
    coordinates, labels = panel(FOUR_CORNERS, spread=0.0)

    with pytest.raises(PopulationsError, match="no usable within-population variation"):
        build_population_model(projection(coordinates), labels)


def test_the_threshold_is_read_off_the_panel_rather_than_set() -> None:
    """It is the quantile of the panel's own members' fit to their nearest population, so a
    tighter panel gets a tighter bar without anybody editing a number."""
    tight, _ = built(spread=0.5)
    loose, _ = built(spread=3.0)

    assert tight.decline_threshold > 0
    assert loose.decline_threshold > 0
    # Both are in units of each panel's own radius, so they land in the same region -- which
    # is the point of expressing the bar as a quantile rather than as a distance.
    assert 1.0 < tight.decline_threshold < 6.0
    assert 1.0 < loose.decline_threshold < 6.0


def test_the_calibration_ranks_on_distance_not_on_fit() -> None:
    """``place_many``'s copy of the rank-by-distance rule is covered; the calibration path's
    copy was not, because four equal-radius clusters cannot express the failure. Ranked on
    fit, a diffuse population attracts anything unusual -- which is how a held-out Finn's
    nearest population comes back as MXL on the real panel.

    The panel here is built so the two rankings give thresholds an order of magnitude apart.
    ``WIDE`` is diffuse and sits close to the very tight ``TIGHT``, so most ``WIDE`` members
    are nearest ``TIGHT`` *by distance* while fitting ``WIDE`` far better. Ranked on
    distance they are scored against ``TIGHT``'s tiny radius and the bar lands around 33;
    ranked on fit they would be scored against ``WIDE``'s own radius and it would collapse
    toward 1. Either way the suite stayed green before, because nothing asserted the value.
    """
    rows = (
        cluster("TIGHT", (0.0, 0.0, 0.0, 0.0), n=40, spread=0.3, seed=1)
        + cluster("WIDE", (6.0, 0.0, 0.0, 0.0), n=40, spread=8.0, seed=2)
        + cluster("FAR", (60.0, 0.0, 0.0, 0.0), n=40, spread=1.0, seed=3)
    )
    coordinates = pl.DataFrame(
        {
            "sample_id": [name for name, _ in rows],
            **{pc: [point[i] for _n, point in rows] for i, pc in enumerate(PCS)},
        }
    )
    labels = PopulationLabels(
        frame=pl.DataFrame(
            {
                "sample_id": [name for name, _ in rows],
                "population": [name[:-3] for name, _ in rows],
                "region": ["REG"] * len(rows),
            }
        ),
        source="test.panel",
    )

    model = build_population_model(projection(coordinates), labels, min_population_samples=20)

    assert model.radius("WIDE") > model.radius("TIGHT") * 10
    # Distance-ranked. Fit-ranked calibration puts this near 1.
    assert model.decline_threshold > 10.0


def test_a_nan_coordinate_is_refused_rather_than_scaled_by() -> None:
    """``sd <= 0`` is false for NaN, because every comparison against NaN is. Written that
    way, one NaN anywhere in the panel makes the scale NaN, then the threshold NaN, then
    every radius NaN -- and the model builds without an error and refuses 100% of samples
    forever, reporting "nan standard deviations" on every card it touches."""
    coordinates, labels = panel(FOUR_CORNERS, n=25)
    poisoned = coordinates.with_columns(
        pl.when(pl.int_range(pl.len()) == 3)
        .then(float("nan"))
        .otherwise(pl.col("PC1"))
        .alias("PC1")
    )

    with pytest.raises(PopulationsError, match="no usable within-population variation"):
        build_population_model(projection(poisoned), labels)


def test_the_declared_quantile_is_what_the_threshold_is_taken_at() -> None:
    """Neutering check: a threshold taken at a different quantile passes every other test in
    this file, because they all place samples far outside the panel or well inside it."""
    coordinates, labels = panel(FOUR_CORNERS, n=200)
    strict = build_population_model(projection(coordinates), labels, quantile=0.5)
    default = build_population_model(projection(coordinates), labels)

    assert strict.decline_threshold < default.decline_threshold
    assert DECLINE_QUANTILE == 0.995


def test_the_refusal_quotes_the_bar_this_model_was_actually_built_with() -> None:
    """The sentence read the module constant rather than the model's own quantile, so a
    model built at the median announced "the bar is 1.00, measured as the 99.5% point" --
    a number and a provenance that never went together."""
    coordinates, labels = panel(FOUR_CORNERS, n=200)
    model = build_population_model(projection(coordinates), labels, quantile=0.5)

    placement = place(projection(sample_at((13.0, 13.0, 13.0, 0.0))), model)

    assert model.quantile == 0.5
    assert "50.0% point" in placement.declined_because
    assert "99.5%" not in placement.declined_because


def test_the_number_of_members_beyond_the_bar_is_reported() -> None:
    """It says how well-determined the bar is: on a small panel the same quantile lands on
    the largest observed fit and this reads 0, meaning the bar is one unusual sample away
    from moving. Replacing the count with a constant 0 passed the whole suite."""
    coordinates, labels = panel(FOUR_CORNERS, n=200)
    model = build_population_model(projection(coordinates), labels)

    placed = place_many(model, coordinates)
    beyond = sum(1 for p in placed if p.nearest.fit > model.decline_threshold)

    assert model.n_beyond_threshold > 0
    assert model.n_beyond_threshold == pytest.approx(beyond, abs=2)


@pytest.mark.parametrize("quantile", [0.0, 1.0, -0.1, 1.5])
def test_an_impossible_quantile_is_refused(quantile: float) -> None:
    coordinates, labels = panel(FOUR_CORNERS)

    with pytest.raises(PopulationsError, match="strictly between"):
        build_population_model(projection(coordinates), labels, quantile=quantile)


def test_a_panel_sample_with_no_population_is_refused(tmp_path: Path) -> None:
    """A centroid built from whoever happened to be labelled is a centroid of that, and
    nothing about the result would look wrong."""
    coordinates, labels = panel(FOUR_CORNERS)
    thinned = PopulationLabels(frame=labels.frame.head(10), source=labels.source)

    with pytest.raises(PopulationsError, match="have no population"):
        build_population_model(projection(coordinates), thinned)


def test_a_population_too_small_to_have_a_spread_is_dropped_and_reported() -> None:
    """SGDP's public subset averages about two samples per population. Left in, each of
    those becomes a tight, arbitrary target that a sample can be confidently named to."""
    clusters = dict(FOUR_CORNERS)
    coordinates, labels = panel(clusters)
    tiny = pl.DataFrame(
        {
            "sample_id": ["TINY0", "TINY1"],
            **{name: [1.0, 1.1] for name in PCS},
        }
    )
    coordinates = pl.concat([coordinates, tiny])
    frame = pl.concat(
        [
            labels.frame,
            pl.DataFrame(
                {
                    "sample_id": ["TINY0", "TINY1"],
                    "population": ["EEE", "EEE"],
                    "region": ["REG", "REG"],
                }
            ),
        ]
    )

    model = build_population_model(
        projection(coordinates), PopulationLabels(frame=frame, source="test.panel")
    )

    assert model.dropped_populations == {"EEE": 2}
    assert "EEE" not in model.populations
    assert MIN_POPULATION_SAMPLES > 2


def test_a_panel_of_one_population_is_refused_because_nearest_means_nothing() -> None:
    coordinates, labels = panel({"AAA": (0.0, 0.0, 0.0, 0.0)})

    with pytest.raises(PopulationsError, match="before 'nearest' means anything"):
        build_population_model(projection(coordinates), labels)


def test_a_projection_missing_a_component_column_says_which() -> None:
    coordinates, labels = panel(FOUR_CORNERS)

    with pytest.raises(PopulationsError, match="PC4"):
        build_population_model(projection(coordinates.drop("PC4")), labels)


def test_the_radius_is_the_median_of_the_populations_own_members() -> None:
    model, _coords = built()

    for population in model.populations:
        distances = model.own_distances[population]
        assert len(distances) == 60
        assert list(distances) == sorted(distances)
        assert model.radius(population) == pytest.approx((distances[29] + distances[30]) / 2)


def test_the_leave_one_out_correction_is_computed_against_hand_arithmetic() -> None:
    """A member helped define its own centroid, so its raw distance to it is biased low by
    exactly n/(n-1). Asserted against a hand-computed value rather than against a ratio
    between two panels: the ratio version tested a 3.65% signal against a 15% tolerance,
    with the fixture's own scatter already larger than the effect, and deleting the
    correction outright passed it.

    Nothing else can see the correction either -- it cancels in ``fit = distance / radius``
    for a sample's own population, so the threshold is identical with and without it. Its
    only observable effect is on ``own_distances``, which is what this reads.
    """
    members = {
        "AAA": [(0.0, 0.0, 0.0, 0.0), (3.0, 1.0, 2.0, 1.0), (6.0, 2.0, 1.0, 3.0)],
        "BBB": [(40.0, 0.0, 1.0, 0.0), (43.0, 2.0, 0.0, 2.0), (46.0, 1.0, 2.0, 1.0)],
    }
    names = [f"{pop}{i}" for pop in members for i in range(3)]
    points = [point for pop in members for point in members[pop]]
    coordinates = pl.DataFrame(
        {"sample_id": names, **{pc: [p[i] for p in points] for i, pc in enumerate(PCS)}}
    )
    labels = PopulationLabels(
        frame=pl.DataFrame(
            {
                "sample_id": names,
                "population": [pop for pop in members for _ in range(3)],
                "region": ["REG"] * len(names),
            }
        ),
        source="test.panel",
    )
    model = build_population_model(
        projection(coordinates), labels, min_population_samples=3, quantile=0.9
    )

    own = members["AAA"]
    centroid = [sum(point[axis] for point in own) / len(own) for axis in range(K)]
    # The uncorrected distance, then the factor the correction is defined to be: with three
    # members, a member pulled its own centroid by a third, so n/(n-1) = 3/2.
    raw = [
        math.sqrt(
            sum(((point[axis] - centroid[axis]) / model.scale[axis]) ** 2 for axis in range(K))
        )
        for point in own
    ]
    corrected = sorted(value * 3 / 2 for value in raw)

    assert list(model.own_distances["AAA"]) == pytest.approx(corrected, rel=1e-9)
    assert model.radius("AAA") == pytest.approx(corrected[1], rel=1e-9)


def test_the_correction_is_not_applied_to_a_population_the_sample_is_not_from() -> None:
    """The other twenty-five centroids owe this sample nothing, so correcting against them
    too would inflate every distance and move the threshold for no reason. An unconditional
    correction in the calibration path passed the entire suite."""
    small, _ = built(n=25)

    placement = place(projection(sample_at((0.0, 0.0, 0.0, 0.0))), small)
    far = next(fit for fit in placement.fits if fit.population == "BBB")

    # A placed sample belongs to no population, so every distance it reports is uncorrected.
    # Recompute BBB's by hand from the stored centroid and confirm no n/(n-1) crept in.
    centroid = small.centroids.filter(pl.col("population") == "BBB")
    expected = math.sqrt(sum(float(centroid.get_column(pc)[0]) ** 2 for pc in PCS))
    assert far.distance == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# Placing, and refusing to
# ---------------------------------------------------------------------------


def test_a_sample_inside_a_cluster_is_named_that_population() -> None:
    model, _coords = built()

    placement = place(projection(sample_at((0.2, 0.1, 0.0, 0.0))), model)

    assert placement.population == "AAA"
    assert placement.region == "REG"
    assert placement.named is True
    # The raw projection coordinates, not the scaled ones a distance is measured in. A card
    # printing these beside a distance would otherwise be mixing two unit systems.
    assert placement.coordinates == pytest.approx((0.2, 0.1, 0.0, 0.0))
    assert placement.declined_because == ""
    assert placement.nearest.population == "AAA"


def test_a_sample_between_every_cluster_is_named_nothing() -> None:
    """The Lebanese case, which is the whole milestone: a sample that sits *between* the
    panel's clusters and belongs to none of them. A nearest-neighbour report does not return
    "no match" -- it returns the least-bad label with a distance attached, and the distance
    is what makes the label read as an answer."""
    model, _coords = built()

    placement = place(projection(sample_at((13.0, 13.0, 13.0, 0.0))), model)

    assert placement.population is None
    assert placement.region is None
    assert placement.named is False
    assert placement.call is None


def test_the_refusal_still_names_the_nearest_population_and_its_distance() -> None:
    """Withholding those would be a different failure. The reader is owed what the panel did
    find and why it was not enough -- what they must not be given is the name offered as an
    answer with a caveat attached."""
    model, _coords = built()

    placement = place(projection(sample_at((13.0, 13.0, 13.0, 0.0))), model)

    assert placement.nearest.population in FOUR_CORNERS
    assert placement.nearest.distance > 0
    reason = placement.declined_because
    assert placement.nearest.population in reason
    assert "No population is named" in reason
    assert f"{model.decline_threshold:.2f}" in reason


def test_every_population_is_reported_ranked_by_distance() -> None:
    """ "Nearest reference populations" is plural in the milestone, and a card that shows one
    cannot show that the second was nearly as good."""
    model, _coords = built()

    placement = place(projection(sample_at((1.0, 0.0, 0.0, 0.0))), model)

    assert len(placement.fits) == 4
    assert {fit.population for fit in placement.fits} == set(FOUR_CORNERS)
    assert placement.fits[0].population == "AAA"
    assert placement.fits == tuple(sorted(placement.fits, key=lambda fit: fit.distance))


def test_the_call_is_the_nearest_population_that_fits_not_merely_the_nearest() -> None:
    """Measured on held-out 1000 Genomes populations: requiring the very closest to fit
    refuses 17% of ACB, 23% of PJL and 19% of CHS samples, each of which has a good sibling
    one step down the list, and refuses nothing extra where refusing is the point.

    Here ``BBB`` is a tight cluster and ``CCC`` a looser one a little further along the same
    axis; a sample just outside ``BBB`` is nearest to it, does not fit it, and does fit
    ``CCC``. The spreads differ by a factor of four rather than a factor of thirty, because
    a panel whose populations differ that wildly makes the pooled scale meaningless and the
    test would then be about the pathology rather than about the rule.
    """
    rows = (
        cluster("AAA", (0.0, 0.0, 0.0, 0.0), n=120, spread=1.0, seed=3)
        + cluster("BBB", (30.0, 0.0, 0.0, 0.0), n=120, spread=0.4, seed=1)
        + cluster("CCC", (38.0, 0.0, 0.0, 0.0), n=120, spread=1.6, seed=2)
    )
    coordinates = pl.DataFrame(
        {
            "sample_id": [name for name, _ in rows],
            **{pc: [point[i] for _n, point in rows] for i, pc in enumerate(PCS)},
        }
    )
    labels = PopulationLabels(
        frame=pl.DataFrame(
            {
                "sample_id": [name for name, _ in rows],
                "population": [name[:3] for name, _ in rows],
                "region": ["REG"] * len(rows),
            }
        ),
        source="test.panel",
    )
    # The bar is set explicitly rather than calibrated, because what is under test is the
    # rule that consumes it. Calibrating a 360-sample synthetic panel puts the 99.5% point
    # at 1.4, which refuses both populations and would make this a test of that instead.
    model = replace(build_population_model(projection(coordinates), labels), decline_threshold=3.0)

    placement = place(projection(sample_at((33.0, 0.0, 0.0, 0.0))), model)

    assert placement.nearest.population == "BBB"
    assert placement.nearest.fit > model.decline_threshold
    assert placement.population == "CCC"
    assert placement.call is not None and placement.call.population == "CCC"


def test_the_percentile_says_where_the_sample_falls_in_that_populations_own_spread() -> None:
    """ "Farther out than 99.8% of Tuscans" is a claim about a distribution, so it is read
    off one rather than derived from the radius."""
    model, _coords = built()

    inside = place(projection(sample_at((0.0, 0.0, 0.0, 0.0))), model)
    outside = place(projection(sample_at((13.0, 13.0, 13.0, 0.0))), model)

    assert inside.nearest.percentile < 0.5
    assert outside.nearest.percentile == 1.0


def test_fit_is_one_for_a_typical_member_of_a_population() -> None:
    """The property the threshold is expressed against: the median own-member sits at 1."""
    model, coordinates = built()

    placed = place_many(model, coordinates)
    fits = sorted(p.call.fit for p in placed if p.call is not None and p.call.population == "AAA")

    assert fits[len(fits) // 2] == pytest.approx(1.0, abs=0.15)


def test_coverage_travels_with_the_placement_without_changing_the_decision() -> None:
    """A sparsely-called sample's coordinates are noisier rather than biased, and noise
    already inflates distances -- so this module declines more readily on its own. Scaling
    the threshold by coverage as well would correct for the same thing twice."""
    model, _coords = built()
    point = (0.2, 0.1, 0.0, 0.0)

    full = place(projection(sample_at(point), n_markers=50_000, scored=50_000), model)
    thin = place(projection(sample_at(point), n_markers=50_000, scored=30_000), model)

    assert full.coverage == pytest.approx(1.0)
    assert thin.coverage == pytest.approx(0.6)
    assert full.n_scored_markers == 50_000
    assert thin.n_scored_markers == 30_000
    assert full.population == thin.population


# ---------------------------------------------------------------------------
# Refusals that keep two spaces from being compared
# ---------------------------------------------------------------------------


def test_a_sample_projected_against_a_different_reference_pca_is_refused() -> None:
    """Two projections against different loadings are coordinates in different spaces, and
    nothing about them looks wrong: same columns, same count, same magnitude, and they plot.
    This is the M5.4 variant-ID join's failure mode moved up one milestone."""
    model, _coords = built()

    with pytest.raises(PopulationsError, match="different eigenvector sets"):
        place(projection(sample_at((0.2, 0.1, 0.0, 0.0)), reference="refpca-other"), model)


def test_a_component_count_mismatch_is_refused() -> None:
    model, _coords = built()

    with pytest.raises(PopulationsError, match="component\\(s\\) and the model"):
        place(projection(sample_at((0.2, 0.1, 0.0, 0.0)), n_components=K + 1), model)


def test_place_takes_one_sample_and_says_so_when_given_more() -> None:
    model, coordinates = built()

    with pytest.raises(PopulationsError, match="single sample"):
        place(projection(coordinates), model)


def test_a_repeated_sample_id_is_refused_when_placing() -> None:
    """A ``.sscore`` reports IID alone and PLINK permits a repeated IID under distinct FIDs.
    Two individuals sharing one collapse into a single ``Placement`` whose ``fits`` lists
    every population twice and whose coordinates are whichever row survived -- the other
    person gone, with nothing raised. The label side has guarded this since M5.5; this is
    the same guard on the projection side."""
    model, _coords = built()
    duplicated = pl.DataFrame(
        {
            "sample_id": ["dup", "dup"],
            **{pc: [0.0, 40.0] if pc == "PC1" else [0.0, 0.0] for pc in PCS},
        }
    )

    with pytest.raises(PopulationsError, match="more than once"):
        place_many(model, duplicated)


def test_a_repeated_sample_id_is_refused_when_building_the_model() -> None:
    """On this side the repetition pulls a centroid toward the duplicated sample and
    inflates ``n``, which shrinks that population's leave-one-out correction."""
    coordinates, labels = panel(FOUR_CORNERS)
    doubled = pl.concat([coordinates, coordinates.head(1)])
    frame = pl.concat([labels.frame, labels.frame.head(1)])

    with pytest.raises(PopulationsError, match="more than once"):
        build_population_model(
            projection(doubled), PopulationLabels(frame=frame, source=labels.source)
        )


def test_a_header_only_label_file_is_refused_by_name(tmp_path: Path) -> None:
    """A truncated download looks exactly like this. Left alone it reached a raw polars
    ``SchemaError`` about null join-key dtypes, three frames away from the cause."""
    path = tmp_path / "truncated.panel"
    path.write_text("sample\tpop\tsuper_pop\tgender\n", encoding="utf-8")

    with pytest.raises(PopulationsError, match="header and no samples"):
        read_population_labels(path)


def test_place_many_names_the_missing_coordinate_column() -> None:
    model, coordinates = built()

    with pytest.raises(PopulationsError, match="PC3"):
        place_many(model, coordinates.drop("PC3"))


# ---------------------------------------------------------------------------
# What the panel cannot answer for
# ---------------------------------------------------------------------------


def test_the_coverage_statement_attaches_only_to_the_panel_it_describes() -> None:
    """AGENTS.md 5.2's ``refs probe`` lesson, pointed at a different declared fact: a
    statement nothing re-verifies decays quietly and stays attached. Widening the panel must
    detach this rather than leave it describing a panel that has changed."""
    assert coverage_for(THOUSAND_GENOMES_COVERAGE.populations) is THOUSAND_GENOMES_COVERAGE
    assert coverage_for(THOUSAND_GENOMES_COVERAGE.populations | {"HGDP_YAKUT"}) is None
    assert coverage_for(THOUSAND_GENOMES_COVERAGE.populations - {"FIN"}) is None
    assert coverage_for(frozenset()) is None


def test_a_panel_nobody_has_written_gaps_for_reports_none_rather_than_no_gaps() -> None:
    """``None`` and an empty tuple would render identically if a caller were careless, and
    one of those readings is "this panel covers the world"."""
    model, _coords = built()

    assert model.coverage is None

    placement = place(projection(sample_at((0.2, 0.1, 0.0, 0.0))), model)
    assert placement.panel_coverage is None


def test_the_recorded_gaps_are_the_regions_agents_md_names() -> None:
    """The list is a statement about 1000 Genomes taken from AGENTS.md 4.6 and 5.4. If it
    ever disagrees with them, one of the two is wrong and this is where it surfaces."""
    regions = " | ".join(gap.region for gap in THOUSAND_GENOMES_COVERAGE.gaps).lower()

    for expected in ("middle east", "north africa", "oceania", "central asia", "siberia"):
        assert expected in regions
    assert "indigenous american" in regions
    assert "khoisan" in regions
    assert len(THOUSAND_GENOMES_COVERAGE.populations) == 26
    assert all(gap.note for gap in THOUSAND_GENOMES_COVERAGE.gaps)


def test_the_coverage_statement_reaches_the_placement(tmp_path: Path) -> None:
    coordinates, labels = panel(
        dict(zip(sorted(THOUSAND_GENOMES_COVERAGE.populations), _spread_out(26), strict=True)),
        n=25,
    )
    model = build_population_model(projection(coordinates), labels)

    placement = place(projection(sample_at((0.2, 0.1, 0.0, 0.0))), model)

    assert placement.panel_coverage is THOUSAND_GENOMES_COVERAGE
    assert len(placement.panel_coverage.gaps) == 5


def _spread_out(n: int) -> list[tuple[float, ...]]:
    """``n`` well-separated centres, so a synthetic panel can carry real population codes."""
    return [(40.0 * (i % 5), 40.0 * (i // 5), 13.0 * (i % 3), 7.0 * (i % 7)) for i in range(n)]


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_the_placement_repr_carries_neither_coordinates_nor_the_call() -> None:
    """A ranked population list is an ancestry inference about a person, which AGENTS.md 1.1
    names in the same breath as PCA coordinates. This is the object a caller logs."""
    model, _coords = built()

    placement = place(projection(sample_at((0.2, 0.1, 0.0, 0.0))), model)
    text = repr(placement)

    assert "AAA" not in text
    assert "0.2" not in text
    assert "n_populations" in text


@pytest.mark.privacy
def test_a_population_fit_repr_carries_neither_the_population_nor_the_distance() -> None:
    """``Placement`` withholds the call, and then hands out objects that publish it.

    ``fits`` is ordered nearest-first and ``nearest`` returns the first of them, so
    ``repr(placement.nearest)`` naming a population *is* the ancestry call, in a log line,
    one attribute access around the withholding. The first version of ``_repr_fields`` here
    listed ``population`` and so leaked exactly what the class docstring forbids.
    """
    model, _coords = built()

    fit = place(projection(sample_at((0.2, 0.1, 0.0, 0.0))), model).nearest

    assert "AAA" not in repr(fit)
    assert str(round(fit.distance, 3)) not in repr(fit)
    assert "n_samples" in repr(fit)


@pytest.mark.privacy
def test_the_ranked_fits_cannot_be_printed_as_a_population_ranking() -> None:
    """The collection, not just one element -- printing the tuple is the whole call."""
    model, _coords = built()

    text = repr(place(projection(sample_at((0.2, 0.1, 0.0, 0.0))), model).fits)

    assert not [name for name in FOUR_CORNERS if name in text]


def test_the_coverage_statement_describes_the_populations_that_survived_the_floor() -> None:
    """A population dropped for being too small is one this model cannot name, so a gap list
    keyed to the wider label set would stay attached to a panel it is no longer true of --
    the decay ``coverage_for``'s identity check exists to prevent, reintroduced by feeding it
    the wrong set."""
    centres = dict(zip(sorted(THOUSAND_GENOMES_COVERAGE.populations), _spread_out(26), strict=True))
    coordinates, labels = panel(centres, n=25)
    # One population drops below the floor; the label file still names all 26.
    doomed = sorted(THOUSAND_GENOMES_COVERAGE.populations)[0]
    keep = labels.frame.filter(
        (pl.col("population") != doomed)
        | (
            pl.col("sample_id").is_in(
                labels.frame.filter(pl.col("population") == doomed)
                .get_column("sample_id")
                .to_list()[:3]
            )
        )
    )
    coordinates = coordinates.filter(
        pl.col("sample_id").is_in(keep.get_column("sample_id").to_list())
    )

    model = build_population_model(
        projection(coordinates), PopulationLabels(frame=keep, source=labels.source)
    )

    assert model.dropped_populations == {doomed: 3}
    assert model.coverage is None, "the 26-population statement must not survive losing one"
