# Task 14 — Audit trail and replay comparison

## Build

Expose Postgres-backed endpoints to list audit events, retrieve a complete recorded
transaction decision, and compare two recorded decisions for the same transaction.
The stored decision contains the transaction input and full assessment, including
citations and model and prompt versions.

Audit reads must not call Qdrant or the LLM. They remain available when either
dependency is down. Replay comparison reports `match` or `diverged`; divergence is
an audit finding rather than a request error.

## Acceptance

- A complete decision can be read while Qdrant and the LLM are unavailable.
- Event listing supports subject filtering and a bounded result limit.
- Replay comparison identifies every changed assessment field.
- A divergent replay returns a successful response with a `diverged` outcome.
- The architecture document states why replay divergence is retained.
