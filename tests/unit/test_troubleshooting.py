"""tools/troubleshooting.py (DC-22): the manual's troubleshooting table, from docs/errors.md."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def tool() -> ModuleType:
    if "troubleshooting" in sys.modules:
        return sys.modules["troubleshooting"]
    spec = importlib.util.spec_from_file_location(
        "troubleshooting", ROOT / "tools" / "troubleshooting.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["troubleshooting"] = module
    spec.loader.exec_module(module)
    return module


def _row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


ERRORS = "\n".join([
    "# Error-handling table",
    "",
    _row("Source", "Error", "Kind", "Detection", "Action", "Record", "Light", "Transmit",
         "Requirements", "Test", "Operator"),
    _row(*["---"] * 11),
    _row("Storage", "Card nearly full", "`card_nearly_full`", "use", "Free raw captures",
         "`fault`", "Slow blink", "Continues", "LOG-11", "`test_x`", "Run `retrieve`."),
    _row("CAN transmit", "Breach", "`tx_breach`", "guard", "Drop the frame", "`fault`",
         "Fast blink", "Off for the session", "NP-9", "`test_y`", "Report it."),
    "",
])  # fmt: skip
MANUAL = (
    "# Manual\n\n### Troubleshooting\n\n"
    "<!-- troubleshooting:start -->\nold\n<!-- troubleshooting:end -->\n\nafter\n"
)


def test_DC_22_each_error_row_becomes_a_troubleshooting_row() -> None:
    lines = tool().table(ERRORS).splitlines()
    assert lines[0] == "| Light | What happened | What the logger does | What to do |"
    assert (
        lines[2]
        == "| Slow blink | Storage: Card nearly full | Free raw captures | Run `retrieve`. |"
    )
    breach = "| Fast blink | CAN transmit: Breach | Drop the frame. Transmit: off for the session."
    assert lines[3] == breach + " | Report it. |"


def test_DC_22_render_replaces_only_the_marked_section() -> None:
    out = tool().render(MANUAL, ERRORS)
    assert out.startswith("# Manual\n\n### Troubleshooting\n\n<!-- troubleshooting:start -->\n")
    assert "old" not in out and out.endswith("<!-- troubleshooting:end -->\n\nafter\n")
    assert tool().render(out, ERRORS) == out  # stable


def test_DC_22_a_row_without_operator_text_is_refused() -> None:
    bad = ERRORS.replace(" Report it. |", "  |")
    with pytest.raises(ValueError, match="no Operator text"):
        tool().table(bad)


def test_DC_22_check_fails_when_the_manual_is_out_of_date(tmp_path: Path) -> None:
    (tmp_path / "errors.md").write_text(ERRORS, "utf-8")
    (tmp_path / "manual.md").write_text(MANUAL, "utf-8")
    args = ["--errors", str(tmp_path / "errors.md"), "--manual", str(tmp_path / "manual.md")]
    assert tool().main([*args, "--check"]) == 1
    assert tool().main(args) == 0
    assert tool().main([*args, "--check"]) == 0


def test_DC_22_the_repository_manual_matches_docs_errors_md() -> None:
    manual = (ROOT / "docs" / "user-manual.md").read_text("utf-8")
    errors = (ROOT / "docs" / "errors.md").read_text("utf-8")
    assert tool().render(manual, errors) == manual
    assert len(tool().rows(errors)) == 23  # every error row has operator text
