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


class UnsafeDataDirError(ValueError):
    """Raised when the configured data directory would place genotypes inside the repo."""


def user_data_dir() -> Path:
    """Per-user application data, outside the repository.

    Runs live here rather than in the repo because a run bundle *is* genotype data
    (AGENTS.md 1.1), and the safest place for it is somewhere git will never see.

    An override pointing inside the checkout is **rejected**, not honoured. Pointing a
    data directory at your project is an entirely reasonable-looking thing to do, and it
    silently defeats the 1.5 guarantee: ``.gitignore`` covers the specific paths we
    declare, so a run bundle under some arbitrary in-repo directory is only partly
    caught -- ``x.run.json`` matches a pattern, but ``run_001/cards.json`` does not.
    Failing loudly here is the difference between an error message and a published genome.
    """
    override = os.environ.get(_DATA_DIR_ENV)
    if override:
        resolved = Path(override).expanduser().resolve()
        if is_inside_repo(resolved):
            raise UnsafeDataDirError(
                f"{_DATA_DIR_ENV} points inside the repository ({resolved}). "
                "Analysis output is genotype data and must live outside the checkout "
                "(AGENTS.md 1.5). Choose a path elsewhere on disk."
            )
        return resolved

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


def tools_manifest() -> Path:
    """Committed. Pins each external tool's build, URL and checksum (roadmap M2.5).

    Lives beside ``data/`` rather than under ``data/references/`` because a tool is not
    reference data: it is installed to ``tools_dir()`` outside the repo, it is selected by
    platform, and it carries no availability tier. Keeping it separate also keeps it clear
    of the ``/data/references/**`` ignore rule, so it needs no allowlist exception.
    """
    return repo_root() / "data" / "tools.yaml"


def is_inside_repo(path: Path) -> bool:
    """True if ``path`` lies within this checkout."""
    try:
        path.resolve().relative_to(repo_root())
    except ValueError:
        return False
    return True


def app_write_paths() -> tuple[tuple[str, Path, bool], ...]:
    """Every path the application may write to, and whether git must ignore it.

    A function rather than a module constant: evaluated at import time it would freeze
    whatever ``GENETICS_DATA_DIR`` happened to hold then, and the privacy suite would go
    on checking a location the app no longer uses.

    The privacy suite iterates this; see tests/privacy/test_output_paths.py. A new output
    location that skips this registry is a location nothing verifies.
    """
    return (
        #  label,             path,               must be gitignored
        ("user_data_dir", user_data_dir(), True),
        ("runs_dir", runs_dir(), True),
        ("cache_dir", cache_dir(), True),
        ("tools_dir", tools_dir(), True),
        ("references_dir", references_dir(), True),
        ("reference_manifest", reference_manifest(), False),
        ("reference_lock", reference_lock(), False),
        ("tools_manifest", tools_manifest(), False),
    )
