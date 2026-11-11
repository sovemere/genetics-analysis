"""The agent CLI's versioned JSON schema (roadmap M13.2).

``src/genetics/cli/agent_schema.json`` is checked three ways. It is a valid JSON Schema. Its
vocabularies and key lists equal the engine's own, so neither can move alone. And what the
commands print matches it, for a saved run built from the committed pack and for every card's
evidence. The saved runs with HLA and guideline cards are built by ``tests/hla`` and
``tests/refs``, which check them with the same ``agent_schema_check`` fixture.

The run is matched against an invented table: each card's first and last declared allele.
No export is read.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from collections.abc import Callable, Iterator
from enum import StrEnum
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from genetics.ancestry.context import AncestryContext
from genetics.cli import contract
from genetics.cli.main import app
from genetics.engine.cards import (
    Ancestry,
    CardKind,
    EffectMeasure,
    EvidenceTier,
    KnowledgePack,
    Replication,
    default_knowledge_dir,
)
from genetics.engine.citations import CitationType
from genetics.engine.confidence import CallSource, ConfidenceTier
from genetics.engine.evidence import assemble_pack
from genetics.engine.matcher import MatchStatus, Strand, match_pack
from genetics.engine.sections import SECTION_ORDER, Section
from genetics.ingest.schema import NORMALIZED_SCHEMA, CallStatus, GenotypeTable
from genetics.privacy import find_genotypes
from genetics.qc.report import QCReport
from genetics.run.bundle import (
    BUNDLE_FORMAT_VERSION,
    CARD_KEYS,
    MANIFEST_NAME,
    RunBundle,
    StoredCard,
    read_bundle,
    write_bundle,
)
from genetics.run.pipeline import observations
from genetics.run.store import RunStatus

runner = CliRunner()
Check = Callable[[object], str]
Change = Callable[[dict[str, Any]], object]

SHAPE_DIGESTS = {
    1: "b03f416e3aa1d460629018bbeec56c493286e3d4c042c0af7e272dcfc5d740f5",
    2: "8451a2298c73410063d93d775ed93ee1242b843ac35ead8dd47fbb26dc814e09",
}
"""The shape of each schema version that has shipped, descriptions left out.

Never edit an entry. A change to any described shape takes the next version number: bump
``contract.AGENT_SCHEMA_VERSION`` and the document's ``version``, add the new digest here,
and add the change to the version history in docs/agent_schema.md. Changes are additions
only; a key is never removed or given another meaning.
"""

ENVELOPE = {"schema", "run_id", "path"}
"""Top-level keys of a run-scoped document that describe the read, not the run."""

RUN_SCOPED = ("runs.show", "runs.section", "runs.card", "runs.qc")


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def _shape(node: Any) -> Any:
    """``node`` without its prose. Names under ``properties`` and ``$defs`` are kept."""
    if isinstance(node, list):
        return [_shape(item) for item in node]
    if not isinstance(node, dict):
        return node
    shaped: dict[str, Any] = {}
    for key, value in node.items():
        if key in {"properties", "$defs"}:
            shaped[key] = {name: _shape(sub) for name, sub in value.items()}
        elif not (key in {"description", "title"} and isinstance(value, str)):
            shaped[key] = _shape(value)
    return shaped


def _shape_digest(document: dict[str, Any]) -> str:
    canonical = json.dumps(_shape(document), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def test_the_document_is_a_valid_schema_at_the_declared_version() -> None:
    document = contract.document()
    Draft202012Validator.check_schema(document)
    assert document["version"] == contract.AGENT_SCHEMA_VERSION
    for name in contract.payload_names():
        Draft202012Validator.check_schema(contract.payload_schema(name))


def test_every_payload_is_listed_defined_and_reachable() -> None:
    document = contract.document()
    names = contract.payload_names()
    assert len(set(names)) == len(names)
    assert [ref.removeprefix("#/$defs/") for ref in _refs(document["oneOf"])] == list(names)
    defs = document["$defs"]
    for name in names:
        assert defs[name]["properties"]["schema"] == {"$ref": f"#/$defs/tag.{name}"}
        tag = defs[f"tag.{name}"]["properties"]
        assert tag["name"] == {"const": name}
        assert tag["version"] == {"const": contract.AGENT_SCHEMA_VERSION}
        assert "schema" in defs[name]["required"]
    # No dangling reference, and no definition nothing uses.
    used = {ref.removeprefix("#/$defs/") for ref in _refs(document)}
    assert used == set(defs)


def test_a_shipped_version_s_shape_cannot_change() -> None:
    """Editing the document under a version that has shipped fails here. See SHAPE_DIGESTS."""
    assert set(SHAPE_DIGESTS) == set(range(1, contract.AGENT_SCHEMA_VERSION + 1))
    assert _shape_digest(contract.document()) == SHAPE_DIGESTS[contract.AGENT_SCHEMA_VERSION]


def test_the_shape_digest_ignores_prose_and_sees_everything_else() -> None:
    document = contract.document()
    reworded = contract.document()
    reworded["$defs"]["variant"]["description"] = "Reworded."
    assert _shape_digest(reworded) == _shape_digest(document)
    changes: tuple[Change, ...] = (
        lambda d: d["$defs"]["variant"]["required"].remove("rsid"),
        lambda d: d["$defs"]["variant"]["properties"].pop("rsid"),
        lambda d: d["$defs"]["section_name"]["enum"].append("new_section"),
        # A property that happens to be called `title` is shape, not prose.
        lambda d: d["$defs"]["stored_card"]["properties"].pop("title"),
    )
    for change in changes:
        changed = contract.document()
        change(changed)
        assert _shape_digest(changed) != _shape_digest(document)


@pytest.mark.parametrize(
    ("definition", "vocabulary"),
    [
        ("section_name", Section),
        ("card_kind", CardKind),
        ("card_status", MatchStatus),
        ("confidence_tier", ConfidenceTier),
        ("evidence_tier", EvidenceTier),
        ("replication", Replication),
        ("effect_measure", EffectMeasure),
        ("study_ancestry", Ancestry),
        ("citation_type", CitationType),
        ("call_source", CallSource),
        ("call_status", CallStatus),
        ("strand", Strand),
        ("run_status", RunStatus),
    ],
)
def test_each_vocabulary_is_the_engine_s_own(definition: str, vocabulary: type[StrEnum]) -> None:
    """A value added to an engine enum must reach the schema, with a version bump."""
    assert contract.document()["$defs"][definition]["enum"] == [m.value for m in vocabulary]


def test_sections_are_listed_in_report_order() -> None:
    listed = contract.document()["$defs"]["section_name"]["enum"]
    assert listed == [section.value for section in SECTION_ORDER]


def test_the_card_definition_has_every_saved_key_and_no_other() -> None:
    card = contract.document()["$defs"]["stored_card"]
    fields = {field.name for field in dataclasses.fields(StoredCard)}
    assert set(card["properties"]) == fields == CARD_KEYS | {"confidence_tier"}
    assert set(card["required"]) == fields
    assert card["additionalProperties"] is False


def test_citations_are_required_wherever_a_card_is_printed() -> None:
    """The roadmap's one named requirement: card JSON must include citations."""
    defs = contract.document()["$defs"]
    assert "citations" in defs["stored_card"]["required"]
    assert "citations" in defs["cards.evidence"]["required"]
    assert {"type", "id"} <= set(defs["citation"]["required"])
    assert "citation_links" in defs["runs.card"]["properties"]["current_context"]["required"]


def test_closed_objects_are_closed_so_an_unlisted_key_fails() -> None:
    """Every object the engine builds at read time rejects a key the schema does not list."""
    defs = contract.document()["$defs"]
    for name in (*contract.payload_names(), "section_context", "pointer", "run_summary"):
        assert defs[name]["additionalProperties"] is False, name


# ---------------------------------------------------------------------------
# A saved run from the committed pack
# ---------------------------------------------------------------------------


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


@pytest.fixture(scope="module")
def full_pack() -> KnowledgePack:
    return KnowledgePack.load(default_knowledge_dir())


@pytest.fixture(scope="module")
def saved(
    full_pack: KnowledgePack, sample_qc: QCReport, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[RunBundle]:
    """Every card that needs no stage record: all but the HLA and guideline kinds."""
    root = tmp_path_factory.mktemp("agent-schema")
    pack = KnowledgePack(
        tuple(c for c in full_pack.cards if c.kind not in {CardKind.HLA, CardKind.GUIDELINE}),
        full_pack.source_dir,
    )
    matches = match_pack(pack, _table(pack))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("GENETICS_DATA_DIR", str(root / "data"))
        path = write_bundle(
            qc=sample_qc,
            cards=assemble_pack(pack, matches, observations(pack, matches)),
            pack=pack,
            ancestry=AncestryContext.not_run("synthetic test bundle"),
            runs_root=root / "data" / "runs",
            lock_path=root / "absent.lock",
            tools_root=root / "tools",
        )
        yield read_bundle(path)


def _json(args: list[str], code: int = 0) -> Any:
    result = runner.invoke(app, args)
    assert result.exit_code == code, result.output
    return json.loads(result.stdout)


def test_the_run_covers_the_kinds_and_statuses_it_claims(saved: RunBundle) -> None:
    kinds = {card.kind for card in saved.cards}
    assert kinds == {"interpretation", "polygenic", "computed", "impossibility"}
    assert {"matched", "not_run", "not_determinable"} <= {card.status for card in saved.cards}
    assert any(card.multi_marker is not None for card in saved.cards)
    assert any(card.carrier is not None for card in saved.cards)


def test_every_read_matches_the_schema_and_names_itself(
    saved: RunBundle, agent_schema_check: Check
) -> None:
    run = saved.path.name
    sections = [arg for section in SECTION_ORDER for arg in ("--section", section.value)]
    assert agent_schema_check(_json(["runs", "list", "--json"])) == "runs.list"
    assert agent_schema_check(_json(["runs", "show", run, "--json"])) == "runs.show"
    assert agent_schema_check(_json(["runs", "show", run, *sections, "--json"])) == "runs.section"
    assert agent_schema_check(_json(["runs", "qc", run, "--json"])) == "runs.qc"
    for card in saved.cards:
        view = _json(["runs", "card", run, card.card_id, "--json"])
        assert agent_schema_check(view) == "runs.card", card.card_id


def test_every_card_s_evidence_matches_the_schema(
    full_pack: KnowledgePack, agent_schema_check: Check
) -> None:
    """All of the pack, HLA and guideline cards included: evidence needs no run."""
    from genetics.engine.declaration import declaration

    for card in full_pack.cards:
        document = contract.tagged("cards.evidence", declaration(card))
        assert agent_schema_check(document) == "cards.evidence", card.id
    printed = _json(["cards", "evidence", "wnt10a_hair_curl", "--json"])
    assert agent_schema_check(printed) == "cards.evidence"


def test_every_card_with_a_claim_carries_citations_an_agent_can_open(
    saved: RunBundle, full_pack: KnowledgePack
) -> None:
    from genetics.engine.declaration import declaration

    for card in full_pack.cards:
        cited = declaration(card)["citations"]
        if card.kind is CardKind.IMPOSSIBILITY:
            # AGENTS.md 7.6: an assay-limit card cites nothing.
            assert cited == [], card.id
            continue
        assert cited, card.id
        assert all(c["url"] for c in cited if c["type"] != "accession"), card.id
    for stored in saved.cards:
        if stored.kind != "impossibility":
            assert stored.citations, stored.card_id
    view = _json(["runs", "card", saved.path.name, "wnt10a_hair_curl", "--json"])
    assert len(view["current_context"]["citation_links"]) == len(view["card"]["citations"]) > 0


def test_a_schema_violation_is_caught(saved: RunBundle, agent_schema_check: Check) -> None:
    """The check is not vacuous: each of these documents is wrong in one way."""
    good = _json(["runs", "card", saved.path.name, "wnt10a_hair_curl", "--json"])
    agent_schema_check(good)

    def broken(change: Change) -> dict[str, Any]:
        document: dict[str, Any] = json.loads(json.dumps(good))
        change(document)
        return document

    for change in (
        lambda d: d["card"].pop("citations"),
        lambda d: d["card"].update(unlisted=1),
        lambda d: d["card"].update(section="health"),
        lambda d: d["card"]["citations"][0].pop("id"),
        lambda d: d["card"]["confidence"]["inputs"].update(unlisted=0.5),
        lambda d: d["current_context"].update(context="saved"),
        lambda d: d["current_context"].update(unlisted=[]),
        lambda d: d.update(unlisted=1),
        lambda d: d.pop("run_id"),
    ):
        with pytest.raises(AssertionError, match="does not match its schema"):
            agent_schema_check(broken(change))
    with pytest.raises(AssertionError):
        agent_schema_check(
            broken(lambda d: d["schema"].update(version=contract.AGENT_SCHEMA_VERSION + 1))
        )
    with pytest.raises(AssertionError):
        agent_schema_check(broken(lambda d: d.pop("schema")))


# ---------------------------------------------------------------------------
# The rules the schema states
# ---------------------------------------------------------------------------


def test_run_id_is_the_id_a_command_resolves_in_every_payload(saved: RunBundle) -> None:
    """A renamed bundle is the one case where the directory and the manifest disagree."""
    renamed = saved.path.with_name("renamed-run")
    shutil.copytree(saved.path, renamed)
    try:
        whole = _json(["runs", "show", "renamed-run", "--json"])
        assert whole["run_id"] == "renamed-run"
        assert whole["recorded_run_id"] == saved.run_id != "renamed-run"
        for args in (
            ["runs", "show", "renamed-run", "--section", "traits"],
            ["runs", "card", "renamed-run", "wnt10a_hair_curl"],
            ["runs", "qc", "renamed-run"],
            ["runs", "clinvar", "renamed-run"],
            ["runs", "secondary", "renamed-run"],
            ["runs", "imputation", "renamed-run"],
        ):
            assert _json([*args, "--json"])["run_id"] == "renamed-run", args
        listed = {row["run_id"] for row in _json(["runs", "list", "--json"])["runs"]}
        assert {"renamed-run", saved.path.name} <= listed
        assert "run renamed-run" in runner.invoke(app, ["runs", "show", "renamed-run"]).stdout
    finally:
        shutil.rmtree(renamed)


def test_what_the_engine_adds_at_read_time_is_under_current_context(saved: RunBundle) -> None:
    """Frozen and current are kept apart by key: envelope, saved record, ``current_context``."""
    run = saved.path.name
    whole = _json(["runs", "show", run, "--json"])
    assert "current_context" not in whole
    by_id = {card["card_id"]: card for card in whole["cards"]}

    section = _json(["runs", "show", run, "--section", "traits", "--json"])
    card = _json(["runs", "card", run, "wnt10a_hair_curl", "--json"])
    qc = _json(["runs", "qc", run, "--json"])
    assert card["card"] == by_id["wnt10a_hair_curl"]
    assert all(entry == by_id[entry["card_id"]] for entry in section["cards"])
    assert qc["qc"] == whole["qc"] and qc["provenance"] == whole["provenance"]
    for document in (section, card):
        assert document["current_context"]["context"] == "current"
    for document in (whole, section, card, qc):
        saved_keys = set(document) - ENVELOPE - {"current_context"}
        assert {"format_version", "created_at"} <= saved_keys
        assert document["format_version"] == BUNDLE_FORMAT_VERSION

    defs = contract.document()["$defs"]
    for name in RUN_SCOPED:
        assert set(defs[name]["required"]) >= ENVELOPE, name
    for name in ("runs.section", "runs.card"):
        context = defs[name]["properties"]["current_context"]
        assert context["properties"]["context"] == {"const": "current"}
        assert "context" in context["required"]


@pytest.mark.privacy
def test_the_schema_and_its_command_hold_no_genotype() -> None:
    assert find_genotypes(contract.SCHEMA_PATH.read_text(encoding="utf-8")) == []
    for args in (["schema"], ["schema", "--json"], ["schema", "runs.card"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0 and find_genotypes(result.stdout) == [], args


@pytest.mark.privacy
def test_the_payload_list_states_which_documents_hold_a_genotype(saved: RunBundle) -> None:
    """``scanned`` in the document is the scan each command runs, not a note beside it."""
    facts = {entry["name"]: entry for entry in contract.payloads()}
    assert {name for name, entry in facts.items() if entry["holds_genotype"]} == {
        "runs.show",
        "runs.section",
        "runs.card",
    }
    assert all(
        entry["scanned"] != entry["holds_genotype"]
        for entry in facts.values()
        if entry["name"] != "error"
    )
    run = saved.path.name
    held = json.dumps(_json(["runs", "card", run, "wnt10a_hair_curl", "--json"]))
    assert "observed_genotype" in held
    for args in (["runs", "list"], ["runs", "qc", run], ["cards", "evidence", "wnt10a_hair_curl"]):
        assert find_genotypes(runner.invoke(app, [*args, "--json"]).stdout) == [], args


# ---------------------------------------------------------------------------
# Errors and exit codes
# ---------------------------------------------------------------------------

MISSING_RUN = "20260101T000000Z-00000000"


@pytest.mark.parametrize(
    ("args", "kind", "code"),
    [
        (["runs", "show", MISSING_RUN], "not-found", 1),
        (["runs", "card", MISSING_RUN, "wnt10a_hair_curl"], "not-found", 1),
        (["runs", "qc", MISSING_RUN], "not-found", 1),
        (["runs", "clinvar", MISSING_RUN], "not-found", 1),
        (["runs", "secondary", MISSING_RUN], "not-found", 1),
        (["runs", "imputation", MISSING_RUN], "not-found", 1),
        (["pgx", "calls", MISSING_RUN], "not-found", 1),
        (["hla", "calls", MISSING_RUN], "not-found", 1),
        (["runs", "card", "{run}", "curly_hair"], "card-not-found", 1),
        (["cards", "evidence", "curly_hair"], "card-not-found", 1),
        (["runs", "show", "{run}", "--section", "health"], "unknown-section", 2),
        (["runs", "delete", "{run}"], "confirmation-required", 2),
        (["schema", "runs.cards"], "unknown-payload", 2),
    ],
)
def test_a_failure_is_one_error_document_with_a_stable_kind(
    saved: RunBundle, agent_schema_check: Check, args: list[str], kind: str, code: int
) -> None:
    """Exit 2 where the command line was wrong; exit 1 where it could not be carried out."""
    resolved = [arg.format(run=saved.path.name) for arg in args]
    document = _json([*resolved, "--json"], code=code)
    assert agent_schema_check(document) == "error"
    assert document["ok"] is False
    assert document["error"]["kind"] == kind
    assert document["error"]["message"].strip()
    assert saved.path.is_dir()


def test_a_failure_without_json_is_a_sentence_on_stderr(saved: RunBundle) -> None:
    result = runner.invoke(app, ["runs", "card", saved.path.name, "curly_hair"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "no card called 'curly_hair'" in result.stderr


def test_a_damaged_and_a_newer_run_are_told_apart(
    saved: RunBundle, agent_schema_check: Check
) -> None:
    cases: tuple[tuple[str, str, Change], ...] = (
        ("newer-run", "version", lambda m: m.update(format_version=BUNDLE_FORMAT_VERSION + 1)),
        ("damaged-run", "integrity", lambda m: m["files"].update(dict.fromkeys(m["files"], "0"))),
    )
    for name, kind, edit in cases:
        copy = saved.path.with_name(name)
        shutil.copytree(saved.path, copy)
        try:
            manifest = json.loads((copy / MANIFEST_NAME).read_text(encoding="utf-8"))
            edit(manifest)
            (copy / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
            for args in (
                ["runs", "show", name],
                ["runs", "qc", name],
                ["pgx", "calls", name],
                ["hla", "calls", name],
            ):
                document = _json([*args, "--json"], code=1)
                assert agent_schema_check(document) == "error"
                assert document["error"]["kind"] == kind, args
        finally:
            shutil.rmtree(copy)


def test_other_groups_print_the_same_error_document(
    tmp_path: Path, agent_schema_check: Check
) -> None:
    """``pgs`` and ``pgx`` printed ``error`` as a bare string before M13.2."""
    absent = str(tmp_path / "absent.txt")
    for args, kind, code in (
        (["pgs", "inspect", absent, "--metadata", str(tmp_path / "absent.json")], "pgs", 1),
        (["pgx", "inspect", "--reference", str(tmp_path / "absent.json")], "pgx", 1),
        (["cards", "evidence", "x", "--knowledge", str(tmp_path / "none")], "knowledge", 1),
    ):
        document = _json([*args, "--json"], code=code)
        assert agent_schema_check(document) == "error", args
        assert document["error"]["kind"] == kind, args


def _emitted_kinds() -> set[str]:
    """Every error kind a CLI module can print: each literal returned by an ``*error_kind``
    function, and each literal passed to ``refuse``.

    Read from the source because most kinds belong to failures that need a broken tool, a
    full disk or a damaged reference to reach. Found in the M13.2 review: version 1's pattern
    refused two of ``genetics run``'s kinds, and no test produced either failure.
    """
    import ast

    import genetics.cli

    kinds: set[str] = set()
    for path in Path(genetics.cli.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.endswith("error_kind"):
                # Every string a return can yield, `"a" if test else "b"` included.
                kinds.update(
                    leaf.value
                    for ret in ast.walk(node)
                    if isinstance(ret, ast.Return) and ret.value is not None
                    for leaf in ast.walk(ret.value)
                    if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str)
                )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute | ast.Name)
                and (getattr(node.func, "attr", None) or getattr(node.func, "id", None))
                in {"refuse", "_refuse"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                kinds.add(node.args[0].value)
    return kinds


def test_every_kind_a_command_can_print_matches_the_schema(agent_schema_check: Check) -> None:
    kinds = _emitted_kinds()
    # The harvest finds what it should, so an empty or partial set cannot pass vacuously.
    assert {"not-found", "card-not-found", "unknown-section", "pgs", "hla"} <= kinds
    assert {"run_parts", "frequency_reference", "structure", "config", "serve"} <= kinds
    for kind in sorted(kinds):
        assert agent_schema_check(contract.error_payload(kind, "A sentence.")) == "error", kind


def test_an_unlisted_payload_cannot_be_tagged() -> None:
    with pytest.raises(ValueError, match="not a payload"):
        contract.tagged("runs.cards", {})
    with pytest.raises(ValueError, match="already has"):
        contract.tagged("runs.qc", {"schema": 1})
    with pytest.raises(KeyError):
        contract.payload_schema("stored_card")


# ---------------------------------------------------------------------------
# genetics schema
# ---------------------------------------------------------------------------


def test_schema_lists_each_payload_with_its_command() -> None:
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert f"agent schema version {contract.AGENT_SCHEMA_VERSION}" in result.stdout
    for entry in contract.payloads():
        assert entry["name"] in result.stdout and entry["command"] in result.stdout


def test_schema_prints_the_document_and_each_payload_s_own() -> None:
    assert _json(["schema", "--json"]) == contract.document()
    for name in contract.payload_names():
        printed = _json(["schema", name])
        assert printed == contract.payload_schema(name)
        assert printed["$ref"] == f"#/$defs/{name}"
        Draft202012Validator.check_schema(printed)


def test_the_listed_commands_exist() -> None:
    for entry in contract.payloads():
        if entry["name"] == "error":
            continue
        words = [w for w in entry["command"].split()[1:] if not w.startswith(("<", "--"))]
        assert runner.invoke(app, [*words, "--help"]).exit_code == 0, entry["command"]


def test_the_schema_ships_inside_the_package() -> None:
    """Beside its module, so an installed wheel can print it (see tests/test_packaging.py)."""
    assert contract.SCHEMA_PATH.is_file()
    assert contract.SCHEMA_PATH.parent == Path(contract.__file__).parent
    raw = contract.SCHEMA_PATH.read_bytes()
    assert b"\r" not in raw and raw.isascii()
