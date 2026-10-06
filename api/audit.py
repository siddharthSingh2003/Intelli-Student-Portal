"""Audit store (M3): one record per /ask response, keyed by trace_id (R10)."""
from __future__ import annotations

import json
from typing import Optional

from data.db import get_conn, one


def save(record: dict) -> None:
    with get_conn() as c:
        c.execute("INSERT OR REPLACE INTO audit_log (trace_id, created_at, answer_type, record_json) "
                  "VALUES (?, ?, ?, ?)", (record["trace_id"], record["timestamp"], record["answer_type"],
                                          json.dumps(record)))


def get(trace_id: str) -> Optional[dict]:
    r = one("SELECT record_json FROM audit_log WHERE trace_id = ?", (trace_id,))
    return json.loads(r["record_json"]) if r else None
