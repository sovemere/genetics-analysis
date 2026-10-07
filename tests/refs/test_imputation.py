"""M8.2 uses generated haplotypes only; it never reads a fetched individual's records."""

from __future__ import annotations

import gzip
import io
import json
import os
import random
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from genetics.external.beagle import Beagle, BeagleOptions, JavaRuntime, _job_lock
from genetics.paths import repo_root, tools_dir
from genetics.refs import imputation as mod
from genetics.refs import manifest, postprocess, tools
from genetics.refs.postprocess import ProcessError, ProcessStatus


def generated_vcf(chrom: str, *, haploid: bool = False) -> bytes:
    rng = random.Random(8202)
    base = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
    rows = ["##fileformat=VCFv4.2", "\t".join(base + [f"synthetic_{i}" for i in range(20)])]
    for i in range(200):
        alleles = [int(rng.random() < (0.2 + i % 5 * 0.1)) for _ in range(40)]
        ref, alt, info = "A", "G", "."
        if i == 1:
            ref, alt = "AC", "A"
        elif i == 2:
            alt, info = "<DEL>", "END=1005100"
        elif i == 3:
            alt = "G,T"
            alleles[0] = 2
        fields = [
            chrom,
            str(1000000 + i * 2500),
            f"rs{920000001 + i}",
            ref,
            alt,
            ".",
            "PASS",
            info,
            "GT",
        ]
        calls = [
            str(alleles[2 * j]) if haploid and j < 10 else f"{alleles[2 * j]}|{alleles[2 * j + 1]}"
            for j in range(20)
        ]
        rows.append("\t".join(fields + calls))
    return ("\n".join(rows) + "\n").encode()


def panel_source(root: Path, chromosomes: tuple[str, ...] = ("1", "X")) -> manifest.Source:
    files = []
    source_root = root / "synthetic_reference"
    source_root.mkdir(parents=True)
    for chrom in chromosomes:
        name = f"synthetic.chr{chrom}.full.vcf.gz"
        path = source_root / name
        path.write_bytes(gzip.compress(generated_vcf(chrom, haploid=chrom == "X"), mtime=0))
        files.append(
            manifest.RemoteFile(
                url=f"https://example.org/{name}", filename=name, sha256=postprocess._sha256(path)
            )
        )
    return manifest.Source(
        id="synthetic_reference",
        name="Generated full reference",
        tier=manifest.Tier.A,
        version="synthetic-8202",
        homepage="https://example.org/",
        license_id="CC0-1.0",
        files=tuple(files),
        post_process=(
            manifest.PostProcess(
                "convert_to_bref3",
                {
                    "output": "bref3/panel.bref3.json",
                    "chromosomes": list(chromosomes),
                    "memory_mb": 512,
                },
            ),
        ),
    )


def prepare(
    source: manifest.Source, root: Path, *, verify: bool = False
) -> postprocess.ProcessResult:
    return postprocess.run(source, root=root, verify_only=verify)[0]


def test_stream_retains_all_markers_alleles_samples_and_explicit_x_encoding() -> None:
    for chrom in ("1", "X"):
        output = io.BytesIO()
        original = mod._vcf_stream(
            io.BytesIO(generated_vcf(chrom, haploid=chrom == "X")), chrom, consume=output.write
        )
        decoded = mod._vcf_stream(io.BytesIO(output.getvalue()), chrom)
        assert original.records == 200 and original.samples == 20
        assert original.semantic_sha256 == decoded.semantic_sha256
        assert original.sample_order_sha256 == decoded.sample_order_sha256
        assert original.haploid_calls_doubled == (2000 if chrom == "X" else 0)
        assert b"<DEL>" in output.getvalue() and b"G,T" in output.getvalue()


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "unphased",
        "wrong-chrom",
        "unsorted",
        "wrong-count",
        "duplicate-header",
        "duplicate-sample",
        "no-gt",
        "empty",
        "build-header",
        "contig-length",
    ],
)
def test_invalid_reference_is_rejected_without_echoing_observations(change: str) -> None:
    lines = generated_vcf("1").splitlines()
    if change == "empty":
        lines = lines[:2]
    elif change == "build-header":
        lines.insert(1, b"##reference=GRCh38")
    elif change == "contig-length":
        lines.insert(1, b"##contig=<ID=1,length=248956422>")
    elif change == "duplicate-header":
        lines.insert(3, lines[1])
    elif change == "duplicate-sample":
        columns = lines[1].split(b"\t")
        columns[-1] = columns[-2]
        lines[1] = b"\t".join(columns)
    else:
        fields = lines[3].split(b"\t")
        if change == "missing":
            fields[-1] = b".|."
        elif change == "unphased":
            fields[-1] = fields[-1].replace(b"|", b"/")
        elif change == "wrong-chrom":
            fields[0] = b"2"
        elif change == "unsorted":
            fields[1] = b"2"
        elif change == "wrong-count":
            fields.pop()
        elif change == "no-gt":
            fields[8] = b"DS"
        lines[3] = b"\t".join(fields)
    with pytest.raises(ProcessError) as caught:
        mod._vcf_stream(io.BytesIO(b"\n".join(lines) + b"\n"), "1")
    assert "synthetic_" not in str(caught.value) and "|" not in str(caught.value)


@pytest.mark.parametrize("scope", [[], ["Y"], ["MT"], ["1", "1"], "1", [True]])
def test_invalid_chromosome_scope(scope: Any) -> None:
    with pytest.raises(ProcessError):
        mod._chromosomes({"chromosomes": scope})


def test_verify_pending_does_not_discover_java_or_create_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = panel_source(tmp_path)

    def forbidden() -> None:
        pytest.fail("read-only verification invoked Java discovery")

    monkeypatch.setattr(mod.BrefTools, "discover", forbidden)
    assert prepare(source, tmp_path, verify=True).status is ProcessStatus.PENDING
    assert not (tmp_path / source.id / "bref3").exists()


def map_source(root: Path, *, bad: str | None = None) -> manifest.Source:
    folder = root / "synthetic_reference"
    folder.mkdir(parents=True)
    archive = folder / "maps.zip"
    with zipfile.ZipFile(archive, "w") as out:
        for chrom in mod.MAP_KEYS:
            if bad == "missing" and chrom == "22":
                continue
            label = "X" if chrom.startswith("X") else chrom
            text = f"{label} generated_start 0 100\n{label} generated_end 1 200\n"
            if chrom == "1":
                text = {
                    "decreasing": f"{label} a 1 100\n{label} b 0 200\n",
                    "nan": f"{label} a nan 100\n",
                    "unsorted": f"{label} a 0 200\n{label} b 1 100\n",
                    "build": f"{label} a 0 999999999\n",
                    "label": "2 a 0 100\n",
                    "empty": "",
                }.get(bad or "", text)
            out.writestr(f"plink.chr{chrom}.GRCh37.map", text)
        out.writestr("../../never-extract", "ignored unrelated member")
    source = manifest.Source(
        id="synthetic_reference",
        name="Generated maps",
        tier=manifest.Tier.A,
        version="test",
        homepage="https://example.org/",
        license_id="CC0-1.0",
    )
    return replace(
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


def test_all_maps_preserved_bound_and_verified(tmp_path: Path) -> None:
    source = map_source(tmp_path)
    assert prepare(source, tmp_path).status is ProcessStatus.CREATED
    index = tmp_path / source.id / "maps/index.bref3.json"
    catalog = mod.validate_catalog(index)
    assert len(catalog["entries"]) == 25 and catalog["rows"] == 50
    assert prepare(source, tmp_path, verify=True).status is ProcessStatus.VERIFIED
    assert prepare(source, tmp_path).status is ProcessStatus.ALREADY_PRESENT
    with zipfile.ZipFile(tmp_path / source.id / "maps.zip") as archive:
        for entry in catalog["entries"]:
            assert (index.parent / entry["path"]).read_bytes() == archive.read(entry["path"])
    assert not (tmp_path / "never-extract").exists()
    (index.parent / catalog["entries"][0]["path"]).write_bytes(b"corrupted")
    assert prepare(source, tmp_path, verify=True).status is ProcessStatus.FAILED


@pytest.mark.parametrize(
    "bad", ["missing", "decreasing", "nan", "unsorted", "build", "label", "empty"]
)
def test_bad_maps_never_publish_completion(tmp_path: Path, bad: str) -> None:
    source = map_source(tmp_path, bad=bad)
    assert prepare(source, tmp_path).status is ProcessStatus.FAILED
    assert not (tmp_path / source.id / "maps/index.bref3.json").exists()


@pytest.mark.parametrize("field", ["records", "last_position", "last_cm"])
def test_map_counts_are_checked_against_actual_files(tmp_path: Path, field: str) -> None:
    source = map_source(tmp_path)
    assert prepare(source, tmp_path).status is ProcessStatus.CREATED
    index = tmp_path / source.id / "maps/index.bref3.json"
    provenance = postprocess.validate_provenance(index)
    catalog = json.loads(index.read_bytes())
    catalog["entries"][0][field] += 1
    catalog["rows"] = sum(e["records"] for e in catalog["entries"])
    mod._write_json(index, catalog)
    postprocess._write_provenance(index, provenance, catalog["rows"])
    assert prepare(source, tmp_path, verify=True).status is ProcessStatus.FAILED


def test_preparation_cancellation_releases_child_and_lock(
    tmp_path: Path, native_preparer: mod.BrefTools
) -> None:
    source = panel_source(tmp_path, ("1",))
    seen = 0

    def cancel(event: postprocess.ProcessProgressEvent) -> None:
        nonlocal seen
        seen += 1
        if seen == 2:
            raise InterruptedError("synthetic cancellation")

    assert postprocess.run(source, root=tmp_path, progress=cancel)[0].status is ProcessStatus.FAILED
    assert not (tmp_path / source.id / "bref3/chr1.bref3-work/complete").exists()
    assert prepare(source, tmp_path).status is ProcessStatus.CREATED


def test_committed_full_panel_and_map_contract() -> None:
    full = manifest.load().get("thousand_genomes_phase3_grch37")
    step = next(p for p in full.post_process if p.step == "convert_to_bref3")
    assert mod._chromosomes(step.params) == mod.SUPPORTED
    assert postprocess.get(step.step).implemented
    maps = manifest.load().get("hapmap_genetic_maps_grch37")
    assert maps.files[0].sha256 and maps.files[0].size_bytes == 23913120
    assert maps.license.authoritative and maps.license.review_status == "confirmed"


def test_declared_panel_provenance_needs_only_manifest_and_lock() -> None:
    expected = postprocess.declared_artifact_provenance(
        "thousand_genomes_phase3_grch37", "convert_to_bref3"
    )
    assert len(expected["inputs"]) == 23
    assert [i["chromosome"] for i in expected["inputs"]] == list(mod.SUPPORTED)
    assert (
        expected["source_version"] == manifest.load().get("thousand_genomes_phase3_grch37").version
    )
    maps = postprocess.declared_artifact_provenance(
        "hapmap_genetic_maps_grch37", "prepare_genetic_maps"
    )
    assert maps["source_version"] == "2013-06-08" and maps["build"] == "GRCh37"


@pytest.mark.parametrize("change", ["version", "url", "missing"])
def test_default_contract_rejects_stale_reference_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from genetics.refs import lock as lockfile

    source = panel_source(tmp_path, ("1",))
    lock_path = tmp_path / "manifest.lock"
    item = source.files[0]
    record = lockfile.LockedFile(
        url=item.url if change != "url" else "https://example.org/other",
        sha256=item.sha256 or "0" * 64,
        size_bytes=(tmp_path / source.id / item.filename).stat().st_size,
        first_seen="2026-10-07",
    )
    locked = lockfile.LockedSource(
        version=source.version if change != "version" else "wrong",
        license_id=source.license_id,
        files={item.filename: record} if change != "missing" else {},
    )
    lockfile.write(lock_path, lockfile.Lock(sources={source.id: locked}))
    monkeypatch.setattr("genetics.paths.reference_lock", lambda: lock_path)
    with pytest.raises(ProcessError):
        mod.declared_panel_provenance(source, source.post_process[0])


@pytest.mark.privacy
def test_new_reference_outputs_ignored_even_under_knowledge_allowlist() -> None:
    for prefix in ("arbitrary", "knowledge/traits/arbitrary"):
        for suffix in (
            ".bref3",
            ".bref3.json",
            ".bref3.json.provenance.json",
            ".bref3.json.tmp",
            ".bref3.json.provenance.json.tmp",
            ".bref3-work/attempt-x/arbitrary.json",
        ):
            assert (
                subprocess.run(
                    ["git", "check-ignore", "-q", prefix + suffix], cwd=repo_root(), check=False
                ).returncode
                == 0
            )


def test_native_pinned_full_roundtrip_resume_and_beagle_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = os.environ.get("GENETICS_BEAGLE_TEST_TOOLS")
    if installed is None:
        pytest.skip("set GENETICS_BEAGLE_TEST_TOOLS for native bref3 acceptance")
    native = mod.BrefTools.discover(Path(installed))
    monkeypatch.setattr(mod.BrefTools, "discover", lambda: native)
    source = panel_source(tmp_path)
    before = [postprocess._sha256(tmp_path / source.id / f.filename) for f in source.files]
    assert prepare(source, tmp_path).status is ProcessStatus.CREATED
    index = tmp_path / source.id / "bref3/panel.bref3.json"
    catalog = mod.validate_catalog(index)
    assert catalog["rows"] == 400
    assert catalog["entries"][1]["summary"]["haploid_calls_doubled"] == 2000
    assert prepare(source, tmp_path, verify=True).status is ProcessStatus.VERIFIED
    index.unlink()  # A lost catalog recovers from completely validated chromosome checkpoints.
    monkeypatch.setattr(
        mod.BrefTools, "convert", lambda *args: pytest.fail("completed chromosome rerun")
    )
    assert prepare(source, tmp_path).status is ProcessStatus.CREATED
    assert [postprocess._sha256(tmp_path / source.id / f.filename) for f in source.files] == before
    panel = index.parent / catalog["entries"][0]["path"]
    target = tmp_path / "target.vcf"
    lines = generated_vcf("1").splitlines()
    target.write_bytes(
        b"\n".join(
            [
                lines[0],
                b"\t".join(lines[1].split(b"\t")[:10]),
                *[
                    b"\t".join(line.split(b"\t")[:10]).replace(b"|", b"/")
                    for i, line in enumerate(lines[2:])
                    if i % 2 == 0
                ],
            ]
        )
        + b"\n"
    )
    genetic_map = tmp_path / "synthetic-map.tmp"
    genetic_map.write_text("1 generated_start 0 1000000\n1 generated_end 1 1500000\n")
    result = Beagle.discover(tools_root=Path(installed)).run(
        gt=target,
        ref=panel,
        genetic_map=genetic_map,
        out=tmp_path / "imputed",
        options=BeagleOptions(memory_mb=512, nthreads=2),
    )
    with gzip.open(result.vcf, "rb") as handle:
        rows = [line for line in handle if not line.startswith(b"#")]
    assert len(rows) == 200 and sum(b"IMP" in r.split(b"\t")[7] for r in rows) == 100
    panel.write_bytes(b"corrupted binary")
    assert prepare(source, tmp_path, verify=True).status is ProcessStatus.FAILED
    assert prepare(source, tmp_path).status is ProcessStatus.FAILED


@pytest.fixture
def native_preparer(monkeypatch: pytest.MonkeyPatch) -> mod.BrefTools:
    installed = os.environ.get("GENETICS_BEAGLE_TEST_TOOLS")
    if installed is None:
        pytest.skip("set GENETICS_BEAGLE_TEST_TOOLS for native bref3 acceptance")
    native = mod.BrefTools.discover(Path(installed))
    monkeypatch.setattr(mod.BrefTools, "discover", lambda: native)
    return native


def test_interruption_reuses_completed_chromosomes_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_preparer: mod.BrefTools
) -> None:
    source = panel_source(tmp_path)
    index = tmp_path / source.id / "bref3/panel.bref3.json"

    def interrupt(event: postprocess.ProcessProgressEvent) -> None:
        if event.step == "convert_to_bref3 chrX":
            raise InterruptedError("synthetic interruption")

    result = postprocess.run(source, root=tmp_path, progress=interrupt)[0]
    assert result.status is ProcessStatus.FAILED
    assert (index.parent / "chr1.bref3-work/complete").is_dir()
    assert not (index.parent / "chrX.bref3-work/complete").exists()
    assert not index.exists()
    real = mod.BrefTools.convert
    calls: list[str] = []

    def counting(
        self: mod.BrefTools,
        source: Path,
        destination: Path,
        chrom: str,
        memory_mb: int,
        progress: Any = None,
    ) -> mod.VcfSummary:
        calls.append(chrom)
        return real(self, source, destination, chrom, memory_mb, progress)

    monkeypatch.setattr(mod.BrefTools, "convert", counting)
    assert prepare(source, tmp_path).status is ProcessStatus.CREATED
    assert calls == ["X"]


@pytest.mark.parametrize(
    "change",
    [
        "rows",
        "sample-count",
        "scope",
        "policy",
        "par",
        "companions",
        "summary-bool",
        "checkpoint",
        "runtime",
        "pin",
    ],
)
def test_digest_consistent_malformed_catalog_is_rejected(
    tmp_path: Path, native_preparer: mod.BrefTools, change: str
) -> None:
    source = panel_source(tmp_path, ("1",))
    assert prepare(source, tmp_path).status is ProcessStatus.CREATED
    index = tmp_path / source.id / "bref3/panel.bref3.json"
    catalog = json.loads(index.read_bytes())
    provenance = postprocess.validate_provenance(index)
    if change == "rows":
        catalog["rows"] += 1
    elif change == "sample-count":
        catalog["entries"][0]["summary"]["samples"] = 0
    elif change == "summary-bool":
        catalog["entries"][0]["summary"]["records"] = True
    elif change == "scope":
        catalog["chromosomes"] = ["2"]
    elif change == "policy":
        catalog["policy"]["variant_filter"] = "array-only"
    elif change == "par":
        catalog["par_grch37"] = []
    elif change == "companions":
        catalog["files"] = catalog["files"][:1]
    else:
        checkpoint_record = catalog["files"][1]
        checkpoint_path = index.parent / checkpoint_record["path"]
        checkpoint = json.loads(checkpoint_path.read_bytes())
        if change == "checkpoint":
            checkpoint["round_trip_verified"] = False
        elif change == "runtime":
            checkpoint["identity"]["tools"]["java"]["executable_sha256"] = "invalid"
        elif change == "pin":
            checkpoint["identity"]["tools"]["bref3"]["version"] = "other-release"
        mod._write_json(checkpoint_path, checkpoint)
        catalog["files"][1] = mod._file_record(checkpoint_path, index.parent)
    mod._write_json(index, catalog)
    postprocess._write_provenance(index, provenance, catalog["rows"])
    assert prepare(source, tmp_path, verify=True).status is ProcessStatus.FAILED


def test_concurrent_preparation_refused(tmp_path: Path, native_preparer: mod.BrefTools) -> None:
    source = panel_source(tmp_path, ("1",))
    folder = tmp_path / source.id / "bref3"
    folder.mkdir()
    with _job_lock(folder / "panel.bref3.json.beagle.lock"):
        refused = prepare(source, tmp_path)
        assert refused.status is ProcessStatus.FAILED and "in use" in refused.detail
    assert prepare(source, tmp_path).status is ProcessStatus.CREATED


def test_old_java_has_actionable_preparation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(JavaRuntime, "discover", lambda: JavaRuntime(Path("java"), "1.8.0_491", 8))
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    known = {
        tools.installed_path(tools_dir(), t, t.builds[0]): t.builds[0].sha256
        for t in tools.load().tools
        if t.id in {"bref3", "unbref3"}
    }
    monkeypatch.setattr(mod, "_sha256", lambda p: known[p])
    with pytest.raises(ProcessError, match="Java 11"):
        mod.BrefTools.discover()
