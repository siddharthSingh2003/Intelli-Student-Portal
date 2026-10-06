"""LangGraph workflow (M3).

    guard --refused--> finalize
      |
    plan --clarify--> finalize
      |  \--(personal data only)--> tools
    retrieve -> tools -> generate -> finalize

Single workflow, not multi-agent: every branch is decided by code, and the only
two LLM calls (plan, answer) are validated afterwards. Nothing here needs an
autonomous agent loop, so we deliberately did not add one.
"""
from __future__ import annotations

import time
import uuid
from datetime import date
from typing import Optional

from langgraph.graph import END, StateGraph

from graph.nodes import finalize_node, generate_node, guard_node, plan_node, retrieve_node, tools_node
from graph.state import GraphState
from shared.config import RetrievalConfig


def _build():
    g = StateGraph(GraphState)
    for name, fn in [("guard", guard_node), ("plan", plan_node), ("retrieve", retrieve_node),
                     ("tools", tools_node), ("generate", generate_node), ("finalize", finalize_node)]:
        g.add_node(name, fn)
    g.set_entry_point("guard")
    g.add_conditional_edges("guard", lambda s: "finalize" if s.get("answer_type") else "plan")
    g.add_conditional_edges("plan", lambda s: "finalize" if s.get("answer_type") else
                            ("retrieve" if s["plan"].get("needs_retrieval") else "tools"))
    g.add_edge("retrieve", "tools")
    g.add_edge("tools", "generate")
    g.add_edge("generate", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


APP = _build()


def run_question(question: str, student_id: Optional[str] = None, as_of_date: Optional[date] = None,
                 retrieval_config: Optional[RetrievalConfig] = None) -> tuple[dict, dict]:
    state = APP.invoke({
        "trace_id": uuid.uuid4().hex[:12], "question": question.strip(),
        "student_id": (student_id or "").strip().upper() or None,
        "as_of_date": (as_of_date or date.today()).isoformat(),
        "retrieval_config": retrieval_config, "started": time.perf_counter(),
        "llm_calls": 0, "tokens": 0, "injection_flags": [], "notes": [],
    })
    return state["response"], state["audit"]
