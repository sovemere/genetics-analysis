"""M9.3 per-score coverage from fabricated observations; no real export is used."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_pgs_engine import MatrixPlink, definition, dosage, probe, table, weight
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.pgs.catalog import Catalog, PgsError
from genetics.pgs.coverage import compute_coverage, read_coverage, summary
from genetics.pgs.engine import ScoreResult, score, write_result
from genetics.qc.report import InferredSex


@pytest.fixture
def fake() -> MatrixPlink:
    return MatrixPlink(Path("synthetic-plink"), "synthetic-test")


def run(tmp_path: Path, fake: MatrixPlink, rows: list[dict[str, str]], **kwargs: Any) -> Any:
    kwargs.setdefault("sex", InferredSex.FEMALE)
    return score(
        definition(tmp_path / "def", rows), plink=fake, workspace=tmp_path / "work", **kwargs
    )


def test_source_denominators_separate_rows_variants_positions_and_undefined_rows(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    rows = [
        weight(101),
        weight(101, value="0.5"),  # repeated authored row of one variant
        weight(101, effect="C", other="A"),  # same variant, the other effect allele
        weight(101, effect="A", other="G"),  # a second variant at the same position
        weight(102),
        {"rsID": "rs9000001", "effect_allele": "A", "other_allele": "C", "effect_weight": "1"},
        weight(103, effect="I", other="D"),
        weight(104, other=""),
    ]
    result = run(tmp_path, fake, rows, table=table([probe(101)]), no_impute=True)
    source = result.record["coverage"]["source"]
    assert source["rows"] == 8
    assert source["variants"] == 3  # 101 A/C, 101 A/G, 102 A/C
    assert source["repeated_variants"] == 1 and source["rows_in_repeated_variants"] == 3
    assert source["variants_with_multiple_effect_alleles"] == 1
    assert source["positions"] == 4 and source["positions_with_multiple_rows"] == 1
    assert source["positions_with_multiple_variants"] == 1
    assert source["model_eligible_rows"] == 5
    assert source["model_ineligible_rows"] == {
        "allele_contract_missing": 2,
        "unresolved_locus": 1,
    }
    undefined = {row["row_number"]: row for row in source["undefined_rows"]}
    assert undefined[6]["missing"] == "locus"
    assert undefined[7]["missing"] == "alleles" and undefined[8]["missing"] == "alleles"
    assert undefined[7]["definition"]["effect_allele"] == "I"  # raw authored definition kept
    before = result.record["coverage"]["before"]
    assert before["rows"]["total"] == 8 and before["rows"]["scored"] == 3
    assert before["row_fraction"] == 3 / 8
    assert result.record["terms"][3]["before"]["status"] == "allele_mismatch"
    assert before["variants"] == {
        "total": 3,
        "with_usable_dose": 1,
        "partially_observed": 0,
        "fraction": pytest.approx(1 / 3),
    }
    assert before["positions"]["with_usable_dose"] == 1
    assert before["positions"]["evidence_present"] == 1
    assert before["positions"]["evidence_absent"] == 3
    assert before["weight"]["absolute_total"] == 7.5
    assert before["weight"]["fraction"] == pytest.approx(2.5 / 7.5)


def test_duplicate_probes_are_classified_without_changing_row_counts(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    rows = [weight(101), weight(102), weight(103), weight(104), weight(105, effect="A", other="T")]
    probes = [
        probe(101),
        probe(101),  # identical
        probe(102),
        probe(102, effect="T", other="G"),  # same call on the opposite strand
        probe(103, copies=0),
        probe(103, copies=2),  # conflicting
        probe(104),
        probe(104, copies=None),  # one call is not a comparison
        probe(105, copies=2, effect="A", other="T"),
        probe(105, copies=2, effect="T", other="A"),  # palindromic: not reconcilable
    ]
    result = run(tmp_path, fake, rows, table=table(probes), no_impute=True).record
    original = result["coverage"]["original_probes"]
    assert original["probes"] == 10 and original["positions_on_array"] == 5
    assert original["positions_with_duplicate_probes"] == 5
    assert original["duplicate_positions"] == {
        "identical": 1,
        "complement_concordant": 1,
        "conflicting": 2,
        "insufficient_calls": 1,
        "unclassified": 0,
    }
    states = [term["before"]["status"] for term in result["terms"]]
    assert states == [
        "observed",
        "observed",
        "duplicate_conflict",
        "observed",
        "duplicate_conflict",
    ]
    assert result["coverage"]["before"]["rows"]["scored"] == 3


def test_observed_zero_is_covered_while_no_call_and_absent_are_distinct(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    rows = [weight(101), weight(102), weight(103)]
    result = run(
        tmp_path,
        fake,
        rows,
        table=table([probe(101, copies=0), probe(102, copies=None)]),
        no_impute=True,
    ).record
    before = result["coverage"]["before"]
    assert result["before"]["sum"] == 0
    assert before["status"] == "partial" and before["rows"]["scored"] == 1
    assert before["rows"]["by_state"] == {"marker_absent": 1, "no_call": 1, "observed": 1}
    positions = before["positions"]
    assert positions["with_usable_dose"] == 1
    assert positions["evidence_present"] == 2 and positions["evidence_absent"] == 1
    assert positions["evidence_fraction"] == pytest.approx(2 / 3)
    assert result["coverage"]["original_probes"]["positions_called"] == 1


def test_no_overlap_is_a_real_zero_but_disabled_and_unrecorded_are_unavailable(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    direct = run(tmp_path, fake, [weight()], table=table([probe(102)]), no_impute=True).record
    assert direct["coverage"]["before"]["status"] == "no_usable_observations"
    assert direct["coverage"]["before"]["row_fraction"] == 0.0
    after = direct["coverage"]["after"]
    assert after["status"] == "unavailable" and after["reason"] == "disabled"
    assert after["row_fraction"] is None and after["rows"] is None
    saved = run(tmp_path / "saved", fake, [weight()], table=None, dosages=[dosage(101)]).record
    before = saved["coverage"]["before"]
    assert before["status"] == "unavailable" and before["reason"] == "not_recorded"
    assert before["row_fraction"] is None
    assert saved["coverage"]["original_probes"] == {
        "status": "unavailable",
        "reason": "not_recorded",
    }
    assert saved["coverage"]["after"]["row_fraction"] == 1.0
    lines = summary(saved["coverage"])
    assert "unavailable (not_recorded), not 0%" in lines[0]


def test_low_unknown_quality_multiallelic_ref_and_haploid_doses_are_described_not_filtered(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    rows = [
        weight(101, value="2"),
        weight(102, value="-1"),
        weight(103, effect="A", other="C", value="0.5"),
        weight(100001, chrom="X", value="1"),
        weight(10_000_000, chrom="X", value="3"),
        weight(104, value="1"),
    ]
    result = run(
        tmp_path,
        fake,
        rows,
        sex=InferredSex.MALE,
        table=table([probe(101, copies=2), probe(102, copies=None)]),
        dosages=[
            dosage(102, values=(2.0,), quality=None, genotype=(1, 1), source="imputed_no_call"),
            dosage(103, ref="A", alt=("C", "T"), values=(0.2, 0.3), quality=(0.9, 0.9)),
            dosage(100001, chrom="X", values=(1.0,), quality=(0.01,)),
            dosage(10_000_000, chrom="X", ploidy=1, genotype=(0,), values=(0.25,), quality=(1.0,)),
        ],
    ).record
    after = result["coverage"]["after"]
    assert after["status"] == "partial" and after["rows"]["scored"] == 5
    observations = after["observations"]
    assert observations["sources"] == {"direct": 1, "imputed_no_call": 1, "imputed_untyped": 3}
    assert observations["ploidy"] == {"1": 1, "2": 4}
    quality = observations["quality"]
    assert quality["estimated"] == 2
    assert quality["unknown"] == {
        "allele_quality_unknown": 1,
        "not_estimated:observed_allele_count": 1,
        "not_estimated:phased_hardcall_only": 1,
    }
    assert quality["dr2_min"] == 0.01 and quality["dr2_max"] == 1.0
    bins = {b["lower"]: (b["rows"], b["absolute_weight"]) for b in quality["dr2_bins"]}
    assert bins[0.0] == (1, 1.0) and bins[0.9] == (1, 3.0)
    assert quality["absolute_weight_unknown_quality"] == 3.5
    # Quality neither hides the low-DR2 row nor rescales its dose.
    assert result["terms"][3]["after"]["value"] == 1.0
    assert result["after"]["sum"] == pytest.approx(4 - 2 + 0.5 * 1.5 + 1 + 0.75)


def test_original_precedence_and_partially_observed_variants(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    rows = [weight(101), weight(102, effect="A", other="T"), weight(102, effect="T", other="A")]
    result = run(
        tmp_path,
        fake,
        rows,
        table=table([probe(101, copies=2)]),
        dosages=[dosage(101, values=(0.5,)), dosage(102, ref="A", alt=("T",), values=(1.0,))],
    ).record
    after = result["coverage"]["after"]
    assert after["observations"]["sources"] == {"direct": 1, "imputed_untyped": 2}
    assert result["terms"][0]["after"]["value"] == 2.0  # never replaced by the 0.5 dosage
    assert after["variants"]["with_usable_dose"] == 2
    assert after["variants"]["partially_observed"] == 0


def test_unsupported_model_keeps_observations_but_has_no_scored_fraction(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    rows = [weight(101), weight(102, is_dominant="True")]
    result = run(tmp_path, fake, rows, table=table([probe(101)]), no_impute=True).record
    before = result["coverage"]["before"]
    assert before["status"] == "unsupported_model"
    assert before["rows"]["observed"] == 1 and before["rows"]["scored"] == 0
    assert before["row_fraction"] is None and before["weight"]["fraction"] is None
    assert before["observed_row_fraction"] == 0.5
    assert result["coverage"]["source"]["unsupported_model"] is True
    assert result["coverage"]["after"]["status"] == "unavailable"


def test_cli_api_and_persisted_coverage_are_equal(
    tmp_path: Path, fake: MatrixPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoring = definition(tmp_path / "def", [weight(101), weight(102)])
    result = score(
        scoring,
        table=table([probe(101)]),
        dosages=[dosage(102)],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    )
    path = write_result(result, tmp_path / "out" / "synthetic.pgs-score.json")
    loaded = read_coverage(path, scoring=scoring)
    assert loaded["coverage_origin"] == "persisted_verified"
    assert loaded["coverage"] == json.loads(json.dumps(result.record["coverage"]))
    assert loaded["artifact_schema_version"] == 2
    monkeypatch.setattr(
        Catalog,
        "default",
        lambda: Catalog(
            {"PGS000001": scoring.metadata}, scoring.metadata_source, "pgs_all_metadata_scores.csv"
        ),
    )
    cli = CliRunner().invoke(
        app, ["pgs", "coverage", str(path), "--scoring-file", str(scoring.path), "--json"]
    )
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout) == {"ok": True, **loaded}
    text = CliRunner().invoke(app, ["pgs", "coverage", str(path)])
    assert text.exit_code == 0 and "2/2 weighted rows scored" in text.stdout


def corrupt_cases() -> dict[str, Any]:
    def coverage_value(data: dict[str, Any]) -> None:
        data["coverage"]["after"]["rows"]["scored"] = 1

    def term_state(data: dict[str, Any]) -> None:
        data["terms"][1]["after"]["status"] = "no_call"

    def lost_proof(data: dict[str, Any]) -> None:
        data["terms"][2]["before"]["native_record"] = None

    def foreign_proof(data: dict[str, Any]) -> None:
        data["terms"][0]["before"]["native_record"]["probes"][0]["pos_grch37"] = 999

    def phase_state(data: dict[str, Any]) -> None:
        data["original_table_sha256"] = None

    def row_order(data: dict[str, Any]) -> None:
        data["terms"][0]["row_number"] = 3

    def schema(data: dict[str, Any]) -> None:
        data["schema_version"] = 3

    def missing(data: dict[str, Any]) -> None:
        del data["coverage"]

    def bad_panel(data: dict[str, Any]) -> None:
        data["terms"][1]["after"]["native_record"]["dr2"] = [2.0]

    return {
        function.__name__: function
        for function in (
            coverage_value,
            term_state,
            lost_proof,
            foreign_proof,
            phase_state,
            row_order,
            schema,
            missing,
            bad_panel,
        )
    }


@pytest.mark.parametrize("case", sorted(corrupt_cases()))
def test_corrupted_saved_coverage_inputs_are_rejected(
    tmp_path: Path, fake: MatrixPlink, case: str
) -> None:
    rows = [weight(101), weight(102), weight(103, effect="A", other="T")]
    result = run(
        tmp_path,
        fake,
        rows,
        table=table([probe(101), probe(103, copies=2, effect="A", other="T")]),
        dosages=[dosage(102)],
    )
    path = write_result(result, tmp_path / "out" / "synthetic.pgs-score.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["terms"][2]["before"]["status"] == "strand_ambiguous"
    corrupt_cases()[case](data)
    path.unlink()
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PgsError):
        read_coverage(path)


def test_scoring_file_mismatch_is_rejected(tmp_path: Path, fake: MatrixPlink) -> None:
    result = run(tmp_path, fake, [weight(101)], table=table([probe(101)]), no_impute=True)
    path = write_result(result, tmp_path / "out" / "synthetic.pgs-score.json")
    other = definition(tmp_path / "other", [weight(101, value="2")])
    with pytest.raises(PgsError, match="supplied scoring file"):
        read_coverage(path, scoring=other)


def test_legacy_schema_one_missing_proof_stays_unknown_and_phase_states_are_not_trusted(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    rows = [weight(101), weight(102, hm_match_pos="False"), weight(103, is_dominant="True")]
    result = run(
        tmp_path,
        fake,
        rows,
        table=table([probe(101), probe(102)]),
        no_impute=True,
    )
    current = result.to_dict()
    data = json.loads(json.dumps(current))
    assert data["terms"][1]["before"]["native_record"]["kind"] == "original_array"
    # Fabricate the pre-review artifact shape: proof dropped, disabled states overwritten.
    data["schema_version"] = 1
    del data["coverage"]
    data["terms"][1]["before"]["native_record"] = None
    data["after"]["status"] = "unsupported_model"
    for term in data["terms"]:
        term["after"] = {**term["after"], "status": "unsupported_model"}
    path = tmp_path / "legacy.pgs-score.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    report = read_coverage(path)
    assert report["coverage_origin"] == "recomputed_legacy"
    coverage = report["coverage"]
    assert coverage["evidence_proof"] == "legacy_excluded_row_proof_may_be_missing"
    positions = coverage["before"]["positions"]
    # Neither the dropped proof nor an ineligible row without proof proves absence.
    assert positions["evidence_present"] == 1 and positions["evidence_unknown"] == 2
    assert positions["evidence_absent"] == 0
    assert positions["evidence_fraction"] is None
    assert positions["evidence_fraction_bounds"] == [pytest.approx(1 / 3), 1.0]
    assert coverage["original_probes"]["positions_unknown"] == 2
    assert (
        coverage["after"]["status"] == "unavailable" and coverage["after"]["reason"] == "disabled"
    )
    # A current artifact guarantees proof: no-proof ineligible rows are absent, and
    # overwritten unavailable phase states are corruption rather than legacy.
    fresh = compute_coverage(current, schema_version=2)
    assert fresh["before"]["positions"]["evidence_absent"] == 1
    assert fresh["before"]["positions"]["evidence_fraction"] == pytest.approx(2 / 3)
    overwritten = json.loads(json.dumps(current))
    overwritten["terms"][0]["after"]["status"] = "unsupported_model"
    with pytest.raises(PgsError):
        compute_coverage(overwritten, schema_version=2)


def test_in_memory_coverage_rejects_terms_that_disagree_with_their_source(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(tmp_path / "def", [weight(101)])
    result = score(
        scoring,
        table=table([probe(101)]),
        no_impute=True,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    )
    other = definition(tmp_path / "other", [weight(101, value="2")])
    with pytest.raises(PgsError, match="scoring source"):
        compute_coverage(result.record, schema_version=2, source_rows=list(other.iter_variants()))
    assert isinstance(result, ScoreResult) and result.to_dict()["schema_version"] == 2
