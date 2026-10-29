from __future__ import annotations

import pytest

from src.ui_state import can_start_analysis


@pytest.mark.parametrize(
    ("configured", "has_document", "running", "expected"),
    [
        (True, True, False, True),
        (False, True, False, False),
        (True, False, False, False),
        (True, True, True, False),
    ],
)
def test_can_start_analysis(configured, has_document, running, expected):
    assert (
        can_start_analysis(configured=configured, has_document=has_document, running=running)
        is expected
    )
