"""Source Precedence Policy - Annex A, implemented as deterministic code (M1).

Used twice:
  * resolve_evidence(): on retrieved chunks, before the LLM sees them
  * resolve_rules():    on rule_registry rows, inside the eligibility tools (M2)

Order (Annex A.2): 1 applicability -> 2 explicit supersession (level 1/2 issuers only)
-> 3 authority -> 4 recency -> 5 unresolved => conflict_flagged.
Level-5 content is informational only and can never override anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from shared.schemas import ConflictRecord, DocMetadata


@dataclass
class Candidate:
    key: str                 # chunk_id or rule_id
    doc_id: str
    section: str
    meta: DocMetadata        # effective dates / scope of the candidate
    score: float = 0.0
    payload: Any = None


@dataclass
class PrecedenceResult:
    kept: list[Candidate] = field(default_factory=list)          # best first
    upcoming: list[Candidate] = field(default_factory=list)      # not yet effective
    excluded: list[tuple[Candidate, str]] = field(default_factory=list)
    superseded: list[tuple[Candidate, str]] = field(default_factory=list)
    conflicts: list[ConflictRecord] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)


def _items(scope: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;,]", scope or "") if x.strip()]


def programme_in_scope(scope: str, programme: Optional[str]) -> bool:
    if not programme or not scope or scope.strip().upper() == "ALL":
        return True
    p = programme.lower()
    return any(p == it.lower() or p.startswith(it.lower()) for it in _items(scope))


def batch_in_scope(scope: str, batch: Optional[int]) -> bool:
    if batch is None or not scope or scope.strip().upper() == "ALL":
        return True
    for it in _items(scope):
        if m := re.fullmatch(r"(\d{4})\+", it):
            if batch >= int(m.group(1)):
                return True
        elif m := re.fullmatch(r"(\d{4})\s*-\s*(\d{4})", it):
            if int(m.group(1)) <= batch <= int(m.group(2)):
                return True
        elif re.fullmatch(r"\d{4}", it) and batch == int(it):
            return True
    return False


def applicability(meta: DocMetadata, as_of: date, programme: Optional[str] = None,
                  batch: Optional[int] = None) -> tuple[bool, str]:
    """Step 1."""
    if meta.effective_from > as_of:
        return False, "upcoming"
    if meta.effective_to and meta.effective_to < as_of:
        return False, "expired"
    if not programme_in_scope(meta.scope_programmes, programme):
        return False, "programme_out_of_scope"
    if not batch_in_scope(meta.scope_batches, batch):
        return False, "batch_out_of_scope"
    return True, "applicable"


def supersedes(a: DocMetadata, doc_id: str, section: str) -> bool:
    """Step 2: explicit supersession counts only when issued at authority level 1 or 2."""
    if a.authority_level not in (1, 2) or a.doc_id == doc_id:
        return False
    for ref in a.supersedes:
        if "#" in ref:
            d, clause = ref.split("#", 1)
            if d == doc_id and section and (section == clause or section.startswith(clause + ".")):
                return True
        elif ref == doc_id:
            return True
    return False


def is_scoped(m: DocMetadata) -> bool:
    return m.scope_batches.strip().upper() != "ALL"


def scope_covers(a: DocMetadata, b: DocMetadata) -> bool:
    """True if a's batch scope includes everything b's does (used when no student is known)."""
    return not is_scoped(a) or a.scope_batches.replace(" ", "") == b.scope_batches.replace(" ", "")


def resolve_pair(a: DocMetadata, b: DocMetadata) -> tuple[Optional[DocMetadata], str]:
    """Steps 3-5 for two applicable, non-superseded sources that disagree."""
    if a.authority_level != b.authority_level:
        w = a if a.authority_level < b.authority_level else b
        note = " (level 5 is informational only)" if 5 in (a.authority_level, b.authority_level) else ""
        return w, "step 3: authority" + note
    if a.effective_from != b.effective_from:
        return (a if a.effective_from > b.effective_from else b), "step 4: recency"
    return None, "step 5: unresolved"


def resolve_evidence(cands: list[Candidate], as_of: date, programme: Optional[str] = None,
                     batch: Optional[int] = None,
                     register: Optional[dict[str, DocMetadata]] = None) -> PrecedenceResult:
    res = PrecedenceResult()
    applicable = []
    for c in cands:
        ok, why = applicability(c.meta, as_of, programme, batch)
        if ok:
            applicable.append(c)
        elif why == "upcoming":
            res.upcoming.append(c)
        else:
            res.excluded.append((c, why))

    # supersession is checked against every applicable registered document,
    # not only the retrieved ones, so a superseded clause can't slip through
    pool = dict(register or {})
    for c in applicable:
        pool.setdefault(c.doc_id, c.meta)
    superseders = [m for m in pool.values() if m.supersedes and applicability(m, as_of, programme, batch)[0]]

    general = programme is None and batch is None
    seen = set()
    for c in applicable:
        by = next((m for m in superseders if supersedes(m, c.doc_id, c.section)), None)
        if by is not None and general and not scope_covers(by, c.meta):
            res.decisions.append(f"{by.doc_id} supersedes {c.doc_id}#{c.section} only for batches "
                                 f"{by.scope_batches}; kept for a general question")
            by = None
        if by is None:
            res.kept.append(c)
            continue
        res.superseded.append((c, by.doc_id))
        target = f"{c.doc_id}#{c.section}"
        if (by.doc_id, target) not in seen:
            seen.add((by.doc_id, target))
            res.conflicts.append(ConflictRecord(winner=by.doc_id, overridden=[target], step="step 2: supersession",
                                                note=f"{by.doc_id} explicitly supersedes {target}"))
            res.decisions.append(f"{by.doc_id} supersedes {target} (step 2)")

    # steps 3+4 as an ordering: higher authority first, then most recent, then relevance
    # with no student context, rules for all batches come before batch-specific ones
    res.kept.sort(key=lambda c: (c.meta.authority_level, general and is_scoped(c.meta),
                                 -c.meta.effective_from.toordinal(), -c.score))
    return res


def resolve_rules(rule_rows: list[dict], as_of: date, programme: Optional[str], batch: Optional[int],
                  register: dict[str, DocMetadata]) -> tuple[Optional[dict], list[ConflictRecord], list[str], bool]:
    """Pick the one rule that applies. Returns (rule, conflicts, decisions, unresolved)."""
    cands, decisions = [], []
    for r in rule_rows:
        meta = register.get(r["source_doc_id"])
        if meta is None:
            decisions.append(f"{r['rule_id']} ignored: source {r['source_doc_id']} not in Source Register")
            continue
        view = meta.model_copy(update={
            "effective_from": date.fromisoformat(r["effective_from"]) if r.get("effective_from") else meta.effective_from,
            "effective_to": date.fromisoformat(r["effective_to"]) if r.get("effective_to") else meta.effective_to,
            "scope_programmes": r.get("scope_programmes") or meta.scope_programmes,
            "scope_batches": r.get("scope_batches") or meta.scope_batches})
        if meta.authority_level == 5:
            decisions.append(f"{r['rule_id']} ignored: level-5 sources cannot set rules")
            continue
        cands.append(Candidate(r["rule_id"], r["source_doc_id"], str(r["source_section"]), view, 0.0, r))

    pr = resolve_evidence(cands, as_of, programme, batch, register)
    conflicts = [ConflictRecord(winner=c.winner, overridden=c.overridden, step=c.step, note=c.note)
                 for c in pr.conflicts]
    decisions += pr.decisions
    if not pr.kept:
        return None, conflicts, decisions, False
    winner = pr.kept[0]
    for other in pr.kept[1:]:
        if str(other.payload["value"]) == str(winner.payload["value"]):
            continue
        w, step = resolve_pair(winner.meta, other.meta)
        if w is None:
            conflicts.append(ConflictRecord(winner=None, overridden=[winner.key, other.key], step=step,
                                            note="same authority and effective date; contact the issuing office"))
            return None, conflicts, decisions, True
        conflicts.append(ConflictRecord(winner=winner.key, overridden=[other.key], step=step,
                                        note=f"{winner.doc_id} prevails over {other.doc_id}"))
        decisions.append(f"{winner.key} prevails over {other.key} ({step})")
    return winner.payload, conflicts, decisions, False
