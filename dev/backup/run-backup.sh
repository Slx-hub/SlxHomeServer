#!/bin/bash
# Host-side orchestration: mount drive → run backup container → unmount → reboot.
# Called by systemd backup.service. Must run as root.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
    logger -t backup "$*"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
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
BACKUP_EXIT=0
docker run --rm \
    --name backup-runner \
    --security-opt no-new-privileges \
    -v /:/host:ro \
    -v /backup:/backup \
    -v "$SCRIPT_DIR/backup-sources.conf:/etc/backup/backup-sources.conf:ro" \
    -v "$SCRIPT_DIR/snapshot-sources.conf:/etc/backup/snapshot-sources.conf:ro" \
    slx-backup || BACKUP_EXIT=$?

log "Container exited with code $BACKUP_EXIT"

# Unmount backup drive
log "Unmounting /backup..."
umount /backup || log "WARNING: Failed to unmount /backup"

if [[ $BACKUP_EXIT -ne 0 ]]; then
    log "ERROR: Backup failed — skipping reboot"
    exit "$BACKUP_EXIT"
fi

log "Backup successful — initiating reboot"
# systemctl reboot is non-blocking; the script exits 0 cleanly before the reboot kicks in
systemctl reboot
exit 0
