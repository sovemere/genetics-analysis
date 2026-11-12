"""``genetics cards search`` and ``genetics runs search`` (roadmap M13.3).

The ranking itself is tested in ``tests/engine/test_search.py``. These tests cover the two
commands: their payloads, their text, their errors, and the privacy split between them.

The saved run is built from committed cards matched against an invented table: each card's
first and last declared allele. No export is read.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine import search as engine
from genetics.engine.cards import KnowledgePack, default_knowledge_dir
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import match_pack
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.paths import runs_dir
from genetics.privacy import GenotypeLeakError, find_genotypes
from genetics.qc.report import QCReport
from genetics.run import reads, store
from genetics.run.bundle import RunBundle, read_bundle, write_bundle
from genetics.run.pipeline import observations

runner = CliRunner()
Check = Callable[[object], str]

CARD_IDS = (
    "mthfr_c677t_homocysteine",
    "mthfr_c677t_venous_thrombosis",
    "mthfr_c677t_coronary_heart_disease",
    "mthfr_c677t_depression",
    "wnt10a_hair_curl",
    "methylation_epigenetic_age",
)
MISSING_RUN = "20260101T000000Z-00000000"
GENOTYPE_QUERY = "rs4988235" + ": " + "A" + "/" + "G"
"""An identifier with a call attached, assembled at runtime so this file holds none."""
DIRTY = "\t".join(("rs4988235", "2", "136608646", "A", "G"))
"""A genotype row, assembled the same way."""


@pytest.fixture(scope="module")
def full_pack() -> KnowledgePack:
    return KnowledgePack.load(default_knowledge_dir())


def _table(pack: KnowledgePack) -> GenotypeTable:
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for card in pack.cards:
        if card.match is None:
            continue
        variant = card.match.variants[0]
        first, last = variant.key.alleles[0], variant.key.alleles[-1]
        rows[(variant.key.chrom.value, variant.key.pos_grch37)] = {
            "rsid": variant.rsid,
            "chrom": variant.key.chrom.value,
            "pos_grch37": variant.key.pos_grch37,
            "a1": first,
            "a2": last,
            "genotype": "".join(sorted(first + last)),
            "call_status": "called",
        }
    return GenotypeTable(
        pl.DataFrame(list(rows.values()), schema=NORMALIZED_SCHEMA), vendor="synthetic"
    )


@pytest.fixture
def saved(
    full_pack: KnowledgePack,
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> RunBundle:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    pack = KnowledgePack(
        tuple(card for card in full_pack.cards if card.id in CARD_IDS), full_pack.source_dir
    )
    matches = match_pack(pack, _table(pack))
    path = write_bundle(
        qc=sample_qc,
        cards=assemble_pack(pack, matches, observations(pack, matches)),
        pack=pack,
        ancestry=AncestryContext.not_run("synthetic test bundle"),
        runs_root=runs_dir(),
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    return read_bundle(path)


def _json(args: list[str], code: int = 0) -> Any:
    result = runner.invoke(app, args)
    assert result.exit_code == code, result.output
    return json.loads(result.stdout)


def _text(args: list[str]) -> str:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.stdout


# ---------------------------------------------------------------------------
# cards search
# ---------------------------------------------------------------------------


def test_the_pack_search_finds_a_card_without_its_id(
    full_pack: KnowledgePack, agent_schema_check: Check
) -> None:
    payload = _json(["cards", "search", "curly hair", "--json"])
    assert agent_schema_check(payload) == "cards.search"
    assert payload["query"] == "curly hair"
    assert payload["terms"] == ["curly", "hair"] and payload["ignored"] == []
    assert payload["searched"] == len(full_pack.cards)
    assert payload["total"] == len(payload["hits"]) and payload["limit"] is None
    top = payload["hits"][0]
    assert top["card_id"] == "wnt10a_hair_curl"
    assert (top["section"], top["kind"], top["gene"]) == ("traits", "interpretation", "WNT10A")
    assert top["title"] == "WNT10A hair-curl association"
    assert top["terms_matched"] == 2 and top["score"] > 0
    assert {"field": "title", "terms": ["curly", "hair"]} in top["matched"]
    # The id it returns is the one the other reads take.
    evidence = _json(["cards", "evidence", top["card_id"], "--json"])
    assert evidence["title"] == top["title"]


def test_the_pack_search_is_the_engine_s_view(full_pack: KnowledgePack) -> None:
    payload = _json(["cards", "search", "MTHFR", "depression", "--json"])
    payload.pop("schema")
    assert payload == engine.pack_view(full_pack.cards, engine.parse_query("MTHFR depression"))


def test_words_may_be_given_quoted_or_one_by_one() -> None:
    quoted = _json(["cards", "search", "curly hair", "--json"])
    apart = _json(["cards", "search", "curly", "hair", "--json"])
    assert quoted == apart
    assert _text(["cards", "search", "curly hair"]) == _text(["cards", "search", "curly", "hair"])


def test_the_pack_search_text_says_what_matched_and_where() -> None:
    text = _text(["cards", "search", "curly hair"])
    first, second, third = text.splitlines()[:3]
    assert first.endswith("in the knowledge pack match 'curly hair' (terms: curly, hair).")
    assert second.split() == ["traits", "wnt10a_hair_curl", "WNT10A", "hair-curl", "association"]
    assert third.strip().startswith("2 of 2 term(s), score ")
    assert "title: curly, hair" in third
    assert text.splitlines()[-1] == (
        "`genetics cards evidence <card-id>` prints what a card rests on."
    )


def test_partial_matches_are_listed_below_full_ones() -> None:
    payload = _json(["cards", "search", "curly hair", "--json"])
    matched = [hit["terms_matched"] for hit in payload["hits"]]
    assert matched == sorted(matched, reverse=True) and set(matched) == {1, 2}
    assert "1 of 2 term(s)" in _text(["cards", "search", "curly hair"])


def test_a_limit_shows_fewer_and_still_states_the_total() -> None:
    everything = _json(["cards", "search", "hair", "--json"])
    limited = _json(["cards", "search", "hair", "--limit", "2", "--json"])
    assert limited["limit"] == 2 and limited["total"] == everything["total"] > 2
    assert limited["hits"] == everything["hits"][:2]
    text = _text(["cards", "search", "hair", "--limit", "2"])
    assert f"{everything['total']} of {everything['searched']} card(s)" in text
    assert "Showing the best 2." in text
    assert "Showing the best" not in _text(["cards", "search", "hair"])
    assert runner.invoke(app, ["cards", "search", "hair", "--limit", "0"]).exit_code == 2


def test_common_words_are_dropped_and_said_to_be() -> None:
    payload = _json(["cards", "search", "risk of heart disease", "--json"])
    assert payload["terms"] == ["risk", "heart", "disease"] and payload["ignored"] == ["of"]
    assert payload["hits"][0]["card_id"] == "mthfr_c677t_coronary_heart_disease"
    assert "(terms: risk, heart, disease; ignored: of)" in _text(
        ["cards", "search", "risk of heart disease"]
    )


def test_no_match_is_an_answer_not_an_error(full_pack: KnowledgePack) -> None:
    payload = _json(["cards", "search", "zzzunmatchable", "--json"])
    assert payload["hits"] == [] and payload["total"] == 0
    text = _text(["cards", "search", "zzzunmatchable"])
    assert text.strip() == (
        "No card in the knowledge pack matches 'zzzunmatchable' (terms: zzzunmatchable). "
        f"{len(full_pack.cards)} card(s) searched."
    )


def test_a_single_match_is_worded_as_one() -> None:
    text = _text(["cards", "search", "abacavir"])
    assert text.startswith("1 of ") and "matches 'abacavir'" in text


def test_the_pack_search_reads_the_pack_it_is_given(
    tmp_path: Path, full_pack: KnowledgePack
) -> None:
    source = next(full_pack.source_dir.rglob("morphology_circadian.yaml"))
    (tmp_path / "traits").mkdir()
    (tmp_path / "traits" / source.name).write_bytes(source.read_bytes())
    payload = _json(["cards", "search", "hair", "--knowledge", str(tmp_path), "--json"])
    assert 0 < payload["searched"] < len(full_pack.cards)
    assert {hit["section"] for hit in payload["hits"]} == {"traits"}


# ---------------------------------------------------------------------------
# runs search
# ---------------------------------------------------------------------------


def test_the_run_search_returns_saved_faces_and_keeps_the_ranking_apart(
    saved: RunBundle, agent_schema_check: Check
) -> None:
    run = saved.path.name
    payload = _json(["runs", "search", run, "curly hair", "--json"])
    assert agent_schema_check(payload) == "runs.search"
    assert payload["run_id"] == run and payload["path"] == str(saved.path)
    assert set(payload) == {
        "schema",
        "run_id",
        "path",
        "format_version",
        "created_at",
        "results",
        "current_context",
    }
    context = payload["current_context"]
    assert context["context"] == "current"
    assert context["query"] == "curly hair" and context["terms"] == ["curly", "hair"]
    assert context["searched"] == len(saved.cards) == len(CARD_IDS)
    assert context["total"] == len(context["hits"]) == len(payload["results"])
    assert [r["card_id"] for r in payload["results"]] == [h["card_id"] for h in context["hits"]]
    assert payload["results"][0]["card_id"] == "wnt10a_hair_curl"

    # A result is the saved card's own values, and nothing this engine computed.
    whole = _json(["runs", "card", run, "wnt10a_hair_curl", "--json"])["card"]
    face = payload["results"][0]
    assert face == {key: whole[key] for key in face}
    assert set(face) == {
        "card_id",
        "section",
        "kind",
        "title",
        "gene",
        "status",
        "confidence_tier",
        "summary",
    }
    assert set(context["hits"][0]) == {"card_id", "score", "terms_matched", "matched"}


def test_the_run_search_is_the_same_ranking_as_the_pack_search(
    saved: RunBundle, full_pack: KnowledgePack
) -> None:
    """One function ranks both (AGENTS.md 3). A title-only query must agree exactly."""
    query = engine.parse_query("MTHFR")
    view = reads.search_view(saved, query)
    assert view["current_context"]["hits"] == [
        hit.to_dict() for hit in engine.search(map(reads.search_document, saved.cards), query)
    ]
    in_run = [card for card in full_pack.cards if card.id in CARD_IDS]
    from_pack = [hit["card_id"] for hit in engine.pack_view(in_run, query)["hits"]]
    assert [hit["card_id"] for hit in view["current_context"]["hits"]] == from_pack
    assert set(from_pack) == {card_id for card_id in CARD_IDS if card_id.startswith("mthfr")}


def test_the_run_search_reads_what_the_run_saved(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The saved summary is searched, not the pack's other outcomes or its current text."""
    cards = tuple(
        dataclasses.replace(card, summary="A saved sentence about zebrafish.", title="Renamed")
        if card.card_id == "wnt10a_hair_curl"
        else card
        for card in saved.cards
    )
    monkeypatch.setattr(store, "load_run", lambda *a, **k: dataclasses.replace(saved, cards=cards))
    payload = _json(["runs", "search", saved.path.name, "zebrafish", "--json"])
    (result,) = payload["results"]
    assert result["card_id"] == "wnt10a_hair_curl" and result["title"] == "Renamed"
    assert payload["current_context"]["hits"][0]["matched"] == [
        {"field": "summary", "terms": ["zebrafish"]}
    ]
    assert _json(["cards", "search", "zebrafish", "--json"])["hits"] == []


def test_no_card_is_ranked_or_left_out_for_its_status_or_tier(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGENTS.md 0.1A: confidence labels, it does not filter. Nor does it rank a search."""
    run = saved.path.name
    payload = _json(["runs", "search", run, "biological age", "--json"])
    assert payload["results"][0]["card_id"] == "methylation_epigenetic_age"
    assert payload["results"][0]["status"] == "not_determinable"
    assert payload["results"][0]["confidence_tier"] is None

    before = _json(["runs", "search", run, "MTHFR", "--json"])
    changed = tuple(
        dataclasses.replace(card, status="no_call", confidence_tier=None, confidence=None)
        if card.card_id == "mthfr_c677t_homocysteine"
        else dataclasses.replace(card, confidence_tier="likely-artifact")
        if card.card_id == "mthfr_c677t_depression"
        else card
        for card in saved.cards
    )
    monkeypatch.setattr(
        store, "load_run", lambda *a, **k: dataclasses.replace(saved, cards=changed)
    )
    after = _json(["runs", "search", run, "MTHFR", "--json"])
    assert after["current_context"] == before["current_context"]
    assert len(after["results"]) == 4
    faces = {result["card_id"]: result for result in after["results"]}
    assert faces["mthfr_c677t_homocysteine"]["status"] == "no_call"
    assert faces["mthfr_c677t_depression"]["confidence_tier"] == "likely-artifact"


def test_the_run_search_text_shows_each_card_s_tier_and_saved_summary(saved: RunBundle) -> None:
    run = saved.path.name
    text = _text(["runs", "search", run, "curly hair"])
    lines = text.splitlines()
    card = reads.find_card(saved, "wnt10a_hair_curl")
    assert card is not None and card.confidence_tier is not None
    assert lines[0].startswith(f"1 of {len(CARD_IDS)} card(s) in run {run} matches 'curly hair'")
    assert lines[1].split()[:3] == [card.confidence_tier, "traits", "wnt10a_hair_curl"]
    assert lines[2].strip() == card.summary
    assert lines[3].strip().startswith("2 of 2 term(s), score ")
    assert lines[-1] == f"`genetics runs card {run} <card-id>` prints one in full."
    # A card with no tier shows its status in that column, as `runs show` does.
    assert "  not_determinable " in _text(["runs", "search", run, "methylation"])
    assert _text(["runs", "search", run, "zzzunmatchable"]).startswith(f"No card in run {run} ")


def test_a_run_search_limit_cuts_results_and_hits_together(saved: RunBundle) -> None:
    payload = _json(["runs", "search", saved.path.name, "MTHFR", "--limit", "1", "--json"])
    context = payload["current_context"]
    assert context["limit"] == 1 and context["total"] == 4
    assert len(payload["results"]) == len(context["hits"]) == 1
    assert "Showing the best 1." in _text(
        ["runs", "search", saved.path.name, "MTHFR", "--limit", "1"]
    )


def test_a_bundle_another_version_wrote_is_searched_defensively(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Odd or missing nested shapes are skipped, never raised: the run was read successfully."""
    odd = tuple(
        dataclasses.replace(
            card,
            variant={"rsid": 7},
            evidence={"effect": "large"},
            carrier={"condition": None},
            multi_marker={"markers": [None, {"variant": {"rsid": "rs0000001"}}, "x"]},
            computation={"result": {"authored": {"trait": "an invented trait", "pgs_id": 3}}},
            citations=({"title": None, "id": 12}, {"note": "an invented note"}),
            section="a_later_section",
        )
        for card in saved.cards
    )
    monkeypatch.setattr(store, "load_run", lambda *a, **k: dataclasses.replace(saved, cards=odd))
    run = saved.path.name
    for query, field in (
        ("rs0000001", "variant"),
        ("invented trait", "trait"),
        ("invented note", "citations"),
        ("later section", "section"),
    ):
        hits = _json(["runs", "search", run, query, "--json"])["current_context"]["hits"]
        assert len(hits) == len(CARD_IDS), query
        assert field in {match["field"] for match in hits[0]["matched"]}, query


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize(
    ("query", "kind"), [("?!", "empty-query"), (GENOTYPE_QUERY, "genotype-in-query")]
)
@pytest.mark.parametrize("command", [["cards", "search"], ["runs", "search", MISSING_RUN]])
def test_an_unsearchable_query_is_a_usage_error_before_anything_is_read(
    agent_schema_check: Check, command: list[str], query: str, kind: str, as_json: bool
) -> None:
    """Exit 2, and before the run is opened: the run named here does not exist."""
    result = runner.invoke(app, [*command, query, *(["--json"] if as_json else [])])
    assert result.exit_code == 2
    if as_json:
        document = json.loads(result.stdout)
        assert agent_schema_check(document) == "error"
        assert document["error"]["kind"] == kind
    else:
        assert result.stdout == "" and result.stderr.strip()
    # A refused query is never repeated, in either stream.
    assert query not in result.output
    assert find_genotypes(result.output) == []


@pytest.mark.parametrize("as_json", [False, True])
def test_a_run_search_reports_an_unknown_run_like_every_other_read(
    saved: RunBundle, agent_schema_check: Check, as_json: bool
) -> None:
    result = runner.invoke(
        app, ["runs", "search", MISSING_RUN, "hair", *(["--json"] if as_json else [])]
    )
    assert result.exit_code == 1
    if as_json:
        document = json.loads(result.stdout)
        assert agent_schema_check(document) == "error"
        assert document["error"]["kind"] == "not-found"
    else:
        assert MISSING_RUN in result.stderr


def test_a_pack_that_cannot_be_loaded_is_a_knowledge_error(
    tmp_path: Path, agent_schema_check: Check
) -> None:
    document = _json(
        ["cards", "search", "hair", "--knowledge", str(tmp_path / "none"), "--json"], code=1
    )
    assert agent_schema_check(document) == "error"
    assert document["error"]["kind"] == "knowledge"


def test_a_search_without_a_query_is_rejected_by_the_command_line(saved: RunBundle) -> None:
    for args in (["cards", "search"], ["runs", "search", saved.path.name]):
        result = runner.invoke(app, [*args, "--json"])
        assert result.exit_code == 2 and result.stdout == "", args


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_the_pack_search_holds_no_genotype_and_the_run_search_holds_the_reader_s(
    saved: RunBundle,
) -> None:
    for extra in ([], ["--json"]):
        assert find_genotypes(_text(["cards", "search", "rs7349332", *extra])) == []
    held = _json(["runs", "search", saved.path.name, "hair", "--json"])
    card = reads.find_card(saved, "wnt10a_hair_curl")
    assert card is not None and card.match["genotype"]
    assert card.match["genotype"] in held["results"][0]["summary"]
    pack = json.dumps(_json(["cards", "search", "hair", "--json"]))
    assert card.summary not in pack and "summary" not in json.loads(pack)["hits"][0]


@pytest.mark.privacy
@pytest.mark.parametrize("as_json", [False, True])
def test_both_pack_search_branches_refuse_to_emit_a_genotype(
    monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    real = engine.pack_view

    def dirty(*args: Any, **kwargs: Any) -> dict[str, Any]:
        view = real(*args, **kwargs)
        view["hits"][0]["title"] = DIRTY
        return view

    monkeypatch.setattr(engine, "pack_view", dirty)
    result = runner.invoke(app, ["cards", "search", "hair", *(["--json"] if as_json else [])])
    assert isinstance(result.exception, GenotypeLeakError)
    assert DIRTY not in result.output


# ---------------------------------------------------------------------------
# Redirected output on Windows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        ["cards", "search", "homocysteine", "folate"],
        ["cards", "search", "homocysteine", "--json"],
        ["runs", "search", "{run}", "homocysteine"],
        ["runs", "search", "{run}", "homocysteine", "--json"],
    ],
)
def test_search_survives_a_legacy_code_page(
    saved: RunBundle, tmp_path: Path, arguments: list[str]
) -> None:
    """``CliRunner`` substitutes a UTF-8 stream; a pipe on Windows gets cp1252 (M11.6)."""
    environment = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "GENETICS_DATA_DIR": str(tmp_path / "data"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "genetics.cli.main",
            *(a.format(run=saved.path.name) for a in arguments),
        ],
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"mthfr_c677t_homocysteine" in result.stdout
