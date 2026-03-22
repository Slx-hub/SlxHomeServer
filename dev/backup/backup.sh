#!/bin/bash
# Runs inside the backup container.
# - Mounts /:/host (read-only) and /backup are provided by the host via docker run.
# - Source paths are read from /etc/backup/backup-sources.conf and snapshot-sources.conf.
# - Logs are written to /backup/logs/ with 60-day rolling retention.

set -uo pipefail

LOG_DIR="/backup/logs"
LIVE_DIR="/backup/live"
SNAP_DIR="/backup/snapshots"
MAX_SNAPSHOTS=4
MAX_LOG_AGE_DAYS=60

mkdir -p "$LOG_DIR" "$LIVE_DIR" "$SNAP_DIR"

LOGFILE="$LOG_DIR/backup-$(date +%Y%m%d-%H%M%S).log"
ERRORS=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"
}

log "=== Backup started ==="
log "Date: $(date)"
log "Host: $(cat /host/etc/hostname 2>/dev/null || echo unknown)"

# ---------------------------------------------------------------------------
# Live backup — rsync (runs every day)
# ---------------------------------------------------------------------------
log "--- Live backup (rsync) ---"

while IFS= read -r src || [[ -n "$src" ]]; do
    # Skip comments and blank lines
    [[ "$src" =~ ^[[:space:]]*# ]] && continue
    src="${src//[[:space:]]/}"
    [[ -z "$src" ]] && continue

    host_src="/host${src}"
    dest="$LIVE_DIR${src}"

    if [[ ! -d "$host_src" ]]; then
        log "WARNING: Source not found, skipping: $host_src"
        continue
    fi

    mkdir -p "$dest"
    log "rsync: $src -> $dest"
    rsync -av --delete "$host_src/" "$dest/" >> "$LOGFILE" 2>&1
    RC=$?
    # exit 24 = some source files vanished mid-transfer; treat as warning
    if [[ $RC -eq 0 || $RC -eq 24 ]]; then
        log "rsync OK: $src (exit $RC)"
    else
        log "ERROR: rsync failed for $src (exit $RC)"
        ERRORS=$((ERRORS + 1))
    fi
done < /etc/backup/backup-sources.conf

# ---------------------------------------------------------------------------
# Weekly snapshot — tar (Tuesdays only, weekday number 2)
# ---------------------------------------------------------------------------
if [[ "$(date +%u)" -eq 2 ]]; then
    log "--- Weekly snapshot (tar) ---"

    SOURCES=()
    while IFS= read -r src || [[ -n "$src" ]]; do
        [[ "$src" =~ ^[[:space:]]*# ]] && continue
        src="${src//[[:space:]]/}"
        [[ -z "$src" ]] && continue

        host_src="/host${src}"
        if [[ -d "$host_src" ]]; then
            SOURCES+=("$host_src")
        else
            log "WARNING: Snapshot source not found, skipping: $host_src"
        fi
    done < /etc/backup/snapshot-sources.conf

    if [[ ${#SOURCES[@]} -gt 0 ]]; then
        SNAP_FILE="$SNAP_DIR/snapshot-$(date +%Y%m%d).tar.gz"
        log "Creating: $SNAP_FILE"
        tar -czf "$SNAP_FILE" "${SOURCES[@]}" >> "$LOGFILE" 2>&1
        RC=$?
        # exit 1 = some files changed while archiving; treat as warning
        if [[ $RC -eq 0 || $RC -eq 1 ]]; then
            log "Snapshot OK: $SNAP_FILE (exit $RC)"
        else
            log "ERROR: tar failed (exit $RC)"
            ERRORS=$((ERRORS + 1))
        fi

        # Keep only the last MAX_SNAPSHOTS, delete oldest if over limit
        mapfile -t SNAPS < <(ls -1t "$SNAP_DIR"/snapshot-*.tar.gz 2>/dev/null)
        if [[ ${#SNAPS[@]} -gt $MAX_SNAPSHOTS ]]; then
            for f in "${SNAPS[@]:$MAX_SNAPSHOTS}"; do
                log "Removing old snapshot: $(basename "$f")"
                rm "$f"
            done
        fi
    else
        log "WARNING: No valid snapshot sources found, skipping tar"
    fi
else
    log "--- Snapshot skipped (not Tuesday, weekday=$(date +%u)) ---"
fi

# ---------------------------------------------------------------------------
# Rolling log cleanup
# ---------------------------------------------------------------------------
log "--- Log cleanup (removing logs older than $MAX_LOG_AGE_DAYS days) ---"
find "$LOG_DIR" -name "backup-*.log" -mtime "+$MAX_LOG_AGE_DAYS" -delete

log "=== Backup complete (errors: $ERRORS) ==="
exit "$ERRORS"
