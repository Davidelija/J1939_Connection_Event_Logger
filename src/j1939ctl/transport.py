"""How j1939ctl reaches the logger: ``ssh`` for commands, ``scp`` for files (DC-21).

``Transport`` is the seam the tests replace with a runner that calls
``j1939cmd`` directly.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional, Protocol

NOT_RUNNING = 3


class Transport(Protocol):
    def call(
        self, cmd: str, args: Optional[dict[str, Any]] = None, reason: Optional[str] = None
    ) -> tuple[dict[str, Any], int]:
        """Run one logger command; the reply and ``j1939cmd``'s exit code."""
        ...

    def fetch(self, remote: str, local: Path) -> None:
        """Copy one card file (``sessions/...``) to ``local``; OSError on failure."""
        ...


class SshTransport:
    """The Windows (or Linux) OpenSSH client, with the operator's own key (STS-5)."""

    def __init__(self, host: str, card: str, ssh: str = "ssh", scp: str = "scp") -> None:
        self.host = host
        self.card = card.rstrip("/")
        self._ssh = ssh
        self._scp = scp

    def call(
        self, cmd: str, args: Optional[dict[str, Any]] = None, reason: Optional[str] = None
    ) -> tuple[dict[str, Any], int]:
        line = json.dumps({"cmd": cmd, "args": args or {}, "reason": reason}) + "\n"
        try:
            done = subprocess.run(
                [self._ssh, "-o", "BatchMode=yes", self.host, "j1939cmd"],
                input=line, capture_output=True, text=True, timeout=120, check=False,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _no_link(str(exc)), NOT_RUNNING
        try:
            reply = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return _no_link(done.stderr.strip() or "no answer from the logger"), NOT_RUNNING
        return reply, done.returncode

    def fetch(self, remote: str, local: Path) -> None:
        done = subprocess.run(
            [self._scp, "-q", "-B", f"{self.host}:{self.card}/{remote}", str(local)],
            capture_output=True, text=True, timeout=600, check=False,
        )  # fmt: skip
        if done.returncode != 0:
            raise OSError(done.stderr.strip() or f"scp failed for {remote}")


def _no_link(detail: str) -> dict[str, Any]:
    return {
        "proto": 1,
        "ok": False,
        "error": f"cannot reach the logger ({detail})",
        "next": "check the Ethernet cable and that the laptop got an address from the logger",
    }
