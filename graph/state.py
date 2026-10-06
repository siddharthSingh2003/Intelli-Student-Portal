"""LangGraph state (M3): what each node reads and writes."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict


class GraphState(TypedDict, total=False):
    # input
    trace_id: str
    question: str
    student_id: Optional[str]
    as_of_date: str
    retrieval_config: Any
    started: float
    # guard / plan
    student: Optional[dict]
    personal: bool
    intent: str
    plan: dict
    assumptions: list
    # retrieval + precedence
    retrieved: list
    evidence: list
    upcoming: list
    precedence_decisions: list
    doc_conflicts: list
    # tools
    tool_calls: list
    applied_rules: list
    rule_conflicts: list
    rule_citations: list
    # generation / output
    llm_answer: dict
    answer: str
    answer_type: str
    explanation: str
    response: dict
    audit: dict
    # accumulated telemetry
    llm_calls: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    injection_flags: Annotated[list, operator.add]
    notes: Annotated[list, operator.add]
