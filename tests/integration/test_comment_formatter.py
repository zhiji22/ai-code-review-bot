"""Integration tests for comment formatting."""

from __future__ import annotations

import pytest

from app.analyzers.result_aggregator import (
    AggregatedResult,
    ReviewScores,
    UnifiedIssue,
)
from app.services.comment_formatter import CommentFormatter


class TestCommentFormatter:
    """Tests for PR comment generation."""

    @pytest.fixture
    def formatter(self) -> CommentFormatter:
        return CommentFormatter()

    @pytest.fixture
    def sample_result(self) -> AggregatedResult:
        return AggregatedResult(
            issues=[
                UnifiedIssue(
                    file_path="src/api.py",
                    line_number=42,
                    line_end=42,
                    source="rule",
                    category="security",
                    severity="critical",
                    message="SQL injection vulnerability",
                    suggestion="Use parameterized queries: cursor.execute(sql, params)",
                    rule_id="SEC001",
                    confidence=1.0,
                ),
                UnifiedIssue(
                    file_path="src/utils.py",
                    line_number=10,
                    line_end=10,
                    source="rule",
                    category="style",
                    severity="warning",
                    message="Line too long (150 chars)",
                    suggestion="Break into multiple lines",
                    rule_id="STYLE001",
                    confidence=1.0,
                ),
            ],
            scores=ReviewScores(
                overall=72.5,
                security=55.0,
                performance=90.0,
                maintainability=72.5,
            ),
            summary="Found 2 issues including 1 critical security vulnerability.",
            files_reviewed=2,
            lines_of_code=250,
            llm_summary=None,
            llm_tokens=0,
        )

    def test_format_pr_comment_contains_score(self, formatter: CommentFormatter, sample_result: AggregatedResult) -> None:
        comment = formatter.format_pr_comment(sample_result, "owner/repo", 42)
        assert "72.5" in comment or "72" in comment
        assert "score" in comment.lower()

    def test_format_pr_comment_contains_issues(self, formatter: CommentFormatter, sample_result: AggregatedResult) -> None:
        comment = formatter.format_pr_comment(sample_result, "owner/repo", 42)
        assert "SQL injection" in comment
        assert "SEC001" in comment or "SEC" in comment
        assert "src/api.py" in comment

    def test_format_pr_comment_contains_repo_and_pr(
        self, formatter: CommentFormatter, sample_result: AggregatedResult
    ) -> None:
        comment = formatter.format_pr_comment(sample_result, "myorg/myrepo", 99)
        assert "myorg/myrepo" in comment or "myrepo" in comment
        assert "99" in comment

    def test_format_pr_comment_has_recommendation(self, formatter: CommentFormatter, sample_result: AggregatedResult) -> None:
        comment = formatter.format_pr_comment(sample_result, "owner/repo", 1)
        assert "request changes" in comment.lower() or "recommend" in comment.lower()

    def test_format_pr_comment_empty_issues(self, formatter: CommentFormatter) -> None:
        result = AggregatedResult(
            issues=[],
            scores=ReviewScores(overall=100.0, security=100.0, performance=100.0, maintainability=100.0),
            summary="No issues found. Clean code!",
            files_reviewed=1,
            lines_of_code=100,
            llm_summary=None,
            llm_tokens=0,
        )
        comment = formatter.format_pr_comment(result, "owner/repo", 1)
        assert "100" in comment
        assert "clean" in comment.lower() or "no issues" in comment.lower()

    def test_format_inline_comments_payload(self, formatter: CommentFormatter, sample_result: AggregatedResult) -> None:
        payload = formatter.format_inline_comments_payload(sample_result, max_comments=50)
        assert isinstance(payload, list)
        assert len(payload) >= 1

        first = payload[0]
        assert "path" in first
        assert "line" in first
        assert "side" in first
        assert first["side"] == "RIGHT"
        assert first["path"] == "src/api.py"
        assert "SQL injection" in first["body"]

    def test_inline_comments_critical_first(self, formatter: CommentFormatter, sample_result: AggregatedResult) -> None:
        payload = formatter.format_inline_comments_payload(sample_result, max_comments=50)
        if len(payload) >= 2:
            first_body = payload[0]["body"].lower()
            assert "critical" in first_body or "security" in first_body

    def test_inline_comment_max_limit(self, formatter: CommentFormatter) -> None:
        issues = [
            UnifiedIssue(
                file_path=f"file_{i}.py",
                line_number=i,
                line_end=i,
                source="rule",
                category="style",
                severity="info",
                message=f"Issue {i}",
                suggestion="Fix it",
                rule_id=f"STYLE{i:03d}",
                confidence=1.0,
            )
            for i in range(100)
        ]
        result = AggregatedResult(
            issues=issues,
            scores=ReviewScores(overall=50, security=50, performance=50, maintainability=50),
            summary="",
            files_reviewed=100,
            lines_of_code=1000,
            llm_summary=None,
            llm_tokens=0,
        )
        payload = formatter.format_inline_comments_payload(result, max_comments=20)
        assert len(payload) <= 20
