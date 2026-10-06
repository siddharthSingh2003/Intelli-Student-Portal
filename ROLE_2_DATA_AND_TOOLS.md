# Role 2 — Data and Tools Engineer

**You own the facts and the arithmetic:** the SQLite database, the synthetic student
data, the rule registry, and the seven deterministic tools that decide eligibility.

If the panel asks "who decides whether a student is eligible, the LLM or your code?"
the answer is your code, and you are the one who explains it.

| | |
|---|---|
| Folders | `data/`, `tools/` |
| Other files | `scripts/load_students.py`, `DATA_CARD.md` |
| Tests | `tests/test_tools.py` |
| Code size | 12 modules, about 1,200 lines of Python |
| In the code comments you are | `M2` (Member 2) |
| Works with | Person 1 (calls your rule extractor, you call their precedence engine), Person 3 (the planner chooses from your tool catalogue, the API calls your loader and credentials), Person 4 (shared contracts, LLM client, evaluation) |

## The team

| Person | Role | Zip |
|---|---|---|
| 1 | RAG Pipeline Engineer | `person1_rag_pipeline.zip` |
| **2 (you)** | Data and Tools Engineer | `person2_data_and_tools.zip` |
| 3 | Orchestration and API Engineer (LangGraph + FastAPI) | `person3_langgraph_and_fastapi.zip` |
| 4 | Platform, UI and Evaluation Lead | `person4_platform_ui_and_evaluation.zip` |

The four zips share no files. Together they are the whole repository. Your zip does not
run on its own: it imports the other three parts.

---

## 1. What is in this zip

### `data/`

| File | What it does |
|---|---|
| `schema.sql` | Nine tables. Annex C tables: `students`, `courses`, `attendance`, `results`, `rule_registry`. Extras: `student_credentials`, `admin_users`, `source_register`, `audit_log`. |
| `db.py` | `get_conn()` (commit or rollback), `rows()`, `one()`, `init_db()`. A new connection per call, with foreign keys switched on. |
| `edge_cases.py` | The dataset design: 2 programmes, 2 batches, 6 courses, and 10 hand-built students that each sit on one rule boundary. |
| `generate_students.py` | Generates 30 more students with the local LLM, in batches of 10. Pydantic validates every batch; an invalid batch is retried with the error. A seeded Python generator replaces the LLM when `MOCK_LLM=true`. |
| `prompts/` | The exact system and user prompts given to the generator. |
| `validate.py` | Checks the four CSVs: required columns, ID format, ranges, attended ≤ held, total = internal + external, result consistent with marks, foreign keys, reserved judge IDs. |
| `loader.py` | Validates first, then upserts all tables in one transaction. If any check fails, nothing is written. |
| `credentials.py` | Student and admin passwords. Every student starts with `Pass@<student_id>`. |
| `generated/` | The generated CSVs, the validation report and the generation log. |
| `seed/rules_seed.csv` | Six hand-written rules for thresholds that sit inside tables in the synthetic circulars, which the regex extractor cannot read. |

### `tools/`

| File | What it does |
|---|---|
| `registry.py` | The tool catalogue. The planner may only pick a tool listed here, with only the listed parameters. |
| `student_tools.py` | `get_student_profile`, `get_attendance`, `get_results`. Read-only look-ups for one student. |
| `eligibility.py` | `check_exam_eligibility`, `check_supplementary_eligibility`, `check_placement_eligibility`, `project_attendance`. |
| `rules.py` | `get_rule(parameter, as_of, student)` finds the one rule that applies. `compare()` evaluates `>=`, `>`, `<=`, `<`, `==`, `in`, `between`. |
| `rule_extractor.py` | On every ingest, regex patterns turn threshold sentences into `rule_registry` rows tied to the document and clause. |

---

## 2. The seven tools

`student_id` and `as_of` are injected by the orchestrator from the login token.
The LLM can never supply them.

| Tool | Parameters the planner may set | Returns |
|---|---|---|
| `get_student_profile` | none | programme, batch, semester, CGPA, active backlogs |
| `get_attendance` | `course_code` (optional) | classes held, attended, percentage |
| `get_results` | `course_code` (optional) | latest result per course with marks |
| `check_exam_eligibility` | `course_code` | `ELIGIBLE`, `NOT_ELIGIBLE` or `CONDONATION_POSSIBLE`, plus `classes_needed` |
| `check_supplementary_eligibility` | `course_code` | `ELIGIBLE` or `NOT_ELIGIBLE` with the reason |
| `check_placement_eligibility` | `assume_passed` (list), `assume_cgpa` (both optional) | `ELIGIBLE` or `NOT_ELIGIBLE` with each check |
| `project_attendance` | `course_code`, `future_classes`, `attend_classes` | `PROJECTED_ELIGIBLE` or `PROJECTED_NOT_ELIGIBLE` |

Every eligibility output also carries `_applied_rules`, `_conflicts` and
`_assumptions`. Person 3's `tools_node` lifts these into the API response and the
audit record.

### How one eligibility check runs (`check_exam_eligibility`)

1. Read the student row and the attendance row for the course.
2. `get_rule("min_attendance_pct", as_of, student)` reads all candidate rules and asks
   Person 1's `resolve_rules` which one applies to this programme and batch on this date.
3. If two rules tie, return `CONFLICT`. If no rule exists, return `RULE_NOT_FOUND`.
4. Compare the **unrounded** percentage against the rule with `compare()`.
5. If not eligible, compute `classes_needed`.

### The `classes_needed` formula

Smallest whole number `x` of consecutive classes attended so that
`(attended + x) / (held + x) >= threshold / 100`:

```
x = ceil( (threshold * held - 100 * attended) / (100 - threshold) )
```

Example, student S1004: attended 31 of 40, threshold 80.
`(80*40 - 100*31) / (100 - 80) = 100 / 20 = 5` classes. Check: `36 / 45 = 80%`.

---

## 3. The rule registry

A rule is a row, not a constant in the code:

| Column | Example |
|---|---|
| `rule_id` | `ATT-MIN@SAMPLE-CIRC-2026-08#2` |
| `parameter` | `min_attendance_pct` |
| `operator`, `value` | `>=`, `80` |
| `scope_programmes`, `scope_batches` | `B.Tech`, `ALL` |
| `effective_from`, `effective_to` | `2026-08-01`, empty |
| `source_doc_id`, `source_section` | `SAMPLE-CIRC-2026-08`, `2` |
| `origin` | `extracted` (regex on ingest), `manual` (seed CSV or `/admin/rules`), `ingest` (sent with the upload) |

The extractor recognises five parameters: `min_attendance_pct`, `pass_min_total_pct`,
`placement_min_cgpa`, `placement_max_backlogs`, `supp_eligible_results`.

Safeguards inside the extractor:

- A level 5 (unofficial) document produces no rules.
- A sentence that is a question or says "you / your" is skipped: an FAQ or worked
  example illustrates a rule, it does not set one.
- "attendance below X%" counts only if the sentence also states a consequence
  (detained, not eligible, shall not).
- An attendance value outside 50–100 is ignored.
- Re-ingesting a document deletes its old extracted rules first.

---

## 4. The synthetic data

- 40 students: 10 edge cases plus 30 generated. 6 courses, 120 attendance rows, 120 results.
- 2 programmes (B.Tech CSE, B.Tech ECE), 2 batches (2023 in semester 7, 2024 in semester 5).

| ID | Edge case it tests |
|---|---|
| S1001 | CS201 attendance exactly 75.0% (regulation threshold) |
| S1002 | CS201 attendance 72.5% (one class below 75%) |
| S1003 | CS201 attendance exactly 80.0% (circular threshold) |
| S1004 | CS201 attendance 77.5% (above 75%, below 80%) |
| S1005 | Failed CS201 with 39/100, one mark short; 1 backlog |
| S1006 | Absent in MA201; 1 backlog |
| S1007 | Detained in CS202 (50% attendance) |
| S1008 | Three fails, 3 backlogs |
| S1009 | CGPA exactly 6.50 (placement cut-off) |
| S1010 | EC201 total exactly 40/100 (pass mark) |

**Code, not the LLM, assigns every derived field:** student IDs, semester, total marks,
maximum marks, exam session and backlog count. If the LLM writes `PASS` with a total
below the pass mark, code recomputes the result and logs the correction.

---

## 5. Design decisions you must be able to defend

**Why are thresholds in a table and not in the code?**
Rules change. When a new circular raises attendance from 75% to 80%, ingesting it adds
a rule row and the precedence engine picks it from its effective date. No code change,
no redeploy, and every decision can name the clause it used.

**Why regex for rule extraction and not the LLM?**
A wrong threshold would silently corrupt every eligibility decision. Regex is
deterministic and auditable: the rule description stores the exact sentence it came
from. Anything the patterns miss is added by hand through the seed CSV or
`POST /admin/rules`.

**Why does code compute eligibility instead of the LLM?**
Requirement R5: authoritative results must be deterministic. A 7B model can misread
77.5 against 80. Code cannot.

**Why compare the unrounded percentage?**
`attendance_pct` is rounded to two decimals for display only. Comparing a rounded
value could turn 79.996% into a pass.

**Why does the loader validate before writing?**
Judges load their own test students. A half-loaded file would leave attendance rows
without students. One transaction means all or nothing.

**Why fixed edge-case students?**
Random data rarely lands exactly on a boundary. Bugs live at 75.0%, 80.0%, 39 and 40
marks, CGPA 6.50. Fixed students also keep the evaluation's expected answers stable.

---

## 6. Interfaces

**You provide**

| Function | Used by |
|---|---|
| `tools.registry.TOOLS`, `catalog_text()` | planner and `tools_node` (Person 3) |
| `tools.rule_extractor.extract_and_store(chunks, meta)` | `ingest_file` (Person 1) |
| `tools.rules.add_rule`, `load_rules_csv` | API (Person 3), `scripts/seed_all.py` (Person 4) |
| `data.db.rows / one / get_conn / init_db` | everyone |
| `data.loader.load_dir` | API (Person 3), scripts, tests and evaluation (Person 4) |
| `data.credentials.*` | login in `api/auth.py` (Person 3) |

**You consume**

- `ingestion.precedence.resolve_rules` and `ingestion.source_register` (Person 1)
- `shared.llm.LLMClient` for the generator (Person 4)
- `shared.config.settings`, `shared.schemas.RuleIn` (Person 4)

---

## 7. Run and test your part

Run inside the full repository (after all four people have pushed).

```bash
pip install -r requirements-core.txt                       # enough for the tests
pytest -q tests/test_tools.py                              # no model needed

python -m data.generate_students --out data/generated --n 30   # needs Ollama unless MOCK_LLM=true
python -m data.validate --dir data/generated --generated
python scripts/load_students.py --dir data/generated
```

---

## 8. Put your part on GitHub

Person 4 creates the repository and pushes first (that part carries `.gitignore`, the
requirements and CI). Wait for the repository link and accept the collaborator
invitation GitHub emails you. Then:

```bash
git config --global user.name  "Your Name"
git config --global user.email "the email of your GitHub account"   # so the commit counts as yours

git clone https://github.com/<owner>/<repo>.git
cd <repo>
```

Extract `person2_data_and_tools.zip` **into this folder**. The zip has no wrapping
folder: `data/`, `tools/`, `scripts/` and `tests/` must end up next to `README.md`.
On Windows, "Extract All" creates a folder named after the zip; open it and move
everything inside into the cloned folder. If you are asked to merge `scripts/` or
`tests/`, say yes. No existing file is overwritten.

```bash
git status       # every new path must start with data/, tools/, scripts/, tests/, DATA_CARD or ROLE_2
git add .
git commit -m "data and tools: schema, synthetic data, rule registry, eligibility tools"
git pull --rebase origin main      # picks up what teammates pushed meanwhile
git push origin main
```

There are no merge conflicts, because no file belongs to two people.

No git on your machine? On the repository page choose **Add file → Upload files**,
drag in the extracted folders and the two `.md` files, and commit.

The green tick on GitHub (the CI test job) appears only once all four parts are in,
because the tests import across layers. A red cross before that is expected.

---

## 9. Your part of the demo

- Log in as **S1004** and ask "Am I eligible for the exam in Data Structures?".
  Expected with the sample corpus: not eligible, 77.5% against 80%, 5 more classes needed.
- With Person 1: after a new circular is ingested live, ask again and show the answer change.

---

## 10. Panel questions for you

**Q. How does a rule get into the registry?**
Three ways: the extractor on ingest (`origin=extracted`), the seed CSV or
`POST /admin/rules` (`manual`), or a `rules` list sent with the upload (`ingest`).

**Q. Two rules give different attendance thresholds. Which one does the tool use?**
`get_rule` hands all candidates to the precedence engine with the student's programme,
batch and the date. It returns one winner, or `CONFLICT` if the policy cannot decide.

**Q. What did the LLM get wrong when generating data, and how did you catch it?**
The generator recomputes any result that contradicts the marks and logs it under
`corrections` in `generation_log.json`. Be honest here: the CSVs shipped in the repo
were produced by the seeded mock generator (the log says `mock-deterministic`), so the
correction list is empty. Run the real generator before the panel and report what it logs.

**Q. A student failed, then passed the supplementary. Which result counts?**
`latest_results` keeps the row with the latest exam session; within a session a
`SUPPLEMENTARY` row beats a `REGULAR` one.

**Q. Why can a detained student not take the supplementary exam?**
The rule's value is `FAIL;ABSENT` with operator `in`. `DETAINED` is not in the list.

**Q. Why SQLite and not PostgreSQL?**
SQLite was fixed by the guide. It also fits: one file, no server, ships in Python,
and the workload is small reads. The trade-off is a single writer at a time.

**Q. Is your SQL safe from injection?**
Every value is passed through `?` placeholders, and the tools only ever receive the
student ID from the login token. There is one weak spot to admit: `data/loader.py`
builds the column list of its `INSERT` from the CSV header, so an unexpected header
name would reach the SQL text. The endpoint is admin-only, but the loader should
check column names against the fixed `REQUIRED` lists (see open item 6).

---

## 11. Open items you own

These are honest gaps. Fixing any of them is a good commit under your own name.
`AI_USAGE.md` says each owner read, ran and modified their module: read every file in
`data/` and `tools/` before the panel so that statement is true for you.

1. **Run the real generator.** `data/generated/generation_log.json` shows the shipped
   data came from the mock path. `DATA_CARD.md` still has "Fill in after the real run"
   in three places.
2. **Condonation is never triggered today.** `check_exam_eligibility` supports a
   `condonation_min_attendance_pct` rule, but nothing extracts or seeds one. Add a seed
   row from the attendance circular's condonation table, with a test.
3. **Passwords are stored as plain text** in `student_credentials`, `admin_users` and
   `data/generated/credentials.csv`. That is acceptable only because the data is
   synthetic. Agree with Person 3 on hashing (bcrypt or argon2).
4. The six seed rules point at the two synthetic circulars. They load only when
   `REGISTER_CSV` is the real register; with the sample register they are skipped.
5. A few docstrings still say identity comes from the `X-Student-Id` header. It now
   comes from the login token; update the comments.
6. **Whitelist CSV columns in `data/loader.py`.** `load_tables` takes column names
   from the uploaded CSV header and puts them into the `INSERT` statement. Keep only
   the columns listed in `data.validate.REQUIRED` and reject the rest.
