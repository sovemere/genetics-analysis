#!/usr/bin/env python
"""Regenerate the synthetic test fixtures (roadmap M0.2).

Thin wrapper. The logic lives in ``genetics.testing.fixtures`` so that strict mypy and
ruff cover it and tests can import it directly.

    python scripts/make_fixtures.py            # write fixtures
    python scripts/make_fixtures.py --check    # verify without writing

Equivalent to ``genetics fixtures`` once the package is installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from genetics.cli.main import app

if __name__ == "__main__":
    sys.argv.insert(1, "fixtures")
    app()
