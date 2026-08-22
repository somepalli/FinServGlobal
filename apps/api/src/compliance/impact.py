"""Determine which transaction types and past decisions a document change affects."""

from datetime import datetime
from typing import cast

from compliance.config.settings import Settings
from compliance.corpus_manifest import load_ingestion_manifest
from compliance.db import DatabasePool, DatabaseRow
from compliance.schemas import (
    AffectedAssessment,
    ClauseChange,
    CorpusDocument,
    RegulatoryChangeImpact,
    RiskRating,
)

_CURRENT_VERSION_SQL = """
    SELECT version_id, version, supersedes
    FROM document_versions
    WHERE doc_id = $1 AND effective_to IS NULL
    ORDER BY effective_from DESC
    LIMIT 1
"""

_VERSION_BY_ID_SQL = "SELECT version FROM document_versions WHERE version_id = $1"

_CLAUSE_TEXT_SQL = "SELECT clause_path, text FROM clauses WHERE version_id = $1"

_AFFECTED_ASSESSMENTS_SQL = """
    SELECT event_id, subject_id AS txn_id,
           payload->'assessment'->>'risk_rating' AS risk_rating, at
    FROM audit_events
    WHERE action = 'screen.completed'
      AND EXISTS (
          SELECT 1
          FROM jsonb_array_elements(payload->'assessment'->'citations') AS citation
          WHERE citation->>'clause_id' LIKE $1
      )
    ORDER BY at DESC
"""


class DocumentNotIndexedError(LookupError):
    """Raised when a document has no indexed version or manifest entry to analyze."""


async def _clause_texts(pool: DatabasePool, version_id: str) -> dict[str, str]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(_CLAUSE_TEXT_SQL, version_id)
    texts: dict[str, str] = {}
    for row in rows:
        path = cast(str, row["clause_path"])
        text = cast(str, row["text"])
        texts[path] = f"{texts[path]}\n\n{text}" if path in texts else text
    return texts


def _diff(old_texts: dict[str, str], new_texts: dict[str, str]) -> list[ClauseChange]:
    changes: list[ClauseChange] = []
    for path in sorted(set(old_texts) | set(new_texts)):
        old_text = old_texts.get(path)
        new_text = new_texts.get(path)
        if old_text == new_text:
            continue
        if old_text is None:
            changes.append(ClauseChange(clause_path=path, change_type="added", new_text=new_text))
        elif new_text is None:
            changes.append(
                ClauseChange(clause_path=path, change_type="removed", old_text=old_text)
            )
        else:
            changes.append(
                ClauseChange(
                    clause_path=path, change_type="modified", old_text=old_text, new_text=new_text
                )
            )
    return changes


async def diff_clauses(
    pool: DatabasePool, old_version_id: str, new_version_id: str
) -> list[ClauseChange]:
    """Compare clause text by clause_path across two versions of the same document.

    Matching by clause_path rather than clause_id: clause_id embeds the version
    string, so it is never stable across a version bump. A source that renumbers
    a section between versions will show as a spurious remove+add rather than a
    modification - a known limitation, not a bug.
    """
    old_texts = await _clause_texts(pool, old_version_id)
    new_texts = await _clause_texts(pool, new_version_id)
    return _diff(old_texts, new_texts)


async def affected_assessments(
    pool: DatabasePool, doc_id: str, version: str
) -> list[AffectedAssessment]:
    """Find every screened transaction that cited a clause under doc_id:version."""
    prefix = f"{doc_id}:{version}:%"
    async with pool.acquire() as connection:
        rows = await connection.fetch(_AFFECTED_ASSESSMENTS_SQL, prefix)
    return [_affected_assessment(row) for row in rows]


def _affected_assessment(row: DatabaseRow) -> AffectedAssessment:
    return AffectedAssessment(
        event_id=cast(int, row["event_id"]),
        txn_id=cast(str, row["txn_id"]),
        risk_rating=RiskRating(cast(str, row["risk_rating"])),
        assessed_at=cast(datetime, row["at"]),
    )


class DocumentImpactAnalyzer:
    def __init__(self, pool: DatabasePool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    async def for_ingested_document(
        self,
        document: CorpusDocument,
        new_version_id: str,
        predecessor_version_id: str | None,
        predecessor_version: str | None,
    ) -> RegulatoryChangeImpact:
        return await self._build(
            document.doc_id,
            document.covers,
            new_version_id,
            document.version,
            predecessor_version_id,
            predecessor_version,
        )

    async def for_current_version(self, doc_id: str) -> RegulatoryChangeImpact:
        async with self._pool.acquire() as connection:
            current = await connection.fetchrow(_CURRENT_VERSION_SQL, doc_id)
        if current is None:
            raise DocumentNotIndexedError(f"no indexed version for {doc_id}")
        predecessor_version_id = cast("str | None", current["supersedes"])
        predecessor_version = await self._version_of(predecessor_version_id)
        document = self._manifest_document(doc_id)
        return await self._build(
            doc_id,
            document.covers,
            cast(str, current["version_id"]),
            cast(str, current["version"]),
            predecessor_version_id,
            predecessor_version,
        )

    async def _version_of(self, version_id: str | None) -> str | None:
        if version_id is None:
            return None
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(_VERSION_BY_ID_SQL, version_id)
        return cast(str, row["version"]) if row is not None else None

    def _manifest_document(self, doc_id: str) -> CorpusDocument:
        manifest = load_ingestion_manifest(self._settings.corpus_manifest)
        document = next((item for item in manifest.documents if item.doc_id == doc_id), None)
        if document is None:
            raise DocumentNotIndexedError(f"{doc_id} is not present in the corpus manifest")
        return document

    async def _build(
        self,
        doc_id: str,
        covers: list[str],
        new_version_id: str,
        new_version: str,
        predecessor_version_id: str | None,
        predecessor_version: str | None,
    ) -> RegulatoryChangeImpact:
        changed_clauses = (
            await diff_clauses(self._pool, predecessor_version_id, new_version_id)
            if predecessor_version_id is not None
            else []
        )
        assessments = (
            await affected_assessments(self._pool, doc_id, predecessor_version)
            if predecessor_version is not None
            else []
        )
        return RegulatoryChangeImpact(
            doc_id=doc_id,
            new_version=new_version,
            previous_version=predecessor_version,
            affected_transaction_types=covers,
            changed_clauses=changed_clauses,
            affected_assessments=assessments,
        )
