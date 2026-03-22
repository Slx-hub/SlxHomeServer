#!/bin/bash
# Runs inside the backup container.
# - Mounts /:/host (read-only) and /backup are provided by the host via docker run.
# - Source paths are read from /etc/backup/backup-sources.conf and snapshot-sources.conf.
# - Logs are written to /backup/logs/ with 60-day rolling retention.
#
# Usage: backup.sh [--full]
#   --full   Force rclone sync + tar snapshot regardless of day of week.
#            Normally these only run on Tuesdays.

set -uo pipefail

# Parse arguments
FORCE_FULL=false
for arg in "$@"; do
    case "$arg" in
        --full) FORCE_FULL=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

# Run weekly steps if it's Tuesday OR --full was passed
RUN_WEEKLY=false
if [[ "$(date +%u)" -eq 2 || "$FORCE_FULL" == true ]]; then
    RUN_WEEKLY=true
fi

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
# Google Photos sync — rclone copy (Tuesdays only, runs before snapshot)
# Failures are logged as warnings and do NOT affect the exit code; backup
# and reboot proceed regardless.
# ---------------------------------------------------------------------------
if [[ "$RUN_WEEKLY" == true ]]; then
    log "--- Google Photos sync (rclone) ---"
    RCLONE_CONF="/etc/rclone/rclone.conf"
    PHOTOS_DEST="/data/media/photos"

    if [[ ! -f "$RCLONE_CONF" ]]; then
        log "WARNING: $RCLONE_CONF not found — skipping Google Photos sync"
        log "  Setup: run 'rclone config' as root, create a remote named 'gphotos'"
        log "  using the 'Google Photos' backend, then place the config at $RCLONE_CONF on the host"
    else
        mkdir -p "$PHOTOS_DEST"
        log "rclone copy gphotos: -> $PHOTOS_DEST"
        rclone copy \
            --config "$RCLONE_CONF" \
            --log-level INFO \
            gphotos: "$PHOTOS_DEST" \
            >> "$LOGFILE" 2>&1
        RC=$?
        if [[ $RC -eq 0 ]]; then
            log "rclone OK (exit 0)"
        else
            log "WARNING: rclone failed (exit $RC) — continuing backup"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Weekly snapshot — tar (Tuesdays only, weekday number 2)
# ---------------------------------------------------------------------------
if [[ "$RUN_WEEKLY" == true ]]; then
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
    log "--- Snapshot skipped (not Tuesday and --full not passed) ---"
fi

# ---------------------------------------------------------------------------
# Rolling log cleanup
# ---------------------------------------------------------------------------
log "--- Log cleanup (removing logs older than $MAX_LOG_AGE_DAYS days) ---"
find "$LOG_DIR" -name "backup-*.log" -mtime "+$MAX_LOG_AGE_DAYS" -delete

log "=== Backup complete (errors: $ERRORS) ==="
exit "$ERRORS"
