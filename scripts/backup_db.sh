#!/usr/bin/env bash
# =============================================================================
# Stage0 Bot — PostgreSQL Backup Script
# =============================================================================
# Creates a timestamped pg_dump backup with rotation.
#
# Usage:
#   ./scripts/backup_db.sh                        # uses .env defaults
#   DATABASE_URL=... BACKUP_DIR=/mnt/backups ./scripts/backup_db.sh
#
# Cron example (daily at 03:00, keep 30 days):
#   0 3 * * * cd /opt/stage0_bot && ./scripts/backup_db.sh >> /var/log/stage0_backup.log 2>&1
#
# Environment variables:
#   DATABASE_URL     — full postgres:// connection string (required)
#   BACKUP_DIR       — directory for dumps (default: ./backups)
#   BACKUP_RETAIN_DAYS — delete dumps older than N days (default: 30)
#   BACKUP_FORMAT    — pg_dump format: custom|plain|directory (default: custom)
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env if present (don't fail if missing)
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
BACKUP_RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-30}"
BACKUP_FORMAT="${BACKUP_FORMAT:-custom}"

# ---------------------------------------------------------------------------
# Derived values
# ---------------------------------------------------------------------------
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
HOSTNAME="$(hostname -s 2>/dev/null || echo "local")"

case "$BACKUP_FORMAT" in
    custom)    EXT="dump" ;;
    plain)     EXT="sql"  ;;
    directory) EXT="dir"  ;;
    *)         echo "ERROR: Unknown BACKUP_FORMAT=$BACKUP_FORMAT"; exit 1 ;;
esac

BACKUP_FILE="$BACKUP_DIR/stage0_${HOSTNAME}_${TIMESTAMP}.${EXT}"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
mkdir -p "$BACKUP_DIR"

if ! command -v pg_dump &>/dev/null; then
    echo "ERROR: pg_dump not found. Install postgresql-client."
    exit 1
fi

echo "=== Stage0 DB Backup ==="
echo "Time:      $(date -Iseconds)"
echo "Target:    $BACKUP_FILE"
echo "Retain:    ${BACKUP_RETAIN_DAYS} days"
echo "Format:    $BACKUP_FORMAT"

# ---------------------------------------------------------------------------
# Dump
# ---------------------------------------------------------------------------
START_TIME=$(date +%s)

pg_dump "$DATABASE_URL" \
    --format="$BACKUP_FORMAT" \
    --no-owner \
    --no-privileges \
    --verbose \
    --file="$BACKUP_FILE" \
    2>&1 | while IFS= read -r line; do echo "  pg_dump: $line"; done

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Verify the backup file exists and has content
if [ "$BACKUP_FORMAT" = "directory" ]; then
    if [ ! -d "$BACKUP_FILE" ]; then
        echo "ERROR: Backup directory was not created"
        exit 1
    fi
else
    if [ ! -s "$BACKUP_FILE" ]; then
        echo "ERROR: Backup file is empty or missing"
        exit 1
    fi
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "Size:      $SIZE"
fi

echo "Duration:  ${DURATION}s"
echo "Status:    OK"

# ---------------------------------------------------------------------------
# Rotation — delete old backups
# ---------------------------------------------------------------------------
if [ "$BACKUP_RETAIN_DAYS" -gt 0 ]; then
    DELETED=$(find "$BACKUP_DIR" -name "stage0_*" -type f -mtime "+${BACKUP_RETAIN_DAYS}" -delete -print | wc -l)
    # Also clean up directory-format backups
    DELETED_DIRS=$(find "$BACKUP_DIR" -name "stage0_*" -type d -mtime "+${BACKUP_RETAIN_DAYS}" -exec rm -rf {} + -print 2>/dev/null | wc -l)
    TOTAL_DELETED=$((DELETED + DELETED_DIRS))
    if [ "$TOTAL_DELETED" -gt 0 ]; then
        echo "Rotated:   $TOTAL_DELETED old backup(s) deleted (>${BACKUP_RETAIN_DAYS} days)"
    fi
fi

echo "=== Backup complete ==="
