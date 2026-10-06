"""Tool catalogue (M2 -> M3 interface). The planner may only choose tools listed here,
with only these parameters. student_id and as_of are injected by the orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from tools import eligibility, student_tools
from tools.student_tools import ToolError  # noqa: F401  (re-export)


@dataclass(frozen=True)
class Param:
    type: str
    required: bool
    description: str


@dataclass(frozen=True)
class ToolSpec:
    fn: Callable
    description: str
    params: dict[str, Param] = field(default_factory=dict)


TOOLS: dict[str, ToolSpec] = {
    "get_student_profile": ToolSpec(student_tools.get_student_profile,
        "Programme, batch, semester, CGPA and active backlog count of the logged-in student."),
    "get_attendance": ToolSpec(student_tools.get_attendance,
        "Classes held, attended and attendance % per course (one course if course_code is given).",
        {"course_code": Param("string", False, "course code, omit for all courses")}),
    "get_results": ToolSpec(student_tools.get_results,
        "Latest exam result (marks and PASS/FAIL/ABSENT/DETAINED) per course.",
        {"course_code": Param("string", False, "course code, omit for all courses")}),
    "check_exam_eligibility": ToolSpec(eligibility.check_exam_eligibility,
        "Whether the student may appear in the end-semester exam of a course (attendance rule).",
        {"course_code": Param("string", True, "course code")}),
    "check_supplementary_eligibility": ToolSpec(eligibility.check_supplementary_eligibility,
        "Whether the student may take the supplementary exam in a course.",
        {"course_code": Param("string", True, "course code")}),
    "check_placement_eligibility": ToolSpec(eligibility.check_placement_eligibility,
        "Whether the student meets campus-placement CGPA and backlog rules. For what-if questions, "
        "assume_passed lists courses the student assumes they will clear.",
        {"assume_passed": Param("list[string]", False, "course codes assumed passed (what-if)"),
         "assume_cgpa": Param("number", False, "hypothetical CGPA (what-if)")}),
    "project_attendance": ToolSpec(eligibility.project_attendance,
        "What-if: attendance % after future classes, and whether it meets the rule.",
        {"course_code": Param("string", True, "course code"),
         "future_classes": Param("integer", True, "classes still to be held"),
         "attend_classes": Param("integer", True, "of those, how many the student attends")}),
}


def catalog_text() -> str:
    lines = []
    for name, spec in TOOLS.items():
        ps = ", ".join(f"{k}: {p.type}{'' if p.required else ' (optional)'}" for k, p in spec.params.items())
        lines.append(f"- {name}({ps}): {spec.description}")
    return "\n".join(lines)
