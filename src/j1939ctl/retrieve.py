"""retrieve: copy a logger's files to the laptop and check the chain (DC-21; LAP-5, LAP-6, LAP-9).

* Files go to ``<folder>/<VIN>/`` (one folder per logger, named by VIN).
* A file already held with the same SHA-256 is skipped; a partial copy (a
  ``.part`` file left by a dropped link) is copied again. A session file whose
  held copy is a prefix of the logger's (the session grew) is replaced; any
  other same-name file with different content is kept under a ``.N`` suffix
  and reported, never skipped.
* The open session (the newest session file, without ``session_end``) is cut at
  its last complete line, so only complete records are kept.
* The chain is checked with ``tools/verify_chain.py`` against the last hash
  kept for this logger in ``.j1939ctl.json``; the folder's files are made
  read-only; the logger is told what was retrieved (``retrieved``).
* The diagnostic log is copied too (LOG-20); it rotates, so it is replaced.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from j1939ctl.transport import Transport

STATE_FILE = ".j1939ctl.json"


def chain_checker() -> ModuleType:
    """``tools/verify_chain.py``, the same checker the logger's CI uses."""
    loaded = sys.modules.get("verify_chain")
    if loaded is not None:
        return loaded
    path = Path(__file__).resolve().parents[2] / "tools" / "verify_chain.py"
    spec = importlib.util.spec_from_file_location("verify_chain", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the chain checker from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_chain"] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


@dataclass
class Result:
    folder: Path
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)  # (remote, kept as)
    chain_ok: bool = False
    in_progress: bool = False
    last_hash: Optional[str] = None
    problems: list[str] = field(default_factory=list)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _writable(path: Path) -> None:
    if path.exists():
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)


def _read_only(folder: Path) -> None:
    for p in folder.rglob("*"):
        if p.is_file() and p.name != STATE_FILE:
            os.chmod(p, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def _cut_to_complete_lines(path: Path) -> None:
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        _writable(path)
        path.write_bytes(data[: data.rfind(b"\n") + 1])  # LAP-9: complete records only


def _load_state(root: Path) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads((root / STATE_FILE).read_text("utf-8"))
        return data
    except (OSError, ValueError):
        return {}


def retrieve(transport: Transport, root: Path) -> tuple[Optional[Result], dict[str, Any]]:
    """Retrieve every new file; the result, or None with the refusal reply."""
    status, code = transport.call("status")
    if not status.get("ok"):
        return None, status
    vin = status["result"].get("vin") or "unknown-VIN"
    listing, code = transport.call("retrieve_list")
    if not listing.get("ok"):
        return None, listing
    folder = root / str(vin)
    folder.mkdir(parents=True, exist_ok=True)
    state = _load_state(root)
    mine = state.setdefault(str(vin), {})
    result = Result(folder)
    files = listing["result"]["files"]
    sessions = sorted(f["path"] for f in files if f["path"].startswith("sessions/"))
    newest = sessions[-1] if sessions else None
    for f in files:
        remote, sha = f["path"], f["sha256"]
        local = folder / remote
        local.parent.mkdir(parents=True, exist_ok=True)
        part = local.with_name(local.name + ".part")
        if local.exists() and _sha(local) == sha:
            result.skipped.append(remote)
            continue
        if part.exists():
            part.unlink()  # a partial copy from a dropped link: copy again (LAP-6)
        try:
            transport.fetch(remote, part)
        except OSError as exc:
            result.problems.append(f"{remote}: {exc}")
            continue
        target = local
        if local.exists():
            held, got = local.read_bytes(), part.read_bytes()
            grew = remote.startswith("sessions/") and got.startswith(held)
            if not grew and not remote.startswith("diag/"):
                n = 1
                while local.with_name(f"{local.name}.{n}").exists():
                    n += 1
                target = local.with_name(f"{local.name}.{n}")
                result.renamed.append((remote, str(target.relative_to(folder))))
            _writable(local)
        os.replace(part, target)
        if remote == newest:
            _cut_to_complete_lines(target)
        result.copied.append(remote)
    checker = chain_checker()
    paths = sorted((folder / "sessions").glob("*.jsonl")) if (folder / "sessions").is_dir() else []
    report = checker.verify(paths, None)
    result.chain_ok = bool(report.ok)
    result.last_hash = report.last_hash
    result.in_progress = any("in progress" in n.message for n in report.notes)
    result.problems += [f"{p.file} line {p.line}: {p.message}" for p in report.problems]
    previous = mine.get("last_hash")
    if previous and result.chain_ok and paths:
        known = _hashes(paths)
        if previous not in known:
            result.chain_ok = False
            result.problems.append(
                "the last hash kept from the previous retrieval is not in the chain"
            )
    for name in ("inventory_show", "config_show"):  # for inventory show and report offline (LAP-12)
        reply, _ = transport.call(name)
        doc = (reply.get("result") or {}).get(name.split("_", 1)[0]) if reply.get("ok") else None
        if isinstance(doc, dict):
            kind = name.split("_", 1)[0]
            target = folder / kind / f"{doc.get(kind, kind)}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            _writable(target)
            target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    _read_only(folder)
    mine["last_hash"] = result.last_hash
    (root / STATE_FILE).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    transport.call("retrieved", {"files": result.copied + result.skipped,
                                 "chain": result.chain_ok,
                                 "last_hash": result.last_hash})  # fmt: skip
    return result, {"proto": 1, "ok": True}


def _hashes(paths: list[Path]) -> set[str]:
    out = set()
    for p in paths:
        for line in p.read_text("utf-8").splitlines():
            try:
                out.add(json.loads(line)["hash"])
            except (ValueError, KeyError, TypeError):
                continue
    return out
