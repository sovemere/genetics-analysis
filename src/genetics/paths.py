"""Canonical locations for everything the app reads and writes.

Two reasons this is centralised rather than scattered:

1. **AGENTS.md 1.5** requires analysis output to default *outside* the repository, so a
   stray ``git add -A`` cannot reach it. That guarantee is only checkable if there is one
   list of the paths we write.
2. The privacy suite asserts that every writable path is either gitignored or explicitly
   allowlisted. ``APP_WRITE_PATHS`` is what it iterates.

Anything that writes to disk must resolve its destination through this module. If you add
a new output location, add it here in the same commit, or the privacy suite fails.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "genetics-analysis"

_DATA_DIR_ENV = "GENETICS_DATA_DIR"
"""Override the user-data root. Useful for tests and for putting large panels on
another drive."""


def repo_root() -> Path:
    """Directory containing this checkout."""
    return Path(__file__).resolve().parents[2]


def user_data_dir() -> Path:
    """Per-user application data, outside the repository.

    Runs live here rather than in the repo because a run bundle *is* genotype data
    (AGENTS.md 1.1), and the safest place for it is somewhere git will never see.
    """
    override = os.environ.get(_DATA_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")

    return (Path(base) / APP_NAME).resolve()


def runs_dir() -> Path:
    """Saved analysis runs. Genotype-derived; never inside the repo by default."""
    return user_data_dir() / "runs"


def cache_dir() -> Path:
    """Intermediate artifacts. Genotype-derived -- caches routinely hold raw calls."""
    return user_data_dir() / "cache"


def tools_dir() -> Path:
    """Third-party binaries fetched at setup (PLINK 2, Beagle)."""
    return user_data_dir() / "tools"


def references_dir() -> Path:
    """Downloaded reference databases.

    These stay inside the repo tree, gitignored, because they are keyed to the checkout
    and the committed manifest sits alongside them. Not personal data -- the concern here
    is size and licensing, not privacy (AGENTS.md 5.5).
    """
    return repo_root() / "data" / "references"


def reference_manifest() -> Path:
    """Committed. Pins source URL, version, checksum and licence per source."""
    return references_dir() / "manifest.yaml"


def reference_lock() -> Path:
    """Committed. Resolved licences, written by the fetcher."""
    return references_dir() / "manifest.lock"


# Every path the application may write to, and whether git must ignore it.
# The privacy suite iterates this; see tests/privacy/test_output_paths.py.
APP_WRITE_PATHS: tuple[tuple[str, Path, bool], ...] = (
    #  label,             path,               must be gitignored
    ("user_data_dir", user_data_dir(), True),
    ("runs_dir", runs_dir(), True),
    ("cache_dir", cache_dir(), True),
    ("tools_dir", tools_dir(), True),
    ("references_dir", references_dir(), True),
    ("reference_manifest", reference_manifest(), False),
    ("reference_lock", reference_lock(), False),
)


def is_inside_repo(path: Path) -> bool:
    """True if ``path`` lies within this checkout."""
    try:
        path.resolve().relative_to(repo_root())
    except ValueError:
        return False
    return True
