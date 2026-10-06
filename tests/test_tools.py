"""M2: deterministic tools and data validation on the edge-case students."""
from datetime import date

from data.validate import validate_tables
from tools.eligibility import (check_exam_eligibility, check_placement_eligibility,
                               check_supplementary_eligibility, classes_needed)

# dated before the live-ingest test circular (2026-10-01) so test order does not matter
TODAY, BEFORE = date(2026, 9, 20), date(2026, 7, 15)


def test_attendance_exactly_at_threshold_is_eligible():
    assert check_exam_eligibility("S1003", TODAY, "CS201")["result"] == "ELIGIBLE"      # 80.0% vs 80
    assert check_exam_eligibility("S1001", BEFORE, "CS201")["result"] == "ELIGIBLE"     # 75.0% vs 75


def test_one_class_below_threshold():
    out = check_exam_eligibility("S1004", TODAY, "CS201")
    assert out["result"] == "NOT_ELIGIBLE" and out["classes_needed"] == 5
    assert out["rule_id"] == "ATT-MIN@SAMPLE-CIRC-2026-08#2"


def test_supplementary_absent_vs_detained():
    assert check_supplementary_eligibility("S1006", TODAY, "MA201")["result"] == "ELIGIBLE"
    assert check_supplementary_eligibility("S1007", TODAY, "CS202")["result"] == "NOT_ELIGIBLE"


def test_placement_cutoff_and_what_if():
    assert check_placement_eligibility("S1009", TODAY)["result"] == "ELIGIBLE"           # CGPA exactly 6.5
    assert check_placement_eligibility("S1005", TODAY)["result"] == "NOT_ELIGIBLE"       # 1 backlog
    assert check_placement_eligibility("S1005", TODAY, ["CS201"])["result"] == "ELIGIBLE"


def test_classes_needed_formula():
    assert classes_needed(29, 40, 75) == 4 and classes_needed(30, 40, 75) == 0


def test_validator_catches_logical_errors():
    t = {"students": [{"student_id": "S9001", "full_name": "X Y", "programme": "B.Tech CSE", "batch_year": "2024",
                       "current_semester": "5", "cgpa": "11", "active_backlogs": "0"}],
         "courses": [{"course_code": "CS201", "course_name": "DS", "programme": "B.Tech CSE", "semester": "3",
                      "credits": "4"}],
         "attendance": [{"student_id": "S9001", "course_code": "CS201", "classes_held": "40",
                         "classes_attended": "41"}],
         "results": [{"student_id": "S9001", "course_code": "CS201", "exam_session": "2025-DEC",
                      "exam_type": "REGULAR", "internal_marks": "20", "external_marks": "10", "total_marks": "35",
                      "max_marks": "100", "result": "PASS"}]}
    rules = {v.rule for v in validate_tables(t, generated=True)}
    assert {"cgpa_range", "attended_le_held", "total_eq_sum", "result_consistent", "reserved_id"} <= rules
