"""Run the reproducible corpus ingestion pipeline."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from compliance.audit import AuditRepository
from compliance.config.settings import Settings, get_settings
from compliance.corpus_manifest import ManifestError
from compliance.corpus_manifest import load_ingestion_manifest as _load_manifest
from compliance.db import DatabasePool, apply_migrations, create_pool
from compliance.impact import DocumentImpactAnalyzer
from compliance.ingest.chunk import chunk_document
from compliance.ingest.fetch import fetch_corpus
from compliance.ingest.parse import parse_document
from compliance.ingest.persist import IngestionError, VersionOrderError, persist_document
from compliance.ingest.persist import version_id as _version_id
from compliance.retrieval.embed import BgeM3Embedder
from compliance.retrieval.store import RegulationStore, create_store
from compliance.schemas import (
    AuditEventInput,
    CorpusDocument,
    CorpusManifest,
    DocumentMetadata,
    IngestionResult,
)

__all__ = [
    "IngestionError",
    "VersionOrderError",
    "load_ingestion_manifest",
    "main",
    "persist_document",
    "run_ingestion",
]


class IngestionManifestError(IngestionError):
    pass


def load_ingestion_manifest(path: Path) -> CorpusManifest:
    try:
        return _load_manifest(path)
    except ManifestError as exc:
        raise IngestionManifestError(str(exc)) from exc


def _metadata(document: CorpusDocument) -> DocumentMetadata:
    return DocumentMetadata(
        doc_id=document.doc_id,
        version=document.version,
        jurisdiction=document.jurisdiction,
        framework=document.framework,
        effective_from=document.effective_from,
        effective_to=document.effective_to,
    )


def _source_by_id(paths: list[Path]) -> dict[str, Path]:
    return {path.stem: path for path in paths}


async def _record_impact(
    pool: DatabasePool,
    settings: Settings,
    audit: AuditRepository,
    document: CorpusDocument,
    predecessor_version: str,
) -> None:
    predecessor_version_id = f"{document.doc_id}:{predecessor_version}"
    impact = await DocumentImpactAnalyzer(pool, settings).for_ingested_document(
        document, _version_id(document), predecessor_version_id, predecessor_version
    )
    await audit.write(
        AuditEventInput(
            actor="ingestion",
            action="document.impact.completed",
            subject_id=_version_id(document),
            payload=cast(JsonValue, impact.model_dump(mode="json")),
        )
    )


async def _ingest_document(
    document: CorpusDocument,
    source: Path,
    pool: DatabasePool,
    settings: Settings,
    audit: AuditRepository,
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
        await _record_impact(pool, settings, audit, document, persisted.predecessor_version)
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
    audit = AuditRepository(active_pool)
    persisted = indexed = 0
    try:
        await apply_migrations(active_pool)
        for document in manifest.documents:
            source = sources.get(document.doc_id)
            if source is None:
                raise IngestionError(f"fetched source is missing for {document.doc_id}")
            clause_count, indexed_count = await _ingest_document(
                document, source, active_pool, settings, audit, active_store,
                active_embedder, resume,
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
