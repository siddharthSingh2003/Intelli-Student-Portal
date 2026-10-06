"""Student-data loader library (M2). Used by scripts/load_students.py and POST /admin/load-students.

Validates first (against what is already in the DB, so judges can load only their
own students/courses), then upserts in one transaction - all or nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from data import credentials
from data.db import get_conn, rows
from data.validate import format_report, read_dir, validate_tables

INT_COLS = {"batch_year", "current_semester", "active_backlogs", "semester", "credits", "classes_held",
            "classes_attended", "internal_marks", "external_marks", "total_marks", "max_marks"}
FLOAT_COLS = {"cgpa"}
ORDER = ["students", "courses", "attendance", "results"]


class LoadError(ValueError):
    def __init__(self, report: str):
        super().__init__(report)
        self.report = report


def _coerce(row: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in row.items():
        if k in INT_COLS:
            out[k] = int(str(v).strip())
        elif k in FLOAT_COLS:
            out[k] = float(str(v).strip())
        else:
            out[k] = str(v).strip()
    return out


def load_tables(tables: dict[str, list[dict]], generated: bool = False) -> dict[str, Any]:
    existing_students = {r["student_id"]: r for r in rows("SELECT * FROM students")}
    existing_courses = {r["course_code"]: r for r in rows("SELECT * FROM courses")}
    for s in tables.get("students", []):        # rows being replaced are re-validated
        existing_students.pop(s.get("student_id"), None)
    viol = validate_tables(tables, existing_students=existing_students,
                           existing_courses=existing_courses, generated=generated)
    report = format_report(viol, tables)
    if any(x.severity == "error" for x in viol):
        raise LoadError(report)
    counts = {}
    with get_conn() as c:
        for table in ORDER:
            data = [_coerce(r) for r in tables.get(table, [])]
            if not data:
                continue
            cols = list(data[0].keys())
            c.executemany(
                f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [tuple(r[k] for k in cols) for r in data])
            counts[table] = len(data)
    return {"loaded": counts, "warnings": sum(x.severity == "warning" for x in viol), "report": report}


def load_dir(path: str | Path, generated: bool = False) -> dict[str, Any]:
    tables = read_dir(path)
    if not tables:
        raise LoadError(f"No Annex C CSV files (students/courses/attendance/results.csv) found in {path}")
    res = load_tables(tables, generated=generated)
    # credentials.csv is optional: students without a row get the initial password
    res["credentials"] = {"loaded": credentials.load_csv(Path(path) / "credentials.csv"),
                          "initialised": credentials.ensure_credentials()}
    return res
