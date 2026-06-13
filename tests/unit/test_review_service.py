"""Unit tests for ReviewService — CRUD + business logic for reviews."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.schemas.reviews import ReviewFiltersSchema
from app.services.review_service import ReviewService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    """Mock AsyncSession."""
    return AsyncMock()


@pytest.fixture
def review_service(mock_session: AsyncMock) -> ReviewService:
    """ReviewService with mocked session."""
    return ReviewService(mock_session)


# ---------------------------------------------------------------------------
# 1. create_from_pipeline
# ---------------------------------------------------------------------------


class TestCreateFromPipeline:
    """Tests for ReviewService.create_from_pipeline."""

    @pytest.mark.asyncio
    async def test_creates_review_with_all_fields(self, review_service: ReviewService) -> None:
        """All keyword arguments are stored on the Review object."""
        review_service.session.commit = AsyncMock()
        review_service.session.refresh = AsyncMock()
        # session.add is synchronous in SQLAlchemy
        review_service.session.add = MagicMock()

        await review_service.create_from_pipeline(
            repository_id=1,
            pr_number=42,
            commit_sha="abc123def456abc123def456abc123def456abcd",
            pr_title="Add feature",
            pr_author="dev",
            trigger="manual",
            files_reviewed=5,
            files_total=10,
            lines_of_code=200,
            additions=150,
            deletions=50,
            overall_score=85,
            security_score=90,
            performance_score=80,
            maintainability_score=75,
            critical_count=1,
            warning_count=3,
            info_count=5,
            llm_model="qwen-plus",
            llm_tokens_prompt=100,
            llm_tokens_completion=200,
            llm_tokens_total=300,
            llm_cost_usd=0.05,
            duration_ms=5000,
            summary="Looks good overall",
            raw_result={"key": "value"},
            pr_comment_posted=True,
            inline_comments_posted=3,
        )

        # Verify session.add was called with a Review
        review_service.session.add.assert_called_once()
        added = review_service.session.add.call_args[0][0]
        assert added.repository_id == 1
        assert added.pr_number == 42
        assert added.commit_sha == "abc123def456abc123def456abc123def456abcd"
        assert added.pr_title == "Add feature"
        assert added.pr_author == "dev"
        assert added.status == "completed"
        assert added.trigger == "manual"
        assert added.files_reviewed == 5
        assert added.files_total == 10
        assert added.lines_of_code == 200
        assert added.additions == 150
        assert added.deletions == 50
        assert added.overall_score == 85
        assert added.security_score == 90
        assert added.performance_score == 80
        assert added.maintainability_score == 75
        assert added.critical_count == 1
        assert added.warning_count == 3
        assert added.info_count == 5
        assert added.llm_model == "qwen-plus"
        assert added.llm_tokens_total == 300
        assert added.llm_cost_usd == 0.05
        assert added.duration_ms == 5000
        assert added.summary == "Looks good overall"
        assert added.raw_result == {"key": "value"}
        assert added.pr_comment_posted is True
        assert added.inline_comments_posted == 3
        assert added.reviewed_at is not None

        review_service.session.commit.assert_awaited_once()
        review_service.session.refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. create_pending
# ---------------------------------------------------------------------------


class TestCreatePending:
    """Tests for ReviewService.create_pending."""

    @pytest.mark.asyncio
    async def test_creates_pending_review(self, review_service: ReviewService) -> None:
        """Pending review has status='pending' and required fields only."""
        review_service.session.commit = AsyncMock()
        review_service.session.refresh = AsyncMock()
        # session.add is synchronous in SQLAlchemy
        review_service.session.add = MagicMock()

        await review_service.create_pending(
            repository_id=2,
            pr_number=7,
            commit_sha="deadbeef" + "0" * 32,
            pr_title="Fix bug",
            pr_author="fixer",
            trigger="webhook",
        )

        review_service.session.add.assert_called_once()
        added = review_service.session.add.call_args[0][0]
        assert added.repository_id == 2
        assert added.pr_number == 7
        assert added.status == "pending"
        assert added.trigger == "webhook"
        assert added.pr_title == "Fix bug"
        assert added.pr_author == "fixer"

        review_service.session.commit.assert_awaited_once()
        review_service.session.refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. mark_failed
# ---------------------------------------------------------------------------


class TestMarkFailed:
    """Tests for ReviewService.mark_failed."""

    @pytest.mark.asyncio
    async def test_updates_status_and_error(self, review_service: ReviewService) -> None:
        """mark_failed executes an UPDATE with status='failed' and error_message."""
        review_service.session.execute = AsyncMock()
        review_service.session.commit = AsyncMock()

        await review_service.mark_failed(99, "Something went wrong")

        review_service.session.execute.assert_awaited_once()
        review_service.session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. save_comments
# ---------------------------------------------------------------------------


class TestSaveComments:
    """Tests for ReviewService.save_comments."""

    @pytest.mark.asyncio
    async def test_bulk_inserts_comments(self, review_service: ReviewService) -> None:
        """Multiple comments are bulk-inserted as ReviewComment objects."""
        review_service.session.commit = AsyncMock()
        # session.add_all is synchronous in SQLAlchemy
        review_service.session.add_all = MagicMock()

        comments = [
            {
                "file_path": "src/main.py",
                "line_number": 10,
                "source": "rule",
                "category": "security",
                "severity": "critical",
                "message": "SQL injection risk",
                "suggestion": "Use parameterized queries",
                "rule_id": "SQL001",
                "confidence": 0.95,
            },
            {
                "file_path": "src/utils.py",
                "message": "Unused import",
                "severity": "info",
            },
        ]

        result = await review_service.save_comments(review_id=1, comments=comments)

        assert len(result) == 2
        review_service.session.add_all.assert_called_once()
        inserted = review_service.session.add_all.call_args[0][0]
        assert len(inserted) == 2

        # First comment — all fields
        c0 = inserted[0]
        assert c0.review_id == 1
        assert c0.file_path == "src/main.py"
        assert c0.line_number == 10
        assert c0.severity == "critical"
        assert c0.message == "SQL injection risk"
        assert c0.suggestion == "Use parameterized queries"
        assert c0.rule_id == "SQL001"
        assert c0.confidence == 0.95

        # Second comment — defaults applied
        c1 = inserted[1]
        assert c1.file_path == "src/utils.py"
        assert c1.line_number == 1  # default
        assert c1.severity == "info"
        assert c1.source == "rule"  # default
        assert c1.category == "general"  # default
        assert c1.confidence == 1.0  # default

        review_service.session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_comments_list(self, review_service: ReviewService) -> None:
        """Empty comments list results in no inserts and empty return."""
        review_service.session.commit = AsyncMock()
        # session.add_all is synchronous in SQLAlchemy
        review_service.session.add_all = MagicMock()

        result = await review_service.save_comments(review_id=1, comments=[])

        assert result == []
        review_service.session.add_all.assert_called_once_with([])
        review_service.session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5. get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    """Tests for ReviewService.get_by_id."""

    @pytest.mark.asyncio
    async def test_returns_review_with_comments(self, review_service: ReviewService) -> None:
        """Returns the review when found."""
        mock_review = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_review
        review_service.session.execute.return_value = mock_result

        result = await review_service.get_by_id(42)

        assert result is mock_review
        review_service.session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, review_service: ReviewService) -> None:
        """Returns None when review id does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        review_service.session.execute.return_value = mock_result

        result = await review_service.get_by_id(9999)

        assert result is None


# ---------------------------------------------------------------------------
# 6. list_reviews with filters
# ---------------------------------------------------------------------------


class TestListReviews:
    """Tests for ReviewService.list_reviews."""

    @pytest.mark.asyncio
    async def test_with_filters(self, review_service: ReviewService) -> None:
        """Filters are applied and results + count returned."""
        mock_review = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_review]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        review_service.session.execute.return_value = mock_result

        # Mock scalar for count
        review_service.session.scalar = AsyncMock(return_value=1)

        filters = ReviewFiltersSchema(
            repository_id=1,
            status="completed",
            pr_number=42,
            min_score=50.0,
            max_score=100.0,
            sort_by="created_at",
            sort_order="desc",
            offset=0,
            limit=20,
        )

        reviews, total = await review_service.list_reviews(filters)

        assert len(reviews) == 1
        assert reviews[0] is mock_review
        assert total == 1
        review_service.session.scalar.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_no_filters(self, review_service: ReviewService) -> None:
        """No filters — returns all reviews."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        review_service.session.execute.return_value = mock_result
        review_service.session.scalar = AsyncMock(return_value=0)

        filters = ReviewFiltersSchema()
        reviews, total = await review_service.list_reviews(filters)

        assert reviews == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_with_cursor_pagination(self, review_service: ReviewService) -> None:
        """Cursor filter applies `Review.id < cursor` condition."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        review_service.session.execute.return_value = mock_result
        review_service.session.scalar = AsyncMock(return_value=0)

        filters = ReviewFiltersSchema(cursor="100")
        _reviews, total = await review_service.list_reviews(filters)

        assert total == 0


# ---------------------------------------------------------------------------
# 7. count_by_repo
# ---------------------------------------------------------------------------


class TestCountByRepo:
    """Tests for ReviewService.count_by_repo."""

    @pytest.mark.asyncio
    async def test_returns_count(self, review_service: ReviewService) -> None:
        """Returns the review count for a repository."""
        review_service.session.scalar = AsyncMock(return_value=7)

        count = await review_service.count_by_repo(repository_id=1)

        assert count == 7

    @pytest.mark.asyncio
    async def test_returns_zero_when_none(self, review_service: ReviewService) -> None:
        """Returns 0 when scalar returns None."""
        review_service.session.scalar = AsyncMock(return_value=None)

        count = await review_service.count_by_repo(repository_id=1)

        assert count == 0

    @pytest.mark.asyncio
    async def test_with_since_filter(self, review_service: ReviewService) -> None:
        """Passing since= applies a date filter."""
        review_service.session.scalar = AsyncMock(return_value=3)

        since = datetime(2025, 1, 1, tzinfo=UTC)
        count = await review_service.count_by_repo(repository_id=1, since=since)

        assert count == 3
        review_service.session.scalar.assert_awaited_once()


# ---------------------------------------------------------------------------
# Additional: get_latest_for_pr, get_comments
# ---------------------------------------------------------------------------


class TestGetLatestForPR:
    """Tests for ReviewService.get_latest_for_pr."""

    @pytest.mark.asyncio
    async def test_found(self, review_service: ReviewService) -> None:
        """Returns most recent review for a repo+PR combination."""
        mock_review = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_review
        review_service.session.execute.return_value = mock_result

        result = await review_service.get_latest_for_pr(repository_id=1, pr_number=42)
        assert result is mock_review

    @pytest.mark.asyncio
    async def test_not_found(self, review_service: ReviewService) -> None:
        """Returns None when no review exists for the repo+PR."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        review_service.session.execute.return_value = mock_result

        result = await review_service.get_latest_for_pr(repository_id=1, pr_number=999)
        assert result is None


class TestGetComments:
    """Tests for ReviewService.get_comments."""

    @pytest.mark.asyncio
    async def test_returns_comments(self, review_service: ReviewService) -> None:
        """Returns ordered list of comments for a review."""
        mock_comment = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_comment]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        review_service.session.execute.return_value = mock_result

        comments = await review_service.get_comments(review_id=42)

        assert len(comments) == 1
        assert comments[0] is mock_comment
