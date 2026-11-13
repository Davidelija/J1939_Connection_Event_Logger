"""Service entry point (step 1 minimal form, DC-9).

Parses the command line, reads and validates the config and inventory files
(cfg-1 and inv-1, through ``config``), and runs a ``Session`` on the desktop
platform until interrupted. ``store`` loads these files once ``session`` is
complete (step 2 PR 2).

    python -m j1939logger.main --config cfg-v3.json [--inventory inv-v2.json]
        [--interface vcan0] [--root DIR]
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional

from j1939logger.config import Config, ConfigError, InventoryError, validate, validate_inventory
from j1939logger.detect import InventoryEntry
from j1939logger.platform.desktop import DesktopPlatform
from j1939logger.session import Session


def inventory_from_file(data: Any) -> dict[int, InventoryEntry]:
    """NAME -> entry ID and category from an inventory file, validated by ``config`` (inv-1)."""
    inv = validate_inventory(data)
    if isinstance(inv, InventoryError):
        raise ValueError(f"inventory rejected: {inv}")
    return {e.name: InventoryEntry(e.entry, e.category) for e in inv.entries if e.name is not None}


def config_from_file(data: Any) -> Config:
    """A validated config (cfg-1), or ValueError listing every problem (STS-19)."""
    cfg = validate(data)
    if isinstance(cfg, ConfigError):
        raise ValueError(f"config rejected: {cfg}")
    return cfg


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="j1939logger", description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--inventory", type=Path)
    ap.add_argument("--interface", default="vcan0")
    ap.add_argument("--root", type=Path, help="folder for card, flash and keys (desktop)")
    args = ap.parse_args(argv)

    try:
        cfg = config_from_file(json.loads(args.config.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"stopped: {exc}", file=sys.stderr)  # a corrupt config stops the logger (STS-19)
        return 2
    settings = dict(cfg.values)
    inventory = None
    if args.inventory is not None:
        inventory = inventory_from_file(json.loads(args.inventory.read_text(encoding="utf-8")))
    platform = DesktopPlatform(interface=args.interface, root=args.root)
    session = Session(platform, settings, inventory)
    signal.signal(signal.SIGINT, lambda *_: session.stop())
    signal.signal(signal.SIGTERM, lambda *_: session.stop())
    session.start()
    print(f"recording to {session.eventlog.path}", flush=True)
    error = session.run()
    if error is not None:
        print(f"stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
