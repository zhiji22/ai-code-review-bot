"""Integration tests for webhook endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
import pytest_asyncio
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
    async def test_webhook_missing_signature(self, client: AsyncClient, webhook_payload: dict) -> None:
        resp = await client.post(
            "/api/v1/webhook",
            json=webhook_payload,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

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
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_webhook_valid_signature_accepted(
        self,
        client: AsyncClient,
        webhook_payload: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        secret = "test_webhook_secret"
        monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
        payload_bytes = json.dumps(webhook_payload).encode()
        signature = _sign_payload(payload_bytes, secret)

        resp = await client.post(
            "/api/v1/webhook",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": f"delivery-{webhook_payload['repository']['id']}-{webhook_payload['number']}",
            },
        )
        # Should be 202 Accepted (queued) or 409 (duplicate)
        assert resp.status_code in (202, 409)


class TestReviewEndpoints:
    """Tests for review listing endpoints."""

    @pytest.mark.asyncio
    async def test_list_reviews_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/reviews")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_review_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/reviews/99999")
        assert resp.status_code in (401, 404)


class TestStatsEndpoints:
    """Tests for stats endpoints."""

    @pytest.mark.asyncio
    async def test_overview_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/stats/overview")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_trends_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/stats/trends")
        assert resp.status_code == 401


class TestRepositoryEndpoints:
    """Tests for repository endpoints."""

    @pytest.mark.asyncio
    async def test_list_repos_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/repositories")
        assert resp.status_code == 401


class TestRuleEndpoints:
    """Tests for rule endpoints."""

    @pytest.mark.asyncio
    async def test_list_rules_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/rules")
        assert resp.status_code == 401


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
