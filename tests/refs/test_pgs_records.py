"""Private score records held compressed (format 25), on fabricated records only."""

from __future__ import annotations

import gzip
import json

import pytest

from genetics.pgs.catalog import PgsError
from genetics.pgs.records import ScoreRecords, encode, is_score_file_name, score_file_name

RECORD = {"status": "computed", "terms": [{"row_number": 1, "weight": 0.25}], "note": "é"}


def test_records_compress_canonically_and_parse_afresh_on_every_access() -> None:
    held = ScoreRecords()
    parsed = held.add("card_a", RECORD)
    assert parsed == RECORD and list(held) == ["card_a"] and len(held) == 1
    data = held.compressed("card_a")
    assert data == gzip.compress(encode(RECORD), compresslevel=6, mtime=0)
    assert json.loads(gzip.decompress(data)) == RECORD
    # Same record, same bytes: key order and timestamps do not leak into the file digest.
    again = ScoreRecords.of({"card_a": dict(reversed(list(RECORD.items())))})
    assert again.compressed("card_a") == data
    assert held["card_a"] == RECORD and held["card_a"] is not held["card_a"]
    assert ScoreRecords.of(held) is held
    assert held.get("absent") is None


def test_records_refuse_duplicates_nan_and_undecodable_bytes() -> None:
    held = ScoreRecords()
    held.add("card_a", RECORD)
    with pytest.raises(PgsError, match="already held"):
        held.add("card_a", RECORD)
    with pytest.raises(ValueError):
        held.add("card_b", {"sum": float("nan")})
    broken = ScoreRecords({"x": b"not gzip", "y": gzip.compress(b"[1]"), "z": b""})
    for key in ("x", "y", "z"):
        with pytest.raises(PgsError):
            broken[key]


def test_score_file_names_land_on_the_ignored_run_payload_suffix() -> None:
    name = score_file_name("synthetic_polygenic")
    assert name == "pgs-synthetic_polygenic.run.json.gz" and is_score_file_name(name)
    assert name.endswith(".run.json.gz")
    for bad in ("../x", "X", "a b", ""):
        with pytest.raises(PgsError):
            score_file_name(bad)
    assert not is_score_file_name("pgs-a.run.json") and not is_score_file_name("pgs-.run.json.gz")


def test_the_repr_never_shows_a_record() -> None:
    held = ScoreRecords.of({"card_a": RECORD})
    assert repr(held) == "ScoreRecords(['card_a'])"
