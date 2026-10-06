"""Validation script (M2): schema + logical constraints for the Annex C tables.

    python -m data.validate --dir data/generated [--generated]

Checks: required columns, ID formats, ranges, attended <= held, marks in range,
total = internal + external, result consistent with marks, foreign keys,
course/programme consistency, reserved judge IDs. Exit code 1 on any error.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data.edge_cases import PASS_PCT

REQUIRED = {
    "students": ["student_id", "full_name", "programme", "batch_year", "current_semester", "cgpa", "active_backlogs"],
    "courses": ["course_code", "course_name", "programme", "semester", "credits"],
    "attendance": ["student_id", "course_code", "classes_held", "classes_attended"],
    "results": ["student_id", "course_code", "exam_session", "exam_type", "internal_marks",
                "external_marks", "total_marks", "max_marks", "result"],
}
SID_RE = re.compile(r"^S\d{4}$")
BACKLOG_RESULTS = {"FAIL", "ABSENT", "DETAINED"}


@dataclass
class Violation:
    table: str
    key: str
    rule: str
    message: str
    severity: str = "error"


def _num(row: dict, col: str, cast=int):
    try:
        return cast(str(row[col]).strip())
    except (ValueError, TypeError, KeyError):
        return None


def session_key(s: str) -> tuple[int, int]:
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    m = re.match(r"(\d{4})-([A-Z]{3})", str(s).upper())
    return (int(m.group(1)), months.index(m.group(2)) + 1) if m and m.group(2) in months else (0, 0)


def validate_tables(t: dict[str, list[dict[str, Any]]], *, existing_students: dict | None = None,
                    existing_courses: dict | None = None, pass_pct: float = PASS_PCT,
                    generated: bool = False) -> list[Violation]:
    v: list[Violation] = []
    add = lambda *a, **k: v.append(Violation(*a, **k))  # noqa: E731
    existing_students = existing_students or {}
    existing_courses = existing_courses or {}

    for table, cols in REQUIRED.items():
        for i, row in enumerate(t.get(table, [])):
            missing = [c for c in cols if c not in row]
            if missing:
                add(table, f"row {i + 1}", "required_columns", f"missing columns {missing}")
    if any(x.rule == "required_columns" for x in v):
        return v

    # ---- students ----
    students = dict(existing_students)
    for s in t.get("students", []):
        sid = str(s["student_id"]).strip()
        if not SID_RE.match(sid):
            add("students", sid, "id_format", "student_id must be S followed by 4 digits")
        elif generated and 9000 <= int(sid[1:]) <= 9999:
            add("students", sid, "reserved_id", "S9000-S9999 are reserved for judges")
        if sid in students and sid not in existing_students:
            add("students", sid, "duplicate", "duplicate student_id")
        sem, cg, bl, by = _num(s, "current_semester"), _num(s, "cgpa", float), _num(s, "active_backlogs"), _num(s, "batch_year")
        if sem is None or not 1 <= sem <= 10:
            add("students", sid, "semester_range", "current_semester must be 1-10")
        if cg is None or not 0.0 <= cg <= 10.0:
            add("students", sid, "cgpa_range", "cgpa must be 0.00-10.00")
        if bl is None or bl < 0:
            add("students", sid, "backlogs_range", "active_backlogs must be >= 0")
        if by is None or not 1990 <= by <= 2100:
            add("students", sid, "batch_year", "batch_year must be a plausible admission year")
        if not str(s["programme"]).strip() or not str(s["full_name"]).strip():
            add("students", sid, "not_empty", "programme and full_name are required")
        students[sid] = s

    # ---- courses ----
    courses = dict(existing_courses)
    programmes = {str(s["programme"]) for s in students.values()}
    for c in t.get("courses", []):
        code = str(c["course_code"]).strip()
        if not code:
            add("courses", "?", "not_empty", "course_code is required")
        if generated and code.upper().startswith("JDG"):
            add("courses", code, "reserved_code", "JDG* course codes are reserved for judges")
        if programmes and c["programme"] not in programmes:
            add("courses", code, "programme_match", f"programme '{c['programme']}' has no students", "warning")
        if (_num(c, "credits") or 0) <= 0:
            add("courses", code, "credits", "credits must be > 0")
        courses[code] = c

    # ---- attendance ----
    seen = Counter()
    for a in t.get("attendance", []):
        key = f"{a['student_id']}/{a['course_code']}"
        seen[key] += 1
        if a["student_id"] not in students:
            add("attendance", key, "fk_student", "unknown student_id")
        if a["course_code"] not in courses:
            add("attendance", key, "fk_course", "unknown course_code")
        held, att = _num(a, "classes_held"), _num(a, "classes_attended")
        if held is None or held <= 0:
            add("attendance", key, "held_positive", "classes_held must be > 0")
        if att is None or att < 0 or (held is not None and att > held):
            add("attendance", key, "attended_le_held", "0 <= classes_attended <= classes_held")
        s, c = students.get(a["student_id"]), courses.get(a["course_code"])
        if s and c and s["programme"] != c["programme"]:
            add("attendance", key, "programme_match", "course belongs to another programme", "warning")
    for key, n in seen.items():
        if n > 1:
            add("attendance", key, "duplicate_pk", "duplicate (student_id, course_code)")

    # ---- results ----
    latest: dict[tuple, dict] = {}
    for r in t.get("results", []):
        key = f"{r['student_id']}/{r['course_code']}/{r['exam_session']}/{r['exam_type']}"
        if r["student_id"] not in students:
            add("results", key, "fk_student", "unknown student_id")
        if r["course_code"] not in courses:
            add("results", key, "fk_course", "unknown course_code")
        if r["exam_type"] not in ("REGULAR", "SUPPLEMENTARY"):
            add("results", key, "exam_type", "exam_type must be REGULAR or SUPPLEMENTARY")
        if r["result"] not in ("PASS", "FAIL", "ABSENT", "DETAINED"):
            add("results", key, "result_enum", "result must be PASS, FAIL, ABSENT or DETAINED")
        i, e, tot, mx = (_num(r, k) for k in ("internal_marks", "external_marks", "total_marks", "max_marks"))
        if None in (i, e, tot, mx):
            add("results", key, "marks_type", "marks must be integers")
            continue
        if i < 0 or e < 0 or mx <= 0 or tot > mx:
            add("results", key, "marks_range", "marks must be >= 0 and total <= max_marks")
        if tot != i + e:
            add("results", key, "total_eq_sum", f"total_marks {tot} != internal {i} + external {e}")
        passed = tot >= pass_pct * mx / 100
        if r["result"] == "PASS" and not passed:
            add("results", key, "result_consistent", f"PASS but total {tot} < pass mark {pass_pct}%")
        if r["result"] == "FAIL" and passed:
            add("results", key, "result_consistent", f"FAIL but total {tot} >= pass mark {pass_pct}%")
        if r["result"] == "ABSENT" and e != 0:
            add("results", key, "result_consistent", "ABSENT must have external_marks = 0")
        k = (r["student_id"], r["course_code"])
        if k not in latest or (session_key(r["exam_session"]), r["exam_type"] == "SUPPLEMENTARY") > \
                (session_key(latest[k]["exam_session"]), latest[k]["exam_type"] == "SUPPLEMENTARY"):
            latest[k] = r

    # cross-table: active_backlogs should match latest failing results (warning: older backlogs may exist)
    if t.get("results"):
        fails = Counter(sid for (sid, _), r in latest.items() if r["result"] in BACKLOG_RESULTS)
        for sid, s in students.items():
            if sid in existing_students:
                continue
            bl = _num(s, "active_backlogs")
            if bl is not None and bl != fails.get(sid, 0):
                add("students", sid, "backlog_consistency",
                    f"active_backlogs={bl} but {fails.get(sid, 0)} course(s) currently FAIL/ABSENT/DETAINED", "warning")
    return v


def read_dir(path: str | Path) -> dict[str, list[dict]]:
    out = {}
    for table in REQUIRED:
        f = Path(path) / f"{table}.csv"
        if f.exists():
            with f.open(newline="", encoding="utf-8") as fh:
                out[table] = [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(fh)]
    return out


def format_report(viol: list[Violation], tables: dict) -> str:
    counts = {k: len(v) for k, v in tables.items()}
    errors = [x for x in viol if x.severity == "error"]
    warns = [x for x in viol if x.severity == "warning"]
    lines = ["VALIDATION REPORT", f"rows: {counts}", f"errors: {len(errors)}  warnings: {len(warns)}", ""]
    for x in errors + warns:
        lines.append(f"[{x.severity.upper()}] {x.table}:{x.key} {x.rule} - {x.message}")
    if not viol:
        lines.append("All checks passed.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="data/generated")
    ap.add_argument("--generated", action="store_true", help="also enforce reserved judge IDs/codes")
    ap.add_argument("--pass-pct", type=float, default=PASS_PCT)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    tables = read_dir(a.dir)
    viol = validate_tables(tables, pass_pct=a.pass_pct, generated=a.generated)
    report = format_report(viol, tables)
    print(report)
    Path(a.report or Path(a.dir) / "validation_report.txt").write_text(report + "\n")
    return 1 if any(x.severity == "error" for x in viol) else 0


if __name__ == "__main__":
    sys.exit(main())
