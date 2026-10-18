"""M11.3 ancestry-driven HIBAG classifier selection and per-call observation ceilings."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from genetics.ancestry.context import AncestryContext, PopulationResult
from genetics.ancestry.populations import Placement, PopulationFit
from genetics.engine.confidence import (
    HLA_PUBLISHED_CALL_THRESHOLD,
    ConfidenceError,
    ConfidenceTier,
    calculate_hla_call_reliability,
)
from genetics.hla import selection
from genetics.hla.models import POPULATIONS, HLAError
from genetics.pgs.portability import THOUSAND_GENOMES_CATEGORY

THRESHOLD = 2.0


def result(
    population: str,
    region: str,
    *,
    named: bool = True,
    others: tuple[tuple[str, float], ...] = (),
) -> PopulationResult:
    """A real M5 placement object: the selection must parse what M5.8 actually writes."""
    fits = sorted(
        [
            PopulationFit(population, region, 30, 1.0 if named else 3.0, 1.0, 0.5),
            *(PopulationFit(name, region, 30, fit, 1.0, 0.5) for name, fit in others),
        ],
        key=lambda fit: fit.distance,
    )
    return PopulationResult(
        placement=Placement(
            sample_id="SAMPLE",
            coordinates=(0.1, 0.2),
            fits=tuple(fits),
            population=population if named else None,
            declined_because="" if named else "Synthetic panel does not fit.",
            decline_threshold=THRESHOLD,
            coverage=0.98,
            n_scored_markers=100,
            n_reference_markers=100,
            panel_coverage=None,
            labels_source="synthetic.panel",
            n_panel_samples=60,
        ),
        reference="synthetic-pca",
        reference_markers=100,
        n_components=2,
    )


def ancestry(
    population: str = "GBR",
    *,
    aadr: str = "placed",
    thousand_genomes: str = "placed",
    others: tuple[tuple[str, float], ...] = (("CEU", 1.5), ("JPT", 9.0)),
) -> dict[str, Any]:
    base = AncestryContext.not_run("Synthetic acceptance")
    gate = (
        result("Synthetic_Human_Origins", "Synthetic_Region", named=aadr == "placed")
        if aadr != "not_run"
        else PopulationResult(not_run_reason="Synthetic AADR absent.")
    )
    tg = (
        result(population, "EUR", named=thousand_genomes == "placed", others=others)
        if thousand_genomes != "not_run"
        else PopulationResult(not_run_reason="Synthetic 1000 Genomes absent.")
    )
    return AncestryContext(
        population=gate, mt=base.mt, y=base.y, ancient=base.ancient, reference_population=tg
    ).to_dict()


EXPECTED = {
    "European": ("european", 1.0),
    "East Asian": ("asian", 1.0),
    "South Asian": ("asian", None),
    "Hispanic or Latin American": ("hispanic", 1.0),
    "African American or Afro-Caribbean": ("african", 1.0),
    "Sub-Saharan African": ("african", 1.0),
    "South East Asian": (None, None),
}


@pytest.mark.parametrize("population", sorted(THOUSAND_GENOMES_CATEGORY))
def test_every_1000_genomes_population_maps_through_its_cited_category(population: str) -> None:
    record = selection.select(ancestry(population, others=()))
    classifier, match = EXPECTED[THOUSAND_GENOMES_CATEGORY[population]]
    assert record["automatic_classifier"] == record["classifier"] == classifier
    assert record["ancestry_match"] == match
    assert record["status"] == ("selected" if classifier else "unsupported")
    assert record["basis"] == ("ancestry" if classifier else None)
    assert record["category"]["morales_category"] == THOUSAND_GENOMES_CATEGORY[population]
    assert record["category"]["training"] == (
        selection.TRAINING[classifier] if classifier else None
    )
    selection.validate(record)


def test_mapping_covers_only_published_classifiers_and_cited_categories() -> None:
    assert set(selection.TRAINING) == set(POPULATIONS)
    assert {c for c, _ in selection.CATEGORY_CLASSIFIER.values()} == set(POPULATIONS)
    assert set(selection.CATEGORY_CLASSIFIER) < set(THOUSAND_GENOMES_CATEGORY.values())


@pytest.mark.parametrize(
    ("aadr", "thousand_genomes", "status"),
    [
        ("declined", "placed", "declined"),
        ("placed", "declined", "declined"),
        ("declined", "not_run", "declined"),
        ("not_run", "placed", "not_run"),
        ("placed", "not_run", "not_run"),
        ("not_run", "not_run", "not_run"),
    ],
)
def test_missing_or_declined_placement_never_forces_a_model(
    aadr: str, thousand_genomes: str, status: str
) -> None:
    record = selection.select(ancestry(aadr=aadr, thousand_genomes=thousand_genomes))
    assert record["status"] == status
    assert record["classifier"] is None and record["automatic_classifier"] is None
    assert record["ancestry_match"] is None and record["basis"] is None
    assert "Synthetic" in record["reason"]
    selection.validate(record)


def test_absent_ancestry_and_historical_bundles_read_as_not_run() -> None:
    for raw in (None, {"population": ancestry()["population"]}):
        record = selection.select(raw)
        assert record["status"] == "not_run" and record["classifier"] is None
        selection.validate(record)


@pytest.mark.parametrize(
    ("population", "others", "status", "candidates"),
    [
        ("PUR", (("IBS", 1.9),), "ambiguous", ["european", "hispanic"]),
        ("GIH", (("KHV", 1.2),), "ambiguous", ["asian", "none"]),
        ("PUR", (("IBS", 2.1),), "selected", ["hispanic"]),
        ("GBR", (("CEU", 1.5), ("FIN", 1.9)), "selected", ["european"]),
    ],
)
def test_admissible_alternatives_that_disagree_on_the_classifier_decline(
    population: str, others: tuple[tuple[str, float], ...], status: str, candidates: list[str]
) -> None:
    record = selection.select(ancestry(population, others=others))
    assert record["status"] == status and record["candidates"] == candidates
    assert (record["classifier"] is None) == (status == "ambiguous")
    selection.validate(record)


def test_uncertainty_is_recorded_without_coordinates() -> None:
    record = selection.select(ancestry())
    uncertainty = record["source"]["thousand_genomes"]["uncertainty"]
    assert uncertainty == {
        "fit": 1.0,
        "decline_threshold": THRESHOLD,
        "margin": THRESHOLD - 1.0,
        "coverage": 0.98,
        "admissible": [{"population": "GBR", "fit": 1.0}, {"population": "CEU", "fit": 1.5}],
    }
    assert "coordinates" not in json.dumps(record)
    assert set(record["source"]["aadr"]) == {"status", "population", "region", "reason"}


@pytest.mark.parametrize(
    ("raw", "requested", "match", "verdict"),
    [
        (lambda: ancestry(), "european", 1.0, "agrees with"),
        (lambda: ancestry(), "african", 0.0, "is not supported by"),
        (lambda: ancestry(aadr="declined"), "european", 0.0, "is not supported by"),
        (lambda: ancestry("KHV", others=()), "asian", 0.0, "is not supported by"),
        (lambda: ancestry(aadr="not_run"), "european", None, "is not established by"),
        (lambda: ancestry("BEB", others=()), "asian", None, "agrees with"),
        (lambda: ancestry("PUR", others=(("IBS", 1.9),)), "european", None, "not established"),
        (lambda: ancestry("PUR", others=(("IBS", 1.9),)), "asian", 0.0, "is not supported by"),
    ],
)
def test_explicit_classifier_runs_and_records_its_ancestry_mismatch(
    raw: Any, requested: str, match: float | None, verdict: str
) -> None:
    record = selection.select(raw(), requested=requested)
    assert record["classifier"] == record["requested_classifier"] == requested
    assert record["basis"] == "explicit" and record["ancestry_match"] == match
    assert verdict in record["reason"]
    selection.validate(record)


def test_unsupported_explicit_classifier_is_refused() -> None:
    with pytest.raises(HLAError, match="opt-in"):
        selection.select(ancestry(), requested="oceanian")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("classifier",), "asian"),
        (("automatic_classifier",), "asian"),
        (("status",), "ambiguous"),
        (("ancestry_match",), 0.0),
        (("basis",), "explicit"),
        (("method",), "invented"),
        (("schema_version",), True),
        (("reason",), "invented"),
        (("candidates",), []),
        (("category", "training"), "invented"),
        (("source", "thousand_genomes", "population"), "JPT"),
        (("source", "thousand_genomes", "uncertainty", "fit"), 0.5),
        (("source", "thousand_genomes", "uncertainty", "margin"), 0.5),
        (("source", "thousand_genomes", "uncertainty", "admissible"), []),
        (("source", "aadr", "status"), "declined"),
        (("source", "aadr", "reason"), "invented"),
        (("extra",), None),
    ],
)
def test_saved_selection_is_rederived_from_its_frozen_placements(
    path: tuple[str, ...], value: Any
) -> None:
    record = selection.select(ancestry())
    broken = copy.deepcopy(record)
    target = broken
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(HLAError):
        selection.validate(broken)


@pytest.mark.parametrize(
    ("mutation"),
    ["placed-no-fits", "nan-fit", "unfit-placement", "bad-status", "placed-with-reason"],
)
def test_malformed_m5_placements_fail_loudly(mutation: str) -> None:
    raw = ancestry()
    tg = raw["reference_population"]
    if mutation == "placed-no-fits":
        tg["fits"] = None
    elif mutation == "nan-fit":
        tg["fits"][0]["fit"] = float("nan")
    elif mutation == "unfit-placement":
        tg["fits"][0]["fit"] = THRESHOLD + 1
    elif mutation == "bad-status":
        tg["status"] = "guessed"
    else:
        tg["reason"] = "A placed sample cannot carry a refusal."
    with pytest.raises(HLAError):
        selection.select(raw)


@pytest.mark.parametrize(
    ("posterior", "coverage", "match", "ceiling", "ceilings"),
    [
        (0.95, 1.0, 1.0, None, ()),
        (0.79, 1.0, 1.0, ConfidenceTier.MODERATE, ("posterior",)),
        (0.59, 1.0, 1.0, ConfidenceTier.LIMITED, ("posterior",)),
        (0.29, 1.0, 1.0, ConfidenceTier.LIKELY_ARTIFACT, ("posterior",)),
        (0.95, 0.49, 1.0, ConfidenceTier.MODERATE, ("marker_coverage",)),
        (0.95, 0.24, 1.0, ConfidenceTier.LIMITED, ("marker_coverage",)),
        (0.95, 1.0, None, ConfidenceTier.STRONG, ("ancestry",)),
        (0.95, 1.0, 0.0, ConfidenceTier.LIMITED, ("ancestry",)),
        (0.79, 0.24, None, ConfidenceTier.LIMITED, ("posterior", "marker_coverage")),
        (0.29, 0.24, 0.0, ConfidenceTier.LIKELY_ARTIFACT, ("posterior",)),
    ],
)
def test_posterior_coverage_and_ancestry_fold_into_one_ceiling(
    posterior: float,
    coverage: float,
    match: float | None,
    ceiling: ConfidenceTier | None,
    ceilings: tuple[str, ...],
) -> None:
    result = calculate_hla_call_reliability(
        posterior=posterior, marker_coverage=coverage, ancestry_match=match
    )
    assert result.ceiling == ceiling and result.ceilings == ceilings
    assert result.meets_published_call_threshold == (posterior >= HLA_PUBLISHED_CALL_THRESHOLD)


def test_published_call_threshold_is_displayed_not_a_filter() -> None:
    at = calculate_hla_call_reliability(posterior=0.5, marker_coverage=1.0, ancestry_match=1.0)
    below = calculate_hla_call_reliability(posterior=0.49, marker_coverage=1.0, ancestry_match=1.0)
    assert at.meets_published_call_threshold and not below.meets_published_call_threshold
    assert at.ceiling == below.ceiling == ConfidenceTier.LIMITED


@pytest.mark.parametrize("bad", [True, -0.1, 1.1, float("nan"), None])
def test_reliability_inputs_are_validated(bad: Any) -> None:
    with pytest.raises(ConfidenceError):
        calculate_hla_call_reliability(posterior=bad, marker_coverage=1.0, ancestry_match=None)
    if bad is not None:
        with pytest.raises(ConfidenceError):
            calculate_hla_call_reliability(posterior=0.9, marker_coverage=1.0, ancestry_match=bad)
