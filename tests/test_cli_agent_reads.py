"""The agent's read commands (roadmap M13.1): ``runs show --section``, ``runs card``,
``runs qc`` and ``cards evidence``.

The saved run is built from committed cards matched against an invented table: each card's
first and last declared allele, so every interpretation card matches as a heterozygote. No
export is read.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli.cards_cmd import evidence_text
from genetics.cli.main import app
from genetics.engine.cards import KnowledgePack, default_knowledge_dir
from genetics.engine.declaration import declaration
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import match_pack
from genetics.ingest.schema import NORMALIZED_SCHEMA, GenotypeTable
from genetics.paths import runs_dir
from genetics.privacy import GenotypeLeakError, find_genotypes
from genetics.qc.report import QCReport
from genetics.run import reads, store
from genetics.run.bundle import RunBundle, StoredCard, read_bundle, write_bundle
from genetics.run.pipeline import observations

runner = CliRunner()

CARD_IDS = (
    "mthfr_c677t_homocysteine",
    "mthfr_c677t_venous_thrombosis",
    "mthfr_c677t_coronary_heart_disease",
    "mthfr_c677t_depression",
    "wnt10a_hair_curl",
    "methylation_epigenetic_age",
)
CLAIMS = CARD_IDS[1:4]
DIRTY = "\t".join(("rs4988235", "2", "136608646", "A", "G"))
"""A genotype row, assembled at runtime so this file holds none."""


@pytest.fixture(scope="module")
def full_pack() -> KnowledgePack:
    return KnowledgePack.load(default_knowledge_dir())


def _table(pack: KnowledgePack) -> GenotypeTable:
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for card in pack.cards:
        if card.match is None:
            continue
        variant = card.match.variants[0]
        first, last = variant.key.alleles[0], variant.key.alleles[-1]
        rows[(variant.key.chrom.value, variant.key.pos_grch37)] = {
            "rsid": variant.rsid,
            "chrom": variant.key.chrom.value,
            "pos_grch37": variant.key.pos_grch37,
            "a1": first,
            "a2": last,
            "genotype": "".join(sorted(first + last)),
            "call_status": "called",
        }
    return GenotypeTable(
        pl.DataFrame(list(rows.values()), schema=NORMALIZED_SCHEMA), vendor="synthetic"
    )


@pytest.fixture
def saved(
    full_pack: KnowledgePack,
    sample_qc: QCReport,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> RunBundle:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    pack = KnowledgePack(
        tuple(card for card in full_pack.cards if card.id in CARD_IDS), full_pack.source_dir
    )
    matches = match_pack(pack, _table(pack))
    path = write_bundle(
        qc=sample_qc,
        cards=assemble_pack(pack, matches, observations(pack, matches)),
        pack=pack,
        ancestry=AncestryContext.not_run("synthetic test bundle"),
        runs_root=runs_dir(),
        lock_path=tmp_path / "absent.lock",
        tools_root=tmp_path / "tools",
    )
    return read_bundle(path)


def _json(args: list[str], code: int = 0) -> Any:
    result = runner.invoke(app, args)
    assert result.exit_code == code, result.output
    return json.loads(result.stdout)


def _text(args: list[str]) -> str:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result.stdout


# ---------------------------------------------------------------------------
# runs show --section
# ---------------------------------------------------------------------------


def test_a_section_read_holds_its_cards_and_not_the_whole_bundle(saved: RunBundle) -> None:
    payload = _json(["runs", "show", saved.run_id, "--section", "physical_health", "--json"])
    assert payload["run_id"] == saved.path.name
    assert payload["sections"] == ["physical_health"]
    assert [c["card_id"] for c in payload["cards"]] == [
        c.card_id for c in saved.cards if c.section == "physical_health"
    ]
    assert {"qc", "clinvar", "imputation_provenance", "pgx"}.isdisjoint(payload)
    whole = _json(["runs", "show", saved.run_id, "--json"])
    by_id = {c["card_id"]: c for c in whole["cards"]}
    assert all(card == by_id[card["card_id"]] for card in payload["cards"])


def test_sections_come_back_once_each_in_report_order(saved: RunBundle) -> None:
    args = ["runs", "show", saved.run_id, "-s", "Nutrition", "-s", "traits", "-s", "nutrition"]
    payload = _json([*args, "--json"])
    assert payload["sections"] == ["traits", "nutrition"]
    contexts = payload["current_context"]["sections"]
    assert [c["section"] for c in contexts] == ["traits", "nutrition"]
    assert payload["current_context"]["context"] == "current"
    text = _text(args)
    assert text.index("Traits, morphology & sensory:") < text.index("Nutrition & metabolism:")
    assert "mthfr_c677t_depression" not in text.split("\n\n")[1]


def test_an_empty_section_says_why(saved: RunBundle) -> None:
    payload = _json(["runs", "show", saved.run_id, "-s", "psychometrics", "--json"])
    (context,) = payload["current_context"]["sections"]
    assert payload["cards"] == []
    assert context["card_count"] == 0
    assert context["empty_reason"] == "Not built yet — roadmap M9.9."
    assert "Not built yet — roadmap M9.9." in _text(
        ["runs", "show", saved.run_id, "-s", "psychometrics"]
    )


def test_the_pgx_notice_is_stated_once_in_its_own_section(saved: RunBundle) -> None:
    from genetics.pgx.presentation import section_framing

    framing = section_framing()
    text = _text(["runs", "show", saved.run_id, "-s", "pharmacogenomics", "-s", "nutrition"])
    assert text.count(framing["text"]) == 1
    payload = _json(["runs", "show", saved.run_id, "-s", "pharmacogenomics", "--json"])
    assert payload["current_context"]["sections"][0]["section_framing"] == framing
    nutrition = _json(["runs", "show", saved.run_id, "-s", "nutrition", "--json"])
    assert "section_framing" not in nutrition["current_context"]["sections"][0]
    assert framing["text"] not in _text(["runs", "show", saved.run_id])


@pytest.mark.parametrize("as_json", [False, True])
def test_an_unknown_section_is_a_usage_error_naming_the_thirteen(
    saved: RunBundle, as_json: bool
) -> None:
    args = ["runs", "show", saved.run_id, "--section", "health", *(["--json"] if as_json else [])]
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    if as_json:
        error = json.loads(result.stdout)["error"]
        assert error["kind"] == "unknown-section"
        assert "physical_health" in error["message"]
    else:
        assert "unknown section 'health'" in result.output


def test_section_pointers_resolve_against_the_run(saved: RunBundle) -> None:
    payload = _json(["runs", "show", saved.run_id, "-s", "nutrition", "--json"])
    related = {p["card_id"]: p for p in payload["current_context"]["sections"][0]["related"]}
    assert set(CLAIMS) <= set(related)
    assert all(related[c]["in_run"] and related[c]["section"] != "nutrition" for c in CLAIMS)
    celiac = related["hla_celiac_dq2_dq8"]
    assert celiac == {
        "card_id": "hla_celiac_dq2_dq8",
        "in_run": False,
        "title": "HLA-DQ2.5 and DQ8 and celiac disease",
        "section": None,
    }
    text = _text(["runs", "show", saved.run_id, "-s", "nutrition"])
    assert "HLA-DQ2.5 and DQ8 and celiac disease (not in this run)" in text
    assert "mthfr_c677t_depression (mental_health)" in text


def test_a_section_names_the_commands_for_its_other_saved_records(saved: RunBundle) -> None:
    payload = _json(["runs", "show", saved.run_id, "-s", "physical_health", "--json"])
    commands = [r["command"] for r in payload["current_context"]["sections"][0]["saved_records"]]
    assert commands == [
        f"genetics runs clinvar {saved.path.name}",
        f"genetics runs secondary {saved.path.name}",
    ]
    for section, names in reads.SAVED_RECORDS.items():
        for _, command in names:
            # Every named command exists: its group and subcommand answer --help.
            words = command.split()[1:-1]
            assert runner.invoke(app, [*words, "--help"]).exit_code == 0, (section, command)


# ---------------------------------------------------------------------------
# runs card
# ---------------------------------------------------------------------------


def test_a_card_read_is_the_saved_card_plus_separate_current_context(saved: RunBundle) -> None:
    whole = {c["card_id"]: c for c in _json(["runs", "show", saved.run_id, "--json"])["cards"]}
    for card_id in CARD_IDS:
        view = _json(["runs", "card", saved.run_id, card_id, "--json"])
        assert set(view) == {
            "schema",
            "run_id",
            "path",
            "format_version",
            "created_at",
            "card",
            "current_context",
        }
        assert view["card"] == whole[card_id]
        assert view["current_context"]["context"] == "current"


def test_the_card_projection_carries_every_saved_field(saved: RunBundle) -> None:
    """A field added to StoredCard and not to the projection would be invisible to agents."""
    names = {field.name for field in dataclasses.fields(StoredCard)}
    assert all(set(reads.card_payload(card)) == names for card in saved.cards)


def test_a_claim_card_reaches_the_card_on_what_the_variant_does(saved: RunBundle) -> None:
    for card_id in CLAIMS:
        context = _json(["runs", "card", saved.run_id, card_id, "--json"])["current_context"]
        assert "mthfr_c677t_homocysteine" in {p["card_id"] for p in context["related"]}
        assert context["pointed_from"] == ["nutrition"]
    home = _json(["runs", "card", saved.run_id, "mthfr_c677t_homocysteine", "--json"])
    assert home["current_context"]["pointed_from"] == ["physical_health", "mental_health"]
    assert set(CLAIMS) <= {p["card_id"] for p in home["current_context"]["related"]}
    text = _text(["runs", "card", saved.run_id, "mthfr_c677t_depression"])
    assert "Mental health also points to: mthfr_c677t_homocysteine (nutrition)" in text
    assert "Pointed to from: nutrition" in text


def test_citation_links_line_up_with_the_saved_citations(saved: RunBundle) -> None:
    view = _json(["runs", "card", saved.run_id, "wnt10a_hair_curl", "--json"])
    links = view["current_context"]["citation_links"]
    assert [(c["type"], c["id"]) for c in view["card"]["citations"]] == [
        (link["type"], link["id"]) for link in links
    ]
    assert links[0]["url"] == "https://doi.org/10.1371/journal.pgen.1000993"


def test_a_card_reads_as_claim_evidence_confidence_and_sources(saved: RunBundle) -> None:
    card = next(c for c in saved.cards if c.card_id == "wnt10a_hair_curl")
    text = _text(["runs", "card", saved.run_id, "wnt10a_hair_curl"])
    for expected in (
        card.summary,
        "variant     rs7349332 at 2:219756383 (GRCh37), alleles C and T",
        "tier gwas; replication independent; n = 5,385; study ancestry EUR",
        "effect beta 0.193 points per T-allele copy",
        f"tier {card.confidence_tier}",
        "evidence_tier",
        "https://doi.org/10.1093/hmg/ddx416",
        "Hair shape is polygenic",
    ):
        assert expected in text, expected
    assert "None" not in text.split("Summary")[0]


def test_an_assay_limit_card_says_why_it_has_no_evidence(saved: RunBundle) -> None:
    text = _text(["runs", "card", saved.run_id, "methylation_epigenetic_age"])
    assert "Not determinable from this data" in text
    assert "None: this card states an assay limit, not a population effect." in text
    assert "Not scored" in text


@pytest.mark.parametrize("as_json", [False, True])
def test_an_unknown_card_is_explained(saved: RunBundle, as_json: bool) -> None:
    result = runner.invoke(
        app, ["runs", "card", saved.run_id, "curly_hair", *(["--json"] if as_json else [])]
    )
    assert result.exit_code == 1
    message = json.loads(result.stdout)["error"]["message"] if as_json else result.output
    assert "no card called 'curly_hair'" in message
    assert f"genetics runs show {saved.path.name}" in message
    if as_json:
        assert json.loads(result.stdout)["error"]["kind"] == "card-not-found"


def test_a_card_in_an_unknown_run_is_not_found(saved: RunBundle) -> None:
    payload = _json(
        ["runs", "card", "20260101T000000Z-00000000", "wnt10a_hair_curl", "--json"], code=1
    )
    assert payload["error"]["kind"] == "not-found"


def test_a_saved_card_and_its_knowledge_entry_cite_the_same_evidence(saved: RunBundle) -> None:
    for card_id in ("wnt10a_hair_curl", "mthfr_c677t_homocysteine"):
        stored = _json(["runs", "card", saved.run_id, card_id, "--json"])["card"]
        declared = _json(["cards", "evidence", card_id, "--json"])
        assert [(c["type"], c["id"]) for c in stored["citations"]] == [
            (c["type"], c["id"]) for c in declared["citations"]
        ]
        if not declared["outcome_evidence"]:
            assert stored["evidence"] == declared["evidence"]


@pytest.mark.privacy
def test_a_card_read_deliberately_states_the_reader_s_call(saved: RunBundle) -> None:
    """As ``runs show`` does: the call is the product. Not scanned, by the same decision."""
    view = _json(["runs", "card", saved.run_id, "wnt10a_hair_curl", "--json"])
    assert view["card"]["match"]["observed_genotype"] == "CT"


# ---------------------------------------------------------------------------
# runs qc
# ---------------------------------------------------------------------------


def test_qc_is_the_saved_report_imputation_record_and_provenance(saved: RunBundle) -> None:
    payload = _json(["runs", "qc", saved.run_id, "--json"])
    assert payload["run_id"] == saved.path.name
    assert payload["qc"] == dict(saved.qc)
    assert payload["provenance"] == dict(saved.provenance)
    assert payload["imputation"] == (None if saved.imputation is None else dict(saved.imputation))
    text = _text(["runs", "qc", saved.run_id])
    assert f"markers      {saved.qc['call_rates']['total_markers']:,}" in text
    assert f"inferred sex              {saved.qc['sex']['inferred']}" in text
    assert "references   none recorded: no manifest.lock at save time" in text


def _with_qc(saved: RunBundle, monkeypatch: pytest.MonkeyPatch, **changes: Any) -> None:
    changed = dataclasses.replace(saved, qc={**saved.qc, **changes})
    monkeypatch.setattr(store, "load_run", lambda *a, **k: changed)


def test_qc_states_every_warning_in_order(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings = [f"synthetic warning {i}" for i in range(5)]
    _with_qc(saved, monkeypatch, warnings=warnings)
    text = _text(["runs", "qc", saved.run_id])
    positions = [text.index(f"! {warning}") for warning in warnings]
    assert positions == sorted(positions)


def test_qc_from_another_version_renders_absent_fields_as_dashes(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_qc(saved, monkeypatch, call_rates="unexpected", sex=None)
    text = _text(["runs", "qc", saved.run_id])
    assert "markers      -" in text
    assert "inferred sex              -" in text


@pytest.mark.privacy
@pytest.mark.parametrize("as_json", [False, True])
def test_both_qc_branches_refuse_to_emit_a_genotype(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    _with_qc(saved, monkeypatch, vendor=DIRTY)
    result = runner.invoke(app, ["runs", "qc", saved.run_id, *(["--json"] if as_json else [])])
    assert isinstance(result.exception, GenotypeLeakError)
    assert DIRTY not in result.output


# ---------------------------------------------------------------------------
# cards evidence
# ---------------------------------------------------------------------------


def test_evidence_states_the_variant_effect_sources_and_caveats() -> None:
    text = _text(["cards", "evidence", "wnt10a_hair_curl"])
    for expected in (
        "variant   rs7349332 at 2:219756383 (GRCh37), alleles C and T",
        "tier gwas; replication independent; n = 5,385; study ancestry EUR",
        "https://doi.org/10.1371/journal.pgen.1000993",
        "Hair shape is polygenic",
    ):
        assert expected in text, expected
    payload = _json(["cards", "evidence", "wnt10a_hair_curl", "--json"])
    assert payload["variants"] == [
        {"rsid": "rs7349332", "chrom": "2", "pos_grch37": 219756383, "alleles": ["C", "T"]}
    ]


def test_outcome_evidence_is_stated_with_the_null_outcomes_explained() -> None:
    payload = _json(["cards", "evidence", "mthfr_c677t_depression", "--json"])
    assert payload["evidence"]["effect"]["value"] == 1.36
    assert payload["outcome_evidence"] == {"ct": None, "cc": None}
    text = _text(["cards", "evidence", "mthfr_c677t_depression"])
    assert "Evidence for outcome ct\n  No phenotype estimate applies to this outcome" in text


@pytest.mark.parametrize("as_json", [False, True])
def test_evidence_for_an_unknown_card_is_explained(as_json: bool) -> None:
    result = runner.invoke(
        app, ["cards", "evidence", "curly_hair", *(["--json"] if as_json else [])]
    )
    assert result.exit_code == 1
    assert "No card called 'curly_hair'" in result.output


@pytest.mark.privacy
def test_evidence_for_every_card_in_the_pack_holds_no_genotype(full_pack: KnowledgePack) -> None:
    """The runtime scan must never refuse correct output, or it gets switched off (M0.3)."""
    for card in full_pack.cards:
        data = declaration(card)
        assert find_genotypes(json.dumps(data, indent=2, ensure_ascii=False)) == [], card.id
        assert find_genotypes(evidence_text(data)) == [], card.id


@pytest.mark.privacy
@pytest.mark.parametrize("as_json", [False, True])
def test_both_evidence_branches_refuse_to_emit_a_genotype(
    monkeypatch: pytest.MonkeyPatch, as_json: bool
) -> None:
    import genetics.engine.declaration as module

    real = module.declaration
    monkeypatch.setattr(module, "declaration", lambda card: real(card) | {"title": DIRTY})
    result = runner.invoke(
        app, ["cards", "evidence", "wnt10a_hair_curl", *(["--json"] if as_json else [])]
    )
    assert isinstance(result.exception, GenotypeLeakError)
    assert DIRTY not in result.output


# ---------------------------------------------------------------------------
# Redirected output on Windows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        ["runs", "show", "{run}", "-s", "psychometrics"],
        ["runs", "card", "{run}", "mthfr_c677t_homocysteine"],
        ["runs", "qc", "{run}"],
        ["cards", "evidence", "mthfr_c677t_homocysteine"],
    ],
)
def test_new_reads_survive_a_legacy_code_page(
    saved: RunBundle, tmp_path: Path, arguments: list[str]
) -> None:
    """``CliRunner`` substitutes a UTF-8 stream; a pipe on Windows gets cp1252 (M11.6)."""
    environment = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "GENETICS_DATA_DIR": str(tmp_path / "data"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "genetics.cli.main",
            *(a.format(run=saved.path.name) for a in arguments),
        ],
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Parity with the dashboard
# ---------------------------------------------------------------------------


def test_section_frames_match_the_dashboard_s(saved: RunBundle) -> None:
    """Counts, empty reasons and pointers, for all thirteen sections, from one run."""
    from genetics.engine.sections import SECTION_ORDER
    from genetics.web import views

    dashboard = {view.section: view for view in views.section_views(saved.cards)}
    cards = views.card_views(saved, run_id=saved.path.name)
    payload = reads.section_view(saved, SECTION_ORDER)
    contexts = payload["current_context"]["sections"]
    assert [c["section"] for c in contexts] == [s.value for s in SECTION_ORDER]
    for context in contexts:
        view = dashboard[context["section"]]
        assert (
            context["title"],
            context["blurb"],
            context["milestone"],
            context["card_count"],
            context["interpreted"],
            context["empty_reason"],
        ) == (
            view.title,
            view.blurb,
            view.milestone,
            view.card_count,
            view.interpreted,
            view.empty_reason,
        )
        links = views.related_links(context["section"], cards)
        assert [(p["card_id"], p["title"], p["in_run"]) for p in context["related"]] == [
            (link.card_id, link.title, link.url is not None) for link in links
        ]


# ---------------------------------------------------------------------------
# Confidence for cards that keep it in their computation (review, 2026-11-10)
# ---------------------------------------------------------------------------


def _with_card(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch, card_id: str, **changes: Any
) -> None:
    cards = tuple(
        dataclasses.replace(card, **changes) if card.card_id == card_id else card
        for card in saved.cards
    )
    changed = dataclasses.replace(saved, cards=cards)
    monkeypatch.setattr(store, "load_run", lambda *a, **k: changed)


def test_a_computed_card_s_reliability_is_printed_not_called_unscored(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Polygenic, computed and guideline cards keep their tier in computation.reliability.

    The first cut printed "Not scored" for every card whose ``confidence`` block was null,
    which is every one of them, while the header line gave their tier.
    """
    reason = "Computed from synthetic inputs; capped by coverage."
    reliability: dict[str, Any] = {
        "tier": "limited",
        "score": 0.31,
        "inputs": {"comparable_weight_fraction": 0.42, "evidence_tier": "gwas"},
        "ceilings": ["coverage"],
        "reason": reason,
    }
    _with_card(
        saved,
        monkeypatch,
        "wnt10a_hair_curl",
        kind="polygenic",
        confidence=None,
        confidence_tier="limited",
        computation={"source": "synthetic", "reliability": reliability},
    )
    text = _text(["runs", "card", saved.run_id, "wnt10a_hair_curl"])
    confidence = text.split("\nConfidence\n")[1].split("\n\n")[0]
    assert "Not scored" not in confidence
    assert "tier limited; score 0.31" in confidence
    assert reason in confidence
    assert "comparable_weight_fraction" in confidence and "0.42" in confidence
    assert "capped by coverage" in confidence


def test_an_unscored_card_names_its_status(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_card(
        saved,
        monkeypatch,
        "wnt10a_hair_curl",
        status="not_on_array",
        confidence=None,
        confidence_tier=None,
    )
    text = _text(["runs", "card", saved.run_id, "wnt10a_hair_curl"])
    assert "Not scored: no finding for this run (status not_on_array)." in text


def test_citation_links_from_other_citations_are_refused() -> None:
    from genetics.cli.render import citation_lines

    with pytest.raises(ValueError):
        citation_lines([{"type": "doi", "id": "10.1000/x"}], [])


# ---------------------------------------------------------------------------
# What decided the tier (M13.4)
# ---------------------------------------------------------------------------


def test_a_card_read_says_what_decided_the_tier(saved: RunBundle) -> None:
    """The block is this engine's reading of the saved inputs, beside the unchanged card."""
    from genetics.run.explain import explain_confidence

    card = next(c for c in saved.cards if c.card_id == "wnt10a_hair_curl")
    view = _json(["runs", "card", saved.run_id, "wnt10a_hair_curl", "--json"])
    block = view["current_context"]["confidence"]
    assert block == json.loads(json.dumps(explain_confidence(card)))
    assert view["card"] == reads.card_payload(card)
    assert "current_context" not in view["card"]
    # This run fetched no frequency reference, so rarity could not be checked (AGENTS.md 4.1).
    assert (block["basis"], block["tier"], block["score_tier"]) == ("ceiling", "moderate", "strong")
    assert block["limiting"] == ["allele_frequency"]
    assert block["source"] == "confidence" and block["replay"]["matches"] is True
    assert block["score"] == view["card"]["confidence"]["score"]


def test_the_text_and_the_json_explain_the_tier_alike(saved: RunBundle) -> None:
    view = _json(["runs", "card", saved.run_id, "wnt10a_hair_curl", "--json"])
    block = view["current_context"]["confidence"]
    text = _text(["runs", "card", saved.run_id, "wnt10a_hair_curl"])
    shown = text.split("\nConfidence\n")[1].split("\n\n")[0]
    assert "tier moderate; score 0.72 (on its own the score gives strong)" in shown
    assert block["reason"] in shown
    for row in block["inputs"]:
        assert f"  {row['name']} " in shown
    assert "component 0.8, weight 0.3, lost 0.06" in shown
    assert "effect_measure beta, effect_value 0.193" in shown
    assert (
        "ceiling from allele_frequency: at most moderate, because no population allele "
        "frequency was available, so rarity could not be checked; sets the tier"
    ) in shown
    # A ceiling above the tier is listed, and not said to set it.
    assert shown.rstrip().endswith(
        "ceiling from ancestry_match: at most strong, because ancestry match to the study "
        "is unknown"
    )


def test_a_ceiling_at_the_score_s_band_is_printed_as_keeping_the_tier(saved: RunBundle) -> None:
    """A claim card whose result has no phenotype estimate: scored low, and capped as well."""
    card_id = next(
        c.card_id for c in saved.cards if c.card_id in CLAIMS and c.confidence_tier == "limited"
    )
    block = _json(["runs", "card", saved.run_id, card_id, "--json"])["current_context"][
        "confidence"
    ]
    assert block["basis"] == "score" and block["limiting"]
    text = _text(["runs", "card", saved.run_id, card_id])
    assert "; keeps the tier here whatever the score" in text
    assert "; sets the tier" not in text
    assert "A higher score would not raise the tier, because" in text


def test_the_explanation_does_not_reach_the_scanned_reads(saved: RunBundle) -> None:
    """`runs qc` and `cards evidence` hold no run result, so they gain nothing."""
    assert "confidence" not in json.dumps(_json(["runs", "qc", saved.run_id, "--json"]))
    evidence = _json(["cards", "evidence", "wnt10a_hair_curl", "--json"])
    assert "current_context" not in evidence


def test_a_rare_call_s_measured_rate_is_printed_once(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sentence that says what decided the tier gives the rate (AGENTS.md 4.1).

    The first version printed the same sentence again two lines below, from the saved
    benchmark. Its scope and the clinical notice are still printed.
    """
    from genetics.engine.confidence import CallSource, calculate_confidence
    from genetics.engine.serialization import confidence_payload

    card = next(c for c in saved.cards if c.card_id == "wnt10a_hair_curl")
    assert card.confidence is not None
    pack = KnowledgePack.load(default_knowledge_dir())
    authored = next(c for c in pack.cards if c.id == "wnt10a_hair_curl").evidence
    rare = confidence_payload(
        calculate_confidence(
            authored, population_allele_frequency=0.000001, call_source=CallSource.DIRECT
        )
    )
    assert rare["tier"] == "likely-artifact"
    _with_card(
        saved, monkeypatch, "wnt10a_hair_curl", confidence=rare, confidence_tier=rare["tier"]
    )
    block = _json(["runs", "card", saved.run_id, "wnt10a_hair_curl", "--json"])["current_context"][
        "confidence"
    ]
    rate = "Published SNP-chip benchmark: about 16% confirmed and 84% unconfirmed"
    assert (block["basis"], block["limiting"]) == ("ceiling", ["allele_frequency"])
    assert rate in block["reason"]
    text = _text(["runs", "card", saved.run_id, "wnt10a_hair_curl"])
    assert text.count(rate) == 1
    assert rare["empirical_ppv"]["applies_to"] in text
    assert "Only clinical sequencing can establish or exclude the variant." in text


def test_a_rate_the_reason_does_not_give_is_still_printed(
    saved: RunBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rare call this engine cannot replay gets no explanation, and keeps its rate."""
    from genetics.engine.confidence import CallSource, calculate_confidence
    from genetics.engine.serialization import confidence_payload

    pack = KnowledgePack.load(default_knowledge_dir())
    authored = next(c for c in pack.cards if c.id == "wnt10a_hair_curl").evidence
    rare = confidence_payload(
        calculate_confidence(
            authored, population_allele_frequency=0.000001, call_source=CallSource.DIRECT
        )
    )
    rare["score"] = round(rare["score"] - 0.05, 4)
    _with_card(
        saved, monkeypatch, "wnt10a_hair_curl", confidence=rare, confidence_tier=rare["tier"]
    )
    text = _text(["runs", "card", saved.run_id, "wnt10a_hair_curl"])
    assert "nothing here says which input decided it" in text
    assert text.count("Published SNP-chip benchmark: about 16% confirmed") == 1
