import os
from datetime import date
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest
from compliance.agent.graph import PostgresScreeningService, build_agent
from compliance.api.service import AuditRepository
from compliance.config.settings import Settings
from compliance.db import apply_migrations, create_pool
from compliance.schemas import (
    AuditEventInput,
    Clause,
    RetrievedClause,
    RiskRating,
    TransactionPayload,
)
from langgraph.checkpoint.memory import MemorySaver


class _Audit:
    def __init__(self) -> None:
        self.events: list[AuditEventInput] = []

    async def write(self, event: AuditEventInput) -> None:
        self.events.append(event)


class _Search:
    def __init__(self, *, empty_text: bool = False) -> None:
        self.calls: list[tuple[list[str] | None, list[str] | None]] = []
        self._empty_text = empty_text

    async def search(
        self,
        query: str,
        *,
        as_of: date | None = None,
        jurisdictions: list[str] | None = None,
        frameworks: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedClause]:
        assert query
        self.calls.append((jurisdictions, frameworks))
        framework = (frameworks or ["RBI"])[0]
        jurisdiction = (jurisdictions or ["IN"])[0]
        text = (
            ""
            if self._empty_text
            else "Customer records require transaction monitoring controls."
        )
        return [_retrieved(framework, jurisdiction, text)]


def _retrieved(framework: str, jurisdiction: str, text: str) -> RetrievedClause:
    safe_framework = framework.lower().replace(" ", "-")
    clause = Clause(
        clause_id=f"{safe_framework}:v1:1",
        doc_id=f"{safe_framework}-document",
        version="v1",
        jurisdiction=jurisdiction,
        framework=framework,
        clause_path="Part I > 1",
        text=text,
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )
    return RetrievedClause(
        clause=clause,
        dense_score=0.9,
        sparse_score=0.8,
        rerank_score=0.95,
    )


def _settings(database_url: str = "postgresql://u:p@localhost/db") -> Settings:
    return Settings(database_url=database_url)


def _payload(*, kyc_status: bool | None = None) -> TransactionPayload:
    return TransactionPayload(
        txn_id="txn-agent-1",
        amount=Decimal("250000.00"),
        currency="EUR",
        counterparty_type="corporate",
        jurisdictions=["IN", "EU"],
        instrument="cross-border payment",
        kyc_status=kyc_status,
    )


@pytest.mark.asyncio
async def test_graph_caps_missing_kyc_and_replays_by_thread_id() -> None:
    search = _Search()
    audit = _Audit()
    agent = build_agent(search, audit, _settings(), MemorySaver())

    assessment = await agent.assess(_payload(), thread_id="thread-kyc")
    replayed = await agent.replay("thread-kyc")

    assert assessment == replayed
    assert assessment.risk_rating is RiskRating.MEDIUM
    assert "Provide kyc_status." in assessment.unresolved_questions
    assert search.calls == [(["IN"], ["RBI"]), (["EU"], ["MiFID II"])]
    assert [event.action for event in audit.events] == [
        "agent.extract.completed",
        "agent.classify.completed",
        "agent.retrieve.completed",
        "agent.cross_reference.completed",
        "agent.assess.completed",
        "agent.validate.completed",
    ]
    mermaid = agent.mermaid()
    assert all(node in mermaid for node in ("extract", "cross_reference", "validate"))


@pytest.mark.asyncio
async def test_validation_retries_once_then_returns_source_free_fallback() -> None:
    audit = _Audit()
    agent = build_agent(_Search(empty_text=True), audit, _settings(), MemorySaver())

    assessment = await agent.assess(_payload(kyc_status=True), thread_id="thread-retry")

    actions = [event.action for event in audit.events]
    assert actions.count("agent.assess.completed") == 2
    assert actions.count("agent.validate.completed") == 2
    assert not assessment.citations
    assert not assessment.required_actions
    assert assessment.unresolved_questions
    assert assessment.prompt_version == "source-actions-v1-fallback"


def _test_database_url() -> str:
    value = os.getenv("COMPLIANCE_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("COMPLIANCE_TEST_DATABASE_URL is required for checkpoint tests")
    return value


def _schema_url(database_url: str, schema: str) -> str:
    separator = "&" if "?" in database_url else "?"
    return f"{database_url}{separator}options=-csearch_path%3D{schema}"


@pytest.mark.asyncio
async def test_postgres_checkpointer_persists_across_agent_instances() -> None:
    database_url = _test_database_url()
    schema = f"test_{uuid4().hex}"
    admin = await asyncpg.connect(database_url)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    pool = await create_pool(_settings(database_url), server_settings={"search_path": schema})
    try:
        await apply_migrations(pool)
        service = PostgresScreeningService(
            _Search(), AuditRepository(pool), _settings(_schema_url(database_url, schema))
        )
        assessment = await service.assess(_payload(kyc_status=True), thread_id="persisted")
        replayed = await service.replay("persisted")
        assert assessment == replayed
        async with pool.acquire() as connection:
            assert await connection.fetchval("SELECT count(*) FROM audit_events") == 6
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
