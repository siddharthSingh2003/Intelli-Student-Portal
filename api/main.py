"""FastAPI app (M3) implementing the fixed API contract in Section 6 of the guide.

    uvicorn api.main:app --reload
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from api import audit
from api.auth import User, current_user, require_admin, router as auth_router
from data import credentials
from data.db import init_db, one
from data.loader import LoadError, load_dir
from data.validate import REQUIRED
from graph.workflow import run_question
from ingestion import source_register
from ingestion.cleaner import clean_pages
from ingestion.loader import load_document
from ingestion.metadata_extractor import extract_metadata
from ingestion.pipeline import bootstrap, ingest_file
from ingestion.vector_store import get_store
from shared.config import RetrievalConfig, settings
from shared.llm import LLMClient
from shared.schemas import AskRequest, AskResponse, IngestMetadata, IngestResponse, RuleIn
from tools.rules import add_rule, load_rules_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        log.info("bootstrap documents: %s", bootstrap(settings.register_csv))
        log.info("seed rules: %s", load_rules_csv(settings.rules_seed_csv))
        if not one("SELECT 1 AS x FROM students LIMIT 1") and (settings.students_dir / "students.csv").exists():
            log.info("seed students: %s", load_dir(settings.students_dir)["loaded"])
        log.info("credentials initialised for %d student(s)", credentials.ensure_credentials())
        if credentials.ensure_admin():
            log.info("created admin account '%s'", settings.admin_username)
    except Exception as e:  # noqa: BLE001 - the API must still start and report via /health
        log.error("startup seeding failed: %s", e)
    yield


app = FastAPI(title="University Student Services Assistant", version="1.0.0", lifespan=lifespan)
app.include_router(auth_router)


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, user: User = Depends(current_user)):
    # an admin is not a student: they can ask about the documents, but there are no "my records"
    response, record = run_question(req.question, user.student_id, req.as_of_date)
    audit.save(record)
    # R7: operational log carries no personal data, only the trace
    log.info("trace=%s type=%s latency_ms=%s", record["trace_id"], record["answer_type"], record["latency_ms"])
    return response


@app.post("/ingest", response_model=IngestResponse)
def ingest(file: UploadFile = File(...), metadata: Optional[str] = Form(default=None),
           authority_level: Optional[int] = Form(default=None, ge=1, le=5), user: User = Depends(current_user)):
    """An admin sends either `authority_level` alone (the rest of the metadata is read from the
    document) or the full `metadata` JSON of the original contract. A student may also add a
    document, but only as level 5 (unofficial): it is informational, can never override an official
    source or set a rule, and cannot replace a document the student did not upload."""
    is_staff = user.is_admin or not settings.auth_required      # legacy contract has no roles
    if not is_staff:
        if metadata is not None:
            raise HTTPException(403, "Only an admin can supply metadata. Upload the file alone.")
        authority_level = 5                                      # whatever the student sent
    suffix = Path(file.filename or "").suffix.lower() or ".pdf"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    extracted_by = None
    if metadata is not None:
        try:
            meta = IngestMetadata.model_validate(json.loads(metadata))
        except (json.JSONDecodeError, ValidationError) as e:
            raise HTTPException(422, f"invalid metadata: {e}")
        dest = settings.uploads_dir / f"{meta.doc_id}{suffix}"
        with dest.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
    elif authority_level is None:
        raise HTTPException(422, "send authority_level (metadata is then extracted) or the full metadata JSON")
    else:
        tmp = settings.uploads_dir / f"_incoming-{uuid.uuid4().hex}{suffix}"
        with tmp.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        try:
            text = "\n".join(p.text for p in clean_pages(load_document(tmp)))
            if not text.strip():
                raise ValueError(f"No text could be extracted from {file.filename} (even with OCR)")
            doc_meta, extracted_by = extract_metadata(text, Path(file.filename or tmp.name).name, authority_level,
                                                      uploaded_by=user.id or "legacy")
        except ValueError as e:
            tmp.unlink(missing_ok=True)
            raise HTTPException(422, str(e))
        if not is_staff:
            # a doc_id of their own, so a student upload can never take the place of an official document
            doc_meta = doc_meta.model_copy(update={"doc_id": f"STU-{user.id}-{doc_meta.doc_id}"[:80],
                                                   "doc_type": "unofficial"})
            extracted_by.update(authority_level="fixed for student uploads", doc_type="fixed for student uploads")
        meta = IngestMetadata(**doc_meta.model_dump())
        dest = settings.uploads_dir / f"{meta.doc_id}{suffix}"
        tmp.replace(dest)
    try:
        result = ingest_file(dest, meta)
    except ValueError as e:
        raise HTTPException(422, str(e))
    result.metadata, result.extracted_by = meta.to_flat(), extracted_by
    added = 0
    for r in meta.rules:
        add_rule(r, origin="ingest")
        added += 1
    result.rules_added = added
    source_register.export_csv(settings.storage_dir / "source_register.snapshot.csv")
    return result


@app.get("/health")
def health():
    status = {"api": "ok"}
    try:
        status["vector_store"] = {"status": "ok", "chunks": get_store(RetrievalConfig.from_env()).count()}
    except Exception as e:  # noqa: BLE001
        status["vector_store"] = {"status": "down", "error": str(e)}
    try:
        status["sqlite"] = {"status": "ok",
                            "students": one("SELECT COUNT(*) AS n FROM students")["n"],
                            "rules": one("SELECT COUNT(*) AS n FROM rule_registry")["n"],
                            "documents": one("SELECT COUNT(*) AS n FROM source_register")["n"]}
    except Exception as e:  # noqa: BLE001
        status["sqlite"] = {"status": "down", "error": str(e)}
    status["llm"] = LLMClient().health()
    healthy = all(v == "ok" or (isinstance(v, dict) and v.get("status") == "ok") for v in status.values())
    return {"status": "ok" if healthy else "degraded", **status}


@app.get("/audit/{trace_id}")
def get_audit(trace_id: str, user: User = Depends(current_user)):
    rec = audit.get(trace_id)
    # a trace holds one student's records: only that student (or an admin) may read it, and
    # other students cannot tell it exists
    own = user.is_admin or rec is None or rec.get("student_id") == user.student_id
    if rec is None or (settings.auth_required and not own):
        raise HTTPException(404, "trace_id not found")
    return rec


@app.get("/sources")
def sources():
    return source_register.all_rows()


@app.post("/admin/load-students")
def load_students(files: list[UploadFile] = File(...), admin: User = Depends(require_admin)):
    """Test-student loader endpoint: upload any of students/courses/attendance/results.csv."""
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            name = Path(f.filename or "").name
            if name.removesuffix(".csv") not in (*REQUIRED, "credentials"):
                raise HTTPException(422, f"unexpected file {name}; expected {[t + '.csv' for t in REQUIRED]}")
            with (Path(tmp) / name).open("wb") as fh:
                shutil.copyfileobj(f.file, fh)
        try:
            return load_dir(tmp)
        except LoadError as e:
            raise HTTPException(422, e.report)


@app.post("/admin/rules")
def add_rules(rules: list[RuleIn], admin: User = Depends(require_admin)):
    try:
        for r in rules:
            add_rule(r, origin="manual")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"added": len(rules)}
