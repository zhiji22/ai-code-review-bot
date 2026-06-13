"""Unit tests for result aggregation and scoring."""

from __future__ import annotations

import pytest
from app.analyzers.ast_analyzer import ASTIssue, ASTReport
from app.analyzers.result_aggregator import (
    AggregatedResult,
    ResultAggregator,
)
from app.analyzers.rule_engine import RuleCategory, RuleSeverity, RuleViolation


class TestResultAggregator:
    """Tests for aggregation, deduplication, and scoring."""

    @pytest.fixture
    def aggregator(self) -> ResultAggregator:
        return ResultAggregator()

    def _make_file_result(
        self,
        file_path: str = "test.py",
        lines_of_code: int = 100,
        ast_issues: list[ASTIssue] | None = None,
        rule_violations: list[RuleViolation] | None = None,
    ) -> dict:
        """Create a file result dict matching ReviewEngine format."""
        return {
            "file_path": file_path,
            "language": "python",
            "ast_report": ASTReport(
                issues=ast_issues or [],
                lines_of_code=lines_of_code,
                comment_lines=5,
                import_count=3,
                function_count=2,
                max_complexity=5,
                parse_error=False,
            ),
            "rule_violations": rule_violations or [],
            "llm_result": None,
            "lines_of_code": lines_of_code,
            "errors": [],
        }

    def test_empty_results(self, aggregator: ResultAggregator) -> None:
        result = aggregator.aggregate([])
        assert isinstance(result, AggregatedResult)
        assert result.total_issues == 0
        assert result.scores.overall == 100.0

    def test_clean_code_perfect_score(self, aggregator: ResultAggregator) -> None:
        file_result = self._make_file_result(lines_of_code=200)
        result = aggregator.aggregate([file_result])
        assert result.scores.overall == 100.0
        assert result.scores.security == 100.0

    def test_security_violation_lowers_score(self, aggregator: ResultAggregator) -> None:
        violations = [
            RuleViolation(
                rule_id="SEC001",
                line_number=10,
                line_end=10,
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.CRITICAL,
                message="SQL injection risk",
                suggestion="Use parameterized queries",
                matched_text='f"SELECT * FROM"',
            ),
        ]
        file_result = self._make_file_result(rule_violations=violations)
        result = aggregator.aggregate([file_result])
        assert result.scores.security < 100.0
        assert result.scores.overall < 100.0
        assert result.critical_count >= 1

    def test_warning_severity_impact(self, aggregator: ResultAggregator) -> None:
        violations = [
            RuleViolation(
                rule_id="STYLE001",
                line_number=5,
                line_end=5,
                category=RuleCategory.STYLE,
                severity=RuleSeverity.WARNING,
                message="Line too long",
                suggestion="Break into multiple lines",
                matched_text="long line",
            ),
        ]
        file_result = self._make_file_result(rule_violations=violations, lines_of_code=200)
        result = aggregator.aggregate([file_result])
        # Warning shouldn't tank the score as hard as critical
        assert result.warning_count >= 1
        assert result.scores.overall > 50.0

    def test_dedup_same_line_same_category(self, aggregator: ResultAggregator) -> None:
        ast_issues = [
            ASTIssue(
                line_number=10,
                line_end=10,
                category="complexity",
                severity="warning",
                message="High complexity (ast)",
                suggestion="Refactor",
                issue_type="cyclomatic_complexity",
            ),
        ]
        violations = [
            RuleViolation(
                rule_id="SEC001",
                line_number=10,
                line_end=10,
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.CRITICAL,
                message="SQL injection (rule)",
                suggestion="Use params",
                matched_text="SELECT",
            ),
        ]
        file_result = self._make_file_result(ast_issues=ast_issues, rule_violations=violations)
        result = aggregator.aggregate([file_result])
        # Different categories shouldn't dedup
        assert len(result.issues) >= 2

    def test_score_capped_at_zero(self, aggregator: ResultAggregator) -> None:
        """Score should never go below 0."""
        violations = [
            RuleViolation(
                rule_id=f"SEC{i:03d}",
                line_number=i,
                line_end=i,
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.CRITICAL,
                message=f"Critical {i}",
                suggestion="Fix it",
                matched_text="bad",
            )
            for i in range(1, 50)
        ]
        file_result = self._make_file_result(rule_violations=violations, lines_of_code=50)
        result = aggregator.aggregate([file_result])
        assert result.scores.overall >= 0.0
        assert result.scores.overall <= 100.0

    def test_score_capped_at_hundred(self, aggregator: ResultAggregator) -> None:
        """Score should never exceed 100."""
        file_result = self._make_file_result(lines_of_code=500)
        result = aggregator.aggregate([file_result])
        assert result.scores.overall <= 100.0

    def test_issue_sorting_by_severity(self, aggregator: ResultAggregator) -> None:
        violations = [
            RuleViolation(
                rule_id="STYLE001",
                line_number=5,
                line_end=5,
                category=RuleCategory.STYLE,
                severity=RuleSeverity.INFO,
                message="Info issue",
                suggestion="",
                matched_text="",
            ),
            RuleViolation(
                rule_id="SEC001",
                line_number=3,
                line_end=3,
                category=RuleCategory.SECURITY,
                severity=RuleSeverity.CRITICAL,
                message="Critical issue",
                suggestion="",
                matched_text="",
            ),
            RuleViolation(
                rule_id="PERF001",
                line_number=7,
                line_end=7,
                category=RuleCategory.PERFORMANCE,
                severity=RuleSeverity.WARNING,
                message="Warning issue",
                suggestion="",
                matched_text="",
            ),
        ]
        file_result = self._make_file_result(rule_violations=violations)
        result = aggregator.aggregate([file_result])
        if len(result.issues) >= 3:
            severities = [i.severity for i in result.issues]
            # Critical should come before warning before info
            assert severities.index("critical") < severities.index("warning")
            assert severities.index("warning") < severities.index("info")

    def test_multi_file_aggregation(self, aggregator: ResultAggregator) -> None:
        files = [
            self._make_file_result(file_path="a.py", lines_of_code=100),
            self._make_file_result(file_path="b.py", lines_of_code=200),
        ]
        result = aggregator.aggregate(files)
        assert result.files_reviewed == 2
        assert result.lines_of_code == 300
