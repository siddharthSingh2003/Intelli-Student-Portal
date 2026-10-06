"""M3: API contract (Section 6) and live ingestion."""
import json

from fastapi.testclient import TestClient

from api.main import app

CIRC = (b"CIRCULAR No. 2026/11\n1 Clause 2 of the attendance circular is superseded for students admitted in 2024.\n"
        b"2 A student must have a minimum attendance of 70% in each course to be permitted to appear in the "
        b"end-semester examination.\n")
META = {"doc_id": "LIVE-CIRC", "title": "Live circular", "issuer": "Dean", "authority_level": 2,
        "doc_type": "circular", "effective_from": "2026-10-01", "supersedes": "SAMPLE-CIRC-2026-08#2",
        "scope_programmes": "B.Tech", "scope_batches": "2024", "synthetic": "Y"}


BODY = {"question": "Am I eligible to appear in the end-semester exam for Data Structures?",
        "as_of_date": "2026-10-06"}


AUTO = (b"CIRCULAR No. EXAM/2026/14 (SAMPLE)\nOffice of the Controller of Examinations. Dated 25 November 2026.\n"
        b"Subject: Attendance relaxation for the 2024 batch.\n\n"
        b"1 With effect from 1 December 2026, clause 2 of the attendance circular is superseded for students "
        b"admitted in 2024.\n"
        b"2 A student must have a minimum attendance of 70% in each course to be permitted to appear in the "
        b"end-semester examination.\n")


def login(c, sid, password=None):
    password = password or ("Admin@123" if sid == "admin" else f"Pass@{sid}")
    r = c.post("/auth/login", json={"student_id": sid, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_login_is_required_and_scopes_data():
    with TestClient(app) as c:
        assert c.post("/ask", json=BODY).status_code == 401
        assert c.post("/ask", json=BODY, headers={"X-Student-Id": "S1004"}).status_code == 401   # header is not identity
        assert c.post("/ask", json=BODY, headers={"Authorization": "Bearer not-a-token"}).status_code == 401
        assert c.post("/auth/login", json={"student_id": "S1004", "password": "wrong"}).status_code == 401
        assert c.post("/auth/login", json={"student_id": "S0000", "password": "Pass@S0000"}).status_code == 401

        ok = c.post("/auth/login", json={"student_id": "s1004", "password": "Pass@S1004"}).json()
        assert ok["student"]["student_id"] == "S1004" and ok["token_type"] == "bearer" and ok["role"] == "student"
        s4, s5 = login(c, "S1004"), login(c, "S1005")
        assert c.get("/auth/me", headers=s5).json()["student"]["student_id"] == "S1005"

        r = c.post("/ask", json=BODY, headers=s4).json()
        assert r["tools_invoked"][0]["output"]["attendance_pct"] == 77.5            # S1004's own record
        assert c.get(f"/audit/{r['trace_id']}", headers=s4).status_code == 200
        assert c.get(f"/audit/{r['trace_id']}", headers=s5).status_code == 404      # not another student's trace
        assert c.get(f"/audit/{r['trace_id']}").status_code == 401
        other = c.post("/ask", json={"question": "What is the attendance of S1004?"}, headers=s5).json()
        assert other["answer_type"] == "refused"


def test_only_admin_adds_documents_and_metadata_is_extracted():
    with TestClient(app) as c:
        s4, admin = login(c, "S1004"), login(c, "admin")
        assert c.post("/auth/login", json={"student_id": "admin", "password": "Pass@admin"}).status_code == 401
        up = {"files": {"file": ("exam_circular.txt", AUTO)}, "data": {"authority_level": "2"}}
        assert c.post("/ingest", **up).status_code == 401
        note = {"file": ("note.txt", b"CIRCULAR No. EXAM/2026/14\nOffice of the Dean. Dated 1 September 2026.\n"
                                     b"1 A student must have a minimum attendance of 50% in each course to be "
                                     b"permitted to appear in the end-semester examination.\n")}
        mine = c.post("/ingest", files=note, data={"authority_level": "1"}, headers=s4)   # asks for level 1
        assert mine.status_code == 200, mine.text
        sm = mine.json()["metadata"]
        assert sm["authority_level"] == 5 and sm["doc_type"] == "unofficial"            # always unofficial
        assert sm["doc_id"] == "STU-S1004-EXAM-2026-14" and mine.json()["rules_extracted"] == 0
        assert c.post("/ingest", files=note, data={"metadata": json.dumps(META)}, headers=s4).status_code == 403
        assert c.post("/admin/rules", json=[], headers=s4).status_code == 403
        assert c.post("/ingest", files=up["files"], headers=admin).status_code == 422  # authority level is required

        later = {**BODY, "as_of_date": "2026-12-05"}       # the new circular takes effect on 1 December
        before = c.post("/ask", json=later, headers=s4).json()
        assert "not eligible" in before["answer"]
        res = c.post("/ingest", **up, headers=admin)
        assert res.status_code == 200, res.text
        m = res.json()["metadata"]
        # same reference number as the student's note, yet neither replaces the other
        assert m["doc_id"] == "EXAM-2026-14" and m["authority_level"] == 2 and m["doc_type"] == "circular"
        assert {"EXAM-2026-14", "STU-S1004-EXAM-2026-14"} <= {s["doc_id"] for s in c.get("/sources").json()}
        assert m["title"] == "CIRCULAR No. EXAM/2026/14 (SAMPLE): Attendance relaxation for the 2024 batch"
        assert m["issuer"] == "Office of the Controller of Examinations"
        assert m["effective_from"] == "2026-12-01" and m["effective_to"] == ""
        assert m["supersedes"] == "SAMPLE-CIRC-2026-08#2" and m["scope_batches"] == "2024"
        assert m["synthetic"] == "Y" and "admin" in m["provenance"]
        assert res.json()["rules_extracted"] == 1 and res.json()["extracted_by"]["authority_level"] == "admin"
        after = c.post("/ask", json=later, headers=s4).json()
        assert "You are eligible" in after["answer"]            # the extracted metadata drives precedence
        assert "not eligible" in c.post("/ask", json=BODY, headers=s4).json()["answer"]   # not yet in October

        # an admin has no student records, and may read any audit trace
        mine = c.post("/ask", json={"question": "What is my attendance?"}, headers=admin).json()
        assert mine["answer_type"] == "refused"
        assert c.get(f"/audit/{after['trace_id']}", headers=admin).status_code == 200


def test_change_password():
    with TestClient(app) as c:
        h = login(c, "S1009")
        bad = c.post("/auth/change-password", json={"current_password": "nope", "new_password": "new-secret-1"}, headers=h)
        assert bad.status_code == 403
        assert c.post("/auth/change-password", headers=h,
                      json={"current_password": "Pass@S1009", "new_password": "new-secret-1"}).status_code == 200
        assert c.post("/auth/login", json={"student_id": "S1009", "password": "Pass@S1009"}).status_code == 401
        login(c, "S1009", "new-secret-1")


def test_contract_and_live_ingest():
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
        body, s4, s5, admin = BODY, login(c, "S1004"), login(c, "S1005"), login(c, "admin")
        r = c.post("/ask", json=body, headers=s4).json()
        assert set(r) >= {"trace_id", "answer", "answer_type", "citations", "tools_invoked", "applied_rules",
                          "conflicts_detected", "explanation", "as_of_date"}
        assert r["answer_type"] == "calculated" and "not eligible" in r["answer"]
        assert c.get(f"/audit/{r['trace_id']}", headers=s4).json()["trace_id"] == r["trace_id"]

        res = c.post("/ingest", files={"file": ("c.txt", CIRC)}, data={"metadata": json.dumps(META)},
                     headers=admin).json()
        assert res["status"] == "indexed" and res["chunks_indexed"] > 0 and res["rules_extracted"] == 1
        after = c.post("/ask", json=body, headers=s4).json()
        assert "You are eligible" in after["answer"]           # batch 2024 now on 70%
        other = c.post("/ask", json=body, headers=s5).json()
        assert other["applied_rules"][0]["source_doc_id"] == "SAMPLE-CIRC-2026-08"   # batch 2023 unchanged
        assert any(s["doc_id"] == "LIVE-CIRC" for s in c.get("/sources").json())
