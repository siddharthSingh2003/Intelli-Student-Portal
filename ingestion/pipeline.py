"""Ingestion pipeline (M1): load -> extract -> clean -> chunk -> metadata -> embed -> Chroma.

`ingest_file` backs POST /ingest (admin only; metadata_extractor.py fills in the metadata
when the admin sends just an authority level) (live, no restart): the new chunks are queryable
immediately and any thresholds found in the document are added to rule_registry.
`bootstrap` indexes the Source Register once; restarts skip documents already in
Chroma (guide: "Do not re-ingest on every restart").
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ingestion import source_register
from ingestion.chunker import chunk_pages
from ingestion.cleaner import clean_pages
from ingestion.loader import load_document
from ingestion.vector_store import get_store
from shared.config import RetrievalConfig
from shared.schemas import DocMetadata, IngestResponse

log = logging.getLogger(__name__)


def ingest_file(path: str | Path, meta: DocMetadata, cfg: Optional[RetrievalConfig] = None,
                extract_rules: bool = True) -> IngestResponse:
    cfg = cfg or RetrievalConfig.from_env()
    pages = clean_pages(load_document(path))
    if not any(p.text.strip() for p in pages):
        raise ValueError(f"No text could be extracted from {Path(path).name} (even with OCR)")
    chunks = chunk_pages(pages, meta.doc_id, cfg.chunk_strategy, cfg.chunk_size, cfg.chunk_overlap)
    store = get_store(cfg)
    store.delete_doc(meta.doc_id)            # re-ingesting a doc_id replaces it (idempotent)
    n = store.add(chunks, meta)
    source_register.upsert(meta, str(path))
    extracted = 0
    if extract_rules:
        from tools.rule_extractor import extract_and_store   # M2 interface
        # rule extraction always uses section-aware chunks so the cited clause is exact
        section_chunks = chunks if cfg.chunk_strategy == "section" else \
            chunk_pages(pages, meta.doc_id, "section", cfg.chunk_size, cfg.chunk_overlap)
        extracted = extract_and_store(section_chunks, meta)
    log.info("ingested %s: %d chunks, %d rules extracted", meta.doc_id, n, extracted)
    return IngestResponse(doc_id=meta.doc_id, chunks_indexed=n, status="indexed", rules_extracted=extracted)


def bootstrap(register_csv: str | Path, cfg: Optional[RetrievalConfig] = None) -> dict[str, int]:
    cfg = cfg or RetrievalConfig.from_env()
    store = get_store(cfg)
    stats = {"indexed": 0, "skipped": 0, "failed": 0}
    for meta, fp in source_register.load_csv(register_csv):
        if store.has_doc(meta.doc_id) and source_register.get(meta.doc_id):
            stats["skipped"] += 1
            continue
        try:
            ingest_file(fp, meta, cfg)
            stats["indexed"] += 1
        except Exception as e:  # noqa: BLE001
            log.error("bootstrap failed for %s (%s): %s", meta.doc_id, fp, e)
            stats["failed"] += 1
    return stats
