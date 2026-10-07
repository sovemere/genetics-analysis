"""Fixed-seed synthetic native imputation inputs shared by execution acceptance tests."""

from __future__ import annotations

import gzip
import random
import zipfile
from dataclasses import replace
from pathlib import Path

import polars as pl

from genetics.imputation import PreparedReference
from genetics.ingest.normalize import GRCH37_LENGTHS
from genetics.ingest.schema import NORMALIZED_SCHEMA, Chrom, GenotypeTable
from genetics.refs import manifest, postprocess
from genetics.refs.imputation import MAP_KEYS, BrefTools


def _table(rows: list[tuple[str, int, str | None, str]]) -> GenotypeTable:
    return GenotypeTable(
        pl.DataFrame(
            [
                (f"synthetic_probe_{i}", c, p, g[0] if g else None, g[1] if g else None, g, s)
                for i, (c, p, g, s) in enumerate(rows)
            ],
            schema=NORMALIZED_SCHEMA,
            orient="row",
        ),
        vendor="synthetic",
    )


def native_reference(
    root: Path, native: BrefTools
) -> tuple[PreparedReference, GenotypeTable, GenotypeTable]:
    """Seeded reference frequencies; no real reference individual or export."""
    rng = random.Random(8303)
    source_root = root / "synthetic_reference"
    source_root.mkdir(parents=True)
    files = []
    male_rows: list[tuple[str, int, str | None, str]] = []
    female_rows: list[tuple[str, int, str | None, str]] = []
    header = (
        "##fileformat=VCFv4.2\n##reference=GRCh37\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t"
        + "\t".join(f"synthetic_{i}" for i in range(20))
        + "\n"
    )
    for chrom, starts in (("1", [1000000]), ("X", [1000000, 3000000, 154940000])):
        lines = [header]
        for start in starts:
            for i in range(200):
                pos = start + i * 1000
                haplotypes = [int(rng.random() < (0.15 + i % 7 * 0.1)) for _ in range(44)]
                ref, alt = "A", "G"
                if i == 1:
                    ref, alt = "AC", "A"
                elif i == 3:
                    alt = "G,T"
                    haplotypes[0] = 2
                reference_calls = [
                    f"{haplotypes[2 * j]}|{haplotypes[2 * j + 1]}" for j in range(20)
                ]
                nonpar = chrom == "X" and start == 3000000
                if nonpar:
                    reference_calls[:10] = [str(haplotypes[2 * j]) for j in range(10)]
                lines.append(
                    f"{chrom}\t{pos}\t.\t{ref}\t{alt}\t.\tPASS\t.\tGT\t"
                    + "\t".join(reference_calls)
                    + "\n"
                )
                if i % 2 == 0:
                    male_gt = "".join(
                        "AG"[h] for h in ([haplotypes[40]] * 2 if nonpar else haplotypes[40:42])
                    )
                    female_gt = "".join(sorted("AG"[h] for h in haplotypes[42:44]))
                    male_gt = "".join(sorted(male_gt))
                    # A sporadic no-call tests source/quality after phase completion.
                    male_rows.append(
                        (
                            chrom,
                            pos,
                            None if i == 2 else male_gt,
                            "no_call" if i == 2 else ("hemizygous" if nonpar else "called"),
                        )
                    )
                    female_rows.append(
                        (
                            chrom,
                            pos,
                            None if i == 2 else female_gt,
                            "no_call" if i == 2 else "called",
                        )
                    )
        path = source_root / f"synthetic.chr{chrom}.vcf.gz"
        path.write_bytes(gzip.compress("".join(lines).encode(), mtime=0))
        files.append(
            manifest.RemoteFile(
                url=f"https://example.org/{path.name}",
                filename=path.name,
                sha256=postprocess._sha256(path),
            )
        )
    source = manifest.Source(
        id="synthetic_reference",
        name="Synthetic full reference",
        tier=manifest.Tier.A,
        version="seed-8303",
        homepage="https://example.org",
        license_id="CC0-1.0",
        files=tuple(files),
        post_process=(
            manifest.PostProcess(
                "convert_to_bref3",
                {"output": "bref3/panel.bref3.json", "chromosomes": ["1", "X"], "memory_mb": 512},
            ),
        ),
    )
    result = postprocess.run(source, root=root)[0]
    assert result.status is postprocess.ProcessStatus.CREATED, result
    archive = source_root / "maps.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        for key in MAP_KEYS:
            label = "X" if key.startswith("X") else key
            zip_file.writestr(
                f"plink.chr{key}.GRCh37.map",
                f"{label} . 0 1\n{label} . 10 {GRCH37_LENGTHS[Chrom(label)]}\n",
            )
    map_source = replace(
        source,
        files=(
            manifest.RemoteFile(
                url="https://example.org/maps.zip",
                filename="maps.zip",
                sha256=postprocess._sha256(archive),
            ),
        ),
        post_process=(
            manifest.PostProcess(
                "prepare_genetic_maps", {"input": "maps.zip", "output": "maps/index.bref3.json"}
            ),
        ),
    )
    assert postprocess.run(map_source, root=root)[0].status is postprocess.ProcessStatus.CREATED
    reference = PreparedReference(
        source_root / "bref3/panel.bref3.json", source_root / "maps/index.bref3.json"
    )
    return reference, _table(male_rows), _table(female_rows)
