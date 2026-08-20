from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


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
