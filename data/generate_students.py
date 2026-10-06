"""Synthetic student-data generator (M2).

    python -m data.generate_students --out data/generated --n 30

* Real mode: the local LLM (Ollama, LLM_MODEL) writes students in batches using the
  verbatim prompts in data/prompts/. Output is schema-enforced (Pydantic + JSON schema
  passed to Ollama), invalid batches are retried with the error fed back.
* Code - not the LLM - assigns IDs, semesters, totals, max marks and backlog counts,
  and recomputes any result that contradicts the marks. Every correction is logged:
  that log is the "What the LLM got wrong" section of the data card.
* The 10 edge-case students (data/edge_cases.py) are inserted deterministically.
* MOCK_LLM=true uses a seeded Python generator instead (labelled in the log).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from data.credentials import COLUMNS as CRED_COLUMNS, initial_password
from data.edge_cases import (BATCHES, COURSES, EDGE_STUDENTS, EXTERNAL_MAX, INTERNAL_MAX, MAX_MARKS,
                             PASS_PCT, PROGRAMMES, SESSION, courses_for)
from data.validate import format_report, read_dir, validate_tables
from shared.config import settings
from shared.llm import LLMClient

PROMPTS = Path(__file__).parent / "prompts"
PASS_MARK = int(PASS_PCT * MAX_MARKS / 100)
COLUMNS = {
    "students": ["student_id", "full_name", "programme", "batch_year", "current_semester", "cgpa", "active_backlogs"],
    "courses": ["course_code", "course_name", "programme", "semester", "credits"],
    "attendance": ["student_id", "course_code", "classes_held", "classes_attended"],
    "results": ["student_id", "course_code", "exam_session", "exam_type", "internal_marks", "external_marks",
                "total_marks", "max_marks", "result"],
}


class GenAttendance(BaseModel):
    course_code: str
    classes_held: int = Field(gt=0, le=80)
    classes_attended: int = Field(ge=0)


class GenResult(BaseModel):
    course_code: str
    internal_marks: int = Field(ge=0, le=INTERNAL_MAX)
    external_marks: int = Field(ge=0, le=EXTERNAL_MAX)
    result: Literal["PASS", "FAIL", "ABSENT", "DETAINED"]


class GenStudent(BaseModel):
    full_name: str = Field(min_length=3)
    programme: Literal["B.Tech CSE", "B.Tech ECE"]
    batch_year: Literal[2023, 2024]
    cgpa: float = Field(ge=0, le=10)
    attendance: list[GenAttendance]
    results: list[GenResult]

    @model_validator(mode="after")
    def _check(self):
        codes = {c["course_code"] for c in courses_for(self.programme)}
        if {a.course_code for a in self.attendance} != codes:
            raise ValueError(f"attendance must cover exactly {sorted(codes)}")
        if {r.course_code for r in self.results} != codes:
            raise ValueError(f"results must cover exactly {sorted(codes)}")
        for a in self.attendance:
            if a.classes_attended > a.classes_held:
                raise ValueError(f"{a.course_code}: classes_attended > classes_held")
        return self


class GenBatch(BaseModel):
    students: list[GenStudent] = Field(min_length=1)


# --------------------------------------------------------------------------- #
def _llm_batches(n: int, batch_size: int, log: dict) -> list[GenStudent]:
    llm = LLMClient()
    system_t = (PROMPTS / "generate_students.system.txt").read_text()
    user_t = (PROMPTS / "generate_students.user.txt").read_text()
    system = system_t.format(internal_max=INTERNAL_MAX, external_max=EXTERNAL_MAX, pass_mark=PASS_MARK)
    out: list[GenStudent] = []
    i = 0
    while len(out) < n:
        programme = PROGRAMMES[i % len(PROGRAMMES)]
        want = min(batch_size, n - len(out))
        user = user_t.format(
            n=want, programme=programme, batch_years=list(BATCHES),
            courses=json.dumps([{k: c[k] for k in ("course_code", "course_name")} for c in courses_for(programme)]),
            avoid_names=json.dumps([s["full_name"] for s in EDGE_STUDENTS] + [s.full_name for s in out]))
        res = llm.chat_json("generate_students", system, user, GenBatch, temperature=0.7)
        log["calls"] += res.calls
        log["retries"] += max(0, res.calls - 1)
        log["tokens"] += res.tokens
        log["prompts"].append({"system": system, "user": user})
        out.extend(res.data.students[:want])
        i += 1
    return out


def _mock_batches(n: int, rng: random.Random) -> list[GenStudent]:
    first = ["Riya", "Aditya", "Neha", "Karan", "Pooja", "Siddhant", "Tanvi", "Yash", "Nikhil", "Sneha",
             "Harsh", "Kavya", "Manav", "Aditi", "Varun", "Simran", "Aryan", "Nisha", "Dev", "Priya"]
    last = ["Kapoor", "Joshi", "Bansal", "Chopra", "Saxena", "Agarwal", "Kulkarni", "Reddy", "Bose", "Das",
            "Mishra", "Pandey", "Sinha", "Jain", "Bhatt"]
    names = rng.sample([f"{f} {l}" for f in first for l in last], n)
    out = []
    for i in range(n):
        programme = PROGRAMMES[i % 2]
        att, res = [], []
        weak = rng.random() < 1 / 6
        for j, c in enumerate(courses_for(programme)):
            held = rng.randint(36, 48)
            attended = round(held * rng.uniform(0.78, 0.97))
            internal, external = rng.randint(22, 38), rng.randint(28, 55)
            if weak and j == 0:
                internal, external = rng.randint(10, 20), rng.randint(5, 18)
            att.append(GenAttendance(course_code=c["course_code"], classes_held=held, classes_attended=attended))
            res.append(GenResult(course_code=c["course_code"], internal_marks=internal, external_marks=external,
                                 result="PASS" if internal + external >= PASS_MARK else "FAIL"))
        out.append(GenStudent(full_name=names[i], programme=programme, batch_year=rng.choice(list(BATCHES)),
                              cgpa=round(rng.uniform(5.2, 9.6), 2), attendance=att, results=res))
    return out


def _to_rows(sid: str, g: GenStudent, log: dict) -> tuple[dict, list[dict], list[dict]]:
    """Code owns every derived field; contradictions from the LLM are corrected and logged."""
    att_rows = [{"student_id": sid, **a.model_dump()} for a in g.attendance]
    att_pct = {a.course_code: a.classes_attended / a.classes_held * 100 for a in g.attendance}
    res_rows, backlogs = [], 0
    for r in g.results:
        result, external = r.result, r.external_marks
        total = r.internal_marks + external
        expected = "PASS" if total >= PASS_MARK else "FAIL"
        if result == "ABSENT" and external != 0:
            log["corrections"].append(f"{sid}/{r.course_code}: ABSENT with external={external} -> external set to 0")
            external, total = 0, r.internal_marks
        elif result == "DETAINED" and att_pct[r.course_code] >= 60:
            log["corrections"].append(f"{sid}/{r.course_code}: DETAINED with attendance "
                                      f"{att_pct[r.course_code]:.1f}% -> recomputed as {expected}")
            result = expected
        elif result in ("PASS", "FAIL") and result != expected:
            log["corrections"].append(f"{sid}/{r.course_code}: {result} contradicts total {total} -> {expected}")
            result = expected
        backlogs += result in ("FAIL", "ABSENT", "DETAINED")
        res_rows.append({"student_id": sid, "course_code": r.course_code, "exam_session": SESSION,
                         "exam_type": "REGULAR", "internal_marks": r.internal_marks, "external_marks": external,
                         "total_marks": total, "max_marks": MAX_MARKS, "result": result})
    student = {"student_id": sid, "full_name": g.full_name, "programme": g.programme, "batch_year": g.batch_year,
               "current_semester": BATCHES[g.batch_year], "cgpa": f"{g.cgpa:.2f}", "active_backlogs": backlogs}
    return student, att_rows, res_rows


def generate(out_dir: Path, n: int, seed: int, batch_size: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    mock = settings.mock_llm
    log = {"generator": "mock-deterministic (MOCK_LLM=true)" if mock else settings.llm_model,
           "temperature": None if mock else 0.7, "seed": seed, "calls": 0, "retries": 0, "tokens": 0,
           "prompts": [], "corrections": [], "generated_at": datetime.now(timezone.utc).isoformat()}
    gen = _mock_batches(n, random.Random(seed)) if mock else _llm_batches(n, batch_size, log)

    tables = {k: [] for k in COLUMNS}
    tables["courses"] = [dict(c) for c in COURSES]
    for e in EDGE_STUDENTS:                                   # deterministic edge cases first
        g = GenStudent(full_name=e["full_name"], programme=e["programme"], batch_year=e["batch_year"],
                       cgpa=e["cgpa"], attendance=e["attendance"], results=e["results"])
        s, a, r = _to_rows(e["student_id"], g, {"corrections": []})
        tables["students"].append(s); tables["attendance"] += a; tables["results"] += r
    for i, g in enumerate(gen):
        s, a, r = _to_rows(f"S{1011 + i:04d}", g, log)
        tables["students"].append(s); tables["attendance"] += a; tables["results"] += r

    for name, cols in COLUMNS.items():
        with (out_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(tables[name])

    # login credentials: each student's initial password, in plain text
    with (out_dir / "credentials.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CRED_COLUMNS)
        w.writeheader()
        w.writerows({"student_id": s["student_id"], "password": initial_password(s["student_id"])}
                    for s in tables["students"])
    log["credentials"] = f"plain-text initial password {settings.initial_password!r}"

    viol = validate_tables(read_dir(out_dir), generated=True)
    report = format_report(viol, tables)
    (out_dir / "validation_report.txt").write_text(report + "\n")
    log["validation"] = {"errors": sum(v.severity == "error" for v in viol),
                         "warnings": sum(v.severity == "warning" for v in viol)}
    log["counts"] = {k: len(v) for k, v in tables.items()}
    (out_dir / "generation_log.json").write_text(json.dumps(log, indent=2))
    return log


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(settings.students_dir))
    ap.add_argument("--n", type=int, default=30, help="non-edge students to generate")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--batch-size", type=int, default=10)
    a = ap.parse_args()
    log = generate(Path(a.out), a.n, a.seed, a.batch_size)
    print(json.dumps({k: log[k] for k in ("generator", "calls", "retries", "counts", "validation")}, indent=2))
    print(f"{len(log['corrections'])} LLM output corrections logged in generation_log.json")


if __name__ == "__main__":
    main()
