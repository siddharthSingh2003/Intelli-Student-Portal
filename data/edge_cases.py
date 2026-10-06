"""Single source of truth for the synthetic dataset design (M2).

Used by: the generator (prompt + deterministic injection), the validator,
the data card and the evaluation set. Edge-case students are fixed so that
eval expectations are stable and hand-verifiable.
"""
from __future__ import annotations

PROGRAMMES = ["B.Tech CSE", "B.Tech ECE"]
BATCHES = {2023: 7, 2024: 5}          # batch_year -> current_semester
INTERNAL_MAX, EXTERNAL_MAX, MAX_MARKS = 40, 60, 100
PASS_PCT = 40                          # pass mark used by the validator (cited from your regulations)
SESSION = "2025-DEC"

COURSES = [
    {"course_code": "CS201", "course_name": "Data Structures", "programme": "B.Tech CSE", "semester": 3, "credits": 4},
    {"course_code": "CS202", "course_name": "Database Management Systems", "programme": "B.Tech CSE", "semester": 3, "credits": 4},
    {"course_code": "MA201", "course_name": "Mathematics-III", "programme": "B.Tech CSE", "semester": 3, "credits": 3},
    {"course_code": "EC201", "course_name": "Signals and Systems", "programme": "B.Tech ECE", "semester": 3, "credits": 4},
    {"course_code": "EC202", "course_name": "Analog Electronics", "programme": "B.Tech ECE", "semester": 3, "credits": 4},
    {"course_code": "MA202", "course_name": "Mathematics-III (ECE)", "programme": "B.Tech ECE", "semester": 3, "credits": 3},
]


def courses_for(programme: str) -> list[dict]:
    return [c for c in COURSES if c["programme"] == programme]


def _att(code, held, att):
    return {"course_code": code, "classes_held": held, "classes_attended": att}


def _res(code, internal, external, result):
    return {"course_code": code, "internal_marks": internal, "external_marks": external, "result": result}


# Each edge student exercises one rule boundary. "why" goes straight into the data card.
EDGE_STUDENTS = [
    {"student_id": "S1001", "full_name": "Aarav Mehta", "programme": "B.Tech CSE", "batch_year": 2024, "cgpa": 7.8,
     "why": "CS201 attendance exactly 75.0% (at the 75% regulation threshold)",
     "attendance": [_att("CS201", 40, 30), _att("CS202", 40, 36), _att("MA201", 40, 35)],
     "results": [_res("CS201", 30, 45, "PASS"), _res("CS202", 32, 44, "PASS"), _res("MA201", 28, 40, "PASS")]},
    {"student_id": "S1002", "full_name": "Diya Sharma", "programme": "B.Tech CSE", "batch_year": 2024, "cgpa": 8.2,
     "why": "CS201 attendance 72.5% (one class below 75%)",
     "attendance": [_att("CS201", 40, 29), _att("CS202", 40, 38), _att("MA201", 40, 37)],
     "results": [_res("CS201", 31, 48, "PASS"), _res("CS202", 34, 50, "PASS"), _res("MA201", 30, 46, "PASS")]},
    {"student_id": "S1003", "full_name": "Kabir Rao", "programme": "B.Tech CSE", "batch_year": 2024, "cgpa": 7.1,
     "why": "CS201 attendance exactly 80.0% (at the 80% circular threshold)",
     "attendance": [_att("CS201", 40, 32), _att("CS202", 40, 34), _att("MA201", 40, 36)],
     "results": [_res("CS201", 27, 40, "PASS"), _res("CS202", 29, 41, "PASS"), _res("MA201", 25, 38, "PASS")]},
    {"student_id": "S1004", "full_name": "Ishita Verma", "programme": "B.Tech CSE", "batch_year": 2024, "cgpa": 6.8,
     "why": "CS201 attendance 77.5% (one class below 80%, above 75%)",
     "attendance": [_att("CS201", 40, 31), _att("CS202", 40, 35), _att("MA201", 40, 33)],
     "results": [_res("CS201", 26, 39, "PASS"), _res("CS202", 28, 37, "PASS"), _res("MA201", 24, 36, "PASS")]},
    {"student_id": "S1005", "full_name": "Rohan Iyer", "programme": "B.Tech CSE", "batch_year": 2023, "cgpa": 7.2,
     "why": "FAILED CS201 with 39/100 (one mark below the 40% pass mark); 1 active backlog",
     "attendance": [_att("CS201", 40, 34), _att("CS202", 40, 36), _att("MA201", 40, 35)],
     "results": [_res("CS201", 22, 17, "FAIL"), _res("CS202", 30, 42, "PASS"), _res("MA201", 27, 41, "PASS")]},
    {"student_id": "S1006", "full_name": "Ananya Gupta", "programme": "B.Tech CSE", "batch_year": 2024, "cgpa": 6.9,
     "why": "ABSENT in MA201 end-semester exam (external = 0); 1 active backlog",
     "attendance": [_att("CS201", 40, 33), _att("CS202", 40, 34), _att("MA201", 40, 31)],
     "results": [_res("CS201", 28, 40, "PASS"), _res("CS202", 27, 38, "PASS"), _res("MA201", 25, 0, "ABSENT")]},
    {"student_id": "S1007", "full_name": "Vihaan Malhotra", "programme": "B.Tech CSE", "batch_year": 2023, "cgpa": 5.4,
     "why": "DETAINED in CS202 (attendance 50%); detained students cannot take the supplementary exam",
     "attendance": [_att("CS201", 40, 33), _att("CS202", 40, 20), _att("MA201", 40, 32)],
     "results": [_res("CS201", 22, 26, "PASS"), _res("CS202", 10, 0, "DETAINED"), _res("MA201", 21, 25, "PASS")]},
    {"student_id": "S1008", "full_name": "Meera Nair", "programme": "B.Tech ECE", "batch_year": 2023, "cgpa": 5.9,
     "why": "Multiple backlogs: FAILED all three ECE courses (3 active backlogs)",
     "attendance": [_att("EC201", 40, 31), _att("EC202", 40, 32), _att("MA202", 40, 30)],
     "results": [_res("EC201", 18, 15, "FAIL"), _res("EC202", 16, 20, "FAIL"), _res("MA202", 14, 19, "FAIL")]},
    {"student_id": "S1009", "full_name": "Arjun Pillai", "programme": "B.Tech ECE", "batch_year": 2024, "cgpa": 6.5,
     "why": "CGPA exactly 6.50 (at the placement cut-off), 0 backlogs",
     "attendance": [_att("EC201", 40, 34), _att("EC202", 40, 35), _att("MA202", 40, 33)],
     "results": [_res("EC201", 25, 30, "PASS"), _res("EC202", 24, 31, "PASS"), _res("MA202", 22, 28, "PASS")]},
    {"student_id": "S1010", "full_name": "Sara Khan", "programme": "B.Tech ECE", "batch_year": 2024, "cgpa": 8.1,
     "why": "EC201 total exactly 40/100 (at the pass mark) -> PASS",
     "attendance": [_att("EC201", 40, 38), _att("EC202", 40, 37), _att("MA202", 40, 39)],
     "results": [_res("EC201", 20, 20, "PASS"), _res("EC202", 34, 50, "PASS"), _res("MA202", 33, 49, "PASS")]},
]
