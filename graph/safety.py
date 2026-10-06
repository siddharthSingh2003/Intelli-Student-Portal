"""Safety (M3): authorisation (R7) and untrusted-content handling (R8). Deterministic, no LLM.

Defence in depth for R8: (1) evidence is wrapped and labelled as data in the prompt,
(2) instruction-like sentences are stripped before the LLM sees them and logged,
(3) the LLM cannot reach other students' data anyway - tools only receive the
header identity, and authoritative results come from code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from data.db import one, rows

STRONG_SELF = re.compile(r"\b(my|me|mine|am i|i am|i'm|i've|i have)\b", re.I)
SELF = re.compile(r"\b(i|my|me|mine)\b", re.I)
PERSONAL_TOPIC = re.compile(r"attendance|\bmarks?\b|\bresults?\b|cgpa|\bgpa\b|backlog|eligib|\bgrades?\b|"
                            r"\bfail|\bpass(ed)?\b|detain|\bscore|supplementar|placement|\babsent|\bclasses\b", re.I)
PROCEDURE = re.compile(r"\b(how|where|when)\s+(do|can|should|to)\s+i\b|\bhow to\b|\bprocedure\b|\bsteps?\b|"
                       r"\bprocess\b|\bapply\b|\bregister\b", re.I)
OTHER_PERSON = re.compile(r"\b(friend|room-?mate|classmate|batch-?mate|brother|sister|another student|"
                          r"other students?|someone else|every student'?s|all students'?)\b", re.I)
SID = re.compile(r"\bS\d{4}\b", re.I)

INJECTION = [re.compile(p, re.I) for p in (
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules)",
    r"disregard (the |all )?(system|previous|above)", r"\byou are now\b", r"\badmin mode\b",
    r"reveal (the )?(records|data|system prompt|password)", r"system prompt", r"^\s*(system|assistant)\s*:",
    r"\bact as\b", r"new instructions?:")]


@dataclass
class AccessDecision:
    refused: bool = False
    message: str = ""
    reason: str = ""
    student: Optional[dict] = None
    personal: bool = False


def is_personal(q: str) -> bool:
    if not PERSONAL_TOPIC.search(q):
        return False
    if STRONG_SELF.search(q):
        return True
    return bool(SELF.search(q)) and not PROCEDURE.search(q)


def check_access(question: str, student_id: Optional[str]) -> AccessDecision:
    sid = (student_id or "").strip().upper() or None
    student = one("SELECT * FROM students WHERE student_id = ?", (sid,)) if sid else None
    if sid and not student:
        return AccessDecision(True, "The logged-in student ID was not found in the student records.", "unknown_student")

    other_ids = {m.upper() for m in SID.findall(question)} - ({sid} if sid else set())
    other_name = False
    if student:
        q = question.lower()
        other_name = any(len(r["full_name"]) >= 6 and r["full_name"].lower() in q
                         for r in rows("SELECT full_name FROM students WHERE student_id != ?", (sid,)))
    if other_ids or other_name or (OTHER_PERSON.search(question) and PERSONAL_TOPIC.search(question)):
        return AccessDecision(True, "I can't share another student's records. I can only answer questions about "
                                    "the logged-in student's own data.", "other_student_data", student)

    personal = is_personal(question)
    if personal and not student:
        return AccessDecision(True, "This question needs your personal records, but no logged-in student was "
                                    "identified. Please log in as a student and ask again.", "no_identity")
    return AccessDecision(False, student=student, personal=personal)


def sanitize_evidence(evidence: list[dict]) -> tuple[list[dict], list[dict]]:
    flags, clean = [], []
    for e in evidence:
        kept = []
        for sent in re.split(r"(?<=[.!?])\s+|\n", e["text"]):
            hit = next((p.pattern for p in INJECTION if p.search(sent)), None)
            if hit:
                flags.append({"chunk_id": e["chunk_id"], "doc_id": e["doc_id"], "pattern": hit})
            elif sent.strip():
                kept.append(sent)
        clean.append({**e, "text": " ".join(kept)})
    return clean, flags
