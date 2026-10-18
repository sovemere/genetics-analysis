"""M11.3 ancestry-driven selection of HIBAG's population-specific classifiers.

HIBAG's four published HLARES models are not interchangeable, and choosing one is an
ancestry claim. This module never reads a genotype table: it consumes the run's persisted
M5 placements, so a missing, declined, ambiguous or unsupported placement stays an explicit
refusal instead of becoming the nearest model by default.

**The mapping is cited at both ends, as M9.5's portability mapping is.** The sample's
1000 Genomes population maps to its Morales et al. 2018 category (the table
:mod:`genetics.pgs.portability` already cites), and a category maps to a classifier only
where the publisher's own training description names it (``TRAINING``, quoted from the
HLARES index page and Zheng et al. 2014, DOI 10.1038/tpj.2013.18). *South East Asian*
(KHV) is named by none of them and has no classifier. The Asian model's training is
described as "East & South Asia" without a published split, so a South Asian placement
selects it with an unknown -- not a perfect -- ancestry match.

**Two gates, as for polygenic scores.** The Human Origins (AADR, M5.9) placement covers the
regions 1000 Genomes lacks, so it must have *placed* the sample: a decline there is a
finding that the sample is unrepresented, and a gate that did not run cannot exclude that.
The 1000 Genomes placement then supplies the category. Every other population whose fit is
also within the 1000 Genomes decline threshold is a candidate the placement could not rule
out; when those candidates point at different classifiers (or at none), the choice is
``ambiguous`` and nothing is selected. No second, HLA-specific margin is added on top of the
panel's own measured 99.5% threshold, because that would be an uncalibrated number.

**An explicit classifier is honoured, never hidden** (AGENTS.md 0.1A). It runs, and the
record keeps what the placement supported beside it. Its ``ancestry_match`` is 1 only when
the placement selects the same classifier; a decline, an unsupported category or a
contradicting placement is 0; a placement that was not run, or one that leaves the choice
open, is unknown. The match caps confidence through
:func:`~genetics.engine.confidence.ancestry_ceiling`; it never removes a call.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

from genetics.hla.models import POPULATIONS, HLAError
from genetics.pgs.portability import THOUSAND_GENOMES_CATEGORY

VERSION: Final = 1
METHOD: Final = "m5-aadr-gate-1000g-morales-hlares-training-v1"
STATUSES: Final = frozenset({"selected", "declined", "not_run", "unsupported", "ambiguous"})

TRAINING: Final[dict[str, str]] = {
    # https://hibag.s3.amazonaws.com/hlares_index.html, verified 2026-10-18.
    "european": "HLARES data of European ancestry",
    "asian": "HLARES data of Asian ancestry (East & South Asia) and HapMap CHB+JPT",
    "hispanic": "HLARES data of Hispanic ancestry",
    "african": "African American HLARES data and 60 African parents of HapMap YRI",
}

CATEGORY_CLASSIFIER: Final[dict[str, tuple[str, float | None]]] = {
    # Morales category -> (classifier, ancestry match). 1.0 where the training description
    # names the category; None where it names the region but publishes no share.
    "European": ("european", 1.0),
    "East Asian": ("asian", 1.0),
    "South Asian": ("asian", None),
    "Hispanic or Latin American": ("hispanic", 1.0),
    "African American or Afro-Caribbean": ("african", 1.0),
    "Sub-Saharan African": ("african", 1.0),
}

_AADR = "Human Origins (AADR)"
_TG = "1000 Genomes"


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise HLAError("HLA ancestry selection source is malformed.")
    return value


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise HLAError("HLA ancestry selection uncertainty is malformed.")
    return float(value)


def _placement(raw: Any, label: str) -> dict[str, Any]:
    """Status, name and reason of one M5 placement, validated as M5.8 writes them."""
    if raw is None:
        return {
            "status": "not_run",
            "population": None,
            "region": None,
            "reason": f"No {label} placement was recorded for this run.",
        }
    if not isinstance(raw, Mapping):
        raise HLAError("HLA ancestry selection source is malformed.")
    status = raw.get("status")
    population, region, reason = (_text(raw.get(k)) for k in ("population", "region", "reason"))
    if status == "placed":
        if population is None or region is None or reason is not None:
            raise HLAError("HLA ancestry selection source is malformed.")
    elif status not in {"declined", "not_run"} or population or region or reason is None:
        raise HLAError("HLA ancestry selection source is malformed.")
    return {"status": status, "population": population, "region": region, "reason": reason}


def _uncertainty(raw: Mapping[str, Any], population: str) -> dict[str, Any]:
    """The placement's admission evidence, without its PCA coordinates."""
    fits = raw.get("fits")
    threshold = _number(raw.get("decline_threshold"))
    coverage = _number(raw.get("coverage"))
    if not isinstance(fits, list) or threshold <= 0 or not 0 <= coverage <= 1:
        raise HLAError("HLA ancestry selection needs retained M5 placement uncertainty.")
    admissible = []
    for row in fits:
        if not isinstance(row, Mapping) or not isinstance(row.get("population"), str):
            raise HLAError("HLA ancestry selection uncertainty is malformed.")
        fit = _number(row.get("fit"))
        if fit < 0:
            raise HLAError("HLA ancestry selection uncertainty is malformed.")
        if fit <= threshold:
            admissible.append({"population": row["population"], "fit": fit})
    admissible.sort(key=lambda row: (row["fit"], row["population"]))
    names = [row["population"] for row in admissible]
    if len(set(names)) != len(names) or population not in names:
        raise HLAError("HLA ancestry selection needs the selected M5 population fit.")
    fit = next(row["fit"] for row in admissible if row["population"] == population)
    return {
        "fit": fit,
        "decline_threshold": threshold,
        "margin": threshold - fit,
        "coverage": coverage,
        "admissible": admissible,
    }


def source(ancestry: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The two M5 placements a classifier choice rests on, in compact frozen form.

    ``None`` -- no ancestry handed over at all, as for ``genetics hla inspect`` -- reads as
    both placements not run, which leaves only an explicit classifier usable.
    """
    if ancestry is None:
        ancestry = {}
    if not isinstance(ancestry, Mapping):
        raise HLAError("HLA ancestry selection source is malformed.")
    aadr = _placement(ancestry.get("population"), _AADR)
    raw = ancestry.get("reference_population")
    tg = _placement(raw, _TG)
    tg["uncertainty"] = None
    if tg["status"] == "placed":
        assert isinstance(raw, Mapping) and tg["population"] is not None
        tg["uncertainty"] = _uncertainty(raw, tg["population"])
    return {"aadr": aadr, "thousand_genomes": tg}


def _classifier(population: str) -> tuple[str | None, float | None, str]:
    category = THOUSAND_GENOMES_CATEGORY.get(population)
    if category is None:
        raise HLAError("HLA ancestry selection met an unknown 1000 Genomes population.")
    classifier, match = CATEGORY_CLASSIFIER.get(category, (None, None))
    return classifier, match, category


def _automatic(src: Mapping[str, Any]) -> dict[str, Any]:
    aadr, tg = src["aadr"], src["thousand_genomes"]
    declined = [label for label, part in ((_AADR, aadr), (_TG, tg)) if part["status"] == "declined"]
    absent = [label for label, part in ((_AADR, aadr), (_TG, tg)) if part["status"] == "not_run"]
    out: dict[str, Any] = {"classifier": None, "match": None, "category": None, "candidates": []}
    if declined:
        part = aadr if declined[0] == _AADR else tg
        return {
            **out,
            "status": "declined",
            "reason": f"The {' and '.join(declined)} placement declined to name any population, "
            "so the sample is unrepresented and no classifier can be shown to cover it: "
            + str(part["reason"]),
        }
    if absent:
        part = aadr if absent[0] == _AADR else tg
        return {
            **out,
            "status": "not_run",
            "reason": f"The {' and '.join(absent)} placement was not run, so an ancestry no "
            "published classifier covers cannot be excluded: " + str(part["reason"]),
        }
    population = str(tg["population"])
    classifier, match, category = _classifier(population)
    candidates = sorted(
        {_classifier(row["population"])[0] or "none" for row in tg["uncertainty"]["admissible"]}
    )
    out.update(
        category={
            "population": population,
            "morales_category": category,
            "training": None if classifier is None else TRAINING[classifier],
        },
        candidates=candidates,
    )
    if len(candidates) > 1:
        return {
            **out,
            "status": "ambiguous",
            "reason": f"1000 Genomes populations admissible for this sample point at "
            f"different classifiers ({', '.join(candidates)}); the placement cannot choose "
            "between them, so none was selected.",
        }
    if classifier is None:
        return {
            **out,
            "status": "unsupported",
            "reason": f"1000 Genomes population {population} is {category}, which no "
            "published HLARES training set describes; no classifier was selected.",
        }
    share = (
        "names this category"
        if match == 1.0
        else "names this region without publishing its share, so the match is unknown"
    )
    return {
        **out,
        "status": "selected",
        "classifier": classifier,
        "match": match,
        "reason": f"1000 Genomes population {population} is {category}; the {classifier} "
        f"classifier's training ({TRAINING[classifier]}) {share}. The Human Origins "
        "placement also named a population.",
    }


def decide(src: Mapping[str, Any], requested: str | None) -> dict[str, Any]:
    """Selection evidence from validated compact placements and an optional explicit model."""
    if requested is not None and requested not in POPULATIONS:
        raise HLAError("Explicit supported HLA classifier and model-terms opt-in are required.")
    auto = _automatic(src)
    reason = auto["reason"]
    if requested is None:
        classifier = auto["classifier"]
        match = auto["match"]
        basis = None if classifier is None else "ancestry"
    else:
        classifier, basis = requested, "explicit"
        if auto["status"] == "selected":
            match = auto["match"] if requested == auto["classifier"] else 0.0
        elif auto["status"] in {"declined", "unsupported"}:
            match = 0.0
        elif auto["status"] == "ambiguous":
            match = None if requested in auto["candidates"] else 0.0
        else:
            match = None
        verdict = (
            "agrees with"
            if requested == auto["classifier"]
            else "is not supported by"
            if match == 0.0
            else "is not established by"
        )
        reason += f" The explicitly requested {requested} classifier {verdict} this placement."
    return {
        "schema_version": VERSION,
        "method": METHOD,
        "status": auto["status"],
        "automatic_classifier": auto["classifier"],
        "requested_classifier": requested,
        "classifier": classifier,
        "basis": basis,
        "ancestry_match": match,
        "category": auto["category"],
        "candidates": auto["candidates"],
        "reason": reason,
        "source": src,
    }


def select(ancestry: Mapping[str, Any] | None, *, requested: str | None = None) -> dict[str, Any]:
    """Choose a classifier from the run's M5 placements, or record why none was chosen."""
    return decide(source(ancestry), requested)


def _expanded(src: Mapping[str, Any]) -> dict[str, Any]:
    """The compact source as an ancestry record, so validation reruns :func:`source`."""
    aadr, tg = dict(src["aadr"]), dict(src["thousand_genomes"])
    uncertainty = tg.pop("uncertainty")
    if uncertainty is not None:
        tg.update(
            decline_threshold=uncertainty["decline_threshold"],
            coverage=uncertainty["coverage"],
            fits=uncertainty["admissible"],
        )
    return {"population": aadr, "reference_population": tg}


KEYS: Final = frozenset(
    {
        "schema_version",
        "method",
        "status",
        "automatic_classifier",
        "requested_classifier",
        "classifier",
        "basis",
        "ancestry_match",
        "category",
        "candidates",
        "reason",
        "source",
    }
)


def validate(record: Any) -> None:
    """Validate saved selection evidence by rederiving it from its frozen placements."""
    try:
        if not isinstance(record, Mapping) or set(record) != KEYS:
            raise HLAError("HLA ancestry selection is malformed.")
        if type(record["schema_version"]) is not int or record["schema_version"] != VERSION:
            raise HLAError("HLA ancestry selection version is unsupported.")
        if record["method"] != METHOD:
            raise HLAError("HLA ancestry selection version is unsupported.")
        raw = record["source"]
        if not isinstance(raw, Mapping) or set(raw) != {"aadr", "thousand_genomes"}:
            raise HLAError("HLA ancestry selection source is malformed.")
        if source(_expanded(raw)) != raw:
            raise HLAError("HLA ancestry selection source is malformed.")
        if decide(raw, record["requested_classifier"]) != record:
            raise HLAError("HLA ancestry selection disagrees with its frozen placement.")
    except HLAError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError):
        raise HLAError("HLA ancestry selection is malformed.") from None
