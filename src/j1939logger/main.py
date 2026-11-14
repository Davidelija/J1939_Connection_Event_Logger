"""Service entry point (DC-9, DC-21).

Loads the newest config and inventory saved on the card (validated by
``config``); on a card that has none, ``--config`` and ``--inventory`` seed it
(the first install, the demo and tests). Runs a ``Session`` on the desktop
platform, with the command socket when ``--socket`` is given (``cmdserver``,
STS-23), until interrupted. A corrupt config stops the logger (exit 2); a
corrupt inventory runs it untrained with a high fault (STS-19). An operator
``restart`` ends with exit code 75 so systemd starts it again (STS-11).

    python -m j1939logger.main [--config cfg-v3.json] [--inventory inv-v2.json]
        [--interface vcan0] [--root DIR] [--socket PATH]
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional

from j1939logger.cmdserver import CmdServer
from j1939logger.config import (
    Config,
    ConfigError,
    Inventory,
    InventoryError,
    validate,
    validate_inventory,
)
from j1939logger.platform.desktop import DesktopPlatform
from j1939logger.session import Session
from j1939logger.store import Store


def inventory_from_file(data: Any) -> Inventory:
    """The inventory, validated by ``config`` (inv-1); ValueError if it is corrupt."""
    inv = validate_inventory(data)
    if isinstance(inv, InventoryError):
        raise ValueError(f"inventory rejected: {inv}")
    return inv


def config_from_file(data: Any) -> Config:
    """A validated config (cfg-1), or ValueError listing every problem (STS-19)."""
    cfg = validate(data)
    if isinstance(cfg, ConfigError):
        raise ValueError(f"config rejected: {cfg}")
    return cfg


def _newest(store: Store, kind: str) -> Optional[Any]:
    versions = store.versions(kind)
    if not versions:
        return None
    raw = store.load(kind, versions[-1])
    if raw is None:
        raise ValueError(f"the newest {kind} could not be read")
    return json.loads(raw.decode("utf-8"))


def _seed(store: Store, kind: str, version: str, data: Any) -> None:
    """Save a seed file as the card's first version (never over an existing one)."""
    if not store.versions(kind):
        store.write_atomic(kind, version, (json.dumps(data, indent=2) + "\n").encode("utf-8"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="j1939logger", description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, help="seed config, used when the card has none")
    ap.add_argument("--inventory", type=Path, help="seed inventory, used when the card has none")
    ap.add_argument("--interface", default="vcan0")
    ap.add_argument("--root", type=Path, help="folder for card, flash and keys (desktop)")
    ap.add_argument("--socket", type=Path, help="command socket (cmdserver, STS-23)")
    args = ap.parse_args(argv)

    platform = DesktopPlatform(interface=args.interface, root=args.root)
    store = Store(platform)
    try:
        cfg_data = _newest(store, "config")
        if cfg_data is None:
            if args.config is None:
                raise ValueError("no config on the card and no --config given")
            cfg_data = json.loads(args.config.read_text(encoding="utf-8"))
        cfg = config_from_file(cfg_data)
        _seed(store, "config", cfg.version, cfg_data)
    except (OSError, ValueError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)  # a corrupt config stops the logger (STS-19)
        return 2
    settings = dict(cfg.values)
    inventory: Optional[Inventory] = None
    startup_faults = []
    try:
        inv_data = _newest(store, "inventory")
        if inv_data is None and args.inventory is not None:
            inv_data = json.loads(args.inventory.read_text(encoding="utf-8"))
        if inv_data is not None:
            inventory = inventory_from_file(inv_data)
            _seed(store, "inventory", inventory.version, inv_data)
    except (OSError, ValueError) as exc:
        # A corrupt inventory runs the logger untrained with a high fault (STS-19).
        startup_faults.append(f"inventory corrupt ({exc}); running untrained")
    versions = {
        "config": cfg.version,
        "inventory": inventory.version if inventory is not None else None,
        "library": None,
    }
    session = Session(platform, settings, inventory, versions, startup_faults)
    signal.signal(signal.SIGINT, lambda *_: session.stop())
    signal.signal(signal.SIGTERM, lambda *_: session.stop())
    server: Optional[CmdServer] = None
    try:
        session.start()
        if args.socket is not None:
            server = CmdServer(args.socket, session)
            try:
                server.start()
            except OSError as exc:
                session.diag.log("error", "cmdserver", f"socket not started: {exc}")
                server = None
        if session.eventlog is not None:
            print(f"recording to {session.eventlog.path}", flush=True)
        error = session.run()
    except Exception:  # top of the main thread: log, record the cause, exit non-zero
        session.diag.log("error", "main", traceback.format_exc().replace("\n", " | "))
        session.diag.restart_cause("software restart")
        return 1
    finally:
        if server is not None:
            server.stop()
    if error is not None:
        print(f"stopped: {error}", file=sys.stderr)
        return 1
    return session.exit_code


if __name__ == "__main__":
    sys.exit(main())
