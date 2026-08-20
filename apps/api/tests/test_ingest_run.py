import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from compliance.config.settings import Settings
from compliance.db import apply_migrations, create_pool
from compliance.ingest.run import load_ingestion_manifest, persist_document
from compliance.schemas import Clause, CorpusDocument


def _test_database_url() -> str:
    database_url = os.getenv("COMPLIANCE_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("COMPLIANCE_TEST_DATABASE_URL is required for ingestion tests")
    return database_url


def _document(version: str, effective_from: date) -> CorpusDocument:
    return CorpusDocument(
        doc_id="test-regulation",
        framework="RBI",
        jurisdiction="IN",
        title="Test Regulation",
        version=version,
        effective_from=effective_from,
        source_url="https://regulator.example/regulation.pdf",
        sha256="a" * 64,
    )


def _clause(document: CorpusDocument) -> Clause:
    return Clause(
        clause_id=f"{document.doc_id}:{document.version}:1",
        doc_id=document.doc_id,
        version=document.version,
        jurisdiction=document.jurisdiction,
        framework=document.framework,
        clause_path="Chapter I > 1",
        text="A regulated entity must retain the record.",
        effective_from=document.effective_from,
        effective_to=document.effective_to,
    )


def test_repository_manifest_declares_effective_dates() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = load_ingestion_manifest(root / "data" / "corpus" / "manifest.yaml")

    assert len(manifest.documents) == 5
    assert all(document.effective_from for document in manifest.documents)


@pytest.mark.asyncio
async def test_persistence_is_idempotent_and_closes_superseded_version() -> None:
    database_url = _test_database_url()
    schema = f"test_{uuid4().hex}"
    admin = await asyncpg.connect(database_url)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    settings = Settings(database_url=database_url)
    pool = await create_pool(settings, server_settings={"search_path": f'"{schema}"'})
    first = _document("v1", date(2020, 1, 1))
    second = _document("v2", date(2021, 1, 1))
    try:
        await apply_migrations(pool)
        await persist_document(pool, first, Path("v1.pdf"), [_clause(first)])
        await persist_document(pool, first, Path("v1.pdf"), [_clause(first)])
        persisted = await persist_document(pool, second, Path("v2.pdf"), [_clause(second)])
        async with pool.acquire() as connection:
            versions = await connection.fetchval("SELECT count(*) FROM document_versions")
            clauses = await connection.fetchval("SELECT count(*) FROM clauses")
            closed = await connection.fetchval(
                "SELECT effective_to FROM document_versions WHERE version = 'v1'"
            )
        assert (versions, clauses) == (2, 2)
        assert closed == date(2021, 1, 1)
        assert persisted.predecessor_version == "v1"
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()
