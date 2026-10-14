"""Kernel locks for reference publication; abandoned processes hold no stale lock."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from genetics.refs.postprocess import ProcessError, _inside


@contextmanager
def publication_lock(output: Path) -> Iterator[None]:
    output.parent.mkdir(parents=True, exist_ok=True)
    path = _inside(output.parent, f".{output.name}.lock", label="publication lock")
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ProcessError("Another process is publishing this PGx reference.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
