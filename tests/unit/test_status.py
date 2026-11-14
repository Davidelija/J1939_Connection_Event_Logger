"""status (step 7 PR 1, DC-21): the light and the status file."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from j1939logger.platform.desktop import DesktopPlatform
from j1939logger.status import State, Status, contents, light

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
GOOD = State(state="recording", session=142, bitrate=250000, logger_sa=247, card_used_pct=3.1,
             clock_valid=True, clock_source="rtc", config="cfg-v3", inventory="inv-v2",
             library="lib-v1", vin_status="match")  # fmt: skip


@pytest.mark.parametrize(
    ("change", "pattern"),
    [
        ({}, "steady"),
        ({"state": "starting"}, "off"),
        ({"state": "detecting bit rate"}, "off"),
        ({"unreviewed_high": 2}, "slow"),
        ({"state": "needs training", "untrained": True}, "slow"),
        ({"state": "training"}, "slow"),
        ({"card_nearly_full": True}, "slow"),
        ({"fault": "storage error (enospc)"}, "fast"),
        ({"vin_status": "mismatch"}, "fast"),
        ({"transmit": "off: bus_off"}, "fast"),
        ({"restart_loop": True}, "fast"),
        ({"unreviewed_high": 1, "fault": "card full; raw captures stopped"}, "fast"),  # fast wins
    ],
)
def test_STS_1_light_priority_fast_over_slow_over_steady(
    change: dict[str, Any], pattern: str
) -> None:
    assert light(replace(GOOD, **change)) == pattern


def test_STS_3_status_file_has_the_example_fields() -> None:
    example = json.loads((EXAMPLES / "status.json").read_text("utf-8"))
    body = contents(replace(GOOD, retrieved=["s000139"], retrieved_partial=["s000142"]),
                    example["utc"])  # fmt: skip
    assert set(example) <= set(body)
    assert body["format"] == "status-1" and body["light"] == "steady"
    assert (body["transmit"], body["vin_status"]) == ("on", "match")  # DC-21


def test_STS_1_status_sets_the_light_on_change_and_writes_on_state_change(tmp_path: Path) -> None:
    p = DesktopPlatform(root=tmp_path)
    st = Status(p, {"logging.sync_interval_s": 2})
    first = st.update(GOOD, 100.0, "2026-11-06T14:00:00.000Z")
    assert first is not None and json.loads(first)["state"] == "recording"
    assert p.lights == ["steady"]
    assert st.update(GOOD, 100.1, None) is None  # nothing changed
    assert st.update(replace(GOOD, unreviewed_high=1), 100.5, None) is None  # within the interval
    later = st.update(replace(GOOD, unreviewed_high=1), 102.6, None)
    assert later is not None and json.loads(later)["unreviewed_high"] == 1
    assert p.lights == ["steady", "slow"]
    assert st.update(replace(GOOD, state="training"), 102.7, None) is not None  # state change
