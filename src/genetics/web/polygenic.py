"""Dashboard view of a polygenic card (M9.6): the distribution first, the person as a band.

The chart is a histogram of the comparison group's scores with the person's 95% interval as
a washed band. There is no marker for the person, because the stored display has no point
to mark (:mod:`genetics.pgs.cards`). Geometry is computed here so the template only draws,
and so it is testable without a browser. Colours are two validated roles (``--pgs-bar``,
``--pgs-band``) defined in ``app.css`` for both themes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

WIDTH: Final = 480.0
TOP: Final = 22.0
BASELINE: Final = 118.0
GAP: Final = 2.0
RADIUS: Final = 4.0
MIN_BAND: Final = 3.0


@dataclass(frozen=True)
class Bar:
    path: str
    title: str


@dataclass(frozen=True)
class Tick:
    x: float
    label: str

    @property
    def anchor(self) -> str:
        """Labels near an edge are anchored inward, so none is clipped by the chart."""
        return "start" if self.x < 28 else "end" if self.x > WIDTH - 28 else "middle"


@dataclass(frozen=True)
class DecileRow:
    decile: int
    rate: str
    overlapped: bool


def _bar_path(x: float, width: float, height: float) -> str:
    """A column rounded at its data end and square at the baseline."""
    top = BASELINE - height
    r = min(RADIUS, width / 2, height)
    return (
        f"M{x:.2f},{BASELINE:.2f}V{top + r:.2f}"
        f"Q{x:.2f},{top:.2f} {x + r:.2f},{top:.2f}"
        f"H{x + width - r:.2f}"
        f"Q{x + width:.2f},{top:.2f} {x + width:.2f},{top + r:.2f}"
        f"V{BASELINE:.2f}Z"
    )


def _ordinal(value: float) -> str:
    n = round(value)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _percent(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{100 * value:.0f}%" if value >= 0.01 or value == 0 else f"{100 * value:.2g}%"


@dataclass(frozen=True)
class PolygenicView:
    pgs_id: str
    trait: str
    placed: bool
    reason: str | None
    bars: tuple[Bar, ...]
    band_x: float
    band_width: float
    band_label: str
    ticks: tuple[Tick, ...]
    reference_label: str
    ancestry_matched: bool
    reference_reason: str | None
    phase_label: str
    coverage: Mapping[str, Any]
    quality: Mapping[str, Any]
    portability: Mapping[str, Any] | None
    deciles: Mapping[str, Any] | None
    decile_rows: tuple[DecileRow, ...]
    reliability: Mapping[str, Any]
    licence: Mapping[str, Any] | None

    @property
    def band_label_x(self) -> float:
        centre = self.band_x + self.band_width / 2
        return min(max(centre, 4.0), WIDTH - 4.0)

    @property
    def band_label_anchor(self) -> str:
        centre = self.band_x + self.band_width / 2
        return "start" if centre < 130 else "end" if centre > WIDTH - 130 else "middle"

    @property
    def coverage_display(self) -> str:
        c = self.coverage
        return (
            f"{c['rows_scored']:,} of {c['rows_total']:,} score rows scored; "
            f"{c['comparable_rows']:,} comparable with the reference, carrying "
            f"{_percent(c['comparable_weight_fraction'])} of the score's absolute weight."
        )

    @property
    def quality_display(self) -> str:
        q = self.quality
        return (
            f"Weight-averaged quality {q['weighted_quality']:.2f} (direct calls 1, imputed "
            f"calls their DR2, unknown 0); imputed share {_percent(q['imputed_weight_fraction'])}"
            f"; unknown-quality share {_percent(q['unknown_quality_weight_fraction'])}."
        )

    @property
    def portability_display(self) -> str | None:
        p = self.portability
        if p is None:
            return None
        match = p.get("match")
        bounds = (
            ""
            if match is None
            else f" Demonstrated match {_percent(match['matched'])}, at most "
            f"{_percent(match['upper_bound'])}."
        )
        return f"{str(p['judgment']).replace('_', ' ').capitalize()}.{bounds} {p['reason']}"

    @classmethod
    def of(cls, computation: Mapping[str, Any]) -> PolygenicView | None:
        result = computation.get("result")
        reliability = computation.get("reliability") or {}
        if not isinstance(result, Mapping):
            return None
        authored = result["authored"]
        deciles = authored.get("decile_outcomes")
        position = result.get("position")
        rows = tuple(
            DecileRow(
                decile=i + 1,
                rate=_percent(rate),
                overlapped=bool(deciles.get("overlapped")) and (i + 1) in deciles["overlapped"],
            )
            for i, rate in enumerate(deciles["rates"] if deciles else ())
        )
        if position is None:
            return cls(
                pgs_id=str(result["pgs_id"]),
                trait=str(authored["trait"]),
                placed=False,
                reason=computation.get("reason"),
                bars=(),
                band_x=0.0,
                band_width=0.0,
                band_label="",
                ticks=(),
                reference_label="",
                ancestry_matched=False,
                reference_reason=None,
                phase_label="",
                coverage={},
                quality={},
                portability=result.get("portability"),
                deciles=deciles,
                decile_rows=rows,
                reliability=reliability,
                licence=None,
            )
        histogram = result["distribution"]["histogram"]
        edges: Sequence[float] = histogram["edges"]
        counts: Sequence[int] = histogram["counts"]
        low_edge, high_edge = edges[0], edges[-1]
        span = high_edge - low_edge

        def x_of(value: float) -> float:
            if span <= 0:
                return WIDTH / 2
            return max(0.0, min(WIDTH, (value - low_edge) / span * WIDTH))

        tallest = max(counts) or 1
        bars = []
        for i, count in enumerate(counts):
            left = x_of(edges[i]) if span > 0 else 0.0
            right = x_of(edges[i + 1]) if span > 0 else WIDTH
            width = max(1.0, right - left - GAP)
            height = (BASELINE - TOP) * count / tallest
            if count:
                bars.append(
                    Bar(
                        _bar_path(left + GAP / 2, width, height),
                        f"{count:,} reference samples scored {edges[i]:.3g} to {edges[i + 1]:.3g}",
                    )
                )
        a, b = result["position"]["score_interval"]
        band_left, band_right = x_of(a), x_of(b)
        if band_right - band_left < MIN_BAND:
            centre = (band_left + band_right) / 2
            band_left = max(0.0, min(WIDTH - MIN_BAND, centre - MIN_BAND / 2))
            band_right = band_left + MIN_BAND
        low, high = position["percentile_interval_95"]
        quantiles = result["distribution"]["quantiles"]
        ticks: list[Tick] = []
        for q in ("10", "50", "90"):
            x = x_of(quantiles[q]) if q in quantiles else None
            # Drop a tick that would collide with the previous one's label.
            if x is not None and (not ticks or x - ticks[-1].x >= 56):
                ticks.append(Tick(x, f"{_ordinal(float(q))} pct"))
        reference = result["reference"]
        return cls(
            pgs_id=str(result["pgs_id"]),
            trait=str(authored["trait"]),
            placed=True,
            reason=None,
            bars=tuple(bars),
            band_x=band_left,
            band_width=band_right - band_left,
            band_label=f"Your interval: {_ordinal(low)} to {_ordinal(high)} percentile",
            ticks=tuple(ticks),
            reference_label=f"{reference['label']} · {reference['n']:,} samples",
            ancestry_matched=bool(reference["ancestry_matched"]),
            reference_reason=reference.get("reason"),
            phase_label="after imputation" if result["phase"] == "after" else "original array",
            coverage=result["coverage"],
            quality=result["quality"],
            portability=result["portability"],
            deciles=deciles,
            decile_rows=rows,
            reliability=reliability,
            licence=result.get("licence"),
        )
