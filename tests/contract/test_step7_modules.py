"""Public names of the step 7 modules (docs/modules.md section 4, frozen for step 7)."""

from __future__ import annotations

import j1939logger.admin as admin
import j1939logger.status as status
from j1939logger.session import Session


def test_SC_6_status_and_admin_public_names() -> None:
    assert {"State", "Status", "light", "contents"} <= set(status.__all__)
    assert {"reset_record", "RESTART_EXIT"} <= set(admin.__all__)
    assert admin.RESTART_EXIT == 75


def test_SC_6_session_answers_every_protocol_command() -> None:
    commands = {
        "status", "login", "logout", "train_start", "train_status", "train_finish",
        "train_confirm", "events", "approve", "remove", "clear", "config_show", "config_push",
        "inventory_show", "retrieve_list", "retrieved", "restart", "retrain",
    }  # fmt: skip
    assert all(hasattr(Session, f"_cmd_{c}") for c in commands)  # DC-21 item 1
