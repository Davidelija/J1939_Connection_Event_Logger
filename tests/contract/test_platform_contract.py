"""Platform contract: Protocol conformance and the single list of fault kinds."""

from __future__ import annotations

import re
from pathlib import Path

from j1939logger.platform.desktop import DesktopPlatform, FakeClock
from j1939logger.platform.interface import FAULT_KINDS, Platform

ROOT = Path(__file__).resolve().parents[2]


def test_SC_6_desktop_platform_conforms_to_platform_protocol(tmp_path: Path) -> None:
    # mypy checks this assignment against the Protocol (docs/modules.md section 5,
    # contract tests); isinstance checks the method names at run time.
    platform: Platform = DesktopPlatform(fault_plan=[], clock=FakeClock(), root=tmp_path)
    assert isinstance(platform, Platform)


def test_SC_6_fault_kinds_match_errors_md_kind_column() -> None:
    kinds: list[str] = []
    for line in (ROOT / "docs" / "errors.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 10 and cells[2].startswith("`"):
            kinds += re.findall(r"`([a-z0-9_]+)`", cells[2])
    assert kinds, "no Kind column found in docs/errors.md"
    assert tuple(kinds) == FAULT_KINDS
