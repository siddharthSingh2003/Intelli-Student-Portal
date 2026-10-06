# `data/loader.py`: how student data gets into the database

`loader.py` takes the four Annex C CSV files (`students.csv`, `courses.csv`, `attendance.csv`, `results.csv`), checks them, and writes them into the SQLite database. It is the library behind the judge-facing CLI [`scripts/load_students.py`](../scripts/load_students.py).

It follows one rule: **validate everything first, then write everything in one transaction**. If any check fails, nothing is written.

---

## The big picture

```
scripts/load_students.py --dir test_students/
        │
        ▼
load_dir(path)
  ├─ read_dir(path)            → reads whichever of the 4 CSVs exist into dicts   (data/validate.py)
  ├─ load_tables(tables)
  │    ├─ fetch existing students + courses from DB
  │    ├─ validate_tables(...)  → list of Violations (errors / warnings)          (data/validate.py)
  │    ├─ any error?  → raise LoadError(report)     ← nothing written
  │    └─ one transaction: INSERT OR REPLACE each table in FK order
  └─ credentials
       ├─ load_csv(credentials.csv)   → optional custom passwords                 (data/credentials.py)
       └─ ensure_credentials()        → default password for everyone else
```

---

## Walkthrough

### Constants (lines 15–18)

```python
INT_COLS = {"batch_year", "current_semester", "active_backlogs", "semester", "credits", ...}
FLOAT_COLS = {"cgpa"}
ORDER = ["students", "courses", "attendance", "results"]
```

- **`INT_COLS` / `FLOAT_COLS`**: CSV values always come in as strings. These sets say which columns are converted to `int` or `float` before they are stored. Every other column stays a string.
- **`ORDER`**: the order the tables are inserted in. `attendance` and `results` hold foreign keys to `students` and `courses`, and `db.connect()` turns on `PRAGMA foreign_keys = ON`, so parent rows have to exist before child rows.

### `LoadError` (lines 21–24)

```python
class LoadError(ValueError):
    def __init__(self, report: str):
        super().__init__(report)
        self.report = report
```

This exception is raised when validation fails or no CSVs are found. It carries the full human-readable validation report in `.report`, and the CLI prints that report before exiting with code 1.

### `_coerce(row)` (lines 27–36)

This function converts one CSV row (a dict of strings) to the right Python types:

| Column is in… | Becomes |
|---|---|
| `INT_COLS` | `int(value.strip())` |
| `FLOAT_COLS` | `float(value.strip())` |
| anything else | `value.strip()` (string) |

It does not handle bad values. It can assume they parse because validation has already rejected any non-numeric value in these columns.

### `load_tables(tables, generated=False)` (lines 39–60)

This is the core function. `tables` looks like `{"students": [ {...}, ... ], "courses": [...], ...}`.

**Step 1: Load what is already in the DB (lines 40–41)**

```python
existing_students = {r["student_id"]: r for r in rows("SELECT * FROM students")}
existing_courses  = {r["course_code"]: r for r in rows("SELECT * FROM courses")}
```

Validation runs against the current DB contents, not only the incoming files. This means a judge can load *only* `attendance.csv` and `results.csv` for students and courses that already exist, and the foreign-key checks still pass.

**Step 2: Remove students that are being replaced (lines 42–43)**

```python
for s in tables.get("students", []):
    existing_students.pop(s.get("student_id"), None)
```

If an incoming `students.csv` contains `S0001`, the old DB copy of `S0001` is dropped from the "existing" set. Then:
- the new row is validated on its own and is not merged with stale data, and
- it is not flagged as a duplicate. The validator only reports duplicates that occur *within the incoming file* (`sid in students and sid not in existing_students`).

**Step 3: Validate (lines 44–48)**

```python
viol = validate_tables(tables, existing_students=..., existing_courses=..., generated=generated)
report = format_report(viol, tables)
if any(x.severity == "error" for x in viol):
    raise LoadError(report)
```

`validate_tables` (in [`validate.py`](validate.py)) returns a list of `Violation(table, key, rule, message, severity)`. It checks required columns, ID format (`S` + 4 digits), value ranges (semester 1–10, CGPA 0–10, etc.), duplicates, and references between tables.

- **Errors** stop the load.
- **Warnings** (for example "course's programme has no students") are allowed through and counted.

The `generated` flag adds two extra checks for *synthetic* data: IDs `S9000–S9999` and course codes starting with `JDG` are reserved for judges, so the project's own generated data must not use them.

**Step 4: Write everything in one transaction (lines 49–59)**

```python
with get_conn() as c:
    for table in ORDER:
        data = [_coerce(r) for r in tables.get(table, [])]
        if not data:
            continue
        cols = list(data[0].keys())
        c.executemany(
            f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [tuple(r[k] for k in cols) for r in data])
        counts[table] = len(data)
```

- `get_conn()` (in [`db.py`](db.py)) is a context manager. It **commits** if the block finishes and **rolls back** if anything raises, so the four tables are written all-or-nothing.
- Tables missing from the input are skipped.
- The SQL is built from the CSV's column names. For example, for students it produces:
  ```sql
  INSERT OR REPLACE INTO students (student_id,full_name,programme,...) VALUES (?,?,?,...)
  ```
  Values go in through `?` placeholders, which is safe. The column list is taken from the keys of the **first row**.
- `INSERT OR REPLACE` is an **upsert**: a row with an existing primary key is overwritten, and a new key is inserted. Running the loader twice on the same files is therefore safe.

**Step 5: Return a summary (line 60)**

```python
{"loaded": {"students": 50, "courses": 12, ...}, "warnings": 2, "report": "VALIDATION REPORT\n..."}
```

### `load_dir(path, generated=False)` (lines 63–71)

This is the entry point used by the CLI.

1. `read_dir(path)` looks for each of the four CSVs in the folder and reads the ones that exist. Header names and values are whitespace-stripped.
2. If none were found, it raises `LoadError("No Annex C CSV files ... found")`.
3. It calls `load_tables(...)` (described above).
4. It sets up **login credentials** for students:
   - `credentials.load_csv(path / "credentials.csv")`: optional file with `student_id,password` columns. Rows for unknown students or with blank passwords are skipped.
   - `credentials.ensure_credentials()`: every student who still has no password gets the initial one (by default `Pass@<student_id>`, set by `settings.initial_password`).
5. It returns the `load_tables` result with an extra `"credentials": {"loaded": n, "initialised": m}` entry.

---

## Example

```bash
python scripts/load_students.py --dir test_students/
```

- **All checks pass:** prints the validation report and `Loaded: {'students': 20, 'attendance': 140, ...}`, then exits with `0`.
- **Any error:** prints the report (for example `[ERROR] students:S12 id_format - student_id must be S followed by 4 digits`), then `Nothing was loaded.`, then exits with `1`.

From Python:

```python
from data.loader import load_dir, LoadError
try:
    res = load_dir("data/generated", generated=True)
except LoadError as e:
    print(e.report)
```

---

## Things worth knowing

- **Credentials are written after the main transaction.** `load_csv` and `ensure_credentials` each open their own connection after the student/course/attendance/results commit. If the credentials step fails, the student data is already saved.
- **Column names come from the CSV headers.** The validator only checks that the *required* columns are present, so an extra header in a CSV (such as `notes`) is placed straight into the `INSERT` column list. SQLite then fails with "no such column" and the transaction rolls back. Header text is also inserted into the SQL as-is, without placeholders. If the CSVs could come from untrusted sources, filter `cols` against a known column list for each table.
- **Every row is assumed to have the same columns as the first row.** This holds for CSVs read through `csv.DictReader`. It may not hold if `load_tables` is called directly with dicts built by hand.
- **The `POST /admin/load-students` endpoint in the module docstring is not in this repo.** Only the CLI calls this module in the current code.
