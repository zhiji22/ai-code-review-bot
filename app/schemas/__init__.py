"""Pydantic v2 schemas package."""

from app.schemas.common import (
    ApiResponse,
    CursorPaginationMeta,
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
)
from app.schemas.reviews import (
    ReviewCreateSchema,
    ReviewFiltersSchema,
    ReviewListSchema,
    ReviewSchema,
)
from app.schemas.repositories import (
    RepositoryListSchema,
    RepositorySchema,
    RepositorySettingsSchema,
    RepositoryUpdateSchema,
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
    "CursorPaginationMeta",
    "ErrorResponse",
    "HealthResponse",
    "PaginatedResponse",
    "ReviewCreateSchema",
    "ReviewFiltersSchema",
    "ReviewListSchema",
    "ReviewSchema",
    "RepositoryListSchema",
    "RepositorySchema",
    "RepositorySettingsSchema",
    "RepositoryUpdateSchema",
    "RuleCreateSchema",
    "RuleListSchema",
    "RuleSchema",
    "RuleUpdateSchema",
    "CategoryBreakdownSchema",
    "OverviewStatsSchema",
    "TrendPointSchema",
    "TrendStatsSchema",
    "GitHubLoginSchema",
    "TokenRefreshSchema",
    "TokenSchema",
    "UserSchema",
    "WebhookPREvent",
]
