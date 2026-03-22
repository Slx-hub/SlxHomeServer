#!/bin/bash
# Registers the backup service and timer on this machine.
# Usage: sudo ./install.sh
# Safe to re-run — it will overwrite previously installed unit files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="$(cd "$SCRIPT_DIR/../.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo ./install.sh)" >&2
    exit 1
fi

echo "=== Backup install ==="
echo "Repo path : $REPO_PATH"
echo "Script dir: $SCRIPT_DIR"
echo ""

# ── 1. Ensure backup.env exists ─────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/backup.env" ]]; then
    cp "$SCRIPT_DIR/backup.env.example" "$SCRIPT_DIR/backup.env"
    echo "Created backup.env from example."
    echo ""
    echo "  !! ACTION REQUIRED: Edit $SCRIPT_DIR/backup.env"
    echo "  !!   Set BACKUP_DEVICE to your drive's UUID."
    echo "  !!   Find it with: blkid /dev/sdX"
    echo ""
fi

# ── 2. Ensure /backup mount point exists ────────────────────────────────────
mkdir -p /backup
echo "Mount point /backup: OK"

# ── 3. Build Docker image ────────────────────────────────────────────────────
echo "Building Docker image slx-backup..."
docker build -t slx-backup "$SCRIPT_DIR"
echo "Image built: OK"

# ── 4. Make wrapper scripts executable ──────────────────────────────────────
chmod +x "$SCRIPT_DIR/run-backup.sh"

# ── 5. Install systemd service (substitute repo path into template) ──────────
sed "s|@@REPO_PATH@@|$REPO_PATH|g" \
    "$SCRIPT_DIR/backup.service.template" \
    > "$SYSTEMD_DIR/backup.service"
echo "Installed: $SYSTEMD_DIR/backup.service"

# ── 6. Install systemd timer ─────────────────────────────────────────────────
cp "$SCRIPT_DIR/backup.timer" "$SYSTEMD_DIR/backup.timer"
echo "Installed: $SYSTEMD_DIR/backup.timer"

# ── 7. Ensure Docker starts on boot ──────────────────────────────────────────
systemctl enable docker
echo "Enabled: docker.service"

# ── 8. Enable and start the timer ────────────────────────────────────────────
systemctl daemon-reload
systemctl enable backup.timer
systemctl start backup.timer
echo "Enabled and started: backup.timer"

echo ""
echo "=== Install complete ==="
echo ""
systemctl list-timers backup.timer --no-pager
echo ""
echo "Next steps:"
echo "  • Verify backup.env has the correct BACKUP_DEVICE"
echo "  • Manual test run: sudo systemctl start backup.service"
echo "  • Follow logs:     journalctl -fu backup.service"
