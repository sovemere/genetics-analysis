"""Synthetic HLA scientific-output, immutable evidence and interface acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
import random
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.external import hibag
from genetics.hla import calling, models, selection
from genetics.hla.models import HLAError
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.refs import postprocess


@pytest.fixture
def reference(tmp_path: Path) -> dict[str, Any]:
    _, source = models.source_identity("european")
    source["sha256"] = hashlib.sha256(b"synthetic classifier").hexdigest()
    source["size_bytes"] = len(b"synthetic classifier")
    loci = {}
    # Synthetic sites distinguish forward, reverse, ambiguous, incompatible and absent.
    pairs = [("A", "G"), ("C", "A"), ("A", "T"), ("A", "C"), ("G", "T")]
    variants = []
    for i, pair in enumerate(pairs):
        position = 30_000_001 + i
        forward = [a.translate(models.COMPLEMENT) for a in pair] if i == 1 else list(pair)
        variants.append(
            {
                "rsid": f"rs{1100001 + i}",
                "chrom": "6",
                "pos_grch37": position,
                "ref": forward[0],
                "alts": [forward[1]],
            }
        )
    for locus in models.LOCI:
        loci[locus] = {
            "assembly": "hg19",
            "training_samples": 100,
            "classifiers": 10,
            "marker_count": 5,
            "allele_count": 2,
            "markers": [
                {
                    "index": i + 1,
                    "rsid": f"rs{1100001 + i}",
                    "position": 30_000_001 + i,
                    "alleles": list(pair),
                }
                for i, pair in enumerate(pairs)
            ],
            "alleles": ["01:01", "02:01"],
        }
    return {
        "source": source,
        "loci": loci,
        "dbsnp": {
            "provenance": {
                "step": "extract_dbsnp_variant_index",
                "schema_version": postprocess._PROVENANCE_VERSION,
                "transform_version": 1,
                "rows": 5,
                "params": {},
                "input": {"filename": "synthetic.vcf.gz", "sha256": "b" * 64},
                "output": "dbsnp_variants.parquet",
                "output_sha256": "c" * 64,
            },
            "variants": variants,
        },
        "panel": {
            "provenance": {
                "source": models.PANEL,
                "version": "20130502",
                "filename": "ALL.chr6.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz",
                "sha256": "d" * 64,
            },
            "variants": [
                {"id": v["rsid"], **{k: v[k] for k in ("pos_grch37", "ref", "alts")}}
                for v in variants
            ],
        },
    }


def table(rows: list[tuple[int, str | None, str | None, str]]) -> GenotypeTable:
    return GenotypeTable(
        pl.DataFrame(
            [
                {
                    "rsid": f"rs{1100000 + position - 30000000}",
                    "chrom": "6",
                    "pos_grch37": position,
                    "a1": a1,
                    "a2": a2,
                    "genotype": None if a1 is None else "".join(sorted([a1, a2 or ""])),
                    "call_status": state,
                }
                for position, a1, a2, state in rows
            ],
            schema=NORMALIZED_SCHEMA,
        ),
        vendor="synthetic",
    )


def sample() -> GenotypeTable:
    rng = random.Random(112)
    # Draw from explicit synthetic reference frequencies with a fixed seed.
    bases = rng.choices(["A", "G"], weights=[0.5, 0.5], k=2)
    return table(
        [
            (30000001, bases[0], bases[1], "called"),
            (30000002, "G", "T", "called"),
            (30000003, "A", "T", "called"),
            (30000004, "I", "D", "called"),
        ]
    )


def write_metadata(directory: Path, reference: dict[str, Any]) -> None:
    meta = ["locus\tassembly\ttraining_samples\tclassifiers\tmarkers\thla_alleles"]
    markers = ["locus\tindex\trsid\tposition\talleles"]
    alleles = ["locus\tallele"]
    for locus in models.LOCI:
        m = reference["loci"][locus]
        meta.append(f"{locus}\thg19\t100\t10\t5\t2")
        for s in m["markers"]:
            markers.append(
                f"{locus}\t{s['index']}\t{s['rsid']}\t{s['position']}\t{'/'.join(s['alleles'])}"
            )
        alleles.extend(f"{locus}\t{a}" for a in m["alleles"])
    for name, lines in [("models.tsv", meta), ("markers.tsv", markers), ("alleles.tsv", alleles)]:
        (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def fake_prediction(
    reference: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Any:
    path = tmp_path / "synthetic.RData"
    path.write_bytes(b"synthetic classifier")
    runtime = hibag.HIBAGRuntime(Path("synthetic-Rscript"), "4.4.1", "synthetic-platform", "1.40.0")
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "private"))

    def execute(runtime: Any, script: str, args: list[str], **kwargs: Any) -> Path:
        output = tmp_path / "scientific-output"
        output.mkdir(exist_ok=True)
        write_metadata(output, reference)
        model, source, token = args
        payload = Path(source).read_bytes()
        rows = models.tsv(Path(source), ("locus", "index", "rsid", "position", "alleles", "dose"))
        lines = ["locus\tsample\tstate\tallele1\tallele2\tposterior"]
        for locus in models.LOCI:
            usable = any(r["dose"] != "NA" for r in rows if r["locus"] == locus)
            tail = "predicted\t02:01\t01:01\t0.01" if usable else "no-markers\tNA\tNA\tNA"
            lines.append(f"{locus}\t{token}\t{tail}")
        (output / "calls.hla-output.tsv").write_text("\n".join(lines) + "\n")
        (output / "identity.tsv").write_text(
            "sample\tinput_md5\tmodel_md5\n"
            + f"{token}\t{hashlib.md5(payload).hexdigest()}\t{hashlib.md5(Path(model).read_bytes()).hexdigest()}\n"
        )
        return output

    monkeypatch.setattr(models, "run_r", execute)
    return path, runtime, execute


def explicit(classifier: str = "european") -> dict[str, Any]:
    """An explicit classifier with no ancestry recorded: the match is unknown, not perfect."""
    return selection.select(None, requested=classifier)


@pytest.fixture
def record(reference: dict[str, Any], fake_prediction: Any) -> dict[str, Any]:
    path, runtime, _ = fake_prediction
    return calling.impute(sample(), path, reference, runtime, choice=explicit())


def test_dosage_order_forward_reverse_and_missing_states(reference: dict[str, Any]) -> None:
    observed = calling.collect(sample(), reference)
    rows = calling.matrices(reference, observed)["A"]
    assert [r["state"] for r in rows["markers"]] == [
        "observed",
        "observed",
        "unresolved-strand",
        "incompatible-alleles",
        "absent",
    ]
    # Independent orientation check: reverse C/A model maps to forward G/T.
    assert rows["markers"][1]["forward_first_allele"] == "G"
    assert rows["markers"][1]["strand_evidence"] == ["dbsnp", "panel"]
    assert rows["markers"][2]["strand_evidence"] == []
    assert rows["markers"][1]["dose"] == 1
    assert rows["observed_markers"] == 2 and rows["model_markers"] == 5
    for a1, a2, count in [("A", "A", 2), ("G", "A", 1), ("G", "G", 0)]:
        m = calling.matrices(
            reference, calling.collect(table([(30000001, a1, a2, "called")]), reference)
        )
        assert m["A"]["markers"][0]["dose"] == count


@pytest.mark.parametrize("state", ["no_call", "hemizygous", "het_haploid", "duplicate"])
def test_unsupported_observations_are_explicit(reference: dict[str, Any], state: str) -> None:
    rows: list[tuple[int, str | None, str | None, str]] = (
        [(30000001, None, None, state)]
        if state == "no_call"
        else [(30000001, "A", "A", "called" if state == "duplicate" else state)]
    )
    if state == "duplicate":
        rows *= 2
    marker = calling.matrices(reference, calling.collect(table(rows), reference))["A"]["markers"][0]
    assert marker["dose"] is None and marker["state"] != "observed"


def test_all_output_is_validated_and_low_posterior_is_retained(record: dict[str, Any]) -> None:
    calling.validate(record)
    assert len(record["genes"]) == 7
    assert all(g["posterior"] == 0.01 for g in record["genes"].values())
    # An explicit classifier with no recorded ancestry: unknown match, low posterior shown.
    assert record["selection"]["basis"] == "explicit"
    assert all(
        g["confidence"]["ceiling"] == "likely-artifact"
        and g["confidence"]["meets_published_call_threshold"] is False
        and g["confidence"]["ancestry_match"] is None
        for g in record["genes"].values()
    )
    assert record["parameters"]["observation_source"] == "original-array"
    assert calling.report(record) == record


def test_zero_markers_never_generates_an_hla_negative(
    reference: dict[str, Any], fake_prediction: Any
) -> None:
    path, runtime, _ = fake_prediction
    result = calling.impute(table([]), path, reference, runtime, choice=explicit())
    assert all(
        g["status"] == "no-markers" and g["alleles"] is None for g in result["genes"].values()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("posterior", True),
        ("posterior", -0.1),
        ("posterior", 1.1),
        ("posterior", float("nan")),
        ("posterior", float("inf")),
        ("posterior", "0.1"),
        ("alleles", ["99:99", "01:01"]),
        ("alleles", ["01:01"]),
        ("status", "negative"),
        ("observed_markers", True),
        ("model_markers", 0),
        ("coverage", {}),
    ],
)
def test_corrupt_frozen_predictions_fail(record: dict[str, Any], field: str, value: Any) -> None:
    record["genes"]["A"][field] = value
    with pytest.raises(HLAError):
        calling.validate(record)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-gene",
        "unknown-gene",
        "runtime",
        "reference-hash",
        "input-hash",
        "observation",
        "duplicate-observation",
        "schema-bool",
        "parameters-bool",
        "sample-token",
        "null-reference",
        "null-probe",
        "null-source",
        "unavailable-with-calls",
    ],
)
def test_corrupt_snapshot_structure_fails_safely(record: dict[str, Any], mutation: str) -> None:
    if mutation == "missing-gene":
        del record["genes"]["B"]
    elif mutation == "unknown-gene":
        record["genes"]["OTHER"] = record["genes"]["A"]
    elif mutation == "runtime":
        record["runtime"]["r_version"] = "private-path"
    elif mutation == "reference-hash":
        record["reference_sha256"] = "d" * 64
    elif mutation == "input-hash":
        record["execution"]["input_sha256"] = "d" * 64
    elif mutation == "observation":
        record["observations"][0]["probes"][0]["a1"] = "C"
    elif mutation == "duplicate-observation":
        record["observations"][1] = record["observations"][0]
    elif mutation == "schema-bool":
        record["schema_version"] = True
    elif mutation == "parameters-bool":
        record["parameters"]["cl"] = 0
    elif mutation == "sample-token":
        record["sample"] = "wrong-sample"
    elif mutation == "null-reference":
        record["reference"] = None
    elif mutation == "null-probe":
        record["observations"][0]["probes"] = [None]
    elif mutation == "null-source":
        record["reference"]["source"] = None
    else:
        record["status"] = "unavailable"
    with pytest.raises(HLAError):
        calling.validate(record)


@pytest.mark.parametrize(
    "mutation",
    [
        "build",
        "position",
        "alleles",
        "marker-order",
        "locus",
        "duplicate-marker",
        "allele-list",
        "training-count",
        "dbsnp",
        "source",
    ],
)
def test_corrupt_reference_fails(reference: dict[str, Any], mutation: str) -> None:
    m = reference["loci"]["A"]
    if mutation == "build":
        m["assembly"] = "hg38"
    elif mutation == "position":
        m["markers"][0]["position"] = True
    elif mutation == "alleles":
        m["markers"][0]["alleles"] = ["A", "A"]
    elif mutation == "marker-order":
        m["markers"].reverse()
    elif mutation == "locus":
        del reference["loci"]["B"]
    elif mutation == "duplicate-marker":
        m["markers"][1]["position"] = m["markers"][0]["position"]
    elif mutation == "allele-list":
        m["alleles"] = ["01:01", "01:01"]
    elif mutation == "training-count":
        m["training_samples"] = True
    elif mutation == "dbsnp":
        reference["dbsnp"]["variants"][0]["chrom"] = "7"
    else:
        reference["source"]["population"] = []
    with pytest.raises(HLAError):
        models.validate_reference(reference)


@pytest.mark.parametrize(
    "file,mutation",
    [
        ("calls.hla-output.tsv", "sample"),
        ("calls.hla-output.tsv", "locus"),
        ("calls.hla-output.tsv", "posterior"),
        ("identity.tsv", "identity"),
        ("markers.tsv", "metadata"),
        ("calls.hla-output.tsv", "missing"),
        ("calls.hla-output.tsv", "directory"),
    ],
)
def test_r_process_success_does_not_establish_scientific_success(
    reference: dict[str, Any],
    fake_prediction: Any,
    monkeypatch: pytest.MonkeyPatch,
    file: str,
    mutation: str,
) -> None:
    path, runtime, execute = fake_prediction

    def corrupt(*args: Any, **kwargs: Any) -> Path:
        output: Path = execute(*args, **kwargs)
        target = output / file
        text = target.read_text()
        if mutation == "sample":
            text = text.replace(text.splitlines()[1].split("\t")[1], "wrong-sample")
        elif mutation == "locus":
            text = "\n".join(text.splitlines()[:-1]) + "\n"
        elif mutation == "posterior":
            text = text.replace("0.01", "NaN")
        elif mutation == "identity":
            text = text.replace(text.splitlines()[1].split("\t")[1], "f" * 32)
        elif mutation == "metadata":
            text = text.replace("30000001", "30000999")
        else:
            target.unlink()
            if mutation == "directory":
                target.mkdir()
            return output
        target.write_text(text)
        return output

    monkeypatch.setattr(models, "run_r", corrupt)
    with pytest.raises(HLAError):
        calling.impute(sample(), path, reference, runtime, choice=explicit())


def test_runtime_absence_probe_error_and_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    states: list[hibag.ReadinessStatus] = ["r-missing", "hibag-missing"]
    for state in states:
        monkeypatch.setattr(
            hibag, "probe", lambda state=state, **_: hibag.Readiness(state, "synthetic")
        )
        stage = calling.HLAStage("european", True)
        stage.prepare()
        stage.select(None)
        result = stage.run(table([]))
        assert result == calling.unavailable(state, explicit())
    monkeypatch.setattr(hibag, "probe", lambda **_: hibag.Readiness("probe-error", "private"))
    with pytest.raises(HLAError, match="readiness"):
        calling.HLAStage("european", True).prepare()
    with pytest.raises(HLAError, match="opt-in"):
        calling.HLAStage("european").prepare()
    assert calling.HLAStage().run(table([]))["reason"] == "not-selected"
    event = threading.Event()
    event.set()
    with pytest.raises(hibag.HIBAGCancelledError):
        calling.HLAStage(cancel=event).prepare()


def test_source_pin_and_metadata_validation(
    reference: dict[str, Any], fake_prediction: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path, runtime, _ = fake_prediction
    monkeypatch.setattr(models, "source_identity", lambda _: (path, reference["source"]))

    def inspect(*args: Any, **kwargs: Any) -> Path:
        out = tmp_path / "inspection"
        out.mkdir(exist_ok=True)
        write_metadata(out, reference)
        return out

    monkeypatch.setattr(models, "run_r", inspect)
    monkeypatch.setattr(models, "_dbsnp", lambda *args: reference["dbsnp"])
    monkeypatch.setattr(models, "_panel", lambda *args: reference["panel"])
    _, prepared = models.prepare("european", runtime, opt_in=True)
    assert prepared == reference
    path.write_bytes(b"changed")
    with pytest.raises(HLAError, match="manifest pin"):
        models.prepare("european", runtime, opt_in=True)


def test_shared_pipeline_executes_hla_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.run.pipeline import analyse

    stages = []

    class Stage(calling.HLAStage):
        def prepare(self, progress: Any = None) -> None:
            stages.append("prepared")

        def select(self, ancestry: Any, progress: Any = None) -> None:
            stages.append("selected")
            assert ancestry["population"]["status"] == "not_run"
            super().select(ancestry, progress)

        def run(self, target: GenotypeTable) -> dict[str, Any]:
            assert target.vendor
            stages.append("called")
            return super().run(target)

    path = Path(__file__).parents[1] / "fixtures/synthetic/ancestry_v2_male.txt"
    result = analyse(
        path,
        no_impute=True,
        hla=Stage(opt_in=True),
        ancestry=lambda *_: AncestryContext.not_run("Synthetic acceptance"),
    )
    assert stages == ["prepared", "selected", "called"]
    # The real M5 context reaches selection: nothing placed, so no model is guessed.
    saved = result.hla
    assert saved is not None
    assert saved["reason"] == "no-classifier" and saved["genes"] == {}
    assert saved["selection"]["status"] == "not_run"
    assert saved["selection"]["classifier"] is None


def _rewrite(path: Path, name: str, payload: Any, *, version: int | None = None) -> None:
    header_path = path / "manifest.json"
    header = json.loads(header_path.read_text())
    raw = json.dumps(payload).encode()
    (path / name).write_bytes(raw)
    header["files"][name] = hashlib.sha256(raw).hexdigest()
    if version is not None:
        header["format_version"] = version
    header_path.write_text(json.dumps(header))


def legacy(record: dict[str, Any]) -> dict[str, Any]:
    """The schema-1 record M11.2 wrote for the same prediction."""
    old = copy.deepcopy(record)
    old["schema_version"] = calling.LEGACY_VERSION
    del old["selection"]
    for gene in old["genes"].values():
        del gene["confidence"]
    return old


def test_bundle_cli_dashboard_offline_and_historical(
    reference: dict[str, Any],
    fake_prediction: Any,
    sample_qc: Any,
    sample_pack: Any,
    sample_cards: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from genetics.ancestry.context import AncestryContext
    from genetics.run.bundle import HLA_NAME, BundleError, read_bundle, write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    context = AncestryContext.not_run("Synthetic acceptance")
    model, runtime, _ = fake_prediction
    choice = selection.select(context.to_dict(), requested="european")
    record = calling.impute(sample(), model, reference, runtime, choice=choice)
    root = tmp_path / "runs"
    common: dict[str, Any] = {
        "qc": sample_qc,
        "pack": sample_pack,
        "cards": sample_cards,
        "ancestry": context,
        "runs_root": root,
        "lock_path": tmp_path / "absent.lock",
        "tools_root": tmp_path / "tools",
    }
    with pytest.raises(BundleError, match="ancestry"):
        # Internally valid, but chosen from placements this run did not record.
        write_bundle(
            **common,
            hla=calling.impute(sample(), model, reference, runtime, choice=explicit()),
            run_id="hla-foreign-selection",
        )
    path = write_bundle(**common, hla=record, run_id="hla-synthetic")
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(hibag, "probe", lambda **_: pytest.fail("Saved reading must not probe R"))
    assert read_bundle(path).hla == record
    result = CliRunner().invoke(app, ["hla", "calls", path.name, "--json"])
    assert result.exit_code == 0 and json.loads(result.output) == record
    full = CliRunner().invoke(app, ["runs", "show", path.name, "--json"])
    assert full.exit_code == 0 and json.loads(full.output)["hla"] == record
    client = TestClient(create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1")
    page = client.get(f"/runs/{path.name}/hla")
    assert page.status_code == 200 and "0.01" in page.text and "2/5" in page.text
    assert "unresolved-strand" in page.text and "dbsnp, panel" in page.text
    assert "Classifier selection · not_run" in page.text and "explicitly requested" in page.text
    assert "ceiling likely-artifact" in page.text and "is below the method" in page.text
    text = CliRunner().invoke(app, ["hla", "calls", path.name])
    assert text.exit_code == 0 and "joint posterior 0.01" in text.output
    assert "Ancestry selection: not_run; classifier european (explicit)" in text.output
    assert "Observation ceiling: likely-artifact (lowered by posterior)" in text.output
    broken = copy.deepcopy(record)
    broken["genes"]["A"]["posterior"] = 2
    _rewrite(path, HLA_NAME, broken)
    with pytest.raises(BundleError, match="HLA"):
        read_bundle(path)
    assert "Saved HLA evidence" in client.get(f"/runs/{path.name}/hla").text
    foreign = calling.impute(sample(), model, reference, runtime, choice=explicit())
    _rewrite(path, HLA_NAME, foreign)
    with pytest.raises(BundleError, match="ancestry"):
        read_bundle(path)
    # Format 21 holds schema 1 only, and format 22 never accepts it.
    _rewrite(path, HLA_NAME, legacy(record))
    with pytest.raises(BundleError, match="HLA"):
        read_bundle(path)
    _rewrite(path, HLA_NAME, record, version=21)
    with pytest.raises(BundleError, match="HLA"):
        read_bundle(path)
    _rewrite(path, HLA_NAME, legacy(record), version=21)
    assert read_bundle(path).hla == legacy(record)
    old_page = client.get(f"/runs/{path.name}/hla").text
    assert "Explicit european classifier" in old_page and "not recorded by this schema" in old_page
    text = CliRunner().invoke(app, ["hla", "calls", path.name])
    assert text.exit_code == 0 and "not recorded (HLA schema 1)" in text.output
    header_path = path / "manifest.json"
    header = json.loads(header_path.read_text())
    header["format_version"] = 20
    header["files"].pop(HLA_NAME)
    (path / HLA_NAME).unlink()
    header_path.write_text(json.dumps(header))
    assert read_bundle(path).hla is None
    assert "not-recorded" in client.get(f"/runs/{path.name}/hla").text


def test_dashboard_and_cli_render_every_selection_outcome(
    reference: dict[str, Any],
    fake_prediction: Any,
    sample_qc: Any,
    sample_pack: Any,
    sample_cards: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Placed, declined, ambiguous and refused selections all render in both views."""
    from test_selection import ancestry

    from genetics.ancestry.context import AncestryContext
    from genetics.run.bundle import write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    context = AncestryContext.not_run("Synthetic acceptance")
    model, runtime, _ = fake_prediction
    choice = selection.select(context.to_dict(), requested="european")
    record = calling.impute(sample(), model, reference, runtime, choice=choice)
    root = tmp_path / "runs"
    path = write_bundle(
        qc=sample_qc,
        pack=sample_pack,
        cards=sample_cards,
        ancestry=context,
        hla=record,
        runs_root=root,
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
        run_id="hla-outcomes",
    )
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    client = TestClient(create_app(WebConfig(runs_root=root)), base_url="http://127.0.0.1")

    def completed(raw: dict[str, Any], requested: str | None) -> dict[str, Any]:
        # The saved run's own ancestry would refuse these; the views render what they get.
        chosen = selection.select(raw, requested=requested)
        shown = copy.deepcopy(record)
        shown["selection"] = chosen
        for gene in shown["genes"].values():
            gene["confidence"] = calling.confidence(gene, chosen["ancestry_match"])
        calling.validate(shown)
        return shown

    cases = [
        (
            completed(ancestry("GBR"), None),
            [
                "Classifier selection · selected",
                "selected from the ancestry placement",
                "Placement fit 1.000 against a decline threshold of 2.000",
                "GBR (1.000), CEU (1.500)",
                "candidate classifiers: european",
            ],
        ),
        (
            completed(ancestry("PUR", others=(("IBS", 1.9),)), "european"),
            [
                "Classifier selection · ambiguous",
                "automatic selection: ambiguous",
                "candidate classifiers: european, hispanic",
                "Ancestry match: unknown",
            ],
        ),
        (
            completed(ancestry(aadr="declined"), "european"),
            [
                "Classifier selection · declined",
                "automatic selection: declined",
                "Synthetic panel does not fit.",
                "Ancestry match: 0.0",
            ],
        ),
        (
            calling.unavailable("no-classifier", selection.select(ancestry("KHV", others=()))),
            [
                "no-classifier",
                "Classifier selection · unsupported",
                "South East Asian",
                "no published training set describes this category",
            ],
        ),
    ]
    for shown, expected in cases:
        monkeypatch.setattr(calling, "report", lambda _record, shown=shown: shown)
        page = client.get(f"/runs/{path.name}/hla")
        assert page.status_code == 200
        for text in expected:
            assert text in page.text, text
        cli = CliRunner().invoke(app, ["hla", "calls", path.name])
        assert cli.exit_code == 0
        assert f"Ancestry selection: {shown['selection']['status']}" in cli.output


def test_ancestry_selected_stage_prepares_only_the_chosen_model(
    reference: dict[str, Any], fake_prediction: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_selection import ancestry

    model, runtime, _ = fake_prediction
    prepared: list[str] = []
    monkeypatch.setattr(
        hibag,
        "probe",
        lambda **_: hibag.Readiness(
            "ready",
            "synthetic",
            path=runtime.path,
            r_version=runtime.r_version,
            r_platform=runtime.r_platform,
            hibag_version=runtime.hibag_version,
        ),
    )
    monkeypatch.setattr(models, "source_identity", lambda population: (model, reference["source"]))

    def prepare(population: str, *args: Any, **kwargs: Any) -> tuple[Path, dict[str, Any]]:
        prepared.append(population)
        return model, reference

    monkeypatch.setattr(models, "prepare", prepare)
    stage = calling.HLAStage(opt_in=True)
    stage.prepare()
    assert prepared == []  # nothing to verify until ancestry has chosen a model
    stage.select(ancestry("GBR"))
    assert prepared == ["european"]
    saved = stage.run(sample())
    calling.validate(saved)
    assert saved["selection"]["basis"] == "ancestry"
    assert saved["selection"]["ancestry_match"] == 1.0
    confidence = saved["genes"]["A"]["confidence"]
    assert confidence["status"] == "computed" and confidence["ancestry_match"] == 1.0
    assert confidence["marker_coverage"] == 2 / 5
    assert confidence["ceiling"] == "likely-artifact" and confidence["ceilings"] == ["posterior"]
    assert saved["genes"]["A"]["posterior"] == 0.01  # retained, never filtered

    declined = calling.HLAStage(opt_in=True)
    declined.prepare()
    declined.select(ancestry(aadr="declined"))
    assert prepared == ["european"]
    refused = declined.run(sample())
    assert refused == calling.unavailable("no-classifier", declined.selection)
    assert refused["selection"]["status"] == "declined" and refused["genes"] == {}


def test_runtime_absence_keeps_the_selection_and_never_a_negative_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_selection import ancestry

    monkeypatch.setattr(hibag, "probe", lambda **_: hibag.Readiness("r-missing", "Synthetic"))
    stage = calling.HLAStage(opt_in=True)
    stage.prepare()
    stage.select(ancestry("JPT", others=()))
    saved = stage.run(table([]))
    assert saved["reason"] == "r-missing" and saved["genes"] == {}
    assert saved["selection"]["classifier"] == "asian"
    calling.validate(saved)
    with pytest.raises(HLAError, match="disagree"):
        calling.unavailable("r-missing")
    with pytest.raises(HLAError, match="disagree"):
        calling.unavailable("no-classifier", saved["selection"])
    with pytest.raises(HLAError, match="ancestry placement"):
        unselected = calling.HLAStage(opt_in=True)
        unselected.prepare()
        unselected.run(table([]))
    event = threading.Event()
    cancelled = calling.HLAStage(opt_in=True, cancel=event)
    cancelled.prepare()
    event.set()
    with pytest.raises(hibag.HIBAGCancelledError):
        # Even a placement that needs no model must not proceed once cancelled.
        cancelled.select(ancestry(aadr="declined"))


def test_frozen_confidence_and_selection_cannot_be_rewritten(record: dict[str, Any]) -> None:
    mutations: tuple[Callable[[dict[str, Any]], Any], ...] = (
        lambda r: r["genes"]["A"]["confidence"].update(ceiling=None, ceilings=[]),
        lambda r: r["genes"]["A"]["confidence"].update(ancestry_match=1.0),
        lambda r: r["genes"]["A"].pop("confidence"),
        lambda r: r["selection"].update(ancestry_match=1.0),
        lambda r: r["selection"].update(classifier="asian", requested_classifier="asian"),
        lambda r: r.update(selection=None),
    )
    for mutate in mutations:
        broken = copy.deepcopy(record)
        mutate(broken)
        with pytest.raises(HLAError):
            calling.validate(broken)
    with pytest.raises(HLAError):
        calling.validate(record, schema_version=1)
    calling.validate(legacy(record), schema_version=1)
    with pytest.raises(HLAError):
        calling.validate(legacy(record), schema_version=2)


@pytest.mark.privacy
def test_hla_copy_paths_are_ignored_even_under_knowledge() -> None:
    import subprocess

    from genetics.paths import repo_root

    for name in [
        "copy.RData",
        "copy.rda",
        "copy.rds",
        "copy.hla-input.tsv",
        "copy.hla-output.tsv",
        "copy.hla.json",
        "hla.run.json",
    ]:
        for folder in ["", "knowledge/"]:
            result = subprocess.run(
                ["git", "check-ignore", folder + name], cwd=repo_root(), capture_output=True
            )
            assert result.returncode == 0


def test_model_terms_and_four_pins_are_explicit() -> None:
    from genetics.refs.fetcher import licence_refusal
    from genetics.refs.manifest import load

    for population in models.POPULATIONS:
        source = load().get("hibag_hlares_" + population + "_hg19")
        assert licence_refusal(source) is not None
        assert licence_refusal(source, [source.id]) is None
        assert source.license.review_status == "needs-review"
        assert source.files[0].sha256 and source.files[0].size_bytes


def test_cli_invalid_selection_is_categorical() -> None:
    from genetics.cli.run_cmd import _error_kind

    assert _error_kind(HLAError("safe")) == "hla"
    assert _error_kind(hibag.HIBAGError("safe")) == "hla"
    result = CliRunner().invoke(
        app, ["hla", "inspect", "--classifier", "unknown", "--model-opt-in", "--json"]
    )
    assert result.exit_code == 1 and json.loads(result.output)["error"]["kind"] == "hla"
    help_result = CliRunner().invoke(app, ["run", "--help"])
    assert "--hla-classifier" in help_result.output and "--hla-model-opt-in" in help_result.output
    path = Path(__file__).parents[1] / "fixtures/synthetic/ancestry_v2_male.txt"
    # A classifier still needs the model-terms opt-in; the opt-in alone now selects one.
    refused = CliRunner().invoke(
        app, ["run", "--input", str(path), "--hla-classifier", "european", "--json"]
    )
    assert refused.exit_code != 0 and json.loads(refused.output)["error"]["kind"] == "hla"


def test_unsupported_prediction_is_retained(record: dict[str, Any]) -> None:
    gene = record["genes"]["A"]
    gene.update(status="no-prediction", alleles=None, posterior=None)
    with pytest.raises(HLAError, match="confidence"):
        calling.validate(record)
    gene["confidence"] = calling.confidence(gene, record["selection"]["ancestry_match"])
    calling.validate(record)
    assert calling.report(record)["genes"]["A"]["status"] == "no-prediction"
    assert gene["confidence"]["status"] == "not_computed" and gene["confidence"]["ceiling"] is None


@pytest.mark.parametrize("extension", [".RData", ".hla-input.tsv"])
def test_symlink_or_nonregular_inputs_are_refused(tmp_path: Path, extension: str) -> None:
    path = tmp_path / ("not-a-file" + extension)
    path.mkdir()
    with pytest.raises(HLAError, match="regular file"):
        models.file_hash(path)


def test_duplicate_multiallelic_strand_evidence_is_unresolved(reference: dict[str, Any]) -> None:
    marker = reference["loci"]["A"]["markers"][0]
    evidence = reference["dbsnp"]["variants"]
    evidence.append(
        {
            "rsid": "rs1100999",
            "chrom": "6",
            "pos_grch37": marker["position"],
            "ref": "T",
            "alts": ["C"],
        }
    )
    del reference["panel"]["variants"][0]
    assert models.orientation(marker, reference) == (None, [])


def test_panel_resolves_tetra_allelic_dbsnp_sites(reference: dict[str, Any]) -> None:
    # dbSNP b157 lists every submitted allele, so most real MHC sites read A/C/G/T there.
    marker = reference["loci"]["A"]["markers"][0]
    reference["dbsnp"]["variants"][0]["alts"] = ["C", "G", "T"]
    assert models.orientation(marker, reference) == ("A", ["panel"])
    reference["panel"]["variants"][0]["alts"] = ["C", "G", "T"]
    assert models.orientation(marker, reference) == (None, [])
    del reference["panel"]["variants"][0]
    assert models.orientation(marker, reference) == (None, [])


def test_indel_and_structural_records_abstain_rather_than_contradict(
    reference: dict[str, Any],
) -> None:
    # 1000 Genomes can encode a site's SNV inside a longer complex record at the same POS.
    marker = reference["loci"]["A"]["markers"][0]
    reference["panel"]["variants"][0].update(ref="AACCACTTAA", alts=["GACCACTTAA", "A"])
    reference["dbsnp"]["variants"].append(
        {"rsid": "rs1100998", "chrom": "6", "pos_grch37": 30000001, "ref": "A", "alts": ["AT"]}
    )
    assert models.orientation(marker, reference) == ("A", ["dbsnp"])
    reference["panel"]["variants"][0].update(ref="A", alts=["<CN0>"])
    assert models.orientation(marker, reference) == ("A", ["dbsnp"])


@pytest.mark.parametrize("alleles", [("T", ["C"]), ("C", ["T"]), ("A", ["T"])])
def test_conflicting_or_mismatched_panel_evidence_is_unresolved(
    reference: dict[str, Any], alleles: tuple[str, list[str]]
) -> None:
    marker = reference["loci"]["A"]["markers"][0]
    reference["panel"]["variants"][0].update(ref=alleles[0], alts=alleles[1])
    assert models.orientation(marker, reference) == (None, [])
    rows = calling.matrices(reference, calling.collect(sample(), reference))
    assert rows["A"]["markers"][0]["state"] == "unresolved-strand"


def test_frozen_strand_evidence_cannot_be_rewritten(record: dict[str, Any]) -> None:
    record["reference"]["panel"]["variants"][0]["alts"] = ["C", "G", "T"]
    record["reference"]["dbsnp"]["variants"][0]["alts"] = ["C", "G", "T"]
    record["reference_sha256"] = models.digest(record["reference"])
    with pytest.raises(HLAError):
        calling.validate(record)


@pytest.mark.parametrize("mutation", ["provenance", "version", "filename", "row", "position"])
def test_corrupt_panel_evidence_fails(reference: dict[str, Any], mutation: str) -> None:
    panel = reference["panel"]
    if mutation == "provenance":
        panel["provenance"]["extra"] = True
    elif mutation == "version":
        panel["provenance"]["version"] = "20200101"
    elif mutation == "filename":
        panel["provenance"]["filename"] = "ALL.chr7.vcf.gz"
    elif mutation == "row":
        panel["variants"][0]["alts"] = []
    else:
        panel["variants"][0]["pos_grch37"] = 40_000_001
    with pytest.raises(HLAError):
        models.validate_reference(reference)


def write_panel(path: Path, rows: list[str]) -> str:
    import gzip

    header = ["##fileformat=VCFv4.1", "#CHROM POS ID REF ALT QUAL FILTER INFO FORMAT S1"]
    lines = [line.replace(" ", "\t") + "\n" for line in [*header, *rows]]
    payload = gzip.compress("".join(lines).encode())
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_panel_reader_verifies_lock_and_stops_after_model_region(
    reference: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from genetics.pgs import reference as pgs_reference

    path = tmp_path / reference["panel"]["provenance"]["filename"]
    rows = [
        "6 29999999 rs1 A G . PASS . GT 0|1",
        "6 30000001 rs1100001 A G . PASS . GT 0|1",
        "6 30000002 . G T,<CN0> . PASS . GT 0|0",
        "6 30000099 rs2 C T . PASS . GT 0|0",
        "6 3 malformed-row-after-the-model-region-is-never-parsed",
    ]
    digest = write_panel(path, rows)
    found = SimpleNamespace(version="20130502", vcfs={"6": (path, digest)})
    monkeypatch.setattr(pgs_reference, "discover_panel", lambda root: found)
    panel = models._panel(reference["loci"], tmp_path)
    assert panel["provenance"]["sha256"] == digest
    assert panel["variants"] == [
        {"id": "rs1100001", "pos_grch37": 30000001, "ref": "A", "alts": ["G"]},
        {"id": ".", "pos_grch37": 30000002, "ref": "G", "alts": ["T", "<CN0>"]},
    ]
    reference["panel"] = panel
    models.validate_reference(reference)
    found.vcfs = {"6": (path, "e" * 64)}
    with pytest.raises(HLAError, match="1000 Genomes"):
        models._panel(reference["loci"], tmp_path)
    write_panel(path, [rows[1], rows[0]])
    found.vcfs = {"6": (path, hashlib.sha256(path.read_bytes()).hexdigest())}
    with pytest.raises(HLAError, match="1000 Genomes"):
        models._panel(reference["loci"], tmp_path)
    monkeypatch.setattr(pgs_reference, "discover_panel", lambda root: "not fetched")
    with pytest.raises(HLAError, match="refs fetch"):
        models._panel(reference["loci"], tmp_path)
