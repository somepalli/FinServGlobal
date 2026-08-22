"""Build compliance posture reports from persisted audit facts."""

import re
from datetime import date, timedelta
from json import JSONDecodeError
from typing import Literal, Protocol, cast

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from compliance.config.settings import Settings
from compliance.db import DatabasePool, DatabaseRow
from compliance.retrieval.answer import is_internal_endpoint
from compliance.schemas import (
    ActivityCounts,
    DailyActivity,
    PostureReport,
    ReportPeriod,
    RiskCount,
    RiskRating,
)

_NUMBER = re.compile(r"\d")
_LOGGER = structlog.get_logger(__name__)


class ReportNarrator(Protocol):
    async def narrate(self, report: PostureReport) -> str: ...


class _Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class _ChatResponse(BaseModel):
    choices: list[dict[str, _Message]]


class LocalReportNarrator:
    def __init__(self, settings: Settings) -> None:
        if not is_internal_endpoint(settings.llm_base_url):
            raise ValueError("report facts may only be sent to an internal LLM")
        self._settings = settings

    async def narrate(self, report: PostureReport) -> str:
        request = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._qualitative_facts(report)},
            ],
            "temperature": self._settings.llm_temperature,
            "max_tokens": self._settings.llm_max_tokens,
        }
        endpoint = f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                response = await client.post(endpoint, json=request)
                response.raise_for_status()
            completion = _ChatResponse.model_validate(response.json())
        except (httpx.HTTPError, JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"local report commentary failed: {exc}") from exc
        if not completion.choices:
            raise RuntimeError("local report commentary returned no choices")
        return completion.choices[0]["message"].content

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Write brief audit-committee commentary from the supplied qualitative facts. "
            "Do not calculate or include digits, quantities, percentages, or dates. "
            "The surrounding report displays all figures separately."
        )

    def _qualitative_facts(self, report: PostureReport) -> str:
        risks = sorted(report.risk_distribution, key=lambda item: item.count, reverse=True)
        dominant = risks[0].risk_rating.value if risks else "no recorded"
        unresolved = "present" if report.unresolved_screenings else "absent"
        query_movement = self._movement(
            report.activity.regulatory_queries,
            report.previous_activity.regulatory_queries,
        )
        screening_movement = self._movement(
            report.activity.transaction_screenings,
            report.previous_activity.transaction_screenings,
        )
        return "\n".join(
            [
                f"Regulatory query movement: {query_movement}.",
                f"Transaction screening movement: {screening_movement}.",
                f"Dominant recorded risk category: {dominant}.",
                f"Screenings with unresolved questions: {unresolved}.",
            ]
        )

    @staticmethod
    def _movement(current: int, previous: int) -> str:
        if current > previous:
            return "increased"
        if current < previous:
            return "decreased"
        return "unchanged"


class PostureReportRepository:
    def __init__(self, pool: DatabasePool, narrator: ReportNarrator | None = None) -> None:
        self._pool = pool
        self._narrator = narrator

    async def build(self, start: date, end: date) -> PostureReport:
        if end < start:
            raise ValueError("report end must not precede start")
        previous = self._previous_period(start, end)
        async with self._pool.acquire() as connection:
            totals = await connection.fetch(self._totals_sql(), previous.start, end)
            risks = await connection.fetch(self._risks_sql(), start, end)
            daily = await connection.fetch(self._daily_sql(), start, end)
        report = self._report(start, end, previous, totals, risks, daily)
        return await self._with_commentary(report)

    async def _with_commentary(self, report: PostureReport) -> PostureReport:
        if self._narrator is None:
            return report
        try:
            commentary = (await self._narrator.narrate(report)).strip()
        except RuntimeError as exc:
            _LOGGER.warning("report_commentary_failed", error=str(exc))
            return report
        if not commentary or _NUMBER.search(commentary):
            return report
        return report.model_copy(
            update={"commentary": commentary, "commentary_generated": True}
        )

    @staticmethod
    def _previous_period(start: date, end: date) -> ReportPeriod:
        width = (end - start).days + 1
        return ReportPeriod(start=start - timedelta(days=width), end=start - timedelta(days=1))

    @staticmethod
    def _totals_sql() -> str:
        return """
            SELECT (at AT TIME ZONE 'UTC')::date AS day,
                   count(*) FILTER (WHERE action = 'query.completed') AS queries,
                   count(*) FILTER (WHERE action = 'screen.completed') AS screenings
            FROM audit_events
            WHERE at >= $1::date AND at < ($2::date + 1)
              AND action IN ('query.completed', 'screen.completed')
            GROUP BY day ORDER BY day
        """

    @staticmethod
    def _risks_sql() -> str:
        return """
            SELECT payload->>'risk_rating' AS risk_rating, count(*) AS count,
                   count(*) FILTER (
                       WHERE (payload->>'unresolved_questions')::int > 0
                   ) AS unresolved
            FROM audit_events
            WHERE action = 'screen.completed'
              AND at >= $1::date AND at < ($2::date + 1)
              AND payload ? 'risk_rating'
            GROUP BY payload->>'risk_rating'
        """

    @staticmethod
    def _daily_sql() -> str:
        return """
            SELECT days.day,
                   count(e.*) FILTER (WHERE e.action = 'query.completed') AS queries,
                   count(e.*) FILTER (WHERE e.action = 'screen.completed') AS screenings
            FROM generate_series($1::date, $2::date, interval '1 day') AS days(day)
            LEFT JOIN audit_events e ON (e.at AT TIME ZONE 'UTC')::date = days.day
              AND e.action IN ('query.completed', 'screen.completed')
            GROUP BY days.day ORDER BY days.day
        """

    def _report(
        self,
        start: date,
        end: date,
        previous: ReportPeriod,
        totals: list[DatabaseRow],
        risks: list[DatabaseRow],
        daily: list[DatabaseRow],
    ) -> PostureReport:
        current_rows = [row for row in totals if cast(date, row["day"]) >= start]
        previous_rows = [row for row in totals if cast(date, row["day"]) < start]
        return PostureReport(
            period=ReportPeriod(start=start, end=end),
            previous_period=previous,
            activity=self._activity(current_rows),
            previous_activity=self._activity(previous_rows),
            risk_distribution=[self._risk(row) for row in risks],
            unresolved_screenings=sum(cast(int, row["unresolved"]) for row in risks),
            daily_activity=[self._daily(row) for row in daily],
        )

    @staticmethod
    def _activity(rows: list[DatabaseRow]) -> ActivityCounts:
        return ActivityCounts(
            regulatory_queries=sum(cast(int, row["queries"]) for row in rows),
            transaction_screenings=sum(cast(int, row["screenings"]) for row in rows),
        )

    @staticmethod
    def _risk(row: DatabaseRow) -> RiskCount:
        return RiskCount(
            risk_rating=RiskRating(cast(str, row["risk_rating"])),
            count=cast(int, row["count"]),
        )

    @staticmethod
    def _daily(row: DatabaseRow) -> DailyActivity:
        return DailyActivity(
            day=cast(date, row["day"]),
            regulatory_queries=cast(int, row["queries"]),
            transaction_screenings=cast(int, row["screenings"]),
        )
