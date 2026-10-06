# Team roles and contribution statement

Each member owns one layer end to end: its code, its tests, its share of the README, and its part of the
demo. The interfaces between layers live in `shared/`. Replace `Member N` with real names before submission.

| Member | Role | Folders | Hand-over note |
|---|---|---|---|
| 1 | RAG Pipeline Engineer | `ingestion/`, `docs/` | `ROLE_1_RAG_PIPELINE.md` |
| 2 | Data and Tools Engineer | `data/`, `tools/` | `ROLE_2_DATA_AND_TOOLS.md` |
| 3 | Orchestration and API Engineer (LangGraph + FastAPI) | `graph/`, `api/` | `ROLE_3_LANGGRAPH_AND_FASTAPI.md` |
| 4 | Platform, UI and Evaluation Lead | `ui/`, `eval/`, `shared/`, Docker, CI | `ROLE_4_PLATFORM_UI_AND_EVALUATION.md` |

No file belongs to two members. `shared/schemas.py` is the one file all four review before it changes.

## Member 1: RAG Pipeline Engineer

**Owns:** `ingestion/`, `docs/` (except `docs/audit_samples/`), `tests/test_ingestion.py`,
`tests/test_precedence.py`

**What they build**
- The ingestion pipeline: PDF text with PyMuPDF, OCR fallback for scanned pages, table extraction with
  pdfplumber, cleaning of running headers and page numbers (`loader.py`, `cleaner.py`).
- Section-aware chunking that keeps the clause number on every chunk (`chunker.py`). This is what makes
  citations precise and clause-level supersession possible.
- Embeddings (MiniLM and bge, switchable) and the ChromaDB store, one collection per configuration
  (`embeddings.py`, `vector_store.py`).
- The Source Register in CSV and SQLite (`source_register.py`), automatic metadata extraction for uploads
  (`metadata_extractor.py`) and the core of `POST /ingest` (`pipeline.py`).
- **The Annex A precedence engine** (`precedence.py`): applicability, supersession, authority, recency,
  unresolved. Used both on retrieved chunks and on rules.
- Collecting the university documents and filling in `docs/source_register.csv`.

**Why it matters for scoring:** grounded answers and citations (20) and versioning, conflicts and live
ingestion (15) both depend on this layer. Judges will ingest unseen documents during live testing.

**Q&A talking points:** why section chunking beat fixed windows (eval numbers); why supersession is checked
against the whole register, not just retrieved chunks; why a level-5 source can never win; how a
batch-scoped circular is handled for a general question.

## Member 2: Data and Tools Engineer

**Owns:** `data/`, `tools/`, `scripts/load_students.py`, `DATA_CARD.md`, `tests/test_tools.py`

**What they build**
- The Annex C schema and DB helpers (`schema.sql`, `db.py`).
- The LLM-based synthetic data generator with verbatim prompts, Pydantic schema enforcement and retries
  (`generate_students.py`, `prompts/`), plus 10 deliberate edge-case students (`edge_cases.py`).
- The validation script and the judge-facing loader (`validate.py`, `loader.py`, `scripts/load_students.py`).
- The rule registry and the rule extractor that turns thresholds in newly ingested documents into rules
  tied to their clause (`rules.py`, `rule_extractor.py`).
- All deterministic tools: attendance, results, profile, exam eligibility, supplementary eligibility,
  placement eligibility with what-if, attendance projection (`student_tools.py`, `eligibility.py`).

**Why it matters for scoring:** tools (15, shared), synthetic data quality (5), and the disqualification
rule that authoritative results must never come from LLM text.

**Q&A talking points:** how a rule gets into the registry and what happens when a new circular changes it;
why code (not the LLM) assigns IDs, totals and backlog counts; which edge case each student ID covers;
what the LLM got wrong during generation and how validation caught it.

## Member 3: Orchestration and API Engineer (LangGraph + FastAPI)

**Owns:** `graph/`, `api/`, `shared/security.py`, `tests/test_graph.py`, `tests/test_api.py`

**What they build**
- The LangGraph workflow: guard, plan, retrieve, tools, generate, finalize (`workflow.py`, `nodes.py`).
- The planner gate: the LLM proposes tools, code validates names, arguments and course codes, and falls
  back to a rule planner (`planner.py`, `courses.py`).
- Safety: refusal of other students' data, stripping and logging of instruction-like text in documents
  (`safety.py`).
- Answer typing, citation validation, numeric grounding check, and the guarantee that the answer always
  comes from the precedence winner (`nodes.finalize_node`, `templates.py`, `extractive.py`).
- The FastAPI app implementing the Section 6 contract exactly (`/ask`, `/ingest`, `/audit`, `/sources`,
  `/health`), plus the admin endpoints for test students and rules (`api/main.py`).
- Login: password check, JWT with a role, and the dependencies that turn a request into the logged-in
  user (`api/auth.py`, `shared/security.py`). The audit store (`api/audit.py`).

**Why it matters for scoring:** orchestration and multi-step (15, shared), safety and responsible AI (10),
architecture judgement (10). The live-testing slot only works if the API contract is exact.

**Q&A talking points:** why one workflow and not multiple agents; why the verdict sentence is templated;
how "I am S1002" in the message is handled; how the forum post's injection is neutralised; why identity
comes from the token and never from a header or the text; why a student upload is forced to level 5; why
another student's trace returns 404.

## Member 4: Platform, UI and Evaluation Lead

**Owns:** `ui/`, `eval/`, `shared/config.py`, `shared/schemas.py` (custodian), `shared/llm.py`, `Dockerfile`,
`docker-compose.yml`, `.github/`, `requirements*.txt`, `.env.example`, `README.md`, `CONTRIBUTIONS.md`,
`AI_USAGE.md`, `tests/conftest.py`, `scripts/seed_all.py`, `scripts/export_audit_samples.py`,
`docs/audit_samples/`

**What they build**
- The LLM client used by every layer: Ollama with JSON-schema output, validation and retry, cloud
  fallback switch, mock mode (`shared/llm.py`), and the central configuration (`shared/config.py`).
- The Streamlit UI: login, ask, add a document, sources, audit lookup (`ui/streamlit_app.py`).
- The 25-question evaluation set and the harness computing all six metrics across configurations
  (`eval/`).
- Docker, compose, CI, the test fixture, README, the sample audit records, and the demo script.

**Why it matters for scoring:** evaluation rigour (10) and engineering quality (10), and the UI is what the
judges see first.

**Q&A talking points:** how each metric is computed and its weakness; which configuration won and by how
much; p50/p95 latency and tokens per question; how `docker compose up` connects to Ollama on the host;
what happens when qwen returns invalid JSON.

## How the four parts go into one repository

The parts share no files, so they can be pushed in any order without merge conflicts. Member 4 goes
first because that part carries `.gitignore`, the requirements and the CI workflow.

1. **Member 4** creates an empty repository (no README, no .gitignore), adds the other three as
   collaborators, and pushes the platform part to `main`.
2. **Members 1, 2 and 3** each clone the repository, extract their part into it, commit under their own
   Git identity and push. If a push is rejected because someone else pushed first:
   `git pull --rebase origin main`, then push again.
3. CI (`.github/workflows/ci.yml`) turns green only once all four parts are in, because the tests import
   across layers.
4. After that, work on `feat/<area>` branches and open pull requests. With branch protection switched on,
   `CODEOWNERS` requires the owning member's review.
5. Tag `final` on `main` after the eval report is regenerated with Ollama.

```bash
git clone https://github.com/<owner>/<repo>.git && cd <repo>
# extract your zip here so that your folders sit next to README.md
git add . && git commit -m "ingestion: loader, section chunking, Chroma store, precedence engine"
git pull --rebase origin main && git push origin main
```

## Demo script (10 minutes)

| Minute | Shown by | Request |
|---|---|---|
| 0-2 | Member 1 | "What is the minimum attendance required?" → 80%, circular cited, step 2 and step 3 shown |
| 2-4 | Member 2 | S1004 "Am I eligible for the exam in Data Structures?" → not eligible, 77.5% vs 80%, 5 classes needed |
| 4-6 | Member 3 | "Scholarship for Antarctica?" → not_found; "attendance of S1002" → refused; hostel curfew → conflict_flagged |
| 6-8 | Member 1 + 2 | Live `/ingest` of a new circular, then the same eligibility question changes answer |
| 8-10 | Member 4 | Eval report: metrics, config comparison, latency; open an audit record |
