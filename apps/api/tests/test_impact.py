from datetime import UTC, date, datetime
from types import TracebackType

import pytest
from compliance.config.settings import Settings
from compliance.impact import (
    DocumentImpactAnalyzer,
    DocumentNotIndexedError,
    affected_assessments,
    diff_clauses,
)
from compliance.schemas import CorpusDocument


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.current_version_row: dict[str, object] | None = None
        self.version_rows: dict[str, dict[str, object]] = {}
        self.clause_rows: dict[str, list[dict[str, object]]] = {}
        self.assessment_rows: list[dict[str, object]] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        if "FROM clauses" in query:
            return self.clause_rows.get(args[0], [])  # type: ignore[index]
        if "jsonb_array_elements" in query:
            return self.assessment_rows
        raise AssertionError(f"unexpected fetch query: {query}")

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        if "effective_to IS NULL" in query:
            return self.current_version_row
        if "FROM document_versions WHERE version_id" in query:
            return self.version_rows.get(args[0])  # type: ignore[index]
        raise AssertionError(f"unexpected fetchrow query: {query}")


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _AsyncContext:
        return _AsyncContext(self.connection)


def _settings() -> Settings:
    return Settings(database_url="postgresql://u:p@localhost/db")


@pytest.mark.asyncio
async def test_diff_clauses_classifies_added_removed_and_modified() -> None:
    connection = _Connection()
    connection.clause_rows = {
        "doc:v1": [
            {"clause_path": "1", "text": "old text"},
            {"clause_path": "2", "text": "unchanged text"},
            {"clause_path": "3", "text": "removed clause text"},
        ],
        "doc:v2": [
            {"clause_path": "1", "text": "new text"},
            {"clause_path": "2", "text": "unchanged text"},
            {"clause_path": "4", "text": "added clause text"},
        ],
    }

    changes = await diff_clauses(_Pool(connection), "doc:v1", "doc:v2")

    by_path = {change.clause_path: change for change in changes}
    assert set(by_path) == {"1", "3", "4"}
    assert by_path["1"].change_type == "modified"
    assert by_path["1"].old_text == "old text"
    assert by_path["1"].new_text == "new text"
    assert by_path["3"].change_type == "removed"
    assert by_path["4"].change_type == "added"


@pytest.mark.asyncio
async def test_for_ingested_document_skips_diff_and_assessments_without_a_predecessor() -> None:
    document = CorpusDocument(
        doc_id="new-doc",
        framework="RBI",
        jurisdiction="IN",
        title="New Regulation",
        version="v1",
        effective_from=date(2024, 1, 1),
        source_url="https://regulator.example/reg.pdf",
        sha256="a" * 64,
        covers=["cross-border-payment"],
    )
    connection = _Connection()
    analyzer = DocumentImpactAnalyzer(_Pool(connection), _settings())

    impact = await analyzer.for_ingested_document(document, "new-doc:v1", None, None)

    assert impact.previous_version is None
    assert impact.changed_clauses == []
    assert impact.affected_assessments == []
    assert impact.affected_transaction_types == ["cross-border-payment"]


@pytest.mark.asyncio
async def test_for_current_version_raises_when_nothing_is_indexed() -> None:
    connection = _Connection()
    connection.current_version_row = None
    analyzer = DocumentImpactAnalyzer(_Pool(connection), _settings())

    with pytest.raises(DocumentNotIndexedError):
        await analyzer.for_current_version("rbi-kyc-md")


@pytest.mark.asyncio
async def test_for_current_version_reads_covers_from_the_real_manifest() -> None:
    connection = _Connection()
    connection.current_version_row = {
        "version_id": "rbi-kyc-md:2016-amended",
        "version": "2016-amended",
        "supersedes": None,
    }
    analyzer = DocumentImpactAnalyzer(_Pool(connection), _settings())

    impact = await analyzer.for_current_version("rbi-kyc-md")

    assert set(impact.affected_transaction_types) == {
        "cross-border-payment",
        "non-kyc-counterparty",
    }
    assert impact.previous_version is None


@pytest.mark.asyncio
async def test_affected_assessments_projects_txn_id_and_risk_rating() -> None:
    connection = _Connection()
    connection.assessment_rows = [
        {
            "event_id": 1,
            "txn_id": "txn-1",
            "risk_rating": "high",
            "at": datetime(2026, 8, 1, tzinfo=UTC),
        }
    ]

    results = await affected_assessments(_Pool(connection), "doc-id", "v1")

    assert len(results) == 1
    assert results[0].txn_id == "txn-1"
    assert results[0].risk_rating.value == "high"
