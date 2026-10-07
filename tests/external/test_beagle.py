"""Beagle jobs use real subprocess stubs and fixed-seed synthetic native inputs."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, TypedDict

import pytest

from genetics.external import beagle as mod
from genetics.external.beagle import (
    Beagle,
    BeagleBusyError,
    BeagleError,
    BeagleNotFoundError,
    BeagleOptions,
    BeagleRunError,
    BeagleVersionError,
    JavaRuntime,
    locate_beagle,
)
from genetics.paths import is_inside_repo, repo_root
from genetics.refs import tools


class BeagleInputs(TypedDict):
    gt: Path
    ref: Path
    genetic_map: Path


STUB = r"""
import gzip, json, os, sys, time
from pathlib import Path
if sys.argv[1:] == ['-version']:
    print('openjdk version "17.0.1"', file=sys.stderr)
    sys.exit(0)
args = dict(a.split('=', 1) for a in sys.argv[1:] if '=' in a)
out = Path(args['out'])
capture = os.environ.get('BEAGLE_STUB_ARGS')
if capture:
    Path(capture).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')
print('Window 1 [7:100-500]', flush=True)
print('private-marker-' + 'rs900000001' + ' genotype ' + 'AG', flush=True)
mode = os.environ.get('BEAGLE_STUB_MODE', '')
if mode == 'hang':
    time.sleep(30)
    Path(os.environ['BEAGLE_STUB_EXIT_MARKER']).write_text('orphan', encoding='utf-8')
if mode in ('fail', 'heap'):
    print('OutOfMemoryError' if mode == 'heap' else 'Bad marker: ' + 'rs900000001' + ' AG', file=sys.stderr)
    sys.exit(4)
header = ['##fileformat=VCFv4.3', '\t'.join(['#CHROM','POS','ID','REF','ALT','QUAL','FILTER','INFO','FORMAT','synthetic'])]
row = '\t'.join(['7','100','rs900000001','A','G','.','PASS','.','GT','0|1'])
vcf = Path(str(out) + '.vcf.gz')
with gzip.open(vcf, 'wt', encoding='utf-8') as h:
    h.write('bad' if mode == 'invalid' else '\n'.join(header + [row]) + '\n')
if mode == 'truncated':
    vcf.write_bytes(vcf.read_bytes()[:-6])
if mode != 'nolog':
    Path(str(out) + '.log').write_text('synthetic Beagle completion log', encoding='utf-8')
if mode == 'mutate':
    with Path(args['gt']).open('a', encoding='utf-8') as h:
        h.write('changed')
"""


@pytest.fixture
def runner(tmp_path: Path, stub_binary: Callable[[str], Path]) -> Beagle:
    java = stub_binary(STUB)
    jar = tmp_path / "synthetic.jar"
    jar.write_bytes(b"synthetic stand-in, not redistributed reference data")
    return Beagle(
        JavaRuntime.discover(java),
        jar,
        "synthetic-build",
        hashlib.sha256(jar.read_bytes()).hexdigest(),
    )


@pytest.fixture
def inputs(tmp_path: Path) -> BeagleInputs:
    result = {}
    for role in ("gt", "ref", "genetic_map"):
        path = tmp_path / f"synthetic {role}.tmp"
        path.write_text(f"synthetic {role} input", encoding="utf-8")
        result[role] = path
    return BeagleInputs(gt=result["gt"], ref=result["ref"], genetic_map=result["genetic_map"])


def fake_manifest(payload: bytes) -> tools.ToolManifest:
    original = tools.load()
    beagle = original.get("beagle")
    build = replace(
        beagle.builds[0], sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload)
    )
    return replace(
        original,
        tools=tuple(replace(t, builds=(build,)) if t.id == "beagle" else t for t in original.tools),
    )


@pytest.mark.parametrize("version,major", [("1.8.0_491", 8), ("17.0.1", 17), ("21.0.2", 21)])
def test_java_version_probe_accepts_supported_legacy_and_modern_versions(
    stub_binary: Callable[[str], Path], version: str, major: int
) -> None:
    binary = stub_binary(f"import sys\nprint('java version \"{version}\"', file=sys.stderr)\n")
    runtime = JavaRuntime.discover(binary)
    assert runtime.major == major and runtime.version == version


@pytest.mark.parametrize(
    "body", ["print('java version \"1.7.0_80\"')", 'print("unknown")', "import sys; sys.exit(1)"]
)
def test_java_refuses_old_malformed_or_failed_version_probe(
    stub_binary: Callable[[str], Path], body: str
) -> None:
    with pytest.raises(BeagleVersionError):
        JavaRuntime.discover(stub_binary(body))


def test_missing_java_and_bad_java_home_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(BeagleNotFoundError, match="not installed"):
        JavaRuntime.discover()
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "missing"))
    with pytest.raises(BeagleNotFoundError, match="Configured"):
        JavaRuntime.discover()


def test_discovery_uses_checksum_not_filename_or_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"synthetic pinned tool"
    manifest = fake_manifest(payload)
    tool = manifest.get("beagle")
    jar = tools.installed_path(tmp_path, tool, tool.builds[0])
    jar.parent.mkdir(parents=True)
    jar.write_bytes(payload)
    other = tmp_path / "beagle.newer.jar"
    other.write_bytes(b"incorrect")
    monkeypatch.delenv("GENETICS_BEAGLE_JAR", raising=False)
    found, version, digest = locate_beagle(tools_root=tmp_path, manifest=manifest)
    assert found == jar and version == "27Feb25.75f"
    assert digest == hashlib.sha256(payload).hexdigest()
    jar.write_bytes(b"corrupt")
    with pytest.raises(BeagleVersionError, match="SHA256"):
        locate_beagle(tools_root=tmp_path, manifest=manifest)


def test_jar_override_must_exist_and_match_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "custom.jar"
    monkeypatch.setenv("GENETICS_BEAGLE_JAR", str(path))
    with pytest.raises(BeagleNotFoundError):
        locate_beagle(tools_root=tmp_path)
    path.write_bytes(b"synthetic")
    assert locate_beagle(tools_root=tmp_path, manifest=fake_manifest(b"synthetic"))[0] == path
    with pytest.raises(BeagleVersionError):
        locate_beagle(tools_root=tmp_path)


@pytest.mark.parametrize(
    "bad",
    [
        {"memory_mb": True},
        {"memory_mb": 100},
        {"nthreads": 0},
        {"seed": 2**63},
        {"impute": "false"},
        {"chrom": "1 out=elsewhere"},
    ],
)
def test_options_fail_loudly_on_invalid_configuration(bad: dict[str, Any]) -> None:
    with pytest.raises(BeagleError):
        BeagleOptions(**bad)


def test_argument_building_defaults_private_logs_and_verified_resume(
    runner: Beagle, inputs: BeagleInputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "args.tmp"
    monkeypatch.setenv("BEAGLE_STUB_ARGS", str(capture))
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        monkeypatch.setenv(key, "bad injected options")
    events: list[str] = []
    out = tmp_path / "prefix with spaces"
    result = runner.run(**inputs, out=out, progress=events.append)
    args = json.loads(capture.read_text(encoding="utf-8"))
    assert args[:3] == ["-Xmx8192m", "-jar", str(runner.jar)]
    assert "nthreads=1" in args and "seed=-99999" in args and "impute=true" in args
    assert f"map={inputs['genetic_map']}" in args
    assert result.vcf.is_file() and result.log.is_file() and not result.resumed
    assert events[-1] == "Beagle job completed and checkpointed"
    assert "Beagle window 1" in events
    assert all("rs900000001" not in e and "genotype" not in e for e in events)
    assert "rs900000001" in (result.log.parent / "console.log").read_text(encoding="utf-8")
    assert "vcf" not in repr(result) and "sha256" not in repr(result)
    stamp = result.vcf.stat().st_mtime_ns
    capture.unlink()
    resumed = runner.run(**inputs, out=out)
    assert resumed.resumed and resumed.provenance == result.provenance
    assert resumed.vcf.stat().st_mtime_ns == stamp and not capture.exists()
    exported = result.to_dict()
    exported["provenance"]["files"].clear()
    assert result.provenance["files"]


def test_default_output_is_stable_and_outside_repo(
    runner: Beagle, inputs: BeagleInputs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mod, "cache_dir", lambda: tmp_path / "private-cache")
    one = runner.run(**inputs)
    two = runner.run(**inputs)
    assert one.vcf == two.vcf and two.resumed
    assert not is_inside_repo(one.vcf)


@pytest.mark.parametrize("mode", ["fail", "heap", "invalid", "truncated", "nolog", "mutate"])
def test_failed_or_partial_jobs_never_publish_completion_and_can_restart(
    runner: Beagle,
    inputs: BeagleInputs,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    out = tmp_path / "job"
    monkeypatch.setenv("BEAGLE_STUB_MODE", mode)
    with pytest.raises(BeagleError) as error:
        runner.run(**inputs, out=out)
    assert "rs900000001" not in str(error.value) and "AG" not in str(error.value)
    if mode == "heap":
        assert "increase memory_mb" in str(error.value)
    root = out.with_name(out.name + ".beagle-work")
    assert not (root / "complete").exists()
    assert list(root.glob("attempt-*"))
    monkeypatch.delenv("BEAGLE_STUB_MODE")
    result = runner.run(**inputs, out=out)
    assert result.vcf.is_file() and not result.resumed


@pytest.mark.parametrize(
    "changed",
    ["gt", "ref", "genetic_map", "options", "jar", "output", "checkpoint", "negative_time"],
)
def test_changed_identity_or_corrupt_completed_output_cannot_resume(
    runner: Beagle, inputs: BeagleInputs, tmp_path: Path, changed: str
) -> None:
    out = tmp_path / "job"
    result = runner.run(**inputs, out=out)
    options = BeagleOptions()
    changed_input = inputs.get(changed)
    if isinstance(changed_input, Path):
        changed_input.write_text("changed synthetic input", encoding="utf-8")
    elif changed == "options":
        options = replace(options, nthreads=2)
    elif changed == "jar":
        runner.jar.write_bytes(b"changed")
    elif changed == "output":
        result.vcf.write_bytes(b"damaged")
    elif changed == "checkpoint":
        result.checkpoint.write_text("[]", encoding="utf-8")
    else:
        record = json.loads(result.checkpoint.read_text(encoding="utf-8"))
        record["elapsed_seconds"] = -1
        result.checkpoint.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(BeagleError):
        runner.run(**inputs, out=out, options=options)


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_or_interrupt_terminates_child_and_releases_job_lock(
    runner: Beagle,
    inputs: BeagleInputs,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    monkeypatch.setenv("BEAGLE_STUB_MODE", "hang")
    marker = tmp_path / "orphan.tmp"
    monkeypatch.setenv("BEAGLE_STUB_EXIT_MARKER", str(marker))
    events: list[str] = []

    def progress(message: str) -> None:
        events.append(message)
        if cancel and message == "Beagle is running":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt if cancel else BeagleRunError):
        runner.run(
            **inputs,
            out=tmp_path / "job",
            timeout=0.5 if not cancel else None,
            progress_interval=0.1,
            progress=progress,
        )
    assert "Beagle is running" in events
    assert not marker.exists()
    monkeypatch.delenv("BEAGLE_STUB_MODE")
    assert not runner.run(**inputs, out=tmp_path / "job").resumed


def test_live_lock_refuses_concurrent_writer(
    runner: Beagle, inputs: BeagleInputs, tmp_path: Path
) -> None:
    out = tmp_path / "job"
    root = tmp_path / "job.beagle-work"
    root.mkdir()
    with mod._job_lock(root / "job.beagle.lock"), pytest.raises(BeagleBusyError):
        runner.run(**inputs, out=out)
    assert not runner.run(**inputs, out=out).resumed


def test_process_death_releases_lock(tmp_path: Path, stub_binary: Callable[[str], Path]) -> None:
    lock = tmp_path / "job.beagle.lock"
    binary = stub_binary(
        f"import os\nfrom pathlib import Path\nfrom genetics.external.beagle import _job_lock\nwith _job_lock(Path({str(lock)!r})):\n    os._exit(7)\n"
    )
    assert subprocess.run([str(binary)], check=False).returncode == 7
    with mod._job_lock(lock):
        pass


def test_explicit_phase_only_and_genetic_map_requirement(
    runner: Beagle, inputs: BeagleInputs, tmp_path: Path
) -> None:
    with pytest.raises(BeagleError, match="reference panel"):
        runner.run(gt=inputs["gt"], genetic_map=inputs["genetic_map"])
    result = runner.run(
        gt=inputs["gt"],
        genetic_map=inputs["genetic_map"],
        out=tmp_path / "phase",
        options=BeagleOptions(impute=False, memory_mb=512, nthreads=2, chrom="7"),
    )
    assert result.provenance["contract"]["options"]["impute"] is False
    with pytest.raises(BeagleError, match="input"):
        runner.run(gt=inputs["gt"], ref=inputs["ref"], genetic_map=tmp_path / "missing")


@pytest.mark.privacy
def test_in_repo_output_requires_opt_in_and_all_names_are_ignored(
    runner: Beagle, inputs: BeagleInputs
) -> None:
    with pytest.raises(BeagleError, match="opt-in"):
        runner.run(**inputs, out=repo_root() / "arbitrary-prefix")
    for path in (
        "arbitrary.beagle-work/attempt-abc/unknown.json",
        "arbitrary.beagle.lock",
        "arbitrary.beagle.run.json",
        "arbitrary.vcf.gz",
        "arbitrary.log",
        "knowledge/traits/arbitrary.beagle-work/attempt-x/unknown.json",
        "knowledge/traits/arbitrary.beagle-work/attempt-x/unknown.csv",
    ):
        assert (
            subprocess.run(
                ["git", "check-ignore", "-q", path], cwd=repo_root(), check=False
            ).returncode
            == 0
        )


def write_native_inputs(root: Path) -> BeagleInputs:
    """Generate independent haplotypes from invented reference frequencies, seed fixed."""
    root.mkdir()
    rng = random.Random(8101)
    header = ["##fileformat=VCFv4.2", "##reference=GRCh37"]
    base = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
    reference = [*header, "\t".join(base + [f"synthetic_ref_{i}" for i in range(20)])]
    target = [*header, "\t".join([*base, "synthetic_target_0"])]
    for i in range(200):
        frequency = 0.15 + (i % 7) * 0.1
        alleles = [int(rng.random() < frequency) for _ in range(42)]
        fields = [
            "7",
            str(1000000 + i * 2500),
            f"rs{900000001 + i}",
            "A",
            "G",
            ".",
            "PASS",
            ".",
            "GT",
        ]
        reference.append(
            "\t".join(fields + [f"{alleles[2 * j]}|{alleles[2 * j + 1]}" for j in range(20)])
        )
        if i % 2 == 0:
            target.append("\t".join([*fields, f"{alleles[40]}/{alleles[41]}"]))
    result: BeagleInputs = {
        "gt": root / "synthetic-target.vcf",
        "ref": root / "synthetic-reference.vcf",
        "genetic_map": root / "synthetic-map.tmp",
    }
    result["gt"].write_text("\n".join(target) + "\n", encoding="utf-8")
    result["ref"].write_text("\n".join(reference) + "\n", encoding="utf-8")
    result["genetic_map"].write_text(
        "7 synthetic_start 0 1000000\n7 synthetic_end 1 1500000\n", encoding="utf-8"
    )
    return result


def test_native_pinned_beagle_phases_imputes_and_reuses_complete_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = os.environ.get("GENETICS_BEAGLE_TEST_TOOLS")
    if root is None:
        pytest.skip("set GENETICS_BEAGLE_TEST_TOOLS for pinned native Beagle acceptance")
    inputs = write_native_inputs(tmp_path / "native-synthetic")
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        monkeypatch.setenv(key, "--not-a-real-java-option")
    beagle = Beagle.discover(tools_root=Path(root))
    events: list[str] = []
    result = beagle.run(
        **inputs,
        out=tmp_path / "native-job",
        options=BeagleOptions(memory_mb=512, nthreads=2),
        progress=events.append,
    )
    assert beagle.version == "27Feb25.75f"
    with gzip.open(result.vcf, "rt", encoding="utf-8") as handle:
        rows = [line.rstrip().split("\t") for line in handle if not line.startswith("#")]
    assert len(rows) == 200
    imputed = [r for r in rows if "IMP" in r[7].split(";")]
    assert len(imputed) == 100
    assert all("DR2=" in r[7] and "DS" in r[8].split(":") for r in imputed)
    assert all(len(r) == 10 and "|" in r[9] for r in rows)
    assert any(e.startswith("Beagle window") for e in events)
    resumed = beagle.run(
        **inputs, out=tmp_path / "native-job", options=BeagleOptions(memory_mb=512, nthreads=2)
    )
    assert resumed.resumed and resumed.provenance == result.provenance
    assert result.provenance["contract"]["java"]["major"] >= 8
    phase = beagle.run(
        **inputs,
        out=tmp_path / "native-phase",
        options=BeagleOptions(memory_mb=512, nthreads=2, impute=False),
    )
    with gzip.open(phase.vcf, "rt", encoding="utf-8") as handle:
        phase_rows = [line for line in handle if not line.startswith("#")]
    assert len(phase_rows) == 100
    assert phase.provenance["contract"]["options"]["impute"] is False
