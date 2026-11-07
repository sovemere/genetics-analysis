"""M11.6: the section-level statement of what carrier screening from this array leaves out.

Every genotype here is fabricated at the authored card's own coordinates. Nothing is read
from a personal export.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
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
from genetics.engine.cards import Card, CardError, KnowledgePack, parse_file
from genetics.engine.carrier import carrier_panel
from genetics.engine.carrier_scope import (
    ALLELE_CLASSES,
    NOT_RECORDED,
    SOURCE,
    _build,
    assemble_scope_card,
    check_pack,
    pack_scope,
    scope_caveats,
    scope_reliability,
    scope_summary,
    section_notice,
)
from genetics.engine.confidence import CallSource
from genetics.engine.evidence import AssembledCard, ObservationEvidence, assemble_card
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.engine.sections import Section
from genetics.ingest.keys import LocusKey, MergeTable
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.pgs.cards import assemble_polygenic_card
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
from genetics.run.pipeline import analyse, observations
from genetics.web import WebConfig, create_app

ROOT = Path(__file__).parents[2]
KNOWLEDGE = ROOT / "knowledge"
CARD_ID = "carrier_screening_scope"

TYPED = {
    "HBB": 1,
    "CFTR": 6,
    "PAH": 3,
    "ACADM": 1,
    "GBA1": 1,
    "HEXA": 1,
    "ASPA": 1,
    "FANCC": 1,
}
ASSAY_LIMITED = {"SMN1", "HBA1", "HBA2", "DMD", "FMR1", "FXN", "F8"}


@pytest.fixture(scope="module")
def pack() -> KnowledgePack:
    return KnowledgePack.load(KNOWLEDGE)


@pytest.fixture(scope="module")
def scope(pack: KnowledgePack) -> dict[str, Any]:
    result = pack_scope(pack)
    assert result is not None
    return result


def _scope_card(pack: KnowledgePack) -> Card:
    card = pack.by_id(CARD_ID)
    assert card is not None
    return card


def _carriers(pack: KnowledgePack) -> list[Card]:
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


def _run_cards(pack: KnowledgePack) -> tuple[AssembledCard, ...]:
    """One each of the interesting results, every other carrier marker read as no copy."""
    special: dict[str, tuple[str | None, bool]] = {
        "cftr_g542x_carrier": ("GT", False),  # one copy
        "pah_r408w_carrier": ("AA", False),  # two copies
        "cftr_g551d_carrier": (None, False),  # on the array, no call
        "acadm_k304e_carrier": (None, True),  # not on the array
    }
    cards = []
    for card in _carriers(pack):
        if card.id in special:
            pair, absent = special[card.id]
            cards.append(_assemble(card, pair, absent=absent))
        else:
            # A/T and C/G homozygotes cannot be oriented, so these report strand ambiguity.
            cards.append(_assemble(card, _pair(card, 0)))
    return tuple(cards)


# ---------------------------------------------------------------------------
# The reference list and the comparison
# ---------------------------------------------------------------------------


def test_the_reference_list_has_the_rows_the_source_tables_have(pack: KnowledgePack) -> None:
    declaration = _scope_card(pack).screening_scope
    assert declaration is not None
    reference = declaration["reference"]
    assert reference["citation"] == "10.1038/s41436-021-01203-z"
    rows: dict[int, int] = {}
    for gene in reference["genes"]:
        rows[gene["table"]] = rows.get(gene["table"], 0) + 1
    assert rows == {1: 19, 2: 19, 3: 25, 4: 23, 5: 11, 6: 16}
    # Gregg 2021 states both totals: 86 genes in Tables 1-4, and 97 with Table 5.
    assert sum(rows[t] for t in (1, 2, 3, 4)) == 86
    assert sum(rows[t] for t in (1, 2, 3, 4, 5)) == 97
    names = {g["gene"] for g in reference["genes"]}
    # G6PC is on the list; G6PD and HFE are not. The card's text depends on the difference.
    assert "G6PC" in names and not {"G6PD", "HFE"} & names
    assert {g["gene"]: g["listed_as"] for g in reference["genes"] if "listed_as" in g} == {
        "GBA1": "GBA"
    }


def test_every_reference_gene_has_exactly_one_status(scope: dict[str, Any]) -> None:
    genes, counts = scope["genes"], scope["counts"]
    assert {g["gene"]: g["markers"] for g in genes["typed"]} == TYPED
    assert {g["gene"] for g in genes["assay_limited"]} == ASSAY_LIMITED
    assert genes["typed_outside_reference"] == ["HFE"]
    assert counts == {
        "reference_genes": 113,
        "autosomal_recessive": 97,
        "x_linked": 16,
        "typed": 8,
        "assay_limited": 7,
        "no_card": 98,
    }
    statuses = [
        *(g["gene"] for g in genes["typed"]),
        *(g["gene"] for g in genes["assay_limited"]),
        *(g["gene"] for g in genes["no_card"]),
    ]
    listed = {g["gene"] for g in scope["declaration"]["reference"]["genes"]}
    assert len(statuses) == len(set(statuses)) and set(statuses) == listed


def test_the_panel_in_the_scope_is_the_carrier_panel(
    pack: KnowledgePack, scope: dict[str, Any]
) -> None:
    panel = carrier_panel(pack)
    assert scope["panel"]["markers"] == len(panel.entries) == 16
    assert set(scope["panel"]["conditions"]) == set(panel.conditions)
    assert {e["rsid"] for e in scope["panel"]["entries"]} == {e.rsid for e in panel.entries}
    assert scope["panel"]["strand_symmetric"] == 4
    assert scope["panel"]["dbsnp_multiallelic"] == 12


def test_excluded_alleles_never_count_as_typed(pack: KnowledgePack, scope: dict[str, Any]) -> None:
    panel = {e.rsid for e in carrier_panel(pack).entries}
    declared = scope["declaration"]["excluded_alleles"]
    assert not panel & {a["rsid"] for a in declared}
    assert scope["excluded_alleles"] == {
        "indel": 5,
        "not_on_array": 9,
        "failed_criterion": 4,
        "not_authored": 20,
    }


def test_a_gap_in_this_report_does_not_read_as_an_assay_limit(scope: dict[str, Any]) -> None:
    summary = scope_summary(scope)
    assert "a gap in this report and not a measured limit of the array" in summary
    assert "Gap in this report" in ALLELE_CLASSES["not_authored"]
    assert "limit" not in ALLELE_CLASSES["not_authored"].lower()
    assert ALLELE_CLASSES["indel"].startswith("Assay limit")


def test_the_audit_document_and_the_declaration_list_the_same_alleles(
    scope: dict[str, Any],
) -> None:
    doc = (ROOT / "docs/carrier_status.md").read_text(encoding="utf-8")
    audit = doc[doc.index("## Candidate audit") : doc.index("## Residual limits")]
    declared = {a["rsid"] for a in scope["declaration"]["excluded_alleles"]}
    assert set(re.findall(r"rs\d+", audit)) == declared


def test_the_face_says_what_the_section_is_not(scope: dict[str, Any]) -> None:
    summary = scope_summary(scope)
    assert summary.startswith("This is not a carrier screen.")
    assert "16 markers for 9 conditions" in summary
    assert "113 genes (97 autosomal recessive, 16 X-linked)" in summary
    assert "would still not be a negative screen" in summary
    caveats = " ".join(scope_caveats(scope))
    assert "12 of the 16 typed markers list another base" in caveats
    assert "4 of the 16 typed markers are A/T or C/G" in caveats
    assert "No detection rate, residual carrier risk or offspring risk is computed" in caveats


def test_the_saved_wording_is_pinned(pack: KnowledgePack) -> None:
    """A saved face is rebuilt and compared on read, so editing the text breaks old runs.

    If this fails on purpose: bump RESULT_SCHEMA_VERSION and keep the old wording for the
    records that hold it. Updating the expected text alone makes those runs unreadable.
    """
    built = assemble_scope_card(_scope_card(pack), _run_cards(pack))
    assert built.computation is not None
    assert built.computation["result"]["schema_version"] == 1
    assert built.summary == (
        "This is not a carrier screen. This report types 16 markers for 9 conditions. "
        "ACMG Tier 3 carrier screening names 113 genes (97 autosomal recessive, 16 X-linked). "
        "Of those, 8 have a typed marker here, and a typed marker reads one named allele rather "
        "than the gene; 7 depend largely on copy number, repeat length or inversion, which "
        "genotype calls cannot show; and 98 have no card, a gap in this report and not a "
        "measured limit of the array. In this run 10 of 16 typed markers gave a result and 6 "
        "were not determined. A no-copy result at every typed marker would still not be a "
        "negative screen."
    )
    assert built.computed_caveats == (
        "A result here covers named alleles only. No detection rate, residual carrier risk or "
        "offspring risk is computed. Only clinical sequencing can establish or exclude a "
        "variant.",
        "12 of the 16 typed markers list another base in dbSNP b157, and the array's probe "
        "alleles are unpublished, so a homozygous reference call cannot show that the probe "
        "tested the card's allele.",
        "4 of the 16 typed markers are A/T or C/G sites, where a homozygous direct call cannot "
        "be oriented: no copy and two copies look the same, so that call is reported as not "
        "determined. An imputed call there is reference-oriented and can give a result.",
    )


def test_an_old_record_does_not_need_a_class_added_later(scope: dict[str, Any]) -> None:
    assert set(scope["excluded_alleles"]) <= set(ALLELE_CLASSES)
    trimmed = copy.deepcopy(scope["declaration"])
    trimmed["excluded_alleles"] = [
        a for a in trimmed["excluded_alleles"] if a["class"] != "not_authored"
    ]
    assert "not_authored" not in _build(trimmed, [], None)["excluded_alleles"]


def test_the_card_makes_a_different_claim_from_the_per_gene_cards(pack: KnowledgePack) -> None:
    scope_card = _scope_card(pack)
    assert scope_card.section is Section.REPRODUCTIVE
    assert scope_card.citations
    text = scope_card.detail or ""
    for card_id in ("smn1_copy_number", "alpha_globin_deletions"):
        other = pack.by_id(card_id)
        assert other is not None and other.impossibility_reason is not None
        assert other.impossibility_reason not in text
        assert (other.summary or "") not in text


def test_the_pack_comparison_reads_no_genotype(scope: dict[str, Any]) -> None:
    assert scope["run"] is None
    assert_no_genotype(json.dumps(scope), context="carrier scope")


# ---------------------------------------------------------------------------
# One run's tally
# ---------------------------------------------------------------------------


def test_a_run_counts_results_and_keeps_missing_apart_from_no_copy(pack: KnowledgePack) -> None:
    cards = _run_cards(pack)
    built = assemble_scope_card(_scope_card(pack), cards)
    assert built.status is MatchStatus.COMPUTED
    assert built.computation is not None
    run = built.computation["result"]["run"]
    assert run == {
        "markers": 16,
        "with_result": 10,
        "imputed_results": 0,
        "no_copy": 8,
        "one_copy": 1,
        "two_copies": 1,
        # The four A/T and C/G homozygotes, the no-call and the absent marker.
        "not_determined": 6,
        "not_determined_by_status": {
            "marker_absent": 1,
            "no_call": 1,
            "strand_ambiguous": 4,
        },
    }
    assert "In this run 10 of 16 typed markers gave a result and 6 were not determined." in (
        built.summary
    )
    assert built.computation["reliability"]["tier"] == "limited"
    assert built.computation["reliability"]["inputs"]["residual_risk_estimated"] is False


def test_all_no_copy_is_still_not_a_negative_screen(pack: KnowledgePack) -> None:
    cards = tuple(_assemble(card, _pair(card, 0)) for card in _carriers(pack))
    built = assemble_scope_card(_scope_card(pack), cards)
    assert "would still not be a negative screen" in built.summary
    assert "negative screen" not in built.summary.replace(
        "A no-copy result at every typed marker would still not be a negative screen.", ""
    )


def _imputed(card: Card, pair: str) -> AssembledCard:
    """A call imputation filled: reference-oriented, with its quality recorded."""
    assert card.match is not None
    key = card.match.variant.key
    single = KnowledgePack((card,), Path("synthetic-memory"))
    match = match_pack(
        single,
        _table(card, pair),
        merges=MergeTable.empty(),
        reference_forward_loci=frozenset({LocusKey(key.chrom, key.pos_grch37)}),
    )[0]
    return assemble_card(
        card, match, ObservationEvidence(CallSource.IMPUTED, imputation_quality=0.95)
    )


def test_an_imputed_result_is_counted_and_never_reads_as_an_array_call(
    pack: KnowledgePack,
) -> None:
    hbs = pack.by_id("hbb_hbs_carrier")
    assert hbs is not None
    direct = _assemble(hbs, _pair(hbs, 0))
    assert direct.carrier is not None and direct.carrier["state"] is None
    # The same homozygote at an A/T marker is oriented when it came from imputation.
    filled = _imputed(hbs, _pair(hbs, 0))
    assert filled.carrier is not None and filled.carrier["state"] == "non_carrier"

    built = assemble_scope_card(_scope_card(pack), (filled,))
    assert built.computation is not None
    assert built.computation["result"]["run"]["imputed_results"] == 1
    assert "(1 imputed, not read from the array)" in built.summary
    caveats = " ".join(built.computed_caveats)
    assert "An imputed call there is reference-oriented" in caveats
    assert "1 result here came from imputation" in caveats
    assert "does not make a rare call reliable" in caveats

    payloads = [json.loads(json.dumps(_card_payload(c))) for c in (filled, built)]
    _check_carriers(payloads, BUNDLE_FORMAT_VERSION)
    payloads[0]["observation"]["call_source"] = "direct"
    with pytest.raises(BundleError, match="does not follow"):
        _check_carriers(payloads, BUNDLE_FORMAT_VERSION)


def test_without_a_run_the_card_is_not_run_and_carries_no_tier(pack: KnowledgePack) -> None:
    built = assemble_scope_card(_scope_card(pack), None, reason="Synthetic not-run reason.")
    assert built.status is MatchStatus.NOT_RUN
    assert built.summary == "Synthetic not-run reason."
    assert built.computation is not None
    assert built.computation["result"] is None
    assert built.computation["reliability"] == scope_reliability(None)


def test_the_pipeline_measures_it_from_the_assembled_carrier_cards(tmp_path: Path) -> None:
    (tmp_path / "reproductive").mkdir()
    for name in ("carrier.yaml", "scope.yaml"):
        (tmp_path / "reproductive" / name).write_bytes(
            (KNOWLEDGE / "reproductive" / name).read_bytes()
        )
    (tmp_path / "impossibilities").mkdir()
    (tmp_path / "impossibilities" / "structural_variants.yaml").write_bytes(
        (KNOWLEDGE / "impossibilities" / "structural_variants.yaml").read_bytes()
    )
    (tmp_path / "health").mkdir()
    (tmp_path / "health" / "common.yaml").write_bytes(
        (KNOWLEDGE / "health" / "common.yaml").read_bytes()
    )
    analysis = analyse(
        ROOT / "tests/fixtures/synthetic/ancestry_v2_male.txt",
        knowledge_dir=tmp_path,
        no_impute=True,
    )
    card = next(c for c in analysis.cards if c.card_id == CARD_ID)
    assert card.status is MatchStatus.COMPUTED
    assert card.computation is not None
    assert card.computation["result"]["run"]["markers"] == 16


# ---------------------------------------------------------------------------
# The schema
# ---------------------------------------------------------------------------


def _authored() -> dict[str, Any]:
    text = (KNOWLEDGE / "reproductive" / "scope.yaml").read_text(encoding="utf-8")
    loaded: dict[str, Any] = yaml.safe_load(text)
    return loaded


def _parse(changed: dict[str, Any]) -> tuple[Card, ...]:
    return parse_file(yaml.safe_dump(changed, allow_unicode=True), "synthetic.yaml")


def test_the_committed_declaration_parses_and_round_trips(pack: KnowledgePack) -> None:
    card = _parse(_authored())[0]
    assert card.screening_scope == _scope_card(pack).screening_scope
    assert json.loads(json.dumps(card.screening_scope)) == card.screening_scope


Change = Callable[[dict[str, Any]], None]


def _block(data: dict[str, Any]) -> dict[str, Any]:
    block: dict[str, Any] = data["cards"][0]["screening_scope"]
    return block


@pytest.mark.parametrize(
    "change,message",
    [
        (lambda d: d.update(schema_version=7), "schema_version 8"),
        (lambda d: d["cards"][0].pop("screening_scope"), "screening_scope"),
        (lambda d: d["cards"][0].update(section="genome_structure"), "unsupported computation"),
        (lambda d: d["cards"][0].update(computation="long_roh"), "unsupported computation"),
        (lambda d: d["cards"][0].update(citations=d["cards"][0]["citations"][1:]), "citations"),
        (lambda d: _block(d)["reference"]["genes"].append({"gene": "HBB"}), "expected fields"),
        (
            lambda d: _block(d)["reference"]["genes"].append(
                {"gene": "HBB", "table": 1, "condition": "Twice"}
            ),
            "listed twice",
        ),
        (lambda d: _block(d)["reference"]["genes"][0].update(gene="not a gene"), "gene symbol"),
        (lambda d: _block(d)["reference"]["genes"][0].update(table=9), "no caption"),
        (lambda d: _block(d)["reference"]["tables"].update({9: "Extra"}), None),
        (lambda d: _block(d)["assay_limits"][0].update(mechanism="vibes"), "mechanism"),
        (lambda d: _block(d)["assay_limits"][0].update(mechanism=["copy_number"]), "mechanism"),
        (lambda d: _block(d)["excluded_alleles"][0].update({"class": ["indel"]}), "class"),
        (lambda d: _block(d)["excluded_alleles"][0].update(allele="G>A"), "typed classes"),
        (lambda d: _block(d)["excluded_alleles"][-1].pop("allele"), "typed classes"),
        (lambda d: _block(d)["excluded_alleles"][-1].update(allele="GA"), "REF>ALT"),
        (lambda d: _block(d)["assay_limits"][0].update(gene="BRCA1"), "not in the reference"),
        (lambda d: _block(d)["excluded_alleles"][0].update({"class": "other"}), "class"),
        (lambda d: _block(d)["excluded_alleles"][0].update(rsid="i1234"), "not an rsID"),
        (lambda d: _block(d)["excluded_alleles"][0].pop("reason"), "expected fields"),
        (lambda d: _block(d)["excluded_alleles"].append(_block(d)["excluded_alleles"][0]), "twice"),
        (lambda d: _block(d)["dbsnp_multiallelic"].append("rs334"), "twice"),
        (lambda d: _block(d).update(extra=1), "expected fields"),
    ],
)
def test_the_schema_refuses_a_malformed_declaration(change: Change, message: str | None) -> None:
    data = copy.deepcopy(_authored())
    change(data)
    if message is None:
        _parse(data)  # A caption nothing uses is harmless, and must not be an error.
        return
    with pytest.raises(CardError, match=message):
        _parse(data)


def test_a_declaration_belongs_only_to_the_scope_card() -> None:
    coverage = yaml.safe_load((KNOWLEDGE / "health" / "coverage.yaml").read_text(encoding="utf-8"))
    coverage["schema_version"] = 8
    coverage["cards"][0]["screening_scope"] = _block(_authored())
    with pytest.raises(CardError, match="belongs to the carrier scope card"):
        _parse(coverage)
    carrier = yaml.safe_load(
        (KNOWLEDGE / "reproductive" / "carrier.yaml").read_text(encoding="utf-8")
    )
    carrier["schema_version"] = 8
    carrier["cards"] = carrier["cards"][:1]
    carrier["cards"][0]["screening_scope"] = _block(_authored())
    with pytest.raises(CardError, match="screening_scope belongs"):
        _parse(carrier)


@pytest.mark.parametrize(
    "change,message",
    [
        (
            lambda d: d["excluded_alleles"].append(
                {**d["excluded_alleles"][0], "rsid": "rs113993959"}
            ),
            "excluded alleles are in the panel",
        ),
        (lambda d: d["dbsnp_multiallelic"].append("rs1"), "not in the panel"),
        (lambda d: d["assay_limits"][0].update(gene="CFTR"), "both typed and an assay limit"),
        (lambda d: d["assay_limits"][0].update(card="cftr_g542x_carrier"), "not an impossibility"),
        (lambda d: d["assay_limits"][0].update(card="no_such_card"), "not an impossibility"),
    ],
)
def test_the_pack_refuses_a_declaration_that_contradicts_the_panel(
    pack: KnowledgePack, change: Change, message: str
) -> None:
    card = _scope_card(pack)
    declaration = copy.deepcopy(dict(card.screening_scope or {}))
    change(declaration)
    changed = replace(card, screening_scope=declaration)
    cards = [changed if c.id == CARD_ID else c for c in pack.cards]
    with pytest.raises(CardError, match=message):
        check_pack(cards, "synthetic")


# ---------------------------------------------------------------------------
# Saved runs, CLI and dashboard
# ---------------------------------------------------------------------------


def test_a_pack_with_two_scope_cards_is_refused_at_load(pack: KnowledgePack) -> None:
    card = _scope_card(pack)
    with pytest.raises(CardError, match="one carrier-screening scope card"):
        check_pack([*pack.cards, replace(card, id="second_scope")], "synthetic")


def _write(pack: KnowledgePack, cards: Sequence[AssembledCard], qc: QCReport, root: Path) -> Path:
    return write_bundle(
        qc=qc,
        cards=tuple(cards),
        pack=pack,
        ancestry=AncestryContext.not_run("synthetic carrier-scope acceptance"),
        runs_root=root,
        run_id="20261106T000000Z-5c09e000",
        lock_path=root / "absent.lock",
        tools_root=root / "tools",
    )


@pytest.fixture
def run(pack: KnowledgePack) -> tuple[AssembledCard, ...]:
    carriers = _run_cards(pack)
    return (*carriers, assemble_scope_card(_scope_card(pack), carriers))


def test_save_read_cli_and_dashboard_parity(
    pack: KnowledgePack,
    run: tuple[AssembledCard, ...],
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write(pack, run, sample_qc, tmp_path / "runs")
    bundle = read_bundle(path)
    assert bundle.format_version == BUNDLE_FORMAT_VERSION == 28
    saved = next(c for c in bundle.cards if c.card_id == CARD_ID)
    assert saved.computation is not None
    assert saved.computation["source"] == SOURCE
    assert saved.confidence_tier == "limited"
    notice = section_notice(bundle.cards)
    assert notice is not None and notice["text"] == saved.summary

    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    shown = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.stdout)
    record = next(c for c in payload["cards"] if c["card_id"] == CARD_ID)
    assert record["computation"]["result"] == saved.computation["result"]
    # The frozen inspection interface holds no current context (docs/pgx_framing.md).
    assert "current_context" not in payload
    text = CliRunner().invoke(app, ["runs", "show", path.name])
    assert text.exit_code == 0
    assert saved.summary in text.stdout

    with TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        detail = html.unescape(client.get(f"/runs/{path.name}/cards/{CARD_ID}").text)
        page = html.unescape(client.get(f"/runs/{path.name}").text)
        hidden = html.unescape(client.get(f"/runs/{path.name}?tier=well-established").text)
        by_tier = html.unescape(client.get(f"/runs/{path.name}?group=tier").text)
    assert "Scope and its limits" in detail
    assert "Not determined: strand ambiguous" in detail
    assert "SMN1" in detail and "F508del" in detail and "rs113993960" in detail
    assert "Gap in this report" in detail and "Assay limit" in detail
    assert "Gene status does not measure coverage within a gene." in detail
    assert "10.1038/s41436-021-01203-z" in detail
    # A filter or an arrangement can hide the card; it cannot hide the statement.
    for shown_page in (page, hidden, by_tier):
        assert shown_page.count(saved.summary) >= 1
    assert "Carrier screening scope" in hidden and "Carrier screening scope" in by_tier


def test_trait_cards_beside_the_carrier_cards_change_neither_the_tally_nor_the_statement(
    pack: KnowledgePack,
    run: tuple[AssembledCard, ...],
    sample_qc: QCReport,
    tmp_path: Path,
) -> None:
    """M11.7: the statement is about carrier screening, and a trait card is not part of one."""
    traits = tuple(
        assemble_polygenic_card(card, None, reason="Synthetic not-run reason.")
        for card in pack.in_section(Section.REPRODUCTIVE)
        if card.pgs is not None
    )
    assert len(traits) == 7
    alone = next(c for c in run if c.card_id == CARD_ID)
    beside = assemble_scope_card(_scope_card(pack), [c for c in run if c.card_id != CARD_ID])
    assert beside.computation == alone.computation and beside.summary == alone.summary

    path = _write(pack, (*run, *traits), sample_qc, tmp_path / "runs")
    bundle = read_bundle(path)
    saved = next(c for c in bundle.cards if c.card_id == CARD_ID)
    assert saved.computation is not None and alone.computation is not None
    assert saved.computation["result"]["run"] == alone.computation["result"]["run"]
    notice = section_notice(bundle.cards)
    assert notice is not None and notice["text"] == saved.summary

    with TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        page = html.unescape(client.get(f"/runs/{path.name}?section=reproductive").text)
    assert page.count(saved.summary) >= 1
    assert "Carrier screening scope" in page
    assert "Carrier findings, about offspring" in page and "about self." in page
    assert "Synthetic not-run reason." in page
    # The statement names carrier screening, so it does not read as a limit on these scores.
    assert "not a carrier screen" in saved.summary and "polygenic" not in saved.summary


def test_a_reproductive_interpretation_card_must_still_be_a_carrier_card() -> None:
    """M11.7 widened polygenic scores, not single-marker cards: no false carrier block."""
    text = (KNOWLEDGE / "reproductive" / "carrier.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    card = copy.deepcopy(data["cards"][0])
    del card["carrier"]
    with pytest.raises(CardError, match="reproductive interpretation card is a carrier card"):
        parse_file(
            yaml.safe_dump({"schema_version": 9, "cards": [card]}, sort_keys=False), "synthetic"
        )


def test_a_run_saved_without_the_record_still_states_the_limit(
    pack: KnowledgePack, sample_qc: QCReport, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    carriers = _run_cards(pack)[:2]
    path = _write(pack, carriers, sample_qc, tmp_path / "runs")
    assert section_notice(read_bundle(path).cards) == {
        "status": "not-recorded",
        "title": "Carrier screening scope",
        "text": NOT_RECORDED,
    }
    with TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        page = html.unescape(client.get(f"/runs/{path.name}").text)
    assert NOT_RECORDED in page
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    text = CliRunner().invoke(app, ["runs", "show", path.name])
    assert text.exit_code == 0
    assert NOT_RECORDED in text.stdout


def test_a_run_with_no_carrier_card_gets_no_statement(
    pack: KnowledgePack, sample_qc: QCReport, tmp_path: Path
) -> None:
    other = pack.by_id("smn1_copy_number")
    assert other is not None
    match = match_pack(
        KnowledgePack((other,), Path("synthetic-memory")),
        _table(_carriers(pack)[0], None, absent=True),
        merges=MergeTable.empty(),
    )[0]
    path = _write(pack, (assemble_card(other, match),), sample_qc, tmp_path / "runs")
    assert section_notice(read_bundle(path).cards) is None
    with TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        by_tier = html.unescape(client.get(f"/runs/{path.name}?group=tier").text)
    assert NOT_RECORDED not in by_tier


Mutation = Callable[[dict[str, Any]], None]


def _edit_result(key: str, field: str, value: Any) -> Mutation:
    def edit(payload: dict[str, Any]) -> None:
        payload["computation"]["result"][key][field] = value

    return edit


@pytest.mark.parametrize(
    "mutate,message",
    [
        (_edit_result("run", "with_result", 16), "does not follow"),
        (_edit_result("run", "not_determined", 0), "does not follow"),
        (_edit_result("counts", "typed", 113), "does not follow"),
        (_edit_result("counts", "no_card", 0), "does not follow"),
        (_edit_result("panel", "markers", 99), "does not follow"),
        (_edit_result("excluded_alleles", "not_authored", 0), "does not follow"),
        (lambda p: p["computation"]["result"].pop("run"), "wrong fields"),
        (
            lambda p: p["computation"]["result"]["declaration"]["excluded_alleles"].pop(),
            "does not follow",
        ),
        (
            lambda p: p["computation"]["result"]["declaration"].update(extra=1),
            "expected fields",
        ),
        (lambda p: p.update(summary="A complete carrier screen."), "summary"),
        (lambda p: p.update(computed_caveats=[]), "caveats"),
    ],
)
def test_a_saved_record_must_follow_from_its_own_bundle(
    run: tuple[AssembledCard, ...], mutate: Mutation, message: str
) -> None:
    payloads = [json.loads(json.dumps(_card_payload(c))) for c in run]
    _check_carriers(payloads, BUNDLE_FORMAT_VERSION)
    mutate(payloads[-1])
    with pytest.raises(BundleError, match=message):
        _check_carriers(payloads, BUNDLE_FORMAT_VERSION)


def test_a_carrier_card_cannot_change_without_the_scope_noticing(
    run: tuple[AssembledCard, ...],
) -> None:
    """Each card is individually consistent here: a marker dropped from the bundle."""
    payloads = [json.loads(json.dumps(_card_payload(c))) for c in run]
    del payloads[0]
    with pytest.raises(BundleError, match="does not follow"):
        _check_carriers(payloads, BUNDLE_FORMAT_VERSION)


def test_the_record_requires_its_format_and_is_unique(run: tuple[AssembledCard, ...]) -> None:
    payloads = [json.loads(json.dumps(_card_payload(c))) for c in run]
    with pytest.raises(BundleError, match="requires bundle format 27"):
        _check_carriers(payloads[-1:], 26)
    with pytest.raises(BundleError, match="one carrier-screening scope card"):
        _check_carriers([*payloads, payloads[-1]], BUNDLE_FORMAT_VERSION)


@pytest.mark.parametrize(
    "mutate,message",
    [
        (lambda c: c.update(section="physical_health"), "inconsistent computed-card"),
        (lambda c: c["computation"].update(reason="Also a reason."), "not-run reason"),
        (lambda c: c["computation"]["reliability"].update(tier="moderate"), "reliability"),
        (lambda c: c.update(status="not_run"), "disagree"),
    ],
)
def test_the_reader_checks_the_card_around_the_record(
    pack: KnowledgePack,
    run: tuple[AssembledCard, ...],
    sample_qc: QCReport,
    tmp_path: Path,
    mutate: Mutation,
    message: str,
) -> None:
    path = _write(pack, run, sample_qc, tmp_path / "runs")
    # Refresh the digest as well, so this reaches the schema check rather than the digest's.
    cards_path = path / CARDS_NAME
    cards = json.loads(cards_path.read_text(encoding="utf-8"))
    mutate(next(c for c in cards["cards"] if c["card_id"] == CARD_ID))
    text = json.dumps(cards, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    cards_path.write_bytes(text.encode("utf-8"))
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][CARDS_NAME] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest_path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    )
    with pytest.raises(BundleError, match=message):
        read_bundle(path)


# ---------------------------------------------------------------------------
# The agent interface
# ---------------------------------------------------------------------------


def test_cli_lists_the_comparison_from_the_pack_alone(scope: dict[str, Any]) -> None:
    as_json = CliRunner().invoke(app, ["cards", "carrier-scope", "--json"])
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout) == scope
    text = CliRunner().invoke(app, ["cards", "carrier-scope"])
    assert text.exit_code == 0
    assert "This is not a carrier screen." in text.stdout
    assert "Also typed, not on this list: HFE" in text.stdout
    assert "Gap in this report" in text.stdout
    assert_no_genotype(text.stdout, context="carrier scope")


def _redirected(arguments: list[str], data_dir: Path) -> subprocess.CompletedProcess[bytes]:
    """The real entry point with stdout going to a pipe, as on Windows: a legacy code page.

    ``CliRunner`` substitutes a UTF-8 stream, so it cannot see this. cp1252 has no beta or
    alpha, which the reference list's condition names use.
    """
    environment = {**os.environ, "PYTHONIOENCODING": "cp1252", "GENETICS_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, "-m", "genetics.cli.main", *arguments],
        capture_output=True,
        env=environment,
        check=False,
    )


def test_the_pack_comparison_survives_a_legacy_code_page(tmp_path: Path) -> None:
    text = _redirected(["cards", "carrier-scope"], tmp_path)
    assert text.returncode == 0, text.stderr.decode("utf-8", "replace")
    assert "β-thalassemia" in text.stdout.decode("utf-8")


def test_a_saved_run_as_json_survives_a_legacy_code_page(
    pack: KnowledgePack,
    run: tuple[AssembledCard, ...],
    sample_qc: QCReport,
    tmp_path: Path,
) -> None:
    path = _write(pack, run, sample_qc, tmp_path / "runs")
    saved = _redirected(["runs", "show", path.name, "--json"], tmp_path)
    assert saved.returncode == 0, saved.stderr.decode("utf-8", "replace")
    record = next(c for c in json.loads(saved.stdout)["cards"] if c["card_id"] == CARD_ID)
    assert "β-thalassemia" in json.dumps(record, ensure_ascii=False)


def test_cli_fails_loudly_on_a_pack_without_the_card(tmp_path: Path) -> None:
    (tmp_path / "health.yaml").write_bytes((KNOWLEDGE / "health" / "coverage.yaml").read_bytes())
    missing = CliRunner().invoke(app, ["cards", "carrier-scope", "--knowledge", str(tmp_path)])
    assert missing.exit_code == 1
    assert "no carrier-screening scope card" in missing.output
