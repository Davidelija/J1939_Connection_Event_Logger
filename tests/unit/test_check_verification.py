"""tools/check_verification.py: the four cases DC-2 lists, plus parsing.

These tests check project tooling rather than a requirement, so they carry
the design-change ID that defines the check (DC-2) in place of a requirement
ID; see the step 1 pull request.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_verification", ROOT / "tools" / "check_verification.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look the module up while building Row
    spec.loader.exec_module(mod)
    return mod


cv = _load()

HEADER = """# Verification matrix

**Merged build steps:** {merged}. *(note)*

| ID | Method | Step | Test or procedure | Where | Result | Date | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
"""


def _row(
    req: str, method: str, step: str, test: str = "", where: str = "", result: str = ""
) -> str:
    return f"| {req} | {method} | {step} | {test} | {where} | {result} |  |  |\n"


def _run(tmp_path: Path, merged: str, rows: str, tests: str = "", mode: str = "staged") -> int:
    (tmp_path / "verification.md").write_text(HEADER.format(merged=merged) + rows, encoding="utf-8")
    tdir = tmp_path / "tests"
    tdir.mkdir(exist_ok=True)
    (tdir / "test_x.py").write_text(tests, encoding="utf-8")
    argv = ["--mode", mode, "--matrix", str(tmp_path / "verification.md"), "--tests", str(tdir)]
    argv += ["--errors", str(tmp_path / "errors.md")]
    return int(cv.main(argv))


def test_DC_2_t_requirement_of_unmerged_step_passes(tmp_path: Path) -> None:
    assert _run(tmp_path, "none", _row("DET-4", "T", "4")) == 0
    assert _run(tmp_path, "1, 2", _row("DET-4", "T", "4")) == 0


def test_DC_2_t_requirement_of_merged_step_without_test_fails(tmp_path: Path) -> None:
    assert _run(tmp_path, "1", _row("DET-1", "T", "1")) == 1
    # A named test that does not exist, or belongs to another requirement, does not count.
    assert _run(tmp_path, "1", _row("DET-1", "T", "1", "`test_DET_1_new_claim`")) == 1
    tests = "def test_DET_16_within_2_s():\n    pass\n"
    assert _run(tmp_path, "1", _row("DET-1", "T", "1", "test_DET_16_within_2_s"), tests) == 1
    # It passes once the named test exists.
    tests = "def test_DET_1_new_claim():\n    pass\n"
    assert _run(tmp_path, "1", _row("DET-1", "T", "1", "`test_DET_1_new_claim`"), tests) == 0
    assert _run(tmp_path, "1", _row("DET-1", "T", "1", "`test_DET_1_*`"), tests) == 0


def test_DC_2_step_8_requirement_with_bench_procedure_passes(tmp_path: Path) -> None:
    assert _run(tmp_path, "8", _row("HW-3", "T", "8", "bench/ B-HW3")) == 0
    assert _run(tmp_path, "8", _row("SC-9", "T", "8", "A4")) == 0
    assert _run(tmp_path, "8", _row("SC-9", "T", "8")) == 1
    # A bench ID does not stand in for a test before step 8.
    assert _run(tmp_path, "3", _row("NP-1", "T", "3", "A1")) == 1


def test_DC_2_release_mode_fails_on_an_empty_row(tmp_path: Path) -> None:
    (tmp_path / "errors.md").write_text("", encoding="utf-8")
    assert _run(tmp_path, "none", _row("DET-1", "T", "1"), mode="release") == 1
    tests = "def test_DET_1_new_claim():\n    pass\n"
    ok = _row("DET-1", "T", "1", "test_DET_1_new_claim", "vcan", "pass")
    assert _run(tmp_path, "none", ok, tests, mode="release") == 0
    gap = _row("HW-7", "T", "8", "A7", "not verified", "Beacon not available")
    assert _run(tmp_path, "none", gap, mode="release") == 0


def test_DC_2_release_mode_fails_on_errors_md_placeholder(tmp_path: Path) -> None:
    head = "| a | b | `can_missing` | d | e | f | g | h | NP-17 | {} |\n"
    (tmp_path / "errors.md").write_text(head.format("*(step 1)*"), encoding="utf-8")
    assert _run(tmp_path, "none", "", mode="release") == 1
    (tmp_path / "errors.md").write_text(head.format("test_NP_17_x"), encoding="utf-8")
    assert _run(tmp_path, "none", "", mode="release") == 0


def test_DC_2_deferred_and_non_t_rows_are_skipped(tmp_path: Path) -> None:
    rows = _row("SC-12", "T", "—", "Deferred, not built") + _row("SC-5", "D", "8")
    assert _run(tmp_path, "8", rows) == 0
    assert _run(tmp_path, "none", rows, mode="release") == 0


def test_DC_2_merged_line_is_required(tmp_path: Path) -> None:
    (tmp_path / "verification.md").write_text("| ID |\n", encoding="utf-8")
    with pytest.raises(ValueError):
        cv.main(["--matrix", str(tmp_path / "verification.md"), "--tests", str(tmp_path)])


def test_DC_2_repository_matrix_passes_staged_check() -> None:
    assert cv.main([]) == 0
