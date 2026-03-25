#!/bin/bash
# Host-side orchestration: mount drive → run backup container → unmount → reboot.
# Called by systemd backup.service. Must run as root.
#
# Usage: run-backup.sh [--full]
#   --full   Force rclone sync + tar snapshot regardless of day of week.

set -uo pipefail

# Pass --full through to the container if given
CONTAINER_ARGS=""
for arg in "$@"; do
    case "$arg" in
        --full) CONTAINER_ARGS="--full" ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
    logger -t backup "$*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ntfy notification config
NTFY_URL="http://localhost:42000"
NTFY_TOPIC="slx-homeserver-alerts"

ntfy_push() {
    local title="$1" message="$2" priority="${3:-default}" tags="${4:-}"
    curl -s --max-time 5 \
        -u "$NTFY_USER:$NTFY_PASSWORD" \
        -H "Title: $title" \
        -H "Priority: $priority" \
        ${tags:+-H "Tags: $tags"} \
        -d "$message" \
        "$NTFY_URL/$NTFY_TOPIC" > /dev/null 2>&1 \
        || log "WARNING: ntfy notification failed (server unreachable?)"
}

# Load machine-specific config (BACKUP_DEVICE) from the central repo .env
ROOT_ENV="$(cd "$SCRIPT_DIR/../.." && pwd)/.env"
if [[ ! -f "$ROOT_ENV" ]]; then
    log "ERROR: $ROOT_ENV not found. Create it from .env.example in the repo root."
    exit 1
fi
# shellcheck source=/dev/null
source "$ROOT_ENV"
: "${BACKUP_DEVICE:?Root .env must define BACKUP_DEVICE}"

log "=== Backup runner started ==="

# Mount backup drive
if mountpoint -q /backup; then
    log "WARNING: /backup already mounted — proceeding"
else
    log "Mounting $BACKUP_DEVICE at /backup..."
    mount "$BACKUP_DEVICE" /backup || { log "ERROR: Mount failed"; exit 1; }
fi

# Run backup container
log "Starting backup container..."
# Ensure rclone config dir exists on the host so the bind mount is always valid.
# Place rclone.conf here after running: sudo rclone config
mkdir -p /etc/rclone
BACKUP_EXIT=0
docker run --rm \
    --name backup-runner \
    --security-opt no-new-privileges \
    -v /:/host:ro \
    -v /backup:/backup \
    -v /etc/rclone:/etc/rclone:ro \
    -v /data/media/photos:/data/media/photos \
    -v "$SCRIPT_DIR/backup-sources.conf:/etc/backup/backup-sources.conf:ro" \
    -v "$SCRIPT_DIR/snapshot-sources.conf:/etc/backup/snapshot-sources.conf:ro" \
    slx-backup $CONTAINER_ARGS || BACKUP_EXIT=$?

log "Container exited with code $BACKUP_EXIT"

# Unmount backup drive
log "Unmounting /backup..."
umount /backup || log "WARNING: Failed to unmount /backup"

if [[ $BACKUP_EXIT -ne 0 ]]; then
    log "ERROR: Backup failed — skipping reboot"
    ntfy_push "Backup Failed" "Backup on $(hostname) finished with errors (exit $BACKUP_EXIT). Check logs in /backup/logs." "high" "warning"
    exit "$BACKUP_EXIT"
fi

# ---- TEST BLOCK: remove once notifications are confirmed working ----
ntfy_push "Backup OK" "Backup on $(hostname) completed successfully." "default" "white_check_mark"
# ---- END TEST BLOCK ----

log "Backup successful — initiating reboot"
# systemctl reboot is non-blocking; the script exits 0 cleanly before the reboot kicks in
systemctl reboot
exit 0
