"""Tests for genetics.privacy (roadmap M0.3).

Note the construction style: genotype rows are assembled from parts rather than written
as literals. A literal specimen in this file would be flagged by the repo-hygiene scan --
correctly. Building them at runtime keeps the test honest and the source clean.
"""

from __future__ import annotations

import pytest

from genetics.privacy import (
    GenotypeLeakError,
    NoGenotypeRepr,
    assert_no_genotype,
    find_genotypes,
    looks_like_genotype,
    redact,
    scan_paths,
)

TAB = "\t"


def ancestry_row(
    rsid: str = "rs900000001", chrom: str = "1", pos: str = "100001", a1: str = "G", a2: str = "G"
) -> str:
    """Build a five-column vendor row without writing one literally."""
    return TAB.join([rsid, chrom, pos, a1, a2])


def merged_row(
    rsid: str = "rs900000002", chrom: str = "1", pos: str = "100042", genotype: str = "AG"
) -> str:
    return TAB.join([rsid, chrom, pos, genotype])


def inline(rsid: str = "rs900000003", a1: str = "A", a2: str = "G") -> str:
    return f"{rsid}: {a1}{a2}"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detects_ancestry_row() -> None:
    assert looks_like_genotype(ancestry_row())


def test_detects_merged_row() -> None:
    assert looks_like_genotype(merged_row())


def test_detects_inline_form() -> None:
    assert looks_like_genotype(inline())


def test_detects_row_embedded_in_prose() -> None:
    """The realistic case: a row pasted into a doc or an issue, surrounded by text."""
    text = f"Here is what the parser saw:\n{ancestry_row()}\nwhich looks wrong."
    assert looks_like_genotype(text)


def test_detects_hemizygous_and_indel_and_nocall_codings() -> None:
    for a1, a2 in (("I", "I"), ("D", "D"), ("0", "0"), ("I", "D")):
        assert looks_like_genotype(ancestry_row(a1=a1, a2=a2)), f"missed {a1}/{a2}"


def test_detects_sex_chromosome_rows() -> None:
    for chrom in ("23", "24", "25", "26", "X", "Y", "MT"):
        assert looks_like_genotype(ancestry_row(chrom=chrom)), f"missed chrom {chrom}"


def test_find_genotypes_reports_pattern_names() -> None:
    hits = find_genotypes(ancestry_row())
    assert hits
    assert all(isinstance(name, str) and matched for name, matched in hits)


# ---------------------------------------------------------------------------
# Precision: a scanner that cries wolf gets bypassed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "The variant rs17822931 in ABCC11 is associated with earwax type.",
        "See rs12913832 for eye colour.",
        "Studies: rs1234567, rs7654321, rs999999.",
        "chromosome 1 position 100001 was not called",
        "A G C T are the four bases",
        "def parse(rsid: str, chrom: str) -> None: ...",
        "coverage was 0.9986 across 677436 markers",
        "rs1234567 has a minor allele frequency of 0.31",
    ],
)
def test_does_not_flag_ordinary_text(text: str) -> None:
    assert not looks_like_genotype(text), f"false positive on: {text!r}"


def test_rsid_alone_is_not_a_genotype() -> None:
    """AGENTS.md 1.3 permits researching a variant; it forbids attaching the person."""
    assert not looks_like_genotype("rs17822931")
    assert not looks_like_genotype("Look up rs17822931 and rs4988235.")


# ---------------------------------------------------------------------------
# Redaction and enforcement
# ---------------------------------------------------------------------------


def test_redact_removes_the_genotype_but_keeps_context() -> None:
    text = f"before\n{ancestry_row()}\nafter"
    cleaned = redact(text)
    assert not looks_like_genotype(cleaned)
    assert "before" in cleaned
    assert "after" in cleaned


def test_assert_no_genotype_passes_on_clean_text() -> None:
    assert_no_genotype("nothing to see here", context="unit test")


def test_assert_no_genotype_raises_on_dirty_text() -> None:
    with pytest.raises(GenotypeLeakError):
        assert_no_genotype(ancestry_row(), context="unit test")


def test_leak_error_does_not_echo_the_genotype() -> None:
    """The exception message is itself a place genotypes escape to."""
    row = ancestry_row(a1="A", a2="C")
    try:
        assert_no_genotype(row)
    except GenotypeLeakError as exc:
        assert not looks_like_genotype(str(exc))
        assert row not in str(exc)
    else:  # pragma: no cover
        pytest.fail("expected GenotypeLeakError")


def test_scan_paths_returns_only_offenders() -> None:
    findings = scan_paths([("clean.md", "no genotypes here"), ("dirty.md", ancestry_row())])
    assert set(findings) == {"dirty.md"}


# ---------------------------------------------------------------------------
# NoGenotypeRepr
# ---------------------------------------------------------------------------


class _Carrier(NoGenotypeRepr):
    _repr_fields = ("marker_count", "build")

    def __init__(self) -> None:
        self.marker_count = 677436
        self.build = "37"
        self.rows = [("rs900000001", "G", "G")]


class _Bare(NoGenotypeRepr):
    def __init__(self) -> None:
        self.rows = [("rs900000001", "G", "G")]


def test_repr_shows_only_declared_fields() -> None:
    text = repr(_Carrier())
    assert "677436" in text
    assert "37" in text
    assert "rs900000001" not in text
    assert "rows" not in text


def test_repr_omits_everything_when_nothing_declared() -> None:
    """Silence is the safe default: undeclared means omitted, not summarised."""
    text = repr(_Bare())
    assert text == "<_Bare>"
    assert "rs900000001" not in text


def test_repr_redacts_a_declared_field_that_turns_out_dirty() -> None:
    class _Sloppy(NoGenotypeRepr):
        _repr_fields = ("note",)

        def __init__(self) -> None:
            self.note = ancestry_row()

    assert not looks_like_genotype(repr(_Sloppy()))
