"""Planning helpers (M3).

The LLM proposes a plan; validate_plan() is the gate: unknown tools or arguments are
rejected, course codes must belong to the student, and the intent category is
recomputed from the tools so audit categories are consistent. rule_plan() is the
deterministic planner used when the LLM output is invalid, and as the MOCK planner.
"""
from __future__ import annotations

import re

from graph.courses import resolve_courses
from shared.llm import register_mock
from tools.registry import TOOLS

WHAT_IF = re.compile(r"\bif i (pass|clear|attend|get|write|take)\b", re.I)
ATTEND_NEXT = re.compile(r"attend (?:the )?(?:next |all )?(\d+)(?: (?:of|out of) (?:the )?(?:next )?(\d+))?", re.I)


def rule_plan(question: str, courses: list[dict]) -> dict:
    ql = question.lower()
    found = resolve_courses(question, courses)
    one = found[0] if len(found) == 1 else ""
    what_if = bool(WHAT_IF.search(ql))
    elig = re.search(r"eligib|allowed|permitted|can i (sit|appear|take|write)", ql)
    supp = re.search(r"supplementar|re-?exam|reappear", ql)
    tools = []
    if supp and (elig or what_if or "fail" in ql):
        tools.append({"name": "check_supplementary_eligibility", "args": {"course_code": one}})
    if "placement" in ql and (elig or what_if):
        args = {"assume_passed": found} if what_if and found else {}
        tools.append({"name": "check_placement_eligibility", "args": args})
    if not tools and (m := ATTEND_NEXT.search(ql)) and what_if:
        n_att = int(m.group(1))
        tools.append({"name": "project_attendance", "args": {"course_code": one, "attend_classes": n_att,
                                                             "future_classes": int(m.group(2) or n_att)}})
    if not tools and elig and re.search(r"exam|end.?sem|appear|\bsit\b", ql):
        tools.append({"name": "check_exam_eligibility", "args": {"course_code": one}})
    if not tools and "attendance" in ql:
        tools.append({"name": "get_attendance", "args": {"course_code": one} if one else {}})
    if not tools and re.search(r"result|marks|grade|score|\bpass|\bfail", ql):
        tools.append({"name": "get_results", "args": {"course_code": one} if one else {}})
    if not tools and re.search(r"cgpa|gpa|backlog|semester|programme|batch", ql):
        tools.append({"name": "get_student_profile", "args": {}})
    return {"intent": "personal_data", "tools": tools, "search_query": question}


@register_mock("plan")
def _mock_plan(ctx: dict) -> dict:
    return rule_plan(ctx["question"], ctx["courses"])


def validate_plan(raw: dict, question: str, courses: list[dict]) -> tuple[dict, str]:
    """Returns (plan, status) where status is ok | invalid | clarify."""
    codes = {c["course_code"] for c in courses}
    names = {c["course_code"]: c["course_name"] for c in courses}
    found = resolve_courses(question, courses)
    tools, notes = [], []
    for t in raw.get("tools") or []:
        name = t.get("name")
        spec = TOOLS.get(name)
        if spec is None:
            return {}, "invalid"
        args = {k: v for k, v in (t.get("args") or {}).items() if k in spec.params and v not in (None, "", [])}
        if "course_code" in spec.params:
            cc = str(args.get("course_code", "")).upper().strip()
            if cc not in codes:
                cc = found[0] if len(found) == 1 else ""
            if not cc and spec.params["course_code"].required:
                return {"courses": courses}, "clarify"
            if cc:
                args["course_code"] = cc
                if cc not in question.upper():
                    notes.append(f"Interpreted the course as {cc} ({names[cc]}).")
            else:
                args.pop("course_code", None)
        if "assume_passed" in args:
            ap = [str(x).upper() for x in (args["assume_passed"] if isinstance(args["assume_passed"], list)
                                            else [args["assume_passed"]])]
            ap = [x for x in ap if x in codes] or [x for x in found]
            if ap:
                args["assume_passed"] = ap
            else:
                args.pop("assume_passed")
        try:
            for k in ("future_classes", "attend_classes"):
                if k in args:
                    args[k] = int(args[k])
            if "assume_cgpa" in args:
                args["assume_cgpa"] = float(args["assume_cgpa"])
        except (TypeError, ValueError):
            return {}, "invalid"
        missing = [k for k, p in spec.params.items() if p.required and k not in args]
        if missing:
            return ({"courses": courses}, "clarify") if missing == ["course_code"] else ({}, "invalid")
        if {"name": name, "args": args} not in tools:
            tools.append({"name": name, "args": args})
    if not tools:
        return {}, "invalid"
    names_used = [t["name"] for t in tools]
    decision = any(n.startswith("check_") or n == "project_attendance" for n in names_used)
    intent = "multi_step" if len(tools) > 1 else "personal_eligibility" if decision else "personal_data"
    return {"intent": intent, "tools": tools, "needs_retrieval": decision,
            "search_query": raw.get("search_query") or question, "assumptions": notes}, "ok"
