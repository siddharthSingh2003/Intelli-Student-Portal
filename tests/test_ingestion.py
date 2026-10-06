"""M1: chunking keeps clause numbers; rule extraction finds thresholds; level 5 sets no rules."""
from ingestion.chunker import chunk_pages
from ingestion.loader import PageText
from shared.schemas import DocMetadata
from tools.rule_extractor import extract_rules

TEXT = ("7 ATTENDANCE\n7.1 Attendance is recorded.\n7.2 Minimum attendance. A student must have a minimum "
        "attendance of 75% in each course.\n8.2 Pass mark. A student must secure at least 40% of the total marks "
        "in a course to pass that course.")
META = DocMetadata(doc_id="D", title="t", issuer="i", authority_level=1, doc_type="regulation",
                   effective_from="2024-07-01")


def test_section_chunks_carry_clause_numbers():
    chunks = chunk_pages([PageText(1, TEXT)], "D", "section", 900, 100)
    assert [c.section for c in chunks] == ["7", "7.1", "7.2", "8.2"]


def test_rule_extraction():
    rules = {r["parameter"]: r for r in extract_rules(chunk_pages([PageText(1, TEXT)], "D"), META)}
    assert rules["min_attendance_pct"]["value"] == "75" and rules["min_attendance_pct"]["source_section"] == "7.2"
    assert rules["pass_min_total_pct"]["value"] == "40"


def test_unofficial_sources_never_create_rules():
    m = META.model_copy(update={"authority_level": 5, "doc_type": "unofficial"})
    assert extract_rules(chunk_pages([PageText(1, TEXT)], "D"), m) == []
