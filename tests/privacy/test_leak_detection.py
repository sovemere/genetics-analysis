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
    assert all(isinstance(hit.pattern, str) and hit.length > 0 for hit in hits)


def test_hits_carry_locations_not_text() -> None:
    """Findings must be safe to print, log, or let pytest render on failure.

    An earlier version returned the matched string, so any caller doing the obvious
    thing wrote the genotype straight to a terminal or a CI log.
    """
    row = ancestry_row()
    for hit in find_genotypes(row):
        assert not looks_like_genotype(repr(hit))
        assert row not in repr(hit)


# ---------------------------------------------------------------------------
# Escaped and keyed forms -- the shapes repr() and tracebacks produce
# ---------------------------------------------------------------------------


def test_detects_row_with_escaped_tabs() -> None:
    """The form that appears inside a Python string literal.

    Matching only real tabs made the scanner blind to source code, log lines and
    tracebacks -- precisely the threats the module docstring names.
    """
    escaped = "rs900000001" + r"\t" + "1" + r"\t" + "100001" + r"\t" + "G" + r"\t" + "G"
    assert looks_like_genotype(escaped)


def test_detects_a_row_that_has_been_through_repr() -> None:
    assert looks_like_genotype(repr(ancestry_row()))


def keyed_fields(rsid: str = "rs900000001", a1: str = "G", a2: str = "G") -> str:
    """Assemble a dataclass-style repr without writing one literally.

    Written as a literal, this line would be blocked by our own pre-commit hook -- which
    is how it was caught the first time.
    """
    parts = [f"rsid='{rsid}'", "chrom='1'", "pos=100001", f"a1='{a1}'", f"a2='{a2}'"]
    return "ParsedRecord(" + ", ".join(parts) + ")"


def test_detects_dataclass_style_keyed_fields() -> None:
    """The shape a record's repr produces in a traceback."""
    assert looks_like_genotype(keyed_fields())


def test_detects_23andme_style_i_identifiers() -> None:
    """23andMe uses i-prefixed IDs for tens of thousands of custom probes."""
    assert looks_like_genotype(merged_row(rsid="i5000940"))
    assert looks_like_genotype(ancestry_row(rsid="i5000940"))


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
    """Asserts the redaction *fired*, not merely that the scanner stayed quiet.

    The previous version asserted only `not looks_like_genotype(repr(...))`, which was
    true for the wrong reason: the scanner could not see escaped tabs, so the test
    passed while the genotype was emitted verbatim. It would have kept passing with the
    redaction deleted entirely.
    """

    class _Sloppy(NoGenotypeRepr):
        _repr_fields = ("note",)

        def __init__(self) -> None:
            self.note = ancestry_row()

    out = repr(_Sloppy())
    assert "<redacted>" in out
    assert "rs900000001" not in out
    assert not looks_like_genotype(out)


def test_plain_dataclass_does_not_defeat_the_mixin() -> None:
    """@dataclass would generate __repr__ on the subclass and shadow the mixin.

    Dataclasses are the house style here, so the first genotype-bearing record class
    would silently have got the default repr while appearing to be protected. The mixin
    claims the __repr__ slot in __init_subclass__, and dataclasses never overwrite a name
    already in cls.__dict__, so the generated one is skipped.
    """
    from dataclasses import dataclass

    @dataclass
    class _Record(NoGenotypeRepr):
        _repr_fields = ("marker_count",)
        marker_count: int = 1
        raw_row: str = ""

    record = _Record(marker_count=677436, raw_row=ancestry_row())
    out = repr(record)

    assert _Record.__repr__ is NoGenotypeRepr.__repr__
    assert "677436" in out
    assert "rs900000001" not in out
    assert not looks_like_genotype(out)


def test_dataclass_with_repr_false_also_works() -> None:
    from dataclasses import dataclass

    @dataclass(repr=False)
    class _Safe(NoGenotypeRepr):
        _repr_fields = ("marker_count",)
        marker_count: int = 1
        raw_row: str = ""

    out = repr(_Safe(marker_count=42, raw_row=ancestry_row()))
    assert "42" in out
    assert not looks_like_genotype(out)


def test_hand_written_repr_is_refused() -> None:
    """Inheriting the mixin and then overriding it is a contradiction, not a preference."""
    with pytest.raises(TypeError, match="__repr__"):

        class _Leaky(NoGenotypeRepr):
            def __repr__(self) -> str:
                return "whatever"
