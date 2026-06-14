"""Unit tests for inline-comment line snapping (GitHub 422 fix).

GitHub 的 review API 只允许把行内评论锚定到 diff hunk 内的行(新增行 ``+`` 与
context 行 `` `` 在新文件中的行号)。分析器(LLM/AST/rule)给出的行号往往来自
完整文件内容,落在 hunk 之外时,整批 POST 返回 ``422 Unprocessable Entity``
(review API 是 all-or-nothing,一个非法行号会让全部评论失败)。这里回归测试
patch 解析 + 行号吸附逻辑。
"""

from __future__ import annotations

from app.analyzers.result_aggregator import (
    AggregatedResult,
    ReviewScores,
    UnifiedIssue,
)
from app.services.comment_formatter import (
    CommentFormatter,
    parse_valid_diff_lines,
    snap_to_valid_line,
)

# @@ -10,3 +10,4 @@ — old 10..12, new 10..13
#   unchanged  -> new line 10 (context)
# - old        -> deleted, no new line
# + new1       -> new line 11
# + new2       -> new line 12
PATCH_BASIC = "@@ -10,3 +10,4 @@\n unchanged\n-old\n+new1\n+new2\n"
# valid RIGHT-side lines: 10, 11, 12


class TestParseValidDiffLines:
    def test_extracts_added_and_context_lines(self) -> None:
        assert parse_valid_diff_lines(PATCH_BASIC) == [10, 11, 12]

    def test_empty_patch_returns_empty(self) -> None:
        assert parse_valid_diff_lines("") == []

    def test_no_patch_field(self) -> None:
        assert parse_valid_diff_lines("binary file, no patch") == []

    def test_multiple_hunks(self) -> None:
        patch = (
            "@@ -1,2 +1,2 @@\n a\n-b\n+C\n"
            "@@ -10,2 +11,2 @@\n d\n-e\n+F\n"
        )
        # hunk1: 1(context a), 2(C). hunk2: 11(d), 12(F).
        assert parse_valid_diff_lines(patch) == [1, 2, 11, 12]

    def test_deleted_only_line_not_a_right_target(self) -> None:
        # hunk that only deletes — no new-file lines to anchor on
        patch = "@@ -5,1 +5,0 @@\n-gone\n"
        assert parse_valid_diff_lines(patch) == []


class TestSnapToValidLine:
    def test_exact_match_returns_same(self) -> None:
        assert snap_to_valid_line(11, [10, 11, 12]) == 11

    def test_above_range_snaps_down(self) -> None:
        assert snap_to_valid_line(99, [10, 11, 12]) == 12

    def test_below_range_snaps_up(self) -> None:
        assert snap_to_valid_line(5, [10, 11, 12]) == 10

    def test_mid_gap_picks_nearest(self) -> None:
        # 4 is closer to 3 than to 8 -> 3
        assert snap_to_valid_line(4, [3, 8]) == 3
        # 6 is closer to 8 than to 3 -> 8
        assert snap_to_valid_line(6, [3, 8]) == 8

    def test_empty_valid_returns_none(self) -> None:
        assert snap_to_valid_line(5, []) is None


def _result(file_path: str, line: int, *, line_end: int | None = None) -> AggregatedResult:
    return AggregatedResult(
        issues=[
            UnifiedIssue(
                file_path=file_path,
                line_number=line,
                line_end=line_end,
                source="llm",
                category="security",
                severity="critical",
                message="bad thing",
                suggestion="fix it",
                confidence=0.9,
            )
        ],
        scores=ReviewScores(overall=50, security=50, performance=50, maintainability=50),
        summary="",
        files_reviewed=1,
        lines_of_code=10,
        llm_summary="",
        llm_tokens=0,
    )


class TestFormatInlinePayloadSnapping:
    def test_out_of_range_line_snapped_to_nearest_valid(self) -> None:
        fmt = CommentFormatter()
        res = _result("a.py", 99)
        payload = fmt.format_inline_comments_payload(
            res, max_comments=50, valid_lines_by_file={"a.py": [10, 11, 12]}
        )
        assert len(payload) == 1
        assert payload[0]["line"] == 12

    def test_file_with_no_valid_lines_is_dropped(self) -> None:
        fmt = CommentFormatter()
        res = _result("b.py", 5)
        payload = fmt.format_inline_comments_payload(
            res, max_comments=50, valid_lines_by_file={"b.py": []}
        )
        assert payload == []

    def test_file_missing_from_map_is_dropped(self) -> None:
        # If we have a map but this file isn't in it (e.g. binary/no patch), skip it
        # rather than risk a 422 on a guessed line.
        fmt = CommentFormatter()
        res = _result("c.py", 5)
        payload = fmt.format_inline_comments_payload(
            res, max_comments=50, valid_lines_by_file={"a.py": [10]}
        )
        assert payload == []

    def test_no_map_falls_back_to_reported_line(self) -> None:
        """Backward-compat: callers that don't pass a map keep old behavior."""
        fmt = CommentFormatter()
        res = _result("a.py", 42)
        payload = fmt.format_inline_comments_payload(res, max_comments=50)
        assert len(payload) == 1
        assert payload[0]["line"] == 42

    def test_mixed_files_keeps_valid_drops_invalid(self) -> None:
        fmt = CommentFormatter()
        res = AggregatedResult(
            issues=[
                UnifiedIssue(
                    file_path="good.py", line_number=11, source="llm",
                    category="security", severity="critical", message="ok",
                ),
                UnifiedIssue(
                    file_path="bad.py", line_number=5, source="llm",
                    category="security", severity="critical", message="nope",
                ),
            ],
            scores=ReviewScores(overall=50, security=50, performance=50, maintainability=50),
            summary="", files_reviewed=2, lines_of_code=20, llm_summary="", llm_tokens=0,
        )
        payload = fmt.format_inline_comments_payload(
            res, max_comments=50,
            valid_lines_by_file={"good.py": [10, 11, 12], "bad.py": []},
        )
        assert len(payload) == 1
        assert payload[0]["path"] == "good.py"
        assert payload[0]["line"] == 11
