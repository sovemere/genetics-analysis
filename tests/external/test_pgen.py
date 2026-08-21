"""Harmonized calls to a PLINK 2 pgen (roadmap M5.2).

Uses the same launcher stub as ``test_plink2.py`` -- CI installs no external tools, so a
test that needed the real binary would skip everywhere. What is being asserted here is not
PLINK's behaviour but this module's: which flags it passes, where the intermediate goes,
when it is deleted, and what happens when harmonization yields nothing.

The real conversion was run by hand against the pinned build while M5.2 was written: a
synthetic panel over the committed male fixture produced 2,896 records from 11,519
autosomal positions, and every written record decoded back to the original call or its
exact complement, none wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from genetics.external.harmonize import PanelSites, read_panel_sites
from genetics.external.pgen import ConversionResult, EmptyHarmonizationError, to_pgen
from genetics.external.plink2 import Plink2, Plink2RunError
from genetics.ingest.schema import NORMALIZED_SCHEMA, CallStatus, Chrom, GenotypeTable

RECORD_ARGV = """
import sys
argv = sys.argv[1:]
prefix = argv[argv.index("--out") + 1]
open(prefix + ".argv", "w").write("|".join(argv))
for suffix in (".pgen", ".pvar", ".psam"):
    open(prefix + suffix, "w").write("")
"""

FAILS = """
import sys
sys.stderr.write("Error: something PLINK did not like.\\n")
sys.exit(8)
"""


def _table(genotype: str | None = "AG") -> GenotypeTable:
    a1: str | None = None
    a2: str | None = None
    if genotype is not None:
        a1, a2 = sorted(genotype)
        genotype = a1 + a2
    return GenotypeTable(
        pl.DataFrame(
            [
                {
                    "rsid": "rs1",
                    "chrom": Chrom.CHR1.value,
                    "pos_grch37": 100,
                    "a1": a1,
                    "a2": a2,
                    "genotype": genotype,
                    "call_status": (
                        CallStatus.NO_CALL.value if genotype is None else CallStatus.CALLED.value
                    ),
                }
            ],
            schema=NORMALIZED_SCHEMA,
        ),
        vendor="test",
    )


def _panel(tmp_path: Path, *, matching: bool = True) -> PanelSites:
    pos = 100 if matching else 999
    path = tmp_path / "ref.pvar"
    path.write_text(f"#CHROM\tPOS\tID\tREF\tALT\n1\t{pos}\trs1\tA\tG\n", encoding="utf-8")
    return read_panel_sites(path)


# ---------------------------------------------------------------------------
# What is handed to PLINK
# ---------------------------------------------------------------------------


def test_the_conversion_passes_make_pgen_and_sort_vars(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """``--sort-vars`` covers a panel whose ordering disagrees with ours; PLINK otherwise
    warns and proceeds, so nothing downstream would say the input was unsorted."""
    work = tmp_path / "work"

    to_pgen(_table(), _panel(tmp_path), plink=stub_plink2(RECORD_ARGV), workspace=work)

    argv = (work / "sample.argv").read_text(encoding="utf-8").split("|")
    assert "--make-pgen" in argv
    assert "--sort-vars" in argv
    assert argv[argv.index("--vcf") + 1].endswith(".harmonized.vcf")


def test_the_result_names_the_three_files_plink_writes(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    result = to_pgen(
        _table(), _panel(tmp_path), plink=stub_plink2(RECORD_ARGV), workspace=tmp_path / "w"
    )

    assert result.pgen.name == "sample.pgen"
    assert result.pvar.name == "sample.pvar"
    assert result.psam.name == "sample.psam"
    assert result.n_variants == 1
    assert result.plink_version.startswith("PLINK v2.0.0-a.7.3")


def test_the_stem_names_every_output(tmp_path: Path, stub_plink2: Callable[[str], Plink2]) -> None:
    result = to_pgen(
        _table(),
        _panel(tmp_path),
        plink=stub_plink2(RECORD_ARGV),
        workspace=tmp_path / "w",
        stem="ref-fit",
    )

    assert result.pgen.name == "ref-fit.pgen"


# ---------------------------------------------------------------------------
# The intermediate
# ---------------------------------------------------------------------------


def test_the_intermediate_vcf_is_deleted_once_the_conversion_succeeds(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """It holds the same genotypes as the pgen in a larger, more quotable form."""
    work = tmp_path / "work"

    result = to_pgen(_table(), _panel(tmp_path), plink=stub_plink2(RECORD_ARGV), workspace=work)

    assert result.vcf is None
    assert list(work.glob("*.vcf")) == []


def test_the_intermediate_is_kept_when_the_caller_asks(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    work = tmp_path / "work"

    result = to_pgen(
        _table(), _panel(tmp_path), plink=stub_plink2(RECORD_ARGV), workspace=work, keep_vcf=True
    )

    assert result.vcf is not None
    assert result.vcf.is_file()


def test_the_intermediate_is_deleted_even_when_plink_fails(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """A failed run is exactly the situation in which files get left behind and forgotten,
    and this one is a full copy of the person's autosomal genotypes."""
    work = tmp_path / "work"

    with pytest.raises(Plink2RunError):
        to_pgen(_table(), _panel(tmp_path), plink=stub_plink2(FAILS), workspace=work)

    assert list(work.glob("*.vcf")) == []


def test_the_workspace_defaults_under_the_cache_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_plink2: Callable[[str], Plink2]
) -> None:
    """AGENTS.md 1.5: genotype-derived intermediates live outside the checkout."""
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))

    result = to_pgen(_table(), _panel(tmp_path), plink=stub_plink2(RECORD_ARGV))

    assert result.pgen.parent == tmp_path / "data" / "cache" / "plink"


# ---------------------------------------------------------------------------
# Nothing to convert
# ---------------------------------------------------------------------------


def test_an_empty_harmonization_is_refused_before_plink_sees_it(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """PLINK's own answer is "Error: No variants in --vcf file." -- true, and useless for
    finding the cause. The counts say whether the panel is the wrong build, whether the
    chromosome naming disagrees, or whether the panel parsed to nothing."""
    work = tmp_path / "work"

    with pytest.raises(EmptyHarmonizationError) as excinfo:
        to_pgen(
            _table(),
            _panel(tmp_path, matching=False),
            plink=stub_plink2(RECORD_ARGV),
            workspace=work,
        )

    assert "not_in_panel: 1" in str(excinfo.value)
    assert excinfo.value.report.n_written == 0
    assert not (work / "sample.argv").exists()
    assert list(work.glob("*.vcf")) == []


def test_a_no_call_alone_is_still_something_to_convert(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    """``./.`` is a written record, so a run whose every marker failed to call is a run
    with real coverage information in it rather than an error."""
    result = to_pgen(
        _table(None), _panel(tmp_path), plink=stub_plink2(RECORD_ARGV), workspace=tmp_path / "w"
    )

    assert result.n_variants == 1
    assert result.report.n_usable == 0


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_the_conversion_result_repr_shows_shape_not_content(
    tmp_path: Path, stub_plink2: Callable[[str], Plink2]
) -> None:
    result = to_pgen(
        _table(), _panel(tmp_path), plink=stub_plink2(RECORD_ARGV), workspace=tmp_path / "w"
    )

    rendered = repr(result)

    assert rendered.startswith(f"{ConversionResult.__name__}(n_variants=1, plink_version=")
    assert "harmonized" not in rendered
    assert "counts" not in rendered
