"""Central configuration. Every value can be overridden with an environment variable.

Values are read lazily (properties), so tests and the evaluation harness can change
environment variables at runtime and compare configurations in a single process.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# Embedding models allowed by the hackathon guide (Section 5). "hash" is an offline
# bag-of-words embedder used ONLY by the test-suite / CI, never for real answers.
EMBEDDING_MODELS = {
    "minilm": "sentence-transformers/all-MiniLM-L6-v2",
    "bge": "BAAI/bge-small-en-v1.5",
    "hash": "hash-384",
}

# Cosine-similarity floor below which retrieval is treated as "no evidence".
# Calibrated per model because bge produces higher similarities for unrelated text.
DEFAULT_MIN_SCORE = {"minilm": 0.30, "bge": 0.55, "hash": 0.05}


@dataclass(frozen=True)
class RetrievalConfig:
    """Everything that changes the index or the retrieval result. Compared in eval."""

    embedding: str = "minilm"          # minilm | bge | hash
    chunk_strategy: str = "section"    # section | fixed
    chunk_size: int = 900              # characters
    chunk_overlap: int = 150
    top_k: int = 6

    @classmethod
    def from_env(cls) -> "RetrievalConfig":
        return cls(
            embedding=os.getenv("EMBEDDING_MODEL", "minilm"),
            chunk_strategy=os.getenv("CHUNK_STRATEGY", "section"),
            chunk_size=int(os.getenv("CHUNK_SIZE", "900")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
            top_k=int(os.getenv("TOP_K", "6")),
        )

    @classmethod
    def parse(cls, spec: str) -> "RetrievalConfig":
        """'bge:section:900:6' -> RetrievalConfig. Used by the eval CLI."""
        emb, strat, size, k = (spec.split(":") + ["", "", "", ""])[:4]
        base = cls.from_env()
        return cls(
            embedding=emb or base.embedding,
            chunk_strategy=strat or base.chunk_strategy,
            chunk_size=int(size or base.chunk_size),
            chunk_overlap=base.chunk_overlap,
            top_k=int(k or base.top_k),
        )

    @property
    def collection_name(self) -> str:
        # one Chroma collection per index-affecting config, so switching never mixes vectors
        return f"chunks_{self.embedding}_{self.chunk_strategy}_{self.chunk_size}"

    @property
    def label(self) -> str:
        return f"{self.embedding}/{self.chunk_strategy}/{self.chunk_size}/k{self.top_k}"


class Settings:
    # ---- LLM -------------------------------------------------------------
    @property
    def mock_llm(self) -> bool:
        return _env_bool("MOCK_LLM")

    @property
    def llm_model(self) -> str:
        return os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")

    @property
    def ollama_url(self) -> str:
        # 127.0.0.1, not localhost: on Windows each localhost request first waits ~2s on IPv6
        return os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

    @property
    def llm_timeout(self) -> float:
        return float(os.getenv("LLM_TIMEOUT", "120"))

    @property
    def llm_max_retries(self) -> int:
        return int(os.getenv("LLM_MAX_RETRIES", "2"))

    @property
    def llm_think(self) -> bool:
        # only affects reasoning models (qwen3, deepseek-r1...): true is slower, sometimes more accurate
        return _env_bool("LLM_THINK")

    @property
    def llm_keep_alive(self) -> str:
        # keeps the model in memory between questions; Ollama's default unloads it after 5 minutes
        return os.getenv("LLM_KEEP_ALIVE", "30m")

    # Cloud fallback: OFF by default, OpenAI-compatible endpoint, disclosed in README.
    @property
    def cloud_fallback(self) -> bool:
        return _env_bool("CLOUD_FALLBACK")

    @property
    def cloud_base_url(self) -> str:
        return os.getenv("CLOUD_BASE_URL", "").rstrip("/")

    @property
    def cloud_api_key(self) -> str:
        return os.getenv("CLOUD_API_KEY", "")

    @property
    def cloud_model(self) -> str:
        return os.getenv("CLOUD_MODEL", "")

    # ---- Auth --------------------------------------------------------------
    @property
    def auth_required(self) -> bool:
        # false = legacy contract: identity taken from the X-Student-Id header without a login
        return _env_bool("AUTH_REQUIRED", True)

    @property
    def jwt_secret(self) -> str:
        env = os.getenv("JWT_SECRET")
        if env:
            return env
        path = self.storage_dir / "jwt_secret"      # generated once, so tokens survive a restart
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_hex(32))
        return path.read_text().strip()

    @property
    def jwt_expire_minutes(self) -> int:
        return int(os.getenv("JWT_EXPIRE_MINUTES", "120"))

    @property
    def initial_password(self) -> str:
        # first-login password of a student who has no credentials row yet
        return os.getenv("INITIAL_PASSWORD", "Pass@{student_id}")

    @property
    def admin_username(self) -> str:
        return os.getenv("ADMIN_USERNAME", "admin").strip().lower()

    @property
    def admin_password(self) -> str:
        # password of the admin account created on first start, when there is no admin yet
        return os.getenv("ADMIN_PASSWORD", "Admin@123")

    # ---- Storage -----------------------------------------------------------
    @property
    def storage_dir(self) -> Path:
        return Path(os.getenv("STORAGE_DIR", ROOT / "storage"))

    @property
    def sqlite_path(self) -> Path:
        return Path(os.getenv("SQLITE_PATH", self.storage_dir / "university.db"))

    @property
    def chroma_dir(self) -> Path:
        return Path(os.getenv("CHROMA_DIR", self.storage_dir / "chroma"))

    @property
    def uploads_dir(self) -> Path:
        return Path(os.getenv("UPLOADS_DIR", self.storage_dir / "uploads"))

    @property
    def register_csv(self) -> Path:
        return Path(os.getenv("REGISTER_CSV", ROOT / "docs" / "source_register.csv"))

    @property
    def rules_seed_csv(self) -> Path:
        return Path(os.getenv("RULES_SEED_CSV", ROOT / "data" / "seed" / "rules_seed.csv"))

    @property
    def students_dir(self) -> Path:
        return Path(os.getenv("STUDENTS_DIR", ROOT / "data" / "generated"))

    def min_score(self, embedding: str) -> float:
        env = os.getenv("MIN_RETRIEVAL_SCORE")
        return float(env) if env else DEFAULT_MIN_SCORE.get(embedding, 0.3)


settings = Settings()
