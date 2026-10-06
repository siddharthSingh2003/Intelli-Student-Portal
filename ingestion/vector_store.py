"""ChromaDB vector store (M1), persisted to disk. One collection per retrieval config."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from ingestion.chunker import Chunk
from ingestion.embeddings import get_embedder
from shared.config import RetrievalConfig, settings
from shared.schemas import DocMetadata


@dataclass
class Retrieved:
    chunk_id: str
    text: str
    score: float
    meta: dict[str, Any]

    @property
    def doc_id(self) -> str:
        return self.meta["doc_id"]

    @property
    def section(self) -> str:
        return str(self.meta.get("section", ""))

    def to_dict(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "text": self.text, "score": round(self.score, 4), **self.meta}


@lru_cache(maxsize=4)
def _client(path: str):
    return chromadb.PersistentClient(path=path, settings=ChromaSettings(anonymized_telemetry=False))


class VectorStore:
    def __init__(self, cfg: RetrievalConfig):
        self.cfg = cfg
        settings.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.col = _client(str(settings.chroma_dir)).get_or_create_collection(
            cfg.collection_name, metadata={"hnsw:space": "cosine"})
        self.embedder = get_embedder(cfg.embedding)

    def count(self) -> int:
        return self.col.count()

    def has_doc(self, doc_id: str) -> bool:
        return bool(self.col.get(where={"doc_id": doc_id}, limit=1)["ids"])

    def delete_doc(self, doc_id: str) -> None:
        self.col.delete(where={"doc_id": doc_id})

    def add(self, chunks: list[Chunk], meta: DocMetadata) -> int:
        if not chunks:
            return 0
        flat = meta.to_flat()
        metas = [{**flat, "section": c.section, "heading": c.heading, "page": c.page, "page_end": c.page_end}
                 for c in chunks]
        texts = [c.text for c in chunks]
        self.col.add(ids=[c.chunk_id for c in chunks], documents=texts,
                     embeddings=self.embedder.embed_documents(texts), metadatas=metas)
        return len(chunks)

    def search(self, query: str, k: int, where: Optional[dict] = None) -> list[Retrieved]:
        if self.count() == 0:
            return []
        res = self.col.query(query_embeddings=[self.embedder.embed_query(query)],
                             n_results=min(k, self.count()), where=where)
        return [Retrieved(cid, doc, 1.0 - dist, meta)
                for cid, doc, dist, meta in zip(res["ids"][0], res["documents"][0],
                                                res["distances"][0], res["metadatas"][0])]

    def find_page(self, doc_id: str, section: str) -> Optional[int]:
        got = self.col.get(where={"doc_id": doc_id}, include=["metadatas"])
        pages = [m["page"] for m in got["metadatas"]
                 if str(m.get("section")) == section or str(m.get("section")).startswith(section + ".")]
        return min(pages) if pages else None


@lru_cache(maxsize=8)
def get_store(cfg: Optional[RetrievalConfig] = None) -> VectorStore:
    return VectorStore(cfg or RetrievalConfig.from_env())
