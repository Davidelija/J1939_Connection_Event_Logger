"""Service entry point (step 1 minimal form, DC-9).

Parses the command line, reads the config and inventory files (cfg-1 and
inv-1 JSON, without validation until the config and inventory modules land),
and runs a ``Session`` on the desktop platform until interrupted.

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

from j1939logger.detect import InventoryEntry
from j1939logger.platform.desktop import DesktopPlatform
from j1939logger.session import Session, settings_from_config


def inventory_from_file(data: dict[str, Any]) -> dict[int, InventoryEntry]:
    """NAME -> entry ID and category from an inv-1 inventory."""
    out = {}
    for e in data.get("entries", []):
        if e.get("name"):
            out[int(e["name"], 16)] = InventoryEntry(e["entry"], e["category"])
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="j1939logger", description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--inventory", type=Path)
    ap.add_argument("--interface", default="vcan0")
    ap.add_argument("--root", type=Path, help="folder for card, flash and keys (desktop)")
    args = ap.parse_args(argv)

    settings = settings_from_config(json.loads(args.config.read_text(encoding="utf-8")))
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
