# Deployment Guide

## Docker Compose (Recommended)

### Production Deployment

1. **Prepare environment**:
```bash
cp .env.example .env
# Edit .env with production values
# IMPORTANT: Set strong secrets, production database credentials
```

2. **SSL certificates** (via Nginx):
```bash
mkdir -p docker/nginx/ssl
# Place your SSL certs:
# docker/nginx/ssl/fullchain.pem
# docker/nginx/ssl/privkey.pem
```

3. **Build and deploy**:
```bash
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

4. **Verify**:
```bash
curl https://your-domain.com/health
```

### Service Architecture

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| nginx | nginx | 80, 443 | SSL termination, reverse proxy, rate limiting |
| backend | backend | 8000 | FastAPI application (4 workers) |
| worker | worker | — | Celery async worker (review pipeline) |
| beat | beat | — | Celery beat scheduler |
| flower | flower | 5555 | Celery monitoring dashboard |
| frontend | frontend | 80 (via nginx) | Static React build |
| postgres | postgres | 5432 | PostgreSQL 16 + pgvector |
| redis | redis | 6379 | Redis 7.2 (4 logical DBs) |
| prometheus | prometheus | 9090 | Metrics collection |
| grafana | grafana | 3001 | Dashboards |

### Redis Logical Databases

| DB | Purpose |
|----|---------|
| 0 | Default (cache, idempotency, budget tracking) |
| 1 | Celery broker |
| 2 | Celery result backend |
| 3 | Reserved for future use |

---

## GitHub App Setup

1. **Create GitHub App**: Settings → Developer settings → GitHub Apps → New GitHub App

2. **Configure permissions**:
   - **Contents**: Read-only
   - **Pull requests**: Read & write
   - **Commit statuses**: Read & write
   - **Checks**: Read & write (optional, for check runs)

3. **Webhook configuration**:
   - URL: `https://your-domain.com/api/v1/webhook`
   - Content type: `application/json`
   - Secret: Generate a strong secret (set as `GITHUB_WEBHOOK_SECRET`)
   - Events: Subscribe to "Pull requests" only

4. **Install app**: Install on target repositories or organizations

5. **Download private key**: Save as `.keys/github-app.pem`

---

## CI/CD Pipeline (GitHub Actions)

### CI Workflow (`.github/workflows/ci.yml`)

Triggers on push/PR to `main` or `develop`:

1. **backend-lint**: ruff check + ruff format check + mypy
2. **backend-test**: pytest with coverage (PostgreSQL + Redis services)
3. **frontend**: TypeScript check + Vite build
4. **docker-build**: Build backend + frontend images (no push)
5. **security-scan**: pip-audit + Trivy filesystem scan

### Deploy Workflow (`.github/workflows/deploy.yml`)

Triggers on push to `main` (path-filtered) or manual dispatch:

1. SSH to production server
2. Transfer source code
3. `docker compose build --no-cache`
4. `alembic upgrade head`
5. `docker compose up -d --remove-orphans`
6. Health check verification

### Required GitHub Secrets

```
SSH_PRIVATE_KEY      # SSH key for deploy server
DEPLOY_HOST          # Deploy server hostname
DEPLOY_USER          # SSH username
DEPLOY_PATH          # Deploy directory path
SLACK_WEBHOOK_URL    # Slack notifications (optional)
```

---

## Backup Strategy

### PostgreSQL

```bash
# Daily full backup (cron)
pg_dump -U review -d review_bot | gzip > backups/postgres_$(date +%Y%m%d).sql.gz

# WAL archiving (continuous)
# Configured in postgresql.conf:
# archive_mode = on
# archive_command = 'test ! -f /backups/wal/%f && cp %p /backups/wal/%f'
```

### Redis

```bash
# AOF persistence (enabled in docker-compose.yml)
appendonly yes
appendfsync everysec

# Periodic RDB snapshot
redis-cli BGSAVE
cp /data/dump.rdb backups/redis_$(date +%Y%m%d).rdb
```

### GDPR Retention (per DESIGN.md §16)

| Data | Retention |
|------|-----------|
| Review records | 180 days |
| Code embeddings | 30 days after repo removal |
| LLM usage logs | 90 days |
| User data | Deletable on request |

---

## Scaling

### Horizontal Scaling

- **Backend**: Scale by adding more `backend` containers behind nginx (already stateless)
- **Workers**: Scale with `docker compose up -d --scale worker=4`
- **PostgreSQL**: Read replicas for dashboard queries

### Vertical Scaling

- **Large PRs**: Tiered strategy (per §16)
  - ≤20 files: Full 3-layer analysis
  - 21-100 files: LLM analyzes top 10 changed files
  - 100+ files: LLM analyzes top 5 critical files only

### Performance Targets

| Metric | Target |
|--------|--------|
| Webhook response time | < 100ms (p99) |
| Review pipeline (per file) | < 10s |
| LLM cache hit rate | > 30% |
| Queue processing | < 5 min for 50-file PR |
