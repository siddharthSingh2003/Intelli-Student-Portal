"""Rule registry access (M2). Tools read every threshold from here - never from constants."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from data.db import get_conn, rows
from ingestion import source_register
from ingestion.precedence import resolve_rules
from shared.schemas import ConflictRecord, RuleIn

RULE_COLS = ["rule_id", "description", "parameter", "operator", "value", "scope_programmes", "scope_batches",
             "effective_from", "effective_to", "source_doc_id", "source_section"]


@dataclass
class RuleResolution:
    parameter: str
    rule: Optional[dict] = None
    conflicts: list[ConflictRecord] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    unresolved: bool = False


def add_rule(rule: RuleIn | dict, origin: str = "manual") -> None:
    r = rule if isinstance(rule, RuleIn) else RuleIn.model_validate(rule)
    if source_register.get(r.source_doc_id) is None:
        raise ValueError(f"rule {r.rule_id}: source_doc_id {r.source_doc_id} is not in the Source Register")
    data = r.model_dump()
    with get_conn() as c:
        c.execute(f"INSERT OR REPLACE INTO rule_registry ({','.join(RULE_COLS)}, origin) "
                  f"VALUES ({','.join('?' * len(RULE_COLS))}, ?)",
                  tuple(data[k] if data[k] is not None else "" for k in RULE_COLS) + (origin,))


def load_rules_csv(path: str | Path) -> dict[str, int]:
    stats = {"loaded": 0, "skipped": 0}
    p = Path(path)
    if not p.exists():
        return stats
    with p.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("rule_id") or "").strip():
                continue
            try:
                add_rule({k: (v or "").strip() for k, v in row.items() if k}, origin="manual")
                stats["loaded"] += 1
            except ValueError:
                stats["skipped"] += 1
    return stats


def get_rule(parameter: str, as_of: date, student: Optional[dict] = None) -> RuleResolution:
    student = student or {}
    candidates = rows("SELECT * FROM rule_registry WHERE parameter = ?", (parameter,))
    rule, conflicts, decisions, unresolved = resolve_rules(
        candidates, as_of, student.get("programme"), student.get("batch_year"), source_register.all_docs())
    return RuleResolution(parameter, rule, conflicts, decisions, unresolved)


def compare(actual: float | str, operator: str, value: str) -> bool:
    op = operator.strip().lower()
    if op == "in":
        return str(actual).upper() in {v.strip().upper() for v in value.split(";")}
    if op == "between":
        lo, hi = (float(x) for x in value.split(";"))
        return lo <= float(actual) <= hi
    a, v = float(actual), float(value)
    return {">=": a >= v, ">": a > v, "<=": a <= v, "<": a < v, "==": a == v}[op]


def applied(rule: dict) -> dict:
    return {"rule_id": rule["rule_id"], "value": f"{rule['operator']}{rule['value']}",
            "source_doc_id": rule["source_doc_id"], "source_section": rule["source_section"],
            "parameter": rule["parameter"]}
