"""Streamlit UI (M4). Minimal by design: the guide scores the UI only for usability."""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import requests
import streamlit as st

# 127.0.0.1, not localhost: on Windows each localhost request first waits ~2s on IPv6
API = os.getenv("API_URL", "http://127.0.0.1:8000")
TYPE_LABEL = {"retrieved_fact": ("Retrieved fact", "blue"), "calculated": ("Calculated by tool", "green"),
              "not_found": ("Not found", "gray"), "clarification_needed": ("Needs clarification", "orange"),
              "refused": ("Refused", "red"), "conflict_flagged": ("Conflict flagged", "violet")}

st.set_page_config(page_title="Student Services Assistant", page_icon="🎓", layout="wide")


@st.cache_resource
def _http() -> requests.Session:
    return requests.Session()   # keep-alive: one connection reused across reruns


HTTP = _http()


def logout(message: str = "") -> None:
    st.session_state.clear()
    st.session_state.flash = message
    st.rerun()


def api(method: str, path: str, **kw) -> requests.Response:
    """Authenticated API call. An expired or rejected token sends the user back to the login page."""
    r = HTTP.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {st.session_state.token}"}, **kw)
    if r.status_code == 401:
        logout("Your session has expired. Please log in again.")
    return r


# Streamlit re-runs this whole script on every interaction, so anything that does not
# change between questions is cached instead of being fetched again each time.
@st.cache_data(ttl=30, show_spinner=False)
def health() -> dict:
    return HTTP.get(f"{API}/health", timeout=5).json()


@st.cache_data(ttl=300, show_spinner=False)
def sources() -> list:
    return HTTP.get(f"{API}/sources", timeout=10).json()


def render_answer(resp: dict) -> None:
    label, colour = TYPE_LABEL.get(resp["answer_type"], (resp["answer_type"], "gray"))
    st.markdown(f":{colour}-background[{label}]  trace `{resp['trace_id']}`")
    st.write(resp["answer"])
    if resp.get("explanation"):
        st.caption(resp["explanation"])
    for a in resp.get("assumptions", []):
        st.info(f"Assumption: {a}")
    for u in resp.get("upcoming_changes", []):
        st.warning(f"Upcoming change: {u}")
    if resp["citations"]:
        with st.expander(f"Citations ({len(resp['citations'])})"):
            st.dataframe(pd.DataFrame(resp["citations"]), hide_index=True)
    if resp["tools_invoked"]:
        with st.expander(f"Tools invoked ({len(resp['tools_invoked'])})"):
            st.json(resp["tools_invoked"])
    if resp["conflicts_detected"]:
        with st.expander(f"Conflicts resolved ({len(resp['conflicts_detected'])})"):
            st.json(resp["conflicts_detected"])


# ---- login gate: nothing below this block runs without a token ----
if "token" not in st.session_state:
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.title("🎓 Student Services Assistant")
        flash = st.session_state.pop("flash", "")
        if flash:
            st.warning(flash)
        with st.form("login"):
            sid = st.text_input("Student ID or admin username", placeholder="e.g. S1001")
            pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary", use_container_width=True):
                try:
                    r = HTTP.post(f"{API}/auth/login", json={"student_id": sid.strip(), "password": pwd}, timeout=15)
                except requests.RequestException:
                    st.error(f"API not reachable at {API}")
                else:
                    if r.ok:
                        st.session_state.token = r.json()["access_token"]
                        st.session_state.user = {k: r.json()[k] for k in ("role", "name", "student")}
                        st.rerun()
                    st.error("Incorrect ID or password." if r.status_code in (401, 422) else r.text)
    st.stop()

user = st.session_state.user
is_admin, student = user["role"] == "admin", user["student"]
with st.sidebar:
    st.header(user["name"])
    st.caption("Administrator" if is_admin else
               f"{student['student_id']} · {student['programme']} · batch {student['batch_year']}")
    if st.button("Log out", use_container_width=True):
        logout()
    as_of = st.date_input("Answer as of", value=date.today())
    try:
        h = health()
        st.caption(f"API {h['status']} · {h['vector_store'].get('chunks', '?')} chunks · "
                   f"LLM {h['llm'].get('status')}")
    except Exception:  # noqa: BLE001
        st.error(f"API not reachable at {API}")

# only an admin gets the "Add a document" tab; the API enforces the same rule (403 for students)
if is_admin:
    ask_tab, ingest_tab, sources_tab, audit_tab = st.tabs(["Ask", "Add a document", "Sources", "Audit"])
else:
    ask_tab, sources_tab, audit_tab = st.tabs(["Ask", "Sources", "Audit"])
    ingest_tab = None

with ask_tab:
    st.title("Ask about university rules" if is_admin else "Ask about university rules or your records")
    if "history" not in st.session_state:
        st.session_state.history = []
    earlier = list(st.session_state.history)
    q = st.chat_input("e.g. What is the minimum attendance for end-semester exams?" if is_admin else
                      "e.g. Am I eligible for the supplementary exam in Mathematics?")
    if q:
        # show the question straight away and keep a visible "working" state while the model answers
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Checking the rules and your records..."):
                    r = api("post", "/ask", json={"question": q, "as_of_date": as_of.isoformat()}, timeout=300)
                    r.raise_for_status()
                render_answer(r.json())
                st.session_state.history.append((q, r.json()))
            except requests.RequestException as e:
                st.error(f"Request failed: {e}")
    for question, resp in reversed(earlier):
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            render_answer(resp)

LEVELS = {1: "1 - Regulation / ordinance", 2: "2 - Circular / office order", 3: "3 - Departmental notice",
          4: "4 - FAQ / help desk", 5: "5 - Unofficial (informational only)"}
SOURCE_LABEL = {"llm": "read by the model, checked against the text", "pattern": "found by pattern",
                "default": "not stated in the document - default used", "admin": "set by you"}

if ingest_tab is not None:
    with ingest_tab:
        st.subheader("Add a document while the system is running")
        st.caption("Choose the authority level. The title, issuer, dates, scope and what the document supersedes "
                   "are read from the document itself.")
        with st.form("ingest"):
            up = st.file_uploader("Document", type=["pdf", "txt", "md", "png", "jpg"])
            level = st.selectbox("Authority level (Annex A)", list(LEVELS), index=1, format_func=LEVELS.get)
            submitted = st.form_submit_button("Add document", type="primary")
        if submitted:
            if not up:
                st.error("Choose a file first.")
            else:
                with st.spinner("Reading the document and extracting its metadata..."):
                    r = api("post", "/ingest", files={"file": (up.name, up.getvalue())},
                            data={"authority_level": str(level)}, timeout=600)
                if not r.ok:
                    st.error(r.json().get("detail", r.text))
                else:
                    res = r.json()
                    sources.clear()
                    st.success(f"Added {res['doc_id']}: {res['chunks_indexed']} chunks indexed, "
                               f"{res['rules_extracted']} rule(s) extracted. It is searchable now.")
                    how = res.get("extracted_by") or {}
                    st.caption("Metadata stored in the Source Register - please check it:")
                    st.dataframe(pd.DataFrame([{"field": k, "value": v, "source": SOURCE_LABEL.get(how.get(k), "")}
                                               for k, v in res["metadata"].items()]), hide_index=True)

with sources_tab:
    st.subheader("Source Register")
    try:
        st.dataframe(pd.DataFrame(sources()), hide_index=True)
    except Exception as e:  # noqa: BLE001
        st.error(str(e))

with audit_tab:
    st.subheader("Look up an audit record")
    tid = st.text_input("trace_id")
    if tid:
        r = api("get", f"/audit/{tid.strip()}", timeout=10)
        st.json(r.json()) if r.ok else st.error("No audit record you can see with that trace_id.")