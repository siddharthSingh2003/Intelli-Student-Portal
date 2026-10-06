"""Student-record tools (M2). Read-only, deterministic, scoped to ONE student_id
that the orchestrator injects from the X-Student-Id header - never from the LLM."""
from __future__ import annotations

from datetime import date
from typing import Optional

from data.db import one, rows
from data.validate import session_key


class ToolError(RuntimeError):
    pass


def student_row(student_id: str) -> dict:
    s = one("SELECT * FROM students WHERE student_id = ?", (student_id,))
    if not s:
        raise ToolError("STUDENT_NOT_FOUND")
    return s


def attendance_pct(attended: int, held: int) -> float:
    return round(attended * 100 / held, 2)


def get_student_profile(student_id: str, as_of: Optional[date] = None) -> dict:
    s = student_row(student_id)
    return {k: s[k] for k in ("programme", "batch_year", "current_semester", "cgpa", "active_backlogs")}


def get_attendance(student_id: str, as_of: Optional[date] = None, course_code: Optional[str] = None) -> dict:
    student_row(student_id)
    sql = ("SELECT a.course_code, c.course_name, a.classes_held, a.classes_attended FROM attendance a "
           "JOIN courses c ON c.course_code = a.course_code WHERE a.student_id = ?")
    params: tuple = (student_id,)
    if course_code:
        sql += " AND a.course_code = ?"
        params += (course_code,)
    data = [{**r, "attendance_pct": attendance_pct(r["classes_attended"], r["classes_held"])}
            for r in rows(sql + " ORDER BY a.course_code", params)]
    if course_code:
        return data[0] if data else {"result": "NO_RECORD", "course_code": course_code}
    return {"courses": data}


def latest_results(student_id: str, course_code: Optional[str] = None) -> list[dict]:
    sql = ("SELECT r.*, c.course_name FROM results r JOIN courses c ON c.course_code = r.course_code "
           "WHERE r.student_id = ?")
    params: tuple = (student_id,)
    if course_code:
        sql += " AND r.course_code = ?"
        params += (course_code,)
    latest: dict[str, dict] = {}
    for r in rows(sql, params):
        k = (session_key(r["exam_session"]), r["exam_type"] == "SUPPLEMENTARY")
        cur = latest.get(r["course_code"])
        if cur is None or k > (session_key(cur["exam_session"]), cur["exam_type"] == "SUPPLEMENTARY"):
            latest[r["course_code"]] = r
    return [latest[c] for c in sorted(latest)]


def get_results(student_id: str, as_of: Optional[date] = None, course_code: Optional[str] = None) -> dict:
    student_row(student_id)
    keep = ("course_code", "course_name", "exam_session", "exam_type", "internal_marks",
            "external_marks", "total_marks", "max_marks", "result")
    data = [{k: r[k] for k in keep} for r in latest_results(student_id, course_code)]
    if course_code:
        return data[0] if data else {"result": "NO_RECORD", "course_code": course_code}
    return {"courses": data}
