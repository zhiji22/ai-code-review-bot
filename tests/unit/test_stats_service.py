"""Unit tests for StatsService — dashboard statistics aggregation."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.stats_service import StatsService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_score_row(
    *,
    avg_overall: float | None = 85.0,
    avg_security: float | None = 90.0,
    avg_performance: float | None = 80.0,
    avg_maintainability: float | None = 75.0,
) -> MagicMock:
    """Mock a Row with average score attributes (one_or_none result)."""
    row = MagicMock()
    row.avg_overall = avg_overall
    row.avg_security = avg_security
    row.avg_performance = avg_performance
    row.avg_maintainability = avg_maintainability
    return row


def _make_issue_row(
    *,
    critical: int | None = 3,
    warning: int | None = 10,
    info: int | None = 5,
) -> MagicMock:
    """Mock a Row with issue count attributes."""
    row = MagicMock()
    row.critical = critical
    row.warning = warning
    row.info = info
    return row


def _make_llm_row(
    *,
    requests: int | None = 20,
    tokens: int | None = 50000,
    cost: float | None = 1.5,
    cached: int | None = 5,
) -> MagicMock:
    """Mock a Row with LLM usage attributes."""
    row = MagicMock()
    row.requests = requests
    row.tokens = tokens
    row.cost = cost
    row.cached = cached
    return row


def _make_execute_result_for_row(row: MagicMock | None) -> MagicMock:
    """Wrap a mock Row so execute().one_or_none() returns it."""
    result = MagicMock()
    result.one_or_none.return_value = row
    return result


def _make_trend_row(
    *,
    d: date,
    reviews: int = 5,
    issues: int = 12,
    critical: int = 2,
    avg_score: float = 78.5,
) -> MagicMock:
    """Mock a trend data-point Row."""
    row = MagicMock()
    row.date = datetime(d.year, d.month, d.day, tzinfo=UTC)
    row.reviews = reviews
    row.issues = issues
    row.critical = critical
    row.avg_score = avg_score
    return row


def _make_breakdown_row(
    *,
    category: str = "security",
    severity: str = "critical",
    count: int = 3,
) -> MagicMock:
    """Mock a category breakdown Row."""
    row = MagicMock()
    row.category = category
    row.severity = severity
    row.count = count
    return row


# ---------------------------------------------------------------------------
# Tests — overview
# ---------------------------------------------------------------------------


class TestStatsServiceOverview:
    """Tests for StatsService.overview."""

    @pytest.mark.asyncio
    async def test_overview_basic(self) -> None:
        """Returns OverviewStatsSchema with all expected fields populated."""
        session = AsyncMock()
        service = StatsService(session)

        # overview calls in order:
        #   1) session.scalar(select count)       -> total_reviews
        #   2) session.execute(score query)        -> score_row
        #   3) session.execute(issue query)        -> issue_row
        #   4) session.execute(llm query)          -> llm_row
        #   5) session.scalar(count repos)         -> total_repos
        session.scalar.side_effect = [5, 2]

        score_result = _make_execute_result_for_row(
            _make_score_row(
                avg_overall=85.0, avg_security=90.0, avg_performance=80.0, avg_maintainability=75.0
            )
        )
        issue_result = _make_execute_result_for_row(_make_issue_row(critical=3, warning=10, info=5))
        llm_result = _make_execute_result_for_row(
            _make_llm_row(requests=20, tokens=50000, cost=1.5, cached=5)
        )
        session.execute.side_effect = [score_result, issue_result, llm_result]

        result = await service.overview()

        assert result.total_reviews == 5
        assert result.total_repositories == 2
        assert result.total_issues == 18  # 3 + 10 + 5
        assert result.critical_issues == 3
        assert result.warning_issues == 10
        assert result.info_issues == 5
        assert result.avg_overall_score == 85.0
        assert result.avg_security_score == 90.0
        assert result.avg_performance_score == 80.0
        assert result.avg_maintainability_score == 75.0
        assert result.total_llm_cost_usd == 1.5
        assert result.total_llm_tokens == 50000
        # cache_hit_rate = cached / requests = 5 / 20 = 0.25
        assert result.cache_hit_rate == 0.25

    @pytest.mark.asyncio
    async def test_overview_with_repository_filter(self) -> None:
        """When repository_id is provided, queries are filtered accordingly."""
        session = AsyncMock()
        service = StatsService(session)

        session.scalar.side_effect = [3, 1]

        score_result = _make_execute_result_for_row(_make_score_row(avg_overall=70.0))
        issue_result = _make_execute_result_for_row(_make_issue_row(critical=1, warning=4, info=2))
        llm_result = _make_execute_result_for_row(
            _make_llm_row(requests=10, tokens=20000, cost=0.8, cached=2)
        )
        session.execute.side_effect = [score_result, issue_result, llm_result]

        result = await service.overview(repository_id=42)

        assert result.total_reviews == 3
        assert result.total_repositories == 1
        assert result.total_issues == 7

        # Verify scalar was called twice (total_reviews, total_repos)
        scalar_calls = session.scalar.call_args_list
        assert len(scalar_calls) == 2

        # The first scalar call should include a repository_id filter
        # Compiled SQL uses bound parameters, so check for the parameter name
        first_query_str = str(scalar_calls[0].args[0])
        assert "repository_id" in first_query_str

    @pytest.mark.asyncio
    async def test_overview_empty_data(self) -> None:
        """Returns all zeros when no reviews exist."""
        session = AsyncMock()
        service = StatsService(session)

        # scalar returns None (no reviews / no repos) — service does `or 0`
        session.scalar.side_effect = [None, None]

        # one_or_none returns None for all execute results
        score_result = _make_execute_result_for_row(
            _make_score_row(
                avg_overall=None,
                avg_security=None,
                avg_performance=None,
                avg_maintainability=None,
            )
        )
        issue_result = _make_execute_result_for_row(
            _make_issue_row(critical=None, warning=None, info=None)
        )
        llm_result = _make_execute_result_for_row(
            _make_llm_row(requests=None, tokens=None, cost=None, cached=None)
        )
        session.execute.side_effect = [score_result, issue_result, llm_result]

        result = await service.overview()

        assert result.total_reviews == 0
        assert result.total_repositories == 0
        assert result.total_issues == 0
        assert result.critical_issues == 0
        assert result.warning_issues == 0
        assert result.info_issues == 0
        assert result.avg_overall_score == 0.0
        assert result.avg_security_score == 0.0
        assert result.avg_performance_score == 0.0
        assert result.avg_maintainability_score == 0.0
        assert result.total_llm_cost_usd == 0.0
        assert result.total_llm_tokens == 0
        assert result.cache_hit_rate == 0.0


# ---------------------------------------------------------------------------
# Tests — trends
# ---------------------------------------------------------------------------


class TestStatsServiceTrends:
    """Tests for StatsService.trends."""

    @pytest.mark.asyncio
    async def test_trends_basic(self) -> None:
        """Returns TrendStatsSchema with expected data points."""
        session = AsyncMock()
        service = StatsService(session)

        day1 = date(2025, 6, 1)
        day2 = date(2025, 6, 2)

        trend_rows = [
            _make_trend_row(d=day1, reviews=3, issues=8, critical=1, avg_score=82.0),
            _make_trend_row(d=day2, reviews=5, issues=12, critical=2, avg_score=78.5),
        ]

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter(trend_rows))
        session.execute.return_value = mock_result

        result = await service.trends()

        assert result.period == "30d"
        assert result.start_date is not None
        assert result.end_date is not None
        assert len(result.points) == 2

        p0 = result.points[0]
        assert p0.date == day1
        assert p0.reviews == 3
        assert p0.issues == 8
        assert p0.critical == 1
        assert p0.avg_score == 82.0

        p1 = result.points[1]
        assert p1.date == day2
        assert p1.reviews == 5

    @pytest.mark.asyncio
    async def test_trends_with_repository_filter(self) -> None:
        """When repository_id is provided, trend query includes filter."""
        session = AsyncMock()
        service = StatsService(session)

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        session.execute.return_value = mock_result

        result = await service.trends(repository_id=42, days=7)

        assert result.period == "7d"
        assert len(result.points) == 0

        # Verify the executed statement includes the repo filter parameter
        execute_call = session.execute.call_args
        stmt = execute_call.args[0]
        compiled_str = str(stmt)
        assert "repository_id" in compiled_str

    @pytest.mark.asyncio
    async def test_trends_empty(self) -> None:
        """Returns empty points list when no reviews exist."""
        session = AsyncMock()
        service = StatsService(session)

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        session.execute.return_value = mock_result

        result = await service.trends(days=14)

        assert result.period == "14d"
        assert len(result.points) == 0


# ---------------------------------------------------------------------------
# Tests — category_breakdown
# ---------------------------------------------------------------------------


class TestStatsServiceCategoryBreakdown:
    """Tests for StatsService.category_breakdown."""

    @pytest.mark.asyncio
    async def test_category_breakdown_basic(self) -> None:
        """Returns list of CategoryBreakdownSchema sorted by total desc."""
        session = AsyncMock()
        service = StatsService(session)

        breakdown_rows = [
            _make_breakdown_row(category="security", severity="critical", count=5),
            _make_breakdown_row(category="security", severity="warning", count=8),
            _make_breakdown_row(category="style", severity="info", count=3),
        ]

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter(breakdown_rows))
        session.execute.return_value = mock_result

        result = await service.category_breakdown()

        assert len(result) == 2  # two distinct categories

        # security should be first (total=13 > style total=3)
        assert result[0].category == "security"
        assert result[0].critical == 5
        assert result[0].warning == 8
        assert result[0].info == 0
        assert result[0].total == 13

        assert result[1].category == "style"
        assert result[1].info == 3
        assert result[1].total == 3

    @pytest.mark.asyncio
    async def test_category_breakdown_with_filter(self) -> None:
        """Filters by repository_id when provided."""
        session = AsyncMock()
        service = StatsService(session)

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        session.execute.return_value = mock_result

        result = await service.category_breakdown(repository_id=42)

        assert result == []
        # Verify the statement includes the repo filter parameter
        execute_call = session.execute.call_args
        stmt = execute_call.args[0]
        compiled_str = str(stmt)
        assert "repository_id" in compiled_str

    @pytest.mark.asyncio
    async def test_category_breakdown_severity_mapping(self) -> None:
        """Correctly maps critical/warning/info severities into their buckets."""
        session = AsyncMock()
        service = StatsService(session)

        breakdown_rows = [
            _make_breakdown_row(category="performance", severity="critical", count=2),
            _make_breakdown_row(category="performance", severity="warning", count=6),
            _make_breakdown_row(category="performance", severity="info", count=4),
        ]

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter(breakdown_rows))
        session.execute.return_value = mock_result

        result = await service.category_breakdown()

        assert len(result) == 1
        entry = result[0]
        assert entry.category == "performance"
        assert entry.critical == 2
        assert entry.warning == 6
        assert entry.info == 4
        assert entry.total == 12

    @pytest.mark.asyncio
    async def test_category_breakdown_empty(self) -> None:
        """Returns empty list when no review comments exist."""
        session = AsyncMock()
        service = StatsService(session)

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        session.execute.return_value = mock_result

        result = await service.category_breakdown()

        assert result == []
