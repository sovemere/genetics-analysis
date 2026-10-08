"""M8.5/M8.7: quality-aware observations, rarity gates and saved-view parity.

Every target is constructed here or generated from the fixed-seed fixture generator.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.engine.cards import Card, KnowledgePack
from genetics.engine.confidence import (
    RARE_CALL_FREQUENCY_CEILING,
    CallSource,
    ConfidenceTier,
    calculate_confidence,
)
from genetics.engine.evidence import ObservationEvidence, assemble_pack
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.engine.multimarker import validate_snapshot
from genetics.engine.observation_snapshot import validate_imputation_snapshot
from genetics.engine.ppv import clinvar_benchmark
from genetics.external.beagle import Beagle, BeagleOptions
from genetics.health.clinvar import lookup_default
from genetics.health.frequencies import FrequencyIndex, parse_record
from genetics.imputation import ImputationError, ImputationResult, impute
from genetics.imputation.context import ImputationContext
from genetics.imputation.dosages import DosageRecord
from genetics.imputation.observations import card_input
from genetics.imputation.quality import ImputationEvidence
from genetics.ingest.keys import LocusKey
from genetics.ingest.schema import NORMALIZED_SCHEMA, Chrom, GenotypeTable
from genetics.privacy import assert_no_genotype
from genetics.qc.report import InferredSex
from genetics.refs.imputation import BrefTools
from genetics.run import pipeline
from genetics.run.bundle import BundleError, _card_payload, read_bundle, write_bundle
from genetics.testing.fixtures import FIXTURES, render_fixture
from genetics.testing.imputation_inputs import native_reference
from genetics.testing.imputation_snapshots import anchors, synthetic_stage
from genetics.web import WebConfig, create_app

PACK = Path(__file__).parents[1] / "fixtures/cards"
LOCUS = ("7", 12345678)


def dosage(
    *, source: str = "imputed_untyped", quality: float = 0.9, ploidy: int = 2
) -> DosageRecord:
    gt = (0, 1) if ploidy == 2 else (1,)
    ds = (1.1,) if ploidy == 2 else (0.7,)
    if source == "imputed_no_call":
        ds = (1.0,)
    return DosageRecord(
        *LOCUS,
        "A",
        ("G",),
        gt,
        gt,
        ds,
        ds,
        None if source == "imputed_no_call" else (quality,),
        ploidy,
        source,
        "resolved",
        "no_call" if source == "imputed_no_call" else None,
        "phased_hardcall_only" if source == "imputed_no_call" else "beagle_DS",
        "not_estimated"
        if source == "imputed_no_call"
        else ("beagle_haploid_dosage" if ploidy == 1 else "beagle_diploid_dosage"),
    )


def table(*rows: tuple[str, int, str | None, str]) -> GenotypeTable:
    return GenotypeTable(
        pl.DataFrame(
            [
                (None, chrom, pos, gt[0] if gt else None, gt[1] if gt else None, gt, status)
                for chrom, pos, gt, status in rows
            ],
            schema=NORMALIZED_SCHEMA,
            orient="row",
        ),
        vendor="synthetic",
    )


def result(
    original: GenotypeTable, root: Path, source: str = "imputed_untyped"
) -> ImputationResult:
    # The two anchor calls do not concern the card under test.
    missing = source == "imputed_no_call"
    return ImputationResult(
        original,
        root,
        (root / "synthetic.dosages.jsonl.gz",),
        {
            "records": 3,
            "sources": {"direct": 2, source: 1},
            "ploidy_conflicts": 0,
            "regions": [
                {
                    "region": "chr7",
                    "ploidy": 2,
                    "positions": 3 if missing else 2,
                    "written": 3 if missing else 2,
                    "called": 2,
                    "outcomes": {"as_written": 2, **({"no_call": 1} if missing else {})},
                    "status": "computed",
                }
            ],
            "unsupported_positions": {},
        },
        False,
    )


@pytest.fixture
def pack() -> KnowledgePack:
    return KnowledgePack.load(PACK)


def install_records(monkeypatch: pytest.MonkeyPatch, records: tuple[DosageRecord, ...]) -> None:
    def stream(self: ImputationResult) -> Iterator[DosageRecord]:
        return iter(records)

    monkeypatch.setattr(ImputationResult, "iter_dosages", stream)


@pytest.mark.parametrize(
    "quality,tier",
    [
        (0.0, "likely-artifact"),
        (0.29, "likely-artifact"),
        (0.3, "limited"),
        (0.59, "limited"),
        (0.6, "moderate"),
        (0.79, "moderate"),
        (0.8, "strong"),
    ],
)
def test_quality_reaches_confidence_without_removing_findings(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    quality: float,
    tier: str,
) -> None:
    install_records(monkeypatch, (dosage(quality=quality),))
    target, metadata = card_input(pack, result(table(), tmp_path), sex=InferredSex.MALE)
    matches = match_pack(pack, target)
    cards = assemble_pack(pack, matches, pipeline.observations(pack, matches, imputed=metadata))
    card = cards[0]
    assert len(cards) == len(pack.cards) and card.has_interpretation
    assert card.observation is not None and card.observation.call_source is CallSource.IMPUTED
    assert card.confidence is not None
    # Missing frequency already caps at moderate; quality imposes the weaker ceiling.
    expected = "moderate" if tier == "strong" else tier
    assert card.confidence.tier.value == expected
    assert card.confidence.inputs.imputation_quality == quality
    assert card.confidence.inputs.imputation_score == quality
    assert card.observation.imputation is not None
    assert card.observation.imputation.dosage == (1.1,)
    validate_imputation_snapshot(_card_payload(card), require_detail=True)


def test_phase_filled_unknown_quality_is_visible_and_limited(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_records(monkeypatch, (dosage(source="imputed_no_call"),))
    original = table((*LOCUS, None, "no_call"))
    target, metadata = card_input(
        pack, result(original, tmp_path, "imputed_no_call"), sex=InferredSex.MALE
    )
    matches = match_pack(pack, target)
    card = assemble_pack(pack, matches, pipeline.observations(pack, matches, imputed=metadata))[0]
    assert card.confidence is not None and card.confidence.tier is ConfidenceTier.LIMITED
    assert card.confidence.inputs.imputation_quality is None
    assert card.confidence.inputs.imputation_score == 0.0
    assert any("unknown" in note for note in card.computed_caveats)
    assert original.frame["genotype"].to_list() == [None]
    validate_imputation_snapshot(_card_payload(card), require_detail=True)


@pytest.mark.parametrize(
    "rows",
    [
        ((*LOCUS, "GG", "called"),),
        ((*LOCUS, "AG", "het_haploid"),),
        ((*LOCUS, "II", "called"),),
        ((*LOCUS, "AA", "called"), (*LOCUS, "GG", "called")),
        ((*LOCUS, None, "no_call"), (*LOCUS, "GG", "called")),
    ],
)
def test_imputation_never_overwrites_an_original_called_probe(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: tuple[tuple[str, int, str | None, str], ...],
) -> None:
    original = table(*rows)
    install_records(monkeypatch, (dosage(),))
    target, metadata = card_input(pack, result(original, tmp_path), sex=InferredSex.MALE)
    assert metadata == {} and target is original


@pytest.mark.parametrize(
    "change",
    [
        {"ref": "C", "alt": ("T",)},
        {"ref": "AC"},
        {"alt": ("G", "T")},
        {"source": "direct"},
        {"status": "ploidy_conflict"},
    ],
)
def test_nonmatching_or_unresolved_dosages_do_not_invent_a_card_call(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
) -> None:
    install_records(monkeypatch, (replace(dosage(), **change),))
    original = table()
    target, metadata = card_input(pack, result(original, tmp_path), sex=InferredSex.MALE)
    assert target is original and metadata == {}
    assert match_pack(pack, target)[0].status is MatchStatus.MARKER_ABSENT


def test_multiple_panel_records_at_one_position_remain_ambiguous(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_records(monkeypatch, (dosage(), replace(dosage(), ref="C", alt=("T",))))
    target, metadata = card_input(pack, result(table(), tmp_path), sex=InferredSex.MALE)
    assert metadata == {} and len(target) == 0


@pytest.mark.parametrize(
    "source,original",
    [
        ("imputed_no_call", ()),
        ("imputed_untyped", ((*LOCUS, None, "no_call"),)),
    ],
)
def test_source_must_agree_with_original_position_presence(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    original: tuple[tuple[str, int, str | None, str], ...],
) -> None:
    install_records(monkeypatch, (dosage(source=source),))
    with pytest.raises(ImputationError, match="source disagrees"):
        card_input(pack, result(table(*original), tmp_path, source), sex=InferredSex.MALE)


@pytest.mark.parametrize("sex", [InferredSex.MALE, InferredSex.FEMALE, InferredSex.AMBIGUOUS])
def test_native_haploid_observation_keeps_single_copy_dose_and_quality(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sex: InferredSex,
) -> None:
    raw = _card_payload_placeholder(pack)
    raw["match"]["variants"][0].update(chrom="X", pos_grch37=3000000)
    card = _parse_card(raw)
    one = KnowledgePack((card,), PACK)
    record = replace(dosage(ploidy=1), chrom="X", pos_grch37=3000000)
    install_records(monkeypatch, (record,))
    if sex is not InferredSex.MALE:
        with pytest.raises(ImputationError, match="ploidy"):
            card_input(one, result(table(), tmp_path), sex=sex)
        return
    target, metadata = card_input(one, result(table(), tmp_path), sex=sex)
    assert target.frame["call_status"].to_list() == ["hemizygous"]
    detail = metadata[("X", 3000000)]
    assert detail.ploidy == 1 and detail.dosage == (0.7,)
    assert detail.quality_scope == "beagle_haploid_dosage" and detail.card_quality == 0.9
    matches = match_pack(one, target)
    assembled = assemble_pack(one, matches, pipeline.observations(one, matches, imputed=metadata))[
        0
    ]
    validate_imputation_snapshot(_card_payload(assembled), require_detail=True)


def _card_payload_placeholder(pack: KnowledgePack) -> dict[str, Any]:
    import yaml

    raw: dict[str, Any] = yaml.safe_load((PACK / "valid_pack.yaml").read_text())["cards"][0]
    return raw


def _parse_card(raw: dict[str, Any]) -> Card:
    return Card.parse(raw, "synthetic quality card")


def test_effect_allele_dosages_use_their_own_quality_without_averaging() -> None:
    detail = ImputationEvidence(
        "imputed_untyped",
        "A",
        ("G", "T"),
        (0.2, 0.7),
        (0.95, 0.1),
        2,
        "beagle_DS",
        "beagle_diploid_dosage",
    )
    assert detail.allele_dosage("G") == (0.2, 0.95)
    assert detail.allele_dosage("T") == (0.7, 0.1)
    ref_dose, ref_quality = detail.allele_dosage("A")
    assert ref_dose == pytest.approx(1.1) and ref_quality is None
    with pytest.raises(ImputationError, match="effect allele"):
        detail.allele_dosage("C")
    with pytest.raises(ImputationError, match="biallelic"):
        _ = detail.card_quality


def test_reference_oriented_imputation_resolves_palindromic_strand_without_trusting_array(
    pack: KnowledgePack,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _card_payload_placeholder(pack)
    raw["match"]["variants"][0]["alleles"] = ["A", "T"]
    raw["match"]["genotypes"] = {"AA": "present", "AT": "present", "TT": "absent"}
    single = KnowledgePack((_parse_card(raw),), PACK)
    record = replace(
        dosage(),
        alt=("T",),
        genotype=(0, 0),
        storage_genotype=(0, 0),
        dosage=(0.1,),
        storage_dosage=(0.1,),
    )
    install_records(monkeypatch, (record,))
    target, metadata = card_input(single, result(table(), tmp_path), sex=InferredSex.MALE)
    assert match_pack(single, target)[0].status is MatchStatus.STRAND_AMBIGUOUS
    matched = match_pack(
        single, target, reference_forward_loci=frozenset({LocusKey(Chrom.CHR7, LOCUS[1])})
    )
    assert matched[0].status is MatchStatus.MATCHED
    card = assemble_pack(single, matched, pipeline.observations(single, matched, imputed=metadata))[
        0
    ]
    validate_imputation_snapshot(_card_payload(card), require_detail=True)
    # Original consumer calls still receive no reference-forward privilege.
    original = table((*LOCUS, "AA", "called"))
    preserved, metadata = card_input(single, result(original, tmp_path), sex=InferredSex.MALE)
    assert (
        metadata == {} and match_pack(single, preserved)[0].status is MatchStatus.STRAND_AMBIGUOUS
    )


@pytest.mark.parametrize("ploidy", [1, 2])
def test_biallelic_ref_quality_and_dosage_remain_on_native_scale(ploidy: int) -> None:
    detail = ImputationEvidence.from_record(dosage(ploidy=ploidy))
    value, quality = detail.allele_dosage("A")
    assert value == pytest.approx(ploidy - detail.dosage[0]) and quality == 0.9
    assert detail.allele_dosage("G") == (detail.dosage[0], 0.9)


@pytest.mark.parametrize(
    "change",
    [
        {"ploidy": True},
        {"dosage": (-0.1,)},
        {"dosage": (float("nan"),)},
        {"dr2": (float("inf"),)},
        {"dr2": (1.1,)},
        {"dr2": (True,)},
        {"dr2": (0.5, 0.5)},
        {"quality_scope": "beagle_haploid_dosage"},
        {"source": "direct"},
        {"dosage_method": "phased_hardcall_only"},
    ],
)
def test_invalid_quality_contract_is_rejected_without_echoing_observations(
    change: dict[str, Any],
) -> None:
    raw = ImputationEvidence.from_record(dosage()).to_dict()
    raw.update(change)
    with pytest.raises(ImputationError) as caught:
        ImputationEvidence.from_dict(raw)
    assert_no_genotype(str(caught.value))


def test_unknown_quality_requires_explicit_provenance() -> None:
    with pytest.raises(ValueError, match="requires imputation_quality"):
        ObservationEvidence(CallSource.IMPUTED)
    detail = ImputationEvidence.from_record(dosage(source="imputed_no_call"))
    assert ObservationEvidence(CallSource.IMPUTED, imputation=detail).imputation_quality is None
    result = calculate_confidence(
        None,
        population_allele_frequency=0.2,
        call_source=CallSource.IMPUTED,
        imputation_quality_unknown=True,
    )
    assert result.tier is ConfidenceTier.LIMITED and result.inputs.imputation_score == 0.0
    with pytest.raises(ValueError):
        calculate_confidence(
            None,
            population_allele_frequency=0.2,
            call_source=CallSource.DIRECT,
            imputation_quality_unknown=True,
        )


@pytest.mark.parametrize("source", ["imputed_untyped", "imputed_no_call"])
def test_multi_marker_confidence_inherits_imputed_quality_without_assuming_phase(
    source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import yaml

    raw = yaml.safe_load((Path(__file__).parents[2] / "knowledge/health/apoe.yaml").read_text())[
        "cards"
    ][0]
    card = Card.parse(raw, "synthetic APOE observation")
    assert card.match is not None
    first, second = card.match.variants
    original = table(
        (first.key.chrom.value, first.key.pos_grch37, "CC", "called"),
        *(
            ([(second.key.chrom.value, second.key.pos_grch37, None, "no_call")])
            if source == "imputed_no_call"
            else []
        ),
    )
    record = replace(
        dosage(source=source, quality=0.1),
        chrom="19",
        pos_grch37=second.key.pos_grch37,
        ref="C",
        alt=("T",),
        genotype=(0, 0),
        storage_genotype=(0, 0),
        dosage=(0.0,),
        storage_dosage=(0.0,),
    )
    install_records(monkeypatch, (record,))
    pack = KnowledgePack((card,), PACK)
    target, metadata = card_input(pack, result(original, tmp_path, source), sex=InferredSex.MALE)
    matches = match_pack(pack, target)
    assembled = assemble_pack(
        pack, matches, pipeline.observations(pack, matches, imputed=metadata)
    )[0]
    assert assembled.confidence is not None
    assert assembled.confidence.tier.value == (
        "limited" if source == "imputed_no_call" else "likely-artifact"
    )
    payload = _card_payload(assembled)
    assert payload["multi_marker"]["phase"] == "unphased"
    assert payload["multi_marker"]["markers"][0]["observation"]["call_source"] == "direct"
    assert payload["multi_marker"]["markers"][1]["observation"]["call_source"] == "imputed"
    validate_snapshot(payload)
    validate_imputation_snapshot(payload, require_detail=True)


def test_format_14_execution_and_observation_basis_are_preserved(
    export: Path,
    tmp_path: Path,
) -> None:
    analysis = pipeline.analyse(export, knowledge_dir=PACK, no_impute=True)
    context = ImputationContext.enabled(result(table(), tmp_path).summary())
    historical = replace(
        analysis,
        imputation=context,
        cards=tuple(replace(c, imputation_mode="enabled") for c in analysis.cards),
    )
    path = write_bundle(
        qc=historical.qc,
        pack=historical.pack,
        cards=historical.cards,
        ancestry=historical.ancestry,
        clinvar=historical.clinvar,
        imputation=historical.imputation,
    )
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["format_version"] = 14
    manifest["files"].pop("imputation.provenance.run.json")
    (path / "imputation.provenance.run.json").unlink()
    manifest_path.write_text(json.dumps(manifest))
    bundle = read_bundle(path)
    assert bundle.imputation == context.to_dict()
    assert bundle.imputation["schema_version"] == 1
    assert bundle.imputation["card_input"] == "original_array"
    assert all(c.observation is None or "imputation" not in c.observation for c in bundle.cards)


@pytest.fixture
def export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    path = tmp_path / "synthetic.txt"
    path.write_text(render_fixture(spec), encoding="utf-8")
    return path


def install_stage(monkeypatch: pytest.MonkeyPatch, root: Path, record: DosageRecord) -> None:
    install_records(monkeypatch, (record,))

    def stage(original: GenotypeTable, **kwargs: Any) -> ImputationResult:
        return synthetic_stage(
            original, root / "synthetic-complete", records=(*anchors(record.chrom), record)
        )

    monkeypatch.setattr(pipeline, "impute", stage)


@pytest.mark.privacy
def test_cli_dashboard_snapshot_parity_with_low_quality_and_no_cache(
    export: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_stage(monkeypatch, tmp_path, dosage(quality=0.1))
    original_lookup = lookup_default
    observed_tables = []

    def lookup(original: GenotypeTable, **kwargs: Any) -> Any:
        observed_tables.append(original)
        return original_lookup(original, **kwargs)

    monkeypatch.setattr(pipeline, "lookup_default", lookup)
    invocation = CliRunner().invoke(
        app, ["run", "--input", str(export), "--knowledge", str(PACK), "--json"]
    )
    assert invocation.exit_code == 0, invocation.output
    assert_no_genotype(invocation.output)
    path = Path(json.loads(invocation.stdout)["path"])
    bundle = read_bundle(path)
    assert bundle.imputation is not None
    assert bundle.format_version == 16 and bundle.imputation["schema_version"] == 2
    assert bundle.imputation["card_input"] == "original_array_with_imputed"
    card = bundle.cards[0]
    assert card.observation is not None and card.observation["imputation_quality"] == 0.1
    assert card.confidence_tier == "likely-artifact"
    assert (
        observed_tables[0]
        .frame.filter(pl.col("chrom") == "7")
        .filter(pl.col("pos_grch37") == LOCUS[1])
        .is_empty()
    )
    # The result points to a nonexistent test cache. Reopening must use only the bundle.
    assert read_bundle(path).cards[0].observation == card.observation
    shown = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["cards"][0]["observation"] == card.observation
    with TestClient(create_app(WebConfig()), base_url="http://127.0.0.1") as client:
        face = client.get(f"/runs/{path.name}").text
        detail = client.get(f"/runs/{path.name}/cards/{card.card_id}").text
    assert "likely-artifact" in face and "plus imputed observations" in face
    assert "beagle_diploid_dosage" in detail and "Imputation quality" in detail
    assert "0.1" in detail and "1.1" in detail


def test_phase_filled_unknown_quality_survives_save_and_dashboard(
    export: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    export.write_text(
        render_fixture(replace(spec, spike_ins={"rs900000001": (7, LOCUS[1], "0", "0")})),
        encoding="utf-8",
    )
    install_stage(monkeypatch, tmp_path, dosage(source="imputed_no_call"))
    path = pipeline.save(pipeline.analyse(export, knowledge_dir=PACK))
    saved = read_bundle(path).cards[0]
    assert saved.observation is not None and saved.observation["imputation_quality"] is None
    assert saved.observation["imputation"]["dr2"] is None
    assert saved.confidence_tier == "limited"
    with TestClient(create_app(WebConfig()), base_url="http://127.0.0.1") as client:
        face = client.get(f"/runs/{path.name}").text
        detail = client.get(f"/runs/{path.name}/cards/{saved.card_id}").text
    assert "quality unknown" in face and "not_estimated" in detail and "unknown" in detail


@pytest.mark.parametrize(
    "damage", ["quality", "dose", "scope", "tier", "source", "missing", "format", "old_format"]
)
def test_saved_quality_corruption_is_rejected_after_rehash(
    export: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    install_stage(monkeypatch, tmp_path, dosage(quality=0.1))
    path = pipeline.save(pipeline.analyse(export, knowledge_dir=PACK))
    payload_path = path / "cards.run.json"
    payload = json.loads(payload_path.read_text())
    card = payload["cards"][0]
    observation = card["observation"]
    if damage == "quality":
        observation["imputation_quality"] = 0.9
    elif damage == "dose":
        observation["imputation"]["dosage"] = [3]
    elif damage == "scope":
        observation["imputation"]["quality_scope"] = "beagle_haploid_dosage"
    elif damage == "tier":
        card["confidence"]["tier"] = "well-established"
    elif damage == "source":
        observation["call_source"] = "direct"
    elif damage == "missing":
        del observation["imputation"]
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if damage == "format":
        manifest["format_version"] = 14
    elif damage == "old_format":
        manifest["format_version"] = 13
        manifest["files"].pop("imputation.run.json")
        (path / "imputation.run.json").unlink()
        for entry in payload["cards"]:
            entry.pop("imputation_mode")
    text = json.dumps(payload)
    payload_path.write_text(text)
    manifest["files"]["cards.run.json"] = hashlib.sha256(text.encode()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BundleError) as caught:
        read_bundle(path)
    assert_no_genotype(str(caught.value))


def test_native_stage_quality_reaches_card_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pack: KnowledgePack,
) -> None:
    installed = os.environ.get("GENETICS_BEAGLE_TEST_TOOLS")
    if installed is None:
        pytest.skip("set GENETICS_BEAGLE_TEST_TOOLS for native quality acceptance")
    beagle = Beagle.discover(tools_root=Path(installed))
    bref = BrefTools.discover(Path(installed))
    monkeypatch.setattr(BrefTools, "discover", lambda: bref)
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "isolated-data"))
    reference, male, _ = native_reference(tmp_path / "refs", bref)
    stage = impute(
        male,
        sex=InferredSex.MALE,
        reference=reference,
        beagle=beagle,
        bref=bref,
        options=BeagleOptions(memory_mb=512, nthreads=2),
        out=tmp_path / "job",
    )
    chosen = {
        (r.chrom, r.pos_grch37): r
        for r in stage.iter_dosages()
        if r.chrom == "1" and r.pos_grch37 in {1002000, 1005000}
    }
    cards = []
    for i, record in enumerate(chosen.values()):
        raw = _card_payload_placeholder(pack)
        raw["id"] = f"synthetic_native_quality_{i}"
        raw["match"]["variants"][0].update(chrom="1", pos_grch37=record.pos_grch37)
        cards.append(_parse_card(raw))
    native_pack = KnowledgePack(tuple(cards), PACK)
    target, metadata = card_input(native_pack, stage, sex=InferredSex.MALE)
    matches = match_pack(native_pack, target)
    assembled = assemble_pack(
        native_pack, matches, pipeline.observations(native_pack, matches, imputed=metadata)
    )
    assert len(assembled) == 2 and all(c.has_interpretation for c in assembled)
    qualities = []
    for card in assembled:
        assert card.observation is not None and card.observation.imputation is not None
        qualities.append(card.observation.imputation_quality)
        assert card.confidence is not None
        validate_imputation_snapshot(_card_payload(card), require_detail=True)
    assert None in qualities and any(q is not None for q in qualities)


# M8.7: generated calls and frequency references only. Strong literature and perfect
# dosage quality make these controls capable of exposing a bypass of the rarity gate.
def rare_pack(ploidy: int = 2) -> KnowledgePack:
    raw = _card_payload_placeholder(KnowledgePack.load(PACK))
    raw["gene"] = "BRCA1"  # A gene label must not turn chip PPV into imputed-call PPV.
    raw["evidence"].update(tier="clinical_guideline", replication="meta_analysis")
    raw["evidence"]["effect"].update(value=12.0, ci_low=10.0, ci_high=14.0)
    for outcome in raw["outcomes"].values():
        outcome.update(summary="Synthetic frequency: {frequency}. {ppv}", detail="Synthetic.")
    if ploidy == 1:
        raw["match"]["variants"][0].update(chrom="X", pos_grch37=3000000)
    return KnowledgePack((_parse_card(raw),), PACK)


def rare_record(source: str, ploidy: int = 2) -> DosageRecord:
    record = dosage(source=source, quality=1.0, ploidy=ploidy)
    if ploidy == 1:
        record = replace(record, chrom="X", pos_grch37=3000000)
    return record


def frequency_rows(record: DosageRecord, frequency: float, *, split: bool = False) -> list[str]:
    # Extra split ALT means 1-AF cannot establish the REF's frequency. This exercises
    # the production lookup's missing-companion path rather than mocking selection.
    extra = next(a for a in "ACGT" if a not in {record.ref, *record.alt})
    alternates = (*record.alt, extra) if split else record.alt
    return [
        "\t".join(
            (
                record.chrom,
                str(record.pos_grch37),
                ".",
                record.ref,
                alt,
                ".",
                "PASS",
                f"AC={round(frequency * 1000000000)};AN=1000000000;AF={frequency:g};nhomalt=0",
            )
        )
        for alt in alternates
    ]


def rare_card(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    record: DosageRecord,
    rows: list[str],
) -> dict[str, Any]:
    pack = rare_pack(record.ploidy)
    locus = (record.chrom, record.pos_grch37)
    original = table((*locus, None, "no_call")) if record.source == "imputed_no_call" else table()
    install_records(monkeypatch, (record,))
    target, metadata = card_input(
        pack, result(original, tmp_path, record.source), sex=InferredSex.MALE
    )
    matches = match_pack(pack, target)
    assembled = assemble_pack(
        pack,
        matches,
        pipeline.observations(pack, matches, {locus: [parse_record(r) for r in rows]}, metadata),
    )
    assert len(assembled) == 1 and assembled[0].has_interpretation
    payload = _card_payload(assembled[0])
    validate_imputation_snapshot(payload, require_detail=True)
    return payload


@pytest.mark.parametrize("source", ["imputed_untyped", "imputed_no_call"])
@pytest.mark.parametrize("ploidy", [1, 2])
@pytest.mark.parametrize("boundary", ["below", "equal", "above"])
def test_imputed_rarity_boundary_cannot_be_rescued_by_quality_or_literature(
    source: str,
    ploidy: int,
    boundary: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    frequency = {
        "below": math.nextafter(RARE_CALL_FREQUENCY_CEILING, 0.0),
        "equal": RARE_CALL_FREQUENCY_CEILING,
        "above": math.nextafter(RARE_CALL_FREQUENCY_CEILING, 1.0),
    }[boundary]
    record = rare_record(source, ploidy)
    # Boundary floats belong in the engine test: integer allele counts cannot encode
    # nextafter. Use exact runtime frequency objects after production observations.
    from genetics.engine.evidence import PopulationFrequency

    pack = rare_pack(ploidy)
    locus = (record.chrom, record.pos_grch37)
    original = table((*locus, None, "no_call")) if source == "imputed_no_call" else table()
    install_records(monkeypatch, (record,))
    target, metadata = card_input(pack, result(original, tmp_path, source), sex=InferredSex.MALE)
    matches = match_pack(pack, target)
    observed = pipeline.observations(pack, matches, imputed=metadata)
    observed[pack.cards[0].id] = replace(
        observed[pack.cards[0].id],
        frequencies=(
            PopulationFrequency("A", 1 - frequency, "EUR", "synthetic-boundary"),
            PopulationFrequency("G", frequency, "EUR", "synthetic-boundary"),
        ),
        ancestry_match=1.0,
    )
    assembled = assemble_pack(pack, matches, observed)
    assert len(assembled) == 1 and assembled[0].has_interpretation
    payload = _card_payload(assembled[0])
    confidence = payload["confidence"]
    assert confidence["inputs"]["population_allele_frequency"] == frequency
    assert confidence["inputs"]["evidence_score"] == 1.0
    assert confidence["inputs"]["replication_score"] == 1.0
    assert confidence["inputs"]["imputation_score"] == (0.0 if source == "imputed_no_call" else 1.0)
    if boundary == "below":
        assert confidence["tier"] == "likely-artifact"
        ppv = confidence["empirical_ppv"]
        assert ppv["estimate"] == 0.16
        assert "SNP-chip" in ppv["applies_to"] and "UK Biobank" in ppv["applies_to"]
        assert "Not calibrated" in ppv["applies_to"] and "imputation" in ppv["applies_to"]
        assert "not an individual posterior probability" in ppv["applies_to"]
    else:
        assert confidence["tier"] == ("limited" if source == "imputed_no_call" else "strong")
        assert confidence["empirical_ppv"] is None
    validate_imputation_snapshot(payload, require_detail=True)


@pytest.mark.parametrize("source", ["imputed_untyped", "imputed_no_call"])
@pytest.mark.parametrize("case", ["rare_missing", "common_missing", "unobserved_rare", "absent"])
def test_imputed_frequency_coverage_prices_only_observed_alleles(
    source: str,
    case: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = rare_record(source)
    frequency = 0.2 if case == "common_missing" else 0.000005
    if case == "unobserved_rare":
        record = replace(
            record, genotype=(0, 0), storage_genotype=(0, 0), dosage=(0.0,), storage_dosage=(0.0,)
        )
    rows = (
        []
        if case == "absent"
        else frequency_rows(record, frequency, split=case.endswith("missing"))
    )
    payload = rare_card(monkeypatch, tmp_path, record, rows)
    confidence = payload["confidence"]
    if case == "rare_missing":
        assert confidence["tier"] == "likely-artifact"
        assert payload["confidence_frequency"]["allele"] == "G"
        assert confidence["inputs"]["population_allele_frequency"] == frequency
        assert any("measured rare allele" in note for note in payload["computed_caveats"])
    elif case == "unobserved_rare":
        assert payload["confidence_frequency"]["allele"] == "A"
        assert confidence["inputs"]["population_allele_frequency"] == 1 - frequency
        assert confidence["tier"] == ("limited" if source == "imputed_no_call" else "strong")
        assert confidence["empirical_ppv"] is None
    else:
        assert payload["confidence_frequency"] is None
        assert confidence["inputs"]["population_allele_frequency"] is None
        assert confidence["tier"] == ("limited" if source == "imputed_no_call" else "moderate")
        assert confidence["empirical_ppv"] is None
        assert any("No population frequency" in note for note in payload["computed_caveats"])


def install_frequency_index(
    monkeypatch: pytest.MonkeyPatch, root: Path, rows: list[str]
) -> FrequencyIndex:
    path = root / "synthetic-frequency.vcf.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("##contig=<ID=1,length=249250621,assembly=gnomAD_GRCh37>\n")
        for name, number, kind in (
            ("AF", "A", "Float"),
            ("AC", "A", "Integer"),
            ("AN", "1", "Integer"),
            ("nhomalt", "A", "Integer"),
        ):
            handle.write(
                f'##INFO=<ID={name},Number={number},Type={kind},Description="Synthetic">\n'
            )
        handle.write(
            "\t".join(("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")) + "\n"
        )
        handle.write("\n".join(rows) + "\n")
    index = FrequencyIndex.build(
        path,
        output=root / "synthetic-frequency.sqlite",
        version="r2.1.1",
        input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(pipeline, "default_index", lambda **kw: index)
    return index


@pytest.mark.privacy
@pytest.mark.parametrize("source", ["imputed_untyped", "imputed_no_call"])
@pytest.mark.parametrize("ploidy", [1, 2])
def test_rare_imputed_snapshot_keeps_gate_native_evidence_and_scoped_ppv_in_both_views(
    source: str,
    ploidy: int,
    export: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = rare_record(source, ploidy)
    pack = rare_pack(ploidy)
    monkeypatch.setattr(KnowledgePack, "load", lambda _: pack)
    if source == "imputed_no_call":
        spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
        export.write_text(
            render_fixture(
                replace(
                    spec,
                    spike_ins={
                        "rs900000001": (23 if ploidy == 1 else 7, record.pos_grch37, "0", "0")
                    },
                )
            ),
            encoding="utf-8",
        )
    index = install_frequency_index(
        monkeypatch, tmp_path, frequency_rows(record, 0.000005, split=ploidy == 2)
    )
    stages: list[ImputationResult] = []

    def stage(original: GenotypeTable, **kwargs: Any) -> ImputationResult:
        saved = synthetic_stage(
            original,
            tmp_path / "stage",
            records=(*anchors(record.chrom, start=record.pos_grch37 + 50, ploidy=ploidy), record),
        )
        stages.append(saved)
        return saved

    monkeypatch.setattr(pipeline, "impute", stage)
    original_lookup = lookup_default
    observed_tables: list[GenotypeTable] = []

    def lookup(original: GenotypeTable, **kwargs: Any) -> Any:
        observed_tables.append(original)
        return original_lookup(original, **kwargs)

    monkeypatch.setattr(pipeline, "lookup_default", lookup)
    invocation = CliRunner().invoke(app, ["run", "--input", str(export), "--json"])
    assert invocation.exit_code == 0, invocation.output
    assert_no_genotype(invocation.output)
    path = Path(json.loads(invocation.stdout)["path"])
    bundle = read_bundle(path)
    assert bundle.format_version == 16 and len(bundle.cards) == 1
    saved = bundle.cards[0]
    assert saved.confidence_tier == "likely-artifact"
    assert (
        saved.confidence_frequency is not None
        and saved.confidence_frequency["frequency"] == 0.000005
    )
    assert saved.observation is not None
    assert saved.observation["imputation"] == ImputationEvidence.from_record(record).to_dict()
    assert saved.imputation_mode == "enabled"
    original = observed_tables[0].frame.filter(
        (pl.col("chrom") == record.chrom) & (pl.col("pos_grch37") == record.pos_grch37)
    )
    assert (
        original.is_empty()
        if source == "imputed_untyped"
        else original["call_status"].to_list() == ["no_call"]
    )
    assert stages[0].original is observed_tables[0]
    # Delete only these generated cache bytes. Saved reads must use the full bundle.
    for file in stages[0].directory.iterdir():
        file.unlink()
    index.path.unlink()
    monkeypatch.setattr(
        pipeline,
        "default_index",
        lambda **kw: pytest.fail("Saved read reopened frequency reference"),
    )
    monkeypatch.setattr(
        pipeline, "impute", lambda *a, **kw: pytest.fail("Saved read reran imputation")
    )
    assert read_bundle(path).cards[0] == saved
    assert any(r.source == source and r.ploidy == ploidy for r in bundle.iter_dosages())
    shown = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert shown.exit_code == 0
    payload = json.loads(shown.stdout)["cards"][0]
    assert payload["confidence"]["tier"] == saved.confidence_tier
    assert payload["confidence_frequency"] == saved.confidence_frequency
    assert payload["observation"] == saved.observation
    assert payload["computed_caveats"] == list(saved.computed_caveats)
    ppv = payload["confidence"]["empirical_ppv"]
    assert ppv["estimate"] == 0.16 and "imputation" in ppv["applies_to"]
    with TestClient(create_app(WebConfig()), base_url="http://127.0.0.1") as client:
        face = client.get(f"/runs/{path.name}")
        detail = client.get(f"/runs/{path.name}/cards/{saved.card_id}")
    assert face.status_code == detail.status_code == 200
    for body in (face.text, detail.text):
        assert "likely-artifact" in body and "16%" in body
        assert "Not calibrated" in body and "imputation" in body
        assert "not an individual posterior probability" in body
    assert source in detail.text and record.quality_scope in detail.text
    assert "0.0005%" in detail.text
    assert "quality unknown" in face.text if source == "imputed_no_call" else "DR2 1" in face.text


@pytest.mark.parametrize("source", ["imputed_untyped", "imputed_no_call"])
def test_rare_imputed_marker_caps_entire_multimarker_finding(
    source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import yaml

    raw = yaml.safe_load((Path(__file__).parents[2] / "knowledge/health/apoe.yaml").read_text())[
        "cards"
    ][0]
    card = Card.parse(raw, "synthetic rare-marker observation")
    assert card.match is not None
    first, second = card.match.variants
    original = table(
        ("19", first.key.pos_grch37, "CC", "called"),
        *(
            ([("19", second.key.pos_grch37, None, "no_call")])
            if source == "imputed_no_call"
            else []
        ),
    )
    record = replace(
        rare_record(source),
        chrom="19",
        pos_grch37=second.key.pos_grch37,
        ref="T",
        alt=("C",),
        genotype=(1, 1),
        storage_genotype=(1, 1),
        dosage=(2.0,),
        storage_dosage=(2.0,),
    )
    install_records(monkeypatch, (record,))
    pack = KnowledgePack((card,), PACK)
    target, metadata = card_input(pack, result(original, tmp_path, source), sex=InferredSex.MALE)
    matches = match_pack(pack, target)
    records = {
        ("19", first.key.pos_grch37): [
            parse_record(r)
            for r in frequency_rows(replace(record, pos_grch37=first.key.pos_grch37), 0.2)
        ],
        ("19", second.key.pos_grch37): [parse_record(r) for r in frequency_rows(record, 0.000005)],
    }
    assembled = assemble_pack(
        pack, matches, pipeline.observations(pack, matches, records, metadata)
    )[0]
    assert assembled.has_interpretation and assembled.confidence is not None
    assert assembled.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT
    payload = _card_payload(assembled)
    multi = payload["multi_marker"]
    assert multi["phase"] == "unphased" and len(multi["candidate_diplotypes"]) == 1
    strong, rare = multi["markers"]
    assert strong["confidence"]["tier"] != "likely-artifact"
    assert rare["confidence"]["tier"] == "likely-artifact"
    assert rare["observation"]["imputation_quality"] == (
        None if source == "imputed_no_call" else 1.0
    )
    assert payload["confidence"] == rare["confidence"]
    validate_snapshot(payload)
    validate_imputation_snapshot(payload, require_detail=True)


@pytest.mark.parametrize("called", [False, True])
def test_no_impute_preserves_original_rare_call_and_never_discovers_prerequisites(
    called: bool,
    export: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pack = rare_pack()
    monkeypatch.setattr(KnowledgePack, "load", lambda _: pack)
    if called:
        spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
        export.write_text(
            render_fixture(replace(spec, spike_ins={"rs900000001": (7, LOCUS[1], "A", "G")})),
            encoding="utf-8",
        )
    install_frequency_index(
        monkeypatch, tmp_path, frequency_rows(rare_record("imputed_untyped"), 0.000005)
    )

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Explicit opt-out discovered imputation prerequisites")

    monkeypatch.setattr(pipeline, "impute", forbidden)
    monkeypatch.setattr(Beagle, "discover", forbidden)
    monkeypatch.setattr(BrefTools, "discover", forbidden)
    monkeypatch.setattr("genetics.imputation.reference.PreparedReference.default", forbidden)
    analysis = pipeline.analyse(export, no_impute=True)
    card = analysis.cards[0]
    assert analysis.imputation_result is None and card.imputation_mode == "disabled"
    assert card.observation is not None and card.observation.call_source is CallSource.DIRECT
    assert card.observation.imputation is None
    assert card.has_interpretation is called
    if called:
        assert (
            card.confidence is not None and card.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT
        )
    else:
        assert card.status is MatchStatus.MARKER_ABSENT and card.confidence is None


@pytest.mark.parametrize("gene", ["BRCA1:672", "BRCA2:675"])
def test_brca_chip_benchmark_is_explicitly_uncalibrated_for_imputation(gene: str) -> None:
    benchmark = clinvar_benchmark({"GENEINFO": gene, "CLNSIG": "Pathogenic"})
    assert benchmark["estimate"] == 0.042
    assert benchmark["scope"] == "brca_pathogenic"
    assert benchmark["population_frequency_ceiling"] is None
    assert "pooled across" in benchmark["applies_to"]
    assert "not an individual posterior probability" in benchmark["applies_to"]
    assert "not calibrated" in benchmark["applies_to"] and "imputation" in benchmark["applies_to"]


@pytest.mark.parametrize("ploidy", [1, 2])
def test_enabled_imputation_keeps_original_rare_observation_and_its_gate(
    ploidy: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = rare_record("imputed_untyped", ploidy)
    pack = rare_pack(ploidy)
    locus = (record.chrom, record.pos_grch37)
    genotype = "GG" if ploidy == 1 else "AG"
    original = table((*locus, genotype, "hemizygous" if ploidy == 1 else "called"))
    # Even a contradictory, perfectly imputed observation cannot replace the probe.
    install_records(
        monkeypatch,
        (
            replace(
                record,
                genotype=(0,) * ploidy,
                storage_genotype=(0,) * ploidy,
                dosage=(0.0,),
                storage_dosage=(0.0,),
            ),
        ),
    )
    target, metadata = card_input(pack, result(original, tmp_path), sex=InferredSex.MALE)
    assert target is original and not metadata
    matches = match_pack(pack, target)
    assembled = assemble_pack(
        pack,
        matches,
        pipeline.observations(
            pack,
            matches,
            {locus: [parse_record(row) for row in frequency_rows(record, 0.000005)]},
            metadata,
        ),
    )[0]
    assert assembled.has_interpretation and assembled.confidence is not None
    assert assembled.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT
    assert assembled.observation is not None
    assert assembled.observation.call_source is CallSource.DIRECT
    assert assembled.observation.imputation is None
    assert assembled.match.observed_genotype == genotype
