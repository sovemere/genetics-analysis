"""The dashboard keeps one saved run open, for as long as the files on disk match it."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from genetics.ancestry.context import AncestryContext
from genetics.engine.cards import KnowledgePack
from genetics.qc.report import QCReport
from genetics.run import store
from genetics.run.bundle import QC_NAME, RunBundle, write_bundle
from genetics.web import WebConfig, create_app

LOCAL_BASE_URL = "http://127.0.0.1"
NO_ANCESTRY = AncestryContext.not_run("synthetic test bundle: no ancestry stage ran")
FIRST = "20260821T090000Z-aaaa1111"
SECOND = "20260822T090000Z-bbbb2222"


@pytest.fixture
def runs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GENETICS_DATA_DIR", str(tmp_path / "data"))
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def saved(
    runs_root: Path, sample_qc: QCReport, sample_pack: KnowledgePack, sample_cards: tuple[Any, ...]
) -> tuple[Path, Path]:
    def save(run_id: str) -> Path:
        return write_bundle(
            qc=sample_qc,
            cards=sample_cards,
            pack=sample_pack,
            ancestry=NO_ANCESTRY,
            runs_root=runs_root,
            run_id=run_id,
            lock_path=runs_root.parent / "absent.lock",
            tools_root=runs_root.parent / "tools",
        )

    return save(FIRST), save(SECOND)


@pytest.fixture
def client(runs_root: Path) -> Iterator[TestClient]:
    with TestClient(create_app(WebConfig(runs_root=runs_root)), base_url=LOCAL_BASE_URL) as running:
        yield running


@pytest.fixture
def opens(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The run id of every real open."""
    seen: list[str] = []
    real = store.load_run

    def spy(run_id: str, runs_root: Path | None = None, **kwargs: Any) -> RunBundle:
        seen.append(run_id)
        return real(run_id, runs_root, **kwargs)

    monkeypatch.setattr(store, "load_run", spy)
    return seen


def test_pages_share_one_opened_copy(
    client: TestClient, saved: tuple[Path, Path], opens: list[str]
) -> None:
    for _ in range(3):
        assert client.get(f"/runs/{FIRST}").status_code == 200
    assert opens == [FIRST]


def test_the_index_uses_the_copy_its_run_already_has(
    client: TestClient, saved: tuple[Path, Path], opens: list[str]
) -> None:
    """``/`` opens the newest readable run, and its pages must not open it again."""
    assert client.get("/").status_code == 200
    assert client.get(f"/runs/{SECOND}").status_code == 200
    assert opens == [SECOND]


def test_only_one_run_is_held(
    client: TestClient, saved: tuple[Path, Path], opens: list[str]
) -> None:
    client.get(f"/runs/{FIRST}")
    client.get(f"/runs/{SECOND}")
    client.get(f"/runs/{FIRST}")
    assert opens == [FIRST, SECOND, FIRST]


def test_the_held_copy_is_dropped_before_the_next_is_opened(
    client: TestClient, saved: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two imputed runs in memory together would be about 5 GB for nothing."""
    import gc
    import weakref

    held: list[weakref.ref[RunBundle]] = []
    alive_at_second_open: list[bool] = []
    real = store.load_run

    def spy(run_id: str, runs_root: Path | None = None, **kwargs: Any) -> RunBundle:
        if held:
            gc.collect()
            alive_at_second_open.append(held[0]() is not None)
        bundle = real(run_id, runs_root, **kwargs)
        if not held:
            held.append(weakref.ref(bundle))
        return bundle

    monkeypatch.setattr(store, "load_run", spy)
    client.get(f"/runs/{FIRST}")
    client.get(f"/runs/{SECOND}")
    assert alive_at_second_open == [False]


def test_changed_files_force_a_real_read_and_damage_is_reported(
    client: TestClient, saved: tuple[Path, Path], opens: list[str]
) -> None:
    first, _ = saved
    assert client.get(f"/runs/{FIRST}").status_code == 200

    target = first / QC_NAME
    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
    response = client.get(f"/runs/{FIRST}")

    assert response.status_code == 200
    assert "does not match the digest" in response.text
    assert opens == [FIRST, FIRST]


def test_a_deleted_run_stops_being_served(
    client: TestClient, saved: tuple[Path, Path], runs_root: Path
) -> None:
    assert client.get(f"/runs/{FIRST}").status_code == 200
    store.delete_run(FIRST, runs_root)
    assert "No run named" in client.get(f"/runs/{FIRST}").text


def test_pages_arriving_during_a_slow_open_wait_for_it(
    runs_root: Path, saved: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second open of an imputed run would double an hour's work and its memory."""
    seen: list[str] = []
    real = store.load_run
    started = threading.Event()

    def slow(run_id: str, root: Path | None = None, **kwargs: Any) -> RunBundle:
        seen.append(run_id)
        started.set()
        time.sleep(0.2)
        return real(run_id, root, **kwargs)

    monkeypatch.setattr(store, "load_run", slow)
    with TestClient(create_app(WebConfig(runs_root=runs_root)), base_url=LOCAL_BASE_URL) as running:
        results: list[int] = []

        def fetch() -> None:
            results.append(running.get(f"/runs/{FIRST}").status_code)

        threads = [threading.Thread(target=fetch) for _ in range(3)]
        threads[0].start()
        assert started.wait(5)
        for thread in threads[1:]:
            thread.start()
        for thread in threads:
            thread.join()

    assert results == [200, 200, 200]
    assert seen == [FIRST]


def test_the_healthz_route_does_not_open_a_run(
    client: TestClient, saved: tuple[Path, Path], opens: list[str]
) -> None:
    assert client.get("/healthz").status_code == 200
    assert opens == []
