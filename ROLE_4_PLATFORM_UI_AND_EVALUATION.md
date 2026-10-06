# Role 4 — Platform, UI and Evaluation Lead

**You own the ground the other three stand on, and the two things the judges look at
first: the screen and the numbers.** That means the shared contracts and
configuration, the LLM client, the Streamlit UI, the evaluation, Docker, CI and the
README. You also create the GitHub repository and push first.

If the panel asks "how do you know it works?", "what happens when the model returns
broken JSON?" or "how do I start it?", those are your questions.

| | |
|---|---|
| Folders | `ui/`, `eval/`, `.github/`, `docs/audit_samples/` |
| Shared code | `shared/config.py`, `shared/schemas.py`, `shared/llm.py` |
| Other files | `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `requirements-core.txt`, `.env.example`, `.gitignore`, `README.md`, `CONTRIBUTIONS.md`, `AI_USAGE.md`, `scripts/seed_all.py`, `scripts/export_audit_samples.py`, `tests/conftest.py` |
| Code size | 8 modules, about 950 lines of Python, plus Docker, CI and the documentation |
| In the code comments you are | `M4` (Member 4) |
| Works with | Everyone. Persons 1, 2 and 3 import your contracts, configuration and LLM client. Your UI calls Person 3's API. Your evaluation runs Person 3's workflow. |

## The team

| Person | Role | Zip |
|---|---|---|
| 1 | RAG Pipeline Engineer | `person1_rag_pipeline.zip` |
| 2 | Data and Tools Engineer | `person2_data_and_tools.zip` |
| 3 | Orchestration and API Engineer (LangGraph + FastAPI) | `person3_langgraph_and_fastapi.zip` |
| **4 (you)** | Platform, UI and Evaluation Lead | `person4_platform_ui_and_evaluation.zip` |

The four zips share no files. Together they are the whole repository. Nothing runs
until all four parts are in.

---

## 1. What is in this zip

| File | What it does |
|---|---|
| `shared/config.py` | Every setting, read from environment variables. `RetrievalConfig` holds what changes the index or the search result: embedding model, chunk strategy, chunk size, overlap, top-k. |
| `shared/schemas.py` | The Pydantic contracts between the layers: `DocMetadata` (a Source Register row), `RuleIn`, `AskRequest`, `AskResponse`, `Citation`, `ToolInvocation`, `AppliedRule`, `ConflictRecord`, `IngestResponse`, and the six answer types. |
| `shared/llm.py` | `LLMClient.chat_json()`: the one way any layer talks to the model. Ollama with a JSON schema, Pydantic validation, retry, optional cloud fallback, mock mode, health check. |
| `ui/streamlit_app.py` | Login page, then four tabs: Ask, Add a document, Sources, Audit. |
| `eval/eval_set.jsonl` | 25 questions with the expected answer type, strings the answer must contain, expected sources and expected tool outputs. |
| `eval/run_eval.py` | Runs every question through the workflow for each configuration and computes the six metrics. Writes per-question results, `summary.json` and `report.md`. |
| `scripts/seed_all.py` | One-shot setup without Docker: tables, students, admin account, documents, seed rules. |
| `scripts/export_audit_samples.py` | Writes the sample audit records in `docs/audit_samples/`. |
| `docs/audit_samples/` | Four sample records: `calculated`, `retrieved_fact`, `refused`, `conflict_flagged`. |
| `tests/conftest.py` | The test fixture: mock LLM, hash embedder, a temporary storage folder, and seeding once per test run. |
| `Dockerfile`, `docker-compose.yml` | One image, two services (`api` on 8000, `ui` on 8501). |
| `.github/workflows/ci.yml` | Runs `pytest -q` on every push and pull request. |
| `.github/CODEOWNERS` | Which member must review which path. |
| `requirements-core.txt`, `requirements.txt` | Core packages (enough for tests and CI); the full file adds CPU-only torch and sentence-transformers. |
| `.env.example`, `.gitignore` | Settings template; ignores `.env`, `storage/`, `eval/results/`, caches. |
| `README.md`, `CONTRIBUTIONS.md`, `AI_USAGE.md` | Project documentation, team roles, AI-usage disclosure. |

---

## 2. How your layer works

### The LLM client (`shared/llm.py`)

1. The caller passes a task name, a system prompt, a user prompt and a Pydantic schema.
2. If `MOCK_LLM=true`, the deterministic Python function registered for that task
   answers instead. Nothing leaves the process.
3. Otherwise the request goes to Ollama's `/api/chat` with the schema in `format`, so
   the model is constrained to that structure. Every field is marked required.
4. The reply is validated with Pydantic. If it is invalid, the model is asked again
   with the validation error in the conversation, up to `LLM_MAX_RETRIES` more times
   (default 2).
5. If Ollama cannot be reached, there is no retry. If `CLOUD_FALLBACK=true`, an
   OpenAI-compatible endpoint is tried once.
6. If everything fails, `LLMError` is raised. Each caller has a deterministic fallback.

There are four LLM tasks in the project: `plan` and `answer` (Person 3),
`doc_metadata` (Person 1), `generate_students` (Person 2).

### Configuration (`shared/config.py`)

Settings are properties that read the environment each time they are used. That is
why the tests and the evaluation can switch configuration inside one process.
A retrieval configuration is written `embedding:strategy:size:k`, for example
`bge:section:900:6`. Each one gets its own Chroma collection.

### The UI (`ui/streamlit_app.py`)

- Nothing is shown before login. The token is kept in the Streamlit session; a 401
  from the API logs the user out.
- **Ask**: the answer, a coloured label for the answer type, the trace ID, and
  expandable citations, tool calls and resolved conflicts. Assumptions and upcoming
  changes are shown as notes.
- **Add a document**: an admin chooses the authority level; a student's upload is
  always level 5. The stored metadata is shown with how each field was obtained.
- **Sources**: the Source Register. **Audit**: look up a record by trace ID.
- `/health` is cached for 30 seconds and `/sources` for 5 minutes, because Streamlit
  re-runs the whole script on every click.

### The evaluation (`eval/`)

| Metric | How it is computed | Its weakness |
|---|---|---|
| Answer correctness | Expected answer type, and every `must_contain` string is in the answer | Exact match: a correct answer in other words fails; a wrong sentence containing the string passes |
| Citation accuracy | A citation matches an expected `doc_id#section` (section by prefix) | An automatic proxy; it does not check the page |
| Abstention accuracy | (expected `not_found`) equals (returned `not_found`), over all questions | Only three questions are unanswerable |
| Tool correctness | Every expected tool output field equals the actual value | Only checks the fields listed in the eval set |
| Retrieval hit rate | An expected source is among the retrieved chunks | Only for questions that have expected sources |
| Latency and cost | p50 and p95 latency; mean LLM calls and tokens per question | In mock mode calls and tokens are zero |

The 25 questions by category: personal eligibility 5, conflict 4, policy fact 3,
not answerable 3, unauthorised 3, personal data 2, multi-step 2, procedure 1,
injection 1, clarification 1.

### Docker and CI

- `docker compose up --build` starts `api` and `ui` from the same image. The UI waits
  until the API's health check passes.
- Ollama runs on the host. The API reaches it at `host.docker.internal:11434`.
- `./storage`, `./docs` and `./data` are mounted, so the index and database survive a
  restart.
- The image installs Tesseract and bakes in both embedding models, so nothing is
  downloaded at start-up.
- CI installs `requirements-core.txt` and runs `pytest -q` with the mock LLM and the
  hash embedder. No model or GPU is needed.

---

## 3. Design decisions you must be able to defend

**Why a JSON schema in `format`, with every field required?**
A 7B model is unreliable at free-form JSON. With constrained decoding it can only
produce the schema's structure. Fields with defaults are optional in a Pydantic schema,
and a model may then stop at `{}`, which reads as "no answer". Marking every field
required forces it to fill them in.

**Why retry with the error, but not when Ollama is down?**
A validation error is something the model can fix when shown it. A connection error
is not, so retrying only adds waiting time.

**Why a mock mode?**
The whole pipeline runs and is tested without a model: in CI, on a laptop with no GPU,
and on the first day before Ollama is set up. The mock tests everything that is
deterministic. It says nothing about the model's quality; that is what the evaluation
with Ollama is for.

**Why Streamlit?**
The UI is scored for usability only, so the least code wins. All logic stays behind
the API, and the UI can be replaced without touching it.

**Why automatic exact-match scoring?**
It is repeatable and costs nothing, so every configuration can be compared on the same
basis. The weaknesses are in the table above; say them before the panel does.

**Why Ollama on the host and not in a container?**
The host has the GPU and the model already pulled. The image stays small and starts fast.

**Why two requirements files?**
`requirements-core.txt` has no torch, so CI installs in seconds and the tests still
run with the hash embedder. `requirements.txt` adds the real embedding models.

**Why is the cloud fallback off by default?**
Student data should stay local. The switch exists for a demo emergency and is
disclosed in the README.

---

## 4. Interfaces

**You provide**

| What | Used by |
|---|---|
| `shared.schemas.*` | everyone. Changing a model here is a team decision. |
| `shared.config.settings`, `RetrievalConfig` | everyone |
| `shared.llm.LLMClient`, `LLMError`, `register_mock` | Person 1 (metadata), Person 2 (generator), Person 3 (plan, answer) |
| `tests/conftest.py` | every test file |

**You consume**

- Person 3: the HTTP API (`/auth/login`, `/ask`, `/ingest`, `/sources`, `/health`,
  `/audit/{trace_id}`) from the UI, and `graph.workflow.run_question` from the evaluation
- Person 1: `ingestion.pipeline.bootstrap`
- Person 2: `data.db`, `data.loader.load_dir`, `data.generate_students.generate`,
  `data.credentials`, `tools.rules.load_rules_csv`

---

## 5. Run it

Run inside the full repository (after all four people have pushed).

```bash
# with Docker
ollama pull qwen2.5:7b-instruct
cp .env.example .env
docker compose up --build              # API http://127.0.0.1:8000, UI http://127.0.0.1:8501

# without Docker
pip install -r requirements.txt
export REGISTER_CSV=docs/sample/source_register.csv    # see the note below
python scripts/seed_all.py
uvicorn api.main:app --reload
streamlit run ui/streamlit_app.py

# tests (no model needed)
pip install -r requirements-core.txt
pytest -q

# evaluation
export REGISTER_CSV=docs/sample/source_register.csv
python -m eval.run_eval --configs minilm:section:900:6 bge:section:900:6 minilm:fixed:900:6
```

**Note on `.env`:** only `docker compose` reads it. Without Docker the code sees
environment variables only, and the default `REGISTER_CSV` is the real register
(`docs/source_register.csv`), not the sample corpus. The 25 evaluation questions and
the demo expect the sample corpus, so set the variable as shown
(Windows PowerShell: `$env:REGISTER_CSV="docs/sample/source_register.csv"`).

Log in as a student with `S1004` / `Pass@S1004`, or as admin with `admin` / `Admin@123`.

---

## 6. Create the repository and push first

You go first because your part carries `.gitignore`, the requirements and CI.

**1. Create the repository.** On github.com choose **New repository**. Give it a name.
Choose **Private** for now (Person 1 has to confirm that the scanned notice in `docs/`
may be published). Do **not** tick "Add a README", ".gitignore" or "license": the
repository must be empty.

**2. Add your teammates.** Settings → Collaborators → Add people. All three need to
accept the invitation before they can push.

**3. Push your part.**

```bash
git config --global user.name  "Your Name"
git config --global user.email "the email of your GitHub account"   # so the commit counts as yours

mkdir uni-assistant && cd uni-assistant
```

Extract `person4_platform_ui_and_evaluation.zip` **into this folder**. The zip has no
wrapping folder: `README.md`, `shared/`, `ui/` and `eval/` must sit directly inside it.
Your zip contains hidden files and folders (`.github/`, `.gitignore`, `.env.example`).
Check that they arrived:

```bash
ls -a            # Windows: dir /a      must list .github  .gitignore  .env.example
git init
git add .
git status       # .github/workflows/ci.yml and .gitignore must be in the list
git commit -m "platform: contracts, LLM client, UI, evaluation, Docker, CI"
git branch -M main
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

Use git for this part, not the web upload: dragging files into the browser easily
loses the dot-folders.

**4. Send the link** to Persons 1, 2 and 3. They clone, add their part and push, in
any order. No file belongs to two people, so there are no merge conflicts.

**5. When all three have pushed:**

```bash
git pull origin main
pip install -r requirements-core.txt && pytest -q
```

Then check the **Actions** tab on GitHub. The test job is red until the fourth part
arrives, because the tests import across layers. After that it must be green.

**6. Finish the placeholders** (see the open items): GitHub usernames in
`.github/CODEOWNERS`, real names in `CONTRIBUTIONS.md`.

Never commit `.env`. It is in `.gitignore`; keep it there.

---

## 7. Your part of the demo

- Show `eval/results/report.md`: the metric table, the configuration comparison, the
  latency, and the failures list.
- In the UI's Audit tab, paste a trace ID from an earlier answer and walk through the
  record: sources retrieved, precedence decision, tools, rules applied, model, tokens,
  latency.
- You also drive the screen for the others' parts.

---

## 8. Panel questions for you

**Q. Which configuration won, and by how much?**
The README reports, for the offline setup (mock LLM, hash embedder), 25/25 correct
with section chunking and 21/25 with fixed windows. Those are not model results. The
real comparison (MiniLM against bge, with Ollama) has not been run yet: there is no
`eval/results/` in the repository. Run it and quote those numbers instead.

**Q. What are your p50 and p95 latency and tokens per question?**
They are in the report after a run with Ollama. In mock mode the LLM calls and tokens
are zero, so do not quote mock numbers.

**Q. What happens when the model returns invalid JSON?**
The reply fails Pydantic validation, the error is sent back to the model, and it gets
up to two more attempts. If it still fails, `LLMError` is raised and the caller falls
back: the planner to rules, the answer to an extractive sentence, the metadata to
patterns.

**Q. How does the container reach Ollama on the host?**
The compose file gives the API `OLLAMA_URL=http://host.docker.internal:11434` by
default, and `extra_hosts: host.docker.internal:host-gateway` makes that name resolve
on Linux too. Test this yourself before the demo (open item 3).

**Q. Your tests pass without a model. What do they prove?**
That every deterministic part is correct: precedence, tools, the guard, the API
contract, ingestion, live rule changes. The two LLM steps are replaced by fixed
stand-ins. Model quality is measured separately by the evaluation.

**Q. Is the hash embedder used for real answers?**
No. It is a bag-of-words hashing trick for offline tests only. Real runs use MiniLM or bge.

**Q. How would you know if a change broke something?**
CI runs the test suite on every push and pull request, and the evaluation can be
re-run to compare the metrics before and after.

**Q. What are the weaknesses of your layer?**
Exact-match scoring; only 25 questions, all on the sample corpus; no human-graded
answers; the UI has no screens for changing a password or for the admin endpoints.

---

## 9. Open items you own

These are honest gaps. Fixing any of them is a good commit under your own name.
`AI_USAGE.md` says each owner read, ran and modified their module: read every file in
your part before the panel so that statement is true for you.

1. **Run the evaluation with Ollama and both embedding models.** Put the real numbers
   in the README. `eval/results/` is in `.gitignore`; copy `report.md` somewhere that
   is committed, or remove that line.
2. **Regenerate `docs/audit_samples/` with Ollama** (`python scripts/export_audit_samples.py`).
   The shipped records say `"model": "mock"`, and their request block still shows
   `X-Student-Id` although identity now comes from the login token.
3. **Check the Ollama address under Docker.** `docker-compose.yml` uses
   `${OLLAMA_URL:-http://host.docker.internal:11434}`, and compose also reads `.env`
   when it fills in `${...}`. `.env.example` sets `OLLAMA_URL=http://127.0.0.1:11434`,
   so after `cp .env.example .env` the container may be told to look for Ollama inside
   itself. Start the stack and open `/health`: if `llm` is `down`, remove `OLLAMA_URL`
   from `.env` or write the host address directly in the compose file.
4. **Make `.env` work without Docker**, or document it: today only `docker compose`
   reads it (see the note in section 5). Adding `python-dotenv` is one option.
5. **The evaluation set covers only the sample corpus.** Every expected source is a
   `SAMPLE-*` document. Add questions for the real register before switching
   `REGISTER_CSV` to it.
6. Replace the placeholders: `@member-N` in `.github/CODEOWNERS`, `Member N` in
   `CONTRIBUTIONS.md`, and the last line of `AI_USAGE.md`.
7. `.env.example` does not list `LLM_MAX_RETRIES` or `MIN_RETRIEVAL_SCORE`, which
   `shared/config.py` reads. Add them.
8. `scripts/export_audit_samples.py` says "three sample audit records" but writes four.
9. The default admin password `Admin@123` and the plain-text student passwords are for
   the synthetic demo only. Say so if asked, and change the admin password in `.env`.
10. The UI has no screen for `POST /auth/change-password`, `/admin/load-students` or
   `/admin/rules`. Add them if there is time.
