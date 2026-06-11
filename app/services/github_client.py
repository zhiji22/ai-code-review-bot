"""GitHub API client wrapper.

Provides async-friendly access to PR diffs, file contents, and comment posting.
Uses httpx for async operations with GitHub App authentication.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jwt
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class FileDiff:
    """Represents a single file's diff in a PR."""

    file_path: str
    status: str  # added, modified, removed, renamed
    additions: int
    deletions: int
    raw_patch: str  # unified diff patch text
    content: str = ""  # full file content (fetched separately if needed)
    language: str = ""  # detected programming language

    @property
    def is_code_file(self) -> bool:
        """Check if this file is a supported code file."""
        CODE_EXTENSIONS = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".cxx": "cpp",
            ".h": "cpp",
            ".hpp": "cpp",
        }
        from pathlib import Path

        ext = Path(self.file_path).suffix.lower()
        return ext in CODE_EXTENSIONS

    @property
    def lines_of_code(self) -> int:
        """Count added lines (approximation for review scope)."""
        return self.additions


@dataclass
class PRInfo:
    """Basic PR metadata."""

    number: int
    title: str
    body: str
    head_sha: str
    base_sha: str
    author: str
    additions: int
    deletions: int
    changed_files: int


def _get_proxy_url() -> str | None:
    """Return the proxy URL from environment variables, if configured.

    Supports HTTPS_PROXY, HTTP_PROXY (lowercase variants also checked).
    NO_PROXY is handled by httpx at the transport level.
    """
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
    )


def _build_github_client(
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> httpx.AsyncClient:
    """Build an httpx client pre-configured for the GitHub API with proxy support."""
    kwargs: dict[str, Any] = {
        "base_url": "https://api.github.com",
        "headers": headers or {},
        "timeout": timeout,
    }
    proxy_url = _get_proxy_url()
    if proxy_url:
        kwargs["proxy"] = proxy_url
        logger.debug("github_client_using_proxy", proxy=proxy_url)
    return httpx.AsyncClient(**kwargs)


class GitHubClient:
    """Async-compatible GitHub API client.

    Uses PyGithub for GitHub App auth + httpx for async API calls.
    """

    def __init__(
        self,
        token: str | None = None,
        installation_id: int | None = None,
    ):
        self._token = token
        self._installation_id = installation_id
        self._http: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazily init httpx client."""
        if self._http is None:
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if self._token:
                headers["Authorization"] = f"token {self._token}"
            self._http = _build_github_client(headers=headers)
        return self._http

    async def get_pr_info(
        self, repo_full_name: str, pr_number: int
    ) -> PRInfo:
        """Fetch PR metadata."""
        client = await self._ensure_client()
        resp = await client.get(
            f"/repos/{repo_full_name}/pulls/{pr_number}"
        )
        resp.raise_for_status()
        data = resp.json()
        return PRInfo(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            head_sha=data["head"]["sha"],
            base_sha=data["base"]["sha"],
            author=data["user"]["login"],
            additions=data["additions"],
            deletions=data["deletions"],
            changed_files=data["changed_files"],
        )

    async def get_pr_files(
        self, repo_full_name: str, pr_number: int
    ) -> list[FileDiff]:
        """Fetch all changed files in a PR with diffs."""
        client = await self._ensure_client()
        files: list[FileDiff] = []
        page = 1
        per_page = 100

        while True:
            resp = await client.get(
                f"/repos/{repo_full_name}/pulls/{pr_number}/files",
                params={"page": page, "per_page": per_page},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break

            for item in data:
                fd = FileDiff(
                    file_path=item["filename"],
                    status=item["status"],
                    additions=item.get("additions", 0),
                    deletions=item.get("deletions", 0),
                    raw_patch=item.get("patch", ""),
                )
                fd.language = _detect_language(fd.file_path)
                files.append(fd)

            if len(data) < per_page:
                break
            page += 1

        return files

    async def get_file_content(
        self, repo_full_name: str, file_path: str, ref: str
    ) -> str:
        """Fetch raw file content at a specific ref."""
        client = await self._ensure_client()
        resp = await client.get(
            f"/repos/{repo_full_name}/contents/{file_path}",
            params={"ref": ref},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return data.get("content", "")

    async def post_review_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Post a general PR review comment (not line-level)."""
        client = await self._ensure_client()
        resp = await client.post(
            f"/repos/{repo_full_name}/issues/{pr_number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()

    async def post_inline_comments(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        comments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Post a review with inline line-level comments.

        Each comment dict should have:
        - path: file path
        - line: line number (or line_end with multi_line)
        - body: comment text
        - side: "RIGHT" (default)
        """
        client = await self._ensure_client()
        payload: dict[str, Any] = {
            "commit_id": commit_sha,
            "event": "COMMENT",
            "comments": comments,
        }
        resp = await client.post(
            f"/repos/{repo_full_name}/pulls/{pr_number}/reviews",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def update_review_status(
        self,
        repo_full_name: str,
        pr_sha: str,
        state: str,  # success, failure, pending, error
        context: str | None = None,
        description: str = "",
        target_url: str | None = None,
    ) -> dict[str, Any]:
        """Update commit status check."""
        client = await self._ensure_client()
        payload: dict[str, Any] = {
            "state": state,
            "context": context or settings.github_status_context,
            "description": description[:140],  # GitHub limit
        }
        if target_url:
            payload["target_url"] = target_url
        resp = await client.post(
            f"/repos/{repo_full_name}/statuses/{pr_sha}",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def check_rate_limit(self) -> dict[str, int]:
        """Check current GitHub API rate limit."""
        client = await self._ensure_client()
        resp = await client.get("/rate_limit")
        resp.raise_for_status()
        core = resp.json()["resources"]["core"]
        return {
            "limit": core["limit"],
            "remaining": core["remaining"],
            "reset": core["reset"],
        }

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None


def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    from pathlib import Path

    LANG_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".h": "cpp",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
    }
    ext = Path(file_path).suffix.lower()
    return LANG_MAP.get(ext, "unknown")


# --- GitHub App Authentication ---

_cached_private_key: str | None = None
_token_cache: dict[int, tuple[str, float]] = {}
_APP_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _read_private_key() -> str:
    """Read and cache the GitHub App private key."""
    global _cached_private_key
    if _cached_private_key is None:
        key_path = Path(settings.github_app_private_key_path)
        if not key_path.exists():
            raise FileNotFoundError(
                f"GitHub App private key not found at: {key_path} "
                f"(resolved from GITHUB_APP_PRIVATE_KEY_PATH={settings.github_app_private_key_path!r})"
            )
        _cached_private_key = key_path.read_text()
    return _cached_private_key


def _generate_jwt() -> str:
    """Generate a JWT for GitHub App authentication."""
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, _read_private_key(), algorithm="RS256")


async def _get_installation_token(installation_id: int) -> str:
    """Exchange a GitHub App JWT for an installation access token (cached)."""
    cached = _token_cache.get(installation_id)
    if cached and cached[1] > time.time() - 300:
        return cached[0]

    app_jwt = _generate_jwt()
    async with _build_github_client(
        headers={**_APP_HEADERS, "Authorization": f"Bearer {app_jwt}"},
    ) as client:
        resp = await client.post(
            f"/app/installations/{installation_id}/access_tokens"
        )
        resp.raise_for_status()
        token = resp.json()["token"]

    _token_cache[installation_id] = (token, time.time())
    return token


async def _list_installations() -> list[dict[str, Any]]:
    """List all installations of the GitHub App."""
    app_jwt = _generate_jwt()
    async with _build_github_client(
        headers={**_APP_HEADERS, "Authorization": f"Bearer {app_jwt}"},
    ) as client:
        resp = await client.get("/app/installations")
        resp.raise_for_status()
        return resp.json()


async def get_github_client(installation_id: int | None = None) -> GitHubClient:
    """Create a GitHub client for a given installation.

    If installation_id is provided, uses GitHub App auth to get an
    installation token. Falls back to GITHUB_TOKEN env var for dev.
    """
    if installation_id:
        token = await _get_installation_token(installation_id)
        return GitHubClient(token=token, installation_id=installation_id)

    if settings.github_token:
        return GitHubClient(token=settings.github_token)

    logger.warning("no_installation_id_falling_back_to_first")
    installations = await _list_installations()
    if installations:
        inst = installations[0]
        token = await _get_installation_token(inst["id"])
        return GitHubClient(token=token, installation_id=inst["id"])

    return GitHubClient()
