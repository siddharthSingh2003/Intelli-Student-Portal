"""Deterministic course resolution: maps 'Data Structures' / 'maths' / 'CS201' to codes (M3)."""
from __future__ import annotations

import re

ROMAN = {"i", "ii", "iii", "iv", "v", "vi"}


def _norm(name: str) -> str:
    name = re.sub(r"\(.*?\)", " ", name.lower()).replace("-", " ")
    return " ".join(w for w in re.findall(r"[a-z]+", name) if w not in ROMAN)


def resolve_courses(question: str, courses: list[dict]) -> list[str]:
    q_up, q_low = question.upper(), " " + _norm(question).replace("maths", "mathematics") + " "
    found = []
    for c in courses:
        code, name = c["course_code"].upper(), _norm(c["course_name"])
        long_words = [w for w in name.split() if len(w) >= 8]
        if re.search(rf"\b{re.escape(code)}\b", q_up) or f" {name} " in q_low or \
                any(f" {w} " in q_low for w in long_words):
            found.append(c["course_code"])
    return found
