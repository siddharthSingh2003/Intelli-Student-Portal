"""Eligibility + what-if tools (M2). All decisions are code over SQLite + rule_registry.

Every output carries the rule_id it used; `_applied_rules`, `_conflicts` and
`_assumptions` are lifted out by the orchestrator into the response/audit.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

from tools.rules import RuleResolution, applied, compare, get_rule
from tools.student_tools import attendance_pct, get_attendance, latest_results, student_row


def _rule_problem(res: RuleResolution) -> Optional[dict]:
    if res.unresolved:
        return {"result": "CONFLICT", "parameter": res.parameter,
                "candidates": [x for c in res.conflicts for x in c.overridden],
                "_conflicts": [c.model_dump() for c in res.conflicts]}
    if res.rule is None:
        return {"result": "RULE_NOT_FOUND", "parameter": res.parameter}
    return None


def classes_needed(attended: int, held: int, threshold: float) -> Optional[int]:
    """Smallest x with (attended + x) / (held + x) >= threshold%, attending every next class."""
    if threshold >= 100:
        return None
    return max(0, math.ceil((threshold * held - 100 * attended) / (100 - threshold)))


def check_exam_eligibility(student_id: str, as_of: date, course_code: str) -> dict:
    student = student_row(student_id)
    att = get_attendance(student_id, as_of, course_code)
    if att.get("result") == "NO_RECORD":
        return att
    res = get_rule("min_attendance_pct", as_of, student)
    if problem := _rule_problem(res):
        return problem
    rule = res.rule
    pct = att["classes_attended"] * 100 / att["classes_held"]
    ok = compare(pct, rule["operator"], rule["value"])
    out = {"result": "ELIGIBLE" if ok else "NOT_ELIGIBLE", "rule_id": rule["rule_id"], "course_code": course_code,
           "course_name": att["course_name"], "classes_held": att["classes_held"],
           "classes_attended": att["classes_attended"], "attendance_pct": attendance_pct(att["classes_attended"], att["classes_held"]),
           "required_pct": float(rule["value"])}
    rules_used = [applied(rule)]
    if not ok:
        out["classes_needed"] = classes_needed(att["classes_attended"], att["classes_held"], float(rule["value"]))
        cond = get_rule("condonation_min_attendance_pct", as_of, student)
        if cond.rule and compare(pct, cond.rule["operator"], cond.rule["value"]):
            out["result"] = "CONDONATION_POSSIBLE"
            rules_used.append(applied(cond.rule))
    out["_applied_rules"] = rules_used
    out["_conflicts"] = [c.model_dump() for c in res.conflicts]
    return out


def check_supplementary_eligibility(student_id: str, as_of: date, course_code: str) -> dict:
    student = student_row(student_id)
    latest = latest_results(student_id, course_code)
    if not latest:
        return {"result": "NO_RECORD", "course_code": course_code}
    r = latest[0]
    res = get_rule("supp_eligible_results", as_of, student)
    if problem := _rule_problem(res):
        return problem
    ok = compare(r["result"], res.rule["operator"], res.rule["value"])
    reason = (f"latest result is {r['result']}" if ok else
              "you have already passed this course" if r["result"] == "PASS" else
              f"a {r['result']} result is not in the eligible results ({res.rule['value'].replace(';', ', ')})")
    return {"result": "ELIGIBLE" if ok else "NOT_ELIGIBLE", "rule_id": res.rule["rule_id"],
            "course_code": course_code, "course_name": r["course_name"], "latest_result": r["result"],
            "exam_session": r["exam_session"], "total_marks": r["total_marks"], "max_marks": r["max_marks"],
            "reason": reason, "_applied_rules": [applied(res.rule)],
            "_conflicts": [c.model_dump() for c in res.conflicts]}


def check_placement_eligibility(student_id: str, as_of: date, assume_passed: Optional[list[str]] = None,
                                assume_cgpa: Optional[float] = None) -> dict:
    student = student_row(student_id)
    cgpa, backlogs, assumptions = float(student["cgpa"]), int(student["active_backlogs"]), []
    for code in assume_passed or []:
        latest = latest_results(student_id, code)
        state = latest[0]["result"] if latest else None
        if state in ("FAIL", "ABSENT"):
            assumptions.append(f"Assumes you pass {code} in the supplementary exam, reducing active backlogs "
                               f"from {backlogs} to {max(0, backlogs - 1)}.")
            backlogs = max(0, backlogs - 1)
        elif state == "DETAINED":
            assumptions.append(f"{code} is DETAINED; it cannot be cleared through the supplementary exam, "
                               "so the assumption was not applied.")
        else:
            assumptions.append(f"{code} is not currently a backlog, so passing it changes nothing.")
    if assume_passed:
        assumptions.append("Assumes your CGPA stays at its current value after the supplementary result.")
    if assume_cgpa is not None:
        assumptions.append(f"Assumes a CGPA of {assume_cgpa} instead of your current {cgpa}.")
        cgpa = float(assume_cgpa)

    cg, bl = get_rule("placement_min_cgpa", as_of, student), get_rule("placement_max_backlogs", as_of, student)
    for res in (cg, bl):
        if problem := _rule_problem(res):
            problem["_assumptions"] = assumptions
            return problem
    checks = [
        {"check": "cgpa", "actual": cgpa, "required": f"{cg.rule['operator']}{cg.rule['value']}",
         "passed": compare(cgpa, cg.rule["operator"], cg.rule["value"]), "rule_id": cg.rule["rule_id"]},
        {"check": "active_backlogs", "actual": backlogs, "required": f"{bl.rule['operator']}{bl.rule['value']}",
         "passed": compare(backlogs, bl.rule["operator"], bl.rule["value"]), "rule_id": bl.rule["rule_id"]},
    ]
    return {"result": "ELIGIBLE" if all(c["passed"] for c in checks) else "NOT_ELIGIBLE",
            "what_if": bool(assume_passed or assume_cgpa is not None), "checks": checks,
            "_applied_rules": [applied(cg.rule), applied(bl.rule)],
            "_conflicts": [c.model_dump() for c in cg.conflicts + bl.conflicts], "_assumptions": assumptions}


def project_attendance(student_id: str, as_of: date, course_code: str, future_classes: int,
                       attend_classes: int) -> dict:
    student = student_row(student_id)
    if attend_classes > future_classes or future_classes <= 0 or attend_classes < 0:
        return {"result": "INVALID_INPUT", "reason": "need 0 <= attend_classes <= future_classes and future_classes > 0"}
    att = get_attendance(student_id, as_of, course_code)
    if att.get("result") == "NO_RECORD":
        return att
    res = get_rule("min_attendance_pct", as_of, student)
    if problem := _rule_problem(res):
        return problem
    held, attended = att["classes_held"] + future_classes, att["classes_attended"] + attend_classes
    pct = attended * 100 / held
    ok = compare(pct, res.rule["operator"], res.rule["value"])
    return {"result": "PROJECTED_ELIGIBLE" if ok else "PROJECTED_NOT_ELIGIBLE", "rule_id": res.rule["rule_id"],
            "course_code": course_code, "current_pct": att["attendance_pct"], "projected_pct": round(pct, 2),
            "required_pct": float(res.rule["value"]), "_applied_rules": [applied(res.rule)],
            "_assumptions": [f"Assumes {future_classes} more classes are held and you attend {attend_classes}."],
            "_conflicts": [c.model_dump() for c in res.conflicts]}
