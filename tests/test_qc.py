"""Tests for the QC module (roadmap M1.5).

The consequential thing here is sex inference, because it decides how the entire X and Y
are *read*. Get it wrong on a male sample and the hemizygous X reads as a genome-wide run
of homozygosity, which would arrive in the autozygosity card (M6.2) as a striking and
entirely false finding. So the tests below check not only that the inference is right on
the fixtures, but that it *refuses* rather than guesses when the signals disagree.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from genetics.ingest import ingest, read_export
from genetics.ingest.schema import (
    NORMALIZED_SCHEMA,
    CallStatus,
    Chrom,
    GenotypeTable,
)
from genetics.qc import (
    InferredSex,
    QCReport,
    call_rates,
    check_build,
    duplicate_summary,
    heterozygosity,
    infer_sex,
    resolve_ploidy,
    run_qc,
)
from genetics.qc.build_anchors import ANCHORS, BuildAnchor
from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR


def fixture(name: str) -> Path:
    path = DEFAULT_FIXTURE_DIR / name
    if not path.exists():
        pytest.skip("fixtures not generated; run `genetics fixtures`")
    return path


def synthetic_table(rows: list[dict[str, object]]) -> GenotypeTable:
    """Build a normalized table directly, for cases no fixture covers."""
    frame = pl.DataFrame(rows, schema=NORMALIZED_SCHEMA)
    return GenotypeTable(frame, vendor="test")


def _row(
    rsid: str,
    chrom: Chrom,
    pos: int,
    a1: str | None,
    a2: str | None,
) -> dict[str, object]:
    lo: str | None = None
    hi: str | None = None
    genotype: str | None = None
    if a1 is not None and a2 is not None:
        lo, hi = sorted([a1, a2])
        genotype = lo + hi

    return {
        "rsid": rsid,
        "chrom": chrom.value,
        "pos_grch37": pos,
        "a1": lo,
        "a2": hi,
        "genotype": genotype,
        "call_status": (CallStatus.NO_CALL if genotype is None else CallStatus.CALLED).value,
    }


def sex_chrom_table(
    *, x_het_fraction: float, y_call_fraction: float, n: int = 400
) -> GenotypeTable:
    """A table with the X and Y profile needed to drive sex inference."""
    rows: list[dict[str, object]] = []
    n_het = int(n * x_het_fraction)
    for i in range(n):
        x_alleles: tuple[str | None, str | None] = ("A", "G") if i < n_het else ("A", "A")
        rows.append(_row(f"rs{700000000 + i}", Chrom.X, 1000 + i, *x_alleles))

    n_called = int(n * y_call_fraction)
    for i in range(n):
        y_alleles: tuple[str | None, str | None] = ("T", "T") if i < n_called else (None, None)
        rows.append(_row(f"rs{710000000 + i}", Chrom.Y, 1000 + i, *y_alleles))

    # A little autosomal ballast so the other metrics have something to report.
    for i in range(n):
        rows.append(_row(f"rs{720000000 + i}", Chrom.CHR1, 1000 + i, "A", "G"))

    return synthetic_table(rows)


# ---------------------------------------------------------------------------
# Sex inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ancestry_v2_male.txt", InferredSex.MALE),
        ("ancestry_v2_female.txt", InferredSex.FEMALE),
        ("ancestry_v2_high_nocall.txt", InferredSex.FEMALE),
        ("other_vendor_layout.txt", InferredSex.MALE),
    ],
)
def test_infers_sex_on_every_fixture(name: str, expected: InferredSex) -> None:
    result = ingest(fixture(name))
    assert isinstance(result.qc, QCReport)
    assert result.qc.sex.inferred is expected


def test_male_x_heterozygosity_is_near_zero() -> None:
    """The hemizygous X is written doubled, so it looks homozygous throughout."""
    result = ingest(fixture("ancestry_v2_male.txt"))
    assert isinstance(result.qc, QCReport)
    assert result.qc.sex.x_het_rate < 0.01
    assert result.qc.sex.y_call_rate > 0.9


def test_female_y_is_entirely_uncalled() -> None:
    result = ingest(fixture("ancestry_v2_female.txt"))
    assert isinstance(result.qc, QCReport)
    assert result.qc.sex.y_call_rate == 0.0
    assert result.qc.sex.x_het_rate > 0.2


def test_disagreeing_signals_produce_ambiguous_not_a_guess() -> None:
    """Male-looking X with female-looking Y. Refusing is the point.

    A sex-chromosome aneuploidy looks exactly like this, and M6.4 has a card for it.
    Picking the likelier answer would silently change how every X and Y call is read.
    """
    table = sex_chrom_table(x_het_fraction=0.0, y_call_fraction=0.0)
    het = heterozygosity(table)
    sex = infer_sex(table, het)

    assert sex.inferred is InferredSex.AMBIGUOUS
    assert any("do not agree" in note for note in sex.notes)


def test_intermediate_x_heterozygosity_is_ambiguous() -> None:
    table = sex_chrom_table(x_het_fraction=0.10, y_call_fraction=0.9)
    sex = infer_sex(table, heterozygosity(table))
    assert sex.inferred is InferredSex.AMBIGUOUS


def test_too_few_x_loci_is_ambiguous_with_a_reason() -> None:
    table = sex_chrom_table(x_het_fraction=0.0, y_call_fraction=0.99, n=20)
    sex = infer_sex(table, heterozygosity(table))

    assert sex.inferred is InferredSex.AMBIGUOUS
    assert any("too sparse" in note for note in sex.notes)


def test_a_layout_with_no_y_markers_decides_on_x_alone_and_says_so() -> None:
    rows = [_row(f"rs{700000000 + i}", Chrom.X, 1000 + i, "A", "A") for i in range(400)]
    sex = infer_sex(synthetic_table(rows), heterozygosity(synthetic_table(rows)))

    assert sex.inferred is InferredSex.MALE
    assert any("no Y markers" in note for note in sex.notes)


def test_par_is_excluded_from_the_x_heterozygosity_rate() -> None:
    """PAR is diploid in both sexes. Folding it into X would give every male a nonzero
    rate and blunt the one signal that separates the two cleanly."""
    rows = [_row(f"rs{700000000 + i}", Chrom.X, 1000 + i, "A", "A") for i in range(200)]
    rows += [_row(f"rs{730000000 + i}", Chrom.PAR, 1000 + i, "A", "G") for i in range(200)]

    het = heterozygosity(synthetic_table(rows))
    assert het.x_nonpar_het_rate == 0.0
    assert het.x_nonpar_loci == 200


# ---------------------------------------------------------------------------
# Ploidy resolution
# ---------------------------------------------------------------------------


def test_male_sex_chromosomes_become_hemizygous() -> None:
    result = ingest(fixture("ancestry_v2_male.txt"))
    frame = result.table.frame

    for chrom in (Chrom.X, Chrom.Y, Chrom.MT):
        called = frame.filter(
            (pl.col("chrom").cast(pl.String) == chrom.value)
            & (pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value)
        )
        statuses = set(called.get_column("call_status").cast(pl.String).unique().to_list())
        assert statuses <= {CallStatus.HEMIZYGOUS.value, CallStatus.HET_HAPLOID.value}, chrom


def test_par_stays_diploid_in_a_male() -> None:
    result = ingest(fixture("ancestry_v2_male.txt"))
    par = result.table.frame.filter(
        (pl.col("chrom").cast(pl.String) == Chrom.PAR.value)
        & (pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value)
    )
    assert par.height > 0
    assert set(par.get_column("call_status").cast(pl.String).unique().to_list()) == {
        CallStatus.CALLED.value
    }


def test_female_x_stays_diploid_but_mt_does_not() -> None:
    """MT is single-copy in everyone, so it resolves without knowing the sex."""
    result = ingest(fixture("ancestry_v2_female.txt"))
    frame = result.table.frame

    x = frame.filter(
        (pl.col("chrom").cast(pl.String) == Chrom.X.value)
        & (pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value)
    )
    assert set(x.get_column("call_status").cast(pl.String).unique().to_list()) == {
        CallStatus.CALLED.value
    }

    mt = frame.filter(
        (pl.col("chrom").cast(pl.String) == Chrom.MT.value)
        & (pl.col("call_status").cast(pl.String) != CallStatus.NO_CALL.value)
    )
    assert set(mt.get_column("call_status").cast(pl.String).unique().to_list()) <= {
        CallStatus.HEMIZYGOUS.value,
        CallStatus.HET_HAPLOID.value,
    }


def test_ambiguous_sex_leaves_sex_chromosomes_unresolved() -> None:
    """An unresolved locus is visibly unresolved; a wrongly resolved one is not."""
    table = sex_chrom_table(x_het_fraction=0.0, y_call_fraction=0.0)
    resolved = resolve_ploidy(table, sex=InferredSex.AMBIGUOUS)

    x = resolved.frame.filter(pl.col("chrom").cast(pl.String) == Chrom.X.value)
    assert set(x.get_column("call_status").cast(pl.String).unique().to_list()) == {
        CallStatus.CALLED.value
    }


def test_heterozygous_call_at_a_haploid_locus_is_labelled_not_dropped() -> None:
    """A contradiction, kept as its own status so it stays countable in QC."""
    rows = [_row(f"rs{700000000 + i}", Chrom.X, 1000 + i, "A", "A") for i in range(300)]
    rows.append(_row("rs799999999", Chrom.X, 99999, "A", "G"))
    table = synthetic_table(rows)

    resolved = resolve_ploidy(table, sex=InferredSex.MALE)
    statuses = resolved.frame.get_column("call_status").cast(pl.String).to_list()

    assert statuses.count(CallStatus.HET_HAPLOID.value) == 1
    assert resolved.n_markers == table.n_markers


def test_no_calls_survive_ploidy_resolution_unchanged() -> None:
    rows = [_row("rs700000001", Chrom.X, 1, None, None)]
    resolved = resolve_ploidy(synthetic_table(rows), sex=InferredSex.MALE)

    assert resolved.frame.get_column("call_status").cast(pl.String).to_list() == [
        CallStatus.NO_CALL.value
    ]


def test_resolve_ploidy_preserves_row_count_and_schema() -> None:
    table = read_export(fixture("ancestry_v2_male.txt")).table
    resolved = resolve_ploidy(table, sex=InferredSex.MALE)

    assert resolved.n_markers == table.n_markers
    assert resolved.frame.schema == table.frame.schema


# ---------------------------------------------------------------------------
# Call rates and heterozygosity
# ---------------------------------------------------------------------------


def test_call_rate_counts_add_up() -> None:
    table = read_export(fixture("ancestry_v2_high_nocall.txt")).table
    rates = call_rates(table)

    assert rates.called + rates.no_call == rates.total_markers
    assert rates.total_markers == table.n_markers
    assert sum(c.total for c in rates.by_chrom) == rates.total_markers


def test_low_call_rate_is_warned_about_not_rejected() -> None:
    """QC labels; it never filters (AGENTS.md 0.1A)."""
    result = ingest(fixture("ancestry_v2_high_nocall.txt"))
    assert isinstance(result.qc, QCReport)

    assert any("call rate" in w for w in result.qc.warnings)
    assert result.table.n_markers == result.qc.call_rates.total_markers


def test_heterozygosity_excludes_indels() -> None:
    rows = [_row(f"rs{700000000 + i}", Chrom.CHR1, 1000 + i, "A", "G") for i in range(100)]
    rows += [_row(f"rs{740000000 + i}", Chrom.CHR1, 5000 + i, "D", "I") for i in range(100)]

    het = heterozygosity(synthetic_table(rows))
    assert het.autosomal_loci == 100
    assert het.autosomal_het_rate == 1.0


def test_heterozygosity_excludes_no_calls() -> None:
    rows = [_row(f"rs{700000000 + i}", Chrom.CHR1, 1000 + i, "A", "G") for i in range(50)]
    rows += [_row(f"rs{750000000 + i}", Chrom.CHR1, 5000 + i, None, None) for i in range(50)]

    assert heterozygosity(synthetic_table(rows)).autosomal_loci == 50


def test_rates_are_zero_rather_than_dividing_by_zero() -> None:
    rows = [_row("rs700000001", Chrom.CHR1, 1, "A", "G")]
    het = heterozygosity(synthetic_table(rows))

    assert het.x_nonpar_loci == 0
    assert het.x_nonpar_het_rate == 0.0


# ---------------------------------------------------------------------------
# Duplicates and build
# ---------------------------------------------------------------------------


def test_duplicates_are_counted_as_excess_rows_not_groups() -> None:
    """Three probes at one position is two duplicates -- the number that matters when
    deciding whether it is noise or a structural problem."""
    rows = [
        _row("rs700000001", Chrom.CHR1, 100, "A", "G"),
        _row("rs700000002", Chrom.CHR1, 100, "A", "G"),
        _row("rs700000003", Chrom.CHR1, 100, "A", "G"),
    ]
    summary = duplicate_summary(synthetic_table(rows))

    assert summary.duplicate_positions == 2
    assert summary.duplicate_rsids == 0


def test_duplicates_are_reported_not_deduplicated() -> None:
    rows = [
        _row("rs700000001", Chrom.CHR1, 100, "A", "G"),
        _row("rs700000001", Chrom.CHR1, 200, "A", "G"),
    ]
    table = synthetic_table(rows)
    assert duplicate_summary(table).duplicate_rsids == 1
    assert table.n_markers == 2


def test_build_anchor_table_ships_empty_pending_m2() -> None:
    """Coordinates written from memory would be invented data (AGENTS.md 6). M2 fetches
    dbSNP; until then the mechanism is tested with injected anchors."""
    assert ANCHORS == ()


def test_unverified_anchors_cannot_trigger_a_build_failure() -> None:
    """A wrong anchor must lose information, never manufacture a false alarm."""
    rows = [_row("rs700000001", Chrom.CHR1, 111, "A", "G")]
    unverified = (
        BuildAnchor("rs700000001", Chrom.CHR1, pos_grch37=999, pos_grch38=111, gene="X"),
        BuildAnchor("rs700000002", Chrom.CHR1, pos_grch37=888, pos_grch38=222, gene="Y"),
    )
    check = check_build(synthetic_table(rows), declared="37", anchors=unverified)

    assert check.anchors_available == 0
    assert check.verdict == "indeterminate"


def test_verified_anchors_on_grch38_positions_are_detected() -> None:
    rows = [
        _row("rs700000001", Chrom.CHR1, 111, "A", "G"),
        _row("rs700000002", Chrom.CHR1, 222, "A", "G"),
    ]
    verified = (
        BuildAnchor("rs700000001", Chrom.CHR1, 999, 111, "X", source="dbSNP b156"),
        BuildAnchor("rs700000002", Chrom.CHR1, 888, 222, "Y", source="dbSNP b156"),
    )
    check = check_build(synthetic_table(rows), declared="37", anchors=verified)

    assert check.anchors_found == 2
    assert check.anchors_matching_38 == 2
    assert check.verdict == "suspected_38"


def test_a_single_matching_anchor_is_not_enough() -> None:
    """Two positions can collide across builds; one match is a coincidence waiting."""
    rows = [_row("rs700000001", Chrom.CHR1, 111, "A", "G")]
    verified = (BuildAnchor("rs700000001", Chrom.CHR1, 999, 111, "X", source="dbSNP b156"),)

    assert check_build(synthetic_table(rows), declared="37", anchors=verified).verdict == (
        "indeterminate"
    )


def test_verified_grch37_anchors_confirm_the_build() -> None:
    rows = [
        _row("rs700000001", Chrom.CHR1, 999, "A", "G"),
        _row("rs700000002", Chrom.CHR1, 888, "A", "G"),
    ]
    verified = (
        BuildAnchor("rs700000001", Chrom.CHR1, 999, 111, "X", source="dbSNP b156"),
        BuildAnchor("rs700000002", Chrom.CHR1, 888, 222, "Y", source="dbSNP b156"),
    )
    assert check_build(synthetic_table(rows), declared="37", anchors=verified).verdict == (
        "confirmed_37"
    )


def test_suspected_38_produces_the_first_warning() -> None:
    """Ordered most-consequential first: every downstream lookup would target the wrong
    locus, which dwarfs anything else QC can say."""
    from genetics.qc.metrics import _warnings

    rows = [
        _row("rs700000001", Chrom.CHR1, 111, "A", "G"),
        _row("rs700000002", Chrom.CHR1, 222, "A", "G"),
    ]
    table = synthetic_table(rows)
    verified = (
        BuildAnchor("rs700000001", Chrom.CHR1, 999, 111, "X", source="dbSNP b156"),
        BuildAnchor("rs700000002", Chrom.CHR1, 888, 222, "Y", source="dbSNP b156"),
    )
    build = check_build(table, declared="37", anchors=verified)
    het = heterozygosity(table)
    sex = infer_sex(table, het)

    warnings = _warnings(call_rates(table), het, sex, build, duplicate_summary(table), 0, table)
    assert warnings and "GRCh38" in warnings[0]


# ---------------------------------------------------------------------------
# The report as a whole
# ---------------------------------------------------------------------------


def test_report_serialises_to_json_safe_primitives() -> None:
    import json

    result = ingest(fixture("ancestry_v2_male.txt"))
    assert isinstance(result.qc, QCReport)

    payload = json.loads(json.dumps(result.qc.to_dict()))
    assert payload["sex"]["inferred"] == "male"
    assert payload["call_rates"]["total_markers"] > 0


@pytest.mark.privacy
def test_the_qc_report_contains_no_genotype() -> None:
    """The report is what the CLI emits and the UI renders. One that had to be redacted
    would be useless for both, so it must hold only counts and rates by construction."""
    import json

    from genetics.privacy import looks_like_genotype

    result = ingest(fixture("ancestry_v2_male.txt"))
    assert isinstance(result.qc, QCReport)

    assert not looks_like_genotype(json.dumps(result.qc.to_dict()))


@pytest.mark.privacy
def test_ingest_result_repr_shows_no_data() -> None:
    result = ingest(fixture("ancestry_v2_male.txt"))
    text = repr(result)

    assert "ancestrydna_v2" in text
    assert "rs9" not in text


def test_run_qc_reports_the_vendor_and_source_name() -> None:
    parsed = read_export(fixture("ancestry_v2_male.txt"))
    report = run_qc(parsed.table, source=parsed.source)

    assert report.vendor == "ancestrydna_v2"
    assert report.source_path == "ancestry_v2_male.txt"
