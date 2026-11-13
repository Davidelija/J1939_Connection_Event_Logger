"""Shared pytest setup: each test level's folder sets its marker."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import settings

# Fixed seed in CI (test plan section 4); random seed elsewhere.
settings.register_profile("ci", derandomize=True, print_blob=True)
if os.environ.get("CI"):
    settings.load_profile("ci")

ROOT = Path(__file__).resolve().parent.parent
_LEVELS = {"unit": "unit", "contract": "contract", "malformed": "malformed"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        parts = Path(str(item.fspath)).resolve().relative_to(ROOT / "tests").parts
        if parts and parts[0] in _LEVELS:
            item.add_marker(getattr(pytest.mark, _LEVELS[parts[0]]))
