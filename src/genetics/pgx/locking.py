"""Kernel locks for reference publication; abandoned processes hold no stale lock."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from genetics.filelock import exclusive_lock
from genetics.refs.postprocess import ProcessError, _inside


@contextmanager
def publication_lock(output: Path) -> Iterator[None]:
    output.parent.mkdir(parents=True, exist_ok=True)
    path = _inside(output.parent, f".{output.name}.lock", label="publication lock")
    with exclusive_lock(
        path, lambda: ProcessError("Another process is publishing this PGx reference.")
    ):
        yield
