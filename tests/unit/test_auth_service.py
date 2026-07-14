"""Unit tests for AuthService — JWT tokens, GitHub OAuth, user management."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from app.core.config import settings
from app.services.auth_service import AuthService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session() -> AsyncMock:
    """Mock AsyncSession for DB interactions."""
    return AsyncMock()


@pytest.fixture
def auth_service(mock_session: AsyncMock) -> AuthService:
    """AuthService with a mocked session."""
    return AuthService(mock_session)


FAKE_GH_USER: dict[str, Any] = {
    "id": 12345,
    "login": "octocat",
    "email": "octocat@github.com",
    "avatar_url": "https://github.com/images/error/octocat_happy.gif",
    "name": "Monalisa Octocat",
    "bio": "Fake bio",
    "company": "GitHub",
    "location": "San Francisco",
}

FAKE_GH_TOKEN = "ghp_fakeAccessToken123456"


# ---------------------------------------------------------------------------
# 1. JWT: create_access_token
# ---------------------------------------------------------------------------


class TestCreateAccessToken:
    """Tests for AuthService.create_access_token (static method)."""

    def test_creates_valid_jwt_with_correct_payload(self) -> None:
        """Token contains sub, iat, exp, type=access, and is decodable."""
        user_id = 42
        token = AuthService.create_access_token(user_id)

        decoded = jwt.decode(token, settings.secret_key, algorithms=["HS256"])

        assert decoded["sub"] == str(user_id)
        assert decoded["type"] == "access"
        assert "iat" in decoded
        assert "exp" in decoded
        # Expiry should be ~15 minutes from now
        expected_exp = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_expire_minutes)
        actual_exp = datetime.fromtimestamp(decoded["exp"], tz=UTC)
        # Allow 10 seconds of leeway for test execution
        assert abs((expected_exp - actual_exp).total_seconds()) < 10

    def test_with_extra_claims(self) -> None:
        """Extra dict is merged into the JWT payload."""
        user_id = 7
        extra = {"role": "admin", "org_id": 99}
        token = AuthService.create_access_token(user_id, extra=extra)

        decoded = jwt.decode(token, settings.secret_key, algorithms=["HS256"])

        assert decoded["sub"] == str(user_id)
        assert decoded["type"] == "access"
        assert decoded["role"] == "admin"
        assert decoded["org_id"] == 99

    def test_with_extra_none_omits_extra(self) -> None:
        """Passing extra=None (default) does not inject extra keys."""
        token = AuthService.create_access_token(1, extra=None)
        decoded = jwt.decode(token, settings.secret_key, algorithms=["HS256"])

        # Only standard keys should be present
        assert set(decoded.keys()) == {"sub", "iat", "exp", "type"}


# ---------------------------------------------------------------------------
# 2. JWT: create_refresh_token
# ---------------------------------------------------------------------------


class TestCreateRefreshToken:
    """Tests for AuthService.create_refresh_token (static method)."""

    def test_creates_valid_refresh_token(self) -> None:
        """Refresh token has type=refresh and ~7 day expiry."""
        user_id = 99
        token = AuthService.create_refresh_token(user_id)

        decoded = jwt.decode(token, settings.secret_key, algorithms=["HS256"])

        assert decoded["sub"] == str(user_id)
        assert decoded["type"] == "refresh"
        assert "iat" in decoded
        assert "exp" in decoded

        expected_exp = datetime.now(UTC) + timedelta(days=settings.jwt_refresh_expire_days)
        actual_exp = datetime.fromtimestamp(decoded["exp"], tz=UTC)
        assert abs((expected_exp - actual_exp).total_seconds()) < 10


# ---------------------------------------------------------------------------
# 3-5. JWT: decode_token
# ---------------------------------------------------------------------------


class TestDecodeToken:
    """Tests for AuthService.decode_token (static method)."""

    def test_roundtrip_encode_decode(self) -> None:
        """Token created by create_access_token can be decoded losslessly."""
        user_id = 55
        token = AuthService.create_access_token(user_id)
        decoded = AuthService.decode_token(token)

        assert decoded["sub"] == str(user_id)
        assert decoded["type"] == "access"

    def test_expired_token_raises_error(self) -> None:
        """An expired token raises jwt.ExpiredSignatureError."""
        now = datetime.now(UTC)
        payload = {
            "sub": "1",
            "iat": now - timedelta(days=30),
            "exp": now - timedelta(days=29),
            "type": "access",
        }
        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        with pytest.raises(jwt.ExpiredSignatureError):
            AuthService.decode_token(token)

    def test_invalid_token_raises_error(self) -> None:
        """A token signed with a different secret raises an error."""
        payload = {
            "sub": "1",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "type": "access",
        }
        token = jwt.encode(payload, "wrong-secret-key-here-at-least-32c!", algorithm="HS256")

        with pytest.raises(jwt.InvalidSignatureError):
            AuthService.decode_token(token)

    def test_malformed_token_raises_error(self) -> None:
        """Completely invalid string raises jwt.DecodeError / InvalidTokenError."""
        with pytest.raises(jwt.InvalidTokenError):
            AuthService.decode_token("not.a.valid-token-string")


# ---------------------------------------------------------------------------
# 6-9. GitHub OAuth exchange
# ---------------------------------------------------------------------------


class TestGithubOAuthExchange:
    """Tests for AuthService.github_oauth_exchange (async instance method)."""

    @pytest.mark.asyncio
    async def test_success(self, auth_service: AuthService) -> None:
        """Successful OAuth exchange: code -> token -> user info -> upsert."""
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {"access_token": FAKE_GH_TOKEN}
        token_response.raise_for_status = MagicMock()

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = FAKE_GH_USER
        user_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = token_response
        mock_client.get.return_value = user_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_user = MagicMock()
        with patch("app.services.auth_service.httpx.AsyncClient", return_value=mock_client):
            with patch.object(auth_service, "_upsert_user", return_value=mock_user) as mock_upsert:
                result = await auth_service.github_oauth_exchange(
                    code="test_code",
                    state="test_state",
                    redirect_uri="https://example.com/callback",
                )

        assert result["user"] is mock_user
        assert result["github_token"] == FAKE_GH_TOKEN
        assert result["github_data"] == FAKE_GH_USER
        mock_upsert.assert_awaited_once_with(FAKE_GH_USER, FAKE_GH_TOKEN)

    @pytest.mark.asyncio
    async def test_error_response(self, auth_service: AuthService) -> None:
        """GitHub returns an error object in the token response body."""
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "error": "bad_verification_code",
            "error_description": "The code passed is incorrect.",
        }
        token_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = token_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.auth_service.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="bad_verification_code"):
                await auth_service.github_oauth_exchange(
                    code="bad_code", state=None, redirect_uri=None
                )

    @pytest.mark.asyncio
    async def test_no_access_token(self, auth_service: AuthService) -> None:
        """GitHub returns a 200 but the JSON has no access_token key."""
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {"token_type": "bearer"}  # no access_token
        token_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = token_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.auth_service.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="no access_token"):
                await auth_service.github_oauth_exchange(
                    code="test_code", state=None, redirect_uri=None
                )

    @pytest.mark.asyncio
    async def test_network_retry_then_success(self, auth_service: AuthService) -> None:
        """First attempt raises ConnectError, second attempt succeeds."""
        import httpx

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"access_token": FAKE_GH_TOKEN}
        success_response.raise_for_status = MagicMock()

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = FAKE_GH_USER
        user_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        # First post fails, second succeeds
        mock_client.post.side_effect = [
            httpx.ConnectError("connection reset"),
            success_response,
        ]
        mock_client.get.return_value = user_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_user = MagicMock()

        with patch("app.services.auth_service.httpx.AsyncClient", return_value=mock_client):
            with patch("app.services.auth_service.asyncio.sleep", new_callable=AsyncMock):
                with patch.object(auth_service, "_upsert_user", return_value=mock_user):
                    result = await auth_service.github_oauth_exchange(
                        code="test_code", state=None, redirect_uri=None
                    )

        assert result["github_token"] == FAKE_GH_TOKEN
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_network_all_retries_fail(self, auth_service: AuthService) -> None:
        """All 3 retry attempts fail — raises the original connection error."""
        import httpx

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.auth_service.httpx.AsyncClient", return_value=mock_client):
            with patch("app.services.auth_service.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(httpx.ConnectError):
                    await auth_service.github_oauth_exchange(
                        code="test_code", state=None, redirect_uri=None
                    )

        assert mock_client.post.call_count == 3


# ---------------------------------------------------------------------------
# 10-11. _upsert_user
# ---------------------------------------------------------------------------


class TestUpsertUser:
    """Tests for AuthService._upsert_user (async instance method)."""

    @pytest.mark.asyncio
    async def test_creates_new_user(self, auth_service: AuthService) -> None:
        """When no existing user is found, a new User is created and added."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # No existing user
        auth_service.session.execute.return_value = mock_result
        auth_service.session.commit = AsyncMock()
        auth_service.session.refresh = AsyncMock()
        # session.add is synchronous in SQLAlchemy — must be a regular MagicMock
        auth_service.session.add = MagicMock()

        await auth_service._upsert_user(FAKE_GH_USER, FAKE_GH_TOKEN)

        # session.add should have been called with a User object
        auth_service.session.add.assert_called_once()
        added_user = auth_service.session.add.call_args[0][0]
        assert added_user.github_id == FAKE_GH_USER["id"]
        assert added_user.username == FAKE_GH_USER["login"]
        assert added_user.github_access_token == FAKE_GH_TOKEN
        auth_service.session.commit.assert_awaited_once()
        auth_service.session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_user(self, auth_service: AuthService) -> None:
        """When user already exists, fields are updated in-place."""
        existing_user = MagicMock()
        existing_user.username = "old_login"
        existing_user.email = "old@email.com"
        existing_user.avatar_url = "old_url"
        existing_user.name = "Old Name"
        existing_user.bio = "Old bio"
        existing_user.company = "Old Co"
        existing_user.location = "Old Location"
        existing_user.github_access_token = "old_token"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_user
        auth_service.session.execute.return_value = mock_result
        auth_service.session.commit = AsyncMock()
        auth_service.session.refresh = AsyncMock()

        user = await auth_service._upsert_user(FAKE_GH_USER, FAKE_GH_TOKEN)

        assert user is existing_user
        assert user.username == FAKE_GH_USER["login"]
        assert user.github_access_token == FAKE_GH_TOKEN
        assert user.last_login_at is not None
        # session.add should NOT be called for updates
        auth_service.session.add.assert_not_called()
        auth_service.session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 12-13. User helper lookups
# ---------------------------------------------------------------------------


class TestUserLookups:
    """Tests for get_user_by_id and get_user_by_github_id."""

    @pytest.mark.asyncio
    async def test_get_user_by_id_found(self, auth_service: AuthService) -> None:
        """Returns user when found by id."""
        mock_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        auth_service.session.execute.return_value = mock_result

        result = await auth_service.get_user_by_id(42)
        assert result is mock_user

    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self, auth_service: AuthService) -> None:
        """Returns None when user not found by id."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        auth_service.session.execute.return_value = mock_result

        result = await auth_service.get_user_by_id(9999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_by_github_id_found(self, auth_service: AuthService) -> None:
        """Returns user when found by github_id."""
        mock_user = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        auth_service.session.execute.return_value = mock_result

        result = await auth_service.get_user_by_github_id(12345)
        assert result is mock_user

    @pytest.mark.asyncio
    async def test_get_user_by_github_id_not_found(self, auth_service: AuthService) -> None:
        """Returns None when user not found by github_id."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        auth_service.session.execute.return_value = mock_result

        result = await auth_service.get_user_by_github_id(99999)
        assert result is None


# ---------------------------------------------------------------------------
# 14. Guest login
# ---------------------------------------------------------------------------


class TestGuestLogin:
    """Tests for AuthService.guest_login (async instance method)."""

    @pytest.mark.asyncio
    async def test_token_not_configured_raises(
        self,
        auth_service: AuthService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Empty/None GUEST_GITHUB_TOKEN → ValueError (endpoint maps to 400)."""
        monkeypatch.setattr(settings, "guest_github_token", None)
        with pytest.raises(ValueError, match="not configured"):
            await auth_service.guest_login()

    @pytest.mark.asyncio
    async def test_invalid_token_raises_value_error(
        self,
        auth_service: AuthService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GitHub 401 on /user → ValueError with a clear message, NOT HTTPStatusError.

        Regression test: previously an expired/invalid guest PAT let the raw
        ``httpx.HTTPStatusError`` propagate, which the endpoint turned into a
        misleading generic 500 "try again later". It must now surface a
        config-specific ValueError (→ 400) so the admin knows to rotate the token.
        """
        import httpx

        monkeypatch.setattr(settings, "guest_github_token", FAKE_GH_TOKEN)

        # Real 401 Response so raise_for_status() raises a genuine HTTPStatusError.
        request = httpx.Request("GET", "https://api.github.com/user")
        user_response = httpx.Response(status_code=401, request=request)

        mock_client = AsyncMock()
        mock_client.get.return_value = user_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.auth_service.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="invalid or expired"):
                await auth_service.guest_login()

    @pytest.mark.asyncio
    async def test_success(
        self,
        auth_service: AuthService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Valid guest token → user info fetched → user upserted."""
        monkeypatch.setattr(settings, "guest_github_token", FAKE_GH_TOKEN)

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = FAKE_GH_USER
        user_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = user_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_user = MagicMock()
        with patch("app.services.auth_service.httpx.AsyncClient", return_value=mock_client):
            with patch.object(auth_service, "_upsert_user", return_value=mock_user) as mock_upsert:
                result = await auth_service.guest_login()

        assert result["user"] is mock_user
        assert result["github_token"] == FAKE_GH_TOKEN
        assert result["github_data"] == FAKE_GH_USER
        mock_upsert.assert_awaited_once_with(FAKE_GH_USER, FAKE_GH_TOKEN)
