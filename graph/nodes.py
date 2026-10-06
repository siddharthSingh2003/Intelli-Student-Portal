"""LangGraph nodes (M3). One linear workflow - guard -> plan -> retrieve -> tools ->
generate -> finalize - with early exits. Deterministic everywhere except two LLM
tasks (plan, answer), each validated by code afterwards."""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timezone

from data.db import rows
from graph import prompts, templates
from graph.extractive import best_sentence, extractive_answer, stems
from graph.planner import rule_plan, validate_plan
from graph.safety import PROCEDURE, check_access, sanitize_evidence
from ingestion import source_register
from ingestion.precedence import Candidate, is_scoped, resolve_evidence, resolve_pair
from ingestion.vector_store import get_store
from shared.config import RetrievalConfig, settings
from shared.llm import LLMClient, LLMError
from shared.schemas import AskResponse, Citation, DocMetadata
from tools.registry import TOOLS, ToolError, catalog_text

log = logging.getLogger(__name__)
NOT_FOUND_MSG = "I could not find this information in the authorised university sources."
NUM = re.compile(r"\d+(?:\.\d+)?")
llm = LLMClient()


def _cfg(state) -> RetrievalConfig:
    return state.get("retrieval_config") or RetrievalConfig.from_env()


def _as_of(state) -> date:
    return date.fromisoformat(state["as_of_date"])


# --------------------------------------------------------------------------- guard
def guard_node(state):
    d = check_access(state["question"], state.get("student_id"))
    if d.refused:
        return {"answer_type": "refused", "answer": d.message, "intent": "unauthorised",
                "explanation": f"Refused by the authorisation check ({d.reason}).", "student": d.student}
    return {"student": d.student, "personal": d.personal}


# --------------------------------------------------------------------------- plan
def plan_node(state):
    q, student = state["question"], state.get("student")
    if not state.get("personal"):
        intent = "procedure" if PROCEDURE.search(q) else "policy_fact"
        return {"intent": intent, "assumptions": [],
                "plan": {"intent": intent, "tools": [], "needs_retrieval": True, "search_query": q}}

    sid = student["student_id"]
    courses = rows("SELECT DISTINCT c.course_code, c.course_name FROM courses c WHERE c.course_code IN "
                   "(SELECT course_code FROM attendance WHERE student_id = ? UNION "
                   " SELECT course_code FROM results WHERE student_id = ?)", (sid, sid)) or \
        rows("SELECT course_code, course_name FROM courses WHERE programme = ?", (student["programme"],))
    calls = tokens = 0
    source = "llm"
    try:
        res = llm.chat_json("plan", prompts.PLAN_SYSTEM, prompts.plan_user(q, courses, catalog_text()),
                            prompts.PlanOut, mock_context={"question": q, "courses": courses})
        calls, tokens, raw = res.calls, res.tokens, res.data.model_dump()
    except LLMError as e:
        log.warning("planner LLM failed, using rule planner: %s", e)
        raw, source = rule_plan(q, courses), "rule_fallback"
    plan, status = validate_plan(raw, q, courses)
    if status == "invalid" and source == "llm":
        plan, status = validate_plan(rule_plan(q, courses), q, courses)
        source = "rule_fallback"
    if status == "clarify":
        listing = ", ".join(f"{c['course_code']} ({c['course_name']})" for c in courses)
        return {"answer_type": "clarification_needed", "intent": "clarification",
                "answer": f"Which course do you mean? Your courses are: {listing}.",
                "llm_calls": calls, "tokens": tokens, "notes": [f"planner={source}"]}
    if status == "invalid":   # personal wording but nothing to compute -> answer from documents
        return {"intent": "policy_fact", "assumptions": [], "llm_calls": calls, "tokens": tokens,
                "plan": {"intent": "policy_fact", "tools": [], "needs_retrieval": True, "search_query": q},
                "notes": [f"planner={source}: no tool applies"]}
    return {"intent": plan["intent"], "plan": plan, "assumptions": plan["assumptions"],
            "llm_calls": calls, "tokens": tokens, "notes": [f"planner={source}"]}


# --------------------------------------------------------------------------- retrieve
def _candidates(hits) -> list[Candidate]:
    return [Candidate(h.chunk_id, h.doc_id, h.section, DocMetadata.from_flat(h.meta), h.score, h) for h in hits]


def retrieve_node(state):
    cfg, as_of, student = _cfg(state), _as_of(state), state.get("student") or {}
    store = get_store(cfg)
    query = state["plan"].get("search_query") or state["question"]
    hits = store.search(query, cfg.top_k)
    register = source_register.all_docs()
    prog, batch = student.get("programme"), student.get("batch_year")
    prec = resolve_evidence(_candidates(hits), as_of, prog, batch, register)

    # the most relevant clauses of every superseding document are fetched explicitly,
    # so a retrieved-but-superseded clause is always replaced by the clause that overrides it
    superseders = {by for _, by in prec.superseded}
    if superseders:
        ids = {h.chunk_id for h in hits}
        for doc_id in superseders:
            hits += [h for h in store.search(query, 3, where={"doc_id": doc_id}) if h.chunk_id not in ids]
        prec = resolve_evidence(_candidates(hits), as_of, prog, batch, register)

    evidence = [{**c.payload.to_dict(), "informational": c.meta.authority_level == 5} for c in prec.kept]
    evidence, flags = sanitize_evidence(evidence)
    upcoming, seen = [], set()
    for c in prec.upcoming:
        if c.doc_id not in seen:
            seen.add(c.doc_id)
            upcoming.append(f"{c.meta.title} ({c.doc_id}) takes effect on {c.meta.effective_from.isoformat()}.")
    return {"retrieved": [{"doc_id": h.doc_id, "section": h.section, "chunk_id": h.chunk_id,
                           "score": round(h.score, 3)} for h in hits],
            "evidence": evidence, "upcoming": upcoming, "precedence_decisions": prec.decisions,
            "doc_conflicts": [c.model_dump() for c in prec.conflicts], "injection_flags": flags}


# --------------------------------------------------------------------------- tools
def tools_node(state):
    calls = (state.get("plan") or {}).get("tools", [])
    if not calls:
        return {"tool_calls": [], "applied_rules": [], "rule_conflicts": [], "rule_citations": []}
    sid, as_of, cfg = state["student"]["student_id"], _as_of(state), _cfg(state)
    invocations, applied, conflicts, assumptions = [], [], [], list(state.get("assumptions") or [])
    for call in calls:
        spec = TOOLS[call["name"]]
        t0 = time.perf_counter()
        try:
            out, status = spec.fn(student_id=sid, as_of=as_of, **call["args"]), "ok"
        except ToolError as e:
            out, status = {"result": "ERROR", "error": str(e)}, "error"
        applied += [r for r in out.pop("_applied_rules", []) if r not in applied]
        conflicts += out.pop("_conflicts", [])
        assumptions += out.pop("_assumptions", [])
        invocations.append({"tool": call["name"], "input": call["args"], "output": out, "status": status,
                            "ms": round((time.perf_counter() - t0) * 1000, 2)})
    citations = []
    for r in applied:
        meta = source_register.get(r["source_doc_id"])
        if meta:
            citations.append(Citation(doc_id=meta.doc_id, title=meta.title, section=str(r["source_section"]),
                                      page=get_store(cfg).find_page(meta.doc_id, str(r["source_section"])),
                                      version=meta.version, effective_from=meta.effective_from.isoformat()).model_dump())
    return {"tool_calls": invocations, "applied_rules": applied, "rule_conflicts": conflicts,
            "rule_citations": citations, "assumptions": assumptions}


# --------------------------------------------------------------------------- generate
def generate_node(state):
    if state.get("answer_type"):
        return {}
    cfg = _cfg(state)
    evidence, tool_calls = state.get("evidence", []), state.get("tool_calls", [])
    if not tool_calls and (not evidence or max(e["score"] for e in evidence) < settings.min_score(cfg.embedding)):
        return {"llm_answer": {"evidence_sufficient": False}, "notes": ["abstained before LLM: weak retrieval"]}
    ctx = {"question": state["question"], "evidence": evidence, "tool_calls": tool_calls,
           "intent": state.get("intent")}
    user = prompts.answer_user(state["question"], state["as_of_date"], state.get("student"), tool_calls,
                               evidence, state.get("upcoming", []), state.get("assumptions", []))
    try:
        res = llm.chat_json("answer", prompts.ANSWER_SYSTEM, user, prompts.AnswerOut, mock_context=ctx)
        return {"llm_answer": res.data.model_dump(), "llm_calls": res.calls, "tokens": res.tokens}
    except LLMError as e:
        log.warning("answer LLM failed, using extractive fallback: %s", e)
        return {"llm_answer": extractive_answer(ctx), "notes": ["answer=extractive_fallback"]}


# --------------------------------------------------------------------------- finalize
def _norm_nums(text: str) -> set[str]:
    return {f"{float(n):g}" for n in NUM.findall(text)}


def _grounded(text: str, sources: list[str]) -> bool:
    allowed = set().union(*(_norm_nums(s) for s in sources)) if sources else set()
    return _norm_nums(text) <= allowed


def _cite(e: dict) -> dict:
    return Citation(doc_id=e["doc_id"], title=e["title"], section=str(e["section"]), page=e.get("page"),
                    version=str(e["version"]), effective_from=e["effective_from"]).model_dump()


def finalize_node(state):
    atype = state.get("answer_type")
    answer, explanation = state.get("answer", ""), state.get("explanation", "")
    la = state.get("llm_answer") or {}
    evidence = {e["chunk_id"]: e for e in state.get("evidence", [])}
    tool_calls = state.get("tool_calls", [])
    applied = state.get("applied_rules", [])
    conflicts = list(state.get("doc_conflicts", [])) + list(state.get("rule_conflicts", []))
    citations: list[dict] = []
    notes, extra_assumptions = [], []
    cited = [c for c in la.get("cited_chunk_ids", []) if c in evidence]
    numeric_sources = [state["question"], state.get("as_of_date", "")] + [evidence[c]["text"] for c in cited] + \
        [str(tc["output"]) for tc in tool_calls] + [str(r) for r in applied] + \
        [f"{e['section']} {e['version']} {e['effective_from']}" for e in evidence.values()]

    if atype in ("refused", "clarification_needed"):
        pass
    elif tool_calls:
        outs = [tc["output"] for tc in tool_calls]
        citations = list(state.get("rule_citations", [])) + [_cite(evidence[c]) for c in cited]
        if any(o.get("result") == "CONFLICT" for o in outs):
            atype, answer = "conflict_flagged", templates.rule_conflict(tool_calls)
        elif all(o.get("result") in ("RULE_NOT_FOUND", "NO_RECORD", "ERROR") for o in outs):
            atype = "not_found"
            answer = NOT_FOUND_MSG if any(o.get("result") == "RULE_NOT_FOUND" for o in outs) else \
                " ".join(templates.verdict(tc["tool"], tc["output"]) for tc in tool_calls)
        else:
            atype = "calculated"
            answer = " ".join(templates.verdict(tc["tool"], tc["output"]) for tc in tool_calls)
        rule_src = {r["rule_id"]: f"{c['title']}, section {c['section']}"
                    for r, c in zip(applied, state.get("rule_citations", []))}
        llm_expl = (la.get("explanation") or "").strip()
        if llm_expl and _grounded(llm_expl, numeric_sources):
            explanation = llm_expl
        else:
            if llm_expl:
                notes.append("LLM explanation rejected: contained numbers not in tools/evidence")
            explanation = templates.explain(tool_calls, applied, rule_src)
    else:
        if not la.get("evidence_sufficient") or not cited:
            atype, answer = "not_found", NOT_FOUND_MSG
            if la.get("partial_note") and cited:
                answer += " " + la["partial_note"]
        else:
            unresolved, losers, scoped_notes = [], {}, []
            general = not state.get("student")
            for pair in la.get("disagreements", []):
                if len(pair) != 2 or not all(p in evidence for p in pair):
                    continue
                a, b = evidence[pair[0]], evidence[pair[1]]
                if a["doc_id"] == b["doc_id"]:
                    continue
                ma, mb = DocMetadata.from_flat(a), DocMetadata.from_flat(b)
                if general and is_scoped(ma) != is_scoped(mb):   # different populations, not a conflict
                    sc, gen = (a, b) if is_scoped(ma) else (b, a)
                    scoped_notes.append(f"{sc['title']} sets a different rule for batches {sc['scope_batches']}; "
                                        "log in for an answer specific to you.")
                    if cited and cited[0] == sc["chunk_id"]:
                        losers[sc["chunk_id"]] = gen
                    continue
                w, step = resolve_pair(ma, mb)
                if w is None:
                    unresolved.append((a, b))
                else:
                    loser = b if w.doc_id == a["doc_id"] else a
                    losers[loser["chunk_id"]] = a if loser is b else b
                    rec = {"winner": w.doc_id, "overridden": [f"{loser['doc_id']}#{loser['section']}"],
                           "step": step, "note": f"{loser['doc_id']} disagrees and is overridden"}
                    if rec not in conflicts:
                        conflicts.append(rec)
            if unresolved:
                a, b = unresolved[0]
                atype, answer = "conflict_flagged", templates.doc_conflict(a, b)
                citations = [_cite(a), _cite(b)]
                conflicts.append({"winner": None, "overridden": [f"{a['doc_id']}#{a['section']}",
                                                                 f"{b['doc_id']}#{b['section']}"],
                                  "step": "step 5: unresolved", "note": "contact the issuing office"})
            else:
                atype = "retrieved_fact"
                answer = la.get("answer", "").strip()
                if cited[0] in losers:       # hard guarantee: the answer comes from the precedence winner
                    winner = losers[cited[0]]
                    notes.append(f"answer re-based from {evidence[cited[0]]['doc_id']} to winner {winner['doc_id']}")
                    cited = [winner["chunk_id"]] + [c for c in cited if c not in losers]
                    answer = best_sentence(stems(state["question"]), winner["text"])
                    numeric_sources.append(winner["text"])
                if not answer or not _grounded(answer, numeric_sources):
                    notes.append("LLM answer failed grounding check; replaced with extractive sentence")
                    answer = best_sentence(stems(state["question"]), evidence[cited[0]]["text"])
                if la.get("partial_note"):
                    answer += f" (Partially answered: {la['partial_note']})"
                citations = [_cite(evidence[c]) for c in cited]
                extra_assumptions += scoped_notes
        top = evidence[cited[0]] if cited else None
        llm_expl = (la.get("explanation") or "").strip()
        if llm_expl and _grounded(llm_expl, numeric_sources):
            explanation = llm_expl
        elif top and atype == "retrieved_fact":
            explanation = (f"Taken from {top['title']}, section {top['section']} (version {top['version']}, "
                           f"effective {top['effective_from']}).")
        if state.get("precedence_decisions") or conflicts:
            explanation += " Precedence applied: " + "; ".join(
                f"{c['winner'] or 'unresolved'} over {', '.join(c['overridden'])} ({c['step']})" for c in conflicts) + "."
        if any(evidence[c].get("informational") for c in cited):
            explanation += " Note: an unofficial (level 5) source is cited for information only."

    if state.get("injection_flags"):
        notes.append(f"{len(state['injection_flags'])} instruction-like sentence(s) removed from documents")
    uniq_cites = []
    for c in citations:
        if c not in uniq_cites:
            uniq_cites.append(c)
    uniq_conf = []
    for c in conflicts:
        if c not in uniq_conf:
            uniq_conf.append(c)
    resp = AskResponse(
        trace_id=state["trace_id"], answer=answer, answer_type=atype, citations=uniq_cites,
        tools_invoked=tool_calls, applied_rules=applied, conflicts_detected=uniq_conf,
        explanation=explanation.strip(), assumptions=list(state.get("assumptions") or []) + extra_assumptions,
        upcoming_changes=state.get("upcoming") or [], as_of_date=state["as_of_date"])
    cfg = _cfg(state)
    audit = {
        "trace_id": state["trace_id"], "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "student_id": state.get("student_id"), "question_category": state.get("intent"),
        "as_of_date": state["as_of_date"],
        "sources_retrieved": state.get("retrieved", []),
        "precedence_decision": state.get("precedence_decisions", []),
        "conflicts_detected": uniq_conf,
        "tools_invoked": tool_calls, "rules_applied": applied,
        "answer_type": atype, "citations": [f"{c['doc_id']}#{c['section']}" for c in uniq_cites],
        "injection_flags": state.get("injection_flags", []), "notes": state.get("notes", []) + notes,
        "model": llm.model_name, "llm_calls": state.get("llm_calls", 0), "tokens": state.get("tokens", 0),
        "retrieval_config": cfg.label,
        "latency_ms": round((time.perf_counter() - state["started"]) * 1000),
    }
    return {"response": resp.model_dump(mode="json"), "audit": audit, "answer_type": atype}
