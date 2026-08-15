"""Tests for the manifest schema (roadmap M2.1).

Every check here is a check that fires *before* a download starts. That ordering is the
point of validating eagerly: a typo discovered after 60 GB has moved is a typo that cost
an afternoon.
"""

from __future__ import annotations

import textwrap

import pytest

from genetics.refs import manifest
from genetics.refs.manifest import ManifestError, Tier

MINIMAL = """
schema_version: 1
sources:
  - id: example
    name: Example source
    tier: A
    version: "1"
    homepage: https://example.org/
    license: CC0-1.0
    files:
      - url: https://example.org/data.txt
        filename: data.txt
        size_bytes: 10
        sha256: {sha}
"""

SHA = "a" * 64


def build(**overrides: str) -> str:
    body = MINIMAL.format(sha=SHA)
    for old, new in overrides.items():
        body = body.replace(old.replace("_", " "), new)
    return body


def test_minimal_manifest_parses() -> None:
    parsed = manifest.loads(MINIMAL.format(sha=SHA))
    assert len(parsed.sources) == 1
    source = parsed.get("example")
    assert source.tier is Tier.A
    assert source.files[0].pinned is True
    assert source.total_size_bytes == 10


def test_unknown_licence_stops_the_manifest_loading() -> None:
    """The fail-closed path, end to end from YAML.

    Not merely 'licenses.get raises' -- this asserts the manifest layer propagates it
    instead of catching it and carrying on with a default.
    """
    text = MINIMAL.format(sha=SHA).replace("license: CC0-1.0", "license: WTFPL-ish")
    with pytest.raises(ManifestError, match="unknown licence id"):
        manifest.loads(text)


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.txt",
        "/etc/passwd",
        "sub/../../escape.txt",
        "C:windows.txt",
        "back\\slash.txt",
    ],
)
def test_filenames_that_escape_their_directory_are_rejected(filename: str) -> None:
    """The manifest names paths the fetcher creates. That is a filesystem write primitive."""
    text = MINIMAL.format(sha=SHA).replace("filename: data.txt", f"filename: {filename!r}")
    with pytest.raises(ManifestError):
        manifest.loads(text)


def test_non_https_urls_are_rejected() -> None:
    """An unpinned file over plain http is unverifiable in both directions at once."""
    text = MINIMAL.format(sha=SHA).replace(
        "https://example.org/data.txt", "http://example.org/data.txt"
    )
    with pytest.raises(ManifestError, match="must be https"):
        manifest.loads(text)


def test_an_unpinned_file_must_say_why() -> None:
    """Keeps 'genuinely unpinnable' distinguishable from 'nobody bothered'."""
    text = MINIMAL.format(sha=SHA).replace(f"        sha256: {SHA}\n", "")
    with pytest.raises(ManifestError, match="unpinned_reason"):
        manifest.loads(text)


def test_a_pinned_file_may_not_also_claim_to_be_unpinnable() -> None:
    text = MINIMAL.format(sha=SHA).replace(
        f"sha256: {SHA}", f'sha256: {SHA}\n        unpinned_reason: "hedging"'
    )
    with pytest.raises(ManifestError, match="pinned but also carries"):
        manifest.loads(text)


@pytest.mark.parametrize("digest", ["abc", "z" * 64, "A" * 63])
def test_malformed_digests_are_rejected(digest: str) -> None:
    text = MINIMAL.format(sha=SHA).replace(f"sha256: {SHA}", f"sha256: {digest}")
    with pytest.raises(ManifestError, match="64 hex characters"):
        manifest.loads(text)


def test_tier_b_must_declare_a_manual_step() -> None:
    """Tier B exists to describe a source that cannot simply be downloaded."""
    text = MINIMAL.format(sha=SHA).replace("tier: A", "tier: B")
    with pytest.raises(ManifestError, match="must declare a manual step"):
        manifest.loads(text)


def test_tier_a_may_not_declare_a_manual_step() -> None:
    text = MINIMAL.format(sha=SHA) + textwrap.dedent(
        """\
        """
    )
    text = text.replace(
        "    files:",
        "    manual:\n"
        "      instructions: do a thing\n"
        "      url: https://example.org/form\n"
        "    files:",
    )
    with pytest.raises(ManifestError, match="tier A means auto-fetchable"):
        manifest.loads(text)


def test_a_required_source_cannot_be_gated_behind_a_human_step() -> None:
    """Otherwise 'required' would mean 'this checkout is unusable until you fill in a form'."""
    text = (
        MINIMAL.format(sha=SHA)
        .replace("tier: A", "tier: B")
        .replace(
            "    files:",
            "    required: true\n"
            "    manual:\n"
            "      instructions: do a thing\n"
            "      url: https://example.org/form\n"
            "    files:",
        )
    )
    with pytest.raises(ManifestError, match="required source cannot be tier"):
        manifest.loads(text)


def test_unknown_post_processing_step_is_caught_at_load_time() -> None:
    text = MINIMAL.format(sha=SHA).replace(
        "    files:", "    post_process:\n      - step: reticulate_splines\n    files:"
    )
    with pytest.raises(ManifestError, match="unknown post-processing step"):
        manifest.loads(text)


def test_post_processing_params_are_checked_against_the_step_definition() -> None:
    missing = MINIMAL.format(sha=SHA).replace(
        "    files:", "    post_process:\n      - step: convert_to_bref3\n    files:"
    )
    with pytest.raises(ManifestError, match="requires param"):
        manifest.loads(missing)

    unexpected = MINIMAL.format(sha=SHA).replace(
        "    files:",
        "    post_process:\n"
        "      - step: convert_to_bref3\n"
        "        params:\n"
        "          output: out/\n"
        "          typo: 1\n"
        "    files:",
    )
    with pytest.raises(ManifestError, match="unexpected param"):
        manifest.loads(unexpected)


def test_an_imputation_panel_may_not_be_subsetted_in_place() -> None:
    """AGENTS.md 5.5, enforced rather than remembered."""
    text = MINIMAL.format(sha=SHA).replace(
        "    files:",
        "    imputation_panel: true\n"
        "    post_process:\n"
        "      - step: subset_vcf_to_array_positions\n"
        "        params:\n"
        "          output: small.parquet\n"
        "    files:",
    )
    with pytest.raises(ManifestError, match="imputation needs the full panel"):
        manifest.loads(text)


def test_an_imputation_panel_may_still_produce_a_separate_pca_subset() -> None:
    """The rule is about replacing the panel, not about the existence of any subset.

    1000 Genomes is simultaneously the imputation panel and the source of the PCA marker
    subset (M5.3), so a blunter rule would forbid something the roadmap requires.
    """
    text = MINIMAL.format(sha=SHA).replace(
        "    files:",
        "    imputation_panel: true\n"
        "    post_process:\n"
        "      - step: build_pca_marker_subset\n"
        "        params:\n"
        "          output: pca.pgen\n"
        "    files:",
    )
    parsed = manifest.loads(text)
    assert parsed.get("example").imputation_panel is True


def test_duplicate_source_ids_are_rejected() -> None:
    text = MINIMAL.format(sha=SHA)
    doubled = text + text.split("sources:")[1]
    with pytest.raises(ManifestError, match="duplicate source id"):
        manifest.loads(doubled)


def test_duplicate_filenames_within_a_source_are_rejected() -> None:
    text = MINIMAL.format(sha=SHA).replace(
        f"        sha256: {SHA}\n",
        f"        sha256: {SHA}\n"
        "      - url: https://example.org/other.txt\n"
        "        filename: data.txt\n"
        f"        sha256: {SHA}\n",
    )
    with pytest.raises(ManifestError, match="duplicate filename"):
        manifest.loads(text)


def test_schema_version_mismatch_refuses_rather_than_guessing() -> None:
    text = MINIMAL.format(sha=SHA).replace("schema_version: 1", "schema_version: 99")
    with pytest.raises(ManifestError, match="Refusing to guess"):
        manifest.loads(text)


def test_yaml_is_parsed_safely() -> None:
    """``yaml.safe_load``, not ``yaml.load``.

    Full-fat YAML deserialisation constructs arbitrary Python objects, and a manifest is
    exactly the sort of file that gets copied between projects.
    """
    hostile = textwrap.dedent(
        """\
        schema_version: 1
        sources: !!python/object/apply:os.system ["echo pwned"]
        """
    )
    with pytest.raises(ManifestError, match="not valid YAML"):
        manifest.loads(hostile)


def test_total_size_is_none_when_any_file_is_unmeasured() -> None:
    """A preflight that silently under-reports is worse than one admitting it cannot tell."""
    text = MINIMAL.format(sha=SHA).replace("        size_bytes: 10\n", "")
    parsed = manifest.loads(text)
    assert parsed.get("example").total_size_bytes is None


def test_a_source_with_neither_files_nor_a_manual_step_is_rejected() -> None:
    text = MINIMAL.format(sha=SHA).split("    files:")[0]
    with pytest.raises(ManifestError, match="neither files nor a manual step"):
        manifest.loads(text)
