"""Tests for the manifest actually shipped in ``data/references/`` (roadmap M2.3, M2.4).

Separate from ``test_manifest.py`` on purpose: that file tests the schema with synthetic
input, this one tests the corpus we committed. The two fail for different reasons and a
reader should be able to tell which broke.
"""

from __future__ import annotations

import subprocess

import pytest

from genetics.paths import reference_manifest, repo_root
from genetics.refs import manifest as manifest_mod
from genetics.refs.manifest import Manifest, Tier


@pytest.fixture(scope="module")
def committed() -> Manifest:
    return manifest_mod.load()


def test_the_committed_manifest_is_valid(committed: Manifest) -> None:
    assert committed.sources


def test_gnomad_is_present_and_required(committed: Manifest) -> None:
    """AGENTS.md 4.1 and 5.1: the frequency gate cannot be computed without it.

    This is the one source whose absence is a design failure rather than a missing
    download, so it is asserted by name.
    """
    exomes = committed.get("gnomad_exomes_r2_1_1_grch37")
    assert exomes.required is True
    assert exomes.tier is Tier.A
    assert exomes.files


def test_dbsnp_fills_the_mechanisms_m1_left_empty(committed: Manifest) -> None:
    """qc/build_anchors.py and the M1.7 merge table ship as tested code with no data."""
    dbsnp = committed.get("dbsnp_b157_grch37")
    steps = {step.step for step in dbsnp.post_process}
    assert "extract_rsid_merge_table" in steps
    assert "extract_build_anchors" in steps


def test_every_url_is_https(committed: Manifest) -> None:
    for source in committed.sources:
        for item in source.files:
            assert item.url.startswith("https://"), f"{source.id}: {item.filename}"


def test_required_sources_are_all_auto_fetchable(committed: Manifest) -> None:
    for source in committed.required():
        assert source.tier is Tier.A, source.id
        assert source.manual is None, source.id


def test_tier_a_sources_have_files_and_gated_sources_have_instructions(
    committed: Manifest,
) -> None:
    for source in committed.sources:
        if source.tier is Tier.A:
            assert source.files, source.id
        else:
            assert source.manual is not None, source.id
            assert source.manual.instructions.strip(), source.id


def test_the_imputation_panel_is_flagged_and_kept_whole(committed: Manifest) -> None:
    panel = committed.get("thousand_genomes_phase3_grch37")
    assert panel.imputation_panel is True
    steps = {step.step for step in panel.post_process}
    assert "subset_vcf_to_array_positions" not in steps
    assert "convert_to_bref3" in steps


def test_restricted_sources_are_the_ones_agents_md_names(committed: Manifest) -> None:
    """Guards the gate against drifting either way -- silently widening or silently
    swallowing a source it should have flagged."""
    blocked = {source.id for source in committed.needing_opt_in()}
    assert {"snpedia", "omim"} <= blocked
    assert "gnomad_exomes_r2_1_1_grch37" not in blocked


def test_pgs_catalog_is_flagged_per_record_not_blocked(committed: Manifest) -> None:
    """AGENTS.md 4.8 trap 1: the obligation is real but belongs at score selection."""
    pgs = committed.get("pgs_catalog_metadata")
    assert pgs.license.authoritative is False
    assert pgs.license.needs_opt_in is False
    assert any(step.step == "parse_pgs_score_licenses" for step in pgs.post_process)


def test_every_unpinned_file_explains_itself(committed: Manifest) -> None:
    """The distinction the schema exists to preserve, asserted on the real corpus."""
    for source in committed.sources:
        for item in source.files:
            if not item.pinned:
                assert item.unpinned_reason, f"{source.id}: {item.filename}"


def test_the_large_panels_are_fully_pinned(committed: Manifest) -> None:
    """gnomAD is ~558 GB across 24 files, every one carrying a publisher md5 taken from
    the base64 digest GCS returns in x-goog-hash. Pinning it cost no download at all, so
    an unpinned file here would mean someone added one without checking."""
    for source_id in ("gnomad_exomes_r2_1_1_grch37", "gnomad_genomes_r2_1_1_grch37"):
        for item in committed.get(source_id).files:
            assert item.md5 or item.sha256, f"{source_id}: {item.filename}"


def test_sizes_are_declared_so_the_preflight_can_do_arithmetic(committed: Manifest) -> None:
    for source in committed.sources:
        if source.files:
            assert source.total_size_bytes is not None, source.id


def test_the_manifest_is_tracked_by_git() -> None:
    """The payloads are gitignored and this file must not be.

    ``.gitignore`` uses ``dir/**`` plus a re-include because git will not re-include a
    file whose parent directory is excluded -- a shape its own comment warns about. This
    asserts the shape still works, rather than trusting the comment.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(reference_manifest())],
        cwd=repo_root(),
        capture_output=True,
        check=False,
    )
    # check-ignore exits 0 when the path IS ignored. We need the opposite.
    assert result.returncode != 0, "manifest.yaml is gitignored; it must be committed"
