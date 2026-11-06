"""M11.5 and M11.6: carrier cards and excluded alleles against their pinned public records.

Native: reads the fetched ClinVar and gnomAD indexes in this checkout and skips where they
are absent, as on CI. Only public reference records are read; no genotype is involved.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from genetics.engine.cards import KnowledgePack
from genetics.engine.carrier import CarrierEntry, carrier_panel
from genetics.engine.carrier_scope import pack_scope

ROOT = Path(__file__).parents[2]
CLINVAR = ROOT / "data/references/clinvar_grch37/clinvar_lookup.sqlite"
GNOMAD = ROOT / "data/references/gnomad_exomes_r2_1_1_grch37/gnomad_frequencies.sqlite"
DBSNP = ROOT / "data/references/dbsnp_b157_grch37/dbsnp_variants.parquet"
PATHOGENIC = {"Pathogenic", "Likely_pathogenic", "Pathogenic,_low_penetrance"}


def _records(index: Path, entry: CarrierEntry) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(f"{index.as_uri()}?mode=ro", uri=True)) as db:
        rows = db.execute(
            "SELECT record FROM variants WHERE chrom=? AND pos=?", (entry.chrom, entry.pos_grch37)
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _entries() -> list[CarrierEntry]:
    return list(carrier_panel(KnowledgePack.load(ROOT / "knowledge")).entries)


@pytest.mark.skipif(not CLINVAR.is_file(), reason="pinned ClinVar index not fetched")
@pytest.mark.parametrize("entry", _entries(), ids=lambda e: e.card_id)
def test_declared_variation_is_a_pathogenic_snv_at_the_card_position(entry: CarrierEntry) -> None:
    declaration = entry.declaration
    other = next(a for a in entry.alleles if a != declaration.pathogenic_allele)
    (record,) = [
        r for r in _records(CLINVAR, entry) if r["variation_id"] == str(declaration.clinvar)
    ]
    assert record["ref"] == other and record["alts"] == [declaration.pathogenic_allele]
    info = record["info"]
    groups = str(info["CLNSIG"]).split("|")
    assert set(groups[0].split("/")) <= PATHOGENIC, (entry.card_id, info["CLNSIG"])
    assert "CLNSIGCONF" not in info
    assert entry.gene is not None and entry.gene in str(info["GENEINFO"])


@pytest.mark.skipif(not GNOMAD.is_file(), reason="pinned gnomAD exomes index not fetched")
@pytest.mark.parametrize("entry", _entries(), ids=lambda e: e.card_id)
def test_the_pathogenic_allele_has_a_usable_gnomad_frequency(entry: CarrierEntry) -> None:
    allele = entry.declaration.pathogenic_allele
    usable = [
        r
        for r in _records(GNOMAD, entry)
        if {r["ref"], *r["alts"]} == set(entry.alleles) and r["filter"] == "PASS"
    ]
    assert len(usable) == 1 and usable[0]["alts"] == [allele]
    counts = usable[0]["populations"]
    assert any(c["an"] and c["ac"][0] for c in counts.values()), entry.card_id


def _site_records(index: Path, chrom: str, pos: int) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(f"{index.as_uri()}?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT record FROM variants WHERE chrom=? AND pos=?", (chrom, pos))
        return [json.loads(row[0]) for row in rows.fetchall()]


def _scope() -> dict[str, Any]:
    scope = pack_scope(KnowledgePack.load(ROOT / "knowledge"))
    assert scope is not None
    return scope


def _dbsnp(rsids: list[str]) -> dict[str, dict[str, Any]]:
    rows = pl.scan_parquet(DBSNP).filter(pl.col("rsid").is_in(rsids)).collect()
    return {row["rsid"]: row for row in rows.iter_rows(named=True)}


@pytest.mark.skipif(not DBSNP.is_file(), reason="pinned dbSNP index not fetched")
def test_the_declared_multiallelic_markers_are_the_ones_dbsnp_lists() -> None:
    scope = _scope()
    records = _dbsnp([entry["rsid"] for entry in scope["panel"]["entries"]])
    assert len(records) == scope["panel"]["markers"]
    measured = {rsid for rsid, record in records.items() if len(record["alts"]) > 1}
    assert measured == set(scope["declaration"]["dbsnp_multiallelic"])


@pytest.mark.skipif(not DBSNP.is_file(), reason="pinned dbSNP index not fetched")
def test_every_excluded_allele_names_a_real_marker() -> None:
    declared = _scope()["declaration"]["excluded_alleles"]
    assert set(_dbsnp([a["rsid"] for a in declared])) == {a["rsid"] for a in declared}


@pytest.mark.skipif(
    not (DBSNP.is_file() and CLINVAR.is_file() and GNOMAD.is_file()),
    reason="pinned dbSNP, ClinVar and gnomAD indexes not fetched",
)
def test_excluded_alleles_stand_where_the_audit_put_them() -> None:
    declared = _scope()["declaration"]["excluded_alleles"]
    sites = _dbsnp([a["rsid"] for a in declared])
    for allele in declared:
        site = sites[allele["rsid"]]
        clinvar = _site_records(CLINVAR, site["chrom"], site["pos_grch37"])
        gnomad = _site_records(GNOMAD, site["chrom"], site["pos_grch37"])
        significance = [str(r["info"].get("CLNSIG", "")) for r in clinvar]
        where = (allele["gene"], allele["variant"])
        if allele["class"] == "not_authored":
            # Passes the measured criteria, so this is a gap in the report and not the data.
            assert any(set(s.split("|")[0].split("/")) <= PATHOGENIC for s in significance), where
            assert any(r["filter"] == "PASS" for r in gnomad), where
            assert any(allele["gene"] in str(r["info"].get("GENEINFO")) for r in clinvar), where
        elif allele["class"] == "failed_criterion":
            if "conflicting" in allele["reason"].lower():
                assert any("Conflicting" in s for s in significance), where
            else:
                assert not gnomad, where
