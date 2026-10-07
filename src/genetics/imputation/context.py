"""Recorded execution mode, separate from each finding's observation source (M8.4)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from genetics.external.harmonize import SiteOutcome
from genetics.imputation.target import ImputationError
from genetics.privacy import NoGenotypeRepr, assert_no_genotype

MODES = frozenset({"enabled", "disabled", "not_recorded"})
SOURCES = frozenset({"direct", "imputed_no_call", "imputed_untyped"})
REGIONS = frozenset(
    {*(f"chr{i}" for i in range(1, 23)), "X_left", "X_par1", "X_nonpar", "X_par2", "X_right"}
)
OUTCOMES = frozenset(
    {*(v.value for v in SiteOutcome), "unresolved_ploidy", "duplicate_panel_position"}
)


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ImputationError("Imputation execution counts must be nonnegative integers.")
    return value


def _validate_summary(raw: Mapping[str, Any]) -> None:
    if set(raw) != {
        "status",
        "jobs",
        "resumed",
        "records",
        "sources",
        "ploidy_conflicts",
        "regions",
        "unsupported_positions",
    }:
        raise ImputationError("Imputation execution summary has invalid fields.")
    jobs, records = _count(raw["jobs"]), _count(raw["records"])
    if type(raw["resumed"]) is not bool or raw["status"] != (
        "computed" if jobs else "no_eligible_jobs"
    ):
        raise ImputationError("Imputation execution status disagrees with its jobs.")
    if (not jobs and records) or _count(raw["ploidy_conflicts"]) > records:
        raise ImputationError("Imputation execution counts disagree.")
    sources = raw["sources"]
    if (
        not isinstance(sources, dict)
        or not set(sources) <= SOURCES
        or sum(_count(v) for v in sources.values()) != records
    ):
        raise ImputationError("Imputation execution source counts disagree with records.")
    regions = raw["regions"]
    if not isinstance(regions, list):
        raise ImputationError("Imputation regions must be a list.")
    names: set[str] = set()
    computed = called = missing = 0
    for region in regions:
        if not isinstance(region, dict) or set(region) != {
            "region",
            "ploidy",
            "positions",
            "written",
            "called",
            "outcomes",
            "status",
        }:
            raise ImputationError("Imputation region report has invalid fields.")
        name = region["region"]
        if not isinstance(name, str) or name not in REGIONS or name in names:
            raise ImputationError("Imputation region names must be unique.")
        names.add(name)
        positions, written, observed = (
            _count(region[k]) for k in ("positions", "written", "called")
        )
        outcomes = region["outcomes"]
        if (
            not isinstance(outcomes, dict)
            or not set(outcomes) <= OUTCOMES
            or sum(_count(v) for v in outcomes.values()) != positions
            or not observed <= written <= positions
        ):
            raise ImputationError("Imputation region counts do not partition positions.")
        if written != sum(
            outcomes.get(k, 0) for k in ("as_written", "complemented", "no_call")
        ) or observed != sum(outcomes.get(k, 0) for k in ("as_written", "complemented")):
            raise ImputationError("Imputation region written/called counts disagree.")
        ploidy = region["ploidy"]
        if ploidy is not None and (type(ploidy) is not int or ploidy not in (1, 2)):
            raise ImputationError("Imputation region has invalid biological ploidy.")
        status = region["status"]
        if status == "computed":
            if ploidy is None or observed < 2:
                raise ImputationError("Completed imputation region lacks typed anchors/ploidy.")
            computed += 1
            called += observed
            missing += written - observed
        elif status == "unresolved_ploidy":
            if ploidy is not None or written:
                raise ImputationError("Unresolved imputation region has resolved observations.")
        elif status != "insufficient_typed_calls" or observed >= 2 or ploidy is None:
            raise ImputationError("Imputation region status disagrees with its observations.")
    if (
        computed != jobs
        or sources.get("direct", 0) != called
        or sources.get("imputed_no_call", 0) != missing
    ):
        raise ImputationError("Imputation execution and region/source counts disagree.")
    unsupported = raw["unsupported_positions"]
    if not isinstance(unsupported, dict) or not set(unsupported) <= {"Y", "MT", "PAR"}:
        raise ImputationError("Imputation unsupported chromosome report is invalid.")
    for value in unsupported.values():
        _count(value)


@dataclass(frozen=True, repr=False)
class ImputationContext(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("mode", "status")
    mode: str
    status: str
    summary: Mapping[str, Any] | None = None
    quality_aware: bool = False

    def __post_init__(self) -> None:
        if type(self.quality_aware) is not bool or (self.quality_aware and self.mode != "enabled"):
            raise ImputationError("Quality-aware card input requires enabled imputation.")
        if (
            not isinstance(self.mode, str)
            or not isinstance(self.status, str)
            or self.mode not in MODES
        ):
            raise ImputationError("Imputation mode is invalid.")
        if self.mode == "enabled":
            if not isinstance(self.summary, Mapping):
                raise ImputationError("Enabled imputation needs its execution summary.")
            try:
                summary = json.loads(json.dumps(dict(self.summary), allow_nan=False))
                _validate_summary(summary)
            except (TypeError, ValueError) as exc:
                if isinstance(exc, ImputationError):
                    raise
                raise ImputationError("Imputation execution summary is malformed.") from None
            if self.status != summary["status"]:
                raise ImputationError("Imputation context and execution status disagree.")
            object.__setattr__(self, "summary", summary)
        elif (
            self.status != ("disabled" if self.mode == "disabled" else "not_recorded")
            or self.summary is not None
        ):
            raise ImputationError("Imputation mode/status/summary are inconsistent.")

    @classmethod
    def disabled(cls) -> ImputationContext:
        return cls("disabled", "disabled")

    @classmethod
    def not_recorded(cls) -> ImputationContext:
        return cls("not_recorded", "not_recorded")

    @classmethod
    def enabled(
        cls, summary: Mapping[str, Any], *, quality_aware: bool = False
    ) -> ImputationContext:
        return cls("enabled", summary["status"], summary, quality_aware)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": 2 if self.quality_aware else 1,
            "mode": self.mode,
            "status": self.status,
            "card_input": "original_array_with_imputed"
            if self.quality_aware
            else ("not_recorded" if self.mode == "not_recorded" else "original_array"),
            "summary": None if self.summary is None else dict(self.summary),
        }
        # Deep copy: nested mutable region reports must not alias a saved snapshot.
        text = json.dumps(result, allow_nan=False)
        assert_no_genotype(text, context="imputation execution record")
        copied: dict[str, Any] = json.loads(text)
        return copied

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ImputationContext:
        if (
            set(raw) != {"schema_version", "mode", "status", "card_input", "summary"}
            or type(raw["schema_version"]) is not int
            or raw["schema_version"] not in {1, 2}
        ):
            raise ImputationError("Imputation execution record has invalid schema.")
        result = cls(raw["mode"], raw["status"], raw["summary"], raw["schema_version"] == 2)
        if result.to_dict() != dict(raw):
            raise ImputationError("Imputation execution record has inconsistent card inputs.")
        return result
