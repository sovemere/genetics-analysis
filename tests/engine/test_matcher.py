"""The card matcher (roadmap M3.2).

The interesting content is the *non*-matches. A matcher that only ever returned successes
would pass a naive suite completely while making "this variant is not on your chip",
"the probes disagree" and "the strand cannot be established" all look like silence.

Rows are assembled at runtime from parts rather than written as literals, the same
construction the privacy tests use: a genotype row written out in a test file would be
flagged by the repo content scan, correctly.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from genetics.engine.cards import Card, KnowledgePack
from genetics.engine.matcher import (
    Matcher,
    MatchResult,
    MatchStatus,
    Strand,
    complement,
    is_strand_ambiguous,
    match_pack,
    strand_canonical,
    summarise,
)
from genetics.ingest.indels import IndelPolicy, IndelRepresentation
from genetics.ingest.keys import MergeTable
from genetics.ingest.schema import NORMALIZED_SCHEMA, CallStatus, Chrom, GenotypeTable

POS = 12345678
RSID = "rs900000001"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _row(
    rsid: str,
    chrom: Chrom,
    pos: int,
    a1: str | None,
    a2: str | None,
    status: CallStatus | None = None,
) -> dict[str, object]:
    lo: str | None = None
    hi: str | None = None
    genotype: str | None = None
    if a1 is not None and a2 is not None:
        lo, hi = sorted([a1, a2])
        genotype = lo + hi
    if status is None:
        status = CallStatus.NO_CALL if genotype is None else CallStatus.CALLED
    return {
        "rsid": rsid,
        "chrom": chrom.value,
        "pos_grch37": pos,
        "a1": lo,
        "a2": hi,
        "genotype": genotype,
        "call_status": status.value,
    }


def _table(rows: list[dict[str, object]]) -> GenotypeTable:
    return GenotypeTable(pl.DataFrame(rows, schema=NORMALIZED_SCHEMA), vendor="test")


def _card_dict(**changes: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": "synth_card",
        "section": "traits",
        "kind": "interpretation",
        "title": "Synthetic card",
        "match": {
            "variants": [{"rsid": RSID, "chrom": "7", "pos_grch37": POS, "alleles": ["A", "G"]}],
            "genotypes": {"AA": "yes", "AG": "yes", "GG": "no"},
        },
        "outcomes": {
            "yes": {"summary": "Carries it.", "detail": "Long form."},
            "no": {"summary": "Does not.", "detail": "Long form."},
        },
        "evidence": {
            "tier": "gwas",
            "replication": "independent",
            "sample_size": 1000,
            "ancestry": ["EUR"],
            "effect": {"measure": "odds_ratio", "value": 1.4},
        },
        "citations": [{"type": "doi", "id": "10.1038/x000000", "title": "A synthetic paper"}],
    }
    for key, value in changes.items():
        raw[key] = value
    return raw


def _card(**changes: Any) -> Card:
    return Card.parse(_card_dict(**changes), "test")


def _ambiguous_card(*, same_outcome: bool = False) -> Card:
    """An A/T site -- self-complementary, so the strand cannot be read off the letters."""
    raw = copy.deepcopy(_card_dict())
    raw["match"]["variants"][0]["alleles"] = ["A", "T"]
    raw["match"]["genotypes"] = (
        {"AA": "yes", "AT": "yes", "TT": "yes"}
        if same_outcome
        else {"AA": "yes", "AT": "yes", "TT": "no"}
    )
    if same_outcome:
        raw["outcomes"] = {"yes": {"summary": "Carries it.", "detail": "Long form."}}
    return Card.parse(raw, "test")


def _pack(*cards: Card) -> KnowledgePack:
    return KnowledgePack(cards=cards, source_dir=Path("."))


def _match(card: Card, rows: list[dict[str, object]], **kwargs: Any) -> MatchResult:
    return match_pack(_pack(card), _table(rows), **kwargs)[0]


# ---------------------------------------------------------------------------
# Strand helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("genotype", "expected"),
    [("AA", "TT"), ("AG", "CT"), ("GG", "CC"), ("AT", "AT"), ("CG", "CG")],
)
def test_complement_reverses_and_renormalises(genotype: str, expected: str) -> None:
    assert complement(genotype) == expected


def test_a_heterozygote_at_an_ambiguous_site_is_its_own_complement() -> None:
    """Which is why heterozygotes need no strand escalation: there is nothing to decide."""
    assert complement("AT") == "AT"
    assert complement("CG") == "CG"


@pytest.mark.parametrize(
    ("alleles", "ambiguous"),
    [(["A", "T"], True), (["C", "G"], True), (["A", "G"], False), (["C", "T"], False)],
)
def test_ambiguity_is_a_property_of_the_allele_pair(alleles: list[str], ambiguous: bool) -> None:
    assert is_strand_ambiguous(alleles) is ambiguous


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_homozygote_matches_its_outcome() -> None:
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "G", "G")])
    assert result.status is MatchStatus.MATCHED
    assert result.outcome_name == "no"
    assert result.outcome is not None
    assert result.outcome.summary == "Does not."
    assert result.strand is Strand.AS_WRITTEN


def test_an_unordered_heterozygote_matches() -> None:
    """The table sorts alleles at ingest, so ``GA`` never reaches here as ``GA``."""
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "G", "A")])
    assert result.status is MatchStatus.MATCHED
    assert result.outcome_name == "yes"


# ---------------------------------------------------------------------------
# Every card gets a result (AGENTS.md 0.1A)
# ---------------------------------------------------------------------------


def test_an_absent_marker_produces_a_result_not_a_silence() -> None:
    result = _match(_card(), [_row("rs900000999", Chrom.CHR7, 999, "A", "G")])
    assert result.status is MatchStatus.MARKER_ABSENT
    assert "not carry" in result.reason
    assert result.outcome is None


def test_the_absent_reason_says_it_is_about_the_chip_not_the_person() -> None:
    """An empty result reads as reassurance unless it says what it is about."""
    result = _match(_card(), [])
    assert "property of the chip" in result.reason


def test_a_no_call_is_distinct_from_an_absent_marker() -> None:
    """Two different facts: the array never carried it, versus it failed to call."""
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, None, None)])
    assert result.status is MatchStatus.NO_CALL
    assert result.genotype is None


def test_every_card_in_a_pack_gets_exactly_one_result() -> None:
    absent = _card_dict(id="absent_card")
    absent["match"]["variants"][0]["pos_grch37"] = 999999
    pack = _pack(_card(), Card.parse(absent, "t"))
    results = match_pack(pack, _table([_row(RSID, Chrom.CHR7, POS, "A", "A")]))
    assert len(results) == len(pack.cards)
    assert [r.card_id for r in results] == ["synth_card", "absent_card"]


def test_an_impossibility_card_is_not_a_failed_lookup() -> None:
    """It gets its own status, not MARKER_ABSENT.

    The table here is empty, so a matcher that simply looked the variant up would report
    the marker missing -- which reads as "your chip does not cover this" for something no
    chip could ever cover.
    """
    card = Card.parse(
        {
            "id": "synth_impossible",
            "section": "genome_structure",
            "kind": "impossibility",
            "title": "Synthetic impossibility",
            "impossibility_reason": "The array measures genotypes, not this.",
            "summary": "Not determinable.",
            "detail": "The long form.",
        },
        "t",
    )
    result = _match(card, [])
    assert result.status is MatchStatus.NOT_DETERMINABLE
    assert "measures genotypes" in result.reason


# ---------------------------------------------------------------------------
# Allele disagreement
# ---------------------------------------------------------------------------


def test_a_heterozygote_fitting_neither_strand_is_a_mismatch() -> None:
    """Wrong coordinates, or a multi-allelic site. Either way the card is describing a
    different variant, and an outcome would be an outcome for that other variant.

    ``A``/``C`` against a declared ``A``/``G``: ``C`` is not declared and its complement
    ``G`` cannot be reached without also turning the observed ``A`` into ``T``, which is
    not declared either.
    """
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "A", "C")])
    assert result.status is MatchStatus.ALLELE_MISMATCH
    assert result.outcome is None


def test_the_mismatch_reason_names_both_allele_sets() -> None:
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "A", "C")])
    assert "A/C" in result.reason and "A/G" in result.reason


def test_a_homozygote_can_never_fit_neither_strand() -> None:
    """Not a happy accident -- a consequence, and one the module documents.

    For a biallelic card the declared pair and its complement cover all four bases, so a
    single observed allele always has *some* reading. That is exactly why the complement
    caveat distinguishes homozygotes: the inference rests on less evidence, and no
    "neither strand fits" signal can ever arrive to contradict it.
    """
    for base in "ACGT":
        result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, base, base)])
        assert result.status is not MatchStatus.ALLELE_MISMATCH, base


# ---------------------------------------------------------------------------
# Strand
# ---------------------------------------------------------------------------


def test_a_heterozygous_flip_is_detected_and_corrected() -> None:
    """At an A/G site the complement reads C/T, which the card declares nowhere.

    Both alleles are visible and together they are exactly the complement of the declared
    pair, so the flip announces itself and correcting it is not much of a guess.
    """
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "C", "T")])
    assert result.status is MatchStatus.MATCHED
    assert result.strand is Strand.COMPLEMENTED
    assert result.genotype == "AG"
    assert result.outcome_name == "yes"


def test_a_homozygous_flip_is_corrected_but_labelled_as_weaker_evidence() -> None:
    """``CC`` complements to ``GG``, but a homozygote shows only one allele.

    One letter cannot separate "reverse strand" from "a different variant at this
    position" -- the asymmetry ingest/keys.py separates LocusKey from VariantKey over. The
    reading is still taken, because an off-strand marker is ordinary and a mis-placed card
    is M3.5's job to catch, but it must not be taken silently.
    """
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "C", "C")])
    assert result.status is MatchStatus.MATCHED
    assert result.strand is Strand.COMPLEMENTED
    assert result.genotype == "GG"
    assert result.outcome_name == "no"
    assert any("less evidence" in c for c in result.caveats)


def test_the_two_flip_caveats_differ() -> None:
    """A guard that gave both the same wording would be recording the distinction nowhere,
    which is the same as not having made it."""
    het = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "C", "T")])
    hom = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "C", "C")])
    assert het.caveats != hom.caveats
    assert any("unambiguous" in c for c in het.caveats)


def test_a_correction_is_recorded_not_applied_silently() -> None:
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "C", "T")])
    assert any("complemented" in c for c in result.caveats)


def test_an_ambiguous_site_escalates_only_when_the_answer_changes() -> None:
    """The central strand rule.

    ``AA`` at an A/T site might really be ``TT``, and here those map to different
    outcomes, so no single answer is honest.
    """
    result = _match(_ambiguous_card(), [_row(RSID, Chrom.CHR7, POS, "A", "A")])
    assert result.status is MatchStatus.STRAND_AMBIGUOUS
    assert result.strand is Strand.AMBIGUOUS
    assert result.candidate_outcomes == ("no", "yes")
    assert result.outcome is None


def test_an_ambiguous_site_matches_when_both_readings_agree() -> None:
    """Otherwise the check would fire on sites where it makes no difference.

    M0.3's lesson applied to this guard: a warning that cannot change the answer is a
    warning people learn to skip past.
    """
    result = _match(_ambiguous_card(same_outcome=True), [_row(RSID, Chrom.CHR7, POS, "A", "A")])
    assert result.status is MatchStatus.MATCHED
    assert result.outcome_name == "yes"
    assert any("same answer" in c for c in result.caveats)


def test_a_heterozygote_at_an_ambiguous_site_matches() -> None:
    """It is its own complement, so there is nothing to be ambiguous about."""
    result = _match(_ambiguous_card(), [_row(RSID, Chrom.CHR7, POS, "A", "T")])
    assert result.status is MatchStatus.MATCHED
    assert result.outcome_name == "yes"


# ---------------------------------------------------------------------------
# Ploidy
# ---------------------------------------------------------------------------


def test_a_hemizygous_call_matches_and_says_it_is_single_copy() -> None:
    """The doubled pair is trustworthy; what it is not is two copies (M1.1)."""
    result = _match(
        _card(),
        [_row(RSID, Chrom.CHR7, POS, "A", "A", status=CallStatus.HEMIZYGOUS)],
    )
    assert result.status is MatchStatus.MATCHED
    assert result.call_status is CallStatus.HEMIZYGOUS
    assert any("single copy" in c for c in result.caveats)


def test_a_het_haploid_call_is_reported_rather_than_interpreted() -> None:
    """The genotype contradicts the ploidy, so it is not trustworthy -- but M1.5 kept it
    countable and this keeps it visible."""
    result = _match(
        _card(),
        [_row(RSID, Chrom.CHR7, POS, "A", "G", status=CallStatus.HET_HAPLOID)],
    )
    assert result.status is MatchStatus.HET_HAPLOID
    assert result.outcome is None
    assert result.observed_genotype is not None, "the contradictory call still travels"
    assert result.genotype is None, "no strand was established, so there is no oriented value"


# ---------------------------------------------------------------------------
# Duplicate probes -- the decision M1 deferred to here
# ---------------------------------------------------------------------------


def test_agreeing_duplicate_probes_produce_one_answer_with_a_note() -> None:
    rows = [
        _row(RSID, Chrom.CHR7, POS, "A", "G"),
        _row("rs900000777", Chrom.CHR7, POS, "A", "G"),
    ]
    result = _match(_card(), rows)
    assert result.status is MatchStatus.MATCHED
    assert any("2 probes" in c for c in result.caveats)


def test_disagreeing_duplicate_probes_are_a_conflict_not_a_choice() -> None:
    """Picking the first row -- or the "better" one -- would manufacture an answer the
    data does not contain."""
    rows = [
        _row(RSID, Chrom.CHR7, POS, "A", "G"),
        _row("rs900000777", Chrom.CHR7, POS, "G", "G"),
    ]
    result = _match(_card(), rows)
    assert result.status is MatchStatus.DUPLICATE_CONFLICT
    assert result.outcome is None
    assert "Neither is preferred" in result.reason


def test_a_no_call_beside_a_call_is_not_a_conflict() -> None:
    """An uncalled probe carries no genotype to disagree with."""
    rows = [
        _row(RSID, Chrom.CHR7, POS, None, None),
        _row("rs900000777", Chrom.CHR7, POS, "G", "G"),
    ]
    result = _match(_card(), rows)
    assert result.status is MatchStatus.MATCHED
    assert result.outcome_name == "no"
    assert any("called" in c for c in result.caveats)


def test_duplicate_probes_that_all_fail_to_call_report_no_call() -> None:
    rows = [
        _row(RSID, Chrom.CHR7, POS, None, None),
        _row("rs900000777", Chrom.CHR7, POS, None, None),
    ]
    assert _match(_card(), rows).status is MatchStatus.NO_CALL


# ---------------------------------------------------------------------------
# Indels -- M1.6 asked to be called, not reimplemented
# ---------------------------------------------------------------------------


def test_an_indel_row_is_excluded_by_policy_not_reported_as_a_mismatch() -> None:
    """A different fact from "the alleles disagree", and a reader deserves the difference:
    one is a policy limit, the other is a card describing the wrong variant."""
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "I", "I")])
    assert result.status is MatchStatus.INDEL_EXCLUDED
    assert "4.2" in result.reason


def test_a_whitelisted_indel_is_no_longer_excluded() -> None:
    """Proves the matcher reads the policy rather than hard-coding the default.

    Without this the exclusion test above would pass against a matcher that simply refused
    every I/D row forever, and the whitelist M1.6 built would be unreachable.
    """
    policy = IndelPolicy.with_whitelist(
        [
            IndelRepresentation(
                rsid=RSID,
                chrom=Chrom.CHR7,
                pos_grch37=POS,
                insertion_allele="AT",
                deletion_allele="A",
                source="synthetic test fixture",
            )
        ]
    )
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "I", "I")], policy=policy)
    assert result.status is not MatchStatus.INDEL_EXCLUDED
    # It now falls through to allele comparison, where I/I is not the card's A/G.
    assert result.status is MatchStatus.ALLELE_MISMATCH


# ---------------------------------------------------------------------------
# rsID cross-check
# ---------------------------------------------------------------------------


def test_a_disagreeing_rsid_is_a_caveat_not_a_failure() -> None:
    """Position is the primary key (ingest/keys.py); the rsID is a secondary index."""
    result = _match(_card(), [_row("rs900000555", Chrom.CHR7, POS, "A", "G")])
    assert result.status is MatchStatus.MATCHED
    assert any("rs900000555" in c for c in result.caveats)


def test_a_merged_rsid_does_not_raise_a_caveat() -> None:
    """The retired id in an old export and the current id in a card are the same variant.

    Resolving only one side would report a disagreement on every card written after a
    merge, which is exactly the case MergeTable exists for.
    """
    merges = MergeTable.from_pairs([("rs900000555", RSID)])
    result = _match(_card(), [_row("rs900000555", Chrom.CHR7, POS, "A", "G")], merges=merges)
    assert result.status is MatchStatus.MATCHED
    assert not any("rs900000555" in c for c in result.caveats)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_summarise_counts_every_status_including_zeroes() -> None:
    """A status missing from the summary reads as "did not happen" rather than "zero"."""
    counts = summarise([_match(_card(), [_row(RSID, Chrom.CHR7, POS, "A", "G")])])
    assert set(counts) == set(MatchStatus)
    assert counts[MatchStatus.MATCHED] == 1
    assert counts[MatchStatus.MARKER_ABSENT] == 0


def test_the_index_only_covers_the_loci_the_pack_asks_about() -> None:
    """677k rows indexed to answer one question would be a great deal of memory for
    nothing, and the whole table is available to the caller anyway."""
    rows = [_row(f"rs90000{i:04d}", Chrom.CHR1, 1000 + i, "A", "G") for i in range(500)]
    rows.append(_row(RSID, Chrom.CHR7, POS, "A", "G"))
    pack = _pack(_card())
    matcher = Matcher.for_pack(pack, _table(rows))
    assert matcher.index.n_loci == 1


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_a_match_result_does_not_print_a_genotype() -> None:
    """It holds one, so M0.3's rule applies: repr shows shape, never content."""
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "A", "G")])
    assert result.genotype == "AG"
    text = repr(result)
    assert "AG" not in text
    assert "synth_card" in text and "matched" in text


@pytest.mark.privacy
def test_the_locus_index_does_not_print_its_rows() -> None:
    pack = _pack(_card())
    matcher = Matcher.for_pack(pack, _table([_row(RSID, Chrom.CHR7, POS, "A", "G")]))
    assert "AG" not in repr(matcher.index)


@pytest.mark.privacy
def test_generated_reasons_and_caveats_are_not_row_shaped() -> None:
    """These strings go to the CLI and into run bundles, both of which are scanned.

    Showing a person their own genotype is the product; emitting something the leak
    scanner reads as an *export row* is not, and it would block the commit that added it.
    """
    from genetics.privacy import find_genotypes

    cases: list[tuple[Card, list[dict[str, object]]]] = [
        (_card(), [_row(RSID, Chrom.CHR7, POS, "A", "G")]),
        (_card(), [_row("rs900000555", Chrom.CHR7, POS, "C", "T")]),
        (_card(), [_row(RSID, Chrom.CHR7, POS, "C", "C")]),
        (_card(), [_row(RSID, Chrom.CHR7, POS, "I", "I")]),
        (_ambiguous_card(), [_row(RSID, Chrom.CHR7, POS, "A", "A")]),
        (_card(), []),
    ]
    for card, rows in cases:
        result = _match(card, rows)
        for text in (result.reason, *result.caveats):
            assert find_genotypes(text) == [], text


# ---------------------------------------------------------------------------
# End to end, through real ingest
# ---------------------------------------------------------------------------


def test_matching_works_against_a_genuinely_ingested_export() -> None:
    """Everything above builds frames by hand, which can drift from what ingest produces.

    This runs the whole path -- sniff, parse, QC, ploidy resolution -- and then matches a
    card built from a marker the fixture actually contains. A matcher that only ever saw
    hand-assembled frames would not notice, say, a chrom dtype or an allele-order
    convention it had assumed rather than checked.
    """
    from genetics.ingest import ingest
    from genetics.testing.fixtures import DEFAULT_FIXTURE_DIR

    path = DEFAULT_FIXTURE_DIR / "ancestry_v2_male.txt"
    if not path.exists():
        pytest.skip("fixtures not generated; run `genetics fixtures`")

    table = ingest(path).table
    row = (
        table.frame.filter(
            (pl.col("chrom") == Chrom.CHR1.value)
            & pl.col("genotype").is_not_null()
            & pl.col("a1").is_in(["A", "C", "G", "T"])
            & pl.col("a2").is_in(["A", "C", "G", "T"])
            & (pl.col("a1") != pl.col("a2"))
        )
        .head(1)
        .to_dicts()[0]
    )

    raw = _card_dict(id="from_fixture")
    raw["match"]["variants"][0] = {
        "rsid": row["rsid"],
        "chrom": "1",
        "pos_grch37": row["pos_grch37"],
        "alleles": [row["a1"], row["a2"]],
    }
    observed = str(row["genotype"])
    a1, a2 = str(row["a1"]), str(row["a2"])
    raw["match"]["genotypes"] = {a1 + a1: "yes", a1 + a2: "yes", a2 + a2: "no"}

    result = _match(Card.parse(raw, "t"), table.frame.to_dicts())
    assert result.status is MatchStatus.MATCHED
    assert result.genotype == observed
    assert result.outcome is not None


# ---------------------------------------------------------------------------
# Review-pass fixes
# ---------------------------------------------------------------------------


def test_duplicate_probes_on_opposite_strands_are_not_a_conflict() -> None:
    """Found in review. The two probes agree; only their strands differ.

    Raw string comparison called ``AG`` beside ``CT`` a DUPLICATE_CONFLICT and suppressed
    an answer the data plainly contains. That this module exists at all is because the
    vendor's forward-strand claim is not trusted -- so trusting it inside the duplicate
    check was the same assumption sneaking back in one function lower.
    """
    rows = [
        _row(RSID, Chrom.CHR7, POS, "A", "G"),
        _row("rs900000777", Chrom.CHR7, POS, "C", "T"),
    ]
    result = _match(_card(), rows)
    assert result.status is MatchStatus.MATCHED
    assert result.outcome_name == "yes"


def test_genuinely_disagreeing_probes_still_conflict_across_strands() -> None:
    """The other half. ``AA`` and ``CC`` are ``AA`` and ``GG`` on the card's strand -- a
    real disagreement, and the strand-independent comparison must not paper over it."""
    rows = [
        _row(RSID, Chrom.CHR7, POS, "A", "A"),
        _row("rs900000777", Chrom.CHR7, POS, "C", "C"),
    ]
    assert _match(_card(), rows).status is MatchStatus.DUPLICATE_CONFLICT


def test_strand_canonical_is_stable_under_complementing() -> None:
    for genotype in ("AA", "AG", "GG", "AT", "CG", "CT", "CC"):
        assert strand_canonical(genotype) == strand_canonical(complement(genotype))


def test_strand_canonical_leaves_indel_codes_alone() -> None:
    """They have no complement, so they are compared literally -- which is right: two I/D
    probes agree only if they read the same."""
    assert strand_canonical("II") == "II"
    assert strand_canonical("DD") == "DD"


def test_complementing_an_indel_fails_with_an_explanation() -> None:
    """It was a bare KeyError, reachable only by the current order of checks in _evaluate.

    That is a property of today's control flow rather than a guarantee, and a KeyError two
    frames up says nothing about indels carrying no sequence.
    """
    with pytest.raises(ValueError, match=r"4\.2"):
        complement("II")


def test_a_complemented_match_reports_both_genotypes() -> None:
    """One field whose meaning depended on the status would be read wrongly the first time
    a card was rendered -- the observed value and the card-strand value differ here."""
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "C", "T")])
    assert result.genotype == "AG", "on the card's strand"
    assert result.observed_genotype == "CT", "as the export wrote it"


def test_an_as_written_match_reports_the_same_value_twice() -> None:
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "A", "G")])
    assert result.genotype == result.observed_genotype == "AG"


def test_an_ambiguous_site_has_no_oriented_genotype() -> None:
    """There is no honest oriented value when the reading is exactly what is undecided."""
    result = _match(_ambiguous_card(), [_row(RSID, Chrom.CHR7, POS, "A", "A")])
    assert result.status is MatchStatus.STRAND_AMBIGUOUS
    assert result.genotype is None
    assert result.observed_genotype == "AA"


@pytest.mark.privacy
def test_neither_genotype_field_is_printed() -> None:
    result = _match(_card(), [_row(RSID, Chrom.CHR7, POS, "C", "T")])
    text = repr(result)
    assert "AG" not in text and "CT" not in text


# ---------------------------------------------------------------------------
# Agent-review fixes
# ---------------------------------------------------------------------------


def test_an_ambiguous_card_reports_a_real_mismatch_as_a_mismatch() -> None:
    """Found by review. ``_orient`` returned early for A/T and C/G sites without ever
    checking the observed alleles were declared.

    So a card declaring A/T against a row reading ``C``/``C`` skipped the mismatch branch
    and landed on the "the schema should have made this impossible" one -- telling the
    reader to file a bug about their own mis-coordinated card. Around a third of SNPs are
    A/T or C/G, so this was the *normal* mismatch path for them.
    """
    result = _match(_ambiguous_card(), [_row(RSID, Chrom.CHR7, POS, "C", "C")])
    assert result.status is MatchStatus.ALLELE_MISMATCH
    assert "bug report" not in result.reason
    assert "A/T" in result.reason


def test_an_ambiguous_match_has_no_oriented_genotype_even_when_it_matches() -> None:
    """The outcome is the same under either reading, but *which* reading is real stays
    unknown -- and ``genotype`` is documented as the value on the card's strand.

    Publishing ``TT`` for a call that may equally be ``AA`` would make the field's own
    invariant false, and a renderer honouring that invariant would print it.
    """
    result = _match(_ambiguous_card(same_outcome=True), [_row(RSID, Chrom.CHR7, POS, "T", "T")])
    assert result.status is MatchStatus.MATCHED
    assert result.strand is Strand.AMBIGUOUS
    assert result.genotype is None
    assert result.observed_genotype == "TT"
    assert result.outcome_name == "yes"


def test_opposite_homozygotes_at_an_ambiguous_site_are_not_declared_to_agree() -> None:
    """The canonical form collapses ``AA`` and ``TT``, which is right at an A/G site and
    wrong at an A/T one.

    There the two probes may be one call on two strands or two different calls, and nothing
    can tell -- so announcing "2 probes agree" was a false statement, and the
    ``observed_genotype`` shown was whichever row the join happened to return first.
    """
    rows = [
        _row(RSID, Chrom.CHR7, POS, "A", "A"),
        _row("rs900000777", Chrom.CHR7, POS, "T", "T"),
    ]
    result = _match(_ambiguous_card(), rows)
    assert result.status is MatchStatus.DUPLICATE_CONFLICT
    assert not any("agree" in c for c in result.caveats)


def test_opposite_strand_agreement_still_holds_at_a_non_ambiguous_site() -> None:
    """The other half: the earlier fix must survive this one."""
    rows = [
        _row(RSID, Chrom.CHR7, POS, "A", "G"),
        _row("rs900000777", Chrom.CHR7, POS, "C", "T"),
    ]
    assert _match(_card(), rows).status is MatchStatus.MATCHED


def test_the_conflict_reason_counts_probes_that_actually_called() -> None:
    """A no-call is not a party to the disagreement, so "3 probes produced different
    genotypes" when one produced none is simply inaccurate on the card face."""
    rows = [
        _row(RSID, Chrom.CHR7, POS, None, None),
        _row("rs900000777", Chrom.CHR7, POS, "A", "A"),
        _row("rs900000888", Chrom.CHR7, POS, "G", "G"),
    ]
    result = _match(_card(), rows)
    assert result.status is MatchStatus.DUPLICATE_CONFLICT
    assert "2 probes" in result.reason
    assert "3 probes" not in result.reason
