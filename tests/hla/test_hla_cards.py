"""M11.4 HLA-linked cards: schema, derivation, confidence, CPIC binding and saved evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import polars as pl
import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext, PopulationResult
from genetics.ancestry.populations import Placement, PopulationFit
from genetics.cli.main import app
from genetics.engine.cards import Card, CardError, CardKind, KnowledgePack, parse_file
from genetics.engine.confidence import ConfidenceTier
from genetics.engine.matcher import MatchStatus
from genetics.external import hibag
from genetics.hla import calling, cards, models, selection
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.refs import postprocess

ALLELES = {
    "A": ["01:01", "02:01", "31:01"],
    "B": ["07:02", "08:01", "15:02", "27:05", "57:01", "58:01"],
    "C": ["07:01", "07:02"],
    "DRB1": ["03:01", "04:01", "04:03", "15:01"],
    "DQA1": ["01:02", "02:01", "03:01", "05:01"],
    "DQB1": ["02:01", "02:02", "03:02", "06:02"],
    "DPB1": ["04:01", "04:02"],
}
PAIRS = [("A", "G"), ("C", "A"), ("A", "T"), ("A", "C"), ("G", "T")]
THRESHOLD = 2.0


def pack_card(card_id: str) -> Card:
    card = KnowledgePack.load().by_id(card_id)
    assert card is not None and card.kind is CardKind.HLA
    return card


def reference(
    population: str = "european", alleles: dict[str, list[str]] = ALLELES
) -> dict[str, Any]:
    _, source = models.source_identity(population)
    source["sha256"] = hashlib.sha256(b"synthetic classifier").hexdigest()
    source["size_bytes"] = len(b"synthetic classifier")
    variants = []
    for i, pair in enumerate(PAIRS):
        forward = [a.translate(models.COMPLEMENT) for a in pair] if i == 1 else list(pair)
        variants.append(
            {
                "rsid": f"rs{1100001 + i}",
                "chrom": "6",
                "pos_grch37": 30_000_001 + i,
                "ref": forward[0],
                "alts": [forward[1]],
            }
        )
    loci = {
        locus: {
            "assembly": "hg19",
            "training_samples": 100,
            "classifiers": 10,
            "marker_count": len(PAIRS),
            "allele_count": len(alleles[locus]),
            "markers": [
                {
                    "index": i + 1,
                    "rsid": f"rs{1100001 + i}",
                    "position": 30_000_001 + i,
                    "alleles": list(pair),
                }
                for i, pair in enumerate(PAIRS)
            ],
            "alleles": list(alleles[locus]),
        }
        for locus in models.LOCI
    }
    return {
        "source": source,
        "loci": loci,
        "dbsnp": {
            "provenance": {
                "step": "extract_dbsnp_variant_index",
                "schema_version": postprocess._PROVENANCE_VERSION,
                "transform_version": 1,
                "rows": 5,
                "params": {},
                "input": {"filename": "synthetic.vcf.gz", "sha256": "b" * 64},
                "output": "dbsnp_variants.parquet",
                "output_sha256": "c" * 64,
            },
            "variants": variants,
        },
        "panel": {
            "provenance": {
                "source": models.PANEL,
                "version": "20130502",
                "filename": "ALL.chr6.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz",
                "sha256": "d" * 64,
            },
            "variants": [
                {"id": v["rsid"], **{k: v[k] for k in ("pos_grch37", "ref", "alts")}}
                for v in variants
            ],
        },
    }


def table(*, empty: bool = False) -> GenotypeTable:
    """Synthetic chr6 observations: two of five model markers observed, or none."""
    rows = [] if empty else [(30000001, "A", "G"), (30000002, "G", "T")]
    return GenotypeTable(
        pl.DataFrame(
            [
                {
                    "rsid": f"rs{1100000 + position - 30000000}",
                    "chrom": "6",
                    "pos_grch37": position,
                    "a1": a1,
                    "a2": a2,
                    "genotype": "".join(sorted([a1, a2])),
                    "call_status": "called",
                }
                for position, a1, a2 in rows
            ],
            schema=NORMALIZED_SCHEMA,
        ),
        vendor="synthetic",
    )


def result(population: str, region: str, *, named: bool = True) -> PopulationResult:
    fits = [PopulationFit(population, region, 30, 1.0 if named else 3.0, 1.0, 0.5)]
    return PopulationResult(
        placement=Placement(
            sample_id="SAMPLE",
            coordinates=(0.1, 0.2),
            fits=tuple(fits),
            population=population if named else None,
            declined_because="" if named else "Synthetic panel does not fit.",
            decline_threshold=THRESHOLD,
            coverage=0.98,
            n_scored_markers=100,
            n_reference_markers=100,
            panel_coverage=None,
            labels_source="synthetic.panel",
            n_panel_samples=60,
        ),
        reference="synthetic-pca",
        reference_markers=100,
        n_components=2,
    )


def ancestry(*, placed: bool = True) -> AncestryContext:
    base = AncestryContext.not_run("Synthetic acceptance")
    return AncestryContext(
        population=result("Synthetic_Human_Origins", "Synthetic_Region", named=placed),
        mt=base.mt,
        y=base.y,
        ancient=base.ancient,
        reference_population=result("GBR", "EUR", named=placed),
    )


@pytest.fixture
def build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Schema-2 records from synthetic genotypes and a synthetic HIBAG prediction."""
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "private"))
    model = tmp_path / "synthetic.RData"
    model.write_bytes(b"synthetic classifier")
    runtime = hibag.HIBAGRuntime(Path("synthetic-Rscript"), "4.4.1", "synthetic-platform", "1.40.0")

    def make(
        calls: dict[str, Any],
        *,
        context: AncestryContext | None = None,
        requested: str | None = None,
        alleles: dict[str, list[str]] = ALLELES,
        empty: bool = False,
    ) -> dict[str, Any]:
        context = ancestry() if context is None else context
        choice = selection.select(context.to_dict(), requested=requested)
        ref = reference(choice["classifier"], alleles)

        def execute(runtime: Any, script: str, args: list[str], **kwargs: Any) -> Path:
            output = tmp_path / uuid.uuid4().hex
            output.mkdir()
            meta = ["locus\tassembly\ttraining_samples\tclassifiers\tmarkers\thla_alleles"]
            markers = ["locus\tindex\trsid\tposition\talleles"]
            listed = ["locus\tallele"]
            for locus in models.LOCI:
                m = ref["loci"][locus]
                meta.append(f"{locus}\thg19\t100\t10\t{len(PAIRS)}\t{len(m['alleles'])}")
                markers.extend(
                    f"{locus}\t{s['index']}\t{s['rsid']}\t{s['position']}\t{'/'.join(s['alleles'])}"
                    for s in m["markers"]
                )
                listed.extend(f"{locus}\t{a}" for a in m["alleles"])
            for name, lines in [
                ("models.tsv", meta),
                ("markers.tsv", markers),
                ("alleles.tsv", listed),
            ]:
                (output / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
            model_path, source, token = args
            payload = Path(source).read_bytes()
            rows = ["locus\tsample\tstate\tallele1\tallele2\tposterior"]
            for locus in models.LOCI:
                spec = calls.get(locus, (ref["loci"][locus]["alleles"][0],) * 2 + (0.9,))
                if empty:
                    spec = "no-markers"
                if isinstance(spec, str):
                    rows.append(f"{locus}\t{token}\t{spec}\tNA\tNA\tNA")
                else:
                    rows.append(f"{locus}\t{token}\tpredicted\t{spec[0]}\t{spec[1]}\t{spec[2]}")
            (output / "calls.hla-output.tsv").write_text("\n".join(rows) + "\n")
            (output / "identity.tsv").write_text(
                "sample\tinput_md5\tmodel_md5\n"
                + f"{token}\t{hashlib.md5(payload).hexdigest()}\t"
                + f"{hashlib.md5(Path(model_path).read_bytes()).hexdigest()}\n"
            )
            return output

        monkeypatch.setattr(models, "run_r", execute)
        return calling.impute(table(empty=empty), model, ref, runtime, choice=choice)

    return make


def assemble(card_id: str, record: dict[str, Any] | None, **kwargs: Any) -> Any:
    context = kwargs.pop("context", ancestry())
    return cards.assemble_hla_card(
        pack_card(card_id), record, kwargs.pop("pgx", None), context.to_dict()
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_shipped_cards_are_complete_and_cited() -> None:
    hla = [c for c in KnowledgePack.load().cards if c.kind is CardKind.HLA]
    assert {c.id for c in hla} == {
        "hla_celiac_dq2_dq8",
        "hla_t1d_dr3_dr4_dq8",
        "hla_b27_ankylosing_spondylitis",
        "hla_dqb1_0602_narcolepsy",
        "hla_b5701_abacavir",
        "hla_b1502_carbamazepine",
        "hla_a3101_carbamazepine",
        "hla_b5801_allopurinol",
    }
    for card in hla:
        assert card.citations and card.evidence is not None and card.hla is not None
        assert all(o.risk_context for o in card.outcomes.values())
        bound = card.section.value == "pharmacogenomics"
        assert (card.hla.cpic is not None) == bound
        # The saved definition reads back to an equal card.
        assert cards.definition(Card.parse(cards.definition(card), "copy")) == cards.definition(
            card
        )


def _base() -> dict[str, Any]:
    raw = yaml.safe_load(
        (Path(__file__).parents[2] / "knowledge/pharmacogenomics/hla.yaml").read_text("utf-8")
    )
    return copy.deepcopy(raw["cards"][0])


def _immuno() -> dict[str, Any]:
    raw = yaml.safe_load(
        (Path(__file__).parents[2] / "knowledge/immunogenetics/hla.yaml").read_text("utf-8")
    )
    return copy.deepcopy(raw["cards"][0])


def _set(card: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    keys = path.split(".")
    node: Any = card
    for key in keys[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    if value is KeyError:
        del node[keys[-1]]
    elif isinstance(node, list):
        node[int(keys[-1])] = value
    else:
        node[keys[-1]] = value
    return card


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (
            lambda: _set(_base(), "hla.alternatives.0.all_of.0.alleles", [5701]),
            "quote every allele",
        ),
        (lambda: _set(_base(), "hla.alternatives.0.all_of.0.alleles", ["5701"]), "two-field"),
        (lambda: _set(_base(), "hla.alternatives.0.all_of.0.locus", "DRB3"), "locus must be"),
        (lambda: _set(_base(), "hla.states", {"B*57:01": "carrier"}), "every alternative"),
        (lambda: _set(_base(), "outcomes.carrier.risk_context", KeyError), "risk_context"),
        (
            lambda: _set(_base(), "outcomes.carrier.summary", "{genotype} carrier"),
            "cannot be filled",
        ),
        (lambda: _set(_base(), "hla.cpic", KeyError), "binds its frozen CPIC"),
        (lambda: _set(_base(), "hla.cpic.allele", "*57:02"), "CPIC-bound card"),
        (lambda: _set(_base(), "section", "traits"), "immunogenetics or pharmacogenomics"),
        (lambda: _set(_base(), "confidence", "high"), "computed"),
        (lambda: _set(_immuno(), "hla.cpic", {"gene": "HLA-DQB1", "allele": "*02:01"}), "binds"),
        (lambda: _set(_immuno(), "hla.phase", KeyError), "declare why unphased"),
        (lambda: _set(_immuno(), "hla.phase", "haplotype"), "declare why unphased"),
        (
            lambda: _set(
                _immuno(),
                "hla.alternatives.0.all_of",
                [{"locus": "DQA1", "alleles": ["05"]}] * 3,
            ),
            "more than twice",
        ),
    ],
)
def test_schema_refusals(make: Any, message: str) -> None:
    with pytest.raises(CardError, match=message):
        Card.parse(make(), "test")


def test_phase_is_refused_where_nothing_spans_loci() -> None:
    with pytest.raises(CardError, match="only an alternative spanning loci"):
        Card.parse(_set(_base(), "hla.phase", "genotype"), "test")


def test_hla_cards_need_schema_six_and_their_own_kind() -> None:
    text = yaml.safe_dump({"schema_version": 5, "cards": [_base()]})
    with pytest.raises(CardError, match="schema_version 6"):
        parse_file(text, "old.yaml")
    interpretation = _set(_base(), "kind", "impossibility")
    with pytest.raises(CardError):
        Card.parse(interpretation, "test")


# ---------------------------------------------------------------------------
# Derivation and confidence
# ---------------------------------------------------------------------------


def test_selected_carrier_states_call_reliability_and_ancestry(build: Any) -> None:
    record = build({"B": ("07:02", "57:01", 0.95)})
    card = assemble("hla_b5701_abacavir", record)
    assert card.status is MatchStatus.MATCHED and card.match.outcome_name == "carrier"
    assert card.confidence is not None and card.confidence.tier is ConfidenceTier.MODERATE
    inputs = card.confidence.inputs
    assert inputs.imputation_quality == 0.95 and inputs.population_allele_frequency is None
    assert inputs.call_source.value == "imputed" and inputs.ancestry_match == 1.0
    for text in (
        "Model call: HLA-B 07:02/57:01 (joint posterior 0.95).",
        "Carried: B*57:01 (HLA-B*57:01).",
        "selected from the ancestry placement; classifier ancestry match 1",
        cards.FREQUENCY_NOTE,
        "Ancestry: matched at super-population level (EUR)",
    ):
        assert text in card.summary
    assert card.risk_context is not None and "47.9%" in card.risk_context
    result = card.computation["result"]
    assert result["reliability"]["locus_ceiling"] == "moderate"  # 2 of 5 markers observed
    assert result["loci"]["B"]["emittable"] == {"57:01": ["57:01"]}


def test_non_carrier_is_a_model_call_with_its_own_evidence(build: Any) -> None:
    card = assemble("hla_b5701_abacavir", build({"B": ("07:02", "08:01", 0.95)}))
    assert card.match.outcome_name == "non_carrier" and card.status is MatchStatus.MATCHED
    assert "None of B*57:01 is carried by these model calls." in card.summary
    assert "not clinical" in card.summary
    assert card.card.evidence is not None and card.card.evidence.effect.value == 0.034


def test_low_posterior_is_labelled_not_filtered(build: Any) -> None:
    card = assemble("hla_b5701_abacavir", build({"B": ("07:02", "57:01", 0.2)}))
    assert card.status is MatchStatus.MATCHED
    assert card.confidence is not None and card.confidence.tier is ConfidenceTier.LIKELY_ARTIFACT
    assert any("below the 0.5" in c for c in card.computed_caveats)


def test_contradicted_explicit_classifier_caps_at_limited(build: Any) -> None:
    record = build({"B": ("07:02", "57:01", 0.95)}, requested="asian")
    card = assemble("hla_b5701_abacavir", record)
    assert card.confidence is not None and card.confidence.tier is ConfidenceTier.LIMITED
    assert "explicitly requested; automatic selection selected" in card.summary
    assert "classifier ancestry match 0" in card.summary
    assert "ancestry" in card.computation["result"]["loci"]["B"]["confidence"]["ceilings"]


def test_weakest_locus_governs_and_posteriors_are_not_multiplied(build: Any) -> None:
    record = build({"DQA1": ("01:02", "05:01", 0.95), "DQB1": ("02:01", "06:02", 0.55)})
    card = assemble("hla_celiac_dq2_dq8", record)
    reliability = card.computation["result"]["reliability"]
    assert reliability["posterior_locus"] == "DQB1" and reliability["posterior"] == 0.55
    assert card.confidence is not None
    assert card.confidence.inputs.imputation_quality == 0.55
    assert card.confidence.tier is ConfidenceTier.LIMITED


@pytest.mark.parametrize(
    ("calls", "outcome", "state"),
    [
        (
            {"DQA1": ("01:02", "05:01", 0.9), "DQB1": ("02:01", "06:02", 0.9)},
            "risk_heterodimer",
            "DQ2.5",
        ),
        (
            {"DQA1": ("03:01", "05:01", 0.9), "DQB1": ("03:02", "06:02", 0.9)},
            "risk_heterodimer",
            "DQ8",
        ),
        (
            {"DQA1": ("01:02", "05:01", 0.9), "DQB1": ("03:02", "06:02", 0.9)},
            "half_heterodimer",
            "half DQ2.5 (DQA1*05)",
        ),
        (
            {"DQA1": ("01:02", "02:01", 0.9), "DQB1": ("02:02", "06:02", 0.9)},
            "half_heterodimer",
            "half DQ2.5 (DQB1*02)",
        ),
        ({"DQA1": ("01:02", "02:01", 0.9), "DQB1": ("06:02", "06:02", 0.9)}, "neither", "none"),
    ],
)
def test_celiac_alternatives_are_ordered(build: Any, calls: Any, outcome: str, state: str) -> None:
    card = assemble("hla_celiac_dq2_dq8", build(calls))
    assert card.match.outcome_name == outcome
    assert card.computation["result"]["state"] == state
    assert cards.PHASE_TEXT["heterodimer"] in card.summary


@pytest.mark.parametrize(
    ("drb1", "dqb1", "outcome"),
    [
        (("03:01", "04:01"), ("03:02", "06:02"), "high_risk_genotype"),
        (("03:01", "03:01"), ("03:02", "03:02"), "other_genotype"),  # one allele cannot be both
        (("04:01", "04:03"), ("03:02", "06:02"), "other_genotype"),
        (("03:01", "04:03"), ("03:02", "06:02"), "high_risk_genotype"),  # caveated subtype
    ],
)
def test_two_terms_at_a_locus_take_different_alleles(
    build: Any, drb1: tuple[str, str], dqb1: tuple[str, str], outcome: str
) -> None:
    record = build({"DRB1": (*drb1, 0.9), "DQB1": (*dqb1, 0.9)})
    card = assemble("hla_t1d_dr3_dr4_dq8", record)
    assert card.match.outcome_name == outcome
    assert cards.PHASE_TEXT["genotype"] in card.summary


def _expect_not_determinable(card: Any, status: MatchStatus, reason: str) -> None:
    assert card.status is status and card.confidence is None and card.risk_context is None
    assert card.computation["reliability"]["tier"] is None
    assert reason in card.summary and cards.NOT_EVIDENCE in card.summary
    assert "not determinable" in card.summary


def test_absence_is_never_a_negative(build: Any) -> None:
    _expect_not_determinable(
        assemble("hla_b27_ankylosing_spondylitis", None), MatchStatus.NOT_RUN, "did not record"
    )
    _expect_not_determinable(
        assemble("hla_b27_ankylosing_spondylitis", calling.unavailable("not-selected")),
        MatchStatus.NOT_RUN,
        "--hla-model-opt-in",
    )
    declined = ancestry(placed=False)
    refusal = calling.unavailable("no-classifier", selection.select(declined.to_dict()))
    _expect_not_determinable(
        assemble("hla_b27_ankylosing_spondylitis", refusal, context=declined),
        MatchStatus.NOT_RUN,
        "No HIBAG classifier was selected: The Human Origins (AADR) and 1000 Genomes placement",
    )
    _expect_not_determinable(
        assemble("hla_b27_ankylosing_spondylitis", build({"B": "no-prediction"})),
        MatchStatus.INSUFFICIENT_COVERAGE,
        "HLA-B: the classifier returned no prediction.",
    )
    _expect_not_determinable(
        assemble("hla_b27_ankylosing_spondylitis", build({}, empty=True)),
        MatchStatus.INSUFFICIENT_CALLS,
        "no model marker was observed",
    )
    narrow = {**ALLELES, "B": ["07:02", "08:01"]}
    _expect_not_determinable(
        assemble("hla_b5701_abacavir", build({"B": ("07:02", "08:01", 0.99)}, alleles=narrow)),
        MatchStatus.INSUFFICIENT_COVERAGE,
        "cannot emit HLA-B*57:01",
    )


def test_schema_one_record_keeps_its_match_unknown(build: Any) -> None:
    record = build({"B": ("07:02", "27:05", 0.95)})
    old = copy.deepcopy(record)
    old["schema_version"] = calling.LEGACY_VERSION
    del old["selection"]
    for gene in old["genes"].values():
        del gene["confidence"]
    card = assemble("hla_b27_ankylosing_spondylitis", old)
    assert card.match.outcome_name == "carrier"
    assert "ancestry selection not recorded (HLA schema 1)" in card.summary
    assert "classifier ancestry match unknown" in card.summary
    assert any("HLA schema 1" in c for c in card.computed_caveats)


# ---------------------------------------------------------------------------
# CPIC binding
# ---------------------------------------------------------------------------


def _pgx(*, url: str = "https://www.clinpgx.org/guideline/PA1") -> dict[str, Any]:
    def rec(identity: str, guideline: str, drug: str, key: dict[str, str]) -> dict[str, Any]:
        return {
            "id": identity,
            "guidelineid": guideline,
            "drugid": drug,
            "lookupkey": json.dumps(key),
            "drugrecommendation": f"Synthetic recommendation {identity}",
            "classification": "Strong",
            "population": "general",
        }

    def pair(gene: str, guideline: str, drug: str) -> dict[str, Any]:
        return {
            "pairid": f"{gene}-{drug}",
            "genesymbol": gene,
            "guidelineid": guideline,
            "drugid": drug,
            "cpiclevel": "A",
        }

    return {
        "status": "completed",
        "reason": None,
        "reference_sha256": "e" * 64,
        "reference": {
            "cpic": {
                "source": {"id": "cpic", "version": "synthetic", "license_id": "synthetic"},
                "tables": {
                    "drug": [
                        {"drugid": "D1", "name": "abacavir"},
                        {"drugid": "D2", "name": "carbamazepine"},
                        {"drugid": "D3", "name": "phenytoin"},
                    ],
                    "guideline": [
                        {"id": "G1", "name": "HLA-B and Abacavir", "url": url},
                        {"id": "G2", "name": "HLA and Carbamazepine", "url": url},
                        {"id": "G3", "name": "CYP2C9, HLA-B and Phenytoin", "url": url},
                    ],
                    "publication": [
                        {
                            "guidelineid": g,
                            "pmid": "22378157",
                            "doi": None,
                            "title": "Synthetic guideline",
                        }
                        for g in ("G1", "G2", "G3")
                    ],
                    "pair": [
                        pair("HLA-B", "G1", "D1"),
                        pair("HLA-A", "G2", "D2"),
                        pair("HLA-B", "G2", "D2"),
                        pair("HLA-B", "G3", "D3"),
                    ],
                    "recommendation": [
                        rec("R1", "G1", "D1", {"HLA-B": "*57:01 positive"}),
                        rec("R2", "G1", "D1", {"HLA-B": "*57:01 negative"}),
                        rec(
                            "R3",
                            "G2",
                            "D2",
                            {"HLA-A": "*31:01 negative", "HLA-B": "*15:02 positive"},
                        ),
                        rec(
                            "R4",
                            "G2",
                            "D2",
                            {"HLA-A": "*31:01 positive", "HLA-B": "*15:02 positive"},
                        ),
                        rec("R5", "G2", "D2", {"HLA-A": "No Result", "HLA-B": "*15:02 positive"}),
                        rec("R6", "G3", "D3", {"HLA-B": "*15:02 positive", "CYP2C9": "1.0"}),
                    ],
                },
            }
        },
    }


def _rows(card: Any) -> list[str]:
    return [r["source_row"]["id"] for r in card.computation["result"]["cpic"]["recommendations"]]


def test_cpic_lookup_follows_the_carrier_state(build: Any) -> None:
    carrier = assemble("hla_b5701_abacavir", build({"B": ("07:02", "57:01", 0.95)}), pgx=_pgx())
    assert _rows(carrier) == ["R1"]
    assert (
        "Frozen CPIC lookup HLA-B *57:01 positive: 1 conditional recommendation row(s) for abacavir"
        in carrier.summary
    )
    negative = assemble("hla_b5701_abacavir", build({"B": ("07:02", "08:01", 0.95)}), pgx=_pgx())
    assert _rows(negative) == ["R2"]


def test_other_hla_genes_resolve_from_the_same_record(build: Any) -> None:
    record = build({"A": ("01:01", "02:01", 0.9), "B": ("07:02", "15:02", 0.9)})
    card = assemble("hla_b1502_carbamazepine", record, pgx=_pgx())
    # A*31:01 is emittable and absent: R3 compatible, R4 excluded, R5 ("No Result") excluded.
    assert _rows(card) == ["R3", "R6"]
    phenytoin = card.computation["result"]["cpic"]["recommendations"][1]
    assert [c["state"] for c in phenytoin["conditions"]] == ["compatible", "unassessed"]
    assert any("unassessed" in gap for gap in phenytoin["gaps"])
    unknown = assemble(
        "hla_b1502_carbamazepine",
        build({"A": "no-prediction", "B": ("07:02", "15:02", 0.9)}),
        pgx=_pgx(),
    )
    # The HLA-B call is determinable, so its card is too; the HLA-A condition is not.
    assert unknown.status is MatchStatus.MATCHED and _rows(unknown) == ["R3", "R4", "R5", "R6"]


def test_cpic_gaps_and_absence_stay_explicit(build: Any) -> None:
    record = build({"B": ("07:02", "57:01", 0.95)})
    broken = assemble("hla_b5701_abacavir", record, pgx=_pgx(url="http://insecure.example"))
    row = broken.computation["result"]["cpic"]["recommendations"][0]
    assert row["status"] == "evidence-missing" and "Guideline row/URL not provided." in row["gaps"]
    absent = assemble("hla_b5701_abacavir", record)
    assert absent.computation["result"]["cpic"]["status"] == "unavailable"
    assert "frozen CPIC release was not recorded" in absent.summary
    undetermined = assemble(
        "hla_b5701_abacavir",
        calling.unavailable("r-missing", selection.select(ancestry().to_dict())),
        pgx=_pgx(),
    )
    assert undetermined.computation["result"]["cpic"]["status"] == "not-determinable"
    assert _rows(undetermined) == []


# ---------------------------------------------------------------------------
# Saved evidence and interfaces
# ---------------------------------------------------------------------------


def _rewrite(path: Path, name: str, payload: Any, *, version: int | None = None) -> None:
    header_path = path / "manifest.json"
    header = json.loads(header_path.read_text())
    raw = json.dumps(payload).encode()
    (path / name).write_bytes(raw)
    header["files"][name] = hashlib.sha256(raw).hexdigest()
    if version is not None:
        header["format_version"] = version
    header_path.write_text(json.dumps(header))


def test_saved_cards_rebuild_from_frozen_evidence(
    build: Any, sample_qc: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.pgx.calling import unavailable as pgx_unavailable
    from genetics.run.bundle import CARDS_NAME, BundleError, read_bundle, write_bundle
    from genetics.web.app import create_app
    from genetics.web.config import WebConfig

    context = ancestry()
    record = build({"B": ("07:02", "57:01", 0.95), "DQB1": ("02:01", "06:02", 0.91)})
    other = build({"B": ("07:02", "57:01", 0.95), "DQB1": ("02:01", "06:02", 0.91)})
    pgx = pgx_unavailable(
        "PGx calling was not supplied to the bundle writer.", sex=sample_qc.sex.inferred.value
    ).to_dict()
    pack = KnowledgePack.load()
    linked = tuple(
        cards.assemble_hla_card(c, record, pgx, context.to_dict())
        for c in pack.cards
        if c.kind is CardKind.HLA
    )
    common: dict[str, Any] = {
        "qc": sample_qc,
        "pack": pack,
        "ancestry": context,
        "runs_root": tmp_path / "runs",
        "lock_path": tmp_path / "absent.lock",
        "tools_root": tmp_path / "tools",
    }
    with pytest.raises(BundleError, match="HLA-linked card"):
        # Internally valid cards, read from another run's HLA record.
        write_bundle(**common, cards=linked, hla=other, run_id="hla-cards-foreign")
    path = write_bundle(**common, cards=linked, hla=record, run_id="hla-cards")
    monkeypatch.setattr(hibag, "probe", lambda **_: pytest.fail("Saved reading must not probe R"))
    bundle = read_bundle(path)
    saved = {c.card_id: c for c in bundle.cards}
    assert saved["hla_dqb1_0602_narcolepsy"].confidence_tier == "moderate"
    assert saved["hla_b5701_abacavir"].risk_context is not None
    assert saved["hla_celiac_dq2_dq8"].match["outcome_name"] == "half_heterodimer"

    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path))
    text = CliRunner().invoke(app, ["hla", "calls", path.name])
    assert text.exit_code == 0 and "HLA-linked cards: 8 saved" in text.output
    assert "hla_b5701_abacavir: matched; moderate; pharmacogenomics" in text.output
    shown = CliRunner().invoke(app, ["runs", "show", path.name])
    assert shown.exit_code == 0 and "PREDICT-1" in shown.output
    client = TestClient(
        create_app(WebConfig(runs_root=tmp_path / "runs")), base_url="http://127.0.0.1"
    )
    page = client.get(f"/runs/{path.name}/hla")
    assert page.status_code == 200 and "HLA-linked cards" in page.text
    assert "HLA-B*57:01 and abacavir hypersensitivity" in page.text
    detail = client.get(f"/runs/{path.name}/cards/hla_b5701_abacavir")
    assert detail.status_code == 200 and "HLA classifier evidence" in detail.text
    assert "Frozen CPIC rows" in detail.text and "07:02 / 57:01" in detail.text
    assert "Calls for the loci this card names" in detail.text
    dash = client.get(f"/runs/{path.name}")
    assert dash.status_code == 200 and "HLA-DQB1*06:02 and narcolepsy with cataplexy" in dash.text

    original = json.loads((path / CARDS_NAME).read_text())
    edits: list[tuple[tuple[str, ...], Any]] = [
        (("computation", "result", "loci", "B", "posterior"), 0.5),
        (("confidence", "tier"), "strong"),
        (("computation", "result", "definition", "outcomes", "carrier", "summary"), "Edited."),
        (("summary",), "Edited."),
    ]
    for keys, value in edits:
        payload = copy.deepcopy(original)
        entry = next(c for c in payload["cards"] if c["card_id"] == "hla_b5701_abacavir")
        node = entry
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value
        _rewrite(path, CARDS_NAME, payload)
        with pytest.raises(BundleError):
            read_bundle(path)
    _rewrite(path, CARDS_NAME, original, version=22)
    with pytest.raises(BundleError, match="format 23"):
        read_bundle(path)
    _rewrite(path, CARDS_NAME, {"cards": []}, version=22)
    old = read_bundle(path)
    assert old.format_version == 22 and not old.cards
    assert "predates HLA-linked cards" in client.get(f"/runs/{path.name}/hla").text
    text = CliRunner().invoke(app, ["hla", "calls", path.name])
    assert "HLA-linked cards: not recorded (bundle format 22)" in text.output


def test_pipeline_assembles_hla_cards_from_its_own_stage() -> None:
    from genetics.run.pipeline import analyse

    path = Path(__file__).parents[1] / "fixtures/synthetic/ancestry_v2_male.txt"
    result = analyse(
        path,
        no_impute=True,
        hla=calling.HLAStage(opt_in=True),
        ancestry=lambda *_: AncestryContext.not_run("Synthetic acceptance"),
    )
    linked = [c for c in result.cards if c.kind is CardKind.HLA]
    assert len(linked) == 8
    for card in linked:
        assert card.status is MatchStatus.NOT_RUN and card.confidence is None
        assert "No HIBAG classifier was selected" in card.summary


@pytest.mark.parametrize(
    ("pair", "outcome"), [(("07:02", "27:05"), "non_carrier"), (("27:05", "27:05"), "carrier")]
)
def test_one_allele_cannot_meet_two_terms(build: Any, pair: tuple[str, str], outcome: str) -> None:
    raw = yaml.safe_load(
        (Path(__file__).parents[2] / "knowledge/immunogenetics/hla.yaml").read_text("utf-8")
    )
    spec = next(c for c in raw["cards"] if c["id"] == "hla_b27_ankylosing_spondylitis")
    spec["hla"]["alternatives"] = [
        {"name": "two B27", "all_of": [{"locus": "B", "alleles": ["27"]}] * 2}
    ]
    spec["hla"]["states"] = {"two B27": "carrier", "none": "non_carrier"}
    card = cards.assemble_hla_card(
        Card.parse(spec, "synthetic homozygosity"),
        build({"B": (*pair, 0.9)}),
        None,
        ancestry().to_dict(),
    )
    assert card.match.outcome_name == outcome


REAL_CPIC = Path(__file__).parents[2] / "data/references/cpic/pgx_reference.json"


@pytest.mark.skipif(not REAL_CPIC.exists(), reason="prepared CPIC reference not fetched")
def test_real_frozen_cpic_rows_bind_each_drug_card(build: Any) -> None:
    """Acceptance against the fetched CPIC v1.60.0 release; synthetic HLA calls only."""
    pgx = {
        "status": "completed",
        "reason": None,
        "reference": json.loads(REAL_CPIC.read_text(encoding="utf-8")),
        "reference_sha256": "f" * 64,
    }
    record = build(
        {"A": ("01:01", "31:01", 0.9), "B": ("57:01", "58:01", 0.9)},
    )
    abacavir = assemble("hla_b5701_abacavir", record, pgx=pgx)
    rows = abacavir.computation["result"]["cpic"]["recommendations"]
    assert [r["source_row"]["drugrecommendation"] for r in rows] == ["Abacavir is not recommended"]
    assert all(r["status"] == "conditional" for r in rows)
    allopurinol = assemble("hla_b5801_allopurinol", record, pgx=pgx)
    assert [
        r["source_row"]["drugrecommendation"]
        for r in allopurinol.computation["result"]["cpic"]["recommendations"]
    ] == ["Allopurinol is contraindicated"]
    # A*31:01 positive with B*15:02 called absent: only rows keyed on that combination.
    a3101 = assemble("hla_a3101_carbamazepine", record, pgx=pgx)
    keys = {
        r["source_row"]["lookupkey"] for r in a3101.computation["result"]["cpic"]["recommendations"]
    }
    assert keys == {'{"HLA-A": "*31:01 positive", "HLA-B": "*15:02 negative"}'}
    b1502 = assemble("hla_b1502_carbamazepine", record, pgx=pgx)
    drugs = {
        r["drug"]["name"]
        for r in b1502.computation["result"]["cpic"]["recommendations"]
        if r["drug"] is not None
    }
    # B*15:02 negative: carbamazepine (with A*31:01 positive), oxcarbazepine, and phenytoin
    # and fosphenytoin, whose CYP2C9 conditions stay unassessed by this card.
    assert drugs == {"carbamazepine", "oxcarbazepine", "phenytoin", "fosphenytoin"}
    phenytoin = [
        r
        for r in b1502.computation["result"]["cpic"]["recommendations"]
        if r["drug"] and r["drug"]["name"] in {"phenytoin", "fosphenytoin"}
    ]
    assert phenytoin and all(
        c["state"] == "unassessed"
        for r in phenytoin
        for c in r["conditions"]
        if c["gene"] == "CYP2C9"
    )
