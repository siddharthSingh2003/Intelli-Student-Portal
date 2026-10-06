"""Student login credentials (extra to Annex C). Passwords are stored as plain text.

Admins (who may add documents) live in admin_users; the first one is created from
ADMIN_USERNAME / ADMIN_PASSWORD. A student without a credentials row (for example one loaded from a judge's students.csv)
gets the initial password INITIAL_PASSWORD, by default `Pass@<student_id>`.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from data.db import get_conn, one, rows
from shared.config import settings

COLUMNS = ["student_id", "password"]


def initial_password(student_id: str) -> str:
    return settings.initial_password.format(student_id=student_id)


def get_password(student_id: str) -> Optional[str]:
    r = one("SELECT password FROM student_credentials WHERE student_id = ?", (student_id,))
    return r["password"] if r else None


def _upsert(pairs: list[tuple[str, str]]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_conn() as c:
        c.executemany("INSERT OR REPLACE INTO student_credentials (student_id, password, updated_at) "
                      "VALUES (?, ?, ?)", [(sid, pw, now) for sid, pw in pairs])


def set_password(student_id: str, password: str) -> None:
    _upsert([(student_id, password)])


def ensure_credentials() -> int:
    """Give every student without credentials the initial password. Returns how many were created."""
    missing = [r["student_id"] for r in rows(
        "SELECT student_id FROM students WHERE student_id NOT IN (SELECT student_id FROM student_credentials)")]
    _upsert([(sid, initial_password(sid)) for sid in missing])
    return len(missing)


def load_csv(path: str | Path) -> int:
    """Load credentials.csv (student_id, password). Rows for unknown students are skipped."""
    path = Path(path)
    if not path.exists():
        return 0
    known = {r["student_id"] for r in rows("SELECT student_id FROM students")}
    with path.open(newline="", encoding="utf-8") as fh:
        pairs = [(r["student_id"].strip(), r["password"]) for r in csv.DictReader(fh)]
    pairs = [(sid, pw) for sid, pw in pairs if sid in known and pw]
    _upsert(pairs)
    return len(pairs)


# --------------------------------------------------------------------------- admins
def get_admin_password(username: str) -> Optional[str]:
    r = one("SELECT password FROM admin_users WHERE username = ?", (username,))
    return r["password"] if r else None


def set_admin_password(username: str, password: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with get_conn() as c:
        c.execute("INSERT OR REPLACE INTO admin_users (username, password, updated_at) VALUES (?, ?, ?)",
                  (username, password, now))


def ensure_admin() -> bool:
    """Create the default admin if there is no admin at all. Returns True if one was created."""
    if one("SELECT 1 AS x FROM admin_users LIMIT 1"):
        return False
    set_admin_password(settings.admin_username, settings.admin_password)
    return True
