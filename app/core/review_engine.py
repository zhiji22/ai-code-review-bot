"""Review Engine - orchestrates the full PR review pipeline.

Pipeline:
1. Fetch PR diff via GitHub API
2. Filter supported code files
3. Per-file parallel analysis: AST + Rules + LLM (asyncio.gather with Semaphore)
4. Aggregate results + calculate scores
5. Post PR comment + inline comments
6. Return ReviewResult

Error handling: each analyzer fails independently; partial results are acceptable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import structlog

from app.analyzers.ast_analyzer import ASTAnalyzer, ASTReport
from app.analyzers.llm_analyzer import LLMAnalyzer, LLMReviewResult
from app.analyzers.result_aggregator import (
    AggregatedResult,
    ResultAggregator,
)
from app.analyzers.rule_engine import RuleEngine, RuleViolation
from app.services.comment_formatter import CommentFormatter

if TYPE_CHECKING:
    from app.services.github_client import FileDiff, GitHubClient

logger = structlog.get_logger(__name__)


@dataclass
class FileReport:
    """Analysis result for a single file."""

    file_path: str
    language: str
    skip_llm: bool = False
    ast_report: ASTReport = field(default_factory=lambda: ASTReport.empty())
    rule_violations: list[RuleViolation] = field(default_factory=list)
    llm_result: LLMReviewResult = field(default_factory=lambda: LLMReviewResult.empty())
    lines_of_code: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    """Complete PR review result."""

    repo_full_name: str
    pr_number: int
    commit_sha: str
    aggregated: AggregatedResult = field(default_factory=AggregatedResult)
    pr_comment: str = ""
    inline_comments_count: int = 0
    success: bool = False
    error: str = ""


class ReviewEngine:
    """Orchestrates the complete review pipeline for a PR."""

    def __init__(
        self,
        max_concurrent_files: int = 4,
        max_inline_comments: int = 50,
        large_pr_threshold: int = 20,
        very_large_pr_threshold: int = 100,
    ) -> None:
        self.ast_analyzer = ASTAnalyzer()
        self.rule_engine = RuleEngine()
        self.llm_analyzer = LLMAnalyzer()
        self.aggregator = ResultAggregator()
        self.formatter = CommentFormatter()

        self.max_concurrent_files = max_concurrent_files
        self.max_inline_comments = max_inline_comments
        self.large_pr_threshold = large_pr_threshold
        self.very_large_pr_threshold = very_large_pr_threshold

    async def review_pull_request(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        github_client: GitHubClient | None = None,
    ) -> ReviewResult:
        """Execute the full review pipeline for a PR.

        Args:
            repo_full_name: GitHub repo (owner/repo)
            pr_number: PR number
            commit_sha: Head commit SHA
            github_client: Optional injected client (for testing)

        Returns:
            ReviewResult with aggregated issues and comment
        """
        result = ReviewResult(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            commit_sha=commit_sha,
        )

        own_client = False
        if github_client is None:
            github_client = await _get_github_client()
            own_client = True

        try:
            # 1. Fetch PR info
            pr_info = await github_client.get_pr_info(repo_full_name, pr_number)
            logger.info(
                "review_started",
                repo=repo_full_name,
                pr=pr_number,
                title=pr_info.title,
                files=pr_info.changed_files,
            )

            # 2. Fetch changed files
            files = await github_client.get_pr_files(repo_full_name, pr_number)

            # 3. Filter code files
            code_files = [f for f in files if f.is_code_file and f.status != "removed"]

            if not code_files:
                result.success = True
                result.aggregated.summary = "No supported code files to review."
                result.pr_comment = self.formatter.format_pr_comment(
                    result.aggregated, repo_full_name, pr_number
                )
                return result

            # 4. Tiered strategy for large PRs (DESIGN.md §16)
            tiered_files = self._apply_tiered_strategy(code_files, pr_info.changed_files)

            # 5. Parallel file analysis
            file_reports = await self._analyze_files_parallel(
                tiered_files, repo_full_name, commit_sha, github_client
            )

            # 6. Aggregate
            file_result_dicts = [
                {
                    "file_path": fr.file_path,
                    "ast_report": fr.ast_report,
                    "rule_violations": fr.rule_violations,
                    "llm_result": fr.llm_result,
                    "lines_of_code": fr.lines_of_code,
                }
                for fr in file_reports
            ]
            result.aggregated = self.aggregator.aggregate(file_result_dicts)

            # 7. Format PR comment
            result.pr_comment = self.formatter.format_pr_comment(
                result.aggregated, repo_full_name, pr_number
            )
            result.inline_comments_count = min(
                len(result.aggregated.issues), self.max_inline_comments
            )

            # 8. Post to GitHub
            await self._post_to_github(github_client, repo_full_name, pr_number, commit_sha, result)

            result.success = True
            logger.info(
                "review_completed",
                repo=repo_full_name,
                pr=pr_number,
                score=result.aggregated.scores.overall,
                issues=result.aggregated.total_issues,
            )

        except Exception as e:
            logger.error(
                "review_failed",
                repo=repo_full_name,
                pr=pr_number,
                error=str(e),
                exc_info=True,
            )
            result.error = str(e)
        finally:
            if own_client:
                await github_client.close()

        return result

    async def _analyze_files_parallel(
        self,
        tiered_files: list[tuple[FileDiff, bool]],
        repo_full_name: str,
        commit_sha: str,
        github_client: GitHubClient,
    ) -> list[FileReport]:
        """Analyze multiple files in parallel with semaphore-based concurrency."""
        sem = asyncio.Semaphore(self.max_concurrent_files)

        async def _one(file: FileDiff, skip_llm: bool) -> FileReport:
            async with sem:
                return await self._analyze_single_file(
                    file, repo_full_name, commit_sha, github_client, skip_llm=skip_llm
                )

        return await asyncio.gather(*[_one(f, skip) for f, skip in tiered_files])

    async def _analyze_single_file(
        self,
        file: FileDiff,
        repo_full_name: str,
        commit_sha: str,
        github_client: GitHubClient,
        skip_llm: bool = False,
    ) -> FileReport:
        """Run AST + Rules + LLM on a single file.

        Per DESIGN.md §4.2.2: analyzers fail independently.
        """
        report = FileReport(
            file_path=file.file_path,
            language=file.language,
            lines_of_code=file.lines_of_code,
        )

        # Fetch full file content for context
        try:
            file.content = await github_client.get_file_content(
                repo_full_name, file.file_path, commit_sha
            )
        except Exception as e:
            logger.warning("fetch_content_failed", file=file.file_path, error=str(e))
            report.errors.append(f"fetch: {e!s}")
            file.content = file.raw_patch  # Fallback to diff only

        # Run all 3 analyzers in parallel (skip LLM if tiered strategy says so)
        ast_task = asyncio.create_task(self._run_ast(file), name=f"ast:{file.file_path}")
        rule_task = asyncio.create_task(self._run_rules(file), name=f"rule:{file.file_path}")
        llm_task: asyncio.Task[object] = asyncio.create_task(
            self._run_llm(file) if not skip_llm else asyncio.sleep(0),
            name=f"llm:{file.file_path}",
        )

        results = await asyncio.gather(ast_task, rule_task, llm_task, return_exceptions=True)

        # Process AST result
        if isinstance(results[0], Exception):
            logger.warning("ast_failed", file=file.file_path, error=str(results[0]))
            report.errors.append(f"ast: {results[0]!s}")
        else:
            report.ast_report = cast("ASTReport", results[0])

        # Process rule result
        if isinstance(results[1], Exception):
            logger.warning("rule_failed", file=file.file_path, error=str(results[1]))
            report.errors.append(f"rule: {results[1]!s}")
        else:
            report.rule_violations = cast("list[RuleViolation]", results[1])

        # Process LLM result (graceful degradation)
        if skip_llm:
            report.llm_result = LLMReviewResult.empty("Skipped by tiered strategy for large PR")
        elif isinstance(results[2], Exception):
            logger.warning("llm_failed", file=file.file_path, error=str(results[2]))
            report.errors.append(f"llm: {results[2]!s}")
            report.llm_result = LLMReviewResult.empty(str(results[2]))
        else:
            report.llm_result = cast("LLMReviewResult", results[2])

        return report

    async def _run_ast(self, file: FileDiff) -> ASTReport:
        """Run AST analysis (CPU-bound, offloaded to executor)."""
        if not file.content:
            return ASTReport.empty(file.file_path, file.language)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.ast_analyzer.analyze,
            file.file_path,
            file.content,
            file.language,
        )

    async def _run_rules(self, file: FileDiff) -> list[RuleViolation]:
        """Run rule engine checks."""
        code = file.content if file.content else file.raw_patch
        if not code:
            return []
        return self.rule_engine.check(code, file.language, file_path=file.file_path)

    async def _run_llm(self, file: FileDiff) -> LLMReviewResult:
        """Run LLM analysis with caching."""
        if not file.raw_patch:
            return LLMReviewResult.empty("No diff to analyze")
        return await self.llm_analyzer.analyze(
            code_diff=file.raw_patch,
            file_context=file.content,
            language=file.language,
            file_path=file.file_path,
        )

    def _apply_tiered_strategy(
        self, files: list[FileDiff], total_changed: int
    ) -> list[tuple[FileDiff, bool]]:
        """Apply tiered analysis strategy for large PRs (§16).

        Returns list of (FileDiff, skip_llm) tuples.
        - <=20 files: full analysis (skip_llm=False for all)
        - 21-100 files: full AST+Rules on all, LLM on top 10 by change size
        - 100+ files: full AST+Rules on top 20, LLM on top 5
        """
        if total_changed <= self.large_pr_threshold:
            return [(f, False) for f in files]

        sorted_files = sorted(files, key=lambda f: f.additions, reverse=True)

        if total_changed <= self.very_large_pr_threshold:
            top_llm = sorted_files[:10]
            rest = sorted_files[10:]
            return [(f, False) for f in top_llm] + [(f, True) for f in rest]

        top_files = sorted_files[:20]
        top_llm = top_files[:5]
        rest = top_files[5:]
        return [(f, False) for f in top_llm] + [(f, True) for f in rest]

    async def _post_to_github(
        self,
        client: GitHubClient,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        result: ReviewResult,
    ) -> None:
        """Post review comments to GitHub PR."""
        try:
            # Post summary comment
            if result.pr_comment:
                await client.post_review_comment(repo_full_name, pr_number, result.pr_comment)

            # Post inline comments via review API
            inline_payload = self.formatter.format_inline_comments_payload(
                result.aggregated, max_comments=self.max_inline_comments
            )
            if inline_payload:
                try:
                    await client.post_inline_comments(
                        repo_full_name,
                        pr_number,
                        commit_sha,
                        inline_payload,
                    )
                except Exception as e:
                    logger.warning(
                        "inline_comments_failed",
                        repo=repo_full_name,
                        pr=pr_number,
                        error=str(e),
                    )

            # Update commit status
            status = "success" if result.aggregated.critical_count == 0 else "failure"
            desc = (
                f"Score: {result.aggregated.scores.overall}/100"
                if result.aggregated.total_issues == 0 or status == "success"
                else f"{result.aggregated.critical_count} critical issue(s)"
            )
            await client.update_review_status(repo_full_name, commit_sha, status, description=desc)

        except Exception as e:
            logger.error(
                "github_post_failed",
                repo=repo_full_name,
                pr=pr_number,
                error=str(e),
            )


async def _get_github_client() -> GitHubClient:
    """Factory for default GitHub client."""
    from app.services.github_client import get_github_client

    return await get_github_client()
