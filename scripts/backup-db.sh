#!/usr/bin/env bash
#
# PostgreSQL backup script
# Usage:
#   ./scripts/backup-db.sh              # one-time backup
#   crontab: 0 2 * * * /app/scripts/backup-db.sh  # daily at 2am
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_DIR}/backups"

# Config
DB_NAME="${POSTGRES_DB:-review_bot}"
DB_USER="${POSTGRES_USER:-review}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"

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

# Timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "==> Backing up database: ${DB_NAME}"
echo "    Output: ${BACKUP_FILE}"

docker compose exec -T postgres pg_dump \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --format=plain \
    --no-owner \
    --no-privileges \
    | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "    Size: ${SIZE}"
echo "==> Backup complete!"

# Cleanup old backups
echo "==> Cleaning up backups older than ${KEEP_DAYS} days..."
find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +"$KEEP_DAYS" -delete 2>/dev/null || true

# List remaining backups
echo "==> Available backups:"
ls -lh "${BACKUP_DIR}/${DB_NAME}_"*.sql.gz 2>/dev/null || echo "    (none)"
