"""Test-student loader CLI (judges use this).

    python scripts/load_students.py --dir test_students/

Loads any of students.csv, courses.csv, attendance.csv, results.csv in the Annex C
schema. Validates first; nothing is written if any check fails.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.db import init_db  # noqa: E402
from data.loader import LoadError, load_dir  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    init_db()
    try:
        res = load_dir(a.dir)
    except LoadError as e:
        print(e.report)
        print("\nNothing was loaded.")
        return 1
    print(res["report"])
    print(f"\nLoaded: {res['loaded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
