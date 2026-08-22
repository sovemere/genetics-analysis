"""Projection onto the reference PCs (roadmap M5.4).

As with ``test_reference_pca.py``: **CI installs no PLINK**, so the binary here is a
stand-in that records its flags and writes a ``.sscore`` shaped like the real one. What is
held to account is the flag set -- and the flag set is the milestone, because M5.4's whole
content is "call ``--score`` with the arguments that work". Two of them were established by
running the real binary during the M5.3 trial and would otherwise have been guessed wrong:
``--read-freq`` (without which PLINK refuses a single sample) and the ``2 5`` column
positions.

Parsing the ``.sscore`` is tested directly, because that is where a column can be read as
the wrong thing without anything failing.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from genetics.ancestry.projection import (
    Projection,
    ProjectionError,
    _read_sscore,
    _score_columns,
    project,
)
from genetics.ancestry.reference_pca import EigenSettings, ReferencePCA
from genetics.external.plink2 import Plink2

PLINK_STUB = """
import os
import sys
from pathlib import Path

argv = sys.argv[1:]

if "--version" in argv:
    print("PLINK v2.0.0-a.7.3 64-bit (8 Aug 2026)")
    raise SystemExit(0)

out = Path(argv[argv.index("--out") + 1])
out.parent.mkdir(parents=True, exist_ok=True)
with Path(os.environ["STUB_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write("|".join(argv) + "\\n")

if "--read-freq" not in argv:
    # What the real binary does with one sample, quoted from the M5.3 trial run.
    sys.stderr.write(
        "Error: --score requires allele frequencies, and less than 50 samples are "
        "available to impute them from.\\n"
    )
    raise SystemExit(13)

lo, hi = (int(x) for x in argv[argv.index("--score-col-nums") + 1].split("-"))
k = hi - lo + 1
# ALLELE_CT is alleles, not markers: twice the scored marker count for diploid calls.
scored = int(os.environ.get("STUB_SCORED", "1400")) * 2
n_samples = int(os.environ.get("STUB_SAMPLES", "1"))

header = os.environ.get("STUB_HEADER")
if header is None:
    header = "#IID\\tALLELE_CT\\tNAMED_ALLELE_DOSAGE_SUM\\t" + "\\t".join(
        f"PC{i+1}_AVG" for i in range(k)
    )

# Rows are built from the header so a custom layout stays internally consistent.
names = [c.lstrip("#") for c in header.split("\\t")]
rows = []
for s in range(n_samples):
    cells = []
    n_score = 0
    for name in names:
        if name == "IID":
            cells.append(f"S{s}")
        elif name == "FID":
            cells.append("0")
        elif name.startswith("PC") or name.startswith("SCORE"):
            n_score += 1
            cells.append(f"0.0{n_score}{s}")
        else:
            cells.append(str(scored))
    rows.append("\\t".join(cells))

body = os.environ.get("STUB_BODY")
text = header + "\\n" + ("" if body == "empty" else "\\n".join(rows) + "\\n")
Path(str(out) + ".sscore").write_text(text, encoding="utf-8")
"""


@pytest.fixture
def plink(
    stub_plink2: Callable[[str], Plink2], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Plink2:
    monkeypatch.setenv("STUB_LOG", str(tmp_path / "commands.log"))
    return stub_plink2(PLINK_STUB)


def commands(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "commands.log"
    if not log.is_file():
        return []
    return [line.split("|") for line in log.read_text(encoding="utf-8").splitlines()]


def make_pgen(directory: Path, stem: str = "sample") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    prefix = directory / stem
    prefix.with_suffix(".pgen").write_bytes(b"pgen-stub")
    prefix.with_suffix(".pvar").write_text("#CHROM\tPOS\tID\tREF\tALT\n", encoding="utf-8")
    prefix.with_suffix(".psam").write_text("#IID\tSEX\nS0\tNA\n", encoding="utf-8")
    return prefix.with_suffix(".pgen")


def make_pca(directory: Path, *, n_components: int = 10, n_markers: int = 1500) -> ReferencePCA:
    directory.mkdir(parents=True, exist_ok=True)
    prefix = directory / "refpca-abc"
    weights = prefix.with_name(prefix.name + ".eigenvec.allele")
    freq = prefix.with_name(prefix.name + ".afreq")
    eigenval = prefix.with_name(prefix.name + ".eigenval")
    weights.write_text("#CHROM\tID\tREF\tALT\tA1\tPC1\n", encoding="utf-8")
    freq.write_text("#CHROM\tID\tREF\tALT\tALT_FREQS\tOBS_CT\n", encoding="utf-8")
    eigenval.write_text("10\n", encoding="utf-8")
    return ReferencePCA(
        allele_weights=weights,
        frequencies=freq,
        eigenvalues=eigenval,
        n_markers=n_markers,
        n_components=n_components,
        n_panel_samples=2504,
        panel_source="pca_markers_ldpruned.pvar",
        settings=EigenSettings(n_components=n_components),
        reused=False,
        plink=None,
    )


# ---------------------------------------------------------------------------
# The flag set -- which is the milestone
# ---------------------------------------------------------------------------


def test_read_freq_is_passed_because_one_sample_cannot_impute_frequencies(
    tmp_path: Path, plink: Plink2
) -> None:
    """The failure this prevents was measured, not imagined: PLINK stops with an error
    about allele frequencies, which points at the sample rather than at the reference."""
    pca = make_pca(tmp_path / "ref")
    project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")

    argv = commands(tmp_path)[0]
    assert argv[argv.index("--read-freq") + 1] == str(pca.frequencies)


def test_the_score_columns_are_the_ones_plink_writes_for_allele_wts(
    tmp_path: Path, plink: Plink2
) -> None:
    """``2`` is the variant ID and ``5`` the effect allele in a ``.eigenvec.allele``.
    Confirmed against the real binary in the M5.3 trial; guessing them yields a run that
    succeeds and scores the wrong column."""
    pca = make_pca(tmp_path / "ref")
    project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")

    argv = commands(tmp_path)[0]
    start = argv.index("--score")
    assert argv[start + 1 : start + 5] == [str(pca.allele_weights), "2", "5", "header-read"]


def test_the_component_column_range_follows_the_reference(tmp_path: Path, plink: Plink2) -> None:
    pca = make_pca(tmp_path / "ref", n_components=4)
    result = project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")

    argv = commands(tmp_path)[0]
    assert argv[argv.index("--score-col-nums") + 1] == "6-9"
    assert result.n_components == 4
    assert result.coordinates.columns == ["sample_id", "PC1", "PC2", "PC3", "PC4"]


def test_no_calls_contribute_nothing_rather_than_the_mean(tmp_path: Path, plink: Plink2) -> None:
    """Mean imputation would pull every sparsely-called sample toward the origin, which on
    an ancestry plot reads as 'averagely admixed' rather than as 'we know less here'."""
    pca = make_pca(tmp_path / "ref")
    project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")
    assert "no-mean-imputation" in commands(tmp_path)[0]


# ---------------------------------------------------------------------------
# Reading the .sscore back
# ---------------------------------------------------------------------------


def test_component_columns_are_found_by_name_not_by_position(
    tmp_path: Path, plink: Plink2, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The leading columns of a ``.sscore`` vary with the flags in play, so counting from
    the left is a way to read a dosage total as a principal component."""
    monkeypatch.setenv(
        "STUB_HEADER",
        "#FID\tIID\tALLELE_CT\tNAMED_ALLELE_DOSAGE_SUM\tSCORE1_AVG\tSCORE2_AVG",
    )
    pca = make_pca(tmp_path / "ref", n_components=2)
    # The stub writes IID, ALLELE_CT then the scores; with this header the reader must key
    # on the names it finds rather than assume the layout.
    result = project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")
    assert result.coordinates.columns == ["sample_id", "PC1", "PC2"]


def test_a_component_count_mismatch_is_refused(
    tmp_path: Path, plink: Plink2, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUB_HEADER", "#IID\tALLELE_CT\tSCORE1_AVG")
    pca = make_pca(tmp_path / "ref", n_components=4)
    with pytest.raises(ProjectionError, match="component column"):
        project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")


def test_a_truncated_sscore_is_refused_with_its_own_message(tmp_path: Path) -> None:
    """Padding a short row instead would put an empty string where a coordinate belongs,
    and the failure would surface as a Polars cast error naming a column rather than a
    truncated file. Found by writing a test whose stub header and rows disagreed."""
    sscore = tmp_path / "sscore" / "truncated.sscore"
    sscore.parent.mkdir(parents=True, exist_ok=True)
    header = "#IID\tALLELE_CT\tSCORE1_AVG\tSCORE2_AVG"
    # One field short, which is what a truncated write leaves behind.
    sscore.write_text(header + "\nS0\t1400\t0.01\n", encoding="utf-8")

    with pytest.raises(ProjectionError, match="malformed"):
        _read_sscore(sscore, n_components=2)


def test_a_missing_allele_ct_is_named_rather_than_reported_as_a_mismatch(
    tmp_path: Path,
) -> None:
    """Defaulting to zero would make coverage 0% and trip the mismatch floor, diagnosing
    'harmonized against a different panel' for a file that is merely missing a column -- a
    confident diagnosis of the wrong problem, which is worse than no diagnosis."""
    path = tmp_path / "no_ct.sscore"
    path.write_text("#IID\tPC1_AVG\nS0\t0.1\n", encoding="utf-8")

    with pytest.raises(ProjectionError, match="no ALLELE_CT column"):
        _read_sscore(path, n_components=1)


def test_a_header_only_sscore_is_refused(
    tmp_path: Path, plink: Plink2, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUB_BODY", "empty")
    pca = make_pca(tmp_path / "ref")
    with pytest.raises(ProjectionError, match="no scored samples"):
        project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")


def test_many_samples_project_in_one_call_which_is_how_m5_5_gets_its_reference(
    tmp_path: Path, plink: Plink2, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This function takes a pgen rather than 'the sample', so M5.5 can push the reference
    panel through the identical path and get coordinates on the identical scale -- which is
    what makes a distance between them mean anything."""
    monkeypatch.setenv("STUB_SAMPLES", "2504")
    pca = make_pca(tmp_path / "ref")
    result = project(make_pgen(tmp_path / "panel"), pca, plink=plink, workspace=tmp_path / "out")
    assert result.n_samples == 2504


# ---------------------------------------------------------------------------
# What the real binary actually writes
# ---------------------------------------------------------------------------


def test_the_real_sscore_header_is_pinned_here(tmp_path: Path) -> None:
    """A transcript, so the two facts below cannot drift back into assumptions.

    Both were wrong in the first version of this module and both passed every test in this
    file, because the stub encoded the same assumption the code did. They were found by
    running the pinned build (v2.0.0-a.7.3) over a synthetic 60-sample panel and reading the
    output, and the fix is only as durable as this test.

    1. The component columns are ``PC1_AVG``, not ``SCORE1_AVG``. ``header-read`` makes
       PLINK name each output column after the score file's own, and a ``.eigenvec.allele``
       names its columns ``PC1``..``PCk``. A reader looking for ``SCORE`` finds nothing.
    2. ``ALLELE_CT`` counts *alleles*. The sample below had 5 of 100 variants no-called and
       reported 190 -- twice the 95 markers that scored. Read as a marker count it makes
       ``coverage`` 1.9 for a 95%-called sample.
    """
    measured = (
        "#IID\tALLELE_CT\tNAMED_ALLELE_DOSAGE_SUM\tPC1_AVG\tPC2_AVG\tPC3_AVG\tPC4_AVG\n"
        "SAMPLE\t190\t190\t0.00826054\t-0.0203888\t-0.0336347\t-2.28904e-05\n"
    )
    path = tmp_path / "measured.sscore"
    path.write_text(measured, encoding="utf-8")

    coordinates, scored_alleles = _read_sscore(path, n_components=4)
    assert coordinates.columns == ["sample_id", "PC1", "PC2", "PC3", "PC4"]
    assert scored_alleles == 190
    assert scored_alleles // 2 == 95, "95 of 100 variants scored; the other 5 were no-calls"


def test_named_allele_dosage_sum_is_not_mistaken_for_a_component() -> None:
    """It ends in ``_SUM``, so a suffix-only pattern would pull it in as a component and
    every projection would carry one extra 'PC' holding a dosage total."""
    frame = pl.DataFrame(
        {"IID": ["S0"], "ALLELE_CT": [190], "NAMED_ALLELE_DOSAGE_SUM": [190], "PC1_AVG": [0.1]}
    )
    assert _score_columns(frame) == ["PC1_AVG"]


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_coverage_is_reported_as_a_number_rather_than_a_verdict(
    tmp_path: Path, plink: Plink2, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGENTS.md 6: confidence is computed, not authored. M5.5 grades this; M5.4 measures
    it."""
    monkeypatch.setenv("STUB_SCORED", "1200")
    pca = make_pca(tmp_path / "ref", n_markers=1500)
    result = project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")

    assert result.n_scored_alleles == 2400, "PLINK reports alleles, not markers"
    assert result.n_scored_markers == 1200
    assert result.coverage == pytest.approx(0.8)


def test_a_near_total_miss_is_refused_rather_than_returned(
    tmp_path: Path, plink: Plink2, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The structural failure: genotypes harmonized against a different panel carry variant
    IDs the reference does not have, so ``--score`` matches almost nothing and still returns
    finite coordinates that plot somewhere plausible."""
    monkeypatch.setenv("STUB_SCORED", "40")
    pca = make_pca(tmp_path / "ref", n_markers=1500)
    with pytest.raises(ProjectionError, match="different panel"):
        project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")


# ---------------------------------------------------------------------------
# Refusals and privacy
# ---------------------------------------------------------------------------


def test_an_incomplete_genotype_fileset_names_the_missing_file(
    tmp_path: Path, plink: Plink2
) -> None:
    pgen = make_pgen(tmp_path / "s")
    pgen.with_suffix(".pvar").unlink()
    with pytest.raises(ProjectionError, match=r"\.pvar is missing"):
        project(pgen, make_pca(tmp_path / "ref"), plink=plink, workspace=tmp_path / "out")


def test_an_incomplete_reference_names_the_missing_file(tmp_path: Path, plink: Plink2) -> None:
    pca = make_pca(tmp_path / "ref")
    pca.frequencies.unlink()
    with pytest.raises(ProjectionError, match=r"\.afreq is missing"):
        project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")
    assert commands(tmp_path) == [], "refused before spending a subprocess"


def test_the_projection_repr_carries_no_coordinates(tmp_path: Path, plink: Plink2) -> None:
    """Coordinates are a lossy summary rather than calls, but they are still an inference
    about a person, and this is the object a caller logs."""
    pca = make_pca(tmp_path / "ref")
    result = project(make_pgen(tmp_path / "s"), pca, plink=plink, workspace=tmp_path / "out")
    text = repr(result)
    assert "coverage" in text
    assert "0.01" not in text, "no score values in the repr"
    assert str(tmp_path) not in text


def test_projection_is_exported() -> None:
    assert Projection.__name__ == "Projection"
