"""Expose query, screening, registry, and health endpoints."""

import hmac
import re
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import cast
from uuid import uuid4

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from opentelemetry import trace
from pydantic import JsonValue
from qdrant_client import QdrantClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import StatelessLifespan

from compliance.agent.extraction import TransactionExtractionError
from compliance.api.service import ApiServices, create_services
from compliance.config.settings import Settings, get_settings
from compliance.db import create_pool
from compliance.schemas import (
    Answer,
    AuditDecision,
    AuditEvent,
    AuditEventInput,
    ComplianceAssessment,
    DocumentInfo,
    HealthStatus,
    PostureReport,
    ProblemDetail,
    QueryRequest,
    ReadinessStatus,
    ReplayComparison,
    TransactionDescriptionRequest,
    TransactionPayload,
)

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LOGGER = structlog.get_logger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_api_key(
    request: Request, provided: str | None = Security(_API_KEY_HEADER)
) -> None:
    expected = cast("str | None", getattr(request.app.state, "api_key", None))
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")


def _add_trace_id(
    _logger: object, _method: str, event: MutableMapping[str, object]
) -> MutableMapping[str, object]:
    context = trace.get_current_span().get_span_context()
    event["trace_id"] = format(context.trace_id, "032x") if context.is_valid else None
    return event


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_id,
            structlog.processors.JSONRenderer(),
        ]
    )


def _request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "")
    return supplied if _REQUEST_ID.fullmatch(supplied) else str(uuid4())


def _services(request: Request) -> ApiServices:
    return cast(ApiServices, request.app.state.services)


def _problem(request: Request, status: int, title: str, detail: str) -> JSONResponse:
    problem = ProblemDetail(
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        request_id=cast(str, request.state.request_id),
    )
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )


def _lifespan(
    configured_settings: Settings | None, configured_services: ApiServices | None
) -> StatelessLifespan[FastAPI]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if configured_services is not None:
            app.state.services = configured_services
            app.state.api_key = (
                configured_settings.api_key.get_secret_value()
                if configured_settings is not None and configured_settings.api_key is not None
                else None
            )
            yield
            return
        settings = configured_settings or get_settings()
        pool = await create_pool(settings)
        qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key_value)
        app.state.services = create_services(settings, pool, qdrant)
        app.state.api_key = (
            settings.api_key.get_secret_value() if settings.api_key is not None else None
        )
        try:
            yield
        finally:
            qdrant.close()
            await pool.close()

    return lifespan


def _install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id(request)
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        _LOGGER.info("request_started", method=request.method, path=request.url.path)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        _LOGGER.info("request_completed", status_code=response.status_code)
        structlog.contextvars.clear_contextvars()
        return response


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(request, 422, "Request validation failed", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(request, exc.status_code, "Request failed", str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        _LOGGER.exception("unhandled_exception", error_type=type(exc).__name__)
        return _problem(request, 500, "Internal server error", "The request could not be completed")


def _install_read_routes(app: FastAPI) -> None:
    @app.get("/healthz", response_model=HealthStatus)
    async def healthz() -> HealthStatus:
        return HealthStatus()

    @app.get("/readyz", response_model=ReadinessStatus)
    async def readyz(request: Request) -> ReadinessStatus | JSONResponse:
        status = await _services(request).readiness.check()
        if status.status == "not_ready":
            return JSONResponse(status_code=503, content=status.model_dump(mode="json"))
        return status

    @app.get(
        "/documents",
        response_model=list[DocumentInfo],
        dependencies=[Depends(_require_api_key)],
    )
    async def documents(request: Request) -> list[DocumentInfo]:
        return await _services(request).documents.list_documents()

    @app.get(
        "/reports/posture",
        response_model=PostureReport,
        dependencies=[Depends(_require_api_key)],
    )
    async def posture_report(
        request: Request, start: date | None = None, end: date | None = None
    ) -> PostureReport:
        report_end = end or date.today()
        report_start = start or report_end - timedelta(days=6)
        return await _services(request).reports.build(report_start, report_end)

    @app.get(
        "/audit/events",
        response_model=list[AuditEvent],
        dependencies=[Depends(_require_api_key)],
    )
    async def audit_events(
        request: Request,
        subject_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[AuditEvent]:
        return await _services(request).audit.list_events(subject_id, limit)

    @app.get(
        "/audit/decisions/{subject_id}",
        response_model=AuditDecision,
        dependencies=[Depends(_require_api_key)],
    )
    async def audit_decision(subject_id: str, request: Request) -> AuditDecision:
        try:
            return await _services(request).audit.decision(subject_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get(
        "/audit/decisions/{subject_id}/replay",
        response_model=ReplayComparison,
        dependencies=[Depends(_require_api_key)],
    )
    async def replay_comparison(
        subject_id: str,
        request: Request,
        original_event_id: int,
        replay_event_id: int,
    ) -> ReplayComparison:
        try:
            return await _services(request).audit.compare(
                subject_id, original_event_id, replay_event_id
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


async def _screen_and_audit(
    request: Request, payload: TransactionPayload
) -> ComplianceAssessment:
    assessment = await _services(request).screening.assess(payload, thread_id=payload.txn_id)
    event = AuditEventInput(
        actor="api",
        action="screen.completed",
        subject_id=payload.txn_id,
        payload=cast(
            JsonValue,
            {
                "risk_rating": assessment.risk_rating.value,
                "unresolved_questions": len(assessment.unresolved_questions),
                "applicable_regulations": assessment.applicable_regulations,
                "transaction": payload.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
            },
        ),
    )
    await _services(request).audit.write(event)
    return assessment


def _install_action_routes(app: FastAPI) -> None:
    @app.post("/query", response_model=Answer, dependencies=[Depends(_require_api_key)])
    async def query(payload: QueryRequest, request: Request) -> Answer:
        answer = await _services(request).query.answer(payload)
        event = AuditEventInput(
            actor="api",
            action="query.completed",
            subject_id=cast(str, request.state.request_id),
            payload={
                "question": payload.question,
                "as_of": answer.as_of.isoformat(),
                "synthesised": answer.synthesised,
                "citation_ids": [item.clause_id for item in answer.citations],
            },
        )
        await _services(request).audit.write(event)
        return answer

    @app.post(
        "/screen", response_model=ComplianceAssessment, dependencies=[Depends(_require_api_key)]
    )
    async def screen(payload: TransactionPayload, request: Request) -> ComplianceAssessment:
        return await _screen_and_audit(request, payload)

    @app.post(
        "/screen/from-description",
        response_model=ComplianceAssessment,
        dependencies=[Depends(_require_api_key)],
    )
    async def screen_from_description(
        payload: TransactionDescriptionRequest, request: Request
    ) -> ComplianceAssessment:
        try:
            transaction = await _services(request).extractor.extract(payload.description)
        except TransactionExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await _services(request).audit.write(
            AuditEventInput(
                actor="api",
                action="screen.extracted",
                subject_id=transaction.txn_id,
                payload={"description": payload.description},
            )
        )
        return await _screen_and_audit(request, transaction)


def create_app(*, settings: Settings | None = None, services: ApiServices | None = None) -> FastAPI:
    configure_logging()
    app = FastAPI(title="FinServGlobal Compliance API", lifespan=_lifespan(settings, services))
    _install_middleware(app)
    _install_error_handlers(app)
    _install_read_routes(app)
    _install_action_routes(app)
    return app


app = create_app()
