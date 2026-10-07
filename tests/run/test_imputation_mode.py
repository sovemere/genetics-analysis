"""M8.4 default-on execution and immutable mode snapshots; generated inputs only."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import infer_ancestry
from genetics.cli.main import app
from genetics.engine.confidence import CallSource
from genetics.external.beagle import Beagle, BeagleError, BeagleOptions
from genetics.health.clinvar import lookup_default
from genetics.imputation import ImputationError, ImputationResult, impute
from genetics.imputation.context import ImputationContext
from genetics.imputation.dosages import DosageRecord
from genetics.ingest.schema import GenotypeTable
from genetics.privacy import assert_no_genotype
from genetics.qc.report import InferredSex
from genetics.refs.imputation import BrefTools
from genetics.refs.postprocess import ProcessError
from genetics.run import pipeline
from genetics.run.bundle import BundleError, read_bundle
from genetics.testing.fixtures import FIXTURES, _ancestry_header, render_fixture
from genetics.testing.imputation_inputs import native_reference
from genetics.testing.imputation_snapshots import anchors, synthetic_stage
from genetics.web import create_app
from genetics.web.config import WebConfig

PACK = Path(__file__).parents[1] / "fixtures/cards"


def summary(*, empty: bool = False) -> dict[str, Any]:
    return {
        "status": "no_eligible_jobs" if empty else "computed",
        "jobs": 0 if empty else 1,
        "records": 0 if empty else 4,
        "resumed": False,
        "ploidy_conflicts": 0,
        "sources": {} if empty else {"direct": 2, "imputed_no_call": 1, "imputed_untyped": 1},
        "regions": [
            {
                "region": "chr1",
                "ploidy": 2,
                "positions": 3,
                "written": 3,
                "called": 1 if empty else 2,
                "outcomes": {"as_written": 1, "no_call": 2}
                if empty
                else {"as_written": 2, "no_call": 1},
                "status": "insufficient_typed_calls" if empty else "computed",
            }
        ],
        "unsupported_positions": {"MT": 1},
    }


@pytest.fixture
def export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    path = tmp_path / "synthetic.txt"
    path.write_text(
        render_fixture(replace(spec, spike_ins={"rs900000001": (7, 12345678, "A", "G")})),
        encoding="utf-8",
    )
    return path


def fake_result(table: GenotypeTable, root: Path, *, empty: bool = False) -> ImputationResult:
    directory = root / "synthetic.imputation-work/complete"
    records = (
        ()
        if empty
        else (
            *anchors(),
            DosageRecord(
                "1",
                30,
                "A",
                ("G",),
                (0, 1),
                (0, 1),
                (1.0,),
                (1.0,),
                None,
                2,
                "imputed_no_call",
                "resolved",
                "no_call",
                "phased_hardcall_only",
                "not_estimated",
            ),
            DosageRecord(
                "1",
                40,
                "A",
                ("G",),
                (0, 1),
                (0, 1),
                (1.1,),
                (1.1,),
                (0.8,),
                2,
                "imputed_untyped",
                "resolved",
                None,
                "beagle_DS",
                "beagle_diploid_dosage",
            ),
        )
    )
    return synthetic_stage(
        table,
        directory,
        records=records,
        empty_report=summary(empty=True)["regions"][0] if empty else None,
    )


def install_fake(
    monkeypatch: pytest.MonkeyPatch, root: Path, *, empty: bool = False
) -> list[GenotypeTable]:
    calls: list[GenotypeTable] = []

    def stage(
        table: GenotypeTable, *, sex: InferredSex, progress: Callable[[str], None] | None
    ) -> ImputationResult:
        calls.append(table)
        if progress:
            progress("Imputation stage complete")
        return fake_result(table, root, empty=empty)

    monkeypatch.setattr(pipeline, "impute", stage)
    monkeypatch.setattr(ImputationResult, "iter_dosages", lambda self: iter(()))
    return calls


def test_default_stage_runs_after_ancestry_and_keeps_original_observations(
    export: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = install_fake(monkeypatch, tmp_path)
    real_ancestry = infer_ancestry

    def ancestry(table: GenotypeTable, qc: Any, **kwargs: Any) -> Any:
        assert not calls
        return real_ancestry(table, qc, **kwargs)

    monkeypatch.setattr(pipeline, "infer_ancestry", ancestry)
    observed: list[GenotypeTable] = []
    real_lookup = lookup_default

    def lookup(table: GenotypeTable, **kwargs: Any) -> Any:
        assert calls == [table]
        observed.append(table)
        return real_lookup(table, **kwargs)

    monkeypatch.setattr(pipeline, "lookup_default", lookup)
    analysis = pipeline.analyse(export, knowledge_dir=PACK)
    assert analysis.imputation.mode == "enabled" and analysis.imputation.status == "computed"
    assert (
        analysis.imputation_result is not None and analysis.imputation_result.original is calls[0]
    )
    assert observed == calls
    assert all(c.imputation_mode == "enabled" for c in analysis.cards)
    assert all(
        c.observation.call_source is CallSource.DIRECT for c in analysis.cards if c.observation
    )
    assert any(c.has_interpretation for c in analysis.cards)


@pytest.mark.parametrize("empty", [False, True])
def test_recorded_enabled_mode_and_execution_survive_without_cache(
    export: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty: bool
) -> None:
    install_fake(monkeypatch, tmp_path, empty=empty)
    analysis = pipeline.analyse(export, knowledge_dir=PACK)
    path = pipeline.save(analysis)
    bundle = read_bundle(path)
    assert bundle.format_version == 16 and bundle.imputation == analysis.imputation.to_dict()
    assert bundle.imputation["status"] == ("no_eligible_jobs" if empty else "computed")
    assert all(c.imputation_mode == "enabled" for c in bundle.cards)
    assert analysis.imputation_result is not None
    import shutil

    shutil.rmtree(analysis.imputation_result.directory)
    assert read_bundle(path).imputation == bundle.imputation


@pytest.mark.privacy
@pytest.mark.parametrize("json_output", [False, True])
@pytest.mark.parametrize("disable", [False, True])
def test_cli_mode_and_saved_dashboard_match_without_outputting_calls(
    export: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, json_output: bool, disable: bool
) -> None:
    calls = install_fake(monkeypatch, tmp_path)
    args = ["run", "--input", str(export), "--knowledge", str(PACK)]
    if disable:
        args.append("--no-impute")
    if json_output:
        args.append("--json")
    invocation = CliRunner().invoke(app, args)
    assert invocation.exit_code == 0, invocation.output
    assert_no_genotype(invocation.output)
    assert len(calls) == (0 if disable else 1)
    (path,) = (tmp_path / "data/runs").iterdir()
    bundle = read_bundle(path)
    mode = "disabled" if disable else "enabled"
    assert bundle.imputation is not None
    assert bundle.imputation["mode"] == mode
    if json_output:
        assert json.loads(invocation.stdout)["imputation"] == bundle.imputation
    else:
        assert f"imputation  {mode}" in invocation.stdout
    shown = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    payload = json.loads(shown.stdout)
    assert payload["imputation"] == bundle.imputation
    assert all(c["imputation_mode"] == mode for c in payload["cards"])
    with TestClient(create_app(WebConfig()), base_url="http://127.0.0.1") as client:
        body = client.get(f"/runs/{path.name}").text
        assert f"Imputation {mode}" in body
        assert "Card findings use" in body
        card = bundle.cards[0]
        detail = client.get(f"/runs/{path.name}/cards/{card.card_id}").text
        assert f"Imputation {mode} for this run" in detail


def test_explicit_opt_out_never_resolves_or_runs_imputation(
    export: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pipeline, "impute", lambda *a, **kw: pytest.fail("Opt-out attempted imputation")
    )
    events: list[str] = []
    analysis = pipeline.analyse(export, knowledge_dir=PACK, no_impute=True, progress=events.append)
    assert analysis.imputation.to_dict()["summary"] is None and analysis.imputation_result is None
    assert "Imputation disabled by explicit --no-impute request" in events
    assert all(c.imputation_mode == "disabled" for c in analysis.cards)


@pytest.mark.parametrize(
    "error",
    [
        ImputationError("Prepared panels/maps unavailable"),
        BeagleError("Pinned tool unavailable"),
        ProcessError("Reference source unavailable"),
    ],
)
@pytest.mark.parametrize("json_output", [False, True])
def test_default_failure_is_reported_without_silent_fallback_or_bundle(
    export: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    json_output: bool,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> ImputationResult:
        raise error

    monkeypatch.setattr(pipeline, "impute", fail)
    invocation = CliRunner().invoke(
        app,
        [
            "run",
            "--input",
            str(export),
            "--knowledge",
            str(PACK),
            *(["--json"] if json_output else []),
        ],
    )
    assert invocation.exit_code == 2
    assert_no_genotype(invocation.output)
    assert not (tmp_path / "data/runs").exists()
    if json_output:
        assert json.loads(invocation.stdout)["error"]["kind"] == "imputation"


@pytest.mark.parametrize(
    "damage",
    [
        "card_mode",
        "missing_card_mode",
        "bad_multimarker",
        "missing_payload",
        "status",
        "boolean_count",
        "source_counts",
        "region_counts",
        "region_status",
        "region_ploidy",
        "extra_summary",
        "mode",
        "card_input",
    ],
)
def test_corrupt_saved_modes_and_execution_arithmetic_are_refused(
    export: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    install_fake(monkeypatch, tmp_path)
    path = pipeline.save(pipeline.analyse(export, knowledge_dir=PACK))
    filename = (
        "cards.run.json"
        if "card_mode" in damage or damage == "bad_multimarker"
        else "imputation.run.json"
    )
    data_path = path / filename
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if damage == "missing_payload":
        del manifest["files"][filename]
        data_path.unlink()
    else:
        data = json.loads(data_path.read_text())
        if damage == "card_mode":
            data["cards"][0]["imputation_mode"] = "disabled"
        elif damage == "missing_card_mode":
            del data["cards"][0]["imputation_mode"]
        elif damage == "bad_multimarker":
            data["cards"][0]["multi_marker"] = {"markers": 9}
        elif damage == "status":
            data["status"] = "disabled"
        elif damage == "boolean_count":
            data["summary"]["records"] = True
        elif damage == "source_counts":
            data["summary"]["sources"]["direct"] = 3
        elif damage == "region_counts":
            data["summary"]["regions"][0]["positions"] = 4
        elif damage == "region_status":
            data["summary"]["regions"][0]["status"] = "insufficient_typed_calls"
        elif damage == "region_ploidy":
            data["summary"]["regions"][0]["ploidy"] = None
        elif damage == "extra_summary":
            data["summary"]["raw_calls"] = []
        elif damage == "mode":
            data["mode"] = "disabled"
        else:
            data["card_input"] = "imputed"
        text = json.dumps(data)
        data_path.write_text(text)
        manifest["files"][filename] = hashlib.sha256(text.encode()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BundleError):
        read_bundle(path)


@pytest.mark.parametrize("version", range(1, 14))
def test_historical_formats_do_not_infer_disabled_or_enabled_mode(
    export: Path, version: int
) -> None:
    path = pipeline.save(pipeline.analyse(export, knowledge_dir=PACK, no_impute=True))
    cards_path = path / "cards.run.json"
    cards = json.loads(cards_path.read_text())
    for card in cards["cards"]:
        del card["imputation_mode"]
    text = json.dumps(cards)
    cards_path.write_text(text)
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["format_version"] = version
    manifest["files"].pop("imputation.provenance.run.json")
    (path / "imputation.provenance.run.json").unlink()
    if 7 <= version < 13:
        from genetics.health.clinvar import ClinVarLookup

        clinvar_path = path / "clinvar.run.json"
        lookup = ClinVarLookup.not_run("Synthetic historical snapshot").to_dict()
        lookup["schema_version"] = 1
        for key in (
            "coverage",
            "secondary",
            "secondary_provenance",
            "secondary_reason",
            "secondary_status",
        ):
            lookup.pop(key, None)
        text_lookup = json.dumps(lookup)
        clinvar_path.write_text(text_lookup)
        manifest["files"]["clinvar.run.json"] = hashlib.sha256(text_lookup.encode()).hexdigest()
    manifest["files"]["cards.run.json"] = hashlib.sha256(text.encode()).hexdigest()
    del manifest["files"]["imputation.run.json"]
    (path / "imputation.run.json").unlink()
    manifest_path.write_text(json.dumps(manifest))
    bundle = read_bundle(path)
    assert bundle.imputation is None and all(c.imputation_mode is None for c in bundle.cards)
    invocation = CliRunner().invoke(app, ["runs", "show", path.name])
    assert invocation.exit_code == 0 and "imputation  not recorded" in invocation.stdout


def test_writer_refuses_card_run_mode_disagreement(export: Path) -> None:
    analysis = pipeline.analyse(export, knowledge_dir=PACK, no_impute=True)
    corrupted = replace(
        analysis, cards=(replace(analysis.cards[0], imputation_mode="enabled"), *analysis.cards[1:])
    )
    with pytest.raises(BundleError, match="mode disagrees"):
        pipeline.save(corrupted)


def test_context_snapshots_do_not_alias_mutable_execution_metadata() -> None:
    original = summary()
    context = ImputationContext.enabled(original)
    original["regions"][0]["called"] = 999
    first = context.to_dict()
    first["summary"]["regions"][0]["called"] = 888
    assert context.to_dict()["summary"]["regions"][0]["called"] == 2
    assert_no_genotype(repr(context))


def test_default_without_prepared_references_fails_instead_of_disabling_imputation(
    export: Path, tmp_path: Path
) -> None:
    invocation = CliRunner().invoke(
        app, ["run", "--input", str(export), "--knowledge", str(PACK), "--json"]
    )
    assert invocation.exit_code == 2
    assert json.loads(invocation.stdout)["error"]["kind"] == "imputation"
    assert not (tmp_path / "data/runs").exists()


@pytest.mark.parametrize("flag", [1, None, "yes"])
def test_opt_out_requires_a_boolean_not_truthiness(export: Path, flag: Any) -> None:
    with pytest.raises(ImputationError, match="explicit boolean"):
        pipeline.analyse(export, knowledge_dir=PACK, no_impute=flag)


def test_array_only_writer_does_not_publish_an_imputed_card(export: Path) -> None:
    from genetics.engine.evidence import ObservationEvidence

    analysis = pipeline.analyse(export, knowledge_dir=PACK, no_impute=True)
    cards = tuple(
        replace(c, observation=ObservationEvidence(CallSource.IMPUTED, imputation_quality=0.5))
        if c.observation
        else c
        for c in analysis.cards
    )
    with pytest.raises(BundleError, match="imputed observation"):
        pipeline.save(replace(analysis, cards=cards))


def test_native_default_cli_runs_and_saves_mode_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = os.environ.get("GENETICS_BEAGLE_TEST_TOOLS")
    if installed is None:
        pytest.skip("set GENETICS_BEAGLE_TEST_TOOLS for native default-run acceptance")
    beagle, bref = Beagle.discover(tools_root=Path(installed)), BrefTools.discover(Path(installed))
    monkeypatch.setattr(BrefTools, "discover", lambda: bref)
    reference, male, _ = native_reference(tmp_path / "refs", bref)
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    lines = [*_ancestry_header("37"), "rsid\tchromosome\tposition\tallele1\tallele2"]
    for i, (chrom, pos, genotype) in enumerate(
        male.frame.select("chrom", "pos_grch37", "genotype").iter_rows()
    ):
        code = "23" if chrom == "X" else chrom
        genotype = genotype or "00"
        lines.append(f"rs{940000001 + i}\t{code}\t{pos}\t{genotype[0]}\t{genotype[1]}")
    # Two extra unmatched X observations and Y calls make QC sex resolvable on this tiny
    # synthetic panel. Calls come from the same invented fixed-frequency generator.
    import random

    rng = random.Random(8404)
    for i in range(102):
        allele = "A" if rng.random() < 0.6 else "G"
        code, pos = ("23", 4000000 + i) if i < 2 else ("24", 1000000 + i)
        lines.append(f"rs{940010001 + i}\t{code}\t{pos}\t{allele}\t{allele}")
    export = tmp_path / "native-synthetic.txt"
    export.write_text("\n".join(lines) + "\n")

    def native(
        table: GenotypeTable, *, sex: InferredSex, progress: Callable[[str], None] | None
    ) -> ImputationResult:
        assert sex is InferredSex.MALE
        return impute(
            table,
            sex=sex,
            progress=progress,
            reference=reference,
            beagle=beagle,
            bref=bref,
            options=BeagleOptions(memory_mb=512, nthreads=2),
        )

    monkeypatch.setattr(pipeline, "impute", native)
    args = ["run", "--input", str(export), "--knowledge", str(PACK), "--json"]
    invocation = CliRunner().invoke(app, args)
    assert invocation.exit_code == 0, invocation.output
    assert_no_genotype(invocation.output)
    payload = json.loads(invocation.stdout)
    record = payload["imputation"]
    assert record["mode"] == "enabled" and record["summary"]["jobs"] == 4
    assert record["summary"]["records"] == 800
    bundle = read_bundle(Path(payload["path"]))
    assert bundle.imputation == record and all(c.imputation_mode == "enabled" for c in bundle.cards)
    dosages = list(bundle.iter_dosages())
    assert len(dosages) == 800
    assert sum(r.source == "direct" for r in dosages) == 396
    assert sum(r.source == "imputed_no_call" for r in dosages) == 4
    assert sum(r.source == "imputed_untyped" for r in dosages) == 400
    assert any(len(r.alt) > 1 for r in dosages)
    assert any(r.ploidy == 1 and r.quality_scope == "beagle_haploid_dosage" for r in dosages)
    second = CliRunner().invoke(app, args)
    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["imputation"]["summary"]["resumed"] is True
