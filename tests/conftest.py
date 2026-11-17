"""Shared pytest setup: each test level's folder sets its marker."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
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


def _sync_threads() -> set[threading.Thread]:
    return {t for t in threading.enumerate() if t.name == "eventlog-sync" and t.is_alive()}


@pytest.fixture(autouse=True)
def no_eventlog_sync_thread_left_running() -> Iterator[None]:
    """Fail a test that leaves an EventLog sync thread running (QC-4 E3).

    A leftover sync thread keeps syncing during later tests (it broke the LOG-23
    sync-order test once). Only threads the test started count, so one leak fails
    one test, not every test after it.
    """
    before = _sync_threads()
    yield
    left = _sync_threads() - before
    for t in left:
        t.join(timeout=0.5)  # a thread may be finishing its last wait
    left = {t for t in left if t.is_alive()}
    if left:
        how = "stop the session (stop() and run()) or the EventLog (close() or stop_sync())"
        pytest.fail(f"{len(left)} EventLog sync thread(s) left running: {how}", pytrace=False)
