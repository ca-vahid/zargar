"""The engine raises its own Windows priority at startup (2026-10-05 desktop-app contention freezes)."""
import sys

import pytest

from zargar.main import raise_process_priority


def test_unknown_level_is_ignored():
    assert raise_process_priority("turbo") == "unchanged"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows priority classes")
def test_normal_level_applies_on_windows():
    assert raise_process_priority("normal") == "normal"
