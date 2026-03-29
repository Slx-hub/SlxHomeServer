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

ntfy_push() {
    local title="$1" message="$2" priority="${3:-default}" tags="${4:-}"
    curl -s --max-time 5 \
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

# Record wall-clock start so we can report duration in the notification
START_TIME=$(date +%s)

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

# ── Post-run stats ────────────────────────────────────────────────────────
ELAPSED=$(( $(date +%s) - START_TIME ))
DURATION="$(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s"

# Most recent log written by the container
LATEST_LOG=$(ls -1t /backup/logs/backup-*.log 2>/dev/null | head -1)

# Was this a weekly run?
IS_WEEKLY=false
if [[ "$(date +%u)" -eq 2 || -n "$CONTAINER_ARGS" ]]; then
    IS_WEEKLY=true
fi

# Total files transferred across all rsync sources (from rsync summary lines)
RSYNC_TRANSFERRED=0
if [[ -n "$LATEST_LOG" ]]; then
    RSYNC_TRANSFERRED=$(grep -oP 'Number of regular files transferred: \K[\d,]+' "$LATEST_LOG" \
        | tr -d ',' | awk '{s+=$1} END {print s+0}')
fi

# Snapshot size (weekly runs only)
SNAPSHOT_LINE=""
if [[ "$IS_WEEKLY" == true ]]; then
    SNAP_FILE="/backup/snapshots/snapshot-$(date +%Y%m%d).tar.gz"
    if [[ -f "$SNAP_FILE" ]]; then
        SNAP_SIZE=$(du -sh "$SNAP_FILE" 2>/dev/null | cut -f1)
        SNAPSHOT_LINE=$'\n'"Snapshot: ${SNAP_SIZE}"
    fi
fi

# Unmount backup drive
log "Unmounting /backup..."
umount /backup || log "WARNING: Failed to unmount /backup"

if [[ $BACKUP_EXIT -ne 0 ]]; then
    log "ERROR: Backup failed — skipping reboot"

    # Pull the first few ERROR lines from the log as context
    ERROR_LINES=""
    if [[ -n "$LATEST_LOG" ]]; then
        ERROR_LINES=$(grep 'ERROR:' "$LATEST_LOG" | head -5 | sed 's/\[.*\] //' | tr '\n' '|' | sed 's/|$//' | tr '|' '\n')
    fi
    [[ -z "$ERROR_LINES" ]] && ERROR_LINES="(no ERROR lines found in log — check /backup/logs)"

    ntfy_push "Backup Failed" "Duration: ${DURATION} | Weekly: ${IS_WEEKLY} | Files synced: ${RSYNC_TRANSFERRED}${SNAPSHOT_LINE}
--- Errors ---
${ERROR_LINES}" "high" "warning"
    exit "$BACKUP_EXIT"
fi

ntfy_push "Backup OK" "Duration: ${DURATION} | Weekly: ${IS_WEEKLY} | Files synced: ${RSYNC_TRANSFERRED}${SNAPSHOT_LINE}" "default" "white_check_mark"

log "Backup successful — initiating reboot"
# systemctl reboot is non-blocking; the script exits 0 cleanly before the reboot kicks in
systemctl reboot
exit 0
