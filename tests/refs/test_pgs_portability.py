"""M9.5 ancestry portability on fabricated scores, panels and placements.

The panel is the M9.4 fixed-seed synthetic panel relabelled with real 1000 Genomes
population codes, because the cited mapping is keyed on them. Ancestry distributions are
invented metadata text. No real panel file, personal export or private run is read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
import test_pgs_reference
from test_pgs_engine import dosage, probe, table
from test_pgs_reference import ROWS, MultiPlink, Stub, build_panel, calls
from typer.testing import CliRunner

from genetics.ancestry.context import PopulationResult
from genetics.cli.main import app
from genetics.engine.cards import (
    Ancestry,
    Effect,
    EffectMeasure,
    Evidence,
    EvidenceTier,
    Replication,
)
from genetics.engine.confidence import CallSource, ConfidenceTier, calculate_confidence
from genetics.pgs import portability
from genetics.pgs.catalog import ID_COLUMN, TERMS_COLUMN, Catalog, PgsError, ScoreMetadata
from genetics.pgs.engine import score, write_result
from genetics.pgs.portability import (
    DISPLAY_CATEGORY,
    STAGE_COLUMNS,
    THOUSAND_GENOMES_CATEGORY,
    compute_portability,
    parse_distribution,
    read_portability,
)
from genetics.pgs.reference import attach_reference
from genetics.pgs.scoring import ScoringFile
from genetics.qc.report import InferredSex

REAL_POPS = (("CEU", "EUR"), ("KHV", "EAS"), ("YRI", "AFR"))
GWAS, DEV, EVAL = (STAGE_COLUMNS[s] for s in ("gwas", "development", "evaluation"))


@pytest.fixture
def fake() -> MultiPlink:
    return MultiPlink(Path("synthetic-plink"), "synthetic-test")


@pytest.fixture
def panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(test_pgs_reference, "POPS", REAL_POPS)
    monkeypatch.setattr("genetics.pgs.reference.cache_dir", lambda: tmp_path / "cache")
    root = tmp_path / "refs"
    build_panel(
        root,
        {
            "1": [
                (101, "C", "A", calls(30, 0.3, seed=1)),
                (102, "T", "G", calls(30, 0.4, seed=2)),
                (105, "C", "A", calls(30, 0.2, seed=5)),
            ]
        },
    )
    return root


def ancestry_definition(directory: Path, **columns: str) -> ScoringFile:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "synthetic-score.txt"
    rows = ROWS[:5]
    keys = list(dict.fromkeys(key for row in rows for key in row))
    path.write_text(
        "#format_version=2.0\n#pgs_id=PGS000001\n#genome_build=GRCh37\n"
        f"#variants_number={len(rows)}\n#weight_type=beta\n"
        + "\t".join(keys)
        + "\n"
        + "".join("\t".join(row.get(k, "") for k in keys) + "\n" for row in rows),
        encoding="utf-8",
    )
    metadata = {ID_COLUMN: "PGS000001", TERMS_COLUMN: "CC0-1.0"}
    names = {"gwas": GWAS, "development": DEV, "evaluation": EVAL}
    metadata.update({names[k]: v for k, v in columns.items()})
    catalog = Catalog(
        {"PGS000001": ScoreMetadata("PGS000001", (metadata,))},
        {"filename": "synthetic_metadata.csv", "sha256": "b" * 64, "size_bytes": 100},
        "pgs_all_metadata_scores.csv",
    )
    return ScoringFile.open(path, catalog)


class Placed(Stub):
    """A 1000 Genomes placement with ranked fits, as M5.5 serializes one."""

    def __init__(self, population: str, region: str, fits: list[tuple[str, float]]):
        super().__init__("placed", population, region)
        self.fits = [{"population": p, "region": "?", "fit": f} for p, f in fits]

    def to_dict(self) -> dict[str, Any]:
        return {**self.data, "decline_threshold": 2.5, "fits": self.fits}


def aadr(status: str) -> dict[str, Any]:
    reason = "" if status == "placed" else f"Synthetic AADR {status}."
    return {"population": {"status": status, "reason": reason, "population": None}}


def scored(
    tmp_path: Path,
    fake: MultiPlink,
    *,
    saved: bool = False,
    aadr_status: str | None = "placed",
    **columns: str,
) -> tuple[ScoringFile, Any]:
    scoring = ancestry_definition(tmp_path / "def", **columns)
    result = score(
        scoring,
        table=None if saved else table([probe(101, copies=2), probe(102)]),
        dosages=[dosage(105, values=(0.5,))],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
        ancestry=None if aadr_status is None else aadr(aadr_status),
    )
    return scoring, result


def attach(
    tmp_path: Path,
    fake: MultiPlink,
    root: Path,
    placement: Any = None,
    *,
    saved: bool = False,
    aadr_status: str | None = "placed",
    **columns: str,
) -> Any:
    scoring, result = scored(tmp_path, fake, saved=saved, aadr_status=aadr_status, **columns)
    return scoring, attach_reference(
        result,
        scoring,
        table=None,
        references_root=root,
        plink=fake,
        workspace=tmp_path / "ref",
        workers=1,
        placement=None if placement is None else cast(PopulationResult, placement),
    )


CEU = Placed("CEU", "EUR", [("CEU", 1.0), ("YRI", 9.0)])


# ---------------------------------------------------------------------------
# The cited mappings
# ---------------------------------------------------------------------------


def test_every_thousand_genomes_population_has_its_table_one_category() -> None:
    assert len(THOUSAND_GENOMES_CATEGORY) == 26
    assert set(THOUSAND_GENOMES_CATEGORY.values()) <= set(DISPLAY_CATEGORY)
    # The super-population is not the mapping: KHV is South East Asian, ACB/ASW are not
    # Sub-Saharan African, and the catalog folds them into different display categories.
    assert DISPLAY_CATEGORY[THOUSAND_GENOMES_CATEGORY["KHV"]] == "Additional Asian Ancestries"
    assert DISPLAY_CATEGORY[THOUSAND_GENOMES_CATEGORY["CDX"]] == "East Asian"
    assert THOUSAND_GENOMES_CATEGORY["ACB"] == "African American or Afro-Caribbean"
    assert DISPLAY_CATEGORY[THOUSAND_GENOMES_CATEGORY["ACB"]] == "African"
    # Categories without a reference population are never a placement target.
    unreachable = {
        "Greater Middle Eastern",
        "Additional Diverse Ancestries",
    }
    reachable = {DISPLAY_CATEGORY[c] for c in THOUSAND_GENOMES_CATEGORY.values()}
    assert not unreachable & reachable
    assert portability.merged_categories("African") == [
        "African American or Afro-Caribbean",
        "African unspecified",
        "Sub-Saharan African",
    ]


def test_distribution_text_keeps_every_share_and_refuses_malformed_text() -> None:
    reported = parse_distribution("European:72.7|Not Reported:18.2|East Asian:9.1")
    assert reported["status"] == "reported" and reported["total_percent"] == 100.0
    assert [s["kind"] for s in reported["shares"]] == ["category", "not_reported", "category"]
    assert parse_distribution("European:99.9")["shares"][0]["fraction"] == 1.0
    rounded = parse_distribution("European:99.8|African:0.1|East Asian:0.02|Not Reported:0")
    assert rounded["status"] == "reported" and rounded["shares"][-1]["fraction"] == 0.0
    assert parse_distribution("Martian:100")["shares"][0]["kind"] == "unrecognised"
    assert parse_distribution("")["status"] == "empty"
    assert parse_distribution(None)["status"] == "column_absent"
    for bad in ("European", "European:abc", "European:0", "European:60|European:40", "EUR:90"):
        assert parse_distribution(bad)["status"] == "malformed"


# ---------------------------------------------------------------------------
# The acceptance matrix
# ---------------------------------------------------------------------------


def cases() -> dict[str, dict[str, Any]]:
    return {
        "matched": {
            "placement": CEU,
            "columns": {"gwas": "European:100", "evaluation": "East Asian:100"},
            "expect": ("matched", 1.0, None, "gwas"),
        },
        "mismatched": {
            "placement": CEU,
            "columns": {"gwas": "East Asian:60|Greater Middle Eastern:40"},
            "expect": ("mismatched", 0.0, "limited", "gwas"),
        },
        "multi_ancestry": {
            "placement": CEU,
            "columns": {"gwas": "European:40|Multi-ancestry (including European):60"},
            "expect": ("partial", 0.4, "moderate", "gwas"),
        },
        "multi_excluding_european_is_a_mismatch_for_a_european": {
            "placement": CEU,
            "columns": {"gwas": "Multi-ancestry (excluding European):100"},
            "expect": ("mismatched", 0.0, "limited", "gwas"),
        },
        "unreported": {
            "placement": CEU,
            "columns": {"gwas": "Not Reported:100"},
            "expect": ("not_demonstrated", 0.0, "limited", "gwas"),
        },
        "development_drives_without_gwas": {
            "placement": CEU,
            "columns": {"gwas": "", "development": "European:70|Not Reported:30"},
            "expect": ("partial", 0.7, None, "development"),
        },
        "nothing_reported_at_any_driving_stage": {
            "placement": CEU,
            "columns": {"evaluation": "European:100"},
            "expect": ("not_demonstrated", 0.0, "limited", None),
        },
        "south_east_asian_sample_is_not_east_asian": {
            "placement": Placed("KHV", "EAS", [("KHV", 1.0), ("CEU", 8.0)]),
            "columns": {"gwas": "East Asian:100"},
            "expect": ("mismatched", 0.0, "limited", "gwas"),
        },
        "declined_by_thousand_genomes": {
            "placement": Stub("declined"),
            "columns": {"gwas": "European:100"},
            "expect": ("sample_unrepresented", 0.0, "limited", "gwas"),
        },
        "declined_by_aadr_is_not_rescued_by_a_placement": {
            "placement": CEU,
            "aadr": "declined",
            "columns": {"gwas": "European:100"},
            "expect": ("sample_unrepresented", 0.0, "limited", "gwas"),
        },
        "not_run": {
            "placement": Stub("not_run"),
            "aadr": "not_run",
            "columns": {"gwas": "European:100"},
            "expect": ("not_computed", None, "strong", "gwas"),
        },
        "saved_only": {
            "placement": None,
            "saved": True,
            "columns": {"gwas": "European:100"},
            "expect": ("not_computed", None, "strong", "gwas"),
        },
    }


@pytest.mark.parametrize("case", sorted(cases()))
def test_acceptance_matrix_labels_every_case_and_filters_nothing(
    tmp_path: Path, fake: MultiPlink, panel: Path, case: str
) -> None:
    spec = cases()[case]
    _, unadjusted = scored(
        tmp_path / "plain",
        fake,
        saved=spec.get("saved", False),
        aadr_status=spec.get("aadr", "placed"),
        **spec["columns"],
    )
    _, result = attach(
        tmp_path,
        fake,
        panel,
        spec["placement"],
        saved=spec.get("saved", False),
        aadr_status=spec.get("aadr", "placed"),
        **spec["columns"],
    )
    block = result.record["portability"]
    judgment, match, ceiling, driving = spec["expect"]
    assert block["judgment"] == judgment
    assert block["ancestry_match"] == match
    assert block["confidence_ceiling"] == ceiling
    assert block["study"]["driving_stage"] == driving
    assert block["schema_version"] == 1 and block["sources"]["sample_mapping"]["doi"] == (
        "10.1186/s13059-018-1396-2"
    )
    # Non-filtering: sums, terms and coverage are those of the unadjusted score, and a
    # percentile is still reported whenever the reference placed one.
    for key in ("before", "after", "terms", "coverage", "status"):
        assert result.record[key] == unadjusted.record[key]
    assert result.record["percentile"]["after"] is not None
    # The calculator accepts the number and still returns a result at every tier.
    evidence = Evidence(
        tier=EvidenceTier.GWAS,
        effect=Effect(EffectMeasure.ODDS_RATIO, 4.0),
        sample_size=100_000,
        ancestry=(Ancestry.EUR,),
        replication=Replication.META_ANALYSIS,
    )
    confidence = calculate_confidence(
        evidence,
        population_allele_frequency=0.3,
        call_source=CallSource.DIRECT,
        ancestry_match=block["ancestry_match"],
    )
    assert confidence.inputs.ancestry_match == match
    if ceiling is not None:
        assert confidence.tier.rank >= ConfidenceTier(ceiling).rank
    else:
        assert confidence.tier is ConfidenceTier.WELL_ESTABLISHED


def test_declined_and_saved_only_states_say_why(
    tmp_path: Path, fake: MultiPlink, panel: Path
) -> None:
    _, both = attach(
        tmp_path / "a", fake, panel, Stub("declined"), aadr_status="declined", gwas="European:100"
    )
    sample = both.record["portability"]["sample"]
    assert sample["state"] == "declined" and sample["declined_by"] == ["aadr", "thousand_genomes"]
    assert both.record["reference_distribution"]["group"]["ancestry_matched"] is False
    _, saved = attach(tmp_path / "b", fake, panel, saved=True, gwas="European:100")
    block = saved.record["portability"]
    assert block["sample"]["state"] == "saved_only" and "pooled" in block["reason"]
    assert block["match"] is None and block["stage_matches"] == {}
    _, saved_declined = attach(
        tmp_path / "c", fake, panel, saved=True, aadr_status="declined", gwas="European:100"
    )
    assert saved_declined.record["portability"]["ancestry_match"] == 0.0


def test_admissible_neighbours_in_another_category_are_recorded(
    tmp_path: Path, fake: MultiPlink, panel: Path
) -> None:
    placement = Placed("KHV", "EAS", [("KHV", 1.0), ("CDX", 1.8), ("CEU", 7.0)])
    _, result = attach(tmp_path, fake, panel, placement, gwas="East Asian:100")
    sample = result.record["portability"]["sample"]
    assert sample["display_category"] == "Additional Asian Ancestries"
    assert sample["alternative_display_categories"] == ["East Asian"]
    assert result.record["portability"]["ancestry_match"] == 0.0


def test_low_level_and_unplaced_results_carry_an_explicit_block(
    tmp_path: Path, fake: MultiPlink
) -> None:
    _, result = scored(tmp_path, fake, aadr_status=None, gwas="European:100")
    block = result.record["portability"]
    assert block["sample"]["state"] == "not_run"
    assert block["sample"]["aadr"]["status"] == "not_supplied"
    assert block["sample"]["thousand_genomes"]["basis"] == "reference_not_requested"


# ---------------------------------------------------------------------------
# Persistence: API, CLI and stored equality, independent of the extraction cache
# ---------------------------------------------------------------------------


def saved_result(tmp_path: Path, fake: MultiPlink, panel: Path) -> tuple[ScoringFile, Path]:
    scoring, result = attach(
        tmp_path, fake, panel, CEU, gwas="European:80|Not Reported:20", development="East Asian:100"
    )
    return scoring, write_result(result, tmp_path / "out" / "synthetic.pgs-score.json")


def test_portability_round_trips_through_api_cli_and_cold_or_warm_cache(
    tmp_path: Path, fake: MultiPlink, panel: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoring, path = saved_result(tmp_path / "cold", fake, panel)
    assert list((tmp_path / "cache").rglob("*.pgs-reference.tsv.gz"))
    _, warm = saved_result(tmp_path / "warm", fake, panel)
    stored = json.loads(path.read_text(encoding="utf-8"))["portability"]
    assert json.loads(warm.read_text(encoding="utf-8"))["portability"] == stored
    loaded = read_portability(path, scoring=scoring)
    assert loaded["portability_origin"] == "persisted_verified"
    assert loaded["portability"] == stored and stored["ancestry_match"] == 0.8
    assert stored["stage_matches"]["development"]["mismatched"] == 1.0
    monkeypatch.setattr(
        Catalog,
        "default",
        lambda: Catalog(
            {"PGS000001": scoring.metadata}, scoring.metadata_source, "pgs_all_metadata_scores.csv"
        ),
    )
    cli = CliRunner().invoke(
        app, ["pgs", "portability", str(path), "--scoring-file", str(scoring.path), "--json"]
    )
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout) == {"ok": True, **loaded}
    text = CliRunner().invoke(app, ["pgs", "portability", str(path)])
    assert text.exit_code == 0 and "partial; ancestry_match 0.800" in text.stdout


def tamper_cases() -> dict[str, Any]:
    def number(data: dict[str, Any]) -> None:
        data["portability"]["ancestry_match"] = 1.0

    def judgment(data: dict[str, Any]) -> None:
        data["portability"]["judgment"] = "matched"

    def ceiling(data: dict[str, Any]) -> None:
        data["portability"]["confidence_ceiling"] = "limited"

    def study_text(data: dict[str, Any]) -> None:
        row = data["score_definition"]["metadata"]["metadata_rows"][0]
        row[GWAS] = "European:100"

    def aadr_status(data: dict[str, Any]) -> None:
        data["ancestry"]["population"]["status"] = "declined"

    def missing(data: dict[str, Any]) -> None:
        del data["portability"]["sample"]

    def placeholder(data: dict[str, Any]) -> None:
        data["portability"] = "not_computed_M9.5"

    return {
        f.__name__: f
        for f in (number, judgment, ceiling, study_text, aadr_status, missing, placeholder)
    }


@pytest.mark.parametrize("case", sorted(tamper_cases()))
def test_tampered_portability_is_refused(
    tmp_path: Path, fake: MultiPlink, panel: Path, case: str
) -> None:
    _, path = saved_result(tmp_path, fake, panel)
    data = json.loads(path.read_text(encoding="utf-8"))
    tamper_cases()[case](data)
    path.unlink()
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PgsError):
        read_portability(path)


def test_schema_three_results_are_recomputed_and_labelled(
    tmp_path: Path, fake: MultiPlink, panel: Path
) -> None:
    _, path = saved_result(tmp_path, fake, panel)
    data = json.loads(path.read_text(encoding="utf-8"))
    current = data["portability"]
    data["schema_version"] = 3
    data["coverage"]["score_schema_version"] = 3
    data["portability"] = "not_computed_M9.5"
    path.unlink()
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = read_portability(path)
    assert loaded["portability_origin"] == "recomputed_legacy"
    assert loaded["portability"] == current


def test_unrecoverable_inputs_are_refused_not_defaulted() -> None:
    with pytest.raises(PgsError):
        compute_portability({"score_definition": {"metadata": {"metadata_rows": []}}})
