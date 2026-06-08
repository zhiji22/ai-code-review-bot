#!/usr/bin/env bash
#
# PostgreSQL restore script
# Usage:
#   ./scripts/restore-db.sh                                    # restore latest backup
#   ./scripts/restore-db.sh backups/review_bot_20260608_020000.sql.gz  # restore specific file
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_DIR}/backups"

DB_NAME="${POSTGRES_DB:-review_bot}"
DB_USER="${POSTGRES_USER:-review}"

# Validate identifiers to prevent SQL injection
if [[ ! "$DB_NAME" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
    echo "ERROR: Invalid DB_NAME '${DB_NAME}' — must be a valid PostgreSQL identifier"
    exit 1
fi
if [[ ! "$DB_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
    echo "ERROR: Invalid DB_USER '${DB_USER}' — must be a valid PostgreSQL identifier"
    exit 1
fi

cd "$PROJECT_DIR"

# Determine backup file
if [ $# -ge 1 ]; then
    BACKUP_FILE="$1"
else
    # Find latest backup
    BACKUP_FILE=$(ls -t "${BACKUP_DIR}/${DB_NAME}_"*.sql.gz 2>/dev/null | head -1)
    if [ -z "$BACKUP_FILE" ]; then
        echo "ERROR: No backup files found in ${BACKUP_DIR}/"
        exit 1
    fi
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: File not found: ${BACKUP_FILE}"
    exit 1
fi

echo "==> WARNING: This will DROP and recreate the database: ${DB_NAME}"
echo "    Backup file: ${BACKUP_FILE}"
echo ""
read -p "    Continue? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo "==> Restoring database: ${DB_NAME}"

# Terminate existing connections
docker compose exec -T postgres psql -U "$DB_USER" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();" 2>/dev/null || true

# Drop and recreate
docker compose exec -T postgres psql -U "$DB_USER" -d postgres -c \
    "DROP DATABASE IF EXISTS ${DB_NAME};"
docker compose exec -T postgres psql -U "$DB_USER" -d postgres -c \
    "CREATE DATABASE ${DB_NAME};"

# Restore
gunzip -c "$BACKUP_FILE" | docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" 2>&1 | tail -5

echo "==> Restore complete!"

# Verify
TABLE_COUNT=$(docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" | tr -d ' ')
echo "    Tables restored: ${TABLE_COUNT}"

REVIEW_COUNT=$(docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT count(*) FROM reviews;" 2>/dev/null | tr -d ' ' || echo "0")
echo "    Reviews count: ${REVIEW_COUNT}"
