# API Reference

Base URL: `/api/v1`

All authenticated endpoints require `Authorization: Bearer <jwt_token>` header.

## Response Format

### Success

```json
{
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-01-15T10:30:00Z"
  }
}
```

### Paginated

```json
{
  "data": [ ... ],
  "meta": {
    "pagination": {
      "cursor": "base64_encoded_next_cursor",
      "has_next": true,
      "total": 150
    }
  }
}
```

### Error

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": { "field": "required" }
  },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-01-15T10:30:00Z"
  }
}
```

---

## Webhook

### POST /webhook

GitHub webhook receiver. Verifies HMAC-SHA256 signature, checks idempotency, queues review task.

**Headers required**: `X-Hub-Signature-256`, `X-GitHub-Event`, `X-GitHub-Delivery`

**Response**: `202 Accepted` (review queued) | `409 Conflict` (duplicate) | `401 Unauthorized`

---

## Reviews

### GET /reviews

List review history.

**Query params**: `repository_id`, `status`, `min_score`, `max_score`, `cursor`, `limit` (max 100, default 20)

### GET /reviews/{id}

Get detailed review including comments.

### GET /reviews/{id}/comments

Get paginated comments for a review.

### POST /reviews

Manually trigger a review (requires repo permissions).

```json
{
  "repository_id": 1,
  "pr_number": 42,
  "commit_sha": "abc123"
}
```

### GET /reviews/{id}/stream (SSE)

Server-Sent Events for real-time review status updates.

---

## Repositories

### GET /repositories

List active repositories.

### GET /repositories/{id}

Get repository details.

### PATCH /repositories/{id}

Update repository metadata.

### PUT /repositories/{id}/settings

```json
{
  "auto_review": true,
  "languages": ["python", "javascript"],
  "exclude_patterns": ["*.md", "vendor/"],
  "severity_threshold": "warning",
  "max_files_per_review": 50,
  "enable_llm": true,
  "enable_ast": true,
  "enable_rules": true,
  "custom_rules_only": false
}
```

### DELETE /repositories/{id}

Deactivate repository (soft delete).

---

## Rules

### GET /rules

List rules. **Filters**: `category`, `severity`, `enabled`, `is_builtin`, `repository_id`

### POST /rules

Create custom rule.

```json
{
  "rule_id": "CUSTOM001",
  "name": "No print statements",
  "description": "Prevent print() in production code",
  "category": "style",
  "severity": "warning",
  "pattern": "\\bprint\\s*\\(",
  "message": "Avoid print statements in production",
  "suggestion": "Use logger.info() instead",
  "languages": ["python"]
}
```

### PATCH /rules/{id}

Update rule configuration.

### POST /rules/{id}/toggle

Enable/disable a rule.

### DELETE /rules/{id}

Delete custom rule (builtin rules cannot be deleted).

---

## Stats

### GET /stats/overview

Dashboard summary: total reviews, average scores, issue counts, LLM usage.

### GET /stats/trends

Review trend data (daily). **Params**: `days` (default 30), `repository_id`

### GET /stats/breakdown

Issue counts by category × severity.

---

## Auth

### POST /auth/github

GitHub OAuth login. Accepts `code` + `state` from GitHub OAuth flow.

```json
{
  "code": "github_oauth_code",
  "state": "random_state_token"
}
```

Returns: `{access_token, refresh_token, token_type, user}`

### POST /auth/refresh

Refresh access token using refresh token.

```json
{
  "refresh_token": "your_refresh_token"
}
```

### GET /auth/me

Get current authenticated user.

---

## Rate Limiting

| Endpoint group | Limit | Headers |
|---------------|-------|---------|
| API (general) | 30 req/s | `X-RateLimit-*` |
| Webhook | 10 req/s | `X-RateLimit-*` |
| Health | Unlimited | — |

Rate limit response includes `Retry-After` header.

---

## Error Codes

| Code | Description |
|------|-------------|
| `VALIDATION_ERROR` | Request validation failed |
| `AUTH_REQUIRED` | Authentication token missing/invalid |
| `FORBIDDEN` | Insufficient permissions |
| `NOT_FOUND` | Resource not found |
| `CONFLICT` | Duplicate/idempotency conflict |
| `RATE_LIMITED` | Rate limit exceeded |
| `BUDGET_EXCEEDED` | Daily LLM budget exceeded |
| `INTERNAL_ERROR` | Unexpected server error |
| `GITHUB_API_ERROR` | GitHub API call failed |
| `LLM_ERROR` | LLM analysis failed |
