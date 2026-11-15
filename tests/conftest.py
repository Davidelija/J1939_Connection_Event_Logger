"""Shared pytest setup: each test level's folder sets its marker."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import settings

# Fixed seed in CI (test plan section 4); random seed elsewhere. The nightly job
# (.github/workflows/nightly.yml) sets HYPOTHESIS_PROFILE=nightly and passes a random
# --hypothesis-seed; a failing example it finds is saved in tests/malformed/regressions/.
settings.register_profile("ci", derandomize=True, print_blob=True)
settings.register_profile("nightly", derandomize=False, print_blob=True)
_profile = os.environ.get("HYPOTHESIS_PROFILE") or ("ci" if os.environ.get("CI") else None)
if _profile is not None:
    settings.load_profile(_profile)

ROOT = Path(__file__).resolve().parent.parent
_LEVELS = {"unit": "unit", "contract": "contract", "malformed": "malformed"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        parts = Path(str(item.fspath)).resolve().relative_to(ROOT / "tests").parts
        if parts and parts[0] in _LEVELS:
            item.add_marker(getattr(pytest.mark, _LEVELS[parts[0]]))
