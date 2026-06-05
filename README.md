# AI Code Review Bot

> **Automated Pull Request review powered by AST analysis, rule engine, and LLM (GPT-4o).**
>
> Targets: 40% less manual review time, >80% security detection rate, <10s/file review time.

[![CI](https://github.com/your-org/ai-code-review-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/ai-code-review-bot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Features

- **Multi-layer analysis**: AST (tree-sitter) + Rule Engine (24 built-in rules) + LLM (GPT-4o)
- **Real-time PR review**: Triggered via GitHub Webhook, results posted as comments + inline annotations
- **Security-first**: SQL injection, XSS, hardcoded secrets, weak crypto, and 6+ more security checks
- **Performance & style**: N+1 queries, complexity, nesting depth, TODO/FIXME tracking
- **Multi-language**: Python, JavaScript, TypeScript, Java, Go, Rust
- **Smart scoring**: Multi-dimensional (security/performance/maintainability) with confidence-weighted aggregation
- **Budget-aware**: Daily LLM cost limits + per-PR token caps
- **Dashboard**: React frontend with review history, trends, and repository management
- **Enterprise-ready**: pgvector semantic search, Prometheus monitoring, Sentry error tracking, CI/CD

---

## Architecture

```
GitHub PR → Nginx (SSL) → FastAPI → Celery Workers → Pipeline → GitHub API
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                          AST         Rule Engine      LLM
                       (tree-sitter)  (24 rules)   (GPT-4o)
                              └────────────┬────────────┘
                                           ▼
                                   Result Aggregator
                                   (dedup + score)
                                           │
                              ┌────────────┴────────────┐
                              ▼                         ▼
                        PostgreSQL                 Redis Cache
                      (7 tables +                  (4 DBs:
                       pgvector)                   broker/cache/
                                                   idempotency/
                                                   budget)
```

**Tech Stack**:
| Layer | Technology |
|-------|-----------|
| Backend | FastAPI 0.115+, Celery 5.4+, SQLAlchemy 2.0 async |
| Database | PostgreSQL 16 + pgvector 0.7+ |
| Cache/Queue | Redis 7.2+ (4 logical databases) |
| AST | tree-sitter 0.23+ (Python, JS, TS, Java, Go, Rust) |
| LLM | OpenAI GPT-4o (structured JSON output, Redis cache) |
| Frontend | React 18, TypeScript 5, Vite, Tailwind, shadcn/ui |
| Monitoring | Prometheus + Grafana + Sentry |
| Infrastructure | Docker Compose (10 services), Nginx SSL reverse proxy |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose v2+
- GitHub App (for webhook integration)
- OpenAI API key

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/ai-code-review-bot.git
cd ai-code-review-bot
cp .env.example .env
```

Edit `.env` with your credentials:

```env
APP_SECRET=your-32-char-secret-key-here
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY_PATH=/path/to/private-key.pem
GITHUB_WEBHOOK_SECRET=your_webhook_secret
OPENAI_API_KEY=sk-your-openai-key
SENTRY_DSN=https://xxx@sentry.io/xxx  # Optional
```

### 2. Launch with Docker

```bash
# Build and start all services
docker compose up -d --build

# Run database migrations
docker compose exec backend alembic upgrade head

# Check health
curl http://localhost/health
```

**Services exposed**:
| Service | Port | URL |
|---------|------|-----|
| Frontend | 80 | http://localhost |
| API | 80 (via Nginx) | http://localhost/api/v1 |
| API Docs | 80 (debug only) | http://localhost/docs |
| Flower (Celery) | 5555 | http://localhost:5555 |
| Grafana | 3001 | http://localhost:3001 |
| Prometheus | 9090 | http://localhost:9090 |

### 3. GitHub App Setup

1. Go to **GitHub Settings → Developer settings → GitHub Apps → New GitHub App**
2. Set **Webhook URL** to `https://your-domain.com/api/v1/webhook`
3. Set **Webhook secret** (same as `GITHUB_WEBHOOK_SECRET` in `.env`)
4. Subscribe to **Pull request** events
5. Grant permissions: `contents:read`, `pull_requests:write`, `statuses:write`, `checks:write`
6. Generate private key, save as `.keys/github-app.pem`

---

## Development

### Local Setup (without Docker)

```bash
# Backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start PostgreSQL + Redis (or use docker compose up postgres redis)

# Run migrations
alembic upgrade head

# Start API (hot reload)
uvicorn app.main:app --reload --port 8000

# Start Celery worker (separate terminal)
celery -A app.tasks.celery_app worker -l info

# Start Celery beat (separate terminal)
celery -A app.tasks.celery_app beat -l info
```

### Frontend Development

```bash
cd frontend
npm install
npm run dev  # Vite dev server at localhost:5173
```

### Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Integration tests only
pytest tests/integration/

# Frontend tests
cd frontend && npm test
```

### Code Quality

```bash
# Lint
ruff check app/
ruff format --check app/

# Type check
mypy app/

# Pre-commit (runs all checks)
pre-commit run --all-files
```

---

## API Overview

All endpoints under `/api/v1`, responses use `{data, meta}` envelope.

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/webhook` | GitHub webhook receiver | HMAC |
| GET | `/health` | Liveness probe | None |
| GET | `/reviews` | List reviews (paginated) | JWT |
| GET | `/reviews/{id}` | Review detail with comments | JWT |
| POST | `/reviews/{id}/stream` | SSE real-time status | JWT |
| POST | `/reviews` | Manually trigger review | JWT |
| GET | `/repositories` | List active repos | JWT |
| PUT | `/repositories/{id}/settings` | Update repo config | JWT |
| GET | `/rules` | List all rules | JWT |
| POST | `/rules` | Create custom rule | JWT |
| GET | `/stats/overview` | Dashboard overview stats | JWT |
| GET | `/stats/trends` | Review trend data | JWT |
| POST | `/auth/github` | GitHub OAuth login | None |
| GET | `/auth/me` | Current user info | JWT |

Full interactive docs at `/docs` (when `DEBUG=True`).

---

## Scoring Algorithm

```
Overall Score = 0.4 × Security + 0.3 × Performance + 0.3 × Maintainability
```

**Source confidence weights**: Rule=1.0, AST=0.95, LLM=0.75

**Severity penalties**: Critical=10pts, Warning=5pts, Info=1pt (per issue, weighted by confidence)

**LOC tolerance**: Base score reduced by penalty ratio after per-100-LOC tolerance thresholds.

Score is clamped to [0, 100].

---

## Project Structure

```
ai-code-review-bot/
├── app/
│   ├── api/v1/           # REST endpoints (webhook, reviews, repos, rules, stats, auth, sse)
│   ├── core/             # Config, logging, security, DB, Redis, review engine, metrics
│   ├── analyzers/        # AST, rule engine, LLM, result aggregator
│   ├── models/           # SQLAlchemy models (7 tables)
│   ├── schemas/          # Pydantic v2 API schemas
│   ├── services/         # Business logic (GitHub, reviews, repos, rules, stats, auth, budget, embedding)
│   ├── tasks/            # Celery tasks
│   └── utils/
├── frontend/             # React app (Vite + TypeScript + Tailwind + shadcn/ui)
│   └── src/
│       ├── components/   # UI components + Layout
│       ├── pages/        # Dashboard, Reviews, Settings, Rules, Login
│       ├── store/        # Zustand stores (auth, theme)
│       └── lib/          # API client, utilities
├── alembic/              # Database migrations
├── docker/               # Nginx, Prometheus, Grafana configs
├── tests/                # Unit + integration tests
├── .github/workflows/    # CI/CD (test, build, security, deploy)
├── docker-compose.yml    # 10-service stack
├── requirements.txt      # Python dependencies (pinned)
└── DESIGN.md             # Full technical specification
```

---

## Monitoring

- **Prometheus**: Metrics at `/metrics` (webhook latency, review duration, LLM tokens/cost, queue depth)
- **Grafana**: Pre-configured dashboards at `http://localhost:3001`
- **Sentry**: Error tracking + performance monitoring (configured via `SENTRY_DSN`)
- **Flower**: Celery worker monitoring at `http://localhost:5555`
- **Structlog**: JSON structured logging for all services

---

## Security

- HMAC-SHA256 webhook signature verification (constant-time)
- Redis SETNX idempotency for duplicate webhook prevention
- JWT HttpOnly + Secure + SameSite=Strict cookies (15min access / 7d refresh)
- Fernet encryption for stored webhook secrets (BYTEA)
- CORS allowlist, GitHub IP whitelist ready
- HSTS, security headers via Nginx
- Parameterized SQL (SQLAlchemy ORM, no raw queries)
- PII/secret redaction in Sentry events
- Pydantic v2 `extra=forbid` on all input schemas
- Dependabot automated dependency updates + Trivy container scanning

---

## License

MIT — See [LICENSE](LICENSE) for details.
