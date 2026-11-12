"""Why a saved card has the tier it has, in one shape for every kind of card (roadmap M13.4).

A saved card keeps what produced its tier in one of two places. An interpretation or HLA
card has a ``confidence`` block: the tier, the weighted score and six scored inputs. A
computed, polygenic or guideline card has ``confidence: null`` and keeps its tier, inputs
and reason in ``computation.reliability``, whose inputs differ by source. Neither says
which input decided the tier. :func:`explain_confidence` reads whichever applies and
returns one block: the inputs as rows, each with its weight and what it cost the score; the
ceilings that applied; and which of them, or the score, decided the tier.

**The saved card is not changed, and this is not part of it.** The block is built when the
run is read, by this engine's rules, so the agent commands print it under
``current_context``. The rules are the calculator's own: the ceilings come from
:func:`~genetics.engine.confidence.single_call_ceilings` and
:func:`~genetics.engine.confidence.polygenic_ceilings`, which the calculators call too.

**It checks itself against the saved tier.** A run saved under other weights or thresholds
would otherwise get this engine's explanation for a tier this engine did not compute. The
saved inputs are replayed; if the replayed tier or score differs from the saved one, the
block says so (basis ``not_reproduced``) and claims nothing about what decided the tier.

Nothing is filtered here and nothing is re-scored. The tier and score are the saved ones.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Final

from genetics.engine.cards import EvidenceTier, Replication
from genetics.engine.confidence import (
    SCORE_BANDS,
    SCORE_WEIGHTS,
    CallSource,
    Ceiling,
    ConfidenceTier,
    polygenic_ceilings,
    score_tier,
    single_call_ceilings,
    weakest,
)
from genetics.engine.ppv import confirmation_text
from genetics.run.bundle import StoredCard


class Basis(StrEnum):
    """What decided a card's tier."""

    SCORE = "score"
    """The weighted score's band, with no ceiling below it. A ceiling may sit at the band."""
    CEILING = "ceiling"
    """One or more ceilings below the score's band."""
    METHOD = "method"
    """The card's method sets the tier; there is no weighted score."""
    NOT_REPRODUCED = "not_reproduced"
    """This engine's rules do not give the saved tier and score from the saved inputs."""
    NONE = "none"
    """The card has no tier."""


SOURCES: Final[tuple[str, ...]] = ("confidence", "computation.reliability")
"""Where the saved card keeps its tier and inputs."""

SCORE_TOLERANCE: Final[float] = 0.00015
"""How far a replayed score may sit from the saved one: one step in the fourth place. A
single call's score was rounded from an unrounded effect component, and the component is
saved rounded, so the two sums can fall either side of a rounding boundary. Every other
component is saved as it was scored."""

_Row = tuple[str, tuple[str, ...], str, str]

SINGLE_CALL_ROWS: Final[tuple[_Row, ...]] = (
    ("evidence_tier", ("evidence_tier",), "evidence_score", "evidence"),
    ("effect_size", ("effect_measure", "effect_value"), "effect_score", "effect"),
    ("replication", ("replication",), "replication_score", "replication"),
    ("allele_frequency", ("population_allele_frequency",), "frequency_score", "frequency"),
    ("call_quality", ("call_source", "imputation_quality"), "imputation_score", "imputation"),
    ("ancestry_match", ("ancestry_match",), "ancestry_score", "ancestry"),
)
"""A ``confidence`` block's six scored inputs: the row's name, the saved keys that hold what
was observed, the saved key that holds its component score, and its weight's name."""

POLYGENIC_ROWS: Final[tuple[_Row, ...]] = (
    ("evidence_tier", ("evidence_tier",), "evidence_score", "evidence"),
    ("effect_size", ("effect_measure", "effect_value"), "effect_score", "effect"),
    ("replication", ("replication",), "replication_score", "replication"),
    ("weight_coverage", ("weight_coverage",), "coverage_score", "frequency"),
    (
        "weighted_quality",
        ("weighted_quality", "unknown_quality_weight_fraction"),
        "quality_score",
        "imputation",
    ),
    ("ancestry_match", ("ancestry_match",), "ancestry_score", "ancestry"),
)
"""A polygenic record's six scored inputs (M9.6). Coverage holds the weight allele frequency
holds for one call, and weighted quality the weight imputation quality holds."""


class _Unreadable(Exception):
    """A saved value this engine's rules cannot take: another version's vocabulary or type."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _fraction(value: Any) -> float | None:
    """A saved fraction or ``None``; anything else cannot be replayed."""
    if value is None:
        return None
    number = _number(value)
    if number is None or not 0.0 <= number <= 1.0:
        raise _Unreadable
    return number


def _scalar(value: Any) -> str | int | float | bool | None:
    """A saved value as a JSON scalar. Anything nested is written out, never dropped."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return json.dumps(value, sort_keys=True, default=str)


def _tier(value: Any) -> ConfidenceTier:
    try:
        return ConfidenceTier(value)
    except ValueError:
        raise _Unreadable from None


def _tier_name(value: Any) -> str | None:
    """The saved tier where it is one of this engine's, else ``None``."""
    try:
        return ConfidenceTier(value).value
    except ValueError:
        return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _row(
    name: str, values: Mapping[str, Any], component: Any = None, weight: float | None = None
) -> dict[str, Any]:
    scored = _number(component)
    if weight is None or scored is None:
        contribution = lost = None
    else:
        contribution, lost = round(weight * scored, 4), round(weight * (1.0 - scored), 4)
    return {
        "name": name,
        "values": {key: _scalar(value) for key, value in values.items()},
        "component": None if weight is None else scored,
        "weight": weight,
        "contribution": contribution,
        "lost": lost,
    }


def _scored_rows(inputs: Mapping[str, Any], layout: Sequence[_Row]) -> list[dict[str, Any]]:
    return [
        _row(name, {key: inputs.get(key) for key in keys}, inputs.get(score), SCORE_WEIGHTS[weight])
        for name, keys, score, weight in layout
    ]


def _bands() -> list[dict[str, Any]]:
    return [{"tier": tier.value, "min_score": floor} for tier, floor in SCORE_BANDS]


def _band_text(tier: ConfidenceTier) -> str:
    floors = dict(SCORE_BANDS)
    if tier not in floors:
        return "no score band"
    above = [floor for _, floor in SCORE_BANDS if floor > floors[tier]]
    if not above:
        return f"{floors[tier]:.2f} or more"
    if floors[tier] == 0.0:
        return f"below {min(above):.2f}"
    return f"{floors[tier]:.2f} up to {min(above):.2f}"


def _ceiling(ceiling: Ceiling) -> dict[str, Any]:
    return {"input": ceiling.input, "tier": ceiling.tier.value, "rule": ceiling.rule}


def _block(
    *,
    source: str | None,
    basis: Basis,
    tier: str | None,
    reason: str,
    score: float | None = None,
    band: ConfidenceTier | None = None,
    inputs: Sequence[Mapping[str, Any]] = (),
    ceilings: Sequence[Ceiling] = (),
    limiting: Sequence[str] = (),
    empirical_ppv: Mapping[str, Any] | None = None,
    replay: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    assert source is None or source in SOURCES
    return {
        "source": source,
        "basis": basis.value,
        "tier": tier,
        "score": score,
        "score_tier": None if band is None else band.value,
        "score_bands": _bands(),
        "inputs": [dict(row) for row in inputs],
        "ceilings": [_ceiling(c) for c in ceilings],
        "limiting": list(limiting),
        "reason": reason,
        "empirical_ppv": None if empirical_ppv is None else dict(empirical_ppv),
        "replay": None if replay is None else dict(replay),
    }


def _join(parts: Sequence[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _losses(rows: Sequence[Mapping[str, Any]]) -> str:
    """The inputs that cost the score most, so "why" has an answer when no ceiling applies."""
    lost = sorted(
        (row for row in rows if row["lost"]),
        key=lambda row: -row["lost"],
    )[:2]
    if not lost:
        return ""
    named = [f"{row['name']} ({row['lost']:g} of a possible {row['weight']:g})" for row in lost]
    return f" The score lost most on {_join(named)}."


def _scored(
    *,
    source: str,
    saved_tier: Any,
    saved_score: Any,
    rows: list[dict[str, Any]],
    ceilings: tuple[Ceiling, ...] | None,
    empirical_ppv: Mapping[str, Any] | None = None,
    preface: str = "",
) -> dict[str, Any]:
    """A tier that came from a weighted score and ceilings, checked against a replay."""
    tier, score = _tier_name(saved_tier), _number(saved_score)
    # From the saved components, not from each row's `contribution`: those are rounded to
    # four places for display, and four rounded rows can sit 0.0002 from the saved score.
    scored = [row for row in rows if row["weight"] is not None]
    replayed_score = (
        None
        if any(row["component"] is None for row in scored)
        else round(math.fsum(float(row["weight"] * row["component"]) for row in scored), 4)
    )
    replayed_tier = (
        None if ceilings is None or score is None else weakest(score_tier(score), ceilings).value
    )
    matches = (
        tier is not None
        and replayed_tier == tier
        and score is not None
        and replayed_score is not None
        and abs(replayed_score - score) <= SCORE_TOLERANCE
    )
    replay = {"tier": replayed_tier, "score": replayed_score, "matches": matches}
    if not matches or tier is None or score is None or ceilings is None:
        if replayed_tier is None or replayed_score is None:
            why = "This engine's rules cannot replay the saved inputs"
        else:
            why = (
                f"This engine's rules give tier {replayed_tier} and score {replayed_score:g} "
                "from the saved inputs"
            )
        return _block(
            source=source,
            basis=Basis.NOT_REPRODUCED,
            tier=tier,
            score=score,
            band=None if score is None else score_tier(score),
            inputs=rows,
            ceilings=ceilings or (),
            empirical_ppv=empirical_ppv,
            replay=replay,
            reason=(
                f"{preface}The run saved tier {saved_tier} with score "
                f"{'not recorded' if score is None else format(score, 'g')}. {why}, so "
                "the rules that set the saved tier are not this engine's and nothing here says "
                "which input decided it. The saved tier stands."
            ),
        )
    band = score_tier(score)
    final = ConfidenceTier(tier)
    deciding = [c for c in ceilings if c.tier is final]
    limiting = list(dict.fromkeys(c.input for c in deciding))
    if final is band:
        reason = (
            f"{preface}The weighted score {score:g} falls in the {band.value} band "
            f"({_band_text(band)}), and no ceiling is below it.{_losses(rows)}"
        )
        if deciding:
            reason += (
                " A higher score would not raise the tier, because "
                f"{_join([c.rule for c in deciding])}."
            )
        return _block(
            source=source,
            basis=Basis.SCORE,
            tier=tier,
            score=score,
            band=band,
            inputs=rows,
            ceilings=ceilings,
            limiting=limiting,
            empirical_ppv=empirical_ppv,
            replay=replay,
            reason=reason,
        )
    reason = (
        f"{preface}The tier is {tier} because {_join([c.rule for c in deciding])}. "
        f"The weighted score {score:g} alone falls in the {band.value} band "
        f"({_band_text(band)})."
    )
    estimate = _number(_mapping(empirical_ppv).get("estimate"))
    if estimate is not None:
        reason += " " + confirmation_text(
            estimate, _number(_mapping(empirical_ppv).get("population_frequency_ceiling"))
        )
    return _block(
        source=source,
        basis=Basis.CEILING,
        tier=tier,
        score=score,
        band=band,
        inputs=rows,
        ceilings=ceilings,
        limiting=limiting,
        empirical_ppv=empirical_ppv,
        replay=replay,
        reason=reason,
    )


def _hla_call(card: StoredCard) -> tuple[list[dict[str, Any]], list[Ceiling]]:
    """An HLA card's classifier-call ceiling (M11.4), which sits beside the six inputs."""
    result = _mapping(_mapping(card.computation).get("result"))
    reliability = _mapping(result.get("reliability"))
    if not reliability:
        return [], []
    loci_named = reliability.get("ceiling_loci")
    loci = (
        [str(locus) for locus in loci_named]
        if isinstance(loci_named, Sequence) and not isinstance(loci_named, str)
        else []
    )
    row = _row(
        "hla_call",
        {
            "posterior_locus": reliability.get("posterior_locus"),
            "locus_ceiling": reliability.get("locus_ceiling"),
            "ceiling_loci": ", ".join(loci) or None,
        },
    )
    if reliability.get("locus_ceiling") is None:
        return [row], []
    from genetics.hla.cards import CEILING_NAMES

    lowered: list[str] = []
    for locus in loci:
        names = _mapping(_mapping(_mapping(result.get("loci")).get(locus)).get("confidence")).get(
            "ceilings"
        )
        if isinstance(names, Sequence) and not isinstance(names, str):
            lowered += [CEILING_NAMES.get(str(name), str(name)) for name in names]
    where = _join([f"HLA-{locus}" for locus in loci]) if loci else "a named locus"
    rule = f"the classifier call at {where} has a ceiling"
    if lowered:
        rule += f", lowered by {_join(sorted(set(lowered)))}"
    return [row], [Ceiling("hla_call", _tier(reliability["locus_ceiling"]), rule)]


def _weakest_marker(card: StoredCard) -> str:
    """A multi-marker card takes one marker's confidence; say that, and which marker."""
    markers = _mapping(card.multi_marker).get("markers")
    if not isinstance(markers, Sequence) or isinstance(markers, str):
        return ""
    rsids = [
        str(_mapping(_mapping(marker).get("variant")).get("rsid"))
        for marker in markers
        if _mapping(marker).get("confidence") == card.confidence
    ]
    named = f" ({_join(list(dict.fromkeys(rsids)))})" if rsids else ""
    return f"This card reads {len(markers)} markers and takes the weakest one's confidence{named}. "


def _single_call(card: StoredCard, confidence: Mapping[str, Any]) -> dict[str, Any]:
    inputs = _mapping(confidence.get("inputs"))
    rows = _scored_rows(inputs, SINGLE_CALL_ROWS)
    ceilings: tuple[Ceiling, ...] | None
    try:
        tier, replication = inputs.get("evidence_tier"), inputs.get("replication")
        extra_rows, extra = _hla_call(card) if card.kind == "hla" else ([], [])
        rows += extra_rows
        ceilings = (
            *single_call_ceilings(
                has_evidence=tier is not None,
                evidence_tier=None if tier is None else EvidenceTier(tier),
                replication=None if replication is None else Replication(replication),
                population_allele_frequency=_fraction(inputs.get("population_allele_frequency")),
                call_source=CallSource(str(inputs.get("call_source"))),
                imputation_quality=_fraction(inputs.get("imputation_quality")),
                ancestry_match=_fraction(inputs.get("ancestry_match")),
                # M9.13: a card compared with its study population by membership keeps the
                # weighted component and takes no PRS transfer ceiling. HLA cards always are.
                variant_ancestry=card.kind == "hla" or card.ancestry_comparison is not None,
            ),
            *extra,
        )
    except (_Unreadable, ValueError):
        ceilings = None
    ppv = confidence.get("empirical_ppv")
    return _scored(
        source="confidence",
        saved_tier=confidence.get("tier"),
        saved_score=confidence.get("score"),
        rows=rows,
        ceilings=ceilings,
        empirical_ppv=ppv if isinstance(ppv, Mapping) else None,
        preface=_weakest_marker(card) if card.multi_marker is not None else "",
    )


def _polygenic(reliability: Mapping[str, Any]) -> dict[str, Any]:
    inputs = _mapping(reliability.get("inputs"))
    ceilings: tuple[Ceiling, ...] | None
    try:
        coverage = _fraction(inputs.get("weight_coverage"))
        quality = _fraction(inputs.get("weighted_quality"))
        if coverage is None or quality is None:
            raise _Unreadable
        ceilings = polygenic_ceilings(
            evidence_tier=EvidenceTier(str(inputs.get("evidence_tier"))),
            replication=Replication(str(inputs.get("replication"))),
            weight_coverage=coverage,
            weighted_quality=quality,
            ancestry_match=_fraction(inputs.get("ancestry_match")),
        )
    except (_Unreadable, ValueError):
        ceilings = None
    return _scored(
        source="computation.reliability",
        saved_tier=reliability.get("tier"),
        saved_score=reliability.get("score"),
        rows=_scored_rows(inputs, POLYGENIC_ROWS),
        ceilings=ceilings,
    )


def _method(card: StoredCard, reliability: Mapping[str, Any]) -> dict[str, Any]:
    """A tier the method sets: a computed card's fixed ceiling, a guideline card's genes."""
    rows = [
        _row(str(key), {str(key): value})
        for key, value in _mapping(reliability.get("inputs")).items()
    ]
    reasons = [str(reliability["reason"])] if reliability.get("reason") else []
    result = _mapping(_mapping(card.computation).get("result"))
    for gene, record in _mapping(_mapping(result.get("reliability")).get("genes")).items():
        rows.append(_row(str(gene), {"tier": _mapping(record).get("tier")}))
        said = _mapping(record).get("reasons")
        if isinstance(said, Sequence) and not isinstance(said, str):
            reasons += [str(sentence) for sentence in said]
    tier = reliability.get("tier")
    return _block(
        source="computation.reliability",
        basis=Basis.METHOD,
        tier=tier if isinstance(tier, str) else None,
        score=_number(reliability.get("score")),
        inputs=rows,
        reason=" ".join(dict.fromkeys(reasons))
        or "The card's method sets this tier; the run recorded no reason.",
    )


def _unscored(card: StoredCard) -> dict[str, Any]:
    if card.kind == "impossibility":
        reason = "Not scored: the card states an assay limit, which is not a finding."
    else:
        reason = f"Not scored: no finding for this run (status {card.status})."
        why = _mapping(card.computation).get("reason") or card.match.get("reason")
        if isinstance(why, str) and why.strip():
            reason += f" {why.strip()}"
    return _block(source=None, basis=Basis.NONE, tier=None, reason=reason)


def explain_confidence(card: StoredCard) -> dict[str, Any]:
    """One block saying what a saved card's tier is and what decided it, for any card kind.

    Every card gets one, including a card with no tier, which says why it has none. The
    tier and score are the saved ones; see the module docstring for what is this engine's.
    """
    if isinstance(card.confidence, Mapping):
        return _single_call(card, card.confidence)
    reliability = _mapping(card.computation).get("reliability")
    if not isinstance(reliability, Mapping) or reliability.get("tier") is None:
        return _unscored(card)
    if _number(reliability.get("score")) is not None and all(
        key in _mapping(reliability.get("inputs"))
        for _, keys, score, _ in POLYGENIC_ROWS
        for key in (*keys, score)
    ):
        return _polygenic(reliability)
    return _method(card, reliability)
