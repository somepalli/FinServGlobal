# Task 07 — FastAPI service

## Build
`api/main.py` with:
- `POST /query` → `{question, as_of?, jurisdictions?}` → `Answer`
- `POST /screen` → transaction payload → `ComplianceAssessment` (stub until 08)
- `GET /healthz`, `GET /readyz` (readyz checks Qdrant and Postgres)
- `GET /documents` → registry with versions and effective dates

Structured JSON logging via structlog with OpenTelemetry trace_id injected into
every line. Request ID middleware. Every `/query` and `/screen` call writes an
`audit_events` row before returning.

## Acceptance
- OpenAPI schema generates without warnings.
- `readyz` returns 503 when Qdrant is down, and the response says which
  dependency failed.
- Errors return RFC 9457 problem details, never a bare 500 with a stack trace.
