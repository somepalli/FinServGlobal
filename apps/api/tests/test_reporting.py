from datetime import date
from types import TracebackType

import pytest
from compliance.reporting import LocalReportNarrator, PostureReportRepository
from compliance.schemas import (
    ActivityCounts,
    PostureReport,
    ReportPeriod,
    RiskCount,
    RiskRating,
)


class _Context:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    async def __aenter__(self) -> object:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.calls += 1
        if "payload->>'risk_rating'" in query:
            return [{"risk_rating": "high", "count": 2, "unresolved": 1}]
        if "generate_series" in query:
            return [{"day": date(2026, 8, 21), "queries": 3, "screenings": 2}]
        return [
            {"day": date(2026, 8, 14), "queries": 1, "screenings": 1},
            {"day": date(2026, 8, 21), "queries": 3, "screenings": 2},
        ]


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Context:
        return _Context(self.connection)


class _Narrator:
    def __init__(self, response: str) -> None:
        self.response = response
        self.report: PostureReport | None = None

    async def narrate(self, report: PostureReport) -> str:
        self.report = report
        return self.response


@pytest.mark.asyncio
async def test_report_figures_come_from_sql_rows() -> None:
    connection = _Connection()
    report = await PostureReportRepository(_Pool(connection)).build(
        date(2026, 8, 21), date(2026, 8, 21)
    )

    assert connection.calls == 3
    assert report.activity == ActivityCounts(regulatory_queries=3, transaction_screenings=2)
    assert report.previous_activity == ActivityCounts(
        regulatory_queries=1, transaction_screenings=1
    )
    assert report.risk_distribution == [RiskCount(risk_rating=RiskRating.HIGH, count=2)]
    assert report.unresolved_screenings == 1


@pytest.mark.asyncio
async def test_numeric_llm_commentary_is_never_published() -> None:
    narrator = _Narrator("There were 2 high-risk screenings.")
    report = await PostureReportRepository(_Pool(_Connection()), narrator).build(
        date(2026, 8, 21), date(2026, 8, 21)
    )

    assert narrator.report is not None
    assert report.commentary is None
    assert not report.commentary_generated


def test_llm_is_never_asked_for_a_count() -> None:
    report = PostureReport(
        period=ReportPeriod(start=date(2026, 8, 21), end=date(2026, 8, 21)),
        previous_period=ReportPeriod(start=date(2026, 8, 20), end=date(2026, 8, 20)),
        activity=ActivityCounts(regulatory_queries=3, transaction_screenings=2),
        previous_activity=ActivityCounts(regulatory_queries=1, transaction_screenings=1),
        risk_distribution=[RiskCount(risk_rating=RiskRating.HIGH, count=2)],
        unresolved_screenings=1,
        daily_activity=[],
    )

    narrator = LocalReportNarrator.__new__(LocalReportNarrator)
    prompt = narrator._qualitative_facts(report)

    assert not any(character.isdigit() for character in prompt)
    assert "count" not in prompt.lower()
