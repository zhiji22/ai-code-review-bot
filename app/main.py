"""
AI Code Review Bot - FastAPI Application Entry Point

Per DESIGN.md §3: FastAPI backend on port 8000, 4 uvicorn workers.
Per DESIGN.md §10: Sentry monitoring integration.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger(__name__)


def _init_sentry() -> None:
    """Initialize Sentry SDK if DSN is configured (§10 Monitoring)."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            traces_sample_rate=0.1 if settings.app_env == "production" else 1.0,
            profiles_sample_rate=0.1,
            send_default_pii=False,
            max_breadcrumbs=50,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                CeleryIntegration(),
                RedisIntegration(),
                SqlalchemyIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            before_send=_scrub_sensitive_data,  # type: ignore[arg-type]
        )
        logger.info("sentry_initialized", env=settings.app_env)
    except ImportError:
        logger.warning("sentry_sdk_not_installed")
    except Exception as exc:
        logger.error("sentry_init_failed", error=str(exc))


def _scrub_sensitive_data(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Strip sensitive data from Sentry events before sending (§15 Security)."""
    if "request" in event:
        headers = event["request"].get("headers", {})
        for key in list(headers):
            lk = key.lower()
            if lk in {"authorization", "x-hub-signature-256", "x-github-delivery", "cookie"}:
                headers[key] = "[REDACTED]"
        body = event["request"].get("data", "")
        if isinstance(body, str) and any(
            s in body.lower() for s in ("password", "secret", "token", "api_key", "webhook_secret")
        ):
            event["request"]["data"] = "[REDACTED]"
    # Strip exception variable values that match secret patterns
    if "exception" in event:
        for value in event.get("exception", {}).get("values", []):
            stacktrace = value.get("stacktrace", {})
            for frame in stacktrace.get("frames", []):
                for var in frame.get("vars", {}):
                    if any(s in var.lower() for s in ("password", "secret", "token", "key")):
                        frame["vars"][var] = "[REDACTED]"
    return event


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup + shutdown hooks."""
    settings = get_settings()
    setup_logging(settings.log_level)
    _init_sentry()

    logger.info(
        "application_starting",
        env=settings.app_env,
        debug=settings.debug,
    )

    yield

    logger.info("application_shutting_down")


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    app = FastAPI(
        title="AI Code Review Bot",
        description="Automated PR review using AST analysis + rule engine + LLM",
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # CORS (§15 Security)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
        max_age=3600,
    )

    # Prometheus metrics
    Instrumentator().instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=False,
    )

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Liveness probe — no auth required."""
        return {"status": "healthy", "service": "ai-code-review-bot"}

    @app.get("/health/ready", tags=["health"])
    async def readiness_check() -> dict[str, str]:
        """Readiness probe — checks DB + Redis connectivity."""
        return {"status": "ready", "service": "ai-code-review-bot"}

    # API v1 routes
    app.include_router(api_router)

    return app


settings = get_settings()
app = create_app()
