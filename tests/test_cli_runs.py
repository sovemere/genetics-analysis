"""CLI contract for ``genetics runs`` (roadmap M4.2).

The store is addressed through ``GENETICS_DATA_DIR`` rather than a ``--runs-root`` flag.
That is the point being tested as much as a convenience: a test-only way to name the store
would be a second name for one thing, and these tests would then be exercising a path no
user takes. Every command below resolves its root exactly as a user's would.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from genetics.cli.main import app
from genetics.engine.cards import KnowledgePack
from genetics.engine.evidence import AssembledCard
from genetics.paths import runs_dir
from genetics.privacy import GenotypeLeakError
from genetics.qc.report import QCReport
from genetics.run.bundle import BUNDLE_FORMAT_VERSION, INCOMING_PREFIX, MANIFEST_NAME, write_bundle

runner = CliRunner()


@pytest.fixture
def store_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    root = runs_dir()
    root.mkdir(parents=True)
    return root


@pytest.fixture
def saved(
    store_root: Path,
    sample_qc: QCReport,
    sample_pack: KnowledgePack,
    sample_cards: tuple[AssembledCard, ...],
) -> Path:
    return write_bundle(
        qc=sample_qc,
        cards=sample_cards,
        pack=sample_pack,
        runs_root=store_root,
        run_id="20260817T101112Z-ab12cd34",
        created_at=datetime(2026, 8, 17, 10, 11, 12, tzinfo=UTC),
        lock_path=store_root / "absent.lock",
        tools_root=store_root / "tools",
    )


def _edit_manifest(directory: Path, **changes: object) -> None:
    path = directory / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(changes)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_json_reports_a_saved_run(saved: Path) -> None:
    result = runner.invoke(app, ["runs", "list", "--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.stdout)
    assert payload["verified"] is False
    (run,) = payload["runs"]
    assert run["run_id"] == saved.name
    assert run["status"] == "readable"
    assert run["card_count"] == 1
    assert run["vendor"] == "ancestrydna_v2"


def test_an_empty_store_lists_cleanly_rather_than_failing(store_root: Path) -> None:
    result = runner.invoke(app, ["runs", "list"])
    assert result.exit_code == 0
    assert "none saved yet" in result.output


def test_list_reports_a_damaged_bundle_without_failing(saved: Path) -> None:
    """Exit 0 with a red row, not exit 1 with nothing.

    This is the command someone runs when something is already wrong; refusing to render
    would hide every intact run alongside the broken one.
    """
    (saved / MANIFEST_NAME).write_bytes(b"\xff\xfe\x00not json\x00")

    result = runner.invoke(app, ["runs", "list"])
    assert result.exit_code == 0, result.output
    assert "damaged" in result.output
    assert saved.name in result.output
    assert "1 of 1 run(s) could not be read" in result.output


def test_verify_is_what_turns_an_edited_payload_into_a_finding(saved: Path) -> None:
    """``readable`` is a claim about the manifest. ``--verify`` is a claim about the bytes."""
    payload_path = saved / "cards.run.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["cards"][0]["title"] = "Edited after the fact"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    fast = json.loads(runner.invoke(app, ["runs", "list", "--json"]).stdout)
    assert fast["runs"][0]["status"] == "readable"

    checked = json.loads(runner.invoke(app, ["runs", "list", "--json", "--verify"]).stdout)
    assert checked["verified"] is True
    assert checked["runs"][0]["status"] == "damaged"


def test_list_names_interrupted_saves_and_the_command_that_clears_them(store_root: Path) -> None:
    staging = store_root / f"{INCOMING_PREFIX}20260817T090000Z-cafe1234"
    staging.mkdir()
    (staging / "qc.run.json").write_text("x" * 2048, encoding="utf-8")

    result = runner.invoke(app, ["runs", "list"])
    assert result.exit_code == 0
    assert "1 interrupted save(s)" in result.output
    assert "genetics runs prune" in result.output


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_json_carries_the_card_its_confidence_and_its_citations(saved: Path) -> None:
    """The v1 definition of done, item 6: an agent reviews a run and checks its citations
    from CLI output alone. M13 builds the per-card and per-section surface on top."""
    result = runner.invoke(app, ["runs", "show", saved.name, "--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.stdout)
    assert payload["run_id"] == saved.name
    assert payload["format_version"] == BUNDLE_FORMAT_VERSION
    (card,) = payload["cards"]
    assert card["card_id"] == "synthetic_dominant_trait"
    assert card["confidence_tier"]
    assert card["confidence"]["inputs"]["population_allele_frequency"] == 0.20
    assert [c["id"] for c in card["citations"]] == ["10.1038/s41586-000-00000-0", "12345678"]


def test_show_puts_the_confidence_tier_on_every_line(saved: Path) -> None:
    result = runner.invoke(app, ["runs", "show", saved.name])
    assert result.exit_code == 0, result.output
    assert f"run {saved.name}" in result.output
    assert "synthetic_dominant_trait" in result.output
    assert "1 card(s)" in result.output


def test_show_of_a_newer_format_fails_as_a_version_error(saved: Path) -> None:
    """M4.2's acceptance, on the surface where a person actually meets it.

    "Written by a newer engine" and "this file is damaged" have completely different
    remedies, so the JSON says which one it is rather than leaving an agent to parse prose.
    """
    _edit_manifest(saved, format_version=BUNDLE_FORMAT_VERSION + 1)

    result = runner.invoke(app, ["runs", "show", saved.name, "--json"])
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    error = json.loads(result.stdout)["error"]
    assert error["kind"] == "version"
    assert "Use the version of the tool that wrote it" in error["message"]


def test_show_of_a_corrupt_bundle_is_damage_rather_than_a_version_problem(saved: Path) -> None:
    (saved / "qc.run.json").write_text("edited", encoding="utf-8")

    result = runner.invoke(app, ["runs", "show", saved.name, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["kind"] == "integrity"


def test_show_of_an_unknown_run_says_so(store_root: Path) -> None:
    result = runner.invoke(app, ["runs", "show", "nope", "--json"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["kind"] == "not-found"
    assert "genetics runs list" in error["message"]


# ---------------------------------------------------------------------------
# delete / prune
# ---------------------------------------------------------------------------


def test_delete_asks_first_and_leaves_the_run_when_declined(saved: Path) -> None:
    """There is no undo and no trash, so a declined prompt has to mean nothing happened."""
    result = runner.invoke(app, ["runs", "delete", saved.name], input="n\n")
    assert result.exit_code == 1
    assert saved.is_dir(), "declining deleted it anyway"


def test_delete_removes_the_run_when_confirmed(saved: Path) -> None:
    result = runner.invoke(app, ["runs", "delete", saved.name], input="y\n")
    assert result.exit_code == 0, result.output
    assert not saved.exists()
    assert "none saved yet" in runner.invoke(app, ["runs", "list"]).output


def test_delete_with_json_requires_an_explicit_yes(saved: Path) -> None:
    """``--json`` has nobody to answer a prompt. Requiring ``--yes`` rather than assuming it
    means a non-interactive caller that meant to delete says so, and one that did not gets
    an error instead of a deletion."""
    result = runner.invoke(app, ["runs", "delete", saved.name, "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["kind"] == "confirmation-required"
    assert saved.is_dir()

    confirmed = runner.invoke(app, ["runs", "delete", saved.name, "--json", "--yes"])
    assert confirmed.exit_code == 0, confirmed.output
    assert json.loads(confirmed.stdout)["ok"] is True
    assert not saved.exists()


def test_delete_refuses_a_directory_that_is_not_a_bundle(store_root: Path) -> None:
    intruder = store_root / "my-notes"
    intruder.mkdir()
    (intruder / "important.txt").write_text("not a bundle", encoding="utf-8")

    result = runner.invoke(app, ["runs", "delete", "my-notes", "--json", "--yes"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["kind"] == "bundle"
    assert (intruder / "important.txt").is_file()


def test_prune_clears_interrupted_saves(store_root: Path, saved: Path) -> None:
    staging = store_root / f"{INCOMING_PREFIX}abandoned"
    staging.mkdir()
    (staging / "cards.run.json").write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["runs", "prune", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    assert [item["run_id"] for item in json.loads(result.stdout)["removed"]] == ["abandoned"]
    assert not staging.exists()
    assert saved.is_dir(), "a saved run is not an interrupted one"


def test_prune_with_nothing_to_do_says_so(store_root: Path) -> None:
    result = runner.invoke(app, ["runs", "prune", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["removed"] == []


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
@pytest.mark.parametrize("args", [["runs", "list"], ["runs", "list", "--json"]])
def test_both_list_branches_refuse_to_emit_a_genotype(
    store_root: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """A negative assertion passes when it is broken, so the guard is driven with input it
    must reject -- on *both* branches.

    M1.8 is the precedent and the warning: the first cut of ``genetics ingest`` scanned the
    JSON branch and left the human render open, which is the branch a person is more likely
    to edit. Parametrised so removing either call fails a test.
    """
    from genetics.run import store
    from genetics.run.store import RunListing, RunStatus, RunSummary

    dirty = "\t".join(("rs4988235", "2", "136608646", "A", "G"))
    poisoned = RunListing(
        root=store_root,
        runs=(
            RunSummary(
                run_id="20260817T101112Z-ab12cd34",
                path=store_root / "x",
                status=RunStatus.READABLE,
                vendor=dirty,
            ),
        ),
        incomplete=(),
        verified=False,
    )
    monkeypatch.setattr(store, "list_runs", lambda *a, **k: poisoned)

    result = runner.invoke(app, args)
    assert isinstance(result.exception, GenotypeLeakError)
    assert dirty not in result.output


@pytest.mark.privacy
def test_show_deliberately_does_render_the_reader_s_own_genotype(
    saved: Path, sample_genotype: str
) -> None:
    """The other half of the split, asserted so it cannot be "fixed" by accident.

    A card's summary states what your genotype is -- that is the product. Scanning this
    output would be a guard that fails on correct output, and M0.3 settled what happens to
    those. The bundle's own writer draws the same line: it scans the manifest and the QC
    report, and not ``cards.run.json``.
    """
    result = runner.invoke(app, ["runs", "show", saved.name, "--json"])
    assert result.exit_code == 0
    assert sample_genotype in json.loads(result.stdout)["cards"][0]["match"]["observed_genotype"]


def test_the_runs_group_is_registered() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "runs" in result.stdout
