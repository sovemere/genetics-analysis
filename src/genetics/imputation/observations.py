"""A card-locus view of imputation; original QC/ClinVar/structure inputs stay intact."""

from __future__ import annotations

from dataclasses import replace

import polars as pl

from genetics.engine.cards import KnowledgePack
from genetics.engine.matcher import MatchResult
from genetics.ingest.schema import NORMALIZED_SCHEMA, CallStatus, GenotypeTable
from genetics.qc.report import InferredSex

from .pipeline import ImputationResult
from .quality import ImputationEvidence
from .target import ImputationError, regions


def card_input(
    pack: KnowledgePack, result: ImputationResult, *, sex: InferredSex
) -> tuple[GenotypeTable, dict[tuple[str, int], ImputationEvidence]]:
    """Stream full dosages, retaining only exact biallelic SNVs requested by cards.

    Any original called probe blocks replacement, including contradictory, indel or
    strand-unresolved probes. Multiple panel records at a requested position are
    ambiguous. Dosages are never rounded to manufacture hard calls: the validated
    Beagle GT is used for categorical findings; DS and quality remain separate.
    """
    alleles: dict[tuple[str, int], set[frozenset[str]]] = {}
    for card in pack.cards:
        if card.match is not None:
            for variant in card.match.variants:
                key = variant.key
                alleles.setdefault((key.chrom.value, key.pos_grch37), set()).add(
                    frozenset(key.alleles)
                )
    requested = set(alleles)
    present: set[tuple[str, int]] = set()
    blocked: set[tuple[str, int]] = set()
    for chrom, pos, status in result.original.frame.select(
        "chrom", "pos_grch37", "call_status"
    ).iter_rows():
        locus = (chrom, pos)
        if locus in requested:
            present.add(locus)
            if status != CallStatus.NO_CALL.value:
                blocked.add(locus)
    requested -= blocked
    if not requested:
        return result.original, {}
    selected = {}
    duplicates: set[tuple[str, int]] = set()
    seen: set[tuple[str, int]] = set()
    for record in result.iter_dosages():
        locus = (record.chrom, record.pos_grch37)
        if locus not in requested:
            continue
        if locus in seen:
            duplicates.add(locus)
        seen.add(locus)
        if (
            record.chrom not in {*(str(i) for i in range(1, 23)), "X"}
            or record.source not in {"imputed_no_call", "imputed_untyped"}
            or record.status != "resolved"
            or len(record.alt) != 1
            or record.ref not in "ACGT"
            or record.alt[0] not in "ACGT"
            or len(record.ref) != 1
            or len(record.alt[0]) != 1
            or frozenset((record.ref, *record.alt)) not in alleles[locus]
        ):
            continue
        if (record.source == "imputed_no_call") != (locus in present):
            raise ImputationError(
                "Imputation observation source disagrees with the original array."
            )
        detail = ImputationEvidence.from_record(record)
        expected_ploidy = next(
            (r.ploidy for r in regions(record.chrom, sex) if r.start <= record.pos_grch37 <= r.end),
            None,
        )
        if (
            record.genotype is None
            or record.ploidy != expected_ploidy
            or record.storage_genotype != record.genotype
            or record.storage_dosage != record.dosage
            or len(record.genotype) != record.ploidy
            or any(type(a) is not int or a not in {0, 1} for a in record.genotype)
        ):
            raise ImputationError("Imputed card observation has invalid native genotype ploidy.")
        bases = (record.ref, *record.alt)
        genotype = "".join(sorted(bases[i] for i in record.genotype))
        if record.ploidy == 1:
            genotype *= 2  # Normalized string representation only; native DS/quality unchanged.
        selected[locus] = (genotype, detail)
    for locus in duplicates:
        selected.pop(locus, None)
    if not selected:
        return result.original, {}
    rows = []
    for (chrom, pos), (genotype, detail) in selected.items():
        rows.append(
            (
                None,
                chrom,
                pos,
                genotype[0],
                genotype[1],
                genotype,
                CallStatus.HEMIZYGOUS.value if detail.ploidy == 1 else CallStatus.CALLED.value,
            )
        )
    added = pl.DataFrame(rows, schema=NORMALIZED_SCHEMA, orient="row")
    loci = added.select("chrom", "pos_grch37")
    frame = result.original.frame.join(loci, on=["chrom", "pos_grch37"], how="anti")
    return (
        GenotypeTable(pl.concat([frame, added]), vendor=result.original.vendor),
        {locus: item[1] for locus, item in selected.items()},
    )


def mark_imputed(match: MatchResult) -> MatchResult:
    """Keep provenance explicit even when strand or phase prevents interpretation."""
    return replace(match, caveats=(*match.caveats, "Observation supplied by imputation."))
