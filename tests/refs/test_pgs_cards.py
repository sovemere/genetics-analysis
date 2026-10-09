"""M9.6 polygenic cards end to end, on fabricated scores, panels, cards and exports.

The export is the committed synthetic fixture; the score's five rows sit on positions it
carries. The panel is the M9.4 fixed-seed synthetic panel relabelled with real 1000 Genomes
codes. Every weight, rate and citation here is invented. No real reference, personal export
or private run is read.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import pytest
import test_pgs_reference
from fastapi.testclient import TestClient
from test_pgs_portability import GWAS, Placed
from test_pgs_reference import MultiPlink, build_panel, calls
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine.card_lint import lint_pack
from genetics.engine.cards import (
    Ancestry,
    CardError,
    Effect,
    EffectMeasure,
    Evidence,
    EvidenceTier,
    KnowledgePack,
    Replication,
    parse_file,
)
from genetics.engine.confidence import ConfidenceTier, calculate_polygenic_confidence
from genetics.engine.matcher import MatchStatus
from genetics.paths import runs_dir
from genetics.pgs import runner
from genetics.pgs.cards import INTERVAL_BASIS, NOT_A_RISK, record_digest
from genetics.pgs.catalog import ID_COLUMN, TERMS_COLUMN, Catalog, PgsError, ScoreMetadata
from genetics.pgs.runner import PolygenicStage, locate_scoring_file
from genetics.pgs.scoring import ScoringFile
from genetics.refs import lock as refs_lock
from genetics.run.bundle import (
    CARDS_NAME,
    MANIFEST_NAME,
    PGS_NAME,
    BundleError,
    read_bundle,
)
from genetics.run.pipeline import analyse, save
from genetics.web import WebConfig, create_app

EXPORT = Path(__file__).parents[1] / "fixtures" / "synthetic" / "ancestry_v2_male.txt"
REAL_POPS = (("CEU", "EUR"), ("KHV", "EAS"), ("YRI", "AFR"))
# (position, effect, other, weight): the fixture export calls CC, CT, CT, CT, AA here.
ROWS = [
    (284347, "C", "A", 0.4),
    (825342, "T", "C", 0.3),
    (1926295, "C", "T", -0.2),
    (2600571, "T", "C", 0.5),
    (423627, "A", "G", 0.25),
]
CEU = Placed("CEU", "EUR", [("CEU", 1.0), ("YRI", 9.0)])
DOI = "10.5555/synthetic-pgs"

CARD = f"""
schema_version: 4
cards:
  - id: synthetic_polygenic
    section: physical_health
    kind: polygenic
    title: Synthetic polygenic score
    pgs: {{id: PGS000001, source: pgs000001_grch37}}
    trait: synthetic trait
    summary: A fabricated five-variant score used only by tests.
    detail: Every weight, frequency and rate here is invented.
    evidence:
      tier: gwas
      effect: {{measure: odds_ratio, value: 1.5, ci_low: 1.4, ci_high: 1.6,
               context: per standard deviation of the synthetic score}}
      sample_size: 100000
      ancestry: [EUR]
      replication: independent
      within_family_attenuation: 0.6
    decile_outcomes:
      measure: cumulative incidence to age 80
      population: a synthetic cohort
      sample_size: 50000
      source: "{DOI}"
      base_rate: 0.1
      rates: [0.04, 0.05, 0.06, 0.07, 0.08, 0.1, 0.11, 0.13, 0.15, 0.21]
    citations:
      - {{type: doi, id: "{DOI}", title: A synthetic polygenic score study}}
"""


@pytest.fixture
def fake() -> MultiPlink:
    return MultiPlink(Path("synthetic-plink"), "synthetic-test")


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(test_pgs_reference, "POPS", REAL_POPS)
    monkeypatch.setattr("genetics.pgs.reference.cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "refs"
    build_panel(
        root,
        {
            "1": [
                (pos, other, effect, calls(30, 0.2 + i / 10, seed=i))
                for i, (pos, effect, other, _) in enumerate(ROWS)
            ]
        },
    )
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "polygenic.yaml").write_text(CARD, encoding="utf-8")
    scoring_path = tmp_path / "score" / "synthetic-score.txt"
    scoring_path.parent.mkdir()
    scoring_path.write_text(
        "#format_version=2.0\n#pgs_id=PGS000001\n#genome_build=GRCh37\n"
        f"#variants_number={len(ROWS)}\n#weight_type=beta\n"
        "rsID\tchr_name\tchr_position\teffect_allele\tother_allele\teffect_weight\n"
        + "".join(
            f"rs{1000 + i}\t1\t{pos}\t{effect}\t{other}\t{weight}\n"
            for i, (pos, effect, other, weight) in enumerate(ROWS)
        ),
        encoding="utf-8",
    )
    catalog = Catalog(
        {
            "PGS000001": ScoreMetadata(
                "PGS000001",
                ({ID_COLUMN: "PGS000001", TERMS_COLUMN: "CC0-1.0", GWAS: "European:100"},),
            )
        },
        {"filename": "synthetic_metadata.csv", "sha256": "c" * 64, "size_bytes": 100},
        "pgs_all_metadata_scores.csv",
    )
    monkeypatch.setattr(runner, "locate_scoring_file", lambda card, root: scoring_path)
    return {"root": root, "knowledge": knowledge, "catalog": catalog, "scoring": scoring_path}


def stage(setup: dict[str, Any], fake: MultiPlink, **kwargs: Any) -> PolygenicStage:
    return PolygenicStage(
        references_root=setup["root"],
        plink=fake,
        catalog=setup["catalog"],
        workers=1,
        placement=kwargs.pop("placement", CEU),
        **kwargs,
    )


def run(setup: dict[str, Any], fake: MultiPlink, **kwargs: Any) -> Any:
    return analyse(
        EXPORT,
        knowledge_dir=setup["knowledge"],
        ancestry=lambda table, qc: AncestryContext.not_run("synthetic: no ancestry stage"),
        no_impute=True,
        polygenic=stage(setup, fake, **kwargs),
    )


def polygenic_card(analysis: Any) -> Any:
    return next(c for c in analysis.cards if c.card_id == "synthetic_polygenic")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _mutated(old: str, new: str) -> str:
    assert old in CARD
    return CARD.replace(old, new, 1)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("schema_version: 4", "schema_version: 3", "schema_version 4"),
        ("section: physical_health", "section: ancestry", "does not belong"),
        ("id: PGS000001,", "id: PGS1,", "PGS Catalog score ID"),
        (
            "used only by tests.",
            "used only by tests {confidence}.",
            "cannot be filled",
        ),
        (f'source: "{DOI}"', 'source: "10.5555/other"', "citations"),
        ("rates: [0.04,", "rates: [4,", "proportions"),
        ("rates: [0.04, 0.05,", "rates: [", "exactly ten"),
        ("trait: synthetic trait", "trait: ''", "trait"),
    ],
)
def test_polygenic_schema_refuses_malformed_cards(old: str, new: str, message: str) -> None:
    with pytest.raises(CardError, match=message):
        parse_file(_mutated(old, new), "polygenic.yaml")


def test_polygenic_card_parses_and_lints() -> None:
    (card,) = parse_file(CARD, "polygenic.yaml")
    assert card.pgs is not None and card.pgs.pgs_id == "PGS000001"
    assert card.decile_outcomes is not None and len(card.decile_outcomes.rates) == 10
    assert card.evidence is not None and card.evidence.within_family_attenuation == 0.6
    report = lint_pack(KnowledgePack((card,), Path(".")), resolve_variants=False)
    assert report.ok, report.issues


# ---------------------------------------------------------------------------
# Confidence: the calculator's own weights and thresholds
# ---------------------------------------------------------------------------


def evidence(**changes: Any) -> Evidence:
    base: dict[str, Any] = {
        "tier": EvidenceTier.GWAS,
        "effect": Effect(EffectMeasure.ODDS_RATIO, 4.0),
        "sample_size": 100_000,
        "ancestry": (Ancestry.EUR,),
        "replication": Replication.META_ANALYSIS,
    }
    return Evidence(**{**base, **changes})


@pytest.mark.parametrize(
    ("kwargs", "tier", "ceiling"),
    [
        ({}, ConfidenceTier.WELL_ESTABLISHED, None),
        ({"weight_coverage": 0.2}, ConfidenceTier.LIMITED, "coverage"),
        ({"weight_coverage": 0.4}, ConfidenceTier.MODERATE, "coverage"),
        ({"weighted_quality": 0.2}, ConfidenceTier.LIKELY_ARTIFACT, "imputation_quality"),
        ({"weighted_quality": 0.7}, ConfidenceTier.MODERATE, "imputation_quality"),
        ({"ancestry_match": None}, ConfidenceTier.STRONG, "ancestry"),
        ({"ancestry_match": 0.0}, ConfidenceTier.LIMITED, "ancestry"),
    ],
)
def test_polygenic_confidence_ceilings(
    kwargs: dict[str, Any], tier: ConfidenceTier, ceiling: str | None
) -> None:
    inputs: dict[str, Any] = {
        "weight_coverage": 1.0,
        "weighted_quality": 1.0,
        "unknown_quality_weight_fraction": 0.0,
        "ancestry_match": 1.0,
    }
    result = calculate_polygenic_confidence(evidence(), **{**inputs, **kwargs})
    assert result.tier is tier
    assert list(result.ceilings) == ([] if ceiling is None else [ceiling])
    weak = calculate_polygenic_confidence(evidence(tier=EvidenceTier.CANDIDATE_GENE), **inputs)
    assert weak.tier is ConfidenceTier.MODERATE and weak.ceilings == ("evidence",)


# ---------------------------------------------------------------------------
# The run: one engine, two front-ends
# ---------------------------------------------------------------------------


def test_a_run_scores_places_and_faces_the_card_without_a_point(
    setup: dict[str, Any], fake: MultiPlink
) -> None:
    analysis = run(setup, fake)
    card = polygenic_card(analysis)
    assert card.status is MatchStatus.COMPUTED
    record = analysis.polygenic["synthetic_polygenic"]
    result = card.computation["result"]
    assert result["score_sha256"] == record_digest(record)
    assert result["phase"] == "before" and result["imputation_mode"] == "disabled"
    # No point estimate leaves the private record: no sum, no point percentile.
    text = json.dumps(result)
    assert "person_sum" not in text and '"percentile"' not in text
    low, high = result["position"]["percentile_interval_95"]
    assert low < high
    # Every statement 4.5 requires is on the face.
    assert "between the" in card.summary and INTERVAL_BASIS in card.summary
    assert "Ancestry portability: matched" in card.summary
    assert "Within-family studies retain about 60%" in card.summary
    assert "against 10% overall" in card.summary and "not a prediction for you" in card.summary
    assert card.computation["reliability"]["tier"] is not None
    assert result["portability"]["ancestry_match"] == 1.0


def test_not_fetched_unlicensed_and_unplaced_cards_still_render_with_reasons(
    setup: dict[str, Any], fake: MultiPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "locate_scoring_file", lambda card, root: "Not fetched. `fix`.")
    card = polygenic_card(run(setup, fake))
    assert card.status is MatchStatus.NOT_RUN and "Not fetched. `fix`." in card.summary
    assert card.computation["result"] is None and card.computation["reliability"]["tier"] is None

    monkeypatch.setattr(runner, "locate_scoring_file", lambda card, root: setup["scoring"])
    restricted = Catalog(
        {
            "PGS000001": ScoreMetadata(
                "PGS000001",
                ({ID_COLUMN: "PGS000001", TERMS_COLUMN: "CC-BY-NC-ND-4.0"},),
            )
        },
        setup["catalog"].source,
        "pgs_all_metadata_scores.csv",
    )
    setup = {**setup, "catalog": restricted}
    card = polygenic_card(run(setup, fake))
    assert card.status is MatchStatus.NOT_RUN and "opt-in" in card.summary


def test_no_reference_panel_leaves_the_score_unplaced_but_recorded(
    setup: dict[str, Any], fake: MultiPlink, tmp_path: Path
) -> None:
    analysis = run({**setup, "root": tmp_path / "empty-refs"}, fake)
    card = polygenic_card(analysis)
    assert card.status is MatchStatus.NOT_RUN and "No reference distribution" in card.summary
    assert analysis.polygenic["synthetic_polygenic"]["reference_distribution"]["status"] == (
        "not_run"
    )
    assert card.computation["result"]["position"] is None


def test_saved_run_round_trips_through_bundle_cli_and_dashboard(
    setup: dict[str, Any], fake: MultiPlink
) -> None:
    analysis = run(setup, fake)
    path = save(analysis)
    bundle = read_bundle(path)
    stored = next(c for c in bundle.cards if c.card_id == "synthetic_polygenic")
    assert stored.kind == "polygenic" and stored.status == "computed"
    assert stored.confidence_tier == polygenic_card(analysis).computation["reliability"]["tier"]
    assert bundle.polygenic is not None
    assert bundle.polygenic["synthetic_polygenic"] == analysis.polygenic["synthetic_polygenic"]

    shown = CliRunner().invoke(app, ["runs", "show", bundle.run_id, "--json"])
    assert shown.exit_code == 0, shown.output
    card_json = next(c for c in json.loads(shown.stdout)["cards"] if c["kind"] == "polygenic")
    assert card_json["computation"] == stored.computation
    assert card_json["citations"][0]["id"] == DOI

    config = WebConfig(runs_root=runs_dir())
    with TestClient(create_app(config), base_url="http://127.0.0.1:8765") as client:
        page = client.get(f"/runs/{bundle.run_id}")
        assert page.status_code == 200 and 'class="pgschart pgschart-compact"' in page.text
        detail = client.get(f"/runs/{bundle.run_id}/cards/synthetic_polygenic")
        assert detail.status_code == 200
        html = detail.text
        assert 'class="pgsband"' in html and html.count('class="pgsbar"') >= 1
        assert "Absolute rates by score decile" in html and "overlaps" in html
        assert "Why this tier" in html and "Comparable weight" in html


def _rewrite(path: Path, name: str, change: Any) -> None:
    target = path / name
    data = json.loads(target.read_text(encoding="utf-8"))
    change(data)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _card(data: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in data["cards"] if c["kind"] == "polygenic")


def tamper_cases() -> dict[str, Any]:
    def face(data: dict[str, Any]) -> None:
        _card(data)["summary"] = _card(data)["summary"].replace("between the", "at the")

    def point(data: dict[str, Any]) -> None:
        _card(data)["computation"]["result"]["position"]["percentile"] = 50.0

    def tier(data: dict[str, Any]) -> None:
        _card(data)["computation"]["reliability"]["tier"] = "well-established"

    def evidence_tier(data: dict[str, Any]) -> None:
        _card(data)["evidence"]["tier"] = "clinical_guideline"

    def status(data: dict[str, Any]) -> None:
        _card(data)["status"] = "not_run"
        _card(data)["computation"]["status"] = "not_run"

    return {f.__name__: (CARDS_NAME, f) for f in (face, point, tier, evidence_tier, status)} | {
        "record_sum": (
            PGS_NAME,
            lambda d: d["scores"]["synthetic_polygenic"]["before"].update(sum=99.0),
        ),
        "record_portability": (
            PGS_NAME,
            lambda d: d["scores"]["synthetic_polygenic"]["portability"].update(ancestry_match=0.1),
        ),
        "record_missing": (PGS_NAME, lambda d: d["scores"].clear()),
        "record_orphan": (
            PGS_NAME,
            lambda d: d["scores"].update(extra=d["scores"]["synthetic_polygenic"]),
        ),
    }


@pytest.mark.parametrize("case", sorted(tamper_cases()))
def test_tampered_polygenic_runs_are_refused(
    setup: dict[str, Any], fake: MultiPlink, case: str
) -> None:
    path = save(run(setup, fake))
    name, change = tamper_cases()[case]
    _rewrite(path, name, change)
    with pytest.raises(BundleError):
        read_bundle(path)


def test_an_older_format_cannot_carry_a_polygenic_card(
    setup: dict[str, Any], fake: MultiPlink
) -> None:
    path = save(run(setup, fake))
    manifest = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["format_version"] = 16
    del manifest["files"][PGS_NAME]
    (path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="format 17"):
        read_bundle(path)


# ---------------------------------------------------------------------------
# Locating the public scoring file
# ---------------------------------------------------------------------------


def test_scoring_files_are_lock_verified(tmp_path: Path) -> None:
    (card,) = parse_file(CARD, "polygenic.yaml")
    root = tmp_path / "refs"
    reason = locate_scoring_file(card, root)
    assert isinstance(reason, str) and "genetics refs fetch --only pgs000001_grch37" in reason
    target = root / "pgs000001_grch37" / "PGS000001_hmPOS_GRCh37.txt.gz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"synthetic scoring bytes")
    digest = hashlib.sha256(b"synthetic scoring bytes").hexdigest()
    refs_lock.write(
        root / "manifest.lock",
        refs_lock.Lock(
            sources={
                "pgs000001_grch37": refs_lock.LockedSource(
                    "latest",
                    "LicenseRef-PGS-Catalog-Per-Score",
                    {
                        target.name: refs_lock.LockedFile(
                            "https://example.invalid/x", digest, 23, "2026-10-09"
                        )
                    },
                )
            }
        ),
    )
    assert locate_scoring_file(card, root) == target
    target.write_bytes(b"tampered scoring bytes!")
    with pytest.raises(PgsError, match="does not match its lock"):
        locate_scoring_file(card, root)


def test_card_interval_and_face_never_carry_a_point(
    setup: dict[str, Any], fake: MultiPlink
) -> None:
    card = polygenic_card(run(setup, fake))
    position = card.computation["result"]["position"]
    assert set(position) == {"percentile_interval_95", "deciles", "score_interval", "basis"}
    a, b = position["score_interval"]
    assert math.isfinite(a) and math.isfinite(b) and a <= b
    assert NOT_A_RISK not in card.summary
    assert isinstance(ScoringFile, type)


def test_an_unknown_manifest_source_is_a_reason_and_a_lint_issue(tmp_path: Path) -> None:
    (card,) = parse_file(_mutated("source: pgs000001_grch37", "source: no_such_source"), "p.yaml")
    reason = locate_scoring_file(card, tmp_path)
    assert isinstance(reason, str) and "no source 'no_such_source'" in reason
    report = lint_pack(KnowledgePack((card,), Path(".")), resolve_variants=False)
    assert [issue.code for issue in report.issues] == ["pgs-source-missing"]
    (wrong,) = parse_file(_mutated("id: PGS000001,", "id: PGS000002,"), "p.yaml")
    report = lint_pack(KnowledgePack((wrong,), Path(".")), resolve_variants=False)
    assert [issue.code for issue in report.issues] == ["pgs-source-mismatch"]


def test_dashboard_geometry_keeps_the_band_and_labels_inside_the_chart(
    setup: dict[str, Any], fake: MultiPlink
) -> None:
    from genetics.web.polygenic import WIDTH, PolygenicView

    computation = polygenic_card(run(setup, fake)).computation
    view = PolygenicView.of(computation)
    assert view is not None and view.placed
    assert view.band_x >= 0 and view.band_x + view.band_width <= WIDTH and view.band_width >= 3
    counts = computation["result"]["distribution"]["histogram"]["counts"]
    assert len(view.bars) == sum(1 for c in counts if c)
    xs = [tick.x for tick in view.ticks]
    assert xs == sorted(xs) and all(b - a >= 56 for a, b in itertools.pairwise(xs))
    for tick in view.ticks:
        assert tick.anchor == (
            "start" if tick.x < 28 else "end" if tick.x > WIDTH - 28 else "middle"
        )
    # The view has no field that could hold a point estimate.
    assert not any(name == "percentile" or "sum" in name for name in vars(view))
    unplaced = PolygenicView.of({**computation, "result": None})
    assert unplaced is None
