"""Deterministic answer sentences for tool results (M3).

For calculated answers the verdict sentence is produced by code from the tool
output, so the LLM can never flip an eligibility decision or misquote a number.
The LLM only writes the plain-language explanation (and that is number-checked).
"""
from __future__ import annotations


def _n(v) -> str:
    return f"{float(v):g}"


def verdict(tool: str, o: dict) -> str:
    r = o.get("result")
    if r == "NO_RECORD":
        return f"I could not find a record for {o.get('course_code', 'that course')} for you."
    if r in ("ERROR", "INVALID_INPUT"):
        return f"The {tool} check could not be completed ({o.get('error') or o.get('reason')})."
    if tool == "get_attendance":
        if "courses" in o:
            return "Your attendance: " + "; ".join(
                f"{c['course_name']} ({c['course_code']}) {_n(c['attendance_pct'])}% "
                f"({c['classes_attended']}/{c['classes_held']})" for c in o["courses"]) + "."
        return (f"Your attendance in {o['course_name']} ({o['course_code']}) is {_n(o['attendance_pct'])}% "
                f"({o['classes_attended']} of {o['classes_held']} classes).")
    if tool == "get_results":
        rows = o["courses"] if "courses" in o else [o]
        return "Your latest results: " + "; ".join(
            f"{c['course_name']} ({c['course_code']}) {c['result']} with {c['total_marks']}/{c['max_marks']} "
            f"in {c['exam_session']} {c['exam_type'].lower()}" for c in rows) + "."
    if tool == "get_student_profile":
        return (f"Your CGPA is {_n(o['cgpa'])} with {o['active_backlogs']} active backlog(s); you are in semester "
                f"{o['current_semester']} of {o['programme']} (batch {o['batch_year']}).")
    if tool == "check_exam_eligibility":
        if r == "ELIGIBLE":
            return f"You are eligible to appear in the end-semester exam for {o['course_code']}."
        s = (f"You are not eligible to appear in the end-semester exam for {o['course_code']}: your attendance "
             f"is {_n(o['attendance_pct'])}%, below the required {_n(o['required_pct'])}%.")
        if r == "CONDONATION_POSSIBLE":
            s += " You fall within the condonation band, so you may apply for condonation."
        if o.get("classes_needed"):
            s += (f" Attending the next {o['classes_needed']} classes without absence would bring you to "
                  f"{_n(o['required_pct'])}%.")
        return s
    if tool == "check_supplementary_eligibility":
        if r == "ELIGIBLE":
            return (f"You are eligible for the supplementary exam in {o['course_code']} "
                    f"(your latest result is {o['latest_result']}).")
        return f"You are not eligible for the supplementary exam in {o['course_code']}: {o['reason']}."
    if tool == "check_placement_eligibility":
        lead = "Under the stated assumptions, you would be" if o.get("what_if") else "You are"
        failed = [c for c in o["checks"] if not c["passed"]]
        s = f"{lead} {'eligible' if r == 'ELIGIBLE' else 'not eligible'} for campus placement"
        if failed:
            s += ": " + "; ".join(f"{c['check'].replace('_', ' ')} is {_n(c['actual'])}, required "
                                  f"{c['required']}" for c in failed)
        return s + "."
    if tool == "project_attendance":
        ok = r == "PROJECTED_ELIGIBLE"
        return (f"If you do that, your attendance in {o['course_code']} would be {_n(o['projected_pct'])}% "
                f"({'meeting' if ok else 'below'} the required {_n(o['required_pct'])}%).")
    return f"{tool}: {r}"


def explain(tool_calls: list[dict], applied_rules: list[dict], citations: dict[str, str]) -> str:
    parts = []
    for rule in applied_rules:
        src = citations.get(rule["rule_id"], f"{rule['source_doc_id']} section {rule['source_section']}")
        parts.append(f"Rule {rule['rule_id']} ({src}) requires {rule['parameter']} {rule['value']}.")
    for tc in tool_calls:
        o = tc["output"]
        if tc["tool"] == "check_placement_eligibility" and "checks" in o:
            parts.append("Checks: " + "; ".join(
                f"{c['check'].replace('_', ' ')} {_n(c['actual'])} vs {c['required']} -> "
                f"{'met' if c['passed'] else 'not met'}" for c in o["checks"]) + ".")
    parts.append("The decision was computed by code from your records; it was not estimated by the language model.")
    return " ".join(parts)


def rule_conflict(tool_calls: list[dict]) -> str:
    params = sorted({tc["output"].get("parameter", "") for tc in tool_calls if tc["output"].get("result") == "CONFLICT"})
    return (f"The authorised sources give conflicting values for {', '.join(params)} and the precedence policy "
            "cannot decide between them, so I can't give a definitive result. Please contact the issuing office.")


def doc_conflict(a: dict, b: dict) -> str:
    return (f"The authorised sources conflict on this and the precedence policy cannot resolve it: "
            f"{a['title']} (section {a['section']}) and {b['title']} (section {b['section']}) give different "
            f"answers, with the same authority level and effective date. Please contact the issuing office "
            f"({a['issuer']}; {b['issuer']}).")
