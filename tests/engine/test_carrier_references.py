"""M11.5: every carrier card is bound to its pinned ClinVar and gnomAD records.

Native: reads the fetched ClinVar and gnomAD indexes in this checkout and skips where they
are absent, as on CI. Only public reference records are read; no genotype is involved.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from genetics.engine.cards import KnowledgePack
from genetics.engine.carrier import CarrierEntry, carrier_panel

ROOT = Path(__file__).parents[2]
CLINVAR = ROOT / "data/references/clinvar_grch37/clinvar_lookup.sqlite"
GNOMAD = ROOT / "data/references/gnomad_exomes_r2_1_1_grch37/gnomad_frequencies.sqlite"
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
