from collections.abc import Sequence
from datetime import UTC, date, datetime
from types import TracebackType
from warnings import catch_warnings, simplefilter

from compliance.agent.extraction import TransactionExtractionError
from compliance.agent.graph import build_agent
from compliance.api.main import create_app
from compliance.api.service import (
    ApiServices,
    AuditRepository,
    DependencyChecker,
    DocumentRepository,
    QueryService,
)
from compliance.config.settings import Settings
from compliance.reporting import PostureReportRepository
from compliance.retrieval.rerank import BgeReranker
from compliance.schemas import Clause, RetrievedClause, TransactionPayload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver


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
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.fail_execute = False
        self.rows: list[dict[str, object]] = [
            {
                "doc_id": "rbi-kyc",
                "framework": "RBI",
                "jurisdiction": "IN",
                "title": "KYC Direction",
                "source_url": "https://regulator.example/kyc.pdf",
                "version": "v1",
                "effective_from": date(2020, 1, 1),
                "effective_to": None,
                "supersedes": None,
            }
        ]
        self.audit_rows: dict[int, dict[str, object]] = {}

    async def execute(self, query: str, *args: object) -> str:
        if self.fail_execute:
            raise OSError("database unavailable")
        self.executed.append((query, args))
        return "INSERT 0 1"

    async def executemany(self, query: str, args: list[tuple[object, ...]]) -> None:
        return None

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        return self.rows

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        if "screen.completed" not in query:
            return None
        event_id = args[1]
        if event_id is None and self.audit_rows:
            return self.audit_rows[max(self.audit_rows)]
        return self.audit_rows.get(int(str(event_id)))

    async def fetchval(self, query: str, *args: object) -> int:
        return 1

    def transaction(self) -> _AsyncContext:
        return _AsyncContext(None)


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection

    def acquire(self) -> _AsyncContext:
        return _AsyncContext(self._connection)

    async def close(self) -> None:
        return None


class _QdrantHealth:
    def __init__(self, *, healthy: bool) -> None:
        self._healthy = healthy

    def collection_exists(self, collection_name: str) -> bool:
        assert collection_name == "regulations"
        if not self._healthy:
            raise OSError("connection refused")
        return True


class _Searcher:
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
        return [_retrieved()]


class _Generator:
    async def generate(self, question: str, clauses: list[RetrievedClause]) -> str:
        return "Banks must retain records for five years."


class _UnavailableGenerator:
    async def generate(self, question: str, clauses: list[RetrievedClause]) -> str:
        raise OSError("LLM unavailable")


class _Extractor:
    async def extract(self, description: str) -> TransactionPayload:
        assert description
        return TransactionPayload(txn_id="txn-extracted-1", currency="USD")


class _RerankerModel:
    def compute_score(
        self,
        sentence_pairs: list[list[str]],
        *,
        batch_size: int,
        max_length: int,
        normalize: bool,
    ) -> float | Sequence[float]:
        return [0.99 for _pair in sentence_pairs]


def _retrieved() -> RetrievedClause:
    clause = Clause(
        clause_id="rbi-kyc:v1:52",
        doc_id="rbi-kyc",
        version="v1",
        jurisdiction="IN",
        framework="RBI",
        clause_path="Chapter VII > 52",
        text="Banks must retain records for five years.",
        effective_from=date(2020, 1, 1),
        effective_to=None,
    )
    return RetrievedClause(
        clause=clause,
        dense_score=0.8,
        sparse_score=0.7,
        rerank_score=None,
    )


TEST_API_KEY = "test-only-api-key"
_AUTH_HEADERS = {"X-API-Key": TEST_API_KEY}


def _authed_app(services: ApiServices) -> FastAPI:
    settings = Settings(database_url="postgresql://u:p@localhost/db", api_key=TEST_API_KEY)
    return create_app(settings=settings, services=services)


def _services(*, qdrant_healthy: bool = True) -> tuple[ApiServices, _Connection]:
    settings = Settings(database_url="postgresql://u:p@localhost/db")
    connection = _Connection()
    pool = _Pool(connection)
    reranker = BgeReranker(settings, model=_RerankerModel())
    audit = AuditRepository(pool)
    services = ApiServices(
        query=QueryService(
            _Searcher(),
            reranker,
            _Generator() if qdrant_healthy else _UnavailableGenerator(),
            settings,
        ),
        audit=audit,
        documents=DocumentRepository(pool),
        readiness=DependencyChecker(pool, _QdrantHealth(healthy=qdrant_healthy), settings),
        screening=build_agent(_Searcher(), audit, settings, MemorySaver()),
        reports=PostureReportRepository(pool),
        extractor=_Extractor(),
    )
    return services, connection


def _audit_decision_row(event_id: int, risk_rating: str = "high") -> dict[str, object]:
    assessment = {
        "txn_id": "txn-audit",
        "risk_rating": risk_rating,
        "applicable_regulations": ["RBI"],
        "required_actions": ["Review transaction."],
        "citations": [],
        "unresolved_questions": [],
        "model_version": "model-a",
        "prompt_version": "prompt-a",
    }
    return {
        "event_id": event_id,
        "actor": "api",
        "action": "screen.completed",
        "subject_id": "txn-audit",
        "payload": {"transaction": {"txn_id": "txn-audit"}, "assessment": assessment},
        "at": datetime(2026, 8, 21, tzinfo=UTC),
    }


def test_openapi_schema_generates_without_warnings() -> None:
    services, _connection = _services()
    app = create_app(services=services)

    with catch_warnings(record=True) as warnings:
        simplefilter("always")
        schema = app.openapi()

    assert not warnings
    expected = {
        "/query",
        "/screen",
        "/readyz",
        "/documents",
        "/reports/posture",
        "/audit/events",
        "/audit/decisions/{subject_id}",
        "/audit/decisions/{subject_id}/replay",
    }
    assert expected <= set(schema["paths"])


def test_readyz_names_failed_qdrant_dependency() -> None:
    services, _connection = _services(qdrant_healthy=False)

    with TestClient(create_app(services=services)) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    qdrant = next(item for item in response.json()["dependencies"] if item["name"] == "qdrant")
    assert not qdrant["healthy"]
    assert "connection refused" in qdrant["detail"]


def test_protected_routes_reject_requests_without_an_api_key() -> None:
    services, _connection = _services()

    with TestClient(_authed_app(services)) as client:
        response = client.post("/query", json={"question": "How long?"})

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_protected_routes_reject_an_incorrect_api_key() -> None:
    services, _connection = _services()

    with TestClient(_authed_app(services)) as client:
        response = client.get("/documents", headers={"X-API-Key": "wrong-key"})

    assert response.status_code == 401


def test_query_returns_answer_and_writes_audit_event() -> None:
    services, connection = _services()

    with TestClient(_authed_app(services)) as client:
        response = client.post(
            "/query",
            json={"question": "How long must records be retained?"},
            headers={**_AUTH_HEADERS, "X-Request-ID": "request-1"},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-1"
    assert response.json()["citations"][0]["quote"] == _retrieved().clause.text
    assert connection.executed
    assert connection.executed[0][1][1] == "query.completed"


def test_screen_runs_agent_and_writes_audit_events() -> None:
    services, connection = _services()

    with TestClient(_authed_app(services)) as client:
        response = client.post(
            "/screen", json={"txn_id": "txn-1", "currency": "USD"}, headers=_AUTH_HEADERS
        )

    assert response.status_code == 200
    assert response.json()["risk_rating"] == "medium"
    actions = [args[1] for _query, args in connection.executed]
    assert "agent.extract.completed" in actions
    assert "agent.validate.completed" in actions
    assert "screen.completed" in actions
    screen_event = next(
        args for _query, args in connection.executed if args[1] == "screen.completed"
    )
    assert '"risk_rating":"medium"' in str(screen_event[3])


def test_screen_from_description_extracts_then_runs_the_same_pipeline() -> None:
    services, connection = _services()

    with TestClient(_authed_app(services)) as client:
        response = client.post(
            "/screen/from-description",
            json={"description": "Cross-border payment of $2M to a non-KYC entity."},
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.json()["txn_id"] == "txn-extracted-1"
    actions = [args[1] for _query, args in connection.executed]
    assert "screen.extracted" in actions
    assert "screen.completed" in actions


def test_screen_from_description_rejects_an_unparseable_description() -> None:
    class _FailingExtractor:
        async def extract(self, description: str) -> TransactionPayload:
            raise TransactionExtractionError("local LLM returned no choices")

    services, _connection = _services()
    services.extractor = _FailingExtractor()  # type: ignore[assignment]

    with TestClient(_authed_app(services)) as client:
        response = client.post(
            "/screen/from-description",
            json={"description": "garbled input"},
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_validation_errors_use_problem_details() -> None:
    services, _connection = _services()

    with TestClient(_authed_app(services)) as client:
        response = client.post("/query", json={}, headers=_AUTH_HEADERS)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Request validation failed"


def test_not_found_errors_use_problem_details() -> None:
    services, _connection = _services()

    with TestClient(create_app(services=services)) as client:
        response = client.get("/missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 404


def test_unexpected_errors_hide_stack_traces() -> None:
    services, connection = _services()
    connection.fail_execute = True

    with TestClient(_authed_app(services), raise_server_exceptions=False) as client:
        response = client.post("/screen", json={"txn_id": "txn-1"}, headers=_AUTH_HEADERS)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "The request could not be completed"
    assert "traceback" not in response.text.lower()


def test_documents_returns_version_registry() -> None:
    services, _connection = _services()

    with TestClient(_authed_app(services)) as client:
        response = client.get("/documents", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()[0]["versions"][0]["effective_from"] == "2020-01-01"


def test_audit_decision_works_with_qdrant_and_llm_unavailable() -> None:
    services, connection = _services(qdrant_healthy=False)
    connection.audit_rows[11] = _audit_decision_row(11)

    with TestClient(_authed_app(services)) as client:
        response = client.get("/audit/decisions/txn-audit", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["assessment"]["risk_rating"] == "high"
    assert response.json()["transaction"]["txn_id"] == "txn-audit"


def test_replay_divergence_is_returned_as_an_audit_outcome() -> None:
    services, connection = _services(qdrant_healthy=False)
    connection.audit_rows[11] = _audit_decision_row(11)
    connection.audit_rows[12] = _audit_decision_row(12, "blocked")

    with TestClient(_authed_app(services)) as client:
        response = client.get(
            "/audit/decisions/txn-audit/replay",
            params={"original_event_id": 11, "replay_event_id": 12},
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.json()["outcome"] == "diverged"
    assert response.json()["differences"][0]["field"] == "risk_rating"
