"""Tests for vendor sniffing, the adapter registry, and the stub adapter (roadmap M1.3).

The requirement being tested is a *coupling* claim: adding a vendor must not require
touching an analysis module. Two tests check it structurally
(``test_no_analysis_module_imports_a_vendor_adapter`` and its converse); the rest check
that the second vendor really does parse a structurally different layout into the same
table.
"""

from __future__ import annotations

import ast
from pathlib import Path

import polars as pl
import pytest

from genetics.ingest import adapters, read_export
from genetics.ingest.errors import UnknownVendorError
from genetics.ingest.registry import detect, get, read_prefix
from genetics.ingest.schema import COLUMNS, CallStatus
from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR


def fixture(name: str) -> Path:
    path = DEFAULT_FIXTURE_DIR / name
    if not path.exists():
        pytest.skip("fixtures not generated; run `genetics fixtures`")
    return path


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "vendor"),
    [
        ("ancestry_v2_male.txt", "ancestrydna_v2"),
        ("ancestry_v2_female.txt", "ancestrydna_v2"),
        ("ancestry_v2_wrong_build.txt", "ancestrydna_v2"),
        ("other_vendor_layout.txt", "23andme_like"),
    ],
)
def test_detects_the_right_vendor(name: str, vendor: str) -> None:
    assert detect(fixture(name)).vendor_id == vendor


def test_a_truncated_ancestry_file_is_still_recognised_as_ancestry() -> None:
    """Recognised, then rejected on its header.

    Sniffing on the column row instead would make a truncated export an "unknown vendor",
    which sends the reader looking for a missing adapter rather than at their file.
    """
    assert detect(fixture("ancestry_v2_malformed_header.txt")).vendor_id == "ancestrydna_v2"


def test_unknown_layout_is_refused_with_a_pointer_to_the_seam(tmp_path: Path) -> None:
    path = tmp_path / "mystery.txt"
    path.write_text("some,csv,file\n1,2,3\n", encoding="utf-8")

    with pytest.raises(UnknownVendorError) as excinfo:
        detect(path)

    message = str(excinfo.value)
    assert "add an adapter" in message
    assert "no analysis module should need changing" in message


def test_empty_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    with pytest.raises(UnknownVendorError, match="empty"):
        detect(path)


def test_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UnknownVendorError, match="no such file"):
        detect(tmp_path / "absent.txt")


def test_sniffers_are_mutually_exclusive() -> None:
    """Two adapters claiming one file is a conflict, not something to resolve by
    registration order -- the wrong choice there mis-parses silently."""
    for name in ("ancestry_v2_male.txt", "other_vendor_layout.txt"):
        prefix = read_prefix(fixture(name))
        claimed = [a.vendor_id for a in adapters() if a.sniff(prefix)]
        assert len(claimed) == 1, f"{name} claimed by {claimed}"


def test_read_prefix_is_bounded() -> None:
    from genetics.ingest.registry import SNIFF_LINES

    assert len(read_prefix(fixture("ancestry_v2_male.txt"))) <= SNIFF_LINES


def test_get_by_id_reports_what_is_registered() -> None:
    assert get("ancestrydna_v2").vendor_id == "ancestrydna_v2"
    with pytest.raises(UnknownVendorError, match="Registered adapters"):
        get("nonexistent")


# ---------------------------------------------------------------------------
# The seam itself
# ---------------------------------------------------------------------------


ANALYSIS_MODULES = (
    "src/genetics/qc/metrics.py",
    "src/genetics/qc/report.py",
    "src/genetics/qc/__init__.py",
    "src/genetics/ingest/keys.py",
    "src/genetics/ingest/indels.py",
    "src/genetics/ingest/normalize.py",
    "src/genetics/ingest/schema.py",
)

VENDOR_MODULES = ("genetics.ingest.ancestry", "genetics.ingest.vendor_23andme")


@pytest.mark.parametrize("module_path", ANALYSIS_MODULES)
def test_no_analysis_module_imports_a_vendor_adapter(module_path: str) -> None:
    """The plug-and-play requirement, checked structurally rather than by intention.

    An analysis module that imported a vendor adapter would compile and pass every other
    test in this suite; the coupling would only surface when someone added a third vendor
    and found they had to edit QC. Parsing the imports is the only way this claim stays
    true as the code grows.
    """
    from genetics.paths import repo_root

    source = (repo_root() / module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offenders = imported & set(VENDOR_MODULES)
    assert not offenders, f"{module_path} imports vendor adapter(s): {sorted(offenders)}"


def test_registry_is_the_only_place_that_names_the_adapters() -> None:
    """Adding a vendor should touch the adapter module and the registry loader, nothing else."""
    from genetics.paths import repo_root

    loader = (repo_root() / "src/genetics/ingest/registry.py").read_text(encoding="utf-8")
    assert "ancestry" in loader and "vendor_23andme" in loader


# ---------------------------------------------------------------------------
# The stub adapter: a structurally different layout, the same table
# ---------------------------------------------------------------------------


def test_stub_adapter_produces_the_same_normalized_shape() -> None:
    ancestry = read_export(fixture("ancestry_v2_male.txt")).table
    other = read_export(fixture("other_vendor_layout.txt")).table

    assert tuple(other.frame.columns) == COLUMNS
    assert other.frame.schema == ancestry.frame.schema


def test_stub_adapter_maps_letter_chromosomes() -> None:
    frame = read_export(fixture("other_vendor_layout.txt")).table.frame
    seen = set(frame.get_column("chrom").cast(pl.String).unique().to_list())

    assert {"X", "Y", "MT"} <= seen
    # This layout does not distinguish PAR; the module docstring says so and QC warns.
    assert "PAR" not in seen


def test_stub_adapter_reads_double_dash_as_a_no_call() -> None:
    frame = read_export(fixture("other_vendor_layout.txt")).table.frame
    no_calls = frame.filter(pl.col("call_status").cast(pl.String) == CallStatus.NO_CALL.value)

    assert no_calls.height > 0
    assert no_calls.get_column("genotype").null_count() == no_calls.height


def test_stub_adapter_doubles_a_single_character_genotype(tmp_path: Path) -> None:
    """A haploid call is written once here and twice by AncestryDNA.

    Doubling it is what makes the two vendors agree on the normalized table; the ambiguity
    that creates is the one AncestryDNA already has, resolved the same way in M1.5.
    """
    body = "\n".join(
        [
            "# SYNTHETIC - assembled in a test.",
            "# build 37",
            "# rsid\tchromosome\tposition\tgenotype",
            "\t".join(["rs900000001", "Y", "2650000", "A"]),
            "\t".join(["rs900000002", "MT", "1200", "G"]),
            "\t".join(["rs900000003", "1", "100001", "--"]),
        ]
    )
    path = tmp_path / "stub_layout.txt"
    path.write_text(body + "\n", encoding="utf-8", newline="\n")

    frame = read_export(path).table.frame
    haploid = frame.filter(pl.col("a1").is_not_null())

    assert haploid.height == 2
    assert haploid.filter(pl.col("a1") == pl.col("a2")).height == 2
    assert haploid.filter(pl.col("genotype").str.len_chars() == 2).height == 2


def test_stub_adapter_reports_a_bad_genotype_as_a_row_error_with_a_file_line(
    tmp_path: Path,
) -> None:
    """A malformed *data row* must not raise MalformedHeaderError, and "line N" must mean
    a line of the file.

    Reporting the raw 0-based body index as a line sends someone to the wrong place --
    off by the header block, and off by one.
    """
    from genetics.ingest.errors import MalformedRowError

    body = "\n".join(
        [
            "# SYNTHETIC - assembled in a test.",
            "# build 37",
            "# rsid\tchromosome\tposition\tgenotype",
            "\t".join(["rs900000001", "1", "100001", "AG"]),
            "\t".join(["rs900000002", "1", "100002", "AGT"]),
        ]
    )
    path = tmp_path / "stub_layout.txt"
    path.write_text(body + "\n", encoding="utf-8", newline="\n")

    with pytest.raises(MalformedRowError, match=r"First at line 5\."):
        read_export(path)


def test_adapters_declare_which_chromosomes_they_can_label() -> None:
    """QC needs the difference between "no PAR markers" and "no PAR in this format".

    It travels on SourceInfo rather than being read off the adapter, because no analysis
    module may import a vendor module.
    """
    ancestry = read_export(fixture("ancestry_v2_male.txt")).source
    other = read_export(fixture("other_vendor_layout.txt")).source

    assert "PAR" in ancestry.representable_chroms
    assert "PAR" not in other.representable_chroms
    assert {"X", "Y", "MT"} <= set(other.representable_chroms)


def test_stub_adapter_is_flagged_as_unverified() -> None:
    """ "It parsed" is not "it was validated", and the CLI says so out loud."""
    assert get("23andme_like").verified_against_real_export is False
    assert "unverified" in get("23andme_like").display_name.lower()
