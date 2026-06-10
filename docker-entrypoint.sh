#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
# Docker Entrypoint — run migrations, then exec CMD
# ─────────────────────────────────────────────

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    echo "[entrypoint] Running database migrations..."
    MAX_RETRIES=5
    for i in $(seq 1 "$MAX_RETRIES"); do
        if alembic upgrade head; then
            echo "[entrypoint] Migrations complete."
            break
        fi
        echo "[entrypoint] Migration attempt $i failed, retrying in ${i}s..."
        sleep "$i"
        if [ "$i" -eq "$MAX_RETRIES" ]; then
            echo "[entrypoint] FATAL: Database migrations failed after $MAX_RETRIES attempts"
            exit 1
        fi
    done
fi

echo "[entrypoint] Starting: $*"
exec "$@"
