"""Fabricated public-reference shapes only; no personal genomes or network."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.pgs.catalog import ID_COLUMN, MEMBER_NAME, TERMS_COLUMN, Catalog, PgsError
from genetics.pgs.scoring import ScoringFile
from genetics.refs import licenses, manifest, postprocess
from genetics.refs.postprocess import ProcessStatus

EBI = "https://www.ebi.ac.uk/about/terms-of-use/"
BASE = {
    "rsID": "rs1000001",
    "chr_name": "1",
    "chr_position": "101",
    "effect_allele": "A",
    "other_allele": "C",
    "effect_weight": "-0.25",
}


def metadata_archive(
    path: Path,
    *,
    terms: str = EBI,
    duplicate: bool = False,
    text: str | None = None,
    member_name: str = MEMBER_NAME,
) -> Path:
    if text is None:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow([ID_COLUMN, TERMS_COLUMN, "Original Genome Build", "Number of Variants"])
        writer.writerow(["PGS000001", terms, "GRCh37", "1"])
        if duplicate:
            writer.writerow(["PGS000001", terms, "GRCh37", "1"])
        text = stream.getvalue()
    payload = text.encode("utf-8")
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(member_name)
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    return path


def scoring_file(
    path: Path,
    *,
    row: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    raw: str | None = None,
) -> Path:
    if raw is None:
        values = BASE if row is None else row
        head = {
            "format_version": "2.0",
            "pgs_id": "PGS000001",
            "genome_build": "GRCh37",
            "variants_number": "1",
            "weight_type": "beta",
        }
        head.update(headers or {})
        raw = "".join(f"#{key}={value}\n" for key, value in head.items())
        raw += "\t".join(values) + "\n" + "\t".join(values.values()) + "\n"
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            handle.write(raw)
    else:
        path.write_text(raw, encoding="utf-8")
    return path


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    return Catalog.from_archive(metadata_archive(tmp_path / "metadata.tar.gz"))


@pytest.mark.parametrize("compressed", [False, True])
def test_public_score_stream_retains_signed_weights_and_raw_fields(
    tmp_path: Path,
    catalog: Catalog,
    compressed: bool,
) -> None:
    path = scoring_file(tmp_path / ("score.txt.gz" if compressed else "score.txt"))
    score = ScoringFile.open(path, catalog)
    (row,) = score.iter_variants()
    assert (row.chrom, row.position, row.effect_allele, row.effect_weight) == ("1", 101, "A", -0.25)
    assert row.fields == BASE and row.features == ()
    result = score.inspect()
    assert result["rows"] == 1 and result["scoring_implemented"] is False
    assert result["scoring_source"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["metadata_source"] == dict(catalog.source)


def test_harmonized_coordinates_keep_original_build_and_allow_partial_author_coordinates(
    tmp_path: Path,
) -> None:
    archive = metadata_archive(
        tmp_path / "meta.tar.gz",
        text=(
            f"{ID_COLUMN},{TERMS_COLUMN},Original Genome Build,Number of Variants\n"
            f"PGS000001,{EBI},GRCh38,1\n"
        ),
    )
    row = {**BASE, "chr_position": "", "hm_chr": "2", "hm_pos": "202", "hm_source": "liftover"}
    path = scoring_file(
        tmp_path / "PGS000001_hmPOS_GRCh37.txt.gz",
        row=row,
        headers={"genome_build": "GRCh38", "HmPOS_build": "GRCh37"},
    )
    score = ScoringFile.open(path, Catalog.from_archive(archive))
    (parsed,) = score.iter_variants()
    assert (parsed.chrom, parsed.position) == ("2", 202)
    assert score.headers["genome_build"] == "GRCh38"
    assert parsed.fields["chr_position"] == ""


@pytest.mark.parametrize(
    "terms,status",
    [
        (EBI, "permissive"),
        ("CC-BY-4.0", "permissive"),
        ("CC0-1.0", "permissive"),
        ("CC-BY-NC-ND-4.0", "restricted"),
        ("CC-BY-SA-4.0", "restricted"),
        ("Creative Commons Attribution 4.0 International (CC BY 4.0).", "permissive"),
        (
            "Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International (CC BY-NC-ND 4.0)",
            "restricted",
        ),
        ("", "missing"),
        ("Academic research only", "unknown"),
        ("CC-BY-4.0; private use only", "unknown"),
        ("https://www.ebi.ac.uk/about/terms-of-use/ plus additional restrictions", "unknown"),
        (
            "Creative Commons Attribution 4.0 International (CC BY 4.0). No redistribution.",
            "unknown",
        ),
    ],
)
def test_terms_require_complete_reviewed_wording(terms: str, status: str) -> None:
    resolved = licenses.classify_pgs_terms(terms)
    assert resolved.status == status
    if status == "permissive":
        resolved.require_usable()
    else:
        with pytest.raises(ValueError):
            resolved.require_usable()
        if status == "restricted":
            resolved.require_usable(opt_in=True)
        else:
            with pytest.raises(ValueError):
                resolved.require_usable(opt_in=True)


def test_header_permission_never_overrides_the_metadata_terms(tmp_path: Path) -> None:
    catalog = Catalog.from_archive(
        metadata_archive(tmp_path / "metadata.tar.gz", terms="CC-BY-NC-ND-4.0")
    )
    path = scoring_file(tmp_path / "score.txt", headers={"license": "CC0-1.0"})
    score = ScoringFile.open(path, catalog)
    assert score.inspect()["metadata"]["license"]["status"] == "restricted"
    with pytest.raises(ValueError):
        score.metadata.license.require_usable()


def test_duplicate_metadata_stays_ambiguous_even_when_terms_are_identical(tmp_path: Path) -> None:
    catalog = Catalog.from_archive(metadata_archive(tmp_path / "metadata.tar.gz", duplicate=True))
    assert len(catalog.get("PGS000001").records) == 2
    assert catalog.get("PGS000001").license.status == "ambiguous"
    with pytest.raises(ValueError):
        catalog.get("PGS000001").license.require_usable(opt_in=True)


@pytest.mark.parametrize(
    "text",
    [
        "Other ID,License/Terms of Use\nPGS000001,CC0-1.0\n",
        f"{ID_COLUMN},Terms\nPGS000001,CC0-1.0\n",
        f"{ID_COLUMN},{TERMS_COLUMN},{TERMS_COLUMN}\nPGS000001,CC0-1.0,CC0-1.0\n",
        f"{ID_COLUMN},{TERMS_COLUMN}\nBAD,CC0-1.0\n",
        f"{ID_COLUMN},{TERMS_COLUMN}\nPGS000001,CC0-1.0,extra\n",
        f"{ID_COLUMN},{TERMS_COLUMN}\nPGS000001\n",
        f"{ID_COLUMN},{TERMS_COLUMN}\n",
    ],
)
def test_malformed_metadata_fails_loudly(tmp_path: Path, text: str) -> None:
    with pytest.raises(PgsError):
        Catalog.from_archive(metadata_archive(tmp_path / "metadata.tar.gz", text=text))


def test_metadata_archive_links_and_duplicate_members_cannot_supply_terms(tmp_path: Path) -> None:
    path = metadata_archive(tmp_path / "metadata.tar.gz")
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(MEMBER_NAME)
        member.type = tarfile.SYMTYPE
        member.linkname = "elsewhere.csv"
        archive.addfile(member)
    with pytest.raises(PgsError):
        Catalog.from_archive(path)
    with tarfile.open(path, "w:gz") as archive:
        for _ in range(2):
            archive.addfile(tarfile.TarInfo(MEMBER_NAME), io.BytesIO(b""))
    with pytest.raises(PgsError):
        Catalog.from_archive(path)


@pytest.mark.parametrize(
    "change",
    [
        {"effect_weight": "nan"},
        {"effect_weight": "inf"},
        {"effect_weight": "-inf"},
        {"effect_weight": ""},
        {"effect_weight": "bad"},
        {"effect_allele": "."},
        {"effect_allele": "N"},
        {"effect_allele": ""},
        {"other_allele": "N"},
        {"other_allele": "A"},
        {"chr_position": "0"},
        {"chr_position": "-1"},
        {"chr_position": "1.2"},
        {"chr_name": "23"},
        {"is_dominant": "maybe"},
        {"is_dominant": "TRUE", "is_recessive": "TRUE"},
        {"OR": "0"},
        {"HR": "nan"},
        {"dosage_0_weight": "1"},
        {"hm_match_pos": "perhaps"},
        {"chr_position": "", "rsID": ""},
    ],
)
def test_invalid_weights_alleles_locations_and_models_fail_before_inspection(
    tmp_path: Path,
    catalog: Catalog,
    change: dict[str, str],
) -> None:
    path = scoring_file(tmp_path / "score.txt", row={**BASE, **change})
    with pytest.raises(PgsError):
        ScoringFile.open(path, catalog).inspect()


@pytest.mark.parametrize(
    "change",
    [
        {"format_version": "1.0"},
        {"format_version": "3.0"},
        {"pgs_id": "bad"},
        {"pgs_id": "PGS000002"},
        {"genome_build": "GRCh38"},
        {"genome_build": "unknown"},
        {"variants_number": "0"},
        {"variants_number": "2"},
        {"variants_number": "nan"},
        {"HmPOS_build": "GRCh37"},
    ],
)
def test_conflicting_headers_and_joins_are_refused(
    tmp_path: Path,
    catalog: Catalog,
    change: dict[str, str],
) -> None:
    path = scoring_file(tmp_path / "score.txt", headers=change)
    with pytest.raises(PgsError):
        ScoringFile.open(path, catalog).inspect()


def test_extra_missing_duplicate_fields_and_midstream_headers_are_refused(
    tmp_path: Path,
    catalog: Catalog,
) -> None:
    path = scoring_file(tmp_path / "score.txt")
    valid = path.read_text(encoding="utf-8")
    for invalid in (
        valid + "extra\n",
        valid.replace("-0.25\n", "-0.25\textra\n"),
        valid.replace("other_allele", "effect_allele"),
        valid.replace("#pgs_id=", "#pgs_id=PGS000001\n#pgs_id="),
        valid.replace("effect_weight", "wrong_column"),
    ):
        scoring_file(path, raw=invalid)
        with pytest.raises(PgsError):
            ScoringFile.open(path, catalog).inspect()


@pytest.mark.parametrize(
    "feature", ["is_haplotype", "is_diplotype", "is_interaction", "is_dominant", "is_recessive"]
)
def test_special_model_flags_survive_parser_without_becoming_additive(
    tmp_path: Path,
    catalog: Catalog,
    feature: str,
) -> None:
    path = scoring_file(tmp_path / "score.txt", row={**BASE, feature: "TRUE"})
    (variant,) = ScoringFile.open(path, catalog).iter_variants()
    assert feature in variant.features and variant.fields[feature] == "TRUE"


def test_dosage_specific_weights_and_unknown_columns_are_preserved(
    tmp_path: Path,
    catalog: Catalog,
) -> None:
    row = {
        **BASE,
        "effect_weight": "",
        "dosage_0_weight": "0",
        "dosage_1_weight": "2",
        "dosage_2_weight": "3",
        "future_annotation": "retained",
    }
    path = scoring_file(tmp_path / "score.txt", row=row)
    (variant,) = ScoringFile.open(path, catalog).iter_variants()
    assert variant.effect_weight is None and "dosage_specific_weights" in variant.features
    assert variant.fields == row


def test_unresolved_loci_and_indels_are_visible_not_inferred(
    tmp_path: Path, catalog: Catalog
) -> None:
    row = {**BASE, "chr_position": "", "effect_allele": "I"}
    path = scoring_file(tmp_path / "score.txt", row=row)
    (variant,) = ScoringFile.open(path, catalog).iter_variants()
    assert variant.chrom is None and variant.position is None
    assert {"unresolved_locus", "unresolved_indel"} <= set(variant.features)


def test_stream_is_bound_to_its_original_file(tmp_path: Path, catalog: Catalog) -> None:
    path = scoring_file(tmp_path / "score.txt")
    score = ScoringFile.open(path, catalog)
    scoring_file(path, row={**BASE, "effect_weight": "1"})
    with pytest.raises(PgsError, match="changed"):
        list(score.iter_variants())


def test_truncated_gzip_and_wrong_filename_are_categorical(
    tmp_path: Path, catalog: Catalog
) -> None:
    path = scoring_file(tmp_path / "PGS000002.txt.gz")
    with pytest.raises(PgsError, match="filename"):
        ScoringFile.open(path, catalog)
    path = scoring_file(tmp_path / "score.txt.gz")
    path.write_bytes(path.read_bytes()[:-8])
    with pytest.raises(PgsError):
        ScoringFile.open(path, catalog).inspect()


def declared_source() -> manifest.Source:
    return manifest.loads("""
schema_version: 1
sources:
  - id: synthetic_pgs
    name: Synthetic public PGS metadata
    tier: A
    version: test
    homepage: https://example.org/
    license: LicenseRef-PGS-Catalog-Per-Score
    files:
      - url: https://example.org/metadata.tar.gz
        filename: metadata.tar.gz
        unpinned_reason: synthetic
    post_process:
      - step: parse_pgs_score_licenses
        params:
          input: metadata.tar.gz
          output: pgs_score_licenses.json
""").get("synthetic_pgs")


def test_transform_creates_reuses_verifies_and_refuses_corrupt_index(tmp_path: Path) -> None:
    source = declared_source()
    source_dir = tmp_path / source.id
    source_dir.mkdir()
    archive = metadata_archive(source_dir / "metadata.tar.gz")
    (pending,) = postprocess.run(source, root=tmp_path, verify_only=True)
    assert pending.status is ProcessStatus.PENDING
    (created,) = postprocess.run(source, root=tmp_path)
    assert created.status is ProcessStatus.CREATED and created.rows == 1
    (reused,) = postprocess.run(source, root=tmp_path)
    assert reused.status is ProcessStatus.ALREADY_PRESENT
    (verified,) = postprocess.run(source, root=tmp_path, verify_only=True)
    assert verified.status is ProcessStatus.VERIFIED
    output = source_dir / "pgs_score_licenses.json"
    loaded = Catalog.load(output)
    assert loaded.source["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    raw = json.loads(output.read_text(encoding="utf-8"))
    raw["scores"]["PGS000001"]["license"]["status"] = "restricted"
    output.write_text(json.dumps(raw), encoding="utf-8")
    # Rehashing does not rescue a licence that disagrees with authoritative raw terms.
    sidecar = postprocess.provenance_path(output)
    provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    provenance["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    sidecar.write_text(json.dumps(provenance), encoding="utf-8")
    (failed,) = postprocess.run(source, root=tmp_path, verify_only=True)
    assert failed.status is ProcessStatus.FAILED
    (repaired,) = postprocess.run(source, root=tmp_path)
    assert repaired.status is ProcessStatus.CREATED
    metadata_archive(archive, terms="CC-BY-NC-ND-4.0")
    (stale,) = postprocess.run(source, root=tmp_path, verify_only=True)
    assert stale.status is ProcessStatus.FAILED
    postprocess.run(source, root=tmp_path)
    assert Catalog.load(output).get("PGS000001").license.status == "restricted"


def test_cli_reports_license_metadata_and_build_without_personal_scoring(tmp_path: Path) -> None:
    archive = metadata_archive(tmp_path / "metadata.tar.gz")
    path = scoring_file(tmp_path / "score.txt")
    runner = CliRunner()
    result = runner.invoke(app, ["pgs", "inspect", str(path), "--metadata", str(archive), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] and payload["rows"] == 1
    assert payload["metadata"]["license"]["status"] == "permissive"
    bad = runner.invoke(
        app,
        [
            "pgs",
            "inspect",
            str(path),
            "--metadata",
            str(archive),
            "--pgs-id",
            "PGS000002",
            "--json",
        ],
    )
    assert bad.exit_code == 1 and not json.loads(bad.stdout)["ok"]


@pytest.mark.privacy
def test_new_public_reference_outputs_are_ignored(tmp_path: Path) -> None:
    import subprocess

    for name in (
        "pgs_score_licenses.json",
        "reference.pgs-reference.json",
        "PGS000001_hmPOS_GRCh37.txt.gz",
        "PGS000001.txt",
    ):
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={Path.cwd().as_posix()}",
                "check-ignore",
                "--no-index",
                name,
            ],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
