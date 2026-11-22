"""One exclusive, non-blocking file lock, owned by the kernel.

A process that dies releases it, which a PID sentinel file does not: an interrupted Beagle
job or reference publication leaves nothing stale behind. Beagle's job lock and the PGx
publication lock were two copies of this; a fix to one would have missed the other.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive_lock(path: Path, busy: Callable[[], Exception]) -> Iterator[None]:
    """Hold ``path`` locked for the block, or raise ``busy()`` at once if another holds it.

    The file is created with one byte when missing, since Windows locks a byte range and an
    empty file has none.
    """
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
            raise busy() from None
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
