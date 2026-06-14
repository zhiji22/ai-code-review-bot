"""
Webhook event schemas.

Per DESIGN.md §3 + §6: GitHub webhook payload validation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# 会触发审查的 PR webhook action。其余 action(closed/edited/labeled/...)
# 不报错、直接忽略。
ACTIONABLE_PR_ACTIONS: frozenset[str] = frozenset({"opened", "synchronize", "reopened"})


class WebhookRepository(BaseModel):
    """Repository info in webhook payload."""

    id: int
    name: str
    full_name: str
    private: bool = False
    html_url: str = ""


class WebhookUser(BaseModel):
    """User info in webhook payload."""

    login: str
    id: int
    html_url: str = ""


class WebhookPullRequest(BaseModel):
    """Pull request info in webhook payload."""

    id: int
    number: int
    title: str
    body: str | None = None
    state: str
    draft: bool = False
    html_url: str = ""
    head: WebhookPRCommit
    base: WebhookPRCommit
    user: WebhookUser | None = None
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0


class WebhookPRCommit(BaseModel):
    """PR branch/commit reference."""

    ref: str
    sha: str
    label: str = ""


class WebhookPREvent(BaseModel):
    """GitHub pull_request webhook event payload.

    Reference: https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request
    """

    action: str = Field(..., description="opened, synchronize, reopened, closed, edited, etc.")
    number: int
    repository: WebhookRepository
    pull_request: WebhookPullRequest
    sender: WebhookUser | None = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        """Only process actionable events."""
        if v not in ACTIONABLE_PR_ACTIONS:
            raise ValueError(f"Action '{v}' is not actionable for review")
        return v


class WebhookPingEvent(BaseModel):
    """GitHub ping webhook event."""

    zen: str
    hook_id: int
    repository: WebhookRepository | None = None
