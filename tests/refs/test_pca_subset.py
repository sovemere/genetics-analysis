"""The LD-pruned PCA marker subset (roadmap M5.3, ``build_pca_marker_subset``).

**The transform's body is PLINK invocations, and CI installs no PLINK**, so what runs here
is a stand-in that reads the flags it is given and writes filesets shaped like the ones the
real binary writes. That is enough to hold the orchestration to account -- which commands,
in which order, with which flags, resumed how -- and it is deliberately not a claim about
what PLINK does with them.

The real pipeline was run by hand against the pinned build while this was written, over a
synthetic 22-chromosome, 60-sample panel: 5,720 markers in, 971 out, the artifact accepted
by ``--pca ... allele-wts`` and read back by M5.2's panel reader with no adapter. The
numbers in the progress log come from that run, not from the stub.

Everything that is *not* a PLINK call -- settings resolution, input selection, the digest
over 22 files, the exclusion regions, provenance and its staleness rules -- is tested
directly, because that is where the decisions live.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from genetics.refs import manifest, postprocess
from genetics.refs.postprocess import ProcessStatus

OUTPUT = "pca_markers_ldpruned.pgen"

# ---------------------------------------------------------------------------
# A PLINK 2 that writes filesets without doing any genetics
# ---------------------------------------------------------------------------

PLINK_STUB = """
import os
import sys
from pathlib import Path

argv = sys.argv[1:]

if "--version" in argv:
    print("PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)")
    raise SystemExit(0)

out = str(Path(argv[argv.index("--out") + 1]))
Path(out).parent.mkdir(parents=True, exist_ok=True)
log = Path(os.environ["STUB_LOG"])
with log.open("a", encoding="utf-8") as handle:
    handle.write("|".join(argv) + "\\n")

if os.environ.get("STUB_FAIL_ON") and os.environ["STUB_FAIL_ON"] in " ".join(argv):
    sys.stderr.write("Error: the stub was told to fail here.\\n")
    raise SystemExit(8)


def variants(prefix):
    text = Path(str(prefix) + ".pvar").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def write(prefix, rows):
    Path(prefix + ".pvar").write_text(
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\n" + "".join(row + "\\n" for row in rows), encoding="utf-8"
    )
    Path(prefix + ".psam").write_text("#IID\\tSEX\\nSAMPLE0\\tNA\\nSAMPLE1\\tNA\\n", encoding="utf-8")
    Path(prefix + ".pgen").write_bytes(b"pgen-stub-" + str(len(rows)).encode())


if "--indep-pairwise" in argv:
    rows = variants(argv[argv.index("--pfile") + 1])
    # Thin by half, deterministically: enough for "pruning removed markers" to be visible.
    # STUB_PRUNE_KEEP=0 prunes everything, which is how the empty-result path is reached.
    kept = [] if os.environ.get("STUB_PRUNE_KEEP") == "0" else rows[::2]
    Path(out + ".prune.in").write_text(
        "".join(row.split("\\t")[2] + "\\n" for row in kept), encoding="utf-8"
    )
elif "--pmerge-list" in argv:
    listing = Path(argv[argv.index("--pmerge-list") + 1]).read_text(encoding="utf-8").split()
    merged = []
    for prefix in listing:
        merged.extend(variants(prefix))
    write(out, merged)
elif "--extract" in argv:
    keep = set(Path(argv[argv.index("--extract") + 1]).read_text(encoding="utf-8").split())
    rows = variants(argv[argv.index("--pfile") + 1])
    write(out, [row for row in rows if row.split("\\t")[2] in keep])
elif "--vcf" in argv:
    chrom = argv[argv.index("--chr") + 1]
    count = int(os.environ.get("STUB_VARIANTS", "8"))
    write(out, [f"{chrom}\\t{1000 * (i + 1)}\\trs{chrom}_{i}\\tA\\tG" for i in range(count)])
"""


@pytest.fixture
def plink(
    installed_plink2: Callable[[str], Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """The stub, installed, with its command log pointed somewhere the test can read."""
    log = tmp_path / "commands.log"
    monkeypatch.setenv("STUB_LOG", str(log))
    installed_plink2(PLINK_STUB)
    return log


def commands(log: Path) -> list[list[str]]:
    if not log.is_file():
        return []
    return [line.split("|") for line in log.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _source(files: list[str], params: str = "") -> manifest.Source:
    entries = "\n".join(
        f"      - url: https://example.org/{name}\n"
        f"        filename: {name}\n"
        f"        sha256: {'a' * 64}\n"
        "        size_bytes: 1000000"
        for name in files
    )
    param_block = f"\n{params}" if params else ""
    return manifest.loads(
        f"""
schema_version: 1
sources:
  - id: synthetic_panel
    name: Synthetic panel
    tier: A
    version: test
    homepage: https://example.org/
    license: CC0-1.0
    post_process:
      - step: build_pca_marker_subset
        params:
          output: {OUTPUT}{param_block}
    files:
{entries}
"""
    ).get("synthetic_panel")


def _chrom_file(chrom: str) -> str:
    return f"ALL.chr{chrom}.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz"


def _payloads(root: Path, files: list[str]) -> Path:
    """Write placeholder payloads. The stub never reads them; only their digests matter."""
    directory = root / "synthetic_panel"
    directory.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(files):
        with gzip.open(directory / name, "wt", encoding="utf-8") as handle:
            handle.write(f"##placeholder {index}\n")
    return directory


def _run(source: manifest.Source, root: Path, **kwargs: object) -> postprocess.ProcessResult:
    results = postprocess.run(source, root=root, **kwargs)  # type: ignore[arg-type]
    return results[0]


def _provenance(directory: Path) -> dict[str, object]:
    payload = json.loads((directory / f"{OUTPUT}.provenance.json").read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_an_artifact_from_an_older_transform_version_is_rebuilt(
    tmp_path: Path, plink: Path
) -> None:
    """The bump is the only thing that invalidates an artifact when the *code* changes
    rather than its inputs or settings, and until now nothing exercised it.

    It matters concretely: version 2 synthesises variant IDs, and every subset built before
    it carries `.` for every marker -- unusable by `--indep-pairwise` and silently useless
    to M5.4's `--score`. An artifact that stale must not be reported as current.
    """
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)
    _run(_source(files), tmp_path)

    sidecar = directory / f"{OUTPUT}.provenance.json"
    recorded = json.loads(sidecar.read_text(encoding="utf-8"))
    assert recorded["transform_version"] == 2
    recorded["transform_version"] = 1
    sidecar.write_text(json.dumps(recorded), encoding="utf-8")

    before = len([c for c in commands(plink) if "--vcf" in c])
    result = _run(_source(files), tmp_path)
    after = len([c for c in commands(plink) if "--vcf" in c])

    assert result.status is ProcessStatus.CREATED
    assert after > before, "a stale version must rebuild, not be reported as present"


def test_the_effective_settings_are_recorded_not_left_implicit(tmp_path: Path, plink: Path) -> None:
    """A default that changed would otherwise leave every existing artifact looking current.

    ``transform_version`` alone cannot carry this: it is bumped by hand, and this is an
    artifact somebody waits hours for and will not rebuild on a hunch.
    """
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    settings = _provenance(directory)["settings"]
    assert isinstance(settings, dict)
    assert settings["maf"] == 0.05
    assert settings["window"] == "200kb"
    assert settings["r2"] == 0.2
    assert settings["long_range_ld_excluded"] == [
        "2:135000000-137000000",
        "6:25000000-35000000",
        "8:8000000-12000000",
        "17:40000000-45000000",
    ]


def test_a_manifest_override_reaches_plink_and_the_sidecar(tmp_path: Path, plink: Path) -> None:
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)

    _run(_source(files, params="          r2: 0.1\n          maf: 0.01"), tmp_path)

    prune = next(c for c in commands(plink) if "--indep-pairwise" in c)
    convert = next(c for c in commands(plink) if "--vcf" in c)
    assert prune[prune.index("--indep-pairwise") + 3] == "0.1"
    assert convert[convert.index("--maf") + 1] == "0.01"
    settings = _provenance(directory)["settings"]
    assert isinstance(settings, dict)
    assert settings["r2"] == 0.1


@pytest.mark.parametrize(
    ("param", "value"),
    [("maf", "0.6"), ("r2", "0"), ("r2", "1.5"), ("step", "0"), ("max_missing", "2")],
)
def test_an_impossible_setting_is_refused_before_anything_runs(
    tmp_path: Path, plink: Path, param: str, value: str
) -> None:
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)

    result = _run(_source(files, params=f"          {param}: {value}"), tmp_path)

    assert result.status is ProcessStatus.FAILED
    assert param in result.detail
    assert commands(plink) == []


# ---------------------------------------------------------------------------
# Which files are the input
# ---------------------------------------------------------------------------


def test_only_the_autosomes_are_read(tmp_path: Path, plink: Path) -> None:
    """X, Y and MT carry ploidy PLINK refuses without sex information, and the sample panel
    is a TSV of population labels rather than genotypes."""
    files = [
        _chrom_file("1"),
        _chrom_file("22"),
        _chrom_file("X"),
        _chrom_file("Y"),
        _chrom_file("MT"),
        "integrated_call_samples_v3.20130502.ALL.panel",
    ]
    _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    read = [c[c.index("--vcf") + 1] for c in commands(plink) if "--vcf" in c]
    assert [Path(p).name for p in read] == [_chrom_file("1"), _chrom_file("22")]


def test_chromosomes_are_processed_in_numeric_order(tmp_path: Path, plink: Path) -> None:
    """Listed 10 before 2, they must still be merged in order: ``--pmerge-list`` requires
    position-sorted inputs, and a filename sorts lexically."""
    files = [_chrom_file("10"), _chrom_file("2"), _chrom_file("1")]
    _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    seen = [c[c.index("--chr") + 1] for c in commands(plink) if "--chr" in c]
    assert seen == ["1", "2", "10"]


def test_each_conversion_asserts_the_chromosome_its_filename_claims(
    tmp_path: Path, plink: Path
) -> None:
    """The cross-check that makes reading the chromosome off the name safe: a file whose
    contents disagree yields no variants rather than the wrong chromosome's markers."""
    files = [_chrom_file("7")]
    _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    convert = next(c for c in commands(plink) if "--vcf" in c)
    assert convert[convert.index("--chr") + 1] == "7"
    assert Path(convert[convert.index("--vcf") + 1]).name == _chrom_file("7")


def test_a_missing_payload_says_to_fetch_rather_than_failing_inside_plink(
    tmp_path: Path, plink: Path
) -> None:
    files = [_chrom_file("1"), _chrom_file("2")]
    directory = _payloads(tmp_path, files)
    (directory / _chrom_file("2")).unlink()

    result = _run(_source(files), tmp_path)

    assert result.status is ProcessStatus.FAILED
    assert "fetch this source first" in result.detail
    assert commands(plink) == []


def test_a_source_with_no_autosomal_file_fails_clearly(tmp_path: Path, plink: Path) -> None:
    files = ["integrated_call_samples_v3.20130502.ALL.panel"]
    _payloads(tmp_path, files)

    result = _run(_source(files), tmp_path)

    assert result.status is ProcessStatus.FAILED
    assert "no per-autosome genotype VCF" in result.detail


def test_the_input_digest_covers_every_chromosome(tmp_path: Path, plink: Path) -> None:
    """One chromosome re-released must invalidate the whole artifact, not two thirds of it."""
    files = [_chrom_file("1"), _chrom_file("2")]
    directory = _payloads(tmp_path, files)
    _run(_source(files), tmp_path)
    before = _provenance(directory)["input"]

    with gzip.open(directory / _chrom_file("2"), "wt", encoding="utf-8") as handle:
        handle.write("##a different release\n")
    stale = _run(_source(files), tmp_path, verify_only=True)

    assert isinstance(before, dict)
    assert before["filename"] == "2 autosomal genotype VCFs"
    assert stale.status is ProcessStatus.FAILED
    assert "stale" in stale.detail


# ---------------------------------------------------------------------------
# Variant IDs
# ---------------------------------------------------------------------------


def test_every_conversion_synthesises_variant_ids_from_the_site(
    tmp_path: Path, plink: Path
) -> None:
    """**1000 Genomes phase 3 ships no variant IDs.** Not "some are missing" -- a full scan
    of the real chromosome 1 VCF found zero non-`.` IDs in any record, and all 530,434
    markers surviving this step's filters carried `.` likewise. Two later steps need them
    and only one complains: `--indep-pairwise`
    refuses a non-unique set outright (exit 7, which is how this was found), while M5.4's
    `--score` joins the sample to the reference weights *by ID* and would match nothing at
    all.

    chrom:pos:ref:alt is unique by construction for the biallelic ACGT SNPs kept here, and
    M5.2's harmonizer copies `panel_id` into the sample's VCF, so both sides of that join
    carry the same synthesised IDs without anything having to coordinate them.
    """
    files = [_chrom_file("1"), _chrom_file("6")]
    _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    conversions = [c for c in commands(plink) if "--vcf" in c]
    assert len(conversions) == 2
    for command in conversions:
        assert command[command.index("--set-all-var-ids") + 1] == "@:#:$r:$a"
        # Applied at load, before --snps-only filters anything, so a long indel allele would
        # otherwise abort the conversion instead of being dropped a step later.
        assert command[command.index("--new-id-max-allele-len") + 1 :][:2] == ["23", "missing"]


# ---------------------------------------------------------------------------
# Long-range LD
# ---------------------------------------------------------------------------


def test_the_long_range_ld_regions_are_excluded_from_every_conversion(
    tmp_path: Path, plink: Path
) -> None:
    """A single inversion spanning tens of megabases contributes enough correlated markers
    to claim a principal component outright, and the axis looks exactly like ancestry."""
    files = [_chrom_file("1"), _chrom_file("6")]
    _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    conversions = [c for c in commands(plink) if "--vcf" in c]
    assert len(conversions) == 2
    for command in conversions:
        assert command[command.index("--exclude") + 1] == "bed1"


def test_the_exclusion_file_is_one_based_and_fully_closed(tmp_path: Path) -> None:
    """``bed1`` is PLINK's 1-based fully-closed reading. Written as ``bed0`` -- the UCSC
    half-open convention -- every region would silently shift by one base."""
    written = tmp_path / "lrld.bed"

    postprocess._write_long_range_ld_bed(written)

    rows = [line.split("\t") for line in written.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == ["2", "135000000", "137000000", "LCT"]
    assert [row[3] for row in rows] == ["LCT", "MHC", "inv8p23", "inv17q21"]
    assert b"\r\n" not in written.read_bytes()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def test_each_chromosome_is_converted_then_pruned_then_extracted(
    tmp_path: Path, plink: Path
) -> None:
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    stages = [
        "convert" if "--vcf" in c else "prune" if "--indep-pairwise" in c else "extract"
        for c in commands(plink)
        if "--version" not in c
    ]
    assert stages == ["convert", "prune", "extract"]


def test_conversion_sorts_and_drops_duplicated_ids(tmp_path: Path, plink: Path) -> None:
    """``--sort-vars`` is what makes the later merge legal rather than hopeful, and 1000
    Genomes really does carry repeated variant IDs."""
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    convert = next(c for c in commands(plink) if "--vcf" in c)
    assert "--sort-vars" in convert
    assert convert[convert.index("--rm-dup") + 1] == "exclude-all"
    assert convert[convert.index("--snps-only") + 1] == "just-acgt"
    assert convert[convert.index("--max-alleles") + 1] == "2"


def test_several_chromosomes_are_merged_into_one_fileset(tmp_path: Path, plink: Path) -> None:
    files = [_chrom_file(str(n)) for n in (1, 2, 3)]
    directory = _payloads(tmp_path, files)

    result = _run(_source(files), tmp_path)

    merge = [c for c in commands(plink) if "--pmerge-list" in c]
    assert len(merge) == 1
    assert result.status is ProcessStatus.CREATED
    # The stub keeps every other variant, so three chromosomes of eight give twelve.
    assert result.rows == 12
    assert (directory / OUTPUT).is_file()


def test_a_single_chromosome_needs_no_merge(tmp_path: Path, plink: Path) -> None:
    """``--pmerge-list`` over one fileset is a copy with a chance of failing."""
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)

    result = _run(_source(files), tmp_path)

    assert [c for c in commands(plink) if "--pmerge-list" in c] == []
    assert result.status is ProcessStatus.CREATED


def test_the_working_directory_is_removed_on_success(tmp_path: Path, plink: Path) -> None:
    """It holds a second copy of every marker in the artifact."""
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)

    _run(_source(files), tmp_path)

    assert not (directory / f".{OUTPUT}.work").exists()
    assert sorted(p.name for p in directory.glob("pca_markers*")) == [
        OUTPUT,
        f"{OUTPUT}.provenance.json",
        "pca_markers_ldpruned.psam",
        "pca_markers_ldpruned.pvar",
    ]


# ---------------------------------------------------------------------------
# Resuming
# ---------------------------------------------------------------------------


def test_a_rerun_after_a_failure_skips_the_chromosomes_that_finished(
    tmp_path: Path, plink: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twenty-two passes of minutes each: losing all of them to an interruption three hours
    in is not a theoretical cost."""
    files = [_chrom_file(str(n)) for n in (1, 2, 3)]
    directory = _payloads(tmp_path, files)
    monkeypatch.setenv("STUB_FAIL_ON", _chrom_file("3"))

    failed = _run(_source(files), tmp_path)
    assert failed.status is ProcessStatus.FAILED
    assert (directory / f".{OUTPUT}.work").is_dir(), "work kept so a rerun can resume"
    plink.unlink()

    monkeypatch.delenv("STUB_FAIL_ON")
    result = _run(_source(files), tmp_path)

    assert result.status is ProcessStatus.CREATED
    converted = [c[c.index("--chr") + 1] for c in commands(plink) if "--vcf" in c]
    assert converted == ["3"], "chromosomes 1 and 2 were already done"


def test_a_changed_setting_invalidates_the_finished_chromosomes(
    tmp_path: Path, plink: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamp binds finished work to the settings that produced it. Trusting a file that
    merely exists is the failure the M2.3 chunk state already had to learn."""
    files = [_chrom_file(str(n)) for n in (1, 2)]
    directory = _payloads(tmp_path, files)
    monkeypatch.setenv("STUB_FAIL_ON", _chrom_file("2"))
    _run(_source(files), tmp_path)
    assert (directory / f".{OUTPUT}.work").is_dir()
    plink.unlink()
    monkeypatch.delenv("STUB_FAIL_ON")

    _run(_source(files, params="          r2: 0.05"), tmp_path)

    converted = [c[c.index("--chr") + 1] for c in commands(plink) if "--vcf" in c]
    assert converted == ["1", "2"], "chromosome 1 must be redone under the new settings"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_a_built_artifact_is_not_rebuilt_and_verifies(tmp_path: Path, plink: Path) -> None:
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)
    assert _run(_source(files), tmp_path).status is ProcessStatus.CREATED
    plink.unlink()

    again = _run(_source(files), tmp_path)
    verified = _run(_source(files), tmp_path, verify_only=True)

    assert again.status is ProcessStatus.ALREADY_PRESENT
    assert verified.status is ProcessStatus.VERIFIED
    assert commands(plink) == [], "no PLINK invocation for an artifact already present"


def test_a_replaced_psam_is_caught_though_the_pgen_is_untouched(
    tmp_path: Path, plink: Path
) -> None:
    """The failure hashing the .pgen alone would never see: a .psam listing different
    samples leaves the genotypes byte-identical and every projection mislabelled."""
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)
    _run(_source(files), tmp_path)
    before = (directory / OUTPUT).read_bytes()

    psam = directory / "pca_markers_ldpruned.psam"
    psam.write_text(
        psam.read_text(encoding="utf-8").replace("SAMPLE0", "SOMEONE"), encoding="utf-8"
    )
    result = _run(_source(files), tmp_path, verify_only=True)

    assert (directory / OUTPUT).read_bytes() == before
    assert result.status is ProcessStatus.FAILED
    assert "psam does not match the digest recorded for it" in result.detail


def test_a_truncated_pvar_is_caught_by_the_row_count(tmp_path: Path, plink: Path) -> None:
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)
    _run(_source(files), tmp_path)

    pvar = directory / "pca_markers_ldpruned.pvar"
    kept = pvar.read_text(encoding="utf-8").splitlines()[:-1]
    pvar.write_text("\n".join(kept) + "\n", encoding="utf-8")
    result = _run(_source(files), tmp_path, verify_only=True)

    assert result.status is ProcessStatus.FAILED
    assert "row(s)" in result.detail


def test_a_missing_psam_is_reported_rather_than_ignored(tmp_path: Path, plink: Path) -> None:
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)
    _run(_source(files), tmp_path)

    (directory / "pca_markers_ldpruned.psam").unlink()
    result = _run(_source(files), tmp_path, verify_only=True)

    assert result.status is ProcessStatus.FAILED
    assert "psam is missing" in result.detail


def test_an_unbuilt_artifact_verifies_as_pending_not_failed(tmp_path: Path, plink: Path) -> None:
    """``refs verify`` must not call a checksum-clean 16.75 GB download unhealthy because
    an hours-long transform has not been asked for yet -- the rule ``_run_anchors`` sets."""
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)

    result = _run(_source(files), tmp_path, verify_only=True)

    assert result.status is ProcessStatus.PENDING
    assert "refs fetch" in result.detail
    assert commands(plink) == []


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


def test_a_plink_failure_writes_nothing_under_the_declared_name(
    tmp_path: Path, plink: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLINK is pointed at scratch prefixes throughout, so a failure part-way cannot leave
    a half-written artifact where the finished one belongs."""
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)
    monkeypatch.setenv("STUB_FAIL_ON", "--pfile")

    result = _run(_source(files), tmp_path)

    assert result.status is ProcessStatus.FAILED
    assert list(directory.glob("pca_markers*")) == []


def test_a_run_that_prunes_everything_away_removes_what_it_promoted(
    tmp_path: Path, plink: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one failure that happens *after* the fileset is in place, and the reason the
    cleanup exists at all.

    An empty subset is not a small subset: a PCA over no markers is not a degraded answer,
    it is no answer. And an empty fileset left on disk satisfies every "is it there?" check
    ``refs status`` makes, so the next command would read it as a finished artifact.
    """
    files = [_chrom_file("1")]
    directory = _payloads(tmp_path, files)
    monkeypatch.setenv("STUB_PRUNE_KEEP", "0")

    result = _run(_source(files), tmp_path)

    assert result.status is ProcessStatus.FAILED
    assert "no markers" in result.detail
    assert list(directory.glob("pca_markers*")) == []


def test_a_missing_plink_says_how_to_install_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)
    empty = tmp_path / "no-tools"
    empty.mkdir()
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setenv("PATH", str(empty))

    result = _run(_source(files), tmp_path)

    assert result.status is ProcessStatus.FAILED
    assert "genetics tools install" in result.detail


def test_an_output_that_is_not_a_pgen_is_refused(tmp_path: Path, plink: Path) -> None:
    """The step promotes three files derived from one name; a ``.parquet`` here would put
    the companions somewhere nothing looks for them."""
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)
    # Built by hand rather than through the manifest, because the manifest has no reason to
    # reject a .parquet here -- `_check_relative_filename` cares about traversal, not about
    # what a step does with the name afterwards. The refusal being tested belongs to the
    # executor, so this is the shape it has to survive.
    source = replace(
        _source(files),
        post_process=(
            manifest.PostProcess(
                step="build_pca_marker_subset", params={"output": "markers.parquet"}
            ),
        ),
    )

    result = _run(source, tmp_path)

    assert result.status is ProcessStatus.FAILED
    assert "must name a .pgen fileset" in result.detail


def test_an_unexpected_failure_is_reported_rather_than_raised(
    tmp_path: Path, plink: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run()`` returns results; it does not raise. Found by review.

    The executor catches what it can predict, and dispatching it ahead of ``run()``'s own
    try block -- which is where it started -- made this the one step whose unpredicted
    failure escaped as a traceback. ``refs fetch`` would have died on it rather than
    reporting it against the source, after however many gigabytes had already downloaded.
    An unreadable companion caught mid-validation is the realistic shape; a raising digest
    is how the test reaches it.
    """
    files = [_chrom_file("1")]
    _payloads(tmp_path, files)
    assert _run(_source(files), tmp_path).status is ProcessStatus.CREATED

    def unreadable(path: Path) -> str:
        raise OSError("the file went away mid-validation")

    monkeypatch.setattr(postprocess, "_sha256", unreadable)
    result = _run(_source(files), tmp_path, verify_only=True)

    assert result.status is ProcessStatus.FAILED
    assert "went away" in result.detail


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_step_reports_a_scratch_allowance(tmp_path: Path) -> None:
    """It names no ``input``, and falling through to ``None`` there reported a 16.75 GB
    transform as needing no disk at all -- the one answer that cannot be right."""
    source = _source([_chrom_file("1"), _chrom_file("2")])

    assert postprocess.estimated_workspace_bytes(source) > 0


def test_the_subset_is_not_marked_genotype_derived() -> None:
    """The decision this milestone had to make, pinned so it is changed deliberately.

    The flag forces an output outside the checkout, and it means "this transform reads a
    genotype export". This one does not: it prunes the panel and nothing else, so the
    artifact is a function of public 1000 Genomes data alone. Give the step an array marker
    list and the flag goes back to True with the output following it out of the tree.
    """
    assert postprocess.STEPS["build_pca_marker_subset"].implemented
    assert not postprocess.STEPS["build_pca_marker_subset"].output_is_genotype_derived
