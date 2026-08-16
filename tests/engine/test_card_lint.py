"""Card linting: schema-plus-render checks and dbSNP key resolution (M3.5)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest

from genetics.engine.card_lint import (
    InMemoryVariantResolver,
    ParquetVariantResolver,
    ReferenceVariant,
    VariantResolution,
    lint_directory,
    lint_pack,
)
from genetics.engine.cards import CardKind, KnowledgePack, Outcome
from genetics.ingest.keys import VariantKey
from genetics.ingest.schema import Chrom
from genetics.refs import postprocess

FIXTURES = Path(__file__).parents[1] / "fixtures" / "cards"


def _pack() -> KnowledgePack:
    return KnowledgePack.load(FIXTURES)


def _exact_records(pack: KnowledgePack | None = None) -> tuple[ReferenceVariant, ...]:
    source = pack or _pack()
    return tuple(
        ReferenceVariant(card.match.variant.rsid, card.match.variant.key)
        for card in source.cards
        if card.match is not None
    )


def test_a_pack_lints_with_an_injected_resolver() -> None:
    report = lint_pack(_pack(), resolver=InMemoryVariantResolver(_exact_records()))
    assert report.ok
    assert report.card_count == 3
    assert report.interpretation_count == 2
    assert report.resolved_variants == 2
    assert report.rendered_templates == 14
    assert report.variant_resolution is VariantResolution.CHECKED


def test_full_lint_fails_closed_without_a_resolver() -> None:
    report = lint_pack(_pack())
    assert not report.ok
    assert report.variant_resolution is VariantResolution.UNAVAILABLE
    assert [issue.code for issue in report.issues] == ["variant-index-unavailable"]


def test_schema_only_is_explicit_in_the_report() -> None:
    report = lint_pack(_pack(), resolve_variants=False)
    assert report.ok
    assert report.variant_resolution is VariantResolution.SKIPPED
    assert report.resolved_variants == 0


def test_a_missing_citation_is_still_caught_defensively_after_parse() -> None:
    pack = _pack()
    cards = (replace(pack.cards[0], citations=()), *pack.cards[1:])
    report = lint_pack(
        replace(pack, cards=cards),
        resolver=InMemoryVariantResolver(_exact_records(pack)),
    )
    assert not report.ok
    assert any(issue.code == "citation-missing" for issue in report.issues)


def test_every_outcome_is_actually_rendered() -> None:
    pack = _pack()
    first = pack.cards[0]
    outcomes = dict(first.outcomes)
    original = outcomes["present"]
    # Bypass Card.parse intentionally: lint is the second line of defence and should
    # execute formatting rather than merely assume the parser did.
    outcomes["present"] = Outcome("Unknown {not_in_context}.", original.detail)
    broken = replace(first, outcomes=outcomes)
    report = lint_pack(
        replace(pack, cards=(broken, *pack.cards[1:])),
        resolver=InMemoryVariantResolver(_exact_records(pack)),
    )
    assert not report.ok
    assert any(issue.code == "template-render" for issue in report.issues)


def test_malformed_yaml_is_reported_as_a_schema_issue(tmp_path: Path) -> None:
    (tmp_path / "broken.yaml").write_text("cards: [", encoding="utf-8")
    report = lint_directory(tmp_path, resolve_variants=False)
    assert not report.ok
    assert report.issues[0].code == "schema"
    assert "YAML" in report.issues[0].message


def test_an_impossibility_only_pack_needs_no_variant_index() -> None:
    pack = _pack()
    only = replace(pack, cards=(pack.cards[-1],))
    report = lint_pack(only)
    assert report.ok
    assert report.variant_resolution is VariantResolution.CHECKED


def test_wrong_rsid_at_the_right_key_is_distinguished() -> None:
    pack = _pack()
    records = list(_exact_records(pack))
    records[0] = replace(records[0], rsid="rs999999999")
    report = lint_pack(pack, resolver=InMemoryVariantResolver(records))
    issue = next(issue for issue in report.issues if issue.card_id == pack.cards[0].id)
    assert issue.code == "variant-rsid-mismatch"


def test_wrong_alleles_at_the_right_rsid_and_locus_are_distinguished() -> None:
    pack = _pack()
    records = list(_exact_records(pack))
    wanted = records[0].key
    records[0] = replace(
        records[0],
        key=VariantKey(wanted.chrom, wanted.pos_grch37, ("A", "C")),
    )
    report = lint_pack(pack, resolver=InMemoryVariantResolver(records))
    issue = next(issue for issue in report.issues if issue.card_id == pack.cards[0].id)
    assert issue.code == "variant-allele-mismatch"


def test_card_alleles_may_be_a_subset_of_a_multiallelic_dbsnp_record() -> None:
    """The array's biallelic probe need not map theoretical extra dbSNP alternates."""

    pack = _pack()
    records = list(_exact_records(pack))
    wanted = records[0].key
    records[0] = replace(
        records[0],
        key=VariantKey(wanted.chrom, wanted.pos_grch37, (*wanted.alleles, "T")),
    )

    report = lint_pack(pack, resolver=InMemoryVariantResolver(records))

    assert report.ok
    assert report.resolved_variants == 2


def test_wrong_coordinate_at_the_right_rsid_is_distinguished() -> None:
    pack = _pack()
    records = list(_exact_records(pack))
    wanted = records[0].key
    records[0] = replace(
        records[0],
        key=VariantKey(wanted.chrom, wanted.pos_grch37 + 1, wanted.alleles),
    )
    report = lint_pack(pack, resolver=InMemoryVariantResolver(records))
    issue = next(issue for issue in report.issues if issue.card_id == pack.cards[0].id)
    assert issue.code == "variant-coordinate-mismatch"


def test_a_completely_unknown_variant_is_reported() -> None:
    pack = _pack()
    report = lint_pack(pack, resolver=InMemoryVariantResolver(()))
    assert {issue.code for issue in report.issues} == {"variant-unresolved"}


def _write_index_provenance(path: Path) -> None:
    # This is a synthetic public reference artifact, not a genotype fixture.  Exercise
    # the same provenance writer as the real dbSNP transform so resolver tests cannot
    # accidentally normalize trusting a bare schema-shaped Parquet file.
    postprocess._write_provenance(
        path,
        {
            "schema_version": 1,
            "step": "extract_dbsnp_variant_index",
            "transform_version": postprocess.get("extract_dbsnp_variant_index").transform_version,
            "input": {"filename": "synthetic.vcf.gz", "sha256": "0" * 64},
            "params": {
                "input": "synthetic.vcf.gz",
                "output": path.name,
            },
            "output": path.name,
        },
        2,
    )


def _write_index(path: Path, *, alts_as_list: bool = True) -> None:
    alts: list[list[str]] | list[str]
    alts = [["G"], ["T"]] if alts_as_list else ["G", "T"]
    pl.DataFrame(
        {
            "rsid": ["rs900000001", "rs900000002"],
            "chrom": ["7", "Y"],
            "pos_grch37": [12345678, 2655180],
            "ref": ["A", "C"],
            "alts": alts,
        }
    ).write_parquet(path)
    _write_index_provenance(path)


def test_the_parquet_resolver_reads_the_declared_index_shape(tmp_path: Path) -> None:
    index = tmp_path / "dbsnp_variants.parquet"
    _write_index(index)
    report = lint_pack(_pack(), resolver=ParquetVariantResolver(index))
    assert report.ok
    assert report.resolved_variants == 2


def test_a_delimited_alts_string_is_refused_instead_of_guessed(tmp_path: Path) -> None:
    index = tmp_path / "dbsnp_variants.parquet"
    _write_index(index, alts_as_list=False)
    report = lint_pack(_pack(), resolver=ParquetVariantResolver(index))
    assert not report.ok
    issue = next(issue for issue in report.issues if issue.code == "variant-index-unavailable")
    assert "Parquet list" in issue.message


def test_a_missing_parquet_index_is_a_clear_lint_failure(tmp_path: Path) -> None:
    missing = tmp_path / "dbsnp_variants.parquet"
    report = lint_pack(_pack(), resolver=ParquetVariantResolver(missing))
    assert not report.ok
    assert report.variant_resolution is VariantResolution.UNAVAILABLE
    assert str(missing) in report.issues[0].message


def test_a_schema_shaped_index_without_provenance_fails_closed(tmp_path: Path) -> None:
    index = tmp_path / "dbsnp_variants.parquet"
    _write_index(index)
    postprocess.provenance_path(index).unlink()

    report = lint_pack(_pack(), resolver=ParquetVariantResolver(index))

    assert not report.ok
    issue = next(issue for issue in report.issues if issue.code == "variant-index-unavailable")
    assert "provenance" in issue.message


def test_an_index_from_an_old_transform_version_fails_closed(tmp_path: Path) -> None:
    index = tmp_path / "dbsnp_variants.parquet"
    _write_index(index)
    sidecar = postprocess.provenance_path(index)
    provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    provenance["transform_version"] = 1
    sidecar.write_text(json.dumps(provenance), encoding="utf-8")

    report = lint_pack(_pack(), resolver=ParquetVariantResolver(index))

    assert not report.ok
    issue = next(issue for issue in report.issues if issue.code == "variant-index-unavailable")
    assert "transform version 2" in issue.message


def test_default_index_binding_rejects_another_locked_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = tmp_path / "dbsnp_variants.parquet"
    _write_index(index)
    expected = {
        "schema_version": 2,
        "step": "extract_dbsnp_variant_index",
        "transform_version": postprocess.get("extract_dbsnp_variant_index").transform_version,
        "input": {"filename": "synthetic.vcf.gz", "sha256": "f" * 64},
        "params": {"input": "synthetic.vcf.gz", "output": index.name},
        "output": index.name,
    }
    monkeypatch.setattr(
        postprocess, "declared_artifact_provenance", lambda *args, **kwargs: expected
    )

    report = lint_pack(
        _pack(),
        resolver=ParquetVariantResolver(index, bind_to_manifest=True),
    )

    assert not report.ok
    issue = next(issue for issue in report.issues if issue.code == "variant-index-unavailable")
    assert "stale for the current input" in issue.message


def test_the_parquet_lookup_checks_the_locus_direction_too(tmp_path: Path) -> None:
    """A row at the authored key under another rsID must be an rsID mismatch, not absent."""
    index = tmp_path / "dbsnp_variants.parquet"
    _write_index(index)
    frame = pl.read_parquet(index).with_columns(
        pl.when(pl.col("rsid") == "rs900000001")
        .then(pl.lit("rs999999999"))
        .otherwise(pl.col("rsid"))
        .alias("rsid")
    )
    frame.write_parquet(index)
    # Preserve valid artifact provenance: this test is about the bidirectional key
    # diagnostic, not the independent mutation gate.
    _write_index_provenance(index)
    report = lint_pack(_pack(), resolver=ParquetVariantResolver(index))
    assert any(issue.code == "variant-rsid-mismatch" for issue in report.issues)


def test_reference_keys_use_the_normalized_chromosome_vocabulary() -> None:
    record = ReferenceVariant(
        "rs900000001",
        VariantKey(Chrom.CHR7, 12345678, ("A", "G")),
    )
    report = lint_pack(_pack(), resolver=InMemoryVariantResolver((record, *_exact_records()[1:])))
    assert report.ok


def test_lint_context_matches_production_context() -> None:
    """Lint must render with exactly what the engine will render with -- no more.

    A placeholder lint supplies and production does not is worse than a missing check:
    `genetics cards lint` reports PASS, the release gate is satisfied, and every matched
    card then fails at runtime inside the renderer whose error says to treat it as an
    engine bug. The registry's `available` flag is the single source of truth, so a
    milestone flip has to update both sides or land here.
    """
    from genetics.engine.card_lint import synthetic_context
    from genetics.engine.cards import TEMPLATE_VARS
    from genetics.engine.confidence import CallSource, calculate_confidence
    from genetics.engine.evidence import _template_values
    from genetics.engine.matcher import MatchResult, MatchStatus, Strand

    available = {name for name, var in TEMPLATE_VARS.items() if var.available}
    card = next(card for card in _pack().cards if card.kind is CardKind.INTERPRETATION)
    assert card.match is not None and card.evidence is not None

    assert set(synthetic_context(card)) == available

    outcome_name = next(iter(card.match.genotypes.values()))
    match = MatchResult(
        card_id=card.id,
        status=MatchStatus.MATCHED,
        reason="Matched.",
        genotype="".join(card.match.variant.key.alleles),
        observed_genotype="".join(card.match.variant.key.alleles),
        observed_rsid=card.match.variant.rsid,
        outcome_name=outcome_name,
        outcome=card.outcomes[outcome_name],
        strand=Strand.AS_WRITTEN,
    )
    confidence = calculate_confidence(
        card.evidence,
        population_allele_frequency=0.2,
        call_source=CallSource.DIRECT,
        ancestry_match=1.0,
    )

    assert set(_template_values(card, match, confidence)) == available, (
        "evidence._template_values and the TEMPLATE_VARS registry have diverged; one of "
        "them supplies a placeholder the other does not"
    )
