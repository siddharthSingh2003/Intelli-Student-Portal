"""Shared data contracts (Pydantic v2). Agreed by all four members in hour one.

Changing a model here is a team decision: it is the interface between
ingestion (M1), tools (M2), orchestration and the API (M3), and the UI and evaluation (M4).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

AnswerType = Literal[
    "retrieved_fact", "calculated", "not_found",
    "clarification_needed", "refused", "conflict_flagged",
]
DocType = Literal["regulation", "circular", "notice", "faq", "handbook", "unofficial"]


# --------------------------------------------------------------------------- #
# Annex B - Source Register row == metadata for POST /ingest
# --------------------------------------------------------------------------- #
class DocMetadata(BaseModel):
    doc_id: str = Field(min_length=1, max_length=80)
    title: str
    issuer: str
    authority_level: int = Field(ge=1, le=5)
    doc_type: DocType
    version: str = "1"
    effective_from: date
    effective_to: Optional[date] = None
    supersedes: list[str] = Field(default_factory=list)   # "DOC" or "DOC#clause"
    scope_programmes: str = "ALL"
    scope_batches: str = "ALL"
    provenance: str = ""
    retrieved_on: Optional[date] = None
    synthetic: Literal["Y", "N"] = "N"

    @field_validator("supersedes", mode="before")
    @classmethod
    def _split_supersedes(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(";") if s.strip()]
        return [str(s).strip() for s in v if str(s).strip()]

    @field_validator("effective_to", "retrieved_on", mode="before")
    @classmethod
    def _empty_date(cls, v: Any) -> Any:
        return None if v in ("", None) else v

    @field_validator("synthetic", mode="before")
    @classmethod
    def _yn(cls, v: Any) -> str:
        if isinstance(v, bool):
            return "Y" if v else "N"
        return str(v or "N").strip().upper()[:1]

    @field_validator("scope_programmes", "scope_batches", mode="before")
    @classmethod
    def _scope(cls, v: Any) -> str:
        return str(v).strip() if v not in (None, "") else "ALL"

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, v: Any) -> str:
        return str(v) if v not in (None, "") else "1"

    def to_flat(self) -> dict[str, Any]:
        """Flat, string-friendly form used by the CSV register and Chroma metadata."""
        return {
            "doc_id": self.doc_id, "title": self.title, "issuer": self.issuer,
            "authority_level": self.authority_level, "doc_type": self.doc_type,
            "version": self.version, "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else "",
            "supersedes": ";".join(self.supersedes),
            "scope_programmes": self.scope_programmes, "scope_batches": self.scope_batches,
            "provenance": self.provenance,
            "retrieved_on": self.retrieved_on.isoformat() if self.retrieved_on else "",
            "synthetic": self.synthetic,
        }

    @classmethod
    def from_flat(cls, d: dict[str, Any]) -> "DocMetadata":
        return cls.model_validate({k: d.get(k) for k in cls.model_fields if k in d})


class RuleIn(BaseModel):
    """Annex C rule_registry row (also accepted inside POST /ingest metadata)."""
    rule_id: str
    description: str
    parameter: str
    operator: str
    value: str
    scope_programmes: str = "ALL"
    scope_batches: str = "ALL"
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    source_doc_id: str
    source_section: str


class IngestMetadata(DocMetadata):
    rules: list[RuleIn] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Section 6 - API contract
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    as_of_date: Optional[date] = None


class Citation(BaseModel):
    doc_id: str
    title: str
    section: str
    page: Optional[int] = None
    version: str
    effective_from: str


class ToolInvocation(BaseModel):
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]
    status: str = "ok"
    ms: float = 0.0


class AppliedRule(BaseModel):
    rule_id: str
    value: str
    source_doc_id: str
    source_section: Optional[str] = None
    parameter: Optional[str] = None


class ConflictRecord(BaseModel):
    winner: Optional[str] = None          # doc_id / rule_id that applies (None = unresolved)
    overridden: list[str] = Field(default_factory=list)
    step: str                             # Annex A step that decided it
    note: str = ""


class AskResponse(BaseModel):
    trace_id: str
    answer: str
    answer_type: AnswerType
    citations: list[Citation] = Field(default_factory=list)
    tools_invoked: list[ToolInvocation] = Field(default_factory=list)
    applied_rules: list[AppliedRule] = Field(default_factory=list)
    conflicts_detected: list[ConflictRecord] = Field(default_factory=list)
    explanation: str = ""
    assumptions: list[str] = Field(default_factory=list)
    upcoming_changes: list[str] = Field(default_factory=list)
    as_of_date: str


class IngestResponse(BaseModel):
    doc_id: str
    chunks_indexed: int
    status: str
    rules_extracted: int = 0
    rules_added: int = 0
    metadata: Optional[dict[str, Any]] = None        # the Source Register row that was stored
    extracted_by: Optional[dict[str, str]] = None    # per field: llm | pattern | default | admin (auto-extraction only)
