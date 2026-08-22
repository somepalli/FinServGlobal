"""Run the reproducible corpus ingestion pipeline."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import cast

import yaml  # type: ignore[import-untyped]  # PyYAML does not publish a PEP 561 marker.
from pydantic import ValidationError

from compliance.config.settings import Settings, get_settings
from compliance.db import DatabaseConnection, DatabasePool, apply_migrations, create_pool
from compliance.ingest.chunk import chunk_document
from compliance.ingest.fetch import fetch_corpus
from compliance.ingest.parse import parse_document
from compliance.retrieval.embed import BgeM3Embedder
from compliance.retrieval.store import RegulationStore, create_store
from compliance.schemas import (
    Clause,
    CorpusDocument,
    CorpusManifest,
    DocumentMetadata,
    IngestionResult,
    PersistedVersion,
)

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


class IngestionManifestError(IngestionError):
    pass


class VersionOrderError(IngestionError):
    pass


def load_ingestion_manifest(path: Path) -> CorpusManifest:
    try:
        return CorpusManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise IngestionManifestError(f"manifest does not exist: {path}") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise IngestionManifestError(f"invalid ingestion manifest {path}: {exc}") from exc


def _metadata(document: CorpusDocument) -> DocumentMetadata:
    return DocumentMetadata(
        doc_id=document.doc_id,
        version=document.version,
        jurisdiction=document.jurisdiction,
        framework=document.framework,
        effective_from=document.effective_from,
        effective_to=document.effective_to,
    )


def _version_id(document: CorpusDocument) -> str:
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
        _version_id(document),
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
        (clause.clause_id, _version_id(document), clause.clause_path, clause.text)
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
        version_id=_version_id(document),
        predecessor_version=predecessor[1] if predecessor is not None else None,
    )


def _source_by_id(paths: list[Path]) -> dict[str, Path]:
    return {path.stem: path for path in paths}


async def _ingest_document(
    document: CorpusDocument,
    source: Path,
    pool: DatabasePool,
    store: RegulationStore,
    embedder: BgeM3Embedder,
    resume: bool,
) -> tuple[int, int]:
    parsed = await asyncio.to_thread(parse_document, source)
    clauses = await asyncio.to_thread(chunk_document, parsed, _metadata(document))
    persisted = await persist_document(pool, document, source, clauses)
    await asyncio.to_thread(store.ensure_collection)
    if persisted.predecessor_version is not None:
        await asyncio.to_thread(
            store.close_version,
            document.doc_id,
            persisted.predecessor_version,
            document.effective_from,
        )
    missing = await asyncio.to_thread(
        store.missing_clause_ids, [clause.clause_id for clause in clauses]
    )
    selected = [clause for clause in clauses if not resume or clause.clause_id in missing]
    embedded = await asyncio.to_thread(embedder.embed, selected)
    await asyncio.to_thread(store.upsert, selected, embedded)
    return len(clauses), len(selected)


async def run_ingestion(
    settings: Settings,
    *,
    resume: bool = False,
    pool: DatabasePool | None = None,
    store: RegulationStore | None = None,
    embedder: BgeM3Embedder | None = None,
) -> IngestionResult:
    manifest = load_ingestion_manifest(settings.corpus_manifest)
    sources = _source_by_id(fetch_corpus(settings))
    active_pool = pool or await create_pool(settings)
    active_store = store or create_store(settings)
    active_embedder = embedder or BgeM3Embedder(settings)
    persisted = indexed = 0
    try:
        await apply_migrations(active_pool)
        for document in manifest.documents:
            source = sources.get(document.doc_id)
            if source is None:
                raise IngestionError(f"fetched source is missing for {document.doc_id}")
            clause_count, indexed_count = await _ingest_document(
                document, source, active_pool, active_store, active_embedder, resume
            )
            persisted += clause_count
            indexed += indexed_count
    finally:
        if pool is None:
            await active_pool.close()
    return IngestionResult(
        documents=len(manifest.documents),
        clauses_persisted=persisted,
        clauses_indexed=indexed,
        clauses_skipped=persisted - indexed,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest the regulatory corpus")
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(run_ingestion(get_settings(), resume=args.resume))
    except IngestionError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
