"""M7.6 uses fabricated calls and references; no personal export is opened."""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.main import app
from genetics.engine.cards import KnowledgePack
from genetics.health.clinvar import ClinVarError, ClinVarIndex, ClinVarLookup, validate_lookup
from genetics.health.coverage import (
    NOTICE,
    assemble_coverage_card,
    measure_coverage,
    validate_coverage,
)
from genetics.health.frequencies import calibrate
from genetics.health.secondary import surface
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    CARDS_NAME,
    CLINVAR_NAME,
    MANIFEST_NAME,
    BundleError,
    read_bundle,
    write_bundle,
)
from genetics.web.app import create_app
from genetics.web.config import WebConfig

VERSION = "2026-01-01"
POS = 12345678


def sample(calls: Sequence[tuple[str, int, str | None, str]] | None = None) -> GenotypeTable:
    calls = [("7", POS, "AG", "called")] if calls is None else calls
    rows = [
        {
            "rsid": f"rs{900000001 + i}",
            "chrom": chrom,
            "pos_grch37": pos,
            "a1": None if gt is None else sorted(gt)[0],
            "a2": None if gt is None else sorted(gt)[1],
            "genotype": None if gt is None else "".join(sorted(gt)),
            "call_status": status,
        }
        for i, (chrom, pos, gt, status) in enumerate(calls)
    ]
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="synthetic")


def reference(tmp_path: Path, variants: Sequence[tuple[str, int, str, str]]) -> ClinVarIndex:
    path = tmp_path / "synthetic.vcf.gz"
    lines = [
        "##fileformat=VCFv4.1",
        f"##fileDate={VERSION}",
        "##reference=GRCh37",
        "\t".join(("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")),
    ]
    for i, (chrom, pos, ref, alt) in enumerate(variants):
        lines.append(
            "\t".join(
                (
                    chrom,
                    str(pos),
                    str(900000001 + i),
                    ref,
                    alt,
                    ".",
                    ".",
                    "CLNSIG=Conflicting_classifications_of_pathogenicity;CLNSIGCONF=Benign(1)|Pathogenic(1)",
                )
            )
        )
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return ClinVarIndex.build(path, version=VERSION)


def test_counts_deduplicate_positions_and_alleles_without_discarding_classifications(
    tmp_path: Path,
) -> None:
    index = reference(
        tmp_path,
        [
            ("7", POS, "A", "G"),
            ("7", POS, "A", "G"),
            ("7", POS, "A", "C"),
            ("7", POS + 1, "A", "G,T"),
            ("7", POS + 2, "A", "G"),
            ("NC_000001.10", POS, "A", "G"),
        ],
    )
    table = sample(
        [
            ("7", POS, "AA", "called"),
            ("7", POS, "AA", "called"),
            ("7", POS + 1, None, "no_call"),
            ("7", POS + 3, "AG", "called"),
        ]
    )
    digest_before = hashlib.sha256(index.path.read_bytes()).hexdigest()
    lookup = index.lookup(table, with_coverage=True)
    assert hashlib.sha256(index.path.read_bytes()).hexdigest() == digest_before
    raw = lookup.to_dict()
    validate_lookup(raw)
    coverage = raw["coverage"]
    assert coverage["reference_counts"] == {
        "records": 6,
        "primary_records": 5,
        "excluded_contig_records": 1,
        "positions": 3,
        "variants": 5,
        "matchable_snv_variants": 3,
    }
    assert coverage["chip_counts"] == {
        "markers": 4,
        "positions": 3,
        "duplicate_positions": 1,
        "extra_probes": 1,
        "called_positions": 2,
        "conflicting_probes": 0,
        "no_call": 1,
        "indel_excluded": 0,
        "ploidy_unresolved": 0,
        "called_snp": 2,
    }
    overlap = coverage["overlap_counts"]
    assert (overlap["positions"], overlap["called_positions"], overlap["variants"]) == (2, 1, 4)
    assert (overlap["allele_resolved_positions"], overlap["allele_resolved_variants"]) == (1, 1)
    assert overlap["alternate_observed_variants"] == 0 and overlap["reference_only_variants"] == 1
    assert coverage["ratios"]["reference_position_coverage"] == {
        "numerator": 2,
        "denominator": 3,
        "fraction": 2 / 3,
    }
    assert raw["counts"]["ambiguous"] == 2
    assert all("CLNSIGCONF" in e["info"] for locus in raw["loci"] for e in locus["records"])
    assert "genotype" not in repr(lookup)


def test_coverage_preserves_rare_call_reliability_and_acmg_state(tmp_path: Path) -> None:
    from genetics.health.frequencies import INDEX_VERSION, SOURCE, FrequencyIndex, parse_record

    index = reference(tmp_path, [("7", POS, "A", "G")])
    lookup = index.lookup(sample(), with_coverage=True)
    frequency_index = FrequencyIndex(
        tmp_path / "unused.sqlite",
        {
            "source": SOURCE,
            "version": "r2.1.1",
            "build": "GRCh37",
            "filename": "synthetic.vcf.bgz",
            "sha256": "1" * 64,
            "index_schema_version": INDEX_VERSION,
            "records": 1,
        },
    )
    frequency = parse_record(
        "\t".join(
            ("7", str(POS), ".", "A", "G", ".", "PASS", "AC=1;AN=200000;AF=0.000005;nhomalt=0")
        )
    )
    enriched = surface(
        calibrate(lookup, index=frequency_index, records={("7", POS): [frequency]}), None
    ).to_dict()
    validate_lookup(enriched)
    assert enriched["schema_version"] == 5 and enriched["lookup_schema_version"] == 4
    assert enriched["loci"][0]["records"][0]["reliability"]["tier"] == "likely-artifact"
    assert enriched["coverage"]["overlap_counts"]["alternate_observed_variants"] == 1
    assert enriched["secondary_reference"]["status"] == "not_run"


@pytest.mark.parametrize(
    "gt,status,state",
    [
        (None, "no_call", "no_call"),
        ("ID", "called", "indel_excluded"),
        ("AG", "het_haploid", "ploidy_unresolved"),
        ("CG", "called", "called_snp"),
    ],
)
def test_present_and_called_do_not_imply_allele_resolved(
    tmp_path: Path, gt: str | None, status: str, state: str
) -> None:
    index = reference(tmp_path, [("7", POS, "A", "G")])
    raw = index.lookup(sample([("7", POS, gt, status)]), with_coverage=True).to_dict()
    validate_lookup(raw)
    overlap = raw["coverage"]["overlap_counts"]
    assert overlap["positions"] == 1 and overlap[state] == 1
    assert overlap["called_positions"] == (0 if gt is None else 1)
    assert overlap["allele_resolved_variants"] == 0


def test_conflicting_probes_and_palindromic_strand_keep_annotations_visible(tmp_path: Path) -> None:
    index = reference(tmp_path, [("7", POS, "A", "G"), ("7", POS + 1, "A", "T")])
    raw = index.lookup(
        sample(
            [
                ("7", POS, "AG", "called"),
                ("7", POS, None, "no_call"),
                ("7", POS + 1, "AT", "called"),
            ]
        ),
        with_coverage=True,
    ).to_dict()
    validate_lookup(raw)
    overlap = raw["coverage"]["overlap_counts"]
    assert overlap["conflicting_probes"] == 1
    assert overlap["called_positions"] == 2
    assert overlap["strand_unresolved_records"] == 1
    assert overlap["allele_resolved_positions"] == 0
    assert raw["counts"]["alternate_observed"] == 1


def test_mt_alias_normalizes_but_vendor_par_and_unresolved_nonpar_are_not_guessed(
    tmp_path: Path,
) -> None:
    index = reference(
        tmp_path, [("M", 100, "A", "G"), ("X", POS, "A", "G"), ("X", 100000, "A", "G")]
    )
    raw = index.lookup(
        sample(
            [
                ("MT", 100, "AG", "called"),
                ("X", POS, "AG", "called"),
                ("X", 100000, "AG", "called"),
                ("PAR", 100000, "AG", "called"),
            ]
        ),
        with_coverage=True,
    ).to_dict()
    validate_lookup(raw)
    coverage = raw["coverage"]
    assert coverage["qc_inferred_sex"] == "ambiguous"
    assert coverage["chip_counts"]["positions"] == 4
    assert coverage["overlap_counts"]["positions"] == 3
    assert coverage["overlap_counts"]["ploidy_unresolved"] == 1
    assert coverage["overlap_counts"]["allele_resolved_positions"] == 2


@pytest.mark.parametrize("contigs_only", [False, True])
def test_zero_overlap_and_empty_primary_reference_are_distinct(
    tmp_path: Path, contigs_only: bool
) -> None:
    index = reference(tmp_path, [("NC_000001.10" if contigs_only else "7", POS + 1, "A", "G")])
    raw = index.lookup(sample(), with_coverage=True).to_dict()
    validate_lookup(raw)
    coverage = raw["coverage"]
    assert coverage["status"] == ("empty_reference" if contigs_only else "zero_overlap")
    assert coverage["overlap_counts"]["positions"] == 0
    assert coverage["ratios"]["reference_position_coverage"]["fraction"] == (
        None if contigs_only else 0.0
    )


def test_missing_source_reports_unknown_with_chip_counts() -> None:
    lookup = ClinVarLookup.not_run()
    raw = replace(lookup, coverage=measure_coverage(sample(), lookup, None)).to_dict()
    validate_lookup(raw)
    assert raw["coverage"]["status"] == "not_run"
    assert raw["coverage"]["reference_counts"] is None
    assert raw["coverage"]["overlap_counts"] is None
    assert raw["coverage"]["ratios"]["chip_position_annotation_share"]["fraction"] is None
    assert raw["coverage"]["chip_counts"]["positions"] == 1


@pytest.mark.parametrize(
    "bad", ["empty_input", "null_position", "bad_call", "empty_index", "bad_reference_count"]
)
def test_malformed_input_or_reference_fails_instead_of_a_negative_screen(
    tmp_path: Path, bad: str
) -> None:
    index = reference(tmp_path, [("7", POS, "A", "G")])
    table = sample([]) if bad == "empty_input" else sample()
    if bad == "null_position":
        table = GenotypeTable(
            table.frame.with_columns(pl.lit(None, dtype=pl.UInt32).alias("pos_grch37")),
            vendor="synthetic",
        )
    if bad == "bad_call":
        table = GenotypeTable(
            table.frame.with_columns(pl.lit("AA").alias("genotype")), vendor="synthetic"
        )
    lookup = index.lookup(sample())
    if bad == "empty_index":
        with sqlite3.connect(index.path) as db:
            db.execute("DELETE FROM variants")
    if bad == "bad_reference_count":
        index = replace(index, provenance={**index.provenance, "records": 2})
        lookup = replace(lookup, provenance=index.provenance)
    with pytest.raises(ClinVarError):
        measure_coverage(table, lookup, index)


@pytest.mark.parametrize(
    "bad",
    [
        "overlap",
        "ratio",
        "boolean",
        "nan",
        "source",
        "status",
        "policy",
        "variants",
        "states",
        "extra",
    ],
)
def test_saved_counts_and_denominators_are_validated_offline(tmp_path: Path, bad: str) -> None:
    raw = reference(tmp_path, [("7", POS, "A", "G")]).lookup(sample(), with_coverage=True).to_dict()
    coverage = raw["coverage"]
    if bad == "overlap":
        coverage["overlap_counts"]["allele_resolved_positions"] += 1
    elif bad == "ratio":
        coverage["ratios"]["reference_position_coverage"]["denominator"] += 1
    elif bad == "boolean":
        coverage["ratios"]["reference_position_coverage"]["numerator"] = True
    elif bad == "nan":
        coverage["ratios"]["reference_position_coverage"]["fraction"] = float("nan")
    elif bad == "source":
        coverage["provenance"]["sha256"] = "0" * 64
    elif bad == "status":
        coverage["status"] = "zero_overlap"
    elif bad == "policy":
        coverage["policy"]["reference_filters"] = "pathogenic only"
    elif bad == "variants":
        coverage["reference_counts"]["variants"] = 0
    elif bad == "states":
        coverage["chip_counts"]["no_call"] = 1
    else:
        coverage["extra"] = 1
    with pytest.raises(ClinVarError):
        validate_lookup(raw)


def _redigest(path: Path, name: str, data: Any) -> None:
    payload = path / name
    payload.write_text(json.dumps(data), encoding="utf-8")
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("missing", [False, True])
def test_saved_card_cli_and_dashboard_agree_and_never_recount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample_qc: QCReport, missing: bool
) -> None:
    pack = KnowledgePack.load()
    definition = next(c for c in pack.cards if c.computation == "clinvar_coverage")
    index = reference(tmp_path, [("7", POS, "A", "G"), ("7", POS + 1, "A", "G")])
    lookup = ClinVarLookup.not_run() if missing else index.lookup(sample(), with_coverage=True)
    if missing:
        lookup = replace(lookup, coverage=measure_coverage(sample(), lookup, None))
    lookup = surface(calibrate(lookup, index=None, records={}), None)
    card = assemble_coverage_card(definition, lookup.coverage)
    data = tmp_path / "private"
    monkeypatch.setenv("GENETICS_DATA_DIR", str(data))
    with pytest.raises(BundleError, match="supplied lookup"):
        write_bundle(
            qc=sample_qc,
            cards=(card,),
            pack=pack,
            clinvar=ClinVarLookup.not_run(),
            ancestry=AncestryContext.not_run("synthetic"),
            runs_root=data / "runs",
            run_id="rejected-coverage",
            lock_path=tmp_path / "absent.lock",
            tools_root=tmp_path / "tools",
        )
    assert not (data / "runs" / "rejected-coverage").exists()
    path = write_bundle(
        qc=sample_qc,
        cards=(card,),
        pack=pack,
        clinvar=lookup,
        ancestry=AncestryContext.not_run("synthetic"),
        runs_root=data / "runs",
        run_id="coverage-test",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    snapshot = lookup.to_dict()
    index.path.unlink()  # All readers must work with the source removed.
    saved = read_bundle(path)
    assert saved.format_version == 14 and saved.clinvar == snapshot
    assert saved.cards[0].computation is not None
    assert saved.cards[0].computation["result"] == snapshot["coverage"]
    cli = CliRunner().invoke(app, ["runs", "clinvar", path.name, "--json"])
    assert cli.exit_code == 0 and json.loads(cli.stdout)["clinvar"] == snapshot
    human = CliRunner().invoke(app, ["runs", "clinvar", path.name])
    assert human.exit_code == 0
    assert NOTICE in human.stdout
    assert ("coverage is unknown" if missing else "1/2 (50.00%)") in human.stdout
    with TestClient(
        create_app(WebConfig(runs_root=data / "runs")), base_url="http://127.0.0.1:8765"
    ) as client:
        page = client.get(f"/runs/{path.name}/clinvar")
        assert page.status_code == 200
        assert NOTICE in page.text
        assert ("coverage fractions are unknown" if missing else "50.00%") in page.text
        detail = client.get(f"/runs/{path.name}/cards/{definition.id}")
        assert detail.status_code == 200 and "Position states" in detail.text
        assert "Coverage and its limits" in detail.text
        if not missing:
            cards = json.loads((path / CARDS_NAME).read_text(encoding="utf-8"))
            cards["cards"][0]["computation"]["result"]["provenance"]["sha256"] = "0" * 64
            _redigest(path, CARDS_NAME, cards)
            with pytest.raises(BundleError, match="disagrees"):
                read_bundle(path)
            page = client.get(f"/runs/{path.name}/clinvar")
            assert page.status_code == 200 and "disagrees" in page.text


def test_historical_lookup_retains_original_meaning(
    tmp_path: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    lookup = surface(
        calibrate(
            reference(tmp_path, [("7", POS, "A", "G")]).lookup(sample()), index=None, records={}
        ),
        None,
    )
    path = write_bundle(
        qc=sample_qc,
        cards=(),
        pack=sample_pack,
        clinvar=lookup,
        ancestry=AncestryContext.not_run("synthetic"),
        runs_root=tmp_path / "runs",
        run_id="historical-coverage",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 12
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    saved = read_bundle(path)
    assert saved.clinvar == lookup.to_dict()
    assert saved.clinvar is not None and "coverage" not in saved.clinvar


def test_schema_five_cannot_be_labelled_an_older_bundle(
    tmp_path: Path, sample_qc: QCReport, sample_pack: KnowledgePack
) -> None:
    lookup = reference(tmp_path, [("7", POS, "A", "G")]).lookup(sample(), with_coverage=True)
    validate_coverage(lookup.to_dict()["coverage"])
    path = write_bundle(
        qc=sample_qc,
        cards=(),
        pack=sample_pack,
        clinvar=lookup,
        ancestry=AncestryContext.not_run("synthetic"),
        runs_root=tmp_path / "runs",
        run_id="version-coverage",
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    manifest_path = path / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format_version"] = 12
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="format 13"):
        read_bundle(path)
    manifest["format_version"] = 13
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    bad = lookup.to_dict()
    bad["coverage"]["chip_counts"]["called_positions"] = 0
    _redigest(path, CLINVAR_NAME, bad)
    with pytest.raises(BundleError, match="coverage"):
        read_bundle(path)
