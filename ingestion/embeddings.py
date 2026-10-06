"""Embedding models (M1). Both guide-approved models, switchable via EMBEDDING_MODEL.

* minilm  all-MiniLM-L6-v2   - 384-d, fastest, good general retrieval
* bge     bge-small-en-v1.5  - 384-d, stronger on retrieval benchmarks; needs a query instruction
* hash    offline bag-of-words hashing - test/CI only
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache

import numpy as np

from shared.config import EMBEDDING_MODELS

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_STOP = set("the a an of to and or in on for is are be by with as at from that this it its".split())


class HashEmbedder:
    dim = 384

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim)
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            if len(w) < 3 or w in _STOP:
                continue
            v[int(hashlib.md5(w[:5].encode()).hexdigest(), 16) % self.dim] += 1.0
        n = np.linalg.norm(v)
        return (v / n if n else v).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class SentenceTransformerEmbedder:
    def __init__(self, key: str):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(EMBEDDING_MODELS[key])
        self.query_prefix = BGE_QUERY_PREFIX if key == "bge" else ""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True, batch_size=32,
                                 show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode([self.query_prefix + text], normalize_embeddings=True)[0].tolist()


@lru_cache(maxsize=4)
def get_embedder(key: str):
    if key not in EMBEDDING_MODELS:
        raise ValueError(f"Unknown EMBEDDING_MODEL '{key}'. Use one of {list(EMBEDDING_MODELS)}")
    return HashEmbedder() if key == "hash" else SentenceTransformerEmbedder(key)
