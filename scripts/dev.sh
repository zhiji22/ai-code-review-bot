#!/usr/bin/env bash
set -euo pipefail

# Development startup script
# Usage: ./scripts/dev.sh [backend|frontend|all]

MODE="${1:-all}"

echo "🚀 Starting AI Code Review Bot (mode: $MODE)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

case "$MODE" in
  backend)
    echo "Starting backend services (PostgreSQL + Redis + FastAPI)..."
    docker compose up -d postgres redis
    sleep 3
    echo "Running migrations..."
    alembic upgrade head
    echo "Starting FastAPI dev server..."
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --workers 1
    ;;
  frontend)
    echo "Starting frontend dev server..."
    cd frontend && npm run dev
    ;;
  worker)
    echo "Starting Celery worker..."
    celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
    ;;
  all)
    echo "Starting all services with Docker Compose..."
    docker compose up -d
    echo ""
    echo "✅ Services running:"
    echo "   Backend:    http://localhost:8000"
    echo "   Frontend:   http://localhost"
    echo "   Flower:     http://localhost:5555"
    echo "   Grafana:    http://localhost:3001"
    echo "   Prometheus: http://localhost:9091"
    echo ""
    echo "View logs: docker compose logs -f"
    ;;
  *)
    echo "Usage: $0 {backend|frontend|worker|all}"
    exit 1
    ;;
esac
