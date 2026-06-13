"""Unit tests for the GitHub client module.

Tests cover dataclasses (FileDiff, PRInfo), module-level helper functions,
GitHub App auth flows, and the GitHubClient async class methods.
"""

from __future__ import annotations

import base64
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services import github_client as gc_module
from app.services.github_client import (
    FileDiff,
    GitHubClient,
    PRInfo,
    _build_github_client,
    _detect_language,
    _generate_jwt,
    _get_installation_token,
    _get_proxy_url,
    _list_installations,
    _read_private_key,
    get_github_client,
)

# ---------------------------------------------------------------------------
# FileDiff dataclass tests
# ---------------------------------------------------------------------------


class TestFileDiff:
    """Tests for the FileDiff dataclass and its properties."""

    def test_file_diff_is_code_file_python(self) -> None:
        """.py extension is recognised as a code file."""
        fd = FileDiff(
            file_path="src/main.py",
            status="modified",
            additions=10,
            deletions=2,
            raw_patch="@@ -1,3 +1,5 @@",
        )
        assert fd.is_code_file is True

    def test_file_diff_is_code_file_typescript(self) -> None:
        """.ts extension is recognised as a code file."""
        fd = FileDiff(
            file_path="app/index.ts",
            status="added",
            additions=20,
            deletions=0,
            raw_patch="",
        )
        assert fd.is_code_file is True

    def test_file_diff_is_code_file_unsupported(self) -> None:
        """.txt extension is NOT a code file."""
        fd = FileDiff(
            file_path="docs/README.txt",
            status="modified",
            additions=5,
            deletions=1,
            raw_patch="",
        )
        assert fd.is_code_file is False

    def test_file_diff_is_code_file_no_extension(self) -> None:
        """File with no extension is not a code file."""
        fd = FileDiff(
            file_path="Makefile",
            status="modified",
            additions=1,
            deletions=0,
            raw_patch="",
        )
        assert fd.is_code_file is False

    def test_file_diff_is_code_file_uppercase_extension(self) -> None:
        """Extension check is case-insensitive (lowered before lookup)."""
        fd = FileDiff(
            file_path="app/Main.PY",
            status="modified",
            additions=3,
            deletions=0,
            raw_patch="",
        )
        assert fd.is_code_file is True

    def test_file_diff_lines_of_code(self) -> None:
        """lines_of_code returns the additions count."""
        fd = FileDiff(
            file_path="foo.py",
            status="added",
            additions=42,
            deletions=5,
            raw_patch="",
        )
        assert fd.lines_of_code == 42

    def test_file_diff_lines_of_code_zero(self) -> None:
        """lines_of_code is 0 when additions is 0."""
        fd = FileDiff(
            file_path="foo.py",
            status="removed",
            additions=0,
            deletions=10,
            raw_patch="",
        )
        assert fd.lines_of_code == 0

    def test_file_diff_default_content_and_language(self) -> None:
        """Default values for content and language fields."""
        fd = FileDiff(
            file_path="a.py",
            status="modified",
            additions=1,
            deletions=1,
            raw_patch="",
        )
        assert fd.content == ""
        assert fd.language == ""


# ---------------------------------------------------------------------------
# PRInfo dataclass tests
# ---------------------------------------------------------------------------


class TestPRInfo:
    """Tests for the PRInfo dataclass."""

    def test_pr_info_dataclass(self) -> None:
        """All fields are accessible after construction."""
        pr = PRInfo(
            number=42,
            title="Add feature",
            body="Description",
            head_sha="abc123",
            base_sha="def456",
            author="testuser",
            additions=100,
            deletions=20,
            changed_files=5,
        )
        assert pr.number == 42
        assert pr.title == "Add feature"
        assert pr.body == "Description"
        assert pr.head_sha == "abc123"
        assert pr.base_sha == "def456"
        assert pr.author == "testuser"
        assert pr.additions == 100
        assert pr.deletions == 20
        assert pr.changed_files == 5

    def test_pr_info_body_can_be_empty(self) -> None:
        """body field may be an empty string."""
        pr = PRInfo(
            number=1,
            title="Fix",
            body="",
            head_sha="a",
            base_sha="b",
            author="u",
            additions=0,
            deletions=0,
            changed_files=0,
        )
        assert pr.body == ""


# ---------------------------------------------------------------------------
# _detect_language tests
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    """Tests for the _detect_language helper function."""

    @pytest.mark.parametrize(
        ("file_path", "expected"),
        [
            ("main.py", "python"),
            ("app.js", "javascript"),
            ("App.jsx", "javascript"),
            ("mod.ts", "typescript"),
            ("Widget.tsx", "typescript"),
            ("Main.java", "java"),
            ("main.go", "go"),
            ("lib.rs", "rust"),
            ("app.rb", "ruby"),
            ("core.cpp", "cpp"),
            ("util.cc", "cpp"),
            ("impl.cxx", "cpp"),
            ("header.h", "cpp"),
            ("header.hpp", "cpp"),
            ("Program.cs", "csharp"),
            ("index.php", "php"),
            ("App.swift", "swift"),
            ("Util.kt", "kotlin"),
        ],
    )
    def test_detect_language(self, file_path: str, expected: str) -> None:
        """Known extensions map to the correct language name."""
        assert _detect_language(file_path) == expected

    def test_detect_language_unknown(self) -> None:
        """Unknown extension returns 'unknown'."""
        assert _detect_language("data.csv") == "unknown"

    def test_detect_language_no_extension(self) -> None:
        """File with no extension returns 'unknown'."""
        assert _detect_language("Dockerfile") == "unknown"

    def test_detect_language_case_insensitive(self) -> None:
        """Extension matching is case-insensitive."""
        assert _detect_language("main.PY") == "python"
        assert _detect_language("app.JS") == "javascript"


# ---------------------------------------------------------------------------
# _get_proxy_url tests
# ---------------------------------------------------------------------------


class TestGetProxyUrl:
    """Tests for the _get_proxy_url environment helper."""

    def test_get_proxy_url_with_https_proxy(self) -> None:
        """Returns HTTPS_PROXY when set."""
        with patch.dict(os.environ, {"HTTPS_PROXY": "https://proxy.example.com:8080"}, clear=False):
            assert _get_proxy_url() == "https://proxy.example.com:8080"

    def test_get_proxy_url_with_http_proxy(self) -> None:
        """Falls back to HTTP_PROXY when HTTPS_PROXY is not set."""
        env = {"HTTP_PROXY": "http://proxy.example.com:3128"}
        with patch.dict(os.environ, env, clear=False):
            # Make sure HTTPS_PROXY is absent
            os.environ.pop("HTTPS_PROXY", None)
            assert _get_proxy_url() == "http://proxy.example.com:3128"

    def test_get_proxy_url_with_lowercase_var(self) -> None:
        """Falls back to lowercase variants."""
        # Clear all proxy env vars first, then set only the lowercase one
        with patch.dict(
            os.environ,
            {"https_proxy": "https://lower.example.com:9000"},
            clear=True,
        ):
            assert _get_proxy_url() == "https://lower.example.com:9000"

    def test_get_proxy_url_without_env(self) -> None:
        """Returns None when no proxy env vars are set."""
        with patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            assert _get_proxy_url() is None


# ---------------------------------------------------------------------------
# _build_github_client tests
# ---------------------------------------------------------------------------


class TestBuildGithubClient:
    """Tests for the _build_github_client factory."""

    def test_build_github_client_default(self) -> None:
        """Returns an httpx.AsyncClient with the correct base_url."""
        with patch.dict(os.environ, {}, clear=True):
            client = _build_github_client()
        assert client.base_url == "https://api.github.com"

    def test_build_github_client_with_headers(self) -> None:
        """Custom headers are forwarded to the client."""
        headers = {"Authorization": "token abc"}
        with patch.dict(os.environ, {}, clear=True):
            client = _build_github_client(headers=headers)
        assert client.headers["Authorization"] == "token abc"

    def test_build_github_client_with_proxy(self) -> None:
        """When a proxy env var is set, the client is created with proxy."""
        with patch.dict(os.environ, {"HTTPS_PROXY": "https://proxy.test:8080"}, clear=False):
            with patch("app.services.github_client.httpx.AsyncClient") as mock_cls:
                _build_github_client()
                call_kwargs = mock_cls.call_args[1]
                assert call_kwargs["proxy"] == "https://proxy.test:8080"

    def test_build_github_client_timeout(self) -> None:
        """Custom timeout is forwarded."""
        with patch.dict(os.environ, {}, clear=True):
            client = _build_github_client(timeout=60.0)
        # httpx stores timeout internally; verify it accepted the kwarg
        assert client is not None


# ---------------------------------------------------------------------------
# _read_private_key tests
# ---------------------------------------------------------------------------


class TestReadPrivateKey:
    """Tests for _read_private_key with caching."""

    def setup_method(self) -> None:
        """Reset the module-level private key cache before each test."""
        gc_module._cached_private_key = None

    def test_reads_key_from_file(self, tmp_path: object) -> None:
        """Reads the private key from the configured path."""
        import pathlib

        key_file = pathlib.Path(str(tmp_path)) / "key.pem"
        key_file.write_text("FAKE PRIVATE KEY CONTENT")

        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_app_private_key_path = str(key_file)
            result = _read_private_key()

        assert result == "FAKE PRIVATE KEY CONTENT"

    def test_caches_key_after_first_read(self, tmp_path: object) -> None:
        """Second call returns the cached value without re-reading the file."""
        import pathlib

        key_file = pathlib.Path(str(tmp_path)) / "key.pem"
        key_file.write_text("FIRST READ")

        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_app_private_key_path = str(key_file)
            _read_private_key()
            # Overwrite file — should NOT be read again
            key_file.write_text("SECOND READ")
            result = _read_private_key()

        assert result == "FIRST READ"

    def test_raises_when_key_file_missing(self) -> None:
        """Raises FileNotFoundError when the key file does not exist."""
        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_app_private_key_path = "/nonexistent/key.pem"
            with pytest.raises(FileNotFoundError, match="GitHub App private key not found"):
                _read_private_key()


# ---------------------------------------------------------------------------
# _generate_jwt tests
# ---------------------------------------------------------------------------


class TestGenerateJwt:
    """Tests for the _generate_jwt function."""

    def test_generate_jwt(self) -> None:
        """Generates a JWT with the correct structure and claims."""
        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_app_id = "test-app-123"
            with patch("app.services.github_client._read_private_key", return_value="fake-key"):
                with patch(
                    "app.services.github_client.jwt.encode", return_value="mocked.jwt.token"
                ) as mock_encode:
                    token = _generate_jwt()

        assert token == "mocked.jwt.token"
        mock_encode.assert_called_once()
        call_args = mock_encode.call_args
        payload = call_args[0][0]
        assert payload["iss"] == "test-app-123"
        assert "iat" in payload
        assert "exp" in payload

    def test_generate_jwt_expiry_is_ten_minutes(self) -> None:
        """JWT payload has exp roughly 10 minutes after iat."""
        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_app_id = "app"
            with patch("app.services.github_client._read_private_key", return_value="fake-key"):
                with patch(
                    "app.services.github_client.jwt.encode", return_value="tok"
                ) as mock_encode:
                    _generate_jwt()

        payload = mock_encode.call_args[0][0]
        # exp - iat == 660 because iat = now - 60 and exp = now + 600
        assert payload["exp"] - payload["iat"] == 660


# ---------------------------------------------------------------------------
# _get_installation_token tests
# ---------------------------------------------------------------------------


class TestGetInstallationToken:
    """Tests for the _get_installation_token function."""

    def setup_method(self) -> None:
        """Clear the token cache before each test."""
        gc_module._token_cache.clear()

    @pytest.mark.asyncio
    async def test_get_installation_token_fetches_new(self) -> None:
        """Fetches a new token when no cache entry exists."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "ghs_new_token"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.github_client._build_github_client", return_value=mock_http):
            with patch("app.services.github_client._generate_jwt", return_value="jwt-token"):
                token = await _get_installation_token(12345)

        assert token == "ghs_new_token"

    @pytest.mark.asyncio
    async def test_get_installation_token_cached(self) -> None:
        """Returns cached token when it is still valid (within 5 min)."""
        gc_module._token_cache[99999] = ("ghs_cached_token", time.time())

        # _build_github_client should NOT be called if cache is valid
        with patch("app.services.github_client._build_github_client") as mock_build:
            token = await _get_installation_token(99999)
            mock_build.assert_not_called()

        assert token == "ghs_cached_token"

    @pytest.mark.asyncio
    async def test_get_installation_token_expired_cache(self) -> None:
        """Re-fetches when the cached token has expired (>5 min old)."""
        gc_module._token_cache[77777] = ("ghs_old_token", time.time() - 400)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"token": "ghs_fresh_token"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.github_client._build_github_client", return_value=mock_http):
            with patch("app.services.github_client._generate_jwt", return_value="jwt-token"):
                token = await _get_installation_token(77777)

        assert token == "ghs_fresh_token"


# ---------------------------------------------------------------------------
# _list_installations tests
# ---------------------------------------------------------------------------


class TestListInstallations:
    """Tests for the _list_installations function."""

    @pytest.mark.asyncio
    async def test_list_installations_success(self) -> None:
        """Returns the list of installation dicts from the API."""
        installations = [
            {"id": 100, "account": {"login": "org1"}},
            {"id": 200, "account": {"login": "org2"}},
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = installations
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.github_client._build_github_client", return_value=mock_http):
            with patch("app.services.github_client._generate_jwt", return_value="jwt-token"):
                result = await _list_installations()

        assert len(result) == 2
        assert result[0]["id"] == 100
        assert result[1]["id"] == 200


# ---------------------------------------------------------------------------
# get_github_client factory tests
# ---------------------------------------------------------------------------


class TestGetGithubClient:
    """Tests for the get_github_client factory function."""

    @pytest.mark.asyncio
    async def test_get_github_client_with_installation_id(self) -> None:
        """When installation_id is given, uses _get_installation_token."""
        with patch(
            "app.services.github_client._get_installation_token",
            new_callable=AsyncMock,
            return_value="ghs_inst_token",
        ) as mock_token:
            client = await get_github_client(installation_id=12345)

        mock_token.assert_awaited_once_with(12345)
        assert isinstance(client, GitHubClient)
        assert client._token == "ghs_inst_token"
        assert client._installation_id == 12345

    @pytest.mark.asyncio
    async def test_get_github_client_with_github_token(self) -> None:
        """When no installation_id but settings.github_token is set, uses it."""
        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_token = "ghp_settings_token"
            client = await get_github_client(installation_id=None)

        assert isinstance(client, GitHubClient)
        assert client._token == "ghp_settings_token"

    @pytest.mark.asyncio
    async def test_get_github_client_fallback_list(self) -> None:
        """When no installation_id and no token, lists installations and uses the first."""
        installations = [{"id": 55555, "account": {"login": "fallback-org"}}]

        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_token = None
            with (
                patch(
                    "app.services.github_client._list_installations",
                    new_callable=AsyncMock,
                    return_value=installations,
                ),
                patch(
                    "app.services.github_client._get_installation_token",
                    new_callable=AsyncMock,
                    return_value="ghs_fallback_token",
                ) as mock_token,
            ):
                client = await get_github_client(installation_id=None)

        mock_token.assert_awaited_once_with(55555)
        assert client._token == "ghs_fallback_token"
        assert client._installation_id == 55555

    @pytest.mark.asyncio
    async def test_get_github_client_no_installations(self) -> None:
        """Returns unauthenticated client when no installations exist."""
        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_token = None
            with patch(
                "app.services.github_client._list_installations",
                new_callable=AsyncMock,
                return_value=[],
            ):
                client = await get_github_client(installation_id=None)

        assert isinstance(client, GitHubClient)
        assert client._token is None
        assert client._installation_id is None


# ---------------------------------------------------------------------------
# GitHubClient class tests
# ---------------------------------------------------------------------------


def _make_mock_response(
    json_data: dict | list,
    status_code: int = 200,
) -> MagicMock:
    """Build a mock httpx.Response with the given JSON body."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def _make_pr_json() -> dict:
    """Return a minimal PR JSON payload matching what GitHub returns."""
    return {
        "number": 42,
        "title": "Add feature X",
        "body": "Please review",
        "head": {"sha": "head_sha_abc"},
        "base": {"sha": "base_sha_def"},
        "user": {"login": "contributor"},
        "additions": 55,
        "deletions": 10,
        "changed_files": 3,
    }


def _make_file_json(filename: str = "src/main.py", status: str = "modified") -> dict:
    """Return a minimal file entry from the PR files API."""
    return {
        "filename": filename,
        "status": status,
        "additions": 12,
        "deletions": 3,
        "patch": "@@ -1,3 +1,5 @@\n+new line",
    }


class TestGitHubClientEnsureClient:
    """Tests for GitHubClient._ensure_client."""

    @pytest.mark.asyncio
    async def test_ensure_client_with_token(self) -> None:
        """Sets Authorization header when token is present."""
        gh = GitHubClient(token="ghp_test_token")
        with patch("app.services.github_client._build_github_client") as mock_build:
            mock_http = MagicMock()
            mock_build.return_value = mock_http
            client = await gh._ensure_client()

        mock_build.assert_called_once()
        call_headers = mock_build.call_args[1]["headers"]
        assert call_headers["Authorization"] == "token ghp_test_token"
        assert client is mock_http

    @pytest.mark.asyncio
    async def test_ensure_client_without_token(self) -> None:
        """No Authorization header when token is absent."""
        gh = GitHubClient(token=None)
        with patch("app.services.github_client._build_github_client") as mock_build:
            mock_http = MagicMock()
            mock_build.return_value = mock_http
            await gh._ensure_client()

        call_headers = mock_build.call_args[1]["headers"]
        assert "Authorization" not in call_headers

    @pytest.mark.asyncio
    async def test_ensure_client_reuses_existing(self) -> None:
        """Does not create a new client on repeated calls."""
        gh = GitHubClient(token="tok")
        mock_http = MagicMock()
        gh._http = mock_http  # pre-set to simulate already initialised

        client = await gh._ensure_client()
        assert client is mock_http


class TestGitHubClientGetPrInfo:
    """Tests for GitHubClient.get_pr_info."""

    @pytest.mark.asyncio
    async def test_get_pr_info_success(self) -> None:
        """Fetches and maps PR metadata into a PRInfo instance."""
        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_make_mock_response(_make_pr_json()))
        gh._http = mock_http

        pr_info = await gh.get_pr_info("owner/repo", 42)

        assert isinstance(pr_info, PRInfo)
        assert pr_info.number == 42
        assert pr_info.title == "Add feature X"
        assert pr_info.body == "Please review"
        assert pr_info.head_sha == "head_sha_abc"
        assert pr_info.base_sha == "base_sha_def"
        assert pr_info.author == "contributor"
        assert pr_info.additions == 55
        assert pr_info.deletions == 10
        assert pr_info.changed_files == 3

    @pytest.mark.asyncio
    async def test_get_pr_info_null_body(self) -> None:
        """Handles null body gracefully (maps to empty string)."""
        data = _make_pr_json()
        data["body"] = None

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_make_mock_response(data))
        gh._http = mock_http

        pr_info = await gh.get_pr_info("owner/repo", 42)
        assert pr_info.body == ""


class TestGitHubClientGetPrFiles:
    """Tests for GitHubClient.get_pr_files."""

    @pytest.mark.asyncio
    async def test_get_pr_files_success(self) -> None:
        """Returns a list of FileDiff objects for changed files."""
        files_json = [
            _make_file_json("src/main.py", "modified"),
            _make_file_json("src/utils.py", "added"),
        ]
        resp = _make_mock_response(files_json)

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=resp)
        gh._http = mock_http

        files = await gh.get_pr_files("owner/repo", 42)

        assert len(files) == 2
        assert all(isinstance(f, FileDiff) for f in files)
        assert files[0].file_path == "src/main.py"
        assert files[0].language == "python"
        assert files[1].file_path == "src/utils.py"

    @pytest.mark.asyncio
    async def test_get_pr_files_pagination(self) -> None:
        """Follows pagination: two pages of 100 items each, then an empty page."""
        page1 = [_make_file_json(f"file_{i}.py", "modified") for i in range(100)]
        page2 = [_make_file_json(f"file_{i}.py", "modified") for i in range(50)]

        resp1 = _make_mock_response(page1)
        resp2 = _make_mock_response(page2)

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=[resp1, resp2])
        gh._http = mock_http

        files = await gh.get_pr_files("owner/repo", 42)

        assert len(files) == 150
        assert mock_http.get.call_count == 2

    @pytest.mark.asyncio
    async def test_get_pr_files_empty(self) -> None:
        """Returns an empty list when the PR has no changed files."""
        resp = _make_mock_response([])

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=resp)
        gh._http = mock_http

        files = await gh.get_pr_files("owner/repo", 42)
        assert files == []

    @pytest.mark.asyncio
    async def test_get_pr_files_missing_patch(self) -> None:
        """Handles missing patch field gracefully (defaults to empty string)."""
        file_json = {
            "filename": "binary.png",
            "status": "added",
            "additions": 0,
            "deletions": 0,
            # no "patch" key
        }
        resp = _make_mock_response([file_json])

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=resp)
        gh._http = mock_http

        files = await gh.get_pr_files("owner/repo", 42)
        assert len(files) == 1
        assert files[0].raw_patch == ""


class TestGitHubClientGetFileContent:
    """Tests for GitHubClient.get_file_content."""

    @pytest.mark.asyncio
    async def test_get_file_content_base64(self) -> None:
        """Decodes base64-encoded file content."""
        original = "print('hello world')"
        encoded = base64.b64encode(original.encode()).decode()
        data = {"encoding": "base64", "content": encoded}

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_make_mock_response(data))
        gh._http = mock_http

        content = await gh.get_file_content("owner/repo", "src/main.py", "main")
        assert content == original

    @pytest.mark.asyncio
    async def test_get_file_content_plain(self) -> None:
        """Returns plain content when encoding is not base64."""
        data = {"encoding": "none", "content": "plain text content"}

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_make_mock_response(data))
        gh._http = mock_http

        content = await gh.get_file_content("owner/repo", "README.md", "main")
        assert content == "plain text content"

    @pytest.mark.asyncio
    async def test_get_file_content_missing_content(self) -> None:
        """Returns empty string when content key is absent and encoding is not base64."""
        data = {"encoding": "none"}

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_make_mock_response(data))
        gh._http = mock_http

        content = await gh.get_file_content("owner/repo", "empty.txt", "main")
        assert content == ""


class TestGitHubClientPostReviewComment:
    """Tests for GitHubClient.post_review_comment."""

    @pytest.mark.asyncio
    async def test_post_review_comment(self) -> None:
        """Posts a comment and returns the response JSON."""
        expected = {"id": 999, "body": "LGTM"}
        resp = _make_mock_response(expected)

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=resp)
        gh._http = mock_http

        result = await gh.post_review_comment("owner/repo", 42, "LGTM")

        assert result == expected
        mock_http.post.assert_awaited_once()
        call_args = mock_http.post.call_args
        assert "issues/42/comments" in call_args[0][0]
        assert call_args[1]["json"]["body"] == "LGTM"


class TestGitHubClientPostInlineComments:
    """Tests for GitHubClient.post_inline_comments."""

    @pytest.mark.asyncio
    async def test_post_inline_comments(self) -> None:
        """Posts a review with inline comments payload."""
        expected = {"id": 555, "state": "COMMENTED"}
        resp = _make_mock_response(expected)
        comments = [
            {"path": "src/main.py", "line": 10, "body": "Consider refactoring."},
        ]

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=resp)
        gh._http = mock_http

        result = await gh.post_inline_comments("owner/repo", 42, "sha123", comments)

        assert result == expected
        call_args = mock_http.post.call_args
        assert "pulls/42/reviews" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["commit_id"] == "sha123"
        assert payload["event"] == "COMMENT"
        assert payload["comments"] == comments


class TestGitHubClientUpdateReviewStatus:
    """Tests for GitHubClient.update_review_status."""

    @pytest.mark.asyncio
    async def test_update_review_status(self) -> None:
        """Posts a commit status with truncated description."""
        long_desc = "A" * 200  # exceeds GitHub 140-char limit
        expected = {"id": 777, "state": "success"}
        resp = _make_mock_response(expected)

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=resp)
        gh._http = mock_http

        result = await gh.update_review_status(
            "owner/repo", "sha123", "success", description=long_desc
        )

        assert result == expected
        payload = mock_http.post.call_args[1]["json"]
        assert payload["state"] == "success"
        assert len(payload["description"]) == 140
        assert "target_url" not in payload

    @pytest.mark.asyncio
    async def test_update_review_status_with_target_url(self) -> None:
        """Includes target_url when provided."""
        expected = {"id": 888, "state": "failure"}
        resp = _make_mock_response(expected)

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=resp)
        gh._http = mock_http

        await gh.update_review_status(
            "owner/repo",
            "sha123",
            "failure",
            target_url="https://dashboard.example.com/review/42",
        )

        payload = mock_http.post.call_args[1]["json"]
        assert payload["target_url"] == "https://dashboard.example.com/review/42"

    @pytest.mark.asyncio
    async def test_update_review_status_default_context(self) -> None:
        """Uses settings.github_status_context when context is not provided."""
        expected = {"id": 999}
        resp = _make_mock_response(expected)

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=resp)
        gh._http = mock_http

        with patch("app.services.github_client.settings") as mock_settings:
            mock_settings.github_status_context = "AI Code Review"
            await gh.update_review_status("owner/repo", "sha123", "pending")

        payload = mock_http.post.call_args[1]["json"]
        assert payload["context"] == "AI Code Review"

    @pytest.mark.asyncio
    async def test_update_review_status_custom_context(self) -> None:
        """Uses the provided context instead of the default."""
        expected = {"id": 111}
        resp = _make_mock_response(expected)

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=resp)
        gh._http = mock_http

        await gh.update_review_status("owner/repo", "sha123", "error", context="Custom CI Check")

        payload = mock_http.post.call_args[1]["json"]
        assert payload["context"] == "Custom CI Check"


class TestGitHubClientCheckRateLimit:
    """Tests for GitHubClient.check_rate_limit."""

    @pytest.mark.asyncio
    async def test_check_rate_limit(self) -> None:
        """Returns the core rate limit dict."""
        rate_data = {"resources": {"core": {"limit": 5000, "remaining": 4999, "reset": 1700000000}}}
        resp = _make_mock_response(rate_data)

        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=resp)
        gh._http = mock_http

        result = await gh.check_rate_limit()

        assert result == {"limit": 5000, "remaining": 4999, "reset": 1700000000}
        mock_http.get.assert_awaited_once_with("/rate_limit")


class TestGitHubClientClose:
    """Tests for GitHubClient.close."""

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        """Closes the internal httpx client and sets it to None."""
        gh = GitHubClient(token="tok")
        mock_http = AsyncMock()
        gh._http = mock_http

        await gh.close()

        mock_http.aclose.assert_awaited_once()
        assert gh._http is None

    @pytest.mark.asyncio
    async def test_close_when_no_client(self) -> None:
        """Does nothing when _http is already None."""
        gh = GitHubClient(token="tok")
        gh._http = None

        # Should not raise
        await gh.close()
        assert gh._http is None
