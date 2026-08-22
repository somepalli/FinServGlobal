"""Persist a parsed regulatory document and its clauses, versioning as needed."""

from datetime import date
from pathlib import Path
from typing import cast

from compliance.db import DatabaseConnection, DatabasePool
from compliance.schemas import Clause, CorpusDocument, PersistedVersion

_INSERT_DOCUMENT = """
INSERT INTO documents (doc_id, framework, jurisdiction, title, source_url)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (doc_id) DO UPDATE SET
    framework = EXCLUDED.framework,
    jurisdiction = EXCLUDED.jurisdiction,
    title = EXCLUDED.title,
    source_url = EXCLUDED.source_url
"""
_INSERT_VERSION = """
INSERT INTO document_versions
    (version_id, doc_id, version, effective_from, effective_to, supersedes, sha256, object_key)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""
_INSERT_CLAUSE = """
INSERT INTO clauses (clause_id, version_id, clause_path, text, parent_clause_id)
VALUES ($1, $2, $3, $4, NULL)
ON CONFLICT (clause_id) DO NOTHING
"""


class IngestionError(RuntimeError):
    pass


class VersionOrderError(IngestionError):
    pass


def version_id(document: CorpusDocument) -> str:
    return f"{document.doc_id}:{document.version}"


async def _existing_version(
    connection: DatabaseConnection, document: CorpusDocument
) -> PersistedVersion | None:
    row = await connection.fetchrow(
        """
        SELECT current.version_id, predecessor.version AS predecessor_version
        FROM document_versions AS current
        LEFT JOIN document_versions AS predecessor
            ON predecessor.version_id = current.supersedes
        WHERE current.doc_id = $1 AND current.version = $2
        """,
        document.doc_id,
        document.version,
    )
    if row is None:
        return None
    return PersistedVersion(
        version_id=cast(str, row["version_id"]),
        predecessor_version=cast(str | None, row["predecessor_version"]),
    )


async def _active_predecessor(
    connection: DatabaseConnection, document: CorpusDocument
) -> tuple[str, str] | None:
    row = await connection.fetchrow(
        """
        SELECT version_id, version, effective_from
        FROM document_versions
        WHERE doc_id = $1 AND effective_to IS NULL
        ORDER BY effective_from DESC
        LIMIT 1
        FOR UPDATE
        """,
        document.doc_id,
    )
    if row is None:
        return None
    effective_from = cast(date, row["effective_from"])
    if effective_from >= document.effective_from:
        raise VersionOrderError(
            f"{document.doc_id}:{document.version} must start after the active version"
        )
    return cast(str, row["version_id"]), cast(str, row["version"])


def _validate_clauses(document: CorpusDocument, clauses: list[Clause]) -> None:
    if not clauses:
        raise IngestionError(f"{document.doc_id}:{document.version} has no clauses")
    for clause in clauses:
        identity = (clause.doc_id, clause.version, clause.jurisdiction, clause.framework)
        expected = (
            document.doc_id,
            document.version,
            document.jurisdiction,
            document.framework,
        )
        if identity != expected or not clause.clause_path.strip():
            raise IngestionError(f"{clause.clause_id}: clause provenance does not match document")


async def _insert_version(
    connection: DatabaseConnection,
    document: CorpusDocument,
    source: Path,
    predecessor_id: str | None,
) -> None:
    await connection.execute(
        _INSERT_VERSION,
        version_id(document),
        document.doc_id,
        document.version,
        document.effective_from,
        document.effective_to,
        predecessor_id,
        document.sha256,
        str(source),
    )


async def _insert_clauses(
    connection: DatabaseConnection, document: CorpusDocument, clauses: list[Clause]
) -> None:
    arguments: list[tuple[object, ...]] = [
        (clause.clause_id, version_id(document), clause.clause_path, clause.text)
        for clause in clauses
    ]
    await connection.executemany(_INSERT_CLAUSE, arguments)


async def persist_document(
    pool: DatabasePool,
    document: CorpusDocument,
    source: Path,
    clauses: list[Clause],
) -> PersistedVersion:
    _validate_clauses(document, clauses)
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            _INSERT_DOCUMENT,
            document.doc_id,
            document.framework,
            document.jurisdiction,
            document.title,
            str(document.source_url),
        )
        existing = await _existing_version(connection, document)
        if existing is not None:
            await _insert_clauses(connection, document, clauses)
            return existing
        predecessor = await _active_predecessor(connection, document)
        predecessor_id = predecessor[0] if predecessor is not None else None
        await _insert_version(connection, document, source, predecessor_id)
        if predecessor_id is not None:
            await connection.execute(
                "UPDATE document_versions SET effective_to = $1 WHERE version_id = $2",
                document.effective_from,
                predecessor_id,
            )
        await _insert_clauses(connection, document, clauses)
    return PersistedVersion(
        version_id=version_id(document),
        predecessor_version=predecessor[1] if predecessor is not None else None,
    )
