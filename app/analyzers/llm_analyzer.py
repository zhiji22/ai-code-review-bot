"""LLM Analyzer - OpenAI-powered deep code analysis.

Features:
- Redis cache (key: llm:{sha256(diff)}, TTL 24h)
- Structured JSON output via response_format
- Token usage tracking
- Graceful fallback on errors
- Model routing: gpt-4o-mini for simple, gpt-4o for complex files
"""

from __future__ import annotations

import hashlib
import json
import structlog
from dataclasses import dataclass, field
from typing import Any

from openai import (
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from app.core.config import settings
from app.core.redis import get_redis

logger = structlog.get_logger(__name__)

# --- Models ---


@dataclass
class LLMIssue:
    """A single LLM-detected issue."""

    line_number: int
    line_end: int | None = None
    category: str = ""  # security, performance, maintainability, style
    severity: str = "warning"  # critical, warning, info
    message: str = ""
    suggestion: str = ""
    confidence: float = 0.75  # LLM default confidence


@dataclass
class LLMReviewResult:
    """Full LLM analysis result."""

    issues: list[LLMIssue] = field(default_factory=list)
    summary: str = ""
    score: int = 80  # 0-100
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached: bool = False
    error: str = ""

    @classmethod
    def empty(cls, reason: str = "") -> LLMReviewResult:
        return cls(
            summary=f"LLM analysis unavailable: {reason}" if reason else "", score=80, error=reason
        )


# --- Prompt ---

SYSTEM_PROMPT = """\
你是一名资深代码审查专家。请分析提供的代码 diff，找出真正有价值的、可操作的问题。

重点关注：
1. **安全性**：注入漏洞、硬编码密钥、认证缺陷、不安全操作
2. **性能**：N+1 查询、不必要的内存分配、阻塞 I/O
3. **可维护性**：逻辑不清晰、缺失错误处理、代码异味
4. **代码风格**：命名规范、可读性、死代码

规则：
- 只报告真正的问题，不要吹毛求疵。
- 提供具体的、可直接使用的修改建议。
- 如果代码没有问题，返回空的 issues 列表和高分。
- 严重程度：critical（合并前必须修复）、warning（建议修复）、info（优化建议）。
- 置信度：0.0-1.0，表示你对这是一个真正问题的确定程度。

**重要：所有 message、suggestion、summary 字段必须使用中文回复。**

严格按照指定的 JSON schema 格式返回结果。
"""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer", "minimum": 1},
                    "line_end": {"type": "integer", "minimum": 1},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "security",
                            "performance",
                            "maintainability",
                            "style",
                        ],
                    },
                    "message": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["line", "severity", "category", "message"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["issues", "summary", "score"],
    "additionalProperties": False,
}


# --- Cache helpers ---


def _diff_hash(code_diff: str) -> str:
    """SHA-256 hash of the diff content."""
    return hashlib.sha256(code_diff.encode("utf-8")).hexdigest()


async def _get_cached(key: str) -> dict[str, Any] | None:
    """Try to fetch cached LLM result from Redis."""
    try:
        redis = await get_redis()
        data = await redis.get(f"llm:{key}")
        if data:
            return json.loads(data)  # type: ignore[no-any-return]
    except Exception as e:
        logger.warning("cache_read_error", error=str(e))
    return None


async def _set_cached(key: str, value: dict[str, Any], ttl: int = 86400) -> None:
    """Store LLM result in Redis with TTL (default 24h)."""
    try:
        redis = await get_redis()
        await redis.set(f"llm:{key}", json.dumps(value), ex=ttl)
    except Exception as e:
        logger.warning("cache_write_error", error=str(e))


# --- Analyzer ---


class LLMAnalyzer:
    """LLM-powered code analyzer (OpenAI-compatible API)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> None:
        self._api_key = api_key or settings.openai_api_key
        self._base_url = settings.openai_api_base
        self._model = model or settings.openai_model
        self._model_light = settings.openai_model_light
        self._max_tokens = max_tokens or settings.openai_max_tokens
        self._temperature = temperature if temperature is not None else settings.openai_temperature
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )
        return self._client

    def _select_model(self, diff_lines: int) -> str:
        """Route to light model for simple files, full model for complex."""
        if diff_lines < 50:
            return self._model_light
        return self._model

    async def analyze(
        self,
        code_diff: str,
        file_context: str,
        language: str,
        file_path: str = "",
    ) -> LLMReviewResult:
        """Analyze code diff using LLM with caching.

        Args:
            code_diff: The unified diff of the file
            file_context: Surrounding code context (full file or key sections)
            language: Programming language
            file_path: File path for context

        Returns:
            LLMReviewResult with issues and metadata
        """
        # 1. Check cache
        cache_key = _diff_hash(code_diff)
        cached = await _get_cached(cache_key)
        if cached:
            result = _parse_response(cached)
            result.cached = True
            result.model = cached.get("model", "")
            # Restore token usage so cached files still contribute to cost tracking.
            # _parse_response only reads issues/summary/score, so tokens must be
            # restored here — otherwise `total_tokens == 0` skips the llm_usage record.
            result.prompt_tokens = int(cached.get("prompt_tokens", 0) or 0)
            result.completion_tokens = int(cached.get("completion_tokens", 0) or 0)
            result.total_tokens = int(cached.get("total_tokens", 0) or 0)
            logger.info("llm_cache_hit", file=file_path, key=cache_key[:16])
            return result

        # 2. Build prompt
        user_prompt = _build_user_prompt(code_diff, file_context, language, file_path)

        # 3. Select model based on complexity
        diff_lines = code_diff.count("\n")
        model = self._select_model(diff_lines)

        # 4. Call OpenAI
        client = self._get_client()
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                seed=42,
                response_format={"type": "json_object"},
            )

            # Parse response
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)

            # Add token usage info
            data["model"] = response.model
            data["prompt_tokens"] = response.usage.prompt_tokens if response.usage else 0
            data["completion_tokens"] = response.usage.completion_tokens if response.usage else 0
            data["total_tokens"] = response.usage.total_tokens if response.usage else 0

            # 5. Cache result
            await _set_cached(cache_key, data)

            # 6. Parse into result object
            result = _parse_response(data)
            result.model = response.model
            result.prompt_tokens = data["prompt_tokens"]
            result.completion_tokens = data["completion_tokens"]
            result.total_tokens = data["total_tokens"]

            logger.info(
                "llm_analyze_success",
                file=file_path,
                model=model,
                tokens=result.total_tokens,
                issues=len(result.issues),
            )
            return result

        except RateLimitError as e:
            logger.warning("llm_rate_limited", file=file_path, error=str(e))
            return LLMReviewResult.empty("OpenAI rate limit exceeded")
        except APITimeoutError as e:
            logger.warning("llm_timeout", file=file_path, error=str(e))
            return LLMReviewResult.empty("OpenAI request timed out")
        except (APIError, json.JSONDecodeError) as e:
            logger.error("llm_api_error", file=file_path, error=str(e))
            return LLMReviewResult.empty(f"LLM API error: {e!s}")
        except Exception as e:
            logger.error("llm_unexpected_error", file=file_path, error=str(e))
            return LLMReviewResult.empty(f"Unexpected error: {e!s}")


def _build_user_prompt(
    code_diff: str,
    file_context: str,
    language: str,
    file_path: str,
) -> str:
    """Build the user message for LLM analysis."""
    parts = [
        f"## File: `{file_path}` ({language})",
        "",
        "### Code Diff (review this):",
        "```diff",
        code_diff[:8000],  # Truncate extremely large diffs
        "```",
    ]
    if file_context and file_context != code_diff:
        parts.extend(
            [
                "",
                "### File Context (for reference):",
                "```" + language,
                file_context[:4000],
                "```",
            ]
        )
    parts.extend([
        "",
        "请分析以上 diff 并用中文给出审查意见，严格按照 JSON schema 格式返回。",
    ])
    return "\n".join(parts)


def _parse_response(data: dict[str, Any]) -> LLMReviewResult:
    """Parse LLM JSON response into LLMReviewResult."""
    issues: list[LLMIssue] = []
    for item in data.get("issues", []):
        issues.append(
            LLMIssue(
                line_number=item.get("line", 1),
                line_end=item.get("line_end"),
                category=item.get("category", "maintainability"),
                severity=item.get("severity", "info"),
                message=item.get("message", ""),
                suggestion=item.get("suggestion", ""),
                confidence=item.get("confidence", 0.75),
            )
        )

    return LLMReviewResult(
        issues=issues,
        summary=data.get("summary", ""),
        score=max(0, min(100, data.get("score", 80))),
    )
