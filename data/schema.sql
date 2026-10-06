-- Annex C fixed schema (required tables/columns are unchanged; extras are marked).
CREATE TABLE IF NOT EXISTS students (
    student_id       TEXT PRIMARY KEY,
    full_name        TEXT NOT NULL,
    programme        TEXT NOT NULL,
    batch_year       INTEGER NOT NULL,
    current_semester INTEGER NOT NULL CHECK (current_semester BETWEEN 1 AND 10),
    cgpa             REAL NOT NULL CHECK (cgpa BETWEEN 0 AND 10),
    active_backlogs  INTEGER NOT NULL CHECK (active_backlogs >= 0)
);

-- extra: login credentials, kept out of the Annex C students table. Passwords are plain text.
CREATE TABLE IF NOT EXISTS student_credentials (
    student_id TEXT PRIMARY KEY REFERENCES students(student_id),
    password   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- extra: staff who may add documents, students and rules. Passwords are plain text.
CREATE TABLE IF NOT EXISTS admin_users (
    username   TEXT PRIMARY KEY,
    password   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    course_code TEXT PRIMARY KEY,
    course_name TEXT NOT NULL,
    programme   TEXT NOT NULL,
    semester    INTEGER NOT NULL,
    credits     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance (
    student_id       TEXT NOT NULL REFERENCES students(student_id),
    course_code      TEXT NOT NULL REFERENCES courses(course_code),
    classes_held     INTEGER NOT NULL CHECK (classes_held > 0),
    classes_attended INTEGER NOT NULL CHECK (classes_attended >= 0 AND classes_attended <= classes_held),
    PRIMARY KEY (student_id, course_code)
);

CREATE TABLE IF NOT EXISTS results (
    student_id     TEXT NOT NULL REFERENCES students(student_id),
    course_code    TEXT NOT NULL REFERENCES courses(course_code),
    exam_session   TEXT NOT NULL,
    exam_type      TEXT NOT NULL CHECK (exam_type IN ('REGULAR', 'SUPPLEMENTARY')),
    internal_marks INTEGER NOT NULL,
    external_marks INTEGER NOT NULL,
    total_marks    INTEGER NOT NULL,
    max_marks      INTEGER NOT NULL,
    result         TEXT NOT NULL CHECK (result IN ('PASS', 'FAIL', 'ABSENT', 'DETAINED')),
    PRIMARY KEY (student_id, course_code, exam_session, exam_type)
);

CREATE TABLE IF NOT EXISTS rule_registry (
    rule_id          TEXT PRIMARY KEY,
    description      TEXT NOT NULL,
    parameter        TEXT NOT NULL,
    operator         TEXT NOT NULL,
    value            TEXT NOT NULL,
    scope_programmes TEXT NOT NULL DEFAULT 'ALL',
    scope_batches    TEXT NOT NULL DEFAULT 'ALL',
    effective_from   TEXT,
    effective_to     TEXT,
    source_doc_id    TEXT NOT NULL,
    source_section   TEXT NOT NULL,
    origin           TEXT NOT NULL DEFAULT 'manual'   -- extra: manual | extracted | ingest
);
CREATE INDEX IF NOT EXISTS idx_rule_param ON rule_registry(parameter);

-- Source Register (Annex B) mirrored in SQLite so GET /sources and live ingestion share one truth.
CREATE TABLE IF NOT EXISTS source_register (
    doc_id TEXT PRIMARY KEY, title TEXT, issuer TEXT, authority_level INTEGER, doc_type TEXT,
    version TEXT, effective_from TEXT, effective_to TEXT, supersedes TEXT,
    scope_programmes TEXT, scope_batches TEXT, provenance TEXT, retrieved_on TEXT, synthetic TEXT,
    file_path TEXT, ingested_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    trace_id    TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    answer_type TEXT,
    record_json TEXT NOT NULL
);
