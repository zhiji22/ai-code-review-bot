"""API v1 routes — aggregates all endpoint routers."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.repositories import router as repositories_router
from app.api.v1.reviews import router as reviews_router
from app.api.v1.rules import router as rules_router
from app.api.v1.sse import router as sse_router
from app.api.v1.stats import router as stats_router
from app.api.v1.webhook import router as webhook_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(webhook_router)
api_router.include_router(reviews_router)
api_router.include_router(repositories_router)
api_router.include_router(rules_router)
api_router.include_router(stats_router)
api_router.include_router(auth_router)
api_router.include_router(sse_router)

__all__ = ["api_router"]
