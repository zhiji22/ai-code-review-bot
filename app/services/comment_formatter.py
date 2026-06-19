"""PR Comment Formatter - generates GitHub-flavored Markdown comments.

Generates:
1. Summary table (scores + issue counts)
2. Inline file-level comments (sorted by severity)
3. Final recommendation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from app.analyzers.result_aggregator import AggregatedResult, UnifiedIssue

logger = logging.getLogger(__name__)


def parse_valid_diff_lines(patch: str) -> list[int]:
    """Extract new-file line numbers a GitHub inline comment may anchor on.

    GitHub's review API rejects (HTTP 422) any inline comment whose ``line`` does
    not fall inside a diff hunk on the requested ``side``. For ``side=RIGHT`` the
    legal targets are the new-file line numbers of added (``+``) and unchanged
    context (`` ``) lines within a hunk. Deleted (``-``) lines have no RIGHT-side
    line number and are therefore excluded.

    Args:
        patch: The unified-diff ``patch`` text for a single file (may be empty
            for binary/renamed-without-change files).

    Returns:
        Sorted list of valid RIGHT-side line numbers. Empty if there is no patch.
    """
    if not patch:
        return []

    valid: list[int] = []
    new_line = 0
    in_hunk = False

    for raw in patch.splitlines():
        if raw.startswith("@@"):
            # @@ -a,b +c,d @@  -> c is the new-file start line
            plus_idx = raw.find("+", 1)  # skip the leading "@@"
            if plus_idx == -1:
                in_hunk = False
                continue
            rest = raw[plus_idx + 1 :]
            head = rest.split(",", 1)[0]
            try:
                new_line = int(head) - 1  # first diff body line increments to `c`
                in_hunk = True
            except ValueError:
                in_hunk = False
            continue

        if not in_hunk:
            continue

        # Skip the file header lines that also start with +++/--- inside a patch.
        if raw.startswith("+++") or raw.startswith("---"):
            continue

        prefix = raw[:1]
        if prefix == "+" or prefix == " ":
            new_line += 1
            valid.append(new_line)
        elif prefix == "-":
            # Deleted line: advances only the old-file counter, not the new one.
            continue
        # "\" (no newline) and anything else: ignore.

    return valid


def snap_to_valid_line(line: int, valid_lines: list[int]) -> int | None:
    """Snap a reported line to the nearest valid diff line.

    Prefers an exact match, otherwise returns the valid line with the smallest
    absolute distance (ties broken toward the lower line number). Returns
    ``None`` when ``valid_lines`` is empty, signalling the caller to drop the
    comment rather than risk a 422.
    """
    if not valid_lines:
        return None
    if line in valid_lines:
        return line
    return min(valid_lines, key=lambda v: (abs(v - line), v))


class CommentFormatter:
    """Formats review results into GitHub PR comments."""

    SEVERITY_ICON: ClassVar[dict[str, str]] = {
        "critical": "🔴",
        "warning": "🟡",
        "info": "🔵",
    }

    SEVERITY_LABEL: ClassVar[dict[str, str]] = {
        "critical": "严重",
        "warning": "警告",
        "info": "建议",
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
            f"{icon} **{self.SEVERITY_LABEL.get(issue.severity, '问题')}**",
            f"| `{issue.source}` | `{issue.category}` | 置信度: {issue.confidence:.0%}",
        ]

        if issue.rule_id:
            parts.append(f"| 规则: `{issue.rule_id}`")

        parts.append("")
        parts.append(f"**{issue.message}**")
        parts.append("")

        if issue.suggestion:
            parts.append(f"> 💡 **建议**: {issue.suggestion}")

        return "\n".join(parts)

    def format_inline_comments_payload(
        self,
        result: AggregatedResult,
        max_comments: int = 50,
        valid_lines_by_file: dict[str, list[int]] | None = None,
    ) -> list[dict[str, object]]:
        """Build the payload for GitHub's review API with inline comments.

        Args:
            result: Aggregated review result
            max_comments: Max number of inline comments (GitHub limits)
            valid_lines_by_file: Optional mapping of file path -> diff-valid
                RIGHT-side line numbers (from :func:`parse_valid_diff_lines`).
                When provided, each comment's line is snapped to the nearest
                valid line and comments with no valid anchor are dropped. This
                prevents GitHub from rejecting the whole batch with HTTP 422
                (the reviews API is all-or-nothing). When ``None``, the reported
                line is used as-is (legacy behavior).

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
            reported = issue.line_end if issue.line_end else issue.line_number
            if valid_lines_by_file is not None:
                valid = valid_lines_by_file.get(issue.file_path, [])
                line = snap_to_valid_line(reported, valid)
                if line is None:
                    # No diff line to anchor on in this file -> skip rather than
                    # let one bad line fail the entire review submission (422).
                    continue
            else:
                line = reported
            comments.append(
                {
                    "path": issue.file_path,
                    "line": line,
                    "side": "RIGHT",
                    "body": self.format_inline_comment(issue),
                }
            )

        return comments

    # --- Internal formatters ---

    def _format_header(self, result: AggregatedResult) -> str:
        """Comment header with bot branding."""
        score = result.scores.overall
        if score >= 80:
            badge = "✅"
            label = "代码良好"
        elif score >= 60:
            badge = "⚠️"
            label = "需要关注"
        else:
            badge = "❌"
            label = "需要修改"

        return (
            f"## 🤖 AI 代码审查 — {badge} {label}\n\n"
            f"**评分: {score}/100** · "
            f"{result.files_reviewed} 个文件 · "
            f"审查了 {result.lines_of_code} 行代码\n"
        )

    def _format_score_table(self, result: AggregatedResult) -> str:
        """Summary score table."""
        s = result.scores
        return (
            "### 📊 评分详情\n\n"
            "| 维度 | 分数 | 状态 |\n"
            "|------|------|------|\n"
            f"| 🔒 安全性 | {s.security}/100 | {_score_status(s.security)} |\n"
            f"| ⚡ 性能 | {s.performance}/100 | {_score_status(s.performance)} |\n"
            f"| 🔧 可维护性 | {s.maintainability}/100 | {_score_status(s.maintainability)} |\n"
            f"| **综合** | **{s.overall}/100** | {_score_status(s.overall)} |\n"
            "\n"
            f"| 严重程度 | 数量 |\n"
            f"|----------|------|\n"
            f"| 🔴 严重 | {result.critical_count} |\n"
            f"| 🟡 警告 | {result.warning_count} |\n"
            f"| 🔵 建议 | {result.info_count} |\n"
        )

    def _format_issues_by_file(self, result: AggregatedResult) -> str:
        """Group issues by file with details."""
        if not result.issues:
            return "### ✅ 未发现问题\n\n干得漂亮！代码看起来很整洁。"

        # Group by file
        by_file: dict[str, list[UnifiedIssue]] = {}
        for issue in result.issues:
            by_file.setdefault(issue.file_path, []).append(issue)

        sections: list[str] = ["### 📝 按文件分类的问题\n"]

        for file_path in sorted(by_file):
            file_issues = by_file[file_path]
            sections.append(f"\n#### `{file_path}`\n")

            # Group by severity within file
            for severity in ("critical", "warning", "info"):
                sev_issues = [i for i in file_issues if i.severity == severity]
                if not sev_issues:
                    continue
                icon = self.SEVERITY_ICON[severity]
                label = self.SEVERITY_LABEL[severity]
                sections.append(f"\n**{icon} {label} ({len(sev_issues)})**\n")
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
                "### 🚨 建议\n\n"
                f"⚠️ 发现 **{result.critical_count} 个严重问题**，"
                "合并前必须修复。请修复后重新请求审查。"
            )
        if result.warning_count > 3:
            return "### 💡 建议\n\n" "检测到多个警告。建议在合并前处理这些问题，以提升代码质量。"
        return "### ✅ 建议\n\n" "代码质量良好！次要建议可酌情处理。"

    def _format_footer(self) -> str:
        """Bot footer."""
        return (
            "---\n" "<sub>🤖 由 AI 代码审查机器人生成 · " "[配置](/settings) · [文档](/docs)</sub>"
        )


def _score_status(score: int) -> str:
    """Convert score to status emoji."""
    if score >= 80:
        return "✅ 良好"
    if score >= 60:
        return "⚠️ 一般"
    return "❌ 较差"
