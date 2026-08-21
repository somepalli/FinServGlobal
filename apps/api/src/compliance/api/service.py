"""Compose API workflows and persistence services."""

import asyncio
import json
from datetime import date
from typing import Literal, Protocol, cast

import asyncpg  # type: ignore[import-untyped]  # The package has no PEP 561 marker.
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from compliance.agent.graph import PostgresScreeningService
from compliance.config.settings import Settings
from compliance.db import DatabasePool
from compliance.retrieval.answer import LocalLlmGenerator, build_answer
from compliance.retrieval.embed import BgeM3Embedder
from compliance.retrieval.rerank import BgeReranker
from compliance.retrieval.search import HybridSearcher
from compliance.schemas import (
    Answer,
    AuditEventInput,
    ComplianceAssessment,
    DependencyStatus,
    DocumentInfo,
    DocumentVersionInfo,
    QueryRequest,
    ReadinessStatus,
    RetrievedClause,
    TextPair,
    TransactionPayload,
)


class _Searcher(Protocol):
    async def search(
        self,
        query: str,
        *,
        as_of: date | None = None,
        jurisdictions: list[str] | None = None,
        frameworks: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedClause]: ...


class _Reranker(Protocol):
    def rerank(self, query: str, clauses: list[RetrievedClause]) -> list[RetrievedClause]: ...

    def score_pairs(self, pairs: list[TextPair]) -> list[float]: ...


class _Generator(Protocol):
    async def generate(self, question: str, clauses: list[RetrievedClause]) -> str: ...


class _QdrantHealth(Protocol):
    def collection_exists(self, collection_name: str) -> bool: ...


class _Screening(Protocol):
    async def assess(
        self, payload: TransactionPayload, *, thread_id: str
    ) -> ComplianceAssessment: ...


class QueryService:
    def __init__(
        self,
        searcher: _Searcher,
        reranker: _Reranker,
        generator: _Generator,
        settings: Settings,
    ) -> None:
        self._searcher = searcher
        self._reranker = reranker
        self._generator = generator
        self._settings = settings
        self._query_lock = asyncio.Lock()

    async def answer(self, request: QueryRequest) -> Answer:
        async with self._query_lock:
            return await self._answer(request)

    async def _answer(self, request: QueryRequest) -> Answer:
        jurisdictions = cast(list[str] | None, request.jurisdictions)
        retrieved = await self._searcher.search(
            request.question,
            as_of=request.as_of,
            jurisdictions=jurisdictions,
        )
        reranked = await asyncio.to_thread(self._reranker.rerank, request.question, retrieved)
        return await build_answer(
            request.question,
            reranked,
            self._settings,
            as_of=request.as_of,
            generator=self._generator,
            scorer=self._reranker,
        )


class AuditRepository:
    def __init__(self, pool: DatabasePool) -> None:
        self._pool = pool

    async def write(self, event: AuditEventInput) -> None:
        payload = json.dumps(event.payload, separators=(",", ":"))
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO audit_events (actor, action, subject_id, payload)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                event.actor,
                event.action,
                event.subject_id,
                payload,
            )


class DocumentRepository:
    def __init__(self, pool: DatabasePool) -> None:
        self._pool = pool

    async def list_documents(self) -> list[DocumentInfo]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT d.doc_id, d.framework, d.jurisdiction, d.title, d.source_url,
                       v.version, v.effective_from, v.effective_to, v.supersedes
                FROM documents AS d
                LEFT JOIN document_versions AS v ON v.doc_id = d.doc_id
                ORDER BY d.doc_id, v.effective_from
                """
            )
        documents: dict[str, DocumentInfo] = {}
        for row in rows:
            doc_id = cast(str, row["doc_id"])
            if doc_id not in documents:
                documents[doc_id] = self._document(row)
            if row["version"] is not None:
                documents[doc_id].versions.append(self._version(row))
        return list(documents.values())

    @staticmethod
    def _document(row: object) -> DocumentInfo:
        values = cast("_Row", row)
        return DocumentInfo(
            doc_id=cast(str, values["doc_id"]),
            framework=cast(str, values["framework"]),
            jurisdiction=cast(Literal["IN", "EU", "US", "GLOBAL"], values["jurisdiction"]),
            title=cast(str, values["title"]),
            source_url=cast(str, values["source_url"]),
            versions=[],
        )

    @staticmethod
    def _version(row: object) -> DocumentVersionInfo:
        values = cast("_Row", row)
        return DocumentVersionInfo(
            version=cast(str, values["version"]),
            effective_from=cast(date, values["effective_from"]),
            effective_to=cast(date | None, values["effective_to"]),
            supersedes=cast(str | None, values["supersedes"]),
        )


class _Row(Protocol):
    def __getitem__(self, key: str) -> object: ...


class DependencyChecker:
    def __init__(self, pool: DatabasePool, qdrant: _QdrantHealth, settings: Settings) -> None:
        self._pool = pool
        self._qdrant = qdrant
        self._settings = settings

    async def check(self) -> ReadinessStatus:
        postgres, qdrant = await asyncio.gather(self._postgres_status(), self._qdrant_status())
        dependencies = [postgres, qdrant]
        if all(item.healthy for item in dependencies):
            return ReadinessStatus(status="ready", dependencies=dependencies)
        return ReadinessStatus(status="not_ready", dependencies=dependencies)

    async def _postgres_status(self) -> DependencyStatus:
        try:
            async with self._pool.acquire() as connection:
                await connection.fetchval("SELECT 1")
        except (OSError, asyncpg.PostgresError) as exc:
            return DependencyStatus(name="postgres", healthy=False, detail=str(exc))
        return DependencyStatus(name="postgres", healthy=True)

    async def _qdrant_status(self) -> DependencyStatus:
        try:
            exists = await asyncio.to_thread(
                self._qdrant.collection_exists, self._settings.qdrant_collection
            )
        except (OSError, ResponseHandlingException, UnexpectedResponse) as exc:
            return DependencyStatus(name="qdrant", healthy=False, detail=str(exc))
        detail = None if exists else "regulations collection is unavailable"
        return DependencyStatus(name="qdrant", healthy=exists, detail=detail)


class ApiServices:
    def __init__(
        self,
        query: QueryService,
        audit: AuditRepository,
        documents: DocumentRepository,
        readiness: DependencyChecker,
        screening: _Screening,
    ) -> None:
        self.query = query
        self.audit = audit
        self.documents = documents
        self.readiness = readiness
        self.screening = screening


def create_services(settings: Settings, pool: DatabasePool, qdrant: QdrantClient) -> ApiServices:
    embedder = BgeM3Embedder(settings)
    reranker = BgeReranker(settings)
    searcher = HybridSearcher(qdrant, embedder, settings)
    audit = AuditRepository(pool)
    query = QueryService(
        searcher,
        reranker,
        LocalLlmGenerator(settings),
        settings,
    )
    return ApiServices(
        query=query,
        audit=audit,
        documents=DocumentRepository(pool),
        readiness=DependencyChecker(pool, qdrant, settings),
        screening=PostgresScreeningService(searcher, audit, settings),
    )
