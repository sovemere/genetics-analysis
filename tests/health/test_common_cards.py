"""M7.5: fabricated calls, exhaustive phase possibilities, and saved-view parity."""

from __future__ import annotations

import hashlib
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
from genetics.engine.cards import Card, CardError, KnowledgePack, parse_file
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import (
    AssembledCard,
    EvidenceAssemblyError,
    ObservationEvidence,
    PopulationFrequency,
    assemble_card,
)
from genetics.engine.matcher import MatchStatus, Strand, match_pack
from genetics.engine.multimarker import validate_snapshot
from genetics.ingest.keys import MergeTable
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    CARDS_NAME,
    MANIFEST_NAME,
    BundleError,
    _card_payload,
    read_bundle,
    write_bundle,
)
from genetics.run.pipeline import observations
from genetics.testing.fixtures import FIXTURES, render_fixture
from genetics.web import WebConfig, create_app


@pytest.fixture(scope="module")
def health_pack() -> KnowledgePack:
    return KnowledgePack.load(Path(__file__).parents[2] / "knowledge" / "health")


def _table(card: Card, pairs: tuple[str | None, ...]) -> GenotypeTable:
    assert card.match is not None
    rows = []
    for variant, pair in zip(card.match.variants, pairs, strict=True):
        if pair == "absent":
            continue
        rows.append(
            {
                "rsid": variant.rsid,
                "chrom": variant.key.chrom.value,
                "pos_grch37": variant.key.pos_grch37,
                "a1": pair[0] if pair else None,
                "a2": pair[1] if pair else None,
                "genotype": pair,
                "call_status": "called" if pair else "no_call",
            }
        )
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")


def _assemble(
    card: Card,
    pairs: tuple[str | None, ...],
    *,
    marker_evidence: tuple[ObservationEvidence, ...] | None = None,
) -> AssembledCard:
    pack = KnowledgePack((card,), Path("synthetic-memory"))
    match = match_pack(pack, _table(card, pairs), merges=MergeTable.empty())[0]
    runtime = observations(pack, (match,))[card.id]
    if marker_evidence is not None:
        runtime = ObservationEvidence(CallSource.DIRECT, markers=marker_evidence)
    return assemble_card(card, match, runtime)


def _apoe(pack: KnowledgePack) -> Card:
    return next(c for c in pack.cards if c.id == "apoe_diplotype_dementia")


def test_confidence_uses_the_matched_outcomes_effect(health_pack: KnowledgePack) -> None:
    card = _assemble(_apoe(health_pack), ("TT", "CT"))
    assert card.confidence is not None
    assert card.confidence.inputs.effect_value == 0.80
    assert card.confidence.inputs.effect_value != 8.74


def test_unestimated_rare_pattern_does_not_inherit_common_disease_evidence(
    health_pack: KnowledgePack,
) -> None:
    card = _assemble(_apoe(health_pack), ("CC", "TT"))
    assert card.card.evidence is None
    assert card.confidence and card.confidence.inputs.effect_value is None
    assert card.confidence.tier is ConfidenceTier.LIMITED


def test_factor_v_homozygote_uses_its_cohort_estimate(health_pack: KnowledgePack) -> None:
    authored = next(c for c in health_pack.cards if c.id == "f5_leiden_thromboembolism")
    card = _assemble(authored, ("TT",))
    assert card.confidence and card.confidence.inputs.effect_value == 18.0
    assert card.card.evidence and card.card.evidence.effect.ci_low == 4.1


@pytest.mark.parametrize(
    "frequency,quality,tier",
    [
        (0.4, 0.95, ConfidenceTier.LIMITED),
        (0.000001, 0.95, ConfidenceTier.LIKELY_ARTIFACT),
        (0.4, 0.01, ConfidenceTier.LIKELY_ARTIFACT),
    ],
    ids=["common", "rare", "poor_quality"],
)
def test_absent_effect_retains_observation_reliability_gates(
    health_pack: KnowledgePack, frequency: float, quality: float, tier: ConfidenceTier
) -> None:
    card = _assemble(
        _apoe(health_pack),
        ("CC", "TT"),
        marker_evidence=(
            ObservationEvidence(CallSource.DIRECT, (_frequency("C", frequency),)),
            ObservationEvidence(
                CallSource.IMPUTED, (_frequency("T", frequency),), imputation_quality=quality
            ),
        ),
    )
    assert card.confidence and card.confidence.tier is tier
    assert card.confidence.inputs.effect_value is None
    validate_snapshot(_card_payload(card))


def test_constituent_matches_cannot_be_swapped(health_pack: KnowledgePack) -> None:
    card = _apoe(health_pack)
    pack = KnowledgePack((card,), Path("synthetic-memory"))
    match = match_pack(pack, _table(card, ("CC", "CC")), merges=MergeTable.empty())[0]
    evidence = observations(pack, (match,))[card.id]
    with pytest.raises(EvidenceAssemblyError):
        assemble_card(card, replace(match, markers=tuple(reversed(match.markers))), evidence)


def test_lint_counts_every_constituent_marker(
    health_pack: KnowledgePack, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.engine.card_lint import InMemoryVariantResolver, ReferenceVariant, lint_pack

    records = tuple(
        ReferenceVariant(v.rsid, v.key)
        for c in health_pack.cards
        if c.match
        for v in c.match.variants
    )
    report = lint_pack(health_pack, resolver=InMemoryVariantResolver(records))
    assert report.ok
    assert report.interpretation_count == 3
    assert report.variant_count == report.resolved_variants == 4
    assert report.to_dict()["variant_count"] == 4
    monkeypatch.setattr(
        "genetics.engine.card_lint.ParquetVariantResolver",
        lambda *args, **kwargs: InMemoryVariantResolver(records),
    )
    result = CliRunner().invoke(app, ["cards", "lint", "--knowledge", str(health_pack.source_dir)])
    assert result.exit_code == 0
    assert "4/4 resolved" in result.stdout


@pytest.mark.parametrize("version", [1, 2])
def test_outcome_evidence_requires_schema_three(version: int) -> None:
    raw = _raw_apoe()
    if version == 1:
        raw = yaml.safe_load(
            (Path(__file__).parents[2] / "knowledge/health/common.yaml").read_text(encoding="utf-8")
        )["cards"][0]
        raw["match"].pop("strand")
    with pytest.raises(CardError, match="schema_version 3"):
        parse_file(yaml.safe_dump({"schema_version": version, "cards": [raw]}), "old.yaml")


@pytest.mark.parametrize("variable", ["effect_value", "effect_units", "sample_size"])
def test_unestimated_outcomes_refuse_phenotype_templates(variable: str) -> None:
    raw = _raw_apoe()
    raw["outcomes"]["rare_pattern"]["summary"] = "{" + variable + "}"
    with pytest.raises(CardError):
        Card.parse(raw, "synthetic validation")


@pytest.mark.parametrize(
    "pairs,expected",
    [
        (("CC", "CC"), ("e4/e4",)),
        (("CC", "CT"), ("e3r/e4",)),
        (("CC", "TT"), ("e3r/e3r",)),
        (("CT", "CC"), ("e3/e4",)),
        (("CT", "CT"), ("e2/e4", "e3/e3r")),
        (("CT", "TT"), ("e2/e3r",)),
        (("TT", "CC"), ("e3/e3",)),
        (("TT", "CT"), ("e2/e3",)),
        (("TT", "TT"), ("e2/e2",)),
    ],
    ids=[
        "four_pair",
        "rare_four",
        "rare_pair",
        "three_four",
        "phase_uncertain",
        "two_rare",
        "three_pair",
        "two_three",
        "two_pair",
    ],
)
def test_all_apoe_observation_combinations_preserve_phase(
    health_pack: KnowledgePack, pairs: tuple[str, str], expected: tuple[str, ...]
) -> None:
    card = _assemble(_apoe(health_pack), pairs)
    assert card.match.candidate_diplotypes == expected
    assert len(card.match.markers) == 2
    assert card.match.genotype is None and card.match.observed_genotype is None
    if len(expected) == 2:
        assert card.status is MatchStatus.PHASE_AMBIGUOUS
        assert card.confidence is None and card.risk_context is None
        assert all(name in card.summary for name in expected)
    else:
        assert card.status is MatchStatus.MATCHED
        assert card.risk_context and card.confidence is not None
        if "e3r" in expected[0]:
            assert "No applicable absolute disease rate" in card.risk_context
    validate_snapshot(_card_payload(card))


@pytest.mark.parametrize(
    "pairs,status",
    [
        ((None, "CC"), MatchStatus.NO_CALL),
        (("CC", None), MatchStatus.NO_CALL),
        (("absent", "CC"), MatchStatus.MARKER_ABSENT),
        (("CC", "absent"), MatchStatus.MARKER_ABSENT),
        (("AC", "CC"), MatchStatus.ALLELE_MISMATCH),
        (("CC", "AC"), MatchStatus.ALLELE_MISMATCH),
        (("II", "CC"), MatchStatus.INDEL_EXCLUDED),
    ],
    ids=[
        "first_uncalled",
        "second_uncalled",
        "first_missing",
        "second_missing",
        "first_mismatch",
        "second_mismatch",
        "indel_excluded",
    ],
)
def test_incomplete_or_inconsistent_multimarker_observations_stay_visible(
    health_pack: KnowledgePack, pairs: tuple[str | None, str | None], status: MatchStatus
) -> None:
    card = _assemble(_apoe(health_pack), pairs)
    assert card.status is status and card.confidence is None
    assert card.match.candidate_diplotypes == ()
    assert card.multi_marker is not None and len(card.multi_marker["markers"]) == 2
    validate_snapshot(_card_payload(card))


def test_duplicate_conflict_is_preserved_with_the_companion_marker(
    health_pack: KnowledgePack,
) -> None:
    card = _apoe(health_pack)
    table = _table(card, ("CC", "CC"))
    other = _table(card, ("TT", "CC"))
    combined = GenotypeTable(pl.concat([table.frame, other.frame.head(1)]), vendor="synthetic")
    pack = KnowledgePack((card,), Path("synthetic-memory"))
    match = match_pack(pack, combined, merges=MergeTable.empty())[0]
    assembled = assemble_card(card, match, observations(pack, (match,))[card.id])
    assert assembled.status is MatchStatus.DUPLICATE_CONFLICT
    assert assembled.multi_marker and assembled.multi_marker["markers"][1]["status"] == "matched"
    validate_snapshot(_card_payload(assembled))


def test_complemented_markers_preserve_both_readings(health_pack: KnowledgePack) -> None:
    card = _assemble(_apoe(health_pack), ("GG", "GG"))
    assert card.match.candidate_diplotypes == ("e4/e4",)
    assert all(m.strand is Strand.COMPLEMENTED for m in card.match.markers)
    validate_snapshot(_card_payload(card))


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("hfe_c282y_iron_overload", {"AA": "two_c282y", "AG": "one_c282y", "GG": "no_c282y"}),
        ("f5_leiden_thromboembolism", {"CC": "no_leiden", "CT": "one_leiden", "TT": "two_leiden"}),
    ],
    ids=["iron_overload", "venous_clots"],
)
def test_single_marker_outcomes_and_forward_strand_mapping(
    health_pack: KnowledgePack, identifier: str, expected: dict[str, str]
) -> None:
    authored = next(c for c in health_pack.cards if c.id == identifier)
    for pair, outcome in expected.items():
        card = _assemble(authored, (pair,))
        assert card.match.outcome_name == outcome
        assert card.risk_context and "baseline" in card.risk_context.lower()
        assert card.confidence and card.citations
        if card.card.evidence is None:
            assert card.confidence.inputs.effect_value is None
            assert card.confidence.tier is ConfidenceTier.LIMITED
        else:
            assert card.confidence.inputs.effect_value == card.card.evidence.effect.value


def _frequency(allele: str, value: float) -> PopulationFrequency:
    return PopulationFrequency(allele, value, "synthetic population", "synthetic reference")


@pytest.mark.parametrize(
    "identifier,pair",
    [
        ("hfe_c282y_iron_overload", "TT"),
        ("hfe_c282y_iron_overload", "CT"),
        ("f5_leiden_thromboembolism", "AA"),
        ("f5_leiden_thromboembolism", "AG"),
        ("f5_leiden_thromboembolism", "GG"),
    ],
    ids=[
        "iron_extra_alternate",
        "iron_reverse_pair",
        "clot_extra_alternate",
        "clot_reverse_pair",
        "clot_other_alternate",
    ],
)
def test_unexpected_forward_alleles_do_not_become_health_claims(
    health_pack: KnowledgePack, identifier: str, pair: str
) -> None:
    authored = next(c for c in health_pack.cards if c.id == identifier)
    card = _assemble(authored, (pair,))
    assert card.status is MatchStatus.ALLELE_MISMATCH
    assert card.match.observed_genotype == pair
    assert card.match.outcome is None and card.confidence is None and card.risk_context is None


def test_forward_strand_policy_requires_schema_two() -> None:
    raw = _raw_apoe()
    variant = raw["match"]["variants"][0]
    raw["match"] = {
        "variants": [variant],
        "genotypes": {pair: "e4_e4" for pair in ("CC", "CT", "TT")},
        "strand": "forward_only",
    }
    raw["outcomes"] = {"e4_e4": raw["outcomes"]["e4_e4"]}
    with pytest.raises(CardError, match="schema_version 2"):
        parse_file(yaml.safe_dump({"schema_version": 1, "cards": [raw]}), "old.yaml")


def test_forward_only_duplicate_calls_cannot_be_collapsed_by_complement(
    health_pack: KnowledgePack,
) -> None:
    authored = next(c for c in health_pack.cards if c.id == "f5_leiden_thromboembolism")
    frame = pl.concat([_table(authored, ("CT",)).frame, _table(authored, ("AG",)).frame])
    table = GenotypeTable(frame, vendor="synthetic")
    pack = KnowledgePack((authored,), Path("synthetic-memory"))
    match = match_pack(pack, table, merges=MergeTable.empty())[0]
    assert match.status is MatchStatus.DUPLICATE_CONFLICT and match.outcome is None


@pytest.mark.parametrize("companion", [None, 0.25], ids=["unknown_companion", "common_companion"])
def test_a_rare_marker_cannot_be_hidden_by_its_companion(
    health_pack: KnowledgePack, companion: float | None
) -> None:
    evidence = (
        ObservationEvidence(
            CallSource.DIRECT, (_frequency("C", 0.000001), _frequency("T", 0.999999))
        ),
        ObservationEvidence(CallSource.DIRECT, (_frequency("C", companion),) if companion else ()),
    )
    card = _assemble(_apoe(health_pack), ("CT", "CC"), marker_evidence=evidence)
    assert card.confidence and card.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT
    assert card.confidence.empirical_ppv is not None
    assert card.frequencies == () and card.confidence_frequency is None
    assert (
        card.multi_marker
        and card.multi_marker["markers"][0]["confidence_frequency"]["allele"] == "C"
    )
    validate_snapshot(_card_payload(card))


def test_unknown_marker_frequency_caps_the_diplotype(health_pack: KnowledgePack) -> None:
    evidence = (
        ObservationEvidence(CallSource.DIRECT, (_frequency("C", 0.3),)),
        ObservationEvidence(CallSource.DIRECT),
    )
    card = _assemble(_apoe(health_pack), ("CC", "CC"), marker_evidence=evidence)
    assert card.confidence and card.confidence.tier.rank >= ConfidenceTier.MODERATE.rank
    assert any("No population frequency" in c for c in card.computed_caveats)
    validate_snapshot(_card_payload(card))


def test_frequency_query_uses_both_loci_without_pooling_alleles(health_pack: KnowledgePack) -> None:
    card = _apoe(health_pack)
    assert card.match
    pack = KnowledgePack((card,), Path("synthetic-memory"))
    match = match_pack(pack, _table(card, ("CT", "CC")), merges=MergeTable.empty())
    records = {}
    for variant, ac in zip(card.match.variants, (2, 100000), strict=True):
        records[(variant.key.chrom.value, variant.key.pos_grch37)] = [
            {
                "ref": "T",
                "alts": ["C"],
                "filter": "PASS",
                "populations": {"global": {"an": 2000000, "ac": [ac], "af": [ac / 2000000]}},
            }
        ]
    runtime = observations(pack, match, records)[card.id]
    assert runtime.markers[0].frequencies != runtime.markers[1].frequencies
    assembled = assemble_card(card, match[0], runtime)
    assert assembled.confidence and assembled.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT


def test_imputation_quality_is_retained_per_marker(health_pack: KnowledgePack) -> None:
    evidence = (
        ObservationEvidence(CallSource.DIRECT, (_frequency("C", 0.3),)),
        ObservationEvidence(CallSource.IMPUTED, (_frequency("C", 0.3),), imputation_quality=0.01),
    )
    card = _assemble(_apoe(health_pack), ("CC", "CC"), marker_evidence=evidence)
    assert card.confidence and card.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT
    assert card.confidence.empirical_ppv is None
    assert (
        card.multi_marker
        and card.multi_marker["markers"][1]["observation"]["imputation_quality"] == 0.01
    )
    validate_snapshot(_card_payload(card))


@pytest.mark.parametrize(
    "damage",
    ["call_source", "effect", "common_companion", "rare_tier", "unknown_tier", "quality_tier"],
)
def test_saved_marker_calibration_cannot_contradict_its_observation(
    health_pack: KnowledgePack, damage: str
) -> None:
    frequencies = (_frequency("C", 0.000001), _frequency("T", 0.4))
    first = ObservationEvidence(CallSource.DIRECT, frequencies)
    if damage == "unknown_tier":
        first = ObservationEvidence(CallSource.DIRECT)
    elif damage == "quality_tier":
        first = ObservationEvidence(CallSource.IMPUTED, frequencies, imputation_quality=0.01)
    card = _assemble(
        _apoe(health_pack),
        ("CT", "CC"),
        marker_evidence=(first, ObservationEvidence(CallSource.DIRECT, (_frequency("C", 0.4),))),
    )
    payload = _card_payload(card)
    marker = payload["multi_marker"]["markers"][0]
    if damage == "call_source":
        marker["observation"].update(call_source="imputed", imputation_quality=0.95)
    elif damage == "effect":
        marker["confidence"]["inputs"]["effect_value"] = 8.74
    elif damage == "common_companion":
        marker["confidence_frequency"] = marker["frequencies"][1]
        marker["confidence"]["inputs"]["population_allele_frequency"] = 0.4
    else:
        for item in payload["multi_marker"]["markers"]:
            item["confidence"].update(tier="well-established", score=0.95)
        payload["confidence"] = marker["confidence"]
    with pytest.raises(ValueError, match="invalid or inconsistent saved multi-marker evidence"):
        validate_snapshot(payload)


@pytest.mark.parametrize("ambiguous", [False, True], ids=["resolved", "unphased"])
def test_marker_quality_and_benchmarks_reach_saved_detail(
    health_pack: KnowledgePack, sample_qc: QCReport, tmp_path: Path, ambiguous: bool
) -> None:
    authored = _apoe(health_pack)
    card = _assemble(
        authored,
        ("CT", "CT") if ambiguous else ("CC", "CC"),
        marker_evidence=(
            ObservationEvidence(
                CallSource.DIRECT, (_frequency("C", 0.000001), _frequency("T", 0.4))
            ),
            ObservationEvidence(
                CallSource.IMPUTED,
                (_frequency("C", 0.4), _frequency("T", 0.4)),
                imputation_quality=0.1234,
                ancestry_match=0.4321,
            ),
        ),
    )
    root = tmp_path / "runs"
    path = _write(KnowledgePack((authored,), health_pack.source_dir), (card,), sample_qc, root)
    with TestClient(
        create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1:8765"
    ) as client:
        detail = client.get(f"/runs/{path.name}/cards/{card.card_id}")
    assert detail.status_code == 200
    for text in ("imputed", "0.1234", "0.4321", "16%", "rs429358 reliability inputs"):
        assert text in detail.text


def test_format_eleven_preserves_historical_phenotype_calibration(
    health_pack: KnowledgePack, sample_qc: QCReport, tmp_path: Path
) -> None:
    authored = _apoe(health_pack)
    # Model the format-11 pack: every diplotype used the card-wide estimate.
    authored = replace(
        authored,
        outcomes={
            name: replace(outcome, overrides_evidence=False)
            for name, outcome in authored.outcomes.items()
        },
    )
    card = _assemble(authored, ("TT", "CT"))
    assert card.confidence and card.confidence.inputs.effect_value == 8.74
    assert isinstance(card.multi_marker, dict)
    card.multi_marker["schema_version"] = 1
    path = _write(KnowledgePack((authored,), health_pack.source_dir), (card,), sample_qc, tmp_path)
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 11
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = read_bundle(path)
    assert loaded.format_version == 11
    assert loaded.cards[0].confidence == _card_payload(card)["confidence"]
    assert loaded.cards[0].multi_marker == card.multi_marker


def test_new_nullable_calibration_cannot_be_declared_format_eleven(
    health_pack: KnowledgePack, sample_qc: QCReport, tmp_path: Path
) -> None:
    authored = next(c for c in health_pack.cards if c.id == "hfe_c282y_iron_overload")
    card = _assemble(authored, ("AG",))
    path = _write(KnowledgePack((authored,), health_pack.source_dir), (card,), sample_qc, tmp_path)
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 11
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="absent phenotype calibration"):
        read_bundle(path)


def test_doubled_single_copy_observations_do_not_become_diplotypes(
    health_pack: KnowledgePack,
) -> None:
    authored = _apoe(health_pack)
    table = _table(authored, ("CC", "CC"))
    frame = table.frame.with_columns(
        pl.lit("hemizygous").cast(NORMALIZED_SCHEMA["call_status"]).alias("call_status")
    )
    table = GenotypeTable(frame, vendor="synthetic")
    pack = KnowledgePack((authored,), Path("synthetic-memory"))
    match = match_pack(pack, table, merges=MergeTable.empty())[0]
    card = assemble_card(authored, match, observations(pack, (match,))[authored.id])
    assert card.status is MatchStatus.INSUFFICIENT_CALLS and card.confidence is None
    validate_snapshot(_card_payload(card))


def test_saved_scalar_format_ten_results_are_not_reinterpreted(
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
    sample_qc: QCReport,
    tmp_path: Path,
) -> None:
    path = _write(sample_pack, sample_cards, sample_qc, tmp_path / "runs")
    cards_path = path / CARDS_NAME
    data = json.loads(cards_path.read_text(encoding="utf-8"))
    for card in data["cards"]:
        card.pop("multi_marker")
        card.pop("risk_context")
    cards_path.write_text(json.dumps(data), encoding="utf-8")
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 10
    manifest["files"][CARDS_NAME] = hashlib.sha256(cards_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = read_bundle(path)
    assert loaded.format_version == 10
    assert loaded.cards[0].summary == sample_cards[0].summary
    assert sample_cards[0].confidence is not None
    assert loaded.cards[0].confidence_tier == sample_cards[0].confidence.tier.value
    assert loaded.cards[0].multi_marker is None and loaded.cards[0].risk_context is None


def _raw_apoe() -> dict[str, Any]:
    file = Path(__file__).parents[2] / "knowledge" / "health" / "apoe.yaml"
    raw: dict[str, Any] = yaml.safe_load(file.read_text(encoding="utf-8"))["cards"][0]
    return raw


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["match"]["haplotypes"].pop("e3r"),
        lambda r: r["match"]["diplotypes"].pop("e3r/e4"),
        lambda r: r["match"]["variants"][1].update(pos_grch37=45411941),
        lambda r: r["match"]["variants"][1].update(chrom="18"),
        lambda r: r["match"]["variants"][1].update(alleles=["A", "T"]),
        lambda r: r["match"]["haplotypes"].update(e3r="TC"),
        lambda r: r["outcomes"]["e4_e4"].update(summary="{genotype}"),
        lambda r: r["outcomes"]["e4_e4"].pop("risk_context"),
        lambda r: r["outcomes"]["e4_e4"].update(risk_context=""),
    ],
    ids=[
        "fourth_haplotype_missing",
        "diplotype_missing",
        "duplicate_locus",
        "different_chromosome",
        "strand_uncertain",
        "duplicate_haplotype",
        "scalar_template",
        "risk_missing",
        "risk_blank",
    ],
)
def test_schema_refuses_incomplete_diplotypes_and_unavailable_templates(
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    raw = _raw_apoe()
    mutate(raw)
    with pytest.raises(CardError):
        Card.parse(raw, "synthetic validation")


def test_multimarker_knowledge_requires_a_new_schema() -> None:
    with pytest.raises(CardError, match="schema_version 2"):
        parse_file(yaml.safe_dump({"schema_version": 1, "cards": [_raw_apoe()]}), "old.yaml")


def _write(
    health_pack: KnowledgePack, cards: tuple[AssembledCard, ...], sample_qc: QCReport, root: Path
) -> Path:
    return write_bundle(
        qc=sample_qc,
        cards=cards,
        pack=health_pack,
        ancestry=AncestryContext.not_run("synthetic acceptance"),
        runs_root=root,
        run_id="20261006T000000Z-abcd1234",
        lock_path=root / "absent.lock",
        tools_root=root / "tools",
    )


@pytest.mark.parametrize("ambiguous", [False, True], ids=["resolved", "phase_unresolved"])
def test_save_read_cli_and_dashboard_parity(
    health_pack: KnowledgePack,
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ambiguous: bool,
) -> None:
    authored = _apoe(health_pack)
    card = _assemble(authored, ("CT", "CT") if ambiguous else ("CC", "CC"))
    pack = KnowledgePack((authored,), health_pack.source_dir)
    root = tmp_path / "runs"
    path = _write(pack, (card,), sample_qc, root)
    bundle = read_bundle(path)
    assert bundle.format_version == BUNDLE_FORMAT_VERSION
    assert bundle.cards[0].multi_marker == card.multi_marker
    assert bundle.cards[0].risk_context == card.risk_context
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert result.exit_code == 0
    saved = json.loads(result.stdout)["cards"][0]
    assert saved["multi_marker"] == card.multi_marker and saved["risk_context"] == card.risk_context
    with TestClient(
        create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1:8765"
    ) as client:
        face = client.get(f"/runs/{path.name}?section=physical_health")
        detail = client.get(f"/runs/{path.name}/cards/{card.card_id}")
    assert face.status_code == detail.status_code == 200
    assert "rs429358" in detail.text and "rs7412" in detail.text
    assert "Multi-marker observations" in detail.text
    for candidate in card.match.candidate_diplotypes:
        assert candidate in detail.text
    if ambiguous:
        assert "Phase unresolved" in face.text and card.confidence is None
    else:
        assert (
            card.risk_context
            and card.risk_context in html.unescape(face.text)
            and card.risk_context in html.unescape(detail.text)
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["multi_marker"].update(candidate_diplotypes=["e3/e3"]),
        lambda p: p["multi_marker"]["markers"].pop(),
        lambda p: p["multi_marker"].update(phase="phased"),
        lambda p: p["multi_marker"]["markers"][0]["variant"].update(alleles=None),
        lambda p: p["multi_marker"]["markers"][0].update(confidence=[]),
        lambda p: p["multi_marker"]["markers"][0]["confidence"].update(tier=[]),
        lambda p: p["multi_marker"]["markers"][0]["confidence"].update(score=None),
        lambda p: p["confidence"].update(tier="well-established"),
        lambda p: p.update(status="phase_ambiguous"),
    ],
    ids=[
        "wrong_candidates",
        "missing_marker",
        "invented_phase",
        "bad_alleles",
        "bad_confidence",
        "bad_tier",
        "bad_score",
        "aggregate_overstated",
        "wrong_status",
    ],
)
def test_digest_consistent_damaged_snapshots_fail_with_domain_errors(
    health_pack: KnowledgePack,
    sample_qc: QCReport,
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    authored = _apoe(health_pack)
    card = _assemble(authored, ("CC", "CC"))
    pack = KnowledgePack((authored,), health_pack.source_dir)
    path = _write(pack, (card,), sample_qc, tmp_path / "runs")
    cards_path = path / CARDS_NAME
    data = json.loads(cards_path.read_text(encoding="utf-8"))
    mutate(data["cards"][0])
    cards_path.write_text(json.dumps(data), encoding="utf-8")
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][CARDS_NAME] = hashlib.sha256(cards_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError):
        read_bundle(path)


@pytest.mark.privacy
def test_multimarker_repr_does_not_expose_observations(health_pack: KnowledgePack) -> None:
    card = _assemble(_apoe(health_pack), ("CT", "CT"))
    assert "observed_genotype" not in repr(card)
    assert "candidate_diplotypes" not in repr(card.match)
    assert "markers=" not in repr(card.match)
    assert all("observed_genotype" not in repr(m) for m in card.match.markers)


def test_full_pipeline_queries_every_authored_locus(
    health_pack: KnowledgePack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.run.pipeline import analyse

    seen: set[tuple[str, int]] = set()

    class FakeIndex:
        def __init__(self) -> None:
            self.provenance: dict[str, Any] = {}

        def lookup(self, loci: set[tuple[str, int]]) -> dict[tuple[str, int], list[dict[str, Any]]]:
            seen.update(loci)
            return {}

    monkeypatch.setattr("genetics.run.pipeline.default_index", lambda **kwargs: FakeIndex())
    monkeypatch.setattr("genetics.ingest.keys.MergeTable.default", lambda rsids: MergeTable.empty())
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    # These are independently invented calls, assembled at runtime, never copied from a person.
    spike_ins = {}
    for card in health_pack.cards:
        if card.match is None:
            continue  # Assay coverage is computed, not a marker interpretation.
        for variant in card.match.variants:
            spike_ins[variant.rsid] = (
                int(variant.key.chrom.value),
                variant.key.pos_grch37,
                variant.key.alleles[0],
                variant.key.alleles[0],
            )
    export = tmp_path / "synthetic-export.txt"
    export.write_text(render_fixture(replace(spec, spike_ins=spike_ins)), encoding="utf-8")
    analysis = analyse(export, knowledge_dir=health_pack.source_dir)
    assert len(analysis.cards) == len(health_pack.cards)
    assert all(c.status is MatchStatus.MATCHED for c in analysis.cards if c.card.match is not None)
    assert all(c.status is MatchStatus.NOT_RUN for c in analysis.cards if c.card.match is None)
    assert ("19", 45411941) in seen and ("19", 45412079) in seen
