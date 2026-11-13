"""Import rules that import-linter cannot check before each module exists.

docs/modules.md section 2: nothing imports ``main``; every module sits in a
layer. Test plan section 2 and X22: ``src/`` imports python-can only in
``platform/``. These scan every module in ``src/`` as it lands.
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "src" / "j1939logger"

# docs/modules.md section 2, plus the shared types.
LAYERED = {
    "main", "j1939cmd",
    "session", "admin",
    "detect", "monitor", "identify", "address", "requests", "inventory", "retention", "status",
    "decode", "config",
    "capture", "transmit", "eventlog", "store", "rawcap", "clock",
    "platform",
    "types",
}  # fmt: skip


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found |= {f"{node.module}.{a.name}" for a in node.names}
    return found


def _modules() -> list[Path]:
    return sorted(PKG.rglob("*.py"))


def test_SC_6_nothing_imports_main() -> None:
    for path in _modules():
        bad = {
            m
            for m in _imports(path)
            if m == "j1939logger.main" or m.startswith("j1939logger.main.")
        }
        assert not bad, f"{path.relative_to(PKG)} imports main"


def test_SC_6_python_can_only_inside_platform() -> None:
    for path in _modules():
        if "platform" in path.relative_to(PKG).parts[:1]:
            continue
        bad = {m for m in _imports(path) if m == "can" or m.startswith("can.")}
        assert not bad, f"{path.relative_to(PKG)} imports python-can outside platform/"


def test_SC_6_every_module_sits_in_a_layer() -> None:
    top = {p.stem if p.is_file() else p.name for p in PKG.iterdir()}
    top -= {"__init__", "__pycache__", "data"}
    assert top <= LAYERED, f"modules with no layer in docs/modules.md section 2: {top - LAYERED}"
