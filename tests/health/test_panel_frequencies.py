"""1000 Genomes counts as the fallback frequency for card loci gnomAD's exomes miss (M15.5)."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from genetics.engine.cards import KnowledgePack
from genetics.engine.confidence import RARE_CALL_FREQUENCY_CEILING, ConfidenceTier
from genetics.engine.evidence import assemble_card
from genetics.engine.matcher import MatchResult, MatchStatus, match_pack
from genetics.health import panel_frequencies
from genetics.health.panel_frequencies import (
    SOURCE,
    PanelFrequencyError,
    lookup,
    select_panel_frequencies,
)
from genetics.ingest.keys import MergeTable
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.pgs.reference import Panel, ReferenceSample
from genetics.qc.report import InferredSex
from genetics.run.pipeline import observations


def _record(ref: str, alt: str, **groups: tuple[int, int]) -> dict[str, Any]:
    """``groups`` maps a population to (allele number, alternate count)."""
    return {
        "ref": ref,
        "alts": [alt],
        "populations": {name: {"an": an, "ac": [ac]} for name, (an, ac) in groups.items()},
    }


def test_a_common_allele_is_priced_from_the_population_that_holds_it_most() -> None:
    record = _record("A", "G", ALL=(5008, 1500), EUR=(1006, 400), EAS=(1008, 10))
    found = select_panel_frequencies([record], alleles={"A", "G"}, called={"A", "G"})
    by_allele = {f.allele: f for f in found}
    assert by_allele["G"].frequency == pytest.approx(400 / 1006)
    assert by_allele["A"].frequency == pytest.approx(606 / 1006)
    assert {f.population for f in found} == {"1000 Genomes EUR"}
    assert {f.source for f in found} == {SOURCE}


def test_a_single_copy_anywhere_prices_nothing() -> None:
    """One copy in ~1,000 alleles cannot show an allele is outside the rare-call band."""
    record = _record("A", "G", ALL=(5008, 1), EUR=(1006, 1), AFR=(1322, 0))
    assert select_panel_frequencies([record], alleles={"A", "G"}, called={"G"}) == ()
    assert select_panel_frequencies([record], alleles={"A", "G"}, called={"A", "G"}) == ()


def test_a_population_short_of_one_called_allele_takes_no_part() -> None:
    record = _record("A", "G", ALL=(5008, 3), EUR=(1006, 0), AFR=(1322, 3))
    found = select_panel_frequencies([record], alleles={"A", "G"}, called={"A", "G"})
    assert {f.population for f in found} == {"1000 Genomes AFR"}


@pytest.mark.parametrize(
    ("records", "alleles"),
    [
        ([_record("A", "G", ALL=(5008, 900))], {"A", "C"}),  # another variant at the position
        ([_record("A", "G", ALL=(5008, 900)), _record("A", "T", ALL=(5008, 9))], {"A", "G"}),
        ([{"ref": "A", "alts": ["G", "T"], "populations": {}}], {"A", "G"}),
        ([_record("A", "AT", ALL=(5008, 900))], {"A", "AT"}),  # an indel
        ([], {"A", "G"}),
    ],
)
def test_anything_but_one_exact_biallelic_snp_prices_nothing(
    records: list[dict[str, Any]], alleles: set[str]
) -> None:
    assert select_panel_frequencies(records, alleles=alleles, called=set(alleles)) == ()


@pytest.mark.parametrize("called", [{"A"}, {"G"}, {"A", "G"}], ids=["ref", "alt", "both"])
def test_the_fallback_can_never_price_an_allele_into_the_rare_call_band(called: set[str]) -> None:
    """So it cannot carry a rare call out of likely-artifact (AGENTS.md 4.1).

    Every allele count from 0 to the allele number, at allele numbers from a tiny group to
    beyond the pooled panel: whatever is priced holds at least two copies of each called
    allele, which no allele number this side of 200,000 can put below 0.001%.
    """
    for an in (1, 2, 3, 10, 694, 1006, 1322, 5008, 6000):
        for ac in range(an + 1):
            found = select_panel_frequencies(
                [_record("A", "G", ALL=(an, ac))], alleles={"A", "G"}, called=called
            )
            for item in found:
                if item.allele in called:
                    assert item.frequency >= RARE_CALL_FREQUENCY_CEILING, (an, ac)


# -- reading the panel -----------------------------------------------------------------------

SAMPLES = {
    "S1": ReferenceSample("GBR", "EUR", InferredSex.FEMALE),
    "S2": ReferenceSample("GBR", "EUR", InferredSex.MALE),
    "S3": ReferenceSample("YRI", "AFR", InferredSex.FEMALE),
}


def _panel(tmp_path: Path, rows: list[str]) -> Panel:
    """A synthetic three-sample panel VCF for chromosome 2, invented, never a real one."""
    text = (
        "##fileformat=VCFv4.1\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\tS2\tS3\n"
    )
    path = tmp_path / "ALL.chr2.phase3_test.genotypes.vcf.gz"
    path.write_bytes(gzip.compress((text + "".join(rows)).encode()))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return Panel("test", "open", {"2": (path, sha)}, "test.panel", "0" * 64, SAMPLES)


ROWS = [
    "2\t100\t.\tA\tG\t100\tPASS\t.\tGT\t0|1\t1|1\t0|0\n",
    "2\t200\t.\tC\tT\t100\tPASS\t.\tGT:GL\t0/1:x\t.|0\t0|1\n",
    "2\t300\t.\tG\tA\t100\tPASS\t.\tGT\t0|0\t0|0\t0|0\n",
]


def test_lookup_counts_alleles_per_super_population_and_pooled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel_frequencies, "cache_dir", lambda: tmp_path / "cache")
    panel = _panel(tmp_path, ROWS)
    found = lookup([("2", 100), ("2", 200), ("2", 999), ("X", 5)], panel=panel, workers=1)
    assert set(found) == {("2", 100), ("2", 200)}
    first = found[("2", 100)][0]["populations"]
    assert first["EUR"] == {"an": 4, "ac": [3]}
    assert first["AFR"] == {"an": 2, "ac": [0]}
    assert first["ALL"] == {"an": 6, "ac": [3]}
    second = found[("2", 200)][0]["populations"]
    assert second["EUR"] == {"an": 3, "ac": [1]}  # a missing allele is not counted


def test_lookup_is_cached_by_its_public_loci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel_frequencies, "cache_dir", lambda: tmp_path / "cache")
    panel = _panel(tmp_path, ROWS)
    first = lookup([("2", 100)], panel=panel, workers=1)
    monkeypatch.setattr(
        panel_frequencies, "_count_chromosome", lambda *a: pytest.fail("read again")
    )
    assert lookup([("2", 100)], panel=panel, workers=1) == first


def test_a_panel_file_that_fails_its_lock_digest_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel_frequencies, "cache_dir", lambda: tmp_path / "cache")
    panel = _panel(tmp_path, ROWS)
    path, _ = panel.vcfs["2"]
    wrong = Panel("test", "open", {"2": (path, "f" * 64)}, "test.panel", "0" * 64, SAMPLES)
    with pytest.raises(PanelFrequencyError, match="lock digest"):
        lookup([("2", 100)], panel=wrong, workers=1)


def test_an_absent_panel_prices_nothing_and_raises_nothing() -> None:
    assert lookup([("2", 100)], panel="The panel is not fetched.") == {}


# -- the pipeline's use of it ----------------------------------------------------------------


def _eye_shade_card() -> tuple[KnowledgePack, MatchResult, tuple[str, int], set[str]]:
    """The committed HERC2 card, whose intronic locus gnomAD's exomes do not hold."""
    card = next(c for c in KnowledgePack.load().cards if c.id == "herc2_oca2_eye_shade")
    assert card.match is not None
    variant = card.match.variant
    alleles = sorted(variant.key.alleles)
    pair = alleles[0] + alleles[1]
    table = GenotypeTable(
        pl.DataFrame(
            [
                {
                    "rsid": variant.rsid,
                    "chrom": variant.key.chrom.value,
                    "pos_grch37": variant.key.pos_grch37,
                    "a1": pair[0],
                    "a2": pair[1],
                    "genotype": pair,
                    "call_status": "called",
                }
            ],
            schema=NORMALIZED_SCHEMA,
        ),
        vendor="synthetic",
    )
    pack = KnowledgePack((card,), Path("synthetic-memory"))
    match = match_pack(pack, table, merges=MergeTable.empty())[0]
    assert match.status is MatchStatus.MATCHED
    locus = (variant.key.chrom.value, variant.key.pos_grch37)
    return pack, match, locus, set(alleles)


def _panel_record(alleles: set[str], ac: int) -> dict[str, Any]:
    ref, alt = sorted(alleles)
    return _record(ref, alt, ALL=(5008, ac), EUR=(1006, min(ac, 1006)))


def test_a_card_gnomad_cannot_price_is_priced_from_the_panel() -> None:
    pack, match, locus, alleles = _eye_shade_card()
    card = pack.cards[0]
    without = observations(pack, (match,), {}, None, None, {})[card.id]
    assert without.frequencies == ()
    assert assemble_card(card, match, without).confidence.tier is ConfidenceTier.MODERATE  # type: ignore[union-attr]
    runtime = observations(pack, (match,), {}, None, None, {locus: [_panel_record(alleles, 700)]})
    assert {f.source for f in runtime[card.id].frequencies} == {SOURCE}
    assembled = assemble_card(card, match, runtime[card.id])
    assert assembled.confidence is not None
    assert not any("allele frequency" in caveat for caveat in assembled.computed_caveats), (
        "a priced card says nothing about a missing frequency"
    )


def test_gnomad_is_read_first_and_the_panel_only_where_it_is_silent() -> None:
    pack, match, locus, alleles = _eye_shade_card()
    ref, alt = sorted(alleles)
    gnomad = [
        {
            "ref": ref,
            "alts": [alt],
            "filter": "PASS",
            "populations": {"global": {"an": 200000, "ac": [60000], "af": [0.3]}},
        }
    ]
    runtime = observations(
        pack, (match,), {locus: gnomad}, None, None, {locus: [_panel_record(alleles, 700)]}
    )
    assert {f.source for f in runtime[pack.cards[0].id].frequencies} != {SOURCE}
