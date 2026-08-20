"""CLI contract for ``genetics run`` (roadmap M4.0).

The store is addressed through ``GENETICS_DATA_DIR`` rather than a flag, and the run id is
generated rather than named, so these tests drive exactly the surface a user has (M4.2).

The privacy split is the subject of half this file. ``genetics run`` is scanned on both
output paths; ``genetics runs show`` is deliberately not. Both halves are asserted here and
in ``test_cli_runs.py``, so neither can be "fixed" by accident in one direction.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from genetics.cli.main import app
from genetics.paths import runs_dir
from genetics.privacy import GenotypeLeakError
from genetics.run.bundle import read_bundle
from genetics.testing.fixtures import FIXTURES, render_fixture

runner = CliRunner()

SYNTHETIC_CARDS = Path(__file__).parent / "fixtures" / "cards"
SYNTHETIC_DIR = Path(__file__).parent / "fixtures" / "synthetic"

# See tests/run/test_pipeline.py: the committed fixtures carry no spike-ins, so a matched
# card only exists against an export rendered with the pack's own markers.
SPIKED_GENOTYPE = "AG"
SPIKE_INS = {
    "rs900000001": (7, 12345678, "A", "G"),
    "rs900000002": (24, 2655180, "T", "T"),
}


@pytest.fixture
def store_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    root = runs_dir()
    root.mkdir(parents=True)
    return root


@pytest.fixture
def export(tmp_path: Path) -> Path:
    """An export whose calls land on a named outcome in the fixture pack."""
    base = next(spec for spec in FIXTURES if spec.name == "ancestry_v2_male.txt")
    path = tmp_path / "spiked.txt"
    path.write_text(
        render_fixture(replace(base, spike_ins=SPIKE_INS)), encoding="utf-8", newline="\n"
    )
    return path


def _run(export: Path, *args: str) -> Result:
    return runner.invoke(
        app, ["run", "--input", str(export), "--knowledge", str(SYNTHETIC_CARDS), *args]
    )


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_run_saves_a_bundle_the_store_then_lists(export: Path, store_root: Path) -> None:
    """One engine, two front-ends: what ``run`` writes is what ``runs list`` reports."""
    result = _run(export)
    assert result.exit_code == 0, result.output

    (saved,) = list(store_root.iterdir())
    assert saved.name in result.output

    listing = runner.invoke(app, ["runs", "list", "--json"])
    (row,) = json.loads(listing.stdout)["runs"]
    assert row["run_id"] == saved.name
    assert row["status"] == "readable"
    assert row["with_interpretation"] == 2


def test_json_reports_counts_and_where_the_run_went(export: Path, store_root: Path) -> None:
    result = _run(export, "--json")
    assert result.exit_code == 0, result.output

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["input"]["vendor"] == "ancestrydna_v2"
    assert Path(payload["path"]).name == payload["run_id"]
    assert payload["cards"]["with_interpretation"] == 2
    assert payload["cards"]["by_status"]["matched"] == 2


def test_every_status_is_reported_including_the_zeros(export: Path, store_root: Path) -> None:
    """ "Nothing was strand-ambiguous" must not read as "strand ambiguity is not checked"."""
    payload = json.loads(_run(export, "--json").stdout)
    by_status = payload["cards"]["by_status"]

    assert by_status["no_call"] == 0
    assert by_status["strand_ambiguous"] == 0
    assert sum(by_status.values()) == payload["cards"]["total"]

    text = _run(export).output
    assert "strand_ambiguous" in text


def test_a_run_with_no_interpretation_says_so_rather_than_looking_broken(
    store_root: Path,
) -> None:
    """The expected result against a committed fixture, and not an error.

    Every card is still reported with its reason. This is the state M4.5 has to render, so
    the command that produces it should not read like a failure.
    """
    result = runner.invoke(
        app,
        [
            "run",
            "--input",
            str(SYNTHETIC_DIR / "ancestry_v2_male.txt"),
            "--knowledge",
            str(SYNTHETIC_CARDS),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "No card produced an interpretation" in result.output
    assert "marker_absent" in result.output


def test_reruns_never_overwrite_a_saved_run(export: Path, store_root: Path) -> None:
    first = json.loads(_run(export, "--json").stdout)["run_id"]
    second = json.loads(_run(export, "--json").stdout)["run_id"]

    assert first != second
    assert len(list(store_root.iterdir())) == 2


def test_the_default_knowledge_pack_is_the_committed_one(export: Path, store_root: Path) -> None:
    """Without ``--knowledge`` the run uses ``knowledge/``, not the test fixtures.

    Checked against the bundle's own provenance digest rather than a card count: a count
    would still pass if the flag silently fell back to some third pack of the same size,
    and the digest is the field a reader of an old bundle uses to ask the same question.
    """
    from genetics.engine.cards import KnowledgePack, default_knowledge_dir
    from genetics.run.bundle import knowledge_provenance

    result = runner.invoke(app, ["run", "--input", str(export), "--json"])
    assert result.exit_code == 0, result.output

    (saved,) = list(store_root.iterdir())
    committed = knowledge_provenance(KnowledgePack.load(default_knowledge_dir()))
    fixtures = knowledge_provenance(KnowledgePack.load(SYNTHETIC_CARDS))

    recorded = read_bundle(saved).provenance["knowledge"]
    assert recorded["digest"] == committed["digest"]
    assert recorded["digest"] != fixtures["digest"]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_malformed_export_is_reported_as_an_ingest_failure(store_root: Path) -> None:
    """Which stage refused is the thing an agent branches on, so it survives into JSON."""
    result = runner.invoke(
        app,
        [
            "run",
            "--input",
            str(SYNTHETIC_DIR / "ancestry_v2_malformed_header.txt"),
            "--knowledge",
            str(SYNTHETIC_CARDS),
            "--json",
        ],
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "ingest"
    assert list(store_root.iterdir()) == [], "a failed run must not leave a bundle"


def test_a_wrong_build_export_is_refused_rather_than_analysed(store_root: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--input",
            str(SYNTHETIC_DIR / "ancestry_v2_wrong_build.txt"),
            "--knowledge",
            str(SYNTHETIC_CARDS),
            "--json",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["kind"] == "ingest"


def test_a_missing_knowledge_pack_is_reported_as_a_knowledge_failure(
    export: Path, tmp_path: Path, store_root: Path
) -> None:
    """Distinguished from a bad export: the user's next action is completely different."""
    result = runner.invoke(
        app,
        ["run", "--input", str(export), "--knowledge", str(tmp_path / "absent"), "--json"],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["kind"] == "knowledge"


def test_a_refusal_prints_a_sentence_rather_than_a_traceback(store_root: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--input",
            str(SYNTHETIC_DIR / "ancestry_v2_malformed_header.txt"),
            "--knowledge",
            str(SYNTHETIC_CARDS),
        ],
    )
    assert result.exit_code == 2
    assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


@pytest.mark.privacy
def test_run_never_prints_a_genotype_even_when_cards_matched(
    export: Path, store_root: Path
) -> None:
    """The card summaries state the reader's genotype; this command shows counts.

    Asserted against a run that *did* match, because a run where nothing matched would pass
    this test with the guard removed.
    """
    for args in ([], ["--json"]):
        result = _run(export, *args)
        assert result.exit_code == 0, result.output
        assert SPIKED_GENOTYPE not in result.output


@pytest.mark.privacy
def test_runs_show_deliberately_does_print_it(export: Path, store_root: Path) -> None:
    """The other half of the split. Without this, "no genotype anywhere" looks correct.

    A card's summary states what your genotype is -- that is the product, on your own
    machine, about your own data. The pair of tests is what stops either half being
    "corrected" into the other.
    """
    run_id = json.loads(_run(export, "--json").stdout)["run_id"]

    shown = runner.invoke(app, ["runs", "show", run_id, "--json"])
    assert shown.exit_code == 0, shown.output
    assert SPIKED_GENOTYPE in shown.stdout


@pytest.mark.privacy
@pytest.mark.parametrize("args", [[], ["--json"]], ids=["human", "json"])
def test_both_output_paths_are_scanned(
    export: Path, store_root: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """M1.8's lesson, parametrised so removing either call fails a test.

    The first cut of ``genetics ingest`` scanned the JSON branch and left the human render
    open -- the branch a person is *more* likely to edit. Poisoning the vendor string is the
    cheapest way in: it is echoed by both branches and by nothing else.
    """
    from genetics.run.pipeline import Analysis, analyse

    dirty = "\t".join(("rs4988235", "2", "136608646", "A", "G"))

    def poisoned(input_path: Path, *, knowledge_dir: Path | None = None) -> Analysis:
        real = analyse(input_path, knowledge_dir=knowledge_dir)
        return replace(real, source=replace(real.source, vendor=dirty))

    # Patched by name on the CLI module, which is where the command resolved it. Patching
    # ``pipeline.analyse`` instead would leave the reference already bound into ``run_cmd``
    # untouched, and this test would pass without exercising anything.
    monkeypatch.setattr("genetics.cli.run_cmd.analyse", poisoned)

    result = _run(export, *args)
    assert isinstance(result.exception, GenotypeLeakError)
    assert dirty not in result.output


def test_the_run_command_is_registered_and_is_not_the_runs_group() -> None:
    """``run`` and ``runs`` differ by one character and do opposite things.

    A substring check for "run" passes on the ``runs`` group alone, so the registration is
    asserted by invoking the command's own help.
    """
    listed = runner.invoke(app, ["--help"])
    assert listed.exit_code == 0
    assert "runs" in listed.stdout

    own = runner.invoke(app, ["run", "--help"])
    assert own.exit_code == 0
    assert "--input" in own.stdout
    assert "run bundle" in own.stdout
