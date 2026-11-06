"""Reads skip a saved run's deep checks only for bytes and an engine that passed them."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from genetics.ancestry.context import AncestryContext
from genetics.engine.cards import KnowledgePack
from genetics.guard import has_forbidden_name
from genetics.paths import UnsafeDataDirError, run_checks_dir
from genetics.privacy import find_genotypes
from genetics.qc.report import QCReport
from genetics.run import checks, store
from genetics.run.bundle import (
    MANIFEST_NAME,
    QC_NAME,
    BundleError,
    BundleIntegrityError,
    _digest,
    read_bundle,
    write_bundle,
)
from genetics.run.store import RunStatus

NO_ANCESTRY = AncestryContext.not_run("synthetic test bundle: no ancestry stage ran")


@pytest.fixture
def runs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def saved(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack, sample_cards: tuple[Any, ...]
) -> Path:
    return write_bundle(
        qc=sample_qc,
        cards=sample_cards,
        pack=sample_pack,
        ancestry=NO_ANCESTRY,
        runs_root=runs_root,
        run_id="20260821T090000Z-aaaa1111",
        lock_path=runs_root.parent / "absent.lock",
        tools_root=runs_root.parent / "tools",
    )


@pytest.fixture
def deep_reads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One entry per read that ran the deep checks."""
    from genetics.run import bundle

    seen: list[int] = []
    real = bundle._check_polygenic

    def spy(*args: Any, **kwargs: Any) -> None:
        seen.append(1)
        real(*args, **kwargs)

    monkeypatch.setattr(bundle, "_check_polygenic", spy)
    return seen


def _record_path(saved: Path) -> Path:
    key = checks.key(saved)
    assert key is not None
    return run_checks_dir() / f"{key}.run.json"


def test_the_first_read_runs_the_deep_checks_and_later_reads_skip_them(
    saved: Path, runs_root: Path, deep_reads: list[int]
) -> None:
    first = store.load_run(saved.name, runs_root)
    assert len(deep_reads) == 1

    second = store.load_run(saved.name, runs_root)
    assert len(deep_reads) == 1, "the record should have spared the second read"
    assert second.cards == first.cards
    assert second.clinvar == first.clinvar
    assert second.pgx == first.pgx
    assert second.hla == first.hla


def test_skipping_the_checks_changes_nothing_a_reader_sees(saved: Path) -> None:
    deep, shallow = read_bundle(saved), read_bundle(saved, deep=False)
    assert shallow == deep


def test_all_four_expensive_checks_are_skipped(
    saved: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.run import bundle

    def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a skipped check ran")

    monkeypatch.setattr("genetics.imputation.snapshot.validate_snapshot", explode)
    monkeypatch.setattr(bundle, "_check_polygenic", explode)
    monkeypatch.setattr("genetics.health.clinvar.validate_lookup", explode)
    monkeypatch.setattr("genetics.pgx.calling.validate_execution", explode)
    assert read_bundle(saved, deep=False).run_id == saved.name
    with pytest.raises(AssertionError):
        read_bundle(saved)


def test_a_changed_engine_repeats_the_checks_once(
    saved: Path, runs_root: Path, deep_reads: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    store.load_run(saved.name, runs_root)
    monkeypatch.setattr(checks, "engine_sha256", lambda: "another engine")

    store.load_run(saved.name, runs_root)
    assert len(deep_reads) == 2

    store.load_run(saved.name, runs_root)
    assert len(deep_reads) == 2, "the repeat should have earned a new record"


def test_changed_bytes_are_refused_whatever_the_record_says(saved: Path, runs_root: Path) -> None:
    store.load_run(saved.name, runs_root)
    target = saved / QC_NAME
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(BundleIntegrityError):
        store.load_run(saved.name, runs_root)


def test_a_rewritten_manifest_has_no_record(
    saved: Path, runs_root: Path, deep_reads: list[int]
) -> None:
    """Editing a payload and its recorded digest together must not inherit the old verdict."""
    store.load_run(saved.name, runs_root)
    target = saved / QC_NAME
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    manifest = json.loads((saved / MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest["files"][QC_NAME] = _digest(target)
    (saved / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    store.load_run(saved.name, runs_root)
    assert len(deep_reads) == 2


@pytest.mark.parametrize("content", [b"{", b"\xff\xfe", b"[]", b'{"schema_version": 1}'])
def test_a_damaged_record_only_costs_a_repeat(
    saved: Path, runs_root: Path, deep_reads: list[int], content: bytes
) -> None:
    store.load_run(saved.name, runs_root)
    _record_path(saved).write_bytes(content)

    store.load_run(saved.name, runs_root)
    assert len(deep_reads) == 2

    store.load_run(saved.name, runs_root)
    assert len(deep_reads) == 2, "the repeat should have replaced the damaged record"


def test_a_record_that_cannot_be_written_does_not_fail_the_read(
    saved: Path, runs_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(checks, "run_checks_dir", lambda: blocker / "run-checks")
    assert store.load_run(saved.name, runs_root).run_id == saved.name
    assert not checks.passed(checks.key(saved))


def test_an_unusable_data_directory_does_not_fail_the_read(
    saved: Path, runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller naming its runs root never needed the data directory before this."""

    def refuse() -> Path:
        raise UnsafeDataDirError("inside the checkout")

    monkeypatch.setattr(checks, "run_checks_dir", refuse)
    assert store.load_run(saved.name, runs_root).run_id == saved.name
    checks.forget(checks.key(saved))


def test_verify_always_repeats_the_checks(
    saved: Path, runs_root: Path, deep_reads: list[int]
) -> None:
    store.load_run(saved.name, runs_root)
    listing = store.list_runs(runs_root, verify=True)
    assert len(deep_reads) == 2
    assert listing.runs[0].status is RunStatus.READABLE


def test_verify_earns_a_record(saved: Path, runs_root: Path, deep_reads: list[int]) -> None:
    assert not checks.passed(checks.key(saved))
    store.list_runs(runs_root, verify=True)
    assert checks.passed(checks.key(saved))

    store.load_run(saved.name, runs_root)
    assert len(deep_reads) == 1


def test_a_failed_verify_forgets_the_pass(
    saved: Path, runs_root: Path, deep_reads: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    from genetics.run import bundle

    store.load_run(saved.name, runs_root)
    assert checks.passed(checks.key(saved))

    def fail(*args: Any, **kwargs: Any) -> None:
        raise BundleError("a check now fails")

    monkeypatch.setattr(bundle, "_check_polygenic", fail)
    listing = store.list_runs(runs_root, verify=True)
    assert listing.runs[0].status is RunStatus.DAMAGED
    assert not checks.passed(checks.key(saved))


def test_deleting_a_run_deletes_its_record(saved: Path, runs_root: Path) -> None:
    store.load_run(saved.name, runs_root)
    record = _record_path(saved)
    assert record.is_file()

    store.delete_run(saved.name, runs_root)
    assert not record.exists()


def test_the_record_holds_digests_and_nothing_else(saved: Path, runs_root: Path) -> None:
    store.load_run(saved.name, runs_root)
    record = _record_path(saved)
    text = record.read_text(encoding="ascii")

    assert set(json.loads(text)) == {"schema_version", "manifest_sha256", "engine_sha256"}
    assert not find_genotypes(text)
    assert has_forbidden_name(record.name), "git must refuse a record copied into a checkout"
    assert record.parent == run_checks_dir()
    assert not list(record.parent.glob(".pending-*"))


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A file of an engine a test can edit. Clearing the cache stands in for a new process."""
    root = tmp_path / "engine"
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    module = root / "module.py"
    module.write_text("# one\n", encoding="utf-8")
    monkeypatch.setattr("genetics.__file__", str(root / "__init__.py"))
    checks.engine_sha256.cache_clear()
    yield module
    checks.engine_sha256.cache_clear()


def test_the_engine_digest_follows_the_source(source: Path) -> None:
    before = checks.engine_sha256()
    source.write_text("# two\n", encoding="utf-8")
    assert checks.engine_sha256() == before, "this process is still running the code it started"

    checks.engine_sha256.cache_clear()
    assert checks.engine_sha256() != before


def test_source_edited_during_the_checks_does_not_inherit_their_verdict(
    saved: Path, runs_root: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An hour-long check, a dashboard left up: the record names the code that ran them."""
    from genetics.run import bundle

    checks.engine_sha256()
    real = bundle._check_polygenic

    def edited_meanwhile(*args: Any, **kwargs: Any) -> None:
        source.write_text("# edited while the checks ran\n", encoding="utf-8")
        real(*args, **kwargs)

    monkeypatch.setattr(bundle, "_check_polygenic", edited_meanwhile)
    store.load_run(saved.name, runs_root)
    assert checks.passed(checks.key(saved)), "the code that ran them may still skip them"

    checks.engine_sha256.cache_clear()
    assert not checks.passed(checks.key(saved)), "the edited source never ran them"


def test_the_engine_is_read_before_any_check_can_start() -> None:
    spec = importlib.util.spec_from_file_location("a_fresh_checks", checks.__file__)
    assert spec is not None and spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh.engine_sha256.cache_info().currsize == 1


def test_source_that_cannot_be_read_only_costs_a_repeat(
    saved: Path, runs_root: Path, deep_reads: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    store.load_run(saved.name, runs_root)

    def locked() -> str:
        raise PermissionError("held by another program")

    monkeypatch.setattr(checks, "engine_sha256", locked)
    assert not checks.passed(checks.key(saved))
    assert store.load_run(saved.name, runs_root).run_id == saved.name
    assert len(deep_reads) == 2
