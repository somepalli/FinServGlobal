from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue, model_validator


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


class TextPair(BaseModel):
    query: str = Field(min_length=1)
    passage: str = Field(min_length=1)


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
    effective_from: date | None = None
    effective_to: date | None = None


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


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    as_of: date | None = None
    jurisdictions: list[Literal["IN", "EU", "US", "GLOBAL"]] | None = None


class TransactionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    txn_id: str = Field(min_length=1)
    amount: Decimal | None = None
    currency: str | None = None
    counterparty_type: str | None = None
    jurisdictions: list[Literal["IN", "EU", "US", "GLOBAL"]] | None = None
    instrument: str | None = None
    kyc_status: bool | None = None
    high_risk_jurisdiction: bool | None = None
    large_exposure_threshold_exceeded: bool | None = None
    appropriateness_assessed: bool | None = None
    priority_sector_reporting_required: bool | None = None


class TransactionFacts(BaseModel):
    txn_id: str
    amount: Decimal | None
    currency: str | None
    counterparty_type: str | None
    jurisdictions: list[Literal["IN", "EU", "US", "GLOBAL"]]
    instrument: str | None
    kyc_status: bool | None
    missing_fields: list[str]
    high_risk_jurisdiction: bool | None = None
    large_exposure_threshold_exceeded: bool | None = None
    appropriateness_assessed: bool | None = None
    priority_sector_reporting_required: bool | None = None


class FrameworkTarget(BaseModel):
    framework: str
    jurisdiction: Literal["IN", "EU", "US", "GLOBAL"]


class FrameworkScope(BaseModel):
    targets: list[FrameworkTarget]


class RetrievalRequest(BaseModel):
    query: str
    framework: str
    jurisdiction: Literal["IN", "EU", "US", "GLOBAL"]
    top_k: int = Field(gt=0)


class FrameworkRetrieval(BaseModel):
    target: FrameworkTarget
    clauses: list[RetrievedClause]


class CrossReference(BaseModel):
    frameworks: list[str] = Field(min_length=2)
    clause_ids: list[str] = Field(min_length=2)
    shared_terms: list[str]


class CitationValidation(BaseModel):
    valid: bool
    problems: list[str]


class SampleAssessment(BaseModel):
    name: str
    expected_doc_id: str
    assessment: ComplianceAssessment


class DependencyStatus(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class ReadinessStatus(BaseModel):
    status: Literal["ready", "not_ready"]
    dependencies: list[DependencyStatus]


class HealthStatus(BaseModel):
    status: Literal["ok"] = "ok"


class DocumentVersionInfo(BaseModel):
    version: str
    effective_from: date
    effective_to: date | None = None
    supersedes: str | None = None


class DocumentInfo(BaseModel):
    doc_id: str
    framework: str
    jurisdiction: Literal["IN", "EU", "US", "GLOBAL"]
    title: str
    source_url: str
    versions: list[DocumentVersionInfo]


class AuditEventInput(BaseModel):
    actor: str
    action: str
    subject_id: str
    payload: JsonValue


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str
    request_id: str
