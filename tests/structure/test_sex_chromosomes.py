"""Synthetic profiles, PAR boundaries, immutable results and visible assay limits."""

from __future__ import annotations

import copy
import json
import random
import shutil
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.engine.cards import KnowledgePack
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import MatchStatus, match_pack
from genetics.ingest import ingest
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.paths import repo_root
from genetics.qc.metrics import heterozygosity, infer_sex, resolve_ploidy
from genetics.qc.report import InferredSex
from genetics.qc.sex_regions import coordinate_par_expr
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    BundleError,
    _card_payload,
    _stored_card,
    read_bundle,
)
from genetics.run.pipeline import analyse, save
from genetics.structure.sex_chromosomes import (
    LIMIT,
    SOURCE,
    compute_sex_chromosomes,
    infer_sex_chromosome_cards,
    validate_result,
)
from genetics.structure.sex_interpretation import assemble_sex_chromosome_card
from genetics.web import WebConfig, create_app

EXPORT = Path(__file__).parents[1] / "fixtures/synthetic/ancestry_v2_male.txt"


@pytest.fixture
def pack(tmp_path: Path) -> KnowledgePack:
    root = tmp_path / "knowledge/structure"
    root.mkdir(parents=True)
    shutil.copyfile(repo_root() / "knowledge/structure/sex_chromosomes.yaml", root / "sex.yaml")
    return KnowledgePack.load(root.parent)


def synthetic(
    x_hets: int = 0, y_called: int = 400, *, nx: int = 400, ny: int = 400
) -> GenotypeTable:
    """Fixed seed and invented reference frequency 0.3; controlled QC distortions.

    No real person's file or alleles enter this generator. Conditioning pairs on
    heterozygosity lets threshold tests specify exact counts rather than noise.
    """
    rng = random.Random(642026)
    rows: list[tuple[str, str, int, str | None, str | None, str | None, str]] = []
    for chrom, n in (("X", nx), ("Y", ny)):
        for i in range(n):
            allele = "G" if rng.random() < 0.3 else "A"
            pair = sorted(
                [allele, ("A" if allele == "G" else "G") if chrom == "X" and i < x_hets else allele]
            )
            called = chrom == "X" or i < y_called
            rows.append(
                (
                    f"rs{800000000 + len(rows)}",
                    chrom,
                    3_000_000 + i,
                    pair[0] if called else None,
                    pair[1] if called else None,
                    "".join(pair) if called else None,
                    "called" if called else "no_call",
                )
            )
    return GenotypeTable(
        pl.DataFrame(rows, schema=NORMALIZED_SCHEMA, orient="row"), vendor="synthetic"
    )


@pytest.mark.parametrize(
    ("x_hets", "y_called", "sex"),
    [
        (0, 400, "male"),
        (120, 0, "female"),
        (120, 400, "ambiguous"),
        (0, 0, "ambiguous"),
        (40, 400, "ambiguous"),
        (0, 80, "ambiguous"),
        (20, 120, "male"),
        (60, 60, "female"),
    ],
)
def test_literal_signals_and_threshold_edges_stay_visible(
    pack: KnowledgePack, x_hets: int, y_called: int, sex: str
) -> None:
    table = synthetic(x_hets, y_called)
    result = compute_sex_chromosomes(table)
    data = result.data
    assert data["x_het_rate"] == x_hets / 400 and data["y_call_rate"] == y_called / 400
    assert data["qc_inferred_sex"] == sex and data["status"] == "computed"
    assert infer_sex(table, heterozygosity(table)).inferred.value == sex
    validate_result(data, "computed")
    cards = infer_sex_chromosome_cards(assemble_pack(pack, match_pack(pack, table)), table)
    card = cards[0]
    assert card.has_interpretation and card.computation is not None
    assert card.computation["reliability"]["tier"] == "limited"
    assert LIMIT in card.summary and f"({x_hets}/400 SNP calls)" in card.summary
    if sex == "ambiguous":
        assert "ploidy remains unresolved" in card.summary
        resolved = resolve_ploidy(table, sex=InferredSex.AMBIGUOUS)
        assert not resolved.frame.filter(
            pl.col("call_status").cast(pl.String) == "hemizygous"
        ).height


@pytest.mark.parametrize(
    ("nx", "ny", "status"),
    [
        (0, 0, "insufficient_calls"),
        (99, 400, "insufficient_calls"),
        (100, 0, "computed"),
        (400, 1, "computed"),
    ],
)
def test_missing_and_sparse_signals_are_not_a_chromosome_count(
    pack: KnowledgePack, nx: int, ny: int, status: str
) -> None:
    result = compute_sex_chromosomes(synthetic(nx=nx, ny=ny))
    validate_result(result.data, status)
    card = assemble_sex_chromosome_card(pack.cards[0], result)
    assert card.status.value == status and LIMIT in card.summary
    if ny == 0:
        assert result.data["y_call_rate"] is None
        assert "no Y probes" in card.summary
    if nx == 0:
        assert result.data["x_het_rate"] is None
    if ny == 1:
        assert any("small denominator" in w for w in card.computed_caveats)


# Independent NCBI GRCh37 boundaries, deliberately not imported from implementation.
@pytest.mark.parametrize(
    ("chrom", "start", "end"),
    [
        ("X", 60001, 2699520),
        ("X", 154931044, 155260560),
        ("Y", 10001, 2649520),
        ("Y", 59034050, 59363566),
    ],
)
def test_par_endpoints_are_inclusive_and_called_par_stays_diploid(
    chrom: str, start: int, end: int
) -> None:
    table = synthetic(nx=4, ny=0)
    frame = table.frame.with_columns(
        pl.lit(chrom).cast(NORMALIZED_SCHEMA["chrom"]).alias("chrom"),
        pl.Series("pos_grch37", [start - 1, start, end, end + 1], dtype=pl.UInt32),
        pl.lit("G").alias("a2"),
        pl.lit("A").alias("a1"),
        pl.lit("AG").alias("genotype"),
    )
    table = GenotypeTable(frame, vendor="synthetic")
    result = compute_sex_chromosomes(table)
    assert result.data[chrom.lower()]["total"] == 2
    assert result.data["par_excluded"][f"coordinate_{chrom.lower()}"] == 2
    resolved = resolve_ploidy(table, sex=InferredSex.MALE).frame
    assert resolved.filter(coordinate_par_expr(chrom)).get_column("call_status").cast(
        pl.String
    ).to_list() == ["called", "called"]
    assert resolved.filter(~coordinate_par_expr(chrom)).get_column("call_status").cast(
        pl.String
    ).to_list() == ["het_haploid", "het_haploid"]
    if chrom == "X":
        assert heterozygosity(table).x_nonpar_loci == 2
    else:
        assert infer_sex(table, heterozygosity(table)).y_loci == 2


def test_indels_missingness_duplicate_probes_and_y_heterozygotes(pack: KnowledgePack) -> None:
    base = synthetic(120, 10)
    rows = base.frame.rows()
    rows.extend(
        [
            ("rs890000000", "X", 4_000_000, "D", "I", "DI", "called"),
            ("rs890000001", "X", 4_000_001, None, None, None, "no_call"),
            ("rs890000002", "Y", 4_000_000, "D", "I", "DI", "called"),
            ("rs890000003", "Y", 4_000_001, "A", "G", "AG", "called"),
            ("rs890000004", "PAR", 4_000_001, "A", "G", "AG", "called"),
            rows[0],
        ]
    )
    table = GenotypeTable(
        pl.DataFrame(rows, schema=NORMALIZED_SCHEMA, orient="row"), vendor="synthetic"
    )
    result = compute_sex_chromosomes(table)
    data = result.data
    assert data["x"]["snp_called"] == 401 and data["x"]["called"] == 402
    assert data["y_call_rate"] == round(12 / 402, 6) and data["y"]["heterozygous_snps"] == 1
    assert data["duplicate_positions"] == data["duplicate_rsids"] == 1
    assert data["par_excluded"]["vendor_labelled"] == 1
    validate_result(data, "computed")
    card = assemble_sex_chromosome_card(pack.cards[0], result)
    assert any("overweight" in w for w in card.computed_caveats)
    assert any("additional Y copies" in w for w in card.computed_caveats)


def test_pipeline_saved_cli_and_http_share_the_same_measurements(
    pack: KnowledgePack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    analysis = analyse(EXPORT, knowledge_dir=pack.source_dir)
    card = analysis.cards[0]
    assert card.computation is not None and card.computation["source"] == SOURCE
    data = card.computation["result"]
    assert data["x_het_rate"] == analysis.qc.sex.x_het_rate
    assert data["y_call_rate"] == analysis.qc.sex.y_call_rate
    path = save(analysis, lock_path=tmp_path / "absent", tools_root=tmp_path / "tools")
    assert read_bundle(path).format_version == BUNDLE_FORMAT_VERSION
    assert read_bundle(path).cards[0].computation == card.computation
    response = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert response.exit_code == 0
    assert json.loads(response.stdout)["cards"][0]["computation"] == card.computation
    with TestClient(
        create_app(WebConfig(runs_root=path.parent)), base_url="http://127.0.0.1:8765"
    ) as client:
        assert "Limited" in client.get(f"/runs/{path.name}").text
        detail = client.get(f"/runs/{path.name}/cards/{card.card_id}")
        assert detail.status_code == 200
        for text in (
            "not a karyotype",
            "Non-PAR X",
            "PAR boundaries",
            "207067",
            "10.1016/j.gim.2022.05.011",
        ):
            assert text in detail.text
        assert (
            "Archaic allele-sharing model" not in detail.text
            and "Observed F_ROH" not in detail.text
        )
    shutil.rmtree(pack.source_dir)
    assert read_bundle(path).cards[0].summary == card.summary


@pytest.mark.parametrize(
    "edit",
    [
        "rate",
        "nan",
        "count",
        "bool_count",
        "schema",
        "missing",
        "policy",
        "copy_number",
        "source",
        "sex",
        "tier",
        "status",
        "limitation",
    ],
)
def test_saved_inconsistent_measurements_are_rejected(pack: KnowledgePack, edit: str) -> None:
    payload: dict[str, Any] = copy.deepcopy(
        _card_payload(
            assemble_sex_chromosome_card(pack.cards[0], compute_sex_chromosomes(synthetic()))
        )
    )
    raw = payload["computation"]["result"]
    if edit == "rate":
        raw["x_het_rate"] = 0.3
    elif edit == "nan":
        raw["y_call_rate"] = float("nan")
    elif edit == "count":
        raw["x"]["snp_called"] = 1000
    elif edit == "bool_count":
        raw["x"]["heterozygous_snps"] = False
    elif edit == "schema":
        raw["schema_version"] = True
    elif edit == "missing":
        del raw["y"]
    elif edit == "policy":
        raw["settings"]["low_x_max"] = 0.9
    elif edit == "copy_number":
        raw["karyotype_determinable"] = True
    elif edit == "source":
        raw["source"] = "long_roh"
    elif edit == "sex":
        raw["qc_inferred_sex"] = "female"
    elif edit == "tier":
        payload["computation"]["reliability"]["tier"] = "well-established"
    elif edit == "status":
        raw["status"] = payload["status"] = payload["computation"]["status"] = "insufficient_calls"
    elif edit == "limitation":
        raw["warnings"] = []
    with pytest.raises(BundleError):
        _stored_card(payload, "synthetic corrupted sex-chromosome card")


def test_saved_profile_survives_current_wording_changes(
    pack: KnowledgePack, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.structure import sex_chromosomes

    payload = copy.deepcopy(
        _card_payload(
            assemble_sex_chromosome_card(pack.cards[0], compute_sex_chromosomes(synthetic()))
        )
    )
    monkeypatch.setattr(sex_chromosomes, "LIMIT", "Updated presentation of the assay limitation.")
    monkeypatch.setitem(sex_chromosomes.SETTINGS, "par_source", "https://example.org/new-source")
    monkeypatch.setitem(sex_chromosomes.SETTINGS, "duplicate_policy", "Updated policy wording.")
    assert (
        _stored_card(payload, "historical synthetic profile").computation == payload["computation"]
    )


def test_serialized_profile_is_an_independent_snapshot() -> None:
    from genetics.structure.sex_chromosomes import SETTINGS

    result = compute_sex_chromosomes(synthetic())
    serialized = result.as_dict()
    serialized["settings"]["par_boundaries"]["X"][0][0] = 0
    serialized["warnings"].clear()
    assert result.data["settings"]["par_boundaries"]["X"][0][0] == 60_001
    assert SETTINGS["par_boundaries"]["X"][0][0] == 60_001
    assert result.data["warnings"]


@pytest.mark.privacy
def test_result_repr_does_not_expose_derived_measurements() -> None:
    result = compute_sex_chromosomes(synthetic(120))
    assert "0.3" not in repr(result) and "x_het_rate" not in repr(result)
    assert "800000000" not in repr(result)


def test_default_assembly_preserves_a_not_run_card(pack: KnowledgePack) -> None:
    table = ingest(EXPORT).table
    card = assemble_pack(pack, match_pack(pack, table))[0]
    assert card.status is MatchStatus.NOT_RUN and card.computation is not None
    assert card.computation["result"] is None
