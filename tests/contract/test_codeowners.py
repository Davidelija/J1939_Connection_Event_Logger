"""DC-25: every safety-critical path named in docs/modules.md section 2 is in CODEOWNERS."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNERS = {"@vaughan2017", "@Davidelija"}


def safety_critical_paths() -> list[str]:
    """The paths in the modules.md sentence, as repository paths with a leading slash."""
    text = (ROOT / "docs" / "modules.md").read_text(encoding="utf-8")
    [line] = [x for x in text.splitlines() if x.startswith("Safety-critical paths need a review")]
    out = []
    for name in re.findall(r"`([^`]+)`", line):
        if name == "src/j1939logger/":
            continue  # the sentence's note on how paths are given
        if not (name.endswith(".py") or name.endswith("/") or name.startswith(".github/")):
            continue
        rooted = name.startswith(("tests/", ".github/"))
        path = "/" + (name if rooted else "src/j1939logger/" + name)
        if path not in out:
            out.append(path)
    return out


def codeowners() -> dict[str, set[str]]:
    rules: dict[str, set[str]] = {}
    for line in (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts and not parts[0].startswith("#"):
            rules[parts[0]] = set(parts[1:])
    return rules


def test_DC_25_codeowners_covers_every_safety_critical_path() -> None:
    paths = safety_critical_paths()
    assert "/src/j1939logger/session/can.py" in paths and "/.github/CODEOWNERS" in paths
    rules = codeowners()
    missing = [p for p in paths if not OWNERS <= rules.get(p, set())]
    assert missing == [], f"not in .github/CODEOWNERS with both owners: {missing}"


def test_DC_25_every_safety_critical_path_exists() -> None:
    gone = [p for p in safety_critical_paths() if not (ROOT / p.lstrip("/")).exists()]
    assert gone == [], f"named in docs/modules.md section 2 but missing: {gone}"
