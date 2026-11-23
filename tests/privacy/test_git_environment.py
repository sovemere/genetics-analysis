"""The suite runs with none of the variables that point git at a particular repository.

Under ``git commit -a`` the pre-commit hook inherits ``GIT_INDEX_FILE`` for the commit's
temporary index, and the privacy tests that build scratch repositories then staged their
fake exports into the real commit (see ``GIT_LOCATION_VARIABLES`` in ``tests/conftest.py``).
Outside a hook this passes trivially; inside one it is the check that the clearing ran.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.privacy


def test_no_git_location_variable_reaches_the_suite(
    git_location_variables: tuple[str, ...],
) -> None:
    assert "GIT_INDEX_FILE" in git_location_variables
    assert [name for name in git_location_variables if name in os.environ] == []
