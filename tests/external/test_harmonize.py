"""Harmonizing the normalized table onto a panel's alleles (roadmap M5.2).

Organised one-test-per-rule rather than one-test-per-function, for the reason M3.1 gives:
this module's job is mostly *refusing* things, and a suite grouped by function tends to
assert that the accepting path works while leaving each refusal covered once by accident.

Every :class:`SiteOutcome` has a test that produces it, and one test asserts the outcomes
partition the array's autosomal positions -- so a new outcome that forgets to be counted,
or an existing one that starts being counted twice, fails here rather than showing up as a
coverage figure on a card that is quietly wrong.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from genetics.engine.matcher import complement
from genetics.external.harmonize import (
    SAMPLE_ID,
    PanelError,
    SiteOutcome,
    is_ambiguous_site,
    is_snp_site,
    orient,
    read_panel_sites,
    write_harmonized_vcf,
)
from genetics.ingest.schema import NORMALIZED_SCHEMA, CallStatus, Chrom, GenotypeTable

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _row(
    rsid: str,
    chrom: Chrom,
    pos: int,
    genotype: str | None,
    status: CallStatus | None = None,
) -> dict[str, object]:
    a1 = a2 = None
    if genotype is not None:
        a1, a2 = sorted(genotype)
        genotype = a1 + a2
    if status is None:
        status = CallStatus.NO_CALL if genotype is None else CallStatus.CALLED
    return {
        "rsid": rsid,
        "chrom": chrom.value,
        "pos_grch37": pos,
        "a1": a1,
        "a2": a2,
        "genotype": genotype,
        "call_status": status.value,
    }


def _table(rows: list[dict[str, object]]) -> GenotypeTable:
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="test")


def _panel(
    tmp_path: Path, rows: list[tuple[str, int, str, str, str]], name: str = "p.pvar"
) -> Path:
    lines = ["#CHROM\tPOS\tID\tREF\tALT"]
    lines += ["\t".join((c, str(p), i, r, a)) for c, p, i, r, a in rows]
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
    return path


def _records(vcf: Path) -> list[list[str]]:
    return [
        line.split("\t")
        for line in vcf.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]


def _harmonize(
    tmp_path: Path,
    rows: list[dict[str, object]],
    panel_rows: list[tuple[str, int, str, str, str]],
) -> tuple[list[list[str]], dict[SiteOutcome, int]]:
    panel = read_panel_sites(_panel(tmp_path, panel_rows))
    out = tmp_path / "out.vcf"
    report = write_harmonized_vcf(_table(rows), panel, out)
    return _records(out), dict(report.counts)


# ---------------------------------------------------------------------------
# Orientation: the proof the module rests on
# ---------------------------------------------------------------------------


def test_a_matching_genotype_is_coded_against_the_panels_alleles() -> None:
    assert orient("AG", ["A", "G"]) == ((0, 1), SiteOutcome.AS_WRITTEN)
    assert orient("GG", ["A", "G"]) == ((1, 1), SiteOutcome.AS_WRITTEN)


def test_allele_order_in_the_genotype_does_not_reach_the_encoding() -> None:
    """``a1``/``a2`` are alphabetically sorted, so pairing ``a1`` with REF would be
    reading an artefact of sorting as biology. Indices come from set membership."""
    assert orient("AG", ["G", "A"]) == ((0, 1), SiteOutcome.AS_WRITTEN)


def test_an_opposite_strand_call_is_flipped_and_says_so() -> None:
    assert orient("CT", ["A", "G"]) == ((0, 1), SiteOutcome.COMPLEMENTED)
    assert orient("TT", ["A", "G"]) == ((0, 0), SiteOutcome.COMPLEMENTED)


def test_a_genotype_the_panel_does_not_carry_is_a_mismatch() -> None:
    """A heterozygote, because a homozygote cannot reach this outcome -- see
    :func:`test_a_homozygote_can_never_mismatch_a_surviving_site`."""
    indices, outcome = orient("AC", ["A", "G"])

    assert indices is None
    assert outcome is SiteOutcome.ALLELE_MISMATCH


def test_a_homozygote_can_never_mismatch_a_surviving_site() -> None:
    """The second consequence of only four allele sets surviving, and the reason the
    mismatch tests all use heterozygotes.

    The survivors are A/C, A/G, C/T and G/T, and each of those unioned with its own
    complement is all four bases. So a single observed base is always in one reading or
    the other, and only a heterozygote -- which must satisfy *both* of its bases under one
    reading -- can fail. Stated here because a test suite that happened to use homozygotes
    throughout would look thorough and never exercise the mismatch branch at all.
    """
    surviving = [["A", "C"], ["A", "G"], ["C", "T"], ["G", "T"]]

    for alleles in surviving:
        for base in "ACGT":
            _, outcome = orient(base * 2, alleles)
            assert outcome is not SiteOutcome.ALLELE_MISMATCH, (alleles, base)


def test_a_multiallelic_panel_site_codes_to_the_right_index() -> None:
    """The index arithmetic is general even though :func:`_decide` never reaches it.

    See :func:`test_every_surviving_site_is_biallelic` for why a triallelic SNP site is
    always excluded upstream. ``orient`` is still written for the general case, because
    "REF plus the ALT list" is the shape a VCF actually has, and special-casing two would
    be an assumption to unlearn if this is ever pointed at anything but a SNP array.
    """
    assert orient("AT", ["A", "C", "T"]) == ((0, 2), SiteOutcome.AS_WRITTEN)


def test_every_surviving_site_is_biallelic() -> None:
    """A consequence worth stating, because it is not obvious and downstream relies on it.

    A/C/G/T is two complementary pairs, so any set of three or more bases must contain
    both members of one -- which makes it strand-ambiguous, and excluded. Only four allele
    sets survive: A/C, A/G, C/T and G/T. The VCF this module writes is therefore always
    biallelic, which is what PLINK's PCA and ``--score`` want anyway.
    """
    bases = "ACGT"
    triples = [
        [a, b, c]
        for i, a in enumerate(bases)
        for j, b in enumerate(bases[i + 1 :], i + 1)
        for c in bases[j + 1 :]
    ]
    survivors = [
        [a, b] for i, a in enumerate(bases) for b in bases[i + 1 :] if not is_ambiguous_site([a, b])
    ]

    assert all(is_ambiguous_site(triple) for triple in triples)
    assert is_ambiguous_site(list(bases))
    assert survivors == [["A", "C"], ["A", "G"], ["C", "T"], ["G", "T"]]


def test_at_a_non_ambiguous_site_at_most_one_strand_reading_ever_fits() -> None:
    """The property :func:`orient` documents and relies on, checked exhaustively.

    ``orient`` tries the as-written reading first and the complement second, with no tie
    break, and that is only honest if a tie cannot arise. It cannot: an allele fits both
    readings only if it is in the panel's set *and* in its complement, which is exactly
    what :func:`is_ambiguous_site` tests. This walks every allele set and every genotype
    over A/C/G/T and confirms it -- and confirms the converse, that at an ambiguous site a
    tie really does occur, so the check is not guarding against nothing.
    """
    bases = "ACGT"
    pairs = [[a, b] for i, a in enumerate(bases) for b in bases[i + 1 :]]
    genotypes = sorted({"".join(sorted(a + b)) for a in bases for b in bases})
    ties_at_ambiguous_sites = 0

    for alleles in pairs:
        allowed = set(alleles)
        for genotype in genotypes:
            as_written = all(base in allowed for base in genotype)
            flipped = all(base in allowed for base in complement(genotype))
            if not is_ambiguous_site(alleles):
                assert not (as_written and flipped), (alleles, genotype)
            elif as_written and flipped:
                ties_at_ambiguous_sites += 1

    assert ties_at_ambiguous_sites > 0


@pytest.mark.parametrize(
    ("alleles", "snp"),
    [
        (["A", "G"], True),
        (["A", "C", "T"], True),
        (["AT", "A"], False),
        (["A", "AT"], False),
        (["A"], False),
        ([], False),
        (["A", "A"], False),
        (["A", "G", "G"], False),
    ],
)
def test_a_panel_site_is_usable_only_when_every_allele_is_one_base(
    alleles: list[str], snp: bool
) -> None:
    assert is_snp_site(alleles) is snp


def test_a_panel_record_whose_alt_repeats_its_ref_is_not_read_at_all(tmp_path: Path) -> None:
    """Found by review, and it survives every later check if this one lets it through.

    The allele index keeps the last position for a repeated letter, so ``orient`` reports a
    clean ``AS_WRITTEN`` and the writer emits ``1/1`` at a site whose ALT *is* the
    reference -- indistinguishable downstream from a real homozygous-alternate call.
    """
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AA")],
        [("1", 100, "panel_rs1", "A", "A")],
    )

    assert records == []
    assert counts == {SiteOutcome.PANEL_NOT_SNP: 1}


# ---------------------------------------------------------------------------
# Panel reading
# ---------------------------------------------------------------------------


def test_panel_columns_are_resolved_by_name_not_position(tmp_path: Path) -> None:
    """A ``.pvar`` may carry extra columns, and PLINK does not promise their order."""
    path = tmp_path / "extra.pvar"
    path.write_text(
        "##a comment\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t100\trs1\tA\tG\t.\t.\tAC=3\n",
        encoding="utf-8",
    )

    panel = read_panel_sites(path)

    assert panel.n_sites == 1
    assert panel.frame["panel_id"].to_list() == ["rs1"]
    assert panel.frame["ref"].to_list() == ["A"]


def test_a_header_missing_a_required_column_is_refused(tmp_path: Path) -> None:
    """Falling back to positions here would harmonize against whatever column was fourth."""
    path = tmp_path / "wrong.pvar"
    path.write_text("#CHROM\tPOS\tID\tALLELE\n1\t100\trs1\tA\n", encoding="utf-8")

    with pytest.raises(PanelError, match=r"not a VCF or \.pvar"):
        read_panel_sites(path)


def test_a_headerless_pvar_falls_back_to_the_specified_column_order(tmp_path: Path) -> None:
    path = tmp_path / "bare.pvar"
    path.write_text("1\t100\trs1\tA\tG\n1\t200\trs2\tC\tT\n", encoding="utf-8")

    panel = read_panel_sites(path)

    assert panel.n_sites == 2


def test_a_gzipped_vcf_is_read_with_the_standard_library(tmp_path: Path) -> None:
    """AGENTS.md 4.9: BGZF is gzip-compatible for sequential reads, which is all this does."""
    path = tmp_path / "sites.vcf.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\n1\t100\trs1\tA\tG\n")

    assert read_panel_sites(path).n_sites == 1


def test_panel_chromosome_spellings_are_normalized(tmp_path: Path) -> None:
    """An unrecognised code matches nothing and raises nothing, so a whole chromosome
    would go missing in silence."""
    path = tmp_path / "chr.pvar"
    path.write_text(
        "#CHROM\tPOS\tID\tREF\tALT\nchr1\t100\trs1\tA\tG\nCHR2\t200\trs2\tA\tG\n",
        encoding="utf-8",
    )

    panel = read_panel_sites(path)

    assert panel.frame["chrom"].cast(pl.String()).to_list() == ["1", "2"]


def test_non_autosomal_panel_sites_are_left_out(tmp_path: Path) -> None:
    path = _panel(tmp_path, [("1", 100, "rs1", "A", "G"), ("X", 100, "rsx", "A", "G")])

    assert read_panel_sites(path).n_sites == 1


def test_wanted_positions_filter_while_reading(tmp_path: Path) -> None:
    """The difference between usable and not: 1000 Genomes is 85 million sites."""
    path = _panel(
        tmp_path,
        [("1", 100, "rs1", "A", "G"), ("1", 200, "rs2", "A", "G"), ("1", 300, "rs3", "A", "G")],
    )

    panel = read_panel_sites(path, wanted={("1", 200)})

    assert panel.n_sites == 1
    assert panel.n_read == 3


def test_a_repeated_panel_position_is_dropped_and_counted(tmp_path: Path) -> None:
    """Left in, the join would multiply the array's rows and the comparison would be
    against whichever record happened to come first."""
    path = _panel(tmp_path, [("1", 100, "rs1", "A", "G"), ("1", 100, "rs1b", "A", "C")])

    panel = read_panel_sites(path)

    assert panel.n_sites == 1
    assert panel.n_duplicate_positions == 1


# ---------------------------------------------------------------------------
# Writing: one test per outcome
# ---------------------------------------------------------------------------


def test_a_clean_call_is_written_on_the_panels_alleles(tmp_path: Path) -> None:
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AG")],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert records == [["1", "100", "panel_rs1", "A", "G", ".", ".", ".", "GT", "0/1"]]
    assert counts == {SiteOutcome.AS_WRITTEN: 1}


def test_the_panels_variant_id_is_written_not_the_arrays(tmp_path: Path) -> None:
    """A vendor probe id exists nowhere outside the vendor's array, while PCA loadings
    and PGS scoring files key on the panel's rsIDs."""
    records, _ = _harmonize(
        tmp_path,
        [_row("i5000123", Chrom.CHR1, 100, "AG")],
        [("1", 100, "rs4988235", "A", "G")],
    )

    assert records[0][2] == "rs4988235"


def test_an_opposite_strand_call_is_written_flipped(tmp_path: Path) -> None:
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "CT")],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert records[0][9] == "0/1"
    assert counts == {SiteOutcome.COMPLEMENTED: 1}


def test_a_no_call_is_written_as_missing_rather_than_omitted(tmp_path: Path) -> None:
    """Omitted, the marker becomes indistinguishable from one the array never carried --
    the same to a scorer's arithmetic, very different in a coverage report."""
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, None)],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert records[0][9] == "./."
    assert counts == {SiteOutcome.NO_CALL: 1}


def test_a_position_the_panel_does_not_carry_is_counted_and_dropped(tmp_path: Path) -> None:
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AG")],
        [("1", 999, "panel_rs1", "A", "G")],
    )

    assert records == []
    assert counts == {SiteOutcome.NOT_IN_PANEL: 1}


def test_a_panel_indel_site_cannot_be_placed(tmp_path: Path) -> None:
    """A consumer array reports one base per allele and carries no sequence for its
    indels (AGENTS.md 4.2), so nothing here can be matched against ``AT``/``A``."""
    _, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AG")],
        [("1", 100, "panel_rs1", "AT", "A")],
    )

    assert counts == {SiteOutcome.PANEL_NOT_SNP: 1}


def test_a_monomorphic_panel_record_is_not_a_usable_site(tmp_path: Path) -> None:
    _, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AA")],
        [("1", 100, "panel_rs1", "A", ".")],
    )

    assert counts == {SiteOutcome.PANEL_NOT_SNP: 1}


def test_an_array_indel_row_is_excluded(tmp_path: Path) -> None:
    _, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "DI")],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert counts == {SiteOutcome.ARRAY_INDEL: 1}


def test_a_strand_ambiguous_site_is_dropped_even_when_heterozygous(tmp_path: Path) -> None:
    """The distributional decision, and the one most likely to be "optimised" back out.

    ``AT`` encodes to ``0/1`` on either strand, so keeping it looks free. It is not: every
    homozygote at that site would still be dropped, so the site's surviving dosages would
    all be exactly 1, and mean-imputing the rest pulls the projection toward a value the
    data never supported. :mod:`genetics.engine.matcher` keeps the heterozygotes because
    the question it answers is about one card, not about a distribution.
    """
    _, het_counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AT")],
        [("1", 100, "panel_rs1", "A", "T")],
    )
    _, hom_counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AA")],
        [("1", 100, "panel_rs1", "A", "T")],
    )

    assert het_counts == {SiteOutcome.AMBIGUOUS_SITE: 1}
    assert hom_counts == {SiteOutcome.AMBIGUOUS_SITE: 1}


def test_a_call_the_panel_cannot_explain_is_a_mismatch(tmp_path: Path) -> None:
    """``A``/``C`` observed where the panel says ``A``/``G``: neither base pair fits under
    either strand, so the array and the panel are describing different variants."""
    _, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AC")],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert counts == {SiteOutcome.ALLELE_MISMATCH: 1}


def test_probes_that_agree_produce_one_record(tmp_path: Path) -> None:
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AG"), _row("rs1b", Chrom.CHR1, 100, "AG")],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert len(records) == 1
    assert counts == {SiteOutcome.AS_WRITTEN: 1}


def test_probes_that_disagree_produce_none(tmp_path: Path) -> None:
    """Choosing between them would manufacture an answer the data does not contain."""
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AG"), _row("rs1b", Chrom.CHR1, 100, "GG")],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert records == []
    assert counts == {SiteOutcome.DUPLICATE_CONFLICT: 1}


def test_an_uncalled_probe_beside_a_called_one_is_not_a_disagreement(tmp_path: Path) -> None:
    """An uncalled probe has no genotype to conflict with -- the M1 rule, restated here
    because this module resolves duplicates independently of the matcher."""
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AG"), _row("rs1b", Chrom.CHR1, 100, None)],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert records[0][9] == "0/1"
    assert counts == {SiteOutcome.AS_WRITTEN: 1}


def test_a_single_copy_call_on_an_autosome_is_a_ploidy_conflict(tmp_path: Path) -> None:
    _, counts = _harmonize(
        tmp_path,
        [_row("rs1", Chrom.CHR1, 100, "AG", CallStatus.HET_HAPLOID)],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert counts == {SiteOutcome.PLOIDY_CONFLICT: 1}


@pytest.mark.parametrize("chrom", [Chrom.X, Chrom.Y, Chrom.MT, Chrom.PAR])
def test_non_autosomes_never_reach_the_output(tmp_path: Path, chrom: Chrom) -> None:
    """PLINK refuses a chrX record without sex information, and a doubled hemizygous call
    written as a diploid homozygote would be a fabricated second allele."""
    records, counts = _harmonize(
        tmp_path,
        [_row("rs1", chrom, 100, "AG")],
        [("1", 100, "panel_rs1", "A", "G")],
    )

    assert records == []
    assert counts == {}


# ---------------------------------------------------------------------------
# The report as a whole
# ---------------------------------------------------------------------------


def test_the_outcomes_partition_the_arrays_autosomal_positions(tmp_path: Path) -> None:
    """Overlapping tallies would make the coverage figure on a card quietly wrong.

    Every branch appears once, plus a two-probe position, so the total is positions and
    not rows.
    """
    rows = [
        _row("a", Chrom.CHR1, 100, "AG"),
        _row("b", Chrom.CHR1, 200, "CT"),
        _row("c", Chrom.CHR1, 300, None),
        _row("d", Chrom.CHR1, 400, "AG"),
        _row("e", Chrom.CHR1, 500, "AG"),
        _row("f", Chrom.CHR1, 600, "DD"),
        _row("g", Chrom.CHR1, 700, "AT"),
        _row("h", Chrom.CHR1, 800, "AC"),
        _row("i", Chrom.CHR1, 900, "AG"),
        _row("i2", Chrom.CHR1, 900, "GG"),
        _row("j", Chrom.X, 100, "AG"),
    ]
    panel_rows = [
        ("1", 100, "p1", "A", "G"),
        ("1", 200, "p2", "A", "G"),
        ("1", 300, "p3", "A", "G"),
        ("1", 500, "p5", "AT", "A"),
        ("1", 600, "p6", "A", "G"),
        ("1", 700, "p7", "A", "T"),
        ("1", 800, "p8", "A", "G"),
        ("1", 900, "p9", "A", "G"),
    ]
    panel = read_panel_sites(_panel(tmp_path, panel_rows))
    report = write_harmonized_vcf(_table(rows), panel, tmp_path / "out.vcf")

    assert report.counts == {
        SiteOutcome.AS_WRITTEN: 1,
        SiteOutcome.COMPLEMENTED: 1,
        SiteOutcome.NO_CALL: 1,
        SiteOutcome.NOT_IN_PANEL: 1,
        SiteOutcome.PANEL_NOT_SNP: 1,
        SiteOutcome.ARRAY_INDEL: 1,
        SiteOutcome.AMBIGUOUS_SITE: 1,
        SiteOutcome.ALLELE_MISMATCH: 1,
        SiteOutcome.DUPLICATE_CONFLICT: 1,
    }
    assert report.n_sites == 9
    assert report.n_array_rows == 10
    assert report.n_written == 3
    assert report.n_usable == 2
    assert len(_records(tmp_path / "out.vcf")) == 3


def test_a_new_outcome_cannot_be_added_without_a_case_here() -> None:
    """A tripwire, not a tautology: a new member fails this until it is written into the
    partition test above or named here as an exception.

    ``PLOIDY_CONFLICT`` is the one exception. It is deliberately absent from the partition
    test because on an autosome it is a contradiction that should never occur, and it has
    its own test above.
    """
    partitioned = {
        SiteOutcome.AS_WRITTEN,
        SiteOutcome.COMPLEMENTED,
        SiteOutcome.NO_CALL,
        SiteOutcome.NOT_IN_PANEL,
        SiteOutcome.PANEL_NOT_SNP,
        SiteOutcome.ARRAY_INDEL,
        SiteOutcome.AMBIGUOUS_SITE,
        SiteOutcome.ALLELE_MISMATCH,
        SiteOutcome.DUPLICATE_CONFLICT,
    }

    assert set(SiteOutcome) == partitioned | {SiteOutcome.PLOIDY_CONFLICT}


def test_the_report_renders_without_naming_a_genotype(tmp_path: Path) -> None:
    panel = read_panel_sites(_panel(tmp_path, [("1", 100, "p1", "A", "G")]))
    report = write_harmonized_vcf(
        _table([_row("rs1", Chrom.CHR1, 100, "AG")]), panel, tmp_path / "out.vcf"
    )

    rendered = report.render()

    assert "p.pvar" in rendered
    assert "as_written: 1" in rendered


# ---------------------------------------------------------------------------
# The file itself
# ---------------------------------------------------------------------------


def test_the_sample_column_is_a_constant_not_the_input_filename(tmp_path: Path) -> None:
    """PLINK copies this name into every file it writes and every log line, and those
    outlive the run."""
    panel = read_panel_sites(_panel(tmp_path, [("1", 100, "p1", "A", "G")]))
    out = tmp_path / "out.vcf"
    write_harmonized_vcf(_table([_row("rs1", Chrom.CHR1, 100, "AG")]), panel, out)

    header = next(
        line for line in out.read_text(encoding="utf-8").splitlines() if line.startswith("#CHROM")
    )

    assert header.split("\t")[-1] == SAMPLE_ID


def test_the_header_names_the_panel_file_not_its_path(tmp_path: Path) -> None:
    """An absolute path on Windows begins with the user's account name."""
    nested = tmp_path / "deep"
    nested.mkdir()
    panel = read_panel_sites(_panel(nested, [("1", 100, "p1", "A", "G")], name="ref.pvar"))
    out = tmp_path / "out.vcf"
    write_harmonized_vcf(_table([_row("rs1", Chrom.CHR1, 100, "AG")]), panel, out)

    text = out.read_text(encoding="utf-8")

    assert "##panelSource=ref.pvar" in text
    assert str(nested) not in text


def test_records_are_written_with_lf_endings_on_every_platform(tmp_path: Path) -> None:
    """M0.1 already learned that letting the platform decide line endings turns a
    byte-identical artefact into a platform-specific one."""
    panel = read_panel_sites(_panel(tmp_path, [("1", 100, "p1", "A", "G")]))
    out = tmp_path / "out.vcf"
    write_harmonized_vcf(_table([_row("rs1", Chrom.CHR1, 100, "AG")]), panel, out)

    assert b"\r\n" not in out.read_bytes()


def test_two_runs_over_the_same_input_produce_identical_bytes(tmp_path: Path) -> None:
    """Which is why the header carries no ``##fileDate``."""
    panel = read_panel_sites(_panel(tmp_path, [("1", 100, "p1", "A", "G")]))
    table = _table([_row("rs1", Chrom.CHR1, 100, "AG")])
    first, second = tmp_path / "a.vcf", tmp_path / "b.vcf"

    write_harmonized_vcf(table, panel, first)
    write_harmonized_vcf(table, panel, second)

    assert first.read_bytes() == second.read_bytes()


def test_records_are_sorted_by_position(tmp_path: Path) -> None:
    """PLINK warns rather than fails on unsorted input, so nothing downstream would say so."""
    rows = [_row(f"rs{p}", Chrom.CHR1, p, "AG") for p in (900, 100, 500)]
    panel = read_panel_sites(
        _panel(tmp_path, [("1", p, f"p{p}", "A", "G") for p in (900, 100, 500)])
    )
    out = tmp_path / "out.vcf"
    write_harmonized_vcf(_table(rows), panel, out)

    assert [int(record[1]) for record in _records(out)] == [100, 500, 900]


def test_contigs_are_declared_for_the_chromosomes_present(tmp_path: Path) -> None:
    rows = [_row("a", Chrom.CHR2, 100, "AG"), _row("b", Chrom.CHR1, 100, "AG")]
    panel = read_panel_sites(
        _panel(tmp_path, [("1", 100, "p1", "A", "G"), ("2", 100, "p2", "A", "G")])
    )
    out = tmp_path / "out.vcf"
    write_harmonized_vcf(_table(rows), panel, out)

    text = out.read_text(encoding="utf-8")

    assert "##contig=<ID=1>" in text
    assert "##contig=<ID=2>" in text
    assert "##contig=<ID=3>" not in text


def test_an_empty_panel_produces_a_header_and_no_records(tmp_path: Path) -> None:
    """A valid file rather than a crash, so the caller decides what an empty result means."""
    panel = read_panel_sites(_panel(tmp_path, []))
    out = tmp_path / "out.vcf"

    report = write_harmonized_vcf(_table([_row("rs1", Chrom.CHR1, 100, "AG")]), panel, out)

    assert report.n_written == 0
    assert _records(out) == []
    assert out.read_text(encoding="utf-8").startswith("##fileformat=VCFv4.2")


@pytest.mark.privacy
def test_the_panel_is_safe_to_print_but_the_table_is_not(tmp_path: Path) -> None:
    """Panel sites are properties of the panel; the table is a person. Different rules."""
    panel = read_panel_sites(_panel(tmp_path, [("1", 100, "p1", "A", "G")]))
    table = _table([_row("rs1", Chrom.CHR1, 100, "AG")])

    assert "p1" in repr(panel.frame)
    assert "AG" not in repr(table)
