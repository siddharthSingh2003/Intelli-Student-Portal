"""M1: Annex A precedence engine, including the guide's worked example (A.3)."""
from datetime import date

from ingestion.precedence import Candidate, batch_in_scope, programme_in_scope, resolve_evidence, resolve_rules
from shared.schemas import DocMetadata

REG = DocMetadata(doc_id="REG", title="Regs", issuer="Dean", authority_level=1, doc_type="regulation",
                  effective_from="2024-07-01")
CIRC = DocMetadata(doc_id="CIRC", title="Circ", issuer="Dean", authority_level=2, doc_type="circular",
                   effective_from="2026-08-01", supersedes="REG#7.2")
FAQ = DocMetadata(doc_id="FAQ", title="FAQ", issuer="Help desk", authority_level=4, doc_type="faq",
                  effective_from="2026-09-15")
REGISTER = {m.doc_id: m for m in (REG, CIRC, FAQ)}


def _rule(rid, doc, sec, val):
    return {"rule_id": rid, "parameter": "min_attendance_pct", "operator": ">=", "value": val,
            "source_doc_id": doc, "source_section": sec, "effective_from": "", "effective_to": "",
            "scope_programmes": "", "scope_batches": ""}


RULES = [_rule("R-REG", "REG", "7.2", "75"), _rule("R-CIRC", "CIRC", "2", "80"), _rule("R-FAQ", "FAQ", "1", "65")]


def test_worked_example_answer_is_80():
    rule, conflicts, _, unresolved = resolve_rules(RULES, date(2026, 10, 6), None, None, REGISTER)
    assert rule["value"] == "80" and not unresolved
    steps = {c.step.split(":")[0] for c in conflicts}
    assert steps == {"step 2", "step 3"}      # circular supersedes regs; FAQ is lower authority


def test_before_circular_regulation_applies():
    rule, *_ = resolve_rules(RULES, date(2026, 7, 15), None, None, REGISTER)
    assert rule["value"] == "75"


def test_supersession_requires_level_1_or_2():
    weak = FAQ.model_copy(update={"doc_id": "DEPT", "authority_level": 3, "supersedes": ["REG#7.2"]})
    c = Candidate("x", "REG", "7.2", REG)
    assert resolve_evidence([c], date(2026, 10, 6), register={"DEPT": weak}).kept == [c]


def test_unresolved_same_authority_same_date():
    a = FAQ.model_copy(update={"doc_id": "A", "authority_level": 3, "effective_from": date(2026, 9, 1)})
    b = a.model_copy(update={"doc_id": "B"})
    rules = [_rule("RA", "A", "1", "10"), _rule("RB", "B", "1", "11")]
    rule, _, _, unresolved = resolve_rules(rules, date(2026, 10, 6), None, None, {"A": a, "B": b})
    assert rule is None and unresolved


def test_scope_matching():
    assert programme_in_scope("B.Tech", "B.Tech CSE") and not programme_in_scope("M.Tech", "B.Tech CSE")
    assert batch_in_scope("2023+", 2024) and not batch_in_scope("2023+", 2022)
    assert batch_in_scope("2021-2023", 2022) and batch_in_scope("ALL", 2019)
