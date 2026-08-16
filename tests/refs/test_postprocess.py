"""Executable reference transforms use only tiny synthetic public-data lookalikes."""

from __future__ import annotations

import bz2
import gzip
import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path

import polars as pl
import pytest

from genetics.ingest.keys import MergeTable, UnresolvableRsidError
from genetics.paths import reference_lock
from genetics.qc.build_anchors import AnchorError, load_anchors
from genetics.refs import lock as lockfile
from genetics.refs import manifest, postprocess
from genetics.refs.postprocess import ProcessStatus


def source(text: str) -> manifest.Source:
    return manifest.loads(
        """
schema_version: 1
sources:
  - id: synthetic_reference
    name: Synthetic reference
    tier: A
    version: test
    homepage: https://example.org/
    license: CC0-1.0
"""
        + text
    ).get("synthetic_reference")


def remote(filename: str) -> str:
    return f"""
    files:
      - url: https://example.org/{filename}
        filename: {filename}
        sha256: {"a" * 64}
"""


def test_registry_never_claims_an_executor_that_does_not_exist() -> None:
    postprocess.assert_registry_is_honest()


def test_declared_artifact_provenance_uses_manifest_params_and_locked_input_sha() -> None:
    expected = postprocess.declared_artifact_provenance(
        "dbsnp_b157_grch37",
        "extract_dbsnp_variant_index",
        output_name="dbsnp_variants.parquet",
    )
    locked_sha = lockfile.read(reference_lock()).file_digest(
        "dbsnp_b157_grch37", "GCF_000001405.25.gz"
    )

    assert expected["input"] == {
        "filename": "GCF_000001405.25.gz",
        "sha256": locked_sha,
    }
    assert expected["params"] == {
        "input": "GCF_000001405.25.gz",
        "output": "dbsnp_variants.parquet",
    }


def test_post_process_paths_are_validated_with_download_paths() -> None:
    text = (
        remote("input.gz")
        + """
    post_process:
      - step: extract_dbsnp_variant_index
        params:
          input: input.gz
          output: ../escape.parquet
"""
    )
    with pytest.raises(manifest.ManifestError, match="escapes its directory"):
        source(text)


def test_dbsnp_vcf_becomes_the_explicit_variant_index_contract(tmp_path: Path) -> None:
    parsed = source(
        remote("dbsnp.vcf.gz")
        + """
    post_process:
      - step: extract_dbsnp_variant_index
        params:
          input: dbsnp.vcf.gz
          output: dbsnp_variants.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    with gzip.open(source_dir / "dbsnp.vcf.gz", "wt", encoding="ascii") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        handle.write("NC_000001.10\t101\trs101\tA\tG\t.\t.\tRS=101\n")
        handle.write("NC_000023.10\t202\trs202\tC\tA,T\t.\t.\tRS=202\n")
        # Alternate contigs cannot be represented by the card chromosome vocabulary.
        handle.write("NT_123456.1\t303\trs303\tG\tA\t.\t.\tRS=303\n")

    result = postprocess.run(parsed, root=tmp_path)

    assert result[0].status is ProcessStatus.CREATED
    frame = pl.read_parquet(source_dir / "dbsnp_variants.parquet")
    assert frame.schema == postprocess.VARIANT_INDEX_SCHEMA
    assert frame.to_dicts() == [
        {"rsid": "rs101", "chrom": "1", "pos_grch37": 101, "ref": "A", "alts": ["G"]},
        {
            "rsid": "rs202",
            "chrom": "X",
            "pos_grch37": 202,
            "ref": "C",
            "alts": ["A", "T"],
        },
    ]
    assert not (source_dir / ".dbsnp_variants.parquet.part").exists()
    assert not (source_dir / ".dbsnp_variants.parquet.chunks").exists()


def test_dbsnp_vcf_skips_only_the_lone_no_alternate_sentinel(tmp_path: Path) -> None:
    path = tmp_path / "dbsnp.vcf.gz"
    with gzip.open(path, "wt", encoding="ascii") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        # VCF ALT='.' means that no alternate allele is specified. dbSNP carries these
        # non-variant placements, which have no allele-bearing row to add to the index.
        handle.write("NC_000001.10\t100\trs100\tT\t.\t.\t.\tRS=100;VC=SNV\n")
        # Symbolic alleles are genuine VCF alternate alleles and remain representable.
        handle.write("NC_000001.10\t101\trs101\tA\t<DEL>\t.\t.\tRS=101;VC=DIV\n")
        handle.write("NC_000001.10\t102\trs102\tC\tG\t.\t.\tRS=102;VC=SNV\n")

    assert list(postprocess._vcf_records(path)) == [
        ("rs101", "1", 101, "A", ["<DEL>"]),
        ("rs102", "1", 102, "C", ["G"]),
    ]


@pytest.mark.parametrize("ref, alt", [("A", ""), ("", "G"), ("A", "G,.")])
def test_dbsnp_vcf_rejects_malformed_allele_fields(tmp_path: Path, ref: str, alt: str) -> None:
    path = tmp_path / "dbsnp.vcf.gz"
    with gzip.open(path, "wt", encoding="ascii") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        handle.write(f"NC_000001.10\t100\trs100\t{ref}\t{alt}\t.\t.\tRS=100\n")

    with pytest.raises(postprocess.ProcessError, match="empty allele at line 3"):
        list(postprocess._vcf_records(path))


def test_refsnp_merge_json_round_trips_through_merge_table(tmp_path: Path) -> None:
    parsed = source(
        remote("refsnp-merged.json.bz2")
        + """
    post_process:
      - step: extract_rsid_merge_table
        params:
          input: refsnp-merged.json.bz2
          output: rsid_merges.parquet
          unresolvable_output: rsid_unresolvable.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    rows = [
        {"refsnp_id": "800", "merged_snapshot_data": {"merged_into": ["700"]}},
        {"refsnp_id": "900", "merged_snapshot_data": {"merged_into": ["800"]}},
    ]
    with bz2.open(source_dir / "refsnp-merged.json.bz2", "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    result = postprocess.run(parsed, root=tmp_path)
    merges = MergeTable.from_parquet(source_dir / "rsid_merges.parquet", rsids=["rs900"])

    assert result[0].rows == 2
    assert merges.resolve("rs900") == "rs700"


def test_merge_loader_rejects_a_sidecar_from_another_locked_input(tmp_path: Path) -> None:
    parsed = source(
        remote("refsnp-merged.json.bz2")
        + """
    post_process:
      - step: extract_rsid_merge_table
        params:
          input: refsnp-merged.json.bz2
          output: rsid_merges.parquet
          unresolvable_output: rsid_unresolvable.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    with bz2.open(source_dir / "refsnp-merged.json.bz2", "wt", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"refsnp_id": "800", "merged_snapshot_data": {"merged_into": ["700"]}})
            + "\n"
        )
    postprocess.run(parsed, root=tmp_path)
    merge_path = source_dir / "rsid_merges.parquet"
    unresolved_path = source_dir / "rsid_unresolvable.parquet"

    bad_merge = postprocess._expected_provenance(
        parsed.post_process[0],
        source_dir / "refsnp-merged.json.bz2",
        "f" * 64,
    )
    bad_unresolved = postprocess._expected_provenance(
        parsed.post_process[0],
        source_dir / "refsnp-merged.json.bz2",
        "f" * 64,
        output_param="unresolvable_output",
    )

    with pytest.raises(ValueError, match="stale for the current input"):
        MergeTable.from_parquet(
            merge_path,
            rsids=["rs800"],
            unresolved_path=unresolved_path,
            provenance_contracts=(bad_merge, bad_unresolved),
        )


def test_merge_transform_preserves_unresolvable_records_and_scoped_loading(
    tmp_path: Path,
) -> None:
    parsed = source(
        remote("refsnp-merged.json.bz2")
        + """
    post_process:
      - step: extract_rsid_merge_table
        params:
          input: refsnp-merged.json.bz2
          output: rsid_merges.parquet
          unresolvable_output: rsid_unresolvable.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    rows = [
        {"refsnp_id": "100", "merged_snapshot_data": {"merged_into": ["200"]}},
        {"refsnp_id": "200", "merged_snapshot_data": {"merged_into": ["300", "400"]}},
        {"refsnp_id": "500", "merged_snapshot_data": {"merged_into": []}},
        # This unrelated mapping must not be loaded by a query rooted at rs100.
        {"refsnp_id": "600", "merged_snapshot_data": {"merged_into": ["700"]}},
    ]
    with bz2.open(source_dir / "refsnp-merged.json.bz2", "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    result = postprocess.run(parsed, root=tmp_path)
    unresolved_path = source_dir / "rsid_unresolvable.parquet"
    unresolved = pl.read_parquet(unresolved_path)
    merges = MergeTable.from_parquet(
        source_dir / "rsid_merges.parquet",
        rsids=["rs100"],
        unresolved_path=unresolved_path,
    )

    assert result[0].rows == 2
    assert "2 unresolvable" in result[0].detail
    assert unresolved.to_dicts() == [
        {
            "retired_rsid": "rs200",
            "status": "multiple-current-targets",
            "targets": ["rs300", "rs400"],
        },
        {"retired_rsid": "rs500", "status": "no-current-target", "targets": []},
    ]
    assert len(merges) == 2  # rs100 plus its unresolved terminal; not unrelated rs600.
    with pytest.raises(UnresolvableRsidError):
        merges.resolve("rs100")


def test_non_unique_merges_are_preserved_without_picking_a_target(tmp_path: Path) -> None:
    path = tmp_path / "merged.json.bz2"
    with bz2.open(path, "wt", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"refsnp_id": "900", "merged_snapshot_data": {"merged_into": ["800", "700"]}}
            )
            + "\n"
        )
        handle.write(json.dumps({"refsnp_id": "901", "merged_snapshot_data": {"merged_into": []}}))
    assert list(postprocess._merge_records(path)) == [
        (
            "rs900",
            "multiple-current-targets",
            None,
            ["rs800", "rs700"],
        ),
        ("rs901", "no-current-target", None, []),
    ]


def test_merge_parser_rejects_duplicate_or_out_of_order_retired_ids(tmp_path: Path) -> None:
    path = tmp_path / "merged.json.bz2"
    with bz2.open(path, "wt", encoding="utf-8") as handle:
        for retired in (900, 900):
            handle.write(
                json.dumps(
                    {
                        "refsnp_id": str(retired),
                        "merged_snapshot_data": {"merged_into": ["1000"]},
                    }
                )
                + "\n"
            )
    with pytest.raises(postprocess.ProcessError, match="duplicate retired rsID"):
        list(postprocess._merge_records(path))


def _clinvar_row(
    allele_id: int, rsid: int, assembly: str, chrom: str, position: int, gene: str
) -> str:
    return (
        f"{allele_id}\tsingle nucleotide variant\t{gene}\t{rsid}\t{assembly}\t"
        f"{chrom}\t{position}\t{position}\tna\tna\tA\tG\n"
    )


def test_clinvar_summary_produces_sourced_dual_build_anchors(tmp_path: Path) -> None:
    parsed = source(
        remote("variant_summary.txt.gz")
        + """
    post_process:
      - step: extract_build_anchors
        params:
          input: variant_summary.txt.gz
          output: build_anchors.json
          count: 2
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    header = (
        "#AlleleID\tType\tGeneSymbol\tRS# (dbSNP)\tAssembly\tChromosome\t"
        "Start\tStop\tReferenceAllele\tAlternateAllele\t"
        "ReferenceAlleleVCF\tAlternateAlleleVCF\n"
    )
    with gzip.open(source_dir / "variant_summary.txt.gz", "wt", encoding="utf-8") as handle:
        handle.write(header)
        # Same coordinate on both builds cannot discriminate them and must not become an
        # anchor even though its lower rsID would otherwise be selected first.
        handle.write(_clinvar_row(0, 5, "GRCh37", "1", 50, "STATIC"))
        handle.write(_clinvar_row(0, 5, "GRCh38", "1", 50, "STATIC"))
        handle.write(_clinvar_row(1, 10, "GRCh37", "1", 101, "GENE1"))
        handle.write(_clinvar_row(1, 10, "GRCh38", "1", 111, "GENE1"))
        handle.write(_clinvar_row(2, 20, "GRCh37", "2", 202, "GENE2"))
        handle.write(_clinvar_row(2, 20, "GRCh38", "2", 222, "GENE2"))
        # Multiple ClinVar alleles may share a multiallelic RefSNP; one rsID is one QC
        # anchor, not one anchor per allele.
        handle.write(_clinvar_row(3, 10, "GRCh37", "1", 101, "GENE1"))
        handle.write(_clinvar_row(3, 10, "GRCh38", "1", 111, "GENE1"))

    result = postprocess.run(parsed, root=tmp_path)
    anchors = load_anchors(source_dir / "build_anchors.json")

    assert result[0].status is ProcessStatus.CREATED
    assert [(a.rsid, a.pos_grch37, a.pos_grch38) for a in anchors] == [
        ("rs10", 101, 111),
        ("rs20", 202, 222),
    ]
    assert all(anchor.verified for anchor in anchors)
    assert all(
        anchor.source is not None and "rolling variant_summary.txt.gz" in anchor.source
        for anchor in anchors
    )
    assert all(anchor.source is not None and "input sha256" in anchor.source for anchor in anchors)


def test_anchor_loader_rejects_a_sidecar_from_another_locked_input(tmp_path: Path) -> None:
    parsed = source(
        remote("variant_summary.txt.gz")
        + """
    post_process:
      - step: extract_build_anchors
        params:
          input: variant_summary.txt.gz
          output: build_anchors.json
          count: 1
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    header = (
        "#AlleleID\tType\tGeneSymbol\tRS# (dbSNP)\tAssembly\tChromosome\t"
        "Start\tStop\tReferenceAllele\tAlternateAllele\t"
        "ReferenceAlleleVCF\tAlternateAlleleVCF\n"
    )
    with gzip.open(source_dir / "variant_summary.txt.gz", "wt", encoding="utf-8") as handle:
        handle.write(header)
        handle.write(_clinvar_row(1, 10, "GRCh37", "1", 101, "GENE1"))
        handle.write(_clinvar_row(1, 10, "GRCh38", "1", 111, "GENE1"))
    postprocess.run(parsed, root=tmp_path)
    anchor_path = source_dir / "build_anchors.json"
    raw = json.loads(postprocess.provenance_path(anchor_path).read_text(encoding="utf-8"))
    expected = {key: value for key, value in raw.items() if key not in {"rows", "output_sha256"}}
    expected["input"] = {"filename": "variant_summary.txt.gz", "sha256": "f" * 64}

    with pytest.raises(AnchorError, match="stale for the current input"):
        load_anchors(anchor_path, expected_count=1, expected_provenance=expected)


def test_clinvar_pairs_skip_ambiguous_placements_but_allow_exact_duplicates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "variant_summary.txt.gz"
    header = (
        "#AlleleID\tType\tGeneSymbol\tRS# (dbSNP)\tAssembly\tChromosome\t"
        "Start\tStop\tReferenceAllele\tAlternateAllele\t"
        "ReferenceAlleleVCF\tAlternateAlleleVCF\n"
    )
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(header)
        # Duplicate/transcript rows describing one placement remain usable even when
        # their gene labels differ.
        handle.write(_clinvar_row(1, 10, "GRCh37", "1", 101, "GENE1"))
        handle.write(_clinvar_row(1, 10, "GRCh37", "1", 101, "GENE1_ALIAS"))
        handle.write(_clinvar_row(1, 10, "GRCh38", "1", 111, "GENE1"))
        handle.write(_clinvar_row(1, 10, "GRCh38", "1", 111, "GENE1"))
        # A legitimate pseudoautosomal allele can have both X and Y placements in each
        # assembly. Neither locus may be selected arbitrarily as a build anchor.
        handle.write(_clinvar_row(2, 20, "GRCh37", "X", 202, "SHOX"))
        handle.write(_clinvar_row(2, 20, "GRCh37", "Y", 252, "SHOX"))
        handle.write(_clinvar_row(2, 20, "GRCh38", "X", 222, "SHOX"))
        handle.write(_clinvar_row(2, 20, "GRCh38", "Y", 272, "SHOX"))
        handle.write(_clinvar_row(3, 30, "GRCh37", "2", 303, "GENE3"))
        handle.write(_clinvar_row(3, 30, "GRCh38", "2", 333, "GENE3"))

    pairs = list(postprocess._clinvar_pairs(path))

    assert [rsid for rsid, _, _ in pairs] == ["rs10", "rs30"]
    assert pairs[0][1].gene == "GENE1|GENE1_ALIAS"


def test_anchor_selection_excludes_rsid_with_conflicting_allele_placements() -> None:
    candidates = [
        (
            "rs10",
            postprocess._AnchorSide("1", 101, "GENE1"),
            postprocess._AnchorSide("1", 111, "GENE1"),
        ),
        (
            "rs20",
            postprocess._AnchorSide("1", 202, "GENE2"),
            postprocess._AnchorSide("1", 222, "GENE2"),
        ),
        (
            "rs20",
            postprocess._AnchorSide("1", 202, "GENE2_ALIAS"),
            postprocess._AnchorSide("1", 222, "GENE2_ALIAS"),
        ),
        (
            "rs10",
            postprocess._AnchorSide("2", 303, "GENE1"),
            postprocess._AnchorSide("2", 333, "GENE1"),
        ),
        (
            "rs30",
            postprocess._AnchorSide("2", 404, "GENE3"),
            postprocess._AnchorSide("2", 444, "GENE3"),
        ),
    ]

    selected = postprocess._select_anchors(candidates, 2)

    assert [rsid for rsid, _, _ in selected] == ["rs20", "rs30"]


def test_clinvar_pairs_still_reject_allele_id_order_corruption(tmp_path: Path) -> None:
    path = tmp_path / "variant_summary.txt.gz"
    header = (
        "#AlleleID\tType\tGeneSymbol\tRS# (dbSNP)\tAssembly\tChromosome\t"
        "Start\tStop\tReferenceAllele\tAlternateAllele\t"
        "ReferenceAlleleVCF\tAlternateAlleleVCF\n"
    )
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(header)
        handle.write(_clinvar_row(2, 20, "GRCh37", "1", 202, "GENE2"))
        handle.write(_clinvar_row(2, 20, "GRCh38", "1", 222, "GENE2"))
        handle.write(_clinvar_row(1, 10, "GRCh37", "1", 101, "GENE1"))

    with pytest.raises(postprocess.ProcessError, match="AlleleID order changed"):
        list(postprocess._clinvar_pairs(path))


def test_chunk_checkpoint_resumes_without_rewriting_completed_rows(tmp_path: Path) -> None:
    input_path = tmp_path / "input.bin"
    input_path.write_bytes(b"stable public input")
    output = tmp_path / "output.parquet"
    schema: Mapping[str, postprocess.PolarsType] = {"value": pl.UInt32}

    def interrupted() -> Iterator[tuple[int]]:
        yield (1,)
        yield (2,)
        raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError, match="simulated"):
        postprocess._write_chunked_parquet(
            interrupted(),
            input_path=input_path,
            output=output,
            schema=schema,
            chunk_rows=2,
        )
    assert not output.exists()

    rows = postprocess._write_chunked_parquet(
        ((n,) for n in range(1, 6)),
        input_path=input_path,
        output=output,
        schema=schema,
        chunk_rows=2,
    )
    assert rows == 5
    assert pl.read_parquet(output).get_column("value").to_list() == [1, 2, 3, 4, 5]


def test_changed_provenance_discards_a_stale_checkpoint(tmp_path: Path) -> None:
    input_path = tmp_path / "input.bin"
    input_path.write_bytes(b"first public input")
    output = tmp_path / "output.parquet"
    schema: Mapping[str, postprocess.PolarsType] = {"value": pl.UInt32}

    def interrupted() -> Iterator[tuple[int]]:
        yield (1,)
        yield (2,)
        raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError):
        postprocess._write_chunked_parquet(
            interrupted(),
            input_path=input_path,
            output=output,
            schema=schema,
            chunk_rows=2,
            provenance={"input": "first"},
        )
    input_path.write_bytes(b"second public input")
    postprocess._write_chunked_parquet(
        ((9,),),
        input_path=input_path,
        output=output,
        schema=schema,
        chunk_rows=2,
        provenance={"input": "second"},
    )
    assert pl.read_parquet(output).get_column("value").to_list() == [9]


@pytest.mark.parametrize(
    "damage",
    ["unreadable-chunk", "wrong-row-count", "non-utf8-state", "missing-state"],
)
def test_corrupt_checkpoint_state_is_discarded_and_rebuilt(tmp_path: Path, damage: str) -> None:
    input_path = tmp_path / "input.bin"
    input_path.write_bytes(b"stable public input")
    output = tmp_path / "output.parquet"
    schema: Mapping[str, postprocess.PolarsType] = {"value": pl.UInt32}

    def interrupted() -> Iterator[tuple[int]]:
        yield (1,)
        yield (2,)
        raise RuntimeError("simulated interruption")

    with pytest.raises(RuntimeError):
        postprocess._write_chunked_parquet(
            interrupted(),
            input_path=input_path,
            output=output,
            schema=schema,
            chunk_rows=2,
        )
    staging = tmp_path / ".output.parquet.chunks"
    if damage == "unreadable-chunk":
        (staging / "part-00000000.parquet").write_bytes(b"not parquet")
    elif damage == "wrong-row-count":
        pl.DataFrame({"value": [1]}, schema=schema).write_parquet(staging / "part-00000000.parquet")
    elif damage == "non-utf8-state":
        (staging / "state.json").write_bytes(b"\xff\xfe")
    else:
        (staging / "state.json").unlink()

    rows = postprocess._write_chunked_parquet(
        ((n,) for n in range(1, 6)),
        input_path=input_path,
        output=output,
        schema=schema,
        chunk_rows=2,
    )

    assert rows == 5
    assert pl.read_parquet(output).get_column("value").to_list() == [1, 2, 3, 4, 5]
    assert not staging.exists()


def test_promoted_output_without_provenance_is_finalized_without_reparsing(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.bin"
    input_path.write_bytes(b"stable public input")
    output = tmp_path / "output.parquet"
    schema: Mapping[str, postprocess.PolarsType] = {"value": pl.UInt32}
    declared = manifest.PostProcess(
        step="extract_dbsnp_variant_index",
        params={"input": input_path.name, "output": output.name},
    )
    expected = postprocess._expected_provenance(declared, input_path, "a" * 64)
    postprocess._write_chunked_parquet(
        ((1,), (2,)),
        input_path=input_path,
        output=output,
        schema=schema,
        chunk_rows=1,
        provenance=expected,
        retain_staging=True,
    )
    assert output.is_file()
    assert not postprocess.provenance_path(output).exists()

    def must_not_reparse(_: Path) -> Iterator[tuple[int]]:
        raise AssertionError("completed input was reparsed")

    result = postprocess._run_parquet(
        declared,
        tmp_path,
        records=must_not_reparse,
        schema=schema,
        verify_only=False,
        progress=None,
        input_sha256="a" * 64,
    )

    assert result.status is ProcessStatus.CREATED
    assert "recovered" in result.detail
    assert pl.read_parquet(output).get_column("value").to_list() == [1, 2]
    postprocess.validate_provenance(output, expected=expected, actual_rows=2)
    assert not (tmp_path / ".output.parquet.chunks").exists()


def test_verify_requires_and_validates_post_process_outputs(tmp_path: Path) -> None:
    parsed = source(
        remote("dbsnp.vcf.gz")
        + """
    post_process:
      - step: extract_dbsnp_variant_index
        params:
          input: dbsnp.vcf.gz
          output: dbsnp_variants.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    (source_dir / "dbsnp.vcf.gz").write_bytes(b"payload")

    missing = postprocess.run(parsed, root=tmp_path, verify_only=True)
    assert missing[0].status is ProcessStatus.FAILED

    pl.DataFrame(schema=postprocess.VARIANT_INDEX_SCHEMA).write_parquet(
        source_dir / "dbsnp_variants.parquet"
    )
    verified = postprocess.run(parsed, root=tmp_path, verify_only=True)
    assert verified[0].status is ProcessStatus.FAILED
    assert "provenance" in verified[0].detail


def test_structurally_valid_but_stale_output_is_rebuilt(tmp_path: Path) -> None:
    parsed = source(
        remote("dbsnp.vcf.gz")
        + """
    post_process:
      - step: extract_dbsnp_variant_index
        params:
          input: dbsnp.vcf.gz
          output: dbsnp_variants.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()

    def write_vcf(position: int) -> None:
        with gzip.open(source_dir / "dbsnp.vcf.gz", "wt", encoding="ascii") as handle:
            handle.write("##fileformat=VCFv4.2\n")
            handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
            handle.write(f"NC_000001.10\t{position}\trs101\tA\tG\t.\t.\tRS=101\n")

    write_vcf(101)
    assert postprocess.run(parsed, root=tmp_path)[0].status is ProcessStatus.CREATED
    write_vcf(202)
    assert (
        postprocess.run(parsed, root=tmp_path, verify_only=True)[0].status is ProcessStatus.FAILED
    )
    rebuilt = postprocess.run(parsed, root=tmp_path)
    assert rebuilt[0].status is ProcessStatus.CREATED
    assert pl.read_parquet(source_dir / "dbsnp_variants.parquet")[0, "pos_grch37"] == 202


def test_verify_rejects_same_schema_and_height_output_mutation(tmp_path: Path) -> None:
    parsed = source(
        remote("dbsnp.vcf.gz")
        + """
    post_process:
      - step: extract_dbsnp_variant_index
        params:
          input: dbsnp.vcf.gz
          output: dbsnp_variants.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    with gzip.open(source_dir / "dbsnp.vcf.gz", "wt", encoding="ascii") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        handle.write("NC_000001.10\t101\trs101\tA\tG\t.\t.\tRS=101\n")
    assert postprocess.run(parsed, root=tmp_path)[0].status is ProcessStatus.CREATED

    output = source_dir / "dbsnp_variants.parquet"
    pl.read_parquet(output).with_columns(pos_grch37=pl.lit(202, dtype=pl.UInt32)).write_parquet(
        output
    )

    result = postprocess.run(parsed, root=tmp_path, verify_only=True)
    assert result[0].status is ProcessStatus.FAILED
    assert "output digest" in result[0].detail


def test_verify_rejects_tampered_provenance_row_count(tmp_path: Path) -> None:
    parsed = source(
        remote("dbsnp.vcf.gz")
        + """
    post_process:
      - step: extract_dbsnp_variant_index
        params:
          input: dbsnp.vcf.gz
          output: dbsnp_variants.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    with gzip.open(source_dir / "dbsnp.vcf.gz", "wt", encoding="ascii") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")
        handle.write("NC_000001.10\t101\trs101\tA\tG\t.\t.\tRS=101\n")
    assert postprocess.run(parsed, root=tmp_path)[0].status is ProcessStatus.CREATED

    output = source_dir / "dbsnp_variants.parquet"
    sidecar = postprocess.provenance_path(output)
    provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    provenance["rows"] = 2
    sidecar.write_text(json.dumps(provenance), encoding="utf-8")

    result = postprocess.run(parsed, root=tmp_path, verify_only=True)
    assert result[0].status is ProcessStatus.FAILED
    assert "but dbsnp_variants.parquet contains 1" in result[0].detail


def test_merge_split_failure_reuses_completed_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed = source(
        remote("refsnp-merged.json.bz2")
        + """
    post_process:
      - step: extract_rsid_merge_table
        params:
          input: refsnp-merged.json.bz2
          output: rsid_merges.parquet
          unresolvable_output: rsid_unresolvable.parquet
"""
    )
    source_dir = tmp_path / parsed.id
    source_dir.mkdir()
    input_path = source_dir / "refsnp-merged.json.bz2"
    with bz2.open(input_path, "wt", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"refsnp_id": "100", "merged_snapshot_data": {"merged_into": ["200"]}})
            + "\n"
        )
        handle.write(
            json.dumps({"refsnp_id": "300", "merged_snapshot_data": {"merged_into": []}}) + "\n"
        )

    output = source_dir / "rsid_merges.parquet"
    classified = source_dir / ".rsid_merges.parquet.classified.parquet"
    real_replace = os.replace

    def fail_first_output(source_path: str | Path, target_path: str | Path) -> None:
        if Path(target_path) == output:
            raise OSError("injected split promotion failure")
        real_replace(source_path, target_path)

    monkeypatch.setattr("genetics.refs.postprocess.os.replace", fail_first_output)
    failed = postprocess.run(parsed, root=tmp_path)
    assert failed[0].status is ProcessStatus.FAILED
    assert classified.is_file()
    postprocess.validate_provenance(classified, expected_step="extract_rsid_merge_table")

    monkeypatch.setattr("genetics.refs.postprocess.os.replace", real_replace)

    def must_not_reparse(_path: Path) -> Iterator[tuple[str, str, str | None, list[str]]]:
        raise AssertionError("completed classification should have been reused")

    monkeypatch.setattr(postprocess, "_merge_records", must_not_reparse)
    rerun = postprocess.run(parsed, root=tmp_path)

    assert rerun[0].status is ProcessStatus.CREATED
    assert not classified.exists()
    assert not postprocess.provenance_path(classified).exists()


@pytest.mark.parametrize("anchors", [[], [{"source": None}]])
def test_anchor_loader_rejects_empty_or_non_string_provenance(
    tmp_path: Path, anchors: list[dict[str, object]]
) -> None:
    path = tmp_path / "build_anchors.json"
    rows = anchors
    if anchors:
        rows = [
            {
                "rsid": "rs1",
                "chrom": "1",
                "pos_grch37": 10,
                "pos_grch38": 20,
                "gene": "SYNTH",
                **anchors[0],
            }
        ]
    path.write_text(json.dumps({"schema_version": 1, "anchors": rows}), encoding="utf-8")
    with pytest.raises(AnchorError):
        load_anchors(path)
