"""PR Comment Formatter - generates GitHub-flavored Markdown comments.

Generates:
1. Summary table (scores + issue counts)
2. Inline file-level comments (sorted by severity)
3. Final recommendation
"""

from __future__ import annotations

import logging

from app.analyzers.result_aggregator import AggregatedResult, UnifiedIssue

logger = logging.getLogger(__name__)


class CommentFormatter:
    """Formats review results into GitHub PR comments."""

    SEVERITY_ICON = {
        "critical": "🔴",
        "warning": "🟡",
        "info": "🔵",
    }

    SEVERITY_LABEL = {
        "critical": "Critical",
        "warning": "Warning",
        "info": "Info",
    }

    def format_pr_comment(
        self,
        result: AggregatedResult,
        repo_full_name: str,
        pr_number: int,
    ) -> str:
        """Generate the main PR review comment as Markdown.

        Args:
            result: Aggregated review result
            repo_full_name: GitHub repo full name (owner/repo)
            pr_number: PR number

        Returns:
            GitHub-flavored Markdown comment body
        """
        sections: list[str] = []

        # Header
        sections.append(self._format_header(result))

        # Summary table
        sections.append(self._format_score_table(result))

        # Issues by file
        sections.append(self._format_issues_by_file(result))

        # Recommendation
        sections.append(self._format_recommendation(result))

        # Footer
        sections.append(self._format_footer())

        return "\n\n".join(sections)

    def format_inline_comment(self, issue: UnifiedIssue) -> str:
        """Format a single issue for inline (line-level) comment.

        Args:
            issue: The unified issue

        Returns:
            Markdown string for the inline comment
        """
        icon = self.SEVERITY_ICON.get(issue.severity, "ℹ️")
        parts = [
            f"{icon} **{self.SEVERITY_LABEL.get(issue.severity, 'Issue')}**",
            f"| `{issue.source}` | `{issue.category}` | confidence: {issue.confidence:.0%}",
        ]

        if issue.rule_id:
            parts.append(f"| Rule: `{issue.rule_id}`")

        parts.append("")
        parts.append(f"**{issue.message}**")
        parts.append("")

        if issue.suggestion:
            parts.append(f"> 💡 **Suggestion**: {issue.suggestion}")

        return "\n".join(parts)

    def format_inline_comments_payload(
        self,
        result: AggregatedResult,
        max_comments: int = 50,
    ) -> list[dict[str, object]]:
        """Build the payload for GitHub's review API with inline comments.

        Args:
            result: Aggregated review result
            max_comments: Max number of inline comments (GitHub limits)

        Returns:
            List of comment dicts for the API payload
        """
        # Sort: critical first, then by file/line
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        sorted_issues = sorted(
            result.issues,
            key=lambda i: (
                severity_order.get(i.severity, 3),
                i.file_path,
                i.line_number,
            ),
        )

        comments: list[dict[str, object]] = []
        for issue in sorted_issues[:max_comments]:
            line = issue.line_end if issue.line_end else issue.line_number
            comments.append({
                "path": issue.file_path,
                "line": line,
                "side": "RIGHT",
                "body": self.format_inline_comment(issue),
            })

        return comments

    # --- Internal formatters ---

    def _format_header(self, result: AggregatedResult) -> str:
        """Comment header with bot branding."""
        score = result.scores.overall
        if score >= 80:
            badge = "✅"
            label = "Looks Good"
        elif score >= 60:
            badge = "⚠️"
            label = "Needs Attention"
        else:
            badge = "❌"
            label = "Needs Changes"

        return (
            f"## 🤖 AI Code Review — {badge} {label}\n\n"
            f"**Score: {score}/100** · "
            f"{result.files_reviewed} file(s) · "
            f"{result.lines_of_code} LOC reviewed\n"
        )

    def _format_score_table(self, result: AggregatedResult) -> str:
        """Summary score table."""
        s = result.scores
        return (
            "### 📊 Score Breakdown\n\n"
            "| Dimension | Score | Status |\n"
            "|-----------|-------|--------|\n"
            f"| 🔒 Security | {s.security}/100 | {_score_status(s.security)} |\n"
            f"| ⚡ Performance | {s.performance}/100 | {_score_status(s.performance)} |\n"
            f"| 🔧 Maintainability | {s.maintainability}/100 | {_score_status(s.maintainability)} |\n"
            f"| **Overall** | **{s.overall}/100** | {_score_status(s.overall)} |\n"
            "\n"
            f"| Severity | Count |\n"
            f"|----------|-------|\n"
            f"| 🔴 Critical | {result.critical_count} |\n"
            f"| 🟡 Warning | {result.warning_count} |\n"
            f"| 🔵 Info | {result.info_count} |\n"
        )

    def _format_issues_by_file(self, result: AggregatedResult) -> str:
        """Group issues by file with details."""
        if not result.issues:
            return "### ✅ No issues found\n\nGreat work! The code looks clean."

        # Group by file
        by_file: dict[str, list[UnifiedIssue]] = {}
        for issue in result.issues:
            by_file.setdefault(issue.file_path, []).append(issue)

        sections: list[str] = ["### 📝 Issues by File\n"]

        for file_path in sorted(by_file):
            file_issues = by_file[file_path]
            sections.append(f"\n#### `{file_path}`\n")

            # Group by severity within file
            for severity in ("critical", "warning", "info"):
                sev_issues = [i for i in file_issues if i.severity == severity]
                if not sev_issues:
                    continue
                icon = self.SEVERITY_ICON[severity]
                sections.append(f"\n**{icon} {severity.title()} ({len(sev_issues)})**\n")
                for issue in sev_issues:
                    line_link = f"L{issue.line_number}"
                    if issue.line_end and issue.line_end > issue.line_number:
                        line_link = f"L{issue.line_number}-L{issue.line_end}"
                    sections.append(
                        f"- [`{line_link}`] **{issue.message}** "
                        f"`({issue.source}/{issue.category})`\n"
                    )
                    if issue.suggestion:
                        sections.append(f"  - 💡 {issue.suggestion}\n")

        return "".join(sections)

    def _format_recommendation(self, result: AggregatedResult) -> str:
        """Final recommendation section."""
        if result.critical_count > 0:
            return (
                "### 🚨 Recommendation\n\n"
                f"⚠️ **{result.critical_count} critical issue(s)** must be addressed "
                "before merging. Please fix and re-request review."
            )
        if result.warning_count > 3:
            return (
                "### 💡 Recommendation\n\n"
                "Several warnings detected. Consider addressing them before merging "
                "for better code quality."
            )
        return (
            "### ✅ Recommendation\n\n"
            "Code quality looks good! Minor suggestions are optional."
        )

    def _format_footer(self) -> str:
        """Bot footer."""
        return (
            "---\n"
            "<sub>🤖 Generated by AI Code Review Bot · "
            "[Configure](/settings) · [Docs](/docs)</sub>"
        )


def _score_status(score: int) -> str:
    """Convert score to status emoji."""
    if score >= 80:
        return "✅ Good"
    if score >= 60:
        return "⚠️ Fair"
    return "❌ Poor"
