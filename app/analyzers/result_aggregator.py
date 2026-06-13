"""Result Aggregator - combines AST, Rule, and LLM results.

Responsibilities:
1. Deduplicate overlapping issues from different analyzers
2. Calculate multi-dimensional scores (security/performance/maintainability)
3. Sort by severity
4. Generate final ReviewResult
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.analyzers.ast_analyzer import ASTReport
from app.analyzers.llm_analyzer import LLMReviewResult

if TYPE_CHECKING:
    from app.analyzers.rule_engine import RuleViolation

logger = logging.getLogger(__name__)

# --- Scoring Constants (per DESIGN.md §7.2) ---

SOURCE_CONFIDENCE = {
    "rule": 1.0,
    "ast": 0.95,
    "llm": 0.75,
}

SEVERITY_PENALTY = {
    "critical": 10,
    "warning": 5,
    "info": 1,
}

ISSUE_TOLERANCE_PER_100_LOC = {
    "critical": 0,
    "warning": 5,
    "info": 10,
}

# --- LLM Cost Constants (USD per 1M tokens) ---
# Pricing for common models (as of 2024)
LLM_PRICING_PER_1M_TOKENS = {
    # Qwen models (Alibaba DashScope)
    "qwen-plus": {"prompt": 0.004, "completion": 0.012},
    "qwen-turbo": {"prompt": 0.002, "completion": 0.006},
    "qwen-max": {"prompt": 0.02, "completion": 0.06},
    # OpenAI models
    "gpt-4o": {"prompt": 2.50, "completion": 10.00},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00},
    "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
    # Default fallback
    "default": {"prompt": 0.01, "completion": 0.03},
}


def calculate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate LLM API cost in USD.

    Args:
        model: Model name (e.g., "qwen-plus", "gpt-4o")
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens

    Returns:
        Cost in USD
    """
    # Normalize model name (handle versioned models like "gpt-4o-2024-05-13")
    model_base = model.split("-2024")[0].split("-2025")[0] if "-" in model else model
    pricing = LLM_PRICING_PER_1M_TOKENS.get(model_base, LLM_PRICING_PER_1M_TOKENS["default"])

    prompt_cost = (prompt_tokens / 1_000_000) * pricing["prompt"]
    completion_cost = (completion_tokens / 1_000_000) * pricing["completion"]

    return round(prompt_cost + completion_cost, 6)


# --- Unified Issue Model ---


@dataclass
class UnifiedIssue:
    """A single deduplicated issue from any source."""

    file_path: str
    line_number: int
    source: str  # ast, rule, llm
    category: str  # security, performance, maintainability, style
    severity: str  # critical, warning, info
    message: str
    line_end: int | None = None
    suggestion: str = ""
    rule_id: str = ""
    confidence: float = 1.0

    @property
    def dedup_key(self) -> tuple[str, int, str]:
        """Key for deduplication: (file, line, category)."""
        return (self.file_path, self.line_number, self.category)


@dataclass
class ReviewScores:
    """Multi-dimensional review scores."""

    overall: int = 100
    security: int = 100
    performance: int = 100
    maintainability: int = 100
    style: int = 100


@dataclass
class AggregatedResult:
    """Final aggregated review result."""

    issues: list[UnifiedIssue] = field(default_factory=list)
    scores: ReviewScores = field(default_factory=ReviewScores)
    summary: str = ""
    files_reviewed: int = 0
    lines_of_code: int = 0
    llm_summary: str = ""
    llm_tokens: int = 0
    llm_cost_usd: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")

    @property
    def total_issues(self) -> int:
        return len(self.issues)


class ResultAggregator:
    """Aggregates results from all analyzers."""

    def aggregate(
        self,
        file_results: list[dict[str, Any]],
    ) -> AggregatedResult:
        """Aggregate per-file analysis results.

        Args:
            file_results: List of dicts with keys:
                - file_path: str
                - ast_report: ASTReport
                - rule_violations: list[RuleViolation]
                - llm_result: LLMReviewResult
                - lines_of_code: int

        Returns:
            AggregatedResult with deduped issues and scores
        """
        all_issues: list[UnifiedIssue] = []
        total_loc = 0
        llm_summary_parts: list[str] = []
        total_llm_tokens = 0
        total_llm_cost = 0.0
        llm_model = ""

        for fr in file_results:
            file_path = fr.get("file_path", "")
            ast_report_raw = fr.get("ast_report")
            ast_report: ASTReport = (
                ast_report_raw if isinstance(ast_report_raw, ASTReport) else ASTReport.empty()
            )
            rule_violations_raw = fr.get("rule_violations", [])
            rule_violations: list[RuleViolation] = (
                rule_violations_raw if isinstance(rule_violations_raw, list) else []
            )
            llm_result_raw = fr.get("llm_result")
            llm_result: LLMReviewResult = (
                llm_result_raw
                if isinstance(llm_result_raw, LLMReviewResult)
                else LLMReviewResult.empty()
            )
            loc: int = fr.get("lines_of_code", 0)
            total_loc += loc

            # Convert AST issues
            for issue in ast_report.issues:
                all_issues.append(
                    UnifiedIssue(
                        file_path=file_path,
                        line_number=issue.line_number,
                        source="ast",
                        category=issue.category,
                        severity=issue.severity,
                        message=issue.message,
                        line_end=issue.line_end,
                        suggestion=issue.suggestion,
                        confidence=issue.confidence,
                    )
                )

            # Convert rule violations
            for violation in rule_violations:
                all_issues.append(
                    UnifiedIssue(
                        file_path=file_path,
                        line_number=violation.line_number,
                        source="rule",
                        category=violation.category,
                        severity=violation.severity,
                        message=violation.message,
                        line_end=violation.line_end,
                        suggestion=violation.suggestion,
                        rule_id=violation.rule_id,
                        confidence=1.0,
                    )
                )

            # Convert LLM issues
            for llm_issue in llm_result.issues:
                all_issues.append(
                    UnifiedIssue(
                        file_path=file_path,
                        line_number=llm_issue.line_number,
                        source="llm",
                        category=llm_issue.category,
                        severity=llm_issue.severity,
                        message=llm_issue.message,
                        line_end=llm_issue.line_end,
                        suggestion=llm_issue.suggestion,
                        confidence=llm_issue.confidence,
                    )
                )

            if llm_result.summary:
                llm_summary_parts.append(f"**{file_path}**: {llm_result.summary}")
            total_llm_tokens += llm_result.total_tokens

            # Calculate LLM cost if we have token info and model
            if llm_result.total_tokens > 0 and llm_result.model:
                if not llm_model:
                    llm_model = llm_result.model
                total_llm_cost += calculate_llm_cost(
                    llm_result.model,
                    llm_result.prompt_tokens,
                    llm_result.completion_tokens,
                )

        # Deduplicate
        deduped = _deduplicate(all_issues)

        # Sort by severity (critical > warning > info)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        deduped.sort(key=lambda x: (severity_order.get(x.severity, 3), x.file_path, x.line_number))

        # Calculate scores
        scores = calculate_score(deduped, total_loc)

        # Build summary
        summary = _build_summary(deduped, scores, len(file_results))

        return AggregatedResult(
            issues=deduped,
            scores=scores,
            summary=summary,
            files_reviewed=len(file_results),
            lines_of_code=total_loc,
            llm_summary="\n".join(llm_summary_parts),
            llm_tokens=total_llm_tokens,
            llm_cost_usd=total_llm_cost,
        )


def _deduplicate(issues: list[UnifiedIssue]) -> list[UnifiedIssue]:
    """Remove duplicate issues at the same file+line+category.

    When duplicates exist, prefer rule > ast > llm (by confidence).
    """
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    source_priority = {"rule": 0, "ast": 1, "llm": 2}

    seen: dict[tuple[str, int, str], UnifiedIssue] = {}
    for issue in issues:
        key = issue.dedup_key
        if key not in seen:
            seen[key] = issue
        else:
            existing = seen[key]
            # Prefer higher severity, then higher-confidence source
            if severity_order.get(issue.severity, 3) < severity_order.get(existing.severity, 3) or (
                issue.severity == existing.severity
                and source_priority.get(issue.source, 3) < source_priority.get(existing.source, 3)
            ):
                seen[key] = issue

    return list(seen.values())


def calculate_score(
    issues: list[UnifiedIssue],
    lines_of_code: int,
) -> ReviewScores:
    """Calculate multi-dimensional review scores.

    Per DESIGN.md §7.2:
    - Score by category independently
    - Weight by source confidence
    - Normalize by LOC (tolerance per 100 LOC)
    - Capped 0-100
    """
    base = 100
    loc_factor = max(lines_of_code / 100, 1)

    # Include all categories: security, performance, maintainability, style
    categories: dict[str, list[UnifiedIssue]] = {
        "security": [],
        "performance": [],
        "maintainability": [],
        "style": [],
    }

    for issue in issues:
        if issue.category in categories:
            categories[issue.category].append(issue)

    def category_score(cat_issues: list[UnifiedIssue]) -> int:
        penalty_by_severity: dict[str, float] = {"critical": 0, "warning": 0, "info": 0}
        for i in cat_issues:
            conf = i.confidence * SOURCE_CONFIDENCE.get(i.source, 0.5)
            penalty_by_severity[i.severity] += SEVERITY_PENALTY[i.severity] * conf

        normalized_penalty = 0.0
        for sev, penalty in penalty_by_severity.items():
            tolerance = ISSUE_TOLERANCE_PER_100_LOC[sev] * loc_factor
            excess = max(0, penalty - tolerance)
            normalized_penalty += excess

        return max(0, int(base - normalized_penalty))

    sec = category_score(categories["security"])
    perf = category_score(categories["performance"])
    maint = category_score(categories["maintainability"])
    style = category_score(categories["style"])

    # Overall score: weighted average of all categories
    # security (40%), performance (25%), maintainability (25%), style (10%)
    overall = int(0.4 * sec + 0.25 * perf + 0.25 * maint + 0.1 * style)

    return ReviewScores(
        overall=min(100, max(0, overall)),
        security=sec,
        performance=perf,
        maintainability=maint,
        style=style,
    )


def _build_summary(
    issues: list[UnifiedIssue],
    scores: ReviewScores,
    files_reviewed: int,
) -> str:
    """Generate a text summary of the review."""
    critical = sum(1 for i in issues if i.severity == "critical")
    warning = sum(1 for i in issues if i.severity == "warning")
    info = sum(1 for i in issues if i.severity == "info")

    parts = [
        f"Reviewed {files_reviewed} file(s).",
        f"Overall score: **{scores.overall}/100**.",
    ]
    if critical:
        parts.append(f"{critical} critical issue(s) found.")
    if warning:
        parts.append(f"{warning} warning(s).")
    if info:
        parts.append(f"{info} info/suggestion(s).")

    if critical == 0 and warning == 0:
        parts.append("Code looks good overall!")

    return " ".join(parts)
