"""Deterministic extractive answerer (M3).

Two uses: (1) the MOCK_LLM responder for the 'answer' task, so the full pipeline
runs offline/in CI; (2) the fallback when the real LLM fails or its answer is not
grounded. It only ever copies sentences that exist in the evidence.
"""
from __future__ import annotations

import re

from shared.llm import register_mock

STOP = set("""a an the is are was were be been to of in on for and or what which who whom how do does did i my me
am can will would should could at by with from as it this that these those there their its your you we our any all
please tell about get much many need when where why if than then also into per""".split())
VALUE = re.compile(r"\d+(?:\.\d+)?\s*%|\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|\brs\.?\s*[\d,]+|\b\d+(?:\.\d+)?\b", re.I)
SENT = re.compile(r"(?<=[.!?])\s+")


def stems(text: str) -> set[str]:
    return {w[:4] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in STOP}


def overlap(qs: set[str], text: str) -> int:
    return len(qs & stems(text))


def relevant(qs: set[str], text: str) -> bool:
    n = overlap(qs, text)
    return n >= min(2, len(qs)) and n / max(1, len(qs)) >= 0.4


def _units(text: str) -> list[str]:
    """Sentences, with short heading fragments ("7.2 Minimum attendance.") joined to the next sentence."""
    body = re.sub(r"^\[[^\]]*\]\s*", "", text)
    sents = [s.strip() for s in SENT.split(body) if s.strip()]
    units, carry = [], ""
    for s in sents:
        if len(s.split()) < 6 and not VALUE.search(s.split(" ", 1)[-1]):
            carry = f"{carry} {s}".strip()
            continue
        units.append(f"{carry} {s}".strip())
        carry = ""
    if carry:
        units.append(carry)
    return units or [body]


def _sentence_key(qs: set[str], s: str) -> tuple[int, bool]:
    return overlap(qs, s), bool(values(s))


def best_sentence(qs: set[str], text: str) -> str:
    best = max(_units(text), key=lambda s: _sentence_key(qs, s))
    return re.sub(r"^\d{1,2}(?:\.\d{1,2})*\s+", "", best)


def values(text: str) -> set[str]:
    return {re.sub(r"\s+", "", v.lower()) for v in VALUE.findall(text) if "%" in v or ":" in v or "m" in v.lower()}


@register_mock("answer")
def extractive_answer(ctx: dict) -> dict:
    qs = stems(ctx["question"])
    evidence = ctx.get("evidence", [])
    if ctx.get("tool_calls"):
        return {"answer": "", "explanation": "", "cited_chunk_ids": [], "evidence_sufficient": True}
    scored = [(overlap(qs, e["text"]), i, e) for i, e in enumerate(evidence) if relevant(qs, e["text"])]
    if not scored:
        return {"answer": "", "evidence_sufficient": False, "cited_chunk_ids": []}
    # most relevant, then states a concrete value, then precedence order
    scored.sort(key=lambda t: (-t[0], not values(best_sentence(qs, t[2]["text"])), t[1]))
    best_n, _, top = scored[0]
    if ctx.get("intent") == "procedure":
        answer = re.sub(r"^\[[^\]]*\]\s*", "", top["text"])
    else:
        answer = best_sentence(qs, top["text"])
    pairs = []
    top_vals = values(best_sentence(qs, top["text"]))
    for n, _, e in scored[1:]:
        if e["doc_id"] == top["doc_id"] or n < max(2, 0.6 * best_n):
            continue
        ev = values(best_sentence(qs, e["text"]))
        if top_vals and ev and top_vals != ev:
            pairs.append([top["chunk_id"], e["chunk_id"]])
    return {"answer": answer, "explanation": "", "cited_chunk_ids": [top["chunk_id"]],
            "evidence_sufficient": True, "partial_note": "", "disagreements": pairs}
