"""Unit tests for the review engine.

Tests the ReviewEngine orchestration pipeline including:
- Tiered strategy for large PRs
- Parallel file analysis with graceful degradation
- GitHub posting with partial failure handling
- ReviewResult and FileReport dataclass defaults
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.analyzers.ast_analyzer import ASTIssue, ASTReport
from app.analyzers.llm_analyzer import LLMIssue, LLMReviewResult
from app.analyzers.result_aggregator import AggregatedResult, ReviewScores, UnifiedIssue
from app.analyzers.rule_engine import RuleViolation
from app.core.review_engine import FileReport, ReviewEngine, ReviewResult
from app.services.github_client import FileDiff, PRInfo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_diff(
    file_path: str = "src/main.py",
    language: str = "python",
    is_code_file: bool = True,
    status: str = "modified",
    additions: int = 10,
    deletions: int = 2,
    raw_patch: str = "diff --git a/src/main.py",
    content: str = "print('hello')",
) -> FileDiff:
    """Create a FileDiff instance with sensible defaults."""
    fd = FileDiff(
        file_path=file_path,
        status=status,
        additions=additions,
        deletions=deletions,
        raw_patch=raw_patch,
        content=content,
        language=language,
    )
    # Override is_code_file property if needed via a subclass trick.
    # Since is_code_file is a @property based on extension, we only
    # need to set file_path correctly for it to return True.
    return fd


def _make_pr_info(
    title: str = "Test PR",
    changed_files: int = 5,
) -> PRInfo:
    """Create a PRInfo instance with sensible defaults."""
    return PRInfo(
        number=42,
        title=title,
        body="test body",
        head_sha="abc123",
        base_sha="def456",
        author="testuser",
        additions=100,
        deletions=20,
        changed_files=changed_files,
    )


def _make_engine(**overrides) -> ReviewEngine:
    """Create a ReviewEngine with all sub-analyzers mocked out."""
    engine = ReviewEngine(**overrides)
    engine.ast_analyzer = MagicMock()
    engine.rule_engine = MagicMock()
    engine.llm_analyzer = AsyncMock()
    engine.aggregator = MagicMock()
    engine.formatter = MagicMock()
    return engine


def _make_github_client() -> AsyncMock:
    """Create a mocked GitHubClient with all async methods."""
    client = AsyncMock()
    client.get_pr_info = AsyncMock()
    client.get_pr_files = AsyncMock()
    client.get_file_content = AsyncMock(return_value="file content")
    client.post_review_comment = AsyncMock(return_value={"id": 1})
    client.post_inline_comments = AsyncMock(return_value={"id": 2})
    client.update_review_status = AsyncMock(return_value={"id": 3})
    client.close = AsyncMock()
    return client


def _stub_aggregate_ok(aggregator: MagicMock) -> None:
    """Configure the aggregator mock to return a valid AggregatedResult."""
    aggregator.aggregate.return_value = AggregatedResult(
        issues=[],
        scores=ReviewScores(overall=90, security=95, performance=88, maintainability=92),
        summary="Review completed",
        files_reviewed=1,
        lines_of_code=10,
    )


def _stub_formatter_ok(formatter: MagicMock) -> None:
    """Configure the formatter mock with valid return values."""
    formatter.format_pr_comment.return_value = "## Review Summary\nScore: 90/100"
    formatter.format_inline_comments_payload.return_value = []


# ---------------------------------------------------------------------------
# Test: Dataclass defaults
# ---------------------------------------------------------------------------


class TestDataclassDefaults:
    """Verify default values for ReviewResult and FileReport dataclasses."""

    def test_review_result_defaults(self) -> None:
        result = ReviewResult(
            repo_full_name="owner/repo",
            pr_number=1,
            commit_sha="abc",
        )
        assert result.repo_full_name == "owner/repo"
        assert result.pr_number == 1
        assert result.commit_sha == "abc"
        assert isinstance(result.aggregated, AggregatedResult)
        assert result.pr_comment == ""
        assert result.inline_comments_count == 0
        assert result.success is False
        assert result.error == ""

    def test_file_report_defaults(self) -> None:
        report = FileReport(file_path="src/main.py", language="python")
        assert report.file_path == "src/main.py"
        assert report.language == "python"
        assert report.skip_llm is False
        assert isinstance(report.ast_report, ASTReport)
        assert report.rule_violations == []
        assert isinstance(report.llm_result, LLMReviewResult)
        assert report.lines_of_code == 0
        assert report.errors == []


# ---------------------------------------------------------------------------
# Test: Tiered strategy
# ---------------------------------------------------------------------------


class TestApplyTieredStrategy:
    """Test the tiered analysis strategy for different PR sizes."""

    def test_small_pr_all_get_full_analysis(self) -> None:
        """PR with <=20 files: all files get skip_llm=False."""
        engine = _make_engine(large_pr_threshold=20, very_large_pr_threshold=100)
        files = [_make_file_diff(file_path=f"file_{i}.py", additions=i) for i in range(15)]
        result = engine._apply_tiered_strategy(files, total_changed=15)

        assert len(result) == 15
        for _file_diff, skip_llm in result:
            assert skip_llm is False

    def test_small_pr_at_threshold(self) -> None:
        """PR with exactly 20 files: all get full analysis."""
        engine = _make_engine(large_pr_threshold=20, very_large_pr_threshold=100)
        files = [_make_file_diff(file_path=f"file_{i}.py", additions=i) for i in range(20)]
        result = engine._apply_tiered_strategy(files, total_changed=20)

        assert len(result) == 20
        for _, skip_llm in result:
            assert skip_llm is False

    def test_medium_pr_top_10_get_llm(self) -> None:
        """PR with 21-100 files: top 10 by additions get LLM, rest skip."""
        engine = _make_engine(large_pr_threshold=20, very_large_pr_threshold=100)
        # 30 files with varying additions
        files = [_make_file_diff(file_path=f"file_{i}.py", additions=i) for i in range(30)]
        result = engine._apply_tiered_strategy(files, total_changed=50)

        assert len(result) == 30
        llm_count = sum(1 for _, skip in result if not skip)
        skip_count = sum(1 for _, skip in result if skip)
        assert llm_count == 10
        assert skip_count == 20

    def test_medium_pr_sorted_by_additions_desc(self) -> None:
        """Files with most additions get LLM first in medium PRs."""
        engine = _make_engine(large_pr_threshold=20, very_large_pr_threshold=100)
        # Create 12 files: top 10 get LLM, bottom 2 skip
        files = [_make_file_diff(file_path=f"big_{i}.py", additions=100 - i) for i in range(12)]
        result = engine._apply_tiered_strategy(files, total_changed=50)

        # Sorted by additions desc; top 10 get LLM, last 2 skip
        assert len(result) == 12
        assert result[0][0].additions == 100  # highest additions first
        for _, skip_llm in result[:10]:
            assert skip_llm is False
        for _, skip_llm in result[10:]:
            assert skip_llm is True

    def test_large_pr_top_5_get_llm(self) -> None:
        """PR with 100+ files: only top 5 by additions get LLM, rest skip."""
        engine = _make_engine(large_pr_threshold=20, very_large_pr_threshold=100)
        files = [_make_file_diff(file_path=f"file_{i}.py", additions=200 - i) for i in range(150)]
        result = engine._apply_tiered_strategy(files, total_changed=150)

        # Large PR: only top 20 files processed, top 5 get LLM, next 15 skip
        # But the input list has 150 files; the method filters to top 20
        llm_count = sum(1 for _, skip in result if not skip)
        skip_count = sum(1 for _, skip in result if skip)
        assert llm_count == 5
        assert skip_count == 15
        assert len(result) == 20  # only top 20 are included

    def test_empty_files_list(self) -> None:
        """Empty file list returns empty result."""
        engine = _make_engine()
        result = engine._apply_tiered_strategy([], total_changed=0)
        assert result == []


# ---------------------------------------------------------------------------
# Test: review_pull_request
# ---------------------------------------------------------------------------


class TestReviewPullRequest:
    """Test the main review pipeline."""

    @pytest.mark.asyncio
    async def test_no_code_files_returns_early(self) -> None:
        """When no code files are found, return success with appropriate message."""
        engine = _make_engine()
        _stub_formatter_ok(engine.formatter)

        # PR info with changed files but they are not code
        pr_info = _make_pr_info(changed_files=3)

        # Non-code files (e.g., .md, .txt)
        non_code_files = [
            _make_file_diff(file_path="README.md", language="", status="modified"),
            _make_file_diff(file_path="docs.txt", language="", status="added"),
        ]
        # Make these non-code by using extensions that aren't in CODE_EXTENSIONS
        # is_code_file is a property based on extension, so .md/.txt will be False

        github_client = _make_github_client()
        github_client.get_pr_info.return_value = pr_info
        github_client.get_pr_files.return_value = non_code_files

        result = await engine.review_pull_request(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123",
            github_client=github_client,
        )

        assert result.success is True
        assert "没有支持的代码文件" in result.aggregated.summary
        # close() should NOT be called since we passed a client
        github_client.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_happy_path(self) -> None:
        """Full happy-path review with mocked dependencies."""
        engine = _make_engine()
        _stub_aggregate_ok(engine.aggregator)
        _stub_formatter_ok(engine.formatter)

        pr_info = _make_pr_info(changed_files=1)
        code_file = _make_file_diff(file_path="src/main.py", language="python")

        github_client = _make_github_client()
        github_client.get_pr_info.return_value = pr_info
        github_client.get_pr_files.return_value = [code_file]
        github_client.get_file_content.return_value = "print('hello')"

        # Mock the sub-analyzer methods directly
        ast_report = ASTReport(file_path="src/main.py", language="python")
        with patch.object(engine, "_analyze_files_parallel") as mock_parallel:
            file_report = FileReport(
                file_path="src/main.py",
                language="python",
                ast_report=ast_report,
                lines_of_code=10,
            )
            mock_parallel.return_value = [file_report]

            result = await engine.review_pull_request(
                repo_full_name="owner/repo",
                pr_number=42,
                commit_sha="abc123",
                github_client=github_client,
            )

        assert result.success is True
        assert result.repo_full_name == "owner/repo"
        assert result.pr_number == 42
        assert result.commit_sha == "abc123"
        assert result.error == ""
        # Formatter should have been called
        engine.formatter.format_pr_comment.assert_called()
        # Aggregator should have been called
        engine.aggregator.aggregate.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_handling_returns_failure_result(self) -> None:
        """Exception during pipeline sets success=False and captures error."""
        engine = _make_engine()

        github_client = _make_github_client()
        github_client.get_pr_info.side_effect = ConnectionError("GitHub API down")

        result = await engine.review_pull_request(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123",
            github_client=github_client,
        )

        assert result.success is False
        assert "GitHub API down" in result.error
        assert result.repo_full_name == "owner/repo"

    @pytest.mark.asyncio
    async def test_creates_own_client_when_none_provided(self) -> None:
        """When github_client is None, engine should create and close its own."""
        engine = _make_engine()
        _stub_aggregate_ok(engine.aggregator)
        _stub_formatter_ok(engine.formatter)

        pr_info = _make_pr_info(changed_files=1)
        code_file = _make_file_diff(file_path="src/main.py", language="python")

        mock_client = _make_github_client()
        mock_client.get_pr_info.return_value = pr_info
        mock_client.get_pr_files.return_value = [code_file]

        with patch.object(engine, "_analyze_files_parallel") as mock_parallel:
            mock_parallel.return_value = [
                FileReport(file_path="src/main.py", language="python", lines_of_code=10)
            ]
            with patch(
                "app.core.review_engine._get_github_client",
                return_value=mock_client,
            ) as mock_factory:
                result = await engine.review_pull_request(
                    repo_full_name="owner/repo",
                    pr_number=42,
                    commit_sha="abc123",
                )

        mock_factory.assert_awaited_once()
        mock_client.close.assert_awaited_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_own_client_closed_on_error(self) -> None:
        """Own client is closed even when the pipeline throws."""
        engine = _make_engine()

        mock_client = _make_github_client()
        mock_client.get_pr_info.side_effect = RuntimeError("boom")

        with patch(
            "app.core.review_engine._get_github_client",
            return_value=mock_client,
        ):
            result = await engine.review_pull_request(
                repo_full_name="owner/repo",
                pr_number=42,
                commit_sha="abc123",
            )

        mock_client.close.assert_awaited_once()
        assert result.success is False
        assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_removed_files_are_excluded(self) -> None:
        """Files with status='removed' should be filtered out."""
        engine = _make_engine()
        _stub_formatter_ok(engine.formatter)

        pr_info = _make_pr_info(changed_files=2)
        removed_file = _make_file_diff(file_path="src/old.py", status="removed", language="python")
        active_file = _make_file_diff(file_path="src/new.py", status="modified", language="python")

        github_client = _make_github_client()
        github_client.get_pr_info.return_value = pr_info
        github_client.get_pr_files.return_value = [removed_file, active_file]

        with patch.object(engine, "_analyze_files_parallel") as mock_parallel:
            mock_parallel.return_value = [
                FileReport(file_path="src/new.py", language="python", lines_of_code=10)
            ]
            engine.aggregator.aggregate.return_value = AggregatedResult(
                scores=ReviewScores(), files_reviewed=1, lines_of_code=10
            )
            await engine.review_pull_request(
                repo_full_name="owner/repo",
                pr_number=42,
                commit_sha="abc123",
                github_client=github_client,
            )

        # Only the non-removed file should have been analyzed
        called_files = mock_parallel.call_args[0][0]
        assert len(called_files) == 1
        assert called_files[0][0].file_path == "src/new.py"


# ---------------------------------------------------------------------------
# Test: _analyze_single_file
# ---------------------------------------------------------------------------


class TestAnalyzeSingleFile:
    """Test per-file analysis with graceful error handling."""

    @pytest.mark.asyncio
    async def test_ast_failure_graceful_degradation(self) -> None:
        """AST analyzer exception is caught and recorded in errors."""
        engine = _make_engine()
        engine.ast_analyzer.analyze.side_effect = RuntimeError("AST parse error")
        engine.rule_engine.check.return_value = []
        engine.llm_analyzer.analyze = AsyncMock(
            return_value=LLMReviewResult(summary="ok", score=85)
        )

        file_diff = _make_file_diff(file_path="src/broken.py", content="bad code")
        github_client = _make_github_client()
        github_client.get_file_content.return_value = "bad code"

        report = await engine._analyze_single_file(file_diff, "owner/repo", "abc123", github_client)

        assert isinstance(report, FileReport)
        assert report.file_path == "src/broken.py"
        assert any("ast:" in e for e in report.errors)

    @pytest.mark.asyncio
    async def test_rule_failure_graceful_degradation(self) -> None:
        """Rule engine exception is caught and recorded in errors."""
        engine = _make_engine()
        engine.ast_analyzer.analyze.return_value = ASTReport(file_path="src/main.py")
        engine.rule_engine.check.side_effect = RuntimeError("Rule crash")
        engine.llm_analyzer.analyze = AsyncMock(
            return_value=LLMReviewResult(summary="ok", score=85)
        )

        file_diff = _make_file_diff(file_path="src/main.py", content="x = 1")
        github_client = _make_github_client()
        github_client.get_file_content.return_value = "x = 1"

        report = await engine._analyze_single_file(file_diff, "owner/repo", "abc123", github_client)

        assert isinstance(report, FileReport)
        assert any("rule:" in e for e in report.errors)

    @pytest.mark.asyncio
    async def test_llm_failure_graceful_degradation(self) -> None:
        """LLM analyzer exception is caught; result degrades to empty."""
        engine = _make_engine()
        engine.ast_analyzer.analyze.return_value = ASTReport(file_path="src/main.py")
        engine.rule_engine.check.return_value = []
        engine.llm_analyzer.analyze = AsyncMock(side_effect=RuntimeError("API timeout"))

        file_diff = _make_file_diff(file_path="src/main.py", content="x = 1")
        github_client = _make_github_client()
        github_client.get_file_content.return_value = "x = 1"

        report = await engine._analyze_single_file(file_diff, "owner/repo", "abc123", github_client)

        assert isinstance(report, FileReport)
        assert any("llm:" in e for e in report.errors)
        # LLM result should be empty with error reason
        assert "API timeout" in report.llm_result.error

    @pytest.mark.asyncio
    async def test_skip_llm_returns_skipped_result(self) -> None:
        """When skip_llm=True, LLM analyzer is not called."""
        engine = _make_engine()
        engine.ast_analyzer.analyze.return_value = ASTReport(file_path="src/main.py")
        engine.rule_engine.check.return_value = []
        # Should never be called
        engine.llm_analyzer.analyze = AsyncMock()

        file_diff = _make_file_diff(file_path="src/main.py", content="x = 1")
        github_client = _make_github_client()
        github_client.get_file_content.return_value = "x = 1"

        report = await engine._analyze_single_file(
            file_diff, "owner/repo", "abc123", github_client, skip_llm=True
        )

        assert isinstance(report, FileReport)
        engine.llm_analyzer.analyze.assert_not_awaited()
        assert "Skipped by tiered strategy" in report.llm_result.summary

    @pytest.mark.asyncio
    async def test_all_analyzers_succeed(self) -> None:
        """When all analyzers succeed, report has no errors."""
        engine = _make_engine()
        engine.ast_analyzer.analyze.return_value = ASTReport(
            file_path="src/main.py",
            language="python",
            issues=[ASTIssue(line_number=5, message="complex function")],
        )
        engine.rule_engine.check.return_value = [
            RuleViolation(
                rule_id="SEC001",
                severity="critical",
                category="security",
                message="SQL injection",
                line_number=10,
            )
        ]
        engine.llm_analyzer.analyze = AsyncMock(
            return_value=LLMReviewResult(
                issues=[LLMIssue(line_number=3, message="security issue")],
                summary="Found issues",
                score=70,
            )
        )

        file_diff = _make_file_diff(file_path="src/main.py", content="x = 1")
        github_client = _make_github_client()
        github_client.get_file_content.return_value = "x = 1"

        report = await engine._analyze_single_file(file_diff, "owner/repo", "abc123", github_client)

        assert report.errors == []
        assert len(report.ast_report.issues) == 1
        assert len(report.rule_violations) == 1
        assert len(report.llm_result.issues) == 1

    @pytest.mark.asyncio
    async def test_content_fetch_failure_falls_back_to_patch(self) -> None:
        """When get_file_content fails, falls back to raw_patch."""
        engine = _make_engine()
        engine.ast_analyzer.analyze.return_value = ASTReport(file_path="src/main.py")
        engine.rule_engine.check.return_value = []
        engine.llm_analyzer.analyze = AsyncMock(return_value=LLMReviewResult(summary="ok"))

        file_diff = _make_file_diff(file_path="src/main.py", content="", raw_patch="fallback patch")
        github_client = _make_github_client()
        github_client.get_file_content.side_effect = RuntimeError("Not found")

        report = await engine._analyze_single_file(file_diff, "owner/repo", "abc123", github_client)

        # content should have been set to raw_patch as fallback
        assert file_diff.content == "fallback patch"
        assert any("fetch:" in e for e in report.errors)


# ---------------------------------------------------------------------------
# Test: _analyze_files_parallel
# ---------------------------------------------------------------------------


class TestAnalyzeFilesParallel:
    """Test parallel file analysis with semaphore."""

    @pytest.mark.asyncio
    async def test_parallel_respects_max_concurrency(self) -> None:
        """Semaphore limits concurrent file analyses."""
        engine = _make_engine(max_concurrent_files=2)

        call_count = 0
        max_concurrent = 0
        current = 0
        lock = asyncio.Lock()

        async def mock_analyze_single(*args, **kwargs):
            nonlocal call_count, max_concurrent, current
            async with lock:
                call_count += 1
                current += 1
                if current > max_concurrent:
                    max_concurrent = current
            await asyncio.sleep(0.05)
            async with lock:
                current -= 1
            return FileReport(file_path="f.py", language="python")

        with patch.object(engine, "_analyze_single_file", side_effect=mock_analyze_single):
            files = [(_make_file_diff(file_path=f"file_{i}.py"), False) for i in range(6)]
            reports = await engine._analyze_files_parallel(
                files, "owner/repo", "abc123", _make_github_client()
            )

        assert len(reports) == 6
        assert call_count == 6
        assert max_concurrent <= 2


# ---------------------------------------------------------------------------
# Test: _post_to_github
# ---------------------------------------------------------------------------


class TestPostToGithub:
    """Test GitHub comment posting with error handling."""

    @pytest.mark.asyncio
    async def test_success_posts_summary_and_status(self) -> None:
        """Successful post includes summary comment and commit status update."""
        engine = _make_engine()
        _stub_formatter_ok(engine.formatter)

        github_client = _make_github_client()

        aggregated = AggregatedResult(
            issues=[],
            scores=ReviewScores(overall=95),
            summary="Clean code",
        )
        result = ReviewResult(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123",
            aggregated=aggregated,
            pr_comment="## Review: 95/100",
        )

        await engine._post_to_github(github_client, "owner/repo", 42, "abc123", result)

        github_client.post_review_comment.assert_awaited_once_with(
            "owner/repo", 42, "## Review: 95/100"
        )
        github_client.update_review_status.assert_awaited_once()
        status_call = github_client.update_review_status.call_args
        assert status_call[0][0] == "owner/repo"
        assert status_call[0][1] == "abc123"
        assert status_call[0][2] == "success"  # no critical issues

    @pytest.mark.asyncio
    async def test_inline_failure_does_not_block_summary(self) -> None:
        """Inline comments failure is logged but does not prevent status update."""
        engine = _make_engine()
        engine.formatter.format_inline_comments_payload.return_value = [
            {"path": "src/main.py", "line": 5, "body": "issue"}
        ]

        github_client = _make_github_client()
        github_client.post_inline_comments.side_effect = RuntimeError("API error")

        aggregated = AggregatedResult(
            issues=[],
            scores=ReviewScores(overall=90),
        )
        result = ReviewResult(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123",
            aggregated=aggregated,
            pr_comment="## Review",
        )

        # Should NOT raise
        await engine._post_to_github(github_client, "owner/repo", 42, "abc123", result)

        # Summary comment was still posted
        github_client.post_review_comment.assert_awaited_once()
        # Status was still updated despite inline failure
        github_client.update_review_status.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_failure_is_caught(self) -> None:
        """When post_review_comment raises, error is caught (not re-raised)."""
        engine = _make_engine()

        github_client = _make_github_client()
        github_client.post_review_comment.side_effect = RuntimeError("GitHub down")

        aggregated = AggregatedResult(
            issues=[],
            scores=ReviewScores(overall=90),
        )
        result = ReviewResult(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123",
            aggregated=aggregated,
            pr_comment="## Review",
        )

        # Should NOT raise -- error is logged internally
        await engine._post_to_github(github_client, "owner/repo", 42, "abc123", result)

    @pytest.mark.asyncio
    async def test_no_comment_when_pr_comment_empty(self) -> None:
        """When pr_comment is empty, post_review_comment is not called."""
        engine = _make_engine()
        _stub_formatter_ok(engine.formatter)

        github_client = _make_github_client()

        aggregated = AggregatedResult(scores=ReviewScores())
        result = ReviewResult(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123",
            aggregated=aggregated,
            pr_comment="",  # empty
        )

        await engine._post_to_github(github_client, "owner/repo", 42, "abc123", result)

        github_client.post_review_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_critical_issues_set_failure_status(self) -> None:
        """When critical issues exist, commit status is 'failure'."""
        engine = _make_engine()
        engine.formatter.format_inline_comments_payload.return_value = []

        github_client = _make_github_client()

        critical_issue = UnifiedIssue(
            file_path="src/main.py",
            line_number=10,
            source="rule",
            category="security",
            severity="critical",
            message="SQL injection",
        )
        aggregated = AggregatedResult(
            issues=[critical_issue],
            scores=ReviewScores(overall=40),
        )
        result = ReviewResult(
            repo_full_name="owner/repo",
            pr_number=42,
            commit_sha="abc123",
            aggregated=aggregated,
            pr_comment="## Review: critical issues found",
        )

        await engine._post_to_github(github_client, "owner/repo", 42, "abc123", result)

        status_call = github_client.update_review_status.call_args
        assert status_call[0][2] == "failure"


# ---------------------------------------------------------------------------
# Test: _run_ast, _run_rules, _run_llm
# ---------------------------------------------------------------------------


class TestSubAnalyzerMethods:
    """Test the individual _run_ast, _run_rules, _run_llm methods."""

    @pytest.mark.asyncio
    async def test_run_ast_empty_content(self) -> None:
        """When file content is empty, return empty AST report."""
        engine = _make_engine()
        file_diff = _make_file_diff(content="")

        result = await engine._run_ast(file_diff)

        assert isinstance(result, ASTReport)
        assert result.file_path == file_diff.file_path
        engine.ast_analyzer.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_ast_with_content(self) -> None:
        """When content exists, AST analyzer is invoked via executor."""
        engine = _make_engine()
        expected = ASTReport(file_path="src/main.py", language="python")
        engine.ast_analyzer.analyze.return_value = expected

        file_diff = _make_file_diff(content="x = 1")
        result = await engine._run_ast(file_diff)

        assert result == expected
        engine.ast_analyzer.analyze.assert_called_once_with("src/main.py", "x = 1", "python")

    @pytest.mark.asyncio
    async def test_run_rules_empty_code(self) -> None:
        """When both content and raw_patch are empty, return empty list."""
        engine = _make_engine()
        file_diff = _make_file_diff(content="", raw_patch="")

        result = await engine._run_rules(file_diff)

        assert result == []
        engine.rule_engine.check.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_rules_with_content(self) -> None:
        """When content exists, rule engine checks it."""
        engine = _make_engine()
        violations = [
            RuleViolation(
                rule_id="SEC001",
                severity="critical",
                category="security",
                message="SQL",
                line_number=5,
            )
        ]
        engine.rule_engine.check.return_value = violations

        file_diff = _make_file_diff(content="cursor.execute(query)")
        result = await engine._run_rules(file_diff)

        assert result == violations
        engine.rule_engine.check.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_rules_falls_back_to_raw_patch(self) -> None:
        """When content is empty, rule engine uses raw_patch."""
        engine = _make_engine()
        engine.rule_engine.check.return_value = []

        file_diff = _make_file_diff(content="", raw_patch="diff --git")
        await engine._run_rules(file_diff)

        engine.rule_engine.check.assert_called_once_with(
            "diff --git", "python", file_path="src/main.py"
        )

    @pytest.mark.asyncio
    async def test_run_llm_empty_diff(self) -> None:
        """When raw_patch is empty, return empty LLM result."""
        engine = _make_engine()
        file_diff = _make_file_diff(raw_patch="")

        result = await engine._run_llm(file_diff)

        assert isinstance(result, LLMReviewResult)
        engine.llm_analyzer.analyze.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_llm_with_diff(self) -> None:
        """When raw_patch exists, LLM analyzer is called."""
        engine = _make_engine()
        expected = LLMReviewResult(summary="LGTM", score=90)
        engine.llm_analyzer.analyze = AsyncMock(return_value=expected)

        file_diff = _make_file_diff(raw_patch="+x = 1", content="x = 1")
        result = await engine._run_llm(file_diff)

        assert result == expected
        engine.llm_analyzer.analyze.assert_awaited_once_with(
            code_diff="+x = 1",
            file_context="x = 1",
            language="python",
            file_path="src/main.py",
        )


# ---------------------------------------------------------------------------
# Test: _get_github_client factory
# ---------------------------------------------------------------------------


class TestGetGithubClient:
    """Test the module-level factory function."""

    @pytest.mark.asyncio
    async def test_factory_delegates_to_get_github_client(self) -> None:
        """Factory function delegates to the imported get_github_client."""
        from app.core.review_engine import _get_github_client

        mock_client = _make_github_client()
        with patch(
            "app.services.github_client.get_github_client",
            return_value=mock_client,
            new_callable=AsyncMock,
        ) as mock_fn:
            result = await _get_github_client()

        mock_fn.assert_awaited_once()
        assert result is mock_client
