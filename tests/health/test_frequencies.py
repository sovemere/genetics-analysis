"""Frequency/reference fixtures are invented; no personal exports are read."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from genetics.health.clinvar import ClinVarIndex, validate_lookup
from genetics.health.frequencies import (
    FrequencyError,
    FrequencyIndex,
    calibrate,
    parse_record,
    reliability,
    select_frequencies,
)
from genetics.refs import postprocess
from genetics.refs.manifest import Source

POS = 12345678


def row(
    *,
    info: str = "AC=1;AN=200000;AF=0.000005;nhomalt=0",
    alt: str = "G",
    ref: str = "A",
    filters: str = "PASS",
    pos: int = POS,
) -> str:
    return "\t".join(("7", str(pos), ".", ref, alt, ".", filters, info))


def vcf(tmp_path: Path, rows: list[str] | None = None) -> Path:
    path = tmp_path / "synthetic-sites.vcf.bgz"
    declarations = [
        f'##INFO=<ID={name},Number={number},Type={kind},Description="Synthetic">'
        for name, number, kind in (
            ("AF", "A", "Float"),
            ("AC", "A", "Integer"),
            ("AN", "1", "Integer"),
            ("nhomalt", "A", "Integer"),
        )
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    "##fileformat=VCFv4.2",
                    "##contig=<ID=1,length=249250621,assembly=gnomAD_GRCh37>",
                    *declarations,
                    "\t".join(("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")),
                    *(rows if rows is not None else [row()]),
                ]
            )
            + "\n"
        )
    return path


def build(tmp_path: Path, rows: list[str] | None = None, progress: Any = None) -> FrequencyIndex:
    path = vcf(tmp_path, rows)
    return FrequencyIndex.build(
        path,
        output=tmp_path / "gnomad_frequencies.sqlite",
        version="r2.1.1",
        input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        progress=progress,
    )


def entry(*, status: str = "alternate_observed") -> dict[str, Any]:
    return {"status": status, "ref": "A", "alts": ["G"]}


def test_rare_gate_keeps_published_benchmark_and_exact_counts(tmp_path: Path) -> None:
    index = build(tmp_path)
    found = index.lookup([("7", POS), ("7", POS + 1)])
    assert ("7", POS + 1) not in found
    result = reliability(entry(), found[("7", POS)])
    assert result["tier"] == "likely-artifact"
    assert result["empirical_ppv"]["estimate"] == 0.16
    assert result["frequency"] == 1 / 200000
    assert found[("7", POS)][0]["populations"]["global"]["an"] == 200000
    assert reliability(entry(), [])["frequency"] is None


@pytest.mark.privacy
def test_sample_loci_never_change_the_public_reference_cache(tmp_path: Path) -> None:
    index = build(tmp_path)
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.iterdir()
        if p.is_file()
    }
    index.lookup([("7", POS), ("2", POS + 99)])
    after = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.iterdir()
        if p.is_file()
    }
    assert after == files
    with closing(sqlite3.connect(index.path)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"variants", "checkpoint"}


def test_population_maximum_prevents_pooled_rarity() -> None:
    record = parse_record(
        row(
            info="AC=1;AN=200000;AF=0.000005;nhomalt=0;AC_afr=1;AN_afr=1000;AF_afr=0.001;nhomalt_afr=0;AF_popmax=0.001;popmax=afr"
        )
    )
    result = reliability(entry(), [record])
    assert result["tier"] == "frequency_screen_passed"
    assert result["frequency"] == 0.001
    assert result["population"] == "afr"
    values = select_frequencies([record], alleles={"A", "G"}, called={"A", "G"})
    assert {v.population for v in values} == {"afr"}
    assert sum(v.frequency for v in values) == 1


def test_reported_subgroup_frequency_is_not_diluted_into_its_parent_population() -> None:
    record = parse_record(
        row(
            info=(
                "AC=1;AN=200000;AF=0.000005;nhomalt=0;"
                "AC_eas=1;AN_eas=120000;AF_eas=0.00000833333;nhomalt_eas=0;"
                "AC_eas_jpn=1;AN_eas_jpn=1000;AF_eas_jpn=0.001;nhomalt_eas_jpn=0"
            )
        )
    )
    result = reliability(entry(), [record])
    assert result["tier"] == "frequency_screen_passed"
    assert result["population"] == "eas_jpn"
    assert result["frequency"] == 0.001


@pytest.mark.parametrize(
    "info,filters,ref,alt",
    [
        ("AC=0;AN=0;AF=0;nhomalt=0", "PASS", "A", "G"),
        ("AC=1;AN=200000;nhomalt=0", "PASS", "A", "G"),
        ("AC=1;AN=200000;AF=0.000005;nhomalt=0", "RF", "A", "G"),
        ("AC=1;AN=200000;AF=0.000005;nhomalt=0", ".", "A", "G"),
        ("AC=1;AN=200000;AF=0.000005;nhomalt=0", "PASS", "C", "G"),
        ("AC=1;AN=200000;AF=0.000005;nhomalt=0", "PASS", "A", "T"),
        ("AC=1;AN=200000;AF=0.000005;nhomalt=0", "PASS", "A", "GG"),
        ("AC=1,1;AN=200000;AF=0.000005,0.000005;nhomalt=0,0", "PASS", "A", "G,T"),
    ],
)
def test_unknown_is_not_zero_or_a_reliable_call(
    info: str, filters: str, ref: str, alt: str
) -> None:
    record = parse_record(row(info=info, filters=filters, ref=ref, alt=alt))
    result = reliability(entry(), [record])
    assert result["tier"] == "unknown"
    assert result["frequency"] is None
    assert result["empirical_ppv"] is None


def test_duplicates_and_reference_only_do_not_get_alt_reliability() -> None:
    record = parse_record(row())
    assert reliability(entry(), [record, record])["tier"] == "unknown"
    assert reliability(entry(status="reference_only"), [record])["tier"] == "not_applicable"


def test_split_locus_does_not_mistake_other_alternate_frequency_for_reference() -> None:
    records = [parse_record(row()), parse_record(row(alt="T"))]
    values = select_frequencies(records, alleles={"A", "G"}, called={"A", "G"})
    assert len(values) == 1 and values[0].allele == "G"
    assert select_frequencies(records, alleles={"A", "G"}, called={"A"}) == ()
    assert reliability(entry(), records)["tier"] == "likely-artifact"


def test_boundary_uses_exact_counts_and_zero_requires_positive_denominator() -> None:
    at_boundary = parse_record(row(info="AC=2;AN=200000;AF=0.00001;nhomalt=0"))
    assert reliability(entry(), [at_boundary])["tier"] == "frequency_screen_passed"
    zero = parse_record(row(info="AC=0;AN=200000;AF=0;nhomalt=0"))
    assert reliability(entry(), [zero])["tier"] == "likely-artifact"


@pytest.mark.parametrize(
    "info",
    [
        "AC=1,2;AN=100;AF=0.01;nhomalt=0",
        "AC=101;AN=100;AF=1;nhomalt=0",
        "AC=1;AN=100;AF=0.9;nhomalt=0",
        "AC=1;AN=100;AF=0.01;nhomalt=1",
        "AC=1;AN=100;AF=nan;nhomalt=0",
        "AC=1;AN=100;AF=-0.1;nhomalt=0",
        "AC=1;AN=100;AF=0.01;AF=0.01;nhomalt=0",
        "AC=1.0;AN=100;AF=0.01;nhomalt=0",
    ],
)
def test_bad_cardinality_or_counts_fail_loudly(info: str) -> None:
    with pytest.raises(FrequencyError):
        parse_record(row(info=info))


def test_index_cache_binds_source_and_detects_corruption(tmp_path: Path) -> None:
    index = build(tmp_path)
    source = tmp_path / "synthetic-sites.vcf.bgz"
    before = index.path.stat().st_mtime_ns
    cached = FrequencyIndex.build(
        source, output=index.path, version="r2.1.1", input_sha256=index.provenance["sha256"]
    )
    assert cached.path.stat().st_mtime_ns == before
    with index.path.open("ab") as handle:
        handle.write(b"corruption")
    with pytest.raises(FrequencyError, match="provenance"):
        FrequencyIndex.open(index.path, expected=index.provenance)


@pytest.mark.parametrize(
    "before,after",
    [
        ("assembly=gnomAD_GRCh37", "assembly=gnomAD_GRCh38"),
        ("length=249250621", "length=248956422"),
        ("ID=AN,Number=1", "ID=AN,Number=A"),
        ("FILTER\tINFO\n", "FILTER\tINFO\tFORMAT\n"),
    ],
)
def test_wrong_build_or_frequency_header_cannot_produce_an_index(
    tmp_path: Path, before: str, after: str
) -> None:
    source = vcf(tmp_path)
    with gzip.open(source, "rt", encoding="utf-8") as handle:
        text = handle.read()
    assert before in text
    with gzip.open(source, "wt", encoding="utf-8") as handle:
        handle.write(text.replace(before, after))
    destination = tmp_path / "gnomad_frequencies.sqlite"
    with pytest.raises(FrequencyError):
        FrequencyIndex.build(
            source,
            output=destination,
            version="r2.1.1",
            input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
    assert not destination.exists()


def test_interrupted_build_recovers_only_checkpointed_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.health import frequencies

    real = frequencies._records
    source = vcf(tmp_path)
    destination = tmp_path / "gnomad_frequencies.sqlite"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    def interrupted(path: Path, *, skip: int = 0) -> Any:
        yield next(iter(real(path, skip=skip)))
        raise OSError("synthetic interruption")

    monkeypatch.setattr(frequencies, "_records", interrupted)
    with pytest.raises(OSError):
        FrequencyIndex.build(source, output=destination, version="r2.1.1", input_sha256=digest)
    assert not destination.exists()
    monkeypatch.setattr(frequencies, "_records", real)
    index = FrequencyIndex.build(source, output=destination, version="r2.1.1", input_sha256=digest)
    assert index.provenance["records"] == 1


@pytest.mark.parametrize("damage", [False, True])
def test_committed_checkpoint_resumes_or_refuses_changed_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: bool
) -> None:
    from genetics.health import frequencies

    source = vcf(tmp_path, [row(pos=POS + i) for i in range(4)])
    destination = tmp_path / "gnomad_frequencies.sqlite"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    real = frequencies._records

    def interrupted(path: Path, *, skip: int = 0) -> Any:
        for n, record in enumerate(real(path, skip=skip)):
            if n == 3:
                raise OSError("synthetic interruption after checkpoint")
            yield record

    monkeypatch.setattr(frequencies, "CHECKPOINT_ROWS", 2)
    monkeypatch.setattr(frequencies, "_records", interrupted)
    with pytest.raises(OSError):
        FrequencyIndex.build(source, output=destination, version="r2.1.1", input_sha256=digest)
    stage = destination.with_name(destination.name + ".building")
    with closing(sqlite3.connect(stage)) as db, db:
        assert db.execute("SELECT rows FROM checkpoint").fetchone()[0] == 2
        if damage:
            db.execute("UPDATE variants SET record='{}' WHERE rowid=1")
    monkeypatch.setattr(frequencies, "_records", real)
    if damage:
        with pytest.raises(FrequencyError, match="checksum"):
            FrequencyIndex.build(source, output=destination, version="r2.1.1", input_sha256=digest)
    else:
        result = FrequencyIndex.build(
            source, output=destination, version="r2.1.1", input_sha256=digest
        )
        assert result.provenance["records"] == 4
        assert len(result.lookup([("7", POS + i) for i in range(4)])) == 4


@pytest.mark.parametrize("existing_sidecar", [False, True])
def test_interrupted_provenance_promotion_recovers_verified_index(
    tmp_path: Path, existing_sidecar: bool
) -> None:
    result = build(tmp_path)
    sidecar = result.path.with_name(result.path.name + ".provenance.json")
    pending = sidecar.with_name(sidecar.name + ".tmp")
    if existing_sidecar:
        pending.write_bytes(sidecar.read_bytes())
        previous = json.loads(sidecar.read_text(encoding="utf-8"))
        previous["provenance"]["index_schema_version"] = 1
        sidecar.write_text(json.dumps(previous), encoding="utf-8")
    else:
        sidecar.rename(pending)
    source = tmp_path / "synthetic-sites.vcf.bgz"
    recovered = FrequencyIndex.build(
        source, output=result.path, version="r2.1.1", input_sha256=result.provenance["sha256"]
    )
    assert sidecar.is_file()
    assert not pending.exists()
    assert recovered.provenance == result.provenance


def test_an_older_verified_public_index_is_rebuilt_without_orphaning_saved_data(
    tmp_path: Path,
) -> None:
    result = build(tmp_path)
    sidecar = result.path.with_name(result.path.name + ".provenance.json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["provenance"]["index_schema_version"] = 1
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    source = tmp_path / "synthetic-sites.vcf.bgz"
    messages: list[str] = []
    rebuilt = FrequencyIndex.build(
        source,
        output=result.path,
        version="r2.1.1",
        input_sha256=result.provenance["sha256"],
        progress=messages.append,
    )
    assert rebuilt.provenance["index_schema_version"] == 2
    assert any("Rebuilding" in message for message in messages)


def test_pipeline_uses_reference_frequency_without_dropping_any_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.engine.confidence import ConfidenceTier
    from genetics.run.pipeline import analyse
    from genetics.testing.fixtures import FIXTURES, render_fixture

    index = build(tmp_path)
    monkeypatch.setattr("genetics.run.pipeline.default_index", lambda **kwargs: index)
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    export = tmp_path / "synthetic-export.txt"
    export.write_text(
        render_fixture(
            replace(
                spec,
                spike_ins={
                    "rs900000001": (7, POS, "A", "G"),
                },
            )
        ),
        encoding="utf-8",
    )
    knowledge = Path(__file__).parents[1] / "fixtures" / "cards"
    result = analyse(export, knowledge_dir=knowledge)
    card = next(c for c in result.cards if c.card_id == "synthetic_dominant_trait")
    assert len(result.cards) == len(result.pack.cards)
    assert card.confidence is not None and card.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT
    assert card.confidence_frequency is not None
    assert card.confidence_frequency.frequency == 1 / 200000
    assert card.confidence_frequency.source.startswith("gnomAD r2.1.1")


def test_calibrated_snapshot_validates_and_cannot_relabel_rare_call(tmp_path: Path) -> None:
    import polars as pl

    from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable

    frequency = build(tmp_path)
    clinvar_path = tmp_path / "synthetic-clinvar.vcf.gz"
    with gzip.open(clinvar_path, "wt", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    "##fileformat=VCFv4.1",
                    "##fileDate=2026-01-01",
                    "##reference=GRCh37",
                    "\t".join(("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")),
                    "\t".join(
                        ("7", str(POS), "900000001", "A", "G", ".", ".", "CLNSIG=Pathogenic")
                    ),
                ]
            )
            + "\n"
        )
    table = GenotypeTable(
        pl.DataFrame(
            [
                {
                    "rsid": "rs900000001",
                    "chrom": "7",
                    "pos_grch37": POS,
                    "a1": "A",
                    "a2": "G",
                    "genotype": "AG",
                    "call_status": "called",
                }
            ],
            schema=NORMALIZED_SCHEMA,
        ),
        vendor="synthetic",
    )
    lookup = ClinVarIndex.build(clinvar_path, version="2026-01-01").lookup(table)
    calibrated = calibrate(lookup, index=frequency, records=frequency.lookup([("7", POS)]))
    raw = calibrated.to_dict()
    validate_lookup(raw)
    assert raw["schema_version"] == 2
    assert raw["loci"][0]["records"][0]["reliability"]["tier"] == "likely-artifact"
    older_index = copy.deepcopy(raw)
    older_index["frequency_reference"]["provenance"]["index_schema_version"] = 1
    validate_lookup(older_index)
    changed = copy.deepcopy(raw)
    changed["loci"][0]["records"][0]["reliability"]["tier"] = "frequency_screen_passed"
    with pytest.raises(FrequencyError):
        validate_lookup(changed)
    unknown = calibrate(lookup, index=None, records={}).to_dict()
    validate_lookup(unknown)
    assert unknown["loci"][0]["records"][0]["reliability"]["tier"] == "unknown"
    validate_lookup(lookup.to_dict())  # schema 1 remains readable without reinterpretation


def test_manifest_transform_has_real_executor_and_verified_provenance(tmp_path: Path) -> None:
    source = vcf(tmp_path)
    parsed = Source.parse(
        {
            "id": "gnomad_exomes_r2_1_1_grch37",
            "name": "Synthetic",
            "homepage": "https://example.org/",
            "tier": "A",
            "required": True,
            "version": "r2.1.1",
            "license": "LicenseRef-gnomAD-Open-Access",
            "files": [
                {
                    "filename": source.name,
                    "url": "https://example.org/sites.vcf.bgz",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ],
            "post_process": [
                {
                    "step": "build_gnomad_frequency_index",
                    "params": {"input": source.name, "output": "gnomad_frequencies.sqlite"},
                }
            ],
        },
        "synthetic",
    )
    root = tmp_path / "refs"
    folder = root / parsed.id
    folder.mkdir(parents=True)
    (folder / source.name).write_bytes(source.read_bytes())
    postprocess.assert_registry_is_honest()
    built = postprocess.run(parsed, root=root)
    assert built[0].status == postprocess.ProcessStatus.CREATED
    checked = postprocess.run(parsed, root=root, verify_only=True)
    assert checked[0].status == postprocess.ProcessStatus.VERIFIED
    sidecar = json.loads((folder / "gnomad_frequencies.sqlite.provenance.json").read_text())
    assert sidecar["provenance"]["records"] == 1
