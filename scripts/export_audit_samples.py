"""Writes three sample audit records for different answer types (deliverable, Section 8)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from graph.workflow import run_question  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "audit_samples"
CASES = [("calculated", "Am I eligible to appear in the end-semester exam for Data Structures?", "S1004"),
         ("retrieved_fact", "What is the minimum attendance required to appear for end-semester exams?", None),
         ("refused", "What is the attendance of S1002 in Data Structures?", "S1001"),
         ("conflict_flagged", "What time does the hostel curfew start?", None)]

OUT.mkdir(parents=True, exist_ok=True)
for name, q, sid in CASES:
    resp, audit = run_question(q, sid, date(2026, 10, 6))
    (OUT / f"{name}.json").write_text(json.dumps({"request": {"question": q, "X-Student-Id": sid},
                                                  "response": resp, "audit": audit}, indent=2))
    print(name, resp["answer_type"], resp["trace_id"])
