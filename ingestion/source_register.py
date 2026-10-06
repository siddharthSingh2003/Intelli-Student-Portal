"""Source Register (Annex B) - CSV file for humans, SQLite table for the running system (M1)."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from data.db import get_conn, one, rows
from shared.schemas import DocMetadata

FIELDS = ["doc_id", "title", "issuer", "authority_level", "doc_type", "version", "effective_from",
          "effective_to", "supersedes", "scope_programmes", "scope_batches", "provenance",
          "retrieved_on", "synthetic"]
CSV_FIELDS = FIELDS + ["file_path"]      # extra column: where the document lives in the repo


def upsert(meta: DocMetadata, file_path: str = "") -> None:
    row = {**meta.to_flat(), "file_path": file_path,
           "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    cols = list(row)
    with get_conn() as c:
        c.execute(f"INSERT OR REPLACE INTO source_register ({','.join(cols)}) "
                  f"VALUES ({','.join('?' * len(cols))})", tuple(row[k] for k in cols))


def get(doc_id: str) -> Optional[DocMetadata]:
    r = one("SELECT * FROM source_register WHERE doc_id = ?", (doc_id,))
    return DocMetadata.from_flat(r) if r else None


def all_docs() -> dict[str, DocMetadata]:
    return {r["doc_id"]: DocMetadata.from_flat(r) for r in rows("SELECT * FROM source_register")}


def all_rows() -> list[dict]:
    return rows("SELECT * FROM source_register ORDER BY authority_level, effective_from")


def load_csv(path: str | Path) -> list[tuple[DocMetadata, Path]]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            # a row without a file is a document that is listed but not collected yet
            if not (row.get("doc_id") or "").strip() or not (row.get("file_path") or "").strip():
                continue
            fp = Path((row.get("file_path") or "").strip())
            out.append((DocMetadata.from_flat(row), fp if fp.is_absolute() else path.parent / fp))
    return out


def export_csv(path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(all_rows())
