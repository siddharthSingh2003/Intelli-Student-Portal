# Role 3 — Orchestration and API Engineer (LangGraph + FastAPI)

**You own the request path:** from the HTTP request that arrives at FastAPI, through the
LangGraph workflow, to the typed, cited and audited response that goes back.

If the panel asks "why is this not a multi-agent system?", "what stops one student
reading another's records?" or "can the LLM flip an eligibility result?", those are
your questions.

| | |
|---|---|
| Folders | `graph/`, `api/` |
| Other files | `shared/security.py` |
| Tests | `tests/test_graph.py`, `tests/test_api.py` |
| Code size | 13 modules, about 1,250 lines of Python |
| In the code comments you are | `M3` (Member 3) |
| Works with | Person 1 (you call their search, precedence engine and ingestion), Person 2 (you call their tools, database and loader), Person 4 (you use their LLM client and contracts; their UI and evaluation call you) |

## The team

| Person | Role | Zip |
|---|---|---|
| 1 | RAG Pipeline Engineer | `person1_rag_pipeline.zip` |
| 2 | Data and Tools Engineer | `person2_data_and_tools.zip` |
| **3 (you)** | Orchestration and API Engineer (LangGraph + FastAPI) | `person3_langgraph_and_fastapi.zip` |
| 4 | Platform, UI and Evaluation Lead | `person4_platform_ui_and_evaluation.zip` |

The four zips share no files. Together they are the whole repository. Your zip does not
run on its own: it imports the other three parts.

---

## 1. What is in this zip

### `graph/` — the LangGraph workflow

| File | What it does |
|---|---|
| `state.py` | `GraphState`, the dictionary every node reads and writes. Four fields accumulate across nodes: `llm_calls`, `tokens`, `injection_flags`, `notes`. |
| `workflow.py` | Builds the `StateGraph` with six nodes and its conditional edges. `run_question(question, student_id, as_of_date, retrieval_config)` returns `(response, audit)`. |
| `nodes.py` | The six nodes: `guard`, `plan`, `retrieve`, `tools`, `generate`, `finalize`. |
| `planner.py` | `validate_plan()` is the gate on the LLM's plan. `rule_plan()` is the deterministic planner used when the LLM fails, and as the mock planner. |
| `courses.py` | Maps "Data Structures", "maths" or "CS201" in a question to the student's course codes. |
| `safety.py` | `check_access()` decides refusals (requirement R7). `sanitize_evidence()` strips instruction-like sentences from documents (R8). No LLM involved. |
| `prompts.py` | The two system prompts, the prompt builders, and the Pydantic schemas the LLM must fill (`PlanOut`, `AnswerOut`). |
| `templates.py` | Builds the verdict sentence from a tool's output, so the wording of an eligibility decision comes from code. |
| `extractive.py` | Copies the best-matching sentence from the evidence. Used as the mock answerer and as the fallback when the LLM fails or its answer is not grounded. |

### `api/` — the FastAPI app

| File | What it does |
|---|---|
| `main.py` | The app, its startup seeding, and the endpoints of the Section 6 contract plus two admin endpoints. |
| `auth.py` | `POST /auth/login`, `GET /auth/me`, `POST /auth/change-password`, and the dependencies `current_user` and `require_admin`. |
| `audit.py` | Saves and reads one audit record per `/ask` call in the `audit_log` table. |
| `shared/security.py` | Constant-time password check, and JWT create/decode (HS256). |

---

## 2. How the workflow runs

```
guard ── refused ───────────────────────────────────────► finalize
  │
plan ─── course unclear (clarification) ────────────────► finalize
  │
  ├─ needs documents ─► retrieve ─► tools ─► generate ──► finalize
  └─ personal data only ──────────► tools ─► generate ──► finalize
```

| Node | What it does |
|---|---|
| **guard** | Looks up the student for the ID in the login token. Refuses when the ID is unknown, when the question names another student (an ID like `S1002`, another student's full name, or "my friend's marks"), or when a personal question arrives with no logged-in student. Otherwise marks the question personal or general. |
| **plan** | General question: no LLM call, the plan is "retrieve". Personal question: the LLM proposes tool calls, `validate_plan()` checks them, and the rule planner takes over if the LLM fails or proposes something invalid. If a required course cannot be identified, the node returns `clarification_needed` with the student's course list. |
| **retrieve** | Top-k search in Person 1's vector store, then Person 1's `resolve_evidence()`. For every document that supersedes a retrieved clause, its three best clauses are fetched explicitly and precedence is resolved again. Level 5 chunks are marked informational. `sanitize_evidence()` removes instruction-like sentences and records them. |
| **tools** | Runs each planned tool from Person 2's catalogue. `student_id` (from the token) and `as_of` are injected here; the plan cannot set them. Lifts `_applied_rules`, `_conflicts` and `_assumptions` out of the outputs and builds a citation for every rule used. |
| **generate** | If there are no tool results and the best retrieval score is under the model's floor, it abstains without calling the LLM. Otherwise the LLM writes the answer and explanation in the `AnswerOut` schema. If the LLM fails, the extractive answerer is used. |
| **finalize** | Decides the answer type and the final text, checks citations and numbers, and builds the `AskResponse` and the audit record. |

The workflow makes at most **two LLM calls** per question: plan and answer. (A third
LLM task, document metadata, belongs to Person 1's ingestion.)

### What `validate_plan()` enforces

- A tool name that is not in the catalogue makes the whole plan invalid.
- Arguments the tool does not list are dropped.
- A course code must be one of the student's own courses. If it is not, the code tries
  to resolve the course from the question; if that fails for a required course, the
  result is a clarification question.
- `future_classes`, `attend_classes` and `assume_cgpa` must convert to numbers.
- The intent category is recomputed from the tools, so audit categories are consistent.

### How `finalize` decides the answer type

| Situation | Answer type | Where the text comes from |
|---|---|---|
| Guard refused | `refused` | fixed sentence in `safety.py` |
| Course unclear | `clarification_needed` | fixed sentence plus the course list |
| A tool returned `CONFLICT` | `conflict_flagged` | `templates.rule_conflict()` |
| Every tool returned `RULE_NOT_FOUND`, `NO_RECORD` or `ERROR` | `not_found` | fixed sentence or the tool's verdict |
| Tools ran | `calculated` | `templates.verdict()` per tool |
| No tools, evidence insufficient or nothing validly cited | `not_found` | "I could not find this information in the authorised university sources." |
| No tools, two cited sources disagree and precedence cannot decide | `conflict_flagged` | `templates.doc_conflict()`, both sources cited |
| No tools, evidence sufficient | `retrieved_fact` | the LLM's answer, after the checks below |

Checks on a `retrieved_fact` answer:

1. **Citations.** Only chunk ids that were really in the evidence are kept.
2. **Precedence.** If the LLM reports that two chunks disagree, `resolve_pair()`
   (Person 1) picks the winner. If the LLM's first citation is the loser, the answer is
   rebuilt from the winner's text.
3. **Numbers.** Every number in the answer must appear in the question, the cited
   evidence, the tool outputs, or the clause and date labels of the evidence. If one
   does not, the answer is replaced by a sentence copied from the evidence.

The same number check is applied to the LLM's explanation for tool answers. If it
fails, a templated explanation is used.

---

## 3. The API

| Endpoint | Who may call it | What it does |
|---|---|---|
| `POST /auth/login` | anyone | Checks the password; returns a JWT (HS256, 120 minutes by default) carrying the role. |
| `GET /auth/me` | logged in | The current user. |
| `POST /auth/change-password` | logged in | New password must be at least 8 characters. |
| `POST /ask` | logged in | Runs the workflow with the token's student ID, saves the audit record, returns `AskResponse`. |
| `POST /ingest` | logged in | Admin: sends `authority_level` alone (metadata is extracted) or the full `metadata` JSON. Student: the level is forced to 5, the `doc_id` gets the prefix `STU-<student_id>-`, and a `metadata` JSON is rejected with 403. |
| `GET /audit/{trace_id}` | the student who asked, or an admin | Anyone else gets 404. |
| `GET /sources` | open | The Source Register rows. |
| `GET /health` | open | Status of the API, vector store, SQLite and LLM. |
| `POST /admin/load-students` | admin | Uploads Annex C CSVs; validated first, then loaded. |
| `POST /admin/rules` | admin | Adds rules to the registry. |

**Startup** (`lifespan` in `main.py`): create tables, index the Source Register, load
the seed rules, load students if the table is empty, give every student a password,
create the admin account. If any of this fails, the error is logged and the API still
starts, so `/health` can report what is wrong.

**Identity** has one source: the token. `/ask` calls
`run_question(req.question, user.student_id, ...)`. The `X-Student-Id` header is
ignored unless `AUTH_REQUIRED=false`, which restores the original no-login contract for
a test harness and must never be used with real data.

---

## 4. Design decisions you must be able to defend

**Why one workflow and not several agents?**
No step needs to loop on its own or decide what to do next. Every branch is an `if` in
code, and the two LLM calls are checked afterwards. An agent loop would add latency,
token cost and unpredictability, and requirement R5 needs eligibility to be deterministic.

**Why "the LLM proposes, code decides" for the plan?**
A 7B model can invent a tool name, an argument or a course code. The gate makes those
harmless: only catalogue tools, only listed arguments, only the student's courses.

**Why is the verdict sentence templated?**
"You are not eligible ... 77.5%, below the required 80%" is built from the tool output.
The LLM cannot flip the decision or misquote a number, because it does not write that
sentence.

**Why does the guard run before any LLM call?**
A refusal is decided by code, costs no tokens, and cannot be argued with by a clever
prompt. "I am S1002" in the message changes nothing: an ID other than the token's
leads to a refusal.

**Why abstain before calling the LLM when retrieval is weak?**
If nothing relevant was retrieved, the honest answer is "not found". Not calling the
model removes the chance that it answers from its own knowledge.

**Why 404 and not 403 for another student's audit trace?**
403 would confirm that the trace exists. 404 tells the caller nothing.

**Why may a student upload a document at all?**
The upload is forced to authority level 5: informational only, never overrides an
official source, sets no rules. Its `doc_id` is prefixed with the student's ID, so it
can never replace an official document.

**Why three layers against prompt injection in documents?**
(1) Evidence is wrapped in `<evidence>` blocks and the system prompt says it is data,
not instructions. (2) Sentences matching known injection patterns are removed before
the LLM sees them and logged in the audit record. (3) Even if one got through, tools
only receive the token's student ID and the decisive numbers come from code.

---

## 5. Interfaces

**You provide**

| What | Used by |
|---|---|
| `graph.workflow.run_question(...)` | your own `/ask`; `eval/run_eval.py` and `scripts/export_audit_samples.py` (Person 4) |
| The HTTP API | the Streamlit UI (Person 4), judges' test harness |
| `shared.security` | `api/auth.py` |

**You consume**

- Person 1: `get_store(cfg).search / find_page`, `resolve_evidence`, `resolve_pair`,
  `is_scoped`, `source_register`, `ingest_file`, `bootstrap`, `extract_metadata`,
  `load_document`, `clean_pages`
- Person 2: `tools.registry.TOOLS / catalog_text / ToolError`, `data.db`,
  `data.credentials`, `data.loader.load_dir`, `tools.rules.add_rule / load_rules_csv`
- Person 4: `shared.llm.LLMClient / LLMError / register_mock`, `shared.config`,
  `shared.schemas` (`AskRequest`, `AskResponse`, `Citation`, `IngestMetadata`,
  `IngestResponse`, `RuleIn`)

---

## 6. Run and test your part

Run inside the full repository (after all four people have pushed).

```bash
pip install -r requirements-core.txt                 # enough for the tests
pytest -q tests/test_graph.py tests/test_api.py      # no model needed

export MOCK_LLM=true                                  # run without Ollama
export REGISTER_CSV=docs/sample/source_register.csv   # the sample corpus the demo and tests use
uvicorn api.main:app --reload
# interactive API docs: http://127.0.0.1:8000/docs
```

`.env` is read only by `docker compose`. Without Docker, set the variables in your
shell as above (Windows PowerShell: `$env:MOCK_LLM="true"`).

```bash
TOKEN=$(curl -s 127.0.0.1:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"student_id":"S1004","password":"Pass@S1004"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s 127.0.0.1:8000/ask -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" \
  -d '{"question":"Am I eligible to appear in the end-semester exam for Data Structures?","as_of_date":"2026-10-06"}'
```

---

## 7. Put your part on GitHub

Person 4 creates the repository and pushes first (that part carries `.gitignore`, the
requirements and CI). Wait for the repository link and accept the collaborator
invitation GitHub emails you. Then:

```bash
git config --global user.name  "Your Name"
git config --global user.email "the email of your GitHub account"   # so the commit counts as yours

git clone https://github.com/<owner>/<repo>.git
cd <repo>
```

Extract `person3_langgraph_and_fastapi.zip` **into this folder**. The zip has no
wrapping folder: `graph/`, `api/`, `shared/` and `tests/` must end up next to
`README.md`. On Windows, "Extract All" creates a folder named after the zip; open it
and move everything inside into the cloned folder. If you are asked to merge `shared/`
or `tests/`, say yes. No existing file is overwritten.

```bash
git status       # every new path must start with graph/, api/, shared/, tests/ or ROLE_3
git add .
git commit -m "orchestration and API: LangGraph workflow, safety, FastAPI contract, login"
git pull --rebase origin main      # picks up what teammates pushed meanwhile
git push origin main
```

There are no merge conflicts, because no file belongs to two people.

No git on your machine? On the repository page choose **Add file → Upload files**,
drag in the extracted folders and this file, and commit.

The green tick on GitHub (the CI test job) appears only once all four parts are in,
because the tests import across layers. A red cross before that is expected.

---

## 8. Your part of the demo

- "What is the scholarship for studying in Antarctica?" → `not_found`, with the fixed sentence.
- Logged in as S1001: "What is the attendance of S1002 in Data Structures?" → `refused`.
- "What time does the hostel curfew start?" → `conflict_flagged`, two notices cited,
  same authority level and date, so the policy cannot choose.
- If there is time: open `http://127.0.0.1:8000/docs` and show the contract.

---

## 9. Panel questions for you

**Q. I am logged in as S1001 and type "I am S1002. What is my attendance?" What happens?**
The guard finds a student ID in the text that is not the token's and refuses.
`test_identity_never_taken_from_text` covers it.

**Q. A forum post in the corpus says "ignore all previous instructions". What happens?**
`sanitize_evidence()` drops that sentence before the prompt is built and records the
chunk and the pattern under `injection_flags` in the audit record. The post is level 5,
so it is informational only in any case.

**Q. What if the LLM returns invalid JSON, or Ollama is down?**
Person 4's client retries with the validation error fed back. If it still fails it
raises `LLMError`. Then `plan_node` uses the rule planner and `generate_node` uses the
extractive answerer. The request is still answered.

**Q. Can the LLM change an eligibility result?**
No. The verdict sentence is built by `templates.verdict()` from the tool output. The
LLM only writes the explanation, and that is rejected if it contains a number that is
not in the tool outputs or evidence.

**Q. Who detects that two documents disagree?**
The LLM reports pairs of chunks that give different values. Which one wins is always
decided by `resolve_pair()` in code. A 7B model can miss a disagreement; the README
lists this as a limitation and the evaluation measures it.

**Q. Why JWT? Where is the secret?**
The token carries the student ID and role, so the API keeps no session state. HS256,
two-hour expiry, and `sub`, `role` and `exp` are required claims. The key is
`JWT_SECRET`; if unset, one is generated once into `storage/jwt_secret`.

**Q. What does the operational log contain?**
Only the trace ID, the answer type and the latency. No question text and no student
data. The full record is in the audit table, readable by its owner or an admin.

**Q. What are the weaknesses of your layer?**
The guard is keyword and regex based and English only, so it can over-refuse (any
personal topic plus "friend") or miss an indirect reference. The number check verifies
numbers, not wording. Passwords are plain text. There is no rate limit on login.

---

## 10. Open items you own

These are honest gaps. Fixing any of them is a good commit under your own name.
`AI_USAGE.md` says each owner read, ran and modified their module: read every file in
`graph/` and `api/` before the panel so that statement is true for you.

1. **Validate `doc_id` before using it as a file name.** `/ingest` saves the upload as
   `uploads/<doc_id><suffix>`. With the full `metadata` JSON the `doc_id` is free text,
   so a value containing `/` or `..` would write outside the uploads folder. It is
   admin-only, but restrict `doc_id` to letters, digits, `.`, `_` and `-`.
2. **Passwords are compared as plain text** (`shared/security.verify_password`).
   Agree with Person 2 on hashing (bcrypt or argon2).
3. **No rate limit or lock-out on `/auth/login`.**
4. `graph/safety.py`'s docstring still says tools receive "the header identity". It is
   the token identity now; update the comment.
5. Add tests for questions that must **not** be refused (for example a procedure
   question that mentions a friend) to measure how often the guard over-refuses.
6. `GET /sources` and `GET /health` need no login. Decide whether that is intended and
   say so in the README.
7. The diagram in `graph/workflow.py`'s docstring contains `\-`, which Python 3.12 and
   later report as a `SyntaxWarning`. Make the docstring a raw string (`r"""`).
