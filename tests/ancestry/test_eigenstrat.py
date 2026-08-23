"""Reading the AADR's EIGENSTRAT trio (roadmap M5.6, first half).

**The fixtures here are written by the tests, in the layout measured off ``v66.p1_HO``.**
The real archive is 4 GB and is not in the checkout, so what is held to account is the
arithmetic that turns three files into genotypes: the record length, the bit order, the
size check, and every refusal. The one thing a synthetic fixture cannot establish is that
the measured layout is the real file's -- that was established by running this reader
against it, and the numbers are recorded on M5.6 and in the module docstring.

No privacy marker on any of this: AADR individuals are a published archive, not a person's
export, which is why the packed reader returns real codes where the rest of this project
returns counts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genetics.ancestry.eigenstrat import (
    CODE_MISSING,
    AadrIndividual,
    EigenstratError,
    annotate,
    open_packed,
    read_anno,
    read_ind,
    read_individuals,
    read_snp,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

HEADER_BYTES = 48
CODES_PER_BYTE = 4


def write_snp(tmp_path: Path, rows: list[tuple[str, str, int, str, str]]) -> Path:
    """A ``.snp`` file. AADR pads its columns heavily, so these do too."""
    path = tmp_path / "test.snp"
    lines = [
        f"{rsid:>20} {chrom:>5} {0.0:>15.6f} {pos:>15} {a1} {a2}"
        for rsid, chrom, pos, a1, a2 in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_ind(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    path = tmp_path / "test.ind"
    path.write_text(
        "\n".join(f"{i:>25} {sex} {group}" for i, sex, group in rows) + "\n", encoding="utf-8"
    )
    return path


def write_geno(
    tmp_path: Path, codes: list[list[int]], *, n_sites: int, magic: bytes = b"TGENO"
) -> Path:
    """A packed transposed genotype file: one record per individual.

    ``codes[i][j]`` is individual ``i``'s code at site ``j``. Packing is most-significant
    pair first within each byte, which is the order the real file uses -- verified by
    decoding Loschbour and getting the published homozygote/no-call split.
    """
    path = tmp_path / "test.geno"
    record_bytes = -(-n_sites // CODES_PER_BYTE)
    head = (magic + f"{len(codes):>8}{n_sites:>8} 0 0".encode()).ljust(HEADER_BYTES, b"\x00")
    body = bytearray()
    for row in codes:
        record = bytearray(record_bytes)
        for index, code in enumerate(row):
            record[index >> 2] |= (code & 3) << (6 - 2 * (index & 3))
        # Sites the caller did not name default to 0, not missing: the real file packs a
        # full record whatever the site count, and the trailing bits are padding.
        body += record
    path.write_bytes(head + bytes(body))
    return path


def write_anno(tmp_path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    """An ``.anno`` sheet with the real file's paragraph-length column names."""
    path = tmp_path / "test.anno"
    columns = [
        'Genetic ID (suffices: ".DG" is a high coverage shotgun genome)',
        "Persistent Genetic ID",
        "Date mean in BP in years before 1950 CE [OxCal mu]",
        "Group ID",
        "SNPs hit on autosomal targets (Computed using easystats on HO snpset)",
    ]
    lines = ["\t".join(columns)]
    lines += [f"{i}\t{i}\t{bp}\t{group}\t{snps}" for i, bp, group, snps in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------


def test_a_snp_row_reads_as_position_and_alleles(tmp_path: Path) -> None:
    path = write_snp(tmp_path, [("rs1", "1", 752566, "G", "A"), ("rs2", "2", 100, "T", "C")])

    sites = read_snp(path)

    assert sites.n_sites == sites.n_read == 2
    assert sites.frame.get_column("pos").to_list() == [752566, 100]
    assert sites.frame.get_column("a1").to_list() == ["G", "T"]
    assert sites.indices == [0, 1]


def test_wanted_narrows_while_reading_and_keeps_the_files_own_row_numbers(tmp_path: Path) -> None:
    """The index is what locates a site in the packed file, so a filtered frame that
    renumbered its rows would read a different marker's genotypes for every one."""
    path = write_snp(
        tmp_path,
        [("rs1", "1", 100, "A", "G"), ("rs2", "1", 200, "A", "G"), ("rs3", "1", 300, "A", "G")],
    )

    sites = read_snp(path, wanted={("1", 200), ("1", 300)})

    assert sites.n_sites == 2
    assert sites.n_read == 3
    assert sites.indices == [1, 2]


def test_a_blank_line_does_not_shift_every_marker_onto_another_genotype(tmp_path: Path) -> None:
    """``index`` locates a site in the packed record, and the packed record has one code per
    SNP *row* -- not per file line. Counting blank lines shifts every marker after one onto a
    different marker's genotype, and nothing downstream notices: ``open_packed``'s size check
    reads ``n_read``, which is blank-insensitive and still agrees. ``read_ind`` counts data
    rows on the same file family, so the two readers disagreed."""
    path = tmp_path / "gappy.snp"
    rows = ["", "rs1 1 0.0 100 A G", "", "rs2 1 0.0 200 A G", "rs3 1 0.0 300 A G"]
    path.write_text(chr(10).join(rows) + chr(10), encoding="utf-8")

    sites = read_snp(path)

    assert sites.n_read == 3
    assert sites.indices == [0, 1, 2]


def test_a_blank_line_does_not_shift_a_filtered_read_either(tmp_path: Path) -> None:
    path = tmp_path / "gappy.snp"
    rows = ["", "rs1 1 0.0 100 A G", "", "rs2 1 0.0 200 A G", "rs3 1 0.0 300 A G"]
    path.write_text(chr(10).join(rows) + chr(10), encoding="utf-8")

    sites = read_snp(path, wanted={("1", 300)})

    assert sites.indices == [2]


def test_a_short_snp_row_is_refused_rather_than_read_past(tmp_path: Path) -> None:
    path = tmp_path / "short.snp"
    path.write_text("rs1 1 0.0 100 A G\nrs2 1 0.0 200\n", encoding="utf-8")

    with pytest.raises(EigenstratError, match="field"):
        read_snp(path)


def test_a_non_numeric_position_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.snp"
    path.write_text("rs1 1 0.0 notanumber A G\n", encoding="utf-8")

    with pytest.raises(EigenstratError, match="non-numeric position"):
        read_snp(path)


# ---------------------------------------------------------------------------
# Individuals and annotation
# ---------------------------------------------------------------------------


def test_an_ind_row_reads_as_identifier_sex_and_group(tmp_path: Path) -> None:
    path = write_ind(tmp_path, [("Loschbour.AG", "M", "Luxembourg_Loschbour_Mesolithic")])

    individuals = read_ind(path)

    assert individuals[0].sample_id == "Loschbour.AG"
    assert individuals[0].group == "Luxembourg_Loschbour_Mesolithic"
    assert individuals[0].index == 0


def test_an_empty_ind_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.ind"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(EigenstratError, match="no individuals"):
        read_ind(path)


def test_anno_columns_are_found_by_a_substring_of_their_paragraph_long_names(
    tmp_path: Path,
) -> None:
    """The real sheet documents each field inline; the identifier column's name is four
    hundred characters of glossary. Equality or position would both fail on it."""
    path = write_anno(tmp_path, [("A.AG", "8025", "Group_One", "300000")])

    frame = read_anno(path)

    assert frame.columns == ["sample_id", "date_bp", "group", "ho_snps"]
    assert frame.get_column("date_bp").to_list() == [8025.0]


def test_a_sheet_without_a_date_column_says_which_field_it_cannot_read(tmp_path: Path) -> None:
    path = tmp_path / "thin.anno"
    path.write_text("Genetic ID\tGroup ID\tHO snpset\nA\tG\t1\n", encoding="utf-8")

    with pytest.raises(EigenstratError, match="Date mean in BP"):
        read_anno(path)


def test_present_day_individuals_are_marked_by_a_zero_not_by_a_missing_date(
    tmp_path: Path,
) -> None:
    """The resource distinguishes "sampled today" from "date unresolved", and collapsing
    them would put 8,474 living Human Origins samples into an ancient panel."""
    anno = read_anno(
        write_anno(tmp_path, [("A.HO", "0", "French", "590000"), ("B.AG", "4000", "G", "5")])
    )
    individuals = annotate(
        [
            AadrIndividual(index=0, sample_id="A.HO", sex="M", group="from_ind"),
            AadrIndividual(index=1, sample_id="B.AG", sex="F", group="from_ind"),
            AadrIndividual(index=2, sample_id="C.SG", sex="U", group="from_ind"),
        ],
        anno,
    )

    assert individuals[0].date_bp == 0.0 and individuals[0].is_ancient is False
    assert individuals[1].date_bp == 4000.0 and individuals[1].is_ancient is True
    assert individuals[2].date_bp is None and individuals[2].is_ancient is False


def test_the_sheets_group_label_wins_over_the_ind_files(tmp_path: Path) -> None:
    """The ``.ind`` copy has drifted between releases; the sheet is the curated one."""
    anno = read_anno(write_anno(tmp_path, [("A.AG", "4000", "Curated_Label", "5")]))

    individuals = annotate(
        [AadrIndividual(index=0, sample_id="A.AG", sex="M", group="stale_label")], anno
    )

    assert individuals[0].group == "Curated_Label"


def test_an_unresolved_date_becomes_null_rather_than_failing_the_read(tmp_path: Path) -> None:
    """The sheet carries ``..`` and free text in numeric columns, and an unresolved date is
    a fact about that individual rather than a broken file."""
    frame = read_anno(write_anno(tmp_path, [("A.AG", "..", "G", "n/a")]))

    assert frame.get_column("date_bp").to_list() == [None]
    assert frame.get_column("ho_snps").to_list() == [None]


# ---------------------------------------------------------------------------
# The packed genotypes
# ---------------------------------------------------------------------------


def test_codes_decode_in_the_measured_bit_order(tmp_path: Path) -> None:
    """Two bits per site, most significant pair first. Verified against the real file by
    decoding Loschbour and getting its published homozygote and no-call counts."""
    rows = [[0, 1, 2, CODE_MISSING, 2], [2, 2, 0, 0, 1]]
    path = write_geno(tmp_path, rows, n_sites=5)
    packed = open_packed(path, n_individuals=2, n_sites=5)

    read = dict(read_individuals(packed, [0, 1], list(range(5))))

    assert read[0] == [0, 1, 2, CODE_MISSING, 2]
    assert read[1] == [2, 2, 0, 0, 1]


def test_only_the_requested_sites_come_back_and_in_the_order_asked(tmp_path: Path) -> None:
    """A caller lines these up against its own site frame row for row, so the order is part
    of the contract rather than an accident of iteration."""
    path = write_geno(tmp_path, [[0, 1, 2, 0, 1, 2, 0, 1]], n_sites=8)
    packed = open_packed(path, n_individuals=1, n_sites=8)

    _index, codes = next(iter(read_individuals(packed, [0], [5, 1, 7])))

    assert codes == [2, 1, 1]


def test_only_the_requested_individuals_are_read(tmp_path: Path) -> None:
    """What the transposed layout buys: selecting people costs a seek each rather than a
    pass over four gigabytes."""
    path = write_geno(tmp_path, [[0] * 4, [1] * 4, [2] * 4], n_sites=4)
    packed = open_packed(path, n_individuals=3, n_sites=4)

    read = list(read_individuals(packed, [2, 0], [0]))

    assert [index for index, _codes in read] == [2, 0]
    assert [codes for _i, codes in read] == [[2], [0]]


def test_the_record_length_is_derived_from_the_site_count(tmp_path: Path) -> None:
    path = write_geno(tmp_path, [[0] * 9], n_sites=9)

    packed = open_packed(path, n_individuals=1, n_sites=9)

    assert packed.record_bytes == 3  # ceil(9 / 4)


def test_a_size_that_does_not_match_the_geometry_is_refused(tmp_path: Path) -> None:
    """A packed file has no per-record framing, so a truncated one does not fail to parse --
    it reads shifted, and every genotype past the discrepancy is a different marker's."""
    path = write_geno(tmp_path, [[0] * 8, [1] * 8], n_sites=8)
    path.write_bytes(path.read_bytes()[:-1])

    with pytest.raises(EigenstratError, match="bytes where"):
        open_packed(path, n_individuals=2, n_sites=8)


def test_header_counts_disagreeing_with_the_companion_files_are_refused(tmp_path: Path) -> None:
    path = write_geno(tmp_path, [[0] * 8], n_sites=8)

    with pytest.raises(EigenstratError, match="not one dataset"):
        open_packed(path, n_individuals=2, n_sites=8)


def test_a_snp_major_geno_file_is_refused_rather_than_guessed_at(tmp_path: Path) -> None:
    """Its layout is documented and would be a dozen lines, but no GENO file is pinned here
    -- so that dozen lines would be untested code between an archive and an ancestry claim."""
    path = write_geno(tmp_path, [[0] * 8], n_sites=8, magic=b"GENO")

    with pytest.raises(EigenstratError, match="SNP-major GENO"):
        open_packed(path, n_individuals=1, n_sites=8)


def test_a_file_that_is_not_packed_eigenstrat_at_all_says_so(tmp_path: Path) -> None:
    path = tmp_path / "other.geno"
    path.write_bytes(b"PLINKBED" + b"\x00" * 200)

    with pytest.raises(EigenstratError, match="not a packed"):
        open_packed(path, n_individuals=1, n_sites=8)


def test_an_individual_outside_the_file_is_refused(tmp_path: Path) -> None:
    path = write_geno(tmp_path, [[0] * 4], n_sites=4)
    packed = open_packed(path, n_individuals=1, n_sites=4)

    with pytest.raises(EigenstratError, match="outside the"):
        list(read_individuals(packed, [7], [0]))
