"""Test setup: offline (MOCK_LLM + hash embedder), isolated temp storage, sample corpus."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_tmp = tempfile.mkdtemp(prefix="ua-test-")
os.environ.update({"MOCK_LLM": "true", "EMBEDDING_MODEL": "hash", "STORAGE_DIR": _tmp,
                   "REGISTER_CSV": str(ROOT / "docs/sample/source_register.csv"),
                   "STUDENTS_DIR": str(Path(_tmp) / "students"),
                   "JWT_SECRET": "test-secret-" + "x" * 32})
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded():
    from data.db import init_db
    from data.generate_students import generate
    from data.loader import load_dir
    from ingestion.pipeline import bootstrap
    from shared.config import settings
    init_db()
    generate(settings.students_dir, 30, 42, 10)
    load_dir(settings.students_dir, generated=True)
    bootstrap(settings.register_csv)
    yield
