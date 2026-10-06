"""One-shot setup: DB schema -> synthetic students -> documents -> rules.

    python scripts/seed_all.py            # uses REGISTER_CSV / EMBEDDING_MODEL from env
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data import credentials  # noqa: E402
from data.db import init_db  # noqa: E402
from data.generate_students import generate  # noqa: E402
from data.loader import load_dir  # noqa: E402
from ingestion.pipeline import bootstrap  # noqa: E402
from shared.config import settings  # noqa: E402
from tools.rules import load_rules_csv  # noqa: E402


def main() -> None:
    init_db()
    if not (settings.students_dir / "students.csv").exists():
        print("generating students:", generate(settings.students_dir, 30, 42, 10)["counts"])
    print("students:", load_dir(settings.students_dir, generated=True)["loaded"])
    print("admin created:", credentials.ensure_admin())
    print("documents:", bootstrap(settings.register_csv))
    print("seed rules:", load_rules_csv(settings.rules_seed_csv))


if __name__ == "__main__":
    main()
