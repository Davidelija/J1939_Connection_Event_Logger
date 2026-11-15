"""Session files, settings and card helpers (part of ``session``, docs/modules.md section 4)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from j1939logger.identify import (
    Identification,
)
from j1939logger.requests import RequestOutcome
from j1939logger.types import Connection

__all__ = [
    "settings_from_config",
    "SessionFile",
    "session_files",
    "SW_VERSION",
    "card_files",
    "operator_key_fingerprints",
]

SW_VERSION = "0.0.0"
LOG_FORMAT = "log-1"
STATE_FORMAT = "state-1"
BITRATES = (250000, 500000)

# The config keys step 1 read directly (DC-9); kept for callers passing a nested cfg-1.
STEP1_KEYS = (
    ("can", "rx_buffer_bytes"),
    ("logging", "raw_before_s"),
    ("limits", "tp_sessions"),
    ("clock", "max_skew_min"),
    ("classify", "wake_window_s"),
)

_NAME = re.compile(r"^s(\d{6})_([0-9TZ]+|noclock)(?:_p(\d+))?\.jsonl$")


def settings_from_config(cfg: Mapping[str, Any]) -> dict[str, Any]:
    """Every ``section.key`` -> value from a nested cfg-1 config."""
    out: dict[str, Any] = {}
    for section, value in cfg.items():
        if isinstance(value, Mapping):
            for key, v in value.items():
                out[f"{section}.{key}"] = v
    for section, key in STEP1_KEYS:
        if f"{section}.{key}" not in out:
            raise ValueError(f"config is missing {section}.{key}")
    return out


@dataclass(frozen=True)
class SessionFile:
    path: Path
    session: int
    stamp: str
    part: int


def session_files(folder: Path) -> list[SessionFile]:
    """Session files in a folder, oldest first (by session number, then part)."""
    if not folder.is_dir():
        return []
    out = []
    for p in folder.iterdir():
        m = _NAME.match(p.name)
        if m:
            out.append(SessionFile(p, int(m.group(1)), m.group(2), int(m.group(3) or 1)))
    return sorted(out, key=lambda f: (f.session, f.part))


def _vin_text(value: Optional[bytes]) -> Optional[str]:
    if not value:
        return None
    text = value.split(b"*", 1)[0].decode("ascii", "replace").strip()
    return text or None


# session_end reason -> Connection end reason for the connections still open (DET-6).
CONNECTION_END_REASON = {
    "key-off, bus silent": "key-off",
    "service stopped": "software restart",
}


def _refused(error: str, next_step: str) -> dict[str, Any]:
    return {"proto": 1, "ok": False, "error": error, "next": next_step}


def operator_key_fingerprints(keys_dir: Path) -> list[str]:
    """``SHA256:...`` of each installed operator public key (``*.pub``), as ``ssh-keygen -l``."""
    out = []
    for p in sorted(keys_dir.glob("*.pub")) if keys_dir.is_dir() else []:
        try:
            parts = p.read_text(encoding="ascii").split()
            blob = base64.b64decode(parts[1], validate=True)
        except (OSError, ValueError, IndexError, binascii.Error):
            continue  # not a public key file
        digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii")
        out.append("SHA256:" + digest.rstrip("="))
    return sorted(out)


def card_files(card: Path) -> list[dict[str, Any]]:
    """Session files, raw captures and diagnostic files on the card, with size and SHA-256.

    ``j1939cmd`` answers ``retrieve_list`` with this even when the service is down (DC-21).
    """
    out = []
    for sub in ("sessions", "raw", "diag"):
        folder = card / sub
        if not folder.is_dir():
            continue
        for p in sorted(folder.iterdir()):
            if not p.is_file():
                continue
            digest, size = hashlib.sha256(), 0
            try:
                with open(p, "rb") as fh:  # in chunks: the Beacon has little RAM
                    for chunk in iter(lambda: fh.read(HASH_CHUNK), b""):
                        digest.update(chunk)
                        size += len(chunk)
            except OSError:
                continue
            out.append({"path": f"{sub}/{p.name}", "size": size, "sha256": digest.hexdigest()})
    return out


def _version_number(version: str) -> Optional[int]:
    m = re.match(r"^inv-v(\d+)$", version)
    return int(m.group(1)) if m else None


@dataclass
class _Ident:
    """What session keeps per connection for identify (step 5, DC-17)."""

    conn: Connection
    rule: str  # classification_rule at connection start
    outcomes: list[RequestOutcome] = field(default_factory=list)
    ident: Optional[Identification] = None


APPROVED = "external device (approved)"
CAN_LOST = ("can_missing", "can_down")
HASH_CHUNK = 1024 * 1024
CAN_RETRY_FIRST_S = 1.0
CAN_RETRY_MAX_S = 30.0
IDENTITY_REQUESTS = 3  # Component ID, Software ID, ECU ID (NP-13)
