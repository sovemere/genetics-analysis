"""The reference PCA over array-overlapping markers (roadmap M5.3, second half).

**The transform's body is one PLINK invocation and CI installs no PLINK**, so what runs
here is a stand-in that records the flags it is given and writes files shaped like the ones
the real binary writes -- the same arrangement, and the same disclaimer, as
``tests/refs/test_pca_subset.py``. It holds the orchestration to account: which markers are
selected, which flags carry them, what the sidecar covers, and when a cached artifact is
reused. It is not a claim about what PLINK computes from them.

Everything that is not a PLINK call -- the array intersection, the ID check, the cache key,
the provenance rules -- is tested directly, because that is where the decisions are.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import polars as pl
import pytest

from genetics.ancestry import reference_pca
from genetics.ancestry.reference_pca import (
    EigenSettings,
    ReferencePcaError,
    array_marker_positions,
    build_reference_pca,
)
from genetics.external.harmonize import SiteOutcome
from genetics.external.plink2 import Plink2, Plink2RunError
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable

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

if os.environ.get("STUB_FAIL_ON") and os.environ["STUB_FAIL_ON"] in " ".join(argv):
    sys.stderr.write("Error: the stub was told to fail here.\\n")
    raise SystemExit(8)

ranges = Path(argv[argv.index("--extract") + 2]).read_text(encoding="utf-8").split(chr(10))
kept = [line for line in ranges if line.strip()]
k = int(argv[argv.index("--pca") + 1])

# STUB_SKIP names an output the stub should not write, for the missing-output path.
skip = os.environ.get("STUB_SKIP", "")
if skip != "eigenvec.allele":
    header = "#CHROM\\tID\\tREF\\tALT\\tA1\\t" + "\\t".join(f"PC{i+1}" for i in range(k))
    rows = []
    for i, line in enumerate(kept):
        chrom, pos, _end = line.split("\\t")
        weights = "\\t".join(f"0.0{i}" for _ in range(k))
        rows.append(f"{chrom}\\tv{chrom}_{pos}\\tA\\tG\\tG\\t{weights}")
    Path(str(out) + ".eigenvec.allele").write_text(
        header + chr(10) + chr(10).join(rows) + chr(10), encoding="utf-8"
    )
if skip != "afreq":
    Path(str(out) + ".afreq").write_text(
        "#CHROM\\tID\\tREF\\tALT\\tALT_FREQS\\tOBS_CT" + chr(10), encoding="utf-8"
    )
if skip != "eigenval":
    Path(str(out) + ".eigenval").write_text(
        chr(10).join(str(10 - i) for i in range(k)) + chr(10), encoding="utf-8"
    )
"""


@pytest.fixture
def plink(
    stub_plink2: Callable[[str], Plink2], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Plink2:
    """A :class:`Plink2` around the stub, constructed rather than discovered.

    This module takes its binary as an argument, so the tests use that seam directly
    instead of the installed-state fixture ``test_pca_subset.py`` needs.
    """
    monkeypatch.setenv("STUB_LOG", str(tmp_path / "commands.log"))
    return stub_plink2(PLINK_STUB)


def commands(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "commands.log"
    if not log.is_file():
        return []
    return [line.split("|") for line in log.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_table(
    positions: list[tuple[str, int]], *, no_call: set[int] | None = None
) -> GenotypeTable:
    no_call = no_call or set()
    frame = pl.DataFrame(
        {
            "rsid": [f"rs{i}" for i in range(len(positions))],
            "chrom": [c for c, _ in positions],
            "pos_grch37": [p for _, p in positions],
            "a1": ["A"] * len(positions),
            "a2": ["G"] * len(positions),
            "genotype": ["--" if i in no_call else "AG" for i in range(len(positions))],
            "call_status": ["no_call" if i in no_call else "called" for i in range(len(positions))],
        },
        schema=NORMALIZED_SCHEMA,
    )
    return GenotypeTable(frame, vendor="stub")


def make_subset(
    directory: Path,
    positions: list[tuple[str, int]],
    *,
    n_samples: int = 2504,
    ids: list[str] | None = None,
    alleles: list[tuple[str, str]] | None = None,
) -> Path:
    """A pgen trio standing in for M5.3's LD-pruned marker subset.

    ``alleles`` gives ``(REF, ALT)`` per position. The default A/G is unambiguous and a
    well-formed SNP, so a test that says nothing about alleles gets a panel every marker of
    which survives the exclusion M5.5 added.
    """
    directory.mkdir(parents=True, exist_ok=True)
    prefix = directory / "pca_markers_ldpruned"
    names = ids if ids is not None else [f"v{c}_{p}" for c, p in positions]
    pairs = alleles if alleles is not None else [("A", "G")] * len(positions)
    rows = "".join(
        f"{c}\t{p}\t{name}\t{ref}\t{alt}\n"
        for (c, p), name, (ref, alt) in zip(positions, names, pairs, strict=True)
    )
    prefix.with_suffix(".pvar").write_text("#CHROM\tPOS\tID\tREF\tALT\n" + rows, encoding="utf-8")
    prefix.with_suffix(".psam").write_text(
        "#IID\tSEX\n" + "".join(f"S{i}\tNA\n" for i in range(n_samples)), encoding="utf-8"
    )
    prefix.with_suffix(".pgen").write_bytes(b"pgen-stub")
    return prefix.with_suffix(".pgen")


def panel_positions(n: int, *, chrom: str = "1") -> list[tuple[str, int]]:
    return [(chrom, 1000 * (i + 1)) for i in range(n)]


# ---------------------------------------------------------------------------
# The array intersection
# ---------------------------------------------------------------------------


def test_the_array_contributes_its_marker_positions_sorted_and_deduplicated() -> None:
    table = make_table([("2", 500), ("1", 200), ("1", 100), ("1", 200)])
    assert array_marker_positions(table) == [("1", 100), ("1", 200), ("2", 500)]


def test_no_call_markers_are_kept_because_the_chip_still_carries_them() -> None:
    """Dropping them would key the artifact on one person's call rate, so two people with
    the same chip would stop sharing it -- and the artifact would start encoding something
    about the individual rather than about the hardware."""
    table = make_table([("1", 100), ("1", 200)], no_call={1})
    assert array_marker_positions(table) == [("1", 100), ("1", 200)]


def test_sex_chromosomes_are_excluded_from_the_intersection() -> None:
    table = make_table([("1", 100), ("X", 200), ("MT", 300)])
    assert array_marker_positions(table) == [("1", 100)]


def test_only_markers_on_both_the_array_and_the_panel_are_scored(
    tmp_path: Path, plink: Plink2
) -> None:
    panel = panel_positions(2000)
    # The array carries the first 1,500 panel markers plus 500 the panel does not have.
    array = panel[:1500] + [("1", 9_000_000 + i) for i in range(500)]
    subset = make_subset(tmp_path / "ref", panel)

    result = build_reference_pca(
        make_table(array), subset, plink=plink, workspace=tmp_path / "cache"
    )
    assert result.n_markers == 1500


# ---------------------------------------------------------------------------
# The panel-only exclusion (M5.5's half of the M5.4 coverage finding)
# ---------------------------------------------------------------------------


def ambiguous_alleles(n: int, *, every: int) -> list[tuple[str, str]]:
    """A/G everywhere except every ``every``-th marker, which is A/T."""
    return [("A", "T") if i % every == 0 else ("A", "G") for i in range(n)]


def test_strand_ambiguous_panel_sites_get_no_loading(tmp_path: Path, plink: Plink2) -> None:
    """The whole point of the change: M5.2 cannot supply these markers for any sample, so a
    reference that carries weights for them measures the chip's strand problem and calls it
    the sample's coverage."""
    panel = panel_positions(2000)
    subset = make_subset(tmp_path / "ref", panel, alleles=ambiguous_alleles(2000, every=5))

    result = build_reference_pca(
        make_table(panel), subset, plink=plink, workspace=tmp_path / "cache"
    )

    assert result.n_intersected == 2000
    assert result.n_markers == 1600
    assert result.excluded_sites == {SiteOutcome.AMBIGUOUS_SITE: 400}
    assert result.n_excluded == 400


def test_the_excluded_markers_never_reach_the_extract_file(tmp_path: Path, plink: Plink2) -> None:
    """The range file is the mechanism, so the assertion belongs on the file PLINK reads --
    a filtered frame that still wrote every range would leave the loadings unchanged."""
    panel = panel_positions(2000)
    subset = make_subset(tmp_path / "ref", panel, alleles=ambiguous_alleles(2000, every=5))
    ranges: list[str] = []

    real = reference_pca._write_extract_ranges

    def capture(path: Path, sites: object) -> None:
        real(path, sites)  # type: ignore[arg-type]
        ranges.extend(path.read_text(encoding="utf-8").splitlines())

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(reference_pca, "_write_extract_ranges", capture)
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")

    assert len(ranges) == 1600
    excluded = {str(pos) for (_c, pos) in panel[::5]}
    assert not [line for line in ranges if line.split("\t")[1] in excluded]


def test_panel_records_that_are_not_snps_are_excluded_under_their_own_name(
    tmp_path: Path, plink: Plink2
) -> None:
    """Counted separately from ambiguity because they are a different fact about the panel:
    an indel record is one the subset step should not have kept at all."""
    panel = panel_positions(2000)
    alleles: list[tuple[str, str]] = [("A", "G")] * 2000
    alleles[3] = ("AT", "G")
    alleles[4] = ("A", "A")
    alleles[5] = ("C", "G")
    subset = make_subset(tmp_path / "ref", panel, alleles=alleles)

    result = build_reference_pca(
        make_table(panel), subset, plink=plink, workspace=tmp_path / "cache"
    )
    assert result.excluded_sites == {
        SiteOutcome.PANEL_NOT_SNP: 2,
        SiteOutcome.AMBIGUOUS_SITE: 1,
    }
    assert result.n_markers == 1997


def test_the_id_check_ignores_markers_that_are_on_their_way_out(
    tmp_path: Path, plink: Plink2
) -> None:
    """A duplicated ID at a site no sample can score is not a fact about this run, and
    refusing on it would block a build for a marker that never reaches ``--score``."""
    panel = panel_positions(2000)
    alleles: list[tuple[str, str]] = [("A", "G")] * 2000
    alleles[8] = alleles[9] = ("C", "G")
    ids = [f"v{c}_{p}" for c, p in panel]
    ids[9] = ids[8] = "."

    subset = make_subset(tmp_path / "ref", panel, ids=ids, alleles=alleles)
    result = build_reference_pca(
        make_table(panel), subset, plink=plink, workspace=tmp_path / "cache"
    )
    assert result.n_markers == 1998


def test_the_exclusion_counts_survive_a_cache_hit(tmp_path: Path, plink: Plink2) -> None:
    """Otherwise the same field holds enum keys after a build and nothing after a reuse,
    which is a difference a caller only meets on the second run."""
    panel = panel_positions(2000)
    subset = make_subset(tmp_path / "ref", panel, alleles=ambiguous_alleles(2000, every=5))
    table, cache = make_table(panel), tmp_path / "cache"

    first = build_reference_pca(table, subset, plink=plink, workspace=cache)
    second = build_reference_pca(table, subset, plink=plink, workspace=cache)

    assert second.reused is True
    assert second.excluded_sites == first.excluded_sites == {SiteOutcome.AMBIGUOUS_SITE: 400}
    assert second.n_intersected == first.n_intersected == 2000


def test_the_marker_floor_counts_usable_markers_not_the_whole_intersection(
    tmp_path: Path, plink: Plink2
) -> None:
    """1,100 markers that score 900 is the case this ordering exists for."""
    panel = panel_positions(1100)
    alleles: list[tuple[str, str]] = [("A", "T")] * 200 + [("A", "G")] * 900
    subset = make_subset(tmp_path / "ref", panel, alleles=alleles)

    with pytest.raises(ReferencePcaError, match="900 of the panel's markers"):
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")


def test_the_refusal_says_how_many_markers_the_exclusion_took(
    tmp_path: Path, plink: Plink2
) -> None:
    """A bare "only 900 usable" reads as a broken chip until the message says 200 of the
    1,100 were strand-ambiguous."""
    panel = panel_positions(1100)
    alleles: list[tuple[str, str]] = [("A", "T")] * 200 + [("A", "G")] * 900
    subset = make_subset(tmp_path / "ref", panel, alleles=alleles)

    with pytest.raises(ReferencePcaError) as caught:
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")
    assert "200 of those were strand-ambiguous" in str(caught.value)


def test_the_refusal_does_not_name_a_restriction_that_was_never_applied(
    tmp_path: Path, plink: Plink2
) -> None:
    """Unconditionally, the message reads "the export offered 1,100 autosomal positions
    (1,100 after the 'array' restriction)" -- naming a restriction nobody passed, with two
    identical numbers standing as its apparent evidence, and ``array`` is the name of the
    *unrestricted* space. The reader is left looking for a bug in their own call."""
    panel = panel_positions(1100)
    alleles: list[tuple[str, str]] = [("A", "T")] * 200 + [("A", "G")] * 900
    subset = make_subset(tmp_path / "ref", panel, alleles=alleles)

    with pytest.raises(ReferencePcaError) as caught:
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")

    assert "restriction" not in str(caught.value)
    assert "1,100 autosomal positions," in str(caught.value)


def test_the_refusal_does_name_the_restriction_when_there_was_one(
    tmp_path: Path, plink: Plink2
) -> None:
    """The other half: a restriction that ate the intersection is the first thing to say."""
    panel = panel_positions(1100)
    subset = make_subset(tmp_path / "ref", panel)

    with pytest.raises(ReferencePcaError) as caught:
        build_reference_pca(
            make_table(panel),
            subset,
            plink=plink,
            workspace=tmp_path / "cache",
            restrict_to=panel[:900],
            space="aadr_v66p1_ho",
        )

    assert "900 after the 'aadr_v66p1_ho' restriction" in str(caught.value)


def test_a_restriction_disjoint_from_the_array_is_refused_before_plink(
    tmp_path: Path, plink: Plink2
) -> None:
    panel = panel_positions(2000)
    subset = make_subset(tmp_path / "ref", panel)

    with pytest.raises(ReferencePcaError, match="share no autosomal position"):
        build_reference_pca(
            make_table(panel),
            subset,
            plink=plink,
            workspace=tmp_path / "cache",
            restrict_to=[("1", 7_000_000)],
            space="aadr_v66p1_ho",
        )
    assert commands(tmp_path) == []


def test_a_restriction_narrows_the_space_and_is_recorded_in_the_sidecar(
    tmp_path: Path, plink: Plink2
) -> None:
    """M5.6's shared space: the array, the panel and AADR all carry these markers, and two
    artifacts over the same chip differing only in restriction must be tellable apart by
    somebody reading the sidecar rather than only by their marker counts."""
    panel = panel_positions(2000)
    subset = make_subset(tmp_path / "ref", panel)

    result = build_reference_pca(
        make_table(panel),
        subset,
        plink=plink,
        workspace=tmp_path / "cache",
        restrict_to=panel[:1500],
        space="aadr_v66p1_ho",
    )

    assert result.n_markers == 1500
    assert result.space == "aadr_v66p1_ho"
    sidecar = json.loads(
        result.prefix.with_name(result.prefix.name + ".provenance.json").read_text(encoding="utf-8")
    )
    assert sidecar["space"] == "aadr_v66p1_ho"


def test_the_marker_positions_are_sorted_whatever_order_the_panel_file_used(
    tmp_path: Path, plink: Plink2
) -> None:
    """The field promises sorted and M5.6 is invited to line another source up against it,
    which is exactly the caller who would bisect or merge on that promise. 1000 Genomes
    ships a position-ordered .pvar, so the two agree by luck until the panel widens."""
    panel = panel_positions(1500)
    shuffled = panel[750:] + panel[:750]
    subset = make_subset(tmp_path / "ref", shuffled)

    result = build_reference_pca(
        make_table(panel), subset, plink=plink, workspace=tmp_path / "cache"
    )

    assert list(result.marker_positions) == sorted(panel, key=lambda p: (p[0], p[1]))
    assert len(result.marker_positions) == result.n_markers


def test_the_marker_positions_survive_a_cache_hit(tmp_path: Path, plink: Plink2) -> None:
    """Computed on both paths, because the intersection is read before the cache is
    consulted -- and a reused artifact that returned an empty tuple would silently narrow
    M5.6's shared space to nothing."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    table, cache = make_table(panel), tmp_path / "cache"

    first = build_reference_pca(table, subset, plink=plink, workspace=cache)
    second = build_reference_pca(table, subset, plink=plink, workspace=cache)

    assert second.reused is True
    assert second.marker_positions == first.marker_positions
    assert len(second.marker_positions) == 1500


# ---------------------------------------------------------------------------
# The PLINK invocation
# ---------------------------------------------------------------------------


def test_pca_and_freq_are_computed_in_one_invocation(tmp_path: Path, plink: Plink2) -> None:
    """Not a saved subprocess: M5.4 pairs the weights with these frequencies, and two
    invocations leave a flag able to drift between them and produce a pair that disagrees
    about which markers or samples they describe."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")

    log = commands(tmp_path)
    assert len(log) == 1, "one pass, not one for --pca and another for --freq"
    argv = log[0]
    assert "--pca" in argv and "--freq" in argv
    assert argv[argv.index("--pca") + 2] == "allele-wts"


def test_markers_are_selected_by_range_not_by_variant_id(tmp_path: Path, plink: Plink2) -> None:
    """``--extract bed1`` does not depend on the panel having usable IDs, and matches the
    ``--exclude bed1`` the subset step already uses."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")

    argv = commands(tmp_path)[0]
    assert argv[argv.index("--extract") + 1] == "bed1"


def test_the_component_count_reaches_plink(tmp_path: Path, plink: Plink2) -> None:
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    result = build_reference_pca(
        make_table(panel),
        subset,
        plink=plink,
        settings=EigenSettings(n_components=4),
        workspace=tmp_path / "cache",
    )
    argv = commands(tmp_path)[0]
    assert argv[argv.index("--pca") + 1] == "4"
    assert result.n_components == 4


def test_a_missing_output_is_reported_even_when_plink_exits_zero(
    tmp_path: Path, plink: Plink2, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The .afreq is the one M5.4 cannot proceed without, and a silent absence here becomes
    an error about allele frequencies two milestones away."""
    monkeypatch.setenv("STUB_SKIP", "afreq")
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)

    with pytest.raises(ReferencePcaError, match="afreq"):
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_incomplete_subset_names_the_file_that_is_missing(tmp_path: Path, plink: Plink2) -> None:
    subset = make_subset(tmp_path / "ref", panel_positions(1500))
    subset.with_suffix(".psam").unlink()

    with pytest.raises(ReferencePcaError, match=r"\.psam is missing"):
        build_reference_pca(
            make_table(panel_positions(1500)), subset, plink=plink, workspace=tmp_path / "cache"
        )


def test_a_panel_too_small_for_plinks_statistics_is_refused_here(
    tmp_path: Path, plink: Plink2
) -> None:
    """Measured during the M5.3 trial: PLINK will not impute allele frequencies from fewer
    than fifty samples. Refusing here means the message names the panel."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel, n_samples=20)

    with pytest.raises(ReferencePcaError, match="at least 50"):
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")
    assert commands(tmp_path) == [], "refused before spending a subprocess"


def test_a_near_empty_intersection_is_refused_and_says_what_it_looks_like(
    tmp_path: Path, plink: Plink2
) -> None:
    """The realistic cause is a build or chromosome-naming disagreement, not a sparse chip,
    and a PCA over two hundred markers still returns numbers."""
    subset = make_subset(tmp_path / "ref", panel_positions(2000))
    array = [("1", 7_000_000 + i) for i in range(2000)]

    with pytest.raises(ReferencePcaError, match="build or chromosome-naming"):
        build_reference_pca(make_table(array), subset, plink=plink, workspace=tmp_path / "cache")


def test_an_export_with_no_autosomal_markers_is_refused(tmp_path: Path, plink: Plink2) -> None:
    subset = make_subset(tmp_path / "ref", panel_positions(1500))
    with pytest.raises(ReferencePcaError, match="no autosomal markers"):
        build_reference_pca(
            make_table([("X", 100)]), subset, plink=plink, workspace=tmp_path / "cache"
        )


def test_missing_variant_ids_are_refused_because_m5_4_joins_on_them(
    tmp_path: Path, plink: Plink2
) -> None:
    """``--score`` matches by ID. A missing one does not fail the projection, it makes it
    match nothing -- and the coordinates still plot."""
    panel = panel_positions(1500)
    ids = [f"v{c}_{p}" for c, p in panel]
    ids[7] = "."
    subset = make_subset(tmp_path / "ref", panel, ids=ids)

    with pytest.raises(ReferencePcaError, match="no variant ID"):
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")


def test_duplicated_variant_ids_are_refused(tmp_path: Path, plink: Plink2) -> None:
    panel = panel_positions(1500)
    ids = [f"v{c}_{p}" for c, p in panel]
    ids[9] = ids[8]
    subset = make_subset(tmp_path / "ref", panel, ids=ids)

    with pytest.raises(ReferencePcaError, match="duplicated variant ID"):
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=tmp_path / "cache")


@pytest.mark.parametrize("n", [0, -1, 101])
def test_an_unusable_component_count_is_refused_at_construction(n: int) -> None:
    with pytest.raises(ReferencePcaError):
        EigenSettings(n_components=n)


# ---------------------------------------------------------------------------
# Caching and provenance
# ---------------------------------------------------------------------------


def test_a_second_run_for_the_same_chip_reuses_the_artifact(tmp_path: Path, plink: Plink2) -> None:
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    table, cache = make_table(panel), tmp_path / "cache"

    first = build_reference_pca(table, subset, plink=plink, workspace=cache)
    second = build_reference_pca(table, subset, plink=plink, workspace=cache)

    assert first.reused is False and second.reused is True
    assert len(commands(tmp_path)) == 1
    assert second.allele_weights == first.allele_weights
    assert second.n_markers == first.n_markers


def test_a_different_chip_gets_a_different_artifact_rather_than_overwriting(
    tmp_path: Path, plink: Plink2
) -> None:
    """The requirement M5.3 moved the intersection here for: a subset chosen by one
    person's chip must not be silently reused for the next person's."""
    panel = panel_positions(2000)
    subset = make_subset(tmp_path / "ref", panel)
    cache = tmp_path / "cache"

    a = build_reference_pca(make_table(panel[:1500]), subset, plink=plink, workspace=cache)
    b = build_reference_pca(make_table(panel[:1800]), subset, plink=plink, workspace=cache)

    assert a.allele_weights != b.allele_weights
    assert (a.n_markers, b.n_markers) == (1500, 1800)
    assert a.allele_weights.is_file() and b.allele_weights.is_file()


def test_two_chips_with_the_same_marker_count_still_get_separate_artifacts(
    tmp_path: Path, plink: Plink2
) -> None:
    """The sharper form of the test above, and the one with teeth.

    Two arrays that intersect the panel at the *same number* of markers differ only in
    which markers those are. Nothing but the marker-set digest separates them, so if the
    cache key ever stopped including it these two would silently share an artifact -- and
    each would be scored on the other chip's markers. The count-based test passes either
    way, which is how this gap was found: by neutering the digest and watching it not fail.
    """
    panel = panel_positions(3000)
    subset = make_subset(tmp_path / "ref", panel)
    cache = tmp_path / "cache"

    a = build_reference_pca(make_table(panel[:1500]), subset, plink=plink, workspace=cache)
    b = build_reference_pca(make_table(panel[1500:]), subset, plink=plink, workspace=cache)

    assert a.n_markers == b.n_markers == 1500
    assert a.allele_weights != b.allele_weights
    assert b.reused is False


def test_changed_settings_invalidate_the_cache_without_a_version_bump(
    tmp_path: Path, plink: Plink2
) -> None:
    """The marker subset learned this one: relying on a version integer means a changed
    default leaves every existing artifact looking current."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    table, cache = make_table(panel), tmp_path / "cache"

    build_reference_pca(table, subset, plink=plink, workspace=cache)
    again = build_reference_pca(
        table, subset, plink=plink, settings=EigenSettings(n_components=4), workspace=cache
    )
    assert again.reused is False
    assert len(commands(tmp_path)) == 2


def test_a_changed_panel_invalidates_the_cache(tmp_path: Path, plink: Plink2) -> None:
    panel = panel_positions(1500)
    table, cache = make_table(panel), tmp_path / "cache"

    subset = make_subset(tmp_path / "ref", panel)
    build_reference_pca(table, subset, plink=plink, workspace=cache)
    # Same positions, different alleles: the .pvar digest moves, so the artifact must too.
    subset.with_suffix(".pvar").write_text(
        "#CHROM\tPOS\tID\tREF\tALT\n" + "".join(f"{c}\t{p}\tv{c}_{p}\tC\tT\n" for c, p in panel),
        encoding="utf-8",
    )
    assert build_reference_pca(table, subset, plink=plink, workspace=cache).reused is False


def test_the_sidecar_covers_every_output_not_just_the_weights(
    tmp_path: Path, plink: Plink2
) -> None:
    """An .eigenvec.allele beside an .afreq computed over different markers projects every
    sample slightly wrong while both files look present and parse cleanly -- the lesson the
    marker subset's three-file sidecar already carries."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    table, cache = make_table(panel), tmp_path / "cache"
    result = build_reference_pca(table, subset, plink=plink, workspace=cache)

    sidecar = json.loads(
        result.prefix.with_name(result.prefix.name + ".provenance.json").read_text(encoding="utf-8")
    )
    assert set(sidecar["outputs"]) == {"eigenvec_allele", "afreq", "eigenval"}

    result.frequencies.write_text("tampered\n", encoding="utf-8")
    assert build_reference_pca(table, subset, plink=plink, workspace=cache).reused is False


def test_the_sidecar_records_which_panels_went_into_it(tmp_path: Path, plink: Plink2) -> None:
    """Widening to SGDP later produces a different artifact; without this field it would
    look current."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    result = build_reference_pca(
        make_table(panel), subset, plink=plink, workspace=tmp_path / "cache"
    )
    sidecar = json.loads(
        result.prefix.with_name(result.prefix.name + ".provenance.json").read_text(encoding="utf-8")
    )
    assert sidecar["reference_panels"] == ["thousand_genomes_phase3_grch37"]
    assert sidecar["artifact_version"] == reference_pca.ARTIFACT_VERSION


def test_a_corrupt_sidecar_rebuilds_rather_than_raising(tmp_path: Path, plink: Plink2) -> None:
    """A cache miss is not an error. Failing would turn a changed default into a crash."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    table, cache = make_table(panel), tmp_path / "cache"
    result = build_reference_pca(table, subset, plink=plink, workspace=cache)

    result.prefix.with_name(result.prefix.name + ".provenance.json").write_text(
        "{not json", encoding="utf-8"
    )
    assert build_reference_pca(table, subset, plink=plink, workspace=cache).reused is False


def test_the_range_file_is_not_left_behind(tmp_path: Path, plink: Plink2) -> None:
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    result = build_reference_pca(
        make_table(panel), subset, plink=plink, workspace=tmp_path / "cache"
    )
    assert not result.prefix.with_name(result.prefix.name + ".extract.bed").exists()


def test_the_range_file_is_removed_even_when_plink_fails(
    tmp_path: Path, plink: Plink2, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed run is exactly when scratch gets left behind and forgotten, and this file
    is a line per marker -- the reasoning `to_pgen` applies to its harmonized VCF."""
    monkeypatch.setenv("STUB_FAIL_ON", "--pca")
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    cache = tmp_path / "cache"

    with pytest.raises(Plink2RunError):
        build_reference_pca(make_table(panel), subset, plink=plink, workspace=cache)

    assert list(cache.glob("*.extract.bed")) == []


def test_the_result_repr_carries_no_paths(tmp_path: Path, plink: Plink2) -> None:
    """It is the object a caller logs, and a cache_dir() path contains the account name."""
    panel = panel_positions(1500)
    subset = make_subset(tmp_path / "ref", panel)
    result = build_reference_pca(
        make_table(panel), subset, plink=plink, workspace=tmp_path / "cache"
    )
    text = repr(result)
    assert "n_markers" in text
    assert str(tmp_path) not in text
