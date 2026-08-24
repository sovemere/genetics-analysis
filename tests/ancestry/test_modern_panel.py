"""Selecting AADR's present-day individuals as a reference panel (roadmap M5.9).

Same fixture strategy as :mod:`tests.ancestry.test_eigenstrat`, and the builders are
imported from it rather than copied: the real archive is 4 GB and not in the checkout, so
what is held to account here is the *selection* and the *transpose*, both of which are
arithmetic over a layout that module already establishes.

**The transpose is the part a synthetic fixture tests properly and a real one would not.**
:func:`~genetics.ancestry.modern_panel.write_plink_fileset` reads an individual-major
archive and writes a variant-major PLINK fileset through four ``bytes.translate`` calls and
a big-integer ``or``, none of which is legible by inspection. A fixture whose codes the test
chose can be decoded back and compared cell by cell, which is what
``test_the_written_bed_decodes_back_to_the_archives_codes`` does. Against the real archive
the same round trip was run at full size and produced a file byte-identical to one built by
an independent implementation.

No privacy marker: AADR individuals are a published archive.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from test_eigenstrat import write_anno, write_geno, write_ind, write_snp

from genetics.ancestry.eigenstrat import EigenstratError, PackedGenotypes, hasharr, read_snp
from genetics.ancestry.modern_panel import (
    DIPLOID_MIN_HETEROZYGOSITY,
    ModernPanelError,
    is_analysis_label,
    open_panel_genotypes,
    present_day_individuals,
    select_modern_panel,
    write_plink_fileset,
)
from genetics.ancestry.populations import (
    HUMAN_ORIGINS_COVERAGE,
    MIN_POPULATION_SAMPLES,
    PopulationsError,
    coverage_for,
    read_aadr_population_labels,
)
from genetics.external.plink2 import Plink2
from genetics.refs import manifest, postprocess
from genetics.refs.postprocess import _MODERN_PANEL_MIN_GROUP, ProcessStatus, _resolve_min_group

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

N_SITES = 40
"""Enough rows that a diploid individual's heterozygosity is a stable fraction, few enough
that a test can write every code out. The autosomes are the first 32 of them, so the
sex-chromosome rows are real rather than notional."""

AUTOSOMAL = 32


def sites(tmp_path: Path) -> Path:
    """``.snp`` rows: 32 autosomal, then 8 on chromosomes 23 and 24, which is the pinned
    release's shape -- autosomes first and contiguous."""
    rows = [(f"rs{i}", str(i % 22 + 1), 1000 + i, "A", "G") for i in range(AUTOSOMAL)]
    rows += [(f"rsX{i}", "23" if i < 4 else "24", 2000 + i, "A", "G") for i in range(8)]
    return write_snp(tmp_path, rows)


def diploid(seed: int) -> list[int]:
    """Codes for one individual: about a third heterozygous, which is what a real one is."""
    return [(seed + i) % 3 for i in range(N_SITES)]


def haploid() -> list[int]:
    """Codes with no heterozygote anywhere -- the pseudo-haploid representation."""
    return [0 if i % 2 else 2 for i in range(N_SITES)]


def build(
    tmp_path: Path,
    people: list[tuple[str, str, str]],
    codes: list[list[int]],
) -> tuple[Path, Path, Path, Path]:
    """``(snp, ind, geno, anno)`` for ``people`` as ``(id, date_bp, group)``.

    The ``.geno`` header carries the real ``hasharr`` over the ``.snp``'s rsIDs, because
    ``open_packed`` checks it -- that check is what separates the two same-shaped HO
    datasets in the release, and a fixture writing zero would be exercising the error path
    rather than the reader.
    """
    snp = sites(tmp_path)
    ind = write_ind(tmp_path, [(sample, "M", group) for sample, _, group in people])
    geno = write_geno(
        tmp_path,
        codes,
        n_sites=N_SITES,
        ind_hash=hasharr(sample for sample, _, _ in people),
        snp_hash=hasharr(read_snp(snp).frame["rsid"].to_list()),
    )
    anno = write_anno(tmp_path, [(sample, bp, group, "500000") for sample, bp, group in people])
    return snp, ind, geno, anno


def cohort(group: str, n: int, *, date: str = "0", start: int = 0) -> list[tuple[str, str, str]]:
    return [(f"{group}_{start + i}", date, group) for i in range(n)]


# ---------------------------------------------------------------------------
# Who counts as present-day
# ---------------------------------------------------------------------------


def test_a_negative_date_is_present_day_because_khwit_is(tmp_path: Path) -> None:
    """``Khwit.SG`` is dated **-4 BP** -- sampled in the 20th century, which is what "before
    1950" makes negative. ``date_bp == 0`` would drop him; ``is_ancient`` alone would keep
    an individual the sheet never dated. The rule is dated *and* not into the past."""
    people = [("modern", "0", "A"), ("khwit", "-4", "A"), ("old", "4000", "A"), ("na", "..", "A")]
    _snp, ind, _geno, anno = build(tmp_path, people, [diploid(i) for i in range(4)])

    from genetics.ancestry.eigenstrat import annotate, read_anno, read_ind

    kept = present_day_individuals(annotate(read_ind(ind), read_anno(anno)))

    assert [item.sample_id for item in kept] == ["modern", "khwit"]


def test_an_ancient_individual_is_not_in_the_modern_panel(tmp_path: Path) -> None:
    people = cohort("A", 20) + cohort("Ancient", 20, date="4000")
    snp, ind, geno, anno = build(tmp_path, people, [diploid(i) for i in range(40)])

    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)

    assert panel.groups == ("A",)
    assert panel.n_present_day == 20


# ---------------------------------------------------------------------------
# The labels AADR flags
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "usable"),
    [
        ("Palestinian", True),
        ("Lebanese_Christian", True),
        ("Yemeni_Highlands", True),
        ("Iranian_Zoroastrian", True),
        # The productive outlier mark, in each form the release uses.
        ("Palestinian-o", False),
        ("Palestinian-oAfrica", False),
        ("Altaian-oPCA", False),
        ("YRI-oRelative", False),
        ("Mozabite-oSubSaharan", False),
        ("Turkish-QCremove", False),
        ("Han-Discovery", False),
        ("Ignore_Something", False),
    ],
)
def test_aadrs_own_label_marks_are_read_as_verdicts(label: str, usable: bool) -> None:
    assert is_analysis_label(label) is usable


def test_the_relatives_group_is_excluded_although_it_clears_the_floor(tmp_path: Path) -> None:
    """``YRI-oRelative`` holds 29 present-day individuals in the pinned release, so a
    selection trusting the group floor to catch AADR's marks gains a population whose
    defining property is that its members are relatives of one another. Their centroid is
    tight, and a tight centroid is a confident call."""
    people = cohort("YRI", 20) + cohort("YRI-oRelative", 29)
    snp, ind, geno, anno = build(tmp_path, people, [diploid(i) for i in range(49)])

    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)

    assert panel.groups == ("YRI",)
    assert panel.n_flagged_label == 29


# ---------------------------------------------------------------------------
# Diploidy, measured
# ---------------------------------------------------------------------------


def test_a_pseudo_haploid_individual_is_excluded_by_its_heterozygosity(tmp_path: Path) -> None:
    """Measured, not read off the data type -- following M5.6, and here the difference is
    not hypothetical: in the pinned release the count finds 244 where the ``Shotgun`` suffix
    finds 233, the other eleven being outgroups and reference sequences."""
    people = cohort("A", 21)
    codes = [diploid(i) for i in range(20)] + [haploid()]
    snp, ind, geno, anno = build(tmp_path, people, codes)

    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)

    assert panel.n_pseudo_haploid == 1
    assert panel.n_individuals == 20
    assert "A_20" not in {item.sample_id for item in panel.individuals}
    assert panel.min_heterozygosity >= DIPLOID_MIN_HETEROZYGOSITY


def test_the_floor_is_applied_after_the_other_exclusions(tmp_path: Path) -> None:
    """A group of 22 that is 19 once its flagged and pseudo-haploid members are gone is a
    group of 19. Applying the floor first would keep it and then hand the model a
    population three members smaller than the floor it was admitted under."""
    people = cohort("A", 20) + cohort("A-QCremove", 1, start=20) + cohort("A", 2, start=30)
    # 22 individuals labelled A, of whom two are pseudo-haploid: a group of 20, not 22.
    codes = (
        [diploid(i) for i in range(18)] + [haploid(), haploid()] + [diploid(i) for i in range(3)]
    )
    snp, ind, geno, anno = build(tmp_path, people, codes)

    with pytest.raises(ModernPanelError, match="largest surviving group holds 20"):
        select_modern_panel(snp, ind, geno, anno, min_group=21)

    # And at a floor of twenty it is admitted, with the same three exclusions applied --
    # so the test is about the *order* rather than about the exclusions firing at all.
    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)
    assert panel.n_individuals == 20
    assert (panel.n_flagged_label, panel.n_pseudo_haploid) == (1, 2)


def test_an_outgroup_that_reached_the_floor_raises_rather_than_being_filtered(
    tmp_path: Path,
) -> None:
    """AADR dates a chimpanzee, a gorilla, a macaque and the hg19 reference to the present
    alongside people. Two guards remove them today and neither is about them -- their
    heterozygosity is zero and their groups hold one or two members. This is the tripwire
    that says so out loud if a release ever ships twenty of one."""
    people = cohort("Chimp", 20)
    snp, ind, geno, anno = build(tmp_path, people, [diploid(i) for i in range(20)])

    with pytest.raises(ModernPanelError, match="Chimp"):
        select_modern_panel(snp, ind, geno, anno, min_group=20)


# ---------------------------------------------------------------------------
# Writing PLINK's fileset
# ---------------------------------------------------------------------------


def decode_bed(bed: Path, *, n_markers: int, n_individuals: int) -> list[list[int]]:
    """Read a variant-major PLINK 1 ``.bed`` back to EIGENSTRAT codes, ``[ind][marker]``.

    Deliberately a second implementation rather than the writer run backwards: the writer
    is four ``translate`` tables and a big-integer ``or``, and a decoder sharing them would
    agree with it about a shared mistake. This one shifts one genotype at a time.
    """
    raw = bed.read_bytes()
    assert raw[:3] == bytes((0x6C, 0x1B, 0x01))
    body = raw[3:]
    row_bytes = (n_individuals + 3) // 4
    to_eigenstrat = {0: 2, 1: 3, 2: 1, 3: 0}
    out = [[0] * n_markers for _ in range(n_individuals)]
    for marker in range(n_markers):
        record = body[marker * row_bytes : (marker + 1) * row_bytes]
        for individual in range(n_individuals):
            code = (record[individual >> 2] >> (2 * (individual & 3))) & 3
            out[individual][marker] = to_eigenstrat[code]
    return out


def test_the_written_bed_decodes_back_to_the_archives_codes(tmp_path: Path) -> None:
    """The transpose, cell by cell. Twenty-one individuals rather than twenty so the last
    byte of every record is a partial group -- the path that writes fewer than four
    individuals into one byte, which a count divisible by four never exercises."""
    people = cohort("A", 21)
    codes = [
        [(i * 7 + j * 3) % 4 for j in range(N_SITES)]  # every code including CODE_MISSING
        for i in range(21)
    ]
    snp, ind, geno, anno = build(tmp_path, people, codes)
    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)
    packed = open_panel_genotypes(panel, ind, geno)

    bed, _bim, _fam = write_plink_fileset(panel, packed, tmp_path / "out")

    decoded = decode_bed(bed, n_markers=AUTOSOMAL, n_individuals=panel.n_individuals)
    for position, individual in enumerate(panel.individuals):
        source = codes[int(individual.sample_id.removeprefix("A_"))]
        assert decoded[position] == source[:AUTOSOMAL], individual.sample_id


def test_only_the_autosomes_are_written(tmp_path: Path) -> None:
    """The sex chromosomes are in the archive and out of the panel: a male's X is
    hemizygous, so it would read as a run of homozygous calls on an axis meant to carry
    ancestry."""
    people = cohort("A", 20)
    snp, ind, geno, anno = build(tmp_path, people, [diploid(i) for i in range(20)])
    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)

    _bed, bim, _ = write_plink_fileset(panel, panel_genotypes(panel, ind, geno), tmp_path / "out")

    lines = bim.read_text(encoding="utf-8").splitlines()
    assert len(lines) == AUTOSOMAL
    assert {line.split("\t")[0] for line in lines} <= {str(c) for c in range(1, 23)}


def panel_genotypes(panel, ind: Path, geno: Path) -> PackedGenotypes:  # type: ignore[no-untyped-def]
    return open_panel_genotypes(panel, ind, geno)


def test_the_fam_carries_the_population_so_the_pgen_does(tmp_path: Path) -> None:
    """The group goes in the family column because ``--make-pgen`` carries it into the
    ``.psam``. That is what lets
    :func:`~genetics.ancestry.populations.read_aadr_population_labels` read the membership
    off the artifact itself instead of from a second file that can fall out of step."""
    people = cohort("Druze", 20)
    snp, ind, geno, anno = build(tmp_path, people, [diploid(i) for i in range(20)])
    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)

    _, _, fam = write_plink_fileset(panel, panel_genotypes(panel, ind, geno), tmp_path / "out")

    rows = [line.split("\t") for line in fam.read_text(encoding="utf-8").splitlines()]
    assert {row[0] for row in rows} == {"Druze"}
    assert [row[1] for row in rows] == [i.sample_id for i in panel.individuals]


def test_reopening_refuses_a_same_shaped_wrong_individual_file(tmp_path: Path) -> None:
    """Counts cannot distinguish two releases with the same number of people. The packed
    header's individual hash can, and the bulk transpose must not be the caller that skips
    that half of the archive's identity check."""
    people = cohort("Druze", 20)
    snp, ind, geno, anno = build(tmp_path, people, [diploid(i) for i in range(20)])
    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)
    wrong = write_ind(
        tmp_path,
        [(f"other_{i}", "M", "Druze") for i in range(20)],
    )

    with pytest.raises(ModernPanelError, match="individuals hash"):
        open_panel_genotypes(panel, wrong, geno)


def test_selection_refuses_a_same_shaped_wrong_individual_file(tmp_path: Path) -> None:
    """The identity check must run before selection too; checking only on the later reopen
    would let heterozygosity and group membership be measured against the wrong records."""
    people = cohort("Druze", 20)
    snp, _ind, geno, _anno = build(tmp_path, people, [diploid(i) for i in range(20)])
    replacements = cohort("Druze", 20, start=100)
    wrong_ind = write_ind(tmp_path, [(sample, "M", group) for sample, _, group in replacements])
    wrong_anno = write_anno(
        tmp_path,
        [(sample, bp, group, "500000") for sample, bp, group in replacements],
    )

    with pytest.raises(EigenstratError, match="individuals hash"):
        select_modern_panel(snp, wrong_ind, geno, wrong_anno, min_group=20)


def test_interleaved_chromosomes_are_refused_rather_than_gathered(tmp_path: Path) -> None:
    """The decode slices a whole record, which a sorted ``.snp`` allows. An interleaved one
    needs a per-marker gather -- three billion interpreter steps at full size -- so it is
    refused rather than handled by a slow path nobody has ever run."""
    rows = [("rs0", "1", 1000, "A", "G"), ("rsX", "23", 2000, "A", "G")]
    rows += [(f"rs{i}", "1", 3000 + i, "A", "G") for i in range(1, 21)]
    snp = write_snp(tmp_path, rows)
    people = cohort("A", 20)
    ind = write_ind(tmp_path, [(s, "M", g) for s, _, g in people])
    geno = write_geno(
        tmp_path,
        [diploid(i)[: len(rows)] for i in range(20)],
        n_sites=len(rows),
        ind_hash=hasharr(sample for sample, _, _ in people),
        snp_hash=hasharr(read_snp(snp).frame["rsid"].to_list()),
    )
    anno = write_anno(tmp_path, [(s, bp, g, "500000") for s, bp, g in people])
    panel = select_modern_panel(snp, ind, geno, anno, min_group=20)

    with pytest.raises(ModernPanelError, match="contiguous"):
        write_plink_fileset(panel, panel_genotypes(panel, ind, geno), tmp_path / "out")


# ---------------------------------------------------------------------------
# The floor is one number, shared
# ---------------------------------------------------------------------------


def test_panel_floor_matches_the_model(tmp_path: Path) -> None:
    """A group written by the transform and then dropped by the model is work done for
    nothing; a group the model would admit that the transform never wrote is a population it
    looks for and cannot find. Named in both docstrings, held here."""
    assert _MODERN_PANEL_MIN_GROUP == MIN_POPULATION_SAMPLES


@pytest.mark.parametrize("value", [20.5, True, "20.5"])
def test_manifest_panel_floor_refuses_values_that_are_not_whole(value: object) -> None:
    with pytest.raises(postprocess.ProcessError, match="whole number"):
        _resolve_min_group({"min_group": value})


def test_a_panel_with_no_qualifying_group_says_what_was_dropped(tmp_path: Path) -> None:
    """The counts are in the error because "no group reaches 20" with nothing beside it
    cannot distinguish a truncated archive from a floor set too high."""
    people = cohort("A", 5) + cohort("B", 5)
    snp, ind, geno, anno = build(tmp_path, people, [diploid(i) for i in range(10)])

    with pytest.raises(ModernPanelError, match=re.compile(r"largest surviving group holds 5")):
        select_modern_panel(snp, ind, geno, anno, min_group=20)


def test_the_selector_itself_refuses_a_single_person_population(tmp_path: Path) -> None:
    """The transform validates its manifest parameter, but this function is public too.
    Letting a direct caller set one would admit a centroid with radius zero."""
    people = cohort("A", 1)
    snp, ind, geno, anno = build(tmp_path, people, [diploid(0)])

    with pytest.raises(ModernPanelError, match="at least 2"):
        select_modern_panel(snp, ind, geno, anno, min_group=1)


# ---------------------------------------------------------------------------
# Labels and the coverage statement travel with the widened panel
# ---------------------------------------------------------------------------


def locality_sheet(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    """A narrow stand-in for the three columns the label reader uses."""
    path = tmp_path / "localities.anno"
    lines = [
        "Genetic ID\tGroup ID\tPolitical Entity",
        *(f"{sample}\t{group}\t{place}" for sample, group, place in rows),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_aadr_labels_read_population_from_the_artifact_and_locality_from_the_sheet(
    tmp_path: Path,
) -> None:
    """Membership is carried by the pgen's own ``.psam``; only the sampling locality is
    joined from the sheet. The modal country wins, with an alphabetical tie-break so two
    runs cannot disagree because row order changed."""
    psam = tmp_path / "modern.psam"
    psam.write_text(
        "#FID\tIID\tSEX\nDruze\tD1\t1\nDruze\tD2\t2\nKazakh\tK1\t1\n",
        encoding="utf-8",
    )
    anno = locality_sheet(
        tmp_path,
        [
            ("D1", "Druze", "Israel"),
            ("D2", "Druze", "Jordan"),
            # Same group, not in the artifact: it must not vote in the artifact's mode.
            ("D3", "Druze", "Jordan"),
            ("K1", "Kazakh", "Kazakhstan"),
        ],
    )

    labels = read_aadr_population_labels(psam, anno)

    assert labels.frame.to_dicts() == [
        {"sample_id": "D1", "population": "Druze", "region": "Israel"},
        {"sample_id": "D2", "population": "Druze", "region": "Israel"},
        {"sample_id": "K1", "population": "Kazakh", "region": "Kazakhstan"},
    ]


def test_aadr_labels_refuse_a_sheet_that_cannot_locate_a_panel_population(
    tmp_path: Path,
) -> None:
    psam = tmp_path / "modern.psam"
    psam.write_text("#FID\tIID\nDruze\tD1\nKazakh\tK1\n", encoding="utf-8")
    anno = locality_sheet(tmp_path, [("D1", "Druze", "Israel"), ("K1", "Kazakh", "..")])

    with pytest.raises(PopulationsError, match="Kazakh"):
        read_aadr_population_labels(psam, anno)


def test_aadr_labels_refuse_group_names_from_a_different_set_of_samples(tmp_path: Path) -> None:
    """A stale sheet can carry all the same groups and none of the same people. Joining on
    group alone returns plausible countries and defeats the release-integrity check."""
    psam = tmp_path / "modern.psam"
    psam.write_text("#FID\tIID\nDruze\tD1\nKazakh\tK1\n", encoding="utf-8")
    anno = locality_sheet(
        tmp_path,
        [("other_d", "Druze", "Israel"), ("other_k", "Kazakh", "Kazakhstan")],
    )

    with pytest.raises(PopulationsError, match="D1"):
        read_aadr_population_labels(psam, anno)


def test_aadr_labels_refuse_a_sample_whose_group_changed_between_files(tmp_path: Path) -> None:
    psam = tmp_path / "modern.psam"
    psam.write_text("#FID\tIID\nDruze\tD1\n", encoding="utf-8")
    anno = locality_sheet(tmp_path, [("D1", "BedouinA", "Israel")])

    with pytest.raises(PopulationsError, match="different panel builds"):
        read_aadr_population_labels(psam, anno)


def test_aadr_labels_refuse_a_panel_sample_repeated_in_the_sheet(tmp_path: Path) -> None:
    psam = tmp_path / "modern.psam"
    psam.write_text("#FID\tIID\nDruze\tD1\n", encoding="utf-8")
    anno = locality_sheet(
        tmp_path,
        [("D1", "Druze", "Israel"), ("D1", "Druze", "Jordan")],
    )

    with pytest.raises(PopulationsError, match="more than once"):
        read_aadr_population_labels(psam, anno)


def test_the_widened_coverage_statement_attaches_only_to_its_exact_population_set() -> None:
    assert len(HUMAN_ORIGINS_COVERAGE.populations) == 100
    assert coverage_for(HUMAN_ORIGINS_COVERAGE.populations) is HUMAN_ORIGINS_COVERAGE
    assert coverage_for(HUMAN_ORIGINS_COVERAGE.populations - {"Druze"}) is None

    gaps = " | ".join(gap.region for gap in HUMAN_ORIGINS_COVERAGE.gaps).lower()
    for expected in ("maghreb", "aboriginal australia", "khoisan", "levant"):
        assert expected in gaps


# ---------------------------------------------------------------------------
# The reference post-process step
# ---------------------------------------------------------------------------


OUTPUT = "modern_panel_ldpruned.pgen"

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


def pvar_rows(prefix):
    path = Path(str(prefix) + ".pvar")
    return [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]


def write_pgen(prefix, rows, psam):
    Path(str(prefix) + ".pvar").write_text(
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\n" + "".join(row + "\\n" for row in rows),
        encoding="utf-8",
    )
    Path(str(prefix) + ".psam").write_text(psam, encoding="utf-8")
    Path(str(prefix) + ".pgen").write_bytes(b"pgen-stub-" + str(len(rows)).encode())


if "--bfile" in argv:
    source = Path(argv[argv.index("--bfile") + 1])
    rows = []
    for line in source.with_suffix(".bim").read_text(encoding="utf-8").splitlines():
        chrom, marker, _cm, pos, first, second = line.split()
        rows.append("\\t".join((chrom, pos, marker, first, second)))
    samples = ["#FID\\tIID\\tSEX"]
    for line in source.with_suffix(".fam").read_text(encoding="utf-8").splitlines():
        family, sample, _father, _mother, sex, _phenotype = line.split()
        samples.append("\\t".join((family, sample, sex)))
    write_pgen(out, rows, "\\n".join(samples) + "\\n")
elif "--indep-pairwise" in argv:
    source = Path(argv[argv.index("--pfile") + 1])
    kept = [row.split("\\t")[2] for row in pvar_rows(source)[::2]]
    Path(str(out) + ".prune.in").write_text("\\n".join(kept) + "\\n", encoding="utf-8")
elif "--extract" in argv:
    source = Path(argv[argv.index("--pfile") + 1])
    wanted = set(Path(argv[argv.index("--extract") + 1]).read_text(encoding="utf-8").split())
    rows = [row for row in pvar_rows(source) if row.split("\\t")[2] in wanted]
    psam = Path(str(source) + ".psam").read_text(encoding="utf-8")
    write_pgen(out, rows, psam)
"""


@pytest.fixture
def plink_log(
    stub_plink2: Callable[[str], Plink2],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    log = tmp_path / "commands.log"
    monkeypatch.setenv("STUB_LOG", str(log))
    plink = stub_plink2(PLINK_STUB)
    monkeypatch.setattr(Plink2, "discover", classmethod(lambda cls: plink))
    return log


def modern_source() -> manifest.Source:
    entries = "\n".join(
        f"      - url: https://example.org/test{suffix}\n"
        f"        filename: test{suffix}\n"
        f"        sha256: {'a' * 64}\n"
        "        size_bytes: 1000000"
        for suffix in (".snp", ".ind", ".geno", ".anno")
    )
    return manifest.loads(
        f"""
schema_version: 1
sources:
  - id: synthetic_aadr
    name: Synthetic AADR
    tier: A
    version: test
    homepage: https://example.org/
    license: CC0-1.0
    post_process:
      - step: build_modern_reference_panel
        params:
          output: {OUTPUT}
    files:
{entries}
"""
    ).get("synthetic_aadr")


def modern_payloads(root: Path) -> tuple[manifest.Source, Path]:
    source = modern_source()
    directory = root / source.id
    directory.mkdir(parents=True)
    people = cohort("Druze", 21)
    build(directory, people, [diploid(i) for i in range(21)])
    return source, directory


def run_transform(source: manifest.Source, root: Path, **kwargs: object):  # type: ignore[no-untyped-def]
    return postprocess.run(source, root=root, **kwargs)[0]  # type: ignore[arg-type]


def transform_commands(log: Path) -> list[list[str]]:
    if not log.is_file():
        return []
    return [line.split("|") for line in log.read_text(encoding="utf-8").splitlines()]


def test_the_transform_selects_then_filters_prunes_and_promotes(
    tmp_path: Path, plink_log: Path
) -> None:
    source, directory = modern_payloads(tmp_path)

    result = run_transform(source, tmp_path)

    assert result.status is ProcessStatus.CREATED
    assert result.rows == AUTOSOMAL // 2
    assert (directory / OUTPUT).is_file()
    assert not (directory / f".{OUTPUT}.work").exists()

    commands = transform_commands(plink_log)
    assert len(commands) == 3
    convert, prune, extract = commands
    assert "--bfile" in convert and "--sort-vars" in convert
    assert convert[convert.index("--rm-dup") + 1] == "exclude-all"
    assert convert[convert.index("--snps-only") + 1] == "just-acgt"
    assert "--indep-pairwise" in prune
    assert "--extract" in extract

    sidecar = json.loads((directory / f"{OUTPUT}.provenance.json").read_text(encoding="utf-8"))
    assert sidecar["settings"]["min_group"] == MIN_POPULATION_SAMPLES
    assert sidecar["selection"]["n_individuals"] == 21
    assert sidecar["selection"]["groups"] == ["Druze"]
    psam = (directory / "modern_panel_ldpruned.psam").read_text(encoding="utf-8")
    assert "#FID\tIID" in psam
    assert "Druze\tDruze_0" in psam


def test_the_transform_digest_covers_the_annotation_sheet(tmp_path: Path, plink_log: Path) -> None:
    source, directory = modern_payloads(tmp_path)
    assert run_transform(source, tmp_path).status is ProcessStatus.CREATED
    (directory / "test.anno").write_text("a different release\n", encoding="utf-8")

    result = run_transform(source, tmp_path, verify_only=True)

    assert result.status is ProcessStatus.FAILED
    assert "stale" in result.detail
    assert len(transform_commands(plink_log)) == 3


def test_a_malformed_packed_archive_is_a_failed_transform_not_a_traceback(
    tmp_path: Path, plink_log: Path
) -> None:
    source, directory = modern_payloads(tmp_path)
    geno = directory / "test.geno"
    geno.write_bytes(geno.read_bytes()[:-1])

    result = run_transform(source, tmp_path)

    assert result.status is ProcessStatus.FAILED
    assert "bytes where" in result.detail
    assert transform_commands(plink_log) == []
    assert not (directory / OUTPUT).exists()


def test_the_modern_transform_is_public_reference_data_not_user_derived() -> None:
    step = postprocess.STEPS["build_modern_reference_panel"]
    assert step.implemented
    assert not step.output_is_genotype_derived
