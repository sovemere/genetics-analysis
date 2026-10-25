"""The carrier panel and each carrier card's saved state (roadmap M11.5).

Two things live here, and they answer different questions.

:func:`carrier_panel` is **the callable set**: every marker this knowledge pack can report
carrier status for, read from the cards' schema-7 ``carrier`` declarations. It is data, not
prose, because M11.6's section-level incompleteness statement has to say what carrier
screening from this array leaves out, and it can only do that against an exact list of what
it puts in. The panel describes the knowledge pack, not a person: it is the same for every
run and carries no genotype.

:func:`carrier_record` is **one run's result** for one carrier card -- the declaration plus
the derived state. The state is computed from the oriented call and the declared pathogenic
allele, never read from an outcome name, and :func:`validate_record` re-derives it from a
saved bundle's own match so a record that disagrees with its call is refused rather than
displayed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from genetics.engine.cards import (
    Card,
    CardKind,
    CarrierDeclaration,
    CarrierState,
    Inheritance,
    KnowledgePack,
)
from genetics.engine.matcher import (
    MatchResult,
    MatchStatus,
    Strand,
    complement,
    is_strand_ambiguous,
)

PANEL_SCHEMA_VERSION: Final[int] = 1
"""Bumped when a reader of :meth:`CarrierPanel.to_dict` would misread it."""

RECORD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "condition",
        "inheritance",
        "variant",
        "pathogenic_allele",
        "clinvar",
        "typed_scope",
        "state",
        "pathogenic_copies",
    }
)


class CarrierRecordError(ValueError):
    """A saved carrier record that does not follow from its own card's call."""


@dataclass(frozen=True)
class CarrierEntry:
    """One typed marker in the panel."""

    card_id: str
    section: str
    gene: str | None
    rsid: str
    chrom: str
    pos_grch37: int
    alleles: tuple[str, ...]
    declaration: CarrierDeclaration

    @property
    def strand_symmetric(self) -> bool:
        """An A/T or C/G marker: a homozygous call cannot be oriented, so no copies and two
        copies look the same and the card reports that rather than choosing. A heterozygote
        is one copy on either strand, so a carrier is still reported."""
        return is_strand_ambiguous(self.alleles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "section": self.section,
            "gene": self.gene,
            "rsid": self.rsid,
            "chrom": self.chrom,
            "pos_grch37": self.pos_grch37,
            "alleles": list(self.alleles),
            "strand_symmetric": self.strand_symmetric,
            **self.declaration.to_dict(),
        }


@dataclass(frozen=True)
class CarrierPanel:
    """Every carrier marker the pack types, ordered by condition, gene and position."""

    entries: tuple[CarrierEntry, ...]

    @property
    def conditions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(e.declaration.condition for e in self.entries))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PANEL_SCHEMA_VERSION,
            "conditions": list(self.conditions),
            "entries": [entry.to_dict() for entry in self.entries],
        }


def carrier_panel(pack: KnowledgePack) -> CarrierPanel:
    entries = []
    for card in pack.cards:
        if card.carrier is None:
            continue
        assert card.match is not None  # schema: a carrier card is single-marker
        variant = card.match.variant
        entries.append(
            CarrierEntry(
                card_id=card.id,
                section=card.section.value,
                gene=card.gene,
                rsid=variant.rsid,
                chrom=variant.key.chrom.value,
                pos_grch37=variant.key.pos_grch37,
                alleles=variant.key.alleles,
                declaration=card.carrier,
            )
        )
    entries.sort(
        key=lambda e: (e.declaration.condition.lower(), e.gene or "", e.chrom, e.pos_grch37)
    )
    return CarrierPanel(tuple(entries))


def pathogenic_copies(
    allele: str, alleles: Sequence[str], genotype: str | None, observed: str | None, strand: str
) -> int:
    """How many copies of ``allele`` a matched call carries.

    ``genotype`` is the call on the card's strand. At an A/T or C/G site the matcher leaves
    it ``None`` even when it matched, because which strand was read is unknown; it matches
    there only when both readings give the same outcome, which for a carrier card is the
    heterozygote. The count is then taken from the observed call and must be the same on
    both strands -- otherwise the strand would decide the answer and nothing here may.
    """
    if genotype is not None:
        if len(genotype) != 2 or set(genotype) - set(alleles):
            raise CarrierRecordError("matched carrier card lacks a call on its own alleles")
        return genotype.count(allele)
    if strand != Strand.AMBIGUOUS.value or not isinstance(observed, str) or len(observed) != 2:
        raise CarrierRecordError("matched carrier card lacks a call on its own alleles")
    copies = observed.count(allele)
    if set(observed) - set(alleles) or complement(observed).count(allele) != copies:
        raise CarrierRecordError("an ambiguous-strand call cannot fix the carrier state")
    return copies


def carrier_record(card: Card, match: MatchResult) -> dict[str, Any] | None:
    """The saved record for one carrier card, derived from its match.

    A match without an interpretation -- absent, uncalled, conflicting, mismatched or
    strand-ambiguous -- leaves the state ``None``: not determined, and never non-carrier.
    """
    if card.carrier is None:
        return None
    copies = None
    if match.status is MatchStatus.MATCHED:
        assert card.match is not None
        copies = pathogenic_copies(
            card.carrier.pathogenic_allele,
            card.match.variant.key.alleles,
            match.genotype,
            match.observed_genotype,
            match.strand.value,
        )
    return {
        **card.carrier.to_dict(),
        "state": None if copies is None else CarrierState.of(copies).value,
        "pathogenic_copies": copies,
    }


STATE_LABELS: Final[dict[str | None, str]] = {
    CarrierState.NON_CARRIER.value: "No copy of the typed allele",
    CarrierState.CARRIER.value: "One copy of the typed allele",
    CarrierState.TWO_COPIES.value: "Two copies of the typed allele",
    None: "Not determined",
}


def validate_record(entry: Mapping[str, Any]) -> None:
    """Refuse a saved carrier record that is malformed or contradicts its own call.

    Only the bundle's own fields are consulted. The current knowledge pack is deliberately
    not: a saved run keeps the declaration it was written with even after a card changes.
    """
    record = entry.get("carrier")
    if record is None:
        return
    if not isinstance(record, Mapping) or set(record) != RECORD_KEYS:
        raise CarrierRecordError("carrier record has the wrong fields")
    if entry.get("kind") != CardKind.INTERPRETATION.value or entry.get("multi_marker"):
        raise CarrierRecordError("carrier records belong to single-marker interpretation cards")
    for key in ("condition", "variant", "typed_scope"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise CarrierRecordError(f"carrier {key} must be nonempty text")
    if record["inheritance"] != Inheritance.AUTOSOMAL_RECESSIVE.value:
        raise CarrierRecordError("unsupported carrier inheritance")
    clinvar = record["clinvar"]
    if isinstance(clinvar, bool) or not isinstance(clinvar, int) or clinvar <= 0:
        raise CarrierRecordError("carrier ClinVar VariationID must be a positive integer")
    variant = entry.get("variant")
    alleles = variant.get("alleles") if isinstance(variant, Mapping) else None
    allele = record["pathogenic_allele"]
    if (
        not isinstance(alleles, list)
        or len(alleles) != 2
        or not isinstance(allele, str)
        or allele not in alleles
    ):
        raise CarrierRecordError("carrier pathogenic allele is not one of the card's alleles")
    match = entry.get("match")
    if not isinstance(match, Mapping):
        raise CarrierRecordError("carrier card has no saved match")
    if entry.get("status") == "matched":
        genotype, observed = match.get("genotype"), match.get("observed_genotype")
        copies = pathogenic_copies(
            allele,
            alleles,
            genotype if isinstance(genotype, str) else None,
            observed if isinstance(observed, str) else None,
            str(match.get("strand")),
        )
        expected: tuple[Any, Any] = (CarrierState.of(copies).value, copies)
    else:
        expected = (None, None)
    copies_saved = record["pathogenic_copies"]
    if (copies_saved is not None and type(copies_saved) is not int) or (
        record["state"],
        copies_saved,
    ) != expected:
        raise CarrierRecordError("carrier state does not follow from the saved call")
