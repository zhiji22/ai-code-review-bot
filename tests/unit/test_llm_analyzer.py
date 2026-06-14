"""Unit tests for LLM Analyzer - OpenAI-powered deep code analysis.

Tests cover:
- LLMIssue / LLMReviewResult dataclasses
- Cache helpers (_diff_hash, _get_cached, _set_cached)
- Prompt building (_build_user_prompt)
- Response parsing (_parse_response)
- LLMAnalyzer class (init, model selection, analyze flow, error handling)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.analyzers.llm_analyzer import (
    LLMAnalyzer,
    LLMIssue,
    LLMReviewResult,
    _build_user_prompt,
    _diff_hash,
    _get_cached,
    _parse_response,
    _set_cached,
)

# Module path for patching the module-level logger.
_LOGGER = "app.analyzers.llm_analyzer.logger"


# ---------------------------------------------------------------------------
# 1. LLMIssue dataclass
# ---------------------------------------------------------------------------


class TestLLMIssue:
    """Tests for the LLMIssue dataclass."""

    def test_llm_issue_dataclass_defaults(self) -> None:
        """LLMIssue should provide sensible defaults for all optional fields."""
        issue = LLMIssue(line_number=10)

        assert issue.line_number == 10
        assert issue.line_end is None
        assert issue.category == ""
        assert issue.severity == "warning"
        assert issue.message == ""
        assert issue.suggestion == ""
        assert issue.confidence == 0.75

    def test_llm_issue_all_fields(self) -> None:
        """LLMIssue should accept all fields explicitly."""
        issue = LLMIssue(
            line_number=5,
            line_end=10,
            category="security",
            severity="critical",
            message="SQL injection vulnerability",
            suggestion="Use parameterized queries",
            confidence=0.95,
        )

        assert issue.line_number == 5
        assert issue.line_end == 10
        assert issue.category == "security"
        assert issue.severity == "critical"
        assert issue.message == "SQL injection vulnerability"
        assert issue.suggestion == "Use parameterized queries"
        assert issue.confidence == 0.95


# ---------------------------------------------------------------------------
# 2. LLMReviewResult dataclass
# ---------------------------------------------------------------------------


class TestLLMReviewResult:
    """Tests for the LLMReviewResult dataclass."""

    def test_llm_review_result_defaults(self) -> None:
        """LLMReviewResult should provide sensible defaults."""
        result = LLMReviewResult()

        assert result.issues == []
        assert result.summary == ""
        assert result.score == 80
        assert result.model == ""
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0
        assert result.cached is False
        assert result.error == ""

    def test_llm_review_result_empty_with_reason(self) -> None:
        """empty() with a reason should set summary and error."""
        result = LLMReviewResult.empty("something went wrong")

        assert result.issues == []
        assert result.summary == "LLM analysis unavailable: something went wrong"
        assert result.score == 80
        assert result.error == "something went wrong"
        assert result.cached is False

    def test_llm_review_result_empty_no_reason(self) -> None:
        """empty() without a reason should produce an empty summary string."""
        result = LLMReviewResult.empty("")

        assert result.issues == []
        assert result.summary == ""
        assert result.score == 80
        assert result.error == ""

    def test_llm_review_result_with_issues(self) -> None:
        """LLMReviewResult should hold issues and other metadata."""
        issues = [LLMIssue(line_number=1, severity="critical", category="security")]
        result = LLMReviewResult(
            issues=issues,
            summary="Found 1 issue",
            score=60,
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cached=True,
        )

        assert len(result.issues) == 1
        assert result.issues[0].severity == "critical"
        assert result.summary == "Found 1 issue"
        assert result.score == 60
        assert result.model == "gpt-4o"
        assert result.total_tokens == 150
        assert result.cached is True


# ---------------------------------------------------------------------------
# 3. _diff_hash
# ---------------------------------------------------------------------------


class TestDiffHash:
    """Tests for _diff_hash helper."""

    def test_diff_hash_deterministic(self) -> None:
        """Same input must always produce the same hash."""
        diff = "diff --git a/file.py b/file.py\n+print('hello')"
        hash1 = _diff_hash(diff)
        hash2 = _diff_hash(diff)

        assert hash1 == hash2
        assert isinstance(hash1, str)
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_diff_hash_different_inputs(self) -> None:
        """Different inputs must produce different hashes."""
        hash1 = _diff_hash("diff content A")
        hash2 = _diff_hash("diff content B")

        assert hash1 != hash2

    def test_diff_hash_empty_string(self) -> None:
        """Empty string should still produce a valid SHA-256 hash."""
        result = _diff_hash("")

        assert isinstance(result, str)
        assert len(result) == 64


# ---------------------------------------------------------------------------
# 4. _get_cached
# ---------------------------------------------------------------------------


class TestGetCached:
    """Tests for _get_cached async helper."""

    @pytest.mark.asyncio
    async def test_get_cached_hit(self) -> None:
        """Should return parsed dict when Redis has data."""
        cached_data = {"issues": [], "summary": "OK", "score": 95}
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(cached_data)

        with (
            patch(
                "app.analyzers.llm_analyzer.get_redis",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(_LOGGER),
        ):
            result = await _get_cached("some-key")

        assert result == cached_data
        mock_redis.get.assert_awaited_once_with("llm:some-key")

    @pytest.mark.asyncio
    async def test_get_cached_miss(self) -> None:
        """Should return None when Redis has no data for the key."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with (
            patch(
                "app.analyzers.llm_analyzer.get_redis",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(_LOGGER),
        ):
            result = await _get_cached("missing-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_error(self) -> None:
        """Should return None gracefully when Redis throws an exception."""
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = ConnectionError("Redis down")

        with (
            patch(
                "app.analyzers.llm_analyzer.get_redis",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(_LOGGER),
        ):
            result = await _get_cached("any-key")

        assert result is None


# ---------------------------------------------------------------------------
# 5. _set_cached
# ---------------------------------------------------------------------------


class TestSetCached:
    """Tests for _set_cached async helper."""

    @pytest.mark.asyncio
    async def test_set_cached_success(self) -> None:
        """Should store serialized data in Redis with correct TTL."""
        mock_redis = AsyncMock()
        data = {"issues": [], "summary": "clean", "score": 100}

        with (
            patch(
                "app.analyzers.llm_analyzer.get_redis",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(_LOGGER),
        ):
            await _set_cached("test-key", data)

        mock_redis.set.assert_awaited_once_with(
            "llm:test-key",
            json.dumps(data),
            ex=86400,
        )

    @pytest.mark.asyncio
    async def test_set_cached_custom_ttl(self) -> None:
        """Should respect custom TTL value."""
        mock_redis = AsyncMock()
        data = {"key": "value"}

        with (
            patch(
                "app.analyzers.llm_analyzer.get_redis",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(_LOGGER),
        ):
            await _set_cached("key2", data, ttl=3600)

        _args, kwargs = mock_redis.set.call_args
        assert kwargs.get("ex") == 3600

    @pytest.mark.asyncio
    async def test_set_cached_error(self) -> None:
        """Should not crash when Redis throws during write."""
        mock_redis = AsyncMock()
        mock_redis.set.side_effect = ConnectionError("Redis unavailable")

        with (
            patch(
                "app.analyzers.llm_analyzer.get_redis",
                new_callable=AsyncMock,
                return_value=mock_redis,
            ),
            patch(_LOGGER),
        ):
            # Must not raise
            await _set_cached("failing-key", {"data": 1})


# ---------------------------------------------------------------------------
# 6. _build_user_prompt
# ---------------------------------------------------------------------------


class TestBuildUserPrompt:
    """Tests for _build_user_prompt function."""

    def test_build_user_prompt_basic(self) -> None:
        """Prompt should include file path, language, and diff."""
        prompt = _build_user_prompt(
            code_diff="+print('hello')",
            file_context="",
            language="python",
            file_path="src/main.py",
        )

        assert "src/main.py" in prompt
        assert "python" in prompt
        assert "+print('hello')" in prompt
        assert "Code Diff" in prompt
        assert "```diff" in prompt

    def test_build_user_prompt_with_context(self) -> None:
        """Prompt should include file context section when provided."""
        prompt = _build_user_prompt(
            code_diff="+x = 1",
            file_context="def foo():\n    pass",
            language="python",
            file_path="app.py",
        )

        assert "File Context" in prompt
        assert "def foo():" in prompt

    def test_build_user_prompt_no_context(self) -> None:
        """Prompt should skip context section when file_context is empty."""
        prompt = _build_user_prompt(
            code_diff="+x = 1",
            file_context="",
            language="python",
            file_path="app.py",
        )

        assert "File Context" not in prompt

    def test_build_user_prompt_context_same_as_diff(self) -> None:
        """Prompt should skip context section when file_context equals code_diff."""
        diff = "+x = 1"
        prompt = _build_user_prompt(
            code_diff=diff,
            file_context=diff,
            language="python",
            file_path="app.py",
        )

        assert "File Context" not in prompt

    def test_build_user_prompt_truncates_diff(self) -> None:
        """Prompt should truncate diffs longer than 8000 characters."""
        long_diff = "A" * 10000
        prompt = _build_user_prompt(
            code_diff=long_diff,
            file_context="",
            language="python",
            file_path="big.py",
        )

        # The diff content is code_diff[:8000], so exactly 8000 A's appear
        assert "A" * 8000 in prompt
        # And no contiguous block longer than 8000 A's exists
        assert "A" * 8001 not in prompt

    def test_build_user_prompt_includes_json_schema_instruction(self) -> None:
        """Prompt should include the JSON schema instruction."""
        prompt = _build_user_prompt(
            code_diff="+x = 1",
            file_context="",
            language="python",
            file_path="app.py",
        )

        assert "JSON schema" in prompt

    def test_build_user_prompt_truncates_context(self) -> None:
        """Prompt should truncate file context longer than 4000 characters."""
        long_context = "B" * 5000
        prompt = _build_user_prompt(
            code_diff="+x = 1",
            file_context=long_context,
            language="python",
            file_path="app.py",
        )

        assert "File Context" in prompt
        # The context content is file_context[:4000], so exactly 4000 B's appear
        assert "B" * 4000 in prompt
        # And no contiguous block of 4001 B's exists
        assert "B" * 4001 not in prompt


# ---------------------------------------------------------------------------
# 7. _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    """Tests for _parse_response function."""

    def test_parse_response_basic(self) -> None:
        """Should parse a well-formed response dict."""
        data = {
            "issues": [
                {
                    "line": 10,
                    "line_end": 12,
                    "severity": "critical",
                    "category": "security",
                    "message": "SQL injection",
                    "suggestion": "Use parameterized query",
                    "confidence": 0.9,
                }
            ],
            "summary": "Found 1 security issue",
            "score": 70,
        }

        result = _parse_response(data)

        assert len(result.issues) == 1
        assert result.issues[0].line_number == 10
        assert result.issues[0].line_end == 12
        assert result.issues[0].severity == "critical"
        assert result.issues[0].category == "security"
        assert result.issues[0].message == "SQL injection"
        assert result.issues[0].suggestion == "Use parameterized query"
        assert result.issues[0].confidence == 0.9
        assert result.summary == "Found 1 security issue"
        assert result.score == 70

    def test_parse_response_empty_issues(self) -> None:
        """Should handle response with no issues."""
        data = {"issues": [], "summary": "Code looks clean", "score": 95}

        result = _parse_response(data)

        assert result.issues == []
        assert result.summary == "Code looks clean"
        assert result.score == 95

    def test_parse_response_score_clamped_low(self) -> None:
        """Score below 0 should be clamped to 0."""
        data = {"issues": [], "summary": "", "score": -10}

        result = _parse_response(data)

        assert result.score == 0

    def test_parse_response_score_clamped_high(self) -> None:
        """Score above 100 should be clamped to 100."""
        data = {"issues": [], "summary": "", "score": 150}

        result = _parse_response(data)

        assert result.score == 100

    def test_parse_response_score_boundary_zero(self) -> None:
        """Score of exactly 0 should remain 0."""
        data = {"issues": [], "summary": "", "score": 0}

        result = _parse_response(data)

        assert result.score == 0

    def test_parse_response_score_boundary_hundred(self) -> None:
        """Score of exactly 100 should remain 100."""
        data = {"issues": [], "summary": "", "score": 100}

        result = _parse_response(data)

        assert result.score == 100

    def test_parse_response_missing_fields(self) -> None:
        """Should use sensible defaults for missing fields."""
        data = {
            "issues": [
                {
                    "line": 5,
                    "severity": "warning",
                    "category": "style",
                    "message": "Bad naming",
                }
            ],
            "summary": "Minor issues",
            "score": 85,
        }

        result = _parse_response(data)

        issue = result.issues[0]
        assert issue.line_number == 5
        assert issue.line_end is None
        assert issue.suggestion == ""
        assert issue.confidence == 0.75

    def test_parse_response_missing_score(self) -> None:
        """Missing score should default to 80."""
        data = {"issues": [], "summary": "OK"}

        result = _parse_response(data)

        assert result.score == 80

    def test_parse_response_missing_summary(self) -> None:
        """Missing summary should default to empty string."""
        data = {"issues": [], "score": 90}

        result = _parse_response(data)

        assert result.summary == ""

    def test_parse_response_missing_issues_list(self) -> None:
        """Missing issues should default to empty list."""
        data = {"summary": "Clean", "score": 100}

        result = _parse_response(data)

        assert result.issues == []

    def test_parse_response_issue_defaults(self) -> None:
        """Issue with minimal data should use defaults for line_number, severity, etc."""
        data = {"issues": [{}], "summary": "", "score": 50}

        result = _parse_response(data)

        issue = result.issues[0]
        assert issue.line_number == 1  # default from .get("line", 1)
        assert issue.severity == "info"
        assert issue.category == "maintainability"
        assert issue.message == ""
        assert issue.suggestion == ""
        assert issue.confidence == 0.75


# ---------------------------------------------------------------------------
# 8. LLMAnalyzer.__init__
# ---------------------------------------------------------------------------


class TestLLMAnalyzerInit:
    """Tests for LLMAnalyzer initialization."""

    def test_init_with_defaults(self) -> None:
        """Should read defaults from settings when no overrides provided."""
        analyzer = LLMAnalyzer()

        assert analyzer._api_key is not None
        assert analyzer._model is not None
        assert analyzer._max_tokens > 0
        assert analyzer._temperature >= 0
        assert analyzer._client is None

    def test_init_with_overrides(self) -> None:
        """Should use provided values over settings defaults."""
        analyzer = LLMAnalyzer(
            api_key="sk-custom-key",
            model="gpt-4-turbo",
            max_tokens=4096,
            temperature=0.5,
        )

        assert analyzer._api_key == "sk-custom-key"
        assert analyzer._model == "gpt-4-turbo"
        assert analyzer._max_tokens == 4096
        assert analyzer._temperature == 0.5

    def test_init_temperature_zero(self) -> None:
        """Temperature of 0 should be accepted (not replaced by default)."""
        analyzer = LLMAnalyzer(temperature=0.0)

        assert analyzer._temperature == 0.0


# ---------------------------------------------------------------------------
# 9. LLMAnalyzer._get_client
# ---------------------------------------------------------------------------


class TestGetClient:
    """Tests for lazy AsyncOpenAI client initialization."""

    @patch("app.analyzers.llm_analyzer.AsyncOpenAI")
    def test_get_client_lazy_init(self, mock_openai_cls: MagicMock) -> None:
        """Client should be created on first access and reused afterwards."""
        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance

        analyzer = LLMAnalyzer(api_key="sk-test")
        client1 = analyzer._get_client()
        client2 = analyzer._get_client()

        assert client1 is client2
        mock_openai_cls.assert_called_once_with(
            api_key="sk-test",
            base_url=analyzer._base_url,
        )


# ---------------------------------------------------------------------------
# 10. LLMAnalyzer._select_model
# ---------------------------------------------------------------------------


class TestSelectModel:
    """Tests for model selection based on diff complexity."""

    def test_select_model_light(self) -> None:
        """Diffs with < 50 lines should use the light model."""
        analyzer = LLMAnalyzer()
        model = analyzer._select_model(49)

        assert model == analyzer._model_light

    def test_select_model_light_at_zero(self) -> None:
        """Zero lines should use the light model."""
        analyzer = LLMAnalyzer()
        model = analyzer._select_model(0)

        assert model == analyzer._model_light

    def test_select_model_full(self) -> None:
        """Diffs with >= 50 lines should use the full model."""
        analyzer = LLMAnalyzer()
        model = analyzer._select_model(50)

        assert model == analyzer._model

    def test_select_model_full_large(self) -> None:
        """Very large diffs should use the full model."""
        analyzer = LLMAnalyzer()
        model = analyzer._select_model(500)

        assert model == analyzer._model


# ---------------------------------------------------------------------------
# 11. LLMAnalyzer.analyze - cache hit
# ---------------------------------------------------------------------------


class TestAnalyzeCacheHit:
    """Tests for analyze() when cache has a result."""

    @pytest.mark.asyncio
    async def test_analyze_cache_hit(self) -> None:
        """Cached result should be returned without calling the OpenAI API."""
        cached_data = {
            "issues": [{"line": 1, "severity": "info", "category": "style", "message": "x"}],
            "summary": "Cached result",
            "score": 90,
            "model": "qwen-turbo",
        }

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=cached_data),
            patch("app.analyzers.llm_analyzer._set_cached") as mock_set,
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="some diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.cached is True
        assert result.summary == "Cached result"
        assert result.score == 90
        assert result.model == "qwen-turbo"
        # Should NOT write to cache on a hit
        mock_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_cache_hit_restores_tokens(self) -> None:
        """Cached result must restore token usage so cost tracking is not lost.

        Regression: previously the cache-hit path only restored `model`, leaving
        `total_tokens == 0`, which caused the llm_usage record (and thus the LLM
        cost on the dashboard) to be skipped for cached files.
        """
        cached_data = {
            "issues": [],
            "summary": "Cached result",
            "score": 90,
            "model": "qwen-turbo",
            "prompt_tokens": 123,
            "completion_tokens": 45,
            "total_tokens": 168,
        }

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=cached_data),
            patch("app.analyzers.llm_analyzer._set_cached") as mock_set,
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="some diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.cached is True
        assert result.model == "qwen-turbo"
        assert result.prompt_tokens == 123
        assert result.completion_tokens == 45
        assert result.total_tokens == 168
        mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# 12. LLMAnalyzer.analyze - success (happy path)
# ---------------------------------------------------------------------------


class TestAnalyzeSuccess:
    """Tests for analyze() successful API call path."""

    @pytest.mark.asyncio
    async def test_analyze_success(self) -> None:
        """Should call OpenAI API, parse response, and cache the result."""
        api_response = MagicMock()
        api_response.model = "qwen-plus"
        api_response.choices = [MagicMock()]
        api_response.choices[0].message.content = json.dumps(
            {
                "issues": [
                    {
                        "line": 3,
                        "severity": "warning",
                        "category": "performance",
                        "message": "N+1 query",
                        "suggestion": "Use select_related",
                        "confidence": 0.8,
                    }
                ],
                "summary": "Found 1 performance issue",
                "score": 75,
            }
        )
        api_response.usage = MagicMock()
        api_response.usage.prompt_tokens = 200
        api_response.usage.completion_tokens = 100
        api_response.usage.total_tokens = 300

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = api_response

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch("app.analyzers.llm_analyzer._set_cached", new_callable=AsyncMock) as mock_set,
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="some diff",
                file_context="context",
                language="python",
                file_path="app/models.py",
            )

        assert len(result.issues) == 1
        assert result.issues[0].line_number == 3
        assert result.issues[0].category == "performance"
        assert result.summary == "Found 1 performance issue"
        assert result.score == 75
        assert result.model == "qwen-plus"
        assert result.cached is False
        assert result.error == ""
        # Verify caching was attempted
        mock_set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_analyze_caches_result(self) -> None:
        """_set_cached should be called with the correct cache key and data."""
        api_response = MagicMock()
        api_response.model = "qwen-plus"
        api_response.choices = [MagicMock()]
        api_response.choices[0].message.content = json.dumps(
            {
                "issues": [],
                "summary": "Clean",
                "score": 100,
            }
        )
        api_response.usage = MagicMock()
        api_response.usage.prompt_tokens = 50
        api_response.usage.completion_tokens = 25
        api_response.usage.total_tokens = 75

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = api_response

        analyzer = LLMAnalyzer(api_key="sk-test")
        code_diff = "unique diff content for cache key"

        expected_cache_key = _diff_hash(code_diff)

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch("app.analyzers.llm_analyzer._set_cached", new_callable=AsyncMock) as mock_set,
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            await analyzer.analyze(
                code_diff=code_diff,
                file_context="",
                language="python",
                file_path="test.py",
            )

        mock_set.assert_awaited_once()
        call_args = mock_set.call_args
        assert call_args[0][0] == expected_cache_key
        # The cached data should include the issues and score
        cached_data = call_args[0][1]
        assert cached_data["score"] == 100

    @pytest.mark.asyncio
    async def test_analyze_token_tracking(self) -> None:
        """Result should contain token usage from the API response."""
        api_response = MagicMock()
        api_response.model = "qwen-plus"
        api_response.choices = [MagicMock()]
        api_response.choices[0].message.content = json.dumps(
            {
                "issues": [],
                "summary": "OK",
                "score": 95,
            }
        )
        api_response.usage = MagicMock()
        api_response.usage.prompt_tokens = 500
        api_response.usage.completion_tokens = 250
        api_response.usage.total_tokens = 750

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = api_response

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch("app.analyzers.llm_analyzer._set_cached", new_callable=AsyncMock),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.prompt_tokens == 500
        assert result.completion_tokens == 250
        assert result.total_tokens == 750

    @pytest.mark.asyncio
    async def test_analyze_no_usage_info(self) -> None:
        """Should handle missing usage info gracefully."""
        api_response = MagicMock()
        api_response.model = "qwen-plus"
        api_response.choices = [MagicMock()]
        api_response.choices[0].message.content = json.dumps(
            {
                "issues": [],
                "summary": "OK",
                "score": 90,
            }
        )
        api_response.usage = None

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = api_response

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch("app.analyzers.llm_analyzer._set_cached", new_callable=AsyncMock),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0

    @pytest.mark.asyncio
    async def test_analyze_empty_content(self) -> None:
        """Should handle empty response content by parsing empty JSON object."""
        api_response = MagicMock()
        api_response.model = "qwen-plus"
        api_response.choices = [MagicMock()]
        api_response.choices[0].message.content = None  # Triggers fallback to "{}"
        api_response.usage = MagicMock()
        api_response.usage.prompt_tokens = 10
        api_response.usage.completion_tokens = 5
        api_response.usage.total_tokens = 15

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = api_response

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch("app.analyzers.llm_analyzer._set_cached", new_callable=AsyncMock),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.issues == []
        assert result.score == 80  # default when no score in empty dict


# ---------------------------------------------------------------------------
# 13. LLMAnalyzer.analyze - model selection via analyze
# ---------------------------------------------------------------------------


class TestAnalyzeModelSelection:
    """Tests that analyze() routes to the correct model."""

    @pytest.mark.asyncio
    async def test_analyze_uses_light_model_for_small_diff(self) -> None:
        """Small diffs (< 50 lines) should use the light model."""
        api_response = MagicMock()
        api_response.model = "qwen-turbo"
        api_response.choices = [MagicMock()]
        api_response.choices[0].message.content = json.dumps(
            {
                "issues": [],
                "summary": "OK",
                "score": 100,
            }
        )
        api_response.usage = MagicMock()
        api_response.usage.prompt_tokens = 0
        api_response.usage.completion_tokens = 0
        api_response.usage.total_tokens = 0

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = api_response

        analyzer = LLMAnalyzer(api_key="sk-test")

        # A diff with only 1 newline -> 1 line, which is < 50
        small_diff = "+one line"

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch("app.analyzers.llm_analyzer._set_cached", new_callable=AsyncMock),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            await analyzer.analyze(
                code_diff=small_diff,
                file_context="",
                language="python",
                file_path="test.py",
            )

        create_call = mock_client.chat.completions.create.call_args
        assert create_call.kwargs["model"] == analyzer._model_light

    @pytest.mark.asyncio
    async def test_analyze_uses_full_model_for_large_diff(self) -> None:
        """Large diffs (>= 50 lines) should use the full model."""
        api_response = MagicMock()
        api_response.model = "qwen-plus"
        api_response.choices = [MagicMock()]
        api_response.choices[0].message.content = json.dumps(
            {
                "issues": [],
                "summary": "OK",
                "score": 100,
            }
        )
        api_response.usage = MagicMock()
        api_response.usage.prompt_tokens = 0
        api_response.usage.completion_tokens = 0
        api_response.usage.total_tokens = 0

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = api_response

        analyzer = LLMAnalyzer(api_key="sk-test")

        # A diff with 50 newlines (51 lines joined) -> count("\n") == 50, which is >= 50
        large_diff = "\n".join([f"+line {i}" for i in range(51)])

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch("app.analyzers.llm_analyzer._set_cached", new_callable=AsyncMock),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            await analyzer.analyze(
                code_diff=large_diff,
                file_context="",
                language="python",
                file_path="test.py",
            )

        create_call = mock_client.chat.completions.create.call_args
        assert create_call.kwargs["model"] == analyzer._model


# ---------------------------------------------------------------------------
# 14. LLMAnalyzer.analyze - error handling
# ---------------------------------------------------------------------------


class TestAnalyzeErrors:
    """Tests for analyze() error handling paths."""

    @pytest.mark.asyncio
    async def test_analyze_rate_limit_error(self) -> None:
        """RateLimitError should return empty result with rate limit message."""
        from openai import RateLimitError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = RateLimitError(
            message="Rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.issues == []
        assert "rate limit" in result.summary.lower()
        assert result.error != ""

    @pytest.mark.asyncio
    async def test_analyze_timeout_error(self) -> None:
        """APITimeoutError should return empty result with timeout message."""
        from openai import APITimeoutError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(
            request=MagicMock(),
        )

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.issues == []
        assert "timed out" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_analyze_api_error(self) -> None:
        """APIError should return empty result with API error message."""
        from openai import APIError

        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = APIError(
            message="Internal server error",
            request=MagicMock(),
            body=None,
        )

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.issues == []
        assert "API error" in result.summary

    @pytest.mark.asyncio
    async def test_analyze_json_decode_error(self) -> None:
        """JSONDecodeError should return empty result with API error message."""
        api_response = MagicMock()
        api_response.model = "qwen-plus"
        api_response.choices = [MagicMock()]
        api_response.choices[0].message.content = "this is not valid json {{{"
        api_response.usage = MagicMock()
        api_response.usage.prompt_tokens = 0
        api_response.usage.completion_tokens = 0
        api_response.usage.total_tokens = 0

        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = api_response

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.issues == []
        assert "API error" in result.summary

    @pytest.mark.asyncio
    async def test_analyze_unexpected_error(self) -> None:
        """Unexpected exceptions should return empty result with error message."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("Something broke")

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            result = await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        assert result.issues == []
        assert "Unexpected error" in result.summary

    @pytest.mark.asyncio
    async def test_analyze_error_does_not_cache(self) -> None:
        """Failed analysis should not write to cache."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("boom")

        analyzer = LLMAnalyzer(api_key="sk-test")

        with (
            patch("app.analyzers.llm_analyzer._get_cached", return_value=None),
            patch(
                "app.analyzers.llm_analyzer._set_cached",
                new_callable=AsyncMock,
            ) as mock_set,
            patch.object(analyzer, "_get_client", return_value=mock_client),
            patch(_LOGGER),
        ):
            await analyzer.analyze(
                code_diff="diff",
                file_context="",
                language="python",
                file_path="test.py",
            )

        mock_set.assert_not_awaited()
