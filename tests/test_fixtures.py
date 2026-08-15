"""Tests for the synthetic fixture generator (roadmap M0.2).

The acceptance criterion is byte-identical regeneration from a fixed seed. Everything
downstream depends on it: if fixtures drift, every parser and card test silently changes
meaning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genetics.testing.fixtures import (
    DEFAULT_FIXTURE_DIR,
    FIXTURES,
    FixtureSpec,
    generate_all,
    render_fixture,
    verify_all,
)


def _rows(content: str) -> list[str]:
    return [ln for ln in content.splitlines() if ln and not ln.startswith("#")]


def _data_rows(content: str) -> list[str]:
    return [ln for ln in _rows(content) if not ln.startswith("rsid\t")]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", FIXTURES, ids=lambda s: s.name)
def test_generation_is_deterministic(spec: FixtureSpec) -> None:
    assert render_fixture(spec) == render_fixture(spec)


def test_seed_changes_output() -> None:
    spec = FIXTURES[0]
    assert render_fixture(spec, seed=1) != render_fixture(spec, seed=2)


def test_fixtures_are_independent() -> None:
    """A fixture's bytes must not depend on which other fixtures exist.

    Each derives its RNG from (seed, name), so adding one cannot perturb the rest.
    """
    baseline = render_fixture(FIXTURES[0])
    other = FixtureSpec(name="brand_new.txt", description="added later")
    render_fixture(other)
    assert render_fixture(FIXTURES[0]) == baseline


def test_committed_fixtures_match_fresh_generation() -> None:
    """Guards against someone hand-editing a fixture instead of regenerating it."""
    if not (DEFAULT_FIXTURE_DIR / FIXTURES[0].name).exists():
        pytest.skip("fixtures not generated yet; run `genetics fixtures`")
    assert verify_all() == []


def test_generate_all_writes_manifest(tmp_path: Path) -> None:
    written = generate_all(tmp_path)
    assert len(written) == len(FIXTURES) + 1

    manifest = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["seed"]
    assert len(manifest["fixtures"]) == len(FIXTURES)
    assert all(entry["sha256"] for entry in manifest["fixtures"])


def test_manifest_records_marker_counts_not_line_counts(tmp_path: Path) -> None:
    """Header lines are not markers; counting them made every fixture look different."""
    generate_all(tmp_path)
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    counts = {entry["markers"] for entry in manifest["fixtures"]}
    assert len(counts) == 1, f"all fixtures share a marker budget, got {counts}"


def test_manifest_drift_is_detected(tmp_path: Path) -> None:
    """The manifest is the provenance record for the one allowlisted genotype directory.

    A manifest that contradicts the files it describes must not verify clean.
    """
    generate_all(tmp_path)
    manifest_path = tmp_path / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixtures"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")

    assert "MANIFEST.json" in verify_all(tmp_path)


def test_written_files_use_lf(tmp_path: Path) -> None:
    """Byte-identity across Windows and Linux depends on this."""
    generate_all(tmp_path)
    raw = (tmp_path / FIXTURES[0].name).read_bytes()
    assert b"\r\n" not in raw


def test_crlf_rewrite_is_detected_as_drift(tmp_path: Path) -> None:
    """The check .gitattributes exists to protect must actually be able to fail.

    Comparing with read_text() folds CRLF to LF in universal-newline mode, so a fixture
    whose bytes had been rewritten reported no drift -- meaning a removed eol=lf rule
    would produce no signal from the CLI, from CI, or from the reproducibility test.
    """
    generate_all(tmp_path)
    path = tmp_path / FIXTURES[0].name
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

    assert FIXTURES[0].name in verify_all(tmp_path)


# ---------------------------------------------------------------------------
# Privacy: the reason this module exists at all
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_fixtures_are_labelled_synthetic() -> None:
    for spec in FIXTURES:
        content = render_fixture(spec)
        header = "\n".join(ln for ln in content.splitlines() if ln.startswith("#"))
        assert "SYNTHETIC" in header.upper(), f"{spec.name} must announce itself as synthetic"


@pytest.mark.privacy
def test_generation_functions_perform_no_io() -> None:
    """Content generation must be a pure function of the seed.

    If it ever grew an argument pointing at a real export, that export's genotypes could
    reach a committed fixture -- the exact failure AGENTS.md 1.2 forbids.

    Scoped to the functions that *produce* content, not the whole module. A module-wide
    grep was the obvious way to write this and it was quietly useless: it forbade
    ``open(`` and ``read_bytes(`` while the module read files via ``read_text(``, so the
    test passed even though the invariant it names was already broken. Naming the
    functions makes the claim precise and keeps the writer/verifier free to touch disk.
    """
    import inspect

    from genetics.testing import fixtures as mod

    generators = (
        mod.render_fixture,
        mod.render_manifest,
        mod._render,
        mod._genotype,
        mod._pick_alleles,
        mod._allocate_markers,
        mod._ancestry_header,
        mod._fixture_rng,
    )

    forbidden = (
        "open(",
        "read_text(",
        "read_bytes(",
        "loadtxt",
        "pd.read_",
        "requests.",
        "urlopen",
    )

    for func in generators:
        source = inspect.getsource(func)
        for token in forbidden:
            assert token not in source, f"{func.__name__} must not use {token}"


@pytest.mark.privacy
def test_no_generation_function_takes_an_input_path() -> None:
    """Belt and braces: purity by signature, not only by body."""
    import inspect

    from genetics.testing import fixtures as mod

    for func in (mod.render_fixture, mod.render_manifest, mod._render):
        params = set(inspect.signature(func).parameters)
        assert not (params & {"src", "source", "input", "input_path", "path", "infile"}), (
            f"{func.__name__} accepts an input path; generation must derive from the seed"
        )


# ---------------------------------------------------------------------------
# Format fidelity: these encode AGENTS.md section 2
# ---------------------------------------------------------------------------


def test_ancestry_layout_has_five_tab_columns() -> None:
    content = render_fixture(FIXTURES[0])
    for line in _data_rows(content)[:200]:
        assert len(line.split("\t")) == 5


def test_vendor_chromosome_codes_are_numeric() -> None:
    """1-22, 23=X, 24=Y, 25=PAR, 26=MT. Never letters in the Ancestry layout."""
    content = render_fixture(FIXTURES[0])
    codes = {line.split("\t")[1] for line in _data_rows(content)}
    assert codes <= {str(n) for n in range(1, 27)}
    assert {"23", "24", "25", "26"} <= codes


def test_no_calls_are_zero_zero() -> None:
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_high_nocall.txt")
    rows = _data_rows(render_fixture(spec))
    nocalls = [r for r in rows if r.split("\t")[3] == "0"]
    assert nocalls, "high-no-call fixture should contain no-calls"
    for row in nocalls:
        assert row.split("\t")[4] == "0"


def test_indels_use_i_and_d() -> None:
    rows = _data_rows(render_fixture(FIXTURES[0]))
    alleles = {a for r in rows for a in r.split("\t")[3:5]}
    assert {"I", "D"} & alleles, "array format codes indels as I/D with no sequence"
    assert alleles <= {"A", "C", "G", "T", "I", "D", "0"}


def test_male_x_is_effectively_homozygous() -> None:
    """Hemizygous calls are written doubled, so male X looks homozygous throughout."""
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_male.txt")
    rows = [r.split("\t") for r in _data_rows(render_fixture(spec))]
    x_rows = [r for r in rows if r[1] == "23" and r[3] != "0"]
    assert x_rows
    assert all(r[3] == r[4] for r in x_rows)


def test_female_has_heterozygous_x_and_no_y() -> None:
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_female.txt")
    rows = [r.split("\t") for r in _data_rows(render_fixture(spec))]

    x_called = [r for r in rows if r[1] == "23" and r[3] != "0"]
    assert any(r[3] != r[4] for r in x_called), "female X must show heterozygosity"

    y_rows = [r for r in rows if r[1] == "24"]
    assert y_rows
    assert all(r[3] == "0" and r[4] == "0" for r in y_rows), "female Y must be all no-call"


def test_mitochondrial_is_always_single_copy() -> None:
    rows = [r.split("\t") for r in _data_rows(render_fixture(FIXTURES[0]))]
    mt = [r for r in rows if r[1] == "26" and r[3] != "0"]
    assert mt
    assert all(r[3] == r[4] for r in mt)


def test_heterozygote_column_order_varies() -> None:
    """The format does not guarantee allele ordering.

    Fixtures deliberately emit both orders so a parser that compares positionally instead
    of sorting will fail here rather than in production (AGENTS.md section 2).
    """
    rows = [r.split("\t") for r in _data_rows(render_fixture(FIXTURES[0]))]
    hets = [(r[3], r[4]) for r in rows if r[3] != r[4] and "0" not in (r[3], r[4])]
    assert any(a > b for a, b in hets), "expected some non-alphabetical het orderings"
    assert any(a < b for a, b in hets), "expected some alphabetical het orderings"


# ---------------------------------------------------------------------------
# Negative fixtures: ingest must reject these
# ---------------------------------------------------------------------------


def test_malformed_fixture_lacks_column_header() -> None:
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_malformed_header.txt")
    assert "rsid\tchromosome" not in render_fixture(spec)


def test_wrong_build_fixture_declares_38() -> None:
    spec = next(s for s in FIXTURES if s.name == "ancestry_v2_wrong_build.txt")
    header = "\n".join(ln for ln in render_fixture(spec).splitlines() if ln.startswith("#"))
    assert "build 38" in header
    assert "build 37" not in header


def test_other_vendor_layout_differs_structurally() -> None:
    spec = next(s for s in FIXTURES if s.name == "other_vendor_layout.txt")
    rows = _data_rows(render_fixture(spec))
    assert all(len(r.split("\t")) == 4 for r in rows[:200]), "merged genotype column"
    chroms = {r.split("\t")[1] for r in rows}
    assert {"X", "Y", "MT"} <= chroms, "letter chromosome codes, not numeric"
