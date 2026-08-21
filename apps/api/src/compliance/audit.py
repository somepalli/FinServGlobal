"""Persist and inspect the append-only audit record."""

import json
from datetime import datetime
from typing import cast

from pydantic import JsonValue

from compliance.db import DatabasePool, DatabaseRow
from compliance.schemas import (
    AuditDecision,
    AuditEvent,
    AuditEventInput,
    ComplianceAssessment,
    ReplayComparison,
    ReplayDifference,
    TransactionPayload,
)


class AuditRecordNotFoundError(LookupError):
    """Raised when a requested persisted audit record does not exist."""


class AuditRepository:
    def __init__(self, pool: DatabasePool) -> None:
        self._pool = pool

    async def write(self, event: AuditEventInput) -> None:
        payload = json.dumps(event.payload, separators=(",", ":"))
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO audit_events (actor, action, subject_id, payload)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                event.actor,
                event.action,
                event.subject_id,
                payload,
            )

    async def list_events(self, subject_id: str | None, limit: int) -> list[AuditEvent]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT event_id, actor, action, subject_id, payload, at
                FROM audit_events
                WHERE ($1::text IS NULL OR subject_id = $1)
                ORDER BY event_id DESC LIMIT $2
                """,
                subject_id,
                limit,
            )
        return [self._event(row) for row in rows]

    async def decision(self, subject_id: str, event_id: int | None = None) -> AuditDecision:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT event_id, actor, action, subject_id, payload, at
                FROM audit_events
                WHERE subject_id = $1 AND action = 'screen.completed'
                  AND ($2::bigint IS NULL OR event_id = $2)
                  AND payload ? 'transaction' AND payload ? 'assessment'
                ORDER BY event_id DESC LIMIT 1
                """,
                subject_id,
                event_id,
            )
        if row is None:
            raise AuditRecordNotFoundError(f"no recorded decision for {subject_id}")
        return self._decision(row)

    async def compare(
        self, subject_id: str, original_event_id: int, replay_event_id: int
    ) -> ReplayComparison:
        original = await self.decision(subject_id, original_event_id)
        replayed = await self.decision(subject_id, replay_event_id)
        differences = self._differences(original.assessment, replayed.assessment)
        return ReplayComparison(
            subject_id=subject_id,
            original_event_id=original_event_id,
            replay_event_id=replay_event_id,
            outcome="diverged" if differences else "match",
            differences=differences,
        )

    @staticmethod
    def _event(row: DatabaseRow) -> AuditEvent:
        return AuditEvent(
            event_id=cast(int, row["event_id"]),
            actor=cast(str, row["actor"]),
            action=cast(str, row["action"]),
            subject_id=cast(str, row["subject_id"]),
            payload=cast(JsonValue, row["payload"]),
            at=cast(datetime, row["at"]),
        )

    def _decision(self, row: DatabaseRow) -> AuditDecision:
        event = self._event(row)
        payload = cast(dict[str, JsonValue], event.payload)
        return AuditDecision(
            event=event,
            transaction=TransactionPayload.model_validate(payload["transaction"]),
            assessment=ComplianceAssessment.model_validate(payload["assessment"]),
        )

    @staticmethod
    def _differences(
        original: ComplianceAssessment, replayed: ComplianceAssessment
    ) -> list[ReplayDifference]:
        original_values = original.model_dump(mode="json")
        replayed_values = replayed.model_dump(mode="json")
        return [
            ReplayDifference(
                field=field,
                original=cast(JsonValue, original_values[field]),
                replayed=cast(JsonValue, replayed_values[field]),
            )
            for field in original_values
            if original_values[field] != replayed_values[field]
        ]
