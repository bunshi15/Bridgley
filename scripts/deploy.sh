#!/usr/bin/env bash
# =============================================================================
# Stage0 Bot — Immutable Tag Deploy with Quick Rollback
# =============================================================================
#
# Builds a Docker image with an immutable tag (git SHA + timestamp),
# deploys it, and supports instant rollback to the previous version.
#
# Usage:
#   ./scripts/deploy.sh                  # build + deploy
#   ./scripts/deploy.sh rollback         # rollback to previous version
#   ./scripts/deploy.sh status           # show current and previous versions
#
# Environment variables:
#   IMAGE_NAME       — Docker image name (default: stage0-bot)
#   REGISTRY         — Registry prefix, e.g. ghcr.io/your-org (optional)
#   COMPOSE_FILE     — docker-compose file (default: docker-compose.prod.example.yml)
#   COMPOSE_PROJECT  — compose project name (default: stage0)
#   SKIP_BACKUP      — set to "true" to skip pre-deploy DB backup
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

IMAGE_NAME="${IMAGE_NAME:-stage0-bot}"
REGISTRY="${REGISTRY:-}"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_DIR/docker-compose.prod.example.yml}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-stage0}"
SKIP_BACKUP="${SKIP_BACKUP:-false}"

STATE_DIR="$PROJECT_DIR/.deploy"
CURRENT_TAG_FILE="$STATE_DIR/current_tag"
PREVIOUS_TAG_FILE="$STATE_DIR/previous_tag"

mkdir -p "$STATE_DIR"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo "[deploy] $(date +%H:%M:%S) $*"; }
fail() { log "ERROR: $*"; exit 1; }

get_current_tag() {
    [ -f "$CURRENT_TAG_FILE" ] && cat "$CURRENT_TAG_FILE" || echo ""
}

get_previous_tag() {
    [ -f "$PREVIOUS_TAG_FILE" ] && cat "$PREVIOUS_TAG_FILE" || echo ""
}

full_image() {
    local tag="$1"
    if [ -n "$REGISTRY" ]; then
        echo "$REGISTRY/$IMAGE_NAME:$tag"
    else
        echo "$IMAGE_NAME:$tag"
    fi
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_status() {
    log "=== Deploy Status ==="
    local current
    current=$(get_current_tag)
    local previous
    previous=$(get_previous_tag)
    log "Current:  ${current:-<not deployed>}"
    log "Previous: ${previous:-<none>}"
    log "Image:    $IMAGE_NAME"
    if [ -n "$REGISTRY" ]; then
        log "Registry: $REGISTRY"
    fi
}

cmd_rollback() {
    local previous
    previous=$(get_previous_tag)
    [ -z "$previous" ] && fail "No previous version to rollback to"

    local current
    current=$(get_current_tag)
    log "=== Rolling back ==="
    log "Current:  $current"
    log "Target:   $previous"

    local image
    image=$(full_image "$previous")

    # Update compose to use the previous image
    export STAGE0_IMAGE="$image"
    docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" up -d \
        --no-build --remove-orphans 2>&1 | while IFS= read -r line; do log "  $line"; done

    # Swap tags: current becomes previous, previous becomes current
    echo "$previous" > "$CURRENT_TAG_FILE"
    echo "$current"  > "$PREVIOUS_TAG_FILE"

    log "Rollback complete: now running $previous"
    log "To rollback again (to $current): ./scripts/deploy.sh rollback"
}

cmd_deploy() {
    # Require clean git state for production deploys
    if [ -n "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null)" ]; then
        log "WARNING: Working directory has uncommitted changes"
    fi

    # Build immutable tag: git-SHA_YYYYMMDD_HHMMSS
    local GIT_SHA
    GIT_SHA=$(git -C "$PROJECT_DIR" rev-parse --short=8 HEAD 2>/dev/null || echo "nogit")
    local TIMESTAMP
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    local TAG="${GIT_SHA}_${TIMESTAMP}"
    local IMAGE
    IMAGE=$(full_image "$TAG")

    log "=== Deploying ==="
    log "Tag:      $TAG"
    log "Image:    $IMAGE"

    # Pre-deploy database backup
    if [ "$SKIP_BACKUP" != "true" ] && [ -x "$SCRIPT_DIR/backup_db.sh" ]; then
        log "Running pre-deploy backup..."
        "$SCRIPT_DIR/backup_db.sh" 2>&1 | while IFS= read -r line; do log "  $line"; done
    fi

    # Build the image
    log "Building image..."
    docker build -t "$IMAGE" -t "$IMAGE_NAME:latest" "$PROJECT_DIR" \
        2>&1 | while IFS= read -r line; do log "  build: $line"; done

    # Push to registry if configured
    if [ -n "$REGISTRY" ]; then
        log "Pushing to registry..."
        docker push "$IMAGE" 2>&1 | while IFS= read -r line; do log "  push: $line"; done
        docker push "$IMAGE_NAME:latest" 2>&1 | while IFS= read -r line; do log "  push: $line"; done
    fi

    # Run migrations first
    log "Running migrations..."
    docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" run --rm migrate \
        2>&1 | while IFS= read -r line; do log "  migrate: $line"; done

    # Deploy with the new image
    log "Starting services..."
    export STAGE0_IMAGE="$IMAGE"
    docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" up -d \
        --no-build --remove-orphans 2>&1 | while IFS= read -r line; do log "  $line"; done

    # Wait for health check
    log "Waiting for health check..."
    local RETRIES=0
    local MAX_RETRIES=30
    while [ $RETRIES -lt $MAX_RETRIES ]; do
        if curl -sf http://localhost:${PORT:-8098}/health >/dev/null 2>&1; then
            log "Health check passed"
            break
        fi
        RETRIES=$((RETRIES + 1))
        sleep 2
    done

    if [ $RETRIES -eq $MAX_RETRIES ]; then
        log "WARNING: Health check did not pass after ${MAX_RETRIES} attempts"
        log "Consider rolling back: ./scripts/deploy.sh rollback"
    fi

    # Save version state for rollback
    local old_current
    old_current=$(get_current_tag)
    if [ -n "$old_current" ]; then
        echo "$old_current" > "$PREVIOUS_TAG_FILE"
    fi
    echo "$TAG" > "$CURRENT_TAG_FILE"

    log "=== Deploy complete ==="
    log "Tag:      $TAG"
    log "Rollback: ./scripts/deploy.sh rollback"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "${1:-deploy}" in
    deploy)   cmd_deploy   ;;
    rollback) cmd_rollback ;;
    status)   cmd_status   ;;
    *)        fail "Unknown command: $1 (use: deploy|rollback|status)" ;;
esac
