import os
from uuid import uuid4

import asyncpg
import pytest
from compliance.config.settings import Settings
from compliance.db import apply_migrations, create_pool


def _test_database_url() -> str:
    database_url = os.getenv("COMPLIANCE_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("COMPLIANCE_TEST_DATABASE_URL is required for migration tests")
    return database_url


@pytest.mark.asyncio
async def test_migrations_are_idempotent_and_audit_events_are_append_only() -> None:
    database_url = _test_database_url()
    schema = f"test_{uuid4().hex}"
    admin_connection = await asyncpg.connect(database_url)
    await admin_connection.execute(f'CREATE SCHEMA "{schema}"')
    settings = Settings(database_url=database_url)
    pool = await create_pool(settings, server_settings={"search_path": f'"{schema}"'})
    try:
        assert await apply_migrations(pool) == ["0001_initial.sql"]
        assert await apply_migrations(pool) == []
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO audit_events (actor, action, subject_id, payload) "
                "VALUES ('tester', 'created', 'subject-1', '{}')"
            )
            with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="append-only"):
                await connection.execute(
                    "UPDATE audit_events SET action = 'changed' WHERE subject_id = 'subject-1'"
                )
            with pytest.raises(asyncpg.ObjectNotInPrerequisiteStateError, match="append-only"):
                await connection.execute(
                    "DELETE FROM audit_events WHERE subject_id = 'subject-1'"
                )
    finally:
        await pool.close()
        await admin_connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin_connection.close()
