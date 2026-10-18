"""Optional actual R/HIBAG scientific acceptance; never install or fetch from tests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from genetics.external import hibag
from genetics.hla import calling, models, selection
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.refs import postprocess


def native() -> hibag.HIBAGRuntime:
    found = (
        os.environ.get("GENETICS_HIBAG_TEST_RSCRIPT")
        or os.environ.get("GENETICS_RSCRIPT")
        or shutil.which("Rscript")
    )
    if found is None:
        pytest.skip("User-installed Rscript unavailable for native HLA imputation acceptance")
    state = hibag.probe(Path(found))
    if state.status == "hibag-missing":
        pytest.skip("HIBAG unavailable for native HLA imputation acceptance")
    assert state.status == "ready", state.detail
    return hibag.HIBAGRuntime.from_readiness(state)


def synthetic_table(reference: dict[str, Any]) -> GenotypeTable:
    import random

    rng = random.Random(112)
    rows = {}
    for model in reference["loci"].values():
        for marker in model["markers"]:
            first, _ = models.orientation(marker, reference)
            if first is None:
                continue
            pair = marker["alleles"]
            if first != pair[0]:
                pair = [a.translate(models.COMPLEMENT) for a in pair]
            bases = sorted(rng.choices(pair, weights=[0.5, 0.5], k=2))
            rows[marker["position"]] = {
                "rsid": marker["rsid"],
                "chrom": "6",
                "pos_grch37": marker["position"],
                "a1": bases[0],
                "a2": bases[1],
                "genotype": "".join(bases),
                "call_status": "called",
            }
    return GenotypeTable(
        pl.DataFrame(list(rows.values()), schema=NORMALIZED_SCHEMA), vendor="synthetic"
    )


def test_native_synthetic_classifier_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = native()
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "private"))
    # Training genomes are generated in R from fixed-seed synthetic frequencies;
    # no example HapMap or other person's genotypes are loaded.
    training = r"""
set.seed(112)
ids <- paste0("synthetic-", seq_len(60L))
g <- matrix(stats::rbinom(8L*60L, 2L, 0.5), nrow=8L)
pos <- 30000000L + seq_len(8L)
geno <- HIBAG::hlaMakeSNPGeno(g, ids, paste0("rs", 1100000L+seq_len(8L)),
    pos, rep("A",8L), rep("G",8L), assembly="hg19")
models <- list()
for (gene in c("A","B","C","DRB1","DQA1","DQB1","DPB1")) {
    h <- HIBAG::hlaAllele(ids, ifelse(g[1L,] >= 1L, "01:01", "02:01"),
        ifelse(g[1L,] == 2L, "01:01", "02:01"), locus=gene, assembly="hg19")
    m <- HIBAG::hlaAttrBagging(h, geno, nclassifier=4L, verbose=FALSE)
    models[[gene]] <- HIBAG::hlaModelToObj(m)
    HIBAG::hlaClose(m)
}
save(models, file="synthetic.RData")
"""
    directory = models.run_r(runtime, training, [], timeout=1200, cancel=None)
    path = directory / "synthetic.RData"
    from genetics.hla import scripts

    inspected = models.run_r(runtime, scripts.INSPECT, [str(path)], timeout=300, cancel=None)
    loci = models.metadata(inspected)
    _, source = models.source_identity("european")
    source.update(sha256=models.file_hash(path), size_bytes=path.stat().st_size)
    variants = {
        s["position"]: {
            "rsid": s["rsid"],
            "chrom": "6",
            "pos_grch37": s["position"],
            "ref": "A",
            "alts": ["G"],
        }
        for m in loci.values()
        for s in m["markers"]
    }
    reference = {
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
            "variants": list(variants.values()),
        },
        "panel": {
            "provenance": {
                "source": models.PANEL,
                "version": "20130502",
                "filename": "ALL.chr6.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz",
                "sha256": "d" * 64,
            },
            "variants": [],
        },
    }
    choice = selection.select(None, requested="european")
    record = calling.impute(
        synthetic_table(reference), path, reference, runtime, choice=choice, timeout=1200
    )
    calling.validate(record)
    assert set(record["genes"]) == set(models.LOCI)
    assert all(g["status"] == "predicted" for g in record["genes"].values())
    empty = GenotypeTable(pl.DataFrame(schema=NORMALIZED_SCHEMA), vendor="synthetic")
    missing = calling.impute(empty, path, reference, runtime, choice=choice, timeout=1200)
    assert all(g["status"] == "no-markers" for g in missing["genes"].values())


@pytest.mark.parametrize("population", models.POPULATIONS)
def test_native_published_classifier(
    population: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = native()
    root = os.environ.get("GENETICS_HIBAG_TEST_REFERENCES")
    if not root:
        pytest.skip("Explicit verified public HIBAG/dbSNP reference root not configured")
    monkeypatch.setattr(models, "references_dir", lambda: Path(root))
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "private"))
    path, reference = models.prepare(population, runtime, opt_in=True, timeout=3600)
    choice = selection.select(None, requested=population)
    result = calling.impute(synthetic_table(reference), path, reference, runtime, choice=choice)
    calling.validate(result)
    assert result["status"] == "completed"
    assert any(g["status"] == "predicted" for g in result["genes"].values())
