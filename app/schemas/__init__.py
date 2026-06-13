"""Pydantic v2 schemas package."""

from app.schemas.common import (
    ApiResponse,
    CursorPaginationMeta,
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
)
from app.schemas.repositories import (
    RepositoryListSchema,
    RepositorySchema,
    RepositorySettingsSchema,
    RepositoryUpdateSchema,
)
from app.schemas.reviews import (
    ReviewCreateSchema,
    ReviewFiltersSchema,
    ReviewListSchema,
    ReviewSchema,
)
from app.schemas.rules import (
    RuleCreateSchema,
    RuleListSchema,
    RuleSchema,
    RuleUpdateSchema,
)
from app.schemas.stats import (
    CategoryBreakdownSchema,
    OverviewStatsSchema,
    TrendPointSchema,
    TrendStatsSchema,
)
from app.schemas.users import (
    GitHubLoginSchema,
    TokenRefreshSchema,
    TokenSchema,
    UserSchema,
)
from app.schemas.webhook import WebhookPREvent

__all__ = [
    "ApiResponse",
    "CategoryBreakdownSchema",
    "CursorPaginationMeta",
    "ErrorResponse",
    "GitHubLoginSchema",
    "HealthResponse",
    "OverviewStatsSchema",
    "PaginatedResponse",
    "RepositoryListSchema",
    "RepositorySchema",
    "RepositorySettingsSchema",
    "RepositoryUpdateSchema",
    "ReviewCreateSchema",
    "ReviewFiltersSchema",
    "ReviewListSchema",
    "ReviewSchema",
    "RuleCreateSchema",
    "RuleListSchema",
    "RuleSchema",
    "RuleUpdateSchema",
    "TokenRefreshSchema",
    "TokenSchema",
    "TrendPointSchema",
    "TrendStatsSchema",
    "UserSchema",
    "WebhookPREvent",
]
