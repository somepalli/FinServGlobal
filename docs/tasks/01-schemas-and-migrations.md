# Task 01 — Schemas and Postgres migrations

Read AGENTS.md and docs/spec.md first.

## Build
- `apps/api/src/compliance/schemas.py` — every model in the spec's Contracts
  section, exactly those field names and types.
- `apps/api/migrations/0001_initial.sql` — the DDL from the spec, plus the
  append-only trigger on `audit_events`.
- `apps/api/src/compliance/db.py` — asyncpg pool built from
  `settings.database_url`, plus `apply_migrations()` that runs any unapplied
  file in `migrations/` in filename order and records them in a
  `schema_migrations` table.

## Acceptance
- `uv run pytest` passes, including a test that an UPDATE on `audit_events`
  raises.
- `mypy --strict` clean.
- Migrations are idempotent: running twice applies nothing the second time.

## Out of scope
ORM, Alembic, seed data.
