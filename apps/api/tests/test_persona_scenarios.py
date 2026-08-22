"""End-to-end checks against the persona scenarios in the project brief.

Each test drives the real FastAPI app (compliance.api.main.create_app) through
TestClient, exercising routing, auth, the agent graph, and the reporting layer
together. Qdrant/Postgres/the LLM are replaced with fakes so the suite runs
without external infrastructure; retrieval content for the fakes is drawn from
the committed corpus manifest and sample transactions so the scenarios stay
representative of real usage.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import TracebackType

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
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

_TEST_API_KEY = "persona-test-key"
_AUTH = {"X-API-Key": _TEST_API_KEY}
_ROOT = Path(__file__).resolve().parents[3]


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
    """Stands in for Postgres: records writes, answers audit/report reads."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.rows: list[dict[str, object]] = []
        self.audit_rows: dict[int, dict[str, object]] = {}
        self._next_event_id = 1

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append((query, args))
        if "audit_events" in query and "screen.completed" in str(args):
            self.audit_rows[self._next_event_id] = {
                "event_id": self._next_event_id,
                "actor": args[0],
                "action": args[1],
                "subject_id": args[2],
                "payload": json.loads(str(args[3])),
                "at": datetime(2026, 8, 21, tzinfo=UTC),
            }
            self._next_event_id += 1
        return "INSERT 0 1"

    async def executemany(self, query: str, args: list[tuple[object, ...]]) -> None:
        return None

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        if "FROM audit_events" in query:
            return [dict(row) for row in reversed(self.audit_rows.values())]
        if "payload->>'risk_rating'" in query:
            return [{"risk_rating": "high", "count": 1, "unresolved": 0}]
        if "generate_series" in query:
            return [{"day": date(2026, 8, 21), "queries": 1, "screenings": 4}]
        if "documents" in query:
            return self.rows
        return [{"day": date(2026, 8, 21), "queries": 1, "screenings": 4}]

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        if "screen.completed" not in query:
            return None
        event_id = args[1]
        if event_id is None and self.audit_rows:
            return self.audit_rows[max(self.audit_rows)]
        return self.audit_rows.get(int(str(event_id))) if event_id is not None else None

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
    def collection_exists(self, collection_name: str) -> bool:
        return True


class _RerankerModel:
    def compute_score(
        self,
        sentence_pairs: list[list[str]],
        *,
        batch_size: int,
        max_length: int,
        normalize: bool,
    ) -> list[float]:
        return [0.97 for _pair in sentence_pairs]


def _basel_clause() -> RetrievedClause:
    clause = Clause(
        clause_id="basel3-d424:2017:52",
        doc_id="basel3-d424",
        version="2017",
        jurisdiction="GLOBAL",
        framework="Basel III",
        clause_path="Section 4 > 52",
        text=(
            "Common Equity Tier 1 capital must be maintained at a minimum of 4.5% "
            "of risk-weighted assets at all times."
        ),
        effective_from=date(2017, 12, 7),
        effective_to=None,
    )
    return RetrievedClause(clause=clause, dense_score=0.91, sparse_score=0.84, rerank_score=0.97)


class _Searcher:
    """Q&A search fake: always returns the Tier 1 capital adequacy clause."""

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
        return [_basel_clause()]


class _ScreeningSearcher:
    """Screening search fake: returns a clause tagged to the requested framework."""

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
        framework = (frameworks or ["RBI"])[0]
        jurisdiction = (jurisdictions or ["IN"])[0]
        safe = framework.lower().replace(" ", "-")
        clause = Clause(
            clause_id=f"{safe}:v1:1",
            doc_id=f"{safe}-document",
            version="v1",
            jurisdiction=jurisdiction,
            framework=framework,
            clause_path="Part I > 1",
            text="Regulated entities must apply enhanced controls for this transaction type.",
            effective_from=date(2020, 1, 1),
            effective_to=None,
        )
        return [
            RetrievedClause(clause=clause, dense_score=0.9, sparse_score=0.8, rerank_score=0.95)
        ]


class _Generator:
    async def generate(self, question: str, clauses: list[RetrievedClause]) -> str:
        return "Tier 1 common equity must be at least 4.5% of risk-weighted assets."


class _Extractor:
    """Extraction fake: mimics parsing the spec's example sentence into fields."""

    async def extract(self, description: str) -> TransactionPayload:
        assert description
        return TransactionPayload(
            txn_id="desc-cross-border-1",
            amount=Decimal("2000000"),
            currency="USD",
            jurisdictions=["IN"],
            instrument="cross-border payment",
            kyc_status=False,
            high_risk_jurisdiction=True,
        )


def _app_and_state() -> tuple[TestClient, _Connection]:
    settings = Settings(database_url="postgresql://u:p@localhost/db", api_key=_TEST_API_KEY)
    connection = _Connection()
    pool = _Pool(connection)
    reranker = BgeReranker(settings, model=_RerankerModel())
    audit = AuditRepository(pool)
    services = ApiServices(
        query=QueryService(_Searcher(), reranker, _Generator(), settings),
        audit=audit,
        documents=DocumentRepository(pool),
        readiness=DependencyChecker(pool, _QdrantHealth(), settings),
        screening=build_agent(_ScreeningSearcher(), audit, settings, MemorySaver()),
        reports=PostureReportRepository(pool),
        extractor=_Extractor(),
    )
    app = create_app(settings=settings, services=services)
    return TestClient(app), connection


# ---------------------------------------------------------------------------
# Scenario 1 (Compliance Officer): natural-language regulatory Q&A
# ---------------------------------------------------------------------------


def test_scenario_regulatory_qa_returns_cited_versioned_answer() -> None:
    client, _connection = _app_and_state()
    with client:
        response = client.post(
            "/query",
            json={
                "question": (
                    "What are the capital adequacy requirements for Tier 1 "
                    "under Basel III as amended in 2023?"
                )
            },
            headers=_AUTH,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["citations"], "answer must carry at least one citation"
    citation = body["citations"][0]
    assert citation["clause_id"] == "basel3-d424:2017:52"
    assert citation["effective_from"] == "2017-12-07"
    assert body["as_of"]


# ---------------------------------------------------------------------------
# Scenario 2 (Compliance Officer): transaction screening against real samples
# ---------------------------------------------------------------------------


def test_scenario_transaction_screening_flags_regulations_and_risk() -> None:
    client, connection = _app_and_state()
    expected_risk = {
        "sample-complex-product": "high",
        "sample-cross-border-payment": "high",
        "sample-intra-group-derivative": "high",
        "sample-nbfc-lending": "low",
    }
    input_files = sorted((_ROOT / "samples" / "input").glob("*.json"))
    assert len(input_files) == 4

    with client:
        for input_file in input_files:
            payload = TransactionPayload.model_validate_json(
                input_file.read_text(encoding="utf-8")
            )
            response = client.post(
                "/screen", json=payload.model_dump(mode="json"), headers=_AUTH
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["risk_rating"] == expected_risk[payload.txn_id]
            assert body["applicable_regulations"]
            assert body["citations"]

    screen_actions = [args[1] for _query, args in connection.executed if len(args) > 1]
    assert screen_actions.count("screen.completed") == 4


def test_scenario_transaction_screening_accepts_a_free_text_description() -> None:
    """The brief's literal example: a sentence, not a JSON payload."""
    client, connection = _app_and_state()

    with client:
        response = client.post(
            "/screen/from-description",
            json={
                "description": (
                    "Cross-border payment of $2M to a non-KYC entity in a high-risk "
                    "jurisdiction"
                )
            },
            headers=_AUTH,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["risk_rating"] == "high"
    assert body["applicable_regulations"]
    assert body["citations"]

    actions = [args[1] for _query, args in connection.executed if len(args) > 1]
    assert "screen.extracted" in actions
    assert "screen.completed" in actions


# ---------------------------------------------------------------------------
# Scenario 3 (Compliance Head): regulatory change impact analysis
# ---------------------------------------------------------------------------

# No test here: the API exposes no endpoint, service, or agent tool that takes
# a newly ingested document and reports which existing policies or transaction
# types it affects. `CorpusDocument.covers` (schemas.py) tags each source
# document with the transaction types it governs, but nothing reads that field
# outside of `samples/` test fixtures (compliance.ingest.run only persists it).
# This scenario from the brief has no corresponding implementation to test.


# ---------------------------------------------------------------------------
# Scenario 4 (Compliance Head): structured compliance posture report
# ---------------------------------------------------------------------------


def test_scenario_posture_report_is_structured_for_audit_submission() -> None:
    client, _connection = _app_and_state()
    with client:
        response = client.get(
            "/reports/posture",
            params={"start": "2026-08-15", "end": "2026-08-21"},
            headers=_AUTH,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == {"start": "2026-08-15", "end": "2026-08-21"}
    assert "activity" in body and "risk_distribution" in body
    assert "unresolved_screenings" in body


# ---------------------------------------------------------------------------
# Internal Auditor: audit trail with citations, and decision replay
# ---------------------------------------------------------------------------


def test_scenario_audit_trail_records_and_replays_ai_assisted_decisions() -> None:
    client, _connection = _app_and_state()
    payload = TransactionPayload.model_validate_json(
        (_ROOT / "samples" / "input" / "cross-border-payment.json").read_text(encoding="utf-8")
    )

    with client:
        screen_response = client.post(
            "/screen", json=payload.model_dump(mode="json"), headers=_AUTH
        )
        assert screen_response.status_code == 200

        events_response = client.get(
            "/audit/events", params={"subject_id": payload.txn_id}, headers=_AUTH
        )
        assert events_response.status_code == 200

        decision_response = client.get(f"/audit/decisions/{payload.txn_id}", headers=_AUTH)

    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert decision["transaction"]["txn_id"] == payload.txn_id
    assert decision["assessment"]["citations"], "auditor must be able to see cited sources"


def test_scenario_protected_routes_reject_unauthenticated_auditor_access() -> None:
    client, _connection = _app_and_state()
    with client:
        response = client.get("/audit/events")

    assert response.status_code == 401
