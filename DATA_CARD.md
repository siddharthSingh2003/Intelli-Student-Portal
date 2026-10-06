# Synthetic data card (Annex E)

| Field | Content |
|---|---|
| Purpose | Test personal-data and eligibility paths (attendance, exam, supplementary, placement, what-if) at every rule boundary, without real student data. |
| Generator | `qwen2.5:7b-instruct` via Ollama, temperature 0.7, batches of 10 students. Calls, retries and tokens are logged in `data/generated/generation_log.json`. **Fill in after the real run.** |
| Prompts | Verbatim in `data/prompts/generate_students.system.txt` and `.user.txt`; the exact filled prompts of each call are stored in `generation_log.json`. |
| Schema enforcement | Ollama `format` = JSON schema of `GenBatch`; Pydantic validation (ranges, course coverage, attended ≤ held); invalid output retried with the error message fed back. Code assigns IDs, semesters, totals, max marks, sessions and backlog counts. |
| Row counts and distributions | 40 students (10 edge + 30 generated), 2 programmes (B.Tech CSE, B.Tech ECE), 2 batches (2023 in semester 7, 2024 in semester 5), 6 courses, 120 attendance rows, 120 results. **Fill in the per-programme/batch split and attendance/marks distribution from the real run.** |
| Edge cases included | See table below. |
| Validation results | `python -m data.validate --dir data/generated --generated`; report in `data/generated/validation_report.txt`. |
| What the LLM got wrong | Every correction the code made is listed in `generation_log.json → corrections` (for example a PASS with a total below the pass mark, or ABSENT with non-zero external marks). **Summarise the real run here.** |
| Login credentials | `credentials.csv` (`student_id`, `password`) is written next to the Annex C files and loaded into the extra `student_credentials` table; the Annex C tables are unchanged. Each row holds the student's initial password `Pass@<student_id>` in plain text. |
| Known limitations | All students take their programme's three courses regardless of semester; one exam session; no electives, transfers or year-back students; names are synthetic but India-centric. |

## Edge-case students

| ID | Edge case |
|---|---|
| S1001 | CS201 attendance exactly 75.0% (at the regulation threshold) |
| S1002 | CS201 attendance 72.5% (one class below 75%) |
| S1003 | CS201 attendance exactly 80.0% (at the circular threshold) |
| S1004 | CS201 attendance 77.5% (one class below 80%, above 75%) |
| S1005 | FAILED CS201 with 39/100, one mark below the pass mark; 1 backlog |
| S1006 | ABSENT in MA201 (external 0); 1 backlog |
| S1007 | DETAINED in CS202 (attendance 50%) |
| S1008 | Three FAILs, 3 active backlogs |
| S1009 | CGPA exactly 6.50 (placement cut-off), 0 backlogs |
| S1010 | EC201 total exactly 40/100 (at the pass mark) → PASS |

Reserved judge IDs (S9000-S9999) and course codes (JDG*) are never generated; the validator enforces this.
