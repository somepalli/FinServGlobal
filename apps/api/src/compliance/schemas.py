from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class Clause(BaseModel):
    clause_id: str
    doc_id: str
    version: str
    jurisdiction: Literal["IN", "EU", "US", "GLOBAL"]
    framework: str
    clause_path: str = Field(min_length=1, pattern=r"\S")
    text: str
    effective_from: date
    effective_to: date | None


class DocumentMetadata(BaseModel):
    doc_id: str
    version: str
    jurisdiction: Literal["IN", "EU", "US", "GLOBAL"]
    framework: str
    effective_from: date
    effective_to: date | None = None


class DocumentNode(BaseModel):
    title: str = Field(min_length=1)
    number: str | None = None
    content: list[str] = Field(default_factory=list)
    children: list["DocumentNode"] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    title: str = Field(min_length=1)
    content: list[str] = Field(default_factory=list)
    children: list[DocumentNode] = Field(default_factory=list)


class ClauseEmbedding(BaseModel):
    clause_id: str
    dense: list[float] = Field(min_length=1)
    sparse_indices: list[int]
    sparse_values: list[float]

    @model_validator(mode="after")
    def sparse_components_align(self) -> "ClauseEmbedding":
        if len(self.sparse_indices) != len(self.sparse_values):
            raise ValueError("sparse indices and values must have equal lengths")
        return self


class QueryEmbedding(BaseModel):
    dense: list[float] = Field(min_length=1)
    sparse_indices: list[int]
    sparse_values: list[float]

    @model_validator(mode="after")
    def sparse_components_align(self) -> "QueryEmbedding":
        if len(self.sparse_indices) != len(self.sparse_values):
            raise ValueError("sparse indices and values must have equal lengths")
        return self


class CorpusDocument(BaseModel):
    doc_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    framework: str
    jurisdiction: Literal["IN", "EU", "US", "GLOBAL"]
    title: str
    version: str
    effective_from: date
    effective_to: date | None = None
    source_url: HttpUrl
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    covers: list[str] = Field(default_factory=list)


class CorpusManifest(BaseModel):
    documents: list[CorpusDocument] = Field(min_length=1)


class IngestionResult(BaseModel):
    documents: int
    clauses_persisted: int
    clauses_indexed: int
    clauses_skipped: int


class PersistedVersion(BaseModel):
    version_id: str
    predecessor_version: str | None = None


class RetrievedClause(BaseModel):
    clause: Clause
    dense_score: float
    sparse_score: float
    rerank_score: float | None


class Citation(BaseModel):
    clause_id: str
    clause_path: str
    quote: str
    support: float = Field(ge=0.0, le=1.0)


class Answer(BaseModel):
    text: str
    citations: list[Citation]
    synthesised: bool
    as_of: date


class RiskRating(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class ComplianceAssessment(BaseModel):
    txn_id: str
    risk_rating: RiskRating
    applicable_regulations: list[str]
    required_actions: list[str]
    citations: list[Citation]
    unresolved_questions: list[str]
    model_version: str
    prompt_version: str
