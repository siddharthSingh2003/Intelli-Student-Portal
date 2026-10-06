"""Rule extraction on ingest (M2).

Answers the judge question "what happens when a new circular changes a rule?":
when a document is ingested (startup or live POST /ingest), sentences matching
known threshold patterns become rule_registry rows tied to the exact doc_id and
section. Precedence (Annex A) then decides which rule applies on any date.

Deliberately pattern-based (deterministic, auditable) rather than LLM-based:
a wrong threshold would silently corrupt every eligibility decision. Anything the
patterns miss is added via data/seed/rules_seed.csv, the POST /ingest "rules"
field, or POST /admin/rules.
"""
from __future__ import annotations

import re

from ingestion.chunker import Chunk
from shared.schemas import DocMetadata

PCT = r"(\d{2,3}(?:\.\d+)?)\s*(?:%|per\s*cent|percent)"
SENT_SPLIT = re.compile(r"(?<=[.;])\s+(?=[A-Z(])|\n")
# PDF text is hard-wrapped mid-sentence: join a line to the previous one unless it starts a new
# clause, list item or table row, so a rule that spans two lines is still read as one sentence
WRAPPED = re.compile(r"\n(?!\s*(?:\d+(?:\.\d+)*\.?\s|\(\w{1,3}\)\s|\[Table|Table \d|.*\|))")
# "attendance below X%" only states a minimum when the sentence also states the consequence;
# on its own (a table cell, a worked example) it is not a rule
# questions and second-person answers (FAQ sections, worked examples) illustrate a rule, they do not set one
EXAMPLE = re.compile(r"\?|\b(?:you|your|am i|will i|can i|do i)\b")
CONSEQUENCE = re.compile(r"detain|debar|not (?:be )?(?:eligible|permitted|allowed)|shall not|may not", re.I)

ATTENDANCE = [
    re.compile(r"(?:minimum|at least|not less than)[^.\n]{0,60}?attendance[^.\n]{0,40}?" + PCT, re.I),
    re.compile(r"attendance[^.\n]{0,40}?(?:minimum|at least|not less than)[^.\n]{0,20}?" + PCT, re.I),
    re.compile(r"(?:less than|below)\s*" + PCT + r"\s*(?:of\s+)?attendance", re.I),
    re.compile(r"attendance\s*(?:of\s*)?(?:less than|below)\s*" + PCT, re.I),
]
PASS = re.compile(r"(?:at least|minimum(?: of)?|not less than)\s*" + PCT + r"[^.\n]{0,60}?\bpass", re.I)
CGPA = [re.compile(r"(?:minimum|at least)\s+CGPA\s+(?:of\s+)?(\d{1,2}(?:\.\d{1,2})?)", re.I),
        re.compile(r"CGPA[^.\n]{0,30}?(?:of at least|not less than|>=|≥|minimum of)\s*(\d{1,2}(?:\.\d{1,2})?)", re.I)]
BACKLOG_NONE = re.compile(r"\bno\s+(?:active\s+)?backlogs?\b", re.I)
BACKLOG_MAX = re.compile(r"(?:not more than|maximum of|at most|up to)\s+(\d+)\s+(?:active\s+)?backlogs?", re.I)

PREFIX = {"min_attendance_pct": "ATT-MIN", "pass_min_total_pct": "PASS-MIN", "placement_min_cgpa": "PLC-CGPA",
          "placement_max_backlogs": "PLC-BKLG", "supp_eligible_results": "SUPP-ELIG"}
DESC = {"min_attendance_pct": "Minimum attendance % per course to appear in the end-semester exam",
        "pass_min_total_pct": "Minimum % of total marks to pass a course",
        "placement_min_cgpa": "Minimum CGPA to register for campus placement",
        "placement_max_backlogs": "Maximum active backlogs allowed for campus placement",
        "supp_eligible_results": "Results that make a student eligible for the supplementary exam"}


def extract_rules(chunks: list[Chunk], meta: DocMetadata) -> list[dict]:
    if meta.authority_level == 5:          # unofficial content can never set a rule
        return []
    found: dict[tuple[str, str], dict] = {}

    def put(param: str, op: str, value: str, section: str, sentence: str):
        key = (param, section)
        if key not in found:
            found[key] = {"rule_id": f"{PREFIX[param]}@{meta.doc_id}#{section}",
                          "description": f"{DESC[param]} (auto-extracted: \"{sentence.strip()[:140]}\")",
                          "parameter": param, "operator": op, "value": value,
                          "scope_programmes": meta.scope_programmes, "scope_batches": meta.scope_batches,
                          "effective_from": meta.effective_from.isoformat(),
                          "effective_to": meta.effective_to.isoformat() if meta.effective_to else "",
                          "source_doc_id": meta.doc_id, "source_section": section}

    for ch in chunks:
        for s in SENT_SPLIT.split(WRAPPED.sub(" ", ch.text)):
            low = s.lower()
            if EXAMPLE.search(low):
                continue
            if "attendance" in low:
                for i, pat in enumerate(ATTENDANCE):
                    if i >= 2 and not CONSEQUENCE.search(s):      # the two "below X%" forms
                        continue
                    if (m := pat.search(s)) and 50 <= float(m.group(1)) <= 100:
                        put("min_attendance_pct", ">=", m.group(1), ch.section, s)
                        break
            if (m := PASS.search(s)) and "attendance" not in low:
                put("pass_min_total_pct", ">=", m.group(1), ch.section, s)
            if "placement" in low:
                for pat in CGPA:
                    if m := pat.search(s):
                        put("placement_min_cgpa", ">=", m.group(1), ch.section, s)
                        break
                if BACKLOG_NONE.search(s):
                    put("placement_max_backlogs", "<=", "0", ch.section, s)
                elif m := BACKLOG_MAX.search(s):
                    put("placement_max_backlogs", "<=", m.group(1), ch.section, s)
            if "supplementary" in low and "eligible" in low and re.search(r"\bfail", low) \
                    and "not eligible" not in low:
                vals = ["FAIL"] + (["ABSENT"] if "absent" in low else [])
                put("supp_eligible_results", "in", ";".join(vals), ch.section, s)
    return list(found.values())


def extract_and_store(chunks: list[Chunk], meta: DocMetadata) -> int:
    from data.db import get_conn
    from tools.rules import add_rule
    with get_conn() as c:     # re-ingesting a document refreshes its extracted rules
        c.execute("DELETE FROM rule_registry WHERE source_doc_id = ? AND origin = 'extracted'", (meta.doc_id,))
    rules = extract_rules(chunks, meta)
    for r in rules:
        add_rule(r, origin="extracted")
    return len(rules)
