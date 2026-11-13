"""The session 142 example files (docs/examples/) stay valid as the specs change (DC-7)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from j1939logger import types

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "examples"
SESSION = EXAMPLES / "s000142_20261106T140211Z.jsonl"


def _records() -> list[dict[str, Any]]:
    lines = SESSION.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def test_LOG_5_example_session_142_hash_chain_verifies() -> None:
    # docs/log-format.md: SHA-256 of prev followed by the record without its
    # hash, compact JSON, keys in written order, non-ASCII as-is.
    prev = None
    for rec in _records():
        body = {k: v for k, v in rec.items() if k != "hash"}
        text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        assert list(rec)[-1] == "hash", rec["rec"]
        assert hashlib.sha256((rec["prev"] + text).encode("utf-8")).hexdigest() == rec["hash"]
        if prev is not None:
            assert rec["prev"] == prev, rec["rec"]
        prev = rec["hash"]


def test_LOG_5_example_retrieval_last_hash_is_the_chain_before_it() -> None:
    recs = _records()
    for i, rec in enumerate(recs):
        if rec["type"] == "retrieval":
            assert rec["last_hash"] == recs[i - 1]["hash"]


def test_IDN_6_example_values_use_the_requirements_enumerations() -> None:
    for rec in _records():
        assert rec["sev"] in types.SEVERITIES
        assert rec["clock_source"] in types.CLOCK_SOURCES
        if "category" in rec:
            assert rec["category"] in types.CATEGORIES
        if "classification_rule" in rec:
            assert rec["classification_rule"] in types.CLASSIFICATION_RULES
        if "end_reason" in rec:
            assert rec["end_reason"] in types.END_REASONS
        if "vin_status" in rec:
            assert rec["vin_status"] in types.VIN_STATUSES
        if "prev_session_end" in rec:
            assert rec["prev_session_end"] in types.PREV_SESSION_ENDS
        if rec["type"] == "identification":
            assert rec["make_source"] in types.MAKE_SOURCES
            assert rec["confidence"] in types.CONFIDENCES
            assert set(rec["id_source"]) <= set(types.ID_SOURCES)
            assert all(q["outcome"] in types.REQUEST_OUTCOMES for q in rec["requests"])


def test_TRN_13_example_inventory_approval_kinds_use_the_enumeration() -> None:
    inv = json.loads((EXAMPLES / "inv-v2.json").read_text(encoding="utf-8"))
    kinds: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("pgns_approved", "requests_approved"):
                kinds.extend(item["kind"] for item in node.get(key, []))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(inv)
    assert kinds, "no approved PGNs found in inv-v2.json"
    assert set(kinds) <= set(types.APPROVAL_KINDS)
