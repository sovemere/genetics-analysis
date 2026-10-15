"""Shared child termination for private external-tool jobs."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import TypeVar

_ProcessText = TypeVar("_ProcessText", str, bytes)


def stop(process: subprocess.Popen[_ProcessText]) -> None:
    """Reap a running child; on Windows terminate only this launcher's process tree."""
    if process.poll() is None:
        if sys.platform == "win32":
            with suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    [
                        str(Path(os.environ["SYSTEMROOT"]) / "System32" / "taskkill.exe"),
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            if process.poll() is not None:
                return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
