"""Allele-specific dosage/quality contract for evidence and future score consumers.

Dosages remain on their native 0-ploidy scale. DR2 describes an allele dosage
across a reference model, not the posterior probability of this person's hard call.
No quality threshold discards an observation or modifies its dosage.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from genetics.privacy import NoGenotypeRepr

from .dosages import DosageRecord
from .target import ImputationError


@dataclass(frozen=True, repr=False)
class ImputationEvidence(NoGenotypeRepr):
    _repr_fields: ClassVar[tuple[str, ...]] = ("source", "ploidy", "quality_scope")
    source: str
    ref: str
    alt: tuple[str, ...]
    dosage: tuple[float, ...]
    dr2: tuple[float, ...] | None
    ploidy: int
    dosage_method: str
    quality_scope: str

    def __post_init__(self) -> None:
        for name in ("alt", "dosage", "dr2"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, tuple | list):
                    raise ImputationError(
                        "Imputed allele/dosage/quality vectors must be sequences."
                    )
                object.__setattr__(self, name, tuple(value))
        if (
            not isinstance(self.source, str)
            or self.source not in {"imputed_no_call", "imputed_untyped"}
            or type(self.ploidy) is not int
            or self.ploidy not in {1, 2}
            or not isinstance(self.ref, str)
            or not self.ref
            or self.ref == "."
            or not self.alt
            or any(not isinstance(a, str) or not a or a == "." for a in self.alt)
            or len(set((self.ref, *self.alt))) != len(self.alt) + 1
            or not isinstance(self.dosage, tuple)
            or len(self.dosage) != len(self.alt)
        ):
            raise ImputationError("Imputed observation allele/ploidy contract is invalid.")
        for vector, upper in ((self.dosage, self.ploidy), (self.dr2, 1)):
            if vector is not None and any(
                isinstance(v, bool)
                or not isinstance(v, int | float)
                or not math.isfinite(v)
                or not 0 <= v <= upper
                for v in vector
            ):
                raise ImputationError("Imputed observation dosage/quality is invalid.")
        if sum(self.dosage) > self.ploidy + 0.005 * len(self.alt) + 0.000001:
            raise ImputationError("Imputed alternate dosages exceed biological ploidy.")
        scope = "beagle_haploid_dosage" if self.ploidy == 1 else "beagle_diploid_dosage"
        if self.source == "imputed_no_call":
            if (
                self.dr2 is not None
                or self.quality_scope != "not_estimated"
                or self.dosage_method != "phased_hardcall_only"
            ):
                raise ImputationError("Phase-filled no-calls have unestimated quality.")
        elif (
            self.dr2 is None
            or len(self.dr2) != len(self.alt)
            or self.quality_scope != scope
            or self.dosage_method != "beagle_DS"
        ):
            raise ImputationError("Untyped imputation needs native per-ALT dosage quality.")

    @classmethod
    def from_record(cls, record: DosageRecord) -> ImputationEvidence:
        if record.status != "resolved":
            raise ImputationError("Unresolved imputed observations cannot enter evidence.")
        return cls(
            record.source,
            record.ref,
            record.alt,
            record.dosage,
            record.dr2,
            record.ploidy,
            record.dosage_method,
            record.quality_scope,
        )

    @property
    def card_quality(self) -> float | None:
        """Biallelic dosage quality applies to both complementary allele counts.

        Multi-ALT REF quality cannot be inferred without dosage covariance. Card
        matching currently accepts only an exact biallelic SNV allele contract.
        """
        if len(self.alt) != 1:
            raise ImputationError("Card quality requires an exact biallelic allele contract.")
        return None if self.dr2 is None else self.dr2[0]

    def allele_dosage(self, allele: str) -> tuple[float, float | None]:
        """Return native dose and its own DR2 for a future score's effect allele.

        REF dose is complementary; multi-ALT REF quality remains unknown. Independent
        writer rounding may exceed ploidy by its recorded tolerance; clamp only the
        complementary REF dose at zero, never any ALT dose or quality.
        """
        if allele == self.ref:
            return max(0.0, self.ploidy - sum(self.dosage)), (
                self.dr2[0] if self.dr2 is not None and len(self.alt) == 1 else None
            )
        if allele not in self.alt:
            raise ImputationError("Score effect allele is absent from the dosage contract.")
        index = self.alt.index(allele)
        return self.dosage[index], None if self.dr2 is None else self.dr2[index]

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        for key in ("alt", "dosage", "dr2"):
            if raw[key] is not None:
                raw[key] = list(raw[key])
        return raw

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ImputationEvidence:
        if set(raw) != {
            "source",
            "ref",
            "alt",
            "dosage",
            "dr2",
            "ploidy",
            "dosage_method",
            "quality_scope",
        }:
            raise ImputationError("Imputed observation has invalid fields.")
        return cls(**raw)
