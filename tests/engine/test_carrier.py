"""M11.5: carrier declarations, the carrier panel, and saved carrier state.

Every genotype here is fabricated at the authored card's own coordinates. Nothing is read
from a personal export.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine.cards import (
    Card,
    CardError,
    CarrierState,
    KnowledgePack,
    parse_file,
)
from genetics.engine.carrier import (
    PANEL_SCHEMA_VERSION,
    STATE_LABELS,
    CarrierRecordError,
    carrier_panel,
    carrier_record,
    validate_record,
)
from genetics.engine.confidence import ConfidenceTier
from genetics.engine.evidence import AssembledCard, assemble_card
from genetics.engine.matcher import MatchStatus, is_strand_ambiguous, match_pack
from genetics.engine.sections import Section
from genetics.ingest.keys import MergeTable
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.privacy import assert_no_genotype
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    CARDS_NAME,
    MANIFEST_NAME,
    BundleError,
    _card_payload,
    _check_carriers,
    read_bundle,
    write_bundle,
)
from genetics.run.pipeline import observations
from genetics.web import WebConfig, create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"

EXPECTED_PANEL = {
    "hbb_hbs_carrier": ("rs334", "A"),
    "cftr_g542x_carrier": ("rs113993959", "T"),
    "cftr_w1282x_carrier": ("rs77010898", "A"),
    "cftr_g551d_carrier": ("rs75527207", "A"),
    "cftr_621_1g_t_carrier": ("rs78756941", "T"),
    "cftr_n1303k_carrier": ("rs80034486", "G"),
    "cftr_r553x_carrier": ("rs74597325", "T"),
    "pah_r408w_carrier": ("rs5030858", "A"),
    "pah_ivs10_11g_a_carrier": ("rs5030855", "T"),
    "pah_r261q_carrier": ("rs5030849", "T"),
    "acadm_k304e_carrier": ("rs77931234", "G"),
    "gba_n370s_carrier": ("rs76763715", "C"),
    "hexa_ivs12_1g_c_carrier": ("rs147324677", "G"),
    "aspa_e285a_carrier": ("rs28940279", "C"),
    "fancc_ivs4_4a_t_carrier": ("rs104886456", "A"),
    "hfe_c282y_iron_overload": ("rs1800562", "A"),
}
"""Pinned rather than derived from the pack, so a card silently dropped from the panel --
or a pathogenic allele flipped to the reference base -- fails here instead of shrinking
what M11.6 will say the report covers."""


@pytest.fixture(scope="module")
def pack() -> KnowledgePack:
    return KnowledgePack.load(KNOWLEDGE)


def _carrier_cards(pack: KnowledgePack) -> list[Card]:
    return [card for card in pack.cards if card.carrier is not None]


def _table(card: Card, pair: str | None, *, absent: bool = False) -> GenotypeTable:
    assert card.match is not None
    variant = card.match.variant
    rows = (
        []
        if absent
        else [
            {
                "rsid": variant.rsid,
                "chrom": variant.key.chrom.value,
                "pos_grch37": variant.key.pos_grch37,
                "a1": pair[0] if pair else None,
                "a2": pair[1] if pair else None,
                "genotype": pair,
                "call_status": "called" if pair else "no_call",
            }
        ]
    )
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")


def _assemble(card: Card, pair: str | None, *, absent: bool = False) -> AssembledCard:
    single = KnowledgePack((card,), Path("synthetic-memory"))
    match = match_pack(single, _table(card, pair, absent=absent), merges=MergeTable.empty())[0]
    return assemble_card(card, match, observations(single, (match,))[card.id])


def _pair(card: Card, copies: int) -> str:
    assert card.carrier is not None and card.match is not None
    allele = card.carrier.pathogenic_allele
    other = next(a for a in card.match.variant.key.alleles if a != allele)
    return "".join(sorted(allele * copies + other * (2 - copies)))


# ---------------------------------------------------------------------------
# The committed panel
# ---------------------------------------------------------------------------


def test_the_panel_is_exactly_the_authored_carrier_markers(pack: KnowledgePack) -> None:
    panel = carrier_panel(pack)
    assert {e.card_id: (e.rsid, e.declaration.pathogenic_allele) for e in panel.entries} == (
        EXPECTED_PANEL
    )
    assert len(panel.conditions) == 9
    reproductive = {c.id for c in pack.in_section(Section.REPRODUCTIVE) if c.match is not None}
    assert reproductive == {e.card_id for e in panel.entries if e.section == "reproductive"}
    data = panel.to_dict()
    assert data["schema_version"] == PANEL_SCHEMA_VERSION
    assert [e["card_id"] for e in data["entries"]] == [e.card_id for e in panel.entries]
    assert all(e["inheritance"] == "autosomal_recessive" for e in data["entries"])
    # A property of the pack, identical for every run: no genotype can be in it.
    assert_no_genotype(json.dumps(data), context="carrier panel")


def test_every_committed_carrier_card_reads_one_forward_autosomal_marker(
    pack: KnowledgePack,
) -> None:
    for card in _carrier_cards(pack):
        assert card.match is not None and card.carrier is not None
        assert card.match.forward_only and card.match.variant.key.chrom.is_autosome
        assert all(outcome.risk_context for outcome in card.outcomes.values())
        assert card.carrier.typed_scope.startswith("This card types")


def _misdirected(card: Card) -> list[int]:
    """Copy counts whose authored face does not say what the derived state says."""
    assert card.match is not None
    words = ("no ", "one ", "two ")
    return [
        copies
        for copies in range(3)
        if words[copies]
        not in card.outcomes[card.match.genotypes[_pair(card, copies)]].summary.lower()
    ]


def test_a_swapped_genotype_map_is_caught_by_the_direction_check(pack: KnowledgePack) -> None:
    card = pack.by_id("cftr_g542x_carrier")
    assert card is not None and card.match is not None and not _misdirected(card)
    genotypes = dict(card.match.genotypes)
    genotypes["GG"], genotypes["GT"] = genotypes["GT"], genotypes["GG"]
    swapped = replace(card, match=replace(card.match, genotypes=genotypes))
    assert _misdirected(swapped) == [0, 1]


@pytest.mark.parametrize("card_id", sorted(EXPECTED_PANEL))
def test_each_copy_count_reaches_its_own_state_and_direction(
    pack: KnowledgePack, card_id: str
) -> None:
    card = pack.by_id(card_id)
    assert card is not None and card.carrier is not None and card.match is not None
    symmetric = is_strand_ambiguous(card.match.variant.key.alleles)
    # The authored face must say what the derived state says. A map that sent the
    # heterozygote to the no-copy text passes every schema check except this one.
    assert not _misdirected(card)
    seen = set()
    for copies, state in enumerate(CarrierState):
        pair = _pair(card, copies)
        outcome = card.match.genotypes[pair]
        seen.add(outcome)
        assembled = _assemble(card, pair)
        assert assembled.carrier is not None
        if symmetric and copies != 1:
            # No copy and two copies read identically at an A/T or C/G site.
            assert assembled.status is MatchStatus.STRAND_AMBIGUOUS
            assert assembled.carrier["state"] is None
            assert assembled.carrier["pathogenic_copies"] is None
            continue
        assert assembled.status is MatchStatus.MATCHED
        assert assembled.match.outcome_name == outcome
        assert assembled.carrier["state"] == state.value
        assert assembled.carrier["pathogenic_copies"] == copies
        assert assembled.risk_context == card.outcomes[outcome].risk_context
        if copies != 1 and card.section is Section.REPRODUCTIVE:
            assert assembled.card.evidence is None
            assert assembled.confidence is not None
            assert assembled.confidence.tier in {
                ConfidenceTier.LIMITED,
                ConfidenceTier.LIKELY_ARTIFACT,
            }
        if copies == 1 and card.section is Section.REPRODUCTIVE:
            assert assembled.card.evidence is card.evidence
    assert len(seen) == 3


def test_strand_symmetric_markers_are_flagged_on_the_panel(pack: KnowledgePack) -> None:
    flagged = {e.card_id for e in carrier_panel(pack).entries if e.strand_symmetric}
    assert flagged == {
        "hbb_hbs_carrier",
        "cftr_n1303k_carrier",
        "hexa_ivs12_1g_c_carrier",
        "fancc_ivs4_4a_t_carrier",
    }


@pytest.mark.parametrize(
    "case",
    ["absent", "no_call", "complement"],
)
def test_no_interpretation_is_never_a_non_carrier(pack: KnowledgePack, case: str) -> None:
    card = pack.by_id("cftr_g542x_carrier")
    assert card is not None
    if case == "absent":
        assembled = _assemble(card, None, absent=True)
    elif case == "no_call":
        assembled = _assemble(card, None)
    else:
        # The complement of G/T is C/A: forward-only reads it as another variant.
        assembled = _assemble(card, "AC")
    assert assembled.status is not MatchStatus.MATCHED
    assert assembled.carrier is not None
    assert assembled.carrier["state"] is None and assembled.carrier["pathogenic_copies"] is None
    assert assembled.confidence is None and assembled.risk_context is None


def test_cards_without_a_declaration_carry_no_record(pack: KnowledgePack) -> None:
    card = pack.by_id("f5_leiden_thromboembolism")
    assert card is not None and card.carrier is None
    assembled = _assemble(card, "CC")
    assert assembled.carrier is None
    assert carrier_record(card, assembled.match) is None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _card_yaml(**changes: Any) -> dict[str, Any]:
    card: dict[str, Any] = {
        "id": "synthetic_carrier",
        "section": "reproductive",
        "kind": "interpretation",
        "title": "Synthetic carrier",
        "gene": "SYN1",
        "carrier": {
            "condition": "Synthetic recessive condition",
            "inheritance": "autosomal_recessive",
            "variant": "SYN1 c.1A>G",
            "pathogenic_allele": "G",
            "clinvar": 1,
            "typed_scope": "This card types c.1A>G only.",
        },
        "match": {
            "strand": "forward_only",
            "variants": [
                {"rsid": "rs900000001", "chrom": "1", "pos_grch37": 1000, "alleles": ["A", "G"]}
            ],
            "genotypes": {"AA": "none", "AG": "one", "GG": "two"},
        },
        "outcomes": {
            name: {"summary": name, "detail": name, "risk_context": f"{name} context"}
            for name in ("none", "one", "two")
        },
        "evidence": {
            "tier": "cohort",
            "replication": "independent",
            "sample_size": 100,
            "ancestry": ["EUR"],
            "effect": {"measure": "proportion", "value": 0.5, "context": "synthetic share"},
        },
        "citations": [{"type": "doi", "id": "10.1234/synthetic", "title": "Synthetic"}],
    }
    for path, value in changes.items():
        target = card
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[key]
        if value is KeyError:
            del target[keys[-1]]
        else:
            target[keys[-1]] = value
    return card


def _parse(card: dict[str, Any], version: int = 7) -> tuple[Card, ...]:
    return parse_file(yaml.safe_dump({"schema_version": version, "cards": [card]}), "synthetic")


def test_a_valid_declaration_parses() -> None:
    (card,) = _parse(_card_yaml())
    assert card.carrier is not None and card.carrier.state("AG") is CarrierState.CARRIER


@pytest.mark.parametrize(
    "changes,message",
    [
        (
            {
                "match.genotypes": {"AA": "none", "AG": "none", "GG": "two"},
                "outcomes.one": KeyError,
            },
            "own outcome",
        ),
        ({"carrier.pathogenic_allele": "T"}, "two declared alleles"),
        ({"carrier.pathogenic_allele": "GG"}, "one base"),
        ({"match.strand": "infer"}, "forward_only"),
        ({"match.strand": KeyError}, "forward_only"),
        ({"carrier.inheritance": "x_linked"}, "not supported"),
        (
            {
                "match.variants": [
                    {"rsid": "rs900000001", "chrom": "X", "pos_grch37": 1000, "alleles": ["A", "G"]}
                ]
            },
            "autosomal",
        ),
        ({"outcomes.two.risk_context": KeyError}, "requires risk_context"),
        ({"carrier.typed_scope": "Types {gene} only."}, "typed_scope"),
        ({"carrier.typed_scope": " "}, "nonempty"),
        ({"carrier.clinvar": "VCV1"}, "VariationID"),
        ({"carrier.clinvar": True}, "VariationID"),
        ({"carrier.extra": 1}, "extra"),
        ({"carrier": KeyError}, "declares carrier"),
        ({"section": "traits"}, "reproductive or physical health"),
    ],
    ids=[
        "merged_outcomes",
        "allele_not_declared",
        "allele_not_a_base",
        "strand_infer",
        "strand_default",
        "x_linked",
        "x_chromosome",
        "missing_risk",
        "placeholder_scope",
        "empty_scope",
        "clinvar_text",
        "clinvar_bool",
        "unknown_key",
        "reproductive_without_carrier",
        "wrong_section",
    ],
)
def test_schema_refuses_an_unbound_declaration(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(CardError, match=message):
        _parse(_card_yaml(**changes))


def test_declarations_require_schema_seven() -> None:
    with pytest.raises(CardError, match="schema_version 7"):
        _parse(_card_yaml(), version=6)


def test_only_interpretation_cards_declare_carrier() -> None:
    impossibility = {
        "id": "synthetic_limit",
        "section": "reproductive",
        "kind": "impossibility",
        "title": "Synthetic limit",
        "impossibility_reason": "Synthetic.",
        "summary": "Not determinable.",
        "detail": "Synthetic.",
        "carrier": _card_yaml()["carrier"],
    }
    with pytest.raises(CardError, match="single-marker interpretation"):
        _parse(impossibility)


# ---------------------------------------------------------------------------
# Saved runs, CLI and dashboard
# ---------------------------------------------------------------------------


def _write(pack: KnowledgePack, cards: tuple[AssembledCard, ...], qc: QCReport, root: Path) -> Path:
    return write_bundle(
        qc=qc,
        cards=cards,
        pack=pack,
        ancestry=AncestryContext.not_run("synthetic carrier acceptance"),
        runs_root=root,
        run_id="20261025T000000Z-ca11e500",
        lock_path=root / "absent.lock",
        tools_root=root / "tools",
    )


@pytest.fixture
def saved(
    pack: KnowledgePack, sample_qc: QCReport, tmp_path: Path
) -> tuple[Path, tuple[AssembledCard, ...]]:
    hbs = pack.by_id("hbb_hbs_carrier")
    g542x = pack.by_id("cftr_g542x_carrier")
    w1282x = pack.by_id("cftr_w1282x_carrier")
    assert hbs is not None and g542x is not None and w1282x is not None
    cards = (
        _assemble(hbs, _pair(hbs, 1)),
        _assemble(g542x, _pair(g542x, 1)),
        _assemble(w1282x, None, absent=True),
    )
    subset = KnowledgePack((hbs, g542x, w1282x), pack.source_dir)
    return _write(subset, cards, sample_qc, tmp_path / "runs"), cards


def test_save_read_cli_and_dashboard_parity(
    saved: tuple[Path, tuple[AssembledCard, ...]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, cards = saved
    bundle = read_bundle(path)
    assert bundle.format_version == BUNDLE_FORMAT_VERSION == 24
    assert [c.carrier for c in bundle.cards] == [c.carrier for c in cards]
    states = [None if c.carrier is None else c.carrier["state"] for c in bundle.cards]
    assert states == ["carrier", "carrier", None]
    # The A/T heterozygote is recorded without an oriented genotype, as the matcher leaves it.
    assert bundle.cards[0].match["genotype"] is None

    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    shown = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert shown.exit_code == 0, shown.output
    assert [c["carrier"] for c in json.loads(shown.stdout)["cards"]] == [c.carrier for c in cards]
    text = CliRunner().invoke(app, ["runs", "show", path.name])
    assert text.exit_code == 0
    assert f"Carrier: {STATE_LABELS['carrier']}" in text.stdout
    assert f"Carrier: {STATE_LABELS[None]}" in text.stdout

    hbs = cards[0].carrier
    assert hbs is not None
    with TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        face = html.unescape(client.get(f"/runs/{path.name}?section=reproductive").text)
        detail = html.unescape(client.get(f"/runs/{path.name}/cards/hbb_hbs_carrier").text)
    assert f"Carrier status: {STATE_LABELS['carrier']}" in face
    assert f"Carrier status: {STATE_LABELS[None]}" in face
    assert hbs["typed_scope"] in face and hbs["typed_scope"] in detail
    assert "VariationID 15333" in detail and hbs["variant"] in detail
    assert "no offspring risk is computed" in detail


Mutation = Callable[[dict[str, Any]], None]


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda c: c["carrier"].update(state="non_carrier"), "follow from the saved call"),
        (lambda c: c["carrier"].update(pathogenic_copies=2), "follow from the saved call"),
        (lambda c: c["carrier"].update(pathogenic_copies=True), "follow from the saved call"),
        (lambda c: c["carrier"].update(pathogenic_allele="C"), "one of the card's alleles"),
        (lambda c: c["carrier"].update(inheritance="x_linked"), "inheritance"),
        (lambda c: c["carrier"].update(clinvar=0), "VariationID"),
        (lambda c: c["carrier"].pop("typed_scope"), "wrong fields"),
        (lambda c: c["carrier"].update(condition=""), "condition"),
        (lambda c: c.update(kind="computed"), "single-marker interpretation"),
        (lambda c: c["match"].update(genotype="TT"), "follow from the saved call"),
        (lambda c: c["match"].update(genotype="AA"), "lacks a call"),
        (lambda c: c["match"].update(genotype=None), "lacks a call"),
    ],
    ids=[
        "state",
        "copies",
        "bool_copies",
        "allele",
        "inheritance",
        "clinvar",
        "missing_field",
        "empty_condition",
        "kind",
        "genotype",
        "foreign_genotype",
        "no_genotype",
    ],
)
def test_saved_records_must_follow_from_their_own_call(
    saved: tuple[Path, tuple[AssembledCard, ...]], mutate: Mutation, message: str
) -> None:
    _, cards = saved
    payload = _card_payload(cards[1])
    validate_record(payload)
    mutate(payload)
    with pytest.raises(CarrierRecordError, match=message):
        validate_record(payload)


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda c: c["match"].update(observed_genotype="AA"), "cannot fix"),
        (lambda c: c["match"].update(observed_genotype=None), "lacks a call"),
        (lambda c: c["match"].update(strand="as_written"), "lacks a call"),
        (lambda c: c["match"].update(observed_genotype="CG"), "cannot fix"),
    ],
    ids=["homozygous_letters", "no_letters", "oriented_strand", "foreign_letters"],
)
def test_ambiguous_strand_records_are_bound_to_the_observed_heterozygote(
    saved: tuple[Path, tuple[AssembledCard, ...]], mutate: Mutation, message: str
) -> None:
    _, cards = saved
    payload = _card_payload(cards[0])
    assert payload["match"]["strand"] == "ambiguous"
    validate_record(payload)
    mutate(payload)
    with pytest.raises(CarrierRecordError, match=message):
        validate_record(payload)


def test_unmatched_records_cannot_claim_a_state(
    saved: tuple[Path, tuple[AssembledCard, ...]],
) -> None:
    _, cards = saved
    payload = _card_payload(cards[2])
    validate_record(payload)
    payload["carrier"].update(state="non_carrier", pathogenic_copies=0)
    with pytest.raises(CarrierRecordError, match="follow from the saved call"):
        validate_record(payload)


def test_carrier_records_require_format_24(
    saved: tuple[Path, tuple[AssembledCard, ...]],
) -> None:
    _, cards = saved
    payload = _card_payload(cards[0])
    _check_carriers([payload], 24)
    with pytest.raises(BundleError, match="bundle format 24"):
        _check_carriers([payload], 23)


def test_a_damaged_saved_record_is_refused_on_read(
    saved: tuple[Path, tuple[AssembledCard, ...]],
) -> None:
    import hashlib

    path, _ = saved
    cards_file = path / CARDS_NAME
    data = json.loads(cards_file.read_text(encoding="utf-8"))
    data["cards"][0]["carrier"]["state"] = "non_carrier"
    cards_file.write_text(json.dumps(data), encoding="utf-8")
    manifest_file = path / MANIFEST_NAME
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["files"][CARDS_NAME] = hashlib.sha256(cards_file.read_bytes()).hexdigest()
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="carrier card is inconsistent"):
        read_bundle(path)


def test_cards_carriers_cli_lists_the_panel(pack: KnowledgePack) -> None:
    result = CliRunner().invoke(app, ["cards", "carriers", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == carrier_panel(pack).to_dict()
    text = CliRunner().invoke(app, ["cards", "carriers"])
    assert text.exit_code == 0
    assert "16 typed marker(s) across 9 condition(s)" in text.stdout
    assert "rs334" in text.stdout and "outside this panel" in text.stdout
    assert text.stdout.count("strand-symmetric: homozygotes not oriented") == 4
