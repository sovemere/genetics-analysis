"""Fabricated boundary observations and fixed-seed native PGS arithmetic."""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.external.plink2 import Plink2, Plink2ResultInfo
from genetics.imputation.dosages import DosageRecord
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.paths import repo_root
from genetics.pgs import engine, workflow
from genetics.pgs.catalog import ID_COLUMN, TERMS_COLUMN, Catalog, PgsError, ScoreMetadata
from genetics.pgs.engine import score, write_result
from genetics.pgs.scoring import ScoringFile
from genetics.qc.report import InferredSex


def definition(
    directory: Path,
    rows: list[dict[str, str]],
    *,
    terms: str = "CC0-1.0",
) -> ScoringFile:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "synthetic-score.txt"
    columns = list(dict.fromkeys(key for row in rows for key in row))
    body = (
        "#format_version=2.0\n#pgs_id=PGS000001\n#genome_build=GRCh37\n"
        f"#variants_number={len(rows)}\n#weight_type=beta\n"
        + "\t".join(columns)
        + "\n"
        + "".join("\t".join(row.get(column, "") for column in columns) + "\n" for row in rows)
    )
    path.write_text(body, encoding="utf-8")
    catalog = Catalog(
        {"PGS000001": ScoreMetadata("PGS000001", ({ID_COLUMN: "PGS000001", TERMS_COLUMN: terms},))},
        {"filename": "synthetic_metadata.csv", "sha256": "a" * 64, "size_bytes": 100},
        "pgs_all_metadata_scores.csv",
    )
    return ScoringFile.open(path, catalog)


def weight(
    position: int = 101,
    *,
    effect: str = "A",
    other: str = "C",
    value: str = "1",
    chrom: str = "1",
    **extra: str,
) -> dict[str, str]:
    return {
        "rsID": f"rs{1000000 + position}",
        "chr_name": chrom,
        "chr_position": str(position),
        "effect_allele": effect,
        "other_allele": other,
        "effect_weight": value,
        **extra,
    }


def probe(
    position: int = 101,
    *,
    copies: int | None = 1,
    effect: str = "A",
    other: str = "C",
    chrom: str = "1",
    haploid: bool = False,
    status: str | None = None,
) -> dict[str, Any]:
    alleles = None if copies is None else sorted(effect * copies + other * (2 - copies))
    return {
        "rsid": f"rs{1000000 + position}",
        "chrom": chrom,
        "pos_grch37": position,
        "a1": None if alleles is None else alleles[0],
        "a2": None if alleles is None else alleles[1],
        "genotype": None if alleles is None else "".join(alleles),
        "call_status": status
        or ("no_call" if copies is None else "hemizygous" if haploid else "called"),
    }


def table(probes: list[dict[str, Any]]) -> GenotypeTable:
    return GenotypeTable(pl.DataFrame(probes, schema=NORMALIZED_SCHEMA), vendor="synthetic")


def dosage(
    position: int = 102,
    *,
    ref: str = "C",
    alt: tuple[str, ...] = ("A",),
    values: tuple[float, ...] = (1.25,),
    quality: tuple[float, ...] | None = (0.8,),
    genotype: tuple[int, ...] = (0, 1),
    chrom: str = "1",
    ploidy: int = 2,
    source: str = "imputed_untyped",
) -> DosageRecord:
    return DosageRecord(
        chrom,
        position,
        ref,
        alt,
        genotype,
        genotype,
        values,
        values,
        quality,
        ploidy,
        source,
        "resolved",
        None,
        "beagle_DS"
        if source == "imputed_untyped"
        else "phased_hardcall_only"
        if source == "imputed_no_call"
        else "observed_allele_count",
        "not_estimated"
        if quality is None
        else "beagle_haploid_dosage"
        if ploidy == 1
        else "beagle_diploid_dosage",
    )


class MatrixPlink(Plink2):
    mode = "good"

    def run(
        self,
        args: Sequence[str],
        *,
        out: Path,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> Plink2ResultInfo:
        assert "no-mean-imputation" in args
        assert args[args.index("--dosage-erase-threshold") + 1] == "0"
        assert "cols=nallele,denom,dosagesum,scoresums" in args
        matrix = Path(args[args.index("--vcf") + 1])
        weights = Path(args[args.index("--score") + 1])
        coefficients = {
            r.split()[0]: float(r.split()[2]) for r in weights.read_text().splitlines()[1:]
        }
        records = [r.split("\t") for r in matrix.read_text().splitlines() if not r.startswith("#")]
        ds = {r[2]: float(r[9].split(":")[1]) for r in records}
        assert all(r[0] == "1" and r[3:5] == ["C", "A"] for r in records)
        value = math.fsum(ds[key] * coefficients[key] for key in ds)
        target = "OTHER" if self.mode == "wrong_target" else "SAMPLE"
        total = (
            "nan"
            if self.mode == "nonfinite"
            else str(value + 1)
            if self.mode == "wrong_sum"
            else str(value)
        )
        count = 2 * len(records) + (2 if self.mode == "wrong_count" else 0)
        out.with_suffix(".sscore").write_text(
            "#IID\tALLELE_CT\tDENOM\tNAMED_ALLELE_DOSAGE_SUM\tWEIGHT_SUM\n"
            f"{target}\t{count}\t{count}\t{sum(ds.values())}\t{total}\n",
            encoding="utf-8",
        )
        used = sorted(ds) + (["OTHER_TERM"] if self.mode == "wrong_terms" else [])
        out.with_name(out.name + ".sscore.vars").write_text(
            "\n".join(used) + "\n", encoding="utf-8"
        )
        return Plink2ResultInfo(tuple(args), 0, "", "", out, out.with_suffix(".log"), ())


@pytest.fixture
def fake() -> MatrixPlink:
    return MatrixPlink(Path("synthetic-plink"), "synthetic-test")


@pytest.mark.parametrize("case", ["strand", "alleles", "ploidy", "duplicates"])
def test_review_excluded_native_terms_retain_full_evidence(
    tmp_path: Path, fake: MatrixPlink, case: str
) -> None:
    scoring = definition(tmp_path, [weight(102, other="T" if case == "strand" else "C")])
    records = (
        [dosage(ref="T", values=(1.25,))]
        if case == "strand"
        else [dosage(ref="G", alt=("C",))]
        if case == "alleles"
        else [dosage(ploidy=1, genotype=(0,), values=(0.25,))]
        if case == "ploidy"
        else [dosage(), dosage(values=(0.25,))]
    )
    data = score(
        scoring,
        table=None,
        dosages=records,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    observed = data["terms"][0]["after"]
    assert observed["status"] != "observed"
    proof = observed["native_record"]
    assert proof == (
        records[0].to_dict()
        if len(records) == 1
        else {"kind": "ambiguous_panel_records", "records": [r.to_dict() for r in records]}
    )


@pytest.mark.parametrize("saved", [False, True])
def test_review_unsupported_models_keep_phase_availability_and_input_evidence(
    tmp_path: Path, fake: MatrixPlink, saved: bool
) -> None:
    scoring = definition(tmp_path, [weight(102, is_dominant="True")])
    original = probe(102)
    record = dosage()
    data = score(
        scoring,
        table=None if saved else table([original]),
        dosages=[record] if saved else None,
        no_impute=not saved,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert data["status"] == "unsupported_model"
    assert data["before"]["status"] == ("not_recorded" if saved else "unsupported_model")
    assert data["after"]["status"] == ("unsupported_model" if saved else "disabled")
    term = data["terms"][0]
    assert term["before"]["status"] == ("not_recorded" if saved else "unsupported_model")
    assert (term["after"] if saved else term["before"])["native_record"] == (
        record.to_dict() if saved else {"kind": "original_array", "probes": [original]}
    )


def test_review_matrix_write_failure_is_categorical_and_cleans_partial_files(
    tmp_path: Path, fake: MatrixPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoring = definition(tmp_path, [weight()])
    native_open = Path.open

    def blocked(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name.endswith(".pgs-weights.tsv"):
            raise PermissionError("fabricated write failure")
        return native_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", blocked)
    with pytest.raises(PgsError, match="execution or validation"):
        score(
            scoring,
            table=table([probe()]),
            no_impute=True,
            sex=InferredSex.FEMALE,
            plink=fake,
            workspace=tmp_path / "work",
        )
    assert not list((tmp_path / "work").glob("*.vcf"))


def test_review_output_parent_failure_is_categorical(tmp_path: Path) -> None:
    parent = tmp_path / "a-file"
    parent.write_text("synthetic obstacle", encoding="utf-8")
    result = engine.ScoreResult("PGS000001", "no_usable_observations", {})
    with pytest.raises(PgsError, match="publish"):
        write_result(result, parent / "score.pgs-score.json")


def test_review_nonfinite_arithmetic_cannot_weaken_native_verification(
    tmp_path: Path, fake: MatrixPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoring = definition(tmp_path, [weight(value="1e308")])
    native_run = MatrixPlink.run

    def finite_wrong_report(self: MatrixPlink, args: Sequence[str], **kwargs: Any) -> Any:
        result = native_run(self, args, **kwargs)
        path = kwargs["out"].with_suffix(".sscore")
        path.write_text(path.read_text().replace("inf", "1e308"), encoding="utf-8")
        return result

    monkeypatch.setattr(MatrixPlink, "run", finite_wrong_report)
    with pytest.raises(PgsError, match="arithmetic"):
        score(
            scoring,
            table=table([probe(copies=2)]),
            no_impute=True,
            sex=InferredSex.FEMALE,
            plink=fake,
            workspace=tmp_path / "work",
        )


def test_review_stale_native_reports_cannot_be_reused_as_new_execution(
    tmp_path: Path, fake: MatrixPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoring = definition(tmp_path, [weight()])
    kwargs: dict[str, Any] = {
        "table": table([probe()]),
        "no_impute": True,
        "sex": InferredSex.FEMALE,
        "plink": fake,
        "workspace": tmp_path / "work",
    }
    assert score(scoring, **kwargs).status == "computed"

    def no_report(self: MatrixPlink, args: Sequence[str], *, out: Path, **kw: Any) -> Any:
        return Plink2ResultInfo(tuple(args), 0, "", "", out, out.with_suffix(".log"), ())

    monkeypatch.setattr(MatrixPlink, "run", no_report)
    with pytest.raises(PgsError, match="execution or validation"):
        score(scoring, **kwargs)


@pytest.mark.parametrize("name", ["no_impute", "allow_restricted"])
def test_review_workflow_rejects_nonboolean_flags_before_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    scoring = definition(tmp_path, [weight()], terms="CC-BY-NC-ND-4.0")

    def untouched(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid flags must fail before reading personal input")

    monkeypatch.setattr(workflow, "ingest", untouched)
    kwargs: dict[str, Any] = {"allow_restricted": True, name: "false"}
    with pytest.raises(PgsError, match="booleans"):
        workflow.score_export(scoring, tmp_path / "absent-export.txt", **kwargs)


@pytest.mark.parametrize("case", ["suffix", "checkout", "exists", "parent"])
def test_review_cli_validates_output_before_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    scoring = definition(tmp_path, [weight()])
    paths = {
        "suffix": tmp_path / "bad.json",
        "checkout": repo_root() / "tmp" / "never-created-review.pgs-score.json",
        "exists": tmp_path / "exists.pgs-score.json",
        "parent": tmp_path / "parent-file" / "score.pgs-score.json",
    }
    paths["exists"].write_text("synthetic existing result", encoding="utf-8")
    paths["parent"].parent.write_text("synthetic obstacle", encoding="utf-8")
    monkeypatch.setattr(
        Catalog,
        "default",
        lambda: Catalog(
            {"PGS000001": scoring.metadata}, scoring.metadata_source, "pgs_all_metadata_scores.csv"
        ),
    )

    def untouched(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid output must fail before analysis")

    monkeypatch.setattr(workflow, "score_export", untouched)
    result = CliRunner().invoke(
        app,
        [
            "pgs",
            "score",
            str(scoring.path),
            "--input",
            str(tmp_path / "absent-export.txt"),
            "--output",
            str(paths[case]),
            "--json",
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_both_sums_preserve_original_probes_low_quality_and_unknown_phase_quality(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(
        tmp_path, [weight(101, value="2"), weight(102, value="-0.5"), weight(103, value="0.25")]
    )
    original = table([probe(101, copies=1), probe(103, copies=None)])
    result = score(
        scoring,
        table=original,
        dosages=[
            dosage(102, values=(1.5,), quality=(0.01,)),
            dosage(103, values=(2.0,), quality=None, genotype=(1, 1), source="imputed_no_call"),
        ],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    )
    data = result.to_dict()
    assert data["before"]["sum"] == 2
    assert data["after"]["sum"] == 1.75
    assert data["terms"][0]["before"] == data["terms"][0]["after"]
    assert data["terms"][0]["before"]["native_record"]["kind"] == "original_array"
    assert data["terms"][0]["before"]["native_record"]["probes"] == [probe(101, copies=1)]
    assert data["terms"][1]["after"]["dr2"] == 0.01
    assert data["terms"][1]["after"]["value"] == 1.5
    assert data["terms"][2]["after"]["dr2"] is None
    assert data["terms"][2]["after"]["quality_scope"] == "not_estimated"
    assert data["before"]["status"] == "scored_partial"
    assert data["after"]["status"] == "scored"
    assert data["portability"] == "not_computed_M9.5" and data["percentile"] is None
    assert not list((tmp_path / "work").glob("*.vcf"))
    assert not list((tmp_path / "work").glob("*.pgs-weights.tsv"))


@pytest.mark.parametrize("source", ["imputed_untyped", "imputed_no_call", "direct"])
def test_saved_stage_sums_do_not_invent_original_array_observations(
    tmp_path: Path, fake: MatrixPlink, source: str
) -> None:
    scoring = definition(tmp_path, [weight()])
    rec = dosage(
        101, source=source, values=(1.0,), quality=(0.5,) if source == "imputed_untyped" else None
    )
    result = score(
        scoring,
        table=None,
        dosages=[rec],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["before"]["status"] == "not_recorded" and result["before"]["sum"] is None
    assert result["after"]["sum"] == 1
    assert result["original_table_sha256"] is None
    assert result["terms"][0]["after"]["source"] == source


@pytest.mark.parametrize(
    "effect,other,expected,quality", [("A", "C", 1.5, None), ("C", "A", 0.2, 0.01)]
)
def test_multiallelic_ref_and_alt_dose_keep_their_own_quality(
    tmp_path: Path,
    fake: MatrixPlink,
    effect: str,
    other: str,
    expected: float,
    quality: float | None,
) -> None:
    scoring = definition(tmp_path, [weight(effect=effect, other=other)])
    rec = dosage(101, ref="A", alt=("C", "T"), values=(0.2, 0.3), quality=(0.01, 0.99))
    result = score(
        scoring,
        table=None,
        dosages=[rec],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    observed = result["terms"][0]["after"]
    assert observed["value"] == expected and observed["dr2"] == quality
    assert observed["native_record"]["dr2"] == (0.01, 0.99)


@pytest.mark.parametrize(
    "before",
    [
        probe(copies=0),
        probe(copies=2),
        probe(copies=1, status="het_haploid"),
        probe(copies=2, effect="I", other="D"),
    ],
)
def test_called_original_observations_are_never_replaced_by_stage_dosage(
    tmp_path: Path, fake: MatrixPlink, before: dict[str, Any]
) -> None:
    scoring = definition(tmp_path, [weight()])
    result = score(
        scoring,
        table=table([before]),
        dosages=[dosage(101)],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["terms"][0]["before"] == result["terms"][0]["after"]


@pytest.mark.parametrize(
    "probes,status",
    [
        ([probe(copies=0), probe(copies=2)], "duplicate_conflict"),
        ([probe(copies=None)], "no_call"),
        ([probe(copies=1, effect="A", other="G")], "allele_mismatch"),
    ],
)
def test_invalid_original_matches_remain_explicit(
    tmp_path: Path, fake: MatrixPlink, probes: list[dict[str, Any]], status: str
) -> None:
    scoring = definition(tmp_path, [weight()])
    result = score(
        scoring,
        table=table(probes),
        no_impute=True,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["terms"][0]["before"]["status"] == status
    assert result["before"]["sum"] is None
    assert result["after"]["status"] == "disabled"


def test_complemented_duplicates_agree_but_palindromic_homozygotes_stay_ambiguous(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(tmp_path, [weight(), weight(102, effect="A", other="T")])
    original = table(
        [probe(), probe(effect="T", other="G"), probe(102, copies=2, effect="A", other="T")]
    )
    result = score(
        scoring,
        table=original,
        no_impute=True,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["before"]["sum"] == 1
    assert result["terms"][1]["before"]["status"] == "strand_ambiguous"


@pytest.mark.parametrize(
    "sex,copies,haploid,expected,status",
    [
        (InferredSex.MALE, 2, True, 1.0, "observed"),
        (InferredSex.FEMALE, 2, False, 2.0, "observed"),
        (InferredSex.AMBIGUOUS, 2, False, None, "ploidy_unresolved"),
        (InferredSex.MALE, 1, True, None, "ploidy_conflict"),
    ],
)
def test_nonpar_x_uses_biological_copy_count(
    tmp_path: Path,
    fake: MatrixPlink,
    sex: InferredSex,
    copies: int,
    haploid: bool,
    expected: float | None,
    status: str,
) -> None:
    scoring = definition(tmp_path, [weight(10_000_000, chrom="X")])
    original = table([probe(10_000_000, chrom="X", copies=copies, haploid=haploid)])
    result = score(
        scoring, table=original, no_impute=True, sex=sex, plink=fake, workspace=tmp_path / "work"
    ).to_dict()
    assert result["before"]["sum"] == expected
    assert result["terms"][0]["before"]["status"] == status


def test_par_diploid_and_fractional_haploid_doses_are_not_rescaled(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(tmp_path, [weight(100001, chrom="X"), weight(10_000_000, chrom="X")])
    result = score(
        scoring,
        table=None,
        dosages=[
            dosage(100001, chrom="X", values=(1.2,)),
            dosage(10_000_000, chrom="X", values=(0.25,), ploidy=1, genotype=(0,), quality=(0.1,)),
        ],
        sex=InferredSex.MALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["after"]["sum"] == 1.45
    assert result["after"]["native_alleles"] == 3
    assert result["after"]["plink_matrix_allele_ct"] == 4


@pytest.mark.parametrize(
    "feature", ["is_haplotype", "is_diplotype", "is_interaction", "is_dominant", "is_recessive"]
)
def test_nonadditive_models_are_reported_without_an_additive_score(
    tmp_path: Path, fake: MatrixPlink, feature: str
) -> None:
    row = weight()
    row[feature] = "TRUE"
    scoring = definition(tmp_path, [row])
    result = score(
        scoring,
        table=table([probe()]),
        no_impute=True,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["status"] == "unsupported_model"
    assert result["before"]["sum"] is None and result["after"]["sum"] is None
    assert result["terms"][0]["fields"][feature] == "TRUE"
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("terms", ["", "Academic research only", "CC-BY-NC-ND-4.0"])
def test_licence_gate_precedes_personal_scoring(
    tmp_path: Path, fake: MatrixPlink, terms: str
) -> None:
    scoring = definition(tmp_path, [weight()], terms=terms)
    with pytest.raises(PgsError, match="licence"):
        score(
            scoring,
            table=table([probe()]),
            no_impute=True,
            sex=InferredSex.FEMALE,
            plink=fake,
            workspace=tmp_path / "work",
        )
    if terms == "CC-BY-NC-ND-4.0":
        result = score(
            scoring,
            table=table([probe()]),
            no_impute=True,
            allow_restricted=True,
            sex=InferredSex.FEMALE,
            plink=fake,
            workspace=tmp_path / "work",
        )
        assert result.to_dict()["allow_restricted"] is True
    else:
        with pytest.raises(PgsError):
            score(
                scoring,
                table=table([probe()]),
                no_impute=True,
                allow_restricted=True,
                sex=InferredSex.FEMALE,
                plink=fake,
            )


@pytest.mark.parametrize(
    "mode", ["wrong_target", "wrong_sum", "wrong_count", "wrong_terms", "nonfinite"]
)
def test_malformed_native_reports_cannot_become_scores(
    tmp_path: Path, fake: MatrixPlink, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(MatrixPlink, "mode", mode)
    scoring = definition(tmp_path, [weight()])
    with pytest.raises(PgsError):
        score(
            scoring,
            table=table([probe()]),
            no_impute=True,
            sex=InferredSex.FEMALE,
            plink=fake,
            workspace=tmp_path / "work",
        )


def test_no_overlap_is_unavailable_and_observed_zero_is_a_real_sum(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(tmp_path, [weight()])
    for probes, expected in (([probe(102)], None), ([probe(copies=0)], 0)):
        result = score(
            scoring,
            table=table(probes),
            no_impute=True,
            sex=InferredSex.FEMALE,
            plink=fake,
            workspace=tmp_path / f"work{expected}",
        ).to_dict()
        assert result["before"]["sum"] == expected
        assert result["status"] == ("no_usable_observations" if expected is None else "computed")


def test_default_imputation_is_required_and_saved_direct_records_cannot_replace_missing_probes(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(tmp_path, [weight()])
    with pytest.raises(PgsError, match="Default scoring"):
        score(scoring, table=table([probe()]), sex=InferredSex.FEMALE, plink=fake)
    with pytest.raises(PgsError, match="Stage-direct"):
        score(
            scoring,
            table=table([probe(copies=None)]),
            dosages=[dosage(101, values=(1.0,), quality=None, source="direct")],
            sex=InferredSex.FEMALE,
            plink=fake,
        )


@pytest.mark.privacy
def test_private_output_defaults_atomic_publication_and_repr(
    tmp_path: Path, fake: MatrixPlink, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoring = definition(tmp_path, [weight()])
    result = score(
        scoring,
        table=table([probe()]),
        no_impute=True,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    )
    monkeypatch.setattr(engine, "cache_dir", lambda: tmp_path / "cache")
    path = write_result(result)
    assert path.is_relative_to(tmp_path / "cache")
    assert json.loads(path.read_text())["before"]["sum"] == 1
    with pytest.raises(PgsError, match="already exists"):
        write_result(result, path)
    with pytest.raises(PgsError, match="suffix"):
        write_result(result, tmp_path / "unsafe.json")
    assert "sum" not in repr(result) and "genotype" not in repr(result)
    assert not list(path.parent.glob("*.part"))
    for name in (
        "private.pgs-score.json",
        "private.pgs-score.json.x.part",
        "before.pgs-weights.tsv",
        "before.sscore.vars",
        "knowledge/private.pgs-score.json",
    ):
        check = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={repo_root().as_posix()}",
                "check-ignore",
                "--no-index",
                name,
            ],
            capture_output=True,
            check=False,
            cwd=repo_root(),
        )
        assert check.returncode == 0


def test_in_repo_matrix_workspace_requires_explicit_opt_in(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(tmp_path, [weight()])
    with pytest.raises(PgsError, match="outside the checkout"):
        score(
            scoring,
            table=table([probe()]),
            no_impute=True,
            sex=InferredSex.FEMALE,
            plink=fake,
            workspace=repo_root() / "tmp" / "never-created-pgs",
        )


def test_native_fixed_seed_arithmetic_and_fractional_quality(tmp_path: Path) -> None:
    installed = os.environ.get("GENETICS_PGS_TEST_TOOLS") or os.environ.get(
        "GENETICS_ROH_TEST_TOOLS"
    )
    if installed is None:
        pytest.skip("set GENETICS_PGS_TEST_TOOLS for pinned native PGS arithmetic")
    plink = Plink2.discover(tools_root=Path(installed))
    # Synthetic reference frequencies, fixed seed. Additional rows are deliberate
    # analytical boundary cases, not subsets of a consumer file.
    rng = random.Random(9202)
    reference_frequencies = (0.2, 0.5, 0.8)
    counts = [sum(rng.random() < af for _ in range(2)) for af in reference_frequencies]
    original = table(
        [probe(101 + i, copies=copies) for i, copies in enumerate(counts)]
        + [probe(10_000_000, chrom="X", copies=2, haploid=True), probe(105, copies=None)]
    )
    weights = [
        weight(101, value="2"),
        weight(102, value="-0.5"),
        weight(103, value="0.25"),
        weight(10_000_000, chrom="X", value="3"),
        weight(104, value="1.1"),
        weight(105, value="-0.2"),
        weight(106, value="0.4"),
        weight(107, effect="C", other="A", value="-2"),
        weight(100001, chrom="X", value="0.75"),
        weight(20_000_000, chrom="X", value="2"),
    ]
    scoring = definition(tmp_path, weights)
    records = [
        dosage(104, values=(0.019,), quality=(0.01,), genotype=(0, 0)),
        dosage(105, values=(2.0,), quality=None, genotype=(1, 1), source="imputed_no_call"),
        dosage(106, ref="A", alt=("C", "T"), values=(0.2, 0.3), quality=(0.1, 0.9)),
        dosage(107, ref="A", alt=("C", "T"), values=(0.35, 0.65), quality=(0.01, 0.99)),
        dosage(100001, chrom="X", values=(1.2,)),
        dosage(20_000_000, chrom="X", values=(0.25,), ploidy=1, genotype=(0,), quality=(0.1,)),
    ]
    data = score(
        scoring,
        table=original,
        dosages=records,
        sex=InferredSex.MALE,
        plink=plink,
        workspace=tmp_path / "work",
    ).to_dict()
    expected_before = 2 * counts[0] - 0.5 * counts[1] + 0.25 * counts[2] + 3
    expected_after = (
        expected_before + 0.019 * 1.1 - 2 * 0.2 + 1.5 * 0.4 - 0.35 * 2 + 1.2 * 0.75 + 0.25 * 2
    )
    assert data["before"]["sum"] == pytest.approx(
        expected_before, abs=data["before"]["verification_bound"]
    )
    assert data["after"]["sum"] == pytest.approx(
        expected_after, abs=data["after"]["verification_bound"]
    )
    assert data["after"]["native_alleles"] == 18 and data["after"]["plink_matrix_allele_ct"] == 20
    assert data["terms"][4]["after"]["value"] == 0.019
    assert data["terms"][5]["after"]["dr2"] is None
    assert data["terms"][6]["after"]["dr2"] is None
    assert data["method_version"] == 1 and data["plink_sha256"] is not None
    assert data["tool_manifest_sha256"] is not None


def test_cli_argument_errors_are_json_and_do_not_open_an_export() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["pgs", "score", "missing-public-score.txt", "--json"])
    assert result.exit_code == 1 and not json.loads(result.stdout)["ok"]


@pytest.mark.parametrize("effect,other,expected", [("AG", "A", 1.25), ("A", "AG", 0.75)])
def test_sequence_resolved_imputed_indels_are_exact_but_direct_indels_stay_excluded(
    tmp_path: Path,
    fake: MatrixPlink,
    effect: str,
    other: str,
    expected: float,
) -> None:
    scoring = definition(tmp_path, [weight(effect=effect, other=other)])
    record = dosage(101, ref="A", alt=("AG",))
    result = score(
        scoring,
        table=table([probe(102)]),
        dosages=[record],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["after"]["sum"] == expected
    assert result["terms"][0]["after"]["dr2"] == 0.8
    original = table([probe(effect="I", other="D")])
    direct = score(
        scoring,
        table=original,
        dosages=[record],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "direct",
    ).to_dict()
    assert direct["terms"][0]["before"]["status"] == "indel_excluded"
    assert direct["after"]["sum"] is None


def test_indel_sequences_are_not_complemented_or_reanchored(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(tmp_path, [weight(effect="AG", other="A")])
    result = score(
        scoring,
        table=None,
        dosages=[dosage(101, ref="T", alt=("CT",))],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["after"]["sum"] is None
    assert result["terms"][0]["after"]["status"] == "allele_mismatch"


def test_four_allele_reference_orientation_cannot_be_guessed(
    tmp_path: Path, fake: MatrixPlink
) -> None:
    scoring = definition(tmp_path, [weight()])
    record = dosage(
        101, ref="A", alt=("C", "G", "T"), values=(0.2, 0.3, 0.4), quality=(0.1, 0.2, 0.3)
    )
    result = score(
        scoring,
        table=None,
        dosages=[record],
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["after"]["sum"] is None
    assert result["terms"][0]["after"]["status"] == "strand_ambiguous"
    assert result["terms"][0]["after"]["native_record"]["dr2"] == (0.1, 0.2, 0.3)


def test_default_export_workflow_orders_ancestry_before_imputation_and_has_no_failure_fallback(
    tmp_path: Path,
    fake: MatrixPlink,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.imputation import ImputationResult
    from genetics.imputation.target import ImputationError
    from genetics.ingest import IngestResult, ingest
    from genetics.testing.fixtures import FIXTURES, render_fixture

    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "appdata"))
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    export = tmp_path / "synthetic.txt"
    export.write_text(render_fixture(spec), encoding="utf-8")
    original = ingest(export)
    scoring = definition(tmp_path, [weight()])
    events: list[str] = []

    def read(path: Path) -> IngestResult:
        events.append("ingest")
        return original

    def ancestry(*args: Any, **kwargs: Any) -> AncestryContext:
        events.append("ancestry")
        return AncestryContext.not_run("Synthetic control.")

    def imputation(table: GenotypeTable, **kwargs: Any) -> ImputationResult:
        events.append("imputation")
        return ImputationResult(table, tmp_path / "stage", (), {"records": 0}, False)

    monkeypatch.setattr(workflow, "ingest", read)
    monkeypatch.setattr(workflow, "infer_ancestry", ancestry)
    monkeypatch.setattr(workflow, "impute", imputation)
    monkeypatch.setattr(Plink2, "discover", lambda **kwargs: fake)
    result = workflow.score_export(scoring, export)
    assert events == ["ingest", "ancestry", "imputation"]
    assert result.to_dict()["imputation_mode"] == "enabled"
    events.clear()
    workflow.score_export(scoring, export, no_impute=True)
    assert events == ["ingest", "ancestry"]

    def failure(*args: Any, **kwargs: Any) -> ImputationResult:
        raise ImputationError("Synthetic prerequisite unavailable.")

    monkeypatch.setattr(workflow, "impute", failure)
    with pytest.raises(ImputationError):
        workflow.score_export(scoring, export)


def test_saved_full_bundle_cache_removal_cli_and_engine_equality(
    tmp_path: Path,
    fake: MatrixPlink,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from genetics.imputation import ImputationResult
    from genetics.run import pipeline
    from genetics.testing.fixtures import FIXTURES, render_fixture
    from genetics.testing.imputation_snapshots import anchors, synthetic_stage

    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(Plink2, "discover", lambda **kwargs: fake)
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    export = tmp_path / "synthetic.txt"
    export.write_text(render_fixture(spec), encoding="utf-8")
    streams: list[ImputationResult] = []

    def stage(original: GenotypeTable, **kwargs: Any) -> ImputationResult:
        generated = synthetic_stage(
            original, tmp_path / "synthetic-stage", records=(*anchors(), dosage(102))
        )
        streams.append(generated)
        return generated

    monkeypatch.setattr(pipeline, "impute", stage)
    pack = Path(__file__).parents[1] / "fixtures" / "cards"
    analysis = pipeline.analyse(export, knowledge_dir=pack)
    saved = pipeline.save(analysis, runs_root=tmp_path / "runs", run_id="m92-synthetic")
    scoring = definition(tmp_path, [weight(102)])
    assert streams[0].directory.resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(streams[0].directory)
    expected = workflow.score_saved(scoring, saved).to_dict()
    assert expected["before"]["status"] == "not_recorded"
    assert expected["after"]["sum"] == 1.25
    assert expected["imputation_provenance"]["status"] == "recorded"
    catalog = Catalog(
        {"PGS000001": scoring.metadata}, scoring.metadata_source, "pgs_all_metadata_scores.csv"
    )
    monkeypatch.setattr(Catalog, "default", lambda: catalog)
    output = tmp_path / "cli.pgs-score.json"
    cli = CliRunner().invoke(
        app,
        ["pgs", "score", str(scoring.path), "--run", str(saved), "--output", str(output), "--json"],
    )
    assert cli.exit_code == 0, cli.output
    actual = json.loads(cli.stdout)
    assert actual["after"] == expected["after"]
    assert json.loads(output.read_text()) == {
        key: value for key, value in actual.items() if key not in {"ok", "output"}
    }
    assert actual["terms"][0]["after"]["dr2"] == 0.8


@pytest.mark.parametrize("change", ["wrong_ploidy", "duplicate_panel", "bad_quality"])
def test_native_observation_errors_are_not_silently_scored(
    tmp_path: Path,
    fake: MatrixPlink,
    change: str,
) -> None:
    from dataclasses import replace

    scoring = definition(tmp_path, [weight()])
    record = dosage(101)
    if change == "bad_quality":
        records = [replace(record, dr2=(float("nan"),))]
        with pytest.raises(ValueError):
            score(
                scoring,
                table=None,
                dosages=records,
                sex=InferredSex.FEMALE,
                plink=fake,
                workspace=tmp_path / "work",
            )
        return
    records = (
        [
            replace(
                record,
                ploidy=1,
                genotype=(1,),
                storage_genotype=(1,),
                dosage=(0.5,),
                storage_dosage=(0.5,),
                quality_scope="beagle_haploid_dosage",
            )
        ]
        if change == "wrong_ploidy"
        else [record, record]
    )
    result = score(
        scoring,
        table=None,
        dosages=records,
        sex=InferredSex.FEMALE,
        plink=fake,
        workspace=tmp_path / "work",
    ).to_dict()
    assert result["after"]["sum"] is None
    assert result["terms"][0]["after"]["status"] in {"ploidy_conflict", "ambiguous_panel_records"}
