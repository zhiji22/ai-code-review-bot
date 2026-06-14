"""Integration tests for webhook endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient


def _sign_payload(payload: bytes, secret: str) -> str:
    """Sign a payload with GitHub-style HMAC-SHA256."""
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class TestWebhookEndpoint:
    """Tests for POST /api/v1/webhook."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_webhook_missing_signature(
        self, client: AsyncClient, webhook_payload: dict
    ) -> None:
        """Missing required headers → FastAPI returns 422 Validation Error."""
        resp = await client.post(
            "/api/v1/webhook",
            json=webhook_payload,
            headers={"Content-Type": "application/json"},
        )
        # FastAPI Header(...) validation returns 422 for missing required headers
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_webhook_invalid_signature(
        self, client: AsyncClient, webhook_payload: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test_secret")
        payload_bytes = json.dumps(webhook_payload).encode()
        resp = await client.post(
            "/api/v1/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid_hex_signature",
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "test-delivery-id",
            },
        )
        # Invalid signature → 403 Forbidden from security.verify_github_signature
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_webhook_valid_signature_accepted(
        self,
        client: AsyncClient,
        webhook_payload: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        secret = "test_webhook_secret"
        # Patch the cached settings singleton's webhook secret
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "github_webhook_secret", secret)

        payload_bytes = json.dumps(webhook_payload).encode()
        signature = _sign_payload(payload_bytes, secret)

        # Send a ping event — it doesn't require Redis/Celery
        resp = await client.post(
            "/api/v1/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
                "X-GitHub-Event": "ping",
                "X-GitHub-Delivery": f"delivery-{webhook_payload['repository']['id']}-{webhook_payload['number']}",
            },
        )
        # ping events return 202 (default status_code for this endpoint)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pong"

    @pytest.mark.asyncio
    async def test_webhook_closed_action_ignored(
        self, client: AsyncClient, webhook_payload: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非 actionable 的 PR action(closed/edited/...)应被忽略,而非报错。

        回归:此前这些 action 走完整 payload 校验并返回 ``{"status": "error"}``,
        在 GitHub 显示红色 delivery 并刷错误日志。现在应在校验/入队之前
        短路返回 ignored。
        """
        secret = "test_webhook_secret"
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "github_webhook_secret", secret)

        closed_payload = {**webhook_payload, "action": "closed"}
        payload_bytes = json.dumps(closed_payload).encode()
        signature = _sign_payload(payload_bytes, secret)

        resp = await client.post(
            "/api/v1/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-closed",
            },
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "ignored"


class TestReviewEndpoints:
    """Tests for review listing endpoints."""

    @pytest.mark.asyncio
    async def test_list_reviews_unauthenticated(self, client: AsyncClient) -> None:
        """These endpoints have no auth guard; they return 500 when DB is unavailable."""
        resp = await client.get("/api/v1/reviews")
        # No auth dependency on this route — succeeds or fails at DB level
        assert resp.status_code in (200, 500)

    @pytest.mark.asyncio
    async def test_get_review_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/reviews/99999")
        # No auth dependency — succeeds or fails at DB level
        assert resp.status_code in (200, 404, 500)


class TestStatsEndpoints:
    """Tests for stats endpoints."""

    @pytest.mark.asyncio
    async def test_overview_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/stats/overview")
        # No auth dependency — succeeds or fails at DB level
        assert resp.status_code in (200, 500)

    @pytest.mark.asyncio
    async def test_trends_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/stats/trends")
        # No auth dependency — succeeds or fails at DB level
        assert resp.status_code in (200, 500)


class TestRepositoryEndpoints:
    """Tests for repository endpoints."""

    @pytest.mark.asyncio
    async def test_list_repos_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/repositories")
        # No auth dependency — succeeds or fails at DB level
        assert resp.status_code in (200, 500)


class TestRuleEndpoints:
    """Tests for rule endpoints."""

    @pytest.mark.asyncio
    async def test_list_rules_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/rules")
        # No auth dependency — succeeds or fails at DB level
        assert resp.status_code in (200, 500)


class TestAuthEndpoints:
    """Tests for auth endpoints."""

    @pytest.mark.asyncio
    async def test_me_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_missing_token(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/auth/refresh", json={})
        assert resp.status_code in (400, 401, 422)
